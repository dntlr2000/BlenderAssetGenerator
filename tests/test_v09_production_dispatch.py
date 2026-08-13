from __future__ import annotations

import json
import os
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.auto_revision.convergence_session_models import (
    ConvergencePathLimit,
    VisualConvergencePlan,
)
from codex_blender_modeler.blender_artifacts import native_io_path, sha256_file
from codex_blender_modeler.orchestration.service import _artifact_digest
from codex_blender_modeler.production import service as production_service
from codex_blender_modeler.production.models import (
    AssetProductionDispatchPlan,
    AssetProductionDispatchRequest,
    CodexTaskBinding,
    CodexTaskBindingReceipt,
    CodexTaskLaunchManifest,
    DelegatedProductionAdvanceReceipt,
    DelegatedProductionControllerPlan,
    DelegatedProductionState,
    DelegatedWorkAssignment,
    ProductionConvergenceBinding,
    ProductionPostflightAuditReceipt,
)
from codex_blender_modeler.production.service import (
    advance_delegated_production_controller,
    bind_asset_production_task,
    create_asset_production_dispatch,
    get_asset_production_dispatch_status,
    record_delegated_production_step,
)
from codex_blender_modeler.production.validation import (
    controller_tool_profile_digest,
    production_artifact_digest,
    validate_dispatch_bundle,
)
from codex_blender_modeler.stabilization.models import JobAudit, WorkspaceAuditReport
from codex_blender_modeler.stabilization.service import _audit_production_dispatches

ROOT = Path(__file__).resolve().parents[1]


def _image(path: Path) -> Path:
    """Create one deterministic reference fixture for isolated dispatch tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (42, 95, 140)).save(path)
    return path


def _directory_link(link: Path, target: Path) -> None:
    """Create a directory symlink or Windows junction for containment tests."""

    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Windows junction creation is unavailable: {result.stderr}")
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation is unavailable: {exc}")


def _dangling_leaf_link(link: Path, missing_target: Path) -> None:
    """Create one dangling symlink-like leaf for missing-target containment tests."""

    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        missing_target.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(missing_target)],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Windows junction creation is unavailable: {result.stderr}")
        missing_target.rmdir()
        return
    try:
        link.symlink_to(missing_target, target_is_directory=False)
    except OSError as exc:
        pytest.skip(f"file symlink creation is unavailable: {exc}")


def _dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    job_id: str = "production_asset",
    execution_policy: str = "standard",
    controller_execution_mode: str = "client_mediated",
    destination_kind: str = "unspecified",
    convergence: bool = False,
) -> tuple[Path, dict]:
    """Create one isolated production dispatch with no Blender execution."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    result = create_asset_production_dispatch(
        "Create a static reference asset and stop at every exact approval boundary.",
        reference_path=_image(tmp_path / f"{job_id}.png"),
        purpose="Static environment review asset",
        job_id=job_id,
        execution_policy=execution_policy,
        controller_execution_mode=controller_execution_mode,
        profile_id="fbx_interchange",
        destination_kind=destination_kind,
        convergence_mode=("bounded_after_v06" if convergence else "disabled"),
        convergence_target_direct_score=(0.85 if convergence else None),
        convergence_target_silhouette_iou=(0.8 if convergence else None),
        convergence_max_iterations=3,
    )
    return workspace / job_id, result


def _dispatch_identity(result: dict) -> tuple[str, str, str]:
    """Extract dispatch, controller, and workflow IDs from one public response."""

    plan = result["dispatch_plan"]
    return plan["dispatch_id"], plan["controller_id"], plan["workflow_id"]


def _bind_dispatch(root: Path, result: dict) -> CodexTaskBinding:
    """Bind one synthetic client task to the exact prepared controller profile."""

    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    return bind_asset_production_task(
        root.name,
        dispatch_id,
        controller_id,
        external_task_id=f"thread_{root.name}",
        client_tool_policy_enforced=True,
        enforced_controller_tool_profile_sha256=result[
            "controller_tool_profile_sha256"
        ],
    )


