from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.materials import create_material_scaffold, load_shader_recipe
from codex_blender_modeler.shader_recipe_runtime import load_runtime_shader_recipes


def _seed_scene_spec(root: Path, job_id: str) -> None:
    """Copy a valid bundled SceneSpec into an isolated test workspace."""

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


def test_create_material_scaffold_is_deterministic_and_runtime_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scaffolding writes stable recipe paths without changing SceneSpec content."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    _seed_scene_spec(tmp_path, "scaffold_test")
    spec_path = tmp_path / "scaffold_test" / "analysis" / "scene_spec.json"
    before = spec_path.read_bytes()

    plan = create_material_scaffold("scaffold_test")

    assert plan.stage == "scaffold"
    assert plan.materials
    assert spec_path.read_bytes() == before
    for item in plan.materials:
        assert item.shader_recipe is not None
        recipe = load_shader_recipe(tmp_path / "scaffold_test" / item.shader_recipe)
        assert recipe.material_id == item.material_id
    recipes = load_runtime_shader_recipes(tmp_path / "scaffold_test", "scaffold_test")
    assert set(recipes) == {item.material_id for item in plan.materials}


def test_create_material_scaffold_refuses_implicit_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing material plan remains untouched unless overwrite is explicit."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    _seed_scene_spec(tmp_path, "scaffold_test")
    create_material_scaffold("scaffold_test")
    plan_path = tmp_path / "scaffold_test" / "analysis" / "material_plan.json"
    before = plan_path.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        create_material_scaffold("scaffold_test")

    assert plan_path.read_bytes() == before
