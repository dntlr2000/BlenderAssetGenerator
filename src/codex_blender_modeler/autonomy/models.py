"""Strict Autonomous Quality 0.1.0 machine-readable contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

SCHEMA_VERSION = "0.1.0"

AutonomyPhase = Literal[
    "reference_evidence",
    "initial_candidates",
    "structural_authoring",
    "parametric_convergence",
    "material_authoring",
    "integrated_quality",
    "production_repair",
    "optimization",
    "package",
    "review_bundle",
    "terminal",
]
AutonomyStatus = Literal[
    "planned",
    "running",
    "waiting_for_controller",
    "completed",
    "blocked",
    "cancelled",
    "failed",
]
AutonomyNextAction = Literal[
    "collect_reference_evidence",
    "author_initial_candidate",
    "evaluate_candidate",
    "promote_best_candidate",
    "advance_production",
    "await_controller_output",
    "run_structural_round",
    "run_parametric_iteration",
    "run_material_round",
    "run_integrated_quality",
    "authorize_routine_gate",
    "run_optimization",
    "build_package",
    "build_review_bundle",
    "terminalize",
    "none",
]
TerminalReason = Literal[
    "quality_target_reached",
    "plateau",
    "duplicate_candidate_state",
    "oscillation_detected",
    "no_eligible_candidates",
    "structural_budget_exhausted",
    "parametric_budget_exhausted",
    "material_budget_exhausted",
    "package_repair_budget_exhausted",
    "global_budget_exhausted",
    "repeated_failure",
    "structural_regression",
    "constraint_regression",
    "unscorable_evidence",
    "restricted_scope_required",
    "stale_or_tampered",
    "cancelled",
    "host_failure",
    "completed_review_bundle",
]
PolicyGateKind = Literal[
    "generic_proxy_review",
    "generic_detail_review",
    "material_swatch_acknowledgement",
    "structural_candidate_promotion",
    "bounded_convergence_plan",
    "bounded_convergence_candidate",
    "material_candidate_promotion",
    "qa_review_acknowledgement",
    "optimization_plan",
    "final_package_acknowledgement",
    "destination_handoff_envelope_plan",
]
CandidatePhase = Literal["initial", "structural", "parametric"]


class AQStrictModel(BaseModel):
    """Reject undeclared fields and non-finite floats in AQ contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class AutonomyArtifact(AQStrictModel):
    """Bind one contained artifact to its repository-relative path and exact bytes."""

    path: RelativePath
    sha256: Sha256


class AutonomyEvidenceContract(AQStrictModel):
    """Provide common immutable identity, ownership, input, and provenance fields."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    contract_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: str = Field(min_length=1, max_length=128)
    producer_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provenance: list[AutonomyArtifact] = Field(min_length=1)
    created_at: datetime


class AutonomyBudget(AQStrictModel):
    """Declare immutable bounded work allowances for one autonomy session."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    budget_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: str = Field(default="codex_blender_modeler.autonomy", min_length=1)
    producer_version: Literal["0.1.0"] = SCHEMA_VERSION
    provenance: list[AutonomyArtifact] = Field(min_length=1)
    initial_candidates: int = Field(default=3, ge=1, le=4)
    structural_rounds: int = Field(default=2, ge=0, le=3)
    candidates_per_structural_round: int = Field(default=2, ge=1, le=3)
    parametric_convergence_iterations: int = Field(default=3, ge=0, le=5)
    material_rounds: int = Field(default=2, ge=0, le=3)
    package_repairs: int = Field(default=1, ge=0, le=2)
    total_blender_builds: int = Field(default=12, ge=1, le=18)
    total_quality_evaluations: int = Field(default=8, ge=1, le=12)
    canonical_promotions: int = Field(default=5, ge=0, le=8)
    plateau_patience: int = Field(default=1, ge=1, le=2)
    repeated_identical_failure_limit: int = Field(default=1, ge=1, le=2)
    global_action_limit: int = Field(default=64, ge=1, le=128)
    created_at: datetime


