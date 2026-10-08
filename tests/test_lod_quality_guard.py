"""Regression checks for measured-floor publication guards and read-only exported masks."""

from __future__ import annotations

import json
import shutil
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.optimization.io import write_model
from codex_blender_modeler.optimization.models import (
    HashedArtifact,
    LODManifest,
    OptimizationPlan,
    SourceProvenance,
)
from codex_blender_modeler.optimization.optimizer import _lod_manifest
from codex_blender_modeler.optimization.preflight import _lod_feasibility_warnings
from codex_blender_modeler.optimization.profiles import create_builtin_profile
from codex_blender_modeler.packaging.lod_quality import (
    _camera,
    _json,
    _regular_path,
    inspect_exported_lod_quality,
)
from codex_blender_modeler.packaging.models import ExportPackageManifest, PackageFile
from codex_blender_modeler.packaging.service import _require_lod_quality_for_publication
from codex_blender_modeler.workspace import sha256_file

NOW = datetime(2026, 9, 30, tzinfo=UTC)
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
MATRICES = {
    "canonical": IDENTITY,
    "front": [1, 0, 0, 0, 0, 0, -1, -4, 0, 1, 0, 0, 0, 0, 0, 1],
    "right": [0, 0, 1, 4, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1],
    "top": IDENTITY,
}


