"""V0.9 release evidence, read-only workspace audits, and bounded queue services."""

from __future__ import annotations

import json
import os
import platform
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_artifacts import sha256_file, write_json_atomic
from ..config import get_settings, load_feature_config
from ..orchestration import get_workflow_status, resume_workflow
from ..orchestration.models import (
    WorkflowAttempt,
    WorkflowLock,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowState,
)
from ..versioning import (
    CONSTRAINT_SCHEMA_VERSION,
    INTERIOR_SCOPE_SCHEMA_VERSION,
    MATERIAL_SCHEMA_VERSION,
    PORTABLE_ASSET_SCHEMA_VERSION,
    PROJECT_VERSION,
    REFERENCE_SCHEMA_VERSION,
    SCENE_SPEC_VERSION,
    STABILIZATION_SCHEMA_VERSION,
    VISUAL_QA_SCHEMA_VERSION,
    WORKFLOW_SCHEMA_VERSION,
)
from .locks import queue_write_lock
from .models import (
    AuditFinding,
    ContractVersionRecord,
    EnvironmentProbeReport,
    EvidenceReference,
    JobAudit,
    LocalWorkflowQueue,
    QueueAttemptReceipt,
    QueueEntry,
    WorkspaceAuditReport,
)

_PORTABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for V0.9 evidence."""

    return datetime.now(UTC)


def _portable_id(prefix: str) -> str:
    """Create a sortable portable identifier for immutable V0.9 artifacts."""

    stamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


def _validate_portable_id(value: str, label: str) -> str:
    """Reject caller-controlled identifiers that could escape their storage root."""

    if not _PORTABLE_ID_RE.fullmatch(value):
        raise ValueError(f"{label} must match [a-z0-9][a-z0-9._-]{{0,127}}")
    return value


def _require_stabilization() -> tuple[int, int, int]:
    """Require the V0.9 feature and return audit, lock, and lease bounds."""

    config = load_feature_config()
    if not config.features.stabilization_core:
        raise RuntimeError("stabilization_core is disabled in cbm.toml")
    return (
        config.stabilization.audit_scan_limit,
        config.stabilization.queue_lock_ttl_seconds,
        config.stabilization.queue_lease_seconds,
    )


def _workspace_mode() -> str:
    """Describe whether the workspace uses the repository default without exposing paths."""

    settings = get_settings()
    default_root = (settings.repo_root / "workspaces").resolve()
    return (
        "repository_default"
        if settings.workspace_root.resolve() == default_root
        else "external_configured"
    )


def _contract_versions() -> list[ContractVersionRecord]:
    """List every stable contract boundary preserved by project V0.9."""

    values = [
        ("scene_spec", SCENE_SPEC_VERSION),
        ("reference_analysis", REFERENCE_SCHEMA_VERSION),
        ("constraints", CONSTRAINT_SCHEMA_VERSION),
        ("interior_scope", INTERIOR_SCOPE_SCHEMA_VERSION),
        ("materials", MATERIAL_SCHEMA_VERSION),
        ("visual_qa", VISUAL_QA_SCHEMA_VERSION),
        ("portable_asset", PORTABLE_ASSET_SCHEMA_VERSION),
        ("workflow", WORKFLOW_SCHEMA_VERSION),
        ("stabilization", STABILIZATION_SCHEMA_VERSION),
    ]
    return [ContractVersionRecord(contract=name, version=version) for name, version in values]


def _repo_relative(path: Path) -> str:
    """Convert one repository-contained path into a privacy-safe POSIX path."""

    settings = get_settings()
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(settings.repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("V0.9 release evidence must remain inside the repository") from exc


def _read_blender_compatibility() -> tuple[
    str,
    str | None,
    bool | None,
    list[EvidenceReference],
    list[str],
]:
    """Read existing Blender evidence without rerunning Blender or copying absolute paths."""

    settings = get_settings()
    path = settings.repo_root / "reports" / "blender_compatibility.json"
    if not path.is_file():
        return (
            "missing",
            None,
            None,
            [],
            ["Blender compatibility evidence is missing; run cbm blender-compat."],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        blender_version = payload.get("blender_version")
        ok = payload.get("ok")
        if not isinstance(blender_version, str) or not isinstance(ok, bool):
            raise ValueError("compatibility report lacks blender_version or boolean ok")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return (
            "invalid",
            None,
            None,
            [],
            [f"Blender compatibility evidence is invalid: {type(exc).__name__}."],
        )
    evidence = EvidenceReference(
        evidence_id="blender-compatibility",
        kind="blender_compatibility",
        path=_repo_relative(path),
        sha256=sha256_file(path),
    )
    return "valid", blender_version, ok, [evidence], []


def probe_release_environment(
    *,
    probe_id: str | None = None,
) -> EnvironmentProbeReport:
    """Persist a privacy-safe host snapshot backed by existing compatibility evidence."""

    _require_stabilization()
    selected_id = _validate_portable_id(
        probe_id or _portable_id("probe"),
        "probe_id",
    )
    status, blender_version, blender_ok, evidence, warnings = (
        _read_blender_compatibility()
    )
    settings = get_settings()
    feature_config = load_feature_config()
    executable_name = Path(settings.blender_bin).name or settings.blender_bin
    report = EnvironmentProbeReport(
        probe_id=selected_id,
        project_version=PROJECT_VERSION,
        platform_system=platform.system() or "unknown",
        platform_release=platform.release() or "unknown",
        architecture=platform.machine() or "unknown",
        python_version=platform.python_version(),
        blender_executable_name=executable_name,
        workspace_mode=_workspace_mode(),  # type: ignore[arg-type]
        blender_report_status=status,  # type: ignore[arg-type]
        blender_version=blender_version,
        blender_compatibility_ok=blender_ok,
        contracts=_contract_versions(),
        evidence=evidence,
        feature_flags=asdict(feature_config.features),
        warnings=warnings,
        limitations=[
            "Detected environment data is not a cross-platform support claim.",
            "Unity, Unreal, and custom destination adapters remain unsupported.",
            "Blender evidence is reused by hash; this command does not execute Blender.",
        ],
        generated_at=_utc_now(),
    )
    output = (
        settings.repo_root
        / "reports"
        / "v09"
        / "environment"
        / selected_id
        / "environment_probe.json"
    )
    if output.exists():
        raise FileExistsError(f"Environment probe already exists: {selected_id}")
    write_json_atomic(output, report.model_dump(mode="json"))
    return report


def _finding(
    code: str,
    severity: str,
    message: str,
    *,
    job_id: str | None = None,
    path: str | None = None,
    remediation: str | None = None,
) -> AuditFinding:
    """Create a deterministic, privacy-safe audit finding identifier."""

    seed = json.dumps(
        [code, severity, job_id, path, message],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    import hashlib

    suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    identifier = f"{code.casefold().replace('_', '-')}-{suffix}"
    return AuditFinding(
        finding_id=identifier,
        severity=severity,  # type: ignore[arg-type]
        code=code,
        job_id=job_id,
        path=path,
        message=message,
        remediation=remediation,
    )


def _workspace_relative(path: Path) -> str:
    """Express one contained workspace path without exposing the configured root."""

    workspace = get_settings().workspace_root.resolve()
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(workspace).as_posix()
    except ValueError as exc:
        raise ValueError("Audited path escapes the configured workspace") from exc
    return f"workspace/{relative}" if relative else "workspace"


def _is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows junctions before bounded traversal."""

    if path.is_symlink():
        return True
    junction_test = getattr(path, "is_junction", None)
    return bool(junction_test()) if callable(junction_test) else False