class BudgetUsage(AQStrictModel):
    """Count consumed actions without changing the authorized budget."""

    initial_candidates: int = Field(default=0, ge=0)
    structural_rounds: int = Field(default=0, ge=0)
    parametric_convergence_iterations: int = Field(default=0, ge=0)
    material_rounds: int = Field(default=0, ge=0)
    package_repairs: int = Field(default=0, ge=0)
    total_blender_builds: int = Field(default=0, ge=0)
    total_quality_evaluations: int = Field(default=0, ge=0)
    canonical_promotions: int = Field(default=0, ge=0)
    total_actions: int = Field(default=0, ge=0)


class AutonomyProfile(AutonomyEvidenceContract):
    """Snapshot one verified or explicitly experimental autonomy policy."""

    profile_id: Literal[
        "autonomous_static_prop_v1",
        "autonomous_environment_v1",
        "autonomous_architecture_v1",
        "autonomous_measured_asset_v1",
    ]
    status: Literal["verified_active", "disabled_experimental"]
    production_mode: Literal["autonomous_profile"] = "autonomous_profile"
    underlying_execution_policy: Literal["standard"] = "standard"
    allowed_mode: Literal["concept"] = "concept"
    reference_content_scope: Literal["primary_object_only"] = "primary_object_only"
    output_profile: Literal["portable_gltf"] = "portable_gltf"
    allowed_asset_kinds: list[Literal["static_hard_surface", "static_prop"]]
    allowed_gate_kinds: list[PolicyGateKind]
    prohibited_capabilities: list[str] = Field(min_length=1)
    default_budget: AutonomyBudget
    quality_gate_profile: AutonomyArtifact
    optional_destination_handoff_envelope: bool = True

    @model_validator(mode="after")
    def validate_activation(self) -> AutonomyProfile:
        """Permit only the static-prop profile to claim verified activation."""

        if self.profile_id == "autonomous_static_prop_v1":
            if self.status != "verified_active":
                raise ValueError("autonomous_static_prop_v1 must be verified_active")
        elif self.status != "disabled_experimental":
            raise ValueError("future autonomy profiles must remain disabled_experimental")
        return self


class RootAuthorization(AutonomyEvidenceContract):
    """Bind one initial user request to a fixed autonomy scope and immutable budget."""

    authorization_id: PortableId
    authorization_source: Literal["initial_user_request"] = "initial_user_request"
    original_request_sha256: Sha256
    production_launch_or_binding: AutonomyArtifact
    primary_reference: AutonomyArtifact
    autonomy_profile: AutonomyArtifact
    reference_content_scope: Literal["primary_object_only"] = "primary_object_only"
    target_subject: str = Field(min_length=1, max_length=256)
    output_profile: Literal["portable_gltf"] = "portable_gltf"
    allowed_gate_kinds: list[PolicyGateKind] = Field(min_length=1)
    prohibited_scopes: list[str] = Field(min_length=1)
    budget: AutonomyArtifact
    status: Literal["active", "expired", "cancelled"] = "active"
    expires_at: datetime | None = None
    cancelled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> RootAuthorization:
        """Keep active, expired, and cancelled lifecycle evidence internally consistent."""

        if self.status == "cancelled" and self.cancelled_at is None:
            raise ValueError("cancelled root authorization requires cancelled_at")
        if self.status != "cancelled" and self.cancelled_at is not None:
            raise ValueError("cancelled_at is valid only for cancelled authorization")
        return self


class AutonomyPlan(AutonomyEvidenceContract):
    """Bind one bounded supervisor plan to an existing standard production dispatch."""

    session_id: PortableId
    profile: AutonomyArtifact
    budget: AutonomyArtifact
    root_authorization: AutonomyArtifact
    production_dispatch_plan: AutonomyArtifact
    production_controller_plan: AutonomyArtifact
    underlying_execution_policy: Literal["standard"] = "standard"
    reference_content_scope: Literal["primary_object_only"] = "primary_object_only"
    target_subject: str = Field(min_length=1, max_length=256)
    output_profile: Literal["portable_gltf"] = "portable_gltf"
    include_destination_handoff_envelope: bool = False
    initial_candidate_limit: int = Field(default=3, ge=1, le=4)
    max_parallel_read_only_advisors: int = Field(default=3, ge=1, le=3)
    canonical_writer: Literal["controller_only"] = "controller_only"
    action_limit: int = Field(default=64, ge=1, le=128)


