from __future__ import annotations

from pathlib import Path

from cli_help_support import assert_cli_help_contract
from typer.testing import CliRunner

from codex_blender_modeler.cli import app
from codex_blender_modeler.repository_catalog import discover_mcp_server_tools
from codex_blender_modeler.versioning import PROJECT_VERSION, STORAGE_RETENTION_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_storage_retention_cli_is_registered_without_combined_delete() -> None:
    """Expose inspect, exact plan/apply, resume, and verification as separate commands."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(
        result.stdout,
        required=(
            "storage-inventory",
            "storage-cleanup-plan",
            "storage-cleanup-apply",
            "storage-cleanup-resume",
            "storage-cleanup-verify",
            "storage-gate-retention-resume",
        ),
        forbidden=("storage-cleanup-all",),
    )


def test_storage_cleanup_apply_requires_exact_confirmation_option() -> None:
    """Keep destructive CLI execution behind one exact plan file digest."""

    result = CliRunner().invoke(app, ["storage-cleanup-apply", "--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(result.stdout, required=("--confirm-plan-sha256",))


def test_storage_retention_remains_cli_only_and_additive() -> None:
    """Avoid granting destructive cleanup authority to MCP or changing project V0.9."""

    tools = discover_mcp_server_tools(ROOT / "src/codex_blender_modeler/mcp_server.py")
    assert not any("storage_cleanup" in tool or "storage_inventory" in tool for tool in tools)
    assert PROJECT_VERSION == "0.9.1"
    assert STORAGE_RETENTION_SCHEMA_VERSION == "0.1.0"
