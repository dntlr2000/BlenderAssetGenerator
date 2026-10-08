"""Data-only contour shells with exact silhouettes and error-bounded bevels.

These host helpers emit the existing triangulated-shell contract. They do not
change schemas, materials, UVs, execution authority, or canonical job state.
Broad caps are planar; the error bound describes the authored ruled elliptical
bevel, not an inferred dome or the image reference. Input corners are retained.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .triangle_shell import TriangulatedShellGeometry

Point = tuple[float, float]
Triangle = tuple[int, int, int]
_EPSILON = 1.0e-12
_MAX_CONTOUR_POINTS = 512
_MAX_CAP_POINT_TESTS = 4 * _MAX_CONTOUR_POINTS**2


def _number(value: object, label: str, *, positive: bool = False) -> float:
    """Require finite numeric dimensions without accepting booleans or strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise ValueError(f"{label} must be finite" + (" and positive" if positive else ""))
    return result


def _point(value: object, label: str) -> Point:
    """Require exactly two finite numeric coordinates for both contours and routes."""
    try:
        if len(value) != 2:
            raise ValueError(f"{label} points require exactly two coordinates")
        return (_number(value[0], label), _number(value[1], label))
    except (TypeError, IndexError, KeyError) as exc:
        raise ValueError(f"{label} points require exactly two coordinates") from exc


