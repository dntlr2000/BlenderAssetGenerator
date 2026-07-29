from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
BBox4 = tuple[float, float, float, float]
RGB = tuple[int, int, int]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DominantColor(StrictModel):
    rgb: RGB
    fraction: float = Field(ge=0, le=1)


class LineAngleCluster(StrictModel):
    angle_deg: float = Field(ge=0, lt=180)
    count: int = Field(ge=1)
    spread_deg: float = Field(ge=0)


class ImageAnalysis(StrictModel):
    source_id: str
    path: str
    sha256: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    aspect_ratio: float = Field(gt=0)
    color_mode: str
    has_alpha: bool
    content_bbox_norm: BBox4
    edge_density: float = Field(ge=0, le=1)
    bilateral_symmetry_score: float = Field(ge=0, le=1)
    dominant_colors: list[DominantColor] = Field(default_factory=list)
    line_angle_clusters: list[LineAngleCluster] = Field(default_factory=list)
    diagnostics: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_bbox(self) -> ImageAnalysis:
        x0, y0, x1, y1 = self.content_bbox_norm
        if not all(0 <= value <= 1 for value in self.content_bbox_norm):
            raise ValueError("content_bbox_norm values must be in [0, 1]")
        if x1 <= x0 or y1 <= y0:
            raise ValueError("content_bbox_norm must have positive area")
        return self


class ReferenceAnalysis(StrictModel):
    schema_version: Literal["0.4.0"] = "0.4.0"
    job_id: str
    provider: Literal["basic", "opencv"]
    images: list[ImageAnalysis]
    recommended_projection: Literal["PERSP", "ORTHO", "UNKNOWN"]
    projection_confidence: float = Field(ge=0, le=1)
    reference_type: Literal[
        "perspective_reference",
        "orthographic_set",
        "blueprint_set",
        "mixed",
        "unknown",
    ]
    scale_status: Literal["unscaled", "anchored", "multi_anchor"]
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CameraSolution(StrictModel):
    schema_version: Literal["0.4.0"] = "0.4.0"
    job_id: str
    projection: Literal["PERSP", "ORTHO"]
    method: Literal["user_hint", "orthographic_source", "line_heuristic", "default_heuristic"]
    focal_length_mm: float = Field(gt=0)
    azimuth_deg: float = Field(ge=-180, le=180)
    elevation_deg: float = Field(ge=-89, le=89)
    roll_deg: float = Field(ge=-180, le=180)
    view_direction: Vec3
    principal_point_norm: Vec2 = (0.5, 0.5)
    confidence: float = Field(ge=0, le=1)
    locked_fields: list[str] = Field(default_factory=list)
    underconstrained: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ModelingPlanObject(StrictModel):
    """Describe one semantic modeling target and its optional content-scope role."""

    id: str
    label: str
    recommended_geometry: Literal[
        "primitive",
        "profile_extrude",
        "revolve",
        "curve",
        "terrain",
        "custom_mesh",
        "undecided",
    ] = "undecided"
    source_ids: list[str] = Field(default_factory=list)
    bbox_norm: BBox4 | None = None
    observed: bool = True
    confidence: float = Field(default=0.5, ge=0, le=1)
    scope_role: Literal["primary", "supporting", "context"] | None = None
    notes: list[str] = Field(default_factory=list)


class ModelingPlan(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"stage": {"const": "authored"}},
                        "required": ["stage"],
                    },
                    "then": {
                        "properties": {"objects": {"minItems": 1}},
                        "required": ["objects"],
                    },
                }
            ]
        },
    )
    schema_version: Literal["0.4.0"] = "0.4.0"
    job_id: str
    reference_analysis_path: str
    camera_solution_path: str
    stage: Literal["scaffold", "authored"] = "scaffold"
    objects: list[ModelingPlanObject] = Field(default_factory=list)
    global_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_authored_objects(self) -> ModelingPlan:
        """Require a non-empty, uniquely identified object list for authored plans."""

        object_ids = [item.id for item in self.objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("Modeling plan object IDs must be unique")
        if self.stage == "authored" and not self.objects:
            raise ValueError("An authored modeling plan must contain at least one object")
        return self
