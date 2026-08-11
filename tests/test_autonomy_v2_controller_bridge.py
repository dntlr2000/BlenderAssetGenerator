"""AQ v2 bridge tests over the isolated ControllerExecutor contract."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2 import (
    AutonomyPlanV2,
    AutonomyStateV2,
    RootAuthorizationV2,
    advance_autonomy_v2,
    artifact_for_v2,
    cancel_autonomy_v2,
    execute_autonomy_v2_controller,
    get_autonomy_v2_status,
    plan_autonomous_static_prop_v2,
    run_autonomy_v2,
    transition_state,
)
from codex_blender_modeler.autonomy_v2.delivery_service import write_immutable_v2_model
from codex_blender_modeler.blender_artifacts import (
    native_io_path,
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.production.controller_executor import (
    ControllerExecutionRequest,
    DesktopInSessionController,
    FakeControllerForTests,
)


def _planned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_id: str,
) -> tuple[Path, dict[str, object]]:
    """Create one isolated internal v2 session for bridge behavior tests."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / f"{job_id}.png"
    Image.new("RGB", (32, 32), (40, 80, 120)).save(reference)
    planned = plan_autonomous_static_prop_v2(
        "Create only the test prop.",
        reference_path=reference,
        target_subject="test prop",
        requested_delivery_profiles=["review_only"],
        job_id=job_id,
        allow_disabled_experimental=True,
    )
    return workspace / job_id, planned


def _inputs(root: Path, session_id: str):
    """Publish one assignment and one immutable input for a controller invocation."""

    base = root / "production" / "autonomy_v2" / session_id / "test_inputs"
    base.mkdir(parents=True)
    assignment_path = base / "assignment.json"
    input_path = base / "camera.json"
    assignment_path.write_text('{"phase":"geometry"}\n', encoding="utf-8")
    input_path.write_text('{"camera":"fixed"}\n', encoding="utf-8")
    return (
        artifact_for_v2(
            root,
            assignment_path,
            artifact_id="geometry-assignment",
            kind="assignment",
        ),
        artifact_for_v2(
            root,
            input_path,
            artifact_id="fixed-camera",
            kind="camera",
        ),
    )


def _advance_reference_boundary(root: Path, session_id: str) -> None:
    """Record the exact copied reference before a controller can author a candidate."""

    session_root = root / "production" / "autonomy_v2" / session_id
    state_path = session_root / "states" / "0000.json"
    state = AutonomyStateV2.model_validate_json(state_path.read_bytes())
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    next_state = transition_state(
        state,
        event="reference_ready",
        evidence=authorization.primary_reference,
        created_at=state.created_at,
    )
    write_immutable_v2_model(
        root,
        session_root / "states" / "0001.json",
        next_state,
    )


def _rebind_root_authorization(
    root: Path,
    session_id: str,
    **updates: object,
) -> RootAuthorizationV2:
    """Replace temporary authorization bytes and rebuild the exact plan/state bindings."""

    session_root = root / "production" / "autonomy_v2" / session_id
    authorization_path = session_root / "root_authorization.json"
    plan_path = session_root / "plan.json"
    state_zero_path = session_root / "states" / "0000.json"
    state_one_path = session_root / "states" / "0001.json"
    authorization = RootAuthorizationV2.model_validate_json(
        authorization_path.read_bytes()
    ).model_copy(update=updates)
    plan = AutonomyPlanV2.model_validate_json(plan_path.read_bytes())
    state_zero = AutonomyStateV2.model_validate_json(state_zero_path.read_bytes())
    state_one = AutonomyStateV2.model_validate_json(state_one_path.read_bytes())
    write_json_atomic(authorization_path, authorization.model_dump(mode="json"))
    authorization_artifact = artifact_for_v2(
        root,
        authorization_path,
        artifact_id=plan.root_authorization.artifact_id,
        kind=plan.root_authorization.kind,
    )
    plan_inputs = {
        "profile": plan.profile.sha256,
        "authorization": authorization_artifact.sha256,
        "budget": plan.budget.sha256,
        "dispatch": plan.production_dispatch_plan.sha256,
        "controller": plan.production_controller_plan.sha256,
        "phase_profiles": [item.sha256 for item in plan.phase_tool_profiles],
    }
    rebound_plan = plan.model_copy(
        update={
            "root_authorization": authorization_artifact,
            "provenance": [
                plan.profile,
                authorization_artifact,
                plan.budget,
                plan.production_dispatch_plan,
                plan.production_controller_plan,
                *plan.phase_tool_profiles,
            ],
            "input_sha256": stable_json_digest(plan_inputs),
            "source_fingerprint": stable_json_digest(
                {
                    **plan_inputs,
                    "requested_deliveries": plan.requested_delivery_profiles,
                }
            ),
        }
    )
    write_json_atomic(plan_path, rebound_plan.model_dump(mode="json"))
    plan_artifact = artifact_for_v2(
        root,
        plan_path,
        artifact_id=state_zero.plan.artifact_id,
        kind=state_zero.plan.kind,
    )
    rebound_zero = state_zero.model_copy(
        update={
            "plan": plan_artifact,
            "provenance": [plan_artifact],
            "input_sha256": stable_json_digest(
                {"plan": plan_artifact.sha256, "sequence": 0}
            ),
            "source_fingerprint": stable_json_digest(
                {"plan": plan_artifact.sha256, "status": "planned"}
            ),
        }
    )
    write_json_atomic(state_zero_path, rebound_zero.model_dump(mode="json"))
    rebound_one = transition_state(
        rebound_zero,
        event="reference_ready",
        evidence=authorization.primary_reference,
        created_at=state_one.created_at,
    )
    write_json_atomic(state_one_path, rebound_one.model_dump(mode="json"))
    return authorization


