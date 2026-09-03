"""Exercise terminal publication and crash-safe AQ adapter cancellation boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2 import approval_supervisor_service as one_prompt_service
from codex_blender_modeler.autonomy_v2 import (
    cancel_autonomy_v2,
    get_autonomy_v2_status,
)
from codex_blender_modeler.autonomy_v2.models import AutonomyStateV2
from codex_blender_modeler.autonomy_v2.supervisor_service import _write_next_state
from codex_blender_modeler.autonomy_v2.transitions import transition_state
from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.skill_orchestration import (
    cancel_aq_one_prompt_skill,
    get_aq_one_prompt_skill_status,
    get_skill_execution_trace,
    plan_aq_one_prompt_skill,
    run_aq_one_prompt_skill,
)
from codex_blender_modeler.skill_orchestration import service as skill_service

JOB_ID = "aqt"
RUN_ID = "aqt"


def _plan_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """Plan a short test-owned run so fixture path depth does not mask recovery faults."""

    workspace = tmp_path / "w"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (70, 100, 150)).save(reference)
    planned = plan_aq_one_prompt_skill(
        "Build this isolated static prop within the current task.",
        reference_path=reference,
        target_subject="isolated static prop",
        requested_delivery_profiles=["review_only"],
        explicit_autonomy_delegation_observed=True,
        job_id=JOB_ID,
        run_id=RUN_ID,
        experimental_opt_in=True,
    )
    return workspace / JOB_ID, str(planned["session_id"])


def _append_failed_base(root: Path, session_id: str) -> AutonomyStateV2:
    """Use a legal test-only transition to model an action's already-persisted failure."""

    status = get_autonomy_v2_status(JOB_ID, session_id)
    state = AutonomyStateV2.model_validate_json(json.dumps(status["state"]))
    failed = transition_state(
        state,
        event="failed",
        evidence=state.plan,
        created_at=datetime.now(UTC),
        reason="Test-owned technical action failed without canonical mutation.",
    )
    _write_next_state(root, root / "production" / "autonomy_v2" / session_id, failed)
    return failed


def _trace_counts() -> tuple[int, int]:
    """Revalidate the full public trace before counting routes and receipts."""

    trace = get_skill_execution_trace(JOB_ID, RUN_ID)
    return len(trace["routes"]), len(trace["receipts"])


def test_one_prompt_exception_closes_its_already_failed_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An action exception publishes a blocked companion without rewriting base failure."""

    root, session_id = _plan_run(tmp_path, monkeypatch)
    initial = root / "production" / "autonomy_v2" / session_id / "states" / "0000.json"
    initial_hash = sha256_file(initial)

    def fail_action(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Persist the terminal state before reproducing the original action error."""

        _append_failed_base(root, session_id)
        raise ValueError("injected terminal action failure")

    monkeypatch.setattr(one_prompt_service, "run_autonomy_v2", fail_action)
    with pytest.raises(ValueError, match="injected terminal action failure"):
        run_aq_one_prompt_skill(JOB_ID, RUN_ID, experimental_opt_in=True)
    status = get_aq_one_prompt_skill_status(JOB_ID, RUN_ID)
    assert status["status"] == "terminal"
    assert status["terminal"]["terminal_type"] == "blocked"
    assert status["terminal"]["campaign_terminal_candidate"] is False
    assert status["one_prompt"]["base_autonomy"]["state"]["status"] == "failed"
    telemetry_path = root / status["one_prompt"]["terminal"]["approval_telemetry"]["path"]
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    assert telemetry["additional_user_decision_count"] == 0
    assert telemetry["technical_user_approval_request_count"] == 0
    assert telemetry["canonical_corruption_count"] == 0
    assert sha256_file(initial) == initial_hash
    assert _trace_counts() == (1, 1)
    receipt = get_skill_execution_trace(JOB_ID, RUN_ID)["receipts"][0]
    assert receipt["outcome"] == "failed"


def test_last_action_terminal_does_not_require_another_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last bounded action publishes its exact terminal before returning a slice."""

    root, session_id = _plan_run(tmp_path, monkeypatch)

    def terminal_action(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Return a legal terminal transition from the final available action slot."""

        state = _append_failed_base(root, session_id)
        return {"state": state.model_dump(mode="json"), "stop_reason": "terminal"}

    monkeypatch.setattr(one_prompt_service, "run_autonomy_v2", terminal_action)
    status = run_aq_one_prompt_skill(JOB_ID, RUN_ID, max_actions=1, experimental_opt_in=True)
    assert status["status"] == "terminal"
    assert status["terminal"]["terminal_type"] == "blocked"
    assert _trace_counts() == (1, 1)


