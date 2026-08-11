"""Strict MaterialAuthoring 0.1.0 companion contracts.

These contracts add run-owned local authoring evidence without changing the canonical
V0.5 MaterialPlan, ShaderRecipe, TextureManifest, or BakeManifest contracts.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
PORTABLE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"
JOB_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
SUPPORTED_RESOLUTION_TIERS = (256, 512, 1024, 2048, 4096)


def _validate_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by its owning job."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty normalized POSIX relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
PortableId = Annotated[str, Field(pattern=PORTABLE_ID_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
RelativePath = Annotated[str, AfterValidator(_validate_relative_path)]
UnitFloat = Annotated[float, Field(ge=0, le=1)]
ColorRGB = tuple[UnitFloat, UnitFloat, UnitFloat]
ColorRGBA = tuple[UnitFloat, UnitFloat, UnitFloat, UnitFloat]

RawPBRChannel = Literal[
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "height",
    "occlusion",
    "opacity",
    "emission",
]
ColorSpace = Literal["srgb", "non_color", "linear"]
MaterialAuthoringStrategy = Literal[
    "uniform_portable_fallback_v1",
    "user_image_pbr_v1",
    "localized_decal_v1",
    "planar_reference_patch_v1",
    "procedural_wood_v1",
    "procedural_metal_v1",
    "emissive_pattern_v1",
    "crystal_portable_approximation_v1",
]
MaterialFamily = Literal[
    "uniform_fallback",
    "user_image_pbr",
    "signage_decal",
    "planar_reference_patch",
    "wood",
    "metal",
    "emissive",
    "crystal",
]


class MaterialAuthoringStrictModel(BaseModel):
    """Reject undeclared fields and non-finite numeric material evidence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class ExactArtifact(MaterialAuthoringStrictModel):
    """Bind one non-empty job-contained file to its exact bytes and role."""

    artifact_id: PortableId
    kind: str = Field(min_length=1, max_length=96)
    path: RelativePath
    sha256: Sha256
    byte_size: int = Field(gt=0)
    media_type: str = Field(min_length=1, max_length=128)


class UVIdentitySnapshot(MaterialAuthoringStrictModel):
    """Store the exact current UV identity derived by a trusted inventory producer."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    semantic_id: str = Field(min_length=1, max_length=128)
    uv_set: str = Field(min_length=1, max_length=64)
    uv_fingerprint: Sha256
    ordered_polygon_corner_count: int = Field(ge=3)
    texel_density_px_m: float = Field(gt=0)


class UVIdentity(UVIdentitySnapshot):
    """Bind the current UV identity to an exact stale-detecting evidence artifact."""

    evidence: ExactArtifact


class ImageEvidence(MaterialAuthoringStrictModel):
    """Describe exact image bytes, interpretation, rights, provenance, and UV ownership."""

    source_id: PortableId
    channel: RawPBRChannel
    artifact: ExactArtifact
    width: int = Field(ge=1, le=32768)
    height: int = Field(ge=1, le=32768)
    color_space: ColorSpace
    license_id: str = Field(min_length=1, max_length=256)
    rights_status: Literal[
        "user_provided",
        "project_owned",
        "licensed",
        "public_domain",
        "unknown",
    ]
    provenance: str = Field(min_length=1, max_length=1024)
    uv_identity: UVIdentity
    normal_convention: Literal["opengl_y_plus", "directx_y_minus"] | None = None

    @model_validator(mode="after")
    def validate_channel_interpretation(self) -> ImageEvidence:
        """Reject color-space and normal-convention ambiguity for PBR inputs."""

        expected = "srgb" if self.channel in {"base_color", "emission"} else "non_color"
        if self.color_space != expected:
            raise ValueError(f"{self.channel} must use {expected} color space")
        if self.channel == "normal" and self.normal_convention is None:
            raise ValueError("normal images require an explicit normal convention")
        if self.channel != "normal" and self.normal_convention is not None:
            raise ValueError("normal_convention is valid only for a normal image")
        return self


class ResolutionSelectorInput(MaterialAuthoringStrictModel):
    """Freeze scale-aware inputs used by the bounded texture-resolution selector."""

    selector_id: PortableId
    material_family: MaterialFamily
    mapping_kind: Literal["unique", "tileable", "decal", "fallback"]
    projected_pixel_footprint: float = Field(gt=0)
    target_texel_density_px_m: float = Field(gt=0)
    longest_object_dimension_m: float = Field(gt=0)
    package_budget_bytes: int = Field(gt=0)
    requested_pixels: int | None = Field(default=None, ge=256, le=8192)

    @model_validator(mode="after")
    def validate_requested_tier(self) -> ResolutionSelectorInput:
        """Limit explicit requests to power-of-two tiers supported by this companion."""

        if self.requested_pixels is not None and self.requested_pixels not in {
            *SUPPORTED_RESOLUTION_TIERS,
            8192,
        }:
            raise ValueError("requested resolution must be 256..4096 or authorized 8192")
        return self

    def exact_sha256(self) -> str:
        """Hash the selector payload for a separate high-resolution authorization."""

        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class HighResolutionAuthorization(MaterialAuthoringStrictModel):
    """Authorize exactly one 8192 selection without weakening the normal 4K cap."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    authorization_id: PortableId
    selector_input_sha256: Sha256
    authorized_pixels: Literal[8192]
    purpose: Literal["material_authoring_resolution_above_4096"]
    authorized_by: Literal["user"]
    created_at: AwareDatetime


