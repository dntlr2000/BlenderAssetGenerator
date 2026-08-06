from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.6.0"
DIAGNOSTIC_VERSION = "camera_geometry_attribution_v1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
JOB_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
RUN_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$"
SEMANTIC_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,191}$"


def _validate_job_relative_path(value: str) -> str:
    """Require a normalized POSIX path contained by the owning job workspace."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty POSIX job-relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be job-relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not escape or contain empty segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


def _path_is_within(value: str, parent: str) -> bool:
    """Return whether one normalized relative path is contained by another."""

    path_parts = PurePosixPath(value).parts
    parent_parts = PurePosixPath(parent).parts
    return path_parts[: len(parent_parts)] == parent_parts


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
RunId = Annotated[str, Field(pattern=RUN_ID_PATTERN)]
SemanticId = Annotated[str, Field(pattern=SEMANTIC_ID_PATTERN)]
JobRelativePath = Annotated[str, AfterValidator(_validate_job_relative_path)]
SemanticRole = Literal[
    "primary",
    "supporting",
    "decorative",
    "ground_background",
    "unscoped",
]
AttributionClass = Literal[
    "camera",
    "geometry",
    "assembly",
    "mixed",
    "ambiguous",
    "unscorable",
]
AuthoringAction = Literal[
    "none",
    "camera_recalibration",
    "v04_parametric_revision",
    "v04_redesign_review",
    "additional_evidence_required",
]
V04Reentry = Literal["not_indicated", "recommended", "required"]
RedesignScope = Literal[
    "geometry_recipe",
    "semantic_recomposition",
    "assembly",
]


class DiagnosticStrictModel(BaseModel):
    """Reject undeclared fields and non-finite diagnostic evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SemanticMaskBinding(DiagnosticStrictModel):
    """Bind one semantic comparison to exact run-owned reference and render masks."""

    semantic_id: SemanticId
    role: SemanticRole = "unscoped"
    source_id: str = Field(min_length=1, max_length=192)
    confidence: float = Field(ge=0, le=1)
    reference_mask_path: JobRelativePath
    reference_mask_sha256: Sha256
    rendered_mask_path: JobRelativePath
    rendered_mask_sha256: Sha256


class SemanticReferenceMaskRecord(DiagnosticStrictModel):
    """Bind one evidence-backed semantic reference mask to its exact source identity."""

    semantic_id: SemanticId
    source_id: str = Field(min_length=1, max_length=192)
    path: JobRelativePath
    sha256: Sha256
    confidence: float = Field(ge=0, le=1)