def _three_receipt_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, str, list[Path]]:
    """Create three public controller actions whose final action changes workflow state."""

    root, result = _dispatch(
        monkeypatch,
        tmp_path,
        job_id="production_lineage_asset",
    )
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    _bind_dispatch(root, result)
    advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
        max_host_steps=2,
    )
    assigned = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    assignment = DelegatedWorkAssignment.model_validate_json(
        (root / assigned["state"]["current_assignment"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    _author_modeling_plan(root)
    record_delegated_production_step(
        root.name,
        dispatch_id,
        controller_id,
        step_id=assignment.step_id,
        input_fingerprint=assignment.input_fingerprint,
        note="Complete the exact lineage fixture assignment.",
    )
    receipts = sorted(
        (root / "production" / "dispatches" / dispatch_id / "advances").glob(
            "*.json"
        )
    )
    assert len(receipts) == 3
    return root, dispatch_id, receipts


def _author_modeling_plan(root: Path) -> None:
    """Promote the deterministic analysis scaffold to a schema-valid authored plan."""

    scene_seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["objects"] = [
        {
            "id": item["id"],
            "label": item["name"],
            "recommended_geometry": item["geometry"]["kind"],
            "source_ids": ["ref.main"],
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "observed": True,
            "confidence": 0.8,
            "assembly_role": "root" if index == 0 else "free_standing",
            "notes": [],
        }
        for index, item in enumerate(scene_seed["objects"])
    ]
    payload["assembly_consistency_policy"] = "spatial_v1"
    payload["assembly_frame"] = {
        "root_object_id": scene_seed["objects"][0]["id"],
        "longitudinal_axis": "X",
        "lateral_axis": "Y",
        "vertical_axis": "Z",
        "symmetry": "unknown",
        "evidence_status": "inferred",
        "source_ids": [],
        "confidence": 0.5,
        "notes": ["Test-only inferred assembly frame."],
    }
    payload["assembly_relationships"] = []
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _replace_workflow_state_with_test_receipt(
    root: Path,
    dispatch_id: str,
    payload: dict[str, object],
    *,
    note: str,
) -> None:
    """Wrap one test-only V0.8 state fixture change in the real receipt lineage writer."""

    dispatch_root = root / "production" / "dispatches" / dispatch_id
    workflow_id = str(payload["workflow_id"])
    path = root / "workflows" / workflow_id / "state.json"
    before_bytes = path.read_bytes()
    before = production_service._reconstruct_controller_state(root, dispatch_id)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    after = production_service._reconstruct_controller_state(
        root,
        dispatch_id,
        allow_inflight_workflow_state=True,
    )
    production_service._record_advance_receipt(
        root,
        dispatch_root,
        before,
        after,
        before_workflow_state=before_bytes,
        after_workflow_state=path.read_bytes(),
        note=note,
    )


def _mark_workflow_completed(root: Path, workflow_id: str, dispatch_id: str) -> None:
    """Create one receipt-anchored terminal V0.8 fixture for postflight tests."""

    path = root / "workflows" / workflow_id / "state.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(
        {
            "status": "completed",
            "milestone": "completed",
            "current_step_id": None,
            "next_action": None,
            "waiting_gate": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    _replace_workflow_state_with_test_receipt(
        root,
        dispatch_id,
        payload,
        note="TEST FIXTURE ONLY: anchored terminal workflow projection.",
    )


def _write_fake_convergence_plan(
    root: Path,
    *,
    session_id: str,
    run_id: str,
    qa_report_path: Path,
    target_direct_score: float,
    target_silhouette_iou: float,
    max_iterations: int,
) -> dict[str, str]:
    """Write one strict status fixture for production-controller boundary tests."""

    session_root = root / "qa" / "convergence" / session_id
    session_root.mkdir(parents=True, exist_ok=False)
    plan = VisualConvergencePlan(
        session_id=session_id,
        job_id=root.name,
        input_fingerprint="1" * 64,
        initial_scene_spec_sha256="2" * 64,
        initial_qa_run_id=run_id,
        initial_qa_report_sha256=sha256_file(qa_report_path),
        camera_fingerprint="3" * 64,
        scoring_version="semantic_bbox_v2",
        initial_direct_score=0.4,
        initial_silhouette_iou=0.4,
        target_direct_score=target_direct_score,
        target_silhouette_iou=target_silhouette_iou,
        max_iterations=max_iterations,
        allowed_target_ids=["asset.primary"],
        path_limits=[
            ConvergencePathLimit(
                path_family="transform.location",
                allowed_operations=["add"],
                max_absolute_delta=0.1,
            )
        ],
        created_at=datetime.now(UTC).isoformat(),
    )
    plan_path = session_root / "plan.json"
    plan_path.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "plan": str(plan_path),
        "plan_sha256": sha256_file(plan_path),
        "session_id": session_id,
    }


def _passed_audit(job_id: str, audit_id: str) -> WorkspaceAuditReport:
    """Build one internally consistent passed V0.9 audit fixture."""

    now = datetime.now(UTC)
    job = JobAudit(job_id=job_id, status="passed", migration_status="current")
    return WorkspaceAuditReport(
        audit_id=audit_id,
        project_version="0.9.0",
        workspace_mode="external_configured",
        job_filter=job_id,
        scan_limit=100,
        scanned_file_count=1,
        scanned_job_count=1,
        passed_job_count=1,
        warning_job_count=0,
        failed_job_count=0,
        status="passed",
        jobs=[job],
        started_at=now,
        completed_at=now,
    )


def test_production_contract_schemas_are_current_and_strict() -> None:
    """Keep generated V0.9 production schemas byte-equivalent to host models."""

    contracts = {
        "asset_production_dispatch_request.schema.json": AssetProductionDispatchRequest,
        "delegated_production_controller_plan.schema.json": (
            DelegatedProductionControllerPlan
        ),
        "codex_task_launch_manifest.schema.json": CodexTaskLaunchManifest,
        "asset_production_dispatch_plan.schema.json": AssetProductionDispatchPlan,
        "codex_task_binding.schema.json": CodexTaskBinding,
        "codex_task_binding_receipt.schema.json": CodexTaskBindingReceipt,
        "delegated_work_assignment.schema.json": DelegatedWorkAssignment,
        "delegated_production_advance_receipt.schema.json": (
            DelegatedProductionAdvanceReceipt
        ),
        "delegated_production_state.schema.json": DelegatedProductionState,
        "production_postflight_audit_receipt.schema.json": (
            ProductionPostflightAuditReceipt
        ),
        "production_convergence_binding.schema.json": ProductionConvergenceBinding,
    }
    for filename, model in contracts.items():
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False


def test_dispatch_prepares_relative_client_launch_and_read_only_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Prepare a client task without persisting host paths or claiming task creation."""

    root, result = _dispatch(monkeypatch, tmp_path)
    dispatch_id, controller_id, workflow_id = _dispatch_identity(result)
    dispatch_root = root / "production" / "dispatches" / dispatch_id
    assert result["launch_status"] == "prepared"
    assert result["task_created_by_repository"] is False
    assert result["controller_state"]["next_action"] == "bind_client_task"
    launch = CodexTaskLaunchManifest.model_validate_json(
        (dispatch_root / "task_launch_manifest.json").read_text(encoding="utf-8")
    )
    assert launch.controller_tool_policy == "allowlist_only"
    assert "advance_delegated_production_controller" in launch.controller_mcp_allowlist
    assert "generate_destination_handoff" in launch.controller_forbidden_mcp_tools
    assert "resume_short_workflow" in launch.controller_forbidden_mcp_tools
    assert result["controller_tool_profile_sha256"] == controller_tool_profile_digest(
        launch
    )
    reduced_capabilities = launch.model_copy(
        update={
            "required_client_capabilities": launch.required_client_capabilities[:-1]
        }
    )
    assert controller_tool_profile_digest(reduced_capabilities) != result[
        "controller_tool_profile_sha256"
    ]
    for path in dispatch_root.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert str(tmp_path) not in text
            assert str(root.resolve()) not in text
    before = list((dispatch_root / "advances").glob("*.json"))
    status = get_asset_production_dispatch_status(root.name, dispatch_id)
    with pytest.raises(PermissionError, match="exact client task binding"):
        advance_delegated_production_controller(
            root.name,
            dispatch_id,
            controller_id,
        )
    after = list((dispatch_root / "advances").glob("*.json"))
    assert status["state"]["workflow_id"] == workflow_id
    assert status["state"]["controller_id"] == controller_id
    assert before == after == []


def test_desktop_in_session_starts_without_external_binding_and_advances_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run the current Codex task as controller without claiming client-profile isolation."""

    root, result = _dispatch(
        monkeypatch,
        tmp_path,
        job_id="desktop_session_asset",
        controller_execution_mode="desktop_in_session",
    )
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    assert result["launch_status"] == "ready_in_session"
    assert result["controller_execution_mode"] == "desktop_in_session"
    assert result["approval_isolation"] == "workflow_contract_only"
    assert result["controller_tool_profile_enforced"] is False
    assert result["controller_state"]["next_action"] == "resume_host"
    assert result["controller_state"]["task_binding"] is None
    assert any(
        "no per-task tool-profile isolation" in warning
        for warning in result["controller_state"]["warnings"]
    )

    advanced = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
        max_host_steps=2,
    )
    assert advanced["state"]["next_action"] == "delegate_read_only"
    assert advanced["state"]["approval_isolation"] == "workflow_contract_only"
    assigned = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    assert assigned["state"]["next_action"] == "controller_author"
    assert assigned["advance_receipt"]["task_binding"] is None
    assignment_path = root / assigned["state"]["current_assignment"]["path"]
    assignment = DelegatedWorkAssignment.model_validate_json(
        assignment_path.read_text(encoding="utf-8")
    )
    _author_modeling_plan(root)
    completed = record_delegated_production_step(
        root.name,
        dispatch_id,
        controller_id,
        step_id=assignment.step_id,
        input_fingerprint=assignment.input_fingerprint,
        note="Current desktop task authored the exact assigned ModelingPlan.",
    )
    assert completed["state"]["next_action"] == "delegate_read_only"
    assert completed["advance_receipt"]["task_binding"] is None


def test_desktop_in_session_rejects_external_task_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep current-task execution distinct from the externally isolated task route."""

    root, result = _dispatch(
        monkeypatch,
        tmp_path,
        job_id="desktop_binding_asset",
        controller_execution_mode="desktop_in_session",
    )
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    with pytest.raises(ValueError, match="do not accept an external task binding"):
        bind_asset_production_task(
            root.name,
            dispatch_id,
            controller_id,
            external_task_id="thread_should_not_bind",
            client_tool_policy_enforced=True,
            enforced_controller_tool_profile_sha256=result[
                "controller_tool_profile_sha256"
            ],
        )


def test_invalid_controller_execution_mode_fails_before_creating_a_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject unknown controller runtimes before copying a reference or creating evidence."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    with pytest.raises(ValueError, match="controller_execution_mode"):
        create_asset_production_dispatch(
            "Create a static asset.",
            reference_path=_image(tmp_path / "invalid_controller_mode.png"),
            purpose="Static asset",
            job_id="invalid_controller_mode_asset",
            controller_execution_mode="unsupported",
        )
    assert not (workspace / "invalid_controller_mode_asset").exists()


def test_controller_issues_read_only_assignment_and_records_exact_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Advance host work, issue one advisory assignment, and reuse V0.8 completion safety."""

    root, result = _dispatch(monkeypatch, tmp_path)
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    _bind_dispatch(root, result)
    advanced = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
        max_host_steps=2,
    )
    assert advanced["state"]["next_action"] == "delegate_read_only"
    assigned = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    state = assigned["state"]
    assert state["next_action"] == "controller_author"
    assignment_path = root / state["current_assignment"]["path"]
    assignment = DelegatedWorkAssignment.model_validate_json(
        assignment_path.read_text(encoding="utf-8")
    )
    assert assignment.step_id == "geometry.modeling_plan"
    assert assignment.subagent_write_allowlist == []
    assert assignment.canonical_write_authority == "controller_only"
    assert "analysis/modeling_plan.json" in assignment.controller_expected_outputs
    _author_modeling_plan(root)
    completed = record_delegated_production_step(
        root.name,
        dispatch_id,
        controller_id,
        step_id=assignment.step_id,
        input_fingerprint=assignment.input_fingerprint,
        note="Controller authored the exact ModelingPlan after read-only review.",
    )
    assert completed["state"]["current_step_id"] == "geometry.proxy_author"
    assert completed["state"]["next_action"] == "delegate_read_only"
    receipts = sorted((assignment_path.parents[1] / "advances").glob("*.json"))
    assert len(receipts) == 3
    parsed = [
        DelegatedProductionAdvanceReceipt.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        for path in receipts
    ]
    assert [item.sequence for item in parsed] == [1, 2, 3]
    assert parsed[0].previous_receipt_sha256 is None
    assert parsed[1].previous_receipt_sha256 is not None
    for index, item in enumerate(parsed):
        before_path = root / item.workflow_state_before.path
        after_path = root / item.workflow_state_after.path
        assert before_path.is_file()
        assert after_path.is_file()
        assert sha256_file(before_path) == item.workflow_state_before_sha256
        assert sha256_file(after_path) == item.workflow_state_after_sha256
        if index:
            assert (
                parsed[index - 1].workflow_state_after_sha256
                == item.workflow_state_before_sha256
            )
    workflow_state = root / "workflows" / parsed[-1].workflow_id / "state.json"
    assert parsed[-1].workflow_state_after_sha256 == sha256_file(workflow_state)
    validate_dispatch_bundle(root, dispatch_id)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("lineage", "workflow-state lineage is broken"),
        ("snapshot_bytes", "hash mismatch"),
        ("sequence_gap", "sequence is not contiguous"),
        ("previous_receipt", "hash chain is broken"),
        ("tail", "receipt tail does not match"),
        ("job_id", "receipt identity mismatch"),
        ("workflow_id", "receipt identity mismatch"),
        ("dispatch_id", "receipt identity mismatch"),
        ("controller_id", "receipt identity mismatch"),
        ("dispatch_plan", "receipt identity mismatch"),
    ],
)
def test_production_receipt_state_lineage_tampering_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    """Reject gaps, altered snapshots, identities, plan hashes, and stale current tails."""

    root, dispatch_id, receipts = _three_receipt_dispatch(monkeypatch, tmp_path)
    final_path = receipts[-1]
    final = json.loads(final_path.read_text(encoding="utf-8"))
    if mutation == "lineage":
        final["workflow_state_before_sha256"] = final[
            "workflow_state_after_sha256"
        ]
        final["workflow_state_before"] = final["workflow_state_after"]
        final_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    elif mutation == "snapshot_bytes":
        snapshot = root / final["workflow_state_after"]["path"]
        snapshot.write_bytes(snapshot.read_bytes() + b"\n")
    elif mutation == "sequence_gap":
        receipts[1].unlink()
    elif mutation == "previous_receipt":
        final["previous_receipt_sha256"] = "0" * 64
        final_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    elif mutation == "tail":
        state_path = root / "workflows" / final["workflow_id"] / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["updated_at"] = datetime.now(UTC).isoformat()
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    elif mutation == "dispatch_plan":
        final["dispatch_plan_sha256"] = "0" * 64
        final_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    else:
        replacement = {
            "job_id": "other-production-job",
            "workflow_id": "wf-other-production",
            "dispatch_id": "dispatch-other-production",
            "controller_id": "controller-other-production",
        }[mutation]
        final[mutation] = replacement
        final_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_dispatch_bundle(root, dispatch_id)


