"""Bounded host supervisor for the disabled-by-default AQ 0.2 companion."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import native_io_path, sha256_file
from ..integrated_quality.v02_models import (
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
)
from ..optimization.models import OptimizationApproval, OptimizationPlan, OptimizationReview
from ..orchestration.models import WorkflowState
from ..production import (
    DelegatedProductionAdvanceReceipt,
    DelegatedProductionState,
    advance_delegated_production_controller,
    get_asset_production_dispatch_status,
)
from ..production.controller_executor import ControllerResult, PhaseToolProfile
from ..production.validation import ensure_contained_production_path
from .candidate_validation_service import validate_and_promote_geometry_candidate_v2
from .controller_bridge import _resume_pending_controller_locked, _session_bundle
from .delivery_executor import execute_approved_delivery_plan_v2
from .delivery_service import (
    artifact_for_v2,
    create_delivery_plan,
    prepare_v07_delivery_reviews,
    publish_delivery_terminal,
    publish_quality_source_freeze,
    quality_source_fingerprint_v2,
    quality_submission_input_sha256_v2,
    validate_delivery_terminal_v2,
    validate_host_recomputed_quality_report_v2,
    validate_quality_promotion_evidence_v2,
    validate_quality_source_freeze,
    validate_quality_source_inputs_v2,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .material_phase_service import validate_and_promote_material_controller_result_v2
from .models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    AutonomyStateV2,
    BudgetUsageV2,
    DeliveryPlan,
    DeliveryResult,
    DeliveryReviewBinding,
    DeliveryTerminalV2,
    QualityApprovedSourceFreeze,
    RootAuthorizationV2,
)
from .quality_terminal_service import (
    build_quality_review_bundle_v2,
    publish_quality_terminal_v2,
    validate_quality_review_bundle_v2,
    validate_quality_terminal_v2,
)
from .transitions import transition_state

ModelT = TypeVar("ModelT", bound=BaseModel)

_TERMINAL_STATUSES = {
    "review_required",
    "completed",
    "partial",
    "failed",
    "blocked",
    "cancelled",
}
_REFERENCE_READY_MILESTONES = {
    "analyzed",
    "proxy_ready",
    "geometry_approved",
    "interior_scope_waiting",
    "interior_scope_approved",
    "material_ready",
    "qa_review",
    "portable_ready",
    "delivered_for_review",
    "completed",
}


class _SupervisorStrictModel(BaseModel):
    """Reject undeclared or coerced public supervisor submission fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class QualitySubmissionV2(_SupervisorStrictModel):
    """Bind exact IQ, review, and source-freeze inputs supplied to one host action."""

    integrated_quality_report: AQV2Artifact
    quality_evidence: list[AQV2Artifact] = Field(min_length=1)
    camera_artifact: AQV2Artifact
    candidate_blend: AQV2Artifact | None = None
    representative_render: AQV2Artifact | None = None
    scene_spec: AQV2Artifact | None = None
    authoring_blend: AQV2Artifact | None = None
    build_provenance: AQV2Artifact | None = None
    material_plan: AQV2Artifact | None = None
    shader_recipes: list[AQV2Artifact] = Field(default_factory=list)
    texture_manifests: list[AQV2Artifact] = Field(default_factory=list)
    geometry_payloads: list[AQV2Artifact] = Field(default_factory=list)
    geometry_intent_survival: AQV2Artifact | None = None

    @model_validator(mode="after")
    def validate_unique_submission_paths(self) -> QualitySubmissionV2:
        """Reject duplicated evidence paths and require the declared fixed camera evidence."""

        artifacts = [
            self.integrated_quality_report,
            *self.quality_evidence,
            *([self.candidate_blend] if self.candidate_blend is not None else []),
            *([self.representative_render] if self.representative_render is not None else []),
            *([self.scene_spec] if self.scene_spec is not None else []),
            *([self.authoring_blend] if self.authoring_blend is not None else []),
            *([self.build_provenance] if self.build_provenance is not None else []),
            *([self.material_plan] if self.material_plan is not None else []),
            *self.shader_recipes,
            *self.texture_manifests,
            *self.geometry_payloads,
            *([self.geometry_intent_survival] if self.geometry_intent_survival is not None else []),
        ]
        paths = [item.path for item in artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("AQ v2 quality submission artifact paths must be unique")
        if self.camera_artifact not in self.quality_evidence:
            raise ValueError("AQ v2 quality submission must include its fixed camera evidence")
        return self


@dataclass(frozen=True)
class _ValidatedQualitySubmissionV2:
    """Carry host-recomputed IQ bindings into one side-effecting quality action."""

    report: IntegratedQualityReportV02
    quality_source_fingerprint: str
    quality_input_sha256: str
    geometry_candidate_validation_receipt: AQV2Artifact | None = None
    material_phase_receipt: AQV2Artifact | None = None


def _read_exact_model(
    root: Path,
    artifact: AQV2Artifact,
    model: type[ModelT],
) -> ModelT:
    """Rehash and strict-parse one AQ v2 or companion model artifact."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model.model_validate_json(handle.read())


def _normalize_quality_submission(
    value: QualitySubmissionV2 | dict[str, object] | None,
) -> QualitySubmissionV2 | None:
    """Strictly normalize an optional public quality submission without coercion."""

    if value is None or isinstance(value, QualitySubmissionV2):
        return value
    return QualitySubmissionV2.model_validate(value)


def _load_authorization(
    root: Path,
    plan: AutonomyPlanV2,
) -> RootAuthorizationV2:
    """Load and revalidate the session's exact root authorization and expiry."""

    authorization = _read_exact_model(root, plan.root_authorization, RootAuthorizationV2)
    if (
        authorization.job_id != plan.job_id
        or authorization.workflow_id != plan.workflow_id
        or authorization.dispatch_id != plan.dispatch_id
        or authorization.session_id != plan.session_id
    ):
        raise ValueError("AQ v2 root authorization identity does not match its plan")
    if authorization.status != "active":
        raise PermissionError("AQ v2 root authorization is not active")
    if authorization.expires_at is not None and authorization.expires_at <= datetime.now(UTC):
        raise PermissionError("AQ v2 root authorization has expired")
    return authorization


def _require_execution_opt_in(
    root: Path,
    plan: AutonomyPlanV2,
    *,
    allow_disabled_experimental: bool,
) -> AutonomyProfileV2:
    """Keep the unverified v2 profile disabled unless this call explicitly opts in."""

    profile = _read_exact_model(root, plan.profile, AutonomyProfileV2)
    if profile.profile_id != "autonomous_static_prop_v2":
        raise ValueError("AQ v2 plan is bound to an unexpected autonomy profile")
    if profile.status != "verified_active" and not allow_disabled_experimental:
        raise PermissionError("autonomous_static_prop_v2 is disabled_experimental")
    return profile


def _consume_action_budget(
    usage: BudgetUsageV2,
    budget: AutonomyBudgetV2,
    *,
    quality_evaluation: bool = False,
    delivery_runs: int = 0,
) -> BudgetUsageV2:
    """Reserve one bounded host action and any delivery attempts before side effects."""

    if isinstance(delivery_runs, bool) or not isinstance(delivery_runs, int):
        raise TypeError("AQ v2 delivery run usage must be an integer")
    if delivery_runs < 0:
        raise ValueError("AQ v2 delivery run usage cannot be negative")

    updated = usage.model_copy(
        update={
            "total_actions": usage.total_actions + 1,
            "total_quality_evaluations": (
                usage.total_quality_evaluations + int(quality_evaluation)
            ),
            "delivery_runs": usage.delivery_runs + delivery_runs,
        }
    )
    if updated.total_actions > budget.global_action_limit:
        raise PermissionError("AQ v2 global action budget is exhausted")
    if updated.total_quality_evaluations > budget.total_quality_evaluations:
        raise PermissionError("AQ v2 quality evaluation budget is exhausted")
    if updated.delivery_runs > budget.delivery_runs:
        raise PermissionError("AQ v2 delivery run budget is exhausted")
    return updated


def _write_next_state(
    root: Path,
    session_root: Path,
    state: AutonomyStateV2,
) -> AQV2Artifact:
    """Publish one immutable numbered state and return its exact artifact binding."""

    return write_immutable_v2_model(
        root,
        session_root / "states" / f"{state.sequence:04d}.json",
        state,
    )


def _production_state(
    plan: AutonomyPlanV2,
) -> DelegatedProductionState:
    """Reconstruct and identity-check the exact underlying V0.9 production state."""

    payload = get_asset_production_dispatch_status(plan.job_id, plan.dispatch_id)
    state_payload = payload.get("state")
    if not isinstance(state_payload, dict):
        raise ValueError("V0.9 production status returned no strict state")
    state = DelegatedProductionState.model_validate(state_payload)
    if (
        state.job_id != plan.job_id
        or state.workflow_id != plan.workflow_id
        or state.dispatch_id != plan.dispatch_id
    ):
        raise ValueError("AQ v2 plan identity differs from its V0.9 production state")
    return state


def _receipt_artifact(
    root: Path,
    plan: AutonomyPlanV2,
    receipt: DelegatedProductionAdvanceReceipt,
) -> AQV2Artifact:
    """Locate and bind one exact V0.9 advance receipt returned by the host service."""

    advances_root = ensure_contained_production_path(
        root,
        root / "production" / "dispatches" / plan.dispatch_id / "advances",
        must_exist=True,
    )
    matches = list(advances_root.glob(f"*-{receipt.receipt_id}.json"))
    if len(matches) != 1:
        raise ValueError("AQ v2 could not locate one exact V0.9 advance receipt")
    artifact = artifact_for_v2(
        root,
        matches[0],
        artifact_id=receipt.receipt_id,
        kind="production_advance_receipt",
    )
    parsed = _read_exact_model(root, artifact, DelegatedProductionAdvanceReceipt)
    if parsed != receipt:
        raise ValueError("V0.9 advance response differs from its immutable receipt")
    return artifact


def _validate_reference_receipt(
    root: Path,
    plan: AutonomyPlanV2,
    artifact: AQV2Artifact,
    production_state: DelegatedProductionState,
) -> DelegatedProductionAdvanceReceipt:
    """Revalidate the reference action receipt and its exact after-state anchor."""

    receipt = _read_exact_model(root, artifact, DelegatedProductionAdvanceReceipt)
    if (
        receipt.job_id != plan.job_id
        or receipt.workflow_id != plan.workflow_id
        or receipt.dispatch_id != plan.dispatch_id
        or receipt.controller_id != production_state.controller_id
        or receipt.dispatch_plan_sha256 != production_state.dispatch_plan_sha256
        or receipt.workflow_state_after_sha256 != production_state.workflow_state_sha256
    ):
        raise ValueError("AQ v2 reference receipt no longer matches production state")
    snapshot_path = ensure_contained_production_path(
        root,
        root / receipt.workflow_state_after.path,
        must_exist=True,
    )
    if (
        not os.path.isfile(native_io_path(snapshot_path))
        or sha256_file(snapshot_path) != receipt.workflow_state_after.sha256
        or receipt.workflow_state_after.sha256 != receipt.workflow_state_after_sha256
    ):
        raise ValueError("V0.9 reference after-state snapshot changed")
    with open(native_io_path(snapshot_path), "rb") as handle:
        workflow_state = WorkflowState.model_validate_json(handle.read())
    if (
        workflow_state.job_id != plan.job_id
        or workflow_state.workflow_id != plan.workflow_id
        or workflow_state.milestone not in _REFERENCE_READY_MILESTONES
    ):
        raise ValueError("V0.9 reference receipt does not prove analyzed reference evidence")
    return receipt


def _reference_receipt_from_state(state: AutonomyStateV2) -> AQV2Artifact | None:
    """Select the single reference-production receipt accumulated in AQ provenance."""

    matches = [item for item in state.provenance if item.kind == "production_advance_receipt"]
    if len(matches) > 1:
        raise ValueError("AQ v2 state contains multiple reference-production receipts")
    return matches[0] if matches else None


def _validate_production_anchor(
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
) -> DelegatedProductionState:
    """Reject downstream work if the underlying production state changed unexpectedly."""

    production_state = _production_state(plan)
    reference_receipt = _reference_receipt_from_state(state)
    if state.sequence > 0 and reference_receipt is None:
        raise ValueError("advanced AQ v2 state lacks its production reference receipt")
    if reference_receipt is not None:
        _validate_reference_receipt(root, plan, reference_receipt, production_state)
    return production_state


def _recover_reference_receipt(
    root: Path,
    plan: AutonomyPlanV2,
    production_state: DelegatedProductionState,
) -> AQV2Artifact | None:
    """Recover only the first exact host receipt after an interrupted reference action."""

    advances_root = root / "production" / "dispatches" / plan.dispatch_id / "advances"
    if not advances_root.is_dir():
        return None
    paths = sorted(advances_root.glob("*.json"))
    if len(paths) != 1:
        if paths:
            raise ValueError(
                "AQ v2 reference recovery found unexpected additional production actions"
            )
        return None
    candidate = artifact_for_v2(
        root,
        paths[0],
        artifact_id="recovered-reference-receipt",
        kind="production_advance_receipt",
    )
    receipt = _read_exact_model(root, candidate, DelegatedProductionAdvanceReceipt)
    candidate = candidate.model_copy(update={"artifact_id": receipt.receipt_id})
    _validate_reference_receipt(root, plan, candidate, production_state)
    return candidate


def _advance_reference_action(
    *,
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
) -> dict[str, object]:
    """Run or recover exactly one V0.9 reference-analysis host action."""

    before = _production_state(plan)
    recovered = _recover_reference_receipt(root, plan, before)
    if recovered is not None:
        receipt_artifact = recovered
        receipt = _read_exact_model(root, receipt_artifact, DelegatedProductionAdvanceReceipt)
        after = before
        recovered_action = True
    else:
        if before.milestone != "created" or before.next_action != "resume_host":
            return {
                "advanced": False,
                "outcome": "waiting_for_production_boundary",
                "next_action": before.next_action,
                "production_state": before.model_dump(mode="json"),
                "state": state.model_dump(mode="json"),
            }
        result = advance_delegated_production_controller(
            plan.job_id,
            plan.dispatch_id,
            before.controller_id,
            max_host_steps=1,
        )
        state_payload = result.get("state")
        receipt_payload = result.get("advance_receipt")
        if not isinstance(state_payload, dict) or not isinstance(receipt_payload, dict):
            raise ValueError("V0.9 production advance returned incomplete exact evidence")
        after = DelegatedProductionState.model_validate(state_payload)
        receipt = DelegatedProductionAdvanceReceipt.model_validate(receipt_payload)
        receipt_artifact = _receipt_artifact(root, plan, receipt)
        observed = _production_state(plan)
        if observed.model_dump(mode="json", exclude={"observed_at"}) != after.model_dump(
            mode="json", exclude={"observed_at"}
        ):
            raise ValueError("V0.9 production state changed after its advance receipt")
        _validate_reference_receipt(root, plan, receipt_artifact, observed)
        recovered_action = False
    if after.milestone not in _REFERENCE_READY_MILESTONES:
        return {
            "advanced": False,
            "outcome": "waiting_for_reference_analysis",
            "next_action": after.next_action,
            "production_state": after.model_dump(mode="json"),
            "production_receipt": receipt.model_dump(mode="json"),
            "state": state.model_dump(mode="json"),
        }
    usage = _consume_action_budget(state.budget_usage, budget)
    next_state = transition_state(
        state,
        event="reference_ready",
        evidence=receipt_artifact,
        created_at=datetime.now(UTC),
        budget_usage=usage,
    )
    state_artifact = _write_next_state(root, session_root, next_state)
    return {
        "advanced": True,
        "outcome": "reference_ready",
        "recovered_action": recovered_action,
        "production_state": after.model_dump(mode="json"),
        "production_receipt": receipt.model_dump(mode="json"),
        "state": next_state.model_dump(mode="json"),
        "state_artifact": state_artifact.model_dump(mode="json"),
    }


def _controller_validation_boundary(
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
    authorization: RootAuthorizationV2,
) -> dict[str, object]:
    """Run the strict host validator selected by the exact authoring phase profile."""

    matches = [item for item in state.provenance if item.path.endswith("/result.json")]
    if not matches or state.provenance[-1] != matches[-1]:
        raise ValueError("AQ v2 candidate boundary requires a current controller result")
    result_artifact = matches[-1]
    result = _read_exact_model(root, result_artifact, ControllerResult)
    if result.status != "completed":
        raise ValueError("AQ v2 candidate boundary requires a completed controller result")
    profile_artifact = artifact_for_v2(
        root,
        root / result.tool_profile.path,
        artifact_id=result.tool_profile.artifact_id,
        kind="controller_phase_tool_profile",
    )
    if (
        profile_artifact.path,
        profile_artifact.sha256,
        profile_artifact.byte_size,
    ) != (
        result.tool_profile.path,
        result.tool_profile.sha256,
        result.tool_profile.byte_size,
    ):
        raise ValueError("AQ v2 controller phase profile changed after execution")
    profile = _read_exact_model(root, profile_artifact, PhaseToolProfile)
    if profile.profile_id == "geometry_authoring":
        receipt, evidence = validate_and_promote_geometry_candidate_v2(
            job_root=root,
            session_root=session_root,
            plan=plan,
            budget=budget,
            state=state,
            authorization=authorization,
        )
        event = "candidate_validated"
        outcome = "geometry_candidate_validated"
    elif profile.profile_id == "material_authoring":
        from .codex_image_material_loop_service import (
            validate_codex_image_material_controller_promotion_boundary,
        )

        loop_profile_authorized = validate_codex_image_material_controller_promotion_boundary(
            root,
            session_root,
            plan,
            state,
            result_artifact,
        )
        receipt, evidence = validate_and_promote_material_controller_result_v2(
            root,
            plan,
            budget,
            state,
            result_artifact,
            authorized_profile_artifact=(
                profile_artifact if loop_profile_authorized else None
            ),
        )
        event = "material_candidate_validated"
        outcome = "material_candidate_validated"
    else:
        raise PermissionError(
            "AQ v2 candidate boundary accepts only geometry or material authoring"
        )
    next_state = transition_state(
        state,
        event=event,
        evidence=evidence,
        created_at=datetime.now(UTC),
        budget_usage=receipt.budget_usage_after,
    )
    state_artifact = _write_next_state(root, session_root, next_state)
    return {
        "advanced": True,
        "outcome": outcome,
        "candidate_receipt": evidence.model_dump(mode="json"),
        "state": next_state.model_dump(mode="json"),
        "state_artifact": state_artifact.model_dump(mode="json"),
    }


def _report_named_evidence_hashes(report: IntegratedQualityReportV02) -> set[str]:
    """Collect every exact file hash named by an IQ 0.2 report, including its camera."""

    hashes = {report.camera_sha256}
    if report.legacy_v06_report_sha256 is not None:
        hashes.add(report.legacy_v06_report_sha256)
    for value in (report.contour.reference_mask_sha256, report.contour.candidate_mask_sha256):
        if value is not None:
            hashes.add(value)
    for semantic in report.semantics:
        for value in (
            semantic.reference_evidence.artifact_sha256,
            semantic.reference_evidence.registration_receipt_sha256,
            semantic.contour.reference_mask_sha256,
            semantic.contour.candidate_mask_sha256,
        ):
            if value is not None:
                hashes.add(value)
    for landmark in report.landmarks:
        for value in (landmark.source_artifact_sha256, landmark.candidate_artifact_sha256):
            if value is not None:
                hashes.add(value)
    for observation in report.multiview.observations:
        if observation.artifact_sha256 is not None:
            hashes.add(observation.artifact_sha256)
    for metric in report.advisory_metrics:
        if metric.artifact_sha256 is not None:
            hashes.add(metric.artifact_sha256)
    return hashes


def _quality_phase_receipts(
    state: AutonomyStateV2,
) -> tuple[AQV2Artifact, AQV2Artifact]:
    """Select the single accepted geometry receipt and current material receipt from state."""

    geometry = [
        item for item in state.provenance if item.kind == "geometry_candidate_validation_receipt"
    ]
    material = [item for item in state.provenance if item.kind == "material_phase_receipt"]
    if len(geometry) != 1 or len(material) != 1:
        raise ValueError(
            "passed IQ 0.2 requires one accepted geometry receipt and one material receipt"
        )
    geometry_index = state.provenance.index(geometry[0])
    material_index = state.provenance.index(material[0])
    if geometry_index >= material_index or state.provenance[-1] != material[0]:
        raise ValueError("AQ v2 promotion receipts are stale or out of phase order")
    return geometry[0], material[0]


def _validate_quality_submission(
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    authorization: RootAuthorizationV2,
    submission: QualitySubmissionV2,
) -> _ValidatedQualitySubmissionV2:
    """Rehash every submission file and bind IQ policy, identity, camera, and evidence."""

    artifacts = [
        submission.integrated_quality_report,
        *submission.quality_evidence,
        *([submission.candidate_blend] if submission.candidate_blend is not None else []),
        *(
            [submission.representative_render]
            if submission.representative_render is not None
            else []
        ),
        *([submission.scene_spec] if submission.scene_spec is not None else []),
        *([submission.authoring_blend] if submission.authoring_blend is not None else []),
        *([submission.build_provenance] if submission.build_provenance is not None else []),
        *([submission.material_plan] if submission.material_plan is not None else []),
        *submission.shader_recipes,
        *submission.texture_manifests,
        *submission.geometry_payloads,
        *(
            [submission.geometry_intent_survival]
            if submission.geometry_intent_survival is not None
            else []
        ),
    ]
    for artifact in artifacts:
        validate_v2_artifact(root, artifact)
    report = _read_exact_model(
        root,
        submission.integrated_quality_report,
        IntegratedQualityReportV02,
    )
    if (
        report.job_id != plan.job_id
        or report.workflow_id != plan.workflow_id
        or report.dispatch_id != plan.dispatch_id
        or report.camera_sha256 != submission.camera_artifact.sha256
    ):
        raise ValueError("IQ 0.2 report identity or camera differs from the AQ v2 plan")
    policy = _read_exact_model(root, authorization.quality_profile, IntegratedQualityPolicyV02)
    validate_host_recomputed_quality_report_v2(
        job_root=root,
        report=report,
        quality_evidence=submission.quality_evidence,
        camera_artifact=submission.camera_artifact,
        expected_policy=policy,
    )
    evidence_hashes = {item.sha256 for item in submission.quality_evidence}
    missing = _report_named_evidence_hashes(report) - evidence_hashes
    if missing:
        raise ValueError("IQ 0.2 report names evidence outside the exact submission")
    quality_source_fingerprint = quality_source_fingerprint_v2(root, plan.job_id)
    geometry_receipt: AQV2Artifact | None = None
    material_receipt: AQV2Artifact | None = None
    if report.outcome == "passed":
        scene, blend, build, material, survival = _required_freeze_artifacts(submission)
        geometry_receipt, material_receipt = _quality_phase_receipts(state)
        validate_quality_promotion_evidence_v2(
            job_root=root,
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            geometry_candidate_validation_receipt=geometry_receipt,
            material_phase_receipt=material_receipt,
            geometry_intent_survival=survival,
            scene_spec=scene,
            authoring_blend=blend,
            build_provenance=build,
            material_plan=material,
        )
        canonical_fingerprint = validate_quality_source_inputs_v2(
            job_root=root,
            job_id=plan.job_id,
            scene_spec=scene,
            authoring_blend=blend,
            build_provenance=build,
            material_plan=material,
            shader_recipes=submission.shader_recipes,
            texture_manifests=submission.texture_manifests,
            geometry_payloads=submission.geometry_payloads,
        )
        if canonical_fingerprint != quality_source_fingerprint:
            raise ValueError("canonical source changed during IQ 0.2 submission validation")
        quality_input_sha256 = quality_submission_input_sha256_v2(
            source_fingerprint=quality_source_fingerprint,
            camera_artifact=submission.camera_artifact,
            quality_evidence=submission.quality_evidence,
            scene_spec=scene,
            authoring_blend=blend,
            build_provenance=build,
            material_plan=material,
            shader_recipes=submission.shader_recipes,
            texture_manifests=submission.texture_manifests,
            geometry_payloads=submission.geometry_payloads,
            geometry_intent_survival=survival,
            geometry_candidate_validation_receipt=geometry_receipt,
            material_phase_receipt=material_receipt,
        )
    else:
        quality_input_sha256 = quality_submission_input_sha256_v2(
            source_fingerprint=quality_source_fingerprint,
            camera_artifact=submission.camera_artifact,
            quality_evidence=submission.quality_evidence,
        )
    if (
        report.source_fingerprint != quality_source_fingerprint
        or report.input_sha256 != quality_input_sha256
    ):
        raise ValueError("IQ 0.2 report is stale for the exact canonical submission")
    return _ValidatedQualitySubmissionV2(
        report=report,
        quality_source_fingerprint=quality_source_fingerprint,
        quality_input_sha256=quality_input_sha256,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
    )


def _required_freeze_artifacts(
    submission: QualitySubmissionV2,
) -> tuple[AQV2Artifact, AQV2Artifact, AQV2Artifact, AQV2Artifact, AQV2Artifact]:
    """Return all mandatory passed-quality freeze artifacts or fail before publication."""

    values = (
        submission.scene_spec,
        submission.authoring_blend,
        submission.build_provenance,
        submission.material_plan,
        submission.geometry_intent_survival,
    )
    if any(item is None for item in values):
        raise ValueError(
            "passed IQ 0.2 submission requires scene, blend, build, material, and "
            "geometry-survival artifacts"
        )
    return cast(
        tuple[AQV2Artifact, AQV2Artifact, AQV2Artifact, AQV2Artifact, AQV2Artifact],
        values,
    )


def _adopt_or_publish_source_freeze(
    *,
    root: Path,
    plan: AutonomyPlanV2,
    validated_submission: _ValidatedQualitySubmissionV2,
    submission: QualitySubmissionV2,
) -> AQV2Artifact:
    """Recover an exact source freeze or publish it once from passed IQ evidence."""

    scene, blend, build, material, survival = _required_freeze_artifacts(submission)
    geometry_receipt = validated_submission.geometry_candidate_validation_receipt
    material_receipt = validated_submission.material_phase_receipt
    if geometry_receipt is None or material_receipt is None:
        raise ValueError("passed IQ 0.2 validation omitted exact promotion receipts")
    path = root / "production" / "autonomy_v2" / plan.session_id / "source_freeze.json"
    if path.exists():
        artifact = artifact_for_v2(
            root,
            path,
            artifact_id=f"quality-freeze-{plan.session_id}",
            kind="source-freeze",
        )
        freeze = _read_exact_model(root, artifact, QualityApprovedSourceFreeze)
        if (
            freeze.scene_spec != scene
            or freeze.authoring_blend != blend
            or freeze.build_provenance != build
            or freeze.integrated_quality_report != submission.integrated_quality_report
            or freeze.quality_evidence != submission.quality_evidence
            or freeze.material_plan != material
            or freeze.shader_recipes != submission.shader_recipes
            or freeze.texture_manifests != submission.texture_manifests
            or freeze.geometry_payloads != submission.geometry_payloads
            or freeze.geometry_intent_survival != survival
            or freeze.geometry_candidate_validation_receipt != geometry_receipt
            or freeze.material_phase_receipt != material_receipt
        ):
            raise ValueError("existing AQ v2 source freeze differs from this action")
        validate_quality_source_freeze(root, freeze)
        validate_quality_promotion_evidence_v2(
            job_root=root,
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            geometry_candidate_validation_receipt=geometry_receipt,
            material_phase_receipt=material_receipt,
            geometry_intent_survival=survival,
            scene_spec=scene,
            authoring_blend=blend,
            build_provenance=build,
            material_plan=material,
        )
        current_source = validate_quality_source_inputs_v2(
            job_root=root,
            job_id=plan.job_id,
            scene_spec=scene,
            authoring_blend=blend,
            build_provenance=build,
            material_plan=material,
            shader_recipes=submission.shader_recipes,
            texture_manifests=submission.texture_manifests,
            geometry_payloads=submission.geometry_payloads,
        )
        if current_source != validated_submission.quality_source_fingerprint:
            raise ValueError("canonical source changed before source-freeze recovery")
        return artifact
    _freeze, artifact = publish_quality_source_freeze(
        job_root=root,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        integrated_quality_report=submission.integrated_quality_report,
        quality_evidence=submission.quality_evidence,
        scene_spec=scene,
        authoring_blend=blend,
        build_provenance=build,
        material_plan=material,
        shader_recipes=submission.shader_recipes,
        texture_manifests=submission.texture_manifests,
        geometry_payloads=submission.geometry_payloads,
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
        camera_artifact=submission.camera_artifact,
    )
    return artifact


def _adopt_or_build_review_bundle(
    *,
    root: Path,
    plan: AutonomyPlanV2,
    submission: QualitySubmissionV2,
) -> AQV2Artifact:
    """Recover or publish the deterministic non-production IQ review bundle."""

    if submission.candidate_blend is None or submission.representative_render is None:
        raise ValueError(
            "non-passing IQ 0.2 submission requires candidate blend and representative render"
        )
    path = root / "production" / "autonomy_v2" / plan.session_id / "quality_review_bundle.json"
    if path.exists():
        artifact = artifact_for_v2(
            root,
            path,
            artifact_id=f"quality-review-{plan.session_id}",
            kind="quality-review-bundle",
        )
        bundle = validate_quality_review_bundle_v2(root, artifact)
        if (
            bundle.integrated_quality_report != submission.integrated_quality_report
            or bundle.candidate_blend != submission.candidate_blend
            or bundle.representative_render != submission.representative_render
        ):
            raise ValueError("existing AQ v2 review bundle differs from this action")
        return artifact
    _bundle, artifact = build_quality_review_bundle_v2(
        job_root=root,
        session_id=plan.session_id,
        integrated_quality_report=submission.integrated_quality_report,
        candidate_blend=submission.candidate_blend,
        representative_render=submission.representative_render,
    )
    return artifact


def _quality_reason(outcome: str) -> str:
    """Return the stable host explanation for one IQ terminal branch."""

    reasons = {
        "passed": "Exact IQ 0.2 hard gates passed and the canonical source was frozen.",
        "needs_revision": "Exact IQ 0.2 requires another authoring review.",
        "unscorable": "Required IQ 0.2 evidence is unscorable and needs manual review.",
        "blocked": "A required IQ 0.2 hard gate blocked production readiness.",
    }
    return reasons[outcome]


def _adopt_or_publish_quality_terminal(
    *,
    root: Path,
    plan: AutonomyPlanV2,
    submission: QualitySubmissionV2,
    status: Literal["quality_approved", "review_required", "blocked"],
    reason: str,
    source_freeze: AQV2Artifact | None = None,
    review_bundle: AQV2Artifact | None = None,
) -> AQV2Artifact:
    """Recover or publish one exact branch-specific quality terminal."""

    path = root / "production" / "autonomy_v2" / plan.session_id / "quality_terminal.json"
    if path.exists():
        artifact = artifact_for_v2(
            root,
            path,
            artifact_id=f"quality-terminal-{plan.session_id}",
            kind="quality-terminal",
        )
        terminal = validate_quality_terminal_v2(root, artifact)
        if (
            terminal.status != status
            or terminal.integrated_quality_report != submission.integrated_quality_report
            or terminal.source_freeze != source_freeze
            or terminal.review_bundle != review_bundle
            or terminal.reason != reason
        ):
            raise ValueError("existing AQ v2 quality terminal differs from this action")
        return artifact
    _terminal, artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id=plan.session_id,
        status=status,
        integrated_quality_report=submission.integrated_quality_report,
        source_freeze=source_freeze,
        review_bundle=review_bundle,
        reason=reason,
    )
    return artifact


