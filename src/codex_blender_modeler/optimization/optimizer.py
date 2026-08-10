"""Derived Blender optimization and manifest normalization for V0.7."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_runner import run_blender
from ..config import load_feature_config
from ..workspace import job_dir, sha256_file
from .io import (
    job_relative,
    latest_complete_run_id,
    load_model,
    new_run_id,
    resolve_inside,
    run_directory,
    utc_now,
    write_latest_run,
    write_model,
)
from .models import (
    AssetCostReduction,
    AssetCostSnapshot,
    AssetProfile,
    Bounds3D,
    CollisionEntry,
    CollisionManifest,
    CollisionOptimizationReview,
    ConsolidationBatch,
    CostBudgetResult,
    ExactInstanceGroup,
    HashedArtifact,
    LODEntry,
    LODLevelReview,
    LODManifest,
    LODOptimizationReview,
    MeshCleanupRecord,
    MeshOverlapFinding,
    MeshPreflightReport,
    MeshSummary,
    OptimizationApproval,
    OptimizationDirective,
    OptimizationPlan,
    OptimizationReview,
    SourceProvenance,
    SourceQualitySummary,
    StaticAssetCostReport,
    UVManifest,
    UVSetRecord,
)
from .preflight import (
    NON_RENDER_BOOLEAN_TAG,
    load_asset_profile,
    profile_artifact,
    run_asset_preflight,
)
from .provenance import collect_source_provenance, require_unchanged_source


def _bounds(records: list[dict[str, Any]]) -> Bounds3D:
    """Aggregate finite Blender world bounds for one semantic object family."""

    if not records:
        raise ValueError("Cannot calculate bounds for an empty object group")
    minima = [record["bbox_world"]["min"] for record in records]
    maxima = [record["bbox_world"]["max"] for record in records]
    return Bounds3D(
        minimum=tuple(min(float(value[axis]) for value in minima) for axis in range(3)),
        maximum=tuple(max(float(value[axis]) for value in maxima) for axis in range(3)),
    )


def _role_level(record: dict[str, Any]) -> int | None:
    """Normalize Blender render and LOD roles into the manifest level number."""

    role = str(record.get("asset_role") or "")
    if role == "render":
        return 0
    if role == "lod":
        return int(record.get("lod_level"))
    return None


def _artifact_for_derived_blend(
    root: Path,
    blend: Path,
    artifact_id: str,
    kind: str,
) -> HashedArtifact:
    """Reference one mesh embedded in the immutable run-owned optimized blend."""

    return HashedArtifact(
        id=artifact_id,
        kind=kind,
        path=job_relative(root, blend),
        sha256=sha256_file(blend),
    )


def _maximum_lod_triangle_count(source_triangles: int, target_ratio: float) -> int:
    """Round one profile ratio upward into a whole-triangle budget ceiling."""

    if source_triangles < 0:
        raise ValueError("Source triangle count cannot be negative")
    if not 0.0 < target_ratio < 1.0:
        raise ValueError("Derived LOD target ratio must be between zero and one")
    if source_triangles == 0:
        return 0
    return max(1, math.ceil(source_triangles * target_ratio))


def _maximum_lod_counts(
    profile: AssetProfile,
    source_triangle_counts: list[int],
) -> dict[int, int]:
    """Aggregate per-instance whole-triangle ceilings for one semantic family."""

    source_triangles = sum(source_triangle_counts)
    expected = {0: source_triangles}
    if profile.lod.enabled:
        expected.update(
            {
                target.level: sum(
                    _maximum_lod_triangle_count(
                        triangle_count,
                        target.target_triangle_ratio,
                    )
                    for triangle_count in source_triangle_counts
                )
                for target in profile.lod.targets
            }
        )
    return expected


def _source_triangle_counts(
    raw: dict[str, Any], target_id: str, fallback_records: list[dict[str, Any]]
) -> list[int]:
    """Recover per-source LOD0 counts so batching cannot tighten rounded LOD budgets."""

    counts = [
        int(action["lod_triangle_counts"]["0"])
        for action in raw.get("actions", [])
        if isinstance(action, dict)
        and str(action.get("semantic_id")) == target_id
        and isinstance(action.get("lod_triangle_counts"), dict)
        and "0" in action["lod_triangle_counts"]
    ]
    if counts:
        return counts
    return [
        int(record.get("topology", {}).get("triangles_estimated", 0))
        for record in fallback_records
    ]


def _lod_manifest(
    root: Path,
    run_id: str,
    profile: AssetProfile,
    source: Any,
    raw: dict[str, Any],
    optimized_blend: Path,
) -> LODManifest:
    """Normalize embedded derived LOD objects into stable semantic-family entries."""

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in raw.get("objects", []):
        if not isinstance(record, dict) or record.get("type") != "MESH":
            continue
        level = _role_level(record)
        if level is None:
            continue
        target_id = str(record.get("semantic_id") or "")
        if not target_id:
            raise ValueError("Derived LOD object is missing its semantic ID")
        grouped[(target_id, level)].append(record)

    entries: list[LODEntry] = []
    if not grouped:
        raise RuntimeError("Optimized Blender evidence contains no render or LOD meshes")
    for target_id in sorted({key[0] for key in grouped}):
        source_records = grouped.get((target_id, 0), [])
        if not source_records:
            raise RuntimeError(f"Derived LOD family has no LOD0 source: {target_id}")
        source_triangle_counts = _source_triangle_counts(raw, target_id, source_records)
        source_triangles = sum(source_triangle_counts)
        grouped_source_triangles = sum(
            int(record.get("topology", {}).get("triangles_estimated", 0))
            for record in source_records
        )
        if grouped_source_triangles != source_triangles:
            raise RuntimeError(
                f"Semantic batching changed LOD0 triangles for {target_id}: "
                f"{grouped_source_triangles} != {source_triangles}"
            )
        maximum_counts = _maximum_lod_counts(profile, source_triangle_counts)
        actual_levels = sorted(level for family, level in grouped if family == target_id)
        expected_levels = sorted(maximum_counts)
        if actual_levels != expected_levels:
            raise RuntimeError(
                f"Derived LOD levels differ from AssetProfile for {target_id}: "
                f"actual={actual_levels}, expected={expected_levels}"
            )
        for _, level in sorted(key for key in grouped if key[0] == target_id):
            records = grouped[(target_id, level)]
            triangles = sum(
                int(record.get("topology", {}).get("triangles_estimated", 0))
                for record in records
            )
            maximum_triangles = maximum_counts[level]
            if triangles > maximum_triangles:
                target = next(
                    (item for item in profile.lod.targets if item.level == level),
                    None,
                )
                ratio_label = (
                    "1.0" if level == 0 else str(target.target_triangle_ratio)
                )
                raise RuntimeError(
                    f"LOD{level} triangle count for {target_id} violates AssetProfile "
                    f"target ratio {ratio_label}: actual={triangles}, "
                    f"maximum={maximum_triangles}"
                )
            ratio = triangles / source_triangles if source_triangles else 0.0
            materials = sorted(
                {
                    str(material_id)
                    for record in records
                    for material_id in record.get("material_ids", [])
                }
            )
            entries.append(
                LODEntry(
                    target_id=target_id,
                    level=level,
                    mesh=_artifact_for_derived_blend(
                        root,
                        optimized_blend,
                        f"lod.{target_id}.{level}",
                        "lod_mesh",
                    ),
                    source_triangle_count=source_triangles,
                    triangle_count=triangles,
                    triangle_ratio=1.0 if level == 0 else min(1.0, ratio),
                    silhouette_iou=None,
                    bounds=_bounds(records),
                    material_ids=materials,
                )
            )
    now = utc_now()
    return LODManifest(
        manifest_id=f"lod.{run_id}",
        job_id=profile.job_id,
        run_id=run_id,
        profile_id=profile.profile_id,
        source=source,
        status="complete",
        quality_status="partially_verified",
        unverified_checks=["silhouette_iou"],
        entries=entries,
        created_at=now,
        completed_at=now,
        notes=[
            "LOD0 is an evaluated copy in the run-owned optimized blend.",
            "Silhouette IoU is unverified for every LOD, including the evaluated LOD0 copy.",
            "Derived triangle counts do not exceed profile ratio budgets after "
            "deterministic per-instance whole-triangle ceiling.",
        ],
    )


def _collision_strategy(value: str) -> str:
    """Map compound colliders to their per-entry primitive representation."""

    normalized = value.lower()
    if normalized == "compound":
        return "box"
    if normalized == "convex":
        return "convex_hull"
    if normalized == "mesh":
        return "mesh_proxy"
    return normalized


def _collision_manifest(
    root: Path,
    run_id: str,
    profile: AssetProfile,
    source: Any,
    raw: dict[str, Any],
    optimized_blend: Path,
) -> CollisionManifest:
    """Normalize derived collider objects while retaining their semantic ownership."""

    entries: list[CollisionEntry] = []
    counters: dict[str, int] = defaultdict(int)
    for record in raw.get("objects", []):
        if not isinstance(record, dict) or record.get("asset_role") != "collider":
            continue
        target_id = str(record.get("semantic_id") or "")
        if not target_id:
            raise ValueError("Derived collider is missing its semantic owner")
        counters[target_id] += 1
        strategy = _collision_strategy(str(record.get("collider_strategy") or "box"))
        triangle_count = int(
            record.get("topology", {}).get("triangles_estimated", 0)
        )
        if triangle_count > profile.collision.max_triangles_per_object:
            raise RuntimeError(
                f"Collider for {target_id} exceeds profile triangle budget: "
                f"{triangle_count} > {profile.collision.max_triangles_per_object}"
            )
        mesh = None
        if strategy in {"convex_hull", "mesh_proxy"}:
            mesh = _artifact_for_derived_blend(
                root,
                optimized_blend,
                f"collider.mesh.{target_id}.{counters[target_id]}",
                "collider_mesh",
            )
        rotation = tuple(
            math.degrees(float(value)) for value in record.get("rotation_euler", [0, 0, 0])
        )
        entries.append(
            CollisionEntry(
                collider_id=f"collider.{target_id}.{counters[target_id]}",
                target_id=target_id,
                strategy=strategy,  # type: ignore[arg-type]
                location=tuple(float(value) for value in record.get("location", [0, 0, 0])),
                rotation_deg=rotation,
                dimensions=tuple(float(value) for value in record["dimensions"]),
                mesh=mesh,
                triangle_count=triangle_count,
            )
        )
    now = utc_now()
    return CollisionManifest(
        manifest_id=f"collision.{run_id}",
        job_id=profile.job_id,
        run_id=run_id,
        profile_id=profile.profile_id,
        source=source,
        strategy=profile.collision.strategy,
        status="complete",
        entries=entries,
        created_at=now,
        completed_at=now,
        notes=[
            "Collision proxies are derived and never replace render geometry.",
            "The compound strategy is represented as one box entry per exported semantic "
            "object instance in this V0.7 core.",
        ],
    )


def _uv_generated(raw: dict[str, Any], target_id: str, uv_set: str) -> bool:
    """Infer whether the preparation action created rather than preserved one UV set."""

    for action in raw.get("actions", []):
        if not isinstance(action, dict) or str(action.get("semantic_id")) != target_id:
            continue
        for value in action.get("uv", []):
            text = str(value)
            if uv_set in text and "preserved" not in text:
                return True
    return False


def _uv_manifest(
    run_id: str,
    profile: AssetProfile,
    source: Any,
    raw: dict[str, Any],
) -> UVManifest:
    """Normalize measured Blender UV layer presence without fabricating overlap scores."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in raw.get("objects", []):
        if not isinstance(record, dict) or record.get("asset_role") != "render":
            continue
        target_id = str(record.get("semantic_id") or "")
        for layer in record.get("topology", {}).get("uv_layers", []):
            if isinstance(layer, dict):
                grouped[(target_id, str(layer.get("name") or "UVMap"))].append(layer)
    records = [
        UVSetRecord(
            target_id=target_id,
            uv_set=uv_set,
            purpose="lightmap" if uv_set.lower().startswith("lightmap") else "material",
            generated=_uv_generated(raw, target_id, uv_set),
            overlap_fraction=None,
            degenerate_face_count=sum(
                int(layer.get("degenerate_face_count", 0)) for layer in layers
            ),
            texel_density_px_m=None,
            padding_px=(
                profile.uv.minimum_padding_px
                if uv_set.lower().startswith("lightmap")
                else None
            ),
        )
        for (target_id, uv_set), layers in sorted(grouped.items())
    ]
    now = utc_now()
    return UVManifest(
        manifest_id=f"uv.{run_id}",
        job_id=profile.job_id,
        run_id=run_id,
        profile_id=profile.profile_id,
        source=source,
        uv_required=True,
        status="complete",
        quality_status="partially_verified",
        unverified_checks=["overlap_fraction", "texel_density"],
        records=records,
        created_at=now,
        completed_at=now,
        notes=[
            "UV overlap is unavailable in this core pass and is represented as null.",
            (
                "The profile requests texel density "
                f"{profile.uv.target_texel_density_px_m} px/m; measured density is "
                "unavailable until a bound texture resolution exists."
                if profile.uv.target_texel_density_px_m is not None
                else "No explicit texel-density target was requested by the profile."
            ),
            "UV records describe the run-owned optimized scene, not canonical authoring meshes.",
        ],
    )


