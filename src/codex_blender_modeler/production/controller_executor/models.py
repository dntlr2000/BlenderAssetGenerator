"""Strict ControllerExecutor 0.1.0 contracts for isolated candidate authoring."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

SCHEMA_VERSION = "0.1.0"


class ControllerStrictModel(BaseModel):
    """Reject undeclared fields, coercion, and non-finite values in controller evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class ControllerArtifact(ControllerStrictModel):
    """Bind one controller input or output to exact job-contained bytes."""

    artifact_id: PortableId
    role: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)


class ControllerEvidenceEnvelope(ControllerStrictModel):
    """Provide the immutable identity and provenance shared by executor contracts."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    contract_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: str = Field(min_length=1, max_length=128)
    producer_version: Literal["0.1.0"] = SCHEMA_VERSION
    provenance: list[ControllerArtifact] = Field(min_length=1)
    created_at: datetime


class PhaseToolProfile(ControllerEvidenceEnvelope):
    """Declare a hash-bound, phase-specific tool and filesystem authority ceiling."""

    profile_id: Literal[
        "reference_readonly",
        "geometry_authoring",
        "material_authoring",
        "codex_imagegen",
        "quality_readonly",
        "delivery",
        "handoff_plan",
        "admin_audit",
    ]
    allowed_tools: list[str]
    forbidden_tools: list[str] = Field(min_length=1)
    allowed_input_roles: list[str] = Field(min_length=1)
    allowed_output_paths: list[RelativePath]
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"
    network_access: Literal["denied"] = "denied"
    destination_project_write: Literal[False] = False
    sandbox_attestation: Literal[
        "repository_path_validation_only",
        "supporting_client_enforced",
    ] = "repository_path_validation_only"

    @model_validator(mode="after")
    def validate_tools_and_paths(self) -> PhaseToolProfile:
        """Reject duplicated or contradictory tool and output declarations."""

        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("allowed tools must be unique")
        if len(self.forbidden_tools) != len(set(self.forbidden_tools)):
            raise ValueError("forbidden tools must be unique")
        if set(self.allowed_tools) & set(self.forbidden_tools):
            raise ValueError("a tool cannot be both allowed and forbidden")
        if len(self.allowed_output_paths) != len(set(self.allowed_output_paths)):
            raise ValueError("allowed output paths must be unique")
        if self.profile_id.endswith("readonly") and self.allowed_output_paths:
            raise ValueError("read-only profiles cannot declare output paths")
        return self


class ControllerExecutionRequest(ControllerEvidenceEnvelope):
    """Freeze one bounded controller call and its isolated input/output contract."""

    execution_id: PortableId
    controller_kind: Literal[
        "desktop_in_session",
        "fake_for_tests",
        "optional_codex_app_server",
    ]
    assignment: ControllerArtifact
    immutable_inputs: list[ControllerArtifact] = Field(min_length=1)
    tool_profile: ControllerArtifact
    output_root: RelativePath
    allowed_output_paths: list[RelativePath] = Field(min_length=1)
    expected_output_sha256: dict[RelativePath, Sha256] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=900, ge=1, le=3600)
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"
    invocation_budget: Literal[1] = 1

    @model_validator(mode="after")
    def validate_request_paths(self) -> ControllerExecutionRequest:
        """Require every allowed output to be a unique descendant of output_root."""

        prefix = self.output_root.rstrip("/") + "/"
        if len(self.allowed_output_paths) != len(set(self.allowed_output_paths)):
            raise ValueError("allowed output paths must be unique")
        if any(not path.startswith(prefix) for path in self.allowed_output_paths):
            raise ValueError("allowed controller outputs must stay below output_root")
        if set(self.expected_output_sha256) - set(self.allowed_output_paths):
            raise ValueError("expected output hashes must reference allowed outputs")
        input_paths = [item.path for item in self.immutable_inputs]
        if len(input_paths) != len(set(input_paths)):
            raise ValueError("immutable controller inputs must have unique paths")
        return self


class ControllerResult(ControllerEvidenceEnvelope):
    """Record a validated controller outcome without granting canonical authority."""

    execution_id: PortableId
    controller_kind: Literal[
        "desktop_in_session",
        "fake_for_tests",
        "optional_codex_app_server",
    ]
    status: Literal[
        "completed",
        "waiting_for_output",
        "timeout",
        "failed",
        "rejected",
        "cancelled",
    ]
    request: ControllerArtifact
    tool_profile: ControllerArtifact
    outputs: list[ControllerArtifact]
    output_inventory_sha256: Sha256
    canonical_unchanged: Literal[True] = True
    extra_output_count: int = Field(default=0, ge=0)
    partial_output_count: int = Field(default=0, ge=0)
    retryable: bool = False
    limitations: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_outcome(self) -> ControllerResult:
        """Keep completed, waiting, and rejected controller outcomes internally honest."""

        if self.completed_at < self.started_at:
            raise ValueError("controller completion cannot precede start")
        if self.status == "completed":
            if not self.outputs or self.extra_output_count or self.partial_output_count:
                raise ValueError("completed controller result requires exact complete outputs")
            if self.retryable:
                raise ValueError("completed controller result cannot be retryable")
        if self.status == "waiting_for_output" and self.outputs:
            raise ValueError("waiting controller result cannot claim adopted outputs")
        if self.status == "rejected" and not (
            self.extra_output_count or self.partial_output_count or self.diagnostics
        ):
            raise ValueError("rejected controller result requires a rejection reason")
        if self.status not in {"timeout", "failed"} and self.retryable:
            raise ValueError("only timeout or failed controller results may be retryable")
        return self


class ControllerCapabilityStatus(ControllerStrictModel):
    """Describe availability without pretending an unverified adapter can execute."""

    controller_kind: Literal[
        "desktop_in_session",
        "fake_for_tests",
        "optional_codex_app_server",
    ]
    status: Literal["available", "test_only", "experimental_unverified", "unavailable"]
    official_interface_detected: bool
    repository_can_spawn_codex_task: Literal[False] = False
    limitations: list[str] = Field(min_length=1)
