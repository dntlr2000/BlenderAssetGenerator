"""Validation and immutable evidence publication for isolated controller executions."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from ...blender_artifacts import (
    deterministic_directory_files,
    native_io_path,
    native_json_bytes,
    sha256_file,
    stable_json_digest,
)
from ...material_retry_supersession import (
    MaterialRetryAdmissionArtifact,
    validate_material_retry_supersession_admission,
)
from ...production.validation import (
    ensure_contained_production_path as _ensure_contained_production_path,
)
from ..models import ProductionArtifact
from .models import (
    ControllerArtifact,
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
)
from .protocol import CandidateAuthoringController


@dataclass(frozen=True)
class _ControllerWorkspace:
    """Hold one request-owned input snapshot, output map, and start receipt."""

    root: Path
    evidence_root: Path
    assignment: Path
    immutable_inputs: tuple[Path, ...]
    tool_profile_snapshot: Path
    input_snapshots: tuple[Path, ...]
    output_root: Path
    output_map: dict[str, Path]
    started_receipt: ControllerArtifact
    started_payload: dict[str, Any]
    started_adopted: bool


_CONTROLLER_RECEIPT_NAMES = frozenset(
    {
        "started.json",
        "invocation.json",
        "completed.json",
        "adopted.json",
        "published.json",
    }
)


def ensure_contained_production_path(
    root: Path,
    path: Path,
    *,
    must_exist: bool,
) -> Path:
    """Apply central containment using extended-length paths on Windows."""

    native_root = Path(native_io_path(root))
    native_path = Path(native_io_path(path))
    return _ensure_contained_production_path(
        native_root,
        native_path,
        must_exist=must_exist,
    )


def _artifact(root: Path, path: Path, *, artifact_id: str, role: str) -> ControllerArtifact:
    """Create one exact contained regular-file binding for controller evidence."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ValueError(f"controller artifact must be a regular file: {safe.name}")
    return ControllerArtifact(
        artifact_id=artifact_id,
        role=role,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=os.path.getsize(native_io_path(safe)),
    )


def _validate_input(root: Path, item: ControllerArtifact) -> Path:
    """Reject missing, linked, resized, or rehashed immutable controller inputs."""

    path = ensure_contained_production_path(root, root / item.path, must_exist=True)
    if not os.path.isfile(native_io_path(path)):
        raise ValueError(f"controller input is not a regular file: {item.path}")
    if os.path.getsize(native_io_path(path)) != item.byte_size:
        raise ValueError(f"controller input size changed: {item.path}")
    if sha256_file(path) != item.sha256:
        raise ValueError(f"controller input hash changed: {item.path}")
    return path


def _load_request(root: Path, path: Path) -> tuple[ControllerExecutionRequest, ControllerArtifact]:
    """Load and bind one immutable request through strict JSON-mode validation."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    request = ControllerExecutionRequest.model_validate_json(
        Path(native_io_path(safe)).read_text(encoding="utf-8")
    )
    artifact = _artifact(root, safe, artifact_id=request.contract_id, role="controller_request")
    return request, artifact


def _load_profile(root: Path, artifact: ControllerArtifact) -> PhaseToolProfile:
    """Reparse and verify the exact phase tool profile bound by the request."""

    path = _validate_input(root, artifact)
    return PhaseToolProfile.model_validate_json(
        Path(native_io_path(path)).read_text(encoding="utf-8")
    )


def _validate_request_profile(
    request: ControllerExecutionRequest,
    profile: PhaseToolProfile,
) -> None:
    """Require request identity, roles, and output paths to stay inside its exact phase profile."""

    if (
        profile.job_id != request.job_id
        or profile.workflow_id != request.workflow_id
        or profile.dispatch_id != request.dispatch_id
        or profile.session_id != request.session_id
    ):
        raise ValueError("controller request and phase profile identities differ")
    if profile.allowed_output_paths != request.allowed_output_paths:
        raise ValueError("controller request output paths do not match its phase tool profile")
    supplied_roles = {request.assignment.role, *(item.role for item in request.immutable_inputs)}
    if not supplied_roles.issubset(set(profile.allowed_input_roles)):
        raise ValueError("controller request supplies a role outside its phase tool profile")


def _copy_or_validate_exact_file(
    *,
    containment_root: Path,
    source: Path,
    destination: Path,
    expected_sha256: str,
    expected_size: int,
) -> None:
    """Create one exact snapshot once or adopt only byte-identical existing bytes."""

    safe_destination = ensure_contained_production_path(
        containment_root,
        destination,
        must_exist=False,
    )
    if os.path.exists(native_io_path(safe_destination)):
        safe_destination = ensure_contained_production_path(
            containment_root,
            safe_destination,
            must_exist=True,
        )
        if not os.path.isfile(native_io_path(safe_destination)):
            raise ValueError(
                f"controller snapshot is not a regular file: {safe_destination.name}"
            )
        if (
            os.path.getsize(native_io_path(safe_destination)) != expected_size
            or sha256_file(safe_destination) != expected_sha256
        ):
            raise ValueError(f"controller snapshot is stale: {safe_destination.name}")
        return
    os.makedirs(native_io_path(safe_destination.parent), exist_ok=True)
    ensure_contained_production_path(
        containment_root,
        safe_destination.parent,
        must_exist=True,
    )
    with open(native_io_path(source), "rb") as source_handle, open(
        native_io_path(safe_destination),
        "xb",
    ) as target_handle:
        shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
    safe_destination = ensure_contained_production_path(
        containment_root,
        safe_destination,
        must_exist=True,
    )
    if (
        os.path.getsize(native_io_path(safe_destination)) != expected_size
        or sha256_file(safe_destination) != expected_sha256
    ):
        raise ValueError(
            f"controller snapshot copy is inconsistent: {safe_destination.name}"
        )


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read one strict JSON object from a host-owned controller receipt."""

    value = json.loads(Path(native_io_path(path)).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"controller receipt is not a JSON object: {path.name}")
    return value