def _cost_reductions(
    before: AssetCostSnapshot, after: AssetCostSnapshot
) -> list[AssetCostReduction]:
    """Calculate exact cost deltas for the bounded V0.7.3 proxy metric set."""

    metrics = (
        "lod0_render_objects",
        "lod0_material_slots",
        "lod0_estimated_draw_calls",
        "lod0_vertices",
        "lod0_triangles",
        "lod_objects",
        "collider_objects",
        "collider_triangles",
        "total_derived_triangles",
        "overlap_candidates",
    )
    reductions: list[AssetCostReduction] = []
    for metric in metrics:
        before_value = int(getattr(before, metric))
        after_value = int(getattr(after, metric))
        reduction = before_value - after_value
        reductions.append(
            AssetCostReduction(
                metric=metric,  # type: ignore[arg-type]
                before=before_value,
                after=after_value,
                reduction=reduction,
                reduction_fraction=(reduction / before_value if before_value else 0.0),
            )
        )
    return reductions


def _budget_results(
    profile: AssetProfile, after: AssetCostSnapshot
) -> list[CostBudgetResult]:
    """Evaluate only explicitly configured engine-neutral cost ceilings."""

    configured = (
        ("lod0_render_objects", profile.budgets.max_lod0_render_objects),
        ("lod0_material_slots", profile.budgets.max_lod0_material_slots),
        (
            "lod0_estimated_draw_calls",
            profile.budgets.max_lod0_estimated_draw_calls,
        ),
        ("lod0_triangles", profile.budgets.max_lod0_triangles),
        ("collider_triangles", profile.budgets.max_collider_triangles),
        ("overlap_candidates", profile.budgets.max_overlap_candidates),
    )
    results: list[CostBudgetResult] = []
    for metric, maximum in configured:
        if maximum is None:
            continue
        actual = int(getattr(after, metric))
        exceeded = actual > maximum
        status = (
            ("failed" if profile.budgets.enforcement == "fail" else "warning")
            if exceeded
            else "passed"
        )
        results.append(
            CostBudgetResult(
                metric=metric,  # type: ignore[arg-type]
                actual=actual,
                maximum=maximum,
                status=status,
                message=(
                    f"{metric} exceeded {actual} > {maximum}"
                    if exceeded
                    else f"{metric} passed {actual} <= {maximum}"
                ),
            )
        )
    return results


