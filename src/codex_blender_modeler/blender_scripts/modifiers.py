from __future__ import annotations

import bpy


def _activate(obj: bpy.types.Object) -> None:
    """Make one object the active Blender target for operator-based modifiers."""

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _mark_modifier_applied(obj: bpy.types.Object, kind: str) -> None:
    """Record one successfully configured modifier kind for deterministic validation."""

    current = str(obj.get("cbm_applied_modifier_kinds", ""))
    kinds = [item for item in current.split(",") if item]
    kinds.append(kind)
    obj["cbm_applied_modifier_kinds"] = ",".join(kinds)


def apply_immediate_modifiers(obj: bpy.types.Object, modifiers: list[dict]) -> None:
    """Configure non-boolean modifiers and record each successful application."""

    for spec in modifiers:
        kind = spec["kind"]
        if kind == "boolean":
            continue
        if kind == "bevel":
            modifier = obj.modifiers.new(name="CBM_Bevel", type="BEVEL")
            modifier.width = float(spec["width"])
            modifier.segments = int(spec.get("segments", 2))
            modifier.limit_method = spec.get("limit_method", "ANGLE")
        elif kind == "mirror":
            modifier = obj.modifiers.new(name="CBM_Mirror", type="MIRROR")
            axes = set(spec.get("axes", ["X"]))
            modifier.use_axis[0] = "X" in axes
            modifier.use_axis[1] = "Y" in axes
            modifier.use_axis[2] = "Z" in axes
            modifier.use_mirror_merge = bool(spec.get("merge", True))
            modifier.merge_threshold = float(spec.get("merge_threshold", 0.001))
        elif kind == "subdivision":
            modifier = obj.modifiers.new(name="CBM_Subdivision", type="SUBSURF")
            modifier.levels = int(spec.get("levels", 2))
            modifier.render_levels = int(spec.get("render_levels", modifier.levels))
            modifier.subdivision_type = spec.get("subdivision_type", "CATMULL_CLARK")
        elif kind == "solidify":
            modifier = obj.modifiers.new(name="CBM_Solidify", type="SOLIDIFY")
            modifier.thickness = float(spec["thickness"])
            modifier.offset = float(spec.get("offset", 0.0))
        elif kind == "array":
            modifier = obj.modifiers.new(name="CBM_Array", type="ARRAY")
            modifier.count = int(spec["count"])
            modifier.use_relative_offset = False
            modifier.use_constant_offset = True
            modifier.constant_offset_displace = tuple(float(value) for value in spec["offset"])
        elif kind == "decimate":
            modifier = obj.modifiers.new(name="CBM_Decimate", type="DECIMATE")
            modifier.ratio = float(spec["ratio"])
        elif kind == "remesh":
            if obj.type != "MESH":
                raise ValueError(f"Remesh requires a mesh object: {obj.name}")
            _activate(obj)
            obj.data.remesh_voxel_size = float(spec["voxel_size"])
            bpy.ops.object.voxel_remesh()
            if spec.get("smooth", False):
                for polygon in obj.data.polygons:
                    polygon.use_smooth = True
        else:
            raise ValueError(f"Unsupported modifier kind: {kind}")
        _mark_modifier_applied(obj, kind)


def apply_deferred_modifiers(
    obj: bpy.types.Object,
    modifier_specs: list[dict],
    object_map: dict[str, list[bpy.types.Object]],
    instance_index: int,
) -> None:
    """Resolve boolean targets after all object families exist in the scene."""

    for spec in modifier_specs:
        if spec["kind"] != "boolean":
            continue
        targets = object_map.get(spec["target_id"])
        if not targets:
            raise ValueError(f"Boolean target is not built: {spec['target_id']}")
        target = targets[min(instance_index, len(targets) - 1)]
        modifier = obj.modifiers.new(name="CBM_Boolean", type="BOOLEAN")
        modifier.operation = spec["operation"]
        modifier.solver = spec.get("solver", "EXACT")
        modifier.object = target
        if spec.get("hide_target", True):
            target.hide_render = True
            target.hide_set(True)
        _mark_modifier_applied(obj, "boolean")
