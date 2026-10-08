"""Host model for the opt-in constant optical-volume0.1.0 contract."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .optical_volume import validate_optical_volume


class OpticalVolumeSpec(BaseModel):
    """Declare a positive approximate thickness and homogeneous absorption parameters."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["0.1.0"]
    thickness_factor: float = Field(ge=1e-6, le=1e6)
    attenuation_distance: float | None = Field(ge=1e-6, le=1e6)
    attenuation_color: tuple[
        Annotated[float, Field(ge=1e-6, le=1)],
        Annotated[float, Field(ge=1e-6, le=1)],
        Annotated[float, Field(ge=1e-6, le=1)],
    ]

    @model_validator(mode="before")
    @classmethod
    def validate_literal_contract(cls, value: Any) -> Any:
        """Share exact input-domain checks with the standard-library Blender reader."""
        return validate_optical_volume(value)
