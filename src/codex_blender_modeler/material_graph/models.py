"""Versioned whitelist-only contracts for layered portable material authoring."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

SCHEMA_VERSION = "0.1.0"

MaterialChannel = Literal[
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "height",
    "occlusion",
    "emission",
    "opacity",
]
ColorSpace = Literal["sRGB", "Non-Color"]
Vec4 = tuple[float, float, float, float]


class MaterialGraphStrictModel(BaseModel):
    """Reject undeclared fields and non-finite values in graph contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class MaterialGraphArtifact(MaterialGraphStrictModel):
    """Bind one contained graph input to a portable path and exact digest."""

    role: Literal[
        "scene_spec",
        "material_plan",
        "shader_recipe",
        "texture",
        "reference",
        "mask",
        "other",
    ]
    path: RelativePath
    sha256: Sha256


class MaterialGraphProvenance(MaterialGraphStrictModel):
    """Freeze job, workflow, dispatch, contract, and exact input provenance."""

    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    project_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    material_contract_version: Literal["0.5.0"] = "0.5.0"
    graph_contract_version: Literal["0.1.0"] = SCHEMA_VERSION
    inputs: list[MaterialGraphArtifact] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_inputs(self) -> MaterialGraphProvenance:
        """Require unique paths and the canonical material-plan binding."""

        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("material graph provenance paths must be unique")
        if not any(item.role == "material_plan" for item in self.inputs):
            raise ValueError("material graph provenance requires a material_plan input")
        return self


class TextureScale(MaterialGraphStrictModel):
    """Describe physical texture size without relying on arbitrary node transforms."""

    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    uv_set: str = Field(default="UVMap", min_length=1, max_length=128)


class ChannelBinding(MaterialGraphStrictModel):
    """Bind one PBR channel to a constant or immutable image source."""

    channel: MaterialChannel
    source_kind: Literal["constant", "image"]
    color_space: ColorSpace
    constant: float | Vec4 | None = None
    image: MaterialGraphArtifact | None = None
    physical_scale: TextureScale | None = None
    sampling: Literal["repeat", "clamp", "clip"] = "repeat"
    localized_detail: bool = False
    normal_format: Literal["OpenGL", "DirectX"] | None = None

    @model_validator(mode="after")
    def validate_channel_source(self) -> ChannelBinding:
        """Enforce portable color-space and localized-detail sampling rules."""

        data_channels = {
            "roughness",
            "metallic",
            "normal",
            "height",
            "occlusion",
            "opacity",
        }
        if self.channel in data_channels and self.color_space != "Non-Color":
            raise ValueError(f"{self.channel} must use Non-Color")
        if self.source_kind == "image":
            if self.image is None or self.image.role != "texture":
                raise ValueError("image channel requires a role=texture artifact")
            if self.constant is not None:
                raise ValueError("image channel cannot also carry a constant")
            if self.physical_scale is None:
                raise ValueError("image channel requires physical texture scale")
        else:
            if self.constant is None or self.image is not None or self.physical_scale is not None:
                raise ValueError("constant channel requires only a constant value")
        if self.localized_detail and self.sampling == "repeat":
            raise ValueError("localized details must use clamp or clip sampling")
        if self.channel == "normal" and self.normal_format is None:
            raise ValueError("normal channels require an explicit normal format")
        if self.channel != "normal" and self.normal_format is not None:
            raise ValueError("normal_format is valid only for the normal channel")
        return self


class ImageMask(MaterialGraphStrictModel):
    """Mask a layer by one immutable non-color image."""

    kind: Literal["image"] = "image"
    image: MaterialGraphArtifact
    channel: Literal["R", "G", "B", "A", "luminance"] = "luminance"
    color_space: Literal["Non-Color"] = "Non-Color"
    sampling: Literal["clamp", "clip"] = "clamp"
    invert: bool = False

    @model_validator(mode="after")
    def validate_image_role(self) -> ImageMask:
        """Require mask artifacts to declare their mask role explicitly."""

        if self.image.role != "mask":
            raise ValueError("image masks require a role=mask artifact")
        return self


class VertexAttributeMask(MaterialGraphStrictModel):
    """Mask a layer by one bounded mesh attribute name."""

    kind: Literal["vertex_attribute"] = "vertex_attribute"
    attribute: str = Field(min_length=1, max_length=128)
    domain: Literal["POINT", "CORNER", "FACE"] = "POINT"
    invert: bool = False


class SemanticObjectMask(MaterialGraphStrictModel):
    """Restrict a layer to stable semantic or object identities."""

    kind: Literal["semantic_object"] = "semantic_object"
    semantic_ids: list[str] = Field(default_factory=list)
    object_ids: list[str] = Field(default_factory=list)
    invert: bool = False

    @model_validator(mode="after")
    def validate_targets(self) -> SemanticObjectMask:
        """Require at least one unique stable target identity."""

        targets = [*self.semantic_ids, *self.object_ids]
        if not targets:
            raise ValueError("semantic/object mask requires at least one target")
        if len(targets) != len(set(targets)):
            raise ValueError("semantic/object mask targets must be unique")
        return self


class CurvatureMask(MaterialGraphStrictModel):
    """Mask by bounded convexity or concavity sampled at a physical radius."""

    kind: Literal["curvature"] = "curvature"
    mode: Literal["convex", "concave", "both"] = "both"
    radius_m: float = Field(gt=0)
    low: float = Field(default=0.0, ge=0, le=1)
    high: float = Field(default=1.0, ge=0, le=1)
    invert: bool = False

    @model_validator(mode="after")
    def validate_range(self) -> CurvatureMask:
        """Reject inverted curvature response ranges."""

        if self.high <= self.low:
            raise ValueError("curvature mask high must exceed low")
        return self


