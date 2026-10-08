"""Experimental pure height-field relief generation; no canonical writes or public schema.

Every coverage/depth decision uses exact rational arithmetic on supplied binary
coordinates. The caller must independently bind complete component patches to the
actual inspected artifact. An in-memory float32 roundtrip is not an export audit.
"""

from __future__ import annotations

import math
import struct
from bisect import bisect_left, bisect_right
from fractions import Fraction as Q

from codex_blender_modeler.structural_geometry.profiled_relief import _validate_embedded
from codex_blender_modeler.structural_geometry.triangle_shell import (
    TriangulatedShellGeometry,
)

MAX_INPUT_VERTICES = 512
MAX_INPUT_TRIANGLES = 256
MAX_INSPECTION_VERTICES = 8192
MAX_INSPECTION_TRIANGLES = 4096
MAX_CELLS = 4096
MAX_CLIPS = 32768
MAX_EDGE_TESTS = 1048576
MAX_PAIR_SCANS = 1048576
MAX_RATIONAL_BITS = 4096


class Unverified(ValueError):
    """Identify unsupported, malformed, ambiguous, or budget-exhausted evidence."""


class Budget:
    """Bound clipping, conforming-edge work, and rational expression growth."""

    def __init__(self):
        """Start one non-resetting budget shared by a complete inspection."""
        self.clips = 0
        self.edge_tests = 0
        self.pair_scans = 0

    def clip(self):
        """Refuse work beyond the complete bounded clipping allowance."""
        self.clips += 1
        if self.clips > MAX_CLIPS:
            raise Unverified("exact clipping workload exhausted")

    def edge(self):
        """Refuse work beyond the complete bounded edge-splitting allowance."""
        self.edge_tests += 1
        if self.edge_tests > MAX_EDGE_TESTS:
            raise Unverified("conforming-edge workload exhausted")

    def pair(self):
        """Bound every broad-phase pair, including those skipped as exactly disjoint."""
        self.pair_scans += 1
        if self.pair_scans > MAX_PAIR_SCANS:
            raise Unverified("broad-phase pair workload exhausted")


def bounded(value):
    """Refuse exact intermediates whose integer representation exceeds the bound."""
    if max(value.numerator.bit_length(), value.denominator.bit_length()) > MAX_RATIONAL_BITS:
        raise Unverified("rational complexity exhausted")
    return value


def number(value):
    """Accept finite, bounded built-in numeric values, excluding booleans and coercion."""
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
        raise Unverified("coordinates and dimensions need bounded built-in finite numbers")
    return bounded(Q(value))


def array(value, minimum, maximum):
    """Reject iterators, subclasses, and oversize arrays before traversing them."""
    if type(value) not in (list, tuple) or not minimum <= len(value) <= maximum:
        raise Unverified("explicit bounded list or tuple required")
    return value


def frame_spec(frame):
    """Validate an exact signed axis permutation with depth increasing into the owner."""
    array(frame, 2, 2)
    axes, signs = frame
    array(axes, 3, 3)
    array(signs, 3, 3)
    if any(type(x) is not int for x in (*axes, *signs)):
        raise Unverified("frame needs built-in integer axes and signs")
    if sorted(axes) != [0, 1, 2] or any(s not in (-1, 1) for s in signs):
        raise Unverified("frame must be a signed axis permutation")
    return axes, signs


