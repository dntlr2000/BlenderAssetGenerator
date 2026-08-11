"""Strict parallel contracts for Integrated Quality 0.2 companion evidence."""

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

SCHEMA_VERSION = "0.2.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
JOB_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


def _validate_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by its declared evidence root."""

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
MetricState = Literal["scored", "unscorable"]
Authority = Literal["authoritative", "advisory", "unavailable"]
GateStatus = Literal["passed", "failed", "unscorable"]
FindingCategory = Literal[
    "camera",
    "contour",
    "semantic",
    "local_proportion",
    "topology",
    "uv",
    "normal",
    "missing_evidence",
    "restricted_scope",
]


class IntegratedQualityV02StrictModel(BaseModel):
    """Reject undeclared fields and non-finite values in IQ 0.2 contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class ProducerIdentityV02(IntegratedQualityV02StrictModel):
    """Identify the exact host component that produced one companion report."""

    name: StableId
    version: str = Field(min_length=1, max_length=64)


class ContourEvidenceBindingV02(IntegratedQualityV02StrictModel):
    """Bind global contour inputs without granting generated evidence pass authority."""

    evidence_id: StableId
    origin: Literal[
        "observed",
        "actual_blender",
        "inferred",
        "generated",
        "provider",
        "unavailable",
    ]
    authority: Authority
    artifact_path: RelativePath | None = None
    artifact_sha256: Sha256 | None = None
    camera_sha256: Sha256

    @model_validator(mode="after")
    def validate_authority(self) -> ContourEvidenceBindingV02:
        """Allow only observed evidence to be authoritative and bind usable artifacts."""

        expected = (
            "authoritative"
            if self.origin in {"observed", "actual_blender"}
            else "unavailable"
            if self.origin == "unavailable"
            else "advisory"
        )
        if self.authority != expected:
            raise ValueError("contour evidence authority does not match its origin")
        bound = self.artifact_path is not None and self.artifact_sha256 is not None
        if self.origin == "unavailable" and bound:
            raise ValueError("unavailable contour evidence cannot bind an artifact")
        if self.origin != "unavailable" and not bound:
            raise ValueError("usable contour evidence requires path and SHA-256")
        if (self.artifact_path is None) != (self.artifact_sha256 is None):
            raise ValueError("contour artifact path and SHA-256 must be paired")
        return self


class SemanticEvidenceBindingV02(IntegratedQualityV02StrictModel):
    """Bind semantic masks and restrict authority to registered observed evidence."""

    evidence_id: StableId
    semantic_id: StableId
    origin: Literal[
        "registered_observed",
        "observed",
        "inferred",
        "generated",
        "provider",
        "unavailable",
    ]
    authority: Authority
    artifact_path: RelativePath | None = None
    artifact_sha256: Sha256 | None = None
    camera_sha256: Sha256
    registration_receipt_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_registered_authority(self) -> SemanticEvidenceBindingV02:
        """Prevent non-registered semantic masks from becoming authoritative."""

        expected = (
            "authoritative"
            if self.origin == "registered_observed"
            else "unavailable"
            if self.origin == "unavailable"
            else "advisory"
        )
        if self.authority != expected:
            raise ValueError("semantic evidence authority does not match its origin")
        bound = self.artifact_path is not None and self.artifact_sha256 is not None
        if self.origin == "unavailable" and bound:
            raise ValueError("unavailable semantic evidence cannot bind an artifact")
        if self.origin != "unavailable" and not bound:
            raise ValueError("usable semantic evidence requires path and SHA-256")
        if (self.artifact_path is None) != (self.artifact_sha256 is None):
            raise ValueError("semantic artifact path and SHA-256 must be paired")
        if self.origin == "registered_observed":
            if self.registration_receipt_sha256 is None:
                raise ValueError("registered observed evidence requires its receipt SHA-256")
        elif self.registration_receipt_sha256 is not None:
            raise ValueError("only registered observed evidence may bind a registration receipt")
        return self


