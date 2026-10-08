"""Continuous-bound adversaries, actual serialization and finite-budget refusals."""

import math
import struct
from collections.abc import Sequence
from dataclasses import asdict, replace
from fractions import Fraction

import pytest

from codex_blender_modeler.structural_geometry import cubic_bezier_sampling as sampler
from codex_blender_modeler.structural_geometry.cubic_bezier_sampling import (
    CubicBezierSpan,
    CurveSamplingError,
    SamplingLimits,
    sample_cubic_bezier_chain,
)

LIMITS = SamplingLimits(24, 4096, 4096, 16384)


def span(controls, name="curve"):
    """Build an explicit small authored cubic for each independent case."""
    return CubicBezierSpan(name, tuple(tuple(point) for point in controls))


def evaluate(controls, t):
    """Evaluate original controls by the independent Bernstein polynomial formula."""
    weights = ((1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t**3)
    return tuple(
        sum(w * p[k] for w, p in zip(weights, controls, strict=True)) for k in (0, 1)
    )


def distance(point, start, end):
    """Independently measure finite-segment Euclidean distance with a clipped projection."""
    delta = tuple(b - a for a, b in zip(start, end, strict=True))
    squared = sum(value * value for value in delta)
    t = (
        0
        if squared == 0
        else max(
            0,
            min(
                1,
                sum((p - a) * d for p, a, d in zip(point, start, delta, strict=True))
                / squared,
            ),
        )
    )
    return math.dist(point, tuple(a + t * d for a, d in zip(start, delta, strict=True)))


def sample(controls, tolerance=0.01, limits=LIMITS):
    """Request the same explicit bounds for one test cubic."""
    return sample_cubic_bezier_chain(
        [span(controls)], tolerance=tolerance, limits=limits
    )


def assert_correspondence_and_dense_bound(result):
    """Corroborate both certified polylines densely without treating probes as proof."""
    assert len(result.points) == len(result.segments) + 1
    assert len(result.points) == len(result.float32_points)
    assert result.work_count <= result.limits.max_work
    previous_by_span = {}
    for i, certificate in enumerate(result.segments):
        assert certificate.point_start_index == i
        assert certificate.point_end_index == i + 1
        assert certificate.parameter_start == previous_by_span.get(
            certificate.span_index, 0
        )
        assert certificate.parameter_start < certificate.parameter_end <= 1
        previous_by_span[certificate.span_index] = certificate.parameter_end
        controls = result.spans[certificate.span_index].control_points
        assert certificate.span_id == result.spans[certificate.span_index].span_id
        for path, ratio in (
            (result.points, certificate.source_bound_squared),
            (result.float32_points, certificate.float32_bound_squared),
        ):
            assert path[i] != path[i + 1]
            assert Fraction(*ratio) <= Fraction(result.tolerance) ** 2
            for j in range(65):
                t = certificate.parameter_start + j / 64 * (
                    certificate.parameter_end - certificate.parameter_start
                )
                measured = distance(evaluate(controls, t), path[i], path[i + 1])
                # This numeric corroboration has roundoff; exact acceptance has no epsilon.
                assert measured <= result.tolerance + 1e-9
    assert set(previous_by_span.values()) == {1}
    for source, actual in zip(result.points, result.float32_points, strict=True):
        assert actual == struct.unpack("!2f", struct.pack("!2f", *source))


def test_three_probes_miss_true_cubic_maximum():
    """Demonstrate a known continuous deviation hidden by all three old probes."""
    controls = ((0, 0), (1 / 3, 1), (2 / 3, 0), (1, 0))
    old_probe_max = max(evaluate(controls, t)[1] for t in (0.25, 0.5, 0.75))
    assert old_probe_max == 0.421875 < 0.43
    assert evaluate(controls, 1 / 3)[1] > 0.43
    result = sample(controls, 0.43)
    assert len(result.points) > 2
    assert_correspondence_and_dense_bound(result)


@pytest.mark.parametrize(
    "controls",
    [
        ((0, 0), (1, 2), (-1, 2), (0, 0)),
        ((0, 0), (2, 4), (-2, -4), (0.0001, 0.00001)),
        ((0, 0), (1, 2), (2, -2), (3, 0)),
        ((0, 0), (3, 0), (-2, 0), (1, 0)),
        ((0, 0), (1, 1), (0, 1), (1, 0)),
        ((0, 0), (0, 0), (1, 1), (1, 1)),
    ],
)
def test_loops_inflections_reversals_cusps_and_repeated_controls(controls):
    """Retain challenging authored shapes without claiming their topology is valid."""
    assert_correspondence_and_dense_bound(sample(controls))


def test_finite_chord_distance_catches_collinear_overshoot():
    """Collinear controls outside the finite chord cannot receive a zero bound."""
    result = sample(((0, 0), (3, 0), (3, 0), (1, 0)), tolerance=0.05)
    assert max(point[0] for point in result.points) > 2
    assert len(result.points) > 2
    assert_correspondence_and_dense_bound(result)


def test_long_flat_span_has_no_unrequested_spacing_requirement():
    """A long straight path can be cheap when only geometric error is requested."""
    result = sample(((-600000, 0), (-400000, 0), (400000, 0), (600000, 0)), 1e-12)
    assert len(result.points) == 2 and result.work_count == 1
    assert result.segments[0].source_bound_squared == (0, 1)
    assert result.segments[0].float32_bound_squared == (0, 1)


@pytest.mark.parametrize("scale,offset", [(1, 0), (0.00001, 0), (100, 0), (1, 1000)])
def test_translated_rescaled_curve_is_certified_in_its_final_space(scale, offset):
    """Test actual final coordinates, including meaningful float32 translation error."""
    controls = tuple(
        (offset + scale * x, offset + scale * y)
        for x, y in ((0, 0), (1, 2), (2, -1), (3, 0))
    )
    assert_correspondence_and_dense_bound(sample(controls, 0.002 * scale))


def test_corners_source_endpoints_and_span_provenance_are_retained():
    """Keep a sharp authored join exactly once, plus its two span identities."""
    spans = [
        span(((-0.0, 0.0), (0.2, 0), (0.8, 0), (1.0, 0.0)), "horizontal"),
        span(((1.0, 0.0), (1, 0.2), (1, 0.8), (1.0, 1.0)), "vertical"),
    ]
    result = sample_cubic_bezier_chain(spans, tolerance=0.001, limits=LIMITS)
    assert result.points == ((-0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
    assert struct.pack("!2d", *result.points[0]) == struct.pack(
        "!2d", *spans[0].control_points[0]
    )
    assert [s.span_id for s in result.segments] == ["horizontal", "vertical"]
    assert_correspondence_and_dense_bound(result)


def test_endpoint_binary32_bits_and_original_double_bits_are_bound():
    """Keep original float endpoints while certifying their distinct serialized positions."""
    controls = ((0.1, 0.2), (0.2, 0.6), (0.7, 0.8), (0.9, 0.3))
    result = sample(controls, 0.001)
    assert result.points[0] == controls[0] and result.points[-1] == controls[-1]
    assert result.float32_points[0] != controls[0]
    assert (
        result.segments[0].float32_bound_squared
        != result.segments[0].source_bound_squared
    )
    assert_correspondence_and_dense_bound(result)


@pytest.mark.parametrize(
    "limit,reason",
    [
        ({"max_depth": 0}, "depth_exhausted"),
        ({"max_points_per_span": 2}, "span_points_exhausted"),
        ({"max_total_points": 2}, "total_points_exhausted"),
        ({"max_work": 1}, "work_exhausted"),
    ],
)
def test_independent_budgets_refuse_underresolved_paths(limit, reason):
    """Each explicit exhausted budget must raise instead of returning coarse geometry."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(((0, 0), (0, 1), (1, 1), (1, 0)), 0.001, replace(LIMITS, **limit))
    assert caught.value.reason == reason


def test_initial_join_budget_is_bounded_before_subdivision():
    """Even perfectly straight authored spans cannot exceed the total station budget."""
    spans = [
        span(((i, 0), (i + 0.25, 0), (i + 0.75, 0), (i + 1, 0)), str(i))
        for i in range(3)
    ]
    with pytest.raises(CurveSamplingError, match="joins") as caught:
        sample_cubic_bezier_chain(
            spans, tolerance=0.1, limits=replace(LIMITS, max_total_points=3)
        )
    assert caught.value.reason == "total_points_exhausted"


def test_endpoint_precision_exhaustion_is_distinct_from_work_exhaustion():
    """A float32 endpoint quantization larger than tolerance refuses immediately."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(((100000.001, 0.1), (100001, 2), (100002, 2), (100003, 0.1)), 1e-5)
    assert caught.value.reason == "precision_unattainable"


def test_subnormal_serialized_collapse_never_returns_duplicate_points():
    """Tiny source points which all serialize to zero cannot form an emitted path."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(((0, 0), (1e-46, 0), (2e-46, 0), (3e-46, 0)), 1e-44)
    assert caught.value.reason == "depth_exhausted"


@pytest.mark.parametrize(
    "controls",
    [
        ((0, 0), (1, 2), (-1, 2), (0, 0)),
        ((1, 0), (100, 100), (-100, -100), (1 + 1e-9, 0)),
    ],
)
def test_collapsed_chord_at_caller_depth_is_not_proven_precision_failure(controls):
    """A coarse collapsed chord may resolve by subdivision, so report only depth exhaustion."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(controls, 1000, replace(LIMITS, max_depth=0))
    assert caught.value.reason == "depth_exhausted"
    assert_correspondence_and_dense_bound(sample(controls, 1000))


def test_nonfinite_emission_guard_is_distinct(monkeypatch):
    """Fault injection verifies the fail-closed output guard, independent of valid input caps."""
    monkeypatch.setattr(sampler, "_float32", lambda _: (math.nan, 0.0))
    with pytest.raises(CurveSamplingError) as caught:
        sample(((0, 0), (0, 1), (1, 1), (1, 0)))
    assert caught.value.reason == "nonfinite_output"


@pytest.mark.parametrize(
    "value",
    [True, False, "0.1", None, complex(1, 0), math.nan, math.inf, -math.inf, 10**400],
)
def test_invalid_coordinate_types_and_values(value):
    """Reject booleans, coercible strings, nonfinite numbers and oversized coordinates."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(((value, 0), (0, 1), (1, 1), (1, 0)))
    assert caught.value.reason == "invalid_input"


@pytest.mark.parametrize("value", [True, "1", None, 0, -1, math.nan, math.inf, 1000001])
def test_invalid_tolerance(value):
    """Tolerance is explicit, finite, positive, numeric and bounded."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(((0, 0), (0, 1), (1, 1), (1, 0)), value)
    assert caught.value.reason == "invalid_input"


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_depth", True),
        ("max_depth", -1),
        ("max_depth", 25),
        ("max_points_per_span", 1),
        ("max_points_per_span", 4097),
        ("max_total_points", 2.0),
        ("max_total_points", 4097),
        ("max_work", 0),
        ("max_work", 16385),
        ("max_work", "100"),
    ],
)
def test_limit_validation(field, value):
    """Caller limits cannot disable hard caps or rely on type coercion."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(
            ((0, 0), (0, 1), (1, 1), (1, 0)), limits=replace(LIMITS, **{field: value})
        )
    assert caught.value.reason == "invalid_input"


@pytest.mark.parametrize(
    "spans",
    [
        [],
        "span",
        [None],
        [span(((0, 0), (1, 0), (2, 0)), "short")],
        [span(((0, 0, 0), (1, 0), (2, 0), (3, 0)), "3d")],
        [span(((0, 0), (1, 0), (2, 0), (3, 0)), "")],
        [span(((0, 0), (1, 0), (2, 0), (3, 0)), "a" * 129)],
        [span(((0, 0), (1, 0), (2, 0), (3, 0)), "duplicate")] * 2,
        [span(((0, 0), (1, 0), (2, 0), (3, 0)), str(i)) for i in range(129)],
    ],
)
def test_invalid_span_shape_count_and_identity(spans):
    """Only bounded, uniquely identified, explicitly planar chains are accepted."""
    with pytest.raises(CurveSamplingError) as caught:
        sample_cubic_bezier_chain(spans, tolerance=0.1, limits=LIMITS)
    assert caught.value.reason == "invalid_input"


@pytest.mark.parametrize("next_start", [(2, 0), (1, -0.0)])
def test_disconnected_or_signed_zero_mismatched_joins_refuse(next_start):
    """No guessed welding or approximate endpoint snapping can change authored controls."""
    spans = [
        span(((0, 0), (0.2, 0), (0.8, 0), (1, 0)), "first"),
        span((next_start, (1, 1), (2, 1), (2, 2)), "second"),
    ]
    with pytest.raises(CurveSamplingError) as caught:
        sample_cubic_bezier_chain(spans, tolerance=0.01, limits=LIMITS)
    assert caught.value.reason == "disconnected_chain"


def test_constant_span_policy_is_explicit():
    """Do not silently erase an authored constant span or emit a duplicate station."""
    with pytest.raises(CurveSamplingError) as caught:
        sample(((2, 3),) * 4)
    assert caught.value.reason == "constant_span"


def test_exact_threshold_is_not_relaxed_with_epsilon():
    """A serialized endpoint one exact unit away passes at one and fails immediately below."""
    # 2**-150 is exactly halfway to the smallest positive binary32; ties round to zero.
    tiny = 2.0**-150
    controls = ((0, tiny), (1, tiny), (2, tiny), (3, tiny))
    result = sample(controls, tiny)
    assert len(result.points) == 2
    assert Fraction(*result.segments[0].float32_bound_squared) == Fraction(tiny) ** 2
    with pytest.raises(CurveSamplingError) as caught:
        sample(controls, math.nextafter(tiny, 0))
    assert caught.value.reason == "precision_unattainable"


def test_determinism_and_input_snapshot():
    """Repeated calls agree exactly and later list mutation cannot alter retained controls."""
    controls = [[0, 0], [1, 2], [2, -1], [3, 0]]
    original = CubicBezierSpan("owned", controls)
    first = sample_cubic_bezier_chain([original], tolerance=0.001, limits=LIMITS)
    second = sample_cubic_bezier_chain([original], tolerance=0.001, limits=LIMITS)
    assert asdict(first) == asdict(second)
    controls[1][1] = 999
    assert first.spans[0].control_points[1] == (1, 2)


class EvasiveSequence(Sequence):
    """Advertise a finite size but refuse traversal to expose a premature method call."""

    def __len__(self):
        """Pretend to be a valid one-span container."""
        return 1

    def __getitem__(self, key):
        """Fail quickly instead of hanging if a sampler trusts custom iteration."""
        raise AssertionError("custom sequence traversal must never execute")


class EvasiveList(list):
    """List subclass with iteration that does not honor its materialized elements."""

    def __iter__(self):
        """Fail quickly if a sampler treats a subclass as bounded built-in data."""
        raise AssertionError("custom list iteration must never execute")


class EvasiveTuple(tuple):
    """Tuple subclass with an untrusted iterator despite immutable base storage."""

    def __iter__(self):
        """Fail quickly if a sampler invokes the override."""
        raise AssertionError("custom tuple iteration must never execute")


@pytest.mark.parametrize("container", [EvasiveSequence, EvasiveList, EvasiveTuple])
@pytest.mark.parametrize("boundary", ["spans", "controls", "coordinates"])
def test_custom_containers_cannot_escape_checked_length(container, boundary):
    """Reject overrides at all three boundaries before invoking their iteration methods."""
    controls = ((0, 0), (0, 1), (1, 1), (1, 0))
    original = span(controls)
    values = {"spans": [original], "controls": controls, "coordinates": controls[0]}
    custom = (
        container() if container is EvasiveSequence else container(values[boundary])
    )
    spans = [original]
    if boundary == "spans":
        spans = custom
    elif boundary == "controls":
        spans = [CubicBezierSpan("curve", custom)]
    else:
        spans = [CubicBezierSpan("curve", (custom, *controls[1:]))]
    with pytest.raises(CurveSamplingError) as caught:
        sample_cubic_bezier_chain(spans, tolerance=0.01, limits=LIMITS)
    assert caught.value.reason == "invalid_input"


def test_input_dataclass_and_id_subclasses_are_not_an_execution_surface():
    """Exact input types keep overridden attribute and hash methods out of the data contract."""

    class DerivedSpan(CubicBezierSpan):
        """An unrequested extension of the explicit input contract."""

    class DerivedLimits(SamplingLimits):
        """An unrequested extension of the explicit budget contract."""

    class DerivedId(str):
        """A string subclass can define arbitrary hash behavior."""

        def __hash__(self):
            """Ensure the rejection precedes placing an ID in the uniqueness set."""
            raise AssertionError("custom ID hashing must never execute")

    controls = ((0, 0), (0, 1), (1, 1), (1, 0))
    for spans, limits in (
        ([DerivedSpan("curve", controls)], LIMITS),
        ([CubicBezierSpan(DerivedId("curve"), controls)], LIMITS),
        ([span(controls)], DerivedLimits(24, 4096, 4096, 16384)),
    ):
        with pytest.raises(CurveSamplingError) as caught:
            sample_cubic_bezier_chain(spans, tolerance=0.01, limits=limits)
        assert caught.value.reason == "invalid_input"