class SemanticReferenceMaskManifest(DiagnosticStrictModel):
    """Bind reusable semantic masks to one exact reference and canonical SceneSpec."""

    schema_version: Literal["0.6.0"] = SCHEMA_VERSION
    manifest_version: Literal["semantic_reference_masks_v1"] = (
        "semantic_reference_masks_v1"
    )
    job_id: JobId
    reference_path: JobRelativePath
    reference_sha256: Sha256
    scene_spec_path: JobRelativePath = "analysis/scene_spec.json"
    scene_spec_sha256: Sha256
    masks: list[SemanticReferenceMaskRecord] = Field(min_length=1)
    generated_at: datetime
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mask_ownership(self) -> SemanticReferenceMaskManifest:
        """Require unique semantic IDs and analysis-owned source mask paths."""

        identifiers = [item.semantic_id for item in self.masks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("semantic reference mask IDs must be unique")
        paths = [item.path for item in self.masks]
        if len(paths) != len(set(paths)):
            raise ValueError("semantic reference mask paths must be unique")
        for record in self.masks:
            if not _path_is_within(record.path, "analysis/masks"):
                raise ValueError("semantic reference masks must remain inside analysis/masks")
        return self


class QADiagnosticRequest(DiagnosticStrictModel):
    """Freeze source reports, semantic masks, and camera-probe bounds for one companion run."""

    schema_version: Literal["0.6.0"] = SCHEMA_VERSION
    diagnostic_version: Literal["camera_geometry_attribution_v1"] = DIAGNOSTIC_VERSION
    job_id: JobId
    qa_run_id: RunId
    diagnostic_id: RunId
    artifact_root: JobRelativePath
    visual_qa_request_path: JobRelativePath
    visual_qa_request_sha256: Sha256
    visual_qa_report_path: JobRelativePath
    visual_qa_report_sha256: Sha256
    render_pass_manifest_path: JobRelativePath
    render_pass_manifest_sha256: Sha256
    scene_spec_path: JobRelativePath = "analysis/scene_spec.json"
    scene_spec_sha256: Sha256
    modeling_plan_path: JobRelativePath | None = None
    modeling_plan_sha256: Sha256 | None = None
    camera_role_map_path: JobRelativePath | None = None
    camera_role_map_sha256: Sha256 | None = None
    semantic_reference_manifest_path: JobRelativePath | None = None
    semantic_reference_manifest_sha256: Sha256 | None = None
    assembly_report_path: JobRelativePath | None = None
    assembly_report_sha256: Sha256 | None = None
    primary_reference_mask_path: JobRelativePath | None = None
    primary_reference_mask_sha256: Sha256 | None = None
    primary_reference_mask_source: Literal[
        "canonical_primary_object_reference",
        "semantic_primary_supporting_union",
    ] | None = None
    semantic_masks: list[SemanticMaskBinding] = Field(default_factory=list)
    baseline_probe_id: RunId = "baseline"
    max_camera_probes: int = Field(
        default=12,
        ge=1,
        le=12,
        description=(
            "Maximum non-baseline camera deltas; one neutral baseline probe is additional."
        ),
    )

    @model_validator(mode="after")
    def validate_owned_paths_and_pairs(self) -> QADiagnosticRequest:
        """Keep diagnostic evidence run-owned and require complete optional hash pairs."""

        expected_root = f"qa/runs/{self.qa_run_id}/diagnostics/{self.diagnostic_id}"
        if self.artifact_root != expected_root:
            raise ValueError(f"artifact_root must equal {expected_root}")
        qa_run_root = f"qa/runs/{self.qa_run_id}"
        for label, value in (
            ("visual_qa_request_path", self.visual_qa_request_path),
            ("visual_qa_report_path", self.visual_qa_report_path),
            ("render_pass_manifest_path", self.render_pass_manifest_path),
        ):
            if not _path_is_within(value, qa_run_root):
                raise ValueError(f"{label} must remain inside {qa_run_root}")
        for binding in self.semantic_masks:
            if not _path_is_within(binding.reference_mask_path, qa_run_root):
                raise ValueError("semantic reference masks must remain inside the QA run")
            if not _path_is_within(binding.rendered_mask_path, qa_run_root):
                raise ValueError("semantic rendered masks must remain inside the QA run")
        identifiers = [item.semantic_id for item in self.semantic_masks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("semantic mask bindings must use unique semantic IDs")
        reference_paths = [item.reference_mask_path for item in self.semantic_masks]
        rendered_paths = [item.rendered_mask_path for item in self.semantic_masks]
        if len(reference_paths) != len(set(reference_paths)):
            raise ValueError("semantic reference mask bindings must use unique paths")
        if len(rendered_paths) != len(set(rendered_paths)):
            raise ValueError("semantic rendered mask bindings must use unique paths")
        optional_pairs = (
            (
                "modeling_plan",
                self.modeling_plan_path,
                self.modeling_plan_sha256,
            ),
            (
                "semantic_reference_manifest",
                self.semantic_reference_manifest_path,
                self.semantic_reference_manifest_sha256,
            ),
            (
                "camera_role_map",
                self.camera_role_map_path,
                self.camera_role_map_sha256,
            ),
            (
                "assembly_report",
                self.assembly_report_path,
                self.assembly_report_sha256,
            ),
        )
        for label, path, digest in optional_pairs:
            if (path is None) != (digest is None):
                raise ValueError(f"{label} path and hash must be supplied together")
        if self.camera_role_map_path is not None and not _path_is_within(
            self.camera_role_map_path,
            expected_root,
        ):
            raise ValueError("camera role map must remain inside artifact_root")
        if self.semantic_reference_manifest_path is not None and not _path_is_within(
            self.semantic_reference_manifest_path,
            expected_root,
        ):
            raise ValueError(
                "semantic reference manifest snapshot must remain inside artifact_root"
            )
        primary_mask_values = (
            self.primary_reference_mask_path,
            self.primary_reference_mask_sha256,
            self.primary_reference_mask_source,
        )
        if any(value is None for value in primary_mask_values) != all(
            value is None for value in primary_mask_values
        ):
            raise ValueError(
                "primary reference mask path, hash, and source must be supplied together"
            )
        if self.primary_reference_mask_path is not None and not _path_is_within(
            self.primary_reference_mask_path,
            qa_run_root,
        ):
            raise ValueError("primary reference mask must remain inside the QA run")
        return self


class SemanticShapeMetrics(DiagnosticStrictModel):
    """Store deterministic mask-shape metrics for one stable semantic object."""

    semantic_id: SemanticId
    role: SemanticRole = "unscoped"
    status: Literal["scored", "unscorable"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    reference_foreground_pixels: int = Field(ge=0)
    rendered_foreground_pixels: int = Field(ge=0)
    mask_iou: float | None = Field(default=None, ge=0, le=1)
    centroid_error_norm: float | None = Field(default=None, ge=0)
    area_ratio: float | None = Field(default=None, gt=0)
    boundary_f_score: float | None = Field(default=None, ge=0, le=1)
    boundary_tolerance_px: int = Field(default=2, ge=0, le=32)
    symmetric_contour_distance_norm: float | None = Field(default=None, ge=0)
    oriented_axis_scorable: bool = False
    reference_axis_deg: float | None = Field(default=None, ge=0, lt=180)
    rendered_axis_deg: float | None = Field(default=None, ge=0, lt=180)
    undirected_axis_error_deg: float | None = Field(default=None, ge=0, le=90)
    reference_axis_eccentricity: float | None = Field(default=None, ge=0, le=1)
    rendered_axis_eccentricity: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metric_completeness(self) -> SemanticShapeMetrics:
        """Require complete core metrics when scored and honest axis availability."""

        core = (
            self.mask_iou,
            self.centroid_error_norm,
            self.area_ratio,
            self.boundary_f_score,
            self.symmetric_contour_distance_norm,
        )
        if self.status == "scored" and any(value is None for value in core):
            raise ValueError("scored semantic shape metrics require every core metric")
        if self.status == "unscorable" and not self.limitations:
            raise ValueError("unscorable semantic shape metrics require limitations")
        axis_values = (
            self.reference_axis_deg,
            self.rendered_axis_deg,
            self.undirected_axis_error_deg,
            self.reference_axis_eccentricity,
            self.rendered_axis_eccentricity,
        )
        if self.oriented_axis_scorable and any(value is None for value in axis_values):
            raise ValueError("scorable oriented axes require every axis metric")
        if not self.oriented_axis_scorable and any(value is not None for value in axis_values):
            raise ValueError("unscorable oriented axes must not publish axis metrics")
        return self


class BoundedCameraDelta(DiagnosticStrictModel):
    """Describe one tightly bounded comparison-camera diagnostic perturbation."""

    target_offset_norm: tuple[float, float] = (0.0, 0.0)
    distance_scale: float = Field(default=1.0, ge=0.5, le=2.0)
    projection_scale: float = Field(default=1.0, ge=0.5, le=2.0)
    rotation_delta_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @model_validator(mode="after")
    def validate_bounded_components(self) -> BoundedCameraDelta:
        """Reject camera probes outside the advisory diagnostic envelope."""

        if any(abs(value) > 0.25 for value in self.target_offset_norm):
            raise ValueError("target offsets must remain within +/-0.25 normalized units")
        if any(abs(value) > 15.0 for value in self.rotation_delta_deg):
            raise ValueError("camera rotations must remain within +/-15 degrees")
        return self

    def is_neutral(self) -> bool:
        """Return whether the delta represents the unchanged comparison camera."""

        return (
            self.target_offset_norm == (0.0, 0.0)
            and self.distance_scale == 1.0
            and self.projection_scale == 1.0
            and self.rotation_delta_deg == (0.0, 0.0, 0.0)
        )


class CameraProbeSemanticScore(DiagnosticStrictModel):
    """Record one semantic similarity score produced by a bounded camera probe."""

    semantic_id: SemanticId
    scorable: bool
    score_basis: Literal["bbox", "semantic_shape"] = "bbox"
    score: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_score_availability(self) -> CameraProbeSemanticScore:
        """Require scores only for scorable semantic probe evidence."""

        if self.scorable and self.score is None:
            raise ValueError("scorable semantic probe evidence requires a score")
        if not self.scorable and (self.score is not None or not self.limitations):
            raise ValueError("unscorable semantic probe evidence requires limitations only")
        return self


class CameraProbeResult(DiagnosticStrictModel):
    """Bind one bounded camera probe to exact immutable evidence and semantic scores."""

    probe_id: RunId
    is_baseline: bool = False
    status: Literal["scored", "unscorable"]
    camera_delta: BoundedCameraDelta = Field(default_factory=BoundedCameraDelta)
    overall_score: float | None = Field(default=None, ge=0, le=1)
    primary_silhouette_score: float | None = Field(default=None, ge=0, le=1)
    semantic_scores: list[CameraProbeSemanticScore] = Field(default_factory=list)
    evidence_path: JobRelativePath
    evidence_sha256: Sha256
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_probe_payload(self) -> CameraProbeResult:
        """Require complete scored evidence and an unchanged baseline camera."""

        identifiers = [item.semantic_id for item in self.semantic_scores]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("camera probe semantic IDs must be unique")
        if self.is_baseline and not self.camera_delta.is_neutral():
            raise ValueError("the baseline probe must use a neutral camera delta")
        if self.status == "scored":
            if self.overall_score is None:
                raise ValueError("scored camera probes require an overall score")
            if not any(item.scorable for item in self.semantic_scores):
                raise ValueError("scored camera probes require scorable semantic evidence")
        elif (
            self.overall_score is not None
            or self.primary_silhouette_score is not None
            or not self.limitations
        ):
            raise ValueError("unscorable camera probes require limitations and no score")
        return self


class AssemblyGeometryReviewSummary(DiagnosticStrictModel):
    """Copy one manual-only exterior geometry assessment into diagnostic evidence."""

    outcome: Literal[
        "structurally_consistent",
        "v04_reentry_recommended",
        "v04_reentry_required",
        "unscorable",
    ]
    reference_similarity_status: Literal["unscorable"] = "unscorable"
    reference_unscorable_reason: Literal["no_calibrated_per_view_references"] = (
        "no_calibrated_per_view_references"
    )
    v04_reentry: V04Reentry
    redesign_assessment: Literal[
        "not_indicated",
        "manual_review_required",
        "unscorable",
    ]
    redesign_scopes: list[RedesignScope] = Field(default_factory=list)
    reason_finding_ids: list[str] = Field(default_factory=list)
    automatic_revision_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_summary(self) -> AssemblyGeometryReviewSummary:
        """Preserve the exact outcome and manual-only semantics of geometry review."""

        if len(self.redesign_scopes) != len(set(self.redesign_scopes)):
            raise ValueError("geometry review redesign scopes must be unique")
        if len(self.reason_finding_ids) != len(set(self.reason_finding_ids)):
            raise ValueError("geometry review reason finding IDs must be unique")
        expected = {
            "structurally_consistent": ("not_indicated", "not_indicated"),
            "v04_reentry_recommended": ("recommended", "manual_review_required"),
            "v04_reentry_required": ("required", "manual_review_required"),
            "unscorable": ("not_indicated", "unscorable"),
        }[self.outcome]
        if (self.v04_reentry, self.redesign_assessment) != expected:
            raise ValueError(
                "geometry review outcome conflicts with its V0.4 or redesign assessment"
            )
        if self.outcome in {"structurally_consistent", "unscorable"} and (
            self.redesign_scopes or self.reason_finding_ids
        ):
            raise ValueError(
                "non-actionable geometry review outcomes cannot claim redesign evidence"
            )
        if self.outcome in {
            "v04_reentry_recommended",
            "v04_reentry_required",
        } and not self.reason_finding_ids:
            raise ValueError("V0.4 re-entry assessments require finding IDs")
        return self


class AssemblyDiagnosticEvidence(DiagnosticStrictModel):
    """Summarize deterministic cross-section or assembly checks used for attribution."""

    status: Literal["not_available", "passed", "warning", "failed"] = "not_available"
    report_path: JobRelativePath | None = None
    report_sha256: Sha256 | None = None
    required_failure_ids: list[str] = Field(default_factory=list)
    warning_ids: list[str] = Field(default_factory=list)
    geometry_review: AssemblyGeometryReviewSummary | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_assembly_payload(self) -> AssemblyDiagnosticEvidence:
        """Require hash pairs and align declared failures with assembly status."""

        if (self.report_path is None) != (self.report_sha256 is None):
            raise ValueError("assembly report path and hash must be supplied together")
        if self.status == "failed" and not self.required_failure_ids:
            raise ValueError("failed assembly evidence requires failure IDs")
        if self.status in {"not_available", "passed"} and self.required_failure_ids:
            raise ValueError(f"{self.status} assembly evidence cannot contain failures")
        if self.status == "not_available" and self.report_path is not None:
            raise ValueError("unavailable assembly evidence cannot reference a report")
        if self.status == "not_available" and self.geometry_review is not None:
            raise ValueError("unavailable assembly evidence cannot claim a geometry review")
        if len(self.required_failure_ids) != len(set(self.required_failure_ids)):
            raise ValueError("assembly failure IDs must be unique")
        return self


class DiagnosticAttribution(DiagnosticStrictModel):
    """Classify visual mismatch causes without authorizing an asset revision."""

    classification: AttributionClass
    confidence: float = Field(ge=0, le=1)
    baseline_probe_id: RunId
    best_probe_id: RunId | None = None
    baseline_score: float | None = Field(default=None, ge=0, le=1)
    best_score: float | None = Field(default=None, ge=0, le=1)
    camera_gain: float | None = Field(default=None, ge=-1, le=1)
    baseline_primary_silhouette_score: float | None = Field(default=None, ge=0, le=1)
    best_primary_silhouette_score: float | None = Field(default=None, ge=0, le=1)
    primary_silhouette_gain: float | None = Field(default=None, ge=-1, le=1)
    semantic_consensus_fraction: float | None = Field(default=None, ge=0, le=1)
    geometry_residual_fraction: float | None = Field(default=None, ge=0, le=1)
    semantic_shape_residual_fraction: float | None = Field(default=None, ge=0, le=1)
    semantic_shape_residual_ids: list[SemanticId] = Field(default_factory=list)
    semantic_orientation_residual_ids: list[SemanticId] = Field(default_factory=list)
    assembly_failure_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(min_length=1)
    advisory_only: Literal[True] = True


class AuthoringRecommendation(DiagnosticStrictModel):
    """Recommend a manual authoring next step without granting revision authority."""

    action: AuthoringAction = "none"
    v04_reentry: V04Reentry = "not_indicated"
    redesign_scopes: list[RedesignScope] = Field(default_factory=list)
    target_ids: list[SemanticId] = Field(default_factory=list)
    reason_ids: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    advisory_only: Literal[True] = True
    automatic_revision_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_recommendation(self) -> AuthoringRecommendation:
        """Keep action, V0.4 re-entry, and redesign scope internally consistent."""

        for label, values in (
            ("redesign_scopes", self.redesign_scopes),
            ("target_ids", self.target_ids),
            ("reason_ids", self.reason_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"authoring recommendation {label} must be unique")
        expected_reentry = {
            "none": {"not_indicated"},
            "camera_recalibration": {"not_indicated"},
            "v04_parametric_revision": {"recommended"},
            "v04_redesign_review": {"recommended", "required"},
            "additional_evidence_required": {"not_indicated"},
        }[self.action]
        if self.v04_reentry not in expected_reentry:
            raise ValueError(
                "authoring recommendation action conflicts with V0.4 re-entry"
            )
        if self.action == "v04_redesign_review" and not self.redesign_scopes:
            raise ValueError("V0.4 redesign review requires at least one scope")
        if self.action != "v04_redesign_review" and self.redesign_scopes:
            raise ValueError("only V0.4 redesign review may declare redesign scopes")
        return self


class QADiagnosticReport(DiagnosticStrictModel):
    """Publish hash-bound companion diagnostics without changing V0.6 acceptance scores."""

    schema_version: Literal["0.6.0"] = SCHEMA_VERSION
    diagnostic_version: Literal["camera_geometry_attribution_v1"] = DIAGNOSTIC_VERSION
    job_id: JobId
    qa_run_id: RunId
    diagnostic_id: RunId
    request_path: JobRelativePath
    request_sha256: Sha256
    status: Literal["completed", "degraded", "unscorable"]
    semantic_metrics: list[SemanticShapeMetrics] = Field(default_factory=list)
    camera_probes: list[CameraProbeResult] = Field(min_length=1)
    assembly_evidence: AssemblyDiagnosticEvidence
    attribution: DiagnosticAttribution
    authoring_recommendation: AuthoringRecommendation = Field(
        default_factory=AuthoringRecommendation
    )
    limitations: list[str] = Field(default_factory=list)
    advisory_only: Literal[True] = True
    generated_at: datetime

    @model_validator(mode="after")
    def validate_report_identity(self) -> QADiagnosticReport:
        """Require unique semantic and probe IDs plus exactly one named baseline."""

        semantic_ids = [item.semantic_id for item in self.semantic_metrics]
        if len(semantic_ids) != len(set(semantic_ids)):
            raise ValueError("semantic diagnostic metrics must use unique IDs")
        probe_ids = [item.probe_id for item in self.camera_probes]
        if len(probe_ids) != len(set(probe_ids)):
            raise ValueError("camera diagnostic probes must use unique IDs")
        baselines = [item for item in self.camera_probes if item.is_baseline]
        if len(baselines) != 1:
            raise ValueError("diagnostic reports require exactly one baseline probe")
        if baselines[0].probe_id != self.attribution.baseline_probe_id:
            raise ValueError("attribution baseline must match the baseline probe")
        expected_root = f"qa/runs/{self.qa_run_id}/diagnostics/{self.diagnostic_id}"
        if not _path_is_within(self.request_path, expected_root):
            raise ValueError("diagnostic report request must remain inside artifact_root")
        for probe in self.camera_probes:
            if not _path_is_within(probe.evidence_path, expected_root):
                raise ValueError(
                    "diagnostic report probe evidence must remain inside artifact_root"
                )
        if self.attribution.best_probe_id is not None and (
            self.attribution.best_probe_id not in probe_ids
        ):
            raise ValueError("attribution best probe must exist in camera_probes")
        if self.status == "completed" and (
            not self.semantic_metrics
            or any(item.status != "scored" for item in self.semantic_metrics)
            or any(item.status != "scored" for item in self.camera_probes)
        ):
            raise ValueError("completed diagnostics require complete scorable evidence")
        if (self.status == "unscorable") != (
            self.attribution.classification == "unscorable"
        ):
            raise ValueError("unscorable report status must match attribution")
        if self.status != "completed" and not self.limitations:
            raise ValueError("degraded or unscorable reports require explicit limitations")
        return self


class AssemblyMultiviewBundleEvidence(DiagnosticStrictModel):
    """Bind optional structural multi-view evidence without claiming reference similarity."""

    status: Literal["not_requested", "not_applicable", "passed", "warning", "failed"]
    reason: str | None = None
    run_id: RunId | None = None
    plan_path: JobRelativePath | None = None
    plan_sha256: Sha256 | None = None
    report_path: JobRelativePath | None = None
    report_sha256: Sha256 | None = None
    render_manifest_path: JobRelativePath | None = None
    render_manifest_sha256: Sha256 | None = None
    reference_comparison_status: Literal["unscorable"] | None = None

    @model_validator(mode="after")
    def validate_multiview_binding(self) -> AssemblyMultiviewBundleEvidence:
        """Require complete hash bindings only when the structural diagnostic executed."""

        executed = self.status in {"passed", "warning", "failed"}
        artifact_values = (
            self.run_id,
            self.plan_path,
            self.plan_sha256,
            self.report_path,
            self.report_sha256,
            self.render_manifest_path,
            self.render_manifest_sha256,
            self.reference_comparison_status,
        )
        if executed and any(value is None for value in artifact_values):
            raise ValueError("executed assembly multi-view evidence requires every binding")
        if not executed and any(value is not None for value in artifact_values):
            raise ValueError("non-executed assembly multi-view evidence cannot bind artifacts")
        if self.status == "not_applicable" and not self.reason:
            raise ValueError("not-applicable assembly multi-view evidence requires a reason")
        if self.run_id is not None:
            expected_root = f"qa/assembly_sanity/runs/{self.run_id}"
            for path in (
                self.plan_path,
                self.report_path,
                self.render_manifest_path,
            ):
                if path is None or not _path_is_within(path, expected_root):
                    raise ValueError(
                        "assembly multi-view artifacts must remain inside their run root"
                    )
        return self


class QADiagnosticBundleManifest(DiagnosticStrictModel):
    """Bind canonical V0.6 evidence to exact advisory companion artifacts."""

    schema_version: Literal["0.6.0"] = SCHEMA_VERSION
    diagnostic_kind: Literal["visual_qa_companion_bundle_v1"] = (
        "visual_qa_companion_bundle_v1"
    )
    canonical_v06_qa_run: Literal[False] = False
    job_id: JobId
    qa_run_id: RunId
    diagnostic_id: RunId
    visual_qa_report_path: JobRelativePath
    visual_qa_report_sha256: Sha256
    diagnostic_request_path: JobRelativePath
    diagnostic_request_sha256: Sha256
    diagnostic_report_path: JobRelativePath
    diagnostic_report_sha256: Sha256
    camera_probe_plan_path: JobRelativePath
    camera_probe_plan_sha256: Sha256
    camera_probe_manifest_path: JobRelativePath
    camera_probe_manifest_sha256: Sha256
    assembly_multiview: AssemblyMultiviewBundleEvidence
    canonical_v06_score_unchanged: Literal[True] = True
    created_at: datetime

    @model_validator(mode="after")
    def validate_bundle_paths(self) -> QADiagnosticBundleManifest:
        """Keep direct and companion evidence inside their exact immutable run roots."""

        qa_root = f"qa/runs/{self.qa_run_id}"
        diagnostic_root = f"{qa_root}/diagnostics/{self.diagnostic_id}"
        if not _path_is_within(self.visual_qa_report_path, qa_root):
            raise ValueError("visual QA report must remain inside its canonical run")
        for path in (
            self.diagnostic_request_path,
            self.diagnostic_report_path,
            self.camera_probe_plan_path,
            self.camera_probe_manifest_path,
        ):
            if not _path_is_within(path, diagnostic_root):
                raise ValueError("companion artifacts must remain inside diagnostic_root")
        return self
