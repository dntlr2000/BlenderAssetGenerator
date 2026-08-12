"""Public CLI, MCP, allowlist, and package-surface tests for the material loop."""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codex_blender_modeler import autonomy_v2, codex_imagegen, material_authoring, mcp_server
from codex_blender_modeler.cli import app
from codex_blender_modeler.repository_catalog import PHASE_TOOL_PROFILES

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "codex-imagegen-material-exact-adoption-preflight",
    "codex-imagegen-material-bridge-plan",
    "codex-imagegen-material-bridge-status",
    "codex-imagegen-material-bridge-run",
    "codex-imagegen-material-promote",
    "codex-imagegen-material-resume",
    "codex-imagegen-native-normalize",
    "codex-imagegen-semantic-review-status",
    "autonomy-v2-codex-imagegen-continue",
}
EXPECTED_MCP_TOOLS = {
    "preflight_codex_imagegen_material_exact_adoption",
    "plan_codex_imagegen_material_bridge",
    "get_codex_imagegen_material_bridge_status",
    "run_codex_imagegen_material_bridge",
    "promote_codex_imagegen_material",
    "resume_codex_imagegen_material",
    "normalize_codex_imagegen_native_output",
    "get_codex_imagegen_semantic_review_status",
    "continue_autonomy_v2_codex_imagegen",
}


def test_material_loop_cli_and_mcp_surfaces_are_additive_and_opt_in() -> None:
    """Expose all nine paired surfaces while mutation switches default closed."""

    root_help = CliRunner().invoke(app, ["--help"])
    assert root_help.exit_code == 0
    assert all(command in root_help.stdout for command in EXPECTED_COMMANDS)
    for command in EXPECTED_COMMANDS:
        help_result = CliRunner().invoke(app, [command, "--help"])
        assert help_result.exit_code == 0
        assert "--enable-v2" in help_result.stdout
        assert "--enable-imagegen" in help_result.stdout
    for tool_name in EXPECTED_MCP_TOOLS:
        parameters = inspect.signature(getattr(mcp_server, tool_name)).parameters
        assert parameters["enable_v2"].default is False
        assert parameters["enable_imagegen"].default is False


def test_material_loop_mutations_reject_partial_opt_in_before_service_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when either AQ v2 or ImageGen companion consent is absent."""

    def unexpected(*args: object, **kwargs: object) -> dict[str, object]:
        """Fail if an underlying mutation is reached without both switches."""

        del args, kwargs
        raise AssertionError("mutation service should not be called")

    monkeypatch.setattr(mcp_server, "get_material_loop_status", unexpected)
    with pytest.raises(PermissionError, match="enable_v2 and enable_imagegen"):
        mcp_server.run_codex_imagegen_material_bridge(
            "material-loop-job",
            "material-loop-session",
            enable_v2=True,
        )
    with pytest.raises(PermissionError, match="enable_v2 and enable_imagegen"):
        mcp_server.promote_codex_imagegen_material(
            "material-loop-job",
            "material-loop-session",
            enable_imagegen=True,
        )
    cli_result = CliRunner().invoke(
        app,
        [
            "codex-imagegen-material-bridge-run",
            "material-loop-job",
            "material-loop-session",
            "--enable-v2",
        ],
    )
    assert cli_result.exit_code != 0


def test_material_bridge_run_selects_only_fixed_or_desktop_controllers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route exact adoption to the fixed copier and authored work to wait/resume only."""

    captured: list[object] = []

    def fake_execute(*args: object, **kwargs: object) -> dict[str, object]:
        """Capture the selected bounded controller without creating workspace evidence."""

        del args
        captured.append(kwargs["controller"])
        return {"controller_status": "waiting_for_output"}

    monkeypatch.setattr(mcp_server, "execute_material_loop_controller", fake_execute)
    monkeypatch.setattr(
        mcp_server,
        "get_material_loop_status",
        lambda *_args: {"controller_input": {"execution_mode": "exact_adoption"}},
    )
    mcp_server.run_codex_imagegen_material_bridge(
        "material-loop-job",
        "material-loop-session",
        enable_v2=True,
        enable_imagegen=True,
    )
    assert isinstance(
        captured[-1],
        mcp_server.ExactCodexImageMaterialAdoptionController,
    )
    monkeypatch.setattr(
        mcp_server,
        "get_material_loop_status",
        lambda *_args: {
            "controller_input": {"execution_mode": "controller_authored_completion"}
        },
    )
    mcp_server.run_codex_imagegen_material_bridge(
        "material-loop-job",
        "material-loop-session",
        enable_v2=True,
        enable_imagegen=True,
    )
    assert isinstance(captured[-1], mcp_server.DesktopInSessionController)


