from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import TextureChannelName, TextureManifest


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
        return self


class TextureProvider(Protocol):
    """Define the bounded interface implemented by texture generators."""

    provider_id: str

    def generate(self, request: TextureGenerationRequest, output_dir: Path) -> TextureManifest:
        """Generate declared texture files and return their validated manifest."""

        ...
