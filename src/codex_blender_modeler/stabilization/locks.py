"""Expiring workspace-local locks for the V0.9 deterministic queue."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from ..blender_artifacts import write_json_atomic
from .models import QueueLock


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for queue lock comparisons."""

    return datetime.now(UTC)


def _read_lock(path: Path) -> QueueLock:
    """Load one strict queue lock or report an unreadable lock as unsafe."""

    try:
        return QueueLock.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Local queue lock exists but is unreadable; inspect it before recovery"
        ) from exc


def _archive_stale_lock(path: Path, lock: QueueLock) -> Path:
    """Archive one structurally valid expired queue lock before reacquiring it."""

    history = path.parent / "stale_locks"
    history.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    destination = history / f"{stamp}_{lock.lock_id}.json"
    os.replace(path, destination)
    return destination


def acquire_queue_lock(queue_root: Path, *, ttl_seconds: int = 300) -> QueueLock:
    """Acquire the single local queue writer lock with bounded stale recovery."""

    if ttl_seconds < 30 or ttl_seconds > 86400:
        raise ValueError("queue lock TTL must be within [30, 86400] seconds")
    lock_path = queue_root / ".lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now = _utc_now()
    receipt = QueueLock(
        lock_id=uuid4().hex,
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
                    "Another process owns the local workflow queue lock until "
                    f"{existing.expires_at.isoformat()}"
                ) from None
            _archive_stale_lock(lock_path, existing)
            continue
        try:
            os.write(descriptor, payload.encode("utf-8"))
        finally:
            os.close(descriptor)
        return receipt
    raise RuntimeError("Could not acquire local queue lock after stale recovery")


def release_queue_lock(queue_root: Path, lock: QueueLock) -> None:
    """Release only the exact local queue lock owned by the current call."""

    lock_path = queue_root / ".lock.json"
    if not lock_path.is_file():
        return
    current = _read_lock(lock_path)
    if current.lock_id != lock.lock_id:
        raise RuntimeError("Queue lock ownership changed; refusing to remove another lock")
    lock_path.unlink()


@contextmanager
def queue_write_lock(
    queue_root: Path,
    *,
    ttl_seconds: int = 300,
) -> Iterator[QueueLock]:
    """Hold one exclusive lock for a bounded local queue transition."""

    receipt = acquire_queue_lock(queue_root, ttl_seconds=ttl_seconds)
    try:
        yield receipt
    finally:
        release_queue_lock(queue_root, receipt)


def write_expired_queue_lock_for_test(queue_root: Path) -> QueueLock:
    """Create one expired queue lock solely for deterministic recovery tests."""

    now = _utc_now()
    receipt = QueueLock(
        lock_id=uuid4().hex,
        process_id=0,
        acquired_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(minutes=1),
    )
    write_json_atomic(queue_root / ".lock.json", receipt.model_dump(mode="json"))
    return receipt
