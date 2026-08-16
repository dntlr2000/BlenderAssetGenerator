"""Deterministic host policy for AQ v2 approval envelopes and routine actions."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..blender_artifacts import (
    native_io_path,
    native_json_bytes,
    publish_bytes_create_once,
    sha256_file,
    stable_json_digest,
)
from ..production.validation import ensure_contained_production_path
from ..workspace import job_dir
from .approval_models import (
    ApprovalArtifact,
    ApprovalMode,
    AQV2ApprovalBudget,
    AQV2PolicyDecisionReceipt,
    AQV2RoutineGateEligibilityReport,
    AQV2RoutinePolicyAuthorization,
    AutonomyApprovalEnvelope,
    AutonomyApprovalPolicyProfile,
    BoundedTransformationKind,
    ProviderScope,
    RoutineGateKind,
    RoutineGatePolicy,
)
from .delivery_service import validate_root_authorization_boundary_v2, validate_v2_artifact
from .models import AutonomyPlanV2, RootAuthorizationV2

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_PRODUCER = "codex_blender_modeler.autonomy_v2.approval_policy_service"
_TECHNICAL_FAILURE_CATEGORIES = frozenset(
    {
        "dependency_closure",
        "manifest_missing",
        "path_rebinding",
        "hash_projection",
        "schema_serialization",
        "completion_map_binding",
        "stale_generated_projection",
        "controller_output_packaging",
        "rollback_archive",
        "deterministic_normalization",
        "transient_controller_failure",
        "repeated_framework_failure",
    }
)
_GATE_TRANSFORMATIONS: dict[RoutineGateKind, BoundedTransformationKind | None] = {
    "geometry_candidate_promotion": "bounded_geometry_revision",
    "structural_candidate_promotion": "bounded_geometry_revision",
    "bounded_parametric_revision": "bounded_parameter_revision",
    "bounded_material_identity_split": "bounded_material_identity_split",
    "material_candidate_promotion": "bounded_material_promotion",
    "material_quality_acknowledgement": None,
    "iq_quality_acceptance": None,
    "optimization_plan_authorization": "aq_delivery_authorization",
    "package_acknowledgement": "aq_delivery_authorization",
    "review_bundle_terminal": None,
    "technical_retry": "no_visual_technical_normalization",
    "rollback": "no_visual_technical_normalization",
    "imagegen_candidate_adoption": "bounded_material_promotion",
}
_INTERACTIVE_ROUTINE_GATES = frozenset(
    {"review_bundle_terminal", "technical_retry", "rollback"}
)


def _utc_now(value: datetime | None = None) -> datetime:
    """Return one timezone-aware UTC timestamp for immutable policy evidence."""

    observed = value or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("approval policy timestamps must include a timezone offset")
    return observed.astimezone(UTC)


def _approval_root(root: Path, session_id: str) -> Path:
    """Resolve the additive approval-envelope namespace below one AQ v2 session."""

    return ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / session_id / "approval_envelope",
        must_exist=False,
    )


def _approval_artifact_from_v2(artifact: Any) -> ApprovalArtifact:
    """Convert an exact AQ v2 artifact into the frozen approval companion type."""

    return ApprovalArtifact.model_validate(artifact.model_dump(mode="python"))


def approval_artifact_for(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> ApprovalArtifact:
    """Bind one exact regular file below a job root to frozen approval evidence."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ValueError("approval artifact must be a regular file")
    byte_size = os.path.getsize(native_io_path(safe))
    if byte_size <= 0:
        raise ValueError("approval artifact must be non-empty")
    return ApprovalArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=byte_size,
    )


