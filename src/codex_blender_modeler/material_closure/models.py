"""Strict additive contracts for deterministic Material Closure 0.1.0 evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

MATERIAL_CLOSURE_SCHEMA_VERSION = "0.1.0"
SEMVER_PATTERN = r"^[0-9]+\.[0-9]+\.[0-9]+$"
TOKEN_PATTERN = r"^[a-z][a-z0-9_]{1,95}$"


def _validate_aware_datetime(value: datetime) -> datetime:
    """Require persisted event timestamps to identify an unambiguous instant."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("created_at must include a timezone offset")
    return value


AwareDateTime = Annotated[datetime, AfterValidator(_validate_aware_datetime)]
Token = Annotated[str, Field(pattern=TOKEN_PATTERN)]

ClosureStatus = Literal["passed", "failed"]
ClosureOwnership = Literal["canonical", "staging", "request_owned"]
ClosureSourceKind = Literal[
    "canonical_artifact",
    "staging_artifact",
    "request_input",
    "generated_evidence",
    "derived_evidence",
    "policy_evidence",
    "rollback_evidence",
]
MaterialAttemptStatus = Literal[
    "collecting_closure",
    "closure_failed",
    "rebinding",
    "preflighting",
    "preflight_failed",
    "approval_pending",
    "controller_pending",
    "controller_completed",
    "promoting",
    "promotion_succeeded",
    "rollback_started",
    "rollback_completed",
    "rollback_failed",
    "quality_pending",
    "blocked",
    "cancelled",
]
ApprovalImpact = Literal["no_visual_change", "appearance_change", "scope_change"]
MaterialRepairStep = Literal[
    "verify_geometry",
    "prepare_material_candidate",
    "collect_closure",
    "rebind_graph",
    "run_preflight",
    "shadow_compile",
    "neutral_preview",
    "request_material_approval",
    "controller_exact_adoption",
    "host_promotion",
    "material_phase_receipt",
    "quality_boundary",
]

MATERIAL_REPAIR_REQUIRED_STEPS: tuple[MaterialRepairStep, ...] = (
    "verify_geometry",
    "prepare_material_candidate",
    "collect_closure",
    "rebind_graph",
    "run_preflight",
    "shadow_compile",
    "neutral_preview",
    "request_material_approval",
    "controller_exact_adoption",
    "host_promotion",
    "material_phase_receipt",
    "quality_boundary",
)
MATERIAL_REPAIR_PREAPPROVAL_STEPS: tuple[MaterialRepairStep, ...] = (
    "verify_geometry",
    "prepare_material_candidate",
    "collect_closure",
    "rebind_graph",
    "run_preflight",
    "shadow_compile",
    "neutral_preview",
    "request_material_approval",
)

MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES: frozenset[str] = frozenset(
    {
        "material_closure_source_binding",
        "canonical_scene_spec",
        "modeling_plan",
        "aq_root_authorization",
        "aq_autonomy_plan",
        "aq_autonomy_profile",
        "aq_autonomy_budget",
        "material_phase_tool_profile",
        "geometry_candidate_validation_receipt",
        "canonical_build_provenance",
        "canonical_scene_inventory",
    }
)


class MaterialClosureStrictModel(BaseModel):
    """Reject undeclared fields, coercion, and non-finite numbers in 0.1.0 contracts."""

    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, strict=True, frozen=True
    )


class MaterialClosureBoundContract(MaterialClosureStrictModel):
    """Bind one top-level contract to its exact job, workflow, dispatch, and session."""

    schema_version: Literal["0.1.0"] = MATERIAL_CLOSURE_SCHEMA_VERSION
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    producer: PortableId
    producer_version: str = Field(pattern=SEMVER_PATTERN)
    created_at: AwareDateTime


class ExactArtifact(MaterialClosureStrictModel):
    """Bind one contained job-relative artifact by exact bytes and media type."""

    artifact_id: PortableId
    kind: Token
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(ge=0)
    media_type: str = Field(min_length=1, max_length=127)


class MaterialDependencyEntry(MaterialClosureStrictModel):
    """Describe one unique immutable input in a complete material dependency closure."""

    entry_id: PortableId
    role: Token
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(ge=0)
    source_kind: ClosureSourceKind
    required: bool
    producer: PortableId
    dependency_parent: PortableId | None = None
    semantic_id: PortableId | None = None
    material_id: PortableId | None = None
    ownership: ClosureOwnership


class MaterialClosureSourceBinding(MaterialClosureStrictModel):
    """Declare exact source-evidence roots required for one material authoring mode."""

    source_mode: Literal["procedural", "imagegen", "manual_image"]
    primary_reference_path: RelativePath
    reference_authority_path: RelativePath
    manual_image_source_path: RelativePath | None = None
    imagegen_provider_profile_path: RelativePath | None = None
    imagegen_assignment_path: RelativePath | None = None
    imagegen_completion_path: RelativePath | None = None
    imagegen_generated_image_evidence_path: RelativePath | None = None
    imagegen_normalization_plan_path: RelativePath | None = None
    imagegen_normalization_receipt_path: RelativePath | None = None
    imagegen_semantic_review_path: RelativePath | None = None
    imagegen_selection_receipt_path: RelativePath | None = None
    image_to_material_adoption_path: RelativePath | None = None
    material_authoring_request_path: RelativePath | None = None
    material_authoring_manifest_path: RelativePath | None = None
    material_authoring_receipt_path: RelativePath | None = None
    additional_evidence_paths: list[RelativePath] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_mode(self) -> MaterialClosureSourceBinding:
        """Require complete typed ImageGen/manual roots and keep extras purely additive."""

        imagegen_fields = (
            "imagegen_provider_profile_path",
            "imagegen_assignment_path",
            "imagegen_completion_path",
            "imagegen_generated_image_evidence_path",
            "imagegen_normalization_plan_path",
            "imagegen_normalization_receipt_path",
            "imagegen_semantic_review_path",
            "imagegen_selection_receipt_path",
            "image_to_material_adoption_path",
            "material_authoring_request_path",
            "material_authoring_manifest_path",
            "material_authoring_receipt_path",
        )
        present_imagegen = [name for name in imagegen_fields if getattr(self, name) is not None]
        if self.source_mode == "imagegen":
            if len(present_imagegen) != len(imagegen_fields):
                missing = sorted(set(imagegen_fields) - set(present_imagegen))
                raise ValueError(f"ImageGen source binding is incomplete: {missing}")
            if self.manual_image_source_path is not None:
                raise ValueError("ImageGen source binding cannot declare a manual image root")
        elif present_imagegen:
            raise ValueError("non-ImageGen source binding cannot declare ImageGen roots")
        elif self.source_mode == "manual_image":
            if self.manual_image_source_path is None:
                raise ValueError("manual image source binding requires its exact image root")
        elif self.manual_image_source_path is not None:
            raise ValueError("procedural source binding cannot declare a manual image root")
        all_paths = [
            self.primary_reference_path,
            self.reference_authority_path,
            *(
                value
                for name in imagegen_fields
                if (value := getattr(self, name)) is not None
            ),
            *(
                []
                if self.manual_image_source_path is None
                else [self.manual_image_source_path]
            ),
            *self.additional_evidence_paths,
        ]
        if len(all_paths) != len(set(all_paths)):
            raise ValueError("material source evidence paths must be unique")
        return self