def _receipt_timestamp(payload: dict[str, Any], key: str) -> datetime:
    """Parse one timezone-aware receipt timestamp without accepting naive values."""

    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"controller receipt has no valid {key} timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"controller receipt {key} timestamp must include a timezone")
    return parsed


def _write_or_adopt_receipt(
    *,
    root: Path,
    path: Path,
    execution_id: str,
    stage: str,
    expected: dict[str, Any],
) -> tuple[dict[str, Any], ControllerArtifact, bool]:
    """Publish one request-bound receipt or adopt only its exact deterministic fields."""

    destination = ensure_contained_production_path(root, path, must_exist=False)
    adopted = os.path.exists(native_io_path(destination))
    required = {
        "schema_version": "0.1.0",
        "execution_id": execution_id,
        "stage": stage,
        **expected,
    }
    if adopted:
        destination = ensure_contained_production_path(root, destination, must_exist=True)
        payload = _read_json_object(destination)
        if set(payload) != {*required, "recorded_at"} or any(
            payload.get(key) != value for key, value in required.items()
        ):
            raise ValueError(f"controller {stage} receipt is stale or belongs to another request")
        _receipt_timestamp(payload, "recorded_at")
    else:
        os.makedirs(native_io_path(destination.parent), exist_ok=True)
        ensure_contained_production_path(root, destination.parent, must_exist=True)
        payload = {**required, "recorded_at": datetime.now(UTC).isoformat()}
        encoded = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        with open(native_io_path(destination), "x", encoding="utf-8") as handle:
            handle.write(encoded)
    artifact = _artifact(
        root,
        destination,
        artifact_id=f"{execution_id}-{stage}",
        role=f"controller_{stage}_receipt",
    )
    return payload, artifact, adopted


def _workspace_output_map(
    request: ControllerExecutionRequest,
    output_root: Path,
) -> dict[str, Path]:
    """Map canonical staging leaves onto execution-owned workspace output leaves."""

    declared_root = PurePosixPath(request.output_root)
    mapped: dict[str, Path] = {}
    for relative in request.allowed_output_paths:
        tail = PurePosixPath(relative).relative_to(declared_root)
        mapped[relative] = output_root.joinpath(*tail.parts)
    return mapped


def _workspace_inventory(workspace_root: Path) -> dict[str, Path]:
    """Enumerate a workspace without following symlinks, junctions, or special files."""

    return {
        path.relative_to(workspace_root).as_posix(): path
        for path in deterministic_directory_files(workspace_root)
    }


def _directory_inventory(directory_root: Path) -> set[str]:
    """Enumerate directory members after the file walker has rejected link-like entries."""

    deterministic_directory_files(directory_root)
    pending = [directory_root]
    members: set[str] = set()
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = list(iterator)
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            member = current / entry.name
            members.add(member.relative_to(directory_root).as_posix())
            pending.append(member)
    return members


def _validate_evidence_inventory(evidence_root: Path) -> set[str]:
    """Reject linked, nested, or undeclared files in the host-owned evidence directory."""

    members = {
        path.relative_to(evidence_root).as_posix()
        for path in deterministic_directory_files(evidence_root)
    }
    extra = sorted(members - _CONTROLLER_RECEIPT_NAMES)
    if extra:
        raise ValueError(
            "controller evidence contains unexpected files: " + ", ".join(extra)
        )
    extra_directories = sorted(_directory_inventory(evidence_root))
    if extra_directories:
        raise ValueError(
            "controller evidence contains unexpected directories: "
            + ", ".join(extra_directories)
        )
    return members


def _validate_evidence_stage_order(members: set[str]) -> None:
    """Reject receipts whose immutable lifecycle prerequisites are absent."""

    if members and "started.json" not in members:
        raise ValueError("controller evidence exists without its exact start receipt")
    if "adopted.json" in members and "completed.json" not in members:
        raise ValueError("controller adoption evidence exists without exact completion")
    if "published.json" in members and "completed.json" not in members:
        raise ValueError("controller publication evidence exists without exact completion")