class ResolutionSelection(MaterialAuthoringStrictModel):
    """Record the selected tier, scale basis, budget clamp, and authorization state."""

    selector_input_sha256: Sha256
    selected_pixels: Literal[256, 512, 1024, 2048, 4096, 8192]
    unclamped_target_pixels: float = Field(gt=0)
    scale_context_recommendation: int = Field(gt=0)
    budget_limited: bool
    high_resolution_authorized: bool
    reasons: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_authorized_tier(self) -> ResolutionSelection:
        """Prevent an 8192 result from appearing without explicit authorization evidence."""

        if (self.selected_pixels > 4096) != self.high_resolution_authorized:
            raise ValueError("resolution authorization state contradicts selected tier")
        return self


class ScaleContextBinding(MaterialAuthoringStrictModel):
    """Bind and summarize one exact AssetScaleContext 0.1.0 artifact."""

    artifact: ExactArtifact
    asset_id: str = Field(min_length=1, max_length=128)
    source_fingerprint: Sha256
    shortest_dimension_m: float = Field(gt=0)
    longest_dimension_m: float = Field(gt=0)
    target_texel_density_px_m: float = Field(gt=0)


class V05StrategyCompanionMapping(MaterialAuthoringStrictModel):
    """Name the existing V0.5 uniform strategy without changing its bytes or enum."""

    legacy_strategy: Literal["portable_pbr_v05"] = "portable_pbr_v05"
    companion_strategy: Literal["uniform_portable_fallback_v1"] = "uniform_portable_fallback_v1"
    legacy_candidate_enum_unchanged: Literal[True] = True
    legacy_uniform_bytes_unchanged: Literal[True] = True


