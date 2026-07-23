"""Strict V0.9 contracts for engine-neutral Codex destination handoff bundles."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from ..optimization.models import Bounds3D, JobId, JobRelativePath, StableId

SCHEMA_VERSION = "0.9.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
PORTABLE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"


def _validate_relative_path(value: str) -> str:
    """Require normalized POSIX syntax without absolute or escaping path segments."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty normalized POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative, not absolute")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


def _validate_hint(value: str) -> str:
    """Keep an optional destination hint as inert single-line data rather than code."""

    if any(ord(character) < 32 for character in value):
        raise ValueError("destination hint cannot contain control characters")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
PortableId = Annotated[str, Field(pattern=PORTABLE_ID_PATTERN)]
RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]
DestinationHint = Annotated[
    str,
    Field(min_length=1, max_length=256),
    AfterValidator(_validate_hint),
]
HandoffProfile = Literal["portable_gltf", "fbx_interchange"]
Vec3 = tuple[float, float, float]


class HandoffStrictModel(BaseModel):
    """Reject undeclared fields and non-finite numbers in handoff contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceArtifact(HandoffStrictModel):
    """Bind one source-job artifact to its exact job-relative path and digest."""

    kind: Literal[
        "package_manifest",
        "roundtrip_validation",
        "roundtrip_evidence",
        "package_file",
    ]
    path: JobRelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)


class HandoffFileReceipt(HandoffStrictModel):
    """Bind one file inside a movable handoff envelope by exact relative receipt."""

    file_id: PortableId
    kind: Literal[
        "package_manifest",
        "primary_model",
        "package_file",
        "texture",
        "roundtrip_validation",
        "roundtrip_evidence",
        "destination_context",
        "assembly_manifest",
        "material_mapping",
        "import_checklist",
        "prompt_template",
        "known_limitations",
        "import_schema",
        "handoff_manifest",
        "pdf_report",
        "pdf_manifest",
        "other",
    ]
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)
    media_type: str = Field(min_length=1, max_length=128)


class DestinationHandoffPlan(HandoffStrictModel):
    """Freeze one source package and passed round trip before handoff generation."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    plan_id: PortableId
    handoff_id: PortableId
    job_id: JobId
    profile_id: HandoffProfile
    package_id: StableId
    run_id: StableId
    package_root: JobRelativePath
    package_manifest: SourceArtifact
    roundtrip_validation: SourceArtifact
    roundtrip_evidence: SourceArtifact
    output_root: JobRelativePath
    destination_hint: DestinationHint | None = None
    supported_scope: list[str] = Field(min_length=1)
    excluded_scope: list[str] = Field(min_length=1)
    status: Literal["planned"] = "planned"
    canonical_unchanged: Literal[True] = True
    package_unchanged: Literal[True] = True
    created_at: datetime

    @model_validator(mode="after")
    def validate_bindings(self) -> DestinationHandoffPlan:
        """Require role-correct source artifacts and a dedicated handoff output root."""

        if self.package_manifest.kind != "package_manifest":
            raise ValueError("package_manifest must use kind=package_manifest")
        if self.roundtrip_validation.kind != "roundtrip_validation":
            raise ValueError("roundtrip_validation must use kind=roundtrip_validation")
        if self.roundtrip_evidence.kind != "roundtrip_evidence":
            raise ValueError("roundtrip_evidence must use kind=roundtrip_evidence")
        prefix = f"exports/destination_handoffs/{self.profile_id}/{self.package_id}/"
        if not self.output_root.startswith(prefix) or not self.output_root.endswith(
            f"/{self.handoff_id}"
        ):
            raise ValueError("output_root must match the requested profile/package/handoff IDs")
        return self


class AxisContract(HandoffStrictModel):
    """Describe source-authoring and interchange orientation without runtime claims."""

    handedness: Literal["right_handed"] = "right_handed"
    source_up_axis: Literal["+Z"] = "+Z"
    source_forward_axis: Literal["-Y"] = "-Y"
    interchange_up_axis: Literal["+Y"] = "+Y"
    interchange_forward_axis: Literal["-Z"] = "-Z"
    unit: Literal["meters"] = "meters"
    unit_scale_m: Literal[1.0] = 1.0
    camera_independent_orientation: Literal[True] = True
    file_metadata_verified: bool = False


