"""Bounded exact local-overlap certificates over complete validated closed solid boundaries.

This mathematical module alone cannot attest native extraction, source identity,
package authority, seam-wide coverage, strength or visual quality. Public host
evaluators prepare private solids only from their exact bound source/actual data.
"""

import math
from dataclasses import dataclass, field
from fractions import Fraction as F
from typing import Any, TypeAlias

from codex_blender_modeler.blender_scripts.self_intersection_runtime import prepare_exact_triangles
from codex_blender_modeler.structural_geometry.profiled_relief import (
    _MAX_PAIR_TESTS,
    _improper_contact,
)
from codex_blender_modeler.structural_geometry.triangle_shell_math import (
    validate_triangle_shell_data,
)

Point: TypeAlias = tuple[F, F, F]
Triangle: TypeAlias = tuple[Point, Point, Point]
Bounds: TypeAlias = tuple[Point, Point]
ProjectionInterval: TypeAlias = tuple[float, float]

# One fixed signed-coordinate direction keeps aggregate work conservative and bounded.
# More directions are not a caller option and would consume the same unchanged cap.
_EMBEDDING_DIRECTIONS = ((1, 1, 1),)


class Unverified(ValueError):
    """Mark an unsupported, invalid or exhausted proof without treating it as a pass."""


def sub(a: Point, b: Point) -> Point:
    """Subtract rational coordinate triples."""
    return tuple(x - y for x, y in zip(a, b, strict=True))


def dot(a: Point, b: Point) -> F:
    """Compute an exact dot product."""
    return sum((x * y for x, y in zip(a, b, strict=True)), F(0))


