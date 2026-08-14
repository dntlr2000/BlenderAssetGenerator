"""Focused admission tests for append-only material retry supersessions."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialRetrySupersessionReceipt,
)
from codex_blender_modeler.material_retry_supersession import (
    MaterialRetryAdmissionArtifact,
    validate_material_retry_supersession_admission,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)


def _artifact(
    root: Path,
    relative: str,
    *,
    artifact_id: str,
    kind: str,
    payload: bytes,
) -> ExactArtifact:
    """Write and bind one exact session-owned supersession dependency."""

    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative,
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
        media_type="application/json",
    )


def _candidate(root: Path, session_id: str, name: str) -> ExactArtifact:
    """Create one exact retry plan that may be checked for executability."""

    return _artifact(
        root,
        f"production/autonomy_v2/{session_id}/retry_plans/{name}.json",
        artifact_id=name,
        kind="material_retry_plan",
        payload=f'{{"plan":"{name}"}}\n'.encode(),
    )


def _publish_receipt(
    root: Path,
    *,
    session_id: str,
    receipt_id: str,
    retry_plan: ExactArtifact,
    job_id: str | None = None,
    workflow_id: str = "fixture_workflow",
    dispatch_id: str = "fixture-dispatch",
) -> MaterialRetrySupersessionReceipt:
    """Publish one valid approved supersession receipt and all exact dependencies."""

    prefix = f"production/autonomy_v2/{session_id}"
    approval = _artifact(
        root,
        f"{prefix}/retry_approvals/{receipt_id}.txt",
        artifact_id=f"{receipt_id}-approval",
        kind="material_retry_approval",
        payload=f"approval:{receipt_id}\n".encode(),
    )
    current_state = _artifact(
        root,
        f"{prefix}/states/{receipt_id}.json",
        artifact_id=f"{receipt_id}-state",
        kind="aq_v2_state",
        payload=f'{{"state":"{receipt_id}"}}\n'.encode(),
    )
    report = _artifact(
        root,
        f"{prefix}/material_framework_failures/{receipt_id}/report.json",
        artifact_id=f"{receipt_id}-report",
        kind="material_framework_failure_report",
        payload=f'{{"report":"{receipt_id}"}}\n'.encode(),
    )
    receipt = MaterialRetrySupersessionReceipt(
        receipt_id=receipt_id,
        retry_plan=retry_plan,
        retry_approval=approval,
        current_state=current_state,
        framework_failure_report=report,
        supersession_reason="a newer framework-safe retry replaces these exact bytes",
        job_id=job_id or root.name,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        producer="tests.material_retry_supersession",
        producer_version="0.1.0",
        created_at=NOW,
    )
    receipt_path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "retry_supersessions"
        / receipt_id
        / "receipt.json"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=False)
    receipt_path.write_text(receipt.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return receipt


def _validate(
    root: Path,
    candidate: ExactArtifact,
    *,
    job_id: str | None = None,
) -> None:
    """Run the public admission guard for the shared fixture identity."""

    validate_material_retry_supersession_admission(
        root,
        candidate_artifacts=[
            MaterialRetryAdmissionArtifact(
                path=candidate.path,
                sha256=candidate.sha256,
                byte_size=candidate.byte_size,
            )
        ],
        job_id=job_id or root.name,
        workflow_id="fixture_workflow",
        dispatch_id="fixture-dispatch",
        session_id="fixture-session",
    )


def test_legacy_session_without_supersession_root_retains_admission(tmp_path: Path) -> None:
    """Preserve legacy execution semantics when no supersession root ever existed."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    candidate = _candidate(root, "fixture-session", "legacy-retry")

    _validate(root, candidate)


def test_exact_superseded_retry_is_non_executable_but_unrelated_retry_remains_valid(
    tmp_path: Path,
) -> None:
    """Block only an exact path/hash/size match after validating all receipt bytes."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    blocked = _candidate(root, "fixture-session", "blocked-retry")
    unrelated = _candidate(root, "fixture-session", "unrelated-retry")
    _publish_receipt(
        root,
        session_id="fixture-session",
        receipt_id="blocked-supersession",
        retry_plan=blocked,
    )

    _validate(root, unrelated)
    with pytest.raises(PermissionError, match="exact bytes were superseded"):
        _validate(root, blocked)


def test_admission_identity_does_not_depend_on_job_root_basename(tmp_path: Path) -> None:
    """Scope receipts by their strict identity even when the host uses a staging root."""

    root = tmp_path / "arbitrary_staging_root"
    root.mkdir()
    blocked = _candidate(root, "fixture-session", "blocked-retry")
    unrelated = _candidate(root, "fixture-session", "unrelated-retry")
    _publish_receipt(
        root,
        session_id="fixture-session",
        receipt_id="blocked-supersession",
        retry_plan=blocked,
        job_id="fixture_job",
    )

    _validate(root, unrelated, job_id="fixture_job")
    with pytest.raises(PermissionError, match="exact bytes were superseded"):
        _validate(root, blocked, job_id="fixture_job")


@pytest.mark.parametrize("failure_mode", ["malformed", "tampered", "wrong_scope"])
def test_invalid_supersession_root_fails_closed(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    """Reject malformed, dependency-tampered, or identity-spliced receipt roots."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    candidate = _candidate(root, "fixture-session", "candidate")
    unrelated = _candidate(root, "fixture-session", "receipt-plan")
    receipt = _publish_receipt(
        root,
        session_id="fixture-session",
        receipt_id="invalid-supersession",
        retry_plan=unrelated,
        workflow_id=("other_workflow" if failure_mode == "wrong_scope" else "fixture_workflow"),
    )
    receipt_path = (
        root
        / "production"
        / "autonomy_v2"
        / "fixture-session"
        / "retry_supersessions"
        / receipt.receipt_id
        / "receipt.json"
    )
    if failure_mode == "malformed":
        receipt_path.write_bytes(b"not-json\n")
    elif failure_mode == "tampered":
        root.joinpath(*receipt.current_state.path.split("/")).write_bytes(b"tampered\n")

    with pytest.raises(ValueError, match="material retry supersession"):
        _validate(root, candidate)


def test_duplicate_exact_supersessions_are_ambiguous_and_fail_closed(tmp_path: Path) -> None:
    """Reject two current receipts that both claim the same exact retry plan."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    candidate = _candidate(root, "fixture-session", "duplicate-retry")
    for receipt_id in ("supersession-one", "supersession-two"):
        _publish_receipt(
            root,
            session_id="fixture-session",
            receipt_id=receipt_id,
            retry_plan=candidate,
        )

    with pytest.raises(ValueError, match="ambiguous"):
        _validate(root, candidate)
