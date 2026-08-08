"""Run immutable exterior assembly sanity diagnostics from five temporary cameras.

This module deliberately stays outside the canonical V0.6 fixed-camera QA run.  It
provides structural, multi-view evidence for spatial assembly contracts without
claiming reference-image similarity or mutating the authoring Blender scene.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

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
AssemblySanityReviewPolicy = Literal[
    "assembly_structural_v1",
    "exterior_geometry_review_v2",
]
GeometryReviewScope = Literal[
    "geometry_recipe",
    "semantic_recomposition",
    "assembly",
]
GeometryVisualIssueType = Literal[
    "shape_coherence",
    "proportion",
    "orientation",
    "assembly",
    "topology_artifact",
    "insufficient_evidence",
]
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
ASSEMBLY_SANITY_REFERENCE_NOTE = (
    "No calibrated front/right/top/rear/oblique reference set is scored by this "
    "diagnostic. Use canonical V0.6 direct-reference QA for similarity evidence."
)


def _ordered_discriminator_schema(
    discriminator: str,
    values: tuple[str, ...],
) -> Callable[[dict[str, Any]], None]:
    """Return a schema mutator that preserves item validation and fixes array order."""

    def apply_ordered_schema(schema: dict[str, Any]) -> None:
        """Replace homogeneous items with exact discriminator-bound prefix entries."""

        item_schema = dict(schema["items"])
        schema["prefixItems"] = [
            {
                "allOf": [
                    dict(item_schema),
                    {
                        "type": "object",
                        "properties": {discriminator: {"const": value}},
                        "required": [discriminator],
                    },
                ]
            }
            for value in values
        ]
        schema["items"] = False

    return apply_ordered_schema


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
    review_policy: AssemblySanityReviewPolicy = "assembly_structural_v1"
    assembly_frame: AssemblyFrame
    target_ids: list[str] = Field(min_length=1)
    resolution: tuple[int, int]
    views: list[AssemblySanityViewPlan] = Field(
        min_length=5,
        max_length=5,
        json_schema_extra=_ordered_discriminator_schema(
            "view_id",
            ASSEMBLY_SANITY_VIEW_IDS,
        ),
    )
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
    passes: list[AssemblySanityPassRecord] = Field(
        min_length=4,
        max_length=4,
        json_schema_extra=_ordered_discriminator_schema(
            "kind",
            ASSEMBLY_SANITY_PASS_KINDS,
        ),
    )

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
    views: list[AssemblySanityViewRender] = Field(
        min_length=5,
        max_length=5,
        json_schema_extra=_ordered_discriminator_schema(
            "view_id",
            ASSEMBLY_SANITY_VIEW_IDS,
        ),
    )
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


class GeometryReviewAssessment(StrictModel):
    """Record a manual-only V0.4 re-entry assessment from structural multi-view evidence."""

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
    v04_reentry: Literal["not_indicated", "recommended", "required"]
    redesign_assessment: Literal[
        "not_indicated",
        "manual_review_required",
        "unscorable",
    ]
    redesign_scopes: list[GeometryReviewScope] = Field(default_factory=list)
    reason_finding_ids: list[str] = Field(default_factory=list)
    automatic_revision_authorized: Literal[False] = False

    @model_validator(mode="after")
    def validate_assessment(self) -> GeometryReviewAssessment:
        """Keep the outcome, V0.4 recommendation, and redesign evidence consistent."""

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
        if (
            self.outcome
            in {
                "v04_reentry_recommended",
                "v04_reentry_required",
            }
            and not self.reason_finding_ids
        ):
            raise ValueError("V0.4 re-entry assessments require finding IDs")
        return self


class GeometryVisualReviewFinding(StrictModel):
    """Record one Codex-observed issue from exact five-view beauty/wireframe evidence."""

    finding_id: str = Field(min_length=1)
    issue_type: GeometryVisualIssueType
    severity: Literal["info", "warning", "error"]
    view_ids: list[AssemblySanityViewId] = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    description: str = Field(min_length=1)
    recommended_v04_action: Literal[
        "none",
        "parametric_revision",
        "redesign_review",
        "additional_evidence",
    ]

    @model_validator(mode="after")
    def validate_membership(self) -> GeometryVisualReviewFinding:
        """Keep membership unique and align severity with the recommended V0.4 action."""

        if len(self.view_ids) != len(set(self.view_ids)):
            raise ValueError("geometry visual-review view IDs must be unique")
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("geometry visual-review target IDs must be unique")
        allowed_actions = {
            "info": {"none"},
            "warning": {"parametric_revision", "additional_evidence"},
            "error": {"redesign_review"},
        }
        if self.recommended_v04_action not in allowed_actions[self.severity]:
            raise ValueError(
                "geometry visual-review severity conflicts with its recommended action"
            )
        insufficient_evidence = self.issue_type == "insufficient_evidence"
        requests_more_evidence = self.recommended_v04_action == "additional_evidence"
        if insufficient_evidence != requests_more_evidence:
            raise ValueError(
                "geometry visual-review insufficient evidence must request additional evidence"
            )
        return self


class GeometryMultiviewVisualReview(StrictModel):
    """Bind a Codex visual reading of all five views without claiming reference likeness."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"outcome": {"const": "visually_coherent"}},
                        "required": ["outcome"],
                    },
                    "then": {"properties": {"v04_reentry": {"const": "not_indicated"}}},
                },
                {
                    "if": {
                        "properties": {"outcome": {"const": "v04_revision_recommended"}},
                        "required": ["outcome"],
                    },
                    "then": {"properties": {"v04_reentry": {"const": "recommended"}}},
                },
                {
                    "if": {
                        "properties": {"outcome": {"const": "v04_redesign_review_required"}},
                        "required": ["outcome"],
                    },
                    "then": {"properties": {"v04_reentry": {"const": "required"}}},
                },
                {
                    "if": {
                        "properties": {"outcome": {"const": "unscorable"}},
                        "required": ["outcome"],
                    },
                    "then": {"properties": {"v04_reentry": {"const": "not_indicated"}}},
                },
            ]
        },
    )

    schema_version: Literal["0.6.0"] = "0.6.0"
    review_kind: Literal["geometry_multiview_visual_review_v1"] = (
        "geometry_multiview_visual_review_v1"
    )
    job_id: str
    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    render_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    structural_report_sha256: str = Field(pattern=SHA256_PATTERN)
    reviewed_view_ids: tuple[
        Literal["front"],
        Literal["right"],
        Literal["top"],
        Literal["rear"],
        Literal["oblique"],
    ]
    reviewed_pass_kinds: tuple[Literal["beauty"], Literal["wireframe"]]
    outcome: Literal[
        "visually_coherent",
        "v04_revision_recommended",
        "v04_redesign_review_required",
        "unscorable",
    ]
    v04_reentry: Literal["not_indicated", "recommended", "required"]
    findings: list[GeometryVisualReviewFinding] = Field(default_factory=list)
    reference_similarity_status: Literal["unscorable"] = "unscorable"
    reference_similarity_reason: Literal["no_calibrated_per_view_references"] = (
        "no_calibrated_per_view_references"
    )
    advisory_only: Literal[True] = True
    automatic_revision_authorized: Literal[False] = False
    reviewed_at: datetime

    @model_validator(mode="after")
    def validate_review_contract(self) -> GeometryMultiviewVisualReview:
        """Require all views and derive the review outcome from finding recommendations."""

        if self.reviewed_view_ids != ASSEMBLY_SANITY_VIEW_IDS:
            raise ValueError("geometry visual review must consume all five ordered views")
        if self.reviewed_pass_kinds != ("beauty", "wireframe"):
            raise ValueError("geometry visual review must consume beauty and wireframe")
        identifiers = [item.finding_id for item in self.findings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("geometry visual-review finding IDs must be unique")
        actions = {item.recommended_v04_action for item in self.findings}
        if "redesign_review" in actions:
            expected_outcome = "v04_redesign_review_required"
        elif "parametric_revision" in actions:
            expected_outcome = "v04_revision_recommended"
        elif "additional_evidence" in actions:
            expected_outcome = "unscorable"
        else:
            expected_outcome = "visually_coherent"
        if self.outcome != expected_outcome:
            raise ValueError(
                "geometry visual-review outcome conflicts with finding recommendations"
            )
        expected_reentry = {
            "visually_coherent": "not_indicated",
            "v04_revision_recommended": "recommended",
            "v04_redesign_review_required": "required",
            "unscorable": "not_indicated",
        }[self.outcome]
        if self.v04_reentry != expected_reentry:
            raise ValueError("geometry visual-review outcome conflicts with V0.4 re-entry")
        return self


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
    review_policy: AssemblySanityReviewPolicy = "assembly_structural_v1"
    structural_status: Literal["passed", "warning", "failed"]
    reference_comparison_status: Literal["unscorable"] = "unscorable"
    reference_comparison_note: str
    quality_claimed: Literal[False] = False
    target_ids: list[str] = Field(min_length=1)
    visible_target_ids: list[str]
    unseen_target_ids: list[str]
    semantic_visibility_fraction: float = Field(ge=0, le=1)
    view_coverage: list[AssemblySanityViewCoverage] = Field(min_length=5, max_length=5)
    assembly_evaluation: dict[str, Any]
    findings: list[AssemblySanityFinding] = Field(default_factory=list)
    geometry_review: GeometryReviewAssessment | None = None
    limitations: list[str] = Field(default_factory=list)
    generated_at: str

    @model_validator(mode="after")
    def validate_report(self) -> AssemblySanityReport:
        """Require visibility partitioning, structural status, and v2 review evidence."""

        targets = set(self.target_ids)
        visible = set(self.visible_target_ids)
        unseen = set(self.unseen_target_ids)
        if visible.intersection(unseen) or visible.union(unseen) != targets:
            raise ValueError("visible and unseen assembly targets must partition target_ids")
        has_error = any(item.severity == "error" for item in self.findings)
        if has_error and self.structural_status != "failed":
            raise ValueError("assembly sanity reports with errors must be failed")
        if self.review_policy == "exterior_geometry_review_v2" and self.geometry_review is None:
            raise ValueError("exterior geometry review v2 requires an assessment")
        if self.review_policy == "assembly_structural_v1" and self.geometry_review is not None:
            raise ValueError("legacy structural reports cannot claim a v2 geometry review")
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


def _hidden_implementation_helper_ids(scene_spec: SceneSpec) -> set[str]:
    """Return Boolean and implementation helpers that must stay absent from renders."""

    hidden_targets = {
        str(modifier.target_id)
        for item in scene_spec.objects
        for modifier in item.modifiers
        if modifier.kind == "boolean" and modifier.hide_target
    }
    tagged_helpers = {
        item.id
        for item in scene_spec.objects
        if {"boolean_helper", "implementation_helper"}.intersection(item.tags)
    }
    return hidden_targets | tagged_helpers


def _authored_spatial_target_ids(
    plan: ModelingPlan,
    scene_spec: SceneSpec | None = None,
) -> list[str]:
    """Select authored render targets while excluding hidden implementation helpers."""

    if (
        plan.assembly_consistency_policy != "spatial_v1"
        or plan.stage != "authored"
        or plan.assembly_frame is None
    ):
        raise ValueError(
            "assembly multi-view sanity requires an authored spatial_v1 assembly frame"
        )
    excluded_ids = (
        _hidden_implementation_helper_ids(scene_spec) if scene_spec is not None else set()
    )
    target_ids = sorted(
        item.id
        for item in plan.objects
        if (
            item.assembly_role in {"root", "attached"}
            or item.scope_role in {"primary", "supporting"}
        )
        and item.id not in excluded_ids
    )
    if plan.assembly_frame.root_object_id not in target_ids:
        raise ValueError("assembly multi-view sanity requires its declared root target")
    return target_ids


def plan_job_assembly_multiview_sanity(
    job_id: str,
    *,
    run_id: str | None = None,
    resolution: int = 384,
) -> dict[str, Any]:
    """Write one immutable v2 five-view plan for an authored spatial asset."""

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
    modeling_plan = ModelingPlan.model_validate_json(modeling_plan_path.read_text(encoding="utf-8"))
    target_ids = _authored_spatial_target_ids(modeling_plan, scene_spec)
    contract = validate_assembly_prebuild_contract(modeling_plan, scene_spec)
    if not contract.ok:
        failures = "; ".join(item.message for item in contract.checks if item.status == "failed")
        raise ValueError(f"assembly contract is invalid: {failures}")
    provenance = collect_build_provenance(
        root,
        job_id,
        scene_spec_path=scene_path,
        validate_surface_details=False,
    )
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
        review_policy="exterior_geometry_review_v2",
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
        "review_policy": plan.review_policy,
        "canonical_v06_qa_run": False,
    }


