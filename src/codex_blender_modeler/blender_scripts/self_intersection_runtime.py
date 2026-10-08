"""Bounded exact evaluated-triangle intersections with legitimate shared-boundary handling.

Coordinates are the finite binary floats already produced by Blender. Rational predicates
avoid treating a small but real crossing as legitimate contact through a distance tolerance.
This module has no bpy dependency and grants no geometry or execution authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

Point = tuple[Fraction, Fraction, Fraction]
Point2 = tuple[Fraction, Fraction]
Intersection = Literal["intersects", "clear", "unavailable"]


def _subtract(first: Point, second: Point) -> Point:
    """Subtract exact 3D coordinate triples without float normalization."""

    return tuple(first[index] - second[index] for index in range(3))


def _dot(first: Point, second: Point) -> Fraction:
    """Compute an exact scalar projection of two coordinate triples."""

    return sum((first[index] * second[index] for index in range(3)), Fraction(0))


def _cross(first: Point, second: Point) -> Point:
    """Compute an exact cross product, including a reliable zero-normal predicate."""

    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _plane_interval(
    triangle: tuple[Point, ...], origin: Point, normal: Point, direction: Point
) -> tuple[Fraction, Fraction] | None:
    """Project a triangle's exact plane-intersection segment onto the common line."""

    distances = [_dot(normal, _subtract(point, origin)) for point in triangle]
    points = [point for point, distance in zip(triangle, distances, strict=True) if distance == 0]
    for index in range(3):
        following = (index + 1) % 3
        first, second = distances[index], distances[following]
        if first * second < 0:
            factor = first / (first - second)
            points.append(tuple(
                triangle[index][axis]
                + factor * (triangle[following][axis] - triangle[index][axis])
                for axis in range(3)
            ))
    if not points:
        return None
    projected = [_dot(point, direction) for point in points]
    return min(projected), max(projected)


def _side(point: Point2, start: Point2, end: Point2) -> Fraction:
    """Classify an exact 2D point relative to an oriented clip edge."""

    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def _coplanar_polygon(first: list[Point2], second: list[Point2]) -> list[Point2]:
    """Clip exact coplanar triangles, retaining point/edge contacts as well as area overlap."""

    if _side(second[2], second[0], second[1]) < 0:
        second = list(reversed(second))
    subject = first
    for start, end in zip(second, [*second[1:], second[0]], strict=True):
        if not subject:
            return []
        output = []
        previous = subject[-1]
        previous_side = _side(previous, start, end)
        for current in subject:
            current_side = _side(current, start, end)
            if (current_side >= 0) != (previous_side >= 0):
                factor = previous_side / (previous_side - current_side)
                output.append(tuple(
                    previous[axis] + factor * (current[axis] - previous[axis])
                    for axis in range(2)
                ))
            if current_side >= 0:
                output.append(current)
            previous, previous_side = current, current_side
        subject = output
    return subject


def _within_shared_boundary(point: Point2, shared: list[Point2]) -> bool:
    """Accept only the exact common vertex or closed common edge, never nearby overlap."""

    if len(shared) == 1:
        return point == shared[0]
    first, second = shared
    return _side(point, first, second) == 0 and all(
        min(first[axis], second[axis]) <= point[axis] <= max(first[axis], second[axis])
        for axis in range(2)
    )


@dataclass(frozen=True)
class ExactTriangle:
    """Cache one finite nondegenerate triangle's exact coordinates and plane normal."""

    indices: tuple[int, int, int]
    points: tuple[Point, Point, Point]
    normal: Point


def prepare_exact_triangles(world_vertices: list, triangles: list) -> list[ExactTriangle | None]:
    """Convert each referenced vertex once; invalid and degenerate triangles remain explicit."""

    coordinates: dict[int, Point | None] = {}
    result: list[ExactTriangle | None] = []
    for triangle in triangles:
        try:
            if len(triangle) != 3 or any(
                not isinstance(index, int) or isinstance(index, bool)
                or index < 0 or index >= len(world_vertices) for index in triangle
            ):
                result.append(None)
                continue
            for index in triangle:
                if index in coordinates:
                    continue
                values = tuple(float(value) for value in world_vertices[index])
                coordinates[index] = (
                    tuple(Fraction(value) for value in values)
                    if len(values) == 3 and all(math.isfinite(value) for value in values)
                    else None
                )
            points = tuple(coordinates[index] for index in triangle)
            if any(point is None for point in points):
                result.append(None)
                continue
            normal = _cross(_subtract(points[1], points[0]), _subtract(points[2], points[0]))
            result.append(ExactTriangle(tuple(triangle), points, normal) if any(normal) else None)
        except (IndexError, TypeError, ValueError, ZeroDivisionError, OverflowError):
            result.append(None)
    return result


def _on_segment(point: Point, start: Point, end: Point) -> bool:
    """Prove exact 3D segment membership without tolerances or shared-index assumptions."""

    return not any(_cross(_subtract(point, start), _subtract(end, start))) and all(
        min(start[axis], end[axis]) <= point[axis] <= max(start[axis], end[axis])
        for axis in range(3)
    )


def _boundary_segment(first: Point, second: Point, triangle: tuple[Point, ...]) -> bool:
    """Prove the complete intersection segment lies on one triangle edge, including a point."""

    return any(
        _on_segment(first, start, end) and _on_segment(second, start, end)
        for start, end in zip(triangle, [*triangle[1:], triangle[0]], strict=True)
    )


