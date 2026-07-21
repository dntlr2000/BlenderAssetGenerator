from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

import codex_blender_modeler.orchestration.service as orchestration_service
from codex_blender_modeler.orchestration.locks import (
    acquire_workflow_lock,
    release_workflow_lock,
    write_expired_lock_for_test,
)
from codex_blender_modeler.orchestration.models import WorkflowAttempt
from codex_blender_modeler.orchestration.service import (
    approve_workflow_gate,
    cancel_workflow,
    complete_workflow_step,
    destination_adapters,
    plan_workflow,
    reconcile_workflow,
    resume_workflow,
)
from codex_blender_modeler.workspace import create_job, job_dir, sha256_file

ROOT = Path(__file__).resolve().parents[1]


def _image(path: Path, color: tuple[int, int, int] = (60, 110, 170)) -> Path:
    """Create one small deterministic RGB reference fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 32), color).save(path)
    return path


def _new_proxy_workflow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Plan and analyze one isolated proxy workflow for marker/approval tests."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "reference.png")
    state = plan_workflow(
        "이 이미지로 정적 3D 프록시 모델을 만들어줘",
        job_id="workflow_asset",
        reference_path=reference,
    )
    state = resume_workflow("workflow_asset", state.workflow_id, max_host_steps=1)
    return workspace / "workflow_asset", state


def _author_modeling_plan(root: Path, state) -> None:
    """Promote the deterministic scaffold to one schema-valid authored modeling plan."""

    path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["objects"] = [
        {
            "id": "asset.body",
            "label": "body",
            "recommended_geometry": "primitive",
            "source_ids": ["reference"],
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "observed": True,
            "confidence": 0.8,
            "notes": [],
        }
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = next(
        item for item in state.steps if item.step_id == "geometry.modeling_plan"
    )
    assert current.input_fingerprint


def _complete_modeling_plan(root: Path, state):
    """Record the exact agent marker for the authored modeling plan."""

    _author_modeling_plan(root, state)
    current = next(
        item for item in state.steps if item.step_id == "geometry.modeling_plan"
    )
    return complete_workflow_step(
        "workflow_asset",
        state.workflow_id,
        "geometry.modeling_plan",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored one observed semantic object from the reference.",
    )


def _complete_proxy_scene(root: Path, state):
    """Write one valid SceneSpec and bind it to the waiting proxy-author step."""

    seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    seed["job_id"] = "workflow_asset"
    scene_spec = root / "analysis" / "scene_spec.json"
    scene_spec.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    current = next(
        item for item in state.steps if item.step_id == "geometry.proxy_author"
    )
    assert current.input_fingerprint
    return complete_workflow_step(
        "workflow_asset",
        state.workflow_id,
        "geometry.proxy_author",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored a schema-valid deterministic proxy SceneSpec.",
    )


def test_new_short_request_creates_isolated_proxy_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A new image creates one lowercase job and stops before agent judgment."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    assert state.status == "waiting_for_agent"
    assert state.current_step_id == "geometry.modeling_plan"
    assert state.milestone == "analyzed"
    workflow = root / "workflows" / state.workflow_id
    assert (workflow / "request.json").is_file()
    assert (workflow / "routing.json").is_file()
    assert (workflow / "plan.json").is_file()
    plan = json.loads((workflow / "plan.json").read_text(encoding="utf-8"))
    step_ids = [item["step_id"] for item in plan["steps"]]
    assert step_ids.index("proxy.report") < step_ids.index("geometry.proxy_approval")
    report = next(item for item in plan["steps"] if item["step_id"] == "proxy.report")
    assert report["tool_name"] == "generate_pdf_report"
    assert report["outputs"][0]["path"] == "reports/pdf/proxy_report.pdf"
    request_text = (workflow / "request.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in request_text
    assert "input/reference.png" in request_text


def test_analysis_scaffold_is_valid_but_not_agent_complete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep a valid analyzer scaffold distinct from an authored agent completion."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    step = next(item for item in state.steps if item.step_id == "geometry.modeling_plan")
    assert step.status == "waiting_for_agent"
    assert step.artifacts[0].integrity == "valid"
    assert step.artifacts[0].verification == "partially_verified"
    assert step.input_fingerprint
    with pytest.raises(RuntimeError, match="stage=authored"):
        complete_workflow_step(
            "workflow_asset",
            state.workflow_id,
            "geometry.modeling_plan",
            input_fingerprint=step.input_fingerprint,
            note="A scaffold must not be accepted as authored.",
        )
    assert not (root / "workflows" / state.workflow_id / "completions").exists()


def test_existing_job_rejects_different_primary_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A different asset cannot silently reuse an existing job ID."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    first = _image(tmp_path / "first.png", (10, 20, 30))
    second = _image(tmp_path / "second.png", (220, 210, 200))
    create_job("existing_asset", first, "concept", [])
    before = (workspace / "existing_asset" / "job.json").read_bytes()
    with pytest.raises(FileExistsError, match="cannot be reused"):
        plan_workflow(
            "이 이미지로 다시 만들어줘",
            job_id="existing_asset",
            reference_path=second,
        )
    assert (workspace / "existing_asset" / "job.json").read_bytes() == before
    assert not (workspace / "existing_asset" / "workflows" / "latest.json").exists()


def test_existing_job_rejects_explicit_new_asset_with_matching_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Force existing assets through revision even when the reference hash matches."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = _image(tmp_path / "reference.png", (30, 90, 160))
    create_job("existing_asset", reference, "concept", [])
    root = workspace / "existing_asset"
    before = (root / "job.json").read_bytes()
    with pytest.raises(FileExistsError, match="Use revise_asset"):
        plan_workflow(
            "같은 레퍼런스로 새 자산 생성을 다시 시작해줘",
            job_id="existing_asset",
            reference_path=reference,
            intent="new_asset",
        )
    assert (root / "job.json").read_bytes() == before
    assert list((root / "workflows").iterdir()) == []


def test_add_view_resume_promotes_staged_input_and_reanalyzes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Measured-view routing uses add_view and completes deterministic reanalysis."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    front = _image(tmp_path / "front.png", (180, 80, 40))
    create_job("measured_asset", primary, "measured", ["width = 2 m"])
    state = plan_workflow(
        "정면도를 추가해서 다시 분석해줘",
        job_id="measured_asset",
        reference_path=front,
        view_kind="front",
        mode="measured",
    )
    assert state.current_step_id == "view.add"
    finished = resume_workflow("measured_asset", state.workflow_id, max_host_steps=2)
    root = workspace / "measured_asset"
    assert finished.status == "completed"
    assert (root / "input" / "front.png").is_file()
    assert (root / "analysis" / "reference_analysis.json").is_file()
    metadata = json.loads((root / "job.json").read_text(encoding="utf-8"))
    assert {item["kind"] for item in metadata["sources"]} == {"reference", "front"}


def test_agent_completion_and_generic_approval_are_exactly_hash_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Agent markers and proxy approval reject stale or guessed fingerprints."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    state = _complete_modeling_plan(root, state)
    assert state.current_step_id == "geometry.proxy_author"
    state = _complete_proxy_scene(root, state)
    assert state.current_step_id == "proxy.build"
    (root / "blender").mkdir(exist_ok=True)
    (root / "blender" / "scene.blend").write_bytes(b"workflow-blend")
    (root / "renders").mkdir(exist_ok=True)
    (root / "renders" / "preview.png").write_bytes(b"workflow-preview")
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "scene_inventory.json").write_text(
        '{"job_id":"workflow_asset","objects":[]}\n',
        encoding="utf-8",
    )
    (root / "reports" / "validation.json").write_text(
        '{"ok":true,"errors":[],"warnings":[]}\n',
        encoding="utf-8",
    )
    state = reconcile_workflow("workflow_asset", state.workflow_id)
    assert state.current_step_id == "proxy.report"
    state = resume_workflow("workflow_asset", state.workflow_id, max_host_steps=1)
    assert state.status == "waiting_for_approval"
    assert state.current_step_id == "geometry.proxy_approval"
    assert (root / "reports" / "pdf" / "proxy_report.pdf").is_file()
    assert (root / "reports" / "pdf" / "proxy_report.manifest.json").is_file()
    approval_state = next(
        item for item in state.steps if item.step_id == "geometry.proxy_approval"
    )
    with pytest.raises(ValueError, match="does not match"):
        approve_workflow_gate(
            "workflow_asset",
            state.workflow_id,
            "geometry.proxy_approval",
            artifact_fingerprint="0" * 64,
            approval_note="wrong hash",
        )
    completed = approve_workflow_gate(
        "workflow_asset",
        state.workflow_id,
        "geometry.proxy_approval",
        artifact_fingerprint=str(approval_state.input_fingerprint),
        approval_note="Proxy silhouette and layout reviewed.",
    )
    assert completed.status == "completed"
    assert completed.milestone == "completed"


def test_stale_agent_output_invalidates_completion_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Changing an agent output after completion marks its old receipt stale."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    state = _complete_modeling_plan(root, state)
    plan_path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["global_notes"].append("changed after marker")
    plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    stale = reconcile_workflow("workflow_asset", state.workflow_id)
    step = next(item for item in stale.steps if item.step_id == "geometry.modeling_plan")
    assert step.status == "stale"
    assert stale.status == "blocked"


def test_cancel_preserves_artifacts_and_prevents_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cancellation is non-destructive and cannot be bypassed by resume."""

    root, state = _new_proxy_workflow(monkeypatch, tmp_path)
    reference_hash = (root / "input" / "reference.png").read_bytes()
    cancelled = cancel_workflow(
        "workflow_asset",
        state.workflow_id,
        reason="User stopped the test workflow.",
    )
    assert cancelled.status == "cancelled"
    assert (root / "input" / "reference.png").read_bytes() == reference_hash
    with pytest.raises(RuntimeError, match="cannot be resumed"):
        resume_workflow("workflow_asset", state.workflow_id)


