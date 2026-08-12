"""Fail-closed multi-candidate semantic ranking for the material-loop companion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..blender_artifacts import stable_json_digest
from .artifacts import load_codex_image_model, validate_codex_image_artifact
from .assignment import validate_codex_imagegen_assignment_boundary
from .material_loop_models import (
    CodexImageCandidateRankingEvidence,
    CodexImageCompanionCandidateDecision,
    CodexImageCompanionSelectionReceipt,
    CodexImageSemanticReview,
    CompanionSelectionOutcome,
    MaterialRoleSuitability,
    candidate_ranking_input_sha256,
    companion_candidate_precedence_key,
    companion_selection_receipt_input_sha256,
)
from .material_loop_semantic import validate_codex_image_semantic_review
from .models import (
    CodexImageArtifact,
    CodexImageCandidateDecision,
    CodexImageGenerationAssignment,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
)

CandidateBinding = tuple[CodexImageGenerationCandidate, CodexImageArtifact]
QualityBinding = tuple[CodexImageGenerationQualityReport, CodexImageArtifact]
SemanticBinding = tuple[CodexImageSemanticReview, CodexImageArtifact]
RankingBinding = tuple[CodexImageCandidateRankingEvidence, CodexImageArtifact]


@dataclass(frozen=True)
class CodexImageCompanionSelectionBuild:
    """Return one core-compatible selection plus its companion decision grounds."""

    core_selection: CodexImageGenerationSelection
    decisions: tuple[CodexImageCompanionCandidateDecision, ...]
    missing_candidate_ids: tuple[str, ...]
    unresolved_candidate_ids: tuple[str, ...]
    outcome: CompanionSelectionOutcome


def build_codex_image_candidate_ranking_evidence(
    job_root: Path,
    *,
    contract_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidate: CodexImageGenerationCandidate,
    candidate_artifact: CodexImageArtifact,
    quality_report: CodexImageGenerationQualityReport,
    quality_report_artifact: CodexImageArtifact,
    semantic_review: CodexImageSemanticReview,
    semantic_review_artifact: CodexImageArtifact,
    material_role_suitability: MaterialRoleSuitability,
    repair_cost: float,
    producer: str = "current_codex_task_candidate_ranking",
    created_at: datetime | None = None,
) -> CodexImageCandidateRankingEvidence:
    """Build exact ranking evidence after replaying every candidate input binding."""

    validate_codex_imagegen_assignment_boundary(job_root, assignment)
    _validate_candidate_chain(
        job_root,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        quality_report=quality_report,
        quality_report_artifact=quality_report_artifact,
    )
    _validate_semantic_binding(
        job_root,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        candidate=candidate,
        quality_report_artifact=quality_report_artifact,
        semantic_review=semantic_review,
        semantic_review_artifact=semantic_review_artifact,
    )
    file_hard_gate_passed = _file_hard_gate_passed(quality_report)
    precedence_key = companion_candidate_precedence_key(
        file_hard_gate_passed=file_hard_gate_passed,
        deterministic_quality_outcome=quality_report.outcome,
        deterministic_quality_score=quality_report.deterministic_score,
        semantic_outcome=semantic_review.outcome,
        material_role_suitability=material_role_suitability,
        repair_cost=repair_cost,
        candidate_id=candidate.candidate_id,
    )
    input_sha256 = candidate_ranking_input_sha256(
        assignment=assignment_artifact,
        completion=completion_artifact,
        candidate=candidate_artifact,
        candidate_id=candidate.candidate_id,
        reviewed_image=candidate.generated_file.artifact,
        deterministic_quality_report=quality_report_artifact,
        semantic_review=semantic_review_artifact,
        file_hard_gate_passed=file_hard_gate_passed,
        deterministic_quality_outcome=quality_report.outcome,
        deterministic_quality_score=quality_report.deterministic_score,
        semantic_outcome=semantic_review.outcome,
        material_role_suitability=material_role_suitability,
        repair_cost=repair_cost,
    )
    return CodexImageCandidateRankingEvidence(
        contract_id=contract_id,
        ranking_id=contract_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=input_sha256,
        source_fingerprint=candidate.generated_file.artifact.sha256,
        producer=producer,
        provenance=[
            assignment_artifact,
            completion_artifact,
            candidate_artifact,
            candidate.generated_file.artifact,
            quality_report_artifact,
            semantic_review_artifact,
        ],
        created_at=created_at or datetime.now(UTC),
        assignment=assignment_artifact,
        completion=completion_artifact,
        candidate=candidate_artifact,
        candidate_id=candidate.candidate_id,
        reviewed_image=candidate.generated_file.artifact,
        deterministic_quality_report=quality_report_artifact,
        semantic_review=semantic_review_artifact,
        file_hard_gate_passed=file_hard_gate_passed,
        deterministic_quality_outcome=quality_report.outcome,
        deterministic_quality_score=quality_report.deterministic_score,
        semantic_outcome=semantic_review.outcome,
        material_role_suitability=material_role_suitability,
        repair_cost=repair_cost,
        precedence_key=precedence_key,
    )


def validate_codex_image_candidate_ranking_evidence(
    job_root: Path,
    ranking: CodexImageCandidateRankingEvidence,
    *,
    ranking_artifact: CodexImageArtifact,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidate: CodexImageGenerationCandidate,
    candidate_artifact: CodexImageArtifact,
    quality_report: CodexImageGenerationQualityReport,
    quality_report_artifact: CodexImageArtifact,
    semantic_review: CodexImageSemanticReview,
    semantic_review_artifact: CodexImageArtifact,
) -> None:
    """Reject ranking evidence that drifts from any current assignment-chain input."""

    validate_codex_imagegen_assignment_boundary(job_root, assignment)
    if load_codex_image_model(
        job_root,
        ranking_artifact,
        CodexImageCandidateRankingEvidence,
    ) != ranking:
        raise ValueError("candidate ranking differs from its exact artifact")
    for artifact in ranking.provenance:
        validate_codex_image_artifact(job_root, artifact)
    _validate_candidate_chain(
        job_root,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        quality_report=quality_report,
        quality_report_artifact=quality_report_artifact,
    )
    _validate_semantic_binding(
        job_root,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        candidate=candidate,
        quality_report_artifact=quality_report_artifact,
        semantic_review=semantic_review,
        semantic_review_artifact=semantic_review_artifact,
    )
    expected_identity = (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
    )
    if (
        ranking.job_id,
        ranking.workflow_id,
        ranking.dispatch_id,
        ranking.session_id,
    ) != expected_identity:
        raise ValueError("candidate ranking task identity differs from the assignment")
    if (
        ranking.assignment != assignment_artifact
        or ranking.completion != completion_artifact
        or ranking.candidate != candidate_artifact
        or ranking.candidate_id != candidate.candidate_id
        or ranking.reviewed_image != candidate.generated_file.artifact
        or ranking.deterministic_quality_report != quality_report_artifact
        or ranking.semantic_review != semantic_review_artifact
    ):
        raise ValueError("candidate ranking exact artifact binding is inconsistent")
    expected_scalars = (
        _file_hard_gate_passed(quality_report),
        quality_report.outcome,
        quality_report.deterministic_score,
        semantic_review.outcome,
    )
    observed_scalars = (
        ranking.file_hard_gate_passed,
        ranking.deterministic_quality_outcome,
        ranking.deterministic_quality_score,
        ranking.semantic_outcome,
    )
    if observed_scalars != expected_scalars:
        raise ValueError("candidate ranking derived values differ from exact evidence")


def select_codex_imagegen_companion_candidate(
    job_root: Path,
    *,
    selection_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidates: list[CandidateBinding],
    quality_reports: list[QualityBinding],
    semantic_reviews: list[SemanticBinding],
    ranking_evidence: list[RankingBinding],
    created_at: datetime,
) -> CodexImageCompanionSelectionBuild:
    """Select only with complete resolved evidence or return fail-closed review state."""

    if assignment.requested_candidate_count <= 1:
        raise ValueError("companion selection requires a multi-candidate assignment")
    if len(candidates) != assignment.requested_candidate_count:
        raise ValueError("companion selection must preserve every assignment candidate")
    validate_codex_imagegen_assignment_boundary(job_root, assignment)
    stored_completion = load_codex_image_model(
        job_root,
        completion_artifact,
        CodexImageGenerationCompletion,
    )
    if stored_completion.assignment != assignment_artifact:
        raise ValueError("companion completion binds another assignment")
    candidate_map = _candidate_map(candidates)
    report_map = _quality_map(quality_reports, candidate_map)
    semantic_map = _semantic_map(semantic_reviews, candidate_map)
    ranking_map = _ranking_map(ranking_evidence, candidate_map)
    decisions: list[CodexImageCompanionCandidateDecision] = []
    missing: list[str] = []
    unresolved: list[str] = []
    resolved_rankings: dict[str, CodexImageCandidateRankingEvidence] = {}
    for candidate_id in sorted(candidate_map):
        candidate, candidate_artifact = candidate_map[candidate_id]
        report, report_artifact = report_map[candidate_id]
        _validate_candidate_chain(
            job_root,
            assignment=assignment,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            quality_report=report,
            quality_report_artifact=report_artifact,
        )
        semantic_binding = semantic_map.get(candidate_id)
        ranking_binding = ranking_map.get(candidate_id)
        if semantic_binding is None or ranking_binding is None:
            missing.append(candidate_id)
            decisions.append(
                CodexImageCompanionCandidateDecision(
                    candidate_id=candidate_id,
                    candidate=candidate_artifact,
                    reviewed_image=candidate.generated_file.artifact,
                    deterministic_quality_report=report_artifact,
                    semantic_review=(
                        semantic_binding[1] if semantic_binding is not None else None
                    ),
                    outcome="review_required",
                    reason_codes=["companion-evidence-missing"],
                )
            )
            continue
        semantic, semantic_artifact = semantic_binding
        ranking, ranking_artifact = ranking_binding
        validate_codex_image_candidate_ranking_evidence(
            job_root,
            ranking,
            ranking_artifact=ranking_artifact,
            assignment=assignment,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            quality_report=report,
            quality_report_artifact=report_artifact,
            semantic_review=semantic,
            semantic_review_artifact=semantic_artifact,
        )
        resolved_rankings[candidate_id] = ranking
        if _ranking_requires_review(ranking):
            unresolved.append(candidate_id)
            decisions.append(
                CodexImageCompanionCandidateDecision(
                    candidate_id=candidate_id,
                    candidate=candidate_artifact,
                    reviewed_image=candidate.generated_file.artifact,
                    deterministic_quality_report=report_artifact,
                    semantic_review=semantic_artifact,
                    ranking_evidence=ranking_artifact,
                    precedence_key=ranking.precedence_key,
                    outcome="review_required",
                    reason_codes=["companion-review-required"],
                )
            )
            continue
        reasons = _ineligibility_reasons(ranking)
        decisions.append(
            CodexImageCompanionCandidateDecision(
                candidate_id=candidate_id,
                candidate=candidate_artifact,
                reviewed_image=candidate.generated_file.artifact,
                deterministic_quality_report=report_artifact,
                semantic_review=semantic_artifact,
                ranking_evidence=ranking_artifact,
                precedence_key=ranking.precedence_key,
                outcome="ineligible" if reasons else "rejected",
                reason_codes=reasons or ["lower-companion-precedence"],
            )
        )
    if missing or unresolved:
        outcome: CompanionSelectionOutcome = "review_required"
        decisions = [
            item
            if item.outcome in {"ineligible", "review_required"}
            else item.model_copy(
                update={
                    "outcome": "review_required",
                    "reason_codes": ["companion-set-review-required"],
                }
            )
            for item in decisions
        ]
    else:
        eligible_ids = [
            item.candidate_id for item in decisions if item.outcome == "rejected"
        ]
        if eligible_ids:
            selected_id = min(
                eligible_ids,
                key=lambda candidate_id: resolved_rankings[candidate_id].precedence_key,
            )
            decisions = [
                item.model_copy(
                    update={
                        "outcome": "selected",
                        "reason_codes": ["highest-companion-precedence"],
                    }
                )
                if item.candidate_id == selected_id
                else item
                for item in decisions
            ]
            outcome = "selected"
        else:
            outcome = "no_eligible_candidate"
    core_selection = build_codex_imagegen_companion_core_selection(
        selection_id=selection_id,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        decisions=decisions,
        outcome=outcome,
        created_at=created_at,
    )
    return CodexImageCompanionSelectionBuild(
        core_selection=core_selection,
        decisions=tuple(decisions),
        missing_candidate_ids=tuple(sorted(missing)),
        unresolved_candidate_ids=tuple(sorted(unresolved)),
        outcome=outcome,
    )


def build_codex_imagegen_companion_core_selection(
    *,
    selection_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    decisions: list[CodexImageCompanionCandidateDecision],
    outcome: CompanionSelectionOutcome,
    created_at: datetime,
) -> CodexImageGenerationSelection:
    """Project companion decisions into the unchanged core 0.1 selection contract."""

    core_decisions = [
        CodexImageCandidateDecision(
            candidate_id=item.candidate_id,
            candidate=item.candidate,
            quality_report=item.deterministic_quality_report,
            outcome=(
                item.outcome
                if item.outcome in {"selected", "rejected", "ineligible"}
                else "ineligible"
            ),
            reason_codes=item.reason_codes,
        )
        for item in decisions
    ]
    selected = next(
        (item for item in decisions if item.outcome == "selected"),
        None,
    )
    inputs = {
        "assignment": assignment_artifact.model_dump(mode="json"),
        "completion": completion_artifact.model_dump(mode="json"),
        "decisions": [item.model_dump(mode="json") for item in core_decisions],
    }
    provenance = _unique_artifacts(
        [
            assignment_artifact,
            completion_artifact,
            *[item.candidate for item in decisions],
            *[item.deterministic_quality_report for item in decisions],
        ]
    )
    return CodexImageGenerationSelection(
        contract_id=selection_id,
        selection_id=selection_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {
                **inputs,
                "selected_candidate_id": (
                    selected.candidate_id if selected is not None else None
                ),
            }
        ),
        producer="codex_blender_modeler.codex_imagegen.companion_selection",
        provenance=provenance,
        created_at=created_at,
        assignment=assignment_artifact,
        completion=completion_artifact,
        candidate_count=len(decisions),
        selected_candidate=(selected.candidate if selected is not None else None),
        selected_quality_report=(
            selected.deterministic_quality_report if selected is not None else None
        ),
        decisions=core_decisions,
        outcome=outcome,
    )


def build_codex_image_companion_selection_receipt(
    *,
    receipt_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    core_selection_artifact: CodexImageArtifact,
    build: CodexImageCompanionSelectionBuild,
    producer: str = "codex_imagegen_companion_selection_service",
    created_at: datetime | None = None,
) -> CodexImageCompanionSelectionReceipt:
    """Bind one published core selection to all companion ranking grounds."""

    decisions = list(build.decisions)
    selected = next(
        (item for item in decisions if item.outcome == "selected"),
        None,
    )
    provenance = _unique_artifacts(
        [
            assignment_artifact,
            completion_artifact,
            core_selection_artifact,
            *[item.candidate for item in decisions],
            *[item.reviewed_image for item in decisions],
            *[item.deterministic_quality_report for item in decisions],
            *[item.semantic_review for item in decisions if item.semantic_review],
            *[item.ranking_evidence for item in decisions if item.ranking_evidence],
        ]
    )
    input_sha256 = companion_selection_receipt_input_sha256(
        assignment=assignment_artifact,
        completion=completion_artifact,
        core_selection=core_selection_artifact,
        decisions=decisions,
        missing_candidate_ids=list(build.missing_candidate_ids),
        unresolved_candidate_ids=list(build.unresolved_candidate_ids),
        outcome=build.outcome,
    )
    return CodexImageCompanionSelectionReceipt(
        contract_id=receipt_id,
        receipt_id=receipt_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=input_sha256,
        source_fingerprint=assignment_artifact.sha256,
        producer=producer,
        provenance=provenance,
        created_at=created_at or datetime.now(UTC),
        assignment=assignment_artifact,
        completion=completion_artifact,
        core_selection=core_selection_artifact,
        candidate_count=len(decisions),
        decisions=decisions,
        missing_candidate_ids=list(build.missing_candidate_ids),
        unresolved_candidate_ids=list(build.unresolved_candidate_ids),
        selected_candidate=(selected.candidate if selected is not None else None),
        selected_quality_report=(
            selected.deterministic_quality_report if selected is not None else None
        ),
        selected_ranking_evidence=(
            selected.ranking_evidence if selected is not None else None
        ),
        outcome=build.outcome,
    )


def validate_codex_imagegen_companion_selection(
    job_root: Path,
    receipt: CodexImageCompanionSelectionReceipt,
) -> None:
    """Replay a receipt's complete evidence set and core selection deterministically."""

    assignment = load_codex_image_model(
        job_root,
        receipt.assignment,
        CodexImageGenerationAssignment,
    )
    core_selection = load_codex_image_model(
        job_root,
        receipt.core_selection,
        CodexImageGenerationSelection,
    )
    expected_identity = (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
    )
    for label, evidence in (
        ("receipt", receipt),
        ("core selection", core_selection),
    ):
        if (
            evidence.job_id,
            evidence.workflow_id,
            evidence.dispatch_id,
            evidence.session_id,
        ) != expected_identity:
            raise ValueError(f"companion {label} task identity differs from assignment")
    if core_selection.human_reviewed:
        raise ValueError("companion core selection cannot claim human review")
    candidates: list[CandidateBinding] = []
    reports: list[QualityBinding] = []
    semantics: list[SemanticBinding] = []
    rankings: list[RankingBinding] = []
    for decision in receipt.decisions:
        candidate = load_codex_image_model(
            job_root,
            decision.candidate,
            CodexImageGenerationCandidate,
        )
        report = load_codex_image_model(
            job_root,
            decision.deterministic_quality_report,
            CodexImageGenerationQualityReport,
        )
        candidates.append((candidate, decision.candidate))
        reports.append((report, decision.deterministic_quality_report))
        if decision.semantic_review is not None:
            semantics.append(
                (
                    load_codex_image_model(
                        job_root,
                        decision.semantic_review,
                        CodexImageSemanticReview,
                    ),
                    decision.semantic_review,
                )
            )
        if decision.ranking_evidence is not None:
            rankings.append(
                (
                    load_codex_image_model(
                        job_root,
                        decision.ranking_evidence,
                        CodexImageCandidateRankingEvidence,
                    ),
                    decision.ranking_evidence,
                )
            )
    replay = select_codex_imagegen_companion_candidate(
        job_root,
        selection_id=core_selection.selection_id,
        assignment=assignment,
        assignment_artifact=receipt.assignment,
        completion_artifact=receipt.completion,
        candidates=candidates,
        quality_reports=reports,
        semantic_reviews=semantics,
        ranking_evidence=rankings,
        created_at=core_selection.created_at,
    )
    if replay.core_selection != core_selection:
        raise ValueError("companion receipt core selection differs from exact replay")
    if (
        replay.decisions != tuple(receipt.decisions)
        or replay.missing_candidate_ids != tuple(receipt.missing_candidate_ids)
        or replay.unresolved_candidate_ids != tuple(receipt.unresolved_candidate_ids)
        or replay.outcome != receipt.outcome
    ):
        raise ValueError("companion receipt ranking grounds differ from exact replay")