def plan_job_assembly_multiview_sanity_for_sources(
    job_id: str,
    *,
    scene_spec_path: Path,
    blend_path: Path,
    run_id: str,
    resolution: int = 384,
) -> dict[str, Any]:
    """Plan five-view structural evidence for one isolated job-contained candidate pair."""

    root = job_dir(job_id).resolve()
    metadata = load_job(job_id)
    scene_path = scene_spec_path.expanduser().resolve()
    source_blend = blend_path.expanduser().resolve()
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    for label, path in (
        ("SceneSpec", scene_path),
        ("ModelingPlan", modeling_plan_path),
        ("candidate blend", source_blend),
    ):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"assembly sanity {label} must stay inside the job") from exc
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")
    scene_spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    modeling_plan = ModelingPlan.model_validate_json(modeling_plan_path.read_text(encoding="utf-8"))
    target_ids = _authored_spatial_target_ids(modeling_plan, scene_spec)
    contract = validate_assembly_prebuild_contract(modeling_plan, scene_spec)
    if not contract.ok:
        failures = "; ".join(item.message for item in contract.checks if item.status == "failed")
        raise ValueError(f"assembly contract is invalid: {failures}")
    provenance = collect_build_provenance(
        root,
        job_id,
        scene_spec_path=scene_path,
        validate_surface_details=False,
    )
    selected_run_id = _validate_run_id(run_id)
    run_dir = root / "qa" / "assembly_sanity" / "runs" / selected_run_id
    if run_dir.exists():
        raise FileExistsError(f"assembly sanity run already exists: {selected_run_id}")
    sources = _reference_sources(root, metadata)
    source_payload = {
        "job_id": job_id,
        "scene_spec_sha256": sha256_file(scene_path),
        "modeling_plan_sha256": sha256_file(modeling_plan_path),
        "source_blend_sha256": sha256_file(source_blend),
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
        source_blend_path=_job_relative(root, source_blend),
        source_blend_sha256=source_payload["source_blend_sha256"],
        build_fingerprint=str(provenance["fingerprint"]),
        source_fingerprint=stable_json_digest(source_payload),
        review_policy="exterior_geometry_review_v2",
        assembly_frame=modeling_plan.assembly_frame.model_dump(mode="json"),
        target_ids=target_ids,
        resolution=(resolution, resolution),
        views=_view_plan(modeling_plan, target_ids),
        reference_sources=sources,
        created_at=_utc_now(),
        limitations=[
            "This is candidate-review structural evidence, not canonical V0.6 QA.",
            "Temporary cameras do not modify or save the source Blender file.",
            "The comparison is a veto-only three-dimensional regression guard.",
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
        "review_policy": plan.review_policy,
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
    provenance = collect_build_provenance(
        root,
        plan.job_id,
        scene_spec_path=scene_path,
        validate_surface_details=False,
    )
    if provenance["fingerprint"] != plan.build_fingerprint:
        raise RuntimeError("assembly sanity build fingerprint is stale")
    source_payload = {
        "job_id": plan.job_id,
        "scene_spec_sha256": plan.scene_spec_sha256,
        "modeling_plan_sha256": plan.modeling_plan_sha256,
        "source_blend_sha256": plan.source_blend_sha256,
        "build_fingerprint": plan.build_fingerprint,
        "reference_sources": [item.model_dump(mode="json") for item in plan.reference_sources],
    }
    if stable_json_digest(source_payload) != plan.source_fingerprint:
        raise RuntimeError("assembly sanity source fingerprint is internally inconsistent")
    scene_spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    modeling_plan = ModelingPlan.model_validate_json(modeling_plan_path.read_text(encoding="utf-8"))
    contract = validate_assembly_prebuild_contract(modeling_plan, scene_spec)
    if not contract.ok:
        raise RuntimeError("assembly sanity current assembly contract is invalid")
    try:
        expected_targets = _authored_spatial_target_ids(modeling_plan, scene_spec)
    except ValueError as exc:
        raise RuntimeError(
            "assembly sanity current ModelingPlan is not an authored spatial asset"
        ) from exc
    if (
        modeling_plan.assembly_frame != plan.assembly_frame
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
        re.fullmatch(r"#[0-9a-f]{6}", color) is None for color in manifest.object_id_colors.values()
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
            raise RuntimeError(f"assembly sanity camera {planned_view.view_id} has invalid {field}")
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
            str(check[key]) for key in ("subject_id", "reference_id", "peer_id") if check.get(key)
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


def _geometry_review_assessment(
    findings: list[AssemblySanityFinding],
) -> GeometryReviewAssessment:
    """Derive a conservative V0.4 recommendation from exact structural findings."""

    actionable = [
        item
        for item in findings
        if item.severity == "error"
        or (item.category == "assembly_relation" and item.severity == "warning")
    ]
    if not actionable:
        return GeometryReviewAssessment(
            outcome="structurally_consistent",
            v04_reentry="not_indicated",
            redesign_assessment="not_indicated",
        )
    has_error = any(item.severity == "error" for item in actionable)
    scopes: set[GeometryReviewScope] = set()
    for finding in actionable:
        if finding.category == "assembly_relation":
            scopes.add("assembly")
        elif finding.category == "visibility":
            scopes.add("assembly")
            if finding.finding_id == "visibility.all_views":
                scopes.update({"geometry_recipe", "semantic_recomposition"})
    ordered_scopes: list[GeometryReviewScope] = [
        scope
        for scope in ("geometry_recipe", "semantic_recomposition", "assembly")
        if scope in scopes
    ]
    return GeometryReviewAssessment(
        outcome=("v04_reentry_required" if has_error else "v04_reentry_recommended"),
        v04_reentry="required" if has_error else "recommended",
        redesign_assessment="manual_review_required",
        redesign_scopes=ordered_scopes,
        reason_finding_ids=[item.finding_id for item in actionable],
    )


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
    run_root = (resolved_root / "qa" / "assembly_sanity" / "runs" / plan.run_id).resolve()
    if (
        resolved_plan != run_root / "plan.json"
        or resolved_manifest != run_root / "render_manifest.json"
        or resolved_report != run_root / "report.json"
    ):
        raise ValueError("assembly sanity terminal artifacts are outside their exact run")
    manifest = AssemblySanityRenderManifest.model_validate_json(
        resolved_manifest.read_text(encoding="utf-8")
    )
    report = AssemblySanityReport.model_validate_json(resolved_report.read_text(encoding="utf-8"))
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
    if report.review_policy != plan.review_policy:
        raise ValueError("assembly sanity terminal review policy changed")
    strict_camera_contract = _has_strict_terminal_camera_contract(manifest)
    if plan.review_policy == "exterior_geometry_review_v2" and not strict_camera_contract:
        raise ValueError("exterior geometry review v2 requires strict camera evidence")
    if not strict_camera_contract:
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
        {target for coverage in expected_coverage for target in coverage.visible_target_ids}
    )
    unseen = sorted(set(plan.target_ids) - set(visible))
    expected_status: Literal["passed", "warning", "failed"]
    if any(item.severity == "error" for item in expected_findings):
        expected_status = "failed"
    elif any(item.severity == "warning" for item in expected_findings):
        expected_status = "warning"
    else:
        expected_status = "passed"
    expected_geometry_review = (
        _geometry_review_assessment(expected_findings)
        if plan.review_policy == "exterior_geometry_review_v2"
        else None
    )
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
        or report.geometry_review != expected_geometry_review
        or (
            plan.review_policy == "exterior_geometry_review_v2"
            and (
                report.reference_comparison_note != ASSEMBLY_SANITY_REFERENCE_NOTE
                or report.limitations != plan.limitations
            )
        )
    ):
        raise ValueError("assembly sanity terminal report differs from rendered evidence")
    return plan, manifest, report


def validate_geometry_multiview_visual_review(
    root: Path,
    review_path: Path,
    *,
    expected_job_id: str | None = None,
    expected_run_id: str | None = None,
) -> GeometryMultiviewVisualReview:
    """Validate one agent review against the exact immutable five-view terminal."""

    resolved_root = root.expanduser().resolve()
    resolved_review = review_path.expanduser().resolve()
    review = GeometryMultiviewVisualReview.model_validate_json(
        resolved_review.read_text(encoding="utf-8")
    )
    run_root = (resolved_root / "qa" / "assembly_sanity" / "runs" / review.run_id).resolve()
    if resolved_review != run_root / "visual_review.json":
        raise ValueError("geometry visual review is outside its exact assembly run")
    if expected_job_id is not None and review.job_id != expected_job_id:
        raise ValueError("geometry visual review belongs to another job")
    if expected_run_id is not None and review.run_id != expected_run_id:
        raise ValueError("geometry visual review belongs to another run")
    plan_path = run_root / "plan.json"
    manifest_path = run_root / "render_manifest.json"
    report_path = run_root / "report.json"
    plan_sha256 = sha256_file(plan_path)
    manifest_sha256 = sha256_file(manifest_path)
    report_sha256 = sha256_file(report_path)
    plan, _manifest, report = validate_assembly_sanity_terminal(
        resolved_root,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        report_path=report_path,
        report_sha256=report_sha256,
        expected_job_id=review.job_id,
        expected_run_id=review.run_id,
    )
    if plan.review_policy != "exterior_geometry_review_v2":
        raise ValueError("geometry visual review requires exterior geometry review v2")
    if (
        review.plan_sha256 != plan_sha256
        or review.render_manifest_sha256 != manifest_sha256
        or review.structural_report_sha256 != report_sha256
    ):
        raise ValueError("geometry visual review source hashes changed")
    unknown_target_ids = sorted(
        {target_id for finding in review.findings for target_id in finding.target_ids}
        - set(report.target_ids)
    )
    if unknown_target_ids:
        raise ValueError(
            "geometry visual review references target IDs outside the terminal report: "
            f"{unknown_target_ids}"
        )
    return review


def _recoverable_view_tree(
    root: Path,
    views_dir: Path,
) -> tuple[list[Path], list[Path]]:
    """Inventory only the fixed run-owned view/pass paths that recovery may remove."""

    if views_dir.is_symlink():
        raise RuntimeError("assembly sanity recovery refuses a linked views directory")
    if not views_dir.exists():
        return [], []
    if not views_dir.is_dir():
        raise RuntimeError("assembly sanity recovery views path is not a directory")
    _job_relative(root, views_dir)
    expected_view_ids = set(ASSEMBLY_SANITY_VIEW_IDS)
    expected_pass_names = {f"{kind}.png" for kind in ASSEMBLY_SANITY_PASS_KINDS}
    files: list[Path] = []
    directories: list[Path] = []
    for view_dir in sorted(views_dir.iterdir(), key=lambda path: path.name):
        if view_dir.name not in expected_view_ids:
            raise RuntimeError(
                f"assembly sanity recovery found an unexpected views entry: {view_dir.name}"
            )
        if view_dir.is_symlink() or not view_dir.is_dir():
            raise RuntimeError(
                "assembly sanity recovery requires regular run-owned view directories"
            )
        directories.append(view_dir)
        for artifact in sorted(view_dir.iterdir(), key=lambda path: path.name):
            if artifact.name not in expected_pass_names:
                raise RuntimeError(
                    "assembly sanity recovery found an unexpected view artifact: "
                    f"{view_dir.name}/{artifact.name}"
                )
            if artifact.is_symlink() or not artifact.is_file():
                raise RuntimeError("assembly sanity recovery requires regular run-owned pass files")
            files.append(artifact)
    return files, directories


def _require_regular_optional_derived_file(path: Path, label: str) -> None:
    """Reject links or directories at one exact recoverable derived-file path."""

    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"assembly sanity recovery {label} is not a regular run-owned file")


