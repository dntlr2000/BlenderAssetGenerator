"""Cross-layer admission enforcement for exact material-retry supersessions."""

from __future__ import annotations

import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .blender_artifacts import native_io_path, sha256_file
from .production.validation import ensure_contained_production_path


@dataclass(frozen=True)
class MaterialRetryAdmissionArtifact:
    """Describe exact candidate bytes that may represent a material retry plan."""

    path: str
    sha256: str
    byte_size: int


class _ExactArtifactLike(Protocol):
    """Expose the exact artifact fields shared by controller and closure models."""

    path: str
    sha256: str
    byte_size: int


def _path_exists(path: Path) -> bool:
    """Check one potentially long Windows path without following an unchecked alias."""

    return os.path.exists(native_io_path(path))


def _path_is_file(path: Path) -> bool:
    """Check that one contained supersession member is a regular file."""

    return os.path.isfile(native_io_path(path))


def _path_is_dir(path: Path) -> bool:
    """Check that one contained supersession member is a directory."""

    return os.path.isdir(native_io_path(path))


def _directory_names(path: Path) -> list[str]:
    """List one already-contained directory deterministically through native I/O paths."""

    try:
        names = [entry.name for entry in os.scandir(native_io_path(path))]
    except OSError as exc:
        raise ValueError("material retry supersession root cannot be inventoried") from exc
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("material retry supersession root has ambiguous case aliases")
    return sorted(names, key=lambda item: (item.casefold(), item))


def _validate_exact_artifact(
    job_root: Path,
    artifact: _ExactArtifactLike,
    *,
    label: str,
) -> None:
    """Rehash one strict ExactArtifact-like object and reject stale or special bytes."""

    relative = str(artifact.path)
    path = ensure_contained_production_path(
        job_root,
        job_root.joinpath(*relative.split("/")),
        must_exist=True,
    )
    if not _path_is_file(path):
        raise ValueError(f"material retry supersession {label} is not a regular file")
    if (
        os.path.getsize(native_io_path(path)) != int(artifact.byte_size)
        or sha256_file(path) != str(artifact.sha256)
    ):
        raise ValueError(f"material retry supersession {label} bytes changed")


def _validate_receipt_artifacts(
    job_root: Path,
    receipt: object,
    *,
    receipt_directory: Path,
    session_prefix: str,
) -> None:
    """Rehash every receipt dependency and validate approval-absence linkage."""

    # Import lazily so ControllerExecutor can use this guard without a package cycle.
    from .material_closure.models import MaterialRetryApprovalAbsence

    artifacts = [
        ("retry plan", receipt.retry_plan),
        ("current state", receipt.current_state),
        ("framework failure report", receipt.framework_failure_report),
    ]
    retry_approval = receipt.retry_approval
    retry_approval_absence = receipt.retry_approval_absence
    if retry_approval is not None:
        artifacts.append(("retry approval", retry_approval))
    if retry_approval_absence is not None:
        artifacts.append(("retry approval absence", retry_approval_absence))
    for label, artifact in artifacts:
        if not str(artifact.path).startswith(session_prefix):
            raise ValueError(
                f"material retry supersession {label} escapes its AQ session scope"
            )
        _validate_exact_artifact(job_root, artifact, label=label)

    absence_name = "approval_absence.json"
    expected_members = {"receipt.json"}
    if retry_approval_absence is not None:
        expected_members.add(absence_name)
        expected_absence_path = (
            receipt_directory / absence_name
        ).relative_to(job_root).as_posix()
        if retry_approval_absence.path != expected_absence_path:
            raise ValueError(
                "material retry supersession approval absence is outside its receipt root"
            )
        absence_path = ensure_contained_production_path(
            job_root,
            receipt_directory / absence_name,
            must_exist=True,
        )
        try:
            absence = MaterialRetryApprovalAbsence.model_validate_json(
                Path(native_io_path(absence_path)).read_bytes()
            )
        except Exception as exc:
            raise ValueError(
                "material retry supersession approval absence is malformed"
            ) from exc
        if (
            absence.job_id != receipt.job_id
            or absence.workflow_id != receipt.workflow_id
            or absence.dispatch_id != receipt.dispatch_id
            or absence.session_id != receipt.session_id
            or absence.retry_plan != receipt.retry_plan
            or absence.observation_state != receipt.current_state
        ):
            raise ValueError(
                "material retry supersession approval absence has mismatched scope"
            )
    if set(_directory_names(receipt_directory)) != expected_members:
        raise ValueError("material retry supersession receipt root has unexpected members")


