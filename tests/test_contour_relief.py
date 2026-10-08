"""Pure geometry tests for bounded contour shells, caps, and structural ribbons."""

from __future__ import annotations

import math
from collections import Counter

import pytest

from codex_blender_modeler.structural_geometry.contour_relief import (
    build_contour_prism,
    build_contour_relief_shell,
    build_relief_ribbon,
)
from codex_blender_modeler.structural_geometry.models import StructuralGeometryCandidate

CONTOURS = {
    "panel": [(-2.0, -1.0), (2.0, -1.0), (2.0, 1.0), (-2.0, 1.0)],
    "concave_bracket": [(0.0, 0.0), (3.0, 0.0), (3.0, 1.0), (1.0, 1.0), (1.0, 3.0), (0.0, 3.0)],
    "forked_rail": [
        (0.0, 0.0),
        (4.0, 0.0),
        (4.0, 3.0),
        (3.0, 3.0),
        (3.0, 1.0),
        (1.0, 1.0),
        (1.0, 3.0),
        (0.0, 3.0),
    ],
    "near_collinear": [(-2.0, -1.0), (0.0, -1.0 + 1.0e-14), (2.0, -1.0), (2.0, 1.0), (-2.0, 1.0)],
    "collinear_anchors": [
        (-2.0, -1.0),
        (0.0, -1.0),
        (2.0, -1.0),
        (2.0, 1.0),
        (0.0, 1.0),
        (-2.0, 1.0),
    ],
    "organic_plate": [
        (
            math.cos(i * math.tau / 24) * (1.0 + 0.13 * math.cos(i * math.pi / 4)),
            math.sin(i * math.tau / 24),
        )
        for i in range(24)
    ],
}


def _shell(points, **kwargs):
    """Author the same normalized bevel across independent shape fixtures."""
    values = dict(depth=0.4, bevel_width=0.06, bevel_depth=0.09, max_chord_error=0.004)
    values.update(kwargs)
    return build_contour_relief_shell(points, **values)


def _signed_volume(shell):
    """Measure oriented closed volume independently of the source validator."""
    value = 0.0
    for indices in shell.triangles:
        a, b, c = [shell.vertices[index] for index in indices]
        value += (
            a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0])
        ) / 6.0
    return value


@pytest.mark.parametrize("name", list(CONTOURS))
@pytest.mark.parametrize("reverse", [False, True])
def test_shell_preserves_boundary_and_closes_concave_caps(name, reverse):
    """Retain every boundary anchor, positive volume and exactly two faces per edge."""
    points = CONTOURS[name][::-1] if reverse else CONTOURS[name]
    shell = _shell(points)
    count = len(points)
    assert [(v[0], v[2]) for v in shell.vertices[:count]] == points
    assert [(v[0], v[2]) for v in shell.vertices[count : 2 * count]] == points
    edges = Counter(
        tuple(sorted((face[i], face[(i + 1) % 3]))) for face in shell.triangles for i in range(3)
    )
    assert set(edges.values()) == {2}
    assert _signed_volume(shell) > 0.0
    assert len(shell.vertices) - len(edges) + len(shell.triangles) == 2
    assert len(shell.triangles) < 2000
    assert shell.model_dump_json() == _shell(points).model_dump_json()
    assert (
        StructuralGeometryCandidate(semantic_id="fixture.shell", geometry=shell).geometry == shell
    )
    # Every front cap triangle covers the original concave inset, with -Y outward normal.
    for face in shell.triangles[: count - 2]:
        a, b, c = [shell.vertices[index] for index in face]
        assert a[1] == pytest.approx(-0.2)
        assert (b[0] - a[0]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[0] - a[0]) > 0


@pytest.mark.parametrize("name", list(CONTOURS))
def test_prism_volume_is_polygon_area_times_depth(name):
    """Check exact concave planar cap coverage using independently known prism volume."""
    points = CONTOURS[name]
    shell = build_contour_prism(points, depth=0.4)
    area = (
        abs(
            sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, [*points[1:], points[0]], strict=True)
            )
        )
        / 2.0
    )
    assert _signed_volume(shell) == pytest.approx(area * 0.4)
    assert len(shell.triangles) == 4 * len(points) - 4


