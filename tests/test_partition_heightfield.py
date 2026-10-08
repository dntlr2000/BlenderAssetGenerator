"""Independent geometric cases for bounded root-face partition authoring."""

import math
import struct
from collections import Counter

import numpy as np
import pytest

from codex_blender_modeler.structural_geometry.contour_relief import build_contour_prism
from codex_blender_modeler.structural_geometry.partition_heightfield import (
    partition_heightfield_faces,
)


def box(slope=False):
    """Create a real closed slab, optionally with parallel slanted front/back graphs."""
    shell = build_contour_prism([(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)], depth=2.0)
    vertices = [list(p) for p in shell.vertices]
    if slope:
        for p in vertices:
            p[1] += 0.25 * p[0] - 0.125 * p[2]
    return vertices, [list(f) for f in shell.triangles]


def run_patch(points, slope=False):
    """Partition a declared convex quadrilateral against both complete slab graphs."""
    v, f = box(slope)
    return (
        v,
        f,
        partition_heightfield_faces(
            vertices=v,
            triangles=f,
            front_face_indices=[0, 1],
            back_face_indices=[2, 3],
            patch_vertices=points,
            patch_triangles=[[0, 1, 2], [0, 2, 3]],
        ),
    )


def independent_measures(vertices, faces):
    """Compute volume, area and indexed edge incidence independently with vectorized arithmetic."""
    v = np.asarray(vertices)
    f = np.asarray(faces)
    cross = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    volume = float(np.einsum("ij,ij->i", v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])).sum() / 6)
    area = float(np.linalg.norm(cross, axis=1).sum() / 2)
    edges = Counter(
        tuple(sorted((int(a), int(b))))
        for row in f
        for a, b in zip(row, np.roll(row, -1), strict=False)
    )
    return volume, area, edges


@pytest.mark.parametrize(
    "patch",
    [
        [[-0.4, -0.4], [0.4, -0.4], [0.4, 0.4], [-0.4, 0.4]],
        [[-1.0, -0.5], [0.2, -0.5], [0.2, 0.5], [-1.0, 0.5]],
        [[-1.0, -1.0], [0.0, -1.0], [0.0, 0.0], [-1.0, 0.0]],
        [[-0.75, -0.25], [0.5, -0.5], [0.75, 0.25], [-0.25, 0.75]],
    ],
)
def test_closed_area_volume_boundary_and_float32(patch):
    """Interior, wall-touching, corner-touching and oblique patches retain the whole real slab."""
    oldv, oldf, result = run_patch(patch)
    v = result["vertices"]
    f = result["triangles"]
    volume, area, edges = independent_measures(v, f)
    assert volume == pytest.approx(8.0, abs=1e-12)
    assert area == pytest.approx(24.0, abs=1e-12)
    assert set(edges.values()) == {2}
    assert result["diagnostics"]["full_patch_retained"]
    assert result["face_roles"]["patch_front"] and result["face_roles"]["patch_back"]
    for point in v:
        assert min(abs(abs(point[i]) - 1) for i in range(3)) < 1e-12
    cast = [[struct.unpack("f", struct.pack("f", x))[0] for x in p] for p in v]
    vol32, area32, edges32 = independent_measures(cast, f)
    assert vol32 == pytest.approx(8.0, abs=1e-6)
    assert area32 == pytest.approx(24.0, abs=1e-5)
    assert set(edges32.values()) == {2}


def test_slanted_affine_planes_retained():
    """Every new selected cap vertex remains on the correct original non-horizontal plane."""
    _, _, result = run_patch([[-0.75, -0.25], [0.5, -0.5], [0.75, 0.25], [-0.25, 0.75]], slope=True)
    for role, base in [("front", -1.0), ("back", 1.0)]:
        for i in {v for fi in result["face_roles"][role] for v in result["triangles"][fi]}:
            x, y, z = result["vertices"][i]
            assert y == pytest.approx(base + 0.25 * x - 0.125 * z, abs=1e-12)
    assert independent_measures(result["vertices"], result["triangles"])[0] == pytest.approx(
        8.0, abs=1e-12
    )


def test_whole_requested_patch_cannot_be_clipped_away():
    """An outside strip is a failure, never a smaller passing selected patch."""
    with pytest.raises(ValueError, match="escapes"):
        run_patch([[-1.2, -0.5], [-0.8, -0.5], [-0.8, 0.5], [-1.2, 0.5]])


def test_nonfinite_patch_is_refused():
    """Unbounded/nonfinite patch coordinates cannot enter exact clipping."""
    with pytest.raises((ValueError, OverflowError)):
        run_patch([[math.inf, -0.5], [0.8, -0.5], [0.8, 0.5], [-0.8, 0.5]])


def test_boundary_wall_gets_new_vertices():
    """A root boundary reaching the perimeter subdivides both graphs and their connecting wall."""
    _, _, result = run_patch([[-1.0, -0.5], [0.2, -0.5], [0.2, 0.5], [-1.0, 0.5]])
    wall_vertices = {v for fi in result["face_roles"]["sides"] for v in result["triangles"][fi]}
    points = [result["vertices"][i] for i in wall_vertices]
    for y in [-1.0, 1.0]:
        for z in [-0.5, 0.5]:
            assert any(p == [-1.0, y, z] for p in points)


def test_ambiguous_owner_is_refused():
    """Duplicated whole-owner faces cannot be hidden by selecting only clean front/back patches."""
    v, f = box()
    f.append(f[0])
    with pytest.raises(ValueError, match="ineligible"):
        partition_heightfield_faces(
            vertices=v,
            triangles=f,
            front_face_indices=[0, 1],
            back_face_indices=[2, 3],
            patch_vertices=[[-0.4, -0.4], [0.4, -0.4], [0.4, 0.4], [-0.4, 0.4]],
            patch_triangles=[[0, 1, 2], [0, 2, 3]],
        )
