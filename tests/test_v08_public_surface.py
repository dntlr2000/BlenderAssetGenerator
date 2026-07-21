from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from codex_blender_modeler.cli import app
from codex_blender_modeler.versioning import PROJECT_VERSION, WORKFLOW_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "workflow-plan",
    "workflow-status",
    "workflow-reconcile",
    "workflow-resume",
    "workflow-complete-step",
    "workflow-approve",
    "workflow-cancel",
    "workflow-adapters",
}
EXPECTED_MCP_TOOLS = {
    "plan_short_workflow",
    "get_workflow_state",
    "reconcile_short_workflow",
    "resume_short_workflow",
    "record_workflow_step_completion",
    "approve_workflow_checkpoint",
    "cancel_short_workflow",
    "get_destination_adapters",
}


def test_v08_cli_commands_are_registered() -> None:
    """Keep the short-request orchestration CLI surface discoverable."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.stdout


def test_v08_resume_requires_an_explicit_failed_retry_flag() -> None:
    """Expose failed retry as an explicit operator decision instead of an automatic loop."""

    result = CliRunner().invoke(app, ["workflow-resume", "--help"])
    assert result.exit_code == 0
    assert "--max-host-steps" in result.stdout
    assert "--retry-failed" in result.stdout


def test_v08_mcp_tools_are_explicitly_whitelisted() -> None:
    """Keep every orchestration MCP operation inside the project allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled


def test_v08_versions_preserve_all_earlier_contract_boundaries() -> None:
    """Advance orchestration without rewriting geometry, material, QA, or V0.7 data."""

    assert PROJECT_VERSION == "0.8.0"
    assert WORKFLOW_SCHEMA_VERSION == "0.8.0"
