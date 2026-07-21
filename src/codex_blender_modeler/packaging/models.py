"""Strict V0.7 contracts for texture packing, export packages, and round trips."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, model_validator

from ..optimization.models import (
    SCHEMA_VERSION,
    ArtifactStatus,
    Bounds3D,
    HashedArtifact,
    JobId,
    JobRelativePath,
    PortableMaterialContractArtifact,
    PortableProfile,
    SourceProvenance,
    StableId,
    V07StrictModel,
)


class TextureChannelMapping(V07StrictModel):
    """Map one preserved raw PBR source channel into a portable output component."""

    output_channel: Literal["R", "G", "B", "A", "RGB", "RGBA"]
    source_channel: Literal[
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "occlusion",
        "emission",
        "opacity",
        "orm",
    ]
    source: HashedArtifact
    invert: bool = False

    @model_validator(mode="after")
    def validate_source(self) -> TextureChannelMapping:
        """Require packed channel inputs to reference preserved texture artifacts."""

        if self.source.kind not in {"texture_manifest", "package_file", "other"}:
            raise ValueError("texture mapping source must be a texture-compatible artifact")
        return self


class PackedTexture(V07StrictModel):
    """Describe one immutable raw or packed portable texture and its channel provenance."""

    texture_id: StableId
    material_ids: list[StableId] = Field(min_length=1)
    packing: Literal["raw_channels", "gltf_orm"]
    output: HashedArtifact
    color_space: Literal["sRGB", "Non-Color"]
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    mappings: list[TextureChannelMapping] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_texture(self) -> PackedTexture:
        """Require unique channels, stable materials, and canonical glTF ORM semantics."""

        if self.output.kind != "packed_texture":
            raise ValueError("packed texture output must use kind=packed_texture")
        if len(self.material_ids) != len(set(self.material_ids)):
            raise ValueError("packed texture material IDs must be unique")
        output_channels = [item.output_channel for item in self.mappings]
        if len(output_channels) != len(set(output_channels)):
            raise ValueError("packed texture output channels must be unique")
        if self.packing == "gltf_orm":
            expected = {
                "R": "occlusion",
                "G": "roughness",
                "B": "metallic",
            }
            actual = {item.output_channel: item.source_channel for item in self.mappings}
            if actual != expected:
                raise ValueError("gltf_orm requires R=occlusion, G=roughness, B=metallic")
            if self.color_space != "Non-Color":
                raise ValueError("gltf_orm textures must use Non-Color space")
        return self


class TexturePackManifest(V07StrictModel):
    """Record engine-neutral packed textures while preserving every raw PBR source channel."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    manifest_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    status: ArtifactStatus = "planned"
    packing_required: bool = True
    raw_channels_preserved: Literal[True] = True
    textures: list[PackedTexture] = Field(default_factory=list)
    created_at: datetime
    completed_at: datetime | None = None
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> TexturePackManifest:
        """Require unique texture IDs and outputs with lifecycle-consistent results."""

        texture_ids = [item.texture_id for item in self.textures]
        output_paths = [item.output.path for item in self.textures]
        if len(texture_ids) != len(set(texture_ids)):
            raise ValueError("packed texture IDs must be unique")
        if len(output_paths) != len(set(output_paths)):
            raise ValueError("packed texture output paths must be unique")
        if self.status == "planned":
            if self.textures or self.completed_at or self.errors:
                raise ValueError("planned texture pack manifest cannot contain results")
        elif self.status == "complete":
            if self.packing_required and not self.textures:
                raise ValueError("complete required texture packing needs outputs")
            if self.completed_at is None or self.errors:
                raise ValueError("complete texture pack manifest requires completion and no errors")
        elif self.status == "failed":
            if self.completed_at is None or not self.errors:
                raise ValueError("failed texture pack manifest requires completion and errors")
        return self


class PackageFile(V07StrictModel):
    """Describe one immutable file contained by a portable export package."""

    id: StableId
    kind: Literal[
        "primary_asset",
        "lod",
        "collider",
        "texture",
        "metadata",
        "preview",
        "other",
    ]
    path: JobRelativePath
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)
    media_type: str


