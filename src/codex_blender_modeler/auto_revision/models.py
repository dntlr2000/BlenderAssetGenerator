from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..models import StrictModel

_GROUP_FINDING_PREFIX = "direct.group_position."


class RevisionCandidate(StrictModel):
    """Represent one QA-sourced edit before it becomes an executable RevisionPlan."""

    id: str
    finding_id: str
    target_type: Literal["object", "material", "camera", "scene"]
    target_id: str | None = None
    path: list[str | int] = Field(min_length=1)
    op: Literal["set", "multiply", "add", "append"]
    value: Any
    reason: str
    evidence_sources: list[
        Literal["direct_reference", "generated_target", "constraint"]
    ] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    applicability: Literal["auto_safe", "approval_required", "manual_required"]
    acceptance_criteria: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_target(self) -> RevisionCandidate:
        """Validate target addressing and prevent generated-target-only auto edits."""

        if self.target_type in {"object", "material"} and not self.target_id:
            raise ValueError(f"{self.target_type} candidate requires target_id")
        if self.target_type in {"camera", "scene"} and self.target_id is not None:
            raise ValueError(f"{self.target_type} candidate must not set target_id")
        if set(self.evidence_sources) == {"generated_target"}:
            if self.applicability != "manual_required":
                raise ValueError("generated-target-only candidates must remain manual_required")
        return self


class RevisionCandidates(StrictModel):
    """Bind candidate edits to exact SceneSpec, camera, and QA report hashes."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    base_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    camera_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: list[RevisionCandidate] = Field(default_factory=list)
    locked_ids: list[str] = Field(default_factory=list)
    locked_paths: list[list[str | int]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidate_ids(self) -> RevisionCandidates:
        """Require stable unique candidate IDs and forbid targeting locked semantic IDs."""

        candidate_ids = [candidate.id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("revision candidate IDs must be unique")
        targeted = {
            candidate.target_id
            for candidate in self.candidates
            if candidate.target_id is not None
        }
        collisions = sorted(targeted.intersection(self.locked_ids))
        if collisions:
            raise ValueError(f"revision candidates target locked IDs: {collisions}")
        return self


class RevisionApproval(StrictModel):
    """Record one explicit, hash-bound, single-use user approval."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    approval_id: str
    job_id: str
    candidates_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_spec_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_candidate_ids: list[str] = Field(min_length=1)
    approved_by: Literal["user"] = "user"
    approved_at: str
    one_time: Literal[True] = True
    used: bool = False
    used_at: str | None = None

    @model_validator(mode="after")
    def validate_usage(self) -> RevisionApproval:
        """Require unique candidate IDs and a consumption timestamp only after use."""

        if len(self.approved_candidate_ids) != len(set(self.approved_candidate_ids)):
            raise ValueError("approved candidate IDs must be unique")
        if self.used and not self.used_at:
            raise ValueError("used approvals require used_at")
        if not self.used and self.used_at is not None:
            raise ValueError("unused approvals must not set used_at")
        return self


class ConstraintRegression(StrictModel):
    """Describe one measured constraint that became less acceptable after revision."""

    constraint_id: str
    before_status: Literal["passed", "failed", "missing", "disabled"] | None = None
    after_status: Literal["passed", "failed", "missing", "disabled"] | None = None
    before_residual_m: float | None = None
    after_residual_m: float | None = None
    before_tolerance_m: float | None = None
    after_tolerance_m: float | None = None
    before_residual_ratio: float | None = None
    after_residual_ratio: float | None = None
    reasons: list[str] = Field(min_length=1)


class ConvergenceReport(StrictModel):
    """Decide whether one approved revision improved direct evidence without regressions."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    job_id: str
    before_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    before_direct_score: float = Field(ge=0, le=1)
    after_direct_score: float = Field(ge=0, le=1)
    score_delta: float
    before_failed_constraints: int = Field(ge=0)
    after_failed_constraints: int = Field(ge=0)
    constraint_regressions: list[ConstraintRegression] = Field(default_factory=list)
    changed_ids: list[str] = Field(default_factory=list)
    preserved_ids: list[str] = Field(default_factory=list)
    status: Literal["improved", "no_change", "regressed"]
    accepted: bool
    rollback_required: bool
    reasons: list[str] = Field(default_factory=list)


def require_complete_group_candidate_selection(
    candidates: RevisionCandidates,
    selected_candidate_ids: list[str],
) -> None:
    """Reject partial selection of one synthetic coherent group-position candidate set."""

    selected = set(selected_candidate_ids)
    grouped: dict[str, set[str]] = {}
    for candidate in candidates.candidates:
        if candidate.finding_id.startswith(_GROUP_FINDING_PREFIX):
            grouped.setdefault(candidate.finding_id, set()).add(candidate.id)
    for finding_id, required_ids in sorted(grouped.items()):
        chosen = selected.intersection(required_ids)
        if chosen and chosen != required_ids:
            missing = sorted(required_ids - chosen)
            raise ValueError(
                "coherent group-position candidates must be selected together; "
                f"finding={finding_id}, missing={missing}"
            )
