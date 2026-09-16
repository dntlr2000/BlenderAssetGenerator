"""Opt-in actual-Blender AQ revision vertical; fixture judgments are not art approval."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import test_autonomy_v2_candidate_validation_blender as geometry_smoke
from PIL import Image
from test_reference_fidelity_geometry_blender import _bound_fidelity_geometry_fixture

from codex_blender_modeler.autonomy_v2.approval_policy_service import (
    authorize_routine_gate,
    evaluate_routine_gate_eligibility,
)
from codex_blender_modeler.autonomy_v2.approval_supervisor_service import (
    _geometry_policy_snapshot,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryAuthoringCompletionV2,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _session_bundle,
    execute_autonomy_v2_controller,
)
from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    quality_source_fingerprint_v2,
    quality_submission_input_sha256_v2,
)
from codex_blender_modeler.autonomy_v2.execution_profile_service import (
    publish_execution_phase_profile,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialControllerCompletionV2,
)
from codex_blender_modeler.autonomy_v2.models import RootAuthorizationV2
from codex_blender_modeler.autonomy_v2.quality_revision_models import RevisionCostV01
from codex_blender_modeler.autonomy_v2.quality_revision_service import (
    begin_structural_reentry,
    fidelity_authoring_inputs,
    load_optional_loop,
    quality_revision_boundary,
    render_quality_evidence,
    submit_quality_attempt,
)
from codex_blender_modeler.autonomy_v2.supervisor_service import (
    QualitySubmissionV2,
    _controller_validation_boundary,
)
from codex_blender_modeler.blender_artifacts import sha256_file, write_json_atomic
from codex_blender_modeler.integrated_quality.v02_contour_metrics import (
    compare_contours_v02,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
    IntegratedQualityPolicyV02,
    MultiviewMetricV02,
    ProducerIdentityV02,
)
from codex_blender_modeler.integrated_quality.v02_service import (
    build_integrated_quality_report_v02,
)
from codex_blender_modeler.integrated_quality.v02_v06_bridge import (
    project_authoritative_v06_findings_v02,
)
from codex_blender_modeler.integrated_quality.v02_visibility_metrics import (
    compare_fixed_camera_visibility_v02,
)
from codex_blender_modeler.material_graph.models import (
    ChannelBinding,
    MaterialGraphArtifact,
    MaterialGraphProvenance,
    MaterialGraphSpec,
    PreviewLightingPolicy,
)
from codex_blender_modeler.materials.models import MaterialPlan, MaterialPlanItem
from codex_blender_modeler.production.controller_executor import FakeControllerForTests
from codex_blender_modeler.production.controller_executor.models import ControllerResult
from codex_blender_modeler.qa.models import VisualQAReport
from codex_blender_modeler.reference_fidelity.models import (
    FeatureAssessment,
    FidelityArtifact,
    FidelityComparisonV01,
    RenderEvidenceV01,
    VisualFindingSetV01,
)
from codex_blender_modeler.reference_fidelity.service import publish, read_artifact

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE") != "1",
    reason="set CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE=1 for AQ fidelity vertical",
)


def _json_bytes(value: object) -> bytes:
    """Serialize one deterministic controller fixture payload."""

    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    """Write one test-owned JSON artifact through the production atomic helper."""

    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)


def _artifact(root: Path, path: Path, *, artifact_id: str, kind: str):
    """Bind one existing vertical fixture file as exact AQ evidence."""

    return artifact_for_v2(root, path, artifact_id=artifact_id, kind=kind)


def _write_fixture_reference_mask(root: Path, reference_path: Path) -> None:
    """Publish an all-content observed mask for the synthetic solid-color reference."""

    with Image.open(reference_path):
        scene = json.loads((root / "analysis/scene_spec.json").read_text(encoding="utf-8"))
        mask = Image.new("L", tuple(scene["camera"]["resolution"]), 255)
    destination = root / "analysis/masks/reference_content.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    mask.save(destination)


def _material_plan(job_id: str, note: str) -> MaterialPlan:
    """Create one dependency-free material plan for the actual-Blender vertical."""

    return MaterialPlan(
        job_id=job_id,
        stage="authored",
        materials=[
            MaterialPlanItem(
                material_id="mat.body",
                label="Body",
                texture_strategy="none",
                confidence=0.9,
                notes=[note],
            )
        ],
        global_notes=[note],
    )


def _spatial_modeling(job_id: str, note: str) -> dict[str, object]:
    """Return the same one-part spatial contract used by the initial real build."""

    result = geometry_smoke._modeling_plan(job_id, note)
    result["assembly_consistency_policy"] = "spatial_v1"
    result["assembly_frame"] = {
        "root_object_id": "asset.hull",
        "longitudinal_axis": "Y",
        "lateral_axis": "X",
        "vertical_axis": "Z",
        "evidence_status": "inferred",
    }
    result["objects"][0]["assembly_role"] = "root"
    result["global_notes"] = [note]
    return result


def _run_material_round(root: Path, session_id: str) -> None:
    """Execute and host-promote one real material compile/rebuild round."""

    job_id = root.name
    root, session, plan, budget, state, _state_artifact = _session_bundle(job_id, session_id)
    baseline_path = root / "analysis/material_plan.json"
    if not baseline_path.exists():
        _write_json(baseline_path, _material_plan(job_id, "vertical baseline"))
    execution_id = f"exec-{state.sequence + 1:04d}-material_authoring"
    profile, profile_artifact = publish_execution_phase_profile(
        root,
        plan,
        profile_id="material_authoring",
        execution_id=execution_id,
    )
    assignment_path = session / "vertical_inputs" / execution_id / "assignment.json"
    _write_json(assignment_path, {"phase": "material_authoring", "fixture_only": True})
    assignment = _artifact(
        root,
        assignment_path,
        artifact_id=f"assignment-{execution_id}",
        kind="assignment",
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    inputs = [
        _artifact(
            root,
            root / "analysis/scene_spec.json",
            artifact_id=f"scene-{execution_id}",
            kind="scene",
        ),
        _artifact(
            root,
            baseline_path,
            artifact_id=f"material-baseline-{execution_id}",
            kind="material-baseline",
        ),
        _artifact(
            root,
            root / authorization.primary_reference.path,
            artifact_id=f"reference-{execution_id}",
            kind="reference",
        ),
    ]
    inputs = fidelity_authoring_inputs(root, plan, state, inputs)
    output_by_name = {Path(path).name: path for path in profile.allowed_output_paths}
    candidate = _material_plan(job_id, f"candidate {execution_id}")
    candidate_bytes = _json_bytes(candidate)
    scene_input, material_input, reference_input = inputs[:3]
    graph = MaterialGraphSpec(
        graph_id=f"graph-{state.sequence + 1:04d}",
        provenance=MaterialGraphProvenance(
            job_id=job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            project_version="0.9.0",
            inputs=[
                MaterialGraphArtifact(
                    role="material_plan",
                    path=output_by_name["material_plan.json"],
                    sha256=hashlib.sha256(candidate_bytes).hexdigest(),
                ),
                MaterialGraphArtifact(
                    role="scene_spec",
                    path=scene_input.path,
                    sha256=scene_input.sha256,
                ),
                MaterialGraphArtifact(
                    role="reference",
                    path=reference_input.path,
                    sha256=reference_input.sha256,
                ),
            ],
        ),
        material_id="mat.body",
        base_channels=[
            ChannelBinding(
                channel="base_color",
                source_kind="constant",
                color_space="sRGB",
                constant=(0.24, 0.42, 0.68, 1.0),
            ),
            ChannelBinding(
                channel="roughness",
                source_kind="constant",
                color_space="Non-Color",
                constant=0.48,
            ),
        ],
        preview_lighting=PreviewLightingPolicy(
            reference_source=MaterialGraphArtifact(
                role="reference",
                path=reference_input.path,
                sha256=reference_input.sha256,
            ),
            reference_confidence=0.2,
        ),
        assumptions=["Fixture color is not a reference-fidelity claim."],
    )
    graph_bytes = _json_bytes(graph)
    completion = MaterialControllerCompletionV2(
        completion_id=f"completion-{execution_id}",
        job_id=job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=session_id,
        execution_id=execution_id,
        assignment_sha256=assignment.sha256,
        tool_profile_sha256=profile_artifact.sha256,
        immutable_input_sha256={item.path: item.sha256 for item in inputs},
        source_scene_spec_sha256=scene_input.sha256,
        source_material_plan_sha256=material_input.sha256,
        material_plan_path=output_by_name["material_plan.json"],
        material_plan_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        material_graph_path=output_by_name["material_graph.json"],
        material_graph_sha256=hashlib.sha256(graph_bytes).hexdigest(),
    )
    result = execute_autonomy_v2_controller(
        job_id,
        session_id,
        phase_profile_id="material_authoring",
        assignment=assignment,
        immutable_inputs=inputs,
        controller=FakeControllerForTests(
            payloads={
                "material_plan.json": candidate_bytes,
                "material_graph.json": graph_bytes,
                "completion.json": _json_bytes(completion),
            }
        ),
        timeout_seconds=120,
    )
    assert result["result"]["status"] == "completed"
    root, session, plan, budget, state, _artifact_ref = _session_bundle(job_id, session_id)
    promoted = _controller_validation_boundary(
        root,
        session,
        plan,
        budget,
        state,
        authorization,
    )
    assert promoted["outcome"] == "material_candidate_validated"


def _run_structural_controller_round(
    root: Path, session_id: str, *, with_preflight: bool = False,
) -> None:
    """Promote an actual structural revision through legacy or explicit preflight inputs."""

    job_id = root.name
    root, session, plan, budget, state, _state_artifact = _session_bundle(job_id, session_id)
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    execution_id = f"exec-{state.sequence + 1:04d}-geometry_authoring"
    _profile, profile_artifact = publish_execution_phase_profile(
        root,
        plan,
        profile_id="geometry_authoring",
        execution_id=execution_id,
    )
    assignment_path = session / "vertical_inputs" / execution_id / "assignment.json"
    _write_json(assignment_path, {"phase": "structural_reentry", "fixture_only": True})
    assignment = _artifact(
        root,
        assignment_path,
        artifact_id=f"assignment-{execution_id}",
        kind="assignment",
    )
    immutable_inputs = [
        _artifact(
            root,
            root / authorization.primary_reference.path,
            artifact_id=f"reference-{execution_id}",
            kind="reference",
        ),
        _artifact(
            root,
            root / "analysis/reference_analysis.json",
            artifact_id=f"reference-analysis-{execution_id}",
            kind="reference",
        ),
        _artifact(
            root,
            root / "analysis/camera_solution.json",
            artifact_id=f"camera-{execution_id}",
            kind="camera",
        ),
        _artifact(
            root,
            root / "analysis/modeling_plan.json",
            artifact_id=f"baseline-{execution_id}",
            kind="baseline-scene",
        ),
        _artifact(
            root,
            root / "analysis/scene_spec.json",
            artifact_id=f"canonical-scene-{execution_id}",
            kind="baseline-scene",
        ),
        _artifact(
            root,
            root / "blender/scene.blend",
            artifact_id=f"canonical-blend-{execution_id}",
            kind="baseline-blend",
        ),
    ]
    scene = geometry_smoke._scene_v03(job_id, authorization.primary_reference.path)
    upper = scene["objects"][0]["geometry"]["sections"][1]["points"]
    scene["objects"][0]["geometry"]["sections"][1]["points"] = [
        [point[0] * 1.2, point[1] * 1.15, point[2] + 0.35] for point in upper
    ]
    scene["revision_notes"] = [
        "Fixture-only structural change bound to the diagnosed asset.hull target."
    ]
    modeling_bytes = _json_bytes(
        _spatial_modeling(job_id, "fixture-only bounded structural re-entry")
    )
    scene_bytes = _json_bytes(scene)
    if with_preflight:
        from codex_blender_modeler.autonomy_v2.geometry_preflight_service import (
            GEOMETRY_PREFLIGHT_KIND,
            preflight_aq_geometry_authoring,
        )
        from codex_blender_modeler.reference_fidelity.authoring import StructureAuthoringV01

        staging = root / "fidelity/preflight" / execution_id
        staging.mkdir(parents=True)
        (staging / "modeling_plan.json").write_bytes(modeling_bytes)
        (staging / "scene_spec_v03.json").write_bytes(scene_bytes)
        loop, _loop_ref = load_optional_loop(root, session_id)
        structure = StructureAuthoringV01.model_validate_json(json.dumps({
            "schema_version": "0.1.0", "hypothesis": loop.hypothesis.model_dump(),
            "scene": scene, "modeling_plan": json.loads(modeling_bytes),
            "representation_rationale": "Fixture section change tests the bounded transport path.",
        }))
        _write_json(staging / "structure.json", structure)
        preflight = preflight_aq_geometry_authoring(
            job_id, session_id,
            modeling_plan_path=(staging / "modeling_plan.json").relative_to(root),
            scene_spec_v03_path=(staging / "scene_spec_v03.json").relative_to(root),
            structure_authoring_path=(staging / "structure.json").relative_to(root),
        )
        assert preflight.outcome == "passed", preflight.issues
        _write_json(staging / "report.json", preflight)
        # No manually supplied canonical alias may hide a missing preflight dependency.
        immutable_inputs = [_artifact(
            root, staging / "report.json", artifact_id="structural-preflight",
            kind=GEOMETRY_PREFLIGHT_KIND,
        )]
    completion = GeometryAuthoringCompletionV2(
        job_id=job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=session_id,
        execution_id=execution_id,
        assignment_sha256=assignment.sha256,
        tool_profile_sha256=profile_artifact.sha256,
        outputs=[
            {
                "name": "modeling_plan.json",
                "sha256": hashlib.sha256(modeling_bytes).hexdigest(),
                "byte_size": len(modeling_bytes),
            },
            {
                "name": "scene_spec_v03.json",
                "sha256": hashlib.sha256(scene_bytes).hexdigest(),
                "byte_size": len(scene_bytes),
            },
        ],
    )
    controller_result = execute_autonomy_v2_controller(
        job_id,
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=immutable_inputs,
        controller=FakeControllerForTests(
            payloads={
                "modeling_plan.json": modeling_bytes,
                "scene_spec_v03.json": scene_bytes,
                "completion.json": _json_bytes(completion),
            }
        ),
        timeout_seconds=120,
    )
    assert controller_result["result"]["status"] == "completed"
    root, session, plan, budget, state, _state_artifact = _session_bundle(job_id, session_id)
    result_artifact = state.provenance[-1]
    result = ControllerResult.model_validate_json((root / result_artifact.path).read_bytes())
    canonical_before, canonical_kind = _geometry_policy_snapshot(root, job_id, session_id)
    eligibility = evaluate_routine_gate_eligibility(
        job_id,
        session_id,
        gate_kind="structural_candidate_promotion",
        exact_target_path=result_artifact.path,
        exact_target_kind="controller-result",
        current_canonical_snapshot_path=canonical_before,
        current_canonical_snapshot_kind=canonical_kind,
        dependency_paths=[
            result.request.path,
            result.tool_profile.path,
            *[item.path for item in result.outputs],
        ],
        dependency_kinds=[
            "controller-request",
            "controller-tool-profile",
            *["controller-output" for _item in result.outputs],
        ],
        allow_disabled_experimental=True,
    )
    assert eligibility["eligibility"] == "passed"
    issued = authorize_routine_gate(
        job_id,
        session_id,
        eligibility_report_path=str(eligibility["report_artifact"]["path"]),
        allow_disabled_experimental=True,
    )
    promoted = _controller_validation_boundary(
        root,
        session,
        plan,
        budget,
        state,
        authorization,
        policy_authorization_path=str(issued["authorization_artifact"]["path"]),
    )
    assert promoted["outcome"] == "geometry_candidate_validated"


def _quality_submission(
    root: Path,
    session_id: str,
    run_id: str,
    evidence: RenderEvidenceV01,
    *,
    candidate_blend_path: str = "blender/scene.blend",
    include_canonical_sources: bool = False,
) -> QualitySubmissionV2:
    """Build actual IQ with an explicitly selected canonical or immutable candidate Blend."""

    root, _session, plan, _budget, _state, _state_artifact = _session_bundle(
        root.name, session_id
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    iq_root = root / "fidelity/iq_inputs" / run_id
    camera_path = iq_root / "camera.json"
    scene = json.loads((root / "analysis/scene_spec.json").read_text(encoding="utf-8"))
    _write_json(
        camera_path,
        {
            "schema_version": "0.1.0",
            "camera": scene["camera"],
            "camera_fingerprint": evidence.camera_fingerprint,
            "fixture_only": True,
        },
    )
    camera = _artifact(root, camera_path, artifact_id=f"camera-{run_id}", kind="camera")
    reference_image = _artifact(
        root,
        root / authorization.primary_reference.path,
        artifact_id=f"reference-image-{run_id}",
        kind="reference_image",
    )
    aligned_reference_mask_path = iq_root / "reference_mask_aligned.png"
    with Image.open(root / "qa/runs" / run_id / "reference_mask.png") as source_mask:
        aligned_reference_mask = source_mask.convert("L").resize(
            evidence.resolution,
            Image.Resampling.NEAREST,
        )
    aligned_reference_mask.save(aligned_reference_mask_path)
    reference_mask = _artifact(
        root,
        aligned_reference_mask_path,
        artifact_id=f"reference-mask-{run_id}",
        kind="reference_mask",
    )
    candidate_mask = _artifact(
        root,
        root / evidence.passes["silhouette"].path,
        artifact_id=f"candidate-mask-{run_id}",
        kind="candidate_mask",
    )
    candidate_beauty = _artifact(
        root,
        root / evidence.passes["beauty"].path,
        artifact_id=f"candidate-beauty-{run_id}",
        kind="candidate_beauty",
    )
    v06 = _artifact(
        root,
        root / evidence.qa_report.path,
        artifact_id=f"visual-qa-{run_id}",
        kind="visual_qa_report",
    )
    quality_evidence = [
        camera,
        reference_image,
        reference_mask,
        candidate_mask,
        candidate_beauty,
        v06,
    ]
    contour_binding = ContourEvidenceBindingV02(
        evidence_id=reference_mask.artifact_id,
        origin="observed",
        authority="authoritative",
        artifact_path=reference_mask.path,
        artifact_sha256=reference_mask.sha256,
        camera_sha256=camera.sha256,
    )
    contour = compare_contours_v02(
        root / reference_mask.path,
        root / candidate_mask.path,
        reference_evidence=contour_binding,
        candidate_evidence_id=candidate_mask.artifact_id,
        candidate_artifact_sha256=candidate_mask.sha256,
        candidate_camera_sha256=camera.sha256,
    )
    visibility = compare_fixed_camera_visibility_v02(
        root / reference_image.path,
        root / candidate_beauty.path,
        root / reference_mask.path,
        root / candidate_mask.path,
        reference_image_sha256=reference_image.sha256,
        candidate_beauty_sha256=candidate_beauty.sha256,
        reference_mask_sha256=reference_mask.sha256,
        candidate_mask_sha256=candidate_mask.sha256,
        camera_sha256=camera.sha256,
        evidence_ids=[
            reference_image.artifact_id,
            candidate_beauty.artifact_id,
            reference_mask.artifact_id,
            candidate_mask.artifact_id,
        ],
    )
    source_fingerprint = quality_source_fingerprint_v2(root, root.name)
    quality_input = quality_submission_input_sha256_v2(
        source_fingerprint=source_fingerprint,
        camera_artifact=camera,
        quality_evidence=quality_evidence,
    )
    policy = IntegratedQualityPolicyV02.model_validate_json(
        (root / authorization.quality_profile.path).read_bytes()
    )
    v06_report = VisualQAReport.model_validate_json((root / v06.path).read_bytes())
    report = build_integrated_quality_report_v02(
        report_id=f"iq-{run_id}",
        job_id=root.name,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        source_fingerprint=source_fingerprint,
        camera_sha256=camera.sha256,
        input_sha256=quality_input,
        policy=policy,
        contour=contour,
        semantics=[],
        landmarks=[],
        multiview=MultiviewMetricV02(
            metric_id=f"multiview-{run_id}",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["Fixture vertical supplies one observed reference view."],
        ),
        fixed_camera_visibility=visibility,
        advisory_metrics=[],
        producer=ProducerIdentityV02(name="cbm_integrated_quality_v02", version="0.2.0"),
        created_at=datetime.now(UTC),
        legacy_v06_report_sha256=v06.sha256,
        legacy_v06_direct_score=v06_report.direct_metrics.overall_direct_score,
        additional_findings=project_authoritative_v06_findings_v02(
            v06_report,
            evidence_id=v06.artifact_id,
        ),
    )
    assert report.outcome != "passed"
    report_path = iq_root / "integrated_quality.json"
    _write_json(report_path, report)
    report_artifact = _artifact(
        root,
        report_path,
        artifact_id=report.report_id,
        kind="integrated_quality_report",
    )
    representative_path = iq_root / "representative.png"
    representative_path.parent.mkdir(parents=True, exist_ok=True)
    representative_path.write_bytes((root / evidence.passes["beauty"].path).read_bytes())
    canonical_sources = {}
    if include_canonical_sources:
        material_ref = next(
            item for item in reversed(_state.provenance) if item.kind == "material_phase_receipt"
        )
        material = json.loads((root / material_ref.path).read_bytes())
        for field, path in (
            ("scene_spec", "analysis/scene_spec.json"),
            ("authoring_blend", "blender/scene.blend"),
            ("material_plan", "analysis/material_plan.json"),
            ("build_provenance", material["build_provenance_snapshot"]["path"]),
        ):
            canonical_sources[field] = _artifact(
                root, root / path, artifact_id=f"{field.replace('_', '-')}-{run_id}", kind=field,
            )
    return QualitySubmissionV2(
        integrated_quality_report=report_artifact,
        quality_evidence=quality_evidence,
        camera_artifact=camera,
        candidate_blend=_artifact(
            root,
            root / candidate_blend_path,
            artifact_id=f"candidate-blend-{run_id}",
            kind="candidate_blend",
        ),
        representative_render=_artifact(
            root,
            representative_path,
            artifact_id=f"representative-{run_id}",
            kind="representative_render",
        ),
        **canonical_sources,
    )


def _submit_actual_quality_round(
    root: Path,
    session_id: str,
    *,
    run_id: str,
    outcome: str,
    candidate_blend_path: str = "blender/scene.blend",
    include_canonical_sources: bool = False,
) -> tuple[QualitySubmissionV2, FidelityArtifact]:
    """Render seven passes and bind fixture findings to the explicitly selected Blend source."""

    rendered = render_quality_evidence(root.name, session_id, run_id=run_id)
    evidence = RenderEvidenceV01.model_validate_json(
        json.dumps(rendered["render_evidence"])
    )
    loop, _loop_artifact = load_optional_loop(root, session_id)
    review = VisualFindingSetV01(
        job_id=root.name,
        review_id=f"review-{run_id}",
        hypothesis=loop.hypothesis,
        reference=FidelityArtifact(
            path=loop.hypothesis.path,
            sha256=loop.hypothesis.sha256,
        ),
        evidence=evidence,
        assessments=[
            FeatureAssessment(
                feature_id="form",
                outcome=outcome,
                actual=(
                    "Fixture diagnosis requests the bounded structural transport path."
                    if outcome == "defect"
                    else "Fixture diagnosis closes the transport path; this is not art review."
                ),
                confidence=0.9,
                evidence_passes=["beauty", "normal", "depth"],
                candidate_region=(0.1, 0.1, 0.9, 0.9),
            )
        ],
    )
    # Bind the true authorized reference, not the hypothesis JSON itself.
    hypothesis = json.loads(read_artifact(root, loop.hypothesis))
    review = review.model_copy(
        update={"reference": FidelityArtifact.model_validate(hypothesis["reference"])}
    )
    review_path = root / "fidelity/vertical_reviews" / f"{run_id}.json"
    publish(root, review_path, review)
    submission = _quality_submission(
        root, session_id, run_id, evidence, candidate_blend_path=candidate_blend_path,
        include_canonical_sources=include_canonical_sources,
    )
    submission_path = root / "fidelity/vertical_submissions" / f"{run_id}.json"
    publish(root, submission_path, submission)
    attempt = submit_quality_attempt(
        root.name,
        session_id,
        review_path=review_path.relative_to(root),
        quality_submission_path=submission_path.relative_to(root),
    )
    return submission, attempt


def test_actual_blender_revision_vertical_keeps_round_receipts_and_stops_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove real build/render re-entry mechanics without claiming reference quality."""

    root, session_id = _bound_fidelity_geometry_fixture(tmp_path, monkeypatch)
    reference_path = next((root / "input").glob("*"))
    reference_sha = sha256_file(reference_path)
    _write_fixture_reference_mask(root, reference_path)
    _run_material_round(root, session_id)
    _first_submission, first_attempt_ref = _submit_actual_quality_round(
        root,
        session_id,
        run_id="fidelity-vertical-00",
        outcome="defect",
    )
    root, _session, plan, _budget, state, _state_artifact = _session_bundle(
        root.name, session_id
    )
    first_boundary = quality_revision_boundary(root, plan, state)
    assert first_boundary is not None
    assert first_boundary["next_action"] == "structural_reentry"
    first_receipts = tuple(
        item.sha256 for item in state.provenance if item.kind.endswith("receipt")
    )
    begin_structural_reentry(
        root.name,
        session_id,
        strategy="section-loft",
        cost=RevisionCostV01(
            materializations=1,
            builds=2,
            qa_runs=1,
            closure_runs=1,
            promotions=2,
        ),
    )
    _run_structural_controller_round(root, session_id)
    _run_material_round(root, session_id)
    _second_submission, second_attempt_ref = _submit_actual_quality_round(
        root,
        session_id,
        run_id="fidelity-vertical-01",
        outcome="satisfied",
    )
    root, session, plan, _budget, state, _state_artifact = _session_bundle(
        root.name, session_id
    )
    second_boundary = quality_revision_boundary(root, plan, state)
    assert second_boundary is not None
    assert second_boundary["next_action"] == "review_required"
    assert "budget" in second_boundary["reason"].lower()
    assert first_attempt_ref != second_attempt_ref
    second_attempt = json.loads(read_artifact(root, second_attempt_ref))
    assert second_attempt["next_action"] == "structural_reentry"
    assert any(item.startswith("iq:") for item in second_attempt["unresolved_features"])
    comparison_ref = FidelityArtifact.model_validate(second_attempt["paired_comparison"])
    comparison = FidelityComparisonV01.model_validate_json(read_artifact(root, comparison_ref))
    assert comparison.outcome == "improved"
    current_receipts = tuple(
        item.sha256 for item in state.provenance if item.kind.endswith("receipt")
    )
    assert len(current_receipts) > len(first_receipts)
    assert current_receipts[-2:] != first_receipts[-2:]
    assert state.phase == "quality"
    assert state.status == "running"
    assert state.next_action == "run_integrated_quality"
    assert state.quality_terminal is None
    decisions = [
        json.loads(path.read_bytes())
        for path in sorted(
            (
                session
                / "approval_envelope"
                / "decisions"
            ).glob("*.json")
        )
    ]
    promotion_decisions = [
        item
        for item in decisions
        if item["gate_kind"]
        in {
            "geometry_candidate_promotion",
            "structural_candidate_promotion",
            "material_candidate_promotion",
        }
    ]
    assert {
        item["gate_kind"] for item in promotion_decisions
    } == {
        "geometry_candidate_promotion",
        "structural_candidate_promotion",
    }
    assert all(
        item["canonical_snapshot_after"]["path"] != "analysis/scene_spec.json"
        for item in promotion_decisions
    )
    assert sha256_file(reference_path) == reference_sha
    assert not list(root.rglob("*activation*receipt*.json"))


