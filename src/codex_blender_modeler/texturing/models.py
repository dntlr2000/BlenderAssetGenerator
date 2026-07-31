from __future__ import annotations

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
        return self
