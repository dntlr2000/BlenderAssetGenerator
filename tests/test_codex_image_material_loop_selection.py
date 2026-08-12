"""Focused companion semantic-precedence and command-integration tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_autonomy_v2_codex_image_phase_service as phase_fixtures
import test_codex_imagegen_core as core_fixtures
from PIL import Image

from codex_blender_modeler.codex_imagegen import command_service
from codex_blender_modeler.codex_imagegen.artifacts import (
    artifact_for_codex_image,
    load_codex_image_model,
    write_immutable_codex_image_model,
)
from codex_blender_modeler.codex_imagegen.command_service import (
    run_codex_imagegen_controller_phase,
    select_codex_imagegen_phase,
)
from codex_blender_modeler.codex_imagegen.completion import (
    build_codex_imagegen_candidate,
    build_generated_image_evidence,
    copy_imagegen_png_and_write_completion,
)
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    ALL_SEMANTIC_REVIEW_CATEGORIES,
    CodexImageCompanionSelectionReceipt,
    CodexImageSemanticCheck,
    CodexImageSemanticReview,
    codex_image_candidate_ranking_evidence_path,
    codex_image_candidate_semantic_review_path,
    codex_image_companion_selection_receipt_path,
)
from codex_blender_modeler.codex_imagegen.material_loop_selection import (
    build_codex_image_candidate_ranking_evidence,
    build_codex_image_companion_selection_receipt,
    select_codex_imagegen_companion_candidate,
    validate_codex_imagegen_companion_selection,
)
from codex_blender_modeler.codex_imagegen.material_loop_semantic import (
    build_codex_image_semantic_review,
)
from codex_blender_modeler.codex_imagegen.models import (
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationQualityReport,
)
from codex_blender_modeler.codex_imagegen.quality import evaluate_candidate_quality

NOW = datetime(2026, 8, 13, 9, 0, tzinfo=UTC)

CandidateBinding = tuple[CodexImageGenerationCandidate, CodexImageArtifact]
QualityBinding = tuple[CodexImageGenerationQualityReport, CodexImageArtifact]
SemanticBinding = tuple[CodexImageSemanticReview, CodexImageArtifact]


@dataclass(frozen=True)
class _SelectionFixture:
    """Collect one exact two-candidate generation chain for focused ranking tests."""

    root: Path
    assignment: CodexImageGenerationAssignment
    assignment_artifact: CodexImageArtifact
    completion_artifact: CodexImageArtifact
    candidates: tuple[CandidateBinding, ...]
    reports: tuple[QualityBinding, ...]


def _write_variant_png(path: Path, *, variant: int) -> None:
    """Write a detailed square PNG whose opposite edges remain byte-equivalent."""

    image = Image.new("RGB", (64, 64))
    pixels = image.load()
    for y in range(64):
        for x in range(64):
            mirrored_x = min(x, 63 - x)
            mirrored_y = min(y, 63 - y)
            if variant == 0:
                value = (mirrored_x * 23 + mirrored_y * 41) % 256
            else:
                value = 48 + ((mirrored_x // 4 + mirrored_y // 6) % 3) * 62
            pixels[x, y] = (value, (value * (variant + 2)) % 256, 180 - value // 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


def _build_selection_fixture(
    root: Path,
    *,
    identical_sources: bool = False,
) -> _SelectionFixture:
    """Publish two candidates and their exact deterministic quality evidence."""

    assignment, assignment_artifact, _budget = core_fixtures._build_assignment(
        root,
        candidate_count=2,
    )
    source_root = root.parent / f"{root.name}-controller-sources"
    sources = [source_root / "candidate-00.png", source_root / "candidate-01.png"]
    _write_variant_png(sources[0], variant=0)
    _write_variant_png(sources[1], variant=0 if identical_sources else 1)
    output_paths = tuple(
        root / path
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    )
    completion = copy_imagegen_png_and_write_completion(
        controller_workspace_root=root,
        allowed_source_root=source_root,
        assignment_path=root / assignment_artifact.path,
        assignment_artifact=assignment_artifact,
        source_png_paths=sources,
        allowed_output_paths=output_paths,
        output_roles=["base_color", "base_color"],
        completion_id="completion-assignment-1",
        controller_kind="fake_for_tests",
        controller_executed_at=NOW,
    )
    completion_artifact = artifact_for_codex_image(
        root,
        output_paths[-1],
        artifact_id=completion.contract_id,
        kind="codex-image-generation-completion",
        media_type="application/json",
    )
    controller_request = core_fixtures._write_artifact(
        root,
        "production/autonomy_v2/session-1/codex_imagegen/controller-request.json",
        artifact_id="controller-request",
        kind="controller-request",
    )
    controller_result = core_fixtures._write_artifact(
        root,
        "production/autonomy_v2/session-1/codex_imagegen/controller-result.json",
        artifact_id="controller-result",
        kind="controller-result",
    )
    candidates: list[CandidateBinding] = []
    reports: list[QualityBinding] = []
    assignment_root = (
        root
        / "production/autonomy_v2/session-1/codex_imagegen/assignments/assignment-1"
    )
    for generated_file in completion.generated_files:
        ordinal = generated_file.ordinal
        candidate = build_codex_imagegen_candidate(
            contract_id=f"candidate-contract-{ordinal:02d}",
            assignment=assignment,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
            controller_request_artifact=controller_request,
            controller_result_artifact=controller_result,
            generated_file=generated_file,
            created_at=NOW + timedelta(seconds=1),
        )
        candidate_artifact = write_immutable_codex_image_model(
            root,
            assignment_root / f"candidate-{ordinal:02d}.json",
            candidate,
            kind="codex-image-generation-candidate",
        )
        evidence = build_generated_image_evidence(
            contract_id=f"generated-evidence-{ordinal:02d}",
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            created_at=NOW + timedelta(seconds=1),
        )
        evidence_artifact = write_immutable_codex_image_model(
            root,
            assignment_root / f"evidence-{ordinal:02d}.json",
            evidence,
            kind="codex-generated-image-evidence",
        )
        report = evaluate_candidate_quality(
            job_root=root,
            report_id=f"quality-{ordinal:02d}",
            assignment=assignment,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            generated_image_evidence=evidence,
            generated_image_evidence_artifact=evidence_artifact,
            created_at=NOW + timedelta(seconds=2),
        )
        report_artifact = write_immutable_codex_image_model(
            root,
            assignment_root / f"quality-{ordinal:02d}.json",
            report,
            kind="codex-image-generation-quality-report",
        )
        candidates.append((candidate, candidate_artifact))
        reports.append((report, report_artifact))
    assert all(report.outcome == "passed" for report, _artifact in reports)
    return _SelectionFixture(
        root=root,
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidates=tuple(candidates),
        reports=tuple(reports),
    )


def _semantic_checks(outcome: str) -> list[CodexImageSemanticCheck]:
    """Build canonical ordered checks for a pass, hard failure, or review boundary."""

    checks: list[CodexImageSemanticCheck] = []
    for category in ALL_SEMANTIC_REVIEW_CATEGORIES:
        item_outcome = "passed"
        explicit = False
        if outcome == "failed" and category == "unwanted_text":
            item_outcome = "failed"
            explicit = True
        elif outcome == "review_required" and category == "material_family_suitability":
            item_outcome = "review_required"
        checks.append(
            CodexImageSemanticCheck(
                category=category,
                outcome=item_outcome,
                confidence=0.9,
                rationale=f"current-task observation for {category}",
                explicit_forbidden_content=explicit,
            )
        )
    return checks


def _publish_candidate_ranking(
    fixture: _SelectionFixture,
    *,
    index: int,
    semantic_outcome: str = "passed",
    material_role_suitability: str = "suitable",
    repair_cost: float = 0.0,
    session_id: str | None = None,
) -> tuple[SemanticBinding, tuple[object, CodexImageArtifact]]:
    """Publish one canonical semantic review and its exact ranking evidence."""

    candidate, candidate_artifact = fixture.candidates[index]
    report, report_artifact = fixture.reports[index]
    ordinal = candidate.generated_file.ordinal
    review = build_codex_image_semantic_review(
        fixture.root,
        contract_id=f"semantic-{candidate.candidate_id}",
        job_id=fixture.assignment.job_id,
        workflow_id=fixture.assignment.workflow_id,
        dispatch_id=fixture.assignment.dispatch_id,
        session_id=session_id or fixture.assignment.session_id,
        candidate_id=candidate.candidate_id,
        reviewed_image=candidate.generated_file.artifact,
        assignment=fixture.assignment_artifact,
        deterministic_quality_report=report_artifact,
        material_family="wood",
        checks=_semantic_checks(semantic_outcome),
        created_at=NOW + timedelta(seconds=3),
    )
    semantic_path = fixture.root / codex_image_candidate_semantic_review_path(
        fixture.assignment.session_id,
        fixture.assignment.assignment_id,
        ordinal,
    )
    semantic_artifact = write_immutable_codex_image_model(
        fixture.root,
        semantic_path,
        review,
        kind="codex-image-semantic-review",
    )
    ranking = build_codex_image_candidate_ranking_evidence(
        fixture.root,
        contract_id=f"ranking-{candidate.candidate_id}",
        assignment=fixture.assignment,
        assignment_artifact=fixture.assignment_artifact,
        completion_artifact=fixture.completion_artifact,
        candidate=candidate,
        candidate_artifact=candidate_artifact,
        quality_report=report,
        quality_report_artifact=report_artifact,
        semantic_review=review,
        semantic_review_artifact=semantic_artifact,
        material_role_suitability=material_role_suitability,
        repair_cost=repair_cost,
        created_at=NOW + timedelta(seconds=4),
    )
    ranking_path = fixture.root / codex_image_candidate_ranking_evidence_path(
        fixture.assignment.session_id,
        fixture.assignment.assignment_id,
        ordinal,
    )
    ranking_artifact = write_immutable_codex_image_model(
        fixture.root,
        ranking_path,
        ranking,
        kind="codex-image-candidate-ranking-evidence",
    )
    return (review, semantic_artifact), (ranking, ranking_artifact)


def _select(
    fixture: _SelectionFixture,
    semantics: list[SemanticBinding],
    rankings: list[tuple[object, CodexImageArtifact]],
):
    """Run the companion selector against the fixture's exact current evidence set."""

    return select_codex_imagegen_companion_candidate(
        fixture.root,
        selection_id="selection-assignment-1",
        assignment=fixture.assignment,
        assignment_artifact=fixture.assignment_artifact,
        completion_artifact=fixture.completion_artifact,
        candidates=list(fixture.candidates),
        quality_reports=list(fixture.reports),
        semantic_reviews=semantics,
        ranking_evidence=rankings,
        created_at=NOW + timedelta(seconds=5),
    )


