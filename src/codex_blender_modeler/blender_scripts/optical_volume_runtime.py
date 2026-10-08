"""Fixed Blender5.0.1 graph transport and closed-boundary checks for optical volumes."""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

import bpy

PACKAGE_SRC = Path(__file__).resolve().parents[2]
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from codex_blender_modeler.blender_scripts.self_intersection_runtime import (  # noqa: E402
    bounded_self_intersection,
)
from codex_blender_modeler.optical_volume import validate_optical_volume  # noqa: E402
from codex_blender_modeler.structural_geometry.triangle_shell_math import (  # noqa: E402
    validate_triangle_shell_data,
)

CONTRACT_KEY = "cbm_optical_volume_contract"
THICKNESS_NODE = "CBM_OpticalVolume_Thickness"
ABSORPTION_NODE = "CBM_OpticalVolume_Absorption"


def _f32(value: float) -> float:
    """Compute exactly the Blender socket storage value of a bounded author scalar."""
    return struct.unpack("<f", struct.pack("<f", value))[0]


def apply_optical_volume(material: Any, contract: dict[str, Any]) -> None:
    """Build only the versioned constant thickness/absorption node pattern, never callbacks."""
    value = validate_optical_volume(contract)
    if bpy.app.version[:3] != (5, 0, 1):
        raise ValueError("Experimental optical volume requires Blender5.0.1")
    nodes = material.node_tree.nodes
    outputs = [node for node in nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output]
    if len(outputs) != 1 or outputs[0].inputs["Volume"].is_linked:
        raise ValueError("Optical volume requires one unused active material volume output")
    if any(node.name in {THICKNESS_NODE, ABSORPTION_NODE} for node in nodes):
        raise ValueError("Optical volume refuses a conflicting existing graph")
    group = bpy.data.node_groups.new("glTF Material Output CBM Optical Volume", "ShaderNodeTree")
    group.interface.new_socket(name="Thickness", in_out="INPUT", socket_type="NodeSocketFloat")
    thickness = nodes.new("ShaderNodeGroup")
    thickness.node_tree = group
    thickness.name = THICKNESS_NODE
    thickness.inputs["Thickness"].default_value = value["thickness_factor"]
    absorption = nodes.new("ShaderNodeVolumeAbsorption")
    absorption.name = ABSORPTION_NODE
    absorption.inputs["Color"].default_value = (*value["attenuation_color"], 1.0)
    distance = value["attenuation_distance"]
    absorption.inputs["Density"].default_value = 0.0 if distance is None else 1.0 / distance
    material.node_tree.links.new(absorption.outputs["Volume"], outputs[0].inputs["Volume"])
    material[CONTRACT_KEY] = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    read_optical_volume(material)


