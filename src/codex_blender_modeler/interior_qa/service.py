"""Approval-bound host service for isolated multi-view interior QA."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, ImageOps

from ..architecture import (
    list_interior_objects,
    validate_job_interior_scope,
)
from ..blender_artifacts import safe_artifact_name, stable_json_digest, write_json_atomic
from ..build_provenance import collect_build_provenance
from ..models import ObjectSpec, SceneSpec
from ..qa.models import RenderPassRecord
from ..qa.semantic_localizer import extract_semantic_bboxes
from ..workspace import job_dir, load_job, sha256_file
from .models import (
    InteriorQABounds,
    InteriorQAFinding,
    InteriorQALatest,
    InteriorQAObjectRecord,
    InteriorQAPlan,
    InteriorQAPlanApproval,
    InteriorQARenderManifest,
    InteriorQAReport,
    InteriorQARevisionCandidate,
    InteriorQARevisionCandidates,
    InteriorQASourceInventory,
    InteriorQASpaceCoverage,
    InteriorQAView,
    InteriorQAViewCoverage,
)

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")
_PROFILE_DIRECTIONS: dict[str, tuple[tuple[str, float, float], ...]] = {
    "minimal": (
        ("north", 0.0, 1.0),
        ("east", 1.0, 0.0),
        ("south", 0.0, -1.0),
        ("west", -1.0, 0.0),
    ),
    "standard": (
        ("north", 0.0, 1.0),
        ("east", 1.0, 0.0),
        ("south", 0.0, -1.0),
        ("west", -1.0, 0.0),
        ("north_east", math.sqrt(0.5), math.sqrt(0.5)),
        ("south_west", -math.sqrt(0.5), -math.sqrt(0.5)),
    ),
    "thorough": (
        ("north", 0.0, 1.0),
        ("east", 1.0, 0.0),
        ("south", 0.0, -1.0),
        ("west", -1.0, 0.0),
        ("north_east", math.sqrt(0.5), math.sqrt(0.5)),
        ("south_east", math.sqrt(0.5), -math.sqrt(0.5)),
        ("south_west", -math.sqrt(0.5), -math.sqrt(0.5)),
        ("north_west", -math.sqrt(0.5), math.sqrt(0.5)),
    ),
}


def _utc_now() -> str:
    """Return one timezone-aware timestamp for immutable QA evidence."""

    return datetime.now(UTC).isoformat()


def _new_run_id() -> str:
    """Create a sortable collision-resistant interior QA run ID."""

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"interior-{stamp}-{uuid4().hex[:8]}"


def _validate_run_id(value: str) -> str:
    """Reject path traversal and non-portable interior QA run IDs."""

    if not _RUN_ID_RE.fullmatch(value):
        raise ValueError(
            "interior QA run_id must match [a-zA-Z0-9][a-zA-Z0-9._-]{0,95}"
        )
    return value


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one contained artifact as a normalized job-relative POSIX path."""

    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Interior QA artifact is outside the job workspace: {path}") from exc


def _load_plan(path: Path) -> InteriorQAPlan:
    """Load one required strict interior QA plan."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return InteriorQAPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _load_approval(path: Path) -> InteriorQAPlanApproval:
    """Load one required strict single-use interior QA approval."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return InteriorQAPlanApproval.model_validate_json(path.read_text(encoding="utf-8"))


def _source_fingerprint(
    *,
    scene_spec_sha256: str,
    build_fingerprint: str,
    scope_sha256: str,
    scope_approval_sha256: str,
    inventory_sha256: str,
    profile: str,
    resolution: tuple[int, int],
    max_views: int,
    eye_height_m: float,
    target_ids: list[str],
) -> str:
    """Hash every canonical source and bounded planning parameter."""

    return stable_json_digest(
        {
            "scene_spec_sha256": scene_spec_sha256,
            "build_fingerprint": build_fingerprint,
            "interior_scope_sha256": scope_sha256,
            "interior_scope_approval_sha256": scope_approval_sha256,
            "source_inventory_sha256": inventory_sha256,
            "profile": profile,
            "resolution": list(resolution),
            "max_views": max_views,
            "eye_height_m": eye_height_m,
            "target_ids": target_ids,
        }
    )


def _object_locators(obj: ObjectSpec) -> tuple[list[str | None], list[str | None]]:
    """Read normalized level and space locators from one approved interior object."""

    levels = sorted(
        {
            tag.strip().casefold().removeprefix("level:")
            for tag in obj.tags
            if tag.strip().casefold().startswith("level:")
        }
    )
    spaces = sorted(
        {
            tag.strip().casefold().removeprefix("space:")
            for tag in obj.tags
            if tag.strip().casefold().startswith("space:")
        }
    )
    return levels or [None], spaces or [None]


def _semantic_bounds(
    inventory: InteriorQASourceInventory,
) -> dict[str, InteriorQABounds]:
    """Union fresh Blender object-instance bounds by stable semantic ID."""

    grouped: dict[str, list[InteriorQAObjectRecord]] = defaultdict(list)
    for record in inventory.objects:
        grouped[record.semantic_id].append(record)
    result: dict[str, InteriorQABounds] = {}
    for semantic_id, records in sorted(grouped.items()):
        result[semantic_id] = InteriorQABounds(
            min=tuple(
                min(record.bbox_world.min[axis] for record in records)
                for axis in range(3)
            ),
            max=tuple(
                max(record.bbox_world.max[axis] for record in records)
                for axis in range(3)
            ),
        )
    return result