def _asset_cost_report(
    run_id: str,
    profile: AssetProfile,
    source: Any,
    raw: dict[str, Any],
) -> StaticAssetCostReport:
    """Normalize Blender V0.7.3 cost evidence into one strict immutable report."""

    evidence = raw.get("cost_optimization")
    if not isinstance(evidence, dict):
        raise RuntimeError("Optimized Blender evidence has no V0.7.3 cost section")
    before = AssetCostSnapshot.model_validate(evidence.get("before"))
    after = AssetCostSnapshot.model_validate(evidence.get("after"))
    budgets = _budget_results(profile, after)
    ok = not any(item.status == "failed" for item in budgets)
    notes = [str(value) for value in evidence.get("limitations", [])]
    if evidence.get("overlap_before_truncated"):
        notes.append("Before-cleanup overlap finding details were truncated by policy.")
    if evidence.get("overlap_after_truncated"):
        notes.append("After-cleanup overlap finding details were truncated by policy.")
    return StaticAssetCostReport(
        report_id=f"cost.{run_id}",
        job_id=profile.job_id,
        run_id=run_id,
        profile_id=profile.profile_id,
        source=source,
        status="passed" if ok else "failed",
        ok=ok,
        before=before,
        after=after,
        reductions=_cost_reductions(before, after),
        budgets=budgets,
        consolidation_batches=[
            ConsolidationBatch.model_validate(value)
            for value in evidence.get("consolidation_batches", [])
        ],
        cleanup_records=[
            MeshCleanupRecord.model_validate(value)
            for value in evidence.get("cleanup_records", [])
        ],
        instance_groups=[
            ExactInstanceGroup.model_validate(value)
            for value in evidence.get("instance_groups", [])
        ],
        overlap_findings_before=[
            MeshOverlapFinding.model_validate(value)
            for value in evidence.get("overlap_findings_before", [])
        ],
        overlap_findings_after=[
            MeshOverlapFinding.model_validate(value)
            for value in evidence.get("overlap_findings_after", [])
        ],
        created_at=utc_now(),
        notes=notes,
    )


def _manifest_artifact(
    root: Path,
    artifact_id: str,
    kind: str,
    path: Path,
) -> HashedArtifact:
    """Create one validated output-manifest receipt for an optimization plan."""

    return HashedArtifact(
        id=artifact_id,
        kind=kind,
        path=job_relative(root, path),
        sha256=sha256_file(path),
    )


