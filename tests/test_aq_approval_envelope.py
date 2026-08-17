"""Focused Approval Envelope 0.3 and one-prompt supervisor contract tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from codex_blender_modeler.autonomy_v2 import (
    AQV2ApprovalBudget,
    AQV2ApprovalTelemetryReport,
    AQV2RoutinePolicyAuthorization,
    AutonomyApprovalEnvelope,
    assert_user_approval_category_allowed,
    authorize_routine_gate,
    autonomy_v2_profile_status,
    cancel_autonomy_v2,
    cancel_one_prompt,
    evaluate_routine_gate_eligibility,
    get_approval_envelope_status,
    get_one_prompt_status,
    plan_approval_envelope,
    plan_autonomous_static_prop_v2,
    plan_one_prompt_run,
    publish_consolidated_escalation,
    publish_framework_change_justification,
    publish_policy_decision_receipt,
    resume_one_prompt,
    validate_routine_policy_authorization,
)
from codex_blender_modeler.autonomy_v2.approval_models import ApprovalArtifact
from codex_blender_modeler.autonomy_v2.approval_policy_service import (
    _validate_identity_split_gate_target,
)
from codex_blender_modeler.autonomy_v2.approval_supervisor_service import (
    _geometry_policy_snapshot,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_service import (
    _require_geometry_policy_decision,
    _validate_geometry_policy_authority,
)
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.models import AutonomyPlanV2
from codex_blender_modeler.blender_artifacts import sha256_file, write_json_atomic
from codex_blender_modeler.production.controller_executor.models import (
    ControllerArtifact,
    ControllerResult,
)


def _reference(path: Path, *, color: tuple[int, int, int] = (72, 96, 132)) -> Path:
    """Create one deterministic local static-prop reference fixture."""

    Image.new("RGB", (48, 48), color).save(path)
    return path


def _base_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    job_id: str,
    delivery: str = "review_only",
) -> tuple[Path, dict[str, object]]:
    """Create one disabled-experimental AQ v2 base session inside the test workspace."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    result = plan_autonomous_static_prop_v2(
        "Create the isolated static prop and continue within the stated scope.",
        reference_path=_reference(tmp_path / f"{job_id}.png"),
        target_subject="isolated static prop",
        requested_delivery_profiles=[delivery],  # type: ignore[list-item]
        job_id=job_id,
        allow_disabled_experimental=True,
    )
    return workspace / job_id, result


def _enable_autonomous_envelope(base: dict[str, object]) -> tuple[str, str]:
    """Enable one exact autonomous test envelope over an existing base session."""

    job_id = str(base["job_id"])
    session_id = str(base["session_id"])
    original = str(base["root_authorization"]["original_request_sha256"])  # type: ignore[index]
    plan_approval_envelope(
        job_id,
        session_id,
        approval_mode="autonomous",
        initial_user_request_sha256=original,
        explicit_autonomy_delegation_observed=True,
        allow_disabled_experimental=True,
    )
    return job_id, session_id


def _issue_rollback_policy(
    root: Path,
    base: dict[str, object],
    *,
    suffix: str,
) -> tuple[Path, Path, str]:
    """Issue one exact rollback authorization without consuming its decision."""

    job_id = str(base["job_id"])
    session_id = str(base["session_id"])
    target = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / f"rollback-target-{suffix}.json"
    )
    write_json_atomic(
        target,
        {"status": "rollback_candidate", "canonical_unchanged": True},
    )
    canonical = root / str(base["root_authorization"]["primary_reference"]["path"])  # type: ignore[index]
    eligibility = evaluate_routine_gate_eligibility(
        job_id,
        session_id,
        gate_kind="rollback",
        exact_target_path=target,
        exact_target_kind="rollback-target",
        current_canonical_snapshot_path=canonical,
        current_canonical_snapshot_kind="canonical-reference-snapshot",
        allow_disabled_experimental=True,
    )
    issued = authorize_routine_gate(
        job_id,
        session_id,
        eligibility_report_path=str(eligibility["report_artifact"]["path"]),  # type: ignore[index]
        allow_disabled_experimental=True,
    )
    return (
        target,
        canonical,
        str(issued["authorization_artifact"]["path"]),  # type: ignore[index]
    )


