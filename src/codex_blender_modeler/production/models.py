"""Strict V0.9 contracts for client-mediated production dispatch and control."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ..stabilization.models import (
    JobId,
    PortableId,
    RelativePath,
    Sha256,
    V09StrictModel,
    WorkflowId,
    WorkspaceAuditReport,
)

SCHEMA_VERSION = "0.9.0"

ProductionNextAction = Literal[
    "bind_client_task",
    "resume_host",
    "delegate_read_only",
    "controller_author",
    "plan_destination_handoff",
    "plan_visual_convergence",
    "run_visual_convergence",
    "request_generic_approval",
    "request_specialized_approval",
    "run_postflight_audit",
    "completed",
    "blocked",
    "failed",
    "cancelled",
]
ProductionStatus = Literal[
    "prepared",
    "running",
    "waiting_for_controller",
    "waiting_for_approval",
    "completed",
    "blocked",
    "failed",
    "cancelled",
]


class ProductionArtifact(V09StrictModel):
    """Bind one contained production artifact to a normalized path and exact digest."""

    path: RelativePath
    sha256: Sha256


class ProductionDestinationHint(V09StrictModel):
    """Keep a destination as planning data without claiming a validated adapter."""

    kind: Literal["unspecified", "engine_neutral", "unity", "unreal", "custom"] = (
        "unspecified"
    )
    name: str | None = Field(default=None, min_length=1, max_length=128)
    version: str | None = Field(default=None, min_length=1, max_length=64)
    render_pipeline: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_custom_destination(self) -> ProductionDestinationHint:
        """Require a custom destination name and reject names on built-in destination kinds."""

        if self.kind == "custom" and not self.name:
            raise ValueError("custom destination hint requires name")
        if self.kind != "custom" and self.name is not None:
            raise ValueError("destination name is allowed only for kind=custom")
        return self


class ProductionConvergenceRequest(V09StrictModel):
    """Declare one optional exact-approval bounded V0.6 convergence phase."""

    mode: Literal["disabled", "bounded_after_v06"] = "disabled"
    target_direct_score: float | None = Field(default=None, ge=0, le=1)
    target_silhouette_iou: float | None = Field(default=None, ge=0, le=1)
    minimum_iteration_gain: float = Field(default=0.001, gt=0, le=1)
    minimum_candidate_confidence: float = Field(default=0.8, ge=0, le=1)
    max_iterations: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_targets(self) -> ProductionConvergenceRequest:
        """Require explicit quality targets only when bounded convergence is enabled."""

        targets = (self.target_direct_score, self.target_silhouette_iou)
        if self.mode == "bounded_after_v06" and any(value is None for value in targets):
            raise ValueError(
                "bounded_after_v06 requires direct-score and silhouette targets"
            )
        if self.mode == "disabled" and any(value is not None for value in targets):
            raise ValueError("disabled convergence cannot carry target scores")
        return self


class AssetProductionDispatchRequest(V09StrictModel):
    """Preserve one user-authorized production objective without absolute source paths."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    purpose: str = Field(min_length=1, max_length=1000)
    mode: Literal["concept", "measured"] = "concept"
    reference_content_scope: Literal["full_reference", "primary_object_only"] = (
        "full_reference"
    )
    target_subject: str | None = Field(default=None, min_length=1, max_length=256)
    execution_policy: Literal["standard", "background_exterior"] = "standard"
    delivery_scope: Literal["portable_package", "v06_convergence"] = (
        "portable_package"
    )
    profile_id: Literal["portable_gltf", "fbx_interchange", "obj_legacy"] = (
        "portable_gltf"
    )
    destination_hint: ProductionDestinationHint = Field(
        default_factory=ProductionDestinationHint
    )
    include_destination_handoff: bool = False
    convergence: ProductionConvergenceRequest = Field(
        default_factory=ProductionConvergenceRequest
    )
    primary_reference: ProductionArtifact
    created_at: datetime

    @model_validator(mode="after")
    def validate_dispatch_scope(self) -> AssetProductionDispatchRequest:
        """Preserve explicit object-only and fast-lane restrictions in dispatch evidence."""

        if self.reference_content_scope == "primary_object_only" and not self.target_subject:
            raise ValueError("primary_object_only dispatch requires target_subject")
        if self.execution_policy == "background_exterior" and self.mode != "concept":
            raise ValueError("background_exterior dispatch supports concept mode only")
        if self.execution_policy == "background_exterior" and self.include_destination_handoff:
            raise ValueError(
                "background_exterior dispatch requires a separate post-package handoff"
            )
        if self.include_destination_handoff and self.profile_id == "obj_legacy":
            raise ValueError("destination handoff supports GLB and FBX packages only")
        convergence_enabled = self.convergence.mode == "bounded_after_v06"
        if convergence_enabled != (self.delivery_scope == "v06_convergence"):
            raise ValueError(
                "bounded convergence dispatches must use delivery_scope=v06_convergence"
            )
        if convergence_enabled and self.execution_policy != "standard":
            raise ValueError("bounded convergence production is standard-only")
        if convergence_enabled and self.include_destination_handoff:
            raise ValueError(
                "V0.6 convergence delivery cannot include destination handoff"
            )
        return self


