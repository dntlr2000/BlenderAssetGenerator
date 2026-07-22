from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from codex_blender_modeler.cli import app
from codex_blender_modeler.versioning import (
    DESTINATION_HANDOFF_SCHEMA_VERSION,
    PROJECT_VERSION,
    STABILIZATION_SCHEMA_VERSION,
    WORKFLOW_SCHEMA_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "stability-probe",
    "workspace-audit",
    "stability-report-pdf",
    "queue-enqueue",
    "queue-status",
    "queue-run",
    "queue-requeue",
    "queue-cancel",
    "handoff-plan",
    "handoff-generate",
    "handoff-validate",
    "handoff-status",
}
EXPECTED_MCP_TOOLS = {
    "probe_release_environment",
    "audit_workspace_state",
    "generate_stability_pdf_report",
    "enqueue_local_workflow",
    "get_local_workflow_queue",
    "run_local_workflow_queue",
    "requeue_local_workflow",
    "cancel_local_workflow_queue_entry",
    "plan_destination_handoff",
    "generate_destination_handoff",
    "validate_destination_handoff",
    "get_destination_handoff_status",
}


def test_v09_cli_commands_are_registered() -> None:
    """Keep the stabilization and bounded-queue CLI surface discoverable."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.stdout


def test_v09_failed_requeue_requires_an_explicit_flag() -> None:
    """Expose queue retry as an explicit decision instead of an automatic loop."""

    result = CliRunner().invoke(app, ["queue-requeue", "--help"])
    assert result.exit_code == 0
    assert "--retry-failed" in result.stdout


def test_v09_mcp_tools_are_explicitly_whitelisted() -> None:
    """Keep every stabilization operation inside the project MCP allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled


def test_v09_advances_project_only_and_preserves_workflow_contract() -> None:
    """Advance project stabilization without rewriting the V0.8 workflow contract."""

    assert PROJECT_VERSION == "0.9.0"
    assert STABILIZATION_SCHEMA_VERSION == "0.9.0"
    assert DESTINATION_HANDOFF_SCHEMA_VERSION == "0.9.0"
    assert WORKFLOW_SCHEMA_VERSION == "0.8.0"