def test_cancel_rejects_stale_base_terminal_before_publishing_a_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unprojected base terminal cannot leave a receipt-less cancellation route."""

    root, session_id = _plan_run(tmp_path, monkeypatch)
    _append_failed_base(root, session_id)
    run_root = root / "skill_runs" / RUN_ID
    source_before = get_autonomy_v2_status(JOB_ID, session_id)["state_artifact"]
    with pytest.raises(RuntimeError, match="terminal.*cannot be cancelled"):
        cancel_aq_one_prompt_skill(
            JOB_ID, RUN_ID, reason="Do not recancel an existing failure.", experimental_opt_in=True
        )
    assert not list((run_root / "routes").glob("*.json"))
    assert not list((run_root / "underlying").glob("*-before-cancel.json"))
    assert get_autonomy_v2_status(JOB_ID, session_id)["state_artifact"] == source_before
    assert _trace_counts() == (0, 0)


def test_cancel_exception_records_a_failed_receipt_before_reraising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ordinary cancel failure remains traceable and cannot consume a second route."""

    _plan_run(tmp_path, monkeypatch)

    def fail_cancel(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Reject the cancel host call without advancing any base state."""

        raise ValueError("injected cancellation failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(skill_service, "cancel_one_prompt", fail_cancel)
        with pytest.raises(ValueError, match="injected cancellation failure"):
            cancel_aq_one_prompt_skill(
                JOB_ID, RUN_ID, reason="Exact cancel fixture.", experimental_opt_in=True
            )
    assert _trace_counts() == (1, 1)
    assert get_skill_execution_trace(JOB_ID, RUN_ID)["receipts"][0]["outcome"] == "failed"
    cancelled = cancel_aq_one_prompt_skill(
        JOB_ID, RUN_ID, reason="Fresh explicit cancel fixture.", experimental_opt_in=True
    )
    assert cancelled["terminal"]["terminal_type"] == "cancelled"
    assert _trace_counts() == (2, 2)


@pytest.mark.parametrize("crash_point", ["before_host", "after_base", "after_terminal"])
def test_pending_cancel_route_recovers_without_reexecuting_the_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, crash_point: str
) -> None:
    """Receipt all cancellation crash points from exact snapshots without a second cancel."""

    root, session_id = _plan_run(tmp_path, monkeypatch)
    original_cancel = skill_service.cancel_one_prompt

    def interrupt_cancel(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Interrupt before execution or between the two terminal publication layers."""

        if crash_point == "after_base":
            cancel_autonomy_v2(JOB_ID, session_id, reason="Exact base-only cancel fixture.")
        elif crash_point == "after_terminal":
            original_cancel(
                JOB_ID,
                session_id,
                reason="Exact terminal fixture.",
                allow_disabled_experimental=True,
            )
        raise KeyboardInterrupt("injected cancel interruption")

    monkeypatch.setattr(skill_service, "cancel_one_prompt", interrupt_cancel)
    with pytest.raises(KeyboardInterrupt, match="injected cancel interruption"):
        cancel_aq_one_prompt_skill(
            JOB_ID, RUN_ID, reason="Exact crash-bound cancel fixture.", experimental_opt_in=True
        )
    run_root = root / "skill_runs" / RUN_ID
    route_hash = sha256_file(run_root / "routes" / "0001.json")
    before_hash = sha256_file(run_root / "underlying" / "0001-before-cancel.json")
    base_before = get_autonomy_v2_status(JOB_ID, session_id)["state_artifact"]

    def forbid_action(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Prove pending-route reconciliation never retries a base action."""

        raise AssertionError("pending cancellation must not rerun a base action")

    monkeypatch.setattr(one_prompt_service, "run_autonomy_v2", forbid_action)
    recovered = run_aq_one_prompt_skill(JOB_ID, RUN_ID, experimental_opt_in=True)
    assert recovered["recovered_pending_route"] is True
    assert _trace_counts() == (1, 1)
    assert sha256_file(run_root / "routes" / "0001.json") == route_hash
    assert sha256_file(run_root / "underlying" / "0001-before-cancel.json") == before_hash
    assert get_autonomy_v2_status(JOB_ID, session_id)["state_artifact"] == base_before
    if crash_point == "before_host":
        assert recovered["terminal"] is None
        assert get_skill_execution_trace(JOB_ID, RUN_ID)["receipts"][0]["outcome"] == "failed"
    else:
        assert recovered["status"] == "terminal"
        assert recovered["terminal"]["terminal_type"] == "cancelled"
        assert recovered["terminal"]["campaign_terminal_candidate"] is False


def test_pending_cancel_reason_tamper_fails_before_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Supporting the cancel snapshot family must not loosen exact route provenance."""

    root, session_id = _plan_run(tmp_path, monkeypatch)

    def interrupt_cancel(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Leave one receipt-less route for the tamper-negative fixture."""

        raise KeyboardInterrupt("pending cancel fixture")

    monkeypatch.setattr(skill_service, "cancel_one_prompt", interrupt_cancel)
    with pytest.raises(KeyboardInterrupt):
        cancel_aq_one_prompt_skill(
            JOB_ID, RUN_ID, reason="Exact cancel fixture.", experimental_opt_in=True
        )
    run_root = root / "skill_runs" / RUN_ID
    route_path = run_root / "routes" / "0001.json"
    route = json.loads(route_path.read_text(encoding="utf-8"))
    route["reason"] = "An unbound cancellation claim."
    route_path.write_text(json.dumps(route), encoding="utf-8")
    before = get_autonomy_v2_status(JOB_ID, session_id)["state_artifact"]
    with pytest.raises(ValueError):
        run_aq_one_prompt_skill(JOB_ID, RUN_ID, experimental_opt_in=True)
    assert get_autonomy_v2_status(JOB_ID, session_id)["state_artifact"] == before
    assert not list((run_root / "receipts").glob("*.json"))
