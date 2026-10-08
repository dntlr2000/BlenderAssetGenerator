"""Explicit section preservation, exact embedding and fail-closed host tests."""

from __future__ import annotations

import math
from collections import Counter

import pytest

from codex_blender_modeler.blender_scripts import self_intersection_runtime as exact
from codex_blender_modeler.structural_geometry import profiled_relief as module
from codex_blender_modeler.structural_geometry.mesh_math import build_loft_mesh
from codex_blender_modeler.structural_geometry.models import LoftGeometry, LoftSection
from codex_blender_modeler.structural_geometry.profiled_relief import build_profiled_relief_ribbon

PROFILES = {
    "ridge": [(-0.5, 0.5), (0.0, -0.5), (0.5, 0.5)],
    "chamfer": [(-0.5, 0.5), (-0.5, -0.2), (-0.2, -0.5), (0.2, -0.5), (0.5, -0.2), (0.5, 0.5)],
    "trough": [(-0.5, 0.5), (-0.5, -0.5), (0.0, -0.1), (0.5, -0.5), (0.5, 0.5)],
}
ROUTE = [(0.0, 0.0), (0.6, 0.2), (1.2, 0.25), (2.0, 0.0)]


def make_ribbon(name="ridge", **kwargs):
    """Return an explicitly tapered, depth-conforming fixture with a known profile."""
    values = dict(
        points=ROUTE,
        profile=PROFILES[name],
        width=[0.08, 0.16, 0.12, 0.04],
        depth=[0.04, 0.08, 0.02, 0.01],
        center_y=[0.0, -0.03, -0.08, 0.02],
    )
    values.update(kwargs)
    return build_profiled_relief_ribbon(**values)


def signed_volume(shell):
    """Compute signed volume around a local anchor to avoid translation cancellation."""
    origin = shell.vertices[0]
    terms = []
    for face in shell.triangles:
        a, b, c = [tuple(shell.vertices[i][k] - origin[k] for k in range(3)) for i in face]
        terms.append(
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        )
    return math.fsum(terms) / 6


@pytest.mark.parametrize("name", PROFILES)
@pytest.mark.parametrize("reverse", [False, True])
def test_explicit_profile_taper_and_closed_embedding(name, reverse):
    """Retain exact authored station section/Y values with deterministic closed topology."""
    profile = PROFILES[name][::-1] if reverse else PROFILES[name]
    shell = make_ribbon(profile=profile)
    n, p = len(ROUTE), len(profile)
    assert len(shell.vertices) == n * p
    assert len(shell.triangles) == 2 * n * p - 4
    assert signed_volume(shell) > 0
    edges = Counter(
        tuple(sorted((face[i], face[(i + 1) % 3]))) for face in shell.triangles for i in range(3)
    )
    assert set(edges.values()) == {2}
    assert len(shell.vertices) - len(edges) + len(shell.triangles) == 2
    for i, (depth, center) in enumerate(
        zip([0.04, 0.08, 0.02, 0.01], [0.0, -0.03, -0.08, 0.02], strict=True)
    ):
        assert [v[1] for v in shell.vertices[i * p : (i + 1) * p]] == [
            center + y * depth for _, y in profile
        ]
    assert make_ribbon(profile=profile).model_dump_json() == shell.model_dump_json()
    proof = exact.bounded_self_intersection(
        shell.vertices, shell.triangles, max_triangles=4092, max_pair_tests=32768
    )
    assert proof["availability"] == "available" and proof["passed"]


@pytest.mark.parametrize("scale", [0.001, 1.0, 1000.0])
def test_normalized_predicates_retain_topology_across_scales(scale):
    """Use relative bounds while respecting the unchanged shell area floor."""
    values = dict(
        points=[(x * scale + 12, z * scale - 6) for x, z in ROUTE],
        width=[v * scale for v in [0.08, 0.16, 0.12, 0.04]],
        depth=[v * scale for v in [0.04, 0.08, 0.02, 0.01]],
        center_y=[v * scale + 3 for v in [0.0, -0.03, -0.08, 0.02]],
    )
    shell = make_ribbon("trough", **values)
    assert shell.triangles == make_ribbon("trough").triangles
    assert signed_volume(shell) == pytest.approx(signed_volume(make_ribbon("trough")) * scale**3)


def test_straight_ridge_has_analytic_volume_and_exact_end_profile():
    """Check absolute dimension semantics against triangle area times path length."""
    shell = build_profiled_relief_ribbon(
        [(0, 0), (3, 0)], profile=PROFILES["ridge"], width=0.2, depth=0.1
    )
    assert signed_volume(shell) == pytest.approx(0.5 * 0.2 * 0.1 * 3)
    assert len(shell.triangles) == 8
    assert shell.vertices[:3] == [(0.0, 0.05, -0.1), (0.0, -0.05, 0.0), (0.0, 0.05, 0.1)]


