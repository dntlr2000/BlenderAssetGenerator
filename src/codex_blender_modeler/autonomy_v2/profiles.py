"""Parallel AQ v2 profile and delivery-profile registries."""

from __future__ import annotations

from .models import DeliveryProfile

PROFILE_ID = "autonomous_static_prop_v2"
PROFILE_STATUS = "disabled_experimental"
LOCAL_ACTIVATION_SCOPE = "local_desktop_in_session"

_REQUIRED_LOCAL_BLOCKERS = (
    "current-baseline five-outcome One-Prompt campaign evidence is not published",
    "current-baseline portable GLTF production package evidence is not published",
    "exact human local-profile activation acceptance is not published",
    "source-controlled local-profile activation publication is not complete",
)

_EXCLUDED_LOCAL_CAPABILITIES = (
    "codex_imagegen",
    "client_mediated_controller",
    "signage_or_decal",
    "dependency_rich_bake_material",
    "architecture",
    "interior",
    "rig",
    "animation",
)

_FUTURE_LIMITATIONS = (
    "desktop_in_session is workflow-contract-only and is not a sandbox attestation",
    "supporting-client closed-loop and tool-policy attestation are not verified",
    "destination runtime import and material parity are not verified",
)


def autonomy_v2_profile_status() -> dict[str, object]:
    """Expose the disabled base profile with an exact local activation scope."""

    return {
        "profile_id": PROFILE_ID,
        "contract_version": "0.2.0",
        "status": PROFILE_STATUS,
        "underlying_execution_policy": "standard",
        "reference_content_scope": "primary_object_only",
        "activation_scope": LOCAL_ACTIVATION_SCOPE,
        "approval_isolation": "workflow_contract_only",
        "sandbox_attested": False,
        "client_mediated_verified": False,
        "verified_active": False,
        "required_local_blockers": list(_REQUIRED_LOCAL_BLOCKERS),
        "excluded_capabilities": list(_EXCLUDED_LOCAL_CAPABILITIES),
        "future_limitations": list(_FUTURE_LIMITATIONS),
        # Preserve the legacy public key while narrowing it to true local blockers.
        "activation_blockers": list(_REQUIRED_LOCAL_BLOCKERS),
    }


def autonomy_v2_profile_catalog() -> list[dict[str, object]]:
    """Return base AQ v2 plus its separately disabled Codex ImageGen overlay profile."""

    from .codex_image_overlay import codex_image_overlay_profile_status

    return [autonomy_v2_profile_status(), codex_image_overlay_profile_status()]


def delivery_profile(profile_id: str) -> DeliveryProfile:
    """Return one strict public-to-V0.7 delivery mapping without format conversion."""

    if profile_id == "review_only":
        return DeliveryProfile(
            profile_id="review_only",
            asset_profile_id=None,
            primary_extension=None,
            requires_exact_optimization_approval=False,
            requires_clean_import_roundtrip=False,
            limitations=["review evidence is not a production package"],
        )
    if profile_id == "portable_gltf":
        return DeliveryProfile(
            profile_id="portable_gltf",
            asset_profile_id="portable_gltf",
            primary_extension=".glb",
            requires_exact_optimization_approval=True,
            requires_clean_import_roundtrip=True,
            limitations=["destination runtime parity requires a tested adapter"],
        )
    if profile_id == "portable_fbx":
        return DeliveryProfile(
            profile_id="portable_fbx",
            asset_profile_id="fbx_interchange",
            primary_extension=".fbx",
            requires_exact_optimization_approval=True,
            requires_clean_import_roundtrip=True,
            limitations=[
                "FBX material reconstruction is destination-specific",
                "destination runtime parity requires a tested adapter",
            ],
        )
    raise ValueError(f"unknown AQ v2 delivery profile: {profile_id}")


def delivery_profile_catalog() -> list[dict[str, object]]:
    """Return deterministic public delivery profile projections for docs and CLI parity."""

    return [
        delivery_profile(profile_id).model_dump(mode="json")
        for profile_id in ("review_only", "portable_gltf", "portable_fbx")
    ]
