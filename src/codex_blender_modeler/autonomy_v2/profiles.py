"""Parallel AQ v2 profile and delivery-profile registries."""

from __future__ import annotations

from pathlib import Path

from ..activation_profile_publication import (
    EXCLUDED_LOCAL_CAPABILITIES,
    FUTURE_LOCAL_LIMITATIONS,
    LOCAL_PROFILE_PUBLICATION_RELATIVE_PATH,
    load_local_profile_activation_publication,
    local_profile_publication_is_head_tracked,
    local_profile_publication_path,
)
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

def autonomy_v2_profile_status(root: Path | None = None) -> dict[str, object]:
    """Expose only a committed exact publication as the active local AQ profile."""

    repository = root.expanduser().resolve() if root is not None else None
    publication = None
    publication_state = "absent"
    publication_error = None
    try:
        publication = load_local_profile_activation_publication(
            repository,
            require_head_tracked=False,
        )
        publication_root = (
            repository
            if repository is not None
            else local_profile_publication_path().parents[2]
        )
        publication_state = (
            "verified_active"
            if local_profile_publication_is_head_tracked(publication_root)
            else "pending_source_commit"
        )
    except FileNotFoundError:
        publication = None
    except (OSError, PermissionError, ValueError) as exc:
        publication_state = "invalid"
        publication_error = str(exc)[:1000]

    active = publication is not None and publication_state == "verified_active"
    required_blockers = [] if active else list(_REQUIRED_LOCAL_BLOCKERS)
    if publication_state == "pending_source_commit":
        required_blockers = [
            "source-controlled local-profile activation publication is not committed"
        ]
    elif publication_state == "invalid":
        required_blockers = [
            "source-controlled local-profile activation publication is invalid"
        ]
    result: dict[str, object] = {
        "profile_id": PROFILE_ID,
        "contract_version": "0.2.0",
        "status": "verified_active" if active else PROFILE_STATUS,
        "underlying_execution_policy": "standard",
        "reference_content_scope": "primary_object_only",
        "activation_scope": LOCAL_ACTIVATION_SCOPE,
        "approval_isolation": "workflow_contract_only",
        "sandbox_attested": False,
        "client_mediated_verified": False,
        "verified_active": active,
        "publication_state": publication_state,
        "publication_path": LOCAL_PROFILE_PUBLICATION_RELATIVE_PATH,
        "required_local_blockers": required_blockers,
        "excluded_capabilities": list(EXCLUDED_LOCAL_CAPABILITIES),
        "future_limitations": list(FUTURE_LOCAL_LIMITATIONS),
        # Preserve the legacy public key while narrowing it to true local blockers.
        "activation_blockers": required_blockers,
    }
    if publication_error is not None:
        result["publication_error"] = publication_error
    if active and publication is not None:
        result.update(
            {
                "publication_id": publication.publication_id,
                "publication_sha256": publication.publication_sha256,
                "activation_evidence": [
                    item.model_dump(mode="json")
                    for item in publication.activation_evidence
                ],
                "source_git_commit_sha": publication.source_git_commit_sha,
                "source_git_tree_sha": publication.source_git_tree_sha,
                "distinct_primary_reference_sha256s": (
                    publication.distinct_primary_reference_sha256s
                ),
                "production_package_count": publication.production_package_count,
            }
        )
    return result


def autonomy_v2_profile_catalog(root: Path | None = None) -> list[dict[str, object]]:
    """Return base AQ v2 plus its separately disabled Codex ImageGen overlay profile."""

    from .codex_image_overlay import codex_image_overlay_profile_status

    return [autonomy_v2_profile_status(root), codex_image_overlay_profile_status()]


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
