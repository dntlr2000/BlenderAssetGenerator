from __future__ import annotations

import tomllib
from pathlib import Path

from cli_help_support import assert_cli_help_contract
from typer.main import get_command
from typer.testing import CliRunner

import codex_blender_modeler.cli as cli_module
import codex_blender_modeler.mcp_server as mcp_module
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
    "qa-convergence-plan",
    "qa-convergence-approve",
    "qa-convergence-run",
    "qa-convergence-status",
    "qa-convergence-cancel",
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
    "plan_visual_convergence",
    "approve_visual_convergence",
    "run_visual_convergence",
    "get_visual_convergence_status",
    "cancel_visual_convergence",
}


def test_v06_cli_commands_are_registered() -> None:
    """Keep the documented V0.5/V0.6 CLI surface discoverable."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(result.stdout, required=EXPECTED_COMMANDS)


def test_visual_qa_exposes_explicit_advisory_target_handoff() -> None:
    """Keep the external image-model handoff explicit instead of implying a bundled provider."""

    result = CliRunner().invoke(app, ["visual-qa", "--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(
        result.stdout,
        required=(
            "--target-image",
            "--target-model",
            "--target-allowed-root",
            "--target-prompt-file",
        ),
    )


def test_pdf_report_exposes_scope_run_and_output_controls() -> None:
    """Keep human-report scope, QA run selection, and destination explicit."""

    result = CliRunner().invoke(app, ["report-pdf", "--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(
        result.stdout,
        required=("--scope", "--qa-run-id", "--output"),
    )


def test_pdf_report_rejects_invalid_scope_before_job_access() -> None:
    """Reject unsupported presentation scopes before touching workspace state."""

    result = CliRunner().invoke(
        app,
        ["report-pdf", "missing-job", "--scope", "unsupported"],
    )
    assert result.exit_code != 0
    assert "scope must be build, material, qa, export, or full" in result.output


def test_visual_convergence_cli_exposes_exact_plan_and_bounded_budgets() -> None:
    """Expose one exact approval plus bounded targets instead of blanket authority."""

    runner = CliRunner()
    plan = runner.invoke(app, ["qa-convergence-plan", "--help"])
    approve = runner.invoke(app, ["qa-convergence-approve", "--help"])
    run = runner.invoke(app, ["qa-convergence-run", "--help"])
    cancel = runner.invoke(app, ["qa-convergence-cancel", "--help"])

    assert plan.exit_code == 0
    plan_command = get_command(app).commands["qa-convergence-plan"]
    plan_options = {
        option
        for parameter in plan_command.params
        for option in getattr(parameter, "opts", [])
    }
    assert "--target-direct-score" in plan_options
    assert "--target-silhouette-iou" in plan_options
    assert "--allowed-target-id" in plan_options
    assert "--max-iterations" in plan_options
    assert "--max-changed-ids" in plan_options
    assert "--path-limit-json" in plan_options
    assert approve.exit_code == 0
    approve_command = get_command(app).commands["qa-convergence-approve"]
    approve_options = {
        option
        for parameter in approve_command.params
        for option in getattr(parameter, "opts", [])
    }
    assert "--plan-sha256" in approve_options
    assert "--approval-note" in approve_options
    assert run.exit_code == 0
    run_command = get_command(app).commands["qa-convergence-run"]
    run_options = {
        option
        for parameter in run_command.params
        for option in getattr(parameter, "opts", [])
    }
    assert "--render-engine" in run_options
    assert "--render-device" in run_options
    assert_cli_help_contract(run.stdout.lower(), required=("at most one",))
    assert "at most one" in (mcp_module.run_visual_convergence.__doc__ or "").lower()
    assert cancel.exit_code == 0
    cancel_command = get_command(app).commands["qa-convergence-cancel"]
    cancel_options = {
        option
        for parameter in cancel_command.params
        for option in getattr(parameter, "opts", [])
    }
    assert "--reason" in cancel_options


def test_convergence_plan_hash_is_the_opt_in_without_global_auto_mode(
    monkeypatch,
) -> None:
    """Keep suggest defaults compatible while exact plan approval provides authority."""

    calls: list[tuple[tuple, dict]] = []

    def fake_plan(*args, **kwargs):
        """Capture one public plan request without reading a real job."""

        calls.append((args, kwargs))
        return {
            "ok": True,
            "status": "waiting_for_exact_approval",
            "plan_sha256": "a" * 64,
        }

    monkeypatch.setattr(cli_module, "plan_job_visual_convergence", fake_plan)
    cli_result = CliRunner().invoke(
        app,
        [
            "qa-convergence-plan",
            "asset-test",
            "qa-run-01",
            "--target-direct-score",
            "0.8",
            "--target-silhouette-iou",
            "0.75",
            "--path-limit-json",
            (
                '{"path_family":"transform.location",'
                '"allowed_operations":["add"],"max_absolute_delta":0.25}'
            ),
        ],
    )
    assert cli_result.exit_code == 0
    assert "waiting_for_exact_approval" in cli_result.stdout

    monkeypatch.setattr(mcp_module, "plan_job_visual_convergence", fake_plan)
    mcp_result = mcp_module.plan_visual_convergence(
        "asset-test",
        "qa-run-01",
        0.8,
        0.75,
        path_limits=[
            {
                "path_family": "geometry.dimensions",
                "allowed_operations": ["multiply"],
                "max_relative_delta": 0.05,
            }
        ],
    )
    assert mcp_result["status"] == "waiting_for_exact_approval"
    assert len(calls) == 2
    assert calls[0][1]["path_limits"][0].path_family == "transform.location"
    assert calls[1][1]["path_limits"][0].path_family == "geometry.dimensions"


def test_convergence_cli_rejects_invalid_path_limit_json_before_job_access() -> None:
    """Reject malformed public path authority before any workspace is inspected."""

    result = CliRunner().invoke(
        app,
        [
            "qa-convergence-plan",
            "missing-job",
            "qa-run-01",
            "--target-direct-score",
            "0.8",
            "--target-silhouette-iou",
            "0.75",
            "--path-limit-json",
            '{"path_family":"arbitrary.code","allowed_operations":["set"]}',
        ],
    )
    assert result.exit_code != 0
    assert_cli_help_contract(
        result.output,
        required=("--path-limit-json item 1",),
    )


def test_v06_mcp_tools_are_whitelisted() -> None:
    """Keep every public V0.6 MCP tool explicitly allowed by project config."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled


def test_mcp_preloads_optional_vision_before_stdio_workers(monkeypatch) -> None:
    """Prevent native OpenCV imports from first occurring after MCP workers start."""

    events: list[str] = []
    monkeypatch.setattr(
        mcp_module,
        "_preload_optional_vision_runtime",
        lambda: events.append("vision"),
    )
    monkeypatch.setattr(
        mcp_module.mcp,
        "run",
        lambda *, transport: events.append(f"mcp:{transport}"),
    )

    mcp_module.main()

    assert events == ["vision", "mcp:stdio"]
