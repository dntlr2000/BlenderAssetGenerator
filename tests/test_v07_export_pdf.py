from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from pypdf import PdfReader

from codex_blender_modeler.reporting import (
    collect_job_report_payload,
    generate_job_pdf_report,
)
from codex_blender_modeler.workspace import sha256_file


def _write_json(path: Path, payload: dict) -> None:
    """Write one deterministic JSON object fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    """Write one deterministic report image fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (96, 64), color=color).save(path)


def _artifact(artifact_id: str, kind: str, path: str) -> dict:
    """Create one compact hashed-artifact record for report fixtures."""

    return {"id": artifact_id, "kind": kind, "path": path, "sha256": "1" * 64}


def _source_provenance() -> dict:
    """Create one compact immutable V0.7 source-provenance fixture."""

    return {
        "scene_spec": _artifact("scene", "scene_spec", "analysis/scene_spec.json"),
        "blend": _artifact("blend", "blend", "blender/scene.blend"),
        "source_fingerprint": "4" * 64,
        "build_fingerprint": "2" * 64,
        "geometry_payloads": [],
        "material_plan": None,
        "texture_manifests": [],
    }


def _seed_export_report_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create one isolated V0.7 run and package with all export report evidence."""

    workspace = tmp_path / "workspaces"
    root = workspace / "export_pdf_test"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = root / "input" / "reference.png"
    preview = root / "renders" / "preview.png"
    _write_png(reference, (80, 120, 180))
    _write_png(preview, (100, 140, 90))
    _write_json(
        root / "job.json",
        {
            "job_id": "export_pdf_test",
            "mode": "concept",
            "project_version_created": "0.7.0",
            "reference_path": str(reference),
            "reference_sha256": sha256_file(reference),
        },
    )
    _write_json(
        root / "analysis" / "scene_spec.json",
        {"schema_version": "0.2.0", "job_id": "export_pdf_test", "objects": []},
    )
    profile_path = root / "asset_profiles" / "portable_gltf.json"
    _write_json(
        profile_path,
        {
            "schema_version": "0.7.0",
            "profile_id": "portable_gltf",
            "job_id": "export_pdf_test",
            "asset_kind": "static_environment",
            "primary_format": "glb",
            "units": "meters",
            "up_axis": "+Y",
            "forward_axis": "-Z",
        },
    )
    run_id = "run-001"
    run = root / "optimization" / "runs" / run_id
    source = _source_provenance()
    _write_json(
        run / "optimization_plan.json",
        {
            "schema_version": "0.7.0",
            "plan_id": "plan-001",
            "job_id": "export_pdf_test",
            "profile_id": "portable_gltf",
            "profile_artifact": {
                "id": "profile",
                "kind": "asset_profile",
                "path": "asset_profiles/portable_gltf.json",
                "sha256": sha256_file(profile_path),
            },
            "source": source,
            "status": "complete",
            "directives": [],
        },
    )
    _write_json(
        run / "mesh_preflight_report.json",
        {
            "schema_version": "0.7.0",
            "report_id": "preflight-001",
            "job_id": "export_pdf_test",
            "profile_id": "portable_gltf",
            "source": source,
            "status": "passed",
            "ok": True,
            "passed": 4,
            "warnings": 1,
            "failed": 0,
            "checks": [
                {
                    "id": "uv-warning",
                    "target_id": "asset.body",
                    "category": "uv",
                    "status": "warning",
                    "message": "UV1 padding is near the configured threshold.",
                }
            ],
            "meshes": [{"target_id": "asset.body"}],
            "canonical_unchanged": True,
        },
    )
    _write_json(
        run / "lod_manifest.json",
        {
            "schema_version": "0.7.0",
            "manifest_id": "lod-001",
            "job_id": "export_pdf_test",
            "run_id": run_id,
            "profile_id": "portable_gltf",
            "status": "complete",
            "entries": [
                {
                    "target_id": "asset.body",
                    "level": 0,
                    "source_triangle_count": 1000,
                    "triangle_count": 1000,
                    "triangle_ratio": 1.0,
                    "silhouette_iou": 1.0,
                },
                {
                    "target_id": "asset.body",
                    "level": 1,
                    "source_triangle_count": 1000,
                    "triangle_count": 600,
                    "triangle_ratio": 0.6,
                    "silhouette_iou": 0.985,
                },
            ],
            "canonical_unchanged": True,
        },
    )
    _write_json(
        run / "collision_manifest.json",
        {
            "schema_version": "0.7.0",
            "manifest_id": "collision-001",
            "job_id": "export_pdf_test",
            "run_id": run_id,
            "profile_id": "portable_gltf",
            "strategy": "box",
            "status": "complete",
            "entries": [
                {
                    "collider_id": "collider.asset.body",
                    "target_id": "asset.body",
                    "strategy": "box",
                    "hull_count": 1,
                    "triangle_count": 12,
                    "dimensions": [2.0, 3.0, 4.0],
                }
            ],
            "canonical_unchanged": True,
        },
    )
    _write_json(
        run / "uv_manifest.json",
        {
            "schema_version": "0.7.0",
            "manifest_id": "uv-001",
            "job_id": "export_pdf_test",
            "run_id": run_id,
            "profile_id": "portable_gltf",
            "status": "complete",
            "records": [
                {
                    "target_id": "asset.body",
                    "uv_set": "UVMap",
                    "purpose": "material",
                    "generated": False,
                    "overlap_fraction": 0.0,
                    "degenerate_face_count": 0,
                    "texel_density_px_m": 512.0,
                    "padding_px": 8,
                }
            ],
            "canonical_unchanged": True,
        },
    )
    package_id = "package-001"
    package_root = root / "exports" / "packages" / "portable_gltf" / package_id
    _write_json(
        package_root / "texture_pack_manifest.json",
        {
            "schema_version": "0.7.0",
            "manifest_id": "texture-pack-001",
            "job_id": "export_pdf_test",
            "run_id": run_id,
            "profile_id": "portable_gltf",
            "source": source,
            "status": "complete",
            "packing_required": True,
            "raw_channels_preserved": True,
            "textures": [
                {
                    "texture_id": "texture.orm",
                    "material_ids": ["mat.body"],
                    "packing": "gltf_orm",
                    "output": _artifact(
                        "texture-orm-output",
                        "packed_texture",
                        "optimization/runs/run-001/textures/gltf_orm.png",
                    ),
                    "color_space": "Non-Color",
                    "width": 256,
                    "height": 256,
                    "mappings": [
                        {
                            "output_channel": output,
                            "source_channel": source_channel,
                            "source": _artifact(
                                f"source-{source_channel}",
                                "other",
                                f"textures/raw/{source_channel}.png",
                            ),
                            "invert": False,
                        }
                        for output, source_channel in (
                            ("R", "occlusion"),
                            ("G", "roughness"),
                            ("B", "metallic"),
                        )
                    ],
                }
            ],
            "created_at": "2026-07-16T00:00:00Z",
            "completed_at": "2026-07-16T00:01:00Z",
            "errors": [],
            "notes": [],
        },
    )
    _write_json(
        package_root / "package_manifest.json",
        {
            "schema_version": "0.7.0",
            "package_id": package_id,
            "job_id": "export_pdf_test",
            "run_id": run_id,
            "profile_id": "portable_gltf",
            "source": source,
            "optimization_plan": _artifact(
                "optimization-plan",
                "optimization_plan",
                "optimization/runs/run-001/optimization_plan.json",
            ),
            "source_manifests": [],
            "status": "complete",
            "package_root": "exports/packages/portable_gltf/package-001",
            "files": [
                {
                    "id": "primary-glb",
                    "kind": "primary_asset",
                    "path": "exports/packages/portable_gltf/package-001/asset.glb",
                    "sha256": "3" * 64,
                    "byte_size": 2048,
                    "media_type": "model/gltf-binary",
                }
            ],
            "primary_file_id": "primary-glb",
            "semantic_ids": ["asset.body"],
            "material_ids": ["mat.body"],
            "absolute_path_count": 0,
            "missing_dependency_count": 0,
            "created_at": "2026-07-16T00:01:00Z",
            "completed_at": "2026-07-16T00:02:00Z",
            "canonical_unchanged": True,
            "known_losses": [],
            "warnings": [],
            "errors": [],
        },
    )
    _write_json(
        run / "roundtrip" / package_id / "roundtrip_validation.json",
        {
            "schema_version": "0.7.0",
            "validation_id": "roundtrip-001",
            "job_id": "export_pdf_test",
            "run_id": run_id,
            "package_id": package_id,
            "status": "passed",
            "ok": True,
            "passed": 7,
            "warnings": 0,
            "failed": 0,
            "checks": [],
            "bounds": {
                "source": {"minimum": [0, 0, 0], "maximum": [2, 3, 4]},
                "imported": {"minimum": [0, 0, 0], "maximum": [2, 3, 4]},
                "max_abs_error_m": 0.0,
                "tolerance_m": 0.001,
                "passed": True,
            },
            "semantic_id_coverage": 1.0,
            "material_id_coverage": 1.0,
            "expected_semantic_ids": ["asset.body"],
            "observed_semantic_ids": ["asset.body"],
            "expected_material_ids": ["mat.body"],
            "observed_material_ids": ["mat.body"],
            "errors": [],
        },
    )
    return root


def _canonical_hashes(root: Path) -> dict[str, str]:
    """Hash every fixture file to prove export PDF generation remains read-only."""

    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_export_payload_collects_matching_run_and_package_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The latest package binds its own run and exposes only job-relative source paths."""

    root = _seed_export_report_job(tmp_path, monkeypatch)

    payload = collect_job_report_payload("export_pdf_test", "export")

    assert payload["optimization_run_id"] == "run-001"
    assert payload["package_id"] == "package-001"
    assert {
        "asset_profile",
        "optimization_plan",
        "mesh_preflight_report",
        "lod_manifest",
        "collision_manifest",
        "uv_manifest",
        "texture_pack_manifest",
        "package_manifest",
        "roundtrip_validation",
    } <= set(payload["documents"])
    assert all(not Path(source.path).is_absolute() for source in payload["sources"])
    assert all(str(root.parent) not in source.path for source in payload["sources"])