def test_lock_rejects_concurrency_and_recovers_expired_receipt(tmp_path: Path) -> None:
    """A live lock blocks writers while one expired valid receipt is archived safely."""

    root = tmp_path / "job"
    root.mkdir()
    first = acquire_workflow_lock(root, "lock_asset", "wf-lock-test")
    with pytest.raises(RuntimeError, match="Another workflow"):
        acquire_workflow_lock(root, "lock_asset", "wf-second")
    release_workflow_lock(root, first)
    write_expired_lock_for_test(root, "lock_asset", "wf-expired")
    recovered = acquire_workflow_lock(root, "lock_asset", "wf-recovered")
    assert list((root / "workflows" / "stale_locks").glob("*.json"))
    release_workflow_lock(root, recovered)


def test_failed_host_step_requires_explicit_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A deterministic host failure stays frozen until retry is explicitly authorized."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    state = plan_workflow(
        "Create a 3D proxy model from this image.",
        job_id="retry_asset",
        reference_path=primary,
    )
    original = orchestration_service._execute_host_tool

    def fail_once(*_args, **_kwargs) -> None:
        """Raise one deterministic fixture failure before any host output is written."""

        raise RuntimeError("fixture host failure")

    monkeypatch.setattr(orchestration_service, "_execute_host_tool", fail_once)
    failed = resume_workflow("retry_asset", state.workflow_id, max_host_steps=1)
    assert failed.status == "failed"
    frozen = resume_workflow("retry_asset", state.workflow_id, max_host_steps=1)
    assert frozen.status == "failed"
    assert next(
        item for item in frozen.steps if item.step_id == "reference.analyze"
    ).attempt_count == 1

    monkeypatch.setattr(orchestration_service, "_execute_host_tool", original)
    retried = resume_workflow(
        "retry_asset",
        state.workflow_id,
        max_host_steps=1,
        retry_failed=True,
    )
    assert retried.status == "waiting_for_agent"
    attempts = sorted(
        (
            workspace
            / "retry_asset"
            / "workflows"
            / state.workflow_id
            / "attempts"
            / "reference.analyze"
        ).glob("*.json")
    )
    assert len(attempts) == 2
    assert sorted(json.loads(path.read_text())["status"] for path in attempts) == [
        "failed",
        "succeeded",
    ]


