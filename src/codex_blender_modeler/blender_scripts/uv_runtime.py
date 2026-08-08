from __future__ import annotations

import math
from typing import Any

import bpy


def _activate_mesh(obj: bpy.types.Object) -> None:
    """Select one mesh as the sole active object for UV operators."""

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _smart_project_keywords() -> dict[str, Any]:
    """Feature-probe Blender's Smart UV operator and return portable arguments."""

    identifiers = {
        prop.identifier for prop in bpy.ops.uv.smart_project.get_rna_type().properties
    }
    candidates: dict[str, Any] = {
        "angle_limit": math.radians(66.0),
        "island_margin": 0.02,
        "area_weight": 0.0,
        "correct_aspect": True,
        "scale_to_bounds": True,
    }
    return {name: value for name, value in candidates.items() if name in identifiers}


def ensure_uv_mapping(
    obj: bpy.types.Object,
    mapping: dict[str, Any],
    *,
    generate_if_missing: bool = True,
) -> str:
    """Preserve a requested UV set or deterministically create it when policy permits."""

    mode = str(mapping.get("mode", "object"))
    if mode != "uv":
        return "not_required"
    if obj.type != "MESH" or not isinstance(obj.data, bpy.types.Mesh):
        raise RuntimeError(
            f"UV mapping requires a mesh object: {obj.name} ({obj.type})"
        )
    mesh = obj.data
    if not mesh.polygons:
        raise RuntimeError(f"UV mapping requires faces: {obj.name}")
    uv_set = str(mapping.get("uv_set", "UVMap")).strip()
    if not uv_set:
        raise RuntimeError(f"UV mapping has an empty uv_set: {obj.name}")

    existing = mesh.uv_layers.get(uv_set)
    if existing is not None:
        mesh.uv_layers.active = existing
        existing.active_render = True
        obj["cbm_uv_policy"] = "preserved"
        obj["cbm_uv_set"] = uv_set
        obj["cbm_uv_generated"] = False
        return "preserved"
    if not generate_if_missing:
        raise RuntimeError(
            f"Required existing UV set {uv_set!r} is missing on {obj.name}"
        )

    layer = mesh.uv_layers.new(name=uv_set, do_init=False)
    mesh.uv_layers.active = layer
    layer.active_render = True
    _activate_mesh(obj)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        if not bpy.ops.uv.smart_project.poll():
            raise RuntimeError("Smart UV Project operator is unavailable in the active context")
        result = bpy.ops.uv.smart_project(**_smart_project_keywords())
        if "FINISHED" not in result:
            raise RuntimeError(f"Smart UV Project returned {sorted(result)}")
    except Exception as exc:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if mesh.uv_layers.get(uv_set) is not None:
            mesh.uv_layers.remove(mesh.uv_layers[uv_set])
        raise RuntimeError(f"Failed to generate {uv_set!r} for {obj.name}: {exc}") from exc
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

    mesh.update()
    obj["cbm_uv_policy"] = "smart_project"
    obj["cbm_uv_set"] = uv_set
    obj["cbm_uv_generated"] = True
    return "generated"
