"""Strict contracts for the controller-mediated Codex ImageGen companion."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ..blender_artifacts import stable_json_digest
from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

CODEX_IMAGEGEN_SCHEMA_VERSION = "0.1.0"
IMAGE_TO_MATERIAL_ADOPTION_SCHEMA_VERSION = "0.2.0"
CODEX_IMAGEGEN_PROFILE_ID = "autonomous_static_prop_v2_codex_imagegen"
CODEX_IMAGEGEN_PROVIDER_ID = "codex_builtin_gpt_image_v1"

GenerationIntent = Literal[
    "generated_surface_swatch_v1",
    "generated_decal_art_v1",
    "generated_emission_pattern_v1",
    "reference_guided_texture_patch_v1",
    "generated_image_procedural_hybrid_v1",
]
DirectOutputRole = Literal["base_color", "decal_rgb", "emission", "opacity_source"]
DerivedChannelName = Literal[
    "normal",
    "roughness",
    "metallic",
    "height",
    "displacement",
    "occlusion",
]
ForbiddenDirectChannel = Literal[
    "normal",
    "roughness",
    "metallic",
    "height",
    "displacement",
    "occlusion",
    "tangent_space_vectors",
]
ImageQualityLevel = Literal["low", "medium"]
ImageAspectRatio = Literal["square", "landscape", "portrait"]

ALL_GENERATION_INTENTS: tuple[str, ...] = (
    "generated_surface_swatch_v1",
    "generated_decal_art_v1",
    "generated_emission_pattern_v1",
    "reference_guided_texture_patch_v1",
    "generated_image_procedural_hybrid_v1",
)
ALL_DIRECT_OUTPUT_ROLES: tuple[str, ...] = (
    "base_color",
    "decal_rgb",
    "emission",
    "opacity_source",
)
ALL_FORBIDDEN_DIRECT_CHANNELS: tuple[str, ...] = (
    "normal",
    "roughness",
    "metallic",
    "height",
    "displacement",
    "occlusion",
    "tangent_space_vectors",
)

QualityScore = Annotated[float, Field(ge=0.0, le=1.0)]


class CodexImageStrictModel(BaseModel):
    """Reject undeclared fields, coercion, and non-finite numeric evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class CodexImageArtifact(CodexImageStrictModel):
    """Bind one non-empty job-contained file to exact bytes and media semantics."""

    artifact_id: PortableId
    kind: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)
    media_type: str = Field(min_length=1, max_length=128)


class CodexImageDimensions(CodexImageStrictModel):
    """Describe one bounded raster size without assuming a provider-specific API shape."""

    width: int = Field(ge=64, le=2048)
    height: int = Field(ge=64, le=2048)


class CodexImageEvidenceEnvelope(CodexImageStrictModel):
    """Provide immutable identity and provenance shared by ImageGen 0.1 evidence."""

    schema_version: Literal["0.1.0"] = CODEX_IMAGEGEN_SCHEMA_VERSION
    contract_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    profile_id: Literal["autonomous_static_prop_v2_codex_imagegen"] = (
        CODEX_IMAGEGEN_PROFILE_ID
    )
    provider_id: Literal["codex_builtin_gpt_image_v1"] = CODEX_IMAGEGEN_PROVIDER_ID
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: str = Field(min_length=1, max_length=128)
    producer_version: Literal["0.1.0"] = CODEX_IMAGEGEN_SCHEMA_VERSION
    provenance: list[CodexImageArtifact] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_provenance_uniqueness(self) -> CodexImageEvidenceEnvelope:
        """Reject ambiguous provenance that binds one path or artifact ID more than once."""

        paths = [item.path for item in self.provenance]
        artifact_ids = [item.artifact_id for item in self.provenance]
        if len(paths) != len(set(paths)):
            raise ValueError("Codex ImageGen provenance paths must be unique")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("Codex ImageGen provenance artifact IDs must be unique")
        return self


