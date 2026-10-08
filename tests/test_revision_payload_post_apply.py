"""Post-apply guarded sources stay exact until all pending derivations finish."""

from __future__ import annotations

import json

import pytest
from test_revision_payload_binding import _approve, _complete, _fixture, _write

from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.orchestration import service
from codex_blender_modeler.orchestration.revision_payloads import BINDING_PARAMETER, binding_path


def _applied(tmp_path, monkeypatch, *, legacy=False, spatial=False):
    """Use only disposable synthetic fixture approval and the real guarded apply path."""

    root, state = _fixture(tmp_path, monkeypatch)
    if spatial:
        path = root / "analysis/modeling_plan.json"
        modeling = json.loads(path.read_bytes())
        modeling["objects"][0].update(scope_role="primary", assembly_role="root")
        modeling.update(
            assembly_consistency_policy="spatial_v1",
            assembly_frame={
                "root_object_id": "asset.cube", "longitudinal_axis": "X",
                "lateral_axis": "Y", "vertical_axis": "Z", "symmetry": "unknown",
                "evidence_status": "inferred",
            },
            assembly_relationships=[],
        )
        _write(path, modeling)
        state = service.plan_workflow(
            "Revise this exact spatial fixture.", job_id=root.name, intent="revise_asset",
            revision_strategy="manual_guarded",
        )
    if legacy:
        path = root / "workflows" / state.workflow_id / "plan.json"
        plan = json.loads(path.read_bytes())
        for step in plan["steps"]:
            step["parameters"].pop(BINDING_PARAMETER, None)
            step["outputs"] = [
                item for item in step["outputs"]
                if item["artifact_id"] != "revision.payload_binding"
            ]
        _write(path, plan)
        state = service.reconcile_workflow(root.name, state.workflow_id)
    state = _approve(root, _complete(root, state))
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(
        item.status for item in state.steps if item.step_id == "revision.apply"
    ) == "complete"
    return root, state


def _derived_outputs(monkeypatch, calls):
    """Stub Blender/report work only; real host receipts, snapshots and guards still execute."""

    def execute(root, _workflow_root, _request, step, *, input_fingerprint):
        """Publish deterministic synthetic outputs for one derived host step."""
        calls.append(step.step_id)
        for output in step.outputs:
            path = root / (output.source_path or output.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"ok": true}\n' if path.suffix == ".json" else b"fixture output\n")

    monkeypatch.setattr(service, "_execute_host_tool", execute)
    return execute


def _mutate_payload(root):
    """Change actual geometry while keeping the candidate path and payload schema valid."""

    path = root / "geometry/new.json"
    payload = json.loads(path.read_bytes())
    payload["vertices"][0][0] += 0.025
    _write(path, payload)


@pytest.mark.parametrize(
    "completed,target",
    [(0, "revision.build"), (1, "revision.render"), (2, "revision.inspect"),
     (3, "revision.validate"), (4, "revision.report")],
)
def test_payload_drift_blocks_every_pending_derived_step(tmp_path, monkeypatch, completed, target):
    """Keep completed receipts historical while blocking changed bytes before the next host call."""

    root, state = _applied(tmp_path, monkeypatch)
    calls = []
    _derived_outputs(monkeypatch, calls)
    if completed:
        state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=completed)
    assert state.current_step_id == target
    workflow = root / "workflows" / state.workflow_id
    receipts = {path: path.read_bytes() for path in (workflow / "attempts").glob("**/*.json")}
    canonical = (root / "analysis/scene_spec.json").read_bytes()
    _mutate_payload(root)
    call_count = len(calls)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert state.status == "blocked" and state.current_step_id == target
    assert state.reason_code == "orchestration_artifact_conflict"
    assert len(calls) == call_count
    assert next(
        item.status for item in state.steps if item.step_id == "revision.apply"
    ) == "complete"
    assert all(path.read_bytes() == content for path, content in receipts.items())
    assert (root / "analysis/scene_spec.json").read_bytes() == canonical


def test_approved_unchanged_flow_and_completed_history_remain_valid(tmp_path, monkeypatch):
    """The happy path finishes and later source work does not reclassify completed history."""

    root, state = _applied(tmp_path, monkeypatch)
    calls = []
    _derived_outputs(monkeypatch, calls)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=16)
    assert state.status == "completed"
    assert calls == ["revision.build", "revision.render", "revision.inspect", "revision.validate",
                     "revision.report"]
    workflow = root / "workflows" / state.workflow_id
    receipts = {path: path.read_bytes() for path in (workflow / "attempts").glob("**/*.json")}
    _mutate_payload(root)
    assert service.reconcile_workflow(root.name, state.workflow_id).status == "completed"
    assert all(path.read_bytes() == content for path, content in receipts.items())


def test_old_unbound_workflow_keeps_its_original_behavior(tmp_path, monkeypatch):
    """An immutable historical plan without the opt-in does not gain a new source contract."""

    root, state = _applied(tmp_path, monkeypatch, legacy=True)
    calls = []
    _derived_outputs(monkeypatch, calls)
    _mutate_payload(root)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=16)
    assert state.status == "completed" and calls[0] == "revision.build"
    assert not binding_path(root, state.workflow_id).exists()