def _parse_version(value: str | None) -> tuple[int, int, int] | None:
    """Parse a strict semantic version for migration compatibility classification."""

    if value is None:
        return None
    match = _VERSION_RE.fullmatch(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _resolve_source_path(value: str) -> Path:
    """Resolve legacy absolute or repository-relative source metadata for read-only audit."""

    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (get_settings().repo_root / candidate).resolve()


def _validate_workflow_contract(path: Path) -> None:
    """Validate recognized V0.8 workflow contracts without altering their receipts."""

    model_by_name: dict[str, type[Any]] = {
        "request.json": WorkflowRequest,
        "plan.json": WorkflowPlan,
        "state.json": WorkflowState,
        ".lock.json": WorkflowLock,
    }
    model = model_by_name.get(path.name)
    if model is None and "attempts" in path.parts:
        model = WorkflowAttempt
    if model is not None:
        model.model_validate_json(path.read_text(encoding="utf-8"))


def _scan_job_files(
    root: Path,
    job_id: str,
    scan_counter: list[int],
    scan_limit: int,
) -> list[AuditFinding]:
    """Bound file traversal, reject link escapes, and parse every job-owned JSON artifact."""

    findings: list[AuditFinding] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_directories: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            if _is_link_like(child):
                findings.append(
                    _finding(
                        "LINK_ESCAPE_RISK",
                        "error",
                        "Link-like directories are not followed during release audit.",
                        job_id=job_id,
                        path=_workspace_relative(child),
                        remediation="Replace the link with contained files or audit it manually.",
                    )
                )
            else:
                safe_directories.append(name)
        directories[:] = safe_directories
        for name in sorted(filenames):
            path = current_path / name
            scan_counter[0] += 1
            if scan_counter[0] > scan_limit:
                findings.append(
                    _finding(
                        "SCAN_LIMIT_EXCEEDED",
                        "error",
                        f"Workspace audit exceeded its {scan_limit} file bound.",
                        job_id=job_id,
                        remediation="Increase stabilization.audit_scan_limit explicitly.",
                    )
                )
                return findings
            relative = _workspace_relative(path)
            if _is_link_like(path):
                findings.append(
                    _finding(
                        "LINK_ESCAPE_RISK",
                        "error",
                        "Link-like files are not read during release audit.",
                        job_id=job_id,
                        path=relative,
                    )
                )
                continue
            if name.endswith(".tmp") or ".creating-" in name:
                findings.append(
                    _finding(
                        "INTERRUPTED_TEMP_ARTIFACT",
                        "warning",
                        "A temporary artifact may indicate an interrupted atomic write.",
                        job_id=job_id,
                        path=relative,
                        remediation="Inspect the owning operation before removing the file.",
                    )
                )
            if path.suffix.casefold() != ".json":
                continue
            try:
                json.loads(path.read_text(encoding="utf-8"))
                if "workflows" in path.parts:
                    _validate_workflow_contract(path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                findings.append(
                    _finding(
                        "INVALID_JSON_CONTRACT",
                        "error",
                        "JSON evidence is unreadable or violates its known "
                        f"contract: {type(exc).__name__}.",
                        job_id=job_id,
                        path=relative,
                        remediation=(
                            "Restore this artifact from immutable history or rerun its "
                            "owning stage."
                        ),
                    )
                )
    return findings


def _audit_latest_workflow(root: Path, job_id: str) -> list[AuditFinding]:
    """Verify that a latest-workflow pointer resolves to an existing workflow directory."""

    latest = root / "workflows" / "latest.json"
    if not latest.is_file():
        return []
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
        workflow_id = payload.get("workflow_id")
        if not isinstance(workflow_id, str) or not _PORTABLE_ID_RE.fullmatch(workflow_id):
            raise ValueError("latest workflow_id is missing or invalid")
        target = root / "workflows" / workflow_id
        if not (target / "request.json").is_file() or not (target / "plan.json").is_file():
            raise FileNotFoundError("latest workflow contract directory is incomplete")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [
            _finding(
                "DANGLING_WORKFLOW_POINTER",
                "error",
                f"Latest workflow pointer is invalid: {type(exc).__name__}.",
                job_id=job_id,
                path=_workspace_relative(latest),
                remediation="Restore latest.json from the current workflow state.",
            )
        ]
    return []


def _audit_job(
    root: Path,
    scan_counter: list[int],
    scan_limit: int,
) -> JobAudit:
    """Audit one job's identity, immutable sources, JSON contracts, and migration boundary."""

    job_id = root.name
    findings: list[AuditFinding] = []
    metadata_path = root / "job.json"
    metadata: dict[str, Any] = {}
    if not metadata_path.is_file():
        findings.append(
            _finding(
                "MISSING_JOB_METADATA",
                "error",
                "Job directory does not contain job.json.",
                job_id=job_id,
                path=_workspace_relative(root),
            )
        )
    else:
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("job.json must contain an object")
            metadata = payload
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            findings.append(
                _finding(
                    "INVALID_JOB_METADATA",
                    "error",
                    f"job.json is unreadable: {type(exc).__name__}.",
                    job_id=job_id,
                    path=_workspace_relative(metadata_path),
                )
            )
    if metadata and metadata.get("job_id") != job_id:
        findings.append(
            _finding(
                "JOB_ID_MISMATCH",
                "error",
                "Directory name and job.json job_id do not match exactly.",
                job_id=job_id,
                path=_workspace_relative(metadata_path),
            )
        )
    created_version = metadata.get("project_version_created")
    created_version = created_version if isinstance(created_version, str) else None
    parsed = _parse_version(created_version)
    current = _parse_version(PROJECT_VERSION) or (0, 9, 0)
    if created_version is None:
        migration_status = "compatible_legacy"
        findings.append(
            _finding(
                "LEGACY_VERSION_UNRECORDED",
                "info",
                "Job predates explicit project-version metadata; no migration was applied.",
                job_id=job_id,
            )
        )
    elif parsed is None:
        migration_status = "corrupt"
        findings.append(
            _finding(
                "INVALID_CREATED_VERSION",
                "error",
                "project_version_created is not a semantic version.",
                job_id=job_id,
                path=_workspace_relative(metadata_path),
            )
        )
    elif parsed > current:
        migration_status = "unsupported_future"
        findings.append(
            _finding(
                "FUTURE_JOB_VERSION",
                "error",
                "Job was created by a newer project version and was not migrated.",
                job_id=job_id,
            )
        )
    elif parsed < current:
        migration_status = "compatible_legacy"
        findings.append(
            _finding(
                "COMPATIBLE_LEGACY_JOB",
                "info",
                "Earlier project metadata is retained under preserved contract versions.",
                job_id=job_id,
            )
        )
    else:
        migration_status = "current"

    raw_sources = metadata.get("sources", []) if metadata else []
    sources = raw_sources if isinstance(raw_sources, list) else []
    if metadata and not isinstance(raw_sources, list):
        findings.append(
            _finding(
                "INVALID_SOURCE_LIST",
                "error",
                "job.json sources must be a list.",
                job_id=job_id,
                path=_workspace_relative(metadata_path),
            )
        )
    source_count = len(sources)
    verified_sources = 0
    input_root = (root / "input").resolve()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            findings.append(
                _finding(
                    "INVALID_SOURCE_RECORD",
                    "error",
                    f"Source record {index} is not an object.",
                    job_id=job_id,
                )
            )
            continue
        value = source.get("path")
        expected = source.get("sha256")
        if not isinstance(value, str) or not isinstance(expected, str):
            findings.append(
                _finding(
                    "INVALID_SOURCE_RECORD",
                    "error",
                    f"Source record {index} lacks path or SHA-256.",
                    job_id=job_id,
                )
            )
            continue
        path = _resolve_source_path(value)
        try:
            path.relative_to(input_root)
        except ValueError:
            findings.append(
                _finding(
                    "SOURCE_PATH_ESCAPE",
                    "error",
                    f"Source record {index} does not resolve inside the job input directory.",
                    job_id=job_id,
                )
            )
            continue
        if _is_link_like(path) or not path.is_file():
            findings.append(
                _finding(
                    "SOURCE_MISSING_OR_LINKED",
                    "error",
                    f"Source record {index} is missing or link-like.",
                    job_id=job_id,
                    path=_workspace_relative(path),
                )
            )
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected) or (
            sha256_file(path).casefold() != expected.casefold()
        ):
            findings.append(
                _finding(
                    "SOURCE_HASH_MISMATCH",
                    "error",
                    f"Source record {index} no longer matches its immutable SHA-256.",
                    job_id=job_id,
                    path=_workspace_relative(path),
                )
            )
            continue
        verified_sources += 1

    findings.extend(_scan_job_files(root, job_id, scan_counter, scan_limit))
    findings.extend(_audit_latest_workflow(root, job_id))
    workflows_root = root / "workflows"
    workflow_count = 0
    if workflows_root.is_dir():
        workflow_count = sum(
            1
            for child in workflows_root.iterdir()
            if child.is_dir()
            and not _is_link_like(child)
            and (child / "request.json").is_file()
        )
    if any(item.severity == "error" for item in findings):
        status = "failed"
        if migration_status not in {"unsupported_future"}:
            migration_status = "corrupt"
    elif any(item.severity == "warning" for item in findings):
        status = "warning"
    else:
        status = "passed"
    return JobAudit(
        job_id=job_id,
        status=status,  # type: ignore[arg-type]
        migration_status=migration_status,  # type: ignore[arg-type]
        project_version_created=created_version,
        source_count=source_count,
        verified_source_count=verified_sources,
        workflow_count=workflow_count,
        findings=findings,
    )


def audit_workspace_state(
    *,
    job_id: str | None = None,
    audit_id: str | None = None,
    scan_limit: int | None = None,
) -> WorkspaceAuditReport:
    """Run a bounded read-only workspace audit and persist only a derived report."""

    configured_limit, _lock_ttl, _lease_seconds = _require_stabilization()
    selected_limit = scan_limit or configured_limit
    if selected_limit < 100 or selected_limit > 1_000_000:
        raise ValueError("scan_limit must be within [100, 1000000]")
    selected_id = _validate_portable_id(audit_id or _portable_id("audit"), "audit_id")
    if job_id is not None and not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError("job_id is invalid")
    started = _utc_now()
    workspace = get_settings().workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    global_findings: list[AuditFinding] = []
    roots: list[Path] = []
    if job_id is not None:
        selected = workspace / job_id
        if not selected.is_dir() or _is_link_like(selected):
            global_findings.append(
                _finding(
                    "JOB_NOT_AUDITABLE",
                    "error",
                    "Selected job is missing, not a directory, or link-like.",
                    job_id=job_id,
                    path=f"workspace/{job_id}",
                )
            )
        else:
            roots = [selected]
    else:
        for child in sorted(workspace.iterdir(), key=lambda item: item.name.casefold()):
            if child.name.startswith("."):
                continue
            if _is_link_like(child):
                global_findings.append(
                    _finding(
                        "LINKED_JOB_DIRECTORY",
                        "error",
                        "Link-like workspace entries are not audited as jobs.",
                        path=f"workspace/{child.name}",
                    )
                )
                continue
            if child.is_dir() and _JOB_ID_RE.fullmatch(child.name):
                roots.append(child)
    counter = [0]
    jobs = [_audit_job(root, counter, selected_limit) for root in roots]
    passed = sum(item.status == "passed" for item in jobs)
    warnings = sum(item.status == "warning" for item in jobs)
    failed = sum(item.status == "failed" for item in jobs)
    all_findings = global_findings + [item for job in jobs for item in job.findings]
    status = (
        "failed"
        if any(item.severity == "error" for item in all_findings)
        else "warning"
        if any(item.severity == "warning" for item in all_findings)
        else "passed"
    )
    report = WorkspaceAuditReport(
        audit_id=selected_id,
        project_version=PROJECT_VERSION,
        workspace_mode=_workspace_mode(),  # type: ignore[arg-type]
        job_filter=job_id,
        scan_limit=selected_limit,
        scanned_file_count=counter[0],
        scanned_job_count=len(jobs),
        passed_job_count=passed,
        warning_job_count=warnings,
        failed_job_count=failed,
        status=status,  # type: ignore[arg-type]
        jobs=jobs,
        findings=global_findings,
        started_at=started,
        completed_at=_utc_now(),
    )
    output = (
        get_settings().repo_root
        / "reports"
        / "v09"
        / "audits"
        / selected_id
        / "workspace_audit.json"
    )
    if output.exists():
        raise FileExistsError(f"Workspace audit already exists: {selected_id}")
    write_json_atomic(output, report.model_dump(mode="json"))
    return report


def _queue_root() -> Path:
    """Resolve the non-canonical workspace-local V0.9 queue directory."""

    return get_settings().workspace_root / ".cbm" / "queue"


def _queue_path() -> Path:
    """Resolve the mutable local queue state file."""

    return _queue_root() / "local_queue.json"


def _load_queue() -> LocalWorkflowQueue:
    """Load strict queue state or initialize an empty in-memory queue."""

    path = _queue_path()
    if not path.is_file():
        return LocalWorkflowQueue(updated_at=_utc_now())
    return LocalWorkflowQueue.model_validate_json(path.read_text(encoding="utf-8"))


def _save_queue(queue: LocalWorkflowQueue) -> LocalWorkflowQueue:
    """Atomically persist one incremented queue revision."""

    updated = queue.model_copy(
        update={"revision": queue.revision + 1, "updated_at": _utc_now()}
    )
    write_json_atomic(_queue_path(), updated.model_dump(mode="json"))
    return updated


def get_local_workflow_queue() -> LocalWorkflowQueue:
    """Read local queue state without resuming workflows or changing evidence."""

    _require_stabilization()
    return _load_queue()


def enqueue_short_workflow(
    job_id: str,
    workflow_id: str,
    *,
    priority: int = 50,
    max_attempts: int = 3,
) -> LocalWorkflowQueue:
    """Queue one existing non-terminal V0.8 workflow without creating authority."""

    _scan_limit, lock_ttl, _lease_seconds = _require_stabilization()
    if priority < 0 or priority > 100:
        raise ValueError("priority must be within [0, 100]")
    if max_attempts < 1 or max_attempts > 10:
        raise ValueError("max_attempts must be within [1, 10]")
    status_payload = get_workflow_status(job_id, workflow_id)
    workflow_state = status_payload.get("state", {})
    workflow_status = str(workflow_state.get("status", "unknown"))
    if workflow_status in {"completed", "cancelled"}:
        raise RuntimeError(f"Terminal workflow cannot be queued: {workflow_status}")
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        active = {
            "queued",
            "running",
            "waiting",
            "failed",
        }
        if any(
            item.status in active
            and (item.job_id.casefold() == job_id.casefold() or item.workflow_id == workflow_id)
            for item in queue.entries
        ):
            raise FileExistsError("Job or workflow already has an active local queue entry")
        now = _utc_now()
        entry = QueueEntry(
            entry_id=f"queue-{uuid4().hex}",
            job_id=job_id,
            workflow_id=workflow_id,
            priority=priority,
            max_attempts=max_attempts,
            enqueued_at=now,
            updated_at=now,
            last_workflow_status=workflow_status,
        )
        return _save_queue(queue.model_copy(update={"entries": [*queue.entries, entry]}))


def _workflow_status_value(job_id: str, workflow_id: str) -> str:
    """Read one persisted workflow status from the public V0.8 status surface."""

    payload = get_workflow_status(job_id, workflow_id)
    state = payload.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("Workflow status response lacks state")
    return str(state.get("status", "unknown"))


def _queue_attempt_receipt_exists(entry_id: str, attempt_number: int) -> bool:
    """Detect an already-recorded attempt before recovering an expired lease."""

    root = _queue_root() / "receipts" / entry_id
    if not root.is_dir():
        return False
    for path in sorted(root.glob("*.json")):
        receipt = QueueAttemptReceipt.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if receipt.attempt_number == attempt_number:
            return True
    return False


def _recover_expired_queue_leases(
    queue: LocalWorkflowQueue,
) -> LocalWorkflowQueue:
    """Fail closed on interrupted queue workers only after their exact lease expires."""

    now = _utc_now()
    entries: list[QueueEntry] = []
    for item in queue.entries:
        if (
            item.status == "running"
            and item.lease_expires_at is not None
            and item.lease_expires_at <= now
        ):
            if not _queue_attempt_receipt_exists(item.entry_id, item.attempt_count):
                _write_queue_receipt(
                    QueueAttemptReceipt(
                        receipt_id=f"receipt-{uuid4().hex}",
                        entry_id=item.entry_id,
                        job_id=item.job_id,
                        workflow_id=item.workflow_id,
                        attempt_number=item.attempt_count,
                        retry_failed=item.retry_failed_once,
                        workflow_status_before=item.last_workflow_status,
                        workflow_status_after=None,
                        outcome="failed",
                        error_type="InterruptedQueueAttempt",
                        error_message=(
                            "Execution lease expired before queue finalization."
                        ),
                        started_at=item.started_at or item.updated_at,
                        completed_at=now,
                    )
                )
            entries.append(
                item.model_copy(
                    update={
                        "status": "failed",
                        "lease_id": None,
                        "lease_expires_at": None,
                        "updated_at": now,
                        "last_error": (
                            "InterruptedQueueAttempt: execution lease expired before finalization"
                        ),
                    }
                )
            )
        else:
            entries.append(item)
    return queue.model_copy(update={"entries": entries})


def _select_queue_entry(queue: LocalWorkflowQueue) -> QueueEntry | None:
    """Choose the highest-priority eligible entry without polling unchanged approvals."""

    candidates: list[QueueEntry] = []
    for item in queue.entries:
        if item.status == "queued":
            candidates.append(item)
        elif item.status == "waiting":
            current = _workflow_status_value(item.job_id, item.workflow_id)
            if current not in {"waiting_for_agent", "waiting_for_approval", "blocked"}:
                candidates.append(item)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item.priority, item.enqueued_at))[0]


