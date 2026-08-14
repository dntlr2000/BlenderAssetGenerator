"""Focused supervisor dispatch tests for stabilized material-closure promotion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from codex_blender_modeler.autonomy_v2 import supervisor_service
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialClosurePromotionBoundaryV2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyStateV2,
    RootAuthorizationV2,
)
from codex_blender_modeler.blender_artifacts import (
    sha256_file,
    stable_json_digest,
    write_json_atomic,
)
from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialAppearanceApprovalConsumptionReceipt,
)
from codex_blender_modeler.production.controller_executor import (
    ControllerArtifact,
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
)

NOW = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _write_json(path: Path, value: object) -> None:
    """Write one deterministic model or raw JSON fixture."""

    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)


def _controller_artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    role: str,
) -> ControllerArtifact:
    """Bind one existing fixture file to the controller artifact contract."""

    return ControllerArtifact(
        artifact_id=artifact_id,
        role=role,
        path=path.relative_to(root).as_posix(),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
    )


def _nested_artifact(name: str, index: int) -> AQV2Artifact:
    """Create one unique strict nested boundary artifact without publishing its bytes."""

    token = name.replace("_", "-")
    return AQV2Artifact(
        artifact_id=token,
        kind="fixture-evidence",
        path=f"production/material_closure/session-supervisor/evidence/{index:02d}-{name}.json",
        sha256=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        byte_size=index + 1,
    )


def _closure_boundary() -> MaterialClosurePromotionBoundaryV2:
    """Build one strict promotion boundary sufficient for supervisor type dispatch."""

    names = (
        "current_state",
        "dependency_closure",
        "dependency_closure_receipt",
        "graph_rebinding_receipt",
        "preflight_report",
        "shadow_compile_receipt",
        "neutral_preview_manifest",
        "appearance_approval",
        "state_consistency_report",
        "candidate_material_plan",
        "rebound_material_graph",
    )
    named = {
        name: _nested_artifact(name, index)
        for index, name in enumerate(names, start=1)
    }
    return MaterialClosurePromotionBoundaryV2(
        contract_id="material-closure-boundary-supervisor",
        boundary_id="material-closure-boundary-supervisor",
        job_id="supervisor_material_job",
        workflow_id="workflow-supervisor-material",
        dispatch_id="dispatch-supervisor-material",
        session_id="session-supervisor",
        input_sha256="1" * 64,
        source_fingerprint="2" * 64,
        producer="tests.supervisor-material",
        provenance=list(named.values()),
        created_at=NOW,
        **named,
        immutable_input_sha256={"evidence/source.json": "3" * 64},
        planned_output_sha256={
            "outputs/material_plan.json": "4" * 64,
            "outputs/material_graph.json": "5" * 64,
        },
        canonical_scene_spec_sha256="6" * 64,
        canonical_blend_sha256="7" * 64,
        uv_layout_fingerprint="8" * 64,
    )


@dataclass(frozen=True)
class _SupervisorFixture:
    """Hold one exact controller result at the supervisor validation boundary."""

    root: Path
    session_root: Path
    plan: AutonomyPlanV2
    budget: AutonomyBudgetV2
    state: AutonomyStateV2
    result_artifact: AQV2Artifact
    profile_artifact: AQV2Artifact
    boundary: MaterialClosurePromotionBoundaryV2 | None
    boundary_artifact: AQV2Artifact | None
    consumption_artifact: AQV2Artifact | None


def _fixture(
    tmp_path: Path,
    *,
    closure: bool,
    publish_consumption: bool = True,
) -> _SupervisorFixture:
    """Publish one real request/result chain with a closure or legacy assignment."""

    root = tmp_path / "workspaces" / "supervisor_material_job"
    root.mkdir(parents=True)
    session_id = "session-supervisor"
    session_root = root / "production" / "autonomy_v2" / session_id

    source_path = root / "production" / "profile-source.json"
    _write_json(source_path, {"source": "supervisor"})
    source = _controller_artifact(
        root,
        source_path,
        artifact_id="profile-source",
        role="profile-source",
    )
    output_root = (
        f"production/autonomy_v2/{session_id}/controller_executions/"
        "execution-supervisor/outputs"
    )
    output_path = f"{output_root}/material_plan.json"
    profile = PhaseToolProfile(
        contract_id="profile-supervisor-material",
        job_id="supervisor_material_job",
        workflow_id="workflow-supervisor-material",
        dispatch_id="dispatch-supervisor-material",
        session_id=session_id,
        input_sha256=source.sha256,
        source_fingerprint=stable_json_digest({"source": source.sha256}),
        producer="tests.supervisor-material",
        provenance=[source],
        created_at=NOW,
        profile_id="material_authoring",
        allowed_tools=[],
        forbidden_tools=["arbitrary_python"],
        allowed_input_roles=["assignment", "material-source"],
        allowed_output_paths=[output_path],
    )
    profile_path = session_root / "tool_profiles" / "material_authoring.json"
    _write_json(profile_path, profile)
    profile_controller = _controller_artifact(
        root,
        profile_path,
        artifact_id=profile.contract_id,
        role="tool_profile",
    )
    profile_artifact = artifact_for_v2(
        root,
        profile_path,
        artifact_id=profile.contract_id,
        kind="controller_phase_tool_profile",
    )

    boundary = _closure_boundary() if closure else None
    assignment_path = session_root / "assignments" / "material.json"
    _write_json(
        assignment_path,
        boundary if boundary is not None else {"phase": "material_authoring"},
    )
    assignment = _controller_artifact(
        root,
        assignment_path,
        artifact_id=(
            boundary.contract_id if boundary is not None else "legacy-material-assignment"
        ),
        role="assignment",
    )
    boundary_artifact = (
        artifact_for_v2(
            root,
            assignment_path,
            artifact_id=boundary.contract_id,
            kind="material-controller-assignment",
        )
        if boundary is not None
        else None
    )

    immutable_path = root / "input" / "reference.bin"
    immutable_path.parent.mkdir(parents=True)
    immutable_path.write_bytes(b"supervisor-material-source")
    immutable_input = _controller_artifact(
        root,
        immutable_path,
        artifact_id="material-source",
        role="material-source",
    )
    request = ControllerExecutionRequest(
        contract_id="request-supervisor-material",
        job_id="supervisor_material_job",
        workflow_id="workflow-supervisor-material",
        dispatch_id="dispatch-supervisor-material",
        session_id=session_id,
        input_sha256=immutable_input.sha256,
        source_fingerprint=stable_json_digest(
            {"assignment": assignment.sha256, "profile": profile_controller.sha256}
        ),
        producer="tests.supervisor-material",
        provenance=[assignment, immutable_input, profile_controller],
        created_at=NOW,
        execution_id="execution-supervisor",
        controller_kind="fake_for_tests",
        assignment=assignment,
        immutable_inputs=[immutable_input],
        tool_profile=profile_controller,
        output_root=output_root,
        allowed_output_paths=[output_path],
        timeout_seconds=30,
    )
    request_path = (
        session_root
        / "controller_executions"
        / request.execution_id
        / "request.json"
    )
    _write_json(request_path, request)
    request_controller = _controller_artifact(
        root,
        request_path,
        artifact_id=request.contract_id,
        role="controller-request",
    )
    request_artifact = artifact_for_v2(
        root,
        request_path,
        artifact_id=request.contract_id,
        kind="controller-request",
    )

    output_file = root.joinpath(*output_path.split("/"))
    _write_json(output_file, {"candidate": "material"})
    output = _controller_artifact(
        root,
        output_file,
        artifact_id="material-output",
        role="material-output",
    )
    result = ControllerResult(
        contract_id="result-supervisor-material",
        job_id="supervisor_material_job",
        workflow_id="workflow-supervisor-material",
        dispatch_id="dispatch-supervisor-material",
        session_id=session_id,
        input_sha256=request_controller.sha256,
        source_fingerprint=stable_json_digest({"request": request_controller.sha256}),
        producer="tests.supervisor-material",
        provenance=[request_controller, profile_controller, output],
        created_at=NOW,
        execution_id=request.execution_id,
        controller_kind="fake_for_tests",
        status="completed",
        request=request_controller,
        tool_profile=profile_controller,
        outputs=[output],
        output_inventory_sha256=stable_json_digest({"output": output.sha256}),
        started_at=NOW,
        completed_at=NOW,
    )
    result_path = request_path.with_name("result.json")
    _write_json(result_path, result)
    result_artifact = artifact_for_v2(
        root,
        result_path,
        artifact_id=result.contract_id,
        kind="controller_result",
    )

    anchor = artifact_for_v2(
        root,
        source_path,
        artifact_id="aq-anchor",
        kind="fixture",
    )
    budget = AutonomyBudgetV2(
        contract_id="budget-supervisor-material",
        budget_id="budget-supervisor-material",
        job_id="supervisor_material_job",
        workflow_id="workflow-supervisor-material",
        dispatch_id="dispatch-supervisor-material",
        session_id=session_id,
        input_sha256=anchor.sha256,
        source_fingerprint=stable_json_digest({"anchor": anchor.sha256}),
        producer="tests.supervisor-material",
        provenance=[anchor],
        created_at=NOW,
    )
    plan = AutonomyPlanV2(
        contract_id="plan-supervisor-material",
        plan_id="plan-supervisor-material",
        job_id="supervisor_material_job",
        workflow_id="workflow-supervisor-material",
        dispatch_id="dispatch-supervisor-material",
        session_id=session_id,
        input_sha256=anchor.sha256,
        source_fingerprint=stable_json_digest({"profile": profile_artifact.sha256}),
        producer="tests.supervisor-material",
        provenance=[anchor, profile_artifact],
        created_at=NOW,
        profile=anchor,
        root_authorization=anchor,
        budget=anchor,
        production_dispatch_plan=anchor,
        production_controller_plan=anchor,
        phase_tool_profiles=[profile_artifact],
        requested_delivery_profiles=["review_only"],
    )
    plan_path = session_root / "plan.json"
    _write_json(plan_path, plan)
    plan_artifact = artifact_for_v2(
        root,
        plan_path,
        artifact_id=plan.contract_id,
        kind="plan",
    )
    state = AutonomyStateV2(
        contract_id="state-session-supervisor-0002",
        state_id="state-session-supervisor-0002",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=plan_artifact.sha256,
        source_fingerprint=stable_json_digest({"result": result_artifact.sha256}),
        producer="tests.supervisor-material",
        provenance=[plan_artifact, result_artifact],
        created_at=NOW,
        plan=plan_artifact,
        sequence=2,
        phase="authoring",
        status="running",
        next_action="validate_candidate",
    )

    consumption_artifact: AQV2Artifact | None = None
    if boundary is not None and publish_consumption:
        receipt = MaterialAppearanceApprovalConsumptionReceipt(
            receipt_id=f"approval-consumption-{request.execution_id}",
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            producer="codex_blender_modeler.autonomy_v2.controller_bridge",
            producer_version="0.1.0",
            created_at=NOW,
            approval=ExactArtifact(
                artifact_id=boundary.appearance_approval.artifact_id,
                kind="appearance_approval",
                path=boundary.appearance_approval.path,
                sha256=boundary.appearance_approval.sha256,
                byte_size=boundary.appearance_approval.byte_size,
                media_type="application/json",
            ),
            controller_request=ExactArtifact(
                artifact_id=request_artifact.artifact_id,
                kind="controller_request",
                path=request_artifact.path,
                sha256=request_artifact.sha256,
                byte_size=request_artifact.byte_size,
                media_type="application/json",
            ),
            approval_id="approval-supervisor-material",
            candidate_material_plan_sha256=boundary.candidate_material_plan.sha256,
            rebound_material_graph_sha256=boundary.rebound_material_graph.sha256,
            closure_sha256="9" * 64,
            preflight_report_sha256=boundary.preflight_report.sha256,
            neutral_preview_sha256=boundary.neutral_preview_manifest.sha256,
        )
        receipt_path = (
            session_root
            / "material_closure"
            / "approval_consumptions"
            / f"{request.execution_id}.json"
        )
        _write_json(receipt_path, receipt)
        consumption_artifact = artifact_for_v2(
            root,
            receipt_path,
            artifact_id=receipt.receipt_id,
            kind="material-approval-consumption",
        )
    return _SupervisorFixture(
        root=root,
        session_root=session_root,
        plan=plan,
        budget=budget,
        state=state,
        result_artifact=result_artifact,
        profile_artifact=profile_artifact,
        boundary=boundary,
        boundary_artifact=boundary_artifact,
        consumption_artifact=consumption_artifact,
    )


def _promotion_result(
    fixture: _SupervisorFixture,
) -> tuple[SimpleNamespace, AQV2Artifact]:
    """Create one host-promotion-shaped result for supervisor transition tests."""

    path = fixture.session_root / "material_phase" / "promotion_receipt.json"
    _write_json(path, {"status": "promoted"})
    artifact = artifact_for_v2(
        fixture.root,
        path,
        artifact_id="material-promotion-receipt",
        kind="material_phase_receipt",
    )
    usage = fixture.state.budget_usage.model_copy(
        update={"material_rounds": 1, "total_actions": 1}
    )
    return SimpleNamespace(budget_usage_after=usage), artifact


def _authorization() -> RootAuthorizationV2:
    """Provide an unused typed authorization sentinel for the material-only boundary."""

    return cast(RootAuthorizationV2, object())


def test_supervisor_dispatches_exact_closure_assignment_to_stabilized_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route a strict closure assignment through its consumption-bound host wrapper."""

    fixture = _fixture(tmp_path, closure=True)
    called: dict[str, object] = {}

    def promote_closure(*args: object, **kwargs: object) -> object:
        """Capture the stabilized promotion call and return transition evidence."""

        called["args"] = args
        called["kwargs"] = kwargs
        return _promotion_result(fixture)

    monkeypatch.setattr(
        supervisor_service,
        "validate_and_promote_material_closure_controller_result_v2",
        promote_closure,
    )
    monkeypatch.setattr(
        supervisor_service,
        "validate_and_promote_material_controller_result_v2",
        lambda *_args, **_kwargs: pytest.fail("legacy promotion must not run"),
    )
    response = supervisor_service._controller_validation_boundary(
        fixture.root,
        fixture.session_root,
        fixture.plan,
        fixture.budget,
        fixture.state,
        _authorization(),
    )
    assert response["advanced"] is True
    assert response["outcome"] == "material_candidate_validated"
    assert called["kwargs"] == {
        "boundary_artifact": fixture.boundary_artifact,
        "approval_consumption_artifact": fixture.consumption_artifact,
    }
    assert response["state"]["phase"] == "quality"
    assert response["state"]["next_action"] == "run_integrated_quality"


