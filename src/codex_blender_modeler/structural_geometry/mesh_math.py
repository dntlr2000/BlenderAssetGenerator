"""Pure deterministic mesh compilers shared by host tests and Blender builders."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def _as_vec2(value: Sequence[float]) -> Vec2:
    """Convert a two-value sequence into one finite float tuple."""

    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(item) for item in point):
        raise ValueError("geometry contains a non-finite 2D point")
    return point


def _as_vec3(value: Sequence[float]) -> Vec3:
    """Convert a three-value sequence into one finite float tuple."""

    point = (float(value[0]), float(value[1]), float(value[2]))
    if not all(math.isfinite(item) for item in point):
        raise ValueError("geometry contains a non-finite 3D point")
    return point


def _add(left: Vec3, right: Vec3) -> Vec3:
    """Add two 3D vectors."""

    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _subtract(left: Vec3, right: Vec3) -> Vec3:
    """Subtract the right 3D vector from the left vector."""

    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _scale(vector: Vec3, factor: float) -> Vec3:
    """Scale one 3D vector by a scalar."""

    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _dot(left: Vec3, right: Vec3) -> float:
    """Return the dot product of two vectors."""

    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _cross(left: Vec3, right: Vec3) -> Vec3:
    """Return the right-handed cross product of two vectors."""

    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _length(vector: Vec3) -> float:
    """Return one vector's Euclidean length."""

    return math.sqrt(_dot(vector, vector))


def _normalize(vector: Vec3) -> Vec3:
    """Return one normalized vector and reject a zero-length input."""

    length = _length(vector)
    if length <= 1.0e-12:
        raise ValueError("geometry contains a zero-length direction")
    return _scale(vector, 1.0 / length)


def _rotate_about_axis(vector: Vec3, axis: Vec3, radians: float) -> Vec3:
    """Rotate one vector around a normalized axis with Rodrigues' formula."""

    cosine = math.cos(radians)
    sine = math.sin(radians)
    return _add(
        _add(_scale(vector, cosine), _scale(_cross(axis, vector), sine)),
        _scale(axis, _dot(axis, vector) * (1.0 - cosine)),
    )


def _polyline_segments(points: list[Vec3], closed: bool) -> list[tuple[Vec3, Vec3]]:
    """Return ordered segments for an open or closed polyline."""

    segments = list(zip(points, points[1:], strict=False))
    if closed:
        segments.append((points[-1], points[0]))
    return segments


def resample_polyline(
    points: Sequence[Sequence[float]],
    count: int,
    *,
    closed: bool,
) -> list[Vec3]:
    """Resample an ordered polyline at stable equal arc-length positions."""

    source = [_as_vec3(point) for point in points]
    minimum = 3 if closed else 2
    if count < minimum or len(source) < minimum:
        raise ValueError(f"polyline resampling requires at least {minimum} points")
    segments = _polyline_segments(source, closed)
    lengths = [_length(_subtract(end, start)) for start, end in segments]
    if any(length <= 1.0e-12 for length in lengths):
        raise ValueError("polyline contains a zero-length segment")
    total = sum(lengths)
    if closed:
        distances = [total * index / count for index in range(count)]
    else:
        distances = [total * index / (count - 1) for index in range(count)]
    result: list[Vec3] = []
    segment_index = 0
    traversed = 0.0
    for distance in distances:
        while (
            segment_index < len(segments) - 1
            and distance > traversed + lengths[segment_index]
        ):
            traversed += lengths[segment_index]
            segment_index += 1
        start, end = segments[segment_index]
        factor = min(1.0, max(0.0, (distance - traversed) / lengths[segment_index]))
        result.append(_add(start, _scale(_subtract(end, start), factor)))
    return result


def _minimum_twist_offset(reference: list[Vec3], candidate: list[Vec3]) -> int:
    """Return the cyclic offset minimizing squared point correspondence distance."""

    if len(reference) != len(candidate):
        raise ValueError("minimum-twist sections must use the same point count")

    def score(offset: int) -> float:
        """Measure one cyclic section correspondence using squared distance."""

        total = 0.0
        for index, point in enumerate(reference):
            delta = _subtract(point, candidate[(index + offset) % len(candidate)])
            total += _dot(delta, delta)
        return total

    return min(range(len(candidate)), key=score)


