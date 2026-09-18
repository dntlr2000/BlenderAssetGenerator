"""Exact observation, visual review and bounded revision contracts, separate from IQ 0.2."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..integrated_quality.v02_models import JobId, RelativePath, Sha256, StableId

Unit = Annotated[float, Field(ge=0, le=1)]
Point = tuple[Unit, Unit]
Region = tuple[Unit, Unit, Unit, Unit]
DefectKind = Literal[
    "volume",
    "cross_section",
    "part_relation",
    "silhouette",
    "local_dimension",
    "material",
    "surface_direction",
    "camera",
    "missing_evidence",
    "topology",
    "uv",
]
RevisionRoute = Literal[
    "structural_reentry",
    "parametric_revision",
    "material_revision",
    "calibration",
    "evidence_required",
    "technical_recovery",
    "quality_ready",
    "review_required",
]


class FidelityModel(BaseModel):
    """Reject coercion, unknown versions/fields, non-finite numbers and implicit authority."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FidelityArtifact(FidelityModel):
    """Bind a contained artifact to its immutable bytes, not a mutable latest pointer."""

    path: RelativePath
    sha256: Sha256


class ReferenceMaskSeedV01(FidelityModel):
    """Describe an observed interior segmentation sample, never a whole-part extent."""

    object_id: StableId
    source_id: StableId
    observation_id: StableId
    bbox_norm: Region
    confidence: float = Field(ge=0.5, le=1)

    @model_validator(mode="after")
    def validate_region(self) -> Self:
        """Reject empty or inverted interior seed rectangles."""
        x0, y0, x1, y1 = self.bbox_norm
        if x0 >= x1 or y0 >= y1:
            raise ValueError("reference segmentation seed must have positive area")
        return self


class ReferenceMaskSeedEvidenceV01(FidelityModel):
    """Explicit additive segmentation evidence separate from SceneSpec semantic boxes."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["reference_mask_seed_evidence"] = "reference_mask_seed_evidence"
    job_id: JobId
    reference: FidelityArtifact
    seeds: list[ReferenceMaskSeedV01] = Field(min_length=1, max_length=32)
    semantic_extent_authority: Literal[False] = False
    canonical_write_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_seed_identity(self) -> Self:
        """Require one explicit sample per object and no reused observation identity."""
        for field in ("object_id", "observation_id"):
            values = [getattr(item, field) for item in self.seeds]
            if len(values) != len(set(values)):
                raise ValueError(f"reference segmentation repeats {field}")
        return self


class ReferenceMaskLabelObservationV02(FidelityModel):
    """Bind one sure foreground/background region to an independent reference observation."""

    observation_id: StableId
    bbox_norm: Region
    label: Literal["foreground", "background"]
    confidence: float = Field(ge=0.5, le=1)

    @model_validator(mode="after")
    def validate_region(self) -> Self:
        """Reject empty or inverted segmentation label regions."""
        x0, y0, x1, y1 = self.bbox_norm
        if x0 >= x1 or y0 >= y1:
            raise ValueError("reference label observation must have positive area")
        return self


class ReferenceMaskSeedEvidenceV02(ReferenceMaskSeedEvidenceV01):
    """Select bounded, source-observed trimap constraints without changing V0.1 behavior."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    profile_status: Literal["disabled_experimental"] = "disabled_experimental"
    trimap: FidelityArtifact
    reference_resolution: tuple[
        Annotated[int, Field(ge=1, le=4096)], Annotated[int, Field(ge=1, le=4096)]
    ]
    reference_content_scope: Literal["full_reference", "primary_object_only"]
    subject_object_ids: list[StableId] = Field(max_length=256)
    label_observations: list[ReferenceMaskLabelObservationV02] = Field(min_length=2, max_length=64)
    label_encoding: Literal["bg0_probable_bg85_probable_fg170_fg255"] = (
        "bg0_probable_bg85_probable_fg170_fg255"
    )
    constraint_origin: Literal["observed_reference"] = "observed_reference"
    candidate_or_render_derived: Literal[False] = False
    human_approval_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_constraints(self) -> Self:
        """Require explicit subject membership and both independent label classes."""
        if self.subject_object_ids != sorted(set(self.subject_object_ids)):
            raise ValueError("trimap subject IDs must be uniquely sorted")
        if (self.reference_content_scope == "primary_object_only") != bool(self.subject_object_ids):
            raise ValueError("trimap subject IDs must match the selected content scope")
        ids = [item.observation_id for item in self.label_observations]
        if len(ids) != len(set(ids)):
            raise ValueError("trimap repeats an observed label identity")
        if {item.label for item in self.label_observations} != {"foreground", "background"}:
            raise ValueError("trimap requires observed foreground and background labels")
        if self.trimap.path == self.reference.path:
            raise ValueError("trimap cannot replace the original reference")
        return self


