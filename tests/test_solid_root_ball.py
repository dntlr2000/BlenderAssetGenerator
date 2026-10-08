"""Counterexamples for the experimental local-ball certificate, not native integration tests."""

import math
from fractions import Fraction as F

import pytest

from codex_blender_modeler.structural_geometry import solid_root_ball as r


def box(lo=(-1, -1, -1), hi=(1, 1, 1)):
    """Return an outward twelve-triangle cube or rectangular box."""
    x, y, z = lo
    X, Y, Z = hi
    return [
        [x, y, z],
        [X, y, z],
        [X, Y, z],
        [x, Y, z],
        [x, y, Z],
        [X, y, Z],
        [X, Y, Z],
        [x, Y, Z],
    ], [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ]


def torus():
    """Return one connected genus-one boundary with a real central cavity."""
    n, m = 12, 8
    v = []
    t = []
    for i in range(n):
        a = 2 * math.pi * i / n
        for j in range(m):
            b = 2 * math.pi * j / m
            v.append(
                [
                    (2 + 0.6 * math.cos(b)) * math.cos(a),
                    (2 + 0.6 * math.cos(b)) * math.sin(a),
                    0.6 * math.sin(b),
                ]
            )
    for i in range(n):
        for j in range(m):
            a = i * m + j
            b = ((i + 1) % n) * m + j
            c = ((i + 1) % n) * m + (j + 1) % m
            d = i * m + (j + 1) % m
            t.extend([[a, b, c], [a, c, d]])
    return v, t


@pytest.fixture(scope="module")
def cube():
    """Reuse one fully prepared exact solid."""
    return r.prepare_solid(*box())


@pytest.fixture(scope="module")
def donut():
    """Reuse one prepared torus for material/cavity cases."""
    return r.prepare_solid(*torus())


def test_contained_ball(cube):
    """A centered nontrivial ball has a conservative boundary certificate."""
    out = r.certify_ball(cube, [0, 0, 0], 0.25, [[-0.5] * 3, [0.5] * 3])
    assert out["status"] == "certified_local_ball_only"
    assert out["attained_minimum_claimed"] is False


def test_whole_ball_region(cube):
    """A center inside a narrow root box does not authorize a ball spilling outside it."""
    with pytest.raises(r.Unverified, match="entire ball"):
        r.certify_ball(cube, [0, 0, 0], 0.25, [[-0.1] * 3, [0.1] * 3])


@pytest.mark.parametrize("p,radius", [([0.95, 0, 0], 0.1), ([2, 0, 0], 0.1), ([1, 0, 0], 0.1)])
def test_boundary_crossing_outside_tangency(cube, p, radius):
    """Boundary proximity, outside material and tangent centers fail."""
    with pytest.raises(r.Unverified):
        r.certify_ball(cube, p, radius, [[-3] * 3, [3] * 3])


@pytest.mark.parametrize("radius", [0, -0.1, float("nan"), float("inf"), True, "0.1"])
def test_invalid_radius(cube, radius):
    """No zero, nonfinite or coerced radius can certify overlap."""
    with pytest.raises(r.Unverified):
        r.certify_ball(cube, [0, 0, 0], radius, [[-3] * 3, [3] * 3])


def test_cavity_rejected(donut):
    """A ball in a torus hole clears all surfaces but lies outside solid material."""
    with pytest.raises(r.Unverified, match="cavity"):
        r.certify_ball(donut, [0, 0, 0], 0.1, [[-0.5] * 3, [0.5] * 3])


def test_torus_wall_certified(donut):
    """A ball in actual torus material can pass without a convex-hull assumption."""
    assert (
        r.certify_ball(donut, [2, 0, 0], 0.1, [[1.8, -0.2, -0.2], [2.2, 0.2, 0.2]])["status"]
        == "certified_local_ball_only"
    )


