"""Deterministic material-change impact and approval-boundary policy."""

from __future__ import annotations

from collections.abc import Mapping

from .models import ApprovalImpact, MaterialChange

NO_VISUAL_CHANGE_CATEGORIES = frozenset(
    {
        "path_only_rebinding",
        "hash_map_reconstruction",
        "manifest_ordering",
        "closure_collection",
        "deterministic_serialization",
        "receipt_regeneration",
    }
)
APPEARANCE_CHANGE_CATEGORIES = frozenset(
    {
        "base_color",
        "roughness_metallic",
        "normal_height",
        "texture_bytes",
        "uv_placement",
        "shader_parameter",
        "material_assignment",
    }
)
SCOPE_CHANGE_CATEGORIES = frozenset(
    {
        "new_object_material",
        "reference_replacement",
        "target_subject",
        "content_scope",
        "imagegen_scope_expansion",
    }
)


def classify_material_changes(changes: list[MaterialChange]) -> ApprovalImpact:
    """Return the highest-authority impact across a non-empty exact change list."""

    if not changes:
        raise ValueError("material impact classification requires at least one change")
    categories = {item.category for item in changes}
    if categories & SCOPE_CHANGE_CATEGORIES:
        return "scope_change"
    if categories & APPEARANCE_CHANGE_CATEGORIES:
        return "appearance_change"
    if not categories.issubset(NO_VISUAL_CHANGE_CATEGORIES):
        raise ValueError("material change category has no approval policy")
    return "no_visual_change"


def approval_requirement_for_impact(
    impact: ApprovalImpact,
) -> tuple[bool, str]:
    """Map one impact class to its sole permitted user-approval boundary."""

    return {
        "no_visual_change": (False, "none"),
        "appearance_change": (True, "material_appearance_promotion"),
        "scope_change": (True, "root_scope"),
    }[impact]


def material_approval_is_current(
    approval_bindings: Mapping[str, str],
    current_bindings: Mapping[str, str],
) -> bool:
    """Keep an approval current only when every exact bound hash remains identical."""

    required = {
        "candidate_material_plan_sha256",
        "rebound_material_graph_sha256",
        "closure_sha256",
        "preflight_report_sha256",
        "neutral_preview_sha256",
        "canonical_scene_spec_sha256",
        "canonical_blend_sha256",
        "uv_layout_fingerprint",
    }
    return (
        set(approval_bindings) == required
        and set(current_bindings) == required
        and dict(approval_bindings) == dict(current_bindings)
    )


__all__ = [
    "APPEARANCE_CHANGE_CATEGORIES",
    "NO_VISUAL_CHANGE_CATEGORIES",
    "SCOPE_CHANGE_CATEGORIES",
    "approval_requirement_for_impact",
    "classify_material_changes",
    "material_approval_is_current",
]

