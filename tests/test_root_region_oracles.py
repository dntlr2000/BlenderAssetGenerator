"""Independent region-boundary, affine interval and whole-domain coverage oracles."""

import copy
import itertools
import math
from collections import Counter
from fractions import Fraction as Q

import pytest
from test_surface_attachment_overlay_oracles import oracle_intersection, polygon_area

from codex_blender_modeler.structural_geometry import owner_relief as m
from codex_blender_modeler.structural_geometry import root_region as candidate


def graph(depth, bounds=(-2.0, 2.0, -2.0, 2.0), frame=((0, 2, 1), (1, 1, 1))):
    """Create a literal complete affine square graph in a declared signed frame."""
    left, right, bottom, top = bounds
    vertices = []
    for u, v in ((left, bottom), (right, bottom), (right, top), (left, top)):
        values = (u, v, depth(u, v))
        point = [0.0, 0.0, 0.0]
        for axis, sign, value in zip(*frame, values, strict=False):
            point[axis] = sign * value
        vertices.append(point)
    return vertices, [[0, 1, 2], [0, 2, 3]]


def arguments(polygon, frame=((0, 2, 1), (1, 1, 1)), depths=None, bounds=(-2.0, 2.0, -2.0, 2.0)):
    """Assemble independently specified child and owner intervals from four full graphs."""
    if depths is None:
        depths = (lambda u, v: -0.5, lambda u, v: 0.75, lambda u, v: 0.0, lambda u, v: 1.0)
    result = {"region_polygon": polygon, "minimum_overlap": 0.5, "frame": frame}
    for prefix, depth in zip(("upper", "lower", "owner_front", "owner_back"), depths, strict=True):
        vertices, triangles = graph(depth, bounds, frame)
        result[prefix + "_vertices"] = vertices
        result[prefix + "_triangles"] = triangles
    return result


def chains(polygons):
    """Represent directed boundary chains as exact intervals on normalized supporting lines."""
    result = Counter()
    for polygon in polygons:
        for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=False):
            aa, bb = a[1] - b[1], b[0] - a[0]
            cc = -(aa * a[0] + bb * a[1])
            scale = aa or bb
            line = (aa / scale, bb / scale, cc / scale)
            axis = 0 if a[0] != b[0] else 1
            result[(line, a[axis])] += 1
            result[(line, b[axis])] -= 1
    return {key: value for key, value in result.items() if value}


@pytest.mark.parametrize(
    "polygon",
    [
        [
            [0.0, 0.0],
            [3.0, 0.0],
            [3.0, 3.0],
            [2.0, 3.0],
            [2.0, 1.0],
            [1.0, 1.0],
            [1.0, 3.0],
            [0.0, 3.0],
        ],
        [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [2.0, 1.0], [1.0, 1.0], [1.0, 2.0], [0.0, 2.0]],
        [[-0.713, -0.237], [0.619, -0.331], [0.733, 0.283], [0.137, 0.119], [-0.493, 0.827]],
    ],
)
def test_polygon_cells_match_independent_boundary_and_intersection_oracles(polygon):
    """Nonconvex and collinear boundaries retain their exact compact planar union."""
    for points in (polygon, polygon[::-1]):
        cells, area = candidate.polygon_cells(points, m.Budget())
        expected = [tuple(Q(c) for c in point) for point in polygon]
        assert chains(cells) == chains([expected])
        assert area == sum(polygon_area(t) for t in cells)
        for i, first in enumerate(cells):
            assert polygon_area(first) > 0
            for second in cells[i + 1 :]:
                assert polygon_area(oracle_intersection(first, second)) == 0


def test_nonconvex_region_excludes_notch_without_ignoring_real_corners():
    """The minimum belongs to the actual L region, not its bounding rectangle."""
    polygon = [[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [1.0, 1.0], [1.0, 2.0], [0.0, 2.0]]
    args = arguments(
        polygon,
        depths=(lambda u, v: -10.0, lambda u, v: 4.0 - u - v, lambda u, v: 0.0, lambda u, v: 10.0),
        bounds=(-0.5, 2.5, -0.5, 2.5),
    )
    args["minimum_overlap"] = 1.0
    result = candidate.inspect_root_region(**args)
    assert result["passed"] and Q(result["region_area_exact"]) == 3
    assert Q(result["minimum_overlap_m_exact"]) == 1
    args["minimum_overlap"] = math.nextafter(1.0, math.inf)
    assert candidate.inspect_root_region(**args)["status"] == "failed"


def test_concave_overlap_has_interior_maximum_without_a_sampled_max_claim():
    """Crossing depth intervals have an interior overlap maximum and exact boundary minimum."""
    polygon = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]
    result = candidate.inspect_root_region(
        **arguments(
            polygon,
            depths=(lambda u, v: u, lambda u, v: u + 1.0, lambda u, v: 0.0, lambda u, v: 1.0),
        )
    )
    assert result["passed"] and Q(result["minimum_overlap_m_exact"]) == Q(1, 2)
    assert Q(result["maximum_overlap_m_upper_bound"]) >= 1
    assert "maximum_overlap_m_exact" not in result


