"""Bounded host-only approximation of explicit planar cubic Bézier chains.

The continuous source curve lies in the convex hull of its four controls.
Distance to a closed chord segment is convex, so the largest control-to-segment
distance bounds every curve point. Exact rational de Casteljau subdivision and
squared-distance comparisons certify the *actual* emitted binary64 and binary32
chords, including their endpoint rounding. No probe or floating epsilon is proof.

The contract is directed source-curve-to-corresponding-chord distance, plus
endpoint rounding distance. It is not a parameterwise, arc-length, reference
fidelity, topology, nonintersection, support, width, 3D or mesh-validity claim.
Sampling never smooths across authored span boundaries. Constant authored spans
are rejected; closed nonconstant spans may subdivide. Every emitted chord must
be nonzero in both representations. An unproved result is never returned.

This pure-data helper adds no SceneSpec, runtime, approval or workflow surface.
Callers must use the returned coordinates unchanged, or revalidate any transform.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

Point2 = tuple[float, float]
_ExactPoint = tuple[Fraction, Fraction]
_Controls = tuple[_ExactPoint, _ExactPoint, _ExactPoint, _ExactPoint]
_MAX_COORDINATE = 1.0e6
_MAX_SPANS = 128
_MAX_POINTS = 4096
_MAX_WORK = 16384
_MAX_DEPTH = 24


class CurveSamplingError(ValueError):
    """Refuse an invalid or unproved chain without exposing a partial path."""

    def __init__(
        self, reason: str, message: str, *, span_id: str | None = None
    ) -> None:
        """Retain a stable refusal reason and the responsible authored span."""
        super().__init__(message)
        self.reason = reason
        self.span_id = span_id


@dataclass(frozen=True)
class CubicBezierSpan:
    """Four explicit 2D controls, with a unique caller-owned provenance ID."""

    span_id: str
    control_points: tuple[Point2, Point2, Point2, Point2]


@dataclass(frozen=True)
class SamplingLimits:
    """Explicit local budgets; point counts include each span's two endpoints.

    Limits must be integers, not bools: depth 0..24, per-span and total points
    2..4096, and total visited subcurves 1..16384. One visited subcurve means
    at most eight exact control-to-chord distance tests and one subdivision.
    There are at most 128 authored spans. No caller can increase hard caps.
    """

    max_depth: int
    max_points_per_span: int
    max_total_points: int
    max_work: int


@dataclass(frozen=True)
class SegmentCertificate:
    """Bind one chord to its original cubic and exact dyadic local interval.

    Parameter endpoints are exactly representable binary64 numbers in [0,1].
    Squared bounds are reduced (numerator, denominator) integer ratios; each is
    an exact conservative upper bound in input coordinate units squared.
    """

    span_index: int
    span_id: str
    parameter_start: float
    parameter_end: float
    point_start_index: int
    point_end_index: int
    depth: int
    source_bound_squared: tuple[int, int]
    float32_bound_squared: tuple[int, int]


@dataclass(frozen=True)
class SampledBezierChain:
    """Immutable authored controls, two bound paths, certificates and work count.

    Original authored endpoints are retained bit-for-bit in ``points``;
    ``float32_points`` contains the actual struct-packed binary32 coordinates
    promoted to Python floats. Shared endpoints occur once; intentional corners
    remain explicit. No simplification or cross-span tangent fitting occurs.
    """

    spans: tuple[CubicBezierSpan, ...]
    points: tuple[Point2, ...]
    float32_points: tuple[Point2, ...]
    segments: tuple[SegmentCertificate, ...]
    tolerance: float
    limits: SamplingLimits
    work_count: int


def _number(value: object, label: str, *, positive: bool = False) -> float:
    """Require bounded built-in real scalars; refuse bools and lossy huge ints."""
    if type(value) not in (int, float):
        raise CurveSamplingError(
            "invalid_input", f"{label} must be an int or float, not bool"
        )
    if not -_MAX_COORDINATE <= value <= _MAX_COORDINATE:
        raise CurveSamplingError(
            "invalid_input", f"{label} must be finite and within +/-1e6"
        )
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise CurveSamplingError(
            "invalid_input", f"{label} must be finite and positive"
        )
    return result


def _bounded_sequence(value: object, low: int, high: int, label: str) -> Sequence:
    """Require exact built-in containers before invoking any container method."""
    if type(value) not in (list, tuple):
        raise CurveSamplingError(
            "invalid_input", f"{label} must be a built-in list or tuple"
        )
    if not low <= len(value) <= high:
        raise CurveSamplingError(
            "invalid_input", f"{label} requires {low}..{high} items"
        )
    return value


def _validate_limits(limits: SamplingLimits) -> None:
    """Enforce all independent caller budgets beneath fixed host hard caps."""
    if type(limits) is not SamplingLimits:
        raise CurveSamplingError("invalid_input", "limits must be SamplingLimits")
    for name, low, high in (
        ("max_depth", 0, _MAX_DEPTH),
        ("max_points_per_span", 2, _MAX_POINTS),
        ("max_total_points", 2, _MAX_POINTS),
        ("max_work", 1, _MAX_WORK),
    ):
        value = getattr(limits, name)
        if type(value) is not int or not low <= value <= high:
            raise CurveSamplingError(
                "invalid_input", f"{name} must be an integer in {low}..{high}"
            )


def _read_spans(spans: Sequence[CubicBezierSpan]) -> tuple[CubicBezierSpan, ...]:
    """Snapshot controls and reject duplicate IDs, constants and disconnected joins."""
    copied = []
    ids = set()
    for span in _bounded_sequence(spans, 1, _MAX_SPANS, "spans"):
        if type(span) is not CubicBezierSpan:
            raise CurveSamplingError(
                "invalid_input", "each span must be CubicBezierSpan"
            )
        label = span.span_id
        if type(label) is not str or not 1 <= len(label) <= 128 or not label.strip():
            raise CurveSamplingError(
                "invalid_input", "span_id must contain 1..128 characters"
            )
        if label in ids:
            raise CurveSamplingError(
                "invalid_input", "span_id values must be unique", span_id=label
            )
        ids.add(label)
        controls = []
        for item in _bounded_sequence(span.control_points, 4, 4, "control_points"):
            pair = _bounded_sequence(item, 2, 2, "control point")
            controls.append((_number(pair[0], "x"), _number(pair[1], "y")))
        if all(point == controls[0] for point in controls):
            raise CurveSamplingError(
                "constant_span", "constant spans cannot emit a path", span_id=label
            )
        if copied and struct.pack("!2d", *copied[-1].control_points[-1]) != struct.pack(
            "!2d", *controls[0]
        ):
            raise CurveSamplingError(
                "disconnected_chain",
                "adjacent endpoints must match exactly, including signed zero",
                span_id=label,
            )
        copied.append(CubicBezierSpan(label, tuple(controls)))
    return tuple(copied)


def _exact(point: Point2) -> _ExactPoint:
    """Interpret emitted or authored finite binary floats as exact rationals."""
    return (Fraction(point[0]), Fraction(point[1]))


def _float32(point: Point2) -> Point2:
    """Return exactly the coordinates produced by binary32 serialization."""
    return struct.unpack("!2f", struct.pack("!2f", *point))


def _distance_squared(
    point: _ExactPoint, start: _ExactPoint, end: _ExactPoint
) -> Fraction:
    """Compute exact squared distance to the closed segment, not its infinite line."""
    delta = (end[0] - start[0], end[1] - start[1])
    offset = (point[0] - start[0], point[1] - start[1])
    length_squared = delta[0] ** 2 + delta[1] ** 2
    projection = offset[0] * delta[0] + offset[1] * delta[1]
    if length_squared == 0 or projection <= 0:
        return offset[0] ** 2 + offset[1] ** 2
    if projection >= length_squared:
        return (point[0] - end[0]) ** 2 + (point[1] - end[1]) ** 2
    return (offset[0] * delta[1] - offset[1] * delta[0]) ** 2 / length_squared


def _hull_bound(controls: _Controls, start: Point2, end: Point2) -> Fraction:
    """Bound the whole cubic by all four exact control distances to the emitted chord."""
    a, b = _exact(start), _exact(end)
    return max(_distance_squared(point, a, b) for point in controls)


def _midpoint(first: _ExactPoint, second: _ExactPoint) -> _ExactPoint:
    """Average exact coordinates without rounding away the source curve."""
    return ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)


def _split(controls: _Controls) -> tuple[_Controls, _Controls]:
    """Subdivide one cubic at exactly one half using rational de Casteljau."""
    a, b, c, d = controls
    ab, bc, cd = _midpoint(a, b), _midpoint(b, c), _midpoint(c, d)
    abc, bcd = _midpoint(ab, bc), _midpoint(bc, cd)
    middle = _midpoint(abc, bcd)
    return ((a, ab, abc, middle), (middle, bcd, cd, d))


def _emit_endpoint(
    exact: _ExactPoint, source: Point2, tolerance_squared: Fraction, span_id: str
) -> tuple[Point2, Point2]:
    """Bind endpoint rounding separately and reject unusable precision or nonfinite output."""
    serialized = _float32(source)
    if not all(
        math.isfinite(value) for point in (source, serialized) for value in point
    ):
        raise CurveSamplingError(
            "nonfinite_output", "emission produced a nonfinite point", span_id=span_id
        )
    for point in (source, serialized):
        rounded = _exact(point)
        error = sum((exact[k] - rounded[k]) ** 2 for k in range(2))
        if error > tolerance_squared:
            raise CurveSamplingError(
                "precision_unattainable",
                "endpoint rounding exceeds the requested tolerance",
                span_id=span_id,
            )
    return source, serialized


def sample_cubic_bezier_chain(
    spans: Sequence[CubicBezierSpan], *, tolerance: float, limits: SamplingLimits
) -> SampledBezierChain:
    """Return a fully certified path or refuse, with no partial result or fallback.

    Controls and tolerance use the same authored coordinate units; coordinates
    have magnitude <=1e6 and tolerance is finite in (0,1e6]. Built-in ints/floats
    are accepted, bools are not. Containers must be built-in lists or tuples;
    input dataclasses and string IDs must be their exact declared types, without
    subclasses or custom iteration. Span joins match binary64 bits, including zero
    signs. Repeated first/last endpoints represent a closed chain explicitly.

    Parameters are local to the original span, not arc length. For a recipe-side
    spline knot interval [a,b], interpolate support at a+t*(b-a); conversion from
    another curve representation and support/width validation are caller-owned.
    """
    error = _number(tolerance, "tolerance", positive=True)
    _validate_limits(limits)
    authored = _read_spans(spans)
    if len(authored) + 1 > limits.max_total_points:
        raise CurveSamplingError(
            "total_points_exhausted", "authored joins already exceed point budget"
        )
    tolerance_squared = Fraction(error) ** 2
    points = []
    float32_points = []
    certificates = []
    work = 0
    for span_index, span in enumerate(authored):
        controls = tuple(_exact(point) for point in span.control_points)
        first = _emit_endpoint(
            controls[0], span.control_points[0], tolerance_squared, span.span_id
        )
        last = _emit_endpoint(
            controls[-1], span.control_points[-1], tolerance_squared, span.span_id
        )
        if not points:
            points.append(first[0])
            float32_points.append(first[1])
        # DFS pushes right then left, so every accepted chord extends the output.
        stack = [(controls, 0.0, 1.0, 0, first, last)]
        span_points = 1
        while stack:
            if work >= limits.max_work:
                raise CurveSamplingError(
                    "work_exhausted",
                    "visited-subcurve budget exhausted",
                    span_id=span.span_id,
                )
            node, t0, t1, depth, start, end = stack.pop()
            work += 1
            source_bound = _hull_bound(node, start[0], end[0])
            serialized_bound = _hull_bound(node, start[1], end[1])
            collapsed = start[0] == end[0] or start[1] == end[1]
            if (
                not collapsed
                and max(source_bound, serialized_bound) <= tolerance_squared
            ):
                if span_points >= limits.max_points_per_span:
                    raise CurveSamplingError(
                        "span_points_exhausted",
                        "per-span point budget exhausted",
                        span_id=span.span_id,
                    )
                if len(points) >= limits.max_total_points:
                    raise CurveSamplingError(
                        "total_points_exhausted",
                        "total point budget exhausted",
                        span_id=span.span_id,
                    )
                certificates.append(
                    SegmentCertificate(
                        span_index,
                        span.span_id,
                        t0,
                        t1,
                        len(points) - 1,
                        len(points),
                        depth,
                        source_bound.as_integer_ratio(),
                        serialized_bound.as_integer_ratio(),
                    )
                )
                points.append(end[0])
                float32_points.append(end[1])
                span_points += 1
                continue
            if depth >= limits.max_depth:
                raise CurveSamplingError(
                    "depth_exhausted",
                    "unresolved chord at maximum subdivision depth",
                    span_id=span.span_id,
                )
            # Splitting needs at least one extra endpoint for each pending leaf.
            if span_points + len(stack) + 2 > limits.max_points_per_span:
                raise CurveSamplingError(
                    "span_points_exhausted",
                    "subdivision exceeds per-span point budget",
                    span_id=span.span_id,
                )
            remaining_spans = len(authored) - span_index - 1
            if len(points) + len(stack) + 2 + remaining_spans > limits.max_total_points:
                raise CurveSamplingError(
                    "total_points_exhausted",
                    "subdivision exceeds total point budget",
                    span_id=span.span_id,
                )
            left, right = _split(node)
            middle_source = (float(left[-1][0]), float(left[-1][1]))
            middle = _emit_endpoint(
                left[-1], middle_source, tolerance_squared, span.span_id
            )
            tm = (t0 + t1) / 2
            stack.append((right, tm, t1, depth + 1, middle, end))
            stack.append((left, t0, tm, depth + 1, start, middle))
    return SampledBezierChain(
        authored,
        tuple(points),
        tuple(float32_points),
        tuple(certificates),
        error,
        limits,
        work,
    )