def _validate_candidate_chain(
    job_root: Path,
    *,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidate: CodexImageGenerationCandidate,
    candidate_artifact: CodexImageArtifact,
    quality_report: CodexImageGenerationQualityReport,
    quality_report_artifact: CodexImageArtifact,
) -> None:
    """Require exact persisted assignment, candidate, report, and reviewed image bytes."""

    if load_codex_image_model(
        job_root,
        assignment_artifact,
        CodexImageGenerationAssignment,
    ) != assignment:
        raise ValueError("companion assignment differs from its exact artifact")
    if load_codex_image_model(
        job_root,
        candidate_artifact,
        CodexImageGenerationCandidate,
    ) != candidate:
        raise ValueError("companion candidate differs from its exact artifact")
    if load_codex_image_model(
        job_root,
        quality_report_artifact,
        CodexImageGenerationQualityReport,
    ) != quality_report:
        raise ValueError("companion quality report differs from its exact artifact")
    completion = load_codex_image_model(
        job_root,
        completion_artifact,
        CodexImageGenerationCompletion,
    )
    validate_codex_image_artifact(job_root, candidate.generated_file.artifact)
    if (
        completion.assignment != assignment_artifact
        or candidate.assignment != assignment_artifact
        or candidate.completion != completion_artifact
        or quality_report.assignment != assignment_artifact
        or quality_report.completion != completion_artifact
        or quality_report.candidate != candidate_artifact
    ):
        raise ValueError("companion candidate chain binds a different assignment")
    expected_identity = (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
    )
    for label, model in (
        ("completion", completion),
        ("candidate", candidate),
        ("quality report", quality_report),
    ):
        if (
            model.job_id,
            model.workflow_id,
            model.dispatch_id,
            model.session_id,
        ) != expected_identity:
            raise ValueError(f"companion {label} task identity differs from assignment")
    if quality_report.human_reviewed:
        raise ValueError("companion deterministic quality evidence cannot claim human review")


