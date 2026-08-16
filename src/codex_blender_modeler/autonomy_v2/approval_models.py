"""Strict approval-envelope, policy, escalation, telemetry, and one-prompt contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId
from ..versioning import (
    AUTONOMY_APPROVAL_ENVELOPE_SCHEMA_VERSION,
    AUTONOMY_ONE_PROMPT_SCHEMA_VERSION,
    FRAMEWORK_CHANGE_JUSTIFICATION_SCHEMA_VERSION,
)

ApprovalMode = Literal["autonomous", "checkpointed", "interactive"]
ApprovalCountEffect = Literal["reduces", "maintains", "increases"]
ProviderScope = Literal["local_only", "codex_builtin_imagegen"]
ApprovalEnvelopeStatus = Literal["active", "expired", "cancelled"]
RoutineGateKind = Literal[
    "geometry_candidate_promotion",
    "structural_candidate_promotion",
    "bounded_parametric_revision",
    "bounded_material_identity_split",
    "material_candidate_promotion",
    "material_quality_acknowledgement",
    "iq_quality_acceptance",
    "optimization_plan_authorization",
    "package_acknowledgement",
    "review_bundle_terminal",
    "technical_retry",
    "rollback",
    "imagegen_candidate_adoption",
]
BoundedTransformationKind = Literal[
    "no_visual_technical_normalization",
    "bounded_geometry_revision",
    "bounded_parameter_revision",
    "bounded_material_identity_split",
    "bounded_material_promotion",
    "aq_delivery_authorization",
]
EscalationReason = Literal[
    "scope_expansion",
    "reference_replacement",
    "target_change",
    "budget_expansion",
    "delivery_expansion",
    "destination_project_write",
    "provider_scope_expansion",
    "unresolved_design_ambiguity",
    "missing_exact_user_text",
    "rights_or_license_decision",
]
OnePromptTerminalType = Literal[
    "production_delivery",
    "review_bundle",
    "genuine_escalation",
    "blocked",
    "cancelled",
]
FrameworkChangeClassification = Literal[
    "framework_invariant_violation",
    "reusable_missing_capability",
    "job_local_candidate_error",
    "reference_specific_ambiguity",
]
TechnicalFailureCategory = Literal[
    "dependency_closure",
    "manifest_missing",
    "path_rebinding",
    "hash_projection",
    "schema_serialization",
    "completion_map_binding",
    "stale_generated_projection",
    "controller_output_packaging",
    "rollback_archive",
    "deterministic_normalization",
    "transient_controller_failure",
    "repeated_framework_failure",
]


def _validate_aware_datetime(value: datetime) -> datetime:
    """Require persisted approval evidence to identify an unambiguous instant."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("approval evidence timestamps must include a timezone offset")
    return value


AwareDateTime = Annotated[datetime, AfterValidator(_validate_aware_datetime)]


