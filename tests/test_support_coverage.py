"""Exact continuous coverage tests, including endpoint-supported bridges and tiny gaps."""

from __future__ import annotations

import math
import struct
from fractions import Fraction

import pytest

from codex_blender_modeler.structural_geometry import support_coverage as module
from codex_blender_modeler.structural_geometry.support_coverage import (
    inspect_projected_centerline_coverage,
)


def rectangle_mesh(rectangles):
    """Triangulate disjoint or touching XZ rectangles into explicit support data."""
    vertices, faces = [], []
    for left, right, bottom, top in rectangles:
        index = len(vertices)
        vertices.extend([(left, 0, bottom), (right, 0, bottom), (right, 0, top), (left, 0, top)])
        faces.extend([(index, index + 1, index + 2), (index, index + 2, index + 3)])
    return vertices, faces


def inspect(points, rectangles):
    """Inspect a fixture mesh through the public data-only utility."""
    vertices, faces = rectangle_mesh(rectangles)
    return inspect_projected_centerline_coverage(
        points, support_vertices=vertices, support_triangles=faces
    )


def test_supported_endpoints_do_not_hide_a_continuous_hole():
    """A line across a closed frame reports the entire open unsupported interior interval."""
    rectangles = [(-2, -0.5, -1, 1), (0.5, 2, -1, 1), (-0.5, 0.5, -1, -0.5), (-0.5, 0.5, 0.5, 1)]
    report = inspect([(-2, 0), (2, 0)], rectangles)
    assert report["availability"] == "available" and report["passed"] is False
    assert report["uncovered_intervals"] == [
        dict(
            segment_index=0, t_start="3/8", t_end="5/8", start_inclusive=False, end_inclusive=False
        )
    ]


@pytest.mark.parametrize(
    "route",
    [[(-1, 0), (1, 0)], [(-1, -1), (1, 1)], [(-1, -1), (-1, 1), (1, 1)], [(1, 1), (-1, -1)]],
)
def test_full_support_includes_triangle_seams_and_external_edges(route):
    """Continuous seam and edge contact counts as projected centerline coverage."""
    report = inspect(route, [(-1, 1, -1, 1)])
    assert report["availability"] == "available" and report["passed"] is True
    assert report["uncovered_intervals"] == []


def test_adjacent_triangles_and_duplicate_faces_union_without_cracks():
    """Unordered repeated support faces merge by exact interval endpoints."""
    vertices, faces = rectangle_mesh([(-1, 0, -1, 1), (0, 1, -1, 1)])
    report = inspect_projected_centerline_coverage(
        [(-1, 0.3), (1, 0.3)], support_vertices=vertices, support_triangles=[*faces[::-1], *faces]
    )
    assert report["passed"] is True


def test_sub_float_parameter_gap_retains_exact_rational_endpoints():
    """A gap smaller than float t precision remains visible in exact parameter strings."""
    tiny = 2.0**-70
    report = inspect([(-1, 0), (1, 0)], [(-1, 0, -1, 1), (tiny, 1, -1, 1)])
    assert report["passed"] is False
    gap = report["uncovered_intervals"][0]
    assert Fraction(gap["t_end"]) - Fraction(gap["t_start"]) == Fraction(tiny) / 2
    assert float(Fraction(gap["t_start"])) == float(Fraction(gap["t_end"]))


def test_one_float32_ulp_gap_in_native_source_coordinates_is_preserved():
    """Pass actual float32 positions without an epsilon that bridges their real gap."""
    after_one = struct.unpack("f", struct.pack("I", 0x3F800001))[0]
    report = inspect([(0, 0), (2, 0)], [(0, 1, -1, 1), (after_one, 2, -1, 1)])
    gap = report["uncovered_intervals"][0]
    assert Fraction(gap["t_end"]) - Fraction(gap["t_start"]) == Fraction(1, 2**24)
    assert report["passed"] is False


def test_utility_inspects_supplied_precision_without_synthesizing_native_geometry():
    """Source and float32-rounded coverage can differ; neither is silently substituted."""
    rectangles = [(0, 1, -1, 1), (1 + 2**-30, 2, -1, 1)]
    assert inspect([(0, 0), (2, 0)], rectangles)["passed"] is False
    rounded = [tuple(struct.unpack("f", struct.pack("f", v))[0] for v in r) for r in rectangles]
    assert inspect([(0, 0), (2, 0)], rounded)["passed"] is True


def test_uncovered_endpoints_have_explicit_inclusion_flags():
    """Distinguish missing endpoints from interior gap endpoints already on support."""
    report = inspect([(-2, 0), (2, 0)], [(-1, 1, -1, 1)])
    assert report["uncovered_intervals"] == [
        dict(segment_index=0, t_start="0", t_end="1/4", start_inclusive=True, end_inclusive=False),
        dict(segment_index=0, t_start="3/4", t_end="1", start_inclusive=False, end_inclusive=True),
    ]
    missing = inspect([(-2, 3), (2, 3)], [(-1, 1, -1, 1)])
    assert missing["uncovered_intervals"] == [
        dict(segment_index=0, t_start="0", t_end="1", start_inclusive=True, end_inclusive=True)
    ]


