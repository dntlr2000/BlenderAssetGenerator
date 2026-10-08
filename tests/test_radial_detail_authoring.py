"""Tests preventing ignored authored knots and unbounded Gaussian tails."""

import math

import pytest

from codex_blender_modeler.radial_detail_authoring import (
    MAX_KNOTS,
    MAX_RADIAL_SAMPLES,
    RadialProfile,
    validate_radial_profile,
)


def test_authored_knots_define_shape_instead_of_a_gaussian():
    """A valley and second peak must survive exactly, excluding Gaussian substitution."""
    profile = RadialProfile(((0, 1), (0.25, 0.1), (0.5, 0.8), (1, 0)))
    assert profile.heights_at([0, 0.25, 0.5, 1, 2]) == (1, 0.1, 0.8, 0, 0)
    assert profile.height_at(0.5) > profile.height_at(0.25)
    other = RadialProfile(((0, 1), (0.25, 0.9), (0.5, 0.2), (1, 0)))
    assert other.height_at(0.25) != profile.height_at(0.25)
    assert profile.height_at(2) == 0.0
    assert math.exp(-2 * 2) > 0.0


def test_smoothstep_values_distinguish_linear_interpolation():
    """Quarter and three-quarter values obey the cubic smoothstep polynomial."""
    profile = RadialProfile(((0, 2), (2, 0)))
    assert profile.heights_at([0, 0.5, 1, 1.5, 2]) == (2, 1.6875, 1, 0.3125, 0)


def test_endpoint_continuity_and_zero_slope():
    """Endpoint and knot changes shrink quadratically when the offset halves."""
    profile = RadialProfile(((0, 1), (0.5, 0.3), (1, 0)))
    for knot, height in profile.knots:
        for direction in (-1, 1):
            near, nearer = knot + direction * 1e-4, knot + direction * 5e-5
            if near < 0:
                continue
            first = abs(profile.height_at(near) - height)
            second = abs(profile.height_at(nearer) - height)
            assert second <= first * 0.251 + 1e-15
    assert profile.height_at(math.nextafter(1, math.inf)) == 0
    assert profile.height_at(1e6) == 0


def test_annular_support_has_zero_inner_and_outer_tails():
    """An explicit positive inner support radius joins zero continuously."""
    profile = RadialProfile(((1, 0), (2, 1), (3, 0)))
    assert profile.heights_at([0, 0.5, 1, 2, 3, 4]) == (0, 0, 0, 1, 0, 0)


def test_signed_height_profiles_and_flat_sections_are_retained():
    """Grooves and plateaus are authored data, never rectified or normalized."""
    profile = RadialProfile(((0, -1), (0.25, -1), (0.75, -0.5), (1, 0)))
    assert profile.height_at(0.125) == -1
    assert profile.height_at(0.5) == -0.75
    assert profile.height_at(1) == 0


@pytest.mark.parametrize(
    "knots",
    [
        [],
        [(0, 0)],
        [(0, 1)] * (MAX_KNOTS + 1),
        [(0, 1), (0, 0)],
        [(1, 1), (0, 0)],
        [(-1, 1), (1, 0)],
        [(0, 1), (1, 0.01)],
        [(1, 1), (2, 0)],
        [(0, 1, 2), (1, 0)],
        [(0, 1), (math.nan, 0)],
        [(0, math.inf), (1, 0)],
        [(False, 1), (1, 0)],
        [(0, True), (1, 0)],
        [(0, 1), (10**1000, 0)],
        [(0, 1e7), (1, 0)],
    ],
)
def test_malformed_or_discontinuous_knots_are_rejected(knots):
    """Invalid source data never falls back to an unrelated radial function."""
    with pytest.raises(ValueError):
        RadialProfile(knots)


@pytest.mark.parametrize("radius", [-0.1, True, None, "1", math.nan, math.inf, 10**1000, 1e7])
def test_invalid_sample_radius_is_rejected(radius):
    """Evaluation rejects malformed distances instead of returning misleading zero."""
    with pytest.raises(ValueError):
        RadialProfile(((0, 1), (1, 0))).height_at(radius)


def test_source_is_copied_and_batches_are_bounded():
    """Mutating a supplied list cannot change a validated reusable evaluator."""
    knots = [[0, 1], [1, 0]]
    profile = RadialProfile(knots)
    knots[0][1] = 100
    assert profile.height_at(0) == 1
    assert validate_radial_profile([[0, 1], [1, 0]]) == ((0.0, 1.0), (1.0, 0.0))
    with pytest.raises(ValueError):
        RadialProfile(iter(knots))
    with pytest.raises(ValueError):
        profile.heights_at(iter([0, 1]))
    with pytest.raises(ValueError):
        profile.heights_at([0] * (MAX_RADIAL_SAMPLES + 1))
    assert profile.heights_at([]) == ()