def test_export_pdf_is_readable_hashed_and_does_not_mutate_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Render a readable export PDF and a provenance manifest without changing evidence."""

    root = _seed_export_report_job(tmp_path, monkeypatch)
    before = _canonical_hashes(root)

    result = generate_job_pdf_report("export_pdf_test", scope="export")

    assert _canonical_hashes(root) == before
    pdf = Path(result["pdf"])
    manifest_path = Path(result["manifest"])
    assert pdf == tmp_path / "output" / "pdf" / "export_pdf_test" / "export_report.pdf"
    assert sha256_file(pdf) == result["pdf_sha256"]
    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert "export_pdf_test" in extracted
    assert "V0.7" in extracted
    assert "portable_gltf" in extracted
    assert "asset.body" in extracted
    assert "package-001" in extracted
    assert "round-trip" in extracted
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "human_report_manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=None).validate(manifest)
    assert manifest["scope"] == "export"
    assert manifest["optimization_run_id"] == "run-001"
    assert manifest["package_id"] == "package-001"
    assert manifest["pdf_sha256"] == result["pdf_sha256"]


def test_export_pdf_summarizes_oversized_roundtrip_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oversized round-trip ID lists are summarized instead of breaking PDF layout."""

    root = _seed_export_report_job(tmp_path, monkeypatch)
    roundtrip_path = (
        root
        / "optimization"
        / "runs"
        / "run-001"
        / "roundtrip"
        / "package-001"
        / "roundtrip_validation.json"
    )
    roundtrip = json.loads(roundtrip_path.read_text(encoding="utf-8"))
    semantic_ids = [f"asset.repeated.part.{index:04d}" for index in range(400)]
    roundtrip["warnings"] = 1
    roundtrip["expected_semantic_ids"] = semantic_ids
    roundtrip["observed_semantic_ids"] = semantic_ids
    roundtrip["checks"] = [
        {
            "id": "oversized-uv-warning",
            "category": "uv",
            "status": "warning",
            "message": "UV summary unavailable for: " + ", ".join(semantic_ids),
        }
    ]
    _write_json(roundtrip_path, roundtrip)

    result = generate_job_pdf_report("export_pdf_test", scope="export")

    pdf = Path(result["pdf"])
    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert pdf.is_file()
    assert "canonical round-trip JSON remains authoritative" in extracted
    assert "see canonical JSON" in extracted


