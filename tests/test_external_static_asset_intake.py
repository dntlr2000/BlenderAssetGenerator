from __future__ import annotations

import json
import os
import runpy
import subprocess
import tomllib
from pathlib import Path

import pytest
from cli_help_support import assert_cli_help_contract
from typer.testing import CliRunner

from codex_blender_modeler.cli import app
from codex_blender_modeler.config import get_settings
from codex_blender_modeler.external_intake import (
    approve_external_static_asset_intake,
    get_external_static_asset_intake_status,
    normalize_external_static_asset,
    plan_external_static_asset_intake,
    validate_external_static_asset_intake,
)
from codex_blender_modeler.optimization import (
    approve_asset_optimization,
    initialize_asset_profile,
    optimize_asset,
    plan_asset_optimization,
    preflight_asset,
)
from codex_blender_modeler.optimization.models import SourceProvenance
from codex_blender_modeler.optimization.provenance import collect_source_provenance
from codex_blender_modeler.packaging import (
    convert_portable_materials,
    package_asset,
    validate_asset_package,
)
from codex_blender_modeler.stabilization.service import _audit_job
from codex_blender_modeler.versioning import EXTERNAL_STATIC_ASSET_SCHEMA_VERSION
from codex_blender_modeler.workspace import sha256_file

ROOT = Path(__file__).resolve().parents[1]
CLI_COMMANDS = {
    "external-intake-plan",
    "external-intake-approve",
    "external-intake-normalize",
    "external-intake-validate",
    "external-intake-status",
}
MCP_TOOLS = {
    "plan_external_static_asset_intake",
    "approve_external_static_asset_intake",
    "normalize_external_static_asset",
    "validate_external_static_asset_intake",
    "get_external_static_asset_intake_status",
}


