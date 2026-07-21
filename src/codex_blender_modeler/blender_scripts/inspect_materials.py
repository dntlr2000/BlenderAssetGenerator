from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from codex_blender_modeler.blender_artifacts import write_json_atomic  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse the material-inspection report path from Blender arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def image_record(node: bpy.types.Node) -> dict[str, Any] | None:
    """Describe one image-texture node without loading any new external data."""

    image = getattr(node, "image", None)
    if image is None:
        return None
    raw_path = bpy.path.abspath(image.filepath) if image.filepath else ""
    resolved = Path(raw_path).expanduser().resolve() if raw_path else None
    packed = image.packed_file is not None
    size = [int(image.size[0]), int(image.size[1])]
    return {
        "node": node.name,
        "label": node.label,
        "path": str(resolved) if resolved else None,
        "exists": packed or bool(resolved and resolved.is_file()),
        "packed": packed,
        "color_space": image.colorspace_settings.name,
        "size": size,
        "extension": getattr(node, "extension", None),
        "interpolation": getattr(node, "interpolation", None),
    }


def material_record(material: bpy.types.Material) -> dict[str, Any]:
    """Inspect the applied Blender node graph for one stable material ID."""

    errors: list[str] = []
    warnings: list[str] = []
    node_types: list[str] = []
    images: list[dict[str, Any]] = []
    output_nodes: list[bpy.types.Node] = []
    node_count = 0
    link_count = 0
    if not material.use_nodes or material.node_tree is None:
        errors.append("Material does not use a node tree")
    else:
        nodes = list(material.node_tree.nodes)
        node_count = len(nodes)
        link_count = len(material.node_tree.links)
        node_types = sorted(node.bl_idname for node in nodes)
        output_nodes = [node for node in nodes if node.bl_idname == "ShaderNodeOutputMaterial"]
        for node in nodes:
            if node.bl_idname == "ShaderNodeTexImage":
                record = image_record(node)
                if record is None:
                    warnings.append(f"Image node {node.name!r} has no image")
                else:
                    images.append(record)
                    if not record["exists"]:
                        errors.append(f"Image file is missing for node {node.name!r}")
        active_outputs = [node for node in output_nodes if getattr(node, "is_active_output", False)]
        if not output_nodes:
            errors.append("Material has no Material Output node")
        elif not active_outputs:
            warnings.append("Material has no explicitly active Material Output node")
        for output in active_outputs or output_nodes[:1]:
            surface = output.inputs.get("Surface")
            if surface is None or not surface.is_linked:
                errors.append("Active Material Output has no Surface connection")

    uv_set = material.get("cbm_uv_set")
    if uv_set is None:
        warnings.append("Material has no cbm_uv_set provenance")
    return {
        "material_id": material.get("cbm_id", material.name),
        "name": material.name,
        "users": int(material.users),
        "use_nodes": bool(material.use_nodes),
        "node_count": node_count,
        "link_count": link_count,
        "node_types": node_types,
        "images": images,
        "texture_manifest": material.get("cbm_texture_manifest"),
        "source_type": material.get("cbm_material_source_type"),
        "uv_set": uv_set,
        "intended_scale_m": material.get("cbm_intended_scale_m"),
        "errors": errors,
        "warnings": warnings,
    }


def _triangle_uv_area(
    mesh: bpy.types.Mesh,
    triangle: bpy.types.MeshLoopTriangle,
    uv_layer: bpy.types.MeshUVLoopLayer,
) -> float:
    """Calculate one loop triangle's UV area in normalized texture space."""

    uv0, uv1, uv2 = (uv_layer.data[index].uv for index in triangle.loops)
    return abs((uv1.x - uv0.x) * (uv2.y - uv0.y) - (uv1.y - uv0.y) * (uv2.x - uv0.x)) * 0.5


def _triangle_world_area(
    mesh: bpy.types.Mesh,
    triangle: bpy.types.MeshLoopTriangle,
    matrix_world,
) -> float:
    """Calculate one loop triangle's evaluated world-space area in square meters."""

    point0, point1, point2 = (
        matrix_world @ mesh.vertices[index].co for index in triangle.vertices
    )
    return float((point1 - point0).cross(point2 - point0).length * 0.5)


def _material_resolution(material: bpy.types.Material | None) -> tuple[int, int] | None:
    """Return the largest loaded image resolution in one material graph."""

    if material is None or not material.use_nodes or material.node_tree is None:
        return None
    sizes = [
        (int(node.image.size[0]), int(node.image.size[1]))
        for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage"
        and node.image is not None
        and int(node.image.size[0]) > 0
        and int(node.image.size[1]) > 0
    ]
    return max(sizes, key=lambda value: value[0] * value[1]) if sizes else None


