"""Strict AQ v2 material-controller validation and host-promotion evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId
from .approval_models import ApprovalArtifact, ApprovalV03Evidence
from .models import AQV2Artifact, AQV2Evidence, AQV2StrictModel, BudgetUsageV2


class MaterialControllerCompletionV2(AQV2StrictModel):
    """Bind the three controller outputs to the exact immutable authoring request."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    completion_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    execution_id: PortableId
    assignment_sha256: Sha256
    tool_profile_sha256: Sha256
    immutable_input_sha256: dict[RelativePath, Sha256] = Field(min_length=1)
    source_scene_spec_sha256: Sha256
    source_material_plan_sha256: Sha256 | None = None
    material_dependency_closure_sha256: Sha256 | None = None
    material_plan_path: RelativePath
    material_plan_sha256: Sha256
    material_graph_path: RelativePath
    material_graph_sha256: Sha256
    completed_by: Literal["controller"] = "controller"
    canonical_written: Literal[False] = False
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"

    @model_validator(mode="after")
    def validate_output_bindings(self) -> MaterialControllerCompletionV2:
        """Require distinct outputs and exact canonical source bindings."""

        if self.material_plan_path == self.material_graph_path:
            raise ValueError("material controller outputs must use distinct paths")
        if self.material_dependency_closure_sha256 is None:
            scene_hash = self.immutable_input_sha256.get("analysis/scene_spec.json")
            if scene_hash != self.source_scene_spec_sha256:
                raise ValueError(
                    "material completion must bind the canonical SceneSpec immutable input"
                )
            material_hash = self.immutable_input_sha256.get(
                "analysis/material_plan.json"
            )
            if material_hash != self.source_material_plan_sha256:
                raise ValueError(
                    "material completion baseline MaterialPlan binding is inconsistent"
                )
        else:
            projected_hashes = set(self.immutable_input_sha256.values())
            if self.source_scene_spec_sha256 not in projected_hashes:
                raise ValueError(
                    "closure completion omits its exact SceneSpec snapshot"
                )
            if (
                self.source_material_plan_sha256 is not None
                and (
                    self.source_material_plan_sha256 not in projected_hashes
                    or self.immutable_input_sha256.get(
                        "analysis/material_plan.json"
                    )
                    != self.source_material_plan_sha256
                )
            ):
                raise ValueError(
                    "closure completion omits its immutable MaterialPlan baseline"
                )
        return self