class PositionSlopeMask(MaterialGraphStrictModel):
    """Mask by object-space position or world-space surface slope."""

    kind: Literal["position_slope"] = "position_slope"
    mode: Literal["position", "slope"]
    axis: Literal["X", "Y", "Z"] = "Z"
    minimum: float
    maximum: float
    unit: Literal["meters", "degrees"]
    invert: bool = False

    @model_validator(mode="after")
    def validate_units_and_range(self) -> PositionSlopeMask:
        """Keep position and slope ranges physically unambiguous."""

        if self.maximum <= self.minimum:
            raise ValueError("position/slope mask maximum must exceed minimum")
        expected = "meters" if self.mode == "position" else "degrees"
        if self.unit != expected:
            raise ValueError(f"{self.mode} mask must use {expected}")
        if self.mode == "slope" and (self.minimum < 0 or self.maximum > 180):
            raise ValueError("slope angles must remain within [0, 180]")
        return self


LayerMask = Annotated[
    ImageMask
    | VertexAttributeMask
    | SemanticObjectMask
    | CurvatureMask
    | PositionSlopeMask,
    Field(discriminator="kind"),
]


class MaterialGraphLayer(MaterialGraphStrictModel):
    """Describe one ordered whitelist-only layer over the stable base material."""

    layer_id: str = Field(min_length=1, max_length=128)
    order: int = Field(ge=0)
    material_id: str = Field(min_length=1, max_length=128)
    blend_mode: Literal["replace", "mix", "multiply", "add", "screen", "overlay"]
    opacity: float = Field(default=1.0, ge=0, le=1)
    channels: list[ChannelBinding] = Field(min_length=1)
    mask: LayerMask | None = None

    @model_validator(mode="after")
    def validate_channels(self) -> MaterialGraphLayer:
        """Require one binding per channel within a layer."""

        channels = [item.channel for item in self.channels]
        if len(channels) != len(set(channels)):
            raise ValueError("material graph layer channels must be unique")
        return self


class NormalDisplacementPolicy(MaterialGraphStrictModel):
    """Separate portable tangent normals from bounded physical displacement."""

    normal_mode: Literal["disabled", "tangent_space", "object_space"] = "tangent_space"
    displacement_mode: Literal["disabled", "bump_only", "true_displacement"] = "bump_only"
    maximum_displacement_m: float = Field(default=0.0, ge=0)
    require_subdivision: bool = False

    @model_validator(mode="after")
    def validate_displacement(self) -> NormalDisplacementPolicy:
        """Require physical amplitude and subdivision for true displacement."""

        if self.displacement_mode == "disabled" and self.maximum_displacement_m != 0:
            raise ValueError("disabled displacement must have zero amplitude")
        if self.displacement_mode == "true_displacement":
            if self.maximum_displacement_m <= 0 or not self.require_subdivision:
                raise ValueError(
                    "true displacement requires positive amplitude and subdivision"
                )
        return self


class BakePolicy(MaterialGraphStrictModel):
    """Declare deterministic portable bake outputs without choosing an engine graph."""

    required: bool = False
    channels: list[MaterialChannel] = Field(default_factory=list)
    resolution: tuple[int, int] = (1024, 1024)
    margin_px: int = Field(default=16, ge=0, le=256)
    preserve_raw_channels: Literal[True] = True

    @model_validator(mode="after")
    def validate_bake(self) -> BakePolicy:
        """Keep output channels unique and require them only for an active bake."""

        width, height = self.resolution
        if not (1 <= width <= 16384 and 1 <= height <= 16384):
            raise ValueError("bake resolution must be within 1..16384")
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("bake channels must be unique")
        if self.required != bool(self.channels):
            raise ValueError("required bake and channel presence must agree")
        return self


class PreviewLightingPolicy(MaterialGraphStrictModel):
    """Keep neutral material inspection separate from reference-matched comparison."""

    neutral_profile: Literal["neutral_studio"] = "neutral_studio"
    neutral_exposure: float = Field(default=0.0, ge=-10, le=10)
    reference_profile: Literal["reference_matched"] = "reference_matched"
    reference_source: MaterialGraphArtifact
    reference_confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_reference_source(self) -> PreviewLightingPolicy:
        """Require reference-matched lighting to bind one immutable reference image."""

        if self.reference_source.role != "reference":
            raise ValueError("reference-matched lighting requires role=reference")
        return self


class MaterialGraphSpec(MaterialGraphStrictModel):
    """Define a stable material base and ordered portable layers without arbitrary nodes."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    graph_id: PortableId
    provenance: MaterialGraphProvenance
    material_id: str = Field(min_length=1, max_length=128)
    base_channels: list[ChannelBinding] = Field(min_length=1)
    layers: list[MaterialGraphLayer] = Field(default_factory=list)
    normal_displacement: NormalDisplacementPolicy = Field(
        default_factory=NormalDisplacementPolicy
    )
    bake: BakePolicy = Field(default_factory=BakePolicy)
    preview_lighting: PreviewLightingPolicy
    graph_policy: Literal["whitelisted_material_graph_v1"] = (
        "whitelisted_material_graph_v1"
    )
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> MaterialGraphSpec:
        """Preserve material identity and deterministic ordered layer composition."""

        base_channels = [item.channel for item in self.base_channels]
        if len(base_channels) != len(set(base_channels)):
            raise ValueError("base material channels must be unique")
        layer_ids = [item.layer_id for item in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("material graph layer IDs must be unique")
        orders = [item.order for item in self.layers]
        if orders != list(range(len(self.layers))):
            raise ValueError("material graph layer order must be contiguous and sorted")
        if any(item.material_id != self.material_id for item in self.layers):
            raise ValueError("material layers cannot implicitly change material_id")
        return self
