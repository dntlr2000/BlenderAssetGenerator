"""Public CLI, MCP, capability, and allowlist parity for AQ approval envelope 0.3."""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.autonomy_v2 import approval_policy_capability
from codex_blender_modeler.cli import app

ROOT = Path(__file__).resolve().parents[1]

CLI_COMMANDS = {
    "aq-approval-envelope-plan",
    "aq-approval-envelope-status",
    "aq-policy-eligibility",
    "aq-policy-authorize",
    "aq-escalation-status",
    "aq-approval-telemetry",
    "autonomy-v2-one-prompt-plan",
    "autonomy-v2-one-prompt-run",
    "autonomy-v2-one-prompt-resume",
    "autonomy-v2-one-prompt-status",
    "autonomy-v2-one-prompt-cancel",
}

MCP_TOOLS = {
    "plan_aq_approval_envelope",
    "get_aq_approval_envelope_status",
    "evaluate_aq_policy_eligibility",
    "authorize_aq_policy_gate",
    "get_aq_escalation_status",
    "get_aq_approval_telemetry",
    "plan_autonomy_v2_one_prompt",
    "run_autonomy_v2_one_prompt",
    "resume_autonomy_v2_one_prompt",
    "get_autonomy_v2_one_prompt_status",
    "cancel_autonomy_v2_one_prompt",
}

ROUTINE_GATES = {
    "geometry_candidate_promotion",
    "structural_candidate_promotion",
    "bounded_parametric_revision",
    "bounded_material_identity_split",
    "material_candidate_promotion",
    "material_quality_acknowledgement",
    "iq_quality_acceptance",
    "optimization_plan_authorization",
    "package_acknowledgement",
    "review_bundle_terminal",
    "technical_retry",
    "rollback",
    "imagegen_candidate_adoption",
}


def test_approval_policy_capability_is_disabled_and_non_user() -> None:
    """Expose all gates while denying user-equivalence, task spawn, and destination writes."""

    capability = approval_policy_capability()
    assert capability["schema_version"] == "0.3.0"
    assert capability["status"] == "disabled_experimental"
    assert set(capability["approval_modes"]) == {
        "autonomous",
        "checkpointed",
        "interactive",
    }
    assert set(capability["routine_gate_kinds"]) == ROUTINE_GATES
    assert capability["technical_user_approval_allowed"] is False
    assert capability["policy_is_user_approval"] is False
    assert capability["repository_creates_codex_task"] is False
    assert capability["app_close_background_execution"] is False
    assert capability["destination_project_write"] is False


def test_approval_envelope_cli_help_is_complete() -> None:
    """Keep every documented approval-envelope and one-prompt command discoverable."""

    runner = CliRunner()
    root_help = runner.invoke(app, ["--help"])
    assert root_help.exit_code == 0
    for command in CLI_COMMANDS:
        assert command in root_help.stdout
        command_help = runner.invoke(app, [command, "--help"])
        assert command_help.exit_code == 0, command_help.stdout


def test_approval_envelope_mcp_tools_are_callable_and_allowlisted() -> None:
    """Synchronize the additive MCP host functions with the repository allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])

    assert MCP_TOOLS <= enabled
    for tool_name in MCP_TOOLS:
        assert callable(getattr(mcp_server, tool_name))


def test_mutating_experimental_mcp_surfaces_require_explicit_opt_in() -> None:
    """Keep planning, authorization, running, resume, and cancel disabled by default."""

    mutating_tools = {
        "plan_aq_approval_envelope",
        "evaluate_aq_policy_eligibility",
        "authorize_aq_policy_gate",
        "plan_autonomy_v2_one_prompt",
        "run_autonomy_v2_one_prompt",
        "resume_autonomy_v2_one_prompt",
        "cancel_autonomy_v2_one_prompt",
    }
    for tool_name in mutating_tools:
        parameters = inspect.signature(getattr(mcp_server, tool_name)).parameters
        assert parameters["experimental_opt_in"].default is False