class ExportPackageManifest(V07StrictModel):
    """Provide the authoritative immutable receipt for one portable asset package."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    package_id: StableId
    job_id: JobId
    run_id: StableId
    profile_id: PortableProfile
    source: SourceProvenance
    optimization_plan: HashedArtifact
    material_conversion: PortableMaterialContractArtifact | None = None
    source_manifests: list[HashedArtifact] = Field(default_factory=list)
    status: Literal["planned", "building", "complete", "failed"] = "planned"
    package_root: JobRelativePath
    files: list[PackageFile] = Field(default_factory=list)
    primary_file_id: StableId | None = None
    semantic_ids: list[StableId] = Field(default_factory=list)
    material_ids: list[StableId] = Field(default_factory=list)
    absolute_path_count: int = Field(default=0, ge=0)
    missing_dependency_count: int = Field(default=0, ge=0)
    created_at: datetime
    completed_at: datetime | None = None
    canonical_unchanged: Literal[True] = True
    known_losses: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_manifest(self) -> ExportPackageManifest:
        """Enforce profile format, unique receipts, dependency safety, and lifecycle state."""

        if self.optimization_plan.kind != "optimization_plan":
            raise ValueError("optimization_plan must use kind=optimization_plan")
        if (
            self.material_conversion is not None
            and self.material_conversion.kind != "portable_material_conversion_manifest"
        ):
            raise ValueError(
                "material_conversion must use kind=portable_material_conversion_manifest"
            )
        source_ids = [item.id for item in self.source_manifests]
        source_paths = [item.path for item in self.source_manifests]
        if len(source_ids) != len(set(source_ids)) or len(source_paths) != len(set(source_paths)):
            raise ValueError("source manifests must have unique IDs and paths")
        file_ids = [item.id for item in self.files]
        file_paths = [item.path for item in self.files]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("package file IDs must be unique")
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("package file paths must be unique")
        if len(self.semantic_ids) != len(set(self.semantic_ids)):
            raise ValueError("package semantic IDs must be unique")
        if len(self.material_ids) != len(set(self.material_ids)):
            raise ValueError("package material IDs must be unique")
        package_parts = PurePosixPath(self.package_root).parts
        contained_paths = [
            self.optimization_plan.path,
            *(
                [self.material_conversion.path]
                if self.material_conversion is not None
                else []
            ),
            *(item.path for item in self.source_manifests),
            *(item.path for item in self.files),
        ]
        for path in contained_paths:
            parts = PurePosixPath(path).parts
            if parts[: len(package_parts)] != package_parts or len(parts) <= len(
                package_parts
            ):
                raise ValueError(
                    "package receipts and metadata snapshots must stay below package_root"
                )
        if self.primary_file_id is not None:
            primary = next((item for item in self.files if item.id == self.primary_file_id), None)
            if primary is None or primary.kind != "primary_asset":
                raise ValueError("primary_file_id must reference one primary_asset file")
            expected_suffix = {
                "portable_gltf": ".glb",
                "fbx_interchange": ".fbx",
                "obj_legacy": ".obj",
            }[self.profile_id]
            if PurePosixPath(primary.path).suffix.lower() != expected_suffix:
                raise ValueError(
                    f"profile {self.profile_id} primary file must use {expected_suffix}"
                )
        if self.status == "planned":
            if self.files or self.primary_file_id or self.completed_at or self.errors:
                raise ValueError("planned package manifest cannot contain build results")
        elif self.status == "building":
            if self.completed_at or self.errors:
                raise ValueError("building package manifest cannot be completed or failed")
        elif self.status == "complete":
            if not self.files or self.primary_file_id is None or self.completed_at is None:
                raise ValueError("complete package requires files, a primary file, and completion")
            if not self.semantic_ids or not self.material_ids:
                raise ValueError(
                    "complete package requires non-empty semantic and material identities"
                )
            if self.absolute_path_count or self.missing_dependency_count or self.errors:
                raise ValueError(
                    "complete package cannot have absolute paths, missing dependencies, or errors"
                )
        elif self.status == "failed":
            if self.completed_at is None or not self.errors:
                raise ValueError("failed package manifest requires completion and errors")
        return self


class RoundTripCheck(V07StrictModel):
    """Record one normalized clean-import package verification check."""

    id: StableId
    category: Literal[
        "format",
        "units",
        "axis",
        "bounds",
        "object",
        "semantic_id",
        "material_id",
        "uv",
        "normal",
        "tangent",
        "texture",
        "dependency",
    ]
    status: Literal["passed", "warning", "failed"]
    message: str
    target_id: StableId | None = None


class BoundsComparison(V07StrictModel):
    """Compare source-derived and clean-import bounds against one metric tolerance."""

    source: Bounds3D
    imported: Bounds3D
    max_abs_error_m: float = Field(ge=0)
    tolerance_m: float = Field(gt=0)
    passed: bool

    @model_validator(mode="after")
    def validate_result(self) -> BoundsComparison:
        """Require the pass flag to agree exactly with the measured bounds tolerance."""

        if self.passed != (self.max_abs_error_m <= self.tolerance_m):
            raise ValueError("bounds pass flag must match measured error and tolerance")
        return self


class RoundTripValidation(V07StrictModel):
    """Prove normalized IDs, bounds, and dependencies survive a clean package reimport."""

    schema_version: Literal["0.7.0"] = SCHEMA_VERSION
    validation_id: StableId
    job_id: JobId
    run_id: StableId
    package_id: StableId
    profile_id: PortableProfile
    package_manifest: HashedArtifact
    imported_inventory: HashedArtifact
    status: Literal["passed", "failed", "error"]
    ok: bool
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    checks: list[RoundTripCheck] = Field(default_factory=list)
    bounds: BoundsComparison
    expected_semantic_ids: list[StableId] = Field(default_factory=list)
    observed_semantic_ids: list[StableId] = Field(default_factory=list)
    semantic_id_coverage: float = Field(ge=0, le=1)
    expected_material_ids: list[StableId] = Field(default_factory=list)
    observed_material_ids: list[StableId] = Field(default_factory=list)
    material_id_coverage: float = Field(ge=0, le=1)
    created_at: datetime
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report(self) -> RoundTripValidation:
        """Match summary state to checks, coverage, bounds, and unique stable identities."""

        if self.package_manifest.kind != "package_manifest":
            raise ValueError("package_manifest must use kind=package_manifest")
        if self.imported_inventory.kind != "roundtrip_inventory":
            raise ValueError("imported_inventory must use kind=roundtrip_inventory")
        check_ids = [item.id for item in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("round-trip check IDs must be unique")
        identity_lists = (
            self.expected_semantic_ids,
            self.observed_semantic_ids,
            self.expected_material_ids,
            self.observed_material_ids,
        )
        if any(len(values) != len(set(values)) for values in identity_lists):
            raise ValueError("round-trip stable ID lists must contain unique values")
        counts = {
            state: sum(item.status == state for item in self.checks)
            for state in ("passed", "warning", "failed")
        }
        if (self.passed, self.warnings, self.failed) != (
            counts["passed"],
            counts["warning"],
            counts["failed"],
        ):
            raise ValueError("round-trip summary counts do not match checks")
        expected_semantic = set(self.expected_semantic_ids)
        expected_material = set(self.expected_material_ids)
        actual_semantic_coverage = (
            len(expected_semantic & set(self.observed_semantic_ids)) / len(expected_semantic)
            if expected_semantic
            else 1.0
        )
        actual_material_coverage = (
            len(expected_material & set(self.observed_material_ids)) / len(expected_material)
            if expected_material
            else 1.0
        )
        if abs(self.semantic_id_coverage - actual_semantic_coverage) > 1e-9:
            raise ValueError("semantic ID coverage does not match expected and observed IDs")
        if abs(self.material_id_coverage - actual_material_coverage) > 1e-9:
            raise ValueError("material ID coverage does not match expected and observed IDs")
        should_pass = (
            self.failed == 0
            and self.bounds.passed
            and self.semantic_id_coverage == 1
            and self.material_id_coverage == 1
            and not self.errors
        )
        if self.status == "passed":
            if not should_pass or not self.ok:
                raise ValueError("passed round trip requires all checks and coverage to pass")
        elif self.status == "failed":
            if should_pass or self.ok:
                raise ValueError("failed round trip must contain a verification regression")
        elif self.status == "error":
            if self.ok or not self.errors:
                raise ValueError("round-trip error status requires errors and ok=false")
        return self
