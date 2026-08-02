from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from portable_asset_common import sha256_file, uv_layer_metrics  # noqa: E402

from codex_blender_modeler.blender_artifacts import write_json_atomic  # noqa: E402
from codex_blender_modeler.material_manifest import (  # noqa: E402
    MaterialManifestError,
    load_material_manifest,
)


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


def _linked_node(node: bpy.types.Node, socket_name: str) -> bpy.types.Node | None:
    """Return the single upstream node linked to one input socket, if present."""

    socket = node.inputs.get(socket_name)
    if socket is None or len(socket.links) != 1:
        return None
    return socket.links[0].from_node


def _spatial_graph_evidence(
    material: bpy.types.Material,
    bindings: list[dict[str, Any]],
    expected_channels: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Verify actual non-repeating image nodes and their identity UVMap topology."""

    if not bindings:
        return {"status": "not_applicable", "errors": [], "channels": []}
    errors: list[str] = []
    channels = sorted({name for binding in bindings for name in binding["channels"]})
    expected_extension = {
        "clip": "CLIP",
        "clamp": "EXTEND",
    }[str(bindings[0]["wrap"])]
    if not material.use_nodes or material.node_tree is None:
        return {
            "status": "failed",
            "errors": ["Spatial material has no inspectable node tree"],
            "channels": channels,
        }
    for channel in channels:
        node = material.node_tree.nodes.get(f"CBM_{channel}")
        if node is None or node.bl_idname != "ShaderNodeTexImage":
            errors.append(f"Spatial image node CBM_{channel} is missing")
            continue
        if str(getattr(node, "extension", "")) != expected_extension:
            errors.append(
                f"CBM_{channel} extension is not {expected_extension}"
            )
        expected_channel = expected_channels.get(channel)
        if expected_channel is None:
            errors.append(f"CBM_{channel} has no authoritative image-channel evidence")
        elif node.image is None:
            errors.append(f"CBM_{channel} has no loaded image")
        else:
            actual_path = Path(bpy.path.abspath(str(node.image.filepath))).resolve()
            expected_path = Path(expected_channel["resolved_path"]).resolve()
            if str(actual_path).casefold() != str(expected_path).casefold():
                errors.append(f"CBM_{channel} image path differs from the runtime manifest")
            elif not actual_path.is_file():
                errors.append(f"CBM_{channel} image file is missing")
            elif sha256_file(actual_path) != expected_channel["sha256"]:
                errors.append(f"CBM_{channel} image SHA-256 differs from the runtime manifest")
        mapping = _linked_node(node, "Vector")
        if mapping is None or mapping.bl_idname != "ShaderNodeMapping":
            errors.append(f"CBM_{channel} is not linked through one Mapping node")
            continue
        expected_vectors = {
            "Location": (0.0, 0.0, 0.0),
            "Rotation": (0.0, 0.0, 0.0),
            "Scale": (1.0, 1.0, 1.0),
        }
        for socket_name, expected_vector in expected_vectors.items():
            socket = mapping.inputs.get(socket_name)
            if socket is None:
                errors.append(f"CBM_{channel} Mapping has no {socket_name} socket")
                continue
            actual_vector = tuple(float(value) for value in socket.default_value[:3])
            if any(
                abs(actual - expected) > 1e-6
                for actual, expected in zip(
                    actual_vector,
                    expected_vector,
                    strict=True,
                )
            ):
                errors.append(
                    f"CBM_{channel} Mapping {socket_name.lower()} is not identity"
                )
        coordinates = _linked_node(mapping, "Vector")
        if coordinates is None or coordinates.bl_idname != "ShaderNodeUVMap":
            errors.append(f"CBM_{channel} Mapping is not linked from a UV Map node")
        elif str(getattr(coordinates, "uv_map", "")) != "UVMap":
            errors.append(f"CBM_{channel} UV Map node does not select UVMap")
    return {
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "channels": channels,
        "expected_extension": expected_extension,
    }


def _authoritative_spatial_bindings(
    material: bpy.types.Material,
    job_root: Path,
    errors: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    """Load spatial bindings from the exact runtime manifest instead of custom properties."""

    manifest_value = material.get("cbm_texture_manifest")
    if not manifest_value:
        return [], {}
    manifest_path = Path(str(manifest_value)).expanduser().resolve()
    try:
        relative = manifest_path.relative_to(job_root.resolve()).as_posix()
        manifest, _ = load_material_manifest(
            {
                "id": str(material.get("cbm_id", material.name)),
                "texture_manifest": relative,
            },
            job_root,
        )
    except (MaterialManifestError, OSError, ValueError) as exc:
        errors.append(f"Runtime texture manifest is invalid: {exc}")
        return [], {}
    if manifest is None:
        return [], {}
    bindings = [
        {
            "detail_id": binding["detail_id"],
            "parent_object_id": binding["parent_object_id"],
            "material_id": binding["material_id"],
            "uv_set": binding["uv_set"],
            "uv_layout_sha256": binding["uv_layout_sha256"],
            "channels": list(binding["channels"]),
            "wrap": binding["wrap"],
        }
        for binding in manifest.get("surface_detail_bindings", [])
    ]
    bound_channels = {
        name
        for binding in bindings
        for name in binding["channels"]
    }
    provenance = manifest.get("provenance", {})
    generated_hashes = (
        provenance.get("generated_sha256", {})
        if isinstance(provenance, dict)
        else {}
    )
    channel_evidence: dict[str, dict[str, str]] = {}
    for name, channel in manifest.get("channels", {}).items():
        if name not in bound_channels or channel.get("source") != "image":
            continue
        resolved_path = Path(str(channel["resolved_path"]))
        try:
            current_sha256 = sha256_file(resolved_path)
        except OSError as exc:
            errors.append(f"Spatial channel {name} cannot be hashed: {exc}")
            continue
        declared_sha256 = generated_hashes.get(name)
        expected_sha256 = (
            str(declared_sha256).lower()
            if isinstance(declared_sha256, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha256)
            else current_sha256
        )
        if expected_sha256 != current_sha256:
            errors.append(
                f"Spatial channel {name} differs from its declared generation SHA-256"
            )
        channel_evidence[name] = {
            "resolved_path": str(resolved_path),
            "sha256": expected_sha256,
        }
    return bindings, channel_evidence


def material_record(material: bpy.types.Material, job_root: Path) -> dict[str, Any]:
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

    bindings, channel_evidence = _authoritative_spatial_bindings(
        material,
        job_root,
        errors,
    )
    graph_evidence = _spatial_graph_evidence(
        material,
        bindings,
        channel_evidence,
    )
    errors.extend(graph_evidence["errors"])
    try:
        recorded_bindings = json.loads(
            str(material.get("cbm_spatial_bindings", "[]"))
        )
    except json.JSONDecodeError:
        recorded_bindings = []
        errors.append("cbm_spatial_bindings provenance is invalid JSON")
    if not isinstance(recorded_bindings, list) or any(
        not isinstance(item, dict) for item in recorded_bindings
    ):
        recorded_bindings = []
        errors.append("cbm_spatial_bindings provenance must be a JSON array of objects")
    recorded_keys = {
        (
            item.get("detail_id"),
            item.get("parent_object_id"),
            item.get("uv_layout_sha256"),
            item.get("wrap"),
        )
        for item in recorded_bindings
        if isinstance(item, dict)
    }
    authoritative_keys = {
        (
            item["detail_id"],
            item["parent_object_id"],
            item["uv_layout_sha256"],
            item["wrap"],
        )
        for item in bindings
    }
    if recorded_keys != authoritative_keys:
        errors.append("Spatial-binding custom provenance differs from the runtime manifest")
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
        "sampling_mode": material.get("cbm_sampling_mode"),
        "image_wrap": material.get("cbm_image_wrap"),
        "spatial_binding_count": len(bindings),
        "spatial_bindings": bindings,
        "spatial_graph_evidence": graph_evidence,
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
    source_uv_layers = [
        {
            "name": str(layer.name),
            "active_render": bool(layer.active_render),
            **uv_layer_metrics(obj.data, layer),
        }
        for layer in obj.data.uv_layers
    ]
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
                "source_uv_layers": source_uv_layers,
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
            "source_uv_layers": source_uv_layers,
            "active_uv": active_uv.name,
            "triangle_count": len(mesh.loop_triangles),
            "outside_unit_uv_loops": outside,
            "degenerate_uv_triangles": total_degenerate,
            "material_stats": stats,
            "warnings": warnings,
        }
    finally:
        evaluated.to_mesh_clear()


def _spatial_binding_checks(
    materials: list[dict[str, Any]],
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare every runtime spatial binding with its parent object's exact source UV hash."""

    object_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in objects:
        object_records[str(record["object_id"])].append(record)
    checks: list[dict[str, Any]] = []
    for material in materials:
        material_id = str(material["material_id"])
        for binding in material.get("spatial_bindings", []):
            parent_id = str(binding["parent_object_id"])
            uv_set = str(binding["uv_set"])
            expected = str(binding["uv_layout_sha256"])
            parents = object_records.get(parent_id, [])
            actual_hashes: set[str] = set()
            unit_bounds = True
            assigned_to_parent = True
            for parent in parents:
                layer = next(
                    (
                        item
                        for item in parent.get("source_uv_layers", [])
                        if item.get("name") == uv_set
                    ),
                    None,
                )
                if layer is None:
                    continue
                fingerprint = layer.get("vertex_uv_binding_fingerprint")
                if fingerprint:
                    actual_hashes.add(str(fingerprint))
                bounds = layer.get("coordinate_bounds")
                if not bounds:
                    unit_bounds = False
                else:
                    minimum = bounds.get("min", [])
                    maximum = bounds.get("max", [])
                    unit_bounds = unit_bounds and bool(
                        len(minimum) == 2
                        and len(maximum) == 2
                        and all(0.0 <= float(value) <= 1.0 for value in [*minimum, *maximum])
                    )
                assigned_to_parent = assigned_to_parent and any(
                    item.get("material_id") == material_id
                    for item in parent.get("material_stats", [])
                )
            other_users = sorted(
                str(record["object_id"])
                for record in objects
                if str(record["object_id"]) != parent_id
                and any(
                    item.get("material_id") == material_id
                    for item in record.get("material_stats", [])
                )
            )
            graph_ok = material.get("spatial_graph_evidence", {}).get("status") == "passed"
            matches = bool(
                parents
                and actual_hashes == {expected}
                and unit_bounds
                and assigned_to_parent
                and not other_users
                and graph_ok
            )
            checks.append(
                {
                    "detail_id": binding["detail_id"],
                    "parent_object_id": parent_id,
                    "material_id": material_id,
                    "uv_set": uv_set,
                    "expected_uv_layout_sha256": expected,
                    "actual_uv_layout_sha256": sorted(actual_hashes),
                    "unit_uv_bounds": unit_bounds,
                    "assigned_to_parent": assigned_to_parent,
                    "other_material_users": other_users,
                    "spatial_graph_status": material.get(
                        "spatial_graph_evidence", {}
                    ).get("status"),
                    "status": "passed" if matches else "failed",
                    "message": (
                        "Spatial binding matches every parent instance and stays in UV 0..1"
                        if matches
                        else "Spatial binding does not match the current parent UV layout"
                    ),
                }
            )
    return checks


def build_report(job_root: Path) -> dict[str, Any]:
    """Build a machine-readable report for material graphs and mesh UV statistics."""

    materials = [
        material_record(material, job_root)
        for material in sorted(bpy.data.materials, key=lambda item: item.name)
    ]
    objects = [
        object_uv_record(obj)
        for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name)
        if obj.type == "MESH"
    ]
    spatial_checks = _spatial_binding_checks(materials, objects)
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
    errors.extend(
        f"{record['detail_id']}: {record['message']}"
        for record in spatial_checks
        if record["status"] == "failed"
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
        "spatial_binding_checks": spatial_checks,
    }


def main() -> None:
    """Inspect the current blend and atomically write the validation report."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    report = build_report(output.parent.parent)
    write_json_atomic(output, report)
    print(
        "CBM_MATERIAL_INSPECT_OK "
        f"materials={report['summary']['material_count']} output={output}"
    )


if __name__ == "__main__":
    main()
