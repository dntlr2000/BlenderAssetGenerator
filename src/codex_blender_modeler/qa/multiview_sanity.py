"""Run immutable exterior assembly sanity diagnostics from five temporary cameras.

This module deliberately stays outside the canonical V0.6 fixed-camera QA run.  It
provides structural, multi-view evidence for spatial assembly contracts without
claiming reference-image similarity or mutating the authoring Blender scene.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from ..analysis.assembly import validate_assembly_prebuild_contract
from ..analysis.models import AssemblyFrame, ModelingPlan
from ..blender_artifacts import stable_json_digest, write_json_atomic
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..models import SceneSpec, StrictModel
from ..workspace import job_dir, load_job, resolve_metadata_path, sha256_file
from .camera_probe_service import artifact_publication_lease, write_json_exclusive
from .semantic_localizer import extract_semantic_bboxes

SHA256_PATTERN = r"^[0-9a-f]{64}$"
RUN_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,95}$"
_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:")

AssemblySanityViewId = Literal["front", "right", "top", "rear", "oblique"]
AssemblySanityPassKind = Literal["beauty", "silhouette", "object_id", "wireframe"]
ASSEMBLY_SANITY_VIEW_IDS: tuple[AssemblySanityViewId, ...] = (
    "front",
    "right",
    "top",
    "rear",
    "oblique",
)
ASSEMBLY_SANITY_PASS_KINDS: tuple[AssemblySanityPassKind, ...] = (
    "beauty",
    "silhouette",
    "object_id",
    "wireframe",
)


def _utc_now() -> str:
    """Return one timezone-aware timestamp for immutable diagnostic evidence."""

    return datetime.now(UTC).isoformat()


def _new_run_id() -> str:
    """Create a portable lowercase run identifier for one diagnostic execution."""

    stamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz").lower()
    return f"assembly-sanity-{stamp}-{uuid4().hex[:8]}"


def _validate_run_id(value: str) -> str:
    """Reject identifiers that cannot safely become one run-owned directory name."""

    if not re.fullmatch(RUN_ID_PATTERN, value):
        raise ValueError("run_id must match [a-z0-9][a-z0-9._-]{0,95}")
    return value


def _validate_job_relative_path(value: str) -> str:
    """Require a normalized POSIX path contained by the owning job workspace."""

    if (
        not value
        or "\x00" in value
        or "\\" in value
        or value.startswith("/")
        or _ABSOLUTE_WINDOWS_PATH.match(value)
    ):
        raise ValueError("path must be a non-empty POSIX job-relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    return value


def _job_relative(root: Path, path: Path) -> str:
    """Convert one resolved artifact to a strict job-relative POSIX path."""

    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact is outside the owning job workspace: {resolved}") from exc


def _resolve_job_relative(root: Path, value: str) -> Path:
    """Resolve a validated job-relative path without permitting directory escape."""

    relative = _validate_job_relative_path(value)
    resolved_root = root.expanduser().resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes the owning job: {value}") from exc
    return resolved


def _axis_vector(axis: str, sign: float = 1.0) -> tuple[float, float, float]:
    """Map one declared assembly axis to a signed root-frame unit vector."""

    index = {"X": 0, "Y": 1, "Z": 2}[axis]
    values = [0.0, 0.0, 0.0]
    values[index] = float(sign)
    return tuple(values)  # type: ignore[return-value]


def _normalized_sum(*vectors: tuple[float, float, float]) -> tuple[float, float, float]:
    """Normalize a deterministic sum of assembly-frame direction vectors."""

    values = tuple(sum(vector[index] for vector in vectors) for index in range(3))
    length = math.sqrt(sum(value * value for value in values))
    if length <= 1e-12:
        raise ValueError("assembly sanity direction sum is empty")
    return tuple(value / length for value in values)  # type: ignore[return-value]


class AssemblySanityReferenceSource(StrictModel):
    """Bind one immutable user source without claiming it matches a diagnostic view."""

    kind: str
    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Keep source evidence inside the job using portable relative paths."""

        return _validate_job_relative_path(value)


class AssemblySanityViewPlan(StrictModel):
    """Describe one assembly-frame camera direction for a structural diagnostic."""

    view_id: AssemblySanityViewId
    camera_direction_frame: tuple[float, float, float]
    screen_up_role: Literal["vertical", "longitudinal"]
    target_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_direction_and_targets(self) -> AssemblySanityViewPlan:
        """Reject an empty direction or duplicated semantic targets."""

        if math.sqrt(sum(value * value for value in self.camera_direction_frame)) <= 1e-9:
            raise ValueError("assembly sanity camera direction cannot be empty")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("assembly sanity target IDs must be unique")
        return self


