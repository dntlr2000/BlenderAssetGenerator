"""Check declared root domains without adding verification topology to geometry."""

import copy
from fractions import Fraction

import pytest

from codex_blender_modeler.structural_geometry import owner_relief as m
from codex_blender_modeler.structural_geometry.root_region import (
    inspect_root_region,
    polygon_cells,
)


def graphs():
    """Return intersecting constant-depth slabs over an ordinary square domain."""
    result = {
        "region_polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
        "minimum_overlap": 0.25,
        "frame": ((0, 1, 2), (1, 1, 1)),
    }
    for key, height in (("upper", 0), ("lower", 1), ("owner_front", 0.5), ("owner_back", 2)):
        result[key + "_vertices"] = [[0, 0, height], [1, 0, height], [1, 1, height], [0, 1, height]]
        result[key + "_triangles"] = [[0, 1, 2], [0, 2, 3]]
    return result


def test_root_region_does_not_mutate_or_claim_whole_solid_identity():
    """A full positive result leaves mesh bytes and unrelated assertions untouched."""
    kwargs = graphs()
    original = copy.deepcopy(kwargs)
    result = inspect_root_region(**kwargs)
    assert result["passed"] is True
    assert result["minimum_overlap_m_exact"] == "1/2"
    assert result["region_area_exact"] == result["covered_area_exact"] == "1"
    assert kwargs == original
    assert result["owner_volume_verified"] is False
    assert result["artifact_identity_verified"] is False
    assert result["free_subject_area_overlap_claimed"] is False


@pytest.mark.parametrize("reverse", [False, True])
def test_nonconvex_region_preserves_missing_notch(reverse):
    """A concave L-shaped root covers exactly three quarters of the square."""
    kwargs = graphs()
    polygon = [[0, 0], [1, 0], [1, 0.5], [0.5, 0.5], [0.5, 1], [0, 1]]
    kwargs["region_polygon"] = polygon[::-1] if reverse else polygon
    result = inspect_root_region(**kwargs)
    assert result["passed"] is True
    assert result["region_area_exact"] == result["covered_area_exact"] == "3/4"


def test_collinear_boundary_control_is_exactly_preserved():
    """An exact extra point on an edge changes neither domain nor overlap proof."""
    kwargs = graphs()
    kwargs["region_polygon"].insert(1, [0.25, 0])
    assert inspect_root_region(**kwargs)["region_area_exact"] == "1"


@pytest.mark.parametrize(
    "polygon",
    [
        [],
        [[0, 0], [1, 0]],
        [[0, 0], [1, 0], [2, 0]],
        [[0, 0], [1, 1], [0, 1], [1, 0]],
        [[0, 0], [1, 0], [0.5, 0], [1, 1], [0, 1]],
        [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
        [[[0, 0], [1, 0], [1, 1]], [[0.2, 0.2], [0.3, 0.2], [0.2, 0.3]]],
        [[0, 0], [1, 0], [float("nan"), 1]],
        [[0, 0], [True, 0], [0, 1]],
    ],
)
def test_malformed_regions_are_unverified(polygon):
    """Malformed inputs cannot become vacuous passing contact evidence."""
    kwargs = graphs()
    kwargs["region_polygon"] = polygon
    result = inspect_root_region(**kwargs)
    assert result["status"] == "unverified"
    assert result["passed"] is None


@pytest.mark.parametrize("key", ["upper", "lower", "owner_front", "owner_back"])
def test_every_surface_must_cover_even_subpixel_region_sliver(key):
    """Exact clipping refuses a positive missing strip without any tolerance."""
    kwargs = graphs()
    for point in kwargs[key + "_vertices"]:
        if point[0] == 1:
            point[0] = 1 - 2**-40
    result = inspect_root_region(**kwargs)
    assert result["status"] == "failed"
    assert Fraction(result["covered_area_exact"]) < 1
    assert any(result["uncovered_polygons"].values())


def test_underneath_gap_fails_even_when_projection_matches():
    """Projected overlap alone cannot validate separated depth intervals."""
    kwargs = graphs()
    for point in kwargs["owner_front_vertices"]:
        point[2] = 1 + 2**-40
    result = inspect_root_region(**kwargs)
    assert result["status"] == "failed"
    assert Fraction(result["minimum_overlap_m_exact"]) < 0


def test_affine_wedge_detects_endpoint_minimum():
    """The complete affine proof catches a gap away from a passing center sample."""
    kwargs = graphs()
    for point in kwargs["owner_front_vertices"]:
        point[2] = 1.25 * point[0]
    result = inspect_root_region(**kwargs)
    assert result["status"] == "failed"
    assert result["minimum_overlap_m_exact"] == "-1/4"


def test_intended_free_surface_outside_region_is_not_claimed():
    """A bounded root region need not cover the rest of an open protruding part."""
    kwargs = graphs()
    kwargs["region_polygon"] = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]
    for key in ("owner_front", "owner_back"):
        for point in kwargs[key + "_vertices"]:
            if point[0] == 1:
                point[0] = 0.5
    assert inspect_root_region(**kwargs)["passed"] is True
    kwargs["region_polygon"][1][0] = 0.5 + 2**-40
    assert inspect_root_region(**kwargs)["status"] == "failed"


def test_wrong_frame_is_not_silently_reinterpreted():
    """A frame projecting a cap edge-on cannot certify that surface."""
    kwargs = graphs()
    kwargs["frame"] = ((0, 2, 1), (1, 1, 1))
    assert inspect_root_region(**kwargs)["status"] == "unverified"


def test_exact_boundary_measure_and_unchanged_budget(monkeypatch):
    """Region triangulation retains binary fractions and respects shared work caps."""
    polygon = [[0, 0], [1, 0], [1, 2**-45], [0, 2**-45]]
    cells, area = polygon_cells(polygon, m.Budget())
    assert area == Fraction(1, 2**45)
    assert sum(m.area(cell) for cell in cells) == area
    monkeypatch.setattr(m, "MAX_EDGE_TESTS", 0)
    assert inspect_root_region(**graphs())["status"] == "unverified"