def read_optical_volume(material: Any) -> dict[str, Any] | None:
    """Verify actual constant nodes against their explicit contract before preserving semantics."""
    encoded = material.get(CONTRACT_KEY)
    if encoded is None:
        return None
    if bpy.app.version[:3] != (5, 0, 1):
        raise ValueError("Experimental optical-volume inspection requires Blender5.0.1")
    if not isinstance(encoded, str) or len(encoded) > 2048:
        raise ValueError("Malformed optical-volume native binding")
    value = validate_optical_volume(json.loads(encoded))
    if (
        getattr(material, "animation_data", None) is not None
        or getattr(material.node_tree, "animation_data", None) is not None
    ):
        raise ValueError("Experimental optical volume requires static material factors")
    nodes = material.node_tree.nodes
    thickness = nodes.get(THICKNESS_NODE)
    absorption = nodes.get(ABSORPTION_NODE)
    outputs = [node for node in nodes if node.type == "OUTPUT_MATERIAL" and node.is_active_output]
    if thickness is None or absorption is None or len(outputs) != 1:
        raise ValueError("Optical-volume graph no longer matches its contract")
    if thickness.type != "GROUP" or absorption.type != "VOLUME_ABSORPTION":
        raise ValueError("Optical-volume graph contains an unsupported node")
    socket = thickness.inputs.get("Thickness")
    if (
        socket is None
        or socket.is_linked
        or socket.default_value != _f32(value["thickness_factor"])
    ):
        raise ValueError("Optical-volume thickness is linked, missing or changed")
    if thickness.node_tree is None or not thickness.node_tree.name.startswith(
        "glTF Material Output"
    ):
        raise ValueError("Optical-volume thickness group is not exportable")
    for name in ("Color", "Density"):
        if absorption.inputs[name].is_linked:
            raise ValueError("Optical-volume absorption must remain constant")
    if list(absorption.inputs["Color"].default_value) != [
        *[_f32(x) for x in value["attenuation_color"]],
        1.0,
    ]:
        raise ValueError("Optical-volume absorption color changed")
    distance = value["attenuation_distance"]
    density = 0.0 if distance is None else _f32(1.0 / distance)
    if absorption.inputs["Density"].default_value != density:
        raise ValueError("Optical-volume absorption density changed or clamped")
    links = list(outputs[0].inputs["Volume"].links)
    if len(links) != 1 or links[0].from_node != absorption:
        raise ValueError("Optical-volume absorption is not the active volume output")
    shaders = [node for node in nodes if node.type == "BSDF_PRINCIPLED"]
    if len(shaders) != 1:
        raise ValueError("Optical-volume transport requires one Principled surface")
    shader = shaders[0]
    surface_links = list(outputs[0].inputs["Surface"].links)
    if len(surface_links) != 1 or surface_links[0].from_node != shader:
        raise ValueError("Optical-volume Principled is not the active surface")
    transmission = shader.inputs.get("Transmission Weight")
    if transmission is None or transmission.is_linked or not 0 < transmission.default_value <= 1:
        raise ValueError("Optical-volume transmission must remain a positive constant")
    metallic = shader.inputs["Metallic"]
    ior = shader.inputs["IOR"]
    if metallic.is_linked or metallic.default_value != 0:
        raise ValueError("Optical-volume dielectric requires constant metallic zero")
    if ior.is_linked or not 1 <= ior.default_value <= 3:
        raise ValueError("Optical-volume IOR must be a supported constant in1–3")
    alpha = shader.inputs["Alpha"]
    if alpha.is_linked or alpha.default_value != 1:
        raise ValueError("Optical-volume boundary requires constant alpha one")
    return value


def _owner(material):
    """Resolve evaluated IDs to their original material owner without guessing names."""
    return getattr(material, "original", material) if material is not None else None


def _used_materials(materials, polygons):
    """Resolve only actual used slots, preserving invalid-index failures."""
    result = []
    if not materials and all(face.material_index == 0 for face in polygons):
        return [None] if len(polygons) else []
    for index in sorted({face.material_index for face in polygons}):
        if not 0 <= index < len(materials):
            raise ValueError("Optical material index is outside the evaluated slot table")
        material = materials[index]
        if material not in result:
            result.append(material)
    return result


def _surface_projection(material):
    """Bind the actual constant dielectric scalars that serialized optics depend on."""
    shader = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    return {
        key: float(shader.inputs[socket].default_value)
        for key, socket in (
            ("ior", "IOR"),
            ("transmission", "Transmission Weight"),
            ("metallic", "Metallic"),
            ("alpha", "Alpha"),
        )
    }


def _inspect_boundary(mesh, matrix):
    """Inspect the actual closed outward boundary with unchanged fixed geometry limits."""
    mesh.calc_loop_triangles()
    if len(mesh.loop_triangles) > 4096:
        raise ValueError("Optical-volume native geometry budget exceeded")
    vertices, remap, indices = [], [], {}
    for vertex in mesh.vertices:
        coordinate = tuple(matrix @ vertex.co)
        if not all(math.isfinite(x) and abs(x) <= 1e6 for x in coordinate):
            raise ValueError("Optical-volume coordinate exceeds the finite domain")
        if coordinate not in indices:
            indices[coordinate] = len(vertices)
            vertices.append(list(coordinate))
        remap.append(indices[coordinate])
    triangles = [[remap[i] for i in t.vertices] for t in mesh.loop_triangles]
    validate_triangle_shell_data(
        {"kind": "triangulated_shell", "vertices": vertices, "triangles": triangles}
    )
    exact = bounded_self_intersection(vertices, triangles, max_triangles=4096, max_pair_tests=32768)
    if exact.get("availability") != "available" or exact.get("passed") is not True:
        raise ValueError(f"Optical-volume exact boundary inspection failed: {exact}")
    return {
        "triangles": len(triangles),
        "vertices_after_exact_seam_reconstruction": len(vertices),
        "closed_connected_outward_boundary": True,
        "exact_self_intersection": exact,
    }


