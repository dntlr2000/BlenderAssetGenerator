from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.materials import MaterialPlan, MaterialPlanItem, ShaderRecipe
from codex_blender_modeler.materials.models import ShaderLayer
from codex_blender_modeler.shader_recipe_runtime import (
    ShaderRecipeRuntimeError,
    load_runtime_material_mappings,
    load_runtime_shader_recipes,
)


def _write_runtime_contract(
    root: Path,
    *,
    recipe_path: str = "materials/mat.test/recipe.json",
) -> None:
    """Write one procedural material plan and whitelisted runtime recipe."""

    recipe = ShaderRecipe(
        material_id="mat.test",
        layers=[
            ShaderLayer(
                id="noise.primary",
                kind="noise",
                channels=["base_color", "height"],
                blend="replace",
                factor=1.0,
                parameters={
                    "seed": 7,
                    "scale": 3.0,
                    "base_color_ramp": [
                        [0.0, [0.1, 0.2, 0.3, 1.0]],
                        [1.0, [0.5, 0.6, 0.7, 1.0]],
                    ],
                    "bump_strength": 0.2,
                    "bump_distance": 0.03,
                },
            )
        ],
    )
    target = root / recipe_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="runtime_test",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.test",
                label="Test",
                texture_strategy="procedural",
                shader_recipe=recipe_path,
            )
        ],
    )
    plan_path = root / "analysis" / "material_plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")


def test_absent_material_plan_preserves_legacy_build() -> None:
    """A workspace without a material plan yields no runtime overrides."""

    assert load_runtime_shader_recipes(Path("missing-job-root"), "runtime_test") == {}


def test_runtime_loader_accepts_bounded_noise_recipe(tmp_path: Path) -> None:
    """The Blender-safe loader normalizes one approved procedural Noise layer."""

    _write_runtime_contract(tmp_path)
    recipes = load_runtime_shader_recipes(tmp_path, "runtime_test")

    recipe = recipes["mat.test"]
    assert recipe["surface"]["roughness"] == 0.5
    assert recipe["layers"][0]["parameters"]["seed"] == 7
    assert recipe["mapping"]["mode"] == "object"
    assert Path(recipe["cbm_recipe_path"]).is_file()


def test_runtime_loader_rejects_recipe_path_traversal(tmp_path: Path) -> None:
    """Blender runtime contracts cannot read files outside the current job."""

    plan = MaterialPlan(
        job_id="runtime_test",
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.test",
                label="Test",
                texture_strategy="procedural",
                shader_recipe="../outside.json",
            )
        ],
    )
    path = tmp_path / "analysis" / "material_plan.json"
    path.parent.mkdir(parents=True)
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ShaderRecipeRuntimeError, match="inside job root"):
        load_runtime_shader_recipes(tmp_path, "runtime_test")


def test_runtime_loader_rejects_unapproved_layer_kind(tmp_path: Path) -> None:
    """Host-valid but runtime-unapproved shader layer kinds fail explicitly."""

    _write_runtime_contract(tmp_path)
    recipe_path = tmp_path / "materials" / "mat.test" / "recipe.json"
    raw = json.loads(recipe_path.read_text(encoding="utf-8"))
    raw["layers"][0]["kind"] = "gradient"
    recipe_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ShaderRecipeRuntimeError, match="only procedural noise"):
        load_runtime_shader_recipes(tmp_path, "runtime_test")


def _write_image_manifest(root: Path, *, material_id: str = "mat.test") -> str:
    """Write one minimal image-backed manifest for runtime pointer tests."""

    relative = "textures/mat.test/texture_manifest.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "base_color.png").write_bytes(b"test-image")
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": material_id,
                "uv_set": "Object",
                "intended_scale_m": 1.0,
                "resolution": [16, 16],
                "source_type": "image",
                "channels": {
                    "base_color": {
                        "source": "image",
                        "path": "base_color.png",
                        "color_space": "sRGB",
                    }
                },
                "procedural": {},
            }
        ),
        encoding="utf-8",
    )
    return relative


def test_runtime_loader_consumes_plan_only_texture_manifest(tmp_path: Path) -> None:
    """A MaterialPlan manifest works without duplicating its pointer in SceneSpec or recipe."""

    manifest = _write_image_manifest(tmp_path)
    plan = MaterialPlan(
        job_id="runtime_test",
        materials=[
            MaterialPlanItem(
                material_id="mat.test",
                label="Test",
                texture_strategy="image",
                texture_manifest=manifest,
            )
        ],
    )
    path = tmp_path / "analysis" / "material_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    override = load_runtime_shader_recipes(tmp_path, "runtime_test")["mat.test"]
    assert override["cbm_texture_manifest"] == manifest
    assert Path(override["cbm_texture_manifest_path"]).is_file()


