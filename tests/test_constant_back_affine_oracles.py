"""Independent affine-domain, extreme-value, and precondition regression oracles."""

from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import constant_back as candidate
from codex_blender_modeler.structural_geometry import owner_relief as m

TRANSFORMS = [(1, 0, 0, 1), (3, 1, -1, 2), (0, -2, 3, 1), (-1, 1, 0, 2)]
DOMAINS = [
    {(0, 0)},
    {(0, 0), (1, 0), (0, 1)},
    {(x, y) for x in range(3) for y in range(3)} - {(1, 1)},
    {(-2, -2), (2, 2)},
]


def surface_from_cells(cells, front, subdivide):
    """Construct independently chosen planar grid cells with two cap tessellations."""
    vertices, faces = [], []
    for x, y in sorted(cells):
        offset = len(vertices)
        points = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
        if subdivide:
            points.append((x + 0.375, y + 0.625))
            local = [[i, (i + 1) % 4, 4] for i in range(4)]
        else:
            local = [[0, 1, 3], [1, 2, 3]]
        vertices.extend(
            [[u, v, (-1.0 + 0.125 * abs(u) + 0.25 * v) if front else 1.0] for u, v in points]
        )
        faces.extend([[i + offset for i in face] for face in local])
    return m.surface(vertices, faces, ((0, 1, 2), (1, 1, 1)), m.Budget())


def transformed_surface(cells, front, subdivide, transform):
    """Build exact dyadic graph coordinates under invertible integer affine maps."""
    graph = surface_from_cells(cells, front, subdivide)
    a, b, c, d = transform
    vertices = []
    faces = []
    for _, points in graph:
        first = len(vertices)
        vertices.extend(
            [
                [float(a * x + b * y + Q(3, 8)), float(c * x + d * y - Q(5, 8)), float(z)]
                for x, y, z in points
            ]
        )
        faces.append([first, first + 1, first + 2])
    return m.surface(vertices, faces, ((0, 1, 2), (1, 1, 1)), m.Budget())


@pytest.mark.parametrize("transform", TRANSFORMS)
@pytest.mark.parametrize("cells", DOMAINS)
def test_affine_domains_match_independent_full_overlay(cells, transform):
    """Preserve exact extrema for oblique, reflected, concave, holed and disconnected domains."""
    front = transformed_surface(cells, True, True, transform)
    back = transformed_surface(cells, False, False, transform)
    actual = candidate.constant_back_thickness(front, back, m.Budget())
    overlay, gaps = m.overlay([(p, [s]) for p, s in front], back, m.Budget())
    _, reverse_gaps = m.overlay([(p, [s]) for p, s in back], front, m.Budget())
    assert not gaps and not reverse_gaps
    expected = [
        m.height(p, sources[1]) - m.height(p, sources[0]) for poly, sources in overlay for p in poly
    ]
    assert actual == (min(expected), max(expected))


@pytest.mark.parametrize("transform", TRANSFORMS)
def test_oblique_equal_area_domain_difference_refuses(transform):
    """Equal areas under oblique affine maps cannot substitute for oriented-boundary equality."""
    front = transformed_surface({(0, 0), (1, 0)}, True, True, transform)
    back = transformed_surface({(0, 0), (0, 1)}, False, False, transform)
    assert sum(m.area(p) for p, _ in front) == sum(m.area(p) for p, _ in back)
    assert candidate.constant_back_thickness(front, back, m.Budget()) is None


def test_rational_complexity_exhaustion_fails_closed(monkeypatch):
    """The new line representation refuses rational growth instead of skipping a boundary."""
    front = transformed_surface({(0, 0)}, True, True, (3, 1, -1, 2))
    back = transformed_surface({(0, 0)}, False, False, (3, 1, -1, 2))
    monkeypatch.setattr(m, "MAX_RATIONAL_BITS", 2)
    with pytest.raises(m.Unverified, match="rational complexity"):
        candidate.constant_back_thickness(front, back, m.Budget())
