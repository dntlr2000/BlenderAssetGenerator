"""Host-only public lifecycle facade for the controller-mediated ImageGen overlay."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..blender_artifacts import native_io_path, native_json_bytes
from ..production.controller_executor import (
    CandidateAuthoringController,
    validate_controller_execution_result,
)
from .adoption import build_image_to_material_adoption
from .artifacts import (
    artifact_for_codex_image,
    load_codex_image_model,
    validate_codex_image_artifact,
    write_immutable_codex_image_model,
)
from .assignment import validate_codex_imagegen_assignment_boundary
from .completion import (
    build_codex_imagegen_candidate,
    build_generated_image_evidence,
    validate_codex_imagegen_completion,
)
from .material_loop_models import (
    CodexImageNativeOutputAdoptionReceipt,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
    codex_image_native_output_adoption_receipt_path,
    imagegen_native_normalization_receipt_path,
)
from .material_loop_normalization import (
    execute_native_image_normalization,
    validate_native_normalization_plan,
    validate_native_normalization_receipt,
)
from .models import (
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationBudgetUsage,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationPlan,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    DerivedChannelEvidence,
    DirectOutputRole,
    ImageToMaterialAdoption,
)
from .native_output_adoption import (
    adopt_codex_imagegen_native_output_bytes,
    validate_codex_image_native_output_adoption,
)
from .profile import codex_imagegen_profile_status
from .reporting import build_codex_imagegen_terminal
from .selection import (
    CandidateBinding,
    QualityBinding,
)
from .selection import (
    select_codex_imagegen_candidate as _build_selection,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class CompletionAdoptionResult:
    """Return host-created candidate and generated-image evidence after validation."""

    candidates: tuple[CandidateBinding, ...]
    generated_evidence: tuple[
        tuple[CodexGeneratedImageEvidence, CodexImageArtifact], ...
    ]


@dataclass(frozen=True)
class NativeOutputAdoptionResult:
    """Return an immutable native original and its exact host adoption receipt."""

    receipt: CodexImageNativeOutputAdoptionReceipt
    receipt_artifact: CodexImageArtifact
    original_image: CodexImageArtifact


@dataclass(frozen=True)
class NativeOutputPreparationResult:
    """Return a deterministic core-ready PNG and its exact normalization receipt."""

    receipt: ImageGenNativeNormalizationReceipt
    receipt_artifact: CodexImageArtifact
    normalized_image: CodexImageArtifact
    ordinal: int
    output_role: DirectOutputRole


def codex_imagegen_status() -> dict[str, object]:
    """Report the static capability boundary without network or credential probes."""

    return codex_imagegen_profile_status()


def plan_codex_imagegen(
    *,
    job_root: Path,
    plan: CodexImageGenerationPlan,
) -> CodexImageArtifact:
    """Publish one prebuilt opt-in plan at its canonical additive overlay path."""

    for artifact in plan.provenance:
        validate_codex_image_artifact(job_root, artifact)
    path = job_root / _session_root(plan.session_id) / "plan.json"
    return write_immutable_codex_image_model(
        job_root,
        path,
        plan,
        kind="codex-image-generation-plan",
    )


def run_codex_imagegen(
    *,
    job_root: Path,
    assignment: CodexImageGenerationAssignment,
) -> CodexImageArtifact:
    """Publish or safely rebind one assignment without running an image generator."""

    validate_codex_imagegen_assignment_boundary(job_root, assignment)
    path = (
        job_root
        / _session_root(assignment.session_id)
        / "assignments"
        / assignment.assignment_id
        / "assignment.json"
    )
    if os.path.exists(native_io_path(path)):
        stored, artifact = _load_canonical_published_model(
            job_root,
            path,
            CodexImageGenerationAssignment,
            artifact_id=assignment.contract_id,
            kind="codex-image-generation-assignment",
        )
        validate_codex_imagegen_assignment_boundary(job_root, stored)
        requested_inputs = assignment.model_dump(
            mode="json",
            exclude={"created_at", "assignment_payload_sha256"},
        )
        stored_inputs = stored.model_dump(
            mode="json",
            exclude={"created_at", "assignment_payload_sha256"},
        )
        if stored_inputs != requested_inputs:
            raise ValueError("existing ImageGen assignment inputs differ")
        return artifact
    return write_immutable_codex_image_model(
        job_root,
        path,
        assignment,
        kind="codex-image-generation-assignment",
    )


def adopt_codex_imagegen_native_output(
    *,
    job_root: Path,
    assignment_artifact: CodexImageArtifact,
    allowed_source_root: Path,
    native_source_path: Path,
    native_output_id: str,
    ordinal: int,
    output_role: DirectOutputRole,
    receipt_contract_id: str,
    created_at: datetime,
) -> NativeOutputAdoptionResult:
    """Preserve mismatched native PNG bytes before any core-size validation."""

    assignment = load_codex_image_model(
        job_root,
        assignment_artifact,
        CodexImageGenerationAssignment,
    )
    receipt_path = job_root / codex_image_native_output_adoption_receipt_path(
        assignment.session_id,
        assignment.assignment_id,
        native_output_id,
    )
    if os.path.exists(native_io_path(receipt_path)):
        receipt, receipt_artifact = _load_canonical_published_model(
            job_root,
            receipt_path,
            CodexImageNativeOutputAdoptionReceipt,
            artifact_id=receipt_contract_id,
            kind="codex-image-native-output-adoption-receipt",
        )
        if (
            receipt.contract_id != receipt_contract_id
            or receipt.assignment != assignment_artifact
            or receipt.native_output_id != native_output_id
            or receipt.ordinal != ordinal
            or receipt.output_role != output_role
        ):
            raise ValueError("existing native output adoption receipt differs")
        validate_codex_image_native_output_adoption(job_root, receipt)
        if os.path.exists(native_io_path(native_source_path)):
            replayed = adopt_codex_imagegen_native_output_bytes(
                job_root,
                assignment_artifact=assignment_artifact,
                allowed_source_root=allowed_source_root,
                native_source_path=native_source_path,
                native_output_id=native_output_id,
                ordinal=ordinal,
                output_role=output_role,
                receipt_contract_id=receipt_contract_id,
                created_at=receipt.created_at,
            )
            if replayed != receipt:
                raise ValueError("existing native output adoption source differs")
        return NativeOutputAdoptionResult(
            receipt=receipt,
            receipt_artifact=receipt_artifact,
            original_image=receipt.original_image,
        )
    receipt = adopt_codex_imagegen_native_output_bytes(
        job_root,
        assignment_artifact=assignment_artifact,
        allowed_source_root=allowed_source_root,
        native_source_path=native_source_path,
        native_output_id=native_output_id,
        ordinal=ordinal,
        output_role=output_role,
        receipt_contract_id=receipt_contract_id,
        created_at=created_at,
    )
    receipt_artifact = _write_or_adopt_exact_model(
        job_root,
        receipt_path,
        receipt,
        kind="codex-image-native-output-adoption-receipt",
    )
    validate_codex_image_native_output_adoption(job_root, receipt)
    return NativeOutputAdoptionResult(
        receipt=receipt,
        receipt_artifact=receipt_artifact,
        original_image=receipt.original_image,
    )


def prepare_codex_imagegen_native_output_for_core_completion(
    *,
    job_root: Path,
    assignment_artifact: CodexImageArtifact,
    adoption_receipt_artifact: CodexImageArtifact,
    plan: ImageGenNativeNormalizationPlan,
    plan_artifact: CodexImageArtifact,
    receipt_contract_id: str,
    created_at: datetime,
) -> NativeOutputPreparationResult:
    """Normalize an adopted original into a core 0.1 assignment-sized PNG."""

    adoption = load_codex_image_model(
        job_root,
        adoption_receipt_artifact,
        CodexImageNativeOutputAdoptionReceipt,
    )
    _validate_native_adoption_receipt_artifact(adoption, adoption_receipt_artifact)
    validate_codex_image_native_output_adoption(job_root, adoption)
    if adoption.assignment != assignment_artifact:
        raise ValueError("native adoption receipt targets another assignment")
    if plan.source_image != adoption.original_image:
        raise ValueError("normalization plan source differs from the adopted original")
    if plan.target_size != adoption.expected_assignment_size:
        raise ValueError("normalization target differs from the core assignment size")
    if (
        plan.job_id,
        plan.workflow_id,
        plan.dispatch_id,
        plan.session_id,
    ) != (
        adoption.job_id,
        adoption.workflow_id,
        adoption.dispatch_id,
        adoption.session_id,
    ):
        raise ValueError("normalization plan identity differs from native adoption")
    validate_native_normalization_plan(job_root, plan)
    if plan.operation == "review_required":
        raise ValueError("review-required normalization is not core-completion-ready")
    receipt_path = job_root / imagegen_native_normalization_receipt_path(
        plan.session_id,
        plan.contract_id,
    )
    if os.path.exists(native_io_path(receipt_path)):
        receipt, receipt_artifact = _load_canonical_published_model(
            job_root,
            receipt_path,
            ImageGenNativeNormalizationReceipt,
            artifact_id=receipt_contract_id,
            kind="imagegen-native-normalization-receipt",
        )
        if receipt.contract_id != receipt_contract_id:
            raise ValueError("existing native normalization receipt differs")
    else:
        receipt = execute_native_image_normalization(
            job_root,
            plan,
            plan_artifact,
            receipt_contract_id=receipt_contract_id,
            native_output_adoption_receipt=adoption_receipt_artifact,
            created_at=created_at,
        )
        receipt_artifact = _write_or_adopt_exact_model(
            job_root,
            receipt_path,
            receipt,
            kind="imagegen-native-normalization-receipt",
        )
    normalized_image = validate_prepared_native_output_for_core_completion(
        job_root=job_root,
        assignment_artifact=assignment_artifact,
        adoption_receipt_artifact=adoption_receipt_artifact,
        plan=plan,
        plan_artifact=plan_artifact,
        receipt_artifact=receipt_artifact,
    )
    return NativeOutputPreparationResult(
        receipt=receipt,
        receipt_artifact=receipt_artifact,
        normalized_image=normalized_image,
        ordinal=adoption.ordinal,
        output_role=adoption.output_role,
    )


def validate_prepared_native_output_for_core_completion(
    *,
    job_root: Path,
    assignment_artifact: CodexImageArtifact,
    adoption_receipt_artifact: CodexImageArtifact,
    plan: ImageGenNativeNormalizationPlan,
    plan_artifact: CodexImageArtifact,
    receipt_artifact: CodexImageArtifact,
) -> CodexImageArtifact:
    """Replay the full original-to-normalized chain and return its core-ready PNG."""

    adoption = load_codex_image_model(
        job_root,
        adoption_receipt_artifact,
        CodexImageNativeOutputAdoptionReceipt,
    )
    _validate_native_adoption_receipt_artifact(adoption, adoption_receipt_artifact)
    validate_codex_image_native_output_adoption(job_root, adoption)
    if adoption.assignment != assignment_artifact:
        raise ValueError("prepared native output targets another assignment")
    receipt = load_codex_image_model(
        job_root,
        receipt_artifact,
        ImageGenNativeNormalizationReceipt,
    )
    expected_receipt_path = imagegen_native_normalization_receipt_path(
        plan.session_id,
        plan.contract_id,
    )
    if receipt_artifact.path != expected_receipt_path:
        raise ValueError("normalization receipt is outside its exact run-owned leaf")
    if (
        receipt_artifact.artifact_id != receipt.contract_id
        or receipt_artifact.kind != "imagegen-native-normalization-receipt"
    ):
        raise ValueError("normalization receipt artifact identity is inconsistent")
    if plan.source_image != adoption.original_image:
        raise ValueError("prepared normalization source differs from adopted original")
    if plan.target_size != adoption.expected_assignment_size:
        raise ValueError("prepared normalization target differs from assignment size")
    if receipt.plan != plan_artifact:
        raise ValueError("normalization receipt binds another caller-authored plan")
    if receipt.native_output_adoption_receipt != adoption_receipt_artifact:
        raise ValueError("normalization receipt omits its exact native adoption receipt")
    validate_native_normalization_receipt(job_root, plan, receipt)
    if receipt.normalized_image is None or receipt.status == "review_required":
        raise ValueError("normalization receipt has no core-ready PNG")
    return receipt.normalized_image


def adopt_codex_imagegen_completion(
    *,
    job_root: Path,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    controller_request_artifact: CodexImageArtifact,
    controller_result_artifact: CodexImageArtifact,
    controller: CandidateAuthoringController,
    created_at: datetime,
) -> CompletionAdoptionResult:
    """Replay raw evidence once or resume an exact host-publication prefix after a crash."""

    request_path = validate_codex_image_artifact(
        job_root,
        controller_request_artifact,
    )
    result_path = validate_codex_image_artifact(
        job_root,
        controller_result_artifact,
    )
    assignment, completion, _paths = validate_codex_imagegen_completion(
        job_root=job_root,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        controller_result_artifact=controller_result_artifact,
    )
    evidence_root = (
        job_root
        / _session_root(assignment.session_id)
        / "assignments"
        / assignment.assignment_id
        / "evidence"
    )
    publication_paths = [
        path
        for generated_file in completion.generated_files
        for path in (
            evidence_root / f"candidate-{generated_file.ordinal:02d}.json",
            evidence_root
            / f"generated-image-evidence-{generated_file.ordinal:02d}.json",
        )
    ]
    if not _has_exact_publication_prefix(publication_paths):
        validate_controller_execution_result(
            job_root=job_root,
            request_path=request_path,
            result_path=result_path,
            controller=controller,
        )
    candidate_bindings: list[CandidateBinding] = []
    evidence_bindings: list[
        tuple[CodexGeneratedImageEvidence, CodexImageArtifact]
    ] = []
    for generated_file in completion.generated_files:
        ordinal = generated_file.ordinal
        candidate = build_codex_imagegen_candidate(
            contract_id=f"candidate-{assignment.assignment_id}-{ordinal:02d}",
            assignment=assignment,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
            controller_request_artifact=controller_request_artifact,
            controller_result_artifact=controller_result_artifact,
            generated_file=generated_file,
            created_at=created_at,
        )
        candidate_artifact = _write_or_adopt_exact_model(
            job_root,
            evidence_root / f"candidate-{ordinal:02d}.json",
            candidate,
            kind="codex-image-generation-candidate",
        )
        evidence = build_generated_image_evidence(
            contract_id=f"generated-evidence-{assignment.assignment_id}-{ordinal:02d}",
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            created_at=created_at,
        )
        evidence_artifact = _write_or_adopt_exact_model(
            job_root,
            evidence_root / f"generated-image-evidence-{ordinal:02d}.json",
            evidence,
            kind="codex-generated-image-evidence",
        )
        candidate_bindings.append((candidate, candidate_artifact))
        evidence_bindings.append((evidence, evidence_artifact))
    return CompletionAdoptionResult(
        candidates=tuple(candidate_bindings),
        generated_evidence=tuple(evidence_bindings),
    )


def select_codex_imagegen_candidate(
    *,
    job_root: Path,
    selection_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidates: list[CandidateBinding],
    quality_reports: list[QualityBinding],
    created_at: datetime,
) -> tuple[CodexImageGenerationSelection, CodexImageArtifact]:
    """Build and immutably publish deterministic candidate selection evidence."""

    stored_assignment = _require_exact_model(
        job_root,
        assignment,
        assignment_artifact,
        CodexImageGenerationAssignment,
    )
    load_codex_image_model(
        job_root,
        completion_artifact,
        CodexImageGenerationCompletion,
    )
    stored_candidates = [
        (
            _require_exact_model(
                job_root,
                candidate,
                artifact,
                CodexImageGenerationCandidate,
            ),
            artifact,
        )
        for candidate, artifact in candidates
    ]
    validate_codex_imagegen_assignment_boundary(job_root, stored_assignment)
    for candidate, _artifact in stored_candidates:
        validate_codex_image_artifact(job_root, candidate.generated_file.artifact)
    stored_reports = [
        (
            _require_exact_model(
                job_root,
                report,
                artifact,
                CodexImageGenerationQualityReport,
            ),
            artifact,
        )
        for report, artifact in quality_reports
    ]
    selection = _build_selection(
        selection_id=selection_id,
        assignment=stored_assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidates=stored_candidates,
        quality_reports=stored_reports,
        created_at=created_at,
    )
    path = (
        job_root
        / _session_root(assignment.session_id)
        / "assignments"
        / assignment.assignment_id
        / "selection.json"
    )
    artifact = write_immutable_codex_image_model(
        job_root,
        path,
        selection,
        kind="codex-image-generation-selection",
    )
    return selection, artifact


def adopt_codex_imagegen_material(
    *,
    job_root: Path,
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
) -> tuple[ImageToMaterialAdoption, CodexImageArtifact]:
    """Publish a local-authoring adoption contract without changing canonical materials."""

    stored_selection = _require_exact_model(
        job_root,
        selection,
        selection_artifact,
        CodexImageGenerationSelection,
    )
    stored_candidate = _require_exact_model(
        job_root,
        candidate,
        candidate_artifact,
        CodexImageGenerationCandidate,
    )
    stored_evidence = _require_exact_model(
        job_root,
        generated_image_evidence,
        generated_image_evidence_artifact,
        CodexGeneratedImageEvidence,
    )
    stored_report = _require_exact_model(
        job_root,
        quality_report,
        quality_report_artifact,
        CodexImageGenerationQualityReport,
    )
    assignment = load_codex_image_model(
        job_root,
        stored_selection.assignment,
        CodexImageGenerationAssignment,
    )
    validate_codex_imagegen_assignment_boundary(job_root, assignment)
    validate_codex_imagegen_exact_text_binding(
        job_root=job_root,
        assignment=assignment,
        exact_text_composition=exact_text_composition,
    )
    validate_codex_image_artifact(job_root, stored_candidate.generated_file.artifact)
    for derived in derived_channels:
        validate_codex_image_artifact(job_root, derived.output)
    if exact_text_composition is not None:
        validate_codex_image_artifact(job_root, exact_text_composition)
    adoption = build_image_to_material_adoption(
        contract_id=contract_id,
        adoption_id=adoption_id,
        selection=stored_selection,
        selection_artifact=selection_artifact,
        candidate=stored_candidate,
        candidate_artifact=candidate_artifact,
        generated_image_evidence=stored_evidence,
        generated_image_evidence_artifact=generated_image_evidence_artifact,
        quality_report=stored_report,
        quality_report_artifact=quality_report_artifact,
        material_strategy=material_strategy,
        direct_channels=direct_channels,
        derived_channels=derived_channels,
        created_at=created_at,
        exact_text_composition=exact_text_composition,
    )
    path = (
        job_root
        / _session_root(stored_selection.session_id)
        / "assignments"
        / assignment.assignment_id
        / "adoption.json"
    )
    artifact = write_immutable_codex_image_model(
        job_root,
        path,
        adoption,
        kind="codex-image-material-adoption",
    )
    return adoption, artifact


def validate_codex_imagegen_exact_text_binding(
    *,
    job_root: Path,
    assignment: CodexImageGenerationAssignment,
    exact_text_composition: CodexImageArtifact | None,
) -> None:
    """Bind local exact-text evidence to the assignment hash without exposing its text."""

    expected_sha256 = assignment.exact_text_sha256
    if expected_sha256 is None:
        if exact_text_composition is not None:
            raise ValueError("assignment does not authorize exact signage text")
        return
    if exact_text_composition is None:
        raise ValueError("assignment exact signage text evidence is required")
    if (
        exact_text_composition.kind != "exact-signage-text-evidence"
        or exact_text_composition.media_type != "application/json"
    ):
        raise ValueError("exact signage text must use its strict JSON evidence kind")
    from ..material_authoring.codex_image_models import (  # noqa: PLC0415
        ExactSignageTextEvidenceV021,
    )

    evidence = load_codex_image_model(
        job_root,
        exact_text_composition,
        ExactSignageTextEvidenceV021,
    )
    if evidence.text_sha256 != expected_sha256:
        raise ValueError("exact signage text differs from the assignment binding")


def cancel_codex_imagegen(
    *,
    job_root: Path,
    contract_id: str,
    terminal_id: str,
    plan_artifact: CodexImageArtifact,
    budget: CodexImageGenerationBudget,
    budget_artifact: CodexImageArtifact,
    budget_usage: CodexImageGenerationBudgetUsage,
    reason: str,
    created_at: datetime,
    assignment_artifact: CodexImageArtifact | None = None,
    completion_artifact: CodexImageArtifact | None = None,
    selection_artifact: CodexImageArtifact | None = None,
    candidates: list[CodexImageArtifact] | None = None,
    quality_reports: list[CodexImageArtifact] | None = None,
) -> CodexImageArtifact:
    """Publish cancellation while preserving every supplied current overlay artifact."""

    stored_budget = _require_exact_model(
        job_root,
        budget,
        budget_artifact,
        CodexImageGenerationBudget,
    )
    stored_plan = load_codex_image_model(
        job_root,
        plan_artifact,
        CodexImageGenerationPlan,
    )
    if stored_plan.budget != budget_artifact:
        raise ValueError("cancellation budget differs from the exact ImageGen plan")
    for artifact in [
        assignment_artifact,
        completion_artifact,
        selection_artifact,
        *(candidates or []),
        *(quality_reports or []),
    ]:
        if artifact is not None:
            validate_codex_image_artifact(job_root, artifact)
    terminal = build_codex_imagegen_terminal(
        contract_id=contract_id,
        terminal_id=terminal_id,
        plan_artifact=plan_artifact,
        budget=stored_budget,
        budget_artifact=budget_artifact,
        budget_usage=budget_usage,
        status="cancelled",
        reason=reason,
        created_at=created_at,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        selection_artifact=selection_artifact,
        candidates=candidates,
        quality_reports=quality_reports,
    )
    return write_immutable_codex_image_model(
        job_root,
        job_root / _session_root(stored_budget.session_id) / "terminal.json",
        terminal,
        kind="codex-image-generation-terminal",
    )


def _session_root(session_id: str) -> Path:
    """Return the additive, non-canonical ImageGen session directory."""

    return Path("production") / "autonomy_v2" / session_id / "codex_imagegen"


def _validate_native_adoption_receipt_artifact(
    receipt: CodexImageNativeOutputAdoptionReceipt,
    artifact: CodexImageArtifact,
) -> None:
    """Require one native adoption receipt at its exact assignment-owned JSON leaf."""

    expected_path = codex_image_native_output_adoption_receipt_path(
        receipt.session_id,
        receipt.assignment_id,
        receipt.native_output_id,
    )
    if (
        artifact.path != expected_path
        or artifact.artifact_id != receipt.contract_id
        or artifact.kind != "codex-image-native-output-adoption-receipt"
    ):
        raise ValueError("native output adoption receipt artifact identity is inconsistent")


def _require_exact_model(
    job_root: Path,
    claimed: ModelT,
    artifact: CodexImageArtifact,
    model_type: type[ModelT],
) -> ModelT:
    """Rehash and reparse a claimed model, rejecting any in-memory/artifact mismatch."""

    stored = load_codex_image_model(job_root, artifact, model_type)
    if stored != claimed:
        raise ValueError("claimed ImageGen model differs from its exact artifact")
    return stored


def _write_or_adopt_exact_model(
    job_root: Path,
    path: Path,
    model: ModelT,
    *,
    kind: str,
) -> CodexImageArtifact:
    """Publish one host model or rebind only its exact canonical existing bytes."""

    if os.path.exists(native_io_path(path)):
        stored, artifact = _load_canonical_published_model(
            job_root,
            path,
            type(model),
            artifact_id=str(model.contract_id),
            kind=kind,
        )
        if stored != model:
            raise ValueError("existing ImageGen completion adoption evidence differs")
        return artifact
    return write_immutable_codex_image_model(job_root, path, model, kind=kind)


def _load_canonical_published_model(
    job_root: Path,
    path: Path,
    model_type: type[ModelT],
    *,
    artifact_id: str,
    kind: str,
) -> tuple[ModelT, CodexImageArtifact]:
    """Rebind strict JSON and reject non-canonical bytes before crash recovery."""

    artifact = artifact_for_codex_image(
        job_root,
        path,
        artifact_id=artifact_id,
        kind=kind,
        media_type="application/json",
    )
    stored = load_codex_image_model(job_root, artifact, model_type)
    canonical = native_json_bytes(stored.model_dump(mode="json"))
    with open(native_io_path(path), "rb") as handle:
        if handle.read() != canonical:
            raise ValueError("existing ImageGen evidence bytes are not canonical")
    return stored, artifact


def _has_exact_publication_prefix(paths: list[Path]) -> bool:
    """Accept no evidence or one contiguous crash-published prefix, rejecting holes."""

    present = [os.path.exists(native_io_path(path)) for path in paths]
    if not any(present):
        return False
    first_missing = next(
        (index for index, exists in enumerate(present) if not exists),
        len(present),
    )
    if any(present[first_missing:]):
        raise ValueError("existing ImageGen completion adoption evidence has a publication gap")
    return True
