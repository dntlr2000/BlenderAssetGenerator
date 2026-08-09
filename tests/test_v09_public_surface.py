from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.cli import app
from codex_blender_modeler.versioning import (
    DESTINATION_HANDOFF_SCHEMA_VERSION,
    PRODUCTION_DISPATCH_SCHEMA_VERSION,
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
    "production-dispatch",
    "production-bind-task",
    "production-status",
    "production-advance",
    "production-complete-step",
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
    "create_asset_production_dispatch",
    "bind_asset_production_task",
    "get_asset_production_dispatch_status",
    "advance_delegated_production_controller",
    "record_delegated_production_step",
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


def test_production_controller_cannot_receive_approval_or_retry_authority() -> None:
    """Keep exact handoff approval and failed retry outside the controller advance API."""

    result = CliRunner().invoke(app, ["production-advance", "--help"])
    assert result.exit_code == 0
    assert "--retry-failed" not in result.stdout
    assert "--handoff-plan-sha256" not in result.stdout
    binding = CliRunner().invoke(app, ["production-bind-task", "--help"])
    assert binding.exit_code == 0
    assert "--confirm-tool-profile" in binding.stdout
    assert "--tool-profile-sha256" in binding.stdout


def test_production_dispatch_cli_uses_unambiguous_compact_option_names() -> None:
    """Keep every production-dispatch option distinguishable in narrow terminals."""

    result = CliRunner().invoke(app, ["production-dispatch", "--help"])
    assert result.exit_code == 0
    for option in (
        "--reference",
        "--content-scope",
        "--subject",
        "--policy",
        "--ctrl-mode",
        "--dest-kind",
        "--dest-name",
        "--dest-version",
        "--dest-pipeline",
        "--handoff",
        "--host-limit",
        "--qa-limit",
        "--texture-limit",
        "--triangle-limit",
        "--provider-limit",
        "--convergence",
        "--target-direct",
        "--target-iou",
        "--min-gain",
        "--min-confidence",
        "--conv-iters",
    ):
        assert option in result.stdout


def test_production_dispatch_mcp_exposes_bounded_convergence_inputs() -> None:
    """Keep the MCP dispatcher aligned with the explicit CLI convergence contract."""

    parameters = inspect.signature(
        mcp_server.create_asset_production_dispatch
    ).parameters
    for name in (
        "controller_execution_mode",
        "convergence_mode",
        "convergence_target_direct_score",
        "convergence_target_silhouette_iou",
        "convergence_minimum_iteration_gain",
        "convergence_minimum_candidate_confidence",
        "convergence_max_iterations",
    ):
        assert name in parameters


def test_modeling_capabilities_disclose_both_controller_execution_modes() -> None:
    """Expose desktop convenience without overstating its approval isolation."""

    production = mcp_server.get_modeling_capabilities()["asset_production_dispatch"]
    assert production["controller_execution_modes"] == [
        "client_mediated",
        "desktop_in_session",
    ]
    assert production["default_controller_execution_mode"] == "client_mediated"
    assert production["desktop_approval_isolation"] == "workflow_contract_only"
    assert production["desktop_requires_external_task_binding"] is False


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
    assert PRODUCTION_DISPATCH_SCHEMA_VERSION == "0.9.0"