def _validate_semantic_binding(
    job_root: Path,
    *,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    candidate: CodexImageGenerationCandidate,
    quality_report_artifact: CodexImageArtifact,
    semantic_review: CodexImageSemanticReview,
    semantic_review_artifact: CodexImageArtifact,
) -> None:
    """Require one current-task semantic review for the exact candidate image and report."""

    if load_codex_image_model(
        job_root,
        semantic_review_artifact,
        CodexImageSemanticReview,
    ) != semantic_review:
        raise ValueError("semantic review differs from its exact artifact")
    validate_codex_image_semantic_review(
        job_root,
        semantic_review,
        expected_job_id=assignment.job_id,
        expected_workflow_id=assignment.workflow_id,
        expected_dispatch_id=assignment.dispatch_id,
        expected_session_id=assignment.session_id,
        expected_candidate_id=candidate.candidate_id,
        expected_reviewed_image_sha256=candidate.generated_file.artifact.sha256,
    )
    if (
        semantic_review.assignment != assignment_artifact
        or semantic_review.deterministic_quality_report != quality_report_artifact
        or semantic_review.reviewed_image != candidate.generated_file.artifact
    ):
        raise ValueError("semantic review exact artifact binding is inconsistent")


def _file_hard_gate_passed(report: CodexImageGenerationQualityReport) -> bool:
    """Derive file-level gates separately from later deterministic quality ranking."""

    file_checks = [
        item
        for item in report.checks
        if item.check_id in {"png-dimensions", "alpha-extractability"} and item.hard_gate
    ]
    dimensions = next(
        (item for item in report.checks if item.check_id == "png-dimensions"),
        None,
    )
    return (
        dimensions is not None
        and dimensions.status == "passed"
        and all(item.status == "passed" for item in file_checks)
    )


