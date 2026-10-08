"""Independent whole-curve probes and contract/adversarial sampling checks."""

import json
import math
import random
from fractions import Fraction

import pytest

from codex_blender_modeler.adaptive_sweep_authoring import (
    MAX_DEPTH,
    MAX_EVALUATIONS,
    MAX_FEATURES,
    MAX_SAMPLES,
    MAX_SPANS,
    CubicSpan,
    SamplingError,
    adaptive_sample,
    catmull_rom_spans,
    estimated_ring_cost,
)


def row(x, y=0.0, z=0.0, width=1.0, height=1.0):
    """Construct explicit float data for fixtures."""
    return tuple(float(v) for v in (x, y, z, width, height))


def curve(controls=None, start=0.0, end=1.0):
    """Use a bowed cubic unless explicit controls are supplied."""
    return CubicSpan(start, end, controls or (row(0), row(1, 2), row(2, -2), row(3)))


def sample(spans, tolerance=0.01, **options):
    """Apply a common test tolerance with explicit optional work limits."""
    return adaptive_sample(
        spans,
        center_tolerance=tolerance,
        width_tolerance=tolerance,
        height_tolerance=tolerance,
        **options,
    )


def exact_evaluate(span, station):
    """Evaluate the original cubic using independent Bernstein polynomials."""
    u = (station - Fraction(span.start)) / (Fraction(span.end) - Fraction(span.start))
    weights = ((1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u**3)
    return tuple(
        sum(Fraction(p[axis]) * w for p, w in zip(span.controls, weights, strict=True))
        for axis in range(5)
    )


def assert_probes_bounded(spans, result, probes=31):
    """Compare source cubics to emitted chords without using sampler internals."""
    for evidence, left, right in zip(
        result.intervals, result.samples, result.samples[1:], strict=False
    ):
        a = (*left.center, left.width, left.height)
        b = (*right.center, right.width, right.height)
        for step in range(probes + 1):
            u = Fraction(step, probes)
            station = (1 - u) * Fraction(left.station) + u * Fraction(right.station)
            original = exact_evaluate(spans[evidence.source_span], station)
            chord = tuple(
                (1 - u) * Fraction(x) + u * Fraction(y) for x, y in zip(a, b, strict=True)
            )
            error = tuple(x - y for x, y in zip(original, chord, strict=True))
            assert sum(v * v for v in error[:3]) <= Fraction(evidence.center_error_bound) ** 2
            assert abs(error[3]) <= Fraction(evidence.width_error_bound)
            assert abs(error[4]) <= Fraction(evidence.height_error_bound)


def test_linear_curve_uses_only_required_stations():
    """A genuinely linear 3D curve/profile needs no discretionary subdivisions."""
    spans = [
        curve((row(0, 0, 0, 1, 4), row(1, 2, 3, 2, 3), row(2, 4, 6, 3, 2), row(3, 6, 9, 4, 1)))
    ]
    result = sample(spans, feature_stations=[0.8, 0.2, 0.2])
    assert [v.station for v in result.samples] == [0.0, 0.2, 0.8, 1.0]
    assert result.evidence.forced_splits == 2
    assert result.evidence.adaptive_splits == 0
    assert_probes_bounded(spans, result)


def test_midpoint_aliasing_does_not_hide_s_curve():
    """The zero midpoint deviation of an S curve must not suppress refinement."""
    spans = [curve()]
    assert exact_evaluate(spans[0], Fraction(1, 2))[1] == 0
    result = sample(spans)
    assert len(result.samples) > 4
    assert result.evidence.max_center_error_bound <= 0.01
    assert_probes_bounded(spans, result, 97)


@pytest.mark.parametrize("axis", [3, 4])
def test_profile_curvature_refines_a_straight_center(axis):
    """Width and height each independently trigger additional stations."""
    controls = [list(row(i)) for i in range(4)]
    controls[1][axis] = controls[2][axis] = 3.0
    spans = [curve(tuple(tuple(p) for p in controls))]
    result = sample(spans, 0.005)
    assert len(result.samples) > 2
    assert result.evidence.max_center_error_bound == 0
    assert result.evidence.max_width_error_bound <= 0.005
    assert result.evidence.max_height_error_bound <= 0.005
    assert_probes_bounded(spans, result)


def test_declared_corner_uses_independent_secants_and_is_retained():
    """A corner has different left/right tangents at the original exact point."""
    rows = [row(0), row(1), row(1, 1), row(2, 1)]
    spans = catmull_rom_spans(rows, corner_indices=[1], profile_mode="linear")
    assert spans[0].controls[2][1] == 0
    assert spans[1].controls[1][0] == 1
    result = sample(spans)
    station = next(s for s in result.samples if s.station == 1)
    assert station.center == rows[1][:3]
    assert set(range(len(rows))) <= {s.station for s in result.samples}
    assert_probes_bounded(spans, result)


def test_closed_route_does_not_drop_spatially_repeated_endpoint():
    """Closed-route interpretation stays with the downstream mesher."""
    result = sample(catmull_rom_spans([row(0), row(1, 1), row(0)]))
    assert result.samples[0].center == result.samples[-1].center
    assert result.samples[0].station != result.samples[-1].station


def test_deterministic_bytes_and_order():
    """Fixed inputs produce stable sample order, evidence, and serialized bytes."""
    spans = [curve()]
    first = sample(spans, feature_stations=[0.73, 0.1])
    second = sample(spans, feature_stations=[0.1, 0.73, 0.1])
    assert first == second
    assert json.dumps(first.to_dict(), sort_keys=True, allow_nan=False) == json.dumps(
        second.to_dict(),
        sort_keys=True,
        allow_nan=False,
    )
    assert all(
        a.station < b.station for a, b in zip(first.samples, first.samples[1:], strict=False)
    )
    assert sample(spans, 0.02).evidence.input_sha256 != first.evidence.input_sha256


def test_catmull_conversion_matches_uniform_formula_before_clamping():
    """The converter agrees numerically with the old algebra for valid profiles."""
    rows = [row(0, 0, 1, 0.5, 0.5), row(1, 1, 0, 1, 1), row(2, 0, 1, 0.8, 0.7)]
    spans = catmull_rom_spans(rows)
    for i, span in enumerate(spans):
        a, b, c, d = rows[max(0, i - 1)], rows[i], rows[i + 1], rows[min(len(rows) - 1, i + 2)]
        for step in range(11):
            t = step / 10
            expected = [
                0.5
                * (
                    2 * bv
                    + (-av + cv) * t
                    + (2 * av - 5 * bv + 4 * cv - dv) * t * t
                    + (-av + 3 * bv - 3 * cv + dv) * t * t * t
                )
                for av, bv, cv, dv in zip(a, b, c, d, strict=True)
            ]
            actual = exact_evaluate(span, Fraction(i) + Fraction(step, 10))
            assert tuple(float(v) for v in actual) == pytest.approx(expected, abs=1e-14)


def test_nonpositive_catmull_profile_handles_are_not_silently_clamped():
    """A rejected cubic profile can be replaced only by explicit caller intent."""
    rows = [row(0, width=10), row(1, width=0.01), row(2, width=0.01)]
    with pytest.raises(SamplingError, match="positive"):
        catmull_rom_spans(rows)
    result = sample(catmull_rom_spans(rows, profile_mode="linear"))
    assert all(s.width > 0 for s in result.samples)


@pytest.mark.parametrize(
    "bad", [True, False, None, "1", math.nan, math.inf, -math.inf, 10**1000, 1e7]
)
def test_bad_numeric_controls_fail_closed(bad):
    """Invalid types, nonfinite values, overflow and range violations are rejected."""
    controls = [list(row(i)) for i in range(4)]
    controls[1][0] = bad
    with pytest.raises(SamplingError):
        sample([curve(controls)])


@pytest.mark.parametrize("bad", [0, -1, True, None, math.nan, math.inf, 10**1000])
def test_bad_tolerances_fail_closed(bad):
    """An invalid tolerance cannot be interpreted as a permissive default."""
    with pytest.raises(SamplingError):
        sample([curve()], bad)


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_positive_profile_control_envelope(bad):
    """Zero and negative dimensions are not repaired or accepted."""
    controls = [row(0), row(1, width=bad), row(2), row(3)]
    with pytest.raises(SamplingError):
        sample([curve(controls)])


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"max_samples": 2}, "max_samples"),
        ({"max_depth": 0}, "max_depth"),
        ({"max_evaluations": 1}, "max_evaluations"),
    ],
)
def test_budget_exhaustion_never_returns_partial_success(options, reason):
    """Each independent finite budget fails visibly before returning a result."""
    with pytest.raises(SamplingError, match=reason):
        sample([curve()], **options)


