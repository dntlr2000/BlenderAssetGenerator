"""Strict contracts for the Autonomous Quality integrated evidence layer."""

from __future__ import annotations

import hashlib
import json
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
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
JOB_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


def _validate_relative_path(value: str) -> str:
    """Require one normalized portable path that cannot escape its evidence root."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if PurePosixPath(value).as_posix() != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
StableId = Annotated[str, Field(pattern=ID_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]
QualityAxis = Literal[
    "reference_alignment",
    "structural_integrity",
    "material_fidelity",
    "production_readiness",
]
EvidenceStatus = Literal["available", "degraded", "unavailable"]
MetricStatus = Literal["passed", "warning", "failed", "unscorable"]
ReportOutcome = Literal["passed", "needs_revision", "unscorable", "blocked"]
ReentryStage = Literal["v0.4", "v0.5", "v0.6", "v0.7", "manual_review"]


class IntegratedQualityStrictModel(BaseModel):
    """Reject undeclared fields and non-finite measurements in new quality contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class ProducerIdentity(IntegratedQualityStrictModel):
    """Identify the exact component and implementation version that emitted evidence."""

    name: StableId
    version: str = Field(min_length=1, max_length=64)


class QualityArtifact(IntegratedQualityStrictModel):
    """Bind one immutable quality input to its relative path and exact digest."""

    artifact_id: StableId
    kind: StableId
    relative_path: RelativePath
    sha256: Sha256
    producer: ProducerIdentity
    produced_at: AwareDatetime