def _ranking_requires_review(ranking: CodexImageCandidateRankingEvidence) -> bool:
    """Stop globally when any supplied ranking input remains unresolved."""

    return (
        ranking.deterministic_quality_outcome in {"review_required", "unscorable"}
        or ranking.semantic_outcome in {"review_required", "unavailable"}
        or ranking.material_role_suitability == "review_required"
    )


def _ineligibility_reasons(
    ranking: CodexImageCandidateRankingEvidence,
) -> list[str]:
    """Return ordered definitive reasons that exclude one resolved candidate."""

    reasons: list[str] = []
    if not ranking.file_hard_gate_passed:
        reasons.append("file-hard-gate-failed")
    if ranking.deterministic_quality_outcome == "failed":
        reasons.append("deterministic-quality-failed")
    if ranking.semantic_outcome == "failed":
        reasons.append("semantic-hard-failed")
    if ranking.material_role_suitability == "unsuitable":
        reasons.append("material-role-unsuitable")
    return reasons


def _candidate_map(candidates: list[CandidateBinding]) -> dict[str, CandidateBinding]:
    """Index unique candidate bindings by stable candidate ID."""

    result: dict[str, CandidateBinding] = {}
    for binding in candidates:
        candidate, _artifact = binding
        if candidate.candidate_id in result:
            raise ValueError("companion candidates must use unique IDs")
        result[candidate.candidate_id] = binding
    return result


