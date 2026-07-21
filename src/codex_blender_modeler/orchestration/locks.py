"""Expiring job-local write locks for V0.8 orchestration."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ..blender_artifacts import write_json_atomic
from .models import WorkflowLock


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for lock comparisons."""

    return datetime.now(UTC)


def _read_lock(path: Path) -> WorkflowLock:
    """Load one strict lock receipt or report it as an unsafe active lock."""

    try:
        return WorkflowLock.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Workflow lock exists but is unreadable; inspect it before recovery: {path}"
        ) from exc


def _archive_stale_lock(path: Path, lock: WorkflowLock) -> Path:
    """Move one expired lock into immutable stale-lock history before retrying."""

    history = path.parent / "stale_locks"
    history.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    destination = history / f"{stamp}_{lock.lock_id}.json"
    os.replace(path, destination)
    return destination


def acquire_workflow_lock(
    job_root: Path,
    job_id: str,
    workflow_id: str,
    *,
    ttl_seconds: int = 900,
) -> WorkflowLock:
    """Acquire one exclusive lock, recovering only a structurally valid expired lock."""

    if ttl_seconds < 30 or ttl_seconds > 86400:
        raise ValueError("workflow lock TTL must be within [30, 86400] seconds")
    lock_path = job_root / "workflows" / ".lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now = _utc_now()
    receipt = WorkflowLock(
        lock_id=uuid4().hex,
        workflow_id=workflow_id,
        job_id=job_id,
        process_id=os.getpid(),
        acquired_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    payload = receipt.model_dump_json(indent=2) + "\n"
    for _attempt in range(2):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            existing = _read_lock(lock_path)
            if existing.expires_at > _utc_now():
                raise RuntimeError(
                    "Another workflow owns the job write lock: "
                    f"workflow={existing.workflow_id} expires={existing.expires_at.isoformat()}"
                ) from None
            _archive_stale_lock(lock_path, existing)
            continue
        try:
            os.write(descriptor, payload.encode("utf-8"))
        finally:
            os.close(descriptor)
        return receipt
    raise RuntimeError(f"Could not acquire workflow lock after stale recovery: {lock_path}")


def release_workflow_lock(job_root: Path, lock: WorkflowLock) -> None:
    """Release only the exact lock token owned by the current orchestration call."""

    lock_path = job_root / "workflows" / ".lock.json"
    if not lock_path.is_file():
        return
    current = _read_lock(lock_path)
    if current.lock_id != lock.lock_id:
        raise RuntimeError("Workflow lock ownership changed; refusing to remove another lock")
    lock_path.unlink()


@contextmanager
def workflow_write_lock(
    job_root: Path,
    job_id: str,
    workflow_id: str,
    *,
    ttl_seconds: int = 900,
) -> Iterator[WorkflowLock]:
    """Hold one job-local lock for an atomic workflow state transition."""

    receipt = acquire_workflow_lock(
        job_root,
        job_id,
        workflow_id,
        ttl_seconds=ttl_seconds,
    )
    try:
        yield receipt
    finally:
        release_workflow_lock(job_root, receipt)


def write_expired_lock_for_test(
    job_root: Path,
    job_id: str,
    workflow_id: str,
) -> WorkflowLock:
    """Create an expired lock only for deterministic recovery tests."""

    now = _utc_now()
    receipt = WorkflowLock(
        lock_id=uuid4().hex,
        workflow_id=workflow_id,
        job_id=job_id,
        process_id=0,
        acquired_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(minutes=1),
    )
    write_json_atomic(
        job_root / "workflows" / ".lock.json",
        receipt.model_dump(mode="json"),
    )
    return receipt
