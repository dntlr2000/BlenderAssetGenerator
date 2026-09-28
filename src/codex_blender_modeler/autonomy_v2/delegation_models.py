"""Finite campaign authority; successor scopes are policy, never human acceptance."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from ..production.activation_models import ActivationArtifact
from ..reference_fidelity.models import FidelityModel
from ..stabilization.models import JobId, PortableId, Sha256
from .fidelity_budget_models import (
    FidelityBudgetEpochV01,
    FidelityHistoryEntryV01,
    FidelityLifetimeUsageV01,
)


class DelegationCost(FidelityModel):
    """Count reserved capacity separately from native actual use; capacity is never refunded."""

    candidates: int = Field(default=0, ge=0)
    preparation_repairs: int = Field(default=0, ge=0)
    structural: int = Field(default=0, ge=0)
    local: int = Field(default=0, ge=0)
    strategy_switches: int = Field(default=0, ge=0)
    aq_builds: int = Field(default=0, ge=0)
    closure_processes: int = Field(default=0, ge=0)
    quality_evaluations: int = Field(default=0, ge=0)
    promotions: int = Field(default=0, ge=0)
    controller_invocations: int = Field(default=0, ge=0)
    delivery_runs: int = Field(default=0, ge=0)
    package_repairs: int = Field(default=0, ge=0)
    actions: int = Field(default=0, ge=0)

    def plus(self, other: DelegationCost) -> DelegationCost:
        """Add immutable allocations without conflating them with human decisions."""
        return DelegationCost(
            **{key: getattr(self, key) + getattr(other, key) for key in type(self).model_fields}
        )


class DelegationSlot(FidelityModel):
    """Price one initial candidate and its finite correction, closure and delivery reserve."""

    initial_object_limit: int = Field(ge=1, le=48)
    correction_object_limit: int = Field(ge=1, le=48)
    structural_rounds: int = Field(ge=0, le=3)
    parametric_rounds: int = Field(ge=0, le=2)
    material_corrections: int = Field(ge=0, le=2)
    strategy_switches: int = Field(ge=0, le=1)
    preparation_repairs: int = Field(default=2, ge=0, le=2)

    def funding(
        self,
        job_id: str,
        epoch_id: str,
        reference_sha256: str,
        history: list[FidelityHistoryEntryV01],
    ) -> FidelityBudgetEpochV01:
        """Reprice the native epoch using current verified history and the approved slot."""
        prior = FidelityLifetimeUsageV01(
            **{
                key: sum(getattr(item.usage, key) for item in history)
                for key in FidelityLifetimeUsageV01.model_fields
            }
        )
        return FidelityBudgetEpochV01(
            job_id=job_id,
            epoch_id=epoch_id,
            reference_sha256=reference_sha256,
            prior_history=history,
            prior_usage=prior,
            **self.model_dump(exclude={"strategy_switches", "preparation_repairs"}),
        )

    def cost(self) -> DelegationCost:
        """Include real object materializations, six closure processes and all native caps."""
        funding = self.funding("pricing_fixture", "pricing", "0" * 64, [])
        limits = funding.required_limits(delivery_runs=1)
        return DelegationCost(
            candidates=1,
            preparation_repairs=self.preparation_repairs,
            structural=self.structural_rounds,
            local=self.parametric_rounds + self.material_corrections,
            strategy_switches=self.strategy_switches,
            aq_builds=limits["total_blender_builds"],
            closure_processes=funding.preflight_limits()["preflight_blender_runs"],
            quality_evaluations=limits["total_quality_evaluations"],
            promotions=limits["canonical_promotions"],
            controller_invocations=limits["controller_invocations"],
            delivery_runs=1,
            package_repairs=limits["package_repairs"],
            actions=limits["global_action_limit"],
        )

    @model_validator(mode="after")
    def validate_pricing(self) -> Self:
        """Reject unpriced schedules beyond the unchanged native per-session hard limits."""
        self.cost()
        return self


class DelegationAsset(FidelityModel):
    """Freeze one reference, observed criteria, prior consumption and additive candidate slots."""

    asset_id: PortableId
    target_subject: str = Field(min_length=1, max_length=1024)
    reference: ActivationArtifact
    hypothesis: ActivationArtifact
    comparison_lighting_profile: Literal["camera_studio_v1"] = "camera_studio_v1"
    minimum_boundary_f_score: float = Field(default=0.8, ge=0, le=1)
    minimum_direct_score: float = Field(default=0.0, ge=0, le=1)
    minimum_silhouette_iou: float = Field(default=0.0, ge=0, le=1)
    prior_history: list[FidelityHistoryEntryV01]
    prior_initial_candidates: int = Field(ge=0)
    inherited_evidence: list[ActivationArtifact] = Field(min_length=1, max_length=128)
    slots: list[DelegationSlot] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_addition(self) -> Self:
        """Apply structural/local/strategy caps across all slots, not once per renamed job."""
        total = self.cost()
        if total.structural > 3 or total.local > 2 or total.strategy_switches > 1:
            raise ValueError("asset delegation exceeds additive structural 3/local 2/strategy 1")
        identities = [(item.job_id, item.session_id) for item in self.prior_history]
        if identities != sorted(set(identities)):
            raise ValueError("delegation history must be unique and sorted")
        return self

    def cost(self) -> DelegationCost:
        """Sum the full reserved capacity of every candidate for this reference."""
        total = DelegationCost()
        for slot in self.slots:
            total = total.plus(slot.cost())
        return total


class FidelityCampaignDelegationV01(FidelityModel):
    """Reviewable one-time mandate over exact source, references, budgets and quality rules."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_campaign_delegation"] = "fidelity_campaign_delegation"
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    delegation_id: PortableId
    user_request: str = Field(min_length=1, max_length=32768)
    source_manifest: ActivationArtifact
    baseline: ActivationArtifact
    supersedes: ActivationArtifact | None = None
    prior_delegated_reservations: DelegationCost = Field(default_factory=DelegationCost)
    assets: list[DelegationAsset] = Field(min_length=1, max_length=16)
    total_budget: DelegationCost
    expires_at: datetime
    delivery_profile: Literal["portable_gltf"] = "portable_gltf"
    provider: Literal["local_only"] = "local_only"
    extra_identity_split_operations: Literal[0] = 0
    approval_mode: Literal["autonomous"] = "autonomous"
    canary_then_ordered_assets: Literal[True] = True
    paired_improvement_required: Literal[True] = True
    major_structure_findings_allowed: Literal[0] = 0
    same_defect_plateau_length: Literal[2] = 2
    source_changes_allowed: Literal[False] = False
    historical_evidence_mutation: Literal[False] = False
    future_artifacts_user_approved: Literal[False] = False
    human_beauty_acceptance: Literal[False] = False
    human_package_acceptance: Literal[False] = False
    human_activation_acceptance: Literal[False] = False
    destination_write: Literal[False] = False
    background_execution: Literal[False] = False

    @model_validator(mode="after")
    def validate_campaign(self) -> Self:
        """Reject duplicated references, hidden extra budgets and naive expiry timestamps."""
        for values in (
            [a.asset_id for a in self.assets],
            [a.reference.sha256 for a in self.assets],
        ):
            if len(values) != len(set(values)):
                raise ValueError("delegation repeats an asset or reference")
        total = DelegationCost()
        for asset in self.assets:
            total = total.plus(asset.cost())
        if total != self.total_budget:
            raise ValueError("delegation total budget differs from the exact priced slots")
        if self.supersedes is None and self.prior_delegated_reservations != DelegationCost():
            raise ValueError("prior delegated capacity requires an exact predecessor mandate")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("delegation expiry must include a timezone")
        return self