def _fake_external_blender(script: str, args: list[str], **_kwargs: object) -> dict:
    """Emulate only the two fixed Blender scripts used by host contract tests."""

    def value(flag: str) -> str:
        """Return one required fake Blender argument value."""

        return args[args.index(flag) + 1]

    if script == "inspect_external_static_asset.py":
        output = Path(value("--output"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "ok": True,
                    "objects": [
                        {
                            "name": "Manual Body",
                            "type": "MESH",
                            "dimensions": [2.0, 1.0, 0.5],
                            "parent_chain": [],
                            "material_names": ["Paint", "Glass"],
                            "material_slots": [
                                {
                                    "material_index": 0,
                                    "material_name": "Paint",
                                    "polygon_count": 8,
                                },
                                {
                                    "material_index": 1,
                                    "material_name": "Glass",
                                    "polygon_count": 4,
                                },
                            ],
                            "has_uv0": True,
                            "hide_render": False,
                        }
                    ],
                    "materials": [
                        {
                            "name": "Paint",
                            "node_fingerprint": "a" * 64,
                            "surface": {"roughness": 0.35},
                            "images": [],
                        },
                        {
                            "name": "Glass",
                            "node_fingerprint": "b" * 64,
                            "surface": {"transmission_weight": 1.0, "alpha": 0.4},
                            "images": [],
                        },
                    ],
                    "blockers": [],
                    "warnings": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"ok": True}
    if script == "normalize_external_static_asset.py":
        plan = json.loads(Path(value("--plan")).read_text(encoding="utf-8"))
        output_blend = Path(value("--output-blend"))
        output_blend.parent.mkdir(parents=True, exist_ok=True)
        output_blend.write_bytes(b"normalized-static-blend-fixture")
        evidence = {
            "ok": True,
            "job_id": plan["job_id"],
            "source_sha256": value("--expected-source-sha256"),
            "plan_sha256": value("--expected-plan-sha256"),
            "build_fingerprint": value("--build-fingerprint"),
            "source_unit_scale_to_meters": plan["normalization"][
                "source_unit_scale_to_meters"
            ],
            "normalized_unit_system": "METRIC",
            "normalized_unit_scale_length": 1.0,
            "normalized_length_unit": "METERS",
            "normalized_blend_sha256": sha256_file(output_blend),
            "objects": [
                {
                    "name": item["semantic_id"],
                    "type": "MESH",
                    "semantic_id": item["semantic_id"],
                    "material_ids": item["material_ids"],
                    "location": [0.0, 0.0, 0.0],
                    "rotation_euler": [0.0, 0.0, 0.0],
                    "scale": [1.0, 1.0, 1.0],
                    "dimensions": [2.0, 1.0, 0.5],
                }
                for item in plan["objects"]
            ],
            "materials": [],
            "sanitization": {
                "text_block_count": 0,
                "scene_count": 1,
                "action_count": 0,
                "armature_count": 0,
                "autoexec_disabled": True,
            },
        }
        Path(value("--output-evidence")).write_text(
            json.dumps(evidence),
            encoding="utf-8",
        )
        return {"ok": True}
    raise AssertionError(f"Unexpected Blender script: {script}")


def test_external_intake_public_surface_and_schemas_are_registered() -> None:
    """Keep CLI, MCP allowlist, version, and generated schemas discoverable."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(result.stdout, required=CLI_COMMANDS)
    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert MCP_TOOLS <= enabled
    schemas = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))["SCHEMAS"]
    assert "external_asset_intake_plan.schema.json" in schemas
    assert "external_asset_manifest.schema.json" in schemas
    assert EXTERNAL_STATIC_ASSET_SCHEMA_VERSION == "0.9.0"


def test_external_intake_normalizes_multimaterial_source_and_binds_v07(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create two single-material semantic parts and expose exact V0.7 provenance."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(
        "codex_blender_modeler.external_intake.service.run_blender",
        _fake_external_blender,
    )
    source = tmp_path / "manual_asset.blend"
    source.write_bytes(b"immutable-manual-asset")

    plan = plan_external_static_asset_intake(
        "manual_prop_01",
        source,
        plan_id="intake-manual-prop-01",
    )
    job_root = workspace / "manual_prop_01"
    plan_path = job_root / "intake" / "plans" / plan.plan_id / "plan.json"
    assert plan.status == "awaiting_user_approval"
    assert len(plan.objects) == 2
    assert all(len(item.material_ids) == 1 for item in plan.objects)
    assert {tuple(item.source_material_indices) for item in plan.objects} == {(0,), (1,)}
    assert not (job_root / "analysis" / "scene_spec.json").exists()

    plan_sha256 = sha256_file(plan_path)
    approval = approve_external_static_asset_intake(
        "manual_prop_01",
        plan.plan_id,
        plan_sha256,
        approval_note="Reviewed static-only normalization mapping.",
    )
    assert approval.used is False
    manifest = normalize_external_static_asset(
        "manual_prop_01",
        plan.plan_id,
        plan_sha256,
    )
    validation = validate_external_static_asset_intake("manual_prop_01")
    provenance = collect_source_provenance(job_root, "manual_prop_01")

    assert manifest.source_kind == "external_static_asset"
    assert validation.ok is True
    assert validation.normalization_receipt_current is True
    assert provenance.source_kind == "external_static_asset"
    assert provenance.scene_spec is None
    assert provenance.external_asset_manifest is not None
    assert provenance.blend.sha256 == manifest.normalized_blend.sha256
    audit = _audit_job(job_root, [0], 10_000)
    assert audit.status == "passed", audit.model_dump(mode="json")
    assert not any(item.code.startswith("EXTERNAL_INTAKE_") for item in audit.findings)


def test_external_intake_detects_source_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when the immutable copied source changes after normalization."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(
        "codex_blender_modeler.external_intake.service.run_blender",
        _fake_external_blender,
    )
    source = tmp_path / "manual_asset.blend"
    source.write_bytes(b"immutable-manual-asset")
    plan = plan_external_static_asset_intake(
        "manual_prop_tamper",
        source,
        plan_id="intake-manual-prop-tamper",
    )
    root = workspace / "manual_prop_tamper"
    plan_path = root / "intake" / "plans" / plan.plan_id / "plan.json"
    digest = sha256_file(plan_path)
    approve_external_static_asset_intake(
        "manual_prop_tamper",
        plan.plan_id,
        digest,
        approval_note="Reviewed static-only normalization mapping.",
    )
    normalize_external_static_asset("manual_prop_tamper", plan.plan_id, digest)
    (root / plan.source.path).write_bytes(b"tampered-source")

    validation = validate_external_static_asset_intake("manual_prop_tamper")
    assert validation.ok is False
    assert validation.source_current is False
    status = get_external_static_asset_intake_status("manual_prop_tamper")
    assert status["validation_status"] == "failed"
    assert status["ready_for_v07_preflight"] is False
    audit = _audit_job(root, [0], 10_000)
    assert audit.status == "failed"
    assert any(
        item.code == "EXTERNAL_INTAKE_STALE_OR_TAMPERED"
        for item in audit.findings
    )
    with pytest.raises(RuntimeError, match="stale|missing"):
        collect_source_provenance(root, "manual_prop_tamper")


def test_external_intake_rejects_changed_candidate_before_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject approval when a workflow-owned material candidate changed after planning."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(
        "codex_blender_modeler.external_intake.service.run_blender",
        _fake_external_blender,
    )
    source = tmp_path / "manual_asset.blend"
    source.write_bytes(b"immutable-manual-asset")
    plan = plan_external_static_asset_intake(
        "manual_candidate_tamper",
        source,
        plan_id="intake-candidate-tamper",
    )
    root = workspace / "manual_candidate_tamper"
    plan_path = root / "intake" / "plans" / plan.plan_id / "plan.json"
    candidate = root / plan.candidate_shader_recipes[0].path
    candidate.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="stale|missing"):
        approve_external_static_asset_intake(
            "manual_candidate_tamper",
            plan.plan_id,
            sha256_file(plan_path),
            approval_note="This stale candidate must not be approved.",
        )


def test_external_intake_detects_normalized_blend_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject V0.7 provenance when the normalized authoring blend changes in place."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(
        "codex_blender_modeler.external_intake.service.run_blender",
        _fake_external_blender,
    )
    source = tmp_path / "manual_asset.blend"
    source.write_bytes(b"immutable-manual-asset")
    plan = plan_external_static_asset_intake(
        "manual_blend_tamper",
        source,
        plan_id="intake-blend-tamper",
    )
    root = workspace / "manual_blend_tamper"
    plan_path = root / "intake" / "plans" / plan.plan_id / "plan.json"
    digest = sha256_file(plan_path)
    approve_external_static_asset_intake(
        "manual_blend_tamper",
        plan.plan_id,
        digest,
        approval_note="Reviewed static normalization mapping.",
    )
    manifest = normalize_external_static_asset(
        "manual_blend_tamper",
        plan.plan_id,
        digest,
    )
    (root / manifest.normalized_blend.path).write_bytes(b"tampered-normalized-blend")

    validation = validate_external_static_asset_intake("manual_blend_tamper")
    assert validation.ok is False
    assert validation.normalized_blend_current is False
    with pytest.raises(RuntimeError, match="normalized blend|hash mismatch"):
        collect_source_provenance(root, "manual_blend_tamper")


def test_legacy_source_provenance_defaults_to_scene_spec() -> None:
    """Load pre-intake V0.7 evidence without requiring a new discriminator field."""

    artifact = {
        "id": "source.scene_spec",
        "kind": "scene_spec",
        "path": "analysis/scene_spec.json",
        "sha256": "a" * 64,
    }
    provenance = SourceProvenance.model_validate(
        {
            "scene_spec": artifact,
            "blend": {
                "id": "source.blend",
                "kind": "blend",
                "path": "blender/scene.blend",
                "sha256": "b" * 64,
            },
            "source_fingerprint": "c" * 64,
            "build_fingerprint": "d" * 64,
        }
    )
    assert provenance.source_kind == "scene_spec"
    assert provenance.scene_spec is not None


@pytest.mark.skipif(
    os.getenv("CBM_RUN_EXTERNAL_INTAKE_SMOKE") != "1",
    reason="Set CBM_RUN_EXTERNAL_INTAKE_SMOKE=1 for Blender 5 intake evidence.",
)
def test_blender_external_intake_splits_materials_and_strips_scripts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalize a real source and prove V0.7 GLB clean-import portability."""

    settings = get_settings()
    fixture_script = ROOT / "tests" / "blender_scripts" / "create_external_static_asset_fixture.py"
    source = tmp_path / "manual_multimaterial.blend"
    command = [
        settings.blender_bin,
        "--factory-startup",
        "--disable-autoexec",
        "--background",
        "--python-exit-code",
        "1",
        "--python",
        str(fixture_script),
        "--",
        "--output",
        str(source),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=settings.blender_timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "External intake fixture creation failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    workspace = tmp_path / "w"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    plan = plan_external_static_asset_intake(
        "ext_smoke",
        source,
        plan_id="intake-ext",
    )
    assert plan.normalization.source_unit_scale_to_meters == pytest.approx(0.01)
    assert len(plan.objects) == 2
    assert {item.material_ids[0] for item in plan.objects} == {"mat.paint", "mat.glass"}
    plan_path = (
        workspace
        / "ext_smoke"
        / "intake"
        / "plans"
        / plan.plan_id
        / "plan.json"
    )
    digest = sha256_file(plan_path)
    approve_external_static_asset_intake(
        "ext_smoke",
        plan.plan_id,
        digest,
        approval_note="Opt-in real Blender static-intake smoke approval.",
    )
    normalize_external_static_asset("ext_smoke", plan.plan_id, digest)
    root = workspace / "ext_smoke"
    evidence = json.loads(
        (root / "intake" / "normalization_evidence.json").read_text(encoding="utf-8")
    )
    assert len(evidence["objects"]) == 2
    assert all(len(item["material_ids"]) == 1 for item in evidence["objects"])
    assert all(
        0.0 < max(float(value) for value in item["dimensions"]) <= 0.020001
        for item in evidence["objects"]
    )
    assert evidence["normalized_unit_system"] == "METRIC"
    assert evidence["normalized_unit_scale_length"] == pytest.approx(1.0)
    assert evidence["normalized_length_unit"] == "METERS"
    assert evidence["sanitization"] == {
        "text_block_count": 0,
        "scene_count": 1,
        "action_count": 0,
        "armature_count": 0,
        "autoexec_disabled": True,
    }
    assert validate_external_static_asset_intake("ext_smoke").ok is True
    initialize_asset_profile(
        "ext_smoke",
        profile_id="portable_gltf",
        asset_kind="static_prop",
        consolidation_mode="none",
        lod_mode="disabled",
        generate_uv1=False,
        collision_strategy="none",
    )
    run_id = "v07"
    preflight = preflight_asset(
        "ext_smoke",
        profile_id="portable_gltf",
        run_id=run_id,
    )
    assert preflight.ok is True
    review = plan_asset_optimization(
        "ext_smoke",
        profile_id="portable_gltf",
        run_id=run_id,
    )
    approve_asset_optimization(
        "ext_smoke",
        run_id=run_id,
        plan_sha256=review.plan_sha256,
        approval_note="Opt-in V0.7 external intake smoke approval.",
    )
    optimized = optimize_asset(
        "ext_smoke",
        profile_id="portable_gltf",
        run_id=run_id,
        approved_plan_sha256=review.plan_sha256,
    )
    assert optimized.status == "complete"
    conversion_id = "mat"
    conversion = convert_portable_materials(
        "ext_smoke",
        profile_id="portable_gltf",
        run_id=run_id,
        conversion_id=conversion_id,
        resolution=64,
        margin_px=4,
        render_device="cpu",
    )
    assert conversion.status == "complete"
    package_id = "pkg"
    package = package_asset(
        "ext_smoke",
        profile_id="portable_gltf",
        run_id=run_id,
        package_id=package_id,
        material_conversion_id=conversion_id,
        include_colliders=False,
    )
    assert package.status == "complete"
    roundtrip = validate_asset_package(
        "ext_smoke",
        package_id,
        profile_id="portable_gltf",
    )
    assert roundtrip.ok is True
    assert roundtrip.semantic_id_coverage == 1.0
    assert roundtrip.material_id_coverage == 1.0
