from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from codex_blender_modeler.materials import (
    MaterialPlan,
    MaterialPlanItem,
    ShaderRecipe,
    load_material_plan,
    load_shader_recipe,
    validate_material_contracts,
)
from codex_blender_modeler.materials.models import ShaderLayer


def _assert_schema(name: str, payload: dict) -> None:
    """Validate a generated v0.5 payload against its checked-in JSON Schema."""

    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors, [error.message for error in errors]


def _write_procedural_manifest(root: Path) -> str:
    """Write one legacy-compatible procedural manifest for host validation."""

    relative = "textures/mat.stone/texture_manifest.json"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.stone",
                "uv_set": "Object",
                "intended_scale_m": 1.5,
                "resolution": [256, 256],
                "source_type": "procedural",
                "channels": {"roughness": {"source": "procedural"}},
                "procedural": {
                    "seed": 4,
                    "noise": {"scale": 4.0},
                    "roughness_ramp": [
                        [0.0, [0.2, 0.2, 0.2, 1.0]],
                        [1.0, [0.8, 0.8, 0.8, 1.0]],
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return relative


def test_material_plan_and_shader_recipe_round_trip(tmp_path: Path) -> None:
    """Versioned material plans and shader recipes survive disk validation."""

    recipe = ShaderRecipe(material_id="mat.stone", family="rock")
    recipe_path = tmp_path / "materials" / "mat.stone" / "shader_recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    manifest_path = _write_procedural_manifest(tmp_path)
    plan = MaterialPlan(
        job_id="material_test",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.stone",
                label="Stone",
                shader_family="rock",
                texture_strategy="procedural",
                texture_manifest=manifest_path,
                shader_recipe="materials/mat.stone/shader_recipe.json",
            )
        ],
    )
    plan_path = tmp_path / "analysis" / "material_plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    assert load_material_plan(plan_path) == plan
    assert load_shader_recipe(recipe_path) == recipe
    _assert_schema("material_plan.schema.json", plan.model_dump(mode="json"))
    _assert_schema("shader_recipe.schema.json", recipe.model_dump(mode="json"))


def test_material_contract_validation_matches_scene_ids(tmp_path: Path) -> None:
    """Host validation accepts matching stable IDs, recipes, and manifests."""

    manifest_path = _write_procedural_manifest(tmp_path)
    recipe = ShaderRecipe(material_id="mat.stone", family="rock")
    recipe_path = tmp_path / "materials" / "mat.stone" / "shader_recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="material_test",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.stone",
                label="Stone",
                shader_family="rock",
                texture_strategy="procedural",
                texture_manifest=manifest_path,
                shader_recipe="materials/mat.stone/shader_recipe.json",
            )
        ],
    )
    scene_spec = {
        "job_id": "material_test",
        "materials": [{"id": "mat.stone", "texture_manifest": manifest_path}],
    }

    report = validate_material_contracts(plan, scene_spec, tmp_path)
    assert report.ok
    assert report.failed == 0
    assert report.passed == 4
    _assert_schema("material_validation.schema.json", report.model_dump(mode="json"))


def test_material_contract_validation_rejects_recipe_traversal(tmp_path: Path) -> None:
    """Shader recipe paths cannot escape the current job workspace."""

    plan = MaterialPlan(
        job_id="material_test",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.stone",
                label="Stone",
                shader_recipe="../outside.json",
            )
        ],
    )
    scene_spec = {"job_id": "material_test", "materials": [{"id": "mat.stone"}]}

    with pytest.raises(ValueError, match="inside job root"):
        validate_material_contracts(plan, scene_spec, tmp_path)


def test_authored_plan_rejects_duplicate_material_ids() -> None:
    """Material plan IDs remain unique across revisions."""

    item = MaterialPlanItem(material_id="mat.same", label="Same")
    with pytest.raises(ValueError, match="unique"):
        MaterialPlan(job_id="material_test", stage="authored", materials=[item, item])


def test_procedural_recipe_only_material_needs_no_texture_manifest(tmp_path: Path) -> None:
    """A validated procedural recipe can replace an otherwise empty texture manifest."""

    recipe = ShaderRecipe(material_id="mat.procedural", family="rock")
    recipe_path = tmp_path / "materials" / "mat.procedural" / "shader_recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="material_test",
        stage="authored",
        materials=[
                MaterialPlanItem(
                    material_id="mat.procedural",
                    label="Procedural",
                    shader_family="rock",
                    texture_strategy="procedural",
                shader_recipe="materials/mat.procedural/shader_recipe.json",
            )
        ],
    )
    scene_spec = {"job_id": "material_test", "materials": [{"id": "mat.procedural"}]}

    report = validate_material_contracts(plan, scene_spec, tmp_path)
    assert report.ok
    assert report.failed == 0
    assert any("does not require" in check.message for check in report.checks)