class MaterialClosureSourceBindingArtifact(MaterialClosureBoundContract):
    """Persist host collection roots as exact replayable Material Closure evidence."""

    binding_id: PortableId
    authority_mode: Literal["aq_same_session", "material_repair_lineage"] = (
        "aq_same_session"
    )
    scene_spec_path: RelativePath
    modeling_plan_path: RelativePath
    root_authorization_path: RelativePath
    autonomy_plan_path: RelativePath
    autonomy_profile_path: RelativePath
    autonomy_budget_path: RelativePath
    material_phase_tool_profile_path: RelativePath
    geometry_candidate_validation_receipt_path: RelativePath
    canonical_build_provenance_path: RelativePath
    canonical_scene_inventory_path: RelativePath
    repair_source_binding_path: RelativePath | None = None
    canonical_material_plan_observation_path: RelativePath | None = None
    material_plan_baseline_snapshot_path: RelativePath | None = None
    material_plan_absence_evidence_path: RelativePath | None = None
    candidate_material_plan_path: RelativePath
    material_graph_path: RelativePath
    graph_rebinding_plan_path: RelativePath
    graph_rebinding_receipt_path: RelativePath
    rebound_material_graph_path: RelativePath
    rollback_baseline_path: RelativePath
    uv_layout_fingerprint: Sha256
    source_evidence: MaterialClosureSourceBinding

    @model_validator(mode="after")
    def validate_material_baseline(self) -> MaterialClosureSourceBindingArtifact:
        """Require complete canonical/AQ roots plus an exact MaterialPlan baseline."""

        if self.scene_spec_path != "analysis/scene_spec.json":
            raise ValueError("source binding must name the canonical SceneSpec path")
        if self.modeling_plan_path != "analysis/modeling_plan.json":
            raise ValueError("source binding must name the canonical ModelingPlan path")
        observation_prefix = (
            f"production/material_closure/{self.session_id}/canonical_observations/"
        )
        if self.canonical_build_provenance_path not in {
            "reports/build_provenance.json",
            f"{observation_prefix}build_provenance.json",
        }:
            raise ValueError("source binding must name a canonical build observation")
        if self.canonical_scene_inventory_path not in {
            "reports/scene_inventory.json",
            f"{observation_prefix}scene_inventory.json",
        }:
            raise ValueError("source binding must name a canonical scene observation")
        if self.authority_mode == "material_repair_lineage":
            if self.repair_source_binding_path is None:
                raise ValueError("material repair closure requires exact repair source lineage")
            repair_prefix = f"production/material_repair/{self.session_id}/"
            if not self.repair_source_binding_path.startswith(repair_prefix):
                raise ValueError("repair source lineage must be owned by the repair session")
        elif self.repair_source_binding_path is not None:
            raise ValueError("same-session AQ closure cannot declare repair lineage")
        required_common_paths = (
            self.scene_spec_path,
            self.modeling_plan_path,
            self.root_authorization_path,
            self.autonomy_plan_path,
            self.autonomy_profile_path,
            self.autonomy_budget_path,
            self.material_phase_tool_profile_path,
            self.geometry_candidate_validation_receipt_path,
            self.canonical_build_provenance_path,
            self.canonical_scene_inventory_path,
            *(
                []
                if self.repair_source_binding_path is None
                else [self.repair_source_binding_path]
            ),
            self.candidate_material_plan_path,
            self.material_graph_path,
            self.graph_rebinding_plan_path,
            self.graph_rebinding_receipt_path,
            self.rebound_material_graph_path,
            self.rollback_baseline_path,
        )
        if len(required_common_paths) != len(set(required_common_paths)):
            raise ValueError("material closure common root paths must be unique")

        existing = self.canonical_material_plan_observation_path is not None
        if existing:
            if (
                self.canonical_material_plan_observation_path
                != "analysis/material_plan.json"
                or self.material_plan_baseline_snapshot_path is None
                or self.material_plan_absence_evidence_path is not None
            ):
                raise ValueError(
                    "existing MaterialPlan requires canonical observation and snapshot"
                )
            if (
                self.material_plan_baseline_snapshot_path
                == self.canonical_material_plan_observation_path
            ):
                raise ValueError("MaterialPlan snapshot must use a run-owned path")
        elif (
            self.material_plan_baseline_snapshot_path is not None
            or self.material_plan_absence_evidence_path is None
        ):
            raise ValueError("absent MaterialPlan requires exact absence evidence only")
        elif self.material_plan_absence_evidence_path.startswith("analysis/"):
            raise ValueError(
                "MaterialPlan absence evidence must not mutate its observed parent"
            )
        rebind_paths = (
            self.material_graph_path,
            self.graph_rebinding_plan_path,
            self.graph_rebinding_receipt_path,
            self.rebound_material_graph_path,
        )
        if len(set(rebind_paths)) != len(rebind_paths):
            raise ValueError("graph source, plan, receipt, and rebound paths must differ")
        prefix = f"production/material_closure/{self.session_id}/graph_rebindings/"
        plan_parent, separator, plan_leaf = self.graph_rebinding_plan_path.rpartition("/")
        rebind_id = plan_parent.removeprefix(prefix)
        if (
            not separator
            or not plan_parent.startswith(prefix)
            or not rebind_id
            or "/" in rebind_id
            or plan_leaf != "plan.json"
            or self.graph_rebinding_receipt_path != f"{plan_parent}/receipt.json"
            or self.rebound_material_graph_path
            != f"{plan_parent}/rebound_material_graph.json"
        ):
            raise ValueError("graph rebind artifacts must use one canonical run-owned root")
        return self


class MaterialPlannedOutput(MaterialClosureStrictModel):
    """Declare one exact request-owned controller output before execution."""

    output_id: PortableId
    output_kind: Literal[
        "material_plan", "material_graph", "controller_completion", "additional"
    ]
    path: RelativePath
    verification: Literal["exact_hash", "structural_binding"]
    sha256: Sha256 | None = None
    expected_schema_version: str | None = Field(
        default=None, pattern=SEMVER_PATTERN
    )
    expected_field_bindings: dict[str, str] = Field(default_factory=dict)
    media_type: str = Field(min_length=1, max_length=127)
    request_owned: Literal[True] = True

    @model_validator(mode="after")
    def validate_verification(self) -> MaterialPlannedOutput:
        """Avoid circular completion hashes while requiring exact content output bytes."""

        if self.verification == "exact_hash":
            if self.sha256 is None:
                raise ValueError("exact-hash output requires sha256")
            if self.expected_schema_version is not None or self.expected_field_bindings:
                raise ValueError("exact-hash output cannot declare structural bindings")
        else:
            if self.sha256 is not None:
                raise ValueError("structurally bound output cannot declare a circular hash")
            if self.expected_schema_version is None or not self.expected_field_bindings:
                raise ValueError(
                    "structurally bound output requires schema and exact field bindings"
                )
        if self.output_kind == "controller_completion":
            if self.verification != "structural_binding":
                raise ValueError("controller completion must use structural binding")
        elif self.verification != "exact_hash":
            raise ValueError("material content outputs must use exact-hash verification")
        return self


class MaterialClosureIssue(MaterialClosureStrictModel):
    """Record one deterministic closure or preflight validation finding."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")
    message: str = Field(min_length=1, max_length=2000)
    path: RelativePath | None = None
    entry_id: PortableId | None = None
    required: bool = True


def _json_digest(value: object) -> str:
    """Hash one JSON-compatible value with canonical compact key ordering."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _closure_payload_digest(
    entries: list[MaterialDependencyEntry],
    planned_outputs: list[MaterialPlannedOutput],
    source_binding: ExactArtifact | None = None,
) -> str:
    """Hash source roots, sorted entries, and outputs without mutable metadata."""

    sorted_entries = sorted(entries, key=lambda item: (item.role, item.path))
    sorted_outputs = sorted(planned_outputs, key=lambda item: (item.output_kind, item.path))
    payload: dict[str, object] = {
            "entries": [item.model_dump(mode="json") for item in sorted_entries],
            "planned_outputs": [
                item.model_dump(mode="json") for item in sorted_outputs
            ],
        }
    if source_binding is not None:
        payload["source_binding"] = source_binding.model_dump(mode="json")
    return _json_digest(payload)


