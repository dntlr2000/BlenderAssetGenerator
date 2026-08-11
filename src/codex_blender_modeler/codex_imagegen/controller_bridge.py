"""Dedicated ControllerExecutor bridge for current-task Codex ImageGen outputs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from ..autonomy_v2.delivery_service import validate_root_authorization_boundary_v2
from ..autonomy_v2.models import AQV2Artifact, AutonomyStateV2
from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..production.controller_executor import (
    CandidateAuthoringController,
    ControllerArtifact,
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
    build_phase_tool_profile,
    execute_controller_request,
    validate_controller_execution_result,
    write_controller_contract,
)
from ..production.validation import ensure_contained_production_path
from .artifacts import (
    artifact_for_codex_image,
    load_codex_image_model,
    validate_codex_image_artifact,
)
from .assignment import (
    codex_image_source_inventory_sha256,
    validate_codex_imagegen_assignment_boundary,
)
from .models import (
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationPlan,
)

_INPUT_ROLES = [
    "codex_image_assignment",
    "codex_image_generation_plan",
    "codex_image_provider_profile",
    "codex_image_generation_budget",
    "autonomy_v2_base_state",
    "codex_image_reference",
]


@dataclass(frozen=True)
class CodexImageControllerExecution:
    """Expose one exact controller request/result plus its isolated workspace paths."""

    request: ControllerExecutionRequest
    request_artifact: CodexImageArtifact
    result: ControllerResult
    result_artifact: CodexImageArtifact
    controller_workspace_root: Path
    assignment_snapshot: Path
    allowed_output_paths: tuple[Path, ...]


def execute_codex_imagegen_controller(
    *,
    job_root: Path,
    assignment_artifact: CodexImageArtifact,
    controller: CandidateAuthoringController,
    created_at: datetime,
    timeout_seconds: int = 900,
) -> CodexImageControllerExecution:
    """Create or resume one request without mutating the paused base AQ v2 state."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    assignment, plan, budget = _validate_assignment_boundary(
        root,
        assignment_artifact,
    )
    if timeout_seconds > budget.timeout_per_assignment_seconds:
        raise ValueError("controller timeout exceeds the immutable ImageGen budget")
    execution_id = f"codex-imagegen-{assignment.assignment_id}"
    execution_root = ensure_contained_production_path(
        root,
        root
        / "production"
        / "autonomy_v2"
        / assignment.session_id
        / "codex_imagegen"
        / "controller_executions"
        / execution_id,
        must_exist=False,
    )
    profile_path = execution_root / "phase_tool_profile.json"
    assignment_binding = _controller_artifact(
        assignment_artifact,
        role="codex_image_assignment",
    )
    outputs = [
        *assignment.candidate_output_paths,
        assignment.completion_file_target,
    ]
    profile = build_phase_tool_profile(
        profile_id="codex_imagegen",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        source_artifact=assignment_binding,
        allowed_input_roles=list(_INPUT_ROLES),
        allowed_output_paths=outputs,
        created_at=created_at,
        supporting_client_enforced=False,
    )
    profile = _write_or_adopt_contract(
        root,
        profile_path,
        profile,
        PhaseToolProfile,
    )
    profile_artifact = _controller_artifact_from_path(
        root,
        profile_path,
        artifact_id=profile.contract_id,
        role="tool_profile",
    )
    immutable_inputs = _immutable_inputs(assignment)
    request = _build_request(
        assignment=assignment,
        assignment_artifact=assignment_binding,
        immutable_inputs=immutable_inputs,
        profile=profile,
        profile_artifact=profile_artifact,
        execution_id=execution_id,
        controller_kind=str(controller.controller_kind),
        timeout_seconds=timeout_seconds,
        created_at=created_at,
    )
    request_path = execution_root / "request.json"
    request = _write_or_adopt_contract(
        root,
        request_path,
        request,
        ControllerExecutionRequest,
    )
    request_artifact = artifact_for_codex_image(
        root,
        request_path,
        artifact_id=request.contract_id,
        kind="controller-request",
        media_type="application/json",
    )
    result, result_path = _execute_or_resume(
        root=root,
        request_path=request_path,
        controller=controller,
    )
    result_artifact = artifact_for_codex_image(
        root,
        result_path,
        artifact_id=result.contract_id,
        kind="controller-result",
        media_type="application/json",
    )
    workspace_root = execution_root / "controller_workspace"
    assignment_snapshot = workspace_root / "inputs" / "assignment" / Path(
        assignment_artifact.path
    ).name
    workspace_outputs = tuple(
        workspace_root
        / "outputs"
        / Path(*PurePosixPath(path).relative_to(request.output_root).parts)
        for path in request.allowed_output_paths
    )
    return CodexImageControllerExecution(
        request=request,
        request_artifact=request_artifact,
        result=result,
        result_artifact=result_artifact,
        controller_workspace_root=workspace_root,
        assignment_snapshot=assignment_snapshot,
        allowed_output_paths=workspace_outputs,
    )