def test_thin_wall_rejected():
    """A nonzero but undersized material thickness cannot accept the declared radius."""
    solid = r.prepare_solid(*box((-1, -1, -0.015), (1, 1, 0.015)))
    with pytest.raises(r.Unverified):
        r.certify_ball(solid, [0, 0, 0], 0.02, [[-1] * 3, [1] * 3])


def test_ambiguous_ray_retries():
    """The first exact ray hits a box corner and must not be counted casually."""
    solid = r.prepare_solid(*box((-1, -3, -11), (1, 3, 11)))
    out = r.certify_ball(solid, [0, 0, 0], 0.1, [[-1] * 3, [1] * 3])
    assert out["ray_direction_index"] > 1


def test_budget_exhaustion(cube):
    """An exhausted predicate budget cannot produce a partial pass."""
    with pytest.raises(r.Unverified, match="budget"):
        r.certify_ball(cube, [0, 0, 0], 0.1, [[-1] * 3, [1] * 3], r.Budget(2))


def test_distance_voronoi_regions():
    """Face, segment and vertex nearest points agree with exact rational answers."""
    t = tuple(r.point(p) for p in [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    assert r.triangle_distance2(r.point([0.25, 0.25, 1]), t) == 1
    assert r.triangle_distance2(r.point([2, 0, 0]), t) == 1
    assert r.triangle_distance2(r.point([2, 2, 0]), t) == F(9, 2)


@pytest.mark.parametrize(
    "kind", ["disconnected", "nested", "inward", "duplicate", "missing", "self_cross"]
)
def test_invalid_boundaries_rejected(kind):
    """Full boundary integrity is required before any containment certificate."""
    v, t = box()
    if kind in ("disconnected", "nested"):
        vv, tt = (
            box((3, 3, 3), (4, 4, 4)) if kind == "disconnected" else box((-0.5,) * 3, (0.5,) * 3)
        )
        t += [[i + 8 for i in q[::-1] if True] for q in tt]
        v += vv
    elif kind == "inward":
        t = [q[::-1] for q in t]
    elif kind == "duplicate":
        t.append(t[0])
    elif kind == "missing":
        t.pop()
    else:
        v[6] = [-2, -2, -2]
    with pytest.raises(ValueError):
        r.prepare_solid(v, t)


def test_graph_scope():
    """All required semantic solids must be connected by declared distinct-identity edges."""
    assert r.connected_required_graph(["a", "b", "c"], [["a", "b"], ["b", "c"]])
    for edges in [[["a", "b"]], [["a", "a"], ["a", "b"]], [["a", "x"]]]:
        with pytest.raises(r.Unverified):
            r.connected_required_graph(["a", "b", "c"], edges)


def test_two_solids_overlap_and_tangent_failure():
    """Both complete solids must contain the same positive-radius ball."""
    a = r.prepare_solid(*box((-1, -1, -1), (0.2, 1, 1)))
    b = r.prepare_solid(*box((-0.2, -1, -1), (1, 1, 1)))
    for solid in [a, b]:
        r.certify_ball(solid, [0, 0, 0], 0.1, [[-0.15] * 3, [0.15] * 3])
    tangent = r.prepare_solid(*box((0, -1, -1), (1, 1, 1)))
    with pytest.raises(r.Unverified):
        r.certify_ball(tangent, [0, 0, 0], 0.1, [[-0.15] * 3, [0.15] * 3])


def test_all_ray_directions_ambiguous_on_boundary(cube):
    """The bounded retry loop itself rejects a point on the surface without an epsilon vote."""
    with pytest.raises(r.Unverified, match="all deterministic"):
        r.inside(cube, r.point([1, 0, 0]), r.Budget())


def test_binary32_thickness_loss_does_not_borrow_source_pass():
    """A source ball exactly fitting a thin wall fails after real binary32 inward rounding."""
    import struct

    vertices, triangles = box((-1, -1, 0), (1, 1, 0.02))
    source = r.prepare_solid(vertices, triangles)
    r.certify_ball(source, [0, 0, 0.01], 0.01, [[-0.1, -0.1, 0], [0.1, 0.1, 0.02]])
    native_vertices = [[struct.unpack("f", struct.pack("f", x))[0] for x in p] for p in vertices]
    predicted = r.prepare_solid(native_vertices, triangles)
    with pytest.raises(r.Unverified, match="boundary"):
        r.certify_ball(predicted, [0, 0, 0.01], 0.01, [[-0.1, -0.1, 0], [0.1, 0.1, 0.02]])


def test_thin_neck_and_irrelevant_bulb_overlap():
    """A larger ball in a connected bulb cannot replace the declared thin-neck joint."""
    vertices = []
    sections = [(-2, 0.5), (-1, 0.5), (-0.5, 0.04), (0.5, 0.04), (1, 0.5), (2, 0.5)]
    for x, radius in sections:
        vertices.extend(
            [[x, -radius, -radius], [x, radius, -radius], [x, radius, radius], [x, -radius, radius]]
        )
    triangles = []
    for i in range(len(sections) - 1):
        for j in range(4):
            a = i * 4 + j
            b = i * 4 + (j + 1) % 4
            c = b + 4
            d = a + 4
            triangles.extend([[a, b, c], [a, c, d]])
    triangles.extend([[0, 2, 1], [0, 3, 2], [20, 21, 22], [20, 22, 23]])
    # The chosen sweep winding is normalized before the strict complete-boundary check.
    volume = sum(
        r.dot(r.point(vertices[a]), r.cross(r.point(vertices[b]), r.point(vertices[c])))
        for a, b, c in triangles
    )
    if volume < 0:
        triangles = [t[::-1] for t in triangles]
    solid = r.prepare_solid(vertices, triangles)
    root = [[-0.2, -0.2, -0.2], [0.2, 0.2, 0.2]]
    with pytest.raises(r.Unverified, match="boundary"):
        r.certify_ball(solid, [0, 0, 0], 0.05, root)
    with pytest.raises(r.Unverified, match="entire ball"):
        r.certify_ball(solid, [1.5, 0, 0], 0.1, root)
    assert (
        r.certify_ball(solid, [1.5, 0, 0], 0.1, [[1.2, -0.3, -0.3], [1.8, 0.3, 0.3]])["status"]
        == "certified_local_ball_only"
    )


def test_bvh_pairs_equal_legacy_sweep_and_bruteforce():
    """Random, degenerate and exactly touching boxes preserve the full unordered pair set."""
    import random

    from codex_blender_modeler.structural_geometry.profiled_relief import _embedding_candidate_pairs

    rng = random.Random(98213)
    for size in [0, 1, 2, 4, 5, 16, 37, 100]:
        for _ in range(12):
            bounds = []
            for _ in range(size):
                low = tuple(float(rng.randint(-8, 8)) for _ in range(3))
                high = tuple(low[a] + rng.choice([0.0, 0.0, 0.5, 1.0, 4.0]) for a in range(3))
                bounds.append((low, high))
            expected = {
                (a, b)
                for a in range(size)
                for b in range(a + 1, size)
                if all(
                    bounds[a][1][k] >= bounds[b][0][k] and bounds[b][1][k] >= bounds[a][0][k]
                    for k in range(3)
                )
            }
            actual = list(r.embedding_candidate_pairs(bounds, r.Budget()))
            legacy = {tuple(sorted(pair)) for pair in _embedding_candidate_pairs(bounds)}
            assert len(actual) == len(set(actual))
            assert set(actual) == expected == legacy


def test_embedding_budget_is_aggregate_and_counts_construction():
    """Preparing another solid cannot reset accumulated exact broad-phase work."""
    budget = r.Budget()
    r.prepare_solid(*box(), budget)
    assert budget.embedding_scans[0] > 0
    budget.embedding_scans[0] = 1_000_000
    with pytest.raises(r.Unverified, match="budget"):
        r.prepare_solid(*box(), budget)