def validate_approval_artifact(root: Path, artifact: ApprovalArtifact) -> Path:
    """Reject missing, escaped, linked, resized, or rehashed approval evidence."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if not os.path.isfile(native_io_path(path)):
        raise ValueError(f"approval artifact is not a regular file: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"approval artifact size changed: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"approval artifact hash changed: {artifact.path}")
    return path


def _write_immutable_model(
    root: Path,
    path: Path,
    model: BaseModel,
    *,
    artifact_id: str,
    kind: str,
) -> ApprovalArtifact:
    """Create or exact-adopt deterministic companion bytes without replacing history."""

    destination = ensure_contained_production_path(root, path, must_exist=False)
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    ensure_contained_production_path(root, destination.parent, must_exist=True)
    publish_bytes_create_once(
        destination,
        native_json_bytes(model.model_dump(mode="json")),
    )
    return approval_artifact_for(
        root,
        destination,
        artifact_id=artifact_id,
        kind=kind,
    )


def _load_model(
    root: Path,
    artifact: ApprovalArtifact,
    model: type[_ModelT],
) -> _ModelT:
    """Hash-check and strict-parse one approval artifact into its declared model."""

    path = validate_approval_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model.model_validate_json(handle.read())


def _load_base_boundary(
    job_id: str,
    session_id: str,
) -> tuple[Path, AutonomyPlanV2, RootAuthorizationV2, ApprovalArtifact]:
    """Replay the unchanged AQ v2 plan and active RootAuthorizationV2 boundary."""

    root = job_dir(job_id)
    plan_path = ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / session_id / "plan.json",
        must_exist=True,
    )
    with open(native_io_path(plan_path), "rb") as handle:
        plan = AutonomyPlanV2.model_validate_json(handle.read())
    if plan.job_id != job_id or plan.session_id != session_id:
        raise ValueError("AQ v2 plan identity differs from its requested session")
    authorization, replayed_plan, _profile, _budget = (
        validate_root_authorization_boundary_v2(
            job_root=root,
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            root_authorization_artifact=plan.root_authorization,
        )
    )
    if replayed_plan != plan:
        raise ValueError("AQ v2 plan changed during approval boundary replay")
    validate_v2_artifact(root, plan.root_authorization)
    return root, plan, authorization, _approval_artifact_from_v2(plan.root_authorization)


def _policy_rules() -> list[RoutineGatePolicy]:
    """Build the complete deterministic gate registry in stable enum order."""

    rules: list[RoutineGatePolicy] = []
    for gate_kind, transformation in _GATE_TRANSFORMATIONS.items():
        allowed_modes: list[ApprovalMode] = ["autonomous", "checkpointed"]
        if gate_kind in _INTERACTIVE_ROUTINE_GATES:
            allowed_modes.append("interactive")
        rules.append(
            RoutineGatePolicy(
                gate_kind=gate_kind,
                allowed_modes=allowed_modes,
                bounded_transformation=transformation,
                limitations=[
                    "Exact current evidence is revalidated by the host before issuance.",
                    "This policy decision is never an explicit user approval.",
                ],
            )
        )
    return rules


def _default_gate_kinds(mode: ApprovalMode) -> list[RoutineGateKind]:
    """Select routine gates for a new envelope without broadening interactive behavior."""

    if mode == "interactive":
        return [
            gate_kind
            for gate_kind in _GATE_TRANSFORMATIONS
            if gate_kind in _INTERACTIVE_ROUTINE_GATES
        ]
    return list(_GATE_TRANSFORMATIONS)


def _default_transformations(
    gate_kinds: list[RoutineGateKind],
) -> list[BoundedTransformationKind]:
    """Project unique non-null transformations from the exact allowed gate list."""

    return list(
        dict.fromkeys(
            transformation
            for gate_kind in gate_kinds
            if (transformation := _GATE_TRANSFORMATIONS[gate_kind]) is not None
        )
    )


def plan_approval_envelope(
    job_id: str,
    session_id: str,
    *,
    approval_mode: ApprovalMode,
    initial_user_request_sha256: str,
    explicit_autonomy_delegation_observed: bool,
    allowed_provider_scopes: list[ProviderScope] | None = None,
    allowed_routine_gate_kinds: list[RoutineGateKind] | None = None,
    allowed_bounded_transformations: list[BoundedTransformationKind] | None = None,
    max_identity_splits: int = 4,
    expires_at: datetime | None = None,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Publish one optional envelope exactly bound to the unchanged AQ v2 root."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    if approval_mode in {"autonomous", "checkpointed"} and not (
        explicit_autonomy_delegation_observed
    ):
        raise PermissionError(
            "autonomous and checkpointed envelopes require explicit delegation"
        )
    if isinstance(max_identity_splits, bool) or not isinstance(max_identity_splits, int):
        raise TypeError("approval envelope identity split cap must be an integer")
    if not 0 <= max_identity_splits <= 8:
        raise ValueError("approval envelope identity split cap must be within [0, 8]")
    for label, values in (
        ("routine gate", allowed_routine_gate_kinds),
        ("bounded transformation", allowed_bounded_transformations),
        ("provider scope", allowed_provider_scopes),
    ):
        if values is not None and len(values) != len(set(values)):
            raise ValueError(f"approval envelope {label} values must be unique")
    root, plan, authorization, root_artifact = _load_base_boundary(job_id, session_id)
    if initial_user_request_sha256 != authorization.original_request_sha256:
        raise PermissionError("initial request hash differs from RootAuthorizationV2")
    observed_at = _utc_now(created_at)
    expiry = _utc_now(expires_at) if expires_at is not None else observed_at + timedelta(hours=24)
    if authorization.expires_at is not None and expiry > authorization.expires_at:
        raise PermissionError("approval envelope cannot outlive RootAuthorizationV2")
    gate_kinds = allowed_routine_gate_kinds or _default_gate_kinds(approval_mode)
    transformations = (
        allowed_bounded_transformations
        if allowed_bounded_transformations is not None
        else _default_transformations(gate_kinds)
    )
    unknown_transformations = {
        item
        for item in transformations
        if item not in {
            transformation
            for transformation in _GATE_TRANSFORMATIONS.values()
            if transformation is not None
        }
    }
    if unknown_transformations:
        raise ValueError("approval envelope contains unknown transformations")
    for gate_kind in gate_kinds:
        required = _GATE_TRANSFORMATIONS[gate_kind]
        if required is not None and required not in transformations:
            raise ValueError("allowed routine gate is missing its bounded transformation")
    providers = allowed_provider_scopes or ["local_only"]
    session_root = _approval_root(root, session_id)
    policy_profile = AutonomyApprovalPolicyProfile(
        contract_id=f"approval-policy-{session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "Deterministic host eligibility replaces routine prompts without changing "
            "user authority."
        ),
        profile_id=f"aqv2-approval-policy-{approval_mode}",
        supported_modes=["autonomous", "checkpointed", "interactive"],
        routine_gate_policies=_policy_rules(),
        allowed_bounded_transformations=list(_default_transformations(list(_GATE_TRANSFORMATIONS))),
        default_max_identity_splits=min(max_identity_splits, 4),
    )
    profile_artifact = _write_immutable_model(
        root,
        session_root / "policy_profile.json",
        policy_profile,
        artifact_id=policy_profile.contract_id,
        kind="autonomy-approval-policy-profile",
    )
    max_decisions = {"autonomous": 0, "checkpointed": 3, "interactive": 64}[
        approval_mode
    ]
    base_budget = _load_model_from_v2_budget(root, authorization)
    approval_budget = AQV2ApprovalBudget(
        contract_id=f"approval-budget-{session_id}-0000",
        budget_id=f"approval-budget-{session_id}-0000",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "User, policy, technical, and terminal counters are separated and capped."
        ),
        policy_profile=profile_artifact,
        approval_mode=approval_mode,
        max_additional_user_decisions=max_decisions,
        max_routine_policy_authorizations=min(base_budget.global_action_limit, 128),
        max_total_elapsed_actions=min(base_budget.global_action_limit, 128),
    )
    budget_artifact = _write_immutable_model(
        root,
        session_root / "approval_budget.json",
        approval_budget,
        artifact_id=approval_budget.contract_id,
        kind="aqv2-approval-budget",
    )
    envelope = AutonomyApprovalEnvelope(
        contract_id=f"approval-envelope-{session_id}",
        envelope_id=f"approval-envelope-{session_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "Exact eligible routine actions use policy authority while genuine decisions "
            "escalate once."
        ),
        approval_mode=approval_mode,
        policy_profile=profile_artifact,
        approval_budget=budget_artifact,
        initial_user_request_sha256=initial_user_request_sha256,
        explicit_autonomy_delegation_observed=explicit_autonomy_delegation_observed,
        allowed_routine_gate_kinds=gate_kinds,
        allowed_bounded_transformations=transformations,
        allowed_provider_scopes=providers,
        allowed_delivery_profiles=list(authorization.allowed_delivery_profiles),
        requested_delivery_profiles=list(authorization.requested_delivery_profiles),
        allow_review_bundle_terminal=(approval_mode != "interactive"),
        allow_automatic_rollback=True,
        allow_automatic_technical_retry=True,
        max_identity_splits=(
            max_identity_splits
            if "bounded_material_identity_split" in gate_kinds
            else 0
        ),
        max_material_identities_created=(
            max_identity_splits
            if "bounded_material_identity_split" in gate_kinds
            else 0
        ),
        max_controller_invocations=base_budget.controller_invocations,
        max_canonical_promotions=base_budget.canonical_promotions,
        max_blender_builds=base_budget.total_blender_builds,
        max_quality_evaluations=base_budget.total_quality_evaluations,
        max_package_runs=base_budget.delivery_runs,
        expires_at=expiry,
    )
    envelope_artifact = _write_immutable_model(
        root,
        session_root / "envelope.json",
        envelope,
        artifact_id=envelope.contract_id,
        kind="autonomy-approval-envelope",
    )
    return {
        "status": "planned",
        "profile_status": "disabled_experimental",
        "job_id": job_id,
        "session_id": session_id,
        "policy_profile": policy_profile.model_dump(mode="json"),
        "approval_budget": approval_budget.model_dump(mode="json"),
        "approval_envelope": envelope.model_dump(mode="json"),
        "artifacts": {
            "policy_profile": profile_artifact.model_dump(mode="json"),
            "approval_budget": budget_artifact.model_dump(mode="json"),
            "approval_envelope": envelope_artifact.model_dump(mode="json"),
        },
        "root_authorization_modified": False,
        "future_artifacts_user_approved": False,
        "repository_creates_codex_task": False,
        "destination_project_write": False,
    }


def _load_model_from_v2_budget(root: Path, authorization: RootAuthorizationV2):
    """Load the exact immutable AQ v2 work budget referenced by RootAuthorizationV2."""

    from .models import AutonomyBudgetV2

    path = validate_v2_artifact(root, authorization.budget)
    with open(native_io_path(path), "rb") as handle:
        return AutonomyBudgetV2.model_validate_json(handle.read())


def _load_approval_boundary(
    job_id: str,
    session_id: str,
    *,
    now: datetime | None = None,
) -> tuple[
    Path,
    AutonomyPlanV2,
    RootAuthorizationV2,
    ApprovalArtifact,
    AutonomyApprovalPolicyProfile,
    ApprovalArtifact,
    AQV2ApprovalBudget,
    ApprovalArtifact,
    AutonomyApprovalEnvelope,
    ApprovalArtifact,
]:
    """Replay the complete additive policy boundary without migrating absent evidence."""

    root, plan, authorization, root_artifact = _load_base_boundary(job_id, session_id)
    session_root = _approval_root(root, session_id)
    required_paths = (
        session_root / "policy_profile.json",
        session_root / "approval_budget.json",
        session_root / "envelope.json",
    )
    if not all(os.path.isfile(native_io_path(path)) for path in required_paths):
        raise FileNotFoundError("AQ v2 session has no complete Approval Envelope companion")
    profile_artifact = approval_artifact_for(
        root,
        required_paths[0],
        artifact_id=f"approval-policy-{session_id}",
        kind="autonomy-approval-policy-profile",
    )
    profile = _load_model(root, profile_artifact, AutonomyApprovalPolicyProfile)
    budget_artifact = approval_artifact_for(
        root,
        required_paths[1],
        artifact_id=f"approval-budget-{session_id}-0000",
        kind="aqv2-approval-budget",
    )
    budget = _load_model(root, budget_artifact, AQV2ApprovalBudget)
    envelope_artifact = approval_artifact_for(
        root,
        required_paths[2],
        artifact_id=f"approval-envelope-{session_id}",
        kind="autonomy-approval-envelope",
    )
    envelope = _load_model(root, envelope_artifact, AutonomyApprovalEnvelope)
    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    for label, evidence in (
        ("policy profile", profile),
        ("approval budget", budget),
        ("approval envelope", envelope),
    ):
        observed = (
            evidence.job_id,
            evidence.workflow_id,
            evidence.dispatch_id,
            evidence.session_id,
        )
        if observed != identity:
            raise ValueError(f"{label} identity differs from RootAuthorizationV2")
        if evidence.root_authorization != root_artifact:
            raise ValueError(f"{label} does not bind the exact RootAuthorizationV2")
    if (
        budget.policy_profile != profile_artifact
        or envelope.policy_profile != profile_artifact
        or envelope.approval_budget != budget_artifact
        or envelope.initial_user_request_sha256 != authorization.original_request_sha256
    ):
        raise ValueError("approval envelope support artifacts are stale or mismatched")
    current = _utc_now(now)
    if envelope.status != "active":
        raise PermissionError("approval envelope is not active")
    if envelope.expires_at <= current:
        raise PermissionError("approval envelope has expired")
    return (
        root,
        plan,
        authorization,
        root_artifact,
        profile,
        profile_artifact,
        budget,
        budget_artifact,
        envelope,
        envelope_artifact,
    )


def get_approval_envelope_status(job_id: str, session_id: str) -> dict[str, object]:
    """Report a valid envelope or legacy absence without creating or migrating evidence."""

    root, plan, _authorization, _root_artifact = _load_base_boundary(job_id, session_id)
    session_root = _approval_root(root, session_id)
    envelope_path = session_root / "envelope.json"
    if not os.path.isfile(native_io_path(envelope_path)):
        return {
            "status": "legacy_without_envelope",
            "job_id": job_id,
            "session_id": session_id,
            "approval_mode": None,
            "retroactive_authority": False,
            "automatic_migration": False,
            "base_plan": plan.model_dump(mode="json"),
        }
    boundary = _load_approval_boundary(job_id, session_id)
    profile, budget, envelope = boundary[4], boundary[6], boundary[8]
    current_budget, previous_receipt = _current_budget_and_receipt(
        root,
        session_id,
        budget,
        boundary[5],
        boundary[7],
        envelope,
        boundary[9],
    )
    return {
        "status": "active",
        "profile_status": profile.status,
        "job_id": job_id,
        "session_id": session_id,
        "approval_mode": envelope.approval_mode,
        "approval_envelope": envelope.model_dump(mode="json"),
        "current_budget": current_budget.model_dump(mode="json"),
        "latest_policy_receipt": (
            None if previous_receipt is None else previous_receipt.model_dump(mode="json")
        ),
        "retroactive_authority": False,
        "automatic_migration": False,
    }


def _current_budget_and_receipt(
    root: Path,
    session_id: str,
    initial_budget: AQV2ApprovalBudget,
    profile_artifact: ApprovalArtifact,
    budget_artifact: ApprovalArtifact,
    envelope: AutonomyApprovalEnvelope,
    envelope_artifact: ApprovalArtifact,
) -> tuple[AQV2ApprovalBudget, ApprovalArtifact | None]:
    """Replay all decision receipts to recover current budget and predecessor identity."""

    decisions_root = _approval_root(root, session_id) / "decisions"
    if not os.path.isdir(native_io_path(decisions_root)):
        return initial_budget, None
    current_budget = initial_budget
    previous_artifact: ApprovalArtifact | None = None
    for path in sorted(decisions_root.glob("*.json")):
        receipt, artifact = _decision_receipt_from_path(root, path)
        if (
            receipt.policy_profile != profile_artifact
            or receipt.approval_envelope != envelope_artifact
            or receipt.budget_before != current_budget
            or receipt.previous_receipt != previous_artifact
            or receipt.job_id != envelope.job_id
            or receipt.session_id != envelope.session_id
        ):
            raise ValueError("AQ policy decision receipt chain is stale or spliced")
        _validate_policy_receipt_authorization(root, receipt)
        current_budget = receipt.budget_after
        previous_artifact = artifact
    return current_budget, previous_artifact


def _decision_receipt_from_path(
    root: Path,
    path: Path,
) -> tuple[AQV2PolicyDecisionReceipt, ApprovalArtifact]:
    """Parse one ordered decision file and recover its immutable semantic artifact ID."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    with open(native_io_path(safe), "rb") as handle:
        receipt = AQV2PolicyDecisionReceipt.model_validate_json(handle.read())
    artifact = approval_artifact_for(
        root,
        safe,
        artifact_id=receipt.receipt_id,
        kind="aqv2-policy-decision-receipt",
    )
    return receipt, artifact


