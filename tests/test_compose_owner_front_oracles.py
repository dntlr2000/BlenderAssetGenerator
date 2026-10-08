"""Independent analytic profile sum and complete-footprint oracles."""

import math
from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import owner_relief
from codex_blender_modeler.structural_geometry.compose_owner_front import (
    compose_owner_front,
)
from codex_blender_modeler.structural_geometry.contour_relief import build_contour_prism


def pyramid(name, cx, cz, radius, height):
    """Give a square pyramid independently described by a Chebyshev-distance height function."""
    return {
        "id": name,
        "vertices": [
            [cx - radius, cz - radius, 0.0],
            [cx + radius, cz - radius, 0.0],
            [cx + radius, cz + radius, 0.0],
            [cx - radius, cz + radius, 0.0],
            [cx, cz, height],
        ],
        "triangles": [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]],
    }


def literal_height(x, z, description):
    """Evaluate a pyramid without consulting any generated or input triangulation."""
    cx, cz, r, h = description
    return h * max(0.0, 1.0 - max(abs(x - cx) / r, abs(z - cz) / r))


def compose(descriptions, frame=((0, 2, 1), (1, 1, 1))):
    """Transform an analytic tilted slab into a signed frame, with exact dyadic profile
    definitions."""
    slab = build_contour_prism([(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)], depth=2.0)
    axes, signs = frame
    vertices = []
    for x, y, z in slab.vertices:
        value = [0.0, 0.0, 0.0]
        for axis, sign, c in zip(axes, signs, (x, z, y + 0.25 * x - 0.125 * z), strict=False):
            value[axis] = sign * c
        vertices.append(value)
    faces = [list(f) for f in slab.triangles]
    determinant = (
        -((-1) ** sum(axes[i] > axes[j] for i in range(3) for j in range(i + 1, 3)))
        * signs[0]
        * signs[1]
        * signs[2]
    )
    if determinant < 0:
        faces = [f[::-1] for f in faces]
    profiles = [pyramid("p" + str(i), *d) for i, d in enumerate(descriptions)]
    return compose_owner_front(
        vertices=vertices,
        triangles=faces,
        front_face_indices=[0, 1],
        back_face_indices=[2, 3],
        profiles=profiles,
        maximum_profile_height=0.5,
        minimum_remaining_thickness=1.0,
        frame=frame,
    )


@pytest.mark.parametrize("frame", [((0, 2, 1), (1, 1, 1)), ((1, 0, 2), (-1, 1, -1))])
@pytest.mark.parametrize(
    "descriptions",
    [
        [(-0.25, 0.0, 0.5, 0.25), (0.25, 0.0, 0.5, 0.125)],
        [(0.0, 0.0, 0.5, 0.25), (0.0, 0.0, 0.25, 0.125)],
        [(-0.5, 0.0, 0.5, 0.25), (0.5, 0.0, 0.5, 0.125)],
    ],
)
def test_every_emitted_cap_point_matches_analytic_profile_sum_and_each_whole_footprint(
    descriptions, frame
):
    """Overlapping, nested and seam-touching profiles preserve exact pointwise sums and complete
    feature areas."""
    result = compose(descriptions, frame)
    axes, signs = frame
    vv = [tuple(p[a] * s for a, s in zip(axes, signs, strict=False)) for p in result["vertices"]]
    faces = result["triangles"]
    roles = result["face_roles"]
    for role, front in [("front", True), ("back", False)]:
        for fi in roles[role]:
            points = [vv[i] for i in faces[fi]]
            # The barycentre check also rejects a triangle bridging an unretained crease.
            for x, z, d in points + [tuple(sum(p[k] for p in points) / 3 for k in range(3))]:
                expected = (-1.0 if front else 1.0) + 0.25 * x - 0.125 * z
                if front:
                    expected -= sum(literal_height(x, z, item) for item in descriptions)
                assert d == pytest.approx(expected, abs=3e-15)
    for i, (_, _, radius, _) in enumerate(descriptions):
        area = Q(0)
        for fi in result["feature_face_groups"]["p" + str(i)]:
            (x0, z0, _), (x1, z1, _), (x2, z2, _) = map(
                lambda j: tuple(Q(c) for c in vv[j]), faces[fi]
            )
            area += abs((x1 - x0) * (z2 - z0) - (x2 - x0) * (z1 - z0)) / 2
        assert area == 4 * Q(radius) ** 2
    expected = 8.0 + sum(4 * r * r * h / 3 for _, _, r, h in descriptions)
    assert result["diagnostics"]["checks"]["binary64"]["volume"] == pytest.approx(
        expected, abs=1e-12
    )
    for cast in (lambda x: x, owner_relief.float32):
        proof = owner_relief.verify_height_field_solid(
            vertices=cast(result["vertices"]),
            triangles=faces,
            front_face_indices=roles["front"],
            back_face_indices=roles["back"],
            frame=frame,
        )
        assert proof["passed"], proof


def test_one_ulp_outside_profile_is_not_trimmed():
    """Even a vanishingly narrow zero-height edge extension must retain its complete declared
    area or fail."""
    with pytest.raises(ValueError, match="escapes"):
        compose([(math.nextafter(math.nextafter(0.5, 1.0), 1.0), 0.0, 0.5, 0.25)])


def test_profile_budget_refusal_does_not_return_partial_owner(monkeypatch):
    """Exhausted graph work must not return a partially composed first profile."""
    monkeypatch.setattr(owner_relief, "MAX_PAIR_SCANS", 30)
    with pytest.raises(ValueError):
        compose([(-0.25, 0.0, 0.5, 0.25), (0.25, 0.0, 0.5, 0.125)])