def _require_rigid(matrix):
    """Refuse scale, shear and reflections before any mesh-coordinate thickness transport."""
    linear = matrix.to_3x3()
    columns = [linear.col[i] for i in range(3)]
    if linear.determinant() <= 0 or any(
        abs(columns[i].dot(columns[j]) - (1.0 if i == j else 0.0)) > 2e-6
        for i in range(3)
        for j in range(3)
    ):
        raise ValueError("Experimental optical volume requires a rigid unit-scale world transform")


def validate_optical_volume_objects(objects: Any, *, require_stored_geometry=False):
    """Validate only actual assigned volumes; unused materials never activate the branch."""
    if not any(m.get(CONTRACT_KEY) is not None for m in getattr(bpy.data, "materials", [])):
        return []
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    rows, total = [], 0
    for obj in objects:
        if obj.type not in {"MESH", "CURVE", "SURFACE", "FONT", "META"}:
            continue
        original_slots = [slot.material for slot in obj.material_slots]
        evaluated = obj.evaluated_get(deps)
        if obj.type != "MESH" and any(
            m is not None and m.get(CONTRACT_KEY) is not None for m in original_slots
        ):
            raise ValueError("Experimental optical volume supports only explicit mesh objects")
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=deps)
        try:
            if mesh is None:
                if any(m is not None and m.get(CONTRACT_KEY) is not None for m in original_slots):
                    raise ValueError("Optical-volume object has no evaluated mesh boundary")
                continue
            materials = list(mesh.materials)
            evaluated_slots = list(evaluated.material_slots)
            for i, slot in enumerate(evaluated_slots):
                if i < len(materials) and slot.link == "OBJECT":
                    materials[i] = slot.material
            used = _used_materials(materials, mesh.polygons)
            original_used = (
                _used_materials(original_slots, obj.data.polygons) if obj.type == "MESH" else []
            )
            opted = [m for m in used if m is not None and m.get(CONTRACT_KEY) is not None]
            original_opted = [
                m for m in original_used if m is not None and m.get(CONTRACT_KEY) is not None
            ]
            if not opted and not original_opted:
                continue
            if obj.type != "MESH" or evaluated.type != "MESH":
                raise ValueError("Experimental optical volume supports only explicit mesh objects")
            if (
                len(used) != 1
                or len(original_used) != 1
                or len(opted) != 1
                or _owner(used[0]) != _owner(original_used[0])
            ):
                raise ValueError("Optical-volume material bindings cannot be changed by evaluation")
            material = used[0]
            read_optical_volume(_owner(material))
            contract = read_optical_volume(material)
            if (
                getattr(obj, "animation_data", None) is not None
                or getattr(obj.data, "animation_data", None) is not None
                or obj.data.shape_keys is not None
                or any(mod.type == "ARMATURE" for mod in obj.modifiers)
            ):
                raise ValueError("Experimental optical volume requires static mesh objects")
            if require_stored_geometry and len(obj.modifiers):
                raise ValueError("Stored optical-volume export requires materialized mesh geometry")
            _require_rigid(evaluated.matrix_world)
            boundary = _inspect_boundary(mesh, evaluated.matrix_world)
            total += boundary["triangles"]
            if total > 25000:
                raise ValueError("Optical-volume native geometry budget exceeded")
            rows.append(
                {
                    "object": obj.name,
                    "material": _owner(material).name,
                    "material_id": _owner(material).get("cbm_id"),
                    "contract": contract,
                    "surface": _surface_projection(material),
                    "rigid_unit_scale_world_transform": True,
                    **boundary,
                }
            )
        finally:
            evaluated.to_mesh_clear()
    return rows


def scene_has_optical_volume_contract(objects=None):
    """Query actual assigned opt-in boundaries, never orphan material datablocks."""
    if objects is None:
        objects = list(bpy.context.scene.objects)
    return bool(validate_optical_volume_objects(objects))


