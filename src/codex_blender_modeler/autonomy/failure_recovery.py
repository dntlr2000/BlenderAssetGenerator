"""Fail-closed classification and one-retry evidence for AQ host operations."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..stabilization.models import PortableId, Sha256
from .authorization import artifact_for, canonical_digest
from .budget import consume_budget
from .io import write_immutable_json
from .models import (
    AutonomyArtifact,
    AutonomyBudget,
    AutonomyEvidenceContract,
    BudgetUsage,
    TerminalReason,
)

FailureOperationKind = Literal[
    "process_launch",
    "host_execution",
    "schema_validation",
    "topology_validation",
]
FailureClass = Literal[
    "transient",
    "deterministic",
    "non_retryable_host",
    "canonical_conflict",
]
FailureReasonCode = Literal[
    "timeout",
    "process_launch",
    "schema_validation",
    "topology_validation",
    "deterministic_validation",
    "host_exception",
    "canonical_changed",
    "retry_exhausted",
    "repeated_identical_failure",
]


@dataclass(frozen=True)
class FailureClassification:
    """Describe a sanitized deterministic classification without persisting error text."""

    failure_class: FailureClass
    reason_code: FailureReasonCode
    exception_type: str
    failure_fingerprint: str


class HostAttemptIntent(AutonomyEvidenceContract):
    """Authorize one pre-canonical host attempt and reserve its exact budget usage."""

    operation_id: PortableId
    session_id: PortableId
    action: str = Field(min_length=1, max_length=128)
    operation_kind: FailureOperationKind
    attempt_index: int = Field(ge=1, le=2)
    maximum_attempts: Literal[2] = 2
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    budget_increments: dict[str, int]
    canonical_inputs: list[AutonomyArtifact] = Field(min_length=1)
    canonical_source_fingerprint: Sha256
    previous_failure: AutonomyArtifact | None = None
    canonical_mutation_started: Literal[False] = False

    @model_validator(mode="after")
    def validate_attempt_chain(self) -> HostAttemptIntent:
        """Require exactly one predecessor only for the second and final attempt."""

        if self.attempt_index == 1 and self.previous_failure is not None:
            raise ValueError("first host attempt cannot have a previous failure")
        if self.attempt_index == 2 and self.previous_failure is None:
            raise ValueError("second host attempt requires the first failure receipt")
        if self.budget_after.total_actions != self.budget_before.total_actions + 1:
            raise ValueError("every host attempt must consume exactly one action")
        return self


class HostAttemptFailure(AutonomyEvidenceContract):
    """Record one immutable failed attempt and its bounded retry decision."""

    failure_id: PortableId
    operation_id: PortableId
    session_id: PortableId
    attempt_index: int = Field(ge=1, le=2)
    attempt_intent: AutonomyArtifact
    operation_kind: FailureOperationKind
    failure_class: FailureClass
    reason_code: FailureReasonCode
    exception_type: str = Field(min_length=1, max_length=256)
    failure_fingerprint: Sha256
    canonical_inputs_unchanged: bool
    budget_after: BudgetUsage
    previous_failure: AutonomyArtifact | None = None
    identical_to_previous: bool = False
    retry_allowed: bool
    terminal_reason: TerminalReason | None = None

    @model_validator(mode="after")
    def validate_retry_decision(self) -> HostAttemptFailure:
        """Allow retry only for the first unchanged transient failure."""

        expected_retry = (
            self.failure_class == "transient"
            and self.attempt_index == 1
            and self.canonical_inputs_unchanged
            and not self.identical_to_previous
        )
        if self.retry_allowed != expected_retry:
            raise ValueError("host retry decision violates the bounded retry policy")
        if self.retry_allowed and self.terminal_reason is not None:
            raise ValueError("retryable failure cannot carry a terminal reason")
        if not self.retry_allowed and self.terminal_reason is None:
            raise ValueError("non-retryable failure requires a terminal reason")
        return self


class HostFailureTerminalReceipt(AutonomyEvidenceContract):
    """Bind one non-retryable failure to a fail-closed terminal recommendation."""

    terminal_failure_id: PortableId
    operation_id: PortableId
    session_id: PortableId
    status: Literal["failed"] = "failed"
    reason: TerminalReason
    final_failure: AutonomyArtifact
    budget_usage: BudgetUsage
    canonical_inputs_unchanged: bool
    retry_exhausted: bool
    canonical_mutation_permitted: Literal[False] = False


def _utc_now() -> datetime:
    """Return one timezone-aware UTC timestamp for immutable failure evidence."""

    return datetime.now(UTC)


def _normalized_error_digest(error: Exception) -> str:
    """Hash normalized diagnostic text without persisting paths or raw host output."""

    text = " ".join(str(error).split()).casefold()
    text = re.sub(r"[a-z]:[/\\][^\s]+", "<path>", text)
    text = re.sub(r"/(?:[^\s/]+/)+[^\s]+", "<path>", text)
    text = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        "<uuid>",
        text,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify_host_failure(
    error: Exception,
    *,
    operation_kind: FailureOperationKind,
) -> FailureClassification:
    """Classify only timeout and process-launch failures as one-retry transient."""

    exception_type = f"{type(error).__module__}.{type(error).__qualname__}"
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        failure_class: FailureClass = "transient"
        reason_code: FailureReasonCode = "timeout"
    elif operation_kind == "process_launch" and isinstance(
        error, (OSError, subprocess.SubprocessError)
    ):
        failure_class = "transient"
        reason_code = "process_launch"
    elif operation_kind == "schema_validation":
        failure_class = "deterministic"
        reason_code = "schema_validation"
    elif operation_kind == "topology_validation":
        failure_class = "deterministic"
        reason_code = "topology_validation"
    elif isinstance(error, (ValueError, json.JSONDecodeError)):
        failure_class = "deterministic"
        reason_code = "deterministic_validation"
    else:
        failure_class = "non_retryable_host"
        reason_code = "host_exception"
    fingerprint = canonical_digest(
        {
            "failure_class": failure_class,
            "reason_code": reason_code,
            "exception_type": exception_type,
            "message_digest": _normalized_error_digest(error),
        }
    )
    return FailureClassification(
        failure_class=failure_class,
        reason_code=reason_code,
        exception_type=exception_type,
        failure_fingerprint=fingerprint,
    )


def _verify_exact_artifact(root: Path, artifact: AutonomyArtifact) -> None:
    """Fail closed when one bound artifact is missing, escaped, linked, or changed."""

    path = root / artifact.path
    if path.is_symlink():
        raise ValueError(f"linked autonomy evidence is forbidden: {artifact.path}")
    if artifact_for(root, path) != artifact:
        raise ValueError(f"autonomy artifact is stale or tampered: {artifact.path}")


def _load_exact_model(
    root: Path,
    artifact: AutonomyArtifact,
    model_type: type[HostAttemptIntent] | type[HostAttemptFailure],
) -> HostAttemptIntent | HostAttemptFailure:
    """Load one exact failure contract only after verifying its immutable bytes."""

    _verify_exact_artifact(root, artifact)
    path = root / artifact.path
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def _attempt_path(session_root: Path, operation_id: str, attempt_index: int) -> Path:
    """Return the workflow-owned immutable intent path for one bounded attempt."""

    return (
        session_root
        / "host_attempts"
        / operation_id
        / f"attempt-{attempt_index:02d}"
        / "intent.json"
    )


def begin_host_attempt(
    *,
    root: Path,
    session_root: Path,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    operation_id: str,
    action: str,
    operation_kind: FailureOperationKind,
    attempt_index: int,
    budget: AutonomyBudget,
    budget_before: BudgetUsage,
    canonical_inputs: list[AutonomyArtifact],
    budget_increments: dict[str, int] | None = None,
    previous_failure: AutonomyArtifact | None = None,
) -> tuple[HostAttemptIntent, AutonomyArtifact]:
    """Publish a pre-mutation attempt intent after reserving one bounded action."""

    if (budget.job_id, budget.workflow_id, budget.dispatch_id) != (
        job_id,
        workflow_id,
        dispatch_id,
    ):
        raise ValueError("host attempt identity differs from the immutable budget")
    if not canonical_inputs:
        raise ValueError("host attempt requires at least one canonical input")
    for artifact in canonical_inputs:
        _verify_exact_artifact(root, artifact)
    increments = dict(budget_increments or {})
    if "total_actions" in increments:
        raise ValueError("total_actions is reserved by the host-attempt policy")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in increments.values()
    ):
        raise ValueError("host-attempt budget increments must be non-negative integers")
    decision = consume_budget(
        budget,
        budget_before,
        total_actions=1,
        **increments,
    )
    if not decision.allowed:
        raise PermissionError(
            f"autonomy host-attempt budget exhausted: {decision.exhausted_dimension}"
        )
    prior: HostAttemptFailure | None = None
    if attempt_index == 2:
        if previous_failure is None:
            raise ValueError("second host attempt requires a previous failure")
        loaded = _load_exact_model(root, previous_failure, HostAttemptFailure)
        assert isinstance(loaded, HostAttemptFailure)
        prior = loaded
        loaded_intent = _load_exact_model(root, prior.attempt_intent, HostAttemptIntent)
        assert isinstance(loaded_intent, HostAttemptIntent)
        if (
            prior.operation_id != operation_id
            or prior.session_id != session_id
            or prior.attempt_index != 1
            or not prior.retry_allowed
        ):
            raise PermissionError("previous failure does not authorize one retry")
        if (
            (prior.job_id, prior.workflow_id, prior.dispatch_id)
            != (job_id, workflow_id, dispatch_id)
            or prior.budget_after != budget_before
            or loaded_intent.action != action
            or loaded_intent.operation_kind != operation_kind
            or loaded_intent.canonical_inputs != canonical_inputs
        ):
            raise PermissionError("retry scope or budget differs from the first attempt")
    elif attempt_index != 1:
        raise ValueError("host attempt index must be one or two")
    elif previous_failure is not None:
        raise ValueError("first host attempt cannot bind a previous failure")

    now = _utc_now()
    canonical_source_fingerprint = canonical_digest(
        [item.model_dump(mode="json") for item in canonical_inputs]
    )
    input_sha256 = canonical_digest(
        {
            "canonical_source_fingerprint": canonical_source_fingerprint,
            "budget_before": budget_before.model_dump(mode="json"),
            "operation_id": operation_id,
            "attempt_index": attempt_index,
            "previous_failure": previous_failure.sha256 if previous_failure else None,
        }
    )
    intent = HostAttemptIntent(
        contract_id=f"attempt-{operation_id}-{attempt_index:02d}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=input_sha256,
        source_fingerprint=canonical_digest(
            {
                "input": input_sha256,
                "budget_after": decision.usage.model_dump(mode="json"),
                "operation_kind": operation_kind,
            }
        ),
        producer="codex_blender_modeler.autonomy.failure_recovery",
        producer_version="0.1.0",
        provenance=[*canonical_inputs, *([previous_failure] if previous_failure else [])],
        created_at=now,
        operation_id=operation_id,
        session_id=session_id,
        action=action,
        operation_kind=operation_kind,
        attempt_index=attempt_index,
        budget_before=budget_before,
        budget_after=decision.usage,
        budget_increments={"total_actions": 1, **increments},
        canonical_inputs=canonical_inputs,
        canonical_source_fingerprint=canonical_source_fingerprint,
        previous_failure=previous_failure,
    )
    path = _attempt_path(session_root, operation_id, attempt_index)
    write_immutable_json(root, path, intent.model_dump(mode="json"))
    return intent, artifact_for(root, path)


def record_host_attempt_failure(
    *,
    root: Path,
    intent_artifact: AutonomyArtifact,
    error: Exception,
) -> tuple[HostAttemptFailure, AutonomyArtifact]:
    """Publish one immutable failure and permit only a first unchanged transient retry."""

    loaded = _load_exact_model(root, intent_artifact, HostAttemptIntent)
    assert isinstance(loaded, HostAttemptIntent)
    intent = loaded
    canonical_unchanged = True
    for artifact in intent.canonical_inputs:
        try:
            _verify_exact_artifact(root, artifact)
        except (FileNotFoundError, OSError, ValueError):
            canonical_unchanged = False
            break
    classification = classify_host_failure(error, operation_kind=intent.operation_kind)
    previous: HostAttemptFailure | None = None
    if intent.previous_failure is not None:
        prior = _load_exact_model(root, intent.previous_failure, HostAttemptFailure)
        assert isinstance(prior, HostAttemptFailure)
        previous = prior
    identical = bool(
        previous
        and previous.failure_fingerprint == classification.failure_fingerprint
    )
    failure_class = classification.failure_class
    reason_code = classification.reason_code
    if not canonical_unchanged:
        failure_class = "canonical_conflict"
        reason_code = "canonical_changed"
    elif identical:
        reason_code = "repeated_identical_failure"
    elif intent.attempt_index == 2:
        reason_code = "retry_exhausted"
    retry_allowed = (
        failure_class == "transient"
        and intent.attempt_index == 1
        and canonical_unchanged
        and not identical
    )
    terminal_reason: TerminalReason | None = None
    if not retry_allowed:
        terminal_reason = "repeated_failure" if identical else "host_failure"
    now = _utc_now()
    failure = HostAttemptFailure(
        contract_id=f"failure-{intent.operation_id}-{intent.attempt_index:02d}",
        failure_id=f"failure-{intent.operation_id}-{intent.attempt_index:02d}",
        job_id=intent.job_id,
        workflow_id=intent.workflow_id,
        dispatch_id=intent.dispatch_id,
        input_sha256=intent_artifact.sha256,
        source_fingerprint=canonical_digest(
            {
                "intent": intent_artifact.sha256,
                "failure": classification.failure_fingerprint,
                "failure_class": failure_class,
                "reason_code": reason_code,
                "canonical_unchanged": canonical_unchanged,
                "previous": (
                    intent.previous_failure.sha256 if intent.previous_failure else None
                ),
            }
        ),
        producer="codex_blender_modeler.autonomy.failure_recovery",
        producer_version="0.1.0",
        provenance=[
            intent_artifact,
            *([intent.previous_failure] if intent.previous_failure else []),
        ],
        created_at=now,
        operation_id=intent.operation_id,
        session_id=intent.session_id,
        attempt_index=intent.attempt_index,
        attempt_intent=intent_artifact,
        operation_kind=intent.operation_kind,
        failure_class=failure_class,
        reason_code=reason_code,
        exception_type=classification.exception_type,
        failure_fingerprint=classification.failure_fingerprint,
        canonical_inputs_unchanged=canonical_unchanged,
        budget_after=intent.budget_after,
        previous_failure=intent.previous_failure,
        identical_to_previous=identical,
        retry_allowed=retry_allowed,
        terminal_reason=terminal_reason,
    )
    intent_path = root / intent_artifact.path
    path = intent_path.with_name("failure.json")
    write_immutable_json(root, path, failure.model_dump(mode="json"))
    return failure, artifact_for(root, path)


def publish_failure_terminal_receipt(
    *,
    root: Path,
    failure_artifact: AutonomyArtifact,
) -> tuple[HostFailureTerminalReceipt, AutonomyArtifact]:
    """Publish an operation-local terminal receipt only after retry is forbidden."""

    loaded = _load_exact_model(root, failure_artifact, HostAttemptFailure)
    assert isinstance(loaded, HostAttemptFailure)
    failure = loaded
    if failure.retry_allowed or failure.terminal_reason is None:
        raise PermissionError("retryable failure cannot be terminalized")
    now = _utc_now()
    terminal = HostFailureTerminalReceipt(
        contract_id=f"failure-terminal-{failure.operation_id}",
        terminal_failure_id=f"failure-terminal-{failure.operation_id}",
        job_id=failure.job_id,
        workflow_id=failure.workflow_id,
        dispatch_id=failure.dispatch_id,
        input_sha256=failure_artifact.sha256,
        source_fingerprint=canonical_digest(
            {
                "failure": failure_artifact.sha256,
                "budget": failure.budget_after.model_dump(mode="json"),
                "reason": failure.terminal_reason,
            }
        ),
        producer="codex_blender_modeler.autonomy.failure_recovery",
        producer_version="0.1.0",
        provenance=[failure_artifact, *failure.provenance],
        created_at=now,
        operation_id=failure.operation_id,
        session_id=failure.session_id,
        reason=failure.terminal_reason,
        final_failure=failure_artifact,
        budget_usage=failure.budget_after,
        canonical_inputs_unchanged=failure.canonical_inputs_unchanged,
        retry_exhausted=failure.attempt_index == 2,
    )
    operation_root = (root / failure_artifact.path).parent.parent
    path = operation_root / "terminal_failure.json"
    write_immutable_json(root, path, terminal.model_dump(mode="json"))
    return terminal, artifact_for(root, path)
