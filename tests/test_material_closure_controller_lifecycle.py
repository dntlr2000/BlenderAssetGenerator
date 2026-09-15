"""Exercise material authority at the real host/executor boundary on isolated jobs."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from test_autonomy_v2_controller_bridge import _advance_reference_boundary, _inputs, _planned

from codex_blender_modeler.autonomy_v2 import controller_bridge as bridge
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.material_phase_service import (
    MaterialPhaseError,
    _validate_material_controller_progression,
)
from codex_blender_modeler.blender_artifacts import native_io_path
from codex_blender_modeler.production.controller_executor import DesktopInSessionController


def _material_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use real lifecycle contracts with only preflight and authority content stubbed."""
    root, planned = _planned(tmp_path, monkeypatch, "material_lifecycle")
    session_id = str(planned["session_id"])
    _advance_reference_boundary(root, session_id)
    assignment, camera = _inputs(root, session_id)
    boundary = assignment.model_copy(update={"kind": "material-policy-promotion-boundary"})
    entry = SimpleNamespace(
        entry_id=camera.artifact_id,
        path=camera.path,
        sha256=camera.sha256,
        byte_size=camera.byte_size,
    )
    closure = SimpleNamespace(entries=[entry], project_planned_output_map=lambda: {})
    session = root / "production/autonomy_v2" / session_id
    source_state = bridge._session_bundle(root.name, session_id)[4]
    consumptions: list[str] = []
    delegates: list[str] = []

    def validate_boundary(
        _root, _plan, observed, *, state=None, require_boundary_state=False, **_kwargs
    ):
        """Assert the original source boundary; other tests cover exact closure contents."""
        assert observed == boundary
        if require_boundary_state:
            assert state == source_state
        return SimpleNamespace(), closure

    def consume(_root, _plan, observed, request):
        """Publish a real host-owned receipt once and reject a different exact request on replay."""
        assert observed == boundary
        receipt_path = session / "material_closure/test_consumption.json"
        payload = {"request": request.model_dump(mode="json"), "is_user_approval": False}
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode()
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        if receipt_path.exists():
            assert receipt_path.read_bytes() == encoded
        else:
            receipt_path.write_bytes(encoded)
            consumptions.append(request.sha256)
        artifact = artifact_for_v2(
            root,
            receipt_path,
            artifact_id="test-consumption",
            kind="material-policy-authorization-consumption",
        )
        return SimpleNamespace(model_dump=lambda **_kwargs: payload), artifact

    monkeypatch.setattr(
        bridge, "validate_material_closure_promotion_boundary_v2", validate_boundary
    )
    monkeypatch.setattr(bridge, "_publish_material_authority_consumption", consume)
    monkeypatch.setattr(bridge, "_required_authoring_profile", lambda *_args: "material_authoring")

    class Desktop(DesktopInSessionController):
        """Observe that host authority exists before the actual executor calls the delegate."""

        def execute(self, **kwargs):
            """Record a single delegate call and preserve the ordinary desktop wait protocol."""
            assert (session / "material_closure/test_consumption.json").is_file()
            delegates.append("called")
            return super().execute(**kwargs)

    return SimpleNamespace(
        root=root,
        session=session,
        session_id=session_id,
        boundary=boundary,
        consumptions=consumptions,
        delegates=delegates,
        controller=Desktop(),
    )


def _run(fixture: SimpleNamespace, controller=None):
    """Call the unchanged public material boundary with the same session and exact assignment."""
    return bridge.execute_material_closure_controller_v2(
        fixture.root.name,
        fixture.session_id,
        boundary_artifact=fixture.boundary,
        controller=controller or fixture.controller,
    )


def _fill_desktop_outputs(fixture: SimpleNamespace, waiting: dict) -> None:
    """Author only the three declared isolated outputs for executor lifecycle testing."""
    request = waiting["request"]
    staging = (
        fixture.session
        / "controller_executions"
        / request["execution_id"]
        / "controller_workspace/outputs"
    )
    for relative in request["allowed_output_paths"]:
        tail = PurePosixPath(relative).relative_to(PurePosixPath(request["output_root"]))
        with open(native_io_path(staging.joinpath(*tail.parts)), "xb") as stream:
            stream.write(b"{}\n")


