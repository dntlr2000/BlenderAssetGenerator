"""AQ v2 parallel-contract, delivery, and pure-transition regression tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codex_blender_modeler.autonomy_v2 import (
    AQV2Artifact,
    AutonomyStateV2,
    BudgetUsageV2,
    DeliveryPlan,
    DeliveryRequest,
    DeliveryResult,
    QualityTerminalV2,
    RootAuthorizationV2,
    autonomy_v2_profile_status,
    delivery_profile,
    transition_state,
)
from codex_blender_modeler.autonomy_v2.transitions import (
    validate_initial_state,
    validate_state_transition,
)
from codex_blender_modeler.blender_artifacts import stable_json_digest

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _artifact(name: str, kind: str = "evidence") -> AQV2Artifact:
    """Create one deterministic non-empty artifact descriptor for strict contract tests."""

    return AQV2Artifact(
        artifact_id=name,
        kind=kind,
        path=f"production/autonomy/aq-v2/{name}.json",
        sha256=stable_json_digest({"name": name}),
        byte_size=32,
    )


def _root_authorization(
    requested: list[str],
    *,
    allowed: list[str] | None = None,
) -> RootAuthorizationV2:
    """Build a strict root authorization with fixed primary-object-only scope."""

    source = _artifact("primary-reference", "reference")
    profile = _artifact("profile", "autonomy_profile")
    budget = _artifact("budget", "budget")
    launch = _artifact("launch", "production_launch")
    quality = _artifact("quality-profile", "quality_profile")
    tool = _artifact("tool-profile", "phase_tool_profile")
    provenance = [source, profile, budget, launch, quality, tool]
    input_payload = {"requested": requested, "allowed": allowed or requested}
    return RootAuthorizationV2(
        contract_id="root-authorization-v2",
        job_id="aq_v2_job",
        workflow_id="wf-aq-v2",
        dispatch_id="dispatch-aq-v2",
        session_id="aq-v2",
        input_sha256=stable_json_digest(input_payload),
        source_fingerprint=stable_json_digest(
            {**input_payload, "target": "test object"}
        ),
        producer="tests.autonomy_v2",
        provenance=provenance,
        created_at=NOW,
        authorization_id="root-authorization-v2",
        original_request_sha256="a" * 64,
        primary_reference=source,
        profile=profile,
        budget=budget,
        production_launch_or_binding=launch,
        target_subject="test object",
        quality_profile=quality,
        phase_tool_profiles=[tool],
        allowed_delivery_profiles=allowed or requested,
        requested_delivery_profiles=requested,
        prohibited_scopes=["interior", "measured", "rig", "animation", "gameplay"],
    )


def _initial_state() -> AutonomyStateV2:
    """Create the pure planned-state fixture shared by transition tests."""

    plan = _artifact("plan", "autonomy_plan")
    return AutonomyStateV2(
        contract_id="state-aq-v2-0000",
        job_id="aq_v2_job",
        workflow_id="wf-aq-v2",
        dispatch_id="dispatch-aq-v2",
        session_id="aq-v2",
        input_sha256=stable_json_digest({"plan": plan.sha256, "sequence": 0}),
        source_fingerprint=stable_json_digest(
            {"plan": plan.sha256, "status": "planned"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[plan],
        created_at=NOW,
        state_id="state-aq-v2-0000",
        plan=plan,
        sequence=0,
        phase="planned",
        status="planned",
        next_action="collect_reference",
    )


def _boundary_state(
    *,
    phase: str,
    status: str,
    next_action: str,
    delivery_plan: AQV2Artifact | None = None,
) -> AutonomyStateV2:
    """Create one internally valid nonterminal state at an exact supervisor boundary."""

    state = _initial_state().model_dump(mode="python")
    state.update(
        {
            "phase": phase,
            "status": status,
            "next_action": next_action,
            "delivery_plan": delivery_plan,
        }
    )
    return AutonomyStateV2.model_validate(state)


def _completed_result(delivery_id: str, profile_id: str) -> DeliveryResult:
    """Create one fully evidenced successful format-specific delivery result."""

    return DeliveryResult(
        delivery_id=delivery_id,
        profile_id=profile_id,
        status="completed",
        source_freeze_sha256="3" * 64,
        optimization_plan=_artifact(f"{delivery_id}-plan", "optimization_plan"),
        optimization_approval=_artifact(
            f"{delivery_id}-approval", "optimization_approval"
        ),
        package_manifest=_artifact(f"{delivery_id}-package", "package_manifest"),
        roundtrip_validation=_artifact(f"{delivery_id}-roundtrip", "roundtrip"),
        material_loss_report=_artifact(f"{delivery_id}-material-loss", "material_loss"),
        geometry_survival_report=_artifact(
            f"{delivery_id}-geometry-survival", "geometry_survival"
        ),
        production_ready=True,
    )


def test_v2_profile_is_parallel_and_disabled_until_full_gates() -> None:
    """The new profile cannot alter or prematurely replace verified AQ v1 semantics."""

    status = autonomy_v2_profile_status()
    assert status["profile_id"] == "autonomous_static_prop_v2"
    assert status["status"] == "disabled_experimental"
    assert status["verified_active"] is False
    assert status["activation_blockers"]
    assert all(
        "not yet recorded" not in blocker
        for blocker in status["activation_blockers"]
    )
    assert any(
        "closed loop" in blocker for blocker in status["activation_blockers"]
    )


def test_root_authorization_binds_dual_delivery_without_review_only() -> None:
    """GLB and FBX may be jointly authorized while review-only remains exclusive."""

    root = _root_authorization(["portable_gltf", "portable_fbx"])
    assert root.destination_project_write is False
    assert root.synthetic_user_approval is False

    with pytest.raises(ValueError, match="review_only cannot be combined"):
        _root_authorization(["review_only", "portable_gltf"])
    with pytest.raises(ValueError, match="exceed"):
        _root_authorization(["portable_fbx"], allowed=["portable_gltf"])


def test_delivery_profiles_map_directly_to_existing_v07_exporters() -> None:
    """Public v2 names map to independent GLB/FBX exporters, never GLB-to-FBX conversion."""

    gltf = delivery_profile("portable_gltf")
    fbx = delivery_profile("portable_fbx")
    review = delivery_profile("review_only")
    assert (gltf.asset_profile_id, gltf.primary_extension) == ("portable_gltf", ".glb")
    assert (fbx.asset_profile_id, fbx.primary_extension) == ("fbx_interchange", ".fbx")
    assert review.asset_profile_id is None
    assert gltf.requires_exact_optimization_approval is True
    assert fbx.requires_clean_import_roundtrip is True


def test_dual_delivery_plan_requires_unique_runs_and_same_freeze() -> None:
    """Every format receives a unique run/package while sharing one exact source freeze."""

    freeze = _artifact("freeze", "quality_source_freeze")
    root = _artifact("root", "root_authorization")
    requests = [
        DeliveryRequest(
            delivery_id="delivery-gltf",
            profile=delivery_profile("portable_gltf"),
            source_freeze=freeze,
            run_id="aqv2-gltf-run",
            package_id="aqv2-gltf-package",
            status="awaiting_optimization_approval",
        ),
        DeliveryRequest(
            delivery_id="delivery-fbx",
            profile=delivery_profile("portable_fbx"),
            source_freeze=freeze,
            run_id="aqv2-fbx-run",
            package_id="aqv2-fbx-package",
            status="awaiting_optimization_approval",
        ),
    ]
    plan = DeliveryPlan(
        contract_id="delivery-plan",
        job_id="aq_v2_job",
        workflow_id="wf-aq-v2",
        dispatch_id="dispatch-aq-v2",
        session_id="aq-v2",
        input_sha256="4" * 64,
        source_fingerprint="5" * 64,
        producer="tests.autonomy_v2",
        provenance=[root, freeze],
        created_at=NOW,
        plan_id="delivery-plan",
        root_authorization=root,
        source_freeze=freeze,
        requests=requests,
    )
    assert plan.direct_cross_format_conversion is False
    assert len({item.run_id for item in plan.requests}) == 2

    payload = plan.model_dump(mode="json")
    payload["requests"][1]["run_id"] = "aqv2-gltf-run"
    with pytest.raises(ValueError, match="independent run"):
        DeliveryPlan.model_validate_json(__import__("json").dumps(payload))


def test_failed_format_does_not_cancel_successful_format() -> None:
    """A dual delivery reaches partial while retaining the successful package result."""

    delivery_plan = _artifact("delivery-plan", "delivery_plan")
    pending = _boundary_state(
        phase="delivery",
        status="delivery_pending",
        next_action="await_v07_approval",
        delivery_plan=delivery_plan,
    )
    completed = _completed_result("delivery-gltf", "portable_gltf")
    failed = DeliveryResult(
        delivery_id="delivery-fbx",
        profile_id="portable_fbx",
        status="failed",
        source_freeze_sha256="3" * 64,
        production_ready=False,
        errors=["FBX clean-import material identity failed"],
    )
    delivery_terminal = _artifact("delivery-terminal", "delivery_terminal")
    final = transition_state(
        pending,
        event="delivery_finished",
        evidence=delivery_terminal,
        delivery_terminal=delivery_terminal,
        delivery_results=[completed, failed],
        created_at=NOW,
    )
    assert final.status == "partial"
    assert final.delivery_results[0].production_ready is True
    assert final.delivery_results[1].production_ready is False


def test_quality_nonpass_terminates_review_without_delivery() -> None:
    """Non-passing IQ stops at review and cannot be mislabeled as a production package."""

    state = _boundary_state(
        phase="quality",
        status="running",
        next_action="run_integrated_quality",
    )
    quality_terminal = _artifact("quality-terminal", "quality_terminal")
    final = transition_state(
        state,
        event="quality_nonpassing",
        evidence=quality_terminal,
        quality_terminal=quality_terminal,
        created_at=NOW,
        reason="critical semantic evidence is unscorable",
    )
    assert final.status == "review_required"
    assert final.phase == "terminal"
    assert final.delivery_plan is None
    assert final.next_action == "none"


def test_terminal_state_cannot_transition_again() -> None:
    """Immutable terminal projections reject replay even when new evidence is supplied."""

    state = _initial_state()
    terminal = transition_state(
        state,
        event="cancelled",
        evidence=_artifact("cancellation", "cancellation"),
        created_at=NOW,
        reason="user cancellation",
    )
    with pytest.raises(ValueError, match="terminal"):
        transition_state(
            terminal,
            event="reference_ready",
            evidence=_artifact("reference", "reference"),
            created_at=NOW,
        )


def test_state_machine_rejects_out_of_order_events() -> None:
    """Prevent a nonterminal session from skipping authoring, quality, or delivery."""

    state = _initial_state()
    evidence = _artifact("reference", "reference")
    for event in ("candidate_validated", "quality_passed", "delivery_finished"):
        with pytest.raises(ValueError, match="invalid for the current state boundary"):
            transition_state(
                state,
                event=event,  # type: ignore[arg-type]
                evidence=evidence,
                created_at=NOW,
            )


def test_state_chain_reconstructs_initial_and_adjacent_transition() -> None:
    """Accept only the exact planner envelope and pure transition projection."""

    initial = _initial_state()
    validate_initial_state(initial)
    usage = BudgetUsageV2(total_actions=1)
    current = transition_state(
        initial,
        event="reference_ready",
        evidence=_artifact("reference-ready", "production_receipt"),
        created_at=NOW,
        budget_usage=usage,
    )
    validate_state_transition(initial, current)


def test_state_chain_rejects_self_consistent_skip_and_budget_rollback() -> None:
    """Reject a rehashed phase splice and a later state that lowers consumed budget."""

    initial = _initial_state()
    evidence = _artifact("forged-delivery-plan", "delivery_plan")
    payload = {
        "previous": stable_json_digest(initial.model_dump(mode="json")),
        "event": "delivery_planned",
        "evidence": evidence.sha256,
        "sequence": 1,
    }
    forged = AutonomyStateV2(
        contract_id="state-aq-v2-0001",
        job_id=initial.job_id,
        workflow_id=initial.workflow_id,
        dispatch_id=initial.dispatch_id,
        session_id=initial.session_id,
        input_sha256=stable_json_digest(payload),
        source_fingerprint=stable_json_digest(
            {
                **payload,
                "status": "delivery_pending",
                "next_action": "await_v07_approval",
            }
        ),
        producer="codex_blender_modeler.autonomy_v2.transitions",
        provenance=[*initial.provenance, evidence],
        created_at=NOW,
        state_id="state-aq-v2-0001",
        plan=initial.plan,
        sequence=1,
        phase="delivery",
        status="delivery_pending",
        next_action="await_v07_approval",
        delivery_plan=evidence,
        previous_state_sha256=payload["previous"],
    )
    with pytest.raises(ValueError, match="invalid for the current state boundary"):
        validate_state_transition(initial, forged)

    consumed = transition_state(
        initial,
        event="reference_ready",
        evidence=_artifact("reference-ready", "production_receipt"),
        created_at=NOW,
        budget_usage=BudgetUsageV2(total_actions=1),
    )
    rolled_back = transition_state(
        consumed,
        event="controller_required",
        evidence=_artifact("controller-waiting", "controller_result"),
        created_at=NOW,
        budget_usage=BudgetUsageV2(),
        reason="waiting for exact desktop output",
    )
    with pytest.raises(ValueError, match="rolled back budget usage"):
        validate_state_transition(consumed, rolled_back)


def test_delivery_finish_requires_terminal_and_nonempty_results() -> None:
    """Reject vacuous all-of success and a terminal status without exact evidence."""

    pending = _boundary_state(
        phase="delivery",
        status="delivery_pending",
        next_action="await_v07_approval",
        delivery_plan=_artifact("delivery-plan", "delivery_plan"),
    )
    with pytest.raises(ValueError, match="delivery terminal and nonempty results"):
        transition_state(
            pending,
            event="delivery_finished",
            evidence=_artifact("delivery-terminal", "delivery_terminal"),
            delivery_terminal=_artifact("delivery-terminal", "delivery_terminal"),
            delivery_results=[],
            created_at=NOW,
        )


def test_all_failed_delivery_results_form_a_failed_terminal_state() -> None:
    """Keep exact delivery evidence when every requested format fails safely."""

    pending = _boundary_state(
        phase="delivery",
        status="delivery_pending",
        next_action="await_v07_approval",
        delivery_plan=_artifact("delivery-plan", "delivery_plan"),
    )
    failed = DeliveryResult(
        delivery_id="delivery-gltf",
        profile_id="portable_gltf",
        status="failed",
        source_freeze_sha256="3" * 64,
        production_ready=False,
        errors=["roundtrip validation failed"],
    )
    terminal = _artifact("delivery-terminal", "delivery_terminal")
    final = transition_state(
        pending,
        event="delivery_finished",
        evidence=terminal,
        delivery_terminal=terminal,
        delivery_results=[failed],
        created_at=NOW,
    )

    assert final.status == "failed"
    assert final.delivery_terminal == terminal
    assert final.delivery_results == [failed]


def test_quality_transition_requires_exact_terminal_evidence() -> None:
    """Reject both passing and review outcomes that omit their terminal contract."""

    running = _boundary_state(
        phase="quality",
        status="running",
        next_action="run_integrated_quality",
    )
    with pytest.raises(ValueError, match="quality-terminal"):
        transition_state(
            running,
            event="quality_passed",
            evidence=_artifact("quality-terminal", "quality_terminal"),
            source_freeze=_artifact("freeze", "quality_source_freeze"),
            created_at=NOW,
        )
    with pytest.raises(ValueError, match="quality-terminal"):
        transition_state(
            running,
            event="quality_nonpassing",
            evidence=_artifact("quality-report", "integrated_quality_report"),
            created_at=NOW,
        )


def test_review_quality_terminal_requires_exact_review_bundle() -> None:
    """Prevent a non-passing IQ report from becoming an evidence-free review terminal."""

    report = _artifact("iq-v02-report", "integrated_quality_report")
    payload = {
        "contract_id": "quality-terminal-review",
        "terminal_id": "quality-terminal-review",
        "job_id": "aq_v2_job",
        "workflow_id": "wf-aq-v2",
        "dispatch_id": "dispatch-aq-v2",
        "session_id": "aq-v2",
        "input_sha256": "1" * 64,
        "source_fingerprint": "2" * 64,
        "producer": "tests.autonomy_v2",
        "provenance": [report.model_dump(mode="json")],
        "created_at": NOW,
        "status": "review_required",
        "integrated_quality_report": report.model_dump(mode="json"),
        "reason": "critical semantic evidence is unavailable",
    }
    with pytest.raises(ValueError, match="exact review bundle"):
        QualityTerminalV2.model_validate(payload)