class MaterialDependencyClosure(MaterialClosureBoundContract):
    """Freeze the full exact dependency set and controller output projection."""

    closure_id: PortableId
    closure_sha256: Sha256
    collection_mode: Literal["host_graph_derived"] = "host_graph_derived"
    source_binding: ExactArtifact
    root_kind: Literal["job_root"] = "job_root"
    entries: list[MaterialDependencyEntry] = Field(min_length=1)
    planned_outputs: list[MaterialPlannedOutput] = Field(min_length=3)
    rollback_baseline: ExactArtifact

    @model_validator(mode="after")
    def validate_closure(self) -> MaterialDependencyClosure:
        """Reject collisions, output overlap, incomplete outputs, and stale fingerprints."""

        paths = [item.path for item in self.entries]
        material_observations = [
            item
            for item in self.entries
            if item.path == "analysis/material_plan.json"
            and item.role == "canonical_material_plan_observation"
        ]
        material_baselines = [
            item
            for item in self.entries
            if item.role == "material_plan_baseline_snapshot"
        ]
        if bool(material_observations) != bool(material_baselines):
            raise ValueError(
                "canonical MaterialPlan observation and run-owned baseline must be paired"
            )
        if material_observations:
            if len(material_observations) != 1 or len(material_baselines) != 1:
                raise ValueError("closure accepts one MaterialPlan observation/baseline pair")
            observation = material_observations[0]
            baseline = material_baselines[0]
            if observation.path == baseline.path:
                raise ValueError("MaterialPlan baseline must be a run-owned snapshot path")
            if (observation.sha256, observation.byte_size) != (
                baseline.sha256,
                baseline.byte_size,
            ):
                raise ValueError(
                    "MaterialPlan observation and baseline snapshot bytes must be identical"
                )
        if len(paths) != len(set(paths)):
            raise ValueError("material dependency paths must be unique")
        folded = [item.casefold() for item in paths]
        if len(folded) != len(set(folded)):
            raise ValueError("material dependency paths contain a case collision")
        entry_ids = [item.entry_id for item in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("material dependency entry IDs must be unique")
        roles = {item.role for item in self.entries}
        missing_root_roles = sorted(MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES - roles)
        if missing_root_roles:
            raise ValueError(
                "closure is missing required common roots: "
                + ", ".join(missing_root_roles)
            )
        duplicate_root_roles = sorted(
            role
            for role in MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES
            if sum(item.role == role for item in self.entries) != 1
        )
        if duplicate_root_roles:
            raise ValueError(
                "closure requires exactly one entry per common root role: "
                + ", ".join(duplicate_root_roles)
            )
        output_paths = [item.path for item in self.planned_outputs]
        if len(output_paths) != len(set(output_paths)):
            raise ValueError("planned output paths must be unique")
        output_folded = [item.casefold() for item in output_paths]
        if len(output_folded) != len(set(output_folded)):
            raise ValueError("planned output paths contain a case collision")
        if set(folded) & set(output_folded):
            raise ValueError("planned outputs must not collide with immutable inputs")
        output_kinds = {item.output_kind for item in self.planned_outputs}
        required_outputs = {"material_plan", "material_graph", "controller_completion"}
        if not required_outputs.issubset(output_kinds):
            raise ValueError("closure must plan material plan, graph, and completion outputs")
        if any(
            sum(item.output_kind == kind for item in self.planned_outputs) != 1
            for kind in required_outputs
        ):
            raise ValueError("closure requires exactly one core planned output per kind")
        candidate_entries = [
            item for item in self.entries if item.role == "candidate_material_plan"
        ]
        rebound_entries = [
            item for item in self.entries if item.role == "rebound_material_graph"
        ]
        rebind_plan_entries = [
            item for item in self.entries if item.role == "material_graph_rebinding_plan"
        ]
        rebind_receipt_entries = [
            item
            for item in self.entries
            if item.role == "material_graph_rebinding_receipt"
        ]
        source_graph_entries = [
            item for item in self.entries if item.role == "source_material_graph"
        ]
        if any(
            len(items) != 1
            for items in (
                candidate_entries,
                rebound_entries,
                source_graph_entries,
                rebind_plan_entries,
                rebind_receipt_entries,
            )
        ):
            raise ValueError("closure requires exact candidate and graph rebind evidence")
        exact_outputs = {
            item.output_kind: item
            for item in self.planned_outputs
            if item.verification == "exact_hash"
        }
        if exact_outputs["material_plan"].sha256 != candidate_entries[0].sha256:
            raise ValueError("planned MaterialPlan hash differs from immutable candidate")
        if exact_outputs["material_graph"].sha256 != rebound_entries[0].sha256:
            raise ValueError("planned MaterialGraph hash differs from immutable rebound graph")
        baseline = next(
            (
                item
                for item in self.entries
                if item.path == self.rollback_baseline.path
                and item.sha256 == self.rollback_baseline.sha256
            ),
            None,
        )
        if baseline is None or baseline.source_kind != "rollback_evidence":
            raise ValueError("rollback baseline must be an exact closure dependency")
        if self.closure_sha256 != _closure_payload_digest(
            self.entries, self.planned_outputs, self.source_binding
        ):
            raise ValueError("closure_sha256 differs from deterministic closure payload")
        return self

    def project_immutable_input_map(self) -> dict[str, str]:
        """Project every closure entry into the one canonical sorted immutable map."""

        return {
            item.path: item.sha256
            for item in sorted(self.entries, key=lambda entry: entry.path)
        }

    def project_planned_output_map(self) -> dict[str, str]:
        """Project exact-hash outputs while excluding structurally bound completion bytes."""

        return {
            item.path: item.sha256
            for item in sorted(self.planned_outputs, key=lambda output: output.path)
            if item.verification == "exact_hash" and item.sha256 is not None
        }


class MaterialDependencyClosureReceipt(MaterialClosureBoundContract):
    """Attest a replayed closure file and its exact deterministic projections."""

    receipt_id: PortableId
    closure: ExactArtifact
    closure_sha256: Sha256
    status: ClosureStatus
    issues: list[MaterialClosureIssue] = Field(default_factory=list)
    immutable_input_projection: dict[RelativePath, Sha256] = Field(min_length=1)
    planned_output_projection: dict[RelativePath, Sha256] = Field(min_length=2)
    canonical_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def validate_status(self) -> MaterialDependencyClosureReceipt:
        """Require pass/fail status to agree with all reported closure issues."""

        has_required_issue = any(item.required for item in self.issues)
        if self.status == "passed" and self.issues:
            raise ValueError("passed closure receipt cannot contain issues")
        if self.status == "failed" and not has_required_issue:
            raise ValueError("failed closure receipt requires a blocking issue")
        return self


class MaterialGraphRebindingChange(MaterialClosureStrictModel):
    """Describe one paired provenance path/hash replacement by JSON pointer."""

    dependency_role: Token
    path_pointer: str = Field(pattern=r"^/(?:[^/~]|~[01])+(?:/(?:[^/~]|~[01])+)*$")
    hash_pointer: str = Field(pattern=r"^/(?:[^/~]|~[01])+(?:/(?:[^/~]|~[01])+)*$")
    before_path: RelativePath
    before_sha256: Sha256
    after_path: RelativePath
    after_sha256: Sha256

    @model_validator(mode="after")
    def validate_pointers(self) -> MaterialGraphRebindingChange:
        """Restrict edits to one paired MaterialGraphArtifact path and digest."""

        if self.path_pointer == self.hash_pointer:
            raise ValueError("path and hash JSON pointers must be distinct")
        path_parts = self.path_pointer.split("/")
        hash_parts = self.hash_pointer.split("/")
        if path_parts[-1] != "path" or hash_parts[-1] != "sha256":
            raise ValueError(
                "rebinding pointers may target only artifact path/sha256 fields"
            )
        if path_parts[:-1] != hash_parts[:-1]:
            raise ValueError(
                "rebinding path and hash pointers must share one artifact parent"
            )
        if (
            self.before_path == self.after_path
            and self.before_sha256 == self.after_sha256
        ):
            raise ValueError("rebinding change must replace a path or hash")
        return self


class MaterialGraphRebindingPlan(MaterialClosureBoundContract):
    """Authorize only declared path/hash provenance changes to a graph derivative."""

    plan_id: PortableId
    source_binding: ExactArtifact
    source_graph: ExactArtifact
    candidate_material_plan: ExactArtifact
    output_path: RelativePath
    expected_rebound_sha256: Sha256
    changes: list[MaterialGraphRebindingChange] = Field(min_length=1)
    source_graph_immutable: Literal[True] = True
    semantics_may_change: Literal[False] = False

    @model_validator(mode="after")
    def validate_changes(self) -> MaterialGraphRebindingPlan:
        """Reject overlapping pointer edits and in-place graph replacement."""

        if self.output_path == self.source_graph.path:
            raise ValueError("rebound graph must use a distinct derivative path")
        if self.source_binding.kind != "material_closure_source_binding":
            raise ValueError("rebind plan requires the exact Material Closure source binding")
        expected_binding = (
            f"production/material_closure/{self.session_id}/source_binding.json"
        )
        if self.source_binding.path != expected_binding:
            raise ValueError("rebind plan source binding path is not canonical")
        expected = (
            f"production/material_closure/{self.session_id}/graph_rebindings/"
            f"{self.plan_id}/rebound_material_graph.json"
        )
        if self.output_path != expected:
            raise ValueError("rebound graph output path is not the canonical run-owned leaf")
        pointers = [
            pointer
            for change in self.changes
            for pointer in (change.path_pointer, change.hash_pointer)
        ]
        if len(pointers) != len(set(pointers)):
            raise ValueError("rebinding JSON pointers must be unique")
        return self


class MaterialGraphRebindingReceipt(MaterialClosureBoundContract):
    """Record the exact path-only graph derivative and complete before/after diff."""

    receipt_id: PortableId
    plan: ExactArtifact
    source_binding: ExactArtifact
    status: ClosureStatus
    source_graph: ExactArtifact
    rebound_graph: ExactArtifact | None = None
    applied_changes: list[MaterialGraphRebindingChange] = Field(default_factory=list)
    unauthorized_fields: list[str] = Field(default_factory=list)
    semantic_content_unchanged: bool
    source_graph_unchanged: Literal[True] = True
    issues: list[MaterialClosureIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> MaterialGraphRebindingReceipt:
        """Permit a passed receipt only for a separate semantics-preserving derivative."""

        if self.source_binding.kind != "material_closure_source_binding":
            raise ValueError("rebind receipt requires the exact source binding")
        expected_binding = (
            f"production/material_closure/{self.session_id}/source_binding.json"
        )
        if self.source_binding.path != expected_binding:
            raise ValueError("rebind receipt source binding path is not canonical")
        if self.plan.kind != "material_graph_rebinding_plan":
            raise ValueError("rebind receipt requires the exact rebinding plan")
        expected_plan = (
            f"production/material_closure/{self.session_id}/graph_rebindings/"
            f"{self.plan.artifact_id}/plan.json"
        )
        if self.plan.path != expected_plan:
            raise ValueError("rebind receipt plan path is not canonical")
        if self.status == "passed":
            if self.rebound_graph is None or not self.applied_changes:
                raise ValueError("passed rebinding requires derivative and applied changes")
            if self.unauthorized_fields or self.issues:
                raise ValueError("passed rebinding cannot report unauthorized changes")
            if not self.semantic_content_unchanged:
                raise ValueError("passed rebinding must preserve graph semantics")
            if self.rebound_graph.path == self.source_graph.path:
                raise ValueError("rebound graph receipt cannot overwrite its source")
            expected_rebound = (
                f"production/material_closure/{self.session_id}/graph_rebindings/"
                f"{self.plan.artifact_id}/rebound_material_graph.json"
            )
            if self.rebound_graph.path != expected_rebound:
                raise ValueError("rebound graph receipt uses a noncanonical derivative path")
        elif not self.issues:
            raise ValueError("failed rebinding requires at least one issue")
        return self


class SurfaceDetailUVRect(MaterialClosureStrictModel):
    """Represent one normalized non-empty surface-detail UV rectangle."""

    u_min: float = Field(ge=0.0, le=1.0)
    v_min: float = Field(ge=0.0, le=1.0)
    u_max: float = Field(ge=0.0, le=1.0)
    v_max: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_extent(self) -> SurfaceDetailUVRect:
        """Reject empty or backward UV placement rectangles."""

        if self.u_max <= self.u_min or self.v_max <= self.v_min:
            raise ValueError("surface-detail UV rectangle must have positive area")
        return self


class SurfaceDetailRequirement(MaterialClosureStrictModel):
    """Describe one localized detail that a material candidate must cover exactly."""

    detail_id: PortableId
    object_id: PortableId
    material_id: PortableId
    strategy: Literal["image", "hybrid"]
    uv_set: Literal["UVMap"]
    uv_layout_fingerprint: Sha256
    requested_channels: list[Literal[
        "base_color", "roughness", "metallic", "normal", "height", "opacity", "emission"
    ]] = Field(min_length=1)
    coverage_id: PortableId
    mask: ExactArtifact | None = None
    uv_rect: SurfaceDetailUVRect | None = None
    wrap_policy: Literal["clamp", "repeat", "mirror"]
    ownership: Literal["surface_detail"] = "surface_detail"

    @model_validator(mode="after")
    def validate_placement(self) -> SurfaceDetailRequirement:
        """Require unique channels and an exact mask or bounded UV placement."""

        if len(self.requested_channels) != len(set(self.requested_channels)):
            raise ValueError("surface-detail requested channels must be unique")
        if self.mask is None and self.uv_rect is None:
            raise ValueError("surface detail requires a mask or UV rectangle")
        return self


class SurfaceDetailMaterialBinding(MaterialClosureStrictModel):
    """Expose the candidate mapping facts used by deterministic surface preflight."""

    detail_id: PortableId
    object_id: PortableId
    material_id: PortableId
    strategy: Literal["none", "procedural", "image", "hybrid"]
    mapping: Literal["uv", "generated", "object", "triplanar"]
    uv_set: Literal["UVMap"] | None = None
    uv_layout_fingerprint: Sha256 | None = None
    available_channels: list[Literal[
        "base_color", "roughness", "metallic", "normal", "height", "opacity", "emission"
    ]] = Field(default_factory=list)
    coverage_ids: list[PortableId] = Field(default_factory=list)
    mask_paths: list[RelativePath] = Field(default_factory=list)
    detail_owned_by_geometry: bool = False


class SurfaceDetailPreflightResult(MaterialClosureStrictModel):
    """Summarize deterministic surface-detail, UV, channel, and ownership checks."""

    status: ClosureStatus
    checked_detail_ids: list[PortableId]
    issues: list[MaterialClosureIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status(self) -> SurfaceDetailPreflightResult:
        """Require the result status to agree with its fail-closed issue list."""

        if self.status == "passed" and self.issues:
            raise ValueError("passed surface-detail preflight cannot contain issues")
        if self.status == "failed" and not self.issues:
            raise ValueError("failed surface-detail preflight requires an issue")
        return self


class MaterialPreflightCheck(MaterialClosureStrictModel):
    """Record one named material preflight or shadow-compile check."""

    check_id: Token
    category: Literal["contract", "dependency", "surface_detail", "budget", "rollback", "blender"]
    status: Literal["passed", "failed", "not_applicable"]
    message: str = Field(min_length=1, max_length=2000)
    evidence: list[ExactArtifact] = Field(default_factory=list)


class MaterialResourceCounters(MaterialClosureStrictModel):
    """Keep bounded material-resource limits and consumption in separate categories."""

    preflight_blender_runs: int = Field(ge=0)
    controller_invocations: int = Field(ge=0)
    canonical_promotions: int = Field(ge=0)
    appearance_revisions: int = Field(ge=0)
    transient_controller_retries: int = Field(default=0, ge=0)

    def subtract(self, other: MaterialResourceCounters) -> MaterialResourceCounters:
        """Return non-negative component-wise remaining capacity."""

        payload = {
            name: getattr(self, name) - getattr(other, name)
            for name in type(self).model_fields
        }
        if any(value < 0 for value in payload.values()):
            raise ValueError("resource consumption exceeds its declared limit")
        return MaterialResourceCounters.model_validate(payload)


class MaterialAQBudgetObservation(MaterialClosureStrictModel):
    """Record exact existing AQ v2 usage and immutable category limits at failure."""

    schema_version: Literal[MATERIAL_CLOSURE_SCHEMA_VERSION] = (
        MATERIAL_CLOSURE_SCHEMA_VERSION
    )
    blender_builds_used: int = Field(ge=0)
    blender_builds_limit: int = Field(ge=0)
    controller_invocations_used: int = Field(ge=0)
    controller_invocations_limit: int = Field(ge=0)
    canonical_promotions_used: int = Field(ge=0)
    canonical_promotions_limit: int = Field(ge=0)
    actions_used: int = Field(ge=0)
    actions_limit: int = Field(ge=0)
    quality_evaluations_used: int = Field(ge=0)
    quality_evaluations_limit: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_observed_capacity(self) -> MaterialAQBudgetObservation:
        """Reject an observation whose consumption exceeds any exact AQ budget limit."""

        for category in (
            "blender_builds",
            "controller_invocations",
            "canonical_promotions",
            "actions",
            "quality_evaluations",
        ):
            if getattr(self, f"{category}_used") > getattr(self, f"{category}_limit"):
                raise ValueError(f"AQ {category} usage exceeds its immutable limit")
        return self


class MaterialPreflightBudget(MaterialClosureBoundContract):
    """Separate finite preflight resources from controller, promotion, and art budgets."""

    budget_id: PortableId
    limits: MaterialResourceCounters
    consumed: MaterialResourceCounters
    hard_upper_bound: Literal[True] = True
    automatic_expansion_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_capacity(self) -> MaterialPreflightBudget:
        """Reject any category whose usage already exceeds its immutable limit."""

        self.limits.subtract(self.consumed)
        return self

    def remaining(self) -> MaterialResourceCounters:
        """Return exact remaining capacity without mutating the budget contract."""

        return self.limits.subtract(self.consumed)


class MaterialFrameworkFailureContext(MaterialClosureStrictModel):
    """Carry complete workflow-neutral state needed for strict preflight failure evidence."""

    state_sequence: int = Field(ge=0)
    current_state: ExactArtifact
    canonical_snapshot: MaterialCanonicalSnapshot
    latest_successful_rollback_receipt: ExactArtifact | None = None
    pending_retry_plan: ExactArtifact | None = None
    pending_retry_approval: ExactArtifact | None = None
    controller_execution_count: int = Field(ge=0)
    rollback_count: int = Field(ge=0)
    budget_usage: MaterialResourceCounters
    aq_budget_observation: MaterialAQBudgetObservation
    neutral_preview_present: bool
    material_phase_receipt_present: bool
    integrated_quality_entered: bool
    existing_retry_execution_forbidden: Literal[True] = True


class MaterialPreflightResourceReceipt(MaterialClosureBoundContract):
    """Record one executed or cache-adopted preflight resource accounting event."""

    receipt_id: PortableId
    budget: ExactArtifact
    closure_sha256: Sha256
    preflight_input_sha256: Sha256
    action: Literal["executed", "cache_adopted"]
    before: MaterialResourceCounters
    consumed_by_event: MaterialResourceCounters
    after: MaterialResourceCounters
    cache_source: ExactArtifact | None = None
    cache_hash_reverified: bool

    @model_validator(mode="after")
    def validate_accounting(self) -> MaterialPreflightResourceReceipt:
        """Require exact category accounting and verified zero-cost cache adoption."""

        expected = {
            name: getattr(self.before, name) + getattr(self.consumed_by_event, name)
            for name in type(self.before).model_fields
        }
        if self.after.model_dump() != expected:
            raise ValueError("preflight resource receipt counters do not add up")
        if self.action == "cache_adopted":
            if self.cache_source is None or not self.cache_hash_reverified:
                raise ValueError("cache adoption requires a reverified exact source")
            if any(self.consumed_by_event.model_dump().values()):
                raise ValueError("cache adoption must not consume a second resource")
        elif self.cache_source is not None:
            raise ValueError("executed preflight cannot declare a cache source")
        return self


class MaterialPromotionPreflightRequest(MaterialClosureBoundContract):
    """Bind every candidate, closure, rebound graph, budget, and baseline before review."""

    request_id: PortableId
    closure: ExactArtifact
    closure_receipt: ExactArtifact
    graph_rebinding_receipt: ExactArtifact
    candidate_material_plan: ExactArtifact
    rebound_material_graph: ExactArtifact
    canonical_snapshot: ExactArtifact
    budget: ExactArtifact
    framework_failure_context: MaterialFrameworkFailureContext
    uv_layout_fingerprint: Sha256
    surface_details: list[SurfaceDetailRequirement] = Field(default_factory=list)
    surface_bindings: list[SurfaceDetailMaterialBinding] = Field(default_factory=list)
    planned_output_projection: dict[RelativePath, Sha256] = Field(min_length=2)
    approval_may_be_requested: Literal[False] = False
    controller_may_execute: Literal[False] = False
    canonical_write_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_failure_context(self) -> MaterialPromotionPreflightRequest:
        """Bind complete failure context to the same exact workflow and session."""

        context = self.framework_failure_context
        snapshot = context.canonical_snapshot
        if (
            snapshot.job_id,
            snapshot.workflow_id,
            snapshot.dispatch_id,
            snapshot.session_id,
        ) != (self.job_id, self.workflow_id, self.dispatch_id, self.session_id):
            raise ValueError("inline failure context belongs to another workflow session")
        detail_fingerprints = {
            detail.uv_layout_fingerprint for detail in self.surface_details
        }
        binding_fingerprints = {
            binding.uv_layout_fingerprint
            for binding in self.surface_bindings
            if binding.uv_layout_fingerprint is not None
        }
        if any(
            fingerprint != self.uv_layout_fingerprint
            for fingerprint in detail_fingerprints | binding_fingerprints
        ):
            raise ValueError(
                "surface-detail UV fingerprints differ from the canonical preflight value"
            )
        return self


class MaterialShadowCompileReceipt(MaterialClosureBoundContract):
    """Attest an isolated Blender material compile without canonical mutation."""

    receipt_id: PortableId
    preflight_request: ExactArtifact
    closure: ExactArtifact
    status: ClosureStatus
    blender_version: str | None = Field(default=None, max_length=64)
    blender_executable_sha256: Sha256 | None = None
    shadow_root: RelativePath
    checks: list[MaterialPreflightCheck] = Field(min_length=1)
    outputs: list[ExactArtifact] = Field(default_factory=list)
    canonical_unchanged: Literal[True] = True
    issues: list[MaterialClosureIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shadow_result(self) -> MaterialShadowCompileReceipt:
        """Keep Blender identity, check outcomes, outputs, and status mutually consistent."""

        has_failed_check = any(item.status == "failed" for item in self.checks)
        if self.status == "passed":
            if self.blender_version != "5.0.1" or self.blender_executable_sha256 is None:
                raise ValueError("passed shadow compile requires exact Blender 5.0.1 identity")
            if has_failed_check or self.issues:
                raise ValueError("passed shadow compile cannot contain failures")
            if not self.outputs:
                raise ValueError("passed shadow compile requires output evidence")
        elif not has_failed_check and not self.issues:
            raise ValueError("failed shadow compile requires a failed check or issue")
        return self


class MaterialNeutralPreviewManifest(MaterialClosureBoundContract):
    """Bind the neutral review image to the exact preflight-approved candidate."""

    manifest_id: PortableId
    closure: ExactArtifact
    preflight_request: ExactArtifact
    shadow_compile_receipt: ExactArtifact
    candidate_material_plan: ExactArtifact
    rebound_material_graph: ExactArtifact
    preview_image: ExactArtifact
    camera_id: PortableId
    lighting_profile_id: PortableId
    color_management_fingerprint: Sha256
    reference_matched_preview: ExactArtifact | None = None


class MaterialPromotionPreflightReport(MaterialClosureBoundContract):
    """Prove that every approval prerequisite passed for one immutable candidate."""

    report_id: PortableId
    request: ExactArtifact
    closure: ExactArtifact
    closure_receipt: ExactArtifact
    graph_rebinding_receipt: ExactArtifact
    shadow_compile_receipt: ExactArtifact
    neutral_preview_manifest: ExactArtifact
    resource_receipt: ExactArtifact
    status: Literal["passed"] = "passed"
    checks: list[MaterialPreflightCheck] = Field(min_length=1)
    immutable_input_projection: dict[RelativePath, Sha256] = Field(min_length=1)
    planned_output_projection: dict[RelativePath, Sha256] = Field(min_length=2)
    canonical_unchanged: Literal[True] = True
    approval_may_be_requested: Literal[True] = True
    controller_may_execute: Literal[False] = False

    @model_validator(mode="after")
    def validate_pass(self) -> MaterialPromotionPreflightReport:
        """Reject a passed report containing any failed prerequisite check."""

        if any(item.status == "failed" for item in self.checks):
            raise ValueError("passed preflight report cannot contain failed checks")
        return self


class MaterialPromotionPreflightFailure(MaterialClosureBoundContract):
    """Stop before approval, controller execution, budgets, or canonical side effects."""

    failure_id: PortableId
    request: ExactArtifact
    closure: ExactArtifact | None = None
    status: Literal["failed"] = "failed"
    issues: list[MaterialClosureIssue] = Field(min_length=1)
    framework_failure_report_path: RelativePath
    recommendations: list[str] = Field(min_length=1)
    approval_created: Literal[False] = False
    technical_retry_approval_created: Literal[False] = False
    controller_invocations_consumed: Literal[0] = 0
    canonical_promotions_consumed: Literal[0] = 0
    appearance_revisions_consumed: Literal[0] = 0
    canonical_write_performed: Literal[False] = False


class MaterialChange(MaterialClosureStrictModel):
    """Describe one exact material repair or candidate change for approval policy."""

    change_id: PortableId
    category: Literal[
        "path_only_rebinding",
        "hash_map_reconstruction",
        "manifest_ordering",
        "closure_collection",
        "deterministic_serialization",
        "receipt_regeneration",
        "base_color",
        "roughness_metallic",
        "normal_height",
        "texture_bytes",
        "uv_placement",
        "shader_parameter",
        "material_assignment",
        "new_object_material",
        "reference_replacement",
        "target_subject",
        "content_scope",
        "imagegen_scope_expansion",
    ]
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 | None = None
    description: str = Field(min_length=1, max_length=1000)


class MaterialApprovalImpactReport(MaterialClosureBoundContract):
    """Classify changes by visual or scope impact without inventing user authority."""

    report_id: PortableId
    changes: list[MaterialChange] = Field(min_length=1)
    impact: ApprovalImpact
    user_approval_required: bool
    required_approval: Literal["none", "material_appearance_promotion", "root_scope"]
    reasons: list[str] = Field(min_length=1)
    prior_approval_reusable: bool

    @model_validator(mode="after")
    def validate_policy(self) -> MaterialApprovalImpactReport:
        """Require approval flags to match the classified impact exactly."""

        expected = {
            "no_visual_change": (False, "none"),
            "appearance_change": (True, "material_appearance_promotion"),
            "scope_change": (True, "root_scope"),
        }[self.impact]
        if (self.user_approval_required, self.required_approval) != expected:
            raise ValueError("approval requirement does not match material impact")
        if self.prior_approval_reusable != (self.impact == "no_visual_change"):
            raise ValueError("only no-visual-change repairs may reuse prior approval")
        return self


class MaterialAppearanceApproval(MaterialClosureBoundContract):
    """Record one explicit user decision over exact candidate and preview bytes."""

    approval_id: PortableId
    decision: Literal["approved", "rejected"]
    approved_by: Literal["user"] = "user"
    scope: Literal["material_appearance_promotion"] = "material_appearance_promotion"
    candidate_material_plan_sha256: Sha256
    rebound_material_graph_sha256: Sha256
    closure_sha256: Sha256
    preflight_report_sha256: Sha256
    neutral_preview_sha256: Sha256
    canonical_scene_spec_sha256: Sha256
    canonical_blend_sha256: Sha256
    uv_layout_fingerprint: Sha256
    known_limitations: list[str] = Field(default_factory=list)


class MaterialAppearanceApprovalConsumptionReceipt(MaterialClosureBoundContract):
    """Consume one exact material approval once without mutating its historical bytes."""

    receipt_id: PortableId
    approval: ExactArtifact
    controller_request: ExactArtifact
    approval_id: PortableId
    candidate_material_plan_sha256: Sha256
    rebound_material_graph_sha256: Sha256
    closure_sha256: Sha256
    preflight_report_sha256: Sha256
    neutral_preview_sha256: Sha256
    consumption_ordinal: Literal[1] = 1
    consumed_once: Literal[True] = True
    approval_artifact_unchanged: Literal[True] = True
    canonical_write_authority: Literal["host_promotion_only"] = "host_promotion_only"


def material_plan_absence_context_sha256(
    *,
    absence_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    observation_state: ExactArtifact,
    canonical_scene_spec: ExactArtifact,
    canonical_blend: ExactArtifact,
    filesystem_parent_fingerprint: str,
) -> str:
    """Digest every exact fact that gives one canonical MaterialPlan absence meaning."""

    payload = {
        "schema_version": MATERIAL_CLOSURE_SCHEMA_VERSION,
        "absence_id": absence_id,
        "canonical_path": "analysis/material_plan.json",
        "observed_absent": True,
        "job_id": job_id,
        "workflow_id": workflow_id,
        "dispatch_id": dispatch_id,
        "session_id": session_id,
        "observation_state": observation_state.model_dump(mode="json"),
        "canonical_scene_spec": canonical_scene_spec.model_dump(mode="json"),
        "canonical_blend": canonical_blend.model_dump(mode="json"),
        "filesystem_parent_fingerprint": filesystem_parent_fingerprint,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MaterialCanonicalMaterialPlanAbsence(MaterialClosureBoundContract):
    """Record a generic hash-bound observation that canonical MaterialPlan is absent."""

    absence_id: PortableId
    canonical_path: Literal["analysis/material_plan.json"] = "analysis/material_plan.json"
    observed_absent: Literal[True] = True
    observation_state: ExactArtifact
    observation_context_sha256: Sha256
    canonical_scene_spec: ExactArtifact
    canonical_blend: ExactArtifact
    filesystem_parent_fingerprint: Sha256

    @model_validator(mode="after")
    def validate_observation_context(self) -> MaterialCanonicalMaterialPlanAbsence:
        """Require canonical bindings and a deterministic digest of the absence context."""

        for label, artifact, expected_path, expected_kind in (
            (
                "SceneSpec",
                self.canonical_scene_spec,
                "analysis/scene_spec.json",
                "scene_spec",
            ),
            (
                "Blend",
                self.canonical_blend,
                "blender/scene.blend",
                "canonical_blend",
            ),
        ):
            if artifact.path != expected_path or artifact.kind != expected_kind:
                raise ValueError(
                    f"MaterialPlan absence requires canonical {label} path and kind"
                )
        expected = material_plan_absence_context_sha256(
            absence_id=self.absence_id,
            job_id=self.job_id,
            workflow_id=self.workflow_id,
            dispatch_id=self.dispatch_id,
            session_id=self.session_id,
            observation_state=self.observation_state,
            canonical_scene_spec=self.canonical_scene_spec,
            canonical_blend=self.canonical_blend,
            filesystem_parent_fingerprint=self.filesystem_parent_fingerprint,
        )
        if self.observation_context_sha256 != expected:
            raise ValueError("MaterialPlan absence observation context digest is inconsistent")
        return self


class MaterialCanonicalSnapshot(MaterialClosureBoundContract):
    """Capture the exact canonical material baseline and latest lifecycle evidence."""

    snapshot_id: PortableId
    scene_spec: ExactArtifact
    modeling_plan: ExactArtifact
    material_plan: ExactArtifact | None = None
    material_plan_absence: ExactArtifact | None = None
    blend: ExactArtifact
    build_provenance: ExactArtifact
    # Historical field name: this is the exact provenance JSON artifact SHA-256,
    # while the payload's embedded build-input fingerprint remains internal evidence.
    build_provenance_fingerprint: Sha256
    latest_material_promotion_receipt: ExactArtifact | None = None
    latest_rollback_receipt: ExactArtifact | None = None
    active_candidate_closure: ExactArtifact | None = None

    @model_validator(mode="after")
    def validate_material_baseline(self) -> MaterialCanonicalSnapshot:
        """Require exactly one canonical MaterialPlan artifact or explicit absence record."""

        for label, artifact, expected_path, expected_kind in (
            (
                "SceneSpec",
                self.scene_spec,
                "analysis/scene_spec.json",
                "scene_spec",
            ),
            (
                "ModelingPlan",
                self.modeling_plan,
                "analysis/modeling_plan.json",
                "modeling_plan",
            ),
            (
                "Blend",
                self.blend,
                "blender/scene.blend",
                "canonical_blend",
            ),
        ):
            if artifact.path != expected_path or artifact.kind != expected_kind:
                raise ValueError(
                    f"snapshot requires canonical {label} path and kind"
                )
        if (self.material_plan is None) == (self.material_plan_absence is None):
            raise ValueError("snapshot requires MaterialPlan bytes or exact absence evidence")
        if (
            self.material_plan_absence is not None
            and self.material_plan_absence.kind != "material_plan_absence"
        ):
            raise ValueError("snapshot MaterialPlan absence must use the strict artifact kind")
        if (
            self.build_provenance.kind != "build_provenance"
            or self.build_provenance_fingerprint != self.build_provenance.sha256
        ):
            raise ValueError("snapshot build provenance exact artifact is inconsistent")
        return self


class MaterialAttemptState(MaterialClosureBoundContract):
    """Track one additive material attempt against an embedded canonical snapshot."""

    attempt_id: PortableId
    sequence: int = Field(ge=0)
    state: MaterialAttemptStatus
    canonical_snapshot: MaterialCanonicalSnapshot
    active_closure: ExactArtifact | None = None
    latest_preflight: ExactArtifact | None = None
    pending_approval: ExactArtifact | None = None
    latest_controller_result: ExactArtifact | None = None
    latest_promotion_receipt: ExactArtifact | None = None
    latest_rollback_receipt: ExactArtifact | None = None
    retry_required: bool
    retry_allowed: bool
    blocked_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_state(self) -> MaterialAttemptState:
        """Prevent terminal/rollback states from exposing a stale active candidate."""

        binding = (
            self.job_id,
            self.workflow_id,
            self.dispatch_id,
            self.session_id,
        )
        snapshot_binding = (
            self.canonical_snapshot.job_id,
            self.canonical_snapshot.workflow_id,
            self.canonical_snapshot.dispatch_id,
            self.canonical_snapshot.session_id,
        )
        if binding != snapshot_binding:
            raise ValueError("attempt and canonical snapshot bindings must match")
        if self.state == "rollback_completed":
            if self.active_closure is not None:
                raise ValueError("completed rollback cannot retain an active closure")
            if self.latest_rollback_receipt is None:
                raise ValueError("completed rollback requires its exact receipt")
            if not self.retry_required and self.blocked_reason is None:
                raise ValueError("completed rollback must require retry or report blocking")
        if self.state in {"blocked", "cancelled"} and self.active_closure is not None:
            raise ValueError("terminal material attempt cannot retain an active closure")
        if self.state == "blocked" and self.blocked_reason is None:
            raise ValueError("blocked material attempt requires a reason")
        if self.retry_allowed and not self.retry_required:
            raise ValueError("retry cannot be allowed unless it is required")
        return self


class MaterialStateDifference(MaterialClosureStrictModel):
    """Describe one exact mismatch between attempt state and observed canonical state."""

    field: str = Field(min_length=1, max_length=256)
    expected: str | int | bool | None
    observed: str | int | bool | None
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")


class MaterialStateConsistencyReport(MaterialClosureBoundContract):
    """Compare an attempt snapshot to freshly observed canonical bytes."""

    report_id: PortableId
    attempt_state: ExactArtifact
    top_level_state: ExactArtifact
    expected_snapshot: ExactArtifact
    observed_snapshot: MaterialCanonicalSnapshot
    consistent: bool
    differences: list[MaterialStateDifference] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_consistency(self) -> MaterialStateConsistencyReport:
        """Require the consistency flag to equal the absence of differences."""

        if self.consistent != (not self.differences):
            raise ValueError("state consistency flag does not match differences")
        return self


class AQV2StatusProjection(MaterialClosureBoundContract):
    """Present raw AQ and companion material/canonical state without hiding mismatch."""

    projection_id: PortableId
    top_level_state: ExactArtifact
    top_level_phase: str = Field(min_length=1, max_length=64)
    top_level_status: str = Field(min_length=1, max_length=64)
    top_level_next_action: str = Field(min_length=1, max_length=96)
    material_attempt: ExactArtifact | None = None
    material_attempt_state: MaterialAttemptStatus | None = None
    canonical_snapshot: MaterialCanonicalSnapshot
    active_closure: ExactArtifact | None = None
    latest_preflight: ExactArtifact | None = None
    pending_approval: ExactArtifact | None = None
    latest_controller_result: ExactArtifact | None = None
    latest_promotion_receipt: ExactArtifact | None = None
    latest_rollback_receipt: ExactArtifact | None = None
    blocked_retry: ExactArtifact | None = None
    retry_supersession_receipt: ExactArtifact | None = None
    controller_invocation_count: int = Field(ge=0)
    canonical_promotion_count: int = Field(ge=0)
    rollback_count: int = Field(ge=0)
    consistency_report: ExactArtifact
    state_consistent: bool
    combined_status: Literal[
        "current",
        "approval_pending",
        "review_required",
        "completed",
        "partial",
        "failed",
        "blocked",
        "cancelled",
        "inconsistent",
    ]


class MaterialFrameworkFailureReport(MaterialClosureBoundContract):
    """Separate framework wiring failure from asset-quality judgment and stop execution."""

    report_id: PortableId
    state_sequence: int = Field(ge=0)
    current_state: ExactArtifact
    canonical_snapshot: MaterialCanonicalSnapshot
    latest_successful_rollback_receipt: ExactArtifact | None = None
    pending_retry_plan: ExactArtifact | None = None
    pending_retry_approval: ExactArtifact | None = None
    controller_execution_count: int = Field(ge=0)
    rollback_count: int = Field(ge=0)
    budget_usage: MaterialResourceCounters
    aq_budget_observation: MaterialAQBudgetObservation
    neutral_preview_present: bool
    material_phase_receipt_present: bool
    integrated_quality_entered: bool
    failure_categories: list[Token] = Field(min_length=1)
    missing_or_invalid_dependencies: list[MaterialClosureIssue] = Field(min_length=1)
    framework_failure: Literal[True] = True
    asset_quality_failure: Literal[False, "unknown"]
    recommended_action: str = Field(min_length=1, max_length=2000)
    existing_retry_execution_forbidden: Literal[True] = True
    retry_forbidden_reason: str = Field(min_length=1, max_length=2000)


class IncidentStateDiscrepancy(MaterialClosureStrictModel):
    """Record one non-destructive difference between reported and observed incident state."""

    field: str = Field(min_length=1, max_length=256)
    reported_value: str | int | bool | None
    observed_value: str | int | bool | None
    observed_evidence: ExactArtifact | None = None
    significance: Literal["informational", "material", "blocking"]


class IncidentStateDiscrepancyReport(MaterialClosureBoundContract):
    """Preserve reported incident facts while selecting only hash-verified current state."""

    report_id: PortableId
    reported_state_source: ExactArtifact | None = None
    observed_state: ExactArtifact
    discrepancies: list[IncidentStateDiscrepancy] = Field(min_length=1)
    historical_evidence_unchanged: Literal[True] = True
    pending_retry_executed: Literal[False] = False
    basis: Literal["latest_hash_verified_observation"] = "latest_hash_verified_observation"
    has_blocking_discrepancy: bool

    @model_validator(mode="after")
    def validate_summary(self) -> IncidentStateDiscrepancyReport:
        """Require the blocking summary to reflect all observed discrepancies."""

        expected = any(item.significance == "blocking" for item in self.discrepancies)
        if self.has_blocking_discrepancy != expected:
            raise ValueError("discrepancy blocking summary is inconsistent")
        return self


class MaterialRetrySupersessionReceipt(MaterialClosureBoundContract):
    """Preserve an old retry and approval while making that exact retry non-executable."""

    receipt_id: PortableId
    retry_plan: ExactArtifact
    retry_approval: ExactArtifact | None = None
    retry_approval_absence: ExactArtifact | None = None
    current_state: ExactArtifact
    framework_failure_report: ExactArtifact
    supersession_reason: str = Field(min_length=1, max_length=2000)
    executable: Literal[False] = False
    superseded_by_framework_stabilization: Literal[True] = True
    existing_approval_remains_historical: Literal[True] = True

    @model_validator(mode="after")
    def validate_approval_state(self) -> MaterialRetrySupersessionReceipt:
        """Preserve either exact approval bytes or exact evidence that none existed."""

        if (self.retry_approval is None) == (self.retry_approval_absence is None):
            raise ValueError(
                "retry supersession requires approval bytes or explicit absence evidence"
            )
        return self


class MaterialRetryApprovalAbsence(MaterialClosureBoundContract):
    """Bind an exact observation that a particular retry never received approval."""

    absence_id: PortableId
    retry_plan: ExactArtifact
    expected_approval_path: RelativePath
    observed_absent: Literal[True] = True
    observation_state: ExactArtifact
    observation_context_sha256: Sha256

    @model_validator(mode="after")
    def validate_path_distinction(self) -> MaterialRetryApprovalAbsence:
        """Require the expected approval path to differ from the retry plan itself."""

        if self.expected_approval_path == self.retry_plan.path:
            raise ValueError("retry approval path cannot alias the retry plan")
        return self


class MaterialRollbackRestorationObservation(MaterialClosureBoundContract):
    """Bind a historical successful rollback to exact current canonical geometry bytes."""

    observation_id: PortableId
    source_session_id: PortableId
    source_rollback_receipt: ExactArtifact
    geometry_validation_receipt: ExactArtifact
    restored_scene_spec_archive: ExactArtifact
    restored_modeling_plan_archive: ExactArtifact
    restored_blend_archive: ExactArtifact
    current_scene_spec: ExactArtifact
    current_modeling_plan: ExactArtifact
    current_blend: ExactArtifact
    source_receipt_status: Literal["rolled_back"] = "rolled_back"
    status: Literal["passed"] = "passed"
    canonical_restored: Literal[True] = True
    geometry_semantics_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def validate_exact_restoration(self) -> MaterialRollbackRestorationObservation:
        """Require archived rollback bytes to equal every current canonical geometry root."""

        if self.source_session_id == self.session_id:
            raise ValueError("rollback restoration observation requires a new repair session")
        pairs = (
            (self.restored_scene_spec_archive, self.current_scene_spec),
            (self.restored_modeling_plan_archive, self.current_modeling_plan),
            (self.restored_blend_archive, self.current_blend),
        )
        if any(
            (archive.sha256, archive.byte_size)
            != (current.sha256, current.byte_size)
            for archive, current in pairs
        ):
            raise ValueError("rollback archive bytes differ from current canonical geometry")
        if self.current_scene_spec.path != "analysis/scene_spec.json":
            raise ValueError("rollback observation must bind canonical SceneSpec")
        if self.current_modeling_plan.path != "analysis/modeling_plan.json":
            raise ValueError("rollback observation must bind canonical ModelingPlan")
        if self.current_blend.path != "blender/scene.blend":
            raise ValueError("rollback observation must bind canonical Blender scene")
        return self


class MaterialRepairSourceBinding(MaterialClosureBoundContract):
    """Bind a new material-only repair to exact reusable geometry and source evidence."""

    binding_id: PortableId
    source_session_id: PortableId
    scene_spec: ExactArtifact
    modeling_plan: ExactArtifact
    blend: ExactArtifact
    geometry_approval_or_validation: ExactArtifact
    latest_successful_rollback_receipt: ExactArtifact | None = None
    material_plan: ExactArtifact | None = None
    material_plan_absence: ExactArtifact | None = None
    primary_reference: ExactArtifact
    uv_layout_fingerprint: Sha256
    target_subject: str = Field(min_length=1, max_length=500)
    content_scope_sha256: Sha256
    framework_failure_report: ExactArtifact
    reusable_imagegen_evidence: list[ExactArtifact] = Field(default_factory=list)
    geometry_reuse_only: Literal[True] = True

    @model_validator(mode="after")
    def validate_material_source(self) -> MaterialRepairSourceBinding:
        """Require exactly one current canonical MaterialPlan state for repair."""

        if (self.material_plan is None) == (self.material_plan_absence is None):
            raise ValueError("repair source requires MaterialPlan bytes or absence evidence")
        if (
            self.material_plan_absence is not None
            and self.material_plan_absence.kind != "material_plan_absence"
        ):
            raise ValueError("repair source absence must use the strict artifact kind")
        if self.source_session_id == self.session_id:
            raise ValueError("material repair must use a new session")
        if (
            self.latest_successful_rollback_receipt is not None
            and self.latest_successful_rollback_receipt.kind
            != "material_rollback_restoration_observation"
        ):
            raise ValueError("repair rollback must use the generic restoration observation")
        return self


class MaterialRepairSessionPlan(MaterialClosureBoundContract):
    """Plan a new material-only session without migrating or changing geometry."""

    plan_id: PortableId
    repair_attempt_id: PortableId
    source_session_id: PortableId
    source_binding: ExactArtifact
    source_binding_sha256: Sha256
    preflight_request: ExactArtifact
    geometry_reused: Literal[True] = True
    geometry_write_allowed: Literal[False] = False
    automatic_migration: Literal[False] = False
    old_session_resumable: Literal[False] = False
    run_stop_boundary: Literal["approval_pending"] = "approval_pending"
    synthetic_authority_allowed: Literal[False] = False
    synthetic_approval_allowed: Literal[False] = False
    controller_before_approval_allowed: Literal[False] = False
    canonical_write_before_approval_allowed: Literal[False] = False
    destination_write_allowed: Literal[False] = False
    required_steps: list[MaterialRepairStep] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_session(self) -> MaterialRepairSessionPlan:
        """Require a distinct session and unique ordered repair steps."""

        if self.source_session_id == self.session_id:
            raise ValueError("repair plan must create a distinct session")
        if self.source_binding_sha256 != self.source_binding.sha256:
            raise ValueError("repair plan source binding digest is inconsistent")
        if self.preflight_request.kind != "material_preflight_request":
            raise ValueError("repair plan requires an exact material preflight request")
        if tuple(self.required_steps) != MATERIAL_REPAIR_REQUIRED_STEPS:
            raise ValueError("repair plan steps must declare the exact bounded order")
        return self


class MaterialSessionSupersessionReceipt(MaterialClosureBoundContract):
    """Link a historical blocked session to a distinct material repair session plan."""

    receipt_id: PortableId
    superseded_session_id: PortableId
    superseded_state: ExactArtifact
    framework_failure_report: ExactArtifact
    repair_session_plan: ExactArtifact
    executable: Literal[False] = False
    historical_evidence_preserved: Literal[True] = True
    old_session_resumable: Literal[False] = False

    @model_validator(mode="after")
    def validate_distinct_session(self) -> MaterialSessionSupersessionReceipt:
        """Reject a supersession receipt that points back to the old session."""

        if self.superseded_session_id == self.session_id:
            raise ValueError("supersession receipt must bind the new repair session")
        return self


class JobSpecificRecoverySource(MaterialClosureStrictModel):
    """Inventory one incident-specific executable source before generic replacement."""

    path: RelativePath
    tracking_status: Literal["tracked", "untracked", "ignored"]
    sha256: Sha256
    byte_size: int = Field(ge=0)
    index_sha256: Sha256 | None = None
    index_byte_size: int | None = Field(default=None, ge=0)
    working_tree_differs_from_index: bool | None = None
    job_specific_literals: list[str] = Field(min_length=1)
    generic_capabilities: list[Token] = Field(min_length=1)
    disposition: Literal["archive_then_delete", "archive_then_move", "retain_as_evidence"]
    archive_path: RelativePath | None = None
    archive_sha256: Sha256 | None = None
    archive_byte_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_disposition(self) -> JobSpecificRecoverySource:
        """Require an immutable archive target before deletion or movement."""

        if self.disposition != "retain_as_evidence" and self.archive_path is None:
            raise ValueError("source removal or movement requires an archive path")
        if self.tracking_status == "tracked":
            if self.index_sha256 is None or self.index_byte_size is None:
                raise ValueError("tracked recovery source requires exact index bytes")
            expected_dirty = (
                self.sha256 != self.index_sha256 or self.byte_size != self.index_byte_size
            )
            if self.working_tree_differs_from_index != expected_dirty:
                raise ValueError("working-tree/index difference flag is inconsistent")
        elif any(
            value is not None
            for value in (
                self.index_sha256,
                self.index_byte_size,
                self.working_tree_differs_from_index,
            )
        ):
            raise ValueError("untracked or ignored source cannot claim index bytes")
        archived = (
            self.archive_path,
            self.archive_sha256,
            self.archive_byte_size,
        )
        if any(value is not None for value in archived) and not all(
            value is not None for value in archived
        ):
            raise ValueError("archive path, digest, and byte size must be recorded together")
        if self.disposition != "retain_as_evidence":
            if self.archive_sha256 != self.sha256 or self.archive_byte_size != self.byte_size:
                raise ValueError("archive bytes must exactly preserve working-tree source")
        return self


class JobSpecificRecoverySourceInventory(MaterialClosureBoundContract):
    """Preserve exact provenance for incident-specific executable recovery sources."""

    inventory_id: PortableId
    sources: list[JobSpecificRecoverySource] = Field(default_factory=list)
    scan_roots: list[RelativePath] = Field(min_length=1)
    scan_complete: bool
    evidence_only_after_inventory: Literal[True] = True


__all__ = [
    "AQV2StatusProjection",
    "ApprovalImpact",
    "AwareDateTime",
    "ClosureOwnership",
    "ClosureSourceKind",
    "ClosureStatus",
    "ExactArtifact",
    "IncidentStateDiscrepancy",
    "IncidentStateDiscrepancyReport",
    "JobSpecificRecoverySource",
    "JobSpecificRecoverySourceInventory",
    "MATERIAL_CLOSURE_REQUIRED_ROOT_ROLES",
    "MATERIAL_REPAIR_PREAPPROVAL_STEPS",
    "MATERIAL_REPAIR_REQUIRED_STEPS",
    "MATERIAL_CLOSURE_SCHEMA_VERSION",
    "MaterialAppearanceApproval",
    "MaterialAQBudgetObservation",
    "MaterialAppearanceApprovalConsumptionReceipt",
    "MaterialApprovalImpactReport",
    "MaterialAttemptState",
    "MaterialAttemptStatus",
    "MaterialCanonicalSnapshot",
    "MaterialCanonicalMaterialPlanAbsence",
    "MaterialChange",
    "MaterialClosureBoundContract",
    "MaterialClosureIssue",
    "MaterialClosureStrictModel",
    "MaterialClosureSourceBinding",
    "MaterialClosureSourceBindingArtifact",
    "MaterialDependencyClosure",
    "MaterialDependencyClosureReceipt",
    "MaterialDependencyEntry",
    "MaterialFrameworkFailureReport",
    "MaterialFrameworkFailureContext",
    "MaterialGraphRebindingChange",
    "MaterialGraphRebindingPlan",
    "MaterialGraphRebindingReceipt",
    "MaterialNeutralPreviewManifest",
    "MaterialPlannedOutput",
    "MaterialPreflightBudget",
    "MaterialPreflightCheck",
    "MaterialPreflightResourceReceipt",
    "MaterialPromotionPreflightFailure",
    "MaterialPromotionPreflightReport",
    "MaterialPromotionPreflightRequest",
    "MaterialRepairSessionPlan",
    "MaterialRepairStep",
    "MaterialRepairSourceBinding",
    "MaterialRollbackRestorationObservation",
    "MaterialResourceCounters",
    "MaterialRetrySupersessionReceipt",
    "MaterialRetryApprovalAbsence",
    "MaterialSessionSupersessionReceipt",
    "MaterialShadowCompileReceipt",
    "MaterialStateConsistencyReport",
    "MaterialStateDifference",
    "SurfaceDetailMaterialBinding",
    "SurfaceDetailPreflightResult",
    "SurfaceDetailRequirement",
    "SurfaceDetailUVRect",
    "Token",
    "material_plan_absence_context_sha256",
]