def test_supervisor_blocks_closure_before_promotion_when_consumption_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed before either promotion function when consumption is absent."""

    fixture = _fixture(tmp_path, closure=True, publish_consumption=False)
    promotion_called = False

    def reject_promotion(*_args: object, **_kwargs: object) -> object:
        """Record any unsafe attempt to enter a promotion function."""

        nonlocal promotion_called
        promotion_called = True
        return _promotion_result(fixture)

    monkeypatch.setattr(
        supervisor_service,
        "validate_and_promote_material_closure_controller_result_v2",
        reject_promotion,
    )
    monkeypatch.setattr(
        supervisor_service,
        "validate_and_promote_material_controller_result_v2",
        reject_promotion,
    )
    with pytest.raises(PermissionError, match="approval consumption"):
        supervisor_service._controller_validation_boundary(
            fixture.root,
            fixture.session_root,
            fixture.plan,
            fixture.budget,
            fixture.state,
            _authorization(),
        )
    assert promotion_called is False
    assert not (fixture.session_root / "states" / "0003.json").exists()


def test_supervisor_blocks_ambiguous_consumption_before_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a second receipt that reuses the same exact request and approval."""

    fixture = _fixture(tmp_path, closure=True)
    assert fixture.consumption_artifact is not None
    source = fixture.root / fixture.consumption_artifact.path
    receipt = MaterialAppearanceApprovalConsumptionReceipt.model_validate_json(
        source.read_bytes()
    ).model_copy(update={"receipt_id": "approval-consumption-duplicate"})
    _write_json(source.with_name("duplicate.json"), receipt)
    promotion_called = False

    def reject_promotion(*_args: object, **_kwargs: object) -> object:
        """Record any unsafe attempt to promote ambiguous authority evidence."""

        nonlocal promotion_called
        promotion_called = True
        return _promotion_result(fixture)

    monkeypatch.setattr(
        supervisor_service,
        "validate_and_promote_material_closure_controller_result_v2",
        reject_promotion,
    )
    with pytest.raises(PermissionError, match="missing or ambiguous"):
        supervisor_service._controller_validation_boundary(
            fixture.root,
            fixture.session_root,
            fixture.plan,
            fixture.budget,
            fixture.state,
            _authorization(),
        )
    assert promotion_called is False


