"""Exact adjacent-triangle predicates and native bounded topology reliability regressions."""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

import pytest

from codex_blender_modeler.blender_scripts.self_intersection_runtime import (
    bounded_self_intersection,
    triangle_pair_intersection,
)
from codex_blender_modeler.blender_scripts.topology import (
    TopologyArtifact,
    TopologyObservation,
    TopologyProvenance,
    evaluate_topology_profile,
    get_topology_profile,
)
from codex_blender_modeler.config import get_settings

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "src/codex_blender_modeler/blender_scripts"
# Two minimal measured regressions from immutable sheet payload SHA256
# 8b26b0772ae3f9d92f2f1b3ba967313611bd51f5326bf984b0d952bdbaa564b4.
# Original face pairs: (9496,18138), (6497,18138); only a common vertex is legitimate.
RUST_FIXTURES = {'rust_crossing_a': {'vertices': [[-0.2913858890533447,
                                   -0.126092329621315,
                                   -0.4969669282436371],
                                  [-0.2728075385093689,
                                   -0.14991651475429535,
                                   -0.562538743019104],
                                  [-0.21329276263713837,
                                   -0.22742097079753876,
                                   -0.5872434973716736],
                                  [-0.21296057105064392,
                                   -0.1327803134918213,
                                   -0.5662364363670349],
                                  [-0.2886326014995575,
                                   -0.15586833655834198,
                                   -0.5626434087753296]],
                     'triangles': [[4, 2, 1], [3, 0, 4]],
                     'expected': 'intersects'},
 'rust_crossing_b': {'vertices': [[-0.2913858890533447,
                                   -0.126092329621315,
                                   -0.4969669282436371],
                                  [-0.2728075385093689,
                                   -0.14991651475429535,
                                   -0.562538743019104],
                                  [-0.21329276263713837,
                                   -0.22742097079753876,
                                   -0.5872434973716736],
                                  [-0.21296057105064392,
                                   -0.1327803134918213,
                                   -0.5662364363670349],
                                  [-0.2886326014995575,
                                   -0.15586833655834198,
                                   -0.5626434087753296]],
                     'triangles': [[3, 1, 2], [3, 0, 4]],
                     'expected': 'intersects'}}

# Repaired exact negative payload SHA256
# 948ed310552d87f5f0d72c322ac931a104f7536def43e2502693e7c264d774f1.
RUST_FIXTURES.update({'rust_repaired_a': {'vertices': [[-0.2913858890533447,
                                   -0.126092329621315,
                                   -0.4969669282436371],
                                  [-0.272309273481369,
                                   -0.15135957300662994,
                                   -0.5618352890014648],
                                  [-0.21329276263713837,
                                   -0.22742097079753876,
                                   -0.5872434973716736],
                                  [-0.21296057105064392,
                                   -0.1327803134918213,
                                   -0.5662364363670349],
                                  [-0.2876110076904297,
                                   -0.15728138387203217,
                                   -0.5636230111122131]],
                     'triangles': [[4, 2, 1], [3, 0, 4]],
                     'expected': 'clear'},
 'rust_repaired_b': {'vertices': [[-0.2913858890533447,
                                   -0.126092329621315,
                                   -0.4969669282436371],
                                  [-0.272309273481369,
                                   -0.15135957300662994,
                                   -0.5618352890014648],
                                  [-0.21329276263713837,
                                   -0.22742097079753876,
                                   -0.5872434973716736],
                                  [-0.21296057105064392,
                                   -0.1327803134918213,
                                   -0.5662364363670349],
                                  [-0.2876110076904297,
                                   -0.15728138387203217,
                                   -0.5636230111122131]],
                     'triangles': [[3, 1, 2], [3, 0, 4]],
                     'expected': 'clear'}})