def _controller_artifact(
    root: Path,
    relative_path: str,
    *,
    artifact_id: str,
    role: str,
) -> ControllerArtifact:
    """Write one exact controller artifact for identity-binding policy tests."""

    path = root / relative_path
    write_json_atomic(path, {"artifact_id": artifact_id, "role": role})
    return ControllerArtifact(
        artifact_id=artifact_id,
        role=role,
        path=relative_path,
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


@pytest.mark.parametrize(
    ("mode", "expected_cap", "delegated"),
    [
        ("autonomous", 0, True),
        ("checkpointed", 3, True),
        ("interactive", 64, False),
    ],
)
def test_approval_modes_bind_unchanged_root_and_separate_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_cap: int,
    delegated: bool,
) -> None:
    """Keep RootAuthorizationV2 bytes unchanged while selecting three additive modes."""

    root, base = _base_plan(
        tmp_path,
        monkeypatch,
        job_id=f"approval_mode_{mode}",
    )
    session_id = str(base["session_id"])
    root_path = root / str(base["artifacts"]["root_authorization"]["path"])  # type: ignore[index]
    before = sha256_file(root_path)
    original = str(base["root_authorization"]["original_request_sha256"])  # type: ignore[index]
    result = plan_approval_envelope(
        str(base["job_id"]),
        session_id,
        approval_mode=mode,  # type: ignore[arg-type]
        initial_user_request_sha256=original,
        explicit_autonomy_delegation_observed=delegated,
        allow_disabled_experimental=True,
    )
    envelope = AutonomyApprovalEnvelope.model_validate_json(
        json.dumps(result["approval_envelope"])
    )
    budget = AQV2ApprovalBudget.model_validate_json(
        json.dumps(result["approval_budget"])
    )
    assert sha256_file(root_path) == before
    assert envelope.approval_mode == mode
    assert budget.max_additional_user_decisions == expected_cap
    assert budget.technical_user_approval_requests == 0
    assert envelope.future_artifacts_user_approved is False
    assert result["root_authorization_modified"] is False


def test_legacy_session_is_reported_without_migration_or_retroactive_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read an envelope-free AQ session without creating companion evidence."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_legacy")
    status = get_approval_envelope_status(
        str(base["job_id"]),
        str(base["session_id"]),
    )
    assert status["status"] == "legacy_without_envelope"
    assert status["automatic_migration"] is False
    assert status["retroactive_authority"] is False
    assert not (
        root
        / "production"
        / "autonomy_v2"
        / str(base["session_id"])
        / "approval_envelope"
    ).exists()


