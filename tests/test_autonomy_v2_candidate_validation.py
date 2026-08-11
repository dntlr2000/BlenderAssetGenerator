"""Focused contracts for AQ v2 geometry candidate validation and phase ordering."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryAuthoringCompletionV2,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_service import (
    _archive_baseline,
    _rollback_canonical_files,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _required_authoring_profile,
)
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyPlanV2,
    AutonomyStateV2,
)
from codex_blender_modeler.autonomy_v2.transitions import transition_state
from codex_blender_modeler.blender_artifacts import stable_json_digest

NOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)


def _artifact(name: str, kind: str) -> AQV2Artifact:
    """Create one deterministic nonempty artifact binding for pure state tests."""

    return AQV2Artifact(
        artifact_id=name,
        kind=kind,
        path=f"production/autonomy_v2/fixture/{name}.json",
        sha256=stable_json_digest({"artifact": name}),
        byte_size=32,
    )


def _candidate_state() -> AutonomyStateV2:
    """Create one strict authoring candidate-validation boundary."""

    plan = _artifact("plan", "autonomy_plan")
    result = _artifact("result", "controller_result")
    return AutonomyStateV2(
        contract_id="state-candidate-0002",
        state_id="state-candidate-0002",
        job_id="candidate_test",
        workflow_id="wf-candidate-test",
        dispatch_id="dispatch-candidate-test",
        session_id="aqv2-candidate-test",
        input_sha256=result.sha256,
        source_fingerprint=stable_json_digest(
            {"plan": plan.sha256, "result": result.sha256}
        ),
        producer="tests.autonomy_v2_candidate_validation",
        provenance=[plan, result],
        created_at=NOW,
        plan=plan,
        sequence=2,
        phase="authoring",
        status="running",
        next_action="validate_candidate",
    )


def _completion_payload() -> dict[str, object]:
    """Return one exact geometry completion marker payload."""

    return {
        "schema_version": "0.1.0",
        "phase": "geometry_authoring",
        "status": "completed",
        "job_id": "candidate_test",
        "workflow_id": "wf-candidate-test",
        "dispatch_id": "dispatch-candidate-test",
        "session_id": "aqv2-candidate-test",
        "execution_id": "exec-geometry",
        "assignment_sha256": "a" * 64,
        "tool_profile_sha256": "b" * 64,
        "outputs": [
            {
                "name": "modeling_plan.json",
                "sha256": "c" * 64,
                "byte_size": 10,
            },
            {
                "name": "scene_spec_v03.json",
                "sha256": "d" * 64,
                "byte_size": 20,
            },
        ],
        "canonical_write_requested": False,
        "destination_project_write": False,
    }


def test_geometry_completion_requires_exact_order_and_execution() -> None:
    """Reject reordered, undeclared, or execution-unbound controller completion bytes."""

    payload = _completion_payload()
    completion = GeometryAuthoringCompletionV2.model_validate(payload)
    assert completion.execution_id == "exec-geometry"

    reordered = {**payload, "outputs": list(reversed(payload["outputs"]))}
    with pytest.raises(ValidationError, match="modeling_plan.json then"):
        GeometryAuthoringCompletionV2.model_validate(reordered)

    missing_execution = dict(payload)
    del missing_execution["execution_id"]
    with pytest.raises(ValidationError, match="execution_id"):
        GeometryAuthoringCompletionV2.model_validate(missing_execution)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GeometryAuthoringCompletionV2.model_validate({**payload, "extra": True})


def test_geometry_and_material_validation_have_distinct_transitions() -> None:
    """Route geometry to material authoring and only material validation to quality."""

    state = _candidate_state()
    geometry_receipt = _artifact(
        "geometry-receipt",
        "geometry_candidate_validation_receipt",
    )
    material_boundary = transition_state(
        state,
        event="candidate_validated",
        evidence=geometry_receipt,
        created_at=NOW,
    )
    assert (
        material_boundary.phase,
        material_boundary.status,
        material_boundary.next_action,
    ) == ("authoring", "running", "execute_controller")

    material_result = _artifact("material-result", "controller_result")
    material_candidate = material_boundary.model_copy(
        update={
            "sequence": material_boundary.sequence + 1,
            "next_action": "validate_candidate",
            "provenance": [*material_boundary.provenance, material_result],
        }
    )
    material_receipt = _artifact("material-receipt", "material_phase_receipt")
    quality_boundary = transition_state(
        material_candidate,
        event="material_candidate_validated",
        evidence=material_receipt,
        created_at=NOW,
    )
    assert (
        quality_boundary.phase,
        quality_boundary.status,
        quality_boundary.next_action,
    ) == ("quality", "running", "run_integrated_quality")


def test_bridge_phase_order_rejects_duplicate_or_tampered_geometry_receipts(
) -> None:
    """Keep direct bridge calls at geometry until one exact host receipt exists."""

    state = _candidate_state()
    plan = AutonomyPlanV2.model_construct(
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
    )
    root = Path.cwd()
    assert _required_authoring_profile(root, plan, state) == "geometry_authoring"

    duplicate = _artifact(
        "duplicate-geometry-receipt",
        "geometry_candidate_validation_receipt",
    )
    duplicated_state = state.model_copy(
        update={"provenance": [*state.provenance, duplicate, duplicate]}
    )
    with pytest.raises(ValueError, match="multiple geometry promotion receipts"):
        _required_authoring_profile(root, plan, duplicated_state)

    receipt_artifact = _artifact(
        "tampered-geometry-receipt",
        "geometry_candidate_validation_receipt",
    )
    tampered_state = state.model_copy(
        update={"provenance": [*state.provenance, receipt_artifact]}
    )
    with patch(
        "codex_blender_modeler.autonomy_v2.controller_bridge."
        "validate_geometry_candidate_validation_receipt_v2",
        side_effect=ValueError("geometry receipt changed"),
    ):
        with pytest.raises(ValueError, match="changed"):
            _required_authoring_profile(root, plan, tampered_state)


def test_material_waiting_boundary_retains_geometry_receipt_phase_order() -> None:
    """Allow one material desktop wait only after the exact geometry promotion receipt."""

    candidate = _candidate_state()
    receipt_artifact = _artifact(
        "geometry-promotion",
        "geometry_candidate_validation_receipt",
    )
    material_boundary = transition_state(
        candidate,
        event="candidate_validated",
        evidence=receipt_artifact,
        created_at=NOW,
    )
    waiting_result = _artifact("material-waiting", "controller_result")
    waiting_usage = material_boundary.budget_usage.model_copy(
        update={"controller_invocations": 1, "total_actions": 1}
    )
    waiting = transition_state(
        material_boundary,
        event="controller_required",
        evidence=waiting_result,
        created_at=NOW,
        budget_usage=waiting_usage,
        reason="controller output is not yet complete",
    )
    plan = AutonomyPlanV2.model_construct(
        job_id=waiting.job_id,
        workflow_id=waiting.workflow_id,
        dispatch_id=waiting.dispatch_id,
        session_id=waiting.session_id,
    )
    receipt = SimpleNamespace(
        job_id=waiting.job_id,
        workflow_id=waiting.workflow_id,
        dispatch_id=waiting.dispatch_id,
        session_id=waiting.session_id,
        budget_usage_after=material_boundary.budget_usage,
    )
    with patch(
        "codex_blender_modeler.autonomy_v2.controller_bridge."
        "validate_geometry_candidate_validation_receipt_v2",
        return_value=receipt,
    ):
        assert _required_authoring_profile(Path.cwd(), plan, waiting) == (
            "material_authoring"
        )


def test_grouped_promotion_rollback_restores_old_and_removes_new_targets(
    tmp_path: Path,
) -> None:
    """Restore archived bytes and remove only transaction-created canonical files."""

    root = tmp_path / "job"
    (root / "analysis").mkdir(parents=True)
    (root / "staging").mkdir()
    existing_target = root / "analysis/modeling_plan.json"
    new_target = root / "analysis/scene_spec.json"
    existing_target.write_bytes(b"old-modeling-plan")
    candidate_modeling = root / "staging/modeling.json"
    candidate_scene = root / "staging/scene.json"
    candidate_modeling.write_bytes(b"new-modeling-plan")
    candidate_scene.write_bytes(b"new-scene")
    modeling_artifact = artifact_for_v2(
        root,
        candidate_modeling,
        artifact_id="candidate-modeling",
        kind="candidate_modeling_plan",
    )
    scene_artifact = artifact_for_v2(
        root,
        candidate_scene,
        artifact_id="candidate-scene",
        kind="compiled_scene_spec_v02",
    )
    baselines = [
        _archive_baseline(
            root=root,
            session_id="aqv2-rollback-test",
            target=existing_target,
            candidate=modeling_artifact,
        ),
        _archive_baseline(
            root=root,
            session_id="aqv2-rollback-test",
            target=new_target,
            candidate=scene_artifact,
        ),
    ]
    existing_target.write_bytes(candidate_modeling.read_bytes())
    new_target.write_bytes(candidate_scene.read_bytes())

    _rollback_canonical_files(root, baselines)

    assert existing_target.read_bytes() == b"old-modeling-plan"
    assert not new_target.exists()