class CodexBuiltinImageProviderProfile(CodexImageEvidenceEnvelope):
    """Freeze the credential-free current-task provider boundary for one overlay session."""

    provider_profile_id: PortableId
    base_profile: Literal["autonomous_static_prop_v2"] = "autonomous_static_prop_v2"
    execution_mode: Literal["controller_mediated"] = "controller_mediated"
    controller_mode: Literal["desktop_in_session"] = "desktop_in_session"
    credential_scope: Literal["none"] = "none"
    billing_scope: Literal["codex_usage"] = "codex_usage"
    network_required: Literal[False] = False
    api_key_required: Literal[False] = False
    repository_can_spawn_codex_task: Literal[False] = False
    autonomous_daemon: Literal[False] = False
    controller_required: Literal[True] = True
    destination_project_write: Literal[False] = False
    canonical_material_write: Literal[False] = False
    allowed_generation_intents: list[GenerationIntent] = Field(min_length=1)
    allowed_direct_output_roles: list[DirectOutputRole] = Field(min_length=1)
    forbidden_direct_channels: list[ForbiddenDirectChannel] = Field(min_length=1)
    status: Literal["disabled_experimental"] = "disabled_experimental"
    activation_evidence: list[CodexImageArtifact] = Field(
        default_factory=list,
        max_length=0,
    )

    @model_validator(mode="after")
    def validate_provider_boundary(self) -> CodexBuiltinImageProviderProfile:
        """Require exact allowlists and real evidence before any active status claim."""

        if tuple(self.allowed_generation_intents) != ALL_GENERATION_INTENTS:
            raise ValueError("provider generation-intent allowlist is not canonical")
        if tuple(self.allowed_direct_output_roles) != ALL_DIRECT_OUTPUT_ROLES:
            raise ValueError("provider direct-output allowlist is not canonical")
        if tuple(self.forbidden_direct_channels) != ALL_FORBIDDEN_DIRECT_CHANNELS:
            raise ValueError("provider forbidden-channel list is not canonical")
        if self.activation_evidence:
            raise ValueError("disabled provider status cannot claim activation evidence")
        return self


class CodexImageGenerationBudget(CodexImageEvidenceEnvelope):
    """Freeze bounded generation, candidate, refinement, size, and elapsed-time limits."""

    budget_id: PortableId
    max_total_generations: int = Field(default=4, ge=1, le=4)
    max_candidates: int = Field(default=3, ge=1, le=3)
    max_edits_or_refinements: int = Field(default=1, ge=0, le=1)
    max_generations_per_assignment: int = Field(default=3, ge=1, le=3)
    draft_quality: Literal["low"] = "low"
    final_quality: Literal["medium"] = "medium"
    max_draft_size: CodexImageDimensions = Field(
        default_factory=lambda: CodexImageDimensions(width=1024, height=1024)
    )
    max_final_size: CodexImageDimensions = Field(
        default_factory=lambda: CodexImageDimensions(width=2048, height=2048)
    )
    timeout_per_assignment_seconds: int = Field(default=900, ge=30, le=3600)
    max_total_elapsed_seconds: int = Field(default=3600, ge=30, le=14400)
    immutable: Literal[True] = True
    automatic_expansion: Literal[False] = False

    @model_validator(mode="after")
    def validate_budget_caps(self) -> CodexImageGenerationBudget:
        """Keep nested candidate, assignment, size, and elapsed limits coherent."""

        if self.max_candidates > self.max_total_generations:
            raise ValueError("candidate cap cannot exceed total generation cap")
        if self.max_generations_per_assignment > self.max_candidates:
            raise ValueError("per-assignment cap cannot exceed candidate cap")
        if (
            self.max_draft_size.width > self.max_final_size.width
            or self.max_draft_size.height > self.max_final_size.height
        ):
            raise ValueError("draft size cap cannot exceed final size cap")
        if self.timeout_per_assignment_seconds > self.max_total_elapsed_seconds:
            raise ValueError("assignment timeout cannot exceed total elapsed budget")
        return self


class CodexImageGenerationBudgetUsage(CodexImageStrictModel):
    """Record reconstructed budget use without mutating the immutable budget contract."""

    assignments: int = Field(default=0, ge=0)
    total_generations: int = Field(default=0, ge=0)
    candidates: int = Field(default=0, ge=0)
    edits_or_refinements: int = Field(default=0, ge=0)
    elapsed_seconds: int = Field(default=0, ge=0)


