"""Verified autonomy profile registry and context-bound snapshot construction."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from .models import (
    AutonomyArtifact,
    AutonomyBudget,
    AutonomyProfile,
    PolicyGateKind,
)

ACTIVE_PROFILE_ID = "autonomous_static_prop_v1"
FUTURE_PROFILE_IDS = (
    "autonomous_environment_v1",
    "autonomous_architecture_v1",
    "autonomous_measured_asset_v1",
)

ALLOWED_ROUTINE_GATES: tuple[PolicyGateKind, ...] = (
    "generic_proxy_review",
    "generic_detail_review",
    "material_swatch_acknowledgement",
    "structural_candidate_promotion",
    "bounded_convergence_plan",
    "bounded_convergence_candidate",
    "material_candidate_promotion",
    "qa_review_acknowledgement",
    "optimization_plan",
    "final_package_acknowledgement",
    "destination_handoff_envelope_plan",
)

PROHIBITED_CAPABILITIES = (
    "interior",
    "interior_qa",
    "measured_or_blueprint",
    "rig",
    "skinning",
    "animation",
    "gameplay",
    "engine_specific_prefab_or_actor",
    "destination_project_write",
    "external_network_provider",
    "arbitrary_blender_python",
    "arbitrary_node_graph",
    "cad_brep_support_claim",
    "budget_expansion",
    "reference_content_scope_change",
    "target_subject_change",
    "primary_reference_replacement",
)


def _digest(value: object) -> str:
    """Hash deterministic JSON for immutable profile input binding."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def profile_registry() -> list[dict[str, object]]:
    """Return the one verified profile and explicitly disabled future profiles."""

    return [
        {
            "profile_id": ACTIVE_PROFILE_ID,
            "status": "verified_active",
            "underlying_execution_policy": "standard",
            "reference_content_scope": "primary_object_only",
            "output_profile": "portable_gltf",
        },
        *[
            {
                "profile_id": profile_id,
                "status": "disabled_experimental",
                "underlying_execution_policy": "standard",
            }
            for profile_id in FUTURE_PROFILE_IDS
        ],
    ]


def list_autonomy_profiles() -> list[dict[str, object]]:
    """Expose immutable registry projections without enabling experimental profiles."""

    return profile_registry()


def get_autonomy_profile_status(profile_id: str | None = None) -> dict[str, object]:
    """Return one exact profile status or the complete conservative registry."""

    profiles = profile_registry()
    if profile_id is None:
        return {
            "contract_version": "0.1.0",
            "active_profile_id": ACTIVE_PROFILE_ID,
            "profiles": profiles,
        }
    matches = [item for item in profiles if item["profile_id"] == profile_id]
    if not matches:
        raise ValueError(f"unknown autonomy profile: {profile_id}")
    return {
        "contract_version": "0.1.0",
        "active_profile_id": ACTIVE_PROFILE_ID,
        "profile": matches[0],
    }


def build_default_budget(
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    source_artifact: AutonomyArtifact,
    created_at: datetime | None = None,
) -> AutonomyBudget:
    """Create the immutable default budget within every published hard cap."""

    now = created_at or datetime.now(UTC)
    source = source_artifact.model_dump(mode="json")
    return AutonomyBudget(
        budget_id=f"budget-{dispatch_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=_digest(source),
        source_fingerprint=_digest({"source": source, "profile": ACTIVE_PROFILE_ID}),
        provenance=[source_artifact],
        created_at=now,
    )


def build_profile_snapshot(
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    budget: AutonomyBudget,
    budget_artifact: AutonomyArtifact,
    quality_gate_profile: AutonomyArtifact,
    created_at: datetime | None = None,
) -> AutonomyProfile:
    """Create a job-bound snapshot of the sole verified autonomy profile."""

    now = created_at or datetime.now(UTC)
    input_payload = {
        "profile_id": ACTIVE_PROFILE_ID,
        "budget_sha256": budget_artifact.sha256,
        "quality_gate_profile_sha256": quality_gate_profile.sha256,
    }
    return AutonomyProfile(
        contract_id=f"profile-{dispatch_id}",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=_digest(input_payload),
        source_fingerprint=_digest(
            {**input_payload, "allowed_gates": ALLOWED_ROUTINE_GATES}
        ),
        producer="codex_blender_modeler.autonomy.profiles",
        producer_version="0.1.0",
        provenance=[budget_artifact, quality_gate_profile],
        created_at=now,
        profile_id=ACTIVE_PROFILE_ID,
        status="verified_active",
        allowed_asset_kinds=["static_hard_surface", "static_prop"],
        allowed_gate_kinds=list(ALLOWED_ROUTINE_GATES),
        prohibited_capabilities=list(PROHIBITED_CAPABILITIES),
        default_budget=budget,
        quality_gate_profile=quality_gate_profile,
    )