def _quality_map(
    reports: list[QualityBinding],
    candidates: dict[str, CandidateBinding],
) -> dict[str, QualityBinding]:
    """Match exactly one deterministic quality report to every candidate artifact."""

    candidate_by_artifact = {
        _artifact_key(artifact): candidate_id
        for candidate_id, (_candidate, artifact) in candidates.items()
    }
    result: dict[str, QualityBinding] = {}
    for binding in reports:
        report, _artifact = binding
        candidate_id = candidate_by_artifact.get(_artifact_key(report.candidate))
        if candidate_id is None or candidate_id in result:
            raise ValueError("companion quality reports must uniquely bind candidates")
        result[candidate_id] = binding
    if set(result) != set(candidates):
        raise ValueError("every companion candidate requires one quality report")
    return result


def _semantic_map(
    reviews: list[SemanticBinding],
    candidates: dict[str, CandidateBinding],
) -> dict[str, SemanticBinding]:
    """Index only unique semantic reviews belonging to the current candidate set."""

    result: dict[str, SemanticBinding] = {}
    for binding in reviews:
        review, _artifact = binding
        if review.candidate_id not in candidates or review.candidate_id in result:
            raise ValueError("semantic reviews must uniquely bind current candidates")
        result[review.candidate_id] = binding
    return result


