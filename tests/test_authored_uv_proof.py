"""Exact positive-overlap and stored-affine proof tests without Blender dependencies."""

from __future__ import annotations

import math
import random
import struct
from fractions import Fraction

import pytest

from codex_blender_modeler.blender_scripts.portable_authored_uv_proof import (
    UVProofError,
    mapped_uvs,
    prove_authored_uv,
    triangles_positive_area_overlap,
    validate_uv_layout,
)

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
SQUARE_TRIANGLES = [[0, 1, 2], [0, 2, 3]]


def _cross(a, b, c):
    """Use exact rational coordinates for an independent clipping oracle."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _clipping_oracle(first, second):
    """Measure a Sutherland-Hodgman intersection independently of separating axes."""
    polygon = [tuple(map(Fraction, p)) for p in first]
    clip = [tuple(map(Fraction, p)) for p in second]
    if _cross(*clip) < 0:
        clip.reverse()
    for a, b in zip(clip, clip[1:] + clip[:1], strict=True):
        output = []
        for p, q in zip(polygon, polygon[1:] + polygon[:1], strict=True):
            dp, dq = _cross(a, b, p), _cross(a, b, q)
            if (dp >= 0) != (dq >= 0):
                ratio = dp / (dp - dq)
                output.append(tuple(p[i] + ratio * (q[i] - p[i]) for i in (0, 1)))
            if dq >= 0:
                output.append(q)
        polygon = output
        if not polygon:
            return False
    area = sum(
        p[0] * q[1] - p[1] * q[0] for p, q in zip(polygon, polygon[1:] + polygon[:1], strict=True)
    )
    return area != 0


@pytest.mark.parametrize(
    ("first", "second", "overlap"),
    [
        ([[0, 0], [1, 0], [0, 1]], [[1, 0], [1, 1], [0, 1]], False),
        ([[0, 0], [1, 0], [0, 1]], [[1, 0], [2, 0], [2, 1]], False),
        ([[0, 0], [2, 0], [0, 2]], [[0.5, 0], [1.5, 0], [1, -1]], False),
        ([[0, 0], [2, 0], [0, 2]], [[2, 2], [2, 0.5], [0.5, 2]], False),
        ([[0, 0], [1, 0], [0, 1]], [[0, 0], [1, 0], [0, 1]], True),
        ([[0, 0], [1, 0], [0, 1]], [[0, 1], [1, 0], [0, 0]], True),
        ([[0, 0], [2, 0], [0, 2]], [[0.2, 0.2], [0.4, 0.2], [0.2, 0.4]], True),
        ([[0, 0], [2, 0], [0, 2]], [[1, -1], [1, 3], [3, 1]], True),
        ([[0, 0], [1, 0], [0, 1]], [[0, 0], [1, 0], [0.5, 2**-50]], True),
    ],
)
def test_exact_pair_contact_and_overlap(first, second, overlap):
    """Allow boundary contact, and reject positive intersections regardless of winding."""
    assert triangles_positive_area_overlap(first, second) is overlap
    assert triangles_positive_area_overlap(second, first) is overlap
    assert _clipping_oracle(first, second) is overlap


def test_small_random_pairs_match_independent_rational_clipping():
    """Check deterministic random pairs against a different exact geometric algorithm."""
    rng = random.Random(1729)
    checked = 0
    while checked < 400:
        first = [[rng.randint(-10, 10) / 4, rng.randint(-10, 10) / 4] for _ in range(3)]
        second = [[rng.randint(-10, 10) / 4, rng.randint(-10, 10) / 4] for _ in range(3)]
        if _cross(*first) == 0 or _cross(*second) == 0:
            continue
        expected = _clipping_oracle(first, second)
        assert triangles_positive_area_overlap(first, second) is expected
        checked += 1


def test_layout_proof_checks_adjacent_shared_edge_overlap():
    """Shared loop indices do not exempt two triangles folded onto the same UV side."""
    with pytest.raises(UVProofError, match="Positive-area"):
        validate_uv_layout([[0, 0], [2, 0], [0, 2], [1, 1]], [[0, 1, 2], [0, 1, 3]])


def test_source_and_target_are_measured_with_exact_float32_reconstruction():
    """Reconstruction retains topology, boundaries and orientation in stored coordinates."""
    bounds = [1 / 3, 1 / 7, 2 / 3, 4 / 7]
    actual = mapped_uvs(SQUARE, bounds)
    report = prove_authored_uv(SQUARE, SQUARE_TRIANGLES, bounds, actual)
    assert report["source"]["complete"] and report["target"]["complete"]
    assert report["source"]["overlap_pair_count"] == 0
    assert report["target"]["degenerate_triangle_count"] == 0
    assert report["orientation_preserved"]
    assert (
        report["source"]["topology_fingerprint_sha256"]
        == report["target"]["topology_fingerprint_sha256"]
    )
    for u, v in actual:
        assert bounds[0] <= u <= bounds[2] and bounds[1] <= v <= bounds[3]
        assert struct.unpack(">f", struct.pack(">f", u))[0] == u
        assert struct.unpack(">f", struct.pack(">f", v))[0] == v
    assert report["mapping_target_bounds"][0] >= bounds[0]
    assert report["mapping_target_bounds"][2] <= bounds[2]


def test_non_normalized_authored_domain_is_affine_not_clamped_or_wrapped():
    """Source repeats spanning several UV cells keep their complete source extent."""
    uv = [[-2, -4], [4, -4], [4, 8], [-2, 8]]
    report = prove_authored_uv(uv, SQUARE_TRIANGLES, [0.25, 0.25, 0.75, 0.75])
    assert report["source"]["uv_minimum"] == [-2, -4]
    assert report["target_uvs"] == [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]


def test_planned_reconstruction_does_not_claim_native_stored_observation():
    """Preflight calculation remains distinct from an actually supplied UV snapshot."""
    planned = prove_authored_uv(SQUARE, SQUARE_TRIANGLES, [0, 0, 1, 1])
    assert planned["actual_target_matches_reconstruction"] is False
    measured = prove_authored_uv(
        SQUARE, SQUARE_TRIANGLES, [0, 0, 1, 1], planned["target_uvs"]
    )
    assert measured["actual_target_matches_reconstruction"] is True


def test_exact_positive_tiny_triangle_has_no_area_epsilon():
    """Subnormal determinant arithmetic falls back to exact nonzero orientation."""
    uv = [[0, 0], [1e-200, 0], [0, 1e-200]]
    assert validate_uv_layout(uv, [[0, 1, 2]])["degenerate_triangle_count"] == 0
    assert triangles_positive_area_overlap(uv, uv)


def test_float32_collapse_is_a_failure_after_source_passes():
    """A tiny real triangle may collapse under the actual target-storage precision."""
    uv = [[0, 0], [2**-26, 0], [0, 2**-26], [0.75, 0.75], [1, 0.75], [0.75, 1]]
    triangles = [[0, 1, 2], [3, 4, 5]]
    validate_uv_layout(uv, triangles)
    with pytest.raises(UVProofError, match="zero-area"):
        prove_authored_uv(uv, triangles, [0.5, 0.5, 0.75, 0.75])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "0.5"])
def test_nonfinite_or_coerced_coordinates_fail(value):
    """Malformed coordinates are rejected before predicates or hashing."""
    with pytest.raises(UVProofError, match="finite|numeric"):
        validate_uv_layout([[value, 0], [1, 0], [0, 1]], [[0, 1, 2]])


@pytest.mark.parametrize("triangles", [[[0, 1, 1]], [[0, 1, 3]], [[0, True, 2]], [[0, 1]], []])
def test_invalid_triangle_topology_fails(triangles):
    """Malformed indices or missing triangulation cannot produce a completed proof."""
    with pytest.raises(UVProofError):
        validate_uv_layout([[0, 0], [1, 0], [0, 1]], triangles)


def test_unreferenced_loop_and_exact_degenerate_triangle_fail():
    """All loops and every exact triangle are required, with no adjacency exclusions."""
    with pytest.raises(UVProofError, match="not every loop"):
        validate_uv_layout(SQUARE, [[0, 1, 2]])
    with pytest.raises(UVProofError, match="zero-area"):
        validate_uv_layout([[0, 0], [1, 1], [2, 2]], [[0, 1, 2]])


@pytest.mark.parametrize(
    "limit",
    [{"maximum_triangles": 1}, {"maximum_candidate_pairs": 0}, {"maximum_broadphase_pairs": 0}],
)
def test_resource_limits_fail_closed(limit):
    """Neither coarse nor fine candidate exhaustion is mistaken for zero overlap."""
    with pytest.raises(UVProofError, match="resource limit"):
        validate_uv_layout(SQUARE, SQUARE_TRIANGLES, **limit)


def test_proof_fingerprints_preserve_order_and_full_coordinate_bits():
    """Sub-decimal changes and triangle reordering alter their respective exact hashes."""
    original = validate_uv_layout(SQUARE, SQUARE_TRIANGLES)
    changed = [list(p) for p in SQUARE]
    changed[0][0] = math.nextafter(0, -1)
    revised = validate_uv_layout(changed, SQUARE_TRIANGLES)
    reordered = validate_uv_layout(SQUARE, list(reversed(SQUARE_TRIANGLES)))
    assert original["uv_fingerprint_sha256"] != revised["uv_fingerprint_sha256"]
    assert original["topology_fingerprint_sha256"] != reordered["topology_fingerprint_sha256"]


def test_stored_uv_tampering_fails_even_when_shape_is_still_valid():
    """Native output must equal exact reconstructed float32 values, not a tolerance."""
    target = mapped_uvs(SQUARE, [0.25, 0.25, 0.75, 0.75])
    target[0][0] = math.nextafter(target[0][0], math.inf)
    with pytest.raises(UVProofError, match="reconstruction"):
        prove_authored_uv(SQUARE, SQUARE_TRIANGLES, [0.25, 0.25, 0.75, 0.75], target)


@pytest.mark.parametrize("bounds", [[0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, math.inf, 1]])
def test_invalid_target_intervals_fail(bounds):
    """Only finite positive normalized tile intervals are eligible for reuse."""
    with pytest.raises(UVProofError):
        mapped_uvs(SQUARE, bounds)
