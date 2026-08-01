from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from typer.testing import CliRunner

from codex_blender_modeler.analysis.models import (
    ModelingPlan,
    ModelingPlanObject,
    SurfaceDetailDecision,
    SurfaceDetailPolicy,
    SurfaceDetailValidationReport,
)
from codex_blender_modeler.analysis.surface_details import (
    validate_job_surface_details,
)
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.cli import app
from codex_blender_modeler.materials.models import MaterialPlan, MaterialPlanItem
from codex_blender_modeler.materials.service import validate_job_material_contracts
from codex_blender_modeler.mcp_server import get_modeling_capabilities

ROOT = Path(__file__).resolve().parents[1]


def _seed_surface_detail_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Create one isolated valid job with a texture-routed window decision."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    root = workspace / "surface_detail_asset"
    analysis = root / "analysis"
    analysis.mkdir(parents=True)
    (root / "job.json").write_text(
        json.dumps({"job_id": "surface_detail_asset", "mode": "concept"}),
        encoding="utf-8",
    )
    scene = json.loads(
        (ROOT / "examples" / "measured_box" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    scene["job_id"] = "surface_detail_asset"
    scene["mode"] = "concept"
    (analysis / "scene_spec.json").write_text(
        json.dumps(scene, indent=2) + "\n",
        encoding="utf-8",
    )
    plan = ModelingPlan(
        job_id="surface_detail_asset",
        reference_analysis_path="analysis/reference_analysis.json",
        camera_solution_path="analysis/camera_solution.json",
        stage="authored",
        objects=[
            ModelingPlanObject(
                id="asset.box",
                label="body",
                recommended_geometry="primitive",
                source_ids=["reference"],
                confidence=0.9,
            )
        ],
        surface_detail_policy=SurfaceDetailPolicy(mode="texture_preferred"),
        surface_details=[
            SurfaceDetailDecision(
                id="detail.window.front",
                label="painted front window",
                parent_object_id="asset.box",
                representation="baked_decal",
                source_ids=["reference"],
                bbox_norm=(0.3, 0.2, 0.5, 0.4),
                target_material_id="mat.box",
                channels=["base_color", "normal"],
                uv_strategy="material_atlas",
                projected_size_px=32,
                repeated_count=2,
                confidence=0.9,
            )
        ],
    )
    (analysis / "modeling_plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def _write_authored_materials(root: Path, *, claim_detail: bool) -> None:
    """Write one portable UVMap manifest with optional exact surface-detail coverage."""

    texture_root = root / "textures" / "mat.box"
    texture_root.mkdir(parents=True)
    (texture_root / "base_color.png").write_bytes(b"base-color")
    (texture_root / "normal.png").write_bytes(b"normal")
    manifest = {
        "schema_version": "0.5.0",
        "material_id": "mat.box",
        "uv_set": "UVMap",
        "intended_scale_m": 1.0,
        "resolution": [64, 64],
        "source_type": "image",
        "channels": {
            "base_color": {
                "source": "image",
                "path": "base_color.png",
                "color_space": "sRGB",
            },
            "normal": {
                "source": "image",
                "path": "normal.png",
                "color_space": "Non-Color",
            },
        },
        "surface_detail_ids": ["detail.window.front"] if claim_detail else [],
    }
    (texture_root / "texture_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    plan = MaterialPlan(
        job_id="surface_detail_asset",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.box",
                label="body material",
                texture_strategy="image",
                texture_manifest="textures/mat.box/texture_manifest.json",
                mapping={
                    "mode": "uv",
                    "uv_set": "UVMap",
                    "real_world_scale_m": 1.0,
                },
            )
        ],
    )
    (root / "analysis" / "material_plan.json").write_text(
        plan.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def test_surface_detail_decision_rejects_geometry_worthy_parts() -> None:
    """Keep silhouette and structural parts in the normal geometry object list."""

    with pytest.raises(ValidationError, match="Geometry-worthy details"):
        SurfaceDetailDecision(
            id="detail.window.cutout",
            label="physical glass opening",
            parent_object_id="asset.body",
            representation="baked_decal",
            target_material_id="mat.body",
            channels=["base_color"],
            uv_strategy="existing_uv",
            physical_transparency_required=True,
        )


def test_surface_detail_validation_stays_pending_until_v05_then_requires_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow V0.4 geometry, then fail closed until V0.5 claims exact PBR coverage."""

    root = _seed_surface_detail_job(tmp_path, monkeypatch)
    pending = validate_job_surface_details(
        "surface_detail_asset",
        require_materials=False,
        write_report=False,
    )
    assert pending.ok
    assert pending.material_status == "pending"
    assert pending.textured == 1

    _write_authored_materials(root, claim_detail=False)
    missing = validate_job_surface_details(
        "surface_detail_asset",
        require_materials=True,
        write_report=False,
    )
    assert not missing.ok
    assert any("exact coverage" in item.message for item in missing.checks)

    manifest_path = root / "textures" / "mat.box" / "texture_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["surface_detail_ids"] = ["detail.window.front"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    covered = validate_job_surface_details(
        "surface_detail_asset",
        require_materials=True,
        write_report=True,
    )
    assert covered.ok
    assert covered.material_status == "validated"
    assert (root / "reports" / "surface_detail_validation.json").is_file()
    material_report = validate_job_material_contracts("surface_detail_asset")
    assert material_report["ok"] is True
    assert any(
        str(item["id"]).startswith("surface_detail:")
        for item in material_report["checks"]
    )


def test_surface_detail_validation_rejects_duplicate_detail_mesh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a SceneSpec object whose ID was explicitly routed to a texture decision."""

    root = _seed_surface_detail_job(tmp_path, monkeypatch)
    scene_path = root / "analysis" / "scene_spec.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    duplicate = deepcopy(scene["objects"][0])
    duplicate["id"] = "detail.window.front"
    duplicate["name"] = "forbidden window mesh"
    scene["objects"].append(duplicate)
    scene_path.write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")

    report = validate_job_surface_details(
        "surface_detail_asset",
        require_materials=False,
        write_report=False,
    )
    assert not report.ok
    assert any("must not exist" in item.message for item in report.checks)


def test_surface_detail_modeling_plan_hash_participates_in_build_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalidate a built scene when a declared non-mesh detail decision changes."""

    root = _seed_surface_detail_job(tmp_path, monkeypatch)
    _write_authored_materials(root, claim_detail=True)
    before = collect_build_provenance(root, "surface_detail_asset")
    plan_path = root / "analysis" / "modeling_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["surface_details"][0]["notes"] = ["revised detail evidence"]
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    after = collect_build_provenance(root, "surface_detail_asset")

    assert before["surface_detail_contracts"]["surface_detail_ids"] == [
        "detail.window.front"
    ]
    assert before["fingerprint"] != after["fingerprint"]


def test_surface_detail_provenance_avoids_host_only_analysis_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep Blender-side fingerprint collection independent of host-only imports."""

    import builtins

    root = _seed_surface_detail_job(tmp_path, monkeypatch)
    _write_authored_materials(root, claim_detail=True)
    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        """Fail if Blender-safe provenance tries to load the host analysis package."""

        if name.startswith("codex_blender_modeler.analysis") or name.startswith(
            ".analysis"
        ):
            raise AssertionError("host-only analysis import reached Blender-safe path")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    provenance = collect_build_provenance(
        root,
        "surface_detail_asset",
        validate_contracts=False,
    )

    assert provenance["surface_detail_contracts"]["surface_detail_ids"] == [
        "detail.window.front"
    ]


def test_surface_detail_schemas_and_public_surface_are_available() -> None:
    """Keep schemas, CLI commands, MCP allowlist, and capabilities discoverable."""

    for name in (
        "modeling_plan.schema.json",
        "texture_manifest.schema.json",
        "surface_detail_validation.schema.json",
        "visual_qa_report.schema.json",
    ):
        schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        if name == "visual_qa_report.schema.json":
            assert "surface_detail_summary" in schema["properties"]
        if name == "surface_detail_validation.schema.json":
            assert schema == SurfaceDetailValidationReport.model_json_schema()
    help_result = CliRunner().invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "validate-surface-details" in help_result.stdout
    assert "surface-detail-status" in help_result.stdout
    config_text = (ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert '"validate_surface_details"' in config_text
    assert '"get_surface_detail_status"' in config_text
    capabilities = get_modeling_capabilities()["surface_detail_routing"]
    assert capabilities["representations"] == [
        "texture_channels",
        "baked_decal",
        "omit",
    ]