def _validate_policy_receipt_authorization(
    root: Path,
    receipt: AQV2PolicyDecisionReceipt,
) -> None:
    """Revalidate a receipt's exact issued authorization and eligibility report."""

    authorization = _load_model(
        root,
        receipt.policy_authorization,
        AQV2RoutinePolicyAuthorization,
    )
    eligibility = _load_model(
        root,
        receipt.eligibility_report,
        AQV2RoutineGateEligibilityReport,
    )
    if (
        authorization.eligibility_report != receipt.eligibility_report
        or authorization.gate_kind != receipt.gate_kind
        or authorization.exact_target_artifact != receipt.exact_target_artifact
        or authorization.budget_before != receipt.budget_before
        or authorization.budget_after != receipt.budget_after
        or eligibility.gate_kind != receipt.gate_kind
        or eligibility.exact_target_artifact != receipt.exact_target_artifact
        or eligibility.budget_before != receipt.budget_before
        or eligibility.budget_after != receipt.budget_after
    ):
        raise ValueError("policy receipt differs from its authorization or eligibility")


def _stable_id(prefix: str, payload: object) -> str:
    """Create a deterministic portable identifier from exact canonical input data."""

    digest = stable_json_digest(payload)
    return f"{prefix}-{digest[:24]}"


def _expected_eligibility_id(report: AQV2RoutineGateEligibilityReport) -> str:
    """Reconstruct the host-owned identifier for one exact eligibility report."""

    return _stable_id(
        "eligibility",
        {
            "job_id": report.job_id,
            "session_id": report.session_id,
            "gate_kind": report.gate_kind,
            "target": report.exact_target_artifact.model_dump(mode="json"),
            "canonical": report.current_canonical_snapshot.model_dump(mode="json"),
            "dependencies": [
                item.model_dump(mode="json") for item in report.dependency_artifacts
            ],
            "budget_before": report.budget_before.contract_id,
            "observed_at": report.created_at.isoformat(),
            "previous_receipt": (
                None
                if report.previous_receipt is None
                else report.previous_receipt.sha256
            ),
        },
    )


def _read_json_artifact(root: Path, artifact: ApprovalArtifact) -> dict[str, Any]:
    """Read one exact JSON target and require a top-level object."""

    path = validate_approval_artifact(root, artifact)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("routine policy target must be strict JSON evidence") from exc
    if not isinstance(payload, dict):
        raise ValueError("routine policy target JSON must contain one object")
    return payload


