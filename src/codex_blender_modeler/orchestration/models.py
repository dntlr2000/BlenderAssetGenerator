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
ReferenceContentScope = Literal["primary_object_only", "full_reference"]
ExecutionPolicy = Literal["standard", "background_exterior"]
DeliveryScope = Literal["preview_only", "portable_package"]
FastQualityPolicy = Literal["review_delivery_v2"]
QualityStatus = Literal["passed", "needs_revision", "unscorable"]
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
    "delivered_for_review",
    "completed",
]
IntegrityStatus = Literal["valid", "corrupt", "missing"]
CurrencyStatus = Literal["current", "superseded", "unknown"]
VerificationStatus = Literal["verified", "partially_verified", "unverified"]
DestinationKind = Literal["unspecified", "engine_neutral", "unity", "unreal", "custom"]
DestinationStatus = Literal["not_requested", "available", "unsupported"]
ArtifactAcceptance = Literal["exists", "valid_json", "json_ok", "nonempty_directory"]
ArtifactLifecycle = Literal["canonical", "workflow_snapshot", "immutable_run"]
WorkflowReasonCode = Literal[
    "requires_standard_workflow",
    "orchestration_artifact_conflict",
    "host_failure",
]
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
    max_pre_qa_fit_attempts: int = Field(default=2, ge=0, le=2)
    max_texture_resolution: int = Field(default=2048, ge=16, le=8192)
    max_lod0_triangles: int | None = Field(default=None, ge=1)
    external_provider_budget: int = Field(default=0, ge=0, le=100)


class BackgroundPreviewBinding(V08StrictModel):
    """Bind a package continuation to one exact completed fast-preview source."""

    workflow_id: WorkflowId
    plan_sha256: Sha256
    terminal_step_id: StepId
    terminal_completion_fingerprint: Sha256
    qa_run_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")
    source_fingerprint: Sha256
    build_fingerprint: Sha256
    quality_status: QualityStatus | None = None
    standard_workflow_recommended: bool | None = None
    quality_report_path: JobRelativePath | None = None
    quality_report_sha256: Sha256 | None = None
    bound_at: datetime

    @model_validator(mode="after")
    def validate_optional_quality_binding(self) -> BackgroundPreviewBinding:
        """Require complete quality evidence whenever a new-policy binding provides it."""

        quality_values = (
            self.quality_status,
            self.standard_workflow_recommended,
            self.quality_report_path,
            self.quality_report_sha256,
        )
        if any(value is not None for value in quality_values) and any(
            value is None for value in quality_values
        ):
            raise ValueError("background preview quality binding must be complete")
        return self


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
    reference_content_scope: ReferenceContentScope = "full_reference"
    target_subject: str | None = Field(default=None, min_length=1, max_length=256)
    execution_policy: ExecutionPolicy = "standard"
    delivery_scope: DeliveryScope | None = None
    fast_quality_policy: FastQualityPolicy | None = None
    background_preview_binding: BackgroundPreviewBinding | None = None
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
        """Keep staged views distinct and enforce the bounded background fast lane."""

        if (
            self.reference_content_scope == "primary_object_only"
            and self.target_subject is None
        ):
            raise ValueError(
                "primary_object_only requires an explicit target_subject"
            )
        if self.staged_view is not None and self.staged_view.kind == "reference":
            raise ValueError("staged auxiliary view cannot use kind=reference")
        if self.replace_existing_view and self.staged_view is None:
            raise ValueError("replace_existing_view requires a staged auxiliary view")
        if self.include_destination_handoff and self.profile_id == "obj_legacy":
            raise ValueError("destination handoff supports GLB and FBX packages only")
        if self.execution_policy == "background_exterior":
            if self.intent_hint not in {"auto", "new_asset", "portable_package"}:
                raise ValueError(
                    "background_exterior supports only new_asset or portable_package"
                )
            if self.requested_scope != "full":
                raise ValueError(
                    "background_exterior requires requested_scope=full"
                )
            if self.mode != "concept":
                raise ValueError(
                    "background_exterior supports only unmeasured concept assets"
                )
            if self.staged_view is not None or self.replace_existing_view:
                raise ValueError(
                    "background_exterior cannot add or replace measured views"
                )
            if self.scale_anchors:
                raise ValueError(
                    "background_exterior cannot contain measured scale anchors"
                )
            if self.include_destination_handoff:
                raise ValueError(
                    "background_exterior cannot generate a destination handoff"
                )
            if self.destination.kind not in {"unspecified", "engine_neutral"}:
                raise ValueError(
                    "background_exterior supports only an engine-neutral destination"
                )
            if self.budgets.max_qa_iterations != 1:
                raise ValueError(
                    "background_exterior permits exactly one direct QA iteration"
                )
            if self.budgets.max_texture_resolution > 512:
                raise ValueError(
                    "background_exterior limits texture resolution to 512"
                )
            if self.budgets.external_provider_budget != 0:
                raise ValueError(
                    "background_exterior forbids external provider calls"
                )
            if self.delivery_scope is None:
                raise ValueError(
                    "background_exterior requires an explicit resolved delivery_scope"
                )
            if (
                self.background_preview_binding is not None
                and self.delivery_scope != "portable_package"
            ):
                raise ValueError(
                    "background preview bindings are valid only for portable_package "
                    "continuations"
                )
        elif self.background_preview_binding is not None:
            raise ValueError(
                "background_preview_binding is allowed only for background_exterior"
            )
        elif self.fast_quality_policy is not None:
            raise ValueError(
                "fast_quality_policy is allowed only for background_exterior"
            )
        return self