def _desktop_output_paths(
    root: Path,
    session_id: str,
    request: ControllerExecutionRequest,
) -> list[Path]:
    """Map one immutable request's declared outputs into its execution-owned workspace."""

    workspace = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "controller_executions"
        / request.execution_id
        / "controller_workspace"
        / "outputs"
    )
    declared_root = PurePosixPath(request.output_root)
    return [
        workspace.joinpath(
            *PurePosixPath(relative).relative_to(declared_root).parts
        )
        for relative in request.allowed_output_paths
    ]


def test_v2_bridge_runs_one_isolated_controller_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful action consumes one budget unit and advances to quality evidence."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    result = execute_autonomy_v2_controller(
        "aq_v2_bridge",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=FakeControllerForTests(),
        timeout_seconds=30,
    )
    assert result["result"]["status"] == "completed"
    assert result["state"]["next_action"] == "validate_candidate"
    assert result["state"]["budget_usage"]["controller_invocations"] == 1
    assert not (root / "analysis" / "scene_spec.json").exists()
    status = get_autonomy_v2_status("aq_v2_bridge", session_id)
    assert status["state"]["sequence"] == 2

    with pytest.raises(PermissionError, match="not at a controller-authoring boundary"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=FakeControllerForTests(),
            timeout_seconds=30,
        )


def test_v2_bridge_rejects_partial_output_and_terminalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial controller output cannot become candidate evidence or canonical data."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_partial")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    result = execute_autonomy_v2_controller(
        "aq_v2_bridge_partial",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=FakeControllerForTests(behavior="partial"),
        timeout_seconds=30,
    )
    assert result["result"]["status"] == "rejected"
    assert result["result"]["outputs"] == []
    assert result["state"]["status"] == "failed"
    assert not (root / "analysis" / "scene_spec.json").exists()


def test_v2_bridge_timeout_terminalizes_without_retrying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout consumes one action and closes the session instead of waiting forever."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_timeout")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    controller = FakeControllerForTests(behavior="timeout")
    result = execute_autonomy_v2_controller(
        "aq_v2_bridge_timeout",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=controller,
        timeout_seconds=30,
    )

    assert result["result"]["status"] == "timeout"
    assert result["state"]["status"] == "failed"
    assert result["state"]["next_action"] == "none"
    assert "nonretryable" in result["state"]["terminal_reason"]
    assert controller.calls == 1
    bounded = run_autonomy_v2(
        "aq_v2_bridge_timeout",
        session_id,
        max_actions=2,
        allow_disabled_experimental=True,
    )
    assert bounded["stop_reason"] == "terminal"
    assert bounded["state"]["status"] == "failed"
    assert bounded["state"]["sequence"] == 2
    assert controller.calls == 1
    with pytest.raises(PermissionError, match="terminal"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge_timeout",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=controller,
            timeout_seconds=30,
        )


def test_v2_bridge_cancellation_stops_future_controller_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation appends evidence and blocks every later controller invocation."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_cancel")
    session_id = str(planned["session_id"])
    assignment, camera = _inputs(root, session_id)
    cancelled = cancel_autonomy_v2(
        "aq_v2_bridge_cancel",
        session_id,
        reason="user cancelled the experimental run",
    )
    assert cancelled["state"]["status"] == "cancelled"
    with pytest.raises(PermissionError, match="terminal"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge_cancel",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=FakeControllerForTests(),
            timeout_seconds=30,
        )