def test_client_binding_is_exact_and_does_not_approve_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bind an external Codex task while leaving the workflow at its original boundary."""

    root, result = _dispatch(monkeypatch, tmp_path)
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    binding = bind_asset_production_task(
        root.name,
        dispatch_id,
        controller_id,
        external_task_id="thread_test_123",
        external_host_id="local-test-host",
        client_tool_policy_enforced=True,
        enforced_controller_tool_profile_sha256=result[
            "controller_tool_profile_sha256"
        ],
    )
    status = get_asset_production_dispatch_status(root.name, dispatch_id)["state"]
    assert binding.external_task_id == "thread_test_123"
    receipt = CodexTaskBindingReceipt.model_validate_json(
        (
            root
            / "production"
            / "dispatches"
            / dispatch_id
            / "task_binding_receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt.task_binding == binding
    assert status["task_binding"] is not None
    assert status["next_action"] == "resume_host"
    workflow_root = root / "workflows" / status["workflow_id"]
    assert not (workflow_root / "approvals").exists()


def test_client_binding_requires_restricted_controller_profile_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Refuse task binding when the client cannot enforce the controller allowlist."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="unrestricted_task_asset")
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    with pytest.raises(PermissionError, match="restricted controller tool profile"):
        bind_asset_production_task(
            root.name,
            dispatch_id,
            controller_id,
            external_task_id="thread_without_policy",
            client_tool_policy_enforced=False,
            enforced_controller_tool_profile_sha256=result[
                "controller_tool_profile_sha256"
            ],
        )
    assert not (
        root
        / "production"
        / "dispatches"
        / dispatch_id
        / "task_binding_receipt.json"
    ).exists()


def test_client_binding_rejects_a_stale_controller_profile_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a client attestation that names any profile except the exact launch profile."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="stale_profile_asset")
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    with pytest.raises(PermissionError, match="stale or different"):
        bind_asset_production_task(
            root.name,
            dispatch_id,
            controller_id,
            external_task_id="thread_stale_profile",
            client_tool_policy_enforced=True,
            enforced_controller_tool_profile_sha256="0" * 64,
        )


def test_task_binding_and_workflow_state_snapshot_tampering_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject isolated task-binding and historical workflow-state snapshot changes."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="receipt_asset")
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    bind_asset_production_task(
        root.name,
        dispatch_id,
        controller_id,
        external_task_id="thread_receipt_test",
        client_tool_policy_enforced=True,
        enforced_controller_tool_profile_sha256=result[
            "controller_tool_profile_sha256"
        ],
    )
    binding_path = (
        root
        / "production"
        / "dispatches"
        / dispatch_id
        / "task_binding_receipt.json"
    )
    original_binding = binding_path.read_bytes()
    advanced = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
        max_host_steps=2,
    )
    payload = json.loads(original_binding)
    payload["task_binding"]["external_task_id"] = "thread_tampered"
    binding_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        get_asset_production_dispatch_status(root.name, dispatch_id)
    binding_path.write_bytes(original_binding)
    receipt = advanced["advance_receipt"]
    before_snapshot = root / receipt["workflow_state_before"]["path"]
    before_snapshot.write_text(
        before_snapshot.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        get_asset_production_dispatch_status(root.name, dispatch_id)


def test_completed_workflow_runs_one_hash_bound_postflight_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Finish production only after a passed audit whose snapshot hash remains immutable."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="postflight_asset")
    dispatch_id, controller_id, workflow_id = _dispatch_identity(result)
    _bind_dispatch(root, result)
    advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
        max_host_steps=2,
    )
    _mark_workflow_completed(root, workflow_id, dispatch_id)
    monkeypatch.setattr(
        "codex_blender_modeler.production.service.reconcile_workflow",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.production.service.audit_workspace_state",
        lambda *, job_id, audit_id: _passed_audit(job_id, audit_id),
    )
    before = get_asset_production_dispatch_status(root.name, dispatch_id)["state"]
    assert before["next_action"] == "run_postflight_audit"
    advanced = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    assert advanced["state"]["status"] == "completed"
    assert advanced["state"]["next_action"] == "completed"
    state_path = root / "workflows" / workflow_id / "state.json"
    original_state = state_path.read_bytes()
    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    state_payload["updated_at"] = datetime.now(UTC).isoformat()
    state_path.write_text(json.dumps(state_payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale|receipt tail"):
        get_asset_production_dispatch_status(root.name, dispatch_id)
    state_path.write_bytes(original_state)
    assert (
        get_asset_production_dispatch_status(root.name, dispatch_id)["state"]["status"]
        == "completed"
    )
    snapshot = root / advanced["state"]["postflight_audit"]["path"]
    postflight = ProductionPostflightAuditReceipt.model_validate_json(
        snapshot.read_text(encoding="utf-8")
    )
    assert postflight.terminal_artifacts
    terminal_path = root / postflight.terminal_artifacts[0].path
    original_terminal = terminal_path.read_bytes()
    terminal_path.write_bytes(original_terminal + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        get_asset_production_dispatch_status(root.name, dispatch_id)
    terminal_path.write_bytes(original_terminal)
    assert postflight.workflow_authority_artifacts
    authority_path = root / postflight.workflow_authority_artifacts[0].path
    original_authority = authority_path.read_bytes()
    authority_path.write_bytes(original_authority + b"\n")
    with pytest.raises(ValueError, match="authority artifacts"):
        get_asset_production_dispatch_status(root.name, dispatch_id)
    authority_path.write_bytes(original_authority)
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["audit_report"]["audit_id"] = "tampered-postflight"
    snapshot.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        get_asset_production_dispatch_status(root.name, dispatch_id)


def test_postflight_binds_v08_directory_artifacts_with_their_exact_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Accept valid V0.8 directory outputs and reject later directory-content changes."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="directory_asset")
    dispatch_id, controller_id, workflow_id = _dispatch_identity(result)
    _bind_dispatch(root, result)
    directory = root / "workflows" / workflow_id / "artifacts" / "material_candidate"
    directory.mkdir(parents=True)
    long_directory = directory / ("canonical-" + "a" * 90) / ("material-" + "b" * 90)
    os.makedirs(native_io_path(long_directory), exist_ok=True)
    member = long_directory / "material_plan.authored.json"
    with open(native_io_path(member), "w", encoding="utf-8") as handle:
        handle.write('{"fixture": true}\n')
    assert len(os.path.abspath(os.fspath(member))) > 260
    v08_digest = _artifact_digest(directory)
    assert v08_digest == production_artifact_digest(directory, containment_root=root)
    state_path = root / "workflows" / workflow_id / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["steps"][0]["artifacts"].append(
        {
            "artifact_id": "production.directory_fixture",
            "path": directory.relative_to(root).as_posix(),
            "sha256": v08_digest,
            "integrity": "valid",
            "currency": "current",
            "verification": "verified",
            "reason": "Test-only V0.8 nonempty_directory output.",
        }
    )
    state.update(
        {
            "status": "completed",
            "milestone": "completed",
            "current_step_id": None,
            "next_action": None,
            "waiting_gate": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    _replace_workflow_state_with_test_receipt(
        root,
        dispatch_id,
        state,
        note="TEST FIXTURE ONLY: anchored directory-artifact terminal state.",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.production.service.reconcile_workflow",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.production.service.audit_workspace_state",
        lambda *, job_id, audit_id: _passed_audit(job_id, audit_id),
    )
    advanced = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    receipt_path = root / advanced["state"]["postflight_audit"]["path"]
    receipt = ProductionPostflightAuditReceipt.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    assert any(
        item.path == directory.relative_to(root).as_posix()
        for item in receipt.terminal_artifacts
    )
    with open(native_io_path(member), "w", encoding="utf-8") as handle:
        handle.write('{"fixture": false}\n')
    with pytest.raises(ValueError, match="hash mismatch"):
        get_asset_production_dispatch_status(root.name, dispatch_id)


def test_background_dispatch_remains_explicit_and_destination_is_only_a_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep the opt-in fast lane engine-neutral even when a Unity hint is recorded."""

    root, result = _dispatch(
        monkeypatch,
        tmp_path,
        job_id="background_asset",
        execution_policy="background_exterior",
        destination_kind="unity",
    )
    dispatch_id, _controller_id, workflow_id = _dispatch_identity(result)
    dispatch = AssetProductionDispatchRequest.model_validate_json(
        (
            root
            / "production"
            / "dispatches"
            / dispatch_id
            / "dispatch_request.json"
        ).read_text(encoding="utf-8")
    )
    workflow_request = json.loads(
        (root / "workflows" / workflow_id / "request.json").read_text(encoding="utf-8")
    )
    assert dispatch.execution_policy == "background_exterior"
    assert dispatch.destination_hint.kind == "unity"
    assert workflow_request["destination"]["kind"] == "engine_neutral"
    assert workflow_request["delivery_scope"] == "portable_package"


