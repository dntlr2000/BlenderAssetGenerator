"""Credential-free provider profile construction for the ImageGen companion."""

from __future__ import annotations

from datetime import datetime

from ..blender_artifacts import stable_json_digest
from .models import (
    ALL_DIRECT_OUTPUT_ROLES,
    ALL_FORBIDDEN_DIRECT_CHANNELS,
    ALL_GENERATION_INTENTS,
    CodexBuiltinImageProviderProfile,
    CodexImageArtifact,
)


def codex_imagegen_profile_status() -> dict[str, object]:
    """Return the static disabled-by-default capability boundary without probing a network."""

    return {
        "profile_id": "autonomous_static_prop_v2_codex_imagegen",
        "provider_id": "codex_builtin_gpt_image_v1",
        "status": "disabled_experimental",
        "execution_mode": "controller_mediated",
        "credential_scope": "none",
        "network_required": False,
        "api_key_required": False,
        "repository_can_spawn_codex_task": False,
        "autonomous_daemon": False,
    }


def build_codex_builtin_image_provider_profile(
    *,
    contract_id: str,
    provider_profile_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    base_profile_artifact: CodexImageArtifact,
    created_at: datetime,
    producer: str = "codex_blender_modeler.codex_imagegen.profile",
) -> CodexBuiltinImageProviderProfile:
    """Build the honest disabled-experimental profile without activation claims."""

    inputs = {
        "base_profile": base_profile_artifact.model_dump(mode="json"),
        "provider_id": "codex_builtin_gpt_image_v1",
        "execution_mode": "controller_mediated",
    }
    return CodexBuiltinImageProviderProfile(
        contract_id=contract_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "status": "disabled_experimental"}
        ),
        producer=producer,
        provenance=[base_profile_artifact],
        created_at=created_at,
        provider_profile_id=provider_profile_id,
        allowed_generation_intents=list(ALL_GENERATION_INTENTS),
        allowed_direct_output_roles=list(ALL_DIRECT_OUTPUT_ROLES),
        forbidden_direct_channels=list(ALL_FORBIDDEN_DIRECT_CHANNELS),
        status="disabled_experimental",
        activation_evidence=[],
    )