def test_finer_error_keeps_attachment_and_seam_anchors():
    """Quality settings refine bevels while preserving exact first-ring indices and bounds."""
    points = CONTOURS["concave_bracket"]
    coarse = _shell(points, max_chord_error=0.012)
    fine = _shell(points, max_chord_error=0.002)
    assert coarse.vertices[: 2 * len(points)] == fine.vertices[: 2 * len(points)]
    assert len(fine.triangles) > len(coarse.triangles)
    for axis in range(3):
        assert min(p[axis] for p in coarse.vertices) == min(p[axis] for p in fine.vertices)
        assert max(p[axis] for p in coarse.vertices) == max(p[axis] for p in fine.vertices)


def test_measured_bevel_chords_obey_requested_metric_error():
    """Dense independent ellipse samples verify the requested chord approximation error."""
    shell = _shell(CONTOURS["panel"])
    count = len(CONTOURS["panel"])
    segments = len(shell.vertices) // (2 * count) - 1
    curve = [shell.vertices[0], *[shell.vertices[2 * count + k * count] for k in range(segments)]]
    error = 0.0
    for step in range(1001):
        angle = step * math.pi / 2000
        point = (
            -2.0 + 0.06 * (1.0 - math.cos(angle)),
            -0.11 - 0.09 * math.sin(angle),
            -1.0 + 0.06 * (1.0 - math.cos(angle)),
        )
        segment = min(segments - 1, int(step * segments / 1000))
        a, b = curve[segment], curve[segment + 1]
        delta = [b[k] - a[k] for k in range(3)]
        fraction = max(
            0,
            min(
                1,
                sum((point[k] - a[k]) * delta[k] for k in range(3))
                / sum(value * value for value in delta),
            ),
        )
        error = max(error, math.dist(point, [a[k] + fraction * delta[k] for k in range(3)]))
    assert error <= 0.004


@pytest.mark.parametrize("scale", [0.001, 1.0, 1000.0])
def test_scale_aware_offset_topology(scale):
    """Use relative geometric predicates without changing topology across meter scales."""
    points = [(x * scale + 17.0, z * scale - 23.0) for x, z in CONTOURS["concave_bracket"]]
    shell = _shell(
        points,
        depth=0.4 * scale,
        bevel_width=0.06 * scale,
        bevel_depth=0.09 * scale,
        max_chord_error=0.004 * scale,
    )
    baseline = _shell(CONTOURS["concave_bracket"])
    assert shell.triangles == baseline.triangles
    assert _signed_volume(shell) > 0


def test_explicit_inset_and_narrow_tip_widths():
    """Explicit reduced tip widths preserve thin silhouette points without auto-clamping."""
    points = [(0.0, 0.0), (3.0, 0.3), (0.0, 1.0)]
    with pytest.raises(ValueError, match="inside|inverts|intersects|winding"):
        _shell(points, bevel_width=0.5)
    shell = _shell(points, bevel_width=[0.05, 0.008, 0.05])
    count = len(points)
    segments = len(shell.vertices) // (2 * count) - 1
    inset = [(p[0], p[2]) for p in shell.vertices[(segments + 1) * count : (segments + 2) * count]]
    assert shell == _shell(points, inset_points=inset)


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (1, 1)],
        [(0, 0), (1, 0), (2, 0)],
        [(0, 0), (1, 1), (0, 1), (1, 0)],
        [(0, 0), (1, 0), (1, 1), (0, 0)],
        [(0, 0), (1, 0), (1, 1), (1, 0), (0, 1)],
        [(0, 0), (math.inf, 0), (0, 1)],
        [(0, 0), (True, 0), (0, 1)],
    ],
)
def test_invalid_contours_fail_closed(points):
    """Reject underdefined, nonfinite, zero-area, crossing and pinched contours."""
    with pytest.raises(ValueError):
        _shell(points)


@pytest.mark.parametrize(
    "values",
    [
        {"depth": 0},
        {"depth": math.nan},
        {"center_y": math.inf},
        {"bevel_depth": 0.2},
        {"bevel_depth": -0.1},
        {"bevel_width": -0.1},
        {"bevel_width": [0.1]},
        {"max_chord_error": 0},
        {"max_chord_error": 1e-30},
        {"max_chord_error": True},
        {"inset_points": [(0, 0), (1, 0), (0, 1)]},
        {"inset_points": [(0, 0), (3, 0), (3, 1), (0, 1)]},
        {"inset_points": [(-1.9, -0.9), (-1.9, 0.9), (1.9, 0.9), (1.9, -0.9)]},
    ],
)
def test_invalid_parameters_or_offsets_fail_closed(values):
    """Reject invalid depth, tolerance, cardinality and explicit inset correspondence."""
    with pytest.raises(ValueError):
        _shell(CONTOURS["panel"], **values)