def _gate_specific_forbidden_conditions(
    root: Path,
    envelope: AutonomyApprovalEnvelope,
    gate_kind: RoutineGateKind,
    target: ApprovalArtifact,
    dependencies: list[ApprovalArtifact],
) -> list[str]:
    """Recompute typed gate prerequisites from exact target and dependency bytes."""

    if gate_kind in {"geometry_candidate_promotion", "structural_candidate_promotion"}:
        return _validate_geometry_gate_target(root, target)
    if gate_kind == "bounded_parametric_revision":
        return _validate_parametric_gate_target(root, target)
    if gate_kind == "bounded_material_identity_split":
        return _validate_identity_split_gate_target(root, target, envelope)
    if gate_kind in {"material_candidate_promotion", "material_quality_acknowledgement"}:
        return _validate_material_gate_target(root, target)
    if gate_kind == "iq_quality_acceptance":
        return _validate_quality_gate_target(root, target)
    if gate_kind == "optimization_plan_authorization":
        return _validate_optimization_gate_target(root, target, dependencies, envelope)
    if gate_kind == "package_acknowledgement":
        return _validate_package_gate_target(root, target, dependencies)
    if gate_kind == "review_bundle_terminal":
        return _validate_review_gate_target(root, target, envelope)
    if gate_kind == "technical_retry":
        return _validate_technical_retry_target(root, target)
    if gate_kind == "rollback":
        _read_json_artifact(root, target)
        return []
    if gate_kind == "imagegen_candidate_adoption":
        return _validate_imagegen_gate_target(root, target, envelope)
    return ["UNKNOWN_ROUTINE_GATE"]


def _validate_geometry_gate_target(root: Path, target: ApprovalArtifact) -> list[str]:
    """Accept only host-valid completed controller or passed geometry receipt evidence."""

    from ..production.controller_executor.models import ControllerResult
    from .candidate_validation_models import GeometryCandidateValidationReceiptV2

    try:
        result = _load_model(root, target, ControllerResult)
    except ValueError:
        try:
            receipt = _load_model(root, target, GeometryCandidateValidationReceiptV2)
        except ValueError:
            return ["GEOMETRY_TARGET_NOT_HOST_VALIDATED"]
        if receipt.status != "passed" or receipt.controller_canonical_write:
            return ["GEOMETRY_VALIDATION_NOT_PASSED"]
        return []
    if result.status != "completed" or not result.canonical_unchanged:
        return ["GEOMETRY_CONTROLLER_RESULT_NOT_COMPLETED"]
    return []


def _validate_parametric_gate_target(root: Path, target: ApprovalArtifact) -> list[str]:
    """Require an IQ needs-revision report with a bounded parametric reentry."""

    from ..integrated_quality.v02_models import IntegratedQualityReportV02

    try:
        report = _load_model(root, target, IntegratedQualityReportV02)
    except ValueError:
        return ["PARAMETRIC_TARGET_NOT_IQ_V02"]
    if report.outcome != "needs_revision":
        return ["PARAMETRIC_REVISION_NOT_REQUIRED"]
    if not any(
        item.destination == "v0.6_parametric_convergence" for item in report.reentry
    ):
        return ["PARAMETRIC_REENTRY_NOT_BOUNDED"]
    return []


def _validate_identity_split_gate_target(
    root: Path,
    target: ApprovalArtifact,
    envelope: AutonomyApprovalEnvelope,
) -> list[str]:
    """Replay exact identity-split shadow evidence and all bounded no-change invariants."""

    from ..material_closure.incident_service import load_material_closure_model
    from ..material_identity_split.models import (
        MaterialIdentitySplitApprovalRequest,
        MaterialIdentitySplitInvariantReport,
        MaterialIdentitySplitPlan,
        MaterialIdentitySplitPreapprovalReport,
        MaterialIdentitySplitShadowBuildReceipt,
    )
    from ..material_identity_split.service import MaterialIdentitySplitService

    try:
        request = _load_model(root, target, MaterialIdentitySplitApprovalRequest)
        plan = load_material_closure_model(root, request.plan, MaterialIdentitySplitPlan)
        preflight = load_material_closure_model(
            root,
            request.preapproval_report,
            MaterialIdentitySplitPreapprovalReport,
        )
        invariant = load_material_closure_model(
            root,
            request.invariant_report,
            MaterialIdentitySplitInvariantReport,
        )
        shadow = load_material_closure_model(
            root,
            request.shadow_build_receipt,
            MaterialIdentitySplitShadowBuildReceipt,
        )
        MaterialIdentitySplitService(root).validate_plan_current(plan)
    except (ValueError, FileNotFoundError, PermissionError):
        return ["IDENTITY_SPLIT_EVIDENCE_INVALID_OR_STALE"]
    clone_count = len(plan.clone_rules)
    if clone_count > envelope.max_identity_splits:
        return ["IDENTITY_SPLIT_COUNT_EXCEEDS_ENVELOPE"]
    if clone_count > envelope.max_material_identities_created:
        return ["MATERIAL_IDENTITY_COUNT_EXCEEDS_ENVELOPE"]
    invariant_flags = (
        invariant.clone_equivalence_passed,
        invariant.assignment_exclusivity_passed,
        invariant.object_ids_unchanged,
        invariant.geometry_unchanged,
        invariant.topology_unchanged,
        invariant.transforms_unchanged,
        invariant.dimensions_unchanged,
        invariant.uv_unchanged,
        invariant.reference_scope_unchanged,
        invariant.target_subject_unchanged,
        invariant.content_scope_unchanged,
        invariant.material_assignments_match_plan,
    )
    if (
        preflight.status != "passed"
        or invariant.status != "passed"
        or shadow.status != "passed"
        or not all(invariant_flags)
        or invariant.forbidden_change_count != 0
    ):
        return ["IDENTITY_SPLIT_BOUNDED_INVARIANT_FAILED"]
    return []


def _validate_material_gate_target(root: Path, target: ApprovalArtifact) -> list[str]:
    """Require complete closure, rebinding, Blender shadow, preview, and preflight evidence."""

    from ..material_closure.incident_service import load_material_closure_model
    from ..material_closure.models import (
        MaterialDependencyClosureReceipt,
        MaterialGraphRebindingReceipt,
        MaterialNeutralPreviewManifest,
        MaterialPromotionPreflightReport,
        MaterialShadowCompileReceipt,
    )
    try:
        report = _load_model(root, target, MaterialPromotionPreflightReport)
        closure = load_material_closure_model(
            root,
            report.closure_receipt,
            MaterialDependencyClosureReceipt,
        )
        rebind = load_material_closure_model(
            root,
            report.graph_rebinding_receipt,
            MaterialGraphRebindingReceipt,
        )
        shadow = load_material_closure_model(
            root,
            report.shadow_compile_receipt,
            MaterialShadowCompileReceipt,
        )
        preview = load_material_closure_model(
            root,
            report.neutral_preview_manifest,
            MaterialNeutralPreviewManifest,
        )
    except (ValueError, FileNotFoundError):
        return ["MATERIAL_PREFLIGHT_EVIDENCE_INVALID_OR_STALE"]
    if (
        report.status != "passed"
        or closure.status != "passed"
        or rebind.status != "passed"
        or shadow.status != "passed"
        or not preview.preview_image.path
        or any(item.status == "failed" for item in report.checks)
    ):
        return ["MATERIAL_PREFLIGHT_PREREQUISITE_FAILED"]
    return []


def _validate_quality_gate_target(root: Path, target: ApprovalArtifact) -> list[str]:
    """Require an IQ 0.2 pass with no failed required hard gate."""

    from ..integrated_quality.v02_models import IntegratedQualityReportV02

    try:
        report = _load_model(root, target, IntegratedQualityReportV02)
    except ValueError:
        return ["QUALITY_TARGET_NOT_IQ_V02"]
    if report.outcome != "passed" or not report.quality_accepted:
        return ["INTEGRATED_QUALITY_NOT_ACCEPTED"]
    if any(gate.required and gate.status != "passed" for gate in report.hard_gates):
        return ["INTEGRATED_QUALITY_REQUIRED_GATE_NOT_PASSED"]
    return []


