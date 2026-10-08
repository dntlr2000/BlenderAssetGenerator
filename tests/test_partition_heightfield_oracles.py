"""Independent analytic graph and multiply-connected footprint oracles."""

import itertools
from collections import Counter
from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import owner_relief
from codex_blender_modeler.structural_geometry.partition_heightfield import (
    partition_heightfield_faces,
)
from codex_blender_modeler.structural_geometry.triangle_shell import (
    TriangulatedShellGeometry,
)


def height(x, z, front):
    """Define an independent creased front and tilted back graph with known thick interior."""
    return -1.0 + 0.125 * abs(x) + 0.25 * z if front else 1.0 - 0.125 * x + 0.125 * z


def literal_ring():
    """Extrude a square grid with a real square hole; preserve one sharp front crease."""
    knots = [-1.0, -0.25, 0.0, 0.25, 1.0]
    uv = []
    index = {}
    front = []
    for i, j in itertools.product(range(4), repeat=2):
        if i in (1, 2) and j in (1, 2):
            continue
        row = []
        for point in (
            (knots[i], knots[j]),
            (knots[i + 1], knots[j]),
            (knots[i + 1], knots[j + 1]),
            (knots[i], knots[j + 1]),
        ):
            if point not in index:
                index[point] = len(uv)
                uv.append(point)
            row.append(index[point])
        a, b, c, d = row
        front.extend([(a, b, c), (a, c, d)])
    n = len(uv)
    vertices = [(x, height(x, z, True), z) for x, z in uv] + [
        (x, height(x, z, False), z) for x, z in uv
    ]
    back = [tuple(i + n for i in reversed(face)) for face in front]
    edge_counts = Counter(
        tuple(sorted((a, b))) for f in front for a, b in zip(f, f[1:] + f[:1], strict=False)
    )
    sides = []
    for f in front:
        for a, b in zip(f, f[1:] + f[:1], strict=False):
            if edge_counts[tuple(sorted((a, b)))] == 1:
                sides.extend([(a, a + n, b + n), (a, b + n, b)])
    faces = front + back + sides
    return (
        [list(v) for v in vertices],
        [list(f) for f in faces],
        list(range(len(front))),
        list(range(len(front), 2 * len(front))),
    )


def partition(pv, pt, frame=((0, 2, 1), (1, 1, 1))):
    """Transform one literal solid into the requested signed frame without altering its graphs."""
    vertices, faces, front, back = literal_ring()
    axes, signs = frame
    transformed = []
    for x, y, z in vertices:
        value = [0.0, 0.0, 0.0]
        for axis, sign, coordinate in zip(axes, signs, (x, z, y), strict=False):
            value[axis] = sign * coordinate
        transformed.append(value)
    # A reflection reverses global outward winding.
    perm_sign = (-1) ** sum(axes[i] > axes[j] for i in range(3) for j in range(i + 1, 3))
    determinant = -perm_sign * signs[0] * signs[1] * signs[2]
    if determinant < 0:
        faces = [f[::-1] for f in faces]
    return partition_heightfield_faces(
        vertices=transformed,
        triangles=faces,
        front_face_indices=front,
        back_face_indices=back,
        patch_vertices=pv,
        patch_triangles=pt,
        frame=frame,
    )


@pytest.mark.parametrize(
    "frame",
    [
        ((0, 2, 1), (1, 1, 1)),
        ((2, 0, 1), (-1, 1, 1)),
        ((1, 0, 2), (1, -1, -1)),
        ((1, 2, 0), (-1, -1, 1)),
    ],
)
def test_crease_hole_disconnected_patch_and_signed_axes_preserve_literal_graphs(frame):
    """Disconnected supported strips leave the hole empty and retain the exact analytic cap
    surfaces."""
    pv = [
        [-1.0, -0.25],
        [-0.25, -0.25],
        [-0.25, 0.25],
        [-1.0, 0.25],
        [0.25, -0.25],
        [1.0, -0.25],
        [1.0, 0.25],
        [0.25, 0.25],
    ]
    result = partition(pv, [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], frame)
    axes, signs = frame
    canonical = [
        tuple(p[axis] * sign for axis, sign in zip(axes, signs, strict=False))
        for p in result["vertices"]
    ]
    roles = result["face_roles"]
    faces = result["triangles"]
    for role, isfront in [("front", True), ("back", False)]:
        total = Q(0)
        selected = Q(0)
        for fi in roles[role]:
            pts = [canonical[i] for i in faces[fi]]
            for x, z, d in pts:
                assert d == pytest.approx(height(x, z, isfront), abs=2e-15)
            assert not (min(p[0] for p in pts) < 0 < max(p[0] for p in pts)), (
                "new front triangle bridges the crease"
            )
            (x0, z0, _), (x1, z1, _), (x2, z2, _) = map(lambda p: tuple(Q(c) for c in p), pts)
            area = abs((x1 - x0) * (z2 - z0) - (x2 - x0) * (z1 - z0)) / 2
            total += area
            if fi in roles["patch_" + role]:
                selected += area
        assert total == Q(15, 4)
        assert selected == Q(3, 4)
    shell = TriangulatedShellGeometry(
        vertices=[tuple(p) for p in result["vertices"]],
        triangles=[tuple(f) for f in faces],
    )
    assert shell
    for cast in (lambda x: x, owner_relief.float32):
        proof = owner_relief.verify_height_field_solid(
            vertices=cast(result["vertices"]),
            triangles=faces,
            front_face_indices=roles["front"],
            back_face_indices=roles["back"],
            frame=frame,
        )
        assert proof["passed"], proof


def test_requested_patch_through_true_hole_is_refused():
    """A complete square request cannot be rescued by retaining only its supported ring area."""
    with pytest.raises(ValueError, match="escapes"):
        partition([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]], [[0, 1, 2], [0, 2, 3]])


def test_float32_collapsed_partition_is_refused():
    """A positive-width binary64 cap strip collapsing in binary32 cannot receive a completed
    proof."""
    epsilon = 2.0**-30
    with pytest.raises((ValueError, owner_relief.Unverified)):
        partition(
            [
                [0.5, -0.125],
                [0.5 + epsilon, -0.125],
                [0.5 + epsilon, 0.125],
                [0.5, 0.125],
            ],
            [[0, 1, 2], [0, 2, 3]],
        )


def test_partition_charges_anchor_candidates_rejected_on_other_axis(monkeypatch):
    """This literal patch performs over 200 candidate visits, including candidates rejected by
    the second axis."""
    from codex_blender_modeler.structural_geometry.contour_relief import (
        build_contour_prism,
    )

    slab = build_contour_prism([(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)], depth=2.0)
    monkeypatch.setattr(owner_relief, "MAX_EDGE_TESTS", 200)
    with pytest.raises(ValueError, match="workload"):
        partition_heightfield_faces(
            vertices=[list(p) for p in slab.vertices],
            triangles=[list(f) for f in slab.triangles],
            front_face_indices=[0, 1],
            back_face_indices=[2, 3],
            patch_vertices=[[-1.0, -0.5], [0.2, -0.5], [0.2, 0.5], [-1.0, 0.5]],
            patch_triangles=[[0, 1, 2], [0, 2, 3]],
        )
