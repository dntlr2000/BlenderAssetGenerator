"""Explicit authority-profile 0.2 identity splits over authored registered solid-root jobs.

These contracts do not inherit or change the 0.1 absence/AQ authority domain.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256
from ..structural_geometry.attachment_companion import Artifact
from .models import AwareDateTime, MaterialIdentitySplitStrictModel

AuthoredSplitProfile = Literal[
    "authored_material_registered_solid_root_user_only",
    "authored_material_registered_solid_root_delegated_technical",
]


class AuthoredSplitBoundV02(MaterialIdentitySplitStrictModel):
    """Select one exact authored solid-root authority profile without implicit conversion."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    profile: AuthoredSplitProfile = "authored_material_registered_solid_root_user_only"
    job_id: JobId
    run_id: PortableId


class MaterialIdentityCloneRuleV02(MaterialIdentitySplitStrictModel):
    """Declare one exclusive host and every existing detail row for its new identity."""

    source_material_id: PortableId
    new_material_id: PortableId
    target_object_id: PortableId
    surface_detail_ids: list[PortableId] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_identity(self) -> MaterialIdentityCloneRuleV02:
        """Reject a no-op identity or duplicate detail coverage."""
        if self.source_material_id == self.new_material_id:
            raise ValueError("authored split requires a genuinely new material identity")
        if len(set(self.surface_detail_ids)) != len(self.surface_detail_ids):
            raise ValueError("authored split detail IDs must be unique")
        return self


class AuthoredSplitDerivativeV02(MaterialIdentitySplitStrictModel):
    """Bind a strict payload predecessor and its exact material-only derivative."""

    object_id: PortableId
    source: Artifact
    candidate: Artifact


class AuthoredSplitMaterialDerivativeV02(MaterialIdentitySplitStrictModel):
    """Bind metadata-only recipe/manifest clones and exact copied media bytes."""

    object_id: PortableId
    source_manifest: Artifact | None
    candidate_manifest: Artifact | None
    source_recipe: Artifact | None
    candidate_recipe: Artifact | None
    media_copies: dict[RelativePath, Artifact] = Field(max_length=256)


class AuthoredSplitAttachmentRecordV02(MaterialIdentitySplitStrictModel):
    """Select one specialized run in an acyclic mixed attachment revision chain."""

    profile: AuthoredSplitProfile = "authored_material_registered_solid_root_user_only"

    schema_version: Literal["0.2.0"] = "0.2.0"
    kind: Literal["solid_root_attachment_material_identity_split_revision"] = (
        "solid_root_attachment_material_identity_split_revision"
    )
    job_id: JobId
    run_id: PortableId
    workflow_id: PortableId
    initial_registration: Artifact
    previous_revision: Artifact | None
    previous_intent: Artifact
    candidate_intent: Artifact
    metadata_before_sha256: Sha256