def _advance_quality_action(
    *,
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
    authorization: RootAuthorizationV2,
    submission: QualitySubmissionV2 | None,
) -> dict[str, object]:
    """Publish one strict IQ terminal and transition only from its exact artifact."""

    if submission is None:
        return {
            "advanced": False,
            "outcome": "waiting_for_integrated_quality_submission",
            "next_action": "run_integrated_quality",
            "required_contract": "QualitySubmissionV2",
            "state": state.model_dump(mode="json"),
        }
    _validate_optional_codex_image_material_companion(
        root=root,
        session_root=session_root,
        state=state,
        submission=submission,
    )
    validated_submission = _validate_quality_submission(
        root,
        plan,
        state,
        authorization,
        submission,
    )
    report = validated_submission.report
    usage = _consume_action_budget(
        state.budget_usage,
        budget,
        quality_evaluation=True,
    )
    reason = _quality_reason(report.outcome)
    source_freeze: AQV2Artifact | None = None
    review_bundle: AQV2Artifact | None = None
    if report.outcome == "passed":
        source_freeze = _adopt_or_publish_source_freeze(
            root=root,
            plan=plan,
            validated_submission=validated_submission,
            submission=submission,
        )
        terminal_artifact = _adopt_or_publish_quality_terminal(
            root=root,
            plan=plan,
            submission=submission,
            status="quality_approved",
            reason=reason,
            source_freeze=source_freeze,
        )
        event = "quality_passed"
    elif report.outcome in {"needs_revision", "unscorable"}:
        review_bundle = _adopt_or_build_review_bundle(
            root=root,
            plan=plan,
            submission=submission,
        )
        terminal_artifact = _adopt_or_publish_quality_terminal(
            root=root,
            plan=plan,
            submission=submission,
            status="review_required",
            reason=reason,
            review_bundle=review_bundle,
        )
        event = "quality_nonpassing"
    else:
        terminal_artifact = _adopt_or_publish_quality_terminal(
            root=root,
            plan=plan,
            submission=submission,
            status="blocked",
            reason=reason,
        )
        event = "blocked"
    next_state = transition_state(
        state,
        event=cast(Any, event),
        evidence=terminal_artifact,
        created_at=datetime.now(UTC),
        source_freeze=source_freeze,
        quality_terminal=terminal_artifact,
        budget_usage=usage,
        reason=reason,
    )
    state_artifact = _write_next_state(root, session_root, next_state)
    result: dict[str, object] = {
        "advanced": True,
        "outcome": report.outcome,
        "quality_terminal": terminal_artifact.model_dump(mode="json"),
        "source_freeze": (
            source_freeze.model_dump(mode="json") if source_freeze is not None else None
        ),
        "review_bundle": (
            review_bundle.model_dump(mode="json") if review_bundle is not None else None
        ),
        "state": next_state.model_dump(mode="json"),
        "state_artifact": state_artifact.model_dump(mode="json"),
    }
    companion = _record_optional_codex_image_material_quality_result(
        root=root,
        session_root=session_root,
        submission=submission,
        supervisor_result=result,
    )
    if companion is not None:
        result["codex_image_material_loop"] = companion
    return result


