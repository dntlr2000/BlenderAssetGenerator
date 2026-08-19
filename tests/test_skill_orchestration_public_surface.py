"""Public CLI, MCP, allowlist, schema, and capability parity for Skill Orchestration."""

from __future__ import annotations

import inspect
import json
import runpy
import tomllib
from pathlib import Path

from cli_help_support import assert_cli_help_contract
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.cli import app
from codex_blender_modeler.skill_orchestration.models import (
    AQSkillAdapterPlan,
    AQSkillAdapterState,
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
    "aq_skill_adapter_plan.schema.json": AQSkillAdapterPlan,
    "aq_skill_adapter_state.schema.json": AQSkillAdapterState,
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
        "cancel_aq_one_prompt_skill",
    }:
        parameters = inspect.signature(getattr(mcp_server, tool_name)).parameters
        assert parameters["experimental_opt_in"].default is False


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
    assert PROJECT_VERSION == "0.9.0"
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
