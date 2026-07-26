"""Strict V0.6 contracts for approved multi-view interior inspection."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..models import StrictModel
from ..qa.models import REQUIRED_QA_PASS_KINDS, DepthRange, RenderPassRecord

SHA256_PATTERN = r"^[0-9a-f]{64}$"
RUN_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$"
VIEW_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,95}$"
_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:")

InteriorQAProfile = Literal["minimal", "standard", "thorough"]
InteriorQAStatus = Literal["passed", "warning", "failed"]


def _validate_job_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by the owning job workspace."""

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


class InteriorQABounds(StrictModel):
    """Store one world-space axis-aligned bounding box."""

    min: tuple[float, float, float]
    max: tuple[float, float, float]

    @model_validator(mode="after")
    def validate_order(self) -> InteriorQABounds:
        """Reject inverted world-space bounds."""

        if any(high < low for low, high in zip(self.min, self.max, strict=True)):
            raise ValueError("interior QA bounds cannot be inverted")
        return self


class InteriorQATopology(StrictModel):
    """Record bounded mesh integrity counters from the approved authoring scene."""

    vertices: int = Field(ge=0)
    edges: int = Field(ge=0)
    polygons: int = Field(ge=0)
    triangles_estimated: int = Field(ge=0)
    non_finite_vertex_count: int = Field(ge=0)
    non_finite_vertices: list[int] = Field(default_factory=list)
    degenerate_face_count: int = Field(ge=0)
    degenerate_faces: list[int] = Field(default_factory=list)
    invalid_normal_face_count: int = Field(ge=0)
    invalid_normal_faces: list[int] = Field(default_factory=list)
    boundary_edge_count: int = Field(ge=0)
    overused_edge_count: int = Field(ge=0)
    loose_edge_count: int = Field(ge=0)
    loose_vertex_count: int = Field(ge=0)
    manifold_closed: bool
    negative_determinant: bool
    matrix_determinant: float
    uv_layers: list[dict[str, Any]] = Field(default_factory=list)


class InteriorQAObjectRecord(StrictModel):
    """Describe one Blender object instance selected by an interior semantic ID."""

    name: str
    type: Literal["MESH", "CURVE", "SURFACE", "META", "FONT"]
    semantic_id: str
    instance_index: int | None = None
    bbox_world: InteriorQABounds
    dimensions: tuple[float, float, float]
    material_ids: list[str] = Field(default_factory=list)
    topology: InteriorQATopology | None = None


class InteriorQASourceInventory(StrictModel):
    """Bind fresh Blender geometry inspection to exact canonical build inputs."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    build_fingerprint: str = Field(pattern=SHA256_PATTERN)
    interior_scope_sha256: str = Field(pattern=SHA256_PATTERN)
    interior_scope_approval_sha256: str = Field(pattern=SHA256_PATTERN)
    blender_version: str
    objects: list[InteriorQAObjectRecord] = Field(min_length=1)
    missing_target_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_object_identity(self) -> InteriorQASourceInventory:
        """Require every inspected object to have a non-empty semantic identity."""

        if any(not item.semantic_id.strip() for item in self.objects):
            raise ValueError("interior QA source objects require semantic IDs")
        return self


class InteriorQAView(StrictModel):
    """Declare one temporary perspective camera used only for interior QA."""

    view_id: str = Field(pattern=VIEW_ID_PATTERN)
    level_id: str | None = None
    space_id: str | None = None
    purpose: Literal[
        "room_rotation",
        "corner_overview",
        "corridor_axis",
        "interior_overview",
    ]
    location: tuple[float, float, float]
    target: tuple[float, float, float]
    focal_length_mm: float = Field(default=18.0, ge=8.0, le=120.0)
    clip_start_m: float = Field(default=0.03, gt=0)
    clip_end_m: float = Field(gt=0)
    target_ids: list[str] = Field(min_length=1)
    isolate_targets: Literal[True] = True

    @model_validator(mode="after")
    def validate_camera_and_targets(self) -> InteriorQAView:
        """Reject empty directions, inverted clipping, and duplicate target IDs."""

        if self.location == self.target:
            raise ValueError("interior QA camera location and target must differ")
        if self.clip_end_m <= self.clip_start_m:
            raise ValueError("interior QA clip_end_m must exceed clip_start_m")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("interior QA view target IDs must be unique")
        return self


class InteriorQAPlan(StrictModel):
    """Freeze one bounded multi-view interior inspection plan before rendering."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    profile: InteriorQAProfile
    resolution: tuple[int, int]
    max_views: int = Field(ge=1, le=64)
    eye_height_m: float = Field(gt=0, le=3.0)
    scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    build_fingerprint: str = Field(pattern=SHA256_PATTERN)
    interior_scope_sha256: str = Field(pattern=SHA256_PATTERN)
    interior_scope_approval_sha256: str = Field(pattern=SHA256_PATTERN)
    source_inventory_path: str
    source_inventory_sha256: str = Field(pattern=SHA256_PATTERN)
    source_fingerprint: str = Field(pattern=SHA256_PATTERN)
    target_ids: list[str] = Field(min_length=1)
    views: list[InteriorQAView] = Field(min_length=1, max_length=64)
    reference_comparison_mode: Literal["structural_only"] = "structural_only"
    created_at: str
    warnings: list[str] = Field(default_factory=list)

    @field_validator("source_inventory_path")
    @classmethod
    def validate_inventory_path(cls, value: str) -> str:
        """Keep the planning inventory inside the owning job workspace."""

        return _validate_job_relative_path(value)

    @model_validator(mode="after")
    def validate_plan_membership(self) -> InteriorQAPlan:
        """Require unique views whose targets remain inside the approved plan target set."""

        width, height = self.resolution
        if width < 128 or height < 128 or width > 2048 or height > 2048:
            raise ValueError("interior QA resolution components must be within [128, 2048]")
        if len(self.views) > self.max_views:
            raise ValueError("interior QA plan exceeds max_views")
        view_ids = [view.view_id for view in self.views]
        if len(view_ids) != len(set(view_ids)):
            raise ValueError("interior QA view IDs must be unique")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("interior QA plan target IDs must be unique")
        allowed = set(self.target_ids)
        for view in self.views:
            if not set(view.target_ids).issubset(allowed):
                raise ValueError(f"view {view.view_id} references targets outside the plan")
        return self


