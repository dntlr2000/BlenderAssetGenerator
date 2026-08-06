"""Strict V0.7 contracts for portable static-asset optimization."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.7.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
STABLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
JOB_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
JOB_RELATIVE_SCHEMA_PATTERN = (
    r"^(?!/)(?![A-Za-z]:)(?!.*:)(?!.*(?:^|/)\.\.(?:/|$))(?!.*\\)(?!.*//)"
    r"[^\u0000]+$"
)


def _validate_job_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by its owning job workspace."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty POSIX job-relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be job-relative, not absolute")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
StableId = Annotated[str, Field(pattern=STABLE_ID_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
JobRelativePath = Annotated[
    str,
    Field(
        min_length=1,
        json_schema_extra={"pattern": JOB_RELATIVE_SCHEMA_PATTERN},
    ),
    AfterValidator(_validate_job_relative_path),
]
PortableProfile = Literal["portable_gltf", "fbx_interchange", "obj_legacy"]
ArtifactStatus = Literal["planned", "complete", "failed"]
QualityStatus = Literal["verified", "partially_verified", "unverified"]
Vec3 = tuple[float, float, float]
PortableMaterialChannel = Literal[
    "base_color", "roughness", "metallic", "normal", "emission"
]
PORTABLE_MATERIAL_CHANNELS = (
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "emission",
)
PositivePixel = Annotated[int, Field(ge=1, le=8192)]
PixelResolution = tuple[PositivePixel, PositivePixel]
UnitFloat = Annotated[float, Field(ge=0, le=1)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
UVPoint = tuple[UnitFloat, UnitFloat]


class V07StrictModel(BaseModel):
    """Reject undeclared fields and non-finite floats in V0.7 contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HashedArtifact(V07StrictModel):
    """Bind one stable artifact identity to a job-relative path and SHA-256 digest."""

    id: StableId
    kind: Literal[
        "scene_spec",
        "external_asset_manifest",
        "external_source",
        "external_dependency",
        "external_intake_plan",
        "external_intake_approval",
        "external_normalization_evidence",
        "blend",
        "geometry_payload",
        "material_plan",
        "texture_manifest",
        "asset_profile",
        "optimization_plan",
        "preflight_report",
        "lod_manifest",
        "collision_manifest",
        "uv_manifest",
        "asset_cost_report",
        "texture_pack_manifest",
        "lod_mesh",
        "collider_mesh",
        "uv_preview",
        "packed_texture",
        "package_manifest",
        "package_file",
        "roundtrip_inventory",
        "other",
    ]
    path: JobRelativePath
    sha256: Sha256