def _claim_queue_entry(
    queue: LocalWorkflowQueue,
    selected: QueueEntry,
    lease_seconds: int,
) -> tuple[LocalWorkflowQueue, QueueEntry]:
    """Persist one execution lease before leaving the short queue-lock boundary."""

    now = _utc_now()
    lease_id = uuid4().hex
    claimed = selected.model_copy(
        update={
            "status": "running",
            "attempt_count": selected.attempt_count + 1,
            "started_at": now,
            "updated_at": now,
            "lease_id": lease_id,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "last_error": None,
        }
    )
    entries = [claimed if item.entry_id == selected.entry_id else item for item in queue.entries]
    return _save_queue(queue.model_copy(update={"entries": entries})), claimed


def _queue_outcome(workflow_status: str) -> tuple[str, str]:
    """Map V0.8 workflow state into the smaller V0.9 queue lifecycle."""

    if workflow_status == "completed":
        return "completed", "completed"
    if workflow_status == "cancelled":
        return "cancelled", "cancelled"
    if workflow_status == "failed":
        return "failed", "failed"
    if workflow_status in {"waiting_for_agent", "waiting_for_approval", "blocked"}:
        return "waiting", "waiting"
    return "queued", "advanced"


def _write_queue_receipt(receipt: QueueAttemptReceipt) -> None:
    """Persist one immutable local-queue receipt without overwriting prior attempts."""

    path = _queue_root() / "receipts" / receipt.entry_id / f"{receipt.receipt_id}.json"
    if path.exists():
        raise FileExistsError("Queue attempt receipt already exists")
    write_json_atomic(path, receipt.model_dump(mode="json"))


