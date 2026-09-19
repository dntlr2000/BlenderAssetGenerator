"""Disabled-experimental quality revision companion, with shared non-resettable budgets."""

from __future__ import annotations

import json
from typing import Literal, Self, TypeAlias

from pydantic import Field, model_validator

from ..integrated_quality.v02_models import JobId, Sha256, StableId
from ..reference_fidelity.models import FidelityArtifact, FidelityModel, RevisionRoute
from .fidelity_budget_models import FidelityBudgetEpochV01


class RevisionCostV01(FidelityModel):
    """Reserve actual stage costs before effects; a structural round is not a build budget."""

    materializations: int = Field(default=0, ge=0)
    builds: int = Field(default=0, ge=0)
    qa_runs: int = Field(default=0, ge=0)
    closure_runs: int = Field(default=0, ge=0)
    diagnostic_views: int = Field(default=0, ge=0)
    promotions: int = Field(default=0, ge=0)


class AQQualityRevisionLoopV01(FidelityModel):
    """Freeze one explicitly selected loop over one active AQ root and Approval Envelope."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["aq_quality_revision_loop"] = "aq_quality_revision_loop"
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    job_id: JobId
    session_id: StableId
    root_authorization: FidelityArtifact
    approval_envelope: FidelityArtifact
    hypothesis: FidelityArtifact
    initial_state: FidelityArtifact
    structural_revision_limit: int = Field(default=3, ge=0, le=3)
    local_revision_limit: int = Field(default=2, ge=0, le=2)
    same_input_technical_retries: Literal[1] = 1
    plateau_length: Literal[2] = 2
    strategy_switch_limit: Literal[1] = 1
    cost_limit: RevisionCostV01
    allow_disabled_experimental: Literal[True]
    execution_lifetime: Literal["current_codex_task"] = "current_codex_task"
    human_approval_authority: Literal[False] = False
    destination_write: Literal[False] = False


class AQQualityRevisionLoopV02(AQQualityRevisionLoopV01):
    """Add causal IQ routing and an honest root-budget reserve without changing V0.1."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    routing_policy: Literal["causal_v2"] = "causal_v2"
    initial_pipeline_reserve: RevisionCostV01

    @model_validator(mode="after")
    def validate_initial_pipeline_reserve(self) -> Self:
        """Require the minimum initial geometry, material, render, IQ and promotion costs."""

        minimums = {
            "materializations": 1,
            "builds": 3,
            "qa_runs": 2,
            "closure_runs": 1,
            "promotions": 2,
        }
        for field, minimum in minimums.items():
            if getattr(self.initial_pipeline_reserve, field) < minimum:
                raise ValueError(
                    f"initial_pipeline_reserve.{field} must cover at least {minimum}"
                )
        return self


class AQQualityRevisionLoopV03(AQQualityRevisionLoopV02):
    """Bind the same finite funding epoch as the root, including exact per-route reserves."""

    schema_version: Literal["0.3.0"] = "0.3.0"
    funding: FidelityBudgetEpochV01

    @model_validator(mode="after")
    def validate_funded_loop(self) -> Self:
        """Require every initial and correction cost to match the immutable funded schedule."""

        if self.job_id != self.funding.job_id:
            raise ValueError("loop funding belongs to another job")
        if self.structural_revision_limit != self.funding.structural_rounds:
            raise ValueError("loop structural limit differs from funded reserve")
        if self.local_revision_limit != (
            self.funding.parametric_rounds + self.funding.material_corrections
        ):
            raise ValueError("loop shared local limit differs from funded reserve")
        if self.initial_pipeline_reserve.model_dump() != self.funding.initial_cost():
            raise ValueError("loop initial cost differs from funded reserve")
        if self.cost_limit.model_dump() != self.funding.revision_cost():
            raise ValueError("loop correction cost differs from funded reserve")
        return self


class AQQualityRevisionLoopV04(AQQualityRevisionLoopV03):
    """Select one fixed comparison-lighting policy without expanding any correction budget."""

    schema_version: Literal["0.4.0"] = "0.4.0"
    comparison_lighting_profile: Literal["camera_studio_v1"]
    lighting_implementation_sha256: Sha256


AQQualityRevisionLoop: TypeAlias = (
    AQQualityRevisionLoopV01 | AQQualityRevisionLoopV02 | AQQualityRevisionLoopV03
    | AQQualityRevisionLoopV04
)


