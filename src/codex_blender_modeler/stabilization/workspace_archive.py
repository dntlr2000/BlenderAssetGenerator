"""Reversibly relocate terminal workspaces without rewriting their evidence."""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_artifacts import native_io_path, sha256_file, write_json_atomic
from ..config import get_settings
from ..orchestration import get_workflow_status
from ..orchestration.models import WorkflowPlan, WorkflowRequest, WorkflowState
from ..production.service import get_asset_production_dispatch_status
from ..workspace import validate_job_id
from .archive_models import (
    WorkspaceArchiveArtifact,
    WorkspaceRelocationPlan,
    WorkspaceRelocationReceipt,
    relocation_input_sha256,
)
from .service import get_local_workflow_queue

_PORTABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ACTIVE_QUEUE_STATUSES = {"queued", "running", "waiting", "failed"}
_TERMINAL_WORKFLOW_STATUSES = {"completed", "cancelled", "failed"}
_ARCHIVE_CONTROL_ROOT = ".cbm"


@dataclass(frozen=True)
class _TreeSnapshot:
    """Hold the deterministic identity and size of one link-free directory tree."""

    sha256: str
    file_count: int
    directory_count: int
    byte_size: int


@dataclass(frozen=True)
class _WorkspaceBoundary:
    """Hold exact terminal workflow evidence needed to authorize relocation."""

    workflow_id: str
    classification: str
    workflow_state_sha256: str
    job_metadata_sha256: str


def _utc_now() -> datetime:
    """Return a timezone-aware timestamp for relocation evidence."""

    return datetime.now(UTC)