def verify_exported_optical_volume(path, format_name, expected, *, strict_opt_in=False):
    """Check bounded serialized volume, dielectric factors and real primitive ownership."""
    if not expected and not strict_opt_in:
        return []
    from codex_blender_modeler.optical_volume_gltf import (
        load_optical_gltf,
        verify_optical_document,
    )

    return verify_optical_document(load_optical_gltf(path, format_name), expected)


def _imported_scalar_matches(socket, wanted):
    """Recognize pinned import constants, including metallic texture multiplied by zero."""
    if not socket.is_linked:
        return socket.default_value == wanted
    if wanted != 0 or len(socket.links) != 1:
        return False
    node = socket.links[0].from_node
    if node.type != "MATH" or node.operation != "MULTIPLY":
        return False
    # glTF metallicFactor zero cancels the roughness-packed metallic texture exactly.
    return any(not item.is_linked and item.default_value == 0 for item in node.inputs[:2])


def validate_imported_optical_volume(objects, expected):
    """Recheck actual clean-import graphs and closed boundaries without adding source tags."""
    if not expected:
        return []
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    by_name = {obj.name: obj for obj in objects if obj.type == "MESH"}
    rows, total = [], 0
    for item in expected:
        obj = by_name.get(item["object"])
        if obj is None:
            raise ValueError("Clean import lost an optical object")
        evaluated = obj.evaluated_get(deps)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=deps)
        try:
            used = _used_materials(list(mesh.materials), mesh.polygons)
            if len(used) != 1 or used[0] is None:
                raise ValueError("Clean import changed homogeneous optical material ownership")
            mat = used[0]
            nodes = mat.node_tree.nodes
            outputs = [n for n in nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output]
            shaders = [n for n in nodes if n.type == "BSDF_PRINCIPLED"]
            absorptions = [n for n in nodes if n.type == "VOLUME_ABSORPTION"]
            if len(outputs) != 1 or len(shaders) != 1 or len(absorptions) != 1:
                raise ValueError("Clean import lost the supported optical graph")
            for socket, wanted in (("Surface", shaders[0]), ("Volume", absorptions[0])):
                links = list(outputs[0].inputs[socket].links)
                if len(links) != 1 or links[0].from_node != wanted:
                    raise ValueError("Clean import optical graph is not active")
            for key, socket in (
                ("ior", "IOR"),
                ("transmission", "Transmission Weight"),
                ("metallic", "Metallic"),
                ("alpha", "Alpha"),
            ):
                actual = shaders[0].inputs[socket]
                if not _imported_scalar_matches(actual, item["surface"][key]):
                    raise ValueError("Clean import optical surface scalar changed: " + key)
            contract = validate_optical_volume(item["contract"])
            absorption = absorptions[0]
            if any(absorption.inputs[k].is_linked for k in ("Color", "Density")):
                raise ValueError("Clean import optical absorption is no longer constant")
            if list(absorption.inputs["Color"].default_value) != [
                *[_f32(v) for v in contract["attenuation_color"]],
                1.0,
            ]:
                raise ValueError("Clean import optical absorption color changed")
            distance = contract["attenuation_distance"]
            if absorption.inputs["Density"].default_value != (
                0.0 if distance is None else _f32(1 / distance)
            ):
                raise ValueError("Clean import optical absorption density changed")
            thicknesses = [
                n.inputs.get("Thickness")
                for n in nodes
                if n.type == "GROUP"
                and n.node_tree
                and n.node_tree.name.startswith("glTF Material Output")
            ]
            if (
                len(thicknesses) != 1
                or thicknesses[0] is None
                or thicknesses[0].is_linked
                or (thicknesses[0].default_value != _f32(contract["thickness_factor"]))
            ):
                raise ValueError("Clean import optical thickness changed")
            _require_rigid(evaluated.matrix_world)
            boundary = _inspect_boundary(mesh, evaluated.matrix_world)
            if boundary["triangles"] != item["triangles"]:
                raise ValueError("Clean import optical triangle count changed")
            total += boundary["triangles"]
            if total > 25000:
                raise ValueError("Optical-volume imported geometry budget exceeded")
            rows.append(
                {
                    "object": obj.name,
                    "source_material": item["material"],
                    "imported_material": mat.name,
                    "actual_import_graph_verified": True,
                    "destination_support_verified": False,
                    **boundary,
                }
            )
        finally:
            evaluated.to_mesh_clear()
    return rows
