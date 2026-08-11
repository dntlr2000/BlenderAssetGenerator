"""Prompt-safe host orchestration used by Codex ImageGen CLI and MCP surfaces."""

from __future__ import annotations

import json
import mimetypes
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..autonomy_v2.codex_image_overlay import AutonomyCodexImageOverlay
from ..autonomy_v2.codex_image_phase_service import (
    adopt_codex_image_completion as record_completion_transition,
)
from ..autonomy_v2.codex_image_phase_service import (
    get_codex_image_phase_status,
    publish_codex_image_assignment,
    record_codex_image_material_adoption,
    record_codex_image_quality,
    record_codex_image_selection,
    terminalize_codex_image_phase,
)
from ..autonomy_v2.controller_bridge import get_autonomy_v2_status
from ..autonomy_v2.models import RootAuthorizationV2
from ..blender_artifacts import native_io_path
from ..material_authoring.codex_image_adapter import (
    author_codex_image_material_candidate,
    validate_codex_image_material_candidate,
)
from ..material_authoring.codex_image_models import (
    CodexImageMaterialAuthoringReceiptV021,
    CodexImageMaterialAuthoringRequestV021,
    ExactSignageTextEvidenceV021,
)
from ..production.controller_executor import DesktopInSessionController
from ..production.validation import ensure_contained_production_path
from ..workspace import job_dir
from .artifacts import (
    artifact_for_codex_image,
    load_codex_image_model,
    write_immutable_codex_image_model,
)
from .assignment import build_codex_imagegen_assignment
from .budget import CodexImageGenerationCapacityError
from .controller_bridge import execute_codex_imagegen_controller
from .models import (
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationPlan,
    CodexImageGenerationPlanItem,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    CodexImageGenerationTerminal,
    ImageToMaterialAdoption,
)
from .public_service import (
    adopt_codex_imagegen_completion,
    adopt_codex_imagegen_material,
    codex_imagegen_status,
    run_codex_imagegen,
    select_codex_imagegen_candidate,
    validate_codex_imagegen_exact_text_binding,
)
from .quality import evaluate_candidate_quality
from .reporting import build_codex_imagegen_terminal

ModelT = TypeVar("ModelT", bound=BaseModel)


