"""Independent domain/topology preconditions for the exact constant-back shortcut."""

import copy
import itertools
from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import constant_back as candidate
from codex_blender_modeler.structural_geometry import owner_relief as m
from codex_blender_modeler.structural_geometry.contour_relief import build_contour_prism


def surface_from_cells(cells, front, subdivide):
    """Build different exact cap triangulations on independently specified unit grid cells."""
    vertices = []
    faces = []
    for x, y in sorted(cells):
        n = len(vertices)
        points = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
        if subdivide:
            points.append((x + 0.375, y + 0.625))
            local = [[i, (i + 1) % 4, 4] for i in range(4)]
        else:
            local = [[0, 1, 3], [1, 2, 3]]
        vertices.extend(
            [[u, v, (-1.0 + 0.125 * abs(u) + 0.25 * v) if front else 1.0] for u, v in points]
        )
        faces.extend([[i + n for i in f] for f in local])
    return m.surface(vertices, faces, ((0, 1, 2), (1, 1, 1)), m.Budget())


def rectangle(left, right, bottom=-1.0, top=1.0, depth=0.0):
    """Represent one exact rectangular graph with an ordinary diagonal."""
    vertices = [
        [left, bottom, depth],
        [right, bottom, depth],
        [right, top, depth],
        [left, top, depth],
    ]
    return m.surface(vertices, [[0, 1, 2], [0, 2, 3]], ((0, 1, 2), (1, 1, 1)), m.Budget())


@pytest.mark.parametrize("hole", [None, (0, 0), (-1, 0)])
def test_different_tessellations_and_true_holes_keep_analytic_thickness(hole):
    """Projected oriented-boundary equality preserves holes and a creased affine front."""
    cells = set(itertools.product(range(-2, 2), repeat=2))
    if hole is not None:
        cells.remove(hole)
    front = surface_from_cells(cells, True, True)
    back = surface_from_cells(cells, False, False)
    result = candidate.constant_back_thickness(front, back, m.Budget())
    expected = [
        Q(2) - Q(0.125) * abs(Q(x + i)) - Q(0.25) * Q(y + j)
        for x, y in cells
        for i, j in itertools.product((0, 1), repeat=2)
    ]
    assert result == (min(expected), max(expected))


def test_equal_area_and_outer_boundary_do_not_hide_a_different_hole():
    """Swapping equal-area interior holes changes the domain even with identical outer bounds."""
    cells = set(itertools.product(range(-2, 2), repeat=2))
    front = surface_from_cells(cells - {(-1, -1)}, True, True)
    back = surface_from_cells(cells - {(0, 0)}, False, False)
    assert sum(m.area(p) for p, _ in front) == sum(m.area(p) for p, _ in back)
    assert candidate.constant_back_thickness(front, back, m.Budget()) is None


@pytest.mark.parametrize("gap", [0.0, 2.0**-40])
def test_touching_subdivisions_equal_but_positive_slits_do_not(gap):
    """A tiny exact gap cannot be cancelled by area or endpoint tolerance."""
    front = rectangle(-1.0, 1.0, depth=-1.0)
    back = rectangle(-1.0, 0.0, depth=1.0) + rectangle(gap, 1.0, depth=1.0)
    result = candidate.constant_back_thickness(front, back, m.Budget())
    assert result == ((Q(2), Q(2)) if not gap else None)


def test_equal_area_shifted_domain_and_doubled_boundary_cannot_match():
    """Line location and oriented multiplicity matter independently of total area."""
    front = rectangle(-1.0, 1.0, depth=-1.0)
    shifted = rectangle(0.0, 2.0, depth=1.0)
    assert candidate.constant_back_thickness(front, shifted, m.Budget()) is None
    back = rectangle(-1.0, 1.0, depth=1.0)
    assert candidate.constant_back_thickness(front + front, back, m.Budget()) is None


def test_nonconstant_back_with_one_tiny_difference_uses_fallback():
    """An arbitrarily small real back-depth change cannot be treated as constant."""
    front = rectangle(-1.0, 1.0, depth=-1.0)
    vertices = [[-1.0, -1.0, 1.0], [1.0, -1.0, 1.0], [1.0, 1.0, 1.0 + 2.0**-40], [-1.0, 1.0, 1.0]]
    back = m.surface(vertices, [[0, 1, 2], [0, 2, 3]], ((0, 1, 2), (1, 1, 1)), m.Budget())
    assert candidate.constant_back_thickness(front, back, m.Budget()) is None


def box_arguments(sloped=False):
    """Build a real complete slab for call-order and general-fallback tests."""
    shell = build_contour_prism([(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)], depth=2.0)
    vertices = [list(p) for p in shell.vertices]
    if sloped:
        for point in vertices:
            point[1] += 0.25 * point[0] - 0.125 * point[2]
    return dict(
        vertices=vertices,
        triangles=[list(f) for f in shell.triangles],
        front_face_indices=[0, 1],
        back_face_indices=[2, 3],
    )


def test_whole_embedding_failure_prevents_shortcut_call(monkeypatch):
    """The optimized proof must never turn an unverified shell into an eligible owner."""
    calls = []

    def forbidden(*args, **kwargs):
        """Observe any attempt to reach the shortcut after whole-solid rejection."""
        calls.append(True)
        raise AssertionError("shortcut reached before embedding proof")

    def reject(_shell):
        """Reject the existing mandatory global embedding guard."""
        raise ValueError("independent embedding refusal")

    monkeypatch.setattr(candidate, "constant_back_thickness", forbidden)
    monkeypatch.setattr(m, "_validate_embedded", reject)
    result = m.verify_height_field_solid(**box_arguments())
    assert result["status"] == "unverified" and calls == []


def test_nonconstant_valid_solid_retains_general_overlay(monkeypatch):
    """A tilted back still executes the old exact front/back overlay proof."""
    calls = []
    real = m.overlay

    def record(*args, **kwargs):
        """Observe real fallback overlays while delegating their complete unchanged work."""
        calls.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(m, "overlay", record)
    result = m.verify_height_field_solid(**box_arguments(sloped=True))
    assert result["passed"] and len(calls) == 2
    assert result["thickness_range"] == ["2", "2"]


@pytest.mark.parametrize("mutation", ["missing_cap", "wrong_role", "duplicate_face"])
def test_invalid_complete_role_membership_cannot_use_constant_back(mutation):
    """Normal, coverage and indexed shell failures remain mandatory before the shortcut."""
    args = box_arguments()
    if mutation == "missing_cap":
        args["front_face_indices"] = [0]
    elif mutation == "wrong_role":
        args["front_face_indices"], args["back_face_indices"] = (
            args["back_face_indices"],
            args["front_face_indices"],
        )
    else:
        args["triangles"].append(args["triangles"][0])
    assert m.verify_height_field_solid(**args)["status"] == "unverified"


def test_shared_work_budget_exhaustion_does_not_return_partial_range(monkeypatch):
    """Every reused budget remains finite and its input graphs remain unchanged on refusal."""
    front = rectangle(-1.0, 1.0, depth=-1.0)
    back = rectangle(-1.0, 1.0, depth=1.0)
    original = copy.deepcopy((front, back))
    budget = m.Budget()
    monkeypatch.setattr(m, "MAX_EDGE_TESTS", 10)
    with pytest.raises(m.Unverified, match="workload"):
        candidate.constant_back_thickness(front, back, budget)
    assert (front, back) == original and budget.edge_tests == 11
