"""Focused AQ v2 supervisor delivery terminal and recovery tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2 import supervisor_service
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyStateV2,
    DeliveryPlan,
    DeliveryRequest,
    DeliveryResult,
    DeliveryReviewBinding,
    DeliveryReviewEntry,
    DeliveryTerminalV2,
)
from codex_blender_modeler.autonomy_v2.profiles import delivery_profile
from codex_blender_modeler.blender_artifacts import stable_json_digest
from codex_blender_modeler.optimization.models import OptimizationApproval

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _artifact(name: str, *, kind: str | None = None) -> AQV2Artifact:
    """Create one valid synthetic artifact binding for orchestration-only tests."""

    return AQV2Artifact(
        artifact_id=name,
        kind=kind or name.replace("_", "-"),
        path=f"evidence/{name}.json",
        sha256=stable_json_digest({"artifact": name}),
        byte_size=1,
    )


def _evidence_fields(name: str, provenance: list[AQV2Artifact]) -> dict[str, object]:
    """Return stable common AQ v2 evidence fields for focused model fixtures."""

    return {
        "contract_id": name,
        "job_id": "aq-v2-supervisor-delivery",
        "workflow_id": "wf-aq-v2-supervisor-delivery",
        "dispatch_id": "dispatch-aq-v2-supervisor-delivery",
        "session_id": "aq-v2-supervisor-delivery",
        "input_sha256": stable_json_digest({"input": name}),
        "source_fingerprint": stable_json_digest({"source": name}),
        "producer": "tests.autonomy_v2.supervisor_delivery",
        "provenance": provenance,
        "created_at": NOW,
    }


def _pending_fixture(
    profile_ids: list[str],
) -> tuple[
    AutonomyPlanV2,
    AutonomyBudgetV2,
    AutonomyStateV2,
    DeliveryPlan,
    AQV2Artifact,
]:
    """Build one strict delivery-pending state and its immutable plan projection."""

    anchor = _artifact("anchor")
    plan_artifact = _artifact("autonomy-plan", kind="autonomy-plan")
    freeze_artifact = _artifact("quality-freeze", kind="quality-source-freeze")
    quality_terminal = _artifact("quality-terminal", kind="quality-terminal")
    delivery_plan_artifact = _artifact("delivery-plan", kind="delivery-plan")
    plan = AutonomyPlanV2(
        **_evidence_fields("plan-aq-v2-supervisor-delivery", [anchor]),
        plan_id="plan-aq-v2-supervisor-delivery",
        profile=anchor,
        root_authorization=anchor,
        budget=anchor,
        production_dispatch_plan=anchor,
        production_controller_plan=anchor,
        phase_tool_profiles=[anchor],
        requested_delivery_profiles=profile_ids,
    )
    budget = AutonomyBudgetV2(
        **_evidence_fields("budget-aq-v2-supervisor-delivery", [anchor]),
        budget_id="budget-aq-v2-supervisor-delivery",
        delivery_runs=sum(profile_id != "review_only" for profile_id in profile_ids),
    )
    requests = []
    for index, profile_id in enumerate(profile_ids, start=1):
        profile = delivery_profile(profile_id)
        portable = profile_id != "review_only"
        requests.append(
            DeliveryRequest(
                delivery_id=f"delivery-{index:02d}",
                profile=profile,
                source_freeze=freeze_artifact,
                run_id=f"run-{index:02d}" if portable else None,
                package_id=f"package-{index:02d}" if portable else None,
                status="planned" if portable else "review_only",
            )
        )
    delivery = DeliveryPlan(
        **_evidence_fields(
            "delivery-plan-aq-v2-supervisor-delivery",
            [anchor, freeze_artifact],
        ),
        plan_id="delivery-plan-aq-v2-supervisor-delivery",
        root_authorization=anchor,
        source_freeze=freeze_artifact,
        requests=requests,
    )
    state = AutonomyStateV2(
        **_evidence_fields(
            "state-aq-v2-supervisor-delivery-0006",
            [plan_artifact, quality_terminal, freeze_artifact, delivery_plan_artifact],
        ),
        state_id="state-aq-v2-supervisor-delivery-0006",
        plan=plan_artifact,
        sequence=6,
        phase="delivery",
        status="delivery_pending",
        next_action="await_v07_approval",
        quality_terminal=quality_terminal,
        source_freeze=freeze_artifact,
        delivery_plan=delivery_plan_artifact,
    )
    return plan, budget, state, delivery, delivery_plan_artifact


def _delivery_terminal(
    state: AutonomyStateV2,
    delivery: DeliveryPlan,
    results: list[DeliveryResult],
    *,
    review: AQV2Artifact | None,
) -> DeliveryTerminalV2:
    """Build a strict terminal bound to one focused pending-state fixture."""

    assert state.quality_terminal is not None
    assert state.source_freeze is not None
    assert state.delivery_plan is not None
    statuses = [result.status for result in results]
    outcome = (
        "review_only"
        if statuses == ["review_only"]
        else (
            "completed"
            if all(status == "completed" for status in statuses)
            else ("partial" if any(status == "completed" for status in statuses) else "failed")
        )
    )
    provenance = [state.quality_terminal, state.source_freeze, state.delivery_plan]
    if review is not None:
        provenance.append(review)
    return DeliveryTerminalV2(
        **_evidence_fields("delivery-terminal-aq-v2-supervisor-delivery", provenance),
        terminal_id="delivery-terminal-aq-v2-supervisor-delivery",
        quality_terminal=state.quality_terminal,
        source_freeze=state.source_freeze,
        delivery_plan=state.delivery_plan,
        delivery_review=review,
        outcome=outcome,
        results=results,
    )


def test_review_only_delivery_publishes_terminal_without_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finish review-only delivery without V0.7 approval, package, or executor work."""

    root = tmp_path / "job"
    root.mkdir()
    plan, _budget, state, delivery, _artifact_binding = _pending_fixture(
        ["review_only"]
    )
    terminal_artifact = _artifact("delivery-terminal", kind="delivery-terminal")
    published: dict[str, object] = {}

    def fake_publish(**kwargs: object) -> tuple[DeliveryTerminalV2, AQV2Artifact]:
        """Capture the review-only result passed to the real terminal boundary."""

        results = kwargs["results"]
        assert isinstance(results, list)
        assert kwargs["delivery_review_artifact"] is None
        assert [result.status for result in results] == ["review_only"]
        terminal = _delivery_terminal(state, delivery, results, review=None)
        published["terminal"] = terminal
        return terminal, terminal_artifact

    monkeypatch.setattr(
        supervisor_service,
        "execute_approved_delivery_plan_v2",
        lambda **_kwargs: pytest.fail("review-only delivery invoked the portable executor"),
    )
    monkeypatch.setattr(supervisor_service, "publish_delivery_terminal", fake_publish)
    monkeypatch.setattr(
        supervisor_service,
        "validate_delivery_terminal_v2",
        lambda _root, artifact: (
            published["terminal"]
            if artifact == terminal_artifact
            else pytest.fail("unexpected terminal artifact")
        ),
    )

    terminal, artifact = supervisor_service._adopt_or_publish_delivery_terminal(
        root=root,
        plan=plan,
        state=state,
        delivery=delivery,
        review_artifact=None,
    )

    assert artifact == terminal_artifact
    assert terminal.outcome == "review_only"
    assert terminal.results[0].production_ready is False
    assert terminal.results[0].package_manifest is None


