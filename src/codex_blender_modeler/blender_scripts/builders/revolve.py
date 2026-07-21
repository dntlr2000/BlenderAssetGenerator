from __future__ import annotations

import math

import bpy


def _point(axis: str, radius: float, height: float, angle: float) -> tuple[float, float, float]:
    c = math.cos(angle)
    s = math.sin(angle)
    if axis == "X":
        return height, radius * c, radius * s
    if axis == "Y":
        return radius * c, height, radius * s
    if axis == "Z":
        return radius * c, radius * s, height
    raise ValueError(f"Unsupported revolve axis: {axis}")


def _axis_point(axis: str, height: float) -> tuple[float, float, float]:
    if axis == "X":
        return height, 0.0, 0.0
    if axis == "Y":
        return 0.0, height, 0.0
    return 0.0, 0.0, height


def build(spec: dict, _base_dir) -> bpy.types.Object:
    profile = [(float(radius), float(height)) for radius, height in spec["profile"]]
    axis = spec.get("axis", "Z")
    angle_deg = float(spec.get("angle_deg", 360.0))
    segments = int(spec.get("segments", 48))
    closed = math.isclose(angle_deg, 360.0, rel_tol=0.0, abs_tol=1e-6)
    ring_count = segments if closed else segments + 1
    profile_count = len(profile)

    vertices: list[tuple[float, float, float]] = []
    for ring in range(ring_count):
        denominator = segments if not closed else ring_count
        angle = math.radians(angle_deg) * ring / denominator
        vertices.extend(_point(axis, radius, height, angle) for radius, height in profile)

    faces: list[list[int]] = []
    ring_pairs = ring_count if closed else ring_count - 1
    for ring in range(ring_pairs):
        next_ring = (ring + 1) % ring_count
        for item in range(profile_count - 1):
            a = ring * profile_count + item
            b = next_ring * profile_count + item
            faces.append([a, b, b + 1, a + 1])

    if spec.get("cap_ends", True) and closed:
        for profile_index in (0, profile_count - 1):
            radius, height = profile[profile_index]
            if radius <= 1e-9:
                continue
            center_index = len(vertices)
            vertices.append(_axis_point(axis, height))
            ring_indices = [ring * profile_count + profile_index for ring in range(ring_count)]
            if profile_index == 0:
                ring_indices.reverse()
            for index, current in enumerate(ring_indices):
                nxt = ring_indices[(index + 1) % len(ring_indices)]
                faces.append([center_index, current, nxt])

    mesh = bpy.data.meshes.new("CBM_Revolve")
    mesh.from_pydata(vertices, [], faces)
    mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("CBM_Revolve", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