def test_variable_width_ribbon_is_bounded_closed_geometry():
    """Author a curved structural rail with retained widths and no interior sampling grid."""
    points = [(0.0, 0.0), (1.0, 0.2), (2.0, 0.2), (3.0, 0.0)]
    shell = build_relief_ribbon(
        points,
        width=[0.15, 0.25, 0.2, 0.12],
        depth=0.12,
        bevel_width=0.015,
        bevel_depth=0.025,
        max_chord_error=0.002,
        center_y=-0.3,
    )
    assert _signed_volume(shell) > 0
    assert len(shell.triangles) < 500
    assert min(p[1] for p in shell.vertices) == pytest.approx(-0.36)
    assert max(p[1] for p in shell.vertices) == pytest.approx(-0.24)


@pytest.mark.parametrize(
    "points,width",
    [
        ([(0, 0)], 0.1),
        ([(0, 0), (0, 0)], 0.1),
        ([(0, 0), (1, 0), (0, 0)], 0.1),
        ([(0, 0), (1, 0)], [0.1]),
        ([(0, 0), (1, 1), (0, 1), (1, 0)], 0.2),
    ],
)
def test_ribbon_rejects_invalid_or_crossing_routes(points, width):
    """Refuse zero edges, reversing tips, mismatched widths and overlapping ribbons."""
    with pytest.raises(ValueError):
        build_relief_ribbon(
            points,
            width=width,
            depth=0.1,
            bevel_width=0.01,
            bevel_depth=0.02,
            max_chord_error=0.002,
        )


def test_oversized_contours_refuse_before_quadratic_work(monkeypatch):
    """Large or repeated input arrays must fail before geometric intersection work."""
    import codex_blender_modeler.structural_geometry.contour_relief as module

    def unexpected_predicates(*args):
        """Fail the test if oversized input reaches a quadratic geometry pass."""
        pytest.fail("oversized contour reached geometric predicates")

    monkeypatch.setattr(module, "_simple", unexpected_predicates)
    with pytest.raises(ValueError, match="control points"):
        _shell([(0.0, 0.0)] * 100000)
    with pytest.raises(ValueError, match="control points"):
        build_relief_ribbon(
            [(0.0, 0.0)] * 100000,
            width=0.1,
            depth=0.1,
            bevel_width=0.01,
            bevel_depth=0.02,
            max_chord_error=0.002,
        )


def test_cap_predicate_exhaustion_is_visible(monkeypatch):
    """Bounded triangulation rejects exhaustion without returning a partial shell."""
    import codex_blender_modeler.structural_geometry.contour_relief as module

    monkeypatch.setattr(module, "_MAX_CAP_POINT_TESTS", 1)
    with pytest.raises(ValueError, match="finite predicate budget"):
        build_contour_prism(CONTOURS["forked_rail"], depth=0.4)


@pytest.mark.parametrize("bad", [None, [], [1.0], [1.0, 2.0, 3.0]])
def test_contours_and_ribbons_require_exact_point_dimensions(bad):
    """Reject malformed controls instead of silently dropping depth or extra coordinates."""
    with pytest.raises(ValueError, match="exactly two"):
        build_contour_prism([(0.0, 0.0), (1.0, 0.0), bad], depth=0.1)
    with pytest.raises(ValueError, match="exactly two"):
        build_relief_ribbon(
            [(0.0, 0.0), bad],
            width=0.1,
            depth=0.1,
            bevel_width=0.01,
            bevel_depth=0.02,
            max_chord_error=0.002,
        )


def test_coplanar_offset_bands_do_not_spend_rings_on_tangent_shortening():
    """A plain rectangular panel needs curvature rings, not tangential reparameterization."""
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    shell = _shell(points, depth=0.41, bevel_depth=0.071, bevel_width=0.06, max_chord_error=0.0015)
    assert len(shell.triangles) <= 100


def test_nearly_antiparallel_band_keeps_full_bound_and_invalid_annulus_refuses():
    """Adverse edge reversal retains the conservative bound instead of claiming coplanarity."""
    from codex_blender_modeler.structural_geometry.contour_relief import _band_twist_bound

    outer = [(0.0, 0.0), (1.0, 0.0)]
    inset = [(1.0, 0.01), (0.0, 0.02)]
    assert _band_twist_bound(outer, inset) == pytest.approx(math.hypot(2.0, 0.01))
    with pytest.raises(ValueError):
        _shell(CONTOURS["panel"], inset_points=[(1.8, -0.9), (-1.8, -0.8), (1.8, 0.9), (-1.8, 0.9)])