def test_invalid_handoff_profile_fails_before_creating_a_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject OBJ handoff requests before the dispatcher mutates the workspace."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    with pytest.raises(ValueError, match="GLB and FBX"):
        create_asset_production_dispatch(
            "Create a static package.",
            reference_path=_image(tmp_path / "invalid_handoff.png"),
            purpose="Invalid handoff profile fixture",
            job_id="invalid_handoff_asset",
            profile_id="obj_legacy",
            include_destination_handoff=True,
        )
    assert not (workspace / "invalid_handoff_asset").exists()


def test_dispatch_preserves_generic_and_specialized_v08_approval_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep the dispatcher from replacing any generic or specialized workflow gate."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="approval_asset")
    _dispatch_id, _controller_id, workflow_id = _dispatch_identity(result)
    plan = json.loads(
        (root / "workflows" / workflow_id / "plan.json").read_text(encoding="utf-8")
    )
    steps = {item["step_id"]: item for item in plan["steps"]}
    assert steps["geometry.proxy_approval"]["execution_mode"] == "approval"
    assert steps["geometry.detail_approval"]["execution_mode"] == "approval"
    assert steps["material.approval"]["execution_mode"] == "approval"
    assert steps["qa.review"]["execution_mode"] == "approval"
    assert steps["portable.plan_approval"]["execution_mode"] == "specialized_approval"
    assert steps["portable.final_approval"]["execution_mode"] == "approval"
    assert not (root / "workflows" / workflow_id / "approvals").exists()


