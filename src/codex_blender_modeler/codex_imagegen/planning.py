"""Explicit opt-in generation plan construction for the ImageGen overlay."""

from __future__ import annotations

from datetime import datetime

from ..blender_artifacts import stable_json_digest
from .models import (
    CodexBuiltinImageProviderProfile,
    CodexImageArtifact,
    CodexImageGenerationBudget,
    CodexImageGenerationPlan,
    CodexImageGenerationPlanItem,
)


def build_codex_imagegen_plan(
    *,
    contract_id: str,
    plan_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    base_autonomy_plan: CodexImageArtifact,
    base_root_authorization: CodexImageArtifact,
    provider_profile: CodexBuiltinImageProviderProfile,
    provider_profile_artifact: CodexImageArtifact,
    budget: CodexImageGenerationBudget,
    budget_artifact: CodexImageArtifact,
    items: list[CodexImageGenerationPlanItem],
    created_at: datetime,
) -> CodexImageGenerationPlan:
    """Build one explicit opt-in plan without upgrading experimental provider status."""

    identity = (job_id, workflow_id, dispatch_id, session_id)
    if (
        provider_profile.job_id,
        provider_profile.workflow_id,
        provider_profile.dispatch_id,
        provider_profile.session_id,
    ) != identity:
        raise ValueError("provider profile identity differs from the generation plan")
    if (
        budget.job_id,
        budget.workflow_id,
        budget.dispatch_id,
        budget.session_id,
    ) != identity:
        raise ValueError("generation budget identity differs from the generation plan")
    if not items:
        raise ValueError("Codex ImageGen plan requires at least one plan item")
    inputs = {
        "base_autonomy_plan": base_autonomy_plan.model_dump(mode="json"),
        "base_root_authorization": base_root_authorization.model_dump(mode="json"),
        "provider_profile": provider_profile_artifact.model_dump(mode="json"),
        "budget": budget_artifact.model_dump(mode="json"),
        "items": [item.model_dump(mode="json") for item in items],
    }
    provenance = [
        base_autonomy_plan,
        base_root_authorization,
        provider_profile_artifact,
        budget_artifact,
    ]
    return CodexImageGenerationPlan(
        contract_id=contract_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "profile_status": provider_profile.status}
        ),
        producer="codex_blender_modeler.codex_imagegen.planning",
        provenance=provenance,
        created_at=created_at,
        plan_id=plan_id,
        base_autonomy_plan=base_autonomy_plan,
        base_root_authorization=base_root_authorization,
        provider_profile=provider_profile_artifact,
        budget=budget_artifact,
        items=items,
    )