def _cross(a: Point, b: Point, c: Point) -> float:
    """Return the signed twice-area of one planar triangle."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _area(points: Sequence[Point]) -> float:
    """Measure area relative to an anchor to avoid translation cancellation."""
    return (
        math.fsum(_cross(points[0], points[i], points[i + 1]) for i in range(1, len(points) - 1))
        / 2.0
    )


def _intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    """Detect crossing or touching segments in normalized contour coordinates."""
    values = (_cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b))
    if values[0] * values[1] < 0.0 and values[2] * values[3] < 0.0:
        return True
    for value, p, q, r in (
        (values[0], a, b, c),
        (values[1], a, b, d),
        (values[2], c, d, a),
        (values[3], c, d, b),
    ):
        if abs(value) <= _EPSILON and all(
            min(p[k], q[k]) - _EPSILON <= r[k] <= max(p[k], q[k]) + _EPSILON for k in range(2)
        ):
            return True
    return False


def _simple(points: Sequence[Point], label: str) -> None:
    """Reject degenerate, repeated, touching, or crossing normalized loops."""
    if abs(_area(points)) <= _EPSILON:
        raise ValueError(f"{label} has zero or sub-tolerance area")
    count = len(points)
    for i, a in enumerate(points):
        b = points[(i + 1) % count]
        if math.dist(a, b) <= _EPSILON:
            raise ValueError(f"{label} contains a zero or sub-tolerance edge")
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if _intersects(a, b, points[j], points[(j + 1) % count]):
                raise ValueError(f"{label} is self-intersecting or touching")


def _read_loop(points: Sequence[Point], label: str) -> tuple[list[Point], list[Point], float]:
    """Read a bounded loop and normalize predicates while retaining exact coordinates."""
    if not 3 <= len(points) <= _MAX_CONTOUR_POINTS:
        raise ValueError(f"{label} requires 3 to {_MAX_CONTOUR_POINTS} control points")
    copied = []
    for point in points:
        value = _point(point, label)
        if max(abs(coordinate) for coordinate in value) > 1.0e6:
            raise ValueError(f"{label} coordinates exceed the existing shell bounds")
        copied.append(value)
    scale = max(max(p[k] for p in copied) - min(p[k] for p in copied) for k in range(2))
    if scale <= 0.0:
        raise ValueError(f"{label} has zero extent")
    origin = copied[0]
    normalized = [((p[0] - origin[0]) / scale, (p[1] - origin[1]) / scale) for p in copied]
    _simple(normalized, label)
    return copied, normalized, scale


def _widths(value: float | Sequence[float], count: int, label: str) -> list[float]:
    """Expand explicitly authored widths without silently narrowing any corner."""
    if isinstance(value, (int, float)):
        return [_number(value, label, positive=True)] * count
    if len(value) != count:
        raise ValueError(f"{label} must match the number of contour or route points")
    return [_number(item, label, positive=True) for item in value]


def _offset(points: Sequence[Point], widths: Sequence[float], *, closed: bool) -> list[Point]:
    """Intersect adjacent offset lines using the local authored distance at each vertex."""
    result = []
    direction = 1.0 if not closed or _area(points) > 0 else -1.0
    count = len(points)
    for i, point in enumerate(points):
        previous = points[(i - 1) % count] if closed or i > 0 else point
        following = points[(i + 1) % count] if closed or i < count - 1 else point
        edges = [
            (point[0] - previous[0], point[1] - previous[1]),
            (following[0] - point[0], following[1] - point[1]),
        ]
        normals = [
            (-direction * edge[1] / math.hypot(*edge), direction * edge[0] / math.hypot(*edge))
            for edge in edges
            if math.hypot(*edge) > 0.0
        ]
        if not normals:
            raise ValueError("offset route contains a zero edge")
        first, last = normals[0], normals[-1]
        denominator = 1.0 + first[0] * last[0] + first[1] * last[1]
        if denominator <= _EPSILON:
            raise ValueError("offset reverses direction at a narrow tip")
        result.append(
            (
                point[0] + widths[i] * (first[0] + last[0]) / denominator,
                point[1] + widths[i] * (first[1] + last[1]) / denominator,
            )
        )
    return result


def _inside(point: Point, loop: Sequence[Point]) -> bool:
    """Test strict planar containment after boundary intersection checks."""
    inside = False
    for i, a in enumerate(loop):
        b = loop[(i + 1) % len(loop)]
        if (a[1] > point[1]) != (b[1] > point[1]):
            hit = a[0] + (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1])
            if point[0] < hit:
                inside = not inside
    return inside


def _validate_band(outer: Sequence[Point], inner: Sequence[Point]) -> None:
    """Require an embedded nested annulus with non-inverting corner correspondence."""
    _simple(inner, "inset contour")
    sign = 1.0 if _area(outer) > 0 else -1.0
    if _area(inner) * sign <= _EPSILON:
        raise ValueError("inset contour winding is inverted")
    count = len(outer)
    for i in range(count):
        j = (i + 1) % count
        if not _inside(inner[i], outer):
            raise ValueError("inset contour must lie strictly inside the boundary")
        quad = (outer[i], outer[j], inner[j], inner[i])
        if any(
            sign * _cross(quad[k - 1], quad[k], quad[(k + 1) % 4]) <= _EPSILON for k in range(4)
        ):
            raise ValueError("inset correspondence collapses or inverts a bevel band")
        for k in range(count):
            following = (k + 1) % count
            if _intersects(inner[i], inner[j], outer[k], outer[following]):
                raise ValueError("inset contour intersects the boundary")
            if k != i and _intersects(outer[i], inner[i], outer[k], inner[k]):
                raise ValueError("inset correspondence crosses a bevel band")
            if k not in {i, (i - 1) % count}:
                if _intersects(outer[i], inner[i], outer[k], outer[following]) or _intersects(
                    outer[i], inner[i], inner[k], inner[following]
                ):
                    raise ValueError("inset correspondence leaves its bevel band")


def _ear_clip(points: Sequence[Point]) -> list[Triangle]:
    """Triangulate concave caps with a finite predicate budget and retained anchors."""
    remaining = list(range(len(points)))
    if _area(points) < 0:
        remaining.reverse()
    triangles = []
    point_tests = 0
    while len(remaining) > 3:
        for position, middle in enumerate(remaining):
            first, last = remaining[position - 1], remaining[(position + 1) % len(remaining)]
            a, b, c = points[first], points[middle], points[last]
            if _cross(a, b, c) <= _EPSILON:
                continue
            blocked = False
            for index in remaining:
                if index in {first, middle, last}:
                    continue
                point_tests += 1
                if point_tests > _MAX_CAP_POINT_TESTS:
                    raise ValueError("cap triangulation exhausted its finite predicate budget")
                if all(
                    value >= -_EPSILON
                    for value in (
                        _cross(a, b, points[index]),
                        _cross(b, c, points[index]),
                        _cross(c, a, points[index]),
                    )
                ):
                    blocked = True
                    break
            if blocked:
                continue
            triangles.append((first, middle, last))
            remaining.pop(position)
            break
        else:
            raise ValueError("cap cannot be triangulated without sub-tolerance triangles")
    if _cross(*(points[index] for index in remaining)) <= _EPSILON:
        raise ValueError("cap ends in a sub-tolerance triangle")
    triangles.append(tuple(remaining))
    return triangles


def _assemble(
    vertices: list[tuple[float, float, float]],
    rings: list[list[int]],
    cap: Sequence[Point],
    winding: float,
) -> TriangulatedShellGeometry:
    """Close oriented ring bands with deterministic cap-first triangle ordering."""
    triangles = _ear_clip(cap)
    faces = [tuple(rings[0][index] for index in face) for face in triangles]
    faces.extend(tuple(rings[-1][index] for index in reversed(face)) for face in triangles)
    for left, right in zip(rings, rings[1:], strict=False):
        for i in range(len(cap)):
            j = (i + 1) % len(cap)
            pair = [(left[i], right[i], right[j]), (left[i], right[j], left[j])]
            faces.extend(pair if winding > 0 else [tuple(reversed(face)) for face in pair])
    return TriangulatedShellGeometry(vertices=vertices, triangles=faces)


def _band_twist_bound(outer: Sequence[Point], inset: Sequence[Point]) -> float:
    """Bound geometric ruled-strip twist while excluding coplanar tangent shortening.

    At any fixed Y the exact strip is a segment; triangulation introduces one
    diagonal kink. With nonnegative endpoint-edge dot product its projection
    remains inside that segment and deviation is at most cross(e, f)/(4*q),
    where q is the shortest interpolated edge. Multiplying by the inset-fraction
    step gives a bound for each ring pair. Other turns keep the conservative
    parameter-space bound. This also covers round-off in parallel inset edges.
    """
    bound = 0.0
    for i in range(len(outer)):
        j = (i + 1) % len(outer)
        edge = (outer[j][0] - outer[i][0], outer[j][1] - outer[i][1])
        inner = (inset[j][0] - inset[i][0], inset[j][1] - inset[i][1])
        change = (inner[0] - edge[0], inner[1] - edge[1])
        length = math.hypot(*change)
        if length > 0.0 and edge[0] * inner[0] + edge[1] * inner[1] >= 0.0:
            t = max(0.0, min(1.0, -(edge[0] * change[0] + edge[1] * change[1]) / length**2))
            minimum = math.hypot(edge[0] + t * change[0], edge[1] + t * change[1])
            if minimum > 0.0:
                length = min(length, abs(edge[0] * inner[1] - edge[1] * inner[0]) / minimum)
        bound = max(bound, length)
    return bound


def build_contour_prism(
    points: Sequence[Point], *, depth: float, center_y: float = 0.0
) -> TriangulatedShellGeometry:
    """Build an exact concave prism retaining every input boundary and attachment anchor."""
    outer, normalized, _ = _read_loop(points, "contour")
    half_depth = _number(depth, "depth", positive=True) / 2.0
    center = _number(center_y, "center_y")
    vertices = [(x, center + y, z) for y in (-half_depth, half_depth) for x, z in outer]
    count = len(outer)
    return _assemble(
        vertices, [list(range(count)), list(range(count, 2 * count))], normalized, _area(normalized)
    )


def build_contour_relief_shell(
    points: Sequence[Point],
    *,
    depth: float,
    bevel_width: float | Sequence[float],
    bevel_depth: float,
    max_chord_error: float,
    center_y: float = 0.0,
    inset_points: Sequence[Point] | None = None,
) -> TriangulatedShellGeometry:
    """Build planar caps and elliptical bevels within a metric ruled-surface error.

    Exact original boundary vertices occupy the first N front and next N rear
    indices, independent of error setting. Caps occupy the first N-2 front and
    next N-2 rear triangles. Remaining triangles connect consecutive bevel and
    side rings. UV seams, material assignment and smoothing remain caller intent.

    Bevel widths are explicit; unsafe offsets are rejected rather than clamped.
    Matched inset_points override offset construction. The error bound combines
    ellipse chord error and a conservative ruled-quad triangulation term.
    At most 512 authored contour controls are accepted before quadratic band
    checks; ear clipping additionally has a finite predicate budget. Exhaustion
    rejects the request and never silently resamples or drops a control point.
    """
    outer, normalized, scale = _read_loop(points, "contour")
    half_depth = _number(depth, "depth", positive=True) / 2.0
    bevel = _number(bevel_depth, "bevel_depth", positive=True)
    error = _number(max_chord_error, "max_chord_error", positive=True)
    center = _number(center_y, "center_y")
    if bevel >= half_depth:
        raise ValueError("bevel_depth must be less than half the shell depth")
    widths = _widths(bevel_width, len(outer), "bevel_width")
    inset = (
        _offset(outer, widths, closed=True)
        if inset_points is None
        else _read_loop(inset_points, "inset contour")[0]
    )
    if len(inset) != len(outer):
        raise ValueError("inset_points must match every original contour vertex")
    inner = [((p[0] - outer[0][0]) / scale, (p[1] - outer[0][1]) / scale) for p in inset]
    _validate_band(normalized, inner)
    deltas = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(outer, inset, strict=True)]
    radius = max(bevel, max(math.hypot(*delta) for delta in deltas))
    twist = _band_twist_bound(outer, inset)
    count = len(outer)
    # Existing shell cardinalities bound refinement before any large allocation.
    max_segments = min(65536 // (2 * count) - 1, (131072 + 4) // (4 * count) - 1)
    segments = 1
    while segments <= max_segments:
        angle = math.pi / (2.0 * segments)
        bound = radius * (1.0 - math.cos(angle / 2.0)) + twist * math.sin(angle) / 4.0
        if bound <= error:
            break
        segments += 1
    else:
        raise ValueError("requested chord error exceeds the existing shell cardinality limits")
    vertices = [
        (x, center + y, z) for y in (-half_depth + bevel, half_depth - bevel) for x, z in outer
    ]
    front = [list(range(count))]
    rear = [list(range(count, 2 * count))]
    for side, rings in ((-1.0, front), (1.0, rear)):
        for step in range(1, segments + 1):
            angle = step * math.pi / (2.0 * segments)
            fraction = 1.0 - math.cos(angle) if step < segments else 1.0
            y = center + side * (half_depth - bevel + bevel * math.sin(angle))
            rings.append(list(range(len(vertices), len(vertices) + count)))
            vertices.extend(
                (a[0] + fraction * d[0], y, a[1] + fraction * d[1])
                for a, d in zip(outer, deltas, strict=True)
            )
    return _assemble(vertices, [*reversed(front), *rear], inner, _area(normalized))


def build_relief_ribbon(
    points: Sequence[Point],
    *,
    width: float | Sequence[float],
    depth: float,
    bevel_width: float,
    bevel_depth: float,
    max_chord_error: float,
    center_y: float = 0.0,
) -> TriangulatedShellGeometry:
    """Build a butt-ended variable-width structural rail without a dense interior grid."""
    if not 2 <= len(points) <= _MAX_CONTOUR_POINTS // 2:
        raise ValueError("ribbon requires 2 to 256 route control points")
    route = [_point(p, "route") for p in points]
    widths = _widths(width, len(route), "width")
    if any(math.dist(a, b) <= _EPSILON for a, b in zip(route, route[1:], strict=False)):
        raise ValueError("ribbon route contains a zero or sub-tolerance edge")
    left = _offset(route, [value / 2.0 for value in widths], closed=False)
    right = _offset(route, [-value / 2.0 for value in widths], closed=False)
    return build_contour_relief_shell(
        [*left, *reversed(right)],
        depth=depth,
        bevel_width=bevel_width,
        bevel_depth=bevel_depth,
        max_chord_error=max_chord_error,
        center_y=center_y,
    )