def _validate_optional_codex_image_material_companion(
    *,
    root: Path,
    session_root: Path,
    state: AutonomyStateV2,
    submission: QualitySubmissionV2,
) -> None:
    """Require the exact companion promotion chain when this AQ session has one."""

    loop_root = session_root / "codex_image_material_loop"
    bridge_path = loop_root / "bridge_plan.json"
    if not os.path.exists(native_io_path(bridge_path)):
        return
    promotion_path = loop_root / "promotion_receipt.json"
    if not os.path.exists(native_io_path(promotion_path)):
        raise PermissionError("ImageGen material loop has no completed promotion receipt")
    from ..codex_imagegen.artifacts import artifact_for_codex_image
    from .codex_image_material_quality_service import (
        validate_codex_image_material_quality_boundary,
    )

    promotion_artifact = artifact_for_codex_image(
        root,
        promotion_path,
        artifact_id=f"image-material-promotion-{state.session_id}",
        kind="material-promotion-receipt",
        media_type="application/json",
    )
    validate_codex_image_material_quality_boundary(
        root,
        session_id=state.session_id,
        promotion_receipt_artifact=promotion_artifact,
        quality_submission=submission,
        state=state,
    )


def _record_optional_codex_image_material_quality_result(
    *,
    root: Path,
    session_root: Path,
    submission: QualitySubmissionV2,
    supervisor_result: dict[str, object],
) -> dict[str, object] | None:
    """Append the ImageGen companion quality state while the AQ session lock is held."""

    loop_root = session_root / "codex_image_material_loop"
    bridge_path = loop_root / "bridge_plan.json"
    if not os.path.exists(native_io_path(bridge_path)):
        return None
    promotion_path = loop_root / "promotion_receipt.json"
    if not os.path.exists(native_io_path(promotion_path)):
        raise PermissionError("ImageGen material loop has no completed promotion receipt")
    from ..codex_imagegen.artifacts import artifact_for_codex_image
    from .codex_image_material_loop_service import (
        record_codex_image_material_loop_quality_result_locked,
    )

    promotion_artifact = artifact_for_codex_image(
        root,
        promotion_path,
        artifact_id=f"image-material-promotion-{session_root.name}",
        kind="material-promotion-receipt",
        media_type="application/json",
    )
    return record_codex_image_material_loop_quality_result_locked(
        root,
        session_root.name,
        promotion_receipt_artifact=promotion_artifact,
        quality_submission=submission,
        supervisor_result=supervisor_result,
    )


