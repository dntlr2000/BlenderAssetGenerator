"""Exact-byte promoted recipe aliases preserve effective selection and immutable history."""

from __future__ import annotations

import copy
import json

import pytest
import test_authored_material_identity_split as fixtures

from codex_blender_modeler import authored_material_runtime as graph
from codex_blender_modeler import authored_split_runtime as split
from codex_blender_modeler.material_identity_split.authored_materials import (
    prepare_material_derivatives,
)
from codex_blender_modeler.materials.models import MaterialPlan, ShaderRecipe


def promoted_graph(tmp_path, monkeypatch):
    """Model ordinary native promotion copying exact recipe bytes to a workflow locator."""
    root, rules = fixtures.authored_job(tmp_path, monkeypatch, textures=True)
    scene = json.loads((root / "analysis/scene_spec.json").read_bytes())
    plan = json.loads((root / "analysis/material_plan.json").read_bytes())
    item = plan["materials"][0]
    linked = item["shader_recipe"]
    promoted = "workflows/wf-synthetic/artifacts/m/authored/recipes/shared/recipe.json"
    (root / promoted).parent.mkdir(parents=True)
    (root / promoted).write_bytes((root / linked).read_bytes())
    item["shader_recipe"] = promoted
    MaterialPlan.model_validate(plan)
    (root / "analysis/material_plan.json").write_bytes(split.encode(plan))
    return root, scene, plan, [rule.model_dump(mode="json") for rule in rules], linked, promoted


def test_promoted_exact_alias_keeps_effective_ref_and_both_closure_entries(tmp_path, monkeypatch):
    """A copied recipe is accepted without changing the original graph or effective locator."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    before = {path: (root / path).read_bytes() for path in split.SOURCE_PATHS | {linked, promoted}}
    manifest, recipe = graph.material_sources(root, scene, plan, rules[0])
    assert recipe == split.reference(root, promoted)
    assert manifest == split.reference(root, scene["materials"][0]["texture_manifest"])
    closure = graph.material_dependencies(root, scene, plan, [])
    assert closure[linked] == closure[promoted] == recipe["sha256"]
    assert before == {path: (root / path).read_bytes() for path in before}


def test_promoted_alias_projects_all_three_clones_without_source_writes(tmp_path, monkeypatch):
    """Exact metadata projections use the promoted source for each declared synthetic host."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    before = {path: (root / path).read_bytes() for path in split.SOURCE_PATHS | {linked, promoted}}
    staged = {}

    def memory_publisher(path, value):
        """Capture derived bytes in memory rather than publish candidate or authority files."""
        data = value if isinstance(value, bytes) else split.encode(value)
        assert path not in staged or staged[path] == data
        staged[path] = data
        return {"path": path, "sha256": split.sha(data)}

    derivatives = prepare_material_derivatives(
        root, "alias-projection", scene, plan, rules, publisher=memory_publisher
    )
    assert len(derivatives) == 3
    for rule, derivative in zip(rules, derivatives, strict=True):
        assert derivative["source_recipe"] == split.reference(root, promoted)
        candidate = ShaderRecipe.model_validate_json(staged[derivative["candidate_recipe"]["path"]])
        assert candidate.material_id == rule["new_material_id"]
        source = json.loads((root / promoted).read_bytes())
        expected = copy.deepcopy(source)
        expected["material_id"] = rule["new_material_id"]
        expected["texture_manifest"] = derivative["candidate_manifest"]["path"]
        assert json.loads(staged[derivative["candidate_recipe"]["path"]]) == expected
    assert before == {path: (root / path).read_bytes() for path in before}
    assert not (root / split.prefix("alias-projection")).exists()


@pytest.mark.parametrize("selected", ["linked", "promoted"])
def test_one_byte_semantically_equal_difference_is_rejected(tmp_path, monkeypatch, selected):
    """Even JSON-equivalent whitespace cannot be accepted as an identical recipe alias."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    path = root / (linked if selected == "linked" else promoted)
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    assert json.loads(original) == json.loads(path.read_bytes())
    with pytest.raises(ValueError, match="recipe bytes disagree"):
        graph.material_sources(root, scene, plan, rules[0])


def test_equal_alias_bytes_with_foreign_material_are_rejected(tmp_path, monkeypatch):
    """Byte equivalence never relaxes the recipe's exact source material identity."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    value = json.loads((root / promoted).read_bytes())
    value["material_id"] = "mat.foreign"
    for path in (linked, promoted):
        (root / path).write_bytes(split.encode(value))
    with pytest.raises(ValueError, match="foreign material"):
        graph.material_sources(root, scene, plan, rules[0])


