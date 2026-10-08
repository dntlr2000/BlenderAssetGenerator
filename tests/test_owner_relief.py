"""Positive/adversarial proof tests for the isolated owner-derived relief prototype."""

import copy
import json

import pytest

from codex_blender_modeler.structural_geometry import owner_relief as m


def plane(y, low=0.0, high=1.0):
    """Return one selected rectangular owner graph with explicit triangulation."""
    return [(low, y, low), (high, y, low), (high, y, high), (low, y, high)], [
        (0, 1, 2),
        (0, 2, 3),
    ]


def fixture():
    """Declare a positive complete patch against a thick closed-owner slab selection."""
    front, faces = plane(0.0)
    back, _ = plane(0.2)
    lower, _ = plane(0.02, 0.2, 0.8)
    upper, _ = plane(-0.1, 0.2, 0.8)
    return dict(
        lower_vertices=lower,
        lower_triangles=faces,
        upper_vertices=upper,
        upper_triangles=faces,
        owner_front_vertices=front,
        owner_front_triangles=faces,
        owner_back_vertices=back,
        owner_back_triangles=faces,
        minimum_embed=0.01,
        maximum_embed=0.03,
        minimum_remaining_thickness=0.1,
    )


def builder():
    """Adapt explicit patch controls to the owner-derived generator input."""
    f = fixture()
    for key in (
        "lower_vertices",
        "lower_triangles",
        "upper_vertices",
        "upper_triangles",
    ):
        f.pop(key)
    return dict(
        **f,
        footprint_vertices=[
            (0.2, 0.2, 0.1),
            (0.8, 0.2, 0.1),
            (0.8, 0.8, 0.1),
            (0.2, 0.8, 0.1),
        ],
        footprint_triangles=[(0, 1, 2), (0, 2, 3)],
        embed_depth=0.02,
    )


def test_complete_planar_patch():
    """A full geometric proof covers the entire patch and records its narrow authority."""
    result = m.inspect_attachment(**fixture())
    assert result["status"] == "passed" and result["lower_triangle_count"] == 2
    assert not result["artifact_identity_verified"]
    assert all(not p for p in result["uncovered_polygons"].values())


def test_generator_closed_shell_and_binary32():
    """Construct a closed shell and remeasure the actual serialized-coordinate simulation."""
    result = m.build_owner_relief(**builder())
    assert result["shell"].kind == "triangulated_shell"
    # Two affine triangular cells form the minimal closed rectangular slab.
    assert len(result["shell"].triangles) == 12
    assert all(r["passed"] is True for r in result["diagnostics"].values())
    assert result["actual_export_inspected"] is False


def test_sloped_seamed_owner_with_full_width_conformance():
    """Crossed owner/footprint diagonals create conforming cells, including varying width depth."""
    kwargs = builder()
    kwargs["footprint_vertices"] = [
        (0.25, 0.25, 0.125),
        (0.75, 0.25, 0.125),
        (0.75, 0.75, 0.125),
        (0.25, 0.75, 0.125),
    ]
    kwargs["owner_front_vertices"] = [
        (0.0, 0.0, 0.0),
        (1.0, 0.15, 0.0),
        (1.0, 0.2, 1.0),
        (0.0, 0.05, 1.0),
    ]
    kwargs["owner_back_vertices"] = [(x, y + 0.2, z) for x, y, z in kwargs["owner_front_vertices"]]
    kwargs["owner_front_triangles"] = [(0, 1, 3), (1, 2, 3)]
    kwargs["owner_back_triangles"] = [(0, 1, 3), (1, 2, 3)]
    result = m.build_owner_relief(**kwargs)
    assert all(r["passed"] for r in result["diagnostics"].values())
    assert any(p[0] == 0.5 and p[2] == 0.5 for p in result["shell"].vertices)
    assert len(result["shell"].triangles) == 16


def test_subprecision_overlay_sliver_refused():
    """Exact almost-incident seams cannot be silently rounded into coincident shell vertices."""
    kwargs = builder()
    kwargs["owner_front_triangles"] = [(0, 1, 3), (1, 2, 3)]
    kwargs["owner_back_triangles"] = [(0, 1, 3), (1, 2, 3)]
    with pytest.raises(ValueError):
        m.build_owner_relief(**kwargs)


