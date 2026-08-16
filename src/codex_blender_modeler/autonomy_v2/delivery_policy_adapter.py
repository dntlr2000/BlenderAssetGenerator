"""Additive AQ v2 policy-authority adapter for unchanged V0.7 delivery reviews."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import native_io_path
from .approval_models import ApprovalArtifact
from .approval_policy_service import (
    authorize_routine_gate,
    evaluate_routine_gate_eligibility,
    publish_policy_decision_receipt,
)
from .delivery_executor import execute_policy_authorized_delivery_request_v2
from .delivery_service import (
    artifact_for_v2,
    publish_delivery_terminal,
    validate_delivery_terminal_v2,
    validate_v2_artifact,
)
from .models import (
    AQV2Artifact,
    DeliveryPlan,
    DeliveryResult,
    DeliveryReviewBinding,
)
from .supervisor_service import (
    _consume_action_budget,
    _session_bundle,
    _validate_optional_codex_image_material_terminal,
    _write_next_state,
)
from .transitions import transition_state


def _aq_artifact(value: ApprovalArtifact) -> AQV2Artifact:
    """Project one exact approval artifact into the existing AQ v2 artifact vocabulary."""

    return AQV2Artifact.model_validate(value.model_dump(mode="python"))


def _load_delivery_boundary(
    root: Path,
    state_delivery_plan: AQV2Artifact,
    session_id: str,
) -> tuple[DeliveryPlan, AQV2Artifact | None, DeliveryReviewBinding | None]:
    """Load a pending plan and its V0.7 review only when portable output exists."""

    plan_path = validate_v2_artifact(root, state_delivery_plan)
    with open(native_io_path(plan_path), "rb") as handle:
        delivery = DeliveryPlan.model_validate_json(handle.read())
    portable = any(
        request.profile.profile_id != "review_only" for request in delivery.requests
    )
    review_path = (
        root / "production" / "autonomy_v2" / session_id / "delivery_reviews.json"
    )
    if not portable:
        if os.path.exists(native_io_path(review_path)):
            raise ValueError("review-only policy delivery has an unexpected V0.7 review")
        return delivery, None, None
    review_artifact = artifact_for_v2(
        root,
        review_path,
        artifact_id=f"review-binding-{delivery.plan_id}",
        kind="delivery-review-binding",
    )
    with open(native_io_path(validate_v2_artifact(root, review_artifact)), "rb") as handle:
        review = DeliveryReviewBinding.model_validate_json(handle.read())
    if (
        review.delivery_plan != state_delivery_plan
        or review.source_freeze != delivery.source_freeze
        or review.session_id != session_id
    ):
        raise ValueError("delivery policy adapter received a stale review binding")
    return delivery, review_artifact, review


def _authorize_exact_gate(
    job_id: str,
    session_id: str,
    *,
    gate_kind: str,
    target: AQV2Artifact,
    canonical: AQV2Artifact,
    dependencies: list[AQV2Artifact],
) -> ApprovalArtifact:
    """Evaluate and issue one exact host policy authorization for a delivery gate."""

    eligibility = evaluate_routine_gate_eligibility(
        job_id,
        session_id,
        gate_kind=gate_kind,  # type: ignore[arg-type]
        exact_target_path=target.path,
        exact_target_kind=target.kind,
        current_canonical_snapshot_path=canonical.path,
        current_canonical_snapshot_kind=canonical.kind,
        dependency_paths=[item.path for item in dependencies],
        dependency_kinds=[item.kind for item in dependencies],
        allow_disabled_experimental=True,
    )
    if eligibility["eligibility"] != "passed":
        raise PermissionError(
            f"delivery policy eligibility failed: {eligibility['report']['forbidden_conditions']}"
        )
    report = ApprovalArtifact.model_validate(eligibility["report_artifact"])
    authorization = authorize_routine_gate(
        job_id,
        session_id,
        eligibility_report_path=report.path,
        allow_disabled_experimental=True,
    )
    return ApprovalArtifact.model_validate(authorization["authorization_artifact"])


def _consume_delivery_authorization(
    job_id: str,
    session_id: str,
    *,
    authorization: ApprovalArtifact,
    canonical: AQV2Artifact,
    result: AQV2Artifact | None,
    outcome: str,
) -> dict[str, object]:
    """Publish one single-use delivery policy decision while canonical source stays frozen."""

    return publish_policy_decision_receipt(
        job_id,
        session_id,
        policy_authorization_path=authorization.path,
        canonical_snapshot_after_path=canonical.path,
        canonical_snapshot_after_kind=canonical.kind,
        outcome=outcome,
        action_result_path=None if result is None else result.path,
        action_result_kind=None if result is None else result.kind,
        allow_disabled_experimental=True,
    )


def execute_policy_authorized_delivery_boundary_v2(
    job_id: str,
    session_id: str,
    *,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Complete a pending AQ delivery using policy authority or fail-safe results only."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ delivery policy adapter remains disabled_experimental")
    root, session_root, _plan, _budget, _state, _artifact = _session_bundle(
        job_id,
        session_id,
    )
    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-policy-delivery",
        ttl_seconds=3600,
    ):
        root, session_root, plan, budget, state, _state_artifact = _session_bundle(
            job_id,
            session_id,
        )
        if state.next_action != "await_v07_approval" or state.delivery_plan is None:
            raise PermissionError("AQ session is not at the portable delivery boundary")
        _validate_optional_codex_image_material_terminal(
            root=root,
            session_root=session_root,
        )
        delivery, review_artifact, review = _load_delivery_boundary(
            root,
            state.delivery_plan,
            session_id,
        )
        review_by_id = (
            {} if review is None else {item.delivery_id: item for item in review.entries}
        )
        results: list[DeliveryResult] = []
        policy_receipts: list[dict[str, object]] = []
        for request in delivery.requests:
            if request.profile.profile_id == "review_only":
                results.append(
                    DeliveryResult(
                        delivery_id=request.delivery_id,
                        profile_id="review_only",
                        status="review_only",
                        source_freeze_sha256=delivery.source_freeze.sha256,
                        production_ready=False,
                    )
                )
                continue
            if review_artifact is None:
                raise ValueError("portable policy delivery has no V0.7 review binding")
            entry = review_by_id.get(request.delivery_id)
            if entry is None:
                raise ValueError("portable request has no exact V0.7 review entry")
            optimization_authorization = _authorize_exact_gate(
                job_id,
                session_id,
                gate_kind="optimization_plan_authorization",
                target=entry.optimization_plan,
                canonical=delivery.source_freeze,
                dependencies=[delivery.source_freeze],
            )
            result = execute_policy_authorized_delivery_request_v2(
                job_root=root,
                delivery_plan_artifact=state.delivery_plan,
                delivery_review_artifact=review_artifact,
                delivery_id=request.delivery_id,
                policy_authorization=_aq_artifact(optimization_authorization),
            )
            results.append(result)
            optimization_result = None
            if request.run_id is not None:
                completed_plan_path = (
                    root
                    / "optimization"
                    / "runs"
                    / request.run_id
                    / "optimization_plan.json"
                )
                if os.path.isfile(native_io_path(completed_plan_path)):
                    optimization_result = artifact_for_v2(
                        root,
                        completed_plan_path,
                        artifact_id=f"{request.delivery_id}-completed-optimization-plan",
                        kind="optimization-plan-completion",
                    )
            policy_receipts.append(
                _consume_delivery_authorization(
                    job_id,
                    session_id,
                    authorization=optimization_authorization,
                    canonical=delivery.source_freeze,
                    result=(optimization_result if result.status == "completed" else None),
                    outcome="applied" if result.status == "completed" else "technical_failed",
                )
            )
            if result.status != "completed":
                continue
            if result.package_manifest is None or result.roundtrip_validation is None:
                raise RuntimeError("completed delivery omitted package acknowledgement evidence")
            package_authorization = _authorize_exact_gate(
                job_id,
                session_id,
                gate_kind="package_acknowledgement",
                target=result.package_manifest,
                canonical=delivery.source_freeze,
                dependencies=[result.roundtrip_validation],
            )
            policy_receipts.append(
                _consume_delivery_authorization(
                    job_id,
                    session_id,
                    authorization=package_authorization,
                    canonical=delivery.source_freeze,
                    result=result.package_manifest,
                    outcome="applied",
                )
            )
        if state.quality_terminal is None:
            raise ValueError("delivery-pending state has no quality terminal")
        terminal, terminal_artifact = publish_delivery_terminal(
            job_root=root,
            quality_terminal_artifact=state.quality_terminal,
            delivery_plan_artifact=state.delivery_plan,
            delivery_review_artifact=review_artifact,
            results=results,
        )
        if validate_delivery_terminal_v2(root, terminal_artifact) != terminal:
            raise ValueError("policy delivery terminal differs from exact persisted evidence")
        if terminal.outcome == "review_only":
            review_authorization = _authorize_exact_gate(
                job_id,
                session_id,
                gate_kind="review_bundle_terminal",
                target=terminal_artifact,
                canonical=delivery.source_freeze,
                dependencies=[state.quality_terminal, state.delivery_plan],
            )
            policy_receipts.append(
                _consume_delivery_authorization(
                    job_id,
                    session_id,
                    authorization=review_authorization,
                    canonical=delivery.source_freeze,
                    result=terminal_artifact,
                    outcome="applied",
                )
            )
        delivery_run_count = sum(
            request.profile.profile_id != "review_only" for request in delivery.requests
        )
        usage = _consume_action_budget(
            state.budget_usage,
            budget,
            delivery_runs=delivery_run_count,
        )
        next_state = transition_state(
            state,
            event="delivery_finished",
            evidence=terminal_artifact,
            created_at=datetime.now(UTC),
            delivery_terminal=terminal_artifact,
            delivery_results=terminal.results,
            budget_usage=usage,
            reason=f"policy delivery terminal outcome: {terminal.outcome}",
        )
        next_artifact = _write_next_state(root, session_root, next_state)
        return {
            "advanced": True,
            "outcome": terminal.outcome,
            "next_action": "none",
            "delivery_terminal": terminal_artifact.model_dump(mode="json"),
            "delivery_results": [item.model_dump(mode="json") for item in terminal.results],
            "policy_decision_receipts": policy_receipts,
            "state": next_state.model_dump(mode="json"),
            "state_artifact": next_artifact.model_dump(mode="json"),
            "user_optimization_approval_created": False,
            "policy_authorization_is_user_approval": False,
            "destination_project_write": False,
        }
