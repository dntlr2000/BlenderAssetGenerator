from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_blender_modeler.autonomy import authorization as authorization_module
from codex_blender_modeler.autonomy.authorization import (
    artifact_for,
    authorize_policy_gate,
    canonical_digest,
    create_root_authorization,
    persist_and_validate_policy_authorization,
    validate_policy_authorization,
)
from codex_blender_modeler.autonomy.models import (
    AutonomyArtifact,
    BudgetUsage,
    PolicyAuthorization,
    PolicyGateTarget,
)
from codex_blender_modeler.autonomy.profiles import (
    build_default_budget,
    build_profile_snapshot,
)


def _write(path: Path, payload: object) -> None:
    """Write deterministic JSON evidence for one isolated authorization fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _support_bundle(root: Path) -> dict[str, object]:
    """Create exact root/profile/budget artifacts using production constructors."""

    now = datetime(2026, 8, 10, tzinfo=UTC)
    quality_path = root / "production" / "autonomy" / "aq-test" / "quality.json"
    _write(quality_path, {"quality": "exact"})
    quality_artifact = artifact_for(root, quality_path)
    budget = build_default_budget(
        job_id="auth_hardening",
        workflow_id="wf-auth-hardening",
        dispatch_id="dispatch-auth-hardening",
        source_artifact=quality_artifact,
        created_at=now,
    )
    budget_path = root / "production" / "autonomy" / "aq-test" / "budget.json"
    _write(budget_path, budget)
    budget_artifact = artifact_for(root, budget_path)
    profile = build_profile_snapshot(
        job_id="auth_hardening",
        workflow_id="wf-auth-hardening",
        dispatch_id="dispatch-auth-hardening",
        budget=budget,
        budget_artifact=budget_artifact,
        quality_gate_profile=quality_artifact,
        created_at=now,
    )
    profile_path = root / "production" / "autonomy" / "aq-test" / "profile.json"
    _write(profile_path, profile)
    profile_artifact = artifact_for(root, profile_path)
    launch_path = root / "production" / "dispatches" / "launch.json"
    reference_path = root / "input" / "reference.png"
    launch_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    launch_path.write_bytes(b"launch")
    reference_path.write_bytes(b"reference")
    root_authorization = create_root_authorization(
        request_text="Create only the referenced static prop.",
        job_id="auth_hardening",
        workflow_id="wf-auth-hardening",
        dispatch_id="dispatch-auth-hardening",
        launch_or_binding=artifact_for(root, launch_path),
        primary_reference=artifact_for(root, reference_path),
        profile_artifact=profile_artifact,
        profile=profile,
        budget_artifact=budget_artifact,
        target_subject="static prop",
        created_at=now,
    )
    authorization_path = (
        root / "production" / "autonomy" / "aq-test" / "root_authorization.json"
    )
    _write(authorization_path, root_authorization)
    return {
        "now": now,
        "budget": budget,
        "budget_artifact": budget_artifact,
        "profile": profile,
        "profile_artifact": profile_artifact,
        "root_authorization": root_authorization,
        "root_artifact": artifact_for(root, authorization_path),
    }


def _gate(
    root: Path,
    bundle: dict[str, object],
    *,
    step_id: str,
    budget_before: BudgetUsage,
    budget_after: BudgetUsage,
    previous_sha256: str | None = None,
) -> tuple[PolicyAuthorization, Path]:
    """Issue one exact generic gate grant and return its gate-target path."""

    workflow_plan_path = root / "workflows" / "wf-auth-hardening" / "plan.json"
    if not workflow_plan_path.exists():
        _write(workflow_plan_path, {"workflow": "exact"})
    workflow_plan = artifact_for(root, workflow_plan_path)
    input_fingerprint = canonical_digest(
        {"step": step_id, "workflow_plan": workflow_plan.sha256}
    )
    target = PolicyGateTarget(
        contract_id=f"target-{step_id.replace('.', '-')}",
        target_id=f"target-{step_id.replace('.', '-')}",
        job_id="auth_hardening",
        workflow_id="wf-auth-hardening",
        dispatch_id="dispatch-auth-hardening",
        input_sha256=input_fingerprint,
        source_fingerprint=canonical_digest(
            {
                "workflow_plan": workflow_plan.sha256,
                "input_fingerprint": input_fingerprint,
                "dependencies": {},
            }
        ),
        producer="authorization-test",
        producer_version="0.1.0",
        provenance=[workflow_plan],
        created_at=bundle["now"],
        session_id="aq-test",
        workflow_step_id=step_id,
        workflow_input_fingerprint=input_fingerprint,
        gate_kind="generic_proxy_review",
        workflow_plan=workflow_plan,
    )
    target_path = (
        root
        / "workflows"
        / "wf-auth-hardening"
        / "policy_targets"
        / f"{step_id}.json"
    )
    _write(target_path, target)
    target_artifact = artifact_for(root, target_path)
    root_artifact = bundle["root_artifact"]
    profile_artifact = bundle["profile_artifact"]
    budget_artifact = bundle["budget_artifact"]
    authorization = authorize_policy_gate(
        root_authorization=bundle["root_authorization"],
        root_authorization_artifact=root_artifact,
        root_authorization_sha256=root_artifact.sha256,
        profile=bundle["profile"],
        profile_artifact=profile_artifact,
        profile_sha256=profile_artifact.sha256,
        budget=bundle["budget"],
        budget_artifact=budget_artifact,
        budget_sha256=budget_artifact.sha256,
        gate_kind="generic_proxy_review",
        step_id=step_id,
        workflow_input_fingerprint=input_fingerprint,
        gate_target=target_artifact,
        target_artifact=workflow_plan,
        budget_before=budget_before,
        budget_after=budget_after,
        previous_authorization_sha256=previous_sha256,
        created_at=bundle["now"],
    )
    return authorization, target_path


def _validate(root: Path, authorization: PolicyAuthorization) -> None:
    """Validate one fixture grant against its own exact workflow bindings."""

    validate_policy_authorization(
        root,
        authorization,
        expected_job_id="auth_hardening",
        expected_workflow_id="wf-auth-hardening",
        expected_step_id=authorization.workflow_step_id,
        expected_gate_kind=authorization.gate_kind,
        expected_input_fingerprint=authorization.workflow_input_fingerprint,
    )


def _persisted_gate(
    root: Path,
    bundle: dict[str, object],
    *,
    step_id: str,
    gate_kind: str,
    dependency_key: str,
    budget_before: BudgetUsage | None = None,
    budget_after: BudgetUsage | None = None,
    previous_sha256: str | None = None,
) -> tuple[PolicyAuthorization, Path, Path]:
    """Construct one specialized exact-target grant and its persisted dependencies."""

    workflow_plan_path = root / "workflows" / "wf-auth-hardening" / "plan.json"
    if not workflow_plan_path.exists():
        _write(workflow_plan_path, {"workflow": "exact"})
    exact_target_path = root / "evidence" / f"{step_id}.json"
    _write(exact_target_path, {"step_id": step_id, "kind": gate_kind})
    workflow_plan = artifact_for(root, workflow_plan_path)
    exact_target = artifact_for(root, exact_target_path)
    dependencies = {dependency_key: exact_target.sha256}
    dependency_artifacts = [exact_target]
    provenance = [workflow_plan, exact_target]
    if gate_kind == "structural_candidate_promotion":
        manifest_path = root / "evidence" / f"{step_id}.manifest.json"
        _write(manifest_path, {"candidate": "manifest"})
        manifest = artifact_for(root, manifest_path)
        dependencies["candidate_manifest"] = manifest.sha256
        dependency_artifacts = [manifest]
    elif gate_kind == "bounded_convergence_plan":
        for dependency_name in (
            "baseline_evaluation",
            "canonical_scene_spec",
            "canonical_modeling_plan",
        ):
            dependency_path = root / "evidence" / f"{step_id}.{dependency_name}.json"
            _write(dependency_path, {"dependency": dependency_name})
            dependency = artifact_for(root, dependency_path)
            dependencies[dependency_name] = dependency.sha256
            dependency_artifacts.append(dependency)
    input_fingerprint = exact_target.sha256
    source_payload = {
        "workflow_plan": workflow_plan.sha256,
        "input_fingerprint": input_fingerprint,
        "dependencies": dependencies,
    }
    if gate_kind == "structural_candidate_promotion":
        source_payload = {
            "workflow_plan": workflow_plan.sha256,
            "evaluation": exact_target.sha256,
            "candidate_manifest": dependencies["candidate_manifest"],
        }
    target = PolicyGateTarget(
        contract_id=f"target-{step_id.replace('.', '-')}",
        target_id=f"target-{step_id.replace('.', '-')}",
        job_id="auth_hardening",
        workflow_id="wf-auth-hardening",
        dispatch_id="dispatch-auth-hardening",
        input_sha256=input_fingerprint,
        source_fingerprint=canonical_digest(source_payload),
        producer="authorization-test",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=bundle["now"],
        session_id="aq-test",
        workflow_step_id=step_id,
        workflow_input_fingerprint=input_fingerprint,
        gate_kind=gate_kind,
        workflow_plan=workflow_plan,
        dependency_completion_fingerprints=dependencies,
        dependency_artifacts=dependency_artifacts,
    )
    target_path = (
        root
        / "workflows"
        / "wf-auth-hardening"
        / "policy_targets"
        / f"{step_id}.json"
    )
    _write(target_path, target)
    target_artifact = artifact_for(root, target_path)
    root_artifact = bundle["root_artifact"]
    profile_artifact = bundle["profile_artifact"]
    budget_artifact = bundle["budget_artifact"]
    authorization = authorize_policy_gate(
        root_authorization=bundle["root_authorization"],
        root_authorization_artifact=root_artifact,
        root_authorization_sha256=root_artifact.sha256,
        profile=bundle["profile"],
        profile_artifact=profile_artifact,
        profile_sha256=profile_artifact.sha256,
        budget=bundle["budget"],
        budget_artifact=budget_artifact,
        budget_sha256=budget_artifact.sha256,
        gate_kind=gate_kind,
        step_id=step_id,
        workflow_input_fingerprint=input_fingerprint,
        gate_target=target_artifact,
        target_artifact=exact_target,
        budget_before=(budget_before if budget_before is not None else BudgetUsage()),
        budget_after=(
            budget_after if budget_after is not None else BudgetUsage(total_actions=1)
        ),
        previous_authorization_sha256=previous_sha256,
        created_at=bundle["now"],
    )
    grant_path = (
        root
        / "production"
        / "autonomy"
        / "aq-test"
        / "policy_authorizations"
        / f"{step_id}.json"
    )
    return authorization, target_path, grant_path


def test_policy_authorization_reconstructs_every_exact_support_contract(
    tmp_path: Path,
) -> None:
    """Accept a grant only after rebuilding root, profile, budget, target, and hashes."""

    root = tmp_path / "job"
    root.mkdir()
    bundle = _support_bundle(root)
    authorization, _target = _gate(
        root,
        bundle,
        step_id="geometry.proxy_review",
        budget_before=BudgetUsage(),
        budget_after=BudgetUsage(total_actions=1),
    )
    _validate(root, authorization)

    forged = authorization.model_copy(update={"input_sha256": "0" * 64})
    with pytest.raises(ValueError, match="input SHA-256"):
        _validate(root, forged)
    forged_source = authorization.model_copy(update={"source_fingerprint": "1" * 64})
    with pytest.raises(ValueError, match="source fingerprint"):
        _validate(root, forged_source)


def test_policy_authorization_rejects_exact_target_and_profile_tampering(
    tmp_path: Path,
) -> None:
    """Fail closed when either the gate target or a transitive profile source changes."""

    root = tmp_path / "job"
    root.mkdir()
    bundle = _support_bundle(root)
    authorization, target_path = _gate(
        root,
        bundle,
        step_id="geometry.proxy_review",
        budget_before=BudgetUsage(),
        budget_after=BudgetUsage(total_actions=1),
    )
    target_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gate target hash changed"):
        _validate(root, authorization)

    root = tmp_path / "second-job"
    root.mkdir()
    bundle = _support_bundle(root)
    authorization, _target = _gate(
        root,
        bundle,
        step_id="geometry.proxy_review",
        budget_before=BudgetUsage(),
        budget_after=BudgetUsage(total_actions=1),
    )
    quality_path = root / bundle["profile"].quality_gate_profile.path
    quality_path.write_text('{"quality":"changed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="profile provenance 1 hash changed"):
        _validate(root, authorization)


def test_policy_budget_accounting_is_monotonic_single_action_and_capped(
    tmp_path: Path,
) -> None:
    """Reject counter rollback, multi-action grants, and immutable budget expansion."""

    root = tmp_path / "job"
    root.mkdir()
    bundle = _support_bundle(root)
    with pytest.raises(ValidationError, match="exactly one action"):
        PolicyAuthorization.model_validate(
            {
                "schema_version": "0.1.0",
                "contract_id": "invalid",
                "authorization_id": "invalid",
                "job_id": "auth_hardening",
                "workflow_id": "wf-auth-hardening",
                "dispatch_id": "dispatch-auth-hardening",
                "input_sha256": "0" * 64,
                "source_fingerprint": "0" * 64,
                "producer": "test",
                "producer_version": "0.1.0",
                "provenance": [
                    AutonomyArtifact(path="input/reference.png", sha256="0" * 64)
                ],
                "created_at": datetime(2026, 8, 10, tzinfo=UTC),
                "root_authorization": AutonomyArtifact(
                    path="root.json", sha256="0" * 64
                ),
                "root_authorization_sha256": "0" * 64,
                "profile": AutonomyArtifact(path="profile.json", sha256="0" * 64),
                "profile_sha256": "0" * 64,
                "budget": AutonomyArtifact(path="budget.json", sha256="0" * 64),
                "workflow_step_id": "geometry.proxy_review",
                "workflow_input_fingerprint": "0" * 64,
                "gate_kind": "generic_proxy_review",
                "gate_target": AutonomyArtifact(path="target.json", sha256="0" * 64),
                "target_artifact": AutonomyArtifact(
                    path="workflow.json", sha256="0" * 64
                ),
                "decision_reasons": ["test"],
                "budget_before": {"total_actions": 0},
                "budget_after": {"total_actions": 2},
                "consumed": True,
                "consumed_at": datetime(2026, 8, 10, tzinfo=UTC),
            }
        )

    budget = bundle["budget"]
    with pytest.raises(PermissionError, match="budget caps"):
        _gate(
            root,
            bundle,
            step_id="geometry.proxy_review",
            budget_before=BudgetUsage(total_actions=budget.global_action_limit),
            budget_after=BudgetUsage(total_actions=budget.global_action_limit + 1),
        )


def test_policy_predecessor_chain_is_exact_and_identity_bound(tmp_path: Path) -> None:
    """Resolve one unique predecessor and reject a cross-workflow chain splice."""

    root = tmp_path / "job"
    root.mkdir()
    bundle = _support_bundle(root)
    first, _target = _gate(
        root,
        bundle,
        step_id="geometry.proxy_review",
        budget_before=BudgetUsage(),
        budget_after=BudgetUsage(total_actions=1),
    )
    previous_path = (
        root
        / "production"
        / "autonomy"
        / "aq-test"
        / "policy_authorizations"
        / "first.json"
    )
    _write(previous_path, first)
    previous_artifact = artifact_for(root, previous_path)
    second, _target = _gate(
        root,
        bundle,
        step_id="geometry.detail_review",
        budget_before=first.budget_after,
        budget_after=BudgetUsage(total_actions=2),
        previous_sha256=previous_artifact.sha256,
    )
    _validate(root, second)

    spliced = first.model_copy(update={"workflow_id": "wf-other"})
    _write(previous_path, spliced)
    spliced_artifact = artifact_for(root, previous_path)
    rebound, _target = _gate(
        root,
        bundle,
        step_id="geometry.final_review",
        budget_before=spliced.budget_after,
        budget_after=BudgetUsage(total_actions=2),
        previous_sha256=spliced_artifact.sha256,
    )
    with pytest.raises(ValueError, match="predecessor identity"):
        _validate(root, rebound)


@pytest.mark.parametrize(
    ("step_id", "gate_kind", "dependency_key"),
    [
        (
            "autonomy.structural_candidate_promotion.initial-01",
            "structural_candidate_promotion",
            "candidate_evaluation",
        ),
        (
            "autonomy.bounded_convergence_plan.parametric-01",
            "bounded_convergence_plan",
            "parametric.assignment",
        ),
        ("portable.optimization_review", "optimization_plan", "policy.exact_target"),
        (
            "destination.handoff",
            "destination_handoff_envelope_plan",
            "destination.handoff.plan",
        ),
    ],
)
def test_first_use_specialized_policy_grants_are_persisted_and_fully_validated(
    tmp_path: Path,
    step_id: str,
    gate_kind: str,
    dependency_key: str,
) -> None:
    """Accept fresh structural, parametric, routine, and handoff grants after reload."""

    root = tmp_path / gate_kind
    root.mkdir()
    bundle = _support_bundle(root)
    grant, _target_path, grant_path = _persisted_gate(
        root,
        bundle,
        step_id=step_id,
        gate_kind=gate_kind,
        dependency_key=dependency_key,
    )
    artifact = persist_and_validate_policy_authorization(root, grant_path, grant)

    assert artifact == artifact_for(root, grant_path)
    persisted = PolicyAuthorization.model_validate_json(
        grant_path.read_text(encoding="utf-8")
    )
    _validate(root, persisted)


def test_first_use_policy_grant_tampering_fails_before_returning_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a freshly published grant whose exact bytes change before reload validation."""

    root = tmp_path / "job"
    root.mkdir()
    bundle = _support_bundle(root)
    grant, _target_path, grant_path = _persisted_gate(
        root,
        bundle,
        step_id="portable.optimization_review",
        gate_kind="optimization_plan",
        dependency_key="policy.exact_target",
    )
    original_write = authorization_module.write_immutable_json

    def write_then_tamper(
        owning_root: Path,
        path: Path,
        payload: dict[str, object],
    ) -> None:
        """Alter a non-hashed policy field immediately after immutable publication."""

        original_write(owning_root, path, payload)
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["decision_reasons"] = ["forged after publication"]
        _write(path, stored)

    monkeypatch.setattr(
        authorization_module,
        "write_immutable_json",
        write_then_tamper,
    )
    with pytest.raises(ValueError, match="differs from the exact issued grant"):
        persist_and_validate_policy_authorization(root, grant_path, grant)