class MaterialClosurePromotionBoundaryV2(AQV2Evidence):
    """Bind one preflighted and user-approved closure to exact controller projections."""

    boundary_id: PortableId
    current_state: AQV2Artifact
    dependency_closure: AQV2Artifact
    dependency_closure_receipt: AQV2Artifact
    graph_rebinding_receipt: AQV2Artifact
    preflight_report: AQV2Artifact
    shadow_compile_receipt: AQV2Artifact
    neutral_preview_manifest: AQV2Artifact
    appearance_approval: AQV2Artifact
    state_consistency_report: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    rebound_material_graph: AQV2Artifact
    immutable_input_sha256: dict[RelativePath, Sha256] = Field(min_length=1)
    planned_output_sha256: dict[RelativePath, Sha256] = Field(min_length=2)
    canonical_scene_spec_sha256: Sha256
    canonical_blend_sha256: Sha256
    uv_layout_fingerprint: Sha256
    controller_invocation_limit: Literal[1] = 1
    appearance_approval_required: Literal[True] = True
    controller_may_execute: Literal[True] = True
    canonical_write_authority: Literal["material_phase_service_only"] = (
        "material_phase_service_only"
    )

    @model_validator(mode="after")
    def validate_boundary_provenance(self) -> MaterialClosurePromotionBoundaryV2:
        """Require every gate and exact candidate to appear once in provenance."""

        named = [
            self.current_state,
            self.dependency_closure,
            self.dependency_closure_receipt,
            self.graph_rebinding_receipt,
            self.preflight_report,
            self.shadow_compile_receipt,
            self.neutral_preview_manifest,
            self.appearance_approval,
            self.state_consistency_report,
            self.candidate_material_plan,
            self.rebound_material_graph,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {
            (item.path, item.sha256, item.byte_size) for item in self.provenance
        }
        if expected != observed or len(named) != len(self.provenance):
            raise ValueError("material closure boundary provenance is incomplete")
        if len(self.immutable_input_sha256) != len(
            set(self.immutable_input_sha256)
        ) or len(self.planned_output_sha256) != len(
            set(self.planned_output_sha256)
        ):
            raise ValueError("material closure boundary projections contain duplicates")
        if set(self.immutable_input_sha256) & set(self.planned_output_sha256):
            raise ValueError("material closure inputs and outputs must be disjoint")
        return self


class MaterialClosurePolicyPromotionBoundaryV03(ApprovalV03Evidence):
    """Bind passed closure evidence to one exact non-user material policy authority."""

    boundary_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    approval_budget: ApprovalArtifact
    policy_authorization: ApprovalArtifact
    current_state: AQV2Artifact
    dependency_closure: AQV2Artifact
    dependency_closure_receipt: AQV2Artifact
    graph_rebinding_receipt: AQV2Artifact
    preflight_report: AQV2Artifact
    shadow_compile_receipt: AQV2Artifact
    neutral_preview_manifest: AQV2Artifact
    state_consistency_report: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    rebound_material_graph: AQV2Artifact
    provenance: list[AQV2Artifact] = Field(min_length=11, max_length=11)
    immutable_input_sha256: dict[RelativePath, Sha256] = Field(min_length=1)
    planned_output_sha256: dict[RelativePath, Sha256] = Field(min_length=2)
    canonical_scene_spec_sha256: Sha256
    canonical_blend_sha256: Sha256
    uv_layout_fingerprint: Sha256
    controller_invocation_limit: Literal[1] = 1
    appearance_approval_required: Literal[False] = False
    policy_authorization_required: Literal[True] = True
    policy_authorization_is_user_approval: Literal[False] = False
    controller_may_execute: Literal[True] = True
    canonical_write_authority: Literal["material_phase_service_only"] = (
        "material_phase_service_only"
    )

    @model_validator(mode="after")
    def validate_policy_boundary_provenance(
        self,
    ) -> MaterialClosurePolicyPromotionBoundaryV03:
        """Require every gate, policy authority, and exact candidate once in provenance."""

        policy_as_aq = AQV2Artifact.model_validate(
            self.policy_authorization.model_dump(mode="python")
        )
        named = [
            self.current_state,
            self.dependency_closure,
            self.dependency_closure_receipt,
            self.graph_rebinding_receipt,
            self.preflight_report,
            self.shadow_compile_receipt,
            self.neutral_preview_manifest,
            policy_as_aq,
            self.state_consistency_report,
            self.candidate_material_plan,
            self.rebound_material_graph,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {
            (item.path, item.sha256, item.byte_size) for item in self.provenance
        }
        if expected != observed or len(named) != len(self.provenance):
            raise ValueError("material policy boundary provenance is incomplete")
        if set(self.immutable_input_sha256) & set(self.planned_output_sha256):
            raise ValueError("material policy boundary inputs and outputs overlap")
        return self


class MaterialPolicyAuthorizationConsumptionReceiptV03(ApprovalV03Evidence):
    """Bind one material controller request to an exact unused AQ policy authority."""

    receipt_id: PortableId
    policy_profile: ApprovalArtifact
    approval_envelope: ApprovalArtifact
    approval_budget: ApprovalArtifact
    policy_authorization: ApprovalArtifact
    material_policy_boundary: ApprovalArtifact
    controller_request: ApprovalArtifact
    candidate_material_plan_sha256: Sha256
    rebound_material_graph_sha256: Sha256
    closure_sha256: Sha256
    preflight_report_sha256: Sha256
    neutral_preview_sha256: Sha256
    gate_kind: Literal["material_candidate_promotion"] = (
        "material_candidate_promotion"
    )
    consumption_ordinal: Literal[1] = 1
    consumed_once: Literal[True] = True
    is_user_approval: Literal[False] = False
    approved_by_user: Literal[False] = False
    user_approval_created: Literal[False] = False


MaterialClosurePromotionBoundary = (
    MaterialClosurePromotionBoundaryV2 | MaterialClosurePolicyPromotionBoundaryV03
)
"""Represent either the unchanged user-approval boundary or additive policy boundary."""


class MaterialPromotionIntentV2(AQV2Evidence):
    """Journal one fully validated material candidate before any canonical write."""

    intent_id: PortableId
    controller_result: AQV2Artifact
    controller_completion: AQV2Artifact
    material_plan_candidate: AQV2Artifact
    material_graph_spec: AQV2Artifact
    material_validation: AQV2Artifact
    graph_compile_report: AQV2Artifact
    source_scene_spec: AQV2Artifact
    previous_material_plan: AQV2Artifact | None = None
    expected_canonical_material_sha256: Sha256 | None = None
    candidate_material_sha256: Sha256
    canonical_scene_unchanged: Literal[True] = True
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"

    @model_validator(mode="after")
    def validate_intent_bindings(self) -> MaterialPromotionIntentV2:
        """Require the intent provenance to equal every exact pre-promotion input."""

        named = [
            self.controller_result,
            self.controller_completion,
            self.material_plan_candidate,
            self.material_graph_spec,
            self.material_validation,
            self.graph_compile_report,
            self.source_scene_spec,
            *(
                [self.previous_material_plan]
                if self.previous_material_plan is not None
                else []
            ),
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {
            (item.path, item.sha256, item.byte_size) for item in self.provenance
        }
        if expected != observed or len(named) != len(self.provenance):
            raise ValueError("material promotion intent provenance is incomplete")
        if self.candidate_material_sha256 != self.material_plan_candidate.sha256:
            raise ValueError("material promotion intent candidate hash is inconsistent")
        if self.previous_material_plan is None:
            if self.expected_canonical_material_sha256 is not None:
                raise ValueError("missing baseline cannot declare a canonical material hash")
        elif (
            self.expected_canonical_material_sha256
            != self.previous_material_plan.sha256
        ):
            raise ValueError("material promotion intent baseline hash is inconsistent")
        return self


class MaterialPhaseReceiptV2(AQV2Evidence):
    """Bind successful host promotion to immutable rebuild and compile snapshots."""

    receipt_id: PortableId
    status: Literal["promoted"] = "promoted"
    promotion_intent: AQV2Artifact
    controller_result: AQV2Artifact
    material_plan_candidate: AQV2Artifact
    material_graph_spec: AQV2Artifact
    material_validation: AQV2Artifact
    graph_compile_report: AQV2Artifact
    archived_material_plan: AQV2Artifact | None = None
    canonical_material_snapshot: AQV2Artifact
    canonical_scene_snapshot: AQV2Artifact
    authoring_blend_snapshot: AQV2Artifact
    scene_inventory_snapshot: AQV2Artifact
    scene_validation_snapshot: AQV2Artifact
    build_provenance_snapshot: AQV2Artifact
    previous_canonical_material_sha256: Sha256 | None = None
    canonical_material_plan_sha256: Sha256
    canonical_scene_spec_sha256: Sha256
    build_fingerprint: Sha256
    budget_usage_after: BudgetUsageV2
    primary_object_only_validated: Literal[True] = True
    canonical_scene_unchanged: Literal[True] = True
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"

    @model_validator(mode="after")
    def validate_receipt_bindings(self) -> MaterialPhaseReceiptV2:
        """Require exact immutable snapshots for every promoted canonical derivative."""

        named = [
            self.promotion_intent,
            self.controller_result,
            self.material_plan_candidate,
            self.material_graph_spec,
            self.material_validation,
            self.graph_compile_report,
            *(
                [self.archived_material_plan]
                if self.archived_material_plan is not None
                else []
            ),
            self.canonical_material_snapshot,
            self.canonical_scene_snapshot,
            self.authoring_blend_snapshot,
            self.scene_inventory_snapshot,
            self.scene_validation_snapshot,
            self.build_provenance_snapshot,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {
            (item.path, item.sha256, item.byte_size) for item in self.provenance
        }
        if expected != observed or len(named) != len(self.provenance):
            raise ValueError("material phase receipt provenance is incomplete")
        if (
            self.canonical_material_plan_sha256
            != self.canonical_material_snapshot.sha256
            or self.canonical_scene_spec_sha256
            != self.canonical_scene_snapshot.sha256
        ):
            raise ValueError("material phase canonical snapshot hashes are inconsistent")
        if self.archived_material_plan is None:
            if self.previous_canonical_material_sha256 is not None:
                raise ValueError("missing archive cannot declare a previous material hash")
        elif (
            self.archived_material_plan.sha256
            != self.previous_canonical_material_sha256
        ):
            raise ValueError("material phase archive hash is inconsistent")
        return self


class MaterialPhaseRollbackReceiptV2(AQV2Evidence):
    """Record fail-closed restoration after a post-promotion host failure."""

    receipt_id: PortableId
    status: Literal["rolled_back", "rollback_failed"]
    promotion_intent: AQV2Artifact
    controller_result: AQV2Artifact
    material_plan_candidate: AQV2Artifact
    previous_material_plan: AQV2Artifact | None = None
    restored_material_snapshot: AQV2Artifact | None = None
    restored_blend_snapshot: AQV2Artifact | None = None
    restored_inventory_snapshot: AQV2Artifact | None = None
    restored_validation_snapshot: AQV2Artifact | None = None
    restored_build_provenance_snapshot: AQV2Artifact | None = None
    failure_type: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)
    canonical_scene_unchanged: Literal[True] = True
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"

    @model_validator(mode="after")
    def validate_rollback_bindings(self) -> MaterialPhaseRollbackReceiptV2:
        """Require complete restored evidence only when rollback itself succeeded."""

        restored = [
            self.restored_blend_snapshot,
            self.restored_inventory_snapshot,
            self.restored_validation_snapshot,
            self.restored_build_provenance_snapshot,
        ]
        if self.status == "rolled_back" and any(item is None for item in restored):
            raise ValueError("successful material rollback requires rebuilt evidence")
        if self.status == "rollback_failed" and all(item is not None for item in restored):
            raise ValueError("rollback_failed cannot claim a complete restored rebuild")
        if self.previous_material_plan is None:
            if self.restored_material_snapshot is not None:
                raise ValueError("absent baseline cannot produce a restored material snapshot")
        elif self.status == "rolled_back" and self.restored_material_snapshot is None:
            raise ValueError("restored material baseline requires an immutable snapshot")
        named = [
            self.promotion_intent,
            self.controller_result,
            self.material_plan_candidate,
            *(
                [self.previous_material_plan]
                if self.previous_material_plan is not None
                else []
            ),
            *(
                [self.restored_material_snapshot]
                if self.restored_material_snapshot is not None
                else []
            ),
            *[item for item in restored if item is not None],
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {
            (item.path, item.sha256, item.byte_size) for item in self.provenance
        }
        if expected != observed or len(named) != len(self.provenance):
            raise ValueError("material rollback receipt provenance is incomplete")
        return self