def _finalize_queue_entry(
    claimed: QueueEntry,
    *,
    workflow_status_before: str | None,
    workflow_status_after: str | None,
    error: Exception | None,
    started_at: datetime,
    lock_ttl: int,
) -> LocalWorkflowQueue:
    """Finalize only the exact leased queue entry and write one immutable receipt."""

    completed_at = _utc_now()
    if error is None:
        entry_status, outcome = _queue_outcome(workflow_status_after or "unknown")
        if workflow_status_after == "failed":
            error_type = "WorkflowFailed"
            error_message = "V0.8 workflow reported a failed deterministic host step."
        else:
            error_type = None
            error_message = None
    else:
        entry_status, outcome = "failed", "failed"
        error_type = type(error).__name__
        error_message = str(error)[:4000]
    receipt = QueueAttemptReceipt(
        receipt_id=f"receipt-{uuid4().hex}",
        entry_id=claimed.entry_id,
        job_id=claimed.job_id,
        workflow_id=claimed.workflow_id,
        attempt_number=claimed.attempt_count,
        retry_failed=claimed.retry_failed_once,
        workflow_status_before=workflow_status_before,
        workflow_status_after=workflow_status_after,
        outcome=outcome,  # type: ignore[arg-type]
        error_type=error_type,
        error_message=error_message,
        started_at=started_at,
        completed_at=completed_at,
    )
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        current = next(
            (item for item in queue.entries if item.entry_id == claimed.entry_id),
            None,
        )
        if current is None or current.status != "running":
            raise RuntimeError("Claimed queue entry disappeared or is no longer running")
        if current.lease_id != claimed.lease_id:
            raise RuntimeError("Queue execution lease changed before finalization")
        completed_marker = completed_at if entry_status in {"completed", "cancelled"} else None
        finalized = current.model_copy(
            update={
                "status": entry_status,
                "retry_failed_once": False,
                "updated_at": completed_at,
                "completed_at": completed_marker,
                "lease_id": None,
                "lease_expires_at": None,
                "last_workflow_status": workflow_status_after or workflow_status_before,
                "last_error": error_message,
            }
        )
        entries = [
            finalized if item.entry_id == claimed.entry_id else item
            for item in queue.entries
        ]
        _write_queue_receipt(receipt)
        return _save_queue(queue.model_copy(update={"entries": entries}))