FIXTURES = {
    "noncoplanar_vertex_contact": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 1, 1), (-1, -1, 1)],
        "triangles": [(0, 1, 2), (0, 3, 4)], "expected": "clear",
    },
    "noncoplanar_vertex_crossing": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 1, -1), (1, 1, 1)],
        "triangles": [(0, 1, 2), (0, 3, 4)], "expected": "intersects",
    },
    "noncoplanar_edge_contact": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 2)],
        "triangles": [(0, 1, 2), (0, 1, 3)], "expected": "clear",
    },
    "coplanar_vertex_contact": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (-2, 0, 0), (0, -2, 0)],
        "triangles": [(0, 1, 2), (0, 3, 4)], "expected": "clear",
    },
    "coplanar_vertex_overlap": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0.25, 0), (0.25, 1, 0)],
        "triangles": [(0, 1, 2), (0, 3, 4)], "expected": "intersects",
    },
    "coplanar_edge_contact": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, -2, 0)],
        "triangles": [(0, 1, 2), (0, 1, 3)], "expected": "clear",
    },
    "coplanar_edge_overlap": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 1, 0)],
        "triangles": [(0, 1, 2), (0, 1, 3)], "expected": "intersects",
    },
    "coplanar_nonshared_edge_contact": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0, 0), (0, -1, 0)],
        "triangles": [(0, 1, 2), (0, 3, 4)], "expected": "clear",
    },
    "duplicate_face": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0)],
        "triangles": [(0, 1, 2), (0, 2, 1)], "expected": "intersects",
    },
    "degenerate_face": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0, 0)],
        "triangles": [(0, 1, 2), (0, 1, 3)], "expected": "unavailable",
    },
    "nonadjacent_coplanar_contained": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0),
                     (0.25, 0.25, 0), (1, 0.25, 0), (0.25, 1, 0)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "intersects",
    },
    "nonadjacent_coplanar_disjoint": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (2, 2, 0), (3, 2, 0), (2, 3, 0)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "clear",
    },
    "nonadjacent_parallel_planes": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 1), (2, 0, 1), (0, 2, 1)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "clear",
    },
    "nonadjacent_duplicate_positions": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 0), (2, 0, 0), (0, 2, 0)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "intersects",
    },
    "nonadjacent_nonplanar_crossing": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0),
                     (0.5, 0.5, -1), (0.5, 0.5, 1), (1, 1, 1)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "intersects",
    },
    "split_vertex_edge_contact": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 0), (2, 0, 0), (0, 0, 2)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "clear",
    },
    "split_vertex_point_contact": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 0), (-1, 0, 1), (0, -1, 1)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "clear",
    },
    "coplanar_boundary_t_junction": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0, 0), (0.5, -1, 0), (1.5, -1, 0)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "clear",
    },
    "noncoplanar_boundary_t_junction": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, 0, 0), (1, -1, 1), (1, -1, -1)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "clear",
    },
    "vertex_into_face_interior": {
        "vertices": [(0, 0, 0), (2, 0, 0), (0, 2, 0),
                     (0.5, 0.5, 0), (0.5, 0.5, 1), (1, 0.5, 1)],
        "triangles": [(0, 1, 2), (3, 4, 5)], "expected": "intersects",
    },
    **RUST_FIXTURES,
}


@pytest.mark.parametrize("name", FIXTURES)
@pytest.mark.parametrize("reverse", [False, True])
def test_shared_boundary_exact_predicates(name, reverse):
    """Distinguish genuine crossings, legitimate contact, duplicates and degenerate evidence."""

    fixture = FIXTURES[name]
    first, second = [tuple(face) for face in fixture["triangles"]]
    if reverse:
        first, second = tuple(reversed(second)), tuple(reversed(first))
    assert triangle_pair_intersection(fixture["vertices"], first, second) == fixture["expected"]


@pytest.mark.parametrize("sign,expected", [(1, "intersects"), (-1, "clear")])
@pytest.mark.parametrize("size", [2.0**-30, 1.0, 2.0**30])
def test_no_world_distance_epsilon_can_hide_coplanar_overlap(sign, expected, size):
    """Keep very thin coplanar overlap distinct from contact at widely separated object scales."""

    vertices = [(0, 0, 0), (2*size, 0, 0), (0, 2*size, 0), (size, sign*1e-30*size, 0)]
    assert triangle_pair_intersection(vertices, (0, 1, 2), (0, 1, 3)) == expected


