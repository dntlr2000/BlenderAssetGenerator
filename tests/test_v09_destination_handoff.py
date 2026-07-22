from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

import codex_blender_modeler.stabilization.service as stabilization_service
from codex_blender_modeler.config import Settings
from codex_blender_modeler.handoff import (
    generate_destination_handoff,
    get_destination_handoff_status,
    plan_destination_handoff,
    validate_destination_handoff,
)
from codex_blender_modeler.optimization.models import (
    Bounds3D,
    HashedArtifact,
    SourceProvenance,
)
from codex_blender_modeler.packaging.models import (
    BoundsComparison,
    ExportPackageManifest,
    PackageFile,
    RoundTripValidation,
)
from codex_blender_modeler.reporting.service import (
    collect_job_report_payload,
    generate_job_pdf_report,
)
from codex_blender_modeler.stabilization import audit_workspace_state
from codex_blender_modeler.workspace import create_job, sha256_file


def _write_json(path: Path, payload: dict) -> None:
    """Write one deterministic JSON fixture below an isolated job workspace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _hashed_artifact(path: str, kind: str, digest: str = "a" * 64) -> HashedArtifact:
    """Create one strict V0.7 artifact reference for synthetic provenance."""

    return HashedArtifact(
        id=f"fixture.{kind}",
        kind=kind,  # type: ignore[arg-type]
        path=path,
        sha256=digest,
    )


def _package_file(root: Path, path: Path, file_id: str, kind: str) -> PackageFile:
    """Create an exact package file receipt for one synthetic dependency."""

    media_type = {
        ".json": "application/json",
        ".glb": "model/gltf-binary",
        ".fbx": "application/octet-stream",
    }.get(path.suffix.lower(), "application/octet-stream")
    return PackageFile(
        id=file_id,
        kind=kind,  # type: ignore[arg-type]
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        media_type=media_type,
    )


def _build_package_fixture(
    workspace: Path,
    profile_id: str = "portable_gltf",
) -> tuple[Path, str, str, str]:
    """Build a minimal passed V0.7 GLB or FBX package and round-trip receipt."""

    job_id = "handoff_asset"
    package_id = "package-test"
    run_id = "run-test"
    reference = workspace.parent / "handoff-reference.png"
    Image.new("RGB", (16, 16), (90, 120, 150)).save(reference)
    create_job(job_id, reference, "concept", [])
    root = workspace / job_id
    package_root = root / "exports/packages" / profile_id / package_id
    metadata = package_root / "metadata"
    metadata.mkdir(parents=True)
    primary_name = "asset.glb" if profile_id == "portable_gltf" else "asset.fbx"
    primary = package_root / primary_name
    primary.write_bytes(
        b"glTF-fixture" if primary.suffix == ".glb" else b"FBX-fixture"
    )
    optimization_plan = metadata / "optimization_plan.json"
    _write_json(optimization_plan, {"status": "complete", "run_id": run_id})
    delivery_mapping = metadata / "delivery_mapping.json"
    _write_json(
        delivery_mapping,
        {
            "objects": [
                {
                    "export_key": "prop.body|0|render|0",
                    "name": "prop_body__LOD0",
                    "semantic_id": "prop.body",
                    "instance_index": 0,
                    "asset_role": "render",
                    "lod_level": 0,
                    "collider": False,
                    "material_ids": ["mat.body"],
                }
            ]
        },
    )
    export_evidence = package_root / "export_evidence.json"
    _write_json(
        export_evidence,
        {
            "coordinate_contract": {
                "source_up_axis": "+Z",
                "export_up_axis": "+Y",
                "export_forward_axis": "-Z",
                "source_contract_units": "meters",
                "unit_scale_m": 1.0,
                "file_metadata_verified": False,
            },
            "objects": [
                {
                    "name": "prop_body__LOD0",
                    "semantic_id": "prop.body",
                    "asset_role": "render",
                    "lod_level": 0,
                    "instance_index": 0,
                    "material_ids": ["mat.body"],
                    "location": [0.0, 0.0, 0.5],
                    "rotation_euler": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                    "bbox_world": {"min": [-0.5, -0.5, 0.0], "max": [0.5, 0.5, 1.0]},
                }
            ],
        },
    )
    files = [
        _package_file(root, primary, "primary.asset", "primary_asset"),
        _package_file(root, optimization_plan, "metadata.optimization", "metadata"),
        _package_file(root, delivery_mapping, "metadata.delivery", "metadata"),
        _package_file(root, export_evidence, "metadata.export", "metadata"),
    ]
    now = datetime.now(UTC)
    package = ExportPackageManifest(
        package_id=package_id,
        job_id=job_id,
        run_id=run_id,
        profile_id=profile_id,
        source=SourceProvenance(
            scene_spec=_hashed_artifact("analysis/scene_spec.json", "scene_spec"),
            blend=_hashed_artifact("blender/scene.blend", "blend", "b" * 64),
            source_fingerprint="c" * 64,
            build_fingerprint="d" * 64,
        ),
        optimization_plan=_hashed_artifact(
            optimization_plan.relative_to(root).as_posix(),
            "optimization_plan",
            sha256_file(optimization_plan),
        ),
        status="complete",
        package_root=package_root.relative_to(root).as_posix(),
        files=files,
        primary_file_id="primary.asset",
        semantic_ids=["prop.body"],
        material_ids=["mat.body"],
        created_at=now,
        completed_at=now,
        known_losses=["Blender procedural shader graph is not embedded."],
    )
    manifest_path = package_root / "package_manifest.json"
    manifest_path.write_text(package.model_dump_json(indent=2) + "\n", encoding="utf-8")
    roundtrip_root = root / "optimization/runs" / run_id / "roundtrip" / package_id
    evidence_path = roundtrip_root / "roundtrip_evidence.json"
    _write_json(evidence_path, {"ok": True, "objects": 1})
    bounds = Bounds3D(minimum=(-0.5, -0.5, 0.0), maximum=(0.5, 0.5, 1.0))
    roundtrip = RoundTripValidation(
        validation_id="roundtrip.package-test",
        job_id=job_id,
        run_id=run_id,
        package_id=package_id,
        profile_id=profile_id,
        package_manifest=_hashed_artifact(
            manifest_path.relative_to(root).as_posix(),
            "package_manifest",
            sha256_file(manifest_path),
        ),
        imported_inventory=_hashed_artifact(
            evidence_path.relative_to(root).as_posix(),
            "roundtrip_inventory",
            sha256_file(evidence_path),
        ),
        status="passed",
        ok=True,
        passed=0,
        warnings=0,
        failed=0,
        checks=[],
        bounds=BoundsComparison(
            source=bounds,
            imported=bounds,
            max_abs_error_m=0.0,
            tolerance_m=0.0001,
            passed=True,
        ),
        expected_semantic_ids=["prop.body"],
        observed_semantic_ids=["prop.body"],
        semantic_id_coverage=1.0,
        expected_material_ids=["mat.body"],
        observed_material_ids=["mat.body"],
        material_id_coverage=1.0,
        created_at=now,
    )
    report_path = roundtrip_root / "roundtrip_validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(roundtrip.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return root, profile_id, package_id, run_id


def test_handoff_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Generate and read-only verify a complete GLB handoff in an isolated workspace."""

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    root, profile_id, package_id, _run_id = _build_package_fixture(workspace)
    source_snapshot = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in (root / "exports/packages" / profile_id / package_id).rglob("*")
        if path.is_file()
    }
    plan = plan_destination_handoff(
        root.name,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id="handoff-test",
    )
    plan_path = root / "handoffs/handoff-test/handoff_plan.json"
    validation = generate_destination_handoff(
        root.name,
        plan.handoff_id,
        approved_plan_sha256=sha256_file(plan_path),
    )
    assert validation.ok is True
    verified = validate_destination_handoff(
        root.name,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id=plan.handoff_id,
    )
    envelope = root / plan.output_root
    manifest = json.loads(
        (envelope / "codex_handoff/handoff_manifest.json").read_text(encoding="utf-8")
    )
    prompt = (envelope / "codex_handoff/codex_import_prompt.md").read_text(
        encoding="utf-8"
    )
    pdf = envelope / "codex_handoff/handoff_report.pdf"
    assert verified.handoff_manifest_sha256 == sha256_file(
        envelope / "codex_handoff/handoff_manifest.json"
    )
    assert manifest["package_manifest"]["sha256"] == plan.package_manifest.sha256
    assert manifest["primary_model"]["path"] == "package/asset.glb"
    assert "<PACKAGE_PATH>" in prompt and "import_plan.json" in prompt
    assert len(PdfReader(pdf).pages) >= 3
    assert get_destination_handoff_status(root.name)["status"] == "valid"
    payload = collect_job_report_payload(
        root.name,
        "export",
        package_id=f"{profile_id}/{package_id}",
    )
    assert payload["handoff_id"] == plan.handoff_id
    assert payload["documents"]["destination_handoff_validation"]["ok"] is True
    pdf_result = generate_job_pdf_report(
        root.name,
        scope="export",
        package_id=f"{profile_id}/{package_id}",
        output_path=root / "reports" / "handoff-export-report.pdf",
    )
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(pdf_result["pdf"]).pages
    )
    assert "Codex Destination Handoff" in extracted
    assert plan.handoff_id in extracted
    assert source_snapshot == {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in (root / "exports/packages" / profile_id / package_id).rglob("*")
        if path.is_file()
    }


