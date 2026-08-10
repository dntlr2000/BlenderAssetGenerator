"""Fail-closed Blender builder for bounded declarative Boolean operation trees."""

from __future__ import annotations

import math
from pathlib import Path

import bpy

from ._structural_mesh import edge_incidence_findings


def _activate(obj: bpy.types.Object) -> None:
    """Make one object the sole active target for context-sensitive Blender operators."""

    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _delete_object(obj: bpy.types.Object) -> None:
    """Remove one temporary Boolean operand and its unreferenced mesh datablock."""

    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.meshes.remove(data)


def _is_live_object(obj: bpy.types.Object) -> bool:
    """Return whether one temporary object still owns a valid Blender RNA handle."""

    try:
        return obj.name in bpy.data.objects
    except ReferenceError:
        return False


def _apply_transform(obj: bpy.types.Object, spec: dict) -> None:
    """Apply one declarative local operand transform before Boolean evaluation."""

    obj.location = tuple(float(value) for value in spec.get("location", (0, 0, 0)))
    obj.rotation_euler = tuple(
        math.radians(float(value))
        for value in spec.get("rotation_deg", (0, 0, 0))
    )
    obj.scale = tuple(float(value) for value in spec.get("scale", (1, 1, 1)))
    _activate(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def _validate_runtime_tree(spec: dict) -> None:
    """Reject malformed runtime trees even when host validation was accidentally skipped."""

    operands = spec.get("operands", [])
    operations = spec.get("operations", [])
    operand_ids = [str(item["id"]) for item in operands]
    operation_ids = [str(item["id"]) for item in operations]
    all_ids = [*operand_ids, *operation_ids]
    if len(operand_ids) < 2 or len(operations) != len(operand_ids) - 1:
        raise RuntimeError("boolean_tree must be a complete binary tree")
    if len(all_ids) != len(set(all_ids)):
        raise RuntimeError("boolean_tree IDs must be unique")
    available = set(operand_ids)
    usage = {item: 0 for item in all_ids}
    for operation in operations:
        left_id, right_id = str(operation["left_id"]), str(operation["right_id"])
        if left_id == right_id or {left_id, right_id} - available:
            raise RuntimeError("boolean_tree operation references invalid or reused inputs")
        usage[left_id] += 1
        usage[right_id] += 1
        available.add(str(operation["id"]))
    root_id = str(spec.get("root_id", ""))
    if not operations or root_id != str(operations[-1]["id"]):
        raise RuntimeError("boolean_tree root must be the final operation")
    if any(count != 1 for item, count in usage.items() if item != root_id):
        raise RuntimeError("boolean_tree nodes must be consumed exactly once")


def build(spec: dict, base_dir: Path) -> bpy.types.Object:
    """Build validated operands and apply an exact, ordered, non-reusing Boolean tree."""

    from .structural_registry import create_structural_geometry

    _validate_runtime_tree(spec)
    nodes: dict[str, bpy.types.Object] = {}
    owned: set[bpy.types.Object] = set()
    try:
        for operand in spec["operands"]:
            obj = create_structural_geometry(operand["geometry"], base_dir)
            owned.add(obj)
            _apply_transform(obj, operand.get("transform", {}))
            obj.name = f"CBM_BooleanOperand_{operand['id']}"
            nodes[str(operand["id"])] = obj
        for operation in spec["operations"]:
            left = nodes.pop(str(operation["left_id"]))
            right = nodes.pop(str(operation["right_id"]))
            _activate(left)
            modifier = left.modifiers.new(
                name=f"CBM_Boolean_{operation['id']}",
                type="BOOLEAN",
            )
            modifier.operation = str(operation["operation"])
            modifier.solver = "EXACT"
            modifier.object = right
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            owned.discard(right)
            _delete_object(right)
            if not left.data.vertices or not left.data.polygons:
                raise RuntimeError(
                    f"boolean_tree operation {operation['id']} produced an empty mesh"
                )
            nodes[str(operation["id"])] = left
        result = nodes[str(spec["root_id"])]
        findings = edge_incidence_findings(result)
        if spec.get("fail_on_non_manifold", True) and any(
            item["severity"] == "error" for item in findings
        ):
            raise RuntimeError("boolean_tree result contains non-manifold edges")
        result.name = "CBM_BooleanTree"
        result["cbm_structural_builder_kind"] = "boolean_tree"
        result["cbm_boolean_solver"] = "EXACT"
        result["cbm_boolean_finding_count"] = len(findings)
        owned.discard(result)
        return result
    finally:
        for obj in list(owned):
            if _is_live_object(obj):
                _delete_object(obj)