def test_resume_finalizes_an_interrupted_attempt_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A prior running receipt is marked interrupted before a fresh unique attempt starts."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    state = plan_workflow(
        "Create a 3D proxy model from this image.",
        job_id="interrupted_asset",
        reference_path=primary,
    )
    root = workspace / "interrupted_asset"
    workflow_root = root / "workflows" / state.workflow_id
    current = next(
        item for item in state.steps if item.step_id == "reference.analyze"
    )
    assert current.input_fingerprint
    receipt = WorkflowAttempt(
        attempt_id="attempt-0001-interrupted",
        workflow_id=state.workflow_id,
        job_id="interrupted_asset",
        step_id="reference.analyze",
        plan_sha256=sha256_file(workflow_root / "plan.json"),
        input_fingerprint=current.input_fingerprint,
        status="running",
        started_at=datetime.now(UTC),
    )
    receipt_path = (
        workflow_root
        / "attempts"
        / "reference.analyze"
        / f"{receipt.attempt_id}.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")

    resumed = resume_workflow(
        "interrupted_asset",
        state.workflow_id,
        max_host_steps=1,
    )
    assert resumed.status == "waiting_for_agent"
    recovered = WorkflowAttempt.model_validate_json(receipt_path.read_text())
    assert recovered.status == "failed"
    assert recovered.error_type == "InterruptedAttempt"


