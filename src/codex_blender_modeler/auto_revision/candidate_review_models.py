"""Hash-bound contracts for isolated standard revision candidate review."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..models import StrictModel

SHA256_PATTERN = r"^[0-9a-f]{64}$"
TRIAL_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,95}$"


def _validate_relative_path(value: str) -> str:
    """Require one normalized job-relative path without traversal or drive syntax."""

    if not value or "\x00" in value or "\\" in value or ":" in value or value.startswith("/"):
        raise ValueError("candidate-review paths must be normalized job-relative POSIX paths")
    parts = PurePosixPath(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("candidate-review paths must not escape the owning job")
    return value


class CandidateReviewArtifact(StrictModel):
    """Bind one immutable candidate-review artifact to its job-relative path and hash."""

    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        """Keep artifact references portable and contained by the owning job."""

        return _validate_relative_path(value)


class CandidateReviewScore(StrictModel):
    """Record the comparable direct-reference scores used for one review decision."""

    baseline_direct_score: float = Field(ge=0, le=1)
    candidate_direct_score: float = Field(ge=0, le=1)
    direct_score_delta: float
    baseline_silhouette_iou: float = Field(ge=0, le=1)
    candidate_silhouette_iou: float = Field(ge=0, le=1)
    silhouette_delta: float
    minimum_direct_improvement: float = Field(ge=0, le=1)


class CandidateReviewDecision(StrictModel):
    """Freeze an isolated before/after evaluation before canonical promotion approval."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    review_kind: Literal["standard_candidate_review_v1"] = "standard_candidate_review_v1"
    job_id: str
    trial_id: str = Field(pattern=TRIAL_ID_PATTERN)
    workflow_id: str | None = None
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    source_hashes: dict[str, str]
    revision_plan: CandidateReviewArtifact
    baseline_scene_spec: CandidateReviewArtifact
    candidate_scene_spec: CandidateReviewArtifact
    revision_diff: CandidateReviewArtifact
    baseline_blend: CandidateReviewArtifact
    candidate_blend: CandidateReviewArtifact
    baseline_inventory: CandidateReviewArtifact
    candidate_inventory: CandidateReviewArtifact
    baseline_validation: CandidateReviewArtifact
    candidate_validation: CandidateReviewArtifact
    baseline_qa_report: CandidateReviewArtifact
    candidate_qa_report: CandidateReviewArtifact
    baseline_qa_request: CandidateReviewArtifact
    candidate_qa_request: CandidateReviewArtifact
    baseline_qa_manifest: CandidateReviewArtifact
    candidate_qa_manifest: CandidateReviewArtifact
    baseline_constraints: CandidateReviewArtifact | None = None
    candidate_constraints: CandidateReviewArtifact | None = None
    structural_comparison: CandidateReviewArtifact | None = None
    changed_ids: list[str] = Field(default_factory=list)
    preserved_ids: list[str] = Field(default_factory=list)
    changed_paths: list[list[str | int]] = Field(default_factory=list)
    scores: CandidateReviewScore
    status: Literal["promotable", "not_improved", "regressed", "unscorable"]
    promotable: bool
    approval_required: Literal[True] = True
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evaluated_at: datetime

    @field_validator("source_hashes")
    @classmethod
    def validate_source_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        """Require non-empty normalized source keys and exact lowercase SHA-256 values."""

        if not value:
            raise ValueError("candidate review requires exact source hashes")
        for path, digest in value.items():
            _validate_relative_path(path)
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError(f"invalid source SHA-256 for {path}")
        return dict(sorted(value.items()))

    @model_validator(mode="after")
    def validate_decision(self) -> CandidateReviewDecision:
        """Keep promotion eligibility, status, and changed-ID membership consistent."""

        if self.promotable != (self.status == "promotable"):
            raise ValueError("candidate-review promotable flag must match status")
        if self.promotable and self.blockers:
            raise ValueError("promotable candidate review cannot contain blockers")
        if len(self.changed_ids) != len(set(self.changed_ids)):
            raise ValueError("candidate-review changed IDs must be unique")
        if len(self.preserved_ids) != len(set(self.preserved_ids)):
            raise ValueError("candidate-review preserved IDs must be unique")
        if set(self.changed_ids).intersection(self.preserved_ids):
            raise ValueError("changed and preserved candidate-review IDs must be disjoint")
        return self


class CandidateReviewApproval(StrictModel):
    """Record one exact, user-authored, single-use candidate promotion approval."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    approval_kind: Literal["candidate_review_promotion_v1"] = "candidate_review_promotion_v1"
    approval_id: str
    job_id: str
    trial_id: str = Field(pattern=TRIAL_ID_PATTERN)
    decision_sha256: str = Field(pattern=SHA256_PATTERN)
    baseline_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    approved_by: Literal["user"] = "user"
    approval_note: str | None = Field(default=None, max_length=1000)
    approved_at: datetime
    one_time: Literal[True] = True
    used: bool = False
    used_at: datetime | None = None

    @model_validator(mode="after")
    def validate_usage(self) -> CandidateReviewApproval:
        """Require one consumption timestamp exactly when the approval is used."""

        if self.used != (self.used_at is not None):
            raise ValueError("candidate-review used state and used_at must agree")
        return self


class CandidateReviewPromotionReceipt(StrictModel):
    """Bind canonical promotion and final rebuild evidence to one approved decision."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    promotion_kind: Literal["candidate_review_promotion_v1"] = "candidate_review_promotion_v1"
    job_id: str
    trial_id: str = Field(pattern=TRIAL_ID_PATTERN)
    workflow_id: str | None = None
    decision_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_identity_sha256: str = Field(pattern=SHA256_PATTERN)
    previous_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    candidate_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    final_canonical_sha256: str = Field(pattern=SHA256_PATTERN)
    archived_scene_spec: CandidateReviewArtifact | None = None
    final_blend: CandidateReviewArtifact
    final_inventory: CandidateReviewArtifact
    final_validation: CandidateReviewArtifact
    final_build_fingerprint: str = Field(pattern=SHA256_PATTERN)
    status: Literal["promoted", "rolled_back"]
    promoted_at: datetime
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_final_hash(self) -> CandidateReviewPromotionReceipt:
        """Require successful promotion to leave the candidate as the canonical SceneSpec."""

        if self.status == "promoted" and (
            self.final_canonical_sha256 != self.candidate_scene_spec_sha256
        ):
            raise ValueError("promoted receipt must preserve the exact candidate hash")
        if self.status == "rolled_back" and (
            self.final_canonical_sha256 != self.previous_canonical_sha256
        ):
            raise ValueError("rolled-back receipt must restore the previous canonical hash")
        return self


class CandidateReviewReportManifest(StrictModel):
    """Bind one derived human review PDF to exact candidate decision evidence."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    report_kind: Literal["candidate_review_v1"] = "candidate_review_v1"
    job_id: str
    trial_id: str = Field(pattern=TRIAL_ID_PATTERN)
    decision: CandidateReviewArtifact
    pdf: CandidateReviewArtifact
    sources: list[CandidateReviewArtifact] = Field(min_length=1)
    source_fingerprint: str = Field(pattern=SHA256_PATTERN)
    font: str
    generated_at: datetime
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sources(self) -> CandidateReviewReportManifest:
        """Require the exact decision artifact to participate in the PDF source set."""

        identities = {(item.path, item.sha256) for item in self.sources}
        if (self.decision.path, self.decision.sha256) not in identities:
            raise ValueError("candidate-review PDF sources must include the exact decision")
        return self