def run_local_workflow_queue(
    *,
    max_entries: int = 1,
    max_host_steps: int | None = None,
) -> LocalWorkflowQueue:
    """Dispatch bounded existing workflows sequentially and stop at every V0.8 boundary."""

    _scan_limit, lock_ttl, lease_seconds = _require_stabilization()
    if max_entries < 1 or max_entries > 64:
        raise ValueError("max_entries must be within [1, 64]")
    processed = 0
    while processed < max_entries:
        queue_root = _queue_root()
        with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
            queue = _recover_expired_queue_leases(_load_queue())
            selected = _select_queue_entry(queue)
            if selected is None:
                return _save_queue(queue) if queue != _load_queue() else queue
            queue, claimed = _claim_queue_entry(queue, selected, lease_seconds)
        started = _utc_now()
        before: str | None = None
        after: str | None = None
        failure: Exception | None = None
        try:
            before = _workflow_status_value(claimed.job_id, claimed.workflow_id)
            state = resume_workflow(
                claimed.job_id,
                claimed.workflow_id,
                max_host_steps=max_host_steps,
                retry_failed=claimed.retry_failed_once,
            )
            after = state.status
        except Exception as exc:  # Queue evidence must retain deterministic host failures.
            failure = exc
        queue = _finalize_queue_entry(
            claimed,
            workflow_status_before=before,
            workflow_status_after=after,
            error=failure,
            started_at=started,
            lock_ttl=lock_ttl,
        )
        processed += 1
    return queue


