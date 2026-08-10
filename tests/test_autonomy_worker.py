"""Focused crash-recovery tests for autonomy session writer locks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy import worker


def _session_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create one contained autonomy session and return its lock paths."""

    job_root = tmp_path / "job"
    session_root = job_root / "production" / "autonomy" / "aq-session"
    session_root.mkdir(parents=True)
    return job_root, session_root, session_root / "autonomy.lock"


def _lock_payload(
    *,
    host: str,
    expired: bool,
    process_id: int = 424_242,
) -> dict[str, object]:
    """Build one structurally valid prior-owner receipt for a lock test."""

    now = datetime.now(UTC)
    acquired_at = now - timedelta(minutes=2)
    expires_at = now - timedelta(minutes=1) if expired else now + timedelta(minutes=1)
    return {
        "schema_version": "0.1.0",
        "lock_id": "aq-lock-prior-owner",
        "owner_id": "prior-owner",
        "pid": process_id,
        "host": host,
        "acquired_at": acquired_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def _write_lock(lock_path: Path, payload: dict[str, object]) -> bytes:
    """Write one deterministic lock receipt and return its exact evidence bytes."""

    evidence = (json.dumps(payload, sort_keys=True) + "\n").encode()
    lock_path.write_bytes(evidence)
    return evidence


def test_session_lock_recovers_expired_same_host_dead_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Archive and replace only an expired same-host lock whose PID is dead."""

    job_root, session_root, lock_path = _session_paths(tmp_path)
    prior = _lock_payload(host=worker._local_host_identity(), expired=True)
    prior_evidence = _write_lock(lock_path, prior)
    monkeypatch.setattr(worker, "_local_process_state", lambda _pid: "dead")

    with worker.autonomy_session_lock(
        job_root,
        session_root,
        owner_id="replacement-owner",
        ttl_seconds=60,
    ):
        current = json.loads(lock_path.read_text(encoding="utf-8"))
        assert current["lock_id"] != prior["lock_id"]
        assert current["owner_id"] == "replacement-owner"
        assert datetime.fromisoformat(current["expires_at"]) > datetime.fromisoformat(
            current["acquired_at"]
        )
        archives = list((session_root / "stale_locks").glob("*.json"))
        assert len(archives) == 1
        assert archives[0].read_bytes() == prior_evidence

    assert not lock_path.exists()


@pytest.mark.parametrize(
    ("host_kind", "expired", "process_state"),
    [
        ("local", False, "dead"),
        ("local", True, "alive"),
        ("local", True, "unknown"),
        ("remote", True, "dead"),
        ("unknown", True, "dead"),
    ],
    ids=[
        "unexpired-dead-owner",
        "expired-live-owner",
        "expired-unknown-pid-state",
        "expired-remote-owner",
        "expired-unknown-host",
    ],
)
def test_session_lock_recovery_failures_preserve_owner_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host_kind: str,
    expired: bool,
    process_state: worker._ProcessState,
) -> None:
    """Keep unexpired, live, remote, or uncertain ownership fail-closed."""

    job_root, session_root, lock_path = _session_paths(tmp_path)
    local_host = worker._local_host_identity()
    owner_host = {
        "local": local_host,
        "remote": f"remote-{local_host}",
        "unknown": "unknown",
    }[host_kind]
    original = _write_lock(
        lock_path,
        _lock_payload(host=owner_host, expired=expired),
    )
    monkeypatch.setattr(worker, "_local_process_state", lambda _pid: process_state)

    with pytest.raises(RuntimeError, match="manual recovery is required"):
        with worker.autonomy_session_lock(
            job_root,
            session_root,
            owner_id="blocked-contender",
            ttl_seconds=60,
        ):
            pytest.fail("an unsafe prior owner must never be replaced")

    assert lock_path.read_bytes() == original
    assert not (session_root / "stale_locks").exists()


def test_session_lock_rejects_legacy_or_unreadable_owner_evidence(
    tmp_path: Path,
) -> None:
    """Require manual recovery when prior evidence cannot prove expiry and ownership."""

    job_root, session_root, lock_path = _session_paths(tmp_path)
    legacy = _lock_payload(host=worker._local_host_identity(), expired=True)
    legacy.pop("expires_at")
    original = _write_lock(lock_path, legacy)

    with pytest.raises(RuntimeError, match="unreadable; inspect it before recovery"):
        with worker.autonomy_session_lock(
            job_root,
            session_root,
            owner_id="blocked-contender",
            ttl_seconds=60,
        ):
            pytest.fail("legacy evidence without expiry must remain fail-closed")

    assert lock_path.read_bytes() == original
    assert not (session_root / "stale_locks").exists()


def test_session_lock_refuses_a_concurrent_live_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve the active-writer rejection behavior for a current lock owner."""

    job_root, session_root, lock_path = _session_paths(tmp_path)
    monkeypatch.setattr(worker, "_local_process_state", lambda _pid: "alive")

    with worker.autonomy_session_lock(
        job_root,
        session_root,
        owner_id="active-owner",
        ttl_seconds=60,
    ):
        active_evidence = lock_path.read_bytes()
        with pytest.raises(RuntimeError, match="manual recovery is required"):
            with worker.autonomy_session_lock(
                job_root,
                session_root,
                owner_id="concurrent-owner",
                ttl_seconds=60,
            ):
                pytest.fail("a concurrent writer must never acquire the session")
        assert lock_path.read_bytes() == active_evidence

    assert not lock_path.exists()
