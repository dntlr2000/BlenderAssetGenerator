"""Strict additive provenance closure for native outputs entering core ImageGen 0.1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..blender_artifacts import native_io_path, sha256_file
from .artifacts import (
    artifact_for_codex_image,
    ensure_contained_codex_image_path,
    load_codex_image_model,
    validate_codex_image_artifact,
    write_immutable_codex_image_model,
)
from .assignment import validate_codex_imagegen_assignment_boundary
from .completion import validate_codex_imagegen_completion
from .material_loop_models import (
    CodexImageNativeCorePreparationReceipt,
    CodexImageNativeOutputAdoptionReceipt,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
    MaterialLoopRasterSize,
    codex_image_native_core_preparation_input_sha256,
    codex_image_native_core_preparation_receipt_path,
)
from .material_loop_normalization import validate_native_normalization_receipt
from .models import (
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    DirectOutputRole,
)
from .native_output_adoption import validate_codex_image_native_output_adoption

_PREPARATION_KIND = "codex-image-native-core-preparation-receipt"


@dataclass(frozen=True)
class NativeCorePreparationResult:
    """Return one immutable native-to-core closure and its exact artifact binding."""

    receipt: CodexImageNativeCorePreparationReceipt
    receipt_artifact: CodexImageArtifact


@dataclass(frozen=True)
class _NativeCoreChain:
    """Hold recursively validated native, normalization, and selected core models."""

    assignment: CodexImageGenerationAssignment
    adoption: CodexImageNativeOutputAdoptionReceipt
    normalization_plan: ImageGenNativeNormalizationPlan
    normalization: ImageGenNativeNormalizationReceipt
    completion: CodexImageGenerationCompletion
    candidate: CodexImageGenerationCandidate
    generated_evidence: CodexGeneratedImageEvidence
    quality_report: CodexImageGenerationQualityReport
    selection: CodexImageGenerationSelection


def build_codex_image_native_core_preparation_receipt(
    *,
    job_root: Path,
    preparation_id: str,
    assignment_artifact: CodexImageArtifact,
    native_output_adoption_receipt: CodexImageArtifact,
    normalization_plan: CodexImageArtifact,
    normalization_receipt: CodexImageArtifact,
    core_completion: CodexImageArtifact,
    core_candidate: CodexImageArtifact,
    core_generated_image_evidence: CodexImageArtifact,
    core_quality_report: CodexImageArtifact,
    core_selection: CodexImageArtifact,
    created_at: datetime,
) -> CodexImageNativeCorePreparationReceipt:
    """Build a receipt only after recursively replaying the complete selected chain."""

    chain = _load_native_core_chain(
        job_root,
        assignment_artifact=assignment_artifact,
        native_output_adoption_receipt=native_output_adoption_receipt,
        normalization_plan=normalization_plan,
        normalization_receipt=normalization_receipt,
        core_completion=core_completion,
        core_candidate=core_candidate,
        core_generated_image_evidence=core_generated_image_evidence,
        core_quality_report=core_quality_report,
        core_selection=core_selection,
    )
    generated_file = chain.candidate.generated_file
    normalized_image = chain.normalization.normalized_image
    if normalized_image is None:
        raise ValueError("native core preparation has no normalized image")
    artifacts = [
        assignment_artifact,
        native_output_adoption_receipt,
        chain.adoption.original_image,
        normalization_plan,
        normalization_receipt,
        normalized_image,
        core_completion,
        core_candidate,
        core_generated_image_evidence,
        core_quality_report,
        core_selection,
        generated_file.artifact,
    ]
    target_size = MaterialLoopRasterSize(
        width=chain.assignment.image_size.width,
        height=chain.assignment.image_size.height,
    )
    input_sha256 = codex_image_native_core_preparation_input_sha256(
        assignment=assignment_artifact,
        native_output_adoption_receipt=native_output_adoption_receipt,
        native_original_image=chain.adoption.original_image,
        normalization_plan=normalization_plan,
        normalization_receipt=normalization_receipt,
        normalized_image=normalized_image,
        core_completion=core_completion,
        core_candidate=core_candidate,
        core_generated_image_evidence=core_generated_image_evidence,
        core_quality_report=core_quality_report,
        core_selection=core_selection,
        core_generated_image=generated_file.artifact,
        assignment_id=chain.assignment.assignment_id,
        candidate_id=chain.candidate.candidate_id,
        ordinal=generated_file.ordinal,
        output_role=generated_file.output_role,
        target_size=target_size,
    )
    return CodexImageNativeCorePreparationReceipt(
        contract_id=preparation_id,
        preparation_id=preparation_id,
        job_id=chain.assignment.job_id,
        workflow_id=chain.assignment.workflow_id,
        dispatch_id=chain.assignment.dispatch_id,
        session_id=chain.assignment.session_id,
        input_sha256=input_sha256,
        source_fingerprint=chain.adoption.original_image.sha256,
        producer="codex_blender_modeler.codex_imagegen.native_core_preparation",
        provenance=artifacts,
        created_at=created_at,
        assignment_id=chain.assignment.assignment_id,
        candidate_id=chain.candidate.candidate_id,
        assignment=assignment_artifact,
        native_output_adoption_receipt=native_output_adoption_receipt,
        native_original_image=chain.adoption.original_image,
        normalization_plan=normalization_plan,
        normalization_receipt=normalization_receipt,
        normalized_image=normalized_image,
        core_completion=core_completion,
        core_candidate=core_candidate,
        core_generated_image_evidence=core_generated_image_evidence,
        core_quality_report=core_quality_report,
        core_selection=core_selection,
        core_generated_image=generated_file.artifact,
        ordinal=generated_file.ordinal,
        output_role=generated_file.output_role,
        target_size=target_size,
    )


def publish_codex_image_native_core_preparation_receipt(
    *,
    job_root: Path,
    preparation_id: str,
    assignment_artifact: CodexImageArtifact,
    native_output_adoption_receipt: CodexImageArtifact,
    normalization_plan: CodexImageArtifact,
    normalization_receipt: CodexImageArtifact,
    core_completion: CodexImageArtifact,
    core_candidate: CodexImageArtifact,
    core_generated_image_evidence: CodexImageArtifact,
    core_quality_report: CodexImageArtifact,
    core_selection: CodexImageArtifact,
    created_at: datetime,
) -> NativeCorePreparationResult:
    """Publish or exactly resume the assignment-owned native-to-core receipt."""

    requested = build_codex_image_native_core_preparation_receipt(
        job_root=job_root,
        preparation_id=preparation_id,
        assignment_artifact=assignment_artifact,
        native_output_adoption_receipt=native_output_adoption_receipt,
        normalization_plan=normalization_plan,
        normalization_receipt=normalization_receipt,
        core_completion=core_completion,
        core_candidate=core_candidate,
        core_generated_image_evidence=core_generated_image_evidence,
        core_quality_report=core_quality_report,
        core_selection=core_selection,
        created_at=created_at,
    )
    destination = job_root / codex_image_native_core_preparation_receipt_path(
        requested.session_id,
        requested.assignment_id,
        requested.ordinal,
    )
    if os.path.exists(native_io_path(destination)):
        artifact = artifact_for_codex_image(
            job_root,
            destination,
            artifact_id=preparation_id,
            kind=_PREPARATION_KIND,
            media_type="application/json",
        )
        existing = validate_codex_image_native_core_preparation_receipt(
            job_root,
            artifact,
        )
        if existing.model_dump(mode="json", exclude={"created_at"}) != (
            requested.model_dump(mode="json", exclude={"created_at"})
        ):
            raise FileExistsError("existing native core preparation receipt differs")
        return NativeCorePreparationResult(existing, artifact)
    artifact = write_immutable_codex_image_model(
        job_root,
        destination,
        requested,
        kind=_PREPARATION_KIND,
    )
    validated = validate_codex_image_native_core_preparation_receipt(job_root, artifact)
    return NativeCorePreparationResult(validated, artifact)


def validate_codex_image_native_core_preparation_receipt(
    job_root: Path,
    receipt_artifact: CodexImageArtifact,
) -> CodexImageNativeCorePreparationReceipt:
    """Rehash and recursively replay one published native-to-core closure receipt."""

    receipt = load_codex_image_model(
        job_root,
        receipt_artifact,
        CodexImageNativeCorePreparationReceipt,
    )
    expected_path = codex_image_native_core_preparation_receipt_path(
        receipt.session_id,
        receipt.assignment_id,
        receipt.ordinal,
    )
    if (
        receipt_artifact.path != expected_path
        or receipt_artifact.artifact_id != receipt.contract_id
        or receipt_artifact.kind != _PREPARATION_KIND
    ):
        raise ValueError("native core preparation receipt artifact identity is inconsistent")
    chain = _load_native_core_chain(
        job_root,
        assignment_artifact=receipt.assignment,
        native_output_adoption_receipt=receipt.native_output_adoption_receipt,
        normalization_plan=receipt.normalization_plan,
        normalization_receipt=receipt.normalization_receipt,
        core_completion=receipt.core_completion,
        core_candidate=receipt.core_candidate,
        core_generated_image_evidence=receipt.core_generated_image_evidence,
        core_quality_report=receipt.core_quality_report,
        core_selection=receipt.core_selection,
    )
    generated_file = chain.candidate.generated_file
    normalized_image = chain.normalization.normalized_image
    expected_target = MaterialLoopRasterSize(
        width=chain.assignment.image_size.width,
        height=chain.assignment.image_size.height,
    )
    if normalized_image is None:
        raise ValueError("native core preparation normalization has no output")
    if (
        receipt.assignment_id != chain.assignment.assignment_id
        or receipt.candidate_id != chain.candidate.candidate_id
        or receipt.native_original_image != chain.adoption.original_image
        or receipt.normalized_image != normalized_image
        or receipt.core_generated_image != generated_file.artifact
        or receipt.ordinal != generated_file.ordinal
        or receipt.output_role != generated_file.output_role
        or receipt.target_size != expected_target
    ):
        raise ValueError("native core preparation recursive identity changed")
    return receipt


def validate_native_core_preparation_binding(
    *,
    job_root: Path,
    assignment_artifact: CodexImageArtifact,
    core_completion: CodexImageArtifact,
    core_candidate: CodexImageArtifact,
    core_generated_image_evidence: CodexImageArtifact,
    core_quality_report: CodexImageArtifact,
    core_selection: CodexImageArtifact,
    preparation_receipt: CodexImageArtifact | None,
) -> CodexImageNativeCorePreparationReceipt | None:
    """Require closure for native-origin bytes while preserving legacy direct generation."""

    assignment, completion, candidate, generated, quality, selection = (
        _load_selected_core_chain(
            job_root,
            assignment_artifact=assignment_artifact,
            core_completion=core_completion,
            core_candidate=core_candidate,
            core_generated_image_evidence=core_generated_image_evidence,
            core_quality_report=core_quality_report,
            core_selection=core_selection,
        )
    )
    generated_file = candidate.generated_file
    origins = _matching_native_normalization_origins(
        job_root,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        generated_image=generated_file.artifact,
        ordinal=generated_file.ordinal,
        output_role=generated_file.output_role,
    )
    expected_path = codex_image_native_core_preparation_receipt_path(
        assignment.session_id,
        assignment.assignment_id,
        generated_file.ordinal,
    )
    canonical_exists = os.path.isfile(native_io_path(job_root / expected_path))
    if preparation_receipt is None:
        if origins or canonical_exists:
            raise ValueError("native pre-core normalization origin is orphaned from bridge")
        return None
    receipt = validate_codex_image_native_core_preparation_receipt(
        job_root,
        preparation_receipt,
    )
    if len(origins) != 1:
        raise ValueError("native core preparation requires one exact normalization origin")
    if (
        receipt.assignment != assignment_artifact
        or receipt.core_completion != core_completion
        or receipt.core_candidate != core_candidate
        or receipt.core_generated_image_evidence != core_generated_image_evidence
        or receipt.core_quality_report != core_quality_report
        or receipt.core_selection != core_selection
        or receipt.normalization_receipt != origins[0]
        or receipt.core_generated_image != generated_file.artifact
        or receipt.candidate_id != candidate.candidate_id
    ):
        raise ValueError("native core preparation differs from selected bridge evidence")
    if generated.candidate != core_candidate or quality.candidate != core_candidate:
        raise ValueError("native core preparation selected evidence changed")
    if selection.selected_candidate != core_candidate:
        raise ValueError("native core preparation selection changed")
    if completion.generated_files[generated_file.ordinal] != generated_file:
        raise ValueError("native core preparation completion slot changed")
    return receipt


def _load_native_core_chain(
    job_root: Path,
    *,
    assignment_artifact: CodexImageArtifact,
    native_output_adoption_receipt: CodexImageArtifact,
    normalization_plan: CodexImageArtifact,
    normalization_receipt: CodexImageArtifact,
    core_completion: CodexImageArtifact,
    core_candidate: CodexImageArtifact,
    core_generated_image_evidence: CodexImageArtifact,
    core_quality_report: CodexImageArtifact,
    core_selection: CodexImageArtifact,
) -> _NativeCoreChain:
    """Load and cross-check the native prefix plus the selected core chain."""

    assignment, completion, candidate, generated, quality, selection = (
        _load_selected_core_chain(
            job_root,
            assignment_artifact=assignment_artifact,
            core_completion=core_completion,
            core_candidate=core_candidate,
            core_generated_image_evidence=core_generated_image_evidence,
            core_quality_report=core_quality_report,
            core_selection=core_selection,
        )
    )
    adoption = load_codex_image_model(
        job_root,
        native_output_adoption_receipt,
        CodexImageNativeOutputAdoptionReceipt,
    )
    validate_codex_image_native_output_adoption(
        job_root,
        adoption,
        require_current_protected_inventory=False,
    )
    plan = load_codex_image_model(
        job_root,
        normalization_plan,
        ImageGenNativeNormalizationPlan,
    )
    normalization = load_codex_image_model(
        job_root,
        normalization_receipt,
        ImageGenNativeNormalizationReceipt,
    )
    validate_native_normalization_receipt(
        job_root,
        plan,
        normalization,
        require_current_protected_inventory=False,
    )
    generated_file = candidate.generated_file
    target_size = (assignment.image_size.width, assignment.image_size.height)
    normalized_image = normalization.normalized_image
    if (
        adoption.assignment != assignment_artifact
        or adoption.assignment_id != assignment.assignment_id
        or adoption.ordinal != generated_file.ordinal
        or adoption.output_role != generated_file.output_role
        or (adoption.expected_assignment_size.width, adoption.expected_assignment_size.height)
        != target_size
    ):
        raise ValueError("native adoption differs from the selected core slot")
    if (
        plan.source_image != adoption.original_image
        or normalization.plan != normalization_plan
        or normalization.source_image != adoption.original_image
        or normalization.native_output_adoption_receipt
        != native_output_adoption_receipt
        or normalized_image is None
        or normalization.status == "review_required"
        or (plan.target_size.width, plan.target_size.height) != target_size
        or (normalization.target_size.width, normalization.target_size.height)
        != target_size
    ):
        raise ValueError("native normalization differs from its adoption or core target")
    if (
        normalized_image.sha256,
        normalized_image.byte_size,
        normalized_image.media_type,
    ) != (
        generated_file.artifact.sha256,
        generated_file.artifact.byte_size,
        generated_file.artifact.media_type,
    ):
        raise ValueError("native normalized bytes differ from selected core bytes")
    _validate_common_identity(
        assignment,
        adoption,
        plan,
        normalization,
        completion,
        candidate,
        generated,
        quality,
        selection,
    )
    return _NativeCoreChain(
        assignment=assignment,
        adoption=adoption,
        normalization_plan=plan,
        normalization=normalization,
        completion=completion,
        candidate=candidate,
        generated_evidence=generated,
        quality_report=quality,
        selection=selection,
    )


def _load_selected_core_chain(
    job_root: Path,
    *,
    assignment_artifact: CodexImageArtifact,
    core_completion: CodexImageArtifact,
    core_candidate: CodexImageArtifact,
    core_generated_image_evidence: CodexImageArtifact,
    core_quality_report: CodexImageArtifact,
    core_selection: CodexImageArtifact,
) -> tuple[
    CodexImageGenerationAssignment,
    CodexImageGenerationCompletion,
    CodexImageGenerationCandidate,
    CodexGeneratedImageEvidence,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
]:
    """Replay the unchanged core 0.1 models and selected-candidate cross-links."""

    assignment = load_codex_image_model(
        job_root,
        assignment_artifact,
        CodexImageGenerationAssignment,
    )
    validate_codex_imagegen_assignment_boundary(
        job_root,
        assignment,
        require_current_protected_inventory=False,
    )
    _validated_assignment, completion, _paths = validate_codex_imagegen_completion(
        job_root=job_root,
        assignment_artifact=assignment_artifact,
        completion_artifact=core_completion,
        require_current_protected_inventory=False,
    )
    candidate = load_codex_image_model(
        job_root,
        core_candidate,
        CodexImageGenerationCandidate,
    )
    generated = load_codex_image_model(
        job_root,
        core_generated_image_evidence,
        CodexGeneratedImageEvidence,
    )
    quality = load_codex_image_model(
        job_root,
        core_quality_report,
        CodexImageGenerationQualityReport,
    )
    selection = load_codex_image_model(
        job_root,
        core_selection,
        CodexImageGenerationSelection,
    )
    for envelope in (assignment, completion, candidate, generated, quality, selection):
        for artifact in envelope.provenance:
            validate_codex_image_artifact(job_root, artifact)
    ordinal = candidate.generated_file.ordinal
    if ordinal >= len(completion.generated_files):
        raise ValueError("selected core candidate ordinal is outside completion")
    if (
        candidate.assignment != assignment_artifact
        or candidate.completion != core_completion
        or candidate.generated_file != completion.generated_files[ordinal]
        or generated.assignment != assignment_artifact
        or generated.completion != core_completion
        or generated.candidate != core_candidate
        or generated.generated_file != candidate.generated_file
        or quality.assignment != assignment_artifact
        or quality.completion != core_completion
        or quality.candidate != core_candidate
        or quality.generated_image_evidence != core_generated_image_evidence
        or not quality.selection_eligible
        or selection.assignment != assignment_artifact
        or selection.completion != core_completion
        or selection.outcome != "selected"
        or selection.selected_candidate != core_candidate
        or selection.selected_quality_report != core_quality_report
    ):
        raise ValueError("native preparation core selection closure changed")
    _validate_common_identity(
        assignment,
        completion,
        candidate,
        generated,
        quality,
        selection,
    )
    return assignment, completion, candidate, generated, quality, selection


def _matching_native_normalization_origins(
    job_root: Path,
    *,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    generated_image: CodexImageArtifact,
    ordinal: int,
    output_role: DirectOutputRole,
) -> list[CodexImageArtifact]:
    """Find validated same-assignment native normalizations that match selected bytes."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    normalizations_root = (
        root
        / "production"
        / "autonomy_v2"
        / assignment.session_id
        / "codex_imagegen"
        / "native_normalizations"
    )
    normalizations_root = ensure_contained_codex_image_path(
        root,
        normalizations_root,
        must_exist=False,
    )
    if not os.path.exists(native_io_path(normalizations_root)):
        return []
    normalizations_root = ensure_contained_codex_image_path(
        root,
        normalizations_root,
        must_exist=True,
    )
    if not os.path.isdir(native_io_path(normalizations_root)):
        raise ValueError("native normalization evidence root is not a directory")
    matches: list[CodexImageArtifact] = []
    for contract_name in sorted(os.listdir(native_io_path(normalizations_root))):
        run_root = normalizations_root / contract_name
        if not os.path.isdir(native_io_path(run_root)):
            continue
        run_root = ensure_contained_codex_image_path(
            root,
            run_root,
            must_exist=True,
        )
        receipt_path = run_root / "receipt.json"
        plan_path = run_root / "plan.json"
        output_path = run_root / "normalized.png"
        if os.path.isfile(native_io_path(output_path)):
            output_path = ensure_contained_codex_image_path(
                root,
                output_path,
                must_exist=True,
            )
        output_matches = (
            os.path.isfile(native_io_path(output_path))
            and os.path.getsize(native_io_path(output_path)) == generated_image.byte_size
            and sha256_file(output_path) == generated_image.sha256
        )
        if not os.path.isfile(native_io_path(receipt_path)):
            if output_matches:
                if not os.path.isfile(native_io_path(plan_path)):
                    raise ValueError("matching native normalization output has no plan")
                with open(native_io_path(plan_path), "rb") as handle:
                    orphan_plan = ImageGenNativeNormalizationPlan.model_validate_json(
                        handle.read()
                    )
                if "/native_outputs/" in f"/{orphan_plan.source_image.path}":
                    raise ValueError("matching native normalization output has no receipt")
            continue
        receipt_path = ensure_contained_codex_image_path(
            root,
            receipt_path,
            must_exist=True,
        )
        with open(native_io_path(receipt_path), "rb") as handle:
            parsed = ImageGenNativeNormalizationReceipt.model_validate_json(handle.read())
        artifact = artifact_for_codex_image(
            root,
            receipt_path,
            artifact_id=parsed.contract_id,
            kind="imagegen-native-normalization-receipt",
            media_type="application/json",
        )
        receipt = load_codex_image_model(
            root,
            artifact,
            ImageGenNativeNormalizationReceipt,
        )
        receipt_claims_match = (
            receipt.normalized_image is not None
            and receipt.normalized_image.sha256 == generated_image.sha256
            and receipt.normalized_image.byte_size == generated_image.byte_size
        )
        if receipt.native_output_adoption_receipt is None or not (
            output_matches or receipt_claims_match
        ):
            continue
        adoption = load_codex_image_model(
            root,
            receipt.native_output_adoption_receipt,
            CodexImageNativeOutputAdoptionReceipt,
        )
        validate_codex_image_native_output_adoption(
            root,
            adoption,
            require_current_protected_inventory=False,
        )
        if (
            adoption.assignment == assignment_artifact
            and adoption.assignment_id == assignment.assignment_id
            and adoption.ordinal == ordinal
            and adoption.output_role == output_role
        ):
            plan = load_codex_image_model(
                root,
                receipt.plan,
                ImageGenNativeNormalizationPlan,
            )
            validate_native_normalization_receipt(
                root,
                plan,
                receipt,
                require_current_protected_inventory=False,
            )
            if (
                receipt.normalized_image is None
                or receipt.normalized_image.sha256 != generated_image.sha256
                or receipt.normalized_image.byte_size != generated_image.byte_size
                or receipt.normalized_image.media_type != generated_image.media_type
            ):
                raise ValueError("matching native normalization receipt changed")
            matches.append(artifact)
    if len(matches) > 1:
        raise ValueError("selected core bytes have ambiguous native normalization origins")
    return matches


def _validate_common_identity(
    first: object,
    *others: object,
) -> None:
    """Require every envelope in one closure to retain the same workflow identity."""

    fields = (
        "job_id",
        "workflow_id",
        "dispatch_id",
        "session_id",
        "profile_id",
        "provider_id",
    )
    expected = tuple(getattr(first, field) for field in fields)
    if any(tuple(getattr(item, field) for field in fields) != expected for item in others):
        raise ValueError("native core preparation envelope identity changed")


__all__ = [
    "NativeCorePreparationResult",
    "build_codex_image_native_core_preparation_receipt",
    "publish_codex_image_native_core_preparation_receipt",
    "validate_codex_image_native_core_preparation_receipt",
    "validate_native_core_preparation_binding",
]
