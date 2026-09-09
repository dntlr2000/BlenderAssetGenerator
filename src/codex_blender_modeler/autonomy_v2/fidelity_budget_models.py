"""Explicit finite funding epochs; historical budgets and acceptance retain their meaning."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from ..blender_artifacts import stable_json_digest
from ..reference_fidelity.models import FidelityModel
from ..stabilization.models import JobId, PortableId, Sha256


class FidelityLifetimeUsageV01(FidelityModel):
    """Keep observed or already reserved work visible across reference-identical sessions."""

    structural: int = Field(default=0, ge=0)
    local: int = Field(default=0, ge=0)
    strategy_switches: int = Field(default=0, ge=0)
    blender_builds: int = Field(default=0, ge=0)
    preflight_blender_runs: int = Field(default=0, ge=0)
    quality_evaluations: int = Field(default=0, ge=0)
    promotions: int = Field(default=0, ge=0)


class FidelityHistoryEntryV01(FidelityModel):
    """Bind the full session JSON inventory and validated counters without reopening it."""

    job_id: JobId
    session_id: PortableId
    session_evidence_sha256: Sha256
    last_state_sha256: Sha256
    budget_sha256: Sha256
    status: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    funded_epoch: bool
    epoch_id: PortableId | None = None
    usage: FidelityLifetimeUsageV01


class FidelityBudgetEpochV01(FidelityModel):
    """Freeze one additive allowance with exact history, object counts and route costs."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_budget_epoch"] = "fidelity_budget_epoch"
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    epoch_id: PortableId
    job_id: JobId
    reference_sha256: Sha256
    prior_history: list[FidelityHistoryEntryV01]
    prior_usage: FidelityLifetimeUsageV01
    initial_object_limit: int = Field(ge=1, le=48)
    correction_object_limit: int = Field(ge=1, le=48)
    structural_rounds: int = Field(default=3, ge=0, le=3)
    parametric_rounds: int = Field(default=0, ge=0, le=2)
    material_corrections: int = Field(default=2, ge=0, le=2)
    strategy_switch_limit: Literal[1] = 1
    same_input_technical_retries: Literal[1] = 1
    human_approval_authority: Literal[False] = False
    historical_budget_mutation: Literal[False] = False
    destination_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_finite_funding(self) -> Self:
        """Reject hidden resets, duplicate history and schedules beyond the existing envelope."""

        identities = [(item.job_id, item.session_id) for item in self.prior_history]
        if identities != sorted(set(identities)):
            raise ValueError("funding history must be uniquely ordered by job and session")
        expected = {
            key: sum(getattr(item.usage, key) for item in self.prior_history)
            for key in FidelityLifetimeUsageV01.model_fields
        }
        if self.prior_usage != FidelityLifetimeUsageV01(**expected):
            raise ValueError("funding epoch cannot reset or hide prior lifetime consumption")
        if self.parametric_rounds + self.material_corrections > 2:
            raise ValueError("parametric and material corrections share a two-round limit")
        if self.structural_rounds + self.parametric_rounds and (
            self.correction_object_limit < self.initial_object_limit
        ):
            raise ValueError("correction reserve must cover the initial object allowance")
        if self.required_limits(delivery_runs=0)["total_blender_builds"] > 64:
            raise ValueError("funded schedule exceeds the finite 64-build approval envelope")
        return self

    def digest(self) -> str:
        """Bind the complete funding proposal, including inherited consumption, by exact content."""

        return stable_json_digest(self.model_dump(mode="json"))

    def initial_cost(self) -> dict[str, int]:
        """Reserve N materializations, geometry build, graph compile, rebuild and render/IQ."""

        return {
            "materializations": self.initial_object_limit, "builds": 3,
            "qa_runs": 3, "closure_runs": 1, "diagnostic_views": 0, "promotions": 2,
        }

    def route_cost(self, route: str) -> dict[str, int]:
        """Price one exact route; structural/scalar edits include renewed material closure."""

        if route not in {"structural_reentry", "parametric_revision", "material_revision"}:
            raise ValueError("unsupported funded correction route")
        material = route == "material_revision"
        return {
            "materializations": 0 if material else self.correction_object_limit,
            "builds": 2 if material else 3, "qa_runs": 3, "closure_runs": 1,
            "diagnostic_views": 0, "promotions": 1 if material else 2,
        }

    def revision_cost(self) -> dict[str, int]:
        """Sum the exact finite structural, parametric and material allocation."""

        result = dict.fromkeys(self.initial_cost(), 0)
        for route, count in self.route_limits().items():
            for key, value in self.route_cost(route).items():
                result[key] += count * value
        return result

    def route_limits(self) -> dict[str, int]:
        """Keep local route quotas separate while retaining their shared lifetime cap."""

        return {
            "structural_reentry": self.structural_rounds,
            "parametric_revision": self.parametric_rounds,
            "material_revision": self.material_corrections,
        }

    def required_limits(self, *, delivery_runs: int) -> dict[str, int]:
        """Derive immutable AQ caps from priced work, with one bounded controller retry spare."""

        initial, revision = self.initial_cost(), self.revision_cost()
        summed = {key: value + revision[key] for key, value in initial.items()}
        return {
            "initial_candidates": 1, "structural_rounds": self.structural_rounds,
            "candidates_per_structural_round": 1,
            "parametric_convergence_iterations": self.parametric_rounds + self.material_corrections,
            "material_rounds": summed["closure_runs"],
            "total_blender_builds": summed["materializations"] + summed["builds"],
            "total_quality_evaluations": summed["qa_runs"],
            "controller_invocations": summed["promotions"] + 1,
            "delivery_runs": delivery_runs, "canonical_promotions": summed["promotions"],
            "package_repairs": 1, "global_action_limit": 72,
            "repeated_identical_failure_limit": 1, "transient_retry_limit": 1,
        }

    def lifetime_limit(self) -> FidelityLifetimeUsageV01:
        """Expose prior consumption plus this finite addition without resetting totals."""

        limits = self.required_limits(delivery_runs=0)
        additions = {
            "structural": self.structural_rounds,
            "local": self.parametric_rounds + self.material_corrections,
            "strategy_switches": 1, "blender_builds": limits["total_blender_builds"],
            "preflight_blender_runs": self.preflight_limits()["preflight_blender_runs"],
            "quality_evaluations": limits["total_quality_evaluations"],
            "promotions": limits["canonical_promotions"],
        }
        return FidelityLifetimeUsageV01(**{
            key: getattr(self.prior_usage, key) + amount for key, amount in additions.items()
        })

    def preflight_limits(self) -> dict[str, int]:
        """Price six isolated Blender calls per closure in the separate resource ledger."""

        rounds = self.initial_cost()["closure_runs"] + self.revision_cost()["closure_runs"]
        return {
            "preflight_blender_runs": 6 * rounds, "controller_invocations": 0,
            "canonical_promotions": 0, "appearance_revisions": 0,
            "transient_controller_retries": 0,
        }