def get_codex_imagegen_public_status(
    *,
    job_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    """Return static capability or one prompt-free persisted overlay status."""

    if (job_id is None) != (session_id is None):
        raise ValueError("job_id and session_id must be supplied together")
    if job_id is None or session_id is None:
        return {
            **codex_imagegen_status(),
            "current_controller_mode": "desktop_in_session",
            "codex_controller_required": True,
            "waiting_assignment_count": 0,
            "latest_completion": None,
            "latest_terminal": None,
        }
    phase = get_codex_image_phase_status(job_dir(job_id), session_id)
    evidence = phase.get("evidence") if isinstance(phase, dict) else None
    if not isinstance(evidence, dict):
        evidence = {}
    return {
        **phase,
        "current_controller_mode": "desktop_in_session",
        "codex_controller_required": True,
        "waiting_assignment_count": 1 if phase.get("waiting_for_controller") else 0,
        "latest_completion": evidence.get("completion"),
        "latest_terminal": evidence.get("generation_terminal"),
    }


def run_codex_imagegen_controller_phase(
    *,
    job_id: str,
    session_id: str,
    rendered_prompt_text: str | None = None,
    plan_item_id: str | None = None,
    exact_text_value: str | None = None,
    timeout_seconds: int = 900,
) -> dict[str, object]:
    """Publish or resume one desktop assignment without invoking ImageGen in host code."""

    root = job_dir(job_id)
    state, _state_artifact = _overlay_state(root, session_id)
    if state.status == "planned":
        recovered = _recover_pending_capacity_terminal(
            root=root,
            state=state,
            requested_plan_item_id=plan_item_id,
        )
        if recovered is not None:
            terminal, terminal_artifact = recovered
            state, _state_artifact = terminalize_codex_image_phase(
                root,
                session_id,
                event=terminal.status,
                generation_terminal=terminal_artifact,
                created_at=_monotonic_now(state, terminal.created_at),
            )
            return _runtime_terminal_response(
                state=state,
                terminal_artifact=terminal_artifact,
            )
        prompt = (rendered_prompt_text or "").strip()
        if not prompt:
            raise ValueError("a new ImageGen assignment requires rendered_prompt_text")
        plan, plan_item = _selected_plan_item(root, state, plan_item_id)
        budget = load_codex_image_model(
            root,
            state.budget,
            CodexImageGenerationBudget,
        )
        try:
            if timeout_seconds > budget.timeout_per_assignment_seconds:
                raise CodexImageGenerationCapacityError(
                    "controller timeout exceeds the immutable ImageGen budget"
                )
            assignment, assignment_artifact = _create_assignment(
                root=root,
                job_id=job_id,
                session_id=session_id,
                state=state,
                rendered_prompt_text=prompt,
                plan_item_id=plan_item.plan_item_id,
                exact_text_value=exact_text_value,
            )
        except CodexImageGenerationCapacityError:
            terminal, terminal_artifact = _publish_or_recover_runtime_terminal(
                root=root,
                state=state,
                plan=plan,
                plan_item=plan_item,
                runtime_trigger="assignment_capacity_rejected",
            )
            state, _state_artifact = terminalize_codex_image_phase(
                root,
                session_id,
                event=terminal.status,
                generation_terminal=terminal_artifact,
                created_at=_monotonic_now(state, terminal.created_at),
            )
            return _runtime_terminal_response(
                state=state,
                terminal_artifact=terminal_artifact,
            )
        state, _state_artifact = publish_codex_image_assignment(
            root,
            session_id,
            assignment=assignment_artifact,
            created_at=_monotonic_now(state),
        )
    elif state.status == "waiting_for_controller" and state.assignment is not None:
        assignment_artifact = state.assignment
        assignment = load_codex_image_model(
            root,
            assignment_artifact,
            CodexImageGenerationAssignment,
        )
        if rendered_prompt_text is not None and (
            rendered_prompt_text != assignment.rendered_prompt_text
        ):
            raise ValueError("resume prompt differs from the immutable assignment")
    else:
        return get_codex_imagegen_public_status(job_id=job_id, session_id=session_id)
    controller = DesktopInSessionController()
    execution = execute_codex_imagegen_controller(
        job_root=root,
        assignment_artifact=assignment_artifact,
        controller=controller,
        created_at=_monotonic_now(state),
        timeout_seconds=timeout_seconds,
    )
    if execution.result.status == "completed":
        completion_artifact = artifact_for_codex_image(
            root,
            root / assignment.completion_file_target,
            artifact_id=f"completion-{assignment.assignment_id}",
            kind="codex-image-generation-completion",
            media_type="application/json",
        )
        state, _state_artifact = record_completion_transition(
            root,
            session_id,
            completion=completion_artifact,
            controller_request=execution.request_artifact,
            controller_result=execution.result_artifact,
            controller=controller,
            created_at=_monotonic_now(
                state,
                execution.result.completed_at,
            ),
        )
    terminal_artifact: CodexImageArtifact | None = None
    public_status = execution.result.status
    if execution.result.status in {"timeout", "failed", "rejected", "cancelled"}:
        plan = load_codex_image_model(
            root,
            state.generation_plan,
            CodexImageGenerationPlan,
        )
        plan_item = _plan_item_by_id(plan, assignment.plan_item_id)
        terminal, terminal_artifact = _publish_or_recover_runtime_terminal(
            root=root,
            state=state,
            plan=plan,
            plan_item=plan_item,
            runtime_trigger=_controller_runtime_trigger(execution.result.status),
            assignment_artifact=assignment_artifact,
            controller_request_artifact=execution.request_artifact,
            controller_result_artifact=execution.result_artifact,
        )
        state, _state_artifact = terminalize_codex_image_phase(
            root,
            session_id,
            event=terminal.status,
            generation_terminal=terminal_artifact,
            created_at=_monotonic_now(state, terminal.created_at),
            controller=controller,
        )
        public_status = state.status
    return {
        "status": public_status,
        "controller_status": execution.result.status,
        "job_id": job_id,
        "session_id": session_id,
        "assignment": assignment_artifact.model_dump(mode="json"),
        "controller_request": execution.request_artifact.model_dump(mode="json"),
        "controller_result": execution.result_artifact.model_dump(mode="json"),
        "controller_workspace_root": str(execution.controller_workspace_root),
        "assignment_snapshot": str(execution.assignment_snapshot),
        "allowed_output_paths": [str(path) for path in execution.allowed_output_paths],
        "generation_terminal": (
            terminal_artifact.model_dump(mode="json")
            if terminal_artifact is not None
            else None
        ),
        "next_action": state.next_action,
        "repository_invoked_imagegen": False,
        "codex_controller_required": True,
    }


def select_codex_imagegen_phase(
    *,
    job_id: str,
    session_id: str,
) -> dict[str, object]:
    """Build local reports, preserve every candidate, and select at most one."""

    root = job_dir(job_id)
    state, _state_artifact = _overlay_state(root, session_id)
    if state.status not in {"completion_adopted", "quality_ready", "selected"}:
        return get_codex_imagegen_public_status(job_id=job_id, session_id=session_id)
    if state.assignment is None or state.completion is None:
        raise ValueError("candidate selection requires assignment and completion evidence")
    assignment = load_codex_image_model(
        root,
        state.assignment,
        CodexImageGenerationAssignment,
    )
    completion = load_codex_image_model(
        root,
        state.completion,
        CodexImageGenerationCompletion,
    )
    candidates, evidence = _load_or_build_candidate_evidence(
        root=root,
        state=state,
        assignment=assignment,
        completion=completion,
    )
    reports = _load_or_build_quality_reports(
        root=root,
        assignment=assignment,
        assignment_artifact=state.assignment,
        completion_artifact=state.completion,
        candidates=candidates,
        evidence=evidence,
        created_at=completion.controller_executed_at + timedelta(seconds=2),
    )
    if state.status == "completion_adopted":
        state, _state_artifact = record_codex_image_quality(
            root,
            session_id,
            candidates=[artifact for _model, artifact in candidates],
            quality_reports=[artifact for _model, artifact in reports],
            created_at=_monotonic_now(state),
        )
    selection, selection_artifact = _load_or_build_selection(
        root=root,
        assignment=assignment,
        assignment_artifact=state.assignment,
        completion_artifact=state.completion,
        candidates=candidates,
        reports=reports,
        created_at=completion.controller_executed_at + timedelta(seconds=3),
    )
    if state.status == "quality_ready" and selection.outcome == "selected":
        state, _state_artifact = record_codex_image_selection(
            root,
            session_id,
            selection=selection_artifact,
            created_at=_monotonic_now(state),
        )
    elif state.status == "quality_ready":
        terminal_artifact = _selection_terminal(
            root=root,
            state=state,
            assignment=assignment,
            selection=selection,
            selection_artifact=selection_artifact,
        )
        state, _state_artifact = terminalize_codex_image_phase(
            root,
            session_id,
            event="review_required",
            generation_terminal=terminal_artifact,
            created_at=_monotonic_now(state),
        )
    return {
        "job_id": job_id,
        "session_id": session_id,
        "selection": selection.model_dump(mode="json"),
        "selection_artifact": selection_artifact.model_dump(mode="json"),
        "next_action": state.next_action,
        "human_reviewed": selection.human_reviewed,
        "semantic_checks_authoritative": False,
    }


def prepare_codex_imagegen_material_adoption(
    *,
    job_id: str,
    session_id: str,
    material_strategy: str | None = None,
    direct_channels: list[str] | None = None,
    exact_text_evidence_path: Path | None = None,
) -> dict[str, object]:
    """Publish the selected raster's staging-only local-authoring adoption contract."""

    root = job_dir(job_id)
    state, _state_artifact = _overlay_state(root, session_id)
    selection, selection_artifact, candidate, candidate_artifact, evidence, evidence_artifact, report, report_artifact = (  # noqa: E501
        _selected_evidence_chain(root, state)
    )
    strategy = material_strategy or _default_material_strategy(candidate)
    channels = direct_channels or [candidate.generated_file.output_role]
    assignment = load_codex_image_model(
        root,
        state.assignment,
        CodexImageGenerationAssignment,
    )
    adoption_path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "codex_imagegen"
        / "assignments"
        / assignment.assignment_id
        / "adoption.json"
    )
    if os.path.isfile(native_io_path(adoption_path)):
        adoption, adoption_artifact = _load_bound_model(
            root,
            adoption_path,
            ImageToMaterialAdoption,
            artifact_id=f"adoption-{assignment.assignment_id}",
            kind="codex-image-material-adoption",
        )
        exact_text_artifact = _resolve_exact_text_evidence_artifact(
            root=root,
            assignment=assignment,
            supplied_path=exact_text_evidence_path,
            existing=adoption.exact_text_composition,
        )
        if (
            adoption.selection != selection_artifact
            or adoption.selected_candidate != candidate_artifact
            or adoption.generated_image_evidence != evidence_artifact
            or adoption.quality_report != report_artifact
            or adoption.material_strategy != strategy
            or adoption.direct_channels != channels
            or adoption.exact_text_composition != exact_text_artifact
        ):
            raise ValueError("existing ImageGen material adoption differs")
    else:
        exact_text_artifact = _resolve_exact_text_evidence_artifact(
            root=root,
            assignment=assignment,
            supplied_path=exact_text_evidence_path,
            existing=None,
        )
        adoption, adoption_artifact = adopt_codex_imagegen_material(
            job_root=root,
            contract_id=f"adoption-{assignment.assignment_id}",
            adoption_id=f"adoption-{assignment.assignment_id}",
            selection=selection,
            selection_artifact=selection_artifact,
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            generated_image_evidence=evidence,
            generated_image_evidence_artifact=evidence_artifact,
            quality_report=report,
            quality_report_artifact=report_artifact,
            material_strategy=strategy,
            direct_channels=channels,
            derived_channels=[],
            created_at=_monotonic_now(state),
            exact_text_composition=exact_text_artifact,
        )
    return {
        "status": "material_request_required",
        "job_id": job_id,
        "session_id": session_id,
        "adoption": adoption.model_dump(mode="json"),
        "adoption_artifact": adoption_artifact.model_dump(mode="json"),
        "next_action": "supply_material_authoring_v021_request",
        "canonical_material_unchanged": True,
    }


