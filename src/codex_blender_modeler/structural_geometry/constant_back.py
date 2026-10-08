"""Exact cap-domain and sufficient depth proofs without materializing a cap overlay.

Inputs must already be complete, unambiguous height-field surfaces of an embedded
closed solid. Equality of their oriented planar boundaries establishes equality
of their compact triangle domains, including holes. This is not an area-only or
bounding-box comparison and does not change any surface or work allowance.
"""

from collections import defaultdict

from . import owner_relief as m


def _boundary_events(surfaces, budget):
    """Accumulate signed exact intervals per supporting line, retaining all gaps."""
    events = defaultdict(lambda: defaultdict(int))
    for direction, surface in surfaces:
        for polygon, _ in surface:
            for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
                budget.edge()
                dx, dy = b[0] - a[0], b[1] - a[1]
                if dx == 0:
                    if dy == 0:
                        raise m.Unverified("constant-back proof encountered a zero edge")
                    key, axis = ("vertical", a[0]), 1
                else:
                    slope = m.bounded(dy / dx)
                    intercept = m.bounded(a[1] - slope * a[0])
                    key, axis = ("nonvertical", slope, intercept), 0
                start, end = a[axis], b[axis]
                sign = direction if start < end else -direction
                lower, upper = sorted((start, end))
                events[key][lower] += sign
                events[key][upper] -= sign
    return events


def constant_back_thickness(front, back, budget):
    """Return exact thickness bounds only when full domains and constant back agree.

    Callers must first validate complete solid topology, embedding, face membership,
    orientation and single-valued cap surfaces. Nonconstant or different-domain caps
    return None so the existing general overlay remains the authoritative fallback.
    """
    back_depth = back[0][1][0][2]
    for _, points in back:
        for point in points:
            budget.edge()
            if point[2] != back_depth:
                return None
    events = _boundary_events(((1, front), (-1, back)), budget)
    # A finite oriented interval distribution is zero iff each endpoint event
    # cancels. Coincident subdivision endpoints cancel exactly, never by epsilon.
    for line_events in events.values():
        for value in line_events.values():
            budget.edge()
            if value:
                return None
    thickness = []
    for _, points in front:
        for point in points:
            budget.edge()
            thickness.append(m.bounded(back_depth - point[2]))
    if not thickness:
        raise m.Unverified("constant-back proof has no front surface")
    return min(thickness), max(thickness)


def separated_depth_bounds(front, back, budget):
    """Prove positive thickness by strict global depth separation on equal domains.

    Complete embedded solids and single-valued oriented caps must already be
    validated. Every affine cap value lies between its vertex extrema. Hence
    min(back)-max(front)>0 proves positive thickness everywhere on their common
    domain, without a cross-tessellation overlay. Returned limits are conservative
    exact-rational bounds, not necessarily attained thickness extrema.
    """
    depths = []
    for surface in (front, back):
        values = []
        for _, points in surface:
            for point in points:
                budget.edge()
                values.append(point[2])
        if not values:
            return None
        depths.append((min(values), max(values)))
    lower = m.bounded(depths[1][0] - depths[0][1])
    if lower <= 0:
        return None
    events = _boundary_events(((1, front), (-1, back)), budget)
    for line_events in events.values():
        for value in line_events.values():
            budget.edge()
            if value:
                return None
    upper = m.bounded(depths[1][1] - depths[0][0])
    return lower, upper
