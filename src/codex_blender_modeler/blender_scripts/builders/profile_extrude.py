from __future__ import annotations

import bpy


def _map_point(axis: str, a: float, b: float, depth_value: float) -> tuple[float, float, float]:
    # The profile pair occupies the two axes orthogonal to the extrusion axis.
    if axis == "X":
        return depth_value, a, b
    if axis == "Y":
        return a, depth_value, b
    if axis == "Z":
        return a, b, depth_value
    raise ValueError(f"Unsupported extrusion axis: {axis}")


def build(spec: dict, _base_dir) -> bpy.types.Object:
    profile = [(float(a), float(b)) for a, b in spec["profile"]]
    depth = float(spec["depth"])
    axis = spec.get("axis", "Y")
    half = depth / 2.0
    count = len(profile)

    vertices = [_map_point(axis, a, b, -half) for a, b in profile]
    vertices.extend(_map_point(axis, a, b, half) for a, b in profile)

    faces: list[list[int]] = []
    if spec.get("cap", True):
        faces.append(list(reversed(range(count))))
        faces.append(list(range(count, count * 2)))
    for index in range(count):
        nxt = (index + 1) % count
        faces.append([index, nxt, count + nxt, count + index])

    mesh = bpy.data.meshes.new("CBM_ProfileExtrude")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("CBM_ProfileExtrude", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
