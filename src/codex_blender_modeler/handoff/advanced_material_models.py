"""Strict AdvancedMaterialHandoff 0.1.0 advisory contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from ..material_authoring.models import (
    ColorRGB,
    ColorSpace,
    ExactArtifact,
    JobId,
    MaterialAuthoringStrictModel,
    MaterialFamily,
    PortableId,
    RawPBRChannel,
    RelativePath,
    Sha256,
)

SCHEMA_VERSION = "0.1.0"
DestinationMaterialTarget = Literal["unity_urp", "unity_hdrp"]


def _validate_inert_hint(value: str) -> str:
    """Reject control characters so a destination hint remains inert single-line data."""

    if any(ord(character) < 32 for character in value):
        raise ValueError("destination_hint must remain inert single-line data")
    return value


InertHint = Annotated[
    str,
    Field(min_length=1, max_length=256),
    AfterValidator(_validate_inert_hint),
]


class AdvancedMaterialHandoffRequest(MaterialAuthoringStrictModel):
    """Freeze one exact authored material and an advisory destination-family choice."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    request_id: PortableId
    plan_id: PortableId
    job_id: JobId
    material_authoring_manifest: ExactArtifact
    material_authoring_receipt: ExactArtifact
    destination_target: DestinationMaterialTarget
    destination_hint: InertHint | None = None
    output_root: RelativePath
    destination_write_authority: Literal[False] = False
    engine_execution_authority: Literal[False] = False
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_output_root(self) -> AdvancedMaterialHandoffRequest:
        """Keep the plan in one immutable companion-owned evidence directory."""

        expected = f"exports/advanced_material_handoffs/{self.plan_id}"
        if self.output_root != expected:
            raise ValueError(f"output_root must equal {expected}")
        return self


class RawChannelHandoffMapping(MaterialAuthoringStrictModel):
    """Map one exact raw source channel to a destination property or packing rule."""

    channel: RawPBRChannel
    source_path: RelativePath
    source_sha256: Sha256
    source_color_space: ColorSpace
    destination_property: str = Field(min_length=1, max_length=128)
    conversion: str = Field(min_length=1, max_length=512)
    destination_color_space: ColorSpace
    packed_destination_channel: Literal["R", "G", "B", "A"] | None = None
    advisory_only: Literal[True] = True


class AdvancedMaterialContract(MaterialAuthoringStrictModel):
    """Describe portable material intent and destination feature loss without runtime claims."""

    material_id: str = Field(min_length=1, max_length=128)
    material_family: MaterialFamily
    raw_pbr_channel_mapping: list[RawChannelHandoffMapping]
    authoring_shader_features: list[str] = Field(min_length=1)
    portable_approximation: str = Field(min_length=1, max_length=1024)
    required_destination_features: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)
    preferred_shader_family: str = Field(min_length=1, max_length=128)
    approximation_policy: Literal[
        "direct_portable_mapping",
        "packed_channel_conversion_required",
        "custom_shader_reconstruction_required",
    ]
    source_hashes: list[Sha256] = Field(min_length=1)
    texture_color_spaces: dict[RawPBRChannel, ColorSpace]
    normal_convention: Literal["opengl_y_plus", "not_present"]
    transparency_mode: Literal[
        "opaque",
        "alpha_clip",
        "alpha_blend",
        "approximate_transmission",
        "unspecified",
    ]
    double_sided_intent: bool | None
    emission: bool
    emission_color: ColorRGB | None
    emission_strength: float | None = Field(default=None, ge=0, le=1000)
    clear_coat: bool
    transmission: float = Field(ge=0, le=1)
    ior: float | None = Field(default=None, ge=1, le=3)
    thickness_m: float | None = Field(default=None, gt=0)
    absorption_distance_m: float | None = Field(default=None, gt=0)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)
    destination_write_performed: Literal[False] = False
    runtime_parity_verified: Literal[False] = False

    @model_validator(mode="after")
    def validate_feature_claims(self) -> AdvancedMaterialContract:
        """Require explicit optical values only when transmission intent exists."""

        if self.transmission > 0 and self.ior is None:
            raise ValueError("transmission intent requires an explicit IOR")
        if self.normal_convention == "opengl_y_plus" and "normal" not in {
            item.channel for item in self.raw_pbr_channel_mapping
        }:
            raise ValueError("normal convention cannot be claimed without a normal channel")
        if self.normal_convention == "not_present" and "normal" in {
            item.channel for item in self.raw_pbr_channel_mapping
        }:
            raise ValueError("normal channel requires an explicit convention")
        return self


class AdvancedMaterialHandoffPlan(MaterialAuthoringStrictModel):
    """Provide an advisory Unity-family reconstruction plan without project writes."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    plan_id: PortableId
    job_id: JobId
    destination_target: DestinationMaterialTarget
    destination_hint: InertHint | None = None
    request: ExactArtifact
    material_authoring_manifest: ExactArtifact
    material_authoring_receipt: ExactArtifact
    contract: AdvancedMaterialContract
    operations: list[str] = Field(min_length=1)
    known_limitations: list[str] = Field(default_factory=list)
    status: Literal["advisory_plan"] = "advisory_plan"
    destination_write_performed: Literal[False] = False
    engine_execution_performed: Literal[False] = False
    runtime_parity_verified: Literal[False] = False
    user_approval_required_before_destination_changes: Literal[True] = True
    created_at: AwareDatetime


class AdvancedMaterialHandoffReceipt(MaterialAuthoringStrictModel):
    """Bind one immutable advisory plan and prove no destination mutation occurred."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    plan_id: PortableId
    job_id: JobId
    request: ExactArtifact
    plan: ExactArtifact
    source_manifest_sha256: Sha256
    plan_sha256: Sha256
    status: Literal["published"] = "published"
    destination_write_performed: Literal[False] = False
    engine_execution_performed: Literal[False] = False
    runtime_parity_verified: Literal[False] = False
    created_at: AwareDatetime