def test_semantic_hard_failure_excludes_the_higher_quality_candidate(
    tmp_path: Path,
) -> None:
    """Choose a valid runner-up instead of a higher-scoring forbidden-content image."""

    fixture = _build_selection_fixture(tmp_path)
    scores = [report.deterministic_score for report, _artifact in fixture.reports]
    assert scores[0] != scores[1]
    high_index = max(range(2), key=scores.__getitem__)
    valid_index = 1 - high_index
    semantics: list[SemanticBinding] = []
    rankings: list[tuple[object, CodexImageArtifact]] = []
    for index in range(2):
        semantic, ranking = _publish_candidate_ranking(
            fixture,
            index=index,
            semantic_outcome="failed" if index == high_index else "passed",
        )
        semantics.append(semantic)
        rankings.append(ranking)
    build = _select(fixture, semantics, rankings)
    selected = fixture.candidates[valid_index][0]
    assert build.outcome == "selected"
    assert build.core_selection.selected_candidate == fixture.candidates[valid_index][1]
    assert next(
        item for item in build.decisions if item.candidate_id == selected.candidate_id
    ).outcome == "selected"
    assert next(
        item
        for item in build.decisions
        if item.candidate_id == fixture.candidates[high_index][0].candidate_id
    ).reason_codes == ["semantic-hard-failed"]
    selection_artifact = write_immutable_codex_image_model(
        fixture.root,
        fixture.root
        / "production/autonomy_v2/session-1/codex_imagegen/assignments/assignment-1"
        / "selection.json",
        build.core_selection,
        kind="codex-image-generation-selection",
    )
    receipt = build_codex_image_companion_selection_receipt(
        receipt_id="companion-selection-assignment-1",
        assignment=fixture.assignment,
        assignment_artifact=fixture.assignment_artifact,
        completion_artifact=fixture.completion_artifact,
        core_selection_artifact=selection_artifact,
        build=build,
        created_at=NOW + timedelta(seconds=5),
    )
    write_immutable_codex_image_model(
        fixture.root,
        fixture.root
        / codex_image_companion_selection_receipt_path("session-1", "assignment-1"),
        receipt,
        kind="codex-image-companion-selection-receipt",
    )
    validate_codex_imagegen_companion_selection(fixture.root, receipt)
    assert receipt.human_reviewed is False
    assert receipt.core_selector_meaning_changed is False