ReferenceMaskSeedEvidence = Annotated[
    ReferenceMaskSeedEvidenceV01 | ReferenceMaskSeedEvidenceV02,
    Field(discriminator="schema_version"),
]


def parse_reference_mask_seed_evidence(
    evidence: ReferenceMaskSeedEvidenceV01 | ReferenceMaskSeedEvidenceV02,
) -> ReferenceMaskSeedEvidenceV01 | ReferenceMaskSeedEvidenceV02:
    """Revalidate the exact selected companion version, including model-copy mutations."""
    return TypeAdapter(ReferenceMaskSeedEvidence).validate_json(evidence.model_dump_json())


class DirectionalMappingEvidenceV01(FidelityModel):
    """Bind image-plane coordinate coverage to exact texture and geometry evidence."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["directional_mapping_evidence"] = "directional_mapping_evidence"
    job_id: JobId
    mapping_id: StableId
    texture_manifest: FidelityArtifact
    coordinate_binding: FidelityArtifact
    coordinate_domain: Literal["uv", "normalized_generated", "object_m", "world_m"]
    coordinate_extent: tuple[
        Annotated[float, Field(gt=0, le=1000000)],
        Annotated[float, Field(gt=0, le=1000000)],
    ]
    runtime_mapping_scale: tuple[
        Annotated[float, Field(gt=0, le=1000000)],
        Annotated[float, Field(gt=0, le=1000000)],
    ]
    sampled_tile_span: float = Field(gt=0, le=1000000)
    measurement_basis: Literal["image_plane_coordinate_extent_times_runtime_mapping_scale"] = (
        "image_plane_coordinate_extent_times_runtime_mapping_scale"
    )
    limitations: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_sampled_span(self) -> Self:
        """Reject a declared span that differs from the conservative mapped extent."""

        expected = round(
            min(
                extent * scale
                for extent, scale in zip(
                    self.coordinate_extent,
                    self.runtime_mapping_scale,
                    strict=True,
                )
            ),
            9,
        )
        if abs(self.sampled_tile_span - expected) > 1.0e-9:
            raise ValueError("sampled_tile_span differs from coordinate extent times runtime scale")
        return self


class DirectionalTextureThresholdsV01(FidelityModel):
    """Freeze conservative tile checks that precede, but never replace, visual review."""

    minimum_gradient_energy: float = Field(default=0.001, ge=0, le=1)
    minimum_anisotropy: float = Field(default=0.15, ge=0, le=1)
    maximum_dominant_harmonic_fraction: float = Field(default=0.80, ge=0, le=1)
    minimum_sampled_tile_span: float = Field(default=0.75, gt=0, le=1024)


class DirectionalMaterialPreflightV01(FidelityModel):
    """Reject empty, misdirected, single-period, or under-sampled directional tiles."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["directional_material_preflight"] = "directional_material_preflight"
    job_id: JobId
    preflight_id: StableId
    image: FidelityArtifact
    mapping_evidence: FidelityArtifact
    expected_fibre_axis: Literal["x", "y"]
    coordinate_domain: Literal["uv", "normalized_generated", "object_m", "world_m"]
    sampled_tile_span: float = Field(gt=0, le=1024)
    sampled_resolution: tuple[int, int]
    thresholds: DirectionalTextureThresholdsV01
    gradient_x: Unit
    gradient_y: Unit
    anisotropy: Unit
    detected_fibre_axis: Literal["x", "y", "ambiguous", "none"]
    dominant_harmonic_fraction: Unit
    finding_codes: list[
        Literal[
            "insufficient_spatial_variation",
            "direction_ambiguous",
            "direction_mismatch",
            "single_period_dominance",
            "insufficient_sampled_span",
        ]
    ] = Field(default_factory=list)
    outcome: Literal["preflight_passed", "review_required"]
    reference_similarity_evaluated: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    canonical_write_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_classification(self) -> Self:
        """Recompute every bounded classification from the stored deterministic metrics."""

        if min(self.sampled_resolution) < 8 or max(self.sampled_resolution) > 256:
            raise ValueError("directional preflight sample must remain in [8, 256]")
        expected: list[str] = []
        total = self.gradient_x + self.gradient_y
        if total < self.thresholds.minimum_gradient_energy:
            expected.append("insufficient_spatial_variation")
            detected = "none"
        elif self.anisotropy < self.thresholds.minimum_anisotropy:
            expected.append("direction_ambiguous")
            detected = "ambiguous"
        else:
            detected = "x" if self.gradient_x < self.gradient_y else "y"
            if detected != self.expected_fibre_axis:
                expected.append("direction_mismatch")
        if self.dominant_harmonic_fraction > self.thresholds.maximum_dominant_harmonic_fraction:
            expected.append("single_period_dominance")
        if self.sampled_tile_span < self.thresholds.minimum_sampled_tile_span:
            expected.append("insufficient_sampled_span")
        if self.detected_fibre_axis != detected:
            raise ValueError("stored directional classification differs from its metrics")
        if self.finding_codes != expected:
            raise ValueError("stored directional findings differ from their thresholds")
        if (self.outcome == "preflight_passed") != (not expected):
            raise ValueError("directional preflight outcome contradicts its findings")
        return self


