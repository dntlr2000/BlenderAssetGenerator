from __future__ import annotations

import inspect
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from codex_blender_modeler import autonomy_v2, mcp_server
from codex_blender_modeler import cli as cli_module
from codex_blender_modeler.autonomy import service as legacy_service
from codex_blender_modeler.autonomy_v2 import supervisor_service
from codex_blender_modeler.cli import app

ROOT = Path(__file__).resolve().parents[1]
V2_COMMANDS = {"autonomy-v2-advance", "autonomy-v2-run"}
V2_MCP_TOOLS = {"advance_autonomous_quality_v2", "run_autonomous_quality_v2"}
LEGACY_STATUS_KEYS = {
    "session_id",
    "profile_id",
    "root_authorization_status",
    "state",
    "receipt_chain_head_sha256",
    "remaining_budget",
    "candidate_assignment",
    "production",
    "terminal",
    "recovery_warnings",
}


def _parameter_names(callable_object: object) -> list[str]:
    """Return one callable's public parameter names in declaration order."""

    return list(inspect.signature(callable_object).parameters)


def _status(state_status: str, next_action: str, sequence: int) -> dict[str, Any]:
    """Build the smallest public AQ v2 status projection needed by loop tests."""

    return {
        "profile_status": "disabled_experimental",
        "job_id": "aq_v2_public",
        "workflow_id": "wf-aq-v2-public",
        "dispatch_id": "dispatch-aq-v2-public",
        "session_id": "aq-v2-public",
        "state": {
            "status": state_status,
            "next_action": next_action,
            "sequence": sequence,
        },
    }


def test_v2_supervisor_surface_is_additive_disabled_and_allowlisted() -> None:
    """Expose bounded AQ v2 controls without activating the experimental profile."""

    root_help = CliRunner().invoke(app, ["--help"])
    assert root_help.exit_code == 0
    assert all(command in root_help.stdout for command in V2_COMMANDS)

    advance_help = CliRunner().invoke(app, ["autonomy-v2-advance", "--help"])
    run_help = CliRunner().invoke(app, ["autonomy-v2-run", "--help"])
    assert advance_help.exit_code == 0
    assert run_help.exit_code == 0
    for result in (advance_help, run_help):
        assert "--quality-submission" in result.stdout
        assert "--enable-v2" in result.stdout
        assert "--retry-failed" not in result.stdout
    assert "--max-actions" not in advance_help.stdout
    assert "--max-actions" in run_help.stdout

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert V2_MCP_TOOLS <= enabled

    assert _parameter_names(autonomy_v2.advance_autonomy_v2) == [
        "job_id",
        "session_id",
        "quality_submission",
        "allow_disabled_experimental",
    ]
    assert _parameter_names(autonomy_v2.run_autonomy_v2) == [
        "job_id",
        "session_id",
        "max_actions",
        "quality_submission",
        "allow_disabled_experimental",
    ]
    assert inspect.signature(autonomy_v2.run_autonomy_v2).parameters[
        "max_actions"
    ].default == 8
    assert inspect.signature(autonomy_v2.advance_autonomy_v2).parameters[
        "allow_disabled_experimental"
    ].default is False

    assert _parameter_names(mcp_server.advance_autonomous_quality_v2) == [
        "job_id",
        "session_id",
        "quality_submission",
        "experimental_opt_in",
    ]
    assert _parameter_names(mcp_server.run_autonomous_quality_v2) == [
        "job_id",
        "session_id",
        "max_actions",
        "quality_submission",
        "experimental_opt_in",
    ]
    assert inspect.signature(mcp_server.run_autonomous_quality_v2).parameters[
        "max_actions"
    ].default == 8
    assert inspect.signature(mcp_server.advance_autonomous_quality_v2).parameters[
        "experimental_opt_in"
    ].default is False

    status = autonomy_v2.autonomy_v2_profile_status()
    assert status["profile_id"] == "autonomous_static_prop_v2"
    assert status["status"] == "disabled_experimental"
    assert status["verified_active"] is False


