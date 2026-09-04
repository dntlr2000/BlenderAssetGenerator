"""Focused contract and deterministic-math tests for opt-in structural geometry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_blender_modeler.structural_geometry.composition_geometry import (
    build_balanced_component_union,
)
from codex_blender_modeler.structural_geometry.mesh_math import (
    build_loft_mesh,
    build_multi_loop_side_mesh,
    build_sweep_mesh,
    resample_polyline,
)
from codex_blender_modeler.structural_geometry.migration import (
    apply_v03_migration_plan,
    create_v03_migration_plan,
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    BooleanTreeGeometry,
    GeometryIntent,
    GeometryNodesTemplateGeometry,
    LoftGeometry,
    MultiLoopExtrudeGeometry,
    StructuralEvidenceArtifact,
    StructuralMeshPayload,
    SweepGeometry,
)
from codex_blender_modeler.structural_geometry.relief_geometry import (
    build_beveled_relief_loft,
)

NOW = datetime(2026, 8, 10, 1, 2, 3, tzinfo=UTC)


def _primitive() -> dict:
    """Return one small valid Boolean operand primitive recipe."""

    return {
        "kind": "primitive",
        "primitive": "cube",
        "dimensions": [1.0, 1.0, 1.0],
    }


def _face_normal(
    vertices: list[tuple[float, float, float]],
    face: list[int],
) -> tuple[float, float, float]:
    """Return the unnormalized right-handed normal of one ordered mesh face."""

    first, second, third = (vertices[index] for index in face[:3])
    edge_a = tuple(second[axis] - first[axis] for axis in range(3))
    edge_b = tuple(third[axis] - first[axis] for axis in range(3))
    return (
        edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
        edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
        edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
    )


def _edge_incidence(faces: list[list[int]]) -> dict[tuple[int, int], int]:
    """Count undirected face-edge incidence for one deterministic mesh payload."""

    counts: dict[tuple[int, int], int] = {}
    for face in faces:
        for first, second in zip(face, [*face[1:], face[0]], strict=True):
            edge = tuple(sorted((first, second)))
            counts[edge] = counts.get(edge, 0) + 1
    return counts


def _edge_orientation_balance(faces: list[list[int]]) -> dict[tuple[int, int], int]:
    """Sum canonical edge directions so consistently wound shared edges cancel."""

    balances: dict[tuple[int, int], int] = {}
    for face in faces:
        for first, second in zip(face, [*face[1:], face[0]], strict=True):
            edge = tuple(sorted((first, second)))
            balances[edge] = balances.get(edge, 0) + (1 if (first, second) == edge else -1)
    return balances


def test_explicit_v02_to_v03_migration_is_hash_bound() -> None:
    """Require exact legacy and candidate hashes before accepting migration."""

    source_path = Path("examples/geometry_showcase/scene_spec.seed.json")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    plan, candidate = create_v03_migration_plan(source)
    assert candidate.schema_version == "0.3.0"
    assert apply_v03_migration_plan(source, candidate, plan) == candidate
    changed = candidate.model_dump(mode="json")
    changed["revision_notes"] = [*changed["revision_notes"], "unexpected"]
    with pytest.raises(ValueError, match="candidate no longer matches"):
        apply_v03_migration_plan(source, changed, plan)


def test_loft_resamples_unequal_sections_deterministically() -> None:
    """Resample unequal closed sections and preserve stable mesh ordering."""

    raw = {
        "kind": "loft",
        "sections": [
            {
                "closed": True,
                "points": [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
            },
            {
                "closed": True,
                "points": [
                    [-0.5, -0.5, 2],
                    [0.5, -0.5, 2],
                    [0.7, 0.0, 2],
                    [0.5, 0.5, 2],
                    [-0.5, 0.5, 2],
                    [-0.7, 0.0, 2],
                ],
            },
        ],
        "resample_count": 8,
        "cap_policy": "ends",
        "correspondence_policy": "minimum_twist",
    }
    spec = LoftGeometry.model_validate_json(json.dumps(raw))
    first = build_loft_mesh(spec.model_dump(mode="json"))
    second = build_loft_mesh(spec.model_dump(mode="json"))
    assert first == second
    assert len(first["vertices"]) == 16
    assert len(first["faces"]) == 20
    assert set(_edge_incidence(first["faces"]).values()) == {2}
    assert set(_edge_orientation_balance(first["faces"]).values()) == {0}
    assert all(
        sum(value * value for value in _face_normal(first["vertices"], face)) > 1.0e-24
        for face in first["faces"]
    )


def test_loft_cap_falls_back_when_dense_resampling_makes_legacy_fans_degenerate() -> None:
    """Close dense convex sections without zero-area faces or open boundary edges."""

    spec = LoftGeometry.model_validate_json(
        json.dumps({
            "kind": "loft",
            "sections": [
                {
                    "closed": True,
                    "points": [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                },
                {
                    "closed": True,
                    "points": [[-1, -1, 2], [1, -1, 2], [1, 1, 2], [-1, 1, 2]],
                },
            ],
            "resample_count": 16,
            "cap_policy": "ends",
            "correspondence_policy": "index",
        })
    )

    payload = build_loft_mesh(spec.model_dump(mode="json"))

    assert len(payload["vertices"]) == 34
    assert len(payload["faces"]) == 48
    assert payload["vertices"][-2:] == [(0.0, 0.0, 0.0), (0.0, 0.0, 2.0)]
    assert set(_edge_incidence(payload["faces"]).values()) == {2}
    assert set(_edge_orientation_balance(payload["faces"]).values()) == {0}
    assert all(
        sum(value * value for value in _face_normal(payload["vertices"], face))
        > 1.0e-24
        for face in payload["faces"]
    )


def test_loft_reverses_faces_when_section_normal_opposes_progression() -> None:
    """Keep vertex indices stable while making a Y-axis X/Z loft face outward."""

    spec = LoftGeometry.model_validate_json(
        json.dumps({
            "kind": "loft",
            "sections": [
                {
                    "closed": True,
                    "points": [
                        [-1, -1, -1],
                        [1, -1, -1],
                        [1, -1, 1],
                        [-1, -1, 1],
                    ],
                },
                {
                    "closed": True,
                    "points": [
                        [-1, 1, -1],
                        [1, 1, -1],
                        [1, 1, 1],
                        [-1, 1, 1],
                    ],
                },
            ],
            "resample_count": 4,
            "cap_policy": "ends",
            "correspondence_policy": "index",
        })
    )

    payload = build_loft_mesh(spec.model_dump(mode="json"))
    vertices = payload["vertices"]
    mesh_center = tuple(
        sum(vertex[axis] for vertex in vertices) / len(vertices) for axis in range(3)
    )

    assert vertices[:4] == [tuple(point) for point in spec.sections[0].points]
    assert set(_edge_orientation_balance(payload["faces"]).values()) == {0}
    for face in payload["faces"]:
        normal = _face_normal(vertices, face)
        face_center = tuple(
            sum(vertices[index][axis] for index in face) / len(face)
            for axis in range(3)
        )
        outward = tuple(face_center[axis] - mesh_center[axis] for axis in range(3))
        assert sum(normal[axis] * outward[axis] for axis in range(3)) > 0


def test_beveled_relief_loft_preserves_projection_and_adds_chamfer_sections() -> None:
    """Keep the observed outer loop exact while adding bounded inset side relief."""

    points = [
        (0.26, 0.34),
        (0.80, 0.24),
        (0.88, 0.35),
        (0.78, 0.55),
        (0.33, 0.57),
    ]
    geometry = build_beveled_relief_loft(
        points,
        depth=0.24,
        bevel_depth=0.035,
        edge_inset_ratio=0.08,
    )
    assert [(x, z) for x, _y, z in geometry.sections[0].points] == points
    assert [(x, z) for x, _y, z in geometry.sections[-1].points] == points
    assert [section.points[0][1] for section in geometry.sections] == pytest.approx(
        [-0.12, -0.085, 0.085, 0.12]
    )
    inset_width = max(point[0] for point in geometry.sections[1].points) - min(
        point[0] for point in geometry.sections[1].points
    )
    outer_width = max(point[0] for point in geometry.sections[0].points) - min(
        point[0] for point in geometry.sections[0].points
    )
    assert inset_width < outer_width
    first = build_loft_mesh(geometry.model_dump(mode="json"))
    second = build_loft_mesh(geometry.model_dump(mode="json"))
    assert first == second
    assert len(first["vertices"]) == 20
    assert len(first["faces"]) == 21


@pytest.mark.parametrize(
    ("depth", "bevel_depth", "edge_inset_ratio", "message"),
    [
        (0.0, 0.01, 0.1, "depth must be positive"),
        (0.2, 0.1, 0.1, "less than half"),
        (0.2, 0.02, 0.5, "between zero and one half"),
    ],
)
def test_beveled_relief_loft_rejects_unbounded_parameters(
    depth: float,
    bevel_depth: float,
    edge_inset_ratio: float,
    message: str,
) -> None:
    """Reject non-positive, collapsed, or over-inset relief geometry."""

    with pytest.raises(ValueError, match=message):
        build_beveled_relief_loft(
            [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)],
            depth=depth,
            bevel_depth=bevel_depth,
            edge_inset_ratio=edge_inset_ratio,
        )


def test_loft_winding_produces_outward_side_and_cap_normals() -> None:
    """Verify one closed loft emits consistently outward side and cap normals."""

    spec = LoftGeometry.model_validate_json(
        json.dumps({
            "kind": "loft",
            "sections": [
                {
                    "closed": True,
                    "points": [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                },
                {
                    "closed": True,
                    "points": [[-1, -1, 2], [1, -1, 2], [1, 1, 2], [-1, 1, 2]],
                },
            ],
            "resample_count": 4,
            "cap_policy": "ends",
            "correspondence_policy": "index",
        })
    )
    payload = build_loft_mesh(spec.model_dump(mode="json"))
    vertices = payload["vertices"]
    mesh_center = tuple(
        sum(vertex[axis] for vertex in vertices) / len(vertices) for axis in range(3)
    )

    for face in payload["faces"]:
        normal = _face_normal(vertices, face)
        face_center = tuple(
            sum(vertices[index][axis] for index in face) / len(face) for axis in range(3)
        )
        outward = tuple(face_center[axis] - mesh_center[axis] for axis in range(3))
        assert sum(normal[axis] * outward[axis] for axis in range(3)) > 0
    assert payload["faces"][-4:] == [
        [3, 2, 1],
        [3, 1, 0],
        [4, 5, 6],
        [4, 6, 7],
    ]
    assert all(
        _face_normal(vertices, face)[2] < 0 for face in payload["faces"][-4:-2]
    )
    assert all(
        _face_normal(vertices, face)[2] > 0 for face in payload["faces"][-2:]
    )


def test_open_loft_builds_only_ordered_side_faces() -> None:
    """Build a valid open loft without cyclic side closure or end caps."""

    spec = LoftGeometry.model_validate_json(
        json.dumps({
            "kind": "loft",
            "sections": [
                {"closed": False, "points": [[-1, 0, 0], [0, 0, 0.5], [1, 0, 0]]},
                {"closed": False, "points": [[-1, 0, 2], [0, 0, 2.5], [1, 0, 2]]},
            ],
            "resample_count": 3,
            "cap_policy": "none",
            "correspondence_policy": "index",
        })
    )
    payload = build_loft_mesh(spec.model_dump(mode="json"))

    assert len(payload["vertices"]) == 6
    assert payload["faces"] == [[0, 1, 4, 3], [1, 2, 5, 4]]


def test_open_loft_rejects_caps_and_zero_segments() -> None:
    """Reject incompatible loft caps and duplicate consecutive section points."""

    with pytest.raises(ValidationError, match="end caps require closed"):
        LoftGeometry.model_validate_json(
            json.dumps({
                "kind": "loft",
                "sections": [
                    {"closed": False, "points": [[0, 0, 0], [1, 0, 0]]},
                    {"closed": False, "points": [[0, 0, 1], [1, 0, 1]]},
                ],
                "cap_policy": "ends",
            })
        )
    with pytest.raises(ValueError, match="zero-length"):
        resample_polyline([[0, 0, 0], [0, 0, 0]], 2, closed=False)


def test_sweep_parallel_transport_is_deterministic_and_bounded() -> None:
    """Build a curved sweep with stable topology and finite transported frames."""

    spec = SweepGeometry.model_validate_json(
        json.dumps({
            "kind": "sweep",
            "profile": [[-0.2, -0.1], [0.2, -0.1], [0.2, 0.1], [-0.2, 0.1]],
            "path": [[0, 0, 0], [0, 1, 0], [0.5, 2, 0.5], [1, 3, 1]],
            "scales": [1.0, 0.9, 0.8, 0.7],
            "twist_degrees": [0, 10, 20, 30],
        })
    )
    payload = build_sweep_mesh(spec.model_dump(mode="json"))
    assert len(payload["vertices"]) == 16
    assert len(payload["faces"]) == 16
    assert payload == build_sweep_mesh(spec.model_dump(mode="json"))


def test_straight_sweep_preserves_one_stable_profile_frame() -> None:
    """Keep profile offsets stable along a collinear uncapped sweep path."""

    spec = SweepGeometry.model_validate_json(
        json.dumps({
            "kind": "sweep",
            "profile": [[-0.2, -0.1], [0.2, -0.1], [0.2, 0.1], [-0.2, 0.1]],
            "path": [[0, 0, 0], [0, 0, 1], [0, 0, 2]],
            "cap_policy": "none",
        })
    )
    payload = build_sweep_mesh(spec.model_dump(mode="json"))
    rings = [payload["vertices"][start : start + 4] for start in range(0, 12, 4)]
    offsets = [
        [(vertex[0], vertex[1]) for vertex in ring]
        for ring in rings
    ]

    assert offsets[1] == pytest.approx(offsets[0])
    assert offsets[2] == pytest.approx(offsets[0])
    assert [[vertex[2] for vertex in ring] for ring in rings] == [
        [0.0] * 4,
        [1.0] * 4,
        [2.0] * 4,
    ]
    assert len(payload["faces"]) == 8


def test_closed_sweep_connects_the_last_ring_without_caps() -> None:
    """Close both sweep directions with two-incidence edges and no end caps."""

    spec = SweepGeometry.model_validate_json(
        json.dumps({
            "kind": "sweep",
            "profile": [[-0.1, -0.1], [0.1, -0.1], [0.1, 0.1], [-0.1, 0.1]],
            "path": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            "path_closed": True,
            "cap_policy": "none",
        })
    )
    payload = build_sweep_mesh(spec.model_dump(mode="json"))
    edge_incidence: dict[tuple[int, int], int] = {}
    for face in payload["faces"]:
        for index, first in enumerate(face):
            edge = tuple(sorted((first, face[(index + 1) % len(face)])))
            edge_incidence[edge] = edge_incidence.get(edge, 0) + 1

    assert len(payload["vertices"]) == 16
    assert len(payload["faces"]) == 16
    assert payload["faces"][-4:] == [
        [12, 13, 1, 0],
        [13, 14, 2, 1],
        [14, 15, 3, 2],
        [15, 12, 0, 3],
    ]
    assert set(edge_incidence.values()) == {2}


def test_multi_loop_contract_rejects_crossing_and_compiles_sides() -> None:
    """Accept one contained hole while rejecting a self-intersecting outer profile."""

    spec = MultiLoopExtrudeGeometry.model_validate_json(
        json.dumps({
            "kind": "multi_loop_extrude",
            "outer_loop": [[-2, -2], [2, -2], [2, 2], [-2, 2]],
            "hole_loops": [[[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5]]],
            "depth": 0.5,
            "axis": "Z",
        })
    )
    payload = build_multi_loop_side_mesh(spec.model_dump(mode="json"))
    assert len(payload["vertices"]) == 16
    assert len(payload["faces"]) == 8
    with pytest.raises(ValidationError, match="zero signed area|self-intersecting"):
        MultiLoopExtrudeGeometry.model_validate_json(
            json.dumps({
                "kind": "multi_loop_extrude",
                "outer_loop": [[0, 0], [2, 2], [0, 2], [2, 0]],
                "depth": 1,
            })
        )


def test_boolean_tree_requires_complete_non_reusing_topology() -> None:
    """Accept all Boolean operations in one tree and reject invalid operand reuse."""

    valid = BooleanTreeGeometry.model_validate_json(
        json.dumps({
            "kind": "boolean_tree",
            "operands": [
                {"id": "a", "geometry": _primitive()},
                {"id": "b", "geometry": _primitive()},
                {"id": "c", "geometry": _primitive()},
                {"id": "d", "geometry": _primitive()},
            ],
            "operations": [
                {"id": "ab", "operation": "UNION", "left_id": "a", "right_id": "b"},
                {
                    "id": "cd",
                    "operation": "DIFFERENCE",
                    "left_id": "c",
                    "right_id": "d",
                },
                {
                    "id": "root",
                    "operation": "INTERSECT",
                    "left_id": "ab",
                    "right_id": "cd",
                },
            ],
            "root_id": "root",
        })
    )
    assert valid.root_id == "root"
    assert [operation.operation for operation in valid.operations] == [
        "UNION",
        "DIFFERENCE",
        "INTERSECT",
    ]
    invalid = valid.model_dump(mode="json")
    invalid["operations"][2]["right_id"] = "a"
    with pytest.raises(ValidationError, match="consumed exactly once|unavailable"):
        BooleanTreeGeometry.model_validate_json(json.dumps(invalid))


def test_component_union_builds_one_balanced_exact_tree_deterministically() -> None:
    """Group seven disconnected profile parts into one bounded Boolean materialization."""

    components = [
        {
            "id": f"part.{index}",
            "geometry": {
                "kind": "profile_extrude",
                "profile": [[-0.4, -0.3], [0.4, -0.3], [0.4, 0.3], [-0.4, 0.3]],
                "depth": 0.2,
                "axis": "Y",
                "cap": True,
            },
            "transform": {"location": [float(index) * 1.25, 0.0, 0.0]},
        }
        for index in range(7)
    ]
    first = build_balanced_component_union(
        components,
        operation_id_prefix="laser.dark_parts",
    )
    second = build_balanced_component_union(
        components,
        operation_id_prefix="laser.dark_parts",
    )

    assert first == second
    assert len(first.operands) == 7
    assert len(first.operations) == 6
    assert first.root_id == first.operations[-1].id
    assert {item.operation for item in first.operations} == {"UNION"}
    assert {item.solver for item in first.operations} == {"EXACT"}
    assert [item.id for item in first.operations[:3]] == [
        "laser.dark_parts.01",
        "laser.dark_parts.02",
        "laser.dark_parts.03",
    ]


@pytest.mark.parametrize("component_count", [1, 33])
def test_component_union_rejects_out_of_contract_cardinality(
    component_count: int,
) -> None:
    """Reject a component group that cannot fit the bounded Boolean-tree contract."""

    components = [
        {
            "id": f"part.{index}",
            "geometry": _primitive(),
        }
        for index in range(component_count)
    ]
    with pytest.raises(ValueError, match="between two and 32"):
        build_balanced_component_union(components)


def test_component_union_rejects_generated_operation_id_collision() -> None:
    """Fail closed when a component identity collides with a generated union node."""

    components = [
        {"id": "component_union.01", "geometry": _primitive()},
        {"id": "part.other", "geometry": _primitive()},
    ]
    with pytest.raises(ValueError, match="collides with an operand"):
        build_balanced_component_union(components)


def test_boolean_mesh_payload_rejects_an_empty_result() -> None:
    """Reject an empty Boolean materialization at the strict host payload boundary."""

    with pytest.raises(ValidationError, match="at least 3 items|at least 1 item"):
        StructuralMeshPayload.model_validate_json(
            json.dumps({
                "schema_version": "0.1.0",
                "semantic_id": "asset.empty_boolean",
                "builder_kind": "boolean_tree",
                "vertices": [],
                "faces": [],
            })
        )


def test_geometry_intent_and_nodes_template_are_strict() -> None:
    """Reject duplicate topology intent and unknown Geometry Nodes template fields."""

    with pytest.raises(ValidationError, match="must not repeat"):
        GeometryIntent.model_validate_json(
            json.dumps({
                "sharp_edges": [
                    {"vertices": [0, 1]},
                    {"vertices": [0, 1]},
                ]
            })
        )
    template = GeometryNodesTemplateGeometry.model_validate_json(
        json.dumps({
            "kind": "geometry_nodes_template",
            "template_id": "linear_instance_v1",
            "count": 5,
            "spacing": [1, 0, 0],
            "instance_dimensions": [0.5, 0.5, 0.5],
        })
    )
    assert template.count == 5
    with pytest.raises(ValidationError):
        GeometryNodesTemplateGeometry.model_validate_json(
            json.dumps(
                {**template.model_dump(mode="json"), "arbitrary_node": "Python"}
            )
        )


def test_asset_scale_context_scales_ratios_but_preserves_absolute_overrides() -> None:
    """Resolve ratio-derived features by asset size and preserve exact metric overrides."""

    provenance = [
        StructuralEvidenceArtifact(
            role="scene_spec",
            path="analysis/scene_spec.json",
            sha256="a" * 64,
        )
    ]
    small = AssetScaleContext.from_bounds(
        asset_id="small",
        job_id="scale_test",
        workflow_id="workflow.scale",
        dispatch_id="dispatch.scale",
        source_fingerprint="b" * 64,
        producer="tests.asset_scale",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=NOW,
        local_minimum=(0, 0, 0),
        local_maximum=(0.1, 0.2, 0.3),
        assembly_minimum=(0, 0, 0),
        assembly_maximum=(0.1, 0.2, 0.3),
        projected_pixel_size=256,
        target_texel_density_px_m=512,
        absolute_overrides_m={"seam_width": 0.002},
    )
    large = AssetScaleContext.from_bounds(
        asset_id="large",
        job_id="scale_test",
        workflow_id="workflow.scale",
        dispatch_id="dispatch.scale",
        source_fingerprint="b" * 64,
        producer="tests.asset_scale",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=NOW,
        local_minimum=(0, 0, 0),
        local_maximum=(10, 20, 30),
        assembly_minimum=(0, 0, 0),
        assembly_maximum=(10, 20, 30),
        projected_pixel_size=1024,
        target_texel_density_px_m=512,
        absolute_overrides_m={"seam_width": 0.002},
    )
    assert large.resolve_length("bevel", 0.01) == pytest.approx(
        small.resolve_length("bevel", 0.01) * 100
    )
    assert small.resolve_length("seam_width", 0.01) == 0.002
    assert large.resolve_length("seam_width", 0.01) == 0.002
    assert small.recommended_texture_resolution() == 256
    assert large.recommended_texture_resolution() == 8192
    missing = small.model_dump(mode="json")
    for field in (
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "producer",
        "producer_version",
        "provenance",
        "created_at",
    ):
        missing.pop(field)
    with pytest.raises(ValidationError):
        AssetScaleContext.model_validate_json(json.dumps(missing))
    partial = small.model_dump(mode="json")
    partial.pop("producer_version")
    with pytest.raises(ValidationError):
        AssetScaleContext.model_validate_json(json.dumps(partial))