def test_initial_geometry_policy_uses_the_immutable_reference_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind first promotion policy to real pre-canonical evidence instead of a missing blend."""

    root, base = _base_plan(
        tmp_path,
        monkeypatch,
        job_id="approval_initial_geometry_snapshot",
    )
    snapshot, kind = _geometry_policy_snapshot(root, str(base["job_id"]))
    assert snapshot == root / "input" / "reference.png"
    assert kind == "canonical-reference-snapshot"


def test_missing_delegation_fails_before_companion_or_one_prompt_job_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject policy modes before publishing partial envelope or base-job evidence."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_no_delegation")
    session_id = str(base["session_id"])
    original = str(base["root_authorization"]["original_request_sha256"])  # type: ignore[index]
    with pytest.raises(PermissionError, match="require explicit delegation"):
        plan_approval_envelope(
            str(base["job_id"]),
            session_id,
            approval_mode="autonomous",
            initial_user_request_sha256=original,
            explicit_autonomy_delegation_observed=False,
            allow_disabled_experimental=True,
        )
    assert not (
        root / "production" / "autonomy_v2" / session_id / "approval_envelope"
    ).exists()

    workspace = tmp_path / "one-prompt-workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    with pytest.raises(PermissionError, match="require explicit delegation"):
        plan_one_prompt_run(
            "Create this static prop without explicit routine delegation.",
            reference_path=_reference(tmp_path / "no-delegation.png"),
            target_subject="no-delegation prop",
            requested_delivery_profiles=["review_only"],
            approval_mode="checkpointed",
            explicit_autonomy_delegation_observed=False,
            job_id="approval_one_prompt_no_delegation",
            allow_disabled_experimental=True,
        )
    assert not (workspace / "approval_one_prompt_no_delegation").exists()


def test_policy_authorization_is_single_use_and_never_user_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue, validate, and consume one host policy action without user authority."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_single_use")
    job_id = str(base["job_id"])
    session_id = str(base["session_id"])
    original = str(base["root_authorization"]["original_request_sha256"])  # type: ignore[index]
    plan_approval_envelope(
        job_id,
        session_id,
        approval_mode="autonomous",
        initial_user_request_sha256=original,
        explicit_autonomy_delegation_observed=True,
        allow_disabled_experimental=True,
    )
    target = root / "production" / "autonomy_v2" / session_id / "rollback-target.json"
    write_json_atomic(target, {"status": "rollback_candidate", "canonical_unchanged": True})
    canonical = root / str(base["root_authorization"]["primary_reference"]["path"])  # type: ignore[index]
    eligibility = evaluate_routine_gate_eligibility(
        job_id,
        session_id,
        gate_kind="rollback",
        exact_target_path=target,
        exact_target_kind="rollback-target",
        current_canonical_snapshot_path=canonical,
        current_canonical_snapshot_kind="canonical-reference-snapshot",
        allow_disabled_experimental=True,
    )
    assert eligibility["eligibility"] == "passed"
    report_path = str(eligibility["report_artifact"]["path"])  # type: ignore[index]
    issued = authorize_routine_gate(
        job_id,
        session_id,
        eligibility_report_path=report_path,
        allow_disabled_experimental=True,
    )
    authorization = AQV2RoutinePolicyAuthorization.model_validate_json(
        json.dumps(issued["authorization"])
    )
    authorization_path = str(issued["authorization_artifact"]["path"])  # type: ignore[index]
    assert authorization.is_user_approval is False
    assert authorization.approved_by_user is False
    assert authorization.synthetic_user_approval is False
    assert validate_routine_policy_authorization(
        job_id,
        session_id,
        policy_authorization_path=authorization_path,
        expected_gate_kind="rollback",
        expected_target_path=target,
    )["status"] == "valid_unused"
    receipt = publish_policy_decision_receipt(
        job_id,
        session_id,
        policy_authorization_path=authorization_path,
        canonical_snapshot_after_path=canonical,
        canonical_snapshot_after_kind="canonical-reference-snapshot",
        outcome="rejected",
        allow_disabled_experimental=True,
    )
    assert receipt["is_user_approval"] is False
    assert receipt["canonical_corruption"] is False
    with pytest.raises(PermissionError, match="already consumed"):
        validate_routine_policy_authorization(
            job_id,
            session_id,
            policy_authorization_path=authorization_path,
        )


def test_missing_policy_decision_blocks_the_next_eligibility_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse new eligibility while an issued authorization has no decision receipt."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_missing_decision")
    job_id, session_id = _enable_autonomous_envelope(base)
    target, canonical, _authorization_path = _issue_rollback_policy(
        root,
        base,
        suffix="outstanding",
    )
    eligibility_root = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "approval_envelope"
        / "eligibility"
    )
    before = sorted(eligibility_root.glob("*.json"))

    with pytest.raises(PermissionError, match="no PolicyDecisionReceipt"):
        evaluate_routine_gate_eligibility(
            job_id,
            session_id,
            gate_kind="rollback",
            exact_target_path=target,
            exact_target_kind="rollback-target",
            current_canonical_snapshot_path=canonical,
            current_canonical_snapshot_kind="canonical-reference-snapshot",
            allow_disabled_experimental=True,
        )
    assert sorted(eligibility_root.glob("*.json")) == before


def test_dependency_required_gate_rejects_an_empty_dependency_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject geometry eligibility before publishing a zero-dependency report."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_empty_dependencies")
    job_id, session_id = _enable_autonomous_envelope(base)
    target = root / "production" / "autonomy_v2" / session_id / "controller-result.json"
    write_json_atomic(target, {"status": "completed", "canonical_unchanged": True})
    canonical = root / str(base["root_authorization"]["primary_reference"]["path"])  # type: ignore[index]

    with pytest.raises(ValueError, match="requires at least one exact dependency"):
        evaluate_routine_gate_eligibility(
            job_id,
            session_id,
            gate_kind="geometry_candidate_promotion",
            exact_target_path=target,
            exact_target_kind="controller-result",
            current_canonical_snapshot_path=canonical,
            current_canonical_snapshot_kind="canonical-reference-snapshot",
            allow_disabled_experimental=True,
        )
    eligibility_root = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "approval_envelope"
        / "eligibility"
    )
    assert not list(eligibility_root.glob("*.json"))


def test_geometry_promotion_boundary_rejects_missing_policy_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop an envelope-governed canonical promotion before any canonical write."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_promotion_boundary")
    _enable_autonomous_envelope(base)
    result_path = root / "production" / "autonomy_v2" / str(base["session_id"]) / "result.json"
    write_json_atomic(result_path, {"status": "completed"})
    result_artifact = artifact_for_v2(
        root,
        result_path,
        artifact_id="promotion-result",
        kind="controller_result",
    )
    plan = AutonomyPlanV2.model_validate_json(json.dumps(base["plan"]))
    canonical_path = root / "analysis" / "scene_spec.json"
    canonical_before = sha256_file(canonical_path) if canonical_path.is_file() else None

    with pytest.raises(PermissionError, match="requires PolicyAuthorization"):
        _validate_geometry_policy_authority(plan, result_artifact, None)
    canonical_after = sha256_file(canonical_path) if canonical_path.is_file() else None
    assert canonical_after == canonical_before


def test_geometry_promotion_receipt_requires_an_applied_policy_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a geometry promotion receipt that has no applied decision companion."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_geometry_decision")
    _enable_autonomous_envelope(base)
    _target, _canonical, authorization_path = _issue_rollback_policy(
        root,
        base,
        suffix="geometry-decision",
    )
    receipt_path = (
        root
        / "production"
        / "autonomy_v2"
        / str(base["session_id"])
        / "geometry-promotion-receipt.json"
    )
    write_json_atomic(receipt_path, {"status": "passed"})
    receipt_artifact = artifact_for_v2(
        root,
        receipt_path,
        artifact_id="geometry-promotion-receipt",
        kind="geometry_candidate_validation_receipt",
    )
    plan = AutonomyPlanV2.model_validate_json(json.dumps(base["plan"]))

    with pytest.raises(PermissionError, match="no unique applied PolicyDecisionReceipt"):
        _require_geometry_policy_decision(
            plan,
            authorization_path,
            receipt_artifact,
        )


def test_sibling_controller_result_cannot_satisfy_geometry_eligibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject copied controller evidence whose embedded job identity is a sibling."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_sibling_binding")
    job_id, session_id = _enable_autonomous_envelope(base)
    plan = AutonomyPlanV2.model_validate_json(json.dumps(base["plan"]))
    prefix = f"production/autonomy_v2/{session_id}/sibling-fixture"
    request = _controller_artifact(
        root,
        f"{prefix}/request.json",
        artifact_id="sibling-request",
        role="controller_request",
    )
    profile = _controller_artifact(
        root,
        f"{prefix}/profile.json",
        artifact_id="sibling-profile",
        role="tool_profile",
    )
    output = _controller_artifact(
        root,
        f"{prefix}/output.json",
        artifact_id="sibling-output",
        role="controller_output",
    )
    now = datetime.now(UTC)
    controller_result = ControllerResult(
        contract_id="sibling-controller-result",
        job_id="approval_sibling_source",
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256="1" * 64,
        source_fingerprint="2" * 64,
        producer="pytest",
        provenance=[request],
        created_at=now,
        execution_id="sibling-execution",
        controller_kind="fake_for_tests",
        status="completed",
        request=request,
        tool_profile=profile,
        outputs=[output],
        output_inventory_sha256="3" * 64,
        canonical_unchanged=True,
        started_at=now,
        completed_at=now,
    )
    result_path = root / f"{prefix}/result.json"
    write_json_atomic(result_path, controller_result.model_dump(mode="json"))
    canonical = root / str(base["root_authorization"]["primary_reference"]["path"])  # type: ignore[index]

    result = evaluate_routine_gate_eligibility(
        job_id,
        session_id,
        gate_kind="geometry_candidate_promotion",
        exact_target_path=result_path,
        exact_target_kind="controller-result",
        current_canonical_snapshot_path=canonical,
        current_canonical_snapshot_kind="canonical-reference-snapshot",
        dependency_paths=[
            root / request.path,
            root / profile.path,
            root / output.path,
        ],
        dependency_kinds=[
            "controller-request",
            "controller-tool-profile",
            "controller-output",
        ],
        allow_disabled_experimental=True,
    )
    assert result["eligibility"] == "failed"
    assert "GEOMETRY_CONTROLLER_RESULT_NOT_COMPLETED" in result["report"][  # type: ignore[index]
        "forbidden_conditions"
    ]


def test_policy_target_and_final_hash_mismatches_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject both post-authorization target tamper and a different final snapshot."""

    (tmp_path / "target").mkdir()
    target_root, target_base = _base_plan(
        tmp_path / "target",
        monkeypatch,
        job_id="approval_target_tamper",
    )
    target_job, target_session = _enable_autonomous_envelope(target_base)
    target, _canonical, target_authorization = _issue_rollback_policy(
        target_root,
        target_base,
        suffix="tamper",
    )
    write_json_atomic(target, {"status": "tampered", "canonical_unchanged": False})
    with pytest.raises(ValueError, match="hash|digest|size"):
        validate_routine_policy_authorization(
            target_job,
            target_session,
            policy_authorization_path=target_authorization,
        )

    (tmp_path / "final").mkdir()
    final_root, final_base = _base_plan(
        tmp_path / "final",
        monkeypatch,
        job_id="approval_final_mismatch",
    )
    final_job, final_session = _enable_autonomous_envelope(final_base)
    _target, _canonical, final_authorization = _issue_rollback_policy(
        final_root,
        final_base,
        suffix="final",
    )
    different_final = (
        final_root
        / "production"
        / "autonomy_v2"
        / final_session
        / "different-final.json"
    )
    write_json_atomic(different_final, {"canonical": "different"})
    with pytest.raises(RuntimeError, match="did not preserve canonical snapshot"):
        publish_policy_decision_receipt(
            final_job,
            final_session,
            policy_authorization_path=final_authorization,
            canonical_snapshot_after_path=different_final,
            canonical_snapshot_after_kind="canonical-reference-snapshot",
            outcome="rejected",
            allow_disabled_experimental=True,
        )