def quality_artifact_input_sha256(artifacts: list[QualityArtifact]) -> str:
    """Hash the ordered exact-artifact provenance used to construct a profile."""

    encoded = json.dumps(
        [item.model_dump(mode="json") for item in artifacts],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class QualityProvenance(IntegratedQualityStrictModel):
    """Freeze the job, workflow, dispatch, source, and exact input artifact identities."""

    job_id: JobId
    workflow_id: StableId
    dispatch_id: StableId
    source_fingerprint: Sha256
    input_sha256: Sha256
    artifacts: list[QualityArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_artifacts(self) -> QualityProvenance:
        """Require unique artifact IDs and paths so evidence cannot be ambiguously rebound."""

        identifiers = [item.artifact_id for item in self.artifacts]
        paths = [item.relative_path for item in self.artifacts]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("quality provenance artifact IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("quality provenance artifact paths must be unique")
        return self


class EvidenceAvailability(IntegratedQualityStrictModel):
    """Record whether an expected evidence channel is usable without inventing a score."""

    evidence_id: StableId
    axis: QualityAxis
    status: EvidenceStatus
    artifact_id: StableId | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_artifact_binding(self) -> EvidenceAvailability:
        """Require exact artifacts for usable evidence and forbid them for unavailable evidence."""

        if self.status in {"available", "degraded"} and self.artifact_id is None:
            raise ValueError("available or degraded evidence requires an artifact_id")
        if self.status == "unavailable" and self.artifact_id is not None:
            raise ValueError("unavailable evidence cannot claim an artifact_id")
        if self.status == "unavailable" and self.confidence != 0:
            raise ValueError("unavailable evidence must use confidence=0")
        return self


class QualityMetric(IntegratedQualityStrictModel):
    """Store one independently interpreted measurement without collapsing quality axes."""

    metric_id: StableId
    status: MetricStatus
    value: float | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    threshold: float | None = None
    direction: Literal["higher_is_better", "lower_is_better", "boolean"] | None = None
    confidence: float = Field(ge=0, le=1)
    critical: bool = False
    evidence_ids: list[StableId] = Field(default_factory=list)
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_measurement(self) -> QualityMetric:
        """Ensure unscorable metrics never carry fabricated numeric measurements."""

        if self.status == "unscorable":
            if self.value is not None or self.confidence != 0:
                raise ValueError("unscorable metrics require value=None and confidence=0")
        elif self.value is None:
            raise ValueError("scorable metrics require a numeric value")
        if self.threshold is not None and self.direction is None:
            raise ValueError("thresholded metrics require a comparison direction")
        return self


class QualityAxisResult(IntegratedQualityStrictModel):
    """Summarize one quality axis while preserving all underlying metric evidence."""

    axis: QualityAxis
    required: bool = True
    status: MetricStatus
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    metrics: list[QualityMetric] = Field(default_factory=list)
    evidence_ids: list[StableId] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_axis_state(self) -> QualityAxisResult:
        """Keep axis status consistent and mark missing evidence as explicitly unscorable."""

        metric_ids = [item.metric_id for item in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("quality axis metric IDs must be unique")
        if self.status == "unscorable":
            if self.score is not None or self.confidence != 0 or not self.limitations:
                raise ValueError(
                    "unscorable axes require score=None, confidence=0, and a limitation"
                )
        elif self.score is None:
            raise ValueError("scorable axes require a normalized score")
        if self.status == "passed" and any(item.status == "failed" for item in self.metrics):
            raise ValueError("a passed axis cannot contain a failed metric")
        if self.status != "unscorable" and any(
            item.status == "unscorable" for item in self.metrics
        ):
            raise ValueError("an axis containing unscorable metrics must be unscorable")
        return self


class QualityGateRule(IntegratedQualityStrictModel):
    """Declare one hard-gate dependency on a named quality axis."""

    gate_id: StableId
    axis: QualityAxis
    required: bool = True
    accepted_statuses: list[Literal["passed", "warning"]] = Field(
        default_factory=lambda: ["passed"]
    )
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_status_set(self) -> QualityGateRule:
        """Require a non-empty unique set of statuses that can satisfy the gate."""

        if not self.accepted_statuses:
            raise ValueError("quality gate accepted_statuses cannot be empty")
        if len(self.accepted_statuses) != len(set(self.accepted_statuses)):
            raise ValueError("quality gate accepted_statuses must be unique")
        return self


class AxisThreshold(IntegratedQualityStrictModel):
    """Configure pass and warning boundaries for one independently reported axis."""

    axis: QualityAxis
    required: bool = True
    pass_score: float = Field(ge=0, le=1)
    warning_score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> AxisThreshold:
        """Require the pass boundary to be at least as strict as the warning boundary."""

        if self.pass_score < self.warning_score:
            raise ValueError("pass_score must be greater than or equal to warning_score")
        return self


class QualityGateProfile(IntegratedQualityStrictModel):
    """Freeze integrated quality thresholds and hard-gate policy as an immutable profile."""

    schema_version: Literal["0.1.0"]
    profile_id: StableId
    job_id: JobId
    workflow_id: StableId
    dispatch_id: StableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: ProducerIdentity
    provenance: list[QualityArtifact]
    created_at: AwareDatetime
    axis_thresholds: list[AxisThreshold] = Field(min_length=1)
    gate_rules: list[QualityGateRule] = Field(default_factory=list)
    meaningful_gain_min: float = Field(default=0.01, gt=0, le=1)
    critical_regression_tolerance: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_unique_policy(self) -> QualityGateProfile:
        """Require exact provenance and unique policy identities."""

        axes = [item.axis for item in self.axis_thresholds]
        gate_ids = [item.gate_id for item in self.gate_rules]
        artifact_ids = [item.artifact_id for item in self.provenance]
        artifact_paths = [item.relative_path for item in self.provenance]
        if self.input_sha256 != quality_artifact_input_sha256(self.provenance):
            raise ValueError("quality profile input_sha256 differs from provenance")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("quality profile provenance artifact IDs must be unique")
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("quality profile provenance artifact paths must be unique")
        if len(axes) != len(set(axes)):
            raise ValueError("quality profile axis thresholds must be unique")
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("quality profile gate IDs must be unique")
        return self

    def threshold_for(self, axis: QualityAxis) -> AxisThreshold | None:
        """Return the configured threshold for one axis without adding a default implicitly."""

        return next((item for item in self.axis_thresholds if item.axis == axis), None)


class HardGateResult(IntegratedQualityStrictModel):
    """Record one fail-closed gate result independently from weighted quality observations."""

    gate_id: StableId
    axis: QualityAxis
    status: Literal["passed", "failed", "unscorable"]
    required: bool
    blocking: bool
    evidence_ids: list[StableId] = Field(default_factory=list)
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_blocking_state(self) -> HardGateResult:
        """Allow only failed required gates to claim a definitive blocking failure."""

        if self.blocking != (self.required and self.status == "failed"):
            raise ValueError("blocking must be true exactly for failed required gates")
        return self


class ReentryRecommendation(IntegratedQualityStrictModel):
    """Route a measured quality issue back to the earliest responsible authoring stage."""

    recommendation_id: StableId
    stage: ReentryStage
    axis: QualityAxis | None = None
    target_ids: list[StableId] = Field(default_factory=list)
    reason_codes: list[StableId] = Field(min_length=1)
    message: str = Field(min_length=1)


class IntegratedQualityReport(IntegratedQualityStrictModel):
    """Authoritatively combine hard gates and independent quality axes without a weighted sum."""

    schema_version: Literal["0.1.0"]
    report_id: StableId
    job_id: JobId
    workflow_id: StableId
    dispatch_id: StableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    gate_profile_id: StableId
    gate_profile_sha256: Sha256
    provenance: QualityProvenance
    producer: ProducerIdentity
    created_at: AwareDatetime
    outcome: ReportOutcome
    quality_accepted: bool
    legacy_v06_direct_score: float | None = Field(default=None, ge=0, le=1)
    hard_gates: list[HardGateResult] = Field(default_factory=list)
    axes: list[QualityAxisResult] = Field(min_length=1)
    evidence_availability: list[EvidenceAvailability] = Field(min_length=1)
    blocking_reasons: list[str] = Field(default_factory=list)
    reentry: list[ReentryRecommendation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report_bindings(self) -> IntegratedQualityReport:
        """Enforce identity, evidence, score-preservation, and aggregate outcome invariants."""

        identity = (self.job_id, self.workflow_id, self.dispatch_id)
        provenance_identity = (
            self.provenance.job_id,
            self.provenance.workflow_id,
            self.provenance.dispatch_id,
        )
        if identity != provenance_identity:
            raise ValueError("integrated quality identity must match its provenance")
        if self.input_sha256 != self.provenance.input_sha256:
            raise ValueError("integrated quality input SHA-256 must match its provenance")
        if self.source_fingerprint != self.provenance.source_fingerprint:
            raise ValueError("integrated quality source fingerprint must match its provenance")
        axis_names = [item.axis for item in self.axes]
        gate_ids = [item.gate_id for item in self.hard_gates]
        evidence_ids = [item.evidence_id for item in self.evidence_availability]
        if len(axis_names) != len(set(axis_names)):
            raise ValueError("integrated quality axes must be unique")
        if len(gate_ids) != len(set(gate_ids)):
            raise ValueError("integrated quality hard-gate IDs must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("integrated quality evidence IDs must be unique")
        artifact_ids = {item.artifact_id for item in self.provenance.artifacts}
        for evidence in self.evidence_availability:
            if evidence.artifact_id is not None and evidence.artifact_id not in artifact_ids:
                raise ValueError("quality evidence references an unknown provenance artifact")
        known_evidence = set(evidence_ids)
        used_evidence = {
            evidence_id
            for axis in self.axes
            for evidence_id in axis.evidence_ids
        } | {
            evidence_id
            for axis in self.axes
            for metric in axis.metrics
            for evidence_id in metric.evidence_ids
        } | {
            evidence_id
            for gate in self.hard_gates
            for evidence_id in gate.evidence_ids
        }
        if not used_evidence.issubset(known_evidence):
            raise ValueError("quality result references undeclared evidence")
        reference = next(
            (axis for axis in self.axes if axis.axis == "reference_alignment"),
            None,
        )
        if self.legacy_v06_direct_score is not None:
            if reference is None:
                raise ValueError("legacy direct score requires a reference-alignment axis")
            direct = next(
                (
                    metric.value
                    for metric in reference.metrics
                    if metric.metric_id == "reference.v06_overall_direct_score"
                ),
                None,
            )
            if direct is None or direct != self.legacy_v06_direct_score:
                raise ValueError("legacy V0.6 direct score must be copied without modification")
        failed_required = any(item.blocking for item in self.hard_gates)
        unscorable_required_gate = any(
            item.required and item.status == "unscorable" for item in self.hard_gates
        )
        has_unscorable_axis = any(
            item.required and item.status == "unscorable" for item in self.axes
        )
        has_nonpassing_axis = any(
            item.required and item.status in {"warning", "failed"} for item in self.axes
        )
        expected = (
            "blocked"
            if failed_required
            else "unscorable"
            if unscorable_required_gate or has_unscorable_axis
            else "needs_revision"
            if has_nonpassing_axis
            else "passed"
        )
        if self.outcome != expected or self.quality_accepted != (expected == "passed"):
            raise ValueError("integrated quality outcome does not match gate and axis evidence")
        if failed_required != bool(self.blocking_reasons):
            raise ValueError("blocking reasons are required only for definitive hard-gate failures")
        return self


class RankableQualityCandidate(IntegratedQualityStrictModel):
    """Describe one immutable candidate using only independent gains and change cost."""

    candidate_id: StableId
    candidate_sha256: Sha256
    report_path: RelativePath
    report_sha256: Sha256
    gate_status: Literal["passed", "unscorable", "failed"]
    critical_regressions: list[StableId] = Field(default_factory=list)
    meaningful_gain: bool
    gains: dict[QualityAxis, float] = Field(min_length=1)
    changed_path_count: int = Field(ge=0)
    change_magnitude: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_candidate(self) -> RankableQualityCandidate:
        """Require unique regression IDs and reject a gain claim contradicted by all axes."""

        if len(self.critical_regressions) != len(set(self.critical_regressions)):
            raise ValueError("critical regression IDs must be unique")
        if self.meaningful_gain and max(self.gains.values()) <= 0:
            raise ValueError("meaningful_gain requires at least one positive axis gain")
        return self


class CandidateRankRecord(IntegratedQualityStrictModel):
    """Explain one deterministic candidate position in the lexicographic ordering."""

    candidate_id: StableId
    rank: int = Field(ge=1)
    pareto_front: int = Field(ge=0)
    selected: bool
    reason: str = Field(min_length=1)


class CandidateRanking(IntegratedQualityStrictModel):
    """Preserve the complete candidate ordering without synthesizing a weighted score."""

    schema_version: Literal["0.1.0"]
    ranking_id: StableId
    job_id: JobId
    workflow_id: StableId
    dispatch_id: StableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    provenance: QualityProvenance
    producer: ProducerIdentity
    created_at: AwareDatetime
    selected_candidate_id: StableId
    pareto_candidate_ids: list[StableId] = Field(min_length=1)
    records: list[CandidateRankRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ranking(self) -> CandidateRanking:
        """Require exact provenance, one selection, and contiguous deterministic ranks."""

        identity = (self.job_id, self.workflow_id, self.dispatch_id)
        provenance_identity = (
            self.provenance.job_id,
            self.provenance.workflow_id,
            self.provenance.dispatch_id,
        )
        if identity != provenance_identity:
            raise ValueError("candidate ranking identity must match its provenance")
        if self.input_sha256 != self.provenance.input_sha256:
            raise ValueError("candidate ranking input SHA-256 must match its provenance")
        if self.source_fingerprint != self.provenance.source_fingerprint:
            raise ValueError("candidate ranking source fingerprint must match its provenance")
        if self.input_sha256 != quality_artifact_input_sha256(self.provenance.artifacts):
            raise ValueError("candidate ranking input_sha256 differs from provenance")
        identifiers = [item.candidate_id for item in self.records]
        ranks = [item.rank for item in self.records]
        selected = [item.candidate_id for item in self.records if item.selected]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate ranking IDs must be unique")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("candidate ranks must be contiguous and ordered")
        if selected != [self.selected_candidate_id]:
            raise ValueError("candidate ranking requires exactly one selected record")
        if not set(self.pareto_candidate_ids).issubset(set(identifiers)):
            raise ValueError("Pareto candidate IDs must exist in ranking records")
        return self


class IntegratedQualityReportManifest(IntegratedQualityStrictModel):
    """Bind authoritative JSON and optional derived PDF to exact report provenance."""

    schema_version: Literal["0.1.0"]
    report_id: StableId
    job_id: JobId
    workflow_id: StableId
    dispatch_id: StableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    json_path: RelativePath
    json_sha256: Sha256
    pdf_path: RelativePath | None = None
    pdf_sha256: Sha256 | None = None
    provenance: QualityProvenance
    producer: ProducerIdentity
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_pdf_pair(self) -> IntegratedQualityReportManifest:
        """Require exact provenance and complete JSON/PDF artifact bindings."""

        if (self.pdf_path is None) != (self.pdf_sha256 is None):
            raise ValueError("PDF path and SHA-256 must be present together")
        identity = (self.job_id, self.workflow_id, self.dispatch_id)
        provenance_identity = (
            self.provenance.job_id,
            self.provenance.workflow_id,
            self.provenance.dispatch_id,
        )
        if identity != provenance_identity:
            raise ValueError("integrated quality manifest identity must match its provenance")
        if self.input_sha256 != self.provenance.input_sha256:
            raise ValueError("integrated quality manifest input SHA-256 must match provenance")
        if self.source_fingerprint != self.provenance.source_fingerprint:
            raise ValueError("integrated quality manifest source must match provenance")
        if self.input_sha256 != quality_artifact_input_sha256(self.provenance.artifacts):
            raise ValueError("integrated quality manifest input_sha256 differs from provenance")
        bindings = {
            (item.relative_path, item.sha256) for item in self.provenance.artifacts
        }
        expected = {(self.json_path, self.json_sha256)}
        if self.pdf_path is not None and self.pdf_sha256 is not None:
            expected.add((self.pdf_path, self.pdf_sha256))
        if bindings != expected:
            raise ValueError("integrated quality manifest provenance differs from outputs")
        return self