def test_export_profile_path_escape_is_skipped_without_disclosure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An external profile referenced by a run is excluded and reported as a warning."""

    root = _seed_export_report_job(tmp_path, monkeypatch)
    outside = tmp_path / "outside-profile.json"
    _write_json(outside, {"secret": "not report evidence"})
    plan_path = root / "optimization" / "runs" / "run-001" / "optimization_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["profile_artifact"]["path"] = "../../../../outside-profile.json"
    _write_json(plan_path, plan)

    payload = collect_job_report_payload("export_pdf_test", "export")

    assert "asset_profile" not in payload["documents"]
    assert any("Skipped an external report asset" in item for item in payload["warnings"])
    assert all(str(outside) not in source.path for source in payload["sources"])


def test_explicit_package_id_is_rejected_when_ambiguous_across_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A package ID shared by profiles requires an explicit profile/package selector."""

    root = _seed_export_report_job(tmp_path, monkeypatch)
    second = (
        root
        / "exports"
        / "packages"
        / "fbx_interchange"
        / "package-001"
        / "package_manifest.json"
    )
    _write_json(second, {"package_id": "package-001", "run_id": "run-001"})

    with pytest.raises(ValueError, match="ambiguous across profiles"):
        collect_job_report_payload(
            "export_pdf_test",
            "export",
            package_id="package-001",
        )


