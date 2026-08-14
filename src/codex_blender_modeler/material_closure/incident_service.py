"""Append-only publication helpers for material framework incidents and recovery plans."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from ..autonomy.io import ensure_autonomy_path
from ..autonomy_v2.delivery_service import artifact_for_v2
from ..blender_artifacts import (
    deterministic_json_bytes,
    native_io_path,
    publish_bytes_create_once,
    sha256_file,
    write_json_atomic,
)
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from .failure_reporting import build_material_retry_supersession_receipt
from .models import (
    ExactArtifact,
    JobSpecificRecoverySource,
    JobSpecificRecoverySourceInventory,
    MaterialAttemptState,
    MaterialCanonicalSnapshot,
    MaterialClosureBoundContract,
    MaterialPromotionPreflightRequest,
    MaterialRepairSessionPlan,
    MaterialRepairSourceBinding,
    MaterialRetryApprovalAbsence,
    MaterialRetrySupersessionReceipt,
    MaterialRollbackRestorationObservation,
    MaterialSessionSupersessionReceipt,
)
from .repair_session import (
    validate_material_repair_preapproval_outcome,
    validate_material_repair_session,
    verify_material_repair_geometry,
)
from .service import MaterialClosureService, MaterialPromotionPreflightResult

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class RecoverySourceArchiveSpec:
    """Describe one repository source whose current bytes must be preserved before removal."""

    source_path: str
    job_specific_literals: tuple[str, ...]
    generic_capabilities: tuple[str, ...]
    disposition: str = "archive_then_delete"


@dataclass(frozen=True)
class MaterialRepairSessionRunResult:
    """Return one bounded repair preflight and its append-only attempt state."""

    plan: MaterialRepairSessionPlan
    source_binding: MaterialRepairSourceBinding
    preflight: MaterialPromotionPreflightResult
    attempt_state: MaterialAttemptState
    attempt_state_artifact: ExactArtifact


@dataclass(frozen=True)
class MaterialCanonicalObservationPublication:
    """Return fresh run-owned inventory and build-provenance observations."""

    scene_inventory: ExactArtifact
    build_provenance: ExactArtifact


def _to_exact_artifact(
    job_root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str = "application/json",
) -> ExactArtifact:
    """Rehash one contained file into the Material Closure artifact vocabulary."""

    artifact = artifact_for_v2(
        job_root,
        path,
        artifact_id=artifact_id,
        kind=kind,
    )
    return ExactArtifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind.replace("-", "_"),
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
        media_type=media_type,
    )


def publish_material_closure_model(
    job_root: Path,
    relative_path: str,
    model: ModelT,
    *,
    artifact_id: str,
    kind: str,
) -> tuple[ModelT, ExactArtifact]:
    """Publish or exact-adopt one strict companion model without replacing history."""

    root = job_root.expanduser().resolve(strict=True)
    path = ensure_autonomy_path(
        root,
        root.joinpath(*relative_path.split("/")),
        must_exist=False,
    )
    expected_bytes = deterministic_json_bytes(model.model_dump(mode="json"))
    try:
        publish_bytes_create_once(path, expected_bytes)
    except FileExistsError as exc:
        raise FileExistsError(
            f"conflicting immutable material evidence: {relative_path}"
        ) from exc
    observed = type(model).model_validate_json(Path(native_io_path(path)).read_bytes())
    return observed, _to_exact_artifact(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
    )


def load_material_closure_model(
    job_root: Path,
    artifact: ExactArtifact,
    model_type: type[ModelT],
) -> ModelT:
    """Rehash and strict-parse one companion artifact without mutating it."""

    root = job_root.expanduser().resolve(strict=True)
    path = ensure_autonomy_path(
        root,
        root.joinpath(*artifact.path.split("/")),
        must_exist=True,
    )
    if (
        sha256_file(path) != artifact.sha256
        or path.stat().st_size != artifact.byte_size
    ):
        raise ValueError(f"material companion artifact changed: {artifact.path}")
    return model_type.model_validate_json(Path(native_io_path(path)).read_bytes())


def _publish_immutable_json_object(
    job_root: Path,
    relative_path: str,
    payload: dict[str, object],
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Publish or exact-adopt one non-model JSON observation without replacing it."""

    root = job_root.expanduser().resolve(strict=True)
    destination = ensure_autonomy_path(
        root,
        root.joinpath(*relative_path.split("/")),
        must_exist=False,
    )
    try:
        publish_bytes_create_once(destination, deterministic_json_bytes(payload))
    except FileExistsError as exc:
        raise FileExistsError(
            f"conflicting immutable JSON observation: {relative_path}"
        ) from exc
    return _to_exact_artifact(
        root,
        destination,
        artifact_id=artifact_id,
        kind=kind,
    )


