"""Bounded, dependency-free exact UV checks for explicit authored-atlas reuse.

No adjacency or shared-edge exemption is used. A complete sweep supplies all
strictly intersecting AABB pairs; convex separating axes then distinguish positive
area from harmless boundary contact. Ambiguous float determinants use exact
integer-ratio arithmetic. Successful reports always describe a completed scan.
"""

from __future__ import annotations

import hashlib
import heapq
import math
import struct
from collections.abc import Sequence
from fractions import Fraction
from typing import Any

MAXIMUM_TRIANGLES = 250_000
MAXIMUM_CANDIDATE_PAIRS = 4_000_000
MAXIMUM_BROADPHASE_PAIRS = 20_000_000
_ORIENTATION_ERROR_BOUND = 3.3306690738754716e-16

Point = tuple[float, float]
Triangle = tuple[int, int, int]


class UVProofError(ValueError):
    """Reject an invalid, ambiguous, overlapping or incomplete UV proof."""


def _number(value: Any, label: str) -> float:
    """Require an ordinary finite coordinate rather than coercing arbitrary input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UVProofError(f"{label} must contain finite numeric coordinates")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise UVProofError(f"{label} is not a finite coordinate") from exc
    if not math.isfinite(result):
        raise UVProofError(f"{label} is not a finite coordinate")
    return result


def _points(loop_uvs: Sequence[Sequence[float]]) -> list[Point]:
    """Validate every ordered loop without rounding or changing its value bits."""
    if not isinstance(loop_uvs, Sequence) or not loop_uvs:
        raise UVProofError("loop_uvs must be a nonempty ordered sequence")
    if len(loop_uvs) > MAXIMUM_TRIANGLES * 3:
        raise UVProofError("UV proof loop resource limit exceeded")
    result = []
    for pair in loop_uvs:
        if not isinstance(pair, Sequence) or len(pair) != 2:
            raise UVProofError("Each UV loop must have exactly two coordinates")
        result.append((_number(pair[0], "loop_uvs"), _number(pair[1], "loop_uvs")))
    return result


def _triangles(
    triangle_loop_indices: Sequence[Sequence[int]], loop_count: int, limit: int
) -> list[Triangle]:
    """Require a complete indexed triangulation that examines every supplied loop."""
    if not isinstance(triangle_loop_indices, Sequence) or not triangle_loop_indices:
        raise UVProofError("triangle_loop_indices must be a nonempty ordered sequence")
    if len(triangle_loop_indices) > limit:
        raise UVProofError("UV proof triangle resource limit exceeded")
    used = set()
    result = []
    for triangle in triangle_loop_indices:
        if not isinstance(triangle, Sequence) or len(triangle) != 3:
            raise UVProofError("Each triangle must contain exactly three loop indices")
        if any(type(index) is not int or not 0 <= index < loop_count for index in triangle):
            raise UVProofError("Triangle loop index is invalid or outside the layout")
        if len(set(triangle)) != 3:
            raise UVProofError("Triangle contains repeated loop indices")
        used.update(triangle)
        result.append(tuple(triangle))
    if len(used) != loop_count:
        raise UVProofError("Incomplete UV proof: not every loop is referenced")
    return result


def _orientation(a: Point, b: Point, c: Point) -> int:
    """Return exact orientation, using a conservative floating-point filter first."""
    if a == b or a == c or b == c:
        return 0
    left = (a[0] - c[0]) * (b[1] - c[1])
    right = (a[1] - c[1]) * (b[0] - c[0])
    determinant = left - right
    error = _ORIENTATION_ERROR_BOUND * (abs(left) + abs(right))
    # The filter is valid for normal arithmetic; subnormal products or differences
    # go to the exact path as well as cancellation, overflow and nonfinite results.
    normal_floor = float.fromhex("0x1.0p-1022")
    if (
        math.isfinite(determinant)
        and math.isfinite(error)
        and abs(determinant) > error
        and abs(determinant) >= normal_floor
        and (left == 0.0 or abs(left) >= normal_floor)
        and (right == 0.0 or abs(right) >= normal_floor)
    ):
        return 1 if determinant > 0.0 else -1
    ax, ay = map(Fraction, a)
    bx, by = map(Fraction, b)
    cx, cy = map(Fraction, c)
    exact = (ax - cx) * (by - cy) - (ay - cy) * (bx - cx)
    return (exact > 0) - (exact < 0)


def _positive_overlap(first: Sequence[Point], second: Sequence[Point]) -> bool:
    """Test strict interior intersection of nondegenerate convex triangles exactly."""
    for owner, other in ((first, second), (second, first)):
        sign = _orientation(owner[0], owner[1], owner[2])
        if sign == 0:
            raise UVProofError("Exact zero-area UV triangle")
        for index in range(3):
            a, b = owner[index], owner[(index + 1) % 3]
            if all(_orientation(a, b, point) * sign <= 0 for point in other):
                return False
    return True


def triangles_positive_area_overlap(
    first: Sequence[Sequence[float]], second: Sequence[Sequence[float]]
) -> bool:
    """Expose the exact pair predicate for independent finite-triangle replay tests."""
    a, b = _points(first), _points(second)
    if len(a) != 3 or len(b) != 3:
        raise UVProofError("The overlap predicate requires two triangles")
    if _orientation(*a) == 0 or _orientation(*b) == 0:
        raise UVProofError("Exact zero-area UV triangle")
    return _positive_overlap(a, b)


def _bounds(points: Sequence[Point]) -> tuple[float, float, float, float]:
    """Measure actual complete UV extents without assuming a normalized source cell."""
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _fingerprints(points: Sequence[Point], triangles: Sequence[Triangle]) -> dict[str, str]:
    """Bind exact ordered binary64 UV values and ordered integer loop triangles."""
    uv = hashlib.sha256(b"cbm-authored-uv-values-v1\0")
    uv.update(struct.pack(">Q", len(points)))
    for point in points:
        uv.update(struct.pack(">dd", *point))
    topology = hashlib.sha256(b"cbm-authored-uv-triangles-v1\0")
    topology.update(struct.pack(">QQ", len(points), len(triangles)))
    for triangle in triangles:
        topology.update(struct.pack(">QQQ", *triangle))
    layout = hashlib.sha256(b"cbm-authored-uv-layout-v1\0" + uv.digest() + topology.digest())
    return {
        "uv_fingerprint_sha256": uv.hexdigest(),
        "topology_fingerprint_sha256": topology.hexdigest(),
        "layout_fingerprint_sha256": layout.hexdigest(),
    }


def _limit(value: int, maximum: int, label: str) -> int:
    """Allow stricter diagnostic caps without permitting callers to remove host limits."""
    if type(value) is not int or not 0 <= value <= maximum:
        raise UVProofError(f"{label} must be an integer in [0, {maximum}]")
    return value


def _sweep_cost(boxes: Sequence[tuple[float, float, float, float]], axis: int) -> int:
    """Count all active-axis comparisons to select and bound a complete sweep."""
    active = []
    total = 0
    for index in sorted(range(len(boxes)), key=lambda i: (boxes[i][axis], i)):
        low = boxes[index][axis]
        while active and active[0] <= low:
            heapq.heappop(active)
        total += len(active)
        heapq.heappush(active, boxes[index][axis + 2])
    return total


def validate_uv_layout(
    loop_uvs: Sequence[Sequence[float]],
    triangle_loop_indices: Sequence[Sequence[int]],
    *,
    maximum_triangles: int = MAXIMUM_TRIANGLES,
    maximum_candidate_pairs: int = MAXIMUM_CANDIDATE_PAIRS,
    maximum_broadphase_pairs: int = MAXIMUM_BROADPHASE_PAIRS,
) -> dict[str, Any]:
    """Prove finite, exactly nondegenerate and zero-positive-overlap ordered UVs."""
    triangle_limit = _limit(maximum_triangles, MAXIMUM_TRIANGLES, "maximum_triangles")
    candidate_limit = _limit(
        maximum_candidate_pairs, MAXIMUM_CANDIDATE_PAIRS, "maximum_candidate_pairs"
    )
    broadphase_limit = _limit(
        maximum_broadphase_pairs, MAXIMUM_BROADPHASE_PAIRS, "maximum_broadphase_pairs"
    )
    points = _points(loop_uvs)
    triangles = _triangles(triangle_loop_indices, len(points), triangle_limit)
    values = [tuple(points[index] for index in triangle) for triangle in triangles]
    for index, triangle in enumerate(values):
        if _orientation(*triangle) == 0:
            raise UVProofError(f"Exact zero-area UV triangle {index}")
    boxes = [_bounds(triangle) for triangle in values]
    costs = [_sweep_cost(boxes, axis) for axis in (0, 1)]
    axis = 0 if costs[0] <= costs[1] else 1
    if costs[axis] > broadphase_limit:
        raise UVProofError("Incomplete UV proof: broad-phase resource limit exceeded")
    other = 1 - axis
    active: dict[int, tuple[float, float, float, float]] = {}
    endings: list[tuple[float, int]] = []
    candidates = 0
    comparisons = 0
    for index in sorted(range(len(boxes)), key=lambda i: (boxes[i][axis], i)):
        box = boxes[index]
        while endings and endings[0][0] <= box[axis]:
            _, expired = heapq.heappop(endings)
            del active[expired]
        for previous, prior in active.items():
            comparisons += 1
            if prior[other + 2] <= box[other] or box[other + 2] <= prior[other]:
                continue
            candidates += 1
            if candidates > candidate_limit:
                raise UVProofError("Incomplete UV proof: candidate-pair resource limit exceeded")
            if _positive_overlap(values[previous], values[index]):
                raise UVProofError(
                    f"Positive-area UV overlap between triangles {previous} and {index}"
                )
        active[index] = box
        heapq.heappush(endings, (box[axis + 2], index))
    if comparisons != costs[axis]:
        raise UVProofError("Incomplete UV proof: broad-phase accounting mismatch")
    low_u, low_v, high_u, high_v = _bounds(points)
    return {
        "loop_count": len(points),
        "triangle_count": len(triangles),
        "uv_minimum": [low_u, low_v],
        "uv_maximum": [high_u, high_v],
        **_fingerprints(points, triangles),
        "degenerate_triangle_count": 0,
        "overlap_pair_count": 0,
        "candidate_pair_count": candidates,
        "broadphase_pair_count": comparisons,
        "sweep_axis": axis,
        "complete": True,
    }


def _float32(value: float) -> float:
    """Round exactly once to the stored IEEE binary32 UV representation."""
    try:
        result = struct.unpack(">f", struct.pack(">f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise UVProofError("UV affine result exceeds finite float32 storage") from exc
    if not math.isfinite(result):
        raise UVProofError("UV affine result is not finite float32")
    return result


def _mapping_bounds(target_bounds: Sequence[float]) -> tuple[float, float, float, float]:
    """Move only interval endpoints inward to representable normalized float32 bounds."""
    if not isinstance(target_bounds, Sequence) or len(target_bounds) != 4:
        raise UVProofError(
            "target_bounds must contain [minimum_u, minimum_v, maximum_u, maximum_v]"
        )
    bounds = tuple(_number(value, "target_bounds") for value in target_bounds)
    if not all(0.0 <= value <= 1.0 for value in bounds):
        raise UVProofError("Target tile bounds must remain inside [0, 1]")
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise UVProofError("Target tile must have positive extents")
    stored = []
    for index, value in enumerate(bounds):
        rounded = _float32(value)
        bits = struct.unpack(">I", struct.pack(">f", rounded))[0]
        if index < 2 and rounded < value:
            rounded = struct.unpack(">f", struct.pack(">I", bits + 1))[0]
        elif index >= 2 and rounded > value:
            rounded = struct.unpack(">f", struct.pack(">I", bits - 1))[0]
        stored.append(rounded)
    if stored[0] >= stored[2] or stored[1] >= stored[3]:
        raise UVProofError("Target tile collapses in float32 storage")
    return tuple(stored)


def mapped_uvs(
    loop_uvs: Sequence[Sequence[float]], target_bounds: Sequence[float]
) -> list[list[float]]:
    """Map full source bounds affinely into inward float32 tile bounds without clamping."""
    points = _points(loop_uvs)
    source = _bounds(points)
    target = _mapping_bounds(target_bounds)
    widths = [source[axis + 2] - source[axis] for axis in (0, 1)]
    if any(not math.isfinite(width) or width <= 0.0 for width in widths):
        raise UVProofError("Source UV bounds must have finite positive extents")
    result = []
    for point in points:
        pair = [
            _float32(
                target[axis]
                + ((point[axis] - source[axis]) / widths[axis]) * (target[axis + 2] - target[axis])
            )
            for axis in (0, 1)
        ]
        if any(not target[axis] <= pair[axis] <= target[axis + 2] for axis in (0, 1)):
            raise UVProofError("Stored affine UV escaped its target interval")
        result.append(pair)
    return result


def prove_authored_uv(
    loop_uvs: Sequence[Sequence[float]],
    triangle_loop_indices: Sequence[Sequence[int]],
    target_bounds: Sequence[float],
    actual_target_uvs: Sequence[Sequence[float]] | None = None,
    *,
    maximum_triangles: int = MAXIMUM_TRIANGLES,
    maximum_candidate_pairs: int = MAXIMUM_CANDIDATE_PAIRS,
    maximum_broadphase_pairs: int = MAXIMUM_BROADPHASE_PAIRS,
) -> dict[str, Any]:
    """Reconstruct and independently prove source and actual stored target UV layouts."""
    limits = {
        "maximum_triangles": maximum_triangles,
        "maximum_candidate_pairs": maximum_candidate_pairs,
        "maximum_broadphase_pairs": maximum_broadphase_pairs,
    }
    source = validate_uv_layout(loop_uvs, triangle_loop_indices, **limits)
    expected = mapped_uvs(loop_uvs, target_bounds)
    actual = expected if actual_target_uvs is None else _points(actual_target_uvs)
    if len(actual) != len(expected) or any(
        struct.pack(">dd", *got) != struct.pack(">dd", *want)
        for got, want in zip(actual, expected, strict=True)
    ):
        raise UVProofError("Stored target UVs differ from exact float32 affine reconstruction")
    target = validate_uv_layout(actual, triangle_loop_indices, **limits)
    points = _points(loop_uvs)
    for index, triangle in enumerate(triangle_loop_indices):
        before = _orientation(*(points[corner] for corner in triangle))
        after = _orientation(*(actual[corner] for corner in triangle))
        if before != after:
            raise UVProofError(f"Stored affine mapping inverted UV triangle {index}")
    return {
        "schema_version": "0.1.0",
        "method": "validated_authored_uv_v1",
        "source": source,
        "target": target,
        "target_bounds": list(target_bounds),
        "mapping_target_bounds": list(_mapping_bounds(target_bounds)),
        "target_uvs": expected,
        "orientation_preserved": True,
        "actual_target_matches_reconstruction": actual_target_uvs is not None,
    }