def recover_unpublished_job_assembly_multiview_plan(
    job_id: str,
    run_id: str,
    *,
    recovery_authorized: bool,
) -> dict[str, Any]:
    """Remove an empty or plan-temp-only run left before immutable plan publication."""

    if recovery_authorized is not True:
        raise PermissionError(
            "assembly sanity unpublished-plan recovery requires explicit authorization"
        )
    selected_run_id = _validate_run_id(run_id)
    root = job_dir(job_id)
    run_dir = root / "qa" / "assembly_sanity" / "runs" / selected_run_id
    plan_path = run_dir / "plan.json"
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise RuntimeError(
            "assembly sanity unpublished-plan recovery requires a regular run directory"
        )
    _job_relative(root, run_dir)
    if plan_path.exists() or plan_path.is_symlink():
        raise RuntimeError("assembly sanity unpublished-plan recovery refuses a published plan")
    temporary_pattern = re.compile(r"^\.plan\.json\.\d+\.tmp$")
    temporary_files: list[Path] = []
    for entry in sorted(run_dir.iterdir(), key=lambda path: path.name):
        if (
            entry.is_symlink()
            or not entry.is_file()
            or temporary_pattern.fullmatch(entry.name) is None
        ):
            raise RuntimeError(
                f"assembly sanity unpublished-plan recovery found an unexpected entry: {entry.name}"
            )
        temporary_files.append(entry)
    current_entries = sorted(run_dir.iterdir(), key=lambda path: path.name)
    if current_entries != temporary_files:
        raise RuntimeError(
            "assembly sanity unpublished-plan recovery inventory changed before cleanup"
        )
    removed_paths: list[str] = []
    for temporary in temporary_files:
        temporary.unlink()
        removed_paths.append(_job_relative(root, temporary))
    run_dir.rmdir()
    return {
        "job_id": job_id,
        "run_id": selected_run_id,
        "status": "recovered",
        "removed_paths": removed_paths,
        "removed_run_directory": True,
    }