def test_fbx_handoff_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Generate and validate the same safe handoff contract for an FBX package."""

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    root, profile_id, package_id, _run_id = _build_package_fixture(
        workspace,
        profile_id="fbx_interchange",
    )
    plan = plan_destination_handoff(
        root.name,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id="handoff-fbx",
    )
    plan_path = root / "handoffs/handoff-fbx/handoff_plan.json"
    validation = generate_destination_handoff(
        root.name,
        plan.handoff_id,
        approved_plan_sha256=sha256_file(plan_path),
    )
    verified = validate_destination_handoff(
        root.name,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id=plan.handoff_id,
    )
    envelope = root / plan.output_root
    manifest = json.loads(
        (envelope / "codex_handoff/handoff_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert validation.ok is True
    assert verified.ok is True
    assert manifest["primary_model"]["path"] == "package/asset.fbx"


def test_workspace_audit_reports_valid_handoff_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Expose exact valid handoff totals in the V0.9 read-only workspace audit."""

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    root, profile_id, package_id, _run_id = _build_package_fixture(workspace)
    plan = plan_destination_handoff(
        root.name,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id="handoff-audit",
    )
    generate_destination_handoff(
        root.name,
        plan.handoff_id,
        approved_plan_sha256=sha256_file(
            root / "handoffs" / plan.handoff_id / "handoff_plan.json"
        ),
    )
    settings = Settings(
        repo_root=tmp_path,
        workspace_root=workspace,
        blender_bin=str(tmp_path / "blender.exe"),
        codex_bin="codex",
        blender_timeout=900,
    )
    monkeypatch.setattr(stabilization_service, "get_settings", lambda: settings)
    audit = audit_workspace_state(job_id=root.name, audit_id="handoff-audit")
    assert audit.handoff_count == 1
    assert audit.valid_handoff_count == 1
    assert audit.jobs[0].handoff_status == "valid"
    assert audit.status == "passed"


def test_handoff_rejections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail closed on unsupported OBJ delivery and a changed package after planning."""

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    root, profile_id, package_id, _run_id = _build_package_fixture(workspace)
    with pytest.raises(ValueError, match="GLB and FBX"):
        plan_destination_handoff(
            root.name,
            profile_id="obj_legacy",
            package_id=package_id,
        )
    plan = plan_destination_handoff(
        root.name,
        profile_id=profile_id,
        package_id=package_id,
        handoff_id="handoff-stale",
    )
    plan_path = root / "handoffs/handoff-stale/handoff_plan.json"
    (root / "exports/packages" / profile_id / package_id / "asset.glb").write_bytes(
        b"changed"
    )
    with pytest.raises(RuntimeError, match="package receipt changed"):
        generate_destination_handoff(
            root.name,
            plan.handoff_id,
            approved_plan_sha256=sha256_file(plan_path),
        )