def _group_targets(
    objects: list[ObjectSpec],
) -> dict[tuple[str | None, str | None], list[str]]:
    """Group interior semantic IDs by approved level and space locators."""

    grouped: dict[tuple[str | None, str | None], set[str]] = defaultdict(set)
    for obj in objects:
        levels, spaces = _object_locators(obj)
        for level in levels:
            for space in spaces:
                grouped[(level, space)].add(obj.id)
    return {
        key: sorted(values)
        for key, values in sorted(
            grouped.items(),
            key=lambda item: (item[0][0] or "", item[0][1] or ""),
        )
    }


def _union_bounds(
    target_ids: list[str],
    semantic_bounds: dict[str, InteriorQABounds],
) -> InteriorQABounds:
    """Union semantic family bounds for one level/space camera group."""

    selected = [semantic_bounds[target_id] for target_id in target_ids]
    return InteriorQABounds(
        min=tuple(min(bounds.min[axis] for bounds in selected) for axis in range(3)),
        max=tuple(max(bounds.max[axis] for bounds in selected) for axis in range(3)),
    )


def _view_group_slug(level_id: str | None, space_id: str | None) -> str:
    """Create one portable readable prefix for interior view IDs."""

    raw = ".".join(value for value in (level_id, space_id) if value) or "interior"
    return safe_artifact_name(raw).casefold()


def _allocated_direction_counts(
    group_count: int,
    profile: str,
    max_views: int,
) -> list[int]:
    """Allocate at least four rotation views per space and bounded profile extras."""

    minimum = 4 * group_count
    if minimum > max_views:
        raise ValueError(
            f"max_views={max_views} cannot cover {group_count} interior groups with "
            "the required four cardinal views each"
        )
    desired = len(_PROFILE_DIRECTIONS[profile])
    counts = [4] * group_count
    remaining = max_views - minimum
    while remaining > 0 and any(count < desired for count in counts):
        for index in range(group_count):
            if remaining <= 0:
                break
            if counts[index] < desired:
                counts[index] += 1
                remaining -= 1
    return counts


def _build_views(
    groups: dict[tuple[str | None, str | None], list[str]],
    semantic_bounds: dict[str, InteriorQABounds],
    *,
    profile: str,
    max_views: int,
    eye_height_m: float,
) -> tuple[list[InteriorQAView], list[str]]:
    """Create deterministic 360-degree temporary cameras for every interior group."""

    entries = list(groups.items())
    counts = _allocated_direction_counts(len(entries), profile, max_views)
    views: list[InteriorQAView] = []
    warnings: list[str] = []
    for ((level_id, space_id), target_ids), direction_count in zip(
        entries,
        counts,
        strict=True,
    ):
        bounds = _union_bounds(target_ids, semantic_bounds)
        center = tuple(
            (bounds.min[axis] + bounds.max[axis]) * 0.5 for axis in range(3)
        )
        width = max(0.01, bounds.max[0] - bounds.min[0])
        depth = max(0.01, bounds.max[1] - bounds.min[1])
        height = max(0.01, bounds.max[2] - bounds.min[2])
        eye_offset = min(eye_height_m, max(0.15, height * 0.55))
        camera_location = (center[0], center[1], bounds.min[2] + eye_offset)
        look_distance = max(0.5, max(width, depth) * 0.45)
        clip_end = max(10.0, math.sqrt(width**2 + depth**2 + height**2) * 4.0)
        group_slug = _view_group_slug(level_id, space_id)
        for direction_name, x_axis, y_axis in _PROFILE_DIRECTIONS[profile][
            :direction_count
        ]:
            view_id = f"{group_slug}.{direction_name}"
            views.append(
                InteriorQAView(
                    view_id=view_id,
                    level_id=level_id,
                    space_id=space_id,
                    purpose="room_rotation",
                    location=camera_location,
                    target=(
                        camera_location[0] + x_axis * look_distance,
                        camera_location[1] + y_axis * look_distance,
                        camera_location[2],
                    ),
                    focal_length_mm=18.0,
                    clip_start_m=0.03,
                    clip_end_m=clip_end,
                    target_ids=target_ids,
                )
            )
    desired_total = len(entries) * len(_PROFILE_DIRECTIONS[profile])
    if len(views) < desired_total:
        warnings.append(
            f"max_views limited profile={profile} from {desired_total} to {len(views)} views"
        )
    return views, warnings