def test_invalid_nonfinite_shared_triangle_is_unavailable():
    """Never turn undefined exact geometry into a clean shared-boundary pass."""

    vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, float("nan"), 1)]
    assert triangle_pair_intersection(vertices, (0, 1, 2), (0, 1, 3)) == "unavailable"
    assert triangle_pair_intersection(vertices, (0, 1, 2), (0, 1, 99)) == "unavailable"


def _native_namespace(*, exact_budget=100_000):
    """Extract the native wrapper with the real exact backend, without importing bpy in CI."""

    source = ast.parse((SCRIPT_ROOT / "inspect_quality_companions.py").read_text())
    function = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "_bounded_self_intersection"
    )
    namespace = {
        "Vector": object, "Any": object,
        "MAX_SELF_INTERSECTION_TRIANGLES": 5000,
        "MAX_SELF_INTERSECTION_PAIR_TESTS": exact_budget,
        "bounded_self_intersection": bounded_self_intersection,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "native_self_intersection", "exec"),
         namespace)
    return namespace


@pytest.mark.parametrize("name", FIXTURES)
def test_native_candidate_pair_classification_never_drops_shared_vertices(name):
    """The native candidate loop consumes exact contact/crossing/unavailable results faithfully."""

    fixture = FIXTURES[name]
    namespace = _native_namespace()
    result = namespace["_bounded_self_intersection"](fixture["vertices"], fixture["triangles"])
    if fixture["expected"] == "unavailable":
        assert result["availability"] == "unavailable" and "passed" not in result
    else:
        assert result["availability"] == "available"
        assert result["passed"] == (fixture["expected"] == "clear")
        assert result["measured_value"] == (fixture["expected"] == "intersects")


def test_exact_work_budget_exhaustion_is_unavailable_and_known_failures_stay_failed():
    """Bound new rational work while retaining positive intersection evidence found beforehand."""

    fixture = FIXTURES["noncoplanar_edge_contact"]
    namespace = _native_namespace(exact_budget=0)
    result = namespace["_bounded_self_intersection"](fixture["vertices"], fixture["triangles"])
    assert result["availability"] == "unavailable" and "budget" in result["message"]
    namespace = _native_namespace(exact_budget=1)
    crossing = FIXTURES["coplanar_vertex_overlap"]
    triangles = [*crossing["triangles"], crossing["triangles"][1]]
    result = namespace["_bounded_self_intersection"](crossing["vertices"], triangles)
    assert result["availability"] == "available" and result["passed"] is False
    assert result["measured_value"] == 1 and "pair budget exhausted=True" in result["message"]


def test_original_triangle_budget_and_nonadjacent_failures_are_unchanged():
    """Retain the 5,000-triangle ceiling and fail confirmed nonadjacent coplanar overlap."""

    namespace = _native_namespace()
    check = namespace["_bounded_self_intersection"]
    assert check([], [(0, 1, 2)] * 5001)["availability"] == "unavailable"
    assert check([], [])["availability"] == "unavailable"
    result = check(
        [(0, 0, 0), (2, 0, 0), (0, 2, 0), (0.25, 0.25, 0), (1, 0.25, 0), (0.25, 1, 0)],
        [(0, 1, 2), (3, 4, 5)],
    )
    assert result["availability"] == "available" and result["passed"] is False
    assert result["measured_value"] == 1


