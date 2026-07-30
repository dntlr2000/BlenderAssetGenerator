"""Strict V0.9 contracts for release evidence, workspace audits, and local queues."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.9.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
JOB_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
WORKFLOW_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
PORTABLE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"


def _validate_relative_path(value: str) -> str:
    """Require a normalized POSIX path that cannot escape its declared root."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty normalized POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative, not absolute")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
WorkflowId = Annotated[str, Field(pattern=WORKFLOW_ID_PATTERN)]
PortableId = Annotated[str, Field(pattern=PORTABLE_ID_PATTERN)]
RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]

AuditSeverity = Literal["info", "warning", "error"]
AuditStatus = Literal["passed", "warning", "failed"]
MigrationStatus = Literal[
    "current",
    "compatible_legacy",
    "unsupported_future",
    "corrupt",
]
HandoffAuditStatus = Literal["not_requested", "generated", "valid", "invalid", "stale"]
VisualConvergenceAuditStatus = Literal["not_requested", "active", "valid", "invalid"]
QueueEntryStatus = Literal[
    "queued",
    "running",
    "waiting",
    "completed",
    "failed",
    "cancelled",
]
QueueOutcome = Literal["advanced", "waiting", "completed", "failed", "cancelled"]


class V09StrictModel(BaseModel):
    """Reject undeclared fields and non-finite floats in V0.9 contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ContractVersionRecord(V09StrictModel):
    """Record one preserved project contract boundary without rewriting old data."""

    contract: str = Field(min_length=1, max_length=96)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")


class EvidenceReference(V09StrictModel):
    """Bind one contained evidence file by portable path and exact digest."""

    evidence_id: PortableId
    kind: Literal[
        "blender_compatibility",
        "workspace_audit",
        "test_summary",
        "release_gate",
        "environment_probe",
    ]
    path: RelativePath
    sha256: Sha256


class EnvironmentProbeReport(V09StrictModel):
    """Describe the detected host without turning detection into a support claim."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    probe_id: PortableId
    project_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    platform_system: str = Field(min_length=1, max_length=64)
    platform_release: str = Field(min_length=1, max_length=128)
    architecture: str = Field(min_length=1, max_length=64)
    python_version: str = Field(min_length=1, max_length=64)
    blender_executable_name: str = Field(min_length=1, max_length=260)
    workspace_mode: Literal["repository_default", "external_configured"]
    blender_report_status: Literal["missing", "valid", "invalid"]
    blender_version: str | None = Field(default=None, max_length=64)
    blender_compatibility_ok: bool | None = None
    contracts: list[ContractVersionRecord] = Field(min_length=1)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    feature_flags: dict[str, bool | str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime

    @model_validator(mode="after")
    def validate_blender_evidence(self) -> EnvironmentProbeReport:
        """Keep Blender status, version, and compatibility claims internally consistent."""

        if self.blender_report_status == "valid":
            if self.blender_version is None or self.blender_compatibility_ok is None:
                raise ValueError("valid Blender evidence requires version and ok status")
        elif self.blender_version is not None or self.blender_compatibility_ok is not None:
            raise ValueError("missing or invalid Blender evidence cannot claim a result")
        return self


class AuditFinding(V09StrictModel):
    """Report one actionable workspace integrity or migration observation."""

    finding_id: PortableId
    severity: AuditSeverity
    code: str = Field(pattern=r"^[A-Z0-9_]{3,96}$")
    job_id: JobId | None = None
    path: RelativePath | None = None
    message: str = Field(min_length=1, max_length=2000)
    remediation: str | None = Field(default=None, min_length=1, max_length=2000)


class JobAudit(V09StrictModel):
    """Summarize one job without mutating or migrating its canonical artifacts."""

    job_id: JobId
    status: AuditStatus
    migration_status: MigrationStatus
    project_version_created: str | None = Field(default=None, max_length=64)
    source_count: int = Field(default=0, ge=0)
    verified_source_count: int = Field(default=0, ge=0)
    workflow_count: int = Field(default=0, ge=0)
    handoff_count: int = Field(default=0, ge=0)
    valid_handoff_count: int = Field(default=0, ge=0)
    handoff_status: HandoffAuditStatus = "not_requested"
    visual_convergence_session_count: int = Field(default=0, ge=0)
    valid_visual_convergence_session_count: int = Field(default=0, ge=0)
    visual_convergence_status: VisualConvergenceAuditStatus = "not_requested"
    findings: list[AuditFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts_and_status(self) -> JobAudit:
        """Require verified inputs and finding severity to agree with the summary."""

        if self.verified_source_count > self.source_count:
            raise ValueError("verified source count cannot exceed source count")
        if self.valid_handoff_count > self.handoff_count:
            raise ValueError("valid handoff count cannot exceed handoff count")
        if (
            self.valid_visual_convergence_session_count
            > self.visual_convergence_session_count
        ):
            raise ValueError(
                "valid visual convergence count cannot exceed session count"
            )
        if self.handoff_count == 0 and self.handoff_status != "not_requested":
            raise ValueError("jobs without handoffs must report not_requested")
        if self.handoff_count > 0 and self.handoff_status == "not_requested":
            raise ValueError("jobs with handoffs cannot report not_requested")
        if (
            self.visual_convergence_session_count == 0
            and self.visual_convergence_status != "not_requested"
        ):
            raise ValueError(
                "jobs without visual convergence sessions must report not_requested"
            )
        if (
            self.visual_convergence_session_count > 0
            and self.visual_convergence_status == "not_requested"
        ):
            raise ValueError(
                "jobs with visual convergence sessions cannot report not_requested"
            )
        has_error = any(item.severity == "error" for item in self.findings)
        has_warning = any(item.severity == "warning" for item in self.findings)
        expected = "failed" if has_error else "warning" if has_warning else "passed"
        if self.status != expected:
            raise ValueError("job audit status must reflect its highest finding severity")
        return self


class WorkspaceAuditReport(V09StrictModel):
    """Persist one bounded read-only audit of job evidence and workflow receipts."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    audit_id: PortableId
    project_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    workspace_mode: Literal["repository_default", "external_configured"]
    job_filter: JobId | None = None
    scan_limit: int = Field(ge=100, le=1_000_000)
    scanned_file_count: int = Field(ge=0)
    scanned_job_count: int = Field(ge=0)
    passed_job_count: int = Field(ge=0)
    warning_job_count: int = Field(ge=0)
    failed_job_count: int = Field(ge=0)
    handoff_count: int = Field(default=0, ge=0)
    valid_handoff_count: int = Field(default=0, ge=0)
    visual_convergence_session_count: int = Field(default=0, ge=0)
    valid_visual_convergence_session_count: int = Field(default=0, ge=0)
    status: AuditStatus
    jobs: list[JobAudit] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_summary(self) -> WorkspaceAuditReport:
        """Require audit counts, time ordering, and aggregate status to be exact."""

        counts = (
            self.passed_job_count + self.warning_job_count + self.failed_job_count
        )
        if counts != self.scanned_job_count or len(self.jobs) != self.scanned_job_count:
            raise ValueError("workspace audit job counts do not match job records")
        if self.handoff_count != sum(item.handoff_count for item in self.jobs):
            raise ValueError("workspace handoff count does not match job records")
        if self.valid_handoff_count != sum(
            item.valid_handoff_count for item in self.jobs
        ):
            raise ValueError("workspace valid handoff count does not match job records")
        if self.visual_convergence_session_count != sum(
            item.visual_convergence_session_count for item in self.jobs
        ):
            raise ValueError(
                "workspace visual convergence count does not match job records"
            )
        if self.valid_visual_convergence_session_count != sum(
            item.valid_visual_convergence_session_count for item in self.jobs
        ):
            raise ValueError(
                "workspace valid visual convergence count does not match job records"
            )
        if self.completed_at < self.started_at:
            raise ValueError("workspace audit completion cannot precede its start")
        all_findings = self.findings + [item for job in self.jobs for item in job.findings]
        has_error = any(item.severity == "error" for item in all_findings)
        has_warning = any(item.severity == "warning" for item in all_findings)
        expected = "failed" if has_error else "warning" if has_warning else "passed"
        if self.status != expected:
            raise ValueError("workspace audit status must reflect all finding severities")
        return self


class QueueEntry(V09StrictModel):
    """Track one existing V0.8 workflow without granting new modeling authority."""

    entry_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    status: QueueEntryStatus = "queued"
    priority: int = Field(default=50, ge=0, le=100)
    attempt_count: int = Field(default=0, ge=0, le=1000)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_failed_once: bool = False
    enqueued_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lease_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    lease_expires_at: datetime | None = None
    last_workflow_status: str | None = Field(default=None, max_length=64)
    last_error: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> QueueEntry:
        """Keep queue timestamps and explicit retry tokens consistent with entry state."""

        if self.updated_at < self.enqueued_at:
            raise ValueError("queue entry update cannot precede enqueue time")
        if self.status in {"completed", "cancelled"} and self.completed_at is None:
            raise ValueError("terminal queue entry requires completed_at")
        if self.status not in {"completed", "cancelled"} and self.completed_at is not None:
            raise ValueError("non-terminal queue entry cannot declare completed_at")
        if self.retry_failed_once and self.status not in {"queued", "running"}:
            raise ValueError(
                "explicit failed retry token is valid only while queued or leased"
            )
        if self.status == "running":
            if self.lease_id is None or self.lease_expires_at is None:
                raise ValueError("running queue entry requires an execution lease")
        elif self.lease_id is not None or self.lease_expires_at is not None:
            raise ValueError("only a running queue entry may hold an execution lease")
        return self


class LocalWorkflowQueue(V09StrictModel):
    """Store a deterministic single-worker queue outside canonical job evidence."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    queue_id: Literal["local"] = "local"
    revision: int = Field(default=0, ge=0)
    max_concurrency: Literal[1] = 1
    entries: list[QueueEntry] = Field(default_factory=list)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_uniqueness(self) -> LocalWorkflowQueue:
        """Reject duplicate entry IDs and concurrent active ownership per job or workflow."""

        ids = [item.entry_id for item in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("queue entry IDs must be unique")
        active = [
            item
            for item in self.entries
            if item.status in {"queued", "running", "waiting", "failed"}
        ]
        jobs = [item.job_id.casefold() for item in active]
        workflows = [item.workflow_id for item in active]
        if len(jobs) != len(set(jobs)):
            raise ValueError("only one active queue entry is allowed per job")
        if len(workflows) != len(set(workflows)):
            raise ValueError("only one active queue entry is allowed per workflow")
        return self


class QueueAttemptReceipt(V09StrictModel):
    """Preserve one immutable queue dispatch attempt and observed workflow outcome."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    entry_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    attempt_number: int = Field(ge=1, le=1000)
    retry_failed: bool = False
    workflow_status_before: str | None = Field(default=None, max_length=64)
    workflow_status_after: str | None = Field(default=None, max_length=64)
    outcome: QueueOutcome
    error_type: str | None = Field(default=None, max_length=256)
    error_message: str | None = Field(default=None, max_length=4000)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_outcome(self) -> QueueAttemptReceipt:
        """Require error evidence only for a failed queue dispatch."""

        if self.completed_at < self.started_at:
            raise ValueError("queue attempt completion cannot precede its start")
        if self.outcome == "failed":
            if not self.error_type or not self.error_message:
                raise ValueError("failed queue attempt requires error details")
        elif self.error_type is not None or self.error_message is not None:
            raise ValueError("non-failed queue attempt cannot contain error details")
        return self


class QueueLock(V09StrictModel):
    """Represent one expiring local queue writer lock without host path disclosure."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    lock_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    process_id: int = Field(ge=0)
    acquired_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_expiry(self) -> QueueLock:
        """Reject non-expiring or backward queue lock intervals."""

        if self.expires_at <= self.acquired_at:
            raise ValueError("queue lock must expire after acquisition")
        return self


class StabilityReportSource(V09StrictModel):
    """Record one authoritative V0.9 JSON source represented in a PDF report."""

    kind: Literal["environment_probe", "workspace_audit"]
    path: RelativePath
    sha256: Sha256
    size_bytes: int = Field(ge=0)


class StabilityReportManifest(V09StrictModel):
    """Bind one derived V0.9 PDF to exact privacy-safe machine evidence."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    report_id: PortableId
    generated_at: datetime
    pdf_path: RelativePath
    pdf_sha256: Sha256
    source_fingerprint: Sha256
    font: str = Field(min_length=1, max_length=260)
    sources: list[StabilityReportSource] = Field(min_length=2, max_length=2)
    warnings: list[str] = Field(default_factory=list)
