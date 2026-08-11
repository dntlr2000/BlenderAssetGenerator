"""Pure phase-tool profile catalog for ControllerExecutor 0.1.0."""

from __future__ import annotations

from datetime import datetime

from ...blender_artifacts import stable_json_digest
from .models import ControllerArtifact, PhaseToolProfile

_FORBIDDEN_AUTHORITY_TOOLS = [
    "approve_workflow_checkpoint",
    "approve_visual_revision",
    "approve_optimization_plan",
    "approve_destination_handoff",
    "resume_short_workflow_retry_failed",
    "run_arbitrary_blender_python",
    "run_shell_command",
    "write_destination_project",
]

_PROFILE_TOOLS: dict[str, list[str]] = {
    "reference_readonly": ["get_modeling_capabilities", "get_workflow_state"],
    "geometry_authoring": ["get_workflow_state", "record_delegated_production_step"],
    "material_authoring": ["get_workflow_state", "record_delegated_production_step"],
    # This names a current-task Codex capability, not a project MCP or network provider.
    "codex_imagegen": ["imagegen"],
    "quality_readonly": ["get_workflow_state", "get_integrated_quality_status"],
    "delivery": [
        "get_asset_production_dispatch_status",
        "advance_delegated_production_controller",
    ],
    "handoff_plan": ["get_asset_production_dispatch_status"],
    "admin_audit": ["get_asset_production_dispatch_status", "audit_workspace_state"],
}


def phase_tool_profile_catalog() -> dict[str, dict[str, object]]:
    """Return the host-only profile catalog without importing Blender or MCP servers."""

    return {
        profile_id: {
            "allowed_tools": list(tools),
            "forbidden_tools": list(_FORBIDDEN_AUTHORITY_TOOLS),
            "network_access": "denied",
            "destination_project_write": False,
            "canonical_write_authority": "supervisor_only",
        }
        for profile_id, tools in _PROFILE_TOOLS.items()
    }


def controller_capability_catalog() -> dict[str, object]:
    """Report adapter availability without claiming repository-side Codex task creation."""

    return {
        "schema_version": "0.1.0",
        "controllers": [
            {
                "controller_kind": "desktop_in_session",
                "status": "available",
                "repository_can_spawn_codex_task": False,
                "sandbox_attestation": "repository_path_validation_only",
            },
            {
                "controller_kind": "fake_for_tests",
                "status": "test_only",
                "repository_can_spawn_codex_task": False,
            },
            {
                "controller_kind": "optional_codex_app_server",
                "status": "unavailable",
                "official_interface_detected": False,
                "repository_can_spawn_codex_task": False,
            },
        ],
        "phase_profiles": phase_tool_profile_catalog(),
        "canonical_write_authority": "supervisor_only",
        "destination_project_write": False,
        "limitations": [
            "repository validation alone cannot attest an external client sandbox",
            "no repository code creates or resumes a Codex task",
        ],
    }


def build_phase_tool_profile(
    *,
    profile_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    source_artifact: ControllerArtifact,
    allowed_input_roles: list[str],
    allowed_output_paths: list[str],
    created_at: datetime,
    supporting_client_enforced: bool = False,
) -> PhaseToolProfile:
    """Build one exact job-bound phase profile from the pure authoritative catalog."""

    catalog = phase_tool_profile_catalog()
    if profile_id not in catalog:
        raise ValueError(f"unknown controller phase tool profile: {profile_id}")
    entry = catalog[profile_id]
    payload = {
        "profile_id": profile_id,
        "source": source_artifact.model_dump(mode="json"),
        "allowed_input_roles": allowed_input_roles,
        "allowed_output_paths": allowed_output_paths,
        "catalog": entry,
    }
    digest = stable_json_digest(payload)
    return PhaseToolProfile(
        contract_id=f"tool-profile-{profile_id}-{session_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(source_artifact.model_dump(mode="json")),
        source_fingerprint=digest,
        producer="codex_blender_modeler.production.controller_executor.profiles",
        provenance=[source_artifact],
        created_at=created_at,
        profile_id=profile_id,
        allowed_tools=list(entry["allowed_tools"]),
        forbidden_tools=list(entry["forbidden_tools"]),
        allowed_input_roles=allowed_input_roles,
        allowed_output_paths=allowed_output_paths,
        sandbox_attestation=(
            "supporting_client_enforced"
            if supporting_client_enforced
            else "repository_path_validation_only"
        ),
    )
