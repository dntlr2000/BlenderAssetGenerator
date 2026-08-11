"""Strict selected-image adoption for later local material authoring."""

from __future__ import annotations

from datetime import datetime

from ..blender_artifacts import stable_json_digest
from .models import (
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationCandidate,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    DerivedChannelEvidence,
    ImageToMaterialAdoption,
)


def build_image_to_material_adoption(
    *,
    contract_id: str,
    adoption_id: str,
    selection: CodexImageGenerationSelection,
    selection_artifact: CodexImageArtifact,
    candidate: CodexImageGenerationCandidate,
    candidate_artifact: CodexImageArtifact,
    generated_image_evidence: CodexGeneratedImageEvidence,
    generated_image_evidence_artifact: CodexImageArtifact,
    quality_report: CodexImageGenerationQualityReport,
    quality_report_artifact: CodexImageArtifact,
    material_strategy: str,
    direct_channels: list[str],
    derived_channels: list[DerivedChannelEvidence],
    created_at: datetime,
    exact_text_composition: CodexImageArtifact | None = None,
) -> ImageToMaterialAdoption:
    """Bind one selected raster to local material inputs without canonical writes."""

    if selection.outcome != "selected":
        raise ValueError("material adoption requires a selected outcome")
    if selection.selected_candidate != candidate_artifact:
        raise ValueError("adoption candidate differs from the selection")
    if selection.selected_quality_report != quality_report_artifact:
        raise ValueError("adoption quality report differs from the selection")
    if not quality_report.selection_eligible or quality_report.outcome != "passed":
        raise ValueError("material adoption requires a passed eligible quality report")
    if generated_image_evidence.candidate != candidate_artifact:
        raise ValueError("adoption generated evidence differs from the candidate")
    if quality_report.candidate != candidate_artifact:
        raise ValueError("adoption quality report differs from the candidate")
    _validate_direct_channels(candidate, direct_channels)
    selected_sha256 = candidate.generated_file.artifact.sha256
    if any(item.source_sha256 != selected_sha256 for item in derived_channels):
        raise ValueError("locally derived channels must bind the selected source hash")
    provenance = _unique_artifacts(
        [
            selection_artifact,
            candidate_artifact,
            generated_image_evidence_artifact,
            quality_report_artifact,
            candidate.generated_file.artifact,
            *[item.output for item in derived_channels],
            *([exact_text_composition] if exact_text_composition is not None else []),
        ]
    )
    inputs = {
        "selection": selection_artifact.model_dump(mode="json"),
        "candidate": candidate_artifact.model_dump(mode="json"),
        "generated_image_evidence": generated_image_evidence_artifact.model_dump(
            mode="json"
        ),
        "quality_report": quality_report_artifact.model_dump(mode="json"),
        "material_strategy": material_strategy,
        "direct_channels": direct_channels,
        "derived_channels": [item.model_dump(mode="json") for item in derived_channels],
        "exact_text_composition": (
            exact_text_composition.model_dump(mode="json")
            if exact_text_composition is not None
            else None
        ),
    }
    return ImageToMaterialAdoption(
        contract_id=contract_id,
        adoption_id=adoption_id,
        job_id=selection.job_id,
        workflow_id=selection.workflow_id,
        dispatch_id=selection.dispatch_id,
        session_id=selection.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "selected_source_sha256": selected_sha256}
        ),
        producer="codex_blender_modeler.codex_imagegen.adoption",
        provenance=provenance,
        created_at=created_at,
        selection=selection_artifact,
        selected_candidate=candidate_artifact,
        generated_image_evidence=generated_image_evidence_artifact,
        quality_report=quality_report_artifact,
        selected_source_sha256=selected_sha256,
        target_material_ids=list(candidate.target_material_ids),
        material_strategy=material_strategy,
        direct_channels=direct_channels,
        derived_channels=derived_channels,
        exact_text_composition=exact_text_composition,
    )


def _validate_direct_channels(
    candidate: CodexImageGenerationCandidate,
    direct_channels: list[str],
) -> None:
    """Restrict adoption to the generated role plus extractable embedded opacity."""

    if not direct_channels:
        raise ValueError("material adoption requires at least one direct channel")
    allowed = {candidate.generated_file.output_role}
    if candidate.generated_file.alpha_present:
        allowed.add("opacity_source")
    if not set(direct_channels).issubset(allowed):
        raise ValueError("adoption direct channels are not present in selected pixels")
    if len(direct_channels) != len(set(direct_channels)):
        raise ValueError("adoption direct channels must be unique")


def _unique_artifacts(items: list[CodexImageArtifact]) -> list[CodexImageArtifact]:
    """Preserve provenance order while removing byte-identical bindings."""

    result: list[CodexImageArtifact] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.path, item.sha256, item.kind)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result