@pytest.mark.parametrize("surface", ["upper", "lower", "owner_front", "owner_back"])
def test_tiny_missing_domain_cannot_be_clipped_out_of_the_region(surface):
    """Each of the four complete graph domains must cover the whole requested region."""
    polygon = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]
    args = arguments(polygon)
    gap = 2.0**-40
    full_vertices = args[surface + "_vertices"]
    depth = full_vertices[0][1]
    vertices = []
    triangles = []
    for left, right in [(-2.0, 0.125), (0.125 + gap, 2.0)]:
        local, faces = graph(lambda u, v, d=depth: d, (left, right, -2.0, 2.0))
        offset = len(vertices)
        vertices.extend(local)
        triangles.extend([[i + offset for i in f] for f in faces])
    args[surface + "_vertices"] = vertices
    args[surface + "_triangles"] = triangles
    before = copy.deepcopy(args)
    result = candidate.inspect_root_region(**args)
    assert result["status"] == "failed" and result["passed"] is False
    assert Q(result["covered_area_exact"]) < Q(result["region_area_exact"])
    assert args == before


def test_true_interior_hole_is_not_silently_subtracted_from_required_region():
    """A valid multiply-connected support cannot erase a hole from a simple requested square."""
    args = arguments([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
    vertices = []
    triangles = []
    for bounds in [
        (-2.0, -0.25, -2.0, 2.0),
        (0.25, 2.0, -2.0, 2.0),
        (-0.25, 0.25, -2.0, -0.25),
        (-0.25, 0.25, 0.25, 2.0),
    ]:
        local, faces = graph(lambda u, v: 0.0, bounds)
        offset = len(vertices)
        vertices.extend(local)
        triangles.extend([[i + offset for i in f] for f in faces])
    args["owner_front_vertices"] = vertices
    args["owner_front_triangles"] = triangles
    result = candidate.inspect_root_region(**args)
    assert result["status"] == "failed" and Q(result["covered_area_exact"]) == Q(15, 4)


@pytest.mark.parametrize(
    "polygon",
    [
        [],
        [[0.0, 0.0], [1.0, 0.0]],
        [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]],
        [[0.0, 0.0], [1.0, 1.0], [0.0, 1.0], [1.0, 0.0]],
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]],
        [[0.0, 0.0], [1.0, 0.0], [0.5, 0.0], [1.0, 1.0], [0.0, 1.0]],
        [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [1.0, 0.0], [0.0, 2.0]],
        [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]], [[0.2, 0.2], [0.3, 0.2], [0.3, 0.3]]],
        [[0.0, 0.0], [math.inf, 0.0], [0.0, 1.0]],
    ],
)
def test_malformed_or_multi_ring_regions_remain_unverified(polygon):
    """Invalid intent is distinct from a well-formed region with failed geometric coverage."""
    result = candidate.inspect_root_region(**arguments(polygon))
    assert result["status"] == "unverified" and result["passed"] is None


@pytest.mark.parametrize("axes", list(itertools.permutations(range(3))))
def test_signed_frames_preserve_region_meaning(axes):
    """Every signed-axis frame applies to actual geometry and the unchanged UV polygon."""
    for signs in itertools.product((-1, 1), repeat=3):
        result = candidate.inspect_root_region(
            **arguments([[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]], (axes, signs))
        )
        assert result["passed"] and Q(result["minimum_overlap_m_exact"]) == Q(3, 4)


def test_wrong_layer_and_zero_contact_fail_without_exposure_requirement():
    """Projected coincidence cannot stand in for positive actual depth overlap."""
    for back in (0.0, -(2.0**-40)):
        result = candidate.inspect_root_region(
            **arguments(
                [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]],
                depths=(
                    lambda u, v: -1.0,
                    lambda u, v, d=back: d,
                    lambda u, v: 0.0,
                    lambda u, v: 1.0,
                ),
            )
        )
        assert result["status"] == "failed"


def test_wrong_frame_and_empty_clipped_region_cannot_pass():
    """A collapsed projection is unsupported, while a wholly uncovered valid region fails."""
    args = arguments([[3.0, 3.0], [4.0, 3.0], [4.0, 4.0], [3.0, 4.0]])
    result = candidate.inspect_root_region(**args)
    assert result["status"] == "failed" and Q(result["covered_area_exact"]) == 0
    args["region_polygon"] = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]
    args["frame"] = ((0, 1, 2), (1, 1, 1))
    assert candidate.inspect_root_region(**args)["status"] == "unverified"