def adopt_codex_imagegen_material_phase(
    *,
    job_id: str,
    session_id: str,
    material_request_path: Path,
) -> dict[str, object]:
    """Run local MaterialAuthoring 0.2.1 and bind its staging receipt before resume."""

    root = job_dir(job_id)
    state, _state_artifact = _overlay_state(root, session_id)
    request_path = material_request_path
    if not request_path.is_absolute():
        request_path = root / request_path
    safe_request = ensure_contained_production_path(root, request_path, must_exist=True)
    with open(native_io_path(safe_request), "rb") as handle:
        request = CodexImageMaterialAuthoringRequestV021.model_validate_json(handle.read())
    if state.status in {"adopted", "completed"}:
        return _resume_or_report_material_adoption(
            root=root,
            state=state,
            request=request,
        )
    _selection, selection_artifact, _candidate, _candidate_artifact, _evidence, _evidence_artifact, _report, _report_artifact = (  # noqa: E501
        _selected_evidence_chain(root, state)
    )
    adoption_artifact = CodexImageArtifact.model_validate(
        request.core_evidence.adoption.model_dump(mode="json")
    )
    adoption = load_codex_image_model(root, adoption_artifact, ImageToMaterialAdoption)
    if adoption.selection != selection_artifact:
        raise ValueError("material request adoption differs from current selection")
    receipt_path = root / request.output_root / "receipt.json"
    if os.path.isfile(native_io_path(receipt_path)):
        receipt = CodexImageMaterialAuthoringReceiptV021.model_validate_json(
            Path(native_io_path(receipt_path)).read_bytes()
        )
    else:
        receipt = author_codex_image_material_candidate(root, request)
    manifest = validate_codex_image_material_candidate(root, receipt)
    receipt_artifact = artifact_for_codex_image(
        root,
        receipt_path,
        artifact_id=receipt.receipt_id,
        kind="codex-image-material-authoring-receipt",
        media_type="application/json",
    )
    terminal_artifact = _adopted_terminal(
        root=root,
        state=state,
        adoption_artifact=adoption_artifact,
    )
    state, _state_artifact = record_codex_image_material_adoption(
        root,
        session_id,
        material_adoption=adoption_artifact,
        material_authoring_receipt=receipt_artifact,
        generation_terminal=terminal_artifact,
        created_at=_monotonic_now(state, receipt.created_at),
    )
    return {
        "status": state.status,
        "job_id": job_id,
        "session_id": session_id,
        "material_manifest": manifest.model_dump(mode="json"),
        "material_receipt": receipt_artifact.model_dump(mode="json"),
        "generation_terminal": terminal_artifact.model_dump(mode="json"),
        "next_action": state.next_action,
        "canonical_material_unchanged": True,
        "actual_codex_imagegen_execution_verified": False,
    }