def test_first_use_policy_target_tampering_fails_before_returning_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject target tampering injected between fresh grant publication and validation."""

    root = tmp_path / "job"
    root.mkdir()
    bundle = _support_bundle(root)
    grant, target_path, grant_path = _persisted_gate(
        root,
        bundle,
        step_id="destination.handoff",
        gate_kind="destination_handoff_envelope_plan",
        dependency_key="destination.handoff.plan",
    )
    original_write = authorization_module.write_immutable_json

    def write_then_tamper(
        owning_root: Path,
        path: Path,
        payload: dict[str, object],
    ) -> None:
        """Change the exact gate target after the grant reaches disk."""

        original_write(owning_root, path, payload)
        target_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        authorization_module,
        "write_immutable_json",
        write_then_tamper,
    )
    with pytest.raises(ValueError, match="gate target hash changed"):
        persist_and_validate_policy_authorization(root, grant_path, grant)


def test_first_use_policy_predecessor_tampering_fails_before_returning_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject predecessor-chain tampering between successor publication and validation."""

    root = tmp_path / "job"
    root.mkdir()
    bundle = _support_bundle(root)
    first, _first_target = _gate(
        root,
        bundle,
        step_id="geometry.proxy_review",
        budget_before=BudgetUsage(),
        budget_after=BudgetUsage(total_actions=1),
    )
    predecessor_path = (
        root
        / "production"
        / "autonomy"
        / "aq-test"
        / "policy_authorizations"
        / "first.json"
    )
    predecessor = persist_and_validate_policy_authorization(
        root,
        predecessor_path,
        first,
    )
    second, _target_path, second_path = _persisted_gate(
        root,
        bundle,
        step_id="portable.optimization_review",
        gate_kind="optimization_plan",
        dependency_key="policy.exact_target",
        budget_before=BudgetUsage(total_actions=1),
        budget_after=BudgetUsage(total_actions=2),
        previous_sha256=predecessor.sha256,
    )
    original_write = authorization_module.write_immutable_json

    def write_then_tamper(
        owning_root: Path,
        path: Path,
        payload: dict[str, object],
    ) -> None:
        """Change predecessor bytes after publishing the exact successor grant."""

        original_write(owning_root, path, payload)
        predecessor_path.write_text(
            predecessor_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        authorization_module,
        "write_immutable_json",
        write_then_tamper,
    )
    with pytest.raises(ValueError, match="predecessor hash did not resolve"):
        persist_and_validate_policy_authorization(root, second_path, second)
