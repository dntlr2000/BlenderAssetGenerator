"""Host-only public lifecycle facade for the controller-mediated ImageGen overlay."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..blender_artifacts import native_io_path
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
    ImageToMaterialAdoption,
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
    canonical_text = (
        json.dumps(stored.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    )
    canonical = canonical_text.replace("\n", os.linesep).encode("utf-8")
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