class ContourMetricsV02(IntegratedQualityV02StrictModel):
    """Store exact boundary and distance-transform contour measurements."""

    metric_id: StableId
    status: MetricState
    authority: Authority
    evidence_ids: list[StableId] = Field(min_length=1)
    reference_mask_sha256: Sha256 | None = None
    candidate_mask_sha256: Sha256
    camera_sha256: Sha256
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    reference_boundary_pixels: int = Field(ge=0)
    candidate_boundary_pixels: int = Field(ge=0)
    boundary_tolerance_px: float = Field(ge=0)
    boundary_tolerance_diagonal_fraction: float = Field(ge=0, le=1)
    boundary_precision: float | None = Field(default=None, ge=0, le=1)
    boundary_recall: float | None = Field(default=None, ge=0, le=1)
    boundary_f_score: float | None = Field(default=None, ge=0, le=1)
    edge_distance_transform_chamfer_norm: float | None = Field(default=None, ge=0)
    distance_transform_method: Literal["exact_squared_euclidean_v1"] = (
        "exact_squared_euclidean_v1"
    )
    normalization_basis: Literal["image_diagonal"] = "image_diagonal"
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_measurement_state(self) -> ContourMetricsV02:
        """Require complete values only for scored contour evidence."""

        values = (
            self.boundary_precision,
            self.boundary_recall,
            self.boundary_f_score,
            self.edge_distance_transform_chamfer_norm,
        )
        if self.status == "unscorable":
            if any(value is not None for value in values) or not self.limitations:
                raise ValueError("unscorable contour metrics require no scores and a limitation")
        elif any(value is None for value in values):
            raise ValueError("scored contour metrics require every contour score")
        elif self.reference_mask_sha256 is None:
            raise ValueError("scored contour metrics require the reference mask SHA-256")
        if self.authority == "unavailable" and self.status != "unscorable":
            raise ValueError("unavailable contour evidence must be unscorable")
        return self


class SemanticMetricV02(IntegratedQualityV02StrictModel):
    """Store one per-semantic comparison without averaging away critical missing parts."""

    metric_id: StableId
    semantic_id: StableId
    critical: bool
    authority: Authority
    reference_evidence: SemanticEvidenceBindingV02
    candidate_evidence_id: StableId
    status: MetricState
    mask_iou: float | None = Field(default=None, ge=0, le=1)
    missing_candidate: bool = False
    contour: ContourMetricsV02
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_semantic_metric(self) -> SemanticMetricV02:
        """Keep semantic authority and missing-part values consistent with bound evidence."""

        if self.authority != self.reference_evidence.authority:
            raise ValueError("semantic metric authority must match reference evidence")
        if self.status == "unscorable":
            if self.mask_iou is not None or not self.limitations:
                raise ValueError("unscorable semantic metrics require no IoU and a limitation")
        elif self.mask_iou is None:
            raise ValueError("scored semantic metrics require mask_iou")
        if self.missing_candidate and self.mask_iou != 0:
            raise ValueError("a missing candidate semantic must have mask_iou=0")
        if self.reference_evidence.authority == "unavailable" and self.status != "unscorable":
            raise ValueError("unavailable semantic reference evidence must be unscorable")
        return self


class LandmarkEvidenceV02(IntegratedQualityV02StrictModel):
    """Describe one landmark without inventing a missing source or candidate coordinate."""

    landmark_id: StableId
    semantic_id: StableId
    origin: Literal["observed", "inferred", "generated", "provider", "unavailable"]
    authority: Authority
    source_position_norm: tuple[float, float] | None = None
    candidate_position_norm: tuple[float, float] | None = None
    source_artifact_sha256: Sha256 | None = None
    candidate_artifact_sha256: Sha256 | None = None
    camera_sha256: Sha256
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_landmark_evidence(self) -> LandmarkEvidenceV02:
        """Allow only observed landmarks to be authoritative and reject fabricated coordinates."""

        expected = (
            "authoritative"
            if self.origin == "observed"
            else "unavailable"
            if self.origin == "unavailable"
            else "advisory"
        )
        if self.authority != expected:
            raise ValueError("landmark authority does not match its origin")
        for point in (self.source_position_norm, self.candidate_position_norm):
            if point is not None and not all(0 <= value <= 1 for value in point):
                raise ValueError("landmark coordinates must be normalized to [0, 1]")
        if self.origin == "unavailable":
            if self.source_position_norm is not None or self.source_artifact_sha256 is not None:
                raise ValueError("unavailable landmark evidence cannot claim a source coordinate")
            if self.confidence != 0:
                raise ValueError("unavailable landmark evidence requires confidence=0")
        elif self.source_position_norm is None or self.source_artifact_sha256 is None:
            raise ValueError("usable landmark evidence requires a source coordinate and hash")
        if self.candidate_position_norm is None and self.candidate_artifact_sha256 is not None:
            raise ValueError("candidate landmark hash requires a candidate coordinate")
        if self.candidate_position_norm is not None and self.candidate_artifact_sha256 is None:
            raise ValueError("candidate landmark coordinate requires its artifact hash")
        return self


