from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.auto_revision import service
from codex_blender_modeler.orchestration.locks import workflow_write_lock


def _seed_run(tmp_path: Path, monkeypatch) -> tuple[Path, str]:
    """Create the minimum job and QA-run paths needed before lock acquisition."""

    workspace = tmp_path / "workspaces"
    root = workspace / "lock_test"
    run_id = "qa-run-01"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    (root / "qa" / "runs" / run_id).mkdir(parents=True, exist_ok=True)
    (root / "job.json").write_text(
        json.dumps({"job_id": "lock_test", "mode": "concept"}),
        encoding="utf-8",
    )
    return root, run_id


def test_manual_apply_holds_job_write_lock_for_entire_inner_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Keep the shared job lock active while the guarded apply owns canonical state."""

    root, run_id = _seed_run(tmp_path, monkeypatch)
    observed: dict[str, Any] = {}

    def fake_inner(job_id: str, selected_run_id: str, **kwargs) -> dict[str, Any]:
        """Capture the lock receipt visible to the serialized inner apply."""

        lock_path = root / "workflows" / ".lock.json"
        observed["lock"] = json.loads(lock_path.read_text(encoding="utf-8"))
        observed["job_id"] = job_id
        observed["run_id"] = selected_run_id
        observed["kwargs"] = kwargs
        return {"ok": True, "status": "accepted"}

    monkeypatch.setattr(
        service,
        "_apply_job_approved_revision_under_job_lock",
        fake_inner,
    )

    result = service.apply_job_approved_revision("lock_test", run_id)

    assert result["status"] == "accepted"
    assert observed["job_id"] == "lock_test"
    assert observed["run_id"] == run_id
    assert observed["lock"]["job_id"] == "lock_test"
    assert observed["lock"]["workflow_id"].startswith("qa-revision-")
    assert not (root / "workflows" / ".lock.json").exists()


@pytest.mark.parametrize("lock_owner", ["conv-conflict", "wf-conflict"])
def test_active_job_writer_lock_blocks_manual_apply_without_consuming_it(
    tmp_path: Path,
    monkeypatch,
    lock_owner: str,
) -> None:
    """Fail immediately for convergence or V0.8 owners of the same job lock."""

    root, run_id = _seed_run(tmp_path, monkeypatch)
    called = False

    def fake_inner(*args, **kwargs) -> dict[str, Any]:
        """Record any unsafe entry into the canonical mutation helper."""

        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(
        service,
        "_apply_job_approved_revision_under_job_lock",
        fake_inner,
    )

    with workflow_write_lock(
        root,
        "lock_test",
        lock_owner,
        ttl_seconds=60,
    ):
        with pytest.raises(RuntimeError, match="Another workflow owns the job write lock"):
            service.apply_job_approved_revision("lock_test", run_id)

    assert called is False
    assert not (root / "workflows" / ".lock.json").exists()


def test_manual_apply_releases_job_lock_after_inner_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Release the shared lock even when existing rollback or verification logic raises."""

    root, run_id = _seed_run(tmp_path, monkeypatch)

    def fail_inner(*args, **kwargs) -> dict[str, Any]:
        """Simulate a failure from the existing guarded apply implementation."""

        raise RuntimeError("mock guarded apply failure")

    monkeypatch.setattr(
        service,
        "_apply_job_approved_revision_under_job_lock",
        fail_inner,
    )

    with pytest.raises(RuntimeError, match="mock guarded apply failure"):
        service.apply_job_approved_revision("lock_test", run_id)

    assert not (root / "workflows" / ".lock.json").exists()


def test_invalid_public_options_fail_before_creating_a_job_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Preserve legacy validation order and avoid locks for invalid render requests."""

    root, run_id = _seed_run(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="render_engine"):
        service.apply_job_approved_revision(
            "lock_test",
            run_id,
            render_engine="unsupported",
        )

    assert not (root / "workflows" / ".lock.json").exists()