def _load_or_run_preflight(
    job_id: str,
    profile_id: str,
    run_id: str | None,
) -> tuple[str, MeshPreflightReport, Path]:
    """Reuse an explicit run's preflight or create a fresh isolated run and report."""

    root = job_dir(job_id)
    selected = run_id or new_run_id("optimize")
    run_root = run_directory(root, selected)
    preflight_path = run_root / "mesh_preflight_report.json"
    if preflight_path.is_file():
        report = load_model(preflight_path, MeshPreflightReport)
    else:
        report = run_asset_preflight(job_id, profile_id, run_id=selected)
        run_root = run_directory(root, selected)
    if report.profile_id != profile_id:
        raise ValueError("Preflight profile does not match the requested optimization profile")
    profile = load_asset_profile(root, profile_id)
    if report.profile_artifact != profile_artifact(root, profile):
        raise RuntimeError("Asset profile changed after preflight; start a new V0.7 run")
    if not report.ok:
        raise RuntimeError(
            f"Portable mesh preflight failed; inspect {preflight_path} before optimization"
        )
    return selected, report, run_root


def _optimization_directives(
    profile: AssetProfile,
    preflight: MeshPreflightReport,
) -> list[OptimizationDirective]:
    """Build the deterministic semantic-family directives shown before approval."""

    _require_source_classification_evidence(preflight)
    levels = [target.level for target in profile.lod.targets] if profile.lod.enabled else []
    directives: list[OptimizationDirective] = []
    for mesh in preflight.meshes:
        excluded = _mesh_is_non_render_source(mesh)
        exclusion_reasons: list[str] = []
        if mesh.source_renderable is False:
            exclusion_reasons.append("the canonical Blender source is hidden from render")
        if NON_RENDER_BOOLEAN_TAG in {
            tag.casefold() for tag in (mesh.source_tags or [])
        }:
            exclusion_reasons.append(
                f"source tag {NON_RENDER_BOOLEAN_TAG!r} marks a boolean helper"
            )
        directives.append(
            OptimizationDirective(
                target_id=mesh.target_id,
                include=not excluded,
                lod_levels=[] if excluded else levels,
                collision_strategy="none" if excluded else "inherit",
                notes=(
                    [
                        "Excluded from portable render output because "
                        + " and ".join(exclusion_reasons)
                        + "."
                    ]
                    if excluded
                    else []
                ),
            )
        )
    return directives


def _require_source_classification_evidence(preflight: MeshPreflightReport) -> None:
    """Require explicit tag and visibility evidence from a fresh Blender preflight."""

    missing = sorted(
        mesh.target_id
        for mesh in preflight.meshes
        if mesh.source_tags is None or mesh.source_renderable is None
    )
    if missing:
        raise RuntimeError(
            "Preflight lacks source classification evidence for semantic families; start a new "
            f"V0.7 run: {missing}"
        )


def _mesh_is_non_render_source(mesh: MeshSummary) -> bool:
    """Classify hidden Blender sources and explicitly tagged cutters as non-render helpers."""

    return mesh.source_renderable is False or NON_RENDER_BOOLEAN_TAG in {
        tag.casefold() for tag in (mesh.source_tags or [])
    }


def _included_meshes(preflight: MeshPreflightReport) -> list[MeshSummary]:
    """Return only semantic families eligible for portable render output."""

    _require_source_classification_evidence(preflight)
    return [
        mesh
        for mesh in preflight.meshes
        if not _mesh_is_non_render_source(mesh)
    ]


def _validate_reviewed_directives(
    plan: OptimizationPlan,
    preflight: MeshPreflightReport,
) -> None:
    """Reject incomplete directives or inclusion of canonical non-render source families."""

    _require_source_classification_evidence(preflight)
    directives = {item.target_id: item for item in plan.directives}
    source_ids = {mesh.target_id for mesh in preflight.meshes}
    directive_ids = set(directives)
    missing = sorted(source_ids - directive_ids)
    unknown = sorted(directive_ids - source_ids)
    if missing or unknown:
        raise RuntimeError(
            "Optimization directives must match preflight semantic families exactly; "
            f"missing={missing}, unknown={unknown}"
        )
    unsafe = sorted(
        mesh.target_id
        for mesh in preflight.meshes
        if _mesh_is_non_render_source(mesh)
        and directives[mesh.target_id].include
    )
    if unsafe:
        raise RuntimeError(
            "Optimization plan includes canonical non-render source families: "
            f"{unsafe}"
        )
    if not any(item.include for item in plan.directives):
        raise RuntimeError("Optimization plan must include at least one render family")


def _estimated_lod_triangle_ceiling(
    triangle_count: int,
    object_count: int,
    ratio: float,
) -> int:
    """Bound per-object rounding when only semantic-family totals are available."""

    if triangle_count <= 0 or object_count <= 0:
        return 0
    rounded_family = math.ceil(triangle_count * ratio)
    return min(triangle_count, rounded_family + object_count - 1)


def _lod_review(
    profile: AssetProfile,
    preflight: MeshPreflightReport,
) -> LODOptimizationReview:
    """Summarize configured LOD generation and its bounded pre-execution cost."""

    included = _included_meshes(preflight)
    family_count = len(included)
    object_count = sum(mesh.object_count for mesh in included)
    triangle_count = sum(mesh.triangle_count for mesh in included)
    levels = [
        LODLevelReview(
            level=target.level,
            target_triangle_ratio=target.target_triangle_ratio,
            minimum_silhouette_iou=target.minimum_silhouette_iou,
            estimated_triangle_ceiling=sum(
                _estimated_lod_triangle_ceiling(
                    mesh.triangle_count,
                    mesh.object_count,
                    target.target_triangle_ratio,
                )
                for mesh in included
            ),
            estimated_object_count=object_count,
        )
        for target in profile.lod.targets
    ]
    if not profile.lod.enabled:
        return LODOptimizationReview(
            enabled=False,
            semantic_family_count=family_count,
            source_object_count=object_count,
            source_triangle_count=triangle_count,
            levels=[],
            recommendation="disabled_by_profile",
            reasons=["The selected asset profile disables derived LOD generation."],
        )
    return LODOptimizationReview(
        enabled=True,
        semantic_family_count=family_count,
        source_object_count=object_count,
        source_triangle_count=triangle_count,
        levels=levels,
        recommendation="manual_review",
        reasons=[
            "LOD0 remains preserved and every configured level is derived per source object.",
            "Triangle estimates include a conservative allowance for per-object rounding.",
        ],
        unverified_checks=["silhouette_iou", "runtime_switching"],
    )


