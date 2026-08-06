from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import (  # noqa: E402
    object_inventory,
    operator_kwargs,
    sha256_file,
    write_json,
)


def parse_args() -> argparse.Namespace:
    """Parse one fixed-format external inspection request."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-format", choices=("blend", "fbx", "glb"), required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def import_source(source: Path, source_format: str) -> None:
    """Import a supported interchange source into a factory-startup Blender scene."""

    if source_format == "blend":
        return
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    if source_format == "fbx":
        kwargs = operator_kwargs(bpy.ops.import_scene.fbx, {"filepath": str(source)})
        bpy.ops.import_scene.fbx(**kwargs)
        return
    if source_format == "glb":
        kwargs = operator_kwargs(bpy.ops.import_scene.gltf, {"filepath": str(source)})
        bpy.ops.import_scene.gltf(**kwargs)
        return
    raise ValueError(f"Unsupported external source format: {source_format}")


def json_value(value: Any) -> Any:
    """Convert bounded Blender socket values into stable JSON primitives."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return [round(float(item), 9) for item in value]
    except (TypeError, ValueError):
        return str(value)


def socket_default(node: Any, names: tuple[str, ...], fallback: Any) -> Any:
    """Read a named socket default across Blender-compatible Principled layouts."""

    for name in names:
        socket = node.inputs.get(name)
        if socket is not None and hasattr(socket, "default_value"):
            return json_value(socket.default_value)
    return fallback


def principled_surface(material: Any) -> dict[str, Any]:
    """Extract conservative portable factors from the first Principled node."""

    nodes = material.node_tree.nodes if material.use_nodes and material.node_tree else []
    node = next((item for item in nodes if item.type == "BSDF_PRINCIPLED"), None)
    if node is None:
        diffuse = tuple(float(value) for value in material.diffuse_color)
        return {
            "base_color": list(diffuse),
            "metallic": 0.0,
            "roughness": 0.5,
            "ior": 1.45,
            "transmission_weight": 0.0,
            "alpha": float(diffuse[3]),
            "emission_color": [0.0, 0.0, 0.0, 1.0],
            "emission_strength": 0.0,
            "coat_weight": 0.0,
            "subsurface_weight": 0.0,
            "anisotropic": 0.0,
        }
    base_color = socket_default(node, ("Base Color",), [0.8, 0.8, 0.8, 1.0])
    emission = socket_default(
        node,
        ("Emission Color", "Emission"),
        [0.0, 0.0, 0.0, 1.0],
    )
    return {
        "base_color": base_color,
        "metallic": float(socket_default(node, ("Metallic",), 0.0)),
        "roughness": float(socket_default(node, ("Roughness",), 0.5)),
        "ior": float(socket_default(node, ("IOR",), 1.45)),
        "transmission_weight": float(
            socket_default(node, ("Transmission Weight", "Transmission"), 0.0)
        ),
        "alpha": float(socket_default(node, ("Alpha",), 1.0)),
        "emission_color": emission,
        "emission_strength": float(
            socket_default(node, ("Emission Strength",), 0.0)
        ),
        "coat_weight": float(socket_default(node, ("Coat Weight", "Clearcoat"), 0.0)),
        "subsurface_weight": float(
            socket_default(node, ("Subsurface Weight", "Subsurface"), 0.0)
        ),
        "anisotropic": float(
            socket_default(node, ("Anisotropic IOR Level", "Anisotropic"), 0.0)
        ),
    }