def test_multiple_segments_report_local_parameters_and_order():
    """Each authored line segment gets its own exact interval rather than resampled chords."""
    report = inspect([(-2, 0), (0, 0), (2, 0)], [(-2, -0.5, -1, 1), (0.5, 2, -1, 1)])
    assert [
        (g["segment_index"], g["t_start"], g["t_end"]) for g in report["uncovered_intervals"]
    ] == [(0, "3/4", "1"), (1, "0", "1/4")]


def test_vertical_support_triangles_project_to_valid_line_coverage():
    """Degenerate 2D projections of valid 3D triangles retain closed point/edge support."""
    vertices = [(0, 0, 0), (2, 0, 0), (0, 1, 0)]
    report = inspect_projected_centerline_coverage(
        [(0, 0), (2, 0)], support_vertices=vertices, support_triangles=[(0, 1, 2)]
    )
    assert report["passed"] is True
    crossing = inspect_projected_centerline_coverage(
        [(1, -1), (1, 1)], support_vertices=vertices, support_triangles=[(0, 1, 2)]
    )
    assert crossing["uncovered_intervals"] == [
        dict(segment_index=0, t_start="0", t_end="1/2", start_inclusive=True, end_inclusive=False),
        dict(segment_index=0, t_start="1/2", t_end="1", start_inclusive=False, end_inclusive=True),
    ]


@pytest.mark.parametrize(
    "values",
    [
        {"points": [(0, 0)]},
        {"points": [(0, 0), (0, 0)]},
        {"points": [(0, 0), (math.nan, 0)]},
        {"points": [(0, 0), (math.inf, 0)]},
        {"points": [(0, 0), (True, 0)]},
        {"points": [(0, 0), (10**1000, 0)]},
        {"points": [{0: 0, 1: 0}, (1, 0)]},
        {"support_vertices": []},
        {"support_vertices": [(0, 0, 0), (1, 0, 0), (math.inf, 0, 1)]},
        {"support_vertices": [(0, 0, 0), (1, 0, 0), (2, 0, 0)]},
        {"support_triangles": []},
        {"support_triangles": [(0, 1, 10)]},
        {"support_triangles": [(0, 1, True)]},
        {"support_triangles": [(0, 1, -1)]},
        {"support_triangles": [(0, 1, 1)]},
        {"support_triangles": [(0, 1)]},
    ],
)
def test_unsupported_inputs_return_unverified_without_coverage_claim(values):
    """Malformed, nonfinite or degenerate data never returns a verified coverage result."""
    args = dict(
        points=[(0, 0), (1, 0)],
        support_vertices=[(0, 0, 0), (1, 0, 0), (0, 0, 1)],
        support_triangles=[(0, 1, 2)],
    )
    args.update(values)
    report = inspect_projected_centerline_coverage(**args)
    assert report["availability"] == "unavailable"
    assert report["passed"] is None and report["uncovered_intervals"] is None
    assert report["reason"]


def test_workload_cap_returns_unverified_before_geometric_work(monkeypatch):
    """An over-budget segment/triangle Cartesian product cannot silently become a pass."""
    monkeypatch.setattr(module, "_MAX_PAIR_TESTS", 1)
    report = inspect([(0, 0), (1, 0)], [(0, 1, -1, 1)])
    assert report["availability"] == "unavailable" and report["passed"] is None
    assert "budget" in report["reason"]


def test_maximum_array_and_real_pair_budget_are_bounded():
    """Refuse too many controls and a real 128-by-1025 workload at the public entry point."""
    vertices, faces = rectangle_mesh([(0, 1, -1, 1)])
    report = inspect_projected_centerline_coverage(
        [(i, 0) for i in range(130)], support_vertices=vertices, support_triangles=faces
    )
    assert report["availability"] == "unavailable"
    report = inspect_projected_centerline_coverage(
        [(i, 0) for i in range(129)], support_vertices=vertices, support_triangles=[faces[0]] * 1025
    )
    assert report["availability"] == "unavailable" and "budget" in report["reason"]


def test_real_crystal_vein_supported_endpoints_bridge_owner_cutout():
    """Preserve the measured attempt_06 cutout failure using an immutable extracted fixture."""
    import json
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).parent / "fixtures/profiled_centerline_cutout_crystal.json").read_text()
    )
    report = inspect_projected_centerline_coverage(
        fixture["centerline"],
        support_vertices=fixture["support_vertices"],
        support_triangles=fixture["support_triangles"],
    )
    assert report["availability"] == "available" and report["passed"] is False
    assert report["uncovered_intervals"] == fixture["expected_uncovered_intervals"]
    gap = report["uncovered_intervals"][0]
    assert 0 < Fraction(gap["t_start"]) < Fraction(gap["t_end"]) < 1
    assert gap["start_inclusive"] is gap["end_inclusive"] is False


def test_support_Y_separation_is_outside_projected_coverage_scope():
    """Projected support can be far away in Y; a positive result never means 3D contact."""
    vertices, faces = rectangle_mesh([(-1, 1, -1, 1)])
    report = inspect_projected_centerline_coverage(
        [(-1, 0), (1, 0)],
        support_vertices=[(x, 1000, z) for x, _, z in vertices],
        support_triangles=faces,
    )
    assert report["passed"] is True
    assert report["scope"] == "continuous_projected_centerline_only"
