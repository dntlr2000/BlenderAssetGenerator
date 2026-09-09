"""Consolidated escalation, telemetry, history, and one-prompt AQ v2 services."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..blender_artifacts import native_io_path, publish_bytes_create_once, sha256_file
from ..workspace import find_reference, job_dir
from .approval_models import (
    ApprovalArtifact,
    ApprovalMode,
    AQV2ApprovalBudget,
    AQV2ApprovalTelemetryReport,
    AQV2ConsolidatedEscalationRequest,
    AQV2EscalationDecision,
    AQV2OnePromptRunPlan,
    AQV2OnePromptRunTerminal,
    AQV2PolicyDecisionReceipt,
    AQV2TechnicalFailureReport,
    AutonomyApprovalPolicyProfile,
    EscalationDecisionItem,
    EscalationSelection,
    FrameworkChangeClassification,
    FrameworkChangeJustification,
    HistoricalSessionAutonomyEligibilityReport,
    OnePromptTerminalType,
    ProviderScope,
    TechnicalFailureCategory,
)
from .approval_policy_service import (
    _approval_root,
    _current_budget_and_receipt,
    _current_unconsumed_policy_authorization,
    _decision_receipt_from_path,
    _load_approval_boundary,
    _load_base_boundary,
    _load_model,
    _policy_rules,
    _stable_id,
    _utc_now,
    _validate_identity_split_gate_target,
    _write_immutable_model,
    approval_artifact_for,
    authorize_routine_gate,
    evaluate_routine_gate_eligibility,
    get_approval_envelope_status,
    plan_approval_envelope,
    publish_policy_decision_receipt,
    validate_approval_artifact,
)
from .controller_bridge import (
    cancel_autonomy_v2,
    get_autonomy_v2_status,
)
from .human_quality_review_service import validate_human_quality_review_bundle_v2
from .models import AQV2Artifact, AutonomyStateV2
from .planner import plan_autonomous_static_prop_v2
from .supervisor_service import (
    QualitySubmissionV2,
    _fail_current_policy_action,
    _run_autonomy_v2_with_policy,
    run_autonomy_v2,
)

_PRODUCER = "codex_blender_modeler.autonomy_v2.approval_supervisor_service"


def _artifact_from_user_path(
    root: Path,
    path: str | Path,
    *,
    kind: str,
    id_prefix: str,
) -> ApprovalArtifact:
    """Bind one caller-selected existing job artifact without trusting its metadata."""

    candidate = Path(path) if Path(path).is_absolute() else root / path
    return approval_artifact_for(
        root,
        candidate,
        artifact_id=_stable_id(id_prefix, str(path)),
        kind=kind,
    )


def _artifact_sequence(
    root: Path,
    paths: list[str | Path],
    kinds: list[str],
    *,
    id_prefix: str,
) -> list[ApprovalArtifact]:
    """Bind parallel path/kind lists and reject duplicate evidence paths."""

    if len(paths) != len(kinds):
        raise ValueError("artifact paths and kinds must have equal length")
    artifacts = [
        _artifact_from_user_path(
            root,
            path,
            kind=kind,
            id_prefix=f"{id_prefix}-{index:02d}",
        )
        for index, (path, kind) in enumerate(zip(paths, kinds, strict=True))
    ]
    if len({item.path for item in artifacts}) != len(artifacts):
        raise ValueError("artifact paths must be unique")
    return artifacts


def _approval_boundary_budget(
    job_id: str,
    session_id: str,
) -> tuple[
    tuple[Any, ...],
    AQV2ApprovalBudget,
    ApprovalArtifact | None,
]:
    """Load the approval boundary and replay its current policy decision budget."""

    boundary = _load_approval_boundary(job_id, session_id)
    current_budget, previous_receipt = _current_budget_and_receipt(
        boundary[0],
        session_id,
        boundary[6],
        boundary[5],
        boundary[7],
        boundary[8],
        boundary[9],
    )
    return boundary, current_budget, previous_receipt


def publish_consolidated_escalation(
    job_id: str,
    session_id: str,
    *,
    current_best_candidate_path: str | Path,
    current_best_candidate_kind: str,
    completed_evidence_paths: list[str | Path],
    completed_evidence_kinds: list[str],
    decisions: list[EscalationDecisionItem | dict[str, object]],
    review_bundle_if_no_decision_path: str | Path | None = None,
    review_bundle_if_no_decision_kind: str = "quality-review-bundle",
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Publish one complete genuine-decision request instead of parallel approvals."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    boundary, current_budget, _previous_receipt = _approval_boundary_budget(
        job_id,
        session_id,
    )
    root, plan = boundary[0], boundary[1]
    profile_artifact, budget_artifact = boundary[5], boundary[7]
    envelope_artifact = boundary[9]
    escalation_root = _approval_root(root, session_id) / "escalation"
    request_path = escalation_root / "request.json"
    if os.path.isfile(native_io_path(request_path)):
        artifact = approval_artifact_for(
            root,
            request_path,
            artifact_id=f"escalation-{session_id}",
            kind="aqv2-consolidated-escalation-request",
        )
        existing = _load_model(root, artifact, AQV2ConsolidatedEscalationRequest)
        return {
            "status": "existing",
            "request": existing.model_dump(mode="json"),
            "request_artifact": artifact.model_dump(mode="json"),
            "individual_approval_request_count": 0,
        }
    normalized_decisions = [
        item
        if isinstance(item, EscalationDecisionItem)
        else EscalationDecisionItem.model_validate(item)
        for item in decisions
    ]
    if not normalized_decisions:
        raise ValueError("consolidated escalation requires at least one genuine decision")
    candidate = _artifact_from_user_path(
        root,
        current_best_candidate_path,
        kind=current_best_candidate_kind,
        id_prefix="escalation-candidate",
    )
    completed = _artifact_sequence(
        root,
        completed_evidence_paths,
        completed_evidence_kinds,
        id_prefix="escalation-evidence",
    )
    if not completed:
        raise ValueError("consolidated escalation requires completed evidence")
    review_bundle = None
    if review_bundle_if_no_decision_path is not None:
        review_bundle = _artifact_from_user_path(
            root,
            review_bundle_if_no_decision_path,
            kind=review_bundle_if_no_decision_kind,
            id_prefix="escalation-review-bundle",
        )
    total_actions = sum(
        max(choice.additional_budget_actions for choice in item.choices)
        for item in normalized_decisions
    )
    changed_scope = list(
        dict.fromkeys(
            scope
            for item in normalized_decisions
            for choice in item.choices
            for scope in choice.changed_scope
        )
    )
    observed_at = _utc_now(created_at)
    escalation_id = f"escalation-{session_id}"
    request = AQV2ConsolidatedEscalationRequest(
        contract_id=escalation_id,
        escalation_id=escalation_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=boundary[3],
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="maintains",
        approval_count_justification=(
            "All currently known user-only choices are consolidated into one payload."
        ),
        policy_profile=profile_artifact,
        approval_envelope=envelope_artifact,
        approval_budget=budget_artifact,
        current_best_candidate=candidate,
        completed_evidence=completed,
        decisions=normalized_decisions,
        total_additional_budget_actions=total_actions,
        changed_scope=changed_scope,
        review_bundle_if_no_decision=review_bundle,
    )
    artifact = _write_immutable_model(
        root,
        request_path,
        request,
        artifact_id=escalation_id,
        kind="aqv2-consolidated-escalation-request",
    )
    return {
        "status": "pending",
        "request": request.model_dump(mode="json"),
        "request_artifact": artifact.model_dump(mode="json"),
        "current_budget": current_budget.model_dump(mode="json"),
        "individual_approval_request_count": 0,
        "is_user_approval": False,
    }


def _decision_budget_after(
    budget: AQV2ApprovalBudget,
    request: AQV2ConsolidatedEscalationRequest,
    *,
    created_at: datetime,
) -> AQV2ApprovalBudget:
    """Project one consolidated user decision into categorical approval counters."""

    reasons = {item.reason for item in request.decisions}
    updates: dict[str, object] = {
        "contract_id": f"approval-budget-{budget.session_id}-user-0001",
        "budget_id": f"approval-budget-{budget.session_id}-user-0001",
        "created_at": created_at,
        "additional_user_decisions": budget.additional_user_decisions + 1,
        "total_elapsed_actions": budget.total_elapsed_actions + 1,
    }
    if reasons & {"scope_expansion", "target_change", "reference_replacement"}:
        updates["scope_user_approvals"] = budget.scope_user_approvals + 1
    if "budget_expansion" in reasons:
        updates["budget_user_approvals"] = budget.budget_user_approvals + 1
    if reasons & {"delivery_expansion", "provider_scope_expansion"}:
        updates["delivery_user_approvals"] = budget.delivery_user_approvals + 1
    if "destination_project_write" in reasons:
        updates["destination_user_approvals"] = budget.destination_user_approvals + 1
    return AQV2ApprovalBudget.model_validate(
        budget.model_copy(update=updates).model_dump(mode="python")
    )


def record_consolidated_escalation_decision(
    job_id: str,
    session_id: str,
    *,
    selections: list[EscalationSelection | dict[str, object]],
    decision_payload: str | bytes,
    explicit_user_decision_observed: bool,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Record one exact user response to every item in the consolidated request."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    if not explicit_user_decision_observed:
        raise PermissionError("escalation decision requires observed exact user input")
    boundary, current_budget, _previous_receipt = _approval_boundary_budget(
        job_id,
        session_id,
    )
    root, plan, envelope = boundary[0], boundary[1], boundary[8]
    escalation_root = _approval_root(root, session_id) / "escalation"
    request_path = escalation_root / "request.json"
    request_artifact = approval_artifact_for(
        root,
        request_path,
        artifact_id=f"escalation-{session_id}",
        kind="aqv2-consolidated-escalation-request",
    )
    request = _load_model(root, request_artifact, AQV2ConsolidatedEscalationRequest)
    decision_path = escalation_root / "decision.json"
    if os.path.exists(native_io_path(decision_path)):
        raise FileExistsError("consolidated escalation already has a decision")
    if envelope.approval_mode == "autonomous":
        raise PermissionError(
            "autonomous escalation is a terminal; continuing requires new user authority"
        )
    normalized = [
        item
        if isinstance(item, EscalationSelection)
        else EscalationSelection.model_validate(item)
        for item in selections
    ]
    selected = {item.item_id: item.choice_id for item in normalized}
    expected_items = {item.item_id for item in request.decisions}
    if set(selected) != expected_items:
        raise ValueError("escalation response must select every consolidated decision item")
    valid_choices = {
        item.item_id: {choice.choice_id for choice in item.choices}
        for item in request.decisions
    }
    if any(choice_id not in valid_choices[item_id] for item_id, choice_id in selected.items()):
        raise ValueError("escalation response contains an unknown choice")
    observed_at = _utc_now(created_at)
    budget_after = _decision_budget_after(
        current_budget,
        request,
        created_at=observed_at,
    )
    payload_bytes = (
        decision_payload.encode("utf-8")
        if isinstance(decision_payload, str)
        else bytes(decision_payload)
    )
    if not payload_bytes:
        raise ValueError("escalation decision payload must not be empty")
    decision_id = f"escalation-decision-{session_id}"
    decision = AQV2EscalationDecision(
        contract_id=decision_id,
        decision_id=decision_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=boundary[3],
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="maintains",
        approval_count_justification=(
            "One consolidated response replaces multiple individual approval prompts."
        ),
        policy_profile=boundary[5],
        approval_envelope=boundary[9],
        approval_budget=boundary[7],
        escalation_request=request_artifact,
        selections=normalized,
        budget_before=current_budget,
        budget_after=budget_after,
        decision_payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        decided_at=observed_at,
    )
    artifact = _write_immutable_model(
        root,
        decision_path,
        decision,
        artifact_id=decision_id,
        kind="aqv2-escalation-decision",
    )
    return {
        "status": "decided",
        "decision": decision.model_dump(mode="json"),
        "decision_artifact": artifact.model_dump(mode="json"),
        "additional_user_decision_count": 1,
        "individual_approval_artifacts_created": 0,
    }


def get_escalation_status(job_id: str, session_id: str) -> dict[str, object]:
    """Report consolidated escalation state without creating or modifying evidence."""

    boundary = _load_approval_boundary(job_id, session_id)
    root = boundary[0]
    escalation_root = _approval_root(root, session_id) / "escalation"
    request_path = escalation_root / "request.json"
    if not os.path.isfile(native_io_path(request_path)):
        return {"status": "none", "job_id": job_id, "session_id": session_id}
    request_artifact = approval_artifact_for(
        root,
        request_path,
        artifact_id=f"escalation-{session_id}",
        kind="aqv2-consolidated-escalation-request",
    )
    request = _load_model(root, request_artifact, AQV2ConsolidatedEscalationRequest)
    decision_path = escalation_root / "decision.json"
    decision = None
    if os.path.isfile(native_io_path(decision_path)):
        decision_artifact = approval_artifact_for(
            root,
            decision_path,
            artifact_id=f"escalation-decision-{session_id}",
            kind="aqv2-escalation-decision",
        )
        decision = _load_model(root, decision_artifact, AQV2EscalationDecision)
        if decision.escalation_request != request_artifact:
            raise ValueError("escalation decision does not bind the exact request")
    return {
        "status": "decided" if decision is not None else "pending",
        "request": request.model_dump(mode="json"),
        "decision": None if decision is None else decision.model_dump(mode="json"),
        "individual_approval_request_count": 0,
    }


def publish_framework_change_justification(
    job_id: str,
    session_id: str,
    *,
    classification: FrameworkChangeClassification,
    issue_summary: str,
    evidence_paths: list[str | Path],
    evidence_kinds: list[str],
    generic_fixture_kinds: list[str] | None = None,
    affected_job_ids: list[str] | None = None,
    violated_invariant_ids: list[str] | None = None,
    request_new_public_schema: bool = False,
    request_new_public_cli: bool = False,
    request_new_approval_type: bool = False,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Classify a failure before any reusable framework-surface change is considered."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    boundary = _load_approval_boundary(job_id, session_id)
    root, plan = boundary[0], boundary[1]
    fixture_kinds = list(dict.fromkeys(generic_fixture_kinds or []))
    jobs = list(dict.fromkeys(affected_job_ids or [job_id]))
    invariants = list(dict.fromkeys(violated_invariant_ids or []))
    evidence = _artifact_sequence(
        root,
        evidence_paths,
        evidence_kinds,
        id_prefix="framework-evidence",
    )
    if not evidence:
        raise ValueError("framework classification requires exact evidence")
    reusable = len(fixture_kinds) >= 2 or len(jobs) >= 2 or bool(invariants)
    public_allowed = classification in {
        "framework_invariant_violation",
        "reusable_missing_capability",
    } and reusable
    if any(
        (request_new_public_schema, request_new_public_cli, request_new_approval_type)
    ) and not public_allowed:
        raise PermissionError("job-local or reference-specific evidence cannot add public surface")
    observed_at = _utc_now(created_at)
    justification_id = _stable_id(
        "framework-change",
        {
            "classification": classification,
            "evidence": [item.sha256 for item in evidence],
            "fixtures": fixture_kinds,
            "jobs": jobs,
            "invariants": invariants,
        },
    )
    if public_allowed:
        reasons = [
            "Reusable or invariant evidence satisfies the framework-change threshold."
        ]
    elif classification in {
        "framework_invariant_violation",
        "reusable_missing_capability",
    }:
        reasons = [
            "The issue is framework-level, but current evidence does not satisfy the "
            "public-surface change threshold."
        ]
    else:
        reasons = [
            "The issue remains job-local or reference-specific and must not expand APIs."
        ]
    justification = FrameworkChangeJustification(
        contract_id=justification_id,
        justification_id=justification_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=boundary[3],
        policy_profile=boundary[5],
        approval_envelope=boundary[9],
        classification=classification,
        issue_summary=issue_summary,
        generic_fixture_kinds=fixture_kinds,
        affected_job_ids=jobs,
        violated_invariant_ids=invariants,
        evidence_artifacts=evidence,
        public_framework_change_allowed=public_allowed,
        new_public_schema_allowed=request_new_public_schema,
        new_public_cli_allowed=request_new_public_cli,
        new_approval_type_allowed=request_new_approval_type,
        job_local_candidate_fix_required=(
            classification == "job_local_candidate_error"
        ),
        decision_reasons=reasons,
        producer=_PRODUCER,
        producer_version="0.1.0",
        created_at=observed_at,
        approval_count_effect=(
            "increases" if request_new_approval_type else "maintains"
        ),
        approval_count_justification=(
            "Any requested approval type is counted explicitly."
            if request_new_approval_type
            else "Classification does not add a user approval boundary."
        ),
    )
    artifact = _write_immutable_model(
        root,
        _approval_root(root, session_id)
        / "framework"
        / f"{justification_id}.json",
        justification,
        artifact_id=justification_id,
        kind="framework-change-justification",
    )
    return {
        "status": "classified",
        "justification": justification.model_dump(mode="json"),
        "justification_artifact": artifact.model_dump(mode="json"),
        "public_framework_change_allowed": public_allowed,
    }


def publish_historical_identity_split_eligibility(
    job_id: str,
    session_id: str,
    *,
    approval_request_path: str | Path,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Assess a legacy identity split read-only without creating retroactive authority."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    status = get_approval_envelope_status(job_id, session_id)
    if status["status"] != "legacy_without_envelope":
        raise PermissionError("historical eligibility is only for sessions without envelopes")
    root, plan, _authorization, root_artifact = _load_base_boundary(job_id, session_id)
    observed_at = _utc_now(created_at)
    analysis_root = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "historical_analysis"
    )
    transformations = list(
        dict.fromkeys(
            item.bounded_transformation
            for item in _policy_rules()
            if item.bounded_transformation is not None
        )
    )
    profile = AutonomyApprovalPolicyProfile(
        contract_id=f"historical-policy-{session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="maintains",
        approval_count_justification=(
            "Read-only historical comparison creates no current action authority."
        ),
        profile_id=f"historical-policy-{session_id}",
        supported_modes=["autonomous", "checkpointed", "interactive"],
        routine_gate_policies=_policy_rules(),
        allowed_bounded_transformations=transformations,
    )
    profile_artifact = _write_immutable_model(
        root,
        analysis_root / "future_policy_profile.json",
        profile,
        artifact_id=profile.contract_id,
        kind="autonomy-approval-policy-profile",
    )
    request = _artifact_from_user_path(
        root,
        approval_request_path,
        kind="material-identity-split-approval-request",
        id_prefix="historical-identity-split",
    )
    # The validator reads only the two immutable split caps from this hypothetical
    # object; it never writes or grants authority.
    hypothetical_caps = type(
        "HistoricalIdentitySplitCaps",
        (),
        {"max_identity_splits": 4, "max_material_identities_created": 4},
    )()
    forbidden = _validate_identity_split_gate_target(
        root,
        request,
        hypothetical_caps,  # type: ignore[arg-type]
    )
    passed = not forbidden
    condition_results = {
        "exact_semantic_clone": passed,
        "within_default_identity_cap": passed,
        "localized_assignment_only": passed,
        "geometry_topology_transform_dimensions_unchanged": passed,
        "uv_reference_target_scope_unchanged": passed,
        "clone_equivalence_and_assignment_exclusivity": passed,
        "shadow_blender_rebuild_passed": passed,
        "rollback_archive_can_be_prepared": passed,
    }
    report_id = _stable_id(
        "historical-eligibility",
        {"request": request.sha256, "conditions": condition_results},
    )
    report = HistoricalSessionAutonomyEligibilityReport(
        contract_id=report_id,
        report_id=report_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="maintains",
        approval_count_justification=(
            "Historical analysis never changes or reclassifies existing approvals."
        ),
        policy_profile=profile_artifact,
        historical_session_artifacts=[request],
        evaluated_gate_kind="bounded_material_identity_split",
        future_bounded_conditions_satisfied=passed,
        condition_results=condition_results,
        policy_authorization_that_could_have_applied=(
            "bounded_material_identity_split" if passed else None
        ),
        additional_user_decision_would_have_been_required=not passed,
        decision_reasons=(
            ["Future bounded identity-split policy conditions all pass."]
            if passed
            else [f"Historical evidence failed: {item}" for item in forbidden]
        ),
    )
    artifact = _write_immutable_model(
        root,
        analysis_root / f"{report_id}.json",
        report,
        artifact_id=report_id,
        kind="historical-session-autonomy-eligibility-report",
    )
    return {
        "status": "read_only_complete",
        "report": report.model_dump(mode="json"),
        "report_artifact": artifact.model_dump(mode="json"),
        "retroactive_authority_applied": False,
        "canonical_apply_performed": False,
    }


def _latest_state_artifact(
    job_id: str,
    session_id: str,
) -> tuple[Path, AutonomyStateV2, ApprovalArtifact]:
    """Load the replayed current AQ state and project its exact companion artifact."""

    status = get_autonomy_v2_status(job_id, session_id)
    root = job_dir(job_id)
    state = AutonomyStateV2.model_validate_json(json.dumps(status["state"]))
    artifact = ApprovalArtifact.model_validate(status["state_artifact"])
    validate_approval_artifact(root, artifact)
    return root, state, artifact


def _decision_adjusted_budget(
    root: Path,
    session_id: str,
    current_budget: AQV2ApprovalBudget,
) -> tuple[AQV2ApprovalBudget, ApprovalArtifact | None]:
    """Adopt one terminal consolidated decision after validating its policy budget base."""

    path = _approval_root(root, session_id) / "escalation" / "decision.json"
    if not os.path.isfile(native_io_path(path)):
        return current_budget, None
    with open(native_io_path(path), "rb") as handle:
        decision = AQV2EscalationDecision.model_validate_json(handle.read())
    artifact = approval_artifact_for(
        root,
        path,
        artifact_id=decision.decision_id,
        kind="aqv2-escalation-decision",
    )
    if decision.budget_before != current_budget:
        raise ValueError("escalation decision budget is stale or spliced")
    return decision.budget_after, artifact


def _telemetry_budget_snapshot(
    budget: AQV2ApprovalBudget,
    state: AutonomyStateV2,
    *,
    created_at: datetime,
) -> AQV2ApprovalBudget:
    """Merge replayed AQ execution usage into separated approval counters."""

    usage = state.budget_usage
    updates = {
        "contract_id": f"approval-budget-{budget.session_id}-telemetry-{state.sequence:04d}",
        "budget_id": f"approval-budget-{budget.session_id}-telemetry-{state.sequence:04d}",
        "created_at": created_at,
        "controller_invocations": max(
            budget.controller_invocations,
            usage.controller_invocations,
        ),
        "canonical_promotions": max(
            budget.canonical_promotions,
            usage.canonical_promotions,
        ),
        "blender_builds": max(budget.blender_builds, usage.total_blender_builds),
        "quality_evaluations": max(
            budget.quality_evaluations,
            usage.total_quality_evaluations,
        ),
        "delivery_runs": max(budget.delivery_runs, usage.delivery_runs),
        "quality_terminals": max(
            budget.quality_terminals,
            int(state.quality_terminal is not None),
        ),
        "delivery_terminals": max(
            budget.delivery_terminals,
            int(state.delivery_terminal is not None),
        ),
        "total_elapsed_actions": max(
            budget.total_elapsed_actions,
            usage.total_actions,
        ),
    }
    return AQV2ApprovalBudget.model_validate(
        budget.model_copy(update=updates).model_dump(mode="python")
    )


def _telemetry_promotion_counts(
    budget: AQV2ApprovalBudget,
    state: AutonomyStateV2,
) -> tuple[int, int]:
    """Separate issued promotion authority from executed canonical state changes."""

    return (
        budget.canonical_promotions,
        state.budget_usage.canonical_promotions,
    )


def publish_approval_telemetry(
    job_id: str,
    session_id: str,
    *,
    terminal_type: OnePromptTerminalType,
    human_review_performed: bool = False,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Replay immutable approval and AQ state evidence into a machine KPI report."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    boundary, current_budget, previous_receipt = _approval_boundary_budget(
        job_id,
        session_id,
    )
    root, plan = boundary[0], boundary[1]
    telemetry_path = (
        _approval_root(root, session_id) / "telemetry" / f"{terminal_type}.json"
    )
    if os.path.isfile(native_io_path(telemetry_path)):
        with open(native_io_path(telemetry_path), "rb") as handle:
            existing = AQV2ApprovalTelemetryReport.model_validate_json(handle.read())
        artifact = approval_artifact_for(
            root,
            telemetry_path,
            artifact_id=existing.report_id,
            kind="aqv2-approval-telemetry-report",
        )
        return {
            "status": "existing",
            "report": existing.model_dump(mode="json"),
            "report_artifact": artifact.model_dump(mode="json"),
            "technical_user_approval_request_count": 0,
            "canonical_corruption_count": 0,
        }
    root, state, state_artifact = _latest_state_artifact(job_id, session_id)
    current_budget, escalation_decision = _decision_adjusted_budget(
        root,
        session_id,
        current_budget,
    )
    observed_at = _utc_now(created_at)
    consumed = _telemetry_budget_snapshot(
        current_budget,
        state,
        created_at=observed_at,
    )
    promotion_authorizations, executed_promotions = _telemetry_promotion_counts(
        consumed,
        state,
    )
    sources = [boundary[9], state_artifact]
    decisions_root = _approval_root(root, session_id) / "decisions"
    if os.path.isdir(native_io_path(decisions_root)):
        sources.extend(
            _decision_receipt_from_path(root, path)[1]
            for path in sorted(decisions_root.glob("*.json"))
        )
    if escalation_decision is not None:
        sources.append(escalation_decision)
    if previous_receipt is not None and previous_receipt not in sources:
        sources.append(previous_receipt)
    report_id = _stable_id(
        "approval-telemetry",
        {
            "state": state_artifact.sha256,
            "budget": consumed.model_dump(mode="json"),
            "terminal": terminal_type,
            "human_review": human_review_performed,
        },
    )
    report = AQV2ApprovalTelemetryReport(
        contract_id=report_id,
        report_id=report_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=boundary[3],
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "Counters are replayed from separated policy, user-decision, and AQ evidence."
        ),
        policy_profile=boundary[5],
        approval_envelope=boundary[9],
        source_artifacts=sources,
        additional_user_decision_count=consumed.additional_user_decisions,
        geometry_user_approval_count=consumed.geometry_user_approvals,
        material_user_approval_count=consumed.material_user_approvals,
        scope_user_approval_count=consumed.scope_user_approvals,
        delivery_user_approval_count=consumed.delivery_user_approvals,
        routine_policy_authorization_count=(
            consumed.routine_policy_authorizations
        ),
        technical_repair_count=consumed.technical_policy_repairs,
        controller_invocation_count=consumed.controller_invocations,
        canonical_promotion_count=executed_promotions,
        canonical_promotion_authorization_count=promotion_authorizations,
        canonical_promotion_count_semantics="executed_state_transition",
        rollback_count=consumed.rollbacks,
        imagegen_generation_count=consumed.imagegen_generations,
        blender_build_count=consumed.blender_builds,
        quality_evaluation_count=consumed.quality_evaluations,
        delivery_run_count=consumed.delivery_runs,
        terminal_type=terminal_type,
        total_elapsed_actions=consumed.total_elapsed_actions,
        budget_consumed=consumed,
        human_review_performed=human_review_performed,
    )
    artifact = _write_immutable_model(
        root,
        telemetry_path,
        report,
        artifact_id=report_id,
        kind="aqv2-approval-telemetry-report",
    )
    return {
        "status": "published",
        "report": report.model_dump(mode="json"),
        "report_artifact": artifact.model_dump(mode="json"),
        "technical_user_approval_request_count": 0,
        "canonical_corruption_count": 0,
    }


def get_approval_telemetry(job_id: str, session_id: str) -> dict[str, object]:
    """Read every published terminal telemetry report after exact hash validation."""

    boundary = _load_approval_boundary(job_id, session_id)
    root = boundary[0]
    telemetry_root = _approval_root(root, session_id) / "telemetry"
    reports: list[dict[str, object]] = []
    if os.path.isdir(native_io_path(telemetry_root)):
        for path in sorted(telemetry_root.glob("*.json")):
            with open(native_io_path(path), "rb") as handle:
                report = AQV2ApprovalTelemetryReport.model_validate_json(handle.read())
            artifact = approval_artifact_for(
                root,
                path,
                artifact_id=report.report_id,
                kind="aqv2-approval-telemetry-report",
            )
            reports.append(
                {
                    "report": report.model_dump(mode="json"),
                    "artifact": artifact.model_dump(mode="json"),
                }
            )
    return {
        "status": "available" if reports else "not_published",
        "job_id": job_id,
        "session_id": session_id,
        "reports": reports,
    }


def plan_one_prompt_run(
    request: str,
    *,
    reference_path: str | Path,
    target_subject: str,
    requested_delivery_profiles: list[str],
    approval_mode: ApprovalMode = "autonomous",
    explicit_autonomy_delegation_observed: bool,
    allowed_provider_scopes: list[ProviderScope] | None = None,
    job_id: str | None = None,
    controller_execution_mode: str = "desktop_in_session",
    destination_hint: str = "engine_neutral",
    initial_budget_limits: dict[str, int] | None = None,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Create the base AQ session, exact envelope, and one-prompt supervisor plan."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ one-prompt supervisor remains disabled_experimental")
    if approval_mode in {"autonomous", "checkpointed"} and not (
        explicit_autonomy_delegation_observed
    ):
        raise PermissionError(
            "autonomous and checkpointed one-prompt modes require explicit delegation"
        )
    exact_request = str(request)
    base = plan_autonomous_static_prop_v2(
        exact_request,
        reference_path=reference_path,
        target_subject=target_subject,
        requested_delivery_profiles=requested_delivery_profiles,  # type: ignore[arg-type]
        job_id=job_id,
        controller_execution_mode=controller_execution_mode,
        destination_hint=destination_hint,
        initial_budget_limits=initial_budget_limits,
        allow_disabled_experimental=True,
    )
    created_job_id = str(base["job_id"])
    session_id = str(base["session_id"])
    initial_sha256 = hashlib.sha256(exact_request.encode("utf-8")).hexdigest()
    envelope_result = plan_approval_envelope(
        created_job_id,
        session_id,
        approval_mode=approval_mode,
        initial_user_request_sha256=initial_sha256,
        explicit_autonomy_delegation_observed=(
            explicit_autonomy_delegation_observed
        ),
        allowed_provider_scopes=allowed_provider_scopes,
        allow_disabled_experimental=True,
    )
    root = job_dir(created_job_id)
    base_plan_artifact = ApprovalArtifact.model_validate(base["artifacts"]["plan"])
    initial_state_artifact = ApprovalArtifact.model_validate(base["artifacts"]["state"])
    root_authorization = ApprovalArtifact.model_validate(
        base["artifacts"]["root_authorization"]
    )
    envelope_artifacts = envelope_result["artifacts"]
    profile_artifact = ApprovalArtifact.model_validate(
        envelope_artifacts["policy_profile"]
    )
    budget_artifact = ApprovalArtifact.model_validate(
        envelope_artifacts["approval_budget"]
    )
    envelope_artifact = ApprovalArtifact.model_validate(
        envelope_artifacts["approval_envelope"]
    )
    approval_budget = AQV2ApprovalBudget.model_validate_json(
        json.dumps(envelope_result["approval_budget"])
    )
    base_plan = base["plan"]
    observed_at = datetime.now(UTC)
    plan_id = f"one-prompt-{session_id}"
    one_prompt = AQV2OnePromptRunPlan(
        contract_id=plan_id,
        plan_id=plan_id,
        job_id=created_job_id,
        workflow_id=str(base["workflow_id"]),
        dispatch_id=str(base["dispatch_id"]),
        session_id=session_id,
        root_authorization=root_authorization,
        policy_profile=profile_artifact,
        approval_envelope=envelope_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "One bounded supervisor continues through routine host policy gates."
        ),
        approval_budget=budget_artifact,
        base_autonomy_plan=base_plan_artifact,
        initial_autonomy_state=initial_state_artifact,
        approval_mode=approval_mode,
        phases=["geometry", "material", "quality", "delivery", "terminal"],
        requested_delivery_profiles=requested_delivery_profiles,  # type: ignore[arg-type]
        controller_execution_mode=controller_execution_mode,  # type: ignore[arg-type]
        only_waits_for_consolidated_escalation=(approval_mode != "interactive"),
        routine_approval_wait_allowed=(approval_mode == "interactive"),
        global_action_limit=min(
            int(base_plan["action_limit"]),
            approval_budget.max_total_elapsed_actions,
        ),
    )
    artifact = _write_immutable_model(
        root,
        _approval_root(root, session_id) / "one_prompt" / "plan.json",
        one_prompt,
        artifact_id=plan_id,
        kind="aqv2-one-prompt-run-plan",
    )
    return {
        "status": "planned",
        "profile_status": "disabled_experimental",
        "job_id": created_job_id,
        "session_id": session_id,
        "one_prompt_plan": one_prompt.model_dump(mode="json"),
        "one_prompt_plan_artifact": artifact.model_dump(mode="json"),
        "approval_envelope": envelope_result["approval_envelope"],
        "initial_user_request_count": 1,
        "additional_user_decision_count": 0,
        "technical_user_approval_request_count": 0,
        "repository_creates_codex_task": False,
        "app_close_background_execution": False,
    }


def _load_one_prompt_plan(
    job_id: str,
    session_id: str,
) -> tuple[Path, AQV2OnePromptRunPlan, ApprovalArtifact, tuple[Any, ...]]:
    """Replay one canonical one-prompt plan and all of its immutable bindings."""

    boundary = _load_approval_boundary(job_id, session_id)
    root = boundary[0]
    path = _approval_root(root, session_id) / "one_prompt" / "plan.json"
    with open(native_io_path(path), "rb") as handle:
        plan = AQV2OnePromptRunPlan.model_validate_json(handle.read())
    artifact = approval_artifact_for(
        root,
        path,
        artifact_id=plan.plan_id,
        kind="aqv2-one-prompt-run-plan",
    )
    base_plan_path = root / plan.base_autonomy_plan.path
    expected_base_path = (
        root / "production" / "autonomy_v2" / session_id / "plan.json"
    )
    if (
        plan.job_id != job_id
        or plan.session_id != session_id
        or plan.root_authorization != boundary[3]
        or plan.policy_profile != boundary[5]
        or plan.approval_envelope != boundary[9]
        or plan.approval_budget != boundary[7]
        or base_plan_path.resolve() != expected_base_path.resolve()
    ):
        raise ValueError("one-prompt plan differs from its exact approval boundary")
    for support in (
        plan.base_autonomy_plan,
        plan.initial_autonomy_state,
        plan.root_authorization,
        plan.policy_profile,
        plan.approval_envelope,
        plan.approval_budget,
    ):
        validate_approval_artifact(root, support)
    return root, plan, artifact, boundary


def _load_existing_one_prompt_terminal(
    root: Path,
    session_id: str,
) -> tuple[AQV2OnePromptRunTerminal, ApprovalArtifact] | None:
    """Load the immutable one-prompt terminal when the run already finished."""

    path = _approval_root(root, session_id) / "one_prompt" / "terminal.json"
    if not os.path.isfile(native_io_path(path)):
        return None
    with open(native_io_path(path), "rb") as handle:
        terminal = AQV2OnePromptRunTerminal.model_validate_json(handle.read())
    artifact = approval_artifact_for(
        root,
        path,
        artifact_id=terminal.terminal_id,
        kind="aqv2-one-prompt-run-terminal",
    )
    return terminal, artifact


def _publish_one_prompt_terminal(
    job_id: str,
    session_id: str,
    *,
    terminal_type: OnePromptTerminalType,
    delivery_terminal: ApprovalArtifact | None = None,
    review_bundle: ApprovalArtifact | None = None,
    consolidated_escalation: ApprovalArtifact | None = None,
    framework_change_justification: ApprovalArtifact | None = None,
    framework_failure_report: ApprovalArtifact | None = None,
    human_review_performed: bool = False,
) -> dict[str, object]:
    """Publish one safe terminal and its replayed approval telemetry exactly once."""

    root, plan, plan_artifact, boundary = _load_one_prompt_plan(job_id, session_id)
    existing = _load_existing_one_prompt_terminal(root, session_id)
    if existing is not None:
        return {
            "status": "terminal",
            "terminal": existing[0].model_dump(mode="json"),
            "terminal_artifact": existing[1].model_dump(mode="json"),
        }
    _root, state, state_artifact = _latest_state_artifact(job_id, session_id)
    telemetry_result = publish_approval_telemetry(
        job_id,
        session_id,
        terminal_type=terminal_type,
        human_review_performed=human_review_performed,
        allow_disabled_experimental=True,
    )
    telemetry_artifact = ApprovalArtifact.model_validate(
        telemetry_result["report_artifact"]
    )
    telemetry = AQV2ApprovalTelemetryReport.model_validate_json(
        json.dumps(telemetry_result["report"])
    )
    observed_at = datetime.now(UTC)
    terminal_id = f"one-prompt-terminal-{session_id}"
    terminal = AQV2OnePromptRunTerminal(
        contract_id=terminal_id,
        terminal_id=terminal_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=boundary[3],
        policy_profile=boundary[5],
        approval_envelope=boundary[9],
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "The run reaches one explicit safe terminal without routine user prompts."
        ),
        one_prompt_plan=plan_artifact,
        final_autonomy_state=state_artifact,
        terminal_type=terminal_type,
        delivery_terminal=delivery_terminal,
        review_bundle=review_bundle,
        consolidated_escalation=consolidated_escalation,
        framework_change_justification=framework_change_justification,
        framework_failure_report=framework_failure_report,
        approval_telemetry=telemetry_artifact,
        canonical_restored_after_rollback=(
            telemetry.rollback_count == 0 or telemetry.canonical_corruption_count == 0
        ),
    )
    artifact = _write_immutable_model(
        root,
        _approval_root(root, session_id) / "one_prompt" / "terminal.json",
        terminal,
        artifact_id=terminal_id,
        kind="aqv2-one-prompt-run-terminal",
    )
    return {
        "status": "terminal",
        "terminal_type": terminal_type,
        "terminal": terminal.model_dump(mode="json"),
        "terminal_artifact": artifact.model_dump(mode="json"),
        "approval_telemetry": telemetry.model_dump(mode="json"),
    }


def _framework_classification_for_failure(
    category: TechnicalFailureCategory,
) -> FrameworkChangeClassification:
    """Map a technical terminal to its semantically matching change classification."""

    if category == "repeated_framework_failure":
        return "reusable_missing_capability"
    return "job_local_candidate_error"


def _publish_blocked_failure_evidence(
    job_id: str,
    session_id: str,
    state: AutonomyStateV2,
    state_artifact: ApprovalArtifact,
) -> tuple[ApprovalArtifact, ApprovalArtifact]:
    """Publish technical failure and category-aligned classification evidence."""

    boundary, current_budget, _previous_receipt = _approval_boundary_budget(
        job_id,
        session_id,
    )
    root, plan = boundary[0], boundary[1]
    failure_sources = [
        ApprovalArtifact.model_validate(item.model_dump(mode="python"))
        for item in state.provenance[-2:]
    ]
    for artifact in failure_sources:
        validate_approval_artifact(root, artifact)
    failure_id = f"one-prompt-technical-failure-{session_id}"
    from .candidate_validation_service import CANDIDATE_BUDGET_FAILURE_PREFIX

    failure_category: TechnicalFailureCategory = (
        "candidate_budget_exhaustion"
        if (state.terminal_reason or "").startswith(CANDIDATE_BUDGET_FAILURE_PREFIX)
        else "repeated_framework_failure"
    )
    failure = AQV2TechnicalFailureReport(
        contract_id=failure_id,
        failure_id=failure_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=boundary[3],
        producer=_PRODUCER,
        created_at=datetime.now(UTC),
        approval_count_effect="maintains",
        approval_count_justification=(
            "A technical block terminates without creating a user approval request."
        ),
        policy_profile=boundary[5],
        approval_envelope=boundary[9],
        approval_budget=boundary[7],
        category=failure_category,
        current_state=state_artifact,
        failure_evidence=failure_sources,
        automatic_repair_attempted=(current_budget.technical_policy_repairs > 0),
        transient_retry_count=min(current_budget.technical_policy_repairs, 1),
        retry_exhausted=(current_budget.technical_policy_repairs > 0),
    )
    failure_artifact = _write_immutable_model(
        root,
        _approval_root(root, session_id) / "one_prompt" / "technical_failure.json",
        failure,
        artifact_id=failure_id,
        kind="aqv2-technical-failure-report",
    )
    justification_result = publish_framework_change_justification(
        job_id,
        session_id,
        classification=_framework_classification_for_failure(failure_category),
        issue_summary=(
            state.terminal_reason
            or "The current candidate reached a fail-closed technical terminal."
        ),
        evidence_paths=[failure_artifact.path],
        evidence_kinds=[failure_artifact.kind],
        allow_disabled_experimental=True,
    )
    justification_artifact = ApprovalArtifact.model_validate(
        justification_result["justification_artifact"]
    )
    return failure_artifact, justification_artifact


def _ensure_review_terminal_policy_decision(
    job_id: str,
    session_id: str,
    *,
    review_bundle: ApprovalArtifact,
    quality_terminal: ApprovalArtifact,
) -> dict[str, object]:
    """Authorize one exact non-production review terminal without a user prompt."""

    boundary = _load_approval_boundary(job_id, session_id)
    root = boundary[0]
    if boundary[8].approval_mode == "interactive":
        return {
            "status": "legacy_interactive_no_policy_authorization",
            "is_user_approval": False,
            "policy_authorization_created": False,
        }
    decisions_root = _approval_root(root, session_id) / "decisions"
    if os.path.isdir(native_io_path(decisions_root)):
        for path in sorted(decisions_root.glob("*.json")):
            receipt, artifact = _decision_receipt_from_path(root, path)
            if (
                receipt.gate_kind == "review_bundle_terminal"
                and receipt.exact_target_artifact.path == review_bundle.path
                and receipt.exact_target_artifact.sha256 == review_bundle.sha256
                and receipt.outcome == "applied"
            ):
                return {
                    "status": "existing",
                    "receipt": receipt.model_dump(mode="json"),
                    "receipt_artifact": artifact.model_dump(mode="json"),
                }
    canonical_path = root / "analysis" / "scene_spec.json"
    if not os.path.isfile(native_io_path(canonical_path)):
        canonical_path = root / "blender" / "scene.blend"
    eligibility = evaluate_routine_gate_eligibility(
        job_id,
        session_id,
        gate_kind="review_bundle_terminal",
        exact_target_path=review_bundle.path,
        exact_target_kind=review_bundle.kind,
        current_canonical_snapshot_path=canonical_path,
        current_canonical_snapshot_kind="canonical-review-snapshot",
        dependency_paths=[quality_terminal.path],
        dependency_kinds=[quality_terminal.kind],
        allow_disabled_experimental=True,
    )
    if eligibility["eligibility"] != "passed":
        raise PermissionError("quality review bundle failed routine terminal policy")
    report_artifact = ApprovalArtifact.model_validate(eligibility["report_artifact"])
    authorization = authorize_routine_gate(
        job_id,
        session_id,
        eligibility_report_path=report_artifact.path,
        allow_disabled_experimental=True,
    )
    authorization_artifact = ApprovalArtifact.model_validate(
        authorization["authorization_artifact"]
    )
    return publish_policy_decision_receipt(
        job_id,
        session_id,
        policy_authorization_path=authorization_artifact.path,
        canonical_snapshot_after_path=canonical_path,
        canonical_snapshot_after_kind="canonical-review-snapshot",
        outcome="applied",
        action_result_path=review_bundle.path,
        action_result_kind=review_bundle.kind,
        allow_disabled_experimental=True,
    )


def _terminalize_current_state(
    job_id: str,
    session_id: str,
) -> dict[str, object] | None:
    """Map a terminal AQ state to the exact one-prompt terminal evidence shape."""

    root, state, state_artifact = _latest_state_artifact(job_id, session_id)
    if state.next_action != "none":
        return None
    if state.status == "review_required" and state.quality_terminal is not None:
        from .fidelity_terminal_service import (
            BUNDLE_KIND,
            TERMINAL_KIND,
            validate_fidelity_terminal,
        )
        if state.quality_terminal.kind == TERMINAL_KIND:
            from .delivery_service import artifact_for_v2

            fidelity = validate_fidelity_terminal(root, state.quality_terminal)
            review = ApprovalArtifact.model_validate(artifact_for_v2(
                root, root / fidelity.review_bundle.path,
                artifact_id="fidelity-review-bundle", kind=BUNDLE_KIND,
            ).model_dump())
            _ensure_review_terminal_policy_decision(
                job_id, session_id, review_bundle=review,
                quality_terminal=ApprovalArtifact.model_validate(state.quality_terminal.model_dump()),
            )
            return _publish_one_prompt_terminal(
                job_id, session_id, terminal_type="review_bundle", review_bundle=review,
            )
        from .models import QualityTerminalV2

        quality_artifact = ApprovalArtifact.model_validate(
            state.quality_terminal.model_dump(mode="python")
        )
        quality_path = validate_approval_artifact(root, quality_artifact)
        with open(native_io_path(quality_path), "rb") as handle:
            quality = QualityTerminalV2.model_validate_json(handle.read())
        if quality.review_bundle is not None:
            review = ApprovalArtifact.model_validate(
                quality.review_bundle.model_dump(mode="python")
            )
        elif (
            quality.status == "quality_approved"
            and state.provenance
            and state.provenance[-1].kind == "human-quality-review-bundle"
        ):
            human_artifact = AQV2Artifact.model_validate(
                state.provenance[-1].model_dump(mode="python")
            )
            human_review = validate_human_quality_review_bundle_v2(
                root,
                human_artifact,
            )
            if (
                human_review.machine_quality_terminal != state.quality_terminal
                or human_review.source_freeze != state.source_freeze
                or human_review.delivery_plan != state.delivery_plan
            ):
                raise ValueError(
                    "human review terminal differs from the current passed-IQ state"
                )
            review = ApprovalArtifact.model_validate(
                human_artifact.model_dump(mode="python")
            )
        else:
            raise ValueError("review-required AQ terminal has no exact review bundle")
        validate_approval_artifact(root, review)
        _ensure_review_terminal_policy_decision(
            job_id,
            session_id,
            review_bundle=review,
            quality_terminal=quality_artifact,
        )
        return _publish_one_prompt_terminal(
            job_id,
            session_id,
            terminal_type="review_bundle",
            review_bundle=review,
        )
    if state.status in {"completed", "partial"} and state.delivery_terminal is not None:
        delivery = ApprovalArtifact.model_validate(
            state.delivery_terminal.model_dump(mode="python")
        )
        validate_approval_artifact(root, delivery)
        if state.delivery_results and all(
            result.status == "review_only" for result in state.delivery_results
        ):
            return _publish_one_prompt_terminal(
                job_id,
                session_id,
                terminal_type="review_bundle",
                review_bundle=delivery,
            )
        if state.status != "completed" or any(
            result.status != "completed" for result in state.delivery_results
        ):
            failure, justification = _publish_blocked_failure_evidence(
                job_id,
                session_id,
                state,
                state_artifact,
            )
            return _publish_one_prompt_terminal(
                job_id,
                session_id,
                terminal_type="blocked",
                framework_change_justification=justification,
                framework_failure_report=failure,
            )
        return _publish_one_prompt_terminal(
            job_id,
            session_id,
            terminal_type="production_delivery",
            delivery_terminal=delivery,
        )
    if state.status == "cancelled":
        return _publish_one_prompt_terminal(
            job_id,
            session_id,
            terminal_type="cancelled",
        )
    if state.status in {"blocked", "failed"}:
        failure, justification = _publish_blocked_failure_evidence(
            job_id,
            session_id,
            state,
            state_artifact,
        )
        return _publish_one_prompt_terminal(
            job_id,
            session_id,
            terminal_type="blocked",
            framework_change_justification=justification,
            framework_failure_report=failure,
        )
    return None


def _terminalize_pending_escalation(
    job_id: str,
    session_id: str,
) -> dict[str, object] | None:
    """Turn one pending consolidated request into the only user-wait terminal."""

    escalation = get_escalation_status(job_id, session_id)
    if escalation["status"] != "pending":
        return None
    root = job_dir(job_id)
    path = _approval_root(root, session_id) / "escalation" / "request.json"
    artifact = approval_artifact_for(
        root,
        path,
        artifact_id=f"escalation-{session_id}",
        kind="aqv2-consolidated-escalation-request",
    )
    return _publish_one_prompt_terminal(
        job_id,
        session_id,
        terminal_type="genuine_escalation",
        consolidated_escalation=artifact,
    )


def _snapshot_mutable_geometry_policy_source(
    root: Path, session_id: str, source: Path
) -> Path:
    """Freeze current canonical geometry bytes before a policy-authorized replacement."""

    digest = sha256_file(source)
    destination = (
        _approval_root(root, session_id)
        / "canonical_snapshots"
        / f"geometry-{digest}{source.suffix}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_create_once(destination, source.read_bytes())
    return destination


def _geometry_policy_snapshot(
    root: Path, job_id: str, session_id: str | None = None
) -> tuple[Path, str]:
    """Select immutable pre-promotion geometry or the initial reference snapshot."""

    scene_path = root / "analysis" / "scene_spec.json"
    if os.path.isfile(native_io_path(scene_path)):
        return (
            _snapshot_mutable_geometry_policy_source(root, session_id, scene_path)
            if session_id is not None
            else scene_path,
            "canonical-scene-snapshot",
        )
    blend_path = root / "blender" / "scene.blend"
    if os.path.isfile(native_io_path(blend_path)):
        return (
            _snapshot_mutable_geometry_policy_source(root, session_id, blend_path)
            if session_id is not None
            else blend_path,
            "canonical-scene-snapshot",
        )
    return find_reference(job_id), "canonical-reference-snapshot"


def _reconcile_interrupted_policy_authorization(
    job_id: str,
    session_id: str,
    *,
    gate_kind: str,
    exact_target: ApprovalArtifact,
) -> ApprovalArtifact | None:
    """Adopt exact pending/applied geometry authority, or close a stale orphan safely."""

    pending = _current_unconsumed_policy_authorization(job_id, session_id)
    if pending is None:
        if gate_kind in {
            "geometry_candidate_promotion", "structural_candidate_promotion",
            "bounded_parametric_revision",
        }:
            from .approval_policy_service import get_applied_policy_decision_receipt

            root = job_dir(job_id)
            for path in sorted((_approval_root(root, session_id) / "decisions").glob("*.json")):
                decision, _artifact = _decision_receipt_from_path(root, path)
                if (
                    decision.gate_kind == gate_kind
                    and decision.outcome == "applied"
                    and decision.action_result is not None
                    and decision.exact_target_artifact.path == exact_target.path
                    and decision.exact_target_artifact.sha256 == exact_target.sha256
                    and decision.exact_target_artifact.byte_size == exact_target.byte_size
                ):
                    # Exact completed actions are adopted; they never obtain another approval.
                    get_applied_policy_decision_receipt(
                        job_id, session_id,
                        policy_authorization_path=decision.policy_authorization.path,
                        action_result_path=decision.action_result.path,
                    )
                    return decision.policy_authorization
        return None
    authorization, artifact = pending
    same_target = (
        authorization.gate_kind == gate_kind
        and authorization.exact_target_artifact.path == exact_target.path
        and authorization.exact_target_artifact.sha256 == exact_target.sha256
        and authorization.exact_target_artifact.byte_size == exact_target.byte_size
    )
    if same_target:
        return artifact
    publish_policy_decision_receipt(
        job_id,
        session_id,
        policy_authorization_path=artifact.path,
        canonical_snapshot_after_path=authorization.current_canonical_snapshot.path,
        canonical_snapshot_after_kind=authorization.current_canonical_snapshot.kind,
        outcome="technical_failed",
        decision_reasons=[
            "Recovered an interrupted routine action before a different exact target."
        ],
        allow_disabled_experimental=True,
    )
    return None


def _close_failed_policy_authorization(
    job_id: str,
    session_id: str,
    *,
    authorization_artifact: ApprovalArtifact,
    reason: str,
) -> ApprovalArtifact | None:
    """Consume one still-unused authorization and return its technical-failure receipt."""

    pending = _current_unconsumed_policy_authorization(job_id, session_id)
    if pending is None:
        return None
    authorization, artifact = pending
    if artifact != authorization_artifact:
        raise ValueError("technical failure found a different unconsumed authorization")
    result = publish_policy_decision_receipt(
        job_id,
        session_id,
        policy_authorization_path=artifact.path,
        canonical_snapshot_after_path=authorization.current_canonical_snapshot.path,
        canonical_snapshot_after_kind=authorization.current_canonical_snapshot.kind,
        outcome="technical_failed",
        decision_reasons=[reason],
        allow_disabled_experimental=True,
    )
    return ApprovalArtifact.model_validate(result["receipt_artifact"])


def _terminalize_failed_policy_action(
    job_id: str,
    session_id: str,
    *,
    decision_artifact: ApprovalArtifact,
    expected_gate_kind: str,
    expected_next_action: Literal["validate_candidate", "run_integrated_quality"],
    reason: str,
) -> dict[str, object]:
    """Bind a technical policy receipt to one append-only failed AQ base state."""

    root = job_dir(job_id)
    validate_approval_artifact(root, decision_artifact)
    decision = _load_model(root, decision_artifact, AQV2PolicyDecisionReceipt)
    if (
        decision.job_id != job_id
        or decision.session_id != session_id
        or decision.outcome != "technical_failed"
        or decision.gate_kind != expected_gate_kind
        or decision.action_result is not None
        or decision.canonical_snapshot_before.sha256
        != decision.canonical_snapshot_after.sha256
    ):
        raise ValueError("policy technical-failure receipt differs from the failed action")
    return _fail_current_policy_action(
        job_id,
        session_id,
        failure_evidence_path=decision_artifact.path,
        failure_evidence_kind=decision_artifact.kind,
        expected_next_action=expected_next_action,
        reason=reason,
        allow_disabled_experimental=True,
    )


def _advance_geometry_with_policy(
    job_id: str,
    session_id: str,
    state: AutonomyStateV2,
    *,
    quality_submission: QualitySubmissionV2 | dict[str, object] | None,
) -> dict[str, object] | None:
    """Authorize and consume one geometry promotion immediately around its host action."""

    from ..production.controller_executor.models import ControllerResult, PhaseToolProfile

    root = job_dir(job_id)
    if not state.provenance or not state.provenance[-1].path.endswith("/result.json"):
        return None
    result_artifact = state.provenance[-1]
    result_path = root / result_artifact.path
    with open(native_io_path(result_path), "rb") as handle:
        result = ControllerResult.model_validate_json(handle.read())
    profile_path = root / result.tool_profile.path
    with open(native_io_path(profile_path), "rb") as handle:
        profile = PhaseToolProfile.model_validate_json(handle.read())
    if profile.profile_id != "geometry_authoring":
        return None
    from .candidate_validation_service import (
        CandidateBudgetExhausted,
        preflight_geometry_candidate_budget_v2,
    )
    from .controller_bridge import _session_bundle
    from .models import RootAuthorizationV2

    bundle = _session_bundle(job_id, session_id)
    if bundle[4] != state:
        raise ValueError("geometry budget preflight state changed")
    base_plan, budget = bundle[2:4]
    authorization = _load_model(root, base_plan.root_authorization, RootAuthorizationV2)
    try:
        preflight_geometry_candidate_budget_v2(
            root=root, plan=base_plan, budget=budget, state=state, authorization=authorization,
        )
    except CandidateBudgetExhausted as exc:
        return _fail_current_policy_action(
            job_id, session_id, failure_evidence_path=result_artifact.path,
            failure_evidence_kind=result_artifact.kind,
            expected_next_action="validate_candidate", reason=exc.terminal_reason(),
            allow_disabled_experimental=True,
        )
    canonical_before_path, canonical_before_kind = _geometry_policy_snapshot(
        root,
        job_id,
        session_id,
    )
    dependencies = [result.request, result.tool_profile, *result.outputs]
    from .quality_revision_service import active_reentry

    base_plan = _session_bundle(job_id, session_id)[2]
    reentry = active_reentry(root, base_plan, state)
    promotion_gate = (reentry.policy_gate if reentry is not None
                      else "geometry_candidate_promotion")
    exact_target = approval_artifact_for(
        root,
        result_path,
        artifact_id="geometry-policy-target",
        kind="controller-result",
    )
    authorization_artifact = _reconcile_interrupted_policy_authorization(
        job_id,
        session_id,
        gate_kind=promotion_gate,
        exact_target=exact_target,
    )
    if authorization_artifact is None:
        eligibility = evaluate_routine_gate_eligibility(
            job_id,
            session_id,
            gate_kind=promotion_gate,
            exact_target_path=result_path,
            exact_target_kind="controller-result",
            current_canonical_snapshot_path=canonical_before_path,
            current_canonical_snapshot_kind=canonical_before_kind,
            dependency_paths=[item.path for item in dependencies],
            dependency_kinds=[item.role for item in dependencies],
            allow_disabled_experimental=True,
        )
        if eligibility["eligibility"] != "passed":
            raise PermissionError(
                "geometry candidate failed deterministic policy eligibility"
            )
        report_artifact = ApprovalArtifact.model_validate(eligibility["report_artifact"])
        authorization = authorize_routine_gate(
            job_id,
            session_id,
            eligibility_report_path=report_artifact.path,
            allow_disabled_experimental=True,
        )
        authorization_artifact = ApprovalArtifact.model_validate(
            authorization["authorization_artifact"]
        )
    try:
        result_payload = _run_autonomy_v2_with_policy(
            job_id,
            session_id,
            max_actions=1,
            quality_submission=quality_submission,
            allow_disabled_experimental=True,
            policy_authorization_path=authorization_artifact.path,
        )
    except Exception as exc:
        failure_reason = (
            exc.terminal_reason() if isinstance(exc, CandidateBudgetExhausted)
            else "Geometry policy action ended in an ordinary technical exception."
        )
        decision_artifact = _close_failed_policy_authorization(
            job_id,
            session_id,
            authorization_artifact=authorization_artifact,
            reason=failure_reason,
        )
        if decision_artifact is not None:
            _terminalize_failed_policy_action(
                job_id,
                session_id,
                decision_artifact=decision_artifact,
                expected_gate_kind=promotion_gate,
                expected_next_action="validate_candidate",
                reason=failure_reason,
            )
        raise
    actions = result_payload.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise RuntimeError("geometry policy execution did not return one exact action")
    action = actions[0]
    if not isinstance(action, dict) or "routine_policy_decision" not in action:
        raise RuntimeError("geometry promotion produced no PolicyDecisionReceipt")
    return result_payload


def _advance_quality_with_policy(
    job_id: str,
    session_id: str,
    state: AutonomyStateV2,
    *,
    quality_submission: QualitySubmissionV2 | dict[str, object] | None,
) -> dict[str, object] | None:
    """Authorize and consume one passed IQ 0.2 acceptance around its host action."""

    if quality_submission is None:
        return None
    from ..integrated_quality.v02_models import IntegratedQualityReportV02

    submission = (
        quality_submission
        if isinstance(quality_submission, QualitySubmissionV2)
        else QualitySubmissionV2.model_validate(quality_submission)
    )
    root = job_dir(job_id)
    from .controller_bridge import _session_bundle
    from .quality_revision_service import validate_final_quality_submission

    validate_final_quality_submission(
        root, _session_bundle(job_id, session_id)[2], state, submission
    )
    report_artifact = ApprovalArtifact.model_validate(
        submission.integrated_quality_report.model_dump(mode="python")
    )
    report_path = validate_approval_artifact(root, report_artifact)
    with open(native_io_path(report_path), "rb") as handle:
        report = IntegratedQualityReportV02.model_validate_json(handle.read())
    if report.outcome != "passed":
        return None
    canonical_path = root / "analysis" / "scene_spec.json"
    if not os.path.isfile(native_io_path(canonical_path)):
        canonical_path = root / "blender" / "scene.blend"
    dependencies = [
        ApprovalArtifact.model_validate(item.model_dump(mode="python"))
        for item in submission.quality_evidence
    ]
    authorization_artifact = _reconcile_interrupted_policy_authorization(
        job_id,
        session_id,
        gate_kind="iq_quality_acceptance",
        exact_target=report_artifact,
    )
    if authorization_artifact is None:
        eligibility = evaluate_routine_gate_eligibility(
            job_id,
            session_id,
            gate_kind="iq_quality_acceptance",
            exact_target_path=report_artifact.path,
            exact_target_kind=report_artifact.kind,
            current_canonical_snapshot_path=canonical_path,
            current_canonical_snapshot_kind="canonical-quality-snapshot",
            dependency_paths=[item.path for item in dependencies],
            dependency_kinds=[item.kind for item in dependencies],
            allow_disabled_experimental=True,
        )
        if eligibility["eligibility"] != "passed":
            raise PermissionError("IQ 0.2 report failed deterministic policy acceptance")
        eligibility_artifact = ApprovalArtifact.model_validate(
            eligibility["report_artifact"]
        )
        authorization = authorize_routine_gate(
            job_id,
            session_id,
            eligibility_report_path=eligibility_artifact.path,
            allow_disabled_experimental=True,
        )
        authorization_artifact = ApprovalArtifact.model_validate(
            authorization["authorization_artifact"]
        )
    try:
        result_payload = _run_autonomy_v2_with_policy(
            job_id,
            session_id,
            max_actions=1,
            quality_submission=submission,
            allow_disabled_experimental=True,
            policy_authorization_path=authorization_artifact.path,
        )
    except Exception:
        failure_reason = "IQ policy action ended in an ordinary technical exception."
        decision_artifact = _close_failed_policy_authorization(
            job_id,
            session_id,
            authorization_artifact=authorization_artifact,
            reason=failure_reason,
        )
        if decision_artifact is not None:
            _terminalize_failed_policy_action(
                job_id,
                session_id,
                decision_artifact=decision_artifact,
                expected_gate_kind="iq_quality_acceptance",
                expected_next_action="run_integrated_quality",
                reason=failure_reason,
            )
        raise
    _root, after, _after_artifact = _latest_state_artifact(job_id, session_id)
    if after.sequence <= state.sequence or after.quality_terminal is None:
        raise RuntimeError("IQ policy action did not publish its exact quality terminal")
    actions = result_payload.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise RuntimeError("quality policy execution did not return one exact action")
    action = actions[0]
    if not isinstance(action, dict) or "routine_policy_decision" not in action:
        raise RuntimeError("quality acceptance produced no PolicyDecisionReceipt")
    return result_payload


def get_one_prompt_status(job_id: str, session_id: str) -> dict[str, object]:
    """Reconstruct one-prompt state without spawning work or mutating the session."""

    root, plan, plan_artifact, _boundary = _load_one_prompt_plan(job_id, session_id)
    terminal = _load_existing_one_prompt_terminal(root, session_id)
    base = get_autonomy_v2_status(job_id, session_id)
    escalation = get_escalation_status(job_id, session_id)
    derived_status = "terminal" if terminal is not None else "running"
    if terminal is None and base["state"]["status"] == "waiting_for_controller":
        derived_status = "waiting_for_controller"
    if terminal is None and escalation["status"] == "pending":
        derived_status = "genuine_escalation"
    fidelity = None
    if terminal is None and base["state"]["next_action"] == "run_integrated_quality":
        from .controller_bridge import _session_bundle
        from .quality_revision_service import quality_revision_boundary

        bundle = _session_bundle(job_id, session_id)
        fidelity = quality_revision_boundary(root, bundle[2], bundle[4])
        if fidelity is not None and fidelity["next_action"] != "quality_ready":
            derived_status = "waiting_for_reference_fidelity_review"
    return {
        "status": derived_status,
        "profile_status": "disabled_experimental",
        "job_id": job_id,
        "session_id": session_id,
        "one_prompt_plan": plan.model_dump(mode="json"),
        "one_prompt_plan_artifact": plan_artifact.model_dump(mode="json"),
        "base_autonomy": base,
        "approval_envelope": get_approval_envelope_status(job_id, session_id),
        "escalation": escalation,
        "terminal": None if terminal is None else terminal[0].model_dump(mode="json"),
        **({"reference_fidelity": fidelity} if fidelity is not None else {}),
        "resume_same_state_budget_assignment": True,
        "repository_creates_codex_task": False,
        "app_close_background_execution": False,
    }


def run_one_prompt(
    job_id: str,
    session_id: str,
    *,
    max_actions: int = 32,
    quality_submission: QualitySubmissionV2 | dict[str, object] | None = None,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Run bounded actions and publish terminal companions even on the final or failed action."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ one-prompt supervisor remains disabled_experimental")
    if isinstance(max_actions, bool) or not isinstance(max_actions, int):
        raise TypeError("one-prompt max_actions must be an integer")
    if not 1 <= max_actions <= 128:
        raise ValueError("one-prompt max_actions must be within [1, 128]")
    root, plan, _plan_artifact, _boundary = _load_one_prompt_plan(job_id, session_id)
    existing = _load_existing_one_prompt_terminal(root, session_id)
    if existing is not None:
        return get_one_prompt_status(job_id, session_id)
    escalated = _terminalize_pending_escalation(job_id, session_id)
    if escalated is not None:
        return escalated
    actions: list[dict[str, object]] = []
    for _index in range(min(max_actions, plan.global_action_limit)):
        _root, state, _state_artifact = _latest_state_artifact(job_id, session_id)
        terminal = _terminalize_current_state(job_id, session_id)
        if terminal is not None:
            terminal["actions"] = actions
            return terminal
        if state.next_action == "run_integrated_quality":
            from .controller_bridge import _session_bundle
            from .quality_revision_service import quality_revision_boundary

            base_plan = _session_bundle(job_id, session_id)[2]
            boundary = quality_revision_boundary(root, base_plan, state)
            if boundary is not None and boundary["next_action"] == "review_required":
                from .fidelity_terminal_service import publish_fidelity_review_terminal

                actions.append(publish_fidelity_review_terminal(job_id, session_id))
                terminal = _terminalize_current_state(job_id, session_id)
                if terminal is None:
                    raise RuntimeError("fidelity review terminal was not published")
                terminal["actions"] = actions
                return terminal
            if boundary is not None and boundary["next_action"] != "quality_ready":
                return {
                    "status": "waiting_for_reference_fidelity_review", "job_id": job_id,
                    "session_id": session_id, "actions": actions,
                    "state": state.model_dump(mode="json"), "reference_fidelity": boundary,
                    "routine_user_approval_wait": False,
                    "repository_creates_codex_task": False,
                    "app_close_background_execution": False,
                }
        policy_mode = plan.approval_mode != "interactive"
        try:
            if policy_mode and state.next_action == "validate_candidate":
                policy_result = _advance_geometry_with_policy(
                    job_id,
                    session_id,
                    state,
                    quality_submission=quality_submission,
                )
                if policy_result is not None:
                    actions.append(policy_result)
                    continue
            if policy_mode and state.next_action == "run_integrated_quality":
                policy_result = _advance_quality_with_policy(
                    job_id,
                    session_id,
                    state,
                    quality_submission=quality_submission,
                )
                if policy_result is not None:
                    actions.append(policy_result)
                    continue
            if policy_mode and state.next_action == "await_v07_approval":
                from .delivery_policy_adapter import (
                    execute_policy_authorized_delivery_boundary_v2,
                )

                delivery_result = execute_policy_authorized_delivery_boundary_v2(
                    job_id,
                    session_id,
                    allow_disabled_experimental=True,
                )
                actions.append(delivery_result)
                continue
            result = run_autonomy_v2(
                job_id,
                session_id,
                max_actions=1,
                quality_submission=quality_submission,
                allow_disabled_experimental=True,
            )
        except Exception:
            # Publish only an already-terminal base state; never retry the failed action.
            _terminalize_current_state(job_id, session_id)
            raise
        actions.append(result)
        after = AutonomyStateV2.model_validate_json(json.dumps(result["state"]))
        if after.next_action == "execute_controller" or result["stop_reason"] in {
            "waiting_for_controller",
            "waiting_for_integrated_quality_submission",
            "waiting_for_integrated_quality_submission_recovery",
        }:
            stop_status = (
                "waiting_for_controller"
                if after.next_action == "execute_controller"
                else str(result["stop_reason"])
            )
            return {
                "status": stop_status,
                "job_id": job_id,
                "session_id": session_id,
                "actions": actions,
                "state": after.model_dump(mode="json"),
                "routine_user_approval_wait": plan.routine_approval_wait_allowed,
                "repository_creates_codex_task": False,
                "app_close_background_execution": False,
            }
    terminal = _terminalize_current_state(job_id, session_id)
    if terminal is not None:
        terminal["actions"] = actions
        return terminal
    return {
        "status": "global_action_slice_exhausted",
        "job_id": job_id,
        "session_id": session_id,
        "actions": actions,
        "state": get_autonomy_v2_status(job_id, session_id)["state"],
        "routine_user_approval_wait": plan.routine_approval_wait_allowed,
    }


def resume_one_prompt(
    job_id: str,
    session_id: str,
    *,
    max_actions: int = 32,
    quality_submission: QualitySubmissionV2 | dict[str, object] | None = None,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Resume the same immutable plan, state, budget, and pending controller assignment."""

    return run_one_prompt(
        job_id,
        session_id,
        max_actions=max_actions,
        quality_submission=quality_submission,
        allow_disabled_experimental=allow_disabled_experimental,
    )


def cancel_one_prompt(
    job_id: str,
    session_id: str,
    *,
    reason: str,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Cancel future current-task actions and retain all immutable evidence."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ one-prompt supervisor remains disabled_experimental")
    _load_one_prompt_plan(job_id, session_id)
    cancellation = cancel_autonomy_v2(job_id, session_id, reason=reason)
    terminal = _publish_one_prompt_terminal(
        job_id,
        session_id,
        terminal_type="cancelled",
    )
    return {"cancellation": cancellation, **terminal}
