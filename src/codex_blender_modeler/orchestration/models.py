"""Strict V0.8 contracts for short-request routing and resumable workflows."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.8.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
JOB_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"
WORKFLOW_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
STEP_ID_PATTERN = r"^[a-z0-9][a-z0-9_.-]{0,95}$"


def _validate_job_relative_path(value: str) -> str:
    """Require a normalized POSIX path contained by the owning job workspace."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty POSIX job-relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be job-relative, not absolute")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
WorkflowId = Annotated[str, Field(pattern=WORKFLOW_ID_PATTERN)]
StepId = Annotated[str, Field(pattern=STEP_ID_PATTERN)]
JobRelativePath = Annotated[str, AfterValidator(_validate_job_relative_path)]
WorkflowIntent = Literal[
    "new_asset",
    "revise_asset",
    "add_measured_view",
    "interior_scope",
    "interior_visual_qa",
    "material_authoring",
    "visual_qa",
    "portable_package",
]
IntentHint = Literal[
    "auto",
    "new_asset",
    "revise_asset",
    "add_measured_view",
    "interior_scope",
    "interior_visual_qa",
    "material_authoring",
    "visual_qa",
    "portable_package",
]
WorkflowScope = Literal[
    "analysis_only",
    "proxy_only",
    "geometry_only",
    "interior_only",
    "material_only",
    "qa_only",
    "portable_only",
    "full",
]
ExecutionMode = Literal["host", "agent", "approval", "specialized_approval", "manual"]
StepStatus = Literal[
    "pending",
    "ready",
    "running",
    "waiting_for_agent",
    "waiting_for_approval",
    "blocked",
    "complete",
    "stale",
    "failed",
    "cancelled",
]
WorkflowStatus = Literal[
    "planned",
    "running",
    "waiting_for_agent",
    "waiting_for_approval",
    "blocked",
    "completed",
    "failed",
    "cancelled",
]
Milestone = Literal[
    "created",
    "analyzed",
    "proxy_ready",
    "geometry_approved",
    "interior_scope_waiting",
    "interior_scope_approved",
    "material_ready",
    "qa_review",
    "portable_ready",
    "completed",
]
IntegrityStatus = Literal["valid", "corrupt", "missing"]
CurrencyStatus = Literal["current", "superseded", "unknown"]
VerificationStatus = Literal["verified", "partially_verified", "unverified"]
DestinationKind = Literal["unspecified", "engine_neutral", "unity", "unreal", "custom"]
DestinationStatus = Literal["not_requested", "available", "unsupported"]
ArtifactAcceptance = Literal["exists", "valid_json", "json_ok", "nonempty_directory"]
GateKind = Literal[
    "proxy_geometry",
    "detailed_geometry",
    "material_swatches",
    "qa_review",
    "final_package",
    "interior_scope",
    "interior_qa_plan",
    "visual_revision",
    "optimization_plan",
]


