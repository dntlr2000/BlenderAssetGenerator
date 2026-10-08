"""Independent analytic and adversarial cases for integrated owner fronts."""

import pytest
from test_partition_heightfield import box, independent_measures

from codex_blender_modeler.structural_geometry.compose_owner_front import (
    compose_owner_front,
)


def pyramid(name="shoulder", offset=0.0, height=0.25):
    """Declare a square pyramid with an exact zero-height perimeter."""
    return {
        "id": name,
        "vertices": [
            [-0.5 + offset, -0.5, 0.0],
            [0.5 + offset, -0.5, 0.0],
            [0.5 + offset, 0.5, 0.0],
            [-0.5 + offset, 0.5, 0.0],
            [offset, 0.0, height],
        ],
        "triangles": [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
    }


def compose(profiles, slope=False):
    """Compose a fixture against an independently constructed complete slab."""
    v, f = box(slope)
    return compose_owner_front(
        vertices=v,
        triangles=f,
        front_face_indices=[0, 1],
        back_face_indices=[2, 3],
        profiles=profiles,
        maximum_profile_height=0.5,
        minimum_remaining_thickness=1.0,
    )


def test_analytic_pyramid_volume_and_preserved_rear():
    """Complete pyramid volume is added while the unchanged rear and walls remain closed."""
    r = compose([pyramid()])
    volume, area, edges = independent_measures(r["vertices"], r["triangles"])
    assert volume == pytest.approx(8 + 1 / 12, abs=1e-12)
    assert set(edges.values()) == {2}
    assert r["diagnostics"]["profiles"][0]["full_footprint_retained"]
    for i in {v for fi in r["face_roles"]["back"] for v in r["triangles"][fi]}:
        assert r["vertices"][i][1] == 1.0


def test_overlapping_profiles_add_integrals():
    """Overlapping height profiles preserve both complete footprints and additive volume."""
    r = compose([pyramid("first", -0.25), pyramid("second", 0.25)])
    assert independent_measures(r["vertices"], r["triangles"])[0] == pytest.approx(
        8 + 1 / 6, abs=1e-12
    )
    assert all(r["feature_face_groups"].values())


def test_slanted_owner():
    """Profile composition keeps the original affine slope and adds the same volume."""
    r = compose([pyramid()], True)
    assert independent_measures(r["vertices"], r["triangles"])[0] == pytest.approx(
        8 + 1 / 12, abs=1e-12
    )


def test_wall_touching_zero_profile():
    """A profile reaching the owner outline keeps its cap and side subdivisions closed."""
    r = compose([pyramid(offset=-0.5)])
    assert r["diagnostics"]["checks"]["binary32"]["closed_embedded"]


def test_nonzero_boundary_refused():
    """An exposed discontinuous profile edge cannot become an internal wall by accident."""
    p = pyramid()
    p["vertices"][0][2] = 0.01
    with pytest.raises(ValueError, match="boundary height"):
        compose([p])


def test_escape_refused():
    """Unsupported footprint area cannot disappear into a trimmed passing profile."""
    with pytest.raises(ValueError, match="escapes"):
        compose([pyramid(offset=0.75)])


def test_negative_height_refused():
    """The outward-only kernel rejects undeclared inward carving."""
    with pytest.raises(ValueError, match="nonnegative"):
        compose([pyramid(height=-0.1)])


def test_duplicate_id_refused():
    """Feature groups must have a unique stable identity."""
    with pytest.raises(ValueError, match="unique"):
        compose([pyramid(), pyramid()])


def test_subprecision_overlap_refused():
    """Near-coincident binary controls cannot be rounded into an apparently valid shell."""
    with pytest.raises(ValueError, match="coincident vertex"):
        compose([pyramid("first", -0.2), pyramid("second", 0.2)])