def _collision_review(
    profile: AssetProfile,
    preflight: MeshPreflightReport,
) -> CollisionOptimizationReview:
    """Summarize configured collider generation without claiming runtime suitability."""

    strategy = profile.collision.strategy
    included = _included_meshes(preflight)
    family_count = len(included)
    object_count = sum(mesh.object_count for mesh in included)
    if strategy == "none":
        return CollisionOptimizationReview(
            strategy="none",
            semantic_family_count=family_count,
            source_object_count=object_count,
            estimated_collider_count=0,
            estimated_triangle_count=0,
            maximum_triangle_ceiling=0,
            max_hulls_per_object=profile.collision.max_hulls_per_object,
            max_triangles_per_object=profile.collision.max_triangles_per_object,
            include_in_package=False,
            recommendation="disabled_by_profile",
            reasons=["The selected asset profile disables collider generation."],
        )
    primitive_triangles = {
        "box": 12,
        "compound": 12,
        "sphere": 80,
        "capsule": 168,
    }.get(strategy)
    estimated_triangles = (
        object_count * primitive_triangles if primitive_triangles is not None else None
    )
    limitations = [
        "Destination-engine collision behavior and physics cost remain unverified.",
    ]
    if strategy == "compound":
        limitations.append(
            "The current compound policy creates one bounds box per source object; "
            "max_hulls_per_object is reserved for a future decomposition adapter."
        )
    if strategy in {"convex_hull", "mesh_proxy"}:
        limitations.append(
            "Exact collider triangles depend on source topology and are bounded only at execution."
        )
    return CollisionOptimizationReview(
        strategy=strategy,
        semantic_family_count=family_count,
        source_object_count=object_count,
        estimated_collider_count=object_count,
        estimated_triangle_count=estimated_triangles,
        maximum_triangle_ceiling=(
            object_count * profile.collision.max_triangles_per_object
        ),
        max_hulls_per_object=profile.collision.max_hulls_per_object,
        max_triangles_per_object=profile.collision.max_triangles_per_object,
        include_in_package=True,
        recommendation="manual_review",
        reasons=[
            "Every included source object inherits the profile collider strategy.",
            "Collider artifacts stay separate from canonical render geometry.",
        ],
        limitations=limitations,
    )


def _source_quality_summary(
    root: Path,
    job_id: str,
    value: str | None,
    source: SourceProvenance,
) -> SourceQualitySummary | None:
    """Load and hash one exact fast-preview quality report for V0.7 review."""

    if value is None:
        return None
    from ..background_quality.models import BackgroundQualityReport

    path = resolve_inside(root, value, "source quality report")
    report = BackgroundQualityReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if (
        report.job_id != job_id
        or report.source_fingerprint != source.source_fingerprint
        or report.build_fingerprint != source.build_fingerprint
    ):
        raise RuntimeError(
            "Background quality report is stale for the current V0.7 source"
        )
    return SourceQualitySummary(
        report_artifact=HashedArtifact(
            id=f"source_quality.{report.workflow_id.replace('-', '_')}",
            kind="other",
            path=job_relative(root, path),
            sha256=sha256_file(path),
        ),
        quality_status=report.quality_status,
        overall_direct_score=report.overall_direct_score,
        primary_silhouette_score=report.primary_silhouette_score,
        primary_high_findings=list(report.primary_high_findings),
        supporting_high_findings=list(report.supporting_high_findings),
        decorative_warnings=list(report.decorative_warnings),
        environment_findings=list(report.environment_findings),
        standard_workflow_recommended=report.standard_workflow_recommended,
        qa_run_id=report.qa_run_id,
        source_fingerprint=report.source_fingerprint,
        build_fingerprint=report.build_fingerprint,
        limitations=list(report.limitations),
    )


def _require_source_quality_current(
    root: Path,
    summary: SourceQualitySummary | None,
) -> None:
    """Reject a changed quality report after V0.7 review or exact approval."""

    if summary is None:
        return
    path = resolve_inside(
        root,
        summary.report_artifact.path,
        "source quality report",
    )
    if (
        not path.is_file()
        or sha256_file(path) != summary.report_artifact.sha256
    ):
        raise RuntimeError(
            "Reviewed background quality evidence changed; start a new V0.7 run"
        )


def _optimization_review_decision_guidance(
    source_quality: SourceQualitySummary | None,
) -> tuple[str | None, str | None]:
    """Recommend asset revision only when exact source QA says geometry needs revision."""

    if source_quality is None or source_quality.quality_status != "needs_revision":
        return None, None
    return (
        "revise_asset",
        "Direct-reference QA reports primary visual differences. Start a new standard "
        "revise_asset workflow before creating a fresh V0.7 review; revise_profile is "
        "reserved for LOD, collider, consolidation, UV, texture, or budget settings.",
    )