class SourceProvenance(V07StrictModel):
    """Freeze canonical geometry, build, material, and texture inputs for one V0.7 run."""

    source_kind: Literal["scene_spec", "external_static_asset"] = "scene_spec"
    scene_spec: HashedArtifact | None = None
    external_asset_manifest: HashedArtifact | None = None
    external_source_artifacts: list[HashedArtifact] = Field(default_factory=list)
    blend: HashedArtifact
    source_fingerprint: Sha256
    build_fingerprint: Sha256
    geometry_payloads: list[HashedArtifact] = Field(default_factory=list)
    material_plan: HashedArtifact | None = None
    texture_manifests: list[HashedArtifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_provenance(self) -> SourceProvenance:
        """Require role-correct, uniquely identified provenance artifacts."""

        if self.source_kind == "scene_spec":
            if self.scene_spec is None or self.scene_spec.kind != "scene_spec":
                raise ValueError("scene_spec source provenance requires kind=scene_spec")
            if self.external_asset_manifest is not None or self.external_source_artifacts:
                raise ValueError("scene_spec provenance cannot contain external source artifacts")
        else:
            if self.scene_spec is not None:
                raise ValueError("external source provenance cannot contain a SceneSpec")
            if (
                self.external_asset_manifest is None
                or self.external_asset_manifest.kind != "external_asset_manifest"
            ):
                raise ValueError(
                    "external source provenance requires kind=external_asset_manifest"
                )
            allowed_external_kinds = {
                "external_source",
                "external_dependency",
                "external_intake_plan",
                "external_intake_approval",
                "external_normalization_evidence",
            }
            if any(
                item.kind not in allowed_external_kinds
                for item in self.external_source_artifacts
            ):
                raise ValueError("external provenance contains an invalid source artifact kind")
        if self.blend.kind != "blend":
            raise ValueError("blend provenance artifact must use kind=blend")
        if any(item.kind != "geometry_payload" for item in self.geometry_payloads):
            raise ValueError("geometry payload provenance must use kind=geometry_payload")
        if self.material_plan is not None and self.material_plan.kind != "material_plan":
            raise ValueError("material_plan provenance artifact must use kind=material_plan")
        if any(item.kind != "texture_manifest" for item in self.texture_manifests):
            raise ValueError("texture manifest provenance must use kind=texture_manifest")
        artifacts = self.artifacts()
        ids = [item.id for item in artifacts]
        paths = [item.path for item in artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("provenance artifact IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("provenance artifact paths must be unique")
        return self

    def artifacts(self) -> list[HashedArtifact]:
        """Return every provenance artifact in stable source-role order."""

        artifacts: list[HashedArtifact] = []
        if self.scene_spec is not None:
            artifacts.append(self.scene_spec)
        if self.external_asset_manifest is not None:
            artifacts.append(self.external_asset_manifest)
        artifacts.extend(self.external_source_artifacts)
        artifacts.extend([self.blend, *self.geometry_payloads, *self.texture_manifests])
        if self.material_plan is not None:
            artifacts.append(self.material_plan)
        return artifacts


class Bounds3D(V07StrictModel):
    """Store one finite axis-aligned bounding box in meters."""

    minimum: Vec3
    maximum: Vec3

    @model_validator(mode="after")
    def validate_extents(self) -> Bounds3D:
        """Reject bounds whose maximum lies below their minimum on any axis."""

        if any(high < low for low, high in zip(self.minimum, self.maximum, strict=True)):
            raise ValueError("bounds maximum must be greater than or equal to minimum")
        return self


class LODTarget(V07StrictModel):
    """Define one derived LOD ratio and its minimum silhouette preservation target."""

    level: int = Field(ge=1, le=8)
    target_triangle_ratio: float = Field(gt=0, lt=1)
    minimum_silhouette_iou: float = Field(ge=0, le=1)


class LODPolicy(V07StrictModel):
    """Control immutable-LOD0 preservation and optional derived LOD generation."""

    enabled: bool = True
    preserve_lod0: Literal[True] = True
    targets: list[LODTarget] = Field(
        default_factory=lambda: [
            LODTarget(level=1, target_triangle_ratio=0.6, minimum_silhouette_iou=0.98),
            LODTarget(level=2, target_triangle_ratio=0.3, minimum_silhouette_iou=0.95),
        ]
    )

    @model_validator(mode="after")
    def validate_targets(self) -> LODPolicy:
        """Require ordered unique LOD levels only while derived LOD generation is enabled."""

        levels = [item.level for item in self.targets]
        if len(levels) != len(set(levels)):
            raise ValueError("LOD policy levels must be unique")
        if levels != sorted(levels):
            raise ValueError("LOD policy levels must be ordered")
        if self.enabled and not self.targets:
            raise ValueError("enabled LOD policy requires at least one derived target")
        if not self.enabled and self.targets:
            raise ValueError("disabled LOD policy must not contain derived targets")
        return self


class CollisionPolicy(V07StrictModel):
    """Describe the engine-neutral collision proxy strategy and complexity budget."""

    strategy: Literal[
        "none", "box", "sphere", "capsule", "convex_hull", "compound", "mesh_proxy"
    ] = "compound"
    max_hulls_per_object: int = Field(default=8, ge=1, le=64)
    max_triangles_per_object: int = Field(default=256, ge=4)


class UVPolicy(V07StrictModel):
    """Control preservation, generation, and validation of material and lightmap UVs."""

    preserve_uv0: Literal[True] = True
    generate_uv0_if_missing: bool = True
    generate_uv1: bool = True
    maximum_overlap_fraction: float = Field(default=0.01, ge=0, le=1)
    target_texel_density_px_m: float | None = Field(default=None, gt=0)
    minimum_padding_px: int = Field(default=4, ge=0)


class TexturePolicy(V07StrictModel):
    """Preserve raw PBR channels while defining an optional portable packing layout."""

    preserve_raw_channels: Literal[True] = True
    packing: Literal["raw_channels", "gltf_orm", "none"] = "raw_channels"
    maximum_resolution: int = Field(default=4096, ge=1, le=8192)


class ConsolidationPolicy(V07StrictModel):
    """Control safe derived-object cleanup and semantic-preserving batching."""

    mode: Literal["none", "by_semantic_group", "by_spatial_cell"] = "none"
    maximum_objects_per_batch: int = Field(default=64, ge=2, le=1024)
    spatial_cell_size_m: float = Field(default=25.0, gt=0)
    remove_loose_geometry: bool = True
    deduplicate_material_slots: bool = True
    deduplicate_exact_colliders: bool = True
    detect_exact_instances: bool = True
    detect_overlap_candidates: bool = True
    overlap_pair_limit: int = Field(default=5000, ge=1, le=100000)


class CostBudgetPolicy(V07StrictModel):
    """Declare optional engine-neutral static-asset cost ceilings."""

    enforcement: Literal["warning", "fail"] = "warning"
    max_lod0_render_objects: int | None = Field(default=None, ge=1)
    max_lod0_material_slots: int | None = Field(default=None, ge=1)
    max_lod0_estimated_draw_calls: int | None = Field(default=None, ge=1)
    max_lod0_triangles: int | None = Field(default=None, ge=1)
    max_collider_triangles: int | None = Field(default=None, ge=0)
    max_overlap_candidates: int | None = Field(default=None, ge=0)


class AssetProfile(V07StrictModel):
    """Declare one engine-neutral portable static-asset target profile."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    profile_id: PortableProfile
    job_id: JobId
    asset_kind: Literal["static_prop", "static_environment", "static_architecture"]
    primary_format: Literal["glb", "fbx", "obj"]
    units: Literal["meters"] = "meters"
    up_axis: Literal["+Y"] = "+Y"
    forward_axis: Literal["-Z"] = "-Z"
    pivot_policy: Literal["keep", "bounds_center", "base_center"] = "keep"
    lod: LODPolicy = Field(default_factory=LODPolicy)
    collision: CollisionPolicy = Field(default_factory=CollisionPolicy)
    uv: UVPolicy = Field(default_factory=UVPolicy)
    textures: TexturePolicy = Field(default_factory=TexturePolicy)
    consolidation: ConsolidationPolicy = Field(default_factory=ConsolidationPolicy)
    budgets: CostBudgetPolicy = Field(default_factory=CostBudgetPolicy)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_profile_format(self) -> AssetProfile:
        """Bind each named portable profile to its unambiguous interchange format."""

        expected = {
            "portable_gltf": "glb",
            "fbx_interchange": "fbx",
            "obj_legacy": "obj",
        }[self.profile_id]
        if self.primary_format != expected:
            raise ValueError(f"profile {self.profile_id} requires primary_format={expected}")
        return self


class SourceQualitySummary(V07StrictModel):
    """Carry exact fast-preview quality warnings into the V0.7 approval boundary."""

    report_artifact: HashedArtifact
    quality_status: Literal["passed", "needs_revision", "unscorable"]
    overall_direct_score: float | None = Field(default=None, ge=0, le=1)
    primary_silhouette_score: float | None = Field(default=None, ge=0, le=1)
    primary_high_findings: list[str] = Field(default_factory=list)
    supporting_high_findings: list[str] = Field(default_factory=list)
    decorative_warnings: list[str] = Field(default_factory=list)
    environment_findings: list[str] = Field(default_factory=list)
    standard_workflow_recommended: bool
    qa_run_id: str = Field(min_length=1)
    source_fingerprint: Sha256
    build_fingerprint: Sha256
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_quality_summary(self) -> SourceQualitySummary:
        """Require a generic hashed artifact and preserve non-passing recommendations."""

        if self.report_artifact.kind != "other":
            raise ValueError("source quality report artifact must use kind=other")
        if (
            self.quality_status != "passed"
            and not self.standard_workflow_recommended
        ):
            raise ValueError("non-passing source quality must recommend standard revision")
        return self


class OptimizationDirective(V07StrictModel):
    """Apply explicit derived-asset policies to one stable semantic object family."""

    target_id: StableId
    include: bool = True
    lod_levels: list[int] = Field(default_factory=list)
    collision_strategy: Literal[
        "inherit", "none", "box", "sphere", "capsule", "convex_hull", "compound", "mesh_proxy"
    ] = "inherit"
    preserve_semantic_id: Literal[True] = True
    preserve_material_ids: Literal[True] = True
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lod_levels(self) -> OptimizationDirective:
        """Keep requested derived LOD levels positive, ordered, and unique."""

        if any(level < 1 or level > 8 for level in self.lod_levels):
            raise ValueError("directive LOD levels must be in [1, 8]")
        if self.lod_levels != sorted(set(self.lod_levels)):
            raise ValueError("directive LOD levels must be ordered and unique")
        return self


class OptimizationPlan(V07StrictModel):
    """Bind an approved derived-asset plan to immutable canonical provenance."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    plan_id: StableId
    job_id: JobId
    profile_id: PortableProfile
    profile_artifact: HashedArtifact
    preflight_report: HashedArtifact
    source: SourceProvenance
    source_quality: SourceQualitySummary | None = None
    status: Literal["draft", "approved", "running", "complete", "failed"] = "draft"
    directives: list[OptimizationDirective] = Field(default_factory=list)
    approved_at: datetime | None = None
    completed_at: datetime | None = None
    output_manifests: list[HashedArtifact] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plan(self) -> OptimizationPlan:
        """Enforce unique targets, profile provenance, and lifecycle-specific payloads."""

        if self.profile_artifact.kind != "asset_profile":
            raise ValueError("profile_artifact must use kind=asset_profile")
        if self.preflight_report.kind != "preflight_report":
            raise ValueError("preflight_report must use kind=preflight_report")
        targets = [item.target_id for item in self.directives]
        if len(targets) != len(set(targets)):
            raise ValueError("optimization directive target IDs must be unique")
        output_ids = [item.id for item in self.output_manifests]
        output_paths = [item.path for item in self.output_manifests]
        if len(output_ids) != len(set(output_ids)) or len(output_paths) != len(set(output_paths)):
            raise ValueError("optimization output manifests must have unique IDs and paths")
        if self.status == "draft":
            if self.approved_at or self.completed_at or self.output_manifests or self.errors:
                raise ValueError("draft optimization plan cannot contain execution results")
        elif self.status == "approved":
            if (
                self.approved_at is None
                or self.completed_at
                or self.output_manifests
                or self.errors
            ):
                raise ValueError("approved optimization plan requires only approved_at")
        elif self.status == "running":
            if self.approved_at is None or self.completed_at or self.errors:
                raise ValueError("running optimization plan requires approval and no completion")
        elif self.status == "complete":
            if self.approved_at is None or self.completed_at is None or not self.output_manifests:
                raise ValueError(
                    "complete optimization plan requires approval, completion, and outputs"
                )
            if self.errors:
                raise ValueError("complete optimization plan cannot contain errors")
        elif self.status == "failed":
            if self.approved_at is None or self.completed_at is None or not self.errors:
                raise ValueError(
                    "failed optimization plan requires approval, completion, and errors"
                )
        return self


class LODLevelReview(V07StrictModel):
    """Summarize one configured derived LOD level before optimization begins."""

    level: int = Field(ge=1, le=8)
    target_triangle_ratio: float = Field(gt=0, lt=1)
    minimum_silhouette_iou: float = Field(ge=0, le=1)
    estimated_triangle_ceiling: int = Field(ge=0)
    estimated_object_count: int = Field(ge=0)


class LODOptimizationReview(V07StrictModel):
    """Expose the exact profile LOD policy and its estimated derived cost."""

    enabled: bool
    preserve_lod0: Literal[True] = True
    semantic_family_count: int = Field(ge=0)
    source_object_count: int = Field(ge=0)
    source_triangle_count: int = Field(ge=0)
    levels: list[LODLevelReview] = Field(default_factory=list)
    recommendation: Literal["disabled_by_profile", "manual_review"]
    reasons: list[str] = Field(min_length=1)
    unverified_checks: list[Literal["silhouette_iou", "runtime_switching"]] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_lod_review(self) -> LODOptimizationReview:
        """Keep enabled state, configured levels, and unresolved checks consistent."""

        if self.enabled and not self.levels:
            raise ValueError("enabled LOD review requires at least one configured level")
        if not self.enabled and self.levels:
            raise ValueError("disabled LOD review cannot contain derived levels")
        if self.enabled and self.recommendation != "manual_review":
            raise ValueError("enabled engine-neutral LOD requires explicit manual review")
        if not self.enabled and self.recommendation != "disabled_by_profile":
            raise ValueError("disabled LOD review must report disabled_by_profile")
        return self


class CollisionOptimizationReview(V07StrictModel):
    """Expose the exact collider policy and its bounded pre-execution estimate."""

    strategy: Literal[
        "none", "box", "sphere", "capsule", "convex_hull", "compound", "mesh_proxy"
    ]
    semantic_family_count: int = Field(ge=0)
    source_object_count: int = Field(ge=0)
    estimated_collider_count: int = Field(ge=0)
    estimated_triangle_count: int | None = Field(default=None, ge=0)
    maximum_triangle_ceiling: int = Field(ge=0)
    max_hulls_per_object: int = Field(ge=1, le=64)
    max_triangles_per_object: int = Field(ge=4)
    include_in_package: bool
    recommendation: Literal["disabled_by_profile", "manual_review"]
    reasons: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_collision_review(self) -> CollisionOptimizationReview:
        """Keep collider counts, package behavior, and configured state consistent."""

        disabled = self.strategy == "none"
        if disabled:
            if self.estimated_collider_count or self.include_in_package:
                raise ValueError("disabled collision review cannot create or package colliders")
            if self.recommendation != "disabled_by_profile":
                raise ValueError("disabled collision review must report disabled_by_profile")
        else:
            if self.estimated_collider_count != self.source_object_count:
                raise ValueError(
                    "enabled collision review must estimate one collider per source object"
                )
            if not self.include_in_package or self.recommendation != "manual_review":
                raise ValueError("enabled collision requires package inclusion and manual review")
        return self


class OptimizationReview(V07StrictModel):
    """Present exact V0.7 LOD and collider defaults before any derived mutation."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    review_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    primary_format: Literal["glb", "fbx", "obj"]
    profile_artifact: HashedArtifact
    preflight_report: HashedArtifact
    source: SourceProvenance
    source_quality: SourceQualitySummary | None = None
    plan_sha256: Sha256
    units: Literal["meters"] = "meters"
    up_axis: Literal["+Y"] = "+Y"
    forward_axis: Literal["-Z"] = "-Z"
    pivot_policy: Literal["keep", "bounds_center", "base_center"] = "keep"
    lod: LODOptimizationReview
    collision: CollisionOptimizationReview
    consolidation_mode: Literal["none", "by_semantic_group", "by_spatial_cell"]
    consolidation: ConsolidationPolicy = Field(default_factory=ConsolidationPolicy)
    uv: UVPolicy = Field(default_factory=UVPolicy)
    textures: TexturePolicy = Field(default_factory=TexturePolicy)
    budgets: CostBudgetPolicy = Field(default_factory=CostBudgetPolicy)
    status: Literal["awaiting_user_approval"] = "awaiting_user_approval"
    decision_required: Literal[True] = True
    available_decisions: list[
        Literal["approve", "revise_asset", "revise_profile", "cancel"]
    ] = Field(
        default_factory=lambda: [
            "approve",
            "revise_asset",
            "revise_profile",
            "cancel",
        ]
    )
    recommended_decision: Literal[
        "approve", "revise_asset", "revise_profile", "cancel"
    ] | None = None
    decision_reason: str | None = Field(default=None, min_length=1, max_length=1000)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    canonical_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def validate_review(self) -> OptimizationReview:
        """Require role-correct artifacts and one complete decision menu."""

        if self.profile_artifact.kind != "asset_profile":
            raise ValueError("optimization review profile must use kind=asset_profile")
        if self.preflight_report.kind != "preflight_report":
            raise ValueError("optimization review preflight must use kind=preflight_report")
        legacy_menu = ["approve", "revise_profile", "cancel"]
        current_menu = ["approve", "revise_asset", "revise_profile", "cancel"]
        if tuple(self.available_decisions) not in {
            tuple(legacy_menu),
            tuple(current_menu),
        }:
            raise ValueError(
                "optimization review must expose a supported complete ordered decision menu"
            )
        if (
            self.recommended_decision is not None
            and self.recommended_decision not in self.available_decisions
        ):
            raise ValueError("recommended decision must be available in this review")
        if (self.recommended_decision is None) != (self.decision_reason is None):
            raise ValueError(
                "recommended decision and decision reason must be supplied together"
            )
        return self


class OptimizationApproval(V07StrictModel):
    """Record one explicit hash-bound, single-use approval for derived optimization."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    approval_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    plan_sha256: Sha256
    review_sha256: Sha256
    profile_sha256: Sha256
    preflight_sha256: Sha256
    source_fingerprint: Sha256
    approved_by: Literal["user"] = "user"
    approval_note: str = Field(min_length=1)
    approved_at: datetime
    one_time: Literal[True] = True
    used: bool = False
    used_at: datetime | None = None

    @model_validator(mode="after")
    def validate_approval_usage(self) -> OptimizationApproval:
        """Require a consumption timestamp if and only if approval was used."""

        if self.used and self.used_at is None:
            raise ValueError("used optimization approvals require used_at")
        if not self.used and self.used_at is not None:
            raise ValueError("unused optimization approvals cannot contain used_at")
        return self


class MeshPreflightCheck(V07StrictModel):
    """Record one deterministic topology, transform, normal, or UV preflight check."""

    id: StableId
    target_id: StableId | None = None
    category: Literal["topology", "transform", "normal", "tangent", "material", "uv", "budget"]
    status: Literal["passed", "warning", "failed"]
    message: str
    evidence_path: JobRelativePath | None = None


class MeshSummary(V07StrictModel):
    """Summarize one semantic mesh family before derived optimization."""

    target_id: StableId
    source_tags: list[str] | None = None
    source_renderable: bool | None = None
    object_count: int = Field(ge=1)
    vertex_count: int = Field(ge=0)
    triangle_count: int = Field(ge=0)
    boundary_edge_count: int = Field(ge=0)
    non_manifold_edge_count: int = Field(ge=0)
    degenerate_face_count: int = Field(ge=0)
    negative_scale_count: int = Field(ge=0)
    bounds: Bounds3D
    declared_exceptions: list[str] = Field(default_factory=list)


class MeshPreflightReport(V07StrictModel):
    """Summarize canonical mesh readiness without mutating the authoring master."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    report_id: StableId
    job_id: JobId
    profile_id: PortableProfile
    profile_artifact: HashedArtifact
    source: SourceProvenance
    status: Literal["passed", "failed"]
    ok: bool
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    checks: list[MeshPreflightCheck] = Field(default_factory=list)
    meshes: list[MeshSummary] = Field(default_factory=list)
    created_at: datetime
    canonical_unchanged: Literal[True] = True
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report(self) -> MeshPreflightReport:
        """Match summary counts and success state to uniquely identified check evidence."""

        if self.profile_artifact.kind != "asset_profile":
            raise ValueError("profile_artifact must use kind=asset_profile")
        check_ids = [item.id for item in self.checks]
        target_ids = [item.target_id for item in self.meshes]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("preflight check IDs must be unique")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("preflight mesh target IDs must be unique")
        counts = {
            state: sum(item.status == state for item in self.checks)
            for state in ("passed", "warning", "failed")
        }
        if (self.passed, self.warnings, self.failed) != (
            counts["passed"],
            counts["warning"],
            counts["failed"],
        ):
            raise ValueError("preflight summary counts do not match checks")
        expected_ok = self.failed == 0
        if self.ok != expected_ok or self.status != ("passed" if expected_ok else "failed"):
            raise ValueError("preflight status and ok must match failed check count")
        return self


CostMetricName = Literal[
    "lod0_render_objects",
    "lod0_material_slots",
    "lod0_estimated_draw_calls",
    "lod0_vertices",
    "lod0_triangles",
    "lod_objects",
    "collider_objects",
    "collider_triangles",
    "total_derived_triangles",
    "overlap_candidates",
]


class AssetCostSnapshot(V07StrictModel):
    """Capture deterministic derived-scene cost proxies at one pipeline boundary."""

    lod0_render_objects: int = Field(ge=0)
    lod0_material_slots: int = Field(ge=0)
    lod0_estimated_draw_calls: int = Field(ge=0)
    lod0_vertices: int = Field(ge=0)
    lod0_triangles: int = Field(ge=0)
    lod_objects: int = Field(ge=0)
    collider_objects: int = Field(ge=0)
    collider_triangles: int = Field(ge=0)
    total_derived_triangles: int = Field(ge=0)
    unique_materials: int = Field(ge=0)
    overlap_candidates: int = Field(ge=0)


class AssetCostReduction(V07StrictModel):
    """Record one exact before/after static-asset cost delta."""

    metric: CostMetricName
    before: int = Field(ge=0)
    after: int = Field(ge=0)
    reduction: int
    reduction_fraction: float

    @model_validator(mode="after")
    def validate_delta(self) -> AssetCostReduction:
        """Keep reported cost reductions arithmetically consistent."""

        if self.reduction != self.before - self.after:
            raise ValueError("cost reduction must equal before minus after")
        expected = self.reduction / self.before if self.before else 0.0
        if abs(self.reduction_fraction - expected) > 1e-9:
            raise ValueError("cost reduction_fraction does not match before and after")
        return self


class CostBudgetResult(V07StrictModel):
    """Compare one measured static-asset cost proxy with an explicit ceiling."""

    metric: CostMetricName
    actual: int = Field(ge=0)
    maximum: int = Field(ge=0)
    status: Literal["passed", "warning", "failed"]
    message: str


class ConsolidationBatch(V07StrictModel):
    """Trace one derived batch back to every source object and stable semantic owner."""

    batch_id: StableId
    semantic_id: StableId
    lod_level: int = Field(ge=0, le=8)
    spatial_cell: tuple[int, int, int] | None = None
    material_ids: list[StableId] = Field(default_factory=list)
    source_objects: list[str] = Field(min_length=2)
    output_object: str
    object_count_before: int = Field(ge=2)
    object_count_after: Literal[1] = 1
    triangle_count_before: int = Field(ge=0)
    triangle_count_after: int = Field(ge=0)
    material_slots_before: int = Field(ge=0)
    material_slots_after: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_batch(self) -> ConsolidationBatch:
        """Require lossless triangle batching and complete source-object accounting."""

        if len(self.source_objects) != self.object_count_before:
            raise ValueError("batch source_objects must match object_count_before")
        if len(self.source_objects) != len(set(self.source_objects)):
            raise ValueError("batch source object names must be unique")
        if self.triangle_count_after != self.triangle_count_before:
            raise ValueError("semantic-preserving batching must retain triangle count")
        if self.material_slots_after > self.material_slots_before:
            raise ValueError("batching cannot increase material slot count")
        return self


class MeshCleanupRecord(V07StrictModel):
    """Record non-rendering derived cleanup without claiming canonical repair."""

    semantic_id: StableId
    object_name: str
    asset_role: Literal["render", "lod", "collider"]
    lod_level: int | None = Field(default=None, ge=0, le=8)
    loose_vertices_removed: int = Field(ge=0)
    loose_edges_removed: int = Field(ge=0)
    duplicate_material_slots_removed: int = Field(ge=0)
    exact_duplicate_colliders_removed: int = Field(default=0, ge=0)


class ExactInstanceGroup(V07StrictModel):
    """Identify reusable mesh payloads without assuming destination-engine instancing."""

    group_id: StableId
    mesh_fingerprint: Sha256
    objects: list[str] = Field(min_length=2)
    semantic_ids: list[StableId] = Field(min_length=1)
    material_ids: list[StableId] = Field(default_factory=list)
    potential_mesh_copies_saved: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_group(self) -> ExactInstanceGroup:
        """Require unique object and identity membership for one instance opportunity."""

        if len(self.objects) != len(set(self.objects)):
            raise ValueError("instance-group object names must be unique")
        if len(self.semantic_ids) != len(set(self.semantic_ids)):
            raise ValueError("instance-group semantic IDs must be unique")
        if self.potential_mesh_copies_saved != len(self.objects) - 1:
            raise ValueError("potential mesh savings must equal object count minus one")
        return self


class MeshOverlapFinding(V07StrictModel):
    """Describe one exact duplicate or broad-phase overlap candidate for manual review."""

    finding_id: StableId
    left_object: str
    right_object: str
    left_semantic_id: StableId
    right_semantic_id: StableId
    classification: Literal["exact_duplicate", "aabb_overlap_candidate"]
    overlap_volume_m3: float = Field(ge=0)
    action: Literal["report_only"] = "report_only"

    @model_validator(mode="after")
    def validate_pair(self) -> MeshOverlapFinding:
        """Reject self-pairs and zero-volume broad-phase findings."""

        if self.left_object == self.right_object:
            raise ValueError("overlap finding cannot compare an object with itself")
        if self.overlap_volume_m3 <= 0:
            raise ValueError("overlap findings require positive intersecting AABB volume")
        return self


class StaticAssetCostReport(V07StrictModel):
    """Summarize V0.7.3 batching, cleanup, overlap evidence, and cost budgets."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    report_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    status: Literal["passed", "failed"]
    ok: bool
    quality_status: QualityStatus = "partially_verified"
    unverified_checks: list[
        Literal[
            "internal_face_classification",
            "runtime_draw_calls",
            "destination_engine_instancing",
        ]
    ] = Field(
        default_factory=lambda: [
            "internal_face_classification",
            "runtime_draw_calls",
            "destination_engine_instancing",
        ]
    )
    before: AssetCostSnapshot
    after: AssetCostSnapshot
    reductions: list[AssetCostReduction] = Field(default_factory=list)
    budgets: list[CostBudgetResult] = Field(default_factory=list)
    consolidation_batches: list[ConsolidationBatch] = Field(default_factory=list)
    cleanup_records: list[MeshCleanupRecord] = Field(default_factory=list)
    instance_groups: list[ExactInstanceGroup] = Field(default_factory=list)
    overlap_findings_before: list[MeshOverlapFinding] = Field(default_factory=list)
    overlap_findings_after: list[MeshOverlapFinding] = Field(default_factory=list)
    created_at: datetime
    canonical_unchanged: Literal[True] = True
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report(self) -> StaticAssetCostReport:
        """Bind status to budget failures and keep all evidence identifiers unique."""

        collections = (
            [item.batch_id for item in self.consolidation_batches],
            [item.group_id for item in self.instance_groups],
            [item.finding_id for item in self.overlap_findings_before],
            [item.finding_id for item in self.overlap_findings_after],
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("cost-report evidence identifiers must be unique per collection")
        failed = any(item.status == "failed" for item in self.budgets)
        if self.ok == failed or self.status != ("failed" if failed else "passed"):
            raise ValueError("cost report status must match failed budget results")
        if self.quality_status == "verified" and self.unverified_checks:
            raise ValueError("verified cost quality cannot contain unverified checks")
        if self.quality_status != "verified" and not self.unverified_checks:
            raise ValueError("partially verified cost quality must identify limitations")
        return self


class LODEntry(V07StrictModel):
    """Describe one immutable LOD artifact for a stable semantic object family."""

    target_id: StableId
    level: int = Field(ge=0, le=8)
    mesh: HashedArtifact
    source_triangle_count: int = Field(ge=0)
    triangle_count: int = Field(ge=0)
    triangle_ratio: float = Field(ge=0, le=1)
    silhouette_iou: float | None = Field(default=None, ge=0, le=1)
    bounds: Bounds3D
    material_ids: list[StableId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entry(self) -> LODEntry:
        """Require a role-correct artifact, unique materials, and exact LOD0 preservation."""

        if self.mesh.kind != "lod_mesh":
            raise ValueError("LOD entry mesh artifact must use kind=lod_mesh")
        if len(self.material_ids) != len(set(self.material_ids)):
            raise ValueError("LOD material IDs must be unique")
        if self.triangle_count > self.source_triangle_count:
            raise ValueError("LOD triangle count cannot exceed source triangle count")
        if self.level == 0:
            if self.triangle_count != self.source_triangle_count or self.triangle_ratio != 1:
                raise ValueError("LOD0 must preserve the source triangle count exactly")
            if self.silhouette_iou is not None and self.silhouette_iou != 1:
                raise ValueError("LOD0 silhouette IoU must be exactly one when reported")
        return self


class LODManifest(V07StrictModel):
    """Record derived LOD artifacts while proving the canonical master stayed unchanged."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    manifest_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    status: ArtifactStatus = "planned"
    quality_status: QualityStatus = "unverified"
    unverified_checks: list[Literal["silhouette_iou"]] = Field(
        default_factory=lambda: ["silhouette_iou"]
    )
    entries: list[LODEntry] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    canonical_unchanged: Literal[True] = True
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> LODManifest:
        """Require consecutive LODs, non-increasing complexity, and valid lifecycle data."""

        keys = [(item.target_id, item.level) for item in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("LOD target and level pairs must be unique")
        for target_id in sorted({item.target_id for item in self.entries}):
            target_entries = sorted(
                (item for item in self.entries if item.target_id == target_id),
                key=lambda item: item.level,
            )
            levels = [item.level for item in target_entries]
            if levels != list(range(len(levels))):
                raise ValueError(f"LOD levels for {target_id} must be consecutive from zero")
            triangles = [item.triangle_count for item in target_entries]
            if triangles != sorted(triangles, reverse=True):
                raise ValueError(f"LOD triangle counts for {target_id} must not increase")
        if self.status == "planned":
            if self.entries or self.completed_at or self.errors:
                raise ValueError("planned LOD manifest cannot contain results")
        elif self.status == "complete":
            if not self.entries or self.completed_at is None or self.errors:
                raise ValueError(
                    "complete LOD manifest requires entries, completion, and no errors"
                )
        elif self.status == "failed":
            if self.completed_at is None or not self.errors:
                raise ValueError("failed LOD manifest requires completion and errors")
        if self.quality_status == "verified" and self.unverified_checks:
            raise ValueError("verified LOD quality cannot contain unverified checks")
        if self.quality_status != "verified" and not self.unverified_checks:
            raise ValueError("non-verified LOD quality must identify unverified checks")
        return self


class CollisionEntry(V07StrictModel):
    """Describe one primitive or mesh collision proxy owned by a semantic object."""

    collider_id: StableId
    target_id: StableId
    strategy: Literal["box", "sphere", "capsule", "convex_hull", "mesh_proxy"]
    location: Vec3 = (0.0, 0.0, 0.0)
    rotation_deg: Vec3 = (0.0, 0.0, 0.0)
    dimensions: Vec3
    mesh: HashedArtifact | None = None
    hull_count: int = Field(default=1, ge=1)
    triangle_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_entry(self) -> CollisionEntry:
        """Require positive bounds and mesh evidence only for mesh-backed strategies."""

        if any(value <= 0 for value in self.dimensions):
            raise ValueError("collider dimensions must be positive")
        mesh_backed = self.strategy in {"convex_hull", "mesh_proxy"}
        if mesh_backed and self.mesh is None:
            raise ValueError(f"{self.strategy} collider requires a mesh artifact")
        if not mesh_backed and self.mesh is not None:
            raise ValueError(f"{self.strategy} collider must not include a mesh artifact")
        if self.mesh is not None and self.mesh.kind != "collider_mesh":
            raise ValueError("collider mesh artifact must use kind=collider_mesh")
        return self


class CollisionManifest(V07StrictModel):
    """Record stable semantic ownership for all derived collision proxies."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    manifest_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    strategy: Literal["none", "box", "sphere", "capsule", "convex_hull", "compound", "mesh_proxy"]
    status: ArtifactStatus = "planned"
    entries: list[CollisionEntry] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    canonical_unchanged: Literal[True] = True
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> CollisionManifest:
        """Require unique collider IDs and strategy-consistent lifecycle results."""

        collider_ids = [item.collider_id for item in self.entries]
        if len(collider_ids) != len(set(collider_ids)):
            raise ValueError("collider IDs must be unique")
        if self.strategy == "none" and self.entries:
            raise ValueError("collision strategy none cannot contain entries")
        if self.status == "planned":
            if self.entries or self.completed_at or self.errors:
                raise ValueError("planned collision manifest cannot contain results")
        elif self.status == "complete":
            if self.strategy != "none" and not self.entries:
                raise ValueError("complete collision manifest requires entries")
            if self.completed_at is None or self.errors:
                raise ValueError("complete collision manifest requires completion and no errors")
        elif self.status == "failed":
            if self.completed_at is None or not self.errors:
                raise ValueError("failed collision manifest requires completion and errors")
        return self


class UVSetRecord(V07StrictModel):
    """Report one material or lightmap UV set for a stable semantic object."""

    target_id: StableId
    uv_set: StableId
    purpose: Literal["material", "lightmap"]
    generated: bool
    overlap_fraction: float | None = Field(default=None, ge=0, le=1)
    degenerate_face_count: int = Field(ge=0)
    texel_density_px_m: float | None = Field(default=None, gt=0)
    padding_px: int | None = Field(default=None, ge=0)
    layout_preview: HashedArtifact | None = None

    @model_validator(mode="after")
    def validate_preview(self) -> UVSetRecord:
        """Require UV preview artifacts to use their dedicated provenance role."""

        if self.layout_preview is not None and self.layout_preview.kind != "uv_preview":
            raise ValueError("UV layout preview artifact must use kind=uv_preview")
        return self


class UVManifest(V07StrictModel):
    """Record material and lightmap UV validation without replacing canonical geometry."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    manifest_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    uv_required: bool = True
    status: ArtifactStatus = "planned"
    quality_status: QualityStatus = "unverified"
    unverified_checks: list[Literal["overlap_fraction", "texel_density"]] = Field(
        default_factory=lambda: ["overlap_fraction", "texel_density"]
    )
    records: list[UVSetRecord] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    canonical_unchanged: Literal[True] = True
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> UVManifest:
        """Require unique object/UV pairs and lifecycle-consistent report contents."""

        keys = [(item.target_id, item.uv_set) for item in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("UV target and set pairs must be unique")
        if self.status == "planned":
            if self.records or self.completed_at or self.errors:
                raise ValueError("planned UV manifest cannot contain results")
        elif self.status == "complete":
            if self.uv_required and not self.records:
                raise ValueError("complete required UV manifest needs records")
            if self.completed_at is None or self.errors:
                raise ValueError("complete UV manifest requires completion and no errors")
        elif self.status == "failed":
            if self.completed_at is None or not self.errors:
                raise ValueError("failed UV manifest requires completion and errors")
        if self.quality_status == "verified" and self.unverified_checks:
            raise ValueError("verified UV quality cannot contain unverified checks")
        if self.quality_status != "verified" and not self.unverified_checks:
            raise ValueError("non-verified UV quality must identify unverified checks")
        return self


class PortableMaterialContractArtifact(V07StrictModel):
    """Bind one V0.7.1 material-conversion contract to a safe path and digest."""

    id: StableId
    kind: Literal[
        "portable_material_conversion_plan",
        "portable_material_conversion_manifest",
        "shader_recipe",
    ]
    path: JobRelativePath
    sha256: Sha256


class PortableAtlasPolicy(V07StrictModel):
    """Define one deterministic global atlas over every derived render and LOD binding."""

    layout: Literal["global_shared"] = "global_shared"
    atlas_scope: Literal["all_render_lod"] = "all_render_lod"
    conversion_phase: Literal["after_optimization_with_canonical_source_frame"] = (
        "after_optimization_with_canonical_source_frame"
    )
    tile_strategy: Literal["deterministic_grid"] = "deterministic_grid"
    uv_set: StableId = "CBMPortableAtlas"
    resolution: PositivePixel = 2048
    margin_px: int = Field(default=16, ge=1, le=1024)
    maximum_overlap_fraction: float = Field(default=0.0, ge=0, le=1)
    preserve_existing_uv_sets: Literal[True] = True
    required_channels: list[PortableMaterialChannel] = Field(
        default_factory=lambda: list(PORTABLE_MATERIAL_CHANNELS),
        min_length=5,
        max_length=5,
    )

    @model_validator(mode="after")
    def validate_policy(self) -> PortableAtlasPolicy:
        """Require a power-of-two atlas and the exact five portable PBR channels."""

        if self.resolution & (self.resolution - 1):
            raise ValueError("portable atlas resolution must be a power of two")
        if self.margin_px * 2 >= self.resolution:
            raise ValueError("portable atlas margin must leave a positive image interior")
        if tuple(self.required_channels) != PORTABLE_MATERIAL_CHANNELS:
            raise ValueError(
                "portable atlas channels must be base_color, roughness, metallic, "
                "normal, and emission in canonical order"
            )
        return self


class PortableMaterialBinding(V07StrictModel):
    """Bind one required material to its source recipe and atlas users."""

    material_id: StableId
    source_shader_recipe: PortableMaterialContractArtifact
    source_material_fingerprint: Sha256
    mapping_mode: Literal["uv", "object", "generated", "triplanar"]
    target_ids: list[StableId] = Field(min_length=1)
    bake_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_binding(self) -> PortableMaterialBinding:
        """Require a shader-recipe artifact and ordered unique semantic target IDs."""

        if self.source_shader_recipe.kind != "shader_recipe":
            raise ValueError("source_shader_recipe must use kind=shader_recipe")
        if self.target_ids != sorted(set(self.target_ids)):
            raise ValueError("portable material target IDs must be ordered and unique")
        return self


class PortableMaterialConversionPlan(V07StrictModel):
    """Authorize one derived-only material conversion against immutable run provenance."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    plan_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    profile_artifact: HashedArtifact
    optimization_plan: HashedArtifact
    optimized_blend: HashedArtifact
    uv_manifest: HashedArtifact
    required_material_ids: list[StableId] = Field(min_length=1)
    atlas_policy: PortableAtlasPolicy = Field(default_factory=PortableAtlasPolicy)
    materials: list[PortableMaterialBinding] = Field(min_length=1)
    status: Literal["draft", "approved"] = "draft"
    created_at: datetime
    approved_at: datetime | None = None
    canonical_unchanged: Literal[True] = True
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plan(self) -> PortableMaterialConversionPlan:
        """Enforce artifact roles, exact material coverage, and approval lifecycle rules."""

        expected_roles = (
            (self.profile_artifact, "asset_profile", "profile_artifact"),
            (self.optimization_plan, "optimization_plan", "optimization_plan"),
            (self.optimized_blend, "blend", "optimized_blend"),
            (self.uv_manifest, "uv_manifest", "uv_manifest"),
        )
        for artifact, kind, label in expected_roles:
            if artifact.kind != kind:
                raise ValueError(f"{label} must use kind={kind}")
        if self.required_material_ids != sorted(set(self.required_material_ids)):
            raise ValueError("required material IDs must be ordered and unique")
        material_ids = [item.material_id for item in self.materials]
        if material_ids != self.required_material_ids:
            raise ValueError("material bindings must exactly cover required_material_ids in order")
        source_artifacts = self.source.artifacts()
        artifacts = [
            *source_artifacts,
            self.profile_artifact,
            self.optimization_plan,
            self.optimized_blend,
            self.uv_manifest,
            *(item.source_shader_recipe for item in self.materials),
        ]
        artifact_ids = [item.id for item in artifacts]
        artifact_paths = [item.path for item in artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("conversion-plan artifact IDs must be unique")
        if len(artifact_paths) != len(set(artifact_paths)):
            raise ValueError("conversion-plan artifact paths must be unique")
        if self.status == "draft" and self.approved_at is not None:
            raise ValueError("draft conversion plan cannot contain approved_at")
        if self.status == "approved" and self.approved_at is None:
            raise ValueError("approved conversion plan requires approved_at")
        return self


class PortableAtlasTile(V07StrictModel):
    """Bind one derived render/LOD material use to a deterministic global-atlas tile."""

    binding_id: StableId
    material_id: StableId
    target_id: StableId
    derived_object_id: StableId
    lod_level: int = Field(ge=0, le=8)
    uv_set: StableId
    resolution: PixelResolution
    margin_px: int = Field(ge=1, le=1024)
    uv_minimum: UVPoint
    uv_maximum: UVPoint
    overlap_fraction: float | None = Field(default=None, ge=0, le=1)
    quality_status: QualityStatus = "unverified"
    unwrap_method: Literal["smart_project", "lightmap_pack_fallback"] = (
        "smart_project"
    )
    repaired_uv_degenerate_face_count: int = Field(default=0, ge=0)
    remaining_uv_degenerate_face_count: Literal[0] = 0
    tangent_repair_method: Literal["none", "dissolve_degenerate"] = "none"
    micro_sliver_face_count_before: int = Field(default=0, ge=0)
    remaining_micro_sliver_face_count: int = Field(default=0, ge=0)
    tangent_invalid_loop_count_before: int = Field(default=0, ge=0)
    tangent_invalid_loop_count_after: int = Field(default=0, ge=0)
    bounds_max_abs_delta_m: float = Field(default=0.0, ge=0, le=0.000001)

    @model_validator(mode="after")
    def validate_tile(self) -> PortableAtlasTile:
        """Require positive UV bounds and honest overlap-quality reporting."""

        if self.margin_px * 2 >= min(self.resolution):
            raise ValueError("portable atlas tile margin must leave a positive image interior")
        if any(
            high <= low
            for low, high in zip(self.uv_minimum, self.uv_maximum, strict=True)
        ):
            raise ValueError("portable atlas tile maximum must exceed its minimum")
        if self.quality_status == "verified" and self.overlap_fraction is None:
            raise ValueError("verified atlas quality requires overlap_fraction evidence")
        return self


class PortableChannelOutput(V07StrictModel):
    """Describe one global portable PBR atlas image and its material coverage."""

    id: StableId
    channel: PortableMaterialChannel
    path: JobRelativePath
    sha256: Sha256
    color_space: Literal["sRGB", "Non-Color"]
    resolution: PixelResolution
    material_ids: list[StableId] = Field(min_length=1)
    file_format: Literal["png"] = "png"

    @model_validator(mode="after")
    def validate_color_space(self) -> PortableChannelOutput:
        """Keep color channels in sRGB and numeric data channels in Non-Color space."""

        expected = "sRGB" if self.channel in {"base_color", "emission"} else "Non-Color"
        if self.color_space != expected:
            raise ValueError(f"{self.channel} channel requires color_space={expected}")
        if self.material_ids != sorted(set(self.material_ids)):
            raise ValueError("portable channel material IDs must be ordered and unique")
        return self


class PortableSurfaceFactors(V07StrictModel):
    """Preserve portable scalar factors that cannot be inferred from atlas pixels alone."""

    base_color_factor: tuple[UnitFloat, UnitFloat, UnitFloat, UnitFloat] = (
        1.0,
        1.0,
        1.0,
        1.0,
    )
    roughness_factor: UnitFloat = 1.0
    metallic_factor: UnitFloat = 1.0
    emission_factor: tuple[NonNegativeFloat, NonNegativeFloat, NonNegativeFloat] = (
        1.0,
        1.0,
        1.0,
    )
    alpha_factor: UnitFloat = 1.0
    transmission_factor: UnitFloat = 0.0


class PortableMaterialConversionEntry(V07StrictModel):
    """Record one converted material's bindings, factors, and declared fidelity losses."""

    material_id: StableId
    source_shader_recipe: PortableMaterialContractArtifact
    source_material_fingerprint: Sha256
    portable_material_fingerprint: Sha256
    mapping_mode: Literal["uv", "object", "generated", "triplanar"]
    binding_ids: list[StableId] = Field(min_length=1)
    surface_factors: PortableSurfaceFactors = Field(default_factory=PortableSurfaceFactors)
    losses: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entry(self) -> PortableMaterialConversionEntry:
        """Require a source recipe plus ordered unique derived binding IDs."""

        if self.source_shader_recipe.kind != "shader_recipe":
            raise ValueError("source_shader_recipe must use kind=shader_recipe")
        if self.binding_ids != sorted(set(self.binding_ids)):
            raise ValueError("portable material binding IDs must be ordered and unique")
        return self


class PortableMaterialConversionManifest(V07StrictModel):
    """Prove lifecycle, coverage, and immutable outputs for one portable conversion run."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    manifest_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    plan_artifact: PortableMaterialContractArtifact
    profile_artifact: HashedArtifact
    optimization_plan: HashedArtifact
    optimized_blend: HashedArtifact
    uv_manifest: HashedArtifact
    atlas_policy: PortableAtlasPolicy
    required_material_ids: list[StableId] = Field(min_length=1)
    converted_material_ids: list[StableId] = Field(default_factory=list)
    missing_material_ids: list[StableId] = Field(default_factory=list)
    entries: list[PortableMaterialConversionEntry] = Field(default_factory=list)
    tiles: list[PortableAtlasTile] = Field(default_factory=list)
    outputs: list[PortableChannelOutput] = Field(default_factory=list)
    portable_blend: HashedArtifact | None = None
    status: Literal["planned", "running", "complete", "failed"] = "planned"
    created_at: datetime
    completed_at: datetime | None = None
    canonical_unchanged: Literal[True] = True
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> PortableMaterialConversionManifest:
        """Enforce hash roles, exact coverage, unique paths, and status-specific outputs."""

        if self.plan_artifact.kind != "portable_material_conversion_plan":
            raise ValueError(
                "plan_artifact must use kind=portable_material_conversion_plan"
            )
        expected_roles = (
            (self.profile_artifact, "asset_profile", "profile_artifact"),
            (self.optimization_plan, "optimization_plan", "optimization_plan"),
            (self.optimized_blend, "blend", "optimized_blend"),
            (self.uv_manifest, "uv_manifest", "uv_manifest"),
        )
        for artifact, kind, label in expected_roles:
            if artifact.kind != kind:
                raise ValueError(f"{label} must use kind={kind}")
        for label, values in (
            ("required material IDs", self.required_material_ids),
            ("converted material IDs", self.converted_material_ids),
            ("missing material IDs", self.missing_material_ids),
        ):
            if values != sorted(set(values)):
                raise ValueError(f"{label} must be ordered and unique")
        entry_ids = [item.material_id for item in self.entries]
        if entry_ids != self.converted_material_ids:
            raise ValueError(
                "conversion entries must exactly match converted_material_ids in order"
            )
        required = set(self.required_material_ids)
        converted = set(self.converted_material_ids)
        if not converted.issubset(required):
            raise ValueError("converted materials must be a subset of required materials")
        if self.status in {"complete", "failed"} and set(self.missing_material_ids) != (
            required - converted
        ):
            raise ValueError("missing_material_ids must exactly equal required minus converted")
        tile_ids = [item.binding_id for item in self.tiles]
        if tile_ids != sorted(set(tile_ids)):
            raise ValueError("global atlas tile binding IDs must be ordered and unique")
        entry_binding_ids = [
            binding_id for item in self.entries for binding_id in item.binding_ids
        ]
        if len(entry_binding_ids) != len(set(entry_binding_ids)):
            raise ValueError("material entry binding IDs must be globally unique")
        if sorted(entry_binding_ids) != tile_ids:
            raise ValueError("global atlas tiles must exactly cover material entry bindings")
        entry_material_by_binding = {
            binding_id: item.material_id
            for item in self.entries
            for binding_id in item.binding_ids
        }
        if any(
            entry_material_by_binding.get(tile.binding_id) != tile.material_id
            for tile in self.tiles
        ):
            raise ValueError("global atlas tile material must match its entry binding")
        if any(item.uv_set != self.atlas_policy.uv_set for item in self.tiles):
            raise ValueError("every global atlas tile must use the atlas-policy UV set")
        if any(
            item.resolution
            != (self.atlas_policy.resolution, self.atlas_policy.resolution)
            for item in self.tiles
        ):
            raise ValueError("every global atlas tile resolution must match the policy")
        if any(item.margin_px != self.atlas_policy.margin_px for item in self.tiles):
            raise ValueError("every global atlas tile margin must match the policy")
        if any(
            item.overlap_fraction is not None
            and item.overlap_fraction > self.atlas_policy.maximum_overlap_fraction
            for item in self.tiles
        ):
            raise ValueError("global atlas overlap exceeds the policy")
        output_channels = [item.channel for item in self.outputs]
        if self.outputs and tuple(output_channels) != PORTABLE_MATERIAL_CHANNELS:
            raise ValueError("global atlas outputs must contain the canonical five channels")
        if any(item.material_ids != self.required_material_ids for item in self.outputs):
            raise ValueError("every global channel must exactly cover required materials")
        if any(
            item.resolution
            != (self.atlas_policy.resolution, self.atlas_policy.resolution)
            for item in self.outputs
        ):
            raise ValueError("every global channel resolution must match the atlas policy")
        source_artifacts = self.source.artifacts()
        binding_artifacts = [
            *source_artifacts,
            self.plan_artifact,
            self.profile_artifact,
            self.optimization_plan,
            self.optimized_blend,
            self.uv_manifest,
            *(item.source_shader_recipe for item in self.entries),
        ]
        binding_ids = [item.id for item in binding_artifacts]
        binding_paths = [item.path for item in binding_artifacts]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("conversion-manifest binding artifact IDs must be unique")
        if len(binding_paths) != len(set(binding_paths)):
            raise ValueError("conversion-manifest binding artifact paths must be unique")
        output_ids = [output.id for output in self.outputs]
        output_paths = [output.path for output in self.outputs]
        if self.portable_blend is not None:
            if self.portable_blend.kind != "blend":
                raise ValueError("portable_blend must use kind=blend")
            output_ids.append(self.portable_blend.id)
            output_paths.append(self.portable_blend.path)
        if len(output_ids) != len(set(output_ids)):
            raise ValueError("portable conversion output IDs must be globally unique")
        if len(output_paths) != len(set(output_paths)):
            raise ValueError("portable conversion output paths must be globally unique")
        if set(output_paths).intersection(binding_paths):
            raise ValueError("portable conversion output paths must not overwrite bound inputs")
        if self.status in {"planned", "running"}:
            if (
                self.entries
                or self.tiles
                or self.outputs
                or self.converted_material_ids
                or self.missing_material_ids
                or self.portable_blend is not None
                or self.completed_at is not None
                or self.errors
            ):
                raise ValueError(f"{self.status} conversion manifest cannot contain results")
        elif self.status == "complete":
            if (
                self.completed_at is None
                or self.portable_blend is None
                or self.errors
                or self.missing_material_ids
                or converted != required
                or len(self.outputs) != len(PORTABLE_MATERIAL_CHANNELS)
                or not self.tiles
            ):
                raise ValueError(
                    "complete conversion requires full coverage, portable blend, completion, "
                    "and no errors"
                )
        elif self.status == "failed":
            if (
                self.completed_at is None
                or not self.errors
                or self.portable_blend is not None
                or self.outputs
            ):
                raise ValueError(
                    "failed conversion requires completion and errors without portable outputs"
                )
        return self