def _validate_assignment_boundary(
    root: Path,
    assignment_artifact: CodexImageArtifact,
) -> tuple[
    CodexImageGenerationAssignment,
    CodexImageGenerationPlan,
    CodexImageGenerationBudget,
]:
    """Rehash the assignment and its active base authorization before controller work."""

    assignment = load_codex_image_model(
        root,
        assignment_artifact,
        CodexImageGenerationAssignment,
    )
    plan, provider, budget, _plan_item = validate_codex_imagegen_assignment_boundary(
        root,
        assignment,
    )
    base_state = load_codex_image_model(root, assignment.base_state, AutonomyStateV2)
    identity = (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
    )
    for label, model in (
        ("plan", plan),
        ("provider profile", provider),
        ("budget", budget),
        ("base state", base_state),
    ):
        if (
            model.job_id,
            model.workflow_id,
            model.dispatch_id,
            model.session_id,
        ) != identity:
            raise ValueError(f"ImageGen {label} belongs to another session")
    expected_plan_path = (
        f"production/autonomy_v2/{assignment.session_id}/codex_imagegen/plan.json"
    )
    if assignment.plan.path != expected_plan_path:
        raise ValueError("assignment generation plan is outside its canonical session path")
    if (
        plan.provider_profile != assignment.provider_profile
        or plan.budget != assignment.budget
        or provider.status != "disabled_experimental"
        or provider.activation_evidence
        or not plan.codex_imagegen_allowed
    ):
        raise PermissionError("ImageGen assignment does not preserve disabled opt-in policy")
    if (
        base_state.plan.path
        != f"production/autonomy_v2/{assignment.session_id}/plan.json"
        or not _same_exact_artifact(base_state.plan, plan.base_autonomy_plan)
        or (
            base_state.phase,
            base_state.status,
            base_state.next_action,
        )
        != ("authoring", "running", "execute_controller")
    ):
        raise PermissionError("ImageGen starts only from the paused material-authoring boundary")
    if (
        not base_state.provenance
        or base_state.provenance[-1].kind
        != "geometry_candidate_validation_receipt"
    ):
        raise PermissionError("ImageGen requires the exact geometry promotion boundary")
    validate_root_authorization_boundary_v2(
        job_root=root,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        root_authorization_artifact=_aqv2_artifact(plan.base_root_authorization),
    )
    if (
        codex_image_source_inventory_sha256(root, assignment.session_id)
        != assignment.protected_source_inventory_sha256
    ):
        raise ValueError("protected job inventory changed after ImageGen assignment")
    _validate_published_overlay_assignment(root, assignment_artifact, assignment)
    for artifact in [
        assignment_artifact,
        *assignment.provenance,
        *plan.provenance,
        *provider.provenance,
        *budget.provenance,
    ]:
        validate_codex_image_artifact(root, artifact)
    return assignment, plan, budget


def _immutable_inputs(
    assignment: CodexImageGenerationAssignment,
) -> list[ControllerArtifact]:
    """Project exact plan/profile/budget/base/reference artifacts into controller roles."""

    bindings = [
        _controller_artifact(
            assignment.plan,
            role="codex_image_generation_plan",
        ),
        _controller_artifact(
            assignment.provider_profile,
            role="codex_image_provider_profile",
        ),
        _controller_artifact(
            assignment.budget,
            role="codex_image_generation_budget",
        ),
        _controller_artifact(
            assignment.base_state,
            role="autonomy_v2_base_state",
        ),
    ]
    bindings.extend(
        _controller_artifact(item, role="codex_image_reference")
        for item in assignment.reference_images
    )
    return bindings


def _build_request(
    *,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: ControllerArtifact,
    immutable_inputs: list[ControllerArtifact],
    profile: PhaseToolProfile,
    profile_artifact: ControllerArtifact,
    execution_id: str,
    controller_kind: str,
    timeout_seconds: int,
    created_at: datetime,
) -> ControllerExecutionRequest:
    """Build the exact isolated request for one ImageGen assignment."""

    if controller_kind not in {"desktop_in_session", "fake_for_tests"}:
        raise PermissionError("Codex ImageGen accepts only desktop or explicit fake control")
    outputs = [
        *assignment.candidate_output_paths,
        assignment.completion_file_target,
    ]
    inputs = {
        "assignment": assignment_artifact.sha256,
        "immutable_inputs": [item.sha256 for item in immutable_inputs],
        "profile": profile_artifact.sha256,
        "outputs": outputs,
        "assignment_payload_sha256": assignment.assignment_payload_sha256,
    }
    return ControllerExecutionRequest(
        contract_id=f"request-{execution_id}",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "controller_kind": controller_kind}
        ),
        producer="codex_blender_modeler.codex_imagegen.controller_bridge",
        provenance=[assignment_artifact, *immutable_inputs, profile_artifact],
        created_at=created_at,
        execution_id=execution_id,
        controller_kind=controller_kind,
        assignment=assignment_artifact,
        immutable_inputs=immutable_inputs,
        tool_profile=profile_artifact,
        output_root=assignment.staging_output_directory,
        allowed_output_paths=outputs,
        timeout_seconds=timeout_seconds,
    )