def test_explicit_unity_target_stops_at_engine_neutral_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit unsupported engine never receives fabricated adapter parity."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    create_job("portable_asset", primary, "concept", [])
    state = plan_workflow(
        "Unity로 옮길 FBX 패키지를 만들어줘",
        job_id="portable_asset",
        intent="portable_package",
    )
    workflow_root = workspace / "portable_asset" / "workflows" / state.workflow_id
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    assert plan["destination"]["status"] == "unsupported"
    assert plan["destination"]["terminal_boundary"] == "portable_package"
    assert plan["steps"][-1]["step_id"] == "destination.unsupported"
    assert plan["terminal_step_id"] == "portable.final_approval"
    assert plan["steps"][1]["parameters"]["profile_id"] == "fbx_interchange"
    portable_ids = [item["step_id"] for item in plan["steps"]]
    assert portable_ids.index("portable.report") < portable_ids.index(
        "portable.final_approval"
    )
    adapters = destination_adapters()
    unity = next(
        item for item in adapters["adapters"] if item["destination"] == "unity"
    )
    assert unity["status"] == "unsupported"


@pytest.mark.parametrize(
    ("intent", "request_text", "report_id", "approval_id"),
    [
        (
            "material_authoring",
            "Author materials and shaders.",
            "material.report",
            "material.approval",
        ),
        (
            "visual_qa",
            "Run direct reference visual QA.",
            "qa.report",
            "qa.review",
        ),
    ],
)
def test_human_review_gates_require_a_pdf_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    intent: str,
    request_text: str,
    report_id: str,
    approval_id: str,
) -> None:
    """Material and QA approvals depend on a PDF plus canonical JSON evidence."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / f"{intent}.png")
    job_id = f"{intent}_asset"
    create_job(job_id, primary, "concept", [])
    state = plan_workflow(
        request_text,
        job_id=job_id,
        intent=intent,
    )
    workflow_root = workspace / job_id / "workflows" / state.workflow_id
    plan = json.loads((workflow_root / "plan.json").read_text(encoding="utf-8"))
    step_ids = [item["step_id"] for item in plan["steps"]]
    assert step_ids.index(report_id) < step_ids.index(approval_id)
    approval = next(item for item in plan["steps"] if item["step_id"] == approval_id)
    assert approval["depends_on"] == [report_id]


def test_ambiguous_existing_request_requires_explicit_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Multiple existing-job intents fail closed instead of choosing a broad workflow."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    primary = _image(tmp_path / "primary.png")
    create_job("ambiguous_asset", primary, "concept", [])
    with pytest.raises(ValueError, match="multiple existing-job intents"):
        plan_workflow(
            "셰이더를 수정하고 QA 후 FBX로 내보내줘",
            job_id="ambiguous_asset",
        )
    assert not (job_dir("ambiguous_asset") / "workflows" / "latest.json").exists()
