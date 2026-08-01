"""Built-in engine-neutral static-asset profile definitions."""

from __future__ import annotations

from typing import Literal

from .models import (
    AssetProfile,
    CollisionPolicy,
    ConsolidationPolicy,
    CostBudgetPolicy,
    LODPolicy,
    TexturePolicy,
    UVPolicy,
)

AssetKind = Literal["static_prop", "static_environment", "static_architecture"]
ConsolidationMode = Literal["none", "by_semantic_group", "by_spatial_cell"]
LODMode = Literal["profile_default", "enabled", "disabled"]
PivotPolicy = Literal["keep", "bounds_center", "base_center"]
CollisionStrategy = Literal[
    "profile_default",
    "none",
    "box",
    "sphere",
    "capsule",
    "convex_hull",
    "compound",
    "mesh_proxy",
]


def create_builtin_profile(
    job_id: str,
    profile_id: str,
    asset_kind: AssetKind,
    *,
    consolidation_mode: ConsolidationMode = "by_semantic_group",
    spatial_cell_size_m: float = 25.0,
    maximum_objects_per_batch: int = 64,
    lod_mode: LODMode = "profile_default",
    generate_uv1: bool | None = None,
    pivot_policy: PivotPolicy = "keep",
    collision_strategy: CollisionStrategy = "profile_default",
    max_collider_hulls_per_object: int = 8,
    max_collider_triangles_per_object: int = 256,
    budget_enforcement: Literal["warning", "fail"] = "warning",
    max_lod0_render_objects: int | None = None,
    max_lod0_material_slots: int | None = None,
    max_lod0_estimated_draw_calls: int | None = None,
    max_lod0_triangles: int | None = None,
    max_collider_triangles: int | None = None,
    max_overlap_candidates: int | None = None,
) -> AssetProfile:
    """Create one portable profile with reviewable LOD, collider, and cost controls."""

    consolidation = ConsolidationPolicy(
        mode=consolidation_mode,
        spatial_cell_size_m=spatial_cell_size_m,
        maximum_objects_per_batch=maximum_objects_per_batch,
    )
    budgets = CostBudgetPolicy(
        enforcement=budget_enforcement,
        max_lod0_render_objects=max_lod0_render_objects,
        max_lod0_material_slots=max_lod0_material_slots,
        max_lod0_estimated_draw_calls=max_lod0_estimated_draw_calls,
        max_lod0_triangles=max_lod0_triangles,
        max_collider_triangles=max_collider_triangles,
        max_overlap_candidates=max_overlap_candidates,
    )
    default_lod_enabled = profile_id != "obj_legacy"
    lod_enabled = (
        default_lod_enabled if lod_mode == "profile_default" else lod_mode == "enabled"
    )
    lod = (
        LODPolicy()
        if lod_enabled
        else LODPolicy(enabled=False, targets=[])
    )
    default_collision = "none" if profile_id == "obj_legacy" else "compound"
    selected_collision = (
        default_collision
        if collision_strategy == "profile_default"
        else collision_strategy
    )
    collision = CollisionPolicy(
        strategy=selected_collision,  # type: ignore[arg-type]
        max_hulls_per_object=max_collider_hulls_per_object,
        max_triangles_per_object=max_collider_triangles_per_object,
    )
    default_generate_uv1 = profile_id != "obj_legacy"
    selected_generate_uv1 = (
        default_generate_uv1 if generate_uv1 is None else generate_uv1
    )

    if profile_id == "portable_gltf":
        return AssetProfile(
            profile_id="portable_gltf",
            job_id=job_id,
            asset_kind=asset_kind,
            primary_format="glb",
            up_axis="+Y",
            forward_axis="-Z",
            pivot_policy=pivot_policy,
            lod=lod,
            collision=collision,
            uv=UVPolicy(
                generate_uv0_if_missing=True,
                generate_uv1=selected_generate_uv1,
            ),
            textures=TexturePolicy(packing="gltf_orm"),
            consolidation=consolidation,
            budgets=budgets,
            notes=[
                "Engine-neutral glTF 2.0 metallic-roughness package.",
                "LOD and collision artifacts remain separate from the canonical Blender scene.",
                "V0.7.3 batches only equal semantic/material families and retains provenance.",
            ],
        )
    if profile_id == "fbx_interchange":
        return AssetProfile(
            profile_id="fbx_interchange",
            job_id=job_id,
            asset_kind=asset_kind,
            primary_format="fbx",
            up_axis="+Y",
            forward_axis="-Z",
            pivot_policy=pivot_policy,
            lod=lod,
            collision=collision,
            uv=UVPolicy(
                generate_uv0_if_missing=True,
                generate_uv1=selected_generate_uv1,
            ),
            textures=TexturePolicy(packing="raw_channels"),
            consolidation=consolidation,
            budgets=budgets,
            notes=[
                "Engine-neutral FBX interchange package with raw PBR sidecar channels.",
                "Importer-specific material reconstruction is intentionally deferred.",
                "V0.7.3 batching does not imply destination-engine static batching.",
            ],
        )
    if profile_id == "obj_legacy":
        return AssetProfile(
            profile_id="obj_legacy",
            job_id=job_id,
            asset_kind=asset_kind,
            primary_format="obj",
            up_axis="+Y",
            forward_axis="-Z",
            pivot_policy=pivot_policy,
            lod=lod,
            collision=collision,
            uv=UVPolicy(
                generate_uv0_if_missing=True,
                generate_uv1=selected_generate_uv1,
            ),
            textures=TexturePolicy(packing="raw_channels"),
            consolidation=consolidation,
            budgets=budgets,
            notes=[
                "Legacy geometry interchange profile; semantic metadata loss is expected.",
                "OBJ packages are not the preferred portable delivery format.",
                "V0.7.3 semantic batching remains limited by OBJ metadata loss.",
            ],
        )
    raise ValueError("profile_id must be portable_gltf, fbx_interchange, or obj_legacy")
