"""Independent closed-topology counterexamples require actual surface embedding."""

import pytest

from codex_blender_modeler.structural_geometry.owner_relief import (
    verify_height_field_solid,
)


def side_fan(point):
    """Triangulate a box side through an independently chosen projected-zero-area point."""
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 1.0),
        (0.0, 0.0, 1.0),
        (0.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0),
        point,
    ]
    triangles = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 8),
        (7, 4, 8),
        (4, 0, 8),
        (0, 3, 8),
    ]
    return dict(
        vertices=vertices,
        triangles=triangles,
        front_face_indices=[0, 1],
        back_face_indices=[2, 3],
    )


@pytest.mark.parametrize("point", [(0.0, 2.0, 0.5), (0.0, 0.5, 1.5), (0.0, -0.5, 0.5)])
def test_folded_vertical_side_is_not_a_volume_proof(point):
    """Positive volume and manifold topology cannot admit overlapping side fans."""
    result = verify_height_field_solid(**side_fan(point))
    assert result["status"] == "unverified" and not result["owner_volume_verified"]
    assert "intersect" in result["reason"] or "touch" in result["reason"]


def test_interior_side_fan_is_a_valid_retessellation():
    """A proper side triangulation inside the wall rectangle retains positive eligibility."""
    result = verify_height_field_solid(**side_fan((0.0, 0.5, 0.5)))
    assert result["passed"] and result["improper_triangle_contact_checked"]
