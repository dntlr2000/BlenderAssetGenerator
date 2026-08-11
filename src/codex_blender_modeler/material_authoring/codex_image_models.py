"""Strict MaterialAuthoring 0.2.1 companion contracts for Codex image candidates.

The companion is additive: it never changes MaterialAuthoring 0.1.0 or canonical V0.5
contracts.  Every source is exact evidence and every output remains staging-only until
an authorized controller promotes a separately reviewed material candidate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from .models import (
    ColorRGBA,
    ColorSpace,
    ExactArtifact,
    JobId,
    MaterialAuthoringStrictModel,
    MaterialFamily,
    PortableId,
    ProjectLocalFont,
    RawPBRChannel,
    RelativePath,
    ScaleContextBinding,
    Sha256,
    UVIdentity,
    UVRect,
)

SCHEMA_VERSION = "0.2.1"

__all__ = [
    "CodexImageAuthoredMaterialManifestV021",
    "CodexImageChannelDerivationV021",
    "CodexImageEvidenceBindingsV021",
    "CodexImageMaterialAuthoringReceiptV021",
    "CodexImageMaterialAuthoringRequestV021",
    "CodexImageMaterialQualityV021",
    "CodexImageMaterialSourceV021",
    "ExactSignageTextEvidenceV021",
    "ExactTextCompositionReceiptV021",
    "ExactTextCompositionV021",
    "LocalImageDerivationPolicyV021",
    "SCHEMA_VERSION",
]

CodexImageMaterialStrategy = Literal[
    "codex_generated_base_color_v1",
    "codex_generated_decal_v1",
    "codex_generated_emission_v1",
    "codex_generated_procedural_hybrid_v1",
]
DirectImageRole = Literal["base_color", "decal_rgb", "emission", "opacity_source"]
ChannelProvenanceKind = Literal[
    "codex_generated_direct",
    "local_deterministic_derivation",
    "local_exact_text_composition",
    "local_constant",
]


class CodexImageEvidenceBindingsV021(MaterialAuthoringStrictModel):
    """Bind the selected core records to immutable job-contained JSON artifacts."""

    selection: ExactArtifact
    selected_evidence: ExactArtifact
    selected_quality_report: ExactArtifact
    adoption: ExactArtifact

    @model_validator(mode="after")
    def validate_declared_roles(self) -> CodexImageEvidenceBindingsV021:
        """Reject swapped, duplicated, or ambiguously typed core evidence links."""

        expected = {
            "selection": "codex-image-generation-selection",
            "selected_evidence": "codex-generated-image-evidence",
            "selected_quality_report": "codex-image-generation-quality-report",
            "adoption": "codex-image-material-adoption",
        }
        artifacts = {
            "selection": self.selection,
            "selected_evidence": self.selected_evidence,
            "selected_quality_report": self.selected_quality_report,
            "adoption": self.adoption,
        }
        for name, artifact in artifacts.items():
            if artifact.kind != expected[name]:
                raise ValueError(f"{name} must have kind {expected[name]}")
        paths = [artifact.path for artifact in artifacts.values()]
        if len(paths) != len(set(paths)):
            raise ValueError("core image evidence paths must be unique")
        return self


class CodexImageMaterialSourceV021(MaterialAuthoringStrictModel):
    """Describe the exact selected raster and its only permitted direct semantic role."""

    artifact: ExactArtifact
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    direct_role: DirectImageRole
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

    @model_validator(mode="after")
    def validate_source_interpretation(self) -> CodexImageMaterialSourceV021:
        """Keep generated color roles in sRGB and opacity evidence non-color."""

        expected = "non_color" if self.direct_role == "opacity_source" else "srgb"
        if self.color_space != expected:
            raise ValueError(f"{self.direct_role} source must use {expected} color space")
        if self.artifact.media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("Codex image material sources must be PNG, JPEG, or WebP")
        return self


class ExactSignageTextEvidenceV021(MaterialAuthoringStrictModel):
    """Bind exact user signage text separately from generated background imagery."""

    schema_version: Literal["0.2.1"] = SCHEMA_VERSION
    evidence_id: PortableId
    text: str = Field(min_length=1, max_length=512)
    text_sha256: Sha256
    evidence: Literal["exact_user_text"] = "exact_user_text"
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_text_digest(self) -> ExactSignageTextEvidenceV021:
        """Require the stored digest to match the exact UTF-8 signage text bytes."""

        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.text_sha256 != digest:
            raise ValueError("exact signage text hash does not match its UTF-8 bytes")
        return self


class ExactTextCompositionV021(MaterialAuthoringStrictModel):
    """Freeze exact local signage text, or explicitly record that no glyph may be made."""

    evidence: Literal["exact_user_text", "unknown_text", "inferred_placeholder"]
    text: str | None = Field(default=None, max_length=512)
    text_evidence_artifact: ExactArtifact | None = None
    font: ProjectLocalFont | None = None
    uv_rect: UVRect
    color: ColorRGBA = (1.0, 1.0, 1.0, 1.0)
    font_size_px: int = Field(default=48, ge=4, le=1024)
    horizontal_alignment: Literal["left", "center", "right"] = "center"
    vertical_alignment: Literal["top", "center", "bottom"] = "center"
    clip_mode: Literal["clip"] = "clip"

    @model_validator(mode="after")
    def validate_non_invention(self) -> ExactTextCompositionV021:
        """Require exact text plus an exact local font, and forbid placeholder glyphs."""

        if self.evidence == "exact_user_text":
            if not self.text or self.text_evidence_artifact is None or self.font is None:
                raise ValueError(
                    "exact signage text requires text evidence and a project-local font"
                )
        elif any(
            value is not None
            for value in (self.text, self.text_evidence_artifact, self.font)
        ):
            raise ValueError("unknown or inferred signage text cannot carry invented glyphs")
        return self


class LocalImageDerivationPolicyV021(MaterialAuthoringStrictModel):
    """Bound deterministic host-side normalization and PBR derivation parameters."""

    algorithm_version: Literal["codex_image_local_derivation_v1"] = (
        "codex_image_local_derivation_v1"
    )
    output_resolution: Literal[256, 512, 1024, 2048, 4096]
    low_frequency_radius_px: int = Field(default=24, ge=1, le=128)
    lighting_removal_strength: float = Field(default=0.75, ge=0, le=1)
    height_strength: float = Field(default=0.25, ge=0, le=1)
    normal_strength: float = Field(default=1.0, ge=0, le=8)
    roughness_base: float = Field(default=0.55, ge=0, le=1)
    roughness_variation: float = Field(default=0.2, ge=0, le=0.5)
    occlusion_strength: float = Field(default=0.2, ge=0, le=1)
    derive_occlusion: bool = True
    expected_grain_axis: Literal["x", "y", "none"] = "none"
    minimum_spatial_standard_deviation: float = Field(default=0.02, ge=0, le=1)
    maximum_offset_edge_rmse: float = Field(default=0.18, ge=0, le=1)

    def exact_sha256(self) -> str:
        """Hash the bounded derivation policy for per-channel provenance evidence."""

        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class CodexImageMaterialAuthoringRequestV021(MaterialAuthoringStrictModel):
    """Freeze one run-owned image-to-material derivation without promotion authority."""

    schema_version: Literal["0.2.1"] = SCHEMA_VERSION
    request_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    run_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    strategy: CodexImageMaterialStrategy
    material_family: MaterialFamily
    output_root: RelativePath
    core_evidence: CodexImageEvidenceBindingsV021
    source: CodexImageMaterialSourceV021
    source_v05_contracts: list[ExactArtifact] = Field(min_length=1)
    uv_identity: UVIdentity
    scale_context: ScaleContextBinding
    derivation: LocalImageDerivationPolicyV021
    exact_text: ExactTextCompositionV021 | None = None
    base_roughness: float = Field(default=0.5, ge=0, le=1)
    emission_strength: float = Field(default=1.0, ge=0, le=1000)
    canonical_write_authority: Literal[False] = False
    destination_write_authority: Literal[False] = False
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_strategy_boundary(self) -> CodexImageMaterialAuthoringRequestV021:
        """Match strategy, family, source role, text authority, and staging root exactly."""

        allowed = {
            "codex_generated_base_color_v1": (
                {"base_color", "opacity_source"},
                {"user_image_pbr", "planar_reference_patch"},
            ),
            "codex_generated_decal_v1": (
                {"decal_rgb", "base_color", "opacity_source"},
                {"signage_decal"},
            ),
            "codex_generated_emission_v1": (
                {"emission", "opacity_source"},
                {"emissive", "crystal"},
            ),
            "codex_generated_procedural_hybrid_v1": (
                {"base_color", "emission"},
                {"wood", "crystal"},
            ),
        }
        roles, families = allowed[self.strategy]
        if self.source.direct_role not in roles:
            raise ValueError("selected direct image role is incompatible with material strategy")
        if self.material_family not in families:
            raise ValueError("material family is incompatible with image material strategy")
        if (self.strategy == "codex_generated_decal_v1") != (self.exact_text is not None):
            raise ValueError("only a decal strategy may carry exact-text composition state")
        expected_root = f"material_authoring/codex_imagegen/runs/{self.run_id}"
        if self.output_root != expected_root:
            raise ValueError(f"output_root must equal {expected_root}")
        if self.derivation.expected_grain_axis != "none" and self.material_family != "wood":
            raise ValueError("grain-axis checks are valid only for wood hybrid materials")
        kinds = {artifact.kind for artifact in self.source_v05_contracts}
        if "v05-material-plan" not in kinds:
            raise ValueError("image material authoring requires one exact V0.5 MaterialPlan")
        if any(
            artifact.kind
            not in {
                "v05-material-plan",
                "v05-shader-recipe",
                "v05-texture-manifest",
                "v05-bake-manifest",
            }
            for artifact in self.source_v05_contracts
        ):
            raise ValueError("source_v05_contracts contains an undeclared V0.5 role")
        if len({item.path for item in self.source_v05_contracts}) != len(
            self.source_v05_contracts
        ):
            raise ValueError("source_v05_contracts paths must be unique")
        return self


class CodexImageChannelDerivationV021(MaterialAuthoringStrictModel):
    """Bind one raw output channel to a direct or local deterministic decision."""

    channel: RawPBRChannel
    provenance_kind: ChannelProvenanceKind
    algorithm_id: str = Field(min_length=1, max_length=128)
    algorithm_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    source_sha256: list[Sha256] = Field(min_length=1)
    parameters: dict[str, bool | int | float | str]
    parameters_sha256: Sha256
    output: ExactArtifact
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)
    color_space: ColorSpace
    uv_identity: UVIdentity
    normal_convention: Literal["opengl_y_plus"] | None = None

    @model_validator(mode="after")
    def validate_channel_provenance(self) -> CodexImageChannelDerivationV021:
        """Forbid generated pseudo-PBR adoption and verify deterministic parameters."""

        if self.provenance_kind == "codex_generated_direct" and self.channel not in {
            "base_color",
            "emission",
            "opacity",
        }:
            raise ValueError("Codex-generated bytes cannot directly supply derived PBR channels")
        expected_space = "srgb" if self.channel in {"base_color", "emission"} else "non_color"
        if self.color_space != expected_space:
            raise ValueError(f"{self.channel} output must use {expected_space}")
        if self.channel == "normal" and self.normal_convention != "opengl_y_plus":
            raise ValueError("derived normals must declare OpenGL +Y")
        if self.channel != "normal" and self.normal_convention is not None:
            raise ValueError("normal_convention is valid only for normal output")
        digest = hashlib.sha256(
            json.dumps(
                self.parameters,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.parameters_sha256 != digest:
            raise ValueError("channel parameters_sha256 does not match parameters")
        return self


class ExactTextCompositionReceiptV021(MaterialAuthoringStrictModel):
    """Record whether exact text was locally rasterized without inventing content."""

    evidence: Literal["exact_user_text", "unknown_text", "inferred_placeholder"]
    rendered: bool
    text_sha256: Sha256 | None = None
    font: ExactArtifact | None = None
    output: ExactArtifact | None = None
    glyph_count: int = Field(ge=0)
    algorithm_id: Literal["project_local_exact_text_composition_v1"]

    @model_validator(mode="after")
    def validate_receipt_state(self) -> ExactTextCompositionReceiptV021:
        """Require complete exact evidence for rendering and none for unknown glyphs."""

        if self.evidence == "exact_user_text":
            if (
                not self.rendered
                or self.text_sha256 is None
                or self.font is None
                or self.output is None
            ):
                raise ValueError("rendered exact text requires text, font, and output evidence")
            if self.glyph_count <= 0:
                raise ValueError("rendered exact text must contain at least one glyph")
        elif self.rendered or any(
            value is not None for value in (self.text_sha256, self.font, self.output)
        ) or self.glyph_count != 0:
            raise ValueError("unknown or inferred text must not claim rendered glyph evidence")
        return self


class CodexImageMaterialQualityV021(MaterialAuthoringStrictModel):
    """Store deterministic image suitability checks without claiming human review."""

    decoded: bool
    dimensions_match: bool
    spatial_standard_deviation: float = Field(ge=0, le=1)
    offset_edge_rmse: float = Field(ge=0, le=1)
    detected_grain_axis: Literal["x", "y", "none", "ambiguous"]
    grain_axis_matches: bool | None = None
    direct_role_allowed: Literal[True] = True
    local_derivations_source_bound: Literal[True] = True
    human_reviewed: Literal[False] = False
    outcome: Literal["passed", "review_required", "failed"]
    reasons: list[str] = Field(default_factory=list)


class CodexImageAuthoredMaterialManifestV021(MaterialAuthoringStrictModel):
    """Record a staging-only image-derived material candidate and honest limitations."""

    schema_version: Literal["0.2.1"] = SCHEMA_VERSION
    manifest_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    run_id: PortableId
    material_id: str = Field(min_length=1, max_length=128)
    strategy: CodexImageMaterialStrategy
    material_family: MaterialFamily
    request: ExactArtifact
    core_evidence: CodexImageEvidenceBindingsV021
    source: CodexImageMaterialSourceV021
    source_v05_contracts: list[ExactArtifact] = Field(min_length=1)
    uv_identity: UVIdentity
    scale_context: ScaleContextBinding
    derivation_policy_sha256: Sha256
    channels: list[CodexImageChannelDerivationV021] = Field(min_length=1)
    exact_text: ExactTextCompositionReceiptV021 | None = None
    quality: CodexImageMaterialQualityV021
    status: Literal["candidate_ready", "review_required"]
    limitations: list[str] = Field(default_factory=list)
    staging_only: Literal[True] = True
    canonical_v05_unchanged: Literal[True] = True
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False
    actual_codex_imagegen_execution_verified: Literal[False] = False
    blender_compilation_status: Literal["not_run"] = "not_run"
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_manifest(self) -> CodexImageAuthoredMaterialManifestV021:
        """Require unique channels and prevent a failed local gate from appearing ready."""

        names = [channel.channel for channel in self.channels]
        if len(names) != len(set(names)):
            raise ValueError("image-derived material channels must be unique")
        if self.status == "candidate_ready" and self.quality.outcome != "passed":
            raise ValueError("candidate_ready requires passed deterministic material checks")
        if (self.strategy == "codex_generated_decal_v1") != (self.exact_text is not None):
            raise ValueError("decal manifests require exact-text composition state")
        return self


class CodexImageMaterialAuthoringReceiptV021(MaterialAuthoringStrictModel):
    """Bind one atomically published staging run to request, manifest, and raw channels."""

    schema_version: Literal["0.2.1"] = SCHEMA_VERSION
    receipt_id: PortableId
    job_id: JobId
    workflow_id: PortableId
    run_id: PortableId
    request: ExactArtifact
    manifest: ExactArtifact
    outputs: list[ExactArtifact] = Field(min_length=1)
    output_bundle_sha256: Sha256
    status: Literal["published_to_staging"] = "published_to_staging"
    staging_only: Literal[True] = True
    canonical_write_performed: Literal[False] = False
    destination_write_performed: Literal[False] = False
    created_at: AwareDatetime