def _recover_optional_codex_image_material_quality_result(
    *,
    root: Path,
    session_root: Path,
    state: AutonomyStateV2,
    state_artifact: AQV2Artifact,
    submission: QualitySubmissionV2 | None,
) -> dict[str, object] | None:
    """Recover a companion terminal after the base AQ quality transition was published."""

    if state.quality_terminal is None or submission is None:
        return None
    report = cast(
        IntegratedQualityReportV02,
        _read_exact_model(root, submission.integrated_quality_report, IntegratedQualityReportV02),
    )
    return _record_optional_codex_image_material_quality_result(
        root=root,
        session_root=session_root,
        submission=submission,
        supervisor_result={
            "advanced": False,
            "outcome": report.outcome,
            "quality_terminal": state.quality_terminal.model_dump(mode="json"),
            "state": state.model_dump(mode="json"),
            "state_artifact": state_artifact.model_dump(mode="json"),
        },
    )


def _codex_image_material_quality_recovery_required(
    *, session_root: Path, state: AutonomyStateV2
) -> bool:
    """Detect a base quality transition whose companion terminal is still unpublished."""

    loop_root = session_root / "codex_image_material_loop"
    return (
        state.quality_terminal is not None
        and os.path.exists(native_io_path(loop_root / "bridge_plan.json"))
        and not os.path.exists(native_io_path(loop_root / "terminal.json"))
    )


