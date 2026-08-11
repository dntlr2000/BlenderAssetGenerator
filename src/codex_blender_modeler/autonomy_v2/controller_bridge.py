"""Bridge AQ v2 state evidence to one isolated ControllerExecutor invocation."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import cast

from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..production.controller_executor import (
    CandidateAuthoringController,
    ControllerArtifact,
    ControllerExecutionRequest,
    ControllerResult,
    DesktopInSessionController,
    PhaseToolProfile,
    execute_controller_request,
    validate_controller_execution_result,
    write_controller_contract,
)
from ..production.validation import ensure_contained_production_path
from ..workspace import job_dir
from .candidate_validation_service import (
    validate_geometry_candidate_validation_receipt_v2,
)
from .delivery_service import (
    artifact_for_v2,
    validate_delivery_terminal_v2,
    validate_quality_source_freeze,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyCancellationV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    AutonomyStateV2,
    BudgetUsageV2,
    RootAuthorizationV2,
)
from .transitions import (
    transition_state,
    validate_initial_state,
    validate_state_transition,
)


def _read_native_bytes(path: Path) -> bytes:
    """Read one contained contract through the Windows extended-length path."""

    with open(native_io_path(path), "rb") as handle:
        return handle.read()


def _controller_artifact(artifact: AQV2Artifact, *, role: str) -> ControllerArtifact:
    """Project one exact AQ v2 artifact into ControllerExecutor's binding shape."""

    return ControllerArtifact(
        artifact_id=artifact.artifact_id,
        role=role,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _read_aq_model(
    root: Path,
    artifact: AQV2Artifact,
    model: type[AutonomyPlanV2]
    | type[AutonomyBudgetV2]
    | type[AutonomyProfileV2]
    | type[RootAuthorizationV2]
    | type[AutonomyStateV2],
) -> (
    AutonomyPlanV2
    | AutonomyBudgetV2
    | AutonomyProfileV2
    | RootAuthorizationV2
    | AutonomyStateV2
):
    """Rehash and strict-parse one supported AQ v2 session model."""

    path = validate_v2_artifact(root, artifact)
    return model.model_validate_json(_read_native_bytes(path))


def _required_authoring_profile(
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
) -> str:
    """Require geometry first and material after one exact current promotion boundary."""

    receipts = [
        item
        for item in state.provenance
        if item.kind == "geometry_candidate_validation_receipt"
    ]
    if not receipts:
        return "geometry_authoring"
    if len(receipts) != 1:
        raise ValueError("AQ v2 state contains multiple geometry promotion receipts")
    receipt_index = -2 if state.status == "waiting_for_controller" else -1
    if len(state.provenance) < abs(receipt_index) or state.provenance[receipt_index] != receipts[0]:
        raise ValueError("geometry promotion receipt is not the current authoring boundary")
    receipt = validate_geometry_candidate_validation_receipt_v2(
        root,
        plan,
        receipts[0],
    )
    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    if (
        receipt.job_id,
        receipt.workflow_id,
        receipt.dispatch_id,
        receipt.session_id,
    ) != identity:
        raise ValueError("geometry promotion receipt belongs to another AQ v2 session")
    expected_usage = receipt.budget_usage_after
    if state.status == "waiting_for_controller":
        expected_usage = expected_usage.model_copy(
            update={
                "controller_invocations": expected_usage.controller_invocations + 1,
                "total_actions": expected_usage.total_actions + 1,
            }
        )
    if state.budget_usage != expected_usage:
        raise ValueError("AQ v2 state did not adopt geometry candidate budget usage")
    return "material_authoring"


def _validate_controller_result_outputs(
    root: Path,
    result_path: Path,
    *,
    include_execution_provenance: bool = False,
) -> None:
    """Re-hash stable result bindings and optionally its live execution provenance."""

    result = ControllerResult.model_validate_json(_read_native_bytes(result_path))
    artifacts = [result.request, result.tool_profile, *result.outputs]
    if include_execution_provenance:
        artifacts.extend(result.provenance)
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        identity = (artifact.path, artifact.sha256)
        if identity in seen:
            continue
        seen.add(identity)
        observed = artifact_for_v2(
            root,
            root / artifact.path,
            artifact_id=artifact.artifact_id,
            kind=artifact.role,
        )
        if observed.sha256 != artifact.sha256 or observed.byte_size != artifact.byte_size:
            raise ValueError(
                f"controller result nested artifact changed: {artifact.path}"
            )


def _state_chain(
    root: Path,
    session_root: Path,
) -> list[tuple[AutonomyStateV2, AQV2Artifact]]:
    """Reconstruct every immutable state and reject gaps, splices, or stale provenance."""

    states_root = ensure_contained_production_path(
        root,
        session_root / "states",
        must_exist=True,
    )
    paths = sorted(states_root.glob("*.json"))
    if not paths:
        raise FileNotFoundError("AQ v2 session has no immutable state")
    chain: list[tuple[AutonomyStateV2, AQV2Artifact]] = []
    previous: AutonomyStateV2 | None = None
    for expected_sequence, path in enumerate(paths):
        safe_path = ensure_contained_production_path(root, path, must_exist=True)
        state = AutonomyStateV2.model_validate_json(_read_native_bytes(safe_path))
        if state.sequence != expected_sequence or path.stem != f"{expected_sequence:04d}":
            raise ValueError("AQ v2 state sequence is incomplete or misnamed")
        for provenance in state.provenance:
            provenance_path = validate_v2_artifact(root, provenance)
            if provenance_path.name == "result.json":
                _validate_controller_result_outputs(root, provenance_path)
        if previous is None:
            validate_initial_state(state)
        else:
            validate_state_transition(previous, state)
        artifact = artifact_for_v2(
            root,
            safe_path,
            artifact_id=state.state_id,
            kind="autonomy_v2_state",
        )
        chain.append((state, artifact))
        previous = state
    return chain


def _validate_state_terminal_evidence(
    root: Path,
    state: AutonomyStateV2,
) -> None:
    """Revalidate current quality and delivery terminals through their nested evidence."""

    if state.source_freeze is not None:
        freeze_path = validate_v2_artifact(root, state.source_freeze)
        from .models import QualityApprovedSourceFreeze

        freeze = QualityApprovedSourceFreeze.model_validate_json(
            _read_native_bytes(freeze_path)
        )
        validate_quality_source_freeze(root, freeze)
    if state.quality_terminal is not None:
        from .quality_terminal_service import validate_quality_terminal_v2

        quality_terminal = validate_quality_terminal_v2(root, state.quality_terminal)
        if quality_terminal.source_freeze != state.source_freeze:
            raise ValueError("AQ v2 state and quality terminal use different freezes")
    if state.delivery_terminal is not None:
        terminal = validate_delivery_terminal_v2(root, state.delivery_terminal)
        if terminal.results != state.delivery_results:
            raise ValueError("AQ v2 state delivery results differ from its terminal")


def _session_bundle(
    job_id: str,
    session_id: str,
) -> tuple[
    Path,
    Path,
    AutonomyPlanV2,
    AutonomyBudgetV2,
    AutonomyStateV2,
    AQV2Artifact,
]:
    """Load the exact plan, budget, and current state for one AQ v2 session."""

    root = job_dir(job_id)
    session_root = ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / session_id,
        must_exist=True,
    )
    plan_path = ensure_contained_production_path(
        root,
        session_root / "plan.json",
        must_exist=True,
    )
    plan_artifact = artifact_for_v2(
        root,
        plan_path,
        artifact_id=f"plan-{session_id}",
        kind="plan",
    )
    plan = cast(
        AutonomyPlanV2,
        _read_aq_model(root, plan_artifact, AutonomyPlanV2),
    )
    budget = cast(
        AutonomyBudgetV2,
        _read_aq_model(root, plan.budget, AutonomyBudgetV2),
    )
    state, state_artifact = _state_chain(root, session_root)[-1]
    if (
        (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
        != (state.job_id, state.workflow_id, state.dispatch_id, state.session_id)
        or plan.job_id != job_id
        or plan.session_id != session_id
        or state.plan != plan_artifact
    ):
        raise ValueError("AQ v2 session identity or plan binding is inconsistent")
    usage = state.budget_usage
    limits = {
        "initial_candidates": budget.initial_candidates,
        "structural_rounds": budget.structural_rounds,
        "parametric_convergence_iterations": budget.parametric_convergence_iterations,
        "material_rounds": budget.material_rounds,
        "total_blender_builds": budget.total_blender_builds,
        "total_quality_evaluations": budget.total_quality_evaluations,
        "controller_invocations": budget.controller_invocations,
        "delivery_runs": budget.delivery_runs,
        "canonical_promotions": budget.canonical_promotions,
        "package_repairs": budget.package_repairs,
        "total_actions": min(budget.global_action_limit, plan.action_limit),
    }
    observed_usage = usage.model_dump()
    if any(observed_usage[key] > limit for key, limit in limits.items()):
        raise ValueError("AQ v2 state budget usage exceeds its immutable authorization")
    _validate_state_terminal_evidence(root, state)
    return root, session_root, plan, budget, state, state_artifact


def _validate_controller_authority(
    root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
) -> None:
    """Recompute the exact active authorization, profile, budget, and plan bindings."""

    authorization = cast(
        RootAuthorizationV2,
        _read_aq_model(root, plan.root_authorization, RootAuthorizationV2),
    )
    profile = cast(
        AutonomyProfileV2,
        _read_aq_model(root, plan.profile, AutonomyProfileV2),
    )
    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    if any(
        (item.job_id, item.workflow_id, item.dispatch_id, item.session_id) != identity
        for item in (authorization, profile, budget)
    ):
        raise ValueError("AQ v2 controller authority identity differs from its plan")
    if authorization.status != "active":
        raise PermissionError("AQ v2 root authorization is not active")
    if authorization.expires_at is not None and authorization.expires_at <= datetime.now(UTC):
        raise PermissionError("AQ v2 root authorization has expired")
    if any(
        item.producer != "codex_blender_modeler.autonomy_v2.planner"
        for item in (authorization, profile, budget, plan)
    ):
        raise ValueError("AQ v2 controller authority was not emitted by the planner")
    if (
        authorization.profile != plan.profile
        or authorization.budget != plan.budget
        or authorization.phase_tool_profiles != plan.phase_tool_profiles
        or authorization.requested_delivery_profiles != plan.requested_delivery_profiles
    ):
        raise PermissionError(
            "AQ v2 controller plan exceeds its exact root authorization bindings"
        )

    for artifact in [*plan.provenance, *authorization.provenance]:
        validate_v2_artifact(root, artifact)
    if len(authorization.provenance) != len(plan.phase_tool_profiles) + 6:
        raise ValueError("AQ v2 root authorization provenance has an invalid shape")
    workflow_request = authorization.provenance[1]
    expected_authorization_provenance = [
        authorization.primary_reference,
        workflow_request,
        plan.profile,
        plan.budget,
        authorization.production_launch_or_binding,
        authorization.quality_profile,
        *plan.phase_tool_profiles,
    ]
    if (
        workflow_request.kind != "workflow_request"
        or authorization.provenance != expected_authorization_provenance
    ):
        raise ValueError("AQ v2 root authorization provenance differs from its bindings")
    authorization_inputs = {
        "request": authorization.original_request_sha256,
        "primary_reference": authorization.primary_reference.sha256,
        "profile": plan.profile.sha256,
        "budget": plan.budget.sha256,
        "launch": authorization.production_launch_or_binding.sha256,
        "quality_policy": authorization.quality_profile.sha256,
        "phase_profiles": [item.sha256 for item in plan.phase_tool_profiles],
        "requested_deliveries": plan.requested_delivery_profiles,
        "target_subject": authorization.target_subject,
    }
    if (
        authorization.input_sha256 != stable_json_digest(authorization_inputs)
        or authorization.source_fingerprint
        != stable_json_digest(
            {
                **authorization_inputs,
                "destination_hint": authorization.destination_hint,
            }
        )
    ):
        raise ValueError("AQ v2 root authorization digest is inconsistent")

    budget_inputs = {
        "dispatch_plan": plan.production_dispatch_plan.sha256,
        "quality_policy": authorization.quality_profile.sha256,
        "phase_profiles": [item.sha256 for item in plan.phase_tool_profiles],
    }
    expected_budget_provenance = [
        plan.production_dispatch_plan,
        authorization.quality_profile,
        *plan.phase_tool_profiles,
    ]
    if (
        budget.provenance != expected_budget_provenance
        or budget.input_sha256 != stable_json_digest(budget_inputs)
        or budget.source_fingerprint
        != stable_json_digest(
            {**budget_inputs, "profile": "autonomous_static_prop_v2"}
        )
    ):
        raise ValueError("AQ v2 controller budget binding is inconsistent")

    profile_inputs = {
        "budget": plan.budget.sha256,
        "quality_policy": authorization.quality_profile.sha256,
        "phase_profiles": [item.sha256 for item in plan.phase_tool_profiles],
    }
    expected_profile_provenance = [
        plan.budget,
        authorization.quality_profile,
        *plan.phase_tool_profiles,
    ]
    if (
        profile.profile_id != "autonomous_static_prop_v2"
        or profile.provenance != expected_profile_provenance
        or profile.input_sha256 != stable_json_digest(profile_inputs)
        or profile.source_fingerprint
        != stable_json_digest({**profile_inputs, "status": profile.status})
    ):
        raise ValueError("AQ v2 controller profile binding is inconsistent")

    plan_inputs = {
        "profile": plan.profile.sha256,
        "authorization": plan.root_authorization.sha256,
        "budget": plan.budget.sha256,
        "dispatch": plan.production_dispatch_plan.sha256,
        "controller": plan.production_controller_plan.sha256,
        "phase_profiles": [item.sha256 for item in plan.phase_tool_profiles],
    }
    expected_plan_provenance = [
        plan.profile,
        plan.root_authorization,
        plan.budget,
        plan.production_dispatch_plan,
        plan.production_controller_plan,
        *plan.phase_tool_profiles,
    ]
    if (
        plan.provenance != expected_plan_provenance
        or plan.input_sha256 != stable_json_digest(plan_inputs)
        or plan.source_fingerprint
        != stable_json_digest(
            {**plan_inputs, "requested_deliveries": plan.requested_delivery_profiles}
        )
        or plan.action_limit != budget.global_action_limit
    ):
        raise ValueError("AQ v2 controller plan binding is inconsistent")


def _phase_profile(
    root: Path,
    plan: AutonomyPlanV2,
    profile_id: str,
) -> tuple[PhaseToolProfile, AQV2Artifact]:
    """Select and revalidate one plan-authorized phase profile exactly once."""

    matches: list[tuple[PhaseToolProfile, AQV2Artifact]] = []
    for artifact in plan.phase_tool_profiles:
        path = validate_v2_artifact(root, artifact)
        profile = PhaseToolProfile.model_validate_json(_read_native_bytes(path))
        if profile.profile_id == profile_id:
            matches.append((profile, artifact))
    if len(matches) != 1:
        raise ValueError("AQ v2 plan must contain exactly one requested phase profile")
    return matches[0]


def _consume_controller_budget(
    usage: BudgetUsageV2,
    budget: AutonomyBudgetV2,
) -> BudgetUsageV2:
    """Consume exactly one bounded controller action before external work starts."""

    updated = usage.model_copy(
        update={
            "controller_invocations": usage.controller_invocations + 1,
            "total_actions": usage.total_actions + 1,
        }
    )
    if updated.controller_invocations > budget.controller_invocations:
        raise PermissionError("AQ v2 controller invocation budget is exhausted")
    if updated.total_actions > budget.global_action_limit:
        raise PermissionError("AQ v2 global action budget is exhausted")
    return updated


def _write_or_adopt_request(
    root: Path,
    path: Path,
    request: ControllerExecutionRequest,
) -> ControllerExecutionRequest:
    """Publish a request once or adopt only an exact crash-interrupted request."""

    if os.path.exists(native_io_path(path)):
        existing = ControllerExecutionRequest.model_validate_json(
            _read_native_bytes(path)
        )
        if existing.model_dump(mode="json", exclude={"created_at"}) != request.model_dump(
            mode="json",
            exclude={"created_at"},
        ):
            raise ValueError("existing controller request differs from the current action")
        return existing
    ensure_contained_production_path(root, path, must_exist=False)
    write_controller_contract(path, request)
    return request


def _pending_controller_request(
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
) -> tuple[ControllerExecutionRequest, Path, str]:
    """Reconstruct one exact desktop request that produced the current waiting state."""

    if state.status != "waiting_for_controller" or state.next_action != "execute_controller":
        raise PermissionError("AQ v2 state has no pending controller execution to resume")
    chain = _state_chain(root, session_root)
    if len(chain) < 2 or chain[-1][0] != state:
        raise ValueError("AQ v2 pending state is not the current immutable chain head")
    previous = chain[-2][0]
    if (
        previous.phase,
        previous.status,
        previous.next_action,
    ) != ("authoring", "running", "execute_controller"):
        raise ValueError("AQ v2 pending controller predecessor is not an authoring boundary")
    if not state.provenance:
        raise ValueError("AQ v2 pending state has no request-bound controller result")
    pending_artifact = state.provenance[-1]
    pending_path = validate_v2_artifact(root, pending_artifact)
    result = ControllerResult.model_validate_json(_read_native_bytes(pending_path))
    if result.status != "waiting_for_output" or result.controller_kind != "desktop_in_session":
        raise ValueError("AQ v2 pending result is not a resumable desktop execution")
    expected_usage = _consume_controller_budget(previous.budget_usage, budget)
    if state.budget_usage != expected_usage:
        raise ValueError("AQ v2 pending state did not consume exactly one controller action")
    expected_state = transition_state(
        previous,
        event="controller_required",
        evidence=pending_artifact,
        created_at=state.created_at,
        budget_usage=state.budget_usage,
        reason=state.terminal_reason,
    )
    if expected_state != state:
        raise ValueError("AQ v2 pending state is not the exact waiting transition")

    phase_profile_id = _required_authoring_profile(root, plan, previous)
    profile, profile_artifact = _phase_profile(root, plan, phase_profile_id)
    execution_id = f"exec-{previous.sequence + 1:04d}-{phase_profile_id}"
    request_path = ensure_contained_production_path(
        root,
        session_root / "controller_executions" / execution_id / "request.json",
        must_exist=True,
    )
    request = ControllerExecutionRequest.model_validate_json(
        _read_native_bytes(request_path)
    )
    request_binding = ControllerArtifact(
        artifact_id=request.contract_id,
        role="controller_request",
        path=request_path.relative_to(root).as_posix(),
        sha256=sha256_file(request_path),
        byte_size=os.path.getsize(native_io_path(request_path)),
    )
    expected_profile = _controller_artifact(profile_artifact, role="tool_profile")
    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    if (
        request.job_id,
        request.workflow_id,
        request.dispatch_id,
        request.session_id,
    ) != identity:
        raise ValueError("pending controller request belongs to another AQ v2 session")
    if (
        request.execution_id != execution_id
        or result.execution_id != execution_id
        or request.controller_kind != "desktop_in_session"
        or result.request != request_binding
        or request.tool_profile != expected_profile
        or result.tool_profile != expected_profile
        or request.allowed_output_paths != profile.allowed_output_paths
    ):
        raise ValueError("pending controller request/result/profile binding is inconsistent")
    request_inputs = {
        "state": stable_json_digest(previous.model_dump(mode="json")),
        "assignment": request.assignment.sha256,
        "inputs": [item.sha256 for item in request.immutable_inputs],
        "profile": profile_artifact.sha256,
        "outputs": profile.allowed_output_paths,
    }
    if (
        request.input_sha256 != stable_json_digest(request_inputs)
        or request.source_fingerprint
        != stable_json_digest(
            {**request_inputs, "controller_kind": request.controller_kind}
        )
    ):
        raise ValueError("pending controller request no longer matches its predecessor state")
    expected_pending_path = request_path.parent / "result.json"
    if pending_path != expected_pending_path:
        raise ValueError("AQ v2 waiting result is not located at its exact execution root")
    _validate_controller_result_outputs(
        root,
        pending_path,
        include_execution_provenance=True,
    )
    return request, request_path, phase_profile_id


def _resume_pending_controller_locked(
    *,
    root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
    state_artifact: AQV2Artifact,
) -> dict[str, object]:
    """Adopt exact desktop outputs for one pending request without a second invocation."""

    request, request_path, phase_profile_id = _pending_controller_request(
        root,
        session_root,
        plan,
        budget,
        state,
    )
    completion_path = ensure_contained_production_path(
        root,
        request_path.parent / "adoption" / "result.json",
        must_exist=False,
    )
    recovered_result = os.path.exists(native_io_path(completion_path))
    if recovered_result:
        completion_path = ensure_contained_production_path(
            root,
            completion_path,
            must_exist=True,
        )
        result = validate_controller_execution_result(
            job_root=root,
            request_path=request_path,
            result_path=completion_path,
            controller=DesktopInSessionController(),
        )
        result_artifact = artifact_for_v2(
            root,
            completion_path,
            artifact_id=result.contract_id,
            kind="controller_result",
        )
    else:
        result = execute_controller_request(
            job_root=root,
            request_path=request_path,
            controller=DesktopInSessionController(),
        )
        if result.status == "waiting_for_output":
            return {
                "advanced": False,
                "outcome": "waiting_for_controller",
                "next_action": "execute_controller",
                "phase_profile_id": phase_profile_id,
                "request": request.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
                "state": state.model_dump(mode="json"),
                "state_artifact": state_artifact.model_dump(mode="json"),
            }
        result_artifact = write_immutable_v2_model(
            root,
            completion_path,
            result,
        )
        result = validate_controller_execution_result(
            job_root=root,
            request_path=request_path,
            result_path=completion_path,
            controller=DesktopInSessionController(),
        )
    if (
        result.execution_id != request.execution_id
        or result.controller_kind != request.controller_kind
        or result.request.sha256 != sha256_file(request_path)
        or result.status == "waiting_for_output"
    ):
        raise ValueError("resumed controller result is stale or belongs to another request")
    if result.status == "completed":
        event = "controller_output_ready"
        reason = None
        outcome = "controller_output_ready"
    else:
        event = "failed"
        reason = f"controller resume outcome: {result.status}"
        outcome = "controller_failed"
    next_state = transition_state(
        state,
        event=cast(str, event),
        evidence=result_artifact,
        created_at=datetime.now(UTC),
        budget_usage=state.budget_usage,
        reason=reason,
    )
    next_artifact = write_immutable_v2_model(
        root,
        session_root / "states" / f"{next_state.sequence:04d}.json",
        next_state,
    )
    return {
        "advanced": True,
        "outcome": outcome,
        "recovered_action": recovered_result,
        "phase_profile_id": phase_profile_id,
        "request": request.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "state": next_state.model_dump(mode="json"),
        "state_artifact": next_artifact.model_dump(mode="json"),
    }


def execute_autonomy_v2_controller(
    job_id: str,
    session_id: str,
    *,
    phase_profile_id: str,
    assignment: AQV2Artifact,
    immutable_inputs: list[AQV2Artifact],
    controller: CandidateAuthoringController,
    expected_output_sha256: dict[str, str] | None = None,
    timeout_seconds: int = 900,
) -> dict[str, object]:
    """Run or recover one locked controller action and publish one immutable next state."""

    root, session_root, _plan, _budget, _state, _state_artifact = _session_bundle(
        job_id,
        session_id,
    )
    with autonomy_session_lock(
        root,
        session_root,
        owner_id=f"aqv2-controller-{phase_profile_id}",
        ttl_seconds=max(timeout_seconds + 60, 120),
    ):
        root, session_root, plan, budget, state, state_artifact = _session_bundle(
            job_id,
            session_id,
        )
        _validate_controller_authority(root, plan, budget)
        if state.next_action == "none" or state.status in {
            "cancelled",
            "blocked",
            "failed",
            "completed",
            "partial",
            "review_required",
        }:
            raise PermissionError("terminal AQ v2 session cannot execute a controller")
        if state.next_action != "execute_controller":
            raise PermissionError(
                "current AQ v2 state is not at a controller-authoring boundary"
            )
        if phase_profile_id not in {"geometry_authoring", "material_authoring"}:
            raise PermissionError(
                "AQ v2 controller execution requires an authoring phase profile"
            )
        if state.status == "waiting_for_controller":
            pending_request, _pending_path, pending_profile = _pending_controller_request(
                root,
                session_root,
                plan,
                budget,
                state,
            )
            supplied_assignment = _controller_artifact(assignment, role="assignment")
            supplied_inputs = [
                _controller_artifact(item, role=item.kind) for item in immutable_inputs
            ]
            if (
                phase_profile_id != pending_profile
                or controller.controller_kind != pending_request.controller_kind
                or supplied_assignment != pending_request.assignment
                or supplied_inputs != pending_request.immutable_inputs
                or (
                    expected_output_sha256 is not None
                    and expected_output_sha256
                    != pending_request.expected_output_sha256
                )
            ):
                raise ValueError(
                    "controller resume arguments differ from the exact pending request"
                )
            return _resume_pending_controller_locked(
                root=root,
                session_root=session_root,
                plan=plan,
                budget=budget,
                state=state,
                state_artifact=state_artifact,
            )
        required_profile = _required_authoring_profile(root, plan, state)
        if phase_profile_id != required_profile:
            raise PermissionError(
                f"AQ v2 authoring phase requires {required_profile}, not "
                f"{phase_profile_id}"
            )
        usage = _consume_controller_budget(state.budget_usage, budget)
        profile, profile_artifact = _phase_profile(root, plan, phase_profile_id)
        if not profile.allowed_output_paths:
            raise ValueError("read-only AQ v2 phase has no controller-authoring outputs")
        output_parents = {str(PurePosixPath(path).parent) for path in profile.allowed_output_paths}
        if len(output_parents) != 1:
            raise ValueError("AQ v2 phase outputs must share one isolated output root")
        for artifact in [assignment, *immutable_inputs]:
            validate_v2_artifact(root, artifact)
        execution_id = f"exec-{state.sequence + 1:04d}-{phase_profile_id}"
        execution_root = ensure_contained_production_path(
            root,
            session_root / "controller_executions" / execution_id,
            must_exist=False,
        )
        request_path = execution_root / "request.json"
        request_inputs = {
            "state": stable_json_digest(state.model_dump(mode="json")),
            "assignment": assignment.sha256,
            "inputs": [item.sha256 for item in immutable_inputs],
            "profile": profile_artifact.sha256,
            "outputs": profile.allowed_output_paths,
        }
        request = ControllerExecutionRequest(
            contract_id=f"request-{execution_id}",
            job_id=job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=session_id,
            input_sha256=stable_json_digest(request_inputs),
            source_fingerprint=stable_json_digest(
                {**request_inputs, "controller_kind": controller.controller_kind}
            ),
            producer="codex_blender_modeler.autonomy_v2.controller_bridge",
            provenance=[
                _controller_artifact(assignment, role="assignment"),
                *[
                    _controller_artifact(item, role=item.kind)
                    for item in immutable_inputs
                ],
                _controller_artifact(profile_artifact, role="tool_profile"),
            ],
            created_at=datetime.now(UTC),
            execution_id=execution_id,
            controller_kind=cast(str, controller.controller_kind),
            assignment=_controller_artifact(assignment, role="assignment"),
            immutable_inputs=[
                _controller_artifact(item, role=item.kind)
                for item in immutable_inputs
            ],
            tool_profile=_controller_artifact(profile_artifact, role="tool_profile"),
            output_root=next(iter(output_parents)),
            allowed_output_paths=list(profile.allowed_output_paths),
            expected_output_sha256=expected_output_sha256 or {},
            timeout_seconds=timeout_seconds,
        )
        request = _write_or_adopt_request(root, request_path, request)
        result_path = execution_root / "result.json"
        if os.path.exists(native_io_path(result_path)):
            result = validate_controller_execution_result(
                job_root=root,
                request_path=request_path,
                result_path=result_path,
                controller=controller,
            )
            result_artifact = artifact_for_v2(
                root,
                result_path,
                artifact_id=result.contract_id,
                kind="controller_result",
            )
        else:
            result = execute_controller_request(
                job_root=root,
                request_path=request_path,
                controller=controller,
            )
            result_artifact = write_immutable_v2_model(
                root,
                result_path,
                result,
            )
            result = validate_controller_execution_result(
                job_root=root,
                request_path=request_path,
                result_path=result_path,
                controller=controller,
            )
        if result.status == "completed":
            event = "controller_output_ready"
            reason = None
        elif result.status == "waiting_for_output":
            event = "controller_required"
            reason = "controller output is not yet complete"
        elif result.status == "timeout":
            event = "failed"
            reason = "controller outcome: timeout (nonretryable)"
        else:
            event = "failed"
            reason = f"controller outcome: {result.status}"
        next_state = transition_state(
            state,
            event=cast(str, event),
            evidence=result_artifact,
            created_at=datetime.now(UTC),
            budget_usage=usage,
            reason=reason,
        )
        state_artifact = write_immutable_v2_model(
            root,
            session_root / "states" / f"{next_state.sequence:04d}.json",
            next_state,
        )
        return {
            "request": request.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "state": next_state.model_dump(mode="json"),
            "state_artifact": state_artifact.model_dump(mode="json"),
        }


def get_autonomy_v2_status(job_id: str, session_id: str) -> dict[str, object]:
    """Reconstruct one AQ v2 session read-only from its exact immutable state chain."""

    root, session_root, plan, budget, state, state_artifact = _session_bundle(
        job_id,
        session_id,
    )
    return {
        "profile_status": "disabled_experimental",
        "job_id": job_id,
        "workflow_id": plan.workflow_id,
        "dispatch_id": plan.dispatch_id,
        "session_id": session_id,
        "state": state.model_dump(mode="json"),
        "state_artifact": state_artifact.model_dump(mode="json"),
        "budget": budget.model_dump(mode="json"),
        "session_path": session_root.relative_to(root).as_posix(),
    }


def cancel_autonomy_v2(
    job_id: str,
    session_id: str,
    *,
    reason: str,
) -> dict[str, object]:
    """Cancel future v2 actions under the session lock without deleting any evidence."""

    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("AQ v2 cancellation reason must not be empty")
    root, session_root, _plan, _budget, _state, _artifact = _session_bundle(
        job_id,
        session_id,
    )
    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-cancel",
        ttl_seconds=120,
    ):
        root, session_root, plan, _budget, state, state_artifact = _session_bundle(
            job_id,
            session_id,
        )
        if state.next_action == "none":
            raise PermissionError("terminal AQ v2 session cannot be cancelled again")
        previous_sha = stable_json_digest(state.model_dump(mode="json"))
        cancellation = AutonomyCancellationV2(
            contract_id=f"cancellation-{session_id}",
            cancellation_id=f"cancellation-{session_id}",
            job_id=job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=session_id,
            input_sha256=stable_json_digest(
                {"state": previous_sha, "reason": normalized_reason}
            ),
            source_fingerprint=stable_json_digest(
                {"state": state_artifact.sha256, "status": "cancelled"}
            ),
            producer="codex_blender_modeler.autonomy_v2.controller_bridge",
            provenance=[state_artifact],
            created_at=datetime.now(UTC),
            previous_state_sha256=previous_sha,
            reason=normalized_reason,
        )
        cancellation_artifact = write_immutable_v2_model(
            root,
            session_root / "cancellation.json",
            cancellation,
        )
        next_state = transition_state(
            state,
            event="cancelled",
            evidence=cancellation_artifact,
            created_at=datetime.now(UTC),
            reason=normalized_reason,
        )
        next_artifact = write_immutable_v2_model(
            root,
            session_root / "states" / f"{next_state.sequence:04d}.json",
            next_state,
        )
        return {
            "cancellation": cancellation.model_dump(mode="json"),
            "state": next_state.model_dump(mode="json"),
            "state_artifact": next_artifact.model_dump(mode="json"),
        }
