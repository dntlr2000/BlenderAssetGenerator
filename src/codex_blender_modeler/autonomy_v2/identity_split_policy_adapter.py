"""Additive AQ policy-authority adapter for guarded material identity splits."""

from __future__ import annotations

import os
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from ..blender_artifacts import native_io_path, stable_json_digest
from ..material_closure.incident_service import load_material_closure_model
from ..material_closure.models import ExactArtifact
from ..material_identity_split import (
    MaterialIdentitySplitApprovalRequest,
    MaterialIdentitySplitPlan,
    MaterialIdentitySplitPolicyApplyIntent,
    MaterialIdentitySplitService,
    apply_material_identity_split,
    recover_material_identity_split,
)
from ..workspace import job_dir
from .approval_models import ApprovalArtifact, AQV2PolicyDecisionReceipt
from .approval_policy_service import (
    _approval_root,
    _decision_receipt_from_path,
    approval_artifact_for,
    publish_policy_decision_receipt,
    validate_routine_policy_authorization,
)

_PRODUCER = "codex_blender_modeler.autonomy_v2.identity_split_policy_adapter"


def _exact_artifact(artifact: ApprovalArtifact) -> ExactArtifact:
    """Project one exact AQ artifact into the identity-split artifact vocabulary."""

    return ExactArtifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
        media_type="application/json",
    )


def _result_payload(result: object) -> dict[str, object]:
    """Project one frozen transaction result dataclass into JSON-ready evidence."""

    payload: dict[str, object] = {}
    for field in fields(result):  # type: ignore[arg-type]
        value = getattr(result, field.name)
        payload[field.name] = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )
    return payload


def _existing_policy_receipt(
    root: Path,
    session_id: str,
    policy_authorization: ApprovalArtifact,
) -> tuple[AQV2PolicyDecisionReceipt, ApprovalArtifact] | None:
    """Replay an already-published AQ receipt for crash-safe adapter finalization."""

    decisions_root = _approval_root(root, session_id) / "decisions"
    if not os.path.isdir(native_io_path(decisions_root)):
        return None
    for path in sorted(decisions_root.glob("*.json")):
        receipt, artifact = _decision_receipt_from_path(root, path)
        if receipt.policy_authorization == policy_authorization:
            return receipt, artifact
    return None


def _publish_or_adopt_policy_receipt(
    job_id: str,
    session_id: str,
    *,
    policy_authorization: ApprovalArtifact,
    canonical_after: ExactArtifact,
    action_result: ExactArtifact,
    outcome: str,
) -> dict[str, object]:
    """Publish one AQ decision or adopt the exact existing crash-complete receipt."""

    root = job_dir(job_id)
    existing = _existing_policy_receipt(root, session_id, policy_authorization)
    if existing is not None:
        if existing[0].outcome != outcome:
            raise PermissionError("existing identity-split policy receipt has another outcome")
        return {
            "status": "existing",
            "receipt": existing[0].model_dump(mode="json"),
            "receipt_artifact": existing[1].model_dump(mode="json"),
            "is_user_approval": False,
        }
    return publish_policy_decision_receipt(
        job_id,
        session_id,
        policy_authorization_path=policy_authorization.path,
        canonical_snapshot_after_path=canonical_after.path,
        canonical_snapshot_after_kind=canonical_after.kind,
        outcome=outcome,
        action_result_path=action_result.path,
        action_result_kind=action_result.kind,
        allow_disabled_experimental=True,
    )


