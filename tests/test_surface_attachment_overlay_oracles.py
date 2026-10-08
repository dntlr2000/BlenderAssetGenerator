"""Independent non-clipping convex geometry and index completeness oracles."""

import math
import random
from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import owner_relief as current


def det(a, b):
    """Return a 2D vector determinant for the independent segment-intersection oracle."""
    return a[0] * b[1] - a[1] * b[0]


def minus(a, b):
    """Subtract a pair of exact vectors."""
    return tuple(x - y for x, y in zip(a, b, strict=False))


def hull(points):
    """Compute a convex hull from an unordered exact point set using monotone chains."""
    points = sorted(set(points))
    if len(points) <= 1:
        return points
    chains = []
    for ordered in (points, list(reversed(points))):
        chain = []
        for p in ordered:
            while len(chain) > 1 and det(minus(chain[-1], chain[-2]), minus(p, chain[-2])) <= 0:
                chain.pop()
            chain.append(p)
        chains.append(chain[:-1])
    return chains[0] + chains[1]


def polygon_area(poly):
    """Measure polygon area independently from the implementation's clipping routine."""
    return (
        abs(sum(det(a, b) for a, b in zip(poly, poly[1:] + poly[:1], strict=False))) / 2
        if len(poly) >= 3
        else Q(0)
    )


def inside(point, poly):
    """Include the closed boundary in exact convex membership."""
    return all(
        det(minus(b, a), minus(point, a)) >= 0
        for a, b in zip(poly, poly[1:] + poly[:1], strict=False)
    )


def oracle_intersection(first, second):
    """Intersect by collecting contained vertices and all segment crossings, then taking their
    hull."""
    points = [p for p in first if inside(p, second)] + [p for p in second if inside(p, first)]
    for a, b in zip(first, first[1:] + first[:1], strict=False):
        r = minus(b, a)
        for c, d in zip(second, second[1:] + second[:1], strict=False):
            s = minus(d, c)
            den = det(r, s)
            if not den:
                continue
            t = det(minus(c, a), s) / den
            u = det(minus(c, a), r) / den
            if 0 <= t <= 1 and 0 <= u <= 1:
                points.append(tuple(a[i] + t * r[i] for i in range(2)))
    return hull(points)


def test_random_convex_sat_intersection_and_subtraction_equivalence():
    """Check real area and complement area against a non-clipping exact oracle."""
    rng = random.Random(91534)
    completed = 0
    while completed < 80:
        first = hull([(Q(rng.randrange(-8, 9), 4), Q(rng.randrange(-8, 9), 4)) for _ in range(6)])
        second = hull([(Q(rng.randrange(-8, 9), 4), Q(rng.randrange(-8, 9), 4)) for _ in range(3)])
        if len(first) < 3 or len(second) != 3:
            continue
        expected = polygon_area(oracle_intersection(first, second))
        assert current.separated_in_area(first, second) == (expected == 0)
        for module in (current,):
            assert polygon_area(module.intersection(first, second, module.Budget())) == expected
            differences = module.subtract(first, second, module.Budget())
            assert sum(polygon_area(poly) for poly in differences) == polygon_area(first) - expected
        completed += 1


@pytest.mark.parametrize("offset", [0.0, math.nextafter(0.0, 1.0), math.nextafter(0.0, -1.0)])
def test_touching_or_one_ulp_diagonal_overlap(offset):
    """Retain strict positive overlap even when its width is one binary64 step."""
    # Complementary triangles share the x=z diagonal at offset0. Tiny shifts
    # create a real slit or positive overlap without changing their AABB overlap.
    first = [(Q(0), Q(0)), (Q(1), Q(0)), (Q(1), Q(1))]
    delta = Q(offset)
    second = [(Q(0), delta), (Q(1), Q(1) + delta), (Q(0), Q(1) + delta)]
    expected = polygon_area(oracle_intersection(first, second))
    result = current.intersection(first, second, current.Budget())
    assert polygon_area(result) == expected
    assert current.separated_in_area(first, second) == (expected == 0)


@pytest.mark.parametrize("depth_difference", [0.0, 0.125])
def test_touching_projected_seam_keeps_depth_continuity_check(depth_difference):
    """SAT may skip zero area, but cannot skip a discontinuous touching height-field seam."""
    vertices = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 1.0),
        (0.0, depth_difference, 0.0),
        (1.0, depth_difference, 1.0),
        (0.0, depth_difference, 1.0),
    ]
    faces = [(0, 1, 2), (3, 4, 5)]
    for module in (current,):
        if depth_difference:
            with pytest.raises(ValueError, match="discontinuous"):
                module.surface(vertices, faces, ((0, 2, 1), (1, 1, 1)), module.Budget())
        else:
            assert (
                len(module.surface(vertices, faces, ((0, 2, 1), (1, 1, 1)), module.Budget())) == 2
            )


def test_sweep_charges_retained_and_expired_active_entries(monkeypatch):
    """Work limits still refuse incomplete validation, even when all faces are disjoint."""
    vertices = []
    faces = []
    for i in range(4):
        n = len(vertices)
        x = float(i * 2)
        vertices.extend([(x, 0.0, 0.0), (x + 1, 0.0, 0.0), (x, 0.0, 1.0)])
        faces.append((n, n + 1, n + 2))
    budget = current.Budget()
    current.surface(vertices, faces, ((0, 2, 1), (1, 1, 1)), budget)
    assert budget.pair_scans > 0 and budget.clips == 0
    monkeypatch.setattr(current, "MAX_PAIR_SCANS", 1)
    with pytest.raises(ValueError, match="workload"):
        current.surface(vertices, faces, ((0, 2, 1), (1, 1, 1)), current.Budget())


