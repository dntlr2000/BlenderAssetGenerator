"""Exact-hash root and policy authorization construction and validation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .io import ensure_autonomy_path, write_immutable_json
from .models import (
    AutonomyArtifact,
    AutonomyBudget,
    AutonomyProfile,
    BudgetUsage,
    PolicyAuthorization,
    PolicyGateKind,
    PolicyGateTarget,
    RootAuthorization,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_UNSET = object()


def _artifact_path(root: Path, artifact: AutonomyArtifact, *, label: str) -> Path:
    """Resolve and hash-check one exact job-contained authorization artifact."""

    resolved_root = root.expanduser().resolve()
    resolved = (resolved_root / artifact.path).resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Policy {label} escaped its job") from exc
    if not resolved.is_file():
        raise ValueError(f"Policy {label} must be a regular file")
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != artifact.sha256:
        raise ValueError(f"Policy {label} hash changed")
    return resolved


def _read_artifact_model(
    root: Path,
    artifact: AutonomyArtifact,
    model: type[_ModelT],
    *,
    label: str,
) -> _ModelT:
    """Load a strict support contract only after its path and bytes are verified."""

    path = _artifact_path(root, artifact, label=label)
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _validate_identity(
    authorization: PolicyAuthorization,
    root_authorization: RootAuthorization,
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    gate_target: PolicyGateTarget,
) -> None:
    """Require every support contract to carry the same job/workflow/dispatch identity."""

    expected = (
        authorization.job_id,
        authorization.workflow_id,
        authorization.dispatch_id,
    )
    labeled = {
        "root authorization": root_authorization,
        "autonomy profile": profile,
        "autonomy budget": budget,
        "policy gate target": gate_target,
    }
    mismatched = [
        label
        for label, model in labeled.items()
        if (model.job_id, model.workflow_id, model.dispatch_id) != expected
    ]
    if mismatched:
        raise ValueError(f"Policy support identity mismatch: {mismatched}")


def _validate_root_model(root_authorization: RootAuthorization) -> None:
    """Reconstruct the exact request/scope fingerprint of one root authorization."""

    if root_authorization.input_sha256 != root_authorization.original_request_sha256:
        raise ValueError("Root authorization request hash binding is inconsistent")
    expected_source = canonical_digest(
        {
            "request_sha256": root_authorization.original_request_sha256,
            "launch_sha256": root_authorization.production_launch_or_binding.sha256,
            "reference_sha256": root_authorization.primary_reference.sha256,
            "profile_sha256": root_authorization.autonomy_profile.sha256,
            "budget_sha256": root_authorization.budget.sha256,
            "target_subject": root_authorization.target_subject,
        }
    )
    if root_authorization.source_fingerprint != expected_source:
        raise ValueError("Root authorization source fingerprint is inconsistent")
    expected_provenance = [
        root_authorization.production_launch_or_binding,
        root_authorization.primary_reference,
        root_authorization.autonomy_profile,
        root_authorization.budget,
    ]
    if root_authorization.provenance != expected_provenance:
        raise ValueError("Root authorization provenance is reordered or incomplete")
    now = datetime.now(UTC)
    if root_authorization.status != "active":
        raise PermissionError("Root authorization is not active")
    if (
        root_authorization.expires_at is not None
        and root_authorization.expires_at <= now
    ):
        raise PermissionError("Root authorization has expired")


def _validate_profile_budget_models(
    profile: AutonomyProfile,
    budget: AutonomyBudget,
    *,
    profile_artifact: AutonomyArtifact,
    budget_artifact: AutonomyArtifact,
) -> None:
    """Recompute the immutable profile and budget snapshots used by policy decisions."""

    if profile.status != "verified_active":
        raise PermissionError("Policy authorization requires a verified active profile")
    if profile.default_budget != budget:
        raise ValueError("Autonomy profile embeds a different immutable budget")
    expected_profile_input = canonical_digest(
        {
            "profile_id": profile.profile_id,
            "budget_sha256": budget_artifact.sha256,
            "quality_gate_profile_sha256": profile.quality_gate_profile.sha256,
        }
    )
    if profile.input_sha256 != expected_profile_input:
        raise ValueError("Autonomy profile input SHA-256 is inconsistent")
    expected_profile_source = canonical_digest(
        {
            "profile_id": profile.profile_id,
            "budget_sha256": budget_artifact.sha256,
            "quality_gate_profile_sha256": profile.quality_gate_profile.sha256,
            "allowed_gates": profile.allowed_gate_kinds,
        }
    )
    if profile.source_fingerprint != expected_profile_source:
        raise ValueError("Autonomy profile source fingerprint is inconsistent")
    if profile.provenance != [budget_artifact, profile.quality_gate_profile]:
        raise ValueError("Autonomy profile provenance is reordered or incomplete")
    if budget.provenance != [profile.quality_gate_profile]:
        raise ValueError("Autonomy budget provenance is inconsistent with the profile")
    budget_source = profile.quality_gate_profile.model_dump(mode="json")
    if budget.input_sha256 != canonical_digest(budget_source):
        raise ValueError("Autonomy budget input SHA-256 is inconsistent")
    if budget.source_fingerprint != canonical_digest(
        {"source": budget_source, "profile": profile.profile_id}
    ):
        raise ValueError("Autonomy budget source fingerprint is inconsistent")
    if profile_artifact.sha256 == budget_artifact.sha256:
        raise ValueError("Profile and budget artifacts must remain distinct")


def _validate_budget_transition(
    budget: AutonomyBudget,
    budget_before: BudgetUsage,
    budget_after: BudgetUsage,
) -> None:
    """Verify monotonic single-action accounting against every immutable budget cap."""

    before = budget_before.model_dump()
    after = budget_after.model_dump()
    for field, before_value in before.items():
        if after[field] < before_value:
            raise ValueError(f"Policy budget usage decreased: {field}")
    if budget_after.total_actions != budget_before.total_actions + 1:
        raise ValueError("Policy authorization must consume exactly one global action")
    limits = {
        "initial_candidates": budget.initial_candidates,
        "structural_rounds": budget.structural_rounds,
        "parametric_convergence_iterations": (
            budget.parametric_convergence_iterations
        ),
        "material_rounds": budget.material_rounds,
        "package_repairs": budget.package_repairs,
        "total_blender_builds": budget.total_blender_builds,
        "total_quality_evaluations": budget.total_quality_evaluations,
        "canonical_promotions": budget.canonical_promotions,
        "total_actions": budget.global_action_limit,
    }
    exceeded = [field for field, limit in limits.items() if after[field] > limit]
    if exceeded:
        raise PermissionError(f"Policy authorization exceeds budget caps: {exceeded}")


def _policy_input_payload(authorization: PolicyAuthorization) -> dict[str, object]:
    """Reconstruct the exact canonical payload hashed by the policy issuer."""

    return {
        "root_authorization_sha256": authorization.root_authorization_sha256,
        "profile_sha256": authorization.profile_sha256,
        "step_id": authorization.workflow_step_id,
        "input_fingerprint": authorization.workflow_input_fingerprint,
        "target": authorization.target_artifact.model_dump(mode="json"),
        "gate_target": authorization.gate_target.model_dump(mode="json"),
        "gate_kind": authorization.gate_kind,
        "budget_before": authorization.budget_before.model_dump(mode="json"),
        "budget_after": authorization.budget_after.model_dump(mode="json"),
        "previous": authorization.previous_authorization_sha256,
    }


def _budget_usage_dominates(current: BudgetUsage, previous: BudgetUsage) -> bool:
    """Accept intervening non-policy actions while rejecting any counter rollback."""

    current_values = current.model_dump(mode="python")
    previous_values = previous.model_dump(mode="python")
    return all(
        int(current_values[key]) >= int(previous_values[key])
        for key in previous_values
    )


def _validate_gate_target(
    root: Path,
    authorization: PolicyAuthorization,
    gate_target: PolicyGateTarget,
) -> None:
    """Rebuild one gate target's exact workflow/dependency fingerprint and semantics."""

    if (
        gate_target.workflow_step_id != authorization.workflow_step_id
        or gate_target.workflow_input_fingerprint
        != authorization.workflow_input_fingerprint
        or gate_target.input_sha256 != authorization.workflow_input_fingerprint
        or gate_target.gate_kind != authorization.gate_kind
    ):
        raise ValueError("Policy gate target does not match the authorized workflow boundary")
    _artifact_path(root, gate_target.workflow_plan, label="gate workflow plan")
    for index, artifact in enumerate(gate_target.provenance):
        _artifact_path(root, artifact, label=f"gate provenance {index}")
    for index, artifact in enumerate(gate_target.dependency_artifacts):
        _artifact_path(root, artifact, label=f"gate dependency {index}")
    if gate_target.workflow_plan not in gate_target.provenance:
        raise ValueError("Policy gate target provenance omits the exact workflow plan")
    if authorization.gate_kind in {
        "structural_candidate_promotion",
        "bounded_convergence_candidate",
    }:
        expected_keys = {"candidate_evaluation", "candidate_manifest"}
        if set(gate_target.dependency_completion_fingerprints) != expected_keys:
            raise ValueError("Candidate promotion gate dependencies are incomplete")
        if (
            gate_target.dependency_completion_fingerprints["candidate_evaluation"]
            != authorization.target_artifact.sha256
        ):
            raise ValueError("Candidate gate target is not the exact candidate evaluation")
        manifest_sha256 = gate_target.dependency_completion_fingerprints[
            "candidate_manifest"
        ]
        if manifest_sha256 not in {
            artifact.sha256 for artifact in gate_target.dependency_artifacts
        }:
            raise ValueError("Candidate manifest is not dependency-bound")
        expected_source = canonical_digest(
            {
                "workflow_plan": gate_target.workflow_plan.sha256,
                "evaluation": authorization.target_artifact.sha256,
                "candidate_manifest": manifest_sha256,
            }
        )
    else:
        expected_source = canonical_digest(
            {
                "workflow_plan": gate_target.workflow_plan.sha256,
                "input_fingerprint": gate_target.workflow_input_fingerprint,
                "dependencies": gate_target.dependency_completion_fingerprints,
            }
        )
        workflow_plan_targets = {
            "generic_proxy_review",
            "generic_detail_review",
        }
        exact_evidence_targets = {
            "material_swatch_acknowledgement",
            "qa_review_acknowledgement",
            "optimization_plan",
            "final_package_acknowledgement",
        }
        if (
            authorization.gate_kind in workflow_plan_targets
            and authorization.target_artifact != gate_target.workflow_plan
        ):
            raise ValueError("Generic policy gate is not bound to the exact workflow plan")
        if authorization.gate_kind in exact_evidence_targets and (
            authorization.target_artifact not in gate_target.dependency_artifacts
            or gate_target.dependency_completion_fingerprints.get(
                "policy.exact_target"
            )
            != authorization.target_artifact.sha256
        ):
            raise ValueError("Routine policy gate is not bound to its exact review evidence")
        if authorization.gate_kind == "material_candidate_promotion" and (
            authorization.target_artifact not in gate_target.dependency_artifacts
            or gate_target.dependency_completion_fingerprints.get("material.ranking")
            != authorization.target_artifact.sha256
        ):
            raise ValueError("Material candidate policy is not bound to its exact ranking")
        if authorization.gate_kind == "bounded_convergence_plan" and (
            authorization.target_artifact not in gate_target.dependency_artifacts
            or gate_target.dependency_completion_fingerprints.get(
                "parametric.assignment"
            )
            != authorization.target_artifact.sha256
            or "baseline_evaluation"
            not in gate_target.dependency_completion_fingerprints
            or "canonical_scene_spec"
            not in gate_target.dependency_completion_fingerprints
            or "canonical_modeling_plan"
            not in gate_target.dependency_completion_fingerprints
        ):
            raise ValueError(
                "Bounded convergence plan is not bound to its exact assignment and baseline"
            )
        if authorization.gate_kind == "destination_handoff_envelope_plan" and (
            authorization.target_artifact.sha256
            != authorization.workflow_input_fingerprint
            or authorization.target_artifact not in gate_target.dependency_artifacts
            or gate_target.dependency_completion_fingerprints.get(
                "destination.handoff.plan"
            )
            != authorization.target_artifact.sha256
        ):
            raise ValueError("Destination handoff policy is not bound to its exact plan")
    if gate_target.source_fingerprint != expected_source:
        raise ValueError("Policy gate target source fingerprint is inconsistent")