class CodexImageGenerationPlanItem(CodexImageStrictModel):
    """Describe one material-scoped generation opportunity or bounded fallback route."""

    plan_item_id: PortableId
    target_material_ids: list[PortableId] = Field(min_length=1)
    semantic_roles: list[PortableId] = Field(min_length=1)
    generation_intent: GenerationIntent
    allowed_output_roles: list[DirectOutputRole] = Field(min_length=1)
    prompt_template_id: PortableId
    requested_candidate_count: int = Field(default=1, ge=1, le=3)
    quality_level: ImageQualityLevel
    image_size: CodexImageDimensions
    aspect_ratio: ImageAspectRatio
    fallback: Literal[
        "local_procedural_fallback",
        "review_required",
        "user_image_required",
    ]

    @model_validator(mode="after")
    def validate_plan_item(self) -> CodexImageGenerationPlanItem:
        """Reject duplicate targets or roles and inconsistent aspect declarations."""

        if len(self.target_material_ids) != len(set(self.target_material_ids)):
            raise ValueError("plan item material IDs must be unique")
        if len(self.semantic_roles) != len(set(self.semantic_roles)):
            raise ValueError("plan item semantic roles must be unique")
        if len(self.allowed_output_roles) != len(set(self.allowed_output_roles)):
            raise ValueError("plan item output roles must be unique")
        _validate_aspect(self.image_size, self.aspect_ratio)
        return self