def test_supervisor_preserves_legacy_imagegen_material_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep non-closure assignments on the existing guarded legacy promotion path."""

    fixture = _fixture(tmp_path, closure=False)
    import codex_blender_modeler.autonomy_v2.codex_image_material_loop_service as loop

    called: dict[str, object] = {}

    def promote_legacy(*args: object, **kwargs: object) -> object:
        """Capture the unchanged ImageGen-authorized legacy promotion call."""

        called["args"] = args
        called["kwargs"] = kwargs
        return _promotion_result(fixture)

    monkeypatch.setattr(
        loop,
        "validate_codex_image_material_controller_promotion_boundary",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        supervisor_service,
        "validate_and_promote_material_controller_result_v2",
        promote_legacy,
    )
    monkeypatch.setattr(
        supervisor_service,
        "validate_and_promote_material_closure_controller_result_v2",
        lambda *_args, **_kwargs: pytest.fail("closure promotion must not run"),
    )
    response = supervisor_service._controller_validation_boundary(
        fixture.root,
        fixture.session_root,
        fixture.plan,
        fixture.budget,
        fixture.state,
        _authorization(),
    )
    assert response["advanced"] is True
    assert called["kwargs"] == {
        "authorized_profile_artifact": fixture.profile_artifact,
    }
