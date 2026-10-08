"""Offline, bounded cubic centerline/profile sampling; no mesh or execution hooks.

The acceptance predicate uses exact rational Bezier control-hull bounds against
the emitted float endpoint chord. It proves parameter-matched positional and
scalar-profile error, including endpoint rounding, but no swept-surface bound.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Literal, TypeAlias, cast

Vec3: TypeAlias = tuple[float, float, float]
Row: TypeAlias = tuple[float, float, float, float, float]
Controls: TypeAlias = tuple[Row, Row, Row, Row]
ExactRow: TypeAlias = tuple[Fraction, ...]
ExactControls: TypeAlias = tuple[ExactRow, ...]

MAX_SPANS = 128
MAX_FEATURES = 256
MAX_SAMPLES = 4096
MAX_DEPTH = 24
MAX_EVALUATIONS = 16384
ENVELOPE = 1.0e6


class SamplingError(ValueError):
    """Reject malformed data or a tolerance that cannot be met within limits."""


@dataclass(frozen=True)
class CubicSpan:
    """A cubic over [start, end], with (x, y, z, width, height) controls.

    Width/height have caller-defined consistent units (e.g. radii or diameters).
    Every scalar profile control must be positive: this conservative condition
    guarantees a positive whole profile without silent clamping or root finding.
    """

    start: float
    end: float
    controls: Controls


@dataclass(frozen=True)
class Sample:
    """One exact float station and its rounded center/profile values."""

    station: float
    center: Vec3
    width: float
    height: float


@dataclass(frozen=True)
class IntervalEvidence:
    """Conservative whole-interval errors, outward-rounded for reporting."""

    source_span: int
    start: float
    end: float
    depth: int
    center_error_bound: float
    width_error_bound: float
    height_error_bound: float


@dataclass(frozen=True)
class SamplingEvidence:
    """Deterministic source binding, acceptance limits, errors, and work counts."""

    algorithm: str
    input_sha256: str
    input_spans: int
    preserved_stations: tuple[float, ...]
    center_tolerance: float
    width_tolerance: float
    height_tolerance: float
    max_center_error_bound: float
    max_width_error_bound: float
    max_height_error_bound: float
    samples: int
    evaluated_intervals: int
    forced_splits: int
    adaptive_splits: int
    maximum_depth: int


@dataclass(frozen=True)
class SamplingResult:
    """Plain numeric authoring data and its interval-level evidence."""

    samples: tuple[Sample, ...]
    intervals: tuple[IntervalEvidence, ...]
    evidence: SamplingEvidence

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable data without writing or invoking anything."""
        return asdict(self)


