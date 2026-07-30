"""Strict V0.6 contracts for one user-authorized bounded visual-convergence session."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..models import StrictModel
from ..qa.models import DirectScoringVersion

SHA256_PATTERN = r"^[0-9a-f]{64}$"
SESSION_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,95}$"
QA_RUN_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
_ABSOLUTE_WINDOWS_PATH = re.compile(r"^[A-Za-z]:")

ConvergenceOperation = Literal["set", "add", "multiply"]
ConvergencePathFamily = Literal[
    "transform.location",
    "transform.rotation_deg",
    "transform.scale",
    "geometry.dimensions",
    "geometry.depth",
    "geometry.size",
    "geometry.bevel_depth",
    "geometry.skirt_depth",
    "material.base_color",
    "material.roughness",
    "material.metallic",
    "material.emission_strength",
]
ConvergenceTerminationReason = Literal[
    "target_reached",
    "plateau",
    "no_eligible_candidates",
    "manual_review_required",
    "iteration_budget_exhausted",
    "constraint_regression",
    "stale_or_tampered",
    "cancelled",
    "failed",
]
_MANUAL_REVIEW_TERMINATION_REASONS = frozenset(
    {
        "manual_review_required",
        "no_eligible_candidates",
        "plateau",
        "iteration_budget_exhausted",
        "constraint_regression",
        "failed",
    }
)


def convergence_manual_review_required(
    termination_reason: ConvergenceTerminationReason,
) -> bool:
    """Return the one manual-review value allowed for a terminal reason."""

    return termination_reason in _MANUAL_REVIEW_TERMINATION_REASONS


def _validate_relative_path(value: str) -> str:
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


class ConvergencePathLimit(StrictModel):
    """Bound one approved SceneSpec path family and its per-iteration numeric delta."""

    path_family: ConvergencePathFamily
    allowed_operations: list[ConvergenceOperation] = Field(min_length=1)
    max_absolute_delta: float | None = Field(default=None, gt=0)
    max_relative_delta: float | None = Field(default=None, gt=0, le=10)

    @model_validator(mode="after")
    def validate_limit(self) -> ConvergencePathLimit:
        """Require unique operations and at least one finite delta boundary."""

        if len(self.allowed_operations) != len(set(self.allowed_operations)):
            raise ValueError("convergence path operations must be unique")
        if self.max_absolute_delta is None and self.max_relative_delta is None:
            raise ValueError("convergence path limits require an absolute or relative delta")
        return self


class VisualConvergenceHostSafetyEnvelope(StrictModel):
    """Freeze the host-derived maximum authority for one convergence session."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    initial_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_candidates_sha256: str = Field(pattern=SHA256_PATTERN)
    camera_fingerprint: str = Field(pattern=SHA256_PATTERN)
    scoring_version: DirectScoringVersion
    initial_direct_score: float = Field(ge=0, le=1)
    initial_silhouette_iou: float = Field(ge=0, le=1)
    target_direct_score: float = Field(ge=0, le=1)
    target_silhouette_iou: float = Field(ge=0, le=1)
    minimum_iteration_gain: float = Field(gt=0, le=1)
    minimum_candidate_confidence: float = Field(ge=0, le=1)
    max_iterations: int = Field(ge=1, le=5)
    max_candidate_groups_per_iteration: int = Field(ge=1, le=20)
    max_candidates_per_iteration: int = Field(ge=1, le=100)
    max_changed_ids_per_iteration: int = Field(ge=1, le=50)
    allowed_target_ids: list[str] = Field(min_length=1)
    locked_target_ids: list[str] = Field(default_factory=list)
    custom_mesh_target_ids: list[str] = Field(default_factory=list)
    interior_target_ids: list[str] = Field(default_factory=list)
    manual_candidate_ids: list[str] = Field(default_factory=list)
    path_limits: list[ConvergencePathLimit] = Field(min_length=1)
    allow_material_edits: Literal[False] = False
    camera_locked: Literal[True] = True
    generated_target_policy: Literal["advisory_only"] = "advisory_only"
    constraint_regression_policy: Literal["forbid"] = "forbid"

    @model_validator(mode="after")
    def validate_host_boundary(self) -> VisualConvergenceHostSafetyEnvelope:
        """Reject duplicate, contradictory, or broadened host-policy identities."""

        identity_lists = {
            "allowed_target_ids": self.allowed_target_ids,
            "locked_target_ids": self.locked_target_ids,
            "custom_mesh_target_ids": self.custom_mesh_target_ids,
            "interior_target_ids": self.interior_target_ids,
            "manual_candidate_ids": self.manual_candidate_ids,
        }
        for label, values in identity_lists.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must contain unique identities")
        collisions = sorted(
            set(self.allowed_target_ids).intersection(self.locked_target_ids)
        )
        if collisions:
            raise ValueError(
                "host safety allowed and locked target IDs overlap: "
                f"{collisions}"
            )
        unlocked_interiors = sorted(
            set(self.interior_target_ids) - set(self.locked_target_ids)
        )
        if unlocked_interiors:
            raise ValueError(
                "host safety interior targets must remain locked: "
                f"{unlocked_interiors}"
            )
        families = [item.path_family for item in self.path_limits]
        if len(families) != len(set(families)):
            raise ValueError("host safety path families must be unique")
        if any(family.startswith("material.") for family in families):
            raise ValueError("host safety envelope cannot authorize material paths")
        if self.target_direct_score < self.initial_direct_score:
            raise ValueError(
                "host safety target_direct_score cannot be below the initial score"
            )
        if self.target_silhouette_iou < self.initial_silhouette_iou:
            raise ValueError(
                "host safety target_silhouette_iou cannot be below the initial IoU"
            )
        return self


