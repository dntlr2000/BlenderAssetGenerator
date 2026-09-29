"""Strict additive contracts for disabled-experimental AQ activation readiness."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..blender_artifacts import stable_json_digest
from ..stabilization.models import PortableId, RelativePath, Sha256, V09StrictModel
from ..versioning import PROJECT_VERSION as PROJECT_VERSION

ACTIVATION_CONTRACT_VERSION = "0.1.0"
ACTIVATION_PROFILE_ID = "autonomous_static_prop_v2"
ACTIVATION_PROFILE_VERSION = "0.2.0"
# Preserve the historical default when loading a manifest that omitted this field.
LEGACY_PROJECT_VERSION = "0.9.0"
CANONICAL_SCENESPEC_VERSION = "0.2.0"

GitSha = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
CheckId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")]
ReasonCode = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")]

SourceFileRole = Literal[
    "source",
    "schema",
    "controller_promotion",
    "profile_registry",
    "dependency_lock",
    "test",
    "tooling",
    "configuration",
    "documentation",
    "verification",
    "example",
    "prompt",
    "tracked_repository_input",
]
EvidenceClassificationKind = Literal[
    "authoritative_job",
    "test_run",
    "pytest_basetemp",
    "copied_workspace",
    "local_clone",
    "shadow_job",
    "preflight_copy",
    "staging_copy",
    "recovery_copy",
    "audit_directory",
    "report_only_fixture",
    "review_bundle",
]
TerminalState = Literal[
    "completed",
    "failed",
    "blocked",
    "cancelled",
    "nonterminal",
]
CampaignTerminalClass = Literal[
    "production_delivery",
    "usable_review_terminal",
    "blocked",
    "failed",
    "cancelled",
    "nonterminal",
]


def _contract_digest(
    model: V09StrictModel,
    *,
    id_field: str,
    digest_field: str,
) -> str:
    """Hash one contract projection without its derived identifier and digest fields."""

    return stable_json_digest(
        model.model_dump(mode="json", exclude={id_field, digest_field})
    )


def _require_contract_identity(
    model: V09StrictModel,
    *,
    prefix: str,
    id_field: str,
    digest_field: str,
) -> None:
    """Require deterministic content identity for one immutable activation contract."""

    digest = _contract_digest(model, id_field=id_field, digest_field=digest_field)
    if getattr(model, digest_field) != digest:
        raise ValueError(f"{digest_field} differs from the canonical contract payload")
    if getattr(model, id_field) != f"{prefix}-{digest[:24]}":
        raise ValueError(f"{id_field} differs from the canonical contract payload")


class ActivationArtifact(V09StrictModel):
    """Bind one repository-contained activation artifact to exact immutable bytes."""

    artifact_id: PortableId
    kind: CheckId
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)


class ActivationSourceFile(V09StrictModel):
    """Bind one exact Git-blob payload used by an activation source checkpoint."""

    path: RelativePath
    role: SourceFileRole
    sha256: Sha256
    byte_size: int = Field(ge=0)
    content_source: Literal["git_blob"] = "git_blob"


class ActivationSourceExclusion(V09StrictModel):
    """Explain one runtime class that is deliberately outside source identity."""

    path_prefix: str = Field(min_length=1, max_length=256)
    reason_code: ReasonCode
    reason: str = Field(min_length=1, max_length=1000)


class ActivationCommandReceipt(V09StrictModel):
    """Bind one executed verification command to its exact result evidence."""

    receipt_id: PortableId
    command_id: CheckId
    command: list[str] = Field(min_length=1)
    status: Literal["passed", "failed", "not_applicable"]
    exit_code: int | None = None
    output_sha256: Sha256 | None = None
    output_artifact: ActivationArtifact | None = None
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_command_result(self) -> ActivationCommandReceipt:
        """Require pass/fail commands to carry a matching concrete exit code."""

        if self.status == "passed" and self.exit_code != 0:
            raise ValueError("passed command receipt requires exit_code=0")
        if self.status == "failed" and (self.exit_code is None or self.exit_code == 0):
            raise ValueError("failed command receipt requires a nonzero exit code")
        if self.status == "not_applicable" and self.exit_code is not None:
            raise ValueError("not-applicable command receipt cannot claim execution")
        if self.status != "not_applicable" and self.output_sha256 is None:
            raise ValueError("executed command receipt requires an output digest")
        if (
            self.output_artifact is not None
            and self.output_sha256 != self.output_artifact.sha256
        ):
            raise ValueError("command output digest differs from its exact artifact")
        return self


class ActivationBlenderEvidence(V09StrictModel):
    """Bind the supported Blender executable and its executed version evidence."""

    executable_path: str = Field(min_length=1, max_length=1024)
    executable_sha256: Sha256
    version: Literal["5.0.1"] = "5.0.1"
    version_command: list[str] = Field(min_length=2)
    version_output_sha256: Sha256
    version_receipt: ActivationArtifact

    @model_validator(mode="after")
    def validate_absolute_executable(self) -> ActivationBlenderEvidence:
        """Reject a relative Blender executable that cannot reproduce host evidence."""

        if not (
            self.executable_path.startswith("/")
            or re.match(r"^[A-Za-z]:[\\/]", self.executable_path)
        ):
            raise ValueError("Blender executable path must be absolute")
        if self.version_command[0] != self.executable_path:
            raise ValueError("Blender version command targets another executable")
        if "--version" not in self.version_command[1:]:
            raise ValueError("Blender version evidence must execute --version")
        if self.version_output_sha256 != self.version_receipt.sha256:
            raise ValueError("Blender version digest differs from its exact receipt")
        return self


class ActivationSourceManifest(V09StrictModel):
    """Freeze one clean Git checkpoint and every executable source dependency."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    manifest_id: PortableId
    manifest_sha256: Sha256
    project_version: Literal["0.9.0", "0.9.1"] = LEGACY_PROJECT_VERSION
    canonical_scenespec_version: Literal["0.2.0"] = CANONICAL_SCENESPEC_VERSION
    git_commit_sha: GitSha
    git_tree_sha: GitSha
    working_tree_clean: Literal[True] = True
    staged_tree_clean: Literal[True] = True
    untracked_source_files: list[RelativePath] = Field(default_factory=list, max_length=0)
    source_files: list[ActivationSourceFile] = Field(min_length=1)
    schema_files: list[ActivationSourceFile] = Field(min_length=1)
    controller_promotion_files: list[ActivationSourceFile] = Field(min_length=1)
    profile_registry: ActivationSourceFile
    uv_lock: ActivationSourceFile
    python_version: str = Field(min_length=1, max_length=128)
    uv_version: str = Field(min_length=1, max_length=128)
    dependency_resolution_evidence: ActivationCommandReceipt
    blender: ActivationBlenderEvidence
    excluded_classes: list[ActivationSourceExclusion] = Field(min_length=1)
    generator_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    generated_at: datetime

    @model_validator(mode="after")
    def validate_source_identity(self) -> ActivationSourceManifest:
        """Require ordered unique files and exact subset bindings for critical sources."""

        paths = [item.path for item in self.source_files]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("activation source files must be unique and path-sorted")
        by_path = {item.path: item for item in self.source_files}
        for label, records in (
            ("schema", self.schema_files),
            ("controller/promotion", self.controller_promotion_files),
        ):
            record_paths = [item.path for item in records]
            if record_paths != sorted(record_paths) or len(record_paths) != len(
                set(record_paths)
            ):
                raise ValueError(f"{label} source files must be unique and path-sorted")
            if any(by_path.get(item.path) != item for item in records):
                raise ValueError(f"{label} source binding differs from source_files")
        if by_path.get(self.profile_registry.path) != self.profile_registry:
            raise ValueError("profile registry is absent from source_files")
        if by_path.get(self.uv_lock.path) != self.uv_lock:
            raise ValueError("uv.lock is absent from source_files")
        if self.dependency_resolution_evidence.status != "passed":
            raise ValueError("source manifest requires passed dependency resolution")
        _require_contract_identity(
            self,
            prefix="activation-source",
            id_field="manifest_id",
            digest_field="manifest_sha256",
        )
        return self


