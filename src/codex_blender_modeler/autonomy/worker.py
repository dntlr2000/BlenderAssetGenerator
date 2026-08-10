"""Single-writer lock and bounded supervisor helpers for autonomy sessions."""

from __future__ import annotations

import json
import os
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .io import ensure_autonomy_path

_ProcessState = Literal["alive", "dead", "unknown"]
_MINIMUM_LOCK_TTL_SECONDS = 1
_MAXIMUM_LOCK_TTL_SECONDS = 86_400


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for autonomy lock comparisons."""

    return datetime.now(UTC)


def _local_host_identity() -> str:
    """Return the non-empty hostname used to bind an autonomy lock to this host."""

    hostname = socket.gethostname().strip()
    if not hostname:
        raise RuntimeError("Cannot acquire autonomy lock without a local host identity")
    return hostname


def _parse_lock_timestamp(value: object, field_name: str) -> datetime:
    """Parse one timezone-aware lock timestamp and normalize it to UTC."""

    if not isinstance(value, str):
        raise ValueError(f"autonomy lock {field_name} must be a timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"autonomy lock {field_name} must include a UTC offset")
    return parsed.astimezone(UTC)


def _read_lock(path: Path) -> dict[str, Any]:
    """Load and strictly validate one lock before any recovery decision."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("autonomy lock root must be an object")
        if payload.get("schema_version") != "0.1.0":
            raise ValueError("autonomy lock schema version is unsupported")
        for field_name in ("lock_id", "owner_id", "host"):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"autonomy lock {field_name} must be non-empty")
        process_id = payload.get("pid")
        if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id <= 0:
            raise ValueError("autonomy lock pid must be a positive integer")
        acquired_at = _parse_lock_timestamp(payload.get("acquired_at"), "acquired_at")
        expires_at = _parse_lock_timestamp(payload.get("expires_at"), "expires_at")
        if expires_at <= acquired_at:
            raise ValueError("autonomy lock expiry must follow acquisition")
    except FileNotFoundError:
        raise
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Autonomy lock exists but is unreadable; inspect it before recovery: {path}"
        ) from exc
    return payload


def _windows_process_state(process_id: int) -> _ProcessState:
    """Classify one Windows PID without treating access failures as process death."""

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

    handle = open_process(process_query_limited_information, False, process_id)
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
        return "unknown"
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
    lock: dict[str, Any],
    local_host: str,
    now: datetime,
) -> bool:
    """Authorize recovery only for an expired same-host, conclusively dead owner."""

    expires_at = _parse_lock_timestamp(lock["expires_at"], "expires_at")
    if expires_at > now:
        return False
    owner_host = str(lock["host"])
    if owner_host.casefold() != local_host.casefold():
        return False
    return _local_process_state(int(lock["pid"])) == "dead"


@contextmanager
def _lock_transition_guard(job_root: Path, lock_path: Path) -> Iterator[None]:
    """Serialize autonomy lock creation, stale recovery, and release on this host."""

    guard_path = ensure_autonomy_path(
        job_root,
        lock_path.parent / ".autonomy.lock.guard",
        must_exist=False,
    )
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
                    "Another autonomy lock acquisition or recovery is already in progress"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError(
                    "Another autonomy lock acquisition or recovery is already in progress"
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


def _create_lock_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Create and fully write one lock receipt without replacing an owner."""

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")


def _archive_stale_lock(job_root: Path, lock_path: Path) -> Path:
    """Move one recoverable stale lock into contained immutable history."""

    history = ensure_autonomy_path(
        job_root,
        lock_path.parent / "stale_locks",
        must_exist=False,
    )
    history.mkdir(parents=False, exist_ok=True)
    ensure_autonomy_path(job_root, history, must_exist=True)
    stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    destination = ensure_autonomy_path(
        job_root,
        history / f"{stamp}_{uuid4().hex}.json",
        must_exist=False,
    )
    os.replace(lock_path, destination)
    return destination


def _release_session_lock(job_root: Path, lock_path: Path, lock_id: str) -> None:
    """Release only the exact autonomy lock created by the current context."""

    with _lock_transition_guard(job_root, lock_path):
        try:
            current = _read_lock(lock_path)
        except FileNotFoundError as exc:
            raise RuntimeError("autonomy session lock disappeared") from exc
        if current["lock_id"] != lock_id:
            raise RuntimeError("autonomy session lock ownership changed")
        lock_path.unlink()


@contextmanager
def autonomy_session_lock(
    job_root: Path,
    session_root: Path,
    *,
    owner_id: str,
    ttl_seconds: int = 900,
) -> Iterator[None]:
    """Hold one session lock and recover only an expired local-dead owner."""

    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not (
        _MINIMUM_LOCK_TTL_SECONDS
        <= ttl_seconds
        <= _MAXIMUM_LOCK_TTL_SECONDS
    ):
        raise ValueError(
            "autonomy lock TTL must be within "
            f"[{_MINIMUM_LOCK_TTL_SECONDS}, {_MAXIMUM_LOCK_TTL_SECONDS}] seconds"
        )
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise ValueError("autonomy lock owner_id is required")
    safe_session = ensure_autonomy_path(job_root, session_root, must_exist=True)
    lock_path = ensure_autonomy_path(
        job_root,
        safe_session / "autonomy.lock",
        must_exist=False,
    )
    now = _utc_now()
    local_host = _local_host_identity()
    payload = {
        "schema_version": "0.1.0",
        "lock_id": f"aq-lock-{uuid4().hex}",
        "owner_id": owner_id,
        "pid": os.getpid(),
        "host": local_host,
        "acquired_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
    }
    with _lock_transition_guard(job_root, lock_path):
        try:
            _create_lock_receipt(lock_path, payload)
        except FileExistsError:
            existing = _read_lock(lock_path)
            if not _recoverable_local_dead_owner(existing, local_host, _utc_now()):
                raise RuntimeError(
                    "Autonomy session already has an active writer lock; it is unexpired "
                    "or its owner is live, remote, or unknown, so manual recovery is required"
                ) from None
            _archive_stale_lock(job_root, lock_path)
            try:
                _create_lock_receipt(lock_path, payload)
            except FileExistsError as exc:
                raise RuntimeError(
                    "Autonomy session lock changed during stale recovery"
                ) from exc
    try:
        yield
    finally:
        _release_session_lock(job_root, lock_path, str(payload["lock_id"]))


def bounded_action_limit(requested: int, authorized: int) -> int:
    """Clamp supervisor work to a positive hard limit no greater than authorization."""

    if requested < 1:
        raise ValueError("autonomy-run requires at least one action")
    return min(requested, authorized)