def _resume_or_report_material_adoption(
    *,
    root: Path,
    state: AutonomyCodexImageOverlay,
    request: CodexImageMaterialAuthoringRequestV021,
) -> dict[str, object]:
    """Recover staging evidence without claiming controller promotion or base resume."""

    if (
        state.material_adoption is None
        or state.material_authoring_receipt is None
        or state.generation_terminal is None
        or state.assignment is None
    ):
        raise ValueError("adopted overlay is missing required material evidence")
    if CodexImageArtifact.model_validate(
        request.core_evidence.adoption.model_dump(mode="json")
    ) != state.material_adoption:
        raise ValueError("recovery material request binds another adoption")
    receipt_path = root / request.output_root / "receipt.json"
    receipt = CodexImageMaterialAuthoringReceiptV021.model_validate_json(
        Path(native_io_path(receipt_path)).read_bytes()
    )
    manifest = validate_codex_image_material_candidate(root, receipt)
    receipt_artifact = artifact_for_codex_image(
        root,
        receipt_path,
        artifact_id=receipt.receipt_id,
        kind="codex-image-material-authoring-receipt",
        media_type="application/json",
    )
    if receipt_artifact != state.material_authoring_receipt:
        raise ValueError("recovery material receipt differs from overlay evidence")
    return {
        "status": state.status,
        "job_id": state.job_id,
        "session_id": state.session_id,
        "material_manifest": manifest.model_dump(mode="json"),
        "material_receipt": receipt_artifact.model_dump(mode="json"),
        "generation_terminal": state.generation_terminal.model_dump(mode="json"),
        "next_action": state.next_action,
        "canonical_material_unchanged": True,
        "actual_codex_imagegen_execution_verified": False,
    }


def _selected_plan_item(
    root: Path,
    state: AutonomyCodexImageOverlay,
    requested_plan_item_id: str | None,
) -> tuple[CodexImageGenerationPlan, CodexImageGenerationPlanItem]:
    """Load the immutable generation plan and resolve exactly one requested item."""

    plan = load_codex_image_model(
        root,
        state.generation_plan,
        CodexImageGenerationPlan,
    )
    matches = [
        item
        for item in plan.items
        if requested_plan_item_id is None
        or item.plan_item_id == requested_plan_item_id
    ]
    if len(matches) != 1:
        raise ValueError("plan_item_id must identify exactly one ImageGen plan item")
    return plan, matches[0]


def _plan_item_by_id(
    plan: CodexImageGenerationPlan,
    plan_item_id: str,
) -> CodexImageGenerationPlanItem:
    """Require one exact plan item identifier within an already validated plan."""

    matches = [item for item in plan.items if item.plan_item_id == plan_item_id]
    if len(matches) != 1:
        raise ValueError("ImageGen assignment refers to a missing plan item")
    return matches[0]


def _runtime_terminal_path(root: Path, session_id: str) -> Path:
    """Return the single host-owned terminal path for one ImageGen overlay."""

    return (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "codex_imagegen"
        / "terminal.json"
    )


def _recover_pending_capacity_terminal(
    *,
    root: Path,
    state: AutonomyCodexImageOverlay,
    requested_plan_item_id: str | None,
) -> tuple[CodexImageGenerationTerminal, CodexImageArtifact] | None:
    """Recover a terminal written before its planned-state transition, if present."""

    path = _runtime_terminal_path(root, state.session_id)
    if not os.path.isfile(native_io_path(path)):
        return None
    terminal, _artifact = _load_canonical_runtime_terminal(root, path)
    if terminal.runtime_trigger != "assignment_capacity_rejected":
        raise ValueError("pending ImageGen terminal is not a capacity fallback")
    if (
        requested_plan_item_id is not None
        and terminal.plan_item_id != requested_plan_item_id
    ):
        raise ValueError("pending ImageGen terminal binds another plan item")
    plan = load_codex_image_model(
        root,
        state.generation_plan,
        CodexImageGenerationPlan,
    )
    if terminal.plan_item_id is None:
        raise ValueError("pending ImageGen terminal omits its plan item")
    plan_item = _plan_item_by_id(plan, terminal.plan_item_id)
    return _publish_or_recover_runtime_terminal(
        root=root,
        state=state,
        plan=plan,
        plan_item=plan_item,
        runtime_trigger="assignment_capacity_rejected",
    )