class AuthoredMaterialIdentitySplitPlanV02(AuthoredSplitBoundV02):
    """Bind immutable sources, strict candidates, complete proofs, and prospective provenance."""

    created_at: AwareDateTime
    delegation: Artifact | None = None
    clone_rules: list[MaterialIdentityCloneRuleV02] = Field(min_length=1, max_length=128)
    source_files: dict[RelativePath, Artifact] = Field(min_length=5, max_length=512)
    immutable_dependencies: dict[RelativePath, Sha256] = Field(max_length=512)
    candidate_scene_spec: Artifact
    candidate_modeling_plan: Artifact
    candidate_job_metadata: Artifact
    candidate_attachment_intent: Artifact
    attachment_revision: Artifact
    derivatives: list[AuthoredSplitDerivativeV02] = Field(min_length=1, max_length=128)
    material_derivatives: list[AuthoredSplitMaterialDerivativeV02] = Field(
        min_length=1, max_length=128
    )
    material_dependencies: dict[RelativePath, Sha256] = Field(max_length=512)
    root_proofs: Artifact
    prospective_build_provenance: Artifact
    source_build_provenance: Artifact
    source_material_plan_mode: Literal["current", "scene_spec_only"] = "current"
    material_plan_mode: Literal["authored_identity_preserved"] = "authored_identity_preserved"
    material_closure_status: Literal["pending_native_material_workflow"] = (
        "pending_native_material_workflow"
    )
    execution_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_coverage(self) -> AuthoredMaterialIdentitySplitPlanV02:
        """Keep exclusive new IDs, objects, details, and derivatives one-to-one."""
        if (self.profile == "authored_material_registered_solid_root_delegated_technical") != (
            self.delegation is not None
        ):
            raise ValueError("authored split authority profile/delegation selection differs")
        for values in (
            [rule.new_material_id for rule in self.clone_rules],
            [rule.target_object_id for rule in self.clone_rules],
            [detail for rule in self.clone_rules for detail in rule.surface_detail_ids],
            [item.object_id for item in self.derivatives],
        ):
            if len(values) != len(set(values)):
                raise ValueError("authored split clone/detail/derivative coverage is duplicated")
        if {item.object_id for item in self.derivatives} != {
            rule.target_object_id for rule in self.clone_rules
        }:
            raise ValueError("authored split derivative coverage differs from clone rules")
        required = {
            "analysis/scene_spec.json",
            "analysis/modeling_plan.json",
            "analysis/material_plan.json",
            "job.json",
            "blender/scene.blend",
        }
        if not required <= set(self.source_files):
            raise ValueError("authored split must observe all five current canonical sources")
        return self


class AuthoredMaterialIdentitySplitPreapprovalV02(AuthoredSplitBoundV02):
    """Record exact native preparation without creating approval or canonical authority."""

    plan: Artifact
    status: Literal["passed"] = "passed"
    blender_version: Literal["5.0.1"] = "5.0.1"
    blender_executable_sha256: Sha256
    native_script_sha256: dict[RelativePath, Sha256] = Field(min_length=3, max_length=3)
    source_native_inventory: Artifact
    candidate_native_inventory: Artifact
    shadow_validation: Artifact
    shadow_scene_inventory: Artifact
    shadow_blend: Artifact
    invariant_report: Artifact
    canonical_unchanged: Literal[True] = True
    actual_user_approval_created: Literal[False] = False
    canonical_write_count: Literal[0] = 0


class AuthoredMaterialIdentitySplitInvariantsV02(AuthoredSplitBoundV02):
    """Bind complete native/source equality and exact planned assignment changes."""

    plan: Artifact
    source_native_inventory: Artifact
    candidate_native_inventory: Artifact
    root_proofs: Artifact
    status: Literal["passed"] = "passed"
    geometry_topology_transform_uv_smoothing_unchanged: Literal[True] = True
    root_domain_reference_camera_unchanged: Literal[True] = True
    material_assignments_exact: Literal[True] = True
    full_native_shader_and_render_state_preserved: Literal[True] = True
    authored_material_plan_preserved: Literal[True] = True
    final_human_acceptance: Literal[False] = False


class AuthoredMaterialIdentitySplitApprovalRequestV02(AuthoredSplitBoundV02):
    """Request one specialized root-scope decision over the exact native candidate closure."""

    profile: Literal["authored_material_registered_solid_root_user_only"] = (
        "authored_material_registered_solid_root_user_only"
    )

    plan: Artifact
    preapproval: Artifact
    invariant_report: Artifact
    shadow_blend: Artifact
    approval_scope: Literal["material_identity_split"] = "material_identity_split"
    satisfies_required_approval: Literal["root_scope"] = "root_scope"
    status: Literal["eligible_for_explicit_user_scope_approval"] = (
        "eligible_for_explicit_user_scope_approval"
    )
    is_user_approval: Literal[False] = False


