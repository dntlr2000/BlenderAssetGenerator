"""Independent folded-wall, signed-frame, depth-extremum and pixel predicates."""

import itertools
import random
from fractions import Fraction

import pytest

from codex_blender_modeler.qa import reference_occupancy as occupancy
from codex_blender_modeler.structural_geometry import owner_relief as relief


def box_with_folded_side(fold):
    """Build a unit slab directly, optionally fan one vertical side through an external point."""
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 1.0),
        (0.0, 0.0, 1.0),
        (0.0, 1.0, 0.0),
        (1.0, 1.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.0, 1.0, 1.0),
    ]
    triangles = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6)]
    for i in range(4):
        j = (i + 1) % 4
        if fold and i == 3:
            # Boundary order 3,7,4,0, with a coplanar fan center outside the side.
            vertices.append((0.0, 2.0, 0.5))
            triangles.extend([(3, 7, 8), (7, 4, 8), (4, 0, 8), (0, 3, 8)])
        else:
            triangles.extend([(i, i + 4, j + 4), (i, j + 4, j)])
    return dict(
        vertices=vertices,
        triangles=triangles,
        front_face_indices=[0, 1],
        back_face_indices=[2, 3],
    )


def plane(depth):
    """Declare an independent unit square graph in world coordinates."""
    return [(0.0, depth, 0.0), (1.0, depth, 0.0), (1.0, depth, 1.0), (0.0, depth, 1.0)]


def attachment():
    """Use exactly representable positive contact and material thickness."""
    return {
        "lower_vertices": plane(0.125),
        "lower_triangles": [(0, 1, 2), (0, 2, 3)],
        "upper_vertices": plane(-0.25),
        "upper_triangles": [(0, 1, 2), (0, 2, 3)],
        "owner_front_vertices": plane(0.0),
        "owner_front_triangles": [(0, 1, 2), (0, 2, 3)],
        "owner_back_vertices": plane(0.5),
        "owner_back_triangles": [(0, 1, 2), (0, 2, 3)],
        "minimum_embed": 0.0625,
        "maximum_embed": 0.1875,
        "minimum_remaining_thickness": 0.25,
        "minimum_relief_height": 0.125,
    }


@pytest.mark.parametrize(
    "graph,depth", [("owner_front", 0.25), ("owner_back", 0.25), ("upper", 0.125)]
)
def test_internal_depth_extremum_fails_despite_all_outer_corners_passing(graph, depth):
    """A graph extremum strictly inside the footprint must survive overlay and fail its bound."""
    data = attachment()
    data[graph + "_vertices"].append((0.5, depth, 0.5))
    data[graph + "_triangles"] = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    result = relief.inspect_attachment(**data)
    assert result["status"] == "failed" and result["violations"]
    assert not any(result["uncovered_polygons"].values())


def test_all_signed_axis_frames_on_independent_closed_box():
    """Check the whole-solid orientation restriction under every signed axis permutation."""
    base = box_with_folded_side(False)
    outcomes = []
    # The independent canonical box graph frame is (X,Z,Y).
    canonical = [(x, z, y) for x, y, z in base["vertices"]]
    for axes in itertools.permutations(range(3)):
        parity = (-1) ** sum(axes[i] > axes[j] for i in range(3) for j in range(i + 1, 3))
        for signs in itertools.product((-1, 1), repeat=3):
            vertices = []
            for p in canonical:
                v = [0.0, 0.0, 0.0]
                for k in range(3):
                    v[axes[k]] = p[k] * signs[k]
                vertices.append(tuple(v))
            # Base mapping swaps Y/Z, so compare the new signed determinant to -1.
            flip = parity * signs[0] * signs[1] * signs[2] != -1
            faces = [f[::-1] if flip else f for f in base["triangles"]]
            result = relief.verify_height_field_solid(
                **{**base, "vertices": vertices, "triangles": faces},
                frame=(axes, signs),
            )
            outcomes.append((axes, signs, result))
    assert all(r["passed"] is True for _, _, r in outcomes), outcomes


@pytest.mark.parametrize("outside", [True, False])
def test_topologically_closed_but_overlapping_vertical_side_is_unverified(outside):
    """Both escaped and entirely in-bounds folded triangulations are not embedded solids."""
    data = box_with_folded_side(outside)
    if not outside:
        data["vertices"].append((0.0, 0.25, 0.25))
        # The point is inside the side rectangle, but outside triangle (3,7,4).
        data["triangles"][10:11] = [(3, 7, 8), (7, 4, 8), (4, 3, 8)]
    result = relief.verify_height_field_solid(**data)
    assert result["status"] == "unverified" and not result["owner_volume_verified"], result


def test_disconnected_outer_components_do_not_count_as_one_owner():
    """A second outward solid is refused without relying on cavity winding or omitted roles."""
    first = box_with_folded_side(False)
    second = box_with_folded_side(False)
    first["vertices"] += [(x + 2, y, z) for x, y, z in second["vertices"]]
    first["triangles"] += [tuple(i + 8 for i in f) for f in second["triangles"]]
    first["front_face_indices"] += [12, 13]
    first["back_face_indices"] += [14, 15]
    assert relief.verify_height_field_solid(**first)["status"] == "unverified"


def twice_area(a, b, c):
    """Compute independent absolute shoelace area for a triangle."""
    return abs(a[0] * b[1] + b[0] * c[1] + c[0] * a[1] - a[0] * c[1] - b[0] * a[1] - c[0] * b[1])


@pytest.mark.parametrize("resolution", [(13, 9), (9, 13), (11, 11)])
def test_pixel_occupancy_against_independent_world_area_oracle(resolution):
    """Compare literal geometry to inverse Blender AUTO pixel coordinates and area containment."""
    rng = random.Random(49091)
    w, h = resolution
    scale, cx, cz = Fraction(8), Fraction(3, 4), Fraction(-1, 2)
    for _ in range(20):
        vertices = [
            (
                rng.randrange(-16, 17) / 4,
                rng.randrange(-4, 5) / 4,
                rng.randrange(-16, 17) / 4,
            )
            for _ in range(3)
        ]
        tri = [(Fraction(x), Fraction(z)) for x, _, z in vertices]
        whole = twice_area(*tri)
        if not whole:
            continue
        image, _ = occupancy.rasterize_orthographic_occupancy(
            vertices,
            [(0, 1, 2)],
            resolution=resolution,
            ortho_scale=float(scale),
            center_x=float(cx),
            center_z=float(cz),
        )
        expected = []
        for y in range(h):
            for x in range(w):
                p = (
                    cx + (Fraction(2 * x + 1 - w, 2)) * scale / max(w, h),
                    cz - (Fraction(2 * y + 1 - h, 2)) * scale / max(w, h),
                )
                inside = sum(twice_area(p, tri[i], tri[(i + 1) % 3]) for i in range(3)) == whole
                expected.append(255 if inside else 0)
        assert image.tobytes() == bytes(expected), {
            "resolution": resolution,
            "vertices": vertices,
        }


def test_hostile_numeric_and_container_subclasses_are_never_coerced():
    """Guard pure geometry APIs against user-defined traversal and numeric conversion."""

    class Trap(float):
        def as_integer_ratio(self):
            raise AssertionError("must not coerce float subclass")

    class TrapList(list):
        def __iter__(self):
            raise AssertionError("must not iterate list subclass")

    data = attachment()
    data["minimum_embed"] = Trap(0.0625)
    assert relief.inspect_attachment(**data)["status"] == "unverified"
    data = attachment()
    data["lower_vertices"] = TrapList(data["lower_vertices"])
    assert relief.inspect_attachment(**data)["status"] == "unverified"