def recover_incomplete_job_assembly_multiview_sanity(
    job_id: str,
    run_id: str,
    *,
    plan_sha256: str,
    recovery_authorized: bool,
) -> dict[str, Any]:
    """Remove only incomplete run-owned derivatives after explicit caller authorization."""

    if recovery_authorized is not True:
        raise PermissionError(
            "assembly sanity incomplete-output recovery requires explicit authorization"
        )
    selected_run_id = _validate_run_id(run_id)
    root = job_dir(job_id)
    run_dir = root / "qa" / "assembly_sanity" / "runs" / selected_run_id
    plan_path = run_dir / "plan.json"
    if run_dir.is_symlink():
        raise RuntimeError("assembly sanity recovery refuses a linked run directory")
    if not run_dir.is_dir() or not plan_path.is_file():
        raise FileNotFoundError(f"assembly sanity plan is missing: {plan_path}")
    _job_relative(root, run_dir)
    with artifact_publication_lease(
        run_dir,
        owner_kind="assembly_multiview_recovery",
        owner_id=selected_run_id,
    ):
        return _recover_incomplete_job_assembly_multiview_sanity_locked(
            job_id,
            selected_run_id,
            plan_sha256=plan_sha256,
        )


def _recover_incomplete_job_assembly_multiview_sanity_locked(
    job_id: str,
    run_id: str,
    *,
    plan_sha256: str,
    require_current_sources: bool = True,
) -> dict[str, Any]:
    """Clear a bounded incomplete derivative set after validating its exact run plan."""

    if re.fullmatch(SHA256_PATTERN, plan_sha256) is None:
        raise ValueError("assembly sanity recovery requires a lowercase SHA-256")
    root = job_dir(job_id)
    run_dir = root / "qa" / "assembly_sanity" / "runs" / run_id
    plan_path = run_dir / "plan.json"
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise RuntimeError("assembly sanity recovery run directory is not regular")
    _job_relative(root, run_dir)
    if plan_path.is_symlink() or not plan_path.is_file():
        raise FileNotFoundError(f"assembly sanity plan is missing: {plan_path}")
    _require_exact_plan(plan_path, plan_sha256)
    plan = AssemblySanityPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    if plan.job_id != job_id or plan.run_id != run_id:
        raise ValueError("assembly sanity recovery plan identity does not match the run")
    if require_current_sources:
        _require_current_sources(root, plan)

    manifest_path = run_dir / "render_manifest.json"
    report_path = run_dir / "report.json"
    views_dir = run_dir / "views"
    visual_review_path = run_dir / "visual_review.json"
    _require_regular_optional_derived_file(manifest_path, "render manifest")
    _require_regular_optional_derived_file(report_path, "report")
    view_files, view_directories = _recoverable_view_tree(root, views_dir)
    views_tree_present = views_dir.is_dir()

    if manifest_path.is_file() and report_path.is_file():
        try:
            validate_assembly_sanity_terminal(
                root,
                plan_path=plan_path,
                plan_sha256=plan_sha256,
                manifest_path=manifest_path,
                manifest_sha256=sha256_file(manifest_path),
                report_path=report_path,
                report_sha256=sha256_file(report_path),
                expected_job_id=job_id,
                expected_run_id=run_id,
            )
        except (OSError, RuntimeError, ValueError):
            pass
        else:
            raise FileExistsError(
                "completed assembly sanity terminal is immutable and cannot be recovered"
            )
    if visual_review_path.exists() or visual_review_path.is_symlink():
        raise RuntimeError(
            "assembly sanity recovery refuses a run with downstream visual-review evidence"
        )

    # Recheck caller-reviewed inputs immediately before the first destructive operation.
    _require_exact_plan(plan_path, plan_sha256)
    if require_current_sources:
        _require_current_sources(root, plan)
    removed_paths: list[str] = []
    for artifact in (report_path, manifest_path, *view_files):
        if artifact.is_file():
            artifact.unlink()
            removed_paths.append(_job_relative(root, artifact))
    for directory in reversed(view_directories):
        directory.rmdir()
    if views_dir.is_dir():
        views_dir.rmdir()

    _require_exact_plan(plan_path, plan_sha256)
    if require_current_sources:
        _require_current_sources(root, plan)
    return {
        "job_id": job_id,
        "run_id": run_id,
        "status": "recovered" if removed_paths or views_tree_present else "ready",
        "plan": str(plan_path),
        "plan_sha256": plan_sha256,
        "removed_paths": removed_paths,
        "removed_view_tree": views_tree_present,
    }