def _find_previous_policy(
    root: Path,
    expected_sha256: str,
) -> tuple[Path, PolicyAuthorization]:
    """Resolve one unique predecessor only from known policy-authorization directories."""

    candidates: list[Path] = []
    for base in (root / "production" / "autonomy", root / "workflows"):
        if not base.is_dir():
            continue
        for path in base.rglob("*.json"):
            if path.parent.name != "policy_authorizations" or not path.is_file():
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256:
                candidates.append(path.resolve())
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise ValueError("Policy predecessor hash did not resolve to one exact artifact")
    path = unique[0]
    return path, PolicyAuthorization.model_validate_json(path.read_text(encoding="utf-8"))


def canonical_digest(value: object) -> str:
    """Hash canonical JSON without accepting non-deterministic formatting as evidence."""

    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def artifact_for(root: Path, path: Path) -> AutonomyArtifact:
    """Bind one existing file below a job root to a normalized relative path and hash."""

    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve(strict=True)
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError("Autonomy artifact escaped its owning job") from exc
    if not resolved.is_file():
        raise ValueError("Autonomy artifact must be a regular file")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return AutonomyArtifact(path=relative, sha256=digest)


def create_root_authorization(
    *,
    request_text: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    launch_or_binding: AutonomyArtifact,
    primary_reference: AutonomyArtifact,
    profile_artifact: AutonomyArtifact,
    profile: AutonomyProfile,
    budget_artifact: AutonomyArtifact,
    target_subject: str,
    created_at: datetime | None = None,
) -> RootAuthorization:
    """Create one active authorization bound to the exact initial request and profile."""

    if not request_text.strip():
        raise ValueError("Root authorization request text must not be empty")
    now = created_at or datetime.now(UTC)
    request_sha256 = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
    inputs = {
        "request_sha256": request_sha256,
        "launch_sha256": launch_or_binding.sha256,
        "reference_sha256": primary_reference.sha256,
        "profile_sha256": profile_artifact.sha256,
        "budget_sha256": budget_artifact.sha256,
        "target_subject": target_subject,
    }
    return RootAuthorization(
        contract_id=f"root-authorization-{dispatch_id}",
        authorization_id=f"root-authorization-{dispatch_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=request_sha256,
        source_fingerprint=canonical_digest(inputs),
        producer="codex_blender_modeler.autonomy.authorization",
        producer_version="0.1.0",
        provenance=[
            launch_or_binding,
            primary_reference,
            profile_artifact,
            budget_artifact,
        ],
        created_at=now,
        original_request_sha256=request_sha256,
        production_launch_or_binding=launch_or_binding,
        primary_reference=primary_reference,
        autonomy_profile=profile_artifact,
        target_subject=target_subject,
        allowed_gate_kinds=profile.allowed_gate_kinds,
        prohibited_scopes=profile.prohibited_capabilities,
        budget=budget_artifact,
    )


