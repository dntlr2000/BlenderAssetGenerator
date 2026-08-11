from __future__ import annotations

import hashlib
import inspect
import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codex_blender_modeler import mcp_server
from codex_blender_modeler.autonomy.profiles import get_autonomy_profile_status
from codex_blender_modeler.cli import app
from codex_blender_modeler.integrated_quality import (
    QualityGateProfile,
    public_service,
    quality_artifact_input_sha256,
)
from codex_blender_modeler.qa.models import (
    BoundingBoxMetric,
    DirectVisualMetrics,
    VisualQAReport,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
    "autonomy-profile-status",
    "autonomy-v2-profile-status",
    "autonomy-v2-delivery-profiles",
    "autonomy-v2-plan",
    "autonomy-v2-status",
    "autonomy-v2-cancel",
    "controller-executor-status",
    "autonomy-plan",
    "autonomy-bind",
    "autonomy-status",
    "autonomy-advance",
    "autonomy-run",
    "autonomy-resume",
    "autonomy-cancel",
    "integrated-quality-run",
    "integrated-quality-status",
}
EXPECTED_MCP_TOOLS = {
    "get_autonomy_profile_status",
    "get_autonomy_v2_profile_status",
    "list_autonomy_v2_delivery_profiles",
    "plan_autonomous_quality_v2",
    "get_autonomy_v2_state",
    "cancel_autonomous_quality_v2",
    "get_controller_executor_status",
    "plan_autonomous_quality",
    "bind_autonomy_controller",
    "get_autonomy_state",
    "advance_autonomous_quality",
    "run_autonomous_quality",
    "resume_autonomous_quality",
    "cancel_autonomous_quality",
    "run_integrated_quality",
    "get_integrated_quality_status",
}


def test_autonomous_quality_cli_surface_is_discoverable_and_bounded() -> None:
    """Keep every new command additive and prevent public failed-step retry authority."""

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in EXPECTED_COMMANDS:
        assert command in result.stdout
    for command in ("autonomy-advance", "autonomy-run", "autonomy-resume"):
        help_result = CliRunner().invoke(app, [command, "--help"])
        assert help_result.exit_code == 0
        assert "--retry-failed" not in help_result.stdout
    run_help = CliRunner().invoke(app, ["autonomy-run", "--help"])
    assert "--max-actions" in run_help.stdout


