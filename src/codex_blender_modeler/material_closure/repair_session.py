"""Pure safeguards for additive material-only repair sessions and transient retries."""

from __future__ import annotations

from .models import (
    MATERIAL_REPAIR_PREAPPROVAL_STEPS,
    MATERIAL_REPAIR_REQUIRED_STEPS,
    MaterialRepairSessionPlan,
    MaterialRepairSourceBinding,
)


def verify_material_repair_geometry(
    source: MaterialRepairSourceBinding,
    *,
    scene_spec_sha256: str,
    modeling_plan_sha256: str,
    blend_sha256: str,
) -> None:
    """Fail closed when a proposed material repair no longer matches reusable geometry."""

    expected = (
        source.scene_spec.sha256,
        source.modeling_plan.sha256,
        source.blend.sha256,
    )
    observed = (scene_spec_sha256, modeling_plan_sha256, blend_sha256)
    if observed != expected:
        raise ValueError("material repair geometry source binding is stale")


def validate_material_repair_session(
    plan: MaterialRepairSessionPlan,
    source: MaterialRepairSourceBinding,
) -> None:
    """Require exact session/source binding and prohibit geometry writes or migration."""

    validate_material_repair_session_shape(plan)
    if plan.source_session_id != source.source_session_id:
        raise ValueError("repair plan source session differs from source binding")
    if plan.session_id != source.session_id:
        raise ValueError("repair plan and source binding target different sessions")
    if plan.job_id != source.job_id or plan.workflow_id != source.workflow_id:
        raise ValueError("repair plan and source binding target different workflows")
    request_prefix = f"production/material_closure/{plan.session_id}/preflights/"
    if (
        not plan.preflight_request.path.startswith(request_prefix)
        or not plan.preflight_request.path.endswith("/request.json")
    ):
        raise ValueError("repair preflight request belongs to another material session")


def material_repair_automatic_steps(
    plan: MaterialRepairSessionPlan,
) -> tuple[str, ...]:
    """Return only the safe preapproval prefix executable by an unattended repair run."""

    validate_material_repair_session_shape(plan)
    return MATERIAL_REPAIR_PREAPPROVAL_STEPS


def validate_material_repair_session_shape(plan: MaterialRepairSessionPlan) -> None:
    """Reassert the immutable no-write and approval-pending boundary on a loaded plan."""

    if tuple(plan.required_steps) != MATERIAL_REPAIR_REQUIRED_STEPS:
        raise ValueError("material repair plan step order is incomplete or changed")
    if plan.run_stop_boundary != "approval_pending":
        raise ValueError("material repair automatic execution must stop approval-pending")
    prohibited_flags = (
        plan.geometry_write_allowed,
        plan.automatic_migration,
        plan.old_session_resumable,
        plan.synthetic_authority_allowed,
        plan.synthetic_approval_allowed,
        plan.controller_before_approval_allowed,
        plan.canonical_write_before_approval_allowed,
        plan.destination_write_allowed,
    )
    if any(prohibited_flags):
        raise ValueError("material repair plan grants prohibited unattended authority")


def validate_material_repair_preapproval_outcome(
    plan: MaterialRepairSessionPlan,
    *,
    attempt_status: str,
    approval_consumption_count: int,
    controller_invocation_count: int,
    canonical_write_count: int,
) -> None:
    """Require an automatic repair run to stop before approval consumption or mutation."""

    validate_material_repair_session_shape(plan)
    if attempt_status != "approval_pending":
        raise ValueError("material repair automatic run did not stop approval-pending")
    if min(
        approval_consumption_count,
        controller_invocation_count,
        canonical_write_count,
    ) < 0:
        raise ValueError("material repair effect counters cannot be negative")
    if any(
        (
            approval_consumption_count,
            controller_invocation_count,
            canonical_write_count,
        )
    ):
        raise ValueError("preapproval repair run performed an unauthorized side effect")


def transient_controller_retry_allowed(
    *,
    process_ended_before_output: bool,
    timeout_before_canonical_write: bool,
    request_bytes_unchanged: bool,
    candidate_bytes_unchanged: bool,
    outcome_known: bool,
    retries_used: int,
    retry_limit: int,
) -> bool:
    """Allow at most one same-closure retry only for an exact known pre-output failure."""

    failure_is_pre_output = process_ended_before_output or timeout_before_canonical_write
    return (
        failure_is_pre_output
        and request_bytes_unchanged
        and candidate_bytes_unchanged
        and outcome_known
        and retries_used < min(retry_limit, 1)
    )


__all__ = [
    "material_repair_automatic_steps",
    "transient_controller_retry_allowed",
    "validate_material_repair_preapproval_outcome",
    "validate_material_repair_session",
    "validate_material_repair_session_shape",
    "verify_material_repair_geometry",
]