class IntentRouting(V08StrictModel):
    """Explain deterministic intent selection and whether execution may proceed."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    workflow_id: WorkflowId
    job_id: JobId
    intent: WorkflowIntent
    execution_policy: ExecutionPolicy = "standard"
    delivery_scope: DeliveryScope | None = None
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(min_length=1)
    matched_terms: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    destination: DestinationResolution
    routed_at: datetime

    @model_validator(mode="after")
    def validate_execution_policy(self) -> IntentRouting:
        """Restrict the background fast lane to a newly routed static asset."""

        if self.execution_policy == "background_exterior":
            if self.intent not in {"new_asset", "portable_package"}:
                raise ValueError(
                    "background_exterior routing requires new_asset or portable_package"
                )
            if self.intent == "portable_package" and self.delivery_scope != "portable_package":
                raise ValueError(
                    "background_exterior portable routing requires portable_package delivery"
                )
        return self


class ArtifactRequirement(V08StrictModel):
    """Describe one job-contained artifact needed to complete a workflow step."""

    artifact_id: StepId
    path: JobRelativePath
    source_path: JobRelativePath | None = None
    lifecycle: ArtifactLifecycle = "canonical"
    acceptance: ArtifactAcceptance = "exists"
    canonical: bool = False

    @model_validator(mode="after")
    def validate_lifecycle(self) -> ArtifactRequirement:
        """Keep mutable source paths separate from their immutable workflow snapshots."""

        if self.lifecycle == "workflow_snapshot":
            if self.source_path is None:
                raise ValueError("workflow_snapshot artifacts require source_path")
            if self.source_path == self.path:
                raise ValueError("workflow snapshot path must differ from source_path")
            if self.canonical:
                raise ValueError("workflow snapshots cannot themselves be canonical")
        elif self.source_path is not None:
            raise ValueError("source_path is valid only for workflow_snapshot artifacts")
        return self


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
    reference_content_scope: ReferenceContentScope = "full_reference"
    target_subject: str | None = Field(default=None, min_length=1, max_length=256)
    execution_policy: ExecutionPolicy = "standard"
    delivery_scope: DeliveryScope | None = None
    fast_quality_policy: FastQualityPolicy | None = None
    destination: DestinationResolution
    steps: list[WorkflowStep] = Field(min_length=1)
    terminal_step_id: StepId
    created_at: datetime
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ordered_dag(self) -> WorkflowPlan:
        """Require an ordered DAG and preserve all fast-lane safety boundaries."""

        if (
            self.reference_content_scope == "primary_object_only"
            and self.target_subject is None
        ):
            raise ValueError(
                "primary_object_only plans require an explicit target_subject"
            )
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
        if self.execution_policy == "background_exterior":
            if self.intent not in {"new_asset", "portable_package"} or self.scope != "full":
                raise ValueError(
                    "background_exterior plans require new_asset or portable_package "
                    "with full scope"
                )
            if self.delivery_scope is None:
                raise ValueError(
                    "background_exterior plans require a resolved delivery_scope"
                )
            generic_approvals = [
                step.step_id
                for step in self.steps
                if step.execution_mode == "approval"
            ]
            if generic_approvals:
                raise ValueError(
                    "background_exterior plans cannot contain generic approvals: "
                    f"{generic_approvals}"
                )
            specialized_gates = [
                step.approval_gate
                for step in self.steps
                if step.execution_mode == "specialized_approval"
            ]
            portable_steps = [
                step for step in self.steps if step.phase == "portable"
            ]
            step_map = {step.step_id: step for step in self.steps}
            required_common = [
                "job.created",
                "reference.analyze",
                "geometry.modeling_plan",
                "geometry.background_author",
                "background_geometry.build",
                "background_geometry.render",
                "background_geometry.inspect",
                "background_geometry.validate",
                "background_geometry.report",
                "material.scaffold",
                "material.author",
                "material.promote",
                "material.contract_validate",
                "material.build",
                "material.inspect",
                "material.swatches",
                "material.report",
                "qa.run",
            ]
            if self.fast_quality_policy == "review_delivery_v2":
                required_common.insert(
                    required_common.index("background_geometry.build"),
                    "background.fit",
                )
                required_common.extend(["background.eligibility", "qa.report"])
            else:
                required_common.extend(["qa.report", "background.eligibility"])
            if self.intent == "new_asset":
                missing_common = [
                    step_id for step_id in required_common if step_id not in step_map
                ]
                if missing_common:
                    raise ValueError(
                        "background_exterior plan is missing required bounded steps: "
                        f"{missing_common}"
                    )
                common_positions = [ids.index(step_id) for step_id in required_common]
                if common_positions != sorted(common_positions):
                    raise ValueError(
                        "background_exterior common steps must preserve their fixed order"
                    )
                qa_steps = [step for step in self.steps if step.step_id == "qa.run"]
                if (
                    len(qa_steps) != 1
                    or qa_steps[0].parameters.get("include_generated_target") is not False
                ):
                    raise ValueError(
                        "background_exterior requires one direct QA run without a "
                        "generated target"
                    )
                if self.fast_quality_policy == "review_delivery_v2":
                    fit_step = step_map["background.fit"]
                    if (
                        fit_step.tool_name != "fit_background_exterior"
                        or int(fit_step.parameters.get("max_attempts", -1)) not in {0, 1, 2}
                    ):
                        raise ValueError(
                            "new background quality plans require one bounded pre-QA fit"
                        )
            if self.delivery_scope == "preview_only" and portable_steps:
                raise ValueError(
                    "preview_only background plans cannot contain portable steps"
                )
            if self.delivery_scope == "preview_only" and specialized_gates:
                raise ValueError(
                    "preview_only background plans cannot contain specialized approvals"
                )
            if self.delivery_scope == "portable_package":
                required_portable = [
                    "portable.profile",
                    "portable.preflight",
                    "portable.plan",
                    "portable.plan_approval",
                    "portable.optimize",
                    "portable.material_convert",
                    "portable.package",
                    "portable.roundtrip",
                    "portable.report",
                ]
                missing_portable = [
                    step_id for step_id in required_portable if step_id not in step_map
                ]
                if missing_portable:
                    raise ValueError(
                        "portable background plan is missing required V0.7 steps: "
                        f"{missing_portable}"
                    )
                portable_positions = [ids.index(step_id) for step_id in required_portable]
                if portable_positions != sorted(portable_positions):
                    raise ValueError(
                        "portable background steps must preserve their fixed order"
                    )
                if step_map["portable.optimize"].depends_on != [
                    "portable.plan_approval"
                ]:
                    raise ValueError(
                        "portable optimization must depend on its specialized approval"
                    )
                optimization_approvals = [
                    step
                    for step in self.steps
                    if step.approval_gate == "optimization_plan"
                ]
                if len(optimization_approvals) != 1:
                    raise ValueError(
                        "portable background plans require exactly one "
                        "optimization_plan approval"
                    )
                if specialized_gates != ["optimization_plan"]:
                    raise ValueError(
                        "portable background plans permit only the exact "
                        "optimization_plan approval"
                    )
                if self.intent == "portable_package":
                    if self.terminal_step_id not in ids:
                        raise ValueError(
                            "background package continuation requires a terminal step"
                        )
                    prerequisite = step_map.get("geometry.prerequisite")
                    if (
                        prerequisite is None
                        or prerequisite.tool_name
                        != "verify_background_preview_prerequisite"
                        or prerequisite.parameters.get("require_new_output") is not True
                    ):
                        raise ValueError(
                            "background package continuation requires an exact "
                            "preview-binding prerequisite"
                        )
        elif self.fast_quality_policy is not None:
            raise ValueError(
                "fast_quality_policy is allowed only for background_exterior plans"
            )
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
    reason_code: WorkflowReasonCode | None = None


class WorkflowState(V08StrictModel):
    """Represent reconstructed workflow progress and the next safe action."""

    schema_version: Literal["0.8.0"] = SCHEMA_VERSION
    workflow_id: WorkflowId
    job_id: JobId
    plan_sha256: Sha256
    request_sha256: Sha256
    reference_content_scope: ReferenceContentScope = "full_reference"
    target_subject: str | None = Field(default=None, min_length=1, max_length=256)
    execution_policy: ExecutionPolicy = "standard"
    delivery_scope: DeliveryScope | None = None
    status: WorkflowStatus
    milestone: Milestone
    current_step_id: StepId | None = None
    steps: list[WorkflowStepState]
    next_action: str | None = None
    waiting_gate: GateKind | None = None
    warnings: list[str] = Field(default_factory=list)
    reason_code: WorkflowReasonCode | None = None
    quality_status: QualityStatus | None = None
    standard_workflow_recommended: bool | None = None
    quality_report_path: JobRelativePath | None = None
    quality_report_sha256: Sha256 | None = None
    cancelled_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state_summary(self) -> WorkflowState:
        """Synchronize terminal and waiting fields with the aggregate workflow status."""

        if (
            self.reference_content_scope == "primary_object_only"
            and self.target_subject is None
        ):
            raise ValueError(
                "primary_object_only state requires an explicit target_subject"
            )
        if self.status == "completed" and self.current_step_id is not None:
            raise ValueError("completed workflow cannot have a current step")
        if self.status == "cancelled" and not self.cancelled_reason:
            raise ValueError("cancelled workflow requires a reason")
        if self.status != "waiting_for_approval" and self.waiting_gate is not None:
            raise ValueError("waiting_gate is valid only while waiting_for_approval")
        quality_values = (
            self.quality_status,
            self.standard_workflow_recommended,
            self.quality_report_path,
            self.quality_report_sha256,
        )
        if any(value is not None for value in quality_values) and any(
            value is None for value in quality_values
        ):
            raise ValueError("workflow quality summary must be complete when present")
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
    reason_code: WorkflowReasonCode | None = None
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
