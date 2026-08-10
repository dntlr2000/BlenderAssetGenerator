"""Blender 5 evidence tests for AQ scale, assembly, and topology companions."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.blender_scripts.assembly import (
    AABB,
    AssemblyCompanionRequest,
    BVHNarrowObservation,
    SemanticAssemblyRelation,
    TriangleMeshEvidence,
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
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    StructuralEvidenceArtifact,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _sha256(path: Path) -> str:
    """Hash one generated smoke artifact exactly as its companion contract does."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_contract(path: Path, model: Any) -> None:
    """Persist one strict companion model beside the raw Blender evidence."""

    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _scale_context(scale_m: float) -> AssetScaleContext:
    """Build one context whose shortest local dimension equals the fixture scale."""

    half = scale_m * 0.5
    return AssetScaleContext.from_bounds(
        asset_id=f"fixture.scale.{scale_m:g}",
        job_id="aq_blender_smoke",
        workflow_id="wf-aq-blender-smoke",
        dispatch_id="dispatch-aq-blender-smoke",
        source_fingerprint=SHA_A,
        producer="tests.aq_blender_scale",
        producer_version="0.1.0",
        provenance=[
            StructuralEvidenceArtifact(
                role="scene_spec",
                path="analysis/scene_spec.json",
                sha256=SHA_A,
            )
        ],
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
        local_minimum=(-half, -half, -half),
        local_maximum=(half, half, half),
        assembly_minimum=(-half, -half, -half),
        assembly_maximum=(half, half, half),
        projected_pixel_size=256.0,
        target_texel_density_px_m=256.0,
    )


def test_scale_context_declares_identical_relative_bevel_at_three_scales() -> None:
    """Bind the 0.1 m, 1 m, and 10 m fixtures to one 2% bevel policy."""

    contexts = [_scale_context(scale_m) for scale_m in (0.1, 1.0, 10.0)]
    resolved = [context.resolve_length("bevel", 0.02) for context in contexts]
    assert resolved == pytest.approx([0.002, 0.02, 0.2])
    ratios = [
        value / context.shortest_dimension_m
        for value, context in zip(resolved, contexts, strict=True)
    ]
    assert ratios == pytest.approx([0.02, 0.02, 0.02])


def _topology_provenance() -> TopologyProvenance:
    """Build stable smoke provenance for one generated Blender report."""

    return TopologyProvenance(
        job_id="aq_blender_smoke",
        workflow_id="wf-aq-blender-smoke",
        dispatch_id="dispatch-aq-blender-smoke",
        project_version="0.9.0",
        inputs=[
            TopologyArtifact(
                role="scene_spec",
                path="analysis/scene_spec.json",
                sha256=SHA_A,
            ),
            TopologyArtifact(
                role="blend",
                path="blender/scene.blend",
                sha256=SHA_B,
            ),
        ],
    )


