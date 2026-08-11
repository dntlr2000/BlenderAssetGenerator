"""Pure AQ v2 state transitions kept independent from filesystem and Blender effects."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from ..blender_artifacts import stable_json_digest
from .models import AQV2Artifact, AutonomyStateV2, BudgetUsageV2, DeliveryResult

TransitionEvent = Literal[
    "reference_ready",
    "controller_required",
    "controller_output_ready",
    "candidate_validated",
    "material_candidate_validated",
    "quality_passed",
    "quality_nonpassing",
    "delivery_planned",
    "delivery_finished",
    "blocked",
    "failed",
    "cancelled",
]

_ALLOWED_EVENTS_BY_BOUNDARY: dict[tuple[str, str, str], frozenset[TransitionEvent]] = {
    ("planned", "planned", "collect_reference"): frozenset(
        {"reference_ready", "blocked", "failed", "cancelled"}
    ),
    ("authoring", "running", "execute_controller"): frozenset(
        {
            "controller_required",
            "controller_output_ready",
            "blocked",
            "failed",
            "cancelled",
        }
    ),
    ("authoring", "waiting_for_controller", "execute_controller"): frozenset(
        {
            "controller_required",
            "controller_output_ready",
            "blocked",
            "failed",
            "cancelled",
        }
    ),
    ("authoring", "running", "validate_candidate"): frozenset(
        {
            "candidate_validated",
            "material_candidate_validated",
            "blocked",
            "failed",
            "cancelled",
        }
    ),
    ("quality", "running", "run_integrated_quality"): frozenset(
        {"quality_passed", "quality_nonpassing", "blocked", "failed", "cancelled"}
    ),
    ("quality", "quality_approved", "plan_delivery"): frozenset(
        {"delivery_planned", "blocked", "failed", "cancelled"}
    ),
    ("delivery", "delivery_pending", "await_v07_approval"): frozenset(
        {"delivery_finished", "blocked", "failed", "cancelled"}
    ),
}


def validate_initial_state(state: AutonomyStateV2) -> None:
    """Recompute the exact planner-owned sequence-zero state envelope."""

    expected = AutonomyStateV2(
        contract_id=f"state-{state.session_id}-0000",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
        input_sha256=stable_json_digest(
            {"plan": state.plan.sha256, "sequence": 0}
        ),
        source_fingerprint=stable_json_digest(
            {"plan": state.plan.sha256, "status": "planned"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[state.plan],
        created_at=state.created_at,
        state_id=f"state-{state.session_id}-0000",
        plan=state.plan,
        sequence=0,
        phase="planned",
        status="planned",
        next_action="collect_reference",
    )
    if state.model_dump(mode="json") != expected.model_dump(mode="json"):
        raise ValueError("AQ v2 initial state differs from the exact planner envelope")


def _infer_transition_event(
    previous: AutonomyStateV2,
    current: AutonomyStateV2,
) -> TransitionEvent:
    """Infer the only legal event from adjacent state boundaries and terminal evidence."""

    if current.phase == "terminal":
        if current.status == "review_required":
            return "quality_nonpassing"
        if current.status == "blocked":
            return "blocked"
        if current.status == "cancelled":
            return "cancelled"
        if current.delivery_terminal is not None:
            return "delivery_finished"
        if current.status == "failed":
            return "failed"
        raise ValueError("AQ v2 terminal state has no reconstructable transition event")

    boundary = (current.phase, current.status, current.next_action)
    event_by_boundary: dict[tuple[str, str, str], TransitionEvent] = {
        ("authoring", "waiting_for_controller", "execute_controller"): (
            "controller_required"
        ),
        ("authoring", "running", "validate_candidate"): "controller_output_ready",
        ("quality", "running", "run_integrated_quality"): (
            "material_candidate_validated"
        ),
        ("quality", "quality_approved", "plan_delivery"): "quality_passed",
        ("delivery", "delivery_pending", "await_v07_approval"): "delivery_planned",
    }
    if boundary == ("authoring", "running", "execute_controller"):
        if previous.next_action == "collect_reference":
            return "reference_ready"
        if previous.next_action == "validate_candidate":
            return "candidate_validated"
        raise ValueError("AQ v2 authoring state has an ambiguous predecessor boundary")
    event = event_by_boundary.get(boundary)
    if event is None:
        raise ValueError("AQ v2 state boundary has no reconstructable transition event")
    return event


def validate_state_transition(
    previous: AutonomyStateV2,
    current: AutonomyStateV2,
) -> None:
    """Rebuild one adjacent transition and reject splices or budget rollback."""

    if current.sequence != previous.sequence + 1:
        raise ValueError("AQ v2 state transition sequence is not contiguous")
    if (
        current.job_id,
        current.workflow_id,
        current.dispatch_id,
        current.session_id,
        current.plan,
    ) != (
        previous.job_id,
        previous.workflow_id,
        previous.dispatch_id,
        previous.session_id,
        previous.plan,
    ):
        raise ValueError("AQ v2 state transition changed immutable session identity")
    if current.created_at < previous.created_at:
        raise ValueError("AQ v2 state transition timestamp moved backwards")
    previous_usage = previous.budget_usage.model_dump()
    current_usage = current.budget_usage.model_dump()
    if any(current_usage[key] < value for key, value in previous_usage.items()):
        raise ValueError("AQ v2 state transition rolled back budget usage")
    if (
        len(current.provenance) != len(previous.provenance) + 1
        or current.provenance[:-1] != previous.provenance
    ):
        raise ValueError("AQ v2 state transition provenance is not append-only")
    evidence = current.provenance[-1]
    event = _infer_transition_event(previous, current)
    reconstructed = transition_state(
        previous,
        event=event,
        evidence=evidence,
        created_at=current.created_at,
        source_freeze=current.source_freeze,
        quality_terminal=current.quality_terminal,
        delivery_plan=current.delivery_plan,
        delivery_terminal=current.delivery_terminal,
        delivery_results=current.delivery_results,
        budget_usage=current.budget_usage,
        reason=current.terminal_reason,
    )
    if current.model_dump(mode="json") != reconstructed.model_dump(mode="json"):
        raise ValueError("AQ v2 state differs from its reconstructed transition")


def transition_state(
    current: AutonomyStateV2,
    *,
    event: TransitionEvent,
    evidence: AQV2Artifact,
    created_at: datetime,
    source_freeze: AQV2Artifact | None = None,
    quality_terminal: AQV2Artifact | None = None,
    delivery_plan: AQV2Artifact | None = None,
    delivery_terminal: AQV2Artifact | None = None,
    delivery_results: list[DeliveryResult] | None = None,
    budget_usage: BudgetUsageV2 | None = None,
    reason: str | None = None,
) -> AutonomyStateV2:
    """Return the next deterministic state without performing any side effect."""

    if current.next_action == "none":
        raise ValueError("terminal AQ v2 state cannot transition")
    boundary = (current.phase, current.status, current.next_action)
    allowed_events = _ALLOWED_EVENTS_BY_BOUNDARY.get(boundary, frozenset())
    if event not in allowed_events:
        raise ValueError(
            "AQ v2 event is invalid for the current state boundary: "
            f"{boundary!r} -> {event}"
        )
    if event == "quality_passed" and (
        source_freeze is None or quality_terminal is None
    ):
        raise ValueError(
            "quality_passed requires exact quality-terminal and source-freeze evidence"
        )
    if event == "quality_nonpassing" and quality_terminal is None:
        raise ValueError("quality_nonpassing requires exact quality-terminal evidence")
    if event in {"quality_passed", "quality_nonpassing"} and evidence != quality_terminal:
        raise ValueError("quality transition evidence must be the exact quality terminal")
    if event == "delivery_planned" and delivery_plan is None:
        raise ValueError("delivery_planned requires exact delivery-plan evidence")
    if event == "delivery_planned" and evidence != delivery_plan:
        raise ValueError("delivery planning evidence must be the exact delivery plan")
    if event == "delivery_finished" and (
        delivery_terminal is None or not delivery_results
    ):
        raise ValueError(
            "delivery_finished requires an exact delivery terminal and nonempty results"
        )
    if event == "delivery_finished" and evidence != delivery_terminal:
        raise ValueError("delivery completion evidence must be the exact delivery terminal")
    mapping: dict[str, tuple[str, str, str]] = {
        "reference_ready": ("authoring", "running", "execute_controller"),
        "controller_required": (
            "authoring",
            "waiting_for_controller",
            "execute_controller",
        ),
        "controller_output_ready": ("authoring", "running", "validate_candidate"),
        "candidate_validated": ("authoring", "running", "execute_controller"),
        "material_candidate_validated": (
            "quality",
            "running",
            "run_integrated_quality",
        ),
        "quality_passed": ("quality", "quality_approved", "plan_delivery"),
        "quality_nonpassing": ("terminal", "completed", "none"),
        "delivery_planned": ("delivery", "delivery_pending", "await_v07_approval"),
        "delivery_finished": ("terminal", "completed", "none"),
        "blocked": ("terminal", "blocked", "none"),
        "failed": ("terminal", "failed", "none"),
        "cancelled": ("terminal", "cancelled", "none"),
    }
    phase, status, next_action = mapping[event]
    results = list(delivery_results or current.delivery_results)
    terminal_reason = reason
    if event == "quality_nonpassing":
        status = "review_required"
        terminal_reason = reason or "integrated quality did not pass"
    elif event == "delivery_finished":
        statuses = [item.status for item in results]
        if statuses == ["review_only"] or all(item == "completed" for item in statuses):
            status = "completed"
        elif any(item == "completed" for item in statuses):
            status = "partial"
        else:
            status = "failed"
        terminal_reason = reason or "delivery requests reached terminal outcomes"
    elif status in {"blocked", "failed", "cancelled"}:
        terminal_reason = reason or event
    previous_sha = stable_json_digest(current.model_dump(mode="json"))
    provenance = [*current.provenance, evidence]
    payload = {
        "previous": previous_sha,
        "event": event,
        "evidence": evidence.sha256,
        "sequence": current.sequence + 1,
    }
    return AutonomyStateV2(
        contract_id=f"state-{current.session_id}-{current.sequence + 1:04d}",
        job_id=current.job_id,
        workflow_id=current.workflow_id,
        dispatch_id=current.dispatch_id,
        session_id=current.session_id,
        input_sha256=stable_json_digest(payload),
        source_fingerprint=stable_json_digest(
            {**payload, "status": status, "next_action": next_action}
        ),
        producer="codex_blender_modeler.autonomy_v2.transitions",
        provenance=provenance,
        created_at=created_at,
        state_id=f"state-{current.session_id}-{current.sequence + 1:04d}",
        plan=current.plan,
        sequence=current.sequence + 1,
        phase=phase,
        status=status,
        next_action=next_action,
        quality_terminal=quality_terminal or current.quality_terminal,
        source_freeze=source_freeze or current.source_freeze,
        delivery_plan=delivery_plan or current.delivery_plan,
        delivery_terminal=delivery_terminal or current.delivery_terminal,
        delivery_results=results,
        budget_usage=budget_usage or current.budget_usage,
        previous_state_sha256=previous_sha,
        terminal_reason=terminal_reason,
    )
