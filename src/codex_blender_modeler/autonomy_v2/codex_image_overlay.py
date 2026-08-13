"""Strict append-only state for the optional Codex ImageGen AQ v2 overlay."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ..blender_artifacts import stable_json_digest
from ..codex_imagegen.models import (
    CodexImageArtifact,
    CodexImageEvidenceEnvelope,
    CodexImageGenerationBudgetUsage,
)

CODEX_IMAGE_OVERLAY_SCHEMA_VERSION = "0.1.0"
CODEX_IMAGE_OVERLAY_PROFILE_ID = "autonomous_static_prop_v2_codex_imagegen"
CODEX_IMAGE_OVERLAY_STATUS = "disabled_experimental"

OverlayEvent = Literal[
    "initialized",
    "assignment_published",
    "completion_adopted",
    "quality_completed",
    "candidate_selected",
    "material_adopted",
    "material_candidate_staged",
    "material_evidence_repaired",
    "base_material_authoring_resumed",
    "local_procedural_fallback",
    "review_required",
    "user_image_required",
    "failed",
    "cancelled",
]


class AutonomyCodexImageOverlay(CodexImageEvidenceEnvelope):
    """Represent one reconstructable companion state without changing base AQ v2."""

    overlay_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    base_profile: Literal["autonomous_static_prop_v2"] = "autonomous_static_prop_v2"
    profile_status: Literal["disabled_experimental"] = CODEX_IMAGE_OVERLAY_STATUS
    execution_mode: Literal["controller_mediated"] = "controller_mediated"
    controller_mode: Literal["desktop_in_session"] = "desktop_in_session"
    codex_imagegen_allowed: Literal[True] = True
    controller_required: Literal[True] = True
    repository_can_spawn_codex_task: Literal[False] = False
    autonomous_daemon: Literal[False] = False
    continuation_after_app_exit: Literal[False] = False
    destination_project_write: Literal[False] = False
    canonical_material_write: Literal[False] = False
    generation_plan: CodexImageArtifact
    provider_profile: CodexImageArtifact
    budget: CodexImageArtifact
    sequence: int = Field(ge=0)
    transition_event: OverlayEvent
    phase: Literal[
        "planned",
        "controller",
        "completion",
        "quality",
        "selection",
        "adoption",
        "resume",
        "terminal",
    ]
    status: Literal[
        "planned",
        "waiting_for_controller",
        "completion_adopted",
        "quality_ready",
        "selected",
        "adopted",
        "completed",
        "local_procedural_fallback",
        "review_required",
        "user_image_required",
        "failed",
        "cancelled",
    ]
    next_action: Literal[
        "publish_assignment",
        "adopt_completion",
        "evaluate_quality",
        "select_candidate",
        "adopt_material",
        "resume_base_material_authoring",
        "controller_promotion_required",
        "none",
    ]
    budget_usage: CodexImageGenerationBudgetUsage = Field(
        default_factory=CodexImageGenerationBudgetUsage
    )
    assignment: CodexImageArtifact | None = None
    controller_request: CodexImageArtifact | None = None
    completion: CodexImageArtifact | None = None
    controller_result: CodexImageArtifact | None = None
    candidates: list[CodexImageArtifact] = Field(default_factory=list, max_length=3)
    quality_reports: list[CodexImageArtifact] = Field(default_factory=list, max_length=3)
    selection: CodexImageArtifact | None = None
    material_adoption: CodexImageArtifact | None = None
    material_authoring_receipt: CodexImageArtifact | None = None
    generation_terminal: CodexImageArtifact | None = None
    base_resume_state: CodexImageArtifact | None = None
    previous_state_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    terminal_reason: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_overlay_boundary(self) -> AutonomyCodexImageOverlay:
        """Require each lifecycle boundary to carry its complete exact evidence."""

        if self.sequence == 0:
            if self.transition_event != "initialized" or self.previous_state_sha256 is not None:
                raise ValueError("initial overlay state requires initialized with no predecessor")
        elif self.transition_event == "initialized" or self.previous_state_sha256 is None:
            raise ValueError("non-initial overlay state requires an exact predecessor")
        if self.status == "waiting_for_controller" and self.assignment is None:
            raise ValueError("waiting overlay state requires one immutable assignment")
        if self.status in {
            "completion_adopted",
            "quality_ready",
            "selected",
            "adopted",
            "completed",
        } and any(
            item is None
            for item in (
                self.assignment,
                self.controller_request,
                self.completion,
                self.controller_result,
            )
        ):
            raise ValueError(
                "post-completion overlay state requires assignment, controller request, "
                "completion, and controller result"
            )
        if self.status in {"quality_ready", "selected", "adopted", "completed"}:
            if not self.candidates or len(self.candidates) != len(self.quality_reports):
                raise ValueError("quality-ready overlay state requires every candidate report")
        if self.status in {"selected", "adopted", "completed"} and self.selection is None:
            raise ValueError("selected overlay state requires exact selection evidence")
        if self.status in {"adopted", "completed"}:
            if any(
                item is None
                for item in (
                    self.material_adoption,
                    self.material_authoring_receipt,
                    self.generation_terminal,
                )
            ):
                raise ValueError(
                    "adopted overlay state requires adoption, material receipt, "
                    "and terminal evidence"
                )
        if self.status == "completed" and self.base_resume_state is None:
            raise ValueError("completed overlay state requires the resumed base AQ state")
        terminal_statuses = {
            "completed",
            "local_procedural_fallback",
            "review_required",
            "user_image_required",
            "failed",
            "cancelled",
        }
        if self.status in terminal_statuses:
            if self.phase != "terminal" or self.next_action != "none":
                raise ValueError("terminal overlay state cannot advertise another action")
            if self.generation_terminal is None or not self.terminal_reason:
                raise ValueError("terminal overlay state requires terminal evidence and reason")
        elif self.phase == "terminal" or self.next_action == "none":
            raise ValueError("non-terminal overlay state must advertise its next action")
        named = [
            self.generation_plan,
            self.provider_profile,
            self.budget,
            *([self.assignment] if self.assignment is not None else []),
            *([self.controller_request] if self.controller_request is not None else []),
            *([self.completion] if self.completion is not None else []),
            *([self.controller_result] if self.controller_result is not None else []),
            *self.candidates,
            *self.quality_reports,
            *([self.selection] if self.selection is not None else []),
            *([self.material_adoption] if self.material_adoption is not None else []),
            *(
                [self.material_authoring_receipt]
                if self.material_authoring_receipt is not None
                else []
            ),
            *([self.generation_terminal] if self.generation_terminal is not None else []),
            *([self.base_resume_state] if self.base_resume_state is not None else []),
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("overlay state omits named immutable provenance")
        return self


def codex_image_overlay_profile_status() -> dict[str, object]:
    """Report the optional profile without implying verified ImageGen execution."""

    return {
        "profile_id": CODEX_IMAGE_OVERLAY_PROFILE_ID,
        "contract_version": CODEX_IMAGE_OVERLAY_SCHEMA_VERSION,
        "status": CODEX_IMAGE_OVERLAY_STATUS,
        "base_profile": "autonomous_static_prop_v2",
        "execution_mode": "controller_mediated",
        "controller_mode": "desktop_in_session",
        "provider_id": "codex_builtin_gpt_image_v1",
        "controller_required": True,
        "repository_can_spawn_codex_task": False,
        "autonomous_daemon": False,
        "continuation_after_app_exit": False,
        "network_required": False,
        "api_key_required": False,
        "destination_project_write": False,
        "verified_active": False,
    }


def initial_codex_image_overlay(
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    generation_plan: CodexImageArtifact,
    provider_profile: CodexImageArtifact,
    budget: CodexImageArtifact,
    created_at: datetime,
    codex_imagegen_allowed: bool,
) -> AutonomyCodexImageOverlay:
    """Create the sequence-zero state only after exact experimental opt-in."""

    if codex_imagegen_allowed is not True:
        raise PermissionError("Codex ImageGen overlay requires codex_imagegen_allowed=true")
    provenance = [generation_plan, provider_profile, budget]
    payload = {
        "generation_plan": generation_plan.sha256,
        "provider_profile": provider_profile.sha256,
        "budget": budget.sha256,
        "sequence": 0,
    }
    return AutonomyCodexImageOverlay(
        contract_id=f"codex-image-overlay-{session_id}-0000",
        overlay_id=f"codex-image-overlay-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(payload),
        source_fingerprint=stable_json_digest({**payload, "status": "planned"}),
        producer="codex_blender_modeler.autonomy_v2.codex_image_overlay",
        provenance=provenance,
        created_at=created_at,
        generation_plan=generation_plan,
        provider_profile=provider_profile,
        budget=budget,
        sequence=0,
        transition_event="initialized",
        phase="planned",
        status="planned",
        next_action="publish_assignment",
    )


def transition_codex_image_overlay(
    current: AutonomyCodexImageOverlay,
    *,
    event: OverlayEvent,
    evidence: list[CodexImageArtifact],
    created_at: datetime,
    budget_usage: CodexImageGenerationBudgetUsage | None = None,
    assignment: CodexImageArtifact | None = None,
    controller_request: CodexImageArtifact | None = None,
    completion: CodexImageArtifact | None = None,
    controller_result: CodexImageArtifact | None = None,
    candidates: list[CodexImageArtifact] | None = None,
    quality_reports: list[CodexImageArtifact] | None = None,
    selection: CodexImageArtifact | None = None,
    material_adoption: CodexImageArtifact | None = None,
    material_authoring_receipt: CodexImageArtifact | None = None,
    generation_terminal: CodexImageArtifact | None = None,
    base_resume_state: CodexImageArtifact | None = None,
    reason: str | None = None,
) -> AutonomyCodexImageOverlay:
    """Return one deterministic successor without performing filesystem writes."""

    if current.next_action == "none":
        raise ValueError("terminal Codex ImageGen overlay cannot transition")
    if not evidence:
        raise ValueError("overlay transition requires exact evidence")
    if created_at < current.created_at:
        raise ValueError("overlay transition timestamp cannot move backwards")
    evidence_keys = [(item.path, item.sha256, item.kind) for item in evidence]
    if len(evidence_keys) != len(set(evidence_keys)):
        raise ValueError("overlay transition evidence must be unique")
    if any(item in current.provenance for item in evidence):
        raise ValueError("overlay transition cannot replay consumed evidence")
    boundary = (current.phase, current.status, current.next_action)
    allowed: dict[tuple[str, str, str], frozenset[str]] = {
        ("planned", "planned", "publish_assignment"): frozenset(
            {
                "assignment_published",
                "local_procedural_fallback",
                "review_required",
                "user_image_required",
                "failed",
                "cancelled",
            }
        ),
        ("controller", "waiting_for_controller", "adopt_completion"): frozenset(
            {
                "completion_adopted",
                "local_procedural_fallback",
                "review_required",
                "user_image_required",
                "failed",
                "cancelled",
            }
        ),
        ("completion", "completion_adopted", "evaluate_quality"): frozenset(
            {"quality_completed", "review_required", "failed", "cancelled"}
        ),
        ("quality", "quality_ready", "select_candidate"): frozenset(
            {"candidate_selected", "review_required", "failed", "cancelled"}
        ),
        ("selection", "selected", "adopt_material"): frozenset(
            {
                "material_adopted",
                "material_candidate_staged",
                "review_required",
                "failed",
                "cancelled",
            }
        ),
        ("adoption", "adopted", "resume_base_material_authoring"): frozenset(
            {"base_material_authoring_resumed", "failed", "cancelled"}
        ),
        ("adoption", "adopted", "controller_promotion_required"): frozenset(
            {"material_evidence_repaired", "failed", "cancelled"}
        ),
    }
    if event == "initialized" or event not in allowed.get(boundary, frozenset()):
        raise ValueError(f"invalid Codex ImageGen overlay transition: {boundary!r} -> {event}")
    mapping: dict[str, tuple[str, str, str]] = {
        "assignment_published": ("controller", "waiting_for_controller", "adopt_completion"),
        "completion_adopted": ("completion", "completion_adopted", "evaluate_quality"),
        "quality_completed": ("quality", "quality_ready", "select_candidate"),
        "candidate_selected": ("selection", "selected", "adopt_material"),
        "material_adopted": ("adoption", "adopted", "resume_base_material_authoring"),
        "material_candidate_staged": (
            "adoption",
            "adopted",
            "controller_promotion_required",
        ),
        "material_evidence_repaired": (
            "adoption",
            "adopted",
            "controller_promotion_required",
        ),
        "base_material_authoring_resumed": ("terminal", "completed", "none"),
        "local_procedural_fallback": ("terminal", "local_procedural_fallback", "none"),
        "review_required": ("terminal", "review_required", "none"),
        "user_image_required": ("terminal", "user_image_required", "none"),
        "failed": ("terminal", "failed", "none"),
        "cancelled": ("terminal", "cancelled", "none"),
    }
    phase, status, next_action = mapping[event]
    next_assignment = assignment or current.assignment
    next_controller_request = controller_request or current.controller_request
    next_completion = completion or current.completion
    next_controller_result = controller_result or current.controller_result
    next_candidates = list(candidates if candidates is not None else current.candidates)
    next_reports = list(quality_reports if quality_reports is not None else current.quality_reports)
    next_selection = selection or current.selection
    next_adoption = material_adoption or current.material_adoption
    next_material_receipt = material_authoring_receipt or current.material_authoring_receipt
    next_terminal = generation_terminal or current.generation_terminal
    next_resume = base_resume_state or current.base_resume_state
    next_usage = budget_usage or current.budget_usage
    current_usage = current.budget_usage.model_dump()
    updated_usage = next_usage.model_dump()
    if any(updated_usage[key] < value for key, value in current_usage.items()):
        raise ValueError("overlay transition cannot roll back budget usage")
    if event != "completion_adopted" and next_usage != current.budget_usage:
        raise ValueError("only completion adoption may change overlay budget usage")
    if event == "completion_adopted" and (
        next_usage.assignments != current.budget_usage.assignments + 1
        or next_usage.total_generations < current.budget_usage.total_generations
        or next_usage.candidates < current.budget_usage.candidates
    ):
        raise ValueError("completion adoption must consume one assignment budget")
    if event == "assignment_published" and (assignment is None or evidence != [assignment]):
        raise ValueError("assignment transition must name its exact assignment evidence")
    if event == "completion_adopted" and (
        controller_request is None
        or completion is None
        or controller_result is None
        or evidence != [controller_request, completion, controller_result]
    ):
        raise ValueError(
            "completion transition must name its exact controller request, completion, "
            "and controller result"
        )
    if event == "quality_completed" and (
        not next_candidates
        or len(next_candidates) != len(next_reports)
        or evidence != [*next_candidates, *next_reports]
    ):
        raise ValueError("quality transition must preserve every candidate and report")
    if event == "candidate_selected" and (selection is None or evidence != [selection]):
        raise ValueError("selection transition must name its exact selection evidence")
    if event in {"material_adopted", "material_candidate_staged"} and (
        material_adoption is None
        or material_authoring_receipt is None
        or generation_terminal is None
        or evidence != [material_adoption, material_authoring_receipt, generation_terminal]
    ):
        raise ValueError(
            "material adoption requires adoption, material receipt, and terminal evidence"
        )
    if event == "material_evidence_repaired" and (
        current.material_authoring_receipt is None
        or material_authoring_receipt is None
        or material_authoring_receipt == current.material_authoring_receipt
        or len(evidence) != 3
        or evidence[0].kind != "material-evidence-repair-plan"
        or evidence[1].kind != "material-evidence-repair-approval"
        or evidence[2] != material_authoring_receipt
        or material_authoring_receipt.kind != "codex-image-normalized-material-authoring-receipt"
    ):
        raise ValueError(
            "material evidence repair requires a new normalized receipt and exact plan/approval"
        )
    if event == "base_material_authoring_resumed" and (
        base_resume_state is None or evidence != [base_resume_state]
    ):
        raise ValueError("base resume transition must name the exact resumed AQ state")
    terminal_events = {
        "local_procedural_fallback",
        "review_required",
        "user_image_required",
        "failed",
        "cancelled",
    }
    terminal_reason = reason
    if event in terminal_events:
        controller_terminal_evidence = [
            item
            for item in (controller_request, controller_result)
            if item is not None and item not in current.provenance
        ]
        if (
            (controller_request is None) != (controller_result is None)
            or generation_terminal is None
            or evidence != [*controller_terminal_evidence, generation_terminal]
        ):
            raise ValueError("terminal transition requires its exact generation terminal")
        terminal_reason = reason or event.replace("_", " ")
    elif event == "base_material_authoring_resumed":
        terminal_reason = reason or "Codex image adoption resumed base material authoring"
    previous_sha = stable_json_digest(current.model_dump(mode="json"))
    transition_payload = {
        "previous": previous_sha,
        "event": event,
        "evidence": [item.sha256 for item in evidence],
        "sequence": current.sequence + 1,
    }
    payload = current.model_dump(mode="json")
    return AutonomyCodexImageOverlay.model_validate(
        {
            **payload,
            "contract_id": (f"codex-image-overlay-{current.session_id}-{current.sequence + 1:04d}"),
            "input_sha256": stable_json_digest(transition_payload),
            "source_fingerprint": stable_json_digest(
                {**transition_payload, "status": status, "next_action": next_action}
            ),
            "producer": "codex_blender_modeler.autonomy_v2.codex_image_overlay",
            "provenance": [*current.provenance, *evidence],
            "created_at": created_at,
            "sequence": current.sequence + 1,
            "transition_event": event,
            "phase": phase,
            "status": status,
            "next_action": next_action,
            "budget_usage": next_usage,
            "assignment": next_assignment,
            "controller_request": next_controller_request,
            "completion": next_completion,
            "controller_result": next_controller_result,
            "candidates": next_candidates,
            "quality_reports": next_reports,
            "selection": next_selection,
            "material_adoption": next_adoption,
            "material_authoring_receipt": next_material_receipt,
            "generation_terminal": next_terminal,
            "base_resume_state": next_resume,
            "previous_state_sha256": previous_sha,
            "terminal_reason": terminal_reason,
        }
    )
