"""Exact inserted-root checks over an explicit polygon without changing mesh topology.

The polygon is a single simple boundary in the declared projection frame. Holes
and multiple rings are unsupported. Artifact identity, reference provenance and
complete solid eligibility remain mandatory independent host checks.
"""

from . import owner_relief as m

MAX_REGION_VERTICES = 256


def _on_segment(a, b, p):
    """Test a point on the complete closed segment using exact coordinates."""
    return m.cross(a, b, p) == 0 and all(
        min(a[k], b[k]) <= p[k] <= max(a[k], b[k]) for k in range(2)
    )


def _segments_meet(a, b, c, d):
    """Include crossings, shared endpoints and collinear overlap in intersection."""
    if any(_on_segment(a, b, p) for p in (c, d)) or any(_on_segment(c, d, p) for p in (a, b)):
        return True
    first, second = m.cross(a, b, c), m.cross(a, b, d)
    third, fourth = m.cross(c, d, a), m.cross(c, d, b)
    return ((first < 0 < second) or (second < 0 < first)) and (
        (third < 0 < fourth) or (fourth < 0 < third)
    )


def polygon_cells(region_polygon, budget):
    """Validate and triangulate one bounded simple polygon with exact ear clipping."""
    points = [
        tuple(m.number(c) for c in m.array(p, 2, 2))
        for p in m.array(region_polygon, 3, MAX_REGION_VERTICES)
    ]
    if len(set(points)) != len(points):
        raise m.Unverified("root region repeats a vertex or explicitly closes its ring")
    edges = list(zip(points, points[1:] + points[:1], strict=True))
    for i, (a, b) in enumerate(edges):
        budget.edge()
        previous = points[i - 1]
        if m.cross(previous, a, b) == 0 and not _on_segment(previous, b, a):
            raise m.Unverified("root region has a collinear reversal")
        for j in range(i + 1, len(edges)):
            budget.edge()
            if j == i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            if _segments_meet(a, b, *edges[j]):
                raise m.Unverified("root region self-intersects or has a touching boundary")
    signed = m.bounded(sum(a[0] * b[1] - a[1] * b[0] for a, b in edges))
    if not signed:
        raise m.Unverified("root region has zero area")
    if signed < 0:
        points.reverse()
    original_area = m.area(points)
    # Exact collinear controls do not change the region; removing them avoids
    # zero-area ears while retaining the same complete boundary segments.
    while len(points) > 3:
        remove = None
        for i, p in enumerate(points):
            budget.edge()
            if m.cross(points[i - 1], p, points[(i + 1) % len(points)]) == 0:
                remove = i
                break
        if remove is None:
            break
        points.pop(remove)
    triangles = []
    while len(points) > 3:
        chosen = None
        for i, point in enumerate(points):
            budget.edge()
            triangle = [points[i - 1], point, points[(i + 1) % len(points)]]
            if m.cross(*triangle) <= 0:
                continue
            blocked = False
            for other in points:
                budget.edge()
                if other in triangle:
                    continue
                if all(
                    m.cross(a, b, other) >= 0
                    for a, b in zip(triangle, triangle[1:] + triangle[:1], strict=True)
                ):
                    blocked = True
                    break
            if not blocked:
                chosen = i
                triangles.append(triangle)
                break
        if chosen is None:
            raise m.Unverified("root region cannot be exactly triangulated")
        points.pop(chosen)
    if m.cross(*points) <= 0:
        raise m.Unverified("root region has a degenerate final ear")
    triangles.append(points)
    if sum(m.area(t) for t in triangles) != original_area:
        raise m.Unverified("root region triangulation changed its exact area")
    return triangles, original_area


def inspect_root_region(
    *,
    region_polygon,
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
    """Prove interval overlap at every point of an unchanged explicit root region.

    Supply complete front/back height fields of the actual child and owner. Every
    part of the polygon must lie in all four domains; uncovered regions fail. The
    exact affine overlay creates temporary rational cells, never delivered vertices.
    """
    budget = m.Budget()
    try:
        m.frame_spec(frame)
        required = m.number(minimum_overlap)
        if required <= 0:
            raise m.Unverified("inserted root requires positive minimum overlap")
        regions, region_area = polygon_cells(region_polygon, budget)
        surfaces = [
            ("child_front", m.surface(upper_vertices, upper_triangles, frame, budget)),
            ("child_back", m.surface(lower_vertices, lower_triangles, frame, budget)),
            (
                "owner_front",
                m.surface(owner_front_vertices, owner_front_triangles, frame, budget),
            ),
            (
                "owner_back",
                m.surface(owner_back_vertices, owner_back_triangles, frame, budget),
            ),
        ]
        cells = [(poly, []) for poly in regions]
        missing = {}
        for label, support in surfaces:
            cells, gaps = m.overlay(cells, support, budget)
            missing[label] = m.polygons_json(gaps)
        covered_area = sum(m.area(poly) for poly, _ in cells)
        minima, upper_bounds, violations = [], [], []
        for index, (poly, sources) in enumerate(cells):
            differences = []
            for point in poly:
                cf, cb, pf, pb = (m.height(point, p) for p in sources)
                differences.append((cb - cf, cb - pf, pb - cf, pb - pf))
            # The interval overlap is a concave minimum of four affine terms;
            # its exact minimum is attained at a vertex of each convex cell.
            minimum = min(min(row) for row in differences)
            upper = min(max(row[i] for row in differences) for i in range(4))
            minima.append(minimum)
            upper_bounds.append(upper)
            if minimum < required:
                violations.append(
                    {
                        "cell": index,
                        "polygon": m.polygons_json([poly])[0],
                        "minimum_overlap": str(minimum),
                    }
                )
        passed = (
            covered_area == region_area
            and not any(missing.values())
            and not violations
            and bool(cells)
        )
        return {
            "status": "passed" if passed else "failed",
            "passed": passed,
            "scope": "required_root_patch",
            "selection": "explicit_root_region",
            "proof": "complete exact polygon and interval-overlap overlay",
            "region_area_exact": str(region_area),
            "covered_area_exact": str(covered_area),
            "region_triangle_count": len(regions),
            "covered_cell_count": len(cells),
            "uncovered_polygons": missing,
            "violations": violations,
            "minimum_overlap_m_exact": str(min(minima)) if minima else None,
            "maximum_overlap_m_upper_bound": str(max(upper_bounds)) if upper_bounds else None,
            "outward_exposure_required": False,
            "free_subject_area_overlap_claimed": False,
            "owner_volume_verified": False,
            "artifact_identity_verified": False,
            "delivered_geometry_modified": False,
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
            "region_edge_tests": budget.edge_tests,
        }
    except (m.Unverified, ValueError, OverflowError, ZeroDivisionError) as exc:
        return {
            "status": "unverified",
            "passed": None,
            "reason": str(exc),
            "scope": "required_root_patch",
            "selection": "explicit_root_region",
            "owner_volume_verified": False,
            "artifact_identity_verified": False,
            "delivered_geometry_modified": False,
            "exact_clips": budget.clips,
            "broad_phase_pairs": budget.pair_scans,
            "region_edge_tests": budget.edge_tests,
        }