@pytest.mark.parametrize("when", ["before_host", "during_host"])
def test_host_boundary_rechecks_drift_without_success_receipt(tmp_path, monkeypatch, when):
    """A race after reconciliation or during derivation cannot publish a successful receipt."""

    root, state = _applied(tmp_path, monkeypatch)
    calls = []
    execute = _derived_outputs(monkeypatch, calls)
    if when == "before_host":
        original = service._verify_dependency_sources

        def sources(*args, **kwargs):
            """Mutate only after the host has passed its ordinary source-snapshot check."""
            original(*args, **kwargs)
            _mutate_payload(root)

        monkeypatch.setattr(service, "_verify_dependency_sources", sources)
    else:
        def changed(*args, **kwargs):
            """Mutate an external source while the derived tool is running."""
            execute(*args, **kwargs)
            _mutate_payload(root)

        monkeypatch.setattr(service, "_execute_host_tool", changed)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert state.status == "blocked"
    assert bool(calls) == (when == "during_host")
    attempts = root / "workflows" / state.workflow_id / "attempts/revision.build"
    receipts = [json.loads(path.read_bytes()) for path in attempts.glob("*.json")]
    assert receipts and all(item["status"] == "failed" for item in receipts)
    assert all(item["reason_code"] == "orchestration_artifact_conflict" for item in receipts)


def test_rehashed_binding_cannot_hide_drift_during_host(tmp_path, monkeypatch):
    """Current matching source hashes cannot replace the completed author's approved binding."""

    root, state = _applied(tmp_path, monkeypatch)
    calls = []
    execute = _derived_outputs(monkeypatch, calls)

    def changed(*args, **kwargs):
        """Simulate concurrent replacement of both a payload and its claimed dependency hash."""
        execute(*args, **kwargs)
        _mutate_payload(root)
        path = binding_path(root, state.workflow_id)
        binding = json.loads(path.read_bytes())
        binding["geometry_dependencies"]["geometry/new.json"] = sha256_file(
            root / "geometry/new.json"
        )
        _write(path, binding)

    monkeypatch.setattr(service, "_execute_host_tool", changed)
    result = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert result.status == "blocked" and result.current_step_id == "revision.build"
    attempts = root / "workflows" / state.workflow_id / "attempts/revision.build"
    assert all(
        json.loads(path.read_bytes())["status"] == "failed" for path in attempts.glob("*.json")
    )


def test_spatial_multiview_is_a_guarded_post_apply_descendant(tmp_path, monkeypatch):
    """The native spatial planner's multiview host cannot run with changed approved geometry."""

    root, state = _applied(tmp_path, monkeypatch, spatial=True)
    calls = []
    _derived_outputs(monkeypatch, calls)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=4)
    assert state.current_step_id == "revision.geometry_multiview"
    _mutate_payload(root)
    count = len(calls)
    result = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert result.status == "blocked" and result.current_step_id == "revision.geometry_multiview"
    assert len(calls) == count


@pytest.mark.parametrize("when", ["before_completion", "during_completion", "unchanged"])
def test_spatial_agent_completion_retains_exact_payload_contract(tmp_path, monkeypatch, when):
    """Mock visual-review contents only; completion must still retain approved source bytes."""

    root, state = _applied(tmp_path, monkeypatch, spatial=True)
    calls = []
    _derived_outputs(monkeypatch, calls)
    original_validate = service._validate_known_json_contract

    def validate(job_root, requirement, payload):
        """Keep real source validation while isolating the multiview visual-contract fixture."""
        if ".geometry_multiview." not in requirement.artifact_id:
            original_validate(job_root, requirement, payload)

    monkeypatch.setattr(service, "_validate_known_json_contract", validate)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=5)
    step_id = "revision.geometry_multiview_visual_review"
    assert state.current_step_id == step_id and state.status == "waiting_for_agent"
    workflow = root / "workflows" / state.workflow_id
    raw = json.loads((workflow / "plan.json").read_bytes())
    step = next(item for item in raw["steps"] if item["step_id"] == step_id)
    for output in step["outputs"]:
        _write(root / output["path"], {"ok": True, "fixture_only": True})
    fingerprint = next(item.input_fingerprint for item in state.steps if item.step_id == step_id)
    if when == "before_completion":
        _mutate_payload(root)
    elif when == "during_completion":
        original_semantics = service._validate_agent_completion_semantics

        def semantics(job_root, current, request):
            """Mutate only at the final semantic-check boundary before marker publication."""
            original_semantics(job_root, current, request)
            if current.step_id == step_id:
                _mutate_payload(root)

        monkeypatch.setattr(service, "_validate_agent_completion_semantics", semantics)
    if when == "unchanged":
        result = service.complete_workflow_step(
            root.name, state.workflow_id, step_id, input_fingerprint=fingerprint,
            note="Synthetic contract test only; no visual quality approval.",
        )
        assert result.current_step_id == "revision.report"
        assert service.resume_workflow(
            root.name, state.workflow_id, max_host_steps=1
        ).status == "completed"
    else:
        with pytest.raises(service.OrchestrationArtifactConflict):
            service.complete_workflow_step(
                root.name, state.workflow_id, step_id, input_fingerprint=fingerprint,
                note="Synthetic contract test only; no visual quality approval.",
            )
        assert not (workflow / "completions" / f"{step_id}.json").exists()
