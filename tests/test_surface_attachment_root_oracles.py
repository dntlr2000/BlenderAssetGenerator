"""Independent interval and exact-domain regression oracles."""

import copy
import math
import random
from fractions import Fraction as Q

import pytest

from codex_blender_modeler.structural_geometry import owner_relief as m


def graph(values):
    """Lift the literal unit square into an independently prescribed depth graph."""
    return [
        (x, float(y), z)
        for (x, z), y in zip([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], values, strict=False)
    ]


def planar_intervals(cf, cb, pf, pb):
    """Name independently authored child and owner interval endpoints on one domain."""
    faces = [(0, 1, 2), (0, 2, 3)]
    return {
        "upper_vertices": graph(cf),
        "upper_triangles": faces,
        "lower_vertices": graph(cb),
        "lower_triangles": faces,
        "owner_front_vertices": graph(pf),
        "owner_front_triangles": faces,
        "owner_back_vertices": graph(pb),
        "owner_back_triangles": faces,
        "minimum_overlap": 0.0625,
    }


def constant_intervals(cf=0.25, cb=0.5, pf=0.0, pb=1.0):
    """Construct four constant graphs with dyadic coordinate depths."""
    return planar_intervals(*([v] * 4 for v in (cf, cb, pf, pb)))


def test_buried_subject_is_root_positive_but_exposed_relief_negative():
    """Valid buried interval overlap must not silently relax the exposed-relief predicate."""
    data = constant_intervals()
    root = m.inspect_inserted_root(**data)
    assert root["passed"] is True and Q(root["minimum_overlap_m_exact"]) == Q(1, 4)
    assert (
        root["owner_volume_verified"] is False
        and root["free_subject_area_overlap_claimed"] is False
    )
    data.pop("minimum_overlap")
    relief = m.inspect_attachment(
        **data,
        minimum_embed=0.125,
        maximum_embed=0.75,
        minimum_remaining_thickness=0.25,
        minimum_relief_height=0.0,
    )
    assert relief["status"] == "failed"


def test_switching_intervals_have_interior_peak_and_only_conservative_maximum_claim():
    """Analytic overlap min(x+1,2-x) peaks at x=.5, not at either graph's corner extrema."""
    # Child [0,2*x+1]; parent [x,2]. True minimum=1, true maximum=3/2.
    data = planar_intervals([0] * 4, [1, 3, 3, 1], [0, 1, 1, 0], [2] * 4)
    data["minimum_overlap"] = 1.0
    report = m.inspect_inserted_root(**data)
    assert report["passed"] is True and Q(report["minimum_overlap_m_exact"]) == 1
    assert Q(report["maximum_overlap_m_upper_bound"]) >= Q(3, 2)
    assert "maximum_overlap_m_exact" not in report


def test_affine_interval_oracle_and_dense_interior_bounds():
    """Compare random signed endpoint intervals using direct max/min intersection, not four
    differences."""
    rng = random.Random(83491)
    corners = [(Q(0), Q(0)), (Q(1), Q(0)), (Q(1), Q(1)), (Q(0), Q(1))]
    for _ in range(40):
        a, b, c, d, e, f = [Q(rng.randrange(-8, 9), 16) for _ in range(6)]
        child_thickness = Q(rng.randrange(1, 17), 16)
        parent_thickness = Q(rng.randrange(1, 17), 16)

        def intervals(
            x,
            z,
            a=a,
            b=b,
            c=c,
            d=d,
            e=e,
            f=f,
            child_thickness=child_thickness,
            parent_thickness=parent_thickness,
        ):
            """Evaluate two explicitly positive-thickness affine intervals."""
            cf = a + b * x + c * z
            pf = d + e * x + f * z
            return cf, cf + child_thickness, pf, pf + parent_thickness

        rows = [intervals(x, z) for x, z in corners]
        data = planar_intervals(*zip(*rows, strict=False))
        report = m.inspect_inserted_root(**data)
        expected = min(min(cb, pb) - max(cf, pf) for cf, cb, pf, pb in rows)
        assert Q(report["minimum_overlap_m_exact"]) == expected
        assert report["passed"] == (expected >= Q(1, 16))
        for x in range(9):
            for z in range(9):
                cf, cb, pf, pb = intervals(Q(x, 8), Q(z, 8))
                overlap = min(cb, pb) - max(cf, pf)
                assert expected <= overlap <= Q(report["maximum_overlap_m_upper_bound"])


