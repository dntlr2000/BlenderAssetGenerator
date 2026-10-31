"""Strict data-only mixed triangle/quad shell; canonical SceneSpec remains unchanged."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .polygon_shell_math import validate_polygon_shell_data
from .triangle_shell import Coordinate, Index, Vertex

Face = Annotated[list[Index], Field(min_length=3, max_length=4)]


class PolygonShellGeometry(BaseModel):
    """Preserve bounded, closed, outward polygons with optional exact corner UVs."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    kind: Literal["polygon_shell"] = "polygon_shell"
    vertices: list[Vertex] = Field(min_length=4, max_length=65536)
    faces: list[Face] = Field(min_length=4, max_length=131072)
    loop_uvs: list[tuple[Coordinate, Coordinate]] | None = Field(default=None, max_length=393216)

    @model_validator(mode="after")
    def validate_closed_shell(self) -> Self:
        """Reject malformed polygons and invalid closed topology without triangulating storage."""
        validate_polygon_shell_data(self.model_dump(mode="python"))
        return self
