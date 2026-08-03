from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from assembly_runtime import (  # noqa: E402
    evaluated_basis_in_frame,
    evaluated_bounds_in_frame,
    evaluated_world_bounds,
    matrix_rows,
    resolve_assembly_world_to_frame,
)
from portable_asset_common import uv_layer_metrics  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse the bounded Blender scene-inspection arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def world_bbox(obj: bpy.types.Object) -> tuple[list[float], list[float]]:
    """Return a rounded world-space bounding box for one scene object."""

    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = [min(corner[axis] for corner in corners) for axis in range(3)]
    maximum = [max(corner[axis] for corner in corners) for axis in range(3)]
    return (
        [round(float(value), 6) for value in minimum],
        [round(float(value), 6) for value in maximum],
    )


def inspect_material(material: bpy.types.Material) -> dict:
    """Report deterministic shader nodes, image paths, and manifest metadata."""

    node_types = []
    images = []
    if material.use_nodes and material.node_tree is not None:
        for node in sorted(material.node_tree.nodes, key=lambda item: item.name):
            node_types.append(node.bl_idname)
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                images.append(
                    {
                        "node": node.name,
                        "path": str(Path(bpy.path.abspath(node.image.filepath)).resolve()),
                        "color_space": node.image.colorspace_settings.name,
                    }
                )
    return {
        "material_id": material.get("cbm_id", material.name),
        "name": material.name,
        "texture_manifest": material.get("cbm_texture_manifest"),
        "source_type": material.get("cbm_material_source_type"),
        "uv_set": material.get("cbm_uv_set"),
        "intended_scale_m": material.get("cbm_intended_scale_m"),
        "node_types": sorted(node_types),
        "images": images,
    }


def modifier_kinds(obj: bpy.types.Object, property_name: str) -> list[str]:
    """Decode comma-separated modifier provenance stored on a generated object."""

    value = str(obj.get(property_name, ""))
    return [item for item in value.split(",") if item]


def custom_json(owner: bpy.types.ID, property_name: str, default):
    """Decode one JSON custom property without making inventory output fragile."""

    try:
        return json.loads(str(owner.get(property_name, json.dumps(default))))
    except (TypeError, json.JSONDecodeError):
        return default