class AutonomyControllerBinding(AutonomyEvidenceContract):
    """Bind the autonomy supervisor to the exact production launch/controller evidence."""

    binding_id: PortableId
    session_id: PortableId
    controller_id: PortableId
    production_launch: AutonomyArtifact
    production_controller_plan: AutonomyArtifact
    execution_mode: Literal["client_mediated", "desktop_in_session"]
    canonical_write_authority: Literal["controller_only"] = "controller_only"
    bound_at: datetime


class PolicyAuthorization(AutonomyEvidenceContract):
    """Authorize one exact routine gate through policy rather than user approval."""

    authorization_id: PortableId
    authorization_source: Literal["preauthorized_profile"] = "preauthorized_profile"
    decided_by: Literal["autonomy_policy_engine"] = "autonomy_policy_engine"
    root_authorization: AutonomyArtifact
    root_authorization_sha256: Sha256
    profile: AutonomyArtifact
    profile_sha256: Sha256
    budget: AutonomyArtifact
    workflow_step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    workflow_input_fingerprint: Sha256
    gate_kind: PolicyGateKind
    gate_target: AutonomyArtifact
    target_artifact: AutonomyArtifact
    decision_reasons: list[str] = Field(min_length=1)
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    previous_authorization_sha256: Sha256 | None = None
    single_use: Literal[True] = True
    consumed: bool = False
    consumed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_consumption(self) -> PolicyAuthorization:
        """Require one consumed action and monotonic accounting for every usage counter."""

        if self.consumed != (self.consumed_at is not None):
            raise ValueError("policy consumption flag and timestamp must agree")
        before = self.budget_before.model_dump()
        after = self.budget_after.model_dump()
        decreased = [field for field, value in before.items() if after[field] < value]
        if decreased:
            raise ValueError(
                f"policy authorization cannot decrease budget usage: {decreased}"
            )
        if self.consumed and (
            self.budget_after.total_actions != self.budget_before.total_actions + 1
        ):
            raise ValueError("consumed policy authorization must use exactly one action")
        return self


class PolicyGateTarget(AutonomyEvidenceContract):
    """Freeze the exact workflow boundary evaluated by one policy authorization."""

    target_id: PortableId
    session_id: PortableId
    workflow_step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    workflow_input_fingerprint: Sha256
    gate_kind: PolicyGateKind
    workflow_plan: AutonomyArtifact
    dependency_completion_fingerprints: dict[str, Sha256] = Field(default_factory=dict)
    dependency_artifacts: list[AutonomyArtifact] = Field(default_factory=list)
    requested_decision: Literal["authorize_exact_routine_gate"] = (
        "authorize_exact_routine_gate"
    )


def _validate_structural_evidence_bundle(
    scene_spec_v03: AutonomyArtifact | None,
    compiled_scene_spec: AutonomyArtifact | None,
    recipes: list[AutonomyArtifact],
    mesh_payloads: list[AutonomyArtifact],
    materialization_receipts: list[AutonomyArtifact],
) -> None:
    """Require a complete equal-cardinality structural evidence bundle or no bundle."""

    counts = (len(recipes), len(mesh_payloads), len(materialization_receipts))
    if scene_spec_v03 is None:
        if compiled_scene_spec is not None or any(counts):
            raise ValueError("structural evidence requires its exact SceneSpecV03 source")
        return
    if compiled_scene_spec is None or not all(counts) or len(set(counts)) != 1:
        raise ValueError(
            "SceneSpecV03 evidence requires one compiled SceneSpec and equal non-empty "
            "recipe, mesh-payload, and materialization-receipt lists"
        )


