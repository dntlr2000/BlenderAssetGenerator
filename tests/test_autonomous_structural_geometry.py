"""Focused contract and deterministic-math tests for opt-in structural geometry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

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