def _publish_or_recover_runtime_terminal(
    *,
    root: Path,
    state: AutonomyCodexImageOverlay,
    plan: CodexImageGenerationPlan,
    plan_item: CodexImageGenerationPlanItem,
    runtime_trigger: str,
    assignment_artifact: CodexImageArtifact | None = None,
    controller_request_artifact: CodexImageArtifact | None = None,
    controller_result_artifact: CodexImageArtifact | None = None,
) -> tuple[CodexImageGenerationTerminal, CodexImageArtifact]:
    """Publish one runtime terminal or reconstruct an exact crash-written predecessor."""

    path = _runtime_terminal_path(root, state.session_id)
    existing: CodexImageGenerationTerminal | None = None
    existing_artifact: CodexImageArtifact | None = None
    if os.path.isfile(native_io_path(path)):
        existing, existing_artifact = _load_canonical_runtime_terminal(root, path)
    terminal_status = (
        "cancelled"
        if runtime_trigger == "controller_cancelled"
        else plan_item.fallback
    )
    reason = _runtime_terminal_reason(runtime_trigger, terminal_status)
    budget = load_codex_image_model(
        root,
        state.budget,
        CodexImageGenerationBudget,
    )
    terminal = build_codex_imagegen_terminal(
        contract_id=f"terminal-{state.session_id}",
        terminal_id=f"terminal-{state.session_id}",
        plan_artifact=state.generation_plan,
        budget=budget,
        budget_artifact=state.budget,
        budget_usage=state.budget_usage,
        plan_item_id=plan_item.plan_item_id,
        runtime_trigger=runtime_trigger,
        status=terminal_status,
        reason=reason,
        created_at=(existing.created_at if existing is not None else _monotonic_now(state)),
        assignment_artifact=assignment_artifact,
        controller_request_artifact=controller_request_artifact,
        controller_result_artifact=controller_result_artifact,
        completion_artifact=state.completion,
        selection_artifact=state.selection,
        candidates=state.candidates,
        quality_reports=state.quality_reports,
    )
    if existing is not None:
        if existing != terminal or existing_artifact is None:
            raise ValueError("existing ImageGen runtime terminal differs")
        return existing, existing_artifact
    artifact = write_immutable_codex_image_model(
        root,
        path,
        terminal,
        kind="codex-image-generation-terminal",
    )
    return terminal, artifact