class UniformFallbackInput(MaterialAuthoringStrictModel):
    """Adopt exact existing uniform V0.5 outputs instead of regenerating their bytes."""

    mapping: V05StrategyCompanionMapping = Field(default_factory=V05StrategyCompanionMapping)
    existing_channels: list[ImageEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_legacy_bundle(self) -> UniformFallbackInput:
        """Preserve the legacy uniform candidate's exact 256-byte-set semantics."""

        names = [item.channel for item in self.existing_channels]
        if len(names) != len(set(names)):
            raise ValueError("legacy uniform channels must be unique")
        if any((item.width, item.height) != (256, 256) for item in self.existing_channels):
            raise ValueError("uniform_portable_fallback_v1 must adopt legacy 256 outputs")
        normals = [item for item in self.existing_channels if item.channel == "normal"]
        if any(item.normal_convention != "opengl_y_plus" for item in normals):
            raise ValueError("legacy uniform normal bytes must already use OpenGL +Y")
        return self


class UserImagePBRInput(MaterialAuthoringStrictModel):
    """Bind an exact set of user-supplied PBR channels with one UV identity."""

    channels: list[ImageEvidence] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_channel_set(self) -> UserImagePBRInput:
        """Require unique channels and a shared non-stale UV identity."""

        names = [item.channel for item in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("user image PBR channels must be unique")
        uv = self.channels[0].uv_identity
        if any(item.uv_identity != uv for item in self.channels[1:]):
            raise ValueError("all user image PBR channels must bind the same UV identity")
        return self


class UVRect(MaterialAuthoringStrictModel):
    """Place one localized decal inside a bounded normalized UV rectangle."""

    minimum: tuple[float, float]
    maximum: tuple[float, float]

    @model_validator(mode="after")
    def validate_rect(self) -> UVRect:
        """Require a positive normalized UV extent."""

        values = (*self.minimum, *self.maximum)
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("UV rectangle coordinates must remain in [0, 1]")
        if self.minimum[0] >= self.maximum[0] or self.minimum[1] >= self.maximum[1]:
            raise ValueError("UV rectangle must have positive area")
        return self


class ProjectLocalFont(MaterialAuthoringStrictModel):
    """Bind an exact contained project font used for deterministic text rasterization."""

    artifact: ExactArtifact
    font_format: Literal["truetype_opentype", "bitmap_json_v1"] = "truetype_opentype"
    face_index: int = Field(default=0, ge=0, le=32)
    license_id: str = Field(min_length=1, max_length=256)
    rights_status: Literal[
        "project_owned",
        "licensed",
        "public_domain",
        "unknown",
    ]
    provenance: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_font_media(self) -> ProjectLocalFont:
        """Accept only contained OpenType or TrueType font artifacts."""

        outline_media = {
            "font/ttf",
            "font/otf",
            "application/x-font-ttf",
            "application/vnd.ms-opentype",
        }
        if (
            self.font_format == "truetype_opentype"
            and self.artifact.media_type not in outline_media
        ):
            raise ValueError("localized outline text requires a project-local TTF or OTF font")
        if self.font_format == "bitmap_json_v1" and self.artifact.media_type != "application/json":
            raise ValueError("project bitmap fonts require an exact local JSON artifact")
        if self.font_format == "bitmap_json_v1" and self.face_index != 0:
            raise ValueError("project bitmap fonts do not support face indices")
        return self


class LocalizedDecalInput(MaterialAuthoringStrictModel):
    """Describe an exact image or non-invented text decal with mip-safe placement."""

    source_kind: Literal["user_image", "text"]
    image: ImageEvidence | None = None
    text_evidence: Literal["exact_user_text", "unknown_text", "inferred_placeholder"] | None = None
    text: str | None = Field(default=None, max_length=512)
    font: ProjectLocalFont | None = None
    uv_identity: UVIdentity
    uv_rect: UVRect
    clip_mode: Literal["clip", "clamp"] = "clip"
    mip_padding_px: int = Field(ge=2, le=128)
    base_color: ColorRGBA = (1.0, 1.0, 1.0, 1.0)
    roughness: float = Field(default=0.5, ge=0, le=1)
    normal_strength: float = Field(default=0.0, ge=0, le=1)
    emission_color: ColorRGB = (0.0, 0.0, 0.0)
    emission_strength: float = Field(default=0.0, ge=0, le=1000)

    @model_validator(mode="after")
    def validate_source(self) -> LocalizedDecalInput:
        """Forbid invented text and require exact local evidence for rasterization."""

        if self.source_kind == "user_image":
            if self.image is None or any(
                value is not None for value in (self.text_evidence, self.text, self.font)
            ):
                raise ValueError("image decals require only one exact image source")
            if self.image.uv_identity != self.uv_identity:
                raise ValueError("image decal UV identity is stale or mismatched")
            if self.image.channel != "base_color":
                raise ValueError("localized image decals require base_color image evidence")
        else:
            if self.image is not None or self.text_evidence is None:
                raise ValueError("text decals require text evidence and no image source")
            if self.text_evidence == "exact_user_text":
                if not self.text or self.font is None:
                    raise ValueError("exact text requires user text and a project-local font")
            elif self.text is not None or self.font is not None:
                raise ValueError("unknown or inferred text cannot carry invented glyph content")
        return self


class PlanarReferencePatchInput(MaterialAuthoringStrictModel):
    """Bind one exact observed planar reference region and its rectification settings."""

    reference_image: ImageEvidence
    source_semantic_id: str = Field(min_length=1, max_length=128)
    evidence_status: Literal["observed", "inferred"]
    confidence: float = Field(ge=0, le=1)
    corners_px: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]
    corner_order: Literal["upper_left_upper_right_lower_right_lower_left"] = (
        "upper_left_upper_right_lower_right_lower_left"
    )
    corner_source: Literal["user_confirmed", "advisory_candidate"]
    rectification_method: Literal["perspective_homography_v1"] = "perspective_homography_v1"
    crop_px: tuple[int, int, int, int] | None = None
    mask: ExactArtifact | None = None
    cleanup: Literal["none", "alpha_trim"] = "none"
    uv_identity: UVIdentity
    mip_padding_px: int = Field(ge=2, le=128)

    @model_validator(mode="after")
    def validate_patch(self) -> PlanarReferencePatchInput:
        """Keep inferred or auto-detected corners advisory and inside the source image."""

        for x, y in self.corners_px:
            if not 0 <= x < self.reference_image.width or not 0 <= y < self.reference_image.height:
                raise ValueError("planar patch corners must lie inside the source image")
        if self.crop_px is not None:
            left, top, right, bottom = self.crop_px
            if not (0 <= left < right <= self.reference_image.width):
                raise ValueError("planar patch crop has invalid horizontal bounds")
            if not (0 <= top < bottom <= self.reference_image.height):
                raise ValueError("planar patch crop has invalid vertical bounds")
            if any(not left <= x < right or not top <= y < bottom for x, y in self.corners_px):
                raise ValueError("planar patch crop must contain every rectification corner")
        if self.reference_image.channel != "base_color":
            raise ValueError("planar reference patches require base_color image evidence")
        if self.corner_source == "advisory_candidate" and self.evidence_status != "inferred":
            raise ValueError("automatic corner candidates cannot be recorded as observed truth")
        return self


class ProceduralWoodInput(MaterialAuthoringStrictModel):
    """Describe deterministic scale-aware wood grain and portable raw channels."""

    grain_axis: Literal["x", "y", "z"]
    grain_frequency_m: float = Field(gt=0)
    growth_ring_scale_m: float = Field(gt=0)
    knot_seed: int = Field(ge=0, le=2**31 - 1)
    knot_count: int = Field(ge=0, le=64)
    earlywood_color: ColorRGB
    latewood_color: ColorRGB
    earlywood_latewood_contrast: float = Field(ge=0, le=1)
    roughness_base: float = Field(ge=0, le=1)
    roughness_variation: float = Field(ge=0, le=0.5)
    pore_bump_scale_m: float = Field(gt=0)
    end_grain_mask: ExactArtifact | None = None
    finish_coating_amount: float = Field(ge=0, le=1)
    intended_real_world_scale_m: float = Field(gt=0)
    deterministic_seed: int = Field(ge=0, le=2**31 - 1)
    mapping: Literal["uv", "triplanar"]
    uv_identity: UVIdentity


class ProceduralMetalInput(MaterialAuthoringStrictModel):
    """Describe deterministic metal without unsupported evidence-free scratches."""

    base_metal: Literal["aluminum", "steel", "iron", "copper", "brass", "custom"]
    base_color: ColorRGB
    roughness_base: float = Field(ge=0, le=1)
    roughness_variation: float = Field(ge=0, le=0.35)
    brushed_direction: Literal["x", "y", "radial", "none"]
    brush_scale_m: float = Field(gt=0)
    subtle_normal_strength: float = Field(ge=0, le=0.35)
    edge_wear_mask: ExactArtifact | None = None
    unsupported_scratches: Literal[False] = False
    intended_real_world_scale_m: float = Field(gt=0)
    deterministic_seed: int = Field(ge=0, le=2**31 - 1)
    uv_identity: UVIdentity


class EmissivePatternInput(MaterialAuthoringStrictModel):
    """Describe one deterministic emission pattern at a stated physical scale."""

    pattern: Literal["solid", "stripes", "grid", "cells"]
    base_color: ColorRGB
    emission_color: ColorRGB
    emission_strength: float = Field(gt=0, le=1000)
    pattern_scale_m: float = Field(gt=0)
    duty_cycle: float = Field(gt=0, lt=1)
    opacity: float = Field(default=1.0, ge=0, le=1)
    intended_real_world_scale_m: float = Field(gt=0)
    deterministic_seed: int = Field(ge=0, le=2**31 - 1)
    uv_identity: UVIdentity


class CrystalPortableInput(MaterialAuthoringStrictModel):
    """Separate Blender master transmission intent from a lossy portable PBR fallback."""

    ior: float = Field(ge=1, le=3)
    transmission: float = Field(ge=0, le=1)
    roughness: float = Field(ge=0, le=1)
    absorption_tint: ColorRGB
    absorption_distance_m: float = Field(gt=0)
    fresnel_strength: float = Field(ge=0, le=1)
    emission_color: ColorRGB
    emission_strength: float = Field(ge=0, le=1000)
    thickness_approximation_m: float | None = Field(default=None, gt=0)
    opacity_approximation: float = Field(ge=0, le=1)
    intended_real_world_scale_m: float = Field(gt=0)
    uv_identity: UVIdentity


class AdvancedPreviewPolicy(MaterialAuthoringStrictModel):
    """Keep neutral-studio evidence distinct from optional reference-matched review."""

    neutral_studio_required: Literal[True] = True
    reference_matched_requested: bool = False
    reference_artifact: ExactArtifact | None = None
    reference_matched_never_sufficient_alone: Literal[True] = True

    @model_validator(mode="after")
    def validate_reference_binding(self) -> AdvancedPreviewPolicy:
        """Require an exact reference only when a matched preview was requested."""

        if self.reference_matched_requested != (self.reference_artifact is not None):
            raise ValueError("reference preview request must bind one exact reference artifact")
        return self


class MaterialAuthoringRequest(MaterialAuthoringStrictModel):
    """Freeze one run-owned deterministic authoring request and all canonical inputs."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    request_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    run_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    strategy: MaterialAuthoringStrategy
    output_root: RelativePath
    source_v05_contracts: list[ExactArtifact] = Field(min_length=1)
    scale_context: ScaleContextBinding
    resolution: ResolutionSelectorInput
    high_resolution_authorization: ExactArtifact | None = None
    preview_policy: AdvancedPreviewPolicy
    uniform_fallback: UniformFallbackInput | None = None
    user_image_pbr: UserImagePBRInput | None = None
    localized_decal: LocalizedDecalInput | None = None
    planar_reference_patch: PlanarReferencePatchInput | None = None
    procedural_wood: ProceduralWoodInput | None = None
    procedural_metal: ProceduralMetalInput | None = None
    emissive_pattern: EmissivePatternInput | None = None
    crystal: CrystalPortableInput | None = None
    canonical_write_authority: Literal[False] = False
    destination_write_authority: Literal[False] = False
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_strategy_payload(self) -> MaterialAuthoringRequest:
        """Require exactly the parameter contract matching the selected strategy."""

        expected = {
            "uniform_portable_fallback_v1": "uniform_fallback",
            "user_image_pbr_v1": "user_image_pbr",
            "localized_decal_v1": "localized_decal",
            "planar_reference_patch_v1": "planar_reference_patch",
            "procedural_wood_v1": "procedural_wood",
            "procedural_metal_v1": "procedural_metal",
            "emissive_pattern_v1": "emissive_pattern",
            "crystal_portable_approximation_v1": "crystal",
        }[self.strategy]
        names = (
            "uniform_fallback",
            "user_image_pbr",
            "localized_decal",
            "planar_reference_patch",
            "procedural_wood",
            "procedural_metal",
            "emissive_pattern",
            "crystal",
        )
        present = [name for name in names if getattr(self, name) is not None]
        if present != [expected]:
            raise ValueError(f"strategy requires only {expected}; received {present}")
        expected_root = f"material_authoring/runs/{self.run_id}"
        if self.output_root != expected_root:
            raise ValueError(f"output_root must equal {expected_root}")
        if self.resolution.material_family != self.material_family():
            raise ValueError("resolution material family contradicts authoring strategy")
        allowed_v05_kinds = {
            "v05-material-plan",
            "v05-shader-recipe",
            "v05-texture-manifest",
            "v05-bake-manifest",
        }
        if any(item.kind not in allowed_v05_kinds for item in self.source_v05_contracts):
            raise ValueError("source_v05_contracts contains an undeclared V0.5 role")
        if "v05-material-plan" not in {item.kind for item in self.source_v05_contracts}:
            raise ValueError("material authoring requires one exact V0.5 MaterialPlan")
        if len({item.path for item in self.source_v05_contracts}) != len(self.source_v05_contracts):
            raise ValueError("source_v05_contracts paths must be unique")
        if self.scale_context.artifact.kind != "asset-scale-context":
            raise ValueError("scale_context must bind an AssetScaleContext artifact")
        return self

    def material_family(self) -> MaterialFamily:
        """Map a strategy name to its stable material-family quality category."""

        return {
            "uniform_portable_fallback_v1": "uniform_fallback",
            "user_image_pbr_v1": "user_image_pbr",
            "localized_decal_v1": "signage_decal",
            "planar_reference_patch_v1": "planar_reference_patch",
            "procedural_wood_v1": "wood",
            "procedural_metal_v1": "metal",
            "emissive_pattern_v1": "emissive",
            "crystal_portable_approximation_v1": "crystal",
        }[self.strategy]  # type: ignore[return-value]


class AuthoredChannel(MaterialAuthoringStrictModel):
    """Bind one run-owned raw PBR output and the exact evidence that produced it."""

    channel: RawPBRChannel
    artifact: ExactArtifact
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    color_space: ColorSpace
    uv_identity: UVIdentity
    source_artifact_sha256: list[Sha256] = Field(default_factory=list)
    normal_convention: Literal["opengl_y_plus"] | None = None

    @model_validator(mode="after")
    def validate_channel(self) -> AuthoredChannel:
        """Keep output channel interpretation explicit and role-correct."""

        expected = "srgb" if self.channel in {"base_color", "emission"} else "non_color"
        if self.color_space != expected:
            raise ValueError(f"authored {self.channel} must use {expected}")
        if self.channel == "normal" and self.normal_convention != "opengl_y_plus":
            raise ValueError("authored normals must declare OpenGL +Y convention")
        if self.channel != "normal" and self.normal_convention is not None:
            raise ValueError("normal convention is valid only for normal outputs")
        return self


class MasterMaterialIntent(MaterialAuthoringStrictModel):
    """Describe Blender master intent separately from portable approximation claims."""

    shader_family: MaterialFamily
    features: list[str] = Field(min_length=1)
    blender_compilation_status: Literal["not_run", "passed", "failed"] = "not_run"
    blender_fixture: ExactArtifact | None = None
    portable_approximation: str = Field(min_length=1, max_length=1024)
    known_losses: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_blender_status(self) -> MasterMaterialIntent:
        """Require exact Blender evidence only for a claimed successful compile."""

        if self.blender_compilation_status == "not_run" and self.blender_fixture is not None:
            raise ValueError("not-run Blender compilation cannot carry fixture evidence")
        if self.blender_compilation_status in {"passed", "failed"} and self.blender_fixture is None:
            raise ValueError("executed Blender compilation requires one exact fixture artifact")
        return self


class PreviewEvidenceState(MaterialAuthoringStrictModel):
    """Record neutral and reference preview states without conflating their authority."""

    neutral_studio_status: Literal["not_run", "passed", "failed"]
    neutral_studio_artifact: ExactArtifact | None = None
    reference_matched_status: Literal["not_requested", "not_run", "passed", "failed"]
    reference_matched_artifact: ExactArtifact | None = None
    neutral_studio_required_for_quality: Literal[True] = True
    reference_matched_never_sufficient_alone: Literal[True] = True

    @model_validator(mode="after")
    def validate_preview_receipts(self) -> PreviewEvidenceState:
        """Match successful preview states to exact immutable image artifacts."""

        neutral_executed = self.neutral_studio_status in {"passed", "failed"}
        if neutral_executed != (self.neutral_studio_artifact is not None):
            raise ValueError("executed neutral preview requires one exact artifact")
        reference_executed = self.reference_matched_status in {"passed", "failed"}
        if reference_executed != (self.reference_matched_artifact is not None):
            raise ValueError("executed reference preview requires one exact artifact")
        return self


class AuthoredMaterialManifest(MaterialAuthoringStrictModel):
    """Record exact run-owned channels, scale, preview separation, and limitations."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    manifest_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    run_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    strategy: MaterialAuthoringStrategy
    material_family: MaterialFamily
    request: ExactArtifact
    source_v05_contracts: list[ExactArtifact] = Field(min_length=1)
    scale_context: ScaleContextBinding
    resolution: ResolutionSelection
    channels: list[AuthoredChannel]
    master_intent: MasterMaterialIntent
    preview_evidence: PreviewEvidenceState
    source_to_output_provenance_sha256: Sha256
    status: Literal["completed", "review_required", "unverified"]
    limitations: list[str] = Field(default_factory=list)
    canonical_v05_unchanged: Literal[True] = True
    destination_write_performed: Literal[False] = False
    runtime_parity_verified: Literal[False] = False
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_outputs(self) -> AuthoredMaterialManifest:
        """Require unique raw channels and honest verification status."""

        names = [item.channel for item in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("authored material channels must be unique")
        if self.master_intent.blender_compilation_status != "passed" and (
            self.status == "completed"
        ):
            raise ValueError("unverified Blender master intent cannot claim completed")
        return self


class MaterialAuthoringReceipt(MaterialAuthoringStrictModel):
    """Bind a published run directory to its exact request, manifest, and output set."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    receipt_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    run_id: PortableId
    request: ExactArtifact
    manifest: ExactArtifact
    outputs: list[ExactArtifact]
    output_bundle_sha256: Sha256
    status: Literal["published"] = "published"
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False
    created_at: AwareDatetime