def test_autonomous_quality_mcp_surface_is_allowlisted_and_one_action_bounded() -> None:
    """Expose only the agreed controller operations through the explicit MCP allowlist."""

    with (ROOT / ".codex" / "config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    enabled = set(config["mcp_servers"]["blender_modeler"]["enabled_tools"])
    assert EXPECTED_MCP_TOOLS <= enabled
    advance_parameters = inspect.signature(
        mcp_server.advance_autonomous_quality
    ).parameters
    assert set(advance_parameters) == {"job_id", "session_id"}
    assert "retry_failed" not in inspect.signature(
        mcp_server.resume_autonomous_quality
    ).parameters


def test_capabilities_expose_only_one_verified_autonomy_profile() -> None:
    """Disclose the standard overlay without presenting future profiles as supported."""

    status = get_autonomy_profile_status()
    assert set(status) == {"contract_version", "active_profile_id", "profiles"}
    assert all(
        item["profile_id"] != "autonomous_static_prop_v2"
        for item in status["profiles"]
    )
    active = [item for item in status["profiles"] if item["status"] == "verified_active"]
    disabled = [
        item for item in status["profiles"] if item["status"] == "disabled_experimental"
    ]
    assert [item["profile_id"] for item in active] == ["autonomous_static_prop_v1"]
    assert len(disabled) == 3
    capabilities = mcp_server.get_modeling_capabilities()["autonomous_quality"]
    assert capabilities["underlying_execution_policy"] == "standard"
    assert capabilities["verified_active_profile"] == "autonomous_static_prop_v1"
    assert capabilities["verified_active_profile_ids"] == [
        "autonomous_static_prop_v1"
    ]
    assert capabilities["advance_actions_per_call"] == 1
    assert capabilities["runtime_parity"] is False


def test_v2_public_plan_requires_explicit_experimental_opt_in() -> None:
    """Keep the parallel profile discoverable without silently enabling job creation."""

    cli_help = CliRunner().invoke(app, ["autonomy-v2-plan", "--help"])
    assert cli_help.exit_code == 0
    assert "--enable-v2" in cli_help.stdout
    parameters = inspect.signature(mcp_server.plan_autonomous_quality_v2).parameters
    assert "experimental_opt_in" in parameters
    assert parameters["experimental_opt_in"].default is False
    status = mcp_server.get_autonomy_v2_profile_status()
    assert status["status"] == "disabled_experimental"
    assert status["verified_active"] is False


def test_integrated_quality_public_runner_keeps_missing_axes_unscorable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Persist a verifiable report without inventing any score for omitted evidence."""

    root = tmp_path / "public_surface_job"
    root.mkdir()
    monkeypatch.setattr(public_service, "job_dir", lambda _job_id: root)
    result = public_service.run_integrated_quality(
        "public_surface_job",
        run_id="iq-public-surface",
    )
    assert result["report"]["outcome"] == "unscorable"
    assert all(axis["status"] == "unscorable" for axis in result["report"]["axes"])
    profile = QualityGateProfile.model_validate_json(
        (
            root
            / "reports"
            / "integrated_quality"
            / "profiles"
            / "iq-public-surface.json"
        ).read_text(encoding="utf-8")
    )
    assert profile.input_sha256 == quality_artifact_input_sha256(profile.provenance)
    status = public_service.get_integrated_quality_status(
        "public_surface_job", "iq-public-surface"
    )
    assert status["status"] == "current"
    assert status["quality_accepted"] is False

    report_path = root / status["report_path"]
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["notes"].append("tampered")
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    assert public_service.get_integrated_quality_status(
        "public_surface_job", "iq-public-surface"
    )["status"] == "invalid"


def test_integrated_quality_status_revalidates_all_provenance_and_source_bindings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Public status must fail closed after evidence, provenance, or source tampering."""

    root = tmp_path / "public_provenance_job"
    root.mkdir()
    qa_path = root / "qa" / "visual_qa_report.json"
    qa_path.parent.mkdir()
    qa_report = VisualQAReport(
        job_id="public_provenance_job",
        run_id="qa-public-provenance",
        request_sha256="a" * 64,
        camera_fingerprint="b" * 64,
        direct_metrics=DirectVisualMetrics(
            scoring_version="semantic_bbox_v2",
            silhouette_iou=0.9,
            silhouette_union_fraction=0.5,
            global_bbox=BoundingBoxMetric(
                reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
                rendered_bbox_norm=(0.1, 0.1, 0.9, 0.9),
                center_error_norm=0,
                size_error_norm=0,
            ),
            semantic_deviations=[],
            overall_direct_score=0.9,
        ),
        findings=[],
        generated_target_status="not_requested",
        warnings=[],
    )
    qa_path.write_text(qa_report.model_dump_json(indent=2), encoding="utf-8")
    monkeypatch.setattr(public_service, "job_dir", lambda _job_id: root)
    result = public_service.run_integrated_quality(
        "public_provenance_job",
        run_id="iq-public-provenance",
        qa_report_path=qa_path.relative_to(root),
    )
    assert public_service.get_integrated_quality_status(
        "public_provenance_job", "iq-public-provenance"
    )["status"] == "current"

    original_qa = qa_path.read_bytes()
    qa_payload = json.loads(original_qa)
    qa_payload["warnings"].append("tampered upstream evidence")
    qa_path.write_text(json.dumps(qa_payload), encoding="utf-8")
    evidence_status = public_service.get_integrated_quality_status(
        "public_provenance_job", "iq-public-provenance"
    )
    assert evidence_status["status"] == "invalid"
    assert any("visual_qa" in error for error in evidence_status["errors"])
    qa_path.write_bytes(original_qa)

    report_path = root / result["manifest"]["json_path"]
    manifest_path = (
        report_path.parent / "integrated_quality_report.manifest.json"
    )
    original_report = report_path.read_bytes()
    original_manifest = manifest_path.read_bytes()
    report_payload = json.loads(original_report)
    report_payload["provenance"]["input_sha256"] = "c" * 64
    report_path.write_text(json.dumps(report_payload), encoding="utf-8")
    manifest_payload = json.loads(original_manifest)
    manifest_payload["json_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    input_status = public_service.get_integrated_quality_status(
        "public_provenance_job", "iq-public-provenance"
    )
    assert input_status["status"] == "invalid"
    assert any(
        "manifest provenance differs from outputs" in error
        for error in input_status["errors"]
    )
    report_path.write_bytes(original_report)
    manifest_path.write_bytes(original_manifest)

    profile_artifact = next(
        artifact
        for artifact in result["report"]["provenance"]["artifacts"]
        if artifact["artifact_id"] == "quality_profile"
    )
    profile_path = root / profile_artifact["relative_path"]
    original_profile = profile_path.read_bytes()
    profile_payload = json.loads(original_profile)
    profile_payload["meaningful_gain_min"] = 0.02
    profile_path.write_text(json.dumps(profile_payload), encoding="utf-8")
    profile_status = public_service.get_integrated_quality_status(
        "public_provenance_job", "iq-public-provenance"
    )
    assert profile_status["status"] == "invalid"
    assert any("quality_profile" in error for error in profile_status["errors"])
    profile_path.write_bytes(original_profile)

    manifest_payload = json.loads(original_manifest)
    manifest_payload["source_fingerprint"] = "f" * 64
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    source_status = public_service.get_integrated_quality_status(
        "public_provenance_job", "iq-public-provenance"
    )
    assert source_status["status"] == "invalid"
    assert any(
        "manifest source must match provenance" in error
        for error in source_status["errors"]
    )


def test_integrated_quality_publication_reuses_profile_after_interruption(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An interrupted report publish leaves no run and safely adopts its exact profile."""

    root = tmp_path / "public_interrupted_job"
    root.mkdir()
    monkeypatch.setattr(public_service, "job_dir", lambda _job_id: root)
    original_writer = public_service.write_integrated_quality_evidence

    def fail_publish(*_args, **_kwargs):
        """Simulate interruption before the staged evidence directory is published."""

        raise RuntimeError("simulated publication interruption")

    monkeypatch.setattr(
        public_service,
        "write_integrated_quality_evidence",
        fail_publish,
    )
    with pytest.raises(RuntimeError, match="simulated publication interruption"):
        public_service.run_integrated_quality(
            "public_interrupted_job",
            run_id="iq-public-interrupted",
        )
    run_root = (
        root
        / "reports"
        / "integrated_quality"
        / "runs"
        / "iq-public-interrupted"
    )
    profile_path = (
        root
        / "reports"
        / "integrated_quality"
        / "profiles"
        / "iq-public-interrupted.json"
    )
    assert not run_root.exists()
    assert profile_path.is_file()
    profile_before = profile_path.read_bytes()

    monkeypatch.setattr(
        public_service,
        "write_integrated_quality_evidence",
        original_writer,
    )
    public_service.run_integrated_quality(
        "public_interrupted_job",
        run_id="iq-public-interrupted",
    )
    assert profile_path.read_bytes() == profile_before
    assert public_service.get_integrated_quality_status(
        "public_interrupted_job", "iq-public-interrupted"
    )["status"] == "current"