class VisualConvergencePlan(StrictModel):
    """Freeze the score target, immutable baseline, and automatic-edit envelope."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    initial_input_hashes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Exact input-directory-relative POSIX paths and SHA-256 hashes captured "
            "when the convergence plan was created. An empty map is accepted only "
            "for historical status-only plans and is never executable."
        ),
    )
    initial_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_qa_run_id: str = Field(pattern=QA_RUN_ID_PATTERN)
    initial_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_candidates_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact initial revision-candidate file hash. None is accepted only for "
            "historical plans created before candidate binding was introduced."
        ),
    )
    initial_build_fingerprint: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact initial build fingerprint. None is accepted only for historical "
            "status-only plans."
        ),
    )
    initial_build_provenance_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact initial build-provenance snapshot hash. None is accepted only "
            "for historical status-only plans."
        ),
    )
    host_safety_envelope_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact workflow-owned host safety envelope. None is accepted only for "
            "historical status-only plans."
        ),
    )
    initial_constraints_present: bool | None = Field(
        default=None,
        description=(
            "Whether a measured-constraint contract existed at planning time. None "
            "is accepted only for historical status-only plans."
        ),
    )
    initial_constraints_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact initial constraint-contract hash when present; otherwise null."
        ),
    )
    camera_fingerprint: str = Field(pattern=SHA256_PATTERN)
    scoring_version: DirectScoringVersion
    initial_direct_score: float = Field(ge=0, le=1)
    initial_silhouette_iou: float = Field(ge=0, le=1)
    target_direct_score: float = Field(ge=0, le=1)
    target_silhouette_iou: float = Field(ge=0, le=1)
    minimum_iteration_gain: float = Field(default=0.001, gt=0, le=1)
    minimum_candidate_confidence: float = Field(default=0.8, ge=0, le=1)
    max_iterations: int = Field(default=3, ge=1, le=5)
    max_candidate_groups_per_iteration: int = Field(default=3, ge=1, le=20)
    max_candidates_per_iteration: int = Field(default=12, ge=1, le=100)
    max_changed_ids_per_iteration: int = Field(default=6, ge=1, le=50)
    allowed_target_ids: list[str] = Field(min_length=1)
    locked_target_ids: list[str] = Field(default_factory=list)
    custom_mesh_target_ids: list[str] = Field(default_factory=list)
    path_limits: list[ConvergencePathLimit] = Field(min_length=1)
    allow_material_edits: bool = False
    camera_locked: Literal[True] = True
    generated_target_policy: Literal["advisory_only"] = "advisory_only"
    constraint_regression_policy: Literal["forbid"] = "forbid"
    created_at: str

    @model_validator(mode="after")
    def validate_envelope(self) -> VisualConvergencePlan:
        """Reject ambiguous identities, weaker targets, and implicit material authority."""

        for relative_path, sha256 in self.initial_input_hashes.items():
            _validate_relative_path(relative_path)
            if not re.fullmatch(SHA256_PATTERN, sha256):
                raise ValueError(
                    "initial_input_hashes values must be lowercase SHA-256 strings"
                )
        provenance_values = (
            self.initial_candidates_sha256,
            self.initial_build_fingerprint,
            self.initial_build_provenance_sha256,
            self.host_safety_envelope_sha256,
            self.initial_constraints_present,
        )
        if any(value is not None for value in provenance_values) and any(
            value is None for value in provenance_values
        ):
            raise ValueError(
                "new convergence plans require complete candidate, build, and "
                "constraint bindings"
            )
        if self.initial_constraints_present is True and self.initial_constraints_sha256 is None:
            raise ValueError("present convergence constraints require an exact SHA-256")
        if (
            self.initial_constraints_present is False
            and self.initial_constraints_sha256 is not None
        ):
            raise ValueError("absent convergence constraints cannot carry a SHA-256")
        if (
            self.initial_constraints_present is None
            and self.initial_constraints_sha256 is not None
        ):
            raise ValueError("legacy convergence plans cannot carry an unscoped constraint hash")
        identity_lists = {
            "allowed_target_ids": self.allowed_target_ids,
            "locked_target_ids": self.locked_target_ids,
            "custom_mesh_target_ids": self.custom_mesh_target_ids,
        }
        for label, values in identity_lists.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must contain unique semantic IDs")
        collisions = sorted(set(self.allowed_target_ids).intersection(self.locked_target_ids))
        if collisions:
            raise ValueError(f"allowed and locked convergence target IDs overlap: {collisions}")
        families = [item.path_family for item in self.path_limits]
        if len(families) != len(set(families)):
            raise ValueError("convergence path families must be unique")
        material_families = [item for item in families if item.startswith("material.")]
        if material_families and not self.allow_material_edits:
            raise ValueError("material path limits require explicit allow_material_edits=true")
        if self.target_direct_score < self.initial_direct_score:
            raise ValueError("target_direct_score cannot be lower than the initial score")
        if self.target_silhouette_iou < self.initial_silhouette_iou:
            raise ValueError("target_silhouette_iou cannot be lower than the initial IoU")
        return self


class VisualConvergenceApproval(StrictModel):
    """Activate exactly one bounded session by the exact serialized plan SHA-256."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    approval_id: str
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    initial_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_candidates_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact approved plan candidate hash. None is accepted only for "
            "historical status-only approvals."
        ),
    )
    initial_build_fingerprint: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact approved initial build fingerprint. None is accepted only for "
            "historical status-only approvals."
        ),
    )
    initial_build_provenance_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact approved build-provenance snapshot hash. None is accepted only "
            "for historical status-only approvals."
        ),
    )
    host_safety_envelope_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact approved host-safety-envelope hash. None is accepted only for "
            "historical status-only approvals."
        ),
    )
    initial_constraints_present: bool | None = Field(
        default=None,
        description=(
            "Approved initial constraint-contract presence. None is accepted only "
            "for historical status-only approvals."
        ),
    )
    initial_constraints_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description=(
            "Exact approved initial constraint hash when present; otherwise null."
        ),
    )
    camera_fingerprint: str = Field(pattern=SHA256_PATTERN)
    authorization_scope: Literal["bounded_visual_convergence"] = (
        "bounded_visual_convergence"
    )
    approved_by: Literal["user"] = "user"
    approval_note: str = Field(min_length=1)
    approved_at: str
    status: Literal["active"] = "active"

    @field_validator("approval_note")
    @classmethod
    def validate_approval_note(cls, value: str) -> str:
        """Preserve meaningful explicit approval text."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("visual convergence approval note must not be empty")
        return stripped


class VisualConvergenceIterationAuthorization(StrictModel):
    """Authorize one exact host-selected iteration under the active session envelope."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    authorization_id: str
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    iteration_index: int = Field(ge=1, le=5)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_sha256: str = Field(pattern=SHA256_PATTERN)
    base_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    source_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    candidates_sha256: str = Field(pattern=SHA256_PATTERN)
    source_build_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    selection_sha256: str = Field(pattern=SHA256_PATTERN)
    compiled_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    selected_candidate_ids: list[str] = Field(min_length=1)
    issued_by: Literal["host_policy"] = "host_policy"
    created_at: str

    @model_validator(mode="after")
    def validate_selected_ids(self) -> VisualConvergenceIterationAuthorization:
        """Require one unambiguous set of exact candidate identities."""

        if len(self.selected_candidate_ids) != len(set(self.selected_candidate_ids)):
            raise ValueError("iteration authorization candidate IDs must be unique")
        return self


