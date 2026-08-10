"""Immutable severity maps for the six supported topology profiles."""

from __future__ import annotations

from .models import TopologyCheckName, TopologyCheckPolicy, TopologyProfile, TopologyProfileName

PROFILE_NAMES: tuple[TopologyProfileName, ...] = (
    "static_prop_closed",
    "static_prop_open",
    "game_ready_lowpoly",
    "highpoly_bake_source",
    "modular_architecture",
    "terrain",
)

_CHECKS: tuple[TopologyCheckName, ...] = (
    "non_finite",
    "degenerate_face",
    "self_intersection",
    "winding",
    "flipped_normal",
    "loose_geometry",
    "open_boundary",
    "triangle_aspect",
    "ngon_limit",
    "uv0",
    "uv_overlap",
    "island_padding",
    "texel_density",
    "tangent",
    "subdivision_pinching",
    "lod_silhouette_error",
    "clean_import_normal_preservation",
    "clean_import_material_preservation",
)

_COMMON_HARD: frozenset[TopologyCheckName] = frozenset(
    {
        "non_finite",
        "degenerate_face",
        "self_intersection",
        "winding",
        "flipped_normal",
        "uv0",
        "tangent",
        "clean_import_normal_preservation",
        "clean_import_material_preservation",
    }
)

_PROFILE_HARD: dict[TopologyProfileName, frozenset[TopologyCheckName]] = {
    "static_prop_closed": _COMMON_HARD | {"loose_geometry", "open_boundary"},
    "static_prop_open": _COMMON_HARD | {"loose_geometry"},
    "game_ready_lowpoly": _COMMON_HARD
    | {
        "loose_geometry",
        "open_boundary",
        "uv_overlap",
        "island_padding",
        "texel_density",
        "ngon_limit",
        "lod_silhouette_error",
    },
    "highpoly_bake_source": _COMMON_HARD
    | {"loose_geometry", "subdivision_pinching"},
    "modular_architecture": _COMMON_HARD
    | {
        "loose_geometry",
        "uv_overlap",
        "island_padding",
        "texel_density",
        "ngon_limit",
    },
    "terrain": _COMMON_HARD
    | {"loose_geometry", "uv_overlap", "texel_density", "lod_silhouette_error"},
}


def get_topology_profile(name: TopologyProfileName) -> TopologyProfile:
    """Return one fresh immutable topology profile with all checks classified."""

    hard = _PROFILE_HARD[name]
    return TopologyProfile(
        name=name,
        checks=[
            TopologyCheckPolicy(
                check=check,
                failure_severity="hard_failure" if check in hard else "warning",
                rationale=(
                    f"{check} is a hard acceptance requirement for {name}."
                    if check in hard
                    else f"{check} is review evidence for {name}."
                ),
            )
            for check in _CHECKS
        ],
    )