def plan_asset_optimization(
    job_id: str,
    *,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
    source_quality_path: str | None = None,
) -> OptimizationReview:
    """Create a non-mutating LOD/collider review that requires exact user approval."""

    if not load_feature_config().features.portable_asset_core:
        raise RuntimeError("portable_asset_core is disabled in cbm.toml")
    root = job_dir(job_id)
    profile = load_asset_profile(root, profile_id)
    selected, preflight, run_root = _load_or_run_preflight(job_id, profile_id, run_id)
    source = collect_source_provenance(root, job_id)
    source_quality = _source_quality_summary(
        root,
        job_id,
        source_quality_path,
        source,
    )
    if source != preflight.source:
        raise RuntimeError("Canonical source changed after preflight; start a new V0.7 run")
    plan_path = run_root / "review_plan.json"
    review_path = run_root / "optimization_review.json"
    if plan_path.exists() or review_path.exists():
        if not plan_path.is_file() or not review_path.is_file():
            raise RuntimeError("Optimization review artifacts are incomplete; start a new run")
        existing_plan = load_model(plan_path, OptimizationPlan)
        existing_review = load_model(review_path, OptimizationReview)
        if (
            existing_plan.status != "draft"
            or existing_review.plan_sha256 != sha256_file(plan_path)
            or existing_plan.source != source
            or existing_plan.source_quality != source_quality
            or existing_plan.profile_artifact != profile_artifact(root, profile)
            or existing_plan.preflight_report.sha256
            != sha256_file(run_root / "mesh_preflight_report.json")
        ):
            raise RuntimeError("Existing optimization review is stale; start a new V0.7 run")
        _validate_reviewed_directives(existing_plan, preflight)
        return existing_review
    preflight_receipt = _manifest_artifact(
        root,
        f"preflight.{selected}",
        "preflight_report",
        run_root / "mesh_preflight_report.json",
    )
    draft = OptimizationPlan(
        plan_id=f"plan.{selected}",
        job_id=job_id,
        profile_id=profile.profile_id,
        profile_artifact=profile_artifact(root, profile),
        preflight_report=preflight_receipt,
        source=source,
        source_quality=source_quality,
        status="draft",
        directives=_optimization_directives(profile, preflight),
        notes=[
            "This plan is review-only and does not authorize derived optimization.",
            "Canonical authoring geometry and material contracts remain read-only.",
        ],
    )
    _validate_reviewed_directives(draft, preflight)
    write_model(plan_path, draft)
    write_model(run_root / "optimization_plan.json", draft)
    recommended_decision, decision_reason = _optimization_review_decision_guidance(
        source_quality
    )
    review = OptimizationReview(
        review_id=f"review.{selected}",
        job_id=job_id,
        run_id=selected,
        profile_id=profile.profile_id,
        primary_format=profile.primary_format,
        profile_artifact=draft.profile_artifact,
        preflight_report=preflight_receipt,
        source=source,
        source_quality=source_quality,
        plan_sha256=sha256_file(plan_path),
        units=profile.units,
        up_axis=profile.up_axis,
        forward_axis=profile.forward_axis,
        pivot_policy=profile.pivot_policy,
        lod=_lod_review(profile, preflight),
        collision=_collision_review(profile, preflight),
        consolidation_mode=profile.consolidation.mode,
        consolidation=profile.consolidation,
        uv=profile.uv,
        textures=profile.textures,
        budgets=profile.budgets,
        recommended_decision=recommended_decision,
        decision_reason=decision_reason,
        warnings=[
            "LOD switch distances and runtime memory cost require a selected destination adapter.",
            "Collider suitability requires destination physics and gameplay context.",
            "Approval authorizes derived artifacts only; canonical authoring data "
            "remains unchanged.",
            *(
                [
                    "Fast-preview execution completed, but source visual quality is "
                    f"{source_quality.quality_status}; review its primary and decorative "
                    "findings before approving this package. Choose revise_asset for "
                    "authoring or similarity corrections, not revise_profile.",
                    *source_quality.limitations,
                ]
                if source_quality is not None
                and source_quality.quality_status != "passed"
                else []
            ),
            *(
                [
                    "Excluded non-render semantic families: "
                    + ", ".join(
                        item.target_id for item in draft.directives if not item.include
                    )
                ]
                if any(not item.include for item in draft.directives)
                else []
            ),
        ],
        created_at=utc_now(),
    )
    write_model(review_path, review)
    write_latest_run(root, selected, "optimization_review_pending")
    return review


def approve_asset_optimization(
    job_id: str,
    *,
    run_id: str,
    plan_sha256: str,
    approval_note: str,
) -> OptimizationApproval:
    """Record one explicit single-use approval for the exact reviewed plan hash."""

    if not approval_note.strip():
        raise ValueError("approval_note must not be empty")
    root = job_dir(job_id)
    run_root = run_directory(root, run_id)
    approval_path = run_root / "optimization_approval.json"
    if approval_path.exists():
        raise FileExistsError(f"Optimization approval already exists: {approval_path}")
    plan_path = run_root / "review_plan.json"
    review_path = run_root / "optimization_review.json"
    plan = load_model(plan_path, OptimizationPlan)
    review = load_model(review_path, OptimizationReview)
    actual_plan_hash = sha256_file(plan_path)
    if plan.status != "draft" or plan_sha256.lower() != actual_plan_hash:
        raise RuntimeError("Approval does not match the exact draft OptimizationPlan SHA-256")
    if review.plan_sha256 != actual_plan_hash:
        raise RuntimeError("OptimizationReview is not bound to the current draft plan")
    profile = load_asset_profile(root, plan.profile_id)
    preflight_path = run_root / "mesh_preflight_report.json"
    preflight = load_model(preflight_path, MeshPreflightReport)
    current_source = collect_source_provenance(root, job_id)
    _require_source_quality_current(root, plan.source_quality)
    if (
        plan.job_id != job_id
        or review.job_id != job_id
        or review.run_id != run_id
        or plan.profile_artifact != profile_artifact(root, profile)
        or plan.preflight_report.sha256 != sha256_file(preflight_path)
        or plan.source != current_source
    ):
        raise RuntimeError("Profile, preflight, source, or review changed; create a new plan")
    _validate_reviewed_directives(plan, preflight)
    approval = OptimizationApproval(
        approval_id=f"approval.{run_id}",
        job_id=job_id,
        run_id=run_id,
        profile_id=plan.profile_id,
        plan_sha256=actual_plan_hash,
        review_sha256=sha256_file(review_path),
        profile_sha256=plan.profile_artifact.sha256,
        preflight_sha256=plan.preflight_report.sha256,
        source_fingerprint=plan.source.source_fingerprint,
        approval_note=approval_note.strip(),
        approved_at=utc_now(),
    )
    write_model(approval_path, approval)
    approved = plan.model_copy(
        update={"status": "approved", "approved_at": approval.approved_at}
    )
    write_model(
        run_root / "optimization_plan.json",
        OptimizationPlan.model_validate(approved.model_dump(mode="json")),
    )
    write_latest_run(root, run_id, "optimization_approved")
    return approval


