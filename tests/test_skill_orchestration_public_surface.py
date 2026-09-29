"""Public CLI, MCP, allowlist, schema, and capability parity for Skill Orchestration."""

from __future__ import annotations

import inspect
import json
import runpy
import tomllib
from pathlib import Path

import typer
from cli_help_support import assert_cli_help_contract
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.cli import app
from codex_blender_modeler.skill_orchestration.models import (
    AQSkillAdapterPlan,
    AQSkillAdapterState,
    AQSkillAdapterTerminal,
    GuardedRevisionContinuation,
    MaterialImpactReport,
    SkillBundleManifest,
    SkillExecutionReceipt,
    SkillRegistry,
    SkillRouteDecision,
    StandardCompositeRunPlan,
    StandardCompositeRunState,
    StandardCompositeRunTerminal,
    StandardCompositeStageBinding,
    StandardQualityDispositionRecord,
    StandardQualityDispositionRequest,
)
from codex_blender_modeler.versioning import (
    PROJECT_VERSION,
    SKILL_ORCHESTRATION_SCHEMA_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
CLI_COMMANDS = {
    "skill-catalog",
    "skill-trace",
    "standard-asset-cycle-plan",
    "standard-asset-cycle-run",
    "standard-asset-cycle-resume",
    "standard-asset-cycle-status",
    "standard-asset-cycle-cancel",
    "aq-one-prompt-skill-plan",
    "aq-one-prompt-skill-run",
    "aq-one-prompt-skill-resume",
    "aq-one-prompt-skill-status",
    "aq-one-prompt-skill-reconcile-terminal",
    "aq-one-prompt-skill-cancel",
}
MCP_TOOLS = {
    "get_skill_catalog",
    "get_skill_execution_trace",
    "plan_standard_asset_cycle",
    "run_standard_asset_cycle",
    "resume_standard_asset_cycle",
    "get_standard_asset_cycle_status",
    "cancel_standard_asset_cycle",
    "plan_aq_one_prompt_skill",
    "run_aq_one_prompt_skill",
    "resume_aq_one_prompt_skill",
    "get_aq_one_prompt_skill_status",
    "reconcile_aq_one_prompt_skill_terminal",
    "cancel_aq_one_prompt_skill",
}
SCHEMA_MODELS = {
    "skill_registry.schema.json": SkillRegistry,
    "skill_bundle_manifest.schema.json": SkillBundleManifest,
    "skill_route_decision.schema.json": SkillRouteDecision,
    "skill_execution_receipt.schema.json": SkillExecutionReceipt,
    "material_impact_report.schema.json": MaterialImpactReport,
    "guarded_revision_continuation.schema.json": GuardedRevisionContinuation,
    "standard_composite_run_plan.schema.json": StandardCompositeRunPlan,
    "standard_composite_stage_binding.schema.json": StandardCompositeStageBinding,
    "standard_composite_run_state.schema.json": StandardCompositeRunState,
    "standard_composite_run_terminal.schema.json": StandardCompositeRunTerminal,
    "standard_quality_disposition_request.schema.json": StandardQualityDispositionRequest,
    "standard_quality_disposition_record.schema.json": StandardQualityDispositionRecord,
    "aq_skill_adapter_plan.schema.json": AQSkillAdapterPlan,
    "aq_skill_adapter_state.schema.json": AQSkillAdapterState,
    "aq_skill_adapter_terminal.schema.json": AQSkillAdapterTerminal,
}


def test_skill_cli_commands_are_discoverable() -> None:
    """Expose both entrypoint lifecycles plus catalog and trace through one CLI."""

    runner = CliRunner()
    root_help = runner.invoke(app, ["--help"])
    assert root_help.exit_code == 0
    assert_cli_help_contract(root_help.stdout, required=CLI_COMMANDS)
    for command in CLI_COMMANDS:
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.stdout


def test_skill_mcp_tools_are_callable_and_project_allowlisted() -> None:
    """Keep every documented host adapter callable through the trusted MCP profile."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert MCP_TOOLS <= enabled
    for tool_name in MCP_TOOLS:
        assert callable(getattr(mcp_server, tool_name))


def test_standard_resume_exposes_exact_guarded_technical_recovery() -> None:
    """Expose failed-state recovery without adding a new unsnapshotted entry tool."""

    runner = CliRunner()
    help_result = runner.invoke(
        app,
        ["standard-asset-cycle-resume", "--help"],
        terminal_width=240,
    )
    assert help_result.exit_code == 0
    command = typer.main.get_command(app).commands["standard-asset-cycle-resume"]
    option_names = {
        option
        for parameter in command.params
        for option in getattr(parameter, "opts", ())
    }
    assert "--recover-failed-to-guarded-geometry" in option_names
    assert "--failed-state-sha256" in option_names
    assert "--recovery-reason" in option_names
    assert "--reroute-candidate-to-manual-guarded" in option_names
    assert "--candidate-state-sha256" in option_names
    assert "--reroute-reason" in option_names
    assert "--quality-disposition" in option_names
    assert "--quality-disposition-fingerprint" in option_names
    assert "--quality-disposition-note" in option_names
    parameters = inspect.signature(mcp_server.resume_standard_asset_cycle).parameters
    assert parameters["recover_failed_to_guarded_geometry"].default is False
    assert parameters["failed_state_sha256"].default is None
    assert parameters["recovery_reason"].default is None
    assert parameters["reroute_candidate_to_manual_guarded"].default is False
    assert parameters["candidate_state_sha256"].default is None
    assert parameters["reroute_reason"].default is None
    assert parameters["quality_disposition"].default is None
    assert parameters["quality_disposition_fingerprint"].default is None
    assert parameters["quality_disposition_note"].default is None


def test_registry_tool_allowlists_reference_real_enabled_mcp_tools() -> None:
    """Reject a skill instruction bundle that names missing or project-disabled tools."""

    registry = SkillRegistry.model_validate_json(
        (ROOT / ".agents" / "skills" / "registry.json").read_text(encoding="utf-8")
    )
    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    declared = {tool for skill in registry.skills for tool in skill.allowed_tools}
    assert declared <= enabled
    for tool_name in declared:
        assert callable(getattr(mcp_server, tool_name))


def test_aq_skill_mutations_require_explicit_experimental_opt_in() -> None:
    """Keep every mutating AQ adapter surface false-by-default."""

    for tool_name in {
        "plan_aq_one_prompt_skill",
        "run_aq_one_prompt_skill",
        "resume_aq_one_prompt_skill",
        "reconcile_aq_one_prompt_skill_terminal",
        "cancel_aq_one_prompt_skill",
    }:
        parameters = inspect.signature(getattr(mcp_server, tool_name)).parameters
        assert parameters["experimental_opt_in"].default is False


def test_aq_skill_resume_exposes_exact_post_iq_human_disposition() -> None:
    """Expose human review terminalization only on the existing AQ resume surface."""

    command = typer.main.get_command(app).commands["aq-one-prompt-skill-resume"]
    option_names = {
        option
        for parameter in command.params
        for option in getattr(parameter, "opts", ())
    }
    assert "--human-quality-disposition" in option_names
    parameters = inspect.signature(mcp_server.resume_aq_one_prompt_skill).parameters
    assert parameters["human_quality_disposition_path"].default is None
    run_parameters = inspect.signature(mcp_server.run_aq_one_prompt_skill).parameters
    assert "human_quality_disposition_path" not in run_parameters


def test_skill_schemas_match_strict_models_and_generator_registry() -> None:
    """Keep every checked-in Draft 2020-12 schema equal to its Pydantic model."""

    registered = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))[
        "SCHEMAS"
    ]
    for filename, model in SCHEMA_MODELS.items():
        checked_in = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(checked_in)
        assert checked_in == model.model_json_schema()
        assert registered[filename] is model


def test_skill_capability_is_additive_and_non_authoritative() -> None:
    """Preserve project 0.9 while publishing traceability and disabled AQ semantics."""

    capability = mcp_server.get_modeling_capabilities()["skill_orchestration"]
    assert PROJECT_VERSION == "0.9.1"
    assert SKILL_ORCHESTRATION_SCHEMA_VERSION == "0.1.0"
    assert capability["contract_version"] == "0.1.0"
    assert capability["entry_skills"] == [
        "standard-asset-cycle",
        "aq-one-prompt-orchestrator",
    ]
    assert capability["aq_profile_status"] == "disabled_experimental"
    assert capability["current_route_projection"] is True
    assert capability["v09_audit_and_archive_boundary"] is True
    assert capability["canonical_write_authority"] is False
    assert capability["approval_authority"] is False
