from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.8.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
JOB_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
WORKFLOW_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


def _validate_job_relative_path(value: str) -> str:
    """Require one normalized path contained by the owning job workspace."""

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


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
WorkflowId = Annotated[str, Field(pattern=WORKFLOW_ID_PATTERN)]
JobRelativePath = Annotated[str, AfterValidator(_validate_job_relative_path)]
ObjectRole = Literal["primary", "supporting", "decorative", "ground_background"]
QualityStatus = Literal["passed", "needs_revision", "unscorable"]
BBox = tuple[float, float, float, float]


class BackgroundStrictModel(BaseModel):
    """Reject undeclared fields and non-finite numbers in background quality evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BackgroundRoleAssignment(BackgroundStrictModel):
    """Assign one stable semantic object to its review-priority role."""

    object_id: str = Field(min_length=1)
    role: ObjectRole
    source: Literal[
        "explicit_tag",
        "semantic_rule",
        "parent_rule",
        "largest_observed_fallback",
        "namespace_fallback",
    ]
    tags: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class BackgroundRoleMap(BackgroundStrictModel):
    """Bind deterministic QA roles to one exact initial SceneSpec."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    job_id: JobId
    workflow_id: WorkflowId
    scene_spec_sha256: Sha256
    classification_version: Literal["background_roles_v1"] = "background_roles_v1"
    assignments: list[BackgroundRoleAssignment] = Field(min_length=1)
    primary_subject_roles: list[ObjectRole] = Field(
        default_factory=lambda: ["primary"]
    )
    environment_roles: list[ObjectRole] = Field(
        default_factory=lambda: ["decorative", "ground_background"]
    )
    generated_at: datetime

    @model_validator(mode="after")
    def validate_unique_assignments(self) -> BackgroundRoleMap:
        """Require one role for every stable semantic object ID."""

        identifiers = [item.object_id for item in self.assignments]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("background role assignments must use unique object IDs")
        return self


class BackgroundFitMetrics(BackgroundStrictModel):
    """Record low-resolution primary-subject fit evidence for one candidate."""

    scorable: bool
    primary_reference_bbox_norm: BBox | None = None
    primary_rendered_bbox_norm: BBox | None = None
    primary_silhouette_iou: float | None = Field(default=None, ge=0, le=1)
    primary_bbox_similarity: float | None = Field(default=None, ge=0, le=1)
    combined_score: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scorable_metrics(self) -> BackgroundFitMetrics:
        """Require complete numeric evidence only when the diagnostic is scorable."""

        values = (
            self.primary_reference_bbox_norm,
            self.primary_rendered_bbox_norm,
            self.primary_silhouette_iou,
            self.primary_bbox_similarity,
            self.combined_score,
        )
        if self.scorable and any(value is None for value in values):
            raise ValueError("scorable fit metrics require every primary metric")
        return self


class BackgroundFitChange(BackgroundStrictModel):
    """Describe one bounded camera or parametric candidate edit."""

    path: list[str | int] = Field(min_length=1)
    before: Any
    after: Any
    reason: str = Field(min_length=1)


class BackgroundFitAttempt(BackgroundStrictModel):
    """Preserve one immutable baseline or bounded refinement attempt."""

    attempt_index: int = Field(ge=0, le=2)
    candidate_path: JobRelativePath
    candidate_sha256: Sha256
    input_fingerprint: Sha256
    changes: list[BackgroundFitChange] = Field(default_factory=list)
    metrics: BackgroundFitMetrics | None = None
    improved: bool = False
    selected: bool = False
    outcome: Literal["baseline", "evaluated", "failed"]
    reason: str = Field(min_length=1)