def test_central_opening_retains_exact_uncovered_polygons():
    """A support ring can cover all corner anchors and still fail on its central hole."""
    f = fixture()
    verts = []
    triangles = []
    for x0, x1, z0, z1 in [
        (0.0, 0.45, 0.0, 1.0),
        (0.55, 1.0, 0.0, 1.0),
        (0.45, 0.55, 0.0, 0.45),
        (0.45, 0.55, 0.55, 1.0),
    ]:
        start = len(verts)
        verts += [(x0, 0.0, z0), (x1, 0.0, z0), (x1, 0.0, z1), (x0, 0.0, z1)]
        triangles += [(start, start + 1, start + 2), (start, start + 2, start + 3)]
    f.update(owner_front_vertices=verts, owner_front_triangles=triangles)
    r = m.inspect_attachment(**f)
    assert r["status"] == "failed" and r["uncovered_polygons"]["front"]


def test_one_ulp_support_slit_is_not_sampled_away():
    """An arbitrarily narrow representable interior gap remains explicit rational evidence."""
    f = fixture()
    end = 0.5
    start = __import__("math").nextafter(end, 1.0)
    f["owner_front_vertices"] = [
        (0.0, 0.0, 0.0),
        (end, 0.0, 0.0),
        (end, 0.0, 1.0),
        (0.0, 0.0, 1.0),
        (start, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.0, 1.0),
        (start, 0.0, 1.0),
    ]
    f["owner_front_triangles"] = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    r = m.inspect_attachment(**f)
    assert r["status"] == "failed" and r["uncovered_polygons"]["front"]


@pytest.mark.parametrize(
    "change", ["width_overhang", "wrong_depth", "thin_owner", "upper_overhang"]
)
def test_whole_patch_failures(change):
    """Reject lateral, signed-depth, and rear-puncture counterexamples over complete cells."""
    f = fixture()
    if change == "width_overhang":
        f["lower_vertices"] = [(x + 0.4, y, z) for x, y, z in f["lower_vertices"]]
        f["upper_vertices"] = [(x + 0.4, y, z) for x, y, z in f["upper_vertices"]]
    elif change == "wrong_depth":
        f["lower_vertices"] = [(x, -0.02, z) for x, y, z in f["lower_vertices"]]
    elif change == "thin_owner":
        f["owner_back_vertices"] = [(x, 0.015, z) for x, y, z in f["owner_back_vertices"]]
    else:
        f["upper_vertices"][1] = (1.2, -0.1, 0.2)
    assert m.inspect_attachment(**f)["status"] == "failed"


def test_ambiguous_owner_is_unverified():
    """A hidden overlapping plane cannot silently select a convenient support layer."""
    f = fixture()
    f["owner_front_triangles"] += [(0, 1, 2)]
    assert m.inspect_attachment(**f)["status"] == "unverified"


def test_discontinuous_owner_seam_is_unverified():
    """Projected adjacency with a depth tear is outside the continuous-owner domain."""
    f = fixture()
    f["owner_front_vertices"] += [(0.0, 0.01, 0.0), (1.0, 0.01, 1.0), (0.0, 0.01, 1.0)]
    f["owner_front_triangles"] = [(0, 1, 2), (4, 5, 6)]
    assert m.inspect_attachment(**f)["status"] == "unverified"


@pytest.mark.parametrize("scope", ["intentional_open", "modular_clearance"])
def test_declared_detached_scope_is_not_a_pass(scope):
    """Intentional detached scope has no full-patch contact claim or acceptance authority."""
    r = m.inspect_attachment(**fixture(), scope=scope)
    assert r["status"] == "not_applicable" and r["passed"] is None


def test_generator_refuses_clipping_away_unsupported_width():
    """Refuse an invalid authored footprint rather than silently shrinking it onto support."""
    f = builder()
    f["footprint_vertices"][1] = (1.2, 0.2, 0.1)
    with pytest.raises(ValueError, match="unsupported footprint"):
        m.build_owner_relief(**f)


def test_binary32_rounding_cannot_hide_embedding_collapse():
    """Large-coordinate serialization can erase nominal embed and must block generation."""
    f = builder()
    f["owner_front_vertices"] = [(x, y + 100000.0, z) for x, y, z in f["owner_front_vertices"]]
    f["owner_back_vertices"] = [(x, y + 100000.0, z) for x, y, z in f["owner_back_vertices"]]
    f.update(embed_depth=0.0001, minimum_embed=0.00005, maximum_embed=0.0002)
    with pytest.raises(ValueError, match="simulated_binary32 attachment not proven"):
        m.build_owner_relief(**f)