def _validate_optimization_gate_target(
    root: Path,
    target: ApprovalArtifact,
    dependencies: list[ApprovalArtifact],
    envelope: AutonomyApprovalEnvelope,
) -> list[str]:
    """Require one draft V0.7 plan for an initially requested delivery and exact freeze."""

    from ..optimization.models import OptimizationPlan
    from .models import QualityApprovedSourceFreeze

    try:
        plan = _load_model(root, target, OptimizationPlan)
    except ValueError:
        return ["OPTIMIZATION_TARGET_NOT_V07_PLAN"]
    if plan.status != "draft":
        return ["OPTIMIZATION_PLAN_NOT_DRAFT"]
    delivery = {
        "portable_gltf": "portable_gltf",
        "fbx_interchange": "portable_fbx",
    }.get(plan.profile_id)
    if delivery is None or delivery not in envelope.requested_delivery_profiles:
        return ["OPTIMIZATION_DELIVERY_NOT_INITIALLY_REQUESTED"]
    freeze_dependencies = []
    for artifact in dependencies:
        try:
            freeze_dependencies.append(
                _load_model(root, artifact, QualityApprovedSourceFreeze)
            )
        except ValueError:
            continue
    if len(freeze_dependencies) != 1:
        return ["OPTIMIZATION_REQUIRES_ONE_QUALITY_SOURCE_FREEZE"]
    if plan.source.source_fingerprint != freeze_dependencies[0].v07_source_fingerprint:
        return ["OPTIMIZATION_SOURCE_FREEZE_MISMATCH"]
    return []


def _validate_package_gate_target(
    root: Path,
    target: ApprovalArtifact,
    dependencies: list[ApprovalArtifact],
) -> list[str]:
    """Require one complete immutable package and one passed clean-import validation."""

    from ..packaging.models import ExportPackageManifest, RoundTripValidation

    try:
        package = _load_model(root, target, ExportPackageManifest)
    except ValueError:
        return ["PACKAGE_TARGET_NOT_COMPLETE_MANIFEST"]
    if package.status != "complete":
        return ["PACKAGE_MANIFEST_NOT_COMPLETE"]
    roundtrips = []
    for artifact in dependencies:
        try:
            roundtrips.append(
                _load_model(root, artifact, RoundTripValidation)
            )
        except ValueError:
            continue
    if len(roundtrips) != 1 or roundtrips[0].status != "passed":
        return ["PACKAGE_CLEAN_IMPORT_NOT_PASSED"]
    if roundtrips[0].package_id != package.package_id:
        return ["PACKAGE_ROUNDTRIP_IDENTITY_MISMATCH"]
    return []


def _validate_review_gate_target(
    root: Path,
    target: ApprovalArtifact,
    envelope: AutonomyApprovalEnvelope,
) -> list[str]:
    """Require a strict non-production review bundle and explicit envelope permission."""

    from .models import DeliveryTerminalV2, QualityReviewBundleV2

    if not envelope.allow_review_bundle_terminal:
        return ["REVIEW_BUNDLE_TERMINAL_NOT_ALLOWED"]
    try:
        bundle = _load_model(root, target, QualityReviewBundleV2)
    except ValueError:
        try:
            terminal = _load_model(root, target, DeliveryTerminalV2)
        except ValueError:
            return ["REVIEW_TARGET_NOT_NONPRODUCTION_TERMINAL"]
        if terminal.outcome != "review_only" or any(
            item.production_ready or item.status != "review_only"
            for item in terminal.results
        ):
            return ["REVIEW_DELIVERY_TERMINAL_CLAIMS_PRODUCTION"]
        return []
    if bundle.production_ready or bundle.destination_handoff_eligible:
        return ["REVIEW_BUNDLE_CLAIMS_PRODUCTION"]
    return []


def _validate_technical_retry_target(root: Path, target: ApprovalArtifact) -> list[str]:
    """Accept one retryable transient controller failure, never a forbidden framework retry."""

    from ..material_closure.models import MaterialFrameworkFailureReport
    from ..production.controller_executor.models import ControllerResult

    try:
        result = _load_model(root, target, ControllerResult)
    except ValueError:
        try:
            failure = _load_model(root, target, MaterialFrameworkFailureReport)
        except ValueError:
            return ["TECHNICAL_RETRY_TARGET_NOT_HOST_FAILURE"]
        if failure.existing_retry_execution_forbidden:
            return ["EXISTING_TECHNICAL_RETRY_FORBIDDEN"]
        return []
    if result.status not in {"timeout", "failed"} or not result.retryable:
        return ["CONTROLLER_FAILURE_NOT_TRANSIENT_RETRYABLE"]
    if not result.canonical_unchanged:
        return ["CONTROLLER_FAILURE_CHANGED_CANONICAL"]
    return []


def _technical_retry_already_consumed(
    root: Path,
    session_id: str,
    target: ApprovalArtifact,
) -> bool:
    """Reject a second system retry for the same exact transient controller result."""

    decisions_root = _approval_root(root, session_id) / "decisions"
    if not os.path.isdir(native_io_path(decisions_root)):
        return False
    for path in sorted(decisions_root.glob("*.json")):
        receipt, _artifact = _decision_receipt_from_path(root, path)
        if (
            receipt.gate_kind == "technical_retry"
            and receipt.exact_target_artifact.sha256 == target.sha256
        ):
            return True
    return False


def _validate_imagegen_gate_target(
    root: Path,
    target: ApprovalArtifact,
    envelope: AutonomyApprovalEnvelope,
) -> list[str]:
    """Require explicit initial provider scope and a strict local-only adoption contract."""

    from ..codex_imagegen.models import ImageToMaterialAdoption

    if "codex_builtin_imagegen" not in envelope.allowed_provider_scopes:
        return ["IMAGEGEN_PROVIDER_SCOPE_NOT_AUTHORIZED"]
    try:
        adoption = _load_model(root, target, ImageToMaterialAdoption)
    except ValueError:
        return ["IMAGEGEN_TARGET_NOT_ADOPTION_CONTRACT"]
    if adoption.canonical_write_performed or adoption.destination_write_performed:
        return ["IMAGEGEN_ADOPTION_EXCEEDS_STAGING_SCOPE"]
    return []


def _budget_after_gate(
    budget: AQV2ApprovalBudget,
    gate_kind: RoutineGateKind,
    *,
    contract_suffix: str,
    created_at: datetime,
) -> AQV2ApprovalBudget:
    """Project exactly one routine decision and its gate-specific execution counter."""

    updates: dict[str, object] = {
        "contract_id": f"approval-budget-{budget.session_id}-{contract_suffix}",
        "budget_id": f"approval-budget-{budget.session_id}-{contract_suffix}",
        "created_at": created_at,
        "routine_policy_authorizations": budget.routine_policy_authorizations + 1,
        "total_elapsed_actions": budget.total_elapsed_actions + 1,
    }
    if gate_kind in {
        "geometry_candidate_promotion",
        "structural_candidate_promotion",
        "bounded_material_identity_split",
        "material_candidate_promotion",
    }:
        updates["canonical_promotions"] = budget.canonical_promotions + 1
    if gate_kind == "technical_retry":
        updates["technical_policy_repairs"] = budget.technical_policy_repairs + 1
        updates["controller_invocations"] = budget.controller_invocations + 1
    if gate_kind == "rollback":
        updates["rollbacks"] = budget.rollbacks + 1
    if gate_kind == "iq_quality_acceptance":
        updates["quality_evaluations"] = budget.quality_evaluations + 1
    if gate_kind == "review_bundle_terminal":
        updates["quality_terminals"] = budget.quality_terminals + 1
    if gate_kind == "optimization_plan_authorization":
        updates["delivery_runs"] = budget.delivery_runs + 1
    if gate_kind == "package_acknowledgement":
        updates["delivery_terminals"] = budget.delivery_terminals + 1
    if gate_kind == "imagegen_candidate_adoption":
        updates["imagegen_generations"] = budget.imagegen_generations + 1
    return AQV2ApprovalBudget.model_validate(
        budget.model_copy(update=updates).model_dump(mode="python")
    )