def _fan_cap(indices: list[int], *, reverse: bool) -> list[list[int]]:
    """Triangulate one convex-compatible loop as a deterministic index fan."""

    ordered = list(reversed(indices)) if reverse else list(indices)
    return [
        [ordered[0], ordered[index], ordered[index + 1]]
        for index in range(1, len(ordered) - 1)
    ]


def build_loft_mesh(spec: dict[str, Any]) -> dict[str, Any]:
    """Compile validated loft sections into deterministic vertices and quad side faces."""

    raw_sections = spec["sections"]
    closed = bool(raw_sections[0]["closed"])
    default_count = max(len(section["points"]) for section in raw_sections)
    count = int(spec.get("resample_count") or default_count)
    sections = [
        resample_polyline(section["points"], count, closed=closed)
        for section in raw_sections
    ]
    offsets = [int(value) for value in spec.get("twist_offsets", [])]
    if not offsets:
        offsets = [0]
        for index in range(1, len(sections)):
            offsets.append(
                _minimum_twist_offset(sections[index - 1], sections[index])
                if closed and spec.get("correspondence_policy") == "minimum_twist"
                else 0
            )
    for section_index, offset in enumerate(offsets):
        if offset:
            sections[section_index] = (
                sections[section_index][offset:] + sections[section_index][:offset]
            )
    vertices = [point for section in sections for point in section]
    faces: list[list[int]] = []
    side_count = count if closed else count - 1
    for section_index in range(len(sections) - 1):
        first = section_index * count
        second = (section_index + 1) * count
        for point_index in range(side_count):
            next_index = (point_index + 1) % count
            faces.append(
                [
                    first + point_index,
                    first + next_index,
                    second + next_index,
                    second + point_index,
                ]
            )
    if closed and spec.get("cap_policy", "ends") == "ends":
        faces.extend(_fan_cap(list(range(count)), reverse=True))
        final_start = (len(sections) - 1) * count
        faces.extend(
            _fan_cap(list(range(final_start, final_start + count)), reverse=False)
        )
    return {"vertices": vertices, "faces": faces, "findings": []}


def _path_tangents(path: list[Vec3], closed: bool) -> list[Vec3]:
    """Compute stable centered path tangents with endpoint fallbacks."""

    tangents: list[Vec3] = []
    for index in range(len(path)):
        if closed:
            vector = _subtract(
                path[(index + 1) % len(path)],
                path[(index - 1) % len(path)],
            )
        elif index == 0:
            vector = _subtract(path[1], path[0])
        elif index == len(path) - 1:
            vector = _subtract(path[-1], path[-2])
        else:
            vector = _subtract(path[index + 1], path[index - 1])
        tangents.append(_normalize(vector))
    return tangents


def _initial_normal(tangent: Vec3) -> Vec3:
    """Choose the least-parallel world axis and return a stable frame normal."""

    axis = min(
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        key=lambda candidate: abs(_dot(tangent, candidate)),
    )
    return _normalize(_cross(tangent, axis))


def _transport_frames(
    path: list[Vec3], closed: bool
) -> list[tuple[Vec3, Vec3, Vec3]]:
    """Build deterministic parallel-transport tangent, normal, and binormal frames."""

    tangents = _path_tangents(path, closed)
    normal = _initial_normal(tangents[0])
    frames = [(tangents[0], normal, _normalize(_cross(tangents[0], normal)))]
    for index in range(1, len(path)):
        previous_tangent = tangents[index - 1]
        tangent = tangents[index]
        axis = _cross(previous_tangent, tangent)
        axis_length = _length(axis)
        if axis_length > 1.0e-12:
            normalized_axis = _scale(axis, 1.0 / axis_length)
            dot_value = max(-1.0, min(1.0, _dot(previous_tangent, tangent)))
            normal = _rotate_about_axis(
                normal,
                normalized_axis,
                math.atan2(axis_length, dot_value),
            )
        normal = _normalize(_subtract(normal, _scale(tangent, _dot(normal, tangent))))
        frames.append((tangent, normal, _normalize(_cross(tangent, normal))))
    return frames


