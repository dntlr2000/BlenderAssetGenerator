"""Parallel AQ v2 profile and delivery-profile registries."""

from __future__ import annotations

from .models import DeliveryProfile

PROFILE_ID = "autonomous_static_prop_v2"
PROFILE_STATUS = "disabled_experimental"


def autonomy_v2_profile_status() -> dict[str, object]:
    """Expose v2 as disabled until every required real gate has passed."""

    return {
        "profile_id": PROFILE_ID,
        "contract_version": "0.2.0",
        "status": PROFILE_STATUS,
        "underlying_execution_policy": "standard",
        "reference_content_scope": "primary_object_only",
        "verified_active": False,
        "activation_blockers": [
            "Codex Desktop or App Server supporting-client closed loop is not verified",
            "controller phase sandbox and tool-policy attestation is not verified",
            "real-reference quality benchmark has no human review evidence",
            "destination runtime import and material parity is not verified",
        ],
    }


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