def test_delivery_terminal_is_adopted_after_state_publication_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adopt a validated terminal without rerunning or republishing delivery work."""

    root = tmp_path / "job"
    terminal_path = (
        root
        / "production"
        / "autonomy_v2"
        / "aq-v2-supervisor-delivery"
        / "delivery_terminal.json"
    )
    terminal_path.parent.mkdir(parents=True)
    terminal_path.write_text("{}\n", encoding="utf-8")
    plan, _budget, state, delivery, _artifact_binding = _pending_fixture(
        ["review_only"]
    )
    result = DeliveryResult(
        delivery_id=delivery.requests[0].delivery_id,
        profile_id="review_only",
        status="review_only",
        source_freeze_sha256=delivery.source_freeze.sha256,
        production_ready=False,
    )
    terminal = _delivery_terminal(state, delivery, [result], review=None)
    terminal_artifact = _artifact("delivery-terminal", kind="delivery-terminal")

    monkeypatch.setattr(
        supervisor_service,
        "artifact_for_v2",
        lambda *_args, **_kwargs: terminal_artifact,
    )
    monkeypatch.setattr(
        supervisor_service,
        "validate_delivery_terminal_v2",
        lambda _root, artifact: terminal
        if artifact == terminal_artifact
        else pytest.fail("unexpected terminal artifact"),
    )
    monkeypatch.setattr(
        supervisor_service,
        "execute_approved_delivery_plan_v2",
        lambda **_kwargs: pytest.fail("crash adoption reran the delivery executor"),
    )
    monkeypatch.setattr(
        supervisor_service,
        "publish_delivery_terminal",
        lambda **_kwargs: pytest.fail("crash adoption republished the terminal"),
    )

    adopted, artifact = supervisor_service._adopt_or_publish_delivery_terminal(
        root=root,
        plan=plan,
        state=state,
        delivery=delivery,
        review_artifact=None,
    )

    assert adopted == terminal
    assert artifact == terminal_artifact


def test_portable_delivery_executes_once_then_publishes_validated_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Call the approved executor once and validate its newly published terminal."""

    root = tmp_path / "job"
    root.mkdir()
    plan, _budget, state, delivery, _artifact_binding = _pending_fixture(
        ["portable_gltf"]
    )
    review = _artifact("delivery-reviews", kind="delivery-reviews")
    terminal_artifact = _artifact("delivery-terminal", kind="delivery-terminal")
    failed = DeliveryResult(
        delivery_id=delivery.requests[0].delivery_id,
        profile_id="portable_gltf",
        status="failed",
        source_freeze_sha256=delivery.source_freeze.sha256,
        production_ready=False,
        errors=["bounded portable fixture failure"],
    )
    calls = {"execute": 0, "publish": 0}
    published: dict[str, DeliveryTerminalV2] = {}

    def fake_execute(**kwargs: object) -> list[DeliveryResult]:
        """Verify the executor receives the exact pending plan and review bindings."""

        calls["execute"] += 1
        assert kwargs == {
            "job_root": root,
            "delivery_plan_artifact": state.delivery_plan,
            "delivery_review_artifact": review,
        }
        return [failed]

    def fake_publish(**kwargs: object) -> tuple[DeliveryTerminalV2, AQV2Artifact]:
        """Bind the executor result into the terminal returned by the host service."""

        calls["publish"] += 1
        assert kwargs["quality_terminal_artifact"] == state.quality_terminal
        assert kwargs["delivery_plan_artifact"] == state.delivery_plan
        assert kwargs["delivery_review_artifact"] == review
        assert kwargs["results"] == [failed]
        terminal = _delivery_terminal(state, delivery, [failed], review=review)
        published["terminal"] = terminal
        return terminal, terminal_artifact

    monkeypatch.setattr(
        supervisor_service,
        "execute_approved_delivery_plan_v2",
        fake_execute,
    )
    monkeypatch.setattr(supervisor_service, "publish_delivery_terminal", fake_publish)
    monkeypatch.setattr(
        supervisor_service,
        "validate_delivery_terminal_v2",
        lambda _root, artifact: (
            published["terminal"]
            if artifact == terminal_artifact
            else pytest.fail("unexpected terminal artifact")
        ),
    )

    terminal, artifact = supervisor_service._adopt_or_publish_delivery_terminal(
        root=root,
        plan=plan,
        state=state,
        delivery=delivery,
        review_artifact=review,
    )

    assert calls == {"execute": 1, "publish": 1}
    assert artifact == terminal_artifact
    assert terminal.results == [failed]