class VisualConvergenceIteration(StrictModel):
    """Record one immutable, hash-chained candidate selection and verification result."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    iteration_index: int = Field(ge=1, le=5)
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_sha256: str = Field(pattern=SHA256_PATTERN)
    previous_iteration_receipt_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    base_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    base_scene_spec_snapshot_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    source_qa_run_id: str = Field(pattern=QA_RUN_ID_PATTERN)
    source_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    candidates_sha256: str = Field(pattern=SHA256_PATTERN)
    source_build_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    selection_sha256: str = Field(pattern=SHA256_PATTERN)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    compiled_plan_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    execution_authorization_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    result_scene_spec_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    result_qa_run_id: str | None = Field(default=None, pattern=QA_RUN_ID_PATTERN)
    result_qa_report_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    result_candidates_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    result_build_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    result_build_provenance_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    before_constraints_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    after_constraints_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    before_direct_score: float = Field(ge=0, le=1)
    after_direct_score: float | None = Field(default=None, ge=0, le=1)
    before_silhouette_iou: float = Field(ge=0, le=1)
    after_silhouette_iou: float | None = Field(default=None, ge=0, le=1)
    score_delta: float | None = None
    changed_ids: list[str] = Field(default_factory=list)
    constraint_regression_count: int = Field(default=0, ge=0)
    canonical_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    status: Literal[
        "accepted",
        "rolled_back",
        "manual_review_required",
        "failed",
    ]
    reason_codes: list[str] = Field(min_length=1)
    completed_at: str

    @model_validator(mode="after")
    def validate_iteration_state(self) -> VisualConvergenceIteration:
        """Keep the chain, selected operations, outputs, and rollback state coherent."""

        if self.iteration_index == 1 and self.previous_iteration_receipt_sha256 is not None:
            raise ValueError("the first convergence iteration cannot reference a predecessor")
        if self.iteration_index > 1 and self.previous_iteration_receipt_sha256 is None:
            raise ValueError("later convergence iterations require the previous receipt hash")
        if len(self.selected_candidate_ids) != len(set(self.selected_candidate_ids)):
            raise ValueError("selected convergence candidate IDs must be unique")
        if len(self.changed_ids) != len(set(self.changed_ids)):
            raise ValueError("changed convergence semantic IDs must be unique")
        executed = self.status in {"accepted", "rolled_back"}
        execution_fields = (
            self.compiled_plan_sha256,
            self.execution_authorization_sha256,
            self.result_scene_spec_sha256,
            self.result_qa_run_id,
            self.result_qa_report_sha256,
            self.result_candidates_sha256,
            self.after_direct_score,
            self.after_silhouette_iou,
            self.score_delta,
        )
        if executed and (
            not self.selected_candidate_ids
            or any(item is None for item in execution_fields)
        ):
            raise ValueError(
                "executed convergence iterations require exact plan and result evidence"
            )
        result_qa_fields = (
            self.result_qa_run_id,
            self.result_qa_report_sha256,
            self.result_candidates_sha256,
            self.after_direct_score,
            self.after_silhouette_iou,
            self.score_delta,
        )
        if any(item is not None for item in result_qa_fields) and any(
            item is None for item in result_qa_fields
        ):
            raise ValueError(
                "convergence result QA identity, metrics, and hashes must be complete or absent"
            )
        build_result_fields = (
            self.result_build_fingerprint,
            self.result_build_provenance_sha256,
        )
        if any(item is not None for item in build_result_fields) and any(
            item is None for item in build_result_fields
        ):
            raise ValueError(
                "convergence result build fingerprint and provenance hash "
                "must be complete or absent"
            )
        if (
            self.result_build_fingerprint is not None
            and self.result_scene_spec_sha256 is None
        ):
            raise ValueError(
                "convergence result build provenance requires a result SceneSpec"
            )
        if (
            self.after_constraints_sha256 is not None
            and self.before_constraints_sha256 is None
        ):
            raise ValueError(
                "convergence after-constraint evidence requires its before snapshot"
            )
        if executed and self.source_build_fingerprint is not None and (
            self.before_constraints_sha256 is None
            or self.after_constraints_sha256 is None
        ):
            raise ValueError(
                "executed convergence iterations require exact before/after "
                "constraint evidence"
            )
        if (
            self.base_scene_spec_snapshot_sha256 is not None
            and self.base_scene_spec_snapshot_sha256
            != self.base_scene_spec_sha256
        ):
            raise ValueError(
                "convergence base SceneSpec snapshot must equal the receipt base hash"
            )
        if self.result_qa_run_id is not None and self.result_scene_spec_sha256 is None:
            raise ValueError("convergence result QA requires a result SceneSpec snapshot")
        if (
            self.source_build_fingerprint is not None
            and self.result_qa_run_id is not None
            and (
                self.result_build_fingerprint is None
                or self.result_build_provenance_sha256 is None
            )
        ):
            raise ValueError(
                "new convergence result QA requires exact build provenance evidence"
            )
        if (
            self.after_direct_score is not None
            and self.score_delta is not None
            and abs(
                self.score_delta
                - (self.after_direct_score - self.before_direct_score)
            )
            > 1e-9
        ):
            raise ValueError("iteration score_delta must match the direct score difference")
        if self.status == "accepted":
            if self.constraint_regression_count:
                raise ValueError("accepted convergence iterations cannot contain regressions")
            if self.canonical_scene_spec_sha256 != self.result_scene_spec_sha256:
                raise ValueError("accepted result must be the resulting canonical SceneSpec")
        if self.status == "rolled_back":
            if self.canonical_scene_spec_sha256 != self.base_scene_spec_sha256:
                raise ValueError("rolled-back iteration must restore the base SceneSpec")
        return self


class HashBoundConvergenceArtifact(StrictModel):
    """Bind one job-relative convergence artifact to its exact content hash."""

    relative_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        """Reject absolute and escaping artifact paths."""

        return _validate_relative_path(value)


class VisualConvergenceCancellation(StrictModel):
    """Consume one approved session with an immutable user cancellation receipt."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    cancellation_id: str
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_sha256: str = Field(pattern=SHA256_PATTERN)
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    canonical_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    current_qa_run_id: str = Field(pattern=QA_RUN_ID_PATTERN)
    current_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    current_candidates_sha256: str = Field(pattern=SHA256_PATTERN)
    current_build_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    previous_iteration_receipt_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    cancelled_by: Literal["user"] = "user"
    reason: str = Field(min_length=1)
    cancelled_at: str