def main() -> None:
    """Write a deterministic inventory for geometry, runtime, and modifier provenance."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    objects = []
    families: dict[str, list[dict]] = defaultdict(list)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = bpy.context.scene
    generated_objects = [obj for obj in scene.objects if obj.get("cbm_id")]
    object_map: dict[str, list[bpy.types.Object]] = defaultdict(list)
    for obj in generated_objects:
        object_map[str(obj.get("cbm_id"))].append(obj)
    assembly_policy = str(scene.get("cbm_assembly_policy", "legacy_unbound"))
    assembly_frame = custom_json(scene, "cbm_assembly_frame_json", None)
    world_to_assembly = None
    assembly_frame_error = None
    if assembly_policy == "spatial_v1":
        world_to_assembly, assembly_frame_error = resolve_assembly_world_to_frame(
            assembly_frame,
            object_map,
            depsgraph,
        )
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        if obj.type not in {"MESH", "CURVE", "CAMERA", "LIGHT"}:
            continue
        authored_bbox_min, authored_bbox_max = world_bbox(obj)
        evaluated_bbox = evaluated_world_bounds(obj, depsgraph)
        parent_id = (
            str(obj.parent.get("cbm_id", obj.parent.name))
            if obj.parent is not None
            else None
        )
        relationship_ids = custom_json(obj, "cbm_assembly_relationship_ids", [])
        if not isinstance(relationship_ids, list):
            relationship_ids = []
        assembly_bbox = (
            evaluated_bounds_in_frame([obj], world_to_assembly, depsgraph)
            if obj.get("cbm_id") and world_to_assembly is not None
            else None
        )
        raw_assembly_basis = (
            evaluated_basis_in_frame(obj, world_to_assembly, depsgraph)
            if obj.get("cbm_id") and world_to_assembly is not None
            else None
        )
        assembly_basis = (
            [
                [round(float(value), 9) for value in axis]
                for axis in raw_assembly_basis
            ]
            if raw_assembly_basis is not None
            else None
        )
        record = {
            "name": obj.name,
            "type": obj.type,
            "cbm_id": obj.get("cbm_id"),
            "instance_index": obj.get("cbm_instance_index"),
            "geometry_kind": obj.get("cbm_geometry_kind"),
            "parent_id": parent_id,
            "declared_parent_id": str(obj.get("cbm_parent_id") or "") or None,
            "assembly_role": str(obj.get("cbm_assembly_role", "unclassified")),
            "assembly_relationship_ids": sorted(str(value) for value in relationship_ids),
            "location": [round(float(value), 6) for value in obj.location],
            "rotation_deg": [
                round(math.degrees(float(value)), 6) for value in obj.rotation_euler
            ],
            "scale": [round(float(value), 9) for value in obj.scale],
            "matrix_local": matrix_rows(obj.matrix_local),
            "matrix_world": matrix_rows(obj.matrix_world),
            "dimensions": [round(float(value), 6) for value in obj.dimensions],
            "bbox_world": evaluated_bbox,
            "bbox_world_authored": {
                "min": authored_bbox_min,
                "max": authored_bbox_max,
            },
            "bbox_assembly_frame": assembly_bbox,
            "basis_assembly_frame": assembly_basis,
            "materials": [slot.material.name for slot in obj.material_slots if slot.material],
            "modifiers": [modifier.type for modifier in obj.modifiers],
            "declared_modifiers": modifier_kinds(obj, "cbm_declared_modifier_kinds"),
            "applied_modifiers": modifier_kinds(obj, "cbm_applied_modifier_kinds"),
        }
        if obj.type == "MESH":
            record["vertices"] = len(obj.data.vertices)
            record["polygons"] = len(obj.data.polygons)
            record["active_uv"] = (
                str(obj.data.uv_layers.active.name)
                if obj.data.uv_layers.active is not None
                else None
            )
            record["uv_layers"] = [
                {
                    "name": str(layer.name),
                    "active_render": bool(layer.active_render),
                    **uv_layer_metrics(obj.data, layer),
                }
                for layer in obj.data.uv_layers
            ]
        elif obj.type == "CURVE":
            record["splines"] = len(obj.data.splines)
        objects.append(record)
        if record["cbm_id"]:
            families[str(record["cbm_id"])].append(record)

    family_records = []
    for family_id, members in sorted(families.items()):
        bbox_min = [
            min(member["bbox_world"]["min"][axis] for member in members)
            for axis in range(3)
        ]
        bbox_max = [
            max(member["bbox_world"]["max"][axis] for member in members)
            for axis in range(3)
        ]
        family_records.append(
            {
                "cbm_id": family_id,
                "instance_count": len(members),
                "bbox_world": {"min": bbox_min, "max": bbox_max},
                "dimensions": [round(bbox_max[i] - bbox_min[i], 6) for i in range(3)],
                "center": [round((bbox_max[i] + bbox_min[i]) / 2, 6) for i in range(3)],
            }
        )

    report = {
        "job_id": scene.get("cbm_job_id"),
        "schema_version": scene.get("cbm_schema_version"),
        "blender_version": bpy.app.version_string,
        "render_engine": scene.get("cbm_render_engine", scene.render.engine),
        "render_device": scene.get("cbm_render_device", "DEFAULT"),
        "cycles_compute_backend": scene.get("cbm_cycles_compute_backend"),
        "cycles_devices": scene.get("cbm_cycles_devices"),
        "cycles_samples": scene.get("cbm_cycles_samples"),
        "color_management_look": scene.get(
            "cbm_color_management_look", scene.view_settings.look
        ),
        "object_count": len(objects),
        "objects": objects,
        "families": family_records,
        "materials": sorted(material.name for material in bpy.data.materials),
        "material_details": [
            inspect_material(material)
            for material in sorted(bpy.data.materials, key=lambda item: item.name)
        ],
        "assembly": {
            "policy": assembly_policy,
            "modeling_plan_sha256": scene.get(
                "cbm_assembly_modeling_plan_sha256"
            ),
            "frame": assembly_frame,
            "frame_error": assembly_frame_error,
            "relationship_count": len(
                custom_json(scene, "cbm_assembly_relationships_json", [])
            ),
            "bbox_basis": (
                "evaluated_bbox_corners_in_assembly_frame_meters"
                if world_to_assembly is not None
                else "not_available"
            ),
        },
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"CBM_INSPECT_OK output={output}")


if __name__ == "__main__":
    main()