def _validate_optional_codex_image_material_terminal(
    *, root: Path, session_root: Path
) -> None:
    """Require the recursively valid companion terminal before any delivery mutation."""

    loop_root = session_root / "codex_image_material_loop"
    if not os.path.exists(native_io_path(loop_root / "bridge_plan.json")):
        return
    terminal_path = loop_root / "terminal.json"
    if not os.path.exists(native_io_path(terminal_path)):
        raise PermissionError("ImageGen material loop quality terminal is not published")
    from ..codex_imagegen.artifacts import artifact_for_codex_image
    from .codex_image_material_loop_service import (
        validate_codex_image_material_loop_terminal,
    )

    terminal_artifact = artifact_for_codex_image(
        root,
        terminal_path,
        artifact_id=f"material-loop-terminal-{session_root.name}",
        kind="material-loop-terminal",
        media_type="application/json",
    )
    validate_codex_image_material_loop_terminal(
        root,
        terminal_artifact,
        require_current=True,
    )


def _validate_delivery_plan(
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    artifact: AQV2Artifact,
) -> DeliveryPlan:
    """Recompute the immutable delivery plan's authorization, source, and profiles."""

    delivery = _read_exact_model(root, artifact, DeliveryPlan)
    authorization = _load_authorization(root, plan)
    if (
        delivery.job_id != plan.job_id
        or delivery.workflow_id != plan.workflow_id
        or delivery.dispatch_id != plan.dispatch_id
        or delivery.session_id != plan.session_id
        or delivery.root_authorization != plan.root_authorization
        or delivery.source_freeze != state.source_freeze
        or [item.profile.profile_id for item in delivery.requests]
        != authorization.requested_delivery_profiles
    ):
        raise ValueError("AQ v2 delivery plan differs from exact quality authorization")
    if state.source_freeze is None:
        raise ValueError("AQ v2 delivery plan has no quality-approved source freeze")
    freeze = _read_exact_model(root, state.source_freeze, QualityApprovedSourceFreeze)
    validate_quality_source_freeze(root, freeze)
    for provenance in delivery.provenance:
        validate_v2_artifact(root, provenance)
    return delivery