def _json_timestamp(value: datetime) -> str:
    """Encode one UTC timestamp exactly as Pydantic JSON mode emits it."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    """Create one sortable portable relocation identifier."""

    stamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"{prefix}-{stamp}-{uuid4().hex[:8]}"


def _is_link_like(path: Path) -> bool:
    """Detect symbolic links and Windows junctions without following them."""

    native = native_io_path(path)
    if os.path.islink(native):
        return True
    junction_test = getattr(os.path, "isjunction", None)
    return bool(junction_test(native)) if callable(junction_test) else False


def _absolute_lexical(path: Path) -> Path:
    """Normalize a host path lexically without following symlinks or junctions."""

    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _assert_no_link_ancestors(path: Path, *, include_leaf: bool) -> None:
    """Reject a linked existing path component before archive-control I/O."""

    candidate = _absolute_lexical(path)
    parts = candidate.parts
    if not parts:
        raise ValueError("workspace relocation path is empty")
    current = Path(parts[0])
    selected = parts[1:] if include_leaf else parts[1:-1]
    for part in selected:
        current /= part
        native = native_io_path(current)
        if not os.path.lexists(native):
            continue
        if _is_link_like(current):
            raise ValueError(f"workspace relocation path contains a link: {current}")


def _assert_separate_roots(workspace_root: Path, archive_root: Path) -> None:
    """Require disjoint workspace and archive roots on one filesystem volume."""

    workspace = _absolute_lexical(workspace_root)
    archive = _absolute_lexical(archive_root)
    try:
        archive.relative_to(workspace)
    except ValueError:
        pass
    else:
        raise ValueError("workspace archive root cannot be inside the active workspace")
    try:
        workspace.relative_to(archive)
    except ValueError:
        pass
    else:
        raise ValueError("active workspace cannot be inside the archive root")
    if os.name == "nt" and workspace.drive.casefold() != archive.drive.casefold():
        raise ValueError("workspace relocation requires a same-volume archive root")


def workspace_archive_root(archive_root: Path | None = None) -> Path:
    """Resolve the configured archive root without creating or following it."""

    settings = get_settings()
    configured = os.getenv("CBM_WORKSPACE_ARCHIVE_ROOT", "").strip()
    selected = (
        archive_root
        if archive_root is not None
        else Path(configured).expanduser()
        if configured
        else settings.workspace_root.parent / "workspace_archive"
    )
    workspace = _absolute_lexical(settings.workspace_root)
    archive = _absolute_lexical(selected)
    _assert_separate_roots(workspace, archive)
    _assert_no_link_ancestors(workspace, include_leaf=True)
    _assert_no_link_ancestors(archive, include_leaf=True)
    return archive


def _ensure_archive_root(archive_root: Path) -> None:
    """Create the archive root and revalidate every resulting path component."""

    _assert_no_link_ancestors(archive_root, include_leaf=True)
    os.makedirs(native_io_path(archive_root), exist_ok=True)
    _assert_no_link_ancestors(archive_root, include_leaf=True)
    if not os.path.isdir(native_io_path(archive_root)) or _is_link_like(archive_root):
        raise ValueError("workspace archive root is not a regular directory")
    workspace_root = _absolute_lexical(get_settings().workspace_root)
    if os.stat(native_io_path(workspace_root)).st_dev != os.stat(
        native_io_path(archive_root)
    ).st_dev:
        raise ValueError("workspace relocation requires a same-volume archive root")


def _read_bytes(path: Path) -> bytes:
    """Read one required regular file through its native long-path name."""

    _assert_no_link_ancestors(path, include_leaf=True)
    if _is_link_like(path) or not os.path.isfile(native_io_path(path)):
        raise FileNotFoundError(path)
    with open(native_io_path(path), "rb") as handle:
        return handle.read()


def _load_model(path: Path, model_type: type[Any]) -> Any:
    """Load one strict JSON model without accepting linked evidence."""

    return model_type.model_validate_json(_read_bytes(path))


def _tree_snapshot(root: Path) -> _TreeSnapshot:
    """Hash every directory and file in deterministic order without following links."""

    absolute = _absolute_lexical(root)
    _assert_no_link_ancestors(absolute, include_leaf=True)
    if not os.path.isdir(native_io_path(absolute)) or _is_link_like(absolute):
        raise ValueError("workspace relocation source must be a link-free directory")
    records: list[dict[str, Any]] = [{"path": ".", "type": "directory"}]
    pending = [absolute]
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = sorted(list(iterator), key=lambda item: item.name.casefold())
        directories: list[Path] = []
        for entry in entries:
            member = current / entry.name
            metadata = entry.stat(follow_symlinks=False)
            attributes = getattr(metadata, "st_file_attributes", 0)
            if entry.is_symlink() or _is_link_like(member) or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("workspace relocation source contains a symlink or junction")
            relative = member.relative_to(absolute).as_posix()
            if stat.S_ISDIR(metadata.st_mode):
                records.append({"path": relative, "type": "directory"})
                directories.append(member)
            elif stat.S_ISREG(metadata.st_mode):
                records.append(
                    {
                        "path": relative,
                        "type": "file",
                        "byte_size": metadata.st_size,
                        "sha256": sha256_file(member),
                    }
                )
            else:
                raise ValueError(
                    f"workspace relocation source contains an unsupported entry: {relative}"
                )
        pending.extend(reversed(directories))
    records.sort(key=lambda item: (str(item["path"]), str(item["type"])))
    digest = relocation_input_sha256({"entries": records})
    files = [item for item in records if item["type"] == "file"]
    directories = [item for item in records if item["type"] == "directory"]
    return _TreeSnapshot(
        sha256=digest,
        file_count=len(files),
        directory_count=len(directories),
        byte_size=sum(int(item["byte_size"]) for item in files),
    )


def _reject_active_locks(root: Path) -> None:
    """Reject transient JSON lock files while allowing persistent guard files."""

    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = list(iterator)
        for entry in entries:
            member = current / entry.name
            if entry.is_symlink() or _is_link_like(member):
                raise ValueError("workspace contains a symlink or junction")
            if entry.is_dir(follow_symlinks=False):
                pending.append(member)
            elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".lock.json"):
                raise RuntimeError(f"workspace has an active lock file: {entry.name}")


def _validate_terminal_boundary(job_id: str, *, allow_failed: bool) -> _WorkspaceBoundary:
    """Validate exact V0.8 terminal evidence and all known active-work boundaries."""

    settings = get_settings()
    root = _absolute_lexical(settings.workspace_root / validate_job_id(job_id))
    _assert_no_link_ancestors(root, include_leaf=True)
    if not os.path.isdir(native_io_path(root)) or _is_link_like(root):
        raise FileNotFoundError(f"active workspace job does not exist: {job_id}")
    _reject_active_locks(root)
    job_path = root / "job.json"
    job_payload = json.loads(_read_bytes(job_path))
    if not isinstance(job_payload, dict) or job_payload.get("job_id") != job_id:
        raise ValueError("job metadata identity is missing or mismatched")

    status_payload = get_workflow_status(job_id)
    state_payload = status_payload.get("state")
    if not isinstance(state_payload, dict):
        raise ValueError("job lacks an authoritative V0.8 workflow state")
    state = WorkflowState.model_validate(state_payload)
    if state.job_id != job_id or state.status not in _TERMINAL_WORKFLOW_STATUSES:
        raise RuntimeError("only completed, cancelled, or explicitly allowed failed jobs move")
    if state.status == "failed" and not allow_failed:
        raise PermissionError("failed job relocation requires allow_failed=True")
    if state.status != "failed" and allow_failed:
        raise ValueError("allow_failed is valid only when the workflow status is failed")
    workflow_root = root / "workflows" / state.workflow_id
    request_path = workflow_root / "request.json"
    plan_path = workflow_root / "plan.json"
    state_path = workflow_root / "state.json"
    request = _load_model(request_path, WorkflowRequest)
    plan = _load_model(plan_path, WorkflowPlan)
    persisted_state = _load_model(state_path, WorkflowState)
    if persisted_state != state:
        raise ValueError("public workflow status differs from persisted state")
    if (
        request.job_id != job_id
        or request.workflow_id != state.workflow_id
        or plan.job_id != job_id
        or plan.workflow_id != state.workflow_id
        or state.request_sha256 != sha256_file(request_path)
        or state.plan_sha256 != sha256_file(plan_path)
    ):
        raise ValueError("terminal workflow request, plan, or state binding is stale")
    latest_path = root / "workflows" / "latest.json"
    latest = json.loads(_read_bytes(latest_path))
    if not isinstance(latest, dict) or (
        latest.get("job_id"), latest.get("workflow_id"), latest.get("status")
    ) != (job_id, state.workflow_id, state.status):
        raise ValueError("latest workflow pointer is stale or mismatched")

    queue = get_local_workflow_queue()
    if any(
        item.job_id.casefold() == job_id.casefold()
        and item.status in _ACTIVE_QUEUE_STATUSES
        for item in queue.entries
    ):
        raise RuntimeError("job still has an active local workflow queue entry")
    production_root = root / "production"
    for autonomy_name in ("autonomy", "autonomy_v2"):
        autonomy_root = production_root / autonomy_name
        if os.path.lexists(native_io_path(autonomy_root)):
            raise RuntimeError(
                f"job has {autonomy_name} evidence; use its terminal validator before archive"
            )
    dispatches_root = production_root / "dispatches"
    if os.path.lexists(native_io_path(dispatches_root)):
        if _is_link_like(dispatches_root) or not os.path.isdir(native_io_path(dispatches_root)):
            raise ValueError("production dispatch root is invalid")
        with os.scandir(native_io_path(dispatches_root)) as iterator:
            dispatches = sorted(
                [entry.name for entry in iterator if entry.is_dir(follow_symlinks=False)]
            )
        for dispatch_id in dispatches:
            dispatch_status = get_asset_production_dispatch_status(job_id, dispatch_id)
            dispatch_state = dispatch_status.get("state")
            if not isinstance(dispatch_state, dict) or dispatch_state.get("status") not in {
                "completed",
                "cancelled",
            }:
                raise RuntimeError("production dispatch is not terminal")
    return _WorkspaceBoundary(
        workflow_id=state.workflow_id,
        classification=state.status,
        workflow_state_sha256=sha256_file(state_path),
        job_metadata_sha256=sha256_file(job_path),
    )


def _archive_relative_artifact(
    archive_root: Path,
    path: Path,
    *,
    kind: str,
) -> WorkspaceArchiveArtifact:
    """Create one exact archive-root-relative artifact reference."""

    absolute = _absolute_lexical(path)
    _assert_no_link_ancestors(absolute, include_leaf=True)
    relative = absolute.relative_to(_absolute_lexical(archive_root)).as_posix()
    return WorkspaceArchiveArtifact(
        kind=kind,
        path=relative,
        sha256=sha256_file(absolute),
        byte_size=os.path.getsize(native_io_path(absolute)),
    )


def _write_immutable_model(path: Path, payload: dict[str, Any]) -> None:
    """Publish one archive-control JSON file without overwriting prior history."""

    _assert_no_link_ancestors(path.parent, include_leaf=True)
    if os.path.lexists(native_io_path(path)):
        raise FileExistsError(path)
    write_json_atomic(path, payload)
    _assert_no_link_ancestors(path, include_leaf=True)


def _plan_path(archive_root: Path, plan_id: str) -> Path:
    """Resolve one immutable relocation plan path below the archive control root."""

    if not _PORTABLE_ID_RE.fullmatch(plan_id):
        raise ValueError("plan_id is invalid")
    return archive_root / _ARCHIVE_CONTROL_ROOT / "plans" / f"{plan_id}.json"


def _receipt_path(archive_root: Path, receipt_id: str) -> Path:
    """Resolve one immutable relocation receipt path below the archive control root."""

    if not _PORTABLE_ID_RE.fullmatch(receipt_id):
        raise ValueError("receipt_id is invalid")
    return archive_root / _ARCHIVE_CONTROL_ROOT / "receipts" / f"{receipt_id}.json"


def _build_plan(payload: dict[str, Any]) -> WorkspaceRelocationPlan:
    """Construct a strict relocation plan using the canonical input digest."""

    canonical = {"schema_version": "0.9.0", **payload}
    return WorkspaceRelocationPlan(
        **canonical,
        input_sha256=relocation_input_sha256(canonical),
    )


def _build_receipt(payload: dict[str, Any]) -> WorkspaceRelocationReceipt:
    """Construct a strict relocation receipt using the canonical input digest."""

    canonical = {"schema_version": "0.9.0", **payload}
    return WorkspaceRelocationReceipt(
        **canonical,
        input_sha256=relocation_input_sha256(canonical),
    )


def list_workspace_archive_candidates(
    *,
    allow_failed: bool = False,
) -> list[dict[str, Any]]:
    """Classify active workspace directories without moving or rewriting any job."""

    workspace = _absolute_lexical(get_settings().workspace_root)
    if not os.path.isdir(native_io_path(workspace)):
        return []
    results: list[dict[str, Any]] = []
    with os.scandir(native_io_path(workspace)) as iterator:
        entries = sorted(list(iterator), key=lambda item: item.name.casefold())
    for entry in entries:
        if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
            continue
        if _is_link_like(workspace / entry.name):
            results.append(
                {"job_id": entry.name, "eligible": False, "reason": "link-like job root"}
            )
            continue
        try:
            boundary = _validate_terminal_boundary(
                entry.name,
                allow_failed=allow_failed,
            )
        except Exception as exc:
            results.append(
                {
                    "job_id": entry.name,
                    "eligible": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
        else:
            results.append(
                {
                    "job_id": entry.name,
                    "workflow_id": boundary.workflow_id,
                    "workflow_status": boundary.classification,
                    "eligible": True,
                    "reason": None,
                }
            )
    return results


def plan_workspace_archive(
    job_id: str,
    *,
    allow_failed: bool = False,
    archive_root: Path | None = None,
) -> WorkspaceRelocationPlan:
    """Publish an immutable plan for one exact terminal workspace tree."""

    selected_archive = workspace_archive_root(archive_root)
    _ensure_archive_root(selected_archive)
    boundary = _validate_terminal_boundary(job_id, allow_failed=allow_failed)
    source = _absolute_lexical(get_settings().workspace_root / job_id)
    snapshot = _tree_snapshot(source)
    plan_id = _new_id("workspace-archive")
    month = _utc_now().strftime("%Y-%m")
    archive_entry_path = (
        f"{boundary.classification}/{month}/{job_id}--{plan_id.rsplit('-', 1)[-1]}"
    )
    created_at = _json_timestamp(_utc_now())
    payload = {
        "plan_id": plan_id,
        "action": "archive",
        "job_id": job_id,
        "classification": boundary.classification,
        "workflow_id": boundary.workflow_id,
        "workflow_state_sha256": boundary.workflow_state_sha256,
        "job_metadata_sha256": boundary.job_metadata_sha256,
        "archive_entry_path": archive_entry_path,
        "source_tree_sha256": snapshot.sha256,
        "source_file_count": snapshot.file_count,
        "source_directory_count": snapshot.directory_count,
        "source_byte_size": snapshot.byte_size,
        "allow_failed": allow_failed,
        "prior_archive_receipt": None,
        "created_at": created_at,
    }
    plan = _build_plan(payload)
    _write_immutable_model(
        _plan_path(selected_archive, plan.plan_id),
        plan.model_dump(mode="json"),
    )
    return plan


def _load_archive_artifact(
    archive_root: Path,
    artifact: WorkspaceArchiveArtifact,
    model_type: type[Any],
) -> Any:
    """Load an exact contained archive-control artifact by declared hash and size."""

    path = _absolute_lexical(archive_root / artifact.path)
    path.relative_to(_absolute_lexical(archive_root))
    if (
        _is_link_like(path)
        or not os.path.isfile(native_io_path(path))
        or sha256_file(path) != artifact.sha256
        or os.path.getsize(native_io_path(path)) != artifact.byte_size
    ):
        raise ValueError("archive-control artifact is missing, linked, or stale")
    return model_type.model_validate_json(_read_bytes(path))


def load_workspace_relocation_plan(
    plan_id: str,
    *,
    archive_root: Path | None = None,
) -> WorkspaceRelocationPlan:
    """Load one persisted relocation plan by exact portable identifier."""

    selected_archive = workspace_archive_root(archive_root)
    return _load_model(_plan_path(selected_archive, plan_id), WorkspaceRelocationPlan)


def load_workspace_relocation_receipt(
    receipt_id: str,
    *,
    archive_root: Path | None = None,
) -> WorkspaceRelocationReceipt:
    """Load one persisted relocation receipt by exact portable identifier."""

    selected_archive = workspace_archive_root(archive_root)
    return _load_model(
        _receipt_path(selected_archive, receipt_id),
        WorkspaceRelocationReceipt,
    )


def plan_workspace_restore(
    archive_receipt_id: str,
    *,
    archive_root: Path | None = None,
) -> WorkspaceRelocationPlan:
    """Publish an exact restore plan from one current archive receipt."""

    selected_archive = workspace_archive_root(archive_root)
    _ensure_archive_root(selected_archive)
    archive_receipt = load_workspace_relocation_receipt(
        archive_receipt_id,
        archive_root=selected_archive,
    )
    if archive_receipt.action != "archive":
        raise ValueError("restore requires an archive-action receipt")
    validate_workspace_relocation_receipt(
        archive_receipt,
        archive_root=selected_archive,
        require_current=True,
    )
    destination = _absolute_lexical(get_settings().workspace_root / archive_receipt.job_id)
    if os.path.lexists(native_io_path(destination)):
        raise FileExistsError("active workspace already contains this job_id")
    prior_artifact = _archive_relative_artifact(
        selected_archive,
        _receipt_path(selected_archive, archive_receipt.receipt_id),
        kind="workspace_relocation_receipt",
    )
    payload = {
        "plan_id": _new_id("workspace-restore"),
        "action": "restore",
        "job_id": archive_receipt.job_id,
        "classification": archive_receipt.classification,
        "workflow_id": archive_receipt.workflow_id,
        "workflow_state_sha256": archive_receipt.workflow_state_sha256,
        "job_metadata_sha256": archive_receipt.job_metadata_sha256,
        "archive_entry_path": archive_receipt.archive_entry_path,
        "source_tree_sha256": archive_receipt.tree_sha256,
        "source_file_count": archive_receipt.file_count,
        "source_directory_count": archive_receipt.directory_count,
        "source_byte_size": archive_receipt.byte_size,
        "allow_failed": archive_receipt.classification == "failed",
        "prior_archive_receipt": prior_artifact,
        "created_at": _json_timestamp(_utc_now()),
    }
    plan = _build_plan(payload)
    _write_immutable_model(
        _plan_path(selected_archive, plan.plan_id),
        plan.model_dump(mode="json"),
    )
    return plan


def _snapshot_matches_plan(snapshot: _TreeSnapshot, plan: WorkspaceRelocationPlan) -> bool:
    """Compare one observed tree snapshot with every planned identity field."""

    return (
        snapshot.sha256 == plan.source_tree_sha256
        and snapshot.file_count == plan.source_file_count
        and snapshot.directory_count == plan.source_directory_count
        and snapshot.byte_size == plan.source_byte_size
    )


def _receipt_for_plan(
    archive_root: Path,
    plan: WorkspaceRelocationPlan,
) -> WorkspaceRelocationReceipt | None:
    """Load an already-published receipt for idempotent relocation replay."""

    receipt_id = f"receipt-{plan.plan_id}"
    path = _receipt_path(archive_root, receipt_id)
    if not os.path.isfile(native_io_path(path)):
        return None
    receipt = _load_model(path, WorkspaceRelocationReceipt)
    validate_workspace_relocation_receipt(
        receipt,
        archive_root=archive_root,
        require_current=True,
    )
    return receipt


def execute_workspace_relocation(
    plan: WorkspaceRelocationPlan,
    *,
    archive_root: Path | None = None,
) -> WorkspaceRelocationReceipt:
    """Atomically execute or crash-adopt one exact same-volume relocation plan."""

    selected_archive = workspace_archive_root(archive_root)
    _ensure_archive_root(selected_archive)
    persisted_plan = load_workspace_relocation_plan(
        plan.plan_id,
        archive_root=selected_archive,
    )
    if persisted_plan != plan:
        raise ValueError("caller relocation plan differs from persisted plan")
    existing_receipt = _receipt_for_plan(selected_archive, plan)
    if existing_receipt is not None:
        return existing_receipt

    active = _absolute_lexical(get_settings().workspace_root / plan.job_id)
    archived = _absolute_lexical(selected_archive / plan.archive_entry_path)
    source, destination = (
        (active, archived) if plan.action == "archive" else (archived, active)
    )
    source_exists = os.path.isdir(native_io_path(source)) and not _is_link_like(source)
    destination_exists = os.path.isdir(native_io_path(destination)) and not _is_link_like(
        destination
    )
    adopted = False
    if source_exists and not destination_exists:
        if plan.action == "archive":
            boundary = _validate_terminal_boundary(
                plan.job_id,
                allow_failed=plan.allow_failed,
            )
            if (
                boundary.workflow_id != plan.workflow_id
                or boundary.classification != plan.classification
                or boundary.workflow_state_sha256 != plan.workflow_state_sha256
                or boundary.job_metadata_sha256 != plan.job_metadata_sha256
            ):
                raise ValueError("terminal workspace boundary changed after planning")
        before = _tree_snapshot(source)
        if not _snapshot_matches_plan(before, plan):
            raise ValueError("workspace tree changed after relocation planning")
        _assert_no_link_ancestors(destination.parent, include_leaf=True)
        os.makedirs(native_io_path(destination.parent), exist_ok=True)
        _assert_no_link_ancestors(destination.parent, include_leaf=True)
        if os.path.lexists(native_io_path(destination)):
            raise FileExistsError(destination)
        os.replace(native_io_path(source), native_io_path(destination))
    elif not source_exists and destination_exists:
        adopted = True
    elif source_exists and destination_exists:
        raise FileExistsError("both relocation source and destination exist")
    else:
        raise FileNotFoundError("neither relocation source nor destination exists")

    after = _tree_snapshot(destination)
    if not _snapshot_matches_plan(after, plan):
        if not adopted and not os.path.lexists(native_io_path(source)):
            os.replace(native_io_path(destination), native_io_path(source))
        raise ValueError("relocated workspace tree differs from its immutable plan")
    if plan.action == "restore":
        boundary = _validate_terminal_boundary(
            plan.job_id,
            allow_failed=plan.allow_failed,
        )
        if (
            boundary.workflow_id != plan.workflow_id
            or boundary.classification != plan.classification
            or boundary.workflow_state_sha256 != plan.workflow_state_sha256
            or boundary.job_metadata_sha256 != plan.job_metadata_sha256
        ):
            if not adopted and not os.path.lexists(native_io_path(source)):
                os.replace(native_io_path(destination), native_io_path(source))
            raise ValueError("restored workspace terminal boundary is inconsistent")

    plan_artifact = _archive_relative_artifact(
        selected_archive,
        _plan_path(selected_archive, plan.plan_id),
        kind="workspace_relocation_plan",
    )
    payload = {
        "receipt_id": f"receipt-{plan.plan_id}",
        "plan": plan_artifact,
        "action": plan.action,
        "job_id": plan.job_id,
        "classification": plan.classification,
        "workflow_id": plan.workflow_id,
        "workflow_state_sha256": plan.workflow_state_sha256,
        "job_metadata_sha256": plan.job_metadata_sha256,
        "archive_entry_path": plan.archive_entry_path,
        "tree_sha256": after.sha256,
        "file_count": after.file_count,
        "directory_count": after.directory_count,
        "byte_size": after.byte_size,
        "source_location": "workspace" if plan.action == "archive" else "archive",
        "destination_location": "archive" if plan.action == "archive" else "workspace",
        "adopted_interrupted_move": adopted,
        "completed_at": _json_timestamp(_utc_now()),
    }
    receipt = _build_receipt(payload)
    _write_immutable_model(
        _receipt_path(selected_archive, receipt.receipt_id),
        receipt.model_dump(mode="json"),
    )
    return receipt


def resume_workspace_relocation(
    plan_id: str,
    *,
    archive_root: Path | None = None,
) -> WorkspaceRelocationReceipt:
    """Resume or idempotently adopt one persisted relocation plan by identifier."""

    plan = load_workspace_relocation_plan(plan_id, archive_root=archive_root)
    return execute_workspace_relocation(plan, archive_root=archive_root)


def validate_workspace_relocation_receipt(
    receipt: WorkspaceRelocationReceipt,
    *,
    archive_root: Path | None = None,
    require_current: bool = True,
) -> WorkspaceRelocationReceipt:
    """Recursively validate a relocation receipt and optionally its current tree."""

    selected_archive = workspace_archive_root(archive_root)
    persisted = _load_model(
        _receipt_path(selected_archive, receipt.receipt_id),
        WorkspaceRelocationReceipt,
    )
    if persisted != receipt:
        raise ValueError("caller relocation receipt differs from persisted receipt")
    plan = _load_archive_artifact(
        selected_archive,
        receipt.plan,
        WorkspaceRelocationPlan,
    )
    expected = {
        "action": plan.action,
        "job_id": plan.job_id,
        "classification": plan.classification,
        "workflow_id": plan.workflow_id,
        "workflow_state_sha256": plan.workflow_state_sha256,
        "job_metadata_sha256": plan.job_metadata_sha256,
        "archive_entry_path": plan.archive_entry_path,
        "tree_sha256": plan.source_tree_sha256,
        "file_count": plan.source_file_count,
        "directory_count": plan.source_directory_count,
        "byte_size": plan.source_byte_size,
    }
    actual = {key: getattr(receipt, key) for key in expected}
    if actual != expected or receipt.receipt_id != f"receipt-{plan.plan_id}":
        raise ValueError("workspace relocation receipt differs from its exact plan")
    if plan.action == "restore":
        if plan.prior_archive_receipt is None:
            raise ValueError("restore plan lacks its prior archive receipt")
        prior = _load_archive_artifact(
            selected_archive,
            plan.prior_archive_receipt,
            WorkspaceRelocationReceipt,
        )
        validate_workspace_relocation_receipt(
            prior,
            archive_root=selected_archive,
            require_current=False,
        )
        if (
            prior.action != "archive"
            or prior.job_id != plan.job_id
            or prior.archive_entry_path != plan.archive_entry_path
            or prior.tree_sha256 != plan.source_tree_sha256
        ):
            raise ValueError("restore plan prior receipt is stale or mismatched")
    if require_current:
        current = (
            _absolute_lexical(selected_archive / receipt.archive_entry_path)
            if receipt.action == "archive"
            else _absolute_lexical(get_settings().workspace_root / receipt.job_id)
        )
        snapshot = _tree_snapshot(current)
        if (
            snapshot.sha256 != receipt.tree_sha256
            or snapshot.file_count != receipt.file_count
            or snapshot.directory_count != receipt.directory_count
            or snapshot.byte_size != receipt.byte_size
        ):
            raise ValueError("current relocated workspace tree is stale or tampered")
    return receipt


def archive_workspace_job(
    job_id: str,
    *,
    allow_failed: bool = False,
    archive_root: Path | None = None,
) -> tuple[WorkspaceRelocationPlan, WorkspaceRelocationReceipt]:
    """Plan and execute one terminal workspace archive in a single host call."""

    plan = plan_workspace_archive(
        job_id,
        allow_failed=allow_failed,
        archive_root=archive_root,
    )
    return plan, execute_workspace_relocation(plan, archive_root=archive_root)


def restore_workspace_job(
    archive_receipt_id: str,
    *,
    archive_root: Path | None = None,
) -> tuple[WorkspaceRelocationPlan, WorkspaceRelocationReceipt]:
    """Plan and execute one exact archived-workspace restore in a single host call."""

    plan = plan_workspace_restore(archive_receipt_id, archive_root=archive_root)
    return plan, execute_workspace_relocation(plan, archive_root=archive_root)