class RawPBRContract(HandoffStrictModel):
    """State portable raw-channel meanings and the canonical glTF ORM packing."""

    base_color: str = "sRGB surface albedo; alpha may carry opacity only when declared"
    normal: str = "Non-Color tangent-space normal using the OpenGL +Y convention"
    metallic: str = "Non-Color scalar metalness"
    roughness: str = "Non-Color scalar perceptual roughness"
    occlusion: str = "Non-Color ambient occlusion multiplier"
    emission: str = "sRGB emissive color with strength handled separately when available"
    opacity: str = "Non-Color or base-color alpha according to the mapping entry"
    gltf_orm: dict[Literal["R", "G", "B"], Literal["occlusion", "roughness", "metallic"]] = (
        Field(default_factory=lambda: {"R": "occlusion", "G": "roughness", "B": "metallic"})
    )

    @model_validator(mode="after")
    def validate_orm(self) -> RawPBRContract:
        """Prevent accidental reinterpretation of the glTF ORM channel contract."""

        if self.gltf_orm != {"R": "occlusion", "G": "roughness", "B": "metallic"}:
            raise ValueError("glTF ORM must remain R=occlusion, G=roughness, B=metallic")
        return self


class HierarchySummary(HandoffStrictModel):
    """Separate verified exported hierarchy from advisory canonical relationships."""

    exported_hierarchy: Literal["flat_root"] = "flat_root"
    exported_hierarchy_verified: Literal[True] = True
    canonical_semantic_hierarchy: Literal["advisory"] = "advisory"
    destination_reparenting_requires_approval: Literal[True] = True


class LODColliderSummary(HandoffStrictModel):
    """Summarize whether the portable package contains LOD or collider objects."""

    lod_present: bool
    lod_levels: list[int] = Field(default_factory=list)
    lod_group_count: int = Field(default=0, ge=0)
    default_active_lod: Literal[0] = 0
    membership_explicit: bool = False
    switch_policy: Literal["destination_defined_unverified"] = (
        "destination_defined_unverified"
    )
    collider_present: bool
    collider_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_presence(self) -> LODColliderSummary:
        """Keep presence flags consistent with level and collider counts."""

        if self.lod_present != bool(self.lod_levels):
            raise ValueError("lod_present must match lod_levels")
        if self.lod_present != (self.lod_group_count > 0):
            raise ValueError("lod_present must match lod_group_count")
        if self.collider_present != (self.collider_count > 0):
            raise ValueError("collider_present must match collider_count")
        if self.lod_levels != sorted(set(self.lod_levels)):
            raise ValueError("lod_levels must be sorted and unique")
        return self


