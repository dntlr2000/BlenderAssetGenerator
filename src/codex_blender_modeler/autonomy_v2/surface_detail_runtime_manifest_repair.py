"""Exact-approved append-only repair for Blender runtime surface-detail manifests."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from ..analysis.models import ModelingPlan
from ..analysis.surface_details import validate_surface_detail_contract
from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import (
    deterministic_directory_files,
    native_io_path,
    sha256_file,
    stable_json_digest,
)
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..material_graph.models import MaterialGraphArtifact, MaterialGraphSpec
from ..material_manifest import load_material_manifest
from ..materials.io import load_shader_recipe, resolve_job_path
from ..materials.models import MaterialPlan, ShaderRecipe
from ..models import SceneSpec
from ..production.controller_executor.models import ControllerExecutionRequest, ControllerResult
from ..stabilization.models import PortableId, Sha256
from ..texturing.models import TextureManifest
from ..workspace import canonical_scene_spec_write_lock, job_dir
from .delivery_service import validate_v2_artifact, write_immutable_v2_model
from .material_phase_models import MaterialControllerCompletionV2, MaterialPhaseReceiptV2
from .material_phase_service import (
    _canonical_scene_and_scope,
    _compile_or_adopt_graph,
    _load_controller_material_bundle,
    _material_validation_artifact,
    _publish_or_adopt_intent,
    _request_input_map,
    _snapshot_exact,
    _validate_graph_binding,
    _validate_material_phase_receipt_payload,
    _validate_material_plan_dependencies,
)
from .models import (
    AQV2Artifact,
    AQV2Evidence,
    AQV2StrictModel,
    AutonomyPlanV2,
    AutonomyStateV2,
    BudgetUsageV2,
)
from .surface_detail_spatial_recovery import (
    _ADDITIVE_MATERIAL_IDS,
    _ASSIGNMENT_SPECIALIZATIONS,
    _DETAIL_CONTRACTS,
    _EXPECTED_PROFILE,
    SurfaceDetailSpatialGeometryReviewPlan,
    SurfaceDetailSpatialGeometryReviewReceipt,
    _artifact,
    _copy_exact,
    _execute_controller,
    _prepare_shadow_job,
    _topology_comparison,
    _usage_after_controller,
    _validate_exact_hash,
    _validate_profile_opt_in,
    _write_exact_bytes,
    _write_json_object,
    _write_model,
    _write_or_adopt_v2_model,
    expected_surface_detail_geometry_review_approval,
)
from .transitions import transition_state

_PRODUCER = "codex_blender_modeler.autonomy_v2.surface_detail_runtime_manifest_repair"
_PLAN_ID = "item-crystalgun-surface-detail-runtime-manifest-repair-01"
_PLAN_SHA256 = "58567fcb8c6741f5eaf96637972da1e5b808806a49f72082cc7fac69ec42fd84"
_REFERENCE_SHA256 = "dd2ecc1bfeb403595d8a4f77875980fd7cad7d29582d661a248fa2d639c846bf"
_SOURCE_STATE_SHA256 = "81910704432cc3e737b228dcd7346520b2b3751ea202aacd5e59c68c8f02da81"
_SOURCE_FAILURE_SHA256 = "2559065d9617130db653c10c679f8708c12c5975f504c9639380b56ec8e53c36"
_SOURCE_REQUEST_SHA256 = "e17b96c46ec3ff57051bffcab5fb52818ba179222e65922460ed60d09898ac10"
_SOURCE_RESULT_SHA256 = "e00782d6b4dc58f4aedfd4aea29903557f535dad33258207ab007ad08c9f750d"
_SOURCE_MATERIAL_SHA256 = "c5273ac50c21d7fc146b1d2a96950d8d9c1ba1b234e14df22fc1d312e1cdf8a3"
_SOURCE_GRAPH_SHA256 = "19034a86939e12a186f34677f7d7dbda2a9d461e5743890caa0e7e791917be2f"
_FAILED_PREFLIGHT_SHA256 = "2deaa795cd6ee436ef3d7f31fe4f31a36c648cf9d86d1de3594a64a54e27952b"
_SOURCE_RECOVERY_PLAN_SHA256 = "d1a22f2d6140d4d8662eeeb5221424ce02ba01eca5a902dbee368130a4c88970"
_DETAIL_SUFFIXES = {
    "detail.filigree.body": "fb",
    "detail.filigree.grip": "fg",
    "detail.crystal.internal_emission": "ce",
    "detail.crystal.facet_lines": "cf",
}
_RECIPE_SUFFIXES = {
    "mat.metal.trim.filigree_body": "mtfb",
    "mat.grip.leather": "gl",
    "mat.crystal.emission": "ce",
    "mat.crystal.translucent.facet_crown": "ctfc",
}


class SurfaceDetailRuntimeManifestRepairPreparation(AQV2Evidence):
    """Freeze exact repair approval, failed evidence, and corrected controller blueprints."""

    repair_id: PortableId
    repair_plan: AQV2Artifact
    approval: AQV2Artifact
    source_aq_state: AQV2Artifact
    source_failure_receipt: AQV2Artifact
    source_controller_request: AQV2Artifact
    source_controller_result: AQV2Artifact
    source_material_plan: AQV2Artifact
    source_material_graph: AQV2Artifact
    failed_preflight: AQV2Artifact
    source_scene_spec: AQV2Artifact
    source_modeling_plan: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    candidate_material_graph: AQV2Artifact
    texture_manifests: list[AQV2Artifact] = Field(min_length=4, max_length=4)
    shader_recipes: list[AQV2Artifact] = Field(min_length=4, max_length=4)
    texture_channels: list[AQV2Artifact] = Field(min_length=8)
    imagegen_source: AQV2Artifact
    imagegen_semantic_review: AQV2Artifact
    status: Literal["prepared"] = "prepared"
    source_controller_invocations_consumed: Literal[1] = 1
    new_imagegen_invocation_performed: Literal[False] = False
    geometry_topology_changed: Literal[False] = False
    semantic_ids_changed: Literal[False] = False
    material_ids_changed: Literal[False] = False
    material_assignments_changed: Literal[False] = False
    human_reviewed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_repair_preparation(self) -> SurfaceDetailRuntimeManifestRepairPreparation:
        """Require provenance to equal every exact source and corrected candidate artifact."""

        named = [
            self.repair_plan,
            self.approval,
            self.source_aq_state,
            self.source_failure_receipt,
            self.source_controller_request,
            self.source_controller_result,
            self.source_material_plan,
            self.source_material_graph,
            self.failed_preflight,
            self.source_scene_spec,
            self.source_modeling_plan,
            self.candidate_material_plan,
            self.candidate_material_graph,
            *self.texture_manifests,
            *self.shader_recipes,
            *self.texture_channels,
            self.imagegen_source,
            self.imagegen_semantic_review,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("runtime manifest repair preparation provenance is incomplete")
        if self.source_fingerprint != self.source_failure_receipt.sha256:
            raise ValueError("runtime manifest repair source failure changed")
        return self


class MaterialBindingDerivativeReceipt(AQV2Evidence):
    """Bind two material-slot-only MeshPayload derivatives to immutable source payloads."""

    derivative_id: PortableId
    source_payloads: list[AQV2Artifact] = Field(min_length=2, max_length=2)
    derivative_payloads: list[AQV2Artifact] = Field(min_length=2, max_length=2)
    binding_changes: dict[str, str] = Field(min_length=2, max_length=2)
    topology_payload_sha256: dict[str, Sha256] = Field(min_length=2, max_length=2)
    topology_unchanged: Literal[True] = True
    semantic_ids_unchanged: Literal[True] = True
    vertices_unchanged: Literal[True] = True
    faces_unchanged: Literal[True] = True
    uv_unchanged: Literal[True] = True
    material_slots_only: Literal[True] = True
    human_reviewed: Literal[False] = False

    @model_validator(mode="after")
    def validate_binding_derivative(self) -> MaterialBindingDerivativeReceipt:
        """Require provenance to contain exactly the two sources and two derivatives."""

        named = [*self.source_payloads, *self.derivative_payloads]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("material binding derivative provenance is incomplete")
        return self


class SurfaceDetailGeometryReviewApprovalReceipt(AQV2Evidence):
    """Freeze one exact user geometry-review decision without promoting materials."""

    recovery_id: PortableId
    review_plan: AQV2Artifact
    geometry_review_receipt: AQV2Artifact
    material_binding_derivative: AQV2Artifact
    approval: AQV2Artifact
    candidate_scene_spec: AQV2Artifact
    candidate_modeling_plan: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    candidate_material_graph: AQV2Artifact
    candidate_blend: AQV2Artifact
    candidate_inventory: AQV2Artifact
    candidate_validation: AQV2Artifact
    topology_comparison: AQV2Artifact
    surface_detail_validation: AQV2Artifact
    preview: AQV2Artifact
    geometry_review_approved: Literal[True] = True
    topology_unchanged: Literal[True] = True
    semantic_ids_unchanged: Literal[True] = True
    material_promotion_allowed: Literal[False] = False
    canonical_scene_write_performed: Literal[False] = False
    canonical_blend_write_performed: Literal[False] = False
    material_phase_receipt_created: Literal[False] = False
    human_reviewed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_review_approval_provenance(
        self,
    ) -> SurfaceDetailGeometryReviewApprovalReceipt:
        """Require provenance to contain exactly the approved plan and reviewed artifacts."""

        named = [
            self.review_plan,
            self.geometry_review_receipt,
            self.material_binding_derivative,
            self.approval,
            self.candidate_scene_spec,
            self.candidate_modeling_plan,
            self.candidate_material_plan,
            self.candidate_material_graph,
            self.candidate_blend,
            self.candidate_inventory,
            self.candidate_validation,
            self.topology_comparison,
            self.surface_detail_validation,
            self.preview,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("geometry review approval provenance is incomplete")
        if self.source_fingerprint != self.review_plan.sha256:
            raise ValueError("geometry review approval source plan changed")
        return self


class SurfaceDetailMaterialPromotionPlan(AQV2StrictModel):
    """Declare the next exact host-only material-promotion boundary."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    plan_id: PortableId
    status: Literal["awaiting_user_approval"] = "awaiting_user_approval"
    job_id: str
    source_session_id: PortableId
    source_aq_state_sha256: Sha256
    source_geometry_review_plan_sha256: Sha256
    geometry_review_approval_receipt_sha256: Sha256
    source_recovery_plan_sha256: Sha256
    reference_sha256: Sha256
    canonical_scene_spec_v02_sha256: Sha256
    canonical_modeling_plan_sha256: Sha256
    canonical_blend_sha256: Sha256
    candidate_scene_spec_v02_sha256: Sha256
    candidate_modeling_plan_sha256: Sha256
    candidate_material_plan_sha256: Sha256
    candidate_material_graph_sha256: Sha256
    candidate_blend_sha256: Sha256
    candidate_inventory_sha256: Sha256
    candidate_validation_sha256: Sha256
    topology_comparison_sha256: Sha256
    surface_detail_validation_sha256: Sha256
    preview_sha256: Sha256
    material_binding_derivative_sha256: Sha256
    controller_profile_sha256: Sha256
    controller_request_sha256: Sha256
    controller_result_sha256: Sha256
    controller_completion_sha256: Sha256
    additive_material_ids: list[str] = Field(min_length=2, max_length=2)
    material_assignment_specializations: dict[str, str] = Field(min_length=2, max_length=2)
    effective_budget_usage: BudgetUsageV2
    remaining_budget: dict[str, int]
    topology_unchanged: Literal[True] = True
    semantic_ids_unchanged: Literal[True] = True
    preserve_existing_material_ids: Literal[True] = True
    reuse_controller_result: Literal[True] = True
    new_controller_invocation_allowed: Literal[False] = False
    controller_result_source_binding_preflight_required: Literal[True] = True
    canonical_scene_and_modeling_binding_update_allowed_if_approved: Literal[True] = True
    canonical_geometry_payload_overwrite_allowed: Literal[False] = False
    canonical_promotion_limit: Literal[1] = 1
    host_material_promotion_service_required: Literal[True] = True
    material_phase_receipt_v2_required: Literal[True] = True
    blender_version: Literal["5.0.1"] = "5.0.1"
    neutral_preview_required: Literal[True] = True
    aq_iq_resume_after_promotion: Literal[True] = True
    material_promotion_approved: Literal[False] = False
    human_reviewed: Literal[False] = False
    delivery_disabled: Literal[True] = True
    optimization_disabled: Literal[True] = True
    lod_disabled: Literal[True] = True
    collider_disabled: Literal[True] = True
    destination_write_disabled: Literal[True] = True

    @model_validator(mode="after")
    def validate_promotion_scope(self) -> SurfaceDetailMaterialPromotionPlan:
        """Keep the proposed promotion limited to the reviewed additive bindings."""

        if self.additive_material_ids != list(_ADDITIVE_MATERIAL_IDS):
            raise ValueError("material promotion additive material IDs changed")
        if self.material_assignment_specializations != _ASSIGNMENT_SPECIALIZATIONS:
            raise ValueError("material promotion assignments changed")
        expected_remaining = {
            "total_blender_builds": 1,
            "controller_invocations": 11,
            "canonical_promotions": 4,
            "total_actions": 64,
        }
        if self.remaining_budget != expected_remaining:
            raise ValueError("material promotion remaining budget changed")
        return self