def test_missing_candidate_ranking_fails_closed_to_review(tmp_path: Path) -> None:
    """Refuse automatic selection when even one current candidate lacks full evidence."""

    fixture = _build_selection_fixture(tmp_path)
    semantic, ranking = _publish_candidate_ranking(fixture, index=0)
    build = _select(fixture, [semantic], [ranking])
    assert build.outcome == "review_required"
    assert build.core_selection.selected_candidate is None
    assert build.missing_candidate_ids == (fixture.candidates[1][0].candidate_id,)
    assert all(item.outcome != "selected" for item in build.decisions)


def test_unresolved_semantic_review_stops_the_entire_candidate_set(
    tmp_path: Path,
) -> None:
    """Keep a complete but unresolved semantic set visible as review-required."""

    fixture = _build_selection_fixture(tmp_path)
    semantics: list[SemanticBinding] = []
    rankings: list[tuple[object, CodexImageArtifact]] = []
    for index in range(2):
        semantic, ranking = _publish_candidate_ranking(
            fixture,
            index=index,
            semantic_outcome="review_required" if index == 1 else "passed",
        )
        semantics.append(semantic)
        rankings.append(ranking)
    build = _select(fixture, semantics, rankings)
    assert build.outcome == "review_required"
    assert build.missing_candidate_ids == ()
    assert build.unresolved_candidate_ids == (fixture.candidates[1][0].candidate_id,)
    assert all(item.outcome != "selected" for item in build.decisions)