class DestinationContext(HandoffStrictModel):
    """Describe portable static-asset assumptions for a destination Codex session."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    handoff_id: PortableId
    asset_kind: Literal["static_asset"] = "static_asset"
    profile_id: HandoffProfile
    primary_model: RelativePath
    axis: AxisContract
    pivot_policy: str = Field(min_length=1, max_length=1000)
    expected_bounds: Bounds3D
    expected_bounds_space: Literal["source_authoring_z_up"] = "source_authoring_z_up"
    hierarchy: HierarchySummary
    pbr: RawPBRContract
    lod_and_collider: LODColliderSummary
    known_format_losses: list[str] = Field(default_factory=list)
    unverified_items: list[str] = Field(min_length=1)
    destination_hint: DestinationHint | None = None


class TransformSnapshot(HandoffStrictModel):
    """Record the source-authoring world transform used by a flat exported root."""

    translation_m: Vec3
    rotation_euler_rad: Vec3
    scale: Vec3
    space: Literal["source_authoring_world_as_flat_root"] = (
        "source_authoring_world_as_flat_root"
    )


class PivotSnapshot(HandoffStrictModel):
    """Record object-origin and source +Z base-plane evidence for reconstruction."""

    origin_translation_m: Vec3
    base_plane_z_m: float
    policy: Literal["preserve_exported_object_origin"] = "preserve_exported_object_origin"
    verification: Literal["export_evidence"] = "export_evidence"


class AssemblyNode(HandoffStrictModel):
    """Map one exported object back to stable semantic and material identities."""

    export_key: str = Field(min_length=1, max_length=512)
    object_name: str = Field(min_length=1, max_length=512)
    semantic_id: StableId
    instance_index: int | None = Field(default=None, ge=0)
    parent_export_key: None = None
    canonical_parent_semantic_id: StableId | None = None
    transform: TransformSnapshot
    material_ids: list[StableId] = Field(default_factory=list)
    lod_level: int | None = Field(default=None, ge=0, le=8)
    lod_group_id: StableId | None = None
    default_active: bool = False
    collider_target_id: StableId | None = None
    render_object: bool
    asset_role: Literal["render", "lod", "collider"]
    source_package_file: RelativePath
    repeated_instance_relation: Literal["explicit_index", "advisory", "unavailable"]
    pivot: PivotSnapshot

    @model_validator(mode="after")
    def validate_role(self) -> AssemblyNode:
        """Keep render, LOD, and collider fields consistent with the exported role."""

        if self.asset_role == "collider":
            if (
                self.render_object
                or self.collider_target_id is None
                or self.lod_group_id is not None
                or self.default_active
            ):
                raise ValueError("collider nodes must be non-rendering and name a target")
        elif self.collider_target_id is not None:
            raise ValueError("only collider nodes may declare collider_target_id")
        elif self.lod_group_id is None:
            raise ValueError("render and LOD nodes require explicit lod_group_id membership")
        if self.asset_role == "render" and self.lod_level not in {None, 0}:
            raise ValueError("render nodes may only represent LOD0")
        if self.asset_role == "lod" and self.lod_level in {None, 0}:
            raise ValueError("derived LOD nodes require a positive lod_level")
        if self.asset_role != "collider" and self.default_active != (self.lod_level == 0):
            raise ValueError("only LOD0 render nodes may be active by default")
        if len(self.material_ids) != len(set(self.material_ids)):
            raise ValueError("assembly material IDs must be unique per node")
        return self


class AssemblyManifest(HandoffStrictModel):
    """Provide a deterministic destination reconstruction map for exported objects."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    handoff_id: PortableId
    package_manifest_sha256: Sha256
    primary_model: RelativePath
    exported_root_policy: Literal["flat_root"] = "flat_root"
    canonical_hierarchy_is_advisory: Literal[True] = True
    nodes: list[AssemblyNode] = Field(min_length=1)
    semantic_ids: list[StableId] = Field(min_length=1)
    material_ids: list[StableId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_coverage(self) -> AssemblyManifest:
        """Require identity coverage and one explicit, mutually exclusive LOD0 per group."""

        keys = [item.export_key for item in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("assembly export keys must be unique")
        observed_semantic = sorted({item.semantic_id for item in self.nodes})
        observed_material = sorted(
            {material for item in self.nodes for material in item.material_ids}
        )
        if sorted(self.semantic_ids) != observed_semantic:
            raise ValueError("assembly semantic_ids must exactly cover node identities")
        if sorted(self.material_ids) != observed_material:
            raise ValueError("assembly material_ids must exactly cover node assignments")
        lod_groups: dict[str, list[AssemblyNode]] = {}
        for node in self.nodes:
            if node.lod_group_id is not None:
                lod_groups.setdefault(node.lod_group_id, []).append(node)
        for group_id, members in lod_groups.items():
            identities = {(item.semantic_id, item.instance_index) for item in members}
            if len(identities) != 1:
                raise ValueError(f"LOD group {group_id!r} mixes semantic instances")
            lod0 = [item for item in members if item.lod_level == 0]
            if len(lod0) != 1 or not lod0[0].default_active:
                raise ValueError(f"LOD group {group_id!r} requires one active LOD0")
            if any(item.default_active for item in members if item.lod_level != 0):
                raise ValueError(f"LOD group {group_id!r} activates more than LOD0")
        return self


PortableChannel = Literal[
    "base_color",
    "normal",
    "metallic",
    "roughness",
    "occlusion",
    "emission",
    "opacity",
]


class MaterialChannelMapping(HandoffStrictModel):
    """Describe one portable PBR channel or explicitly record that it is unavailable."""

    channel: PortableChannel
    status: Literal["available", "packed", "unavailable"]
    file: HandoffFileReceipt | None = None
    component: Literal["R", "G", "B", "A", "RGB", "RGBA"] | None = None
    color_space: Literal["sRGB", "Non-Color"]
    meaning: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_file_binding(self) -> MaterialChannelMapping:
        """Require file evidence for available channels and none for unavailable ones."""

        if self.status == "unavailable":
            if self.file is not None or self.component is not None:
                raise ValueError("unavailable channels cannot reference a file or component")
        elif self.file is None:
            raise ValueError("available or packed channels require a texture receipt")
        return self


class TextureCoordinateBinding(HandoffStrictModel):
    """Bind portable material sampling and tangents to one verified UV0 semantic."""

    required_uv_set: str = Field(min_length=1, max_length=128)
    required_uv_channel_index: Literal[0] = 0
    destination_semantic: Literal["TEXCOORD_0"] = "TEXCOORD_0"
    tangent_uv_set: str = Field(min_length=1, max_length=128)
    export_evidence_verified: Literal[True] = True

    @model_validator(mode="after")
    def validate_tangent_basis(self) -> TextureCoordinateBinding:
        """Require normal-map tangents to use the same portable UV set as textures."""

        if self.required_uv_set != self.tangent_uv_set:
            raise ValueError("portable textures and tangents must use the same UV set")
        return self


class PortableMaterialMapping(HandoffStrictModel):
    """Map one stable material ID to raw or packed portable channels."""

    material_id: StableId
    mapping_mode: str = Field(min_length=1, max_length=64)
    source_mapping_mode: str = Field(default="unknown", min_length=1, max_length=64)
    portable_mapping_mode: Literal["uv", "unverified"] = "unverified"
    texture_representation: Literal[
        "portable_global_atlas", "preserved_raw_channels", "unavailable"
    ] = "preserved_raw_channels"
    texture_coordinate_binding: TextureCoordinateBinding | None = None
    channels: list[MaterialChannelMapping] = Field(min_length=7, max_length=7)
    blender_master_shader_baked: bool
    known_losses: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_channels(self) -> PortableMaterialMapping:
        """Require exactly one mapping for every portable PBR semantic channel."""

        expected = {
            "base_color",
            "normal",
            "metallic",
            "roughness",
            "occlusion",
            "emission",
            "opacity",
        }
        actual = {item.channel for item in self.channels}
        if actual != expected or len(self.channels) != len(actual):
            raise ValueError("material mappings require exactly seven unique PBR channels")
        if self.texture_representation == "portable_global_atlas":
            if self.portable_mapping_mode != "uv" or self.texture_coordinate_binding is None:
                raise ValueError("portable atlas materials require a verified UV binding")
        elif self.texture_coordinate_binding is not None:
            raise ValueError("only portable atlas materials may declare atlas UV binding")
        return self


class MaterialMappingManifest(HandoffStrictModel):
    """Describe portable material reconstruction without claiming master-shader parity."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    handoff_id: PortableId
    package_manifest_sha256: Sha256
    pbr_contract: RawPBRContract
    materials: list[PortableMaterialMapping] = Field(min_length=1)
    blender_master_shader_transfer: Literal["not_assumed"] = "not_assumed"
    destination_channel_conversion_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_materials(self) -> MaterialMappingManifest:
        """Require unique material IDs and one consistent atlas binding when converted."""

        ids = [item.material_id for item in self.materials]
        if len(ids) != len(set(ids)):
            raise ValueError("material mapping IDs must be unique")
        atlas_bindings = {
            (
                item.texture_coordinate_binding.required_uv_set,
                item.texture_coordinate_binding.required_uv_channel_index,
                item.texture_coordinate_binding.tangent_uv_set,
            )
            for item in self.materials
            if item.texture_coordinate_binding is not None
        }
        if len(atlas_bindings) > 1:
            raise ValueError("converted materials must share one portable atlas UV binding")
        return self


class ImportChecklistItem(HandoffStrictModel):
    """Define one ordered, approval-aware destination import checkpoint."""

    order: int = Field(ge=1, le=100)
    item_id: PortableId
    title: str = Field(min_length=1, max_length=256)
    instruction: str = Field(min_length=1, max_length=2000)
    gate: Literal["pre_plan", "plan", "approval", "apply", "validate"]


class ImportChecklist(HandoffStrictModel):
    """Require destination analysis and user approval before any project mutation."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    handoff_id: PortableId
    items: list[ImportChecklistItem] = Field(min_length=1)
    required_plan_output: Literal["import_plan.json"] = "import_plan.json"
    required_receipt_output: Literal["import_receipt.json"] = "import_receipt.json"
    required_validation_output: Literal["import_validation.json"] = "import_validation.json"
    user_approval_required_before_apply: Literal[True] = True

    @model_validator(mode="after")
    def validate_order(self) -> ImportChecklist:
        """Require contiguous checklist ordering and unique checkpoint identities."""

        orders = [item.order for item in self.items]
        ids = [item.item_id for item in self.items]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("import checklist orders must be contiguous from one")
        if len(ids) != len(set(ids)):
            raise ValueError("import checklist item IDs must be unique")
        return self


class DestinationHandoffManifest(HandoffStrictModel):
    """Bind the complete core handoff contract to one exact portable package."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    handoff_id: PortableId
    job_id: JobId
    profile_id: HandoffProfile
    package_id: StableId
    run_id: StableId
    package_manifest: HandoffFileReceipt
    roundtrip_validation: HandoffFileReceipt
    primary_model: HandoffFileReceipt
    textures: list[HandoffFileReceipt] = Field(default_factory=list)
    semantic_ids: list[StableId] = Field(min_length=1)
    material_ids: list[StableId] = Field(min_length=1)
    destination_context: HandoffFileReceipt
    assembly_manifest: HandoffFileReceipt
    material_mapping: HandoffFileReceipt
    import_checklist: HandoffFileReceipt
    import_prompt: HandoffFileReceipt
    known_limitations: HandoffFileReceipt
    import_schemas: list[HandoffFileReceipt] = Field(min_length=3)
    assembly_manifest_sha256: Sha256
    material_mapping_sha256: Sha256
    prompt_template_sha256: Sha256
    lod_present: bool
    collider_present: bool
    supported_scope: list[str] = Field(min_length=1)
    excluded_scope: list[str] = Field(min_length=1)
    core_files: list[HandoffFileReceipt] = Field(min_length=1)
    canonical_unchanged: Literal[True] = True
    source_package_unchanged: Literal[True] = True
    generated_at: datetime

    @model_validator(mode="after")
    def validate_receipts(self) -> DestinationHandoffManifest:
        """Require role hashes and unique core receipts to agree with named artifacts."""

        if self.package_manifest.kind != "package_manifest":
            raise ValueError("package_manifest receipt has the wrong kind")
        if self.roundtrip_validation.kind != "roundtrip_validation":
            raise ValueError("roundtrip_validation receipt has the wrong kind")
        if self.primary_model.kind != "primary_model":
            raise ValueError("primary_model receipt has the wrong kind")
        if any(item.kind != "texture" for item in self.textures):
            raise ValueError("texture receipts must use kind=texture")
        if self.assembly_manifest_sha256 != self.assembly_manifest.sha256:
            raise ValueError("assembly_manifest_sha256 must match its artifact")
        if self.material_mapping_sha256 != self.material_mapping.sha256:
            raise ValueError("material_mapping_sha256 must match its artifact")
        if self.prompt_template_sha256 != self.import_prompt.sha256:
            raise ValueError("prompt_template_sha256 must match its artifact")
        paths = [item.path for item in self.core_files]
        ids = [item.file_id for item in self.core_files]
        if len(paths) != len(set(paths)) or len(ids) != len(set(ids)):
            raise ValueError("core handoff file receipts must be unique")
        required = {
            self.package_manifest.path,
            self.roundtrip_validation.path,
            self.primary_model.path,
            self.destination_context.path,
            self.assembly_manifest.path,
            self.material_mapping.path,
            self.import_checklist.path,
            self.import_prompt.path,
            self.known_limitations.path,
            *(item.path for item in self.textures),
            *(item.path for item in self.import_schemas),
        }
        if not required <= set(paths):
            raise ValueError("core_files must include every named handoff artifact")
        return self


class HandoffReportManifest(HandoffStrictModel):
    """Bind the derived PDF report to exact machine-readable handoff sources."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    handoff_id: PortableId
    pdf_path: RelativePath
    pdf_sha256: Sha256
    source_fingerprint: Sha256
    sources: list[HandoffFileReceipt] = Field(min_length=4)
    generated_at: datetime
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sources(self) -> HandoffReportManifest:
        """Require unique source paths and exclude the derived PDF from its own inputs."""

        paths = [item.path for item in self.sources]
        if len(paths) != len(set(paths)):
            raise ValueError("PDF report sources must be unique")
        if self.pdf_path in paths:
            raise ValueError("PDF report cannot be one of its own machine sources")
        return self


class HandoffValidationCheck(HandoffStrictModel):
    """Record one normalized handoff integrity or safety verification."""

    check_id: PortableId
    category: Literal[
        "package",
        "roundtrip",
        "path",
        "hash",
        "assembly",
        "material",
        "prompt",
        "pdf",
        "dependency",
    ]
    status: Literal["passed", "warning", "failed"]
    message: str = Field(min_length=1, max_length=2000)


class DestinationHandoffValidation(HandoffStrictModel):
    """Verify every movable handoff file while excluding only this self-receipt."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    validation_id: PortableId
    handoff_id: PortableId
    job_id: JobId
    profile_id: HandoffProfile
    package_id: StableId
    handoff_manifest_sha256: Sha256
    package_manifest_sha256: Sha256
    roundtrip_validation_sha256: Sha256
    status: Literal["passed", "warning", "failed"]
    ok: bool
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    expected_file_count: int = Field(ge=1)
    files: list[HandoffFileReceipt] = Field(min_length=1)
    checks: list[HandoffValidationCheck] = Field(min_length=1)
    missing_dependency_count: int = Field(ge=0)
    absolute_path_count: int = Field(ge=0)
    source_package_current: bool
    canonical_unchanged: Literal[True] = True
    source_package_unchanged: Literal[True] = True
    created_at: datetime
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_summary(self) -> DestinationHandoffValidation:
        """Require exact file counts and summary state derived from validation checks."""

        paths = [item.path for item in self.files]
        if len(paths) != len(set(paths)) or self.expected_file_count != len(paths):
            raise ValueError("validation file receipts must be unique and exactly counted")
        counts = {
            state: sum(item.status == state for item in self.checks)
            for state in ("passed", "warning", "failed")
        }
        if (self.passed, self.warnings, self.failed) != (
            counts["passed"],
            counts["warning"],
            counts["failed"],
        ):
            raise ValueError("handoff validation summary counts do not match checks")
        should_pass = (
            self.failed == 0
            and self.missing_dependency_count == 0
            and self.absolute_path_count == 0
            and self.source_package_current
            and not self.errors
        )
        expected_status = "passed" if should_pass and self.warnings == 0 else (
            "warning" if should_pass else "failed"
        )
        if self.status != expected_status or self.ok != should_pass:
            raise ValueError("handoff validation status must match exact check outcomes")
        return self


class DestinationImportPlan(HandoffStrictModel):
    """Define the destination-side plan that must exist before project modification."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    plan_id: PortableId
    handoff_manifest_sha256: Sha256
    package_manifest_sha256: Sha256
    detected_engine: str = Field(min_length=1, max_length=128)
    detected_version: str = Field(min_length=1, max_length=128)
    detected_render_pipeline: str = Field(min_length=1, max_length=128)
    detection_evidence: list[str] = Field(min_length=1)
    unit_axis_pivot_plan: list[str] = Field(min_length=1)
    hierarchy_plan: list[str] = Field(min_length=1)
    material_texture_plan: list[str] = Field(min_length=1)
    uv_coordinate_plan: list[str] = Field(min_length=1)
    lod_collider_plan: list[str] = Field(min_length=1)
    expected_changes: list[RelativePath] = Field(default_factory=list)
    known_losses: list[str] = Field(default_factory=list)
    user_approval_required: Literal[True] = True
    approved: Literal[False] = False
    created_at: datetime


class DestinationImportReceipt(HandoffStrictModel):
    """Record destination changes only after an approved import plan is applied."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    import_plan_sha256: Sha256
    handoff_manifest_sha256: Sha256
    changed_files: list[RelativePath] = Field(default_factory=list)
    imported_semantic_ids: list[StableId] = Field(default_factory=list)
    imported_material_ids: list[StableId] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    completed_at: datetime


class DestinationImportValidation(HandoffStrictModel):
    """Report destination reconstruction results without claiming runtime parity."""

    schema_version: Literal["0.9.0"] = SCHEMA_VERSION
    validation_id: PortableId
    import_receipt_sha256: Sha256
    handoff_manifest_sha256: Sha256
    status: Literal["passed", "warning", "failed"]
    semantic_id_coverage: float = Field(ge=0, le=1)
    material_id_coverage: float = Field(ge=0, le=1)
    bounds_within_tolerance: bool
    uv_coordinate_binding_verified: bool = False
    lod_renderer_membership_verified: bool = False
    default_active_lod_verified: bool = False
    material_render_verified: bool = False
    missing_dependencies: list[RelativePath] = Field(default_factory=list)
    runtime_parity_verified: Literal[False] = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    completed_at: datetime

    @model_validator(mode="after")
    def validate_destination_result(self) -> DestinationImportValidation:
        """Prevent a passed destination receipt without UV, LOD, and visual checks."""

        required = (
            self.bounds_within_tolerance,
            self.uv_coordinate_binding_verified,
            self.lod_renderer_membership_verified,
            self.default_active_lod_verified,
            self.material_render_verified,
            not self.missing_dependencies,
            not self.errors,
        )
        if self.status == "passed" and not all(required):
            raise ValueError("passed destination import requires all portable checks")
        return self
