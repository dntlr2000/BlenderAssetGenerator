from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TextureChannelName = Literal[
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "height",
    "opacity",
    "emission",
]


class StrictModel(BaseModel):
    """Reject undeclared fields in versioned texture contracts."""

    model_config = ConfigDict(extra="forbid")


class TextureChannel(StrictModel):
    """Describe one image or procedural PBR channel."""

    source: Literal["image", "procedural"]
    path: str | None = None
    color_space: Literal["sRGB", "Non-Color"] | None = None
    invert: bool = False
    strength: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def validate_source_path(self) -> TextureChannel:
        """Require image paths and forbid paths on procedural channels."""

        if self.source == "image" and not self.path:
            raise ValueError("Image texture channels require a path")
        if self.source == "procedural" and self.path is not None:
            raise ValueError("Procedural texture channels must not declare a path")
        return self


class TextureProvenance(StrictModel):
    """Record reproducibility and rights metadata for generated texture assets."""

    provider: str
    provider_version: str | None = None
    model: str | None = None
    prompt: str | None = None
    seed: int | None = None
    source_hashes: list[str] = Field(default_factory=list)
    generated_sha256: dict[str, str] = Field(default_factory=dict)
    license: str | None = None


class SurfaceDetailPlacement(StrictModel):
    """Locate one non-tiling surface detail inside a stable authored UV layout."""

    mode: Literal["uv_rect", "mask_image"]
    uv_rect: tuple[float, float, float, float] | None = None
    mask_path: str | None = None
    mask_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_placement(self) -> SurfaceDetailPlacement:
        """Require exactly the normalized rectangle or immutable mask evidence for the mode."""

        if self.mode == "uv_rect":
            if self.uv_rect is None or self.mask_path is not None or self.mask_sha256 is not None:
                raise ValueError(
                    "uv_rect placement requires only uv_rect and cannot declare a mask"
                )
            u0, v0, u1, v1 = self.uv_rect
            if not all(0.0 <= value <= 1.0 for value in self.uv_rect):
                raise ValueError("Surface-detail uv_rect values must be in [0, 1]")
            if u1 <= u0 or v1 <= v0:
                raise ValueError("Surface-detail uv_rect must have positive area")
            return self

        if self.uv_rect is not None or not self.mask_path or not self.mask_sha256:
            raise ValueError(
                "mask_image placement requires mask_path and mask_sha256 only"
            )
        candidate = PurePosixPath(self.mask_path)
        if (
            candidate.is_absolute()
            or "\\" in self.mask_path
            or ":" in self.mask_path
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError(
                "Surface-detail mask_path must be a contained POSIX relative path"
            )
        return self


class SurfaceDetailBinding(StrictModel):
    """Bind one planned detail to an object, material, UV layout, and bounded placement."""

    detail_id: str
    parent_object_id: str
    material_id: str
    uv_set: Literal["UVMap"] = "UVMap"
    uv_layout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    placement: SurfaceDetailPlacement
    channels: list[TextureChannelName]
    strength: float = Field(default=1.0, gt=0.0, le=1.0)
    wrap: Literal["clip", "clamp"] = "clamp"

    @model_validator(mode="after")
    def validate_binding(self) -> SurfaceDetailBinding:
        """Reject empty identifiers and duplicate or empty channel claims."""

        if not self.detail_id.strip() or not self.parent_object_id.strip():
            raise ValueError("Surface-detail binding IDs must not be empty")
        if not self.material_id.strip():
            raise ValueError("Surface-detail binding material_id must not be empty")
        if not self.channels:
            raise ValueError("Surface-detail binding requires at least one PBR channel")
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("Surface-detail binding channels must be unique")
        return self


class TextureManifest(StrictModel):
    """Define portable texture channels while accepting known v0.4 draft metadata."""

    schema_version: Literal["0.5.0"] = "0.5.0"
    material_id: str
    uv_set: Literal["UVMap", "Generated", "Object"] = "Object"
    intended_scale_m: float = Field(gt=0)
    resolution: tuple[int, int]
    source_type: Literal["image", "procedural", "hybrid"]
    channels: dict[TextureChannelName, TextureChannel] = Field(default_factory=dict)
    surface_detail_ids: list[str] = Field(default_factory=list)
    surface_detail_bindings: list[SurfaceDetailBinding] = Field(default_factory=list)
    procedural: dict[str, Any] = Field(default_factory=dict)
    shader_recipe: str | None = None
    provenance: TextureProvenance | None = None
    cycles_shader_model: dict[str, Any] | None = None
    node_graph_summary: str | None = None
    color_space_rules: dict[str, Any] | None = None
    generation_notes: str | None = None
    expected_preview_goal: str | None = None

    @model_validator(mode="after")
    def validate_manifest(self) -> TextureManifest:
        """Validate resolution, source composition, and channel color spaces."""

        if any(value < 1 or value > 8192 for value in self.resolution):
            raise ValueError("resolution values must be in [1, 8192]")
        image_count = sum(channel.source == "image" for channel in self.channels.values())
        procedural_count = sum(
            channel.source == "procedural" for channel in self.channels.values()
        )
        if self.source_type == "image" and (not image_count or procedural_count):
            raise ValueError(
                "An image source_type requires image channels and cannot contain procedural ones"
            )
        if self.source_type == "procedural" and (not procedural_count or image_count):
            raise ValueError(
                "A procedural source_type requires procedural channels and cannot contain images"
            )
        if self.source_type == "hybrid" and (not image_count or not procedural_count):
            raise ValueError("A hybrid source_type requires image and procedural channels")
        for name, channel in self.channels.items():
            if channel.source != "image":
                continue
            expected = "sRGB" if name in {"base_color", "emission"} else "Non-Color"
            if channel.color_space not in {None, expected}:
                raise ValueError(f"Channel {name} color_space must be {expected}")
        if len(self.surface_detail_ids) != len(set(self.surface_detail_ids)):
            raise ValueError("TextureManifest surface_detail_ids must be unique")
        binding_ids = [binding.detail_id for binding in self.surface_detail_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("TextureManifest surface-detail binding IDs must be unique")
        if self.surface_detail_bindings and set(binding_ids) != set(self.surface_detail_ids):
            raise ValueError(
                "TextureManifest spatial bindings must exactly cover surface_detail_ids"
            )
        binding_wraps = {binding.wrap for binding in self.surface_detail_bindings}
        if len(binding_wraps) > 1:
            raise ValueError(
                "TextureManifest spatial bindings must use one shared non-repeating wrap mode"
            )
        for binding in self.surface_detail_bindings:
            if binding.material_id != self.material_id:
                raise ValueError(
                    "Surface-detail binding material_id must match TextureManifest material_id"
                )
            if binding.uv_set != self.uv_set:
                raise ValueError(
                    "Surface-detail binding uv_set must match TextureManifest uv_set"
                )
            missing_channels = sorted(set(binding.channels) - set(self.channels))
            if missing_channels:
                raise ValueError(
                    "Surface-detail binding channels are absent from TextureManifest: "
                    f"{missing_channels}"
                )
            non_image_channels = sorted(
                name
                for name in binding.channels
                if self.channels[name].source != "image"
            )
            if non_image_channels:
                raise ValueError(
                    "Spatial surface-detail channels must be image-backed: "
                    f"{non_image_channels}"
                )
        return self