class DevelopmentPreviewBudgetExtensionV01(FidelityModel):
    """Bind one non-resetting two-slot lab extension to one exact staged candidate."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_development_preview_budget_extension"] = (
        "fidelity_development_preview_budget_extension"
    )
    extension_id: StableId
    job_id: JobId
    source: FidelityArtifact
    source_dependencies: list[FidelityArtifact] | None = Field(default=None, max_length=1024)
    build_fingerprint: Sha256 | None = None
    implementation_fingerprint: Sha256 | None = None
    blender_executable_sha256: Sha256 | None = None
    blender_version: Literal["5.0.1"] | None = None
    primary_run_id: StableId
    retry_run_id: StableId
    purpose: Literal[
        "directional_wood_material_correction",
        "reference_fidelity_structural_correction",
    ]
    execution_request_basis: Literal[
        "current_task_explicit_bounded_execution",
        "exact_scope_sha256_user_approval",
    ]
    base_attempt_limit: Literal[6] = 6
    additional_attempt_limit: Literal[2] = 2
    primary_attempts: Literal[1] = 1
    maximum_identical_input_technical_retries: Literal[1] = 1
    scope_sha256: Sha256
    resets_existing_budget: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    package_acceptance_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    campaign_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_scope(self) -> Self:
        """Reject run aliasing or mutations that do not match the embedded scope digest."""

        from ..blender_artifacts import stable_json_digest

        if self.primary_run_id == self.retry_run_id:
            raise ValueError("primary and technical-retry run IDs must differ")
        required_basis = {
            "directional_wood_material_correction": ("current_task_explicit_bounded_execution"),
            "reference_fidelity_structural_correction": ("exact_scope_sha256_user_approval"),
        }[self.purpose]
        if self.execution_request_basis != required_basis:
            raise ValueError("development preview purpose and approval basis differ")
        runtime_bindings = (
            self.build_fingerprint,
            self.implementation_fingerprint,
            self.blender_executable_sha256,
            self.blender_version,
        )
        if self.purpose == "directional_wood_material_correction":
            if self.source_dependencies is not None or any(
                value is not None for value in runtime_bindings
            ):
                raise ValueError("historical wood extension cannot add generic exact bindings")
        elif self.source_dependencies is None or any(
            value is None for value in runtime_bindings
        ):
            raise ValueError(
                "reference-fidelity extension requires source and runtime bindings"
            )
        payload = self.model_dump(
            mode="json",
            exclude={"scope_sha256"},
            exclude_none=True,
        )
        if stable_json_digest(payload) != self.scope_sha256:
            raise ValueError("development preview extension scope digest differs")
        return self


class DevelopmentPreviewBudgetExtensionV02(FidelityModel):
    """Bind one approved strategy-switch pair after the first extension primary completed."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    contract_kind: Literal["fidelity_development_preview_budget_extension"] = (
        "fidelity_development_preview_budget_extension"
    )
    extension_id: StableId
    extension_index: Literal[1] = 1
    job_id: JobId
    prior_extension: FidelityArtifact
    prior_primary_outcome: FidelityArtifact
    source: FidelityArtifact
    source_dependencies: list[FidelityArtifact] = Field(max_length=1024)
    build_fingerprint: Sha256
    implementation_fingerprint: Sha256
    blender_executable_sha256: Sha256
    blender_version: Literal["5.0.1"] = "5.0.1"
    primary_run_id: StableId
    retry_run_id: StableId
    purpose: Literal["material_strategy_switch"]
    execution_request_basis: Literal["exact_scope_sha256_user_approval"]
    prior_authorized_attempt_limit: Literal[8] = 8
    prior_reserved_attempt_count: Literal[7] = 7
    additional_attempt_limit: Literal[2] = 2
    cumulative_authorized_attempt_limit: Literal[10] = 10
    closed_prior_retry_slots: Literal[1] = 1
    maximum_total_reservations: Literal[9] = 9
    reclaims_closed_retry_slot: Literal[False] = False
    primary_attempts: Literal[1] = 1
    maximum_identical_input_technical_retries: Literal[1] = 1
    scope_sha256: Sha256
    resets_existing_budget: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    package_acceptance_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    campaign_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_scope(self) -> Self:
        """Reject aliased runs or any mutation outside the exact proposed scope."""

        from ..blender_artifacts import stable_json_digest

        if self.primary_run_id == self.retry_run_id:
            raise ValueError("primary and technical-retry run IDs must differ")
        if self.prior_extension == self.prior_primary_outcome:
            raise ValueError("prior extension and outcome evidence must differ")
        dependency_paths = [item.path for item in self.source_dependencies]
        if dependency_paths != sorted(set(dependency_paths)):
            raise ValueError("strategy-switch source dependencies must be unique and sorted")
        if self.source.path in dependency_paths:
            raise ValueError("strategy-switch dependencies must not duplicate the SceneSpec")
        payload = self.model_dump(mode="json", exclude={"scope_sha256"})
        if stable_json_digest(payload) != self.scope_sha256:
            raise ValueError("strategy-switch preview extension scope digest differs")
        return self