def cross(a, b, c):
    """Return the exact oriented double area in the declared projection frame."""
    return bounded((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def area(poly):
    """Compute exact nonnegative polygon area without a tolerance or sampling."""
    return (
        abs(
            bounded(
                sum(
                    a[0] * b[1] - a[1] * b[0]
                    for a, b in zip(poly, poly[1:] + poly[:1], strict=True)
                )
            )
        )
        / 2
    )


def clean(poly):
    """Remove only exact consecutive duplicate vertices; retain collinear seam anchors."""
    result = []
    for p in poly:
        if not result or result[-1] != p:
            result.append(p)
    if len(result) > 1 and result[0] == result[-1]:
        result.pop()
    return result if len(result) >= 3 and area(result) else []


def bounds(poly):
    """Compute a conservative exact projected AABB without changing geometric decisions."""
    return tuple((min(p[k] for p in poly), max(p[k] for p in poly)) for k in range(2))


def disjoint(first, second):
    """Skip only provably disjoint closed AABBs; touching seams still receive exact checks."""
    return any(a[1] < b[0] or b[1] < a[0] for a, b in zip(first, second, strict=True))


def no_area_overlap(first, second):
    """Exclude only zero-area or disjoint AABB intersections from positive-area clipping."""
    return any(a[1] <= b[0] or b[1] <= a[0] for a, b in zip(first, second, strict=True))


def separated_in_area(first, second):
    """Skip exact convex polygon pairs separated by an edge, retaining contact elsewhere.

    Both polygons are counterclockwise. A shared line or point has no positive
    intersection area; surface seam continuity is still checked independently.
    """
    for polygon, other in ((first, second), (second, first)):
        for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
            if all(cross(a, b, p) <= 0 for p in other):
                return True
    return False


def halfplane(poly, a, b, positive=True):
    """Clip one convex polygon against one closed exact half-plane."""
    out = []
    sign = 1 if positive else -1
    for p, q in zip(poly, poly[1:] + poly[:1], strict=True):
        dp, dq = sign * cross(a, b, p), sign * cross(a, b, q)
        if dp >= 0:
            out.append(p)
        if (dp < 0 < dq) or (dq < 0 < dp):
            t = bounded(dp / (dp - dq))
            out.append(tuple(bounded(p[k] + t * (q[k] - p[k])) for k in range(2)))
    return clean(out)


def intersection(poly, triangle, budget):
    """Intersect exact convex domains while accounting for every potential pair."""
    if no_area_overlap(bounds(poly), bounds(triangle)) or separated_in_area(poly, triangle):
        return []
    budget.clip()
    out = poly
    for a, b in zip(triangle, triangle[1:] + triangle[:1], strict=True):
        out = halfplane(out, a, b)
        if not out:
            break
    return out


def subtract(poly, triangle, budget):
    """Partition the exact positive-area difference into convex witness polygons."""
    # Remaining witnesses are additional work even when their first predicate
    # rejects the pair. Charge each before any AABB or separating-axis test.
    budget.pair()
    if no_area_overlap(bounds(poly), bounds(triangle)) or separated_in_area(poly, triangle):
        return [poly]
    budget.clip()
    inside, outside = poly, []
    for a, b in zip(triangle, triangle[1:] + triangle[:1], strict=True):
        if not inside:
            break
        rejected = halfplane(inside, a, b, False)
        if rejected:
            outside.append(rejected)
        inside = halfplane(inside, a, b)
    return outside


def surface(vertices, triangles, frame, budget, *, generation=False):
    """Validate one unambiguous single-valued triangulated height field."""
    axes, signs = frame_spec(frame)
    values = [
        tuple(number(p[a]) * s for a, s in zip(axes, signs, strict=True))
        for p in array(vertices, 3, MAX_INPUT_VERTICES if generation else MAX_INSPECTION_VERTICES)
        if array(p, 3, 3)
    ]
    result = []
    for face in array(
        triangles, 1, MAX_INPUT_TRIANGLES if generation else MAX_INSPECTION_TRIANGLES
    ):
        array(face, 3, 3)
        if (
            any(type(i) is not int or i < 0 or i >= len(values) for i in face)
            or len(set(face)) != 3
        ):
            raise Unverified("triangle has invalid indices")
        pts = [values[i] for i in face]
        det = cross(*pts)
        if not det:
            raise Unverified("selected surface is degenerate or not a height field")
        if det < 0:
            pts.reverse()
        result.append(([(p[0], p[1]) for p in pts], pts))
    boxes = [bounds(poly) for poly, _ in result]
    active = []
    for i in sorted(range(len(result)), key=lambda k: (boxes[k][0][0], boxes[k][0][1], k)):
        poly, pts = result[i]
        retained = []
        for j in active:
            budget.pair()
            if boxes[j][0][1] < boxes[i][0][0]:
                continue
            retained.append(j)
            other, op = result[j]
            if disjoint(boxes[i], boxes[j]):
                continue
            if intersection(poly, other, budget):
                raise Unverified("ambiguous overlapping height-field triangles")
            # Any indexed or geometric projected seam must have one common depth.
            for p in poly + other:
                if (
                    all(cross(a, b, p) >= 0 for a, b in zip(poly, poly[1:] + poly[:1], strict=True))
                    and all(
                        cross(a, b, p) >= 0
                        for a, b in zip(other, other[1:] + other[:1], strict=True)
                    )
                    and height(p, pts) != height(p, op)
                ):
                    raise Unverified("discontinuous depth on a projected surface seam")
        active = [*retained, i]
    return result


def height(point, pts):
    """Interpolate the selected triangle's exact affine height at one overlay vertex."""
    a, b, c = pts
    det = cross(a, b, c)
    u, v = cross(a, point, c) / det, cross(a, b, point) / det
    return bounded(a[2] + u * (b[2] - a[2]) + v * (c[2] - a[2]))


def build_bounds_index(boxes, budget):
    """Build a bounded deterministic hierarchy of exact projected boxes."""

    def build(indices):
        """Partition indices without changing triangle ordering or geometry."""
        budget.pair()
        box = tuple(
            (min(boxes[i][a][0] for i in indices), max(boxes[i][a][1] for i in indices))
            for a in range(2)
        )
        if len(indices) <= 8:
            return box, tuple(indices), None
        axis = max(range(2), key=lambda a: box[a][1] - box[a][0])
        ordered = sorted(indices, key=lambda i: (sum(boxes[i][axis]), i))
        middle = len(ordered) // 2
        return box, None, (build(ordered[:middle]), build(ordered[middle:]))

    return build(list(range(len(boxes))))


def query_bounds_index(index, boxes, query, budget):
    """Return every positive-area box candidate in original deterministic order."""
    stack, found = [index], []
    while stack:
        box, leaves, children = stack.pop()
        budget.pair()
        if no_area_overlap(box, query):
            continue
        if leaves is not None:
            for item in leaves:
                budget.pair()
                if not no_area_overlap(boxes[item], query):
                    found.append(item)
        else:
            stack.extend(children)
    return sorted(found)


def overlay(cells, support, budget):
    """Cover every input cell with exact support domains, returning uncovered witnesses."""
    output, uncovered = [], []
    support_boxes = [bounds(domain) for domain, _ in support]
    support_index = build_bounds_index(support_boxes, budget)
    for poly, sources in cells:
        remaining = [poly]
        box = bounds(poly)
        for i in query_bounds_index(support_index, support_boxes, box, budget):
            domain, points = support[i]
            clipped = intersection(poly, domain, budget)
            if clipped:
                output.append((clipped, sources + [points]))
                if len(output) > MAX_CELLS:
                    raise Unverified("overlay cell limit exceeded")
            revised = []
            for old in remaining:
                revised.extend(subtract(old, domain, budget))
            remaining = revised
            if len(remaining) > MAX_CELLS:
                raise Unverified("coverage witness limit exceeded")
        uncovered.extend(remaining)
        if len(uncovered) > MAX_CELLS:
            raise Unverified("coverage witness limit exceeded")
    return output, uncovered


def polygons_json(polygons):
    """Serialize exact rational missing-domain vertices without rounding tiny gaps."""
    return [[[str(v) for v in p] for p in poly] for poly in polygons]


def inspect_attachment(
    *,
    lower_vertices,
    lower_triangles,
    upper_vertices,
    upper_triangles,
    owner_front_vertices,
    owner_front_triangles,
    owner_back_vertices,
    owner_back_triangles,
    minimum_embed,
    maximum_embed,
    minimum_remaining_thickness,
    minimum_relief_height=0.0,
    frame=((0, 2, 1), (1, 1, 1)),
    scope="required_full_patch",
):
    """Prove complete supplied lower-patch containment and upper exposure in exact cells.

    Available failures are geometric counterexamples. Unsupported/malformed input
    or work exhaustion returns unverified, never a pass. The complete patch and its
    owner/component mapping must be independently established by a host inspector.
    """
    budget = Budget()
    try:
        if type(scope) is not str or scope not in (
            "required_full_patch",
            "intentional_open",
            "modular_clearance",
        ):
            raise Unverified("unsupported attachment scope")
        if scope != "required_full_patch":
            return {
                "status": "not_applicable",
                "passed": None,
                "scope": scope,
                "reason": "full-patch support is not declared; no assembly acceptance implied",
            }
        low, high, remain, raised = map(
            number,
            (
                minimum_embed,
                maximum_embed,
                minimum_remaining_thickness,
                minimum_relief_height,
            ),
        )
        if low <= 0 or high < low or remain <= 0 or raised < 0:
            raise Unverified("positive ordered embed and thickness bounds required")
        lower = surface(lower_vertices, lower_triangles, frame, budget)
        front = surface(owner_front_vertices, owner_front_triangles, frame, budget)
        back = surface(owner_back_vertices, owner_back_triangles, frame, budget)
        upper = surface(upper_vertices, upper_triangles, frame, budget)
        cells = [(poly, [pts]) for poly, pts in lower]
        _, upper_outside = overlay([(poly, [pts]) for poly, pts in upper], lower, budget)
        missing = {"upper_outside_lower": polygons_json(upper_outside)}
        for label, support in (("front", front), ("back", back), ("upper", upper)):
            cells, gaps = overlay(cells, support, budget)
            missing[label] = polygons_json(gaps)
        violations, embeds, remainders, heights = [], [], [], []
        for index, (poly, sources) in enumerate(cells):
            lo, fr, ba, up = sources
            e = [height(p, lo) - height(p, fr) for p in poly]
            r = [height(p, ba) - height(p, lo) for p in poly]
            h = [height(p, fr) - height(p, up) for p in poly]
            embeds.extend(e)
            remainders.extend(r)
            heights.extend(h)
            if min(e) < low or max(e) > high or min(r) < remain or min(h) < raised:
                violations.append(
                    {
                        "cell": index,
                        "polygon": polygons_json([poly])[0],
                        "embed": [str(min(e)), str(max(e))],
                        "remaining_thickness": [str(min(r)), str(max(r))],
                        "relief_height": [str(min(h)), str(max(h))],
                    }
                )
        passed = not any(missing.values()) and not violations
        return {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "scope": scope,
            "proof": "complete exact affine overlay, no sampling",
            "lower_triangle_count": len(lower),
            "covered_cell_count": len(cells),
            "uncovered_polygons": missing,
            "violations": violations,
            "embed_range": [str(min(embeds)), str(max(embeds))] if embeds else None,
            "remaining_thickness_range": [str(min(remainders)), str(max(remainders))]
            if remainders
            else None,
            "relief_height_range": [str(min(heights)), str(max(heights))] if heights else None,
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
            "artifact_identity_verified": False,
            "owner_volume_verified": False,
            "meaning": (
                "full patch lies between selected graphs; "
                "complete solid owner needs separate verification"
            ),
        }
    except (Unverified, OverflowError, ZeroDivisionError) as exc:
        return {
            "status": "unverified",
            "passed": None,
            "reason": str(exc),
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
            "artifact_identity_verified": False,
        }


def inspect_inserted_root(
    *,
    lower_vertices,
    lower_triangles,
    upper_vertices,
    upper_triangles,
    owner_front_vertices,
    owner_front_triangles,
    owner_back_vertices,
    owner_back_triangles,
    minimum_overlap,
    frame=((0, 2, 1), (1, 1, 1)),
):
    """Prove positive depth-interval overlap over an entire declared inserted-root patch.

    Upper/lower mean the child's front/back in the declared inward depth frame.
    Free geometry outside the explicit root patch is not asserted to overlap.
    No outward exposure is required. Complete owner/subject solid eligibility and
    actual artifact correspondence remain separate mandatory host checks.
    """
    budget = Budget()
    try:
        required = number(minimum_overlap)
        if required <= 0:
            raise Unverified("inserted root requires positive minimum overlap")
        front = surface(upper_vertices, upper_triangles, frame, budget)
        back = surface(lower_vertices, lower_triangles, frame, budget)
        owner_front = surface(owner_front_vertices, owner_front_triangles, frame, budget)
        owner_back = surface(owner_back_vertices, owner_back_triangles, frame, budget)
        _, outside = overlay([(poly, [pts]) for poly, pts in back], front, budget)
        missing = {"child_back_outside_front": polygons_json(outside)}
        cells = [(poly, [pts]) for poly, pts in front]
        for label, support in (
            ("child_back", back),
            ("owner_front", owner_front),
            ("owner_back", owner_back),
        ):
            cells, gaps = overlay(cells, support, budget)
            missing[label] = polygons_json(gaps)
        minima, upper_bounds, violations = [], [], []
        for index, (poly, sources) in enumerate(cells):
            child_front, child_back, parent_front, parent_back = sources
            differences = []
            for point in poly:
                cf, cb, pf, pb = (
                    height(point, p) for p in (child_front, child_back, parent_front, parent_back)
                )
                differences.append((cb - cf, cb - pf, pb - cf, pb - pf))
            # Interval overlap is the minimum of four affine differences. This
            # concave function attains its minimum at an exact cell vertex.
            minimum = min(min(row) for row in differences)
            upper_bound = min(max(row[i] for row in differences) for i in range(4))
            minima.append(minimum)
            upper_bounds.append(upper_bound)
            if minimum < required:
                violations.append(
                    {
                        "cell": index,
                        "polygon": polygons_json([poly])[0],
                        "minimum_overlap": str(minimum),
                    }
                )
        passed = not any(missing.values()) and not violations
        return {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "scope": "required_root_patch",
            "proof": "complete exact interval-overlap overlay",
            "selected_root_front_triangle_count": len(front),
            "selected_root_back_triangle_count": len(back),
            "covered_cell_count": len(cells),
            "uncovered_polygons": missing,
            "violations": violations,
            "minimum_overlap_m_exact": str(min(minima)) if minima else None,
            "maximum_overlap_m_upper_bound": str(max(upper_bounds)) if upper_bounds else None,
            "outward_exposure_required": False,
            "free_subject_area_overlap_claimed": False,
            "owner_volume_verified": False,
            "artifact_identity_verified": False,
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
        }
    except (Unverified, ValueError, OverflowError, ZeroDivisionError) as exc:
        return {
            "status": "unverified",
            "passed": None,
            "reason": str(exc),
            "scope": "required_root_patch",
            "owner_volume_verified": False,
            "artifact_identity_verified": False,
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
        }


def _projected_boundary_segments(front, budget):
    """Cancel exact oriented cap intervals, including nonmatching subdivisions.

    This is used only after complete embedded-solid and single-valued-domain
    checks. Interior triangulation edges cancel; outer and hole edges remain.
    """
    from .constant_back import _boundary_events

    segments = []
    for line, events in _boundary_events(((1, front),), budget).items():
        winding = 0
        previous = None
        for coordinate, change in sorted(events.items()):
            budget.edge()
            if previous is not None and previous < coordinate and winding:
                if abs(winding) != 1:
                    raise Unverified("projected boundary has ambiguous interval multiplicity")
                if line[0] == "vertical":
                    a, b = (line[1], previous), (line[1], coordinate)
                else:
                    a = (previous, bounded(line[1] * previous + line[2]))
                    b = (coordinate, bounded(line[1] * coordinate + line[2]))
                segments.append((a, b))
            winding += change
            previous = coordinate
        if winding:
            raise Unverified("projected boundary has an unclosed interval")
    return segments


def _boundary_covers_zero_edge(a, b, boundary, budget):
    """Prove complete zero-edge coverage by exact boundary intervals, without sampling."""
    axis = 0 if abs(b[0] - a[0]) >= abs(b[1] - a[1]) else 1
    denominator = b[axis] - a[axis]
    if not denominator:
        raise Unverified("zero locus contains a zero-length edge")
    intervals = []
    for p, q in boundary:
        budget.edge()
        if cross(a, b, p) or cross(a, b, q):
            continue
        low, high = sorted(
            (bounded((p[axis] - a[axis]) / denominator),
             bounded((q[axis] - a[axis]) / denominator))
        )
        low, high = max(Q(0), low), min(Q(1), high)
        if low <= high:
            intervals.append((low, high))
    reached = Q(0)
    for low, high in sorted(intervals):
        budget.edge()
        if low > reached:
            return False
        reached = max(reached, high)
        if reached == 1:
            return True
    return False


def _require_boundary_only_zero_thickness(front, cells, budget):
    """Prove positive interior thickness from the complete affine zero locus.

    Nonnegative affine thickness vanishes only at a vertex, an edge, or an
    entire cell. Reject zero cells, and require every zero vertex and complete
    zero edge to belong to the exact projected boundary. An edge whose endpoints
    are boundary vertices can still cross the interior and must not be accepted.
    """
    boundary = _projected_boundary_segments(front, budget)
    zero_vertices = set()
    zero_edges = set()
    for polygon, sources in cells:
        values = [bounded(height(p, sources[1]) - height(p, sources[0])) for p in polygon]
        if not values or min(values) < 0:
            raise Unverified("complete owner has crossed bounding graphs")
        if max(values) == 0:
            raise Unverified("complete owner has a positive-area zero-thickness cell")
        for index, point in enumerate(polygon):
            budget.edge()
            if values[index] != 0:
                continue
            zero_vertices.add(point)
            following = (index + 1) % len(polygon)
            if values[following] == 0:
                zero_edges.add(tuple(sorted((point, polygon[following]))))
    for point in sorted(zero_vertices):
        found = False
        for a, b in boundary:
            budget.edge()
            if cross(a, b, point) == 0 and all(
                min(a[k], b[k]) <= point[k] <= max(a[k], b[k]) for k in range(2)
            ):
                found = True
                break
        if not found:
            raise Unverified("complete owner has an interior zero-thickness vertex")
    for a, b in sorted(zero_edges):
        if not _boundary_covers_zero_edge(a, b, boundary, budget):
            raise Unverified("complete owner has an interior zero-thickness edge")


def verify_height_field_solid(
    *,
    vertices,
    triangles,
    front_face_indices,
    back_face_indices,
    frame=((0, 2, 1), (1, 1, 1)),
):
    """Verify a complete closed solid of front/back graphs and optional vertical sides.

    This bounded eligibility check excludes omitted internal/cavity/intervening
    boundaries. It is not a general point-in-arbitrary-solid containment method.
    Supply the complete actual owner component, never an outer-shell subset.
    Thickness must be positive in the projected interior. Exact front/back
    convergence is permitted only on the complete projected boundary, after the
    same closed, embedded, outward-solid checks have succeeded.
    """
    budget = Budget()
    try:
        raw_vertices = array(vertices, 4, MAX_INSPECTION_VERTICES)
        raw_faces = array(triangles, 4, MAX_INSPECTION_TRIANGLES)
        axes, signs = frame_spec(frame)
        vv = [tuple(number(c) for c in array(p, 3, 3)) for p in raw_vertices]
        faces = []
        for face in raw_faces:
            array(face, 3, 3)
            if any(type(i) is not int or not 0 <= i < len(vv) for i in face):
                raise Unverified("complete owner has invalid face indices")
            faces.append(tuple(face))
        # Topology alone permits folded side walls; also prove the actual surface embedded.
        shell = TriangulatedShellGeometry(
            vertices=[tuple(float(c) for c in p) for p in vv], triangles=faces
        )
        _validate_embedded(shell)
        groups = []
        for group in (front_face_indices, back_face_indices):
            array(group, 1, len(faces))
            if any(type(i) is not int or not 0 <= i < len(faces) for i in group) or list(
                group
            ) != sorted(set(group)):
                raise Unverified("owner groups need sorted complete unique face indices")
            groups.append(set(group))
        front_ids, back_ids = groups
        if front_ids & back_ids:
            raise Unverified("owner front/back groups overlap")
        framed = [tuple(p[a] * s for a, s in zip(axes, signs, strict=True)) for p in vv]
        inversions = sum(axes[i] > axes[j] for i in range(3) for j in range(i + 1, 3))
        hand = (-1 if inversions % 2 else 1) * signs[0] * signs[1] * signs[2]
        for i, face in enumerate(faces):
            det = cross(*[framed[j] for j in face]) * hand
            if (i in front_ids and det >= 0) or (i in back_ids and det <= 0):
                raise Unverified("selected owner group has wrong projected orientation")
            if i not in front_ids | back_ids and det != 0:
                raise Unverified("owner contains omitted or intervening nonvertical faces")
        front = surface(raw_vertices, [faces[i] for i in sorted(front_ids)], frame, budget)
        back = surface(raw_vertices, [faces[i] for i in sorted(back_ids)], frame, budget)
        # Equal complete projected boundaries and a constant back need no
        # cross-tessellation overlay. The exact proof preserves all old limits.
        from .constant_back import constant_back_thickness, separated_depth_bounds

        constant_bounds = constant_back_thickness(front, back, budget)
        separated_bounds = (
            separated_depth_bounds(front, back, budget)
            if constant_bounds is None and len(front) * len(back) > MAX_CELLS
            else None
        )
        proven_bounds = constant_bounds if constant_bounds is not None else separated_bounds
        if proven_bounds is None:
            cells, gaps = overlay([(poly, [pts]) for poly, pts in front], back, budget)
            _, reverse_gaps = overlay([(poly, [pts]) for poly, pts in back], front, budget)
            if gaps or reverse_gaps:
                raise Unverified("complete owner front/back domains differ")
            thickness = [
                height(p, sources[1]) - height(p, sources[0])
                for poly, sources in cells
                for p in poly
            ]
        else:
            thickness = list(proven_bounds)
        if not thickness or min(thickness) < 0:
            raise Unverified("complete owner has crossed or zero-thickness bounding graphs")
        boundary_closure = min(thickness) == 0
        if boundary_closure:
            if constant_bounds is not None:
                # Constant-back domain equality was proved above. Front cells
                # already capture every affine thickness extremum and zero set.
                cells = [(poly, [points, back[0][1]]) for poly, points in front]
            _require_boundary_only_zero_thickness(front, cells, budget)
        result = {
            "status": "passed",
            "passed": True,
            "owner_volume_verified": True,
            "improper_triangle_contact_checked": True,
            "domain": "complete single closed height-field solid",
            "complete_triangle_count": len(faces),
            "front_triangle_count": len(front_ids),
            "back_triangle_count": len(back_ids),
            "side_triangle_count": len(faces) - len(front_ids) - len(back_ids),
            "thickness_range": [str(min(thickness)), str(max(thickness))],
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
            "artifact_identity_verified": False,
        }
        if separated_bounds is not None:
            result["thickness_range_kind"] = "conservative_global_separation_bounds"
            result["thickness_proof"] = "strict depth separation and exact equal projected domains"
        if boundary_closure:
            result["boundary_only_zero_thickness"] = True
            result["zero_locus_proof"] = "complete exact projected-boundary interval coverage"
        return result
    except (Unverified, ValueError, OverflowError, ZeroDivisionError) as exc:
        return {
            "status": "unverified",
            "passed": None,
            "owner_volume_verified": False,
            "reason": str(exc),
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
        }


def world(point, frame):
    """Invert the signed frame without introducing an arbitrary transformation callback."""
    axes, signs = frame_spec(frame)
    out = [0.0, 0.0, 0.0]
    for i, a in enumerate(axes):
        out[a] = float(point[i]) * signs[i]
    return tuple(out)


def float32(vertices):
    """Round supplied vertices exactly as a binary32 storage simulation, not export evidence."""
    return [tuple(struct.unpack("f", struct.pack("f", c))[0] for c in p) for p in vertices]


def build_owner_relief(
    *,
    footprint_vertices,
    footprint_triangles,
    owner_front_vertices,
    owner_front_triangles,
    owner_back_vertices,
    owner_back_triangles,
    embed_depth,
    minimum_embed,
    maximum_embed,
    minimum_remaining_thickness,
    minimum_relief_height=0.0,
    frame=((0, 2, 1), (1, 1, 1)),
):
    """Build a closed owner-conforming relief from an explicit (u,v,height) footprint.

    Exact overlay retains the entire footprint; clipping never silently trims an
    unsupported overhang. Owner front/back are explicit selected height fields.
    Output is the existing shell plus ephemeral face-role metadata and diagnostics.
    """
    budget = Budget()
    e = number(embed_depth)
    if e <= 0:
        raise Unverified("embed_depth must be positive")
    # Footprint coordinates already use (u,v,height), independent of asset axes.
    footprint = surface(
        footprint_vertices,
        footprint_triangles,
        ((0, 1, 2), (1, 1, 1)),
        budget,
        generation=True,
    )
    if any(p[2] <= 0 for _, pts in footprint for p in pts):
        raise Unverified("footprint outward heights must be positive")
    front = surface(owner_front_vertices, owner_front_triangles, frame, budget, generation=True)
    back = surface(owner_back_vertices, owner_back_triangles, frame, budget, generation=True)
    cells = [(poly, [pts]) for poly, pts in footprint]
    for support in (front, back):
        cells, missing = overlay(cells, support, budget)
        if missing:
            raise ValueError(
                "unsupported footprint; exact uncovered polygons=" + str(polygons_json(missing))
            )
    # Split every cell boundary at all overlay vertices; this avoids T-junctions.
    anchors = sorted({p for poly, _ in cells for p in poly})
    axis_anchors = [sorted(anchors, key=lambda p: (p[a], p[1 - a])) for a in range(2)]
    axis_coordinates = [[p[a] for p in axis_anchors[a]] for a in range(2)]
    vertices, index, top_faces, base_faces, edge_uses = [], {}, [], [], {}

    def vertex(p, sources, top):
        """Deduplicate exact conforming graph positions before floating serialization."""
        h = height(p, sources[1]) - height(p, sources[0]) if top else height(p, sources[1]) + e
        key = (p[0], p[1], h)
        if key not in index:
            index[key] = len(vertices)
            vertices.append(world(key, frame))
        return index[key]

    for poly, sources in cells:
        border = []
        for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
            along = []
            ranges = [
                (
                    bisect_left(axis_coordinates[k], min(a[k], b[k])),
                    bisect_right(axis_coordinates[k], max(a[k], b[k])),
                )
                for k in range(2)
            ]
            axis = min(range(2), key=lambda k: ranges[k][1] - ranges[k][0])
            start, end = ranges[axis]
            # Every point on this closed segment lies in both coordinate ranges.
            # Search the smaller exact range, then retain the original predicates.
            for p in axis_anchors[axis][start:end]:
                budget.edge()
                if cross(a, b, p) == 0 and all(
                    min(a[k], b[k]) <= p[k] <= max(a[k], b[k]) for k in range(2)
                ):
                    along.append(p)
            along.sort(key=lambda p: (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1]))
            border.extend(along[:-1])
        top_ring = [vertex(p, sources, True) for p in border]
        base_ring = [vertex(p, sources, False) for p in border]
        if all(
            cross(border[i - 1], p, border[(i + 1) % len(border)]) > 0 for i, p in enumerate(border)
        ):
            # Affine strictly convex cells need only n-2 triangles; retain every
            # boundary edge without redundant centre vertices or fan triangles.
            top_faces.extend(
                (top_ring[0], top_ring[i], top_ring[i + 1]) for i in range(1, len(border) - 1)
            )
            base_faces.extend(
                (base_ring[0], base_ring[i + 1], base_ring[i]) for i in range(1, len(border) - 1)
            )
        else:
            # Collinear anchors encode neighbouring overlay seams; preserve every
            # anchor with the conservative nondegenerate centre fan.
            center = tuple(bounded(sum(p[k] for p in border) / len(border)) for k in range(2))
            tc, bc = vertex(center, sources, True), vertex(center, sources, False)
            for i in range(len(border)):
                j = (i + 1) % len(border)
                top_faces.append((tc, top_ring[i], top_ring[j]))
                base_faces.append((bc, base_ring[j], base_ring[i]))
        for a, b in zip(border, border[1:] + border[:1], strict=True):
            ta, tb = vertex(a, sources, True), vertex(b, sources, True)
            ba, bb = vertex(a, sources, False), vertex(b, sources, False)
            key = tuple(sorted((a, b)))
            edge_uses.setdefault(key, []).append((ta, tb, ba, bb))
    sides = []
    for uses in edge_uses.values():
        if len(uses) == 1:
            ta, tb, ba, bb = uses[0]
            sides.extend(((ta, ba, bb), (ta, bb, tb)))
        elif len(uses) != 2:
            raise Unverified("non-manifold footprint edge")
    faces = top_faces + base_faces + sides
    # A signed-axis frame may reverse orientation; use actual emitted volume.
    volume6 = sum(
        sum(
            vertices[a][k]
            * (
                vertices[b][(k + 1) % 3] * vertices[c][(k + 2) % 3]
                - vertices[b][(k + 2) % 3] * vertices[c][(k + 1) % 3]
            )
            for k in range(3)
        )
        for a, b, c in faces
    )
    if volume6 < 0:
        faces = [tuple(reversed(f)) for f in faces]
    shell = TriangulatedShellGeometry(vertices=vertices, triangles=faces)
    n = len(top_faces)
    role = {
        "upper": list(range(n)),
        "lower": list(range(n, 2 * n)),
        "side": list(range(2 * n, len(faces))),
    }
    reports = {}
    for label, cast in (
        ("emitted_binary64", lambda value: value),
        ("simulated_binary32", float32),
    ):
        actual = cast(vertices)
        TriangulatedShellGeometry(vertices=actual, triangles=faces)
        report = inspect_attachment(
            lower_vertices=actual,
            lower_triangles=faces[n : 2 * n],
            upper_vertices=actual,
            upper_triangles=faces[:n],
            owner_front_vertices=cast(owner_front_vertices),
            owner_front_triangles=owner_front_triangles,
            owner_back_vertices=cast(owner_back_vertices),
            owner_back_triangles=owner_back_triangles,
            minimum_embed=minimum_embed,
            maximum_embed=maximum_embed,
            minimum_remaining_thickness=minimum_remaining_thickness,
            minimum_relief_height=minimum_relief_height,
            frame=frame,
        )
        reports[label] = report
        if report["passed"] is not True:
            raise ValueError(label + " attachment not proven: " + str(report))
    return {
        "shell": shell,
        "face_roles": role,
        "diagnostics": reports,
        "generation_exact_clips": budget.clips,
        "generation_broad_phase_pairs": budget.pair_scans,
        "generation_edge_tests": budget.edge_tests,
        "actual_export_inspected": False,
    }