@pytest.mark.parametrize("availability,passed,outcome", [
    ("available", False, "hard_failure"), ("unavailable", None, "unscorable"),
])
def test_incomplete_or_crossing_self_check_cannot_be_a_topology_hard_pass(
    availability, passed, outcome
):
    """Keep self-intersection reliability visible to the unchanged hard-gate companion profile."""

    evidence = TopologyArtifact(role="topology_inventory", path="reports/test.json", sha256="a"*64)
    observations = [
        TopologyObservation(
            check=policy.check, availability="available", passed=True, evidence=evidence,
            message="Synthetic other-check pass for isolated outcome projection.",
        ) for policy in get_topology_profile("static_prop_closed").checks
    ]
    index = next(i for i, item in enumerate(observations) if item.check == "self_intersection")
    observations[index] = TopologyObservation(
        check="self_intersection", availability=availability, passed=passed,
        evidence=evidence if availability == "available" else None,
        message="Exact source-bound shared-triangle regression outcome.",
    )
    report = evaluate_topology_profile(
        report_id="self-intersection-regression",
        provenance=TopologyProvenance(
            job_id="intersection_fixture", workflow_id="workflow-fixture",
            dispatch_id="dispatch-fixture", project_version="0.9.0", inputs=[
                TopologyArtifact(role="scene_spec", path="analysis/scene_spec.json", sha256="b"*64),
                TopologyArtifact(role="blend", path="blender/scene.blend", sha256="c"*64),
            ],
        ),
        profile_name="static_prop_closed", observations=observations,
    )
    assert next(
        item.outcome for item in report.results if item.check == "self_intersection"
    ) == outcome
    assert report.status != "passed"


@pytest.mark.skipif(
    os.getenv("CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE") != "1",
    reason="Set CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE=1 for Blender 5.0.1 BVH regression.",
)
def test_blender_five_native_adjacent_crossings_and_clean_contacts(tmp_path):
    """Execute the real inspector/BVH with portable measured pairs and clean manifold fixtures."""

    fixtures = {
        name: fixture for name, fixture in FIXTURES.items()
    }
    input_path = tmp_path / "fixtures.json"
    input_path.write_text(json.dumps(fixtures))
    output = tmp_path / "native-results.json"
    script = tmp_path / "probe.py"
    script.write_text('''import json,sys
from pathlib import Path
import bpy
from mathutils import Vector
source,inputs,output=sys.argv[sys.argv.index("--")+1:]
sys.path.insert(0,source)
from inspect_quality_companions import _bounded_self_intersection
fixtures=json.loads(Path(inputs).read_text())
result={"blender_version":bpy.app.version_string,"fixtures":{}}
for name,fixture in fixtures.items():
    vertices=[Vector(value) for value in fixture["vertices"]]
    result["fixtures"][name]=_bounded_self_intersection(vertices,fixture["triangles"])
Path(output).write_text(json.dumps(result,indent=2)+"\\n")
''')
    settings = get_settings()
    command = [settings.blender_bin, "--factory-startup", "--disable-autoexec", "--background",
               "--python-exit-code", "1", "--python", str(script), "--", str(SCRIPT_ROOT),
               str(input_path), str(output)]
    completed = subprocess.run(
        command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=settings.blender_timeout, check=False,
    )
    (tmp_path / "blender.log").write_text(completed.stdout + completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(output.read_bytes())
    assert result["blender_version"] == "5.0.1"
    for name, fixture in fixtures.items():
        check = result["fixtures"][name]
        if fixture["expected"] == "unavailable":
            assert check["availability"] == "unavailable" and "passed" not in check, name
        else:
            assert check["availability"] == "available", name
            assert check["passed"] == (fixture["expected"] == "clear"), name


def test_aabb_rejection_and_exact_budget_boundary_do_not_invent_missing_work():
    """A disjoint broadphase or exactly consumed complete budget remains eligible for a pass."""

    disjoint = FIXTURES["nonadjacent_parallel_planes"]
    result = bounded_self_intersection(
        disjoint["vertices"], disjoint["triangles"], max_triangles=5000, max_pair_tests=0
    )
    assert result["availability"] == "available" and result["passed"] is True
    contact = FIXTURES["noncoplanar_edge_contact"]
    result = bounded_self_intersection(
        contact["vertices"], contact["triangles"], max_triangles=5000, max_pair_tests=1
    )
    assert result["availability"] == "available" and result["passed"] is True
    assert "pair budget exhausted=False" in result["message"]


def test_closed_cube_is_clean_under_complete_inclusive_candidate_enumeration():
    """Ordinary indexed manifold adjacency is accepted after checking every overlapping AABB."""

    vertices = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    triangles = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
                 (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    result = bounded_self_intersection(
        vertices, triangles, max_triangles=5000, max_pair_tests=100_000
    )
    assert result["availability"] == "available" and result["passed"] is True
    assert result["measured_value"] == 0
