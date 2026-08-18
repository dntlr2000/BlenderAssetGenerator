from __future__ import annotations

import inspect
import json
import tomllib
from pathlib import Path

from cli_help_support import assert_cli_help_contract
from typer.testing import CliRunner

from codex_blender_modeler import cli as cli_module
from codex_blender_modeler import mcp_server
from codex_blender_modeler.cli import app

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "codex-imagegen-status",
    "codex-imagegen-plan",
    "codex-imagegen-run",
    "codex-imagegen-select",
    "codex-imagegen-adopt",
}
EXPECTED_MCP_TOOLS = {
    "get_codex_imagegen_status",
    "plan_codex_imagegen",
    "run_codex_imagegen",
    "select_codex_imagegen",
    "adopt_codex_imagegen",
}


def test_codex_imagegen_cli_is_additive_and_requires_both_plan_opt_ins() -> None:
    """Keep the companion discoverable while both experimental switches default closed."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert_cli_help_contract(result.stdout, required=EXPECTED_COMMANDS)
    plan_help = CliRunner().invoke(app, ["codex-imagegen-plan", "--help"])
    assert plan_help.exit_code == 0
    assert_cli_help_contract(
        plan_help.stdout,
        required=("--enable-v2", "--disable-v2"),
    )
    parameters = inspect.signature(mcp_server.plan_codex_imagegen).parameters
    assert parameters["enable_v2"].default is False
    assert parameters["allow_disabled_experimental"].default is False


def test_codex_imagegen_cli_plan_forwards_strict_material_scope(monkeypatch) -> None:
    """Forward exact comma-separated plan scope without changing the base v2 entrypoint."""

    captured: dict[str, object] = {}

    def fake_plan(request: str, **kwargs: object) -> dict[str, object]:
        """Capture one CLI plan call without creating a workspace fixture."""

        captured.update({"request": request, **kwargs})
        return {"status": "planned"}

    monkeypatch.setattr(
        cli_module,
        "plan_autonomous_static_prop_v2_codex_imagegen",
        fake_plan,
    )
    result = CliRunner().invoke(
        app,
        [
            "codex-imagegen-plan",
            "author a wood swatch",
            "--reference",
            "reference.png",
            "--target-subject",
            "wooden sign",
            "--target-material-ids",
            "wood-base,wood-trim",
            "--semantic-roles",
            "wood,surface",
            "--prompt-template-id",
            "wood-swatch-v1",
            "--output-roles",
            "base_color,decal_rgb",
            "--enable-v2",
            "--allow-disabled-experimental",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"status": "planned"}
    assert captured["requested_delivery_profiles"] == ["portable_gltf"]
    assert captured["target_material_ids"] == ["wood-base", "wood-trim"]
    assert captured["semantic_roles"] == ["wood", "surface"]
    assert captured["allowed_output_roles"] == ["base_color", "decal_rgb"]
    assert captured["codex_imagegen_allowed"] is True
    assert captured["allow_disabled_experimental"] is True


def test_codex_imagegen_static_status_discloses_no_daemon_or_credential_authority() -> None:
    """Report the disabled current-task boundary without prompts, secrets, or background claims."""

    status = mcp_server.get_codex_imagegen_status()
    assert status["status"] == "disabled_experimental"
    assert status["current_controller_mode"] == "desktop_in_session"
    assert status["codex_controller_required"] is True
    assert status["repository_can_spawn_codex_task"] is False
    assert status["autonomous_daemon"] is False
    assert status["network_required"] is False
    assert status["api_key_required"] is False
    assert status["credential_scope"] == "none"
    assert not any("prompt" in key.lower() for key in status)


def test_codex_imagegen_cli_run_reads_prompt_without_echoing_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Pass prompt text only to the host service and keep it out of command output."""

    prompt = "seamless wood grain without words"
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, object]:
        """Capture one desktop assignment call without invoking a controller."""

        captured.update(kwargs)
        return {
            "status": "waiting_for_controller",
            "repository_invoked_imagegen": False,
        }

    monkeypatch.setattr(cli_module, "run_codex_imagegen_controller_phase", fake_run)
    result = CliRunner().invoke(
        app,
        [
            "codex-imagegen-run",
            "public-image-job",
            "session-001",
            "--prompt-file",
            str(prompt_file),
        ],
    )
    assert result.exit_code == 0
    assert captured["rendered_prompt_text"] == prompt
    assert prompt not in result.stdout
    assert json.loads(result.stdout)["repository_invoked_imagegen"] is False


