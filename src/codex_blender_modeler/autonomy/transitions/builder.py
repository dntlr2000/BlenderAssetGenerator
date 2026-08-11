"""Pure AQ 0.1 transition builders extracted behind the legacy service facade."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..authorization import canonical_digest
from ..models import (
    AutonomyArtifact,
    AutonomyIterationReceipt,
    AutonomyState,
    BudgetUsage,
)


def build_transition_state(
    before: AutonomyState,
    *,
    before_artifact: AutonomyArtifact,
    previous_receipt: AutonomyArtifact | None,
    action: str,
    sequence: int,
    budget_usage: BudgetUsage,
    update: dict[str, Any],
    observed_at: datetime,
) -> AutonomyState:
    """Build the next strict v1 state without filesystem or Blender side effects."""

    state_values = {
        **before.model_dump(mode="python"),
        **update,
        "contract_id": f"state-{before.session_id}-{sequence:04d}",
        "input_sha256": before_artifact.sha256,
        "source_fingerprint": canonical_digest(
            {
                "before": before_artifact.sha256,
                "previous_receipt": previous_receipt.sha256 if previous_receipt else None,
                "action": action,
                "sequence": sequence,
            }
        ),
        "provenance": [before_artifact],
        "created_at": observed_at,
        "action_sequence": sequence,
        "budget_usage": budget_usage,
        "receipt_chain_head_before_state_sha256": (
            previous_receipt.sha256 if previous_receipt else None
        ),
        "observed_at": observed_at,
    }
    return AutonomyState.model_validate(state_values)


def build_transition_receipt(
    before: AutonomyState,
    state: AutonomyState,
    *,
    before_artifact: AutonomyArtifact,
    state_artifact: AutonomyArtifact,
    previous_receipt: AutonomyArtifact | None,
    action: str,
    sequence: int,
    budget_usage: BudgetUsage,
    created_at: datetime,
    candidate_evaluation: AutonomyArtifact | None = None,
    policy_authorization: AutonomyArtifact | None = None,
    candidate_promotion_receipt: AutonomyArtifact | None = None,
    material_promotion_receipt: AutonomyArtifact | None = None,
    host_attempt_evidence: list[AutonomyArtifact] | None = None,
    canonical_changed: bool = False,
    rollback_performed: bool = False,
    outcome: str = "advanced",
    failure_fingerprint: str | None = None,
) -> AutonomyIterationReceipt:
    """Build the exact legacy receipt while preserving its producer and hash semantics."""

    supporting = [
        artifact
        for artifact in (
            candidate_evaluation,
            policy_authorization,
            candidate_promotion_receipt,
            material_promotion_receipt,
        )
        if artifact is not None
    ]
    supporting.extend(host_attempt_evidence or [])
    return AutonomyIterationReceipt(
        contract_id=f"receipt-{before.session_id}-{sequence:04d}",
        receipt_id=f"receipt-{before.session_id}-{sequence:04d}",
        job_id=before.job_id,
        workflow_id=before.workflow_id,
        dispatch_id=before.dispatch_id,
        input_sha256=before_artifact.sha256,
        source_fingerprint=canonical_digest(
            {
                "before": before_artifact.sha256,
                "after": state_artifact.sha256,
                "previous": previous_receipt.sha256 if previous_receipt else None,
            }
        ),
        producer="codex_blender_modeler.autonomy.service",
        producer_version="0.1.0",
        provenance=[before_artifact, state_artifact, *supporting],
        created_at=created_at,
        session_id=before.session_id,
        sequence=sequence,
        previous_receipt_sha256=previous_receipt.sha256 if previous_receipt else None,
        action=action,  # type: ignore[arg-type]
        state_before=before_artifact,
        state_after=state_artifact,
        budget_before=before.budget_usage,
        budget_after=budget_usage,
        candidate_evaluation=candidate_evaluation,
        policy_authorization=policy_authorization,
        candidate_promotion_receipt=candidate_promotion_receipt,
        material_promotion_receipt=material_promotion_receipt,
        host_attempt_evidence=host_attempt_evidence or [],
        canonical_changed=canonical_changed,
        rollback_performed=rollback_performed,
        outcome=outcome,  # type: ignore[arg-type]
        failure_fingerprint=failure_fingerprint,
    )
