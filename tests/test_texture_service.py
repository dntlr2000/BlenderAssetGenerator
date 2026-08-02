from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.materials import (
    create_material_scaffold,
    load_material_plan,
    load_shader_recipe,
    validate_material_contracts,
)
from codex_blender_modeler.shader_recipe_runtime import load_runtime_shader_recipes
from codex_blender_modeler.texturing import (
    attach_texture_manifest_to_plan,
    generate_job_procedural_textures,
)


def _seed_scene_spec(root: Path, job_id: str) -> Path:
    """Copy one valid SceneSpec into an isolated job for service integration tests."""

    repo = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (repo / "examples" / "measured_box" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    raw["job_id"] = job_id
    path = root / job_id / "analysis" / "scene_spec.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_generation_service_attaches_plan_recipe_and_preserves_scene_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generated maps become the runtime source without mutating approved geometry contracts."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    scene_path = _seed_scene_spec(tmp_path, "texture_service")
    before = scene_path.read_bytes()
    scaffold = create_material_scaffold("texture_service")
    material_id = scaffold.materials[0].material_id

    result = generate_job_procedural_textures(
        "texture_service",
        material_id,
        preset="rock",
        channels=("base_color", "roughness", "normal", "height"),
        resolution=(24, 24),
        seed=91,
    )

    plan = load_material_plan(tmp_path / "texture_service" / "analysis" / "material_plan.json")
    item = next(value for value in plan.materials if value.material_id == material_id)
    assert item.shader_family == "rock"
    assert item.texture_strategy == "image"
    assert item.texture_manifest == result["manifest_relative_path"]
    assert item.shader_recipe is not None
    recipe = load_shader_recipe(tmp_path / "texture_service" / item.shader_recipe)
    assert recipe.family == "rock"
    assert recipe.texture_manifest == item.texture_manifest
    assert scene_path.read_bytes() == before
    runtime = load_runtime_shader_recipes(
        tmp_path / "texture_service", "texture_service"
    )
    assert runtime[material_id]["cbm_texture_manifest"] == item.texture_manifest
    assert Path(runtime[material_id]["cbm_texture_manifest_path"]).is_file()
    scene_spec = json.loads(scene_path.read_text(encoding="utf-8"))
    assert validate_material_contracts(plan, scene_spec, tmp_path / "texture_service").ok


def test_attachment_normalizes_absolute_job_path_to_portable_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An accepted absolute input path is never persisted into portable material contracts."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    _seed_scene_spec(tmp_path, "texture_service")
    scaffold = create_material_scaffold("texture_service")
    material_id = scaffold.materials[0].material_id
    generated = generate_job_procedural_textures(
        "texture_service",
        material_id,
        channels=("base_color",),
        resolution=(16, 16),
        attach=False,
    )

    updated = attach_texture_manifest_to_plan(
        "texture_service", material_id, generated["manifest_path"]
    )
    item = next(value for value in updated.materials if value.material_id == material_id)
    assert item.texture_manifest == generated["manifest_relative_path"]
    assert not Path(item.texture_manifest).is_absolute()


def test_generation_service_accepts_workflow_owned_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detached generation can write exact PNG contracts inside a workflow candidate."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    _seed_scene_spec(tmp_path, "texture_service")
    relative_dir = "workflows/wf-test/artifacts/m/authored/textures/red"
    generated = generate_job_procedural_textures(
        "texture_service",
        "mat.red",
        preset="standardgun_red_paint",
        channels=("base_color", "roughness", "metallic", "normal", "emission"),
        resolution=(32, 32),
        uv_set="UVMap",
        surface_detail_ids=("detail.panel",),
        detail_pattern="panel_atlas",
        output_relative_dir=relative_dir,
        attach=False,
    )

    assert generated["manifest_relative_path"] == f"{relative_dir}/texture_manifest.json"
    assert generated["manifest"]["surface_detail_ids"] == ["detail.panel"]
    assert Path(generated["manifest_path"]).is_file()

    with pytest.raises(ValueError, match="stay inside job root"):
        generate_job_procedural_textures(
            "texture_service",
            "mat.red",
            channels=("base_color",),
            output_relative_dir="../escaped",
            attach=False,
        )


def test_visual_preset_attachment_uses_portable_standard_shader_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attach a stylized map preset without inventing an unsupported shader family."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    _seed_scene_spec(tmp_path, "stylized_service")
    scaffold = create_material_scaffold("stylized_service")
    material_id = scaffold.materials[0].material_id

    generate_job_procedural_textures(
        "stylized_service",
        material_id,
        preset="stylized_clean_red_paint",
        channels=("base_color", "roughness", "metallic", "normal"),
        resolution=(16, 16),
    )

    plan = load_material_plan(
        tmp_path / "stylized_service" / "analysis" / "material_plan.json"
    )
    item = next(value for value in plan.materials if value.material_id == material_id)
    assert item.shader_family == "standard_pbr"
    assert item.shader_recipe is not None
    recipe = load_shader_recipe(tmp_path / "stylized_service" / item.shader_recipe)
    assert recipe.family == "standard_pbr"


def test_spatial_generation_serializes_only_the_selected_uv_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persist an attached UV rectangle without ambiguous null mask fields."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    _seed_scene_spec(tmp_path, "spatial_service")
    scaffold = create_material_scaffold("spatial_service")
    material_id = scaffold.materials[0].material_id
    binding = {
        "detail_id": "detail.panel",
        "parent_object_id": "measured.body",
        "material_id": material_id,
        "uv_set": "UVMap",
        "uv_layout_sha256": "a" * 64,
        "placement": {
            "mode": "uv_rect",
            "uv_rect": [0.2, 0.25, 0.8, 0.75],
        },
        "channels": ["base_color", "roughness", "normal"],
        "strength": 0.35,
        "wrap": "clamp",
    }

    result = generate_job_procedural_textures(
        "spatial_service",
        material_id,
        preset="stylized_clean_red_paint",
        channels=("base_color", "roughness", "metallic", "normal"),
        resolution=(16, 16),
        uv_set="UVMap",
        surface_detail_ids=("detail.panel",),
        surface_detail_bindings=(binding,),
        detail_pattern="panel_atlas",
    )

    raw = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    placement = raw["surface_detail_bindings"][0]["placement"]
    assert placement == {
        "mode": "uv_rect",
        "uv_rect": [0.2, 0.25, 0.8, 0.75],
    }
    plan = load_material_plan(
        tmp_path / "spatial_service" / "analysis" / "material_plan.json"
    )
    item = next(value for value in plan.materials if value.material_id == material_id)
    assert item.shader_family == "standard_pbr"
    assert item.mapping.mode == "uv"
    assert item.mapping.uv_set == "UVMap"
