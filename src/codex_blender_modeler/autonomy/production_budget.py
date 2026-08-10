"""Exact V0.8 production accounting and bounded portable-package repair contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from ..orchestration.models import WorkflowStep
from ..stabilization.models import PortableId, Sha256
from .budget import consume_budget
from .models import (
    AQStrictModel,
    AutonomyArtifact,
    AutonomyBudget,
    AutonomyEvidenceContract,
    BudgetUsage,
)

ProductionResourceKind = Literal[
    "none",
    "scene_build",
    "quality_evaluation",
    "scene_build_and_quality_evaluation",
]
PackageRepairPhase = Literal["package", "roundtrip"]
PackageRepairDisposition = Literal["repair", "review"]
PackageRepairAction = Literal[
    "rebuild_portable_material_conversion",
    "rebuild_package",
    "reexport_package",
    "rerun_clean_import_roundtrip",
]
PackageRepairOutcome = Literal["repaired", "failed", "aborted"]


class ProductionResourceDelta(AQStrictModel):
    """Describe resource counters that must be reserved before one host step."""

    total_blender_builds: int = Field(default=0, ge=0, le=2)
    total_quality_evaluations: int = Field(default=0, ge=0, le=2)
    package_repairs: int = Field(default=0, ge=0, le=1)

    def as_budget_increments(self) -> dict[str, int]:
        """Project only non-zero dimensions for the immutable budget helper."""

        return {
            name: value
            for name, value in self.model_dump().items()
            if value > 0
        }


class ProductionStepResourceClassification(AQStrictModel):
    """Map one known V0.8 host tool to its pre-execution AQ resource cost."""

    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,95}$")
    tool_name: str = Field(min_length=1, max_length=128)
    phase: str = Field(min_length=1, max_length=32)
    resource_kind: ProductionResourceKind
    delta: ProductionResourceDelta
    charge_timing: Literal["before_execution"] = "before_execution"
    rationale: str = Field(min_length=1, max_length=512)


class ProductionResourceReservation(AutonomyEvidenceContract):
    """Bind one pre-execution budget transition to an exact V0.8 host step."""

    session_id: PortableId
    workflow_plan: AutonomyArtifact
    budget_authority: AutonomyArtifact
    workflow_step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,95}$")
    workflow_tool_name: str = Field(min_length=1, max_length=128)
    workflow_input_fingerprint: Sha256
    classification: ProductionStepResourceClassification
    budget_before: BudgetUsage
    budget_after: BudgetUsage

    @model_validator(mode="after")
    def validate_exact_transition(self) -> ProductionResourceReservation:
        """Require one action plus exactly the classified resource increments."""

        before = self.budget_before.model_dump()
        after = self.budget_after.model_dump()
        expected = dict(before)
        expected["total_actions"] += 1
        for name, amount in self.classification.delta.as_budget_increments().items():
            expected[name] += amount
        if after != expected:
            raise ValueError("production resource reservation has an inexact budget transition")
        if self.workflow_step_id != self.classification.step_id:
            raise ValueError("reservation step does not match its classification")
        if self.workflow_tool_name != self.classification.tool_name:
            raise ValueError("reservation tool does not match its classification")
        return self


class ProductionReservationDecision(AQStrictModel):
    """Return either an exact reservation or a review route without consuming budget."""

    allowed: bool
    usage: BudgetUsage
    exhausted_dimension: str | None = None
    route_to_review: bool
    classification: ProductionStepResourceClassification
    reservation: ProductionResourceReservation | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> ProductionReservationDecision:
        """Keep allowed reservations and denied review routes mutually consistent."""

        if self.allowed:
            if self.reservation is None or self.exhausted_dimension is not None:
                raise ValueError("allowed production step requires one exact reservation")
            if self.route_to_review:
                raise ValueError("allowed production step cannot route to review")
        elif self.reservation is not None or not self.route_to_review:
            raise ValueError("denied production step must route to review without reservation")
        return self


class ProductionResourceReceipt(AutonomyEvidenceContract):
    """Preserve the exact attempt evidence associated with one consumed reservation."""

    session_id: PortableId
    reservation: AutonomyArtifact
    workflow_step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,95}$")
    workflow_input_fingerprint: Sha256
    host_attempt: AutonomyArtifact
    outputs: list[AutonomyArtifact] = Field(default_factory=list)
    reserved_delta: ProductionResourceDelta
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    outcome: Literal["completed", "failed", "interrupted"]
    finished_at: datetime

    @model_validator(mode="after")
    def validate_completed_outputs(self) -> ProductionResourceReceipt:
        """Require exact reserved usage and output evidence for a completed host step."""

        if self.outcome == "completed" and not self.outputs:
            raise ValueError("completed production step requires exact output artifacts")
        expected = self.budget_before.model_dump()
        expected["total_actions"] += 1
        for name, amount in self.reserved_delta.as_budget_increments().items():
            expected[name] += amount
        if self.budget_after.model_dump() != expected:
            raise ValueError("production resource receipt has an inexact budget transition")
        return self


class PackageRepairFailure(AutonomyEvidenceContract):
    """Normalize one failed package or round-trip attempt without interpreting free text."""

    session_id: PortableId
    phase: PackageRepairPhase
    error_code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    failure_evidence: AutonomyArtifact
    package_manifest: AutonomyArtifact | None = None
    roundtrip_validation: AutonomyArtifact | None = None
    deterministic: bool
    canonical_inputs_current: bool
    canonical_input_fingerprint: Sha256
    details: list[str] = Field(min_length=1)


class PackageRepairPlan(AutonomyEvidenceContract):
    """Authorize one derived-only deterministic package repair under an exact budget."""

    session_id: PortableId
    failure: AutonomyArtifact
    profile_id: PortableId
    package_id: PortableId
    repair_index: int = Field(ge=1, le=2)
    actions: list[PackageRepairAction] = Field(min_length=1, max_length=4)
    delta: ProductionResourceDelta
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    canonical_input_fingerprint: Sha256
    canonical_mutation_allowed: Literal[False] = False
    requires_clean_import_roundtrip: Literal[True] = True
    max_attempts: Literal[1] = 1

    @model_validator(mode="after")
    def validate_repair_budget(self) -> PackageRepairPlan:
        """Require exactly one repair charge and the declared build/quality increments."""

        if self.delta.package_repairs != 1:
            raise ValueError("package repair plans must consume exactly one repair allowance")
        expected = self.budget_before.model_dump()
        expected["total_actions"] += 1
        for name, amount in self.delta.as_budget_increments().items():
            expected[name] += amount
        if self.budget_after.model_dump() != expected:
            raise ValueError("package repair plan has an inexact budget transition")
        if self.actions[-1] != "rerun_clean_import_roundtrip":
            raise ValueError("every package repair must end with a clean-import round trip")
        return self


class PackageRepairDecision(AQStrictModel):
    """Choose one budgeted deterministic repair or a fail-closed review route."""

    disposition: PackageRepairDisposition
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    reasons: list[str] = Field(min_length=1)
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    repair_plan: PackageRepairPlan | None = None

    @model_validator(mode="after")
    def validate_disposition(self) -> PackageRepairDecision:
        """Prevent review outcomes from carrying executable repair authority."""

        if self.disposition == "repair" and self.repair_plan is None:
            raise ValueError("repair disposition requires an exact repair plan")
        if self.disposition == "review" and self.repair_plan is not None:
            raise ValueError("review disposition cannot carry a repair plan")
        if self.disposition == "review" and self.budget_after != self.budget_before:
            raise ValueError("review routing cannot consume a package-repair budget")
        return self


class PackageRepairReceipt(AutonomyEvidenceContract):
    """Prove one bounded repair result without ever fabricating package acceptance."""

    session_id: PortableId
    repair_plan: AutonomyArtifact
    failure: AutonomyArtifact
    host_attempts: list[AutonomyArtifact] = Field(min_length=1)
    canonical_input_fingerprint_before: Sha256
    canonical_input_fingerprint_after: Sha256
    package_manifest_after: AutonomyArtifact | None = None
    roundtrip_validation_after: AutonomyArtifact | None = None
    roundtrip_package_manifest_sha256: Sha256 | None = None
    reserved_delta: ProductionResourceDelta
    budget_before: BudgetUsage
    budget_after: BudgetUsage
    outcome: PackageRepairOutcome
    roundtrip_passed: bool
    package_accepted: bool
    completed_at: datetime
    notes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_no_fake_package(self) -> PackageRepairReceipt:
        """Accept a package only with unchanged inputs and exact passed round-trip evidence."""

        if self.canonical_input_fingerprint_after != self.canonical_input_fingerprint_before:
            raise ValueError("package repair cannot change canonical input fingerprint")
        if self.reserved_delta.package_repairs != 1:
            raise ValueError("package repair receipt must consume one repair allowance")
        expected = self.budget_before.model_dump()
        expected["total_actions"] += 1
        for name, amount in self.reserved_delta.as_budget_increments().items():
            expected[name] += amount
        if self.budget_after.model_dump() != expected:
            raise ValueError("package repair receipt has an inexact budget transition")
        can_accept = (
            self.outcome == "repaired"
            and self.roundtrip_passed
            and self.package_manifest_after is not None
            and self.roundtrip_validation_after is not None
            and self.roundtrip_package_manifest_sha256
            == self.package_manifest_after.sha256
        )
        if self.package_accepted != can_accept:
            raise ValueError("package acceptance requires a repaired, round-trip-passed package")
        if self.outcome != "repaired" and self.roundtrip_passed:
            raise ValueError("failed or aborted repair cannot claim a passed round trip")
        return self


_ZERO_COST_HOST_TOOLS = frozenset(
    {
        "add_view",
        "analyze_reference",
        "apply_revision_plan",
        "author_background_exterior_scene_spec",
        "author_detailed_scene_spec",
        "author_interior_scene_spec",
        "author_material_contracts",
        "author_modeling_plan",
        "author_proxy_scene_spec",
        "author_revision_plan",
        "build_portable_package",
        "create_job",
        "evaluate_background_delivery",
        "generate_destination_handoff",
        "generate_pdf_report",
        "initialize_asset_profile",
        "initialize_interior_scope",
        "inspect_materials",
        "inspect_scene",
        "material_scaffold_candidate",
        "plan_interior_qa",
        "plan_portable_asset_optimization",
        "promote_candidate_revision",
        "promote_material_contracts",
        "render_material_swatches",
        "render_preview",
        "review_geometry_multiview",
        "run_asset_preflight",
        "run_visual_diagnostics",
        "select_validated_destination_adapter",
        "validate_interior_scope",
        "validate_material_contracts",
        "validate_material_fidelity",
        "validate_scene",
        "verify_background_preview_prerequisite",
        "verify_geometry_prerequisite",
    }
)
_BUILD_TOOLS = frozenset(
    {"build_scene", "optimize_portable_asset", "convert_portable_materials"}
)
_QUALITY_TOOLS = frozenset(
    {
        "run_geometry_multiview_review",
        "run_interior_qa",
        "run_visual_qa",
        "validate_portable_package",
    }
)
_BUILD_AND_QUALITY_TOOLS = frozenset({"evaluate_candidate_revision"})


def classify_production_step_resources(
    step: WorkflowStep,
) -> ProductionStepResourceClassification:
    """Fail closed while assigning exact pre-execution costs to a known V0.8 host step."""

    if step.execution_mode != "host" or step.tool_name is None:
        raise ValueError("production resource accounting accepts host workflow steps only")
    tool = step.tool_name
    if tool == "fit_background_exterior":
        attempts = int(step.parameters.get("max_attempts", 0))
        if attempts < 0 or attempts > 2:
            raise ValueError("background fit max_attempts must remain within zero to two")
        delta = ProductionResourceDelta(
            total_blender_builds=attempts,
            total_quality_evaluations=attempts,
        )
        kind: ProductionResourceKind = (
            "none" if attempts == 0 else "scene_build_and_quality_evaluation"
        )
        rationale = "Reserve every bounded low-resolution fit build/evaluation attempt."
    elif tool in _BUILD_TOOLS:
        delta = ProductionResourceDelta(total_blender_builds=1)
        kind = "scene_build"
        rationale = "The host tool creates or rewrites one canonical or derived Blender scene."
    elif tool in _QUALITY_TOOLS:
        delta = ProductionResourceDelta(total_quality_evaluations=1)
        kind = "quality_evaluation"
        rationale = "The host tool emits one authoritative comparison or round-trip evaluation."
    elif tool in _BUILD_AND_QUALITY_TOOLS:
        delta = ProductionResourceDelta(
            total_blender_builds=1,
            total_quality_evaluations=1,
        )
        kind = "scene_build_and_quality_evaluation"
        rationale = "The host tool builds an isolated candidate and evaluates it once."
    elif tool in _ZERO_COST_HOST_TOOLS:
        delta = ProductionResourceDelta()
        kind = "none"
        rationale = "The step is accounted as one action but not as a build or quality evaluation."
    else:
        raise ValueError(f"unclassified V0.8 host tool cannot run autonomously: {tool}")
    return ProductionStepResourceClassification(
        step_id=step.step_id,
        tool_name=tool,
        phase=step.phase,
        resource_kind=kind,
        delta=delta,
        rationale=rationale,
    )


def reserve_production_step_resources(
    *,
    step: WorkflowStep,
    budget: AutonomyBudget,
    usage: BudgetUsage,
    contract_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    input_sha256: str,
    source_fingerprint: str,
    provenance: list[AutonomyArtifact],
    workflow_plan: AutonomyArtifact,
    budget_authority: AutonomyArtifact,
    workflow_input_fingerprint: str,
    created_at: datetime,
) -> ProductionReservationDecision:
    """Reserve one action and its classified resources before invoking a V0.8 host tool."""

    classification = classify_production_step_resources(step)
    decision = consume_budget(
        budget,
        usage,
        total_actions=1,
        **classification.delta.as_budget_increments(),
    )
    if not decision.allowed:
        return ProductionReservationDecision(
            allowed=False,
            usage=usage,
            exhausted_dimension=decision.exhausted_dimension,
            route_to_review=True,
            classification=classification,
        )
    reservation = ProductionResourceReservation(
        contract_id=contract_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=input_sha256,
        source_fingerprint=source_fingerprint,
        producer="codex_blender_modeler.autonomy.production_budget",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=created_at,
        session_id=session_id,
        workflow_plan=workflow_plan,
        budget_authority=budget_authority,
        workflow_step_id=step.step_id,
        workflow_tool_name=step.tool_name,
        workflow_input_fingerprint=workflow_input_fingerprint,
        classification=classification,
        budget_before=usage,
        budget_after=decision.usage,
    )
    return ProductionReservationDecision(
        allowed=True,
        usage=decision.usage,
        route_to_review=False,
        classification=classification,
        reservation=reservation,
    )


_REPAIR_RECIPES: dict[str, tuple[tuple[PackageRepairAction, ...], ProductionResourceDelta]] = {
    "stale_portable_material_conversion": (
        (
            "rebuild_portable_material_conversion",
            "rebuild_package",
            "rerun_clean_import_roundtrip",
        ),
        ProductionResourceDelta(
            total_blender_builds=1,
            total_quality_evaluations=1,
            package_repairs=1,
        ),
    ),
    "stale_derived_package": (
        ("rebuild_package", "rerun_clean_import_roundtrip"),
        ProductionResourceDelta(total_quality_evaluations=1, package_repairs=1),
    ),
    "export_metadata_mismatch": (
        ("reexport_package", "rerun_clean_import_roundtrip"),
        ProductionResourceDelta(total_quality_evaluations=1, package_repairs=1),
    ),
    "incomplete_roundtrip_receipt": (
        ("rerun_clean_import_roundtrip",),
        ProductionResourceDelta(total_quality_evaluations=1, package_repairs=1),
    ),
}


def classify_package_repair(
    *,
    failure: PackageRepairFailure,
    budget: AutonomyBudget,
    usage: BudgetUsage,
    contract_id: str,
    profile_id: str,
    package_id: str,
    repair_index: int,
    provenance: list[AutonomyArtifact],
    created_at: datetime,
    failure_contract_artifact: AutonomyArtifact | None = None,
) -> PackageRepairDecision:
    """Allow only known deterministic derived repairs with budget reserved in advance."""

    if not failure.deterministic:
        return _review_repair_decision(
            usage,
            "non_deterministic_failure",
            "Failure is not deterministic.",
        )
    if not failure.canonical_inputs_current:
        return _review_repair_decision(
            usage,
            "stale_canonical_source",
            "Canonical inputs are stale or changed.",
        )
    recipe = _REPAIR_RECIPES.get(failure.error_code)
    if recipe is None:
        return _review_repair_decision(
            usage,
            "repair_not_whitelisted",
            "Failure is not a whitelisted derived package repair.",
        )
    actions, delta = recipe
    if failure.phase == "package" and failure.error_code == "incomplete_roundtrip_receipt":
        return _review_repair_decision(
            usage,
            "failure_phase_mismatch",
            "Round-trip receipt repair requires roundtrip-phase evidence.",
        )
    budget_decision = consume_budget(
        budget,
        usage,
        total_actions=1,
        **delta.as_budget_increments(),
    )
    if not budget_decision.allowed:
        return _review_repair_decision(
            usage,
            "package_repair_budget_exhausted",
            f"Budget dimension exhausted: {budget_decision.exhausted_dimension}.",
        )
    failure_artifact = failure_contract_artifact or AutonomyArtifact(
        path=failure.failure_evidence.path,
        sha256=failure.failure_evidence.sha256,
    )
    plan = PackageRepairPlan(
        contract_id=contract_id,
        job_id=failure.job_id,
        workflow_id=failure.workflow_id,
        dispatch_id=failure.dispatch_id,
        input_sha256=failure.input_sha256,
        source_fingerprint=failure.source_fingerprint,
        producer="codex_blender_modeler.autonomy.production_budget",
        producer_version="0.1.0",
        provenance=provenance,
        created_at=created_at,
        session_id=failure.session_id,
        failure=failure_artifact,
        profile_id=profile_id,
        package_id=package_id,
        repair_index=repair_index,
        actions=list(actions),
        delta=delta,
        budget_before=usage,
        budget_after=budget_decision.usage,
        canonical_input_fingerprint=failure.canonical_input_fingerprint,
    )
    return PackageRepairDecision(
        disposition="repair",
        reason_code="budgeted_deterministic_repair",
        reasons=["Known derived-only repair classified and budget reserved before execution."],
        budget_before=usage,
        budget_after=budget_decision.usage,
        repair_plan=plan,
    )


def _review_repair_decision(
    usage: BudgetUsage,
    reason_code: str,
    reason: str,
) -> PackageRepairDecision:
    """Create one non-consuming review route for an unsafe or unavailable repair."""

    return PackageRepairDecision(
        disposition="review",
        reason_code=reason_code,
        reasons=[reason],
        budget_before=usage,
        budget_after=usage,
    )