def test_v1_supervisor_signatures_and_response_projection_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the established AQ v1 callable, CLI, and MCP contracts byte-shape neutral."""

    assert _parameter_names(legacy_service.advance_autonomy) == [
        "job_id",
        "session_id",
    ]
    assert _parameter_names(legacy_service.run_autonomy) == [
        "job_id",
        "session_id",
        "max_actions",
    ]
    assert inspect.signature(legacy_service.run_autonomy).parameters[
        "max_actions"
    ].default == 8
    assert _parameter_names(mcp_server.advance_autonomous_quality) == [
        "job_id",
        "session_id",
    ]
    assert _parameter_names(mcp_server.run_autonomous_quality) == [
        "job_id",
        "session_id",
        "max_actions",
    ]
    assert inspect.signature(mcp_server.run_autonomous_quality).parameters[
        "max_actions"
    ].default == 8

    for command in ("autonomy-advance", "autonomy-run"):
        help_result = CliRunner().invoke(app, [command, "--help"])
        assert help_result.exit_code == 0
        assert "--quality-submission" not in help_result.stdout
        assert "--enable-v2" not in help_result.stdout

    advance_response = {key: None for key in LEGACY_STATUS_KEYS}
    run_response = {
        **advance_response,
        "actions_executed": 2,
        "action_limit": 8,
    }

    def fake_advance(job_id: str, session_id: str) -> dict[str, Any]:
        """Return the exact established v1 status projection for wrapper checks."""

        assert (job_id, session_id) == ("legacy-job", "legacy-session")
        return advance_response

    def fake_run(
        job_id: str,
        session_id: str,
        *,
        max_actions: int = 8,
    ) -> dict[str, Any]:
        """Return the exact established bounded-run projection for wrapper checks."""

        assert (job_id, session_id, max_actions) == (
            "legacy-job",
            "legacy-session",
            8,
        )
        return run_response

    monkeypatch.setattr(legacy_service, "advance_autonomy", fake_advance)
    monkeypatch.setattr(legacy_service, "run_autonomy", fake_run)

    assert mcp_server.advance_autonomous_quality(
        "legacy-job", "legacy-session"
    ) == advance_response
    assert mcp_server.run_autonomous_quality(
        "legacy-job", "legacy-session"
    ) == run_response

    cli_advance = CliRunner().invoke(
        app,
        ["autonomy-advance", "legacy-job", "legacy-session"],
    )
    cli_run = CliRunner().invoke(
        app,
        ["autonomy-run", "legacy-job", "legacy-session"],
    )
    assert cli_advance.exit_code == 0
    assert cli_run.exit_code == 0
    assert json.loads(cli_advance.stdout) == advance_response
    assert json.loads(cli_run.stdout) == run_response


def test_v2_cli_forwards_one_strict_quality_submission_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parse a JSON object once and preserve bounded opt-in arguments at the CLI edge."""

    submission = {"schema_version": "0.2.0", "submission_id": "quality-cli"}
    submission_path = tmp_path / "quality-submission.json"
    submission_path.write_text(json.dumps(submission), encoding="utf-8")
    calls: list[tuple[str, str, int | None, dict[str, object] | None, bool]] = []

    def fake_advance(
        job_id: str,
        session_id: str,
        *,
        quality_submission: dict[str, object] | None = None,
        allow_disabled_experimental: bool = False,
    ) -> dict[str, object]:
        """Capture one CLI single-action request after its JSON boundary."""

        calls.append(
            (
                job_id,
                session_id,
                None,
                quality_submission,
                allow_disabled_experimental,
            )
        )
        return {"kind": "advance", "advanced": False}

    def fake_run(
        job_id: str,
        session_id: str,
        *,
        max_actions: int = 8,
        quality_submission: dict[str, object] | None = None,
        allow_disabled_experimental: bool = False,
    ) -> dict[str, object]:
        """Capture one CLI bounded request after its JSON boundary."""

        calls.append(
            (
                job_id,
                session_id,
                max_actions,
                quality_submission,
                allow_disabled_experimental,
            )
        )
        return {"kind": "run", "actions_executed": 0, "max_actions": max_actions}

    monkeypatch.setattr(cli_module, "advance_autonomy_v2", fake_advance)
    monkeypatch.setattr(cli_module, "run_autonomy_v2", fake_run)
    advance = CliRunner().invoke(
        app,
        [
            "autonomy-v2-advance",
            "aq-v2-job",
            "aq-v2-session",
            "--quality-submission",
            str(submission_path),
            "--enable-v2",
        ],
    )
    run = CliRunner().invoke(
        app,
        [
            "autonomy-v2-run",
            "aq-v2-job",
            "aq-v2-session",
            "--max-actions",
            "3",
            "--quality-submission",
            str(submission_path),
            "--enable-v2",
        ],
    )
    assert advance.exit_code == 0
    assert run.exit_code == 0
    assert json.loads(advance.stdout) == {"kind": "advance", "advanced": False}
    assert json.loads(run.stdout) == {
        "kind": "run",
        "actions_executed": 0,
        "max_actions": 3,
    }
    assert calls == [
        ("aq-v2-job", "aq-v2-session", None, submission, True),
        ("aq-v2-job", "aq-v2-session", 3, submission, True),
    ]

    non_object_path = tmp_path / "quality-submission-array.json"
    non_object_path.write_text("[]", encoding="utf-8")
    rejected = CliRunner().invoke(
        app,
        [
            "autonomy-v2-advance",
            "aq-v2-job",
            "aq-v2-session",
            "--quality-submission",
            str(non_object_path),
            "--enable-v2",
        ],
    )
    assert rejected.exit_code != 0
    assert len(calls) == 2