def _validate_delivery_review(
    root: Path,
    delivery: DeliveryPlan,
    artifact: AQV2Artifact,
) -> DeliveryReviewBinding:
    """Revalidate every V0.7 draft review against the frozen delivery source."""

    binding = _read_exact_model(root, artifact, DeliveryReviewBinding)
    if (
        binding.job_id != delivery.job_id
        or binding.workflow_id != delivery.workflow_id
        or binding.dispatch_id != delivery.dispatch_id
        or binding.session_id != delivery.session_id
        or binding.delivery_plan.sha256
        != sha256_file(
            root / "production" / "autonomy_v2" / delivery.session_id / "delivery_plan.json"
        )
        or binding.source_freeze != delivery.source_freeze
    ):
        raise ValueError("AQ v2 delivery review does not match its immutable plan")
    expected_ids = {
        request.delivery_id
        for request in delivery.requests
        if request.profile.profile_id != "review_only"
    }
    if {entry.delivery_id for entry in binding.entries} != expected_ids:
        raise ValueError("AQ v2 delivery review entries differ from portable requests")
    freeze = _read_exact_model(root, delivery.source_freeze, QualityApprovedSourceFreeze)
    validate_quality_source_freeze(root, freeze)
    for entry in binding.entries:
        validate_v2_artifact(root, entry.asset_profile)
        draft = _read_exact_model(root, entry.optimization_plan, OptimizationPlan)
        review = _read_exact_model(root, entry.optimization_review, OptimizationReview)
        if (
            draft.status != "draft"
            or draft.job_id != delivery.job_id
            or draft.profile_id != entry.asset_profile_id
            or draft.source.source_fingerprint != freeze.v07_source_fingerprint
            or review.job_id != delivery.job_id
            or review.run_id != entry.run_id
            or review.profile_id != entry.asset_profile_id
            or review.plan_sha256 != entry.exact_plan_sha256
            or entry.optimization_plan.sha256 != entry.exact_plan_sha256
        ):
            raise ValueError("AQ v2 V0.7 review entry is stale or inconsistent")
    for provenance in binding.provenance:
        validate_v2_artifact(root, provenance)
    return binding


def _adopt_or_create_delivery_plan(
    *,
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    allow_disabled_experimental: bool,
) -> tuple[DeliveryPlan, AQV2Artifact]:
    """Recover or create one delivery plan from the exact approved source freeze."""

    if state.source_freeze is None:
        raise ValueError("quality-approved state lacks its exact source freeze")
    path = root / "production" / "autonomy_v2" / plan.session_id / "delivery_plan.json"
    if path.exists():
        artifact = artifact_for_v2(
            root,
            path,
            artifact_id=f"delivery-plan-{plan.session_id}",
            kind="delivery-plan",
        )
        delivery = _validate_delivery_plan(root, plan, state, artifact)
        return delivery, artifact
    delivery, artifact = create_delivery_plan(
        job_root=root,
        root_authorization_artifact=plan.root_authorization,
        source_freeze_artifact=state.source_freeze,
        plan_id=f"delivery-plan-{plan.session_id}",
        allow_disabled_experimental=allow_disabled_experimental,
    )
    return delivery, artifact


def _adopt_or_prepare_delivery_review(
    *,
    root: Path,
    delivery: DeliveryPlan,
    delivery_artifact: AQV2Artifact,
) -> AQV2Artifact | None:
    """Recover or create V0.7 reviews only for portable delivery requests."""

    portable = [
        request for request in delivery.requests if request.profile.profile_id != "review_only"
    ]
    if not portable:
        return None
    path = root / "production" / "autonomy_v2" / delivery.session_id / "delivery_reviews.json"
    if path.exists():
        artifact = artifact_for_v2(
            root,
            path,
            artifact_id=f"review-binding-{delivery.plan_id}",
            kind="delivery-reviews",
        )
        _validate_delivery_review(root, delivery, artifact)
        return artifact
    _binding, artifact = prepare_v07_delivery_reviews(
        job_root=root,
        delivery_plan_artifact=delivery_artifact,
    )
    _validate_delivery_review(root, delivery, artifact)
    return artifact


