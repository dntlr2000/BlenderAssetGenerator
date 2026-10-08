"""Exact adversarial oracles for conservative fixed-direction embedding rejection."""

import itertools
import math
import random
import struct
from fractions import Fraction

import pytest

from codex_blender_modeler.blender_scripts.self_intersection_runtime import prepare_exact_triangles
from codex_blender_modeler.structural_geometry import solid_root_ball as r
from codex_blender_modeler.structural_geometry.profiled_relief import _improper_contact

_DIRECTIONS = (
    (1, 1, 0),
    (1, -1, 0),
    (1, 0, 1),
    (1, 0, -1),
    (0, 1, 1),
    (0, 1, -1),
    (1, 1, 1),
    (1, 1, -1),
    (1, -1, 1),
    (1, -1, -1),
)
_PERMUTATIONS = tuple(itertools.permutations(range(3)))
_TRANSFORMS = tuple(itertools.product(_PERMUTATIONS, itertools.product((-1, 1), repeat=3)))
_MIN_SUBNORMAL = math.nextafter(0.0, math.inf)


def _binary32(value):
    """Perform actual IEEE binary32 storage rounding without decimal surrogates."""
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _represented(vertices, precision):
    """Keep source floats or independently round every coordinate through binary32."""
    convert = float if precision == "source" else _binary32
    return [[convert(value) for value in point] for point in vertices]


def _exact_projection(point, direction):
    """Calculate the independent exact value of the represented signed-coordinate sum."""
    return sum(
        (Fraction(value) * sign for value, sign in zip(point, direction, strict=True)),
        Fraction(0),
    )


def _transform(vertices, permutation, signs):
    """Permute axes and reflect coordinates using only exact float operations."""
    return [[point[axis] * sign for axis, sign in zip(permutation, signs, strict=True)]
            for point in vertices]


def _bounds(vertices, triangles):
    """Build raw-coordinate closed boxes independently of projection helpers."""
    return [
        (tuple(min(vertices[index][axis] for index in face) for axis in range(3)),
         tuple(max(vertices[index][axis] for index in face) for axis in range(3)))
        for face in triangles
    ]


def _retained_pairs(vertices, triangles):
    """Apply the new rejection filter to the unchanged full AABB enumeration."""
    budget = r.Budget()
    projections = r._embedding_projection_bounds(vertices, triangles, budget)
    candidates = set(r.embedding_candidate_pairs(_bounds(vertices, triangles), budget))
    retained = {
        (first, second) for first, second in candidates
        if not r._projection_bounds_disjoint(projections[first], projections[second], budget)
    }
    return candidates, retained


def _pair_fixture(name, precision):
    """Provide actual geometry for distinct contact, adjacency and separation modes."""
    first = [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 2.0, 0.0]]
    if name == "shared_edge":
        return first + [[2.0, 2.0, 0.0]], [[0, 1, 2], [1, 3, 2]], False
    if name == "shared_vertex":
        return first + [[-2.0, 0.0, 1.0], [0.0, -2.0, 1.0]], [[0, 1, 2], [0, 3, 4]], False
    second = {
        "coplanar_overlap": [[0.25, 0.25, 0.0], [1.25, 0.25, 0.0], [0.25, 1.25, 0.0]],
        "independent_vertex": [[2.0, 0.0, 0.0], [3.0, 0.0, 1.0], [2.0, -1.0, 1.0]],
        "independent_edge": [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, -2.0, 0.0]],
        "crossing": [[0.5, 0.5, -1.0], [0.5, 0.5, 1.0], [1.5, 0.5, 0.0]],
        "diagonal_gap": [[2.0, 2.0, 0.0], [2.0, 0.25, 0.0], [0.25, 2.0, 0.0]],
    }
    if name == "near_boundary":
        edge = math.nextafter(2.0, 0.0)
        other = [[edge, 0.0, 0.0], [3.0, 0.0, 0.0], [edge, 1.0, 0.0]]
    elif name == "subnormal_crossing":
        scale = _MIN_SUBNORMAL * 16 if precision == "source" else 2.0**-145
        first = [[coordinate * scale for coordinate in point] for point in first]
        other = [[coordinate * scale for coordinate in point] for point in second["crossing"]]
    elif name == "oblique_gap":
        first = [[-1.0, 1.0, 0.0], [0.0, -1.0, 1.0], [1.0, 0.0, -1.0]]
        other = [[coordinate + 2.0**-20 for coordinate in point] for point in first]
    else:
        other = second[name]
    return first + other, [[0, 1, 2], [3, 4, 5]], name not in {"diagonal_gap", "oblique_gap"}


def test_fixed_directions_are_deterministic_and_unchanged():
    """The single bounded production axis remains symmetric under coordinate permutation."""
    assert tuple(r._EMBEDDING_DIRECTIONS) == ((1, 1, 1),)


