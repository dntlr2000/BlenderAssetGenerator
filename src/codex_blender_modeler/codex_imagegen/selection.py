"""Deterministic candidate selection with immutable rejection evidence."""

from __future__ import annotations

from datetime import datetime

from ..blender_artifacts import stable_json_digest
from .models import (
    CodexImageArtifact,
    CodexImageCandidateDecision,
    CodexImageGenerationAssignment,
    CodexImageGenerationCandidate,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
)

CandidateBinding = tuple[CodexImageGenerationCandidate, CodexImageArtifact]
QualityBinding = tuple[CodexImageGenerationQualityReport, CodexImageArtifact]


def select_codex_imagegen_candidate(
    *,
    selection_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidates: list[CandidateBinding],
    quality_reports: list[QualityBinding],
    created_at: datetime,
) -> CodexImageGenerationSelection:
    """Select the highest deterministic score and preserve every candidate decision."""

    if not candidates or len(candidates) != assignment.requested_candidate_count:
        raise ValueError("selection must preserve every assignment candidate")
    candidate_by_id = _candidate_map(
        candidates,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
    )
    report_by_id = _report_map(
        candidates,
        quality_reports,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
    )
    eligible_ids = [
        candidate_id
        for candidate_id, report in report_by_id.items()
        if report[0].selection_eligible
    ]
    selected_id = (
        sorted(
            eligible_ids,
            key=lambda candidate_id: (
                -report_by_id[candidate_id][0].deterministic_score,
                candidate_id,
            ),
        )[0]
        if eligible_ids
        else None
    )
    decisions: list[CodexImageCandidateDecision] = []
    for candidate_id in sorted(candidate_by_id):
        candidate_artifact = candidate_by_id[candidate_id][1]
        report, report_artifact = report_by_id[candidate_id]
        if candidate_id == selected_id:
            decision_outcome = "selected"
            reasons = ["highest-deterministic-score"]
        elif report.selection_eligible:
            decision_outcome = "rejected"
            reasons = ["lower-deterministic-rank"]
        else:
            decision_outcome = "ineligible"
            reasons = [f"quality-{report.outcome}"]
        decisions.append(
            CodexImageCandidateDecision(
                candidate_id=candidate_id,
                candidate=candidate_artifact,
                quality_report=report_artifact,
                outcome=decision_outcome,
                reason_codes=reasons,
            )
        )
    if selected_id is not None:
        outcome = "selected"
        selected_candidate = candidate_by_id[selected_id][1]
        selected_quality_report = report_by_id[selected_id][1]
    else:
        needs_review = any(
            report.outcome in {"review_required", "unscorable"}
            for report, _artifact in quality_reports
        )
        outcome = "review_required" if needs_review else "no_eligible_candidate"
        selected_candidate = None
        selected_quality_report = None
    inputs = {
        "assignment": assignment_artifact.model_dump(mode="json"),
        "completion": completion_artifact.model_dump(mode="json"),
        "decisions": [item.model_dump(mode="json") for item in decisions],
    }
    provenance = _unique_artifacts(
        [
            assignment_artifact,
            completion_artifact,
            *[artifact for _candidate, artifact in candidates],
            *[artifact for _report, artifact in quality_reports],
        ]
    )
    return CodexImageGenerationSelection(
        contract_id=selection_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "selected_candidate_id": selected_id}
        ),
        producer="codex_blender_modeler.codex_imagegen.selection",
        provenance=provenance,
        created_at=created_at,
        selection_id=selection_id,
        assignment=assignment_artifact,
        completion=completion_artifact,
        candidate_count=len(candidates),
        selected_candidate=selected_candidate,
        selected_quality_report=selected_quality_report,
        decisions=decisions,
        outcome=outcome,
    )


def _candidate_map(
    candidates: list[CandidateBinding],
    *,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
) -> dict[str, CandidateBinding]:
    """Index unique candidates after validating their assignment binding."""

    result: dict[str, CandidateBinding] = {}
    for binding in candidates:
        candidate, _artifact = binding
        if candidate.assignment != assignment_artifact:
            raise ValueError("selection candidate binds a different assignment")
        if candidate.completion != completion_artifact:
            raise ValueError("selection candidate binds a different completion")
        if (
            candidate.job_id,
            candidate.workflow_id,
            candidate.dispatch_id,
            candidate.session_id,
        ) != (
            assignment.job_id,
            assignment.workflow_id,
            assignment.dispatch_id,
            assignment.session_id,
        ):
            raise ValueError("selection candidate identity differs from the assignment")
        if candidate.candidate_id in result:
            raise ValueError("selection candidates must have unique IDs")
        result[candidate.candidate_id] = binding
    return result


def _report_map(
    candidates: list[CandidateBinding],
    reports: list[QualityBinding],
    *,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
) -> dict[str, QualityBinding]:
    """Match exactly one strict quality report to every candidate artifact."""

    artifact_to_id = {
        _artifact_key(artifact): candidate.candidate_id
        for candidate, artifact in candidates
    }
    result: dict[str, QualityBinding] = {}
    for binding in reports:
        report, _artifact = binding
        if report.assignment != assignment_artifact:
            raise ValueError("selection quality report binds a different assignment")
        if report.completion != completion_artifact:
            raise ValueError("selection quality report binds a different completion")
        candidate_id = artifact_to_id.get(_artifact_key(report.candidate))
        if candidate_id is None or candidate_id in result:
            raise ValueError("quality reports must exactly and uniquely bind candidates")
        result[candidate_id] = binding
    if set(result) != set(artifact_to_id.values()):
        raise ValueError("every selection candidate requires one quality report")
    return result


def _artifact_key(artifact: CodexImageArtifact) -> tuple[str, str, int, str]:
    """Return a hashable exact artifact key for candidate/report matching."""

    return (artifact.path, artifact.sha256, artifact.byte_size, artifact.kind)


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