class DelegationDecisionV01(FidelityModel):
    """Record only the user's exact mandate decision, never acceptance of future artwork."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract: ActivationArtifact
    decision: Literal["approve"] = "approve"
    exact_user_text: str = Field(min_length=1, max_length=32768)
    created_at: datetime
    future_artifacts_user_approved: Literal[False] = False


class DelegationScopeV01(FidelityModel):
    """Host-issued single-candidate scope with a nonrefundable aggregate reservation."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract: ActivationArtifact
    decision: ActivationArtifact
    sequence: int = Field(ge=1)
    previous: ActivationArtifact | None
    asset_id: PortableId
    slot_index: int = Field(ge=0, le=3)
    job_id: JobId
    strategy: PortableId
    strategy_switch_reserved_on_entry: bool = False
    funding: FidelityBudgetEpochV01
    reserved_before: DelegationCost
    reserved_after: DelegationCost
    created_at: datetime
    authority: Literal["host_campaign_policy"] = "host_campaign_policy"
    is_user_approval: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"


class DelegationBindingV01(FidelityModel):
    """Bind the native budget to an exact workspace-owned parent reservation."""

    delegation_id: PortableId
    scope_sequence: int = Field(ge=1)
    contract_sha256: Sha256
    scope_sha256: Sha256


class DelegationPreparationV01(FidelityModel):
    """Preserve each published data set or repair without executing it or overwriting history."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    scope: ActivationArtifact
    sequence: int = Field(ge=0, le=2)
    previous: ActivationArtifact | None
    artifacts: list[ActivationArtifact] = Field(min_length=1, max_length=1024)
    created_at: datetime
    is_user_approval: Literal[False] = False


class DelegationOutcomeV01(FidelityModel):
    """Host-verified terminal plus exact evidence; technical and visual success stay separate."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    scope: ActivationArtifact
    session_id: PortableId
    terminal_state: ActivationArtifact
    technical_passed: bool
    visual_passed: bool
    evidence: list[ActivationArtifact]
    remaining_findings: list[str]
    created_at: datetime
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    human_package_acceptance: Literal[False] = False
    human_activation_acceptance: Literal[False] = False
