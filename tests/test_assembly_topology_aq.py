"""Focused tests for assembly narrow phase and profile-driven topology evidence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from codex_blender_modeler.blender_scripts.assembly import (
    AABB,
    AssemblyCompanionRequest,
    BVHNarrowObservation,
    SemanticAssemblyRelation,
    TriangleMeshEvidence,
    bounded_nearest_distance,
    build_assembly_companion_report,
)
from codex_blender_modeler.blender_scripts.assembly.models import (
    AssemblyArtifact,
    AssemblyProvenance,
)
from codex_blender_modeler.blender_scripts.topology import (
    PROFILE_NAMES,
    TopologyArtifact,
    TopologyObservation,
    TopologyProvenance,
    evaluate_topology_profile,
    get_topology_profile,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _assembly_artifact(role: str, path: str, digest: str = SHA_A) -> AssemblyArtifact:
    """Build one valid assembly artifact binding."""

    return AssemblyArtifact(role=role, path=path, sha256=digest)


def _assembly_provenance() -> AssemblyProvenance:
    """Build exact canonical assembly provenance."""

    return AssemblyProvenance(
        job_id="prop_a",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        project_version="0.9.0",
        inputs=[
            _assembly_artifact("scene_spec", "analysis/scene_spec.json", SHA_A),
            _assembly_artifact("modeling_plan", "analysis/modeling_plan.json", SHA_B),
            _assembly_artifact("blend", "blender/scene.blend", SHA_C),
        ],
    )


def _mesh(object_id: str, z: float, digest: str) -> TriangleMeshEvidence:
    """Build one flat evaluated triangle with a positive evidence bound."""

    return TriangleMeshEvidence(
        object_id=object_id,
        snapshot=_assembly_artifact(
            "mesh_snapshot", f"reports/assembly/{object_id}.mesh.json", digest
        ),
        bounds=AABB(minimum=(0, 0, z - 1e-6), maximum=(1, 1, z + 1e-6)),
        vertices_m=[(0, 0, z), (1, 0, z), (0, 1, z)],
        triangles=[(0, 1, 2)],
    )


def test_bounded_nearest_distance_and_required_contact_failure() -> None:
    """Measure separated meshes and fail a required contact without false penetration."""

    first = _mesh("part.a", 0.0, SHA_A)
    second = _mesh("part.b", 0.1, SHA_B)
    distance, samples = bounded_nearest_distance(first, second, maximum_samples=8)
    assert distance == pytest.approx(0.1)
    assert 1 <= samples <= 8
    request = AssemblyCompanionRequest(
        request_id="assembly-a",
        provenance=_assembly_provenance(),
        meshes=[first, second],
        semantic_relations=[
            SemanticAssemblyRelation(
                relation_id="contact-a-b",
                kind="required_contact",
                subject_id="part.a",
                reference_id="part.b",
                maximum_m=0.01,
            )
        ],
        maximum_distance_samples=8,
    )
    report = build_assembly_companion_report(
        request,
        request_path="reports/assembly/request.json",
        request_sha256=SHA_C,
        report_id="assembly-report-a",
    )
    assert report.status == "failed"
    assert any(item.code == "SEMANTIC_REQUIRED_CONTACT" for item in report.findings)
    assert not any(item.code == "MESH_PENETRATION" for item in report.findings)


def test_signed_blender_bvh_penetration_is_a_hard_finding() -> None:
    """Treat explicit signed Blender BVH penetration as hard evidence."""

    first = _mesh("part.a", 0.0, SHA_A)
    second = _mesh("part.b", 0.0, SHA_B)
    request = AssemblyCompanionRequest(
        request_id="assembly-b",
        provenance=_assembly_provenance(),
        meshes=[first, second],
        narrow_observations=[
            BVHNarrowObservation(
                subject_id="part.a",
                reference_id="part.b",
                status="available",
                backend="blender_bvh",
                overlap_triangle_pair_count=2,
                minimum_distance_m=0.0,
                penetration_depth_m=0.02,
                sampled_point_count=6,
                bounded_sample_limit=32,
            )
        ],
        semantic_relations=[
            SemanticAssemblyRelation(
                relation_id="contact-a-b",
                kind="required_contact",
                subject_id="part.a",
                reference_id="part.b",
                maximum_m=0.01,
            )
        ],
    )
    report = build_assembly_companion_report(
        request,
        request_path="reports/assembly/request-b.json",
        request_sha256=SHA_C,
        report_id="assembly-report-b",
    )
    assert report.status == "failed"
    assert any(item.code == "MESH_PENETRATION" for item in report.findings)


def test_empty_mesh_relation_is_unscorable_not_passed() -> None:
    """Keep empty evaluated geometry unavailable instead of inventing contact success."""

    empty = TriangleMeshEvidence(
        object_id="part.empty",
        snapshot=_assembly_artifact(
            "mesh_snapshot", "reports/assembly/empty.mesh.json", SHA_A
        ),
        bounds=AABB(minimum=(0, 0, 0), maximum=(1, 1, 1)),
        vertices_m=[],
        triangles=[],
    )
    other = _mesh("part.other", 0.0, SHA_B)
    request = AssemblyCompanionRequest(
        request_id="assembly-empty",
        provenance=_assembly_provenance(),
        meshes=[empty, other],
        semantic_relations=[
            SemanticAssemblyRelation(
                relation_id="empty-contact",
                kind="required_contact",
                subject_id="part.empty",
                reference_id="part.other",
                maximum_m=0.01,
            )
        ],
    )
    report = build_assembly_companion_report(
        request,
        request_path="reports/assembly/request-empty.json",
        request_sha256=SHA_C,
        report_id="assembly-report-empty",
    )
    assert report.status == "unscorable"
    assert report.ok is False


def _topology_artifact(role: str, path: str, digest: str = SHA_A) -> TopologyArtifact:
    """Build one portable topology artifact binding."""

    return TopologyArtifact(role=role, path=path, sha256=digest)


def _topology_provenance() -> TopologyProvenance:
    """Build exact source provenance for profile evaluation."""

    return TopologyProvenance(
        job_id="prop_a",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        project_version="0.9.0",
        inputs=[
            _topology_artifact("scene_spec", "analysis/scene_spec.json", SHA_A),
            _topology_artifact("blend", "blender/scene.blend", SHA_B),
        ],
    )


def _passing_observations(profile_name: str) -> list[TopologyObservation]:
    """Build explicit available passing evidence for every profile check."""

    evidence = _topology_artifact(
        "topology_inventory", "reports/topology/inventory.json", SHA_C
    )
    return [
        TopologyObservation(
            check=policy.check,
            availability="available",
            passed=True,
            measured_value=0,
            evidence=evidence,
            message="fixture passes",
        )
        for policy in get_topology_profile(profile_name).checks
    ]


def test_all_six_topology_profiles_have_complete_classification() -> None:
    """Expose exactly the six requested profiles with all 18 checks."""

    assert set(PROFILE_NAMES) == {
        "static_prop_closed",
        "static_prop_open",
        "game_ready_lowpoly",
        "highpoly_bake_source",
        "modular_architecture",
        "terrain",
    }
    assert all(len(get_topology_profile(name).checks) == 18 for name in PROFILE_NAMES)


def test_profile_distinguishes_closed_hard_failure_from_open_warning() -> None:
    """Classify an open boundary differently for closed and intentionally open props."""

    closed = _passing_observations("static_prop_closed")
    opened = _passing_observations("static_prop_open")
    for observations in (closed, opened):
        index = next(i for i, item in enumerate(observations) if item.check == "open_boundary")
        observations[index] = observations[index].model_copy(update={"passed": False})
    closed_report = evaluate_topology_profile(
        report_id="topology-closed",
        provenance=_topology_provenance(),
        profile_name="static_prop_closed",
        observations=closed,
    )
    open_report = evaluate_topology_profile(
        report_id="topology-open",
        provenance=_topology_provenance(),
        profile_name="static_prop_open",
        observations=opened,
    )
    assert closed_report.status == "failed"
    assert open_report.status == "warning"
    assert open_report.ok is True


@pytest.mark.parametrize(
    "check",
    [
        "uv0",
        "tangent",
        "lod_silhouette_error",
        "clean_import_normal_preservation",
        "clean_import_material_preservation",
    ],
)
def test_unavailable_portability_evidence_is_unscorable(check: str) -> None:
    """Never turn missing UV, tangent, LOD, or round-trip evidence into pass."""

    observations = _passing_observations("game_ready_lowpoly")
    index = next(i for i, item in enumerate(observations) if item.check == check)
    observations[index] = TopologyObservation(
        check=check,
        availability="unavailable",
        message="fixture intentionally omitted evidence",
    )
    report = evaluate_topology_profile(
        report_id=f"topology-{check}",
        provenance=_topology_provenance(),
        profile_name="game_ready_lowpoly",
        observations=observations,
    )
    assert report.status == "unscorable"
    assert report.ok is False
    result = next(item for item in report.results if item.check == check)
    assert result.outcome == "unscorable"


def test_topology_contract_rejects_extra_fields_and_absolute_paths() -> None:
    """Fail closed on schema drift and host-specific evidence locations."""

    with pytest.raises(ValidationError, match="Extra inputs"):
        TopologyObservation.model_validate(
            {
                "check": "uv0",
                "availability": "unavailable",
                "message": "missing",
                "pretend_pass": True,
            }
        )
    with pytest.raises(ValidationError, match="path"):
        _topology_artifact("uv_report", "E:/unsafe/uv.json")
