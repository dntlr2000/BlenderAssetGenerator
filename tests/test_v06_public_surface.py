from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

from codex_blender_modeler.cli import app

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "material-scaffold",
    "material-presets",
    "generate-procedural-textures",
    "attach-texture-manifest",
    "bake-materials",
    "validate-material-contracts",
    "inspect-materials",
    "render-material-swatches",
    "report-pdf",
    "visual-qa",
    "qa-compile-revision",
    "qa-approve-revision",
    "qa-apply-approved",
}
EXPECTED_MCP_TOOLS = {
    "initialize_materials",
    "get_material_presets",
    "generate_procedural_textures",
    "attach_texture_manifest",
    "bake_materials",
    "validate_material_contracts",
    "inspect_materials",
    "render_material_swatches",
    "generate_pdf_report",
    "run_visual_qa",
    "compile_visual_revision",
    "approve_visual_revision",
    "apply_approved_visual_revision",
}


def test_v06_cli_commands_are_registered() -> None:
    """Keep the documented V0.5/V0.6 CLI surface discoverable."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.stdout


def test_visual_qa_exposes_explicit_advisory_target_handoff() -> None:
    """Keep the external image-model handoff explicit instead of implying a bundled provider."""

    result = CliRunner().invoke(app, ["visual-qa", "--help"])
    assert result.exit_code == 0
    assert "--target-image" in result.stdout
    assert "--target-model" in result.stdout
    assert "--target-allowed-root" in result.stdout
    assert "--target-prompt-file" in result.stdout


def test_pdf_report_exposes_scope_run_and_output_controls() -> None:
    """Keep human-report scope, QA run selection, and destination explicit."""

    result = CliRunner().invoke(app, ["report-pdf", "--help"])
    assert result.exit_code == 0
    assert "--scope" in result.stdout
    assert "--qa-run-id" in result.stdout
    assert "--output" in result.stdout


def test_pdf_report_rejects_invalid_scope_before_job_access() -> None:
    """Reject unsupported presentation scopes before touching workspace state."""

    result = CliRunner().invoke(
        app,
        ["report-pdf", "missing-job", "--scope", "unsupported"],
    )
    assert result.exit_code != 0
    assert "scope must be build, material, qa, export, or full" in result.output


def test_v06_mcp_tools_are_whitelisted() -> None:
    """Keep every public V0.6 MCP tool explicitly allowed by project config."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled
