"""Host-bound job-local write locks for V0.8 orchestration."""

from __future__ import annotations

import json
import os
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from ..blender_artifacts import write_json_atomic
from .models import WorkflowLock

_ProcessState = Literal["alive", "dead", "unknown"]


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
    """Move one expired, confirmed local-dead lock into immutable history."""

    history = path.parent / "stale_locks"
    history.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    destination = history / f"{stamp}_{lock.lock_id}.json"
    os.replace(path, destination)
    return destination


def _local_host_identity() -> str:
    """Return the non-empty local hostname used to classify workflow lock ownership."""

    hostname = socket.gethostname().strip()
    if not hostname:
        raise RuntimeError("Cannot acquire workflow lock without a local host identity")
    return hostname


def _windows_process_state(process_id: int) -> _ProcessState:
    """Classify one Windows PID with correctly typed process-handle APIs."""

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_invalid_parameter = 87
    error_not_found = 1168
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    get_exit_code_process = kernel32.GetExitCodeProcess
    get_exit_code_process.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    get_exit_code_process.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        error = ctypes.get_last_error()
        if error in {error_invalid_parameter, error_not_found}:
            return "dead"
        return "unknown"
    try:
        exit_code = wintypes.DWORD()
        if not get_exit_code_process(handle, ctypes.byref(exit_code)):
            return "unknown"
        return "alive" if exit_code.value == still_active else "dead"
    finally:
        close_handle(handle)


def _local_process_state(process_id: int) -> _ProcessState:
    """Classify a local PID while preserving uncertain checks as fail-closed."""

    if process_id <= 0:
        return "dead"
    if sys.platform == "win32":
        return _windows_process_state(process_id)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return "dead"
    except PermissionError:
        return "alive"
    except (OSError, OverflowError):
        return "unknown"
    return "alive"


def _recoverable_local_dead_owner(
    lock: WorkflowLock,
    local_host: str,
    now: datetime,
) -> bool:
    """Authorize recovery only after expiry and a conclusive local process death."""

    if lock.expires_at > now:
        return False
    if lock.owner_host is None:
        return False
    if lock.owner_host.casefold() != local_host.casefold():
        return False
    return _local_process_state(lock.process_id) == "dead"


@contextmanager
def _lock_transition_guard(lock_path: Path) -> Iterator[None]:
    """Serialize lock creation and stale recovery with an OS-released file lock."""

    guard_path = lock_path.parent / ".lock.guard"
    descriptor = os.open(guard_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if sys.platform == "win32":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError(
                    "Another workflow lock acquisition or recovery is already in progress"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(
                    "Another workflow lock acquisition or recovery is already in progress"
                ) from exc
        locked = True
        yield
    finally:
        if locked:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _create_lock_receipt(path: Path, payload: str) -> None:
    """Create and fully write one lock receipt without replacing an existing owner."""

    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload.encode("utf-8"))
    finally:
        os.close(descriptor)


def acquire_workflow_lock(
    job_root: Path,
    job_id: str,
    workflow_id: str,
    *,
    ttl_seconds: int = 900,
) -> WorkflowLock:
    """Acquire one lock, recovering only an expired, confirmed local-dead owner."""

    if ttl_seconds < 30 or ttl_seconds > 86400:
        raise ValueError("workflow lock TTL must be within [30, 86400] seconds")
    lock_path = job_root / "workflows" / ".lock.json"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now = _utc_now()
    local_host = _local_host_identity()
    receipt = WorkflowLock(
        lock_id=uuid4().hex,
        workflow_id=workflow_id,
        job_id=job_id,
        process_id=os.getpid(),
        owner_host=local_host,
        acquired_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    payload = receipt.model_dump_json(indent=2) + "\n"
    with _lock_transition_guard(lock_path):
        try:
            _create_lock_receipt(lock_path, payload)
        except FileExistsError:
            existing = _read_lock(lock_path)
            if not _recoverable_local_dead_owner(existing, local_host, _utc_now()):
                raise RuntimeError(
                    "Another workflow owns the job write lock; it is unexpired or its owner "
                    "is live, remote, or unknown, so manual recovery is required: "
                    f"workflow={existing.workflow_id} expires={existing.expires_at.isoformat()}"
                ) from None
            _archive_stale_lock(lock_path, existing)
            try:
                _create_lock_receipt(lock_path, payload)
            except FileExistsError as exc:
                raise RuntimeError(
                    f"Workflow lock changed during stale recovery: {lock_path}"
                ) from exc
    return receipt


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
    """Hold one host/PID-bound job lock for an atomic workflow transition."""

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
    """Create one expired local-dead lock only for deterministic recovery tests."""

    now = _utc_now()
    receipt = WorkflowLock(
        lock_id=uuid4().hex,
        workflow_id=workflow_id,
        job_id=job_id,
        process_id=0,
        owner_host=_local_host_identity(),
        acquired_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(minutes=1),
    )
    write_json_atomic(
        job_root / "workflows" / ".lock.json",
        receipt.model_dump(mode="json"),
    )
    return receipt