class DevelopmentPreviewBudgetExtensionV03(FidelityModel):
    """Bind one reviewed structural/material correction after the strategy preview closes."""

    schema_version: Literal["0.3.0"] = "0.3.0"
    contract_kind: Literal["fidelity_development_preview_budget_extension"] = (
        "fidelity_development_preview_budget_extension"
    )
    extension_id: StableId
    extension_index: Literal[2] = 2
    job_id: JobId
    prior_extension: FidelityArtifact
    prior_primary_outcome: FidelityArtifact
    source: FidelityArtifact
    source_dependencies: list[FidelityArtifact] = Field(max_length=1024)
    build_fingerprint: Sha256
    implementation_fingerprint: Sha256
    blender_executable_sha256: Sha256
    blender_version: Literal["5.0.1"] = "5.0.1"
    primary_run_id: StableId
    retry_run_id: StableId
    purpose: Literal["structural_material_correction"]
    execution_request_basis: Literal["exact_scope_sha256_user_approval"]
    prior_authorized_attempt_limit: Literal[10] = 10
    prior_reserved_attempt_count: Literal[8] = 8
    additional_attempt_limit: Literal[2] = 2
    cumulative_authorized_attempt_limit: Literal[12] = 12
    closed_prior_retry_slots: Literal[2] = 2
    maximum_total_reservations: Literal[10] = 10
    reclaims_closed_retry_slot: Literal[False] = False
    primary_attempts: Literal[1] = 1
    maximum_identical_input_technical_retries: Literal[1] = 1
    scope_sha256: Sha256
    resets_existing_budget: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    package_acceptance_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    campaign_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_scope(self) -> Self:
        """Reject aliased runs, unordered dependencies, or mutation of the approved scope."""

        from ..blender_artifacts import stable_json_digest

        if self.primary_run_id == self.retry_run_id:
            raise ValueError("primary and technical-retry run IDs must differ")
        if self.prior_extension == self.prior_primary_outcome:
            raise ValueError("prior extension and outcome evidence must differ")
        dependency_paths = [item.path for item in self.source_dependencies]
        if dependency_paths != sorted(set(dependency_paths)):
            raise ValueError("correction source dependencies must be unique and sorted")
        if self.source.path in dependency_paths:
            raise ValueError("correction dependencies must not duplicate the SceneSpec")
        payload = self.model_dump(mode="json", exclude={"scope_sha256"})
        if stable_json_digest(payload) != self.scope_sha256:
            raise ValueError("correction preview extension scope digest differs")
        return self