def authorize_policy_gate(
    *,
    root_authorization: RootAuthorization,
    root_authorization_artifact: AutonomyArtifact,
    root_authorization_sha256: str,
    profile: AutonomyProfile,
    profile_artifact: AutonomyArtifact,
    profile_sha256: str,
    budget: AutonomyBudget,
    budget_artifact: AutonomyArtifact,
    budget_sha256: str,
    gate_kind: PolicyGateKind,
    step_id: str,
    workflow_input_fingerprint: str,
    gate_target: AutonomyArtifact,
    target_artifact: AutonomyArtifact,
    budget_before: BudgetUsage,
    budget_after: BudgetUsage,
    previous_authorization_sha256: str | None,
    created_at: datetime | None = None,
) -> PolicyAuthorization:
    """Issue one consumed single-use policy grant after revalidating exact scope and budget."""

    _validate_root_model(root_authorization)
    identities = {
        (
            root_authorization.job_id,
            root_authorization.workflow_id,
            root_authorization.dispatch_id,
        ),
        (profile.job_id, profile.workflow_id, profile.dispatch_id),
        (budget.job_id, budget.workflow_id, budget.dispatch_id),
    }
    if len(identities) != 1:
        raise ValueError("Root authorization, profile, and budget identities differ")
    if gate_kind not in profile.allowed_gate_kinds:
        raise PermissionError(f"Autonomy profile does not allow gate {gate_kind}")
    if gate_kind not in root_authorization.allowed_gate_kinds:
        raise PermissionError(f"Root authorization does not allow gate {gate_kind}")
    if root_authorization.allowed_gate_kinds != profile.allowed_gate_kinds:
        raise ValueError("Root authorization gate allowance differs from the profile")
    if root_authorization.prohibited_scopes != profile.prohibited_capabilities:
        raise ValueError("Root authorization prohibited scope differs from the profile")
    if (
        root_authorization.reference_content_scope != profile.reference_content_scope
        or root_authorization.output_profile != profile.output_profile
    ):
        raise ValueError("Root authorization scope/output differs from the profile")
    if root_authorization.autonomy_profile != profile_artifact:
        raise ValueError("Root authorization is bound to a different profile")
    if root_authorization.budget != budget_artifact:
        raise ValueError("Root authorization budget binding is stale")
    if root_authorization_artifact.sha256 != root_authorization_sha256:
        raise ValueError("Root authorization artifact binding is stale")
    if profile_artifact.sha256 != profile_sha256:
        raise ValueError("Autonomy profile artifact binding is stale")
    if budget_artifact.sha256 != budget_sha256:
        raise ValueError("Autonomy budget artifact binding is stale")
    _validate_profile_budget_models(
        profile,
        budget,
        profile_artifact=profile_artifact,
        budget_artifact=budget_artifact,
    )
    _validate_budget_transition(budget, budget_before, budget_after)
    now = created_at or datetime.now(UTC)
    input_payload = {
        "root_authorization_sha256": root_authorization_sha256,
        "profile_sha256": profile_sha256,
        "step_id": step_id,
        "input_fingerprint": workflow_input_fingerprint,
        "target": target_artifact.model_dump(mode="json"),
        "gate_target": gate_target.model_dump(mode="json"),
        "gate_kind": gate_kind,
        "budget_before": budget_before.model_dump(mode="json"),
        "budget_after": budget_after.model_dump(mode="json"),
        "previous": previous_authorization_sha256,
    }
    authorization_id = f"policy-{step_id.replace('.', '-')}-{target_artifact.sha256[:12]}"
    authorization = PolicyAuthorization(
        contract_id=authorization_id,
        authorization_id=authorization_id,
        job_id=root_authorization.job_id,
        workflow_id=root_authorization.workflow_id,
        dispatch_id=root_authorization.dispatch_id,
        input_sha256=canonical_digest(input_payload),
        source_fingerprint=canonical_digest(
            {"input": input_payload, "profile_source": profile.source_fingerprint}
        ),
        producer="codex_blender_modeler.autonomy.authorization",
        producer_version="0.1.0",
        provenance=[
            gate_target,
            target_artifact,
            root_authorization_artifact,
            profile_artifact,
            budget_artifact,
        ],
        created_at=now,
        root_authorization=root_authorization_artifact,
        root_authorization_sha256=root_authorization_sha256,
        profile=profile_artifact,
        profile_sha256=profile_sha256,
        budget=budget_artifact,
        workflow_step_id=step_id,
        workflow_input_fingerprint=workflow_input_fingerprint,
        gate_kind=gate_kind,
        gate_target=gate_target,
        target_artifact=target_artifact,
        decision_reasons=[
            "The exact artifact is inside autonomous_static_prop_v1.",
            "The gate is listed in both profile and root authorization.",
            "The immutable budget remains within its hard cap.",
        ],
        budget_before=budget_before,
        budget_after=budget_after,
        previous_authorization_sha256=previous_authorization_sha256,
        consumed=True,
        consumed_at=now,
    )
    if authorization.input_sha256 != canonical_digest(
        _policy_input_payload(authorization)
    ):
        raise ValueError("Policy authorization input hash construction failed")
    return authorization


