"""Strict additive contracts for the Codex ImageGen material-loop companion."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..blender_artifacts import stable_json_digest
from ..stabilization.models import PortableId, RelativePath, Sha256
from .models import (
    CodexImageArtifact,
    CodexImageEvidenceEnvelope,
    CodexImageStrictModel,
    DirectOutputRole,
)

MATERIAL_LOOP_SCHEMA_VERSION = "0.1.0"

MaterialLoopStatus = Literal[
    "controller_promotion_required",
    "promoting_material",
    "material_promoted",
    "waiting_for_quality",
    "quality_approved",
    "review_required",
    "blocked",
    "failed",
    "cancelled",
]
NormalizationOperation = Literal[
    "pass_through",
    "center_crop",
    "contain_pad",
    "tile_crop",
    "review_required",
]
NormalizationPreference = Literal["center_crop", "contain_pad", "tile_crop"]
SemanticReviewOutcome = Literal["passed", "review_required", "failed", "unavailable"]
MaterialRoleSuitability = Literal["suitable", "unsuitable", "review_required"]
CompanionSelectionOutcome = Literal[
    "selected",
    "no_eligible_candidate",
    "review_required",
]
SemanticReviewCategory = Literal[
    "unwanted_text",
    "unwanted_object_or_background",
    "material_family_suitability",
    "signage_or_decal_suitability",
    "wood_grain_naturalness",
    "decorative_pattern_asset_suitability",
    "crystal_or_energy_pattern_suitability",
    "reference_style_alignment",
    "repeat_or_tile_suitability",
    "lighting_hotspot",
    "perspective_distortion",
    "boundary_contamination",
]

ALL_SEMANTIC_REVIEW_CATEGORIES: tuple[str, ...] = (
    "unwanted_text",
    "unwanted_object_or_background",
    "material_family_suitability",
    "signage_or_decal_suitability",
    "wood_grain_naturalness",
    "decorative_pattern_asset_suitability",
    "crystal_or_energy_pattern_suitability",
    "reference_style_alignment",
    "repeat_or_tile_suitability",
    "lighting_hotspot",
    "perspective_distortion",
    "boundary_contamination",
)
HARD_FAILURE_SEMANTIC_CATEGORIES: frozenset[str] = frozenset(
    {"unwanted_text", "unwanted_object_or_background", "boundary_contamination"}
)
EXPECTED_MATERIAL_CONTROLLER_OUTPUT_NAMES: frozenset[str] = frozenset(
    {"material_plan.json", "material_graph.json", "completion.json"}
)

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
MaterialId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]


class ImageMaterialLoopEvidence(CodexImageEvidenceEnvelope):
    """Add an explicit immutable marker to the existing exact ImageGen envelope."""

    schema_version: Literal["0.1.0"] = MATERIAL_LOOP_SCHEMA_VERSION
    immutable: Literal[True] = True


class MaterialLoopRasterSize(CodexImageStrictModel):
    """Describe one bounded native or material raster size."""

    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)


class ImageGenCropRectangle(CodexImageStrictModel):
    """Record one source-pixel crop rectangle using a top-left origin."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)


class ImageGenPadding(CodexImageStrictModel):
    """Record exact output-pixel padding around contain-resized content."""

    left: int = Field(ge=0, le=8192)
    top: int = Field(ge=0, le=8192)
    right: int = Field(ge=0, le=8192)
    bottom: int = Field(ge=0, le=8192)


class ImageMaterialLoopBudgetUsage(CodexImageStrictModel):
    """Record monotonic companion operations without changing the base AQ budget."""

    normalization_runs: int = Field(default=0, ge=0, le=1)
    semantic_reviews: int = Field(default=0, ge=0, le=1)
    controller_invocations: int = Field(default=0, ge=0, le=1)
    promotions_consumed: int = Field(default=0, ge=0, le=1)


class CodexImageSemanticCheck(CodexImageStrictModel):
    """Store one bounded visual observation without human-review or truth authority."""

    category: SemanticReviewCategory
    outcome: SemanticReviewOutcome
    confidence: UnitInterval
    rationale: str = Field(min_length=1, max_length=1024)
    explicit_forbidden_content: bool = False

    @model_validator(mode="after")
    def validate_failure_scope(self) -> CodexImageSemanticCheck:
        """Reserve hard failure for explicit forbidden-content observations."""

        if self.outcome == "failed":
            if self.category not in HARD_FAILURE_SEMANTIC_CATEGORIES:
                raise ValueError("aesthetic or suitability observations cannot hard-fail")
            if not self.explicit_forbidden_content:
                raise ValueError("semantic failure requires explicit forbidden content")
        elif self.explicit_forbidden_content:
            raise ValueError("explicit forbidden content must produce a failed outcome")
        return self


