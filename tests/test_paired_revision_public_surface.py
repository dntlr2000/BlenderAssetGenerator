"""Exact opt-in, immutable planner, CLI, and MCP contracts for paired guarded revisions."""

from __future__ import annotations

import inspect
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from codex_blender_modeler import cli, mcp_server
from codex_blender_modeler.orchestration.models import (
    DestinationRequest,
    DestinationResolution,
    IntentRouting,
    WorkflowRequest,
)
from codex_blender_modeler.orchestration.planner import build_workflow_plan

ROOT = Path(__file__).resolve().parents[1]
PAIR = {
    "paired_modeling_plan_path": "analysis/candidates/revision_modeling_plan.json",
    "paired_modeling_plan_sha256": "b" * 64,
}


def _request(**updates) -> WorkflowRequest:
    """Build a disposable explicit manual guarded request for public contract tests."""

    payload = {
        "workflow_id": "wf-paired-test",
        "job_id": "paired_asset",
        "raw_request": "Apply this exact bounded paired revision",
        "requested_scope": "geometry_only",
        "intent_hint": "revise_asset",
        "revision_strategy": "manual_guarded",
        "created_at": datetime.now(UTC),
        **updates,
    }
    return WorkflowRequest.model_validate(payload)


def _plan(request: WorkflowRequest, *, intent: str = "revise_asset"):
    """Build an immutable plan using explicit source bytes without creating a job."""

    routing = IntentRouting(
        workflow_id=request.workflow_id,
        job_id=request.job_id,
        intent=intent,
        execution_policy="standard",
        confidence=1.0,
        reasons=["Exact fixture selection"],
        destination=DestinationResolution(
            requested=DestinationRequest(), status="not_requested", reason="No destination"
        ),
        routed_at=datetime.now(UTC),
    )
    return build_workflow_plan(
        request, routing, request_sha256="1" * 64, routing_sha256="2" * 64,
        existing_modeling_plan_sha256="a" * 64,
        existing_assembly_consistency_policy="spatial_v1",
    )


def test_legacy_request_omits_paired_fields_and_retains_plan_shape() -> None:
    """Absent opt-in keeps old request JSON and ordinary revision outputs unchanged."""

    request = _request()
    assert not (PAIR.keys() & request.model_dump(mode="json").keys())
    legacy = WorkflowRequest.model_validate_json(request.model_dump_json())
    assert legacy.paired_modeling_plan_path is None
    plan = _plan(legacy)
    assert all(not (PAIR.keys() & step.parameters.keys()) for step in plan.steps)
    assert not any(
        output.artifact_id in {"revision.candidate_modeling_plan", "revision.modeling_plan"}
        for step in plan.steps for output in step.outputs
    )


@pytest.mark.parametrize("updates", [
    {"paired_modeling_plan_path": PAIR["paired_modeling_plan_path"]},
    {"paired_modeling_plan_sha256": PAIR["paired_modeling_plan_sha256"]},
    {**PAIR, "intent_hint": "auto"},
    {**PAIR, "intent_hint": "new_asset"},
    {**PAIR, "revision_strategy": "candidate_review"},
    {**PAIR, "revision_strategy": None},
    {**PAIR, "execution_policy": "background_exterior"},
    {**PAIR, "paired_modeling_plan_sha256": "B" * 64},
    {**PAIR, "paired_modeling_plan_path": "../outside.json"},
    {**PAIR, "paired_modeling_plan_path": "/absolute.json"},
])
def test_request_rejects_incomplete_or_broadened_paired_selection(updates) -> None:
    """An exact pair cannot silently select auto, background, or candidate-review authority."""

    with pytest.raises(ValueError):
        _request(**updates)


def test_paired_plan_binds_every_revision_step_and_both_lifecycles() -> None:
    """Author owns immutable candidate evidence and apply owns the canonical snapshot."""

    plan = _plan(_request(**PAIR))
    steps = {step.step_id: step for step in plan.steps}
    for step in plan.steps:
        if step.step_id.startswith("revision."):
            assert {key: step.parameters[key] for key in PAIR} == PAIR
            assert step.parameters["paired_workflow_id"] == plan.workflow_id
        if "expected_modeling_plan_sha256" in step.parameters:
            assert step.parameters["expected_modeling_plan_sha256"] == "a" * 64
    candidate = next(
        output for output in steps["revision.author"].outputs
        if output.artifact_id == "revision.candidate_modeling_plan"
    )
    assert candidate.path == PAIR["paired_modeling_plan_path"]
    assert candidate.lifecycle == "immutable_run"
    assert candidate.canonical is False
    promoted = next(
        output for output in steps["revision.apply"].outputs
        if output.artifact_id == "revision.modeling_plan"
    )
    assert promoted.lifecycle == "workflow_snapshot"
    assert promoted.source_path == "analysis/modeling_plan.json"
    assert promoted.path.startswith("workflows/wf-paired-test/artifacts/s/")
    assert promoted.path != promoted.source_path


def test_paired_plan_rejects_inconsistent_routing() -> None:
    """A valid paired request cannot be reused in a different routed workflow."""

    with pytest.raises(ValueError, match="requires revise_asset routing"):
        _plan(_request(**PAIR), intent="visual_qa")


@pytest.mark.parametrize("paired", [False, True])
def test_cli_and_mcp_forward_exact_optional_pair(monkeypatch, paired) -> None:
    """Both public planners forward opt-in bytes while preserving absent legacy arguments."""

    calls = []

    def capture(request, **kwargs):
        """Capture public forwarding without creating files or workflow authority."""

        calls.append((request, kwargs))
        return SimpleNamespace(model_dump_json=lambda: "{}", model_dump=lambda **_: {})

    monkeypatch.setattr(cli, "plan_orchestrated_workflow", capture)
    monkeypatch.setattr(mcp_server, "plan_workflow_internal", capture)
    args = ["workflow-plan", "--request", "Revise", "--job-id", "paired_asset",
            "--intent", "revise_asset", "--revision-strategy", "manual_guarded"]
    if paired:
        args.extend(["--paired-modeling-plan-path", PAIR["paired_modeling_plan_path"],
                     "--paired-modeling-plan-sha256", PAIR["paired_modeling_plan_sha256"]])
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    mcp_server.plan_short_workflow(
        "Revise", job_id="paired_asset", intent="revise_asset",
        revision_strategy="manual_guarded", **(PAIR if paired else {}),
    )
    assert len(calls) == 2
    for _, kwargs in calls:
        assert {key: kwargs[key] for key in PAIR if key in kwargs} == (PAIR if paired else {})


def test_recovery_cli_and_mcp_forward_exact_intent(monkeypatch) -> None:
    """Rollback-only public recovery forwards the exact host intent hash without widening it."""

    calls = []

    def capture(job_id, workflow_id, *, intent_sha256):
        """Capture exact rollback selection without mutating canonical fixtures."""

        calls.append((job_id, workflow_id, intent_sha256))
        return {"outcome": "rolled_back"}

    monkeypatch.setattr(cli, "recover_paired_workflow_revision", capture)
    monkeypatch.setattr(mcp_server, "recover_paired_workflow_revision_internal", capture)
    digest = "c" * 64
    result = CliRunner().invoke(cli.app, [
        "workflow-recover-paired-revision", "paired_asset", "wf-paired-test",
        "--intent-sha256", digest,
    ])
    assert result.exit_code == 0, result.output
    assert mcp_server.recover_paired_workflow_revision(
        "paired_asset", "wf-paired-test", digest,
    ) == {"outcome": "rolled_back"}
    assert calls == [("paired_asset", "wf-paired-test", digest)] * 2


def test_schema_and_tool_allowlist_expose_paired_contract() -> None:
    """Generated schema, callable defaults, and project tool enablement stay synchronized."""

    schema = json.loads((ROOT / "schemas/workflow_request.schema.json").read_text())
    assert schema == WorkflowRequest.model_json_schema()
    signature = inspect.signature(mcp_server.plan_short_workflow)
    for key in PAIR:
        assert signature.parameters[key].default is None
        assert schema["properties"][key]["default"] is None
        assert key not in schema["required"]
    with (ROOT / ".codex/config.toml").open("rb") as handle:
        enabled = tomllib.load(handle)["mcp_servers"]["blender_modeler"]["enabled_tools"]
    assert "recover_paired_workflow_revision" in enabled


@pytest.mark.parametrize("filename, model_name", [
    ("paired_modeling_plan_binding.schema.json", "PairedModelingPlanBinding"),
    ("paired_revision_transaction_intent.schema.json", "PairedTransactionIntent"),
    ("paired_revision_commit_receipt.schema.json", "PairedCommitReceipt"),
    ("paired_revision_rollback_receipt.schema.json", "PairedRollbackReceipt"),
])
def test_paired_machine_evidence_schema_parity(filename, model_name):
    """Versioned pair evidence uses the authoritative strict generated JSON schemas."""

    from codex_blender_modeler.orchestration import paired_models

    model = getattr(paired_models, model_name)
    assert json.loads((ROOT / "schemas" / filename).read_text()) == model.model_json_schema()