class CandidateAuthoringAssignment(AutonomyEvidenceContract):
    """Describe controller-only files required for one isolated initial candidate."""

    assignment_id: PortableId
    session_id: PortableId
    candidate_id: PortableId
    candidate_index: int = Field(ge=1, le=4)
    candidate_phase: CandidatePhase = "initial"
    round_index: int = Field(default=0, ge=0, le=5)
    reference_evidence: AutonomyArtifact
    camera_hypothesis_set: AutonomyArtifact
    workflow_modeling_plan: AutonomyArtifact | None = None
    workflow_scene_spec: AutonomyArtifact | None = None
    baseline_evaluation: AutonomyArtifact | None = None
    output_root: RelativePath
    required_outputs: list[RelativePath] = Field(min_length=3)
    scene_spec_v03_output: RelativePath | None = None
    authoring_prompt_sha256: Sha256
    canonical_write_authority: Literal["controller_only"] = "controller_only"
    advisor_write_authority: Literal["none"] = "none"

    @model_validator(mode="after")
    def validate_structural_output(self) -> CandidateAuthoringAssignment:
        """Keep an optional SceneSpecV03 source fixed inside non-parametric candidate staging."""

        if self.scene_spec_v03_output is None:
            return self
        expected = f"{self.output_root}/scene_spec_v03.json"
        if self.scene_spec_v03_output != expected:
            raise ValueError("SceneSpecV03 output must use the fixed candidate-owned path")
        if self.candidate_phase == "parametric":
            raise ValueError("parametric candidates cannot author structural SceneSpecV03")
        return self


class CandidateCompletionMarker(AutonomyEvidenceContract):
    """Bind controller-authored candidate outputs to one exact immutable assignment."""

    completion_id: PortableId
    session_id: PortableId
    candidate_id: PortableId
    assignment: AutonomyArtifact
    authoring_prompt_sha256: Sha256
    modeling_plan: AutonomyArtifact
    camera_hypothesis: AutonomyArtifact
    scene_spec_candidate: AutonomyArtifact
    scene_spec_v03_candidate: AutonomyArtifact | None = None
    compiled_scene_spec_candidate: AutonomyArtifact | None = None
    structural_recipes: list[AutonomyArtifact] = Field(default_factory=list)
    structural_mesh_payloads: list[AutonomyArtifact] = Field(default_factory=list)
    structural_materialization_receipts: list[AutonomyArtifact] = Field(default_factory=list)
    completed_by: Literal["controller"] = "controller"
    canonical_written: Literal[False] = False

    @model_validator(mode="after")
    def validate_structural_evidence(self) -> CandidateCompletionMarker:
        """Reject partial structural materialization evidence in a completion marker."""

        _validate_structural_evidence_bundle(
            self.scene_spec_v03_candidate,
            self.compiled_scene_spec_candidate,
            self.structural_recipes,
            self.structural_mesh_payloads,
            self.structural_materialization_receipts,
        )
        return self


class StructuralCandidatePlan(AutonomyEvidenceContract):
    """Plan one isolated structural candidate without granting canonical write authority."""

    candidate_id: PortableId
    candidate_index: int = Field(ge=1, le=4)
    modeling_plan: AutonomyArtifact
    camera_hypothesis: AutonomyArtifact
    scene_spec_candidate: AutonomyArtifact
    scene_spec_v03_candidate: AutonomyArtifact | None = None
    compiled_scene_spec_candidate: AutonomyArtifact | None = None
    structural_recipes: list[AutonomyArtifact] = Field(default_factory=list)
    structural_mesh_payloads: list[AutonomyArtifact] = Field(default_factory=list)
    structural_materialization_receipts: list[AutonomyArtifact] = Field(default_factory=list)
    affected_semantic_ids: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    expected_improvements: list[str] = Field(min_length=1)
    exact_input_map: dict[RelativePath, Sha256] = Field(min_length=1)
    authoring_prompt_sha256: Sha256
    canonical_write_authority: Literal["controller_only"] = "controller_only"

    @model_validator(mode="after")
    def validate_structural_evidence(self) -> StructuralCandidatePlan:
        """Require every optional structural plan input and derived output to stay bound."""

        _validate_structural_evidence_bundle(
            self.scene_spec_v03_candidate,
            self.compiled_scene_spec_candidate,
            self.structural_recipes,
            self.structural_mesh_payloads,
            self.structural_materialization_receipts,
        )
        return self