class CodexImageV05ExactAdoptionPreflightReceipt(ImageMaterialLoopEvidence):
    """Bind an actual Blender compile of exact V0.5 graph bytes in an isolated shadow."""

    preflight_id: PortableId
    v05_bridge_receipt: CodexImageArtifact
    candidate_material_plan: CodexImageArtifact
    material_graph_spec: CodexImageArtifact
    shadow_root: RelativePath
    shadow_candidate_material_plan: CodexImageArtifact
    shadow_material_graph_spec: CodexImageArtifact
    compile_run_root: RelativePath
    graph_compile_report: CodexImageArtifact
    compile_artifacts: list[CodexImageArtifact] = Field(min_length=8, max_length=8)
    material_id: MaterialId
    graph_id: PortableId
    status: Literal["passed"] = "passed"
    actual_blender_compiled: Literal[True] = True
    exact_graph_bytes_compiled: Literal[True] = True
    candidate_material_bytes_shadowed: Literal[True] = True
    staging_receipt_reinterpreted: Literal[False] = False
    controller_result_created: Literal[False] = False
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_adoption_preflight(
        self,
    ) -> CodexImageV05ExactAdoptionPreflightReceipt:
        """Require canonical shadow paths, byte identity, and complete compile provenance."""

        if self.contract_id != self.preflight_id:
            raise ValueError("exact-adoption preflight contract_id must equal preflight_id")
        expected_root = codex_image_v05_exact_adoption_preflight_root_path(
            self.session_id,
            self.preflight_id,
        )
        expected_shadow = f"{expected_root}/shadow_job"
        if self.shadow_root != expected_shadow:
            raise ValueError("exact-adoption preflight shadow root is not canonical")
        if not self.shadow_candidate_material_plan.path.startswith(
            f"{expected_shadow}/"
        ) or not self.shadow_material_graph_spec.path.startswith(f"{expected_shadow}/"):
            raise ValueError("exact-adoption shadow inputs escape the canonical shadow root")
        if (
            self.shadow_candidate_material_plan.sha256,
            self.shadow_candidate_material_plan.byte_size,
            self.shadow_candidate_material_plan.media_type,
        ) != (
            self.candidate_material_plan.sha256,
            self.candidate_material_plan.byte_size,
            self.candidate_material_plan.media_type,
        ):
            raise ValueError("shadow MaterialPlan differs from exact candidate bytes")
        if (
            self.shadow_material_graph_spec.sha256,
            self.shadow_material_graph_spec.byte_size,
            self.shadow_material_graph_spec.media_type,
        ) != (
            self.material_graph_spec.sha256,
            self.material_graph_spec.byte_size,
            self.material_graph_spec.media_type,
        ):
            raise ValueError("shadow MaterialGraph differs from exact candidate bytes")
        if len({item.path for item in self.compile_artifacts}) != len(
            self.compile_artifacts
        ):
            raise ValueError("exact-adoption compile artifacts must use unique paths")
        compile_prefix = f"{expected_shadow}/{self.compile_run_root.rstrip('/')}/"
        if self.graph_compile_report.path != f"{compile_prefix}compile_report.json":
            raise ValueError("exact-adoption compile report path is not canonical")
        if any(not item.path.startswith(compile_prefix) for item in self.compile_artifacts):
            raise ValueError("exact-adoption compile artifacts escape their run root")
        artifacts = _unique_artifact_bindings(
            [
                self.v05_bridge_receipt,
                self.candidate_material_plan,
                self.material_graph_spec,
                self.shadow_candidate_material_plan,
                self.shadow_material_graph_spec,
                self.graph_compile_report,
                *self.compile_artifacts,
            ]
        )
        _require_exact_provenance(
            self.provenance,
            artifacts,
            "exact-adoption preflight receipt",
        )
        expected_input = exact_adoption_preflight_input_sha256(
            v05_bridge_receipt=self.v05_bridge_receipt,
            candidate_material_plan=self.candidate_material_plan,
            material_graph_spec=self.material_graph_spec,
            shadow_root=self.shadow_root,
            shadow_candidate_material_plan=self.shadow_candidate_material_plan,
            shadow_material_graph_spec=self.shadow_material_graph_spec,
            compile_run_root=self.compile_run_root,
            graph_compile_report=self.graph_compile_report,
            compile_artifacts=self.compile_artifacts,
            material_id=self.material_id,
            graph_id=self.graph_id,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("exact-adoption preflight input digest is inconsistent")
        if self.source_fingerprint != self.material_graph_spec.sha256:
            raise ValueError("exact-adoption preflight source must equal the graph bytes")
        return self


class ImageGeneratedMaterialBridgePlan(ImageMaterialLoopEvidence):
    """Freeze the exact staging evidence and authority ceiling for one material bridge."""

    base_aq_session_id: PortableId
    selected_candidate_id: PortableId
    material_authoring_run_id: PortableId
    material_controller_request_id: PortableId
    root_authorization: CodexImageArtifact
    aq_plan: CodexImageArtifact
    aq_profile: CodexImageArtifact
    aq_budget: CodexImageArtifact
    current_state: CodexImageArtifact
    canonical_scene_spec: CodexImageArtifact
    geometry_validation_receipt: CodexImageArtifact
    current_build_provenance: CodexImageArtifact
    provider_profile: CodexImageArtifact
    imagegen_plan: CodexImageArtifact
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    generation_terminal: CodexImageArtifact
    selected_candidate: CodexImageArtifact
    generated_image_evidence: CodexImageArtifact
    quality_report: CodexImageArtifact
    selection: CodexImageArtifact
    companion_selection_receipt: CodexImageArtifact | None = None
    native_core_preparation_receipt: CodexImageArtifact | None = None
    semantic_review: CodexImageArtifact
    normalization_receipt: CodexImageArtifact
    adoption: CodexImageArtifact
    material_authoring_request: CodexImageArtifact
    material_authoring_manifest: CodexImageArtifact
    material_authoring_receipt: CodexImageArtifact
    v05_bridge_receipt: CodexImageArtifact
    exact_adoption_preflight: CodexImageArtifact | None = None
    v05_controller_inputs: list[CodexImageArtifact] = Field(min_length=1)
    texture_outputs: list[CodexImageArtifact] = Field(min_length=1)
    candidate_material_plan: CodexImageArtifact
    material_graph_spec: CodexImageArtifact
    shader_recipes: list[CodexImageArtifact] = Field(min_length=1)
    texture_manifests: list[CodexImageArtifact] = Field(min_length=1)
    canonical_material_observation: CodexImageArtifact | None = None
    previous_material_plan: CodexImageArtifact | None = None
    canonical_material_absence_evidence: CodexImageArtifact | None = None
    canonical_scene_spec_sha256: Sha256
    geometry_build_fingerprint: Sha256
    uv_fingerprint: Sha256
    target_material_ids: list[MaterialId] = Field(min_length=1)
    target_semantic_ids: list[MaterialId] = Field(min_length=1)
    mutable_material_ids: list[MaterialId] = Field(min_length=1)
    immutable_material_ids: list[MaterialId] = Field(default_factory=list)
    requested_delivery_profiles: list[
        Literal["none", "review_only", "portable_gltf", "portable_fbx"]
    ] = Field(default_factory=lambda: ["none"], min_length=1, max_length=2)
    execution_mode: Literal["exact_adoption", "controller_authored_completion"]
    output_root: RelativePath
    allowed_output_paths: list[RelativePath] = Field(min_length=3, max_length=3)
    expected_output_sha256: dict[RelativePath, Sha256] = Field(default_factory=dict)
    geometry_changes_allowed: Literal[False] = False
    semantic_id_changes_allowed: Literal[False] = False
    canonical_write_authority: Literal["material_phase_service_only"] = (
        "material_phase_service_only"
    )
    destination_write_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_bridge_boundary(self) -> ImageGeneratedMaterialBridgePlan:
        """Require exact baselines, scoped IDs, controller outputs, and provenance."""

        _validate_material_baseline(
            self.previous_material_plan,
            self.canonical_material_absence_evidence,
        )
        _validate_material_observation(
            self.canonical_material_observation,
            self.previous_material_plan,
            self.canonical_material_absence_evidence,
        )
        _validate_id_scope(
            self.target_material_ids,
            self.mutable_material_ids,
            self.immutable_material_ids,
        )
        if len(self.target_semantic_ids) != len(set(self.target_semantic_ids)):
            raise ValueError("target semantic IDs must be unique")
        _validate_requested_delivery_profiles(self.requested_delivery_profiles)
        _require_unique_artifact_sequence(
            self.v05_controller_inputs,
            "V0.5 controller inputs",
        )
        _validate_controller_outputs(
            self.output_root,
            self.allowed_output_paths,
            self.expected_output_sha256,
            require_expected=self.execution_mode == "exact_adoption",
        )
        if (self.execution_mode == "exact_adoption") != (
            self.exact_adoption_preflight is not None
        ):
            raise ValueError(
                "exact adoption requires one preflight receipt; authored completion forbids it"
            )
        if self.canonical_scene_spec_sha256 != self.canonical_scene_spec.sha256:
            raise ValueError("bridge canonical SceneSpec hash is inconsistent")
        artifacts = [
            self.root_authorization,
            self.aq_plan,
            self.aq_profile,
            self.aq_budget,
            self.current_state,
            self.canonical_scene_spec,
            self.geometry_validation_receipt,
            self.current_build_provenance,
            self.provider_profile,
            self.imagegen_plan,
            self.assignment,
            self.completion,
            self.generation_terminal,
            self.selected_candidate,
            self.generated_image_evidence,
            self.quality_report,
            self.selection,
            *(
                [self.companion_selection_receipt]
                if self.companion_selection_receipt
                else []
            ),
            *(
                [self.native_core_preparation_receipt]
                if self.native_core_preparation_receipt
                else []
            ),
            self.semantic_review,
            self.normalization_receipt,
            self.adoption,
            self.material_authoring_request,
            self.material_authoring_manifest,
            self.material_authoring_receipt,
            self.v05_bridge_receipt,
            *(
                [self.exact_adoption_preflight]
                if self.exact_adoption_preflight
                else []
            ),
            *self.texture_outputs,
            self.candidate_material_plan,
            self.material_graph_spec,
            *self.shader_recipes,
            *self.texture_manifests,
            *(
                [self.canonical_material_observation]
                if self.canonical_material_observation
                else []
            ),
            *([self.previous_material_plan] if self.previous_material_plan else []),
            *(
                [self.canonical_material_absence_evidence]
                if self.canonical_material_absence_evidence
                else []
            ),
        ]
        artifacts = _merge_exact_artifact_aliases(
            artifacts,
            self.v05_controller_inputs,
            "material bridge V0.5 controller inputs",
        )
        _require_exact_provenance(self.provenance, artifacts, "material bridge plan")
        if self.input_sha256 != stable_json_digest(
            {item.path: item.sha256 for item in artifacts}
        ):
            raise ValueError("material bridge plan input digest is inconsistent")
        return self


class ImageGeneratedMaterialControllerInput(ImageMaterialLoopEvidence):
    """Bind an ImageGen staging candidate to one request-owned material execution."""

    bridge_plan: CodexImageArtifact
    current_state: CodexImageArtifact
    phase_tool_profile: CodexImageArtifact
    root_authorization: CodexImageArtifact
    aq_plan: CodexImageArtifact
    aq_profile: CodexImageArtifact
    aq_budget: CodexImageArtifact
    canonical_scene_spec: CodexImageArtifact
    geometry_validation_receipt: CodexImageArtifact
    current_build_provenance: CodexImageArtifact
    provider_profile: CodexImageArtifact
    generation_terminal: CodexImageArtifact
    selected_candidate: CodexImageArtifact
    generated_image_evidence: CodexImageArtifact
    quality_report: CodexImageArtifact
    selection: CodexImageArtifact
    companion_selection_receipt: CodexImageArtifact | None = None
    native_core_preparation_receipt: CodexImageArtifact | None = None
    semantic_review: CodexImageArtifact
    normalization_receipt: CodexImageArtifact
    adoption: CodexImageArtifact
    material_authoring_request: CodexImageArtifact
    material_authoring_manifest: CodexImageArtifact
    material_authoring_receipt: CodexImageArtifact
    v05_bridge_receipt: CodexImageArtifact
    exact_adoption_preflight: CodexImageArtifact | None = None
    v05_controller_inputs: list[CodexImageArtifact] = Field(min_length=1)
    texture_outputs: list[CodexImageArtifact] = Field(min_length=1)
    candidate_material_plan: CodexImageArtifact
    material_graph_spec: CodexImageArtifact
    shader_recipes: list[CodexImageArtifact] = Field(min_length=1)
    texture_manifests: list[CodexImageArtifact] = Field(min_length=1)
    canonical_material_observation: CodexImageArtifact | None = None
    previous_material_plan: CodexImageArtifact | None = None
    canonical_material_absence_evidence: CodexImageArtifact | None = None
    immutable_input_sha256: dict[RelativePath, Sha256] = Field(min_length=1)
    source_scene_spec_sha256: Sha256
    source_material_plan_sha256: Sha256 | None = None
    uv_fingerprint: Sha256
    target_material_ids: list[MaterialId] = Field(min_length=1)
    target_semantic_ids: list[MaterialId] = Field(min_length=1)
    execution_mode: Literal["exact_adoption", "controller_authored_completion"]
    output_root: RelativePath
    allowed_output_paths: list[RelativePath] = Field(min_length=3, max_length=3)
    expected_output_sha256: dict[RelativePath, Sha256] = Field(default_factory=dict)
    invocation_budget: Literal[1] = 1
    canonical_write_authority: Literal["material_phase_service_only"] = (
        "material_phase_service_only"
    )

    @model_validator(mode="after")
    def validate_controller_input(self) -> ImageGeneratedMaterialControllerInput:
        """Require exact immutable maps and the existing material-output boundary."""

        _validate_material_baseline(
            self.previous_material_plan,
            self.canonical_material_absence_evidence,
        )
        _validate_material_observation(
            self.canonical_material_observation,
            self.previous_material_plan,
            self.canonical_material_absence_evidence,
        )
        _validate_controller_outputs(
            self.output_root,
            self.allowed_output_paths,
            self.expected_output_sha256,
            require_expected=self.execution_mode == "exact_adoption",
        )
        if (self.execution_mode == "exact_adoption") != (
            self.exact_adoption_preflight is not None
        ):
            raise ValueError(
                "exact-adoption controller input requires its one preflight receipt"
            )
        _require_unique_artifact_sequence(
            self.v05_controller_inputs,
            "V0.5 controller inputs",
        )
        artifacts = [
            self.bridge_plan,
            self.current_state,
            self.phase_tool_profile,
            self.root_authorization,
            self.aq_plan,
            self.aq_profile,
            self.aq_budget,
            self.canonical_scene_spec,
            self.geometry_validation_receipt,
            self.current_build_provenance,
            self.provider_profile,
            self.generation_terminal,
            self.selected_candidate,
            self.generated_image_evidence,
            self.quality_report,
            self.selection,
            *(
                [self.companion_selection_receipt]
                if self.companion_selection_receipt
                else []
            ),
            *(
                [self.native_core_preparation_receipt]
                if self.native_core_preparation_receipt
                else []
            ),
            self.semantic_review,
            self.normalization_receipt,
            self.adoption,
            self.material_authoring_request,
            self.material_authoring_manifest,
            self.material_authoring_receipt,
            self.v05_bridge_receipt,
            *(
                [self.exact_adoption_preflight]
                if self.exact_adoption_preflight
                else []
            ),
            *self.texture_outputs,
            self.candidate_material_plan,
            self.material_graph_spec,
            *self.shader_recipes,
            *self.texture_manifests,
            *(
                [self.canonical_material_observation]
                if self.canonical_material_observation
                else []
            ),
            *([self.previous_material_plan] if self.previous_material_plan else []),
            *(
                [self.canonical_material_absence_evidence]
                if self.canonical_material_absence_evidence
                else []
            ),
        ]
        artifacts = _merge_exact_artifact_aliases(
            artifacts,
            self.v05_controller_inputs,
            "material controller V0.5 inputs",
        )
        _require_exact_artifact_map(self.immutable_input_sha256, artifacts)
        _require_exact_provenance(self.provenance, artifacts, "material controller input")
        if self.input_sha256 != stable_json_digest(self.immutable_input_sha256):
            raise ValueError("material controller input digest is inconsistent")
        if self.source_scene_spec_sha256 != self.canonical_scene_spec.sha256:
            raise ValueError("controller input SceneSpec hash is inconsistent")
        expected_material = (
            self.previous_material_plan.sha256 if self.previous_material_plan else None
        )
        if self.source_material_plan_sha256 != expected_material:
            raise ValueError("controller input MaterialPlan baseline is inconsistent")
        return self


class ImageGeneratedMaterialControllerBinding(ImageMaterialLoopEvidence):
    """Bind the companion controller input to a formal ControllerExecutionRequest."""

    bridge_plan: CodexImageArtifact
    controller_input: CodexImageArtifact
    controller_execution_request: CodexImageArtifact
    phase_tool_profile: CodexImageArtifact
    execution_id: PortableId
    immutable_input_sha256: dict[RelativePath, Sha256] = Field(min_length=1)
    allowed_output_paths: list[RelativePath] = Field(min_length=3, max_length=3)
    expected_output_sha256: dict[RelativePath, Sha256] = Field(default_factory=dict)
    controller_request_sha256: Sha256
    producer_required: Literal[
        "codex_blender_modeler.production.controller_executor.service"
    ] = (
        "codex_blender_modeler.production.controller_executor.service"
    )
    handwritten_result_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_controller_binding(self) -> ImageGeneratedMaterialControllerBinding:
        """Require the request digest, immutable inputs, and provenance to agree."""

        artifacts = [
            self.bridge_plan,
            self.controller_input,
            self.controller_execution_request,
            self.phase_tool_profile,
        ]
        _require_exact_provenance(self.provenance, artifacts, "material controller binding")
        if self.controller_request_sha256 != self.controller_execution_request.sha256:
            raise ValueError("controller binding request hash is inconsistent")
        if self.immutable_input_sha256.get(self.bridge_plan.path) != self.bridge_plan.sha256:
            raise ValueError("controller binding omits the exact bridge plan")
        if (
            self.immutable_input_sha256.get(self.controller_input.path)
            != self.controller_input.sha256
        ):
            raise ValueError("controller binding omits the exact controller input")
        if len(self.allowed_output_paths) != len(set(self.allowed_output_paths)):
            raise ValueError("controller binding output paths must be unique")
        if {
            item.rsplit("/", 1)[-1] for item in self.allowed_output_paths
        } != EXPECTED_MATERIAL_CONTROLLER_OUTPUT_NAMES:
            raise ValueError("controller binding output set is not the material profile set")
        if set(self.expected_output_sha256) - set(self.allowed_output_paths):
            raise ValueError("controller binding expected hashes escape declared outputs")
        expected_input = stable_json_digest(
            {
                "request": self.controller_execution_request.sha256,
                "inputs": self.immutable_input_sha256,
            }
        )
        if self.input_sha256 != expected_input:
            raise ValueError("material controller binding input digest is inconsistent")
        return self


class ImageGeneratedMaterialPromotionReceipt(ImageMaterialLoopEvidence):
    """Join the ImageGen companion chain to a real host MaterialPhaseReceiptV2."""

    bridge_plan: CodexImageArtifact
    controller_input: CodexImageArtifact
    controller_binding: CodexImageArtifact
    controller_execution_request: CodexImageArtifact
    controller_result: CodexImageArtifact
    material_phase_receipt: CodexImageArtifact
    promoted_base_state: CodexImageArtifact
    generation_terminal: CodexImageArtifact
    selection: CodexImageArtifact
    companion_selection_receipt: CodexImageArtifact | None = None
    native_core_preparation_receipt: CodexImageArtifact | None = None
    generated_image_evidence: CodexImageArtifact
    semantic_review: CodexImageArtifact
    normalization_receipt: CodexImageArtifact
    adoption: CodexImageArtifact
    material_authoring_manifest: CodexImageArtifact
    material_authoring_receipt: CodexImageArtifact
    exact_adoption_preflight: CodexImageArtifact | None = None
    graph_compile_report: CodexImageArtifact
    material_validation: CodexImageArtifact
    neutral_preview: CodexImageArtifact
    neutral_preview_manifest: CodexImageArtifact
    neutral_preview_image: CodexImageArtifact
    reference_preview_manifest: CodexImageArtifact | None = None
    reference_preview_image: CodexImageArtifact | None = None
    canonical_material_snapshot: CodexImageArtifact
    canonical_scene_snapshot: CodexImageArtifact
    canonical_material_plan_sha256: Sha256
    canonical_scene_spec_sha256: Sha256
    status: Literal["promoted"] = "promoted"
    material_phase_service_used: Literal[True] = True
    canonical_write_authority: Literal["material_phase_service_only"] = (
        "material_phase_service_only"
    )
    duplicate_consumption_prevented: Literal[True] = True

    @model_validator(mode="after")
    def validate_promotion_receipt(self) -> ImageGeneratedMaterialPromotionReceipt:
        """Require real controller, compile, canonical, and host-promotion evidence."""

        artifacts = [
            self.bridge_plan,
            self.controller_input,
            self.controller_binding,
            self.controller_execution_request,
            self.controller_result,
            self.material_phase_receipt,
            self.promoted_base_state,
            self.generation_terminal,
            self.selection,
            *(
                [self.companion_selection_receipt]
                if self.companion_selection_receipt
                else []
            ),
            *(
                [self.native_core_preparation_receipt]
                if self.native_core_preparation_receipt
                else []
            ),
            self.generated_image_evidence,
            self.semantic_review,
            self.normalization_receipt,
            self.adoption,
            self.material_authoring_manifest,
            self.material_authoring_receipt,
            *(
                [self.exact_adoption_preflight]
                if self.exact_adoption_preflight
                else []
            ),
            self.graph_compile_report,
            self.material_validation,
            self.neutral_preview,
            self.neutral_preview_manifest,
            self.neutral_preview_image,
            *([self.reference_preview_manifest] if self.reference_preview_manifest else []),
            *([self.reference_preview_image] if self.reference_preview_image else []),
            self.canonical_material_snapshot,
            self.canonical_scene_snapshot,
        ]
        _require_exact_provenance(self.provenance, artifacts, "material promotion receipt")
        if self.input_sha256 != stable_json_digest(
            {item.path: item.sha256 for item in artifacts}
        ):
            raise ValueError("material promotion receipt input digest is inconsistent")
        if self.canonical_material_plan_sha256 != self.canonical_material_snapshot.sha256:
            raise ValueError("promotion canonical MaterialPlan hash is inconsistent")
        if self.canonical_scene_spec_sha256 != self.canonical_scene_snapshot.sha256:
            raise ValueError("promotion canonical SceneSpec hash is inconsistent")
        if (self.reference_preview_manifest is None) != (
            self.reference_preview_image is None
        ):
            raise ValueError("reference preview manifest and image must be present together")
        return self


class ImageGeneratedMaterialNeutralPreview(ImageMaterialLoopEvidence):
    """Bind a fixed Blender material-swatch render to exact promoted source evidence."""

    material_phase_receipt: CodexImageArtifact
    authoring_blend: CodexImageArtifact
    renderer_script: CodexImageArtifact
    raw_swatch_manifest: CodexImageArtifact
    preview_image: CodexImageArtifact
    material_id: MaterialId
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    preview_image_path: RelativePath
    preview_image_sha256: Sha256
    preview_image_byte_size: int = Field(gt=0)
    renderer: Literal["fixed_blender_material_swatch_v1"] = (
        "fixed_blender_material_swatch_v1"
    )
    actual_blender_rendered: Literal[True] = True
    human_reviewed: Literal[False] = False
    reference_matched: Literal[False] = False
    canonical_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_neutral_preview(self) -> ImageGeneratedMaterialNeutralPreview:
        """Require the rendered image cross-binding and exact five-artifact provenance."""

        _require_exact_provenance(
            self.provenance,
            [
                self.material_phase_receipt,
                self.authoring_blend,
                self.renderer_script,
                self.raw_swatch_manifest,
                self.preview_image,
            ],
            "material neutral preview",
        )
        if (
            self.preview_image_path,
            self.preview_image_sha256,
            self.preview_image_byte_size,
        ) != (
            self.preview_image.path,
            self.preview_image.sha256,
            self.preview_image.byte_size,
        ):
            raise ValueError("neutral preview image binding is inconsistent")
        if self.preview_image.media_type != "image/png":
            raise ValueError("neutral material preview must use PNG evidence")
        if self.source_fingerprint != self.material_phase_receipt.sha256:
            raise ValueError("neutral preview source must be the MaterialPhaseReceiptV2")
        expected_input = stable_json_digest(
            {
                "material_phase_receipt": self.material_phase_receipt.model_dump(
                    mode="json"
                ),
                "renderer_script": self.renderer_script.model_dump(mode="json"),
                "material_id": self.material_id,
                "size": self.width,
            }
        )
        if self.input_sha256 != expected_input:
            raise ValueError("neutral material preview input digest is inconsistent")
        return self


class CodexImageNativeOutputAdoptionReceipt(ImageMaterialLoopEvidence):
    """Bind one native controller PNG before any core 0.1 size validation."""

    native_output_id: PortableId
    assignment: CodexImageArtifact
    assignment_id: PortableId
    ordinal: int = Field(ge=0, le=2)
    output_role: DirectOutputRole
    expected_assignment_size: MaterialLoopRasterSize
    native_size: MaterialLoopRasterSize
    original_image: CodexImageArtifact
    source_mode: Literal["L", "LA", "RGB", "RGBA", "P"]
    source_has_alpha: bool
    source_icc_profile_sha256: Sha256 | None = None
    source_format: Literal["png"] = "png"
    status: Literal["adopted"] = "adopted"
    original_source_path_persisted: Literal[False] = False
    source_preserved: Literal[True] = True
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False
    human_reviewed: Literal[False] = False

    @model_validator(mode="after")
    def validate_native_output_adoption(self) -> CodexImageNativeOutputAdoptionReceipt:
        """Require the canonical original leaf, exact digest, and complete provenance."""

        expected_path = codex_image_native_output_original_path(
            self.session_id,
            self.assignment_id,
            self.native_output_id,
        )
        if self.original_image.path != expected_path:
            raise ValueError("native ImageGen original is outside its run-owned leaf")
        if (
            self.original_image.media_type != "image/png"
            or not self.original_image.path.casefold().endswith(".png")
        ):
            raise ValueError("native ImageGen original must be an exact PNG artifact")
        if (
            self.original_image.artifact_id
            != codex_image_native_output_original_artifact_id(self.native_output_id)
            or self.original_image.kind != "codex-imagegen-native-original"
        ):
            raise ValueError("native ImageGen original artifact identity is inconsistent")
        if self.source_fingerprint != self.original_image.sha256:
            raise ValueError("native output source fingerprint must equal original bytes")
        expected_input = codex_image_native_output_adoption_input_sha256(
            assignment=self.assignment,
            assignment_id=self.assignment_id,
            native_output_id=self.native_output_id,
            ordinal=self.ordinal,
            output_role=self.output_role,
            expected_assignment_size=self.expected_assignment_size,
            native_size=self.native_size,
            original_image=self.original_image,
            source_mode=self.source_mode,
            source_has_alpha=self.source_has_alpha,
            source_icc_profile_sha256=self.source_icc_profile_sha256,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("native output adoption input digest is inconsistent")
        _require_exact_provenance(
            self.provenance,
            [self.assignment, self.original_image],
            "native output adoption receipt",
        )
        return self


class CodexImageNativeCorePreparationReceipt(ImageMaterialLoopEvidence):
    """Bind one native original through normalization to selected core 0.1 evidence."""

    producer: Literal[
        "codex_blender_modeler.codex_imagegen.native_core_preparation"
    ] = "codex_blender_modeler.codex_imagegen.native_core_preparation"
    preparation_id: PortableId
    assignment_id: PortableId
    candidate_id: PortableId
    assignment: CodexImageArtifact
    native_output_adoption_receipt: CodexImageArtifact
    native_original_image: CodexImageArtifact
    normalization_plan: CodexImageArtifact
    normalization_receipt: CodexImageArtifact
    normalized_image: CodexImageArtifact
    core_completion: CodexImageArtifact
    core_candidate: CodexImageArtifact
    core_generated_image_evidence: CodexImageArtifact
    core_quality_report: CodexImageArtifact
    core_selection: CodexImageArtifact
    core_generated_image: CodexImageArtifact
    ordinal: int = Field(ge=0, le=2)
    output_role: DirectOutputRole
    target_size: MaterialLoopRasterSize
    status: Literal["prepared"] = "prepared"
    exact_normalized_bytes_copied_to_core: Literal[True] = True
    core_contracts_modified: Literal[False] = False
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_native_core_preparation(
        self,
    ) -> CodexImageNativeCorePreparationReceipt:
        """Require canonical identity, byte preservation, and exact direct provenance."""

        if self.contract_id != self.preparation_id:
            raise ValueError("native core preparation contract_id must equal preparation_id")
        if self.normalized_image.media_type != "image/png":
            raise ValueError("native core preparation normalized image must be PNG")
        normalized_bytes = (
            self.normalized_image.sha256,
            self.normalized_image.byte_size,
            self.normalized_image.media_type,
        )
        core_bytes = (
            self.core_generated_image.sha256,
            self.core_generated_image.byte_size,
            self.core_generated_image.media_type,
        )
        if normalized_bytes != core_bytes:
            raise ValueError("native normalization bytes differ from the core generated image")
        artifacts = [
            self.assignment,
            self.native_output_adoption_receipt,
            self.native_original_image,
            self.normalization_plan,
            self.normalization_receipt,
            self.normalized_image,
            self.core_completion,
            self.core_candidate,
            self.core_generated_image_evidence,
            self.core_quality_report,
            self.core_selection,
            self.core_generated_image,
        ]
        _require_exact_provenance(
            self.provenance,
            artifacts,
            "native core preparation receipt",
        )
        expected_input = codex_image_native_core_preparation_input_sha256(
            assignment=self.assignment,
            native_output_adoption_receipt=self.native_output_adoption_receipt,
            native_original_image=self.native_original_image,
            normalization_plan=self.normalization_plan,
            normalization_receipt=self.normalization_receipt,
            normalized_image=self.normalized_image,
            core_completion=self.core_completion,
            core_candidate=self.core_candidate,
            core_generated_image_evidence=self.core_generated_image_evidence,
            core_quality_report=self.core_quality_report,
            core_selection=self.core_selection,
            core_generated_image=self.core_generated_image,
            assignment_id=self.assignment_id,
            candidate_id=self.candidate_id,
            ordinal=self.ordinal,
            output_role=self.output_role,
            target_size=self.target_size,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("native core preparation input digest is inconsistent")
        if self.source_fingerprint != self.native_original_image.sha256:
            raise ValueError("native core preparation source must equal original bytes")
        return self


class ImageGenNativeNormalizationPlan(ImageMaterialLoopEvidence):
    """Freeze a source-preserving native-raster normalization decision."""

    source_image: CodexImageArtifact
    output_path: RelativePath
    source_size: MaterialLoopRasterSize
    target_size: MaterialLoopRasterSize
    native_output_policy: Literal[
        "exact_known_size",
        "allowed_size_set",
        "bounded_native_size",
        "preserve_native_then_normalize",
    ] = "preserve_native_then_normalize"
    allowed_native_sizes: list[MaterialLoopRasterSize] = Field(default_factory=list)
    requested_operation: NormalizationPreference
    operation: NormalizationOperation
    crop_rectangle: ImageGenCropRectangle | None = None
    content_size: MaterialLoopRasterSize | None = None
    padding: ImageGenPadding | None = None
    pad_rgba: tuple[
        Annotated[int, Field(ge=0, le=255)],
        Annotated[int, Field(ge=0, le=255)],
        Annotated[int, Field(ge=0, le=255)],
        Annotated[int, Field(ge=0, le=255)],
    ] = (0, 0, 0, 0)
    source_color_space: Literal["srgb", "non_color"]
    source_mode: str = Field(min_length=1, max_length=32)
    source_has_alpha: bool
    source_icc_profile_sha256: Sha256 | None = None
    alpha_policy: Literal["preserve", "drop", "opaque_add"] = "preserve"
    source_aspect_ratio: float = Field(gt=0.0, le=8192.0)
    target_aspect_ratio: float = Field(gt=0.0, le=8192.0)
    aspect_ratio_relative_delta: float = Field(ge=0.0, le=8192.0)
    maximum_automatic_aspect_delta: float = Field(default=0.35, ge=0.0, le=1.0)
    algorithm_id: Literal["pillow_native_normalization_v1"] = (
        "pillow_native_normalization_v1"
    )
    resampling: Literal["lanczos"] = "lanczos"
    output_media_type: Literal["image/png", "source_media_type"]
    source_immutable: Literal[True] = True
    stretch_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_normalization_geometry(self) -> ImageGenNativeNormalizationPlan:
        """Reject silent stretch, incoherent native policy, and stale geometry values."""

        expected_source_aspect = self.source_size.width / self.source_size.height
        expected_target_aspect = self.target_size.width / self.target_size.height
        expected_delta = abs(expected_source_aspect / expected_target_aspect - 1.0)
        if not math.isclose(self.source_aspect_ratio, expected_source_aspect, abs_tol=1e-12):
            raise ValueError("normalization source aspect ratio is inconsistent")
        if not math.isclose(self.target_aspect_ratio, expected_target_aspect, abs_tol=1e-12):
            raise ValueError("normalization target aspect ratio is inconsistent")
        if not math.isclose(self.aspect_ratio_relative_delta, expected_delta, abs_tol=1e-12):
            raise ValueError("normalization aspect delta is inconsistent")
        _validate_native_size_policy(self)
        _validate_normalization_operation(self)
        expected_input = imagegen_native_normalization_plan_input_sha256(
            source_image=self.source_image,
            output_path=self.output_path,
            source_size=self.source_size,
            target_size=self.target_size,
            native_output_policy=self.native_output_policy,
            allowed_native_sizes=self.allowed_native_sizes,
            requested_operation=self.requested_operation,
            maximum_automatic_aspect_delta=self.maximum_automatic_aspect_delta,
            source_color_space=self.source_color_space,
            source_mode=self.source_mode,
            source_has_alpha=self.source_has_alpha,
            source_icc_profile_sha256=self.source_icc_profile_sha256,
            alpha_policy=self.alpha_policy,
            pad_rgba=self.pad_rgba,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("normalization plan input digest is inconsistent")
        if self.source_fingerprint != self.source_image.sha256:
            raise ValueError("normalization plan source fingerprint must equal source bytes")
        if self.output_path == self.source_image.path:
            raise ValueError("normalization output must not overwrite its immutable source")
        if self.source_mode not in {"L", "LA", "RGB", "RGBA", "P"}:
            raise ValueError("normalization source mode is unsupported")
        if (
            self.source_image.media_type != "image/png"
            or not self.source_image.path.casefold().endswith(".png")
        ):
            raise ValueError("normalization source must be an exact PNG artifact")
        if self.output_path != imagegen_native_normalization_output_path(
            self.session_id,
            self.contract_id,
        ):
            raise ValueError("normalization output is outside its exact run-owned PNG leaf")
        _require_exact_provenance(
            self.provenance,
            [self.source_image],
            "native normalization plan",
        )
        return self


class ImageGenNativeNormalizationReceipt(ImageMaterialLoopEvidence):
    """Record exact original and deterministic normalized derivative bytes."""

    plan: CodexImageArtifact
    source_image: CodexImageArtifact
    native_output_adoption_receipt: CodexImageArtifact | None = None
    normalized_image: CodexImageArtifact | None = None
    source_size: MaterialLoopRasterSize
    target_size: MaterialLoopRasterSize
    operation: NormalizationOperation
    crop_rectangle: ImageGenCropRectangle | None = None
    content_size: MaterialLoopRasterSize | None = None
    padding: ImageGenPadding | None = None
    source_aspect_ratio: float = Field(gt=0.0, le=8192.0)
    target_aspect_ratio: float = Field(gt=0.0, le=8192.0)
    source_color_space: Literal["srgb", "non_color"]
    source_mode: str = Field(min_length=1, max_length=32)
    output_mode: Literal["L", "LA", "RGB", "RGBA", "P"] | None = None
    source_has_alpha: bool
    output_has_alpha: bool | None = None
    source_icc_profile_sha256: Sha256 | None = None
    output_icc_profile_sha256: Sha256 | None = None
    alpha_policy: Literal["preserve", "drop", "opaque_add"]
    algorithm_id: Literal["pillow_native_normalization_v1"]
    resampling: Literal["lanczos"]
    status: Literal["pass_through", "normalized", "review_required"]
    source_preserved: Literal[True] = True
    exact_byte_adoption: Literal[True] = True
    deterministic_derivative: Literal[True] = True

    @model_validator(mode="after")
    def validate_normalization_receipt(self) -> ImageGenNativeNormalizationReceipt:
        """Require a derivative except at the explicit review boundary and exact provenance."""

        if self.status == "review_required":
            if (
                self.operation != "review_required"
                or self.normalized_image is not None
                or self.output_mode is not None
                or self.output_has_alpha is not None
                or self.output_icc_profile_sha256 is not None
            ):
                raise ValueError("review-required normalization cannot claim output bytes")
        else:
            if (
                self.normalized_image is None
                or self.output_mode is None
                or self.output_has_alpha is None
            ):
                raise ValueError("successful normalization requires exact output bytes")
            expected_status = "pass_through" if self.operation == "pass_through" else "normalized"
            if self.status != expected_status:
                raise ValueError("normalization receipt status is inconsistent")
        if self.source_fingerprint != self.source_image.sha256:
            raise ValueError("normalization receipt source fingerprint must equal source bytes")
        if self.status != "review_required":
            if self.alpha_policy == "drop" and self.output_has_alpha:
                raise ValueError("drop alpha policy cannot retain an alpha channel")
            if self.alpha_policy == "opaque_add" and not self.output_has_alpha:
                raise ValueError("opaque-add alpha policy requires an output alpha channel")
            if (
                self.alpha_policy == "preserve"
                and self.output_has_alpha != self.source_has_alpha
            ):
                raise ValueError("preserve alpha policy changed alpha presence")
            if self.output_icc_profile_sha256 != self.source_icc_profile_sha256:
                raise ValueError("normalization must preserve the exact ICC profile")
        artifacts = [
            self.plan,
            self.source_image,
            *(
                [self.native_output_adoption_receipt]
                if self.native_output_adoption_receipt
                else []
            ),
            *([self.normalized_image] if self.normalized_image else []),
        ]
        _require_exact_provenance(self.provenance, artifacts, "normalization receipt")
        return self


class CodexImageSemanticReview(ImageMaterialLoopEvidence):
    """Record current-task visual observations as advisory, non-human evidence."""

    candidate_id: PortableId
    reviewed_image: CodexImageArtifact
    assignment: CodexImageArtifact
    deterministic_quality_report: CodexImageArtifact
    material_family: Literal[
        "wood",
        "signage_decal",
        "emissive",
        "crystal",
        "user_image_pbr",
        "planar_reference_patch",
    ]
    checks: list[CodexImageSemanticCheck] = Field(
        min_length=len(ALL_SEMANTIC_REVIEW_CATEGORIES),
        max_length=len(ALL_SEMANTIC_REVIEW_CATEGORIES),
    )
    outcome: SemanticReviewOutcome
    human_reviewed: Literal[False] = False
    observed_reference_truth: Literal[False] = False
    deterministic_gates_replaced: Literal[False] = False
    selection_authority: Literal["advisory_after_deterministic_gates"] = (
        "advisory_after_deterministic_gates"
    )

    @model_validator(mode="after")
    def validate_semantic_review(self) -> CodexImageSemanticReview:
        """Require all categories once and derive the honest aggregate outcome."""

        categories = [item.category for item in self.checks]
        if tuple(categories) != ALL_SEMANTIC_REVIEW_CATEGORIES:
            raise ValueError("semantic review checks must use the canonical order exactly once")
        expected = semantic_review_outcome(self.checks)
        if self.outcome != expected:
            raise ValueError("semantic review aggregate outcome is inconsistent")
        if self.source_fingerprint != self.reviewed_image.sha256:
            raise ValueError("semantic review source fingerprint must equal reviewed bytes")
        _require_exact_provenance(
            self.provenance,
            [self.reviewed_image, self.assignment, self.deterministic_quality_report],
            "semantic review",
        )
        return self


class CodexImageCandidateRankingEvidence(ImageMaterialLoopEvidence):
    """Freeze one candidate's exact companion-profile semantic precedence inputs."""

    ranking_id: PortableId
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    candidate: CodexImageArtifact
    candidate_id: PortableId
    reviewed_image: CodexImageArtifact
    deterministic_quality_report: CodexImageArtifact
    semantic_review: CodexImageArtifact
    file_hard_gate_passed: bool
    deterministic_quality_outcome: Literal[
        "passed",
        "review_required",
        "failed",
        "unscorable",
    ]
    deterministic_quality_score: UnitInterval
    semantic_outcome: SemanticReviewOutcome
    material_role_suitability: MaterialRoleSuitability
    repair_cost: float = Field(ge=0.0, le=1_000_000.0)
    precedence_key: tuple[int, int, float, int, int, float, str]
    ranking_algorithm_id: Literal["companion_semantic_precedence_v1"] = (
        "companion_semantic_precedence_v1"
    )
    companion_profile_only: Literal[True] = True
    human_reviewed: Literal[False] = False

    @model_validator(mode="after")
    def validate_candidate_ranking(self) -> CodexImageCandidateRankingEvidence:
        """Recompute the complete ordered ranking key and immutable input closure."""

        expected_key = companion_candidate_precedence_key(
            file_hard_gate_passed=self.file_hard_gate_passed,
            deterministic_quality_outcome=self.deterministic_quality_outcome,
            deterministic_quality_score=self.deterministic_quality_score,
            semantic_outcome=self.semantic_outcome,
            material_role_suitability=self.material_role_suitability,
            repair_cost=self.repair_cost,
            candidate_id=self.candidate_id,
        )
        if self.precedence_key != expected_key:
            raise ValueError("candidate ranking precedence key is inconsistent")
        expected_input = candidate_ranking_input_sha256(
            assignment=self.assignment,
            completion=self.completion,
            candidate=self.candidate,
            candidate_id=self.candidate_id,
            reviewed_image=self.reviewed_image,
            deterministic_quality_report=self.deterministic_quality_report,
            semantic_review=self.semantic_review,
            file_hard_gate_passed=self.file_hard_gate_passed,
            deterministic_quality_outcome=self.deterministic_quality_outcome,
            deterministic_quality_score=self.deterministic_quality_score,
            semantic_outcome=self.semantic_outcome,
            material_role_suitability=self.material_role_suitability,
            repair_cost=self.repair_cost,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("candidate ranking input digest is inconsistent")
        if self.source_fingerprint != self.reviewed_image.sha256:
            raise ValueError("candidate ranking source must equal reviewed image bytes")
        _require_exact_provenance(
            self.provenance,
            [
                self.assignment,
                self.completion,
                self.candidate,
                self.reviewed_image,
                self.deterministic_quality_report,
                self.semantic_review,
            ],
            "candidate ranking evidence",
        )
        return self


class CodexImageCompanionCandidateDecision(CodexImageStrictModel):
    """Record one candidate's exact companion evidence and selection disposition."""

    candidate_id: PortableId
    candidate: CodexImageArtifact
    reviewed_image: CodexImageArtifact
    deterministic_quality_report: CodexImageArtifact
    semantic_review: CodexImageArtifact | None = None
    ranking_evidence: CodexImageArtifact | None = None
    precedence_key: tuple[int, int, float, int, int, float, str] | None = None
    outcome: Literal["selected", "rejected", "ineligible", "review_required"]
    reason_codes: list[PortableId] = Field(min_length=1)
    human_reviewed: Literal[False] = False

    @model_validator(mode="after")
    def validate_companion_decision(self) -> CodexImageCompanionCandidateDecision:
        """Keep missing, unresolved, and ranked decision evidence unambiguous."""

        has_complete_ranking = (
            self.semantic_review is not None
            and self.ranking_evidence is not None
            and self.precedence_key is not None
        )
        if self.outcome in {"selected", "rejected", "ineligible"}:
            if not has_complete_ranking:
                raise ValueError("resolved companion decision requires exact ranking evidence")
        elif has_complete_ranking and not any(
            "review-required" in code for code in self.reason_codes
        ):
            raise ValueError("review decision requires missing or unresolved evidence")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("companion decision reason codes must be unique")
        return self


class CodexImageCompanionSelectionReceipt(ImageMaterialLoopEvidence):
    """Bind companion ranking grounds to one core-compatible selection artifact."""

    receipt_id: PortableId
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    core_selection: CodexImageArtifact
    candidate_count: int = Field(ge=2, le=3)
    decisions: list[CodexImageCompanionCandidateDecision] = Field(
        min_length=2,
        max_length=3,
    )
    missing_candidate_ids: list[PortableId] = Field(default_factory=list)
    unresolved_candidate_ids: list[PortableId] = Field(default_factory=list)
    selected_candidate: CodexImageArtifact | None = None
    selected_quality_report: CodexImageArtifact | None = None
    selected_ranking_evidence: CodexImageArtifact | None = None
    outcome: CompanionSelectionOutcome
    selection_method: Literal["companion_semantic_precedence_v1"] = (
        "companion_semantic_precedence_v1"
    )
    core_selector_meaning_changed: Literal[False] = False
    human_reviewed: Literal[False] = False

    @model_validator(mode="after")
    def validate_companion_selection(self) -> CodexImageCompanionSelectionReceipt:
        """Require exact candidate coverage and fail-closed unresolved selection state."""

        if self.contract_id != self.receipt_id:
            raise ValueError("companion selection contract_id must equal receipt_id")
        ids = [item.candidate_id for item in self.decisions]
        if len(ids) != self.candidate_count or len(ids) != len(set(ids)):
            raise ValueError("companion decisions must exactly cover unique candidates")
        for label, values in (
            ("missing", self.missing_candidate_ids),
            ("unresolved", self.unresolved_candidate_ids),
        ):
            if values != sorted(set(values)) or not set(values).issubset(ids):
                raise ValueError(f"companion {label} candidate IDs are inconsistent")
        selected = [item for item in self.decisions if item.outcome == "selected"]
        if self.outcome == "selected":
            if self.missing_candidate_ids or self.unresolved_candidate_ids:
                raise ValueError("companion selection cannot bypass unresolved evidence")
            if len(selected) != 1:
                raise ValueError("companion selected outcome requires one selected decision")
            decision = selected[0]
            if (
                self.selected_candidate != decision.candidate
                or self.selected_quality_report
                != decision.deterministic_quality_report
                or self.selected_ranking_evidence != decision.ranking_evidence
            ):
                raise ValueError("companion selected artifacts differ from their decision")
        elif (
            selected
            or self.selected_candidate is not None
            or self.selected_quality_report is not None
            or self.selected_ranking_evidence is not None
        ):
            raise ValueError("non-selected companion outcome cannot bind selected evidence")
        if self.outcome == "review_required" and not (
            self.missing_candidate_ids or self.unresolved_candidate_ids
        ):
            raise ValueError("review-required companion receipt needs a visible reason")
        if self.outcome == "no_eligible_candidate" and (
            self.missing_candidate_ids or self.unresolved_candidate_ids
        ):
            raise ValueError("unresolved evidence requires review rather than ineligibility")
        expected_input = companion_selection_receipt_input_sha256(
            assignment=self.assignment,
            completion=self.completion,
            core_selection=self.core_selection,
            decisions=self.decisions,
            missing_candidate_ids=self.missing_candidate_ids,
            unresolved_candidate_ids=self.unresolved_candidate_ids,
            outcome=self.outcome,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("companion selection receipt input digest is inconsistent")
        if self.source_fingerprint != self.assignment.sha256:
            raise ValueError("companion selection source must equal assignment bytes")
        artifacts = [
            self.assignment,
            self.completion,
            self.core_selection,
            *[item.candidate for item in self.decisions],
            *[item.reviewed_image for item in self.decisions],
            *[item.deterministic_quality_report for item in self.decisions],
            *[
                item.semantic_review
                for item in self.decisions
                if item.semantic_review is not None
            ],
            *[
                item.ranking_evidence
                for item in self.decisions
                if item.ranking_evidence is not None
            ],
        ]
        _require_exact_provenance(
            self.provenance,
            _unique_artifact_bindings(artifacts),
            "companion selection receipt",
        )
        return self


class CodexImageMaterialLoopTerminal(ImageMaterialLoopEvidence):
    """Close only the companion material-adoption scope, never the whole AQ workflow."""

    bridge_plan: CodexImageArtifact
    latest_state: CodexImageArtifact
    base_state: CodexImageArtifact
    base_quality_terminal: CodexImageArtifact | None = None
    review_bundle: CodexImageArtifact | None = None
    promotion_receipt: CodexImageArtifact | None = None
    material_phase_receipt: CodexImageArtifact | None = None
    integrated_quality_report: CodexImageArtifact | None = None
    quality_freeze: CodexImageArtifact | None = None
    delivery_receipts: list[CodexImageArtifact] = Field(default_factory=list)
    status: Literal[
        "material_promoted",
        "waiting_for_quality",
        "quality_approved",
        "review_required",
        "blocked",
        "failed",
        "cancelled",
    ]
    material_candidate_promoted: bool
    base_aq_completed: Literal[False] = False
    quality_passed: bool = False
    packages_completed: bool = False
    destination_runtime_parity_verified: Literal[False] = False
    human_reviewed: Literal[False] = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_terminal_scope(self) -> CodexImageMaterialLoopTerminal:
        """Prevent companion completion from overstating IQ, package, or destination state."""

        if self.material_candidate_promoted:
            if self.promotion_receipt is None or self.material_phase_receipt is None:
                raise ValueError("promoted terminal requires both promotion receipts")
        elif self.promotion_receipt is not None or self.material_phase_receipt is not None:
            raise ValueError("unpromoted terminal cannot claim promotion evidence")
        if self.status in {
            "material_promoted",
            "waiting_for_quality",
            "quality_approved",
            "blocked",
        } and not self.material_candidate_promoted:
            raise ValueError("post-promotion companion status requires canonical promotion")
        if self.quality_passed and self.integrated_quality_report is None:
            raise ValueError("quality pass requires an Integrated Quality report")
        if self.quality_passed and (
            self.quality_freeze is None or self.base_quality_terminal is None
        ):
            raise ValueError("quality pass requires exact freeze and base quality terminal")
        if self.packages_completed and (not self.quality_passed or not self.delivery_receipts):
            raise ValueError("completed packages require quality acceptance and receipts")
        if self.quality_freeze is not None and self.material_phase_receipt is None:
            raise ValueError("quality freeze requires MaterialPhaseReceiptV2 evidence")
        if self.quality_freeze is not None and not self.quality_passed:
            raise ValueError("quality freeze cannot precede quality acceptance")
        if self.status == "quality_approved" and self.base_quality_terminal is None:
            raise ValueError("quality-approved companion requires the exact base terminal")
        if self.status == "review_required":
            if self.base_quality_terminal is None or self.review_bundle is None:
                raise ValueError("review terminal requires base terminal and review bundle")
        elif self.review_bundle is not None:
            raise ValueError("only review-required terminal may carry a review bundle")
        if self.status == "blocked":
            if self.base_quality_terminal is None:
                raise ValueError("blocked terminal requires the exact base quality terminal")
            if self.quality_passed or self.quality_freeze is not None:
                raise ValueError("blocked terminal cannot claim quality acceptance or freeze")
            if self.packages_completed or self.delivery_receipts:
                raise ValueError("blocked terminal cannot claim delivery completion")
        if self.status in {"material_promoted", "waiting_for_quality"} and any(
            value is not None
            for value in (
                self.base_quality_terminal,
                self.review_bundle,
                self.integrated_quality_report,
                self.quality_freeze,
            )
        ):
            raise ValueError("pre-quality companion status cannot claim quality evidence")
        if self.status in {"material_promoted", "waiting_for_quality"} and (
            self.quality_passed or self.packages_completed or self.delivery_receipts
        ):
            raise ValueError("pre-quality companion status cannot claim delivery completion")
        artifacts = [
            self.bridge_plan,
            self.latest_state,
            self.base_state,
            *([self.base_quality_terminal] if self.base_quality_terminal else []),
            *([self.review_bundle] if self.review_bundle else []),
            *([self.promotion_receipt] if self.promotion_receipt else []),
            *([self.material_phase_receipt] if self.material_phase_receipt else []),
            *([self.integrated_quality_report] if self.integrated_quality_report else []),
            *([self.quality_freeze] if self.quality_freeze else []),
            *self.delivery_receipts,
        ]
        _require_exact_provenance(self.provenance, artifacts, "material-loop terminal")
        if self.input_sha256 != stable_json_digest(
            {item.path: item.sha256 for item in artifacts}
        ):
            raise ValueError("material-loop terminal input digest is inconsistent")
        return self


class CodexImageMaterialLoopState(ImageMaterialLoopEvidence):
    """Record one append-only companion state distinct from the base AQ v2 state."""

    state_id: PortableId
    sequence: int = Field(ge=0)
    previous_state: CodexImageArtifact | None = None
    previous_state_sha256: Sha256 | None = None
    status: MaterialLoopStatus
    bridge_plan: CodexImageArtifact
    controller_input: CodexImageArtifact
    promotion_receipt: CodexImageArtifact | None = None
    material_phase_receipt: CodexImageArtifact | None = None
    base_state: CodexImageArtifact | None = None
    failure_evidence: CodexImageArtifact | None = None
    review_evidence: CodexImageArtifact | None = None
    budget_usage: ImageMaterialLoopBudgetUsage = Field(
        default_factory=ImageMaterialLoopBudgetUsage
    )
    latest_failure: str | None = Field(default=None, min_length=1, max_length=2048)
    promotion_consumed_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_state_shape(self) -> CodexImageMaterialLoopState:
        """Bind sequence, predecessor, promotion evidence, and failure state exactly."""

        if self.contract_id != self.state_id:
            raise ValueError("material-loop state contract_id must equal state_id")
        if self.source_fingerprint != self.bridge_plan.sha256:
            raise ValueError("material-loop state source fingerprint must equal bridge plan")
        if self.sequence == 0:
            if self.previous_state is not None or self.previous_state_sha256 is not None:
                raise ValueError("initial material-loop state cannot declare a predecessor")
            if self.status != "controller_promotion_required":
                raise ValueError("initial material-loop state must await controller promotion")
        else:
            if self.previous_state is None:
                raise ValueError("non-initial material-loop state requires predecessor evidence")
            if self.previous_state_sha256 != self.previous_state.sha256:
                raise ValueError("material-loop predecessor hash is inconsistent")
        promotion_required = self.status in {
            "material_promoted",
            "waiting_for_quality",
            "quality_approved",
            "blocked",
        }
        promotion_values = (
            self.promotion_receipt,
            self.material_phase_receipt,
            self.base_state,
        )
        has_promotion = any(value is not None for value in promotion_values)
        if has_promotion and not all(value is not None for value in promotion_values):
            raise ValueError("promotion receipt, material receipt, and base state form one closure")
        if promotion_required:
            if not has_promotion:
                raise ValueError("promoted material-loop state requires exact promotion closure")
        elif self.status in {"controller_promotion_required", "promoting_material"}:
            if has_promotion:
                raise ValueError("pre-promotion state cannot consume promotion evidence")
        if has_promotion:
            if self.promotion_receipt is None:
                raise ValueError("promotion closure omits its companion receipt")
            if self.promotion_consumed_sha256 != self.promotion_receipt.sha256:
                raise ValueError("promoted state consumption hash is inconsistent")
        elif self.promotion_consumed_sha256 is not None:
            raise ValueError("unpromoted state cannot consume promotion authority")
        if self.status == "failed":
            if self.latest_failure is None or self.failure_evidence is None:
                raise ValueError("failed state requires a reason and exact failure evidence")
        elif self.latest_failure is not None:
            raise ValueError("only failed states carry a latest_failure")
        if self.status in {"blocked", "cancelled"}:
            if self.failure_evidence is None:
                raise ValueError("blocked or cancelled state requires exact terminal evidence")
        elif self.status != "failed" and self.failure_evidence is not None:
            raise ValueError("only blocked, failed, or cancelled states carry failure evidence")
        if (self.status == "review_required") != (self.review_evidence is not None):
            raise ValueError("review-required state must carry exact review evidence")
        artifacts = [
            self.bridge_plan,
            self.controller_input,
            *([self.previous_state] if self.previous_state else []),
            *([self.promotion_receipt] if self.promotion_receipt else []),
            *([self.material_phase_receipt] if self.material_phase_receipt else []),
            *([self.base_state] if self.base_state else []),
            *([self.failure_evidence] if self.failure_evidence else []),
            *([self.review_evidence] if self.review_evidence else []),
        ]
        _require_exact_provenance(self.provenance, artifacts, "material-loop state")
        expected_input = material_loop_state_input_sha256(
            sequence=self.sequence,
            previous_state_sha256=self.previous_state_sha256,
            status=self.status,
            bridge_plan_sha256=self.bridge_plan.sha256,
            controller_input_sha256=self.controller_input.sha256,
            promotion_receipt_sha256=(
                self.promotion_receipt.sha256 if self.promotion_receipt else None
            ),
            material_phase_receipt_sha256=(
                self.material_phase_receipt.sha256 if self.material_phase_receipt else None
            ),
            base_state_sha256=(self.base_state.sha256 if self.base_state else None),
            failure_evidence_sha256=(
                self.failure_evidence.sha256 if self.failure_evidence else None
            ),
            review_evidence_sha256=(
                self.review_evidence.sha256 if self.review_evidence else None
            ),
            latest_failure=self.latest_failure,
            budget_usage=self.budget_usage,
        )
        if self.input_sha256 != expected_input:
            raise ValueError("material-loop state input hash is inconsistent")
        return self


def semantic_review_outcome(
    checks: list[CodexImageSemanticCheck],
) -> SemanticReviewOutcome:
    """Derive a fail-closed aggregate from ordered semantic checks."""

    if any(item.outcome == "failed" for item in checks):
        return "failed"
    if checks and all(item.outcome == "unavailable" for item in checks):
        return "unavailable"
    if any(item.outcome in {"review_required", "unavailable"} for item in checks):
        return "review_required"
    return "passed"


def companion_candidate_precedence_key(
    *,
    file_hard_gate_passed: bool,
    deterministic_quality_outcome: str,
    deterministic_quality_score: float,
    semantic_outcome: str,
    material_role_suitability: str,
    repair_cost: float,
    candidate_id: str,
) -> tuple[int, int, float, int, int, float, str]:
    """Order file, quality, semantics, role, repair, then stable candidate ID."""

    quality_rank = {
        "passed": 0,
        "review_required": 1,
        "unscorable": 1,
        "failed": 2,
    }[deterministic_quality_outcome]
    semantic_rank = {
        "passed": 0,
        "review_required": 1,
        "unavailable": 1,
        "failed": 2,
    }[semantic_outcome]
    role_rank = {
        "suitable": 0,
        "review_required": 1,
        "unsuitable": 2,
    }[material_role_suitability]
    return (
        0 if file_hard_gate_passed else 1,
        quality_rank,
        -deterministic_quality_score,
        semantic_rank,
        role_rank,
        repair_cost,
        candidate_id,
    )


def candidate_ranking_input_sha256(
    *,
    assignment: CodexImageArtifact,
    completion: CodexImageArtifact,
    candidate: CodexImageArtifact,
    candidate_id: str,
    reviewed_image: CodexImageArtifact,
    deterministic_quality_report: CodexImageArtifact,
    semantic_review: CodexImageArtifact,
    file_hard_gate_passed: bool,
    deterministic_quality_outcome: str,
    deterministic_quality_score: float,
    semantic_outcome: str,
    material_role_suitability: str,
    repair_cost: float,
) -> str:
    """Hash every exact artifact and scalar consumed by companion candidate ranking."""

    return stable_json_digest(
        {
            "assignment": assignment.model_dump(mode="json"),
            "completion": completion.model_dump(mode="json"),
            "candidate": candidate.model_dump(mode="json"),
            "candidate_id": candidate_id,
            "reviewed_image": reviewed_image.model_dump(mode="json"),
            "deterministic_quality_report": deterministic_quality_report.model_dump(
                mode="json"
            ),
            "semantic_review": semantic_review.model_dump(mode="json"),
            "file_hard_gate_passed": file_hard_gate_passed,
            "deterministic_quality_outcome": deterministic_quality_outcome,
            "deterministic_quality_score": deterministic_quality_score,
            "semantic_outcome": semantic_outcome,
            "material_role_suitability": material_role_suitability,
            "repair_cost": repair_cost,
        }
    )


def companion_selection_receipt_input_sha256(
    *,
    assignment: CodexImageArtifact,
    completion: CodexImageArtifact,
    core_selection: CodexImageArtifact,
    decisions: list[CodexImageCompanionCandidateDecision],
    missing_candidate_ids: list[str],
    unresolved_candidate_ids: list[str],
    outcome: str,
) -> str:
    """Hash the full multi-candidate ranking closure and core selection binding."""

    return stable_json_digest(
        {
            "assignment": assignment.model_dump(mode="json"),
            "completion": completion.model_dump(mode="json"),
            "core_selection": core_selection.model_dump(mode="json"),
            "decisions": [item.model_dump(mode="json") for item in decisions],
            "missing_candidate_ids": missing_candidate_ids,
            "unresolved_candidate_ids": unresolved_candidate_ids,
            "outcome": outcome,
        }
    )


def codex_image_v05_exact_adoption_preflight_root_path(
    session_id: str,
    preflight_id: str,
) -> str:
    """Return the isolated immutable root for one pre-controller Blender compile."""

    identity = stable_json_digest(
        {"session_id": session_id, "preflight_id": preflight_id}
    )[:20]
    return f"evidence/image_material_preflights/{identity}"


def codex_image_v05_exact_adoption_preflight_receipt_path(
    session_id: str,
    preflight_id: str,
) -> str:
    """Return the canonical receipt leaf for one exact-adoption preflight."""

    return (
        f"{codex_image_v05_exact_adoption_preflight_root_path(session_id, preflight_id)}"
        "/receipt.json"
    )


def exact_adoption_preflight_input_sha256(
    *,
    v05_bridge_receipt: CodexImageArtifact,
    candidate_material_plan: CodexImageArtifact,
    material_graph_spec: CodexImageArtifact,
    shadow_root: str,
    shadow_candidate_material_plan: CodexImageArtifact,
    shadow_material_graph_spec: CodexImageArtifact,
    compile_run_root: str,
    graph_compile_report: CodexImageArtifact,
    compile_artifacts: list[CodexImageArtifact],
    material_id: str,
    graph_id: str,
) -> str:
    """Hash the exact V0.5 source, shadow, and actual compiler evidence closure."""

    return stable_json_digest(
        {
            "v05_bridge_receipt": v05_bridge_receipt.model_dump(mode="json"),
            "candidate_material_plan": candidate_material_plan.model_dump(mode="json"),
            "material_graph_spec": material_graph_spec.model_dump(mode="json"),
            "shadow_root": shadow_root,
            "shadow_candidate_material_plan": (
                shadow_candidate_material_plan.model_dump(mode="json")
            ),
            "shadow_material_graph_spec": shadow_material_graph_spec.model_dump(
                mode="json"
            ),
            "compile_run_root": compile_run_root,
            "graph_compile_report": graph_compile_report.model_dump(mode="json"),
            "compile_artifacts": [
                item.model_dump(mode="json") for item in compile_artifacts
            ],
            "material_id": material_id,
            "graph_id": graph_id,
        }
    )


def material_loop_state_input_sha256(
    *,
    sequence: int,
    previous_state_sha256: str | None,
    status: MaterialLoopStatus,
    bridge_plan_sha256: str,
    controller_input_sha256: str,
    promotion_receipt_sha256: str | None,
    material_phase_receipt_sha256: str | None,
    base_state_sha256: str | None = None,
    failure_evidence_sha256: str | None = None,
    review_evidence_sha256: str | None = None,
    latest_failure: str | None = None,
    budget_usage: ImageMaterialLoopBudgetUsage,
) -> str:
    """Hash the exact predecessor, evidence, and monotonic usage for a state transition."""

    return stable_json_digest(
        {
            "sequence": sequence,
            "previous_state_sha256": previous_state_sha256,
            "status": status,
            "bridge_plan_sha256": bridge_plan_sha256,
            "controller_input_sha256": controller_input_sha256,
            "promotion_receipt_sha256": promotion_receipt_sha256,
            "material_phase_receipt_sha256": material_phase_receipt_sha256,
            "base_state_sha256": base_state_sha256,
            "failure_evidence_sha256": failure_evidence_sha256,
            "review_evidence_sha256": review_evidence_sha256,
            "latest_failure": latest_failure,
            "budget_usage": budget_usage.model_dump(mode="json"),
        }
    )


def validate_material_loop_transition(
    previous: CodexImageMaterialLoopState,
    current: CodexImageMaterialLoopState,
) -> None:
    """Reject invalid, non-monotonic, cross-session, or duplicate state transitions."""

    allowed: dict[str, frozenset[str]] = {
        "controller_promotion_required": frozenset(
            {"promoting_material", "failed", "cancelled"}
        ),
        "promoting_material": frozenset(
            {"material_promoted", "review_required", "failed", "cancelled"}
        ),
        "material_promoted": frozenset(
            {
                "waiting_for_quality",
                "quality_approved",
                "review_required",
                "blocked",
                "failed",
                "cancelled",
            }
        ),
        "waiting_for_quality": frozenset(
            {"quality_approved", "review_required", "blocked", "failed", "cancelled"}
        ),
        "quality_approved": frozenset(),
        "review_required": frozenset(),
        "blocked": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    }
    if current.status not in allowed[previous.status]:
        raise ValueError(f"invalid material-loop transition: {previous.status}->{current.status}")
    if current.sequence != previous.sequence + 1:
        raise ValueError("material-loop sequence must advance by exactly one")
    if (
        current.job_id,
        current.workflow_id,
        current.dispatch_id,
        current.session_id,
        current.profile_id,
        current.bridge_plan.sha256,
        current.controller_input.sha256,
    ) != (
        previous.job_id,
        previous.workflow_id,
        previous.dispatch_id,
        previous.session_id,
        previous.profile_id,
        previous.bridge_plan.sha256,
        previous.controller_input.sha256,
    ):
        raise ValueError(
            "material-loop transition identity, bridge, or controller-input binding changed"
        )
    previous_promotion = (
        previous.promotion_receipt,
        previous.material_phase_receipt,
        previous.promotion_consumed_sha256,
    )
    current_promotion = (
        current.promotion_receipt,
        current.material_phase_receipt,
        current.promotion_consumed_sha256,
    )
    if previous.promotion_receipt is not None and current_promotion != previous_promotion:
        raise ValueError("post-promotion transition must preserve the exact promotion closure")
    if (
        previous.promotion_receipt is None
        and current.status != "material_promoted"
        and any(value is not None for value in current_promotion)
    ):
        raise ValueError("only material_promoted may introduce promotion evidence")
    for field in ImageMaterialLoopBudgetUsage.model_fields:
        if getattr(current.budget_usage, field) < getattr(previous.budget_usage, field):
            raise ValueError("material-loop budget usage must be monotonic")
    controller_delta = (
        current.budget_usage.controller_invocations
        - previous.budget_usage.controller_invocations
    )
    promotion_delta = (
        current.budget_usage.promotions_consumed
        - previous.budget_usage.promotions_consumed
    )
    if controller_delta > 1 or promotion_delta > 1:
        raise ValueError("one material-loop transition cannot consume duplicate authority")
    if current.status == "promoting_material" and promotion_delta != 0:
        raise ValueError("promoting_material cannot pre-consume a promotion receipt")
    newly_promoted = current.status == "material_promoted"
    if newly_promoted and promotion_delta != 1:
        raise ValueError("material_promoted must consume exactly one promotion")
    if not newly_promoted and promotion_delta != 0:
        raise ValueError("only material_promoted may consume promotion authority")


def _validate_requested_delivery_profiles(profiles: list[str]) -> None:
    """Allow none, review-only, or one/two independent portable delivery profiles."""

    if len(profiles) != len(set(profiles)):
        raise ValueError("requested delivery profiles must be unique")
    if "none" in profiles and len(profiles) != 1:
        raise ValueError("none cannot be combined with a requested delivery profile")
    if "review_only" in profiles and len(profiles) != 1:
        raise ValueError("review_only cannot be combined with portable delivery")


def _require_unique_artifact_sequence(
    artifacts: list[CodexImageArtifact],
    label: str,
) -> None:
    """Require one ordered artifact sequence to use unique exact identities and paths."""

    identities = [_artifact_identity(item) for item in artifacts]
    paths = [item.path for item in artifacts]
    artifact_ids = [item.artifact_id for item in artifacts]
    if len(identities) != len(set(identities)):
        raise ValueError(f"{label} contain duplicate exact artifacts")
    if len(paths) != len(set(paths)) or len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError(f"{label} contain conflicting paths or artifact IDs")


def _merge_exact_artifact_aliases(
    direct: list[CodexImageArtifact],
    aliases: list[CodexImageArtifact],
    label: str,
) -> list[CodexImageArtifact]:
    """Merge exact cross-field aliases while rejecting conflicting identities."""

    _require_unique_artifact_sequence(direct, f"{label} direct inventory")
    _require_unique_artifact_sequence(aliases, f"{label} ordered aliases")
    merged = list(direct)
    identities = {_artifact_identity(item) for item in direct}
    paths = {item.path for item in direct}
    artifact_ids = {item.artifact_id for item in direct}
    for artifact in aliases:
        identity = _artifact_identity(artifact)
        if identity in identities:
            continue
        if artifact.path in paths or artifact.artifact_id in artifact_ids:
            raise ValueError(f"{label} conflict with a direct artifact identity")
        merged.append(artifact)
        identities.add(identity)
        paths.add(artifact.path)
        artifact_ids.add(artifact.artifact_id)
    return merged


def _unique_artifact_bindings(
    artifacts: list[CodexImageArtifact],
) -> list[CodexImageArtifact]:
    """Deduplicate exact aliases while rejecting path or artifact-ID conflicts."""

    merged: list[CodexImageArtifact] = []
    identities: set[tuple[str, str, str, str, int, str]] = set()
    paths: dict[str, tuple[str, str, str, str, int, str]] = {}
    artifact_ids: dict[str, tuple[str, str, str, str, int, str]] = {}
    for artifact in artifacts:
        identity = _artifact_identity(artifact)
        if identity in identities:
            continue
        if artifact.path in paths or artifact.artifact_id in artifact_ids:
            raise ValueError("artifact aliases conflict by path or artifact ID")
        merged.append(artifact)
        identities.add(identity)
        paths[artifact.path] = identity
        artifact_ids[artifact.artifact_id] = identity
    return merged


def _artifact_identity(
    artifact: CodexImageArtifact,
) -> tuple[str, str, str, str, int, str]:
    """Return the complete immutable identity and byte binding of one artifact."""

    return (
        artifact.artifact_id,
        artifact.kind,
        artifact.path,
        artifact.sha256,
        artifact.byte_size,
        artifact.media_type,
    )


def _require_exact_provenance(
    provenance: list[CodexImageArtifact],
    artifacts: list[CodexImageArtifact],
    label: str,
) -> None:
    """Require provenance to enumerate each declared artifact exactly once."""

    expected = [_artifact_identity(item) for item in artifacts]
    observed = [_artifact_identity(item) for item in provenance]
    if len(expected) != len(set(expected)):
        raise ValueError(f"{label} declares duplicate artifact identities")
    if len(observed) != len(set(observed)):
        raise ValueError(f"{label} provenance contains duplicate artifact identities")
    if set(expected) != set(observed):
        raise ValueError(f"{label} provenance is incomplete or contains extras")


def _require_exact_artifact_map(
    bindings: dict[str, str],
    artifacts: list[CodexImageArtifact],
) -> None:
    """Require an immutable-input map to equal all declared artifact path/hash pairs."""

    expected = {item.path: item.sha256 for item in artifacts}
    if len(expected) != len(artifacts):
        raise ValueError("immutable controller inputs contain duplicate paths")
    if bindings != expected:
        raise ValueError("immutable controller input map is incomplete or contains extras")


def _validate_material_baseline(
    previous: CodexImageArtifact | None,
    absence: CodexImageArtifact | None,
) -> None:
    """Require exactly one canonical MaterialPlan baseline or exact absence record."""

    if (previous is None) == (absence is None):
        raise ValueError("declare exactly one prior MaterialPlan or absence evidence")


def _validate_material_observation(
    observation: CodexImageArtifact | None,
    snapshot: CodexImageArtifact | None,
    absence: CodexImageArtifact | None,
) -> None:
    """Separate the mutable canonical CAS observation from its immutable snapshot."""

    if absence is not None:
        if observation is not None or snapshot is not None:
            raise ValueError("canonical absence cannot declare a MaterialPlan observation")
        return
    if observation is None or snapshot is None:
        raise ValueError("existing canonical MaterialPlan requires observation and snapshot")
    if observation.path != "analysis/material_plan.json":
        raise ValueError("canonical MaterialPlan observation path is not canonical")
    if snapshot.path == observation.path:
        raise ValueError("canonical observation and immutable snapshot paths must differ")
    if (
        observation.sha256,
        observation.byte_size,
        observation.media_type,
    ) != (snapshot.sha256, snapshot.byte_size, snapshot.media_type):
        raise ValueError("canonical MaterialPlan observation differs from its snapshot")


def _validate_id_scope(
    targets: list[str],
    mutable: list[str],
    immutable: list[str],
) -> None:
    """Require unique disjoint material scopes and keep targets within mutable IDs."""

    if len(targets) != len(set(targets)) or len(mutable) != len(set(mutable)):
        raise ValueError("target and mutable material IDs must be unique")
    if len(immutable) != len(set(immutable)):
        raise ValueError("immutable material IDs must be unique")
    if not set(targets).issubset(mutable):
        raise ValueError("every target material ID must be mutable")
    if set(mutable) & set(immutable):
        raise ValueError("mutable and immutable material scopes must be disjoint")


def _validate_controller_outputs(
    output_root: str,
    outputs: list[str],
    expected_hashes: dict[str, str],
    *,
    require_expected: bool,
) -> None:
    """Match the existing three-file material controller completion boundary."""

    prefix = output_root.rstrip("/") + "/"
    if len(outputs) != len(set(outputs)) or any(not item.startswith(prefix) for item in outputs):
        raise ValueError("material controller outputs must be unique descendants of output_root")
    names = {item.rsplit("/", 1)[-1] for item in outputs}
    if names != EXPECTED_MATERIAL_CONTROLLER_OUTPUT_NAMES:
        raise ValueError("material controller output set must match existing completion files")
    if set(expected_hashes) - set(outputs):
        raise ValueError("expected controller hashes escape the declared output set")
    if require_expected:
        expected_content_paths = {
            item
            for item in outputs
            if item.rsplit("/", 1)[-1] in {"material_plan.json", "material_graph.json"}
        }
        if set(expected_hashes) != expected_content_paths:
            raise ValueError(
                "exact adoption requires hashes for both content outputs; "
                "completion is lifecycle-bound"
            )


def codex_image_native_output_original_path(
    session_id: str,
    assignment_id: str,
    native_output_id: str,
) -> str:
    """Return the only job-relative leaf allowed to preserve one native PNG."""

    return (
        f"production/autonomy_v2/{session_id}/codex_imagegen/assignments/"
        f"{assignment_id}/native_outputs/{native_output_id}/original.png"
    )


def codex_image_candidate_semantic_review_path(
    session_id: str,
    assignment_id: str,
    ordinal: int,
) -> str:
    """Return the canonical current-task semantic review leaf for one candidate."""

    return (
        f"production/autonomy_v2/{session_id}/codex_imagegen/assignments/"
        f"{assignment_id}/evidence/semantic-review-{ordinal:02d}.json"
    )


def codex_image_candidate_ranking_evidence_path(
    session_id: str,
    assignment_id: str,
    ordinal: int,
) -> str:
    """Return the canonical companion ranking evidence leaf for one candidate."""

    return (
        f"production/autonomy_v2/{session_id}/codex_imagegen/assignments/"
        f"{assignment_id}/evidence/ranking-{ordinal:02d}.json"
    )


def codex_image_companion_selection_receipt_path(
    session_id: str,
    assignment_id: str,
) -> str:
    """Return the aggregate companion ranking receipt beside core selection.json."""

    return (
        f"production/autonomy_v2/{session_id}/codex_imagegen/assignments/"
        f"{assignment_id}/companion-selection.json"
    )


def codex_image_native_output_original_artifact_id(native_output_id: str) -> str:
    """Return a short deterministic artifact ID distinct from caller-owned IDs."""

    return f"native-original-{stable_json_digest(native_output_id)[:16]}"


def codex_image_native_output_adoption_receipt_path(
    session_id: str,
    assignment_id: str,
    native_output_id: str,
) -> str:
    """Return the canonical immutable receipt leaf for one adopted native output."""

    original_path = codex_image_native_output_original_path(
        session_id,
        assignment_id,
        native_output_id,
    )
    return f"{original_path.rsplit('/', 1)[0]}/receipt.json"


def codex_image_native_output_adoption_input_sha256(
    *,
    assignment: CodexImageArtifact,
    assignment_id: str,
    native_output_id: str,
    ordinal: int,
    output_role: str,
    expected_assignment_size: MaterialLoopRasterSize,
    native_size: MaterialLoopRasterSize,
    original_image: CodexImageArtifact,
    source_mode: str,
    source_has_alpha: bool,
    source_icc_profile_sha256: str | None,
) -> str:
    """Hash the exact assignment, original PNG, decoded metadata, and candidate slot."""

    return stable_json_digest(
        {
            "assignment": assignment.model_dump(mode="json"),
            "assignment_id": assignment_id,
            "native_output_id": native_output_id,
            "ordinal": ordinal,
            "output_role": output_role,
            "expected_assignment_size": expected_assignment_size.model_dump(mode="json"),
            "native_size": native_size.model_dump(mode="json"),
            "original_image": original_image.model_dump(mode="json"),
            "source_mode": source_mode,
            "source_has_alpha": source_has_alpha,
            "source_icc_profile_sha256": source_icc_profile_sha256,
        }
    )


def codex_image_native_core_preparation_receipt_path(
    session_id: str,
    assignment_id: str,
    ordinal: int,
) -> str:
    """Return the assignment-owned leaf for one native-to-core closure receipt."""

    return (
        f"production/autonomy_v2/{session_id}/codex_imagegen/assignments/"
        f"{assignment_id}/evidence/native-core-preparation-{ordinal:02d}.json"
    )


def codex_image_native_core_preparation_input_sha256(
    *,
    assignment: CodexImageArtifact,
    native_output_adoption_receipt: CodexImageArtifact,
    native_original_image: CodexImageArtifact,
    normalization_plan: CodexImageArtifact,
    normalization_receipt: CodexImageArtifact,
    normalized_image: CodexImageArtifact,
    core_completion: CodexImageArtifact,
    core_candidate: CodexImageArtifact,
    core_generated_image_evidence: CodexImageArtifact,
    core_quality_report: CodexImageArtifact,
    core_selection: CodexImageArtifact,
    core_generated_image: CodexImageArtifact,
    assignment_id: str,
    candidate_id: str,
    ordinal: int,
    output_role: str,
    target_size: MaterialLoopRasterSize,
) -> str:
    """Hash the exact native, normalization, and selected core evidence closure."""

    artifacts = {
        "assignment": assignment,
        "native_output_adoption_receipt": native_output_adoption_receipt,
        "native_original_image": native_original_image,
        "normalization_plan": normalization_plan,
        "normalization_receipt": normalization_receipt,
        "normalized_image": normalized_image,
        "core_completion": core_completion,
        "core_candidate": core_candidate,
        "core_generated_image_evidence": core_generated_image_evidence,
        "core_quality_report": core_quality_report,
        "core_selection": core_selection,
        "core_generated_image": core_generated_image,
    }
    return stable_json_digest(
        {
            "artifacts": {
                name: artifact.model_dump(mode="json")
                for name, artifact in artifacts.items()
            },
            "assignment_id": assignment_id,
            "candidate_id": candidate_id,
            "ordinal": ordinal,
            "output_role": output_role,
            "target_size": target_size.model_dump(mode="json"),
        }
    )


def imagegen_native_normalization_root_path(session_id: str, contract_id: str) -> str:
    """Return the isolated directory owned by one normalization contract."""

    return (
        f"production/autonomy_v2/{session_id}/codex_imagegen/"
        f"native_normalizations/{contract_id}"
    )


def imagegen_native_normalization_plan_path(session_id: str, contract_id: str) -> str:
    """Return the canonical immutable plan leaf for one normalization run."""

    return f"{imagegen_native_normalization_root_path(session_id, contract_id)}/plan.json"


def imagegen_native_normalization_output_path(session_id: str, contract_id: str) -> str:
    """Return the canonical deterministic PNG leaf for one normalization run."""

    return f"{imagegen_native_normalization_root_path(session_id, contract_id)}/normalized.png"


def imagegen_native_normalization_output_artifact_id(contract_id: str) -> str:
    """Return a bounded derivative artifact ID distinct from the plan contract ID."""

    return f"normalization-output-{stable_json_digest(contract_id)[:16]}"


def imagegen_native_normalization_receipt_path(session_id: str, contract_id: str) -> str:
    """Return the canonical immutable receipt leaf for one normalization run."""

    return f"{imagegen_native_normalization_root_path(session_id, contract_id)}/receipt.json"


def imagegen_native_normalization_plan_input_sha256(
    *,
    source_image: CodexImageArtifact,
    output_path: str,
    source_size: MaterialLoopRasterSize,
    target_size: MaterialLoopRasterSize,
    native_output_policy: str,
    allowed_native_sizes: list[MaterialLoopRasterSize],
    requested_operation: str,
    maximum_automatic_aspect_delta: float,
    source_color_space: str,
    source_mode: str,
    source_has_alpha: bool,
    source_icc_profile_sha256: str | None,
    alpha_policy: str,
    pad_rgba: tuple[int, int, int, int],
) -> str:
    """Hash every caller request and host-observed source field used by planning."""

    return stable_json_digest(
        {
            "source": source_image.model_dump(mode="json"),
            "output_path": output_path,
            "source_size": source_size.model_dump(mode="json"),
            "target_size": target_size.model_dump(mode="json"),
            "native_output_policy": native_output_policy,
            "allowed_native_sizes": [
                item.model_dump(mode="json") for item in allowed_native_sizes
            ],
            "requested_operation": requested_operation,
            "maximum_automatic_aspect_delta": maximum_automatic_aspect_delta,
            "source_color_space": source_color_space,
            "source_mode": source_mode,
            "source_has_alpha": source_has_alpha,
            "source_icc_profile_sha256": source_icc_profile_sha256,
            "alpha_policy": alpha_policy,
            "pad_rgba": pad_rgba,
        }
    )


def canonical_native_normalization_geometry(
    source: MaterialLoopRasterSize,
    target: MaterialLoopRasterSize,
    *,
    requested_operation: NormalizationPreference,
    maximum_automatic_aspect_delta: float,
    alpha_policy: Literal["preserve", "drop", "opaque_add"],
) -> tuple[
    NormalizationOperation,
    ImageGenCropRectangle | None,
    MaterialLoopRasterSize | None,
    ImageGenPadding | None,
]:
    """Recompute the one canonical non-stretch crop or contain geometry."""

    source_aspect = source.width / source.height
    target_aspect = target.width / target.height
    aspect_delta = abs(source_aspect / target_aspect - 1.0)
    if aspect_delta > maximum_automatic_aspect_delta:
        return "review_required", None, None, None
    if source == target and alpha_policy == "preserve":
        return "pass_through", None, None, None
    if requested_operation == "contain_pad":
        scale = min(target.width / source.width, target.height / source.height)
        content = MaterialLoopRasterSize(
            width=max(1, min(target.width, round(source.width * scale))),
            height=max(1, min(target.height, round(source.height * scale))),
        )
        horizontal = target.width - content.width
        vertical = target.height - content.height
        padding = ImageGenPadding(
            left=horizontal // 2,
            right=horizontal - horizontal // 2,
            top=vertical // 2,
            bottom=vertical - vertical // 2,
        )
        return "contain_pad", None, content, padding
    target_aspect = target.width / target.height
    if source.width / source.height > target_aspect:
        crop_width = max(1, round(source.height * target_aspect))
        crop_height = source.height
    else:
        crop_width = source.width
        crop_height = max(1, round(source.width / target_aspect))
    crop = ImageGenCropRectangle(
        x=(source.width - crop_width) // 2 if requested_operation == "center_crop" else 0,
        y=(source.height - crop_height) // 2 if requested_operation == "center_crop" else 0,
        width=crop_width,
        height=crop_height,
    )
    return requested_operation, crop, None, None


def _validate_native_size_policy(plan: ImageGenNativeNormalizationPlan) -> None:
    """Require declared native-size policy to match the observed exact source size."""

    allowed = {(item.width, item.height) for item in plan.allowed_native_sizes}
    if len(allowed) != len(plan.allowed_native_sizes):
        raise ValueError("allowed native sizes must be unique")
    source = (plan.source_size.width, plan.source_size.height)
    if plan.native_output_policy == "exact_known_size":
        if len(allowed) != 1 or source not in allowed:
            raise ValueError("exact-known native policy requires its one observed size")
    elif plan.native_output_policy == "allowed_size_set":
        if not allowed or source not in allowed:
            raise ValueError("observed native size is outside the allowed size set")
    elif plan.allowed_native_sizes:
        raise ValueError("bounded/preserve native policies do not accept an exact size set")


def _validate_normalization_operation(plan: ImageGenNativeNormalizationPlan) -> None:
    """Require operation-specific crop, contain, padding, and review geometry."""

    expected = canonical_native_normalization_geometry(
        plan.source_size,
        plan.target_size,
        requested_operation=plan.requested_operation,
        maximum_automatic_aspect_delta=plan.maximum_automatic_aspect_delta,
        alpha_policy=plan.alpha_policy,
    )
    observed = (
        plan.operation,
        plan.crop_rectangle,
        plan.content_size,
        plan.padding,
    )
    if observed != expected:
        raise ValueError("normalization geometry differs from canonical replay")
    expected_media_type = (
        "source_media_type" if plan.operation == "pass_through" else "image/png"
    )
    if plan.output_media_type != expected_media_type:
        raise ValueError("normalization output media type differs from canonical replay")


__all__ = [
    "ALL_SEMANTIC_REVIEW_CATEGORIES",
    "CodexImageNativeCorePreparationReceipt",
    "CodexImageNativeOutputAdoptionReceipt",
    "CodexImageCandidateRankingEvidence",
    "CodexImageCompanionCandidateDecision",
    "CodexImageCompanionSelectionReceipt",
    "CodexImageMaterialLoopState",
    "CodexImageMaterialLoopTerminal",
    "CodexImageSemanticCheck",
    "CodexImageSemanticReview",
    "CodexImageV05ExactAdoptionPreflightReceipt",
    "EXPECTED_MATERIAL_CONTROLLER_OUTPUT_NAMES",
    "ImageGenCropRectangle",
    "ImageGeneratedMaterialBridgePlan",
    "ImageGeneratedMaterialControllerBinding",
    "ImageGeneratedMaterialControllerInput",
    "ImageGeneratedMaterialNeutralPreview",
    "ImageGeneratedMaterialPromotionReceipt",
    "ImageGenNativeNormalizationPlan",
    "ImageGenNativeNormalizationReceipt",
    "ImageGenPadding",
    "ImageMaterialLoopBudgetUsage",
    "MATERIAL_LOOP_SCHEMA_VERSION",
    "MaterialLoopRasterSize",
    "MaterialRoleSuitability",
    "NormalizationPreference",
    "canonical_native_normalization_geometry",
    "candidate_ranking_input_sha256",
    "companion_candidate_precedence_key",
    "companion_selection_receipt_input_sha256",
    "codex_image_native_core_preparation_input_sha256",
    "codex_image_native_core_preparation_receipt_path",
    "codex_image_native_output_adoption_input_sha256",
    "codex_image_candidate_ranking_evidence_path",
    "codex_image_candidate_semantic_review_path",
    "codex_image_companion_selection_receipt_path",
    "codex_image_native_output_adoption_receipt_path",
    "codex_image_native_output_original_artifact_id",
    "codex_image_native_output_original_path",
    "codex_image_v05_exact_adoption_preflight_receipt_path",
    "codex_image_v05_exact_adoption_preflight_root_path",
    "exact_adoption_preflight_input_sha256",
    "imagegen_native_normalization_output_artifact_id",
    "imagegen_native_normalization_output_path",
    "imagegen_native_normalization_plan_input_sha256",
    "imagegen_native_normalization_plan_path",
    "imagegen_native_normalization_receipt_path",
    "imagegen_native_normalization_root_path",
    "material_loop_state_input_sha256",
    "semantic_review_outcome",
    "validate_material_loop_transition",
]