def apply_policy_authorized_material_identity_split(
    job_id: str,
    session_id: str,
    *,
    approval_request_path: str | Path,
    policy_authorization_path: str | Path,
    canonical_scene_inventory_path: str | Path,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Apply one exact bounded split without synthesizing specialized user approval."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ identity-split policy adapter remains disabled_experimental")
    root = job_dir(job_id).expanduser().resolve(strict=True)
    request_path = (
        Path(approval_request_path)
        if Path(approval_request_path).is_absolute()
        else root / approval_request_path
    )
    request_artifact = approval_artifact_for(
        root,
        request_path,
        artifact_id=request_path.stem,
        kind="material_identity_split_approval_request",
    )
    with open(native_io_path(request_path), "rb") as handle:
        request = MaterialIdentitySplitApprovalRequest.model_validate_json(handle.read())
    plan = load_material_closure_model(root, request.plan, MaterialIdentitySplitPlan)
    MaterialIdentitySplitService(root).validate_plan_current(plan)
    replay = validate_routine_policy_authorization(
        job_id,
        session_id,
        policy_authorization_path=policy_authorization_path,
        expected_gate_kind="bounded_material_identity_split",
        expected_target_path=request_artifact.path,
    )
    authorization = replay["authorization"]
    if not isinstance(authorization, dict):
        raise ValueError("policy authorization replay omitted its strict payload")
    policy_artifact = ApprovalArtifact.model_validate(replay["authorization_artifact"])
    observed_at = created_at or datetime.now(UTC)
    assignment_digest = stable_json_digest(
        [item.model_dump(mode="json") for item in request.changed_assignments]
    )
    intent = MaterialIdentitySplitPolicyApplyIntent(
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        dispatch_id=request.dispatch_id,
        session_id=session_id,
        run_id=request.run_id,
        producer=_PRODUCER,
        created_at=observed_at,
        intent_id=f"{request.run_id}-policy-intent",
        transaction_id=request.run_id,
        policy_authorization=_exact_artifact(policy_artifact),
        approval_request=_exact_artifact(request_artifact),
        plan=request.plan,
        candidate_scene_spec=request.candidate_scene_spec,
        candidate_modeling_plan=request.candidate_modeling_plan,
        scene_diff_allowlist=request.scene_diff_allowlist,
        modeling_plan_diff_report=request.modeling_plan_diff_report,
        preapproval_report=request.preapproval_report,
        shadow_build_receipt=request.shadow_build_receipt,
        invariant_report=request.invariant_report,
        preconditions=request.preconditions,
        expected_scene_spec_sha256=request.candidate_scene_spec.sha256,
        expected_modeling_plan_sha256=request.candidate_modeling_plan.sha256,
        expected_material_assignment_sha256=assignment_digest,
    )
    inventory_path = (
        Path(canonical_scene_inventory_path)
        if Path(canonical_scene_inventory_path).is_absolute()
        else root / canonical_scene_inventory_path
    )
    inventory = _exact_artifact(
        approval_artifact_for(
            root,
            inventory_path,
            artifact_id=f"{request.run_id}-canonical-scene-inventory",
            kind="scene_inventory",
        )
    )
    result = apply_material_identity_split(
        root,
        intent=intent,
        canonical_scene_inventory=inventory,
        created_at=observed_at,
    )
    post_scene = approval_artifact_for(
        root,
        root / "analysis" / "scene_spec.json",
        artifact_id=f"{request.run_id}-post-scene-spec",
        kind="scene_spec",
    )
    policy_receipt = _publish_or_adopt_policy_receipt(
        job_id,
        session_id,
        policy_authorization=policy_artifact,
        canonical_after=_exact_artifact(post_scene),
        action_result=result.apply_receipt,
        outcome="applied",
    )
    return {
        "status": "committed",
        "transaction": _result_payload(result),
        "policy_decision": policy_receipt,
        "policy_authorization_is_user_approval": False,
        "specialized_user_approval_created": False,
        "geometry_uv_changed": False,
        "destination_project_write": False,
    }


def recover_policy_authorized_material_identity_split(
    job_id: str,
    session_id: str,
    *,
    run_id: str,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Recover one partial policy split and consume AQ authority at its exact outcome."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ identity-split policy adapter remains disabled_experimental")
    root = job_dir(job_id).expanduser().resolve(strict=True)
    intent_paths = sorted(
        (root / "production" / "material_identity_split" / run_id / "intents").glob(
            "*.json"
        )
    )
    policy_intents: list[MaterialIdentitySplitPolicyApplyIntent] = []
    for path in intent_paths:
        try:
            policy_intents.append(
                MaterialIdentitySplitPolicyApplyIntent.model_validate_json(path.read_bytes())
            )
        except ValueError:
            continue
    if len(policy_intents) != 1:
        raise ValueError("policy identity-split recovery requires one exact policy intent")
    intent = policy_intents[0]
    result = recover_material_identity_split(root, run_id=run_id)
    canonical = approval_artifact_for(
        root,
        root / "analysis" / "scene_spec.json",
        artifact_id=f"{run_id}-recovery-scene-spec",
        kind="scene_spec",
    )
    policy_artifact = ApprovalArtifact(
        artifact_id=intent.policy_authorization.artifact_id,
        kind=intent.policy_authorization.kind,
        path=intent.policy_authorization.path,
        sha256=intent.policy_authorization.sha256,
        byte_size=intent.policy_authorization.byte_size,
    )
    if result.outcome not in {"committed", "rolled_back"}:
        return {
            "status": "recovery_required",
            "transaction": _result_payload(result),
            "policy_decision": None,
            "user_approval_requested": False,
        }
    policy_receipt = _publish_or_adopt_policy_receipt(
        job_id,
        session_id,
        policy_authorization=policy_artifact,
        canonical_after=_exact_artifact(canonical),
        action_result=result.recovery_receipt,
        outcome="applied" if result.outcome == "committed" else "rolled_back",
    )
    return {
        "status": result.outcome,
        "transaction": _result_payload(result),
        "policy_decision": policy_receipt,
        "user_approval_requested": False,
        "canonical_corruption": False,
    }
