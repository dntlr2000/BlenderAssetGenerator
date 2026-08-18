"""Public CLI, MCP, allowlist, and authority parity for identity split 0.1.0."""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

from cli_help_support import assert_cli_help_contract
from typer.testing import CliRunner

from codex_blender_modeler import cli, material_identity_split_public, mcp_server

ROOT = Path(__file__).resolve().parents[1]
CLI_COMMANDS = {
    "material-identity-split-plan",
    "material-identity-split-status",
    "material-identity-split-preapproval",
    "material-identity-split-approval-request",
    "material-identity-split-approve",
    "material-identity-split-apply",
    "material-identity-split-recover",
}
MCP_TOOLS = {
    "plan_material_identity_split",
    "get_material_identity_split_status",
    "run_material_identity_split_preapproval",
    "get_material_identity_split_approval_request",
    "approve_material_identity_split",
    "apply_material_identity_split",
    "recover_material_identity_split",
}


def test_material_identity_split_cli_and_mcp_surfaces_are_complete() -> None:
    """Expose the seven requested commands as distinct additive host adapters."""

    result = CliRunner().invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(result.stdout, required=CLI_COMMANDS)
    for tool in MCP_TOOLS:
        assert callable(getattr(mcp_server, tool))


def test_material_identity_split_mcp_tools_are_project_enabled() -> None:
    """Keep all seven tools within the explicit project MCP allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        enabled = set(
            tomllib.load(handle)["mcp_servers"]["blender_modeler"]["enabled_tools"]
        )
    assert MCP_TOOLS <= enabled


def test_identity_split_capability_preserves_the_specialized_boundary() -> None:
    """Advertise preapproval without implying approval, material promotion, or migration."""

    capabilities = mcp_server.get_modeling_capabilities()
    assert capabilities["material_identity_split_schema_version"] == "0.1.0"
    companion = capabilities["material_identity_split"]
    assert companion["preapproval_stop_boundary"] == (
        "framework_ready_for_explicit_scope_approval"
    )
    assert companion["canonical_writer"] == "host_owned_paired_transaction_only"
    assert companion["material_plan_promotion"] is False
    assert companion["automatic_migration"] is False
    assert companion["destination_writes"] is False


def test_approval_surface_requires_caller_payload_and_user_decision_bytes() -> None:
    """Prevent a boolean flag or generic approval from synthesizing specialized authority."""

    cli_parameters = inspect.signature(cli.material_identity_split_approve_command).parameters
    mcp_parameters = inspect.signature(mcp_server.approve_material_identity_split).parameters
    required = {
        "job_id",
        "approval_request_path",
        "approval_path",
        "user_decision_path",
    }
    assert required <= set(cli_parameters)
    assert required | {"explicit_user_decision_observed"} <= set(mcp_parameters)
    assert cli_parameters["confirm_explicit_user_decision"].default is False
    assert mcp_parameters["explicit_user_decision_observed"].default is inspect.Parameter.empty


def test_apply_surface_requires_a_caller_authored_intent() -> None:
    """Keep ApplyIntent construction outside every CLI and MCP forwarding surface."""

    for function in (
        cli.material_identity_split_apply_command,
        mcp_server.apply_material_identity_split,
        material_identity_split_public.apply_material_identity_split_public,
    ):
        parameters = inspect.signature(function).parameters
        assert "apply_intent_path" in parameters
        assert "approval_path" not in parameters
        assert "candidate_scene_spec_path" not in parameters


def test_preapproval_and_request_surfaces_do_not_accept_approval_payloads() -> None:
    """Keep framework eligibility and ApprovalRequest read-only from user authority."""

    for function in (
        mcp_server.run_material_identity_split_preapproval,
        mcp_server.get_material_identity_split_approval_request,
    ):
        parameters = inspect.signature(function).parameters
        assert "approval_path" not in parameters
        assert "explicit_user_decision_observed" not in parameters
