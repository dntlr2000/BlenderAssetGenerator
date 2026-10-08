"""Check exact constant-back eligibility without weakening whole-domain coverage."""

from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import owner_relief as m
from codex_blender_modeler.structural_geometry.constant_back import constant_back_thickness


def surface(points, triangles, depths):
    """Create independently validated exact graph triangles for proof comparisons."""
    vertices = [[*point, depth] for point, depth in zip(points, depths, strict=True)]
    return m.surface(vertices, triangles, ((0, 1, 2), (1, 1, 1)), m.Budget())


SQUARE = [[0, 0], [1, 0], [1, 1], [0, 1]]
FACES = [[0, 1, 2], [0, 2, 3]]


def test_constant_back_matches_general_overlay_with_different_diagonal():
    """Exact domain equality does not depend on the two caps sharing topology."""
    front = surface(SQUARE, FACES, [0, 0.25, 0.5, 0.75])
    back = surface(SQUARE, [[0, 1, 3], [1, 2, 3]], [1] * 4)
    result = constant_back_thickness(front, back, m.Budget())
    cells, gaps = m.overlay([(poly, [pts]) for poly, pts in front], back, m.Budget())
    values = [m.height(p, src[1]) - m.height(p, src[0]) for poly, src in cells for p in poly]
    assert not gaps
    assert result == (min(values), max(values)) == (Q(1, 4), Q(1))


def test_collinear_boundary_subdivision_is_not_a_gap():
    """Exact endpoint cancellation recognizes equal complete boundary segments."""
    front = surface(SQUARE, FACES, [0] * 4)
    points = [[0, 0], [0.5, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]]
    back = surface(points, [[5, 0, 1], [5, 1, 2], [5, 2, 3], [5, 3, 4], [5, 4, 0]], [1] * 6)
    assert constant_back_thickness(front, back, m.Budget()) == (Q(1), Q(1))


def test_nonconstant_back_uses_general_path():
    """Even a tiny actual back-depth change is not approximated as constant."""
    front = surface(SQUARE, FACES, [0] * 4)
    back = surface(SQUARE, FACES, [1, 1, 1, 1 + 2**-40])
    assert constant_back_thickness(front, back, m.Budget()) is None


def test_subpixel_boundary_difference_is_not_ignored():
    """A positive uncovered strip remains a different domain at binary precision."""
    front = surface(SQUARE, FACES, [0] * 4)
    points = [[0, 0], [1 - 2**-45, 0], [1 - 2**-45, 1], [0, 1]]
    back = surface(points, FACES, [1] * 4)
    assert constant_back_thickness(front, back, m.Budget()) is None


def test_equal_area_and_bounds_with_different_domains_are_not_enough():
    """Opposite half-square domains have equal area and bounds but unequal boundaries."""
    front = surface(SQUARE, [[0, 1, 2]], [0] * 4)
    back = surface(SQUARE, [[0, 2, 3]], [1] * 4)
    assert sum(m.area(p) for p, _ in front) == sum(m.area(p) for p, _ in back)
    assert m.bounds(front[0][0]) == m.bounds(back[0][0])
    assert constant_back_thickness(front, back, m.Budget()) is None


def test_hole_boundary_must_match():
    """An equal outer boundary cannot hide a missing interior patch."""
    front = surface(SQUARE, FACES, [0] * 4)
    points = SQUARE + [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
    faces = [[0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]]
    back = surface(points, faces, [1] * 8)
    assert constant_back_thickness(front, back, m.Budget()) is None
    holed_front = surface(points, faces, [0] * 8)
    assert constant_back_thickness(holed_front, back, m.Budget()) == (Q(1), Q(1))


def test_no_reset_of_edge_budget(monkeypatch):
    """Fast-path work consumes the same caller-owned bounded accounting object."""
    front = surface(SQUARE, FACES, [0] * 4)
    back = surface(SQUARE, FACES, [1] * 4)
    budget = m.Budget()
    budget.edge_tests = 5
    monkeypatch.setattr(m, "MAX_EDGE_TESTS", 5)
    with pytest.raises(m.Unverified, match="workload exhausted"):
        constant_back_thickness(front, back, budget)


def test_zero_or_inverted_thickness_is_returned_for_mandatory_refusal():
    """A domain proof never converts a nonpositive interval to a valid solid."""
    front = surface(SQUARE, FACES, [0, 0, 1, 2])
    back = surface(SQUARE, FACES, [1] * 4)
    assert constant_back_thickness(front, back, m.Budget()) == (Q(-1), Q(1))