def requeue_local_workflow(
    entry_id: str,
    *,
    retry_failed: bool,
) -> LocalWorkflowQueue:
    """Requeue one failed entry only with an explicit V0.8 failed-step retry decision."""

    _validate_portable_id(entry_id, "entry_id")
    if not retry_failed:
        raise PermissionError("Failed workflow requeue requires retry_failed=True")
    _scan_limit, lock_ttl, _lease_seconds = _require_stabilization()
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        current = next((item for item in queue.entries if item.entry_id == entry_id), None)
        if current is None:
            raise FileNotFoundError(f"Queue entry does not exist: {entry_id}")
        if current.status != "failed":
            raise RuntimeError("Only a failed queue entry can be requeued")
        if current.attempt_count >= current.max_attempts:
            raise RuntimeError("Queue entry exhausted its explicit maximum attempts")
        now = _utc_now()
        workflow_status = _workflow_status_value(current.job_id, current.workflow_id)
        updated = current.model_copy(
            update={
                "status": "queued",
                "retry_failed_once": workflow_status == "failed",
                "updated_at": now,
                "last_error": None,
                "last_workflow_status": workflow_status,
            }
        )
        entries = [updated if item.entry_id == entry_id else item for item in queue.entries]
        return _save_queue(queue.model_copy(update={"entries": entries}))


