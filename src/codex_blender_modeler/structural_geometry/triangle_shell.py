"""Bounded, data-only closed shells for explicit MeshPayload 0.2 authoring."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .triangle_shell_math import validate_triangle_shell_data

Coordinate = Annotated[float, Field(ge=-1.0e6, le=1.0e6)]
Vertex = tuple[Coordinate, Coordinate, Coordinate]
Index = Annotated[int, Field(ge=0, le=65535)]
Triangle = tuple[Index, Index, Index]



class TriangulatedShellGeometry(BaseModel):
    """Declare one closed oriented shell; no path, callback, code or material authority."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    kind: Literal["triangulated_shell"] = "triangulated_shell"
    vertices: list[Vertex] = Field(min_length=4, max_length=65536)
    triangles: list[Triangle] = Field(min_length=4, max_length=131072)
    loop_uvs: list[tuple[Coordinate, Coordinate]] | None = Field(default=None, max_length=393216)

    @model_validator(mode="after")
    def validate_closed_shell(self) -> Self:
        """Reject invalid indices, degeneracy, open/pinched/disconnected or inward shells."""
        validate_triangle_shell_data({
            "kind": self.kind,
            "vertices": self.vertices,
            "triangles": self.triangles,
            "loop_uvs": self.loop_uvs,
        })
        return self