class V08StrictModel(BaseModel):
    """Reject undeclared fields and non-finite floats in V0.8 contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WorkflowInputArtifact(V08StrictModel):
    """Bind one copied workflow input to a safe job-relative path and digest."""

    kind: Literal["reference", "front", "right", "top", "blueprint", "cad"]
    path: JobRelativePath
    sha256: Sha256


class WorkflowBudgets(V08StrictModel):
    """Bound orchestration work without silently broadening modeling scope."""

    max_host_steps_per_resume: int = Field(default=8, ge=1, le=64)
    max_qa_iterations: int = Field(default=1, ge=0, le=10)
    max_texture_resolution: int = Field(default=2048, ge=16, le=8192)
    max_lod0_triangles: int | None = Field(default=None, ge=1)
    external_provider_budget: int = Field(default=0, ge=0, le=100)


class DestinationRequest(V08StrictModel):
    """Record an explicit destination without inferring an engine from asset purpose."""

    kind: DestinationKind = "unspecified"
    name: str | None = Field(default=None, min_length=1, max_length=128)
    version: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_custom_name(self) -> DestinationRequest:
        """Require a name only for custom destinations and reject ambiguous custom targets."""

        if self.kind == "custom" and not self.name:
            raise ValueError("custom destination requires an explicit name")
        if self.kind != "custom" and self.name:
            raise ValueError("destination name is allowed only for kind=custom")
        return self


class DestinationResolution(V08StrictModel):
    """Resolve only implemented destination capabilities and preserve a portable boundary."""

    requested: DestinationRequest
    status: DestinationStatus
    adapter_id: str | None = None
    terminal_boundary: Literal["portable_package"] = "portable_package"
    reason: str

    @model_validator(mode="after")
    def validate_adapter_selection(self) -> DestinationResolution:
        """Require an adapter only when its capability is genuinely available."""

        if self.status == "available" and not self.adapter_id:
            raise ValueError("available destination requires adapter_id")
        if self.status != "available" and self.adapter_id is not None:
            raise ValueError("unavailable destination cannot declare adapter_id")
        return self


class WorkflowRequest(V08StrictModel):
    """Persist one normalized short request without absolute source paths or secrets."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    workflow_id: WorkflowId
    job_id: JobId
    raw_request: str = Field(min_length=1, max_length=4000)
    intent_hint: IntentHint = "auto"
    requested_scope: WorkflowScope
    mode: Literal["concept", "measured"] = "concept"
    primary_reference: WorkflowInputArtifact | None = None
    staged_view: WorkflowInputArtifact | None = None
    replace_existing_view: bool = False
    scale_anchors: list[str] = Field(default_factory=list)
    profile_id: Literal["portable_gltf", "fbx_interchange", "obj_legacy"] = (
        "portable_gltf"
    )
    destination: DestinationRequest = Field(default_factory=DestinationRequest)
    include_destination_handoff: bool = False
    budgets: WorkflowBudgets = Field(default_factory=WorkflowBudgets)
    created_at: datetime

    @model_validator(mode="after")
    def validate_view_request(self) -> WorkflowRequest:
        """Keep staged auxiliary views distinct from immutable primary evidence."""

        if self.staged_view is not None and self.staged_view.kind == "reference":
            raise ValueError("staged auxiliary view cannot use kind=reference")
        if self.replace_existing_view and self.staged_view is None:
            raise ValueError("replace_existing_view requires a staged auxiliary view")
        if self.include_destination_handoff and self.profile_id == "obj_legacy":
            raise ValueError("destination handoff supports GLB and FBX packages only")
        return self


class IntentRouting(V08StrictModel):
    """Explain deterministic intent selection and whether execution may proceed."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    workflow_id: WorkflowId
    job_id: JobId
    intent: WorkflowIntent
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(min_length=1)
    matched_terms: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    destination: DestinationResolution
    routed_at: datetime


class ArtifactRequirement(V08StrictModel):
    """Describe one job-contained artifact needed to complete a workflow step."""

    artifact_id: StepId
    path: JobRelativePath
    acceptance: ArtifactAcceptance = "exists"
    canonical: bool = False


class WorkflowStep(V08StrictModel):
    """Declare one ordered orchestration step and its explicit execution boundary."""

    step_id: StepId
    title: str = Field(min_length=1, max_length=160)
    phase: Literal[
        "job",
        "analysis",
        "geometry",
        "interior",
        "material",
        "qa",
        "portable",
        "destination",
    ]
    execution_mode: ExecutionMode
    tool_name: str | None = None
    depends_on: list[StepId] = Field(default_factory=list)
    outputs: list[ArtifactRequirement] = Field(default_factory=list)
    approval_gate: GateKind | None = None
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    instructions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_execution_boundary(self) -> WorkflowStep:
        """Keep approval, host, agent, and manual steps unambiguous."""

        approval_modes = {"approval", "specialized_approval"}
        if self.execution_mode in approval_modes and self.approval_gate is None:
            raise ValueError("approval steps require approval_gate")
        if self.execution_mode not in approval_modes and self.approval_gate is not None:
            raise ValueError("non-approval step cannot declare approval_gate")
        if self.execution_mode == "host" and not self.tool_name:
            raise ValueError("host step requires tool_name")
        return self


class WorkflowPlan(V08StrictModel):
    """Bind a routed request to one immutable ordered V0.8 execution plan."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    workflow_id: WorkflowId
    job_id: JobId
    request_sha256: Sha256
    routing_sha256: Sha256
    intent: WorkflowIntent
    scope: WorkflowScope
    destination: DestinationResolution
    steps: list[WorkflowStep] = Field(min_length=1)
    terminal_step_id: StepId
    created_at: datetime
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ordered_dag(self) -> WorkflowPlan:
        """Require unique ordered steps whose dependencies only point backward."""

        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("workflow step IDs must be unique")
        if self.terminal_step_id not in ids:
            raise ValueError("terminal_step_id must reference one workflow step")
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in step.depends_on:
                raise ValueError("workflow step cannot depend on itself")
            unknown = set(step.depends_on) - seen
            if unknown:
                raise ValueError(
                    f"workflow step dependencies must precede the step: {sorted(unknown)}"
                )
            seen.add(step.step_id)
        return self