class DelegatedProductionControllerPlan(V09StrictModel):
    """Declare the single-writer controller and bounded read-only delegation policy."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    controller_id: PortableId
    dispatch_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    workflow_plan: ProductionArtifact
    canonical_writer: Literal["controller_only"] = "controller_only"
    subagent_mode: Literal["read_only_advisory"] = "read_only_advisory"
    max_parallel_read_only_advisors: int = Field(default=3, ge=1, le=3)
    subagent_write_allowlist: list[RelativePath] = Field(default_factory=list, max_length=0)
    host_execution: Literal["v08_resume_workflow"] = "v08_resume_workflow"
    failed_retry_policy: Literal["explicit_only"] = "explicit_only"
    approval_boundaries: list[
        Literal[
            "generic_workflow_gate",
            "interior_scope",
            "interior_qa_plan",
            "visual_revision",
            "candidate_review_decision",
            "visual_convergence_plan",
            "optimization_plan",
            "destination_handoff_plan",
            "failed_step_retry",
        ]
    ] = Field(min_length=1)
    run_postflight_audit: Literal[True] = True
    created_at: datetime


class CodexTaskLaunchManifest(V09StrictModel):
    """Describe a prepared Codex task without claiming that the repository launched it."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    launch_id: PortableId
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    launch_mode: Literal["client_mediated"] = "client_mediated"
    launch_status: Literal["prepared"] = "prepared"
    task_created_by_repository: Literal[False] = False
    task_title: str = Field(min_length=1, max_length=160)
    working_directory: Literal["."] = "."
    task_prompt: ProductionArtifact
    controller_plan: ProductionArtifact
    controller_tool_policy: Literal["allowlist_only"] = "allowlist_only"
    controller_mcp_allowlist: list[str] = Field(min_length=1)
    controller_forbidden_mcp_tools: list[str] = Field(min_length=1)
    controller_shell_policy: Literal["approval_and_retry_commands_denied"] = (
        "approval_and_retry_commands_denied"
    )
    client_tool_policy_enforcement_required: Literal[True] = True
    required_client_capabilities: list[
        Literal[
            "create_or_start_codex_task",
            "resume_codex_task",
            "read_repository_files",
            "call_project_mcp_tools",
            "delegate_read_only_subagents",
            "enforce_controller_tool_profile",
        ]
    ] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    prepared_at: datetime


class AssetProductionDispatchPlan(V09StrictModel):
    """Bind dispatcher, workflow, launch prompt, and controller to immutable hashes."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_request: ProductionArtifact
    workflow_request: ProductionArtifact
    workflow_routing: ProductionArtifact
    workflow_plan: ProductionArtifact
    controller_plan: ProductionArtifact
    launch_manifest: ProductionArtifact
    task_prompt: ProductionArtifact
    target_boundary: Literal[
        "engine_neutral_package",
        "engine_neutral_package_and_optional_handoff",
        "approved_v06_convergence_terminal",
    ]
    task_creation_boundary: Literal["client_mediated"] = "client_mediated"
    existing_approval_contracts_preserved: Literal[True] = True
    created_at: datetime


class CodexTaskBinding(V09StrictModel):
    """Bind one client-created Codex task to the exact prepared launch manifest."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    binding_id: PortableId
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    launch_manifest_sha256: Sha256
    task_prompt_sha256: Sha256
    controller_tool_profile_sha256: Sha256
    client_tool_policy_enforced: Literal[True] = True
    external_task_id: str = Field(min_length=1, max_length=256)
    external_host_id: str | None = Field(default=None, min_length=1, max_length=256)
    bound_at: datetime


