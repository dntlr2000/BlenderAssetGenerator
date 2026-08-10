"""Strict contracts for Autonomous Quality reference evidence and camera hypotheses."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

SCHEMA_VERSION = "0.1.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
PORTABLE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"
JOB_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


def _validate_relative_path(value: str) -> str:
    """Require a normalized POSIX path contained by the owning job workspace."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty normalized POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative, not absolute")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
PortableId = Annotated[str, Field(pattern=PORTABLE_ID_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]
BBoxNorm = tuple[float, float, float, float]


class ReferenceEvidenceStrictModel(BaseModel):
    """Reject undeclared fields and non-finite numbers in evidence contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class EvidenceProvenance(ReferenceEvidenceStrictModel):
    """Identify the exact deterministic producer and method for one evidence artifact."""

    producer: str = Field(min_length=1, max_length=128)
    producer_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provider: Literal["pillow", "opencv", "mixed", "advisory"]
    method: str = Field(min_length=1, max_length=128)
    deterministic: bool
    advisory_only: bool = False
    parameters: dict[str, bool | int | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_advisory_provider(self) -> EvidenceProvenance:
        """Require advisory providers to remain explicitly non-authoritative."""

        if self.provider == "advisory" and not self.advisory_only:
            raise ValueError("advisory provider provenance must set advisory_only=true")
        if self.advisory_only and self.provider != "advisory":
            raise ValueError("only advisory provider provenance may be advisory_only")
        return self


class EvidenceArtifact(ReferenceEvidenceStrictModel):
    """Bind one job-relative evidence artifact to its exact bytes."""

    artifact_id: PortableId
    path: RelativePath
    sha256: Sha256
    media_type: str = Field(min_length=1, max_length=128)
    byte_size: int = Field(ge=0)


class ForegroundMaskMetrics(ReferenceEvidenceStrictModel):
    """Record bounded diagnostic metrics for one foreground-mask hypothesis."""

    bbox_norm: BBoxNorm
    area_ratio: float = Field(ge=0, le=1)
    edge_agreement: float = Field(ge=0, le=1)
    border_contact_ratio: float = Field(ge=0, le=1)
    bilateral_symmetry: float = Field(ge=0, le=1)
    shadow_likelihood: float = Field(ge=0, le=1)
    reflection_likelihood: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_bbox(self) -> ForegroundMaskMetrics:
        """Require normalized, positive-area foreground bounds."""

        x0, y0, x1, y1 = self.bbox_norm
        if not all(0 <= value <= 1 for value in self.bbox_norm):
            raise ValueError("bbox_norm values must be in [0, 1]")
        if x1 <= x0 or y1 <= y0:
            raise ValueError("bbox_norm must have positive area")
        return self


class ForegroundMaskCandidate(ReferenceEvidenceStrictModel):
    """Describe one bounded, deterministic foreground-mask candidate."""

    candidate_id: PortableId
    rank: int = Field(ge=1, le=3)
    artifact: EvidenceArtifact
    provenance: EvidenceProvenance
    metrics: ForegroundMaskMetrics
    status: Literal["usable", "underconstrained"]
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AdvisoryObservation(ReferenceEvidenceStrictModel):
    """Preserve optional provider advice without granting mask or camera authority."""

    observation_id: PortableId
    category: Literal["foreground", "camera", "occlusion", "uncertainty"]
    message: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    provenance: EvidenceProvenance

    @model_validator(mode="after")
    def validate_advisory_only(self) -> AdvisoryObservation:
        """Prevent an advisory observation from masquerading as canonical evidence."""

        if not self.provenance.advisory_only:
            raise ValueError("advisory observations require advisory-only provenance")
        return self


class ReferenceEvidence(ReferenceEvidenceStrictModel):
    """Bind one run; producer/version remain in strict nested EvidenceProvenance."""

    schema_version: Literal["0.1.0"]
    evidence_id: PortableId
    run_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    dispatch_id: PortableId
    input_sha256: Sha256
    source_image: EvidenceArtifact
    source_fingerprint: Sha256
    mask_candidates: list[ForegroundMaskCandidate] = Field(min_length=1, max_length=3)
    selected_candidate_id: PortableId | None = None
    status: Literal["ready", "underconstrained", "unscorable"]
    advisory_observations: list[AdvisoryObservation] = Field(default_factory=list)
    provenance: EvidenceProvenance
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_candidate_binding(self) -> ReferenceEvidence:
        """Require unique ordered candidates and an exact selected-candidate binding."""

        identifiers = [item.candidate_id for item in self.mask_candidates]
        ranks = [item.rank for item in self.mask_candidates]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("mask candidate IDs must be unique")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("mask candidates must have contiguous rank order")
        if self.selected_candidate_id not in set(identifiers):
            raise ValueError("selected_candidate_id must reference a mask candidate")
        if self.status == "ready" and not any(
            item.status == "usable" for item in self.mask_candidates
        ):
            raise ValueError("ready evidence requires at least one usable mask")
        if self.status == "unscorable" and any(
            item.status == "usable" for item in self.mask_candidates
        ):
            raise ValueError("unscorable evidence cannot contain a usable selected mask")
        return self


class CameraEvidenceCue(ReferenceEvidenceStrictModel):
    """Describe one bounded cue supporting or weakening a projection hypothesis."""

    cue_id: PortableId
    cue_type: Literal[
        "line_orientation",
        "vanishing_tendency",
        "silhouette_symmetry",
        "orthographic_view_kind",
        "projection_ambiguity",
        "user_hint",
    ]
    supports: Literal["perspective", "orthographic", "ambiguous"]
    strength: float = Field(ge=0, le=1)
    description: str = Field(min_length=1, max_length=1000)
    source_artifact_ids: list[PortableId] = Field(default_factory=list)


class CameraIntrinsics(ReferenceEvidenceStrictModel):
    """Store normalized camera intrinsics without claiming recovered calibration."""

    focal_length_mm: float | None = Field(default=None, gt=0, le=1000)
    sensor_width_mm: float | None = Field(default=None, gt=0, le=1000)
    principal_point_norm: tuple[float, float] = (0.5, 0.5)
    ortho_scale_normalized: float | None = Field(default=None, gt=0, le=100)
    radial_distortion_k1: float | None = Field(default=None, ge=-2, le=2)
    radial_distortion_k2: float | None = Field(default=None, ge=-2, le=2)

    @model_validator(mode="after")
    def validate_principal_point(self) -> CameraIntrinsics:
        """Keep the normalized principal point inside the reference image."""

        if not all(0 <= value <= 1 for value in self.principal_point_norm):
            raise ValueError("principal_point_norm must be inside [0, 1]")
        return self


class CameraPoseHypothesis(ReferenceEvidenceStrictModel):
    """Describe an image-relative pose suitable only for staging comparisons."""

    azimuth_deg: float = Field(ge=-360, le=360)
    elevation_deg: float = Field(ge=-89.9, le=89.9)
    roll_deg: float = Field(ge=-180, le=180)
    distance_scale: float | None = Field(default=None, gt=0, le=1000)
    target_norm: tuple[float, float, float] = (0.5, 0.5, 0.5)

    @model_validator(mode="after")
    def validate_target(self) -> CameraPoseHypothesis:
        """Keep the image-relative target inside its normalized staging volume."""

        if not all(0 <= value <= 1 for value in self.target_norm):
            raise ValueError("target_norm must be inside [0, 1]")
        return self


class CameraHypothesis(ReferenceEvidenceStrictModel):
    """Record one perspective or orthographic camera hypothesis for low-resolution fit."""

    hypothesis_id: PortableId
    rank: int = Field(ge=1, le=6)
    projection: Literal["perspective", "orthographic"]
    intrinsics: CameraIntrinsics
    pose: CameraPoseHypothesis
    confidence: float = Field(ge=0, le=1)
    evidence_cue_ids: list[PortableId] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    underconstrained: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_projection_intrinsics(self) -> CameraHypothesis:
        """Require projection-specific intrinsics without inventing incompatible values."""

        if self.projection == "perspective":
            if self.intrinsics.focal_length_mm is None:
                raise ValueError("perspective hypotheses require focal_length_mm")
            if self.intrinsics.ortho_scale_normalized is not None:
                raise ValueError("perspective hypotheses cannot declare ortho scale")
        else:
            if self.intrinsics.ortho_scale_normalized is None:
                raise ValueError("orthographic hypotheses require ortho scale")
            if self.intrinsics.focal_length_mm is not None:
                raise ValueError("orthographic hypotheses cannot declare focal length")
        if len(self.evidence_cue_ids) != len(set(self.evidence_cue_ids)):
            raise ValueError("camera evidence cue IDs must be unique per hypothesis")
        return self


class CameraHypothesisSet(ReferenceEvidenceStrictModel):
    """Bind camera alternatives; producer/version remain in EvidenceProvenance."""

    schema_version: Literal["0.1.0"]
    hypothesis_set_id: PortableId
    run_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    dispatch_id: PortableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    reference_evidence_path: RelativePath
    reference_evidence_sha256: Sha256
    evidence_cues: list[CameraEvidenceCue] = Field(min_length=1)
    hypotheses: list[CameraHypothesis] = Field(min_length=2, max_length=6)
    staging_hypothesis_id: PortableId
    projection_ambiguity: Literal["constrained", "ambiguous", "underconstrained"]
    ambiguity_reasons: list[str] = Field(default_factory=list)
    canonical_camera_mutated: Literal[False] = False
    canonical_promotion_allowed: Literal[False] = False
    provenance: EvidenceProvenance
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_hypothesis_binding(self) -> CameraHypothesisSet:
        """Require ranked alternatives, valid cues, and both projection families."""

        identifiers = [item.hypothesis_id for item in self.hypotheses]
        ranks = [item.rank for item in self.hypotheses]
        cue_ids = {item.cue_id for item in self.evidence_cues}
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("camera hypothesis IDs must be unique")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("camera hypotheses must have contiguous rank order")
        if self.staging_hypothesis_id not in set(identifiers):
            raise ValueError("staging_hypothesis_id must reference a hypothesis")
        missing_cues = sorted(
            {
                cue_id
                for item in self.hypotheses
                for cue_id in item.evidence_cue_ids
                if cue_id not in cue_ids
            }
        )
        if missing_cues:
            raise ValueError(f"camera hypotheses reference missing cues: {missing_cues}")
        projections = {item.projection for item in self.hypotheses}
        if projections != {"perspective", "orthographic"}:
            raise ValueError("camera hypothesis set must preserve both projection families")
        if self.projection_ambiguity != "constrained" and not self.ambiguity_reasons:
            raise ValueError("ambiguous camera sets require ambiguity reasons")
        return self


class ReferenceEvidenceRunResult(ReferenceEvidenceStrictModel):
    """Return exact output paths and hashes from one immutable evidence run."""

    schema_version: Literal["0.1.0"]
    run_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    dispatch_id: PortableId
    input_sha256: Sha256
    source_image: EvidenceArtifact
    reference_evidence_path: RelativePath
    reference_evidence_sha256: Sha256
    camera_hypothesis_set_path: RelativePath
    camera_hypothesis_set_sha256: Sha256
    summary_path: RelativePath
    summary_sha256: Sha256
    source_fingerprint: Sha256
    provenance: EvidenceProvenance
    created_at: AwareDatetime
