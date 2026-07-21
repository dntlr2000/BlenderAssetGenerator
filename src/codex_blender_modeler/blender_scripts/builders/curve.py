from __future__ import annotations

import bpy


def build(spec: dict, _base_dir) -> bpy.types.Object:
    curve_data = bpy.data.curves.new("CBM_Curve", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = int(spec.get("resolution_u", 12))
    curve_data.bevel_depth = float(spec.get("bevel_depth", 0.05))
    curve_data.bevel_resolution = int(spec.get("bevel_resolution", 3))
    curve_data.resolution_u = int(spec.get("resolution_u", 12))

    spline_type = spec.get("spline_type", "POLY")
    spline = curve_data.splines.new(type=spline_type)
    points = spec["points"]
    spline.points.add(len(points) - 1)
    for target, source in zip(spline.points, points, strict=True):
        target.co = (float(source[0]), float(source[1]), float(source[2]), 1.0)
    spline.use_cyclic_u = bool(spec.get("cyclic", False))
    if spline_type == "NURBS":
        spline.order_u = min(4, len(points))
        spline.use_endpoint_u = True

    obj = bpy.data.objects.new("CBM_Curve", curve_data)
    bpy.context.scene.collection.objects.link(obj)
    if spec.get("convert_to_mesh", True):
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.convert(target="MESH")
        obj = bpy.context.active_object
    return obj