def test_portable_terminal_crash_adoption_does_not_request_approval_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close state from a validated portable terminal without replaying consumed authority."""

    root = tmp_path / "job"
    session_root = root / "production" / "autonomy_v2" / "aq-v2-supervisor-delivery"
    session_root.mkdir(parents=True)
    (session_root / "delivery_terminal.json").write_text("{}\n", encoding="utf-8")
    plan, budget, state, delivery, _artifact_binding = _pending_fixture(
        ["portable_gltf"]
    )
    review = _artifact("delivery-reviews", kind="delivery-reviews")
    terminal_artifact = _artifact("delivery-terminal", kind="delivery-terminal")
    failed = DeliveryResult(
        delivery_id=delivery.requests[0].delivery_id,
        profile_id="portable_gltf",
        status="failed",
        source_freeze_sha256=delivery.source_freeze.sha256,
        production_ready=False,
        errors=["previous executor reached a bounded terminal"],
    )
    terminal = _delivery_terminal(state, delivery, [failed], review=review)

    monkeypatch.setattr(
        supervisor_service,
        "_validate_delivery_plan",
        lambda *_args: delivery,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_delivery_review_for_execution",
        lambda *_args: review,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_approval_boundary",
        lambda *_args: pytest.fail("published terminal requested approval again"),
    )
    monkeypatch.setattr(
        supervisor_service,
        "artifact_for_v2",
        lambda *_args, **_kwargs: terminal_artifact,
    )
    monkeypatch.setattr(
        supervisor_service,
        "validate_delivery_terminal_v2",
        lambda _root, artifact: terminal
        if artifact == terminal_artifact
        else pytest.fail("unexpected terminal artifact"),
    )
    monkeypatch.setattr(
        supervisor_service,
        "execute_approved_delivery_plan_v2",
        lambda **_kwargs: pytest.fail("published terminal reran portable delivery"),
    )
    monkeypatch.setattr(
        supervisor_service,
        "_write_next_state",
        lambda _root, _session_root, _state: _artifact("state-0007", kind="state"),
    )

    result = supervisor_service._advance_delivery_action(
        root=root,
        session_root=session_root,
        plan=plan,
        budget=budget,
        state=state,
    )

    assert result["advanced"] is True
    assert result["outcome"] == "failed"
    assert result["state"]["budget_usage"]["delivery_runs"] == 1


def test_missing_portable_approval_stops_before_budget_or_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return the exact approval wait without consuming action or delivery budget."""

    root = tmp_path / "job"
    root.mkdir()
    session_root = root / "production" / "autonomy_v2" / "aq-v2-supervisor-delivery"
    plan, budget, state, delivery, _artifact_binding = _pending_fixture(
        ["portable_gltf"]
    )
    review = _artifact("delivery-reviews", kind="delivery-reviews")
    boundary = {
        "advanced": False,
        "outcome": "waiting_for_v07_approval",
        "next_action": "approve_exact_v07_plans",
        "state": state.model_dump(mode="json"),
    }
    monkeypatch.setattr(
        supervisor_service,
        "_validate_delivery_plan",
        lambda *_args: delivery,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_delivery_review_for_execution",
        lambda *_args: review,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_approval_boundary",
        lambda *_args: boundary,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_consume_action_budget",
        lambda *_args, **_kwargs: pytest.fail("approval wait consumed budget"),
    )
    monkeypatch.setattr(
        supervisor_service,
        "_adopt_or_publish_delivery_terminal",
        lambda **_kwargs: pytest.fail("approval wait executed delivery"),
    )

    result = supervisor_service._advance_delivery_action(
        root=root,
        session_root=session_root,
        plan=plan,
        budget=budget,
        state=state,
    )

    assert result == boundary
    assert state.budget_usage.total_actions == 0
    assert state.budget_usage.delivery_runs == 0