def test_material_loop_status_discloses_current_experimental_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep successful status explicitly current without implying profile activation."""

    monkeypatch.setattr(
        mcp_server,
        "get_material_loop_status",
        lambda *_args: {
            "state": {"status": "waiting_for_quality"},
            "selected_candidate": {"candidate_id": "candidate-01"},
            "normalization_status": {"status": "normalized"},
            "semantic_review_status": {"outcome": "passed"},
            "material_authoring_status": {"status": "candidate_ready"},
            "controller_request": {"request_id": "controller-request-01"},
            "controller_result": {"status": "completed"},
            "material_phase_receipt": {"kind": "material_phase_receipt"},
            "iq_status": {"status": "waiting_for_submission"},
            "delivery_progress": {"status": "not_started"},
            "remaining_budget": {"controller_invocations": 0, "promotions": 0},
            "latest_failure": None,
            "current": True,
            "stale": False,
            "unverified": True,
        },
    )
    monkeypatch.setattr(
        mcp_server,
        "get_autonomy_v2_status_internal",
        lambda *_args: {"state": {"next_action": "run_integrated_quality"}},
    )
    status = mcp_server.get_codex_imagegen_material_bridge_status(
        "material-loop-job",
        "material-loop-session",
    )
    assert status["profile_status"] == "disabled_experimental"
    assert status["current"] is True
    assert status["stale"] is False
    assert status["unverified"] is True
    assert status["material_loop"]["state"]["status"] == "waiting_for_quality"
    for field in (
        "selected_candidate",
        "normalization_status",
        "semantic_review_status",
        "material_authoring_status",
        "controller_request",
        "controller_result",
        "material_phase_receipt",
        "iq_status",
        "delivery_progress",
        "remaining_budget",
        "latest_failure",
    ):
        assert field in status["material_loop"]


def test_material_loop_host_tools_only_forward_to_bounded_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep promote, resume, normalize, semantic, and IQ tools as strict host forwards."""

    promotion_calls: list[tuple[str, str, int]] = []

    def fake_promote(job_id: str, session_id: str, *, preview_size: int) -> dict:
        """Capture one host promotion or recovery call."""

        promotion_calls.append((job_id, session_id, preview_size))
        return {"next_action": "run_integrated_quality"}

    monkeypatch.setattr(
        mcp_server,
        "_promote_and_finalize_codex_image_material_internal",
        fake_promote,
    )
    for tool in (
        mcp_server.promote_codex_imagegen_material,
        mcp_server.resume_codex_imagegen_material,
    ):
        result = tool(
            "material-loop-job",
            "material-loop-session",
            preview_size=256,
            enable_v2=True,
            enable_imagegen=True,
        )
        assert result["next_action"] == "run_integrated_quality"
    assert promotion_calls == [
        ("material-loop-job", "material-loop-session", 256),
        ("material-loop-job", "material-loop-session", 256),
    ]

    monkeypatch.setattr(
        mcp_server,
        "_normalize_codex_image_native_output_internal",
        lambda *_args: {"recovered": False},
    )
    assert mcp_server.normalize_codex_imagegen_native_output(
        "material-loop-job",
        "normalization-plan.json",
        enable_v2=True,
        enable_imagegen=True,
    ) == {"recovered": False}

    native_calls: list[tuple[str, dict[str, object]]] = []

    def fake_native_adopt(**kwargs: object) -> dict[str, object]:
        """Capture one native-output adoption facade call."""

        native_calls.append(("adopt", kwargs))
        return {"status": "adopted"}

    def fake_native_prepare(**kwargs: object) -> dict[str, object]:
        """Capture one prepared normalization facade call."""

        native_calls.append(("prepare", kwargs))
        return {"status": "prepared"}

    monkeypatch.setattr(mcp_server, "adopt_native_output_internal", fake_native_adopt)
    monkeypatch.setattr(mcp_server, "prepare_native_output_internal", fake_native_prepare)
    adopted = mcp_server.normalize_codex_imagegen_native_output(
        "material-loop-job",
        action="adopt",
        session_id="material-loop-session",
        native_source_path="C:/generated/native.png",
        allowed_source_root="C:/generated",
        native_output_id="native-output-01",
        enable_v2=True,
        enable_imagegen=True,
    )
    prepared = mcp_server.normalize_codex_imagegen_native_output(
        "material-loop-job",
        "normalization-plan.json",
        action="prepare",
        session_id="material-loop-session",
        adoption_receipt_path="native-adoption.json",
        enable_v2=True,
        enable_imagegen=True,
    )
    assert adopted["status"] == "adopted"
    assert prepared["status"] == "prepared"
    assert [item[0] for item in native_calls] == ["adopt", "prepare"]
    assert native_calls[0][1]["output_role"] == "base_color"
    assert native_calls[1][1]["normalization_plan_path"] == Path(
        "normalization-plan.json"
    )

    monkeypatch.setattr(
        mcp_server,
        "_codex_image_semantic_review_status_internal",
        lambda *_args: {"outcome": "review_required", "human_reviewed": False},
    )
    semantic = mcp_server.get_codex_imagegen_semantic_review_status(
        "material-loop-job",
        "material-loop-session",
    )
    assert semantic["human_reviewed"] is False

    promotion_artifact = object()
    captured_quality: dict[str, object] = {}
    monkeypatch.setattr(
        mcp_server,
        "_material_promotion_artifact_internal",
        lambda *_args: promotion_artifact,
    )

    def fake_quality(*args: object, **kwargs: object) -> dict[str, object]:
        """Capture one quality continuation without executing IQ."""

        captured_quality.update({"args": args, **kwargs})
        return {"quality_companion_completed": False}

    monkeypatch.setattr(mcp_server, "advance_material_loop_quality", fake_quality)
    submission = {"schema_version": "0.2.0", "submission_id": "iq-submission"}
    result = mcp_server.continue_autonomy_v2_codex_imagegen(
        "material-loop-job",
        "material-loop-session",
        submission,
        enable_v2=True,
        enable_imagegen=True,
    )
    assert result["quality_companion_completed"] is False
    assert captured_quality["promotion_receipt_artifact"] is promotion_artifact
    assert captured_quality["quality_submission"] == submission
    assert captured_quality["allow_disabled_experimental"] is True