def test_v2_bridge_rehashes_inputs_before_controller_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changed assignment bytes fail before any controller output or state is published."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_stale")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    (root / assignment.path).write_text('{"phase":"tampered"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge_stale",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=FakeControllerForTests(),
            timeout_seconds=30,
        )
    assert get_autonomy_v2_status("aq_v2_bridge_stale", session_id)["state"][
        "sequence"
    ] == 1


def test_v2_bridge_revalidates_expiry_before_direct_controller_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired root authorization stops direct controller work before a request exists."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_expired")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    session_root = root / "production" / "autonomy_v2" / session_id
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    _rebind_root_authorization(
        root,
        session_id,
        expires_at=authorization.created_at,
    )
    assignment, camera = _inputs(root, session_id)

    with pytest.raises(PermissionError, match="authorization has expired"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge_expired",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=FakeControllerForTests(),
            timeout_seconds=30,
        )
    assert not (session_root / "controller_executions").exists()


def test_v2_bridge_requires_active_root_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inactive authorization cannot launch direct controller side effects."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_inactive")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    session_root = root / "production" / "autonomy_v2" / session_id
    _rebind_root_authorization(root, session_id, status="expired")
    assignment, camera = _inputs(root, session_id)

    with pytest.raises(PermissionError, match="authorization is not active"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge_inactive",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=FakeControllerForTests(),
            timeout_seconds=30,
        )
    assert not (session_root / "controller_executions").exists()


def test_v2_bridge_rejects_root_authorization_binding_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rehashed plan cannot broaden its profile or budget beyond root authorization."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_auth_drift")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    session_root = root / "production" / "autonomy_v2" / session_id
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    _rebind_root_authorization(
        root,
        session_id,
        budget=authorization.profile,
    )
    assignment, camera = _inputs(root, session_id)

    with pytest.raises(PermissionError, match="exact root authorization bindings"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge_auth_drift",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=FakeControllerForTests(),
            timeout_seconds=30,
        )
    assert not (session_root / "controller_executions").exists()


def test_v2_bridge_reconstructs_preexisting_execution_result_after_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash-stored result is fully revalidated without invoking its controller again."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_bridge_result_recovery")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    controller = FakeControllerForTests()
    import codex_blender_modeler.autonomy_v2.controller_bridge as bridge

    original_write = bridge.write_immutable_v2_model

    def interrupt_state_write(root_arg: Path, path: Path, model: object):
        """Inject one crash after the execution result but before state publication."""

        if path.name == "0002.json":
            raise RuntimeError("injected state publication crash")
        return original_write(root_arg, path, model)

    monkeypatch.setattr(bridge, "write_immutable_v2_model", interrupt_state_write)
    with pytest.raises(RuntimeError, match="injected state publication crash"):
        execute_autonomy_v2_controller(
            "aq_v2_bridge_result_recovery",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=controller,
            timeout_seconds=30,
        )
    monkeypatch.setattr(bridge, "write_immutable_v2_model", original_write)

    recovered = execute_autonomy_v2_controller(
        "aq_v2_bridge_result_recovery",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=controller,
        timeout_seconds=30,
    )
    assert recovered["result"]["status"] == "completed"
    assert recovered["state"]["next_action"] == "validate_candidate"
    assert controller.calls == 1