def test_v2_mcp_supervisor_forwards_only_explicit_bounded_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward quality evidence and opt-in without synthesizing retries or approval."""

    submission = {"schema_version": "0.2.0", "submission_id": "quality-public"}
    calls: list[tuple[str, str, int | None, dict[str, object] | None, bool]] = []

    def fake_advance(
        job_id: str,
        session_id: str,
        *,
        quality_submission: dict[str, object] | None = None,
        allow_disabled_experimental: bool = False,
    ) -> dict[str, object]:
        """Capture one MCP single-action invocation without touching a workspace."""

        calls.append(
            (
                job_id,
                session_id,
                None,
                quality_submission,
                allow_disabled_experimental,
            )
        )
        return {"kind": "advance", "actions_executed": 1}

    def fake_run(
        job_id: str,
        session_id: str,
        *,
        max_actions: int = 8,
        quality_submission: dict[str, object] | None = None,
        allow_disabled_experimental: bool = False,
    ) -> dict[str, object]:
        """Capture one MCP bounded-run invocation without touching a workspace."""

        calls.append(
            (
                job_id,
                session_id,
                max_actions,
                quality_submission,
                allow_disabled_experimental,
            )
        )
        return {"kind": "run", "actions_executed": 3, "action_limit": max_actions}

    monkeypatch.setattr(mcp_server, "advance_autonomy_v2_internal", fake_advance)
    monkeypatch.setattr(mcp_server, "run_autonomy_v2_internal", fake_run)

    advanced = mcp_server.advance_autonomous_quality_v2(
        "aq-v2-job",
        "aq-v2-session",
        quality_submission=submission,
        experimental_opt_in=True,
    )
    ran = mcp_server.run_autonomous_quality_v2(
        "aq-v2-job",
        "aq-v2-session",
        max_actions=3,
        quality_submission=submission,
        experimental_opt_in=True,
    )
    assert advanced == {"kind": "advance", "actions_executed": 1}
    assert ran == {"kind": "run", "actions_executed": 3, "action_limit": 3}
    assert calls == [
        ("aq-v2-job", "aq-v2-session", None, submission, True),
        ("aq-v2-job", "aq-v2-session", 3, submission, True),
    ]


def test_v2_bounded_run_stops_at_controller_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop a bounded supervisor immediately when one action requests a controller."""

    waiting = _status("waiting_for_controller", "execute_controller", 2)
    calls: list[tuple[str, str, object, bool]] = []

    class StateProjection:
        """Provide the final immutable state's public serialization boundary."""

        def model_dump(self, *, mode: str) -> dict[str, Any]:
            """Return one JSON-compatible final state projection."""

            assert mode == "json"
            return waiting["state"]

    def fake_bundle(job_id: str, session_id: str) -> tuple[object, ...]:
        """Return only the exact plan and budget caps consumed by the runner."""

        assert (job_id, session_id) == ("aq_v2_public", "aq-v2-public")
        return (
            Path("job-root"),
            Path("session-root"),
            SimpleNamespace(action_limit=8),
            SimpleNamespace(global_action_limit=8),
            StateProjection(),
            object(),
        )

    def fake_opt_in(
        root: object,
        plan: object,
        *,
        allow_disabled_experimental: bool,
    ) -> object:
        """Confirm the public run preserves the explicit experimental opt-in."""

        assert root == Path("job-root")
        assert isinstance(plan, SimpleNamespace)
        assert plan.action_limit == 8
        assert allow_disabled_experimental is True
        return object()

    def fake_advance(
        job_id: str,
        session_id: str,
        *,
        quality_submission: object = None,
        allow_disabled_experimental: bool = False,
    ) -> dict[str, Any]:
        """Return one non-advancing controller-wait boundary."""

        calls.append(
            (job_id, session_id, quality_submission, allow_disabled_experimental)
        )
        return {
            "advanced": False,
            "outcome": "waiting_for_controller",
            "state": waiting["state"],
        }

    monkeypatch.setattr(supervisor_service, "_session_bundle", fake_bundle)
    monkeypatch.setattr(
        supervisor_service,
        "_require_execution_opt_in",
        fake_opt_in,
    )
    monkeypatch.setattr(supervisor_service, "advance_autonomy_v2", fake_advance)
    result = supervisor_service.run_autonomy_v2(
        "aq_v2_public",
        "aq-v2-public",
        max_actions=8,
        allow_disabled_experimental=True,
    )

    assert result["state"]["status"] == "waiting_for_controller"
    assert result["actions_executed"] == 1
    assert result["authorized_actions"] == 8
    assert result["max_actions"] == 8
    assert result["stop_reason"] == "waiting_for_controller"
    assert len(calls) == 1
    assert all(call[-1] is True for call in calls)