def publish_current_material_canonical_observations(
    *,
    job_root: Path,
    identity: MaterialClosureBoundContract,
    observation_id: str | None = None,
) -> MaterialCanonicalObservationPublication:
    """Inspect current canonical bytes into one versioned immutable observation leaf."""

    root = job_root.expanduser().resolve(strict=True)
    scene_spec = ensure_autonomy_path(
        root,
        root / "analysis" / "scene_spec.json",
        must_exist=True,
    )
    modeling_plan = ensure_autonomy_path(
        root,
        root / "analysis" / "modeling_plan.json",
        must_exist=True,
    )
    blend = ensure_autonomy_path(
        root,
        root / "blender" / "scene.blend",
        must_exist=True,
    )
    material_plan = root / "analysis" / "material_plan.json"

    def canonical_input_fingerprint() -> tuple[str, ...]:
        """Fingerprint geometry plus current MaterialPlan presence for mutation detection."""

        material_state = (
            sha256_file(material_plan)
            if os.path.isfile(native_io_path(material_plan))
            else "absent"
        )
        return (
            *(sha256_file(path) for path in (scene_spec, modeling_plan, blend)),
            material_state,
        )

    before = canonical_input_fingerprint()
    resolved_observation_id = observation_id or hashlib.sha256(
        "\0".join(before).encode("ascii")
    ).hexdigest()[:24]
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", resolved_observation_id) is None:
        raise ValueError("canonical observation id must be a portable lowercase identifier")
    observation_root = (
        root / "production" / "material_closure" / str(identity.session_id)
        / "canonical_observations" / resolved_observation_id
    )
    inventory_relative = (
        f"production/material_closure/{identity.session_id}/canonical_observations/"
        f"{resolved_observation_id}/scene_inventory.json"
    )
    build_relative = (
        f"production/material_closure/{identity.session_id}/canonical_observations/"
        f"{resolved_observation_id}/build_provenance.json"
    )
    inventory_path = ensure_autonomy_path(
        root,
        root.joinpath(*inventory_relative.split("/")),
        must_exist=False,
    )
    if os.path.exists(native_io_path(inventory_path)):
        try:
            inventory_payload = json.loads(
                Path(native_io_path(inventory_path)).read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ValueError("canonical scene observation is invalid JSON") from exc
    else:
        os.makedirs(native_io_path(observation_root), exist_ok=True)
        ensure_autonomy_path(root, observation_root, must_exist=True)
        temporary = observation_root / f".inv.{os.getpid()}.{uuid4().hex[:16]}.tmp"
        if os.path.exists(native_io_path(temporary)):
            raise FileExistsError("canonical inventory temporary output already exists")
        try:
            run_blender(
                "inspect_scene.py",
                ["--output", str(temporary)],
                blend_file=blend,
                disable_autoexec=True,
            )
            inventory_payload = json.loads(
                Path(native_io_path(temporary)).read_text(encoding="utf-8")
            )
        finally:
            if os.path.exists(native_io_path(temporary)):
                os.unlink(native_io_path(temporary))
    if (
        not isinstance(inventory_payload, dict)
        or inventory_payload.get("job_id") != str(identity.job_id)
        or inventory_payload.get("blender_version") != "5.0.1"
        or not isinstance(inventory_payload.get("objects"), list)
    ):
        raise ValueError("canonical scene observation has invalid identity or shape")
    validation_inventory: Path | None = None
    provenance_inventory = inventory_path
    if not os.path.exists(native_io_path(inventory_path)):
        validation_inventory = (
            observation_root / f".scene_inventory.{os.getpid()}.validated.json"
        )
        write_json_atomic(validation_inventory, inventory_payload)
        provenance_inventory = validation_inventory
    try:
        build_payload = collect_build_provenance(
            root,
            str(identity.job_id),
            scene_spec_path=scene_spec,
            surface_detail_inventory_path=provenance_inventory,
        )
    finally:
        if validation_inventory is not None and os.path.exists(
            native_io_path(validation_inventory)
        ):
            os.unlink(native_io_path(validation_inventory))
    after = canonical_input_fingerprint()
    if after != before:
        raise PermissionError("canonical geometry changed during read-only observation")
    inventory_artifact = _publish_immutable_json_object(
        root,
        inventory_relative,
        inventory_payload,
        artifact_id=(
            "canonical-scene-inventory-"
            + hashlib.sha256(
                f"{identity.session_id}\0{resolved_observation_id}".encode()
            ).hexdigest()[:24]
        ),
        kind="scene_inventory",
    )
    build_artifact = _publish_immutable_json_object(
        root,
        build_relative,
        build_payload,
        artifact_id=(
            "canonical-build-provenance-"
            + hashlib.sha256(
                f"{identity.session_id}\0{resolved_observation_id}".encode()
            ).hexdigest()[:24]
        ),
        kind="build_provenance",
    )
    return MaterialCanonicalObservationPublication(
        scene_inventory=inventory_artifact,
        build_provenance=build_artifact,
    )


def _git_index_bytes(repo_root: Path, relative_path: str) -> bytes | None:
    """Read one staged/index blob without changing the repository or working tree."""

    process = subprocess.run(
        ["git", "show", f":{relative_path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if process.returncode == 0:
        return process.stdout
    return None


def _copy_archive_exact(source: Path, destination: Path, expected_sha256: str) -> None:
    """Copy one source file exactly once and verify the archived working bytes."""

    content = Path(native_io_path(source)).read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("source archive bytes differ from the working source")
    try:
        publish_bytes_create_once(destination, content)
    except FileExistsError as exc:
        raise FileExistsError(f"conflicting source archive: {destination.name}") from exc


def archive_job_specific_recovery_sources(
    *,
    repo_root: Path,
    job_root: Path,
    identity: MaterialClosureBoundContract,
    inventory_id: str,
    sources: list[RecoverySourceArchiveSpec],
    created_at: datetime | None = None,
) -> tuple[JobSpecificRecoverySourceInventory, ExactArtifact]:
    """Archive exact working bytes and publish their tracked/index provenance once."""

    repository = repo_root.expanduser().resolve(strict=True)
    root = job_root.expanduser().resolve(strict=True)
    archive_root = ensure_autonomy_path(
        root,
        root / "history" / "framework_failure_source" / inventory_id,
        must_exist=False,
    )
    records: list[JobSpecificRecoverySource] = []
    for spec in sorted(sources, key=lambda item: item.source_path):
        source = repository.joinpath(*spec.source_path.split("/"))
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(f"recovery source is not a regular file: {spec.source_path}")
        working_sha256 = sha256_file(source)
        working_size = source.stat().st_size
        index_bytes = _git_index_bytes(repository, spec.source_path)
        tracking_status = "tracked" if index_bytes is not None else "untracked"
        index_sha256 = (
            None if index_bytes is None else hashlib.sha256(index_bytes).hexdigest()
        )
        index_size = None if index_bytes is None else len(index_bytes)
        archive_name = f"{working_sha256[:16]}-{source.name}"
        archive_path = ensure_autonomy_path(
            root,
            archive_root / archive_name,
            must_exist=False,
        )
        _copy_archive_exact(source, archive_path, working_sha256)
        records.append(
            JobSpecificRecoverySource(
                path=spec.source_path,
                tracking_status=tracking_status,
                sha256=working_sha256,
                byte_size=working_size,
                index_sha256=index_sha256,
                index_byte_size=index_size,
                working_tree_differs_from_index=(
                    None
                    if index_bytes is None
                    else working_sha256 != index_sha256 or working_size != index_size
                ),
                job_specific_literals=list(spec.job_specific_literals),
                generic_capabilities=list(spec.generic_capabilities),
                disposition=spec.disposition,
                archive_path=archive_path.relative_to(root).as_posix(),
                archive_sha256=sha256_file(archive_path),
                archive_byte_size=archive_path.stat().st_size,
            )
        )
    inventory = JobSpecificRecoverySourceInventory(
        inventory_id=inventory_id,
        job_id=identity.job_id,
        workflow_id=identity.workflow_id,
        dispatch_id=identity.dispatch_id,
        session_id=identity.session_id,
        producer="codex_blender_modeler.material_closure.incident_service",
        producer_version="0.1.0",
        created_at=created_at or datetime.now(UTC),
        sources=records,
        scan_roots=["src/codex_blender_modeler"],
        scan_complete=True,
    )
    return publish_material_closure_model(
        root,
        f"history/framework_failure_source/{inventory_id}/inventory.json",
        inventory,
        artifact_id=inventory_id,
        kind="job_specific_recovery_source_inventory",
    )


def supersede_material_retry(
    *,
    job_root: Path,
    retry_plan: ExactArtifact,
    retry_approval: ExactArtifact | None,
    expected_approval_path: str | None,
    current_state: ExactArtifact,
    framework_failure_report: ExactArtifact,
    identity: MaterialClosureBoundContract,
    receipt_id: str,
    supersession_reason: str,
    observation_context_sha256: str,
    created_at: datetime | None = None,
) -> tuple[MaterialRetrySupersessionReceipt, ExactArtifact]:
    """Supersede one exact approved or approval-absent retry without executing it."""

    root = job_root.expanduser().resolve(strict=True)
    now = created_at or datetime.now(UTC)
    for artifact in (retry_plan, current_state, framework_failure_report):
        load_path = ensure_autonomy_path(
            root,
            root.joinpath(*artifact.path.split("/")),
            must_exist=True,
        )
        if sha256_file(load_path) != artifact.sha256:
            raise ValueError(f"retry supersession input changed: {artifact.path}")
    approval_absence_artifact: ExactArtifact | None = None
    if retry_approval is None:
        if expected_approval_path is None:
            raise ValueError("approval-absent retry requires its expected approval path")
        expected = ensure_autonomy_path(
            root,
            root.joinpath(*expected_approval_path.split("/")),
            must_exist=False,
        )
        if expected.exists():
            raise FileExistsError("retry approval exists and must be preserved explicitly")
        absence = MaterialRetryApprovalAbsence(
            absence_id=f"{receipt_id}-approval-absence",
            job_id=identity.job_id,
            workflow_id=identity.workflow_id,
            dispatch_id=identity.dispatch_id,
            session_id=identity.session_id,
            producer="codex_blender_modeler.material_closure.incident_service",
            producer_version="0.1.0",
            created_at=now,
            retry_plan=retry_plan,
            expected_approval_path=expected_approval_path,
            observation_state=current_state,
            observation_context_sha256=observation_context_sha256,
        )
        _, approval_absence_artifact = publish_material_closure_model(
            root,
            (
                f"production/autonomy_v2/{identity.session_id}/retry_supersessions/"
                f"{receipt_id}/approval_absence.json"
            ),
            absence,
            artifact_id=absence.absence_id,
            kind="material_retry_approval_absence",
        )
    else:
        approval_path = ensure_autonomy_path(
            root,
            root.joinpath(*retry_approval.path.split("/")),
            must_exist=True,
        )
        if sha256_file(approval_path) != retry_approval.sha256:
            raise ValueError("retry approval bytes changed before supersession")
    receipt = build_material_retry_supersession_receipt(
        receipt_id=receipt_id,
        retry_plan=retry_plan,
        retry_approval=retry_approval,
        retry_approval_absence=approval_absence_artifact,
        current_state=current_state,
        framework_failure_report=framework_failure_report,
        supersession_reason=supersession_reason,
        job_id=identity.job_id,
        workflow_id=identity.workflow_id,
        dispatch_id=identity.dispatch_id,
        session_id=identity.session_id,
        producer="codex_blender_modeler.material_closure.incident_service",
        producer_version="0.1.0",
        created_at=now,
    )
    return publish_material_closure_model(
        root,
        (
            f"production/autonomy_v2/{identity.session_id}/retry_supersessions/"
            f"{receipt_id}/receipt.json"
        ),
        receipt,
        artifact_id=receipt_id,
        kind="material_retry_supersession_receipt",
    )


def publish_material_repair_session_plan(
    *,
    job_root: Path,
    source_binding: MaterialRepairSourceBinding,
    plan: MaterialRepairSessionPlan,
) -> tuple[MaterialRepairSessionPlan, ExactArtifact]:
    """Validate and publish a distinct material-only session plan without running it."""

    validate_material_repair_session(plan, source_binding)
    return publish_material_closure_model(
        job_root,
        f"production/material_repair/{plan.session_id}/plan.json",
        plan,
        artifact_id=plan.plan_id,
        kind="material_repair_session_plan",
    )


def publish_material_rollback_restoration_observation(
    *,
    job_root: Path,
    observation: MaterialRollbackRestorationObservation,
) -> tuple[MaterialRollbackRestorationObservation, ExactArtifact]:
    """Publish one exact rollback-to-current geometry proof in the new repair session."""

    for artifact in (
        observation.source_rollback_receipt,
        observation.geometry_validation_receipt,
        observation.restored_scene_spec_archive,
        observation.restored_modeling_plan_archive,
        observation.restored_blend_archive,
        observation.current_scene_spec,
        observation.current_modeling_plan,
        observation.current_blend,
    ):
        path = ensure_autonomy_path(
            job_root,
            job_root.joinpath(*artifact.path.split("/")),
            must_exist=True,
        )
        if sha256_file(path) != artifact.sha256 or path.stat().st_size != artifact.byte_size:
            raise ValueError(f"rollback restoration input changed: {artifact.path}")
    return publish_material_closure_model(
        job_root,
        (
            f"production/material_repair/{observation.session_id}/"
            "rollback_restoration_observation.json"
        ),
        observation,
        artifact_id=observation.observation_id,
        kind="material_rollback_restoration_observation",
    )


def publish_material_session_supersession(
    *,
    job_root: Path,
    receipt: MaterialSessionSupersessionReceipt,
) -> tuple[MaterialSessionSupersessionReceipt, ExactArtifact]:
    """Publish the append-only old-session to new-repair-session relationship."""

    return publish_material_closure_model(
        job_root,
        (
            f"production/autonomy_v2/{receipt.superseded_session_id}/"
            f"material_session_supersessions/{receipt.receipt_id}.json"
        ),
        receipt,
        artifact_id=receipt.receipt_id,
        kind="material_session_supersession_receipt",
    )


def run_material_repair_session(
    *,
    job_root: Path,
    plan_artifact: ExactArtifact,
    source_binding_artifact: ExactArtifact,
    preview_size: int = 512,
    created_at: datetime | None = None,
) -> MaterialRepairSessionRunResult:
    """Run a material-only session through preflight and stop before user approval."""

    root = job_root.expanduser().resolve(strict=True)
    plan = load_material_closure_model(
        root,
        plan_artifact,
        MaterialRepairSessionPlan,
    )
    source = load_material_closure_model(
        root,
        source_binding_artifact,
        MaterialRepairSourceBinding,
    )
    if plan.source_binding != source_binding_artifact:
        raise ValueError("material repair plan binds another source artifact")
    validate_material_repair_session(plan, source)
    verify_material_repair_geometry(
        source,
        scene_spec_sha256=sha256_file(
            ensure_autonomy_path(
                root,
                root.joinpath(*source.scene_spec.path.split("/")),
                must_exist=True,
            )
        ),
        modeling_plan_sha256=sha256_file(
            ensure_autonomy_path(
                root,
                root.joinpath(*source.modeling_plan.path.split("/")),
                must_exist=True,
            )
        ),
        blend_sha256=sha256_file(
            ensure_autonomy_path(
                root,
                root.joinpath(*source.blend.path.split("/")),
                must_exist=True,
            )
        ),
    )
    request = load_material_closure_model(
        root,
        plan.preflight_request,
        MaterialPromotionPreflightRequest,
    )
    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    if (
        request.job_id,
        request.workflow_id,
        request.dispatch_id,
        request.session_id,
    ) != identity:
        raise ValueError("material repair preflight request belongs to another session")
    snapshot = load_material_closure_model(
        root,
        request.canonical_snapshot,
        MaterialCanonicalSnapshot,
    )
    if (
        snapshot.scene_spec != source.scene_spec
        or snapshot.modeling_plan != source.modeling_plan
        or snapshot.blend != source.blend
        or snapshot.material_plan != source.material_plan
        or snapshot.material_plan_absence != source.material_plan_absence
    ):
        raise ValueError("material repair preflight snapshot differs from reusable geometry")
    before = (
        sha256_file(root / "analysis" / "scene_spec.json"),
        sha256_file(root / "analysis" / "modeling_plan.json"),
        sha256_file(root / "blender" / "scene.blend"),
    )
    now = created_at or datetime.now(UTC)
    preflight = MaterialClosureService(root).run_preflight(
        request,
        preview_size=preview_size,
        created_at=now,
    )
    after = (
        sha256_file(root / "analysis" / "scene_spec.json"),
        sha256_file(root / "analysis" / "modeling_plan.json"),
        sha256_file(root / "blender" / "scene.blend"),
    )
    if after != before or after != (
        source.scene_spec.sha256,
        source.modeling_plan.sha256,
        source.blend.sha256,
    ):
        raise PermissionError("material repair preflight changed reusable geometry")
    passed = preflight.approval_plan_eligible
    latest = preflight.report_artifact or preflight.failure_artifact
    if latest is None:
        raise ValueError("material repair preflight published no terminal evidence")
    attempt = MaterialAttemptState(
        attempt_id=plan.repair_attempt_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        producer="codex_blender_modeler.material_closure.incident_service",
        producer_version="0.1.0",
        created_at=now,
        sequence=1,
        state="approval_pending" if passed else "preflight_failed",
        canonical_snapshot=snapshot,
        active_closure=request.closure,
        latest_preflight=latest,
        retry_required=False,
        retry_allowed=False,
        blocked_reason=(
            None
            if passed
            else "material framework preflight failed before approval and controller execution"
        ),
    )
    attempt, attempt_artifact = publish_material_closure_model(
        root,
        (
            f"production/material_repair/{plan.session_id}/attempts/"
            f"{plan.repair_attempt_id}/state-0001.json"
        ),
        attempt,
        artifact_id=attempt.attempt_id,
        kind="material_attempt_state",
    )
    if passed:
        validate_material_repair_preapproval_outcome(
            plan,
            attempt_status=attempt.state,
            approval_consumption_count=0,
            controller_invocation_count=0,
            canonical_write_count=0,
        )
    return MaterialRepairSessionRunResult(
        plan=plan,
        source_binding=source,
        preflight=preflight,
        attempt_state=attempt,
        attempt_state_artifact=attempt_artifact,
    )


__all__ = [
    "MaterialCanonicalObservationPublication",
    "MaterialRepairSessionRunResult",
    "RecoverySourceArchiveSpec",
    "archive_job_specific_recovery_sources",
    "load_material_closure_model",
    "publish_material_closure_model",
    "publish_current_material_canonical_observations",
    "publish_material_repair_session_plan",
    "publish_material_rollback_restoration_observation",
    "publish_material_session_supersession",
    "run_material_repair_session",
    "supersede_material_retry",
]