class LandmarkMetricV02(IntegratedQualityV02StrictModel):
    """Store normalized landmark reprojection error or an explicit unscorable state."""

    metric_id: StableId
    landmark_id: StableId
    semantic_id: StableId
    authority: Authority
    status: MetricState
    source_artifact_sha256: Sha256 | None = None
    candidate_artifact_sha256: Sha256 | None = None
    camera_sha256: Sha256
    reprojection_error_norm: float | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_landmark_metric(self) -> LandmarkMetricV02:
        """Require missing landmarks to remain unscorable rather than receiving a default score."""

        if self.status == "unscorable":
            if self.reprojection_error_norm is not None or self.confidence != 0:
                raise ValueError("unscorable landmarks require no error and confidence=0")
            if not self.limitations:
                raise ValueError("unscorable landmarks require a limitation")
        elif self.reprojection_error_norm is None:
            raise ValueError("scored landmarks require reprojection_error_norm")
        return self


class MultiviewObservationV02(IntegratedQualityV02StrictModel):
    """Bind one structural companion view and its independent measurements."""

    view_id: StableId
    origin: Literal["actual_blender", "generated", "provider", "unavailable"]
    authority: Authority
    artifact_path: RelativePath | None = None
    artifact_sha256: Sha256 | None = None
    camera_sha256: Sha256 | None = None
    silhouette_stability: float | None = Field(default=None, ge=0, le=1)
    semantic_placement_score: float | None = Field(default=None, ge=0, le=1)
    visible_semantic_ids: list[StableId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_multiview_observation(self) -> MultiviewObservationV02:
        """Restrict structural authority to actual Blender evidence and bind every scored view."""

        expected = (
            "authoritative"
            if self.origin == "actual_blender"
            else "unavailable"
            if self.origin == "unavailable"
            else "advisory"
        )
        if self.authority != expected:
            raise ValueError("multiview authority does not match its origin")
        bound = self.artifact_path is not None and self.artifact_sha256 is not None
        measured = (
            self.silhouette_stability is not None
            and self.semantic_placement_score is not None
        )
        if self.origin == "unavailable":
            if bound or measured or self.camera_sha256 is not None:
                raise ValueError("unavailable multiview evidence cannot bind measurements")
        elif not bound or not measured or self.camera_sha256 is None:
            raise ValueError("usable multiview evidence requires artifact and measurements")
        if (self.artifact_path is None) != (self.artifact_sha256 is None):
            raise ValueError("multiview artifact path and SHA-256 must be paired")
        if len(self.visible_semantic_ids) != len(set(self.visible_semantic_ids)):
            raise ValueError("visible semantic IDs must be unique")
        return self


class MultiviewMetricV02(IntegratedQualityV02StrictModel):
    """Summarize authoritative multi-view consistency without using advisory views as truth."""

    metric_id: StableId
    status: MetricState
    observations: list[MultiviewObservationV02]
    authoritative_view_count: int = Field(ge=0)
    minimum_silhouette_stability: float | None = Field(default=None, ge=0, le=1)
    mean_semantic_placement_score: float | None = Field(default=None, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_multiview_metric(self) -> MultiviewMetricV02:
        """Require at least two authoritative views for a scored structural companion result."""

        expected_count = sum(
            item.authority == "authoritative" for item in self.observations
        )
        if self.authoritative_view_count != expected_count:
            raise ValueError("authoritative view count does not match observations")
        values = (
            self.minimum_silhouette_stability,
            self.mean_semantic_placement_score,
        )
        if self.status == "unscorable":
            if any(value is not None for value in values) or not self.limitations:
                raise ValueError("unscorable multiview metrics require no scores and a limitation")
        elif expected_count < 2 or any(value is None for value in values):
            raise ValueError("scored multiview metrics require at least two authoritative views")
        return self


class AdvisoryMetricV02(IntegratedQualityV02StrictModel):
    """Store depth, normal, or generated-target estimates with no pass authority."""

    metric_id: StableId
    kind: Literal["estimated_depth", "estimated_normal", "generated_target"]
    status: MetricState
    authoritative: Literal[False] = False
    value: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    version: str | None = Field(default=None, min_length=1, max_length=64)
    artifact_sha256: Sha256 | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_advisory_metric(self) -> AdvisoryMetricV02:
        """Require complete provenance for scored estimates and no fabricated unavailable value."""

        provenance = (self.provider, self.model, self.version, self.artifact_sha256)
        if self.status == "unscorable":
            if self.value is not None or self.confidence != 0:
                raise ValueError("unscorable advisory metrics require no value and confidence=0")
            if any(item is not None for item in provenance) or not self.limitations:
                raise ValueError(
                    "unscorable advisory metrics require no provenance and a limitation"
                )
        elif self.value is None or any(item is None for item in provenance):
            raise ValueError(
                "scored advisory metrics require value and complete provider provenance"
            )
        return self


class IntegratedQualityPolicyV02(IntegratedQualityV02StrictModel):
    """Freeze explicit companion thresholds without replacing V0.6 scoring."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    profile_id: StableId
    require_contour: bool = True
    minimum_boundary_f_score: float = Field(default=0.8, ge=0, le=1)
    maximum_edge_distance_transform_chamfer_norm: float = Field(default=0.05, ge=0)
    minimum_semantic_iou: float = Field(default=0.7, ge=0, le=1)
    critical_semantic_ids: list[StableId] = Field(default_factory=list)
    required_landmark_ids: list[StableId] = Field(default_factory=list)
    maximum_landmark_reprojection_error_norm: float = Field(default=0.05, ge=0)
    require_multiview: bool = False
    minimum_multiview_silhouette_stability: float = Field(default=0.7, ge=0, le=1)
    minimum_multiview_semantic_placement: float = Field(default=0.7, ge=0, le=1)
    meaningful_gain_min: float = Field(default=0.01, gt=0, le=1)
    lexicographic_metric_priority: list[StableId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_policy_ids(self) -> IntegratedQualityPolicyV02:
        """Require unique critical, landmark, and ranking metric identities."""

        groups = (
            self.critical_semantic_ids,
            self.required_landmark_ids,
            self.lexicographic_metric_priority,
        )
        if any(len(items) != len(set(items)) for items in groups):
            raise ValueError("integrated quality policy IDs must be unique within each list")
        return self


class HardGateResultV02(IntegratedQualityV02StrictModel):
    """Record a required gate before advisory or aggregate quality observations."""

    gate_id: StableId
    status: GateStatus
    required: bool
    blocking: bool
    evidence_ids: list[StableId] = Field(default_factory=list)
    finding_ids: list[StableId] = Field(default_factory=list)
    reason_code: StableId
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_blocking_state(self) -> HardGateResultV02:
        """Permit blocking only for a definitive failed required gate with unique findings."""

        if self.blocking != (self.required and self.status == "failed"):
            raise ValueError("blocking must be true exactly for failed required gates")
        if len(self.finding_ids) != len(set(self.finding_ids)):
            raise ValueError("hard-gate finding IDs must be unique")
        return self


class QualityFindingV02(IntegratedQualityV02StrictModel):
    """Classify one measured issue for deterministic phase reentry."""

    finding_id: StableId
    category: FindingCategory
    severity: Literal["warning", "high", "hard"]
    authoritative: bool = True
    target_ids: list[StableId] = Field(default_factory=list)
    evidence_ids: list[StableId] = Field(default_factory=list)
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_hard_authority(self) -> QualityFindingV02:
        """Reject hard or restricted-scope claims that lack authoritative host evidence."""

        if self.severity == "hard" and not self.authoritative:
            raise ValueError("hard findings must be authoritative")
        if self.category == "restricted_scope" and not self.authoritative:
            raise ValueError("restricted-scope findings must be authoritative")
        return self


class ReentryDecisionV02(IntegratedQualityV02StrictModel):
    """Route a finding to one machine-readable responsible stage."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    finding_id: StableId
    category: FindingCategory
    destination: Literal[
        "v0.4_structural_authoring",
        "v0.6_parametric_convergence",
        "v0.7_production_repair",
        "manual_evidence_review",
        "restricted_scope_required",
    ]
    automatic_action_allowed: Literal[False] = False
    target_ids: list[StableId] = Field(default_factory=list)
    reason_code: StableId
    message: str = Field(min_length=1)


class IntegratedQualityReportV02(IntegratedQualityV02StrictModel):
    """Combine IQ 0.2 companion metrics while preserving the legacy V0.6 score verbatim."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    report_id: StableId
    job_id: JobId
    workflow_id: StableId
    dispatch_id: StableId
    source_fingerprint: Sha256
    camera_sha256: Sha256
    input_sha256: Sha256
    legacy_v06_report_sha256: Sha256 | None = None
    legacy_v06_direct_score: float | None = Field(default=None, ge=0, le=1)
    policy: IntegratedQualityPolicyV02
    contour: ContourMetricsV02
    semantics: list[SemanticMetricV02] = Field(default_factory=list)
    landmarks: list[LandmarkMetricV02] = Field(default_factory=list)
    multiview: MultiviewMetricV02
    advisory_metrics: list[AdvisoryMetricV02] = Field(default_factory=list)
    hard_gates: list[HardGateResultV02] = Field(default_factory=list)
    findings: list[QualityFindingV02] = Field(default_factory=list)
    reentry: list[ReentryDecisionV02] = Field(default_factory=list)
    outcome: Literal["passed", "needs_revision", "unscorable", "blocked"]
    quality_accepted: bool
    revision_reasons: list[StableId] = Field(default_factory=list)
    producer: ProducerIdentityV02
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_report(self) -> IntegratedQualityReportV02:
        """Enforce score preservation, unique evidence, and hard-gate-first outcome precedence."""

        if (self.legacy_v06_report_sha256 is None) != (
            self.legacy_v06_direct_score is None
        ):
            raise ValueError("legacy V0.6 report hash and direct score must be paired")
        semantic_ids = [item.semantic_id for item in self.semantics]
        landmark_ids = [item.landmark_id for item in self.landmarks]
        gate_ids = [item.gate_id for item in self.hard_gates]
        finding_ids = [item.finding_id for item in self.findings]
        reentry_ids = [item.finding_id for item in self.reentry]
        for label, values in (
            ("semantic", semantic_ids),
            ("landmark", landmark_ids),
            ("gate", gate_ids),
            ("finding", finding_ids),
            ("reentry", reentry_ids),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"integrated quality {label} IDs must be unique")
        if set(reentry_ids) != set(finding_ids):
            raise ValueError("every finding requires exactly one reentry decision")
        finding_by_id = {item.finding_id: item for item in self.findings}
        bound_finding_ids = [
            finding_id
            for gate in self.hard_gates
            for finding_id in gate.finding_ids
        ]
        if len(bound_finding_ids) != len(set(bound_finding_ids)):
            raise ValueError("a quality finding cannot be bound to multiple hard gates")
        if set(bound_finding_ids) - set(finding_by_id):
            raise ValueError("hard gates must reference declared quality findings")
        required_gate_findings = {
            item.finding_id
            for item in self.findings
            if (item.severity == "hard" and item.authoritative)
            or item.category == "restricted_scope"
        }
        if required_gate_findings != set(bound_finding_ids):
            raise ValueError(
                "authoritative hard and restricted-scope findings require exact hard-gate bindings"
            )
        if any(gate.finding_ids and not gate.blocking for gate in self.hard_gates):
            raise ValueError("finding-bound hard gates must be failed and required")
        blocked = any(item.blocking for item in self.hard_gates)
        required_unscorable = any(
            item.required and item.status == "unscorable" for item in self.hard_gates
        )
        expected = (
            "blocked"
            if blocked
            else "unscorable"
            if required_unscorable
            else "needs_revision"
            if self.revision_reasons
            else "passed"
        )
        if self.outcome != expected or self.quality_accepted != (expected == "passed"):
            raise ValueError("IQ 0.2 outcome does not match hard-gate precedence")
        expected_revision_reasons = [
            item.finding_id
            for item in self.findings
            if item.severity in {"warning", "high"}
        ]
        if self.revision_reasons != expected_revision_reasons:
            raise ValueError(
                "revision reasons must exactly bind every warning and high finding"
            )
        if self.contour.camera_sha256 != self.camera_sha256:
            raise ValueError("contour camera SHA-256 must match the report camera")
        if any(
            item.reference_evidence.camera_sha256 != self.camera_sha256
            or item.contour.camera_sha256 != self.camera_sha256
            for item in self.semantics
        ):
            raise ValueError("semantic evidence must match the report camera SHA-256")
        if any(item.camera_sha256 != self.camera_sha256 for item in self.landmarks):
            raise ValueError("landmark evidence must match the report camera SHA-256")
        return self


class RankableCandidateV02(IntegratedQualityV02StrictModel):
    """Describe one immutable candidate for hard-gate-first Pareto ranking."""

    candidate_id: StableId
    candidate_sha256: Sha256
    report_path: RelativePath
    report_sha256: Sha256
    hard_gate_status: GateStatus
    required_evidence_available: bool
    critical_regressions: list[StableId] = Field(default_factory=list)
    meaningful_gain: bool
    gains: dict[str, float] = Field(min_length=1)
    changed_path_count: int = Field(ge=0)
    change_magnitude: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_candidate(self) -> RankableCandidateV02:
        """Reject duplicate regression IDs and malformed gain metric identities."""

        if len(self.critical_regressions) != len(set(self.critical_regressions)):
            raise ValueError("critical regression IDs must be unique")
        if any(re.fullmatch(ID_PATTERN, metric_id) is None for metric_id in self.gains):
            raise ValueError("candidate gain metric IDs must be stable identifiers")
        if self.meaningful_gain and max(self.gains.values()) <= 0:
            raise ValueError("meaningful gain requires at least one positive metric gain")
        return self


class CandidateRankRecordV02(IntegratedQualityV02StrictModel):
    """Explain eligibility and deterministic order for one candidate."""

    candidate_id: StableId
    eligible: bool
    rejection_reasons: list[StableId] = Field(default_factory=list)
    rank: int | None = Field(default=None, ge=1)
    pareto_front: int | None = Field(default=None, ge=0)
    selected: bool = False
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rank_state(self) -> CandidateRankRecordV02:
        """Keep eligible ranks and ineligible rejection evidence mutually consistent."""

        if self.eligible:
            if self.rejection_reasons or self.rank is None or self.pareto_front is None:
                raise ValueError("eligible candidates require rank/front and no rejection")
        elif not self.rejection_reasons or self.rank is not None or self.pareto_front is not None:
            raise ValueError("ineligible candidates require rejection reasons and no rank/front")
        if self.selected and not self.eligible:
            raise ValueError("an ineligible candidate cannot be selected")
        return self


class CandidateRankingV02(IntegratedQualityV02StrictModel):
    """Preserve eligible Pareto ranking or an explicit no-eligible-candidate result."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    ranking_id: StableId
    source_fingerprint: Sha256
    policy_id: StableId
    outcome: Literal["selected", "rejected_no_eligible_candidate"]
    selected_candidate_id: StableId | None = None
    pareto_candidate_ids: list[StableId] = Field(default_factory=list)
    records: list[CandidateRankRecordV02] = Field(min_length=1)
    producer: ProducerIdentityV02
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_ranking(self) -> CandidateRankingV02:
        """Require one selection only when at least one candidate is eligible."""

        identifiers = [item.candidate_id for item in self.records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("candidate ranking IDs must be unique")
        eligible = [item for item in self.records if item.eligible]
        selected = [item.candidate_id for item in self.records if item.selected]
        if self.outcome == "rejected_no_eligible_candidate":
            if eligible or selected or self.selected_candidate_id is not None:
                raise ValueError("no-eligible outcome cannot contain a selection")
            if self.pareto_candidate_ids:
                raise ValueError("no-eligible outcome cannot claim a Pareto set")
        else:
            if selected != [self.selected_candidate_id] or self.selected_candidate_id is None:
                raise ValueError("selected outcome requires exactly one selected candidate")
            ranks = [item.rank for item in eligible]
            if ranks != list(range(1, len(ranks) + 1)):
                raise ValueError("eligible candidate ranks must be contiguous")
            if not set(self.pareto_candidate_ids).issubset(
                {item.candidate_id for item in eligible}
            ):
                raise ValueError("Pareto candidates must be eligible")
        return self