def _consume_optimization_approval(
    root: Path,
    run_root: Path,
    plan: OptimizationPlan,
    approved_plan_sha256: str | None,
) -> OptimizationApproval:
    """Verify and consume one exact approval before Blender creates derived artifacts."""

    review_plan_path = run_root / "review_plan.json"
    review_path = run_root / "optimization_review.json"
    approval_path = run_root / "optimization_approval.json"
    policy_snapshot_path = run_root / "optimization_policy_authorization.json"
    if policy_snapshot_path.exists():
        raise RuntimeError(
            "Optimization run mixes user approval and policy authorization evidence"
        )
    reviewed_plan = load_model(review_plan_path, OptimizationPlan)
    review = load_model(review_path, OptimizationReview)
    approval = load_model(approval_path, OptimizationApproval)
    plan_hash = sha256_file(review_plan_path)
    if not approved_plan_sha256 or approved_plan_sha256.lower() != plan_hash:
        raise RuntimeError("asset-optimize requires the exact approved review plan SHA-256")
    if approval.used:
        raise RuntimeError("Optimization approval has already been consumed")
    expected_approved = reviewed_plan.model_copy(
        update={"status": "approved", "approved_at": approval.approved_at}
    )
    expected_approved = OptimizationPlan.model_validate(
        expected_approved.model_dump(mode="json")
    )
    if (
        reviewed_plan.status != "draft"
        or plan != expected_approved
        or approval.job_id != plan.job_id
        or approval.run_id != run_root.name
        or approval.profile_id != plan.profile_id
        or approval.plan_sha256 != plan_hash
        or review.plan_sha256 != plan_hash
        or approval.review_sha256 != sha256_file(review_path)
        or approval.profile_sha256 != plan.profile_artifact.sha256
        or approval.preflight_sha256 != plan.preflight_report.sha256
        or approval.source_fingerprint != plan.source.source_fingerprint
    ):
        raise RuntimeError("Optimization approval no longer matches the reviewed run")
    consumed = approval.model_copy(update={"used": True, "used_at": utc_now()})
    consumed = OptimizationApproval.model_validate(consumed.model_dump(mode="json"))
    write_model(approval_path, consumed)
    return consumed


def _snapshot_optimization_policy_authorization(
    run_root: Path,
    policy_authorization_path: Path,
) -> Path:
    """Copy one already-validated policy grant into immutable run-owned evidence."""

    if (run_root / "optimization_approval.json").exists():
        raise RuntimeError(
            "Optimization run mixes user approval and policy authorization evidence"
        )
    source = policy_authorization_path.resolve(strict=True)
    target = run_root / "optimization_policy_authorization.json"
    content = source.read_bytes()
    if target.exists():
        if not target.is_file() or target.read_bytes() != content:
            raise RuntimeError("Optimization policy authorization snapshot changed")
        return target
    temporary = run_root / f".optimization-policy-{uuid4().hex[:8]}.tmp"
    temporary.write_bytes(content)
    os.replace(temporary, target)
    return target


def _consume_optimization_policy_authorization(
    root: Path,
    run_root: Path,
    plan: OptimizationPlan,
    approved_plan_sha256: str | None,
    *,
    policy_authorization_path: Path,
    workflow_id: str,
    workflow_step_id: str,
    workflow_input_fingerprint: str,
):
    """Validate a consumed autonomy policy grant without forging a user approval."""

    from ..autonomy.authorization import validate_policy_authorization
    from ..autonomy.models import PolicyAuthorization

    review_plan_path = run_root / "review_plan.json"
    review_path = run_root / "optimization_review.json"
    if (run_root / "optimization_approval.json").exists():
        raise RuntimeError(
            "Optimization run mixes user approval and policy authorization evidence"
        )
    reviewed_plan = load_model(review_plan_path, OptimizationPlan)
    review = load_model(review_path, OptimizationReview)
    plan_hash = sha256_file(review_plan_path)
    if not approved_plan_sha256 or approved_plan_sha256.lower() != plan_hash:
        raise RuntimeError("asset-optimize requires the exact policy-authorized plan SHA-256")
    authorization = PolicyAuthorization.model_validate_json(
        policy_authorization_path.read_text(encoding="utf-8")
    )
    validate_policy_authorization(
        root,
        authorization,
        expected_job_id=plan.job_id,
        expected_workflow_id=workflow_id,
        expected_step_id=workflow_step_id,
        expected_gate_kind="optimization_plan",
        expected_input_fingerprint=workflow_input_fingerprint,
    )
    expected_target = review_plan_path.resolve().relative_to(root.resolve()).as_posix()
    if (
        authorization.target_artifact.path != expected_target
        or authorization.target_artifact.sha256 != plan_hash
        or review.plan_sha256 != plan_hash
        or review.job_id != plan.job_id
        or review.run_id != run_root.name
        or review.profile_artifact != plan.profile_artifact
        or review.preflight_report != plan.preflight_report
        or review.source != plan.source
        or reviewed_plan.status != "draft"
        or plan != reviewed_plan
        or authorization.consumed_at is None
    ):
        raise RuntimeError("Optimization policy authorization is stale or mismatched")
    _snapshot_optimization_policy_authorization(
        run_root,
        policy_authorization_path,
    )
    approved = reviewed_plan.model_copy(
        update={"status": "approved", "approved_at": authorization.consumed_at}
    )
    approved = OptimizationPlan.model_validate(approved.model_dump(mode="json"))
    write_model(run_root / "optimization_plan.json", approved)
    return authorization


