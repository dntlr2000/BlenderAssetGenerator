"""Exact boundary-closure eligibility, with interior zero/crossing adversaries."""

from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import owner_relief as m

FRAME = ((0, 2, 1), (1, 1, 1))
SQUARE = [(0, 0), (1, 0), (1, 1), (0, 1)]
DIAGONAL = [(0, 1, 2), (0, 2, 3)]


def lens(*, constant_back=False, height=0.25):
    """Return a complete outward closed lens/pyramid with a shared zero-depth rim."""
    vertices = [(x, 0.0, z) for x, z in SQUARE] + [(0.5, -height, 0.5)]
    front = [(4, i, (i + 1) % 4) for i in range(4)]
    if constant_back:
        back = [(0, 2, 1), (0, 3, 2)]
    else:
        vertices.append((0.5, height, 0.5))
        back = [(5, (i + 1) % 4, i) for i in range(4)]
    return {
        "vertices": vertices,
        "triangles": front + back,
        "front_face_indices": list(range(len(front))),
        "back_face_indices": list(range(len(front), len(front) + len(back))),
        "frame": FRAME,
    }


def thickness_cells(points, faces, thickness):
    """Construct exact affine cells to exercise the zero-locus proof independently."""
    front = m.surface([(x, 0.0, z) for x, z in points], faces, FRAME, m.Budget())
    back = m.surface(
        [(x, h, z) for (x, z), h in zip(points, thickness, strict=True)],
        faces,
        FRAME,
        m.Budget(),
    )
    cells, missing = m.overlay([(p, [plane]) for p, plane in front], back, m.Budget())
    assert not missing
    return front, cells


@pytest.mark.parametrize("constant_back", [False, True])
@pytest.mark.parametrize("binary32", [False, True])
def test_embedded_boundary_closure_has_positive_interior(constant_back, binary32):
    """Both cap-overlay and constant-back paths admit exact silhouette convergence."""
    data = lens(constant_back=constant_back)
    if binary32:
        data["vertices"] = m.float32(data["vertices"])
    result = m.verify_height_field_solid(**data)
    assert result["passed"] is True
    assert result["thickness_range"][0] == "0"
    assert result["boundary_only_zero_thickness"] is True
    assert result["improper_triangle_contact_checked"] is True
    assert result["artifact_identity_verified"] is False


def test_boundary_vertex_is_allowed_without_a_whole_zero_edge():
    """An isolated zero at the exterior corner is still outside the projected interior."""
    front, cells = thickness_cells(SQUARE, DIAGONAL, [0, 1, 1, 1])
    m._require_boundary_only_zero_thickness(front, cells, m.Budget())


def test_hole_boundary_zero_is_distinct_from_interior_zero():
    """A genuine aperture rim belongs to the projected boundary, not a hidden zero slit."""
    points = SQUARE + [(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)]
    faces = [(0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
             (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    front, cells = thickness_cells(points, faces, [1] * 4 + [0] * 4)
    m._require_boundary_only_zero_thickness(front, cells, m.Budget())


def test_arbitrarily_small_positive_interior_is_not_rounded_to_zero():
    """No epsilon changes the exact distinction between interior positivity and a pinch."""
    points = SQUARE + [(0.5, 0.5)]
    faces = [(4, i, (i + 1) % 4) for i in range(4)]
    front, cells = thickness_cells(points, faces, [0, 0, 0, 0, 2**-80])
    m._require_boundary_only_zero_thickness(front, cells, m.Budget())


def test_isolated_interior_zero_vertex_is_refused():
    """A pinched point inside the domain cannot borrow the exterior-zero exception."""
    points = SQUARE + [(0.5, 0.5)]
    faces = [(4, i, (i + 1) % 4) for i in range(4)]
    front, cells = thickness_cells(points, faces, [1, 1, 1, 1, 0])
    with pytest.raises(m.Unverified, match="interior zero-thickness vertex"):
        m._require_boundary_only_zero_thickness(front, cells, m.Budget())


def test_zero_edge_with_boundary_endpoints_but_interior_is_refused():
    """A diagonal zero line has exterior endpoints but an impermissible interior."""
    front, cells = thickness_cells(SQUARE, DIAGONAL, [0, 1, 0, 1])
    with pytest.raises(m.Unverified, match="interior zero-thickness edge"):
        m._require_boundary_only_zero_thickness(front, cells, m.Budget())


def test_positive_area_zero_cell_is_refused():
    """A coincident cap region is never an eligible zero-thickness boundary."""
    front, cells = thickness_cells(SQUARE, DIAGONAL, [0, 0, 0, 1])
    with pytest.raises(m.Unverified, match="positive-area zero-thickness cell"):
        m._require_boundary_only_zero_thickness(front, cells, m.Budget())


def test_one_ulp_negative_thickness_is_not_clamped():
    """Exact negative thickness remains a crossing regardless of its magnitude."""
    front, cells = thickness_cells(SQUARE, DIAGONAL, [-2**-52, 1, 1, 1])
    with pytest.raises(m.Unverified, match="crossed bounding graphs"):
        m._require_boundary_only_zero_thickness(front, cells, m.Budget())


def test_boundary_interval_union_retains_a_subprecision_gap():
    """Whole segment coverage cannot be replaced by endpoint or midpoint sampling."""
    a, b = (Q(0), Q(0)), (Q(1), Q(0))
    left, right = Q(1, 4), Q(1, 4) + Q(1, 2**60)
    boundary = [(a, (left, Q(0))), ((right, Q(0)), b)]
    assert not m._boundary_covers_zero_edge(a, b, boundary, m.Budget())
    boundary.append(((left, Q(0)), (right, Q(0))))
    assert m._boundary_covers_zero_edge(a, b, boundary, m.Budget())


def test_subdivided_shared_diagonal_cancels_from_boundary():
    """An internal edge split on one side does not masquerade as exterior boundary."""
    points = SQUARE + [(0.5, 0.5)]
    front = m.surface(
        [(x, 0.0, z) for x, z in points],
        [(0, 1, 2), (0, 4, 3), (4, 2, 3)],
        FRAME,
        m.Budget(),
    )
    boundary = m._projected_boundary_segments(front, m.Budget())
    assert not m._boundary_covers_zero_edge((Q(0), Q(0)), (Q(1), Q(1)), boundary, m.Budget())
    assert m._boundary_covers_zero_edge((Q(0), Q(0)), (Q(1), Q(0)), boundary, m.Budget())


def test_zero_locus_shares_existing_edge_work_budget(monkeypatch):
    """The new exact boundary work must fail closed without resetting its caller's budget."""
    front, cells = thickness_cells(SQUARE, DIAGONAL, [0, 1, 1, 1])
    budget = m.Budget()
    budget.edge_tests = 7
    monkeypatch.setattr(m, "MAX_EDGE_TESTS", 7)
    with pytest.raises(m.Unverified, match="workload exhausted"):
        m._require_boundary_only_zero_thickness(front, cells, budget)


def test_embedding_failure_still_precedes_boundary_exception():
    """Crossed front/back caps do not become eligible merely because their rim coincides."""
    data = lens()
    data["vertices"][5] = (0.5, -0.5, 0.5)
    assert m.verify_height_field_solid(**data)["status"] == "unverified"


def test_wrong_cap_orientation_remains_unverified():
    """Boundary closure never grants permission to swap complete front/back roles."""
    data = lens()
    data["front_face_indices"], data["back_face_indices"] = (
        data["back_face_indices"], data["front_face_indices"]
    )
    assert m.verify_height_field_solid(**data)["status"] == "unverified"