class BackgroundScenePromotionReceipt(BackgroundStrictModel):
    """Bind one optional refined candidate to the exact canonical promotion event."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    job_id: JobId
    workflow_id: WorkflowId
    input_fingerprint: Sha256
    initial_candidate_path: JobRelativePath
    initial_candidate_sha256: Sha256
    selected_candidate_path: JobRelativePath
    selected_candidate_sha256: Sha256
    selected_attempt_index: int = Field(ge=0, le=2)
    previous_canonical_sha256: Sha256
    new_canonical_sha256: Sha256
    canonical_changed: bool
    archived_scene_spec_path: JobRelativePath | None = None
    role_map_path: JobRelativePath
    role_map_sha256: Sha256
    promoted_at: datetime

    @model_validator(mode="after")
    def validate_promotion_state(self) -> BackgroundScenePromotionReceipt:
        """Require an archive only when canonical SceneSpec content changed."""

        if self.canonical_changed != (
            self.previous_canonical_sha256 != self.new_canonical_sha256
        ):
            raise ValueError("canonical_changed must match the canonical hashes")
        if self.canonical_changed and self.archived_scene_spec_path is None:
            raise ValueError("changed canonical SceneSpec requires an archive path")
        return self


class BackgroundFitReport(BackgroundStrictModel):
    """Summarize bounded pre-QA fitting without claiming canonical QA completion."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    job_id: JobId
    workflow_id: WorkflowId
    status: Literal["completed", "degraded"]
    input_fingerprint: Sha256
    max_refinement_attempts: int = Field(ge=0, le=2)
    initial_candidate_sha256: Sha256
    selected_candidate_sha256: Sha256
    selected_attempt_index: int = Field(ge=0, le=2)
    role_map_path: JobRelativePath
    role_map_sha256: Sha256
    promotion_receipt_path: JobRelativePath
    promotion_receipt_sha256: Sha256
    attempts: list[BackgroundFitAttempt] = Field(min_length=1, max_length=3)
    limitations: list[str] = Field(default_factory=list)
    completed_at: datetime

    @model_validator(mode="after")
    def validate_attempt_bounds(self) -> BackgroundFitReport:
        """Require one baseline and no more than the declared refinement count."""

        indices = [item.attempt_index for item in self.attempts]
        if indices[0] != 0 or indices != list(range(len(indices))):
            raise ValueError("fit attempts must start at zero and remain contiguous")
        if len(self.attempts) > self.max_refinement_attempts + 1:
            raise ValueError("fit report exceeds its bounded refinement count")
        selected = [item for item in self.attempts if item.selected]
        if len(selected) != 1 or selected[0].attempt_index != self.selected_attempt_index:
            raise ValueError("fit report requires exactly one selected attempt")
        return self


class BackgroundQualityFinding(BackgroundStrictModel):
    """Classify one immutable V0.6 finding without rewriting the source QA report."""

    finding_id: str = Field(min_length=1)
    original_severity: Literal["info", "low", "medium", "high"]
    delivery_severity: Literal["info", "warning", "important", "revision_required"]
    role: ObjectRole | Literal["unscoped"]
    target_ids: list[str] = Field(default_factory=list)
    issue_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence_sources: list[str] = Field(default_factory=list)


class BackgroundQualityReport(BackgroundStrictModel):
    """Separate successful review delivery from visual quality acceptance."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    job_id: JobId
    workflow_id: WorkflowId
    ok: Literal[True] = True
    execution_status: Literal["completed"] = "completed"
    delivery_status: Literal["ready_for_review"] = "ready_for_review"
    reference_content_scope: Literal[
        "primary_object_only",
        "full_reference",
    ] = "full_reference"
    target_subject: str | None = Field(default=None, min_length=1, max_length=256)
    quality_status: QualityStatus
    quality_accepted: bool
    standard_workflow_recommended: bool
    overall_direct_score: float | None = Field(default=None, ge=0, le=1)
    primary_silhouette_score: float | None = Field(default=None, ge=0, le=1)
    primary_bbox_similarity: float | None = Field(default=None, ge=0, le=1)
    findings: list[BackgroundQualityFinding] = Field(default_factory=list)
    primary_high_findings: list[str] = Field(default_factory=list)
    supporting_high_findings: list[str] = Field(default_factory=list)
    decorative_warnings: list[str] = Field(default_factory=list)
    environment_findings: list[str] = Field(default_factory=list)
    unscorable_evidence: list[str] = Field(default_factory=list)
    recommended_standard_revision_targets: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    qa_run_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")
    qa_request_path: JobRelativePath
    qa_request_sha256: Sha256
    visual_qa_report_path: JobRelativePath
    visual_qa_report_sha256: Sha256
    render_pass_manifest_path: JobRelativePath
    render_pass_manifest_sha256: Sha256
    role_map_path: JobRelativePath
    role_map_sha256: Sha256
    fit_report_path: JobRelativePath
    fit_report_sha256: Sha256
    source_fingerprint: Sha256
    build_fingerprint: Sha256
    qa_scene_spec_sha256: Sha256
    qa_camera_fingerprint: Sha256
    evaluated_at: datetime

    @model_validator(mode="after")
    def validate_quality_outcome(self) -> BackgroundQualityReport:
        """Prevent review delivery from being mistaken for quality acceptance."""

        if (
            self.reference_content_scope == "primary_object_only"
            and self.target_subject is None
        ):
            raise ValueError(
                "primary_object_only quality requires an explicit target_subject"
            )
        if self.quality_accepted != (self.quality_status == "passed"):
            raise ValueError("quality_accepted is true only for quality_status=passed")
        if self.quality_status == "unscorable" and not self.unscorable_evidence:
            raise ValueError("unscorable quality requires explicit missing evidence")
        if self.quality_status != "passed" and not self.standard_workflow_recommended:
            raise ValueError("non-passing quality must recommend the standard workflow")
        return self