@pytest.mark.parametrize(
    "endpoints",
    [
        (1.0, 1.25, 0.0, 1.0),
        (1.125, 1.25, 0.0, 1.0),
        (0.5, 0.25, 0.0, 1.0),
        (0.25, 0.5, 1.0, 0.0),
    ],
)
def test_zero_contact_gap_and_wrong_interval_order_refused(endpoints):
    """Touching, separated and reversed-depth intervals cannot establish positive support."""
    assert m.inspect_inserted_root(**constant_intervals(*endpoints))["status"] == "failed"


def test_positive_child_thickness_with_interior_only_overlap_gap():
    """A valid child slab can detach only in its interior despite every outer root corner
    overlapping."""
    data = constant_intervals()
    faces = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    data["upper_vertices"].append((0.5, 1.125, 0.5))
    data["lower_vertices"].append((0.5, 1.375, 0.5))
    data["upper_triangles"] = faces
    data["lower_triangles"] = faces
    report = m.inspect_inserted_root(**data)
    assert report["status"] == "failed"
    assert Q(report["minimum_overlap_m_exact"]) == Q(-1, 8)
    assert not any(report["uncovered_polygons"].values())


def test_one_ulp_projected_owner_slit_cannot_disappear():
    """Positive corner depths cannot compensate for an arbitrarily narrow uncovered root strip."""
    data = constant_intervals()
    right = math.nextafter(0.5, 1.0)
    data["owner_front_vertices"] = [
        (0.0, 0.0, 0.0),
        (0.5, 0.0, 0.0),
        (0.5, 0.0, 1.0),
        (0.0, 0.0, 1.0),
        (right, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 1.0),
        (right, 0.0, 1.0),
    ]
    data["owner_front_triangles"] = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    report = m.inspect_inserted_root(**data)
    assert report["status"] == "failed" and report["uncovered_polygons"]["owner_front"]


def test_back_selection_must_cover_exactly_the_entire_front_root():
    """Neither missing lower area nor an added lower overhang is an acceptable root footprint."""
    data = constant_intervals()
    data["lower_triangles"] = [(0, 1, 2)]
    report = m.inspect_inserted_root(**data)
    assert report["status"] == "failed" and report["uncovered_polygons"]["child_back"]
    data = constant_intervals()
    data["lower_vertices"] = [(x * 1.25, y, z) for x, y, z in data["lower_vertices"]]
    report = m.inspect_inserted_root(**data)
    assert report["status"] == "failed" and report["uncovered_polygons"]["child_back_outside_front"]


def test_root_budget_exhaustion_is_unverified(monkeypatch):
    """An incomplete overlay must not be interpreted as a measured geometric failure or pass."""
    monkeypatch.setattr(m, "MAX_CLIPS", 1)
    report = m.inspect_inserted_root(**constant_intervals())
    assert report["status"] == "unverified" and report["passed"] is None


def test_binary32_root_overlap_collapse_is_recomputed_as_zero_contact():
    """A nominal binary64 root overlap cannot survive as a claim after serialized endpoints meet."""
    data = constant_intervals(100000.0 - 0.0001, 100000.0 + 0.25, 100000.0 - 0.5, 100000.0)
    data["minimum_overlap"] = 0.00005
    assert m.inspect_inserted_root(**data)["passed"] is True
    rounded = copy.deepcopy(data)
    for key in list(rounded):
        if key.endswith("_vertices"):
            rounded[key] = m.float32(rounded[key])
    report = m.inspect_inserted_root(**rounded)
    assert report["status"] == "failed" and Q(report["minimum_overlap_m_exact"]) == 0