def _number(value: object, name: str, *, positive: bool = False) -> float:
    """Accept finite bounded built-in numbers; reject booleans and overflow."""
    if type(value) not in (int, float):
        raise SamplingError(f"{name} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise SamplingError(f"{name} must be a finite bounded number") from exc
    if not math.isfinite(result) or abs(result) > ENVELOPE or (positive and result <= 0):
        raise SamplingError(
            f"{name} must be finite, within +/-{ENVELOPE}, and positive if required"
        )
    return result


def _sequence(value: object, low: int, high: int, name: str) -> list | tuple:
    """Bound traversal before accepting explicit list/tuple data."""
    if type(value) not in (list, tuple) or not low <= len(value) <= high:
        raise SamplingError(f"{name} requires {low}..{high} explicit entries")
    return value


def _integer(value: object, low: int, high: int, name: str) -> int:
    """Reject booleans/nonintegers and enforce a finite work envelope."""
    if type(value) is not int or not low <= value <= high:
        raise SamplingError(f"{name} must be an integer in {low}..{high}")
    return value


def _row(value: object) -> Row:
    """Validate one 3D center with two strictly positive profile dimensions."""
    values = _sequence(value, 5, 5, "control")
    return cast(Row, tuple(_number(v, "control", positive=i >= 3) for i, v in enumerate(values)))


def _validated_spans(spans: list[CubicSpan] | tuple[CubicSpan, ...]) -> tuple[CubicSpan, ...]:
    """Require ordered contiguous parameter intervals and exact C0 joins."""
    result = []
    for item in _sequence(spans, 1, MAX_SPANS, "spans"):
        if type(item) is not CubicSpan:
            raise SamplingError("spans must contain CubicSpan records")
        start, end = _number(item.start, "start"), _number(item.end, "end")
        controls = cast(
            Controls, tuple(_row(v) for v in _sequence(item.controls, 4, 4, "controls"))
        )
        if start >= end:
            raise SamplingError("each span must have start < end")
        if result and (result[-1].end != start or result[-1].controls[-1] != controls[0]):
            raise SamplingError("spans must be contiguous with exactly matching endpoints")
        result.append(CubicSpan(start, end, controls))
    return tuple(result)


def _split(controls: ExactControls, u: Fraction) -> tuple[ExactControls, ExactControls]:
    """Split a cubic by exact de Casteljau interpolation, preserving the curve."""
    levels = [controls]
    for _ in range(3):
        previous = levels[-1]
        levels.append(
            tuple(
                tuple((1 - u) * a + u * b for a, b in zip(left, right, strict=True))
                for left, right in zip(previous, previous[1:], strict=False)
            )
        )
    return tuple(level[0] for level in levels), tuple(level[-1] for level in reversed(levels))


def _bounds(controls: ExactControls) -> tuple[Fraction, Fraction, Fraction]:
    """Bound curve minus emitted chord using all four exact residual controls.

    A cubic's Bernstein weights are nonnegative and sum to one. Their convex
    hull bounds the vector norm and scalar absolute error for every parameter.
    The line is degree-elevated to cubic; rounded output endpoints are included.
    """
    first = tuple(Fraction(float(v)) for v in controls[0])
    last = tuple(Fraction(float(v)) for v in controls[-1])
    residuals = [
        tuple(v - ((3 - i) * a + i * b) / 3 for v, a, b in zip(row, first, last, strict=True))
        for i, row in enumerate(controls)
    ]
    return (
        max(sum(v * v for v in row[:3]) for row in residuals),
        max(abs(row[3]) for row in residuals),
        max(abs(row[4]) for row in residuals),
    )


def _upper(value: Fraction, *, square_root: bool = False) -> float:
    """Round a nonnegative exact bound outward, including underflow cases."""
    if not value:
        return 0.0
    if square_root:
        with localcontext() as context:
            context.prec = 40
            result = float((Decimal(value.numerator) / Decimal(value.denominator)).sqrt())
        while Fraction(result) ** 2 < value:
            result = math.nextafter(result, math.inf)
    else:
        result = float(value)
        while Fraction(result) < value:
            result = math.nextafter(result, math.inf)
    return result


def _sample(station: float, row: ExactRow) -> Sample:
    """Convert a proven endpoint into the exact floats used in its chord bound."""
    values = tuple(float(v) for v in row)
    return Sample(station, cast(Vec3, values[:3]), values[3], values[4])


def adaptive_sample(
    spans: list[CubicSpan] | tuple[CubicSpan, ...],
    *,
    center_tolerance: float,
    width_tolerance: float,
    height_tolerance: float,
    feature_stations: list[float] | tuple[float, ...] = (),
    max_samples: int = MAX_SAMPLES,
    max_depth: int = MAX_DEPTH,
    max_evaluations: int = MAX_EVALUATIONS,
) -> SamplingResult:
    """Sample exact input cubics, retaining every span boundary and feature.

    Acceptance bounds the entire parameter interval, not a finite probe set.
    No partial success is returned on an exhausted budget or float parameter
    resolution. Declared corners must be span boundaries; their tangents are
    never altered. Coincident spatial endpoints and closed routes are retained.
    """
    spans = _validated_spans(spans)
    tolerances = tuple(
        _number(v, "tolerance", positive=True)
        for v in (
            center_tolerance,
            width_tolerance,
            height_tolerance,
        )
    )
    max_samples = _integer(max_samples, 2, MAX_SAMPLES, "max_samples")
    max_depth = _integer(max_depth, 0, MAX_DEPTH, "max_depth")
    max_evaluations = _integer(max_evaluations, 1, MAX_EVALUATIONS, "max_evaluations")
    features = sorted(
        set(
            _number(v, "feature station")
            for v in _sequence(
                feature_stations,
                0,
                MAX_FEATURES,
                "feature_stations",
            )
        )
    )
    if any(v < spans[0].start or v > spans[-1].end for v in features):
        raise SamplingError("feature stations must lie inside the authored parameter domain")
    preserved = tuple(sorted(set(features + [s.start for s in spans] + [spans[-1].end])))
    if len(preserved) > max_samples:
        raise SamplingError("required stations exceed max_samples")
    exact_tolerances = tuple(Fraction(v) for v in tolerances)
    seeds = []
    forced_splits = 0
    for index, span in enumerate(spans):
        controls = tuple(tuple(Fraction(v) for v in row) for row in span.controls)
        start = span.start
        for stop in [v for v in features if start < v < span.end] + [span.end]:
            if stop == span.end:
                left = controls
            else:
                u = (Fraction(stop) - Fraction(start)) / (Fraction(span.end) - Fraction(start))
                left, controls = _split(controls, u)
                forced_splits += 1
            seeds.append((index, start, stop, left, 0))
            start = stop
    stack = list(reversed(seeds))
    samples: list[Sample] = []
    intervals: list[IntervalEvidence] = []
    evaluated = adaptive_splits = 0
    while stack:
        index, start, end, controls, depth = stack.pop()
        if evaluated == max_evaluations:
            raise SamplingError("max_evaluations exhausted; no certified result")
        evaluated += 1
        center_squared, width_error, height_error = _bounds(controls)
        if (
            center_squared <= exact_tolerances[0] ** 2
            and width_error <= exact_tolerances[1]
            and height_error <= exact_tolerances[2]
        ):
            if not samples:
                samples.append(_sample(start, controls[0]))
            samples.append(_sample(end, controls[-1]))
            intervals.append(
                IntervalEvidence(
                    index,
                    start,
                    end,
                    depth,
                    _upper(center_squared, square_root=True),
                    _upper(width_error),
                    _upper(height_error),
                )
            )
            continue
        if depth == max_depth:
            raise SamplingError("max_depth exhausted; no certified result")
        if len(intervals) + len(stack) + 3 > max_samples:
            raise SamplingError("max_samples exhausted; no certified result")
        midpoint = float((Fraction(start) + Fraction(end)) / 2)
        if not start < midpoint < end:
            raise SamplingError("float parameter resolution exhausted; no certified result")
        u = (Fraction(midpoint) - Fraction(start)) / (Fraction(end) - Fraction(start))
        left, right = _split(controls, u)
        adaptive_splits += 1
        stack.append((index, midpoint, end, right, depth + 1))
        stack.append((index, start, midpoint, left, depth + 1))
    source = json.dumps(
        {
            "spans": [asdict(s) for s in spans],
            "feature_stations": features,
            "tolerances": tolerances,
            "limits": [max_samples, max_depth, max_evaluations],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    evidence = SamplingEvidence(
        "exact-cubic-control-hull-v1",
        hashlib.sha256(source).hexdigest(),
        len(spans),
        preserved,
        *tolerances,
        max(i.center_error_bound for i in intervals),
        max(i.width_error_bound for i in intervals),
        max(i.height_error_bound for i in intervals),
        len(samples),
        evaluated,
        forced_splits,
        adaptive_splits,
        max(i.depth for i in intervals),
    )
    return SamplingResult(tuple(samples), tuple(intervals), evidence)


def catmull_rom_spans(
    rows: list[Row] | tuple[Row, ...],
    *,
    corner_indices: list[int] | tuple[int, ...] = (),
    profile_mode: Literal["catmull-rom", "linear"] = "catmull-rom",
) -> tuple[CubicSpan, ...]:
    """Convert uniform Catmull-Rom authoring rows to explicit cubic float data.

    Endpoints use repeated controls, matching the previous authoring formula.
    Each declared interior corner gets independent incoming/outgoing secant
    tangents, and remains a required station. Controls are rounded once here;
    sampling certifies these returned cubics, not another implementation's
    floating arithmetic. Nonpositive profile handles are refused, never clamped.
    The caller may explicitly choose linear profiles to avoid cubic overshoot.
    """
    values = tuple(_row(v) for v in _sequence(rows, 2, MAX_SPANS + 1, "rows"))
    corners = set(
        _integer(v, 1, len(values) - 2, "corner index")
        for v in _sequence(
            corner_indices,
            0,
            max(0, len(values) - 2),
            "corner_indices",
        )
    )
    if profile_mode not in ("catmull-rom", "linear"):
        raise SamplingError("unknown profile_mode")
    result = []
    for i in range(len(values) - 1):
        a, b, c, d = (
            values[max(0, i - 1)],
            values[i],
            values[i + 1],
            values[min(len(values) - 1, i + 2)],
        )
        first: list[float] = []
        second: list[float] = []
        for axis in range(5):
            av, bv, cv, dv = (Fraction(row[axis]) for row in (a, b, c, d))
            linear = axis >= 3 and profile_mode == "linear"
            first.append(float(bv + ((cv - bv) / 3 if i in corners or linear else (cv - av) / 6)))
            second.append(
                float(cv - ((cv - bv) / 3 if i + 1 in corners or linear else (dv - bv) / 6))
            )
        result.append(
            CubicSpan(
                float(i),
                float(i + 1),
                (b, cast(Row, tuple(first)), cast(Row, tuple(second)), c),
            )
        )
    return _validated_spans(result)


def estimated_ring_cost(sample_count: int, section_vertices: int) -> dict[str, int]:
    """Count an open sweep with matching rings and fan-triangulated polygon caps.

    This is an estimate for a specific topology, not a generated or validated
    mesh. It excludes separate cap-center vertices, holes, seams, and modifiers.
    """
    count = _integer(sample_count, 2, MAX_SAMPLES, "sample_count")
    section = _integer(section_vertices, 3, 256, "section_vertices")
    return {
        "vertices": count * section,
        "side_triangles": 2 * (count - 1) * section,
        "cap_triangles": 2 * (section - 2),
        "total_triangles": 2 * count * section - 4,
    }