def _output_inventory(
    workspace: _ControllerWorkspace,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Re-hash exact workspace outputs and return canonical records, extras, and missing leaves."""

    actual = _workspace_inventory(workspace.root)
    allowed_inputs = {
        path.relative_to(workspace.root).as_posix() for path in workspace.input_snapshots
    }
    output_to_canonical = {
        path.relative_to(workspace.root).as_posix(): relative
        for relative, path in workspace.output_map.items()
    }
    allowed_files = allowed_inputs | set(output_to_canonical)
    allowed_directories: set[str] = set()
    for relative in allowed_files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            allowed_directories.add(parent.as_posix())
            parent = parent.parent
    extra = sorted(set(actual) - allowed_files)
    extra.extend(
        f"{relative}/"
        for relative in sorted(
            _directory_inventory(workspace.root) - allowed_directories
        )
    )
    missing = sorted(set(output_to_canonical) - set(actual))
    records = [
        {
            "path": output_to_canonical[workspace_relative],
            "workspace_path": workspace_relative,
            "sha256": sha256_file(actual[workspace_relative]),
            "byte_size": os.path.getsize(native_io_path(actual[workspace_relative])),
        }
        for workspace_relative in sorted(set(actual) & set(output_to_canonical))
    ]
    return records, extra, [output_to_canonical[item] for item in missing]


def _prepare_workspace(
    *,
    root: Path,
    request_path: Path,
    request: ControllerExecutionRequest,
    request_artifact: ControllerArtifact,
) -> _ControllerWorkspace:
    """Create or exactly adopt one request-owned workspace with immutable input snapshots."""

    workspace_root = ensure_contained_production_path(
        root,
        request_path.parent / "controller_workspace",
        must_exist=False,
    )
    evidence_root = ensure_contained_production_path(
        root,
        request_path.parent / "controller_executor_evidence",
        must_exist=False,
    )
    os.makedirs(native_io_path(workspace_root), exist_ok=True)
    os.makedirs(native_io_path(evidence_root), exist_ok=True)
    ensure_contained_production_path(root, workspace_root, must_exist=True)
    ensure_contained_production_path(root, evidence_root, must_exist=True)
    evidence_members = _validate_evidence_inventory(evidence_root)
    _validate_evidence_stage_order(evidence_members)

    assignment_source = _validate_input(root, request.assignment)
    assignment_snapshot = workspace_root / "inputs" / "assignment" / assignment_source.name
    _copy_or_validate_exact_file(
        containment_root=workspace_root,
        source=assignment_source,
        destination=assignment_snapshot,
        expected_sha256=request.assignment.sha256,
        expected_size=request.assignment.byte_size,
    )
    immutable_snapshots: list[Path] = []
    for index, artifact in enumerate(request.immutable_inputs):
        source = _validate_input(root, artifact)
        snapshot = (
            workspace_root
            / "inputs"
            / "immutable"
            / f"{index:03d}-{artifact.artifact_id}{source.suffix}"
        )
        _copy_or_validate_exact_file(
            containment_root=workspace_root,
            source=source,
            destination=snapshot,
            expected_sha256=artifact.sha256,
            expected_size=artifact.byte_size,
        )
        immutable_snapshots.append(snapshot)
    profile_source = _validate_input(root, request.tool_profile)
    profile_snapshot = workspace_root / "inputs" / "tool_profile.json"
    _copy_or_validate_exact_file(
        containment_root=workspace_root,
        source=profile_source,
        destination=profile_snapshot,
        expected_sha256=request.tool_profile.sha256,
        expected_size=request.tool_profile.byte_size,
    )
    input_snapshots = (assignment_snapshot, *immutable_snapshots, profile_snapshot)
    output_root = workspace_root / "outputs"
    os.makedirs(native_io_path(output_root), exist_ok=True)
    output_map = _workspace_output_map(request, output_root)
    for path in output_map.values():
        os.makedirs(native_io_path(path.parent), exist_ok=True)
        ensure_contained_production_path(root, path.parent, must_exist=True)

    started_path = evidence_root / "started.json"
    started_preexisting = "started.json" in evidence_members
    records, extra, _missing = _output_inventory(
        _ControllerWorkspace(
            root=workspace_root,
            evidence_root=evidence_root,
            assignment=assignment_snapshot,
            immutable_inputs=tuple(immutable_snapshots),
            tool_profile_snapshot=profile_snapshot,
            input_snapshots=tuple(input_snapshots),
            output_root=output_root,
            output_map=output_map,
            started_receipt=request.tool_profile,
            started_payload={},
            started_adopted=False,
        )
    )
    if extra:
        raise ValueError("controller workspace contains unexpected files: " + ", ".join(extra))
    if not started_preexisting and records:
        raise ValueError("controller workspace contains stale output before its start receipt")
    snapshot_records = [
        {
            "path": path.relative_to(workspace_root).as_posix(),
            "sha256": sha256_file(path),
            "byte_size": os.path.getsize(native_io_path(path)),
        }
        for path in input_snapshots
    ]
    protected_inventory_sha256 = stable_json_digest(
        _protected_job_inventory(
            root=root,
            request_path=request_path,
            workspace_root=workspace_root,
            evidence_root=evidence_root,
            request=request,
        )
    )
    if started_preexisting:
        recorded_start = _read_json_object(started_path)
        recorded_protected_sha256 = recorded_start.get(
            "protected_inventory_sha256"
        )
        if not isinstance(recorded_protected_sha256, str):
            raise ValueError("controller start receipt has no protected inventory digest")
        if recorded_protected_sha256 != protected_inventory_sha256:
            raise PermissionError(
                "protected files outside the controller workspace changed after its exact start"
            )
    started_payload, started_artifact, started_adopted = _write_or_adopt_receipt(
        root=root,
        path=started_path,
        execution_id=request.execution_id,
        stage="started",
        expected={
            "request_sha256": request_artifact.sha256,
            "source_fingerprint": request.source_fingerprint,
            "workspace_path": workspace_root.relative_to(root).as_posix(),
            "protected_inventory_sha256": protected_inventory_sha256,
            "input_snapshots": snapshot_records,
            "output_map": {
                relative: path.relative_to(workspace_root).as_posix()
                for relative, path in output_map.items()
            },
        },
    )
    current_protected_sha256 = stable_json_digest(
        _protected_job_inventory(
            root=root,
            request_path=request_path,
            workspace_root=workspace_root,
            evidence_root=evidence_root,
            request=request,
        )
    )
    if current_protected_sha256 != started_payload["protected_inventory_sha256"]:
        raise PermissionError(
            "protected files outside the controller workspace changed after its exact start"
        )
    return _ControllerWorkspace(
        root=workspace_root,
        evidence_root=evidence_root,
        assignment=assignment_snapshot,
        immutable_inputs=tuple(immutable_snapshots),
        tool_profile_snapshot=profile_snapshot,
        input_snapshots=tuple(input_snapshots),
        output_root=output_root,
        output_map=output_map,
        started_receipt=started_artifact,
        started_payload=started_payload,
        started_adopted=started_adopted,
    )


def _validate_workspace_inputs(
    workspace: _ControllerWorkspace,
    request: ControllerExecutionRequest,
) -> None:
    """Reject controller mutation of any assignment, immutable input, or profile snapshot."""

    expected = [request.assignment, *request.immutable_inputs, request.tool_profile]
    if len(expected) != len(workspace.input_snapshots):
        raise ValueError("controller workspace input snapshot count changed")
    for artifact, snapshot in zip(expected, workspace.input_snapshots, strict=True):
        if not os.path.isfile(native_io_path(snapshot)):
            raise ValueError(f"controller removed an immutable snapshot: {snapshot.name}")
        if (
            os.path.getsize(native_io_path(snapshot)) != artifact.byte_size
            or sha256_file(snapshot) != artifact.sha256
        ):
            raise ValueError(f"controller changed an immutable snapshot: {snapshot.name}")


def _is_below(path: Path, parent: Path) -> bool:
    """Return whether one absolute path is located at or below another path."""

    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _job_inventory_excluding(
    root: Path,
    excluded: tuple[Path, ...],
) -> dict[str, tuple[int, str]]:
    """Fingerprint every job file outside host-owned controller workspace/evidence roots."""

    return {
        path.relative_to(root).as_posix(): (
            os.path.getsize(native_io_path(path)),
            sha256_file(path),
        )
        for path in deterministic_directory_files(root)
        if not any(_is_below(path, item) for item in excluded)
    }


def _protected_job_inventory(
    *,
    root: Path,
    request_path: Path,
    workspace_root: Path,
    evidence_root: Path,
    request: ControllerExecutionRequest,
) -> dict[str, tuple[int, str]]:
    """Fingerprint protected files while excluding exact host lifecycle evidence."""

    staging_outputs = tuple(
        ensure_contained_production_path(root, root / relative, must_exist=False)
        for relative in request.allowed_output_paths
    )
    host_runtime_paths: tuple[Path, ...] = tuple(
        ensure_contained_production_path(root, path, must_exist=False)
        for path in (
            request_path.parent / "result.json",
            request_path.parent / "adoption",
        )
    )
    if request_path.parent.parent.name == "controller_executions":
        session_root = request_path.parent.parent.parent
        session_runtime_paths = tuple(
            ensure_contained_production_path(root, path, must_exist=False)
            for path in (
                session_root / "states",
                session_root / "autonomy.lock",
                session_root / ".autonomy.lock.guard",
            )
        )
        host_runtime_paths = (*host_runtime_paths, *session_runtime_paths)
        if session_root.name == "codex_imagegen":
            # The additive ImageGen overlay appends host states under its own
            # lock; those paths are lifecycle evidence, never controller output.
            imagegen_overlay_runtime = tuple(
                ensure_contained_production_path(root, path, must_exist=False)
                for path in (
                    session_root / "overlay" / "states",
                    session_root / "overlay" / "autonomy.lock",
                    session_root / "overlay" / ".autonomy.lock.guard",
                    # This exact host terminal may be published after invocation and
                    # before crash-replayed overlay state adoption.
                    session_root / "terminal.json",
                )
            )
            host_runtime_paths = (*host_runtime_paths, *imagegen_overlay_runtime)
    return _job_inventory_excluding(
        root,
        (
            workspace_root,
            evidence_root,
            *staging_outputs,
            *host_runtime_paths,
        ),
    )


def _validate_expected_hashes(
    request: ControllerExecutionRequest,
    records: list[dict[str, Any]],
    diagnostics: list[str],
) -> bool:
    """Reject any supplied output whose exact request-bound hash does not match."""

    accepted = True
    by_path = {str(item["path"]): str(item["sha256"]) for item in records}
    for relative, expected in request.expected_output_sha256.items():
        actual = by_path.get(relative)
        if actual is not None and actual != expected:
            diagnostics.append(f"stale or unexpected output hash: {relative}")
            accepted = False
    return accepted


def _result_status(
    token: str,
    *,
    missing: int,
    extra: int,
) -> tuple[str, bool]:
    """Map an adapter token and exact inventory to one conservative public outcome."""

    if extra or (token == "completed" and missing):
        return "rejected", False
    if token == "adopt_existing" and missing:
        return "waiting_for_output", False
    mapping = {
        "completed": ("completed", False),
        "adopt_existing": ("completed", False),
        "timeout": ("timeout", True),
        "failed": ("failed", False),
        "cancelled": ("cancelled", False),
        "unavailable": ("failed", False),
        "rejected": ("rejected", False),
    }
    return mapping.get(token, ("failed", False))


def _load_invocation_receipt(
    *,
    root: Path,
    path: Path,
    request: ControllerExecutionRequest,
    request_artifact: ControllerArtifact,
    started_artifact: ControllerArtifact,
) -> tuple[dict[str, Any], ControllerArtifact] | None:
    """Load an existing single-invocation receipt only when every request binding matches."""

    if not os.path.exists(native_io_path(path)):
        return None
    safe = ensure_contained_production_path(root, path, must_exist=True)
    payload = _read_json_object(safe)
    required = {
        "schema_version",
        "execution_id",
        "stage",
        "request_sha256",
        "started_receipt_sha256",
        "controller_kind",
        "token",
        "inventory",
        "extra_paths",
        "missing_paths",
        "diagnostics",
        "started_at",
        "completed_at",
        "recorded_at",
    }
    if set(payload) != required:
        raise ValueError("controller invocation receipt has an invalid shape")
    if (
        payload.get("schema_version") != "0.1.0"
        or payload.get("execution_id") != request.execution_id
        or payload.get("stage") != "invocation"
        or payload.get("request_sha256") != request_artifact.sha256
        or payload.get("started_receipt_sha256") != started_artifact.sha256
        or payload.get("controller_kind") != request.controller_kind
    ):
        raise ValueError("controller invocation receipt is stale or belongs to another request")
    if not isinstance(payload.get("inventory"), list):
        raise ValueError("controller invocation receipt has an invalid inventory")
    if not isinstance(payload.get("extra_paths"), list) or not isinstance(
        payload.get("missing_paths"),
        list,
    ):
        raise ValueError("controller invocation receipt has invalid path evidence")
    if not isinstance(payload.get("diagnostics"), list):
        raise ValueError("controller invocation receipt has invalid diagnostics")
    token = payload.get("token")
    if token not in {
        "completed",
        "adopt_existing",
        "timeout",
        "failed",
        "cancelled",
        "unavailable",
        "rejected",
    }:
        raise ValueError("controller invocation receipt has an invalid token")
    records = cast(list[Any], payload["inventory"])
    record_paths: list[str] = []
    for item in records:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "workspace_path",
            "sha256",
            "byte_size",
        }:
            raise ValueError("controller invocation receipt has an invalid output record")
        if (
            not isinstance(item["path"], str)
            or item["path"] not in request.allowed_output_paths
            or not isinstance(item["workspace_path"], str)
            or not item["workspace_path"].startswith("outputs/")
            or not isinstance(item["sha256"], str)
            or len(item["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in item["sha256"])
            or not isinstance(item["byte_size"], int)
            or isinstance(item["byte_size"], bool)
            or item["byte_size"] < 0
        ):
            raise ValueError("controller invocation receipt has invalid output values")
        record_paths.append(cast(str, item["path"]))
    extra_paths = cast(list[Any], payload["extra_paths"])
    missing_paths = cast(list[Any], payload["missing_paths"])
    diagnostics = cast(list[Any], payload["diagnostics"])
    if not all(isinstance(item, str) for item in [*extra_paths, *missing_paths, *diagnostics]):
        raise ValueError("controller invocation receipt has non-string diagnostics")
    if (
        len(record_paths) != len(set(record_paths))
        or set(missing_paths) - set(request.allowed_output_paths)
        or set(record_paths) & set(missing_paths)
        or set(record_paths) | set(missing_paths) != set(request.allowed_output_paths)
    ):
        raise ValueError("controller invocation receipt inventory is incomplete or duplicated")
    started_at = _receipt_timestamp(payload, "started_at")
    completed_at = _receipt_timestamp(payload, "completed_at")
    recorded_at = _receipt_timestamp(payload, "recorded_at")
    if completed_at < started_at or recorded_at < completed_at:
        raise ValueError("controller invocation receipt timestamps are out of order")
    return payload, _artifact(
        root,
        safe,
        artifact_id=f"{request.execution_id}-invocation",
        role="controller_invocation_receipt",
    )


def _canonical_output_targets(
    root: Path,
    request: ControllerExecutionRequest,
) -> dict[str, Path]:
    """Resolve every declared staging output while rejecting linked or escaping leaves."""

    return {
        relative: ensure_contained_production_path(
            root,
            root / relative,
            must_exist=False,
        )
        for relative in request.allowed_output_paths
    }


def _validate_staging_precondition(
    *,
    root: Path,
    request: ControllerExecutionRequest,
    workspace: _ControllerWorkspace,
) -> None:
    """Reject stale final staging bytes unless an exact completion receipt precedes them."""

    targets = _canonical_output_targets(root, request)
    completed_path = ensure_contained_production_path(
        root,
        workspace.evidence_root / "completed.json",
        must_exist=False,
    )
    if not os.path.exists(native_io_path(completed_path)) and any(
        os.path.exists(native_io_path(path)) for path in targets.values()
    ):
        raise ValueError("controller staging output existed before exact completion")


def _complete_validated_outputs(
    *,
    root: Path,
    request: ControllerExecutionRequest,
    request_artifact: ControllerArtifact,
    workspace: _ControllerWorkspace,
    records: list[dict[str, Any]],
    invocation_artifact: ControllerArtifact | None,
) -> ControllerArtifact:
    """Bind one exact complete workspace inventory before any staging publication."""

    _payload, artifact, _adopted = _write_or_adopt_receipt(
        root=root,
        path=workspace.evidence_root / "completed.json",
        execution_id=request.execution_id,
        stage="completed",
        expected={
            "request_sha256": request_artifact.sha256,
            "started_receipt_sha256": workspace.started_receipt.sha256,
            "invocation_receipt_sha256": (
                invocation_artifact.sha256 if invocation_artifact is not None else None
            ),
            "outputs": records,
        },
    )
    return artifact


def _publish_validated_outputs(
    *,
    root: Path,
    request: ControllerExecutionRequest,
    request_artifact: ControllerArtifact,
    workspace: _ControllerWorkspace,
    records: list[dict[str, Any]],
    completed_artifact: ControllerArtifact,
) -> tuple[list[ControllerArtifact], list[ControllerArtifact], datetime]:
    """Publish validated workspace bytes to exact staging leaves with crash-safe adoption."""

    published_path = workspace.evidence_root / "published.json"
    published_preexisting = os.path.exists(native_io_path(published_path))
    record_by_path = {str(item["path"]): item for item in records}
    canonical_targets = _canonical_output_targets(root, request)
    if published_preexisting:
        for relative, target in canonical_targets.items():
            receipt = record_by_path[relative]
            if not os.path.isfile(native_io_path(target)):
                raise ValueError(
                    f"published controller staging output is missing: {relative}"
                )
            if (
                os.path.getsize(native_io_path(target)) != receipt["byte_size"]
                or sha256_file(target) != receipt["sha256"]
            ):
                raise ValueError(
                    f"published controller staging output changed: {relative}"
                )
    outputs: list[ControllerArtifact] = []
    for index, relative in enumerate(request.allowed_output_paths):
        source = workspace.output_map[relative]
        receipt = record_by_path[relative]
        target = canonical_targets[relative]
        os.makedirs(native_io_path(target.parent), exist_ok=True)
        ensure_contained_production_path(root, target.parent, must_exist=True)
        _copy_or_validate_exact_file(
            containment_root=root,
            source=source,
            destination=target,
            expected_sha256=cast(str, receipt["sha256"]),
            expected_size=cast(int, receipt["byte_size"]),
        )
        outputs.append(
            _artifact(
                root,
                target,
                artifact_id=f"controller-output-{index + 1:03d}",
                role="controller_output",
            )
        )
    published_payload, published_artifact, _published_adopted = _write_or_adopt_receipt(
        root=root,
        path=published_path,
        execution_id=request.execution_id,
        stage="published",
        expected={
            "request_sha256": request_artifact.sha256,
            "completed_receipt_sha256": completed_artifact.sha256,
            "outputs": [item.model_dump(mode="json") for item in outputs],
        },
    )
    published_at = _receipt_timestamp(published_payload, "recorded_at")
    return outputs, [published_artifact], published_at


def execute_controller_request(
    *,
    job_root: Path,
    request_path: Path,
    controller: CandidateAuthoringController,
) -> ControllerResult:
    """Execute at most once in a request-owned workspace and publish only exact outputs."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    request, request_artifact = _load_request(root, request_path)
    if str(controller.controller_kind) != request.controller_kind:
        raise ValueError("controller kind does not match the immutable execution request")
    profile = _load_profile(root, request.tool_profile)
    _validate_request_profile(request, profile)
    for item in [request.assignment, *request.immutable_inputs, request.tool_profile]:
        _validate_input(root, item)
    validate_material_retry_supersession_admission(
        root,
        candidate_artifacts=[
            MaterialRetryAdmissionArtifact(
                path=item.path,
                sha256=item.sha256,
                byte_size=item.byte_size,
            )
            for item in (request.assignment, *request.immutable_inputs)
        ],
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=request.dispatch_id,
        session_id=request.session_id,
    )
    workspace = _prepare_workspace(
        root=root,
        request_path=request_path,
        request=request,
        request_artifact=request_artifact,
    )
    _validate_staging_precondition(
        root=root,
        request=request,
        workspace=workspace,
    )
    invocation_path = workspace.evidence_root / "invocation.json"
    existing_invocation = _load_invocation_receipt(
        root=root,
        path=invocation_path,
        request=request,
        request_artifact=request_artifact,
        started_artifact=workspace.started_receipt,
    )
    records_before, extra_before, missing_before = _output_inventory(workspace)
    evidence_members = _validate_evidence_inventory(workspace.evidence_root)
    _validate_evidence_stage_order(evidence_members)
    if "completed.json" in evidence_members and (extra_before or missing_before):
        raise ValueError(
            "controller completion evidence no longer has its exact workspace outputs"
        )
    if "completed.json" in evidence_members:
        existing_invocation_artifact = (
            existing_invocation[1] if existing_invocation is not None else None
        )
        if existing_invocation is not None and existing_invocation[0]["token"] not in {
            "completed",
            "adopt_existing",
        }:
            raise ValueError(
                "controller completion evidence follows a non-completing invocation"
            )
        _complete_validated_outputs(
            root=root,
            request=request,
            request_artifact=request_artifact,
            workspace=workspace,
            records=records_before,
            invocation_artifact=existing_invocation_artifact,
        )
    diagnostics: list[str] = []
    invoked_this_call = False
    invocation_artifact: ControllerArtifact | None = None
    result_completed_at: datetime | None = None
    if extra_before:
        token = "rejected"
        diagnostics.append("unexpected workspace paths: " + ", ".join(extra_before))
        started_at = _receipt_timestamp(workspace.started_payload, "recorded_at")
        result_completed_at = started_at
    elif existing_invocation is not None:
        invocation_payload, invocation_artifact = existing_invocation
        token = cast(str, invocation_payload["token"])
        diagnostics.extend(cast(list[str], invocation_payload["diagnostics"]))
        started_at = _receipt_timestamp(invocation_payload, "started_at")
        result_completed_at = _receipt_timestamp(invocation_payload, "completed_at")
        original_inventory = cast(list[dict[str, Any]], invocation_payload["inventory"])
        original_extra = cast(list[str], invocation_payload["extra_paths"])
        original_missing = cast(list[str], invocation_payload["missing_paths"])
        if request.controller_kind != "desktop_in_session" and (
            records_before != original_inventory
            or extra_before != original_extra
            or missing_before != original_missing
        ):
            token = "rejected"
            diagnostics.append("controller workspace changed after its single invocation")
    elif workspace.started_adopted:
        started_at = _receipt_timestamp(workspace.started_payload, "recorded_at")
        result_completed_at = started_at
        if not extra_before and not missing_before:
            token = "adopt_existing"
            diagnostics.append("adopted complete outputs from an interrupted request")
        else:
            token = "rejected"
            diagnostics.append(
                "interrupted controller request has no complete request-bound output"
            )
    else:
        invoked_this_call = True
        started_at = datetime.now(UTC)
        excluded = (workspace.root,)
        job_before = _job_inventory_excluding(root, excluded)
        try:
            try:
                token = controller.execute(
                    assignment=workspace.assignment,
                    immutable_inputs=workspace.immutable_inputs,
                    allowed_output_paths=tuple(
                        workspace.output_map[item] for item in request.allowed_output_paths
                    ),
                    tool_profile=profile.model_copy(deep=True),
                    timeout_seconds=request.timeout_seconds,
                )
            except TimeoutError:
                token = "timeout"
                diagnostics.append(
                    "controller raised TimeoutError before validated completion"
                )
            except Exception as exc:  # noqa: BLE001 - bounded failure evidence only.
                token = "failed"
                diagnostics.append(f"controller exception: {type(exc).__name__}")
        finally:
            job_after = _job_inventory_excluding(root, excluded)
            if job_after != job_before:
                changed = sorted(set(job_before) ^ set(job_after))
                changed.extend(
                    path
                    for path in sorted(set(job_before) & set(job_after))
                    if job_before[path] != job_after[path]
                )
                raise PermissionError(
                    "controller changed files outside its workspace: "
                    + ", ".join(changed)
                )
            _validate_workspace_inputs(workspace, request)
            for item in [
                request.assignment,
                *request.immutable_inputs,
                request.tool_profile,
            ]:
                _validate_input(root, item)
        records_after_call, extra_after_call, missing_after_call = _output_inventory(
            workspace
        )
        completed_at = datetime.now(UTC)
        _invocation_payload, invocation_artifact, _ = _write_or_adopt_receipt(
            root=root,
            path=invocation_path,
            execution_id=request.execution_id,
            stage="invocation",
            expected={
                "request_sha256": request_artifact.sha256,
                "started_receipt_sha256": workspace.started_receipt.sha256,
                "controller_kind": request.controller_kind,
                "token": token,
                "inventory": records_after_call,
                "extra_paths": extra_after_call,
                "missing_paths": missing_after_call,
                "diagnostics": diagnostics,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
            },
        )
        result_completed_at = _receipt_timestamp(
            _invocation_payload,
            "completed_at",
        )

    _validate_workspace_inputs(workspace, request)
    records, extra_paths, missing_paths = _output_inventory(workspace)
    if extra_paths:
        diagnostics.append("unexpected workspace paths: " + ", ".join(extra_paths))
    if missing_paths:
        diagnostics.append("missing output paths: " + ", ".join(missing_paths))
    if any(cast(int, item["byte_size"]) <= 0 for item in records):
        diagnostics.append("controller outputs must be non-empty regular files")
        token = "rejected"
    if not _validate_expected_hashes(request, records, diagnostics):
        token = "rejected"
    status, retryable = _result_status(
        token,
        missing=len(missing_paths),
        extra=len(extra_paths),
    )
    if token == "rejected":
        status = "rejected"
        retryable = False

    evidence: list[ControllerArtifact] = [workspace.started_receipt]
    if invocation_artifact is not None:
        evidence.append(invocation_artifact)

    outputs: list[ControllerArtifact] = []
    completed_at = datetime.now(UTC)
    if status == "completed":
        completed_artifact = _complete_validated_outputs(
            root=root,
            request=request,
            request_artifact=request_artifact,
            workspace=workspace,
            records=records,
            invocation_artifact=invocation_artifact,
        )
        evidence.append(completed_artifact)
        if not invoked_this_call:
            _adoption_payload, _adoption_artifact, _ = _write_or_adopt_receipt(
                root=root,
                path=workspace.evidence_root / "adopted.json",
                execution_id=request.execution_id,
                stage="adopted",
                expected={
                    "request_sha256": request_artifact.sha256,
                    "started_receipt_sha256": workspace.started_receipt.sha256,
                    "completed_receipt_sha256": completed_artifact.sha256,
                    "outputs": records,
                },
            )
        outputs, publication_evidence, completed_at = _publish_validated_outputs(
            root=root,
            request=request,
            request_artifact=request_artifact,
            workspace=workspace,
            records=records,
            completed_artifact=completed_artifact,
        )
        evidence.extend(publication_evidence)
    inventory_payload = records
    now = completed_at if status == "completed" else result_completed_at
    if now is None:
        raise RuntimeError("controller result has no deterministic completion timestamp")
    input_payload = {
        "request": request_artifact.sha256,
        "tool_profile": request.tool_profile.sha256,
        "workspace_started": workspace.started_receipt.sha256,
        "inventory": inventory_payload,
        "token": token,
    }
    provenance = [
        request_artifact,
        request.assignment,
        request.tool_profile,
        *request.immutable_inputs,
        *evidence,
    ]
    if status == "completed":
        provenance.extend(outputs)
    return ControllerResult(
        contract_id=f"result-{request.execution_id}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=request.dispatch_id,
        session_id=request.session_id,
        input_sha256=stable_json_digest(input_payload),
        source_fingerprint=stable_json_digest(
            {**input_payload, "status": status, "output_count": len(outputs)}
        ),
        producer="codex_blender_modeler.production.controller_executor.service",
        provenance=provenance,
        created_at=now,
        execution_id=request.execution_id,
        controller_kind=cast(str, request.controller_kind),
        status=cast(str, status),
        request=request_artifact,
        tool_profile=request.tool_profile,
        outputs=outputs,
        output_inventory_sha256=stable_json_digest(inventory_payload),
        extra_output_count=len(extra_paths),
        partial_output_count=len(missing_paths),
        retryable=retryable,
        limitations=(
            [
                "repository validation does not attest an external client sandbox",
                "result grants no canonical write or approval authority",
            ]
            if profile.sandbox_attestation == "repository_path_validation_only"
            else ["result grants no canonical write or approval authority"]
        ),
        diagnostics=diagnostics,
        started_at=started_at,
        completed_at=now,
    )


def validate_controller_execution_result(
    *,
    job_root: Path,
    request_path: Path,
    result_path: Path,
    controller: CandidateAuthoringController,
) -> ControllerResult:
    """Reconstruct the full executor lifecycle and require exact stored result bytes."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    stored_path = ensure_contained_production_path(root, result_path, must_exist=True)
    if not os.path.isfile(native_io_path(stored_path)):
        raise ValueError("stored controller result is not a regular file")
    stored_bytes = Path(native_io_path(stored_path)).read_bytes()
    stored = ControllerResult.model_validate_json(stored_bytes)
    reconstructed = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )
    expected_bytes = native_json_bytes(reconstructed.model_dump(mode="json"))
    if stored_bytes != expected_bytes or stored != reconstructed:
        raise ValueError(
            "stored controller result differs from the fully reconstructed executor result"
        )
    return stored


def write_controller_contract(
    path: Path,
    model: ControllerExecutionRequest | PhaseToolProfile,
) -> None:
    """Write one controller contract deterministically for host-owned staging tests and plans."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    encoded = json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    with open(native_io_path(path), "x", encoding="utf-8") as handle:
        handle.write(encoded)


def production_artifact_from_controller(item: ControllerArtifact) -> ProductionArtifact:
    """Project a controller artifact into the existing V0.9 path/hash binding shape."""

    return ProductionArtifact(path=item.path, sha256=item.sha256)