def test_wrong_task_identity_and_ranking_file_tamper_are_rejected(
    tmp_path: Path,
) -> None:
    """Reject identity drift before ranking and exact ranking bytes after publication."""

    wrong_root = tmp_path / "wrong-identity"
    wrong_fixture = _build_selection_fixture(wrong_root)
    with pytest.raises(ValueError, match="session identity changed"):
        _publish_candidate_ranking(
            wrong_fixture,
            index=0,
            session_id="another-session",
        )

    tamper_root = tmp_path / "tampered-ranking"
    fixture = _build_selection_fixture(tamper_root)
    semantics: list[SemanticBinding] = []
    rankings: list[tuple[object, CodexImageArtifact]] = []
    for index in range(2):
        semantic, ranking = _publish_candidate_ranking(fixture, index=index)
        semantics.append(semantic)
        rankings.append(ranking)
    tampered_path = fixture.root / rankings[0][1].path
    tampered_path.write_bytes(tampered_path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        _select(fixture, semantics, rankings)


def test_stable_candidate_id_breaks_an_exact_companion_tie(tmp_path: Path) -> None:
    """Use stable candidate ID only after every preceding ranking field ties."""

    fixture = _build_selection_fixture(tmp_path, identical_sources=True)
    semantics: list[SemanticBinding] = []
    rankings: list[tuple[object, CodexImageArtifact]] = []
    for index in range(2):
        semantic, ranking = _publish_candidate_ranking(fixture, index=index)
        semantics.append(semantic)
        rankings.append(ranking)
    assert rankings[0][0].precedence_key[:-1] == rankings[1][0].precedence_key[:-1]
    build = _select(fixture, semantics, rankings)
    expected_id = min(candidate.candidate_id for candidate, _artifact in fixture.candidates)
    selected = next(item for item in build.decisions if item.outcome == "selected")
    assert selected.candidate_id == expected_id


def test_multi_candidate_command_uses_exact_companion_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive the public select command through the additive multi-candidate path."""

    fixture = phase_fixtures._phase_fixture(
        tmp_path,
        monkeypatch,
        job_id="cmd-companion",
        material_boundary=True,
        candidate_count=2,
    )
    phase_fixtures._initialize(fixture)
    prompt = "Generate a neutral wood swatch without any text."
    first = run_codex_imagegen_controller_phase(
        job_id="cmd-companion",
        session_id=fixture.session_id,
        rendered_prompt_text=prompt,
        timeout_seconds=30,
    )
    assignment_artifact = CodexImageArtifact.model_validate(first["assignment"])
    source_root = tmp_path / "command-companion-sources"
    sources = [source_root / "candidate-00.png", source_root / "candidate-01.png"]
    for source in sources:
        phase_fixtures._write_generated_source(source)
    copy_imagegen_png_and_write_completion(
        controller_workspace_root=Path(first["controller_workspace_root"]),
        allowed_source_root=source_root,
        assignment_path=Path(first["assignment_snapshot"]),
        assignment_artifact=assignment_artifact,
        source_png_paths=sources,
        allowed_output_paths=tuple(Path(path) for path in first["allowed_output_paths"]),
        output_roles=["base_color", "base_color"],
        completion_id="completion-material-00",
        controller_kind="desktop_in_session",
        controller_executed_at=fixture.created_at + timedelta(seconds=8),
    )
    resumed = run_codex_imagegen_controller_phase(
        job_id="cmd-companion",
        session_id=fixture.session_id,
        rendered_prompt_text=prompt,
        timeout_seconds=30,
    )
    assert resumed["status"] == "completed"
    state, _state_artifact = command_service._overlay_state(
        fixture.root,
        fixture.session_id,
    )
    assert state.assignment is not None and state.completion is not None
    assignment = load_codex_image_model(
        fixture.root,
        state.assignment,
        CodexImageGenerationAssignment,
    )
    completion = load_codex_image_model(
        fixture.root,
        state.completion,
        CodexImageGenerationCompletion,
    )
    candidates, evidence = command_service._load_or_build_candidate_evidence(
        root=fixture.root,
        state=state,
        assignment=assignment,
        completion=completion,
    )
    reports = command_service._load_or_build_quality_reports(
        root=fixture.root,
        assignment=assignment,
        assignment_artifact=state.assignment,
        completion_artifact=state.completion,
        candidates=candidates,
        evidence=evidence,
        created_at=completion.controller_executed_at + timedelta(seconds=2),
    )
    command_fixture = _SelectionFixture(
        root=fixture.root,
        assignment=assignment,
        assignment_artifact=state.assignment,
        completion_artifact=state.completion,
        candidates=tuple(candidates),
        reports=tuple(reports),
    )
    for index in range(2):
        _publish_candidate_ranking(command_fixture, index=index)
    selected = select_codex_imagegen_phase(
        job_id="cmd-companion",
        session_id=fixture.session_id,
    )
    assert selected["selection"]["outcome"] == "selected"
    assert selected["companion_selection_receipt"] is not None
    receipt_artifact = CodexImageArtifact.model_validate(
        selected["companion_selection_receipt"]
    )
    receipt = load_codex_image_model(
        fixture.root,
        receipt_artifact,
        CodexImageCompanionSelectionReceipt,
    )
    validate_codex_imagegen_companion_selection(fixture.root, receipt)
    assert receipt.human_reviewed is False
    assert receipt.core_selection.path.endswith("/selection.json")