def _discover_current_supersession_receipts(
    job_root: Path,
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
) -> list[object]:
    """Strict-parse and rehash every receipt in one current AQ retry root."""

    # Import lazily so ControllerExecutor's service module remains independently importable.
    from .material_closure.models import MaterialRetrySupersessionReceipt

    retry_root = ensure_contained_production_path(
        job_root,
        job_root / "production" / "autonomy_v2" / session_id / "retry_supersessions",
        must_exist=False,
    )
    if not _path_exists(retry_root):
        return []
    retry_root = ensure_contained_production_path(
        job_root,
        retry_root,
        must_exist=True,
    )
    if not _path_is_dir(retry_root):
        raise ValueError("material retry supersession root is not a directory")
    receipt_names = _directory_names(retry_root)
    if not receipt_names:
        raise ValueError("material retry supersession root is empty")
    receipts: list[object] = []
    session_prefix = f"production/autonomy_v2/{session_id}/"
    for receipt_name in receipt_names:
        receipt_directory = ensure_contained_production_path(
            job_root,
            retry_root / receipt_name,
            must_exist=True,
        )
        if not _path_is_dir(receipt_directory):
            raise ValueError("material retry supersession root contains a non-directory")
        receipt_path = ensure_contained_production_path(
            job_root,
            receipt_directory / "receipt.json",
            must_exist=True,
        )
        if not _path_is_file(receipt_path):
            raise ValueError("material retry supersession receipt is not a regular file")
        try:
            receipt = MaterialRetrySupersessionReceipt.model_validate_json(
                Path(native_io_path(receipt_path)).read_bytes()
            )
        except Exception as exc:
            raise ValueError("material retry supersession receipt is malformed") from exc
        if receipt.receipt_id != receipt_name:
            raise ValueError(
                "material retry supersession directory and receipt identity differ"
            )
        if (
            receipt.job_id,
            receipt.workflow_id,
            receipt.dispatch_id,
            receipt.session_id,
        ) != (job_id, workflow_id, dispatch_id, session_id):
            raise ValueError("material retry supersession receipt scope differs")
        _validate_receipt_artifacts(
            job_root,
            receipt,
            receipt_directory=receipt_directory,
            session_prefix=session_prefix,
        )
        receipts.append(receipt)
    return receipts


def validate_material_retry_supersession_admission(
    job_root: Path,
    *,
    candidate_artifacts: Collection[MaterialRetryAdmissionArtifact],
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
) -> None:
    """Reject an exact superseded retry before any controller or retry side effect."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    for candidate in candidate_artifacts:
        candidate_path = ensure_contained_production_path(
            root,
            root.joinpath(*candidate.path.split("/")),
            must_exist=True,
        )
        if not _path_is_file(candidate_path):
            raise ValueError("material retry admission candidate is not a regular file")
        if (
            os.path.getsize(native_io_path(candidate_path)) != candidate.byte_size
            or sha256_file(candidate_path) != candidate.sha256
        ):
            raise ValueError("material retry admission candidate bytes changed")
    receipts = _discover_current_supersession_receipts(
        root,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
    )
    candidate_keys = {
        (item.path, item.sha256, item.byte_size) for item in candidate_artifacts
    }
    matches = [
        receipt
        for receipt in receipts
        if (
            receipt.retry_plan.path,
            receipt.retry_plan.sha256,
            receipt.retry_plan.byte_size,
        )
        in candidate_keys
    ]
    if len(matches) > 1:
        raise ValueError("material retry supersession admission is ambiguous")
    if matches:
        raise PermissionError(
            "material retry plan is non-executable because its exact bytes were superseded"
        )


__all__ = [
    "MaterialRetryAdmissionArtifact",
    "validate_material_retry_supersession_admission",
]