@pytest.mark.parametrize(
    "options",
    [
        {"max_samples": MAX_SAMPLES + 1},
        {"max_depth": MAX_DEPTH + 1},
        {"max_evaluations": MAX_EVALUATIONS + 1},
        {"max_samples": True},
        {"max_depth": 0.5},
        {"max_evaluations": 0},
    ],
)
def test_hard_limits_cannot_be_disabled(options):
    """Finite envelope controls are strict integers with nonbypassable maxima."""
    with pytest.raises(SamplingError):
        sample([curve()], **options)


def test_features_are_validated_before_sampling():
    """Out-of-range and excessive required stations are refused."""
    for features in ([-0.01], [1.01], [math.nan], [True], [0.1] * (MAX_FEATURES + 1)):
        with pytest.raises(SamplingError):
            sample([curve()], feature_stations=features)
    with pytest.raises(SamplingError, match="required stations"):
        sample([curve()], feature_stations=[0.5], max_samples=2)


def test_invalid_sequence_and_join_shapes_are_rejected():
    """Unbounded iterators, malformed rows, gaps and C0 mismatches fail closed."""
    for spans in (
        iter([curve()]),
        [curve()] * (MAX_SPANS + 1),
        [],
        [curve(start=1, end=1)],
        [curve(), curve(start=2, end=3)],
        [curve(), curve(start=1, end=2)],
        [CubicSpan(0, 1, [row(0)])],
    ):
        with pytest.raises(SamplingError):
            sample(spans)
    with pytest.raises(SamplingError):
        catmull_rom_spans([row(0), (1, 2)])
    with pytest.raises(SamplingError):
        catmull_rom_spans([row(0), row(1)], profile_mode="unknown")
    with pytest.raises(SamplingError):
        catmull_rom_spans([row(0), row(1), row(2)], corner_indices=[0])


