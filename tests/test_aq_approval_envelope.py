"""Focused Approval Envelope 0.3 and one-prompt supervisor contract tests."""

from __future__ import annotations

import json
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
from codex_blender_modeler.blender_artifacts import sha256_file, write_json_atomic


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