def test_tampered_policy_decision_receipt_breaks_chain_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detect a decision mutation whose immutable receipt identity no longer matches."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_receipt_tamper")
    job_id, session_id = _enable_autonomous_envelope(base)
    _target, canonical, authorization_path = _issue_rollback_policy(
        root,
        base,
        suffix="receipt",
    )
    decision = publish_policy_decision_receipt(
        job_id,
        session_id,
        policy_authorization_path=authorization_path,
        canonical_snapshot_after_path=canonical,
        canonical_snapshot_after_kind="canonical-reference-snapshot",
        outcome="rejected",
        allow_disabled_experimental=True,
    )
    decision_path = root / str(decision["receipt_artifact"]["path"])  # type: ignore[index]
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload["outcome"] = "technical_failed"
    write_json_atomic(decision_path, payload)

    with pytest.raises(ValueError, match="identity or ordinal is noncanonical"):
        get_approval_envelope_status(job_id, session_id)


def test_terminal_session_cannot_reuse_an_issued_policy_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject unused policy authority after append-only session cancellation."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_terminal_reuse")
    job_id, session_id = _enable_autonomous_envelope(base)
    _target, _canonical, authorization_path = _issue_rollback_policy(
        root,
        base,
        suffix="terminal",
    )
    cancelled = cancel_autonomy_v2(
        job_id,
        session_id,
        reason="test terminal policy reuse boundary",
    )
    assert cancelled["state"]["status"] == "cancelled"  # type: ignore[index]

    with pytest.raises(PermissionError, match="terminal AQ session"):
        validate_routine_policy_authorization(
            job_id,
            session_id,
            policy_authorization_path=authorization_path,
        )


