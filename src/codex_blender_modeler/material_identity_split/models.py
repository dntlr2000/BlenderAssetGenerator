"""Strict additive contracts for guarded material identity split transactions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from ..material_closure.models import ExactArtifact
from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId
from ..versioning import MATERIAL_IDENTITY_SPLIT_SCHEMA_VERSION

SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"

MaterialIdentitySplitTransactionStatus = Literal[
    "planned",
    "preapproval_running",
    "preapproval_failed",
    "eligible_for_explicit_user_scope_approval",
    "approval_consumed",
    "archives_written",
    "scene_spec_replaced",
    "modeling_plan_replaced",
    "blender_rebuilt",
    "invariants_verified",
    "committed",
    "rollback_started",
    "rolled_back",
    "recovery_required",
]


def _validate_aware_datetime(value: datetime) -> datetime:
    """Require every persisted timestamp to identify an unambiguous instant."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return value


AwareDateTime = Annotated[datetime, AfterValidator(_validate_aware_datetime)]


class MaterialIdentitySplitStrictModel(BaseModel):
    """Reject coercion, non-finite numbers, mutation, and undeclared contract fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True, frozen=True)


class MaterialIdentitySplitBoundContract(MaterialIdentitySplitStrictModel):
    """Bind one identity-split contract to its exact workflow and run identity."""

    schema_version: Literal["0.1.0"] = MATERIAL_IDENTITY_SPLIT_SCHEMA_VERSION
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    run_id: PortableId
    producer: PortableId
    producer_version: str = Field(pattern=SEMVER_PATTERN)
    created_at: AwareDateTime


class MaterialIdentityCloneRule(MaterialIdentitySplitStrictModel):
    """Declare one exact semantic material clone and its exclusive target object."""

    source_material_id: PortableId
    new_material_id: PortableId
    target_object_id: PortableId
    surface_detail_id: PortableId
    retained_source_object_ids: list[PortableId] = Field(default_factory=list)
    allow_display_name_change: Literal[False] = False

    @model_validator(mode="after")
    def validate_distinct_identity(self) -> MaterialIdentityCloneRule:
        """Require a genuinely new identity and disjoint exclusive/retained objects."""

        if self.source_material_id == self.new_material_id:
            raise ValueError("identity split source and new material IDs must differ")
        if self.target_object_id in self.retained_source_object_ids:
            raise ValueError("exclusive target cannot also retain the source material")
        if len(self.retained_source_object_ids) != len(set(self.retained_source_object_ids)):
            raise ValueError("retained source object IDs must be unique")
        return self


class MaterialIdentitySplitModelingPlanChange(MaterialIdentitySplitStrictModel):
    """Declare one allowed ModelingPlan surface-detail target material replacement."""

    detail_id: PortableId
    parent_object_id: PortableId
    source_material_id: PortableId
    new_material_id: PortableId
    required_channels: list[PortableId] = Field(min_length=1)


class MaterialIdentitySplitAssignment(MaterialIdentitySplitStrictModel):
    """Bind one object to one material before or after the guarded split."""

    object_id: PortableId
    material_id: PortableId


class MaterialIdentitySplitCanonicalPreconditions(MaterialIdentitySplitStrictModel):
    """Bind exact canonical bytes, absence, reference, scope, and UV preconditions."""

    scene_spec: ExactArtifact
    modeling_plan: ExactArtifact
    blend: ExactArtifact
    material_plan_absence: ExactArtifact
    root_authorization: ExactArtifact
    primary_reference: ExactArtifact
    content_scope_sha256: Sha256
    target_subject: str = Field(min_length=1, max_length=500)
    uv_layout_fingerprint: Sha256

    @model_validator(mode="after")
    def validate_canonical_paths(self) -> MaterialIdentitySplitCanonicalPreconditions:
        """Require the canonical path/kind vocabulary and strict MaterialPlan absence."""

        expected = (
            (self.scene_spec, "analysis/scene_spec.json", "scene_spec"),
            (self.modeling_plan, "analysis/modeling_plan.json", "modeling_plan"),
            (self.blend, "blender/scene.blend", "canonical_blend"),
        )
        for artifact, path, kind in expected:
            if artifact.path != path or artifact.kind != kind:
                raise ValueError("identity split canonical precondition path or kind is invalid")
        if self.material_plan_absence.kind != "material_plan_absence":
            raise ValueError("identity split requires strict MaterialPlan absence evidence")
        if self.primary_reference.kind != "primary_reference":
            raise ValueError("identity split requires an exact primary reference")
        return self


class MaterialIdentitySplitPlan(MaterialIdentitySplitBoundContract):
    """Bind one exact paired identity-split plan without granting execution authority."""

    plan_id: PortableId
    planning_root: RelativePath
    plan_manifest: ExactArtifact
    revision_plan: ExactArtifact
    candidate_scene_spec: ExactArtifact
    candidate_modeling_plan: ExactArtifact
    scene_diff_allowlist: ExactArtifact
    approval_impact_report: ExactArtifact
    geometry_uv_unchanged_report: ExactArtifact
    surface_detail_material_mapping: ExactArtifact
    specialized_approval_requirement: ExactArtifact
    session_supersession_plan: ExactArtifact
    current_material_closure: ExactArtifact
    latest_framework_failure: ExactArtifact
    channel_reconciliation: ExactArtifact
    preconditions: MaterialIdentitySplitCanonicalPreconditions
    clone_rules: list[MaterialIdentityCloneRule] = Field(min_length=1)
    modeling_plan_changes: list[MaterialIdentitySplitModelingPlanChange] = Field(min_length=1)
    changed_assignments: list[MaterialIdentitySplitAssignment] = Field(min_length=1)
    retained_assignments: list[MaterialIdentitySplitAssignment] = Field(min_length=1)
    impact: Literal["scope_change"] = "scope_change"
    required_approval: Literal["root_scope"] = "root_scope"
    approval_scope: Literal["material_identity_split"] = "material_identity_split"
    no_visual_change_allowed: Literal[False] = False
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_split_plan(self) -> MaterialIdentitySplitPlan:
        """Require one-to-one clone, assignment, and ModelingPlan change coverage."""

        new_ids = [rule.new_material_id for rule in self.clone_rules]
        target_ids = [rule.target_object_id for rule in self.clone_rules]
        detail_ids = [rule.surface_detail_id for rule in self.clone_rules]
        if len(new_ids) != len(set(new_ids)) or len(target_ids) != len(set(target_ids)):
            raise ValueError("identity split clone identities and targets must be unique")
        if set(detail_ids) != {item.detail_id for item in self.modeling_plan_changes}:
            raise ValueError("paired ModelingPlan changes must cover every identity clone")
        expected_changed = {
            (rule.target_object_id, rule.new_material_id) for rule in self.clone_rules
        }
        actual_changed = {(item.object_id, item.material_id) for item in self.changed_assignments}
        if actual_changed != expected_changed:
            raise ValueError("changed assignments differ from the exact clone plan")
        if expected_changed & {
            (item.object_id, item.material_id) for item in self.retained_assignments
        }:
            raise ValueError("changed and retained assignments must be disjoint")
        return self


class MaterialIdentitySplitModelingPlanDiffReport(MaterialIdentitySplitBoundContract):
    """Prove that a candidate ModelingPlan contains only declared paired replacements."""

    report_id: PortableId
    plan: ExactArtifact
    canonical_modeling_plan: ExactArtifact
    candidate_modeling_plan: ExactArtifact
    allowed_changes: list[MaterialIdentitySplitModelingPlanChange] = Field(min_length=1)
    actual_change_count: int = Field(ge=1)
    forbidden_change_count: Literal[0] = 0
    preserved_detail_channels: dict[PortableId, list[PortableId]] = Field(default_factory=dict)
    exact_match: Literal[True] = True


class MaterialIdentitySplitPreapprovalRequest(MaterialIdentitySplitBoundContract):
    """Request isolated paired validation while explicitly withholding approval authority."""

    request_id: PortableId
    plan: ExactArtifact
    candidate_scene_spec: ExactArtifact
    candidate_modeling_plan: ExactArtifact
    scene_diff_allowlist: ExactArtifact
    modeling_plan_diff_report: ExactArtifact
    canonical_scene_inventory: ExactArtifact
    shadow_root: RelativePath
    expected_blender_version: Literal["5.0.1"] = "5.0.1"
    approval_publication_allowed: Literal[False] = False
    canonical_write_allowed: Literal[False] = False


class MaterialIdentitySplitCheck(MaterialIdentitySplitStrictModel):
    """Record one deterministic preapproval or invariant check result."""

    check_id: PortableId
    category: Literal[
        "canonical",
        "candidate",
        "diff",
        "clone",
        "assignment",
        "blender",
        "geometry",
        "topology",
        "transform",
        "uv",
        "reference",
    ]
    status: Literal["passed", "failed"]
    message: str = Field(min_length=1, max_length=1200)


class MaterialIdentitySplitBindingDerivativeEntry(MaterialIdentitySplitStrictModel):
    """Bind one geometry-identical mesh payload whose material slot alone changed."""

    object_id: PortableId
    source_material_id: PortableId
    new_material_id: PortableId
    source_payload: ExactArtifact
    derivative_payload: ExactArtifact
    vertices_unchanged: Literal[True] = True
    faces_unchanged: Literal[True] = True
    topology_unchanged: Literal[True] = True
    uv_unchanged: Literal[True] = True
    material_slots_only: Literal[True] = True


class MaterialIdentitySplitMaterialBindingDerivativeReceipt(MaterialIdentitySplitBoundContract):
    """Prove isolated mesh derivatives alter only exact material-slot identities."""

    receipt_id: PortableId
    entries: list[MaterialIdentitySplitBindingDerivativeEntry] = Field(min_length=1)
    canonical_geometry_payload_overwrite: Literal[False] = False
    status: Literal["passed"] = "passed"


class MaterialIdentitySplitShadowBuildReceipt(MaterialIdentitySplitBoundContract):
    """Record one isolated Blender rebuild, inspect, and validate execution."""

    receipt_id: PortableId
    request: ExactArtifact
    status: Literal["passed", "failed"]
    blender_version: Literal["5.0.1"] | None = None
    blender_executable_name: str = Field(min_length=1, max_length=260)
    blender_executable_sha256: Sha256
    blender_process_count: int = Field(ge=0, le=3)
    commands: list[str] = Field(max_length=3)
    shadow_root: RelativePath
    shadow_blend: ExactArtifact | None = None
    shadow_scene_inventory: ExactArtifact | None = None
    shadow_validation: ExactArtifact | None = None
    material_binding_derivative: ExactArtifact | None = None
    canonical_scene_spec_before: ExactArtifact
    canonical_scene_spec_after: ExactArtifact
    canonical_modeling_plan_before: ExactArtifact
    canonical_modeling_plan_after: ExactArtifact
    canonical_blend_before: ExactArtifact
    canonical_blend_after: ExactArtifact
    material_plan_absent_before: bool
    material_plan_absent_after: bool
    canonical_unchanged: bool

    @model_validator(mode="after")
    def validate_shadow_status(self) -> MaterialIdentitySplitShadowBuildReceipt:
        """Require complete outputs and unchanged canonical bytes for a passed shadow run."""

        if self.status == "passed":
            if self.blender_process_count != 3 or self.blender_version != "5.0.1":
                raise ValueError("passed identity split shadow requires three Blender 5.0.1 runs")
            if any(
                item is None
                for item in (
                    self.shadow_blend,
                    self.shadow_scene_inventory,
                    self.shadow_validation,
                    self.material_binding_derivative,
                )
            ):
                raise ValueError("passed identity split shadow requires every output artifact")
            if not self.canonical_unchanged:
                raise ValueError("passed identity split shadow must preserve canonical bytes")
        return self


class MaterialIdentitySplitInvariantReport(MaterialIdentitySplitBoundContract):
    """Prove exact clone, assignment, geometry, topology, transform, UV, and scope invariants."""

    report_id: PortableId
    request: ExactArtifact
    shadow_receipt: ExactArtifact
    status: Literal["passed", "failed"]
    checks: list[MaterialIdentitySplitCheck] = Field(min_length=1)
    scene_change_count: int = Field(ge=0)
    modeling_plan_change_count: int = Field(ge=0)
    forbidden_change_count: int = Field(ge=0)
    clone_equivalence_passed: bool
    assignment_exclusivity_passed: bool
    object_ids_unchanged: bool
    geometry_unchanged: bool
    topology_unchanged: bool
    transforms_unchanged: bool
    dimensions_unchanged: bool
    uv_unchanged: bool
    reference_scope_unchanged: bool
    target_subject_unchanged: bool
    content_scope_unchanged: bool
    material_assignments_match_plan: bool

    @model_validator(mode="after")
    def validate_passed_invariants(self) -> MaterialIdentitySplitInvariantReport:
        """Require every invariant and zero forbidden changes when status is passed."""

        flags = (
            self.clone_equivalence_passed,
            self.assignment_exclusivity_passed,
            self.object_ids_unchanged,
            self.geometry_unchanged,
            self.topology_unchanged,
            self.transforms_unchanged,
            self.dimensions_unchanged,
            self.uv_unchanged,
            self.reference_scope_unchanged,
            self.target_subject_unchanged,
            self.content_scope_unchanged,
            self.material_assignments_match_plan,
        )
        if self.status == "passed" and (
            not all(flags)
            or self.forbidden_change_count != 0
            or any(check.status != "passed" for check in self.checks)
        ):
            raise ValueError("passed identity split invariant report contains a failed fact")
        return self


class MaterialIdentitySplitPreapprovalReport(MaterialIdentitySplitBoundContract):
    """Aggregate strict paired validation without representing user approval."""

    report_id: PortableId
    request: ExactArtifact
    status: Literal["passed", "failed"]
    checks: list[MaterialIdentitySplitCheck] = Field(min_length=1)
    shadow_build_receipt: ExactArtifact | None = None
    invariant_report: ExactArtifact | None = None
    approval_request_eligible: bool
    actual_user_approval_created: Literal[False] = False
    approval_consumption_count: Literal[0] = 0
    apply_intent_count: Literal[0] = 0
    canonical_write_count: Literal[0] = 0
    repair_session_count: Literal[0] = 0
    controller_count: Literal[0] = 0
    promotion_count: Literal[0] = 0
    iq_count: Literal[0] = 0
    package_count: Literal[0] = 0
    destination_write_count: Literal[0] = 0

    @model_validator(mode="after")
    def validate_preapproval_status(self) -> MaterialIdentitySplitPreapprovalReport:
        """Permit approval eligibility only after complete passed shadow and invariant evidence."""

        if self.status == "passed":
            if self.shadow_build_receipt is None or self.invariant_report is None:
                raise ValueError("passed preapproval requires shadow and invariant receipts")
            if not self.approval_request_eligible:
                raise ValueError("passed preapproval must be eligible for an approval request")
            if any(check.status != "passed" for check in self.checks):
                raise ValueError("passed preapproval contains a failed check")
        elif self.approval_request_eligible:
            raise ValueError("failed preapproval cannot request user approval")
        return self


class MaterialIdentitySplitApprovalRequest(MaterialIdentitySplitBoundContract):
    """Present one exact narrow scope change for a future explicit user decision."""

    approval_request_id: PortableId
    plan: ExactArtifact
    candidate_scene_spec: ExactArtifact
    candidate_modeling_plan: ExactArtifact
    scene_diff_allowlist: ExactArtifact
    modeling_plan_diff_report: ExactArtifact
    approval_impact_report: ExactArtifact
    preapproval_report: ExactArtifact
    shadow_build_receipt: ExactArtifact
    invariant_report: ExactArtifact
    geometry_uv_unchanged_report: ExactArtifact
    surface_detail_material_mapping: ExactArtifact
    changed_assignments: list[MaterialIdentitySplitAssignment] = Field(min_length=1)
    retained_assignments: list[MaterialIdentitySplitAssignment] = Field(min_length=1)
    preconditions: MaterialIdentitySplitCanonicalPreconditions
    channel_reconciliation: ExactArtifact
    current_material_closure: ExactArtifact
    latest_framework_failure: ExactArtifact
    approval_scope: Literal["material_identity_split"] = "material_identity_split"
    satisfies_required_approval: Literal["root_scope"] = "root_scope"
    status: Literal["eligible_for_explicit_user_scope_approval"] = (
        "eligible_for_explicit_user_scope_approval"
    )
    is_user_approval: Literal[False] = False


class MaterialIdentitySplitRootScopeApproval(MaterialIdentitySplitBoundContract):
    """Record one exact user decision over one narrow identity split and nothing broader."""

    approval_id: PortableId
    approval_scope: Literal["material_identity_split"] = "material_identity_split"
    satisfies_required_approval: Literal["root_scope"] = "root_scope"
    decision: Literal["approved", "rejected"]
    approved_by: Literal["user"] = "user"
    explicit_user_decision_observed: Literal[True] = True
    user_decision_text_sha256: Sha256
    decision_observed_at: AwareDateTime
    approval_request: ExactArtifact
    candidate_scene_spec: ExactArtifact
    candidate_modeling_plan: ExactArtifact
    scene_diff_allowlist: ExactArtifact
    modeling_plan_diff_report: ExactArtifact
    preapproval_report: ExactArtifact
    shadow_build_receipt: ExactArtifact
    invariant_report: ExactArtifact
    preconditions: MaterialIdentitySplitCanonicalPreconditions
    single_use: Literal[True] = True
    exact_candidate_only: Literal[True] = True
    reference_replacement_allowed: Literal[False] = False
    target_subject_change_allowed: Literal[False] = False
    content_scope_change_allowed: Literal[False] = False
    imagegen_scope_expansion_allowed: Literal[False] = False
    object_set_change_allowed: Literal[False] = False
    geometry_change_allowed: Literal[False] = False
    uv_change_allowed: Literal[False] = False
    material_plan_promotion_allowed: Literal[False] = False
    package_or_destination_write_allowed: Literal[False] = False


class MaterialIdentitySplitApplyIntent(MaterialIdentitySplitBoundContract):
    """Bind one approved paired candidate to one logical canonical transaction."""

    intent_id: PortableId
    transaction_id: PortableId
    approval: ExactArtifact
    approval_request: ExactArtifact
    plan: ExactArtifact
    candidate_scene_spec: ExactArtifact
    candidate_modeling_plan: ExactArtifact
    scene_diff_allowlist: ExactArtifact
    modeling_plan_diff_report: ExactArtifact
    preapproval_report: ExactArtifact
    shadow_build_receipt: ExactArtifact
    invariant_report: ExactArtifact
    preconditions: MaterialIdentitySplitCanonicalPreconditions
    expected_scene_spec_sha256: Sha256
    expected_modeling_plan_sha256: Sha256
    expected_material_assignment_sha256: Sha256
    retry_allowance: Literal[1] = 1
    rollback_policy: Literal["exact_archives_required"] = "exact_archives_required"

    @model_validator(mode="after")
    def validate_expected_outputs(self) -> MaterialIdentitySplitApplyIntent:
        """Require expected paired JSON outputs to equal the bound candidate bytes."""

        if self.expected_scene_spec_sha256 != self.candidate_scene_spec.sha256:
            raise ValueError("ApplyIntent SceneSpec output differs from its exact candidate")
        if self.expected_modeling_plan_sha256 != self.candidate_modeling_plan.sha256:
            raise ValueError("ApplyIntent ModelingPlan output differs from its exact candidate")
        return self


class MaterialIdentitySplitApprovalConsumptionReceipt(MaterialIdentitySplitBoundContract):
    """Consume one approved identity-split decision for exactly one ApplyIntent."""

    receipt_id: PortableId
    approval: ExactArtifact
    approval_request: ExactArtifact
    apply_intent: ExactArtifact
    approval_decision: Literal["approved"] = "approved"
    consumption_ordinal: Literal[1] = 1
    consumed_once: Literal[True] = True
    approval_unchanged: Literal[True] = True


class MaterialIdentitySplitApplyReceipt(MaterialIdentitySplitBoundContract):
    """Record one committed guarded transaction and exact canonical before/after artifacts."""

    receipt_id: PortableId
    transaction_id: PortableId
    apply_intent: ExactArtifact
    approval_consumption: ExactArtifact
    pre_scene_spec: ExactArtifact
    pre_modeling_plan: ExactArtifact
    pre_blend: ExactArtifact
    post_scene_spec: ExactArtifact
    post_modeling_plan: ExactArtifact
    post_blend: ExactArtifact
    invariant_report: ExactArtifact
    transaction_states: list[ExactArtifact] = Field(min_length=1)
    material_plan_remained_absent: Literal[True] = True
    committed: Literal[True] = True


class MaterialIdentitySplitRollbackReceipt(MaterialIdentitySplitBoundContract):
    """Record exact restoration from immutable archives after a partial split transaction."""

    receipt_id: PortableId
    transaction_id: PortableId
    apply_intent: ExactArtifact
    approval_consumption: ExactArtifact
    archived_scene_spec: ExactArtifact
    archived_modeling_plan: ExactArtifact
    archived_blend: ExactArtifact
    restored_scene_spec: ExactArtifact
    restored_modeling_plan: ExactArtifact
    restored_blend: ExactArtifact
    failure_state: ExactArtifact
    rollback_state: ExactArtifact
    canonical_restored: Literal[True] = True


class MaterialIdentitySplitRecoveryReceipt(MaterialIdentitySplitBoundContract):
    """Record deterministic recovery without consuming approval or creating a new intent."""

    receipt_id: PortableId
    transaction_id: PortableId
    apply_intent: ExactArtifact
    approval_consumption: ExactArtifact
    starting_state: ExactArtifact
    terminal_state: ExactArtifact
    outcome: Literal["committed", "rolled_back", "recovery_required"]
    technical_retry_count: int = Field(ge=0, le=1)
    approval_reconsumed: Literal[False] = False
    new_apply_intent_created: Literal[False] = False


class MaterialIdentitySplitGeometryContinuationReceipt(MaterialIdentitySplitBoundContract):
    """Prove prior approved geometry survives a committed material-only identity split."""

    receipt_id: PortableId
    previous_geometry_approval: ExactArtifact
    previous_geometry_validation: ExactArtifact
    apply_intent: ExactArtifact
    apply_receipt: ExactArtifact
    post_scene_spec: ExactArtifact
    post_modeling_plan: ExactArtifact
    post_blend: ExactArtifact
    invariant_report: ExactArtifact
    canonical_scene_inventory: ExactArtifact
    canonical_build_provenance: ExactArtifact
    material_plan_absence: ExactArtifact
    canonical_snapshot: ExactArtifact
    reference_authorization: ExactArtifact
    content_scope_sha256: Sha256
    identity_split_diff: ExactArtifact
    geometry_approval_reclassified: Literal[False] = False
    geometry_continuity_passed: Literal[True] = True


class MaterialIdentitySplitTransactionState(MaterialIdentitySplitBoundContract):
    """Journal one append-only state in a guarded identity-split transaction."""

    transaction_id: PortableId
    sequence: int = Field(ge=0)
    previous_state: ExactArtifact | None = None
    state: MaterialIdentitySplitTransactionStatus
    plan: ExactArtifact
    preapproval_request: ExactArtifact | None = None
    approval_request: ExactArtifact | None = None
    apply_intent: ExactArtifact | None = None
    approval_consumption: ExactArtifact | None = None
    canonical_observation: MaterialIdentitySplitCanonicalPreconditions
    archives: list[ExactArtifact] = Field(default_factory=list)
    performed_actions: list[PortableId] = Field(default_factory=list)
    allowed_next_actions: list[PortableId] = Field(default_factory=list)
    technical_retry_count: int = Field(default=0, ge=0, le=1)
    blocked_reason: str | None = Field(default=None, max_length=1200)

    @model_validator(mode="after")
    def validate_state_chain(self) -> MaterialIdentitySplitTransactionState:
        """Require predecessor continuity and exact authority at guarded transaction states."""

        if (self.sequence == 0) != (self.previous_state is None):
            raise ValueError("only sequence zero may omit the previous transaction state")
        if self.state in {
            "approval_consumed",
            "archives_written",
            "scene_spec_replaced",
            "modeling_plan_replaced",
            "blender_rebuilt",
            "invariants_verified",
            "committed",
            "rollback_started",
            "rolled_back",
            "recovery_required",
        } and (self.apply_intent is None or self.approval_consumption is None):
            raise ValueError("guarded transaction state requires intent and approval consumption")
        if self.state == "eligible_for_explicit_user_scope_approval":
            if self.approval_request is None or self.apply_intent is not None:
                raise ValueError("preapproval terminal requires request and no ApplyIntent")
        if self.state in {"committed", "rolled_back"} and self.allowed_next_actions:
            raise ValueError("terminal transaction state cannot allow another action")
        return self


class MaterialIdentitySplitStatusProjection(MaterialIdentitySplitBoundContract):
    """Project append-only states without creating a mutable authoritative latest file."""

    projection_id: PortableId
    transaction_id: PortableId
    state_artifacts: list[ExactArtifact] = Field(min_length=1)
    latest_state: ExactArtifact
    latest_sequence: int = Field(ge=0)
    status: MaterialIdentitySplitTransactionStatus
    framework_ready_for_explicit_scope_approval: bool
    approval_request: ExactArtifact | None = None
    actual_user_approval_count: int = Field(ge=0)
    approval_consumption_count: int = Field(ge=0)
    apply_intent_count: int = Field(ge=0)
    canonical_write_count: int = Field(ge=0)
    repair_session_count: int = Field(ge=0)
    controller_count: int = Field(ge=0)
    promotion_count: int = Field(ge=0)
    material_phase_receipt_count: int = Field(ge=0)
    iq_count: int = Field(ge=0)
    package_count: int = Field(ge=0)
    destination_write_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ready_projection(self) -> MaterialIdentitySplitStatusProjection:
        """Keep the ready flag aligned with the exact approval-request boundary only."""

        ready = self.status == "eligible_for_explicit_user_scope_approval"
        if self.framework_ready_for_explicit_scope_approval != ready:
            raise ValueError("identity split ready projection is inconsistent")
        if ready and self.approval_request is None:
            raise ValueError("ready identity split projection requires its approval request")
        return self


class MaterialIdentitySplitPreapprovalFailure(MaterialIdentitySplitBoundContract):
    """Record one structured fail-closed stop before approval and canonical writes."""

    failure_id: PortableId
    plan: ExactArtifact | None = None
    request: ExactArtifact | None = None
    stage: Literal[
        "canonical_rehash",
        "candidate_validation",
        "paired_diff",
        "clone_invariant",
        "shadow_build",
        "invariant_validation",
        "approval_request",
    ]
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")
    message: str = Field(min_length=1, max_length=1600)
    status: Literal["preapproval_failed"] = "preapproval_failed"
    approval_request_created: Literal[False] = False
    actual_user_approval_created: Literal[False] = False
    approval_consumption_count: Literal[0] = 0
    apply_intent_count: Literal[0] = 0
    canonical_write_count: Literal[0] = 0
