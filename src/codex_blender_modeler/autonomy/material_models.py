"""Strict Autonomous Quality 0.1.0 material-round evidence contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..stabilization.models import PortableId, RelativePath, Sha256
from .models import AutonomyArtifact, AutonomyEvidenceContract

MaterialCandidateStrategy = Literal["faithful_v05", "portable_pbr_v05"]
MaterialEvidenceStatus = Literal["passed", "warning", "unscorable", "failed"]


class MaterialRoundInputSnapshot(AutonomyEvidenceContract):
    """Freeze every mutable V0.8 material-authoring input before candidate creation."""

    snapshot_id: PortableId
    session_id: PortableId
    round_id: PortableId
    round_index: int = Field(ge=1, le=3)
    candidate_limit: int = Field(ge=1, le=3)
    production_assignment: AutonomyArtifact
    workflow_plan: AutonomyArtifact
    source_authored_plan_path: RelativePath
    source_authored_plan_sha256: Sha256
    material_plan_snapshot: AutonomyArtifact
    baseline_material_plan: AutonomyArtifact | None = None
    previous_ranking: AutonomyArtifact | None = None
    scene_spec_snapshot: AutonomyArtifact
    source_dependencies: list[AutonomyArtifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_round_chain(self) -> MaterialRoundInputSnapshot:
        """Require every refinement round to bind the prior exact selected ranking."""

        if self.round_index == 1 and self.previous_ranking is not None:
            raise ValueError("first material round cannot reference a previous ranking")
        if self.round_index > 1 and (
            self.previous_ranking is None or self.baseline_material_plan is None
        ):
            raise ValueError("later material rounds require an exact prior ranking baseline")
        return self


class MaterialCandidateAssignment(AutonomyEvidenceContract):
    """Authorize one deterministic host candidate inside a session-owned directory."""

    assignment_id: PortableId
    session_id: PortableId
    round_id: PortableId
    candidate_id: PortableId
    candidate_index: int = Field(ge=1, le=3)
    strategy: MaterialCandidateStrategy
    round_input: AutonomyArtifact
    output_root: RelativePath
    required_outputs: list[RelativePath] = Field(min_length=2)
    authoring_prompt_sha256: Sha256
    canonical_write_authority: Literal["controller_only"] = "controller_only"
    deterministic_host_write: Literal[True] = True


class MaterialCandidateCompletionMarker(AutonomyEvidenceContract):
    """Bind one deterministic material candidate to its exact assignment and files."""

    completion_id: PortableId
    session_id: PortableId
    round_id: PortableId
    candidate_id: PortableId
    assignment: AutonomyArtifact
    material_plan: AutonomyArtifact
    shader_recipes: list[AutonomyArtifact] = Field(default_factory=list)
    texture_dependencies: list[AutonomyArtifact] = Field(default_factory=list)
    bundle_sha256: Sha256
    completed_by: Literal["autonomy_material_host"] = "autonomy_material_host"
    canonical_written: Literal[False] = False


class MaterialCandidateEvaluation(AutonomyEvidenceContract):
    """Record conservative validation and fidelity evidence for one material candidate."""

    evaluation_id: PortableId
    session_id: PortableId
    round_id: PortableId
    candidate_id: PortableId
    candidate_index: int = Field(ge=1, le=3)
    strategy: MaterialCandidateStrategy
    assignment: AutonomyArtifact
    completion_marker: AutonomyArtifact
    material_plan: AutonomyArtifact
    contract_validation: AutonomyArtifact
    fidelity_report: AutonomyArtifact
    contract_valid: bool
    fidelity_status: MaterialEvidenceStatus
    portable_material_coverage: float = Field(ge=0, le=1)
    change_magnitude: float = Field(ge=0)
    eligible_for_selection: bool
    ranking_reasons: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_eligibility(self) -> MaterialCandidateEvaluation:
        """Prevent failed contracts or failed fidelity evidence from becoming selectable."""

        allowed = self.contract_valid and self.fidelity_status != "failed"
        if self.eligible_for_selection != allowed:
            raise ValueError("material candidate eligibility contradicts exact evidence")
        return self


class MaterialCandidateRanking(AutonomyEvidenceContract):
    """Select one exact material candidate without claiming unavailable visual quality."""

    ranking_id: PortableId
    session_id: PortableId
    round_id: PortableId
    round_input: AutonomyArtifact
    candidate_evaluations: list[AutonomyArtifact] = Field(min_length=1, max_length=3)
    selected_evaluation: AutonomyArtifact
    selected_material_plan: AutonomyArtifact
    material_quality_status: MaterialEvidenceStatus
    selection_reasons: list[str] = Field(min_length=1)
    visual_comparison_performed: Literal[False] = False
    canonical_written: Literal[False] = False


class MaterialCandidatePromotionReceipt(AutonomyEvidenceContract):
    """Bind policy-authorized placement into the current V0.8 authored output only."""

    receipt_id: PortableId
    session_id: PortableId
    round_id: PortableId
    ranking: AutonomyArtifact
    selected_evaluation: AutonomyArtifact
    selected_material_plan: AutonomyArtifact
    policy_authorization: AutonomyArtifact
    production_assignment: AutonomyArtifact
    previous_authored_plan: AutonomyArtifact
    workflow_authored_plan_path: RelativePath
    workflow_authored_plan_sha256: Sha256
    scene_spec_sha256: Sha256
    workflow_authored_output_updated: Literal[True] = True
    canonical_material_plan_written: Literal[False] = False
    existing_v08_promotion_remains_authoritative: Literal[True] = True
