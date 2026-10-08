"""Fail-closed exact backend selection and native swatch-attempt integration tests."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from typer.main import get_command

import codex_blender_modeler.orchestration.service as service
import codex_blender_modeler.orchestration.swatch_execution as execution
from codex_blender_modeler.blender_artifacts import write_json_atomic
from codex_blender_modeler.orchestration.models import WorkflowAttempt, WorkflowStep
from codex_blender_modeler.workspace import sha256_file


@pytest.fixture
def case(tmp_path, monkeypatch):
    """Create minimal native attempt inputs with deterministic recursive source evidence."""

    root = tmp_path / "swatch_asset"
    workflow = root / "workflows/wf-swatches"
    workflow.mkdir(parents=True)
    (workflow / "plan.json").write_text('{}\n')
    (workflow / "request.json").write_text('{"request":true}\n')
    (root / "blender").mkdir()
    (root / "blender/scene.blend").write_bytes(b"fixture blend")
    (root / "analysis").mkdir()
    (root / "analysis/material_plan.json").write_text('{}\n')
    step = WorkflowStep(step_id="material.swatches", title="Fixed swatches", phase="material",
                        execution_mode="host", tool_name="render_material_swatches", outputs=[{
                            "artifact_id": "material.swatch_manifest",
                            "path": "workflows/wf-swatches/artifacts/swatches.json",
                            "source_path": "reports/material_swatches.json",
                            "lifecycle": "workflow_snapshot", "acceptance": "valid_json",
                        }])
    plan = SimpleNamespace(job_id=root.name, workflow_id="wf-swatches", steps=[step],
                           request_sha256=sha256_file(workflow / "request.json"))
    current = SimpleNamespace(step_id=step.step_id, status="ready", input_fingerprint="a" * 64,
                              attempt_count=0)
    state = SimpleNamespace(current_step_id=step.step_id, steps=[current],
                            plan_sha256=sha256_file(workflow / "plan.json"))

    def source_evidence(_root):
        """Provide fresh fixture file hashes on every before/after source check."""

        hashes = {p: sha256_file(root / p) for p in (
            "blender/scene.blend", "analysis/material_plan.json"
        )}
        return {"fingerprint": "b" * 64}, hashes, ["amber", "metal"]

    monkeypatch.setattr(execution, "source_evidence", source_evidence)
    return SimpleNamespace(root=root, workflow=workflow, step=step, plan=plan,
                           state=state, current=current, previous=None)


def selection(case, **updates):
    """Resolve one exact fresh or failed selection using the public selection validator."""

    args = dict(backend="cycles_cpu", input_fingerprint="a" * 64,
                failed_attempt_sha256=None, retry_failed=False)
    args.update(updates)
    return execution.validate_selection(case.root, case.workflow, case.plan, case.previous,
                                        case.state, **args)


def failed_attempt(case, *, ordinal=1, **updates):
    """Persist an ordinary exact failed attempt without altering its history later."""

    now = datetime.now(UTC)
    args = dict(attempt_id=f"attempt-{ordinal:04d}-1234abcd", job_id=case.root.name,
                workflow_id=case.plan.workflow_id, step_id=case.step.step_id,
                plan_sha256=case.state.plan_sha256, input_fingerprint="a" * 64,
                status="failed", error_type="BlenderRunError", error_message="EGL_BAD_MATCH",
                reason_code="host_failure", started_at=now, completed_at=now)
    args.update(updates)
    receipt = WorkflowAttempt(**args)
    path = case.workflow / "attempts/material.swatches" / f"{receipt.attempt_id}.json"
    write_json_atomic(path, receipt.model_dump(mode="json"))
    case.previous = SimpleNamespace(status="failed", current_step_id=case.step.step_id)
    case.current.attempt_count = ordinal
    return path


def fake_renderer(_script, args, **_kwargs):
    """Produce fixed actual PNG fixture bytes through the same declared output inventory."""

    output = Path(args[args.index("--output-dir") + 1])
    manifest_path = Path(args[args.index("--manifest") + 1])
    records = []
    for material_id in ("amber", "metal"):
        path = output / material_id / "swatch.png"
        path.parent.mkdir(parents=True)
        Image.new("RGBA", (512, 512), (100, 140, 120, 255)).save(path)
        records.append(dict(material_id=material_id, path=str(path), sha256=sha256_file(path),
                            width=512, height=512, encoding="png-rgba8"))
    write_json_atomic(manifest_path, dict(job_id="swatch_asset", render_engine="CYCLES",
                                         render_device="CPU", resolution=[512, 512],
                                         build_fingerprint="b" * 64, material_count=2,
                                         source_material_count=2, swatches=records))


def test_fresh_exact_selection_and_legacy_defaults(case):
    """Ready selection is explicit and legacy calls produce no selection or model changes."""

    chosen = selection(case)
    assert chosen["backend"] == "cycles_cpu"
    assert chosen["failed_attempt_path"] is None
    assert execution.validate_selection(case.root, case.workflow, case.plan, None, case.state,
                                        backend=None, input_fingerprint=None,
                                        failed_attempt_sha256=None, retry_failed=False) is None
    assert "backend" not in WorkflowAttempt.model_fields


@pytest.mark.parametrize("updates", [
    {"backend": "cycles_gpu"}, {"backend": "CYCLES"}, {"backend": "shell"},
    {"input_fingerprint": None}, {"input_fingerprint": "f" * 64},
    {"backend": None}, {"retry_failed": True}, {"failed_attempt_sha256": "f" * 64},
])
def test_ready_selection_rejects_unbound_or_unsupported_arguments(case, updates):
    """A backend is a strict execution choice, never arbitrary parameters or retry authority."""

    with pytest.raises(ValueError):
        selection(case, **updates)


@pytest.mark.parametrize("field,value", [("current_step_id", "material.inspect"),
                                         ("status", "complete"), ("status", "blocked")])
def test_selection_rejects_wrong_or_terminal_step(case, field, value):
    """Selection cannot bypass a predecessor, adopt a terminal, or recover scope blocking."""

    setattr(case.state if field == "current_step_id" else case.current, field, value)
    with pytest.raises(ValueError):
        selection(case)


def test_retry_requires_latest_exact_failed_receipt_and_explicit_flag(case):
    """The selection binds the newest ordinary failure and preserves the prior receipt bytes."""

    first = failed_attempt(case)
    original = first.read_bytes()
    with pytest.raises(ValueError):
        selection(case)
    chosen = selection(case, retry_failed=True, failed_attempt_sha256=sha256_file(first))
    assert chosen["failed_attempt_path"] == first.relative_to(case.root).as_posix()
    failed_attempt(case, ordinal=2)
    with pytest.raises(ValueError):
        selection(case, retry_failed=True, failed_attempt_sha256=sha256_file(first))
    assert first.read_bytes() == original


@pytest.mark.parametrize("updates", [
    {"input_fingerprint": "f" * 64}, {"plan_sha256": "f" * 64},
    {"workflow_id": "wf-other"}, {"job_id": "other_job"},
    {"reason_code": "orchestration_artifact_conflict"},
    {"error_type": "OrchestrationArtifactConflict"},
])
def test_retry_rejects_wrong_identity_scope_or_artifact_failure(case, updates):
    """A technical renderer choice never grants stale-input or scope-conflict authority."""

    path = failed_attempt(case, **updates)
    with pytest.raises(ValueError):
        selection(case, retry_failed=True, failed_attempt_sha256=sha256_file(path))


def test_native_attempt_success_keeps_failure_and_publishes_true_backend(case, monkeypatch):
    """Native attempt creation retains failed history and binds fresh Cycles CPU artifacts."""

    old = failed_attempt(case)
    old_bytes = old.read_bytes()
    chosen = selection(case, retry_failed=True, failed_attempt_sha256=sha256_file(old))
    monkeypatch.setattr(execution, "run_blender", fake_renderer)
    attempt = service._execute_ready_host_step(case.root, case.workflow, SimpleNamespace(),
                                               case.plan, case.state, case.step,
                                               swatch_selection=chosen)
    assert attempt.status == "succeeded"
    assert old.read_bytes() == old_bytes
    manifest = json.loads((case.root / "reports/material_swatches.json").read_bytes())
    assert manifest["render_engine"] == "CYCLES"
    assert manifest["render_device"] == "CPU"
    execution.validate_manifest(case.root, manifest)
    assert len(list((case.workflow / "attempts/material.swatches").glob("*.json"))) == 2


@pytest.mark.parametrize("mutation", ["source", "dependency", "wrong_engine", "incomplete", "png"])
def test_render_failure_never_publishes_success_or_canonical_manifest(case, monkeypatch, mutation):
    """Source races, incomplete coverage and deceptive output metadata fail before publication."""

    chosen = selection(case)
    dependency = case.root / "reports/prerequisite.json"
    dependency.parent.mkdir(exist_ok=True)
    dependency.write_text('{"ok": true}')
    chosen["dependency_sha256"] = {"reports/prerequisite.json": sha256_file(dependency)}

    def bad_renderer(script, args, **kwargs):
        """Mutate one bound source or rendered result after the fixed renderer fixture."""

        fake_renderer(script, args, **kwargs)
        manifest_path = Path(args[args.index("--manifest") + 1])
        manifest = json.loads(manifest_path.read_bytes())
        if mutation == "source":
            (case.root / "analysis/material_plan.json").write_text('{"changed":true}')
        elif mutation == "dependency":
            dependency.write_text('{"changed":true}')
        elif mutation == "wrong_engine":
            manifest["render_engine"] = "BLENDER_EEVEE"
        elif mutation == "incomplete":
            manifest["swatches"].pop()
        else:
            path = Path(manifest["swatches"][0]["path"])
            path.write_text("not a PNG")
            manifest["swatches"][0]["sha256"] = sha256_file(path)
        write_json_atomic(manifest_path, manifest)

    monkeypatch.setattr(execution, "run_blender", bad_renderer)
    with pytest.raises((ValueError, OSError)):
        service._execute_ready_host_step(case.root, case.workflow, SimpleNamespace(),
                                        case.plan, case.state, case.step, swatch_selection=chosen)
    assert not (case.root / "reports/material_swatches.json").exists()
    attempts = list((case.workflow / "attempts/material.swatches").glob("*.json"))
    assert len(attempts) == 1
    assert json.loads(attempts[0].read_bytes())["status"] == "failed"


def test_manifest_rejects_tamper_and_linked_output(case, monkeypatch):
    """Immutable selection and PNG tampering cannot be accepted by workflow reconciliation."""

    monkeypatch.setattr(execution, "run_blender", fake_renderer)
    chosen = execution.MaterialSwatchExecution(job_id=case.root.name, workflow_id="wf-swatches",
                                              attempt_id="attempt-0001-1234abcd", **selection(case))
    execution.execute_selection(case.root, chosen)
    manifest = json.loads((case.root / "reports/material_swatches.json").read_bytes())
    path = case.root / manifest["swatches"][0]["path"]
    path.write_bytes(b"changed")
    with pytest.raises(ValueError):
        execution.validate_manifest(case.root, manifest)
    path.unlink()
    path.symlink_to(case.root / manifest["swatches"][1]["path"])
    with pytest.raises(ValueError, match="symlink"):
        execution.validate_manifest(case.root, manifest)


def test_schema_cli_mcp_and_internal_surface_parity():
    """Expose exactly the same additive options while retaining default API values."""

    from codex_blender_modeler.cli import app
    from codex_blender_modeler.mcp_server import resume_short_workflow

    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas/material_swatch_execution.schema.json").read_bytes())
    assert schema == execution.MaterialSwatchExecution.model_json_schema()
    assert schema["additionalProperties"] is False
    cli = get_command(app).commands["workflow-resume"]
    names = {p.name for p in cli.params}
    for option in ("material_swatch_backend", "material_swatch_input_fingerprint",
                   "material_swatch_failed_attempt_sha256"):
        assert option in names
        assert inspect.signature(resume_short_workflow).parameters[option].default is None
        assert inspect.signature(service.resume_workflow).parameters[option].default is None
