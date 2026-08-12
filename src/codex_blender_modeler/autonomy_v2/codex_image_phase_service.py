"""Host-side lifecycle persistence for the optional Codex ImageGen AQ v2 overlay.

This module never invokes ImageGen, creates a Codex task, or mutates base AQ state.  It
only validates exact companion evidence and appends one reconstructable overlay state.
"""

from __future__ import annotations

import os
from datetime import datetime
from math import ceil
from pathlib import Path
from typing import Literal, TypeVar, cast

from pydantic import BaseModel

from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import (
    deterministic_directory_files,
    native_io_path,
    stable_json_digest,
)
from ..codex_imagegen.artifacts import (
    load_codex_image_model,
    validate_codex_image_artifact,
    write_immutable_codex_image_model,
)
from ..codex_imagegen.assignment import (
    codex_image_source_inventory_sha256,
    validate_codex_imagegen_assignment_boundary,
)
from ..codex_imagegen.budget import apply_completion_usage, remaining_budget
from ..codex_imagegen.completion import validate_codex_imagegen_completion
from ..codex_imagegen.models import (
    CodexBuiltinImageProviderProfile,
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageEvidenceEnvelope,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationPlan,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    CodexImageGenerationTerminal,
    ImageToMaterialAdoption,
)
from ..production.controller_executor import (
    CandidateAuthoringController,
    ControllerExecutionRequest,
    ControllerResult,
    DesktopInSessionController,
    PhaseToolProfile,
    build_phase_tool_profile,
    validate_controller_execution_result,
)
from ..production.validation import ensure_contained_production_path
from .codex_image_overlay import (
    AutonomyCodexImageOverlay,
    OverlayEvent,
    codex_image_overlay_profile_status,
    initial_codex_image_overlay,
    transition_codex_image_overlay,
)
from .delivery_service import (
    artifact_for_v2,
    validate_root_authorization_boundary_v2,
    validate_v2_artifact,
)
from .models import AQV2Artifact, AutonomyStateV2
from .transitions import validate_initial_state, validate_state_transition

_OVERLAY_KIND = "autonomy-codex-image-overlay"
_CONTROLLER_INPUT_ROLES = [
    "codex_image_assignment",
    "codex_image_generation_plan",
    "codex_image_provider_profile",
    "codex_image_generation_budget",
    "autonomy_v2_base_state",
    "codex_image_reference",
]
_TERMINAL_EVENTS = {
    "local_procedural_fallback",
    "review_required",
    "user_image_required",
    "failed",
    "cancelled",
}

ModelT = TypeVar("ModelT", bound=BaseModel)
TerminalEvent = Literal[
    "local_procedural_fallback",
    "review_required",
    "user_image_required",
    "failed",
    "cancelled",
]


