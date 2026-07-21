"""Public V0.7 profile and portable-asset optimization service."""

from __future__ import annotations

import json
from typing import Any

from ..config import load_feature_config
from ..workspace import ensure_job_dirs, job_dir
from .io import latest_complete_run_id, latest_run_id, write_model
from .models import AssetProfile, MeshPreflightReport
from .preflight import load_asset_profile, profile_path, run_asset_preflight
from .profiles import (
    AssetKind,
    CollisionStrategy,
    ConsolidationMode,
    LODMode,
    create_builtin_profile,
)


def initialize_asset_profile(
    job_id: str,
    *,
    profile_id: str = "portable_gltf",
    asset_kind: AssetKind = "static_prop",
    consolidation_mode: ConsolidationMode = "by_semantic_group",
    spatial_cell_size_m: float = 25.0,
    maximum_objects_per_batch: int = 64,
    lod_mode: LODMode = "profile_default",
    collision_strategy: CollisionStrategy = "profile_default",
    max_collider_hulls_per_object: int = 8,
    max_collider_triangles_per_object: int = 256,
    budget_enforcement: str = "warning",
    max_lod0_render_objects: int | None = None,
    max_lod0_material_slots: int | None = None,
    max_lod0_estimated_draw_calls: int | None = None,
    max_lod0_triangles: int | None = None,
    max_collider_triangles: int | None = None,
    max_overlap_candidates: int | None = None,
    overwrite: bool = False,
) -> AssetProfile:
    """Create or load one profile with explicit derived LOD, collider, and cost controls."""

    if not load_feature_config().features.portable_asset_core:
        raise RuntimeError("portable_asset_core is disabled in cbm.toml")
    root = ensure_job_dirs(job_id)
    path = profile_path(root, profile_id)
    if budget_enforcement not in {"warning", "fail"}:
        raise ValueError("budget_enforcement must be warning or fail")
    requested = create_builtin_profile(
        job_id,
        profile_id,
        asset_kind,
        consolidation_mode=consolidation_mode,
        spatial_cell_size_m=spatial_cell_size_m,
        maximum_objects_per_batch=maximum_objects_per_batch,
        lod_mode=lod_mode,
        collision_strategy=collision_strategy,
        max_collider_hulls_per_object=max_collider_hulls_per_object,
        max_collider_triangles_per_object=max_collider_triangles_per_object,
        budget_enforcement=budget_enforcement,  # type: ignore[arg-type]
        max_lod0_render_objects=max_lod0_render_objects,
        max_lod0_material_slots=max_lod0_material_slots,
        max_lod0_estimated_draw_calls=max_lod0_estimated_draw_calls,
        max_lod0_triangles=max_lod0_triangles,
        max_collider_triangles=max_collider_triangles,
        max_overlap_candidates=max_overlap_candidates,
    )
    if path.exists() and not overwrite:
        existing = load_asset_profile(root, profile_id)
        if existing != requested:
            raise FileExistsError(
                f"Asset profile already exists with different settings: {path}; "
                "use explicit overwrite to replace it."
            )
        return existing
    write_model(path, requested)
    return requested


def preflight_asset(
    job_id: str,
    *,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
) -> MeshPreflightReport:
    """Run the read-only topology and portability gate for one initialized profile."""

    return run_asset_preflight(job_id, profile_id, run_id=run_id)


def asset_status(job_id: str) -> dict[str, Any]:
    """Summarize V0.7 profiles, runs, packages, and validations without changing files."""

    root = job_dir(job_id)
    profile_root = root / "asset_profiles"
    run_root = root / "optimization" / "runs"
    package_root = root / "exports" / "packages"
    profiles = sorted(path.stem for path in profile_root.glob("*.json"))
    runs = (
        sorted(path.name for path in run_root.iterdir() if path.is_dir())
        if run_root.is_dir()
        else []
    )
    run_reviews = []
    for run_id in runs:
        directory = run_root / run_id
        plan_path = directory / "optimization_plan.json"
        plan_status = None
        if plan_path.is_file():
            try:
                payload = json.loads(plan_path.read_text(encoding="utf-8"))
                plan_status = payload.get("status") if isinstance(payload, dict) else None
            except (json.JSONDecodeError, OSError):
                plan_status = "invalid"
        run_reviews.append(
            {
                "run_id": run_id,
                "plan_status": plan_status,
                "review_available": (directory / "optimization_review.json").is_file(),
                "approval_available": (directory / "optimization_approval.json").is_file(),
            }
        )
    packages = (
        sorted(
            path.relative_to(package_root).as_posix()
            for path in package_root.rglob("package_manifest.json")
        )
        if package_root.is_dir()
        else []
    )
    return {
        "schema_version": "0.7.0",
        "job_id": job_id,
        "profiles": profiles,
        "latest_run_id": latest_run_id(root),
        "latest_complete_run_id": latest_complete_run_id(root),
        "runs": runs,
        "run_reviews": run_reviews,
        "package_manifests": packages,
    }