@pytest.mark.parametrize("strategy", ["image", "hybrid"])
def test_image_material_still_requires_texture_manifest(
    strategy: str, tmp_path: Path
) -> None:
    """Image-backed strategies cannot bypass texture-manifest validation."""

    recipe = ShaderRecipe(material_id="mat.image")
    recipe_path = tmp_path / "materials" / "mat.image" / "shader_recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="material_test",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.image",
                label="Image",
                texture_strategy=strategy,
                shader_recipe="materials/mat.image/shader_recipe.json",
            )
        ],
    )
    scene_spec = {"job_id": "material_test", "materials": [{"id": "mat.image"}]}

    report = validate_material_contracts(plan, scene_spec, tmp_path)
    assert not report.ok
    assert any("requires a manifest" in check.message for check in report.checks)


def test_host_validation_rejects_recipe_outside_runtime_subset(tmp_path: Path) -> None:
    """Contract-valid future layers are reported before Blender build when not executable yet."""

    recipe = ShaderRecipe(
        material_id="mat.future",
        layers=[ShaderLayer(id="gradient", kind="gradient", channels=["base_color"])],
    )
    recipe_path = tmp_path / "materials" / "mat.future" / "shader_recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="material_test",
        materials=[
            MaterialPlanItem(
                material_id="mat.future",
                label="Future",
                texture_strategy="procedural",
                shader_recipe="materials/mat.future/shader_recipe.json",
            )
        ],
    )
    scene_spec = {"job_id": "material_test", "materials": [{"id": "mat.future"}]}

    report = validate_material_contracts(plan, scene_spec, tmp_path)
    assert not report.ok
    assert any("runtime subset" in check.message for check in report.checks)


def test_host_validation_rejects_partial_plan_and_image_triplanar(tmp_path: Path) -> None:
    """Partial legacy mixing and unsupported image triplanar mapping fail host preflight."""

    recipe = ShaderRecipe(
        material_id="mat.image",
        mapping={"mode": "triplanar", "uv_set": "UVMap", "real_world_scale_m": 1.0},
    )
    recipe_path = tmp_path / "materials" / "mat.image" / "shader_recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="material_test",
        materials=[
            MaterialPlanItem(
                material_id="mat.image",
                label="Image",
                texture_strategy="image",
                mapping={"mode": "triplanar", "uv_set": "UVMap", "real_world_scale_m": 1.0},
                shader_recipe="materials/mat.image/shader_recipe.json",
            )
        ],
    )
    scene_spec = {
        "job_id": "material_test",
        "materials": [{"id": "mat.image"}, {"id": "mat.omitted"}],
    }

    report = validate_material_contracts(plan, scene_spec, tmp_path)
    assert not report.ok
    assert any(check.id == "material_plan_coverage:mat.omitted" for check in report.checks)
    assert any("triplanar" in check.message for check in report.checks)


def test_host_validation_requires_uv_mapping_for_spatial_details(tmp_path: Path) -> None:
    """Reject an object-mapped MaterialPlan paired with a spatial UV manifest."""

    texture_dir = tmp_path / "textures" / "mat.spatial"
    texture_dir.mkdir(parents=True)
    (texture_dir / "base.png").write_bytes(b"spatial-base")
    manifest_relative = "textures/mat.spatial/texture_manifest.json"
    (texture_dir / "texture_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.spatial",
                "uv_set": "UVMap",
                "intended_scale_m": 1.0,
                "resolution": [64, 64],
                "source_type": "image",
                "channels": {
                    "base_color": {
                        "source": "image",
                        "path": "base.png",
                        "color_space": "sRGB",
                    }
                },
                "surface_detail_ids": ["detail.window"],
                "surface_detail_bindings": [
                    {
                        "detail_id": "detail.window",
                        "parent_object_id": "asset.body",
                        "material_id": "mat.spatial",
                        "uv_set": "UVMap",
                        "uv_layout_sha256": "a" * 64,
                        "placement": {
                            "mode": "uv_rect",
                            "uv_rect": [0.1, 0.1, 0.4, 0.4],
                        },
                        "channels": ["base_color"],
                        "wrap": "clamp",
                    }
                ],
                "procedural": {},
            }
        ),
        encoding="utf-8",
    )
    plan = MaterialPlan(
        job_id="material_test",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.spatial",
                label="Spatial",
                texture_strategy="image",
                mapping={
                    "mode": "object",
                    "uv_set": "Object",
                    "real_world_scale_m": 1.0,
                },
                texture_manifest=manifest_relative,
            )
        ],
    )
    scene_spec = {
        "job_id": "material_test",
        "materials": [
            {"id": "mat.spatial", "texture_manifest": manifest_relative}
        ],
    }

    report = validate_material_contracts(plan, scene_spec, tmp_path)

    assert not report.ok
    assert any(
        "Spatial surface details require MaterialPlan UV mapping" in check.message
        for check in report.checks
    )
