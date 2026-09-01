"""Strict Skill Orchestration 0.1 contracts and immutable trace evidence."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
PORTABLE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"
JOB_ID_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$"


def _validate_relative_path(value: str) -> str:
    """Require normalized POSIX paths that cannot escape their owning root."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty normalized POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path contains an empty, current, or parent segment")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
PortableId = Annotated[str, Field(pattern=PORTABLE_ID_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]
ExecutionMode = Literal["standard", "aq"]
SkillStatus = Literal["active", "compatibility", "disabled_experimental"]
SkillRole = Literal["entrypoint", "stage", "leaf"]
StandardGoal = Literal[
    "new_asset_to_qa",
    "polish_existing_to_qa",
    "material_refresh_to_qa",
    "qa_repair_cycle",
    "full_cycle_to_package",
]
StagePolicy = Literal["smart", "force_all"]
HumanQualityDisposition = Literal["accepted", "needs_revision"]


class SkillStrictModel(BaseModel):
    """Reject undeclared fields and non-finite values in skill evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SkillArtifact(SkillStrictModel):
    """Bind one job-relative immutable artifact to its exact bytes."""

    path: RelativePath
    sha256: Sha256


class SkillDefinition(SkillStrictModel):
    """Declare one bounded project skill and its fixed routing authority."""

    skill_id: PortableId
    status: SkillStatus
    role: SkillRole
    description: str = Field(min_length=1, max_length=512)
    skill_path: RelativePath
    supporting_resources: list[RelativePath] = Field(default_factory=list)
    execution_modes: list[ExecutionMode] = Field(min_length=1)
    dependencies: list[PortableId] = Field(default_factory=list)
    route_keys: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_skill_definition(self) -> SkillDefinition:
        """Keep routes, dependencies, modes, resources, and tools deterministic."""

        for label, values in (
            ("execution_modes", self.execution_modes),
            ("dependencies", self.dependencies),
            ("route_keys", self.route_keys),
            ("supporting_resources", self.supporting_resources),
            ("allowed_tools", self.allowed_tools),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"skill {label} must be unique")
        if self.skill_id in self.dependencies:
            raise ValueError("skill cannot depend on itself")
        if self.role == "entrypoint" and self.route_keys:
            raise ValueError("entrypoint skills cannot own stage route keys")
        if self.role != "entrypoint" and not self.route_keys:
            raise ValueError("stage and leaf skills require at least one route key")
        return self


class SkillRegistry(SkillStrictModel):
    """Publish the complete project skill DAG and its two public entrypoints."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    registry_id: Literal["cbm-skill-registry"] = "cbm-skill-registry"
    project_version: Literal["0.9.0"] = "0.9.0"
    entry_skills: list[PortableId] = Field(min_length=2, max_length=2)
    skills: list[SkillDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_registry_graph(self) -> SkillRegistry:
        """Require known acyclic dependencies and unique mode-scoped routes."""

        ids = [item.skill_id for item in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("skill IDs must be unique")
        skill_map = {item.skill_id: item for item in self.skills}
        if len(self.entry_skills) != len(set(self.entry_skills)):
            raise ValueError("entry skill IDs must be unique")
        if set(self.entry_skills) != {
            "standard-asset-cycle",
            "aq-one-prompt-orchestrator",
        }:
            raise ValueError("registry must expose exactly the two approved entry skills")
        for entry_id in self.entry_skills:
            entry = skill_map.get(entry_id)
            if entry is None or entry.role != "entrypoint":
                raise ValueError("entry_skills must reference entrypoint definitions")
        unknown = {
            dependency
            for item in self.skills
            for dependency in item.dependencies
            if dependency not in skill_map
        }
        if unknown:
            raise ValueError(f"registry contains unknown dependencies: {sorted(unknown)}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(skill_id: str) -> None:
            """Traverse one dependency branch and reject cycles."""

            if skill_id in visiting:
                raise ValueError(f"skill dependency cycle includes {skill_id}")
            if skill_id in visited:
                return
            visiting.add(skill_id)
            for dependency in skill_map[skill_id].dependencies:
                visit(dependency)
            visiting.remove(skill_id)
            visited.add(skill_id)

        for skill_id in ids:
            visit(skill_id)

        routes: set[tuple[str, str]] = set()
        for item in self.skills:
            for mode in item.execution_modes:
                for route_key in item.route_keys:
                    key = (mode, route_key)
                    if key in routes:
                        raise ValueError(f"duplicate skill route: {mode}:{route_key}")
                    routes.add(key)
        return self


class SkillBundleResource(SkillStrictModel):
    """Record one live skill resource copied into a run-owned snapshot."""

    skill_id: PortableId
    source_path: RelativePath
    snapshot_path: RelativePath
    sha256: Sha256


class SkillBundleManifest(SkillStrictModel):
    """Bind a top-level invocation to its exact transitive skill snapshot."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    bundle_id: PortableId
    run_id: PortableId
    job_id: JobId
    entry_skill_id: PortableId
    execution_mode: ExecutionMode
    registry_snapshot: SkillArtifact
    skill_ids: list[PortableId] = Field(min_length=1)
    resources: list[SkillBundleResource] = Field(min_length=1)
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    created_at: datetime

    @model_validator(mode="after")
    def validate_bundle(self) -> SkillBundleManifest:
        """Require a unique bundle that includes its selected entry skill."""

        if len(self.skill_ids) != len(set(self.skill_ids)):
            raise ValueError("bundle skill IDs must be unique")
        if self.entry_skill_id not in self.skill_ids:
            raise ValueError("bundle must contain its entry skill")
        resource_keys = [(item.skill_id, item.snapshot_path) for item in self.resources]
        if len(resource_keys) != len(set(resource_keys)):
            raise ValueError("bundle resources must be unique")
        if {item.skill_id for item in self.resources} - set(self.skill_ids):
            raise ValueError("bundle resource references a skill outside the bundle")
        return self


class SkillRouteDecision(SkillStrictModel):
    """Select one snapshotted stage skill from an exact underlying state."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    decision_id: PortableId
    run_id: PortableId
    job_id: JobId
    execution_mode: ExecutionMode
    stage_key: str = Field(min_length=1, max_length=128)
    selected_skill_id: PortableId
    bundle_manifest: SkillArtifact
    source_state: SkillArtifact
    reason: str = Field(min_length=1, max_length=1000)
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    decided_at: datetime


class UnderlyingExecutionBinding(SkillStrictModel):
    """Bind one trace event to an existing V0.8 or AQ state machine."""

    execution_kind: Literal["workflow_v08", "aq_one_prompt_v01"]
    execution_id: PortableId
    state: SkillArtifact
    status: str = Field(min_length=1, max_length=128)
    next_action: str | None = Field(default=None, max_length=1000)


class SkillExecutionReceipt(SkillStrictModel):
    """Append one immutable projection of an underlying execution transition."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    run_id: PortableId
    job_id: JobId
    sequence: int = Field(ge=1)
    route_decision: SkillArtifact
    before: UnderlyingExecutionBinding
    after: UnderlyingExecutionBinding
    outcome: Literal[
        "advanced",
        "waiting_for_agent",
        "waiting_for_approval",
        "waiting_for_controller",
        "waiting_for_external_revision",
        "completed",
        "blocked",
        "failed",
        "cancelled",
        "slice_exhausted",
    ]
    previous_receipt_sha256: Sha256 | None = None
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_receipt_chain_origin(self) -> SkillExecutionReceipt:
        """Permit a missing predecessor only for the first execution receipt."""

        if (self.sequence == 1) != (self.previous_receipt_sha256 is None):
            raise ValueError("only the first skill receipt may omit its predecessor")
        return self


class MaterialImpactSnapshot(SkillStrictModel):
    """Freeze material-sensitive canonical inputs at one Standard boundary."""

    scene_spec: SkillArtifact | None = None
    modeling_plan: SkillArtifact | None = None
    material_plan: SkillArtifact | None = None
    scene_inventory: SkillArtifact | None = None


class MaterialImpactReport(SkillStrictModel):
    """Explain whether a completed geometry stage requires fresh V0.5 work."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    report_id: PortableId
    run_id: PortableId
    job_id: JobId
    stage_policy: StagePolicy
    before: MaterialImpactSnapshot
    after: MaterialImpactSnapshot
    material_authoring_required: bool
    changed_inputs: list[str]
    reasons: list[str] = Field(min_length=1)
    evaluated_at: datetime

    @model_validator(mode="after")
    def validate_material_decision(self) -> MaterialImpactReport:
        """Require force-all runs to schedule material work explicitly."""

        if self.stage_policy == "force_all" and not self.material_authoring_required:
            raise ValueError("force_all material impact must require V0.5 authoring")
        if len(self.changed_inputs) != len(set(self.changed_inputs)):
            raise ValueError("changed material inputs must be unique")
        return self


class StandardTechnicalRecoveryBinding(SkillStrictModel):
    """Bind one failed Standard child to a guarded geometry continuation."""

    recovery_id: PortableId
    recovery_sequence: int = Field(ge=1, le=8)
    recovery_kind: Literal["guarded_geometry_continuation"] = (
        "guarded_geometry_continuation"
    )
    failed_stage_binding: SkillArtifact
    failed_workflow_state: SkillArtifact
    failed_execution_receipt: SkillArtifact
    failed_step_id: PortableId
    failed_input_fingerprint: Sha256
    failure_reason_code: Literal["host_failure"] = "host_failure"
    canonical_scene_spec_snapshot: SkillArtifact
    recovery_reason: str = Field(min_length=1, max_length=1000)
    technical_failure: Literal[True] = True
    user_approval_requested: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    created_at: datetime


class StandardManualGuardedRerouteBinding(SkillStrictModel):
    """Bind one untouched ineligible child to its manual guarded replacement."""

    reroute_id: PortableId
    reroute_sequence: int = Field(ge=1, le=8)
    reroute_kind: Literal["manual_guarded_correction"] = "manual_guarded_correction"
    source_stage_binding: SkillArtifact
    source_workflow_state: SkillArtifact
    cancelled_workflow_state: SkillArtifact
    cancellation_receipt: SkillArtifact
    reroute_reason: str = Field(min_length=1, max_length=1000)
    technical_failure: Literal[True] = True
    user_approval_requested: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    created_at: datetime


class StandardCompositeStageBinding(SkillStrictModel):
    """Bind one Standard composite stage to one immutable V0.8 child workflow."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    binding_id: PortableId
    run_id: PortableId
    job_id: JobId
    ordinal: int = Field(ge=1, le=32)
    stage_kind: Literal["geometry", "material", "qa", "portable"]
    skill_id: PortableId
    workflow_id: PortableId
    workflow_plan: SkillArtifact
    technical_recovery: StandardTechnicalRecoveryBinding | None = None
    technical_reroute: StandardManualGuardedRerouteBinding | None = None
    created_reason: str = Field(min_length=1, max_length=1000)
    created_at: datetime

    @model_validator(mode="after")
    def validate_technical_recovery_boundary(self) -> StandardCompositeStageBinding:
        """Restrict technical recovery and reroute evidence to guarded geometry."""

        if self.technical_recovery is not None and self.technical_reroute is not None:
            raise ValueError("a Standard stage cannot be both recovery and reroute")
        if self.technical_recovery is None and self.technical_reroute is None:
            return self
        if self.ordinal < 2:
            raise ValueError("technical continuation cannot replace the initial child binding")
        if self.stage_kind != "geometry" or self.skill_id != "guarded-visual-revision":
            raise ValueError("technical continuation must create guarded geometry")
        if self.technical_reroute is not None and self.ordinal < 2:
            raise ValueError("manual guarded reroute requires a prior candidate child")
        return self


class StandardCompositeRunPlan(SkillStrictModel):
    """Plan one bounded Standard cycle without replacing V0.8 workflow authority."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    plan_id: PortableId
    run_id: PortableId
    job_id: JobId
    request_text: str = Field(min_length=1, max_length=4000)
    goal: StandardGoal
    stage_policy: StagePolicy = "smart"
    max_qa_revision_iterations: int = Field(default=1, ge=0, le=5)
    profile_id: Literal["portable_gltf", "fbx_interchange", "obj_legacy"] = (
        "portable_gltf"
    )
    bundle_manifest: SkillArtifact
    initial_material_snapshot: MaterialImpactSnapshot
    initial_stage_binding: SkillArtifact
    created_at: datetime


class GuardedRevisionContinuation(SkillStrictModel):
    """Bind one externally applied exact V0.6 revision before composite QA resumes."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    continuation_id: PortableId
    run_id: PortableId
    job_id: JobId
    iteration: int = Field(ge=1, le=5)
    source_qa_run_id: PortableId
    baseline_scene_spec_sha256: Sha256
    result_scene_spec_sha256: Sha256
    source_visual_qa_report: SkillArtifact
    candidates: SkillArtifact
    revision_plan: SkillArtifact
    consumed_user_approval: SkillArtifact
    application_report: SkillArtifact
    convergence_report: SkillArtifact | None = None
    application_status: Literal["accepted", "applied_unverified"]
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    validated_at: datetime

    @model_validator(mode="after")
    def validate_convergence_binding(self) -> GuardedRevisionContinuation:
        """Require accepted applications, but not unverified applies, to bind convergence."""

        if self.baseline_scene_spec_sha256 == self.result_scene_spec_sha256:
            raise ValueError("guarded revision continuation requires a changed SceneSpec")
        if (self.application_status == "accepted") != (
            self.convergence_report is not None
        ):
            raise ValueError("accepted guarded revisions require exact convergence evidence")
        return self


class StandardQualityDispositionRequest(SkillStrictModel):
    """Bind one human quality decision to exact completed V0.6 evidence."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    request_id: PortableId
    sequence: int = Field(ge=1, le=6)
    run_id: PortableId
    job_id: JobId
    qa_source_stage_binding: SkillArtifact
    completed_qa_state: SkillArtifact
    source_visual_qa_report: SkillArtifact
    canonical_scene_spec_snapshot: SkillArtifact
    source_qa_run_id: PortableId
    qa_review_input_fingerprint: Sha256
    qa_review_completion_fingerprint: Sha256
    qa_review_approval_id: PortableId
    direct_score: float = Field(ge=0, le=1)
    silhouette_iou: float = Field(ge=0, le=1)
    high_finding_ids: list[str] = Field(default_factory=list)
    recommended_disposition: HumanQualityDisposition
    allowed_dispositions: tuple[Literal["accepted"], Literal["needs_revision"]] = (
        "accepted",
        "needs_revision",
    )
    human_decision_required: Literal[True] = True
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    created_at: datetime

    @model_validator(mode="after")
    def validate_quality_recommendation(self) -> StandardQualityDispositionRequest:
        """Recommend revision exactly when high-severity direct QA findings remain."""

        if len(self.high_finding_ids) != len(set(self.high_finding_ids)):
            raise ValueError("quality-disposition high finding IDs must be unique")
        expected = "needs_revision" if self.high_finding_ids else "accepted"
        if self.recommended_disposition != expected:
            raise ValueError("quality-disposition recommendation differs from QA findings")
        return self


class StandardQualityDispositionRecord(SkillStrictModel):
    """Record one exact single-use human quality decision without approval authority."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    disposition_id: PortableId
    sequence: int = Field(ge=1, le=6)
    run_id: PortableId
    job_id: JobId
    request: SkillArtifact
    request_fingerprint: Sha256
    disposition: HumanQualityDisposition
    user_note: str = Field(min_length=1, max_length=1000)
    human_decision_observed: Literal[True] = True
    single_use: Literal[True] = True
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    recorded_at: datetime


class StandardCompositeRunState(SkillStrictModel):
    """Project the current child workflow and next safe composite action."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    run_id: PortableId
    job_id: JobId
    plan: SkillArtifact
    status: Literal[
        "planned",
        "running",
        "waiting_for_agent",
        "waiting_for_approval",
        "waiting_for_quality_disposition",
        "waiting_for_external_revision",
        "completed",
        "blocked",
        "failed",
        "cancelled",
    ]
    current_stage_binding: SkillArtifact | None = None
    stage_bindings: list[SkillArtifact] = Field(min_length=1)
    material_impact_report: SkillArtifact | None = None
    qa_revision_iterations: int = Field(default=0, ge=0, le=5)
    qa_revision_source_run_id: PortableId | None = None
    qa_baseline_scene_spec_sha256: Sha256 | None = None
    qa_revision_evidence: list[SkillArtifact] = Field(default_factory=list, max_length=5)
    quality_disposition_requests: list[SkillArtifact] = Field(
        default_factory=list,
        max_length=6,
    )
    quality_dispositions: list[SkillArtifact] = Field(default_factory=list, max_length=6)
    current_quality_disposition_request: SkillArtifact | None = None
    next_action: str | None = Field(default=None, max_length=1000)
    receipt_chain_head_sha256: Sha256 | None = None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_revision_boundary(self) -> StandardCompositeRunState:
        """Keep QA source, baseline, iteration, and continuation evidence coherent."""

        has_revision_boundary = self.qa_revision_source_run_id is not None
        if has_revision_boundary != (self.qa_baseline_scene_spec_sha256 is not None):
            raise ValueError("QA revision source and baseline must appear together")
        if (self.status == "waiting_for_external_revision") != has_revision_boundary:
            raise ValueError("only an external-revision wait may carry its QA baseline")
        if len(self.qa_revision_evidence) != self.qa_revision_iterations:
            raise ValueError("QA revision evidence count must match completed iterations")
        if len(self.qa_revision_evidence) != len(
            {(item.path, item.sha256) for item in self.qa_revision_evidence}
        ):
            raise ValueError("QA revision evidence must be unique")
        request_count = len(self.quality_disposition_requests)
        disposition_count = len(self.quality_dispositions)
        if disposition_count > request_count or request_count - disposition_count > 1:
            raise ValueError("quality-disposition requests and records are noncontiguous")
        waiting_for_quality = self.status == "waiting_for_quality_disposition"
        if waiting_for_quality != (self.current_quality_disposition_request is not None):
            raise ValueError("only a quality-disposition wait may carry its current request")
        if waiting_for_quality:
            if request_count != disposition_count + 1:
                raise ValueError("quality-disposition wait requires one unconsumed request")
            if self.current_quality_disposition_request != self.quality_disposition_requests[-1]:
                raise ValueError("current quality-disposition request must be the latest request")
        elif request_count != disposition_count:
            raise ValueError("every prior quality-disposition request requires one record")
        if request_count != len(
            {(item.path, item.sha256) for item in self.quality_disposition_requests}
        ):
            raise ValueError("quality-disposition requests must be unique")
        if disposition_count != len(
            {(item.path, item.sha256) for item in self.quality_dispositions}
        ):
            raise ValueError("quality-disposition records must be unique")
        terminal = self.status in {"completed", "blocked", "cancelled"}
        if terminal == (self.current_stage_binding is not None):
            raise ValueError("terminal and resumable Standard states require opposite bindings")
        return self


class StandardCompositeRunTerminal(SkillStrictModel):
    """Close one Standard composite run without rewriting any child workflow."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    terminal_id: PortableId
    run_id: PortableId
    job_id: JobId
    plan: SkillArtifact
    final_state: SkillArtifact
    terminal_type: Literal["completed", "blocked", "failed", "cancelled"]
    final_workflow: UnderlyingExecutionBinding
    stage_bindings: list[SkillArtifact] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000)
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    created_at: datetime


class AQSkillAdapterPlan(SkillStrictModel):
    """Bind the AQ entry skill to one existing immutable One-Prompt plan."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    plan_id: PortableId
    run_id: PortableId
    job_id: JobId
    session_id: PortableId
    bundle_manifest: SkillArtifact
    one_prompt_plan: SkillArtifact
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    created_at: datetime


class AQSkillAdapterState(SkillStrictModel):
    """Project an AQ One-Prompt state into one uniquely routed stage skill."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    run_id: PortableId
    job_id: JobId
    session_id: PortableId
    plan: SkillArtifact
    status: str = Field(min_length=1, max_length=128)
    current_stage_key: str = Field(min_length=1, max_length=128)
    current_skill_id: PortableId
    source_state: SkillArtifact
    next_action: str | None = Field(default=None, max_length=1000)
    receipt_chain_head_sha256: Sha256 | None = None
    updated_at: datetime


class AQSkillAdapterTerminal(SkillStrictModel):
    """Close one AQ adapter projection without changing its authoritative AQ terminal."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    terminal_id: PortableId
    run_id: PortableId
    job_id: JobId
    session_id: PortableId
    plan: SkillArtifact
    final_state: SkillArtifact
    final_aq_state: SkillArtifact
    authoritative_aq_terminal: SkillArtifact
    one_prompt_terminal: SkillArtifact | None = None
    terminal_type: Literal[
        "production_delivery",
        "review_bundle",
        "genuine_escalation",
        "blocked",
        "cancelled",
        "reconciled_failed_recovery",
    ]
    recovery_package_acceptances: list[SkillArtifact] = Field(default_factory=list)
    campaign_terminal_candidate: bool
    original_terminal_reclassified: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    reason: str = Field(min_length=1, max_length=1000)
    created_at: datetime

    @model_validator(mode="after")
    def validate_terminal_projection(self) -> AQSkillAdapterTerminal:
        """Keep successful terminal classes separate from append-only recovery evidence."""

        expected_candidate = self.terminal_type in {
            "production_delivery",
            "review_bundle",
        }
        if self.campaign_terminal_candidate != expected_candidate:
            raise ValueError("AQ campaign terminal candidacy differs from terminal type")
        if self.recovery_package_acceptances and (
            self.terminal_type != "reconciled_failed_recovery"
        ):
            raise ValueError(
                "AQ recovery package acceptance requires a reconciled failed terminal"
            )
        if self.terminal_type == "reconciled_failed_recovery":
            if self.one_prompt_terminal is not None or not self.recovery_package_acceptances:
                raise ValueError(
                    "reconciled AQ failure requires recovery evidence and no "
                    "synthetic One-Prompt terminal"
                )
        elif (
            self.one_prompt_terminal is None
            or self.authoritative_aq_terminal != self.one_prompt_terminal
        ):
            raise ValueError(
                "ordinary AQ adapter terminal must bind its exact One-Prompt terminal"
            )
        if len(self.recovery_package_acceptances) != len(
            {(item.path, item.sha256) for item in self.recovery_package_acceptances}
        ):
            raise ValueError("AQ recovery package acceptances must be unique")
        return self