def test_funded_blender_round_prices_graph_compile_and_keeps_switch_reserve(tmp_path, monkeypatch):
    """Verify real funded receipts and retain a structural strategy reserve."""

    root, session_id = _bound_fidelity_geometry_fixture(tmp_path, monkeypatch, funded=True)
    reference_path = next((root / "input").glob("*"))
    original_reference = sha256_file(reference_path)
    _write_fixture_reference_mask(root, reference_path)
    _run_material_round(root, session_id)
    _submission, first_attempt = _submit_actual_quality_round(
        root, session_id, run_id="funded-vertical-00", outcome="defect",
    )
    _, _, plan, budget, state, _artifact = _session_bundle(root.name, session_id)
    assert state.budget_usage.total_blender_builds == 4  # 1 mesh + geometry + graph + rebuild
    loop, _loop_artifact = load_optional_loop(root, session_id)
    assert quality_revision_boundary(root, plan, state)["next_action"] == "structural_reentry"
    cost = RevisionCostV01(**loop.funding.route_cost("structural_reentry"))
    begin_structural_reentry(root.name, session_id, strategy="section-loft", cost=cost)
    _run_structural_controller_round(root, session_id)
    _run_material_round(root, session_id)
    _submission, second_attempt = _submit_actual_quality_round(
        root, session_id, run_id="funded-vertical-01", outcome="defect",
    )
    _, _, plan, budget, state, _artifact = _session_bundle(root.name, session_id)
    assert state.budget_usage.total_blender_builds == 8
    assert state.budget_usage.material_rounds == 2
    assert state.budget_usage.canonical_promotions == 4
    boundary = quality_revision_boundary(root, plan, state)
    assert boundary["next_action"] == "structural_reentry"
    assert budget.total_blender_builds - state.budget_usage.total_blender_builds == 12
    assert first_attempt != second_attempt
    assert sha256_file(reference_path) == original_reference
    assert state.source_freeze is None