def _execute_or_resume(
    *,
    root: Path,
    request_path: Path,
    controller: CandidateAuthoringController,
) -> tuple[ControllerResult, Path]:
    """Persist one waiting result or adopt one fully replay-validated final result."""

    waiting_path = request_path.parent / "result.json"
    final_path = request_path.parent / "adoption" / "result.json"
    if os.path.exists(native_io_path(final_path)):
        return (
            validate_controller_execution_result(
                job_root=root,
                request_path=request_path,
                result_path=final_path,
                controller=controller,
            ),
            final_path,
        )
    if os.path.exists(native_io_path(waiting_path)):
        waiting = ControllerResult.model_validate_json(
            Path(native_io_path(waiting_path)).read_bytes()
        )
        if waiting.status != "waiting_for_output":
            raise ValueError("non-final ImageGen controller result is not waiting")
    result = execute_controller_request(
        job_root=root,
        request_path=request_path,
        controller=controller,
    )
    destination = waiting_path if result.status == "waiting_for_output" else final_path
    if os.path.exists(native_io_path(destination)):
        stored = ControllerResult.model_validate_json(
            Path(native_io_path(destination)).read_bytes()
        )
        if stored != result:
            raise ValueError("stored ImageGen controller result differs from replay")
    else:
        _write_controller_result(root, destination, result)
    result = validate_controller_execution_result(
        job_root=root,
        request_path=request_path,
        result_path=destination,
        controller=controller,
    )
    return result, destination


def _write_or_adopt_contract(
    root: Path,
    path: Path,
    proposed: PhaseToolProfile | ControllerExecutionRequest,
    model_type: type[PhaseToolProfile] | type[ControllerExecutionRequest],
) -> PhaseToolProfile | ControllerExecutionRequest:
    """Write one controller contract once or adopt an exact timestamp-stable retry."""

    safe = ensure_contained_production_path(root, path, must_exist=False)
    if os.path.exists(native_io_path(safe)):
        existing = model_type.model_validate_json(
            Path(native_io_path(safe)).read_bytes()
        )
        if existing.model_dump(mode="json", exclude={"created_at"}) != proposed.model_dump(
            mode="json",
            exclude={"created_at"},
        ):
            raise ValueError("existing ImageGen controller contract differs")
        return existing
    os.makedirs(native_io_path(safe.parent), exist_ok=True)
    ensure_contained_production_path(root, safe.parent, must_exist=True)
    write_controller_contract(safe, proposed)
    return proposed


def _write_controller_result(
    root: Path,
    path: Path,
    result: ControllerResult,
) -> None:
    """Write the exact byte form required by full ControllerExecutor replay."""

    safe = ensure_contained_production_path(root, path, must_exist=False)
    os.makedirs(native_io_path(safe.parent), exist_ok=True)
    ensure_contained_production_path(root, safe.parent, must_exist=True)
    text = json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    encoded = text.replace("\n", os.linesep).encode("utf-8")
    with open(native_io_path(safe), "xb") as handle:
        handle.write(encoded)


def _controller_artifact(
    artifact: CodexImageArtifact,
    *,
    role: str,
) -> ControllerArtifact:
    """Project one exact Codex image artifact into the executor artifact shape."""

    return ControllerArtifact(
        artifact_id=artifact.artifact_id,
        role=role,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _controller_artifact_from_path(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    role: str,
) -> ControllerArtifact:
    """Bind one newly persisted controller contract to exact job-contained bytes."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    return ControllerArtifact(
        artifact_id=artifact_id,
        role=role,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=os.path.getsize(native_io_path(safe)),
    )


def _aqv2_artifact(artifact: CodexImageArtifact) -> AQV2Artifact:
    """Project an exact Codex artifact into the compatible AQ v2 binding shape."""

    return AQV2Artifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _same_exact_artifact(left: AQV2Artifact, right: CodexImageArtifact) -> bool:
    """Compare compatible artifact shapes without weakening path, hash, or size."""

    return (
        left.artifact_id,
        left.kind,
        left.path,
        left.sha256,
        left.byte_size,
    ) == (
        right.artifact_id,
        right.kind,
        right.path,
        right.sha256,
        right.byte_size,
    )


def _validate_published_overlay_assignment(
    root: Path,
    assignment_artifact: CodexImageArtifact,
    assignment: CodexImageGenerationAssignment,
) -> None:
    """Require the append-only overlay to be waiting on this exact assignment."""

    from ..autonomy_v2.codex_image_phase_service import get_codex_image_phase_status

    status = get_codex_image_phase_status(root, assignment.session_id)
    state = status.get("state")
    evidence = status.get("evidence")
    if not isinstance(state, dict) or not isinstance(evidence, dict):
        raise PermissionError("Codex ImageGen overlay has no published assignment state")
    if (
        state.get("status") != "waiting_for_controller"
        or state.get("next_action") != "adopt_completion"
        or evidence.get("assignment") != assignment_artifact.model_dump(mode="json")
    ):
        raise PermissionError("Codex ImageGen overlay is not waiting on this assignment")
