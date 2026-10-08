"""Compose explicit bounded height profiles into a complete closed owner front.

This is a pure construction kernel. It infers no semantic ownership, reference
feature, hidden depth or material. Profiles have zero boundary height; all
requested profile area survives. Exact affine graph composition precedes one
float serialization, and every output graph edge remains conforming.
"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from fractions import Fraction as Q

from codex_blender_modeler.structural_geometry.profiled_relief import _validate_embedded
from codex_blender_modeler.structural_geometry.triangle_shell import (
    TriangulatedShellGeometry,
)

from . import owner_relief as m
from .partition_heightfield import _area3, _dot, _normal, _orient_closed, _volume

MAX_PROFILES = 24
MAX_OUTPUT_TRIANGLES = 16384
MAX_OUTPUT_VERTICES = 16384


def plane_coefficients(points):
    """Return an exact canonical affine depth plane for coplanarity decisions."""
    (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = points
    det = m.cross((x1, y1), (x2, y2), (x3, y3))
    if not det:
        raise ValueError("affine graph plane is degenerate")
    a = m.bounded(((z2 - z1) * (y3 - y1) - (z3 - z1) * (y2 - y1)) / det)
    b = m.bounded(((x2 - x1) * (z3 - z1) - (x3 - x1) * (z2 - z1)) / det)
    return a, b, m.bounded(z1 - a * x1 - b * y1)


def plane_points(coeff):
    """Represent an exact affine function without retaining arbitrary source triangles."""
    a, b, c = coeff
    return (
        (Q(0), Q(0), c),
        (Q(1), Q(0), m.bounded(a + c)),
        (Q(0), Q(1), m.bounded(b + c)),
    )


def subtract_planes(owner, profile):
    """Move the owner outward by the complete explicit nonnegative profile height."""
    a = plane_coefficients(owner)
    b = plane_coefficients(profile)
    return plane_points(tuple(m.bounded(x - y) for x, y in zip(a, b, strict=False)))


def boundary_rows(surface):
    """Inventory all source outer and hole edges without silently welding cracks."""
    edges = defaultdict(list)
    for poly, plane in surface:
        for a, b in zip(poly, poly[1:] + poly[:1], strict=False):
            edges[tuple(sorted((a, b)))].append((a, b, plane))
    if any(len(rows) > 2 for rows in edges.values()):
        raise ValueError("graph boundary is nonmanifold")
    return [rows[0] for rows in edges.values() if len(rows) == 1]


def edge_splitter(points, budget):
    """Index both axes and charge every visited anchor before exact edge predicates."""
    by_axis = [sorted(set(points), key=lambda p: (p[axis], p[1 - axis])) for axis in (0, 1)]
    keys = [[p[axis] for p in by_axis[axis]] for axis in (0, 1)]

    def split(a, b):
        """Return all on-edge controls in source-edge order within the shared work budget."""
        ranges = []
        for axis in (0, 1):
            lo, hi = sorted((a[axis], b[axis]))
            ranges.append((bisect_left(keys[axis], lo), bisect_right(keys[axis], hi)))
        axis = min((0, 1), key=lambda axis: ranges[axis][1] - ranges[axis][0])
        lo, hi = ranges[axis]
        dv = (b[0] - a[0], b[1] - a[1])
        den = dv[0] * dv[0] + dv[1] * dv[1]
        if not den:
            raise ValueError("zero graph edge")
        found = []
        for p in by_axis[axis][lo:hi]:
            budget.edge()
            if not min(a[1 - axis], b[1 - axis]) <= p[1 - axis] <= max(a[1 - axis], b[1 - axis]):
                continue
            if m.cross(a, b, p) == 0:
                t = m.bounded(((p[0] - a[0]) * dv[0] + (p[1] - a[1]) * dv[1]) / den)
                if 0 <= t <= 1:
                    found.append((t, p))
        return [p for _, p in sorted(set(found))]

    return split


def compose_owner_front(
    *,
    vertices,
    triangles,
    front_face_indices,
    back_face_indices,
    profiles,
    maximum_profile_height,
    minimum_remaining_thickness,
    frame=((0, 2, 1), (1, 1, 1)),
):
    """Add zero-edge height profiles to one complete eligible owner and preserve its back graph.

    Each profile is an explicit mapping with unique id, vertices [(u,v,height)]
    and triangles. Intersecting profiles add heights. No clipping, automatic
    repair, global rounding, sampling or source-derived semantic inference occurs.
    """
    axes, signs = m.frame_spec(frame)
    max_height = m.number(maximum_profile_height)
    min_thickness = m.number(minimum_remaining_thickness)
    if max_height <= 0 or min_thickness <= 0:
        raise ValueError("positive height and remaining thickness bounds required")
    m.array(profiles, 1, MAX_PROFILES)
    eligibility = m.verify_height_field_solid(
        vertices=vertices,
        triangles=triangles,
        front_face_indices=front_face_indices,
        back_face_indices=back_face_indices,
        frame=frame,
    )
    if eligibility.get("passed") is not True:
        raise ValueError("complete owner ineligible: " + str(eligibility))
    budget = m.Budget()
    front = m.surface(vertices, [triangles[i] for i in front_face_indices], frame, budget)
    back = m.surface(vertices, [triangles[i] for i in back_face_indices], frame, budget)
    domain_area = sum(m.area(p) for p, _ in front)
    source_volume = _volume(vertices, triangles)
    cells = [(poly, plane, frozenset()) for poly, plane in front]
    added_volume = Q(0)
    receipts = []
    ids = set()
    # Validate original thickness everywhere; outward additions cannot reduce it.
    overlaps, missing = m.overlay([(p, [plane]) for p, plane in front], back, budget)
    if missing:
        raise ValueError("owner front/back domains disagree")
    minimum = min(
        m.height(p, planes[1]) - m.height(p, planes[0]) for poly, planes in overlaps for p in poly
    )
    if minimum < min_thickness:
        raise ValueError("source thickness below declared remaining thickness")
    for profile in profiles:
        if type(profile) is not dict or set(profile) != {"id", "vertices", "triangles"}:
            raise ValueError("explicit profile id, vertices and triangles required")
        name = profile["id"]
        if type(name) is not str or not 1 <= len(name) <= 128 or name in ids:
            raise ValueError("unique bounded profile id required")
        ids.add(name)
        surface = m.surface(
            profile["vertices"],
            profile["triangles"],
            ((0, 1, 2), (1, 1, 1)),
            budget,
            generation=True,
        )
        for _, plane in surface:
            if any(p[2] < 0 or p[2] > max_height for p in plane):
                raise ValueError("profile height exceeds explicit nonnegative bound")
        for a, b, plane in boundary_rows(surface):
            if m.height(a, plane) != 0 or m.height(b, plane) != 0:
                raise ValueError("profile boundary height must be exactly zero")
        footprint_area = sum(m.area(p) for p, _ in surface)
        # Full footprint is checked against the complete current graph, including
        # every prior feature; coplanar cells may coalesce only after exact cover.
        inside = []
        collapsed = 0
        support = [(poly, (plane, features)) for poly, plane, features in cells]
        for poly, profile_plane in surface:
            rows, uncovered = m.overlay([(poly, [profile_plane])], support, budget)
            if uncovered:
                raise ValueError("complete profile footprint escapes owner: " + name)
            signatures = {(plane_coefficients(data[1][0]), data[1][1]) for _, data in rows}
            if len(signatures) == 1:
                prior_plane, features = rows[0][1][1]
                inside.append(
                    (
                        poly,
                        subtract_planes(prior_plane, profile_plane),
                        features | {name},
                    )
                )
                collapsed += max(0, len(rows) - 1)
            else:
                for region, data in rows:
                    prior_plane, features = data[1]
                    inside.append(
                        (
                            region,
                            subtract_planes(prior_plane, profile_plane),
                            features | {name},
                        )
                    )
        outside = []
        for poly, plane, features in cells:
            _, remaining = m.overlay([(poly, [plane])], surface, budget)
            outside.extend((p, plane, features) for p in remaining)
        cells = outside + inside
        if len(cells) > m.MAX_CELLS:
            raise ValueError(
                "composed front exceeds bounded overlay cell count: " + str(len(cells))
            )
        if sum(m.area(p) for p, _, _ in cells) != domain_area:
            raise ValueError("composition changed complete projected domain")
        integral = sum(
            m.area(poly) * sum(point[2] for point in plane) / 3 for poly, plane in surface
        )
        added_volume = m.bounded(added_volume + integral)
        receipts.append(
            {
                "id": name,
                "full_footprint_area": str(footprint_area),
                "added_volume": str(integral),
                "boundary_height_zero": True,
                "full_footprint_retained": True,
                "coplanar_cells_removed": collapsed,
                "front_cells_after": len(cells),
            }
        )
    # Only true outer boundary controls cross between front and back. Interior
    # front detail never subdivides the rear merely by collinearity in projection.
    boundary = boundary_rows(front)
    front_points = {p for poly, _, _ in cells for p in poly}
    back_points = {p for poly, _ in back for p in poly}
    joint_split = edge_splitter(front_points | back_points, budget)
    boundary_knots = set()
    for a, b, _ in boundary:
        boundary_knots.update(joint_split(a, b))
    front_split = edge_splitter(front_points | boundary_knots, budget)
    back_split = edge_splitter(back_points | boundary_knots, budget)
    output = []
    lookup = {}
    faces = []
    groups = {"front": [], "back": [], "sides": []}
    feature_groups = {name: [] for name in ids}
    # A CCW UV graph points along the signed frame's depth direction iff its
    # signed permutation is right handed. Front needs the opposite orientation.
    frame_normal = _normal(
        [
            m.world((0, 0, 0), frame),
            m.world((1, 0, 0), frame),
            m.world((0, 1, 0), frame),
        ]
    )
    depth_direction = m.world((0, 0, 1), frame)
    hand = _dot(frame_normal, depth_direction)

    def vertex(uv, depth):
        """Deduplicate exact full positions before the sole binary64 serialization."""
        key = (uv[0], uv[1], depth)
        if key not in lookup:
            if len(output) >= MAX_OUTPUT_VERTICES:
                raise ValueError("compositor vertex budget exhausted")
            lookup[key] = len(output)
            output.append(m.world(key, frame))
        return lookup[key]

    def add_face(f, role, features=()):
        """Retain a complete role partition with an explicit output triangle ceiling."""
        if len(faces) >= MAX_OUTPUT_TRIANGLES:
            raise ValueError("compositor triangle budget exhausted")
        index = len(faces)
        faces.append(f)
        groups[role].append(index)
        for name in features:
            feature_groups[name].append(index)

    def emit(poly, plane, role, features, split):
        """Triangulate one convex affine cell without dropping collinear seam anchors."""
        loop = []
        for a, b in zip(poly, poly[1:] + poly[:1], strict=False):
            loop.extend(split(a, b)[:-1])
        if len(loop) < 3:
            raise ValueError("composed cell collapsed")
        if all(
            m.cross(loop[i - 1], loop[i], loop[(i + 1) % len(loop)]) > 0 for i in range(len(loop))
        ):
            uvfaces = [(loop[0], loop[i], loop[i + 1]) for i in range(1, len(loop) - 1)]
        else:
            center = tuple(m.bounded(sum(p[i] for p in loop) / len(loop)) for i in (0, 1))
            uvfaces = [(center, a, b) for a, b in zip(loop, loop[1:] + loop[:1], strict=False)]
        for uv in uvfaces:
            if m.cross(*uv) <= 0:
                raise ValueError("nonpositive composed cap triangle")
            f = [vertex(p, m.height(p, plane)) for p in uv]
            if (role == "front" and hand > 0) or (role == "back" and hand < 0):
                f.reverse()
            add_face(f, role, features)

    for poly, plane, features in cells:
        emit(poly, plane, "front", features, front_split)
    for poly, plane in back:
        emit(poly, plane, "back", (), back_split)
    back_boxes = [m.bounds(poly) for poly, _ in back]
    for a, b, front_plane in boundary:
        knots = joint_split(a, b)
        for p, q in zip(knots, knots[1:], strict=False):
            midpoint = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            back_planes = []
            for (poly, plane), box in zip(back, back_boxes, strict=False):
                budget.pair()
                if not all(box[i][0] <= midpoint[i] <= box[i][1] for i in (0, 1)):
                    continue
                if all(
                    m.cross(c, d, midpoint) >= 0
                    for c, d in zip(poly, poly[1:] + poly[:1], strict=False)
                ):
                    back_planes.append(plane)
            if not back_planes:
                raise ValueError("back graph omits boundary segment")
            back_plane = back_planes[0]
            fa = vertex(p, m.height(p, front_plane))
            fb = vertex(q, m.height(q, front_plane))
            ba = vertex(p, m.height(p, back_plane))
            bb = vertex(q, m.height(q, back_plane))
            add_face([fa, ba, bb], "sides")
            add_face([fa, bb, fb], "sides")
    faces = _orient_closed(output, faces)
    checks = {}
    expected_volume = source_volume + float(added_volume)
    for label, cast in [("binary64", lambda v: v), ("binary32", m.float32)]:
        vv = cast(output)
        shell = TriangulatedShellGeometry(
            vertices=[tuple(p) for p in vv], triangles=[tuple(f) for f in faces]
        )
        _validate_embedded(shell)
        volume = _volume(vv, faces)
        tolerance = (
            max(1e-11, abs(expected_volume) * 1e-10)
            if label == "binary64"
            else max(1e-7, abs(expected_volume) * 1e-5)
        )
        if abs(volume - expected_volume) > tolerance:
            raise ValueError(label + " integrated volume disagrees with full profile integral")
        checks[label] = {
            "closed_embedded": True,
            "volume": volume,
            "expected_volume": expected_volume,
            "volume_tolerance": tolerance,
            "surface_area": _area3(vv, faces),
        }
    return {
        "vertices": [list(p) for p in output],
        "triangles": faces,
        "face_roles": groups,
        "feature_face_groups": feature_groups,
        "diagnostics": {
            "status": "constructed_with_source_checks",
            "source_complete_component_eligibility": eligibility,
            "source_volume": source_volume,
            "exact_added_volume": str(added_volume),
            "source_projection_area": str(domain_area),
            "minimum_source_thickness": str(minimum),
            "profiles": receipts,
            "checks": checks,
            "vertices": len(output),
            "triangles": len(faces),
            "whole_component_inspector_triangle_limit": m.MAX_INSPECTION_TRIANGLES,
            "within_whole_component_inspector_limit": len(faces) <= m.MAX_INSPECTION_TRIANGLES,
            "exact_clips": budget.clips,
            "edge_tests": budget.edge_tests,
            "pair_scans": budget.pair_scans,
            "actual_export_inspected": False,
        },
    }
