"""Blender-only, read-only snapshots and bounded source-UV pinning for authored UV v1."""

from __future__ import annotations

import json
import re
from pathlib import Path

import bpy
from portable_material_conversion_runtime import native_io_path

ATLAS = "CBMPortableAtlas"
MODE = "validated_authored_uv_v1"
MAX_LOOPS = 500000
MAX_OBJECTS = 256


def _render_uv(mesh):
    """Resolve the actual render UV layer used by implicit shader UV consumers."""
    layers = [layer.name for layer in mesh.uv_layers if layer.active_render]
    if len(layers) != 1:
        raise ValueError("authored UV ineligible: ambiguous render UV selection")
    return layers[0]


def _constant_optical_metadata_group(material, node):
    """Recognize only the validated, empty optical-contract thickness metadata owner."""
    from optical_volume_runtime import CONTRACT_KEY, THICKNESS_NODE, read_optical_volume

    # A name is never authority: resolve the exact material-owned contract node first.
    if material.get(CONTRACT_KEY) is None or material.node_tree.nodes.get(THICKNESS_NODE) != node:
        return False
    if read_optical_volume(material) is None:
        return False
    group = node.node_tree
    if (
        node.bl_idname != "ShaderNodeGroup"
        or group is None
        or group.bl_idname != "ShaderNodeTree"
        or re.fullmatch(r"glTF Material Output CBM Optical Volume(?:\.[0-9]{3,})?", group.name)
        is None
        or group.library is not None
        or group.override_library is not None
        or group.animation_data is not None
        or len(group.nodes) != 0
        or len(group.links) != 0
        or len(node.inputs) != 1
        or len(node.outputs) != 0
    ):
        return False
    interface = list(group.interface.items_tree)
    if len(interface) != 1:
        return False
    item = interface[0]
    socket = node.inputs[0]
    return (
        item.item_type == "SOCKET"
        and item.name == "Thickness"
        and item.in_out == "INPUT"
        and item.socket_type == "NodeSocketFloat"
        and socket.name == "Thickness"
        and socket.bl_idname == "NodeSocketFloat"
        and socket.identifier == item.identifier
        and not socket.is_linked
        and not socket.links
        and not any(
            link.from_node == node or link.to_node == node for link in material.node_tree.links
        )
    )


def sampling_bindings(obj, material):
    """Describe UV consumers, allowing only validated UV-independent volume metadata groups."""
    mesh = obj.data
    render = _render_uv(mesh)
    if material.node_tree is None:
        raise ValueError("authored UV ineligible: source material has no node tree")
    if material.node_tree.animation_data or material.animation_data:
        raise ValueError("authored UV ineligible: animated source material")
    bindings = []
    for node in sorted(material.node_tree.nodes, key=lambda item: item.name):
        if node.type == "GROUP" and _constant_optical_metadata_group(material, node):
            continue
        if node.type in {"GROUP", "SCRIPT", "ATTRIBUTE", "TANGENT"}:
            raise ValueError(f"authored UV ineligible: unsupported sampling node {node.type}")
        if (
            node.type == "NEW_GEOMETRY"
            and node.outputs.get("Tangent") is not None
            and node.outputs["Tangent"].is_linked
        ):
            raise ValueError("authored UV ineligible: implicit geometry tangent sampling")
        uv_set = None
        selection = None
        if node.type == "UVMAP":
            if node.from_instancer:
                raise ValueError("authored UV ineligible: instancer UV sampling")
            uv_set = node.uv_map or render
            selection = "uv_map"
        elif node.type == "NORMAL_MAP" and node.space == "TANGENT":
            uv_set = node.uv_map or render
            selection = "normal_map"
        elif node.type == "TEX_IMAGE" and not node.inputs["Vector"].is_linked:
            uv_set = render
            selection = "image_vector"
        elif node.type == "TEX_COORD" and node.outputs["UV"].is_linked:
            if node.from_instancer:
                raise ValueError("authored UV ineligible: instancer texture coordinates")
            uv_set = render
            selection = "texture_coordinate_uv"
        if uv_set is not None:
            if mesh.uv_layers.get(uv_set) is None:
                raise ValueError(f"authored UV ineligible: missing sampled UV layer {uv_set!r}")
            bindings.append(
                {
                    "node_name": node.name,
                    "node_type": node.type,
                    "selection": selection,
                    "uv_set": uv_set,
                }
            )
    return bindings