def _recover_failed_job_assembly_multiview_sanity_locked(
    job_id: str,
    run_id: str,
    *,
    plan_sha256: str,
) -> dict[str, Any]:
    """Remove only known incomplete derivatives while the caller still owns the lease."""

    return _recover_incomplete_job_assembly_multiview_sanity_locked(
        job_id,
        run_id,
        plan_sha256=plan_sha256,
        require_current_sources=False,
    )


def _finalize_job_assembly_multiview_sanity_locked(
    job_id: str,
    run_id: str,
    *,
    root: Path,
    plan: AssemblySanityPlan,
    plan_path: Path,
    plan_sha256: str,
    manifest_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    """Parse and publish one terminal while the caller retains the run lease."""

    _require_exact_plan(plan_path, plan_sha256)
    if not manifest_path.is_file():
        raise RuntimeError("assembly sanity Blender render did not create a manifest")
    manifest = AssemblySanityRenderManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    _validate_render_artifacts(root, plan, plan_sha256, manifest)
    coverage, findings = _coverage_and_findings(root, plan, manifest)
    visible = sorted({target for item in coverage for target in item.visible_target_ids})
    unseen = sorted(set(plan.target_ids) - set(visible))
    if any(item.severity == "error" for item in findings):
        structural_status: Literal["passed", "warning", "failed"] = "failed"
    elif any(item.severity == "warning" for item in findings):
        structural_status = "warning"
    else:
        structural_status = "passed"
    report = AssemblySanityReport(
        job_id=job_id,
        run_id=run_id,
        plan_sha256=plan_sha256,
        render_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=plan.scene_spec_sha256,
        modeling_plan_sha256=plan.modeling_plan_sha256,
        source_blend_sha256=plan.source_blend_sha256,
        build_fingerprint=plan.build_fingerprint,
        review_policy=plan.review_policy,
        structural_status=structural_status,
        reference_comparison_note=ASSEMBLY_SANITY_REFERENCE_NOTE,
        target_ids=plan.target_ids,
        visible_target_ids=visible,
        unseen_target_ids=unseen,
        semantic_visibility_fraction=len(visible) / len(plan.target_ids),
        view_coverage=coverage,
        assembly_evaluation=manifest.assembly_evaluation,
        findings=findings,
        geometry_review=(
            _geometry_review_assessment(findings)
            if plan.review_policy == "exterior_geometry_review_v2"
            else None
        ),
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
        plan_sha256=plan_sha256,
        manifest_path=manifest_path,
        manifest_sha256=sha256_file(manifest_path),
        report_path=report_path,
        report_sha256=sha256_file(report_path),
        expected_job_id=job_id,
        expected_run_id=run_id,
    )
    return {
        "job_id": job_id,
        "run_id": run_id,
        "status": structural_status,
        "reference_comparison_status": "unscorable",
        "review_policy": plan.review_policy,
        "geometry_review": (
            report.geometry_review.model_dump(mode="json")
            if report.geometry_review is not None
            else None
        ),
        "canonical_v06_qa_run": False,
        "plan": str(plan_path),
        "plan_sha256": plan_sha256,
        "render_manifest": str(manifest_path),
        "render_manifest_sha256": sha256_file(manifest_path),
        "report": str(report_path),
        "report_sha256": sha256_file(report_path),
        "view_count": len(manifest.views),
        "pass_count": sum(len(view.passes) for view in manifest.views),
    }


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
        try:
            # A normal Blender failure is still inside the publication lease, so
            # discard only the known partial derivatives and leave the exact plan
            # ready for an explicitly authorized workflow retry.
            _recover_incomplete_job_assembly_multiview_sanity_locked(
                job_id,
                selected_run_id,
                plan_sha256=plan_sha256,
            )
        except Exception as recovery_exc:
            raise RuntimeError(
                "assembly sanity Blender failure left derived evidence that could not "
                "be safely recovered"
            ) from recovery_exc
        raise
    try:
        return _finalize_job_assembly_multiview_sanity_locked(
            job_id,
            selected_run_id,
            root=root,
            plan=plan,
            plan_path=plan_path,
            plan_sha256=current_plan_sha256,
            manifest_path=manifest_path,
            report_path=report_path,
        )
    except Exception as failure:
        recovery_error: Exception | None = None
        try:
            # Finalization is still inside the publication lease. Remove only the
            # fixed manifest/report/view derivatives so the exact plan can be retried.
            _recover_failed_job_assembly_multiview_sanity_locked(
                job_id,
                selected_run_id,
                plan_sha256=plan_sha256,
            )
        except Exception as recovery_exc:
            recovery_error = recovery_exc
        if recovery_error is not None:
            failure.add_note(
                "Automatic post-Blender cleanup was not safe: "
                f"{type(recovery_error).__name__}: {recovery_error}"
            )
            raise failure from recovery_error
        raise
