"""Exact global-separation proof, preserved fallback and domain/adversarial guards."""

from fractions import Fraction as Q

import pytest
from test_constant_back_oracles import box_arguments, rectangle, surface_from_cells

from codex_blender_modeler.structural_geometry import constant_back as candidate
from codex_blender_modeler.structural_geometry import owner_relief as m


def tilt(surface, amount):
    """Change only affine depths of an exact prevalidated surface for proof fixtures."""
    return [
        (poly, [(p[0], p[1], p[2] + amount * p[0]) for p in points]) for poly, points in surface
    ]


def test_global_bounds_are_conservative_not_attained_extrema():
    """Parallel sloped caps have constant thickness inside strictly looser global bounds."""
    front = tilt(rectangle(0.0, 1.0, bottom=0.0, depth=0.0), Q(1))
    back = tilt(rectangle(0.0, 1.0, bottom=0.0, depth=2.0), Q(1))
    assert candidate.separated_depth_bounds(front, back, m.Budget()) == (Q(1), Q(3))


@pytest.mark.parametrize("gap", [0.0, -(2**-45), 2**-45])
def test_strict_separation_has_no_epsilon(gap):
    """An exact zero or negative global gap cannot use this sufficient proof."""
    front = rectangle(0.0, 1.0, bottom=0.0, depth=0.0)
    back = rectangle(0.0, 1.0, bottom=0.0, depth=gap)
    result = candidate.separated_depth_bounds(front, back, m.Budget())
    assert result == ((Q(gap), Q(gap)) if gap > 0 else None)


def test_different_domains_and_tiny_slits_cannot_use_separation():
    """Depth bounds alone cannot hide absent projected support."""
    front = rectangle(-1.0, 1.0, depth=-1.0)
    for gap in (2**-45, 0.25):
        back = rectangle(-1.0, 0.0, depth=1.0) + rectangle(gap, 1.0, depth=1.0)
        assert candidate.separated_depth_bounds(front, back, m.Budget()) is None


def test_changed_hole_refused_despite_equal_area_and_outer_boundary():
    """The complete exact oriented boundary includes every hole, not just its envelope."""
    cells = {(x, y) for x in range(-2, 2) for y in range(-2, 2)}
    front = surface_from_cells(cells - {(-1, -1)}, True, True)
    back = tilt(surface_from_cells(cells - {(0, 0)}, False, False), Q(1, 32))
    assert candidate.separated_depth_bounds(front, back, m.Budget()) is None


def test_existing_budget_is_charged_without_reset(monkeypatch):
    """Work exhaustion remains unverified instead of creating unbounded exact arithmetic."""
    front = rectangle(0.0, 1.0, depth=-1.0)
    back = rectangle(0.0, 1.0, depth=1.0)
    budget = m.Budget()
    budget.edge_tests = 7
    monkeypatch.setattr(m, "MAX_EDGE_TESTS", 7)
    with pytest.raises(m.Unverified, match="workload exhausted"):
        candidate.separated_depth_bounds(front, back, budget)


def test_expensive_overlay_can_use_bounds_but_small_fixture_keeps_exact_range(monkeypatch):
    """A cost-based route preserves small historical overlays and labels conservative results."""
    args = box_arguments(sloped=True)
    before = m.verify_height_field_solid(**args)
    assert before["passed"] and before["thickness_range"] == ["2", "2"]
    monkeypatch.setattr(m, "MAX_CELLS", 1)
    result = m.verify_height_field_solid(**args)
    assert result["passed"]
    assert result["thickness_range_kind"] == "conservative_global_separation_bounds"
    assert Q(result["thickness_range"][0]) <= 2 <= Q(result["thickness_range"][1])


def test_embedding_refusal_precedes_global_depth_proof(monkeypatch):
    """Disjoint depth ranges never replace complete-solid embedding checks."""
    calls = []

    def reject(shell):
        """Simulate mandatory whole-solid rejection before any sufficient depth proof."""
        raise ValueError("mandatory embedding refusal")

    def forbidden(*args, **kwargs):
        """Observe prohibited shortcut execution after failed embedding."""
        calls.append(True)
        raise AssertionError("shortcut after failure")

    monkeypatch.setattr(m, "_validate_embedded", reject)
    monkeypatch.setattr(candidate, "separated_depth_bounds", forbidden)
    assert m.verify_height_field_solid(**box_arguments(sloped=True))["status"] == "unverified"
    assert calls == []