def test_bounded_convergence_dispatch_stops_for_one_exact_approval_and_runs_one_iteration_per_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bridge a completed standard preview into bounded V0.6 without self-approval."""

    root, result = _dispatch(
        monkeypatch,
        tmp_path,
        job_id="production_convergence_asset",
        convergence=True,
    )
    dispatch_id, controller_id, workflow_id = _dispatch_identity(result)
    dispatch_request = AssetProductionDispatchRequest.model_validate_json(
        (
            root
            / "production"
            / "dispatches"
            / dispatch_id
            / "dispatch_request.json"
        ).read_text(encoding="utf-8")
    )
    workflow_request = json.loads(
        (root / "workflows" / workflow_id / "request.json").read_text(
            encoding="utf-8"
        )
    )
    workflow_plan = json.loads(
        (root / "workflows" / workflow_id / "plan.json").read_text(
            encoding="utf-8"
        )
    )
    assert dispatch_request.delivery_scope == "v06_convergence"
    assert result["dispatch_plan"]["target_boundary"] == (
        "approved_v06_convergence_terminal"
    )
    assert workflow_request["execution_policy"] == "standard"
    assert workflow_request["delivery_scope"] == "preview_only"
    assert not any(step["phase"] == "portable" for step in workflow_plan["steps"])

    qa_step = next(step for step in workflow_plan["steps"] if step["step_id"] == "qa.run")
    qa_output = next(
        output
        for output in qa_step["outputs"]
        if output["artifact_id"] == "qa.run.visual_report"
    )
    qa_report = root / qa_output["path"]
    qa_report.parent.mkdir(parents=True, exist_ok=True)
    qa_report.write_text('{"fixture": "initial-qa"}\n', encoding="utf-8")
    run_id = Path(qa_output["path"]).parts[-2]

    _bind_dispatch(root, result)
    _mark_workflow_completed(root, workflow_id, dispatch_id)
    monkeypatch.setattr(
        production_service,
        "reconcile_workflow",
        lambda *_args, **_kwargs: None,
    )

    def fake_plan(
        job_id: str,
        initial_run_id: str,
        *,
        session_id: str,
        target_direct_score: float,
        target_silhouette_iou: float,
        max_iterations: int,
        **_kwargs: object,
    ) -> dict[str, str]:
        """Create one strict plan fixture at the controller-selected session path."""

        assert job_id == root.name
        assert initial_run_id == run_id
        return _write_fake_convergence_plan(
            root,
            session_id=session_id,
            run_id=initial_run_id,
            qa_report_path=qa_report,
            target_direct_score=target_direct_score,
            target_silhouette_iou=target_silhouette_iou,
            max_iterations=max_iterations,
        )

    run_count = 0

    def fake_status(_job_id: str, session_id: str) -> dict[str, object]:
        """Project exact approval and run-owned fixture files into controller status."""

        session_root = root / "qa" / "convergence" / session_id
        if not (session_root / "approval.json").is_file():
            return {
                "ok": True,
                "status": "waiting_for_exact_approval",
                "iteration_count": 0,
                "canonical_relation": "current",
            }
        if (session_root / "convergence_report.json").is_file():
            return {
                "ok": True,
                "status": "terminal",
                "iteration_count": run_count,
                "canonical_relation": "current",
                "target_reached": True,
            }
        return {
            "ok": True,
            "status": "active",
            "iteration_count": run_count,
            "canonical_relation": "current",
        }

    def fake_run(_job_id: str, session_id: str) -> dict[str, object]:
        """Publish exactly one immutable iteration artifact for each controller call."""

        nonlocal run_count
        run_count += 1
        session_root = root / "qa" / "convergence" / session_id
        if run_count == 1:
            receipt = session_root / "iterations" / "001" / "receipt.json"
            receipt.parent.mkdir(parents=True, exist_ok=False)
            receipt.write_text('{"fixture": "iteration-1"}\n', encoding="utf-8")
        else:
            (session_root / "convergence_report.json").write_text(
                '{"fixture": "terminal"}\n',
                encoding="utf-8",
            )
        return fake_status(root.name, session_id)

    monkeypatch.setattr(production_service, "plan_job_visual_convergence", fake_plan)
    monkeypatch.setattr(
        production_service,
        "get_job_visual_convergence_status",
        fake_status,
    )
    monkeypatch.setattr(production_service, "run_job_visual_convergence", fake_run)
    monkeypatch.setattr(
        production_service,
        "audit_workspace_state",
        lambda *, job_id, audit_id: _passed_audit(job_id, audit_id),
    )

    planned = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    state = planned["state"]
    assert state["next_action"] == "request_specialized_approval"
    assert state["approval_boundary"]["gate"] == "visual_convergence_plan"
    binding = ProductionConvergenceBinding.model_validate_json(
        (root / state["convergence_binding"]["path"]).read_text(encoding="utf-8")
    )
    assert state["approval_boundary"]["exact_fingerprint"] == (
        binding.convergence_plan.sha256
    )
    session_id = binding.convergence_session_id
    session_root = root / "qa" / "convergence" / session_id
    assert not (session_root / "approval.json").exists()
    with pytest.raises(RuntimeError, match="exact user-approved plan"):
        advance_delegated_production_controller(
            root.name,
            dispatch_id,
            controller_id,
        )
    assert not (session_root / "approval.json").exists()

    (session_root / "approval.json").write_text(
        json.dumps(
            {
                "fixture": "external-user-approval",
                "plan_sha256": state["approval_boundary"]["exact_fingerprint"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    first = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    assert run_count == 1
    assert first["state"]["next_action"] == "run_visual_convergence"
    second = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    assert run_count == 2
    assert second["state"]["next_action"] == "run_postflight_audit"
    completed = advance_delegated_production_controller(
        root.name,
        dispatch_id,
        controller_id,
    )
    assert completed["state"]["status"] == "completed"
    assert completed["state"]["convergence_report"] is not None


@pytest.mark.parametrize(
    ("execution_policy", "include_handoff", "expected"),
    [
        ("background_exterior", False, "standard-only"),
        ("standard", True, "finish before a separate package/handoff"),
    ],
)
def test_bounded_convergence_rejects_fast_lane_and_combined_handoff_before_job_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    execution_policy: str,
    include_handoff: bool,
    expected: str,
) -> None:
    """Keep convergence opt-in separate from fast execution and package handoff authority."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    with pytest.raises(ValueError, match=expected):
        create_asset_production_dispatch(
            "Create one static asset and converge its V0.6 preview.",
            reference_path=_image(tmp_path / f"invalid-{execution_policy}.png"),
            purpose="Invalid convergence scope fixture",
            job_id=f"invalid_convergence_{execution_policy}",
            execution_policy=execution_policy,
            include_destination_handoff=include_handoff,
            convergence_mode="bounded_after_v06",
            convergence_target_direct_score=0.85,
            convergence_target_silhouette_iou=0.8,
        )
    assert not (workspace / f"invalid_convergence_{execution_policy}").exists()