def _write(path: Path, payload: object) -> None:
    """Write deterministic owned fixture bytes, never production evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _artifact(path: Path, root: Path, kind: str) -> HashedArtifact:
    """Bind an exact fixture file to a job-relative artifact."""

    return HashedArtifact(
        id=path.name.replace("_", "."),
        kind=kind,
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
    )


def _fixture(tmp_path: Path, *, disabled: bool = False) -> dict:
    """Build synthetic immutable receipts without claiming native Blender execution."""

    root = tmp_path / "job"
    run = root / "optimization/runs/run-001"
    blend = run / "optimized/scene.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"fixture derived mesh; not native execution")
    source = SourceProvenance(
        scene_spec=HashedArtifact(
            id="scene", kind="scene_spec", path="analysis/scene_spec.json", sha256="a" * 64
        ),
        blend=HashedArtifact(id="blend", kind="blend", path="blender/scene.blend", sha256="b" * 64),
        source_fingerprint="c" * 64,
        build_fingerprint="d" * 64,
    )
    profile = create_builtin_profile(
        "lod_test", "portable_gltf", "static_prop", lod_mode="disabled" if disabled else "enabled"
    )
    profile_path = root / "asset_profiles/portable_gltf.json"
    profile_path.parent.mkdir(parents=True)
    write_model(profile_path, profile)
    records = [
        {
            "name": f"body__LOD{level}",
            "type": "MESH",
            "semantic_id": "body",
            "asset_role": "render" if level == 0 else "lod",
            "lod_level": level,
            "bbox_world": {"min": [0, 0, 0], "max": [1, 1, 1]},
            "topology": {"triangles_estimated": count},
            "material_ids": ["mat.body"],
        }
        for level, count in enumerate([10] if disabled else [10, 6, 3])
    ]
    lod = _lod_manifest(root, "run-001", profile, source, {"objects": records}, blend)
    write_model(run / "lod_manifest.json", lod)
    _write(run / "mesh_preflight_report.json", {})
    plan = OptimizationPlan(
        plan_id="plan.run-001",
        job_id="lod_test",
        profile_id="portable_gltf",
        profile_artifact=_artifact(profile_path, root, "asset_profile"),
        preflight_report=_artifact(run / "mesh_preflight_report.json", root, "preflight_report"),
        source=source,
        status="running",
        approved_at=NOW,
    )
    write_model(run / "execution_plan.json", plan)
    raw = {
        "schema_version": "0.7.0",
        "kind": "optimized_asset_manifest",
        "ok": True,
        "plan_sha256": sha256_file(run / "execution_plan.json"),
        "profile_sha256": sha256_file(profile_path),
        "derived": {"blend_sha256": sha256_file(blend)},
        "source": {"build_fingerprint": source.build_fingerprint},
    }
    _write(run / "optimized_asset_evidence.json", raw)
    plan = plan.model_copy(
        update={
            "status": "complete",
            "completed_at": NOW,
            "output_manifests": [
                _artifact(run / "lod_manifest.json", root, "lod_manifest"),
                _artifact(run / "execution_plan.json", root, "optimization_plan"),
                _artifact(run / "optimized_asset_evidence.json", root, "other"),
                _artifact(blend, root, "blend"),
            ],
        }
    )
    write_model(run / "optimization_plan.json", plan)
    package_root = root / "exports/packages/portable_gltf/package-001"
    metadata = package_root / "metadata"
    metadata.mkdir(parents=True)
    for name in [
        "optimization_plan.json",
        "execution_plan.json",
        "lod_manifest.json",
        "optimized_asset_evidence.json",
    ]:
        shutil.copyfile(run / name, metadata / name)
    shutil.copyfile(profile_path, metadata / "asset_profile.json")
    nodes = [
        {
            "name": record["name"],
            "mesh": 0,
            "extras": {
                "cbm_id": "body",
                "cbm_asset_role": record["asset_role"],
                "cbm_lod_level": record["lod_level"],
            },
        }
        for record in records
    ]
    glb_json = json.dumps(
        {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": list(range(len(nodes)))}],
            "nodes": nodes,
            "meshes": [{"primitives": []}],
        }
    ).encode()
    glb_json += b" " * (-len(glb_json) % 4)
    primary = package_root / "asset.glb"
    primary.write_bytes(
        struct.pack("<5I", 0x46546C67, 2, 20 + len(glb_json), len(glb_json), 0x4E4F534A) + glb_json
    )
    export = {
        "schema_version": "0.7.0",
        "ok": True,
        "kind": "portable_export_evidence",
        "format": "glb",
        "content_mode": "full_evidence",
        "primary_file": "asset.glb",
        "files": [
            {
                "path": "asset.glb",
                "sha256": sha256_file(primary),
                "size_bytes": primary.stat().st_size,
            }
        ],
        "source": {
            "job_id": "lod_test",
            "plan_sha256": raw["plan_sha256"],
            "build_fingerprint": source.build_fingerprint,
            "source_build_fingerprint": source.build_fingerprint,
            "optimized_blend_sha256": sha256_file(blend),
            "material_conversion_plan_sha256": None,
        },
    }
    _write(package_root / "export_evidence.json", export)
    files = [
        PackageFile(
            id=f"file.{index}",
            kind="primary_asset" if path == primary else "metadata",
            path=path.relative_to(root).as_posix(),
            sha256=sha256_file(path),
            byte_size=path.stat().st_size,
            media_type="application/octet-stream",
        )
        for index, path in enumerate(sorted(package_root.rglob("*")))
        if path.is_file()
    ]
    package = ExportPackageManifest(
        package_id="package-001",
        job_id="lod_test",
        run_id="run-001",
        profile_id="portable_gltf",
        source=source,
        status="complete",
        package_root=package_root.relative_to(root).as_posix(),
        optimization_plan=_artifact(metadata / "optimization_plan.json", root, "optimization_plan"),
        files=files,
        primary_file_id=next(item.id for item in files if item.kind == "primary_asset"),
        semantic_ids=["body"],
        material_ids=["mat.body"],
        created_at=NOW,
        completed_at=NOW,
    )
    manifest = package_root / "package_manifest.json"
    write_model(manifest, package)
    return {
        "root": root,
        "run": run,
        "profile": profile,
        "lod": lod,
        "manifest": manifest,
        "primary": primary,
        "render_root": tmp_path / "renders",
    }


def _render_fixture(fixture: dict, *, rectangle: tuple = (100, 100, 700, 700)) -> None:
    """Create declared mask fixtures; these test recomputation, not renderer attestation."""

    root = fixture["render_root"]
    root.mkdir()
    plan = {
        "kind": "bounded_independent_exported_lod_silhouette_plan",
        "primary_asset_sha256": sha256_file(fixture["primary"]),
        "blender_version": "5.0.1",
        "engine": "BLENDER_WORKBENCH",
        "geometry_only_flat_opaque_override": True,
        "resolution": [1024, 1024],
        "render_aa": "16",
        "mask_alpha_threshold": 128,
        "minimum_reference_foreground_pixels": 1024,
        "levels": [0, 1, 2],
        "profile_floors": {"1": 0.98, "2": 0.95},
        "views": list(MATRICES),
        "scopes": ["whole_asset"],
        "maximum_render_count": 12,
        "canonical_camera_matrix": IDENTITY,
        "canonical_camera_lens_mm": 50,
        "native_lod_manifest_unchanged": True,
        "orthographic_camera_basis": "Fixture declared cardinal camera basis",
    }
    _write(root / "plan.json", plan)
    records = []
    for view, matrix in MATRICES.items():
        for level in range(3):
            path = root / f"{view}-{level}.png"
            image = Image.new("RGBA", (1024, 1024))
            ImageDraw.Draw(image).rectangle(rectangle, fill=(255, 255, 255, 255))
            image.save(path)
            records.append(
                {
                    "scope": "whole_asset",
                    "view": view,
                    "level": level,
                    "selected_objects": [f"body__LOD{level}"],
                    "camera": {
                        "matrix_world": matrix,
                        "type": "ORTHO",
                        "lens": 50,
                        "ortho_scale": 2,
                    },
                    "path": path.name,
                    "sha256": sha256_file(path),
                }
            )
    _write(
        root / "render_manifest.json",
        {
            "plan_sha256": sha256_file(root / "plan.json"),
            "canonical_or_package_saved": False,
            "records": records,
            "elapsed_seconds": 0,
        },
    )


def _inspect(fixture: dict, *, rendered: bool = True) -> dict:
    """Select exact current fixture digests through the public read-only Python helper."""

    root = fixture["render_root"]
    return inspect_exported_lod_quality(
        fixture["manifest"],
        package_manifest_sha256=sha256_file(fixture["manifest"]),
        **(
            {
                "render_root": root,
                "render_plan_sha256": sha256_file(root / "plan.json"),
                "render_manifest_sha256": sha256_file(root / "render_manifest.json"),
            }
            if rendered
            else {}
        ),
    )


def _mutate_render(fixture: dict, change) -> None:
    """Rehash changed fixture declarations to test semantic checks independently of hashes."""

    path = fixture["render_root"] / "render_manifest.json"
    payload = json.loads(path.read_text())
    change(payload)
    _write(path, payload)


@pytest.mark.parametrize("value", [0.949999, 0.93, 0])
def test_publication_rejects_known_failed_optional_lod(tmp_path: Path, value: float) -> None:
    """Read a historical scalar manifest but reject newly publishing its measured failure."""

    f = _fixture(tmp_path)
    payload = f["lod"].model_dump(mode="json")
    payload["entries"][2]["silhouette_iou"] = value
    lod = LODManifest.model_validate(payload)
    with pytest.raises(RuntimeError, match="Known LOD silhouette failure"):
        _require_lod_quality_for_publication(f["root"], f["run"], lod, f["profile"])


def test_publication_preserves_unknown_and_disabled_semantics(tmp_path: Path) -> None:
    """Legacy null metrics remain unknown and explicitly disabled derived checks are N/A."""

    f = _fixture(tmp_path / "enabled")
    before = f["lod"].model_dump_json()
    warnings = _require_lod_quality_for_publication(f["root"], f["run"], f["lod"], f["profile"])
    assert "unverified" in warnings[0] and before == f["lod"].model_dump_json()
    disabled = _fixture(tmp_path / "disabled", disabled=True)
    warnings = _require_lod_quality_for_publication(
        disabled["root"], disabled["run"], disabled["lod"], disabled["profile"]
    )
    assert "not applicable" in warnings[0] and disabled["lod"].entries[0].silhouette_iou is None
    result = _inspect(disabled, rendered=False)
    assert result["diagnostic_status"] == "not_applicable" and result["comparisons"] == []


@pytest.mark.parametrize("mutation", ["false_verified", "mixed_hash", "mixed_path", "levels"])
def test_publication_rejects_inconsistent_manifest(tmp_path: Path, mutation: str) -> None:
    """New publication cannot borrow foreign meshes or call missing measurements verified."""

    f = _fixture(tmp_path)
    payload = f["lod"].model_dump(mode="json")
    if mutation == "false_verified":
        payload.update(quality_status="verified", unverified_checks=[])
    elif mutation == "mixed_hash":
        payload["entries"][1]["mesh"]["sha256"] = "0" * 64
    elif mutation == "mixed_path":
        payload["entries"][1]["mesh"]["path"] = "optimization/runs/other/optimized/scene.blend"
    else:
        payload["entries"] = payload["entries"][:2]
    with pytest.raises(RuntimeError):
        _require_lod_quality_for_publication(
            f["root"], f["run"], LODManifest.model_validate(payload), f["profile"]
        )


def test_absent_and_valid_diagnostics_are_not_native_verification(tmp_path: Path) -> None:
    """No evidence is unknown; supplied passing masks only pass their declared discrete coverage."""

    f = _fixture(tmp_path)
    assert _inspect(f, rendered=False)["diagnostic_status"] == "unverified"
    _render_fixture(f)
    before = {p: sha256_file(p) for p in f["manifest"].parent.rglob("*") if p.is_file()}
    result = _inspect(f)
    assert result["schema_version"] == "0.1.0"
    assert result["diagnostic_status"] == "passed_for_declared_coverage"
    assert result["passed_count"] == 8 and result["native_quality_verified_by_this_check"] is False
    assert result["renderer_provenance"] == "declared_not_independently_attested"
    assert result["coverage"]["isolated_semantic_coverage_complete"] is False
    assert before == {p: sha256_file(p) for p in before}


@pytest.mark.parametrize(
    "rectangle,expected", [((0, 0, 700, 700), "unverified"), ((100, 100, 110, 110), "unverified")]
)
def test_clipped_and_tiny_masks_cannot_pass(
    tmp_path: Path, rectangle: tuple, expected: str
) -> None:
    """Identical masks still remain unavailable when clipped or below fixed minimum support."""

    f = _fixture(tmp_path)
    _render_fixture(f, rectangle=rectangle)
    result = _inspect(f)
    assert result["diagnostic_status"] == expected
    assert result["unavailable_count"] == 8 and result["passed_count"] == 0


def test_measured_bad_mask_fails_unchanged_floor(tmp_path: Path) -> None:
    """Recompute a real pixel loss rather than trusting a supplied passing summary."""

    f = _fixture(tmp_path)
    _render_fixture(f)
    path = f["render_root"] / "front-2.png"
    image = Image.new("RGBA", (1024, 1024))
    ImageDraw.Draw(image).rectangle((100, 100, 650, 700), fill=(255, 255, 255, 255))
    image.save(path)
    _mutate_render(
        f,
        lambda data: next(row for row in data["records"] if row["path"] == path.name).update(
            sha256=sha256_file(path)
        ),
    )
    result = _inspect(f)
    assert result["diagnostic_status"] == "failed" and result["failed_count"] == 1
    failed = next(row for row in result["comparisons"] if row["status"] == "failed")
    assert failed["profile_floor"] == 0.95 and failed["iou"] < 0.95


@pytest.mark.parametrize(
    "mutation",
    [
        "mask_hash",
        "objects",
        "camera",
        "direction",
        "missing",
        "duplicate",
        "foreign_level",
        "mask_dimensions",
    ],
)
def test_bad_mask_evidence_fails_closed(tmp_path: Path, mutation: str) -> None:
    """Reject tampered, mixed, relabeled, missing or unsupported declared mask provenance."""

    f = _fixture(tmp_path)
    _render_fixture(f)

    def change(data: dict) -> None:
        """Apply one independent negative fixture mutation."""
        row = data["records"][4]
        if mutation == "mask_hash":
            row["sha256"] = "0" * 64
        elif mutation == "objects":
            row["selected_objects"] = ["body__LOD2"]
        elif mutation == "camera":
            row["camera"]["ortho_scale"] = 3
        elif mutation == "direction":
            for item in data["records"]:
                if item["view"] == "right":
                    item["camera"]["matrix_world"] = MATRICES["front"]
        elif mutation == "missing":
            data["records"].pop()
        elif mutation == "duplicate":
            data["records"][1] = data["records"][0]
        elif mutation == "foreign_level":
            row["level"] = 3
        else:
            p = f["render_root"] / row["path"]
            Image.new("RGBA", (10, 10)).save(p)
            row["sha256"] = sha256_file(p)

    _mutate_render(f, change)
    with pytest.raises(ValueError):
        _inspect(f)


@pytest.mark.parametrize("mutation", ["export_source", "profile", "lod_source", "output_hash"])
def test_rehashed_cross_source_package_still_rejected(tmp_path: Path, mutation: str) -> None:
    """A fresh outer package digest cannot repair inconsistent internal source bindings."""

    f = _fixture(tmp_path)
    relative = {
        "export_source": "export_evidence.json",
        "profile": "metadata/asset_profile.json",
        "lod_source": "metadata/lod_manifest.json",
        "output_hash": "metadata/optimization_plan.json",
    }[mutation]
    path = f["manifest"].parent / relative
    data = json.loads(path.read_text())
    if mutation == "export_source":
        data["source"]["build_fingerprint"] = "0" * 64
    elif mutation == "profile":
        data["lod"]["targets"][1]["minimum_silhouette_iou"] = 0.90
    elif mutation == "lod_source":
        data["entries"][1]["mesh"]["sha256"] = "0" * 64
    else:
        data["output_manifests"][0]["sha256"] = "0" * 64
    _write(path, data)
    package = json.loads(f["manifest"].read_text())
    receipt = next(item for item in package["files"] if item["path"].endswith(relative))
    receipt.update(sha256=sha256_file(path), byte_size=path.stat().st_size)
    _write(f["manifest"], package)
    with pytest.raises(ValueError):
        _inspect(f, rendered=False)


def test_paths_json_and_camera_are_strict(tmp_path: Path) -> None:
    """Reject ancestor links, duplicate/nonfinite JSON, and nonrigid camera declarations."""

    real = tmp_path / "real/sub"
    real.mkdir(parents=True)
    _write(real / "data.json", {})
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(ValueError, match="link"):
        _regular_path(alias / "sub", "data.json")
    for text in ['{"x":1,"x":2}', '{"x":NaN}']:
        (real / "data.json").write_text(text)
        with pytest.raises(ValueError):
            _json(real / "data.json")
    with pytest.raises(ValueError, match="rigid"):
        _camera({"matrix_world": [2, *IDENTITY[1:]], "type": "ORTHO", "lens": 50, "ortho_scale": 2})


def test_closed_tiny_cap_warning_is_conditional_and_never_changes_policy() -> None:
    """Warn from closed-topology evidence without claiming measured volume or relaxing caps."""

    profile = create_builtin_profile("lod_test", "portable_gltf", "static_prop")
    record = {
        "type": "MESH",
        "semantic_id": "gem",
        "topology": {
            "manifold_closed": True,
            "triangles_estimated": 8,
            "boundary_edge_count": 0,
            "overused_edge_count": 0,
            "degenerate_face_count": 0,
            "loose_edge_count": 0,
            "loose_vertex_count": 0,
            "non_finite_vertex_count": 0,
        },
    }
    before = profile.model_dump_json()
    warnings = _lod_feasibility_warnings({"objects": [record]}, profile, "preflight.json")
    assert len(warnings) == 1 and "cap is 3" in warnings[0].message
    assert "If this source encloses volume" in warnings[0].message
    assert before == profile.model_dump_json()
    record["topology"]["manifold_closed"] = False
    assert _lod_feasibility_warnings({"objects": [record]}, profile, "preflight.json") == []
    record["topology"] = {"triangles_estimated": 8}
    assert _lod_feasibility_warnings({"objects": [record]}, profile, "preflight.json") == []


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("plan.json", "schema_version", "999.0.0"),
        ("plan.json", "unknown_field", True),
        ("render_manifest.json", "schema_version", "999.0.0"),
        ("render_manifest.json", "passed", True),
    ],
)
def test_unknown_diagnostic_contract_is_rejected(
    tmp_path: Path, target: str, field: str, value: object
) -> None:
    """Reject unknown version or field combinations without migrating historical diagnostics."""

    f = _fixture(tmp_path)
    _render_fixture(f)
    path = f["render_root"] / target
    data = json.loads(path.read_text())
    data[field] = value
    _write(path, data)
    if target == "plan.json":
        _mutate_render(f, lambda item: item.update(plan_sha256=sha256_file(path)))
    with pytest.raises(ValueError, match="fields or schema"):
        _inspect(f)


def test_explicit_digest_and_disabled_proof_mismatch_fail_closed(tmp_path: Path) -> None:
    """Require exact selected bytes and reject reduced-level proof borrowed by a no-LOD package."""

    f = _fixture(tmp_path, disabled=True)
    with pytest.raises(ValueError, match="SHA-256 changed"):
        inspect_exported_lod_quality(f["manifest"], package_manifest_sha256="0" * 64)
    _render_fixture(f)
    with pytest.raises(ValueError, match="Disabled optional LODs"):
        _inspect(f)