class UVSpatialPreservationV01(FidelityModel):
    """Prove that a material-only candidate preserves the bound spatial geometry."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_uv_spatial_preservation"] = "fidelity_uv_spatial_preservation"
    job_id: JobId
    source_scene: FidelityArtifact
    candidate_scene: FidelityArtifact
    source_mesh: FidelityArtifact
    candidate_mesh: FidelityArtifact
    source_vertex_count: int = Field(gt=0)
    candidate_vertex_count: int = Field(gt=0)
    seam_duplicate_count: int = Field(ge=0)
    uv_representation: Literal["polygon_corner_mesh_payload_v02"]
    loop_uv_count_matches: Literal[True]
    closed_two_manifold: Literal[True]
    bounds_equal: Literal[True]
    zero_area_face_count: Literal[0]
    source_side_faces_equal: Literal[True]
    cap_retriangulation_preserves_surface: Literal[True]
    exact_topology_preserved: Literal[True]
    original_positions_equal: Literal[True]
    duplicates_match_source_positions: Literal[True]
    faces_equal_after_seam_collapse: Literal[True]
    object_pose_equal: Literal[True]
    camera_equal: Literal[True]
    reference_sources_equal: Literal[True]
    spatial_geometry_preserved: Literal[True]
    canonical_write_performed: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        """Reject count evidence that contradicts a topology-preserving UV candidate."""

        if self.source_vertex_count != self.candidate_vertex_count:
            raise ValueError("material-only UV preservation changed the vertex count")
        if self.seam_duplicate_count != 0:
            raise ValueError("polygon-corner UV preservation cannot introduce seam vertices")
        return self


class DevelopmentPreviewBudgetExtensionV04(FidelityModel):
    """Bind one material-only refinement to the exact unresolved visual finding."""

    schema_version: Literal["0.4.0"] = "0.4.0"
    contract_kind: Literal["fidelity_development_preview_budget_extension"] = (
        "fidelity_development_preview_budget_extension"
    )
    extension_id: StableId
    extension_index: Literal[3] = 3
    job_id: JobId
    prior_extension: FidelityArtifact
    prior_primary_outcome: FidelityArtifact
    prior_visual_findings: FidelityArtifact
    prior_evaluation: FidelityArtifact
    prior_spatial_preservation: FidelityArtifact
    source: FidelityArtifact
    source_dependencies: list[FidelityArtifact] = Field(max_length=1024)
    source_spatial_preservation: FidelityArtifact
    revision_route: Literal["material_revision"] = "material_revision"
    build_fingerprint: Sha256
    implementation_fingerprint: Sha256
    blender_executable_sha256: Sha256
    blender_version: Literal["5.0.1"] = "5.0.1"
    primary_run_id: StableId
    retry_run_id: StableId
    purpose: Literal["material_fidelity_refinement"]
    execution_request_basis: Literal["exact_scope_sha256_user_approval"]
    prior_authorized_attempt_limit: Literal[12] = 12
    prior_reserved_attempt_count: Literal[9] = 9
    additional_attempt_limit: Literal[2] = 2
    cumulative_authorized_attempt_limit: Literal[14] = 14
    closed_prior_retry_slots: Literal[3] = 3
    maximum_total_reservations: Literal[11] = 11
    reclaims_closed_retry_slot: Literal[False] = False
    primary_attempts: Literal[1] = 1
    maximum_identical_input_technical_retries: Literal[1] = 1
    scope_sha256: Sha256
    resets_existing_budget: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    package_acceptance_authority: Literal[False] = False
    activation_authority: Literal[False] = False
    campaign_evidence: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_scope(self) -> Self:
        """Reject aliasing, unordered dependencies, or mutation of the review-bound scope."""

        from ..blender_artifacts import stable_json_digest

        if self.primary_run_id == self.retry_run_id:
            raise ValueError("primary and technical-retry run IDs must differ")
        bound_paths = {
            self.prior_extension.path,
            self.prior_primary_outcome.path,
            self.prior_visual_findings.path,
            self.prior_evaluation.path,
            self.prior_spatial_preservation.path,
            self.source.path,
            self.source_spatial_preservation.path,
        }
        if len(bound_paths) != 7:
            raise ValueError("material-refinement evidence paths must be distinct")
        dependency_paths = [item.path for item in self.source_dependencies]
        if dependency_paths != sorted(set(dependency_paths)):
            raise ValueError("material-refinement dependencies must be unique and sorted")
        if self.source.path in dependency_paths:
            raise ValueError("material-refinement dependencies must not duplicate the SceneSpec")
        payload = self.model_dump(mode="json", exclude={"scope_sha256"})
        if stable_json_digest(payload) != self.scope_sha256:
            raise ValueError("material-refinement preview extension scope digest differs")
        return self


class DevelopmentPreviewAttemptOutcomeV01(FidelityModel):
    """Close one reserved lab attempt as completed or as an exact-input technical failure."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["fidelity_development_preview_attempt_outcome"] = (
        "fidelity_development_preview_attempt_outcome"
    )
    job_id: JobId
    attempt_index: int = Field(ge=0, le=7)
    run_id: StableId
    source: FidelityArtifact
    outcome: Literal["completed", "technical_failure"]
    result: FidelityArtifact | None = None
    error_type: str | None = Field(default=None, min_length=1, max_length=128)
    error_message: str | None = Field(default=None, min_length=1, max_length=2048)
    scope_sha256: Sha256
    canonical_write_authority: Literal[False] = False
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    activation_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_outcome_scope(self) -> Self:
        """Require role-correct evidence and detect accidental outcome-file mutation."""

        from ..blender_artifacts import stable_json_digest

        completed = self.outcome == "completed"
        if completed != (self.result is not None):
            raise ValueError("completed preview outcome requires exactly one result artifact")
        if completed and (self.error_type is not None or self.error_message is not None):
            raise ValueError("completed preview outcome cannot contain an error")
        if not completed and (self.error_type is None or self.error_message is None):
            raise ValueError("technical failure requires bounded error evidence")
        payload = self.model_dump(mode="json", exclude={"scope_sha256"})
        if stable_json_digest(payload) != self.scope_sha256:
            raise ValueError("development preview outcome scope digest differs")
        return self