def test_adjacent_float_stations_fail_when_refinement_is_needed():
    """An unrepresentable midpoint cannot create duplicate parameter stations."""
    with pytest.raises(SamplingError, match="parameter resolution"):
        sample([curve(start=1.0, end=math.nextafter(1.0, math.inf))])


def test_endpoint_roundoff_is_included_in_tolerance():
    """Exact evaluation at an inserted station may not round inside tiny limits."""
    spans = [curve((row(0.1), row(0.2), row(0.3), row(0.4)))]
    with pytest.raises(SamplingError):
        sample(spans, 1e-30, feature_stations=[0.37], max_depth=8)
    result = sample(spans, 1e-12, feature_stations=[0.37])
    assert result.evidence.max_center_error_bound > 0
    assert_probes_bounded(spans, result)


def test_tiny_curve_bounds_survive_squared_underflow():
    """Reporting preserves a nonzero bound when squared errors underflow float."""
    tiny = 1e-200
    spans = [curve((row(0), row(tiny, tiny), row(2 * tiny, -tiny), row(3 * tiny)))]
    result = sample(spans, 1e-199)
    assert 0 < result.evidence.max_center_error_bound < 1e-199
    assert_probes_bounded(spans, result)


def test_random_3d_curves_and_profiles_against_independent_rational_probes():
    """A seeded family checks all dimensions across irregular mandatory splits."""
    rng = random.Random(1729)
    for _ in range(12):
        controls = tuple(
            row(
                *(rng.uniform(-3, 3) for _ in range(3)),
                width=rng.uniform(0.1, 2),
                height=rng.uniform(0.1, 2),
            )
            for _ in range(4)
        )
        spans = [curve(controls, start=-0.3, end=0.7)]
        result = sample(spans, 0.02, feature_stations=[0.13, 0.271])
        assert result.evidence.max_center_error_bound <= 0.02
        assert result.evidence.max_width_error_bound <= 0.02
        assert result.evidence.max_height_error_bound <= 0.02
        assert_probes_bounded(spans, result, 19)


def test_tighter_tolerance_does_not_reduce_deterministic_dyadic_sample_set():
    """Refining the same exact inputs retains previously accepted boundaries."""
    coarse, fine = sample([curve()], 0.03), sample([curve()], 0.005)
    assert {s.station for s in coarse.samples} <= {s.station for s in fine.samples}
    assert fine.evidence.max_center_error_bound <= coarse.evidence.max_center_error_bound


def test_ring_cost_is_explicitly_topology_specific():
    """The closed-cap count excludes center-fan and other mesh conventions."""
    assert estimated_ring_cost(4, 3) == {
        "vertices": 12,
        "side_triangles": 18,
        "cap_triangles": 2,
        "total_triangles": 20,
    }
    with pytest.raises(SamplingError):
        estimated_ring_cost(4, 2)