def test_independent_json_binary32_geometry_recomputed():
    """Recompute from decoded coordinate bytes; subsequent lower movement fails."""
    f = fixture()
    for key in list(f):
        if key.endswith("vertices"):
            f[key] = m.float32(f[key])
    loaded = json.loads(json.dumps(f))
    assert m.inspect_attachment(**loaded)["passed"]
    loaded["lower_vertices"][0][1] = -0.01
    assert m.inspect_attachment(**loaded)["status"] == "failed"


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "0.02"])
def test_nonfinite_or_coercible_data_is_unverified(bad):
    """Data-only admission never accepts booleans, strings, or nonfinite numbers."""
    f = fixture()
    f["minimum_embed"] = bad
    assert m.inspect_attachment(**f)["status"] == "unverified"


def test_iterator_refused_without_consumption():
    """An unbounded iterator cannot enter the geometric traversal."""
    f = fixture()
    f["owner_front_vertices"] = (p for p in f["owner_front_vertices"])
    assert m.inspect_attachment(**f)["status"] == "unverified"


def test_work_exhaustion_is_unverified(monkeypatch):
    """An exhausted exact-predicate budget never becomes partial success."""
    monkeypatch.setattr(m, "MAX_CLIPS", 3)
    assert m.inspect_attachment(**fixture())["status"] == "unverified"


def test_non_height_field_owner_is_unverified():
    """A vertical selected face is unsupported rather than guessed from nearest points."""
    f = fixture()
    f["owner_front_vertices"] = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    f["owner_front_triangles"] = [(0, 1, 2)]
    assert m.inspect_attachment(**f)["status"] == "unverified"


def test_output_is_deterministic():
    """Identical explicit inputs produce identical ordered geometry and evidence."""
    first = m.build_owner_relief(**builder())
    second = m.build_owner_relief(**copy.deepcopy(builder()))
    assert first == second


def test_generated_patch_above_256_triangles_uses_complete_aabb_proof():
    """Realistic fine relief tessellation retains complete proof within the fixed pair budget."""
    f = builder()
    points = []
    faces = []
    for i in range(65):
        x = 0.125 + i / 128
        points.extend([(x, 0.25, 0.125), (x, 0.75, 0.125)])
    for i in range(64):
        a = 2 * i
        faces.extend([(a, a + 2, a + 3), (a, a + 3, a + 1)])
    f.update(footprint_vertices=points, footprint_triangles=faces)
    r = m.build_owner_relief(**f)
    assert len(r["face_roles"]["lower"]) > 256
    assert all(d["passed"] for d in r["diagnostics"].values())
    assert all(d["exact_clips"] < d["broad_phase_pairs"] for d in r["diagnostics"].values())


def complete_owner():
    """Use an independently closed generated slab as a complete solid verification fixture."""
    result = m.build_owner_relief(**builder())
    return dict(
        vertices=result["shell"].vertices,
        triangles=result["shell"].triangles,
        front_face_indices=result["face_roles"]["upper"],
        back_face_indices=result["face_roles"]["lower"],
    )


def test_complete_owner_volume_verification():
    """A complete single closed height-field slab establishes actual eligible solid volume."""
    r = m.verify_height_field_solid(**complete_owner())
    assert r["passed"] is True and r["owner_volume_verified"] is True


def test_outer_graphs_do_not_certify_an_internal_cavity():
    """An inner shell invalidates the owner despite safe exterior graph bounds."""
    f = complete_owner()
    outer = list(f["vertices"])
    inner = [(0.5 + (x - 0.5) * 0.5, y * 0.4, 0.5 + (z - 0.5) * 0.5) for x, y, z in outer]
    offset = len(outer)
    f["vertices"] = outer + inner
    f["triangles"] = list(f["triangles"]) + [
        tuple(i + offset for i in reversed(face)) for face in f["triangles"]
    ]
    r = m.verify_height_field_solid(**f)
    assert r["status"] == "unverified" and r["owner_volume_verified"] is False


def test_omitted_or_wrong_role_owner_faces_refused():
    """A convenient subset or wrong front/back role cannot certify the whole owner's interior."""
    f = complete_owner()
    f["front_face_indices"] = f["front_face_indices"][1:]
    assert m.verify_height_field_solid(**f)["status"] == "unverified"
    f = complete_owner()
    f["front_face_indices"], f["back_face_indices"] = (
        f["back_face_indices"],
        f["front_face_indices"],
    )
    assert m.verify_height_field_solid(**f)["status"] == "unverified"