def test_dispatch_hash_tampering_fails_status_and_v09_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail closed when the exact task prompt no longer matches its launch bundle."""

    root, result = _dispatch(monkeypatch, tmp_path)
    dispatch_id, _controller_id, _workflow_id = _dispatch_identity(result)
    assert _audit_production_dispatches(root, root.name) == []
    prompt = (
        root
        / "production"
        / "dispatches"
        / dispatch_id
        / "codex_task_prompt.md"
    )
    prompt.write_text(prompt.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        get_asset_production_dispatch_status(root.name, dispatch_id)
    findings = _audit_production_dispatches(root, root.name)
    assert any(item.code == "PRODUCTION_DISPATCH_INTEGRITY_FAILED" for item in findings)


@pytest.mark.parametrize(
    "dispatch_id",
    ["../outside", "C:/outside", "\\\\server\\share", "CON"],
)
def test_dispatch_lookup_rejects_path_and_device_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dispatch_id: str,
) -> None:
    """Reject untrusted dispatch IDs before resolving or reading an external path."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    (workspace / "safe_asset").mkdir(parents=True)
    with pytest.raises(ValueError, match="portable lowercase|reserved Windows"):
        get_asset_production_dispatch_status("safe_asset", dispatch_id)


def test_live_controller_lock_is_not_stolen_by_age(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep a live local controller lock authoritative regardless of its timestamp."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="locked_asset")
    dispatch_id, controller_id, _workflow_id = _dispatch_identity(result)
    lock_path = (
        root
        / "production"
        / "dispatches"
        / dispatch_id
        / ".controller.lock.json"
    )
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": "0.9.0",
                "lock_id": "live-test-lock",
                "controller_id": controller_id,
                "owner_host": socket.gethostname(),
                "owner_pid": os.getpid(),
                "acquired_at": "2000-01-01T00:00:00+00:00",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="live or externally-owned"):
        advance_delegated_production_controller(root.name, dispatch_id, controller_id)