def test_immutable_binary64_region_refuses_binary32_boundary_shrink():
    """Storage rounding may lose a positive sliver even with unchanged healthy depth overlap."""
    right = math.nextafter(1.0, math.inf)
    polygon = [[0.0, 0.0], [right, 0.0], [right, 1.0], [0.0, 1.0]]
    args = arguments(polygon)
    for prefix, depth in [("upper", -0.5), ("lower", 0.75)]:
        v, f = graph(lambda u, v, d=depth: d, (0.0, right, 0.0, 1.0))
        args[prefix + "_vertices"] = v
        args[prefix + "_triangles"] = f
    assert candidate.inspect_root_region(**args)["passed"]
    for key in list(args):
        if key.endswith("_vertices"):
            args[key] = m.float32(args[key])
    result = candidate.inspect_root_region(**args)
    assert result["status"] == "failed"
    assert Q(result["region_area_exact"]) - Q(result["covered_area_exact"]) == Q(right) - 1
    assert Q(result["minimum_overlap_m_exact"]) == Q(3, 4)


@pytest.mark.parametrize("location", ["outer", "point", "coordinate"])
def test_strict_polygon_admission_precedes_subclass_behavior(location):
    """Reject caller-defined traversal or numeric coercion before geometry processing."""

    class TrapList(list):
        """Raise if strict list admission is bypassed."""

        def __iter__(self):
            raise AssertionError("custom polygon traversal")

    class TrapFloat(float):
        """Reject a numeric subclass regardless of its apparently valid value."""

    polygon = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]
    if location == "outer":
        polygon = TrapList(polygon)
    elif location == "point":
        polygon[0] = TrapList(polygon[0])
    else:
        polygon[0][0] = TrapFloat(-0.5)
    assert candidate.inspect_root_region(**arguments(polygon))["status"] == "unverified"


def test_region_limit_and_exhausted_work_return_no_geometric_pass(monkeypatch):
    """Unsupported region size and exhausted accounting remain unverified evidence."""
    oversized = [[float(i), float(i * i)] for i in range(257)]
    assert candidate.inspect_root_region(**arguments(oversized))["status"] == "unverified"
    monkeypatch.setattr(m, "MAX_EDGE_TESTS", 0)
    result = candidate.inspect_root_region(
        **arguments([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    )
    assert result["status"] == "unverified" and result["passed"] is None
    assert "workload" in result["reason"]


def test_legacy_partitioned_l_region_and_direct_clipping_agree_exactly():
    """Compare with the unchanged legacy selected-face proof on literal representable geometry."""
    from codex_blender_modeler.structural_geometry.contour_relief import build_contour_prism
    from codex_blender_modeler.structural_geometry.partition_heightfield import (
        partition_heightfield_faces,
    )

    shell = build_contour_prism([(-2.0, -2.0), (2.0, -2.0), (2.0, 2.0), (-2.0, 2.0)], depth=2.0)
    vertices = [list(v) for v in shell.vertices]
    faces = [list(f) for f in shell.triangles]
    polygon = [[-1.0, -1.0], [1.0, -1.0], [1.0, 0.0], [0.0, 0.0], [0.0, 1.0], [-1.0, 1.0]]
    patch_triangles = [[0, 1, 2], [0, 2, 3], [0, 3, 5], [3, 4, 5]]
    partitioned = partition_heightfield_faces(
        vertices=vertices,
        triangles=faces,
        front_face_indices=[0, 1],
        back_face_indices=[2, 3],
        patch_vertices=polygon,
        patch_triangles=patch_triangles,
    )
    roles = partitioned["face_roles"]
    actual = partitioned["triangles"]
    part = partitioned["vertices"]
    legacy = m.inspect_inserted_root(
        lower_vertices=part,
        lower_triangles=[actual[i] for i in roles["patch_back"]],
        upper_vertices=part,
        upper_triangles=[actual[i] for i in roles["patch_front"]],
        owner_front_vertices=vertices,
        owner_front_triangles=faces[:2],
        owner_back_vertices=vertices,
        owner_back_triangles=faces[2:4],
        minimum_overlap=0.5,
    )
    direct = candidate.inspect_root_region(
        region_polygon=polygon,
        lower_vertices=vertices,
        lower_triangles=faces[2:4],
        upper_vertices=vertices,
        upper_triangles=faces[:2],
        owner_front_vertices=vertices,
        owner_front_triangles=faces[:2],
        owner_back_vertices=vertices,
        owner_back_triangles=faces[2:4],
        minimum_overlap=0.5,
    )
    assert legacy["passed"] and direct["passed"]
    assert legacy["minimum_overlap_m_exact"] == direct["minimum_overlap_m_exact"] == "2"
    assert (
        Q(direct["covered_area_exact"]) == Q(partitioned["diagnostics"]["selected_patch_area"]) == 3
    )
