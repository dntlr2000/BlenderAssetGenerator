from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..models import StrictModel

Sha256 = str
DirectScoringVersion = Literal["legacy_bbox_v1", "semantic_bbox_v2"]
PassKind = Literal[
    "beauty",
    "silhouette",
    "object_id",
    "material_id",
    "normal",
    "depth",
    "wireframe",
]
REQUIRED_QA_PASS_KINDS: tuple[PassKind, ...] = (
    "beauty",
    "silhouette",
    "object_id",
    "material_id",
    "normal",
    "depth",
    "wireframe",
)


class RenderPassRecord(StrictModel):
    """Describe one deterministic render-pass artifact and its encoding."""

    kind: PassKind
    path: str
    sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    encoding: str


class DepthRange(StrictModel):
    """Record the camera-space range used to encode the depth pass."""

    near: float = Field(ge=0)
    far: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> DepthRange:
        """Reject inverted or empty depth ranges."""

        if self.far <= self.near:
            raise ValueError("depth far must be greater than near")
        return self


class RenderPassManifest(StrictModel):
    """Bind QA render passes to one scene, camera, resolution, and Blender runtime."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str | None = None
    scene_spec_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    camera_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    build_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    blender_version: str
    render_engine: str
    render_device: str
    resolution: tuple[int, int]
    passes: list[RenderPassRecord] = Field(
        min_length=len(REQUIRED_QA_PASS_KINDS),
        max_length=len(REQUIRED_QA_PASS_KINDS),
    )
    object_id_colors: dict[str, str] = Field(default_factory=dict)
    material_id_colors: dict[str, str] = Field(default_factory=dict)
    depth_range: DepthRange | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> RenderPassManifest:
        """Require the complete unique seven-pass set at one comparison resolution."""

        width, height = self.resolution
        if width <= 0 or height <= 0:
            raise ValueError("render resolution must be positive")
        kinds = [record.kind for record in self.passes]
        if len(kinds) != len(set(kinds)):
            raise ValueError("render pass kinds must be unique")
        expected = set(REQUIRED_QA_PASS_KINDS)
        actual = set(kinds)
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            raise ValueError(
                "render pass manifest must contain the complete seven-pass set; "
                f"missing={missing}, unexpected={unexpected}"
            )
        for record in self.passes:
            if (record.width, record.height) != self.resolution:
                raise ValueError(f"render pass {record.kind} resolution does not match manifest")
        return self


class VisualQARequest(StrictModel):
    """Freeze every input used by one direct or image-assisted visual QA run."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str
    mode: Literal["concept", "measured"]
    reference_path: str
    reference_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    reference_mask_path: str
    reference_mask_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    preview_path: str
    preview_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    render_pass_manifest_path: str
    render_pass_manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    scene_spec_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    camera_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    include_generated_target: bool = False


class BoundingBoxMetric(StrictModel):
    """Report normalized reference and rendered bounding-box deviations."""

    reference_bbox_norm: tuple[float, float, float, float]
    rendered_bbox_norm: tuple[float, float, float, float] | None
    center_error_norm: float | None = Field(default=None, ge=0)
    size_error_norm: float | None = Field(default=None, ge=0)


class SemanticDeviation(StrictModel):
    """Localize one observed reference region to a rendered semantic object family."""

    target_id: str
    metric: BoundingBoxMetric
    confidence: float = Field(ge=0, le=1)


class DirectVisualMetrics(StrictModel):
    """Store shader-independent direct-reference metrics for one fixed camera."""

    scoring_version: DirectScoringVersion = "legacy_bbox_v1"
    silhouette_iou: float = Field(ge=0, le=1)
    silhouette_union_fraction: float = Field(ge=0, le=1)
    global_bbox: BoundingBoxMetric
    semantic_deviations: list[SemanticDeviation] = Field(default_factory=list)
    overall_direct_score: float = Field(ge=0, le=1)


class SuggestedEdit(StrictModel):
    """Describe a non-executable SceneSpec edit suggested by one QA finding."""

    target_type: Literal["object", "material", "camera", "scene"]
    target_id: str | None = None
    path: list[str | int] = Field(min_length=1)
    op: Literal["set", "multiply", "add", "append"]
    value: Any

    @model_validator(mode="after")
    def validate_target(self) -> SuggestedEdit:
        """Require IDs only for object and material suggestions."""

        if self.target_type in {"object", "material"} and not self.target_id:
            raise ValueError(f"{self.target_type} suggestion requires target_id")
        if self.target_type in {"camera", "scene"} and self.target_id is not None:
            raise ValueError(f"{self.target_type} suggestion must not set target_id")
        return self


class QAFinding(StrictModel):
    """Represent one localized discrepancy and the evidence channels supporting it."""

    id: str
    target_ids: list[str] = Field(default_factory=list)
    issue_type: Literal[
        "silhouette",
        "position",
        "proportion",
        "missing",
        "camera",
        "depth_order",
        "color_block",
        "constraint",
        "other",
    ]
    severity: Literal["info", "low", "medium", "high"]
    description: str
    evidence_sources: list[
        Literal["direct_reference", "generated_target", "constraint"]
    ] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    metrics: dict[str, float] = Field(default_factory=dict)
    suggestion: SuggestedEdit | None = None


class SurfaceDetailQASummary(StrictModel):
    """Expose non-mesh detail coverage without pretending geometry QA scored each mark."""

    contract_status: Literal["not_declared", "not_required", "pending", "validated"]
    declared_details: int = Field(ge=0)
    texture_bound_details: int = Field(ge=0)
    omitted_details: int = Field(ge=0)
    failed_checks: int = Field(ge=0)
    geometry_scoring_excluded: Literal[True] = True
    report_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


class VisualQAReport(StrictModel):
    """Combine direct evidence with optional advisory target findings without conflation."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str
    request_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    camera_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    direct_metrics: DirectVisualMetrics
    findings: list[QAFinding] = Field(default_factory=list)
    generated_target_status: Literal[
        "not_requested",
        "pending",
        "generated",
        "cached",
        "failed",
    ]
    surface_detail_summary: SurfaceDetailQASummary | None = None
    warnings: list[str] = Field(default_factory=list)


class QATargetManifest(StrictModel):
    """Record one optional image-model target as advisory, reproducible evidence."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    run_id: str
    request_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    camera_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["disabled", "generated", "cached", "failed"]
    advisory_only: Literal[True] = True
    provider: str
    model: str | None = None
    model_version: str | None = None
    seed: int | None = None
    prompt_sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    prompt_path: str | None = None
    output_path: str | None = None
    output_sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> QATargetManifest:
        """Require output metadata on success and an error message on provider failure."""

        if self.status in {"generated", "cached"}:
            if not self.output_path or not self.output_sha256:
                raise ValueError("successful QA targets require output path and hash")
        if self.status == "failed" and not self.error:
            raise ValueError("failed QA targets require an error message")
        return self