def _require_approved_scope(
    job_id: str,
) -> tuple[SceneSpec, list[ObjectSpec], str, str]:
    """Require a valid approved InteriorScope and at least one canonical interior object."""

    root = job_dir(job_id)
    scene_spec_path = root / "analysis" / "scene_spec.json"
    if not scene_spec_path.is_file():
        raise FileNotFoundError(scene_spec_path)
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    validation = validate_job_interior_scope(job_id, write_report=True)
    if not validation.ok:
        raise ValueError(
            "Interior QA requires a valid InteriorScope: " + "; ".join(validation.errors)
        )
    if validation.scope_state != "approved" or not validation.approval_valid:
        raise PermissionError(
            "Interior QA requires the exact current InteriorScope approval"
        )
    objects = list_interior_objects(spec)
    if not objects:
        raise ValueError("Interior QA requires at least one approved interior object")
    if validation.scope_sha256 is None or validation.approval_sha256 is None:
        raise ValueError("InteriorScope validation did not provide exact contract hashes")
    return spec, objects, validation.scope_sha256, validation.approval_sha256


def plan_job_interior_qa(
    job_id: str,
    *,
    profile: str = "standard",
    resolution: int = 512,
    max_views: int = 24,
    eye_height_m: float = 1.6,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Inspect the current build and create an immutable approval-bound camera plan."""

    load_job(job_id)
    if profile not in _PROFILE_DIRECTIONS:
        raise ValueError("interior QA profile must be minimal, standard, or thorough")
    if resolution < 128 or resolution > 2048:
        raise ValueError("interior QA resolution must be within [128, 2048]")
    if max_views < 1 or max_views > 64:
        raise ValueError("interior QA max_views must be within [1, 64]")
    if eye_height_m <= 0 or eye_height_m > 3.0:
        raise ValueError("interior QA eye_height_m must be within (0, 3]")
    root = job_dir(job_id)
    _spec, interior_objects, scope_hash, scope_approval_hash = _require_approved_scope(
        job_id
    )
    selected_run_id = _validate_run_id(run_id or _new_run_id())
    run_dir = root / "qa" / "interior" / "runs" / selected_run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    provenance = collect_build_provenance(
        root,
        job_id,
        scene_spec_path=root / "analysis" / "scene_spec.json",
    )
    target_ids = sorted({obj.id for obj in interior_objects})
    source_inventory_path = run_dir / "source_inventory.json"
    from ..blender_artifact_runner import inspect_job_interior_qa_source

    inventory = inspect_job_interior_qa_source(
        job_id,
        run_id=selected_run_id,
        target_ids=target_ids,
        output_path=source_inventory_path,
        scene_spec_sha256=str(provenance["scene_spec_sha256"]),
        build_fingerprint=str(provenance["fingerprint"]),
        interior_scope_sha256=scope_hash,
        interior_scope_approval_sha256=scope_approval_hash,
    )
    if inventory.job_id != job_id:
        raise ValueError("Blender interior QA inventory job_id does not match the job")
    if inventory.missing_target_ids:
        raise RuntimeError(
            "Current Blender build is missing approved interior IDs: "
            + ", ".join(inventory.missing_target_ids)
        )
    semantic_bounds = _semantic_bounds(inventory)
    missing_bounds = sorted(set(target_ids) - set(semantic_bounds))
    if missing_bounds:
        raise RuntimeError(
            "Interior QA could not resolve Blender bounds for: " + ", ".join(missing_bounds)
        )
    groups = _group_targets(interior_objects)
    views, planning_warnings = _build_views(
        groups,
        semantic_bounds,
        profile=profile,
        max_views=max_views,
        eye_height_m=eye_height_m,
    )
    inventory_hash = sha256_file(source_inventory_path)
    resolution_tuple = (resolution, resolution)
    source_fingerprint = _source_fingerprint(
        scene_spec_sha256=str(provenance["scene_spec_sha256"]),
        build_fingerprint=str(provenance["fingerprint"]),
        scope_sha256=scope_hash,
        scope_approval_sha256=scope_approval_hash,
        inventory_sha256=inventory_hash,
        profile=profile,
        resolution=resolution_tuple,
        max_views=max_views,
        eye_height_m=eye_height_m,
        target_ids=target_ids,
    )
    plan = InteriorQAPlan(
        job_id=job_id,
        run_id=selected_run_id,
        profile=profile,  # type: ignore[arg-type]
        resolution=resolution_tuple,
        max_views=max_views,
        eye_height_m=eye_height_m,
        scene_spec_sha256=str(provenance["scene_spec_sha256"]),
        build_fingerprint=str(provenance["fingerprint"]),
        interior_scope_sha256=scope_hash,
        interior_scope_approval_sha256=scope_approval_hash,
        source_inventory_path=_job_relative(root, source_inventory_path),
        source_inventory_sha256=inventory_hash,
        source_fingerprint=source_fingerprint,
        target_ids=target_ids,
        views=views,
        created_at=_utc_now(),
        warnings=[*inventory.warnings, *planning_warnings],
    )
    plan_path = run_dir / "plan.json"
    write_json_atomic(plan_path, plan.model_dump(mode="json"))
    plan_hash = sha256_file(plan_path)
    return {
        "ok": True,
        "status": "awaiting_approval",
        "job_id": job_id,
        "run_id": selected_run_id,
        "profile": profile,
        "plan": str(plan_path),
        "plan_sha256": plan_hash,
        "source_inventory": str(source_inventory_path),
        "view_count": len(plan.views),
        "space_count": len(groups),
        "target_count": len(target_ids),
        "views": [
            {
                "view_id": view.view_id,
                "level_id": view.level_id,
                "space_id": view.space_id,
                "target_count": len(view.target_ids),
            }
            for view in plan.views
        ],
        "warnings": plan.warnings,
        "approval_required": True,
    }


def _require_current_plan_sources(root: Path, plan: InteriorQAPlan) -> None:
    """Reject stale canonical, scope, approval, build, or inventory evidence."""

    scene_spec_path = root / "analysis" / "scene_spec.json"
    scope_path = root / "architecture" / "interior_scope.json"
    scope_approval_path = root / "architecture" / "interior_scope.approval.json"
    inventory_path = root / plan.source_inventory_path
    current = {
        "scene_spec_sha256": sha256_file(scene_spec_path),
        "interior_scope_sha256": sha256_file(scope_path),
        "interior_scope_approval_sha256": sha256_file(scope_approval_path),
        "source_inventory_sha256": sha256_file(inventory_path),
    }
    expected = {
        "scene_spec_sha256": plan.scene_spec_sha256,
        "interior_scope_sha256": plan.interior_scope_sha256,
        "interior_scope_approval_sha256": plan.interior_scope_approval_sha256,
        "source_inventory_sha256": plan.source_inventory_sha256,
    }
    stale = [
        label for label, actual in current.items() if actual != expected[label]
    ]
    provenance = collect_build_provenance(root, plan.job_id)
    if str(provenance["fingerprint"]) != plan.build_fingerprint:
        stale.append("build_fingerprint")
    calculated = _source_fingerprint(
        scene_spec_sha256=plan.scene_spec_sha256,
        build_fingerprint=plan.build_fingerprint,
        scope_sha256=plan.interior_scope_sha256,
        scope_approval_sha256=plan.interior_scope_approval_sha256,
        inventory_sha256=plan.source_inventory_sha256,
        profile=plan.profile,
        resolution=plan.resolution,
        max_views=plan.max_views,
        eye_height_m=plan.eye_height_m,
        target_ids=plan.target_ids,
    )
    if calculated != plan.source_fingerprint:
        stale.append("source_fingerprint")
    if stale:
        raise RuntimeError(
            "Interior QA plan is stale; create a new plan after reviewing: "
            + ", ".join(sorted(set(stale)))
        )


def approve_job_interior_qa_plan(
    job_id: str,
    run_id: str,
    *,
    plan_sha256: str,
    approval_note: str,
    approved_view_ids: list[str] | None = None,
) -> InteriorQAPlanApproval:
    """Persist explicit approval for one exact plan and optional exact view subset."""

    root = job_dir(job_id)
    selected_run_id = _validate_run_id(run_id)
    run_dir = root / "qa" / "interior" / "runs" / selected_run_id
    plan_path = run_dir / "plan.json"
    plan = _load_plan(plan_path)
    actual_plan_hash = sha256_file(plan_path)
    if actual_plan_hash != plan_sha256:
        raise ValueError(
            "Interior QA approval hash does not match the plan: "
            f"expected={actual_plan_hash} supplied={plan_sha256}"
        )
    if plan.job_id != job_id or plan.run_id != selected_run_id:
        raise ValueError("Interior QA plan identity does not match the selected job/run")
    _require_current_plan_sources(root, plan)
    approval_path = run_dir / "plan_approval.json"
    if approval_path.exists():
        raise FileExistsError(f"Interior QA approval already exists: {approval_path}")
    valid_view_ids = [view.view_id for view in plan.views]
    selected = approved_view_ids or valid_view_ids
    unknown = sorted(set(selected) - set(valid_view_ids))
    if unknown:
        raise ValueError(f"Interior QA approval references unknown views: {unknown}")
    selected_targets = {
        target_id
        for view in plan.views
        if view.view_id in set(selected)
        for target_id in view.target_ids
    }
    if selected_targets != set(plan.target_ids):
        missing = sorted(set(plan.target_ids) - selected_targets)
        raise ValueError(
            "Interior QA approval must retain coverage for every planned target ID; "
            f"missing={missing}"
        )
    approval = InteriorQAPlanApproval(
        approval_id=f"interior-qa-{uuid4().hex}",
        job_id=job_id,
        run_id=selected_run_id,
        plan_sha256=actual_plan_hash,
        source_fingerprint=plan.source_fingerprint,
        approved_view_ids=selected,
        approval_note=approval_note,
        approved_at=_utc_now(),
    )
    write_json_atomic(approval_path, approval.model_dump(mode="json"))
    return approval


def _resolve_pass(
    manifest_path: Path,
    record: RenderPassRecord,
) -> Path:
    """Resolve one manifest-relative interior pass and enforce its recorded hash."""

    raw = Path(record.path)
    path = raw.resolve() if raw.is_absolute() else (manifest_path.parent / raw).resolve()
    try:
        path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise ValueError(f"Interior QA pass escapes its run directory: {record.path}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    if sha256_file(path) != record.sha256:
        raise ValueError(f"Interior QA pass hash changed: {record.kind}")
    return path


def _coverage_from_manifest(
    manifest: InteriorQARenderManifest,
    manifest_path: Path,
) -> tuple[
    list[InteriorQAViewCoverage],
    list[InteriorQASpaceCoverage],
    list[str],
    list[str],
]:
    """Measure exact semantic-ID visibility per view and across every interior space."""

    view_coverage: list[InteriorQAViewCoverage] = []
    grouped: dict[
        tuple[str | None, str | None],
        dict[str, set[str] | list[str]],
    ] = {}
    visible_overall: set[str] = set()
    for view in manifest.views:
        object_record = next(record for record in view.passes if record.kind == "object_id")
        object_path = _resolve_pass(manifest_path, object_record)
        mapping = {
            target_id: manifest.object_id_colors[target_id]
            for target_id in view.target_ids
        }
        bboxes = extract_semantic_bboxes(object_path, mapping)
        visible = sorted(
            target_id for target_id, bbox in bboxes.items() if bbox is not None
        )
        unseen = sorted(set(view.target_ids) - set(visible))
        fraction = len(visible) / len(view.target_ids)
        view_coverage.append(
            InteriorQAViewCoverage(
                view_id=view.view_id,
                level_id=view.level_id,
                space_id=view.space_id,
                target_ids=sorted(view.target_ids),
                visible_target_ids=visible,
                unseen_target_ids=unseen,
                semantic_visibility_fraction=fraction,
            )
        )
        visible_overall.update(visible)
        key = (view.level_id, view.space_id)
        bucket = grouped.setdefault(
            key,
            {"views": [], "targets": set(), "visible": set()},
        )
        views = bucket["views"]
        targets = bucket["targets"]
        group_visible = bucket["visible"]
        assert isinstance(views, list)
        assert isinstance(targets, set)
        assert isinstance(group_visible, set)
        views.append(view.view_id)
        targets.update(view.target_ids)
        group_visible.update(visible)
    space_coverage: list[InteriorQASpaceCoverage] = []
    for (level_id, space_id), bucket in grouped.items():
        views = bucket["views"]
        targets = bucket["targets"]
        visible = bucket["visible"]
        assert isinstance(views, list)
        assert isinstance(targets, set)
        assert isinstance(visible, set)
        unseen = targets - visible
        space_coverage.append(
            InteriorQASpaceCoverage(
                level_id=level_id,
                space_id=space_id,
                view_ids=sorted(views),
                target_ids=sorted(targets),
                visible_target_ids=sorted(visible),
                unseen_target_ids=sorted(unseen),
                semantic_visibility_fraction=len(visible) / len(targets),
            )
        )
    target_ids = sorted(manifest.object_id_colors)
    return (
        view_coverage,
        sorted(
            space_coverage,
            key=lambda item: (item.level_id or "", item.space_id or ""),
        ),
        sorted(visible_overall),
        sorted(set(target_ids) - visible_overall),
    )


def _family_bounds(
    inventory: InteriorQASourceInventory,
) -> dict[str, InteriorQABounds]:
    """Reuse deterministic semantic bounds for overlap candidate inspection."""

    return _semantic_bounds(inventory)


def _positive_overlap_volume(
    first: InteriorQABounds,
    second: InteriorQABounds,
) -> float:
    """Return positive AABB intersection volume while treating touching faces as zero."""

    extents = [
        min(first.max[axis], second.max[axis])
        - max(first.min[axis], second.min[axis])
        for axis in range(3)
    ]
    if any(value <= 1e-6 for value in extents):
        return 0.0
    return extents[0] * extents[1] * extents[2]


def _structural_findings(
    inventory: InteriorQASourceInventory,
    *,
    run_relative: str,
    unseen_target_ids: list[str],
) -> tuple[list[InteriorQAFinding], list[InteriorQARevisionCandidate]]:
    """Convert topology, visibility, and conservative AABB overlap evidence into findings."""

    findings: list[InteriorQAFinding] = []
    candidates: list[InteriorQARevisionCandidate] = []
    inventory_evidence = f"{run_relative}/source_inventory.json"
    records_by_id: dict[str, list[InteriorQAObjectRecord]] = defaultdict(list)
    for record in inventory.objects:
        records_by_id[record.semantic_id].append(record)
        topology = record.topology
        if topology is None:
            continue
        critical = (
            topology.non_finite_vertex_count
            + topology.degenerate_face_count
            + topology.invalid_normal_face_count
            + topology.overused_edge_count
            + topology.loose_edge_count
            + topology.loose_vertex_count
        )
        if critical:
            finding_id = f"interior.topology.{safe_artifact_name(record.name)}"
            findings.append(
                InteriorQAFinding(
                    finding_id=finding_id,
                    category="topology",
                    severity="error",
                    target_ids=[record.semantic_id],
                    description=(
                        f"{record.name} has {critical} critical topology indicators "
                        "(non-finite, degenerate, invalid-normal, overused, or loose)."
                    ),
                    evidence_paths=[inventory_evidence],
                    measured_value=critical,
                    threshold=0,
                )
            )
            candidates.append(
                InteriorQARevisionCandidate(
                    candidate_id=f"candidate.{finding_id}",
                    finding_id=finding_id,
                    target_ids=[record.semantic_id],
                    action="repair_topology",
                    recommendation=(
                        "Repair the canonical geometry recipe for this semantic ID, then "
                        "rebuild and create a new interior QA plan."
                    ),
                    acceptance_criteria=[
                        "Critical topology counters are zero in a fresh source inventory.",
                        "InteriorScope and all unrelated semantic IDs remain unchanged.",
                    ],
                )
            )
        if topology.negative_determinant:
            findings.append(
                InteriorQAFinding(
                    finding_id=(
                        "interior.transform.negative."
                        + safe_artifact_name(record.name)
                    ),
                    category="topology",
                    severity="warning",
                    target_ids=[record.semantic_id],
                    description=f"{record.name} has a negative world transform determinant.",
                    evidence_paths=[inventory_evidence],
                )
            )
        if topology.boundary_edge_count:
            findings.append(
                InteriorQAFinding(
                    finding_id=(
                        "interior.boundary."
                        + safe_artifact_name(record.name)
                    ),
                    category="topology",
                    severity="info",
                    target_ids=[record.semantic_id],
                    description=(
                        f"{record.name} has {topology.boundary_edge_count} boundary edges. "
                        "Open architectural planes may be intentional."
                    ),
                    evidence_paths=[inventory_evidence],
                    measured_value=topology.boundary_edge_count,
                )
            )
    for target_id in unseen_target_ids:
        finding_id = f"interior.visibility.{safe_artifact_name(target_id)}"
        findings.append(
            InteriorQAFinding(
                finding_id=finding_id,
                category="visibility",
                severity="warning",
                target_ids=[target_id],
                description=(
                    "This approved semantic family was not visible in any generated "
                    "interior object-ID pass."
                ),
                evidence_paths=[inventory_evidence],
                measured_value=0,
                threshold=1,
            )
        )
        candidates.append(
            InteriorQARevisionCandidate(
                candidate_id=f"candidate.{finding_id}",
                finding_id=finding_id,
                target_ids=[target_id],
                action="review_occlusion",
                recommendation=(
                    "Review whether the object is intentionally hidden, incorrectly placed, "
                    "or needs a revised interior camera plan."
                ),
                acceptance_criteria=[
                    "The semantic ID is visible in at least one approved object-ID pass, "
                    "or its intentional occlusion is documented."
                ],
            )
        )
    bounds = _family_bounds(inventory)
    overlap_count = 0
    identifiers = sorted(bounds)
    for index, first_id in enumerate(identifiers):
        for second_id in identifiers[index + 1 :]:
            volume = _positive_overlap_volume(bounds[first_id], bounds[second_id])
            if volume <= 0:
                continue
            overlap_count += 1
            if overlap_count > 50:
                break
            finding_id = (
                f"interior.overlap.{safe_artifact_name(first_id)}."
                f"{safe_artifact_name(second_id)}"
            )
            findings.append(
                InteriorQAFinding(
                    finding_id=finding_id,
                    category="overlap",
                    severity="info",
                    target_ids=[first_id, second_id],
                    description=(
                        "Positive-volume world AABB overlap is advisory and does not prove "
                        "actual mesh intersection."
                    ),
                    evidence_paths=[inventory_evidence],
                    measured_value=round(volume, 9),
                    threshold=0,
                )
            )
            candidates.append(
                InteriorQARevisionCandidate(
                    candidate_id=f"candidate.{finding_id}",
                    finding_id=finding_id,
                    target_ids=[first_id, second_id],
                    action="review_overlap",
                    recommendation=(
                        "Inspect the wireframe and source geometry before changing either "
                        "semantic object; AABB overlap alone cannot authorize a revision."
                    ),
                    acceptance_criteria=[
                        "Visual inspection confirms either intentional contact or a corrected "
                        "mesh intersection."
                    ],
                )
            )
        if overlap_count > 50:
            break
    if overlap_count > 50:
        findings.append(
            InteriorQAFinding(
                finding_id="interior.overlap.truncated",
                category="overlap",
                severity="warning",
                description="AABB overlap findings were truncated at the bounded limit of 50.",
                evidence_paths=[inventory_evidence],
                measured_value=overlap_count,
                threshold=50,
            )
        )
    return findings, candidates


def _contact_sheet(
    manifest: InteriorQARenderManifest,
    manifest_path: Path,
    *,
    kind: str,
    output_path: Path,
) -> Path:
    """Compose labeled per-view evidence into one bounded human-review sheet."""

    selected: list[tuple[str, Path]] = []
    for view in manifest.views:
        record = next(item for item in view.passes if item.kind == kind)
        selected.append((view.view_id, _resolve_pass(manifest_path, record)))
    columns = min(3, len(selected))
    rows = math.ceil(len(selected) / columns)
    cell_width = 360
    image_height = 300
    label_height = 34
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * (image_height + label_height)),
        (245, 247, 250),
    )
    draw = ImageDraw.Draw(sheet)
    for index, (view_id, path) in enumerate(selected):
        with Image.open(path) as opened:
            image = ImageOps.contain(opened.convert("RGB"), (cell_width, image_height))
        x = (index % columns) * cell_width + (cell_width - image.width) // 2
        y = (index // columns) * (image_height + label_height)
        sheet.paste(image, (x, y))
        draw.text(
            ((index % columns) * cell_width + 8, y + image_height + 8),
            view_id,
            fill=(20, 33, 61),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


def run_job_interior_qa(
    job_id: str,
    run_id: str,
    *,
    approved_plan_sha256: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Consume one exact approval, render all views, and generate derived QA evidence."""

    if render_engine not in {"eevee", "cycles"}:
        raise ValueError("render_engine must be eevee or cycles")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    if render_engine == "eevee" and render_device != "auto":
        raise ValueError("render_device must be auto for eevee")
    root = job_dir(job_id)
    selected_run_id = _validate_run_id(run_id)
    run_dir = root / "qa" / "interior" / "runs" / selected_run_id
    plan_path = run_dir / "plan.json"
    approval_path = run_dir / "plan_approval.json"
    plan = _load_plan(plan_path)
    approval = _load_approval(approval_path)
    plan_hash = sha256_file(plan_path)
    if plan_hash != approved_plan_sha256:
        raise ValueError(
            "approved_plan_sha256 does not match the current immutable interior QA plan"
        )
    if approval.status != "approved":
        raise PermissionError("Interior QA plan approval has already been consumed")
    if approval.plan_sha256 != plan_hash:
        raise PermissionError("Interior QA approval does not match the selected plan")
    if approval.source_fingerprint != plan.source_fingerprint:
        raise PermissionError("Interior QA approval is stale for the selected sources")
    _require_current_plan_sources(root, plan)
    consumed = approval.model_copy(
        update={"status": "consumed", "consumed_at": _utc_now()}
    )
    write_json_atomic(approval_path, consumed.model_dump(mode="json"))
    consumed_approval_hash = sha256_file(approval_path)
    manifest_path = run_dir / "render_manifest.json"
    output_dir = run_dir
    from ..blender_artifact_runner import render_job_interior_qa

    manifest = render_job_interior_qa(
        job_id,
        plan_path=plan_path,
        approval_path=approval_path,
        output_dir=output_dir,
        manifest_path=manifest_path,
        render_engine=render_engine,
        render_device=render_device,
    )
    if manifest.job_id != job_id or manifest.run_id != selected_run_id:
        raise RuntimeError("Interior QA render manifest identity does not match the run")
    if manifest.plan_sha256 != plan_hash:
        raise RuntimeError("Interior QA render manifest plan hash does not match")
    if manifest.plan_approval_sha256 != consumed_approval_hash:
        raise RuntimeError("Interior QA render manifest approval hash does not match")
    expected_sources = {
        "scene_spec_sha256": plan.scene_spec_sha256,
        "build_fingerprint": plan.build_fingerprint,
        "interior_scope_sha256": plan.interior_scope_sha256,
        "interior_scope_approval_sha256": plan.interior_scope_approval_sha256,
    }
    stale_manifest_fields = [
        field
        for field, expected in expected_sources.items()
        if getattr(manifest, field) != expected
    ]
    if stale_manifest_fields:
        raise RuntimeError(
            "Interior QA render manifest has stale source bindings: "
            + ", ".join(stale_manifest_fields)
        )
    expected_view_ids = set(consumed.approved_view_ids)
    rendered_view_ids = {view.view_id for view in manifest.views}
    if rendered_view_ids != expected_view_ids:
        raise RuntimeError(
            "Interior QA render manifest does not contain the exact approved view set"
        )
    if set(manifest.object_id_colors) != set(plan.target_ids):
        raise RuntimeError(
            "Interior QA object-ID color map does not match the exact plan targets"
        )
    inventory_path = root / plan.source_inventory_path
    inventory = InteriorQASourceInventory.model_validate_json(
        inventory_path.read_text(encoding="utf-8")
    )
    (
        view_coverage,
        space_coverage,
        visible_target_ids,
        unseen_target_ids,
    ) = _coverage_from_manifest(manifest, manifest_path)
    run_relative = _job_relative(root, run_dir)
    findings, candidates = _structural_findings(
        inventory,
        run_relative=run_relative,
        unseen_target_ids=unseen_target_ids,
    )
    visibility_fraction = len(visible_target_ids) / len(plan.target_ids)
    has_errors = any(finding.severity == "error" for finding in findings)
    has_warnings = any(finding.severity == "warning" for finding in findings)
    status = "failed" if has_errors else "warning" if has_warnings else "passed"
    report = InteriorQAReport(
        job_id=job_id,
        run_id=selected_run_id,
        plan_sha256=plan_hash,
        render_manifest_sha256=sha256_file(manifest_path),
        source_inventory_sha256=sha256_file(inventory_path),
        status=status,  # type: ignore[arg-type]
        reference_comparison_status="unavailable",
        reference_comparison_note=(
            "No interior-specific calibrated reference set is mapped to these temporary "
            "views. This run reports semantic visibility and structural evidence only."
        ),
        semantic_visibility_fraction=visibility_fraction,
        target_ids=plan.target_ids,
        visible_target_ids=visible_target_ids,
        unseen_target_ids=unseen_target_ids,
        view_coverage=view_coverage,
        space_coverage=space_coverage,
        findings=findings,
        candidates=candidates,
        limitations=[
            "Semantic visibility is not surface-area coverage or a completion percentage.",
            "Positive-volume AABB overlap is advisory and does not prove mesh intersection.",
            "Boundary edges may be intentional for architectural planes.",
            "No interior reference similarity score is produced without mapped evidence.",
            "All revision candidates are manual-only and require a separate guarded change.",
        ],
        generated_at=_utc_now(),
    )
    report_path = run_dir / "interior_qa_report.json"
    write_json_atomic(report_path, report.model_dump(mode="json"))
    candidate_set = InteriorQARevisionCandidates(
        job_id=job_id,
        run_id=selected_run_id,
        report_sha256=sha256_file(report_path),
        candidates=candidates,
    )
    candidates_path = run_dir / "revision_candidates.json"
    write_json_atomic(candidates_path, candidate_set.model_dump(mode="json"))
    contact_sheets = [
        _contact_sheet(
            manifest,
            manifest_path,
            kind=kind,
            output_path=run_dir / "contact_sheets" / f"{kind}.png",
        )
        for kind in ("beauty", "object_id", "wireframe")
    ]
    latest = InteriorQALatest(
        job_id=job_id,
        run_id=selected_run_id,
        plan=_job_relative(root, plan_path),
        plan_sha256=plan_hash,
        approval=_job_relative(root, approval_path),
        approval_sha256=sha256_file(approval_path),
        source_inventory=_job_relative(root, inventory_path),
        render_manifest=_job_relative(root, manifest_path),
        report=_job_relative(root, report_path),
        revision_candidates=_job_relative(root, candidates_path),
        contact_sheets=[_job_relative(root, path) for path in contact_sheets],
    )
    latest_path = root / "qa" / "interior" / "latest.json"
    write_json_atomic(latest_path, latest.model_dump(mode="json"))
    return {
        "ok": report.status != "failed",
        "status": report.status,
        "job_id": job_id,
        "run_id": selected_run_id,
        "run_dir": str(run_dir),
        "plan_sha256": plan_hash,
        "approval_sha256": sha256_file(approval_path),
        "render_manifest": str(manifest_path),
        "report": str(report_path),
        "revision_candidates": str(candidates_path),
        "contact_sheets": [str(path) for path in contact_sheets],
        "view_count": len(manifest.views),
        "pass_count": len(manifest.views) * 7,
        "semantic_visibility_fraction": report.semantic_visibility_fraction,
        "unseen_target_ids": report.unseen_target_ids,
        "candidate_count": len(report.candidates),
        "reference_comparison_status": report.reference_comparison_status,
        "latest": str(latest_path),
        "pdf_scope": "qa",
    }


def get_job_interior_qa_status(job_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Reconstruct current plan, approval, render, report, and stale-source state."""

    root = job_dir(job_id)
    selected = run_id
    latest_path = root / "qa" / "interior" / "latest.json"
    if selected in {None, "latest"} and latest_path.is_file():
        latest = InteriorQALatest.model_validate_json(
            latest_path.read_text(encoding="utf-8")
        )
        selected = latest.run_id
    runs_root = root / "qa" / "interior" / "runs"
    if not selected:
        planned = sorted(
            path.name
            for path in runs_root.iterdir()
            if path.is_dir() and (path / "plan.json").is_file()
        ) if runs_root.is_dir() else []
        selected = planned[-1] if planned else None
    if selected is None:
        return {
            "job_id": job_id,
            "status": "not_planned",
            "run_id": None,
            "runs": [],
        }
    selected = _validate_run_id(selected)
    run_dir = runs_root / selected
    plan_path = run_dir / "plan.json"
    approval_path = run_dir / "plan_approval.json"
    manifest_path = run_dir / "render_manifest.json"
    report_path = run_dir / "interior_qa_report.json"
    stale = False
    stale_reason = None
    plan_hash = None
    if plan_path.is_file():
        plan = _load_plan(plan_path)
        plan_hash = sha256_file(plan_path)
        try:
            _require_current_plan_sources(root, plan)
        except (OSError, ValueError, RuntimeError) as exc:
            stale = True
            stale_reason = str(exc)
    approval_status = "missing"
    if approval_path.is_file():
        approval_status = _load_approval(approval_path).status
    if report_path.is_file():
        report = InteriorQAReport.model_validate_json(
            report_path.read_text(encoding="utf-8")
        )
        status = report.status
    elif manifest_path.is_file():
        status = "rendered_without_report"
    elif approval_status == "consumed":
        status = "execution_incomplete"
    elif approval_status == "approved":
        status = "approved"
    elif plan_path.is_file():
        status = "awaiting_approval"
    else:
        status = "incomplete"
    return {
        "job_id": job_id,
        "run_id": selected,
        "status": status,
        "stale": stale,
        "stale_reason": stale_reason,
        "plan": str(plan_path) if plan_path.is_file() else None,
        "plan_sha256": plan_hash,
        "approval": str(approval_path) if approval_path.is_file() else None,
        "approval_status": approval_status,
        "render_manifest": str(manifest_path) if manifest_path.is_file() else None,
        "report": str(report_path) if report_path.is_file() else None,
        "latest": str(latest_path) if latest_path.is_file() else None,
    }
