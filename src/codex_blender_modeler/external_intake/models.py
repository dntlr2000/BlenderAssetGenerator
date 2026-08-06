"""Strict contracts for importing user-authored static Blender assets."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..materials.models import SurfaceSpec
from ..versioning import EXTERNAL_STATIC_ASSET_SCHEMA_VERSION

Sha256 = str
StableId = str
JobRelativePath = str


class ExternalIntakeStrictModel(BaseModel):
    """Reject undeclared fields in external-intake evidence."""

    model_config = ConfigDict(extra="forbid")


class ExternalIntakeArtifact(ExternalIntakeStrictModel):
    """Bind one job-contained intake artifact to its immutable SHA-256."""

    id: StableId
    kind: Literal[
        "external_source",
        "external_dependency",
        "external_inspection",
        "external_intake_plan",
        "external_intake_approval",
        "external_asset_manifest",
        "external_normalization_evidence",
        "external_normalization_receipt",
        "blend",
        "material_plan",
        "shader_recipe",
    ]
    path: JobRelativePath
    sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    source_names: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_relative_path(self) -> ExternalIntakeArtifact:
        """Reject absolute, backslash, empty, and escaping artifact paths."""

        if not self.path or "\\" in self.path:
            raise ValueError("intake artifact paths must use non-empty POSIX relative paths")
        parsed = PurePosixPath(self.path)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise ValueError("intake artifact paths must stay inside the job")
        if len(self.source_names) != len(set(self.source_names)):
            raise ValueError("intake artifact source_names must be unique")
        return self


class ExternalNormalizationPolicy(ExternalIntakeStrictModel):
    """Define the bounded static-only normalization applied to a copied source."""

    apply_object_scale: Literal[True] = True
    preserve_hierarchy: Literal[True] = True
    preserve_uv_layers: Literal[True] = True
    preserve_material_identity: Literal[True] = True
    split_multi_material_objects: Literal[True] = True
    pack_image_dependencies: Literal[True] = True
    remove_non_static_objects: Literal[True] = True
    strip_embedded_scripts: Literal[True] = True
    source_unit_scale_to_meters: float = Field(default=1.0, ge=1e-9, le=1e9)
    material_policy: Literal["preserve_master_and_bake_portable"] = (
        "preserve_master_and_bake_portable"
    )


class ExternalObjectPlan(ExternalIntakeStrictModel):
    """Map one inspected source object to one stable semantic identity."""

    source_name: str = Field(min_length=1)
    source_material_indices: list[int] = Field(default_factory=list)
    semantic_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    parent_semantic_id: StableId | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$",
    )
    object_type: Literal["MESH", "CURVE"]
    material_ids: list[StableId] = Field(default_factory=list)
    qa_role: Literal["primary", "supporting", "decorative", "ground_background"] = (
        "supporting"
    )
    include: Literal[True] = True

    @model_validator(mode="after")
    def validate_material_partition(self) -> ExternalObjectPlan:
        """Require one deterministic, non-negative material-index partition."""

        if any(value < 0 for value in self.source_material_indices):
            raise ValueError("source material indices must be non-negative")
        if self.source_material_indices != sorted(set(self.source_material_indices)):
            raise ValueError("source material indices must be sorted and unique")
        if len(self.material_ids) != 1:
            raise ValueError("normalized external submeshes require exactly one material ID")
        return self


class ExternalMaterialPlan(ExternalIntakeStrictModel):
    """Map one source material to a stable ID and portable bake policy."""

    source_name: str = Field(min_length=1)
    material_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    node_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_mode: Literal["uv", "object"] = "uv"
    surface: SurfaceSpec = Field(default_factory=SurfaceSpec)
    image_dependency_ids: list[StableId] = Field(default_factory=list)
    portable_strategy: Literal["bake_to_raw_pbr"] = "bake_to_raw_pbr"
    limitations: list[str] = Field(default_factory=list)


class ExternalAssetIntakePlan(ExternalIntakeStrictModel):
    """Freeze one reviewed mapping from an immutable external file into CBM semantics."""

    schema_version: Literal["0.9.0"] = EXTERNAL_STATIC_ASSET_SCHEMA_VERSION
    plan_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    job_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source: ExternalIntakeArtifact
    source_format: Literal["blend", "fbx", "glb"]
    dependencies: list[ExternalIntakeArtifact] = Field(default_factory=list)
    inspection: ExternalIntakeArtifact
    candidate_material_plan: ExternalIntakeArtifact
    candidate_shader_recipes: list[ExternalIntakeArtifact] = Field(default_factory=list)
    normalization: ExternalNormalizationPolicy = Field(
        default_factory=ExternalNormalizationPolicy
    )
    objects: list[ExternalObjectPlan] = Field(default_factory=list)
    materials: list[ExternalMaterialPlan] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["awaiting_user_approval", "blocked"] = "awaiting_user_approval"
    created_at: datetime
    canonical_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def validate_plan(self) -> ExternalAssetIntakePlan:
        """Require role-correct artifacts, unique mappings, and honest blocker state."""

        if self.source.kind != "external_source":
            raise ValueError("external intake source must use kind=external_source")
        if self.inspection.kind != "external_inspection":
            raise ValueError("external inspection must use kind=external_inspection")
        if self.candidate_material_plan.kind != "material_plan":
            raise ValueError("candidate_material_plan must use kind=material_plan")
        if any(item.kind != "shader_recipe" for item in self.candidate_shader_recipes):
            raise ValueError("candidate shader recipes must use kind=shader_recipe")
        if any(item.kind != "external_dependency" for item in self.dependencies):
            raise ValueError("external dependencies must use kind=external_dependency")
        object_partitions = [
            (item.source_name, tuple(item.source_material_indices)) for item in self.objects
        ]
        semantic_ids = [item.semantic_id for item in self.objects]
        material_names = [item.source_name for item in self.materials]
        material_ids = [item.material_id for item in self.materials]
        for values, label in (
            (object_partitions, "source object/material partitions"),
            (semantic_ids, "semantic IDs"),
            (material_names, "source material names"),
            (material_ids, "material IDs"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"external intake {label} must be unique")
        semantic_set = set(semantic_ids)
        missing_parents = sorted(
            {
                item.parent_semantic_id
                for item in self.objects
                if item.parent_semantic_id is not None
            }
            - semantic_set
        )
        if missing_parents:
            raise ValueError(f"external intake references missing parents: {missing_parents}")
        missing_materials = sorted(
            {value for item in self.objects for value in item.material_ids}
            - set(material_ids)
        )
        if missing_materials:
            raise ValueError(
                f"external objects reference missing material IDs: {missing_materials}"
            )
        dependency_ids = {item.id for item in self.dependencies}
        missing_dependencies = sorted(
            {
                value
                for material in self.materials
                for value in material.image_dependency_ids
            }
            - dependency_ids
        )
        if missing_dependencies:
            raise ValueError(
                "external materials reference missing dependencies: "
                f"{missing_dependencies}"
            )
        if self.status == "blocked" and not self.blockers:
            raise ValueError("blocked external intake plans require blocker messages")
        if self.status == "awaiting_user_approval" and self.blockers:
            raise ValueError("approvable external intake plans cannot contain blockers")
        if self.status == "awaiting_user_approval" and (
            not self.objects or not self.materials
        ):
            raise ValueError("approvable external intake plans require objects and materials")
        return self


class ExternalAssetIntakeApproval(ExternalIntakeStrictModel):
    """Record exact, single-use user approval for one intake plan."""

    schema_version: Literal["0.9.0"] = EXTERNAL_STATIC_ASSET_SCHEMA_VERSION
    approval_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    job_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    plan_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    plan_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: Literal["user"] = "user"
    approval_note: str = Field(min_length=1)
    approved_at: datetime
    one_time: Literal[True] = True
    used: bool = False
    used_at: datetime | None = None

    @model_validator(mode="after")
    def validate_usage(self) -> ExternalAssetIntakeApproval:
        """Require a consumption timestamp exactly when approval is consumed."""

        if self.used != (self.used_at is not None):
            raise ValueError("external intake approval used state and timestamp must match")
        return self


class ExternalNormalizedObject(ExternalIntakeStrictModel):
    """Record one normalized authoring object and its preserved assembly mapping."""

    source_name: str
    object_name: str
    semantic_id: StableId
    parent_semantic_id: StableId | None = None
    object_type: Literal["MESH", "CURVE"]
    material_ids: list[StableId] = Field(default_factory=list)
    qa_role: Literal["primary", "supporting", "decorative", "ground_background"]
    location: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]
    scale: tuple[float, float, float]
    dimensions: tuple[float, float, float]

    @model_validator(mode="after")
    def validate_portable_partition(self) -> ExternalNormalizedObject:
        """Require one exact material on each portable normalized submesh."""

        if len(self.material_ids) != 1:
            raise ValueError("normalized external objects require exactly one material ID")
        return self


class ExternalNormalizedMaterial(ExternalIntakeStrictModel):
    """Record one preserved Blender material and its portable bake bridge."""

    source_name: str
    material_name: str
    material_id: StableId
    node_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    shader_recipe: ExternalIntakeArtifact
    portable_strategy: Literal["bake_to_raw_pbr"] = "bake_to_raw_pbr"
    limitations: list[str] = Field(default_factory=list)


class ExternalAssetManifest(ExternalIntakeStrictModel):
    """Describe the immutable intake source and normalized authoring derivative."""

    schema_version: Literal["0.9.0"] = EXTERNAL_STATIC_ASSET_SCHEMA_VERSION
    manifest_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    job_id: StableId = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    source_kind: Literal["external_static_asset"] = "external_static_asset"
    source_format: Literal["blend", "fbx", "glb"]
    source: ExternalIntakeArtifact
    dependencies: list[ExternalIntakeArtifact] = Field(default_factory=list)
    intake_plan: ExternalIntakeArtifact
    intake_approval: ExternalIntakeArtifact
    normalized_blend: ExternalIntakeArtifact
    normalization_evidence: ExternalIntakeArtifact
    material_plan: ExternalIntakeArtifact
    shader_recipes: list[ExternalIntakeArtifact] = Field(default_factory=list)
    objects: list[ExternalNormalizedObject] = Field(min_length=1)
    materials: list[ExternalNormalizedMaterial] = Field(min_length=1)
    source_contract_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    build_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["complete"] = "complete"
    created_at: datetime
    completed_at: datetime
    limitations: list[str] = Field(default_factory=list)
    canonical_source_unchanged: Literal[True] = True

    @model_validator(mode="after")
    def validate_manifest(self) -> ExternalAssetManifest:
        """Require role-correct artifacts and exact normalized identity coverage."""

        expected = (
            (self.source, "external_source", "source"),
            (self.intake_plan, "external_intake_plan", "intake_plan"),
            (self.intake_approval, "external_intake_approval", "intake_approval"),
            (self.normalized_blend, "blend", "normalized_blend"),
            (
                self.normalization_evidence,
                "external_normalization_evidence",
                "normalization_evidence",
            ),
            (self.material_plan, "material_plan", "material_plan"),
        )
        for artifact, kind, label in expected:
            if artifact.kind != kind:
                raise ValueError(f"{label} must use kind={kind}")
        if any(item.kind != "external_dependency" for item in self.dependencies):
            raise ValueError("manifest dependencies must use kind=external_dependency")
        if any(item.kind != "shader_recipe" for item in self.shader_recipes):
            raise ValueError("manifest shader recipes must use kind=shader_recipe")
        semantic_ids = [item.semantic_id for item in self.objects]
        material_ids = [item.material_id for item in self.materials]
        if len(semantic_ids) != len(set(semantic_ids)):
            raise ValueError("normalized semantic IDs must be unique")
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("normalized material IDs must be unique")
        semantic_set = set(semantic_ids)
        missing_parents = sorted(
            {
                item.parent_semantic_id
                for item in self.objects
                if item.parent_semantic_id is not None
            }
            - semantic_set
        )
        if missing_parents:
            raise ValueError(f"normalized objects reference missing parents: {missing_parents}")
        missing_materials = sorted(
            {value for item in self.objects for value in item.material_ids}
            - set(material_ids)
        )
        if missing_materials:
            raise ValueError(
                f"normalized objects reference missing materials: {missing_materials}"
            )
        recipe_ids = {item.id for item in self.shader_recipes}
        expected_recipe_ids = {
            material.shader_recipe.id for material in self.materials
        }
        if recipe_ids != expected_recipe_ids:
            raise ValueError("manifest shader recipe coverage differs from material records")
        artifacts = [
            self.source,
            *self.dependencies,
            self.intake_plan,
            self.intake_approval,
            self.normalized_blend,
            self.normalization_evidence,
            self.material_plan,
            *self.shader_recipes,
        ]
        ids = [item.id for item in artifacts]
        paths = [item.path for item in artifacts]
        if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
            raise ValueError("manifest artifact IDs and paths must be unique")
        return self


class ExternalNormalizationReceipt(ExternalIntakeStrictModel):
    """Bind one consumed approval to exact normalized outputs."""

    schema_version: Literal["0.9.0"] = EXTERNAL_STATIC_ASSET_SCHEMA_VERSION
    receipt_id: StableId
    job_id: StableId
    plan_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    approval_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    material_plan_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    shader_recipe_sha256: dict[StableId, Sha256]
    normalized_blend_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    normalization_evidence_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    source_contract_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    build_fingerprint: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["complete"] = "complete"
    completed_at: datetime


class ExternalAssetIntakeValidation(ExternalIntakeStrictModel):
    """Report current hash, provenance, dependency, and semantic readiness."""

    schema_version: Literal["0.9.0"] = EXTERNAL_STATIC_ASSET_SCHEMA_VERSION
    job_id: StableId
    plan_id: StableId
    status: Literal["passed", "failed"]
    ok: bool
    source_current: bool
    dependencies_current: bool
    approval_current_and_used: bool
    contracts_current: bool
    normalized_blend_current: bool
    embedded_build_current: bool
    normalization_receipt_current: bool
    semantic_object_count: int = Field(ge=0)
    material_count: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: datetime

    @model_validator(mode="after")
    def validate_status(self) -> ExternalAssetIntakeValidation:
        """Keep success state, error presence, and status mutually consistent."""

        expected = not self.errors and all(
            (
                self.source_current,
                self.dependencies_current,
                self.approval_current_and_used,
                self.contracts_current,
                self.normalized_blend_current,
                self.embedded_build_current,
                self.normalization_receipt_current,
                self.semantic_object_count > 0,
                self.material_count > 0,
            )
        )
        if self.ok != expected or self.status != ("passed" if expected else "failed"):
            raise ValueError("external intake validation status does not match evidence")
        return self