class AuthoredMaterialIdentitySplitApprovalV02(AuthoredSplitBoundV02):
    """Preserve caller-authored specialized user authority and exact decision byte hash."""

    profile: Literal["authored_material_registered_solid_root_user_only"] = (
        "authored_material_registered_solid_root_user_only"
    )

    approval_id: PortableId
    decision: Literal["approved", "rejected"]
    approved_by: Literal["user"] = "user"
    explicit_user_decision_observed: Literal[True] = True
    user_decision_text_sha256: Sha256
    decision_observed_at: AwareDateTime
    approval_request: Artifact
    plan: Artifact
    preapproval: Artifact
    invariant_report: Artifact
    shadow_blend: Artifact
    approval_scope: Literal["material_identity_split"] = "material_identity_split"
    satisfies_required_approval: Literal["root_scope"] = "root_scope"
    single_use: Literal[True] = True
    exact_candidate_only: Literal[True] = True
    geometry_change_allowed: Literal[False] = False
    uv_change_allowed: Literal[False] = False
    reference_or_content_scope_change_allowed: Literal[False] = False
    material_plan_promotion_allowed: Literal[False] = False
    appearance_or_package_acceptance: Literal[False] = False
    delegated_authority_allowed: Literal[False] = False


class AuthoredMaterialIdentitySplitApplyIntentV02(AuthoredSplitBoundV02):
    """Select one exact user approval and request for a single four-file transaction."""

    profile: Literal["authored_material_registered_solid_root_user_only"] = (
        "authored_material_registered_solid_root_user_only"
    )

    intent_id: PortableId
    approval: Artifact
    approval_request: Artifact
    plan: Artifact
    user_decision: Artifact


class AuthoredMaterialIdentitySplitJournalV02(AuthoredSplitBoundV02):
    """Bind four exact archives and specialized one-use authority before the first write."""

    apply_intent: Artifact
    approval_consumption: Artifact
    before: dict[RelativePath, Sha256] = Field(min_length=4, max_length=4)
    after: dict[RelativePath, Sha256] = Field(min_length=4, max_length=4)


class AuthoredMaterialIdentitySplitConsumptionV02(AuthoredSplitBoundV02):
    """Consume the original specialized approval once, preserving decision bytes."""

    profile: Literal["authored_material_registered_solid_root_user_only"] = (
        "authored_material_registered_solid_root_user_only"
    )

    apply_intent: Artifact
    approval: Artifact
    approval_request: Artifact
    user_decision: Artifact
    consumption_ordinal: Literal[1] = 1
    consumed_once: Literal[True] = True


class AuthoredMaterialIdentitySplitTerminalV02(AuthoredSplitBoundV02):
    """Record one immutable commit or exact rollback without granting future authority."""

    status: Literal["committed", "rolled_back"]
    journal: Artifact
    canonical: dict[RelativePath, Sha256] = Field(min_length=4, max_length=4)
    material_closure_status: Literal["pending_native_material_workflow"] = (
        "pending_native_material_workflow"
    )
    authored_material_plan_preserved: Literal[True] = True
    final_human_acceptance: Literal[False] = False


class AuthoredMaterialIdentitySplitRootProofsV02(AuthoredSplitBoundV02):
    """Retain complete existing binary64 and binary32 proof payloads for source and candidate."""

    source_binary64: dict[str, Any]
    source_float32: dict[str, Any]
    candidate_binary64: dict[str, Any]
    candidate_float32: dict[str, Any]


class AuthoredMaterialIdentitySplitDelegationV02(AuthoredSplitBoundV02):
    """Bind the actual user question/reply to one narrow current-source split, not future hashes."""

    profile: Literal["authored_material_registered_solid_root_delegated_technical"] = (
        "authored_material_registered_solid_root_delegated_technical"
    )
    delegation_id: PortableId
    original_delegation_id: Sha256
    question: Artifact
    reply: Artifact
    question_message_id: str = Field(min_length=1, max_length=512)
    reply_message_id: str = Field(min_length=1, max_length=512)
    delegation_observed_at: AwareDateTime
    source_sha256: dict[RelativePath, Sha256] = Field(min_length=5, max_length=5)
    source_dependency_sha256: dict[RelativePath, Sha256] = Field(min_length=1, max_length=512)
    clone_rules: list[MaterialIdentityCloneRuleV02] = Field(min_length=1, max_length=128)
    delegated_by: Literal["user"] = "user"
    decision_actor: Literal["delegated_assistant"] = "delegated_assistant"
    approval_scope: Literal["material_identity_split"] = "material_identity_split"
    allowed_action: Literal["select_and_approve_exact_specialized_technical_candidate"] = (
        "select_and_approve_exact_specialized_technical_candidate"
    )
    explicit_delegation_observed: Literal[True] = True
    user_approved_future_candidate_hashes: Literal[False] = False
    geometry_or_uv_change_allowed: Literal[False] = False
    reference_or_content_scope_change_allowed: Literal[False] = False
    material_appearance_change_allowed: Literal[False] = False
    final_human_acceptance: Literal[False] = False
    aq_authority_created: Literal[False] = False