def _envelope_budget_forbidden_conditions(
    envelope: AutonomyApprovalEnvelope,
    budget_after: AQV2ApprovalBudget,
    gate_kind: RoutineGateKind,
) -> list[str]:
    """Compare one projected action against every immutable envelope hard cap."""

    conditions: list[str] = []
    if budget_after.controller_invocations > envelope.max_controller_invocations:
        conditions.append("CONTROLLER_INVOCATION_BUDGET_EXCEEDED")
    if budget_after.canonical_promotions > envelope.max_canonical_promotions:
        conditions.append("CANONICAL_PROMOTION_BUDGET_EXCEEDED")
    if budget_after.blender_builds > envelope.max_blender_builds:
        conditions.append("BLENDER_BUILD_BUDGET_EXCEEDED")
    if budget_after.quality_evaluations > envelope.max_quality_evaluations:
        conditions.append("QUALITY_EVALUATION_BUDGET_EXCEEDED")
    if budget_after.delivery_runs > envelope.max_package_runs:
        conditions.append("PACKAGE_RUN_BUDGET_EXCEEDED")
    if gate_kind == "rollback" and not envelope.allow_automatic_rollback:
        conditions.append("AUTOMATIC_ROLLBACK_NOT_ALLOWED")
    if gate_kind == "technical_retry" and not envelope.allow_automatic_technical_retry:
        conditions.append("AUTOMATIC_TECHNICAL_RETRY_NOT_ALLOWED")
    return conditions


def evaluate_routine_gate_eligibility(
    job_id: str,
    session_id: str,
    *,
    gate_kind: RoutineGateKind,
    exact_target_path: str | Path,
    exact_target_kind: str,
    current_canonical_snapshot_path: str | Path,
    current_canonical_snapshot_kind: str,
    dependency_paths: list[str | Path] | None = None,
    dependency_kinds: list[str] | None = None,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Publish one host-recomputed eligibility report without accepting a caller verdict."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    boundary = _load_approval_boundary(job_id, session_id)
    (
        root,
        plan,
        _authorization,
        root_artifact,
        profile,
        profile_artifact,
        initial_budget,
        budget_artifact,
        envelope,
        envelope_artifact,
    ) = boundary
    if gate_kind not in envelope.allowed_routine_gate_kinds:
        raise PermissionError("routine gate is outside the approval envelope")
    rule = next(item for item in profile.routine_gate_policies if item.gate_kind == gate_kind)
    if envelope.approval_mode not in rule.allowed_modes:
        raise PermissionError("routine gate is not enabled for this approval mode")
    if (
        rule.bounded_transformation is not None
        and rule.bounded_transformation not in envelope.allowed_bounded_transformations
    ):
        raise PermissionError("routine gate transformation is outside the envelope")
    dependency_paths = dependency_paths or []
    dependency_kinds = dependency_kinds or []
    if len(dependency_paths) != len(dependency_kinds):
        raise ValueError("dependency paths and kinds must have equal length")
    target_path = (
        Path(exact_target_path)
        if Path(exact_target_path).is_absolute()
        else root / exact_target_path
    )
    target = approval_artifact_for(
        root,
        target_path,
        artifact_id=_stable_id("target", str(exact_target_path)),
        kind=exact_target_kind,
    )
    canonical = approval_artifact_for(
        root,
        (
            Path(current_canonical_snapshot_path)
            if Path(current_canonical_snapshot_path).is_absolute()
            else root / current_canonical_snapshot_path
        ),
        artifact_id=_stable_id("canonical", str(current_canonical_snapshot_path)),
        kind=current_canonical_snapshot_kind,
    )
    dependencies = [
        approval_artifact_for(
            root,
            Path(path) if Path(path).is_absolute() else root / path,
            artifact_id=_stable_id("dependency", str(path)),
            kind=kind,
        )
        for path, kind in zip(dependency_paths, dependency_kinds, strict=True)
    ]
    if len({item.path for item in dependencies}) != len(dependencies):
        raise ValueError("routine gate dependency paths must be unique")
    current_budget, previous_receipt = _current_budget_and_receipt(
        root,
        session_id,
        initial_budget,
        profile_artifact,
        budget_artifact,
        envelope,
        envelope_artifact,
    )
    observed_at = _utc_now(created_at)
    suffix = f"{current_budget.routine_policy_authorizations + 1:04d}"
    budget_after = _budget_after_gate(
        current_budget,
        gate_kind,
        contract_suffix=suffix,
        created_at=observed_at,
    )
    forbidden = _envelope_budget_forbidden_conditions(
        envelope,
        budget_after,
        gate_kind,
    )
    forbidden.extend(
        _gate_specific_forbidden_conditions(
            root,
            envelope,
            gate_kind,
            target,
            dependencies,
        )
    )
    if gate_kind == "technical_retry" and _technical_retry_already_consumed(
        root,
        session_id,
        target,
    ):
        forbidden.append("TRANSIENT_CONTROLLER_RETRY_ALREADY_CONSUMED")
    forbidden = list(dict.fromkeys(forbidden))
    eligibility = "passed" if not forbidden else "failed"
    reasons = (
        [
            "Exact target and canonical bytes are current.",
            "RootAuthorizationV2, envelope, profile, and budget bindings passed.",
            "The deterministic host gate reported no forbidden condition.",
        ]
        if eligibility == "passed"
        else [f"Host policy rejected routine action: {item}" for item in forbidden]
    )
    report_payload = {
        "job_id": job_id,
        "session_id": session_id,
        "gate_kind": gate_kind,
        "target": target.model_dump(mode="json"),
        "canonical": canonical.model_dump(mode="json"),
        "dependencies": [item.model_dump(mode="json") for item in dependencies],
        "budget_before": current_budget.contract_id,
        "observed_at": observed_at.isoformat(),
        "previous_receipt": (
            None if previous_receipt is None else previous_receipt.sha256
        ),
    }
    report_id = _stable_id("eligibility", report_payload)
    report = AQV2RoutineGateEligibilityReport(
        contract_id=report_id,
        report_id=report_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "Host eligibility prevents routine prompts without claiming a user decision."
        ),
        policy_profile=profile_artifact,
        approval_envelope=envelope_artifact,
        approval_budget=budget_artifact,
        gate_kind=gate_kind,
        bounded_transformation=rule.bounded_transformation,
        exact_target_artifact=target,
        current_canonical_snapshot=canonical,
        dependency_artifacts=dependencies,
        budget_before=current_budget,
        budget_after=budget_after,
        eligibility=eligibility,
        decision_reasons=reasons,
        forbidden_conditions=forbidden,
        previous_receipt=previous_receipt,
    )
    if report.report_id != _expected_eligibility_id(report):
        raise RuntimeError("host eligibility identifier projection is inconsistent")
    report_artifact = _write_immutable_model(
        root,
        _approval_root(root, session_id) / "eligibility" / f"{report_id}.json",
        report,
        artifact_id=report_id,
        kind="aqv2-routine-gate-eligibility-report",
    )
    return {
        "eligibility": eligibility,
        "report": report.model_dump(mode="json"),
        "report_artifact": report_artifact.model_dump(mode="json"),
        "user_approval_created": False,
        "controller_determined_eligibility": False,
    }


