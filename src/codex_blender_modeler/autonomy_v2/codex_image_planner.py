"""Plan the optional Codex built-in ImageGen overlay over an unchanged AQ v2 session."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ..codex_imagegen.artifacts import write_immutable_codex_image_model
from ..codex_imagegen.budget import build_default_codex_imagegen_budget
from ..codex_imagegen.models import (
    CodexImageArtifact,
    CodexImageDimensions,
    CodexImageGenerationPlanItem,
    DirectOutputRole,
    GenerationIntent,
    ImageAspectRatio,
    ImageQualityLevel,
)
from ..codex_imagegen.planning import build_codex_imagegen_plan
from ..codex_imagegen.profile import build_codex_builtin_image_provider_profile
from ..codex_imagegen.public_service import plan_codex_imagegen
from ..workspace import job_dir
from .codex_image_phase_service import initialize_codex_image_phase
from .models import DeliveryProfileId
from .planner import plan_autonomous_static_prop_v2


def plan_autonomous_static_prop_v2_codex_imagegen(
    request: str,
    *,
    reference_path: str | Path,
    target_subject: str,
    requested_delivery_profiles: list[DeliveryProfileId],
    target_material_ids: list[str],
    semantic_roles: list[str],
    allowed_output_roles: list[DirectOutputRole],
    generation_intent: GenerationIntent,
    prompt_template_id: str,
    requested_candidate_count: int = 1,
    quality_level: ImageQualityLevel = "low",
    image_width: int = 1024,
    image_height: int = 1024,
    aspect_ratio: ImageAspectRatio = "square",
    fallback: str = "local_procedural_fallback",
    job_id: str | None = None,
    controller_execution_mode: str = "desktop_in_session",
    destination_hint: str = "engine_neutral",
    codex_imagegen_allowed: bool = False,
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Create a local-only AQ v2 base plus an additive disabled ImageGen plan."""

    if codex_imagegen_allowed is not True or allow_disabled_experimental is not True:
        raise PermissionError(
            "Codex ImageGen requires explicit provider and disabled-profile opt-in"
        )
    base = plan_autonomous_static_prop_v2(
        request,
        reference_path=reference_path,
        target_subject=target_subject,
        requested_delivery_profiles=requested_delivery_profiles,
        job_id=job_id,
        controller_execution_mode=controller_execution_mode,
        destination_hint=destination_hint,
        allow_disabled_experimental=True,
    )
    root = job_dir(str(base["job_id"]))
    session_id = str(base["session_id"])
    workflow_id = str(base["workflow_id"])
    dispatch_id = str(base["dispatch_id"])
    created_at = datetime.now(UTC)
    base_plan = _codex_artifact(base, "plan")
    base_authorization = _codex_artifact(base, "root_authorization")
    companion_root = (
        root / "production" / "autonomy_v2" / session_id / "codex_imagegen"
    )
    provider = build_codex_builtin_image_provider_profile(
        contract_id=f"codex-profile-{session_id}",
        provider_profile_id=f"codex-profile-{session_id}",
        job_id=str(base["job_id"]),
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        base_profile_artifact=base_plan,
        created_at=created_at,
    )
    provider_artifact = write_immutable_codex_image_model(
        root,
        companion_root / "provider-profile.json",
        provider,
        kind="codex-builtin-image-provider-profile",
    )
    budget = build_default_codex_imagegen_budget(
        contract_id=f"codex-budget-{session_id}",
        budget_id=f"codex-budget-{session_id}",
        job_id=str(base["job_id"]),
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        provider_profile=provider_artifact,
        created_at=created_at,
    )
    budget_artifact = write_immutable_codex_image_model(
        root,
        companion_root / "budget.json",
        budget,
        kind="codex-image-generation-budget",
    )
    item = CodexImageGenerationPlanItem(
        plan_item_id="codex-image-material-00",
        target_material_ids=target_material_ids,
        semantic_roles=semantic_roles,
        generation_intent=generation_intent,
        allowed_output_roles=allowed_output_roles,
        prompt_template_id=prompt_template_id,
        requested_candidate_count=requested_candidate_count,
        quality_level=quality_level,
        image_size=CodexImageDimensions(
            width=image_width,
            height=image_height,
        ),
        aspect_ratio=aspect_ratio,
        fallback=fallback,
    )
    plan = build_codex_imagegen_plan(
        contract_id=f"codex-plan-{session_id}",
        plan_id=f"codex-plan-{session_id}",
        job_id=str(base["job_id"]),
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        base_autonomy_plan=base_plan,
        base_root_authorization=base_authorization,
        provider_profile=provider,
        provider_profile_artifact=provider_artifact,
        budget=budget,
        budget_artifact=budget_artifact,
        items=[item],
        created_at=created_at,
    )
    plan_artifact = plan_codex_imagegen(job_root=root, plan=plan)
    overlay, overlay_artifact = initialize_codex_image_phase(
        root,
        generation_plan=plan_artifact,
        provider_profile=provider_artifact,
        budget=budget_artifact,
        created_at=created_at,
        allow_disabled_experimental=True,
    )
    return {
        "profile_status": "disabled_experimental",
        "experimental_override_used": True,
        "base": base,
        "job_id": base["job_id"],
        "workflow_id": workflow_id,
        "dispatch_id": dispatch_id,
        "session_id": session_id,
        "provider_profile": provider.model_dump(mode="json"),
        "budget": budget.model_dump(mode="json"),
        "generation_plan": plan.model_dump(mode="json"),
        "overlay": overlay.model_dump(mode="json"),
        "artifacts": {
            "provider_profile": provider_artifact.model_dump(mode="json"),
            "budget": budget_artifact.model_dump(mode="json"),
            "generation_plan": plan_artifact.model_dump(mode="json"),
            "overlay": overlay_artifact.model_dump(mode="json"),
        },
        "controller_required": True,
        "repository_can_spawn_codex_task": False,
        "autonomous_daemon": False,
        "network_required": False,
        "api_key_required": False,
    }


def _codex_artifact(payload: dict[str, object], name: str) -> CodexImageArtifact:
    """Convert one exact base AQ artifact response into the companion shape."""

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get(name), dict):
        raise ValueError(f"base AQ v2 response has no exact {name} artifact")
    return CodexImageArtifact.model_validate(
        {**artifacts[name], "media_type": "application/json"}
    )