class CodexImageGenerationPlan(CodexImageEvidenceEnvelope):
    """Bind an explicit overlay opt-in to one base AQ plan, profile, and budget."""

    plan_id: PortableId
    base_autonomy_plan: CodexImageArtifact
    base_root_authorization: CodexImageArtifact
    provider_profile: CodexImageArtifact
    budget: CodexImageArtifact
    items: list[CodexImageGenerationPlanItem] = Field(min_length=1)
    codex_imagegen_allowed: Literal[True] = True
    controller_required: Literal[True] = True
    repository_can_spawn_codex_task: Literal[False] = False
    automatic_migration: Literal[False] = False
    canonical_material_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_plan_bindings(self) -> CodexImageGenerationPlan:
        """Require unique plan items and every named source in exact provenance."""

        item_ids = [item.plan_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("generation plan item IDs must be unique")
        named = [
            self.base_autonomy_plan,
            self.base_root_authorization,
            self.provider_profile,
            self.budget,
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("generation plan omits a named provenance artifact")
        return self


class CodexImageGenerationAssignment(CodexImageEvidenceEnvelope):
    """Freeze one current-task generation request and its exact staging file set."""

    assignment_id: PortableId
    sequence: int = Field(ge=0)
    plan_item_id: PortableId
    plan: CodexImageArtifact
    provider_profile: CodexImageArtifact
    budget: CodexImageArtifact
    base_state: CodexImageArtifact
    target_material_ids: list[PortableId] = Field(min_length=1)
    semantic_roles: list[PortableId] = Field(min_length=1)
    allowed_output_roles: list[DirectOutputRole] = Field(min_length=1)
    prompt_template_id: PortableId
    rendered_prompt_text: str = Field(min_length=1, max_length=8000)
    prompt_sha256: Sha256
    exact_text_sha256: Sha256 | None = None
    exact_text_in_prompt: Literal[False] = False
    reference_images: list[CodexImageArtifact] = Field(default_factory=list)
    staging_output_directory: RelativePath
    candidate_output_paths: list[RelativePath] = Field(min_length=1, max_length=3)
    completion_file_target: RelativePath
    candidate_count_upper_bound: int = Field(default=3, ge=1, le=3)
    requested_candidate_count: int = Field(default=1, ge=1, le=3)
    image_size: CodexImageDimensions
    quality_level: ImageQualityLevel
    aspect_ratio: ImageAspectRatio
    generation_intent: GenerationIntent
    forbidden_content_notes: list[str] = Field(min_length=1)
    forbidden_text_notes: list[str] = Field(min_length=1)
    budget_snapshot_sha256: Sha256
    protected_source_inventory_sha256: Sha256
    assignment_payload_sha256: Sha256
    controller_required: Literal[True] = True
    canonical_write_authority: Literal[False] = False
    destination_write_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_assignment(self) -> CodexImageGenerationAssignment:
        """Validate exact prompt, output namespace, counts, bindings, and self digest."""

        if self.prompt_sha256 != text_sha256(self.rendered_prompt_text):
            raise ValueError("rendered prompt hash is inconsistent")
        if self.requested_candidate_count > self.candidate_count_upper_bound:
            raise ValueError("requested candidates exceed the assignment cap")
        if len(self.candidate_output_paths) != self.requested_candidate_count:
            raise ValueError("candidate output paths must equal requested candidate count")
        if len(self.candidate_output_paths) != len(set(self.candidate_output_paths)):
            raise ValueError("candidate output paths must be unique")
        if len(self.target_material_ids) != len(set(self.target_material_ids)):
            raise ValueError("assignment material IDs must be unique")
        if len(self.semantic_roles) != len(set(self.semantic_roles)):
            raise ValueError("assignment semantic roles must be unique")
        if len(self.allowed_output_roles) != len(set(self.allowed_output_roles)):
            raise ValueError("assignment output roles must be unique")
        expected_root = (
            f"production/autonomy_v2/{self.session_id}/codex_imagegen/"
            f"assignments/{self.assignment_id}/staging"
        )
        if self.staging_output_directory != expected_root:
            raise ValueError("assignment staging directory differs from its identity")
        prefix = expected_root + "/"
        for index, path in enumerate(self.candidate_output_paths):
            if path != f"{prefix}candidate-{index:02d}.png":
                raise ValueError("candidate output path is not the canonical staging leaf")
        if self.completion_file_target != f"{prefix}completion.json":
            raise ValueError("completion target is not the canonical staging leaf")
        _validate_aspect(self.image_size, self.aspect_ratio)
        named = [self.plan, self.provider_profile, self.budget, self.base_state]
        if any(item not in self.provenance for item in [*named, *self.reference_images]):
            raise ValueError("assignment omits named immutable provenance")
        payload = self.model_dump(mode="json", exclude={"assignment_payload_sha256"})
        if self.assignment_payload_sha256 != stable_json_digest(payload):
            raise ValueError("assignment payload hash is inconsistent")
        return self


class CodexGeneratedFile(CodexImageStrictModel):
    """Describe one generated raster in the assignment-declared staging file set."""

    candidate_id: PortableId
    ordinal: int = Field(ge=0, le=2)
    output_role: DirectOutputRole
    artifact: CodexImageArtifact
    width: int = Field(ge=64, le=2048)
    height: int = Field(ge=64, le=2048)
    image_format: Literal["png"] = "png"
    alpha_present: bool

    @model_validator(mode="after")
    def validate_file_media(self) -> CodexGeneratedFile:
        """Keep the strict PNG-only staging contract consistent with artifact metadata."""

        if self.artifact.media_type != "image/png":
            raise ValueError("generated PNG artifact must use image/png media type")
        if not self.artifact.path.casefold().endswith(".png"):
            raise ValueError("generated PNG artifact path must end in .png")
        return self


class CodexImageGenerationCompletion(CodexImageEvidenceEnvelope):
    """Record one bounded controller completion without granting adoption authority."""

    completion_id: PortableId
    assignment: CodexImageArtifact
    assignment_payload_sha256: Sha256
    controller_kind: Literal["desktop_in_session", "fake_for_tests"]
    execution_scope: Literal["codex_built_in", "deterministic_fake"]
    source_kind: Literal["codex_builtin_generated_image", "deterministic_fake"]
    source_policy: Literal["controller_allowed_local_root"] = (
        "controller_allowed_local_root"
    )
    source_inventory_sha256: Sha256
    generated_files: list[CodexGeneratedFile] = Field(default_factory=list, max_length=3)
    generation_count: int = Field(ge=0, le=4)
    edit_or_refinement_count: int = Field(default=0, ge=0, le=1)
    prompt_echo_sha256: Sha256
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    controller_executed_at: AwareDatetime
    status: Literal["completed", "partial", "failed", "cancelled"]
    canonical_unchanged: Literal[True] = True
    human_reviewed: Literal[False] = False

    @model_validator(mode="after")
    def validate_completion_shape(self) -> CodexImageGenerationCompletion:
        """Reject duplicate files and dishonest completed, partial, or fake outcomes."""

        ids = [item.candidate_id for item in self.generated_files]
        paths = [item.artifact.path for item in self.generated_files]
        ordinals = [item.ordinal for item in self.generated_files]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("completion generated files must be unique")
        if ordinals != list(range(len(ordinals))):
            raise ValueError("completion ordinals must be contiguous from zero")
        if self.generation_count < len(self.generated_files):
            raise ValueError("generation count cannot be below generated file count")
        if self.status == "completed":
            if not self.generated_files or self.failures:
                raise ValueError("completed generation requires files and no failures")
        elif self.status == "partial":
            if not self.generated_files or not self.failures:
                raise ValueError("partial generation requires files and failures")
        elif self.status == "failed":
            if not self.failures:
                raise ValueError("failed generation requires failure diagnostics")
        elif self.generated_files:
            raise ValueError("cancelled generation cannot claim generated files")
        if (self.controller_kind, self.execution_scope) not in {
            ("desktop_in_session", "codex_built_in"),
            ("fake_for_tests", "deterministic_fake"),
        }:
            raise ValueError("controller kind and execution scope differ")
        if (self.controller_kind, self.source_kind) not in {
            ("desktop_in_session", "codex_builtin_generated_image"),
            ("fake_for_tests", "deterministic_fake"),
        }:
            raise ValueError("controller kind and local source kind differ")
        named = [self.assignment, *[item.artifact for item in self.generated_files]]
        if any(item not in self.provenance for item in named):
            raise ValueError("completion omits named immutable provenance")
        return self


class CodexImageGenerationCandidate(CodexImageEvidenceEnvelope):
    """Bind one completion output to its material and semantic candidate scope."""

    candidate_id: PortableId
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    controller_request: CodexImageArtifact
    controller_result: CodexImageArtifact
    generated_file: CodexGeneratedFile
    target_material_ids: list[PortableId] = Field(min_length=1)
    semantic_roles: list[PortableId] = Field(min_length=1)
    generation_intent: GenerationIntent
    staging_only: Literal[True] = True
    canonical_material_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_candidate_evidence(self) -> CodexImageGenerationCandidate:
        """Bind the candidate identity and every named execution artifact exactly."""

        if self.candidate_id != self.generated_file.candidate_id:
            raise ValueError("candidate identity differs from its generated file")
        if len(self.target_material_ids) != len(set(self.target_material_ids)):
            raise ValueError("candidate target material IDs must be unique")
        if len(self.semantic_roles) != len(set(self.semantic_roles)):
            raise ValueError("candidate semantic roles must be unique")
        named = [
            self.assignment,
            self.completion,
            self.controller_request,
            self.controller_result,
            self.generated_file.artifact,
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("candidate omits named immutable provenance")
        return self


class CodexGeneratedImageEvidence(CodexImageEvidenceEnvelope):
    """Describe generated pixels honestly as staged visual content, not a PBR set."""

    evidence_id: PortableId
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    controller_request: CodexImageArtifact
    controller_result: CodexImageArtifact
    candidate: CodexImageArtifact
    candidate_id: PortableId
    generated_file: CodexGeneratedFile
    target_material_ids: list[PortableId] = Field(min_length=1)
    semantic_roles: list[PortableId] = Field(min_length=1)
    generation_intent: GenerationIntent
    staging_only: Literal[True] = True
    complete_pbr_set: Literal[False] = False
    human_reviewed: Literal[False] = False
    rights_scope: Literal["project_generated_codex_usage"] = (
        "project_generated_codex_usage"
    )

    @model_validator(mode="after")
    def validate_generated_evidence(self) -> CodexGeneratedImageEvidence:
        """Require candidate identity and every named source in exact provenance."""

        if self.candidate_id != self.generated_file.candidate_id:
            raise ValueError("generated evidence candidate identity differs")
        if len(self.target_material_ids) != len(set(self.target_material_ids)):
            raise ValueError("generated evidence material IDs must be unique")
        if len(self.semantic_roles) != len(set(self.semantic_roles)):
            raise ValueError("generated evidence semantic roles must be unique")
        named = [
            self.assignment,
            self.completion,
            self.controller_request,
            self.controller_result,
            self.candidate,
            self.generated_file.artifact,
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("generated evidence omits named immutable provenance")
        return self


class CodexImageQualityCheck(CodexImageStrictModel):
    """Record one deterministic, advisory, or unavailable candidate quality check."""

    check_id: PortableId
    status: Literal["passed", "failed", "unscorable", "advisory"]
    score: QualityScore | None = None
    threshold: QualityScore | None = None
    hard_gate: bool
    algorithm_id: PortableId
    message: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_check_score(self) -> CodexImageQualityCheck:
        """Keep scored and unscorable checks internally consistent."""

        if self.status == "unscorable" and self.score is not None:
            raise ValueError("unscorable quality checks cannot carry a score")
        if self.status in {"passed", "failed"} and self.score is None:
            raise ValueError("passed or failed quality checks require a score")
        return self


class CodexImageGenerationQualityReport(CodexImageEvidenceEnvelope):
    """Aggregate one candidate's hard gates and advisory content observations."""

    report_id: PortableId
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    candidate: CodexImageArtifact
    generated_image_evidence: CodexImageArtifact
    checks: list[CodexImageQualityCheck] = Field(min_length=1)
    deterministic_score: QualityScore
    outcome: Literal["passed", "failed", "review_required", "unscorable"]
    selection_eligible: bool
    human_reviewed: bool = False
    human_review_evidence: CodexImageArtifact | None = None

    @model_validator(mode="after")
    def validate_quality_outcome(self) -> CodexImageGenerationQualityReport:
        """Prevent missing or failed hard gates and synthetic human-review claims."""

        ids = [item.check_id for item in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("quality check IDs must be unique")
        hard = [item for item in self.checks if item.hard_gate]
        if not hard:
            raise ValueError("quality report requires at least one hard gate")
        has_failed = any(item.status == "failed" for item in hard)
        has_unscorable = any(item.status == "unscorable" for item in hard)
        if has_failed and self.outcome != "failed":
            raise ValueError("failed hard gate requires failed quality outcome")
        if has_unscorable and self.outcome == "passed":
            raise ValueError("unscorable hard gate cannot produce a passed outcome")
        if self.selection_eligible != (self.outcome == "passed"):
            raise ValueError("selection eligibility must match a passed outcome")
        if self.human_reviewed != (self.human_review_evidence is not None):
            raise ValueError("human review claim requires exact review evidence")
        named = [
            self.assignment,
            self.completion,
            self.candidate,
            self.generated_image_evidence,
            *(
                [self.human_review_evidence]
                if self.human_review_evidence is not None
                else []
            ),
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("quality report omits named immutable provenance")
        return self


class CodexImageCandidateDecision(CodexImageStrictModel):
    """Record one selected, rejected, or ineligible candidate without deleting it."""

    candidate_id: PortableId
    candidate: CodexImageArtifact
    quality_report: CodexImageArtifact
    outcome: Literal["selected", "rejected", "ineligible"]
    reason_codes: list[PortableId] = Field(min_length=1)


class CodexImageGenerationSelection(CodexImageEvidenceEnvelope):
    """Choose at most one eligible candidate with deterministic rejection evidence."""

    selection_id: PortableId
    assignment: CodexImageArtifact
    completion: CodexImageArtifact
    candidate_count: int = Field(ge=1, le=3)
    selected_candidate: CodexImageArtifact | None = None
    selected_quality_report: CodexImageArtifact | None = None
    decisions: list[CodexImageCandidateDecision] = Field(min_length=1, max_length=3)
    outcome: Literal["selected", "no_eligible_candidate", "review_required"]
    selection_method: Literal["deterministic_lexicographic_v1"] = (
        "deterministic_lexicographic_v1"
    )
    human_reviewed: bool = False
    human_review_evidence: CodexImageArtifact | None = None

    @model_validator(mode="after")
    def validate_single_selection(self) -> CodexImageGenerationSelection:
        """Require every candidate exactly once and never synthesize human review."""

        ids = [item.candidate_id for item in self.decisions]
        if len(ids) != self.candidate_count or len(ids) != len(set(ids)):
            raise ValueError("selection decisions must exactly cover unique candidates")
        selected = [item for item in self.decisions if item.outcome == "selected"]
        if self.outcome == "selected":
            if len(selected) != 1:
                raise ValueError("selected outcome requires exactly one selected decision")
            if self.selected_candidate != selected[0].candidate:
                raise ValueError("selected candidate differs from its decision")
            if self.selected_quality_report != selected[0].quality_report:
                raise ValueError("selected quality report differs from its decision")
        elif (
            selected
            or self.selected_candidate is not None
            or self.selected_quality_report is not None
        ):
            raise ValueError("non-selected outcome cannot bind a selected candidate")
        if self.human_reviewed != (self.human_review_evidence is not None):
            raise ValueError("human review claim requires exact review evidence")
        named = [
            self.assignment,
            self.completion,
            *[item.candidate for item in self.decisions],
            *[item.quality_report for item in self.decisions],
            *(
                [self.human_review_evidence]
                if self.human_review_evidence is not None
                else []
            ),
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("selection omits named immutable provenance")
        return self


class DerivedChannelEvidence(CodexImageStrictModel):
    """Bind one locally derived material channel to source, algorithm, and output bytes."""

    channel: DerivedChannelName
    algorithm_id: PortableId
    source_sha256: Sha256
    parameters: dict[str, bool | int | float | str]
    parameters_sha256: Sha256
    output: CodexImageArtifact

    @model_validator(mode="after")
    def validate_parameters_digest(self) -> DerivedChannelEvidence:
        """Require an exact digest of bounded deterministic derivation parameters."""

        if self.parameters_sha256 != stable_json_digest(self.parameters):
            raise ValueError("derived channel parameter hash is inconsistent")
        return self


class ImageToMaterialAdoption(CodexImageStrictModel):
    """Authorize one selected visual source for later local material authoring only."""

    schema_version: Literal["0.2.0"] = IMAGE_TO_MATERIAL_ADOPTION_SCHEMA_VERSION
    contract_id: PortableId
    adoption_id: PortableId
    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    session_id: PortableId
    profile_id: Literal["autonomous_static_prop_v2_codex_imagegen"] = (
        CODEX_IMAGEGEN_PROFILE_ID
    )
    provider_id: Literal["codex_builtin_gpt_image_v1"] = CODEX_IMAGEGEN_PROVIDER_ID
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: str = Field(min_length=1, max_length=128)
    producer_version: Literal["0.2.0"] = IMAGE_TO_MATERIAL_ADOPTION_SCHEMA_VERSION
    provenance: list[CodexImageArtifact] = Field(min_length=1)
    created_at: AwareDatetime
    selection: CodexImageArtifact
    selected_candidate: CodexImageArtifact
    generated_image_evidence: CodexImageArtifact
    quality_report: CodexImageArtifact
    selected_source_sha256: Sha256
    target_material_ids: list[PortableId] = Field(min_length=1)
    material_strategy: Literal[
        "codex_generated_base_color_v1",
        "codex_generated_decal_v1",
        "codex_generated_emission_v1",
        "codex_generated_procedural_hybrid_v1",
    ]
    direct_channels: list[DirectOutputRole] = Field(min_length=1)
    derived_channels: list[DerivedChannelEvidence] = Field(default_factory=list)
    exact_text_composition: CodexImageArtifact | None = None
    complete_pbr_set: Literal[False] = False
    provider_canonical_write: Literal[False] = False
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_adoption_scope(self) -> ImageToMaterialAdoption:
        """Limit direct channels and bind every local derivation to the selected source."""

        if len(self.target_material_ids) != len(set(self.target_material_ids)):
            raise ValueError("adoption material IDs must be unique")
        if len(self.direct_channels) != len(set(self.direct_channels)):
            raise ValueError("adoption direct channels must be unique")
        derived_names = [item.channel for item in self.derived_channels]
        if len(derived_names) != len(set(derived_names)):
            raise ValueError("adoption derived channels must be unique")
        if any(
            item.source_sha256 != self.selected_source_sha256
            for item in self.derived_channels
        ):
            raise ValueError("derived channel does not bind the selected source")
        named = [
            self.selection,
            self.selected_candidate,
            self.generated_image_evidence,
            self.quality_report,
            *[item.output for item in self.derived_channels],
            *(
                [self.exact_text_composition]
                if self.exact_text_composition is not None
                else []
            ),
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("adoption omits named immutable provenance")
        return self


class CodexImageGenerationTerminal(CodexImageEvidenceEnvelope):
    """Close one generation plan without implying background execution or PBR completion."""

    terminal_id: PortableId
    plan: CodexImageArtifact
    budget: CodexImageArtifact
    budget_usage: CodexImageGenerationBudgetUsage
    plan_item_id: PortableId | None = None
    runtime_trigger: Literal[
        "assignment_capacity_rejected",
        "controller_timeout",
        "controller_failed",
        "controller_rejected",
        "controller_cancelled",
    ] | None = None
    status: Literal[
        "adopted",
        "local_procedural_fallback",
        "review_required",
        "user_image_required",
        "failed",
        "cancelled",
    ]
    assignment: CodexImageArtifact | None = None
    controller_request: CodexImageArtifact | None = None
    controller_result: CodexImageArtifact | None = None
    completion: CodexImageArtifact | None = None
    selection: CodexImageArtifact | None = None
    adoption: CodexImageArtifact | None = None
    candidates: list[CodexImageArtifact] = Field(default_factory=list, max_length=3)
    quality_reports: list[CodexImageArtifact] = Field(default_factory=list, max_length=3)
    reason: str = Field(min_length=1, max_length=1024)
    codex_controller_required: Literal[True] = True
    autonomous_daemon: Literal[False] = False
    continuation_after_app_exit: Literal[False] = False
    canonical_unchanged_by_provider: Literal[True] = True

    @model_validator(mode="after")
    def validate_terminal_evidence(self) -> CodexImageGenerationTerminal:
        """Require adoption evidence only for adopted terminals and preserve all candidates."""

        if (self.controller_request is None) != (self.controller_result is None):
            raise ValueError(
                "generation terminal requires controller request and result together"
            )
        if self.runtime_trigger is not None and self.plan_item_id is None:
            raise ValueError("runtime generation terminal requires its exact plan item")
        if self.runtime_trigger == "assignment_capacity_rejected":
            if any(
                item is not None
                for item in (
                    self.assignment,
                    self.controller_request,
                    self.controller_result,
                    self.completion,
                    self.selection,
                    self.adoption,
                )
            ) or self.candidates or self.quality_reports:
                raise ValueError(
                    "capacity terminal cannot claim assignment or controller evidence"
                )
            if self.status not in {
                "local_procedural_fallback",
                "review_required",
                "user_image_required",
            }:
                raise ValueError("capacity terminal must apply its declared plan fallback")
        if self.runtime_trigger is not None and self.runtime_trigger.startswith(
            "controller_"
        ):
            if any(
                item is None
                for item in (
                    self.assignment,
                    self.controller_request,
                    self.controller_result,
                )
            ):
                raise ValueError(
                    "controller terminal requires assignment, request, and result evidence"
                )
            if any(
                item is not None
                for item in (self.completion, self.selection, self.adoption)
            ):
                raise ValueError(
                    "non-completing controller terminal cannot claim downstream evidence"
                )
            if self.candidates or self.quality_reports:
                raise ValueError(
                    "non-completing controller terminal cannot claim candidate evidence"
                )
            if self.runtime_trigger == "controller_cancelled":
                if self.status != "cancelled":
                    raise ValueError("cancelled controller terminal must remain cancelled")
            elif self.status not in {
                "local_procedural_fallback",
                "review_required",
                "user_image_required",
            }:
                raise ValueError(
                    "failed controller terminal must apply its declared plan fallback"
                )
        if self.status == "adopted":
            if any(
                item is None
                for item in (self.assignment, self.completion, self.selection, self.adoption)
            ):
                raise ValueError("adopted terminal requires the complete evidence chain")
            if not self.candidates or len(self.candidates) != len(self.quality_reports):
                raise ValueError("adopted terminal requires every candidate quality report")
        elif self.adoption is not None:
            raise ValueError("non-adopted terminal cannot carry material adoption evidence")
        named = [
            self.plan,
            self.budget,
            *(
                [self.assignment]
                if self.assignment is not None
                else []
            ),
            *(
                [self.controller_request]
                if self.controller_request is not None
                else []
            ),
            *(
                [self.controller_result]
                if self.controller_result is not None
                else []
            ),
            *(
                [self.completion]
                if self.completion is not None
                else []
            ),
            *(
                [self.selection]
                if self.selection is not None
                else []
            ),
            *(
                [self.adoption]
                if self.adoption is not None
                else []
            ),
            *self.candidates,
            *self.quality_reports,
        ]
        if any(item not in self.provenance for item in named):
            raise ValueError("generation terminal omits named immutable provenance")
        return self


def _validate_aspect(size: CodexImageDimensions, aspect: ImageAspectRatio) -> None:
    """Require the declared coarse aspect to match the exact raster dimensions."""

    if aspect == "square" and size.width != size.height:
        raise ValueError("square image dimensions must be equal")
    if aspect == "landscape" and size.width <= size.height:
        raise ValueError("landscape image width must exceed height")
    if aspect == "portrait" and size.height <= size.width:
        raise ValueError("portrait image height must exceed width")


def assignment_payload_sha256(payload: dict[str, object]) -> str:
    """Hash an assignment payload after excluding its self-digest field."""

    normalized = dict(payload)
    normalized.pop("assignment_payload_sha256", None)
    return stable_json_digest(normalized)


def text_sha256(value: str) -> str:
    """Hash exact UTF-8 text without JSON string quoting or newline normalization."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