def test_material_loop_tools_are_allowlisted_but_never_phase_authority() -> None:
    """Enable host orchestration while excluding raw ImageGen and promotion from phases."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        enabled = set(
            tomllib.load(handle)["mcp_servers"]["blender_modeler"]["enabled_tools"]
        )
    assert EXPECTED_MCP_TOOLS <= enabled
    assert "imagegen" not in enabled
    profiles = {profile.profile_id: profile for profile in PHASE_TOOL_PROFILES}
    assert "run_codex_imagegen" not in profiles["material_authoring"].allowed_tools
    assert (
        "promote_codex_imagegen_material"
        not in profiles["material_authoring"].allowed_tools
    )
    assert profiles["codex_imagegen"].allowed_tools == frozenset()


def test_material_loop_contracts_and_services_are_package_exports() -> None:
    """Keep companion contracts, V0.5 bridge, and host services importable explicitly."""

    for name in (
        "ImageGeneratedMaterialBridgePlan",
        "ImageGenNativeNormalizationPlan",
        "CodexImageSemanticReview",
        "execute_native_image_normalization",
    ):
        assert name in codex_imagegen.__all__
        assert hasattr(codex_imagegen, name)
    for name in (
        "CodexImageNormalizedAuthoredMaterialManifestV010",
        "CodexImageNormalizedMaterialAuthoringReceiptV010",
        "CodexImageNormalizedMaterialAuthoringRequestV010",
        "CodexImageV05ControllerBlueprint",
        "CodexImageV05BridgeReceipt",
        "author_codex_image_normalized_material_candidate",
        "build_codex_image_v05_controller_blueprint",
        "build_codex_image_normalized_material_request",
        "validate_codex_image_normalized_material_candidate",
        "validate_codex_image_v05_bridge",
    ):
        assert name in material_authoring.__all__
        assert hasattr(material_authoring, name)
    for name in (
        "publish_codex_image_material_loop_bridge",
        "execute_codex_image_material_loop_controller",
        "promote_codex_image_material_loop",
        "advance_codex_image_material_loop_quality",
    ):
        assert name in autonomy_v2.__all__
        assert hasattr(autonomy_v2, name)
