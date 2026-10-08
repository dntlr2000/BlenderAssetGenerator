"""Bounded exact patch partitions on complete closed height-field components.

The helper preserves source affine graphs, adds shared edge anchors and rebuilds
vertical boundary walls. It never trims an unsupported requested patch or writes
canonical files. Binary serialization is independently revalidated, not repaired.
"""

import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from fractions import Fraction as Q

from codex_blender_modeler.structural_geometry.profiled_relief import _validate_embedded
from codex_blender_modeler.structural_geometry.triangle_shell import (
    TriangulatedShellGeometry,
)

from . import owner_relief as math3d

MAX_OUTPUT_TRIANGLES = 8192
MAX_OUTPUT_VERTICES = 8192


def _normal(points):
    """Compute a source orientation vector without modifying supplied positions."""
    a, b, c = points
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    return (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )


def _dot(a, b):
    """Use a stable small-vector dot product without a numeric-runtime dependency."""
    return math.fsum(x * y for x, y in zip(a, b, strict=False))


def _volume(vertices, triangles):
    """Compute oriented volume for independent before/after diagnostics."""
    return math.fsum(
        _dot(vertices[a], _normal([(0.0, 0.0, 0.0), vertices[b], vertices[c]])) / 6
        for a, b, c in triangles
    )


def _area3(vertices, triangles):
    """Compute actual3D surface area for independent serialization diagnostics."""
    return math.fsum(
        math.sqrt(_dot(n, n)) / 2 for n in (_normal([vertices[i] for i in f]) for f in triangles)
    )


def _orient_closed(vertices, faces):
    """Orient all shared edges from an already outward first cap, refusing disconnected/pinched
    results."""
    edges = defaultdict(list)
    for i, face in enumerate(faces):
        for a, b in zip(face, face[1:] + face[:1], strict=False):
            edges[tuple(sorted((a, b)))].append((i, a, b))
    if any(len(items) != 2 for items in edges.values()):
        raise ValueError("partition has open or overused edges")
    graph = defaultdict(list)
    for (i, a, b), (j, c, d) in edges.values():
        same = (a, b) == (c, d)
        graph[i].append((j, same))
        graph[j].append((i, same))
    flips = {0: False}
    queue = [0]
    for i in queue:
        for j, same in graph[i]:
            value = flips[i] ^ same
            if j in flips and flips[j] != value:
                raise ValueError("partition cannot be oriented consistently")
            if j not in flips:
                flips[j] = value
                queue.append(j)
    if len(flips) != len(faces):
        raise ValueError("partition changed complete component connectivity")
    result = [f[::-1] if flips[i] else f for i, f in enumerate(faces)]
    if _volume(vertices, result) <= 0:
        raise ValueError("partition source orientation is not outward")
    return result


