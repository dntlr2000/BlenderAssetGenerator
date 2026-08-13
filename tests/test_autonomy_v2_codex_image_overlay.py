"""Focused tests for the append-only Codex ImageGen AQ v2 overlay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from codex_blender_modeler.autonomy_v2.codex_image_overlay import (
    codex_image_overlay_profile_status,
    initial_codex_image_overlay,
    transition_codex_image_overlay,
)
from codex_blender_modeler.codex_imagegen.models import (
    CodexImageArtifact,
    CodexImageGenerationBudgetUsage,
)


def _artifact(name: str, ordinal: int) -> CodexImageArtifact:
    """Build one valid in-memory artifact binding for pure transition tests."""

    return CodexImageArtifact(
        artifact_id=name,
        kind=name,
        path=f"production/autonomy_v2/session/codex_imagegen/test/{name}.json",
        sha256=f"{ordinal:064x}",
        byte_size=ordinal + 1,
        media_type="application/json",
    )


def _initial(*, allowed: bool = True):
    """Create one explicitly opted-in sequence-zero overlay state."""

    return initial_codex_image_overlay(
        job_id="codex-overlay-job",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        session_id="session",
        generation_plan=_artifact("generation-plan", 1),
        provider_profile=_artifact("provider-profile", 2),
        budget=_artifact("generation-budget", 3),
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
        codex_imagegen_allowed=allowed,
    )


def test_overlay_requires_explicit_opt_in_and_reports_disabled_boundary() -> None:
    """Keep the overlay disabled by default and free of task or credential authority."""

    with pytest.raises(PermissionError, match="codex_imagegen_allowed=true"):
        _initial(allowed=False)

    status = codex_image_overlay_profile_status()
    assert status["status"] == "disabled_experimental"
    assert status["controller_required"] is True
    assert status["repository_can_spawn_codex_task"] is False
    assert status["autonomous_daemon"] is False
    assert status["api_key_required"] is False
    assert status["destination_project_write"] is False


def test_overlay_records_the_complete_wait_adopt_resume_chain() -> None:
    """Advance only through exact assignment, completion, quality, and adoption evidence."""

    now = datetime(2026, 8, 11, tzinfo=UTC)
    state = _initial()
    assignment = _artifact("assignment", 4)
    state = transition_codex_image_overlay(
        state,
        event="assignment_published",
        evidence=[assignment],
        assignment=assignment,
        created_at=now + timedelta(seconds=1),
    )
    assert (state.phase, state.status, state.next_action) == (
        "controller",
        "waiting_for_controller",
        "adopt_completion",
    )
    assert state.budget_usage == CodexImageGenerationBudgetUsage()

    completion = _artifact("completion", 5)
    controller_request = _artifact("controller-request", 19)
    controller_result = _artifact("controller-result", 17)
    usage = CodexImageGenerationBudgetUsage(
        assignments=1,
        total_generations=2,
        candidates=2,
        elapsed_seconds=9,
    )
    state = transition_codex_image_overlay(
        state,
        event="completion_adopted",
        evidence=[controller_request, completion, controller_result],
        controller_request=controller_request,
        completion=completion,
        controller_result=controller_result,
        budget_usage=usage,
        created_at=now + timedelta(seconds=2),
    )
    candidates = [_artifact("candidate-0", 6), _artifact("candidate-1", 7)]
    reports = [_artifact("report-0", 8), _artifact("report-1", 9)]
    state = transition_codex_image_overlay(
        state,
        event="quality_completed",
        evidence=[*candidates, *reports],
        candidates=candidates,
        quality_reports=reports,
        created_at=now + timedelta(seconds=3),
    )
    selection = _artifact("selection", 10)
    state = transition_codex_image_overlay(
        state,
        event="candidate_selected",
        evidence=[selection],
        selection=selection,
        created_at=now + timedelta(seconds=4),
    )
    adoption = _artifact("material-adoption", 11)
    material_receipt = _artifact("material-authoring-receipt", 18)
    terminal = _artifact("generation-terminal", 12)
    state = transition_codex_image_overlay(
        state,
        event="material_adopted",
        evidence=[adoption, material_receipt, terminal],
        material_adoption=adoption,
        material_authoring_receipt=material_receipt,
        generation_terminal=terminal,
        created_at=now + timedelta(seconds=5),
    )
    resumed = _artifact("base-resume-state", 13)
    state = transition_codex_image_overlay(
        state,
        event="base_material_authoring_resumed",
        evidence=[resumed],
        base_resume_state=resumed,
        created_at=now + timedelta(seconds=6),
    )

    assert state.status == "completed"
    assert state.sequence == 6
    assert state.budget_usage == usage
    assert state.base_resume_state == resumed
    assert state.provenance[-1] == resumed
    with pytest.raises(ValueError, match="cannot transition"):
        transition_codex_image_overlay(
            state,
            event="cancelled",
            evidence=[terminal],
            generation_terminal=terminal,
            created_at=now + timedelta(seconds=7),
        )


def test_overlay_rejects_out_of_order_or_incomplete_evidence() -> None:
    """Fail closed when a caller skips a boundary or supplies the wrong exact artifact."""

    state = _initial()
    now = datetime(2026, 8, 11, tzinfo=UTC)
    assignment = _artifact("assignment", 4)
    with pytest.raises(ValueError, match="invalid Codex ImageGen overlay transition"):
        transition_codex_image_overlay(
            state,
            event="completion_adopted",
            evidence=[_artifact("completion", 5)],
            completion=_artifact("completion", 5),
            created_at=now,
        )
    with pytest.raises(ValueError, match="exact assignment evidence"):
        transition_codex_image_overlay(
            state,
            event="assignment_published",
            evidence=[_artifact("wrong-assignment", 14)],
            assignment=assignment,
            created_at=now,
        )


def test_overlay_terminal_requires_only_its_exact_terminal_artifact() -> None:
    """Prevent a fallback terminal from smuggling unrelated transition evidence."""

    state = _initial()
    terminal = _artifact("fallback-terminal", 15)
    unrelated = _artifact("unrelated", 16)
    with pytest.raises(ValueError, match="exact generation terminal"):
        transition_codex_image_overlay(
            state,
            event="local_procedural_fallback",
            evidence=[terminal, unrelated],
            generation_terminal=terminal,
            created_at=datetime(2026, 8, 11, tzinfo=UTC),
        )

    closed = transition_codex_image_overlay(
        state,
        event="local_procedural_fallback",
        evidence=[terminal],
        generation_terminal=terminal,
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
        reason="immutable ImageGen budget is unavailable",
    )
    assert closed.status == "local_procedural_fallback"
    assert closed.next_action == "none"
    assert closed.terminal_reason == "immutable ImageGen budget is unavailable"


def test_overlay_appends_one_exact_normalized_material_evidence_repair() -> None:
    """Preserve the direct receipt while accepting only plan/approval/new receipt evidence."""

    now = datetime(2026, 8, 11, tzinfo=UTC)
    state = _initial()
    assignment = _artifact("assignment", 20)
    state = transition_codex_image_overlay(
        state,
        event="assignment_published",
        evidence=[assignment],
        assignment=assignment,
        created_at=now + timedelta(seconds=1),
    )
    request = _artifact("controller-request", 21)
    completion = _artifact("completion", 22)
    result = _artifact("controller-result", 23)
    state = transition_codex_image_overlay(
        state,
        event="completion_adopted",
        evidence=[request, completion, result],
        controller_request=request,
        completion=completion,
        controller_result=result,
        budget_usage=CodexImageGenerationBudgetUsage(assignments=1),
        created_at=now + timedelta(seconds=2),
    )
    candidate = _artifact("candidate", 24)
    report = _artifact("report", 25)
    state = transition_codex_image_overlay(
        state,
        event="quality_completed",
        evidence=[candidate, report],
        candidates=[candidate],
        quality_reports=[report],
        created_at=now + timedelta(seconds=3),
    )
    selection = _artifact("selection", 26)
    state = transition_codex_image_overlay(
        state,
        event="candidate_selected",
        evidence=[selection],
        selection=selection,
        created_at=now + timedelta(seconds=4),
    )
    adoption = _artifact("material-adoption", 27)
    direct_receipt = _artifact("direct-material-receipt", 28)
    terminal = _artifact("generation-terminal", 29)
    state = transition_codex_image_overlay(
        state,
        event="material_candidate_staged",
        evidence=[adoption, direct_receipt, terminal],
        material_adoption=adoption,
        material_authoring_receipt=direct_receipt,
        generation_terminal=terminal,
        created_at=now + timedelta(seconds=5),
    )
    plan = _artifact("repair-plan", 30).model_copy(
        update={"kind": "material-evidence-repair-plan"}
    )
    approval = _artifact("repair-approval", 31).model_copy(
        update={"kind": "material-evidence-repair-approval"}
    )
    normalized = _artifact("normalized-material-receipt", 32).model_copy(
        update={"kind": "codex-image-normalized-material-authoring-receipt"}
    )

    repaired = transition_codex_image_overlay(
        state,
        event="material_evidence_repaired",
        evidence=[plan, approval, normalized],
        material_authoring_receipt=normalized,
        created_at=now + timedelta(seconds=6),
    )

    assert repaired.sequence == state.sequence + 1
    assert repaired.material_authoring_receipt == normalized
    assert direct_receipt in repaired.provenance
    assert repaired.provenance[-3:] == [plan, approval, normalized]
    assert (repaired.phase, repaired.status, repaired.next_action) == (
        "adoption",
        "adopted",
        "controller_promotion_required",
    )
    with pytest.raises(ValueError, match="replay consumed evidence"):
        transition_codex_image_overlay(
            state,
            event="material_evidence_repaired",
            evidence=[plan, approval, direct_receipt],
            material_authoring_receipt=direct_receipt,
            created_at=now + timedelta(seconds=6),
        )