def build_sweep_mesh(spec: dict[str, Any]) -> dict[str, Any]:
    """Compile a 2D profile along a 3D path using stable transported frames."""

    profile = [_as_vec2(point) for point in spec["profile"]]
    path = [_as_vec3(point) for point in spec["path"]]
    profile_closed = bool(spec.get("profile_closed", True))
    path_closed = bool(spec.get("path_closed", False))
    frames = _transport_frames(path, path_closed)
    scales = [float(value) for value in spec.get("scales", [])] or [1.0] * len(path)
    twists = [float(value) for value in spec.get("twist_degrees", [])] or [0.0] * len(path)
    vertices: list[Vec3] = []
    for center, (tangent, normal, binormal), scale, twist in zip(
        path,
        frames,
        scales,
        twists,
        strict=True,
    ):
        radians = math.radians(twist)
        rotated_normal = _rotate_about_axis(normal, tangent, radians)
        rotated_binormal = _rotate_about_axis(binormal, tangent, radians)
        for x, y in profile:
            vertices.append(
                _add(
                    center,
                    _add(
                        _scale(rotated_normal, x * scale),
                        _scale(rotated_binormal, y * scale),
                    ),
                )
            )
    count = len(profile)
    path_sides = len(path) if path_closed else len(path) - 1
    profile_sides = count if profile_closed else count - 1
    faces: list[list[int]] = []
    for path_index in range(path_sides):
        next_path = (path_index + 1) % len(path)
        for profile_index in range(profile_sides):
            next_profile = (profile_index + 1) % count
            faces.append(
                [
                    path_index * count + profile_index,
                    path_index * count + next_profile,
                    next_path * count + next_profile,
                    next_path * count + profile_index,
                ]
            )
    if (
        profile_closed
        and not path_closed
        and spec.get("cap_policy", "ends") == "ends"
    ):
        faces.extend(_fan_cap(list(range(count)), reverse=True))
        final_start = (len(path) - 1) * count
        faces.extend(
            _fan_cap(list(range(final_start, final_start + count)), reverse=False)
        )
    return {"vertices": vertices, "faces": faces, "findings": []}


def map_extrude_point(axis: str, first: float, second: float, depth: float) -> Vec3:
    """Map profile coordinates and depth onto one selected principal axis."""

    if axis == "X":
        return (depth, first, second)
    if axis == "Y":
        return (first, depth, second)
    if axis == "Z":
        return (first, second, depth)
    raise ValueError(f"unsupported multi-loop extrusion axis: {axis}")


def build_multi_loop_side_mesh(spec: dict[str, Any]) -> dict[str, Any]:
    """Compile deterministic outer and hole side walls; caps are triangulated in Blender."""

    outer = [_as_vec2(point) for point in spec["outer_loop"]]
    holes = [[_as_vec2(point) for point in loop] for loop in spec.get("hole_loops", [])]
    if _signed_area_2d(outer) < 0:
        outer.reverse()
    for hole in holes:
        if _signed_area_2d(hole) > 0:
            hole.reverse()
    loops = [outer, *holes]
    half = float(spec["depth"]) / 2.0
    axis = str(spec.get("axis", "Z"))
    flat = [point for loop in loops for point in loop]
    vertices = [map_extrude_point(axis, *point, -half) for point in flat]
    vertices.extend(map_extrude_point(axis, *point, half) for point in flat)
    faces: list[list[int]] = []
    total = len(flat)
    offset = 0
    for loop_index, loop in enumerate(loops):
        for point_index in range(len(loop)):
            next_index = (point_index + 1) % len(loop)
            first = offset + point_index
            second = offset + next_index
            face = [first, second, total + second, total + first]
            faces.append(face if loop_index == 0 else list(reversed(face)))
        offset += len(loop)
    return {
        "vertices": vertices,
        "faces": faces,
        "loops": loops,
        "flat_profile": flat,
        "findings": [],
    }


def _signed_area_2d(loop: list[Vec2]) -> float:
    """Return one closed 2D loop's signed shoelace area."""

    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(loop, [*loop[1:], loop[0]], strict=True)
    )