def snapshot_object(obj, *, source=None):
    """Read exact ordered mesh/UV storage; never normalize or repair source geometry."""
    if bpy.app.version[:3] != (5, 0, 1):
        raise ValueError("validated_authored_uv_v1 requires Blender 5.0.1")
    mesh = obj.data
    if len(mesh.loops) > MAX_LOOPS or not mesh.loops:
        raise ValueError("authored UV ineligible: loop resource limit or empty mesh")
    if any(mod.show_render or mod.show_viewport for mod in obj.modifiers):
        raise ValueError("authored UV ineligible: evaluated modifier topology")
    if mesh.shape_keys or obj.animation_data or mesh.animation_data:
        raise ValueError("authored UV ineligible: animated or shape-key geometry")
    if mesh.users != 1:
        raise ValueError("authored UV ineligible: shared mesh datablock overwrite risk")
    if len(obj.material_slots) != 1 or obj.material_slots[0].material is None:
        raise ValueError("authored UV ineligible: require one material slot")
    material = obj.material_slots[0].material
    if any(poly.material_index != 0 for poly in mesh.polygons):
        raise ValueError("authored UV ineligible: inconsistent polygon material index")
    render = _render_uv(mesh)
    selected = (
        source["source_uv_set"]
        if source
        else str(material.get("cbm_uv_set") or render)
        if str(material.get("cbm_mapping_mode")) == "uv"
        else render
    )
    if mesh.uv_layers.get(selected) is None:
        raise ValueError("authored UV ineligible: selected authored UV layer is missing")
    if source is None and mesh.uv_layers.get(ATLAS) is not None:
        raise ValueError("authored UV ineligible: pre-existing source/target UV layer collision")
    if source is None and len(mesh.uv_layers) >= 8:
        raise ValueError("authored UV ineligible: no free UV layer slot")
    mesh.calc_loop_triangles()
    layers = {}
    for layer in mesh.uv_layers:
        values = [0.0] * (2 * len(mesh.loops))
        layer.uv.foreach_get("vector", values)
        layers[layer.name] = [values[index : index + 2] for index in range(0, len(values), 2)]
    return {
        "identity": {
            "name": obj.name,
            "semantic_id": str(obj.get("cbm_id")),
            "source_object": str(obj.get("cbm_source_object")),
            "asset_role": str(obj.get("cbm_asset_role")),
            "lod_level": int(obj.get("cbm_lod_level", 0)),
            "material_id": str(material.get("cbm_id")),
            "source_material_fingerprint": str(material.get("cbm_material_source_fingerprint")),
        },
        "vertices": [[float(value) for value in vertex.co] for vertex in mesh.vertices],
        "matrix_world": [[float(value) for value in row] for row in obj.matrix_world],
        "polygons": [list(poly.vertices) for poly in mesh.polygons],
        "polygon_materials": [int(poly.material_index) for poly in mesh.polygons],
        "loops": [int(loop.vertex_index) for loop in mesh.loops],
        "polygon_loops": [list(poly.loop_indices) for poly in mesh.polygons],
        "triangles": [list(triangle.loops) for triangle in mesh.loop_triangles],
        "uv_layers": layers,
        "source_uv_set": selected,
        "sampling": sampling_bindings(obj, material),
        "active_uv_set": mesh.uv_layers.active.name if mesh.uv_layers.active else "",
        "render_uv_set": render,
    }


def pin_sampling(material, source):
    """Pin every supported implicit UV consumer to its measured original render layer."""
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    for binding in source["sampling"]:
        node = nodes.get(binding["node_name"])
        if node is None or node.type != binding["node_type"]:
            raise ValueError("authored UV ineligible: source sampling graph changed")
        selected = binding["uv_set"]
        selection = binding["selection"]
        if selection in {"uv_map", "normal_map"}:
            node.uv_map = selected
        else:
            targets = (
                [node.inputs["Vector"]]
                if selection == "image_vector"
                else [link.to_socket for link in list(node.outputs["UV"].links)]
            )
            uv_node = nodes.new("ShaderNodeUVMap")
            uv_node.uv_map = selected
            for target in targets:
                links.new(uv_node.outputs["UV"], target)


def inspection(objects, blend_sha256, *, sources=None):
    """Collect a bounded ordered snapshot for one exact input or saved output blend."""
    if len(objects) > MAX_OBJECTS:
        raise ValueError("authored UV ineligible: object resource limit")
    source_by_name = {item["identity"]["name"]: item for item in (sources or [])}
    if sources is not None and set(source_by_name) != {obj.name for obj in objects}:
        raise ValueError("authored UV proof object coverage changed")
    return {
        "schema_version": "0.1.0",
        "kind": "authored_uv_inspection",
        "uv_method": MODE,
        "blender_version": "5.0.1",
        "blend_sha256": blend_sha256,
        "stage": "target" if sources is not None else "source",
        "objects": [snapshot_object(obj, source=source_by_name.get(obj.name)) for obj in objects],
    }


def read_source(path):
    """Read the internally bound source inspection without accepting duplicate JSON keys."""

    def unique(pairs):
        """Reject duplicate object keys before dict construction can hide them."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate authored UV JSON key")
            result[key] = value
        return result

    with open(native_io_path(Path(path)), "rb") as stream:
        payload = stream.read(128 * 1024 * 1024 + 1)
    if len(payload) > 128 * 1024 * 1024:
        raise ValueError("authored UV source evidence resource limit exceeded")
    return json.loads(payload, object_pairs_hook=unique)