class InteriorQAPlanApproval(StrictModel):
    """Record explicit single-use approval of one exact interior camera plan."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    approval_id: str
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    source_fingerprint: str = Field(pattern=SHA256_PATTERN)
    approved_view_ids: list[str] = Field(min_length=1)
    approval_note: str = Field(min_length=1)
    recorded_via: Literal["cli_or_mcp"] = "cli_or_mcp"
    approved_at: str
    status: Literal["approved", "consumed"] = "approved"
    consumed_at: str | None = None

    @field_validator("approval_note")
    @classmethod
    def validate_approval_note(cls, value: str) -> str:
        """Preserve meaningful user approval text instead of an empty placeholder."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("interior QA approval note must not be empty")
        return stripped

    @model_validator(mode="after")
    def validate_consumption_state(self) -> InteriorQAPlanApproval:
        """Keep single-use approval status synchronized with its consumption timestamp."""

        if self.status == "approved" and self.consumed_at is not None:
            raise ValueError("unconsumed interior QA approval cannot have consumed_at")
        if self.status == "consumed" and self.consumed_at is None:
            raise ValueError("consumed interior QA approval requires consumed_at")
        if len(self.approved_view_ids) != len(set(self.approved_view_ids)):
            raise ValueError("approved interior QA view IDs must be unique")
        return self


class InteriorQAViewRender(StrictModel):
    """Bind one temporary interior camera to exactly seven immutable QA passes."""

    view_id: str = Field(pattern=VIEW_ID_PATTERN)
    level_id: str | None = None
    space_id: str | None = None
    camera: dict[str, Any]
    target_ids: list[str] = Field(min_length=1)
    depth_range: DepthRange
    passes: list[RenderPassRecord] = Field(
        min_length=len(REQUIRED_QA_PASS_KINDS),
        max_length=len(REQUIRED_QA_PASS_KINDS),
    )

    @model_validator(mode="after")
    def validate_seven_passes(self) -> InteriorQAViewRender:
        """Require the complete unique V0.6 pass set for every interior view."""

        kinds = [record.kind for record in self.passes]
        if len(kinds) != len(set(kinds)) or set(kinds) != set(REQUIRED_QA_PASS_KINDS):
            raise ValueError("each interior QA view requires the exact seven-pass set")
        return self


