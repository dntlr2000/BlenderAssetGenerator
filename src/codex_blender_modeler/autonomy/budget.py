"""Immutable budget accounting helpers for bounded autonomy execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import AutonomyBudget, BudgetUsage


@dataclass(frozen=True)
class BudgetDecision:
    """Describe one bounded budget transition without mutating its source models."""

    allowed: bool
    usage: BudgetUsage
    exhausted_dimension: str | None = None


_LIMIT_FIELDS = {
    "initial_candidates": "initial_candidates",
    "structural_rounds": "structural_rounds",
    "parametric_convergence_iterations": "parametric_convergence_iterations",
    "material_rounds": "material_rounds",
    "package_repairs": "package_repairs",
    "total_blender_builds": "total_blender_builds",
    "total_quality_evaluations": "total_quality_evaluations",
    "canonical_promotions": "canonical_promotions",
    "total_actions": "global_action_limit",
}


def consume_budget(
    budget: AutonomyBudget,
    usage: BudgetUsage,
    **increments: int,
) -> BudgetDecision:
    """Return an incremented usage only when every immutable limit remains satisfied."""

    unknown = sorted(set(increments) - set(_LIMIT_FIELDS))
    if unknown:
        raise ValueError(f"Unknown autonomy budget dimensions: {unknown}")
    if any(not isinstance(value, int) or value < 0 for value in increments.values()):
        raise ValueError("Autonomy budget increments must be non-negative integers")
    values = usage.model_dump()
    for name, amount in increments.items():
        values[name] += amount
    candidate = BudgetUsage.model_validate(values)
    for usage_field, limit_field in _LIMIT_FIELDS.items():
        if getattr(candidate, usage_field) > getattr(budget, limit_field):
            return BudgetDecision(False, usage, usage_field)
    return BudgetDecision(True, candidate)


def remaining_budget(budget: AutonomyBudget, usage: BudgetUsage) -> dict[str, int]:
    """Project non-negative remaining counts for reporting and policy decisions."""

    _ = asdict(BudgetDecision(True, usage))
    return {
        usage_field: max(
            0,
            int(getattr(budget, limit_field)) - int(getattr(usage, usage_field)),
        )
        for usage_field, limit_field in _LIMIT_FIELDS.items()
    }