class StructuralCandidateManifest(AutonomyEvidenceContract):
    """Bind one built candidate to its exact staging outputs and completion marker."""

    candidate_id: PortableId
    plan: AutonomyArtifact
    scene_spec: AutonomyArtifact
    scene_spec_v03_candidate: AutonomyArtifact | None = None
    compiled_scene_spec_candidate: AutonomyArtifact | None = None
    structural_recipes: list[AutonomyArtifact] = Field(default_factory=list)
    structural_mesh_payloads: list[AutonomyArtifact] = Field(default_factory=list)
    structural_materialization_receipts: list[AutonomyArtifact] = Field(default_factory=list)
    completion_marker: AutonomyArtifact
    blend: AutonomyArtifact
    inventory: AutonomyArtifact
    validation: AutonomyArtifact
    low_resolution_renders: list[AutonomyArtifact] = Field(min_length=1)
    integrated_quality_report: AutonomyArtifact
    status: Literal["evaluated", "invalid", "failed"]
    canonical_promoted: Literal[False] = False

    @model_validator(mode="after")
    def validate_structural_evidence(self) -> StructuralCandidateManifest:
        """Keep the built manifest bound to every optional structural source and receipt."""

        _validate_structural_evidence_bundle(
            self.scene_spec_v03_candidate,
            self.compiled_scene_spec_candidate,
            self.structural_recipes,
            self.structural_mesh_payloads,
            self.structural_materialization_receipts,
        )
        if (
            self.compiled_scene_spec_candidate is not None
            and self.scene_spec != self.compiled_scene_spec_candidate
        ):
            raise ValueError("structural manifest must build the exact compiled SceneSpec")
        return self


class CandidateMetricVector(AQStrictModel):
    """Preserve comparable multi-axis candidate evidence without one canonical score."""

    hard_gate_failures: int = Field(ge=0)
    critical_regressions: int = Field(ge=0)
    reference_fidelity: float | None = Field(default=None, ge=0, le=1)
    silhouette_iou: float | None = Field(default=None, ge=0, le=1)
    structural_quality: float | None = Field(default=None, ge=0, le=1)
    material_quality: float | None = Field(default=None, ge=0, le=1)
    production_quality: float | None = Field(default=None, ge=0, le=1)
    change_magnitude: float = Field(ge=0)


class CandidateEvaluation(AutonomyEvidenceContract):
    """Record immutable lexicographic/Pareto evidence for one candidate."""

    evaluation_id: PortableId
    candidate_id: PortableId
    candidate_manifest: AutonomyArtifact
    baseline_evaluation: AutonomyArtifact | None = None
    scene_spec_v03_candidate: AutonomyArtifact | None = None
    compiled_scene_spec_candidate: AutonomyArtifact | None = None
    structural_recipes: list[AutonomyArtifact] = Field(default_factory=list)
    structural_mesh_payloads: list[AutonomyArtifact] = Field(default_factory=list)
    structural_materialization_receipts: list[AutonomyArtifact] = Field(default_factory=list)
    metrics: CandidateMetricVector
    evidence_status: Literal["scored", "unscorable", "invalid"]
    minimum_meaningful_gain: float = Field(default=0.001, gt=0, le=1)
    eligible_for_promotion: bool
    ranking_reasons: list[str] = Field(min_length=1)
    regression_findings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_structural_evidence(self) -> CandidateEvaluation:
        """Preserve the exact structural evidence bundle beside candidate ranking data."""

        _validate_structural_evidence_bundle(
            self.scene_spec_v03_candidate,
            self.compiled_scene_spec_candidate,
            self.structural_recipes,
            self.structural_mesh_payloads,
            self.structural_materialization_receipts,
        )
        return self


