from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from codex_blender_modeler.cli import app
from codex_blender_modeler.versioning import PORTABLE_ASSET_SCHEMA_VERSION, PROJECT_VERSION

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "asset-profile-init",
    "asset-preflight",
    "asset-plan",
    "asset-plan-approve",
    "asset-optimize",
    "asset-material-convert",
    "asset-package",
    "asset-validate",
    "asset-status",
}
EXPECTED_MCP_TOOLS = {
    "initialize_asset_profile",
    "run_asset_preflight",
    "plan_portable_asset_optimization",
    "approve_portable_asset_optimization",
    "optimize_portable_asset",
    "convert_portable_materials",
    "build_portable_package",
    "validate_portable_package",
    "get_portable_asset_status",
}


def test_v07_cli_commands_are_registered() -> None:
    """Keep the documented portable-asset CLI surface discoverable."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.stdout


def test_v07_cli_exposes_explicit_profile_and_package_controls() -> None:
    """Keep optimization and package identity explicit instead of engine-assumed."""

    profile_help = CliRunner().invoke(app, ["asset-profile-init", "--help"])
    optimize_help = CliRunner().invoke(app, ["asset-optimize", "--help"])
    plan_help = CliRunner().invoke(app, ["asset-plan", "--help"])
    approve_help = CliRunner().invoke(app, ["asset-plan-approve", "--help"])
    convert_help = CliRunner().invoke(app, ["asset-material-convert", "--help"])
    package_help = CliRunner().invoke(
        app,
        ["asset-package", "--help"],
        env={"COLUMNS": "180"},
    )
    validate_help = CliRunner().invoke(app, ["asset-validate", "--help"])
    assert profile_help.exit_code == 0
    assert optimize_help.exit_code == 0
    assert plan_help.exit_code == 0
    assert approve_help.exit_code == 0
    assert convert_help.exit_code == 0
    assert package_help.exit_code == 0
    assert validate_help.exit_code == 0
    assert "--consolidation" in profile_help.stdout
    assert "--max-draw-calls" in profile_help.stdout
    assert "--budget-enforcement" in profile_help.stdout
    assert "--lod-mode" in profile_help.stdout
    assert "--collision-strategy" in profile_help.stdout
    assert "--profile" in optimize_help.stdout
    assert "--run-id" in optimize_help.stdout
    assert "--approved-plan-sha256" in optimize_help.stdout
    assert "--run-id" in plan_help.stdout
    assert "--plan-sha256" in approve_help.stdout
    assert "--approval-note" in approve_help.stdout
    assert "--conversion-id" in convert_help.stdout
    assert "--resolution" in convert_help.stdout
    assert "--margin-px" in convert_help.stdout
    assert "--render-device" in convert_help.stdout
    assert "--package-id" in package_help.stdout
    assert "--material-conversion-id" in package_help.stdout
    assert "--include-colliders" in package_help.stdout
    assert "--bounds-tolerance-m" in validate_help.stdout


def test_v07_mcp_tools_are_explicitly_whitelisted() -> None:
    """Keep every portable-asset MCP operation inside the project allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled


def test_v07_versions_preserve_older_contract_boundaries() -> None:
    """Advance the project while keeping portable data on its independent contract."""

    assert PROJECT_VERSION == "0.8.0"
    assert PORTABLE_ASSET_SCHEMA_VERSION == "0.7.0"


def test_export_pdf_scope_is_public() -> None:
    """Expose the derived portable-asset report without replacing canonical JSON."""

    result = CliRunner().invoke(
        app,
        ["report-pdf", "missing-job", "--scope", "unsupported"],
    )
    assert result.exit_code != 0
    assert "export" in result.output


def test_export_pdf_scope_exposes_immutable_run_and_package_selection() -> None:
    """Let a user report one exact V0.7 optimization run and package revision."""

    result = CliRunner().invoke(app, ["report-pdf", "--help"])
    assert result.exit_code == 0
    assert "--optimization-run-id" in result.output
    assert "--package-id" in result.output