class ArtifactFreshness(V08StrictModel):
    """Separate integrity, currency, and verification for one observed artifact."""

    artifact_id: StepId
    path: JobRelativePath
    sha256: Sha256 | None = None
    integrity: IntegrityStatus
    currency: CurrencyStatus
    verification: VerificationStatus
    reason: str


class WorkflowStepState(V08StrictModel):
    """Track one step without mutating its immutable plan declaration."""

    step_id: StepId
    status: StepStatus = "pending"
    input_fingerprint: Sha256 | None = None
    completion_fingerprint: Sha256 | None = None
    attempt_count: int = Field(default=0, ge=0)
    artifacts: list[ArtifactFreshness] = Field(default_factory=list)
    approval_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class WorkflowState(V08StrictModel):
    """Represent reconstructed workflow progress and the next safe action."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    workflow_id: WorkflowId
    job_id: JobId
    plan_sha256: Sha256
    request_sha256: Sha256
    status: WorkflowStatus
    milestone: Milestone
    current_step_id: StepId | None = None
    steps: list[WorkflowStepState]
    next_action: str | None = None
    waiting_gate: GateKind | None = None
    warnings: list[str] = Field(default_factory=list)
    cancelled_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state_summary(self) -> WorkflowState:
        """Synchronize terminal and waiting fields with the aggregate workflow status."""

        if self.status == "completed" and self.current_step_id is not None:
            raise ValueError("completed workflow cannot have a current step")
        if self.status == "cancelled" and not self.cancelled_reason:
            raise ValueError("cancelled workflow requires a reason")
        if self.status != "waiting_for_approval" and self.waiting_gate is not None:
            raise ValueError("waiting_gate is valid only while waiting_for_approval")
        return self


class WorkflowStepCompletion(V08StrictModel):
    """Bind an agent/manual completion marker to exact current outputs."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    completion_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    workflow_id: WorkflowId
    job_id: JobId
    step_id: StepId
    plan_sha256: Sha256
    input_fingerprint: Sha256
    output_fingerprint: Sha256
    output_artifacts: list[ArtifactFreshness]
    note: str = Field(min_length=1, max_length=2000)
    recorded_at: datetime


class WorkflowApproval(V08StrictModel):
    """Record one exact generic workflow-gate approval without authorizing future gates."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    approval_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    workflow_id: WorkflowId
    job_id: JobId
    step_id: StepId
    gate: Literal[
        "proxy_geometry",
        "detailed_geometry",
        "material_swatches",
        "qa_review",
        "final_package",
    ]
    plan_sha256: Sha256
    artifact_fingerprint: Sha256
    approval_note: str = Field(min_length=1, max_length=2000)
    approved_at: datetime
    status: Literal["approved"] = "approved"


class WorkflowAttempt(V08StrictModel):
    """Preserve one immutable execution attempt and its exact input/output evidence."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    attempt_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    workflow_id: WorkflowId
    job_id: JobId
    step_id: StepId
    plan_sha256: Sha256
    input_fingerprint: Sha256
    status: Literal["running", "succeeded", "failed"]
    output_fingerprint: Sha256 | None = None
    outputs: list[ArtifactFreshness] = Field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    started_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_result(self) -> WorkflowAttempt:
        """Require output evidence on success and an explicit error on failure."""

        if self.status == "running":
            if (
                self.completed_at
                or self.output_fingerprint
                or self.error_type
                or self.error_message
            ):
                raise ValueError("running attempt cannot contain completion evidence")
        elif self.status == "succeeded":
            if self.output_fingerprint is None or self.error_type or self.error_message:
                raise ValueError("successful attempt requires outputs and no error")
            if self.completed_at is None:
                raise ValueError("successful attempt requires completed_at")
        else:
            if not self.error_type or not self.error_message or self.completed_at is None:
                raise ValueError("failed attempt requires error details and completed_at")
        return self


class WorkflowLock(V08StrictModel):
    """Represent one expiring job write lock without storing host secrets."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    lock_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    workflow_id: WorkflowId
    job_id: JobId
    process_id: int = Field(ge=0)
    acquired_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_expiry(self) -> WorkflowLock:
        """Reject non-expiring or backward lock intervals."""

        if self.expires_at <= self.acquired_at:
            raise ValueError("workflow lock must expire after acquisition")
        return self