class AuthoredMaterialIdentitySplitTechnicalApprovalV02(AuthoredSplitBoundV02):
    """Record a delegated assistant's exact specialized technical decision, never user approval."""

    profile: Literal["authored_material_registered_solid_root_delegated_technical"] = (
        "authored_material_registered_solid_root_delegated_technical"
    )
    approval_id: PortableId
    decision: Literal["approved", "rejected"]
    approved_by: Literal["delegated_assistant"] = "delegated_assistant"
    authority_kind: Literal["bounded_specialized_technical_delegation"] = (
        "bounded_specialized_technical_delegation"
    )
    decision_observed_at: AwareDateTime
    delegation: Artifact
    technical_decision_text_sha256: Sha256
    approval_request: Artifact
    plan: Artifact
    preapproval: Artifact
    invariant_report: Artifact
    shadow_blend: Artifact
    approval_scope: Literal["material_identity_split"] = "material_identity_split"
    satisfies_required_approval: Literal["root_scope"] = "root_scope"
    single_use: Literal[True] = True
    exact_candidate_only: Literal[True] = True
    geometry_or_uv_change_allowed: Literal[False] = False
    material_plan_promotion_allowed: Literal[False] = False
    appearance_or_package_acceptance: Literal[False] = False
    is_user_approval: Literal[False] = False
    user_approval_created: Literal[False] = False
    aq_authority_created: Literal[False] = False


class AuthoredMaterialIdentitySplitTechnicalApplyIntentV02(AuthoredSplitBoundV02):
    """Consume one non-user specialized technical decision under the original bounded delegation."""

    profile: Literal["authored_material_registered_solid_root_delegated_technical"] = (
        "authored_material_registered_solid_root_delegated_technical"
    )
    intent_id: PortableId
    technical_approval: Artifact
    approval_request: Artifact
    plan: Artifact
    delegation: Artifact
    technical_decision: Artifact
    user_approval_consumed: Literal[False] = False


class AuthoredMaterialIdentitySplitTechnicalConsumptionV02(AuthoredSplitBoundV02):
    """Consume one delegated-assistant technical authority without counting a human approval."""

    profile: Literal["authored_material_registered_solid_root_delegated_technical"] = (
        "authored_material_registered_solid_root_delegated_technical"
    )
    apply_intent: Artifact
    technical_approval: Artifact
    approval_request: Artifact
    delegation: Artifact
    technical_decision: Artifact
    decision_actor: Literal["delegated_assistant"] = "delegated_assistant"
    original_delegation_id: Sha256
    delegation_origin_id: Sha256
    consumption_ordinal: Literal[1] = 1
    consumed_once: Literal[True] = True
    user_approval_consumed: Literal[False] = False
    aq_authority_consumed: Literal[False] = False


class AuthoredMaterialIdentitySplitTechnicalApprovalRequestV02(
    AuthoredMaterialIdentitySplitApprovalRequestV02
):
    """Request an exact assistant technical decision only within the explicit user delegation."""

    profile: Literal["authored_material_registered_solid_root_delegated_technical"] = (
        "authored_material_registered_solid_root_delegated_technical"
    )
    status: Literal["eligible_for_delegated_technical_scope_decision"] = (
        "eligible_for_delegated_technical_scope_decision"
    )