@pytest.mark.parametrize("value", [None, ""])
def test_latent_manifest_recipe_is_never_substituted(tmp_path, monkeypatch, value):
    """An available linked recipe does not activate a missing effective MaterialPlan recipe."""
    root, scene, plan, rules, _, _ = promoted_graph(tmp_path, monkeypatch)
    plan["materials"][0]["shader_recipe"] = value
    with pytest.raises(ValueError, match="latent manifest recipe"):
        graph.material_sources(root, scene, plan, rules[0])


@pytest.mark.parametrize(
    "path",
    ["../recipe.json", "/recipe.json", "x/../recipe.json", "x//recipe.json",
     "./recipe.json", "x\\recipe.json", "C:recipe.json", "x/recipe.json/", "missing.json"],
)
def test_effective_alias_path_is_strictly_contained(tmp_path, monkeypatch, path):
    """Allowing identical aliases does not authorize escaped or ambiguous effective locators."""
    root, scene, plan, rules, _, _ = promoted_graph(tmp_path, monkeypatch)
    plan["materials"][0]["shader_recipe"] = path
    with pytest.raises((ValueError, FileNotFoundError)):
        graph.material_sources(root, scene, plan, rules[0])


@pytest.mark.parametrize("selected", ["linked", "promoted"])
def test_linked_alias_file_is_rejected(tmp_path, monkeypatch, selected):
    """Neither locator can bypass the ordinary-file requirement with an identical symlink."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    path = root / (linked if selected == "linked" else promoted)
    backup = path.with_suffix(".original")
    path.rename(backup)
    path.symlink_to(backup.name)
    with pytest.raises(ValueError, match="link"):
        graph.material_sources(root, scene, plan, rules[0])


@pytest.mark.parametrize("selected", ["linked", "promoted"])
def test_each_alias_remains_byte_bounded(tmp_path, monkeypatch, selected):
    """The compatibility comparison rejects an oversized file before JSON parsing."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    path = root / (linked if selected == "linked" else promoted)
    path.write_bytes(path.read_bytes() + b" " * (8 * 1024 * 1024))
    with pytest.raises(ValueError, match="byte bound"):
        graph.material_sources(root, scene, plan, rules[0])


@pytest.mark.parametrize("selected", ["linked", "promoted", "manifest"])
def test_late_mutation_does_not_rebind_checked_source(tmp_path, monkeypatch, selected):
    """A mutation after alias comparison fails the final check of captured references."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    manifest = scene["materials"][0]["texture_manifest"]
    target = root / {"linked": linked, "promoted": promoted, "manifest": manifest}[selected]
    original_read, changed = split.read, []

    def mutate_after_alias_read(job_root, ref, **kwargs):
        """Inject one late file change after returning the initially equivalent alias bytes."""
        data = original_read(job_root, ref, **kwargs)
        if ref["path"] == linked and not changed:
            changed.append(True)
            target.write_bytes(target.read_bytes() + b" ")
        return data

    monkeypatch.setattr(split, "read", mutate_after_alias_read)
    with pytest.raises(ValueError, match="bytes changed"):
        graph.material_sources(root, scene, plan, rules[0])
    assert changed


@pytest.mark.parametrize("selected", ["linked", "promoted", "both"])
def test_bound_closure_rejects_stale_alias_bytes(tmp_path, monkeypatch, selected):
    """Changing either alias, including both to equal new bytes, stales the exact closure."""
    root, scene, plan, rules, linked, promoted = promoted_graph(tmp_path, monkeypatch)
    graph.material_sources(root, scene, plan, rules[0])
    closure = graph.material_dependencies(root, scene, plan, [])
    paths = [linked, promoted] if selected == "both" else [
        linked if selected == "linked" else promoted
    ]
    for path in paths:
        (root / path).write_bytes((root / path).read_bytes() + b" ")
    with pytest.raises(ValueError, match="bytes changed"):
        for path, digest in closure.items():
            split.read(root, {"path": path, "sha256": digest})
    assert graph.material_dependencies(root, scene, plan, []) != closure
