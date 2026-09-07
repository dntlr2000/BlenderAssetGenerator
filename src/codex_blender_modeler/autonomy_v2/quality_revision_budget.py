"""Pure bounded routing and cost accounting shared by host execution and negative tests."""

from __future__ import annotations

from ..reference_fidelity.models import FidelityArtifact, FidelityEvaluationV01
from .quality_revision_models import (
    AQQualityRevisionLoop,
    QualityAttemptV01,
    RevisionCostV01,
    RevisionLedgerEntryV01,
    StructuralReentryPlanV01,
)


def require_strategy_change(attempts: list[QualityAttemptV01]) -> bool:
    """Detect the same unresolved defect/route even when unrelated features have improved."""

    if len(attempts) < 2:
        return False
    older, current = attempts[-2:]
    return (
        older.strategy == current.strategy
        and older.next_action == current.next_action
        and bool(set(older.unresolved_features) & set(current.unresolved_features))
    )


def select_revision_route(
    evaluation: FidelityEvaluationV01,
    attempts: list[QualityAttemptV01],
    *,
    structural_used: int,
    local_used: int,
    strategy_switches_used: int,
    loop: AQQualityRevisionLoop,
) -> tuple[str, str]:
    """Stop on limits/plateau rather than treating a missing approval as a quality fix."""

    route = evaluation.next_action
    if route == "quality_ready":
        return route, "Observed requirements are satisfied; exact IQ/freeze checks remain."
    if route in {"technical_recovery", "calibration", "evidence_required"}:
        return route, "Resolve the diagnosed prerequisite; do not conceal it with geometry detail."
    if require_strategy_change(attempts):
        if strategy_switches_used >= loop.strategy_switch_limit:
            return "review_required", "Stagnation after the allowed representation strategy change."
        if route == "structural_reentry" and structural_used >= loop.structural_revision_limit:
            return (
                "review_required",
                "No structural budget remains for the required strategy change.",
            )
        if route in {"material_revision", "parametric_revision"} and (
            local_used >= loop.local_revision_limit
        ):
            return "review_required", "No shared local budget remains for a strategy change."
        return route, "Repeated defect requires a new strategy within the diagnosed route."
    if route == "structural_reentry" and structural_used >= loop.structural_revision_limit:
        return "review_required", "Structural reauthoring budget exhausted; preserve best evidence."
    if (
        route in {"parametric_revision", "material_revision"}
        and local_used >= loop.local_revision_limit
    ):
        return "review_required", "Shared local dimension/material/lighting budget exhausted."
    return route, "Correct the exact finding and compare under the frozen conditions."


def reserve_revision(
    loop: AQQualityRevisionLoop,
    plan: StructuralReentryPlanV01,
    *,
    loop_artifact: FidelityArtifact,
    plan_artifact: FidelityArtifact,
    previous: RevisionLedgerEntryV01 | None,
    previous_artifact: FidelityArtifact | None,
) -> RevisionLedgerEntryV01:
    """Charge all planned effects before execution and reject any round/cost reset or overrun."""

    if plan.loop != loop_artifact:
        raise ValueError("reentry plan belongs to another loop")
    if (previous is None) != (previous_artifact is None):
        raise ValueError("previous ledger and fingerprint must be paired")
    if previous is not None and previous.loop != loop_artifact:
        raise ValueError("cannot reuse another loop's budget ledger")
    sequence = 1 if previous is None else previous.sequence + 1
    if plan.round_index != sequence:
        raise ValueError("reentry round would reset or skip the consumed budget")
    structural = int(plan.route == "structural_reentry") + (
        previous.structural_used if previous else 0
    )
    local = int(plan.route != "structural_reentry") + (previous.local_used if previous else 0)
    switches = int(plan.change_strategy) + (previous.strategy_switches_used if previous else 0)
    if structural > loop.structural_revision_limit or local > loop.local_revision_limit:
        raise PermissionError("quality revision round budget exhausted")
    if switches > loop.strategy_switch_limit:
        raise PermissionError("quality revision strategy change budget exhausted")
    old_cost = previous.cost_used if previous else RevisionCostV01()
    values = {key: getattr(old_cost, key) + value for key, value in plan.cost.model_dump().items()}
    for key, value in values.items():
        if value > getattr(loop.cost_limit, key):
            raise PermissionError(f"quality revision {key} budget exhausted before side effects")
    return RevisionLedgerEntryV01(
        loop=loop_artifact,
        sequence=sequence,
        previous=previous_artifact,
        plan=plan_artifact,
        structural_used=structural,
        local_used=local,
        strategy_switches_used=switches,
        cost_used=RevisionCostV01(**values),
    )