def partition_heightfield_faces(
    *,
    vertices,
    triangles,
    front_face_indices,
    back_face_indices,
    patch_vertices,
    patch_triangles,
    frame=((0, 2, 1), (1, 1, 1)),
):
    """Retain a full requested patch as new front/back groups on the unchanged closed solid."""
    eligibility = math3d.verify_height_field_solid(
        vertices=vertices,
        triangles=triangles,
        front_face_indices=front_face_indices,
        back_face_indices=back_face_indices,
        frame=frame,
    )
    if eligibility.get("passed") is not True:
        raise ValueError("complete owner ineligible: " + str(eligibility))
    budget = math3d.Budget()
    axes, signs = math3d.frame_spec(frame)
    source_front = math3d.surface(
        vertices, [triangles[i] for i in front_face_indices], frame, budget
    )
    source_back = math3d.surface(vertices, [triangles[i] for i in back_face_indices], frame, budget)
    patch = math3d.surface(
        [
            [p[0], p[1], 0.0]
            for p in math3d.array(patch_vertices, 3, math3d.MAX_INPUT_VERTICES)
            if math3d.array(p, 2, 2)
        ],
        patch_triangles,
        ((0, 1, 2), (1, 1, 1)),
        budget,
        generation=True,
    )
    requested_area = sum(math3d.area(poly) for poly, _ in patch)
    for label, support in [("front", source_front), ("back", source_back)]:
        _, missing = math3d.overlay([(p, [s]) for p, s in patch], support, budget)
        if missing:
            raise ValueError(
                "requested root patch escapes " + label + ": " + str(math3d.polygons_json(missing))
            )
    cells = []
    original_area = {}
    selected_area = {}
    for label, surface, indices in [
        ("front", source_front, front_face_indices),
        ("back", source_back, back_face_indices),
    ]:
        original_area[label] = sum(math3d.area(p) for p, _ in surface)
        selected_area[label] = Q(0)
        for (poly, plane), source_id in zip(surface, indices, strict=False):
            inside, outside = math3d.overlay([(poly, [plane])], patch, budget)
            for region, _ in inside:
                cells.append((region, plane, source_id, label, True))
                selected_area[label] += math3d.area(region)
            for region in outside:
                cells.append((region, plane, source_id, label, False))
        if selected_area[label] != requested_area:
            raise ValueError("selected patch area does not equal complete requested area")
    for label in ["front", "back"]:
        if (
            sum(math3d.area(p) for p, _, _, role, _ in cells if role == label)
            != original_area[label]
        ):
            raise ValueError("partition changed exact projected source area")
    if len(cells) > math3d.MAX_CELLS:
        raise ValueError("partition exceeds bounded overlay-cell count")
    anchors = sorted({p for poly, _, _, _, _ in cells for p in poly})
    anchor_u = [p[0] for p in anchors]

    def split_edge(a, b):
        """Retain every exact on-edge graph anchor with an ordered bounded candidate sweep."""
        lo, hi = sorted((a[0], b[0]))
        dv = (b[0] - a[0], b[1] - a[1])
        den = dv[0] * dv[0] + dv[1] * dv[1]
        if not den:
            raise ValueError("partition contains a zero edge")
        found = []
        for p in anchors[bisect_left(anchor_u, lo) : bisect_right(anchor_u, hi)]:
            budget.edge()
            if not min(a[1], b[1]) <= p[1] <= max(a[1], b[1]):
                continue
            if math3d.cross(a, b, p) == 0:
                t = ((p[0] - a[0]) * dv[0] + (p[1] - a[1]) * dv[1]) / den
                if 0 <= t <= 1:
                    found.append((t, p))
        return [p for _, p in sorted(set(found))]

    output = []
    lookup = {}
    faces = []
    groups = {"front": [], "back": [], "sides": [], "patch_front": [], "patch_back": []}
    source_map = []

    def vertex(uv, depth):
        """Deduplicate exact full3D rational anchors before floating serialization."""
        key = (uv[0], uv[1], depth)
        if key not in lookup:
            if len(output) >= MAX_OUTPUT_VERTICES:
                raise ValueError("partition vertex budget exhausted")
            lookup[key] = len(output)
            output.append(math3d.world(key, frame))
        return lookup[key]

    def emit(points, plane, source_id, label, selected):
        """Triangulate a convex cell while preserving collinear shared-boundary controls."""
        loop = []
        for a, b in zip(points, points[1:] + points[:1], strict=False):
            loop.extend(split_edge(a, b)[:-1])
        if len(loop) < 3:
            raise ValueError("partition cell collapsed")
        strictly_convex = all(
            math3d.cross(loop[i - 1], loop[i], loop[(i + 1) % len(loop)]) > 0
            for i in range(len(loop))
        )
        if strictly_convex:
            tris = [(loop[0], loop[i], loop[i + 1]) for i in range(1, len(loop) - 1)]
        else:
            center = (
                sum(p[0] for p in loop) / len(loop),
                sum(p[1] for p in loop) / len(loop),
            )
            tris = [(center, a, b) for a, b in zip(loop, loop[1:] + loop[:1], strict=False)]
        source_normal = _normal([vertices[i] for i in triangles[source_id]])
        for uv in tris:
            if math3d.cross(*uv) <= 0:
                raise ValueError("partition emitted a nonpositive cap triangle")
            f = [vertex(p, math3d.height(p, plane)) for p in uv]
            direction = _dot(_normal([output[i] for i in f]), source_normal)
            if direction == 0:
                raise ValueError("partition cap orientation collapsed during serialization")
            if direction < 0:
                f.reverse()
            if len(faces) >= MAX_OUTPUT_TRIANGLES:
                raise ValueError("partition triangle budget exhausted")
            index = len(faces)
            faces.append(f)
            groups[label].append(index)
            source_map.append(source_id)
            if selected:
                groups["patch_" + label].append(index)

    for poly, plane, source_id, label, selected in cells:
        emit(poly, plane, source_id, label, selected)
    # The full front graph defines all outer and hole boundary edges; rebuild only
    # vertical side walls, including subdivisions shared with either cap graph.
    boundary = defaultdict(list)
    for poly, plane in source_front:
        for a, b in zip(poly, poly[1:] + poly[:1], strict=False):
            boundary[tuple(sorted((a, b)))].append((a, b, plane))
    walls = []
    for _edge, rows in boundary.items():
        if len(rows) == 2:
            continue
        if len(rows) != 1:
            raise ValueError("source front boundary is nonmanifold")
        a, b, front_plane = rows[0]
        knots = split_edge(a, b)
        for p, q in zip(knots, knots[1:], strict=False):
            midpoint = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            back_planes = []
            for poly, plane in source_back:
                budget.pair()
                box = math3d.bounds(poly)
                if not all(box[i][0] <= midpoint[i] <= box[i][1] for i in range(2)):
                    continue
                if all(
                    math3d.cross(c, d, midpoint) >= 0
                    for c, d in zip(poly, poly[1:] + poly[:1], strict=False)
                ):
                    back_planes.append(plane)
            if not back_planes:
                raise ValueError("back graph omits a source boundary segment")
            # Continuity was verified; any coincident triangle gives the same boundary depth.
            back_plane = back_planes[0]
            fa = vertex(p, math3d.height(p, front_plane))
            fb = vertex(q, math3d.height(q, front_plane))
            ba = vertex(p, math3d.height(p, back_plane))
            bb = vertex(q, math3d.height(q, back_plane))
            walls.extend([[fa, ba, bb], [fa, bb, fb]])
    for f in walls:
        if len(faces) >= MAX_OUTPUT_TRIANGLES:
            raise ValueError("partition wall triangle budget exhausted")
        groups["sides"].append(len(faces))
        faces.append(f)
        source_map.append(None)
    faces = _orient_closed(output, faces)
    checks = {}
    for label, cast in [("binary64", lambda v: v), ("binary32", math3d.float32)]:
        vv = cast(output)
        shell = TriangulatedShellGeometry(
            vertices=[tuple(p) for p in vv], triangles=[tuple(f) for f in faces]
        )
        _validate_embedded(shell)
        checks[label] = {
            "closed_embedded": True,
            "volume": _volume(vv, faces),
            "surface_area": _area3(vv, faces),
            "vertices": len(vv),
            "triangles": len(faces),
        }
    old_volume = _volume(vertices, triangles)
    old_area = _area3(vertices, triangles)
    if abs(checks["binary64"]["volume"] - old_volume) > max(1e-11, abs(old_volume) * 1e-10):
        raise ValueError("partition changed volume beyond serialization allowance")
    if abs(checks["binary64"]["surface_area"] - old_area) > max(1e-10, old_area * 1e-10):
        raise ValueError("partition changed area beyond serialization allowance")
    return {
        "vertices": [list(p) for p in output],
        "triangles": faces,
        "face_roles": groups,
        "source_face_map": source_map,
        "diagnostics": {
            "status": "passed",
            "source_complete_component_eligibility": eligibility,
            "original_projected_area": {k: str(v) for k, v in original_area.items()},
            "selected_patch_area": str(requested_area),
            "full_patch_retained": True,
            "all_new_shared_edge_anchors_retained": True,
            "old_volume": old_volume,
            "old_surface_area": old_area,
            "checks": checks,
            "exact_clips": budget.clips,
            "edge_tests": budget.edge_tests,
            "pair_scans": budget.pair_scans,
            "actual_export_inspected": False,
            ("serialization_limit"): (
                "Exact rational pre-serialization surfaces; binary64 area/volume "
                "tolerance1e-10relative and explicit floors. Binary32 closure/embedding "
                "checked; final actual export remains separate."
            ),
        },
    }