class DevelopmentPreviewAttemptOutcomeV02(DevelopmentPreviewAttemptOutcomeV01):
    """Close an attempt beyond the original eight-slot development-preview contract."""

    schema_version: Literal["0.2.0"] = "0.2.0"
    attempt_index: int = Field(ge=8, le=9)


class DevelopmentPreviewAttemptOutcomeV03(DevelopmentPreviewAttemptOutcomeV01):
    """Close the final technical retry added by the material-refinement extension."""

    schema_version: Literal["0.3.0"] = "0.3.0"
    attempt_index: Literal[10]


class ReferenceObservation(FidelityModel):
    """Record image observations independently of a generated candidate's geometry."""

    observation_id: StableId
    region: Region
    description: str = Field(min_length=8, max_length=2048)
    status: Literal["observed", "inferred"]
    confidence: Unit
    landmarks: dict[StableId, Point] = Field(default_factory=dict)
    uncertainty: str = Field(min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_region(self) -> Self:
        """Require a positive image region and landmarks inside that region."""

        x0, y0, x1, y1 = self.region
        if x0 >= x1 or y0 >= y1:
            raise ValueError("observation region must have positive area")
        if any(not (x0 <= x <= x1 and y0 <= y <= y1) for x, y in self.landmarks.values()):
            raise ValueError("landmark must lie inside its observation region")
        return self


class FeatureRequirement(FidelityModel):
    """Freeze an observable criterion before candidate evaluation, including justified N/A."""

    feature_id: StableId
    observation_ids: list[StableId] = Field(min_length=1)
    target_ids: list[StableId] = Field(min_length=1)
    face_groups: list[StableId] = Field(default_factory=list)
    kind: DefectKind
    expected: str = Field(min_length=8, max_length=2048)
    comparison: str = Field(min_length=8, max_length=2048)
    required: bool = True
    applicability: Literal["applicable", "not_applicable"] = "applicable"
    applicability_reason: str | None = Field(default=None, min_length=8)
    severity: Literal["minor", "major", "critical"] = "major"
    minimum_confidence: Unit = 0.7

    @model_validator(mode="after")
    def validate_applicability(self) -> Self:
        """Require predeclared exceptions; an evaluator cannot silently waive a feature."""

        if (self.applicability == "not_applicable") != (self.applicability_reason is not None):
            raise ValueError("not_applicable requires an explicit predeclared reason")
        for values in (self.observation_ids, self.target_ids, self.face_groups):
            if len(values) != len(set(values)):
                raise ValueError("requirement bindings must be unique")
        return self


class CameraHypothesis(FidelityModel):
    """Distinguish measured calibration from a chosen underconstrained viewing hypothesis."""

    camera_fingerprint: Sha256
    origin: Literal["default_hypothesis", "visual_hypothesis", "line_fit", "measured"]
    evidence_observation_ids: list[StableId] = Field(min_length=1)
    rationale: str = Field(min_length=8)
    uncertainty: str = Field(min_length=8)
    hidden_surfaces_recovered: Literal[False] = False


class ModelingHypothesisV01(FidelityModel):
    """Describe the 3D hypothesis without changing SceneSpec 0.2 or ModelingPlan 0.4."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["modeling_hypothesis"] = "modeling_hypothesis"
    job_id: JobId
    hypothesis_id: StableId
    reference: FidelityArtifact
    observations: list[ReferenceObservation] = Field(min_length=1, max_length=128)
    requirements: list[FeatureRequirement] = Field(min_length=1, max_length=128)
    camera: CameraHypothesis
    representation: Literal["solid", "shell", "sheet", "assembly"]
    volume_and_sections: str = Field(min_length=8)
    part_relations: str = Field(min_length=8)
    hidden_geometry_assumptions: list[str] = Field(min_length=1)
    authoring_strategy: StableId
    reference_mask_seed_evidence: ReferenceMaskSeedEvidence | None = None
    reference_derived_from_candidate: Literal[False] = False
    canonical_write_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_observation_coverage(self) -> Self:
        """Require unique, independent observation bindings for every expected feature."""

        observed = {item.observation_id: item for item in self.observations}
        if len(observed) != len(self.observations):
            raise ValueError("observation IDs must be unique")
        if len({item.feature_id for item in self.requirements}) != len(self.requirements):
            raise ValueError("feature IDs must be unique")
        for item in self.requirements:
            if not set(item.observation_ids) <= observed.keys():
                raise ValueError("requirement names an unknown observation")
            if item.required and item.applicability == "applicable":
                if not any(observed[key].status == "observed" for key in item.observation_ids):
                    raise ValueError(
                        "required reference match needs an observed, not hidden, feature"
                    )
        if not set(self.camera.evidence_observation_ids) <= observed.keys():
            raise ValueError("camera names an unknown observation")
        if not any(item.status == "observed" for item in self.observations):
            raise ValueError("a reference hypothesis needs observed evidence")
        if self.reference_mask_seed_evidence is not None:
            seed_evidence = self.reference_mask_seed_evidence
            if seed_evidence.job_id != self.job_id or seed_evidence.reference != self.reference:
                raise ValueError("segmentation seed evidence binds another job or reference")
            for seed in seed_evidence.seeds:
                observation = observed.get(seed.observation_id)
                if (
                    observation is None or observation.status != "observed"
                    or observation.region != seed.bbox_norm
                    or observation.confidence != seed.confidence
                ):
                    raise ValueError("segmentation seed must match an exact observed region")
            if isinstance(seed_evidence, ReferenceMaskSeedEvidenceV02):
                for label in seed_evidence.label_observations:
                    observation = observed.get(label.observation_id)
                    if (
                        observation is None or observation.status != "observed"
                        or observation.region != label.bbox_norm
                        or observation.confidence != label.confidence
                    ):
                        raise ValueError("trimap label must match an exact observed region")
        return self


class BuildSourceSnapshotV01(FidelityModel):
    """Keep mutable material/plan inputs readable after later canonical promotions."""

    provenance: FidelityArtifact
    files: dict[RelativePath, FidelityArtifact]
    supplemental_scene_materials: dict[RelativePath, FidelityArtifact] = Field(default_factory=dict)
    supplemental_meaning: Literal["captured_source_not_legacy_build_fingerprint"] = (
        "captured_source_not_legacy_build_fingerprint"
    )


class RenderEvidenceV01(FidelityModel):
    """Bind all seven actual V0.6 passes and immutable source snapshots for one comparison."""

    scene_spec: FidelityArtifact
    geometry_payloads: list[FidelityArtifact] = Field(default_factory=list)
    geometry_snapshots: dict[RelativePath, FidelityArtifact] = Field(default_factory=dict)
    qa_request: FidelityArtifact
    qa_report: FidelityArtifact
    pass_manifest: FidelityArtifact
    camera_fingerprint: Sha256
    build_fingerprint: Sha256
    build_sources: BuildSourceSnapshotV01 | None = None
    comparison_conditions: FidelityArtifact | None = None
    render_engine: str = Field(min_length=1)
    resolution: tuple[int, int]
    passes: dict[
        Literal[
            "beauty",
            "silhouette",
            "object_id",
            "material_id",
            "normal",
            "depth",
            "wireframe",
        ],
        FidelityArtifact,
    ]
    auxiliary_views: list[FidelityArtifact] = Field(default_factory=list, max_length=8)
    auxiliary_view_meaning: Literal["candidate_consistency_only"] = "candidate_consistency_only"

    @model_validator(mode="after")
    def validate_passes(self) -> Self:
        """Require actual canonical passes; extra views never impersonate reference truth."""

        from ..qa.models import REQUIRED_QA_PASS_KINDS

        if set(self.passes) != set(REQUIRED_QA_PASS_KINDS):
            raise ValueError("reference fidelity requires all seven exact V0.6 passes")
        if min(self.resolution) <= 0:
            raise ValueError("resolution must be positive")
        return self


class FeatureAssessment(FidelityModel):
    """Record one nonhuman visual judgment, not an approval or arbitrary numeric score."""

    feature_id: StableId
    outcome: Literal["satisfied", "defect", "unscorable", "not_applicable"]
    actual: str = Field(min_length=8, max_length=2048)
    confidence: Unit
    evidence_passes: list[
        Literal[
            "beauty",
            "silhouette",
            "object_id",
            "material_id",
            "normal",
            "depth",
            "wireframe",
        ]
    ] = Field(min_length=1)
    candidate_region: Region

    @model_validator(mode="after")
    def validate_region(self) -> Self:
        """Reject empty or repeated evidence and inverted candidate image regions."""

        x0, y0, x1, y1 = self.candidate_region
        if x0 >= x1 or y0 >= y1:
            raise ValueError("candidate region must have positive area")
        if len(self.evidence_passes) != len(set(self.evidence_passes)):
            raise ValueError("evidence passes must be unique")
        return self


class VisualFindingSetV01(FidelityModel):
    """Source-bound Codex visual judgments consumed by the host's separate quality gate."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["visual_finding_set"] = "visual_finding_set"
    job_id: JobId
    review_id: StableId
    hypothesis: FidelityArtifact
    reference: FidelityArtifact
    evidence: RenderEvidenceV01
    assessments: list[FeatureAssessment] = Field(default_factory=list, max_length=128)
    producer: Literal["codex_visual_adviser"] = "codex_visual_adviser"
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_unique_assessments(self) -> Self:
        """Prevent duplicate ratings from hiding a missing expected observation."""

        if len({item.feature_id for item in self.assessments}) != len(self.assessments):
            raise ValueError("feature assessments must be unique")
        return self


class RoutedFindingV01(FidelityModel):
    """Convert a concrete defect or missing expected item into the appropriate host route."""

    feature_id: StableId
    target_ids: list[StableId]
    face_groups: list[StableId]
    observation_ids: list[StableId]
    kind: DefectKind
    severity: Literal["minor", "major", "critical"]
    expected: str
    actual: str
    comparison: str
    route: RevisionRoute


class FidelityEvaluationV01(FidelityModel):
    """Keep technical score, observable fidelity, and human disposition separate."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["reference_fidelity_evaluation"] = "reference_fidelity_evaluation"
    hypothesis: FidelityArtifact
    visual_review: FidelityArtifact
    legacy_direct_score: Unit
    required_features: int = Field(ge=0)
    satisfied_features: int = Field(ge=0)
    findings: list[RoutedFindingV01]
    outcome: Literal["visually_satisfied", "needs_revision", "unscorable"]
    next_action: RevisionRoute
    human_quality_disposition: Literal["not_recorded"] = "not_recorded"
    is_promotion_authority: Literal[False] = False


class FidelityComparisonV01(FidelityModel):
    """Record exact paired improvement, not a render count or added-detail proxy."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    before: FidelityArtifact
    after: FidelityArtifact
    resolved_features: list[StableId]
    regressed_features: list[StableId]
    unresolved_major_features: list[StableId]
    direct_score_delta: float
    outcome: Literal["improved", "partially_improved", "regressed", "unchanged", "incomparable"]
    reason: str
    is_human_acceptance: Literal[False] = False