class CandidatePromotionReceipt(AutonomyEvidenceContract):
    """Bind one best-known candidate to an atomic canonical SceneSpec promotion."""

    receipt_id: PortableId
    session_id: PortableId
    candidate_id: PortableId
    candidate_evaluation: AutonomyArtifact
    candidate_manifest: AutonomyArtifact
    candidate_modeling_plan: AutonomyArtifact
    candidate_scene_spec: AutonomyArtifact
    policy_authorization: AutonomyArtifact
    previous_modeling_plan_sha256: Sha256 | None = None
    previous_scene_spec_sha256: Sha256 | None = None
    canonical_modeling_plan: AutonomyArtifact
    canonical_scene_spec: AutonomyArtifact
    archived_modeling_plan_path: RelativePath | None = None
    archived_scene_spec_path: RelativePath | None = None
    canonical_writer: Literal["controller_only"] = "controller_only"


class StateFingerprint(AQStrictModel):
    """Bind all canonical and metric inputs used for duplicate/cycle detection."""

    modeling_plan_sha256: Sha256 | None = None
    scene_spec_sha256: Sha256
    material_plan_or_graph_sha256: Sha256 | None = None
    camera_fingerprint: Sha256
    normalized_metric_vector_sha256: Sha256
    build_fingerprint: Sha256
    canonical_source_fingerprint: Sha256
    change_direction: str | None = Field(default=None, max_length=256)


class AutonomyState(AutonomyEvidenceContract):
    """Project immutable autonomy evidence into one reconstructable current state."""

    session_id: PortableId
    root_authorization: AutonomyArtifact
    profile: AutonomyArtifact
    budget: AutonomyArtifact
    status: AutonomyStatus
    phase: AutonomyPhase
    next_action: AutonomyNextAction
    action_sequence: int = Field(ge=0)
    budget_usage: BudgetUsage
    best_known_candidate: AutonomyArtifact | None = None
    current_candidate_id: PortableId | None = None
    current_round_index: int = Field(default=0, ge=0, le=5)
    current_round_candidate_index: int = Field(default=0, ge=0, le=4)
    round_baseline_candidate: AutonomyArtifact | None = None
    last_quality_report: AutonomyArtifact | None = None
    plateau_count: int = Field(default=0, ge=0, le=2)
    state_history: list[StateFingerprint] = Field(default_factory=list)
    receipt_chain_head_before_state_sha256: Sha256 | None = None
    pending_terminal_reason: TerminalReason | None = None
    terminal_reason: TerminalReason | None = None
    warnings: list[str] = Field(default_factory=list)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_terminal_state(self) -> AutonomyState:
        """Require terminal reason and no next action only for terminal states."""

        terminal = self.status in {"completed", "blocked", "cancelled", "failed"}
        if terminal and (self.terminal_reason is None or self.next_action != "none"):
            raise ValueError("terminal autonomy state needs terminal_reason and next_action=none")
        if not terminal and self.terminal_reason is not None:
            raise ValueError("non-terminal autonomy state cannot carry terminal_reason")
        return self


class AutonomyIterationReceipt(AutonomyEvidenceContract):
    """Append one exact action transition to the immutable autonomy receipt chain."""

    receipt_id: PortableId
    session_id: PortableId
    sequence: int = Field(ge=1)
    previous_receipt_sha256: Sha256 | None = None
    action: AutonomyNextAction
    state_before: AutonomyArtifact
    state_after: AutonomyArtifact
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    candidate_evaluation: AutonomyArtifact | None = None
    policy_authorization: AutonomyArtifact | None = None
    candidate_promotion_receipt: AutonomyArtifact | None = None
    material_promotion_receipt: AutonomyArtifact | None = None
    host_attempt_evidence: list[AutonomyArtifact] = Field(default_factory=list)
    canonical_changed: bool = False
    rollback_performed: bool = False
    outcome: Literal["advanced", "rolled_back", "terminal", "failed"]
    failure_fingerprint: Sha256 | None = None


