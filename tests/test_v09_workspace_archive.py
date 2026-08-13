from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.orchestration.models import WorkflowState
from codex_blender_modeler.orchestration.service import plan_workflow
from codex_blender_modeler.stabilization import (
    WorkspaceRelocationPlan,
    archive_workspace_job,
    execute_workspace_relocation,
    list_workspace_archive_candidates,
    plan_workspace_archive,
    restore_workspace_job,
    validate_workspace_relocation_receipt,
)
from codex_blender_modeler.workspace import load_job


def _isolated_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path]:
    """Route active and archived workspaces into one same-volume test repository."""

    workspace = tmp_path / "repo" / "workspaces"
    archive = tmp_path / "repo" / "workspace_archive"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("CBM_WORKSPACE_ARCHIVE_ROOT", str(archive))
    return workspace, archive


def _reference(path: Path) -> Path:
    """Create one deterministic reference image for an isolated V0.8 workflow."""

    Image.new("RGB", (12, 10), (45, 90, 135)).save(path)
    return path


def _workflow(
    workspace: Path,
    tmp_path: Path,
    job_id: str,
    *,
    status: str,
) -> WorkflowState:
    """Create a strict workflow fixture and project it onto one requested terminal state."""

    initial = plan_workflow(
        "Create a bounded proxy from this reference.",
        job_id=job_id,
        reference_path=_reference(tmp_path / f"{job_id}.png"),
    )
    updates: dict[str, object] = {
        "status": status,
        "current_step_id": None,
        "next_action": None,
        "waiting_gate": None,
    }
    if status == "completed":
        updates["milestone"] = "completed"
    if status == "cancelled":
        updates["cancelled_reason"] = "Test-only explicit cancellation."
    state = initial.model_copy(update=updates)
    state = WorkflowState.model_validate(state.model_dump(mode="json"))
    workflow_root = workspace / job_id / "workflows" / state.workflow_id
    (workflow_root / "state.json").write_text(
        state.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (workspace / job_id / "workflows" / "latest.json").write_text(
        json.dumps(
            {
                "schema_version": "0.8.0",
                "job_id": job_id,
                "workflow_id": state.workflow_id,
                "status": state.status,
                "updated_at": state.updated_at.isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return state


def test_completed_workspace_archives_and_restores_without_rewriting_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Round-trip one completed job while preserving its exact tree and public load boundary."""

    workspace, archive = _isolated_roots(monkeypatch, tmp_path)
    _workflow(workspace, tmp_path, "archive_asset", status="completed")
    before_job = (workspace / "archive_asset" / "job.json").read_bytes()

    archive_plan, archive_receipt = archive_workspace_job("archive_asset")
    archived_root = archive / archive_receipt.archive_entry_path
    assert not (workspace / "archive_asset").exists()
    assert archived_root.is_dir()
    assert archive_receipt.tree_sha256 == archive_plan.source_tree_sha256
    assert archive_receipt.adopted_interrupted_move is False
    validate_workspace_relocation_receipt(archive_receipt)
    with pytest.raises(FileNotFoundError, match="Job does not exist"):
        load_job("archive_asset")

    restore_plan, restore_receipt = restore_workspace_job(archive_receipt.receipt_id)
    assert restore_plan.prior_archive_receipt is not None
    assert not archived_root.exists()
    assert (workspace / "archive_asset" / "job.json").read_bytes() == before_job
    assert restore_receipt.tree_sha256 == archive_receipt.tree_sha256
    validate_workspace_relocation_receipt(restore_receipt)
    assert load_job("archive_asset")["job_id"] == "archive_asset"


def test_failed_workspace_requires_explicit_archive_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep failed workflows active unless the caller supplies the narrow explicit flag."""

    workspace, _archive = _isolated_roots(monkeypatch, tmp_path)
    _workflow(workspace, tmp_path, "failed_asset", status="failed")
    with pytest.raises(PermissionError, match="allow_failed=True"):
        plan_workspace_archive("failed_asset")
    plan, receipt = archive_workspace_job("failed_asset", allow_failed=True)
    assert plan.classification == "failed"
    assert plan.allow_failed is True
    assert receipt.classification == "failed"


def test_nonterminal_and_locked_workspaces_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject planned work and terminal work that still carries an active lock artifact."""

    workspace, _archive = _isolated_roots(monkeypatch, tmp_path)
    plan_workflow(
        "Create a bounded proxy from this reference.",
        job_id="planned_asset",
        reference_path=_reference(tmp_path / "planned.png"),
    )
    with pytest.raises(RuntimeError, match="only completed"):
        plan_workspace_archive("planned_asset")

    _workflow(workspace, tmp_path, "locked_asset", status="completed")
    lock_path = workspace / "locked_asset" / "workflows" / ".writer.lock.json"
    lock_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="active lock"):
        plan_workspace_archive("locked_asset")


def test_archive_plan_crash_adopts_exact_already_moved_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recover a crash between atomic directory rename and receipt publication."""

    workspace, archive = _isolated_roots(monkeypatch, tmp_path)
    _workflow(workspace, tmp_path, "adopt_asset", status="completed")
    plan = plan_workspace_archive("adopt_asset")
    source = workspace / "adopt_asset"
    destination = archive / plan.archive_entry_path
    destination.parent.mkdir(parents=True)
    os.replace(source, destination)

    receipt = execute_workspace_relocation(plan)
    assert receipt.adopted_interrupted_move is True
    assert not source.exists()
    validate_workspace_relocation_receipt(receipt)


def test_archive_rejects_tree_and_plan_digest_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject changed workspace bytes and independently reject a forged plan digest."""

    workspace, _archive = _isolated_roots(monkeypatch, tmp_path)
    _workflow(workspace, tmp_path, "tamper_asset", status="completed")
    plan = plan_workspace_archive("tamper_asset")
    (workspace / "tamper_asset" / "new-file.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="tree changed"):
        execute_workspace_relocation(plan)

    payload = plan.model_dump(mode="json")
    payload["input_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="input digest"):
        WorkspaceRelocationPlan.model_validate(payload)


def test_candidate_report_exposes_only_terminal_eligible_jobs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Classify completed and planned jobs without moving either workspace."""

    workspace, _archive = _isolated_roots(monkeypatch, tmp_path)
    _workflow(workspace, tmp_path, "eligible_asset", status="completed")
    plan_workflow(
        "Create a bounded proxy from this reference.",
        job_id="active_asset",
        reference_path=_reference(tmp_path / "active.png"),
    )
    report = {item["job_id"]: item for item in list_workspace_archive_candidates()}
    assert report["eligible_asset"]["eligible"] is True
    assert report["active_asset"]["eligible"] is False
    assert (workspace / "eligible_asset").is_dir()
    assert (workspace / "active_asset").is_dir()


def test_archive_rejects_linked_control_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Refuse archive-control publication through a symlink or junction-like component."""

    workspace, archive = _isolated_roots(monkeypatch, tmp_path)
    _workflow(workspace, tmp_path, "linked_archive_asset", status="completed")
    outside = tmp_path / "outside-control"
    outside.mkdir()
    archive.mkdir()
    control = archive / ".cbm"
    try:
        control.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"host cannot create a directory symlink: {exc}")
    with pytest.raises(ValueError, match="contains a link"):
        plan_workspace_archive("linked_archive_asset")