class AssemblySanityPlan(StrictModel):
    """Freeze exact canonical sources and five assembly-frame diagnostic views."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    diagnostic_kind: Literal["assembly_multiview_sanity"] = "assembly_multiview_sanity"
    canonical_v06_qa_run: Literal[False] = False
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    scene_spec_path: str
    scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    modeling_plan_path: str
    modeling_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    source_blend_path: str
    source_blend_sha256: str = Field(pattern=SHA256_PATTERN)
    build_fingerprint: str = Field(pattern=SHA256_PATTERN)
    source_fingerprint: str = Field(pattern=SHA256_PATTERN)
    assembly_frame: AssemblyFrame
    target_ids: list[str] = Field(min_length=2)
    resolution: tuple[int, int]
    views: list[AssemblySanityViewPlan] = Field(min_length=5, max_length=5)
    reference_sources: list[AssemblySanityReferenceSource] = Field(default_factory=list)
    reference_comparison_mode: Literal["structural_only"] = "structural_only"
    created_at: str
    limitations: list[str] = Field(default_factory=list)

    @field_validator("scene_spec_path", "modeling_plan_path", "source_blend_path")
    @classmethod
    def validate_artifact_path(cls, value: str) -> str:
        """Keep every canonical source reference job-relative and portable."""

        return _validate_job_relative_path(value)

    @model_validator(mode="after")
    def validate_plan(self) -> AssemblySanityPlan:
        """Require the exact view set, bounded resolution, and stable target membership."""

        width, height = self.resolution
        if width < 128 or height < 128 or width > 1024 or height > 1024:
            raise ValueError("assembly sanity resolution must be within [128, 1024]")
        view_ids = [view.view_id for view in self.views]
        if tuple(view_ids) != ASSEMBLY_SANITY_VIEW_IDS:
            raise ValueError("assembly sanity plan requires front/right/top/rear/oblique order")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("assembly sanity plan target IDs must be unique")
        allowed = set(self.target_ids)
        if any(set(view.target_ids) != allowed for view in self.views):
            raise ValueError("every assembly sanity view must bind the exact target set")
        return self


class AssemblySanityPassRecord(StrictModel):
    """Bind one diagnostic render image to its exact job-relative path and hash."""

    kind: AssemblySanityPassKind
    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    encoding: Literal["png-rgb8"] = "png-rgb8"

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Keep every render artifact inside the owning job workspace."""

        return _validate_job_relative_path(value)


class AssemblySanityViewRender(StrictModel):
    """Record the actual temporary camera and four structural passes for one view."""

    view_id: AssemblySanityViewId
    camera: dict[str, Any]
    target_ids: list[str] = Field(min_length=1)
    passes: list[AssemblySanityPassRecord] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_pass_set(self) -> AssemblySanityViewRender:
        """Require the exact diagnostic pass set without impersonating V0.6 QA."""

        kinds = tuple(record.kind for record in self.passes)
        if kinds != ASSEMBLY_SANITY_PASS_KINDS:
            raise ValueError("assembly sanity view requires four ordered diagnostic passes")
        return self