@pytest.mark.parametrize("precision", ["source", "binary32"])
def test_projection_intervals_enclose_exact_adversarial_sums(precision):
    """Cancellation, signed zero, normal boundaries and subnormals never round inward."""
    normal = float.fromhex("0x1.0p-1022")
    points = [
        [0.0, -0.0, 0.0],
        [2.0**19, 2.0**-36, -2.0**19],
        [2.0**19, 2.0**-149, -2.0**19],
        [1.0, math.nextafter(-1.0, 0.0), 2.0**-54],
        [math.nextafter(1.0, math.inf), -1.0, -2.0**-52],
        [1_000_000.0, -1_000_000.0, _MIN_SUBNORMAL],
        [_MIN_SUBNORMAL, -_MIN_SUBNORMAL, _MIN_SUBNORMAL],
        [normal, -normal, _MIN_SUBNORMAL],
        [math.nextafter(normal, 0.0), _MIN_SUBNORMAL, -normal],
        [2.0**-149, -2.0**-126, 2.0**-126],
        [math.nextafter(2.0**-126, 0.0), 2.0**-149, -2.0**-126],
    ]
    for permutation, signs in _TRANSFORMS:
        for point in _represented(_transform(points, permutation, signs), precision):
            for direction in _DIRECTIONS:
                low, high = r._projection_interval(point, direction)
                exact = _exact_projection(point, direction)
                assert math.isfinite(low) and math.isfinite(high)
                assert Fraction(low) <= exact <= Fraction(high), (point, direction, exact)


@pytest.mark.parametrize("precision", ["source", "binary32"])
def test_projection_intervals_enclose_seeded_exponent_mixtures(precision):
    """Seeded mixed exponents independently stress rounding outside hand-picked cases."""
    rng = random.Random(683917)
    for _ in range(128):
        point = [
            math.ldexp(rng.choice((-1.0, 1.0)) * rng.uniform(1.0, 2.0),
                       rng.choice((-1074, -1022, -149, -126, -53, -24, -1, 0, 19)))
            for _ in range(3)
        ]
        for represented in _represented([point], precision):
            for direction in _DIRECTIONS:
                low, high = r._projection_interval(represented, direction)
                assert Fraction(low) <= _exact_projection(represented, direction) <= Fraction(high)


def test_cancellation_requires_enclosure_before_the_final_addition():
    """One outward ULP around a naive final sum cannot enclose this bounded exact sum."""
    point = (2.0**19, 2.0**-36, -2.0**19)
    exact = _exact_projection(point, (1, 1, 1))
    naive = (point[0] + point[1]) + point[2]
    assert Fraction(math.nextafter(naive, math.inf)) < exact
    low, high = r._projection_interval(point, (1, 1, 1))
    assert Fraction(low) <= exact <= Fraction(high)


@pytest.mark.parametrize("precision", ["source", "binary32"])
def test_triangle_bounds_enclose_each_exact_vertex_extremum(precision):
    """Every reported triangle interval encloses its true linear extrema in either format."""
    vertices = _represented([
        [2.0**19, 2.0**-36, -2.0**19],
        [math.nextafter(2.0**19, math.inf), 2.0**-35, -2.0**19],
        [2.0**19, 2.0**-149, math.nextafter(-2.0**19, 0.0)],
        [_MIN_SUBNORMAL, -_MIN_SUBNORMAL, 2.0**-149],
    ], precision)
    triangles = [[0, 1, 2], [2, 1, 0], [0, 2, 3]]
    budget = r.Budget()
    projections = r._embedding_projection_bounds(vertices, triangles, budget)
    assert len(projections) == len(triangles)
    assert budget.embedding_scans == [len(triangles) * len(r._EMBEDDING_DIRECTIONS)]
    assert projections[0] == projections[1]
    for face, intervals in zip(triangles, projections, strict=True):
        assert len(intervals) == len(r._EMBEDDING_DIRECTIONS)
        for direction, (low, high) in zip(r._EMBEDDING_DIRECTIONS, intervals, strict=True):
            exact = [_exact_projection(vertices[index], direction) for index in face]
            assert Fraction(low) <= min(exact) <= max(exact) <= Fraction(high)


