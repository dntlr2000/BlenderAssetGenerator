from __future__ import annotations

import ast
import math
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_readiness():
    """Load only the pure orchestration function without importing Blender."""

    path = (
        Path(__file__).resolve().parents[1]
        / "src/codex_blender_modeler/blender_scripts/validate_export_roundtrip.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "tangent_readiness"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            function,
        ],
        type_ignores=[],
    )
    namespace = {"math": math}
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["tangent_readiness"]


class UVLayers(list):
    """Expose the minimal collection lookup used by the production selector."""

    @property
    def active(self):
        """Return the first active layer or no layer."""

        return self[0] if self else None

    def get(self, name):
        """Resolve names through fresh collection entries, as Blender does."""

        return next((layer for layer in self if layer.name == name), None)


class Object(dict):
    """Provide native object properties and dictionary custom properties."""


def fixture_object(*, selection="material", invalidation="calc", error=None):
    """Replace collection wrappers while invalidating the previously held RNA."""

    held = SimpleNamespace(name="UVMap", active_render=True)
    layers = UVLayers([held])
    calls = []
    mesh = SimpleNamespace(
        uv_layers=layers,
        loops=[SimpleNamespace(tangent=(1.0, 0.0, 0.0), bitangent_sign=1.0)],
    )

    def invalidate():
        """Keep the real UV identity while making the held wrapper stale."""

        held.name = ""
        layers[:] = [SimpleNamespace(name="UVMap", active_render=True)]

    def calc_tangents(*, uvmap):
        """Record the requested identity before simulating native allocation."""

        calls.append(("calc", uvmap))
        if invalidation in {"calc", "both"}:
            invalidate()
        if error:
            raise error("test native failure")

    def free_tangents():
        """Simulate a separate release-time wrapper invalidation."""

        calls.append(("free",))
        if invalidation in {"free", "both"}:
            invalidate()

    mesh.calc_tangents = calc_tangents
    mesh.free_tangents = free_tangents
    nodes = [SimpleNamespace(type="NORMAL_MAP", uv_map="UVMap")] if selection == "material" else []
    obj = Object()
    obj.data = mesh
    obj.material_slots = [
        SimpleNamespace(material=SimpleNamespace(node_tree=SimpleNamespace(nodes=nodes)))
    ]
    return obj, calls


@pytest.mark.parametrize("selection", ["material", "fallback"])
@pytest.mark.parametrize("invalidation", ["calc", "free", "both"])
def test_tangent_uv_name_survives_native_rna_invalidation(selection, invalidation):
    """Readiness retains the selected scalar name across native RNA replacement."""

    obj, calls = fixture_object(selection=selection, invalidation=invalidation)
    report = load_readiness()(obj)
    assert report["status"] == "ready"
    assert report["uv_set"] == "UVMap"
    assert report["invalid_loop_count"] == 0
    assert report["selection_basis"] == (
        "material_normal_map" if selection == "material" else "active_render_fallback"
    )
    assert calls == [("calc", "UVMap"), ("free",)]
    assert obj.data.uv_layers.get("UVMap").name == "UVMap"


@pytest.mark.parametrize("error", [AttributeError, RuntimeError, TypeError, ValueError])
def test_tangent_error_retains_uv_identity_and_releases(error):
    """Native errors keep their failed result and stable selected UV identity."""

    obj, calls = fixture_object(error=error)
    report = load_readiness()(obj)
    assert report["status"] == "failed"
    assert report["reason"] == "tangent_calculation_error"
    assert report["uv_set"] == "UVMap"
    assert error.__name__ in report["detail"]
    assert calls == [("calc", "UVMap"), ("free",)]


@pytest.mark.parametrize(
    "tangent,sign",
    [
        ((0.0, 0.0, 0.0), 1.0),
        ((float("nan"), 0.0, 0.0), 1.0),
        ((float("inf"), 0.0, 0.0), 1.0),
        ((1.0, 0.0, 0.0), float("nan")),
        ((1.0, 0.0, 0.0), float("inf")),
    ],
)
def test_invalid_tangents_still_fail_after_name_fix(tangent, sign):
    """Pinning identity must never relax the existing finite/nonzero guard."""

    obj, _ = fixture_object()
    obj.data.loops[0] = SimpleNamespace(tangent=tangent, bitangent_sign=sign)
    report = load_readiness()(obj)
    assert report["status"] == "failed"
    assert report["invalid_loop_count"] == 1
    assert report["uv_set"] == "UVMap"


@pytest.mark.parametrize(
    "names,reason",
    [
        (["Missing"], "declared_normal_uv_missing"),
        (["UVMap", "Other"], "declared_normal_uv_ambiguous"),
    ],
)
def test_invalid_material_uv_selection_stays_fail_closed(names, reason):
    """Missing and ambiguous declarations fail before native tangent work."""

    obj, calls = fixture_object()
    obj.material_slots[0].material.node_tree.nodes = [
        SimpleNamespace(type="NORMAL_MAP", uv_map=name) for name in names
    ]
    report = load_readiness()(obj)
    assert report["status"] == "failed"
    assert report["reason"] == reason
    assert calls == []


@pytest.mark.parametrize(
    "case,status,reason",
    [
        ("collider", "not_applicable", "collider"),
        ("missing_uv", "unverified", "missing_uv"),
        ("unsupported", "unverified", "runtime_unsupported"),
    ],
)
def test_unverified_and_inapplicable_outcomes_stay_distinct(case, status, reason):
    """Preserve the existing role, missing-data, and runtime support outcomes."""

    obj, calls = fixture_object()
    if case == "collider":
        obj["cbm_asset_role"] = "collider"
    elif case == "missing_uv":
        obj.data.uv_layers.clear()
    else:
        del obj.data.calc_tangents
    assert load_readiness()(obj) == {"status": status, "reason": reason}
    assert calls == []