def test_nonmatching_user_approval_is_rejected_before_delivery_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a user approval whose source hash differs from the frozen V0.7 source."""

    root = tmp_path / "job"
    root.mkdir()
    session_root = root / "production" / "autonomy_v2" / "aq-v2-supervisor-delivery"
    plan, budget, state, delivery, _artifact_binding = _pending_fixture(
        ["portable_gltf"]
    )
    request = delivery.requests[0]
    assert request.run_id is not None
    assert request.package_id is not None
    assert request.profile.asset_profile_id is not None
    profile_artifact = _artifact("asset-profile", kind="asset-profile")
    preflight_artifact = _artifact("preflight", kind="preflight-report")
    review_plan_artifact = _artifact("review-plan", kind="optimization-plan")
    review_artifact = _artifact("optimization-review", kind="optimization-review")
    binding_artifact = _artifact("delivery-reviews", kind="delivery-reviews")
    entry = DeliveryReviewEntry(
        delivery_id=request.delivery_id,
        profile_id="portable_gltf",
        asset_profile_id="portable_gltf",
        run_id=request.run_id,
        package_id=request.package_id,
        asset_profile=profile_artifact,
        optimization_plan=review_plan_artifact,
        optimization_review=review_artifact,
        exact_plan_sha256=review_plan_artifact.sha256,
    )
    binding = DeliveryReviewBinding(
        **_evidence_fields("review-binding-aq-v2-supervisor-delivery", [binding_artifact]),
        binding_id="review-binding-aq-v2-supervisor-delivery",
        delivery_plan=state.delivery_plan,
        source_freeze=delivery.source_freeze,
        entries=[entry],
    )
    approval = OptimizationApproval(
        approval_id="approval-aq-v2-supervisor-delivery",
        job_id=plan.job_id,
        run_id=request.run_id,
        profile_id=request.profile.asset_profile_id,
        plan_sha256=entry.exact_plan_sha256,
        review_sha256=entry.optimization_review.sha256,
        profile_sha256=entry.asset_profile.sha256,
        preflight_sha256=preflight_artifact.sha256,
        source_fingerprint="f" * 64,
        approval_note="Exact user review fixture with deliberately stale source.",
        approved_at=NOW,
    )
    approval_path = (
        root
        / "optimization"
        / "runs"
        / request.run_id
        / "optimization_approval.json"
    )
    approval_path.parent.mkdir(parents=True)
    approval_path.write_text(approval.model_dump_json(), encoding="utf-8")

    def fake_read(
        _root: Path,
        _artifact_binding: AQV2Artifact,
        model: object,
    ) -> object:
        """Return the exact freeze/plan fields needed by the approval boundary."""

        if getattr(model, "__name__", "") == "QualityApprovedSourceFreeze":
            return SimpleNamespace(v07_source_fingerprint="e" * 64)
        if getattr(model, "__name__", "") == "OptimizationPlan":
            return SimpleNamespace(preflight_report=preflight_artifact)
        pytest.fail(f"unexpected exact-model request: {model}")

    monkeypatch.setattr(
        supervisor_service,
        "_validate_delivery_plan",
        lambda *_args: delivery,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_delivery_review_for_execution",
        lambda *_args: binding_artifact,
    )
    monkeypatch.setattr(
        supervisor_service,
        "artifact_for_v2",
        lambda *_args, **_kwargs: binding_artifact,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_validate_delivery_review",
        lambda *_args: binding,
    )
    monkeypatch.setattr(supervisor_service, "_read_exact_model", fake_read)
    monkeypatch.setattr(
        supervisor_service,
        "validate_quality_source_freeze",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_adopt_or_publish_delivery_terminal",
        lambda **_kwargs: pytest.fail("stale approval reached the delivery executor"),
    )

    with pytest.raises(ValueError, match="differs from the exact"):
        supervisor_service._advance_delivery_action(
            root=root,
            session_root=session_root,
            plan=plan,
            budget=budget,
            state=state,
        )


def test_portable_delivery_consumes_one_action_and_hash_chains_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Charge independent formats once and bind their terminal into the next state hash."""

    root = tmp_path / "job"
    root.mkdir()
    session_root = root / "production" / "autonomy_v2" / "aq-v2-supervisor-delivery"
    plan, budget, state, delivery, _artifact_binding = _pending_fixture(
        ["portable_gltf", "portable_fbx"]
    )
    review = _artifact("delivery-reviews", kind="delivery-reviews")
    terminal_artifact = _artifact("delivery-terminal", kind="delivery-terminal")
    results = [
        DeliveryResult(
            delivery_id=request.delivery_id,
            profile_id=request.profile.profile_id,
            status="failed",
            source_freeze_sha256=delivery.source_freeze.sha256,
            production_ready=False,
            errors=[f"bounded failure for {request.delivery_id}"],
        )
        for request in delivery.requests
    ]
    terminal = _delivery_terminal(state, delivery, results, review=review)
    written: dict[str, AutonomyStateV2] = {}

    monkeypatch.setattr(
        supervisor_service,
        "_validate_delivery_plan",
        lambda *_args: delivery,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_delivery_review_for_execution",
        lambda *_args: review,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_approval_boundary",
        lambda *_args: {
            "advanced": False,
            "outcome": "delivery_executor_required",
            "state": state.model_dump(mode="json"),
        },
    )
    monkeypatch.setattr(
        supervisor_service,
        "_adopt_or_publish_delivery_terminal",
        lambda **_kwargs: (terminal, terminal_artifact),
    )

    def fake_write(
        _root: Path,
        _session_root: Path,
        next_state: AutonomyStateV2,
    ) -> AQV2Artifact:
        """Capture the exact next state that would be atomically published."""

        written["state"] = next_state
        return _artifact("state-0007", kind="state")

    monkeypatch.setattr(supervisor_service, "_write_next_state", fake_write)

    result = supervisor_service._advance_delivery_action(
        root=root,
        session_root=session_root,
        plan=plan,
        budget=budget,
        state=state,
    )

    next_state = written["state"]
    assert result["advanced"] is True
    assert result["outcome"] == "failed"
    assert next_state.status == "failed"
    assert next_state.next_action == "none"
    assert next_state.delivery_terminal == terminal_artifact
    assert next_state.delivery_results == results
    assert next_state.budget_usage.total_actions == 1
    assert next_state.budget_usage.delivery_runs == 2
    assert next_state.previous_state_sha256 == stable_json_digest(
        state.model_dump(mode="json")
    )
    assert next_state.provenance[-1] == terminal_artifact


