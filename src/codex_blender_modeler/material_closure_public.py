"""Thin public host adapters for generic Material Closure evidence and read-only status."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from .autonomy_v2 import AQV2Artifact, get_autonomy_v2_material_closure_status
from .blender_artifacts import native_io_path, publish_bytes_create_once
from .material_closure.collector import (
    build_material_plan_absence_evidence,
    collect_material_dependency_closure_from_roots,
)
from .material_closure.graph_rebinding import (
    apply_material_graph_rebinding,
    serialize_rebound_material_graph,
)
from .material_closure.incident_service import (
    publish_current_material_canonical_observations,
    publish_material_closure_model,
    publish_material_repair_session_plan,
)
from .material_closure.incident_service import (
    run_material_repair_session as execute_material_repair_session,
)
from .material_closure.incident_service import (
    supersede_material_retry as publish_material_retry_supersession,
)
from .material_closure.models import (
    ExactArtifact,
    MaterialAppearanceApproval,
    MaterialAttemptState,
    MaterialCanonicalSnapshot,
    MaterialClosureSourceBindingArtifact,
    MaterialDependencyClosure,
    MaterialDependencyClosureReceipt,
    MaterialFrameworkFailureReport,
    MaterialGraphRebindingPlan,
    MaterialGraphRebindingReceipt,
    MaterialPlannedOutput,
    MaterialPromotionPreflightRequest,
    MaterialRepairSessionPlan,
    MaterialRepairSourceBinding,
    MaterialRetrySupersessionReceipt,
    MaterialSessionSupersessionReceipt,
    MaterialStateConsistencyReport,
)
from .material_closure.repair_session import (
    validate_material_repair_session,
    verify_material_repair_geometry,
)
from .material_closure.service import (
    MaterialClosureService,
    material_shadow_compile,
    publish_material_appearance_approval,
)
from .material_closure.state_consistency import (
    build_material_canonical_snapshot,
    compare_material_state_to_canonical,
)
from .versioning import MATERIAL_CLOSURE_SCHEMA_VERSION
from .workspace import job_dir, sha256_file

ModelT = TypeVar("ModelT", bound=BaseModel)
_PRODUCER = "cbm_material_closure_public"


def _job_root(job_id: str) -> Path:
    """Resolve one existing workspace job without creating or migrating it."""

    root = job_dir(job_id).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root


def _contained_file(root: Path, relative_path: str) -> Path:
    """Resolve one regular non-link POSIX path contained by the owning job."""

    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or "\\" in relative_path
    ):
        raise ValueError("material closure path must be contained relative POSIX")
    candidate = root.joinpath(*pure.parts)
    if candidate.is_symlink():
        raise ValueError("material closure public inputs cannot be symbolic links")
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(root)
    if not os.path.isfile(native_io_path(resolved)):
        raise FileNotFoundError(resolved)
    return resolved


def _load_model(root: Path, relative_path: str, model: type[ModelT]) -> ModelT:
    """Load one strict JSON model from a contained immutable-evidence path."""

    return model.model_validate_json(
        Path(native_io_path(_contained_file(root, relative_path))).read_bytes()
    )


def _exact_artifact(
    root: Path,
    relative_path: str,
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Bind one current contained file to its exact size and SHA-256."""

    path = _contained_file(root, relative_path)
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative_path,
        sha256=sha256_file(path),
        byte_size=os.path.getsize(native_io_path(path)),
        media_type="application/json",
    )