def optimize_asset(
    job_id: str,
    *,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
    approved_plan_sha256: str | None = None,
    policy_authorization_path: str | Path | None = None,
    workflow_id: str | None = None,
    workflow_step_id: str | None = None,
    workflow_input_fingerprint: str | None = None,
) -> OptimizationPlan:
    """Execute one exactly user- or policy-authorized derived-asset plan once."""

    if not load_feature_config().features.portable_asset_core:
        raise RuntimeError("portable_asset_core is disabled in cbm.toml")
    root = job_dir(job_id)
    if not run_id:
        raise ValueError("asset-optimize requires the reviewed --run-id")
    selected = run_id
    run_root = run_directory(root, selected)
    preflight = load_model(run_root / "mesh_preflight_report.json", MeshPreflightReport)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    if plan.profile_id != profile_id or preflight.profile_id != profile_id:
        raise RuntimeError("Requested profile does not match the reviewed optimization run")
    profile = load_asset_profile(root, profile_id)
    source = collect_source_provenance(root, job_id)
    _require_source_quality_current(root, plan.source_quality)
    if (
        source != preflight.source
        or source != plan.source
        or plan.profile_artifact != profile_artifact(root, profile)
        or plan.preflight_report.sha256
        != sha256_file(run_root / "mesh_preflight_report.json")
    ):
        raise RuntimeError("Reviewed source, profile, or preflight changed; start a new V0.7 run")
    _validate_reviewed_directives(plan, preflight)
    if policy_authorization_path is None:
        approval = _consume_optimization_approval(
            root,
            run_root,
            plan,
            approved_plan_sha256,
        )
        approval_note = (
            "Execution is bound to one explicit, hash-matched, single-use user approval."
        )
        approved_at = approval.approved_at
    else:
        if not workflow_id or not workflow_step_id or not workflow_input_fingerprint:
            raise ValueError("policy-authorized optimization requires exact workflow binding")
        policy_path = Path(policy_authorization_path).expanduser().resolve()
        try:
            policy_path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("optimization policy authorization escaped its job") from exc
        approval = _consume_optimization_policy_authorization(
            root,
            run_root,
            plan,
            approved_plan_sha256,
            policy_authorization_path=policy_path,
            workflow_id=workflow_id,
            workflow_step_id=workflow_step_id,
            workflow_input_fingerprint=workflow_input_fingerprint,
        )
        approval_note = (
            "Execution is bound to one exact preauthorized-profile PolicyAuthorization; "
            "no user OptimizationApproval was created."
        )
        approved_at = approval.consumed_at
    plan = plan.model_copy(
        update={
            "status": "running",
            "approved_at": approved_at,
            "notes": [
                *plan.notes,
                approval_note,
            ],
        }
    )
    plan = OptimizationPlan.model_validate(plan.model_dump(mode="json"))
    plan_path = run_root / "optimization_plan.json"
    execution_plan_path = run_root / "execution_plan.json"
    write_model(plan_path, plan)
    write_model(execution_plan_path, plan)
    optimized_blend = run_root / "optimized" / "scene.blend"
    raw_manifest_path = run_root / "optimized_asset_evidence.json"
    try:
        run_blender(
            "prepare_optimized_asset.py",
            [
                "--plan",
                str(execution_plan_path),
                "--profile",
                str(profile_path := root / "asset_profiles" / f"{profile_id}.json"),
                "--output-blend",
                str(optimized_blend),
                "--output-manifest",
                str(raw_manifest_path),
            ],
            blend_file=root / "blender" / "scene.blend",
        )
        if not profile_path.is_file():
            raise FileNotFoundError(profile_path)
        raw = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not raw.get("ok"):
            raise RuntimeError("Blender did not produce a successful optimized asset manifest")
        raw_source = raw.get("source", {})
        if not isinstance(raw_source, dict) or (
            str(raw_source.get("build_fingerprint", "")).lower()
            != source.build_fingerprint
        ):
            raise RuntimeError("Optimized Blender evidence has a stale build fingerprint")
        require_unchanged_source(source, root, job_id)
        _require_source_quality_current(root, plan.source_quality)
        cost = _asset_cost_report(selected, profile, source, raw)
        cost_path = run_root / "asset_cost_report.json"
        write_model(cost_path, cost)
        if not cost.ok:
            failed_budgets = [
                item.message for item in cost.budgets if item.status == "failed"
            ]
            raise RuntimeError(
                "V0.7.3 static-asset cost budget failed: " + "; ".join(failed_budgets)
            )
        lod = _lod_manifest(root, selected, profile, source, raw, optimized_blend)
        collision = _collision_manifest(
            root,
            selected,
            profile,
            source,
            raw,
            optimized_blend,
        )
        uv = _uv_manifest(selected, profile, source, raw)
        paths = {
            "lod": run_root / "lod_manifest.json",
            "collision": run_root / "collision_manifest.json",
            "uv": run_root / "uv_manifest.json",
            "cost": cost_path,
        }
        write_model(paths["lod"], lod)
        write_model(paths["collision"], collision)
        write_model(paths["uv"], uv)
        output_kinds = {
            "lod": "lod_manifest",
            "collision": "collision_manifest",
            "uv": "uv_manifest",
            "cost": "asset_cost_report",
        }
        outputs = [
            _manifest_artifact(
                root,
                f"manifest.{name}.{selected}",
                output_kinds[name],
                path,
            )
            for name, path in paths.items()
        ]
        outputs.extend(
            [
                _manifest_artifact(
                    root,
                    f"plan.execution.{selected}",
                    "optimization_plan",
                    execution_plan_path,
                ),
                _manifest_artifact(
                    root,
                    f"blend.optimized.{selected}",
                    "blend",
                    optimized_blend,
                ),
                _manifest_artifact(
                    root,
                    f"evidence.optimized.{selected}",
                    "other",
                    raw_manifest_path,
                ),
            ]
        )
        plan = plan.model_copy(
            update={
                "status": "complete",
                "completed_at": utc_now(),
                "output_manifests": outputs,
            }
        )
        plan = OptimizationPlan.model_validate(plan.model_dump(mode="json"))
        write_model(plan_path, plan)
        write_latest_run(root, selected, "optimization_complete")
        return plan
    except Exception as exc:
        failed = plan.model_copy(
            update={
                "status": "failed",
                "completed_at": utc_now(),
                "errors": [str(exc)],
            }
        )
        write_model(
            plan_path,
            OptimizationPlan.model_validate(failed.model_dump(mode="json")),
        )
        write_latest_run(root, selected, "optimization_failed")
        raise


def latest_optimized_run(job_id: str) -> tuple[str, Path]:
    """Resolve the latest run and require a complete optimized Blender scene."""

    root = job_dir(job_id)
    selected = latest_complete_run_id(root)
    if not selected:
        raise FileNotFoundError("No V0.7 optimization run exists for this job")
    run_root = run_directory(root, selected)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    blend = run_root / "optimized" / "scene.blend"
    if plan.status != "complete" or not blend.is_file():
        raise RuntimeError(f"Latest optimization run is not complete: {selected}")
    return selected, run_root