class AutonomyTerminal(AutonomyEvidenceContract):
    """Bind the exact final state to either a package or a non-production review bundle."""

    terminal_id: PortableId
    session_id: PortableId
    status: Literal["quality_passed", "review_required", "blocked", "cancelled", "failed"]
    reason: TerminalReason
    final_state: AutonomyArtifact
    best_known_candidate: AutonomyArtifact | None = None
    integrated_quality_report: AutonomyArtifact | None = None
    package_manifest: AutonomyArtifact | None = None
    roundtrip_validation: AutonomyArtifact | None = None
    review_bundle_manifest: AutonomyArtifact | None = None
    destination_handoff_envelope: AutonomyArtifact | None = None

    @model_validator(mode="after")
    def validate_terminal_outputs(self) -> AutonomyTerminal:
        """Keep production packages and review bundles mutually exclusive."""

        if self.status == "quality_passed":
            if self.package_manifest is None or self.roundtrip_validation is None:
                raise ValueError("quality_passed terminal requires package and roundtrip")
            if self.review_bundle_manifest is not None:
                raise ValueError("quality_passed terminal cannot carry review bundle")
        elif self.status == "review_required":
            if self.review_bundle_manifest is None:
                raise ValueError("review_required terminal needs review bundle")
            if self.package_manifest is not None or self.destination_handoff_envelope is not None:
                raise ValueError("review terminal cannot claim package or handoff")
        return self


class AutonomyTerminalIntent(AutonomyEvidenceContract):
    """Preserve recoverable terminal intent before the final state transition is published."""

    intent_id: PortableId
    session_id: PortableId
    status: Literal["quality_passed", "review_required", "blocked", "cancelled", "failed"]
    reason: TerminalReason
    state_before: AutonomyArtifact
    integrated_quality_report: AutonomyArtifact | None = None
    package_manifest: AutonomyArtifact | None = None
    roundtrip_validation: AutonomyArtifact | None = None
    review_bundle_manifest: AutonomyArtifact | None = None
    destination_handoff_envelope: AutonomyArtifact | None = None

    @model_validator(mode="after")
    def validate_terminal_intent_outputs(self) -> AutonomyTerminalIntent:
        """Apply the same package/review exclusivity before terminal publication."""

        if self.status == "quality_passed" and (
            self.package_manifest is None or self.roundtrip_validation is None
        ):
            raise ValueError("quality-passed intent requires package and roundtrip")
        if self.status == "review_required" and self.review_bundle_manifest is None:
            raise ValueError("review intent requires a review bundle manifest")
        if self.status != "review_required" and self.review_bundle_manifest is not None:
            raise ValueError("only review-required intent may carry a review bundle")
        if self.status != "quality_passed" and self.destination_handoff_envelope is not None:
            raise ValueError("only quality-passed intent may carry a handoff envelope")
        return self


class ReviewBundleManifest(AutonomyEvidenceContract):
    """Describe a non-production bundle containing the best reviewable candidate."""

    bundle_id: PortableId
    session_id: PortableId
    status: Literal["review_only"] = "review_only"
    production_ready: Literal[False] = False
    destination_handoff_eligible: Literal[False] = False
    best_candidate_blend: AutonomyArtifact
    preview_glb: AutonomyArtifact
    representative_renders: list[AutonomyArtifact] = Field(min_length=1)
    integrated_quality_report: AutonomyArtifact
    unresolved_findings: AutonomyArtifact
    iteration_history: AutonomyArtifact
    candidate_comparison: AutonomyArtifact
    next_manual_actions: AutonomyArtifact
    termination_reason: TerminalReason
    pdf: AutonomyArtifact
    pdf_sidecar: AutonomyArtifact


class ReviewBundleReceipt(AutonomyEvidenceContract):
    """Bind every immutable review-bundle file and its non-production semantics."""

    receipt_id: PortableId
    bundle_id: PortableId
    manifest: AutonomyArtifact
    files: list[AutonomyArtifact] = Field(min_length=1)
    production_ready: Literal[False] = False
    destination_handoff_eligible: Literal[False] = False
    canonical_unchanged: Literal[True] = True
