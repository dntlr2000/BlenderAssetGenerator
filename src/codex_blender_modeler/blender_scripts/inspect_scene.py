from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
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


def main() -> None:
    """Write a deterministic inventory for geometry, runtime, and modifier provenance."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    objects = []
    families: dict[str, list[dict]] = defaultdict(list)
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        if obj.type not in {"MESH", "CURVE", "CAMERA", "LIGHT"}:
            continue
        bbox_min, bbox_max = world_bbox(obj)
        record = {
            "name": obj.name,
            "type": obj.type,
            "cbm_id": obj.get("cbm_id"),
            "instance_index": obj.get("cbm_instance_index"),
            "geometry_kind": obj.get("cbm_geometry_kind"),
            "location": [round(float(value), 6) for value in obj.location],
            "dimensions": [round(float(value), 6) for value in obj.dimensions],
            "bbox_world": {"min": bbox_min, "max": bbox_max},
            "materials": [slot.material.name for slot in obj.material_slots if slot.material],
            "modifiers": [modifier.type for modifier in obj.modifiers],
            "declared_modifiers": modifier_kinds(obj, "cbm_declared_modifier_kinds"),
            "applied_modifiers": modifier_kinds(obj, "cbm_applied_modifier_kinds"),
        }
        if obj.type == "MESH":
            record["vertices"] = len(obj.data.vertices)
            record["polygons"] = len(obj.data.polygons)
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

    scene = bpy.context.scene
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
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"CBM_INSPECT_OK output={output}")


if __name__ == "__main__":
    main()
