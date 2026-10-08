"""Read-only exact projected centerline coverage against explicit support triangles.

This proves continuous XZ centerline coverage only. It does not prove finite-width
coverage, 3D contact, mechanical support, or whether a bridge is artistically valid.
No geometry, policy, callback, schema, or approval authority is introduced.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

Point = tuple[Fraction, Fraction]
Interval = tuple[Fraction, Fraction]
_MAX_PATH_POINTS = 129
_MAX_SUPPORT_VERTICES = 65536
_MAX_SUPPORT_TRIANGLES = 131072
_MAX_PAIR_TESTS = 131072


def _unverified(reason: str) -> dict[str, Any]:
    """Return explicit unavailable evidence without disguising a failure as coverage."""
    return {
        "scope": "continuous_projected_centerline_only",
        "availability": "unavailable",
        "passed": None,
        "reason": reason,
        "uncovered_intervals": None,
    }


def _array(value: object, minimum: int, maximum: int, label: str) -> list | tuple:
    """Bound explicit input arrays before copying or performing geometric work."""
    if not isinstance(value, (list, tuple)) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} requires {minimum} to {maximum} explicit entries")
    return value


def _coordinates(value: object, width: int, label: str) -> tuple[Fraction, ...]:
    """Interpret finite source coordinates exactly as their binary float values."""
    raw = _array(value, width, width, label)
    result = []
    for coordinate in raw:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise ValueError(f"{label} requires finite numeric coordinates")
        try:
            number = float(coordinate)
        except OverflowError as exc:
            raise ValueError(f"{label} coordinates exceed the existing mesh bounds") from exc
        if not math.isfinite(number) or abs(number) > 1.0e6:
            raise ValueError(f"{label} coordinates exceed the existing mesh bounds")
        result.append(Fraction(number))
    return tuple(result)


def _cross(first: Point, second: Point) -> Fraction:
    """Return an exact two-dimensional determinant, with no distance tolerance."""
    return first[0] * second[1] - first[1] * second[0]


def _subtract(first: Point, second: Point) -> Point:
    """Subtract exact projected coordinate pairs."""
    return first[0] - second[0], first[1] - second[1]


def _degenerate_projection_interval(
    a: Point, b: Point, triangle: tuple[Point, ...]
) -> Interval | None:
    """Include the line or point projection of a valid vertical 3D support triangle."""
    first, last = min(triangle), max(triangle)
    direction, edge = _subtract(b, a), _subtract(last, first)
    offset = _subtract(first, a)
    denominator = _cross(direction, edge)
    if denominator:
        t = _cross(offset, edge) / denominator
        u = _cross(offset, direction) / denominator
        return (t, t) if 0 <= t <= 1 and 0 <= u <= 1 else None
    if _cross(offset, direction):
        return None
    axis = 0 if direction[0] else 1
    t0, t1 = (first[axis] - a[axis]) / direction[axis], (last[axis] - a[axis]) / direction[axis]
    low, high = max(Fraction(0), min(t0, t1)), min(Fraction(1), max(t0, t1))
    return (low, high) if low <= high else None


def _clip_triangle(a: Point, b: Point, triangle: tuple[Point, ...]) -> Interval | None:
    """Clip a full centerline segment against all three closed triangle half-planes."""
    area = _cross(_subtract(triangle[1], triangle[0]), _subtract(triangle[2], triangle[0]))
    if area == 0:
        return _degenerate_projection_interval(a, b, triangle)
    orientation = 1 if area > 0 else -1
    low, high = Fraction(0), Fraction(1)
    direction = _subtract(b, a)
    for i, first in enumerate(triangle):
        edge = _subtract(triangle[(i + 1) % 3], first)
        start = orientation * _cross(edge, _subtract(a, first))
        slope = orientation * _cross(edge, direction)
        if slope == 0:
            if start < 0:
                return None
        elif slope > 0:
            low = max(low, -start / slope)
        else:
            high = min(high, -start / slope)
        if low > high:
            return None
    return low, high


def _union(intervals: list[Interval]) -> list[Interval]:
    """Merge overlapping or exactly touching closed support intervals without gap tolerances."""
    result = []
    for low, high in sorted(intervals):
        if result and low <= result[-1][1]:
            result[-1] = result[-1][0], max(result[-1][1], high)
        else:
            result.append((low, high))
    return result


def _gaps(covered: list[Interval], segment_index: int) -> list[dict[str, Any]]:
    """Report exact open/closed uncovered parameter intervals, including unsupported endpoints."""
    result = []
    cursor = Fraction(0)
    cursor_inclusive = True
    for low, high in covered:
        if cursor < low:
            result.append(
                {
                    "segment_index": segment_index,
                    "t_start": str(cursor),
                    "t_end": str(low),
                    "start_inclusive": cursor_inclusive,
                    "end_inclusive": False,
                }
            )
        cursor = high
        cursor_inclusive = False
    if cursor < 1:
        result.append(
            {
                "segment_index": segment_index,
                "t_start": str(cursor),
                "t_end": "1",
                "start_inclusive": cursor_inclusive,
                "end_inclusive": True,
            }
        )
    return result


def inspect_projected_centerline_coverage(
    points: object,
    *,
    support_vertices: object,
    support_triangles: object,
) -> dict[str, Any]:
    """Inspect every XZ centerline segment against explicit indexed support triangles.

    Input arrays use existing mesh coordinate/index data, without requiring a new
    contract or a closed support mesh. Coordinates are finite, bounded source
    floats; pass actual native coordinates when inspecting a native model. Each
    uncovered interval uses exact rational strings for t in P[i]+t*(P[i+1]-P[i]),
    plus endpoint inclusion flags. No sampling or epsilon can hide a tiny gap.
    Unsupported/malformed data or more than 131,072 segment/triangle tests returns
    unavailable evidence and passed=None. This utility never changes geometry or
    imposes a no-bridge authoring policy.
    """
    try:
        route_raw = _array(points, 2, _MAX_PATH_POINTS, "centerline")
        vertices_raw = _array(support_vertices, 3, _MAX_SUPPORT_VERTICES, "support vertices")
        faces_raw = _array(support_triangles, 1, _MAX_SUPPORT_TRIANGLES, "support triangles")
        pair_count = (len(route_raw) - 1) * len(faces_raw)
        if pair_count > _MAX_PAIR_TESTS:
            return _unverified("segment/triangle workload budget exceeded")
        route = [_coordinates(p, 2, "centerline") for p in route_raw]
        if any(a == b for a, b in zip(route, route[1:], strict=False)):
            raise ValueError("centerline contains a zero-length segment")
        vertices = [_coordinates(p, 3, "support vertices") for p in vertices_raw]
        triangles = []
        for face in faces_raw:
            indices = _array(face, 3, 3, "support triangle")
            if any(type(i) is not int or not 0 <= i < len(vertices) for i in indices):
                raise ValueError("support triangle contains invalid indices")
            if len(set(indices)) != 3:
                raise ValueError("support triangle repeats an index")
            a, b, c = [vertices[i] for i in indices]
            ab, ac = [tuple(p[k] - a[k] for k in range(3)) for p in (b, c)]
            normal = (
                ab[1] * ac[2] - ab[2] * ac[1],
                ab[2] * ac[0] - ab[0] * ac[2],
                ab[0] * ac[1] - ab[1] * ac[0],
            )
            if not any(normal):
                raise ValueError("support triangle is degenerate in 3D")
            triangles.append(tuple((p[0], p[2]) for p in (a, b, c)))
    except ValueError as exc:
        return _unverified(str(exc))
    bounds = [
        tuple((min(p[axis] for p in triangle), max(p[axis] for p in triangle)) for axis in range(2))
        for triangle in triangles
    ]
    uncovered = []
    clips = 0
    for index, (a, b) in enumerate(zip(route, route[1:], strict=False)):
        segment_bounds = [(min(a[axis], b[axis]), max(a[axis], b[axis])) for axis in range(2)]
        intervals = []
        for triangle, triangle_bounds in zip(triangles, bounds, strict=True):
            if any(
                segment_bounds[axis][1] < triangle_bounds[axis][0]
                or triangle_bounds[axis][1] < segment_bounds[axis][0]
                for axis in range(2)
            ):
                continue
            clips += 1
            interval = _clip_triangle(a, b, triangle)
            if interval is not None:
                intervals.append(interval)
        uncovered.extend(_gaps(_union(intervals), index))
    return {
        "scope": "continuous_projected_centerline_only",
        "availability": "available",
        "passed": not uncovered,
        "reason": None,
        "segment_triangle_pairs_considered": pair_count,
        "exact_triangle_clips": clips,
        "uncovered_intervals": uncovered,
    }
