from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

from cli_help_support import assert_cli_help_contract
from typer.main import get_command
from typer.testing import CliRunner

from codex_blender_modeler.cli import app
from codex_blender_modeler.mcp_server import (
    get_modeling_capabilities,
    plan_short_workflow,
)
from codex_blender_modeler.versioning import PROJECT_VERSION, WORKFLOW_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "candidate-review-approve",
    "candidate-review-status",
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
    "approve_candidate_review_promotion",
    "get_candidate_review_state",
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
    assert_cli_help_contract(result.stdout, required=EXPECTED_COMMANDS)


def test_v08_resume_requires_an_explicit_failed_retry_flag() -> None:
    """Expose failed retry as an explicit operator decision instead of an automatic loop."""

    result = CliRunner().invoke(app, ["workflow-resume", "--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(
        result.stdout,
        required=("--max-host-steps", "--retry-failed"),
    )


def test_v08_background_policy_is_available_without_powershell() -> None:
    """Expose explicit fast-lane choices through both CLI help and the MCP planner."""

    result = CliRunner().invoke(app, ["workflow-plan", "--help"])
    assert result.exit_code == 0
    workflow_command = get_command(app).commands["workflow-plan"]
    option_names = {
        option
        for parameter in workflow_command.params
        for option in getattr(parameter, "opts", [])
    }
    assert "--execution-policy" in option_names
    assert "--delivery-scope" in option_names
    assert "--revision-strategy" in option_names
    parameters = inspect.signature(plan_short_workflow).parameters
    assert parameters["execution_policy"].default == "standard"
    assert parameters["delivery_scope"].default is None
    assert parameters["revision_strategy"].default == "candidate_review"

    capabilities = get_modeling_capabilities()
    orchestration = capabilities["workflow_orchestration"]
    assert orchestration["execution_policies"] == [
        "standard",
        "background_exterior",
    ]
    assert orchestration["delivery_scopes"] == [
        "preview_only",
        "portable_package",
    ]
    assert orchestration["default_standard_revision_strategy"] == "candidate_review"
    assert orchestration["background_exterior"]["direct_qa_runs"] == 1
    assert orchestration["background_exterior"]["automatic_revision"] is False
    assert (
        orchestration["background_exterior"]["automatic_revision_iterations"]
        == 0
    )
    assert "exact preview plan" in (
        orchestration["background_exterior"]["package_continuation_binding"]
    )
    assert "requires_standard_workflow" in (
        orchestration["background_exterior"]["disqualification_outcome"]
    )


def test_v08_mcp_tools_are_explicitly_whitelisted() -> None:
    """Keep every orchestration MCP operation inside the project allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled


def test_v08_versions_preserve_all_earlier_contract_boundaries() -> None:
    """Advance orchestration without rewriting geometry, material, QA, or V0.7 data."""

    assert PROJECT_VERSION == "0.9.0"
    assert WORKFLOW_SCHEMA_VERSION == "0.8.0"