def test_dispatch_creation_rejects_outside_production_junction_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a production-parent junction injected after V0.8 job planning."""

    workspace = tmp_path / "workspaces"
    outside = tmp_path / "outside-production"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    original_plan_workflow = production_service.plan_workflow

    def _plan_then_inject_link(*args: object, **kwargs: object) -> object:
        """Create the legitimate workflow, then inject the hostile production parent."""

        state = original_plan_workflow(*args, **kwargs)
        root = workspace / state.job_id
        _directory_link(root / "production", outside)
        return state

    monkeypatch.setattr(production_service, "plan_workflow", _plan_then_inject_link)
    with pytest.raises(ValueError, match="symlink or junction"):
        create_asset_production_dispatch(
            "Create one static reference asset.",
            reference_path=_image(tmp_path / "outside_link.png"),
            purpose="Containment fixture",
            job_id="outside_link_asset",
        )
    assert not (outside / "dispatches").exists()


def test_dispatch_status_rejects_operational_subdirectory_junction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject an assignments junction before status reads or controller writes."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="assignment_link_asset")
    dispatch_id, _controller_id, _workflow_id = _dispatch_identity(result)
    dispatch_root = root / "production" / "dispatches" / dispatch_id
    outside = tmp_path / "outside-assignments"
    _directory_link(dispatch_root / "assignments", outside)
    with pytest.raises(ValueError, match="symlink or junction"):
        get_asset_production_dispatch_status(root.name, dispatch_id)


def test_dispatch_status_rejects_dangling_controller_state_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a dangling controller-state leaf even though Path.exists is false."""

    root, result = _dispatch(monkeypatch, tmp_path, job_id="dangling_state_asset")
    dispatch_id, _controller_id, _workflow_id = _dispatch_identity(result)
    state_path = (
        root
        / "production"
        / "dispatches"
        / dispatch_id
        / "controller_state.json"
    )
    state_path.unlink()
    _dangling_leaf_link(state_path, tmp_path / "missing-controller-state")
    with pytest.raises(ValueError, match="symlink or junction"):
        get_asset_production_dispatch_status(root.name, dispatch_id)


def test_directory_artifact_digest_rejects_recursive_external_link(
    tmp_path: Path,
) -> None:
    """Reject an external directory link encountered during recursive artifact hashing."""

    root = tmp_path / "job"
    artifact = root / "workflows" / "wf-test" / "artifacts" / "candidate"
    artifact.mkdir(parents=True)
    (artifact / "local.json").write_text('{"local": true}\n', encoding="utf-8")
    outside = tmp_path / "outside-artifact"
    (outside / "external.json").parent.mkdir(parents=True, exist_ok=True)
    (outside / "external.json").write_text('{"outside": true}\n', encoding="utf-8")
    _directory_link(artifact / "external", outside)
    with pytest.raises(ValueError, match="symlink or junction"):
        production_artifact_digest(artifact, containment_root=root)