class CodexTaskBindingReceipt(V09StrictModel):
    """Anchor one task binding to the immutable dispatch and launch evidence."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_plan_sha256: Sha256
    task_binding: CodexTaskBinding
    launch_manifest_sha256: Sha256
    task_prompt_sha256: Sha256
    recorded_at: datetime


class DelegatedWorkAssignment(V09StrictModel):
    """Issue one exact read-only advisory subtask for the current V0.8 agent step."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    assignment_id: PortableId
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    workflow_plan_sha256: Sha256
    input_fingerprint: Sha256
    advisory_role: Literal[
        "reference_reviewer",
        "geometry_reviewer",
        "material_reviewer",
        "qa_reviewer",
        "portable_reviewer",
        "destination_reviewer",
        "general_reviewer",
    ]
    prompt: str = Field(min_length=1, max_length=8000)
    read_artifacts: list[ProductionArtifact] = Field(default_factory=list)
    canonical_write_authority: Literal["controller_only"] = "controller_only"
    subagent_write_allowlist: list[RelativePath] = Field(default_factory=list, max_length=0)
    controller_expected_outputs: list[RelativePath] = Field(default_factory=list)
    issued_at: datetime


class ProductionApprovalBoundary(V09StrictModel):
    """Expose one exact existing approval boundary without creating an approval."""

    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    gate: str = Field(min_length=1, max_length=96)
    exact_fingerprint: Sha256
    specialized: bool
    instruction: str = Field(min_length=1, max_length=2000)


class ProductionPostflightAuditReceipt(V09StrictModel):
    """Atomically bind a fresh V0.9 audit to one completed workflow state."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_plan_sha256: Sha256
    workflow_state_fingerprint: Sha256
    terminal_artifacts: list[ProductionArtifact]
    workflow_authority_artifacts: list[ProductionArtifact] = Field(default_factory=list)
    audit_report: WorkspaceAuditReport
    recorded_at: datetime


class ProductionConvergenceBinding(V09StrictModel):
    """Bind one production dispatch to an exact V0.6 convergence plan and baseline."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    binding_id: PortableId
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    workflow_state_fingerprint: Sha256
    initial_qa_run_id: PortableId
    initial_qa_report: ProductionArtifact
    convergence_session_id: PortableId
    convergence_plan: ProductionArtifact
    created_at: datetime


class DelegatedProductionAdvanceReceipt(V09StrictModel):
    """Preserve one immutable controller transition in a hash-chained receipt stream."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    sequence: int = Field(ge=1)
    previous_receipt_sha256: Sha256 | None = None
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_plan_sha256: Sha256
    workflow_state_before_sha256: Sha256
    workflow_state_after_sha256: Sha256
    workflow_state_before: ProductionArtifact
    workflow_state_after: ProductionArtifact
    action: ProductionNextAction
    task_binding: ProductionArtifact | None = None
    assignment: ProductionArtifact | None = None
    postflight_audit: ProductionArtifact | None = None
    convergence_artifact: ProductionArtifact | None = None
    note: str = Field(min_length=1, max_length=2000)
    recorded_at: datetime


class DelegatedProductionState(V09StrictModel):
    """Project exact workflow evidence into the next safe controller action."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    dispatch_id: PortableId
    controller_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_plan_sha256: Sha256
    workflow_plan_sha256: Sha256
    workflow_state_sha256: Sha256
    integrity_status: Literal["valid"] = "valid"
    status: ProductionStatus
    workflow_status: str = Field(min_length=1, max_length=64)
    milestone: str = Field(min_length=1, max_length=96)
    current_step_id: str | None = Field(default=None, max_length=128)
    next_action: ProductionNextAction
    current_assignment: ProductionArtifact | None = None
    approval_boundary: ProductionApprovalBoundary | None = None
    task_binding: ProductionArtifact | None = None
    postflight_audit: ProductionArtifact | None = None
    convergence_binding: ProductionArtifact | None = None
    convergence_report: ProductionArtifact | None = None
    delivery_artifacts: list[ProductionArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_action_payload(self) -> DelegatedProductionState:
        """Require assignments and approvals only for their matching controller actions."""

        assignment_actions = {"controller_author"}
        approval_actions = {"request_generic_approval", "request_specialized_approval"}
        if self.next_action in assignment_actions and self.current_assignment is None:
            raise ValueError("controller authoring actions require a current assignment")
        if self.next_action not in assignment_actions and self.current_assignment is not None:
            raise ValueError("assignment evidence is valid only for controller authoring")
        if self.next_action in approval_actions and self.approval_boundary is None:
            raise ValueError("approval action requires an exact approval boundary")
        if self.next_action not in approval_actions and self.approval_boundary is not None:
            raise ValueError("approval evidence is valid only while waiting for approval")
        return self
