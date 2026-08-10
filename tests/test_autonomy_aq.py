from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.autonomy.budget import consume_budget
from codex_blender_modeler.autonomy.cycle_detection import detect_state_cycle
from codex_blender_modeler.autonomy.models import (
    AutonomyArtifact,
    BudgetUsage,
    PolicyAuthorization,
    StateFingerprint,
)
from codex_blender_modeler.autonomy.planner import plan_autonomous_static_prop
from codex_blender_modeler.autonomy.profiles import get_autonomy_profile_status
from codex_blender_modeler.autonomy.service import (
    _budget_terminal_reason,
    _review_termination_reason,
    _write_or_adopt_immutable_json,
    advance_autonomy,
    get_autonomy_status,
    run_autonomy,
)
from codex_blender_modeler.integrated_quality import (
    QualityGateProfile,
    quality_artifact_input_sha256,
)


def test_interrupted_immutable_json_is_adopted_only_when_exact(tmp_path: Path) -> None:
    """Adopt exact action evidence while rejecting a changed receipt-less artifact."""

    root = tmp_path / "job"
    root.mkdir()
    evidence = root / "production" / "autonomy" / "session" / "input.json"
    payload = {"kind": "assembly_validation", "ok": True}
    _write_or_adopt_immutable_json(root, evidence, payload)
    original = evidence.read_bytes()

    _write_or_adopt_immutable_json(root, evidence, payload)
    assert evidence.read_bytes() == original

    evidence.write_text('{"kind": "assembly_validation", "ok": false}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="interrupted immutable evidence differs"):
        _write_or_adopt_immutable_json(root, evidence, payload)


def _reference(path: Path) -> Path:
    """Create one deterministic isolated reference image."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 60), (46, 91, 132)).save(path)
    return path


def _fingerprint(seed: str, *, direction: str | None = None) -> StateFingerprint:
    """Build one valid deterministic state fingerprint for cycle tests."""

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return StateFingerprint(
        scene_spec_sha256=digest,
        camera_fingerprint=hashlib.sha256(f"camera:{seed}".encode()).hexdigest(),
        normalized_metric_vector_sha256=hashlib.sha256(
            f"metric:{seed}".encode()
        ).hexdigest(),
        build_fingerprint=hashlib.sha256(f"build:{seed}".encode()).hexdigest(),
        canonical_source_fingerprint=hashlib.sha256(
            f"source:{seed}".encode()
        ).hexdigest(),
        change_direction=direction,
    )


def test_only_static_prop_profile_is_active() -> None:
    """Keep future autonomy profiles disabled until their Blender gates exist."""

    status = get_autonomy_profile_status()
    profiles = {item["profile_id"]: item["status"] for item in status["profiles"]}
    assert status["active_profile_id"] == "autonomous_static_prop_v1"
    assert profiles["autonomous_static_prop_v1"] == "verified_active"
    assert profiles["autonomous_environment_v1"] == "disabled_experimental"
    assert profiles["autonomous_architecture_v1"] == "disabled_experimental"
    assert profiles["autonomous_measured_asset_v1"] == "disabled_experimental"


def test_budget_and_cycle_detection_are_bounded() -> None:
    """Reject budget expansion and detect exact and normalized state cycles."""

    from codex_blender_modeler.autonomy.models import AutonomyBudget

    zeros = "0" * 64
    budget = AutonomyBudget(
        budget_id="budget-test",
        job_id="aq_budget_test",
        workflow_id="wf-budget-test",
        dispatch_id="dispatch-budget-test",
        input_sha256=zeros,
        source_fingerprint=zeros,
        provenance=[AutonomyArtifact(path="input/reference.png", sha256=zeros)],
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
        initial_candidates=1,
    )
    accepted = consume_budget(
        budget,
        BudgetUsage(),
        initial_candidates=1,
        total_actions=1,
    )
    rejected = consume_budget(
        budget,
        accepted.usage,
        initial_candidates=1,
    )
    assert accepted.allowed is True
    assert rejected.allowed is False
    assert rejected.exhausted_dimension == "initial_candidates"

    first = _fingerprint("a", direction="widen")
    duplicate = first.model_copy(update={"camera_fingerprint": "1" * 64})
    assert detect_state_cycle([first, duplicate]).kind == "duplicate_candidate_state"

    middle = _fingerprint("b", direction="narrow")
    normalized_return = _fingerprint("c", direction="widen").model_copy(
        update={
            "normalized_metric_vector_sha256": first.normalized_metric_vector_sha256,
        }
    )
    assert detect_state_cycle([first, middle, normalized_return]).kind == (
        "oscillation_detected"
    )


def test_review_reason_preserves_bounded_search_stop() -> None:
    """Carry an exact cycle or plateau stop into a later non-passing review bundle."""

    plateau_state = SimpleNamespace(pending_terminal_reason="plateau")
    failed_report = SimpleNamespace(outcome="failed")
    assert _review_termination_reason(plateau_state, failed_report) == "plateau"
    ordinary_state = SimpleNamespace(pending_terminal_reason=None)
    unscorable_report = SimpleNamespace(outcome="unscorable")
    assert _review_termination_reason(ordinary_state, unscorable_report) == (
        "unscorable_evidence"
    )


@pytest.mark.parametrize(
    ("dimension", "reason"),
    [
        ("structural_rounds", "structural_budget_exhausted"),
        ("parametric_convergence_iterations", "parametric_budget_exhausted"),
        ("material_rounds", "material_budget_exhausted"),
        ("package_repairs", "package_repair_budget_exhausted"),
        ("canonical_promotions", "structural_budget_exhausted"),
        ("total_blender_builds", "global_budget_exhausted"),
        ("total_quality_evaluations", "global_budget_exhausted"),
        ("total_actions", "global_budget_exhausted"),
    ],
)
def test_budget_dimensions_have_stable_terminal_reasons(
    dimension: str,
    reason: str,
) -> None:
    """Keep bounded resource exhaustion machine-readable across review routing."""

    assert _budget_terminal_reason(dimension) == reason


def test_strict_policy_contract_rejects_unknown_fields() -> None:
    """Reject schema drift instead of silently broadening policy authority."""

    with pytest.raises(ValidationError):
        PolicyAuthorization.model_validate(
            {
                "schema_version": "0.1.0",
                "unexpected_authority": True,
            }
        )

    with pytest.raises(ValidationError):
        AutonomyArtifact(path="../outside.json", sha256="0" * 64)


def test_plan_binds_exact_request_and_stops_for_controller(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Plan an unchanged standard workflow and stop after one isolated assignment."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    request = "  이 레퍼런스의 휴대용 단말기만 정적 소품으로 제작해.  "
    planned = plan_autonomous_static_prop(
        request,
        reference_path=_reference(tmp_path / "reference.png"),
        target_subject="휴대용 단말기",
        job_id="aq_static_prop",
    )
    root = workspace / "aq_static_prop"
    session_id = planned["session_id"]
    authorization = json.loads(
        (
            root
            / "production"
            / "autonomy"
            / session_id
            / "root_authorization.json"
        ).read_text(encoding="utf-8")
    )
    assert authorization["original_request_sha256"] == hashlib.sha256(
        request.encode("utf-8")
    ).hexdigest()
    assert authorization["authorization_source"] == "initial_user_request"
    dispatch_request_path = (
        root
        / planned["production"]["dispatch_plan"]["dispatch_request"]["path"]
    )
    dispatch_request = json.loads(dispatch_request_path.read_text(encoding="utf-8"))
    assert dispatch_request["execution_policy"] == "standard"
    assert dispatch_request["reference_content_scope"] == (
        "primary_object_only"
    )
    quality_profile = QualityGateProfile.model_validate_json(
        (
            root
            / "production"
            / "autonomy"
            / session_id
            / "quality_gate_profile.json"
        ).read_text(encoding="utf-8")
    )
    assert {item.artifact_id for item in quality_profile.provenance} == {
        "autonomy-primary-reference",
        "autonomy-workflow-request",
    }
    assert quality_profile.input_sha256 == quality_artifact_input_sha256(
        quality_profile.provenance
    )

    status = run_autonomy("aq_static_prop", session_id, max_actions=2)
    assert status["state"]["status"] == "waiting_for_controller"
    assert status["state"]["next_action"] == "await_controller_output"
    assert status["candidate_assignment"]["assignment"][
        "canonical_write_authority"
    ] == "controller_only"
    assert not list((root / "workflows").glob("*/approvals/*.json"))

    before_hash = status["receipt_chain_head_sha256"]
    reread = get_autonomy_status("aq_static_prop", session_id)
    assert reread["receipt_chain_head_sha256"] == before_hash


def test_tampered_transition_budget_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a schema-valid receipt whose budget no longer matches its state pair."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_autonomous_static_prop(
        "파란 상자 제품만 모델링해.",
        reference_path=_reference(tmp_path / "tamper.png"),
        target_subject="파란 상자 제품",
        job_id="aq_receipt_tamper",
    )
    run_autonomy("aq_receipt_tamper", planned["session_id"], max_actions=2)
    receipt_path = (
        workspace
        / "aq_receipt_tamper"
        / "production"
        / "autonomy"
        / planned["session_id"]
        / "transitions"
        / "0002"
        / "receipt.json"
    )
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["budget_after"]["total_actions"] += 1
    receipt_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale or spliced"):
        get_autonomy_status("aq_receipt_tamper", planned["session_id"])


def test_receiptless_candidate_assignment_is_adopted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recover a complete assignment written before its atomic state transition."""

    from codex_blender_modeler.autonomy import service as autonomy_service

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    planned = plan_autonomous_static_prop(
        "Create only the small blue static prop.",
        reference_path=_reference(tmp_path / "assignment-recovery.png"),
        target_subject="small blue static prop",
        job_id="aq_assignment_recovery",
    )
    session_id = planned["session_id"]
    advance_autonomy("aq_assignment_recovery", session_id)
    original_transition = autonomy_service._transition

    def interrupt_transition(*args: object, **kwargs: object) -> object:
        """Simulate a process stop after assignment publication."""

        raise RuntimeError("injected assignment transition interruption")

    with monkeypatch.context() as context:
        context.setattr(autonomy_service, "_transition", interrupt_transition)
        with pytest.raises(RuntimeError, match="injected assignment"):
            advance_autonomy("aq_assignment_recovery", session_id)

    assert original_transition is autonomy_service._transition
    recovered = advance_autonomy("aq_assignment_recovery", session_id)
    assert recovered["state"]["status"] == "waiting_for_controller"
    assert recovered["state"]["next_action"] == "await_controller_output"
    assert recovered["candidate_assignment"] is not None
    assert any(
        "Recovered a complete receipt-less initial candidate assignment" in item
        for item in recovered["state"]["warnings"]
    )
