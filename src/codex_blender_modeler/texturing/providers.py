from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import SurfaceDetailBinding, TextureChannelName, TextureManifest


class TextureGenerationRequest(BaseModel):
    """Describe a provider-neutral, reproducible texture generation request."""

    model_config = ConfigDict(extra="forbid")
    material_id: str
    prompt: str = ""
    preset: str = "standard_pbr"
    resolution: tuple[int, int] = (512, 512)
    channels: list[TextureChannelName]
    seed: int = Field(ge=0)
    intended_scale_m: float = Field(gt=0)
    uv_set: Literal["UVMap", "Generated", "Object"] = "Object"
    surface_detail_ids: list[str] = Field(default_factory=list)
    surface_detail_bindings: list[SurfaceDetailBinding] = Field(default_factory=list)
    detail_pattern: Literal[
        "none", "panel_atlas", "horizontal_bands", "vertical_grooves"
    ] = "none"
    overwrite: bool = False

    @model_validator(mode="after")
    def validate_generation_request(self) -> TextureGenerationRequest:
        """Reject empty/duplicate channels and unsafe texture dimensions."""

        if not self.channels:
            raise ValueError("At least one texture channel is required")
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("Texture channels must be unique")
        if any(value < 8 or value > 8192 for value in self.resolution):
            raise ValueError("Texture generation resolution values must be in [8, 8192]")
        if not self.material_id.strip():
            raise ValueError("material_id must not be empty")
        if not self.preset.strip():
            raise ValueError("preset must not be empty")
        if len(self.surface_detail_ids) != len(set(self.surface_detail_ids)):
            raise ValueError("surface_detail_ids must be unique")
        if any(not value.strip() for value in self.surface_detail_ids):
            raise ValueError("surface_detail_ids must not contain empty values")
        if self.surface_detail_ids and self.detail_pattern == "none":
            raise ValueError(
                "surface-detail coverage requires a rendered detail_pattern"
            )
        binding_ids = [item.detail_id for item in self.surface_detail_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("surface_detail_bindings must use unique detail IDs")
        if self.surface_detail_bindings and set(binding_ids) != set(
            self.surface_detail_ids
        ):
            raise ValueError(
                "surface_detail_bindings must exactly cover surface_detail_ids"
            )
        binding_wraps = {item.wrap for item in self.surface_detail_bindings}
        if len(binding_wraps) > 1:
            raise ValueError(
                "surface_detail_bindings must use one shared non-repeating wrap mode"
            )
        for binding in self.surface_detail_bindings:
            if binding.material_id != self.material_id:
                raise ValueError(
                    "surface-detail binding material_id must match the generation request"
                )
            if binding.uv_set != self.uv_set:
                raise ValueError(
                    "surface-detail binding uv_set must match the generation request"
                )
            missing_channels = sorted(set(binding.channels) - set(self.channels))
            if missing_channels:
                raise ValueError(
                    "surface-detail binding channels are absent from the generation request: "
                    f"{missing_channels}"
                )
        return self


class TextureProvider(Protocol):
    """Define the bounded interface implemented by texture generators."""

    provider_id: str

    def generate(self, request: TextureGenerationRequest, output_dir: Path) -> TextureManifest:
        """Generate declared texture files and return their validated manifest."""

        ...