class InteriorQARenderManifest(StrictModel):
    """Bind all approved interior views to one Blender runtime and exact plan hash."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_approval_sha256: str = Field(pattern=SHA256_PATTERN)
    scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    build_fingerprint: str = Field(pattern=SHA256_PATTERN)
    interior_scope_sha256: str = Field(pattern=SHA256_PATTERN)
    interior_scope_approval_sha256: str = Field(pattern=SHA256_PATTERN)
    blender_version: str
    render_engine: str
    render_device: str
    resolution: tuple[int, int]
    object_id_colors: dict[str, str]
    material_id_colors: dict[str, str]
    views: list[InteriorQAViewRender] = Field(min_length=1, max_length=64)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_render_views(self) -> InteriorQARenderManifest:
        """Require unique rendered view IDs and pass resolutions matching the run."""

        view_ids = [view.view_id for view in self.views]
        if len(view_ids) != len(set(view_ids)):
            raise ValueError("interior QA render view IDs must be unique")
        for view in self.views:
            for record in view.passes:
                if (record.width, record.height) != self.resolution:
                    raise ValueError(
                        f"interior QA pass resolution differs for {view.view_id}"
                    )
        return self


class InteriorQAViewCoverage(StrictModel):
    """Report exact-color semantic visibility for one approved interior view."""

    view_id: str = Field(pattern=VIEW_ID_PATTERN)
    level_id: str | None = None
    space_id: str | None = None
    target_ids: list[str]
    visible_target_ids: list[str]
    unseen_target_ids: list[str]
    semantic_visibility_fraction: float = Field(ge=0, le=1)


class InteriorQASpaceCoverage(StrictModel):
    """Aggregate semantic visibility across all views assigned to one interior space."""

    level_id: str | None = None
    space_id: str | None = None
    view_ids: list[str] = Field(min_length=1)
    target_ids: list[str] = Field(min_length=1)
    visible_target_ids: list[str]
    unseen_target_ids: list[str]
    semantic_visibility_fraction: float = Field(ge=0, le=1)


class InteriorQAFinding(StrictModel):
    """Describe one structural or multi-view interior QA observation."""

    finding_id: str
    category: Literal[
        "visibility",
        "topology",
        "overlap",
        "camera",
        "render",
        "reference",
    ]
    severity: Literal["info", "warning", "error"]
    target_ids: list[str] = Field(default_factory=list)
    view_ids: list[str] = Field(default_factory=list)
    description: str
    evidence_paths: list[str] = Field(default_factory=list)
    measured_value: float | int | None = None
    threshold: float | int | None = None

    @field_validator("evidence_paths")
    @classmethod
    def validate_evidence_paths(cls, values: list[str]) -> list[str]:
        """Keep all finding evidence paths inside the owning job workspace."""

        return [_validate_job_relative_path(value) for value in values]


class InteriorQARevisionCandidate(StrictModel):
    """Offer one manual-only semantic correction candidate from interior QA evidence."""

    candidate_id: str
    finding_id: str
    target_ids: list[str] = Field(min_length=1)
    action: Literal[
        "review_occlusion",
        "repair_topology",
        "review_overlap",
        "add_reference_view",
        "review_camera_plan",
    ]
    recommendation: str
    acceptance_criteria: list[str] = Field(min_length=1)
    approval_required: Literal[True] = True
    executable: Literal[False] = False


class InteriorQARevisionCandidates(StrictModel):
    """Collect manual-only candidates without granting geometry-change authority."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    report_sha256: str = Field(pattern=SHA256_PATTERN)
    candidates: list[InteriorQARevisionCandidate] = Field(default_factory=list)


class InteriorQAReport(StrictModel):
    """Summarize structural interior evidence without inventing a reference score."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    render_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    source_inventory_sha256: str = Field(pattern=SHA256_PATTERN)
    status: InteriorQAStatus
    reference_comparison_status: Literal["unavailable", "not_requested"]
    reference_comparison_note: str
    semantic_visibility_fraction: float = Field(ge=0, le=1)
    target_ids: list[str] = Field(min_length=1)
    visible_target_ids: list[str]
    unseen_target_ids: list[str]
    view_coverage: list[InteriorQAViewCoverage] = Field(min_length=1)
    space_coverage: list[InteriorQASpaceCoverage] = Field(min_length=1)
    findings: list[InteriorQAFinding] = Field(default_factory=list)
    candidates: list[InteriorQARevisionCandidate] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: str

    @model_validator(mode="after")
    def validate_status_and_coverage(self) -> InteriorQAReport:
        """Synchronize visibility sets and prevent errors from being reported as passed."""

        target_ids = set(self.target_ids)
        visible = set(self.visible_target_ids)
        unseen = set(self.unseen_target_ids)
        if visible.intersection(unseen) or visible.union(unseen) != target_ids:
            raise ValueError("visible and unseen interior IDs must partition target_ids")
        has_error = any(finding.severity == "error" for finding in self.findings)
        if has_error and self.status != "failed":
            raise ValueError("interior QA reports with errors must have status=failed")
        return self


class InteriorQALatest(StrictModel):
    """Point to the latest immutable interior QA evidence using job-relative paths."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan: str
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    approval: str
    approval_sha256: str = Field(pattern=SHA256_PATTERN)
    source_inventory: str
    render_manifest: str
    report: str
    revision_candidates: str
    contact_sheets: list[str] = Field(default_factory=list)

    @field_validator(
        "plan",
        "approval",
        "source_inventory",
        "render_manifest",
        "report",
        "revision_candidates",
    )
    @classmethod
    def validate_artifact_path(cls, value: str) -> str:
        """Keep latest-run pointers inside the owning job workspace."""

        return _validate_job_relative_path(value)

    @field_validator("contact_sheets")
    @classmethod
    def validate_contact_sheet_paths(cls, values: list[str]) -> list[str]:
        """Keep every human-review contact sheet inside the owning job workspace."""

        return [_validate_job_relative_path(value) for value in values]