def test_overlay_charges_remaining_witness_pair_scans(monkeypatch):
    """Internal witness scans must share the non-resetting broad-phase ceiling."""
    square = [(Q(0), Q(0)), (Q(1), Q(0)), (Q(1), Q(1)), (Q(0), Q(1))]
    support = []
    for x, z in [(1, 1), (5, 1), (1, 5), (5, 5)]:
        triangle = [(Q(x, 8), Q(z, 8)), (Q(x + 1, 8), Q(z, 8)), (Q(x, 8), Q(z + 1, 8))]
        support.append((triangle, [(a, b, Q(0)) for a, b in triangle]))
    monkeypatch.setattr(current, "MAX_PAIR_SCANS", 4)
    with pytest.raises(ValueError, match="workload"):
        current.overlay([(square, [])], support, current.Budget())


def rectangle(x, z, width, height):
    """Construct literal counterclockwise rectangular domains."""
    return [(x, z), (x + width, z), (x + width, z + height), (x, z + height)]


def test_index_candidates_equal_independent_strict_interval_intersections():
    """The hierarchy must include all and only positive-area AABB pairs, including tiny
    intervals."""
    rng = random.Random(71023)
    boxes = []
    for _ in range(100):
        x, z = [Q(rng.randrange(-32, 33), 16) for _ in range(2)]
        w, h = [Q(rng.randrange(1, 17), 32) for _ in range(2)]
        boxes.append(((x, x + w), (z, z + h)))
    boxes += [
        ((Q(0), Q(1, 2)), (Q(0), Q(1))),
        ((Q(1, 2) + Q(1, 2**53), Q(1)), (Q(0), Q(1))),
    ]
    budget = current.Budget()
    index = current.build_bounds_index(boxes, budget)
    queries = boxes[:] + [
        ((Q(1, 2), Q(1, 2) + Q(1, 2**53)), (Q(0), Q(1))),
        ((Q(-9), Q(9)), (Q(-9), Q(9))),
    ]
    for query in queries:
        expected = [
            i
            for i, b in enumerate(boxes)
            if all(max(b[k][0], query[k][0]) < min(b[k][1], query[k][1]) for k in range(2))
        ]
        assert current.query_bounds_index(index, boxes, query, budget) == expected


def test_query_exhaustion_never_returns_partial_candidates(monkeypatch):
    """Even a leaf-only query charges every candidate and refuses before returning a partial
    list."""
    boxes = [((Q(i), Q(i + 1)), (Q(0), Q(1))) for i in range(8)]
    index = current.build_bounds_index(boxes, current.Budget())
    monkeypatch.setattr(current, "MAX_PAIR_SCANS", 2)
    with pytest.raises(ValueError, match="workload"):
        current.query_bounds_index(index, boxes, ((Q(-1), Q(9)), (Q(-1), Q(2))), current.Budget())


def compare_partition(first, second):
    """Prove equal positive-area domains by exact pairwise intersection areas of disjoint convex
    pieces."""
    a = sum(polygon_area(p) for p in first)
    b = sum(polygon_area(p) for p in second)
    for collection in (first, second):
        assert all(
            polygon_area(oracle_intersection(p, q)) == 0
            for i, p in enumerate(collection)
            for q in collection[:i]
        )
    overlap = sum(polygon_area(oracle_intersection(p, q)) for p in first for q in second)
    assert a == b == overlap


@pytest.mark.parametrize("coverage", ["islands", "ring", "full_tiled", "one_ulp_gap"])
def test_indexed_overlay_covers_exact_literal_domains_and_complement(coverage):
    """Compare the exact covered union to literal input domains and prove its complement fills
    the original square."""
    square = rectangle(Q(0), Q(0), Q(1), Q(1))
    domains = []
    if coverage == "islands":
        for x, z in [(1, 1), (5, 1), (1, 5), (5, 5)]:
            domains.append([(Q(x, 8), Q(z, 8)), (Q(x + 1, 8), Q(z, 8)), (Q(x, 8), Q(z + 1, 8))])
    else:
        if coverage == "ring":
            rectangles = [
                rectangle(Q(0), Q(0), Q(1, 4), Q(1)),
                rectangle(Q(3, 4), Q(0), Q(1, 4), Q(1)),
                rectangle(Q(1, 4), Q(0), Q(1, 2), Q(1, 4)),
                rectangle(Q(1, 4), Q(3, 4), Q(1, 2), Q(1, 4)),
            ]
        elif coverage == "full_tiled":
            rectangles = [
                rectangle(Q(x, 4), Q(z, 4), Q(1, 4), Q(1, 4)) for x in range(4) for z in range(4)
            ]
        else:
            edge = Q(1, 2) + Q(1, 2**53)
            rectangles = [
                rectangle(Q(0), Q(0), Q(1, 2), Q(1)),
                rectangle(edge, Q(0), 1 - edge, Q(1)),
            ]
        for poly in rectangles:
            domains.extend([[poly[0], poly[1], poly[2]], [poly[0], poly[2], poly[3]]])
    support = [(domain, [(x, z, Q(0)) for x, z in domain]) for domain in domains]
    new, missing_new = current.overlay([(square, [])], support, current.Budget())
    compare_partition(domains, [poly for poly, _ in new])
    compare_partition([square], domains + missing_new)
    if coverage == "full_tiled":
        assert not missing_new
    if coverage == "one_ulp_gap":
        assert sum(polygon_area(p) for p in missing_new) == Q(1, 2**53)
