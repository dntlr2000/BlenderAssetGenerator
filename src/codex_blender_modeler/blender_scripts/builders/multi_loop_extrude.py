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
        triangles.append(tuple(indices))
    expected_area = abs(_signed_area(loops[0])) - sum(
        abs(_signed_area(loop)) for loop in loops[1:]
    )
    actual_area = 0.0
    for first, second, third in triangles:
        a, b, c = flat[first], flat[second], flat[third]
        actual_area += abs(
            (b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0])
        ) / 2.0
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