def validate_policy_authorization(
    root: Path,
    authorization: PolicyAuthorization,
    *,
    expected_job_id: str,
    expected_workflow_id: str,
    expected_step_id: str,
    expected_gate_kind: str,
    expected_input_fingerprint: str,
    expected_previous_authorization_sha256: str | None | object = _UNSET,
) -> None:
    """Reconstruct every exact support, target, budget, and predecessor policy binding."""

    if (
        authorization.job_id != expected_job_id
        or authorization.workflow_id != expected_workflow_id
        or authorization.workflow_step_id != expected_step_id
        or authorization.gate_kind != expected_gate_kind
        or authorization.workflow_input_fingerprint != expected_input_fingerprint
        or not authorization.single_use
        or not authorization.consumed
    ):
        raise ValueError("Policy authorization identity or workflow binding is stale")
    if (
        expected_previous_authorization_sha256 is not _UNSET
        and authorization.previous_authorization_sha256
        != expected_previous_authorization_sha256
    ):
        raise ValueError("Policy predecessor binding is stale or spliced")
    if authorization.root_authorization.sha256 != authorization.root_authorization_sha256:
        raise ValueError("Policy root authorization SHA binding is inconsistent")
    if authorization.profile.sha256 != authorization.profile_sha256:
        raise ValueError("Policy profile SHA binding is inconsistent")
    root_authorization = _read_artifact_model(
        root,
        authorization.root_authorization,
        RootAuthorization,
        label="root authorization",
    )
    profile = _read_artifact_model(
        root,
        authorization.profile,
        AutonomyProfile,
        label="autonomy profile",
    )
    budget = _read_artifact_model(
        root,
        authorization.budget,
        AutonomyBudget,
        label="autonomy budget",
    )
    gate_target = _read_artifact_model(
        root,
        authorization.gate_target,
        PolicyGateTarget,
        label="gate target",
    )
    _artifact_path(root, authorization.target_artifact, label="target artifact")
    _validate_identity(
        authorization,
        root_authorization,
        profile,
        budget,
        gate_target,
    )
    for label, artifacts in (
        ("root provenance", root_authorization.provenance),
        ("profile provenance", profile.provenance),
        ("budget provenance", budget.provenance),
    ):
        for index, artifact in enumerate(artifacts):
            _artifact_path(root, artifact, label=f"{label} {index}")
    _validate_root_model(root_authorization)
    if root_authorization.autonomy_profile != authorization.profile:
        raise ValueError("Root authorization profile artifact was rebound")
    if root_authorization.budget != authorization.budget:
        raise ValueError("Root authorization budget artifact was rebound")
    if root_authorization.allowed_gate_kinds != profile.allowed_gate_kinds:
        raise ValueError("Root authorization gate allowance differs from the profile")
    if root_authorization.prohibited_scopes != profile.prohibited_capabilities:
        raise ValueError("Root authorization prohibited scope differs from the profile")
    if authorization.gate_kind not in profile.allowed_gate_kinds:
        raise PermissionError("Autonomy profile does not allow this policy gate")
    if authorization.gate_kind not in root_authorization.allowed_gate_kinds:
        raise PermissionError("Root authorization does not allow this policy gate")
    _validate_profile_budget_models(
        profile,
        budget,
        profile_artifact=authorization.profile,
        budget_artifact=authorization.budget,
    )
    _validate_budget_transition(
        budget,
        authorization.budget_before,
        authorization.budget_after,
    )
    _validate_gate_target(root, authorization, gate_target)
    expected_provenance = [
        authorization.gate_target,
        authorization.target_artifact,
        authorization.root_authorization,
        authorization.profile,
        authorization.budget,
    ]
    if authorization.provenance != expected_provenance:
        raise ValueError("Policy authorization provenance is reordered or incomplete")
    input_payload = _policy_input_payload(authorization)
    if authorization.input_sha256 != canonical_digest(input_payload):
        raise ValueError("Policy authorization input SHA-256 is inconsistent")
    if authorization.source_fingerprint != canonical_digest(
        {"input": input_payload, "profile_source": profile.source_fingerprint}
    ):
        raise ValueError("Policy authorization source fingerprint is inconsistent")
    expected_id = (
        f"policy-{authorization.workflow_step_id.replace('.', '-')}"
        f"-{authorization.target_artifact.sha256[:12]}"
    )
    if authorization.authorization_id != expected_id or authorization.contract_id != expected_id:
        raise ValueError("Policy authorization identity is inconsistent")
    if authorization.created_at != authorization.consumed_at:
        raise ValueError("Policy authorization must be consumed at its issue time")

    previous_sha256 = authorization.previous_authorization_sha256
    if previous_sha256 is not None:
        _previous_path, previous = _find_previous_policy(root, previous_sha256)
        if (
            previous.job_id != authorization.job_id
            or previous.workflow_id != authorization.workflow_id
            or previous.dispatch_id != authorization.dispatch_id
        ):
            raise ValueError("Policy predecessor identity is stale or spliced")
        if not _budget_usage_dominates(
            authorization.budget_before,
            previous.budget_after,
        ):
            raise ValueError("Policy predecessor budget chain is stale or spliced")
        if previous.created_at > authorization.created_at:
            raise ValueError("Policy predecessor timestamp is after its successor")
        validate_policy_authorization(
            root,
            previous,
            expected_job_id=previous.job_id,
            expected_workflow_id=previous.workflow_id,
            expected_step_id=previous.workflow_step_id,
            expected_gate_kind=previous.gate_kind,
            expected_input_fingerprint=previous.workflow_input_fingerprint,
            expected_previous_authorization_sha256=(
                previous.previous_authorization_sha256
            ),
        )


