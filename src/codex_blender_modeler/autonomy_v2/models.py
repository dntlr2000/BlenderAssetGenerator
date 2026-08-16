"""Strict Autonomous Quality 0.2.0 and DeliveryProfile 0.1.0 contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

AUTONOMY_SCHEMA_VERSION = "0.2.0"
DELIVERY_SCHEMA_VERSION = "0.1.0"

DeliveryProfileId = Literal["review_only", "portable_gltf", "portable_fbx"]
DeliveryOutcome = Literal["completed", "partial", "failed", "review_only"]
QualityEvidenceId = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
]


class AQV2StrictModel(BaseModel):
    """Reject undeclared fields, coercion, and non-finite values in AQ v2 evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class AQV2Artifact(AQV2StrictModel):
    """Bind one immutable job-contained artifact to exact bytes and role."""

    artifact_id: PortableId
    kind: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)


class AQV2Evidence(AQV2StrictModel):
    """Provide mandatory identity, ownership, input, and provenance for AQ v2."""

    schema_version: Literal["0.2.0"] = AUTONOMY_SCHEMA_VERSION
    contract_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: str = Field(min_length=1, max_length=128)
    producer_version: Literal["0.2.0"] = AUTONOMY_SCHEMA_VERSION
    provenance: list[AQV2Artifact] = Field(min_length=1)
    created_at: datetime