def parse_quality_revision_loop(payload: bytes) -> AQQualityRevisionLoop:
    """Dispatch an exact loop schema version without coercing or migrating historical bytes."""

    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("quality revision loop is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("quality revision loop must be a JSON object")
    model = {
        "0.1.0": AQQualityRevisionLoopV01,
        "0.2.0": AQQualityRevisionLoopV02,
        "0.3.0": AQQualityRevisionLoopV03,
        "0.4.0": AQQualityRevisionLoopV04,
    }.get(decoded.get("schema_version"))
    if model is None:
        raise ValueError("unsupported quality revision loop schema_version")
    return model.model_validate_json(payload)


class QualityAttemptV01(FidelityModel):
    """Persist a nonterminal quality attempt against the exact current round source tuple."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["aq_quality_attempt"] = "aq_quality_attempt"
    loop: FidelityArtifact
    round_index: int = Field(ge=0)
    source_state: FidelityArtifact
    scene_spec: FidelityArtifact
    geometry_receipt: FidelityArtifact
    material_receipt: FidelityArtifact
    quality_submission: FidelityArtifact
    visual_review: FidelityArtifact
    fidelity_evaluation: FidelityArtifact
    strategy: StableId
    unresolved_features: list[StableId]
    next_action: RevisionRoute
    previous_attempt: FidelityArtifact | None = None
    paired_comparison: FidelityArtifact | None = None
    supplements_attempt: FidelityArtifact | None = None
    is_terminal: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"


class QualityRenderReservationV01(FidelityModel):
    """Charge a real QA invocation before effects and preserve exact same-input retry identity."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_qa_reservation"] = "fidelity_qa_reservation"
    loop: FidelityArtifact
    sequence: int = Field(ge=1)
    previous: FidelityArtifact | None
    round_index: int = Field(ge=0, le=5)
    attempt_index: int = Field(ge=0, le=1)
    source_state: FidelityArtifact
    source: FidelityArtifact
    build_fingerprint: Sha256
    run_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")
    reserved_before_effects: Literal[True] = True
    human_approval_authority: Literal[False] = False


class StructuralReentryPlanV01(FidelityModel):
    """Bind one exact correction and its cost before candidate authoring or promotion."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["structural_reentry_plan"] = "structural_reentry_plan"
    loop: FidelityArtifact
    attempt: FidelityArtifact
    round_index: int = Field(ge=1, le=5)
    source_scene: FidelityArtifact
    source_modeling_plan: FidelityArtifact
    source_blend: FidelityArtifact
    feature_ids: list[StableId] = Field(min_length=1)
    target_ids: list[StableId] = Field(min_length=1)
    route: Literal["structural_reentry", "parametric_revision", "material_revision"]
    strategy: StableId
    change_strategy: bool
    cost: RevisionCostV01
    comparison_camera_sha256: Sha256
    policy_gate: Literal[
        "structural_candidate_promotion",
        "bounded_parametric_revision",
        "material_candidate_promotion",
    ]
    authority: Literal["plan_only_requires_exact_host_policy"] = (
        "plan_only_requires_exact_host_policy"
    )

    @model_validator(mode="after")
    def validate_route(self) -> Self:
        """Keep structural, scalar and material policy purposes distinct."""

        expected = {
            "structural_reentry": "structural_candidate_promotion",
            "parametric_revision": "bounded_parametric_revision",
            "material_revision": "material_candidate_promotion",
        }[self.route]
        if self.policy_gate != expected:
            raise ValueError("reentry policy gate differs from defect route")
        if min(self.cost.builds, self.cost.qa_runs, self.cost.promotions) < 1:
            raise ValueError("revision reservation must include build, QA and promotion")
        if self.route == "structural_reentry" and self.cost.closure_runs < 1:
            raise ValueError("structural reentry must reserve renewed material closure")
        for values in (self.feature_ids, self.target_ids):
            if len(values) != len(set(values)):
                raise ValueError("reentry targets must be unique")
        return self


class RevisionLedgerEntryV01(FidelityModel):
    """Append one consumed reservation; crash, cancellation and restart cannot refund it."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["quality_revision_reservation"] = "quality_revision_reservation"
    loop: FidelityArtifact
    sequence: int = Field(ge=1, le=5)
    previous: FidelityArtifact | None
    plan: FidelityArtifact
    structural_used: int = Field(ge=0, le=3)
    local_used: int = Field(ge=0, le=2)
    strategy_switches_used: int = Field(ge=0, le=1)
    cost_used: RevisionCostV01
    reserved_before_effects: Literal[True] = True
    counts_as_human_approval: Literal[False] = False

    @model_validator(mode="after")
    def validate_chain_shape(self) -> Self:
        """Reject a reset counter or missing predecessor in a later reservation."""

        if (self.sequence == 1) != (self.previous is None):
            raise ValueError("reservation predecessor is inconsistent with sequence")
        if self.structural_used + self.local_used != self.sequence:
            raise ValueError("consumed revision counts differ from ledger sequence")
        return self


class FidelityReviewBundleV01(FidelityModel):
    """Preserve attempts and best-known evidence without changing IQ or human disposition."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_review_bundle"] = "fidelity_review_bundle"
    job_id: JobId
    session_id: StableId
    loop: FidelityArtifact
    source_state: FidelityArtifact
    attempts: list[FidelityArtifact] = Field(min_length=1)
    best_known_attempt: FidelityArtifact
    reason: str = Field(min_length=1, max_length=512)
    review_only: Literal[True] = True
    production_ready: Literal[False] = False
    destination_handoff_eligible: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"


class FidelityReviewTerminalV01(FidelityModel):
    """Terminate the new companion, never retroactively reinterpret a legacy IQ report."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_review_terminal"] = "fidelity_review_terminal"
    job_id: JobId
    session_id: StableId
    loop: FidelityArtifact
    source_state: FidelityArtifact
    review_bundle: FidelityArtifact
    status: Literal["review_required"] = "review_required"
    reason: str = Field(min_length=1, max_length=512)
    source_freeze: None = None
    production_ready: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