def _topology_observations(
    fixture: dict[str, Any],
    evidence: TopologyArtifact,
) -> list[TopologyObservation]:
    """Translate measured Blender fixture values into all profile check outcomes."""

    topology = fixture["topology"]
    uv_layers = topology["uv_layers"]
    tangent = fixture["tangent"]
    measured: dict[str, tuple[bool, Any, Any, str]] = {
        "non_finite": (
            topology["non_finite_vertex_count"] == 0,
            topology["non_finite_vertex_count"],
            0,
            "Blender mesh vertices are finite.",
        ),
        "degenerate_face": (
            topology["degenerate_face_count"] == 0,
            topology["degenerate_face_count"],
            0,
            "Blender reports no degenerate faces.",
        ),
        "self_intersection": (
            fixture["self_intersection_pair_count"] == 0,
            fixture["self_intersection_pair_count"],
            0,
            "Non-adjacent cube triangles have no Blender BVH self-overlap.",
        ),
        "winding": (
            fixture["outward_normal_failure_count"] == 0,
            fixture["outward_normal_failure_count"],
            0,
            "Centered convex fixture normals point outward.",
        ),
        "flipped_normal": (
            fixture["outward_normal_failure_count"] == 0,
            fixture["outward_normal_failure_count"],
            0,
            "No outward-normal failure was measured.",
        ),
        "loose_geometry": (
            topology["loose_edge_count"] + topology["loose_vertex_count"] == 0,
            topology["loose_edge_count"] + topology["loose_vertex_count"],
            0,
            "Blender topology inventory has no loose geometry.",
        ),
        "open_boundary": (
            topology["boundary_edge_count"] == 0,
            topology["boundary_edge_count"],
            0,
            "The fixture is a closed manifold cube.",
        ),
        "triangle_aspect": (
            fixture["maximum_triangle_aspect_ratio"] <= 2.1,
            fixture["maximum_triangle_aspect_ratio"],
            2.1,
            "Cube triangulation remains inside the bounded aspect ratio.",
        ),
        "ngon_limit": (
            fixture["maximum_polygon_sides"] <= 4,
            fixture["maximum_polygon_sides"],
            4,
            "The fixture contains quads only.",
        ),
        "uv0": (
            bool(uv_layers) and uv_layers[0]["degenerate_face_count"] == 0,
            len(uv_layers),
            1,
            "A complete non-degenerate UVMap exists.",
        ),
        "uv_overlap": (
            fixture["uv_overlap"]["overlap_pair_count"] == 0,
            fixture["uv_overlap"]["overlap_pair_count"],
            0,
            "Positive-area overlap is measured from actual polygon-corner UVs.",
        ),
        "island_padding": (
            fixture["minimum_island_padding_uv"] >= 0.01,
            fixture["minimum_island_padding_uv"],
            0.01,
            "The deterministic atlas reserves bounded island padding.",
        ),
        "texel_density": (
            fixture["uniform_texel_density_fixture"],
            fixture["uniform_texel_density_fixture"],
            1,
            "All six equal-area faces use equal atlas cells.",
        ),
        "tangent": (
            tangent["finite_unit_tangent_count"] == tangent["loop_count"],
            tangent["finite_unit_tangent_count"],
            tangent["loop_count"],
            "Blender calculated finite unit tangents for every loop.",
        ),
    }
    observations = [
        TopologyObservation(
            check=check,
            availability="available",
            passed=passed,
            measured_value=value,
            threshold=threshold,
            evidence=evidence,
            message=message,
        )
        for check, (passed, value, threshold, message) in measured.items()
    ]
    observations.extend(
        TopologyObservation(
            check=check,
            availability="not_applicable",
            message="This Blender-local fixture does not exercise the downstream check.",
        )
        for check in (
            "subdivision_pinching",
            "lod_silhouette_error",
            "clean_import_normal_preservation",
            "clean_import_material_preservation",
        )
    )
    return observations


def _assembly_artifact(role: str, path: str, digest: str) -> AssemblyArtifact:
    """Create one exact smoke artifact binding."""

    return AssemblyArtifact(role=role, path=path, sha256=digest)


def _mesh_from_blender_payload(
    object_id: str,
    payload: dict[str, Any],
    snapshot: AssemblyArtifact,
) -> TriangleMeshEvidence:
    """Load one measured Blender BVH fixture into the strict assembly model."""

    return TriangleMeshEvidence(
        object_id=object_id,
        snapshot=snapshot,
        bounds=AABB(
            minimum=tuple(payload["bounds"]["minimum"]),
            maximum=tuple(payload["bounds"]["maximum"]),
        ),
        vertices_m=[tuple(vertex) for vertex in payload["vertices_m"]],
        triangles=[tuple(triangle) for triangle in payload["triangles"]],
    )


