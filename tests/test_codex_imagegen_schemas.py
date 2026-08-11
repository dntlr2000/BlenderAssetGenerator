"""Checked-in schema parity for top-level Codex ImageGen companion contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from codex_blender_modeler.autonomy_v2.codex_image_overlay import (
    AutonomyCodexImageOverlay,
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
        if filename.startswith("material_authoring_codex_image_") or filename == (
            "exact_signage_text_evidence_v021.schema.json"
        ):
            expected = "0.2.1"
        elif filename == "image_to_material_adoption.schema.json":
            expected = "0.2.0"
        else:
            expected = "0.1.0"
        assert model.model_json_schema()["properties"]["schema_version"]["const"] == expected
