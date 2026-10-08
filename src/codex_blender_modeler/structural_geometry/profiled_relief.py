"""Bounded data-only, closed polygon-profile relief ribbons.

The host emits the existing shell contract. Authored cross-sections remain
piecewise planar: no oval substitution, smoothing, callback, or schema change.
"""

from __future__ import annotations

import heapq
import math
import struct
from collections.abc import Sequence

from ..blender_scripts import self_intersection_runtime as _exact
from .contour_relief import _area, _cross, _ear_clip, _inside, _intersects, _simple
from .contour_relief import _number as _legacy_number
from .triangle_shell import TriangulatedShellGeometry

Point = tuple[float, float]
_MAX_STATIONS = 128
_MAX_PROFILE_POINTS = 16
_MAX_PAIR_TESTS = 32768
_EPS = 1.0e-10
_MAX_MITER = 4.0


def _number(value: object, label: str, *, positive: bool = False) -> float:
    """Normalize finite numeric data, including oversized integers, to ValueError."""
    try:
        return _legacy_number(value, label, positive=positive)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite bounded number") from exc


def _point(value: object, label: str) -> Point:
    """Accept only an explicit pair of finite numbers, never mappings or iterators."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} points require exactly two numeric coordinates")
    return _number(value[0], label), _number(value[1], label)


def _sequence(value: object, minimum: int, maximum: int, label: str) -> Sequence:
    """Reject unbounded iterators, strings and oversized arrays before copying data."""
    if not isinstance(value, (list, tuple)) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} requires {minimum} to {maximum} explicit entries")
    return value


def _dimensions(value: float | Sequence[float], count: int, label: str) -> list[float]:
    """Expand positive scalar or exactly matched station dimensions without clamping."""
    values = (
        [value] * count
        if isinstance(value, (int, float))
        else _sequence(value, count, count, label)
    )
    result = [_number(item, label, positive=True) for item in values]
    if max(result) > 1.0e6:
        raise ValueError(f"{label} exceeds the existing coordinate envelope")
    return result


def _profile(value: Sequence[Point]) -> list[Point]:
    """Require a simple explicit normalized section with non-collinear corners."""
    result = [_point(p, "profile") for p in _sequence(value, 3, _MAX_PROFILE_POINTS, "profile")]
    if any(abs(c) > 0.5 for p in result for c in p) or any(
        min(p[axis] for p in result) != -0.5 or max(p[axis] for p in result) != 0.5
        for axis in range(2)
    ):
        raise ValueError("profile must span exactly [-0.5, 0.5] on both axes")
    _simple(result, "profile")
    if any(
        abs(_cross(result[i - 1], p, result[(i + 1) % len(result)])) <= _EPS
        for i, p in enumerate(result)
    ):
        raise ValueError("profile has a collinear or sub-tolerance corner")
    return result


def _miter_frames(route: Sequence[Point]) -> list[Point]:
    """Construct bounded planar bisectors, refusing near-cusps rather than beveling them."""
    directions = []
    for first, second in zip(route, route[1:], strict=False):
        dx, dz = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dz)
        if length <= _EPS:
            raise ValueError("route contains a zero or sub-tolerance edge")
        directions.append((dx / length, dz / length))
    normals = [(-dz, dx) for dx, dz in directions]
    frames = [normals[0]]
    for first, last in zip(normals, normals[1:], strict=False):
        denominator = 1.0 + first[0] * last[0] + first[1] * last[1]
        if denominator <= 2.0 / _MAX_MITER**2:
            raise ValueError("route near-cusp exceeds the four-times miter limit")
        frames.append(((first[0] + last[0]) / denominator, (first[1] + last[1]) / denominator))
    return [*frames, normals[-1]]


def _footprint(route: Sequence[Point], frames: Sequence[Point], widths: Sequence[float]) -> None:
    """Prove footprint cells are convex, disjoint except at their common station edge."""
    left = [
        (p[0] - n[0] * w / 2, p[1] - n[1] * w / 2)
        for p, n, w in zip(route, frames, widths, strict=True)
    ]
    right = [
        (p[0] + n[0] * w / 2, p[1] + n[1] * w / 2)
        for p, n, w in zip(route, frames, widths, strict=True)
    ]
    _simple([*left, *reversed(right)], "ribbon footprint")
    cells = [(left[i], right[i], right[i + 1], left[i + 1]) for i in range(len(route) - 1)]
    for cell in cells:
        if any(_cross(cell[i - 1], cell[i], cell[(i + 1) % 4]) >= -_EPS for i in range(4)):
            raise ValueError("ribbon footprint cell folds or becomes sub-tolerance")
    for i, first in enumerate(cells):
        for j in range(i + 2, len(cells)):
            second = cells[j]
            if (
                any(
                    _intersects(first[k], first[(k + 1) % 4], second[m], second[(m + 1) % 4])
                    for k in range(4)
                    for m in range(4)
                )
                or _inside(first[0], second)
                or _inside(second[0], first)
            ):
                raise ValueError("nonadjacent ribbon footprint cells intersect or touch")
    # Each convex adjacent cell lies strictly on its own side of its shared edge.
    for i in range(1, len(route) - 1):
        values = [_cross(left[i], right[i], p) for p in (left[i - 1], right[i - 1])]
        following = [_cross(left[i], right[i], p) for p in (left[i + 1], right[i + 1])]
        if min(values) <= _EPS or max(following) >= -_EPS:
            raise ValueError("adjacent ribbon footprint cells overlap or fold")


def _improper_contact(first: _exact.ExactTriangle, second: _exact.ExactTriangle) -> bool:
    """Reject exact triangle contact outside an indexed common edge or vertex.

    The existing exact runtime intentionally permits independent boundary contact.
    A closed ribbon is stricter: non-indexed contact would create a pinched shell.
    Reuse its rational plane/clip predicates, but narrow the permitted contact set.
    """
    shared = sorted(set(first.indices) & set(second.indices))
    allowed = [first.points[first.indices.index(index)] for index in shared]
    direction = _exact._cross(first.normal, second.normal)
    if any(direction):
        one = _exact._plane_interval(first.points, second.points[0], second.normal, direction)
        two = _exact._plane_interval(second.points, first.points[0], first.normal, direction)
        if one is None or two is None:
            return False
        low, high = max(one[0], two[0]), min(one[1], two[1])
        if low > high:
            return False
        if not allowed:
            return True
        projections = [_exact._dot(point, direction) for point in allowed]
        return not min(projections) <= low <= high <= max(projections)
    if _exact._dot(first.normal, _exact._subtract(second.points[0], first.points[0])) != 0:
        return False
    drop = max(range(3), key=lambda axis: abs(first.normal[axis]))
    axes = [axis for axis in range(3) if axis != drop]
    first2 = [tuple(p[a] for a in axes) for p in first.points]
    second2 = [tuple(p[a] for a in axes) for p in second.points]
    polygon = _exact._coplanar_polygon(first2, second2)
    allowed2 = [tuple(p[a] for a in axes) for p in allowed]
    return bool(polygon) and (
        not allowed2 or any(not _exact._within_shared_boundary(p, allowed2) for p in polygon)
    )


def _embedding_candidate_pairs(bounds, *, scan_budget=None, max_scans=None):
    """Enumerate the identical closed-AABB pair set with heap-based X expiry.

    Count actual active-pair scans plus heap insertions/removals when the host
    supplies its shared budget. Expiry never scans the surviving active list.
    Strict '<' expiry retains touching boundary boxes for exact predicates.
    """
    active = {}
    expiry = []
    for index in sorted(range(len(bounds)), key=lambda i: (bounds[i][0][0], i)):
        low, high = bounds[index]
        while expiry and expiry[0][0] < low[0]:
            if scan_budget is not None:
                scan_budget[0] += 1
                if scan_budget[0] > max_scans:
                    raise ValueError("attachment embedding broad-phase scan budget exhausted")
            _, other = heapq.heappop(expiry)
            del active[other]
        for other in active:
            if scan_budget is not None:
                scan_budget[0] += 1
                if scan_budget[0] > max_scans:
                    raise ValueError("attachment embedding broad-phase scan budget exhausted")
            other_low, other_high = bounds[other]
            if any(high[a] < other_low[a] or other_high[a] < low[a] for a in (1, 2)):
                continue
            yield other, index
        if scan_budget is not None:
            scan_budget[0] += 1
            if scan_budget[0] > max_scans:
                raise ValueError("attachment embedding broad-phase scan budget exhausted")
        active[index] = None
        heapq.heappush(expiry, (high[0], index))


def _validate_embedded(
    shell: TriangulatedShellGeometry, *, scan_budget=None, max_scans=None
) -> None:
    """Prove all emitted triangles embedded with unchanged exact contact tests."""
    prepared = _exact.prepare_exact_triangles(shell.vertices, shell.triangles)
    if any(item is None for item in prepared):
        raise ValueError("ribbon exact triangle preparation failed")
    bounds = [
        (
            tuple(min(shell.vertices[i][a] for i in f) for a in range(3)),
            tuple(max(shell.vertices[i][a] for i in f) for a in range(3)),
        )
        for f in shell.triangles
    ]
    pair_tests = 0
    for other, index in _embedding_candidate_pairs(
        bounds, scan_budget=scan_budget, max_scans=max_scans
    ):
        pair_tests += 1
        if pair_tests > _MAX_PAIR_TESTS:
            raise ValueError("ribbon exhausted its exact triangle-pair budget")
        if _improper_contact(prepared[other], prepared[index]):
            raise ValueError("ribbon emitted triangles self-intersect or touch")


def build_profiled_relief_ribbon(
    points: Sequence[Point],
    *,
    profile: Sequence[Point],
    width: float | Sequence[float],
    depth: float | Sequence[float],
    center_y: float | Sequence[float] = 0.0,
) -> TriangulatedShellGeometry:
    """Sweep a closed authored lateral/Y profile along a bounded open XZ route.

    Each station contributes P vertices, in exactly the authored profile order.
    Caps occupy the first 2*(P-2) triangles; side pairs follow station then profile
    edge order. Total triangles = 2*N*P-4. Width and depth can taper at stations,
    but must stay strictly positive. center_y is scalar or one finite Y per station.
    Coordinates and dimensions use meters.
    Exact tests validate emitted diagonals, not merely the ideal ruled surface.
    """
    route = [_point(p, "route") for p in _sequence(points, 2, _MAX_STATIONS, "route")]
    shape = _profile(profile)
    widths = _dimensions(width, len(route), "width")
    depths = _dimensions(depth, len(route), "depth")
    centers = (
        [_number(center_y, "center_y")] * len(route)
        if isinstance(center_y, (int, float))
        else [
            _number(c, "center_y") for c in _sequence(center_y, len(route), len(route), "center_y")
        ]
    )
    if any(abs(c) > 1.0e6 for p in route for c in p) or max(map(abs, centers)) > 1.0e6:
        raise ValueError("route/center exceeds the existing coordinate envelope")
    scale = max(max(p[a] for p in route) - min(p[a] for p in route) for a in range(2))
    scale = max(scale, *widths, *depths, max(centers) - min(centers))
    if min(*widths, *depths) <= scale * _EPS:
        raise ValueError("ribbon width/depth is sub-tolerance relative to its extent")
    origin = route[0]
    normalized = [((p[0] - origin[0]) / scale, (p[1] - origin[1]) / scale) for p in route]
    frames = _miter_frames(normalized)
    _footprint(normalized, frames, [w / scale for w in widths])
    vertices = [
        (p[0] + lateral * w * n[0], center + y * d, p[1] + lateral * w * n[1])
        for p, n, w, d, center in zip(route, frames, widths, depths, centers, strict=True)
        for lateral, y in shape
    ]
    count = len(shape)
    # Profile CCW is -tangent in this frame; the initial cap uses that orientation.
    caps = _ear_clip(shape)
    faces = list(caps)
    last = (len(route) - 1) * count
    faces.extend(tuple(last + index for index in reversed(face)) for face in caps)
    for station in range(len(route) - 1):
        first, second = station * count, (station + 1) * count
        for i in range(count):
            j = (i + 1) % count
            pair = [(first + i, second + i, second + j), (first + i, second + j, first + j)]
            faces.extend(pair if _area(shape) > 0 else [tuple(reversed(f)) for f in pair])
    shell = TriangulatedShellGeometry(vertices=vertices, triangles=faces)
    _validate_embedded(shell)
    # Native mesh positions use float32; prove that roundtrip before returning doubles.
    rounded = [tuple(struct.unpack("f", struct.pack("f", c))[0] for c in p) for p in vertices]
    try:
        native = TriangulatedShellGeometry(vertices=rounded, triangles=faces)
        _validate_embedded(native)
    except ValueError as exc:
        raise ValueError(f"ribbon fails float32 materialization safety: {exc}") from exc
    return shell
