"""Blender builder for the hardcoded linear_instance_v1 Geometry Nodes template."""

from __future__ import annotations

from pathlib import Path

import bpy


def _activate(obj: bpy.types.Object) -> None:
    """Make one generated object active before applying its whitelisted node modifier."""

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _create_linear_instance_group(spec: dict) -> bpy.types.GeometryNodeTree:
    """Create the exact Mesh Line to realized cube-instance node graph."""

    group = bpy.data.node_groups.new(
        name="CBM_linear_instance_v1",
        type="GeometryNodeTree",
    )
    group.interface.new_socket(
        name="Geometry",
        in_out="OUTPUT",
        socket_type="NodeSocketGeometry",
    )
    nodes = group.nodes
    links = group.links
    output = nodes.new("NodeGroupOutput")
    mesh_line = nodes.new("GeometryNodeMeshLine")
    mesh_line.mode = "OFFSET"
    mesh_line.inputs["Count"].default_value = int(spec["count"])
    mesh_line.inputs["Offset"].default_value = tuple(
        float(value) for value in spec["spacing"]
    )
    cube = nodes.new("GeometryNodeMeshCube")
    cube.inputs["Size"].default_value = tuple(
        float(value) for value in spec["instance_dimensions"]
    )
    instances = nodes.new("GeometryNodeInstanceOnPoints")
    realized = nodes.new("GeometryNodeRealizeInstances")
    links.new(mesh_line.outputs["Mesh"], instances.inputs["Points"])
    links.new(cube.outputs["Mesh"], instances.inputs["Instance"])
    links.new(instances.outputs["Instances"], realized.inputs["Geometry"])
    links.new(realized.outputs["Geometry"], output.inputs["Geometry"])
    return group


def build(spec: dict, _base_dir: Path) -> bpy.types.Object:
    """Evaluate the whitelisted linear instance template into one ordinary mesh."""

    if spec.get("template_id") != "linear_instance_v1":
        raise RuntimeError("unsupported Geometry Nodes template")
    mesh = bpy.data.meshes.new("CBM_LinearInstanceSource")
    obj = bpy.data.objects.new("CBM_LinearInstance", mesh)
    bpy.context.scene.collection.objects.link(obj)
    group = _create_linear_instance_group(spec)
    modifier = obj.modifiers.new(name="CBM_linear_instance_v1", type="NODES")
    modifier.node_group = group
    _activate(obj)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    if not obj.data.vertices or not obj.data.polygons:
        raise RuntimeError("linear_instance_v1 produced an empty mesh")
    obj["cbm_structural_builder_kind"] = "geometry_nodes_template"
    obj["cbm_geometry_nodes_template"] = "linear_instance_v1"
    return obj