def _publish_bytes_exact(
    root: Path,
    relative_path: str,
    content: bytes,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> ExactArtifact:
    """Publish one immutable byte payload or exact-adopt identical existing bytes."""

    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError("material closure output must be a contained relative path")
    path = root.joinpath(*pure.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_parent = path.parent.resolve(strict=True)
    resolved_parent.relative_to(root)
    if path.is_symlink() or resolved_parent.is_symlink():
        raise ValueError("material closure output cannot use symbolic links")
    try:
        publish_bytes_create_once(path, content)
    except FileExistsError as exc:
        raise FileExistsError(
            f"conflicting immutable material evidence: {relative_path}"
        ) from exc
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative_path,
        sha256=sha256_file(path),
        byte_size=os.path.getsize(native_io_path(path)),
        media_type=media_type,
    )


def _aq_artifact(
    root: Path,
    relative_path: str,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Bind one closure companion to the legacy AQ v2 exact-artifact envelope."""

    exact = _exact_artifact(
        root,
        relative_path,
        artifact_id=artifact_id,
        kind=kind,
    )
    return AQV2Artifact(
        artifact_id=exact.artifact_id,
        kind=exact.kind,
        path=exact.path,
        sha256=exact.sha256,
        byte_size=exact.byte_size,
    )


def _planned_outputs(root: Path, relative_path: str) -> list[MaterialPlannedOutput]:
    """Load a strict planned-output array or one object containing that array."""

    payload = json.loads(
        Path(native_io_path(_contained_file(root, relative_path))).read_text(
            encoding="utf-8"
        )
    )
    values = payload.get("planned_outputs") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValueError("planned outputs JSON must be an array or planned_outputs object")
    return [MaterialPlannedOutput.model_validate(item) for item in values]


def plan_material_closure(
    job_id: str,
    *,
    source_binding_path: str,
    planned_outputs_path: str,
    closure_id: str | None = None,
) -> dict[str, Any]:
    """Collect and immutably publish one closure plus its exact passed receipt."""

    root = _job_root(job_id)
    binding = _load_model(
        root,
        source_binding_path,
        MaterialClosureSourceBindingArtifact,
    )
    binding_artifact = _exact_artifact(
        root,
        source_binding_path,
        artifact_id=binding.binding_id,
        kind="material_closure_source_binding",
    )
    resolved_closure_id = closure_id or f"material-closure-{uuid4().hex[:12]}"
    closure_relative = (
        f"production/material_closure/{binding.session_id}/closures/"
        f"{resolved_closure_id}/closure.json"
    )
    existing_closure_path = root.joinpath(*closure_relative.split("/"))
    created_at = (
        MaterialDependencyClosure.model_validate_json(
            Path(native_io_path(existing_closure_path)).read_bytes()
        ).created_at
        if os.path.isfile(native_io_path(existing_closure_path))
        else datetime.now(UTC)
    )
    closure = collect_material_dependency_closure_from_roots(
        job_root=root,
        source_binding=binding_artifact,
        closure_id=resolved_closure_id,
        job_id=binding.job_id,
        workflow_id=binding.workflow_id,
        dispatch_id=binding.dispatch_id,
        session_id=binding.session_id,
        producer=_PRODUCER,
        producer_version=MATERIAL_CLOSURE_SCHEMA_VERSION,
        created_at=created_at,
        planned_outputs=_planned_outputs(root, planned_outputs_path),
    )
    closure, closure_artifact = publish_material_closure_model(
        root,
        closure_relative,
        closure,
        artifact_id=resolved_closure_id,
        kind="material_dependency_closure",
    )
    receipt = MaterialDependencyClosureReceipt(
        receipt_id=f"receipt-{resolved_closure_id}",
        job_id=binding.job_id,
        workflow_id=binding.workflow_id,
        dispatch_id=binding.dispatch_id,
        session_id=binding.session_id,
        producer=_PRODUCER,
        producer_version=MATERIAL_CLOSURE_SCHEMA_VERSION,
        created_at=created_at,
        closure=closure_artifact,
        closure_sha256=closure.closure_sha256,
        status="passed",
        immutable_input_projection=closure.project_immutable_input_map(),
        planned_output_projection=closure.project_planned_output_map(),
    )
    receipt, receipt_artifact = publish_material_closure_model(
        root,
        (
            f"production/material_closure/{binding.session_id}/closures/"
            f"{resolved_closure_id}/receipt.json"
        ),
        receipt,
        artifact_id=receipt.receipt_id,
        kind="material_dependency_closure_receipt",
    )
    return {
        "closure": closure.model_dump(mode="json"),
        "closure_artifact": closure_artifact.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
        "receipt_artifact": receipt_artifact.model_dump(mode="json"),
    }


def _discover_material_companion(
    root: Path,
    *,
    job_id: str,
    session_id: str,
    model: type[ModelT],
    explicit_path: str | None,
    kind: str,
) -> AQV2Artifact | None:
    """Resolve an explicit companion or the unique newest strict session-bound record."""

    if explicit_path is not None:
        value = _load_model(root, explicit_path, model)
        if value.job_id != job_id:
            raise ValueError(f"{model.__name__} targets another job")
        return _aq_artifact(
            root,
            explicit_path,
            artifact_id=Path(explicit_path).stem,
            kind=kind,
        )
    search_roots = (
        root / "production" / "material_closure" / session_id,
        root / "production" / "autonomy_v2" / session_id,
        root / "production" / "material_repair" / session_id,
    )
    candidates: list[tuple[datetime, str, ModelT]] = []
    for search_root in search_roots:
        if not search_root.is_dir() or search_root.is_symlink():
            continue
        for path in search_root.rglob("*.json"):
            if not os.path.isfile(native_io_path(path)) or path.is_symlink():
                continue
            try:
                value = model.model_validate_json(Path(native_io_path(path)).read_bytes())
            except (OSError, ValidationError):
                continue
            model_session = getattr(value, "session_id", None)
            if model is MaterialSessionSupersessionReceipt:
                session_matches = (
                    model_session == session_id
                    or getattr(value, "superseded_session_id", None) == session_id
                )
            else:
                session_matches = model_session == session_id
            if value.job_id != job_id or not session_matches:
                continue
            candidates.append(
                (value.created_at, path.relative_to(root).as_posix(), value)
            )
    if not candidates:
        return None
    newest = max(item[0] for item in candidates)
    current = [item for item in candidates if item[0] == newest]
    if len(current) != 1:
        paths = ", ".join(sorted(item[1] for item in current))
        raise ValueError(f"conflicting current {model.__name__} evidence: {paths}")
    _created_at, relative, value = current[0]
    artifact_id = str(
        next(
            (
                getattr(value, field)
                for field in (
                    "attempt_id",
                    "report_id",
                    "receipt_id",
                    "plan_id",
                    "snapshot_id",
                )
                if hasattr(value, field)
            ),
            Path(relative).stem,
        )
    )
    return _aq_artifact(
        root,
        relative,
        artifact_id=artifact_id,
        kind=kind,
    )


def _validate_supersession_references_current(
    root: Path,
    value: MaterialRetrySupersessionReceipt | MaterialSessionSupersessionReceipt,
) -> None:
    """Require every direct supersession binding to retain its declared exact bytes."""

    references = (
        (
            value.retry_plan,
            value.retry_approval,
            value.retry_approval_absence,
            value.current_state,
            value.framework_failure_report,
        )
        if isinstance(value, MaterialRetrySupersessionReceipt)
        else (
            value.superseded_state,
            value.framework_failure_report,
            value.repair_session_plan,
        )
    )
    for reference in references:
        if reference is None:
            continue
        current = _exact_artifact(
            root,
            reference.path,
            artifact_id=reference.artifact_id,
            kind=reference.kind,
        )
        if (current.sha256, current.byte_size) != (
            reference.sha256,
            reference.byte_size,
        ):
            raise ValueError(f"supersession dependency changed: {reference.path}")


def _canonical_supersession_path(
    value: MaterialRetrySupersessionReceipt | MaterialSessionSupersessionReceipt,
) -> str:
    """Return the sole canonical repository leaf for one supersession receipt."""

    if isinstance(value, MaterialRetrySupersessionReceipt):
        return (
            f"production/autonomy_v2/{value.session_id}/retry_supersessions/"
            f"{value.receipt_id}/receipt.json"
        )
    return (
        f"production/autonomy_v2/{value.superseded_session_id}/"
        f"material_session_supersessions/{value.receipt_id}.json"
    )


def _path_is_link_or_reparse(path: Path) -> bool:
    """Inspect one lexical path for POSIX link or Windows reparse metadata."""

    try:
        metadata = os.lstat(native_io_path(path))
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _strict_directories(path: Path) -> list[Path]:
    """List direct directories while failing closed on linked hierarchy members."""

    if not os.path.lexists(native_io_path(path)):
        return []
    if _path_is_link_or_reparse(path) or not path.is_dir():
        raise ValueError(f"canonical supersession hierarchy is not a directory: {path}")
    directories: list[Path] = []
    for member in sorted(path.iterdir(), key=lambda item: item.name):
        if _path_is_link_or_reparse(member):
            raise ValueError(
                f"canonical supersession hierarchy contains a link: {member}"
            )
        if member.is_dir():
            directories.append(member)
    return directories


def _canonical_supersession_candidates(
    root: Path,
    *,
    session_id: str,
    model: type[MaterialRetrySupersessionReceipt]
    | type[MaterialSessionSupersessionReceipt],
) -> list[str]:
    """Enumerate only canonical retry or cross-session supersession receipt leaves."""

    autonomy_root = root / "production" / "autonomy_v2"
    candidates: list[Path] = []
    if model is MaterialRetrySupersessionReceipt:
        retry_root = autonomy_root / session_id / "retry_supersessions"
        for receipt_root in _strict_directories(retry_root):
            candidate = receipt_root / "receipt.json"
            if os.path.lexists(native_io_path(candidate)):
                candidates.append(candidate)
    else:
        for source_session_root in _strict_directories(autonomy_root):
            receipt_root = source_session_root / "material_session_supersessions"
            if not os.path.lexists(native_io_path(receipt_root)):
                continue
            if _path_is_link_or_reparse(receipt_root) or not receipt_root.is_dir():
                raise ValueError(
                    "canonical session supersession hierarchy is not a directory: "
                    f"{receipt_root}"
                )
            candidates.extend(
                member
                for member in sorted(receipt_root.iterdir(), key=lambda item: item.name)
                if member.suffix == ".json"
            )
    relative_paths: list[str] = []
    for candidate in candidates:
        if _path_is_link_or_reparse(candidate) or not candidate.is_file():
            raise ValueError(
                f"canonical supersession leaf is not a regular file: {candidate}"
            )
        relative_paths.append(candidate.relative_to(root).as_posix())
    return relative_paths


def _discover_material_supersessions(
    root: Path,
    *,
    job_id: str,
    session_id: str,
    model: type[MaterialRetrySupersessionReceipt]
    | type[MaterialSessionSupersessionReceipt],
    explicit_path: str | None,
    kind: str,
) -> list[tuple[str, BaseModel, AQV2Artifact]]:
    """Return strict canonical supersessions and expose malformed canonical leaves."""

    if explicit_path is not None:
        paths = [explicit_path]
    else:
        paths = _canonical_supersession_candidates(
            root,
            session_id=session_id,
            model=model,
        )
    results: list[tuple[str, BaseModel, AQV2Artifact]] = []
    for relative in paths:
        try:
            value = _load_model(root, relative, model)
        except (OSError, ValidationError) as exc:
            if explicit_path is not None:
                raise
            raise ValueError(
                f"malformed canonical {model.__name__} evidence: {relative}"
            ) from exc
        canonical_relative = _canonical_supersession_path(value)
        if relative != canonical_relative:
            raise ValueError(
                f"non-canonical {model.__name__} evidence path: {relative}; "
                f"expected {canonical_relative}"
            )
        session_matches = value.session_id == session_id
        if isinstance(value, MaterialSessionSupersessionReceipt):
            session_matches = session_matches or value.superseded_session_id == session_id
        if value.job_id != job_id:
            raise ValueError(f"{model.__name__} targets another job")
        if not session_matches:
            if explicit_path is not None:
                raise ValueError(f"{model.__name__} targets another session")
            continue
        _validate_supersession_references_current(root, value)
        results.append(
            (
                relative,
                value,
                _aq_artifact(
                    root,
                    relative,
                    artifact_id=value.receipt_id,
                    kind=kind,
                ),
            )
        )
    return results


def _require_retry_supersessions_unambiguous(
    entries: list[tuple[str, BaseModel, AQV2Artifact]],
) -> None:
    """Fail closed when one retry plan has substantively conflicting receipts."""

    grouped: dict[tuple[str, str, int], list[MaterialRetrySupersessionReceipt]] = {}
    for _path, value, _artifact in entries:
        assert isinstance(value, MaterialRetrySupersessionReceipt)
        key = (
            value.retry_plan.path,
            value.retry_plan.sha256,
            value.retry_plan.byte_size,
        )
        grouped.setdefault(key, []).append(value)
    excluded = {"receipt_id", "producer", "producer_version", "created_at"}
    for retry_plan, receipts in grouped.items():
        projections = {
            json.dumps(
                receipt.model_dump(mode="json", exclude=excluded),
                sort_keys=True,
                separators=(",", ":"),
            )
            for receipt in receipts
        }
        if len(projections) > 1:
            raise ValueError(
                "conflicting retry supersessions target the same exact plan: "
                f"{retry_plan[0]}"
            )


def _session_supersession_ambiguities(
    entries: list[tuple[str, BaseModel, AQV2Artifact]],
) -> list[dict[str, object]]:
    """Describe one old state linked to multiple active repair targets without choosing."""

    grouped: dict[tuple[str, str, int], list[tuple[str, MaterialSessionSupersessionReceipt]]] = {}
    for path, value, _artifact in entries:
        assert isinstance(value, MaterialSessionSupersessionReceipt)
        key = (
            value.superseded_state.path,
            value.superseded_state.sha256,
            value.superseded_state.byte_size,
        )
        grouped.setdefault(key, []).append((path, value))
    ambiguities: list[dict[str, object]] = []
    for state, receipts in sorted(grouped.items()):
        targets = {
            (
                receipt.repair_session_plan.path,
                receipt.repair_session_plan.sha256,
                receipt.repair_session_plan.byte_size,
            )
            for _path, receipt in receipts
        }
        if len(targets) > 1:
            ambiguities.append(
                {
                    "superseded_state": {
                        "path": state[0],
                        "sha256": state[1],
                        "byte_size": state[2],
                    },
                    "receipt_paths": sorted(path for path, _receipt in receipts),
                    "repair_targets": [
                        {"path": path, "sha256": sha256, "byte_size": byte_size}
                        for path, sha256, byte_size in sorted(targets)
                    ],
                    "policy": "ambiguous_no_active_target_selected",
                }
            )
    return ambiguities


def get_material_closure_status(
    job_id: str,
    session_id: str,
    *,
    material_attempt_path: str | None = None,
    consistency_report_path: str | None = None,
    framework_failure_path: str | None = None,
    retry_supersession_path: str | None = None,
    session_supersession_path: str | None = None,
) -> dict[str, object]:
    """Auto-discover current companions and return them beside preserved raw AQ state."""

    root = _job_root(job_id)
    retry_entries = _discover_material_supersessions(
        root,
        job_id=job_id,
        session_id=session_id,
        model=MaterialRetrySupersessionReceipt,
        explicit_path=retry_supersession_path,
        kind="material_retry_supersession_receipt",
    )
    _require_retry_supersessions_unambiguous(retry_entries)
    session_entries = _discover_material_supersessions(
        root,
        job_id=job_id,
        session_id=session_id,
        model=MaterialSessionSupersessionReceipt,
        explicit_path=session_supersession_path,
        kind="material_session_supersession_receipt",
    )
    outbound_session_entries = [
        entry
        for entry in session_entries
        if isinstance(entry[1], MaterialSessionSupersessionReceipt)
        and entry[1].superseded_session_id == session_id
    ]
    incoming_session_entries = [
        entry
        for entry in session_entries
        if isinstance(entry[1], MaterialSessionSupersessionReceipt)
        and entry[1].session_id == session_id
    ]
    session_ambiguities = _session_supersession_ambiguities(
        outbound_session_entries
    )
    result = get_autonomy_v2_material_closure_status(
        job_id,
        session_id,
        material_attempt=_discover_material_companion(
            root,
            job_id=job_id,
            session_id=session_id,
            model=MaterialAttemptState,
            explicit_path=material_attempt_path,
            kind="material_attempt_state",
        ),
        consistency_report=_discover_material_companion(
            root,
            job_id=job_id,
            session_id=session_id,
            model=MaterialStateConsistencyReport,
            explicit_path=consistency_report_path,
            kind="material_state_consistency_report",
        ),
        framework_failure=_discover_material_companion(
            root,
            job_id=job_id,
            session_id=session_id,
            model=MaterialFrameworkFailureReport,
            explicit_path=framework_failure_path,
            kind="material_framework_failure_report",
        ),
        retry_supersession=(None if not retry_entries else retry_entries[0][2]),
        session_supersession=(
            None
            if not outbound_session_entries or session_ambiguities
            else outbound_session_entries[0][2]
        ),
    )
    result["retry_supersessions"] = [
        value.model_dump(mode="json") for _path, value, _artifact in retry_entries
    ]
    result["retry_supersession_artifacts"] = [
        artifact.model_dump(mode="json") for _path, _value, artifact in retry_entries
    ]
    result["session_supersessions"] = [
        value.model_dump(mode="json") for _path, value, _artifact in session_entries
    ]
    result["session_supersession_artifacts"] = [
        artifact.model_dump(mode="json") for _path, _value, artifact in session_entries
    ]
    result["outbound_session_supersessions"] = [
        value.model_dump(mode="json")
        for _path, value, _artifact in outbound_session_entries
    ]
    result["outbound_session_supersession_artifacts"] = [
        artifact.model_dump(mode="json")
        for _path, _value, artifact in outbound_session_entries
    ]
    result["incoming_session_supersessions"] = [
        value.model_dump(mode="json")
        for _path, value, _artifact in incoming_session_entries
    ]
    result["incoming_session_supersession_artifacts"] = [
        artifact.model_dump(mode="json")
        for _path, _value, artifact in incoming_session_entries
    ]
    result["session_supersession_ambiguities"] = session_ambiguities
    if (
        retry_entries or outbound_session_entries
    ) and result.get("combined_status") != "inconsistent":
        result["combined_status"] = "blocked"
    return result


def run_material_preflight(
    job_id: str,
    *,
    request_path: str,
    preview_size: int = 512,
) -> dict[str, Any]:
    """Run the canonical-write-free preflight service from one strict request."""

    root = _job_root(job_id)
    request = _load_model(root, request_path, MaterialPromotionPreflightRequest)
    if request.job_id != job_id:
        raise ValueError("material preflight request targets another job")
    result = MaterialClosureService(root).run_preflight(
        request,
        preview_size=preview_size,
    )
    return _preflight_result_payload(result)


def _preflight_result_payload(result: Any) -> dict[str, Any]:
    """Project one complete preflight result without weakening its typed evidence."""

    return {
        "status": result.status,
        "execution_scope": result.execution_scope,
        "approval_plan_eligible": result.approval_plan_eligible,
        "report": None if result.report is None else result.report.model_dump(mode="json"),
        "report_artifact": (
            None
            if result.report_artifact is None
            else result.report_artifact.model_dump(mode="json")
        ),
        "failure": (
            None if result.failure is None else result.failure.model_dump(mode="json")
        ),
        "failure_artifact": (
            None
            if result.failure_artifact is None
            else result.failure_artifact.model_dump(mode="json")
        ),
        "framework_failure_report": (
            None
            if result.framework_failure_report is None
            else result.framework_failure_report.model_dump(mode="json")
        ),
        "neutral_preview": (
            None
            if result.neutral_preview is None
            else result.neutral_preview.model_dump(mode="json")
        ),
    }


def run_material_shadow_compile(
    job_id: str,
    *,
    request_path: str,
    preview_size: int = 512,
) -> dict[str, Any]:
    """Run the named shadow command through the mandatory complete-preflight facade."""

    root = _job_root(job_id)
    request = _load_model(root, request_path, MaterialPromotionPreflightRequest)
    if request.job_id != job_id:
        raise ValueError("material shadow preflight request targets another job")
    return _preflight_result_payload(
        material_shadow_compile(root, request, preview_size=preview_size)
    )


def approve_material_appearance(
    job_id: str,
    *,
    report_path: str,
    approval_path: str,
    expected_uv_layout_fingerprint: str,
    explicit_user_decision_observed: bool,
) -> dict[str, Any]:
    """Publish one complete caller-authored approval after current preflight replay."""

    root = _job_root(job_id)
    approval = _load_model(root, approval_path, MaterialAppearanceApproval)
    if approval.job_id != job_id:
        raise ValueError("material appearance approval targets another job")
    if approval.uv_layout_fingerprint != expected_uv_layout_fingerprint:
        raise PermissionError("expected UV fingerprint differs from caller-authored approval")
    report_payload = json.loads(
        Path(native_io_path(_contained_file(root, report_path))).read_text(encoding="utf-8")
    )
    if not isinstance(report_payload, dict) or not isinstance(
        report_payload.get("report_id"),
        str,
    ):
        raise ValueError("material preflight report lacks its strict report_id")
    report_artifact = _exact_artifact(
        root,
        report_path,
        artifact_id=report_payload["report_id"],
        kind="material_preflight_report",
    )
    publication = publish_material_appearance_approval(
        root,
        report_artifact=report_artifact,
        approval=approval,
        explicit_user_decision_observed=explicit_user_decision_observed,
    )
    return {
        "approval": publication.approval.model_dump(mode="json"),
        "approval_artifact": publication.approval_artifact.model_dump(mode="json"),
        "preflight_report": publication.preflight_report.model_dump(mode="json"),
    }


def get_material_preflight_status(
    job_id: str,
    *,
    report_path: str,
    require_current: bool = False,
) -> dict[str, Any]:
    """Replay a published preflight historically or against current canonical bytes."""

    root = _job_root(job_id)
    payload = json.loads(
        Path(native_io_path(_contained_file(root, report_path))).read_text(
            encoding="utf-8"
        )
    )
    report_id = str(payload.get("report_id", Path(report_path).stem))
    artifact = _exact_artifact(
        root,
        report_path,
        artifact_id=report_id,
        kind="material_preflight_report",
    )
    service = MaterialClosureService(root)
    report = (
        service.validate_preflight_for_approval(artifact)
        if require_current
        else service.validate_published_preflight(artifact)
    )
    return {
        "status": report.status,
        "approval_plan_eligible": True,
        "current_canonical_required": require_current,
        "report": report.model_dump(mode="json"),
        "report_artifact": artifact.model_dump(mode="json"),
    }


def rebind_material_graph(
    job_id: str,
    *,
    source_graph_path: str,
    plan_path: str,
) -> dict[str, Any]:
    """Publish one path/hash-only graph derivative and exact passed receipt."""

    root = _job_root(job_id)
    source = json.loads(
        Path(native_io_path(_contained_file(root, source_graph_path))).read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(source, dict):
        raise ValueError("source MaterialGraph JSON must contain one object")
    plan = _load_model(root, plan_path, MaterialGraphRebindingPlan)
    if plan.job_id != job_id:
        raise ValueError("material graph rebinding plan targets another job")
    if source_graph_path != plan.source_graph.path:
        raise ValueError("source graph path differs from the exact rebinding plan")
    for artifact in (
        plan.source_binding,
        plan.source_graph,
        plan.candidate_material_plan,
    ):
        current = _exact_artifact(
            root,
            artifact.path,
            artifact_id=artifact.artifact_id,
            kind=artifact.kind,
        )
        if (current.sha256, current.byte_size) != (artifact.sha256, artifact.byte_size):
            raise ValueError(f"material graph rebinding input changed: {artifact.path}")
    expected_plan_path = (
        f"production/material_closure/{plan.session_id}/graph_rebindings/"
        f"{plan.plan_id}/plan.json"
    )
    if plan_path != expected_plan_path:
        raise ValueError("material graph rebinding plan is not at its canonical leaf")
    plan_artifact = _exact_artifact(
        root,
        plan_path,
        artifact_id=plan.plan_id,
        kind="material_graph_rebinding_plan",
    )
    rebound, changes = apply_material_graph_rebinding(source, plan)
    rebound_artifact = _publish_bytes_exact(
        root,
        plan.output_path,
        serialize_rebound_material_graph(rebound),
        artifact_id=f"rebound-{plan.plan_id}",
        kind="material_graph",
        media_type="application/json",
    )
    receipt_relative = (
        f"production/material_closure/{plan.session_id}/graph_rebindings/"
        f"{plan.plan_id}/receipt.json"
    )
    receipt_path = root.joinpath(*receipt_relative.split("/"))
    created_at = (
        MaterialGraphRebindingReceipt.model_validate_json(
            Path(native_io_path(receipt_path)).read_bytes()
        ).created_at
        if os.path.isfile(native_io_path(receipt_path))
        else datetime.now(UTC)
    )
    receipt = MaterialGraphRebindingReceipt(
        receipt_id=f"receipt-{plan.plan_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        producer=_PRODUCER,
        producer_version=MATERIAL_CLOSURE_SCHEMA_VERSION,
        created_at=created_at,
        plan=plan_artifact,
        source_binding=plan.source_binding,
        status="passed",
        source_graph=plan.source_graph,
        rebound_graph=rebound_artifact,
        applied_changes=changes,
        semantic_content_unchanged=True,
    )
    receipt, receipt_artifact = publish_material_closure_model(
        root,
        receipt_relative,
        receipt,
        artifact_id=receipt.receipt_id,
        kind="material_graph_rebinding_receipt",
    )
    return {
        "status": "passed",
        "rebound_graph_artifact": rebound_artifact.model_dump(mode="json"),
        "receipt": receipt.model_dump(mode="json"),
        "receipt_artifact": receipt_artifact.model_dump(mode="json"),
    }


def get_material_state_consistency(
    job_id: str,
    *,
    attempt_state_path: str,
    top_level_state_path: str,
    expected_snapshot_path: str,
    report_id: str | None = None,
) -> dict[str, Any]:
    """Host-observe canonical bytes, then publish their comparison with one attempt."""

    root = _job_root(job_id)
    attempt = _load_model(root, attempt_state_path, MaterialAttemptState)
    expected = _load_model(root, expected_snapshot_path, MaterialCanonicalSnapshot)
    if attempt.job_id != job_id or expected.job_id != job_id:
        raise ValueError("material state consistency inputs target another job")
    if attempt.canonical_snapshot != expected:
        raise ValueError("expected snapshot differs from the attempt-bound snapshot")
    resolved_report_id = report_id or f"material-consistency-{uuid4().hex[:12]}"
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", resolved_report_id) is None:
        raise ValueError("material consistency report id must be portable lowercase")
    consistency_root = (
        f"production/material_closure/{attempt.session_id}/consistency/"
        f"{resolved_report_id}"
    )
    observed_relative = f"{consistency_root}/observed_snapshot.json"
    observed_path = root.joinpath(*observed_relative.split("/"))
    observed_created_at = (
        MaterialCanonicalSnapshot.model_validate_json(
            Path(native_io_path(observed_path)).read_bytes()
        ).created_at
        if os.path.isfile(native_io_path(observed_path))
        else datetime.now(UTC)
    )

    def current_from_expected(artifact: ExactArtifact) -> ExactArtifact:
        """Rebind an expected artifact identity to current bytes at the same host path."""

        return _exact_artifact(
            root,
            artifact.path,
            artifact_id=artifact.artifact_id,
            kind=artifact.kind,
        )

    def latest_phase_artifact(filename: str, kind: str) -> ExactArtifact | None:
        """Select the highest numeric AQ material-phase receipt below this session."""

        phase_root = root / "production" / "autonomy_v2" / attempt.session_id / "material_phase"
        if not phase_root.is_dir():
            return None
        candidates = [
            item
            for item in phase_root.glob(f"*/{filename}")
            if item.parent.name.isdecimal()
            and os.path.isfile(native_io_path(item))
            and not item.is_symlink()
        ]
        if not candidates:
            return None
        selected = max(candidates, key=lambda item: int(item.parent.name))
        relative = selected.relative_to(root).as_posix()
        return _exact_artifact(
            root,
            relative,
            artifact_id=selected.stem,
            kind=kind,
        )

    current_scene = current_from_expected(expected.scene_spec)
    current_modeling = current_from_expected(expected.modeling_plan)
    current_blend = current_from_expected(expected.blend)
    top_level_artifact = _exact_artifact(
        root,
        top_level_state_path,
        artifact_id=Path(top_level_state_path).stem,
        kind="autonomy_v02_state",
    )
    material_path = root / "analysis" / "material_plan.json"
    if material_path.is_symlink():
        raise ValueError("canonical MaterialPlan cannot be a symbolic link")
    if os.path.isfile(native_io_path(material_path)):
        current_material = _exact_artifact(
            root,
            "analysis/material_plan.json",
            artifact_id=(
                expected.material_plan.artifact_id
                if expected.material_plan is not None
                else "canonical-material-plan"
            ),
            kind="material_plan",
        )
        current_absence = None
    else:
        current_material = None
        absence_id = (
            "absence-"
            + hashlib.sha256(resolved_report_id.encode("utf-8")).hexdigest()[:24]
        )
        absence = build_material_plan_absence_evidence(
            job_root=root,
            absence_id=absence_id,
            job_id=attempt.job_id,
            workflow_id=attempt.workflow_id,
            dispatch_id=attempt.dispatch_id,
            session_id=attempt.session_id,
            producer=_PRODUCER,
            producer_version=MATERIAL_CLOSURE_SCHEMA_VERSION,
            created_at=observed_created_at,
            observation_state=top_level_artifact,
            canonical_scene_spec=current_scene,
            canonical_blend=current_blend,
        )
        _absence, current_absence = publish_material_closure_model(
            root,
            f"{consistency_root}/material_plan_absence.json",
            absence,
            artifact_id=absence.absence_id,
            kind="material_plan_absence",
        )
    observations = publish_current_material_canonical_observations(
        job_root=root,
        identity=attempt,
        observation_id=resolved_report_id,
    )
    observed = build_material_canonical_snapshot(
        job_root=root,
        snapshot_id=f"observed-{resolved_report_id}",
        job_id=attempt.job_id,
        workflow_id=attempt.workflow_id,
        dispatch_id=attempt.dispatch_id,
        session_id=attempt.session_id,
        producer=_PRODUCER,
        producer_version=MATERIAL_CLOSURE_SCHEMA_VERSION,
        created_at=observed_created_at,
        scene_spec=current_scene,
        modeling_plan=current_modeling,
        blend=current_blend,
        build_provenance=observations.build_provenance,
        material_plan=current_material,
        material_plan_absence=current_absence,
        latest_material_promotion_receipt=latest_phase_artifact(
            "promotion_receipt.json",
            "material_phase_receipt",
        ),
        latest_rollback_receipt=latest_phase_artifact(
            "rollback_receipt.json",
            "material_phase_rollback_receipt",
        ),
        active_candidate_closure=(
            None
            if attempt.active_closure is None
            else current_from_expected(attempt.active_closure)
        ),
    )
    observed, observed_artifact = publish_material_closure_model(
        root,
        observed_relative,
        observed,
        artifact_id=observed.snapshot_id,
        kind="material_canonical_snapshot",
    )
    report = compare_material_state_to_canonical(
        report_id=resolved_report_id,
        attempt=attempt,
        attempt_artifact=_exact_artifact(
            root,
            attempt_state_path,
            artifact_id=attempt.attempt_id,
            kind="material_attempt_state",
        ),
        top_level_state=top_level_artifact,
        expected_snapshot_artifact=_exact_artifact(
            root,
            expected_snapshot_path,
            artifact_id=expected.snapshot_id,
            kind="material_canonical_snapshot",
        ),
        observed_snapshot=observed,
        producer=_PRODUCER,
        producer_version=MATERIAL_CLOSURE_SCHEMA_VERSION,
        created_at=observed_created_at,
    )
    report, report_artifact = publish_material_closure_model(
        root,
        f"{consistency_root}/report.json",
        report,
        artifact_id=report.report_id,
        kind="material_state_consistency_report",
    )
    return {
        "report": report.model_dump(mode="json"),
        "report_artifact": report_artifact.model_dump(mode="json"),
        "observed_snapshot": observed.model_dump(mode="json"),
        "observed_snapshot_artifact": observed_artifact.model_dump(mode="json"),
    }


def get_material_framework_failure_status(
    job_id: str,
    *,
    report_path: str,
) -> dict[str, Any]:
    """Read and validate one immutable framework-failure report without retrying it."""

    root = _job_root(job_id)
    report = _load_model(root, report_path, MaterialFrameworkFailureReport)
    if report.job_id != job_id:
        raise ValueError("material framework failure report targets another job")
    return report.model_dump(mode="json")


def supersede_material_retry(
    job_id: str,
    *,
    retry_plan_path: str,
    current_state_path: str,
    framework_failure_report_path: str,
    supersession_reason: str,
    observation_context_sha256: str,
    retry_approval_path: str | None = None,
    expected_approval_path: str | None = None,
    receipt_id: str | None = None,
) -> dict[str, Any]:
    """Publish append-only retry supersession evidence without executing the retry."""

    root = _job_root(job_id)
    report = _load_model(
        root,
        framework_failure_report_path,
        MaterialFrameworkFailureReport,
    )
    if report.job_id != job_id:
        raise ValueError("retry supersession failure report targets another job")
    approval = (
        None
        if retry_approval_path is None
        else _exact_artifact(
            root,
            retry_approval_path,
            artifact_id=Path(retry_approval_path).stem,
            kind="material_retry_approval",
        )
    )
    receipt, receipt_artifact = publish_material_retry_supersession(
        job_root=root,
        identity=report,
        receipt_id=receipt_id or f"retry-supersession-{uuid4().hex[:12]}",
        retry_plan=_exact_artifact(
            root,
            retry_plan_path,
            artifact_id=Path(retry_plan_path).stem,
            kind="material_retry_plan",
        ),
        retry_approval=approval,
        expected_approval_path=expected_approval_path,
        current_state=_exact_artifact(
            root,
            current_state_path,
            artifact_id=Path(current_state_path).stem,
            kind="autonomy_v02_state",
        ),
        framework_failure_report=_exact_artifact(
            root,
            framework_failure_report_path,
            artifact_id=report.report_id,
            kind="material_framework_failure_report",
        ),
        supersession_reason=supersession_reason,
        observation_context_sha256=observation_context_sha256,
        created_at=datetime.now(UTC),
    )
    return {
        "receipt": receipt.model_dump(mode="json"),
        "receipt_artifact": receipt_artifact.model_dump(mode="json"),
    }


def plan_material_repair_session(
    job_id: str,
    *,
    plan_path: str,
    source_binding_path: str,
) -> dict[str, Any]:
    """Validate and publish a pre-authored material-only repair session plan."""

    root = _job_root(job_id)
    plan = _load_model(root, plan_path, MaterialRepairSessionPlan)
    source = _load_model(root, source_binding_path, MaterialRepairSourceBinding)
    if plan.job_id != job_id or source.job_id != job_id:
        raise ValueError("material repair inputs target another job")
    source_artifact = _exact_artifact(
        root,
        source_binding_path,
        artifact_id=source.binding_id,
        kind="material_repair_source_binding",
    )
    if (
        plan.source_binding.path != source_artifact.path
        or plan.source_binding.sha256 != source_artifact.sha256
        or plan.source_binding_sha256 != source_artifact.sha256
    ):
        raise ValueError("material repair plan source binding is stale")
    verify_material_repair_geometry(
        source,
        scene_spec_sha256=sha256_file(_contained_file(root, source.scene_spec.path)),
        modeling_plan_sha256=sha256_file(
            _contained_file(root, source.modeling_plan.path)
        ),
        blend_sha256=sha256_file(_contained_file(root, source.blend.path)),
    )
    validate_material_repair_session(plan, source)
    published_plan, plan_artifact = publish_material_repair_session_plan(
        job_root=root,
        source_binding=source,
        plan=plan,
    )
    return {
        "status": "published",
        "plan": published_plan.model_dump(mode="json"),
        "plan_artifact": plan_artifact.model_dump(mode="json"),
        "source_binding": source_artifact.model_dump(mode="json"),
    }


def run_material_repair_session(
    job_id: str,
    *,
    plan_path: str,
    source_binding_path: str,
    preview_size: int = 512,
) -> dict[str, Any]:
    """Run one repair through complete preflight and stop at approval pending or failure."""

    root = _job_root(job_id)
    plan = _load_model(root, plan_path, MaterialRepairSessionPlan)
    source = _load_model(root, source_binding_path, MaterialRepairSourceBinding)
    if plan.job_id != job_id or source.job_id != job_id:
        raise ValueError("material repair run inputs target another job")
    result = execute_material_repair_session(
        job_root=root,
        plan_artifact=_exact_artifact(
            root,
            plan_path,
            artifact_id=plan.plan_id,
            kind="material_repair_session_plan",
        ),
        source_binding_artifact=_exact_artifact(
            root,
            source_binding_path,
            artifact_id=source.binding_id,
            kind="material_repair_source_binding",
        ),
        preview_size=preview_size,
    )
    return {
        "plan": result.plan.model_dump(mode="json"),
        "source_binding": result.source_binding.model_dump(mode="json"),
        "preflight": _preflight_result_payload(result.preflight),
        "attempt_state": result.attempt_state.model_dump(mode="json"),
        "attempt_state_artifact": result.attempt_state_artifact.model_dump(mode="json"),
    }


__all__ = [
    "get_material_closure_status",
    "get_material_framework_failure_status",
    "get_material_preflight_status",
    "get_material_state_consistency",
    "plan_material_closure",
    "plan_material_repair_session",
    "rebind_material_graph",
    "run_material_preflight",
    "run_material_repair_session",
    "run_material_shadow_compile",
    "approve_material_appearance",
    "supersede_material_retry",
]