def _load_canonical_runtime_terminal(
    root: Path,
    path: Path,
) -> tuple[CodexImageGenerationTerminal, CodexImageArtifact]:
    """Strict-load one terminal and reject non-canonical crash-recovery bytes."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    raw = Path(native_io_path(safe)).read_bytes()
    terminal = CodexImageGenerationTerminal.model_validate_json(raw)
    canonical_text = (
        json.dumps(terminal.model_dump(mode="json"), indent=2, ensure_ascii=False)
        + "\n"
    )
    canonical = canonical_text.replace("\n", os.linesep).encode("utf-8")
    if raw != canonical:
        raise ValueError("existing ImageGen runtime terminal bytes are not canonical")
    artifact = artifact_for_codex_image(
        root,
        safe,
        artifact_id=terminal.contract_id,
        kind="codex-image-generation-terminal",
        media_type="application/json",
    )
    loaded = load_codex_image_model(
        root,
        artifact,
        CodexImageGenerationTerminal,
    )
    if loaded != terminal:
        raise ValueError("existing ImageGen runtime terminal cannot be reconstructed")
    return terminal, artifact


def _runtime_terminal_reason(runtime_trigger: str, terminal_status: str) -> str:
    """Map a bounded runtime outcome to one non-secret deterministic reason."""

    if runtime_trigger == "assignment_capacity_rejected":
        return f"assignment capacity rejected; applied plan fallback: {terminal_status}"
    labels = {
        "controller_timeout": "timeout",
        "controller_failed": "failed",
        "controller_rejected": "rejected",
        "controller_cancelled": "cancelled",
    }
    label = labels.get(runtime_trigger)
    if label is None:
        raise ValueError("unsupported ImageGen runtime terminal trigger")
    if runtime_trigger == "controller_cancelled":
        return "controller result cancelled; overlay cancelled"
    return f"controller result {label}; applied plan fallback: {terminal_status}"


def _controller_runtime_trigger(controller_status: str) -> str:
    """Convert one final non-completing ControllerResult status to a terminal trigger."""

    triggers = {
        "timeout": "controller_timeout",
        "failed": "controller_failed",
        "rejected": "controller_rejected",
        "cancelled": "controller_cancelled",
    }
    try:
        return triggers[controller_status]
    except KeyError as exc:
        raise ValueError("controller result is not a terminal failure status") from exc


def _runtime_terminal_response(
    *,
    state: AutonomyCodexImageOverlay,
    terminal_artifact: CodexImageArtifact,
) -> dict[str, object]:
    """Return a prompt-free public response for a fallback or cancellation terminal."""

    return {
        "status": state.status,
        "controller_status": None,
        "job_id": state.job_id,
        "session_id": state.session_id,
        "assignment": (
            state.assignment.model_dump(mode="json")
            if state.assignment is not None
            else None
        ),
        "controller_request": (
            state.controller_request.model_dump(mode="json")
            if state.controller_request is not None
            else None
        ),
        "controller_result": (
            state.controller_result.model_dump(mode="json")
            if state.controller_result is not None
            else None
        ),
        "generation_terminal": terminal_artifact.model_dump(mode="json"),
        "next_action": state.next_action,
        "repository_invoked_imagegen": False,
        "codex_controller_required": True,
    }


def _create_assignment(
    *,
    root: Path,
    job_id: str,
    session_id: str,
    state: AutonomyCodexImageOverlay,
    rendered_prompt_text: str,
    plan_item_id: str | None,
    exact_text_value: str | None,
) -> tuple[CodexImageGenerationAssignment, CodexImageArtifact]:
    """Build and publish one exact assignment from the current base material boundary."""

    plan = load_codex_image_model(root, state.generation_plan, CodexImageGenerationPlan)
    matches = [
        item for item in plan.items if plan_item_id is None or item.plan_item_id == plan_item_id
    ]
    if len(matches) != 1:
        raise ValueError("plan_item_id must identify exactly one ImageGen plan item")
    base_status = get_autonomy_v2_status(job_id, session_id)
    base_state_payload = base_status.get("state")
    if not isinstance(base_state_payload, dict) or (
        base_state_payload.get("phase"),
        base_state_payload.get("status"),
        base_state_payload.get("next_action"),
    ) != ("authoring", "running", "execute_controller"):
        raise PermissionError("ImageGen assignment requires the base material boundary")
    base_state = _codex_artifact_from_payload(base_status["state_artifact"])
    authorization = load_codex_image_model(
        root,
        plan.base_root_authorization,
        RootAuthorizationV2,
    )
    reference = CodexImageArtifact.model_validate(
        {
            **authorization.primary_reference.model_dump(mode="json"),
            "media_type": _media_type(authorization.primary_reference.path),
        }
    )
    budget = load_codex_image_model(root, state.budget, CodexImageGenerationBudget)
    assignment_id = f"material-{state.budget_usage.assignments:02d}"
    assignment = build_codex_imagegen_assignment(
        contract_id=f"assignment-{assignment_id}",
        assignment_id=assignment_id,
        sequence=state.budget_usage.assignments,
        plan=plan,
        plan_artifact=state.generation_plan,
        plan_item=matches[0],
        provider_profile_artifact=state.provider_profile,
        budget=budget,
        budget_artifact=state.budget,
        usage=state.budget_usage,
        base_state_artifact=base_state,
        job_root=root,
        rendered_prompt_text=rendered_prompt_text,
        reference_images=[reference],
        created_at=datetime.now(UTC),
        exact_text_value=exact_text_value,
    )
    artifact = run_codex_imagegen(job_root=root, assignment=assignment)
    stored = load_codex_image_model(
        root,
        artifact,
        CodexImageGenerationAssignment,
    )
    return stored, artifact


def _selected_evidence_chain(
    root: Path,
    state: AutonomyCodexImageOverlay,
) -> tuple[
    CodexImageGenerationSelection,
    CodexImageArtifact,
    CodexImageGenerationCandidate,
    CodexImageArtifact,
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationQualityReport,
    CodexImageArtifact,
]:
    """Load the one exact selected candidate, report, and generated-image evidence chain."""

    if state.status != "selected" or state.selection is None:
        raise ValueError("material adoption requires one selected ImageGen candidate")
    selection_artifact = state.selection
    selection = load_codex_image_model(
        root,
        selection_artifact,
        CodexImageGenerationSelection,
    )
    if (
        selection.outcome != "selected"
        or selection.selected_candidate is None
        or selection.selected_quality_report is None
    ):
        raise ValueError("selection has no eligible material candidate")
    candidate_artifact = selection.selected_candidate
    report_artifact = selection.selected_quality_report
    if candidate_artifact not in state.candidates or report_artifact not in state.quality_reports:
        raise ValueError("selected evidence is not part of the current overlay")
    candidate = load_codex_image_model(
        root,
        candidate_artifact,
        CodexImageGenerationCandidate,
    )
    report = load_codex_image_model(
        root,
        report_artifact,
        CodexImageGenerationQualityReport,
    )
    evidence_artifact = report.generated_image_evidence
    evidence = load_codex_image_model(
        root,
        evidence_artifact,
        CodexGeneratedImageEvidence,
    )
    if evidence.candidate != candidate_artifact or report.candidate != candidate_artifact:
        raise ValueError("selected ImageGen evidence chain is inconsistent")
    return (
        selection,
        selection_artifact,
        candidate,
        candidate_artifact,
        evidence,
        evidence_artifact,
        report,
        report_artifact,
    )


def _default_material_strategy(candidate: CodexImageGenerationCandidate) -> str:
    """Map one bounded generation intent to its additive MaterialAuthoring strategy."""

    strategies = {
        "generated_surface_swatch_v1": "codex_generated_base_color_v1",
        "generated_decal_art_v1": "codex_generated_decal_v1",
        "generated_emission_pattern_v1": "codex_generated_emission_v1",
        "reference_guided_texture_patch_v1": "codex_generated_base_color_v1",
        "generated_image_procedural_hybrid_v1": (
            "codex_generated_procedural_hybrid_v1"
        ),
    }
    return strategies[candidate.generation_intent]


def _adopted_terminal(
    *,
    root: Path,
    state: AutonomyCodexImageOverlay,
    adoption_artifact: CodexImageArtifact,
) -> CodexImageArtifact:
    """Publish or exactly adopt the generation terminal for local material adoption."""

    if state.assignment is None or state.completion is None or state.selection is None:
        raise ValueError("adopted terminal requires the complete generation chain")
    terminal_path = (
        root
        / "production"
        / "autonomy_v2"
        / state.session_id
        / "codex_imagegen"
        / "terminal.json"
    )
    if os.path.isfile(native_io_path(terminal_path)):
        terminal, artifact = _load_bound_model(
            root,
            terminal_path,
            CodexImageGenerationTerminal,
            artifact_id=f"terminal-{state.session_id}",
            kind="codex-image-generation-terminal",
        )
        if terminal.status != "adopted" or terminal.adoption != adoption_artifact:
            raise ValueError("existing ImageGen terminal differs from material adoption")
        return artifact
    budget = load_codex_image_model(root, state.budget, CodexImageGenerationBudget)
    terminal = build_codex_imagegen_terminal(
        contract_id=f"terminal-{state.session_id}",
        terminal_id=f"terminal-{state.session_id}",
        plan_artifact=state.generation_plan,
        budget=budget,
        budget_artifact=state.budget,
        budget_usage=state.budget_usage,
        status="adopted",
        reason="selected pixels were adopted only into local staging material authoring",
        created_at=_monotonic_now(state),
        assignment_artifact=state.assignment,
        completion_artifact=state.completion,
        selection_artifact=state.selection,
        adoption_artifact=adoption_artifact,
        candidates=state.candidates,
        quality_reports=state.quality_reports,
    )
    return _write_or_adopt_model(
        root,
        terminal_path,
        terminal,
        kind="codex-image-generation-terminal",
    )


def _overlay_state(
    root: Path,
    session_id: str,
) -> tuple[AutonomyCodexImageOverlay, CodexImageArtifact]:
    """Reconstruct the public phase chain and load its exact current state artifact."""

    status = get_codex_image_phase_status(root, session_id)
    payload = status.get("state")
    if not isinstance(payload, dict) or not isinstance(payload.get("artifact"), dict):
        raise FileNotFoundError("Codex ImageGen overlay is not initialized")
    artifact = CodexImageArtifact.model_validate(payload["artifact"])
    return load_codex_image_model(root, artifact, AutonomyCodexImageOverlay), artifact


def _codex_artifact_from_payload(payload: object) -> CodexImageArtifact:
    """Convert one exact AQ artifact mapping into the JSON companion shape."""

    if not isinstance(payload, dict):
        raise ValueError("expected one exact artifact mapping")
    return CodexImageArtifact.model_validate(
        {**payload, "media_type": "application/json"}
    )


def _media_type(path: str) -> str:
    """Return a deterministic media type for one exact reference suffix."""

    guessed, _encoding = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _load_or_build_candidate_evidence(
    *,
    root: Path,
    state: AutonomyCodexImageOverlay,
    assignment: CodexImageGenerationAssignment,
    completion: CodexImageGenerationCompletion,
) -> tuple[
    list[tuple[CodexImageGenerationCandidate, CodexImageArtifact]],
    list[tuple[CodexGeneratedImageEvidence, CodexImageArtifact]],
]:
    """Revalidate completion and publish or exactly recover every host evidence pair."""

    if (
        state.assignment is None
        or state.completion is None
        or state.controller_request is None
        or state.controller_result is None
    ):
        raise ValueError("candidate evidence requires exact assignment and completion")
    adopted = adopt_codex_imagegen_completion(
        job_root=root,
        assignment_artifact=state.assignment,
        completion_artifact=state.completion,
        controller_request_artifact=state.controller_request,
        controller_result_artifact=state.controller_result,
        controller=DesktopInSessionController(),
        created_at=completion.controller_executed_at + timedelta(seconds=1),
    )
    return list(adopted.candidates), list(adopted.generated_evidence)


def _load_or_build_quality_reports(
    *,
    root: Path,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidates: list[tuple[CodexImageGenerationCandidate, CodexImageArtifact]],
    evidence: list[tuple[CodexGeneratedImageEvidence, CodexImageArtifact]],
    created_at: datetime,
) -> list[tuple[CodexImageGenerationQualityReport, CodexImageArtifact]]:
    """Recompute deterministic quality and require exact persisted report equality."""

    reports = []
    evidence_by_candidate = {
        _artifact_key(model.candidate): (model, artifact)
        for model, artifact in evidence
    }
    for candidate, candidate_artifact in candidates:
        generated, generated_artifact = evidence_by_candidate[
            _artifact_key(candidate_artifact)
        ]
        ordinal = candidate.generated_file.ordinal
        report = evaluate_candidate_quality(
            job_root=root,
            report_id=f"quality-{assignment.assignment_id}-{ordinal:02d}",
            assignment=assignment,
            assignment_artifact=assignment_artifact,
            completion_artifact=completion_artifact,
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            generated_image_evidence=generated,
            generated_image_evidence_artifact=generated_artifact,
            created_at=created_at,
        )
        path = Path(root / candidate_artifact.path).parent / f"quality-{ordinal:02d}.json"
        artifact = _write_or_adopt_model(
            root,
            path,
            report,
            kind="codex-image-generation-quality-report",
        )
        reports.append((report, artifact))
    return reports


def _load_or_build_selection(
    *,
    root: Path,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    candidates: list[tuple[CodexImageGenerationCandidate, CodexImageArtifact]],
    reports: list[tuple[CodexImageGenerationQualityReport, CodexImageArtifact]],
    created_at: datetime,
) -> tuple[CodexImageGenerationSelection, CodexImageArtifact]:
    """Publish deterministic selection once or revalidate its exact stored bytes."""

    path = (
        root
        / "production"
        / "autonomy_v2"
        / assignment.session_id
        / "codex_imagegen"
        / "assignments"
        / assignment.assignment_id
        / "selection.json"
    )
    if os.path.isfile(native_io_path(path)):
        return _load_bound_model(
            root,
            path,
            CodexImageGenerationSelection,
            artifact_id=f"selection-{assignment.assignment_id}",
            kind="codex-image-generation-selection",
        )
    return select_codex_imagegen_candidate(
        job_root=root,
        selection_id=f"selection-{assignment.assignment_id}",
        assignment=assignment,
        assignment_artifact=assignment_artifact,
        completion_artifact=completion_artifact,
        candidates=candidates,
        quality_reports=reports,
        created_at=created_at,
    )


def _selection_terminal(
    *,
    root: Path,
    state: AutonomyCodexImageOverlay,
    assignment: CodexImageGenerationAssignment,
    selection: CodexImageGenerationSelection,
    selection_artifact: CodexImageArtifact,
) -> CodexImageArtifact:
    """Publish one review terminal when deterministic selection has no eligible candidate."""

    budget = load_codex_image_model(root, state.budget, CodexImageGenerationBudget)
    terminal = build_codex_imagegen_terminal(
        contract_id=f"terminal-{assignment.assignment_id}",
        terminal_id=f"terminal-{assignment.assignment_id}",
        plan_artifact=state.generation_plan,
        budget=budget,
        budget_artifact=state.budget,
        budget_usage=state.budget_usage,
        status="review_required",
        reason=f"selection outcome: {selection.outcome}",
        created_at=datetime.now(UTC),
        assignment_artifact=state.assignment,
        completion_artifact=state.completion,
        selection_artifact=selection_artifact,
        candidates=state.candidates,
        quality_reports=state.quality_reports,
    )
    path = (
        root
        / "production"
        / "autonomy_v2"
        / state.session_id
        / "codex_imagegen"
        / "terminal.json"
    )
    return _write_or_adopt_model(
        root,
        path,
        terminal,
        kind="codex-image-generation-terminal",
    )


def _load_bound_model(
    root: Path,
    path: Path,
    model_type: type[ModelT],
    *,
    artifact_id: str,
    kind: str,
) -> tuple[ModelT, CodexImageArtifact]:
    """Rebind one existing JSON path and strict-load its declared model."""

    artifact = artifact_for_codex_image(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
        media_type="application/json",
    )
    return load_codex_image_model(root, artifact, model_type), artifact


def _resolve_exact_text_evidence_artifact(
    *,
    root: Path,
    assignment: CodexImageGenerationAssignment,
    supplied_path: Path | None,
    existing: CodexImageArtifact | None,
) -> CodexImageArtifact | None:
    """Resolve or recover one strict exact-text artifact and recheck assignment authority."""

    artifact = existing
    if supplied_path is not None:
        candidate_path = supplied_path if supplied_path.is_absolute() else root / supplied_path
        safe_path = ensure_contained_production_path(
            root,
            candidate_path,
            must_exist=True,
        )
        _evidence, supplied = _load_bound_model(
            root,
            safe_path,
            ExactSignageTextEvidenceV021,
            artifact_id=f"exact-text-{assignment.assignment_id}",
            kind="exact-signage-text-evidence",
        )
        if existing is not None and existing != supplied:
            raise ValueError("supplied exact signage text differs from existing adoption")
        artifact = supplied
    validate_codex_imagegen_exact_text_binding(
        job_root=root,
        assignment=assignment,
        exact_text_composition=artifact,
    )
    return artifact


def _artifact_key(artifact: CodexImageArtifact) -> tuple[str, str, int, str]:
    """Return the immutable identity used to join candidate evidence safely."""

    return (artifact.path, artifact.sha256, artifact.byte_size, artifact.kind)


def _monotonic_now(
    state: AutonomyCodexImageOverlay,
    *evidence_times: datetime,
) -> datetime:
    """Return a current timestamp that never precedes persisted overlay evidence."""

    return max(datetime.now(UTC), state.created_at, *evidence_times)


def _write_or_adopt_model(
    root: Path,
    path: Path,
    model: ModelT,
    *,
    kind: str,
) -> CodexImageArtifact:
    """Publish one model once or require exact equality with an existing contract."""

    if os.path.isfile(native_io_path(path)):
        existing, artifact = _load_bound_model(
            root,
            path,
            type(model),
            artifact_id=str(model.contract_id),
            kind=kind,
        )
        if existing != model:
            raise ValueError("existing ImageGen command evidence differs")
        return artifact
    return write_immutable_codex_image_model(root, path, model, kind=kind)