def cross(a: Point, b: Point) -> Point:
    """Compute an exact cross product."""
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def point(raw: object) -> Point:
    """Validate finite bounded numeric coordinates without string or bool coercion."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        raise Unverified("invalid point")
    if any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e6 for x in raw):
        raise Unverified("invalid coordinate")
    return tuple(F(x) for x in raw)


@dataclass
class Budget:
    """Account for aggregate asset geometry, embedding scans and root predicates."""

    limit: int = 1_000_000
    used: int = field(default=0, init=False)
    triangle_count: int = field(default=0, init=False)
    embedding_scans: list[int] = field(default_factory=lambda: [0], init=False)

    def __post_init__(self) -> None:
        """Only a strict bounded integer can select an equal or smaller work limit."""
        if type(self.limit) is not int or not 1 <= self.limit <= 1_000_000:
            raise Unverified("invalid predicate budget limit")

    def claim_component(self, triangle_count: int) -> None:
        """Count each prepared component in the aggregate 25,000-triangle asset cap."""
        if type(triangle_count) is not int or not 4 <= triangle_count <= 4096:
            raise Unverified("component triangle limit exceeded")
        self.triangle_count += triangle_count
        if self.triangle_count > 25_000:
            raise Unverified("aggregate asset triangle limit exceeded")

    def charge(self) -> None:
        """Count every boundary/ray triangle visit in one shared evaluation budget."""
        if type(self.limit) is not int or not 1 <= self.limit <= 1_000_000:
            raise Unverified("invalid predicate budget limit")
        if type(self.used) is not int or self.used < 0:
            raise Unverified("invalid predicate budget counter")
        self.used += 1
        if self.used > self.limit:
            raise Unverified("root-ball predicate budget exhausted")


@dataclass(frozen=True)
class _PreparedSolid:
    """Hold a complete validated connected solid boundary, never a subset of faces."""

    triangles: tuple[Triangle, ...]
    bounds: tuple[Bounds, ...]
    embedding_strategy: str


@dataclass(frozen=True)
class _BoxNode:
    """One deterministic partition of triangle indices and its exact enclosing AABB."""

    bounds: tuple[tuple[float, ...], tuple[float, ...]]
    count: int
    indices: tuple[int, ...] = ()
    children: tuple["_BoxNode", "_BoxNode"] | None = None


def _embedding_charge(budget: Budget, amount: int = 1) -> None:
    """Charge hierarchy entries, pair visits, projection records and filter visits to one cap."""
    if (
        len(budget.embedding_scans) != 1
        or type(budget.embedding_scans[0]) is not int
        or budget.embedding_scans[0] < 0
    ):
        raise Unverified("invalid embedding work counter")
    budget.embedding_scans[0] += amount
    if budget.embedding_scans[0] > 1_000_000:
        raise Unverified("attachment embedding broad-phase work budget exhausted")


def _build_box_tree(
    bounds: list[tuple[tuple[float, ...], tuple[float, ...]]],
    indices: tuple[int, ...],
    budget: Budget,
) -> _BoxNode:
    """Partition by widest centroid span; every child retains its complete original boxes."""
    _embedding_charge(budget, len(indices))
    low = tuple(min(bounds[i][0][a] for i in indices) for a in range(3))
    high = tuple(max(bounds[i][1][a] for i in indices) for a in range(3))
    if len(indices) <= 3:
        return _BoxNode((low, high), len(indices), indices)
    if len(indices) == 4:
        # Preserve a compact leaf for a closed-overlap clique; charge every extra record.
        # Otherwise a three-triangle terminal bound improves sparse local partitions.
        # This deterministic heuristic never rejects a box pair or changes a predicate.
        _embedding_charge(budget, len(indices))
        if all(
            max(bounds[i][0][axis] for i in indices) <= min(bounds[i][1][axis] for i in indices)
            for axis in range(3)
        ):
            return _BoxNode((low, high), len(indices), indices)
    spans = []
    for axis in range(3):
        centers = [bounds[i][0][axis] + bounds[i][1][axis] for i in indices]
        spans.append(max(centers) - min(centers))
    axis = max(range(3), key=lambda a: (spans[a], -a))
    ordered = tuple(sorted(indices, key=lambda i: (bounds[i][0][axis] + bounds[i][1][axis], i)))
    middle = len(ordered) // 2
    children = (
        _build_box_tree(bounds, ordered[:middle], budget),
        _build_box_tree(bounds, ordered[middle:], budget),
    )
    return _BoxNode((low, high), len(indices), children=children)


def _boxes_overlap(
    first: tuple[tuple[float, ...], tuple[float, ...]],
    second: tuple[tuple[float, ...], tuple[float, ...]],
) -> bool:
    """Retain all closed-box face/edge/point touches without tolerance expansion or contraction."""
    return all(
        first[1][axis] >= second[0][axis] and second[1][axis] >= first[0][axis] for axis in range(3)
    )


def embedding_candidate_pairs(
    bounds: list[tuple[tuple[float, ...], tuple[float, ...]]], budget: Budget
):
    """Enumerate the complete unordered closed-AABB pair set with bounded BVH traversal."""
    if not bounds:
        return
    root = _build_box_tree(bounds, tuple(range(len(bounds))), budget)
    pending = [(root, root)]
    while pending:
        first, second = pending.pop()
        _embedding_charge(budget)
        if not _boxes_overlap(first.bounds, second.bounds):
            continue
        if first is second:
            if first.children is not None:
                left, right = first.children
                pending.extend(((right, right), (left, right), (left, left)))
                continue
            pairs = (
                (a, b)
                for offset, a in enumerate(first.indices)
                for b in first.indices[offset + 1 :]
            )
        elif first.children is None and second.children is None:
            pairs = ((a, b) for a in first.indices for b in second.indices)
        else:
            if first.children is not None and (
                second.children is None or first.count >= second.count
            ):
                pending.extend((child, second) for child in first.children)
            else:
                pending.extend((first, child) for child in second.children)
            continue
        for a, b in pairs:
            _embedding_charge(budget)
            if _boxes_overlap(bounds[a], bounds[b]):
                yield (a, b) if a < b else (b, a)


def _projection_interval(point: list[float], direction: tuple[int, int, int]) -> ProjectionInterval:
    """Enclose the exact signed-coordinate sum by rounding outward after every addition.

    Complete embedding supplies already validated finite coordinates bounded by
    1e6 and only the fixed directions above. Negation by -1 is exact; every rounded
    addition expands both endpoints, including cancellation and subnormal cases.
    """
    low = high = 0.0
    for value, sign in zip(point, direction, strict=True):
        if sign:
            term = value if sign == 1 else -value
            low = math.nextafter(low + term, -math.inf)
            high = math.nextafter(high + term, math.inf)
    return low, high


def _embedding_projection_bounds(
    vertices: list[list[float]], triangles: list[list[int]], budget: Budget
) -> list[tuple[ProjectionInterval, ...]]:
    """Enclose each validated triangle along the fixed axis, charging every axis record.

    One construction unit covers exactly three vertex projections, each with at
    most three additions. Triangle and aggregate work caps bound the outer loops.
    """
    result = []
    for triangle in triangles:
        projections = []
        for direction in _EMBEDDING_DIRECTIONS:
            _embedding_charge(budget)
            corners = [_projection_interval(vertices[index], direction) for index in triangle]
            projections.append(
                (min(value[0] for value in corners), max(value[1] for value in corners))
            )
        result.append(tuple(projections))
    return result


def _projection_bounds_disjoint(
    first: tuple[ProjectionInterval, ...],
    second: tuple[ProjectionInterval, ...],
    budget: Budget,
) -> bool:
    """Reject only strict interval separation, charging every fixed-direction comparison.

    A common triangle point projects into both enclosing intervals, so touching
    endpoints and all uncertain overlaps remain for the unchanged exact predicate.
    """
    for (first_low, first_high), (second_low, second_high) in zip(first, second, strict=True):
        _embedding_charge(budget)
        if first_high < second_low or second_high < first_low:
            return True
    return False


def _validate_complete_embedding(
    vertices: list[list[float]], triangles: list[list[int]], budget: Budget
) -> None:
    """Filter only proven disjoint bounds before unchanged exact contact predicates and cap."""
    prepared = prepare_exact_triangles(vertices, triangles)
    if any(item is None for item in prepared):
        raise Unverified("solid-root exact triangle preparation failed")
    bounds = [
        (
            tuple(min(vertices[i][a] for i in face) for a in range(3)),
            tuple(max(vertices[i][a] for i in face) for a in range(3)),
        )
        for face in triangles
    ]
    projections = _embedding_projection_bounds(vertices, triangles, budget)
    pairs = 0
    for other, index in embedding_candidate_pairs(bounds, budget):
        if _projection_bounds_disjoint(projections[other], projections[index], budget):
            continue
        pairs += 1
        if pairs > _MAX_PAIR_TESTS:
            raise Unverified("solid-root exhausted the unchanged exact triangle-pair budget")
        if _improper_contact(prepared[other], prepared[index]):
            raise Unverified("solid-root triangles self-intersect or touch improperly")


def prepare_solid(
    vertices: list[list[float]], triangles: list[list[int]], budget: Budget | None = None
) -> _PreparedSolid:
    """Require the existing topology/embedding checks and exact outward volume."""
    budget = budget if budget is not None else Budget()
    budget.claim_component(len(triangles))
    validate_triangle_shell_data(
        {"kind": "triangulated_shell", "vertices": vertices, "triangles": triangles}
    )
    _validate_complete_embedding(vertices, triangles, budget)
    vs = tuple(point(v) for v in vertices)
    ts = tuple(tuple(vs[i] for i in t) for t in triangles)
    if sum((dot(a, cross(b, c)) for a, b, c in ts), F(0)) <= 0:
        raise Unverified("nonpositive exact signed volume")
    bounds = tuple(
        (
            tuple(min(p[k] for p in t) for k in range(3)),
            tuple(max(p[k] for p in t) for k in range(3)),
        )
        for t in ts
    )
    return _PreparedSolid(ts, bounds, "exact_closed_aabb_bvh")


def box_distance2(p: Point, bounds: Bounds) -> F:
    """Return an exact lower bound on distance to any enclosed triangle."""
    lo, hi = bounds
    return sum((max(lo[k] - p[k], F(0), p[k] - hi[k]) ** 2 for k in range(3)), F(0))


def segment_distance2(p: Point, a: Point, b: Point) -> F:
    """Measure exact squared distance to the closed segment."""
    e = sub(b, a)
    t = max(F(0), min(F(1), dot(sub(p, a), e) / dot(e, e)))
    q = tuple(a[k] + t * e[k] for k in range(3))
    d = sub(p, q)
    return dot(d, d)


def triangle_distance2(p: Point, t: Triangle) -> F:
    """Measure exact point/face/edge/vertex squared distance without square roots."""
    a, b, c = t
    ab = sub(b, a)
    ac = sub(c, a)
    ap = sub(p, a)
    d00 = dot(ab, ab)
    d01 = dot(ab, ac)
    d11 = dot(ac, ac)
    d20 = dot(ap, ab)
    d21 = dot(ap, ac)
    den = d00 * d11 - d01 * d01
    if den <= 0:
        raise Unverified("degenerate exact triangle")
    u = d11 * d20 - d01 * d21
    v = d00 * d21 - d01 * d20
    if u >= 0 and v >= 0 and u + v <= den:
        n = cross(ab, ac)
        return dot(ap, n) ** 2 / dot(n, n)
    return min(segment_distance2(p, a, b), segment_distance2(p, b, c), segment_distance2(p, c, a))


def ray_box(p: Point, d: Point, bounds: Bounds) -> bool:
    """Conservatively reject boxes outside the exact forward ray."""
    lo, hi = bounds
    near = F(0)
    far = None
    for k in range(3):
        a = (lo[k] - p[k]) / d[k]
        b = (hi[k] - p[k]) / d[k]
        if a > b:
            a, b = b, a
        near = max(near, a)
        far = b if far is None else min(far, b)
        if far < near:
            return False
    return True


def inside(solid: _PreparedSolid, p: Point, budget: Budget) -> tuple[bool, int, int]:
    """Use exact bounded ray parity; ambiguous edge, vertex or coplanar hits retry."""
    for k in range(1, 33):
        d = (F(1), F(2 * k + 1), F((2 * k + 1) ** 2 + 2))
        hits = 0
        ambiguous = False
        for t, bounds in zip(solid.triangles, solid.bounds, strict=True):
            budget.charge()
            if not ray_box(p, d, bounds):
                continue
            a, b, c = t
            e1 = sub(b, a)
            e2 = sub(c, a)
            h = cross(d, e2)
            det = dot(e1, h)
            s = sub(p, a)
            if det == 0:
                if dot(cross(e1, e2), s) == 0:
                    ambiguous = True
                    break
                continue
            u = dot(s, h) / det
            q = cross(s, e1)
            v = dot(d, q) / det
            distance = dot(e2, q) / det
            if distance < 0 or u < 0 or v < 0 or u + v > 1:
                continue
            if distance == 0 or u == 0 or v == 0 or u + v == 1:
                ambiguous = True
                break
            hits += 1
        if not ambiguous:
            return bool(hits % 2), k, hits
    raise Unverified("all deterministic ray directions ambiguous")


def certify_ball(
    solid: _PreparedSolid,
    center: list[float],
    radius: float,
    root_bounds: list[list[float]],
    budget: Budget | None = None,
) -> dict[str, Any]:
    """Prove the declared ball lies in one solid; report only a conservative lower bound."""
    budget = budget if budget is not None else Budget()
    p = point(center)
    if type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
        raise Unverified("radius must be finite and positive")
    r = F(radius)
    r2 = r * r
    lo, hi = (point(v) for v in root_bounds)
    if any(lo[k] > hi[k] or not lo[k] <= p[k] - r <= p[k] + r <= hi[k] for k in range(3)):
        raise Unverified("entire ball must lie inside declared root region")
    minimum = None
    pruned = 0
    exact = 0
    for t, bounds in zip(solid.triangles, solid.bounds, strict=True):
        budget.charge()
        value = box_distance2(p, bounds)
        if value >= r2:
            pruned += 1
        else:
            value = triangle_distance2(p, t)
            exact += 1
        minimum = value if minimum is None else min(minimum, value)
        if value < r2:
            raise Unverified("declared ball crosses or approaches solid boundary")
    contained, direction, hits = inside(solid, p, budget)
    if not contained:
        raise Unverified("center is outside material, possibly in a cavity")
    return {
        "status": "certified_local_ball_only",
        "radius": radius,
        "conservative_boundary_distance_squared_lower_bound": {
            "numerator": str(minimum.numerator),
            "denominator": str(minimum.denominator),
        },
        "attained_minimum_claimed": False,
        "aabb_proven_triangles": pruned,
        "exact_distance_triangles": exact,
        "ray_direction_index": direction,
        "forward_intersections": hits,
        "aggregate_predicate_visits": budget.used,
    }


def connected_required_graph(required: list[str], edges: list[tuple[str, str]]) -> bool:
    """Reject unknown/self connections and require all declared solids to be reachable."""
    names = set(required)
    if not names or len(names) != len(required):
        raise Unverified("invalid required identities")
    graph = {x: set() for x in names}
    for a, b in edges:
        if a not in names or b not in names or a == b:
            raise Unverified("invalid connection identities")
        graph[a].add(b)
        graph[b].add(a)
    seen = set()
    todo = [next(iter(names))]
    while todo:
        a = todo.pop()
        if a not in seen:
            seen.add(a)
            todo.extend(graph[a] - seen)
    if seen != names:
        raise Unverified("required attachment graph is disconnected")
    return True