def object_uv_record(obj: bpy.types.Object) -> dict[str, Any]:
    """Measure evaluated UV coverage and approximate texel density for one mesh object."""

    warnings: list[str] = []
    dependencies = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(dependencies)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        uv_layers = [layer.name for layer in mesh.uv_layers]
        active_uv = mesh.uv_layers.active
        if active_uv is None:
            return {
                "object_id": obj.get("cbm_id", obj.name),
                "name": obj.name,
                "uv_layers": uv_layers,
                "active_uv": None,
                "triangle_count": len(mesh.loop_triangles),
                "outside_unit_uv_loops": 0,
                "degenerate_uv_triangles": 0,
                "material_stats": [],
                "warnings": ["Mesh has no active UV layer"],
            }

        outside = sum(
            1
            for loop in active_uv.data
            if loop.uv.x < 0.0 or loop.uv.x > 1.0 or loop.uv.y < 0.0 or loop.uv.y > 1.0
        )
        aggregates: dict[int, dict[str, float | int]] = defaultdict(
            lambda: {"world_area_m2": 0.0, "uv_area": 0.0, "triangles": 0, "degenerate": 0}
        )
        for triangle in mesh.loop_triangles:
            polygon = mesh.polygons[triangle.polygon_index]
            slot_index = int(polygon.material_index)
            uv_area = _triangle_uv_area(mesh, triangle, active_uv)
            world_area = _triangle_world_area(mesh, triangle, evaluated.matrix_world)
            aggregates[slot_index]["uv_area"] += uv_area
            aggregates[slot_index]["world_area_m2"] += world_area
            aggregates[slot_index]["triangles"] += 1
            if uv_area <= 1e-12:
                aggregates[slot_index]["degenerate"] += 1

        stats: list[dict[str, Any]] = []
        total_degenerate = 0
        for slot_index, values in sorted(aggregates.items()):
            material = (
                obj.material_slots[slot_index].material
                if slot_index < len(obj.material_slots)
                else None
            )
            material_id = material.get("cbm_id", material.name) if material else None
            resolution = _material_resolution(material)
            world_area = float(values["world_area_m2"])
            uv_area = float(values["uv_area"])
            density = None
            if resolution and world_area > 1e-12 and uv_area > 1e-12:
                density = math.sqrt(uv_area * resolution[0] * resolution[1] / world_area)
            total_degenerate += int(values["degenerate"])
            stats.append(
                {
                    "slot_index": slot_index,
                    "material_id": material_id,
                    "triangles": int(values["triangles"]),
                    "world_area_m2": round(world_area, 8),
                    "uv_area": round(uv_area, 8),
                    "texture_resolution": list(resolution) if resolution else None,
                    "estimated_texel_density_px_per_m": round(density, 3) if density else None,
                }
            )
        if outside:
            warnings.append("UV coordinates extend outside the 0..1 tile")
        if total_degenerate:
            warnings.append("Mesh contains degenerate UV triangles")
        return {
            "object_id": obj.get("cbm_id", obj.name),
            "name": obj.name,
            "uv_layers": uv_layers,
            "active_uv": active_uv.name,
            "triangle_count": len(mesh.loop_triangles),
            "outside_unit_uv_loops": outside,
            "degenerate_uv_triangles": total_degenerate,
            "material_stats": stats,
            "warnings": warnings,
        }
    finally:
        evaluated.to_mesh_clear()


def build_report() -> dict[str, Any]:
    """Build a machine-readable report for material graphs and mesh UV statistics."""

    materials = [
        material_record(material)
        for material in sorted(bpy.data.materials, key=lambda item: item.name)
    ]
    objects = [
        object_uv_record(obj)
        for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name)
        if obj.type == "MESH"
    ]
    errors = [
        f"{record['material_id']}: {message}"
        for record in materials
        for message in record["errors"]
    ]
    warnings = [
        f"{record['material_id']}: {message}"
        for record in materials
        for message in record["warnings"]
    ]
    warnings.extend(
        f"{record['object_id']}: {message}"
        for record in objects
        for message in record["warnings"]
    )
    return {
        "schema_version": "0.5.0",
        "job_id": str(bpy.context.scene.get("cbm_job_id") or "__unknown__"),
        "blender_version": bpy.app.version_string,
        "engine": bpy.context.scene.get(
            "cbm_render_engine", bpy.context.scene.render.engine
        ),
        "device": bpy.context.scene.get("cbm_render_device", "DEFAULT"),
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "material_count": len(materials),
            "mesh_object_count": len(objects),
            "image_node_count": sum(len(record["images"]) for record in materials),
            "objects_without_uv": sum(record["active_uv"] is None for record in objects),
            "degenerate_uv_triangles": sum(
                record["degenerate_uv_triangles"] for record in objects
            ),
        },
        "materials": materials,
        "objects": objects,
    }


def main() -> None:
    """Inspect the current blend and atomically write the validation report."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    report = build_report()
    write_json_atomic(output, report)
    print(
        "CBM_MATERIAL_INSPECT_OK "
        f"materials={report['summary']['material_count']} output={output}"
    )


if __name__ == "__main__":
    main()
