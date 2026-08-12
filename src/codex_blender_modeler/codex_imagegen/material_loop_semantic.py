"""Non-human semantic-review recording and deterministic candidate precedence helpers."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from ..blender_artifacts import stable_json_digest
from ..stabilization.models import PortableId
from .artifacts import validate_codex_image_artifact
from .material_loop_models import (
    CodexImageSemanticCheck,
    CodexImageSemanticReview,
    semantic_review_outcome,
)
from .models import CodexImageArtifact

DeterministicQualityOutcome = Literal["passed", "review_required", "failed", "unavailable"]


def build_codex_image_semantic_review(
    job_root: Path,
    *,
    contract_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    candidate_id: str,
    reviewed_image: CodexImageArtifact,
    assignment: CodexImageArtifact,
    deterministic_quality_report: CodexImageArtifact,
    material_family: Literal[
        "wood",
        "signage_decal",
        "emissive",
        "crystal",
        "user_image_pbr",
        "planar_reference_patch",
    ],
    checks: list[CodexImageSemanticCheck],
    producer: str = "current_codex_task_semantic_review",
    created_at: datetime | None = None,
) -> CodexImageSemanticReview:
    """Bind current-task observations to exact image and deterministic quality evidence."""

    TypeAdapter(PortableId).validate_python(candidate_id, strict=True)
    for artifact in (reviewed_image, assignment, deterministic_quality_report):
        validate_codex_image_artifact(job_root, artifact)
    input_sha256 = _semantic_review_input_sha256(
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        candidate_id=candidate_id,
        reviewed_image=reviewed_image,
        assignment=assignment,
        deterministic_quality_report=deterministic_quality_report,
        material_family=material_family,
        checks=checks,
    )
    return CodexImageSemanticReview(
        contract_id=contract_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=input_sha256,
        source_fingerprint=reviewed_image.sha256,
        producer=producer,
        provenance=[reviewed_image, assignment, deterministic_quality_report],
        created_at=created_at or datetime.now(UTC),
        candidate_id=candidate_id,
        reviewed_image=reviewed_image,
        assignment=assignment,
        deterministic_quality_report=deterministic_quality_report,
        material_family=material_family,
        checks=checks,
        outcome=semantic_review_outcome(checks),
    )


def validate_codex_image_semantic_review(
    job_root: Path,
    review: CodexImageSemanticReview,
    *,
    expected_job_id: str | None = None,
    expected_workflow_id: str | None = None,
    expected_dispatch_id: str | None = None,
    expected_candidate_id: str | None = None,
    expected_session_id: str | None = None,
    expected_reviewed_image_sha256: str | None = None,
) -> None:
    """Reject stale review bytes, identity mismatch, or a changed semantic input digest."""

    for artifact in (
        review.reviewed_image,
        review.assignment,
        review.deterministic_quality_report,
    ):
        validate_codex_image_artifact(job_root, artifact)
    expected_identity = (
        expected_job_id,
        expected_workflow_id,
        expected_dispatch_id,
        expected_session_id,
    )
    observed_identity = (
        review.job_id,
        review.workflow_id,
        review.dispatch_id,
        review.session_id,
    )
    for expected, observed, label in zip(
        expected_identity,
        observed_identity,
        ("job", "workflow", "dispatch", "session"),
        strict=True,
    ):
        if expected is not None and observed != expected:
            raise ValueError(f"semantic review {label} identity changed")
    if expected_candidate_id is not None and review.candidate_id != expected_candidate_id:
        raise ValueError("semantic review candidate identity changed")
    if (
        expected_reviewed_image_sha256 is not None
        and review.reviewed_image.sha256 != expected_reviewed_image_sha256
    ):
        raise ValueError("semantic review image identity changed")
    expected_input = _semantic_review_input_sha256(
        job_id=review.job_id,
        workflow_id=review.workflow_id,
        dispatch_id=review.dispatch_id,
        session_id=review.session_id,
        candidate_id=review.candidate_id,
        reviewed_image=review.reviewed_image,
        assignment=review.assignment,
        deterministic_quality_report=review.deterministic_quality_report,
        material_family=review.material_family,
        checks=review.checks,
    )
    if review.input_sha256 != expected_input:
        raise ValueError("semantic review input hash is inconsistent")


def semantic_review_gate(
    review: CodexImageSemanticReview | None,
) -> Literal["passed", "review_required", "failed"]:
    """Map unavailable or absent semantic evidence to review rather than an invented pass."""

    if review is None or review.outcome in {"unavailable", "review_required"}:
        return "review_required"
    return review.outcome


def candidate_selection_precedence_key(
    *,
    file_hard_gate_passed: bool,
    deterministic_quality_outcome: DeterministicQualityOutcome,
    semantic_review: CodexImageSemanticReview | None,
    material_role_suitable: bool | None,
    repair_cost: float,
    candidate_id: str,
) -> tuple[int, int, int, int, float, str]:
    """Rank file, deterministic, semantic, role, repair, then stable-ID evidence in order."""

    if type(file_hard_gate_passed) is not bool:
        raise TypeError("file_hard_gate_passed must be a strict boolean")
    if material_role_suitable is not None and type(material_role_suitable) is not bool:
        raise TypeError("material_role_suitable must be a strict boolean or None")
    if not math.isfinite(repair_cost) or repair_cost < 0.0:
        raise ValueError("repair cost must be finite and non-negative")
    TypeAdapter(PortableId).validate_python(candidate_id, strict=True)
    quality_rank = {
        "passed": 0,
        "review_required": 1,
        "unavailable": 1,
        "failed": 2,
    }[deterministic_quality_outcome]
    semantic_rank = {
        "passed": 0,
        "review_required": 1,
        "failed": 2,
    }[semantic_review_gate(semantic_review)]
    role_rank = 0 if material_role_suitable is True else 1
    return (
        0 if file_hard_gate_passed else 1,
        quality_rank,
        semantic_rank,
        role_rank,
        repair_cost,
        candidate_id,
    )


def _semantic_review_input_sha256(
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    candidate_id: str,
    reviewed_image: CodexImageArtifact,
    assignment: CodexImageArtifact,
    deterministic_quality_report: CodexImageArtifact,
    material_family: str,
    checks: list[CodexImageSemanticCheck],
) -> str:
    """Hash the complete exact semantic-review input closure."""

    return stable_json_digest(
        {
            "job_id": job_id,
            "workflow_id": workflow_id,
            "dispatch_id": dispatch_id,
            "session_id": session_id,
            "candidate_id": candidate_id,
            "reviewed_image": reviewed_image.model_dump(mode="json"),
            "assignment": assignment.model_dump(mode="json"),
            "deterministic_quality_report": deterministic_quality_report.model_dump(
                mode="json"
            ),
            "material_family": material_family,
            "checks": [item.model_dump(mode="json") for item in checks],
        }
    )


__all__ = [
    "build_codex_image_semantic_review",
    "candidate_selection_precedence_key",
    "semantic_review_gate",
    "validate_codex_image_semantic_review",
]