def test_codex_imagegen_mcp_run_is_only_a_host_service_forwarder(monkeypatch) -> None:
    """Keep the MCP run tool on the waiting/resume host boundary without hidden authority."""

    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, object]:
        """Capture one MCP request and return an explicit non-execution receipt."""

        captured.update(kwargs)
        return {
            "status": "waiting_for_controller",
            "repository_invoked_imagegen": False,
        }

    monkeypatch.setattr(mcp_server, "run_codex_imagegen_internal", fake_run)
    result = mcp_server.run_codex_imagegen(
        "public-image-job",
        "session-001",
        rendered_prompt_text="bounded prompt",
    )
    assert result["repository_invoked_imagegen"] is False
    assert captured == {
        "job_id": "public-image-job",
        "session_id": "session-001",
        "rendered_prompt_text": "bounded prompt",
        "plan_item_id": None,
        "exact_text_value": None,
        "timeout_seconds": 900,
    }


def test_codex_imagegen_adopt_separates_prepare_and_finalize_inputs(monkeypatch) -> None:
    """Expose one two-mode command without letting prepare overrides affect finalization."""

    calls: list[tuple[str, dict[str, object]]] = []

    def fake_prepare(**kwargs: object) -> dict[str, object]:
        """Capture one staging-only adoption preparation call."""

        calls.append(("prepare", kwargs))
        return {"status": "material_request_required"}

    def fake_adopt(**kwargs: object) -> dict[str, object]:
        """Capture one strict local material finalization call."""

        calls.append(("adopt", kwargs))
        return {"status": "completed"}

    monkeypatch.setattr(
        cli_module,
        "prepare_codex_imagegen_material_adoption",
        fake_prepare,
    )
    monkeypatch.setattr(
        cli_module,
        "adopt_codex_imagegen_material_phase",
        fake_adopt,
    )
    prepare = CliRunner().invoke(
        app,
        [
            "codex-imagegen-adopt",
            "public-image-job",
            "session-001",
            "--material-strategy",
            "codex_generated_procedural_hybrid_v1",
            "--direct-channels",
            "base_color,decal_rgb",
            "--exact-text-evidence",
            "analysis/exact-signage-text.json",
        ],
    )
    assert prepare.exit_code == 0
    assert calls[-1] == (
        "prepare",
        {
            "job_id": "public-image-job",
            "session_id": "session-001",
            "material_strategy": "codex_generated_procedural_hybrid_v1",
            "direct_channels": ["base_color", "decal_rgb"],
            "exact_text_evidence_path": Path(
                "analysis/exact-signage-text.json"
            ),
        },
    )
    finalize = CliRunner().invoke(
        app,
        [
            "codex-imagegen-adopt",
            "public-image-job",
            "session-001",
            "--material-request",
            "production/autonomy_v2/session-001/codex_imagegen/material-request.json",
        ],
    )
    assert finalize.exit_code == 0
    assert calls[-1][0] == "adopt"
    assert calls[-1][1]["material_request_path"] == Path(
        "production/autonomy_v2/session-001/codex_imagegen/material-request.json"
    )
    rejected = CliRunner().invoke(
        app,
        [
            "codex-imagegen-adopt",
            "public-image-job",
            "session-001",
            "--material-request",
            "request.json",
            "--direct-channels",
            "base_color",
            "--exact-text-evidence",
            "analysis/exact-signage-text.json",
        ],
    )
    assert rejected.exit_code != 0
    assert len(calls) == 2


def test_codex_imagegen_mcp_adopt_enforces_the_same_two_modes(monkeypatch) -> None:
    """Keep MCP adoption overrides prepare-only and request finalization path-bound."""

    captured: dict[str, object] = {}

    def fake_adopt(**kwargs: object) -> dict[str, object]:
        """Capture one MCP material request without touching workspace evidence."""

        captured.update(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(mcp_server, "adopt_codex_imagegen_internal", fake_adopt)
    result = mcp_server.adopt_codex_imagegen(
        "public-image-job",
        "session-001",
        material_request_path="request.json",
    )
    assert result == {"status": "completed"}
    assert captured["material_request_path"] == Path("request.json")
    try:
        mcp_server.adopt_codex_imagegen(
            "public-image-job",
            "session-001",
            material_request_path="request.json",
            direct_channels=["base_color"],
            exact_text_evidence_path="analysis/exact-signage-text.json",
        )
    except ValueError as exc:
        assert "prepare-only" in str(exc)
    else:
        raise AssertionError("MCP finalization accepted prepare-only overrides")


def test_codex_imagegen_project_allowlist_contains_host_tools_not_capability() -> None:
    """Allow MCP orchestration tools without granting the controller-only imagegen tool."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled
    assert "imagegen" not in enabled
