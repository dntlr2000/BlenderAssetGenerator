"""Focused fail-closed tests for Autonomous Quality host failure recovery."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy.authorization import artifact_for
from codex_blender_modeler.autonomy.failure_recovery import (
    begin_host_attempt,
    classify_host_failure,
    publish_failure_terminal_receipt,
    record_host_attempt_failure,
)
from codex_blender_modeler.autonomy.models import (
    AutonomyArtifact,
    AutonomyBudget,
    BudgetUsage,
)


def _budget() -> AutonomyBudget:
    """Create a small immutable test budget with room for exactly two actions."""

    zero = "0" * 64
    return AutonomyBudget(
        budget_id="budget-failure-test",
        job_id="aq_failure_test",
        workflow_id="wf-failure-test",
        dispatch_id="dispatch-failure-test",
        input_sha256=zero,
        source_fingerprint=zero,
        provenance=[AutonomyArtifact(path="input/reference.png", sha256=zero)],
        global_action_limit=2,
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def _workspace(tmp_path: Path) -> tuple[Path, Path, AutonomyArtifact]:
    """Create one contained canonical input and autonomy session root."""

    root = tmp_path / "aq_failure_test"
    source = root / "analysis" / "scene_spec.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"schema_version":"0.2.0"}\n', encoding="utf-8")
    session_root = root / "production" / "autonomy" / "aq-session"
    session_root.mkdir(parents=True)
    return root, session_root, artifact_for(root, source)


def _begin(
    root: Path,
    session_root: Path,
    canonical: AutonomyArtifact,
    *,
    attempt_index: int = 1,
    budget_before: BudgetUsage | None = None,
    previous_failure: AutonomyArtifact | None = None,
    operation_kind: str = "host_execution",
):
    """Start one test attempt with stable identities and exact canonical evidence."""

    return begin_host_attempt(
        root=root,
        session_root=session_root,
        job_id="aq_failure_test",
        workflow_id="wf-failure-test",
        dispatch_id="dispatch-failure-test",
        session_id="aq-session",
        operation_id="build-candidate-01",
        action="build_candidate",
        operation_kind=operation_kind,  # type: ignore[arg-type]
        attempt_index=attempt_index,
        budget=_budget(),
        budget_before=budget_before or BudgetUsage(),
        canonical_inputs=[canonical],
        previous_failure=previous_failure,
    )


def test_failure_classifier_is_narrow_and_fail_closed() -> None:
    """Retry timeout and launch errors but classify validation failures deterministically."""

    timeout = classify_host_failure(
        subprocess.TimeoutExpired("blender", 5), operation_kind="host_execution"
    )
    launch = classify_host_failure(
        FileNotFoundError("blender unavailable"), operation_kind="process_launch"
    )
    schema = classify_host_failure(
        RuntimeError("invalid schema"), operation_kind="schema_validation"
    )
    topology = classify_host_failure(
        RuntimeError("non-manifold"), operation_kind="topology_validation"
    )
    unknown = classify_host_failure(
        RuntimeError("host exploded"), operation_kind="host_execution"
    )

    assert (timeout.failure_class, timeout.reason_code) == ("transient", "timeout")
    assert (launch.failure_class, launch.reason_code) == (
        "transient",
        "process_launch",
    )
    assert schema.failure_class == "deterministic"
    assert topology.failure_class == "deterministic"
    assert unknown.failure_class == "non_retryable_host"


def test_first_transient_failure_authorizes_exactly_one_budgeted_retry(
    tmp_path: Path,
) -> None:
    """Persist a first transient failure and reserve one action without canonical writes."""

    root, session_root, canonical = _workspace(tmp_path)
    intent, intent_artifact = _begin(root, session_root, canonical)
    failure, failure_artifact = record_host_attempt_failure(
        root=root,
        intent_artifact=intent_artifact,
        error=TimeoutError("candidate build timed out"),
    )

    assert intent.budget_after.total_actions == 1
    assert failure.retry_allowed is True
    assert failure.terminal_reason is None
    assert failure.canonical_inputs_unchanged is True
    assert failure_artifact.path.endswith("attempt-01/failure.json")
    with pytest.raises(FileExistsError):
        _begin(root, session_root, canonical)
    with pytest.raises(PermissionError):
        publish_failure_terminal_receipt(
            root=root,
            failure_artifact=failure_artifact,
        )


def test_identical_second_transient_failure_terminalizes_as_repeated(
    tmp_path: Path,
) -> None:
    """Stop after one retry and publish immutable repeated-failure evidence."""

    root, session_root, canonical = _workspace(tmp_path)
    first_intent, first_intent_artifact = _begin(root, session_root, canonical)
    first_failure, first_failure_artifact = record_host_attempt_failure(
        root=root,
        intent_artifact=first_intent_artifact,
        error=TimeoutError("same timeout"),
    )
    second_intent, second_intent_artifact = _begin(
        root,
        session_root,
        canonical,
        attempt_index=2,
        budget_before=first_intent.budget_after,
        previous_failure=first_failure_artifact,
    )
    second_failure, second_failure_artifact = record_host_attempt_failure(
        root=root,
        intent_artifact=second_intent_artifact,
        error=TimeoutError("same timeout"),
    )
    terminal, terminal_artifact = publish_failure_terminal_receipt(
        root=root,
        failure_artifact=second_failure_artifact,
    )

    assert first_failure.retry_allowed is True
    assert second_intent.budget_after.total_actions == 2
    assert second_failure.retry_allowed is False
    assert second_failure.identical_to_previous is True
    assert second_failure.reason_code == "repeated_identical_failure"
    assert second_failure.terminal_reason == "repeated_failure"
    assert terminal.reason == "repeated_failure"
    assert terminal.retry_exhausted is True
    assert terminal_artifact.path.endswith("terminal_failure.json")
    with pytest.raises(FileExistsError):
        publish_failure_terminal_receipt(
            root=root,
            failure_artifact=second_failure_artifact,
        )


@pytest.mark.parametrize(
    ("operation_kind", "error"),
    [
        ("schema_validation", RuntimeError("bad schema")),
        ("topology_validation", RuntimeError("bad topology")),
        ("host_execution", ValueError("deterministic validation")),
    ],
)
def test_deterministic_failures_never_authorize_retry(
    tmp_path: Path,
    operation_kind: str,
    error: Exception,
) -> None:
    """Fail closed immediately for schema, topology, and deterministic validation errors."""

    root, session_root, canonical = _workspace(tmp_path)
    intent, intent_artifact = _begin(
        root,
        session_root,
        canonical,
        operation_kind=operation_kind,
    )
    failure, failure_artifact = record_host_attempt_failure(
        root=root,
        intent_artifact=intent_artifact,
        error=error,
    )

    assert failure.retry_allowed is False
    assert failure.failure_class == "deterministic"
    assert failure.terminal_reason == "host_failure"
    with pytest.raises(PermissionError):
        _begin(
            root,
            session_root,
            canonical,
            attempt_index=2,
            budget_before=intent.budget_after,
            previous_failure=failure_artifact,
        )


def test_changed_canonical_input_blocks_transient_retry(tmp_path: Path) -> None:
    """Convert an otherwise transient failure into a canonical-conflict terminal."""

    root, session_root, canonical = _workspace(tmp_path)
    _intent, intent_artifact = _begin(root, session_root, canonical)
    (root / canonical.path).write_text('{"changed":true}\n', encoding="utf-8")
    failure, failure_artifact = record_host_attempt_failure(
        root=root,
        intent_artifact=intent_artifact,
        error=TimeoutError("timeout after an unexpected write"),
    )
    terminal, _terminal_artifact = publish_failure_terminal_receipt(
        root=root,
        failure_artifact=failure_artifact,
    )

    assert failure.failure_class == "canonical_conflict"
    assert failure.reason_code == "canonical_changed"
    assert failure.retry_allowed is False
    assert terminal.canonical_inputs_unchanged is False


def test_attempt_budget_exhaustion_writes_no_intent(tmp_path: Path) -> None:
    """Reject an attempt before publication when the immutable budget is exhausted."""

    root, session_root, canonical = _workspace(tmp_path)
    exhausted = BudgetUsage(total_actions=2)
    with pytest.raises(PermissionError, match="budget exhausted"):
        _begin(
            root,
            session_root,
            canonical,
            budget_before=exhausted,
        )
    assert not (session_root / "host_attempts").exists()


def test_second_attempt_rejects_budget_or_scope_splicing(tmp_path: Path) -> None:
    """Keep the only retry bound to the first attempt's exact budget and operation scope."""

    root, session_root, canonical = _workspace(tmp_path)
    first_intent, first_intent_artifact = _begin(root, session_root, canonical)
    _first_failure, first_failure_artifact = record_host_attempt_failure(
        root=root,
        intent_artifact=first_intent_artifact,
        error=TimeoutError("retryable timeout"),
    )

    with pytest.raises(PermissionError, match="scope or budget"):
        _begin(
            root,
            session_root,
            canonical,
            attempt_index=2,
            budget_before=BudgetUsage(total_actions=0),
            previous_failure=first_failure_artifact,
        )
    with pytest.raises(PermissionError, match="scope or budget"):
        _begin(
            root,
            session_root,
            canonical,
            attempt_index=2,
            budget_before=first_intent.budget_after,
            previous_failure=first_failure_artifact,
            operation_kind="process_launch",
        )