@pytest.mark.parametrize("axis", range(len(r._EMBEDDING_DIRECTIONS)))
@pytest.mark.parametrize("reverse", [False, True])
def test_only_strict_interval_gaps_reject_pairs(axis, reverse):
    """Endpoint touches survive, while a one-representable-step gap in either order rejects."""
    first = [(0.0, 1.0)] * len(r._EMBEDDING_DIRECTIONS)
    touching = [(0.0, 1.0)] * len(r._EMBEDDING_DIRECTIONS)
    touching[axis] = (1.0, 2.0)
    pair = (touching, first) if reverse else (first, touching)
    budget = r.Budget()
    assert r._projection_bounds_disjoint(*pair, budget) is False
    assert budget.embedding_scans == [len(r._EMBEDDING_DIRECTIONS)]
    separated = list(touching)
    separated[axis] = (math.nextafter(1.0, math.inf), 2.0)
    pair = (separated, first) if reverse else (first, separated)
    budget = r.Budget()
    assert r._projection_bounds_disjoint(*pair, budget) is True
    assert budget.embedding_scans == [axis + 1]


@pytest.mark.parametrize("precision", ["source", "binary32"])
@pytest.mark.parametrize("name", [
    "shared_edge", "shared_vertex", "coplanar_overlap", "independent_vertex",
    "independent_edge", "crossing", "near_boundary", "subnormal_crossing",
    "diagonal_gap", "oblique_gap",
])
def test_contact_semantics_survive_all_axis_orientations(name, precision):
    """Unchanged exact predicates retain real contacts under reflections and vertex orderings."""
    vertices, triangles, improper = _pair_fixture(name, precision)
    for offset, (permutation, signs) in enumerate(_TRANSFORMS):
        represented = _represented(_transform(vertices, permutation, signs), precision)
        first_order = _PERMUTATIONS[offset % 6]
        second_order = _PERMUTATIONS[(offset // 6 + offset) % 6]
        faces = [[triangles[0][index] for index in first_order],
                 [triangles[1][index] for index in second_order]]
        prepared = prepare_exact_triangles(represented, faces)
        assert all(triangle is not None for triangle in prepared)
        assert _improper_contact(*prepared) is improper, (name, precision, permutation, signs)
        candidates, retained = _retained_pairs(represented, faces)
        assert candidates == {(0, 1)}
        if improper or name.startswith("shared_"):
            assert retained == {(0, 1)}
        if improper:
            with pytest.raises(r.Unverified, match="self-intersect or touch improperly"):
                r._validate_complete_embedding(represented, faces, r.Budget())
        else:
            r._validate_complete_embedding(represented, faces, r.Budget())


@pytest.mark.parametrize("precision", ["source", "binary32"])
def test_selected_axis_removes_a_real_gap_inside_overlapping_aabbs(precision):
    """The x+y+z axis rejects separated triangles despite overlapping original boxes."""
    vertices, triangles, _ = _pair_fixture("diagonal_gap", precision)
    represented = _represented(vertices, precision)
    assert not _improper_contact(*prepare_exact_triangles(represented, triangles))
    candidates, retained = _retained_pairs(represented, triangles)
    assert candidates == {(0, 1)}
    assert not retained
    r._validate_complete_embedding(represented, triangles, r.Budget())


@pytest.mark.parametrize("precision", ["source", "binary32"])
def test_bruteforce_exact_contacts_are_a_subset_of_retained_pairs(precision):
    """An all-pairs original-predicate oracle cannot lose a crossing to either broad phase."""
    rng = random.Random(972931)
    vertices = []
    triangles = []
    for name in ("coplanar_overlap", "independent_vertex", "crossing", "diagonal_gap"):
        points, faces, _ = _pair_fixture(name, precision)
        triangles.extend([[index + len(vertices) for index in face] for face in faces])
        vertices.extend(points)
    for _ in range(12):
        triangle = [[rng.randrange(-16, 17) / 8 for _ in range(3)] for _ in range(3)]
        assert prepare_exact_triangles(triangle, [[0, 1, 2]])[0] is not None
        triangles.append(list(range(len(vertices), len(vertices) + 3)))
        vertices.extend(triangle)
    rejected_count = 0
    for permutation in _PERMUTATIONS:
        represented = _represented(_transform(vertices, permutation, (-1, 1, -1)), precision)
        prepared = prepare_exact_triangles(represented, triangles)
        assert all(triangle is not None for triangle in prepared)
        improper = {
            (first, second) for first, second in itertools.combinations(range(len(triangles)), 2)
            if _improper_contact(prepared[first], prepared[second])
        }
        candidates, retained = _retained_pairs(represented, triangles)
        assert improper
        assert improper <= retained <= candidates
        rejected_count += len(candidates - retained)
        for first, second in candidates - retained:
            assert not _improper_contact(prepared[first], prepared[second])
    assert rejected_count > 0


def test_binary32_rounding_is_rechecked_in_its_own_exact_geometry():
    """An exact source gap may become an improper binary32 contact and must then fail."""
    edge = math.nextafter(1.0, math.inf)
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                [edge, 0.0, 0.0], [2.0, 0.0, 0.0], [edge, 1.0, 0.0]]
    triangles = [[0, 1, 2], [3, 4, 5]]
    assert not _improper_contact(*prepare_exact_triangles(vertices, triangles))
    r._validate_complete_embedding(vertices, triangles, r.Budget())
    rounded = _represented(vertices, "binary32")
    assert _improper_contact(*prepare_exact_triangles(rounded, triangles))
    assert _retained_pairs(rounded, triangles)[1] == {(0, 1)}
    with pytest.raises(r.Unverified, match="self-intersect or touch improperly"):
        r._validate_complete_embedding(rounded, triangles, r.Budget())


def test_projection_budget_is_aggregate_and_exhausts_during_construction():
    """Projection preparation consumes the shared fixed cap before returning partial data."""
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    budget = r.Budget()
    budget.embedding_scans[0] = 1_000_000 - 2 * len(r._EMBEDDING_DIRECTIONS)
    r._embedding_projection_bounds(vertices, [[0, 1, 2]], budget)
    r._embedding_projection_bounds(vertices, [[2, 1, 0]], budget)
    assert budget.embedding_scans == [1_000_000]
    with pytest.raises(r.Unverified, match="embedding broad-phase work budget exhausted"):
        r._embedding_projection_bounds(vertices, [[0, 1, 2]], budget)
    assert budget.embedding_scans == [1_000_001]


def test_projection_comparison_exhaustion_cannot_return_a_clear_result():
    """Overlapping comparisons and a rejecting comparison are charged before their result."""
    first = [(0.0, 1.0)] * len(r._EMBEDDING_DIRECTIONS)
    budget = r.Budget()
    budget.embedding_scans[0] = 1_000_001 - len(r._EMBEDDING_DIRECTIONS)
    with pytest.raises(r.Unverified, match="embedding broad-phase work budget exhausted"):
        r._projection_bounds_disjoint(first, first, budget)
    assert budget.embedding_scans == [1_000_001]
    separated = [(2.0, 3.0)] * len(r._EMBEDDING_DIRECTIONS)
    budget.embedding_scans[0] = 1_000_000
    with pytest.raises(r.Unverified, match="embedding broad-phase work budget exhausted"):
        r._projection_bounds_disjoint(first, separated, budget)
    assert budget.embedding_scans == [1_000_001]


def test_disjoint_projection_does_not_spend_the_narrow_pair_cap(monkeypatch):
    """A proved gap bypasses narrow-phase counting while the original exact oracle is clear."""
    assert r._MAX_PAIR_TESTS == 32768
    vertices, triangles, _ = _pair_fixture("diagonal_gap", "source")
    assert not _improper_contact(*prepare_exact_triangles(vertices, triangles))
    assert _retained_pairs(vertices, triangles) == ({(0, 1)}, set())
    monkeypatch.setattr(r, "_MAX_PAIR_TESTS", 0)
    r._validate_complete_embedding(vertices, triangles, r.Budget())


def test_retained_legal_adjacency_still_spends_the_narrow_pair_cap(monkeypatch):
    """A three-triangle fan counts every legitimate indexed contact, with an inclusive cap."""
    vertices = [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [-1.0, 2.0, 0.0], [-1.0, -2.0, 0.0]]
    triangles = [[0, 1, 2], [0, 2, 3], [0, 3, 1]]
    prepared = prepare_exact_triangles(vertices, triangles)
    assert all(not _improper_contact(first, second)
               for first, second in itertools.combinations(prepared, 2))
    assert len(_retained_pairs(vertices, triangles)[1]) == 3
    monkeypatch.setattr(r, "_MAX_PAIR_TESTS", 2)
    with pytest.raises(r.Unverified, match="unchanged exact triangle-pair budget"):
        r._validate_complete_embedding(vertices, triangles, r.Budget())
    monkeypatch.setattr(r, "_MAX_PAIR_TESTS", 3)
    r._validate_complete_embedding(vertices, triangles, r.Budget())


def test_retained_improper_touch_reaches_the_unchanged_narrow_predicate(monkeypatch):
    """A nonindexed point touch first obeys the cap and then fails the real exact predicate."""
    vertices, triangles, _ = _pair_fixture("independent_vertex", "source")
    assert _improper_contact(*prepare_exact_triangles(vertices, triangles))
    monkeypatch.setattr(r, "_MAX_PAIR_TESTS", 0)
    with pytest.raises(r.Unverified, match="unchanged exact triangle-pair budget"):
        r._validate_complete_embedding(vertices, triangles, r.Budget())
    monkeypatch.setattr(r, "_MAX_PAIR_TESTS", 1)
    with pytest.raises(r.Unverified, match="self-intersect or touch improperly"):
        r._validate_complete_embedding(vertices, triangles, r.Budget())