@pytest.mark.parametrize(
    "values",
    [
        {"points": [(0, 0)]},
        {"points": [(0, 0)] * 129},
        {"points": [(0, 0), (0, 0)]},
        {"points": [(0, 0), (1, 0), (0.001, 0.001)]},
        {"points": [(0, 0), (1, 1), (0, 1), (1, 0)]},
        {"points": [(0, 0), (1, 0), (1, 0.02), (0, 0.02)]},
        {"points": [(0, 0), (1, 0), (1, 1)], "width": [0.2, 4, 0.2]},
        {"points": [(0, 0), (1, float("inf"))]},
        {"points": [(0, 0), (1, True)]},
        {"width": 0},
        {"depth": -1},
        {"width": True},
        {"depth": "0.01"},
        {"width": [0.1]},
        {"width": 1e-20},
        {"depth": float("nan")},
        {"center_y": [0, 0]},
        {"center_y": float("inf")},
        {"center_y": 1000001},
        {"profile": [(-0.5, -0.5), (0.5, 0.5), (-0.5, 0.5), (0.5, -0.5)]},
        {"profile": [(-0.5, 0.5), (0, -0.5), (0.5, 0.5), (0, 0.5)]},
        {"profile": [(-0.4, 0.5), (0, -0.5), (0.5, 0.5)]},
        {"profile": PROFILES["ridge"] * 6},
        {"profile": [(0, 0), (0, 1)]},
    ],
)
def test_malformed_degenerate_cusp_fold_and_crossing_inputs_fail_closed(values):
    """Reject unsupported numeric, cardinality, topology and footprint conditions."""
    with pytest.raises(ValueError):
        make_ribbon(**values)


def test_exact_work_budget_exhaustion_fails_closed(monkeypatch):
    """An inconclusive triangle test cannot return an apparently validated shell."""
    monkeypatch.setattr(module, "_MAX_PAIR_TESTS", 1)
    with pytest.raises(ValueError, match="budget"):
        make_ribbon()


@pytest.mark.parametrize(
    "vertices, faces",
    [
        (
            [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, -1, 0), (1, 1, 0), (3, 0, 0)],
            [(0, 1, 2), (3, 4, 5)],
        ),
        (
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0.5, 0, 0), (0.5, -1, 0), (1.5, -1, 0)],
            [(0, 1, 2), (3, 4, 5)],
        ),
        (
            [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0.5, 0, 0), (0.5, 0, 1), (0.5, -1, 1)],
            [(0, 1, 2), (3, 4, 5)],
        ),
    ],
)
def test_actual_triangle_overlap_or_nonindexed_contact_is_rejected(vertices, faces):
    """The host embedding predicate is stricter than independent-boundary contact QA."""
    first, second = exact.prepare_exact_triangles(vertices, faces)
    assert module._improper_contact(first, second)


def test_existing_loft_is_sufficient_for_equal_edge_sparse_gem_sections():
    """Four equal-edge anchors remain sparse across existing closed loft sections."""
    sections = [
        LoftSection(
            points=[(x * radius, y, z * radius) for x, z in [(0, -1), (1, 0), (0, 1), (-1, 0)]],
            closed=True,
        )
        for radius, y in [(0.2, -0.1), (1.0, 0.0), (0.2, 0.1)]
    ]
    recipe = LoftGeometry(sections=sections, correspondence_policy="index")
    result = build_loft_mesh(recipe.model_dump())
    expected = [p for section in sections for p in section.points]
    for actual, anchor in zip(result["vertices"], expected, strict=True):
        assert actual == pytest.approx(anchor)
    assert sum(len(face) - 2 for face in result["faces"]) == 20


def test_existing_loft_does_not_preserve_irregular_equal_count_anchors():
    """Document existing equal-arclength resampling before choosing a faceted recipe."""
    points = [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1)]
    recipe = LoftGeometry(
        sections=[
            LoftSection(points=points, closed=True),
            LoftSection(points=[(x, y + 1, z) for x, y, z in points], closed=True),
        ],
        correspondence_policy="index",
    )
    result = build_loft_mesh(recipe.model_dump())
    assert result["vertices"][:4] != points


def test_float32_coordinate_collapse_fails_closed():
    """Reject otherwise valid doubles when native storage merges profile positions."""
    with pytest.raises(ValueError, match="float32 materialization"):
        build_profiled_relief_ribbon(
            [(900000, 900000), (900001, 900000)], profile=PROFILES["ridge"], width=0.01, depth=0.01
        )


ADVERSARIAL_TAPER = dict(
    points=[(0, 0), (1, -0.15), (2, 0)],
    profile=[(-0.5, 0.5), (-0.5, -0.5), (0, 0.49), (0.5, -0.5), (0.5, 0.5)],
    width=[0.11, 0.49, 0.019],
    depth=[0.095, 0.065, 0.01],
    center_y=[-0.35, -0.8, 0.07],
)


def test_nonfolding_footprint_does_not_hide_triangulated_trough_crossing(monkeypatch):
    """Refuse a real concave/taper crossing that the footprint-only proof cannot see."""
    with pytest.raises(ValueError, match="emitted triangles"):
        build_profiled_relief_ribbon(**ADVERSARIAL_TAPER)
    # Test-only negative control: omit the added proof to inspect its rejected triangles.
    with monkeypatch.context() as context:
        context.setattr(module, "_validate_embedded", lambda shell: None)
        unsafe = build_profiled_relief_ribbon(**ADVERSARIAL_TAPER)
    proof = exact.bounded_self_intersection(
        unsafe.vertices, unsafe.triangles, max_triangles=4092, max_pair_tests=32768
    )
    assert proof["availability"] == "available" and not proof["passed"]
    assert proof["measured_value"] > 0


@pytest.mark.parametrize(
    "values",
    [
        {"points": [{0: 0, 1: 0}, (1, 0)]},
        {"points": [(0, 0), (10**1000, 1)]},
        {"width": 10**1000},
        {"center_y": 10**1000},
    ],
)
def test_nondata_points_and_unrepresentable_numbers_fail_closed(values):
    """Normalize unsupported point containers and huge integer conversion failures."""
    with pytest.raises(ValueError):
        make_ribbon(**values)
