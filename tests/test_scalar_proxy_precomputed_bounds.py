"""Exercise actual scalar-proxy setup without requiring Blender mesh allocation."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_authored_uv_conversion import fixture

from codex_blender_modeler.blender_scripts.portable_authored_uv_proof import mapped_uvs
from codex_blender_modeler.blender_scripts.portable_material_conversion_runtime import (
    resolve_atlas_tiles,
)
from codex_blender_modeler.blender_scripts.portable_uv_scalar_bake import (
    SCALAR_CHANNELS,
    affine_layer_corners,
)


@pytest.mark.parametrize("precomputed,weighted", [(True, True), (False, True), (False, False)])
def test_actual_proxy_setup_reuses_bounds_and_preserves_fallback(precomputed, weighted):
    """Supplying a tile skips allocation while both old fallback policies compute identical UVs."""
    plan, source, _ = fixture()
    policy = plan.atlas_policy.model_dump(mode="json")
    if weighted:
        policy["tile_strategy"] = "area_weighted_rect_v1"
        source.objects[0].vertices[1] = (3.0, 0.0, 0.0)
        source.objects[0].vertices[2] = (3.0, 1.0, 0.0)
    objects = [row.model_dump(mode="json") for row in source.objects]
    bounds = resolve_atlas_tiles(policy, len(objects), objects)[1]
    allocation_calls = []
    target_uvs = []

    def allocate(*args):
        """Observe fallback allocation without altering its policy or geometric calculation."""
        allocation_calls.append(args)
        return resolve_atlas_tiles(*args)

    def map_uvs(points, rectangle):
        """Capture the real affine target UVs before Blender-specific mesh creation."""
        result = mapped_uvs(points, rectangle)
        target_uvs.append(result)
        return result

    def stop_at_mesh_creation(name):
        """Stop after all real proxy layout work and before any native mesh side effect."""
        raise RuntimeError("layout reached native mesh creation")

    path = Path(__file__).resolve().parents[1] / (
        "src/codex_blender_modeler/blender_scripts/portable_uv_scalar_runtime.py"
    )
    tree = ast.parse(path.read_text())
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "make_scalar_proxy")
    namespace = {
        "SCALAR_CHANNELS": SCALAR_CHANNELS,
        "affine_layer_corners": affine_layer_corners,
        "resolve_atlas_tiles": allocate,
        "mapped_uvs": map_uvs,
        "scalar_dependencies": lambda *args: ([], []),
        "bpy": SimpleNamespace(data=SimpleNamespace(
            meshes=SimpleNamespace(new=stop_at_mesh_creation)
        )),
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    material = SimpleNamespace(
        node_tree=SimpleNamespace(animation_data=None), animation_data=None
    )
    obj = SimpleNamespace(material_slots=[SimpleNamespace(material=material)])
    kwargs = {"atlas_policy": policy, "source_objects": objects} if weighted else {}
    if precomputed:
        kwargs["precomputed_bounds"] = bounds
    with pytest.raises(RuntimeError, match="layout reached native mesh creation"):
        namespace[function.name](
            obj, objects[1], 1, len(objects), 2048, 16,
            lambda *args: None, lambda *args: None, **kwargs,
        )
    assert len(allocation_calls) == (0 if precomputed else 1)
    assert target_uvs == [mapped_uvs(objects[1]["uv_layers"]["Layout"], bounds)]


def test_native_conversion_supplies_its_resolved_object_tile():
    """Keep production proxy creation on the existing native allocation, not N re-evaluations."""
    path = Path(__file__).resolve().parents[1] / (
        "src/codex_blender_modeler/blender_scripts/convert_portable_materials.py"
    )
    calls = [node for node in ast.walk(ast.parse(path.read_text()))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "make_scalar_proxy"]
    assert len(calls) == 1
    supplied = next(item.value for item in calls[0].keywords if item.arg == "precomputed_bounds")
    assert isinstance(supplied, ast.Subscript)
    assert isinstance(supplied.value, ast.Name) and supplied.value.id == "tiles"
    assert isinstance(supplied.slice, ast.Name) and supplied.slice.id == "index"