def test_public_run_resumes_one_exact_desktop_wait_without_duplicate_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Public advance/run adopt one pending desktop workspace without spending budget twice."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_desktop_resume")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    waiting = execute_autonomy_v2_controller(
        "aq_v2_desktop_resume",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=DesktopInSessionController(),
        timeout_seconds=30,
    )
    request = ControllerExecutionRequest.model_validate_json(
        json.dumps(waiting["request"])
    )
    assert waiting["result"]["status"] == "waiting_for_output"
    assert waiting["state"]["budget_usage"]["controller_invocations"] == 1
    session_root = root / "production" / "autonomy_v2" / session_id
    execution_root = session_root / "controller_executions" / request.execution_id
    invocation_path = execution_root / "controller_executor_evidence" / "invocation.json"
    invocation_sha256 = sha256_file(invocation_path)

    import codex_blender_modeler.autonomy_v2.supervisor_service as supervisor

    production_state = SimpleNamespace(
        model_dump=lambda **_kwargs: {"status": "fixture-current"}
    )
    monkeypatch.setattr(
        supervisor,
        "_validate_production_anchor",
        lambda *_args, **_kwargs: production_state,
    )
    first_wait = advance_autonomy_v2(
        "aq_v2_desktop_resume",
        session_id,
        allow_disabled_experimental=True,
    )
    second_wait = advance_autonomy_v2(
        "aq_v2_desktop_resume",
        session_id,
        allow_disabled_experimental=True,
    )
    assert first_wait["advanced"] is False
    assert second_wait["advanced"] is False
    assert first_wait["state"]["sequence"] == second_wait["state"]["sequence"] == 2
    assert len(list((session_root / "controller_executions").iterdir())) == 1
    assert sha256_file(invocation_path) == invocation_sha256

    for index, output in enumerate(_desktop_output_paths(root, session_id, request)):
        os.makedirs(native_io_path(output.parent), exist_ok=True)
        Path(native_io_path(output)).write_text(
            f"desktop-output-{index}\n",
            encoding="utf-8",
        )
    resumed = run_autonomy_v2(
        "aq_v2_desktop_resume",
        session_id,
        max_actions=2,
        allow_disabled_experimental=True,
    )
    assert resumed["actions_executed"] == 1
    assert resumed["stop_reason"] == "validate_candidate"
    assert resumed["state"]["sequence"] == 3
    assert resumed["state"]["next_action"] == "validate_candidate"
    assert resumed["state"]["budget_usage"]["controller_invocations"] == 1
    assert sha256_file(invocation_path) == invocation_sha256
    assert os.path.isfile(native_io_path(execution_root / "result.json"))
    assert os.path.isfile(native_io_path(execution_root / "adoption" / "result.json"))
    assert len(list((session_root / "controller_executions").iterdir())) == 1

    with pytest.raises(PermissionError, match="not at a controller-authoring boundary"):
        execute_autonomy_v2_controller(
            "aq_v2_desktop_resume",
            session_id,
            phase_profile_id="geometry_authoring",
            assignment=assignment,
            immutable_inputs=[camera],
            controller=DesktopInSessionController(),
            timeout_seconds=30,
        )


def test_desktop_adoption_result_is_reconstructed_after_state_write_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored desktop adoption result is fully validated before recovery transition."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_adoption_recovery")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    waiting = execute_autonomy_v2_controller(
        "aq_v2_adoption_recovery",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=DesktopInSessionController(),
        timeout_seconds=30,
    )
    request = ControllerExecutionRequest.model_validate_json(
        json.dumps(waiting["request"])
    )
    for index, output in enumerate(_desktop_output_paths(root, session_id, request)):
        os.makedirs(native_io_path(output.parent), exist_ok=True)
        Path(native_io_path(output)).write_text(
            f"desktop-recovery-output-{index}\n",
            encoding="utf-8",
        )
    session_root = root / "production" / "autonomy_v2" / session_id
    execution_root = session_root / "controller_executions" / request.execution_id

    import codex_blender_modeler.autonomy_v2.controller_bridge as bridge
    import codex_blender_modeler.autonomy_v2.supervisor_service as supervisor

    production_state = SimpleNamespace(
        model_dump=lambda **_kwargs: {"status": "fixture-current"}
    )
    monkeypatch.setattr(
        supervisor,
        "_validate_production_anchor",
        lambda *_args, **_kwargs: production_state,
    )
    original_write = bridge.write_immutable_v2_model

    def interrupt_state_write(root_arg: Path, path: Path, model: object):
        """Inject one crash after adoption result publication but before its state."""

        if path.name == "0003.json":
            raise RuntimeError("injected adoption state crash")
        return original_write(root_arg, path, model)

    monkeypatch.setattr(bridge, "write_immutable_v2_model", interrupt_state_write)
    with pytest.raises(RuntimeError, match="injected adoption state crash"):
        advance_autonomy_v2(
            "aq_v2_adoption_recovery",
            session_id,
            allow_disabled_experimental=True,
        )
    adoption_result = execution_root / "adoption" / "result.json"
    assert os.path.isfile(native_io_path(adoption_result))
    assert len(list((session_root / "states").glob("*.json"))) == 3
    monkeypatch.setattr(bridge, "write_immutable_v2_model", original_write)

    recovered = advance_autonomy_v2(
        "aq_v2_adoption_recovery",
        session_id,
        allow_disabled_experimental=True,
    )
    assert recovered["advanced"] is True
    assert recovered["recovered_action"] is True
    assert recovered["state"]["sequence"] == 3
    assert recovered["state"]["next_action"] == "validate_candidate"