def test_delivery_run_budget_fails_before_terminal_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed before delivery when the immutable run budget cannot cover formats."""

    root = tmp_path / "job"
    root.mkdir()
    session_root = root / "production" / "autonomy_v2" / "aq-v2-supervisor-delivery"
    plan, budget, state, delivery, _artifact_binding = _pending_fixture(
        ["portable_gltf", "portable_fbx"]
    )
    exhausted = budget.model_copy(update={"delivery_runs": 1})
    review = _artifact("delivery-reviews", kind="delivery-reviews")
    monkeypatch.setattr(
        supervisor_service,
        "_validate_delivery_plan",
        lambda *_args: delivery,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_delivery_review_for_execution",
        lambda *_args: review,
    )
    monkeypatch.setattr(
        supervisor_service,
        "_approval_boundary",
        lambda *_args: {
            "advanced": False,
            "outcome": "delivery_executor_required",
            "state": state.model_dump(mode="json"),
        },
    )
    monkeypatch.setattr(
        supervisor_service,
        "_adopt_or_publish_delivery_terminal",
        lambda **_kwargs: pytest.fail("exhausted delivery budget performed a side effect"),
    )

    with pytest.raises(PermissionError, match="delivery run budget"):
        supervisor_service._advance_delivery_action(
            root=root,
            session_root=session_root,
            plan=plan,
            budget=exhausted,
            state=state,
        )