def test_material_authority_precedes_executor_inventory_and_desktop_resume(tmp_path, monkeypatch):
    """Handle native Windows paths and consume host authority once across desktop resume."""
    fixture = _material_lifecycle(tmp_path, monkeypatch)
    waiting = _run(fixture)
    assert waiting["result"]["status"] == "waiting_for_output"
    assert waiting["state"]["status"] == "waiting_for_controller"
    assert waiting["user_approval_consumed"] is False
    assert len(fixture.consumptions) == len(fixture.delegates) == 1
    _fill_desktop_outputs(fixture, waiting)
    result = _run(fixture)
    assert result["result"]["status"] == "completed"
    assert result["state"]["next_action"] == "validate_candidate"
    assert result["state"]["budget_usage"] == waiting["state"]["budget_usage"]
    assert len(fixture.consumptions) == len(fixture.delegates) == 1
    assert result["authority_consumption_artifact"] == waiting["authority_consumption_artifact"]
    root, _session, plan, _budget, state, _artifact = bridge._session_bundle(
        fixture.root.name, fixture.session_id
    )
    source = bridge._state_chain(root, fixture.session)[-3][0]
    _validate_material_controller_progression(root, plan, fixture.boundary, source, state)
    wrong_boundary = fixture.boundary.model_copy(update={"sha256": "f" * 64})
    with pytest.raises(MaterialPhaseError, match="mixes requests"):
        _validate_material_controller_progression(root, plan, wrong_boundary, source, state)
    with pytest.raises(MaterialPhaseError, match="predecessor"):
        _validate_material_controller_progression(
            root,
            plan,
            fixture.boundary,
            source,
            state.model_copy(update={"sequence": state.sequence + 1}),
        )
    with pytest.raises((AssertionError, PermissionError, ValueError)):
        _run(fixture)


def test_material_delegate_failure_returns_original_terminal_without_post_terminal_policy(
    tmp_path, monkeypatch
):
    """Retain the failed result and charged action without another authority check."""
    fixture = _material_lifecycle(tmp_path, monkeypatch)
    calls = []

    class FailingDesktop(DesktopInSessionController):
        """Fail inside the bounded delegate after valid host consumption."""

        def execute(self, **_kwargs):
            """Simulate one technical authoring failure without any candidate or canonical write."""
            calls.append("failed")
            raise ValueError("fixture delegate failure")

    result = _run(fixture, FailingDesktop())
    assert result["result"]["status"] == "failed"
    assert "controller exception: ValueError" in result["result"]["diagnostics"]
    assert result["state"]["status"] == "failed"
    assert result["state"]["budget_usage"]["controller_invocations"] == 1
    assert len(fixture.consumptions) == 1
    assert calls == ["failed"]
    assert result["result"]["canonical_unchanged"] is True


def test_material_host_consumption_survives_crash_before_executor_start(tmp_path, monkeypatch):
    """Replay the existing request and receipt after a crash without a second invocation."""
    fixture = _material_lifecycle(tmp_path, monkeypatch)
    actual = bridge.execute_controller_request

    def crash_before_start(**_kwargs):
        """Stop after host consumption and before executor lifecycle evidence."""
        assert len(fixture.consumptions) == 1
        raise RuntimeError("fixture crash before executor start")

    monkeypatch.setattr(bridge, "execute_controller_request", crash_before_start)
    with pytest.raises(RuntimeError, match="fixture crash"):
        _run(fixture)
    monkeypatch.setattr(bridge, "execute_controller_request", actual)
    result = _run(fixture)
    assert result["result"]["status"] == "waiting_for_output"
    assert len(fixture.consumptions) == len(fixture.delegates) == 1
    assert result["state"]["budget_usage"]["controller_invocations"] == 1


def test_material_controller_cannot_write_outside_workspace(tmp_path, monkeypatch):
    """Preserve the executor's strict inventory boundary after moving host receipt publication."""
    fixture = _material_lifecycle(tmp_path, monkeypatch)

    class EscapingDesktop(DesktopInSessionController):
        """Write an undeclared fixture file to verify the existing containment rejection."""

        def execute(self, **_kwargs):
            """Create an intentional test-only violation outside controller staging."""
            (fixture.root / "forbidden.txt").write_text("test-only violation", encoding="utf-8")
            return "adopt_existing"

    with pytest.raises(PermissionError, match="outside its workspace"):
        _run(fixture, EscapingDesktop())


def test_changed_material_assignment_fails_before_authority_or_invocation(tmp_path, monkeypatch):
    """Reject changed candidate authority without consuming policy or entering the delegate."""
    fixture = _material_lifecycle(tmp_path, monkeypatch)
    (fixture.root / fixture.boundary.path).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="(size|hash|changed)"):
        _run(fixture)
    assert fixture.consumptions == fixture.delegates == []


def test_unprepared_material_callback_has_no_authority(tmp_path, monkeypatch):
    """Require host preparation even when the private callback is invoked directly."""
    fixture = _material_lifecycle(tmp_path, monkeypatch)
    plan = bridge._session_bundle(fixture.root.name, fixture.session_id)[2]
    controller = bridge._ApprovalConsumingController(
        fixture.controller,
        root=fixture.root,
        plan=plan,
        boundary_artifact=fixture.boundary,
    )
    with pytest.raises(PermissionError, match="not prepared"):
        controller.execute(
            assignment=fixture.root / fixture.boundary.path,
            immutable_inputs=(),
            allowed_output_paths=(),
            tool_profile=None,
            timeout_seconds=1,
        )
    assert fixture.consumptions == fixture.delegates == []