def test_profile_stays_disabled_before_human_activation_acceptance() -> None:
    """Keep the profile disabled while the real indexer owns activation asset counts."""

    status = autonomy_v2_profile_status()
    assert status["status"] == "disabled_experimental"
    assert status["verified_active"] is False
    assert any(
        "human review evidence" in blocker
        for blocker in status["activation_blockers"]  # type: ignore[union-attr]
    )


def test_quality_policy_decision_failure_prevents_state_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep quality state canonicalization behind a successful policy decision receipt."""

    import codex_blender_modeler.autonomy_v2.approval_policy_service as policy_service
    import codex_blender_modeler.autonomy_v2.supervisor_service as service

    report = SimpleNamespace(outcome="passed")
    submission = SimpleNamespace(
        integrated_quality_report=SimpleNamespace(path="quality/report.json")
    )
    plan = SimpleNamespace(job_id="quality-policy-job", session_id="quality-policy-session")
    state = SimpleNamespace(budget_usage=SimpleNamespace())
    terminal = SimpleNamespace(path="quality/terminal.json", kind="quality-terminal")
    source_freeze = SimpleNamespace(path="quality/freeze.json", kind="source-freeze")
    state_writes: list[object] = []

    def accept_companion(**_kwargs: object) -> None:
        """Treat the optional companion boundary as absent in this focused unit test."""

    def validate_submission(*_args: object) -> SimpleNamespace:
        """Return one already-validated passing report for the policy boundary."""

        return SimpleNamespace(report=report)

    def require_policy(*_args: object) -> bool:
        """Require the routine policy decision for this isolated quality action."""

        return True

    def accept_authorization(*_args: object, **_kwargs: object) -> None:
        """Treat the exact policy authorization as already validated for this test."""

    def consume_budget(*_args: object, **_kwargs: object) -> SimpleNamespace:
        """Return a bounded usage placeholder before the simulated decision failure."""

        return SimpleNamespace()

    def adopt_source_freeze(**_kwargs: object) -> SimpleNamespace:
        """Return the exact source-freeze artifact selected by the passing branch."""

        return source_freeze

    def adopt_terminal(**_kwargs: object) -> SimpleNamespace:
        """Return the immutable quality terminal staged before canonical state promotion."""

        return terminal

    def reject_decision(*_args: object, **_kwargs: object) -> dict[str, object]:
        """Simulate an unavailable PolicyDecisionReceipt writer at the final gate."""

        raise PermissionError("PolicyDecisionReceipt unavailable")

    def record_state_write(*_args: object, **_kwargs: object) -> SimpleNamespace:
        """Record any forbidden canonical state write after the failed decision."""

        state_writes.append(object())
        return SimpleNamespace()

    monkeypatch.setattr(
        service,
        "_validate_optional_codex_image_material_companion",
        accept_companion,
    )
    monkeypatch.setattr(service, "_validate_quality_submission", validate_submission)
    monkeypatch.setattr(policy_service, "policy_authorization_required", require_policy)
    monkeypatch.setattr(
        policy_service,
        "validate_routine_policy_authorization",
        accept_authorization,
    )
    monkeypatch.setattr(service, "_consume_action_budget", consume_budget)
    monkeypatch.setattr(service, "_adopt_or_publish_source_freeze", adopt_source_freeze)
    monkeypatch.setattr(service, "_adopt_or_publish_quality_terminal", adopt_terminal)
    monkeypatch.setattr(policy_service, "publish_policy_decision_receipt", reject_decision)
    monkeypatch.setattr(service, "_write_next_state", record_state_write)

    with pytest.raises(PermissionError, match="PolicyDecisionReceipt unavailable"):
        service._advance_quality_action(
            root=tmp_path,
            session_root=tmp_path / "session",
            plan=plan,
            budget=SimpleNamespace(),
            state=state,
            authorization=SimpleNamespace(),
            submission=submission,
            policy_authorization_path="policy-authorization.json",
        )
    assert state_writes == []


def test_technical_failure_categories_cannot_enter_user_approval_factory() -> None:
    """Reject every named technical repair category at the user-approval boundary."""

    for category in (
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
    ):
        with pytest.raises(PermissionError, match="technical failure"):
            assert_user_approval_category_allowed(category)
    assert_user_approval_category_allowed("scope_expansion")


def test_identity_split_policy_validator_fails_closed_on_missing_evidence(
    tmp_path: Path,
) -> None:
    """Load the correct closure reader and reject an absent split target cleanly."""

    target = ApprovalArtifact(
        artifact_id="missing-split-request",
        kind="material-identity-split-approval-request",
        path="production/material_identity_split/missing/approval_request.json",
        sha256="a" * 64,
        byte_size=1,
    )
    caps = SimpleNamespace(max_identity_splits=4, max_material_identities_created=4)
    assert _validate_identity_split_gate_target(  # type: ignore[arg-type]
        tmp_path,
        target,
        caps,
    ) == ["IDENTITY_SPLIT_EVIDENCE_INVALID_OR_STALE"]


def test_genuine_decisions_are_consolidated_into_one_nonapproval_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish scope and delivery choices together with zero individual approvals."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_escalation")
    job_id = str(base["job_id"])
    session_id = str(base["session_id"])
    original = str(base["root_authorization"]["original_request_sha256"])  # type: ignore[index]
    plan_approval_envelope(
        job_id,
        session_id,
        approval_mode="autonomous",
        initial_user_request_sha256=original,
        explicit_autonomy_delegation_observed=True,
        allow_disabled_experimental=True,
    )
    candidate = root / "production" / "autonomy_v2" / session_id / "candidate.json"
    evidence = root / "production" / "autonomy_v2" / session_id / "evidence.json"
    write_json_atomic(candidate, {"candidate": "best-current"})
    write_json_atomic(evidence, {"completed": ["geometry", "material"]})
    response = publish_consolidated_escalation(
        job_id,
        session_id,
        current_best_candidate_path=candidate,
        current_best_candidate_kind="current-best-candidate",
        completed_evidence_paths=[evidence],
        completed_evidence_kinds=["completed-evidence"],
        decisions=[
            {
                "item_id": "scope-choice",
                "reason": "scope_expansion",
                "question": "Should the content scope expand?",
                "choices": [
                    {
                        "choice_id": "keep-scope",
                        "label": "Keep scope",
                        "impact": "Finish with the current object only.",
                        "additional_budget_actions": 0,
                        "changed_scope": [],
                        "review_bundle_if_not_selected": True,
                    }
                ],
            },
            {
                "item_id": "delivery-choice",
                "reason": "delivery_expansion",
                "question": "Should an additional delivery profile be added?",
                "choices": [
                    {
                        "choice_id": "keep-delivery",
                        "label": "Keep delivery",
                        "impact": "Retain the initially requested review terminal.",
                        "additional_budget_actions": 0,
                        "changed_scope": [],
                        "review_bundle_if_not_selected": True,
                    }
                ],
            },
        ],
        allow_disabled_experimental=True,
    )
    assert response["status"] == "pending"
    assert response["individual_approval_request_count"] == 0
    assert response["is_user_approval"] is False
    assert len(response["request"]["decisions"]) == 2  # type: ignore[index]
    escalation_root = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "approval_envelope"
        / "escalation"
    )
    assert [item.name for item in escalation_root.glob("*.json")] == ["request.json"]


def test_job_local_failure_cannot_add_schema_cli_or_approval_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep one candidate defect out of reusable framework and approval surfaces."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="approval_job_local")
    job_id = str(base["job_id"])
    session_id = str(base["session_id"])
    original = str(base["root_authorization"]["original_request_sha256"])  # type: ignore[index]
    plan_approval_envelope(
        job_id,
        session_id,
        approval_mode="autonomous",
        initial_user_request_sha256=original,
        explicit_autonomy_delegation_observed=True,
        allow_disabled_experimental=True,
    )
    evidence = root / "production" / "fixtures" / "job-local-failure.json"
    write_json_atomic(evidence, {"classification": "job_local_candidate_error"})

    with pytest.raises(PermissionError, match="cannot add public surface"):
        publish_framework_change_justification(
            job_id,
            session_id,
            classification="job_local_candidate_error",
            issue_summary="One candidate has an invalid local parameter.",
            evidence_paths=[evidence],
            evidence_kinds=["candidate-failure"],
            request_new_public_schema=True,
            request_new_public_cli=True,
            request_new_approval_type=True,
            allow_disabled_experimental=True,
        )
    result = publish_framework_change_justification(
        job_id,
        session_id,
        classification="job_local_candidate_error",
        issue_summary="Repair only the exact candidate parameter.",
        evidence_paths=[evidence],
        evidence_kinds=["candidate-failure"],
        allow_disabled_experimental=True,
    )
    assert result["public_framework_change_allowed"] is False
    assert result["justification"]["job_local_candidate_fix_required"] is True  # type: ignore[index]
    assert result["justification"]["new_approval_type_allowed"] is False  # type: ignore[index]


def test_one_prompt_status_resume_and_cancel_preserve_current_task_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep resume in-session and never claim repository task spawn or background work."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_one_prompt_run(
        "Create the prop end to end within this exact scope and stop safely.",
        reference_path=_reference(tmp_path / "one-prompt.png", color=(110, 80, 50)),
        target_subject="small procedural prop",
        requested_delivery_profiles=["review_only"],
        approval_mode="autonomous",
        explicit_autonomy_delegation_observed=True,
        job_id="approval_one_prompt",
        allow_disabled_experimental=True,
    )
    job_id = str(planned["job_id"])
    session_id = str(planned["session_id"])
    status = get_one_prompt_status(job_id, session_id)
    assert status["repository_creates_codex_task"] is False
    assert status["app_close_background_execution"] is False
    resumed = resume_one_prompt(
        job_id,
        session_id,
        max_actions=1,
        allow_disabled_experimental=True,
    )
    assert resumed["status"] == "waiting_for_controller"
    assert resumed["job_id"] == job_id
    assert resumed["session_id"] == session_id
    assert resumed["repository_creates_codex_task"] is False
    assert resumed["app_close_background_execution"] is False
    cancelled = cancel_one_prompt(
        job_id,
        session_id,
        reason="test cancellation after bounded current-task slice",
        allow_disabled_experimental=True,
    )
    assert cancelled["terminal_type"] == "cancelled"
    terminal_status = get_one_prompt_status(job_id, session_id)
    assert terminal_status["status"] == "terminal"
    assert terminal_status["resume_same_state_budget_assignment"] is True
    telemetry_artifact = terminal_status["terminal"]["approval_telemetry"]  # type: ignore[index]
    telemetry = AQV2ApprovalTelemetryReport.model_validate_json(
        (workspace / job_id / telemetry_artifact["path"]).read_bytes()
    )
    assert telemetry.initial_user_request_count == 1
    assert telemetry.additional_user_decision_count == 0
    assert telemetry.technical_user_approval_request_count == 0
    assert telemetry.canonical_corruption_count == 0


def test_interactive_one_prompt_preserves_legacy_approval_waits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep interactive one-prompt outside routine policy authorization semantics."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_one_prompt_run(
        "Create this prop while retaining every existing explicit approval boundary.",
        reference_path=_reference(tmp_path / "interactive-one-prompt.png"),
        target_subject="interactive static prop",
        requested_delivery_profiles=["review_only"],
        approval_mode="interactive",
        explicit_autonomy_delegation_observed=False,
        job_id="approval_one_prompt_interactive",
        allow_disabled_experimental=True,
    )

    plan = planned["one_prompt_plan"]
    assert plan["approval_mode"] == "interactive"  # type: ignore[index]
    assert plan["only_waits_for_consolidated_escalation"] is False  # type: ignore[index]
    assert plan["routine_approval_wait_allowed"] is True  # type: ignore[index]


def test_approval_contracts_reject_unknown_fields_and_publish_draft_202012_schema() -> None:
    """Keep strict unknown-field rejection and checked-in JSON Schema semantics visible."""

    schema = AutonomyApprovalEnvelope.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "0.3.0"
    assert AQV2RoutinePolicyAuthorization.model_json_schema()["additionalProperties"] is False