class AutonomyProfileV2(AQV2Evidence):
    """Snapshot the parallel v2 policy without changing the verified v1 profile."""

    profile_id: Literal["autonomous_static_prop_v2"] = "autonomous_static_prop_v2"
    status: Literal["disabled_experimental", "verified_active"]
    underlying_execution_policy: Literal["standard"] = "standard"
    mode: Literal["concept"] = "concept"
    reference_content_scope: Literal["primary_object_only"] = "primary_object_only"
    allowed_asset_kinds: list[Literal["static_hard_surface", "static_prop"]] = Field(
        min_length=1
    )
    allowed_delivery_profiles: list[DeliveryProfileId] = Field(min_length=1)
    controller_protocol_version: Literal["0.1.0"] = "0.1.0"
    integrated_quality_version: Literal["0.2.0"] = "0.2.0"
    prohibited_capabilities: list[str] = Field(min_length=1)
    activation_evidence: list[AQV2Artifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_activation_evidence(self) -> AutonomyProfileV2:
        """Require explicit gate evidence before the v2 profile can claim verified activation."""

        if self.status == "verified_active" and not self.activation_evidence:
            raise ValueError("verified AQ v2 profile requires activation gate evidence")
        return self


class AutonomyBudgetV2(AQV2Evidence):
    """Freeze bounded AQ v2 authoring, controller, quality, and delivery allowances."""

    budget_id: PortableId
    initial_candidates: int = Field(default=3, ge=1, le=4)
    structural_rounds: int = Field(default=2, ge=0, le=3)
    candidates_per_structural_round: int = Field(default=2, ge=1, le=3)
    parametric_convergence_iterations: int = Field(default=3, ge=0, le=5)
    material_rounds: int = Field(default=2, ge=0, le=3)
    total_blender_builds: int = Field(default=14, ge=1, le=20)
    total_quality_evaluations: int = Field(default=10, ge=1, le=16)
    controller_invocations: int = Field(default=16, ge=1, le=32)
    delivery_runs: int = Field(default=2, ge=0, le=2)
    canonical_promotions: int = Field(default=5, ge=0, le=8)
    package_repairs: int = Field(default=1, ge=0, le=2)
    global_action_limit: int = Field(default=72, ge=1, le=128)
    repeated_identical_failure_limit: Literal[1] = 1
    transient_retry_limit: Literal[1] = 1


class BudgetUsageV2(AQV2StrictModel):
    """Count consumed AQ v2 work without mutating the immutable budget."""

    initial_candidates: int = Field(default=0, ge=0)
    structural_rounds: int = Field(default=0, ge=0)
    parametric_convergence_iterations: int = Field(default=0, ge=0)
    material_rounds: int = Field(default=0, ge=0)
    total_blender_builds: int = Field(default=0, ge=0)
    total_quality_evaluations: int = Field(default=0, ge=0)
    controller_invocations: int = Field(default=0, ge=0)
    delivery_runs: int = Field(default=0, ge=0)
    canonical_promotions: int = Field(default=0, ge=0)
    package_repairs: int = Field(default=0, ge=0)
    total_actions: int = Field(default=0, ge=0)


class RootAuthorizationV2(AQV2Evidence):
    """Bind one user request to fixed v2 scope, controller profiles, and deliveries."""

    authorization_id: PortableId
    authorization_source: Literal["initial_user_request"] = "initial_user_request"
    original_request_sha256: Sha256
    primary_reference: AQV2Artifact
    profile: AQV2Artifact
    budget: AQV2Artifact
    production_launch_or_binding: AQV2Artifact
    target_subject: str = Field(min_length=1, max_length=256)
    reference_content_scope: Literal["primary_object_only"] = "primary_object_only"
    authoring_profile: Literal["standard_static_prop_v2"] = "standard_static_prop_v2"
    quality_profile: AQV2Artifact
    phase_tool_profiles: list[AQV2Artifact] = Field(min_length=1)
    allowed_delivery_profiles: list[DeliveryProfileId] = Field(min_length=1)
    requested_delivery_profiles: list[DeliveryProfileId] = Field(min_length=1)
    destination_hint: Literal[
        "engine_neutral",
        "unity_urp",
        "unity_hdrp",
        "custom_unverified",
    ] = "engine_neutral"
    destination_project_write: Literal[False] = False
    synthetic_user_approval: Literal[False] = False
    prohibited_scopes: list[str] = Field(min_length=1)
    status: Literal["active", "expired", "cancelled"] = "active"
    expires_at: datetime | None = None
    cancelled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_authorized_scope(self) -> RootAuthorizationV2:
        """Require unique requested deliveries to stay within the initial user authority."""

        if len(self.allowed_delivery_profiles) != len(set(self.allowed_delivery_profiles)):
            raise ValueError("allowed delivery profiles must be unique")
        if len(self.requested_delivery_profiles) != len(
            set(self.requested_delivery_profiles)
        ):
            raise ValueError("requested delivery profiles must be unique")
        if not set(self.requested_delivery_profiles).issubset(
            self.allowed_delivery_profiles
        ):
            raise ValueError("requested deliveries exceed root authorization")
        if "review_only" in self.requested_delivery_profiles and len(
            self.requested_delivery_profiles
        ) > 1:
            raise ValueError("review_only cannot be combined with portable delivery")
        if self.status == "cancelled" and self.cancelled_at is None:
            raise ValueError("cancelled authorization requires cancelled_at")
        if self.status != "cancelled" and self.cancelled_at is not None:
            raise ValueError("cancelled_at is valid only for cancelled authorization")
        return self


class QualityApprovedSourceFreeze(AQV2Evidence):
    """Freeze the exact quality-approved canonical authoring source before delivery."""

    freeze_id: PortableId
    scene_spec: AQV2Artifact
    authoring_blend: AQV2Artifact
    build_provenance: AQV2Artifact
    integrated_quality_report: AQV2Artifact
    quality_evidence: list[AQV2Artifact] = Field(min_length=1)
    material_plan: AQV2Artifact
    shader_recipes: list[AQV2Artifact]
    texture_manifests: list[AQV2Artifact]
    geometry_payloads: list[AQV2Artifact]
    geometry_intent_survival: AQV2Artifact
    geometry_candidate_validation_receipt: AQV2Artifact
    material_phase_receipt: AQV2Artifact
    quality_status: Literal["passed"] = "passed"
    canonical_unchanged_at_freeze: Literal[True] = True
    v07_source_fingerprint: Sha256
    frozen_source_sha256: Sha256

    @model_validator(mode="after")
    def validate_unique_frozen_sources(self) -> QualityApprovedSourceFreeze:
        """Reject duplicate paths and require every named source in exact provenance."""

        named = [
            self.scene_spec,
            self.authoring_blend,
            self.build_provenance,
            self.integrated_quality_report,
            *self.quality_evidence,
            self.material_plan,
            *self.shader_recipes,
            *self.texture_manifests,
            *self.geometry_payloads,
            self.geometry_intent_survival,
            self.geometry_candidate_validation_receipt,
            self.material_phase_receipt,
        ]
        paths = [item.path for item in named]
        if len(paths) != len(set(paths)):
            raise ValueError("quality source freeze artifacts must use unique paths")
        provenance_paths = {item.path for item in self.provenance}
        if any(item.path not in provenance_paths for item in named):
            raise ValueError("every frozen source must be included in provenance")
        return self


class DeliveryProfile(AQV2StrictModel):
    """Map one public AQ v2 delivery name to an existing engine-neutral V0.7 profile."""

    schema_version: Literal["0.1.0"] = DELIVERY_SCHEMA_VERSION
    profile_id: DeliveryProfileId
    asset_profile_id: Literal["portable_gltf", "fbx_interchange"] | None
    primary_extension: Literal[".glb", ".fbx"] | None
    direct_from_quality_freeze: Literal[True] = True
    independent_run: Literal[True] = True
    requires_exact_optimization_approval: bool
    requires_clean_import_roundtrip: bool
    destination_runtime_parity: Literal[False] = False
    canonical_authoring_mutation: Literal[False] = False
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile_mapping(self) -> DeliveryProfile:
        """Keep review-only and portable format mappings mutually consistent."""

        if self.profile_id == "review_only":
            if self.asset_profile_id is not None or self.primary_extension is not None:
                raise ValueError("review_only cannot map to a package format")
            if self.requires_exact_optimization_approval:
                raise ValueError("review_only cannot request V0.7 optimization approval")
            if self.requires_clean_import_roundtrip:
                raise ValueError("review_only cannot require a package roundtrip")
        else:
            expected = {
                "portable_gltf": ("portable_gltf", ".glb"),
                "portable_fbx": ("fbx_interchange", ".fbx"),
            }[self.profile_id]
            if (self.asset_profile_id, self.primary_extension) != expected:
                raise ValueError("portable delivery profile mapping is invalid")
            if not self.requires_exact_optimization_approval:
                raise ValueError("portable delivery requires exact V0.7 approval")
            if not self.requires_clean_import_roundtrip:
                raise ValueError("portable delivery requires clean-import roundtrip")
        return self


class DeliveryRequest(AQV2StrictModel):
    """Describe one independent delivery run sourced directly from the same freeze."""

    delivery_id: PortableId
    profile: DeliveryProfile
    source_freeze: AQV2Artifact
    run_id: PortableId | None = None
    package_id: PortableId | None = None
    status: Literal[
        "review_only",
        "planned",
        "awaiting_optimization_approval",
        "running",
        "completed",
        "failed",
    ]
    known_losses: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_delivery_identity(self) -> DeliveryRequest:
        """Require run/package IDs only for portable delivery requests."""

        if self.profile.profile_id == "review_only":
            if self.status != "review_only" or self.run_id or self.package_id:
                raise ValueError("review_only delivery cannot allocate package identities")
        elif not self.run_id or not self.package_id or self.status == "review_only":
            raise ValueError("portable delivery requires independent run and package IDs")
        return self


class DeliveryPlan(AQV2Evidence):
    """Bind all initially authorized delivery requests to one exact quality freeze."""

    plan_id: PortableId
    root_authorization: AQV2Artifact
    source_freeze: AQV2Artifact
    requests: list[DeliveryRequest] = Field(min_length=1)
    direct_cross_format_conversion: Literal[False] = False
    generic_authorization_replaces_v07_approval: Literal[False] = False
    destination_project_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_independent_requests(self) -> DeliveryPlan:
        """Require unique profiles, runs, packages, and the same exact freeze binding."""

        profile_ids = [item.profile.profile_id for item in self.requests]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("delivery plan profiles must be unique")
        runs = [item.run_id for item in self.requests if item.run_id]
        packages = [item.package_id for item in self.requests if item.package_id]
        if len(runs) != len(set(runs)) or len(packages) != len(set(packages)):
            raise ValueError("portable deliveries require independent run and package IDs")
        if any(item.source_freeze != self.source_freeze for item in self.requests):
            raise ValueError("every delivery must bind the same exact quality freeze")
        return self


class DeliveryReviewEntry(AQV2StrictModel):
    """Bind one V0.7 review boundary for an independently planned delivery format."""

    delivery_id: PortableId
    profile_id: Literal["portable_gltf", "portable_fbx"]
    asset_profile_id: Literal["portable_gltf", "fbx_interchange"]
    run_id: PortableId
    package_id: PortableId
    asset_profile: AQV2Artifact
    optimization_plan: AQV2Artifact
    optimization_review: AQV2Artifact
    exact_plan_sha256: Sha256
    next_action: Literal["request_exact_v07_optimization_approval"] = (
        "request_exact_v07_optimization_approval"
    )
    user_approval_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_plan_binding(self) -> DeliveryReviewEntry:
        """Require the public delivery name to map to the matching V0.7 profile."""

        expected = {
            "portable_gltf": "portable_gltf",
            "portable_fbx": "fbx_interchange",
        }[self.profile_id]
        if self.asset_profile_id != expected:
            raise ValueError("delivery review uses the wrong V0.7 asset profile")
        if self.exact_plan_sha256 != self.optimization_plan.sha256:
            raise ValueError("delivery review exact plan hash does not match its artifact")
        return self


class DeliveryReviewBinding(AQV2Evidence):
    """Record format-specific V0.7 review plans without synthesizing their approvals."""

    binding_id: PortableId
    delivery_plan: AQV2Artifact
    source_freeze: AQV2Artifact
    entries: list[DeliveryReviewEntry] = Field(min_length=1)
    generic_authorization_consumed_as_v07_approval: Literal[False] = False

    @model_validator(mode="after")
    def validate_review_entries(self) -> DeliveryReviewBinding:
        """Require each portable format, run, and package identity exactly once."""

        profiles = [item.profile_id for item in self.entries]
        runs = [item.run_id for item in self.entries]
        packages = [item.package_id for item in self.entries]
        if len(profiles) != len(set(profiles)):
            raise ValueError("delivery review profiles must be unique")
        if len(runs) != len(set(runs)) or len(packages) != len(set(packages)):
            raise ValueError("delivery review run and package identities must be unique")
        return self


class DeliveryResult(AQV2StrictModel):
    """Record one format-specific result without changing another delivery outcome."""

    delivery_id: PortableId
    profile_id: DeliveryProfileId
    status: Literal["completed", "failed", "review_only"]
    source_freeze_sha256: Sha256
    optimization_plan: AQV2Artifact | None = None
    optimization_approval: AQV2Artifact | None = None
    optimization_policy_authorization: AQV2Artifact | None = None
    package_manifest: AQV2Artifact | None = None
    roundtrip_validation: AQV2Artifact | None = None
    material_loss_report: AQV2Artifact | None = None
    geometry_survival_report: AQV2Artifact | None = None
    handoff_manifest: AQV2Artifact | None = None
    production_ready: bool
    known_losses: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result_evidence(self) -> DeliveryResult:
        """Require exact package evidence only for completed portable deliveries."""

        if (
            self.optimization_approval is not None
            and self.optimization_policy_authorization is not None
        ):
            raise ValueError("delivery result cannot mix user and policy authority")
        evidence = [
            self.optimization_plan,
            self.package_manifest,
            self.roundtrip_validation,
            self.material_loss_report,
            self.geometry_survival_report,
        ]
        if self.status == "review_only":
            if (
                any(item is not None for item in evidence)
                or self.optimization_approval is not None
                or self.optimization_policy_authorization is not None
                or self.production_ready
            ):
                raise ValueError("review_only result cannot claim production evidence")
        elif self.status == "completed":
            authorities = [
                self.optimization_approval,
                self.optimization_policy_authorization,
            ]
            if any(item is None for item in evidence) or sum(
                item is not None for item in authorities
            ) != 1:
                raise ValueError(
                    "completed delivery requires one exact authority, package, and validation"
                )
            if not self.production_ready or self.errors:
                raise ValueError("completed delivery must be production-ready and error-free")
        elif not self.errors or self.production_ready:
            raise ValueError("failed delivery requires errors and cannot be production-ready")
        return self


class QualityReviewActionV2(AQV2StrictModel):
    """Record one deterministic non-executing recommendation from IQ 0.2 evidence."""

    action_id: PortableId
    finding_id: QualityEvidenceId | None = None
    destination: Literal[
        "v0.4_structural_authoring",
        "v0.6_parametric_convergence",
        "v0.7_production_repair",
        "manual_evidence_review",
        "restricted_scope_required",
    ]
    reason_code: QualityEvidenceId
    target_ids: list[QualityEvidenceId] = Field(default_factory=list)
    message: str = Field(min_length=1)
    automatic_action_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_review_action(self) -> QualityReviewActionV2:
        """Keep fallback actions manual and reject duplicated semantic targets."""

        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("quality review action target IDs must be unique")
        if self.finding_id is None and self.destination != "manual_evidence_review":
            raise ValueError("finding-free quality review actions must request manual review")
        return self


class QualityReviewBundleV2(AQV2Evidence):
    """Bind one exact IQ 0.2 non-pass to reviewable, non-production evidence."""

    bundle_id: PortableId
    quality_outcome: Literal["needs_revision", "unscorable"]
    integrated_quality_report: AQV2Artifact
    candidate_blend: AQV2Artifact
    representative_render: AQV2Artifact
    recommended_actions: list[QualityReviewActionV2] = Field(min_length=1)
    review_only: Literal[True] = True
    production_ready: Literal[False] = False
    destination_handoff_eligible: Literal[False] = False
    canonical_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def validate_review_bundle(self) -> QualityReviewBundleV2:
        """Require exact named provenance, review file types, and unique recommendations."""

        named = [
            self.integrated_quality_report,
            self.candidate_blend,
            self.representative_render,
        ]
        named_bindings = {(item.path, item.sha256, item.byte_size) for item in named}
        provenance_bindings = {
            (item.path, item.sha256, item.byte_size) for item in self.provenance
        }
        if provenance_bindings != named_bindings or len(self.provenance) != len(named):
            raise ValueError("quality review bundle provenance must equal its named artifacts")
        if len(named_bindings) != len(named):
            raise ValueError("quality review bundle artifacts must be distinct")
        if not self.candidate_blend.path.casefold().endswith(".blend"):
            raise ValueError("quality review candidate must be a Blender file")
        if not self.representative_render.path.casefold().endswith(
            (".png", ".jpg", ".jpeg", ".webp")
        ):
            raise ValueError("quality review render must be PNG, JPEG, or WEBP")
        action_ids = [item.action_id for item in self.recommended_actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("quality review action IDs must be unique")
        return self


class QualityTerminalV2(AQV2Evidence):
    """End authoring quality independently from any later package-format delivery."""

    terminal_id: PortableId
    status: Literal["quality_approved", "review_required", "blocked", "failed"]
    integrated_quality_report: AQV2Artifact
    source_freeze: AQV2Artifact | None = None
    review_bundle: AQV2Artifact | None = None
    production_ready: Literal[False] = False
    reason: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_quality_terminal(self) -> QualityTerminalV2:
        """Require a source freeze only for pass and a review bundle only for non-pass."""

        if self.status == "quality_approved":
            if self.source_freeze is None or self.review_bundle is not None:
                raise ValueError("quality-approved terminal requires only a source freeze")
        else:
            if self.source_freeze is not None:
                raise ValueError("non-passing quality terminal cannot create a source freeze")
            if self.status == "review_required" and self.review_bundle is None:
                raise ValueError("review-required terminal requires an exact review bundle")
            if self.status in {"blocked", "failed"} and self.review_bundle is not None:
                raise ValueError("blocked or failed quality terminal cannot claim review delivery")
        named = [
            self.integrated_quality_report,
            *([self.source_freeze] if self.source_freeze is not None else []),
            *([self.review_bundle] if self.review_bundle is not None else []),
        ]
        provenance = {(item.path, item.sha256) for item in self.provenance}
        if any((item.path, item.sha256) not in provenance for item in named):
            raise ValueError("quality terminal must bind every named artifact in provenance")
        return self


class DeliveryTerminalV2(AQV2Evidence):
    """Summarize independent format outcomes after an immutable quality source freeze."""

    terminal_id: PortableId
    quality_terminal: AQV2Artifact
    source_freeze: AQV2Artifact
    delivery_plan: AQV2Artifact
    delivery_review: AQV2Artifact | None = None
    outcome: DeliveryOutcome
    results: list[DeliveryResult] = Field(min_length=1)
    destination_runtime_parity: Literal[False] = False
    canonical_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def validate_aggregate_outcome(self) -> DeliveryTerminalV2:
        """Derive aggregate delivery outcome without erasing format-specific failures."""

        statuses = [item.status for item in self.results]
        has_portable = any(item.profile_id != "review_only" for item in self.results)
        if has_portable and self.delivery_review is None:
            raise ValueError("portable delivery terminal requires an exact review binding")
        if not has_portable and self.delivery_review is not None:
            raise ValueError("review-only delivery terminal cannot claim a V0.7 review")
        expected: DeliveryOutcome
        if statuses == ["review_only"]:
            expected = "review_only"
        elif all(status == "completed" for status in statuses):
            expected = "completed"
        elif any(status == "completed" for status in statuses):
            expected = "partial"
        else:
            expected = "failed"
        if self.outcome != expected:
            raise ValueError("delivery terminal outcome does not match per-format results")
        named = [
            self.quality_terminal,
            self.source_freeze,
            self.delivery_plan,
            *([self.delivery_review] if self.delivery_review is not None else []),
            *[
                artifact
                for result in self.results
                for artifact in (
                    result.optimization_plan,
                    result.optimization_approval,
                    result.optimization_policy_authorization,
                    result.package_manifest,
                    result.roundtrip_validation,
                    result.material_loss_report,
                    result.geometry_survival_report,
                    result.handoff_manifest,
                )
                if artifact is not None
            ],
        ]
        provenance = {(item.path, item.sha256) for item in self.provenance}
        if any((item.path, item.sha256) not in provenance for item in named):
            raise ValueError("delivery terminal must bind every named artifact in provenance")
        return self


class AutonomyPlanV2(AQV2Evidence):
    """Bind one v2 supervisor to existing standard production and exact phase profiles."""

    plan_id: PortableId
    profile: AQV2Artifact
    root_authorization: AQV2Artifact
    budget: AQV2Artifact
    production_dispatch_plan: AQV2Artifact
    production_controller_plan: AQV2Artifact
    phase_tool_profiles: list[AQV2Artifact] = Field(min_length=1)
    requested_delivery_profiles: list[DeliveryProfileId] = Field(min_length=1)
    canonical_writer: Literal["supervisor_only"] = "supervisor_only"
    automatic_user_approval: Literal[False] = False
    action_limit: int = Field(default=64, ge=1, le=128)


class AutonomyStateV2(AQV2Evidence):
    """Represent one reconstructable v2 projection driven only by immutable events."""

    state_id: PortableId
    plan: AQV2Artifact
    sequence: int = Field(ge=0)
    phase: Literal[
        "planned",
        "reference",
        "authoring",
        "quality",
        "delivery",
        "terminal",
    ]
    status: Literal[
        "planned",
        "running",
        "waiting_for_controller",
        "quality_approved",
        "review_required",
        "delivery_pending",
        "completed",
        "partial",
        "failed",
        "blocked",
        "cancelled",
    ]
    next_action: Literal[
        "collect_reference",
        "execute_controller",
        "validate_candidate",
        "run_integrated_quality",
        "freeze_quality_source",
        "plan_delivery",
        "await_v07_approval",
        "run_delivery",
        "publish_review",
        "terminalize",
        "none",
    ]
    quality_terminal: AQV2Artifact | None = None
    source_freeze: AQV2Artifact | None = None
    delivery_plan: AQV2Artifact | None = None
    delivery_terminal: AQV2Artifact | None = None
    delivery_results: list[DeliveryResult] = Field(default_factory=list)
    budget_usage: BudgetUsageV2 = Field(default_factory=BudgetUsageV2)
    previous_state_sha256: Sha256 | None = None
    terminal_reason: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_state_boundary(self) -> AutonomyStateV2:
        """Require terminal states to carry the exact evidence for their outcome."""

        terminal = {
            "review_required",
            "completed",
            "partial",
            "failed",
            "blocked",
            "cancelled",
        }
        if self.status in terminal:
            if self.phase != "terminal" or self.next_action != "none":
                raise ValueError("terminal AQ v2 state cannot advertise another action")
            if not self.terminal_reason:
                raise ValueError("terminal AQ v2 state requires a reason")
        if self.status == "quality_approved" and self.source_freeze is None:
            raise ValueError("quality-approved state requires an exact source freeze")
        if self.status == "review_required" and self.quality_terminal is None:
            raise ValueError("review-required state requires an exact quality terminal")
        if self.status == "delivery_pending" and self.delivery_plan is None:
            raise ValueError("delivery-pending state requires an exact delivery plan")
        if self.status in {"completed", "partial"}:
            if self.delivery_terminal is None or not self.delivery_results:
                raise ValueError(
                    "completed or partial state requires an exact delivery terminal and results"
                )
        if self.delivery_terminal is not None:
            if self.status not in {"completed", "partial", "failed"}:
                raise ValueError(
                    "delivery terminal is valid only for a terminal delivery outcome"
                )
            if not self.delivery_results:
                raise ValueError("delivery terminal requires nonempty delivery results")
        if self.status == "failed" and self.delivery_results and self.delivery_terminal is None:
            raise ValueError("failed delivery results require an exact delivery terminal")
        return self


class AutonomyCancellationV2(AQV2Evidence):
    """Record one user-requested cancellation without deleting accumulated evidence."""

    cancellation_id: PortableId
    previous_state_sha256: Sha256
    reason: str = Field(min_length=1, max_length=512)