def test_public_resume_rejects_a_stale_pending_request_without_new_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request mutation after waiting fails before output adoption or state publication."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_desktop_replay")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    waiting = execute_autonomy_v2_controller(
        "aq_v2_desktop_replay",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=DesktopInSessionController(),
        timeout_seconds=30,
    )
    request = ControllerExecutionRequest.model_validate_json(
        json.dumps(waiting["request"])
    )
    request_path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "controller_executions"
        / request.execution_id
        / "request.json"
    )
    Path(native_io_path(request_path)).write_text('{}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="nested artifact changed"):
        advance_autonomy_v2(
            "aq_v2_desktop_replay",
            session_id,
            allow_disabled_experimental=True,
        )
    state_paths = list(
        (root / "production" / "autonomy_v2" / session_id / "states").glob("*.json")
    )
    assert len(state_paths) == 3


def test_desktop_resume_rejects_job_root_mutation_before_output_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed protected job inventory vetoes desktop adoption despite exact outputs."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_desktop_job_mutation")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    waiting = execute_autonomy_v2_controller(
        "aq_v2_desktop_job_mutation",
        session_id,
        phase_profile_id="geometry_authoring",
        assignment=assignment,
        immutable_inputs=[camera],
        controller=DesktopInSessionController(),
        timeout_seconds=30,
    )
    request = ControllerExecutionRequest.model_validate_json(
        json.dumps(waiting["request"])
    )
    for index, output in enumerate(_desktop_output_paths(root, session_id, request)):
        os.makedirs(native_io_path(output.parent), exist_ok=True)
        Path(native_io_path(output)).write_text(
            f"desktop-output-{index}\n",
            encoding="utf-8",
        )
    changed = root / "analysis" / "unexpected-canonical.json"
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text('{"changed":true}\n', encoding="utf-8")

    import codex_blender_modeler.autonomy_v2.supervisor_service as supervisor

    production_state = SimpleNamespace(
        model_dump=lambda **_kwargs: {"status": "fixture-current"}
    )
    monkeypatch.setattr(
        supervisor,
        "_validate_production_anchor",
        lambda *_args, **_kwargs: production_state,
    )
    with pytest.raises(PermissionError, match="protected files.*changed"):
        advance_autonomy_v2(
            "aq_v2_desktop_job_mutation",
            session_id,
            allow_disabled_experimental=True,
        )
    session_root = root / "production" / "autonomy_v2" / session_id
    assert len(list((session_root / "states").glob("*.json"))) == 3
    assert not os.path.exists(
        native_io_path(
            session_root
            / "controller_executions"
            / request.execution_id
            / "adoption"
            / "result.json"
        )
    )


def test_status_rejects_a_rehashed_out_of_order_state_splice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A numbered state with valid hashes cannot skip authoring and quality phases."""

    root, planned = _planned(tmp_path, monkeypatch, "aq_v2_state_splice")
    session_id = str(planned["session_id"])
    session_root = root / "production" / "autonomy_v2" / session_id
    previous = AutonomyStateV2.model_validate_json(
        (session_root / "states" / "0000.json").read_bytes()
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (session_root / "root_authorization.json").read_bytes()
    )
    evidence = authorization.primary_reference
    previous_sha256 = stable_json_digest(previous.model_dump(mode="json"))
    payload = {
        "previous": previous_sha256,
        "event": "delivery_planned",
        "evidence": evidence.sha256,
        "sequence": 1,
    }
    forged = AutonomyStateV2(
        contract_id=f"state-{session_id}-0001",
        job_id=previous.job_id,
        workflow_id=previous.workflow_id,
        dispatch_id=previous.dispatch_id,
        session_id=previous.session_id,
        input_sha256=stable_json_digest(payload),
        source_fingerprint=stable_json_digest(
            {
                **payload,
                "status": "delivery_pending",
                "next_action": "await_v07_approval",
            }
        ),
        producer="codex_blender_modeler.autonomy_v2.transitions",
        provenance=[*previous.provenance, evidence],
        created_at=previous.created_at,
        state_id=f"state-{session_id}-0001",
        plan=previous.plan,
        sequence=1,
        phase="delivery",
        status="delivery_pending",
        next_action="await_v07_approval",
        delivery_plan=evidence,
        previous_state_sha256=previous_sha256,
    )
    write_immutable_v2_model(
        root,
        session_root / "states" / "0001.json",
        forged,
    )

    with pytest.raises(ValueError, match="invalid for the current state boundary"):
        get_autonomy_v2_status("aq_v2_state_splice", session_id)