class ActivationEvidenceClassification(V09StrictModel):
    """Declare whether one candidate root is canonical production evidence or a copy."""

    kind: EvidenceClassificationKind
    authoritative: bool
    copied_workspace: bool
    test_only: bool
    activation_asset: bool
    production_evidence: bool

    @model_validator(mode="after")
    def validate_classification(self) -> ActivationEvidenceClassification:
        """Reserve production truth exclusively for authoritative job evidence."""

        production = self.kind == "authoritative_job"
        expected = (
            self.authoritative
            and not self.copied_workspace
            and not self.test_only
            and self.activation_asset
            and self.production_evidence
        )
        if production != expected:
            raise ValueError("candidate classification flags are internally inconsistent")
        return self


class ActivationEvidenceCheck(V09StrictModel):
    """Bind one eligibility requirement to exact validator-owned evidence artifacts."""

    check_id: CheckId
    status: Literal["passed", "failed", "missing", "unknown"]
    validator: str = Field(min_length=1, max_length=256)
    artifacts: list[ActivationArtifact] = Field(default_factory=list)
    detail: str = Field(min_length=1, max_length=1000)


class ActivationAssetEvidence(V09StrictModel):
    """Provide one explicit candidate root without scanning or migrating legacy evidence."""

    candidate_id: PortableId
    job_id: PortableId
    workflow_id: PortableId
    session_id: PortableId
    attempt_id: PortableId
    revision_id: PortableId
    evidence_root: RelativePath
    classification: ActivationEvidenceClassification
    primary_reference: ActivationArtifact
    candidate_artifact: ActivationArtifact
    final_artifact: ActivationArtifact
    source_activation_baseline: ActivationArtifact
    source_activation_baseline_id: PortableId
    source_activation_baseline_sha256: Sha256
    profile_id: Literal["autonomous_static_prop_v2"] = ACTIVATION_PROFILE_ID
    profile_version: Literal["0.2.0"] = ACTIVATION_PROFILE_VERSION
    terminal_state: TerminalState
    canonical_disposition: Literal["canonical", "superseded", "unknown"]
    superseded_by_candidate_id: PortableId | None = None
    checks: list[ActivationEvidenceCheck]

    @model_validator(mode="after")
    def validate_evidence_projection(self) -> ActivationAssetEvidence:
        """Require unique checks and an explicit supersession identity when applicable."""

        check_ids = [item.check_id for item in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("activation evidence checks must be unique")
        if (self.canonical_disposition == "superseded") != (
            self.superseded_by_candidate_id is not None
        ):
            raise ValueError("superseded evidence requires exactly one replacement identity")
        return self


class ActivationExclusion(V09StrictModel):
    """Record one deterministic machine-readable reason a candidate is not counted."""

    code: ReasonCode
    detail: str = Field(min_length=1, max_length=1000)


class ActivationAssetEligibilityReport(V09StrictModel):
    """Project exact candidate evidence into a fail-closed activation eligibility result."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    report_id: PortableId
    report_sha256: Sha256
    evidence: ActivationAssetEvidence
    eligible: bool
    exclusion_reasons: list[ActivationExclusion]
    generated_at: datetime

    @model_validator(mode="after")
    def validate_eligibility_result(self) -> ActivationAssetEligibilityReport:
        """Require eligible candidates to be canonical production evidence with no blockers."""

        if self.eligible == bool(self.exclusion_reasons):
            raise ValueError("eligibility and exclusion reasons disagree")
        if self.eligible and (
            self.evidence.classification.kind != "authoritative_job"
            or self.evidence.terminal_state != "completed"
            or self.evidence.canonical_disposition != "canonical"
        ):
            raise ValueError("eligible activation evidence is not canonical terminal production")
        _require_contract_identity(
            self,
            prefix="activation-eligibility",
            id_field="report_id",
            digest_field="report_sha256",
        )
        return self


class ActivationCandidateRegistryEntry(V09StrictModel):
    """Bind one explicitly registered eligibility report without filesystem discovery."""

    candidate_id: PortableId
    eligibility_report: ActivationArtifact


class ActivationAssetCandidateRegistry(V09StrictModel):
    """List the only candidate reports an authoritative indexing run may inspect."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    registry_id: PortableId
    authoritative_registry: Literal[True] = True
    entries: list[ActivationCandidateRegistryEntry]
    generated_at: datetime

    @model_validator(mode="after")
    def validate_registry_entries(self) -> ActivationAssetCandidateRegistry:
        """Require deterministic unique registry identities and report paths."""

        candidate_ids = [item.candidate_id for item in self.entries]
        paths = [item.eligibility_report.path for item in self.entries]
        if candidate_ids != sorted(candidate_ids) or len(candidate_ids) != len(
            set(candidate_ids)
        ):
            raise ValueError("activation registry entries must be candidate-sorted and unique")
        if len(paths) != len(set(paths)):
            raise ValueError("activation registry cannot repeat an eligibility report")
        return self


class ActivationAssetIndexRecord(V09StrictModel):
    """Record one registered candidate and whether it contributes an asset unit."""

    candidate_id: PortableId
    job_id: PortableId
    session_id: PortableId
    attempt_id: PortableId
    revision_id: PortableId
    primary_reference_sha256: Sha256
    eligibility_report: ActivationArtifact
    eligible: bool
    counted: bool
    exclusion_reasons: list[ActivationExclusion]


class ActivationReferenceDeduplicationGroup(V09StrictModel):
    """Deduplicate all revisions sharing one exact primary-reference content hash."""

    primary_reference_sha256: Sha256
    candidate_ids: list[PortableId] = Field(min_length=1)
    eligible_canonical_representative: PortableId | None = None
    excluded_candidate_ids: list[PortableId]
    status: Literal["counted", "excluded", "ambiguous"]
    counted_asset_units: Literal[0, 1]
    duplicate_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_group_counts(self) -> ActivationReferenceDeduplicationGroup:
        """Require one representative only for a uniquely counted reference group."""

        if self.candidate_ids != sorted(self.candidate_ids) or len(
            self.candidate_ids
        ) != len(set(self.candidate_ids)):
            raise ValueError("deduplication candidates must be unique and sorted")
        if self.duplicate_count != len(self.candidate_ids) - 1:
            raise ValueError("duplicate count differs from the reference group")
        counted = self.status == "counted"
        if counted != (self.counted_asset_units == 1):
            raise ValueError("deduplication status and counted units disagree")
        if counted != (self.eligible_canonical_representative is not None):
            raise ValueError("counted group requires exactly one representative")
        return self


class ActivationAssetCandidateIndex(V09StrictModel):
    """Count only uniquely eligible primary references from one explicit registry."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    index_id: PortableId
    index_sha256: Sha256
    authoritative_registry: ActivationArtifact
    source_activation_baseline: ActivationArtifact
    source_activation_baseline_id: PortableId
    source_activation_baseline_sha256: Sha256
    records: list[ActivationAssetIndexRecord]
    deduplication_groups: list[ActivationReferenceDeduplicationGroup]
    distinct_asset_count: int = Field(ge=0)
    counted_asset_units: int = Field(ge=0)
    generated_at: datetime

    @model_validator(mode="after")
    def validate_index_totals(self) -> ActivationAssetCandidateIndex:
        """Require deterministic records, groups, and exact counted-unit totals."""

        record_ids = [item.candidate_id for item in self.records]
        group_hashes = [item.primary_reference_sha256 for item in self.deduplication_groups]
        if record_ids != sorted(record_ids) or len(record_ids) != len(set(record_ids)):
            raise ValueError("activation index records must be unique and candidate-sorted")
        if group_hashes != sorted(group_hashes) or len(group_hashes) != len(
            set(group_hashes)
        ):
            raise ValueError("activation reference groups must be unique and hash-sorted")
        counted = sum(item.counted_asset_units for item in self.deduplication_groups)
        if self.counted_asset_units != counted or self.distinct_asset_count != counted:
            raise ValueError("activation index totals differ from deduplication groups")
        if sum(1 for item in self.records if item.counted) != counted:
            raise ValueError("activation index record count differs from group totals")
        _require_contract_identity(
            self,
            prefix="activation-index",
            id_field="index_id",
            digest_field="index_sha256",
        )
        return self


class ActivationHumanQualityDisposition(V09StrictModel):
    """Record one exact human visual disposition without granting approval authority."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    disposition_id: PortableId
    disposition_sha256: Sha256
    job_id: PortableId
    skill_run_id: PortableId
    representative_beauty: ActivationArtifact
    disposition: Literal["accepted", "needs_revision"]
    reviewer_identity: str = Field(min_length=1, max_length=256)
    observed_statement_sha256: Sha256
    is_user_approval: Literal[False] = False
    is_quality_disposition: Literal[True] = True
    recorded_at: datetime

    @model_validator(mode="after")
    def validate_disposition_identity(self) -> ActivationHumanQualityDisposition:
        """Bind the exact beauty and disposition to deterministic immutable identity."""

        _require_contract_identity(
            self,
            prefix="activation-quality-disposition",
            id_field="disposition_id",
            digest_field="disposition_sha256",
        )
        return self


class ActivationCampaignOutcomeEvidence(V09StrictModel):
    """Declare one explicit AQ campaign result without scanning historical workspaces."""

    outcome_id: PortableId
    job_id: PortableId
    session_id: PortableId
    skill_run_id: PortableId
    source_activation_baseline: ActivationArtifact
    source_activation_baseline_id: PortableId
    source_activation_baseline_sha256: Sha256
    primary_reference: ActivationArtifact
    adapter_terminal: ActivationArtifact
    terminal_class: CampaignTerminalClass
    human_quality_disposition: ActivationArtifact
    actual_blender_render_manifests: list[ActivationArtifact] = Field(min_length=1)
    initial_request_count: Literal[1] = 1
    additional_user_decision_count: int = Field(ge=0)
    technical_user_approval_count: int = Field(ge=0)
    canonical_corruption_count: int = Field(ge=0)
    rollback_integrity_preserved: bool
    unresolved_next_action_count: int = Field(ge=0)
    actionable_review_action_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_outcome_evidence_shape(self) -> ActivationCampaignOutcomeEvidence:
        """Require unique Blender receipts and terminal-specific action semantics."""

        manifest_paths = [item.path for item in self.actual_blender_render_manifests]
        if len(manifest_paths) != len(set(manifest_paths)):
            raise ValueError("campaign Blender manifests must use unique paths")
        if self.terminal_class == "usable_review_terminal":
            if self.unresolved_next_action_count or not self.actionable_review_action_count:
                raise ValueError(
                    "usable review terminal requires actions and no unresolved next action"
                )
        elif self.actionable_review_action_count:
            raise ValueError(
                "actionable review actions belong only to a usable review terminal"
            )
        return self


class ActivationCampaignOutcomeEligibilityReport(V09StrictModel):
    """Classify one explicit campaign outcome against local first-completion KPIs."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    report_id: PortableId
    report_sha256: Sha256
    evidence: ActivationCampaignOutcomeEvidence
    eligible: bool
    production_package_verified: bool
    exclusion_reasons: list[ActivationExclusion]
    generated_at: datetime

    @model_validator(mode="after")
    def validate_campaign_eligibility(self) -> ActivationCampaignOutcomeEligibilityReport:
        """Keep success, package, and exclusion claims internally consistent."""

        if self.eligible == bool(self.exclusion_reasons):
            raise ValueError("campaign eligibility and exclusion reasons disagree")
        if self.production_package_verified != (
            self.eligible and self.evidence.terminal_class == "production_delivery"
        ):
            raise ValueError("campaign package count differs from terminal eligibility")
        _require_contract_identity(
            self,
            prefix="activation-campaign-eligibility",
            id_field="report_id",
            digest_field="report_sha256",
        )
        return self


class ActivationCampaignRegistryEntry(V09StrictModel):
    """Bind one explicitly registered campaign-outcome eligibility report."""

    outcome_id: PortableId
    eligibility_report: ActivationArtifact


class ActivationCampaignOutcomeRegistry(V09StrictModel):
    """List the only campaign outcomes one authoritative index may inspect."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    registry_id: PortableId
    authoritative_registry: Literal[True] = True
    entries: list[ActivationCampaignRegistryEntry]
    generated_at: datetime

    @model_validator(mode="after")
    def validate_campaign_registry(self) -> ActivationCampaignOutcomeRegistry:
        """Require unique outcome identities, paths, and deterministic ordering."""

        outcome_ids = [item.outcome_id for item in self.entries]
        paths = [item.eligibility_report.path for item in self.entries]
        if outcome_ids != sorted(outcome_ids) or len(outcome_ids) != len(
            set(outcome_ids)
        ):
            raise ValueError("campaign registry outcomes must be sorted and unique")
        if len(paths) != len(set(paths)):
            raise ValueError("campaign registry cannot repeat an eligibility report")
        return self


class ActivationCampaignOutcomeIndexRecord(V09StrictModel):
    """Record whether one registered terminal contributes a campaign asset unit."""

    outcome_id: PortableId
    job_id: PortableId
    session_id: PortableId
    skill_run_id: PortableId
    primary_reference_sha256: Sha256
    terminal_class: CampaignTerminalClass
    eligibility_report: ActivationArtifact
    eligible: bool
    counted: bool
    production_package_verified: bool
    exclusion_reasons: list[ActivationExclusion]


class ActivationCampaignReferenceGroup(V09StrictModel):
    """Deduplicate eligible campaign outcomes by exact primary-reference bytes."""

    primary_reference_sha256: Sha256
    outcome_ids: list[PortableId] = Field(min_length=1)
    eligible_representative: PortableId | None = None
    status: Literal["counted", "excluded", "ambiguous"]
    counted_asset_units: Literal[0, 1]
    production_package_units: Literal[0, 1]

    @model_validator(mode="after")
    def validate_campaign_reference_group(self) -> ActivationCampaignReferenceGroup:
        """Require one representative and at most one package unit per reference."""

        if self.outcome_ids != sorted(self.outcome_ids) or len(
            self.outcome_ids
        ) != len(set(self.outcome_ids)):
            raise ValueError("campaign outcome IDs must be unique and sorted")
        counted = self.status == "counted"
        if counted != (self.counted_asset_units == 1):
            raise ValueError("campaign group status and counted units disagree")
        if counted != (self.eligible_representative is not None):
            raise ValueError("counted campaign group requires one representative")
        if self.production_package_units > self.counted_asset_units:
            raise ValueError("campaign package units cannot exceed counted assets")
        return self


class ActivationCampaignOutcomeIndex(V09StrictModel):
    """Count normal AQ outcomes separately from strict production-package candidates."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    index_id: PortableId
    index_sha256: Sha256
    authoritative_registry: ActivationArtifact
    source_activation_baseline: ActivationArtifact
    source_activation_baseline_id: PortableId
    source_activation_baseline_sha256: Sha256
    records: list[ActivationCampaignOutcomeIndexRecord]
    reference_groups: list[ActivationCampaignReferenceGroup]
    distinct_successful_asset_count: int = Field(ge=0)
    production_delivery_count: int = Field(ge=0)
    usable_review_terminal_count: int = Field(ge=0)
    production_package_count: int = Field(ge=0)
    generated_at: datetime

    @model_validator(mode="after")
    def validate_campaign_index_totals(self) -> ActivationCampaignOutcomeIndex:
        """Derive campaign totals from exact counted representatives only."""

        record_ids = [item.outcome_id for item in self.records]
        group_hashes = [item.primary_reference_sha256 for item in self.reference_groups]
        if record_ids != sorted(record_ids) or len(record_ids) != len(set(record_ids)):
            raise ValueError("campaign records must be unique and outcome-sorted")
        if group_hashes != sorted(group_hashes) or len(group_hashes) != len(
            set(group_hashes)
        ):
            raise ValueError("campaign reference groups must be unique and hash-sorted")
        counted_records = [item for item in self.records if item.counted]
        counted_units = sum(item.counted_asset_units for item in self.reference_groups)
        package_units = sum(item.production_package_units for item in self.reference_groups)
        production = sum(
            item.terminal_class == "production_delivery" for item in counted_records
        )
        reviews = sum(
            item.terminal_class == "usable_review_terminal" for item in counted_records
        )
        if (
            self.distinct_successful_asset_count != counted_units
            or len(counted_records) != counted_units
            or self.production_delivery_count != production
            or self.usable_review_terminal_count != reviews
            or production + reviews != counted_units
            or self.production_package_count != package_units
        ):
            raise ValueError("campaign outcome index totals differ from its records")
        _require_contract_identity(
            self,
            prefix="activation-campaign-index",
            id_field="index_id",
            digest_field="index_sha256",
        )
        return self


class HumanLocalActivationAcceptance(V09StrictModel):
    """Authorize one exact local profile publication from the five-outcome index."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    acceptance_id: PortableId
    acceptance_sha256: Sha256
    activation_scope: Literal["local_desktop_in_session"] = "local_desktop_in_session"
    activation_baseline: ActivationArtifact
    activation_baseline_id: PortableId
    activation_baseline_sha256: Sha256
    campaign_outcome_index: ActivationArtifact
    campaign_outcome_index_id: PortableId
    campaign_outcome_index_sha256: Sha256
    distinct_primary_reference_sha256s: list[Sha256] = Field(
        min_length=5,
        max_length=5,
    )
    minimum_production_package_count: Literal[1] = 1
    profile_id: Literal["autonomous_static_prop_v2"] = ACTIVATION_PROFILE_ID
    profile_version: Literal["0.2.0"] = ACTIVATION_PROFILE_VERSION
    requested_operation: Literal["publish_local_profile"] = "publish_local_profile"
    reviewer_identity: str = Field(min_length=1, max_length=256)
    created_at: datetime
    expires_at: datetime
    single_use: Literal[True] = True
    is_policy_authorization: Literal[False] = False
    is_user_approval: Literal[True] = True

    @model_validator(mode="after")
    def validate_local_acceptance(self) -> HumanLocalActivationAcceptance:
        """Require exactly five unique references and finite single-use authority."""

        hashes = self.distinct_primary_reference_sha256s
        if hashes != sorted(hashes) or len(hashes) != len(set(hashes)):
            raise ValueError("local activation reference hashes must be unique and sorted")
        if self.expires_at <= self.created_at:
            raise ValueError("local activation acceptance must expire after creation")
        _require_contract_identity(
            self,
            prefix="human-local-activation",
            id_field="acceptance_id",
            digest_field="acceptance_sha256",
        )
        return self


class ActivationReadinessFinding(V09StrictModel):
    """Classify one local requirement, excluded capability, or future limitation."""

    finding_id: ReasonCode
    detail: str = Field(min_length=1, max_length=1000)
    evidence: list[ActivationArtifact] = Field(default_factory=list)


class LocalActivationReadinessReport(V09StrictModel):
    """Project local AQ readiness without treating future client parity as a blocker."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    report_id: PortableId
    report_sha256: Sha256
    activation_scope: Literal["local_desktop_in_session"] = "local_desktop_in_session"
    status: Literal[
        "validation_blocked",
        "ready_for_fresh_campaign",
        "campaign_in_progress",
        "ready_for_human_activation_acceptance",
        "ready_for_profile_publication",
    ]
    source_manifest: ActivationArtifact
    activation_baseline: ActivationArtifact
    production_candidate_index: ActivationArtifact | None = None
    campaign_outcome_index: ActivationArtifact | None = None
    campaign_target_count: Literal[5] = 5
    distinct_campaign_outcome_count: int = Field(ge=0)
    production_package_target_count: Literal[1] = 1
    production_package_count: int = Field(ge=0)
    exact_human_activation_acceptance: ActivationArtifact | None = None
    validation_blockers: list[ActivationReadinessFinding]
    open_requirements: list[ActivationReadinessFinding]
    excluded_capabilities: list[ActivationReadinessFinding]
    future_limitations: list[ActivationReadinessFinding]
    profile_id: Literal["autonomous_static_prop_v2"] = ACTIVATION_PROFILE_ID
    profile_version: Literal["0.2.0"] = ACTIVATION_PROFILE_VERSION
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    sandbox_attested: Literal[False] = False
    client_mediated_verified: Literal[False] = False
    destination_runtime_parity: Literal[False] = False
    generated_at: datetime

    @model_validator(mode="after")
    def validate_local_readiness(self) -> LocalActivationReadinessReport:
        """Keep local status, campaign counts, and remaining requirements exact."""

        for label, findings in (
            ("validation blockers", self.validation_blockers),
            ("open requirements", self.open_requirements),
            ("excluded capabilities", self.excluded_capabilities),
            ("future limitations", self.future_limitations),
        ):
            ids = [item.finding_id for item in findings]
            if ids != sorted(ids) or len(ids) != len(set(ids)):
                raise ValueError(f"{label} must be unique and finding-sorted")
        if self.status == "validation_blocked" and not self.validation_blockers:
            raise ValueError("blocked local readiness requires a validation blocker")
        if self.status != "validation_blocked" and self.validation_blockers:
            raise ValueError("nonblocked local readiness cannot carry validation blockers")
        campaign_complete = self.distinct_campaign_outcome_count == 5
        package_complete = self.production_package_count >= 1
        accepted = self.exact_human_activation_acceptance is not None
        expected_status = "ready_for_fresh_campaign"
        if self.validation_blockers:
            expected_status = "validation_blocked"
        elif campaign_complete and package_complete and accepted:
            expected_status = "ready_for_profile_publication"
        elif campaign_complete and package_complete:
            expected_status = "ready_for_human_activation_acceptance"
        elif self.distinct_campaign_outcome_count:
            expected_status = "campaign_in_progress"
        if self.status != expected_status:
            raise ValueError("local readiness status differs from current evidence counts")
        _require_contract_identity(
            self,
            prefix="local-activation-readiness",
            id_field="report_id",
            digest_field="report_sha256",
        )
        return self


class HumanActivationAcceptance(V09StrictModel):
    """Bind one human profile-activation decision without impersonating policy authority."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    acceptance_id: PortableId
    acceptance_sha256: Sha256
    activation_baseline: ActivationArtifact
    activation_baseline_id: PortableId
    activation_baseline_sha256: Sha256
    candidate_index: ActivationArtifact
    candidate_index_id: PortableId
    candidate_index_sha256: Sha256
    distinct_primary_reference_sha256s: list[Sha256] = Field(min_length=1)
    profile_id: Literal["autonomous_static_prop_v2"] = ACTIVATION_PROFILE_ID
    profile_version: Literal["0.2.0"] = ACTIVATION_PROFILE_VERSION
    requested_operation: Literal["activate_profile"] = "activate_profile"
    reviewer_identity: str = Field(min_length=1, max_length=256)
    created_at: datetime
    expires_at: datetime
    single_use: Literal[True] = True
    is_policy_authorization: Literal[False] = False
    is_user_approval: Literal[True] = True

    @model_validator(mode="after")
    def validate_acceptance_binding(self) -> HumanActivationAcceptance:
        """Require a unique exact asset set, finite expiry, and deterministic identity."""

        hashes = self.distinct_primary_reference_sha256s
        if hashes != sorted(hashes) or len(hashes) != len(set(hashes)):
            raise ValueError("human acceptance asset hashes must be unique and sorted")
        if self.expires_at <= self.created_at:
            raise ValueError("human activation acceptance must expire after creation")
        _require_contract_identity(
            self,
            prefix="human-activation",
            id_field="acceptance_id",
            digest_field="acceptance_sha256",
        )
        return self


class ActivationBaseline(V09StrictModel):
    """Bind one validated clean source checkpoint without activating its profile."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    baseline_id: PortableId
    baseline_sha256: Sha256
    source_manifest: ActivationArtifact
    source_manifest_id: PortableId
    source_manifest_sha256: Sha256
    git_commit_sha: GitSha
    git_tree_sha: GitSha
    schema_manifest_sha256: Sha256
    controller_promotion_manifest_sha256: Sha256
    profile_registry_sha256: Sha256
    uv_lock_sha256: Sha256
    python_version: str = Field(min_length=1, max_length=128)
    uv_version: str = Field(min_length=1, max_length=128)
    blender: ActivationBlenderEvidence
    validation_receipts: list[ActivationCommandReceipt] = Field(min_length=1)
    profile_id: Literal["autonomous_static_prop_v2"] = ACTIVATION_PROFILE_ID
    profile_version: Literal["0.2.0"] = ACTIVATION_PROFILE_VERSION
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    campaign_created: Literal[False] = False
    production_activation_performed: Literal[False] = False
    human_activation_accepted: Literal[False] = False
    created_at: datetime

    @model_validator(mode="after")
    def validate_baseline_identity(self) -> ActivationBaseline:
        """Require all validation receipts to pass and bind a deterministic baseline."""

        command_ids = [item.command_id for item in self.validation_receipts]
        if command_ids != sorted(command_ids) or len(command_ids) != len(
            set(command_ids)
        ):
            raise ValueError("baseline validation receipts must be unique and sorted")
        if any(item.status != "passed" for item in self.validation_receipts):
            raise ValueError("activation baseline cannot bind a failing validation")
        _require_contract_identity(
            self,
            prefix="activation-baseline",
            id_field="baseline_id",
            digest_field="baseline_sha256",
        )
        return self


class ActivationReadinessReport(V09StrictModel):
    """Report the safe activation reentry boundary without starting a campaign."""

    schema_version: Literal["0.1.0"] = ACTIVATION_CONTRACT_VERSION
    contract_status: Literal["disabled_experimental"] = "disabled_experimental"
    report_id: PortableId
    report_sha256: Sha256
    status: Literal[
        "ready_for_campaign_but_not_activated",
        "source_checkpoint_required",
        "validation_blocked",
    ]
    source_manifest: ActivationArtifact | None = None
    activation_baseline: ActivationArtifact | None = None
    candidate_index: ActivationArtifact | None = None
    blockers: list[str]
    profile_id: Literal["autonomous_static_prop_v2"] = ACTIVATION_PROFILE_ID
    profile_version: Literal["0.2.0"] = ACTIVATION_PROFILE_VERSION
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    human_activation_accepted: Literal[False] = False
    campaign_created: Literal[False] = False
    production_activation_performed: Literal[False] = False
    generated_at: datetime

    @model_validator(mode="after")
    def validate_readiness_result(self) -> ActivationReadinessReport:
        """Keep ready and blocked projections internally consistent and non-activating."""

        ready = self.status == "ready_for_campaign_but_not_activated"
        if ready and (self.activation_baseline is None or self.blockers):
            raise ValueError("ready activation report requires a baseline and no blockers")
        if not ready and not self.blockers:
            raise ValueError("blocked activation report requires at least one blocker")
        _require_contract_identity(
            self,
            prefix="activation-readiness",
            id_field="report_id",
            digest_field="report_sha256",
        )
        return self