def material_fingerprint(material: Any) -> str:
    """Hash one bounded node-and-link description without embedding host paths."""

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []
    if material.use_nodes and material.node_tree:
        for node in sorted(material.node_tree.nodes, key=lambda item: item.name):
            defaults = {
                socket.identifier or socket.name: json_value(socket.default_value)
                for socket in node.inputs
                if hasattr(socket, "default_value")
            }
            nodes.append(
                {
                    "name": node.name,
                    "type": node.bl_idname,
                    "defaults": defaults,
                }
            )
        for link in material.node_tree.links:
            links.append(
                {
                    "from_node": link.from_node.name,
                    "from_socket": link.from_socket.identifier or link.from_socket.name,
                    "to_node": link.to_node.name,
                    "to_socket": link.to_socket.identifier or link.to_socket.name,
                }
            )
    payload = {
        "name": material.name,
        "use_nodes": bool(material.use_nodes),
        "surface": principled_surface(material),
        "nodes": nodes,
        "links": sorted(
            links,
            key=lambda item: (
                item["from_node"],
                item["from_socket"],
                item["to_node"],
                item["to_socket"],
            ),
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def material_node_trees(material: Any) -> list[Any]:
    """Return every nested material node tree once in deterministic traversal order."""

    if not material.use_nodes or material.node_tree is None:
        return []
    trees: list[Any] = []
    visited: set[int] = set()

    def visit(tree: Any) -> None:
        """Traverse one node tree and recursively include group-node definitions."""

        pointer = int(tree.as_pointer())
        if pointer in visited:
            return
        visited.add(pointer)
        trees.append(tree)
        for node in sorted(tree.nodes, key=lambda item: item.name):
            nested = getattr(node, "node_tree", None)
            if nested is not None:
                visit(nested)

    visit(material.node_tree)
    return trees


def recursive_node_types(material: Any) -> list[str]:
    """List material and nested node-group types while preventing graph cycles."""

    return sorted(
        {
            str(node.bl_idname)
            for tree in material_node_trees(material)
            for node in tree.nodes
        }
    )


def image_dependencies(material: Any) -> list[dict[str, Any]]:
    """List nested image-node dependencies for immutable copying and sanitization."""

    records: list[dict[str, Any]] = []
    for tree in material_node_trees(material):
        for node in sorted(tree.nodes, key=lambda item: item.name):
            if node.type != "TEX_IMAGE" or node.image is None:
                continue
            image = node.image
            packed = image.packed_file is not None
            resolved = ""
            exists = packed
            if image.filepath:
                try:
                    resolved = str(
                        Path(bpy.path.abspath(image.filepath)).expanduser().resolve()
                    )
                    exists = packed or Path(resolved).is_file()
                except (OSError, ValueError):
                    resolved = ""
            records.append(
                {
                    "image_name": image.name,
                    "node_name": f"{tree.name}/{node.name}",
                    "packed": packed,
                    "exists": bool(exists),
                    "resolved_path": resolved,
                    "source": str(image.source),
                }
            )
    return records


def material_object_dependencies(material: Any) -> list[str]:
    """List explicit object pointers that cannot survive static normalization safely."""

    names: set[str] = set()
    for tree in material_node_trees(material):
        for node in tree.nodes:
            value = getattr(node, "object", None)
            if isinstance(value, bpy.types.Object):
                names.add(value.name)
    return sorted(names)


def evaluated_material_slots(obj: bpy.types.Object) -> list[dict[str, Any]]:
    """Report evaluated polygon use per source material slot without saving changes."""

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    try:
        counts = Counter(int(polygon.material_index) for polygon in mesh.polygons)
        slots: list[dict[str, Any]] = []
        for index, slot in enumerate(obj.material_slots):
            polygon_count = counts.get(index, 0)
            if polygon_count <= 0:
                continue
            slots.append(
                {
                    "material_index": index,
                    "material_name": slot.material.name if slot.material else None,
                    "polygon_count": polygon_count,
                }
            )
        unbound_count = sum(
            count for index, count in counts.items() if index >= len(obj.material_slots)
        )
        if not slots or unbound_count:
            slots.append(
                {
                    "material_index": None,
                    "material_name": None,
                    "polygon_count": unbound_count or len(mesh.polygons),
                }
            )
        return slots
    finally:
        bpy.data.meshes.remove(mesh)


def animation_binding_labels() -> list[str]:
    """List datablocks carrying actions, NLA tracks, or drivers outside static scope."""

    candidates: list[tuple[str, Any]] = []
    for obj in bpy.context.scene.objects:
        candidates.append((f"object:{obj.name}", obj))
        if getattr(obj, "data", None) is not None:
            candidates.append((f"data:{obj.name}", obj.data))
            shape_keys = getattr(obj.data, "shape_keys", None)
            if shape_keys is not None:
                candidates.append((f"shape_keys:{obj.name}", shape_keys))
    for material in bpy.data.materials:
        candidates.append((f"material:{material.name}", material))
        if material.node_tree is not None:
            candidates.append((f"material_nodes:{material.name}", material.node_tree))
    labels: list[str] = []
    for label, datablock in candidates:
        animation = getattr(datablock, "animation_data", None)
        if animation is None:
            continue
        if animation.action is not None or animation.drivers or animation.nla_tracks:
            labels.append(label)
    return sorted(set(labels))


def main() -> None:
    """Inspect one immutable external source without saving or changing that source file."""

    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    if sha256_file(source) != args.expected_source_sha256.lower():
        raise RuntimeError("External source hash changed before Blender inspection")
    import_source(source, args.source_format)

    objects: list[dict[str, Any]] = []
    unsupported: list[dict[str, str]] = []
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        if obj.type not in {"MESH", "CURVE"}:
            unsupported.append({"name": obj.name, "type": obj.type})
            continue
        record = object_inventory(obj)
        parent_chain: list[str] = []
        ancestor = obj.parent
        while ancestor is not None:
            parent_chain.append(ancestor.name)
            ancestor = ancestor.parent
        record.update(
            {
                "parent_name": obj.parent.name if obj.parent is not None else None,
                "parent_chain": parent_chain,
                "material_names": [
                    slot.material.name
                    for slot in obj.material_slots
                    if slot.material is not None
                ],
                "material_slots": evaluated_material_slots(obj),
                "has_uv0": bool(obj.type == "MESH" and obj.data.uv_layers),
                "modifiers": [modifier.type for modifier in obj.modifiers],
                "linked_library": bool(obj.library or obj.data.library),
                "hide_render": bool(obj.hide_render),
            }
        )
        objects.append(record)

    used_materials = sorted(
        {
            slot.material
            for obj in bpy.context.scene.objects
            if obj.type in {"MESH", "CURVE"}
            for slot in obj.material_slots
            if slot.material is not None
        },
        key=lambda item: item.name,
    )
    materials = [
        {
            "name": material.name,
            "use_nodes": bool(material.use_nodes),
            "node_fingerprint": material_fingerprint(material),
            "surface": principled_surface(material),
            "images": image_dependencies(material),
            "object_dependencies": material_object_dependencies(material),
            "node_types": recursive_node_types(material),
        }
        for material in used_materials
    ]
    blockers: list[str] = []
    if any(item["type"] == "ARMATURE" for item in unsupported):
        blockers.append("Armature objects are outside External Static Asset Intake scope.")
    if bpy.data.actions:
        blockers.append("Animation actions are outside External Static Asset Intake scope.")
    animated_bindings = animation_binding_labels()
    if animated_bindings:
        blockers.append(
            "Driven or animated datablocks are outside External Static Asset Intake scope: "
            f"{animated_bindings}"
        )
    if any(bool(record.get("linked_library")) for record in objects):
        blockers.append("Linked-library geometry must be made local before intake.")
    scripted_materials = sorted(
        material["name"]
        for material in materials
        if "ShaderNodeScript" in material["node_types"]
    )
    if scripted_materials:
        blockers.append(
            "OSL Script nodes are outside the non-executable material intake scope: "
            f"{scripted_materials}"
        )
    animated_images = sorted(
        image["image_name"]
        for material in materials
        for image in material["images"]
        if image.get("source") in {"MOVIE", "SEQUENCE"}
    )
    if animated_images:
        blockers.append(
            "Movie and image-sequence textures are outside static asset scope: "
            f"{animated_images}"
        )
    object_bound_materials = sorted(
        material["name"]
        for material in materials
        if material.get("object_dependencies")
    )
    if object_bound_materials:
        blockers.append(
            "Material node graphs with explicit object dependencies require manual baking "
            f"before intake: {object_bound_materials}"
        )
    missing_images = sorted(
        {
            image["image_name"]
            for material in materials
            for image in material["images"]
            if not image["exists"]
        }
    )
    if missing_images:
        blockers.append(f"Missing image dependencies: {missing_images}")
    if not objects:
        blockers.append("No mesh or curve objects were found in the external source.")

    report = {
        "schema_version": "0.9.0",
        "kind": "external_static_asset_inspection",
        "ok": not blockers,
        "source_sha256": args.expected_source_sha256.lower(),
        "source_format": args.source_format,
        "runtime": {"blender_version": bpy.app.version_string},
        "units": {
            "system": str(bpy.context.scene.unit_settings.system),
            "scale_length": float(bpy.context.scene.unit_settings.scale_length),
            "length_unit": str(bpy.context.scene.unit_settings.length_unit),
        },
        "objects": objects,
        "materials": materials,
        "unsupported_objects": unsupported,
        "blockers": blockers,
        "warnings": [
            "Arbitrary Blender node graphs are preserved only in the normalized master .blend; "
            "portable delivery requires a derived PBR bake.",
            "Rigging, animation, drivers, gameplay data, and destination-engine graphs "
            "are excluded.",
            "Embedded Blender text scripts are never promoted into the normalized asset.",
        ],
    }
    write_json(output, report)
    print(f"CBM_EXTERNAL_INTAKE_INSPECTED ok={report['ok']} output={output}")


if __name__ == "__main__":
    main()