def _advance_delivery_plan_action(
    *,
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
    allow_disabled_experimental: bool,
) -> dict[str, object]:
    """Plan authorized deliveries, create V0.7 reviews, and stop before approval."""

    _validate_optional_codex_image_material_terminal(
        root=root,
        session_root=session_root,
    )

    delivery, delivery_artifact = _adopt_or_create_delivery_plan(
        root=root,
        plan=plan,
        state=state,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    review_artifact = _adopt_or_prepare_delivery_review(
        root=root,
        delivery=delivery,
        delivery_artifact=delivery_artifact,
    )
    usage = _consume_action_budget(state.budget_usage, budget)
    next_state = transition_state(
        state,
        event="delivery_planned",
        evidence=delivery_artifact,
        created_at=datetime.now(UTC),
        delivery_plan=delivery_artifact,
        budget_usage=usage,
    )
    state_artifact = _write_next_state(root, session_root, next_state)
    return {
        "advanced": True,
        "outcome": "delivery_pending",
        "delivery_plan": delivery_artifact.model_dump(mode="json"),
        "delivery_review": (
            review_artifact.model_dump(mode="json") if review_artifact is not None else None
        ),
        "state": next_state.model_dump(mode="json"),
        "state_artifact": state_artifact.model_dump(mode="json"),
    }


def _approval_boundary(
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
) -> dict[str, object]:
    """Report exact V0.7 approval hashes without creating or consuming approval."""

    if state.delivery_plan is None:
        raise ValueError("delivery-pending state lacks its exact delivery plan")
    delivery = _validate_delivery_plan(root, plan, state, state.delivery_plan)
    portable = [
        request for request in delivery.requests if request.profile.profile_id != "review_only"
    ]
    if not portable:
        return {
            "advanced": False,
            "outcome": "delivery_executor_required",
            "next_action": "publish_review_delivery",
            "reason": (
                "Review-only delivery has no V0.7 approval and is not published by this supervisor."
            ),
            "state": state.model_dump(mode="json"),
        }
    review_path = root / "production" / "autonomy_v2" / plan.session_id / "delivery_reviews.json"
    review_artifact = artifact_for_v2(
        root,
        review_path,
        artifact_id=f"review-binding-{delivery.plan_id}",
        kind="delivery-reviews",
    )
    review = _validate_delivery_review(root, delivery, review_artifact)
    freeze = _read_exact_model(root, delivery.source_freeze, QualityApprovedSourceFreeze)
    validate_quality_source_freeze(root, freeze)
    approvals: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    consumed: list[dict[str, object]] = []
    for entry in review.entries:
        approval_path = root / "optimization" / "runs" / entry.run_id / "optimization_approval.json"
        required = {
            "delivery_id": entry.delivery_id,
            "run_id": entry.run_id,
            "profile_id": entry.profile_id,
            "exact_plan_sha256": entry.exact_plan_sha256,
            "approval_path": approval_path.relative_to(root).as_posix(),
        }
        if not approval_path.is_file():
            missing.append(required)
            continue
        approval = OptimizationApproval.model_validate_json(approval_path.read_bytes())
        reviewed_plan = _read_exact_model(
            root,
            entry.optimization_plan,
            OptimizationPlan,
        )
        if (
            approval.job_id != plan.job_id
            or approval.run_id != entry.run_id
            or approval.profile_id != entry.asset_profile_id
            or approval.plan_sha256 != entry.exact_plan_sha256
            or approval.review_sha256 != entry.optimization_review.sha256
            or approval.profile_sha256 != entry.asset_profile.sha256
            or approval.preflight_sha256 != reviewed_plan.preflight_report.sha256
            or approval.source_fingerprint != freeze.v07_source_fingerprint
        ):
            raise ValueError("V0.7 approval differs from the exact AQ v2 review entry")
        policy_path = (
            root / "optimization" / "runs" / entry.run_id / "optimization_policy_authorization.json"
        )
        if policy_path.exists():
            raise PermissionError(
                "AQ v2 delivery requires exact user approval, not policy authorization"
            )
        artifact = artifact_for_v2(
            root,
            approval_path,
            artifact_id=approval.approval_id,
            kind="optimization_approval",
        )
        payload = {**required, "approval": artifact.model_dump(mode="json")}
        (consumed if approval.used else approvals).append(payload)
    if missing:
        outcome = "waiting_for_v07_approval"
        next_action = "approve_exact_v07_plans"
    elif consumed:
        outcome = "delivery_executor_resume_required"
        next_action = "resume_delivery_executor"
    else:
        outcome = "delivery_executor_required"
        next_action = "run_delivery_executor"
    return {
        "advanced": False,
        "outcome": outcome,
        "next_action": next_action,
        "missing_approvals": missing,
        "approved": approvals,
        "consumed": consumed,
        "delivery_plan": state.delivery_plan.model_dump(mode="json"),
        "delivery_review": review_artifact.model_dump(mode="json"),
        "automatic_user_approval": False,
        "state": state.model_dump(mode="json"),
    }


def _delivery_review_for_execution(
    root: Path,
    delivery: DeliveryPlan,
) -> AQV2Artifact | None:
    """Return the exact portable review binding, or none for review-only delivery."""

    portable = any(request.profile.profile_id != "review_only" for request in delivery.requests)
    path = root / "production" / "autonomy_v2" / delivery.session_id / "delivery_reviews.json"
    if not portable:
        if path.exists():
            raise ValueError("review-only delivery has an unexpected V0.7 review artifact")
        return None
    artifact = artifact_for_v2(
        root,
        path,
        artifact_id=f"review-binding-{delivery.plan_id}",
        kind="delivery-reviews",
    )
    _validate_delivery_review(root, delivery, artifact)
    return artifact


def _validate_terminal_against_pending_state(
    state: AutonomyStateV2,
    terminal: DeliveryTerminalV2,
) -> None:
    """Require an adopted delivery terminal to close this exact pending state."""

    if (
        state.quality_terminal is None
        or state.source_freeze is None
        or state.delivery_plan is None
        or terminal.quality_terminal != state.quality_terminal
        or terminal.source_freeze != state.source_freeze
        or terminal.delivery_plan != state.delivery_plan
    ):
        raise ValueError("delivery terminal does not match the exact pending AQ v2 state")


def _delivery_terminal_path(root: Path, session_id: str) -> Path:
    """Return the fixed session-owned delivery terminal publication path."""

    return root / "production" / "autonomy_v2" / session_id / "delivery_terminal.json"


def _adopt_or_publish_delivery_terminal(
    *,
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    delivery: DeliveryPlan,
    review_artifact: AQV2Artifact | None,
) -> tuple[DeliveryTerminalV2, AQV2Artifact]:
    """Adopt an exact crash-complete terminal or execute and publish it once."""

    if state.quality_terminal is None or state.delivery_plan is None:
        raise ValueError("delivery-pending state lacks quality or delivery evidence")
    terminal_path = _delivery_terminal_path(root, plan.session_id)
    if terminal_path.exists():
        terminal_artifact = artifact_for_v2(
            root,
            terminal_path,
            artifact_id=f"delivery-terminal-{plan.session_id}",
            kind="delivery-terminal",
        )
        terminal = validate_delivery_terminal_v2(root, terminal_artifact)
        _validate_terminal_against_pending_state(state, terminal)
        return terminal, terminal_artifact

    if review_artifact is None:
        results = [
            DeliveryResult(
                delivery_id=request.delivery_id,
                profile_id="review_only",
                status="review_only",
                source_freeze_sha256=delivery.source_freeze.sha256,
                production_ready=False,
            )
            for request in delivery.requests
        ]
    else:
        results = execute_approved_delivery_plan_v2(
            job_root=root,
            delivery_plan_artifact=state.delivery_plan,
            delivery_review_artifact=review_artifact,
        )
    terminal, terminal_artifact = publish_delivery_terminal(
        job_root=root,
        quality_terminal_artifact=state.quality_terminal,
        delivery_plan_artifact=state.delivery_plan,
        delivery_review_artifact=review_artifact,
        results=results,
    )
    validated = validate_delivery_terminal_v2(root, terminal_artifact)
    if validated != terminal:
        raise ValueError("published delivery terminal differs from its exact artifact")
    _validate_terminal_against_pending_state(state, validated)
    return validated, terminal_artifact


def _advance_delivery_action(
    *,
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
) -> dict[str, object]:
    """Finish one approved delivery action and hash-chain its terminal state."""

    _validate_optional_codex_image_material_terminal(
        root=root,
        session_root=session_root,
    )

    if state.delivery_plan is None:
        raise ValueError("delivery-pending state lacks its exact delivery plan")
    delivery = _validate_delivery_plan(root, plan, state, state.delivery_plan)
    review_artifact = _delivery_review_for_execution(root, delivery)
    if review_artifact is not None and not _delivery_terminal_path(root, plan.session_id).exists():
        boundary = _approval_boundary(root, plan, state)
        if boundary["outcome"] == "waiting_for_v07_approval":
            return boundary
    delivery_run_count = sum(
        request.profile.profile_id != "review_only" for request in delivery.requests
    )
    usage = _consume_action_budget(
        state.budget_usage,
        budget,
        delivery_runs=delivery_run_count,
    )
    terminal, terminal_artifact = _adopt_or_publish_delivery_terminal(
        root=root,
        plan=plan,
        state=state,
        delivery=delivery,
        review_artifact=review_artifact,
    )
    next_state = transition_state(
        state,
        event="delivery_finished",
        evidence=terminal_artifact,
        created_at=datetime.now(UTC),
        delivery_terminal=terminal_artifact,
        delivery_results=terminal.results,
        budget_usage=usage,
        reason=f"delivery terminal outcome: {terminal.outcome}",
    )
    state_artifact = _write_next_state(root, session_root, next_state)
    return {
        "advanced": True,
        "outcome": terminal.outcome,
        "next_action": "none",
        "delivery_terminal": terminal_artifact.model_dump(mode="json"),
        "delivery_results": [item.model_dump(mode="json") for item in terminal.results],
        "state": next_state.model_dump(mode="json"),
        "state_artifact": state_artifact.model_dump(mode="json"),
        "automatic_user_approval": False,
    }


def advance_autonomy_v2(
    job_id: str,
    session_id: str,
    *,
    quality_submission: QualitySubmissionV2 | dict[str, object] | None = None,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Execute or recover at most one host-owned AQ v2 action and stop at boundaries."""

    submission = _normalize_quality_submission(quality_submission)
    root, session_root, plan, _budget, _state, _state_artifact = _session_bundle(
        job_id,
        session_id,
    )
    _require_execution_opt_in(
        root,
        plan,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-supervisor-advance",
        ttl_seconds=900,
    ):
        root, session_root, plan, budget, state, state_artifact = _session_bundle(
            job_id,
            session_id,
        )
        _require_execution_opt_in(
            root,
            plan,
            allow_disabled_experimental=allow_disabled_experimental,
        )
        authorization = _load_authorization(root, plan)
        companion_recovery_required = _codex_image_material_quality_recovery_required(
            session_root=session_root,
            state=state,
        )
        companion_recovery = _recover_optional_codex_image_material_quality_result(
            root=root,
            session_root=session_root,
            state=state,
            state_artifact=state_artifact,
            submission=submission,
        )
        if companion_recovery_required and companion_recovery is None:
            return {
                "advanced": False,
                "outcome": "waiting_for_integrated_quality_submission_recovery",
                "next_action": "run_integrated_quality",
                "required_contract": "QualitySubmissionV2",
                "state": state.model_dump(mode="json"),
                "state_artifact": state_artifact.model_dump(mode="json"),
            }
        if companion_recovery is not None:
            return {
                "advanced": False,
                "outcome": "material_loop_quality_terminal_recovered",
                "next_action": state.next_action,
                "state": state.model_dump(mode="json"),
                "state_artifact": state_artifact.model_dump(mode="json"),
                "codex_image_material_loop": companion_recovery,
            }
        if state.next_action == "none" or state.status in _TERMINAL_STATUSES:
            result: dict[str, object] = {
                "advanced": False,
                "outcome": "terminal",
                "next_action": "none",
                "state": state.model_dump(mode="json"),
                "state_artifact": state_artifact.model_dump(mode="json"),
            }
            if companion_recovery is not None:
                result["codex_image_material_loop"] = companion_recovery
            return result
        if state.next_action == "collect_reference":
            return _advance_reference_action(
                root=root,
                session_root=session_root,
                plan=plan,
                budget=budget,
                state=state,
            )
        production_state = _validate_production_anchor(root, plan, state)
        if state.next_action == "execute_controller":
            if state.status == "waiting_for_controller":
                resumed = _resume_pending_controller_locked(
                    root=root,
                    session_root=session_root,
                    plan=plan,
                    budget=budget,
                    state=state,
                    state_artifact=state_artifact,
                )
                return {
                    **resumed,
                    "production_state": production_state.model_dump(mode="json"),
                }
            return {
                "advanced": False,
                "outcome": "waiting_for_controller",
                "next_action": "execute_controller",
                "production_state": production_state.model_dump(mode="json"),
                "state": state.model_dump(mode="json"),
            }
        if state.next_action == "validate_candidate":
            return _controller_validation_boundary(
                root,
                session_root,
                plan,
                budget,
                state,
                authorization,
            )
        if state.next_action == "run_integrated_quality":
            return _advance_quality_action(
                root=root,
                session_root=session_root,
                plan=plan,
                budget=budget,
                state=state,
                authorization=authorization,
                submission=submission,
            )
        if state.next_action == "plan_delivery":
            return _advance_delivery_plan_action(
                root=root,
                session_root=session_root,
                plan=plan,
                budget=budget,
                state=state,
                allow_disabled_experimental=allow_disabled_experimental,
            )
        if state.next_action == "await_v07_approval":
            return _advance_delivery_action(
                root=root,
                session_root=session_root,
                plan=plan,
                budget=budget,
                state=state,
            )
        raise RuntimeError(f"AQ v2 supervisor has no authorized action for {state.next_action}")


def run_autonomy_v2(
    job_id: str,
    session_id: str,
    *,
    max_actions: int = 8,
    quality_submission: QualitySubmissionV2 | dict[str, object] | None = None,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Run bounded actions, adopting pending desktop output before stopping at hard waits."""

    if isinstance(max_actions, bool) or not isinstance(max_actions, int):
        raise TypeError("AQ v2 max_actions must be an integer")
    if not 1 <= max_actions <= 32:
        raise ValueError("AQ v2 max_actions must be within [1, 32]")
    initial = _session_bundle(job_id, session_id)
    plan = initial[2]
    budget = initial[3]
    _require_execution_opt_in(
        initial[0],
        plan,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    permitted = min(max_actions, plan.action_limit, budget.global_action_limit)
    actions: list[dict[str, object]] = []
    stop_reason = "max_actions_reached"
    for _index in range(permitted):
        result = advance_autonomy_v2(
            job_id,
            session_id,
            quality_submission=quality_submission,
            allow_disabled_experimental=allow_disabled_experimental,
        )
        actions.append(result)
        state_payload = result.get("state")
        if not isinstance(state_payload, dict):
            raise ValueError("AQ v2 advance returned no strict state projection")
        if result.get("advanced") is not True:
            stop_reason = str(result.get("outcome", "waiting"))
            break
        if state_payload.get("next_action") in {
            "execute_controller",
            "validate_candidate",
            "await_v07_approval",
            "none",
        }:
            stop_reason = str(state_payload["next_action"])
            break
    final = _session_bundle(job_id, session_id)[4]
    return {
        "profile_status": "disabled_experimental",
        "job_id": job_id,
        "session_id": session_id,
        "max_actions": max_actions,
        "authorized_actions": permitted,
        "actions_executed": len(actions),
        "stop_reason": stop_reason,
        "actions": actions,
        "state": final.model_dump(mode="json"),
        "automatic_user_approval": False,
    }