def _validate_current_eligibility(
    root: Path,
    session_id: str,
    report: AQV2RoutineGateEligibilityReport,
    *,
    profile_artifact: ApprovalArtifact,
    budget_artifact: ApprovalArtifact,
    envelope: AutonomyApprovalEnvelope,
    envelope_artifact: ApprovalArtifact,
    current_budget: AQV2ApprovalBudget,
    previous_receipt: ApprovalArtifact | None,
) -> None:
    """Recompute a persisted eligibility report immediately before authorization."""

    for artifact in [
        report.exact_target_artifact,
        report.current_canonical_snapshot,
        *report.dependency_artifacts,
    ]:
        validate_approval_artifact(root, artifact)
    if (
        report.job_id != envelope.job_id
        or report.workflow_id != envelope.workflow_id
        or report.dispatch_id != envelope.dispatch_id
        or report.session_id != envelope.session_id
        or report.root_authorization != envelope.root_authorization
        or report.policy_profile != profile_artifact
        or report.approval_envelope != envelope_artifact
        or report.approval_budget != budget_artifact
        or report.gate_kind not in envelope.allowed_routine_gate_kinds
        or report.budget_before != current_budget
        or report.previous_receipt != previous_receipt
    ):
        raise PermissionError("routine eligibility report is stale")
    rule = next(
        item
        for item in _load_model(
            root,
            profile_artifact,
            AutonomyApprovalPolicyProfile,
        ).routine_gate_policies
        if item.gate_kind == report.gate_kind
    )
    if report.bounded_transformation != rule.bounded_transformation:
        raise PermissionError("routine eligibility transformation differs from host policy")
    expected_budget = _budget_after_gate(
        current_budget,
        report.gate_kind,
        contract_suffix=f"{current_budget.routine_policy_authorizations + 1:04d}",
        created_at=report.created_at,
    )
    if report.budget_after != expected_budget:
        raise PermissionError("routine eligibility budget projection differs from host policy")
    expected_forbidden = _envelope_budget_forbidden_conditions(
        envelope,
        report.budget_after,
        report.gate_kind,
    )
    expected_forbidden.extend(
        _gate_specific_forbidden_conditions(
            root,
            envelope,
            report.gate_kind,
            report.exact_target_artifact,
            report.dependency_artifacts,
        )
    )
    expected_forbidden = list(dict.fromkeys(expected_forbidden))
    if (
        report.eligibility != ("passed" if not expected_forbidden else "failed")
        or report.forbidden_conditions != expected_forbidden
    ):
        raise PermissionError("routine eligibility no longer matches host policy")


def authorize_routine_gate(
    job_id: str,
    session_id: str,
    *,
    eligibility_report_path: str | Path,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Issue one exact single-use policy authorization only for current passed eligibility."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    boundary = _load_approval_boundary(job_id, session_id)
    (
        root,
        plan,
        _root_authorization,
        root_artifact,
        _profile,
        profile_artifact,
        initial_budget,
        budget_artifact,
        envelope,
        envelope_artifact,
    ) = boundary
    path = (
        Path(eligibility_report_path)
        if Path(eligibility_report_path).is_absolute()
        else root / eligibility_report_path
    )
    report_artifact = approval_artifact_for(
        root,
        path,
        artifact_id=Path(path).stem,
        kind="aqv2-routine-gate-eligibility-report",
    )
    report = _load_model(root, report_artifact, AQV2RoutineGateEligibilityReport)
    expected_report_path = (
        _approval_root(root, session_id)
        / "eligibility"
        / f"{report.report_id}.json"
    )
    if (
        path.resolve() != expected_report_path.resolve()
        or report.report_id != _expected_eligibility_id(report)
        or report.contract_id != report.report_id
    ):
        raise PermissionError("eligibility report was not published by the host policy path")
    current_budget, previous_receipt = _current_budget_and_receipt(
        root,
        session_id,
        initial_budget,
        profile_artifact,
        budget_artifact,
        envelope,
        envelope_artifact,
    )
    _validate_current_eligibility(
        root,
        session_id,
        report,
        profile_artifact=profile_artifact,
        budget_artifact=budget_artifact,
        envelope=envelope,
        envelope_artifact=envelope_artifact,
        current_budget=current_budget,
        previous_receipt=previous_receipt,
    )
    if report.eligibility != "passed":
        raise PermissionError("failed eligibility cannot create policy authorization")
    authorizations_root = _approval_root(root, session_id) / "authorizations"
    if os.path.isdir(native_io_path(authorizations_root)):
        for existing_path in authorizations_root.glob("*.json"):
            existing_artifact = approval_artifact_for(
                root,
                existing_path,
                artifact_id=existing_path.stem,
                kind="aqv2-routine-policy-authorization",
            )
            existing = _load_model(
                root,
                existing_artifact,
                AQV2RoutinePolicyAuthorization,
            )
            if existing.eligibility_report == report_artifact:
                raise FileExistsError("eligibility report already has a policy authorization")
    observed_at = _utc_now(created_at)
    authorization_id = _stable_id(
        "policy-auth",
        {
            "eligibility": report_artifact.sha256,
            "target": report.exact_target_artifact.sha256,
            "budget": report.budget_after.contract_id,
        },
    )
    authorization = AQV2RoutinePolicyAuthorization(
        contract_id=authorization_id,
        authorization_id=authorization_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "One exact routine action is policy-authorized instead of prompting the user."
        ),
        policy_profile=profile_artifact,
        approval_envelope=envelope_artifact,
        approval_budget=budget_artifact,
        eligibility_report=report_artifact,
        gate_kind=report.gate_kind,
        bounded_transformation=report.bounded_transformation,
        exact_target_artifact=report.exact_target_artifact,
        current_canonical_snapshot=report.current_canonical_snapshot,
        dependency_artifacts=report.dependency_artifacts,
        budget_before=report.budget_before,
        budget_after=report.budget_after,
        decision_reasons=report.decision_reasons,
        forbidden_conditions=[],
        previous_receipt=report.previous_receipt,
    )
    authorization_artifact = _write_immutable_model(
        root,
        authorizations_root / f"{authorization_id}.json",
        authorization,
        artifact_id=authorization_id,
        kind="aqv2-routine-policy-authorization",
    )
    return {
        "status": "issued",
        "authorization": authorization.model_dump(mode="json"),
        "authorization_artifact": authorization_artifact.model_dump(mode="json"),
        "is_user_approval": False,
        "approved_by_user": False,
        "single_use": True,
    }


def _validated_current_policy_authorization(
    job_id: str,
    session_id: str,
    *,
    policy_authorization_path: str | Path,
    expected_gate_kind: RoutineGateKind | None = None,
    expected_target_path: str | Path | None = None,
) -> tuple[
    Path,
    AQV2RoutinePolicyAuthorization,
    ApprovalArtifact,
    AQV2RoutineGateEligibilityReport,
]:
    """Replay one canonical issued authorization and prove that it is still unused."""

    boundary = _load_approval_boundary(job_id, session_id)
    (
        root,
        _plan,
        _root_authorization,
        root_artifact,
        _profile,
        profile_artifact,
        initial_budget,
        budget_artifact,
        envelope,
        envelope_artifact,
    ) = boundary
    path = (
        Path(policy_authorization_path)
        if Path(policy_authorization_path).is_absolute()
        else root / policy_authorization_path
    )
    with open(native_io_path(path), "rb") as handle:
        authorization = AQV2RoutinePolicyAuthorization.model_validate_json(handle.read())
    expected_path = (
        _approval_root(root, session_id)
        / "authorizations"
        / f"{authorization.authorization_id}.json"
    )
    if path.resolve() != expected_path.resolve():
        raise PermissionError("policy authorization is outside its canonical host path")
    authorization_artifact = approval_artifact_for(
        root,
        path,
        artifact_id=authorization.authorization_id,
        kind="aqv2-routine-policy-authorization",
    )
    decisions_root = _approval_root(root, session_id) / "decisions"
    if os.path.isdir(native_io_path(decisions_root)):
        for existing_path in decisions_root.glob("*.json"):
            existing, _artifact = _decision_receipt_from_path(root, existing_path)
            if existing.policy_authorization == authorization_artifact:
                raise PermissionError("routine policy authorization was already consumed")
    current_budget, previous_receipt = _current_budget_and_receipt(
        root,
        session_id,
        initial_budget,
        profile_artifact,
        budget_artifact,
        envelope,
        envelope_artifact,
    )
    report = _load_model(
        root,
        authorization.eligibility_report,
        AQV2RoutineGateEligibilityReport,
    )
    report_path = validate_approval_artifact(root, authorization.eligibility_report)
    expected_report_path = (
        _approval_root(root, session_id)
        / "eligibility"
        / f"{report.report_id}.json"
    )
    if (
        report_path.resolve() != expected_report_path.resolve()
        or report.report_id != _expected_eligibility_id(report)
        or authorization.created_at < report.created_at
    ):
        raise PermissionError("policy authorization references noncanonical eligibility")
    _validate_current_eligibility(
        root,
        session_id,
        report,
        profile_artifact=profile_artifact,
        budget_artifact=budget_artifact,
        envelope=envelope,
        envelope_artifact=envelope_artifact,
        current_budget=current_budget,
        previous_receipt=previous_receipt,
    )
    expected_id = _stable_id(
        "policy-auth",
        {
            "eligibility": authorization.eligibility_report.sha256,
            "target": authorization.exact_target_artifact.sha256,
            "budget": authorization.budget_after.contract_id,
        },
    )
    if (
        authorization.contract_id != authorization.authorization_id
        or authorization.authorization_id != expected_id
        or authorization.root_authorization != root_artifact
        or authorization.policy_profile != profile_artifact
        or authorization.approval_envelope != envelope_artifact
        or authorization.approval_budget != budget_artifact
        or authorization.gate_kind != report.gate_kind
        or authorization.bounded_transformation != report.bounded_transformation
        or authorization.exact_target_artifact != report.exact_target_artifact
        or authorization.current_canonical_snapshot
        != report.current_canonical_snapshot
        or authorization.dependency_artifacts != report.dependency_artifacts
        or authorization.budget_before != report.budget_before
        or authorization.budget_after != report.budget_after
        or authorization.decision_reasons != report.decision_reasons
        or authorization.previous_receipt != report.previous_receipt
    ):
        raise PermissionError("policy authorization differs from host eligibility")
    if expected_gate_kind is not None and authorization.gate_kind != expected_gate_kind:
        raise PermissionError("policy authorization gate differs from the requested action")
    if expected_target_path is not None:
        expected_target = (
            Path(expected_target_path)
            if Path(expected_target_path).is_absolute()
            else root / expected_target_path
        )
        if validate_approval_artifact(root, authorization.exact_target_artifact) != (
            expected_target.resolve()
        ):
            raise PermissionError("policy authorization targets another exact artifact")
    return root, authorization, authorization_artifact, report


