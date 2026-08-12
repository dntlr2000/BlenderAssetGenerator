"""Checked-in schema parity for top-level Codex ImageGen companion contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from codex_blender_modeler.autonomy_v2.codex_image_overlay import (
    AutonomyCodexImageOverlay,
)
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    CodexImageCandidateRankingEvidence,
    CodexImageCompanionSelectionReceipt,
    CodexImageMaterialLoopState,
    CodexImageMaterialLoopTerminal,
    CodexImageNativeCorePreparationReceipt,
    CodexImageNativeOutputAdoptionReceipt,
    CodexImageSemanticReview,
    CodexImageV05ExactAdoptionPreflightReceipt,
    ImageGeneratedMaterialBridgePlan,
    ImageGeneratedMaterialControllerBinding,
    ImageGeneratedMaterialControllerInput,
    ImageGeneratedMaterialNeutralPreview,
    ImageGeneratedMaterialPromotionReceipt,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
)
from codex_blender_modeler.codex_imagegen.models import (
    CodexBuiltinImageProviderProfile,
    CodexGeneratedImageEvidence,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationPlan,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    CodexImageGenerationTerminal,
    ImageToMaterialAdoption,
)
from codex_blender_modeler.material_authoring.codex_image_models import (
    CodexImageAuthoredMaterialManifestV021,
    CodexImageMaterialAuthoringReceiptV021,
    CodexImageMaterialAuthoringRequestV021,
    ExactSignageTextEvidenceV021,
)
from codex_blender_modeler.material_authoring.codex_image_normalized_models import (
    CodexImageNormalizedAuthoredMaterialManifestV010,
    CodexImageNormalizedMaterialAuthoringReceiptV010,
    CodexImageNormalizedMaterialAuthoringRequestV010,
)
from codex_blender_modeler.material_authoring.codex_image_v05_bridge import (
    CodexImageV05BridgeReceipt,
    CodexImageV05CanonicalMaterialAbsence,
    CodexImageV05ControllerBlueprint,
)

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "autonomy_codex_image_overlay.schema.json": AutonomyCodexImageOverlay,
    "codex_builtin_image_provider_profile.schema.json": (
        CodexBuiltinImageProviderProfile
    ),
    "codex_image_generation_budget.schema.json": CodexImageGenerationBudget,
    "codex_image_generation_plan.schema.json": CodexImageGenerationPlan,
    "codex_image_generation_assignment.schema.json": CodexImageGenerationAssignment,
    "codex_image_generation_completion.schema.json": CodexImageGenerationCompletion,
    "codex_generated_image_evidence.schema.json": CodexGeneratedImageEvidence,
    "codex_image_generation_candidate.schema.json": CodexImageGenerationCandidate,
    "codex_image_generation_quality_report.schema.json": (
        CodexImageGenerationQualityReport
    ),
    "codex_image_generation_selection.schema.json": CodexImageGenerationSelection,
    "codex_image_generation_terminal.schema.json": CodexImageGenerationTerminal,
    "image_to_material_adoption.schema.json": ImageToMaterialAdoption,
    "material_authoring_codex_image_request_v021.schema.json": (
        CodexImageMaterialAuthoringRequestV021
    ),
    "material_authoring_codex_image_manifest_v021.schema.json": (
        CodexImageAuthoredMaterialManifestV021
    ),
    "material_authoring_codex_image_receipt_v021.schema.json": (
        CodexImageMaterialAuthoringReceiptV021
    ),
    "exact_signage_text_evidence_v021.schema.json": ExactSignageTextEvidenceV021,
    "material_authoring_codex_image_normalized_request_0_1_0.schema.json": (
        CodexImageNormalizedMaterialAuthoringRequestV010
    ),
    "material_authoring_codex_image_normalized_manifest_0_1_0.schema.json": (
        CodexImageNormalizedAuthoredMaterialManifestV010
    ),
    "material_authoring_codex_image_normalized_receipt_0_1_0.schema.json": (
        CodexImageNormalizedMaterialAuthoringReceiptV010
    ),
    "image_generated_material_bridge_plan_0_1_0.schema.json": (
        ImageGeneratedMaterialBridgePlan
    ),
    "image_generated_material_controller_input_0_1_0.schema.json": (
        ImageGeneratedMaterialControllerInput
    ),
    "image_generated_material_controller_binding_0_1_0.schema.json": (
        ImageGeneratedMaterialControllerBinding
    ),
    "image_generated_material_promotion_receipt_0_1_0.schema.json": (
        ImageGeneratedMaterialPromotionReceipt
    ),
    "image_generated_material_neutral_preview_0_1_0.schema.json": (
        ImageGeneratedMaterialNeutralPreview
    ),
    "imagegen_native_normalization_plan_0_1_0.schema.json": (
        ImageGenNativeNormalizationPlan
    ),
    "imagegen_native_normalization_receipt_0_1_0.schema.json": (
        ImageGenNativeNormalizationReceipt
    ),
    "codex_image_semantic_review_0_1_0.schema.json": CodexImageSemanticReview,
    "codex_image_candidate_ranking_evidence_0_1_0.schema.json": (
        CodexImageCandidateRankingEvidence
    ),
    "codex_image_companion_selection_receipt_0_1_0.schema.json": (
        CodexImageCompanionSelectionReceipt
    ),
    "codex_image_material_loop_terminal_0_1_0.schema.json": (
        CodexImageMaterialLoopTerminal
    ),
    "codex_image_material_loop_state_0_1_0.schema.json": CodexImageMaterialLoopState,
    "codex_image_native_output_adoption_receipt_0_1_0.schema.json": (
        CodexImageNativeOutputAdoptionReceipt
    ),
    "codex_image_native_core_preparation_receipt_0_1_0.schema.json": (
        CodexImageNativeCorePreparationReceipt
    ),
    "codex_image_v05_exact_adoption_preflight_receipt_0_1_0.schema.json": (
        CodexImageV05ExactAdoptionPreflightReceipt
    ),
    "codex_image_v05_controller_blueprint_0_1_0.schema.json": (
        CodexImageV05ControllerBlueprint
    ),
    "codex_image_v05_bridge_receipt_0_1_0.schema.json": CodexImageV05BridgeReceipt,
    "codex_image_v05_canonical_material_absence_0_1_0.schema.json": (
        CodexImageV05CanonicalMaterialAbsence
    ),
}


@pytest.mark.parametrize(("filename", "model"), sorted(SCHEMA_MODELS.items()))
def test_checked_in_codex_imagegen_schema_matches_model(
    filename: str,
    model: type[BaseModel],
) -> None:
    """Keep each generated schema byte-semantically equal to its strict model."""

    checked_in = json.loads((Path("schemas") / filename).read_text(encoding="utf-8"))
    assert checked_in == model.model_json_schema()
    assert checked_in["additionalProperties"] is False


def test_top_level_schema_versions_remain_additive() -> None:
    """Keep ImageGen at 0.1.0 and material adoption at its 0.2.0 companion version."""

    for filename, model in SCHEMA_MODELS.items():
        if filename in {
            "material_authoring_codex_image_request_v021.schema.json",
            "material_authoring_codex_image_manifest_v021.schema.json",
            "material_authoring_codex_image_receipt_v021.schema.json",
            "exact_signage_text_evidence_v021.schema.json",
        }:
            expected = "0.2.1"
        elif filename == "image_to_material_adoption.schema.json":
            expected = "0.2.0"
        else:
            expected = "0.1.0"
        assert model.model_json_schema()["properties"]["schema_version"]["const"] == expected