def initialize_codex_image_phase(
    job_root: Path,
    *,
    generation_plan: CodexImageArtifact,
    provider_profile: CodexImageArtifact,
    budget: CodexImageArtifact,
    created_at: datetime,
    allow_disabled_experimental: bool,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Create or recover sequence zero after explicit disabled-profile opt-in."""

    root = _job_root(job_root)
    plan_model = _load_model(root, generation_plan, CodexImageGenerationPlan)
    profile_model = _load_model(
        root,
        provider_profile,
        CodexBuiltinImageProviderProfile,
    )
    budget_model = _load_model(root, budget, CodexImageGenerationBudget)
    _validate_initial_bindings(
        root,
        plan_model,
        profile_model,
        provider_profile,
        budget_model,
        budget,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    session_root, states_root = _overlay_roots(root, plan_model.session_id)
    lock_root = _overlay_lock_root(root, session_root, create=True)
    with autonomy_session_lock(
        root,
        lock_root,
        owner_id="aqv2-codex-image-initialize",
    ):
        if os.path.isdir(states_root):
            chain = _state_chain(root, session_root)
            if len(chain) != 1:
                raise FileExistsError("Codex ImageGen overlay already advanced")
            state, artifact = chain[0]
            expected = initial_codex_image_overlay(
                job_id=plan_model.job_id,
                workflow_id=plan_model.workflow_id,
                dispatch_id=plan_model.dispatch_id,
                session_id=plan_model.session_id,
                generation_plan=generation_plan,
                provider_profile=provider_profile,
                budget=budget,
                created_at=state.created_at,
                codex_imagegen_allowed=True,
            )
            if state != expected:
                raise ValueError("existing Codex ImageGen overlay initialization differs")
            return state, artifact
        state = initial_codex_image_overlay(
            job_id=plan_model.job_id,
            workflow_id=plan_model.workflow_id,
            dispatch_id=plan_model.dispatch_id,
            session_id=plan_model.session_id,
            generation_plan=generation_plan,
            provider_profile=provider_profile,
            budget=budget,
            created_at=created_at,
            codex_imagegen_allowed=True,
        )
        artifact = _write_state(root, states_root, state)
        return state, artifact


def publish_codex_image_assignment(
    job_root: Path,
    session_id: str,
    *,
    assignment: CodexImageArtifact,
    created_at: datetime,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Publish one assignment transition without invoking its controller."""

    root, session_root = _locked_roots(job_root, session_id)
    with autonomy_session_lock(
        root,
        _overlay_lock_root(root, session_root),
        owner_id="aqv2-codex-image-assignment",
    ):
        state, _state_artifact = _state_chain(root, session_root)[-1]
        assignment_model = _load_model(
            root,
            assignment,
            CodexImageGenerationAssignment,
        )
        validate_codex_imagegen_assignment_boundary(root, assignment_model)
        _validate_assignment_binding(root, state, assignment_model, assignment)
        successor = transition_codex_image_overlay(
            state,
            event="assignment_published",
            evidence=[assignment],
            assignment=assignment,
            created_at=created_at,
        )
        return successor, _write_successor(root, session_root, successor)


def adopt_codex_image_completion(
    job_root: Path,
    session_id: str,
    *,
    completion: CodexImageArtifact,
    controller_request: CodexImageArtifact,
    controller_result: CodexImageArtifact,
    controller: CandidateAuthoringController | None = None,
    created_at: datetime,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Validate one exact ControllerExecutor completion and consume immutable usage."""

    root, session_root = _locked_roots(job_root, session_id)
    with autonomy_session_lock(
        root,
        _overlay_lock_root(root, session_root),
        owner_id="aqv2-codex-image-completion",
    ):
        state, _state_artifact = _state_chain(root, session_root)[-1]
        if state.assignment is None:
            raise ValueError("Codex ImageGen overlay has no current assignment")
        assignment_model = _load_model(
            root,
            state.assignment,
            CodexImageGenerationAssignment,
        )
        request_model, result_model = _validate_raw_controller_lifecycle(
            root,
            state,
            assignment_model,
            controller_request,
            controller_result,
            controller,
        )
        assignment_model, completion_model, _paths = validate_codex_imagegen_completion(
            job_root=root,
            assignment_artifact=state.assignment,
            completion_artifact=completion,
            controller_result_artifact=controller_result,
        )
        _require_identity(
            state,
            assignment_model,
            completion_model,
            request_model,
            result_model,
        )
        budget_model = _load_model(
            root,
            state.budget,
            CodexImageGenerationBudget,
        )
        usage = apply_completion_usage(
            budget_model,
            state.budget_usage,
            completion_model,
            elapsed_seconds=ceil(
                (result_model.completed_at - result_model.started_at).total_seconds()
            ),
        )
        successor = transition_codex_image_overlay(
            state,
            event="completion_adopted",
            evidence=[controller_request, completion, controller_result],
            controller_request=controller_request,
            completion=completion,
            controller_result=controller_result,
            budget_usage=usage,
            created_at=created_at,
        )
        return successor, _write_successor(root, session_root, successor)


def record_codex_image_quality(
    job_root: Path,
    session_id: str,
    *,
    candidates: list[CodexImageArtifact],
    quality_reports: list[CodexImageArtifact],
    created_at: datetime,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Append the complete candidate/report set after strict nested validation."""

    root, session_root = _locked_roots(job_root, session_id)
    with autonomy_session_lock(
        root,
        _overlay_lock_root(root, session_root),
        owner_id="aqv2-codex-image-quality",
    ):
        state, _state_artifact = _state_chain(root, session_root)[-1]
        _validate_quality_bindings(root, state, candidates, quality_reports)
        successor = transition_codex_image_overlay(
            state,
            event="quality_completed",
            evidence=[*candidates, *quality_reports],
            candidates=candidates,
            quality_reports=quality_reports,
            created_at=created_at,
        )
        return successor, _write_successor(root, session_root, successor)


def record_codex_image_selection(
    job_root: Path,
    session_id: str,
    *,
    selection: CodexImageArtifact,
    created_at: datetime,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Append one deterministic selected outcome while preserving rejected candidates."""

    root, session_root = _locked_roots(job_root, session_id)
    with autonomy_session_lock(
        root,
        _overlay_lock_root(root, session_root),
        owner_id="aqv2-codex-image-selection",
    ):
        state, _state_artifact = _state_chain(root, session_root)[-1]
        selection_model = _load_model(
            root,
            selection,
            CodexImageGenerationSelection,
        )
        _validate_selection_binding(root, state, selection_model)
        successor = transition_codex_image_overlay(
            state,
            event="candidate_selected",
            evidence=[selection],
            selection=selection,
            created_at=created_at,
        )
        return successor, _write_successor(root, session_root, successor)


def record_codex_image_material_adoption(
    job_root: Path,
    session_id: str,
    *,
    material_adoption: CodexImageArtifact,
    material_authoring_receipt: CodexImageArtifact,
    generation_terminal: CodexImageArtifact,
    created_at: datetime,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Bind staging-only material output and an adopted core generation terminal."""

    root, session_root = _locked_roots(job_root, session_id)
    with autonomy_session_lock(
        root,
        _overlay_lock_root(root, session_root),
        owner_id="aqv2-codex-image-material-adoption",
    ):
        state, _state_artifact = _state_chain(root, session_root)[-1]
        adoption_model = _load_model(
            root,
            material_adoption,
            ImageToMaterialAdoption,
        )
        terminal_model = _load_model(
            root,
            generation_terminal,
            CodexImageGenerationTerminal,
        )
        _validate_material_bindings(
            root,
            state,
            adoption_model,
            material_adoption,
            material_authoring_receipt,
            terminal_model,
        )
        successor = transition_codex_image_overlay(
            state,
            event="material_candidate_staged",
            evidence=[
                material_adoption,
                material_authoring_receipt,
                generation_terminal,
            ],
            material_adoption=material_adoption,
            material_authoring_receipt=material_authoring_receipt,
            generation_terminal=generation_terminal,
            created_at=created_at,
        )
        return successor, _write_successor(root, session_root, successor)


def resume_base_material_authoring(
    job_root: Path,
    session_id: str,
    *,
    base_state: CodexImageArtifact,
    created_at: datetime,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Close the overlay by binding, but never mutating, the paused base AQ state."""

    root, session_root = _locked_roots(job_root, session_id)
    with autonomy_session_lock(
        root,
        _overlay_lock_root(root, session_root),
        owner_id="aqv2-codex-image-base-resume",
    ):
        state, _state_artifact = _state_chain(root, session_root)[-1]
        _validate_base_resume(root, state, base_state)
        successor = transition_codex_image_overlay(
            state,
            event="base_material_authoring_resumed",
            evidence=[base_state],
            base_resume_state=base_state,
            created_at=created_at,
        )
        return successor, _write_successor(root, session_root, successor)


def terminalize_codex_image_phase(
    job_root: Path,
    session_id: str,
    *,
    event: TerminalEvent,
    generation_terminal: CodexImageArtifact,
    created_at: datetime,
    controller: CandidateAuthoringController | None = None,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Append one immutable fallback, review, failure, or cancellation terminal."""

    root, session_root = _locked_roots(job_root, session_id)
    with autonomy_session_lock(
        root,
        _overlay_lock_root(root, session_root),
        owner_id=f"aqv2-codex-image-{event}",
    ):
        state, _state_artifact = _state_chain(root, session_root)[-1]
        terminal_model = _load_model(
            root,
            generation_terminal,
            CodexImageGenerationTerminal,
        )
        _validate_terminal_binding(
            root,
            state,
            terminal_model,
            event,
            controller=controller,
        )
        controller_evidence = [
            item
            for item in (
                terminal_model.controller_request,
                terminal_model.controller_result,
            )
            if item is not None and item not in state.provenance
        ]
        successor = transition_codex_image_overlay(
            state,
            event=event,
            evidence=[*controller_evidence, generation_terminal],
            controller_request=terminal_model.controller_request,
            controller_result=terminal_model.controller_result,
            generation_terminal=generation_terminal,
            created_at=created_at,
            reason=terminal_model.reason,
        )
        return successor, _write_successor(root, session_root, successor)


def get_codex_image_phase_status(
    job_root: Path,
    session_id: str,
) -> dict[str, object]:
    """Return prompt-free, byte-free local status without activating the overlay."""

    root = _job_root(job_root)
    session_root, states_root = _overlay_roots(root, session_id)
    profile_status = codex_image_overlay_profile_status()
    if not os.path.isdir(states_root):
        return {
            "exists": False,
            "profile": profile_status,
            "session_id": session_id,
            "state": None,
            "controller_required": True,
            "waiting_for_controller": False,
            "actual_codex_imagegen_execution_verified": False,
        }
    state, state_artifact = _state_chain(root, session_root)[-1]
    budget = _load_model(root, state.budget, CodexImageGenerationBudget)
    profile = _load_model(
        root,
        state.provider_profile,
        CodexBuiltinImageProviderProfile,
    )
    completion_status: str | None = None
    generated_count = 0
    if state.completion is not None:
        completion = _load_model(
            root,
            state.completion,
            CodexImageGenerationCompletion,
        )
        completion_status = completion.status
        generated_count = len(completion.generated_files)
    selection_outcome: str | None = None
    if state.selection is not None:
        selection = _load_model(
            root,
            state.selection,
            CodexImageGenerationSelection,
        )
        selection_outcome = selection.outcome
    terminal_status: str | None = None
    if state.generation_terminal is not None:
        terminal = _load_model(
            root,
            state.generation_terminal,
            CodexImageGenerationTerminal,
        )
        terminal_status = terminal.status
    return {
        "exists": True,
        "profile": {**profile_status, "evidence_status": profile.status},
        "session_id": state.session_id,
        "overlay_id": state.overlay_id,
        "state": {
            "sequence": state.sequence,
            "phase": state.phase,
            "status": state.status,
            "next_action": state.next_action,
            "transition_event": state.transition_event,
            "artifact": _public_artifact(state_artifact),
        },
        "controller_required": True,
        "waiting_for_controller": state.status == "waiting_for_controller",
        "continuation_after_app_exit": False,
        "repository_can_spawn_codex_task": False,
        "autonomous_daemon": False,
        "budget": {
            "limits": {
                "total_generations": budget.max_total_generations,
                "candidates": budget.max_candidates,
                "edits_or_refinements": budget.max_edits_or_refinements,
                "generations_per_assignment": budget.max_generations_per_assignment,
                "elapsed_seconds": budget.max_total_elapsed_seconds,
            },
            "usage": state.budget_usage.model_dump(mode="json"),
            "remaining": remaining_budget(budget, state.budget_usage),
        },
        "evidence": {
            "assignment": _public_optional_artifact(state.assignment),
            "controller_request": _public_optional_artifact(state.controller_request),
            "completion": _public_optional_artifact(state.completion),
            "controller_result": _public_optional_artifact(state.controller_result),
            "candidate_count": len(state.candidates),
            "quality_report_count": len(state.quality_reports),
            "selection": _public_optional_artifact(state.selection),
            "material_adoption": _public_optional_artifact(state.material_adoption),
            "material_authoring_receipt": _public_optional_artifact(
                state.material_authoring_receipt
            ),
            "generation_terminal": _public_optional_artifact(
                state.generation_terminal
            ),
            "base_resume_state": _public_optional_artifact(state.base_resume_state),
        },
        "completion_status": completion_status,
        "generated_count": generated_count,
        "selection_outcome": selection_outcome,
        "terminal_status": terminal_status,
        "terminal_reason_recorded": state.terminal_reason is not None,
        "actual_codex_imagegen_execution_verified": False,
    }


def _job_root(job_root: Path) -> Path:
    """Resolve one existing job root through the production containment sentinel."""

    return ensure_contained_production_path(job_root, job_root, must_exist=True)


def _overlay_roots(job_root: Path, session_id: str) -> tuple[Path, Path]:
    """Return the existing base session and exact overlay state namespace."""

    session_root = ensure_contained_production_path(
        job_root,
        job_root / "production" / "autonomy_v2" / session_id,
        must_exist=True,
    )
    states_root = ensure_contained_production_path(
        job_root,
        session_root / "codex_imagegen" / "overlay" / "states",
        must_exist=False,
    )
    return session_root, states_root


def _locked_roots(job_root: Path, session_id: str) -> tuple[Path, Path]:
    """Resolve the job and session roots before acquiring their single-writer lock."""

    root = _job_root(job_root)
    session_root, _states_root = _overlay_roots(root, session_id)
    return root, session_root


def _overlay_lock_root(
    root: Path,
    session_root: Path,
    *,
    create: bool = False,
) -> Path:
    """Keep the companion writer lock inside its source-inventory-excluded subtree."""

    lock_root = ensure_contained_production_path(
        root,
        session_root / "codex_imagegen" / "overlay",
        must_exist=False,
    )
    if create:
        os.makedirs(lock_root, exist_ok=True)
    return ensure_contained_production_path(root, lock_root, must_exist=True)


def _load_model(
    root: Path,
    artifact: CodexImageArtifact,
    model_type: type[ModelT],
) -> ModelT:
    """Rehash and strict-parse a model plus every declared envelope provenance file."""

    model = load_codex_image_model(root, artifact, model_type)
    if isinstance(model, CodexImageEvidenceEnvelope):
        for provenance in model.provenance:
            validate_codex_image_artifact(root, provenance)
    return model


def _identity(model: object) -> tuple[object, object, object, object]:
    """Project one supported evidence model into its immutable session identity."""

    return (
        getattr(model, "job_id", None),
        getattr(model, "workflow_id", None),
        getattr(model, "dispatch_id", None),
        getattr(model, "session_id", None),
    )


def _require_identity(reference: object, *models: object) -> None:
    """Reject any evidence object whose immutable session identity was spliced."""

    expected = _identity(reference)
    if any(_identity(model) != expected for model in models):
        raise ValueError("Codex ImageGen evidence belongs to another session")


def _same_artifact(left: object, right: CodexImageArtifact) -> bool:
    """Compare an AQ or material artifact with a Codex artifact by exact binding."""

    exact_bytes = all(
        getattr(left, field, None) == getattr(right, field)
        for field in ("artifact_id", "path", "sha256", "byte_size")
    )
    declared_kind = getattr(left, "kind", None)
    return exact_bytes and (declared_kind is None or declared_kind == right.kind)


def _validate_initial_bindings(
    root: Path,
    plan: CodexImageGenerationPlan,
    profile: CodexBuiltinImageProviderProfile,
    profile_artifact: CodexImageArtifact,
    budget: CodexImageGenerationBudget,
    budget_artifact: CodexImageArtifact,
    *,
    allow_disabled_experimental: bool,
) -> None:
    """Validate opt-in, identity, exact plan/profile/budget, and base AQ evidence."""

    if allow_disabled_experimental is not True:
        raise PermissionError(
            "Codex ImageGen profile is disabled_experimental; explicit opt-in is required"
        )
    _require_identity(plan, profile, budget)
    if (
        plan.provider_profile != profile_artifact
        or plan.budget != budget_artifact
        or profile.status != "disabled_experimental"
        or profile.activation_evidence
        or profile.provenance != [plan.base_autonomy_plan]
        or budget.provenance != [profile_artifact]
        or plan.provenance
        != [
            plan.base_autonomy_plan,
            plan.base_root_authorization,
            profile_artifact,
            budget_artifact,
        ]
    ):
        raise ValueError("Codex ImageGen plan/profile/budget binding is inconsistent")
    profile_inputs = {
        "base_profile": plan.base_autonomy_plan.model_dump(mode="json"),
        "provider_id": "codex_builtin_gpt_image_v1",
        "execution_mode": "controller_mediated",
    }
    budget_inputs = {
        "provider_profile": profile_artifact.model_dump(mode="json"),
        "caps": {
            "max_total_generations": 4,
            "max_candidates": 3,
            "max_edits_or_refinements": 1,
            "max_generations_per_assignment": 3,
        },
    }
    plan_inputs = {
        "base_autonomy_plan": plan.base_autonomy_plan.model_dump(mode="json"),
        "base_root_authorization": plan.base_root_authorization.model_dump(mode="json"),
        "provider_profile": profile_artifact.model_dump(mode="json"),
        "budget": budget_artifact.model_dump(mode="json"),
        "items": [item.model_dump(mode="json") for item in plan.items],
    }
    if (
        profile.input_sha256 != stable_json_digest(profile_inputs)
        or profile.source_fingerprint
        != stable_json_digest({**profile_inputs, "status": "disabled_experimental"})
        or budget.input_sha256 != stable_json_digest(budget_inputs)
        or budget.source_fingerprint
        != stable_json_digest({**budget_inputs, "immutable": True})
        or plan.input_sha256 != stable_json_digest(plan_inputs)
        or plan.source_fingerprint
        != stable_json_digest({**plan_inputs, "profile_status": profile.status})
    ):
        raise ValueError("Codex ImageGen plan/profile/budget digest is inconsistent")
    for artifact in (
        plan.base_autonomy_plan,
        plan.base_root_authorization,
        *plan.provenance,
        *profile.provenance,
        *budget.provenance,
    ):
        validate_codex_image_artifact(root, artifact)
    _base_authorization, base_plan, _base_profile, _base_budget = (
        validate_root_authorization_boundary_v2(
            job_root=root,
            job_id=plan.job_id,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            session_id=plan.session_id,
            root_authorization_artifact=_aq_from_codex(
                plan.base_root_authorization
            ),
            now=plan.created_at,
        )
    )
    if (
        plan.base_autonomy_plan.path
        != f"production/autonomy_v2/{plan.session_id}/plan.json"
        or plan.base_autonomy_plan.artifact_id != base_plan.contract_id
        or not _same_artifact(
            base_plan.root_authorization,
            plan.base_root_authorization,
        )
    ):
        raise PermissionError("base AQ v2 plan authorization is not exact")


def _validate_assignment_binding(
    root: Path,
    state: AutonomyCodexImageOverlay,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
) -> None:
    """Require an assignment to bind the overlay and a paused base material state."""

    _require_identity(state, assignment)
    if (
        assignment.plan != state.generation_plan
        or assignment.provider_profile != state.provider_profile
        or assignment.budget != state.budget
        or assignment.sequence != state.budget_usage.assignments
    ):
        raise ValueError("assignment differs from the current overlay bindings")
    if assignment_artifact in state.provenance:
        raise ValueError("assignment was already consumed by this overlay")
    base_state = _validate_current_base_state(root, state.session_id, assignment.base_state)
    _require_identity(state, base_state)
    plan = _load_model(root, state.generation_plan, CodexImageGenerationPlan)
    if not _same_artifact(base_state.plan, plan.base_autonomy_plan):
        raise ValueError("assignment base state binds another AQ v2 plan")
    if (
        base_state.phase,
        base_state.status,
        base_state.next_action,
    ) != ("authoring", "running", "execute_controller"):
        raise PermissionError("Codex ImageGen overlay starts only at material authoring")
    if (
        not base_state.provenance
        or base_state.provenance[-1].kind
        != "geometry_candidate_validation_receipt"
    ):
        raise PermissionError("base AQ state has not completed geometry promotion")


def _validate_raw_controller_lifecycle(
    root: Path,
    state: AutonomyCodexImageOverlay,
    assignment: CodexImageGenerationAssignment,
    request_artifact: CodexImageArtifact,
    result_artifact: CodexImageArtifact,
    controller: CandidateAuthoringController | None,
) -> tuple[ControllerExecutionRequest, ControllerResult]:
    """Replay the full executor receipts and validate the dedicated ImageGen request."""

    request_path = validate_codex_image_artifact(root, request_artifact)
    result_path = validate_codex_image_artifact(root, result_artifact)
    request = ControllerExecutionRequest.model_validate_json(
        _read_bytes(request_path)
    )
    result = ControllerResult.model_validate_json(_read_bytes(result_path))
    _require_identity(state, request, result)
    expected_prefix = (
        f"production/autonomy_v2/{state.session_id}/codex_imagegen/"
        "controller_executions/"
    )
    if (
        not request_artifact.path.startswith(expected_prefix)
        or not request_artifact.path.endswith("/request.json")
        or result_artifact.path
        not in {
            request_artifact.path.removesuffix("request.json") + "result.json",
            request_artifact.path.removesuffix("request.json") + "adoption/result.json",
        }
    ):
        raise ValueError("controller request/result are outside the ImageGen execution root")
    if (
        not _same_artifact(request.assignment, cast(CodexImageArtifact, state.assignment))
        or not _same_artifact(result.request, request_artifact)
        or result.execution_id != request.execution_id
        or result.controller_kind != request.controller_kind
    ):
        raise ValueError("controller request/result do not bind the overlay assignment")
    expected_inputs = [
        state.generation_plan,
        state.provider_profile,
        state.budget,
        assignment.base_state,
        *assignment.reference_images,
    ]
    expected_roles = [
        "codex_image_generation_plan",
        "codex_image_provider_profile",
        "codex_image_generation_budget",
        "autonomy_v2_base_state",
        *(["codex_image_reference"] * len(assignment.reference_images)),
    ]
    if len(request.immutable_inputs) != len(expected_inputs) or any(
        not _same_artifact(actual, expected)
        for actual, expected in zip(request.immutable_inputs, expected_inputs, strict=True)
    ):
        raise ValueError("controller request immutable inputs differ from the overlay")
    if (
        request.assignment.role != "codex_image_assignment"
        or [item.role for item in request.immutable_inputs] != expected_roles
        or request.provenance
        != [request.assignment, *request.immutable_inputs, request.tool_profile]
    ):
        raise ValueError("controller request input roles or provenance differ")
    expected_outputs = [
        *assignment.candidate_output_paths,
        assignment.completion_file_target,
    ]
    budget = _load_model(root, state.budget, CodexImageGenerationBudget)
    if (
        request.output_root != assignment.staging_output_directory
        or request.allowed_output_paths != expected_outputs
        or request.timeout_seconds > budget.timeout_per_assignment_seconds
    ):
        raise ValueError("controller request output or timeout boundary differs")
    profile_artifact = _core_from_controller(request.tool_profile)
    profile = _load_model(root, profile_artifact, PhaseToolProfile)
    expected_profile = build_phase_tool_profile(
        profile_id="codex_imagegen",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
        source_artifact=request.assignment,
        allowed_input_roles=list(_CONTROLLER_INPUT_ROLES),
        allowed_output_paths=expected_outputs,
        created_at=profile.created_at,
        supporting_client_enforced=False,
    )
    if (
        profile != expected_profile
        or request.tool_profile != result.tool_profile
    ):
        raise PermissionError("controller request lacks the dedicated ImageGen tool profile")
    request_inputs = {
        "assignment": cast(CodexImageArtifact, state.assignment).sha256,
        "immutable_inputs": [item.sha256 for item in request.immutable_inputs],
        "profile": request.tool_profile.sha256,
        "outputs": expected_outputs,
        "assignment_payload_sha256": assignment.assignment_payload_sha256,
    }
    if (
        request.input_sha256 != stable_json_digest(request_inputs)
        or request.source_fingerprint
        != stable_json_digest(
            {**request_inputs, "controller_kind": request.controller_kind}
        )
    ):
        raise ValueError("controller request digest differs from the overlay boundary")
    selected_controller = controller
    if request.controller_kind == "desktop_in_session":
        selected_controller = selected_controller or DesktopInSessionController()
    elif request.controller_kind == "fake_for_tests":
        if selected_controller is None:
            raise PermissionError("fake controller replay requires the exact injected adapter")
    else:
        raise PermissionError("ImageGen overlay supports only desktop or explicit fake control")
    if str(selected_controller.controller_kind) != request.controller_kind:
        raise ValueError("controller replay adapter differs from the immutable request")
    validated = validate_controller_execution_result(
        job_root=root,
        request_path=request_path,
        result_path=result_path,
        controller=selected_controller,
    )
    if validated != result:
        raise ValueError("controller result differs from full executor reconstruction")
    protected = codex_image_source_inventory_sha256(root, state.session_id)
    if protected != assignment.protected_source_inventory_sha256:
        raise ValueError("protected job inventory changed after ImageGen assignment")
    return request, result


def _validate_quality_bindings(
    root: Path,
    state: AutonomyCodexImageOverlay,
    candidate_artifacts: list[CodexImageArtifact],
    report_artifacts: list[CodexImageArtifact],
) -> None:
    """Require every completion output and its exact report exactly once."""

    if any(
        item is None
        for item in (
            state.assignment,
            state.controller_request,
            state.completion,
            state.controller_result,
        )
    ):
        raise ValueError("quality evidence requires a completed controller boundary")
    if not candidate_artifacts or len(candidate_artifacts) != len(report_artifacts):
        raise ValueError("every Codex image candidate requires one quality report")
    completion = _load_model(
        root,
        state.completion,
        CodexImageGenerationCompletion,
    )
    if len(candidate_artifacts) != len(completion.generated_files):
        raise ValueError("quality candidates do not cover every completion output")
    seen_ids: set[str] = set()
    for generated_file, candidate_artifact, report_artifact in zip(
        completion.generated_files,
        candidate_artifacts,
        report_artifacts,
        strict=True,
    ):
        candidate = _load_model(
            root,
            candidate_artifact,
            CodexImageGenerationCandidate,
        )
        report = _load_model(
            root,
            report_artifact,
            CodexImageGenerationQualityReport,
        )
        evidence = _load_model(
            root,
            report.generated_image_evidence,
            CodexGeneratedImageEvidence,
        )
        _require_identity(state, candidate, report, evidence)
        if candidate.candidate_id in seen_ids:
            raise ValueError("quality candidate identity is duplicated")
        seen_ids.add(candidate.candidate_id)
        if (
            candidate.assignment != state.assignment
            or candidate.completion != state.completion
            or candidate.controller_request != state.controller_request
            or candidate.controller_result != state.controller_result
            or candidate.generated_file != generated_file
            or report.assignment != state.assignment
            or report.completion != state.completion
            or report.candidate != candidate_artifact
            or evidence.candidate != candidate_artifact
            or evidence.controller_request != state.controller_request
            or evidence.controller_result != state.controller_result
            or evidence.generated_file != generated_file
        ):
            raise ValueError("candidate quality evidence chain is inconsistent")


def _validate_selection_binding(
    root: Path,
    state: AutonomyCodexImageOverlay,
    selection: CodexImageGenerationSelection,
) -> None:
    """Require one selected outcome over the exact preserved candidate/report set."""

    _require_identity(state, selection)
    if state.assignment is None or state.completion is None:
        raise ValueError("selection requires assignment and completion evidence")
    if selection.outcome != "selected":
        raise PermissionError("non-selected outcomes must terminate without adoption")
    decisions = [(item.candidate, item.quality_report) for item in selection.decisions]
    expected = list(zip(state.candidates, state.quality_reports, strict=True))
    if (
        selection.assignment != state.assignment
        or selection.completion != state.completion
        or decisions != expected
    ):
        raise ValueError("selection does not exactly cover current candidate evidence")
    for artifact in selection.provenance:
        validate_codex_image_artifact(root, artifact)


def _validate_material_bindings(
    root: Path,
    state: AutonomyCodexImageOverlay,
    adoption: ImageToMaterialAdoption,
    adoption_artifact: CodexImageArtifact,
    receipt_artifact: CodexImageArtifact,
    terminal: CodexImageGenerationTerminal,
) -> None:
    """Validate core adoption, material staging receipt, and adopted terminal as one chain."""

    if state.selection is None or state.assignment is None or state.completion is None:
        raise ValueError("material adoption requires a selected completion")
    _require_identity(state, adoption, terminal)
    if (
        adoption.selection != state.selection
        or adoption.selected_candidate not in state.candidates
        or adoption.quality_report not in state.quality_reports
    ):
        raise ValueError("material adoption does not bind the current selection")
    for artifact in adoption.provenance:
        validate_codex_image_artifact(root, artifact)
    _validate_material_receipt(root, state, adoption, adoption_artifact, receipt_artifact)
    _validate_terminal_binding(root, state, terminal, "adopted")
    if terminal.adoption != adoption_artifact:
        raise ValueError("adopted terminal binds another material adoption")


def _validate_material_receipt(
    root: Path,
    state: AutonomyCodexImageOverlay,
    adoption: ImageToMaterialAdoption,
    adoption_artifact: CodexImageArtifact,
    receipt_artifact: CodexImageArtifact,
) -> None:
    """Rehash legacy or normalized material staging and its selected evidence."""

    from ..material_authoring.codex_image_models import (
        CodexImageAuthoredMaterialManifestV021,
        CodexImageMaterialAuthoringReceiptV021,
        CodexImageMaterialAuthoringRequestV021,
    )
    from ..material_authoring.codex_image_normalized_adapter import (
        validate_codex_image_normalized_material_candidate,
    )
    from ..material_authoring.codex_image_normalized_models import (
        CodexImageNormalizedMaterialAuthoringReceiptV010,
        CodexImageNormalizedMaterialAuthoringRequestV010,
    )

    if receipt_artifact.kind == "codex-image-normalized-material-authoring-receipt":
        normalized_receipt = _load_model(
            root,
            receipt_artifact,
            CodexImageNormalizedMaterialAuthoringReceiptV010,
        )
        manifest = validate_codex_image_normalized_material_candidate(
            root,
            normalized_receipt,
        )
        normalized_request = _load_model(
            root,
            normalized_receipt.request,
            CodexImageNormalizedMaterialAuthoringRequestV010,
        )
        base_request = _load_model(
            root,
            normalized_request.base_request_artifact,
            CodexImageMaterialAuthoringRequestV021,
        )
        validate_codex_image_artifact(
            root,
            _codex_artifact(normalized_request.effective_source.artifact),
        )
        if base_request != normalized_request.base_request:
            raise ValueError("embedded 0.2.1 request differs from its exact artifact")
        for output in normalized_receipt.outputs:
            validate_codex_image_artifact(root, _codex_artifact(output))
        if (
            normalized_receipt.job_id != state.job_id
            or normalized_receipt.workflow_id != state.workflow_id
            or normalized_request.job_id != state.job_id
            or normalized_request.workflow_id != state.workflow_id
            or normalized_request.run_id != normalized_receipt.run_id
            or manifest.run_id != normalized_receipt.run_id
            or manifest.status != "candidate_ready"
            or manifest.selected_source != base_request.source
            or manifest.effective_source != normalized_request.effective_source
            or not _same_artifact(
                base_request.core_evidence.selection,
                cast(CodexImageArtifact, state.selection),
            )
            or not _same_artifact(
                base_request.core_evidence.adoption,
                adoption_artifact,
            )
            or not _same_artifact(
                base_request.core_evidence.selected_quality_report,
                adoption.quality_report,
            )
            or adoption.selected_source_sha256
            != base_request.source.artifact.sha256
            or base_request.material_id not in adoption.target_material_ids
        ):
            raise ValueError(
                "normalized material authoring receipt differs from selected core evidence"
            )
        return

    receipt = _load_model(
        root,
        receipt_artifact,
        CodexImageMaterialAuthoringReceiptV021,
    )
    if receipt.job_id != state.job_id or receipt.workflow_id != state.workflow_id:
        raise ValueError("material authoring receipt belongs to another workflow")
    request_artifact = _codex_artifact(receipt.request)
    manifest_artifact = _codex_artifact(receipt.manifest)
    request = _load_model(
        root,
        request_artifact,
        CodexImageMaterialAuthoringRequestV021,
    )
    manifest = _load_model(
        root,
        manifest_artifact,
        CodexImageAuthoredMaterialManifestV021,
    )
    for output in receipt.outputs:
        validate_codex_image_artifact(root, _codex_artifact(output))
    if (
        request.job_id != state.job_id
        or request.workflow_id != state.workflow_id
        or request.run_id != receipt.run_id
        or manifest.run_id != receipt.run_id
        or manifest.status != "candidate_ready"
        or not _same_artifact(
            request.core_evidence.selection,
            cast(CodexImageArtifact, state.selection),
        )
        or not _same_artifact(request.core_evidence.adoption, adoption_artifact)
        or not _same_artifact(
            request.core_evidence.selected_quality_report,
            adoption.quality_report,
        )
        or adoption.selected_source_sha256 != request.source.artifact.sha256
        or request.material_id not in adoption.target_material_ids
    ):
        raise ValueError("material authoring receipt differs from selected core evidence")


def _validate_base_resume(
    root: Path,
    state: AutonomyCodexImageOverlay,
    base_state_artifact: CodexImageArtifact,
) -> None:
    """Require resume to reference the unchanged base state frozen by the assignment."""

    if state.assignment is None:
        raise ValueError("base resume requires one overlay assignment")
    assignment = _load_model(
        root,
        state.assignment,
        CodexImageGenerationAssignment,
    )
    if assignment.base_state != base_state_artifact:
        raise ValueError("base resume state differs from the assignment boundary")
    base_state = _validate_current_base_state(root, state.session_id, base_state_artifact)
    _require_identity(state, base_state)
    if (
        base_state.phase,
        base_state.status,
        base_state.next_action,
    ) != ("authoring", "running", "execute_controller"):
        raise ValueError("base material authoring boundary is no longer resumable")


def _validate_terminal_binding(
    root: Path,
    state: AutonomyCodexImageOverlay,
    terminal: CodexImageGenerationTerminal,
    expected_status: str,
    *,
    controller: CandidateAuthoringController | None = None,
) -> None:
    """Require a terminal to preserve the current exact evidence and budget usage."""

    _require_identity(state, terminal)
    if expected_status not in {*_TERMINAL_EVENTS, "adopted"}:
        raise ValueError("unsupported Codex ImageGen terminal status")
    if (
        terminal.status != expected_status
        or terminal.plan != state.generation_plan
        or terminal.budget != state.budget
        or terminal.budget_usage != state.budget_usage
        or terminal.assignment != state.assignment
        or terminal.completion != state.completion
        or terminal.selection != state.selection
        or terminal.candidates != state.candidates
        or terminal.quality_reports != state.quality_reports
    ):
        raise ValueError("generation terminal differs from current overlay evidence")
    if terminal.runtime_trigger is not None:
        plan = _load_model(root, state.generation_plan, CodexImageGenerationPlan)
        matching_items = [
            item for item in plan.items if item.plan_item_id == terminal.plan_item_id
        ]
        if len(matching_items) != 1:
            raise ValueError("generation terminal plan item is not exact")
        plan_item = matching_items[0]
        if terminal.runtime_trigger == "assignment_capacity_rejected":
            if (
                state.status != "planned"
                or terminal.status != plan_item.fallback
                or terminal.assignment is not None
                or terminal.controller_request is not None
                or terminal.controller_result is not None
            ):
                raise ValueError("capacity terminal differs from the selected plan fallback")
        else:
            _validate_controller_terminal_binding(
                root,
                state,
                terminal,
                plan_item_fallback=plan_item.fallback,
                controller=controller,
            )
    for artifact in terminal.provenance:
        validate_codex_image_artifact(root, artifact)


def _validate_controller_terminal_binding(
    root: Path,
    state: AutonomyCodexImageOverlay,
    terminal: CodexImageGenerationTerminal,
    *,
    plan_item_fallback: str,
    controller: CandidateAuthoringController | None,
) -> None:
    """Replay one final non-completing controller result and verify its exact fallback."""

    if (
        state.status != "waiting_for_controller"
        or state.assignment is None
        or terminal.assignment != state.assignment
        or terminal.controller_request is None
        or terminal.controller_result is None
    ):
        raise ValueError("controller terminal differs from the waiting assignment")
    assignment = _load_model(
        root,
        state.assignment,
        CodexImageGenerationAssignment,
    )
    _request, result = _validate_raw_controller_lifecycle(
        root,
        state,
        assignment,
        terminal.controller_request,
        terminal.controller_result,
        controller,
    )
    trigger_by_status = {
        "timeout": "controller_timeout",
        "failed": "controller_failed",
        "rejected": "controller_rejected",
        "cancelled": "controller_cancelled",
    }
    expected_trigger = trigger_by_status.get(result.status)
    expected_terminal_status = (
        "cancelled" if result.status == "cancelled" else plan_item_fallback
    )
    if (
        expected_trigger is None
        or terminal.runtime_trigger != expected_trigger
        or terminal.status != expected_terminal_status
    ):
        raise ValueError("controller terminal status differs from its exact result")


def _validate_current_base_state(
    root: Path,
    session_id: str,
    expected_artifact: CodexImageArtifact,
) -> AutonomyStateV2:
    """Reconstruct the base AQ chain and require its unchanged current head."""

    states_root = ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / session_id / "states",
        must_exist=True,
    )
    paths = sorted(states_root.glob("*.json"))
    if not paths:
        raise FileNotFoundError("base AQ v2 session has no immutable state")
    previous: AutonomyStateV2 | None = None
    head: AutonomyStateV2 | None = None
    head_artifact: object | None = None
    for expected_sequence, path in enumerate(paths):
        safe = ensure_contained_production_path(root, path, must_exist=True)
        current = AutonomyStateV2.model_validate_json(_read_bytes(safe))
        if current.sequence != expected_sequence or path.stem != f"{expected_sequence:04d}":
            raise ValueError("base AQ v2 state sequence is incomplete")
        for provenance in current.provenance:
            validate_v2_artifact(root, provenance)
        if previous is None:
            validate_initial_state(current)
        else:
            validate_state_transition(previous, current)
        head = current
        head_artifact = artifact_for_v2(
            root,
            safe,
            artifact_id=current.state_id,
            kind="autonomy_v2_state",
        )
        previous = current
    if head is None or head_artifact is None:
        raise FileNotFoundError("base AQ v2 session has no current state")
    if not _same_artifact(head_artifact, expected_artifact):
        raise ValueError("assignment base state is not the current AQ v2 chain head")
    return head


def _state_chain(
    root: Path,
    session_root: Path,
) -> list[tuple[AutonomyCodexImageOverlay, CodexImageArtifact]]:
    """Reconstruct every overlay state and reject gaps, edits, or provenance splices."""

    states_root = ensure_contained_production_path(
        root,
        session_root / "codex_imagegen" / "overlay" / "states",
        must_exist=True,
    )
    paths = _strict_overlay_state_paths(states_root)
    if not paths:
        raise FileNotFoundError("Codex ImageGen overlay has no immutable state")
    chain: list[tuple[AutonomyCodexImageOverlay, CodexImageArtifact]] = []
    previous: AutonomyCodexImageOverlay | None = None
    for expected_sequence, path in enumerate(paths):
        safe = ensure_contained_production_path(root, path, must_exist=True)
        state = AutonomyCodexImageOverlay.model_validate_json(_read_bytes(safe))
        if state.sequence != expected_sequence or path.stem != f"{expected_sequence:04d}":
            raise ValueError("Codex ImageGen overlay state sequence is incomplete")
        for provenance in state.provenance:
            validate_codex_image_artifact(root, provenance)
        if previous is None:
            expected = initial_codex_image_overlay(
                job_id=state.job_id,
                workflow_id=state.workflow_id,
                dispatch_id=state.dispatch_id,
                session_id=state.session_id,
                generation_plan=state.generation_plan,
                provider_profile=state.provider_profile,
                budget=state.budget,
                created_at=state.created_at,
                codex_imagegen_allowed=True,
            )
        else:
            expected = _reconstruct_successor(previous, state)
        if state != expected:
            raise ValueError("Codex ImageGen overlay state is not reconstructable")
        artifact = _artifact_for_state(root, safe, state)
        chain.append((state, artifact))
        previous = state
    return chain


def _strict_overlay_state_paths(states_root: Path) -> list[Path]:
    """Reject undeclared files or nested members in the protected overlay state root."""

    paths = deterministic_directory_files(states_root)
    for path in paths:
        relative = path.relative_to(states_root).as_posix()
        if "/" in relative or not path.name.endswith(".json"):
            raise ValueError("Codex ImageGen overlay state root contains an extra member")
    return paths


def _reconstruct_successor(
    previous: AutonomyCodexImageOverlay,
    current: AutonomyCodexImageOverlay,
) -> AutonomyCodexImageOverlay:
    """Rebuild one adjacent state from its append-only evidence suffix."""

    if current.created_at < previous.created_at:
        raise ValueError("Codex ImageGen overlay timestamp moved backwards")
    if (
        len(current.provenance) <= len(previous.provenance)
        or current.provenance[: len(previous.provenance)] != previous.provenance
    ):
        raise ValueError("Codex ImageGen overlay provenance is not append-only")
    evidence = current.provenance[len(previous.provenance) :]
    event = current.transition_event
    kwargs: dict[str, object] = {}
    if event == "assignment_published":
        kwargs["assignment"] = current.assignment
    elif event == "completion_adopted":
        kwargs["controller_request"] = current.controller_request
        kwargs["completion"] = current.completion
        kwargs["controller_result"] = current.controller_result
    elif event == "quality_completed":
        kwargs["candidates"] = current.candidates
        kwargs["quality_reports"] = current.quality_reports
    elif event == "candidate_selected":
        kwargs["selection"] = current.selection
    elif event in {"material_adopted", "material_candidate_staged"}:
        kwargs["material_adoption"] = current.material_adoption
        kwargs["material_authoring_receipt"] = current.material_authoring_receipt
        kwargs["generation_terminal"] = current.generation_terminal
    elif event == "base_material_authoring_resumed":
        kwargs["base_resume_state"] = current.base_resume_state
    elif event in _TERMINAL_EVENTS:
        kwargs["generation_terminal"] = current.generation_terminal
        if current.controller_request != previous.controller_request:
            kwargs["controller_request"] = current.controller_request
        if current.controller_result != previous.controller_result:
            kwargs["controller_result"] = current.controller_result
    else:
        raise ValueError("Codex ImageGen overlay contains an unknown transition event")
    return transition_codex_image_overlay(
        previous,
        event=cast(OverlayEvent, event),
        evidence=evidence,
        created_at=current.created_at,
        budget_usage=current.budget_usage,
        reason=current.terminal_reason,
        **kwargs,
    )


def _write_state(
    root: Path,
    states_root: Path,
    state: AutonomyCodexImageOverlay,
) -> CodexImageArtifact:
    """Write one exact sequence path and return its immutable binding."""

    return write_immutable_codex_image_model(
        root,
        states_root / f"{state.sequence:04d}.json",
        state,
        kind=_OVERLAY_KIND,
    )


def _write_successor(
    root: Path,
    session_root: Path,
    state: AutonomyCodexImageOverlay,
) -> CodexImageArtifact:
    """Publish one successor into the already-created exact overlay namespace."""

    states_root = ensure_contained_production_path(
        root,
        session_root / "codex_imagegen" / "overlay" / "states",
        must_exist=True,
    )
    return _write_state(root, states_root, state)


def _artifact_for_state(
    root: Path,
    path: Path,
    state: AutonomyCodexImageOverlay,
) -> CodexImageArtifact:
    """Bind an existing state file without writing or altering its immutable bytes."""

    from ..codex_imagegen.artifacts import artifact_for_codex_image

    return artifact_for_codex_image(
        root,
        path,
        artifact_id=state.contract_id,
        kind=_OVERLAY_KIND,
        media_type="application/json",
    )


def _read_bytes(path: Path) -> bytes:
    """Read one contained file through the platform-native long-path spelling."""

    return Path(native_io_path(path)).read_bytes()


def _codex_artifact(artifact: object) -> CodexImageArtifact:
    """Strictly project a compatible exact material artifact into core shape."""

    if not isinstance(artifact, BaseModel):
        raise TypeError("exact material artifact must be a strict model")
    return CodexImageArtifact.model_validate(artifact.model_dump(mode="json"))


def _core_from_controller(artifact: object) -> CodexImageArtifact:
    """Add JSON media semantics to one strict ControllerExecutor artifact."""

    if not isinstance(artifact, BaseModel):
        raise TypeError("controller artifact must be a strict model")
    payload = artifact.model_dump(mode="json")
    payload["kind"] = payload.pop("role")
    return CodexImageArtifact.model_validate(
        {**payload, "media_type": "application/json"}
    )


def _aq_from_codex(artifact: CodexImageArtifact) -> AQV2Artifact:
    """Project a JSON Codex binding into the exact base AQ artifact shape."""

    payload = artifact.model_dump(mode="json")
    payload.pop("media_type")
    return AQV2Artifact.model_validate(payload)


def _public_artifact(artifact: CodexImageArtifact) -> dict[str, object]:
    """Expose only identity, path, and digest metadata, never file bytes."""

    return artifact.model_dump(mode="json")


def _public_optional_artifact(
    artifact: CodexImageArtifact | None,
) -> dict[str, object] | None:
    """Project one optional evidence binding into the byte-free status shape."""

    return None if artifact is None else _public_artifact(artifact)