class SurfaceDetailMaterialPromotionReceipt(AQV2Evidence):
    """Bind the exact approval to canonical material evidence and resumed AQ state."""

    promotion_id: PortableId
    approval: AQV2Artifact
    promotion_plan: AQV2Artifact
    geometry_review_approval: AQV2Artifact
    material_binding_manifest: AQV2Artifact
    material_phase_receipt: AQV2Artifact
    neutral_preview_report: AQV2Artifact
    neutral_preview_image: AQV2Artifact
    source_state: AQV2Artifact
    candidate_scene_spec: AQV2Artifact
    candidate_modeling_plan: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    candidate_material_graph: AQV2Artifact
    candidate_blend: AQV2Artifact
    resumed_state: AQV2Artifact
    status: Literal["promoted"] = "promoted"
    topology_unchanged: Literal[True] = True
    semantic_ids_unchanged: Literal[True] = True
    canonical_geometry_payload_overwrite_performed: Literal[False] = False
    controller_reused: Literal[True] = True
    controller_invocation_performed: Literal[False] = False
    imagegen_invocation_performed: Literal[False] = False
    material_phase_receipt_v2_present: Literal[True] = True
    neutral_preview_present: Literal[True] = True
    blender_version: Literal["5.0.1"] = "5.0.1"
    human_reviewed: Literal[False] = False
    delivery_performed: Literal[False] = False
    optimization_performed: Literal[False] = False
    lod_created: Literal[False] = False
    collider_created: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_promotion_provenance(self) -> SurfaceDetailMaterialPromotionReceipt:
        """Require every exact approval, candidate, receipt, preview, and state artifact."""

        named = [
            self.approval,
            self.promotion_plan,
            self.geometry_review_approval,
            self.material_binding_manifest,
            self.material_phase_receipt,
            self.neutral_preview_report,
            self.neutral_preview_image,
            self.source_state,
            self.candidate_scene_spec,
            self.candidate_modeling_plan,
            self.candidate_material_plan,
            self.candidate_material_graph,
            self.candidate_blend,
            self.resumed_state,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("surface-detail material promotion provenance is incomplete")
        if self.source_fingerprint != self.material_phase_receipt.sha256:
            raise ValueError("surface-detail material phase receipt changed")
        return self


class SurfaceDetailMaterialPromotionRollbackReceipt(AQV2Evidence):
    """Record exact restoration when the specialized host promotion fails."""

    promotion_id: PortableId
    approval: AQV2Artifact
    promotion_plan: AQV2Artifact
    archived_scene_spec: AQV2Artifact
    archived_modeling_plan: AQV2Artifact
    archived_blend: AQV2Artifact
    archived_derived: list[AQV2Artifact] = Field(default_factory=list)
    archived_material_plan: AQV2Artifact | None = None
    archived_binding_manifest: AQV2Artifact | None = None
    restored_scene_spec_sha256: Sha256
    restored_modeling_plan_sha256: Sha256
    restored_blend_sha256: Sha256
    failure_type: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)
    status: Literal["rolled_back"] = "rolled_back"
    canonical_restored: Literal[True] = True
    material_phase_receipt_v2_present: Literal[False] = False
    human_reviewed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_rollback_provenance(
        self,
    ) -> SurfaceDetailMaterialPromotionRollbackReceipt:
        """Require exact approval, plan, and three canonical baseline archives."""

        named = [
            self.approval,
            self.promotion_plan,
            self.archived_scene_spec,
            self.archived_modeling_plan,
            self.archived_blend,
            *self.archived_derived,
            *([self.archived_material_plan] if self.archived_material_plan is not None else []),
            *(
                [self.archived_binding_manifest]
                if self.archived_binding_manifest is not None
                else []
            ),
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("surface-detail material rollback provenance is incomplete")
        return self


class MaterialCompletionBindingRepairPreparation(AQV2Evidence):
    """Freeze the exact failed lifecycle and reviewed candidate before one repair."""

    repair_id: PortableId
    repair_plan: AQV2Artifact
    approval: AQV2Artifact
    source_state: AQV2Artifact
    source_material_promotion_plan: AQV2Artifact
    failed_promotion_rollback: AQV2Artifact
    failed_controller_request: AQV2Artifact
    failed_controller_result: AQV2Artifact
    failed_controller_completion: AQV2Artifact
    geometry_review_approval: AQV2Artifact
    material_binding_derivative: AQV2Artifact
    candidate_scene_spec: AQV2Artifact
    candidate_modeling_plan: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    candidate_material_graph: AQV2Artifact
    candidate_blend: AQV2Artifact
    status: Literal["prepared"] = "prepared"
    controller_invocation_limit: Literal[1] = 1
    blender_build_limit: Literal[1] = 1
    canonical_promotion_limit: Literal[1] = 1
    imagegen_invocation_allowed: Literal[False] = False
    geometry_topology_changed: Literal[False] = False
    semantic_ids_changed: Literal[False] = False
    material_ids_changed: Literal[False] = False
    human_reviewed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_preparation_provenance(
        self,
    ) -> MaterialCompletionBindingRepairPreparation:
        """Require every approved source and candidate artifact exactly once."""

        named = [
            self.repair_plan,
            self.approval,
            self.source_state,
            self.source_material_promotion_plan,
            self.failed_promotion_rollback,
            self.failed_controller_request,
            self.failed_controller_result,
            self.failed_controller_completion,
            self.geometry_review_approval,
            self.material_binding_derivative,
            self.candidate_scene_spec,
            self.candidate_modeling_plan,
            self.candidate_material_plan,
            self.candidate_material_graph,
            self.candidate_blend,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("completion binding repair preparation provenance is incomplete")
        if self.source_fingerprint != self.failed_promotion_rollback.sha256:
            raise ValueError("completion binding repair rollback source changed")
        return self


class MaterialCompletionBindingPromotionReceipt(AQV2Evidence):
    """Bind the repaired controller lifecycle to the promoted material receipt."""

    repair_id: PortableId
    repair_plan: AQV2Artifact
    approval: AQV2Artifact
    preparation: AQV2Artifact
    controller_profile: AQV2Artifact
    controller_assignment: AQV2Artifact
    controller_request: AQV2Artifact
    controller_result: AQV2Artifact
    controller_completion: AQV2Artifact
    material_binding_manifest: AQV2Artifact
    material_phase_receipt: AQV2Artifact
    neutral_preview_report: AQV2Artifact
    neutral_preview_image: AQV2Artifact
    resumed_state: AQV2Artifact
    status: Literal["promoted"] = "promoted"
    controller_invocation_performed: Literal[True] = True
    controller_completion_full_request_bound: Literal[True] = True
    blender_builds_performed: Literal[1] = 1
    canonical_promotions_performed: Literal[1] = 1
    material_phase_receipt_v2_present: Literal[True] = True
    neutral_preview_present: Literal[True] = True
    topology_unchanged: Literal[True] = True
    semantic_ids_unchanged: Literal[True] = True
    material_ids_preserved: Literal[True] = True
    imagegen_invocation_performed: Literal[False] = False
    human_reviewed: Literal[False] = False
    delivery_performed: Literal[False] = False
    optimization_performed: Literal[False] = False
    lod_created: Literal[False] = False
    collider_created: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_promotion_provenance(
        self,
    ) -> MaterialCompletionBindingPromotionReceipt:
        """Require the repaired lifecycle, receipt, preview, and resumed state."""

        named = [
            self.repair_plan,
            self.approval,
            self.preparation,
            self.controller_profile,
            self.controller_assignment,
            self.controller_request,
            self.controller_result,
            self.controller_completion,
            self.material_binding_manifest,
            self.material_phase_receipt,
            self.neutral_preview_report,
            self.neutral_preview_image,
            self.resumed_state,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("completion binding promotion provenance is incomplete")
        if self.source_fingerprint != self.material_phase_receipt.sha256:
            raise ValueError("completion binding material receipt changed")
        return self


class MaterialCompletionBindingRepairRollbackReceipt(AQV2Evidence):
    """Record fail-closed restoration after an approved binding repair attempt."""

    repair_id: PortableId
    approval: AQV2Artifact
    repair_plan: AQV2Artifact
    preparation: AQV2Artifact | None = None
    archived_scene_spec: AQV2Artifact
    archived_modeling_plan: AQV2Artifact
    archived_blend: AQV2Artifact
    archived_derived: list[AQV2Artifact] = Field(default_factory=list)
    archived_material_plan: AQV2Artifact | None = None
    archived_binding_manifest: AQV2Artifact | None = None
    attempted_controller_request: AQV2Artifact | None = None
    attempted_controller_result: AQV2Artifact | None = None
    attempted_controller_completion: AQV2Artifact | None = None
    restored_scene_spec_sha256: Sha256
    restored_modeling_plan_sha256: Sha256
    restored_blend_sha256: Sha256
    failure_type: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1024)
    status: Literal["rolled_back"] = "rolled_back"
    canonical_restored: Literal[True] = True
    material_phase_receipt_v2_present: Literal[False] = False
    human_reviewed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_rollback_provenance(
        self,
    ) -> MaterialCompletionBindingRepairRollbackReceipt:
        """Require all present lifecycle and archive artifacts in provenance."""

        named = [
            self.approval,
            self.repair_plan,
            *([self.preparation] if self.preparation is not None else []),
            self.archived_scene_spec,
            self.archived_modeling_plan,
            self.archived_blend,
            *self.archived_derived,
            *([self.archived_material_plan] if self.archived_material_plan is not None else []),
            *(
                [self.archived_binding_manifest]
                if self.archived_binding_manifest is not None
                else []
            ),
            *(
                [self.attempted_controller_request]
                if self.attempted_controller_request is not None
                else []
            ),
            *(
                [self.attempted_controller_result]
                if self.attempted_controller_result is not None
                else []
            ),
            *(
                [self.attempted_controller_completion]
                if self.attempted_controller_completion is not None
                else []
            ),
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("completion binding rollback provenance is incomplete")
        return self


def _expected_approval(payload: dict[str, Any], plan_sha256: str) -> str:
    """Render the sole exact user approval accepted for this runtime manifest repair."""

    return (
        "APPROVE MATERIAL SURFACE DETAIL RUNTIME MANIFEST REPAIR "
        f"job_id={payload['job_id']} source_session_id={payload['source_session_id']} "
        f"source_aq_state_sha256={payload['source_aq_state_sha256']} "
        f"source_recovery_plan_sha256={payload['source_recovery_plan_sha256']} "
        f"source_failure_receipt_sha256={payload['source_failure_receipt_sha256']} "
        f"source_controller_request_sha256={payload['source_controller_request_sha256']} "
        f"source_controller_result_sha256={payload['source_controller_result_sha256']} "
        f"source_material_plan_sha256={payload['source_material_plan_sha256']} "
        f"source_material_graph_sha256={payload['source_material_graph_sha256']} "
        f"failed_preflight_sha256={payload['failed_preflight_sha256']} "
        f"repair_plan_sha256={plan_sha256} new_manifest_root=a2/sdsr02 "
        "changes=detail.filigree.body:hybrid->image,"
        "detail.filigree.grip:hybrid->image,"
        "detail.crystal.facet_lines:hybrid->image,all:omit_null_placement_fields "
        "retarget_material_plan_and_graph=true new_controller_invocation_allowed=true "
        "controller_invocation_limit=1 new_imagegen_invocation_allowed=false "
        "preserve_geometry_topology=true preserve_semantic_ids=true "
        "preserve_existing_material_ids=true preserve_additive_material_ids=true "
        "preserve_imagegen_evidence=true scope=append_only_runtime_manifest_contract_repair "
        "delivery_disabled=true optimization_disabled=true lod_disabled=true "
        "collider_disabled=true destination_write_disabled=true"
    )


def _validate_plan(payload: dict[str, Any], *, job_id: str, session_id: str) -> None:
    """Fail closed unless every repair authority field retains its approved value."""

    required = {
        "plan_id": _PLAN_ID,
        "status": "proposal_only",
        "approval_granted": False,
        "job_id": job_id,
        "source_session_id": session_id,
        "profile_id": _EXPECTED_PROFILE,
        "profile_status": "disabled_experimental",
        "source_aq_state_sha256": _SOURCE_STATE_SHA256,
        "source_recovery_plan_sha256": _SOURCE_RECOVERY_PLAN_SHA256,
        "source_failure_receipt_sha256": _SOURCE_FAILURE_SHA256,
        "source_controller_request_sha256": _SOURCE_REQUEST_SHA256,
        "source_controller_result_sha256": _SOURCE_RESULT_SHA256,
        "source_material_plan_sha256": _SOURCE_MATERIAL_SHA256,
        "source_material_graph_sha256": _SOURCE_GRAPH_SHA256,
        "failed_preflight_sha256": _FAILED_PREFLIGHT_SHA256,
        "reference_sha256": _REFERENCE_SHA256,
        "scope": "append_only_runtime_manifest_contract_repair",
        "preserve_geometry_topology": True,
        "preserve_semantic_ids": True,
        "preserve_existing_material_ids": True,
        "preserve_additive_material_ids": True,
        "preserve_imagegen_evidence": True,
        "delivery_disabled": True,
        "optimization_disabled": True,
        "lod_disabled": True,
        "collider_disabled": True,
        "destination_write_disabled": True,
        "human_reviewed": False,
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("runtime manifest repair authority fields changed")
    changes = payload.get("approved_changes_if_authorized")
    lifecycle = payload.get("required_lifecycle")
    if not isinstance(changes, dict) or not isinstance(lifecycle, dict):
        raise ValueError("runtime manifest repair plan is incomplete")
    expected_changes = {
        "immutable_failed_artifacts": True,
        "new_manifest_root": "a2/sdsr02",
        "source_type_changes": {
            "detail.filigree.body": "hybrid_to_image",
            "detail.filigree.grip": "hybrid_to_image",
            "detail.crystal.facet_lines": "hybrid_to_image",
        },
        "placement_serialization": "omit_null_mask_fields_for_uv_rect",
        "image_channels_reused_byte_identically": True,
        "imagegen_candidate_reused_byte_identically": True,
        "retarget_material_plan_to_new_manifests": True,
        "retarget_material_graph_to_new_manifests": True,
        "add_material_ids": [],
        "change_material_assignments": False,
    }
    if changes != expected_changes:
        raise ValueError("runtime manifest repair change set changed")
    expected_lifecycle = {
        "new_controller_invocation_allowed": True,
        "controller_invocation_limit": 1,
        "new_imagegen_invocation_allowed": False,
        "controller_executor_required": True,
        "isolated_blender_5_0_1_build_required": True,
        "runtime_manifest_preflight_required": True,
        "candidate_inventory_uv_validation_required": True,
        "topology_comparison_required": True,
        "neutral_preview_required": True,
        "geometry_review_approval_required": True,
        "material_promotion_before_geometry_review": False,
    }
    if lifecycle != expected_lifecycle:
        raise ValueError("runtime manifest repair lifecycle changed")


def _write_texture_manifest(path: Path, manifest: TextureManifest) -> None:
    """Write a runtime-compatible manifest while omitting mode-inapplicable null fields."""

    payload = (manifest.model_dump_json(indent=2, exclude_none=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"corrected runtime manifest differs: {path}")
        return
    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "xb") as handle:
        handle.write(payload)


def _target_manifest_path(root: Path, detail_id: str) -> Path:
    """Return the append-only corrected manifest path for one stable detail ID."""

    return root / "a2" / "sdsr02" / "tex" / _DETAIL_SUFFIXES[detail_id] / "manifest.json"


def _target_recipe_path(root: Path, material_id: str) -> Path:
    """Return the append-only corrected ShaderRecipe path for one stable material ID."""

    return root / "a2" / "sdsr02" / "sh" / _RECIPE_SUFFIXES[material_id] / "recipe.json"


def _author_corrected_texture_assets(
    root: Path,
) -> tuple[dict[str, TextureManifest], list[AQV2Artifact], list[AQV2Artifact]]:
    """Copy exact image channels and publish image-only runtime-compatible manifests."""

    manifests: dict[str, TextureManifest] = {}
    manifest_artifacts: list[AQV2Artifact] = []
    channel_artifacts: list[AQV2Artifact] = []
    for detail_id, contract in _DETAIL_CONTRACTS.items():
        suffix = _DETAIL_SUFFIXES[detail_id]
        source_dir = root / "a2" / "sdsr01" / "tex" / suffix
        source_path = source_dir / "spatial_texture_manifest.json"
        source = TextureManifest.model_validate_json(source_path.read_bytes())
        material_id = str(contract["material_id"])
        target_path = _target_manifest_path(root, detail_id)
        image_channels = {
            name: descriptor
            for name, descriptor in source.channels.items()
            if descriptor.source == "image"
        }
        for channel, descriptor in sorted(image_channels.items()):
            if descriptor.path is None:
                raise ValueError(f"runtime repair image channel has no path: {detail_id}/{channel}")
            source_channel = source_dir / descriptor.path
            target_channel = target_path.parent / descriptor.path
            expected_sha256 = source.provenance.generated_sha256[channel]
            _copy_exact(source_channel, target_channel, expected_sha256)
            channel_artifacts.append(
                _artifact(
                    root,
                    target_channel,
                    artifact_id=f"runtime-texture-{detail_id.replace('.', '-')}-{channel}",
                    kind="surface_detail_texture_channel",
                )
            )
        procedural = {
            **source.procedural,
            "runtime_manifest_repair": "removed unsupported neutral procedural metallic leaf",
            "runtime_channel_authority": "all declared channels are deterministic image maps",
        }
        procedural.pop("neutral_procedural_channel", None)
        procedural.pop("neutral_procedural_value_source", None)
        corrected = source.model_copy(
            update={
                "source_type": "image",
                "channels": image_channels,
                "procedural": procedural,
                "shader_recipe": _target_recipe_path(root, material_id)
                .relative_to(root)
                .as_posix(),
                "generation_notes": (
                    f"{source.generation_notes} Runtime repair serializes uv_rect without null "
                    "mask fields and exposes only byte-identical image channels."
                ),
            }
        )
        corrected = TextureManifest.model_validate(corrected.model_dump(mode="python"))
        _write_texture_manifest(target_path, corrected)
        load_material_manifest(
            {
                "id": material_id,
                "texture_manifest": target_path.relative_to(root).as_posix(),
            },
            root,
        )
        manifests[material_id] = corrected
        manifest_artifacts.append(
            _artifact(
                root,
                target_path,
                artifact_id=f"runtime-manifest-{detail_id.replace('.', '-')}",
                kind="surface_detail_texture_manifest",
            )
        )
    return manifests, manifest_artifacts, channel_artifacts


def _author_corrected_shader_recipes(
    root: Path,
    manifests: dict[str, TextureManifest],
) -> list[AQV2Artifact]:
    """Retarget four stable ShaderRecipes to corrected append-only manifests."""

    artifacts: list[AQV2Artifact] = []
    for detail_id, contract in _DETAIL_CONTRACTS.items():
        material_id = str(contract["material_id"])
        source_path = root / "a2" / "sdsr01" / "sh" / _RECIPE_SUFFIXES[material_id] / "recipe.json"
        source = load_shader_recipe(source_path)
        target_path = _target_recipe_path(root, material_id)
        manifest_path = _target_manifest_path(root, detail_id).relative_to(root).as_posix()
        corrected = source.model_copy(
            update={
                "texture_manifest": manifest_path,
                "assumptions": [
                    *source.assumptions,
                    "Runtime manifest repair uses byte-identical image maps only.",
                    "uv_rect serialization omits mode-inapplicable null mask fields.",
                ],
            }
        )
        corrected = ShaderRecipe.model_validate(corrected.model_dump(mode="python"))
        _write_model(target_path, corrected)
        if manifests[material_id].shader_recipe != target_path.relative_to(root).as_posix():
            raise ValueError(f"corrected manifest and ShaderRecipe disagree: {material_id}")
        artifacts.append(
            _artifact(
                root,
                target_path,
                artifact_id=f"runtime-recipe-{material_id}",
                kind="surface_detail_shader_recipe",
            )
        )
    return artifacts


def _corrected_material_plan(root: Path, source_path: Path) -> MaterialPlan:
    """Retarget only four detailed material records to corrected image-only companions."""

    source = MaterialPlan.model_validate_json(source_path.read_bytes())
    detail_by_material = {
        str(contract["material_id"]): detail_id for detail_id, contract in _DETAIL_CONTRACTS.items()
    }
    materials = []
    for item in source.materials:
        detail_id = detail_by_material.get(item.material_id)
        if detail_id is None:
            materials.append(item)
            continue
        materials.append(
            item.model_copy(
                update={
                    "texture_strategy": "image",
                    "texture_manifest": _target_manifest_path(root, detail_id)
                    .relative_to(root)
                    .as_posix(),
                    "shader_recipe": _target_recipe_path(root, item.material_id)
                    .relative_to(root)
                    .as_posix(),
                    "notes": [
                        *item.notes,
                        "Runtime repair removes unsupported procedural channel declarations.",
                    ],
                }
            )
        )
    candidate = source.model_copy(
        update={
            "materials": materials,
            "global_notes": [
                *source.global_notes,
                "Append-only runtime manifest repair; geometry and material IDs are unchanged.",
            ],
        }
    )
    return MaterialPlan.model_validate(candidate.model_dump(mode="python"))


def _corrected_material_graph(
    *,
    root: Path,
    source_path: Path,
    candidate_scene: AQV2Artifact,
    candidate_material: AQV2Artifact,
    manifest_artifacts: list[AQV2Artifact],
    recipe_artifacts: list[AQV2Artifact],
    channel_artifacts: list[AQV2Artifact],
) -> MaterialGraphSpec:
    """Retarget the whitelist-only graph to corrected exact manifest dependencies."""

    source = MaterialGraphSpec.model_validate_json(source_path.read_bytes())
    reference_path = root / "input" / "reference.png"
    inputs = [
        MaterialGraphArtifact(
            role="scene_spec",
            path=candidate_scene.path,
            sha256=candidate_scene.sha256,
        ),
        MaterialGraphArtifact(
            role="material_plan",
            path=candidate_material.path,
            sha256=candidate_material.sha256,
        ),
        *[
            MaterialGraphArtifact(role="shader_recipe", path=item.path, sha256=item.sha256)
            for item in recipe_artifacts
        ],
        *[
            MaterialGraphArtifact(role="other", path=item.path, sha256=item.sha256)
            for item in manifest_artifacts
        ],
        *[
            MaterialGraphArtifact(role="texture", path=item.path, sha256=item.sha256)
            for item in channel_artifacts
        ],
        MaterialGraphArtifact(
            role="reference",
            path="input/reference.png",
            sha256=sha256_file(reference_path),
        ),
    ]
    emission = next(
        item
        for item in channel_artifacts
        if item.artifact_id.endswith("internal_emission-emission")
    )
    base_channels = [
        channel.model_copy(
            update={
                "image": MaterialGraphArtifact(
                    role="texture",
                    path=emission.path,
                    sha256=emission.sha256,
                )
            }
        )
        if channel.channel == "emission"
        else channel
        for channel in source.base_channels
    ]
    graph = source.model_copy(
        update={
            "graph_id": "crystalgun-runtime-manifest-repair-01",
            "provenance": source.provenance.model_copy(update={"inputs": inputs}),
            "base_channels": base_channels,
            "assumptions": [
                "Emission manifest is a2/sdsr02/tex/ce/manifest.json.",
                "Only bounded emission uses immutable Codex ImageGen pixels.",
                "All other localized channels are byte-identical deterministic local maps.",
                "Runtime manifests omit mode-inapplicable null placement fields.",
                "Geometry review is required before canonical material promotion.",
                "Human review has not been performed.",
            ],
        }
    )
    return MaterialGraphSpec.model_validate(graph.model_dump(mode="python"))


def _source_artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    expected_sha256: str,
) -> AQV2Artifact:
    """Rehash and bind one immutable source artifact for the repair closure."""

    _validate_exact_hash(path, expected_sha256, kind)
    return _artifact(root, path, artifact_id=artifact_id, kind=kind)


def _copy_custom_mesh_dependency_closures(
    *,
    root: Path,
    shadow_root: Path,
    scene: SceneSpec,
) -> None:
    """Copy exact aq2 custom-mesh dependency trees without changing geometry payloads."""

    copied_roots: set[Path] = set()
    for item in scene.objects:
        geometry_value = getattr(item.geometry, "path", None)
        if not geometry_value:
            continue
        relative = Path(str(geometry_value))
        if len(relative.parts) < 2 or relative.parts[0] != "aq2":
            continue
        dependency_root = root / relative.parts[0] / relative.parts[1]
        if dependency_root in copied_roots:
            continue
        copied_roots.add(dependency_root)
        for source in deterministic_directory_files(dependency_root):
            destination = shadow_root / source.relative_to(root)
            _copy_exact(source, destination, sha256_file(source))


def _material_binding_topology_digest(payload: dict[str, Any]) -> str:
    """Digest every MeshPayload field except the authorized material-slot metadata."""

    topology_payload = {key: value for key, value in payload.items() if key != "material_slots"}
    return stable_json_digest(topology_payload)


def _author_material_binding_derivatives(
    *,
    root: Path,
    shadow_root: Path,
    repair_root: Path,
    scene: SceneSpec,
    state: Any,
) -> AQV2Artifact:
    """Author and apply two append-only material-slot derivatives in the shadow job."""

    source_artifacts: list[AQV2Artifact] = []
    derivative_artifacts: list[AQV2Artifact] = []
    binding_changes: dict[str, str] = {}
    topology_digests: dict[str, str] = {}
    for item in scene.objects:
        geometry_value = getattr(item.geometry, "path", None)
        if not geometry_value or item.material_id not in _ADDITIVE_MATERIAL_IDS:
            continue
        source_path = root / str(geometry_value)
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        slots = payload.get("material_slots")
        indices = payload.get("polygon_material_indices")
        if (
            not isinstance(slots, list)
            or len(slots) != 1
            or slots[0].get("slot_index") != 0
            or not isinstance(indices, list)
            or set(indices) != {0}
        ):
            raise ValueError(f"material binding derivative is not single-slot: {item.id}")
        source_material = slots[0].get("material_id")
        if source_material == item.material_id:
            continue
        expected_source = {
            "prop.crystalgun.frame.trim": "mat.metal.trim",
            "prop.crystalgun.rear.crown": "mat.crystal.translucent",
        }.get(item.id)
        if source_material != expected_source:
            raise ValueError(f"material binding derivative source changed: {item.id}")
        topology_digest = _material_binding_topology_digest(payload)
        derivative = dict(payload)
        derivative["material_slots"] = [{"slot_index": 0, "material_id": item.material_id}]
        if _material_binding_topology_digest(derivative) != topology_digest:
            raise RuntimeError(f"material binding derivative changed topology: {item.id}")
        suffix = "frame-trim" if item.id.endswith("frame.trim") else "rear-crown"
        derivative_path = root / "a2" / "sdsr02" / "gb" / suffix / "m.json"
        _write_json_object(derivative_path, derivative)
        source_artifacts.append(
            _artifact(
                root,
                source_path,
                artifact_id=f"binding-source-{suffix}",
                kind="source_mesh_payload",
            )
        )
        derivative_artifacts.append(
            _artifact(
                root,
                derivative_path,
                artifact_id=f"binding-derivative-{suffix}",
                kind="material_binding_mesh_payload",
            )
        )
        binding_changes[item.id] = f"{source_material}->{item.material_id}"
        topology_digests[item.id] = topology_digest
        shadow_payload_path = shadow_root / str(geometry_value)
        observed_shadow_sha256 = sha256_file(shadow_payload_path)
        allowed_shadow_hashes = {sha256_file(source_path), sha256_file(derivative_path)}
        if observed_shadow_sha256 not in allowed_shadow_hashes:
            raise FileExistsError(f"shadow MeshPayload differs: {item.id}")
        derivative_bytes = derivative_path.read_bytes()
        if observed_shadow_sha256 != sha256_file(derivative_path):
            with open(native_io_path(shadow_payload_path), "wb") as handle:
                handle.write(derivative_bytes)
    if set(binding_changes) != {
        "prop.crystalgun.frame.trim",
        "prop.crystalgun.rear.crown",
    }:
        raise ValueError("material binding derivative set changed")
    provenance = [*source_artifacts, *derivative_artifacts]
    receipt = MaterialBindingDerivativeReceipt(
        contract_id="material-binding-derivative-runtime-manifest-repair-01",
        job_id=scene.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
        input_sha256=stable_json_digest({item.path: item.sha256 for item in provenance}),
        source_fingerprint=stable_json_digest(
            {item.path: item.sha256 for item in source_artifacts}
        ),
        producer=_PRODUCER,
        provenance=provenance,
        created_at=datetime.now(UTC),
        derivative_id="material-binding-derivative-runtime-manifest-repair-01",
        source_payloads=source_artifacts,
        derivative_payloads=derivative_artifacts,
        binding_changes=binding_changes,
        topology_payload_sha256=topology_digests,
    )
    return _write_or_adopt_v2_model(
        root=root,
        path=repair_root / "material_binding_derivative_receipt.json",
        model=receipt,
        kind="material_binding_derivative_receipt",
    )


def execute_surface_detail_runtime_manifest_repair(
    job_id: str,
    session_id: str,
    *,
    repair_plan_path: Path,
    repair_plan_sha256: str,
    exact_approval: str,
    allow_disabled_experimental: bool = False,
) -> dict[str, Any]:
    """Repair manifests, execute one controller, validate Blender, and stop for review."""

    root = job_dir(job_id).expanduser().resolve()
    session_root = root / "production" / "autonomy_v2" / session_id
    plan_path = repair_plan_path.expanduser().resolve()
    if not plan_path.is_relative_to(root):
        raise ValueError("runtime manifest repair plan escaped the job root")
    _validate_exact_hash(plan_path, repair_plan_sha256, "runtime manifest repair plan")
    if repair_plan_sha256 != _PLAN_SHA256:
        raise ValueError("runtime manifest repair plan hash is not approved")
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan_payload, dict):
        raise ValueError("runtime manifest repair plan is not an object")
    _validate_plan(plan_payload, job_id=job_id, session_id=session_id)
    if exact_approval != _expected_approval(plan_payload, repair_plan_sha256):
        raise PermissionError("runtime manifest repair approval is not exact")
    _profile, budget, state, state_artifact = _validate_profile_opt_in(
        root,
        session_root,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    if state_artifact.sha256 != _SOURCE_STATE_SHA256:
        raise ValueError("runtime manifest repair source AQ state is stale")
    _validate_exact_hash(root / "input" / "reference.png", _REFERENCE_SHA256, "reference")
    repair_root = session_root / "surface_detail_runtime_manifest_repairs" / _PLAN_ID
    approval_path = repair_root / "approval.txt"
    preparation_path = repair_root / "preparation_receipt.json"
    geometry_review_path = repair_root / "geometry_review_receipt.json"
    review_plan_path = repair_root / "geometry_review_plan.json"
    if review_plan_path.exists():
        review_plan = SurfaceDetailSpatialGeometryReviewPlan.model_validate_json(
            review_plan_path.read_bytes()
        )
        review_plan_artifact = _artifact(
            root,
            review_plan_path,
            artifact_id=review_plan.plan_id,
            kind="surface_detail_geometry_review_plan",
        )
        receipt_artifact = _artifact(
            root,
            geometry_review_path,
            artifact_id=f"geometry-review-{_PLAN_ID}",
            kind="surface_detail_geometry_review_receipt",
        )
        return {
            "outcome": "awaiting_geometry_review_approval",
            "review_plan": review_plan.model_dump(mode="json"),
            "review_plan_artifact": review_plan_artifact.model_dump(mode="json"),
            "geometry_review_receipt_artifact": receipt_artifact.model_dump(mode="json"),
            "exact_approval": expected_surface_detail_geometry_review_approval(
                review_plan,
                review_plan_artifact.sha256,
            ),
        }
    if geometry_review_path.exists():
        geometry_receipt = SurfaceDetailSpatialGeometryReviewReceipt.model_validate_json(
            geometry_review_path.read_bytes()
        )
        for item in geometry_receipt.provenance:
            _validate_exact_hash(root / item.path, item.sha256, item.kind)
        geometry_receipt_artifact = _artifact(
            root,
            geometry_review_path,
            artifact_id=geometry_receipt.contract_id,
            kind="surface_detail_geometry_review_receipt",
        )
        derivative = geometry_receipt.material_binding_derivative
        review_plan = SurfaceDetailSpatialGeometryReviewPlan(
            plan_id=f"geometry-review-plan-{_PLAN_ID}",
            job_id=job_id,
            source_session_id=session_id,
            source_aq_state_sha256=state_artifact.sha256,
            recovery_plan_sha256=repair_plan_sha256,
            recovery_preparation_sha256=geometry_receipt.preparation.sha256,
            controller_result_sha256=geometry_receipt.controller_result.sha256,
            candidate_scene_spec_v02_sha256=geometry_receipt.candidate_scene_spec.sha256,
            candidate_modeling_plan_sha256=geometry_receipt.candidate_modeling_plan.sha256,
            candidate_material_plan_sha256=geometry_receipt.candidate_material_plan.sha256,
            candidate_material_graph_sha256=geometry_receipt.candidate_material_graph.sha256,
            candidate_blend_sha256=geometry_receipt.candidate_blend.sha256,
            candidate_inventory_sha256=geometry_receipt.candidate_inventory.sha256,
            candidate_validation_sha256=geometry_receipt.candidate_validation.sha256,
            topology_comparison_sha256=geometry_receipt.topology_comparison.sha256,
            surface_detail_validation_sha256=geometry_receipt.surface_detail_validation.sha256,
            preview_sha256=geometry_receipt.preview.sha256,
            geometry_review_receipt_sha256=geometry_receipt_artifact.sha256,
            material_binding_derivative_sha256=(
                derivative.sha256 if derivative is not None else None
            ),
            additive_material_ids=list(_ADDITIVE_MATERIAL_IDS),
            material_assignment_specializations=_ASSIGNMENT_SPECIALIZATIONS,
        )
        _write_model(review_plan_path, review_plan)
        review_plan_artifact = _artifact(
            root,
            review_plan_path,
            artifact_id=review_plan.plan_id,
            kind="surface_detail_geometry_review_plan",
        )
        usage = _usage_after_controller(
            state.budget_usage,
            budget,
            controller_increment=2,
            blender_build_increment=1,
            action_increment=3,
        )
        return {
            "outcome": "awaiting_geometry_review_approval",
            "review_plan": review_plan.model_dump(mode="json"),
            "review_plan_artifact": review_plan_artifact.model_dump(mode="json"),
            "geometry_review_receipt": geometry_receipt.model_dump(mode="json"),
            "geometry_review_receipt_artifact": geometry_receipt_artifact.model_dump(mode="json"),
            "effective_budget_usage": usage.model_dump(mode="json"),
            "exact_approval": expected_surface_detail_geometry_review_approval(
                review_plan,
                review_plan_artifact.sha256,
            ),
        }

    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-surface-detail-runtime-manifest-repair",
        ttl_seconds=3600,
    ):
        os.makedirs(native_io_path(repair_root), exist_ok=True)
        if approval_path.exists():
            if approval_path.read_text(encoding="utf-8") != exact_approval:
                raise FileExistsError("runtime manifest repair approval differs")
        else:
            approval_path.write_text(exact_approval, encoding="utf-8")
        approval_artifact = _artifact(
            root,
            approval_path,
            artifact_id=f"approval-{_PLAN_ID}",
            kind="surface_detail_runtime_manifest_repair_approval",
        )
        source_failure = _source_artifact(
            root,
            root / "reports" / "material_surface_detail_spatial_recovery_failure_01.json",
            artifact_id="surface-detail-spatial-recovery-failure-01",
            kind="source_failure_receipt",
            expected_sha256=_SOURCE_FAILURE_SHA256,
        )
        source_request_path = (
            session_root
            / "controller_executions"
            / "exec-0008-material-surface-detail-spatial-recovery"
            / "request.json"
        )
        source_request = _source_artifact(
            root,
            source_request_path,
            artifact_id="request-exec-0008-material-surface-detail-spatial-recovery",
            kind="source_controller_request",
            expected_sha256=_SOURCE_REQUEST_SHA256,
        )
        source_result = _source_artifact(
            root,
            source_request_path.parent / "result.json",
            artifact_id="result-exec-0008-material-surface-detail-spatial-recovery",
            kind="source_controller_result",
            expected_sha256=_SOURCE_RESULT_SHA256,
        )
        source_material_path = (
            session_root
            / "controller_outputs"
            / "material_surface_detail_spatial_recovery_01"
            / "material_plan.json"
        )
        source_material = _source_artifact(
            root,
            source_material_path,
            artifact_id="source-runtime-failed-material-plan",
            kind="source_material_plan",
            expected_sha256=_SOURCE_MATERIAL_SHA256,
        )
        source_graph_path = source_material_path.with_name("material_graph.json")
        source_graph = _source_artifact(
            root,
            source_graph_path,
            artifact_id="source-runtime-failed-material-graph",
            kind="source_material_graph",
            expected_sha256=_SOURCE_GRAPH_SHA256,
        )
        failed_preflight = _source_artifact(
            root,
            root / "a2" / "sdsr01" / "val" / "surface_preflight.json",
            artifact_id="source-runtime-failed-preflight",
            kind="source_surface_detail_preflight",
            expected_sha256=_FAILED_PREFLIGHT_SHA256,
        )
        source_scene_path = (
            session_root
            / "surface_detail_spatial_recoveries"
            / "item-crystalgun-material-surface-detail-spatial-recovery-01"
            / "candidate"
            / "scene_spec_v02.json"
        )
        source_modeling_path = source_scene_path.with_name("modeling_plan.json")
        candidate_scene_artifact = _artifact(
            root,
            source_scene_path,
            artifact_id="runtime-repair-scene-spec",
            kind="candidate_scene_spec_v02",
        )
        candidate_modeling_artifact = _artifact(
            root,
            source_modeling_path,
            artifact_id="runtime-repair-modeling-plan",
            kind="candidate_modeling_plan",
        )
        candidate_scene = SceneSpec.model_validate_json(source_scene_path.read_bytes())
        manifests, manifest_artifacts, channel_artifacts = _author_corrected_texture_assets(root)
        recipe_artifacts = _author_corrected_shader_recipes(root, manifests)
        technical_root = root / "a2" / "sdsr02"
        candidate_material_path = technical_root / "candidate" / "material_plan.json"
        candidate_material = _corrected_material_plan(root, source_material_path)
        _write_model(candidate_material_path, candidate_material)
        candidate_material_artifact = _artifact(
            root,
            candidate_material_path,
            artifact_id="runtime-repair-material-plan",
            kind="candidate_material_plan",
        )
        candidate_graph_path = technical_root / "candidate" / "material_graph.json"
        candidate_graph = _corrected_material_graph(
            root=root,
            source_path=source_graph_path,
            candidate_scene=candidate_scene_artifact,
            candidate_material=candidate_material_artifact,
            manifest_artifacts=manifest_artifacts,
            recipe_artifacts=recipe_artifacts,
            channel_artifacts=channel_artifacts,
        )
        _write_model(candidate_graph_path, candidate_graph)
        candidate_graph_artifact = _artifact(
            root,
            candidate_graph_path,
            artifact_id="runtime-repair-material-graph",
            kind="candidate_material_graph",
        )
        repair_plan_artifact = _artifact(
            root,
            plan_path,
            artifact_id=_PLAN_ID,
            kind="runtime_manifest_repair_plan",
        )
        imagegen_source_path = (
            session_root
            / "codex_imagegen"
            / "native_normalizations"
            / "crystal-emission-core-pass-through-repair-00"
            / "normalized.png"
        )
        imagegen_source = _artifact(
            root,
            imagegen_source_path,
            artifact_id="runtime-repair-imagegen-source",
            kind="imagegen_normalized_source",
        )
        imagegen_review_path = (
            session_root
            / "codex_imagegen"
            / "assignments"
            / "material-00"
            / "evidence"
            / "semantic-review-00.json"
        )
        imagegen_review = _artifact(
            root,
            imagegen_review_path,
            artifact_id="runtime-repair-imagegen-review",
            kind="imagegen_semantic_review",
        )
        preparation_items = [
            repair_plan_artifact,
            approval_artifact,
            state_artifact,
            source_failure,
            source_request,
            source_result,
            source_material,
            source_graph,
            failed_preflight,
            candidate_scene_artifact,
            candidate_modeling_artifact,
            candidate_material_artifact,
            candidate_graph_artifact,
            *manifest_artifacts,
            *recipe_artifacts,
            *channel_artifacts,
            imagegen_source,
            imagegen_review,
        ]
        preparation = SurfaceDetailRuntimeManifestRepairPreparation(
            contract_id=f"preparation-{_PLAN_ID}",
            job_id=job_id,
            workflow_id=state.workflow_id,
            dispatch_id=state.dispatch_id,
            session_id=session_id,
            input_sha256=stable_json_digest({item.path: item.sha256 for item in preparation_items}),
            source_fingerprint=source_failure.sha256,
            producer=_PRODUCER,
            provenance=preparation_items,
            created_at=datetime.now(UTC),
            repair_id=_PLAN_ID,
            repair_plan=repair_plan_artifact,
            approval=approval_artifact,
            source_aq_state=state_artifact,
            source_failure_receipt=source_failure,
            source_controller_request=source_request,
            source_controller_result=source_result,
            source_material_plan=source_material,
            source_material_graph=source_graph,
            failed_preflight=failed_preflight,
            source_scene_spec=candidate_scene_artifact,
            source_modeling_plan=candidate_modeling_artifact,
            candidate_material_plan=candidate_material_artifact,
            candidate_material_graph=candidate_graph_artifact,
            texture_manifests=manifest_artifacts,
            shader_recipes=recipe_artifacts,
            texture_channels=channel_artifacts,
            imagegen_source=imagegen_source,
            imagegen_semantic_review=imagegen_review,
        )
        preparation_artifact = _write_or_adopt_v2_model(
            root=root,
            path=preparation_path,
            model=preparation,
            kind="runtime_manifest_repair_preparation",
        )
        dependency_artifacts = [
            *manifest_artifacts,
            *recipe_artifacts,
            *channel_artifacts,
            imagegen_source,
            imagegen_review,
            source_failure,
            source_result,
            failed_preflight,
        ]
        (
            _result,
            request_artifact,
            result_artifact,
            profile_artifact,
            assignment_artifact,
            completion_artifact,
            controller_plan_artifact,
            controller_graph_artifact,
            usage,
        ) = _execute_controller(
            root=root,
            session_root=session_root,
            recovery_id=_PLAN_ID,
            preparation_artifact=preparation_artifact,
            state=state,
            state_artifact=state_artifact,
            budget=budget,
            candidate_scene_artifact=candidate_scene_artifact,
            candidate_modeling_artifact=candidate_modeling_artifact,
            candidate_material_artifact=candidate_material_artifact,
            candidate_graph_artifact=candidate_graph_artifact,
            dependency_artifacts=dependency_artifacts,
            plan_artifact=repair_plan_artifact,
            execution_id="exec-0009-material-surface-detail-runtime-manifest-repair",
            output_leaf="material_surface_detail_runtime_manifest_repair_01",
            controller_increment=2,
            blender_build_increment=1,
            action_increment=3,
            controller_staging_root=technical_root,
        )
        del _result
        shadow_root = root / "a2w" / "r3"
        shadow_scene, shadow_modeling, shadow_material = _prepare_shadow_job(
            root=root,
            shadow_root=shadow_root,
            candidate_scene_path=source_scene_path,
            candidate_modeling_path=source_modeling_path,
            candidate_material_plan_path=root / controller_plan_artifact.path,
        )
        _copy_custom_mesh_dependency_closures(
            root=root,
            shadow_root=shadow_root,
            scene=shadow_scene,
        )
        binding_derivative_artifact = _author_material_binding_derivatives(
            root=root,
            shadow_root=shadow_root,
            repair_root=repair_root,
            scene=shadow_scene,
            state=state,
        )
        source_inventory_path = (
            session_root / "material_phase" / "0007" / "rollback" / "scene_inventory.json"
        )
        preflight = validate_surface_detail_contract(
            shadow_modeling,
            shadow_scene,
            shadow_root,
            material_plan=shadow_material,
            require_materials=True,
            inventory_path=source_inventory_path,
        )
        validation_root = technical_root / "val"
        preflight_path = validation_root / "surface_preflight.json"
        _write_model(preflight_path, preflight)
        if not preflight.ok:
            failures = [item.message for item in preflight.checks if item.status == "failed"]
            raise ValueError("runtime manifest repair preflight failed: " + "; ".join(failures))
        provenance = collect_build_provenance(
            shadow_root,
            job_id,
            scene_spec_path=shadow_root / "analysis" / "scene_spec.json",
            validate_contracts=True,
            surface_detail_inventory_path=source_inventory_path,
        )
        build_root = shadow_root / "build"
        blend_path = build_root / "scene.blend"
        inventory_path = build_root / "scene_inventory.json"
        validation_path = build_root / "validation.json"
        preview_path = build_root / "preview.png"
        provenance_path = build_root / "provenance.json"
        run_blender(
            "build_scene.py",
            [
                "--spec",
                str(shadow_root / "analysis" / "scene_spec.json"),
                "--job-root",
                str(shadow_root),
                "--output",
                str(blend_path),
                "--render-engine",
                "eevee",
                "--render-device",
                "auto",
            ],
            factory_startup=True,
            disable_autoexec=True,
        )
        run_blender(
            "inspect_scene.py",
            ["--output", str(inventory_path)],
            blend_file=blend_path,
            disable_autoexec=True,
        )
        run_blender(
            "validate_scene.py",
            [
                "--spec",
                str(shadow_root / "analysis" / "scene_spec.json"),
                "--job-root",
                str(shadow_root),
                "--output",
                str(validation_path),
            ],
            blend_file=blend_path,
            disable_autoexec=True,
        )
        run_blender(
            "render_preview.py",
            [
                "--output",
                str(preview_path),
                "--render-engine",
                "eevee",
                "--render-device",
                "auto",
            ],
            blend_file=blend_path,
            disable_autoexec=True,
        )
        _write_json_object(provenance_path, provenance)
        validation_payload = json.loads(validation_path.read_text(encoding="utf-8"))
        inventory_payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        if validation_payload.get("ok") is not True:
            raise RuntimeError("runtime manifest repair Blender validation failed")
        if inventory_payload.get("blender_version") != "5.0.1":
            raise RuntimeError("runtime manifest repair requires actual Blender 5.0.1")
        final_surface = validate_surface_detail_contract(
            shadow_modeling,
            shadow_scene,
            shadow_root,
            material_plan=shadow_material,
            require_materials=True,
            inventory_path=inventory_path,
        )
        surface_path = validation_root / "surface.json"
        _write_model(surface_path, final_surface)
        if not final_surface.ok:
            failures = [item.message for item in final_surface.checks if item.status == "failed"]
            raise ValueError("runtime manifest candidate validation failed: " + "; ".join(failures))
        candidate_provenance = collect_build_provenance(
            shadow_root,
            job_id,
            scene_spec_path=shadow_root / "analysis" / "scene_spec.json",
            validate_contracts=True,
            surface_detail_inventory_path=inventory_path,
        )
        if candidate_provenance != provenance:
            raise RuntimeError("candidate inventory changed runtime repair build provenance")
        canonical_scene = SceneSpec.model_validate_json(
            (root / "analysis" / "scene_spec.json").read_bytes()
        )
        topology = _topology_comparison(
            source_scene=canonical_scene,
            candidate_scene=candidate_scene,
            source_inventory_path=source_inventory_path,
            candidate_inventory_path=inventory_path,
        )
        topology_path = validation_root / "topology.json"
        _write_json_object(topology_path, topology)
        if topology["topology_unchanged"] is not True:
            raise RuntimeError("runtime manifest repair changed geometry topology")
        review_artifacts = [
            preparation_artifact,
            profile_artifact,
            assignment_artifact,
            request_artifact,
            result_artifact,
            completion_artifact,
            candidate_scene_artifact,
            candidate_modeling_artifact,
            controller_plan_artifact,
            controller_graph_artifact,
            _artifact(root, blend_path, artifact_id="runtime-repair-blend", kind="candidate_blend"),
            _artifact(
                root,
                inventory_path,
                artifact_id="runtime-repair-inventory",
                kind="candidate_inventory",
            ),
            _artifact(
                root,
                validation_path,
                artifact_id="runtime-repair-validation",
                kind="candidate_validation",
            ),
            _artifact(
                root,
                provenance_path,
                artifact_id="runtime-repair-provenance",
                kind="candidate_build_provenance",
            ),
            _artifact(
                root,
                surface_path,
                artifact_id="runtime-repair-surface",
                kind="surface_detail_validation",
            ),
            _artifact(
                root,
                topology_path,
                artifact_id="runtime-repair-topology",
                kind="topology_comparison",
            ),
            _artifact(
                root,
                preview_path,
                artifact_id="runtime-repair-preview",
                kind="candidate_preview",
            ),
            binding_derivative_artifact,
        ]
        by_kind = {item.kind: item for item in review_artifacts}
        geometry_receipt = SurfaceDetailSpatialGeometryReviewReceipt(
            contract_id=f"geometry-review-{_PLAN_ID}",
            job_id=job_id,
            workflow_id=state.workflow_id,
            dispatch_id=state.dispatch_id,
            session_id=session_id,
            input_sha256=stable_json_digest({item.path: item.sha256 for item in review_artifacts}),
            source_fingerprint=result_artifact.sha256,
            producer=_PRODUCER,
            provenance=review_artifacts,
            created_at=datetime.now(UTC),
            recovery_id=_PLAN_ID,
            preparation=preparation_artifact,
            controller_profile=profile_artifact,
            controller_assignment=assignment_artifact,
            controller_request=request_artifact,
            controller_result=result_artifact,
            controller_completion=completion_artifact,
            candidate_scene_spec=candidate_scene_artifact,
            candidate_modeling_plan=candidate_modeling_artifact,
            candidate_material_plan=controller_plan_artifact,
            candidate_material_graph=controller_graph_artifact,
            candidate_blend=by_kind["candidate_blend"],
            candidate_inventory=by_kind["candidate_inventory"],
            candidate_validation=by_kind["candidate_validation"],
            candidate_build_provenance=by_kind["candidate_build_provenance"],
            surface_detail_validation=by_kind["surface_detail_validation"],
            topology_comparison=by_kind["topology_comparison"],
            preview=by_kind["candidate_preview"],
            material_binding_derivative=by_kind["material_binding_derivative_receipt"],
            blender_version="5.0.1",
        )
        geometry_receipt_artifact = _write_or_adopt_v2_model(
            root=root,
            path=geometry_review_path,
            model=geometry_receipt,
            kind="surface_detail_geometry_review_receipt",
        )
        review_plan = SurfaceDetailSpatialGeometryReviewPlan(
            plan_id=f"geometry-review-plan-{_PLAN_ID}",
            job_id=job_id,
            source_session_id=session_id,
            source_aq_state_sha256=state_artifact.sha256,
            recovery_plan_sha256=repair_plan_sha256,
            recovery_preparation_sha256=preparation_artifact.sha256,
            controller_result_sha256=result_artifact.sha256,
            candidate_scene_spec_v02_sha256=candidate_scene_artifact.sha256,
            candidate_modeling_plan_sha256=candidate_modeling_artifact.sha256,
            candidate_material_plan_sha256=controller_plan_artifact.sha256,
            candidate_material_graph_sha256=controller_graph_artifact.sha256,
            candidate_blend_sha256=by_kind["candidate_blend"].sha256,
            candidate_inventory_sha256=by_kind["candidate_inventory"].sha256,
            candidate_validation_sha256=by_kind["candidate_validation"].sha256,
            topology_comparison_sha256=by_kind["topology_comparison"].sha256,
            surface_detail_validation_sha256=by_kind["surface_detail_validation"].sha256,
            preview_sha256=by_kind["candidate_preview"].sha256,
            geometry_review_receipt_sha256=geometry_receipt_artifact.sha256,
            material_binding_derivative_sha256=by_kind[
                "material_binding_derivative_receipt"
            ].sha256,
            additive_material_ids=list(_ADDITIVE_MATERIAL_IDS),
            material_assignment_specializations=_ASSIGNMENT_SPECIALIZATIONS,
        )
        _write_model(review_plan_path, review_plan)
        review_plan_artifact = _artifact(
            root,
            review_plan_path,
            artifact_id=review_plan.plan_id,
            kind="surface_detail_geometry_review_plan",
        )
    return {
        "outcome": "awaiting_geometry_review_approval",
        "review_plan": review_plan.model_dump(mode="json"),
        "review_plan_artifact": review_plan_artifact.model_dump(mode="json"),
        "geometry_review_receipt": geometry_receipt.model_dump(mode="json"),
        "geometry_review_receipt_artifact": geometry_receipt_artifact.model_dump(mode="json"),
        "effective_budget_usage": usage.model_dump(mode="json"),
        "exact_approval": expected_surface_detail_geometry_review_approval(
            review_plan,
            review_plan_artifact.sha256,
        ),
    }


def expected_surface_detail_material_promotion_approval(
    plan: SurfaceDetailMaterialPromotionPlan,
    plan_sha256: str,
) -> str:
    """Render the sole exact approval that may start reviewed material promotion."""

    return (
        "APPROVE MATERIAL SPATIAL RECOVERY PROMOTION "
        f"job_id={plan.job_id} source_session_id={plan.source_session_id} "
        f"source_aq_state_sha256={plan.source_aq_state_sha256} "
        f"source_geometry_review_plan_sha256={plan.source_geometry_review_plan_sha256} "
        "geometry_review_approval_receipt_sha256="
        f"{plan.geometry_review_approval_receipt_sha256} "
        f"material_promotion_plan_sha256={plan_sha256} "
        f"reference_sha256={plan.reference_sha256} "
        f"candidate_scene_spec_v02_sha256={plan.candidate_scene_spec_v02_sha256} "
        f"candidate_modeling_plan_sha256={plan.candidate_modeling_plan_sha256} "
        f"candidate_material_plan_sha256={plan.candidate_material_plan_sha256} "
        f"candidate_material_graph_sha256={plan.candidate_material_graph_sha256} "
        f"candidate_blend_sha256={plan.candidate_blend_sha256} "
        f"material_binding_derivative_sha256={plan.material_binding_derivative_sha256} "
        f"controller_profile_sha256={plan.controller_profile_sha256} "
        f"controller_request_sha256={plan.controller_request_sha256} "
        f"controller_result_sha256={plan.controller_result_sha256} "
        f"controller_completion_sha256={plan.controller_completion_sha256} "
        "add_material_ids=mat.metal.trim.filigree_body,"
        "mat.crystal.translucent.facet_crown "
        "assignments=prop.crystalgun.frame.trim->mat.metal.trim.filigree_body,"
        "prop.crystalgun.rear.crown->mat.crystal.translucent.facet_crown "
        "reuse_controller_result=true new_controller_invocation_allowed=false "
        "controller_result_source_binding_preflight_required=true "
        "canonical_scene_and_modeling_binding_update_allowed=true "
        "canonical_geometry_payload_overwrite_allowed=false "
        "canonical_promotion_limit=1 host_material_promotion_service_required=true "
        "material_phase_receipt_v2_required=true blender_version=5.0.1 "
        "neutral_preview_required=true aq_iq_resume_after_promotion=true "
        "scope=host_material_promotion_only delivery_disabled=true "
        "optimization_disabled=true lod_disabled=true collider_disabled=true "
        "destination_write_disabled=true"
    )


def expected_material_completion_binding_repair_approval(
    payload: dict[str, Any],
    plan_sha256: str,
) -> str:
    """Render the sole exact approval accepted for completion-map repair."""

    return (
        "APPROVE MATERIAL CONTROLLER COMPLETION BINDING REPAIR "
        f"job_id={payload['job_id']} "
        f"source_session_id={payload['source_session_id']} "
        f"source_aq_state_sha256={payload['source_aq_state_sha256']} "
        "source_material_promotion_plan_sha256="
        f"{payload['source_material_promotion_plan_sha256']} "
        "failed_promotion_rollback_receipt_sha256="
        f"{payload['failed_promotion_rollback_receipt_sha256']} "
        f"failed_controller_request_sha256={payload['failed_controller_request_sha256']} "
        f"failed_controller_result_sha256={payload['failed_controller_result_sha256']} "
        "failed_controller_completion_sha256="
        f"{payload['failed_controller_completion_sha256']} "
        "request_immutable_input_map_sha256="
        f"{payload['request_immutable_input_map_sha256']} "
        "completion_immutable_input_map_sha256="
        f"{payload['completion_immutable_input_map_sha256']} "
        f"repair_plan_sha256={plan_sha256} "
        f"reference_sha256={payload['reference_sha256']} "
        f"candidate_scene_spec_v02_sha256={payload['candidate_scene_spec_v02_sha256']} "
        f"candidate_modeling_plan_sha256={payload['candidate_modeling_plan_sha256']} "
        f"candidate_material_plan_sha256={payload['candidate_material_plan_sha256']} "
        f"candidate_material_graph_sha256={payload['candidate_material_graph_sha256']} "
        f"candidate_blend_sha256={payload['candidate_blend_sha256']} "
        "material_binding_derivative_sha256="
        f"{payload['material_binding_derivative_sha256']} "
        "new_controller_invocation_allowed=true controller_invocation_limit=1 "
        "execution_id=exec-0010-material-completion-binding-repair "
        "output_root=production/autonomy_v2/"
        f"{payload['source_session_id']}/controller_outputs/"
        "material_completion_binding_repair_01 "
        "controller_completion_binding=full_controller_request_input_map "
        "preserve_failed_controller_lifecycle=true "
        "canonical_scene_adoption_before_controller_request=true "
        "canonical_scene_rollback_on_failure=true "
        "canonical_geometry_payload_overwrite=false "
        "preserve_geometry_topology=true preserve_semantic_ids=true "
        "preserve_material_ids=true preserve_imagegen_evidence=true "
        "new_imagegen_invocation_allowed=false new_blender_build_limit=1 "
        "canonical_promotion_limit=1 material_phase_receipt_v2_required=true "
        "neutral_preview_required=true aq_iq_resume_after_promotion=true "
        "scope=append_only_controller_completion_full_request_binding_repair_only "
        "delivery_disabled=true optimization_disabled=true lod_disabled=true "
        "collider_disabled=true destination_write_disabled=true"
    )


def _validate_completion_binding_repair_plan(
    payload: dict[str, Any],
    *,
    job_id: str,
    session_id: str,
) -> None:
    """Fail closed unless the plan retains the exact approved one-shot scope."""

    if (
        payload.get("schema_version") != "0.1.0"
        or payload.get("plan_id") != "item-crystalgun-material-completion-binding-repair-01"
        or payload.get("status") != "awaiting_user_approval"
        or payload.get("approval_granted") is not False
        or payload.get("job_id") != job_id
        or payload.get("source_session_id") != session_id
        or payload.get("scope")
        != "append_only_controller_completion_full_request_binding_repair_only"
    ):
        raise ValueError("completion binding repair plan identity or scope changed")
    approved = payload.get("approved_changes_if_authorized")
    lifecycle = payload.get("required_lifecycle")
    if approved != {
        "preserve_failed_controller_lifecycle": True,
        "new_execution_id": "exec-0010-material-completion-binding-repair",
        "new_output_root": (
            f"production/autonomy_v2/{session_id}/controller_outputs/"
            "material_completion_binding_repair_01"
        ),
        "copy_candidate_material_plan_byte_identically": True,
        "copy_candidate_material_graph_byte_identically": True,
        "completion_immutable_input_sha256": "full_controller_request_input_map",
        "canonical_scene_adoption_before_controller_request": True,
        "canonical_scene_rollback_on_failure": True,
        "canonical_geometry_payload_overwrite": False,
    }:
        raise ValueError("completion binding approved changes changed")
    if lifecycle != {
        "new_controller_invocation_allowed": True,
        "controller_invocation_limit": 1,
        "controller_executor_required": True,
        "new_imagegen_invocation_allowed": False,
        "new_blender_build_limit": 1,
        "canonical_promotion_limit": 1,
        "material_phase_receipt_v2_required": True,
        "neutral_preview_required": True,
        "aq_iq_resume_after_promotion": True,
    }:
        raise ValueError("completion binding repair lifecycle changed")
    for key in (
        "preserve_geometry_topology",
        "preserve_semantic_ids",
        "preserve_material_ids",
        "preserve_imagegen_evidence",
        "delivery_disabled",
        "optimization_disabled",
        "lod_disabled",
        "collider_disabled",
        "destination_write_disabled",
    ):
        if payload.get(key) is not True:
            raise ValueError(f"completion binding repair guard changed: {key}")
    if payload.get("human_reviewed") is not False:
        raise ValueError("completion binding repair cannot claim human review")


def accept_surface_detail_runtime_geometry_review(
    job_id: str,
    session_id: str,
    *,
    geometry_review_plan_path: Path,
    geometry_review_plan_sha256: str,
    exact_approval: str,
    allow_disabled_experimental: bool = False,
) -> dict[str, Any]:
    """Record exact geometry approval and stage a non-executing promotion plan."""

    root = job_dir(job_id).expanduser().resolve()
    session_root = root / "production" / "autonomy_v2" / session_id
    review_plan_path = geometry_review_plan_path.expanduser().resolve()
    if not review_plan_path.is_relative_to(root):
        raise ValueError("geometry review plan escaped the job root")
    _validate_exact_hash(
        review_plan_path,
        geometry_review_plan_sha256,
        "surface-detail geometry review plan",
    )
    review_plan = SurfaceDetailSpatialGeometryReviewPlan.model_validate_json(
        review_plan_path.read_bytes()
    )
    if review_plan.job_id != job_id or review_plan.source_session_id != session_id:
        raise ValueError("surface-detail geometry review identity changed")
    expected_approval = expected_surface_detail_geometry_review_approval(
        review_plan,
        geometry_review_plan_sha256,
    )
    if exact_approval != expected_approval:
        raise PermissionError("surface-detail geometry review approval is not exact")
    _profile, budget, state, state_artifact = _validate_profile_opt_in(
        root,
        session_root,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    if state_artifact.sha256 != review_plan.source_aq_state_sha256:
        raise ValueError("surface-detail geometry review source AQ state is stale")
    _validate_exact_hash(root / "input" / "reference.png", _REFERENCE_SHA256, "reference")
    repair_root = review_plan_path.parent
    geometry_receipt_path = repair_root / "geometry_review_receipt.json"
    _validate_exact_hash(
        geometry_receipt_path,
        review_plan.geometry_review_receipt_sha256,
        "surface-detail geometry review receipt",
    )
    geometry_receipt = SurfaceDetailSpatialGeometryReviewReceipt.model_validate_json(
        geometry_receipt_path.read_bytes()
    )
    for item in geometry_receipt.provenance:
        _validate_exact_hash(root / item.path, item.sha256, item.kind)
    if geometry_receipt.controller_result.sha256 != review_plan.controller_result_sha256:
        raise ValueError("geometry review ControllerResult changed")
    derivative = geometry_receipt.material_binding_derivative
    if derivative is None or derivative.sha256 != review_plan.material_binding_derivative_sha256:
        raise ValueError("geometry review material binding derivative changed")
    if review_plan.additive_material_ids != list(_ADDITIVE_MATERIAL_IDS):
        raise ValueError("geometry review additive material IDs changed")
    if review_plan.material_assignment_specializations != _ASSIGNMENT_SPECIALIZATIONS:
        raise ValueError("geometry review material assignments changed")

    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-surface-detail-runtime-geometry-review",
        ttl_seconds=600,
    ):
        approval_path = repair_root / "geometry_review_approval.txt"
        _write_exact_bytes(approval_path, exact_approval.encode("utf-8"))
        approval_artifact = _artifact(
            root,
            approval_path,
            artifact_id=f"approval-{review_plan.plan_id}",
            kind="surface_detail_geometry_review_approval",
        )
        review_plan_artifact = _artifact(
            root,
            review_plan_path,
            artifact_id=review_plan.plan_id,
            kind="surface_detail_geometry_review_plan",
        )
        geometry_receipt_artifact = _artifact(
            root,
            geometry_receipt_path,
            artifact_id=geometry_receipt.contract_id,
            kind="surface_detail_geometry_review_receipt",
        )
        reviewed_artifacts = [
            review_plan_artifact,
            geometry_receipt_artifact,
            derivative,
            approval_artifact,
            geometry_receipt.candidate_scene_spec,
            geometry_receipt.candidate_modeling_plan,
            geometry_receipt.candidate_material_plan,
            geometry_receipt.candidate_material_graph,
            geometry_receipt.candidate_blend,
            geometry_receipt.candidate_inventory,
            geometry_receipt.candidate_validation,
            geometry_receipt.topology_comparison,
            geometry_receipt.surface_detail_validation,
            geometry_receipt.preview,
        ]
        approval_receipt = SurfaceDetailGeometryReviewApprovalReceipt(
            contract_id=f"geometry-review-approval-{_PLAN_ID}",
            job_id=job_id,
            workflow_id=state.workflow_id,
            dispatch_id=state.dispatch_id,
            session_id=session_id,
            input_sha256=stable_json_digest(
                {item.path: item.sha256 for item in reviewed_artifacts}
            ),
            source_fingerprint=review_plan_artifact.sha256,
            producer=_PRODUCER,
            provenance=reviewed_artifacts,
            created_at=datetime.now(UTC),
            recovery_id=_PLAN_ID,
            review_plan=review_plan_artifact,
            geometry_review_receipt=geometry_receipt_artifact,
            material_binding_derivative=derivative,
            approval=approval_artifact,
            candidate_scene_spec=geometry_receipt.candidate_scene_spec,
            candidate_modeling_plan=geometry_receipt.candidate_modeling_plan,
            candidate_material_plan=geometry_receipt.candidate_material_plan,
            candidate_material_graph=geometry_receipt.candidate_material_graph,
            candidate_blend=geometry_receipt.candidate_blend,
            candidate_inventory=geometry_receipt.candidate_inventory,
            candidate_validation=geometry_receipt.candidate_validation,
            topology_comparison=geometry_receipt.topology_comparison,
            surface_detail_validation=geometry_receipt.surface_detail_validation,
            preview=geometry_receipt.preview,
        )
        approval_receipt_path = repair_root / "geometry_review_approval_receipt.json"
        approval_receipt_artifact = _write_or_adopt_v2_model(
            root=root,
            path=approval_receipt_path,
            model=approval_receipt,
            kind="surface_detail_geometry_review_approval_receipt",
        )
        usage = _usage_after_controller(
            state.budget_usage,
            budget,
            controller_increment=2,
            blender_build_increment=1,
            action_increment=3,
        )
        canonical_scene_path = root / "analysis" / "scene_spec.json"
        canonical_modeling_path = root / "analysis" / "modeling_plan.json"
        canonical_blend_path = root / "blender" / "scene.blend"
        for path, label in (
            (canonical_scene_path, "canonical SceneSpec"),
            (canonical_modeling_path, "canonical ModelingPlan"),
            (canonical_blend_path, "canonical Blender scene"),
        ):
            if not path.is_file():
                raise FileNotFoundError(f"{label} is missing")
        promotion_plan = SurfaceDetailMaterialPromotionPlan(
            plan_id="item-crystalgun-surface-detail-material-promotion-01",
            job_id=job_id,
            source_session_id=session_id,
            source_aq_state_sha256=state_artifact.sha256,
            source_geometry_review_plan_sha256=review_plan_artifact.sha256,
            geometry_review_approval_receipt_sha256=approval_receipt_artifact.sha256,
            source_recovery_plan_sha256=review_plan.recovery_plan_sha256,
            reference_sha256=_REFERENCE_SHA256,
            canonical_scene_spec_v02_sha256=sha256_file(canonical_scene_path),
            canonical_modeling_plan_sha256=sha256_file(canonical_modeling_path),
            canonical_blend_sha256=sha256_file(canonical_blend_path),
            candidate_scene_spec_v02_sha256=geometry_receipt.candidate_scene_spec.sha256,
            candidate_modeling_plan_sha256=geometry_receipt.candidate_modeling_plan.sha256,
            candidate_material_plan_sha256=geometry_receipt.candidate_material_plan.sha256,
            candidate_material_graph_sha256=geometry_receipt.candidate_material_graph.sha256,
            candidate_blend_sha256=geometry_receipt.candidate_blend.sha256,
            candidate_inventory_sha256=geometry_receipt.candidate_inventory.sha256,
            candidate_validation_sha256=geometry_receipt.candidate_validation.sha256,
            topology_comparison_sha256=geometry_receipt.topology_comparison.sha256,
            surface_detail_validation_sha256=geometry_receipt.surface_detail_validation.sha256,
            preview_sha256=geometry_receipt.preview.sha256,
            material_binding_derivative_sha256=derivative.sha256,
            controller_profile_sha256=geometry_receipt.controller_profile.sha256,
            controller_request_sha256=geometry_receipt.controller_request.sha256,
            controller_result_sha256=geometry_receipt.controller_result.sha256,
            controller_completion_sha256=geometry_receipt.controller_completion.sha256,
            additive_material_ids=list(_ADDITIVE_MATERIAL_IDS),
            material_assignment_specializations=_ASSIGNMENT_SPECIALIZATIONS,
            effective_budget_usage=usage,
            remaining_budget={
                "total_blender_builds": budget.total_blender_builds - usage.total_blender_builds,
                "controller_invocations": budget.controller_invocations
                - usage.controller_invocations,
                "canonical_promotions": budget.canonical_promotions - usage.canonical_promotions,
                "total_actions": budget.global_action_limit - usage.total_actions,
            },
        )
        promotion_plan_path = repair_root / "material_promotion_plan.json"
        _write_model(promotion_plan_path, promotion_plan)
        promotion_plan_artifact = _artifact(
            root,
            promotion_plan_path,
            artifact_id=promotion_plan.plan_id,
            kind="surface_detail_material_promotion_plan",
        )
    return {
        "outcome": "awaiting_material_promotion_approval",
        "geometry_review_approval_receipt": approval_receipt.model_dump(mode="json"),
        "geometry_review_approval_receipt_artifact": (
            approval_receipt_artifact.model_dump(mode="json")
        ),
        "material_promotion_plan": promotion_plan.model_dump(mode="json"),
        "material_promotion_plan_artifact": promotion_plan_artifact.model_dump(mode="json"),
        "exact_approval": expected_surface_detail_material_promotion_approval(
            promotion_plan,
            promotion_plan_artifact.sha256,
        ),
    }


def _replace_exact_file(source: Path, destination: Path, expected_sha256: str) -> None:
    """Atomically copy one exact candidate over a contained canonical destination."""

    if sha256_file(source) != expected_sha256:
        raise ValueError(f"promotion source changed: {source.name}")
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    temporary = destination.parent / f".{destination.name}.promotion.tmp"
    if os.path.exists(native_io_path(temporary)):
        raise FileExistsError(f"promotion staging file already exists: {temporary.name}")
    shutil.copy2(native_io_path(source), native_io_path(temporary))
    try:
        if sha256_file(temporary) != expected_sha256:
            raise RuntimeError("promotion staging hash mismatch")
        os.replace(native_io_path(temporary), native_io_path(destination))
    except Exception:
        if os.path.exists(native_io_path(temporary)):
            os.unlink(native_io_path(temporary))
        raise
    if sha256_file(destination) != expected_sha256:
        raise RuntimeError("promoted canonical file hash mismatch")


def _binding_manifest_payload(
    root: Path,
    derivative_receipt: MaterialBindingDerivativeReceipt,
    derivative_artifact: AQV2Artifact,
    candidate_scene: SceneSpec,
) -> dict[str, Any]:
    """Create the exact host runtime companion for two approved material-slot derivatives."""

    source_by_id = {
        "prop.crystalgun.frame.trim": derivative_receipt.source_payloads[0],
        "prop.crystalgun.rear.crown": derivative_receipt.source_payloads[1],
    }
    derivative_by_id = {
        "prop.crystalgun.frame.trim": derivative_receipt.derivative_payloads[0],
        "prop.crystalgun.rear.crown": derivative_receipt.derivative_payloads[1],
    }
    object_by_id = {item.id: item for item in candidate_scene.objects}
    bindings = []
    for object_id, material_id in _ASSIGNMENT_SPECIALIZATIONS.items():
        item = object_by_id[object_id]
        scene_payload_path = getattr(item.geometry, "path", None)
        source = source_by_id[object_id]
        derivative = derivative_by_id[object_id]
        if scene_payload_path != source.path or item.material_id != material_id:
            raise ValueError("candidate SceneSpec differs from the approved binding derivative")
        _validate_exact_hash(root / source.path, source.sha256, f"{object_id} source payload")
        _validate_exact_hash(
            root / derivative.path,
            derivative.sha256,
            f"{object_id} derivative payload",
        )
        bindings.append(
            {
                "object_id": object_id,
                "material_id": material_id,
                "scene_payload_path": scene_payload_path,
                "source_sha256": source.sha256,
                "derivative_path": derivative.path,
                "derivative_sha256": derivative.sha256,
                "topology_payload_sha256": derivative_receipt.topology_payload_sha256[object_id],
            }
        )
    return {
        "schema_version": "0.1.0",
        "status": "approved_material_binding_derivative",
        "source_receipt_path": derivative_artifact.path,
        "source_receipt_sha256": derivative_artifact.sha256,
        "bindings": bindings,
        "topology_unchanged": True,
        "semantic_ids_unchanged": True,
        "canonical_geometry_payload_overwrite": False,
        "human_reviewed": False,
    }


def _exact_artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    expected_sha256: str,
) -> AQV2Artifact:
    """Create one artifact only after its exact planned digest is revalidated."""

    _validate_exact_hash(path, expected_sha256, kind)
    return _artifact(root, path, artifact_id=artifact_id, kind=kind)


def _write_or_validate_state(
    root: Path,
    path: Path,
    state: AutonomyStateV2,
) -> AQV2Artifact:
    """Publish one immutable AQ state or adopt only the identical prior state."""

    if os.path.exists(native_io_path(path)):
        with open(native_io_path(path), "rb") as handle:
            existing = AutonomyStateV2.model_validate_json(handle.read())
        if existing != state:
            raise FileExistsError(f"existing AQ state differs: {path.name}")
        return _artifact(root, path, artifact_id=state.contract_id, kind="state")
    return write_immutable_v2_model(root, path, state).model_copy(update={"kind": "state"})


def execute_surface_detail_material_promotion(
    job_id: str,
    session_id: str,
    *,
    promotion_plan_path: Path,
    promotion_plan_sha256: str,
    exact_approval: str,
    allow_disabled_experimental: bool = False,
) -> dict[str, Any]:
    """Promote the exact reviewed material candidate and resume AQ at IQ 0.2."""

    root = job_dir(job_id).expanduser().resolve()
    session_root = root / "production" / "autonomy_v2" / session_id
    plan_path = promotion_plan_path.expanduser().resolve()
    if not plan_path.is_relative_to(root):
        raise ValueError("material promotion plan escaped the job root")
    _validate_exact_hash(plan_path, promotion_plan_sha256, "material promotion plan")
    promotion_plan = SurfaceDetailMaterialPromotionPlan.model_validate_json(plan_path.read_bytes())
    if promotion_plan.job_id != job_id or promotion_plan.source_session_id != session_id:
        raise ValueError("material promotion identity changed")
    if exact_approval != expected_surface_detail_material_promotion_approval(
        promotion_plan,
        promotion_plan_sha256,
    ):
        raise PermissionError("material promotion approval is not exact")
    _profile, budget, state, state_artifact = _validate_profile_opt_in(
        root,
        session_root,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    if state_artifact.sha256 != promotion_plan.source_aq_state_sha256:
        raise ValueError("material promotion source AQ state is stale")
    _validate_exact_hash(root / "input" / "reference.png", _REFERENCE_SHA256, "reference")
    if promotion_plan.reference_sha256 != _REFERENCE_SHA256:
        raise ValueError("material promotion reference hash changed")
    repair_root = plan_path.parent
    geometry_approval_path = repair_root / "geometry_review_approval_receipt.json"
    geometry_approval_artifact = _exact_artifact(
        root,
        geometry_approval_path,
        artifact_id=f"geometry-review-approval-{_PLAN_ID}",
        kind="surface_detail_geometry_review_approval_receipt",
        expected_sha256=promotion_plan.geometry_review_approval_receipt_sha256,
    )
    with open(native_io_path(geometry_approval_path), "rb") as handle:
        geometry_approval = SurfaceDetailGeometryReviewApprovalReceipt.model_validate_json(
            handle.read()
        )
    derivative_artifact = geometry_approval.material_binding_derivative
    if derivative_artifact.sha256 != promotion_plan.material_binding_derivative_sha256:
        raise ValueError("material binding derivative changed")
    derivative_path = root / derivative_artifact.path
    derivative_receipt = MaterialBindingDerivativeReceipt.model_validate_json(
        open(native_io_path(derivative_path), "rb").read()
    )
    candidate_scene_artifact = geometry_approval.candidate_scene_spec
    candidate_modeling_artifact = geometry_approval.candidate_modeling_plan
    candidate_material_artifact = geometry_approval.candidate_material_plan
    candidate_graph_artifact = geometry_approval.candidate_material_graph
    candidate_blend_artifact = geometry_approval.candidate_blend
    for artifact, expected in (
        (candidate_scene_artifact, promotion_plan.candidate_scene_spec_v02_sha256),
        (candidate_modeling_artifact, promotion_plan.candidate_modeling_plan_sha256),
        (candidate_material_artifact, promotion_plan.candidate_material_plan_sha256),
        (candidate_graph_artifact, promotion_plan.candidate_material_graph_sha256),
        (candidate_blend_artifact, promotion_plan.candidate_blend_sha256),
    ):
        if artifact.sha256 != expected:
            raise ValueError(f"planned candidate hash changed: {artifact.kind}")
        validate_v2_artifact(root, artifact)
    candidate_scene = SceneSpec.model_validate_json(
        open(native_io_path(root / candidate_scene_artifact.path), "rb").read()
    )
    ModelingPlan.model_validate_json(
        open(native_io_path(root / candidate_modeling_artifact.path), "rb").read()
    )
    canonical_scene = root / "analysis" / "scene_spec.json"
    canonical_modeling = root / "analysis" / "modeling_plan.json"
    canonical_material = root / "analysis" / "material_plan.json"
    canonical_binding = root / "analysis" / "material_binding_derivative.json"
    canonical_blend = root / "blender" / "scene.blend"
    _validate_exact_hash(
        canonical_scene,
        promotion_plan.canonical_scene_spec_v02_sha256,
        "canonical SceneSpec baseline",
    )
    _validate_exact_hash(
        canonical_modeling,
        promotion_plan.canonical_modeling_plan_sha256,
        "canonical ModelingPlan baseline",
    )
    _validate_exact_hash(
        canonical_blend,
        promotion_plan.canonical_blend_sha256,
        "canonical Blender baseline",
    )
    plan = AutonomyPlanV2.model_validate_json((session_root / "plan.json").read_bytes())
    result_artifact = geometry_approval.geometry_review_receipt
    geometry_receipt = SurfaceDetailSpatialGeometryReviewReceipt.model_validate_json(
        open(native_io_path(root / result_artifact.path), "rb").read()
    )
    if (
        geometry_receipt.controller_result.sha256 != promotion_plan.controller_result_sha256
        or geometry_receipt.controller_profile.sha256 != promotion_plan.controller_profile_sha256
        or geometry_receipt.controller_request.sha256 != promotion_plan.controller_request_sha256
        or geometry_receipt.controller_completion.sha256
        != promotion_plan.controller_completion_sha256
    ):
        raise ValueError("material promotion controller lifecycle changed")
    source_usage = promotion_plan.effective_budget_usage
    if source_usage.total_blender_builds + 1 > budget.total_blender_builds:
        raise PermissionError("material promotion Blender build budget is exhausted")
    promotion_usage = source_usage.model_copy(
        update={
            "material_rounds": source_usage.material_rounds + 1,
            "total_blender_builds": source_usage.total_blender_builds + 1,
            "canonical_promotions": source_usage.canonical_promotions + 1,
            "total_actions": source_usage.total_actions + 1,
        }
    )
    if promotion_usage.canonical_promotions > budget.canonical_promotions:
        raise PermissionError("material promotion canonical budget is exhausted")
    approval_path = repair_root / "material_promotion_approval.txt"
    _write_exact_bytes(approval_path, exact_approval.encode("utf-8"))
    approval_artifact = _artifact(
        root,
        approval_path,
        artifact_id="approval-item-crystalgun-surface-detail-material-promotion-01",
        kind="surface_detail_material_promotion_approval",
    )
    promotion_plan_artifact = _artifact(
        root,
        plan_path,
        artifact_id=promotion_plan.plan_id,
        kind="surface_detail_material_promotion_plan",
    )
    archive_root = repair_root / "promotion" / "archive"
    archive_scene = _snapshot_exact(
        root,
        canonical_scene,
        archive_root / "scene_spec.json",
        artifact_id="material-promotion-source-scene",
        kind="archived_scene_spec",
    )
    archive_modeling = _snapshot_exact(
        root,
        canonical_modeling,
        archive_root / "modeling_plan.json",
        artifact_id="material-promotion-source-modeling",
        kind="archived_modeling_plan",
    )
    archive_blend = _snapshot_exact(
        root,
        canonical_blend,
        archive_root / "scene.blend",
        artifact_id="material-promotion-source-blend",
        kind="archived_blend",
    )
    derived_paths = [
        root / "reports" / "scene_inventory.json",
        root / "reports" / "validation.json",
        root / "reports" / "build_provenance.json",
    ]
    archived_derived = [
        _snapshot_exact(
            root,
            path,
            archive_root / "derived" / path.name,
            artifact_id=f"material-promotion-source-{path.stem}",
            kind=f"archived_{path.stem}",
        )
        for path in derived_paths
        if path.is_file()
    ]
    archived_material = (
        _snapshot_exact(
            root,
            canonical_material,
            archive_root / "material_plan.json",
            artifact_id="material-promotion-source-material",
            kind="archived_material_plan",
        )
        if canonical_material.is_file()
        else None
    )
    archived_binding = (
        _snapshot_exact(
            root,
            canonical_binding,
            archive_root / "material_binding_derivative.json",
            artifact_id="material-promotion-source-binding",
            kind="archived_material_binding_manifest",
        )
        if canonical_binding.is_file()
        else None
    )
    phase_root = session_root / "material_phase" / "surface_detail_promotion_0008"
    rollback_path = phase_root / "rollback_receipt.json"
    receipt_path = phase_root / "promotion_receipt.json"
    if os.path.exists(native_io_path(rollback_path)):
        raise RuntimeError("surface-detail material promotion previously rolled back")
    if os.path.exists(native_io_path(receipt_path)):
        artifact = _artifact(
            root,
            receipt_path,
            artifact_id="material-receipt-exec-0009-material-surface-detail-runtime-manifest-repair",
            kind="material_phase_receipt",
        )
        receipt = MaterialPhaseReceiptV2.model_validate_json(
            open(native_io_path(receipt_path), "rb").read()
        )
        _validate_material_phase_receipt_payload(root, receipt, require_current=True)
        return {
            "outcome": "material_promoted",
            "material_phase_receipt": artifact.model_dump(mode="json"),
        }
    with (
        autonomy_session_lock(
            root,
            session_root,
            owner_id="aqv2-surface-detail-material-promotion",
            ttl_seconds=3600,
        ),
        canonical_scene_spec_write_lock(job_id, session_id, ttl_seconds=3600),
    ):
        try:
            binding_payload = _binding_manifest_payload(
                root,
                derivative_receipt,
                derivative_artifact,
                candidate_scene,
            )
            _replace_exact_file(
                root / candidate_scene_artifact.path,
                canonical_scene,
                candidate_scene_artifact.sha256,
            )
            _replace_exact_file(
                root / candidate_modeling_artifact.path,
                canonical_modeling,
                candidate_modeling_artifact.sha256,
            )
            _write_json_object(canonical_binding, binding_payload)
            _replace_exact_file(
                root / candidate_material_artifact.path,
                canonical_material,
                candidate_material_artifact.sha256,
            )
            _replace_exact_file(
                root / candidate_blend_artifact.path,
                canonical_blend,
                candidate_blend_artifact.sha256,
            )
            candidate_inventory = geometry_approval.candidate_inventory
            candidate_validation = geometry_approval.candidate_validation
            _replace_exact_file(
                root / candidate_inventory.path,
                root / "reports" / "scene_inventory.json",
                candidate_inventory.sha256,
            )
            _replace_exact_file(
                root / candidate_validation.path,
                root / "reports" / "validation.json",
                candidate_validation.sha256,
            )
            candidate_provenance_path = root / "a2w" / "r3" / "build" / "provenance.json"
            candidate_provenance_sha256 = sha256_file(candidate_provenance_path)
            _replace_exact_file(
                candidate_provenance_path,
                root / "reports" / "build_provenance.json",
                candidate_provenance_sha256,
            )
            binding_artifact = _artifact(
                root,
                canonical_binding,
                artifact_id="material-binding-derivative-runtime-manifest-repair-01",
                kind="canonical_material_binding_derivative",
            )
            state_geometry = transition_state(
                state,
                event="candidate_validated",
                evidence=geometry_approval_artifact,
                created_at=datetime.now(UTC),
                budget_usage=source_usage,
            )
            state_geometry_artifact = _write_or_validate_state(
                root,
                session_root / "states" / f"{state_geometry.sequence:04d}.json",
                state_geometry,
            )
            state_controller = transition_state(
                state_geometry,
                event="controller_output_ready",
                evidence=geometry_receipt.controller_result,
                created_at=state_geometry.created_at + timedelta(microseconds=1),
                budget_usage=source_usage,
            )
            state_controller_artifact = _write_or_validate_state(
                root,
                session_root / "states" / f"{state_controller.sequence:04d}.json",
                state_controller,
            )
            del state_geometry_artifact
            bundle = _load_controller_material_bundle(
                root,
                plan,
                state_controller,
                geometry_receipt.controller_result,
                authorized_profile_artifact=geometry_receipt.controller_profile,
            )
            canonical_scene_model, canonical_scene_sha256 = _canonical_scene_and_scope(
                root,
                plan,
            )
            if canonical_scene_sha256 != candidate_scene_artifact.sha256:
                raise ValueError("canonical candidate SceneSpec promotion hash changed")
            if bundle.completion.source_scene_spec_sha256 != canonical_scene_sha256:
                raise ValueError("controller result source SceneSpec binding is stale")
            input_map = _request_input_map(root, bundle.request)
            _validate_material_plan_dependencies(root, bundle.material_plan, input_map)
            _validate_graph_binding(
                root,
                bundle,
                canonical_scene_model,
                canonical_scene_sha256,
            )
            material_validation = _material_validation_artifact(
                root,
                phase_root,
                bundle,
                canonical_scene_model,
            )
            _compiled, compile_report = _compile_or_adopt_graph(
                root,
                phase_root,
                bundle,
            )
            compile_root = phase_root / "graph_compile"
            compiled_blend = compile_root / "compiled" / "material_graph.blend"
            neutral_preview = phase_root / "neutral_preview.png"
            neutral_report = phase_root / "neutral_preview_report.json"
            run_blender(
                "render_material_neutral_preview.py",
                [
                    "--material-id",
                    bundle.material_graph.material_id,
                    "--output",
                    str(neutral_preview),
                    "--report",
                    str(neutral_report),
                ],
                blend_file=compiled_blend,
                disable_autoexec=True,
            )
            with open(native_io_path(neutral_report), encoding="utf-8") as handle:
                neutral_payload = json.load(handle)
            if (
                neutral_payload.get("status") != "passed"
                or neutral_payload.get("blender_version") != "5.0.1"
                or neutral_payload.get("preview_sha256") != sha256_file(neutral_preview)
            ):
                raise RuntimeError("neutral material preview evidence is invalid")
            neutral_report_artifact = _artifact(
                root,
                neutral_report,
                artifact_id="neutral-material-preview-report-0008",
                kind="neutral_material_preview_report",
            )
            neutral_image_artifact = _artifact(
                root,
                neutral_preview,
                artifact_id="neutral-material-preview-0008",
                kind="neutral_material_preview",
            )
            source_scene_snapshot = _snapshot_exact(
                root,
                canonical_scene,
                phase_root / "source_scene_spec.json",
                artifact_id="material-source-scene-exec-0009",
                kind="source_scene_spec_snapshot",
            )
            intent, intent_artifact = _publish_or_adopt_intent(
                root,
                plan,
                phase_root,
                bundle,
                material_validation,
                compile_report,
                source_scene_snapshot,
                archived_material,
            )
            material_snapshot = _snapshot_exact(
                root,
                canonical_material,
                phase_root / "promoted" / "material_plan.json",
                artifact_id="promoted-material-plan",
                kind="canonical_material_plan_snapshot",
            )
            scene_snapshot = _snapshot_exact(
                root,
                canonical_scene,
                phase_root / "promoted" / "scene_spec.json",
                artifact_id="promoted-scene-spec",
                kind="canonical_scene_spec_snapshot",
            )
            blend_snapshot = _snapshot_exact(
                root,
                canonical_blend,
                phase_root / "promoted" / "scene.blend",
                artifact_id="promoted-scene-blend",
                kind="authoring_blend_snapshot",
            )
            inventory_snapshot = _snapshot_exact(
                root,
                root / "reports" / "scene_inventory.json",
                phase_root / "promoted" / "scene_inventory.json",
                artifact_id="promoted-scene-inventory",
                kind="scene_inventory_snapshot",
            )
            validation_snapshot = _snapshot_exact(
                root,
                root / "reports" / "validation.json",
                phase_root / "promoted" / "validation.json",
                artifact_id="promoted-scene-validation",
                kind="scene_validation_snapshot",
            )
            build_provenance_snapshot = _snapshot_exact(
                root,
                root / "reports" / "build_provenance.json",
                phase_root / "promoted" / "build_provenance.json",
                artifact_id="promoted-build-provenance",
                kind="build_provenance_snapshot",
            )
            current_provenance = collect_build_provenance(
                root,
                job_id,
                scene_spec_path=canonical_scene,
                validate_contracts=True,
                surface_detail_inventory_path=root / "reports" / "scene_inventory.json",
            )
            candidate_provenance = json.loads(
                (root / "reports" / "build_provenance.json").read_text(encoding="utf-8")
            )
            if current_provenance != candidate_provenance:
                raise RuntimeError("promoted build provenance differs from reviewed candidate")
            build_fingerprint = str(current_provenance["fingerprint"])
            receipt_provenance = [
                intent_artifact,
                bundle.result_artifact,
                bundle.material_plan_artifact,
                bundle.material_graph_artifact,
                material_validation,
                compile_report,
                *([archived_material] if archived_material is not None else []),
                material_snapshot,
                scene_snapshot,
                blend_snapshot,
                inventory_snapshot,
                validation_snapshot,
                build_provenance_snapshot,
            ]
            receipt_payload = {
                "intent": intent_artifact.sha256,
                "candidate": bundle.material_plan_artifact.sha256,
                "compile_report": compile_report.sha256,
                "build_fingerprint": build_fingerprint,
                "neutral_preview": neutral_image_artifact.sha256,
            }
            material_receipt = MaterialPhaseReceiptV2(
                contract_id="material-receipt-exec-0009-material-surface-detail-runtime-manifest-repair",
                receipt_id="material-receipt-exec-0009-material-surface-detail-runtime-manifest-repair",
                job_id=plan.job_id,
                workflow_id=plan.workflow_id,
                dispatch_id=plan.dispatch_id,
                session_id=plan.session_id,
                input_sha256=stable_json_digest(receipt_payload),
                source_fingerprint=stable_json_digest(
                    {**receipt_payload, "canonical_material": material_snapshot.sha256}
                ),
                producer=_PRODUCER,
                provenance=receipt_provenance,
                created_at=datetime.now(UTC),
                promotion_intent=intent_artifact,
                controller_result=bundle.result_artifact,
                material_plan_candidate=bundle.material_plan_artifact,
                material_graph_spec=bundle.material_graph_artifact,
                material_validation=material_validation,
                graph_compile_report=compile_report,
                archived_material_plan=archived_material,
                canonical_material_snapshot=material_snapshot,
                canonical_scene_snapshot=scene_snapshot,
                authoring_blend_snapshot=blend_snapshot,
                scene_inventory_snapshot=inventory_snapshot,
                scene_validation_snapshot=validation_snapshot,
                build_provenance_snapshot=build_provenance_snapshot,
                previous_canonical_material_sha256=(
                    archived_material.sha256 if archived_material is not None else None
                ),
                canonical_material_plan_sha256=material_snapshot.sha256,
                canonical_scene_spec_sha256=scene_snapshot.sha256,
                build_fingerprint=build_fingerprint,
                budget_usage_after=promotion_usage,
            )
            _validate_material_phase_receipt_payload(
                root,
                material_receipt,
                require_current=True,
            )
            material_receipt_artifact = write_immutable_v2_model(
                root,
                receipt_path,
                material_receipt,
            ).model_copy(update={"kind": "material_phase_receipt"})
            quality_state = transition_state(
                state_controller,
                event="material_candidate_validated",
                evidence=material_receipt_artifact,
                created_at=datetime.now(UTC),
                budget_usage=promotion_usage,
            )
            quality_state_artifact = _write_or_validate_state(
                root,
                session_root / "states" / f"{quality_state.sequence:04d}.json",
                quality_state,
            )
            promotion_receipt_path = repair_root / "material_promotion_receipt.json"
            promotion_receipt_provenance = [
                approval_artifact,
                promotion_plan_artifact,
                geometry_approval_artifact,
                binding_artifact,
                material_receipt_artifact,
                neutral_report_artifact,
                neutral_image_artifact,
                state_artifact,
                candidate_scene_artifact,
                candidate_modeling_artifact,
                candidate_material_artifact,
                candidate_graph_artifact,
                candidate_blend_artifact,
                quality_state_artifact,
            ]
            promotion_receipt = SurfaceDetailMaterialPromotionReceipt(
                contract_id="item-crystalgun-surface-detail-material-promotion-01",
                job_id=job_id,
                workflow_id=state.workflow_id,
                dispatch_id=state.dispatch_id,
                session_id=session_id,
                input_sha256=stable_json_digest(
                    {item.path: item.sha256 for item in promotion_receipt_provenance}
                ),
                source_fingerprint=material_receipt_artifact.sha256,
                producer=_PRODUCER,
                provenance=promotion_receipt_provenance,
                created_at=datetime.now(UTC),
                promotion_id="item-crystalgun-surface-detail-material-promotion-01",
                approval=approval_artifact,
                promotion_plan=promotion_plan_artifact,
                geometry_review_approval=geometry_approval_artifact,
                material_binding_manifest=binding_artifact,
                material_phase_receipt=material_receipt_artifact,
                neutral_preview_report=neutral_report_artifact,
                neutral_preview_image=neutral_image_artifact,
                source_state=state_artifact,
                candidate_scene_spec=candidate_scene_artifact,
                candidate_modeling_plan=candidate_modeling_artifact,
                candidate_material_plan=candidate_material_artifact,
                candidate_material_graph=candidate_graph_artifact,
                candidate_blend=candidate_blend_artifact,
                resumed_state=quality_state_artifact,
            )
            promotion_receipt_artifact = _write_or_adopt_v2_model(
                root=root,
                path=promotion_receipt_path,
                model=promotion_receipt,
                kind="surface_detail_material_promotion_receipt",
            )
            del intent, binding_payload, state_controller_artifact
        except Exception as failure:
            _replace_exact_file(
                root / archive_scene.path,
                canonical_scene,
                archive_scene.sha256,
            )
            _replace_exact_file(
                root / archive_modeling.path,
                canonical_modeling,
                archive_modeling.sha256,
            )
            _replace_exact_file(
                root / archive_blend.path,
                canonical_blend,
                archive_blend.sha256,
            )
            for archive in archived_derived:
                target_name = Path(archive.path).name
                _replace_exact_file(
                    root / archive.path,
                    root / "reports" / target_name,
                    archive.sha256,
                )
            if archived_material is None:
                if canonical_material.is_file():
                    os.unlink(native_io_path(canonical_material))
            else:
                _replace_exact_file(
                    root / archived_material.path,
                    canonical_material,
                    archived_material.sha256,
                )
            if archived_binding is None:
                if canonical_binding.is_file():
                    os.unlink(native_io_path(canonical_binding))
            else:
                _replace_exact_file(
                    root / archived_binding.path,
                    canonical_binding,
                    archived_binding.sha256,
                )
            rollback = SurfaceDetailMaterialPromotionRollbackReceipt(
                contract_id="item-crystalgun-surface-detail-material-promotion-rollback-01",
                job_id=job_id,
                workflow_id=state.workflow_id,
                dispatch_id=state.dispatch_id,
                session_id=session_id,
                input_sha256=stable_json_digest(
                    {
                        "plan": promotion_plan_artifact.sha256,
                        "failure": type(failure).__name__,
                    }
                ),
                source_fingerprint=promotion_plan_artifact.sha256,
                producer=_PRODUCER,
                provenance=[
                    approval_artifact,
                    promotion_plan_artifact,
                    archive_scene,
                    archive_modeling,
                    archive_blend,
                    *archived_derived,
                    *([archived_material] if archived_material is not None else []),
                    *([archived_binding] if archived_binding is not None else []),
                ],
                created_at=datetime.now(UTC),
                promotion_id="item-crystalgun-surface-detail-material-promotion-01",
                approval=approval_artifact,
                promotion_plan=promotion_plan_artifact,
                archived_scene_spec=archive_scene,
                archived_modeling_plan=archive_modeling,
                archived_blend=archive_blend,
                archived_derived=archived_derived,
                archived_material_plan=archived_material,
                archived_binding_manifest=archived_binding,
                restored_scene_spec_sha256=sha256_file(canonical_scene),
                restored_modeling_plan_sha256=sha256_file(canonical_modeling),
                restored_blend_sha256=sha256_file(canonical_blend),
                failure_type=type(failure).__name__,
                reason=str(failure).replace(str(root), "<job-root>")[:1024],
            )
            _write_or_adopt_v2_model(
                root=root,
                path=rollback_path,
                model=rollback,
                kind="surface_detail_material_promotion_rollback_receipt",
            )
            raise RuntimeError(
                "surface-detail material promotion failed and canonical baselines were restored"
            ) from failure
    return {
        "outcome": "material_promoted",
        "material_phase_receipt": material_receipt.model_dump(mode="json"),
        "material_phase_receipt_artifact": material_receipt_artifact.model_dump(mode="json"),
        "neutral_preview_report": neutral_report_artifact.model_dump(mode="json"),
        "neutral_preview_image": neutral_image_artifact.model_dump(mode="json"),
        "material_promotion_receipt": promotion_receipt.model_dump(mode="json"),
        "material_promotion_receipt_artifact": promotion_receipt_artifact.model_dump(mode="json"),
        "next_state": quality_state.model_dump(mode="json"),
        "next_state_artifact": quality_state_artifact.model_dump(mode="json"),
    }


def execute_material_completion_binding_repair(
    job_id: str,
    session_id: str,
    *,
    repair_plan_path: Path,
    repair_plan_sha256: str,
    exact_approval: str,
    allow_disabled_experimental: bool = False,
) -> dict[str, Any]:
    """Run one full-request-bound controller and promote its reviewed material."""

    root = job_dir(job_id).expanduser().resolve()
    session_root = root / "production" / "autonomy_v2" / session_id
    plan_path = repair_plan_path.expanduser().resolve()
    if not plan_path.is_relative_to(root):
        raise ValueError("completion binding repair plan escaped the job root")
    _validate_exact_hash(plan_path, repair_plan_sha256, "completion binding repair plan")
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan_payload, dict):
        raise ValueError("completion binding repair plan is not an object")
    _validate_completion_binding_repair_plan(
        plan_payload,
        job_id=job_id,
        session_id=session_id,
    )
    expected_approval = expected_material_completion_binding_repair_approval(
        plan_payload,
        repair_plan_sha256,
    )
    if exact_approval != expected_approval:
        raise PermissionError("completion binding repair approval is not exact")
    _profile, budget, state, state_artifact = _validate_profile_opt_in(
        root,
        session_root,
        allow_disabled_experimental=allow_disabled_experimental,
        state_sequence=9,
    )
    if state_artifact.sha256 != plan_payload["source_aq_state_sha256"]:
        raise ValueError("completion binding repair source AQ state is stale")
    _validate_exact_hash(root / "input" / "reference.png", _REFERENCE_SHA256, "reference")
    if plan_payload["reference_sha256"] != _REFERENCE_SHA256:
        raise ValueError("completion binding repair reference hash changed")

    repair_root = plan_path.parent
    source_repair_root = session_root / "surface_detail_runtime_manifest_repairs" / _PLAN_ID
    source_promotion_path = source_repair_root / "material_promotion_plan.json"
    source_promotion_artifact = _exact_artifact(
        root,
        source_promotion_path,
        artifact_id="item-crystalgun-surface-detail-material-promotion-01",
        kind="surface_detail_material_promotion_plan",
        expected_sha256=plan_payload["source_material_promotion_plan_sha256"],
    )
    source_promotion = SurfaceDetailMaterialPromotionPlan.model_validate_json(
        open(native_io_path(source_promotion_path), "rb").read()
    )
    failed_rollback_path = (
        session_root / "material_phase" / "surface_detail_promotion_0008" / "rollback_receipt.json"
    )
    failed_rollback_artifact = _exact_artifact(
        root,
        failed_rollback_path,
        artifact_id="item-crystalgun-surface-detail-material-promotion-rollback-01",
        kind="surface_detail_material_promotion_rollback_receipt",
        expected_sha256=plan_payload["failed_promotion_rollback_receipt_sha256"],
    )
    failed_rollback = SurfaceDetailMaterialPromotionRollbackReceipt.model_validate_json(
        open(native_io_path(failed_rollback_path), "rb").read()
    )
    if not failed_rollback.canonical_restored:
        raise ValueError("failed promotion rollback did not restore canonical baselines")

    failed_execution_root = (
        session_root
        / "controller_executions"
        / "exec-0009-material-surface-detail-runtime-manifest-repair"
    )
    failed_request_path = failed_execution_root / "request.json"
    failed_result_path = failed_execution_root / "result.json"
    failed_request_artifact = _exact_artifact(
        root,
        failed_request_path,
        artifact_id="request-exec-0009-material-surface-detail-runtime-manifest-repair",
        kind="failed_controller_request",
        expected_sha256=plan_payload["failed_controller_request_sha256"],
    )
    failed_result_artifact = _exact_artifact(
        root,
        failed_result_path,
        artifact_id="result-exec-0009-material-surface-detail-runtime-manifest-repair",
        kind="failed_controller_result",
        expected_sha256=plan_payload["failed_controller_result_sha256"],
    )
    failed_request = ControllerExecutionRequest.model_validate_json(
        open(native_io_path(failed_request_path), "rb").read()
    )
    failed_result = ControllerResult.model_validate_json(
        open(native_io_path(failed_result_path), "rb").read()
    )
    failed_completion_output = next(
        item for item in failed_result.outputs if item.path.endswith("/completion.json")
    )
    failed_completion_path = root / failed_completion_output.path
    failed_completion_artifact = _exact_artifact(
        root,
        failed_completion_path,
        artifact_id="failed-material-controller-completion-exec-0009",
        kind="failed_material_controller_completion",
        expected_sha256=plan_payload["failed_controller_completion_sha256"],
    )
    failed_completion = MaterialControllerCompletionV2.model_validate_json(
        open(native_io_path(failed_completion_path), "rb").read()
    )
    failed_request_map = {item.path: item.sha256 for item in failed_request.immutable_inputs}
    if (
        len(failed_request_map) != plan_payload["request_immutable_input_count"]
        or stable_json_digest(failed_request_map)
        != plan_payload["request_immutable_input_map_sha256"]
        or len(failed_completion.immutable_input_sha256)
        != plan_payload["completion_immutable_input_count"]
        or stable_json_digest(failed_completion.immutable_input_sha256)
        != plan_payload["completion_immutable_input_map_sha256"]
        or failed_completion.immutable_input_sha256 == failed_request_map
    ):
        raise ValueError("failed controller immutable input mismatch evidence changed")

    geometry_approval_path = source_repair_root / "geometry_review_approval_receipt.json"
    geometry_approval_artifact = _exact_artifact(
        root,
        geometry_approval_path,
        artifact_id=f"geometry-review-approval-{_PLAN_ID}",
        kind="surface_detail_geometry_review_approval_receipt",
        expected_sha256=source_promotion.geometry_review_approval_receipt_sha256,
    )
    geometry_approval = SurfaceDetailGeometryReviewApprovalReceipt.model_validate_json(
        open(native_io_path(geometry_approval_path), "rb").read()
    )
    derivative_artifact = geometry_approval.material_binding_derivative
    if derivative_artifact.sha256 != plan_payload["material_binding_derivative_sha256"]:
        raise ValueError("completion binding material derivative changed")
    validate_v2_artifact(root, derivative_artifact)
    derivative_receipt = MaterialBindingDerivativeReceipt.model_validate_json(
        open(native_io_path(root / derivative_artifact.path), "rb").read()
    )
    candidate_scene_artifact = geometry_approval.candidate_scene_spec
    candidate_modeling_artifact = geometry_approval.candidate_modeling_plan
    candidate_material_artifact = geometry_approval.candidate_material_plan
    candidate_graph_artifact = geometry_approval.candidate_material_graph
    candidate_blend_artifact = geometry_approval.candidate_blend
    planned_candidates = (
        (candidate_scene_artifact, "candidate_scene_spec_v02_sha256"),
        (candidate_modeling_artifact, "candidate_modeling_plan_sha256"),
        (candidate_material_artifact, "candidate_material_plan_sha256"),
        (candidate_graph_artifact, "candidate_material_graph_sha256"),
        (candidate_blend_artifact, "candidate_blend_sha256"),
    )
    for artifact, key in planned_candidates:
        if artifact.sha256 != plan_payload[key]:
            raise ValueError(f"completion binding candidate changed: {artifact.kind}")
        validate_v2_artifact(root, artifact)
    candidate_scene = SceneSpec.model_validate_json(
        open(native_io_path(root / candidate_scene_artifact.path), "rb").read()
    )
    ModelingPlan.model_validate_json(
        open(native_io_path(root / candidate_modeling_artifact.path), "rb").read()
    )

    canonical_scene = root / "analysis" / "scene_spec.json"
    canonical_modeling = root / "analysis" / "modeling_plan.json"
    canonical_material = root / "analysis" / "material_plan.json"
    canonical_binding = root / "analysis" / "material_binding_derivative.json"
    canonical_blend = root / "blender" / "scene.blend"
    for path, key, label in (
        (canonical_scene, "canonical_scene_spec_v02_sha256", "canonical SceneSpec"),
        (canonical_modeling, "canonical_modeling_plan_sha256", "canonical ModelingPlan"),
        (canonical_blend, "canonical_blend_sha256", "canonical Blender scene"),
    ):
        _validate_exact_hash(path, plan_payload[key], label)

    aq_plan = AutonomyPlanV2.model_validate_json(
        open(native_io_path(session_root / "plan.json"), "rb").read()
    )
    approval_path = repair_root / "approval.txt"
    _write_exact_bytes(approval_path, exact_approval.encode("utf-8"))
    approval_artifact = _artifact(
        root,
        approval_path,
        artifact_id="approval-item-crystalgun-material-completion-binding-repair-01",
        kind="material_completion_binding_repair_approval",
    )
    repair_plan_artifact = _artifact(
        root,
        plan_path,
        artifact_id=str(plan_payload["plan_id"]),
        kind="material_completion_binding_repair_plan",
    )
    preparation_provenance = [
        repair_plan_artifact,
        approval_artifact,
        state_artifact,
        source_promotion_artifact,
        failed_rollback_artifact,
        failed_request_artifact,
        failed_result_artifact,
        failed_completion_artifact,
        geometry_approval_artifact,
        derivative_artifact,
        candidate_scene_artifact,
        candidate_modeling_artifact,
        candidate_material_artifact,
        candidate_graph_artifact,
        candidate_blend_artifact,
    ]
    preparation = MaterialCompletionBindingRepairPreparation(
        contract_id="item-crystalgun-material-completion-binding-repair-preparation-01",
        job_id=job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(
            {item.path: item.sha256 for item in preparation_provenance}
        ),
        source_fingerprint=failed_rollback_artifact.sha256,
        producer=_PRODUCER,
        provenance=preparation_provenance,
        created_at=datetime.now(UTC),
        repair_id=str(plan_payload["plan_id"]),
        repair_plan=repair_plan_artifact,
        approval=approval_artifact,
        source_state=state_artifact,
        source_material_promotion_plan=source_promotion_artifact,
        failed_promotion_rollback=failed_rollback_artifact,
        failed_controller_request=failed_request_artifact,
        failed_controller_result=failed_result_artifact,
        failed_controller_completion=failed_completion_artifact,
        geometry_review_approval=geometry_approval_artifact,
        material_binding_derivative=derivative_artifact,
        candidate_scene_spec=candidate_scene_artifact,
        candidate_modeling_plan=candidate_modeling_artifact,
        candidate_material_plan=candidate_material_artifact,
        candidate_material_graph=candidate_graph_artifact,
        candidate_blend=candidate_blend_artifact,
    )
    preparation_artifact = _write_or_adopt_v2_model(
        root=root,
        path=repair_root / "preparation_receipt.json",
        model=preparation,
        kind="material_completion_binding_repair_preparation",
    )

    archive_root = repair_root / "archive"
    archive_scene = _snapshot_exact(
        root,
        canonical_scene,
        archive_root / "scene_spec.json",
        artifact_id="completion-binding-source-scene",
        kind="archived_scene_spec",
    )
    archive_modeling = _snapshot_exact(
        root,
        canonical_modeling,
        archive_root / "modeling_plan.json",
        artifact_id="completion-binding-source-modeling",
        kind="archived_modeling_plan",
    )
    archive_blend = _snapshot_exact(
        root,
        canonical_blend,
        archive_root / "scene.blend",
        artifact_id="completion-binding-source-blend",
        kind="archived_blend",
    )
    derived_paths = [
        root / "reports" / "scene_inventory.json",
        root / "reports" / "validation.json",
        root / "reports" / "build_provenance.json",
    ]
    archived_derived = [
        _snapshot_exact(
            root,
            path,
            archive_root / "derived" / path.name,
            artifact_id=f"completion-binding-source-{path.stem}",
            kind=f"archived_{path.stem}",
        )
        for path in derived_paths
        if os.path.isfile(native_io_path(path))
    ]
    archived_material = (
        _snapshot_exact(
            root,
            canonical_material,
            archive_root / "material_plan.json",
            artifact_id="completion-binding-source-material",
            kind="archived_material_plan",
        )
        if os.path.isfile(native_io_path(canonical_material))
        else None
    )
    archived_binding = (
        _snapshot_exact(
            root,
            canonical_binding,
            archive_root / "material_binding_derivative.json",
            artifact_id="completion-binding-source-binding",
            kind="archived_material_binding_manifest",
        )
        if os.path.isfile(native_io_path(canonical_binding))
        else None
    )

    phase_root = session_root / "material_phase" / "completion_binding_repair_0010"
    receipt_path = phase_root / "promotion_receipt.json"
    rollback_path = phase_root / "rollback_receipt.json"
    attempted_request: AQV2Artifact | None = None
    attempted_result: AQV2Artifact | None = None
    attempted_completion: AQV2Artifact | None = None
    with (
        autonomy_session_lock(
            root,
            session_root,
            owner_id="aqv2-material-completion-binding-repair",
            ttl_seconds=3600,
        ),
        canonical_scene_spec_write_lock(job_id, session_id, ttl_seconds=3600),
    ):
        try:
            binding_payload = _binding_manifest_payload(
                root,
                derivative_receipt,
                derivative_artifact,
                candidate_scene,
            )
            _replace_exact_file(
                root / candidate_scene_artifact.path,
                canonical_scene,
                candidate_scene_artifact.sha256,
            )
            _replace_exact_file(
                root / candidate_modeling_artifact.path,
                canonical_modeling,
                candidate_modeling_artifact.sha256,
            )
            _write_json_object(canonical_binding, binding_payload)
            canonical_scene_artifact = _artifact(
                root,
                canonical_scene,
                artifact_id="completion-binding-canonical-scene-candidate",
                kind="candidate_scene_spec_v02",
            )
            canonical_modeling_artifact = _artifact(
                root,
                canonical_modeling,
                artifact_id="completion-binding-canonical-modeling-candidate",
                kind="candidate_modeling_plan",
            )
            state_controller = transition_state(
                state,
                event="candidate_validated",
                evidence=preparation_artifact,
                created_at=datetime.now(UTC),
                budget_usage=state.budget_usage,
            )
            state_controller_artifact = _write_or_validate_state(
                root,
                session_root / "states" / f"{state_controller.sequence:04d}.json",
                state_controller,
            )
            dependency_artifacts = []
            duplicate_blueprint_hashes = {
                candidate_material_artifact.sha256,
                candidate_graph_artifact.sha256,
            }
            for item in failed_request.immutable_inputs:
                if item.sha256 in duplicate_blueprint_hashes:
                    continue
                dependency_artifacts.append(
                    _artifact(
                        root,
                        root / item.path,
                        artifact_id=item.artifact_id,
                        kind="controller_immutable_input",
                    )
                )
            (
                controller_result,
                controller_request_artifact,
                controller_result_artifact,
                controller_profile_artifact,
                controller_assignment_artifact,
                controller_completion_artifact,
                controller_material_artifact,
                controller_graph_artifact,
                controller_usage,
            ) = _execute_controller(
                root=root,
                session_root=session_root,
                recovery_id=str(plan_payload["plan_id"]),
                preparation_artifact=preparation_artifact,
                state=state_controller,
                state_artifact=state_controller_artifact,
                budget=budget,
                candidate_scene_artifact=canonical_scene_artifact,
                candidate_modeling_artifact=canonical_modeling_artifact,
                candidate_material_artifact=candidate_material_artifact,
                candidate_graph_artifact=candidate_graph_artifact,
                dependency_artifacts=dependency_artifacts,
                plan_artifact=repair_plan_artifact,
                execution_id="exec-0010-material-completion-binding-repair",
                output_leaf="material_completion_binding_repair_01",
                controller_increment=1,
                blender_build_increment=0,
                action_increment=1,
                controller_staging_root=repair_root / "controller_staging",
                completion_input_binding="full_request_input_map",
            )
            del controller_result
            attempted_request = controller_request_artifact
            attempted_result = controller_result_artifact
            attempted_completion = controller_completion_artifact
            new_request = ControllerExecutionRequest.model_validate_json(
                open(native_io_path(root / controller_request_artifact.path), "rb").read()
            )
            new_completion = MaterialControllerCompletionV2.model_validate_json(
                open(native_io_path(root / controller_completion_artifact.path), "rb").read()
            )
            new_request_map = {item.path: item.sha256 for item in new_request.immutable_inputs}
            if (
                new_completion.immutable_input_sha256 != new_request_map
                or new_completion.source_scene_spec_sha256 != canonical_scene_artifact.sha256
                or controller_material_artifact.sha256 != candidate_material_artifact.sha256
                or controller_graph_artifact.sha256 != candidate_graph_artifact.sha256
            ):
                raise ValueError("repaired controller completion is not fully request-bound")
            state_validation = transition_state(
                state_controller,
                event="controller_output_ready",
                evidence=controller_result_artifact,
                created_at=datetime.now(UTC),
                budget_usage=controller_usage,
            )
            state_validation_artifact = _write_or_validate_state(
                root,
                session_root / "states" / f"{state_validation.sequence:04d}.json",
                state_validation,
            )
            bundle = _load_controller_material_bundle(
                root,
                aq_plan,
                state_validation,
                controller_result_artifact,
                authorized_profile_artifact=controller_profile_artifact,
            )
            canonical_scene_model, canonical_scene_sha256 = _canonical_scene_and_scope(
                root,
                aq_plan,
            )
            if canonical_scene_sha256 != candidate_scene_artifact.sha256:
                raise ValueError("repaired canonical candidate SceneSpec changed")
            input_map = _request_input_map(root, bundle.request)
            if bundle.completion.immutable_input_sha256 != input_map:
                raise ValueError("strict material bundle lost full request binding")
            _validate_material_plan_dependencies(root, bundle.material_plan, input_map)
            _validate_graph_binding(
                root,
                bundle,
                canonical_scene_model,
                canonical_scene_sha256,
            )
            material_validation = _material_validation_artifact(
                root,
                phase_root,
                bundle,
                canonical_scene_model,
            )
            _compiled, compile_report = _compile_or_adopt_graph(
                root,
                phase_root,
                bundle,
            )
            compiled_blend = phase_root / "graph_compile" / "compiled" / "material_graph.blend"
            neutral_preview = phase_root / "neutral_preview.png"
            neutral_report = phase_root / "neutral_preview_report.json"
            run_blender(
                "render_material_neutral_preview.py",
                [
                    "--material-id",
                    bundle.material_graph.material_id,
                    "--output",
                    str(neutral_preview),
                    "--report",
                    str(neutral_report),
                ],
                blend_file=compiled_blend,
                disable_autoexec=True,
            )
            neutral_payload = json.loads(neutral_report.read_text(encoding="utf-8"))
            if (
                neutral_payload.get("status") != "passed"
                or neutral_payload.get("blender_version") != "5.0.1"
                or neutral_payload.get("preview_sha256") != sha256_file(neutral_preview)
            ):
                raise RuntimeError("neutral material preview evidence is invalid")
            neutral_report_artifact = _artifact(
                root,
                neutral_report,
                artifact_id="neutral-material-preview-report-0010",
                kind="neutral_material_preview_report",
            )
            neutral_image_artifact = _artifact(
                root,
                neutral_preview,
                artifact_id="neutral-material-preview-0010",
                kind="neutral_material_preview",
            )

            _replace_exact_file(
                root / controller_material_artifact.path,
                canonical_material,
                controller_material_artifact.sha256,
            )
            _replace_exact_file(
                root / candidate_blend_artifact.path,
                canonical_blend,
                candidate_blend_artifact.sha256,
            )
            for candidate_report, destination in (
                (geometry_approval.candidate_inventory, root / "reports" / "scene_inventory.json"),
                (geometry_approval.candidate_validation, root / "reports" / "validation.json"),
            ):
                _replace_exact_file(
                    root / candidate_report.path,
                    destination,
                    candidate_report.sha256,
                )
            candidate_provenance_path = root / "a2w" / "r3" / "build" / "provenance.json"
            _replace_exact_file(
                candidate_provenance_path,
                root / "reports" / "build_provenance.json",
                sha256_file(candidate_provenance_path),
            )
            binding_artifact = _artifact(
                root,
                canonical_binding,
                artifact_id="material-binding-completion-repair-01",
                kind="canonical_material_binding_derivative",
            )
            source_scene_snapshot = _snapshot_exact(
                root,
                canonical_scene,
                phase_root / "source_scene_spec.json",
                artifact_id="material-source-scene-exec-0010",
                kind="source_scene_spec_snapshot",
            )
            _intent, intent_artifact = _publish_or_adopt_intent(
                root,
                aq_plan,
                phase_root,
                bundle,
                material_validation,
                compile_report,
                source_scene_snapshot,
                archived_material,
            )
            material_snapshot = _snapshot_exact(
                root,
                canonical_material,
                phase_root / "promoted" / "material_plan.json",
                artifact_id="completion-binding-promoted-material-plan",
                kind="canonical_material_plan_snapshot",
            )
            scene_snapshot = _snapshot_exact(
                root,
                canonical_scene,
                phase_root / "promoted" / "scene_spec.json",
                artifact_id="completion-binding-promoted-scene-spec",
                kind="canonical_scene_spec_snapshot",
            )
            blend_snapshot = _snapshot_exact(
                root,
                canonical_blend,
                phase_root / "promoted" / "scene.blend",
                artifact_id="completion-binding-promoted-scene-blend",
                kind="authoring_blend_snapshot",
            )
            inventory_snapshot = _snapshot_exact(
                root,
                root / "reports" / "scene_inventory.json",
                phase_root / "promoted" / "scene_inventory.json",
                artifact_id="completion-binding-promoted-scene-inventory",
                kind="scene_inventory_snapshot",
            )
            validation_snapshot = _snapshot_exact(
                root,
                root / "reports" / "validation.json",
                phase_root / "promoted" / "validation.json",
                artifact_id="completion-binding-promoted-scene-validation",
                kind="scene_validation_snapshot",
            )
            provenance_snapshot = _snapshot_exact(
                root,
                root / "reports" / "build_provenance.json",
                phase_root / "promoted" / "build_provenance.json",
                artifact_id="completion-binding-promoted-build-provenance",
                kind="build_provenance_snapshot",
            )
            current_provenance = collect_build_provenance(
                root,
                job_id,
                scene_spec_path=canonical_scene,
                validate_contracts=True,
                surface_detail_inventory_path=root / "reports" / "scene_inventory.json",
            )
            candidate_provenance = json.loads(
                (root / "reports" / "build_provenance.json").read_text(encoding="utf-8")
            )
            if current_provenance != candidate_provenance:
                raise RuntimeError("promoted build provenance differs from reviewed candidate")
            promotion_usage = controller_usage.model_copy(
                update={
                    "material_rounds": controller_usage.material_rounds + 1,
                    "total_blender_builds": controller_usage.total_blender_builds + 1,
                    "canonical_promotions": controller_usage.canonical_promotions + 1,
                    "total_actions": controller_usage.total_actions + 1,
                }
            )
            if (
                promotion_usage.total_blender_builds > budget.total_blender_builds
                or promotion_usage.canonical_promotions > budget.canonical_promotions
                or promotion_usage.total_actions > budget.total_actions
            ):
                raise PermissionError("completion binding promotion budget is exhausted")
            build_fingerprint = str(current_provenance["fingerprint"])
            receipt_provenance = [
                intent_artifact,
                bundle.result_artifact,
                bundle.material_plan_artifact,
                bundle.material_graph_artifact,
                material_validation,
                compile_report,
                *([archived_material] if archived_material is not None else []),
                material_snapshot,
                scene_snapshot,
                blend_snapshot,
                inventory_snapshot,
                validation_snapshot,
                provenance_snapshot,
            ]
            receipt_payload = {
                "intent": intent_artifact.sha256,
                "candidate": bundle.material_plan_artifact.sha256,
                "compile_report": compile_report.sha256,
                "build_fingerprint": build_fingerprint,
                "neutral_preview": neutral_image_artifact.sha256,
            }
            material_receipt = MaterialPhaseReceiptV2(
                contract_id="material-receipt-exec-0010-material-completion-binding-repair",
                receipt_id="material-receipt-exec-0010-material-completion-binding-repair",
                job_id=aq_plan.job_id,
                workflow_id=aq_plan.workflow_id,
                dispatch_id=aq_plan.dispatch_id,
                session_id=aq_plan.session_id,
                input_sha256=stable_json_digest(receipt_payload),
                source_fingerprint=stable_json_digest(
                    {**receipt_payload, "canonical_material": material_snapshot.sha256}
                ),
                producer=_PRODUCER,
                provenance=receipt_provenance,
                created_at=datetime.now(UTC),
                promotion_intent=intent_artifact,
                controller_result=bundle.result_artifact,
                material_plan_candidate=bundle.material_plan_artifact,
                material_graph_spec=bundle.material_graph_artifact,
                material_validation=material_validation,
                graph_compile_report=compile_report,
                archived_material_plan=archived_material,
                canonical_material_snapshot=material_snapshot,
                canonical_scene_snapshot=scene_snapshot,
                authoring_blend_snapshot=blend_snapshot,
                scene_inventory_snapshot=inventory_snapshot,
                scene_validation_snapshot=validation_snapshot,
                build_provenance_snapshot=provenance_snapshot,
                previous_canonical_material_sha256=(
                    archived_material.sha256 if archived_material is not None else None
                ),
                canonical_material_plan_sha256=material_snapshot.sha256,
                canonical_scene_spec_sha256=scene_snapshot.sha256,
                build_fingerprint=build_fingerprint,
                budget_usage_after=promotion_usage,
            )
            _validate_material_phase_receipt_payload(
                root,
                material_receipt,
                require_current=True,
            )
            material_receipt_artifact = write_immutable_v2_model(
                root,
                receipt_path,
                material_receipt,
            ).model_copy(update={"kind": "material_phase_receipt"})
            quality_state = transition_state(
                state_validation,
                event="material_candidate_validated",
                evidence=material_receipt_artifact,
                created_at=datetime.now(UTC),
                budget_usage=promotion_usage,
            )
            quality_state_artifact = _write_or_validate_state(
                root,
                session_root / "states" / f"{quality_state.sequence:04d}.json",
                quality_state,
            )
            promotion_provenance = [
                repair_plan_artifact,
                approval_artifact,
                preparation_artifact,
                controller_profile_artifact,
                controller_assignment_artifact,
                controller_request_artifact,
                controller_result_artifact,
                controller_completion_artifact,
                binding_artifact,
                material_receipt_artifact,
                neutral_report_artifact,
                neutral_image_artifact,
                quality_state_artifact,
            ]
            promotion_receipt = MaterialCompletionBindingPromotionReceipt(
                contract_id="item-crystalgun-material-completion-binding-promotion-01",
                job_id=job_id,
                workflow_id=state.workflow_id,
                dispatch_id=state.dispatch_id,
                session_id=session_id,
                input_sha256=stable_json_digest(
                    {item.path: item.sha256 for item in promotion_provenance}
                ),
                source_fingerprint=material_receipt_artifact.sha256,
                producer=_PRODUCER,
                provenance=promotion_provenance,
                created_at=datetime.now(UTC),
                repair_id=str(plan_payload["plan_id"]),
                repair_plan=repair_plan_artifact,
                approval=approval_artifact,
                preparation=preparation_artifact,
                controller_profile=controller_profile_artifact,
                controller_assignment=controller_assignment_artifact,
                controller_request=controller_request_artifact,
                controller_result=controller_result_artifact,
                controller_completion=controller_completion_artifact,
                material_binding_manifest=binding_artifact,
                material_phase_receipt=material_receipt_artifact,
                neutral_preview_report=neutral_report_artifact,
                neutral_preview_image=neutral_image_artifact,
                resumed_state=quality_state_artifact,
            )
            promotion_receipt_artifact = _write_or_adopt_v2_model(
                root=root,
                path=repair_root / "promotion_receipt.json",
                model=promotion_receipt,
                kind="material_completion_binding_promotion_receipt",
            )
            del _intent, state_validation_artifact
        except Exception as failure:
            _replace_exact_file(root / archive_scene.path, canonical_scene, archive_scene.sha256)
            _replace_exact_file(
                root / archive_modeling.path,
                canonical_modeling,
                archive_modeling.sha256,
            )
            _replace_exact_file(root / archive_blend.path, canonical_blend, archive_blend.sha256)
            for archive in archived_derived:
                _replace_exact_file(
                    root / archive.path,
                    root / "reports" / Path(archive.path).name,
                    archive.sha256,
                )
            if archived_material is None:
                if os.path.isfile(native_io_path(canonical_material)):
                    os.unlink(native_io_path(canonical_material))
            else:
                _replace_exact_file(
                    root / archived_material.path,
                    canonical_material,
                    archived_material.sha256,
                )
            if archived_binding is None:
                if os.path.isfile(native_io_path(canonical_binding)):
                    os.unlink(native_io_path(canonical_binding))
            else:
                _replace_exact_file(
                    root / archived_binding.path,
                    canonical_binding,
                    archived_binding.sha256,
                )
            rollback_provenance = [
                approval_artifact,
                repair_plan_artifact,
                preparation_artifact,
                archive_scene,
                archive_modeling,
                archive_blend,
                *archived_derived,
                *([archived_material] if archived_material is not None else []),
                *([archived_binding] if archived_binding is not None else []),
                *([attempted_request] if attempted_request is not None else []),
                *([attempted_result] if attempted_result is not None else []),
                *([attempted_completion] if attempted_completion is not None else []),
            ]
            rollback = MaterialCompletionBindingRepairRollbackReceipt(
                contract_id="item-crystalgun-material-completion-binding-rollback-01",
                job_id=job_id,
                workflow_id=state.workflow_id,
                dispatch_id=state.dispatch_id,
                session_id=session_id,
                input_sha256=stable_json_digest(
                    {item.path: item.sha256 for item in rollback_provenance}
                ),
                source_fingerprint=repair_plan_artifact.sha256,
                producer=_PRODUCER,
                provenance=rollback_provenance,
                created_at=datetime.now(UTC),
                repair_id=str(plan_payload["plan_id"]),
                approval=approval_artifact,
                repair_plan=repair_plan_artifact,
                preparation=preparation_artifact,
                archived_scene_spec=archive_scene,
                archived_modeling_plan=archive_modeling,
                archived_blend=archive_blend,
                archived_derived=archived_derived,
                archived_material_plan=archived_material,
                archived_binding_manifest=archived_binding,
                attempted_controller_request=attempted_request,
                attempted_controller_result=attempted_result,
                attempted_controller_completion=attempted_completion,
                restored_scene_spec_sha256=sha256_file(canonical_scene),
                restored_modeling_plan_sha256=sha256_file(canonical_modeling),
                restored_blend_sha256=sha256_file(canonical_blend),
                failure_type=type(failure).__name__,
                reason=str(failure).replace(str(root), "<job-root>")[:1024],
            )
            _write_or_adopt_v2_model(
                root=root,
                path=rollback_path,
                model=rollback,
                kind="material_completion_binding_repair_rollback_receipt",
            )
            raise RuntimeError(
                "completion binding repair failed and canonical baselines were restored"
            ) from failure
    return {
        "outcome": "material_promoted",
        "controller_request": controller_request_artifact.model_dump(mode="json"),
        "controller_result": controller_result_artifact.model_dump(mode="json"),
        "controller_completion": controller_completion_artifact.model_dump(mode="json"),
        "material_phase_receipt": material_receipt.model_dump(mode="json"),
        "material_phase_receipt_artifact": material_receipt_artifact.model_dump(mode="json"),
        "neutral_preview_report": neutral_report_artifact.model_dump(mode="json"),
        "neutral_preview_image": neutral_image_artifact.model_dump(mode="json"),
        "promotion_receipt": promotion_receipt.model_dump(mode="json"),
        "promotion_receipt_artifact": promotion_receipt_artifact.model_dump(mode="json"),
        "next_state": quality_state.model_dump(mode="json"),
        "next_state_artifact": quality_state_artifact.model_dump(mode="json"),
    }


def expected_material_dependency_closure_retry_approval(
    payload: dict[str, Any],
    plan_sha256: str,
) -> str:
    """Render the sole exact approval for one dependency-complete controller retry."""

    return (
        "APPROVE MATERIAL CONTROLLER DEPENDENCY CLOSURE RETRY "
        f"job_id={payload['job_id']} "
        f"source_session_id={payload['source_session_id']} "
        f"source_aq_state_sha256={payload['source_aq_state_sha256']} "
        "source_completion_binding_plan_sha256="
        f"{payload['source_completion_binding_plan_sha256']} "
        "source_completion_binding_rollback_sha256="
        f"{payload['source_completion_binding_rollback_sha256']} "
        f"source_controller_request_sha256={payload['source_controller_request_sha256']} "
        f"source_controller_result_sha256={payload['source_controller_result_sha256']} "
        "source_controller_completion_sha256="
        f"{payload['source_controller_completion_sha256']} "
        f"source_request_input_map_sha256={payload['source_request_input_map_sha256']} "
        f"missing_dependency_count={payload['missing_dependency_count']} "
        f"dependency_closure_sha256={payload['dependency_closure_sha256']} "
        f"retry_plan_sha256={plan_sha256} "
        f"reference_sha256={payload['reference_sha256']} "
        "new_controller_invocation_allowed=true controller_invocation_limit=1 "
        "execution_id=exec-0011-material-dependency-closure-retry "
        "output_root=production/autonomy_v2/"
        f"{payload['source_session_id']}/controller_outputs/"
        "material_dependency_closure_retry_01 "
        "controller_completion_binding=full_controller_request_input_map "
        "add_missing_material_dependencies_as_immutable_inputs=true "
        "preserve_prior_controller_lifecycles=true "
        "canonical_scene_adoption_before_controller_request=true "
        "canonical_scene_rollback_on_failure=true "
        "canonical_geometry_payload_overwrite=false "
        "preserve_geometry_topology=true preserve_semantic_ids=true "
        "preserve_material_ids=true preserve_imagegen_evidence=true "
        "new_imagegen_invocation_allowed=false new_blender_build_limit=1 "
        "canonical_promotion_limit=1 material_phase_receipt_v2_required=true "
        "neutral_preview_required=true aq_iq_resume_after_promotion=true "
        "scope=append_only_material_dependency_closure_retry_only "
        "delivery_disabled=true optimization_disabled=true lod_disabled=true "
        "collider_disabled=true destination_write_disabled=true"
    )


def prepare_material_dependency_closure_retry_plan(
    job_id: str,
    session_id: str,
    *,
    allow_disabled_experimental: bool = False,
) -> dict[str, Any]:
    """Diagnose the rolled-back request and publish one exact retry approval plan."""

    root = job_dir(job_id).expanduser().resolve()
    session_root = root / "production" / "autonomy_v2" / session_id
    _profile, budget, state, state_artifact = _validate_profile_opt_in(
        root,
        session_root,
        allow_disabled_experimental=allow_disabled_experimental,
        state_sequence=11,
    )
    if (state.phase, state.status, state.next_action) != (
        "authoring",
        "running",
        "validate_candidate",
    ):
        raise ValueError("dependency closure retry source state is not reviewable")
    _validate_exact_hash(root / "input" / "reference.png", _REFERENCE_SHA256, "reference")
    repair_root = session_root / "material_completion_binding_repairs" / "mcbr01"
    source_plan_path = repair_root / "plan.json"
    source_plan_sha256 = sha256_file(source_plan_path)
    if source_plan_sha256 != "87bbe30b489c2525c0cbe7f526839e0338301bbfd5032f2d8837818b61aa388c":
        raise ValueError("completion binding source plan changed")
    rollback_path = (
        session_root / "material_phase" / "completion_binding_repair_0010" / "rollback_receipt.json"
    )
    rollback_sha256 = sha256_file(rollback_path)
    rollback = MaterialCompletionBindingRepairRollbackReceipt.model_validate_json(
        open(native_io_path(rollback_path), "rb").read()
    )
    if (
        not rollback.canonical_restored
        or rollback.failure_type != "MaterialPhaseError"
        or rollback.reason
        != "material shader recipe is not bound as an exact immutable controller input"
    ):
        raise ValueError("dependency closure retry source failure changed")
    execution_root = (
        session_root / "controller_executions" / "exec-0010-material-completion-binding-repair"
    )
    request_path = execution_root / "request.json"
    result_path = execution_root / "result.json"
    request = ControllerExecutionRequest.model_validate_json(
        open(native_io_path(request_path), "rb").read()
    )
    result = ControllerResult.model_validate_json(open(native_io_path(result_path), "rb").read())
    completion_output = next(
        item for item in result.outputs if item.path.endswith("/completion.json")
    )
    material_output = next(
        item for item in result.outputs if item.path.endswith("/material_plan.json")
    )
    completion_path = root / completion_output.path
    completion = MaterialControllerCompletionV2.model_validate_json(
        open(native_io_path(completion_path), "rb").read()
    )
    request_map = {item.path: item.sha256 for item in request.immutable_inputs}
    if completion.immutable_input_sha256 != request_map:
        raise ValueError("dependency closure source completion is not request-bound")
    material_plan = MaterialPlan.model_validate_json(
        open(native_io_path(root / material_output.path), "rb").read()
    )
    required_dependencies: dict[str, str] = {}
    for item in material_plan.materials:
        manifest_value = item.texture_manifest
        if item.shader_recipe is not None:
            recipe_path = resolve_job_path(root, item.shader_recipe, "shader recipe")
            recipe_relative = recipe_path.relative_to(root).as_posix()
            required_dependencies[recipe_relative] = sha256_file(recipe_path)
            recipe = load_shader_recipe(recipe_path)
            manifest_value = manifest_value or recipe.texture_manifest
        if manifest_value is None:
            continue
        manifest, manifest_path = load_material_manifest(
            {"id": item.material_id, "texture_manifest": manifest_value},
            root,
        )
        if manifest is None or manifest_path is None:
            raise ValueError("dependency closure material manifest is missing")
        manifest_relative = manifest_path.relative_to(root).as_posix()
        required_dependencies[manifest_relative] = sha256_file(manifest_path)
        for channel in manifest["channels"].values():
            resolved = channel.get("resolved_path")
            if resolved is None:
                continue
            channel_path = Path(str(resolved))
            channel_relative = channel_path.relative_to(root).as_posix()
            required_dependencies[channel_relative] = sha256_file(channel_path)
    missing_dependencies = {
        path: digest
        for path, digest in sorted(required_dependencies.items())
        if request_map.get(path) != digest
    }
    expected_missing_ids = {
        "material_authoring/codex_imagegen/v05_bridge/runs/"
        "crystal-emission-v05-bridge-mapping-repair-01/mapping_recipe_overrides/"
        "mat.crystal.translucent/shader_recipe.json",
        "material_authoring/codex_imagegen/v05_bridge/runs/"
        "crystal-emission-v05-bridge-mapping-repair-01/mapping_recipe_overrides/"
        "mat.metal.trim/shader_recipe.json",
        f"production/autonomy_v2/{session_id}/codex_imagegen/material_baseline/"
        "recipes/mat.detail.filigree/shader_recipe.json",
        f"production/autonomy_v2/{session_id}/codex_imagegen/material_baseline/"
        "recipes/mat.metal.dark/shader_recipe.json",
    }
    if set(missing_dependencies) != expected_missing_ids:
        raise ValueError("dependency closure missing path set changed")
    source_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "0.1.0",
        "plan_id": "item-crystalgun-material-controller-dependency-closure-retry-01",
        "status": "awaiting_user_approval",
        "approval_granted": False,
        "job_id": job_id,
        "source_session_id": session_id,
        "source_aq_state_sha256": state_artifact.sha256,
        "source_completion_binding_plan_sha256": source_plan_sha256,
        "source_completion_binding_rollback_sha256": rollback_sha256,
        "source_controller_request_sha256": sha256_file(request_path),
        "source_controller_result_sha256": sha256_file(result_path),
        "source_controller_completion_sha256": sha256_file(completion_path),
        "source_request_input_map_sha256": stable_json_digest(request_map),
        "source_request_input_count": len(request_map),
        "missing_dependencies": missing_dependencies,
        "missing_dependency_count": len(missing_dependencies),
        "dependency_closure_sha256": stable_json_digest(missing_dependencies),
        "reference_sha256": _REFERENCE_SHA256,
        "canonical_scene_spec_v02_sha256": source_plan["canonical_scene_spec_v02_sha256"],
        "canonical_modeling_plan_sha256": source_plan["canonical_modeling_plan_sha256"],
        "canonical_blend_sha256": source_plan["canonical_blend_sha256"],
        "candidate_scene_spec_v02_sha256": source_plan["candidate_scene_spec_v02_sha256"],
        "candidate_modeling_plan_sha256": source_plan["candidate_modeling_plan_sha256"],
        "candidate_material_plan_sha256": material_output.sha256,
        "candidate_material_graph_sha256": next(
            item.sha256 for item in result.outputs if item.path.endswith("/material_graph.json")
        ),
        "candidate_blend_sha256": source_plan["candidate_blend_sha256"],
        "material_binding_derivative_sha256": source_plan["material_binding_derivative_sha256"],
        "approved_changes_if_authorized": {
            "preserve_prior_controller_lifecycles": True,
            "new_execution_id": "exec-0011-material-dependency-closure-retry",
            "new_output_root": (
                f"production/autonomy_v2/{session_id}/controller_outputs/"
                "material_dependency_closure_retry_01"
            ),
            "add_missing_material_dependencies_as_immutable_inputs": True,
            "completion_immutable_input_sha256": "full_controller_request_input_map",
            "canonical_scene_adoption_before_controller_request": True,
            "canonical_scene_rollback_on_failure": True,
            "canonical_geometry_payload_overwrite": False,
        },
        "required_lifecycle": {
            "new_controller_invocation_allowed": True,
            "controller_invocation_limit": 1,
            "controller_executor_required": True,
            "new_imagegen_invocation_allowed": False,
            "new_blender_build_limit": 1,
            "canonical_promotion_limit": 1,
            "material_phase_receipt_v2_required": True,
            "neutral_preview_required": True,
            "aq_iq_resume_after_promotion": True,
        },
        "budget_before": state.budget_usage.model_dump(mode="json"),
        "remaining_budget_before": {
            "total_blender_builds": budget.total_blender_builds
            - state.budget_usage.total_blender_builds,
            "controller_invocations": budget.controller_invocations
            - state.budget_usage.controller_invocations,
            "canonical_promotions": budget.canonical_promotions
            - state.budget_usage.canonical_promotions,
            "total_actions": budget.global_action_limit - state.budget_usage.total_actions,
        },
        "preserve_geometry_topology": True,
        "preserve_semantic_ids": True,
        "preserve_material_ids": True,
        "preserve_imagegen_evidence": True,
        "human_reviewed": False,
        "delivery_disabled": True,
        "optimization_disabled": True,
        "lod_disabled": True,
        "collider_disabled": True,
        "destination_write_disabled": True,
        "scope": "append_only_material_dependency_closure_retry_only",
    }
    retry_root = session_root / "material_controller_dependency_closure_retries" / "mcdcr01"
    retry_plan_path = retry_root / "plan.json"
    _write_json_object(retry_plan_path, payload)
    retry_plan_sha256 = sha256_file(retry_plan_path)
    return {
        "outcome": "awaiting_material_controller_dependency_closure_approval",
        "plan_path": retry_plan_path.relative_to(root).as_posix(),
        "plan_sha256": retry_plan_sha256,
        "plan": payload,
        "exact_approval": expected_material_dependency_closure_retry_approval(
            payload,
            retry_plan_sha256,
        ),
    }