def test_export_report_rejects_run_that_differs_from_selected_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent one PDF from mixing a package with an unrelated optimization run."""

    _seed_export_report_job(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="does not match the selected package"):
        collect_job_report_payload(
            "export_pdf_test",
            "export",
            optimization_run_id="run-different",
            package_id="portable_gltf/package-001",
        )


def test_export_report_prefers_hash_verified_package_metadata_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use immutable package metadata instead of a later-mutated live run document."""

    root = _seed_export_report_job(tmp_path, monkeypatch)
    package_root = root / "exports" / "packages" / "portable_gltf" / "package-001"
    metadata_root = package_root / "metadata"
    metadata_root.mkdir()
    live_plan = root / "optimization" / "runs" / "run-001" / "optimization_plan.json"
    snapshot_plan = metadata_root / "optimization_plan.json"
    snapshot = json.loads(live_plan.read_text(encoding="utf-8"))
    snapshot["notes"] = ["immutable package snapshot"]
    _write_json(snapshot_plan, snapshot)
    live = dict(snapshot)
    live["notes"] = ["later live-run mutation"]
    _write_json(live_plan, live)
    manifest_path = package_root / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(
        {
            "id": "metadata-optimization-plan",
            "kind": "metadata",
            "path": snapshot_plan.relative_to(root).as_posix(),
            "sha256": sha256_file(snapshot_plan),
            "byte_size": snapshot_plan.stat().st_size,
            "media_type": "application/json",
        }
    )
    _write_json(manifest_path, manifest)

    payload = collect_job_report_payload(
        "export_pdf_test",
        "export",
        package_id="portable_gltf/package-001",
    )

    assert payload["documents"]["optimization_plan"]["notes"] == [
        "immutable package snapshot"
    ]
    plan_sources = [source for source in payload["sources"] if source.kind == "optimization_plan"]
    assert len(plan_sources) == 1
    assert plan_sources[0].path.endswith("metadata/optimization_plan.json")
