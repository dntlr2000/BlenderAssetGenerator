"""Strict AQ v2 geometry-controller validation and promotion evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..stabilization.models import JobId, PortableId, Sha256, WorkflowId
from .models import (
    AQV2Artifact,
    AQV2Evidence,
    AQV2StrictModel,
    BudgetUsageV2,
)


class GeometryAuthoringOutputBindingV2(AQV2StrictModel):
    """Bind one controller-authored sibling output by fixed leaf name and exact bytes."""

    name: Literal["modeling_plan.json", "scene_spec_v03.json"]
    sha256: Sha256
    byte_size: int = Field(gt=0)


class GeometryAuthoringCompletionV2(AQV2StrictModel):
    """Let a geometry controller close only its exact isolated output set."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    phase: Literal["geometry_authoring"] = "geometry_authoring"
    status: Literal["completed"] = "completed"
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    execution_id: PortableId
    assignment_sha256: Sha256
    tool_profile_sha256: Sha256
    outputs: list[GeometryAuthoringOutputBindingV2] = Field(min_length=2, max_length=2)
    canonical_write_requested: Literal[False] = False
    destination_project_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_siblings(self) -> GeometryAuthoringCompletionV2:
        """Require each non-marker geometry output exactly once in deterministic order."""

        names = [item.name for item in self.outputs]
        expected = ["modeling_plan.json", "scene_spec_v03.json"]
        if names != expected:
            raise ValueError(
                "geometry completion outputs must be modeling_plan.json then "
                "scene_spec_v03.json"
            )
        return self


class GeometryCandidateValidationReceiptV2(AQV2Evidence):
    """Bind one host-only validated candidate and its atomic canonical promotion."""

    receipt_id: PortableId
    root_authorization: AQV2Artifact
    controller_result: AQV2Artifact
    controller_request: AQV2Artifact
    phase_tool_profile: AQV2Artifact
    controller_completion: AQV2Artifact
    candidate_modeling_plan: AQV2Artifact
    candidate_scene_spec_v03: AQV2Artifact
    compiled_scene_spec: AQV2Artifact
    structural_recipes: list[AQV2Artifact] = Field(min_length=1)
    mesh_payloads_v02: list[AQV2Artifact] = Field(min_length=1)
    materialization_receipts: list[AQV2Artifact] = Field(min_length=1)
    materialization_blends: list[AQV2Artifact] = Field(min_length=1)
    candidate_build_provenance: AQV2Artifact
    candidate_blend: AQV2Artifact
    candidate_inventory: AQV2Artifact
    candidate_validation: AQV2Artifact
    candidate_geometry_snapshot: AQV2Artifact
    previous_modeling_plan_sha256: Sha256 | None
    previous_scene_spec_sha256: Sha256 | None
    previous_blend_sha256: Sha256 | None
    canonical_archives: list[AQV2Artifact]
    canonical_modeling_plan: AQV2Artifact
    canonical_scene_spec: AQV2Artifact
    canonical_blend: AQV2Artifact
    canonical_geometry_snapshot: AQV2Artifact
    geometry_intent_survival: AQV2Artifact
    reference_content_scope: Literal["primary_object_only"] = "primary_object_only"
    target_subject: str = Field(min_length=1, max_length=256)
    budget_usage_after: BudgetUsageV2
    status: Literal["passed"] = "passed"
    canonical_writer: Literal["supervisor_host"] = "supervisor_host"
    controller_canonical_write: Literal[False] = False
    destination_project_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_bound_promotion(self) -> GeometryCandidateValidationReceiptV2:
        """Require byte-identical candidate promotion and complete receipt provenance."""

        if self.candidate_modeling_plan.sha256 != self.canonical_modeling_plan.sha256:
            raise ValueError("canonical ModelingPlan differs from the validated candidate")
        if self.compiled_scene_spec.sha256 != self.canonical_scene_spec.sha256:
            raise ValueError("canonical SceneSpec differs from the validated candidate")
        if self.candidate_blend.sha256 != self.canonical_blend.sha256:
            raise ValueError("canonical blend differs from the validated candidate")
        named = [
            self.root_authorization,
            self.controller_result,
            self.controller_request,
            self.phase_tool_profile,
            self.controller_completion,
            self.candidate_modeling_plan,
            self.candidate_scene_spec_v03,
            self.compiled_scene_spec,
            *self.structural_recipes,
            *self.mesh_payloads_v02,
            *self.materialization_receipts,
            *self.materialization_blends,
            self.candidate_build_provenance,
            self.candidate_blend,
            self.candidate_inventory,
            self.candidate_validation,
            self.candidate_geometry_snapshot,
            *self.canonical_archives,
            self.canonical_modeling_plan,
            self.canonical_scene_spec,
            self.canonical_blend,
            self.canonical_geometry_snapshot,
            self.geometry_intent_survival,
        ]
        provenance = {(item.path, item.sha256) for item in self.provenance}
        if any((item.path, item.sha256) not in provenance for item in named):
            raise ValueError(
                "geometry validation receipt must bind every named artifact in provenance"
            )
        return self