class VisualConvergenceReport(StrictModel):
    """Summarize one terminal bounded session without replacing iteration evidence."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_sha256: str = Field(pattern=SHA256_PATTERN)
    input_fingerprint: str = Field(pattern=SHA256_PATTERN)
    camera_fingerprint: str = Field(pattern=SHA256_PATTERN)
    scoring_version: DirectScoringVersion
    initial_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_scene_spec_snapshot: HashBoundConvergenceArtifact | None = None
    final_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    final_scene_spec_snapshot: HashBoundConvergenceArtifact | None = None
    initial_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_candidates_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    final_qa_report_sha256: str = Field(pattern=SHA256_PATTERN)
    initial_build_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    final_build_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    initial_build_provenance_snapshot: HashBoundConvergenceArtifact | None = None
    final_build_provenance_snapshot: HashBoundConvergenceArtifact | None = None
    initial_constraints_present: bool | None = None
    initial_constraints_sha256: str | None = Field(
        default=None,
        pattern=SHA256_PATTERN,
    )
    cancellation_receipt: HashBoundConvergenceArtifact | None = None
    initial_direct_score: float = Field(ge=0, le=1)
    final_direct_score: float = Field(ge=0, le=1)
    target_direct_score: float = Field(ge=0, le=1)
    initial_silhouette_iou: float = Field(ge=0, le=1)
    final_silhouette_iou: float = Field(ge=0, le=1)
    target_silhouette_iou: float = Field(ge=0, le=1)
    iteration_receipts: list[HashBoundConvergenceArtifact] = Field(default_factory=list)
    iteration_evidence: list[HashBoundConvergenceArtifact] = Field(default_factory=list)
    accepted_iterations: int = Field(ge=0)
    rolled_back_iterations: int = Field(ge=0)
    termination_reason: ConvergenceTerminationReason
    target_reached: bool
    manual_review_required: bool
    remaining_high_finding_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(min_length=1)
    started_at: str
    completed_at: str

    @model_validator(mode="after")
    def validate_terminal_summary(self) -> VisualConvergenceReport:
        """Cross-check iteration counts, target state, and review semantics."""

        receipt_paths = [item.relative_path for item in self.iteration_receipts]
        if len(receipt_paths) != len(set(receipt_paths)):
            raise ValueError("convergence iteration receipt paths must be unique")
        evidence_paths = [item.relative_path for item in self.iteration_evidence]
        if len(evidence_paths) != len(set(evidence_paths)):
            raise ValueError("convergence iteration evidence paths must be unique")
        missing_receipts = sorted(set(receipt_paths) - set(evidence_paths))
        if self.iteration_evidence and missing_receipts:
            raise ValueError(
                "convergence iteration evidence must include every receipt: "
                f"{missing_receipts}"
            )
        if self.accepted_iterations + self.rolled_back_iterations > len(
            self.iteration_receipts
        ):
            raise ValueError("convergence iteration counts exceed recorded receipts")
        scores_reached = (
            self.final_direct_score >= self.target_direct_score
            and self.final_silhouette_iou >= self.target_silhouette_iou
        )
        if self.target_reached != scores_reached:
            raise ValueError("target_reached must match the terminal direct metrics")
        reason_reached = self.termination_reason == "target_reached"
        if self.target_reached != reason_reached:
            raise ValueError(
                "target_reached and termination_reason must identify the same outcome"
            )
        expected_manual_review = convergence_manual_review_required(
            self.termination_reason
        )
        if self.manual_review_required != expected_manual_review:
            raise ValueError(
                "manual_review_required does not match termination_reason semantics"
            )
        build_values = (
            self.initial_candidates_sha256,
            self.initial_build_fingerprint,
            self.final_build_fingerprint,
            self.initial_scene_spec_snapshot,
            self.initial_build_provenance_snapshot,
            self.final_build_provenance_snapshot,
            self.initial_constraints_present,
        )
        if any(value is not None for value in build_values) and any(
            value is None for value in build_values
        ):
            raise ValueError(
                "new convergence terminal reports require complete candidate/build bindings"
            )
        if self.initial_constraints_present is True and self.initial_constraints_sha256 is None:
            raise ValueError("present convergence constraints require an exact SHA-256")
        if (
            self.initial_constraints_present is False
            and self.initial_constraints_sha256 is not None
        ):
            raise ValueError("absent convergence constraints cannot carry a SHA-256")
        if self.termination_reason == "cancelled" and self.cancellation_receipt is None:
            raise ValueError("cancelled convergence reports require a cancellation receipt")
        if self.termination_reason != "cancelled" and self.cancellation_receipt is not None:
            raise ValueError("only cancelled convergence reports may bind cancellation evidence")
        return self


class VisualConvergenceReportManifest(StrictModel):
    """Bind a derived convergence PDF to authoritative JSON and receipt hashes."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    session_id: str = Field(pattern=SESSION_ID_PATTERN)
    job_id: str
    source_fingerprint: str = Field(pattern=SHA256_PATTERN)
    report_json: HashBoundConvergenceArtifact
    pdf: HashBoundConvergenceArtifact
    sources: list[HashBoundConvergenceArtifact] = Field(min_length=2)
    generated_at: str

    @model_validator(mode="after")
    def validate_manifest_sources(self) -> VisualConvergenceReportManifest:
        """Require unique sources and inclusion of the authoritative terminal report."""

        paths = [item.relative_path for item in self.sources]
        if len(paths) != len(set(paths)):
            raise ValueError("convergence PDF source paths must be unique")
        source_pairs = {(item.relative_path, item.sha256) for item in self.sources}
        if (self.report_json.relative_path, self.report_json.sha256) not in source_pairs:
            raise ValueError("convergence PDF sources must include the terminal JSON report")
        if self.pdf.relative_path in set(paths):
            raise ValueError("derived convergence PDF cannot be one of its own sources")
        return self
