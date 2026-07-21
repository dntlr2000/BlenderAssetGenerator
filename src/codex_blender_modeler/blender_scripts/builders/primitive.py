from __future__ import annotations

import bpy


def build(spec: dict, _base_dir) -> bpy.types.Object:
    kind = spec["primitive"]
    segments = int(spec.get("segments", 32))
    rings = int(spec.get("ring_segments", 16))

    if kind == "cube":
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    elif kind == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=segments, radius=0.5, depth=1.0, location=(0.0, 0.0, 0.0)
        )
    elif kind == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=segments,
            ring_count=rings,
            radius=0.5,
            location=(0.0, 0.0, 0.0),
        )
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(
            vertices=segments,
            radius1=0.5,
            radius2=0.08,
            depth=1.0,
            location=(0.0, 0.0, 0.0),
        )
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(
            major_radius=0.4,
            minor_radius=0.1,
            major_segments=segments,
            minor_segments=rings,
            location=(0.0, 0.0, 0.0),
        )
    else:
        raise ValueError(f"Unsupported primitive: {kind}")

    obj = bpy.context.active_object
    obj.dimensions = tuple(float(value) for value in spec["dimensions"])
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj
