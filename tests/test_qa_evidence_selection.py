"""Public exact-mask selection and immutable Standard QA-only continuation coverage."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_reference_subject_extent import _fixture
from test_visual_qa_service import _mock_render
from typer.main import get_command
from typer.testing import CliRunner

from codex_blender_modeler import cli, mcp_server, qa
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.orchestration import planner
from codex_blender_modeler.orchestration import service as workflow
from codex_blender_modeler.orchestration.models import WorkflowPlan, WorkflowRequest
from codex_blender_modeler.qa import reference_mask_constraints
from codex_blender_modeler.qa import service as native
from codex_blender_modeler.qa.evidence_selection import (
    load_reference_mask_selection,
    selection_artifact,
)
from codex_blender_modeler.reference_fidelity.service import artifact_at
from codex_blender_modeler.workspace import sha256_file


def _job(tmp_path, monkeypatch):
    """Make an isolated current job whose second part cannot justify whole-subject bounds."""
    root = tmp_path / "workspaces/asset_qa"
    fix = _fixture(root)
    fix.scene = fix.scene.model_copy(update={"job_id": "asset_qa"})
    fix.extent = fix.extent.model_copy(update={"job_id": "asset_qa"})
    fix.extent_path.write_text(fix.extent.model_dump_json())
    fix.seed = fix.seed.model_copy(
        update={
            "job_id": "asset_qa",
            "subject_extent": artifact_at(root, fix.extent_path),
        }
    )
    fix.path = root / "seeds.json"
    fix.path.write_text(fix.seed.model_dump_json(indent=2) + "\n")
    fix.artifact = artifact_at(root, fix.path)
    fix.scene_path = root / "analysis/scene_spec.json"
    fix.scene_path.parent.mkdir()
    fix.scene_path.write_text(fix.scene.model_dump_json())
    mask = root / "analysis/masks/reference_content.png"
    mask.parent.mkdir()
    mask.write_bytes(fix.source.read_bytes())
    (root / "job.json").write_text(
        json.dumps(
            {
                "job_id": "asset_qa",
                "mode": "concept",
                "reference_path": "input/reference.png",
                "reference_sha256": sha256_file(fix.reference),
                "sources": [
                    {
                        "kind": "reference",
                        "path": "input/reference.png",
                        "sha256": sha256_file(fix.reference),
                    }
                ],
                "scale_anchors": [],
                "reference_content_scope": "primary_object_only",
                "target_subject": "isolated fixture",
            }
        )
    )
    (root / "reports").mkdir()
    (root / "reports/validation.json").write_text('{"ok":true}')
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(root.parent))
    monkeypatch.setattr(
        native, "_render_job_qa_passes", _mock_render(root, fix.scene.objects[0].id)
    )
    monkeypatch.setattr(reference_mask_constraints, "refine_reference_trimap", _sure_labels)
    return fix


def _sure_labels(_reference, trimap):
    """Return independently observed fixture pixels through the segmentation seam."""
    return trimap.copy()


def _plan(fix, **kwargs):
    """Use the public host planner with an explicit current QA-only mask selection."""
    return workflow.plan_workflow(
        "Validate current reference evidence",
        job_id="asset_qa",
        intent="visual_qa",
        scope="qa_only",
        reference_mask_seed_path=fix.artifact.path,
        reference_mask_seed_sha256=fix.artifact.sha256,
        **kwargs,
    )


def _contracts(fix, state):
    """Load native immutable contracts rather than patching any historical workflow."""
    directory = fix.root / "workflows" / state.workflow_id
    return (
        WorkflowRequest.model_validate_json((directory / "request.json").read_bytes()),
        WorkflowPlan.model_validate_json((directory / "plan.json").read_bytes()),
        directory,
    )


def test_public_qa_opt_in_freezes_exact_source_bytes(tmp_path, monkeypatch):
    """The ordinary public QA service preserves full source extent and all exact snapshots."""
    fix = _job(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in (fix.path, fix.reference, fix.scene_path)}
    result = qa.run_job_visual_qa(
        "asset_qa",
        run_id="selected",
        reference_mask_seed_path=fix.artifact.path,
        reference_mask_seed_sha256=fix.artifact.sha256,
    )
    run = Path(result["run_dir"])
    manifest = json.loads((run / "reference_mask_manifest.json").read_text())
    assert (run / "reference_mask_seed_evidence.json").read_bytes() == before[fix.path]
    assert manifest["seed_evidence_source"] == fix.artifact.model_dump(mode="json")
    assert manifest["seed_evidence_snapshot"]["sha256"] == fix.artifact.sha256
    assert manifest["output_mask_metrics"]["foreground_fraction"] == 0.64
    assert all(path.read_bytes() == raw for path, raw in before.items())
    with pytest.raises(FileExistsError):
        qa.run_job_visual_qa(
            "asset_qa",
            run_id="selected",
            reference_mask_seed_path=fix.artifact.path,
            reference_mask_seed_sha256=fix.artifact.sha256,
        )


@pytest.mark.parametrize("mutation", ["seed", "trimap", "extent", "reference", "scope", "subject"])
def test_public_qa_rejects_stale_closure_before_render(tmp_path, monkeypatch, mutation):
    """Bad source selection fails before a run directory or renderer can be invoked."""
    fix = _job(tmp_path, monkeypatch)
    if mutation in {"seed", "trimap", "extent", "reference"}:
        path = {
            "seed": fix.path,
            "trimap": fix.trimap,
            "extent": fix.extent_path,
            "reference": fix.reference,
        }[mutation]
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "scope":
        path = fix.root / "job.json"
        data = json.loads(path.read_text())
        data["reference_content_scope"] = "full_reference"
        path.write_text(json.dumps(data))
    else:
        data = fix.scene.model_dump(mode="json")
        data["objects"][1]["tags"] = ["qa_role:context"]
        fix.scene_path.write_text(SceneSpec.model_validate(data).model_dump_json())
    calls = []
    monkeypatch.setattr(native, "_render_job_qa_passes", lambda *a, **k: calls.append(k))
    with pytest.raises((ValueError, PermissionError)):
        qa.run_job_visual_qa(
            "asset_qa",
            run_id="rejected",
            reference_mask_seed_path=fix.artifact.path,
            reference_mask_seed_sha256=fix.artifact.sha256,
        )
    assert calls == []
    assert not (fix.root / "qa/runs/rejected").exists()


@pytest.mark.parametrize(
    "path,digest",
    [
        ("seeds.json", None),
        (None, "a" * 64),
        ("../seeds.json", "a" * 64),
        ("/tmp/seeds.json", "a" * 64),
        ("seeds.json", "A" * 64),
        ("", "a" * 64),
    ],
)
def test_selection_rejects_unbound_or_escaped_values(path, digest):
    """Require normalized contained paths and a complete lowercase exact digest pair."""
    with pytest.raises(ValueError):
        selection_artifact(path, digest)


def test_selected_seed_symlink_is_rejected(tmp_path, monkeypatch):
    """A local alias cannot bypass no-link evidence containment even when bytes match."""
    fix = _job(tmp_path, monkeypatch)
    link = fix.root / "linked.json"
    link.symlink_to(fix.path)
    with pytest.raises((ValueError, PermissionError)):
        load_reference_mask_selection(
            fix.root,
            fix.reference,
            fix.scene,
            "primary_object_only",
            selection_artifact("linked.json", fix.artifact.sha256),
        )


def test_standard_plan_binds_and_executes_exact_selected_qa(tmp_path, monkeypatch):
    """Native host plans bind scalar inputs and required immutable snapshot outputs."""
    fix = _job(tmp_path, monkeypatch)
    state = _plan(fix)
    request, plan, directory = _contracts(fix, state)
    step = next(step for step in plan.steps if step.step_id == "qa.run")
    assert "reference_mask_seed_path" not in request.model_dump()
    assert step.parameters["reference_mask_scene_spec_sha256"] == sha256_file(fix.scene_path)
    assert step.parameters["reference_mask_seed_sha256"] == fix.artifact.sha256
    assert {"qa.run.seed_evidence", "qa.run.subject_extent", "qa.run.trimap"} <= {
        item.artifact_id for item in step.outputs
    }
    workflow._execute_host_tool(fix.root, directory, request, step, input_fingerprint="a" * 64)
    for requirement in step.outputs:
        assert (fix.root / requirement.path).is_file()
    assert not (directory / "approvals").exists()


def test_standard_rejects_changed_scene_before_qa(tmp_path, monkeypatch):
    """An opt-in QA-only continuation cannot silently follow a later source revision."""
    fix = _job(tmp_path, monkeypatch)
    request, plan, directory = _contracts(fix, _plan(fix))
    step = next(step for step in plan.steps if step.step_id == "qa.run")
    fix.scene_path.write_bytes(fix.scene_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="evidence changed"):
        workflow._execute_host_tool(fix.root, directory, request, step, input_fingerprint="a" * 64)
    assert not (fix.root / "qa/runs" / step.parameters["run_id"]).exists()


@pytest.mark.parametrize(
    "intent,scope,policy",
    [
        ("auto", "qa_only", "standard"),
        ("visual_qa", "auto", "standard"),
        ("visual_qa", "full", "standard"),
        ("revise_asset", "qa_only", "standard"),
        ("visual_qa", "qa_only", "background_exterior"),
    ],
)
def test_host_planner_rejects_other_routes(tmp_path, monkeypatch, intent, scope, policy):
    """Explicit source evidence is limited to a fresh QA-only continuation of an existing job."""
    fix = _job(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Standard visual_qa/qa_only"):
        workflow.plan_workflow(
            "QA",
            job_id="asset_qa",
            intent=intent,
            scope=scope,
            execution_policy=policy,
            reference_mask_seed_path=fix.artifact.path,
            reference_mask_seed_sha256=fix.artifact.sha256,
        )
    assert not (fix.root / "workflows").exists()


@pytest.mark.parametrize("surface", ["qa", "cli_qa", "mcp_qa", "cli_plan", "mcp_plan"])
def test_public_surfaces_forward_exact_pair(monkeypatch, surface):
    """CLI, MCP, and lazy Python wrappers preserve exact explicit opt-in values."""
    calls = []

    def capture(*args, **kwargs):
        """Capture boundary values without executing work or creating approval evidence."""
        calls.append(kwargs)
        return (
            SimpleNamespace(model_dump=lambda **k: {}, model_dump_json=lambda: "{}")
            if surface.endswith("plan")
            else {}
        )

    pair = {"reference_mask_seed_path": "seeds.json", "reference_mask_seed_sha256": "a" * 64}
    if surface == "qa":
        monkeypatch.setattr(native, "run_job_visual_qa", capture)
        qa.run_job_visual_qa("asset", **pair)
    elif surface == "mcp_qa":
        monkeypatch.setattr(mcp_server, "run_job_visual_qa", capture)
        mcp_server.run_visual_qa("asset", **pair)
    elif surface == "mcp_plan":
        monkeypatch.setattr(mcp_server, "plan_workflow_internal", capture)
        mcp_server.plan_short_workflow("QA", **pair)
    else:
        name = "run_job_visual_qa" if surface == "cli_qa" else "plan_orchestrated_workflow"
        monkeypatch.setattr(cli, name, capture)
        args = (
            ["visual-qa", "asset"] if surface == "cli_qa" else ["workflow-plan", "--request", "QA"]
        )
        result = CliRunner().invoke(
            cli.app,
            args
            + [
                "--reference-mask-seed-path",
                "seeds.json",
                "--reference-mask-seed-sha256",
                "a" * 64,
            ],
        )
        assert result.exit_code == 0, result.output
    assert all(calls[0][key] == value for key, value in pair.items())


def test_cli_mcp_pair_discoverability_and_schema_compatibility():
    """Expose paired controls without introducing unversioned WorkflowRequest/plan defaults."""
    for name in ("visual-qa", "workflow-plan"):
        command = get_command(cli.app).commands[name]
        options = {option for param in command.params for option in getattr(param, "opts", [])}
        assert {"--reference-mask-seed-path", "--reference-mask-seed-sha256"} <= options
    for function in (
        qa.run_job_visual_qa,
        mcp_server.run_visual_qa,
        mcp_server.plan_short_workflow,
    ):
        assert inspect.signature(function).parameters["reference_mask_seed_path"].default is None
    for model in (WorkflowRequest, WorkflowPlan):
        assert "reference_mask_seed_path" not in model.model_fields


def _legacy_contracts(monkeypatch):
    """Build a fixed legacy QA plan whose exact serialization predates this opt-in."""
    from datetime import UTC, datetime

    from codex_blender_modeler.orchestration.models import (
        DestinationRequest,
        DestinationResolution,
        IntentRouting,
    )

    class FixedTime:
        """Return one deterministic plan timestamp for byte compatibility fixtures."""

        @staticmethod
        def now(_timezone):
            """Preserve the exact baseline serialization timestamp."""
            return datetime(2026, 9, 30, tzinfo=UTC)

    monkeypatch.setattr(planner, "datetime", FixedTime)
    request = WorkflowRequest(
        workflow_id="wf-legacy-qa",
        job_id="legacy_asset",
        raw_request="QA",
        intent_hint="visual_qa",
        requested_scope="qa_only",
        delivery_scope="preview_only",
        created_at=FixedTime.now(UTC),
    )
    routing = IntentRouting(
        workflow_id=request.workflow_id,
        job_id=request.job_id,
        intent="visual_qa",
        delivery_scope="preview_only",
        confidence=1.0,
        reasons=["Exact fixture"],
        destination=DestinationResolution(
            requested=DestinationRequest(), status="not_requested", reason="No destination"
        ),
        routed_at=FixedTime.now(UTC),
    )
    plan = planner.build_workflow_plan(
        request, routing, request_sha256="a" * 64, routing_sha256="b" * 64
    )
    return request, routing, plan


def test_absent_selection_preserves_exact_request_and_plan_bytes(monkeypatch):
    """No opt-in preserves baseline full serialized model hashes, not merely field absence."""
    request, _, plan = _legacy_contracts(monkeypatch)
    assert (
        hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        == "2860c5745f7fc4cdda1f092896bde33a4b0166ead136d47f0de73c0a08062cb9"
    )
    assert (
        hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
        == "9089993df7d487674f05bbbcf7afd4395b00606781b64647566536526dc8e2e0"
    )


@pytest.mark.parametrize("mutation", ["seed", "scene"])
def test_pending_selection_is_blocked_but_completed_qa_is_historical(
    tmp_path, monkeypatch, mutation
):
    """Pending scope drift blocks execution while complete run snapshots retain their meaning."""
    fix = _job(tmp_path, monkeypatch)
    state = _plan(fix)
    request, plan, directory = _contracts(fix, state)
    workflow.resume_workflow("asset_qa", state.workflow_id, max_host_steps=1)
    old = (directory / "plan.json").read_bytes()
    target = fix.path if mutation == "seed" else fix.scene_path
    initial = target.read_bytes()
    target.write_bytes(initial + b" ")
    blocked = workflow.reconcile_workflow("asset_qa", state.workflow_id)
    qa_state = next(step for step in blocked.steps if step.step_id == "qa.run")
    assert qa_state.status == "blocked"
    assert "source-evidence binding" in qa_state.error
    assert not list((fix.root / "qa/runs").iterdir())
    # Return this test-only input to its original bytes, then create a separate fresh plan.
    target.write_bytes(initial)
    fresh = _plan(fix)
    completed = workflow.resume_workflow("asset_qa", fresh.workflow_id, max_host_steps=2)
    assert next(step for step in completed.steps if step.step_id == "qa.run").status == "complete"
    target.write_bytes(initial + b" ")
    reread = workflow.reconcile_workflow("asset_qa", fresh.workflow_id)
    assert next(step for step in reread.steps if step.step_id == "qa.run").status == "complete"
    assert (directory / "plan.json").read_bytes() == old


def test_selected_evidence_changed_during_render_is_not_published(tmp_path, monkeypatch):
    """A renderer-time source change cannot publish a mask, score, or successful run receipt."""
    fix = _job(tmp_path, monkeypatch)
    renderer = native._render_job_qa_passes

    def change_seed(*args, **kwargs):
        """Simulate source drift after the original preflight and exact render pass creation."""
        result = renderer(*args, **kwargs)
        fix.path.write_bytes(fix.path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(native, "_render_job_qa_passes", change_seed)
    with pytest.raises(ValueError, match="evidence changed"):
        qa.run_job_visual_qa(
            "asset_qa",
            run_id="race",
            reference_mask_seed_path=fix.artifact.path,
            reference_mask_seed_sha256=fix.artifact.sha256,
        )
    run = fix.root / "qa/runs/race"
    assert (run / "render_pass_manifest.json").is_file()
    assert not (run / "reference_mask.png").exists()
    assert not (run / "visual_qa_report.json").exists()
    assert not (fix.root / "qa/latest.json").exists()


def test_no_discovery_does_not_bypass_partial_scope_guard(tmp_path, monkeypatch):
    """Having valid V0.3 artifacts on disk cannot opt a legacy QA call into them."""
    fix = _job(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="reference mask scope is unscorable"):
        qa.run_job_visual_qa("asset_qa", run_id="legacy")
    assert not (fix.root / "qa/runs/legacy/visual_qa_report.json").exists()