def test_runtime_loader_rejects_plan_recipe_manifest_disagreement(tmp_path: Path) -> None:
    """Plan and recipe pointers cannot silently select different texture contracts."""

    first = _write_image_manifest(tmp_path)
    second = "textures/mat.test/other_manifest.json"
    recipe = ShaderRecipe(material_id="mat.test", texture_manifest=second)
    recipe_path = tmp_path / "materials" / "mat.test" / "recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="runtime_test",
        materials=[
            MaterialPlanItem(
                material_id="mat.test",
                label="Test",
                texture_strategy="image",
                texture_manifest=first,
                shader_recipe="materials/mat.test/recipe.json",
            )
        ],
    )
    path = tmp_path / "analysis" / "material_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ShaderRecipeRuntimeError, match="disagree"):
        load_runtime_shader_recipes(tmp_path, "runtime_test")


def test_runtime_loader_rejects_manifest_material_or_strategy_mismatch(tmp_path: Path) -> None:
    """Stable IDs and declared source strategies are enforced before Blender opens images."""

    manifest = _write_image_manifest(tmp_path, material_id="mat.other")
    plan = MaterialPlan(
        job_id="runtime_test",
        materials=[
            MaterialPlanItem(
                material_id="mat.test",
                label="Test",
                texture_strategy="image",
                texture_manifest=manifest,
            )
        ],
    )
    path = tmp_path / "analysis" / "material_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    with pytest.raises(ShaderRecipeRuntimeError, match="material_id"):
        load_runtime_shader_recipes(tmp_path, "runtime_test")

    raw = json.loads((tmp_path / manifest).read_text(encoding="utf-8"))
    raw["material_id"] = "mat.test"
    (tmp_path / manifest).write_text(json.dumps(raw), encoding="utf-8")
    plan.materials[0].texture_strategy = "procedural"
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    with pytest.raises(ShaderRecipeRuntimeError, match="does not match"):
        load_runtime_shader_recipes(tmp_path, "runtime_test")


def test_runtime_recipe_uses_safe_procedural_triplanar_fallback(tmp_path: Path) -> None:
    """Procedural triplanar contracts execute as 3D object-coordinate noise explicitly."""

    recipe = ShaderRecipe(
        material_id="mat.test",
        mapping={"mode": "triplanar", "uv_set": "UVMap", "real_world_scale_m": 2.0},
    )
    recipe_path = tmp_path / "materials" / "mat.test" / "recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(recipe.model_dump_json(indent=2), encoding="utf-8")
    plan = MaterialPlan(
        job_id="runtime_test",
        materials=[
            MaterialPlanItem(
                material_id="mat.test",
                label="Test",
                texture_strategy="procedural",
                mapping={"mode": "triplanar", "uv_set": "UVMap", "real_world_scale_m": 2.0},
                shader_recipe="materials/mat.test/recipe.json",
            )
        ],
    )
    path = tmp_path / "analysis" / "material_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    runtime = load_runtime_shader_recipes(tmp_path, "runtime_test")["mat.test"]
    assert runtime["mapping"]["mode"] == "object"
    assert runtime["cbm_mapping_fallback"] == "triplanar->object"


def test_runtime_loader_rejects_partial_material_plan(tmp_path: Path) -> None:
    """A present plan cannot silently mix authored and legacy SceneSpec materials."""

    analysis = tmp_path / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "scene_spec.json").write_text(
        json.dumps({"job_id": "runtime_test", "materials": [{"id": "mat.a"}, {"id": "mat.b"}]}),
        encoding="utf-8",
    )
    plan = MaterialPlan(
        job_id="runtime_test",
        materials=[MaterialPlanItem(material_id="mat.a", label="A")],
    )
    (analysis / "material_plan.json").write_text(
        plan.model_dump_json(indent=2), encoding="utf-8"
    )

    with pytest.raises(ShaderRecipeRuntimeError, match="cover SceneSpec"):
        load_runtime_shader_recipes(tmp_path, "runtime_test")


def test_runtime_mapping_loader_preserves_all_coordinate_policies(tmp_path: Path) -> None:
    """Build-time UV policy loading does not require a shader recipe or force non-UV modes."""

    plan = MaterialPlan(
        job_id="runtime_test",
        materials=[
            MaterialPlanItem(
                material_id=f"mat.{mode}",
                label=mode,
                mapping={"mode": mode, "uv_set": "DetailUV", "real_world_scale_m": 2.0},
            )
            for mode in ("uv", "object", "generated", "triplanar")
        ],
    )
    path = tmp_path / "analysis" / "material_plan.json"
    path.parent.mkdir(parents=True)
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    mappings = load_runtime_material_mappings(tmp_path, "runtime_test")

    assert mappings["mat.uv"] == {
        "mode": "uv",
        "uv_set": "DetailUV",
        "real_world_scale_m": 2.0,
    }
    assert {value["mode"] for value in mappings.values()} == {
        "uv",
        "object",
        "generated",
        "triplanar",
    }