class ApprovalEnvelopeStrictModel(BaseModel):
    """Reject coercion, mutation, non-finite values, and undeclared approval fields."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        strict=True,
        frozen=True,
    )


class ApprovalArtifact(ApprovalEnvelopeStrictModel):
    """Bind one non-empty job-contained artifact to a normalized path and exact bytes."""

    artifact_id: PortableId
    kind: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)


class ApprovalV03Evidence(ApprovalEnvelopeStrictModel):
    """Provide the mandatory AQ v2 root identity for approval-envelope evidence."""

    schema_version: Literal["0.3.0"] = AUTONOMY_APPROVAL_ENVELOPE_SCHEMA_VERSION
    contract_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    root_authorization: ApprovalArtifact
    producer: str = Field(min_length=1, max_length=160)
    producer_version: Literal["0.3.0"] = AUTONOMY_APPROVAL_ENVELOPE_SCHEMA_VERSION
    created_at: AwareDateTime
    approval_count_effect: ApprovalCountEffect
    approval_count_justification: str = Field(min_length=1, max_length=1200)


class OnePromptV01Evidence(ApprovalEnvelopeStrictModel):
    """Provide the mandatory AQ v2 root identity for one-prompt evidence."""

    schema_version: Literal["0.1.0"] = AUTONOMY_ONE_PROMPT_SCHEMA_VERSION
    contract_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    root_authorization: ApprovalArtifact
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    producer: str = Field(min_length=1, max_length=160)
    producer_version: Literal["0.1.0"] = AUTONOMY_ONE_PROMPT_SCHEMA_VERSION
    created_at: AwareDateTime
    approval_count_effect: ApprovalCountEffect
    approval_count_justification: str = Field(min_length=1, max_length=1200)


class RoutineGatePolicy(ApprovalEnvelopeStrictModel):
    """Declare one deterministic gate rule without granting authority to a controller."""

    gate_kind: RoutineGateKind
    allowed_modes: list[ApprovalMode] = Field(min_length=1)
    bounded_transformation: BoundedTransformationKind | None = None
    requires_current_canonical_snapshot: Literal[True] = True
    requires_exact_target: Literal[True] = True
    host_policy_only: Literal[True] = True
    controller_eligibility_authority: Literal[False] = False
    user_approval_equivalent: Literal[False] = False
    technical_failure_category_allowed: Literal[False] = False
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_modes(self) -> RoutineGatePolicy:
        """Reject duplicate mode declarations in one deterministic routine-gate rule."""

        if len(self.allowed_modes) != len(set(self.allowed_modes)):
            raise ValueError("routine gate allowed modes must be unique")
        return self


class AutonomyApprovalPolicyProfile(ApprovalV03Evidence):
    """Freeze the deterministic routine-gate registry and bounded transformation caps."""

    profile_id: PortableId
    status: Literal["disabled_experimental"] = "disabled_experimental"
    supported_modes: list[ApprovalMode] = Field(min_length=3, max_length=3)
    routine_gate_policies: list[RoutineGatePolicy] = Field(min_length=1)
    allowed_bounded_transformations: list[BoundedTransformationKind] = Field(
        min_length=1
    )
    default_max_identity_splits: int = Field(default=4, ge=0, le=8)
    hard_max_identity_splits: Literal[8] = 8
    transient_controller_retry_limit: Literal[1] = 1
    technical_user_approval_allowed: Literal[False] = False
    policy_is_user_approval: Literal[False] = False
    repository_creates_codex_task: Literal[False] = False
    destination_project_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_profile_registry(self) -> AutonomyApprovalPolicyProfile:
        """Require complete modes, unique gates, and transformations covered by the profile."""

        if set(self.supported_modes) != {"autonomous", "checkpointed", "interactive"}:
            raise ValueError("approval policy profile must declare all three modes exactly once")
        gate_kinds = [item.gate_kind for item in self.routine_gate_policies]
        if len(gate_kinds) != len(set(gate_kinds)):
            raise ValueError("approval policy profile gate kinds must be unique")
        transformations = set(self.allowed_bounded_transformations)
        if len(transformations) != len(self.allowed_bounded_transformations):
            raise ValueError("approval policy transformations must be unique")
        if any(
            item.bounded_transformation is not None
            and item.bounded_transformation not in transformations
            for item in self.routine_gate_policies
        ):
            raise ValueError("routine gate uses a transformation outside its policy profile")
        return self


class AQV2ApprovalBudget(ApprovalV03Evidence):
    """Separate user decisions, policy actions, technical repairs, and terminal counters."""

    budget_id: PortableId
    policy_profile: ApprovalArtifact
    approval_mode: ApprovalMode
    initial_user_requests: Literal[1] = 1
    additional_user_decisions: int = Field(default=0, ge=0, le=64)
    geometry_user_approvals: int = Field(default=0, ge=0, le=64)
    material_user_approvals: int = Field(default=0, ge=0, le=64)
    delivery_user_approvals: int = Field(default=0, ge=0, le=64)
    scope_user_approvals: int = Field(default=0, ge=0, le=64)
    budget_user_approvals: int = Field(default=0, ge=0, le=64)
    destination_user_approvals: int = Field(default=0, ge=0, le=64)
    technical_user_approval_requests: Literal[0] = 0
    routine_policy_authorizations: int = Field(default=0, ge=0, le=256)
    technical_policy_repairs: int = Field(default=0, ge=0, le=256)
    controller_invocations: int = Field(default=0, ge=0, le=64)
    canonical_promotions: int = Field(default=0, ge=0, le=32)
    rollbacks: int = Field(default=0, ge=0, le=32)
    quality_terminals: int = Field(default=0, ge=0, le=1)
    delivery_terminals: int = Field(default=0, ge=0, le=1)
    imagegen_generations: int = Field(default=0, ge=0, le=32)
    blender_builds: int = Field(default=0, ge=0, le=64)
    quality_evaluations: int = Field(default=0, ge=0, le=64)
    delivery_runs: int = Field(default=0, ge=0, le=8)
    total_elapsed_actions: int = Field(default=0, ge=0, le=512)
    canonical_corruption_count: Literal[0] = 0
    max_additional_user_decisions: int = Field(ge=0, le=64)
    max_routine_policy_authorizations: int = Field(default=128, ge=1, le=256)
    max_total_elapsed_actions: int = Field(default=128, ge=1, le=512)

    @model_validator(mode="after")
    def validate_mode_budget(self) -> AQV2ApprovalBudget:
        """Enforce mode-specific user-decision caps and a zero technical-approval budget."""

        expected_cap = {"autonomous": 0, "checkpointed": 3}.get(self.approval_mode)
        if expected_cap is not None and self.max_additional_user_decisions != expected_cap:
            raise ValueError("approval budget user-decision cap differs from its mode")
        if self.additional_user_decisions > self.max_additional_user_decisions:
            raise ValueError("approval budget exceeds its user-decision cap")
        categorized = (
            self.geometry_user_approvals,
            self.material_user_approvals,
            self.delivery_user_approvals,
            self.scope_user_approvals,
            self.budget_user_approvals,
            self.destination_user_approvals,
        )
        if any(item > self.additional_user_decisions for item in categorized):
            raise ValueError("categorized user decisions exceed consolidated decisions")
        if self.routine_policy_authorizations > self.max_routine_policy_authorizations:
            raise ValueError("routine policy authorization budget is exhausted")
        if self.total_elapsed_actions > self.max_total_elapsed_actions:
            raise ValueError("one-prompt global action budget is exhausted")
        return self


class AutonomyApprovalEnvelope(ApprovalV03Evidence):
    """Bind explicit initial delegation to exact routine scopes without preapproving artifacts."""

    envelope_id: PortableId
    approval_mode: ApprovalMode
    policy_profile: ApprovalArtifact
    approval_budget: ApprovalArtifact
    initial_user_request_sha256: Sha256
    explicit_autonomy_delegation_observed: bool
    allowed_routine_gate_kinds: list[RoutineGateKind]
    allowed_bounded_transformations: list[BoundedTransformationKind]
    allowed_provider_scopes: list[ProviderScope] = Field(min_length=1)
    allowed_delivery_profiles: list[
        Literal["review_only", "portable_gltf", "portable_fbx"]
    ] = Field(min_length=1)
    requested_delivery_profiles: list[
        Literal["review_only", "portable_gltf", "portable_fbx"]
    ] = Field(min_length=1)
    allow_review_bundle_terminal: bool
    allow_automatic_rollback: bool
    allow_automatic_technical_retry: bool
    max_identity_splits: int = Field(default=4, ge=0, le=8)
    max_material_identities_created: int = Field(default=4, ge=0, le=8)
    max_controller_invocations: int = Field(ge=0, le=64)
    max_canonical_promotions: int = Field(ge=0, le=32)
    max_blender_builds: int = Field(ge=0, le=64)
    max_quality_evaluations: int = Field(ge=0, le=64)
    max_package_runs: int = Field(ge=0, le=8)
    expires_at: AwareDateTime
    status: ApprovalEnvelopeStatus = "active"
    future_artifacts_user_approved: Literal[False] = False
    policy_authorization_required_per_action: Literal[True] = True
    destination_project_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_delegated_scope(self) -> AutonomyApprovalEnvelope:
        """Keep delegation explicit, unique, bounded, and within its declared deliveries."""

        if self.approval_mode in {"autonomous", "checkpointed"} and not (
            self.explicit_autonomy_delegation_observed
        ):
            raise ValueError("autonomous and checkpointed envelopes require explicit delegation")
        unique_lists = (
            self.allowed_routine_gate_kinds,
            self.allowed_bounded_transformations,
            self.allowed_provider_scopes,
            self.allowed_delivery_profiles,
            self.requested_delivery_profiles,
        )
        if any(len(items) != len(set(items)) for items in unique_lists):
            raise ValueError("approval envelope scope lists must be unique")
        if not set(self.requested_delivery_profiles).issubset(
            self.allowed_delivery_profiles
        ):
            raise ValueError("requested deliveries exceed the approval envelope")
        if "review_only" in self.requested_delivery_profiles and len(
            self.requested_delivery_profiles
        ) > 1:
            raise ValueError("review_only cannot be combined with portable delivery")
        if self.max_material_identities_created < self.max_identity_splits:
            raise ValueError("material identity cap cannot be lower than split count cap")
        if (
            "bounded_material_identity_split" not in self.allowed_routine_gate_kinds
            and self.max_identity_splits != 0
        ):
            raise ValueError("identity split cap requires its exact routine gate")
        if self.status == "active" and self.expires_at <= self.created_at:
            raise ValueError("active approval envelope must expire after creation")
        return self


class AQV2RoutineGateEligibilityReport(ApprovalV03Evidence):
    """Record one host-recomputed routine-gate decision over exact current evidence."""

    report_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    approval_budget: ApprovalArtifact
    gate_kind: RoutineGateKind
    bounded_transformation: BoundedTransformationKind | None = None
    exact_target_artifact: ApprovalArtifact
    current_canonical_snapshot: ApprovalArtifact
    dependency_artifacts: list[ApprovalArtifact] = Field(default_factory=list)
    budget_before: AQV2ApprovalBudget
    budget_after: AQV2ApprovalBudget
    eligibility: Literal["passed", "failed"]
    decision_reasons: list[str] = Field(min_length=1)
    forbidden_conditions: list[str]
    previous_receipt: ApprovalArtifact | None = None
    determined_by: Literal["host_policy_engine"] = "host_policy_engine"
    controller_eligibility_authority: Literal[False] = False
    is_user_approval: Literal[False] = False

    @model_validator(mode="after")
    def validate_eligibility_outcome(self) -> AQV2RoutineGateEligibilityReport:
        """Require passed reports to be clean and project exactly one policy decision."""

        if self.eligibility == "passed" and self.forbidden_conditions:
            raise ValueError("passed policy eligibility cannot contain forbidden conditions")
        if self.eligibility == "failed" and not self.forbidden_conditions:
            raise ValueError("failed policy eligibility requires a forbidden condition")
        if self.budget_before.approval_mode != self.budget_after.approval_mode:
            raise ValueError("policy eligibility cannot change approval mode")
        if (
            self.budget_after.routine_policy_authorizations
            != self.budget_before.routine_policy_authorizations + 1
            or self.budget_after.total_elapsed_actions
            != self.budget_before.total_elapsed_actions + 1
        ):
            raise ValueError("policy eligibility must project one exact authorization action")
        return self


class AQV2RoutinePolicyAuthorization(ApprovalV03Evidence):
    """Authorize one exact eligible routine action once without representing user approval."""

    authorization_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    approval_budget: ApprovalArtifact
    eligibility_report: ApprovalArtifact
    gate_kind: RoutineGateKind
    bounded_transformation: BoundedTransformationKind | None = None
    exact_target_artifact: ApprovalArtifact
    current_canonical_snapshot: ApprovalArtifact
    dependency_artifacts: list[ApprovalArtifact] = Field(default_factory=list)
    budget_before: AQV2ApprovalBudget
    budget_after: AQV2ApprovalBudget
    decision_reasons: list[str] = Field(min_length=1)
    forbidden_conditions: list[str] = Field(max_length=0)
    previous_receipt: ApprovalArtifact | None = None
    issued_by: Literal["host_policy_engine"] = "host_policy_engine"
    authorization_status: Literal["issued"] = "issued"
    single_use: Literal[True] = True
    exact_target_only: Literal[True] = True
    is_user_approval: Literal[False] = False
    approved_by_user: Literal[False] = False
    synthetic_user_approval: Literal[False] = False

    @model_validator(mode="after")
    def validate_authorized_budget(self) -> AQV2RoutinePolicyAuthorization:
        """Require an issued authorization to carry one monotonic projected budget action."""

        if (
            self.budget_after.routine_policy_authorizations
            != self.budget_before.routine_policy_authorizations + 1
            or self.budget_after.total_elapsed_actions
            != self.budget_before.total_elapsed_actions + 1
        ):
            raise ValueError("routine policy authorization must consume one projected action")
        return self


class AQV2PolicyDecisionReceipt(ApprovalV03Evidence):
    """Consume one routine policy authorization and bind its exact host action result."""

    receipt_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    policy_authorization: ApprovalArtifact
    eligibility_report: ApprovalArtifact
    gate_kind: RoutineGateKind
    exact_target_artifact: ApprovalArtifact
    canonical_snapshot_before: ApprovalArtifact
    canonical_snapshot_after: ApprovalArtifact
    action_result: ApprovalArtifact | None = None
    outcome: Literal["applied", "rejected", "rolled_back", "technical_failed"]
    budget_before: AQV2ApprovalBudget
    budget_after: AQV2ApprovalBudget
    previous_receipt: ApprovalArtifact | None = None
    decision_reasons: list[str] = Field(min_length=1)
    authorization_consumption_ordinal: Literal[1] = 1
    authorization_consumed_once: Literal[True] = True
    consumed_at: AwareDateTime
    is_user_approval: Literal[False] = False
    approved_by_user: Literal[False] = False
    canonical_corruption: Literal[False] = False

    @model_validator(mode="after")
    def validate_decision_result(self) -> AQV2PolicyDecisionReceipt:
        """Require applied decisions to name a result and preserve the authorized budget."""

        if self.outcome == "applied" and self.action_result is None:
            raise ValueError("applied policy decision requires an exact action result")
        if self.budget_after.routine_policy_authorizations != (
            self.budget_before.routine_policy_authorizations + 1
        ):
            raise ValueError("policy decision receipt budget differs from its authorization")
        return self


class EscalationChoice(ApprovalEnvelopeStrictModel):
    """Describe one bounded user-selectable response and its complete impact."""

    choice_id: PortableId
    label: str = Field(min_length=1, max_length=300)
    impact: str = Field(min_length=1, max_length=1200)
    additional_budget_actions: int = Field(default=0, ge=0, le=512)
    changed_scope: list[str] = Field(default_factory=list)
    review_bundle_if_not_selected: bool


class EscalationDecisionItem(ApprovalEnvelopeStrictModel):
    """Consolidate one genuine user-only question and all currently known choices."""

    item_id: PortableId
    reason: EscalationReason
    question: str = Field(min_length=1, max_length=1200)
    choices: list[EscalationChoice] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_choices(self) -> EscalationDecisionItem:
        """Reject duplicate choices within one consolidated decision item."""

        choice_ids = [item.choice_id for item in self.choices]
        if len(choice_ids) != len(set(choice_ids)):
            raise ValueError("consolidated escalation choice IDs must be unique")
        return self


class AQV2ConsolidatedEscalationRequest(ApprovalV03Evidence):
    """Present all known genuine user decisions as one non-approval request payload."""

    escalation_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    approval_budget: ApprovalArtifact
    current_best_candidate: ApprovalArtifact
    completed_evidence: list[ApprovalArtifact] = Field(min_length=1)
    decisions: list[EscalationDecisionItem] = Field(min_length=1)
    total_additional_budget_actions: int = Field(ge=0, le=512)
    changed_scope: list[str]
    review_bundle_if_no_decision: ApprovalArtifact | None = None
    single_decision_payload_required: Literal[True] = True
    individual_approval_request_count: Literal[0] = 0
    is_user_approval: Literal[False] = False
    status: Literal["pending", "decided", "review_terminal"] = "pending"

    @model_validator(mode="after")
    def validate_consolidation(self) -> AQV2ConsolidatedEscalationRequest:
        """Require unique decision items and an exact review fallback when promised."""

        item_ids = [item.item_id for item in self.decisions]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("consolidated escalation decision item IDs must be unique")
        if self.status == "review_terminal" and self.review_bundle_if_no_decision is None:
            raise ValueError("review-terminal escalation requires an exact review bundle")
        expected_actions = sum(
            max(choice.additional_budget_actions for choice in item.choices)
            for item in self.decisions
        )
        if self.total_additional_budget_actions != expected_actions:
            raise ValueError("escalation budget impact differs from its complete choice set")
        expected_scope = list(
            dict.fromkeys(
                scope
                for item in self.decisions
                for choice in item.choices
                for scope in choice.changed_scope
            )
        )
        if self.changed_scope != expected_scope:
            raise ValueError("escalation changed scope differs from its complete choice set")
        return self


class EscalationSelection(ApprovalEnvelopeStrictModel):
    """Bind one selected choice to the exact consolidated decision item."""

    item_id: PortableId
    choice_id: PortableId


class AQV2EscalationDecision(ApprovalV03Evidence):
    """Record one exact user payload resolving a consolidated escalation request."""

    decision_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    approval_budget: ApprovalArtifact
    escalation_request: ApprovalArtifact
    selections: list[EscalationSelection] = Field(min_length=1)
    budget_before: AQV2ApprovalBudget
    budget_after: AQV2ApprovalBudget
    decision_payload_sha256: Sha256
    decided_by: Literal["user"] = "user"
    explicit_user_decision_observed: Literal[True] = True
    additional_user_decision_count: Literal[1] = 1
    individual_approval_artifacts_created: Literal[0] = 0
    decided_at: AwareDateTime

    @model_validator(mode="after")
    def validate_selections(self) -> AQV2EscalationDecision:
        """Require exactly one selected choice for each referenced decision item."""

        item_ids = [item.item_id for item in self.selections]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("escalation decision cannot select one item more than once")
        if (
            self.budget_after.additional_user_decisions
            != self.budget_before.additional_user_decisions + 1
            or self.budget_after.total_elapsed_actions
            != self.budget_before.total_elapsed_actions + 1
        ):
            raise ValueError("one consolidated escalation must consume one user decision")
        return self


class AQV2ApprovalTelemetryReport(ApprovalV03Evidence):
    """Report approval-minimization counters replayed from immutable session evidence."""

    report_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    source_artifacts: list[ApprovalArtifact] = Field(min_length=1)
    initial_user_request_count: Literal[1] = 1
    additional_user_decision_count: int = Field(ge=0, le=64)
    technical_user_approval_request_count: Literal[0] = 0
    geometry_user_approval_count: int = Field(ge=0, le=64)
    material_user_approval_count: int = Field(ge=0, le=64)
    scope_user_approval_count: int = Field(ge=0, le=64)
    delivery_user_approval_count: int = Field(ge=0, le=64)
    routine_policy_authorization_count: int = Field(ge=0, le=256)
    technical_repair_count: int = Field(ge=0, le=256)
    controller_invocation_count: int = Field(ge=0, le=64)
    canonical_promotion_count: int = Field(ge=0, le=32)
    rollback_count: int = Field(ge=0, le=32)
    imagegen_generation_count: int = Field(ge=0, le=32)
    blender_build_count: int = Field(ge=0, le=64)
    quality_evaluation_count: int = Field(ge=0, le=64)
    delivery_run_count: int = Field(ge=0, le=8)
    terminal_type: OnePromptTerminalType
    total_elapsed_actions: int = Field(ge=0, le=512)
    budget_consumed: AQV2ApprovalBudget
    canonical_corruption_count: Literal[0] = 0
    counters_replayed_by_host: Literal[True] = True
    human_review_performed: bool

    @model_validator(mode="after")
    def validate_telemetry_mode(self) -> AQV2ApprovalTelemetryReport:
        """Apply autonomous and checkpointed decision caps to replayed telemetry."""

        mode = self.budget_consumed.approval_mode
        if mode == "autonomous" and self.additional_user_decision_count != 0:
            raise ValueError("autonomous success telemetry cannot contain extra user decisions")
        if mode == "checkpointed" and self.additional_user_decision_count > 3:
            raise ValueError("checkpointed telemetry exceeds three user decisions")
        if self.total_elapsed_actions != self.budget_consumed.total_elapsed_actions:
            raise ValueError("telemetry action count differs from its exact budget snapshot")
        return self


class AQV2TechnicalFailureReport(ApprovalV03Evidence):
    """Close an unrecoverable technical branch without requesting a user decision."""

    failure_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    approval_budget: ApprovalArtifact
    category: TechnicalFailureCategory
    current_state: ApprovalArtifact
    failure_evidence: list[ApprovalArtifact] = Field(min_length=1)
    automatic_repair_attempted: bool
    transient_retry_count: int = Field(ge=0, le=1)
    retry_exhausted: bool
    canonical_restored_or_unchanged: Literal[True] = True
    user_approval_requested: Literal[False] = False
    status: Literal["blocked"] = "blocked"

    @model_validator(mode="after")
    def validate_retry_terminal(self) -> AQV2TechnicalFailureReport:
        """Require exhausted retry state to agree with the bounded technical attempt count."""

        if self.retry_exhausted and not (
            self.automatic_repair_attempted or self.transient_retry_count == 1
        ):
            raise ValueError("retry exhaustion requires one attempted technical recovery")
        return self


class AQV2OnePromptRunPlan(OnePromptV01Evidence):
    """Bind a bounded geometry-to-delivery supervisor to one exact approval envelope."""

    plan_id: PortableId
    approval_budget: ApprovalArtifact
    base_autonomy_plan: ApprovalArtifact
    initial_autonomy_state: ApprovalArtifact
    approval_mode: ApprovalMode
    phases: list[Literal["geometry", "material", "quality", "delivery", "terminal"]]
    requested_delivery_profiles: list[
        Literal["review_only", "portable_gltf", "portable_fbx"]
    ] = Field(min_length=1)
    controller_execution_mode: Literal["desktop_in_session", "client_mediated"]
    global_action_limit: int = Field(ge=1, le=512)
    only_waits_for_consolidated_escalation: bool
    routine_approval_wait_allowed: bool
    repository_creates_codex_task: Literal[False] = False
    app_close_background_execution: Literal[False] = False
    resume_same_state_budget_assignment: Literal[True] = True
    destination_project_write: Literal[False] = False
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    status: Literal["planned", "running", "cancelled"] = "planned"

    @model_validator(mode="after")
    def validate_phase_order(self) -> AQV2OnePromptRunPlan:
        """Require fixed phases and preserve interactive legacy approval waits."""

        if self.phases != ["geometry", "material", "quality", "delivery", "terminal"]:
            raise ValueError("one-prompt phases must use the fixed bounded order")
        if len(self.requested_delivery_profiles) != len(
            set(self.requested_delivery_profiles)
        ):
            raise ValueError("one-prompt requested delivery profiles must be unique")
        if self.approval_mode == "interactive":
            if self.only_waits_for_consolidated_escalation:
                raise ValueError("interactive one-prompt must preserve legacy approval waits")
            if not self.routine_approval_wait_allowed:
                raise ValueError("interactive one-prompt must allow legacy approval waits")
        elif not self.only_waits_for_consolidated_escalation:
            raise ValueError("policy one-prompt may wait only for consolidated escalation")
        elif self.routine_approval_wait_allowed:
            raise ValueError("policy one-prompt cannot wait for routine user approval")
        return self


class AQV2OnePromptRunTerminal(OnePromptV01Evidence):
    """Close one-prompt execution with exact production, review, escalation, or failure evidence."""

    terminal_id: PortableId
    one_prompt_plan: ApprovalArtifact
    final_autonomy_state: ApprovalArtifact
    terminal_type: OnePromptTerminalType
    delivery_terminal: ApprovalArtifact | None = None
    review_bundle: ApprovalArtifact | None = None
    consolidated_escalation: ApprovalArtifact | None = None
    framework_change_justification: ApprovalArtifact | None = None
    framework_failure_report: ApprovalArtifact | None = None
    approval_telemetry: ApprovalArtifact
    canonical_corruption_count: Literal[0] = 0
    canonical_restored_after_rollback: bool
    destination_project_write: Literal[False] = False
    background_execution_claimed: Literal[False] = False
    repository_task_spawn_claimed: Literal[False] = False

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> AQV2OnePromptRunTerminal:
        """Require one exact evidence shape for each one-prompt terminal type."""

        named = {
            "delivery": self.delivery_terminal,
            "review": self.review_bundle,
            "escalation": self.consolidated_escalation,
            "framework": self.framework_failure_report,
            "justification": self.framework_change_justification,
        }
        if self.terminal_type == "production_delivery":
            if named["delivery"] is None or any(
                named[key] is not None for key in ("review", "escalation", "framework")
            ):
                raise ValueError("production terminal requires only delivery evidence")
        elif self.terminal_type == "review_bundle":
            if named["review"] is None or any(
                named[key] is not None for key in ("delivery", "escalation", "framework")
            ):
                raise ValueError("review terminal requires only review evidence")
        elif self.terminal_type == "genuine_escalation":
            if named["escalation"] is None or any(
                named[key] is not None for key in ("delivery", "review", "framework")
            ):
                raise ValueError("escalation terminal requires only consolidated escalation")
        elif self.terminal_type == "blocked":
            if named["framework"] is None or named["justification"] is None:
                raise ValueError("blocked terminal requires framework failure and justification")
            if any(named[key] is not None for key in ("delivery", "review", "escalation")):
                raise ValueError("blocked terminal cannot claim delivery, review, or escalation")
        elif any(named[key] is not None for key in ("delivery", "review", "escalation")):
            raise ValueError("cancelled terminal cannot claim successful terminal evidence")
        return self


class FrameworkChangeJustification(ApprovalEnvelopeStrictModel):
    """Classify a failure before permitting reusable public framework changes."""

    schema_version: Literal["0.1.0"] = FRAMEWORK_CHANGE_JUSTIFICATION_SCHEMA_VERSION
    contract_id: PortableId
    justification_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    root_authorization: ApprovalArtifact
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    classification: FrameworkChangeClassification
    issue_summary: str = Field(min_length=1, max_length=1600)
    generic_fixture_kinds: list[PortableId]
    affected_job_ids: list[JobId]
    violated_invariant_ids: list[PortableId]
    evidence_artifacts: list[ApprovalArtifact] = Field(min_length=1)
    public_framework_change_allowed: bool
    new_public_schema_allowed: bool
    new_public_cli_allowed: bool
    new_approval_type_allowed: bool
    job_local_candidate_fix_required: bool
    decision_reasons: list[str] = Field(min_length=1)
    producer: str = Field(min_length=1, max_length=160)
    producer_version: Literal["0.1.0"] = FRAMEWORK_CHANGE_JUSTIFICATION_SCHEMA_VERSION
    created_at: AwareDateTime
    approval_count_effect: ApprovalCountEffect
    approval_count_justification: str = Field(min_length=1, max_length=1200)

    @model_validator(mode="after")
    def validate_framework_threshold(self) -> FrameworkChangeJustification:
        """Permit public changes only for reusable evidence or an explicit invariant breach."""

        reusable = (
            len(set(self.generic_fixture_kinds)) >= 2
            or len(set(self.affected_job_ids)) >= 2
            or bool(self.violated_invariant_ids)
        )
        if self.public_framework_change_allowed and not reusable:
            raise ValueError("public framework change lacks reusable or invariant evidence")
        if self.classification == "job_local_candidate_error":
            if any(
                (
                    self.public_framework_change_allowed,
                    self.new_public_schema_allowed,
                    self.new_public_cli_allowed,
                    self.new_approval_type_allowed,
                )
            ) or not self.job_local_candidate_fix_required:
                raise ValueError(
                    "job-local candidate errors cannot create public framework surface"
                )
        if self.new_approval_type_allowed and self.approval_count_effect != "increases":
            raise ValueError(
                "a new approval type must explicitly record its approval-count increase"
            )
        return self


class HistoricalSessionAutonomyEligibilityReport(ApprovalV03Evidence):
    """Evaluate historical evidence read-only without granting retroactive policy authority."""

    report_id: PortableId
    policy_profile: ApprovalArtifact
    historical_session_artifacts: list[ApprovalArtifact] = Field(min_length=1)
    evaluated_gate_kind: RoutineGateKind
    future_bounded_conditions_satisfied: bool
    condition_results: dict[str, bool]
    policy_authorization_that_could_have_applied: RoutineGateKind | None = None
    additional_user_decision_would_have_been_required: bool
    decision_reasons: list[str] = Field(min_length=1)
    approval_envelope_existed_historically: Literal[False] = False
    retroactive_authority_applied: Literal[False] = False
    historical_user_approval_reclassified: Literal[False] = False
    canonical_apply_performed: Literal[False] = False
    report_is_read_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_historical_hypothesis(self) -> HistoricalSessionAutonomyEligibilityReport:
        """Keep hypothetical policy eligibility consistent with its bounded condition results."""

        all_conditions = bool(self.condition_results) and all(self.condition_results.values())
        if self.future_bounded_conditions_satisfied != all_conditions:
            raise ValueError("historical eligibility summary differs from condition results")
        if self.future_bounded_conditions_satisfied and (
            self.policy_authorization_that_could_have_applied != self.evaluated_gate_kind
        ):
            raise ValueError("eligible historical report must name the evaluated policy gate")
        if not self.future_bounded_conditions_satisfied and (
            self.policy_authorization_that_could_have_applied is not None
        ):
            raise ValueError("ineligible historical evidence cannot name applicable authority")
        return self
