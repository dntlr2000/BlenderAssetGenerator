"""Blender builder for deterministic extrusion of one outer loop and bounded holes."""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

from codex_blender_modeler.structural_geometry.mesh_math import (
    build_multi_loop_side_mesh,
)

from ._structural_mesh import create_mesh_object


def _signed_area(loop: list[tuple[float, float]]) -> float:
    """Return one loop's signed 2D shoelace area."""

    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(loop, [*loop[1:], loop[0]], strict=True)
    )


def _canonical_loops(
    loops: list[list[tuple[float, float]]],
) -> list[list[tuple[float, float]]]:
    """Orient the outer loop counter-clockwise and every hole clockwise."""

    result: list[list[tuple[float, float]]] = []
    for index, loop in enumerate(loops):
        area = _signed_area(loop)
        should_reverse = (index == 0 and area < 0) or (index > 0 and area > 0)
        result.append(list(reversed(loop)) if should_reverse else list(loop))
    return result


def _triangle_area_2d(
    points: list[tuple[float, float]],
    triangle: tuple[int, int, int],
) -> float:
    """Return the unsigned 2D area of one indexed profile triangle."""

    first, second, third = (points[index] for index in triangle)
    return abs(
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    ) / 2.0


def _cross_2d(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    """Return the signed 2D turn from first through second to third."""

    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _point_in_or_on_triangle(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> bool:
    """Return whether a point lies inside or on one counter-clockwise triangle."""

    tolerance = 1.0e-14
    return (
        _cross_2d(first, second, point) >= -tolerance
        and _cross_2d(second, third, point) >= -tolerance
        and _cross_2d(third, first, point) >= -tolerance
    )


def _ear_clip_simple_profile(
    loop: list[tuple[float, float]],
) -> list[tuple[int, int, int]]:
    """Triangulate one simple counter-clockwise profile without skipping boundary edges."""

    remaining = list(range(len(loop)))
    triangles: list[tuple[int, int, int]] = []
    while len(remaining) > 3:
        for position, current in enumerate(remaining):
            previous = remaining[position - 1]
            following = remaining[(position + 1) % len(remaining)]
            if _cross_2d(loop[previous], loop[current], loop[following]) <= 1.0e-14:
                continue
            if any(
                _point_in_or_on_triangle(
                    loop[other],
                    loop[previous],
                    loop[current],
                    loop[following],
                )
                for other in remaining
                if other not in {previous, current, following}
            ):
                continue
            triangles.append((previous, current, following))
            del remaining[position]
            break
        else:
            raise RuntimeError("multi-loop fallback could not find a topology-safe ear")
    final = tuple(remaining)
    if _triangle_area_2d(loop, final) <= 1.0e-14:
        raise RuntimeError("multi-loop fallback returned a degenerate final triangle")
    triangles.append(final)
    return triangles


def _profile_triangle_indices(
    loops: list[list[tuple[float, float]]],
) -> list[tuple[int, int, int]]:
    """Triangulate a validated profile with holes and map results to flat indices."""

    flat = [point for loop in loops for point in loop]
    lookup = {
        (round(point[0], 12), round(point[1], 12)): index
        for index, point in enumerate(flat)
    }
    vectors = [[Vector((point[0], point[1], 0.0)) for point in loop] for loop in loops]
    triangles: list[tuple[int, int, int]] = []
    zero_area_returned = False
    for triangle in tessellate_polygon(vectors):
        indices: list[int] = []
        for item in triangle:
            if isinstance(item, int):
                indices.append(int(item))
                continue
            key = (round(float(item[0]), 12), round(float(item[1]), 12))
            if key not in lookup:
                raise RuntimeError("multi-loop triangulation returned an unknown point")
            indices.append(lookup[key])
        if len(indices) != 3 or len(set(indices)) != 3:
            raise RuntimeError("multi-loop triangulation returned a degenerate triangle")
        triangle = tuple(indices)
        if _triangle_area_2d(flat, triangle) <= 1.0e-14:
            zero_area_returned = True
            continue
        triangles.append(triangle)
    if zero_area_returned:
        if len(loops) != 1:
            raise RuntimeError(
                "multi-loop triangulation returned a degenerate triangle for a holed profile"
            )
        # Blender may bridge a valid comb-shaped outline with zero-area triangles,
        # which either creates invalid faces or drops required boundary incidence.
        triangles = _ear_clip_simple_profile(loops[0])
    expected_area = abs(_signed_area(loops[0])) - sum(
        abs(_signed_area(loop)) for loop in loops[1:]
    )
    actual_area = 0.0
    for triangle in triangles:
        actual_area += _triangle_area_2d(flat, triangle)
    if not triangles or not math.isclose(
        actual_area,
        expected_area,
        rel_tol=1.0e-8,
        abs_tol=1.0e-10,
    ):
        raise RuntimeError("multi-loop cap triangulation did not preserve profile area")
    return triangles


def _oriented_triangle(
    vertices: list[tuple[float, float, float]],
    triangle: tuple[int, int, int],
    desired_normal: tuple[float, float, float],
) -> list[int]:
    """Return a triangle whose geometric normal points toward the requested direction."""

    first, second, third = (Vector(vertices[index]) for index in triangle)
    normal = (second - first).cross(third - first)
    if normal.dot(Vector(desired_normal)) < 0:
        return [triangle[0], triangle[2], triangle[1]]
    return list(triangle)


def build(spec: dict, _base_dir: Path) -> bpy.types.Object:
    """Build one holed profile extrusion with validated deterministic cap tessellation."""

    payload = build_multi_loop_side_mesh(spec)
    if spec.get("cap", True):
        loops = _canonical_loops(payload["loops"])
        triangles = _profile_triangle_indices(loops)
        total = len(payload["flat_profile"])
        axis = str(spec.get("axis", "Z"))
        positive = {
            "X": (1.0, 0.0, 0.0),
            "Y": (0.0, 1.0, 0.0),
            "Z": (0.0, 0.0, 1.0),
        }[axis]
        negative = tuple(-value for value in positive)
        payload["faces"].extend(
            _oriented_triangle(payload["vertices"], triangle, negative)
            for triangle in triangles
        )
        payload["faces"].extend(
            _oriented_triangle(
                payload["vertices"],
                tuple(index + total for index in triangle),
                positive,
            )
            for triangle in triangles
        )
    return create_mesh_object(
        "CBM_MultiLoopExtrude",
        payload,
        builder_kind="multi_loop_extrude",
    )