def _ranking_map(
    rankings: list[RankingBinding],
    candidates: dict[str, CandidateBinding],
) -> dict[str, RankingBinding]:
    """Index only unique ranking evidence belonging to the current candidate set."""

    result: dict[str, RankingBinding] = {}
    for binding in rankings:
        ranking, _artifact = binding
        if ranking.candidate_id not in candidates or ranking.candidate_id in result:
            raise ValueError("ranking evidence must uniquely bind current candidates")
        result[ranking.candidate_id] = binding
    return result


def _unique_artifacts(items: list[CodexImageArtifact]) -> list[CodexImageArtifact]:
    """Preserve artifact order while deduplicating exact cross-field aliases."""

    result: list[CodexImageArtifact] = []
    seen: set[tuple[str, str, str, int]] = set()
    paths: set[str] = set()
    artifact_ids: set[str] = set()
    for item in items:
        key = _artifact_key(item)
        if key in seen:
            continue
        if item.path in paths or item.artifact_id in artifact_ids:
            raise ValueError("companion evidence contains artifact identity conflicts")
        result.append(item)
        seen.add(key)
        paths.add(item.path)
        artifact_ids.add(item.artifact_id)
    return result


def _artifact_key(artifact: CodexImageArtifact) -> tuple[str, str, str, int]:
    """Return the immutable artifact identity used for exact joins."""

    return (
        artifact.artifact_id,
        artifact.path,
        artifact.sha256,
        artifact.byte_size,
    )


__all__ = [
    "CodexImageCompanionSelectionBuild",
    "build_codex_image_candidate_ranking_evidence",
    "build_codex_image_companion_selection_receipt",
    "build_codex_imagegen_companion_core_selection",
    "select_codex_imagegen_companion_candidate",
    "validate_codex_image_candidate_ranking_evidence",
    "validate_codex_imagegen_companion_selection",
]