def _line_point(
    parameter: Fraction, first: ExactTriangle, second: ExactTriangle, direction: Point
) -> Point:
    """Recover a point on the exact two-plane intersection from its scalar line projection."""

    first_distance = _dot(first.normal, first.points[0])
    second_distance = _dot(second.normal, second.points[0])
    first_term = _cross(second.normal, direction)
    second_term = _cross(direction, first.normal)
    denominator = _dot(direction, direction)
    return tuple(
        (first_distance * first_term[axis] + second_distance * second_term[axis]
         + parameter * direction[axis]) / denominator
        for axis in range(3)
    )


def triangle_intersection(first: ExactTriangle, second: ExactTriangle) -> Intersection:
    """Reject overlap or interior intersection while permitting exact contact on both boundaries."""

    shared_indices = sorted(set(first.indices) & set(second.indices))
    if len(shared_indices) == 3:
        return "intersects"
    shared_points = [first.points[first.indices.index(index)] for index in shared_indices]
    direction = _cross(first.normal, second.normal)
    if any(direction):
        first_interval = _plane_interval(first.points, second.points[0], second.normal, direction)
        second_interval = _plane_interval(second.points, first.points[0], first.normal, direction)
        if first_interval is None or second_interval is None:
            return "clear"
        left = max(first_interval[0], second_interval[0])
        right = min(first_interval[1], second_interval[1])
        if left > right:
            return "clear"
        if shared_points:
            allowed = [_dot(point, direction) for point in shared_points]
            if min(allowed) <= left <= right <= max(allowed):
                return "clear"
        first_point = _line_point(left, first, second, direction)
        second_point = _line_point(right, first, second, direction)
        return (
            "clear" if _boundary_segment(first_point, second_point, first.points)
            and _boundary_segment(first_point, second_point, second.points)
            else "intersects"
        )
    if _dot(first.normal, _subtract(second.points[0], first.points[0])) != 0:
        return "clear"
    drop = max(range(3), key=lambda axis: abs(first.normal[axis]))
    axes = [axis for axis in range(3) if axis != drop]
    first2 = [tuple(point[axis] for axis in axes) for point in first.points]
    second2 = [tuple(point[axis] for axis in axes) for point in second.points]
    polygon = _coplanar_polygon(first2, second2)
    if not polygon:
        return "clear"
    area_twice = sum(
        start[0] * end[1] - end[0] * start[1]
        for start, end in zip(polygon, [*polygon[1:], polygon[0]], strict=True)
    )
    if area_twice != 0:
        return "intersects"
    for triangle2 in (first2, second2):
        if not any(
            all(_within_shared_boundary(point, [start, end]) for point in polygon)
            for start, end in zip(triangle2, [*triangle2[1:], triangle2[0]], strict=True)
        ):
            return "intersects"
    return "clear"


def triangle_pair_intersection(
    world_vertices: list, first_indices: tuple[int, int, int], second_indices: tuple[int, int, int]
) -> Intersection:
    """Expose the exact predicate for a standalone pair, refusing malformed triangle evidence."""

    first, second = prepare_exact_triangles(world_vertices, [first_indices, second_indices])
    if first is None or second is None:
        return "unavailable"
    return triangle_intersection(first, second)


def bounded_self_intersection(
    world_vertices: list,
    triangles: list,
    *,
    max_triangles: int,
    max_pair_tests: int,
) -> dict[str, Any]:
    """Use an inclusive AABB sweep and exact predicates within explicit finite work budgets."""

    if len(triangles) > max_triangles:
        return {
            "availability": "unavailable",
            "message": (
                f"Self-intersection budget exceeded: {len(triangles)} > {max_triangles} triangles."
            ),
        }
    if not triangles:
        return {
            "availability": "unavailable",
            "message": "Self-intersection evidence requires at least one triangle.",
        }
    prepared = prepare_exact_triangles(world_vertices, triangles)
    invalid = sum(item is None for item in prepared)
    if invalid:
        return {
            "availability": "unavailable",
            "message": (
                f"Exact self-intersection evidence has {invalid} invalid or degenerate triangles."
            ),
        }
    bounds = [
        (
            tuple(min(float(point[axis]) for point in item.points) for axis in range(3)),
            tuple(max(float(point[axis]) for point in item.points) for axis in range(3)),
        ) for item in prepared
    ]
    active: list[int] = []
    pair_tests = intersections = 0
    exhausted = False
    # Endpoint-inclusive comparisons cannot drop coplanar or shared-boundary candidates.
    for index in sorted(range(len(prepared)), key=lambda item: (bounds[item][0][0], item)):
        minimum, maximum = bounds[index]
        active = [other for other in active if bounds[other][1][0] >= minimum[0]]
        for other in active:
            other_minimum, other_maximum = bounds[other]
            if any(maximum[axis] < other_minimum[axis] or other_maximum[axis] < minimum[axis]
                   for axis in (1, 2)):
                continue
            if pair_tests >= max_pair_tests:
                exhausted = True
                break
            pair_tests += 1
            result = triangle_intersection(prepared[other], prepared[index])
            if result == "intersects":
                intersections += 1
        if exhausted:
            break
        active.append(index)
    detail = (
        f"Exact evaluated-triangle tests found {intersections} intersection pair(s); "
        f"AABB candidate tests={pair_tests}, pair budget exhausted={exhausted}."
    )
    if not intersections and exhausted:
        return {
            "availability": "unavailable",
            "message": detail + (
                f" The {max_pair_tests}-pair exact-test budget prevents a clean pass."
            ),
        }
    return {
        "availability": "available",
        "passed": intersections == 0,
        "measured_value": intersections,
        "threshold": 0,
        "message": detail,
    }
