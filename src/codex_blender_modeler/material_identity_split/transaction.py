"""Guarded paired canonical transaction and recovery for approved identity splits."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel

from ..autonomy.io import ensure_autonomy_path
from ..blender_artifacts import native_io_path, publish_bytes_create_once
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..material_closure.collector import build_material_plan_absence_evidence
from ..material_closure.incident_service import (
    load_material_closure_model,
)
from ..material_closure.models import ExactArtifact, MaterialDependencyClosure
from ..material_closure.preflight import validate_exact_artifact
from ..material_closure.state_consistency import build_material_canonical_snapshot
from ..workspace import canonical_scene_spec_write_lock
from .models import (
    MaterialIdentitySplitApplyIntent,
    MaterialIdentitySplitApplyReceipt,
    MaterialIdentitySplitApprovalConsumptionReceipt,
    MaterialIdentitySplitApprovalRequest,
    MaterialIdentitySplitGeometryContinuationReceipt,
    MaterialIdentitySplitInvariantReport,
    MaterialIdentitySplitPlan,
    MaterialIdentitySplitPolicyApplyIntent,
    MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt,
    MaterialIdentitySplitPreapprovalReport,
    MaterialIdentitySplitPreapprovalRequest,
    MaterialIdentitySplitRecoveryReceipt,
    MaterialIdentitySplitRollbackReceipt,
    MaterialIdentitySplitRootScopeApproval,
    MaterialIdentitySplitTransactionState,
)
from .service import (
    MaterialIdentitySplitError,
    MaterialIdentitySplitService,
    _artifact_from_path,
    _identity_kwargs,
    _inventory_assignment_projection,
    _inventory_object_projection,
    _load_exact_json,
    _publish_json_artifact,
    _publish_model,
    _utc_now,
)

CrashPoint = Literal[
    "after_scene_spec",
    "after_modeling_plan",
    "after_blender_rebuild",
    "after_invariant_validation",
    "before_apply_receipt",
    "after_apply_receipt",
    "during_rollback",
]
MaterialIdentitySplitTransactionIntent: TypeAlias = (
    MaterialIdentitySplitApplyIntent | MaterialIdentitySplitPolicyApplyIntent
)


@dataclass(frozen=True)
class MaterialIdentitySplitApplyResult:
    """Return one committed paired transaction and refreshed canonical evidence."""

    apply_intent: ExactArtifact
    approval_consumption: ExactArtifact
    apply_receipt: ExactArtifact
    geometry_continuation: ExactArtifact
    canonical_scene_inventory: ExactArtifact
    canonical_build_provenance: ExactArtifact
    material_plan_absence: ExactArtifact
    canonical_snapshot: ExactArtifact
    terminal_state: ExactArtifact


@dataclass(frozen=True)
class MaterialIdentitySplitRecoveryResult:
    """Return one deterministic terminal recovery outcome."""

    recovery_receipt: ExactArtifact
    rollback_receipt: ExactArtifact | None
    geometry_continuation: ExactArtifact | None
    terminal_state: ExactArtifact
    outcome: str


@dataclass(frozen=True)
class MaterialIdentitySplitAuthorityRefresh:
    """Return post-apply authority that future material closure must recollect."""

    geometry_continuation: ExactArtifact
    canonical_scene_inventory: ExactArtifact
    canonical_build_provenance: ExactArtifact
    material_plan_absence: ExactArtifact
    canonical_snapshot: ExactArtifact


def _atomic_replace_exact(destination: Path, source: Path) -> None:
    """Replace one canonical file with exact source bytes using same-directory rename."""

    destination = destination.expanduser().resolve()
    source = source.expanduser().resolve(strict=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{uuid4().hex}.identity-split.tmp"
    )
    with open(native_io_path(source), "rb") as input_handle:
        content = input_handle.read()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(native_io_path(temporary), flags, 0o600)
    try:
        pending = memoryview(content)
        while pending:
            written = os.write(descriptor, pending)
            if written <= 0:
                raise OSError("identity-split atomic replacement made no progress")
            pending = pending[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(native_io_path(temporary), native_io_path(destination))
    finally:
        if os.path.exists(native_io_path(temporary)):
            os.unlink(native_io_path(temporary))


def _publish_state(
    job_root: Path,
    plan: MaterialIdentitySplitPlan,
    *,
    sequence: int,
    previous_state: ExactArtifact,
    state: str,
    plan_artifact: ExactArtifact,
    approval_request: ExactArtifact,
    apply_intent: ExactArtifact,
    approval_consumption: ExactArtifact,
    archives: list[ExactArtifact],
    performed_actions: list[str],
    allowed_next_actions: list[str],
    created_at: datetime,
    blocked_reason: str | None = None,
    technical_retry_count: int = 0,
) -> ExactArtifact:
    """Append one exact transaction state with explicit predecessor continuity."""

    model = MaterialIdentitySplitTransactionState(
        **_identity_kwargs(plan, created_at),
        transaction_id=plan.run_id,
        sequence=sequence,
        previous_state=previous_state,
        state=state,
        plan=plan_artifact,
        approval_request=approval_request,
        apply_intent=apply_intent,
        approval_consumption=approval_consumption,
        canonical_observation=plan.preconditions,
        archives=archives,
        performed_actions=performed_actions,
        allowed_next_actions=allowed_next_actions,
        technical_retry_count=technical_retry_count,
        blocked_reason=blocked_reason,
    )
    return _publish_model(
        job_root,
        f"production/material_identity_split/{plan.run_id}/states/{sequence:04d}.json",
        model,
        artifact_id=f"{plan.run_id}-state-{sequence:04d}",
        kind="material_identity_split_transaction_state",
    )


def _archive_canonical(
    job_root: Path,
    plan: MaterialIdentitySplitPlan,
) -> list[ExactArtifact]:
    """Publish exact create-once archives for the three paired canonical inputs."""

    archives: list[ExactArtifact] = []
    for label, artifact, suffix, kind, media_type in (
        (
            "scene-spec",
            plan.preconditions.scene_spec,
            "scene_spec.json",
            "archived_scene_spec",
            "application/json",
        ),
        (
            "modeling-plan",
            plan.preconditions.modeling_plan,
            "modeling_plan.json",
            "archived_modeling_plan",
            "application/json",
        ),
        (
            "blend",
            plan.preconditions.blend,
            "scene.blend",
            "archived_blend",
            "application/x-blender",
        ),
    ):
        source = validate_exact_artifact(job_root, artifact)
        relative = f"production/material_identity_split/{plan.run_id}/archives/{suffix}"
        destination = ensure_autonomy_path(
            job_root,
            job_root.joinpath(*relative.split("/")),
            must_exist=False,
        )
        publish_bytes_create_once(destination, source.read_bytes())
        archives.append(
            _artifact_from_path(
                job_root,
                relative,
                artifact_id=f"{plan.run_id}-archive-{label}",
                kind=kind,
                media_type=media_type,
            )
        )
    return archives


def _validate_apply_bindings(
    job_root: Path,
    intent: MaterialIdentitySplitTransactionIntent,
    *,
    require_current_preconditions: bool = True,
) -> tuple[
    MaterialIdentitySplitPlan,
    MaterialIdentitySplitApprovalRequest,
    MaterialIdentitySplitRootScopeApproval | object,
]:
    """Replay one explicit or policy intent and require its exact candidate bindings."""

    plan = load_material_closure_model(job_root, intent.plan, MaterialIdentitySplitPlan)
    request = load_material_closure_model(
        job_root,
        intent.approval_request,
        MaterialIdentitySplitApprovalRequest,
    )
    if isinstance(intent, MaterialIdentitySplitPolicyApplyIntent):
        from ..autonomy_v2.approval_models import (
            ApprovalArtifact,
            AQV2RoutinePolicyAuthorization,
        )
        from ..autonomy_v2.approval_policy_service import (
            validate_routine_policy_authorization,
        )
        from ..workspace import job_dir

        if job_dir(intent.job_id).expanduser().resolve(strict=True) != job_root:
            raise PermissionError("policy ApplyIntent resolved another workspace job")
        validate_exact_artifact(job_root, intent.policy_authorization)
        replay = validate_routine_policy_authorization(
            intent.job_id,
            intent.session_id,
            policy_authorization_path=intent.policy_authorization.path,
            expected_gate_kind="bounded_material_identity_split",
            expected_target_path=intent.approval_request.path,
        )
        authorization = AQV2RoutinePolicyAuthorization.model_validate_json(
            json.dumps(replay["authorization"])
        )
        authorization_artifact = ApprovalArtifact.model_validate(
            replay["authorization_artifact"]
        )
        authority_matches = (
            intent.policy_authorization.path == authorization_artifact.path
            and intent.policy_authorization.sha256 == authorization_artifact.sha256
            and intent.policy_authorization.byte_size == authorization_artifact.byte_size
            and intent.policy_authorization.kind == authorization_artifact.kind
        )
        target_matches = (
            authorization.exact_target_artifact.path == intent.approval_request.path
            and authorization.exact_target_artifact.sha256
            == intent.approval_request.sha256
            and authorization.exact_target_artifact.byte_size
            == intent.approval_request.byte_size
        )
        canonical_matches = (
            authorization.current_canonical_snapshot.path
            == plan.preconditions.scene_spec.path
            and authorization.current_canonical_snapshot.sha256
            == plan.preconditions.scene_spec.sha256
            and authorization.current_canonical_snapshot.byte_size
            == plan.preconditions.scene_spec.byte_size
        )
        if (
            not authority_matches
            or not target_matches
            or not canonical_matches
            or authorization.workflow_id != intent.workflow_id
            or authorization.dispatch_id != intent.dispatch_id
            or authorization.session_id != intent.session_id
            or authorization.bounded_transformation
            != "bounded_material_identity_split"
            or authorization.is_user_approval
            or authorization.approved_by_user
        ):
            raise PermissionError(
                "identity-split policy authority differs from the exact bounded request"
            )
        if (
            any(
                observed != expected
                for observed, expected in (
                    (request.job_id, intent.job_id),
                    (request.workflow_id, intent.workflow_id),
                    (request.dispatch_id, intent.dispatch_id),
                    (request.run_id, intent.run_id),
                )
            )
            or request.plan != intent.plan
            or request.candidate_scene_spec != plan.candidate_scene_spec
            or request.candidate_modeling_plan != plan.candidate_modeling_plan
            or request.scene_diff_allowlist != plan.scene_diff_allowlist
            or request.modeling_plan_diff_report != intent.modeling_plan_diff_report
            or request.preapproval_report != intent.preapproval_report
            or request.shadow_build_receipt != intent.shadow_build_receipt
            or request.invariant_report != intent.invariant_report
            or request.preconditions != plan.preconditions
            or intent.candidate_scene_spec != plan.candidate_scene_spec
            or intent.candidate_modeling_plan != plan.candidate_modeling_plan
            or intent.scene_diff_allowlist != plan.scene_diff_allowlist
            or intent.modeling_plan_diff_report != request.modeling_plan_diff_report
            or intent.preapproval_report != request.preapproval_report
            or intent.shadow_build_receipt != request.shadow_build_receipt
            or intent.invariant_report != request.invariant_report
            or intent.preconditions != plan.preconditions
            or intent.transaction_id != plan.run_id
        ):
            raise PermissionError(
                "policy ApplyIntent is not exact-bound to the paired split candidate"
            )
        if require_current_preconditions:
            MaterialIdentitySplitService(job_root).validate_plan_current(plan)
        return plan, request, authorization
    approval = load_material_closure_model(
        job_root,
        intent.approval,
        MaterialIdentitySplitRootScopeApproval,
    )
    if approval.decision != "approved":
        raise PermissionError("rejected identity-split approval cannot be applied")
    if (
        any(
            observed != expected
            for observed, expected in (
                (request.job_id, intent.job_id),
                (request.workflow_id, intent.workflow_id),
                (request.dispatch_id, intent.dispatch_id),
                (request.run_id, intent.run_id),
                (approval.job_id, intent.job_id),
                (approval.workflow_id, intent.workflow_id),
                (approval.dispatch_id, intent.dispatch_id),
                (approval.run_id, intent.run_id),
            )
        )
        or request.plan != intent.plan
        or request.candidate_scene_spec != plan.candidate_scene_spec
        or request.candidate_modeling_plan != plan.candidate_modeling_plan
        or request.scene_diff_allowlist != plan.scene_diff_allowlist
        or request.modeling_plan_diff_report != intent.modeling_plan_diff_report
        or request.preapproval_report != intent.preapproval_report
        or request.shadow_build_receipt != intent.shadow_build_receipt
        or request.invariant_report != intent.invariant_report
        or request.preconditions != plan.preconditions
        or approval.approval_request != intent.approval_request
        or approval.candidate_scene_spec != request.candidate_scene_spec
        or approval.candidate_modeling_plan != request.candidate_modeling_plan
        or approval.scene_diff_allowlist != request.scene_diff_allowlist
        or approval.modeling_plan_diff_report != request.modeling_plan_diff_report
        or approval.preapproval_report != request.preapproval_report
        or approval.shadow_build_receipt != request.shadow_build_receipt
        or approval.invariant_report != request.invariant_report
        or approval.preconditions != request.preconditions
        or intent.candidate_scene_spec != plan.candidate_scene_spec
        or intent.candidate_modeling_plan != plan.candidate_modeling_plan
        or intent.scene_diff_allowlist != plan.scene_diff_allowlist
        or intent.modeling_plan_diff_report != request.modeling_plan_diff_report
        or intent.preapproval_report != request.preapproval_report
        or intent.shadow_build_receipt != request.shadow_build_receipt
        or intent.invariant_report != request.invariant_report
        or intent.preconditions != plan.preconditions
        or intent.transaction_id != plan.run_id
    ):
        raise PermissionError("ApplyIntent is not exact-bound to the approved paired candidate")
    if require_current_preconditions:
        MaterialIdentitySplitService(job_root).validate_plan_current(plan)
    return plan, request, approval


def _recovery_retry_count(
    job_root: Path,
    run_id: str,
    latest: MaterialIdentitySplitTransactionState,
) -> int:
    """Return the bounded retry ordinal and reject a second recovery reattempt."""

    recoveries_root = (
        job_root / "production" / "material_identity_split" / run_id / "recoveries"
    )
    recovery_files = (
        sorted(recoveries_root.glob("[0-9][0-9][0-9][0-9].json"))
        if recoveries_root.is_dir()
        else []
    )
    receipts = [
        MaterialIdentitySplitRecoveryReceipt.model_validate_json(path.read_bytes())
        for path in recovery_files
    ]
    if any(receipt.transaction_id != run_id for receipt in receipts):
        raise MaterialIdentitySplitError("identity-split recovery receipt scope is inconsistent")
    if latest.state != "recovery_required":
        return 0
    prior_count = max(
        [latest.technical_retry_count, *(item.technical_retry_count for item in receipts)],
        default=0,
    )
    if prior_count >= 1:
        raise PermissionError("identity-split technical recovery retry is exhausted")
    return 1


def _require_single_intent(
    job_root: Path,
    approval_artifact: ExactArtifact,
    intent: MaterialIdentitySplitTransactionIntent,
) -> None:
    """Reject a second substantive intent for one user or policy authority."""

    intents_root = job_root / "production" / "material_identity_split" / intent.run_id / "intents"
    if not intents_root.is_dir():
        return
    for path in sorted(intents_root.glob("*.json")):
        observed = _load_transaction_intent_bytes(path.read_bytes())
        observed_authority = (
            observed.policy_authorization
            if isinstance(observed, MaterialIdentitySplitPolicyApplyIntent)
            else observed.approval
        )
        if observed_authority == approval_artifact and observed != intent:
            raise PermissionError(
                "identity-split authority already binds another ApplyIntent"
            )


def _load_transaction_intent_bytes(
    payload: bytes,
) -> MaterialIdentitySplitTransactionIntent:
    """Dispatch an immutable split intent by exact additive schema version."""

    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("identity-split ApplyIntent must contain one JSON object")
    if decoded.get("schema_version") == "0.3.0":
        return MaterialIdentitySplitPolicyApplyIntent.model_validate_json(payload)
    return MaterialIdentitySplitApplyIntent.model_validate_json(payload)


def _load_transaction_intent(
    job_root: Path,
    artifact: ExactArtifact,
) -> MaterialIdentitySplitTransactionIntent:
    """Hash-check and strict-load either supported split intent authority shape."""

    model = (
        MaterialIdentitySplitPolicyApplyIntent
        if artifact.kind == "material_identity_split_policy_apply_intent"
        else MaterialIdentitySplitApplyIntent
    )
    return load_material_closure_model(job_root, artifact, model)


def _publish_intent_and_consumption(
    job_root: Path,
    intent: MaterialIdentitySplitTransactionIntent,
) -> tuple[ExactArtifact, ExactArtifact]:
    """Publish an intent and consume its separated user or policy authority once."""

    authority = (
        intent.policy_authorization
        if isinstance(intent, MaterialIdentitySplitPolicyApplyIntent)
        else intent.approval
    )
    _require_single_intent(job_root, authority, intent)
    intent_artifact = _publish_model(
        job_root,
        f"production/material_identity_split/{intent.run_id}/intents/{intent.intent_id}.json",
        intent,
        artifact_id=intent.intent_id,
        kind=(
            "material_identity_split_policy_apply_intent"
            if isinstance(intent, MaterialIdentitySplitPolicyApplyIntent)
            else "material_identity_split_apply_intent"
        ),
    )
    if isinstance(intent, MaterialIdentitySplitPolicyApplyIntent):
        consumption: BaseModel = MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt(
            job_id=intent.job_id,
            workflow_id=intent.workflow_id,
            dispatch_id=intent.dispatch_id,
            session_id=intent.session_id,
            run_id=intent.run_id,
            producer="codex_blender_modeler.material_identity_split",
            created_at=intent.created_at,
            receipt_id=f"{intent.run_id}-policy-consumption",
            policy_authorization=intent.policy_authorization,
            approval_request=intent.approval_request,
            apply_intent=intent_artifact,
        )
        consumption_id = f"{intent.run_id}-policy-consumption"
        consumption_kind = "material_identity_split_policy_authorization_consumption_receipt"
    else:
        consumption = MaterialIdentitySplitApprovalConsumptionReceipt(
            job_id=intent.job_id,
            workflow_id=intent.workflow_id,
            dispatch_id=intent.dispatch_id,
            run_id=intent.run_id,
            producer="codex_blender_modeler.material_identity_split",
            producer_version="0.1.0",
            created_at=intent.created_at,
            receipt_id=f"{intent.run_id}-approval-consumption",
            approval=intent.approval,
            approval_request=intent.approval_request,
            apply_intent=intent_artifact,
        )
        consumption_id = f"{intent.run_id}-approval-consumption"
        consumption_kind = "material_identity_split_approval_consumption_receipt"
    consumption_artifact = _publish_model(
        job_root,
        (f"production/material_identity_split/{intent.run_id}/approval_consumptions/0001.json"),
        consumption,
        artifact_id=consumption_id,
        kind=consumption_kind,
    )
    return intent_artifact, consumption_artifact


def _run_canonical_blender(job_root: Path) -> tuple[Path, Path, Path]:
    """Rebuild, inspect, and validate the paired canonical SceneSpec under host lock."""

    scene = job_root / "analysis" / "scene_spec.json"
    blend = job_root / "blender" / "scene.blend"
    inventory = job_root / "reports" / "scene_inventory.json"
    validation = job_root / "reports" / "validation.json"
    run_blender(
        "build_scene.py",
        ["--spec", str(scene), "--output", str(blend)],
        factory_startup=True,
        disable_autoexec=True,
    )
    run_blender(
        "inspect_scene.py",
        ["--output", str(inventory)],
        blend_file=blend,
        factory_startup=True,
        disable_autoexec=True,
    )
    run_blender(
        "validate_scene.py",
        ["--spec", str(scene), "--output", str(validation)],
        blend_file=blend,
        factory_startup=True,
        disable_autoexec=True,
    )
    with open(native_io_path(validation), "rb") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise MaterialIdentitySplitError("canonical identity-split validation failed")
    return blend, inventory, validation


def _validate_post_apply_inventory(
    job_root: Path,
    plan: MaterialIdentitySplitPlan,
    inventory_path: Path,
    canonical_inventory: ExactArtifact,
) -> None:
    """Require only planned material changes in a rebuilt canonical inventory."""

    canonical = _load_exact_json(job_root, canonical_inventory)
    with open(native_io_path(inventory_path), "rb") as handle:
        observed = json.load(handle)
    if not isinstance(observed, dict):
        raise MaterialIdentitySplitError("post-apply inventory root is invalid")
    if _inventory_object_projection(canonical) != _inventory_object_projection(observed):
        raise MaterialIdentitySplitError("identity split changed geometry or UV inventory")
    candidate = _load_exact_json(job_root, plan.candidate_scene_spec)
    expected = {str(item["id"]): [str(item["material_id"])] for item in candidate["objects"]}
    actual = _inventory_assignment_projection(observed)
    if any(actual.get(object_id) != materials for object_id, materials in expected.items()):
        raise MaterialIdentitySplitError("rebuilt material assignments differ from the plan")


def _closure_role_artifact(
    job_root: Path,
    plan: MaterialIdentitySplitPlan,
    role: str,
    *,
    kind: str,
) -> ExactArtifact:
    """Resolve one exact prior authority root from the plan-bound material closure."""

    closure = load_material_closure_model(
        job_root,
        plan.current_material_closure,
        MaterialDependencyClosure,
    )
    matches = [entry for entry in closure.entries if entry.role == role]
    if len(matches) != 1:
        raise MaterialIdentitySplitError(
            f"identity-split prior closure requires exactly one {role}"
        )
    entry = matches[0]
    artifact = ExactArtifact(
        artifact_id=f"{plan.run_id}-prior-{role}",
        kind=kind,
        path=entry.path,
        sha256=entry.sha256,
        byte_size=entry.byte_size,
        media_type="application/json",
    )
    validate_exact_artifact(job_root, artifact)
    return artifact


def _previous_geometry_approval_artifact(
    job_root: Path,
    plan: MaterialIdentitySplitPlan,
) -> ExactArtifact:
    """Bind the exact pre-split geometry review decision without reclassifying it."""

    authority_path = validate_exact_artifact(job_root, plan.preconditions.root_authorization)
    approval_path = ensure_autonomy_path(
        job_root,
        authority_path.with_name("geometry_review_approval.txt"),
        must_exist=True,
    )
    if not approval_path.is_file():
        raise MaterialIdentitySplitError("identity split requires prior geometry approval bytes")
    return _artifact_from_path(
        job_root,
        approval_path.relative_to(job_root).as_posix(),
        artifact_id=f"{plan.run_id}-prior-geometry-review-approval",
        kind="geometry_review_approval",
        media_type="text/plain",
    )


def _publish_post_apply_authority_refresh(
    job_root: Path,
    *,
    plan: MaterialIdentitySplitPlan,
    request: MaterialIdentitySplitApprovalRequest,
    apply_receipt_artifact: ExactArtifact,
    created_at: datetime,
) -> MaterialIdentitySplitAuthorityRefresh:
    """Publish current post-apply observations and a non-synthetic geometry continuation."""

    apply_receipt = load_material_closure_model(
        job_root,
        apply_receipt_artifact,
        MaterialIdentitySplitApplyReceipt,
    )
    for artifact in (
        apply_receipt.post_scene_spec,
        apply_receipt.post_modeling_plan,
        apply_receipt.post_blend,
    ):
        validate_exact_artifact(job_root, artifact)
    material_plan_path = job_root / "analysis" / "material_plan.json"
    if os.path.exists(native_io_path(material_plan_path)):
        raise MaterialIdentitySplitError("identity split must preserve MaterialPlan absence")
    inventory_path = ensure_autonomy_path(
        job_root,
        job_root / "reports" / "scene_inventory.json",
        must_exist=True,
    )
    with open(native_io_path(inventory_path), "rb") as handle:
        inventory_payload = json.load(handle)
    if (
        not isinstance(inventory_payload, dict)
        or inventory_payload.get("job_id") != plan.job_id
        or inventory_payload.get("blender_version") != "5.0.1"
    ):
        raise MaterialIdentitySplitError("post-apply SceneInventory identity is invalid")
    post_root = f"production/material_identity_split/{plan.run_id}/post_apply"
    inventory_artifact = _publish_json_artifact(
        job_root,
        f"{post_root}/scene_inventory.json",
        inventory_payload,
        artifact_id=f"{plan.run_id}-post-scene-inventory",
        kind="scene_inventory",
    )
    build_payload = collect_build_provenance(
        job_root,
        plan.job_id,
        validate_surface_details=False,
    )
    build_artifact = _publish_json_artifact(
        job_root,
        f"{post_root}/build_provenance.json",
        build_payload,
        artifact_id=f"{plan.run_id}-post-build-provenance",
        kind="build_provenance",
    )
    absence = build_material_plan_absence_evidence(
        job_root=job_root,
        absence_id=f"{plan.run_id}-post-material-plan-absence",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.run_id,
        producer="codex_blender_modeler.material_identity_split",
        producer_version="0.1.0",
        created_at=created_at,
        observation_state=apply_receipt_artifact,
        canonical_scene_spec=apply_receipt.post_scene_spec,
        canonical_blend=apply_receipt.post_blend,
    )
    absence_artifact = _publish_model(
        job_root,
        f"{post_root}/material_plan_absence.json",
        absence,
        artifact_id=absence.absence_id,
        kind="material_plan_absence",
    )
    snapshot = build_material_canonical_snapshot(
        job_root=job_root,
        snapshot_id=f"{plan.run_id}-post-canonical-snapshot",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.run_id,
        producer="codex_blender_modeler.material_identity_split",
        producer_version="0.1.0",
        created_at=created_at,
        scene_spec=apply_receipt.post_scene_spec,
        modeling_plan=apply_receipt.post_modeling_plan,
        blend=apply_receipt.post_blend,
        build_provenance=build_artifact,
        material_plan_absence=absence_artifact,
    )
    snapshot_artifact = _publish_model(
        job_root,
        f"{post_root}/canonical_snapshot.json",
        snapshot,
        artifact_id=snapshot.snapshot_id,
        kind="material_canonical_snapshot",
    )
    preapproval = load_material_closure_model(
        job_root,
        request.preapproval_report,
        MaterialIdentitySplitPreapprovalReport,
    )
    preapproval_request = load_material_closure_model(
        job_root,
        preapproval.request,
        MaterialIdentitySplitPreapprovalRequest,
    )
    prior_invariant = load_material_closure_model(
        job_root,
        request.invariant_report,
        MaterialIdentitySplitInvariantReport,
    )
    if prior_invariant.status != "passed":
        raise MaterialIdentitySplitError("post-apply continuation requires passed invariants")
    previous_geometry_validation = _closure_role_artifact(
        job_root,
        plan,
        "geometry_candidate_validation_receipt",
        kind="geometry_candidate_validation_receipt",
    )
    continuation = MaterialIdentitySplitGeometryContinuationReceipt(
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        run_id=plan.run_id,
        producer="codex_blender_modeler.material_identity_split",
        producer_version="0.1.0",
        created_at=created_at,
        receipt_id=f"{plan.run_id}-geometry-continuation",
        previous_geometry_approval=_previous_geometry_approval_artifact(job_root, plan),
        previous_geometry_validation=previous_geometry_validation,
        apply_intent=apply_receipt.apply_intent,
        apply_receipt=apply_receipt_artifact,
        post_scene_spec=apply_receipt.post_scene_spec,
        post_modeling_plan=apply_receipt.post_modeling_plan,
        post_blend=apply_receipt.post_blend,
        invariant_report=request.invariant_report,
        canonical_scene_inventory=inventory_artifact,
        canonical_build_provenance=build_artifact,
        material_plan_absence=absence_artifact,
        canonical_snapshot=snapshot_artifact,
        reference_authorization=plan.preconditions.root_authorization,
        content_scope_sha256=plan.preconditions.content_scope_sha256,
        identity_split_diff=plan.scene_diff_allowlist,
    )
    if preapproval_request.canonical_scene_inventory.path == inventory_artifact.path:
        raise MaterialIdentitySplitError("post-apply inventory must be a new run-owned observation")
    continuation_artifact = _publish_model(
        job_root,
        f"{post_root}/geometry_continuation_receipt.json",
        continuation,
        artifact_id=continuation.receipt_id,
        kind="material_identity_split_geometry_continuation_receipt",
    )
    return MaterialIdentitySplitAuthorityRefresh(
        geometry_continuation=continuation_artifact,
        canonical_scene_inventory=inventory_artifact,
        canonical_build_provenance=build_artifact,
        material_plan_absence=absence_artifact,
        canonical_snapshot=snapshot_artifact,
    )


def _restore_archives(job_root: Path, archives: list[ExactArtifact]) -> None:
    """Restore exact SceneSpec, ModelingPlan, and Blend bytes from immutable archives."""

    if len(archives) != 3:
        raise MaterialIdentitySplitError("identity-split rollback requires three archives")
    targets = (
        job_root / "analysis" / "scene_spec.json",
        job_root / "analysis" / "modeling_plan.json",
        job_root / "blender" / "scene.blend",
    )
    for artifact, target in zip(archives, targets, strict=True):
        _atomic_replace_exact(target, validate_exact_artifact(job_root, artifact))


def apply_material_identity_split(
    job_root: Path,
    *,
    intent: MaterialIdentitySplitTransactionIntent,
    canonical_scene_inventory: ExactArtifact,
    crash_after: CrashPoint | None = None,
    created_at: datetime | None = None,
) -> MaterialIdentitySplitApplyResult:
    """Execute one user-approved or policy-authorized guarded paired transaction."""

    root = job_root.expanduser().resolve(strict=True)
    observed_at = _utc_now(created_at)
    plan, request, _approval = _validate_apply_bindings(root, intent)
    if intent.created_at != observed_at:
        observed_at = intent.created_at
    status = MaterialIdentitySplitService(root).get_status(plan.run_id)
    if status.status != "eligible_for_explicit_user_scope_approval":
        raise PermissionError(
            "identity-split transaction is not at its approval boundary "
            "or policy authority boundary"
        )
    lock_owner = f"material-identity-split-{plan.run_id}"
    archives: list[ExactArtifact] = []
    state_artifacts: list[ExactArtifact] = []
    try:
        with canonical_scene_spec_write_lock(plan.job_id, lock_owner):
            plan, request, _approval = _validate_apply_bindings(root, intent)
            status = MaterialIdentitySplitService(root).get_status(plan.run_id)
            if status.status != "eligible_for_explicit_user_scope_approval":
                raise PermissionError(
                    "identity-split transaction changed before authority consumption"
                )
            MaterialIdentitySplitService(root).validate_plan_current(plan)
            intent_artifact, consumption_artifact = _publish_intent_and_consumption(
                root, intent
            )
            approval_consumed_state = _publish_state(
                root,
                plan,
                sequence=status.latest_sequence + 1,
                previous_state=status.latest_state,
                state="approval_consumed",
                plan_artifact=request.plan,
                approval_request=intent.approval_request,
                apply_intent=intent_artifact,
                approval_consumption=consumption_artifact,
                archives=[],
                performed_actions=["approval_consumed_once", "apply_intent_published"],
                allowed_next_actions=["archive_canonical_inputs"],
                created_at=observed_at,
            )
            state_artifacts.append(approval_consumed_state)
            archives = _archive_canonical(root, plan)
            state = _publish_state(
                root,
                plan,
                sequence=status.latest_sequence + 2,
                previous_state=state_artifacts[-1],
                state="archives_written",
                plan_artifact=request.plan,
                approval_request=intent.approval_request,
                apply_intent=intent_artifact,
                approval_consumption=consumption_artifact,
                archives=archives,
                performed_actions=["canonical_archives_written"],
                allowed_next_actions=["replace_scene_spec"],
                created_at=observed_at,
            )
            state_artifacts.append(state)
            _atomic_replace_exact(
                root / "analysis" / "scene_spec.json",
                validate_exact_artifact(root, plan.candidate_scene_spec),
            )
            state_artifacts.append(
                _publish_state(
                    root,
                    plan,
                    sequence=status.latest_sequence + 3,
                    previous_state=state_artifacts[-1],
                    state="scene_spec_replaced",
                    plan_artifact=request.plan,
                    approval_request=intent.approval_request,
                    apply_intent=intent_artifact,
                    approval_consumption=consumption_artifact,
                    archives=archives,
                    performed_actions=["scene_spec_replaced"],
                    allowed_next_actions=["replace_modeling_plan"],
                    created_at=observed_at,
                )
            )
            if crash_after == "after_scene_spec":
                raise RuntimeError("injected identity-split crash after SceneSpec")
            _atomic_replace_exact(
                root / "analysis" / "modeling_plan.json",
                validate_exact_artifact(root, plan.candidate_modeling_plan),
            )
            state_artifacts.append(
                _publish_state(
                    root,
                    plan,
                    sequence=status.latest_sequence + 4,
                    previous_state=state_artifacts[-1],
                    state="modeling_plan_replaced",
                    plan_artifact=request.plan,
                    approval_request=intent.approval_request,
                    apply_intent=intent_artifact,
                    approval_consumption=consumption_artifact,
                    archives=archives,
                    performed_actions=["modeling_plan_replaced"],
                    allowed_next_actions=["rebuild_blender"],
                    created_at=observed_at,
                )
            )
            if crash_after == "after_modeling_plan":
                raise RuntimeError("injected identity-split crash after ModelingPlan")
            blend, inventory, _validation = _run_canonical_blender(root)
            state_artifacts.append(
                _publish_state(
                    root,
                    plan,
                    sequence=status.latest_sequence + 5,
                    previous_state=state_artifacts[-1],
                    state="blender_rebuilt",
                    plan_artifact=request.plan,
                    approval_request=intent.approval_request,
                    apply_intent=intent_artifact,
                    approval_consumption=consumption_artifact,
                    archives=archives,
                    performed_actions=["canonical_blender_rebuilt"],
                    allowed_next_actions=["validate_invariants"],
                    created_at=observed_at,
                )
            )
            if crash_after == "after_blender_rebuild":
                raise RuntimeError("injected identity-split crash after Blender rebuild")
            _validate_post_apply_inventory(root, plan, inventory, canonical_scene_inventory)
            state_artifacts.append(
                _publish_state(
                    root,
                    plan,
                    sequence=status.latest_sequence + 6,
                    previous_state=state_artifacts[-1],
                    state="invariants_verified",
                    plan_artifact=request.plan,
                    approval_request=intent.approval_request,
                    apply_intent=intent_artifact,
                    approval_consumption=consumption_artifact,
                    archives=archives,
                    performed_actions=["post_apply_invariants_verified"],
                    allowed_next_actions=["publish_apply_receipt"],
                    created_at=observed_at,
                )
            )
            if crash_after == "after_invariant_validation":
                raise RuntimeError("injected identity-split crash after invariants")
            if crash_after == "before_apply_receipt":
                raise RuntimeError("injected identity-split crash before ApplyReceipt")
            post_scene = _artifact_from_path(
                root,
                "analysis/scene_spec.json",
                artifact_id=f"{plan.run_id}-post-scene-spec",
                kind="scene_spec",
            )
            post_modeling = _artifact_from_path(
                root,
                "analysis/modeling_plan.json",
                artifact_id=f"{plan.run_id}-post-modeling-plan",
                kind="modeling_plan",
            )
            post_blend = _artifact_from_path(
                root,
                "blender/scene.blend",
                artifact_id=f"{plan.run_id}-post-blend",
                kind="canonical_blend",
                media_type="application/x-blender",
            )
            if (
                post_scene.sha256 != intent.expected_scene_spec_sha256
                or post_modeling.sha256 != intent.expected_modeling_plan_sha256
                or blend != root / "blender" / "scene.blend"
            ):
                raise MaterialIdentitySplitError("paired canonical outputs differ from ApplyIntent")
            receipt = MaterialIdentitySplitApplyReceipt(
                **_identity_kwargs(plan, observed_at),
                receipt_id=f"{plan.run_id}-apply-receipt",
                transaction_id=plan.run_id,
                apply_intent=intent_artifact,
                approval_consumption=consumption_artifact,
                pre_scene_spec=plan.preconditions.scene_spec,
                pre_modeling_plan=plan.preconditions.modeling_plan,
                pre_blend=plan.preconditions.blend,
                post_scene_spec=post_scene,
                post_modeling_plan=post_modeling,
                post_blend=post_blend,
                invariant_report=request.invariant_report,
                transaction_states=state_artifacts,
            )
            receipt_artifact = _publish_model(
                root,
                f"production/material_identity_split/{plan.run_id}/apply_receipt.json",
                receipt,
                artifact_id=f"{plan.run_id}-apply-receipt",
                kind="material_identity_split_apply_receipt",
            )
            if crash_after == "after_apply_receipt":
                raise RuntimeError("injected identity-split crash after ApplyReceipt")
            authority_refresh = _publish_post_apply_authority_refresh(
                root,
                plan=plan,
                request=request,
                apply_receipt_artifact=receipt_artifact,
                created_at=observed_at,
            )
            terminal = _publish_state(
                root,
                plan,
                sequence=status.latest_sequence + 7,
                previous_state=state_artifacts[-1],
                state="committed",
                plan_artifact=request.plan,
                approval_request=intent.approval_request,
                apply_intent=intent_artifact,
                approval_consumption=consumption_artifact,
                archives=archives,
                performed_actions=["apply_receipt_published", "transaction_committed"],
                allowed_next_actions=[],
                created_at=observed_at,
            )
            return MaterialIdentitySplitApplyResult(
                apply_intent=intent_artifact,
                approval_consumption=consumption_artifact,
                apply_receipt=receipt_artifact,
                geometry_continuation=authority_refresh.geometry_continuation,
                canonical_scene_inventory=authority_refresh.canonical_scene_inventory,
                canonical_build_provenance=authority_refresh.canonical_build_provenance,
                material_plan_absence=authority_refresh.material_plan_absence,
                canonical_snapshot=authority_refresh.canonical_snapshot,
                terminal_state=terminal,
            )
    except Exception:
        # Preserve the exact partial journal and bytes for the explicit recovery path.
        raise


def recover_material_identity_split(
    job_root: Path,
    *,
    run_id: str,
    crash_after: CrashPoint | None = None,
    created_at: datetime | None = None,
) -> MaterialIdentitySplitRecoveryResult:
    """Resolve a partial approved transaction to exact rollback or fail-closed recovery."""

    root = job_root.expanduser().resolve(strict=True)
    observed_at = _utc_now(created_at)
    service = MaterialIdentitySplitService(root)
    status = service.get_status(run_id)
    latest = load_material_closure_model(
        root,
        status.latest_state,
        MaterialIdentitySplitTransactionState,
    )
    if latest.state == "committed":
        raise FileExistsError("identity-split transaction is already committed")
    if latest.state == "rolled_back":
        raise FileExistsError("identity-split transaction is already rolled back")
    if latest.apply_intent is None or latest.approval_consumption is None:
        raise PermissionError("identity-split recovery has no consumed approved ApplyIntent")
    intent = _load_transaction_intent(root, latest.apply_intent)
    plan, request, _approval = _validate_apply_bindings(
        root,
        intent,
        require_current_preconditions=False,
    )
    archives = latest.archives
    if len(archives) != 3:
        raise MaterialIdentitySplitError("identity-split recovery lacks exact archives")
    technical_retry_count = _recovery_retry_count(root, run_id, latest)
    lock_owner = f"material-identity-split-recovery-{run_id}"
    rollback_artifact: ExactArtifact | None = None
    try:
        with canonical_scene_spec_write_lock(plan.job_id, lock_owner):
            apply_receipt_path = (
                root
                / "production"
                / "material_identity_split"
                / run_id
                / "apply_receipt.json"
            )
            if apply_receipt_path.is_file():
                apply_receipt_artifact = _artifact_from_path(
                    root,
                    f"production/material_identity_split/{run_id}/apply_receipt.json",
                    artifact_id=f"{run_id}-apply-receipt",
                    kind="material_identity_split_apply_receipt",
                )
                apply_receipt = load_material_closure_model(
                    root,
                    apply_receipt_artifact,
                    MaterialIdentitySplitApplyReceipt,
                )
                if (
                    apply_receipt.apply_intent != latest.apply_intent
                    or apply_receipt.approval_consumption != latest.approval_consumption
                ):
                    raise MaterialIdentitySplitError(
                        "identity-split ApplyReceipt differs from the partial transaction"
                    )
                for artifact in (
                    apply_receipt.post_scene_spec,
                    apply_receipt.post_modeling_plan,
                    apply_receipt.post_blend,
                ):
                    validate_exact_artifact(root, artifact)
                authority_refresh = _publish_post_apply_authority_refresh(
                    root,
                    plan=plan,
                    request=request,
                    apply_receipt_artifact=apply_receipt_artifact,
                    created_at=observed_at,
                )
                committed = _publish_state(
                    root,
                    plan,
                    sequence=status.latest_sequence + 1,
                    previous_state=status.latest_state,
                    state="committed",
                    plan_artifact=request.plan,
                    approval_request=intent.approval_request,
                    apply_intent=latest.apply_intent,
                    approval_consumption=latest.approval_consumption,
                    archives=archives,
                    performed_actions=[
                        "existing_apply_receipt_replayed",
                        "transaction_committed",
                    ],
                    allowed_next_actions=[],
                    created_at=observed_at,
                    technical_retry_count=technical_retry_count,
                )
                recovery = MaterialIdentitySplitRecoveryReceipt(
                    **_identity_kwargs(plan, observed_at),
                    receipt_id=f"{run_id}-recovery-{status.latest_sequence + 1:04d}",
                    transaction_id=run_id,
                    apply_intent=latest.apply_intent,
                    approval_consumption=latest.approval_consumption,
                    starting_state=status.latest_state,
                    terminal_state=committed,
                    outcome="committed",
                    technical_retry_count=technical_retry_count,
                )
                recovery_artifact = _publish_model(
                    root,
                    (
                        f"production/material_identity_split/{run_id}/recoveries/"
                        f"{status.latest_sequence + 1:04d}.json"
                    ),
                    recovery,
                    artifact_id=recovery.receipt_id,
                    kind="material_identity_split_recovery_receipt",
                )
                return MaterialIdentitySplitRecoveryResult(
                    recovery_receipt=recovery_artifact,
                    rollback_receipt=None,
                    geometry_continuation=authority_refresh.geometry_continuation,
                    terminal_state=committed,
                    outcome="committed",
                )
            rollback_started = _publish_state(
                root,
                plan,
                sequence=status.latest_sequence + 1,
                previous_state=status.latest_state,
                state="rollback_started",
                plan_artifact=request.plan,
                approval_request=intent.approval_request,
                apply_intent=latest.apply_intent,
                approval_consumption=latest.approval_consumption,
                archives=archives,
                performed_actions=["rollback_started"],
                allowed_next_actions=["restore_exact_archives"],
                created_at=observed_at,
                technical_retry_count=technical_retry_count,
            )
            if crash_after == "during_rollback":
                _atomic_replace_exact(
                    root / "analysis" / "scene_spec.json",
                    validate_exact_artifact(root, archives[0]),
                )
                raise RuntimeError("injected identity-split crash during rollback")
            _restore_archives(root, archives)
            restored = (
                _artifact_from_path(
                    root,
                    "analysis/scene_spec.json",
                    artifact_id=f"{run_id}-restored-scene-spec",
                    kind="scene_spec",
                ),
                _artifact_from_path(
                    root,
                    "analysis/modeling_plan.json",
                    artifact_id=f"{run_id}-restored-modeling-plan",
                    kind="modeling_plan",
                ),
                _artifact_from_path(
                    root,
                    "blender/scene.blend",
                    artifact_id=f"{run_id}-restored-blend",
                    kind="canonical_blend",
                    media_type="application/x-blender",
                ),
            )
            if tuple(item.sha256 for item in restored) != tuple(
                item.sha256
                for item in (
                    plan.preconditions.scene_spec,
                    plan.preconditions.modeling_plan,
                    plan.preconditions.blend,
                )
            ):
                raise MaterialIdentitySplitError(
                    "identity-split rollback did not restore exact bytes"
                )
            rolled_back = _publish_state(
                root,
                plan,
                sequence=status.latest_sequence + 2,
                previous_state=rollback_started,
                state="rolled_back",
                plan_artifact=request.plan,
                approval_request=intent.approval_request,
                apply_intent=latest.apply_intent,
                approval_consumption=latest.approval_consumption,
                archives=archives,
                performed_actions=["exact_archives_restored"],
                allowed_next_actions=[],
                created_at=observed_at,
                technical_retry_count=technical_retry_count,
            )
            rollback = MaterialIdentitySplitRollbackReceipt(
                **_identity_kwargs(plan, observed_at),
                receipt_id=f"{run_id}-rollback-receipt",
                transaction_id=run_id,
                apply_intent=latest.apply_intent,
                approval_consumption=latest.approval_consumption,
                archived_scene_spec=archives[0],
                archived_modeling_plan=archives[1],
                archived_blend=archives[2],
                restored_scene_spec=restored[0],
                restored_modeling_plan=restored[1],
                restored_blend=restored[2],
                failure_state=status.latest_state,
                rollback_state=rolled_back,
            )
            rollback_artifact = _publish_model(
                root,
                f"production/material_identity_split/{run_id}/rollback_receipt.json",
                rollback,
                artifact_id=f"{run_id}-rollback-receipt",
                kind="material_identity_split_rollback_receipt",
            )
            recovery = MaterialIdentitySplitRecoveryReceipt(
                **_identity_kwargs(plan, observed_at),
                receipt_id=f"{run_id}-recovery-{status.latest_sequence + 2:04d}",
                transaction_id=run_id,
                apply_intent=latest.apply_intent,
                approval_consumption=latest.approval_consumption,
                starting_state=status.latest_state,
                terminal_state=rolled_back,
                outcome="rolled_back",
                technical_retry_count=technical_retry_count,
            )
            recovery_artifact = _publish_model(
                root,
                (
                    f"production/material_identity_split/{run_id}/recoveries/"
                    f"{status.latest_sequence + 2:04d}.json"
                ),
                recovery,
                artifact_id=f"{run_id}-recovery-receipt",
                kind="material_identity_split_recovery_receipt",
            )
            return MaterialIdentitySplitRecoveryResult(
                recovery_receipt=recovery_artifact,
                rollback_receipt=rollback_artifact,
                geometry_continuation=None,
                terminal_state=rolled_back,
                outcome="rolled_back",
            )
    except Exception as exc:
        if rollback_artifact is not None:
            raise
        refreshed = service.get_status(run_id)
        if refreshed.status == "rolled_back":
            raise
        blocked = _publish_state(
            root,
            plan,
            sequence=refreshed.latest_sequence + 1,
            previous_state=refreshed.latest_state,
            state="recovery_required",
            plan_artifact=request.plan,
            approval_request=intent.approval_request,
            apply_intent=latest.apply_intent,
            approval_consumption=latest.approval_consumption,
            archives=archives,
            performed_actions=["automatic_recovery_failed"],
            allowed_next_actions=["retry_exact_recovery_once"],
            created_at=observed_at,
            blocked_reason=str(exc),
            technical_retry_count=technical_retry_count,
        )
        recovery = MaterialIdentitySplitRecoveryReceipt(
            **_identity_kwargs(plan, observed_at),
            receipt_id=f"{run_id}-recovery-{refreshed.latest_sequence + 1:04d}",
            transaction_id=run_id,
            apply_intent=latest.apply_intent,
            approval_consumption=latest.approval_consumption,
            starting_state=refreshed.latest_state,
            terminal_state=blocked,
            outcome="recovery_required",
            technical_retry_count=technical_retry_count,
        )
        recovery_artifact = _publish_model(
            root,
            (
                f"production/material_identity_split/{run_id}/recoveries/"
                f"{refreshed.latest_sequence + 1:04d}.json"
            ),
            recovery,
            artifact_id=f"{run_id}-recovery-receipt",
            kind="material_identity_split_recovery_receipt",
        )
        return MaterialIdentitySplitRecoveryResult(
            recovery_receipt=recovery_artifact,
            rollback_receipt=None,
            geometry_continuation=None,
            terminal_state=blocked,
            outcome="recovery_required",
        )