def cancel_local_workflow_queue_entry(
    entry_id: str,
    *,
    reason: str,
) -> LocalWorkflowQueue:
    """Cancel future queue dispatch without cancelling or deleting the V0.8 workflow."""

    _validate_portable_id(entry_id, "entry_id")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("queue cancellation reason must not be empty")
    _scan_limit, lock_ttl, _lease_seconds = _require_stabilization()
    queue_root = _queue_root()
    with queue_write_lock(queue_root, ttl_seconds=lock_ttl):
        queue = _load_queue()
        current = next((item for item in queue.entries if item.entry_id == entry_id), None)
        if current is None:
            raise FileNotFoundError(f"Queue entry does not exist: {entry_id}")
        if current.status == "running":
            raise RuntimeError("Running queue entry cannot be cancelled until it finalizes")
        if current.status in {"completed", "cancelled"}:
            raise RuntimeError("Terminal queue entry cannot be cancelled again")
        now = _utc_now()
        updated = current.model_copy(
            update={
                "status": "cancelled",
                "updated_at": now,
                "completed_at": now,
                "last_error": f"Cancelled: {normalized_reason}"[:4000],
                "retry_failed_once": False,
            }
        )
        entries = [updated if item.entry_id == entry_id else item for item in queue.entries]
        return _save_queue(queue.model_copy(update={"entries": entries}))


__all__ = [
    "audit_workspace_state",
    "cancel_local_workflow_queue_entry",
    "enqueue_short_workflow",
    "get_local_workflow_queue",
    "probe_release_environment",
    "requeue_local_workflow",
    "run_local_workflow_queue",
]