class AssemblySanityRenderManifest(StrictModel):
    """Bind temporary-camera renders to exact source, plan, and Blender evidence."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    diagnostic_kind: Literal["assembly_multiview_sanity"] = "assembly_multiview_sanity"
    canonical_v06_qa_run: Literal[False] = False
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    modeling_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    source_blend_path: str
    source_blend_sha256: str = Field(pattern=SHA256_PATTERN)
    build_fingerprint: str = Field(pattern=SHA256_PATTERN)
    blender_version: str
    render_engine: str
    render_device: str
    resolution: tuple[int, int]
    object_id_colors: dict[str, str]
    assembly_frame_bounds: dict[str, list[float]]
    assembly_evaluation: dict[str, Any]
    views: list[AssemblySanityViewRender] = Field(min_length=5, max_length=5)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("source_blend_path")
    @classmethod
    def validate_blend_path(cls, value: str) -> str:
        """Keep the source blend reference portable and job-relative."""

        return _validate_job_relative_path(value)

    @model_validator(mode="after")
    def validate_manifest(self) -> AssemblySanityRenderManifest:
        """Require exact ordered views and one consistent diagnostic resolution."""

        if tuple(view.view_id for view in self.views) != ASSEMBLY_SANITY_VIEW_IDS:
            raise ValueError("assembly sanity render manifest has an incomplete view set")
        for view in self.views:
            for record in view.passes:
                if (record.width, record.height) != self.resolution:
                    raise ValueError("assembly sanity pass resolution differs from manifest")
        return self


class AssemblySanityViewCoverage(StrictModel):
    """Report exact object-ID visibility for one temporary diagnostic camera."""

    view_id: AssemblySanityViewId
    visible_target_ids: list[str]
    unseen_target_ids: list[str]
    semantic_visibility_fraction: float = Field(ge=0, le=1)


class AssemblySanityFinding(StrictModel):
    """Describe one structural relation, visibility, or reference limitation."""

    finding_id: str
    category: Literal["assembly_relation", "visibility", "reference", "render"]
    severity: Literal["info", "warning", "error"]
    target_ids: list[str] = Field(default_factory=list)
    view_ids: list[AssemblySanityViewId] = Field(default_factory=list)
    description: str
    evidence_paths: list[str] = Field(default_factory=list)

    @field_validator("evidence_paths")
    @classmethod
    def validate_evidence_paths(cls, values: list[str]) -> list[str]:
        """Keep finding evidence portable and contained by the job workspace."""

        return [_validate_job_relative_path(value) for value in values]


class AssemblySanityReport(StrictModel):
    """Summarize structural multi-view evidence without claiming image similarity."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    diagnostic_kind: Literal["assembly_multiview_sanity"] = "assembly_multiview_sanity"
    canonical_v06_qa_run: Literal[False] = False
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    render_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    modeling_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    source_blend_sha256: str = Field(pattern=SHA256_PATTERN)
    build_fingerprint: str = Field(pattern=SHA256_PATTERN)
    structural_status: Literal["passed", "warning", "failed"]
    reference_comparison_status: Literal["unscorable"] = "unscorable"
    reference_comparison_note: str
    quality_claimed: Literal[False] = False
    target_ids: list[str] = Field(min_length=2)
    visible_target_ids: list[str]
    unseen_target_ids: list[str]
    semantic_visibility_fraction: float = Field(ge=0, le=1)
    view_coverage: list[AssemblySanityViewCoverage] = Field(min_length=5, max_length=5)
    assembly_evaluation: dict[str, Any]
    findings: list[AssemblySanityFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: str

    @model_validator(mode="after")
    def validate_report(self) -> AssemblySanityReport:
        """Require visibility partitioning and fail structural errors closed."""

        targets = set(self.target_ids)
        visible = set(self.visible_target_ids)
        unseen = set(self.unseen_target_ids)
        if visible.intersection(unseen) or visible.union(unseen) != targets:
            raise ValueError("visible and unseen assembly targets must partition target_ids")
        has_error = any(item.severity == "error" for item in self.findings)
        if has_error and self.structural_status != "failed":
            raise ValueError("assembly sanity reports with errors must be failed")
        return self


def _reference_sources(root: Path, metadata: dict[str, Any]) -> list[AssemblySanityReferenceSource]:
    """Collect immutable job inputs while rejecting missing or changed source evidence."""

    records: list[AssemblySanityReferenceSource] = []
    for item in metadata.get("sources", []):
        path = resolve_metadata_path(str(item["path"]))
        if not path.is_file():
            raise FileNotFoundError(f"assembly sanity source is missing: {path}")
        actual = sha256_file(path)
        if actual != item.get("sha256"):
            raise RuntimeError(f"assembly sanity source changed: {item.get('kind')}")
        records.append(
            AssemblySanityReferenceSource(
                kind=str(item.get("kind", "unknown")),
                path=_job_relative(root, path),
                sha256=actual,
            )
        )
    return records


def _view_plan(plan: ModelingPlan, target_ids: list[str]) -> list[AssemblySanityViewPlan]:
    """Create front, right, top, rear, and oblique cameras from declared asset axes."""

    frame = plan.assembly_frame
    if frame is None:
        raise ValueError("assembly sanity requires one declared assembly frame")
    longitudinal = _axis_vector(frame.longitudinal_axis)
    lateral = _axis_vector(frame.lateral_axis)
    vertical = _axis_vector(frame.vertical_axis)
    directions: tuple[
        tuple[
            AssemblySanityViewId,
            tuple[float, float, float],
            Literal["vertical", "longitudinal"],
        ],
        ...,
    ] = (
        ("front", longitudinal, "vertical"),
        ("right", lateral, "vertical"),
        ("top", vertical, "longitudinal"),
        ("rear", tuple(-value for value in longitudinal), "vertical"),
        ("oblique", _normalized_sum(longitudinal, lateral, vertical), "vertical"),
    )
    return [
        AssemblySanityViewPlan(
            view_id=view_id,
            camera_direction_frame=direction,
            screen_up_role=up_role,
            target_ids=target_ids,
        )
        for view_id, direction, up_role in directions
    ]


def plan_job_assembly_multiview_sanity(
    job_id: str,
    *,
    run_id: str | None = None,
    resolution: int = 384,
) -> dict[str, Any]:
    """Write one immutable five-view plan bound to a fresh spatial assembly build."""

    root = job_dir(job_id)
    metadata = load_job(job_id)
    scene_path = root / "analysis" / "scene_spec.json"
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    blend_path = root / "blender" / "scene.blend"
    for label, path in (
        ("SceneSpec", scene_path),
        ("ModelingPlan", modeling_plan_path),
        ("authoring blend", blend_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")
    scene_spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    modeling_plan = ModelingPlan.model_validate_json(
        modeling_plan_path.read_text(encoding="utf-8")
    )
    if modeling_plan.assembly_consistency_policy != "spatial_v1":
        raise ValueError("assembly multi-view sanity requires spatial_v1 ModelingPlan evidence")
    if modeling_plan.stage != "authored" or modeling_plan.assembly_frame is None:
        raise ValueError("assembly multi-view sanity requires an authored assembly frame")
    contract = validate_assembly_prebuild_contract(modeling_plan, scene_spec)
    if not contract.ok:
        failures = "; ".join(
            item.message for item in contract.checks if item.status == "failed"
        )
        raise ValueError(f"assembly contract is invalid: {failures}")
    target_ids = sorted(
        item.id
        for item in modeling_plan.objects
        if item.assembly_role in {"root", "attached"}
    )
    if len(target_ids) < 2 or not any(
        item.assembly_role == "attached" for item in modeling_plan.objects
    ):
        raise ValueError("assembly multi-view sanity requires a root and attached component")
    provenance = collect_build_provenance(root, job_id, scene_spec_path=scene_path)
    selected_run_id = _validate_run_id(run_id or _new_run_id())
    run_dir = root / "qa" / "assembly_sanity" / "runs" / selected_run_id
    if run_dir.exists():
        raise FileExistsError(f"assembly sanity run already exists: {selected_run_id}")
    sources = _reference_sources(root, metadata)
    source_payload = {
        "job_id": job_id,
        "scene_spec_sha256": sha256_file(scene_path),
        "modeling_plan_sha256": sha256_file(modeling_plan_path),
        "source_blend_sha256": sha256_file(blend_path),
        "build_fingerprint": provenance["fingerprint"],
        "reference_sources": [item.model_dump(mode="json") for item in sources],
    }
    plan = AssemblySanityPlan(
        job_id=job_id,
        run_id=selected_run_id,
        scene_spec_path=_job_relative(root, scene_path),
        scene_spec_sha256=source_payload["scene_spec_sha256"],
        modeling_plan_path=_job_relative(root, modeling_plan_path),
        modeling_plan_sha256=source_payload["modeling_plan_sha256"],
        source_blend_path=_job_relative(root, blend_path),
        source_blend_sha256=source_payload["source_blend_sha256"],
        build_fingerprint=str(provenance["fingerprint"]),
        source_fingerprint=stable_json_digest(source_payload),
        assembly_frame=modeling_plan.assembly_frame.model_dump(mode="json"),
        target_ids=target_ids,
        resolution=(resolution, resolution),
        views=_view_plan(modeling_plan, target_ids),
        reference_sources=sources,
        created_at=_utc_now(),
        limitations=[
            "This is a structural multi-view diagnostic, not a canonical V0.6 QA run.",
            "Temporary cameras do not modify or save the authoring Blender file.",
            "Reference similarity is unscored unless a separate calibrated comparison is run.",
            "Bounding-box assembly checks are broad evidence, not triangle-level clearance proof.",
        ],
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    plan_path = run_dir / "plan.json"
    write_json_atomic(plan_path, plan.model_dump(mode="json"))
    return {
        "job_id": job_id,
        "run_id": selected_run_id,
        "status": "planned",
        "plan": str(plan_path),
        "plan_sha256": sha256_file(plan_path),
        "view_ids": list(ASSEMBLY_SANITY_VIEW_IDS),
        "canonical_v06_qa_run": False,
    }


def _require_current_sources(root: Path, plan: AssemblySanityPlan) -> dict[str, Any]:
    """Re-hash and re-derive every canonical input before diagnostic rendering."""

    scene_path = _resolve_job_relative(root, plan.scene_spec_path)
    modeling_plan_path = _resolve_job_relative(root, plan.modeling_plan_path)
    blend_path = _resolve_job_relative(root, plan.source_blend_path)
    for path, expected, label in (
        (scene_path, plan.scene_spec_sha256, "SceneSpec"),
        (modeling_plan_path, plan.modeling_plan_sha256, "ModelingPlan"),
        (blend_path, plan.source_blend_sha256, "authoring blend"),
    ):
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"assembly sanity {label} is stale or changed")
    for source in plan.reference_sources:
        path = _resolve_job_relative(root, source.path)
        if not path.is_file() or sha256_file(path) != source.sha256:
            raise RuntimeError(f"assembly sanity reference source changed: {source.kind}")
    provenance = collect_build_provenance(root, plan.job_id, scene_spec_path=scene_path)
    if provenance["fingerprint"] != plan.build_fingerprint:
        raise RuntimeError("assembly sanity build fingerprint is stale")
    source_payload = {
        "job_id": plan.job_id,
        "scene_spec_sha256": plan.scene_spec_sha256,
        "modeling_plan_sha256": plan.modeling_plan_sha256,
        "source_blend_sha256": plan.source_blend_sha256,
        "build_fingerprint": plan.build_fingerprint,
        "reference_sources": [
            item.model_dump(mode="json") for item in plan.reference_sources
        ],
    }
    if stable_json_digest(source_payload) != plan.source_fingerprint:
        raise RuntimeError("assembly sanity source fingerprint is internally inconsistent")
    scene_spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    modeling_plan = ModelingPlan.model_validate_json(
        modeling_plan_path.read_text(encoding="utf-8")
    )
    contract = validate_assembly_prebuild_contract(modeling_plan, scene_spec)
    if not contract.ok:
        raise RuntimeError("assembly sanity current assembly contract is invalid")
    expected_targets = sorted(
        item.id
        for item in modeling_plan.objects
        if item.assembly_role in {"root", "attached"}
    )
    if (
        modeling_plan.assembly_consistency_policy != "spatial_v1"
        or modeling_plan.stage != "authored"
        or modeling_plan.assembly_frame is None
        or modeling_plan.assembly_frame != plan.assembly_frame
        or expected_targets != plan.target_ids
        or _view_plan(modeling_plan, expected_targets) != plan.views
    ):
        raise RuntimeError(
            "assembly sanity plan no longer matches the current authored assembly model"
        )
    return provenance


def _require_exact_plan(path: Path, expected_sha256: str) -> None:
    """Reject a missing or mutated immutable assembly-sanity plan."""

    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise RuntimeError("assembly sanity plan is missing or changed")


def _validate_render_artifacts(
    root: Path,
    plan: AssemblySanityPlan,
    plan_sha256: str,
    manifest: AssemblySanityRenderManifest,
) -> None:
    """Validate manifest bindings and every diagnostic image before reporting."""

    expected = (
        manifest.job_id == plan.job_id
        and manifest.run_id == plan.run_id
        and manifest.plan_sha256 == plan_sha256
        and manifest.scene_spec_sha256 == plan.scene_spec_sha256
        and manifest.modeling_plan_sha256 == plan.modeling_plan_sha256
        and manifest.source_blend_sha256 == plan.source_blend_sha256
        and manifest.build_fingerprint == plan.build_fingerprint
        and manifest.source_blend_path == plan.source_blend_path
        and manifest.resolution == plan.resolution
    )
    if not expected:
        raise RuntimeError("assembly sanity render manifest is not bound to the exact plan")
    if sorted(manifest.object_id_colors) != plan.target_ids or len(
        set(manifest.object_id_colors.values())
    ) != len(plan.target_ids):
        raise RuntimeError("assembly sanity object-ID color membership changed")
    if any(
        re.fullmatch(r"#[0-9a-f]{6}", color) is None
        for color in manifest.object_id_colors.values()
    ):
        raise RuntimeError("assembly sanity object-ID color encoding is invalid")
    for view, planned_view in zip(manifest.views, plan.views, strict=True):
        if view.target_ids != plan.target_ids or planned_view.target_ids != plan.target_ids:
            raise RuntimeError(f"assembly sanity target set changed in view {view.view_id}")
        _validate_assembly_camera_record(view.camera, planned_view)
        for record in view.passes:
            path = _resolve_job_relative(root, record.path)
            expected_path = (
                root
                / "qa"
                / "assembly_sanity"
                / "runs"
                / plan.run_id
                / "views"
                / view.view_id
                / f"{record.kind}.png"
            ).resolve()
            if path != expected_path:
                raise RuntimeError(
                    f"assembly sanity pass path changed: {view.view_id}/{record.kind}"
                )
            if not path.is_file() or sha256_file(path) != record.sha256:
                raise RuntimeError(
                    f"assembly sanity pass is missing or changed: {view.view_id}/{record.kind}"
                )


def _validate_assembly_camera_record(
    camera: dict[str, Any],
    planned_view: AssemblySanityViewPlan,
) -> None:
    """Bind one actual temporary camera to the exact planned frame direction and view."""

    expected_direction = [round(float(value), 9) for value in planned_view.camera_direction_frame]
    if (
        camera.get("view_id") != planned_view.view_id
        or camera.get("camera_direction_frame") != expected_direction
        or camera.get("screen_up_role") != planned_view.screen_up_role
        or camera.get("type") != "PERSP"
    ):
        raise RuntimeError(
            f"assembly sanity camera differs from planned view {planned_view.view_id}"
        )
    for field in ("location", "rotation_deg", "target"):
        values = camera.get(field)
        if (
            not isinstance(values, list)
            or len(values) != 3
            or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)
        ):
            raise RuntimeError(
                f"assembly sanity camera {planned_view.view_id} has invalid {field}"
            )
    numeric = [camera.get("lens_mm"), camera.get("clip_start"), camera.get("clip_end")]
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in numeric):
        raise RuntimeError(
            f"assembly sanity camera {planned_view.view_id} has invalid lens or clipping"
        )
    if float(numeric[0]) <= 0 or float(numeric[1]) <= 0 or float(numeric[2]) <= float(numeric[1]):
        raise RuntimeError(
            f"assembly sanity camera {planned_view.view_id} has unsafe lens or clipping"
        )


def _has_strict_terminal_camera_contract(
    manifest: AssemblySanityRenderManifest,
) -> bool:
    """Identify post-hardening manifests that recorded the complete generated camera."""

    required = {
        "view_id",
        "camera_direction_frame",
        "screen_up_role",
        "type",
        "location",
        "rotation_deg",
        "target",
        "lens_mm",
        "clip_start",
        "clip_end",
    }
    return all(required.issubset(view.camera) for view in manifest.views)


def _validate_legacy_render_artifacts(
    root: Path,
    plan: AssemblySanityPlan,
    plan_sha256: str,
    manifest: AssemblySanityRenderManifest,
) -> None:
    """Keep historical structural evidence readable while rechecking its exact file hashes."""

    expected = (
        manifest.job_id == plan.job_id
        and manifest.run_id == plan.run_id
        and manifest.plan_sha256 == plan_sha256
        and manifest.scene_spec_sha256 == plan.scene_spec_sha256
        and manifest.modeling_plan_sha256 == plan.modeling_plan_sha256
        and manifest.source_blend_sha256 == plan.source_blend_sha256
        and manifest.build_fingerprint == plan.build_fingerprint
        and manifest.source_blend_path == plan.source_blend_path
        and manifest.resolution == plan.resolution
    )
    if not expected:
        raise RuntimeError("legacy assembly sanity manifest is not bound to its exact plan")
    for view, planned_view in zip(manifest.views, plan.views, strict=True):
        if view.view_id != planned_view.view_id or view.target_ids != plan.target_ids:
            raise RuntimeError("legacy assembly sanity view membership changed")
        for record in view.passes:
            path = _resolve_job_relative(root, record.path)
            if not path.is_file() or sha256_file(path) != record.sha256:
                raise RuntimeError(
                    f"legacy assembly sanity pass is missing or changed: "
                    f"{view.view_id}/{record.kind}"
                )


def _coverage_and_findings(
    root: Path,
    plan: AssemblySanityPlan,
    manifest: AssemblySanityRenderManifest,
) -> tuple[list[AssemblySanityViewCoverage], list[AssemblySanityFinding]]:
    """Measure semantic visibility and translate runtime assembly checks to findings."""

    coverage: list[AssemblySanityViewCoverage] = []
    findings: list[AssemblySanityFinding] = []
    visible_union: set[str] = set()
    target_set = set(plan.target_ids)
    for view in manifest.views:
        object_pass = next(record for record in view.passes if record.kind == "object_id")
        bboxes = extract_semantic_bboxes(
            _resolve_job_relative(root, object_pass.path),
            manifest.object_id_colors,
        )
        visible = sorted(target for target in plan.target_ids if bboxes.get(target) is not None)
        unseen = sorted(target_set - set(visible))
        visible_union.update(visible)
        coverage.append(
            AssemblySanityViewCoverage(
                view_id=view.view_id,
                visible_target_ids=visible,
                unseen_target_ids=unseen,
                semantic_visibility_fraction=len(visible) / len(plan.target_ids),
            )
        )
        if unseen:
            findings.append(
                AssemblySanityFinding(
                    finding_id=f"visibility.{view.view_id}",
                    category="visibility",
                    severity="warning",
                    target_ids=unseen,
                    view_ids=[view.view_id],
                    description=(
                        "Some assembly targets are not visible from this diagnostic view; "
                        "review occlusion or placement using the other views."
                    ),
                    evidence_paths=[object_pass.path],
                )
            )
    never_visible = sorted(target_set - visible_union)
    if never_visible:
        findings.append(
            AssemblySanityFinding(
                finding_id="visibility.all_views",
                category="visibility",
                severity="error",
                target_ids=never_visible,
                view_ids=list(ASSEMBLY_SANITY_VIEW_IDS),
                description="Assembly targets are absent from every object-ID diagnostic view.",
                evidence_paths=[
                    record.path
                    for view in manifest.views
                    for record in view.passes
                    if record.kind == "object_id"
                ],
            )
        )
    for index, check in enumerate(manifest.assembly_evaluation.get("checks", [])):
        status = str(check.get("status", "warning"))
        if status == "passed":
            continue
        target_ids = [
            str(check[key])
            for key in ("subject_id", "reference_id", "peer_id")
            if check.get(key)
        ]
        findings.append(
            AssemblySanityFinding(
                finding_id=f"assembly_relation.{index}",
                category="assembly_relation",
                severity="error" if status == "failed" else "warning",
                target_ids=sorted(set(target_ids)),
                description=str(check.get("message", "Assembly relation needs review.")),
            )
        )
    findings.append(
        AssemblySanityFinding(
            finding_id="reference.structural_only",
            category="reference",
            severity="info",
            description=(
                "This diagnostic has no calibrated per-view reference comparison and "
                "therefore cannot produce a reference-similarity score."
            ),
        )
    )
    return coverage, findings


def validate_assembly_sanity_terminal(
    root: Path,
    *,
    plan_path: Path,
    plan_sha256: str,
    manifest_path: Path,
    manifest_sha256: str,
    report_path: Path,
    report_sha256: str,
    expected_job_id: str | None = None,
    expected_run_id: str | None = None,
) -> tuple[AssemblySanityPlan, AssemblySanityRenderManifest, AssemblySanityReport]:
    """Replay immutable five-view generation evidence without consulting mutable latest data."""

    resolved_root = root.expanduser().resolve()
    resolved_plan = plan_path.expanduser().resolve()
    resolved_manifest = manifest_path.expanduser().resolve()
    resolved_report = report_path.expanduser().resolve()
    for path, expected, label in (
        (resolved_plan, plan_sha256, "plan"),
        (resolved_manifest, manifest_sha256, "render manifest"),
        (resolved_report, report_sha256, "report"),
    ):
        _job_relative(resolved_root, path)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"assembly sanity terminal {label} is missing or changed")
    plan = AssemblySanityPlan.model_validate_json(resolved_plan.read_text(encoding="utf-8"))
    run_root = (
        resolved_root / "qa" / "assembly_sanity" / "runs" / plan.run_id
    ).resolve()
    if (
        resolved_plan != run_root / "plan.json"
        or resolved_manifest != run_root / "render_manifest.json"
        or resolved_report != run_root / "report.json"
    ):
        raise ValueError("assembly sanity terminal artifacts are outside their exact run")
    manifest = AssemblySanityRenderManifest.model_validate_json(
        resolved_manifest.read_text(encoding="utf-8")
    )
    report = AssemblySanityReport.model_validate_json(
        resolved_report.read_text(encoding="utf-8")
    )
    if (
        (expected_job_id is not None and plan.job_id != expected_job_id)
        or (expected_run_id is not None and plan.run_id != expected_run_id)
        or manifest.job_id != plan.job_id
        or report.job_id != plan.job_id
        or manifest.run_id != plan.run_id
        or report.run_id != plan.run_id
        or manifest.plan_sha256 != plan_sha256
        or report.plan_sha256 != plan_sha256
        or report.render_manifest_sha256 != manifest_sha256
    ):
        raise ValueError("assembly sanity terminal identity or hash binding is invalid")
    if not _has_strict_terminal_camera_contract(manifest):
        _validate_legacy_render_artifacts(
            resolved_root,
            plan,
            plan_sha256,
            manifest,
        )
        if (
            report.scene_spec_sha256 != plan.scene_spec_sha256
            or report.modeling_plan_sha256 != plan.modeling_plan_sha256
            or report.source_blend_sha256 != plan.source_blend_sha256
            or report.build_fingerprint != plan.build_fingerprint
            or report.target_ids != plan.target_ids
            or report.assembly_evaluation != manifest.assembly_evaluation
        ):
            raise ValueError("legacy assembly sanity terminal provenance changed")
        return plan, manifest, report
    _validate_render_artifacts(resolved_root, plan, plan_sha256, manifest)
    expected_coverage, expected_findings = _coverage_and_findings(
        resolved_root,
        plan,
        manifest,
    )
    visible = sorted(
        {
            target
            for coverage in expected_coverage
            for target in coverage.visible_target_ids
        }
    )
    unseen = sorted(set(plan.target_ids) - set(visible))
    expected_status: Literal["passed", "warning", "failed"]
    if any(item.severity == "error" for item in expected_findings):
        expected_status = "failed"
    elif any(item.severity == "warning" for item in expected_findings):
        expected_status = "warning"
    else:
        expected_status = "passed"
    expected_fraction = len(visible) / len(plan.target_ids)
    provenance_matches = (
        report.scene_spec_sha256 == plan.scene_spec_sha256
        and report.modeling_plan_sha256 == plan.modeling_plan_sha256
        and report.source_blend_sha256 == plan.source_blend_sha256
        and report.build_fingerprint == plan.build_fingerprint
        and manifest.scene_spec_sha256 == plan.scene_spec_sha256
        and manifest.modeling_plan_sha256 == plan.modeling_plan_sha256
        and manifest.source_blend_sha256 == plan.source_blend_sha256
        and manifest.build_fingerprint == plan.build_fingerprint
    )
    if not provenance_matches:
        raise ValueError("assembly sanity terminal generation provenance changed")
    if (
        report.target_ids != plan.target_ids
        or report.visible_target_ids != visible
        or report.unseen_target_ids != unseen
        or not math.isclose(
            report.semantic_visibility_fraction,
            expected_fraction,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or report.view_coverage != expected_coverage
        or report.assembly_evaluation != manifest.assembly_evaluation
        or report.findings != expected_findings
        or report.structural_status != expected_status
    ):
        raise ValueError("assembly sanity terminal report differs from rendered evidence")
    return plan, manifest, report


def run_job_assembly_multiview_sanity(
    job_id: str,
    run_id: str,
    *,
    plan_sha256: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Serialize one run-owned assembly diagnostic and reject concurrent publishers."""

    selected_run_id = _validate_run_id(run_id)
    root = job_dir(job_id)
    run_dir = root / "qa" / "assembly_sanity" / "runs" / selected_run_id
    with artifact_publication_lease(
        run_dir,
        owner_kind="assembly_multiview_sanity",
        owner_id=selected_run_id,
    ):
        return _run_job_assembly_multiview_sanity_locked(
            job_id,
            selected_run_id,
            plan_sha256=plan_sha256,
            render_engine=render_engine,
            render_device=render_device,
        )


def _run_job_assembly_multiview_sanity_locked(
    job_id: str,
    run_id: str,
    *,
    plan_sha256: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Run one exact-hash structural plan while its publication lease is held."""

    selected_run_id = _validate_run_id(run_id)
    root = job_dir(job_id)
    run_dir = root / "qa" / "assembly_sanity" / "runs" / selected_run_id
    plan_path = run_dir / "plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"assembly sanity plan is missing: {plan_path}")
    plan = AssemblySanityPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    if plan.job_id != job_id or plan.run_id != selected_run_id:
        raise ValueError("assembly sanity plan identity does not match the requested run")
    current_plan_sha256 = sha256_file(plan_path)
    if current_plan_sha256 != plan_sha256:
        raise RuntimeError(
            "assembly sanity plan SHA-256 differs from the caller-supplied reviewed value"
        )
    _require_current_sources(root, plan)
    manifest_path = run_dir / "render_manifest.json"
    report_path = run_dir / "report.json"
    views_dir = run_dir / "views"
    if manifest_path.exists() or report_path.exists() or views_dir.exists():
        raise FileExistsError(
            "assembly sanity run already has derived output; use a new immutable run_id"
        )
    args = [
        "--job-root",
        str(root),
        "--plan",
        str(plan_path),
        "--plan-sha256",
        current_plan_sha256,
        "--manifest",
        str(manifest_path),
        "--output-dir",
        str(views_dir),
        "--scene-spec",
        str(_resolve_job_relative(root, plan.scene_spec_path)),
        "--build-fingerprint",
        plan.build_fingerprint,
        "--render-engine",
        render_engine,
        "--render-device",
        render_device,
    ]
    try:
        run_blender(
            "render_assembly_sanity.py",
            args,
            blend_file=_resolve_job_relative(root, plan.source_blend_path),
        )
    except Exception:
        try:
            _require_exact_plan(plan_path, plan_sha256)
            _require_current_sources(root, plan)
        except Exception as source_exc:
            raise RuntimeError(
                "assembly sanity source changed while Blender failed"
            ) from source_exc
        raise
    _require_exact_plan(plan_path, plan_sha256)
    if not manifest_path.is_file():
        raise RuntimeError("assembly sanity Blender render did not create a manifest")
    manifest = AssemblySanityRenderManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    _validate_render_artifacts(root, plan, current_plan_sha256, manifest)
    coverage, findings = _coverage_and_findings(root, plan, manifest)
    visible = sorted(
        {
            target
            for item in coverage
            for target in item.visible_target_ids
        }
    )
    unseen = sorted(set(plan.target_ids) - set(visible))
    if any(item.severity == "error" for item in findings):
        structural_status: Literal["passed", "warning", "failed"] = "failed"
    elif any(item.severity == "warning" for item in findings):
        structural_status = "warning"
    else:
        structural_status = "passed"
    report = AssemblySanityReport(
        job_id=job_id,
        run_id=selected_run_id,
        plan_sha256=current_plan_sha256,
        render_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=plan.scene_spec_sha256,
        modeling_plan_sha256=plan.modeling_plan_sha256,
        source_blend_sha256=plan.source_blend_sha256,
        build_fingerprint=plan.build_fingerprint,
        structural_status=structural_status,
        reference_comparison_note=(
            "No calibrated front/right/top/rear/oblique reference set is scored by this "
            "diagnostic. Use canonical V0.6 direct-reference QA for similarity evidence."
        ),
        target_ids=plan.target_ids,
        visible_target_ids=visible,
        unseen_target_ids=unseen,
        semantic_visibility_fraction=len(visible) / len(plan.target_ids),
        view_coverage=coverage,
        assembly_evaluation=manifest.assembly_evaluation,
        findings=findings,
        limitations=[*plan.limitations],
        generated_at=_utc_now(),
    )
    write_json_exclusive(report_path, report.model_dump(mode="json"))
    _require_exact_plan(plan_path, plan_sha256)
    _require_current_sources(root, plan)
    _require_exact_plan(plan_path, plan_sha256)
    validate_assembly_sanity_terminal(
        root,
        plan_path=plan_path,
        plan_sha256=current_plan_sha256,
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
        report_path=report_path,
        report_sha256=sha256_file(report_path),
        expected_job_id=job_id,
        expected_run_id=selected_run_id,
    )
    return {
        "job_id": job_id,
        "run_id": selected_run_id,
        "status": structural_status,
        "reference_comparison_status": "unscorable",
        "canonical_v06_qa_run": False,
        "plan": str(plan_path),
        "plan_sha256": current_plan_sha256,
        "render_manifest": str(manifest_path),
        "render_manifest_sha256": sha256_file(manifest_path),
        "report": str(report_path),
        "report_sha256": sha256_file(report_path),
        "view_count": len(manifest.views),
        "pass_count": sum(len(view.passes) for view in manifest.views),
    }