def validate_routine_policy_authorization(
    job_id: str,
    session_id: str,
    *,
    policy_authorization_path: str | Path,
    expected_gate_kind: RoutineGateKind | None = None,
    expected_target_path: str | Path | None = None,
) -> dict[str, object]:
    """Expose read-only host replay for one current non-user policy authorization."""

    _root, authorization, artifact, report = _validated_current_policy_authorization(
        job_id,
        session_id,
        policy_authorization_path=policy_authorization_path,
        expected_gate_kind=expected_gate_kind,
        expected_target_path=expected_target_path,
    )
    return {
        "status": "valid_unused",
        "authorization": authorization.model_dump(mode="json"),
        "authorization_artifact": artifact.model_dump(mode="json"),
        "eligibility_report": report.model_dump(mode="json"),
        "is_user_approval": False,
    }


def publish_policy_decision_receipt(
    job_id: str,
    session_id: str,
    *,
    policy_authorization_path: str | Path,
    canonical_snapshot_after_path: str | Path,
    canonical_snapshot_after_kind: str,
    outcome: str,
    action_result_path: str | Path | None = None,
    action_result_kind: str | None = None,
    decision_reasons: list[str] | None = None,
    allow_disabled_experimental: bool = False,
    created_at: datetime | None = None,
) -> dict[str, object]:
    """Consume one current authorization exactly once and publish its immutable result."""

    if not allow_disabled_experimental:
        raise PermissionError("AQ Approval Envelope remains disabled_experimental")
    if outcome not in {"applied", "rejected", "rolled_back", "technical_failed"}:
        raise ValueError("unknown AQ policy decision outcome")
    if (action_result_path is None) != (action_result_kind is None):
        raise ValueError("action result path and kind must be supplied together")
    boundary = _load_approval_boundary(job_id, session_id)
    (
        root,
        plan,
        _root_authorization,
        root_artifact,
        _profile,
        profile_artifact,
        initial_budget,
        budget_artifact,
        envelope,
        envelope_artifact,
    ) = boundary
    validated_root, authorization, authorization_artifact, eligibility = (
        _validated_current_policy_authorization(
            job_id,
            session_id,
            policy_authorization_path=policy_authorization_path,
        )
    )
    if validated_root.resolve() != root.resolve():
        raise PermissionError("policy authorization resolved another job boundary")
    decisions_root = _approval_root(root, session_id) / "decisions"
    canonical_after = approval_artifact_for(
        root,
        (
            Path(canonical_snapshot_after_path)
            if Path(canonical_snapshot_after_path).is_absolute()
            else root / canonical_snapshot_after_path
        ),
        artifact_id=_stable_id("canonical-after", str(canonical_snapshot_after_path)),
        kind=canonical_snapshot_after_kind,
    )
    result_artifact = None
    if action_result_path is not None and action_result_kind is not None:
        result_path = (
            Path(action_result_path)
            if Path(action_result_path).is_absolute()
            else root / action_result_path
        )
        result_artifact = approval_artifact_for(
            root,
            result_path,
            artifact_id=_stable_id("action-result", str(action_result_path)),
            kind=action_result_kind,
        )
    if outcome == "applied" and result_artifact is None:
        raise ValueError("applied policy action requires exact result evidence")
    if outcome in {"rejected", "rolled_back", "technical_failed"} and (
        canonical_after.sha256 != authorization.current_canonical_snapshot.sha256
    ):
        raise RuntimeError("non-applied policy action did not preserve canonical snapshot")
    observed_at = _utc_now(created_at)
    receipt_id = _stable_id(
        "policy-receipt",
        {
            "authorization": authorization_artifact.sha256,
            "outcome": outcome,
            "canonical_after": canonical_after.sha256,
            "result": None if result_artifact is None else result_artifact.sha256,
        },
    )
    receipt = AQV2PolicyDecisionReceipt(
        contract_id=receipt_id,
        receipt_id=receipt_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        root_authorization=root_artifact,
        producer=_PRODUCER,
        created_at=observed_at,
        approval_count_effect="reduces",
        approval_count_justification=(
            "The exact routine authorization was consumed without creating user approval."
        ),
        policy_profile=profile_artifact,
        approval_envelope=envelope_artifact,
        policy_authorization=authorization_artifact,
        eligibility_report=authorization.eligibility_report,
        gate_kind=authorization.gate_kind,
        exact_target_artifact=authorization.exact_target_artifact,
        canonical_snapshot_before=authorization.current_canonical_snapshot,
        canonical_snapshot_after=canonical_after,
        action_result=result_artifact,
        outcome=outcome,
        budget_before=authorization.budget_before,
        budget_after=authorization.budget_after,
        previous_receipt=authorization.previous_receipt,
        decision_reasons=decision_reasons or list(authorization.decision_reasons),
        consumed_at=observed_at,
    )
    receipt_artifact = _write_immutable_model(
        root,
        decisions_root
        / f"{authorization.budget_after.routine_policy_authorizations:04d}.json",
        receipt,
        artifact_id=receipt_id,
        kind="aqv2-policy-decision-receipt",
    )
    return {
        "status": outcome,
        "receipt": receipt.model_dump(mode="json"),
        "receipt_artifact": receipt_artifact.model_dump(mode="json"),
        "authorization_consumed_once": True,
        "is_user_approval": False,
        "canonical_corruption": False,
    }


def assert_user_approval_category_allowed(category: str) -> None:
    """Fail closed when a caller tries to turn a technical failure into user approval."""

    normalized = category.strip().casefold()
    if normalized in _TECHNICAL_FAILURE_CATEGORIES:
        raise PermissionError(
            "technical failure categories cannot create user approval artifacts"
        )


def approval_policy_capability() -> dict[str, object]:
    """Return the static disabled policy catalog without reading or mutating a session."""

    return {
        "schema_version": "0.3.0",
        "status": "disabled_experimental",
        "approval_modes": ["autonomous", "checkpointed", "interactive"],
        "routine_gate_kinds": list(_GATE_TRANSFORMATIONS),
        "bounded_transformations": list(
            dict.fromkeys(
                item for item in _GATE_TRANSFORMATIONS.values() if item is not None
            )
        ),
        "technical_user_approval_allowed": False,
        "policy_is_user_approval": False,
        "repository_creates_codex_task": False,
        "app_close_background_execution": False,
        "destination_project_write": False,
    }