def persist_and_validate_policy_authorization(
    root: Path,
    authorization_path: Path,
    authorization: PolicyAuthorization,
) -> AutonomyArtifact:
    """Publish or recover one grant, then fully validate its persisted exact bytes."""

    try:
        persisted_path = ensure_autonomy_path(
            root,
            authorization_path,
            must_exist=True,
        )
    except FileNotFoundError:
        write_immutable_json(
            root,
            authorization_path,
            authorization.model_dump(mode="json"),
        )
        persisted_path = ensure_autonomy_path(
            root,
            authorization_path,
            must_exist=True,
        )
    persisted = PolicyAuthorization.model_validate_json(
        persisted_path.read_text(encoding="utf-8")
    )
    validate_policy_authorization(
        root,
        persisted,
        expected_job_id=authorization.job_id,
        expected_workflow_id=authorization.workflow_id,
        expected_step_id=authorization.workflow_step_id,
        expected_gate_kind=authorization.gate_kind,
        expected_input_fingerprint=authorization.workflow_input_fingerprint,
        expected_previous_authorization_sha256=(
            authorization.previous_authorization_sha256
        ),
    )
    comparable = persisted.model_copy(
        update={
            "created_at": authorization.created_at,
            "consumed_at": authorization.consumed_at,
        }
    )
    if comparable != authorization:
        raise ValueError(
            "persisted policy authorization differs from the exact issued grant"
        )
    return artifact_for(root, persisted_path)
