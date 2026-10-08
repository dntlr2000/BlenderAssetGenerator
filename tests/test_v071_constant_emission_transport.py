from __future__ import annotations

import ast
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "src/codex_blender_modeler/blender_scripts/convert_portable_materials.py"
)


def helpers() -> dict[str, Any]:
    """Execute only side-effect-free helpers, keeping Python CI independent of bpy."""
    names = {
        "_active_pure_emission", "_constant_emission_transport", "_surface_semantics",
        "_principled", "_socket", "_json_value", "_portable_surface_factors", "_loss_notes",
    }
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes.extend(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names)
    # These emission-only fixtures have no optical companion; its graph is tested natively.
    namespace: dict[str, Any] = {
        "math": math, "Any": Any, "read_optical_volume": lambda material: None,
    }
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    exec(compile(module, SCRIPT, "exec"), namespace)
    return namespace


def material(color=(0.018, 0.95, 0.32, 1.0), strength=1.7, *, linked=False):
    """Build a minimal active pure-emission fixture with optional linked color."""
    emitter = SimpleNamespace(type="EMISSION", inputs={
        "Color": SimpleNamespace(default_value=color, is_linked=linked),
        "Strength": SimpleNamespace(default_value=strength, is_linked=False),
    })
    output = SimpleNamespace(type="OUTPUT_MATERIAL", is_active_output=True, inputs={
        "Surface": SimpleNamespace(links=[SimpleNamespace(from_node=emitter)]),
    })
    return SimpleNamespace(node_tree=SimpleNamespace(nodes=[output, emitter]),
                           diffuse_color=color, metallic=0.0, roughness=0.1)


def test_exact_source_color_and_strength_are_split_without_clipping():
    """Actual evaluated source color, not a different unused recipe socket, drives transport."""
    h = helpers()
    data = h["_constant_emission_transport"](material())
    assert data["source_color"] == [0.018, 0.95, 0.32, 1.0]
    assert data["baked_color"] == data["source_color"]
    assert data["portable_strength"] == 1.7
    assert [v * data["portable_strength"] for v in data["baked_color"][:3]] == [
        0.018 * 1.7, 0.95 * 1.7, 0.32 * 1.7,
    ]


def test_hdr_color_is_normalized_and_scalar_retained():
    """Colors above one retain finite radiance through a bounded LDR texture."""
    data = helpers()["_constant_emission_transport"](material((2.0, 0.5, 1.0, 1.0), 3.0))
    assert data["baked_color"] == [1.0, 0.25, 0.5, 1.0]
    assert data["portable_strength"] == 6.0


def test_only_explicit_glb_opt_in_selects_new_semantics():
    """Legacy non-GLB callers retain prior factors and a truthful unsupported-source warning."""
    h = helpers()
    for enabled in [False, True]:
        semantics = h["_surface_semantics"](material(), preserve_constant_emission=enabled)
        assert ("constant_pure_emission_transport" in semantics) == enabled
        factors = h["_portable_surface_factors"](semantics)
        assert factors["emission_factor"] == ([1.7] * 3 if enabled else [1.0] * 3)
        notes = " ".join(h["_loss_notes"]("object", semantics))
        assert ("HDR glTF requires" in notes) == enabled
        assert ("unverified" in notes) != enabled
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count('preserve_constant_emission=profile.get("primary_format") == "glb"') == 2


def test_detached_principled_does_not_mask_active_emission():
    """The exact branch follows active Surface despite an unrelated Principled node."""
    m = material()
    m.node_tree.nodes.insert(0, SimpleNamespace(type="BSDF_PRINCIPLED", inputs={}))
    assert helpers()["_constant_emission_transport"](m)["portable_strength"] == 1.7


def test_detached_emission_does_not_override_active_principled():
    """An unused emission node cannot grant a pure-emission preservation claim."""
    m = material()
    m.node_tree.nodes[0].inputs["Surface"].links[0].from_node = SimpleNamespace(
        type="BSDF_PRINCIPLED", inputs={})
    assert helpers()["_constant_emission_transport"](m) is None


def test_inactive_material_output_is_not_authoritative():
    """An inactive output connected to emission is never treated as the active surface."""
    m = material()
    m.node_tree.nodes[0].is_active_output = False
    assert helpers()["_constant_emission_transport"](m) is None


def test_linked_emission_stays_outside_exact_constant_route():
    """Arbitrary linked color graphs are not interpreted as constant emission."""
    h = helpers()
    m = material(linked=True)
    assert h["_constant_emission_transport"](m) is None
    semantics = h["_surface_semantics"](m, preserve_constant_emission=True)
    assert semantics["nonconstant_pure_emission_unverified"] is True


@pytest.mark.parametrize("color,strength", [
    ((-1.0, 0.5, 0.5, 1.0), 1.0), ((math.nan, 0.5, 0.5, 1.0), 1.0),
    ((0.5, 0.5, 0.5, 1.0), math.inf), ((0.5, 0.5, 0.5, 1.0), 0.0),
])
def test_unsupported_constants_are_not_reported_preserved(color, strength):
    """Invalid or zero-strength constants never select the exact positive-HDR route."""
    assert helpers()["_constant_emission_transport"](material(color, strength)) is None


@pytest.mark.parametrize("color,strength", [
    ((1e20, 5e19, 2.5e19, 1.0), 1e20), ((3e38, 1.0, 1.0, 1.0), 2.0),
])
def test_finite_product_above_blender_float32_fails_closed(color, strength):
    """Finite Python products may not silently clamp in a Blender float32 socket."""
    with pytest.raises(RuntimeError, match="float32 strength range"):
        helpers()["_constant_emission_transport"](material(color, strength))