@pytest.mark.skipif(
    os.getenv("CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE") != "1",
    reason="Set CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE=1 for Blender 5 evidence.",
)
def test_blender_scale_assembly_and_topology_evidence(tmp_path: Path) -> None:
    """Verify all missing AQ companion evidence in one isolated Blender invocation."""

    output = tmp_path / "reports" / "aq_blender_quality_smoke.json"
    run_blender(
        "probe_autonomous_quality.py",
        ["--output", str(output)],
        factory_startup=True,
        disable_autoexec=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["blender_version"].startswith("5.0")

    scale = payload["scale_shading"]
    assert scale["normalized_geometry_identical"] is True
    assert scale["evaluated_topology_identical"] is True
    assert scale["scale_relative_bevel_passed"] is True
    assert scale["shading_policy_passed"] is True
    assert [item["bevel_width_m"] for item in scale["fixtures"]] == pytest.approx(
        [0.002, 0.02, 0.2]
    )
    assert {tuple(item["normalized_dimensions"]) for item in scale["fixtures"]} == {
        (1.0, 1.0, 1.0)
    }

    contact = payload["assembly_bvh"]["contact"]
    penetration = payload["assembly_bvh"]["penetration"]
    assert contact["backend"] == penetration["backend"] == "blender_bvh"
    assert contact["classification"] == "contact"
    assert contact["minimum_distance_m"] == pytest.approx(0.0, abs=1.0e-7)
    assert contact["penetration_depth_m"] == pytest.approx(0.0)
    assert penetration["classification"] == "penetration"
    assert penetration["overlap_triangle_pair_count"] > 0
    assert penetration["penetration_depth_m"] == pytest.approx(0.25)

    digest = _sha256(output)
    snapshot = _assembly_artifact(
        "mesh_snapshot",
        "reports/aq_blender_quality_smoke.json",
        digest,
    )
    observation = BVHNarrowObservation(
        **{
            key: penetration[key]
            for key in (
                "subject_id",
                "reference_id",
                "status",
                "backend",
                "overlap_triangle_pair_count",
                "minimum_distance_m",
                "penetration_depth_m",
                "sampled_point_count",
                "bounded_sample_limit",
            )
        }
    )
    request = AssemblyCompanionRequest(
        request_id="aq-blender-bvh-request",
        provenance=AssemblyProvenance(
            job_id="aq_blender_smoke",
            workflow_id="wf-aq-blender-smoke",
            dispatch_id="dispatch-aq-blender-smoke",
            project_version="0.9.0",
            inputs=[
                _assembly_artifact("scene_spec", "analysis/scene_spec.json", SHA_A),
                _assembly_artifact("modeling_plan", "analysis/modeling_plan.json", SHA_B),
                _assembly_artifact("blend", "blender/scene.blend", digest),
            ],
        ),
        meshes=[
            _mesh_from_blender_payload(
                observation.subject_id,
                penetration["subject"],
                snapshot,
            ),
            _mesh_from_blender_payload(
                observation.reference_id,
                penetration["reference"],
                snapshot,
            ),
        ],
        semantic_relations=[
            SemanticAssemblyRelation(
                relation_id="fixture.penetration.contact",
                kind="required_contact",
                subject_id=observation.subject_id,
                reference_id=observation.reference_id,
                maximum_m=0.001,
            )
        ],
        narrow_observations=[observation],
    )
    assembly_report = build_assembly_companion_report(
        request,
        request_path="reports/aq_blender_quality_smoke.json",
        request_sha256=digest,
        report_id="aq-blender-assembly-report",
    )
    assert assembly_report.status == "failed"
    assert any(item.code == "MESH_PENETRATION" for item in assembly_report.findings)
    _write_contract(output.parent / "assembly_companion_report.json", assembly_report)

    topology_artifact = TopologyArtifact(
        role="topology_inventory",
        path="reports/aq_blender_quality_smoke.json",
        sha256=digest,
    )
    topology = payload["topology_uv"]
    passing = evaluate_topology_profile(
        report_id="aq-blender-topology-pass",
        provenance=_topology_provenance(),
        profile_name="game_ready_lowpoly",
        observations=_topology_observations(
            topology["passing_fixture"], topology_artifact
        ),
    )
    failing = evaluate_topology_profile(
        report_id="aq-blender-topology-fail",
        provenance=_topology_provenance(),
        profile_name="game_ready_lowpoly",
        observations=_topology_observations(
            topology["failing_fixture"], topology_artifact
        ),
    )
    assert passing.status == "passed"
    assert passing.ok is True
    assert failing.status == "failed"
    assert failing.ok is False
    overlap = next(item for item in failing.results if item.check == "uv_overlap")
    assert overlap.outcome == "hard_failure"
    assert int(overlap.measured_value) > 0
    _write_contract(output.parent / "topology_profile_pass.json", passing)
    _write_contract(output.parent / "topology_profile_fail.json", failing)
    assert tuple(PROFILE_NAMES) == (
        "static_prop_closed",
        "static_prop_open",
        "game_ready_lowpoly",
        "highpoly_bake_source",
        "modular_architecture",
        "terrain",
    )
