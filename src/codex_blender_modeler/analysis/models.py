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


class SurfaceDetailPolicy(StrictModel):
    """Define how small, surface-attached reference details should be represented."""

    mode: Literal[
        "auto_balanced",
        "texture_preferred",
        "geometry_preferred",
        "explicit",
    ] = "auto_balanced"
    default_representation: Literal[
        "texture_channels",
        "baked_decal",
        "omit",
    ] = "texture_channels"
    prefer_texture_for_repeated_details: bool = True
    max_texture_projected_size_px: int = Field(default=128, ge=1)
    max_texture_relief_m: float = Field(default=0.01, ge=0)
    geometry_required_conditions: list[
        Literal[
            "silhouette",
            "structural",
            "gameplay",
            "physical_transparency",
        ]
    ] = Field(
        default_factory=lambda: [
            "silhouette",
            "structural",
            "gameplay",
            "physical_transparency",
        ]
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_required_conditions(self) -> SurfaceDetailPolicy:
        """Keep geometry-required condition names unique and deterministic."""

        if len(self.geometry_required_conditions) != len(
            set(self.geometry_required_conditions)
        ):
            raise ValueError("Surface-detail geometry-required conditions must be unique")
        return self


class SurfaceDetailDecision(StrictModel):
    """Route one non-structural visible detail to portable texture evidence or omission."""

    id: str
    label: str
    parent_object_id: str
    representation: Literal["texture_channels", "baked_decal", "omit"]
    source_ids: list[str] = Field(default_factory=list)
    bbox_norm: BBox4 | None = None
    target_material_id: str | None = None
    channels: list[
        Literal[
            "base_color",
            "roughness",
            "metallic",
            "normal",
            "height",
            "opacity",
            "emission",
        ]
    ] = Field(default_factory=list)
    uv_strategy: Literal["existing_uv", "projected_patch", "material_atlas"] | None = None
    projected_size_px: float | None = Field(default=None, gt=0)
    estimated_relief_m: float | None = Field(default=None, ge=0)
    repeated_count: int = Field(default=1, ge=1)
    silhouette_affecting: bool = False
    structural: bool = False
    gameplay_relevant: bool = False
    physical_transparency_required: bool = False
    evidence_status: Literal["observed", "inferred"] = "observed"
    confidence: float = Field(default=0.5, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_surface_representation(self) -> SurfaceDetailDecision:
        """Reject geometry-worthy details and require complete portable texture routing."""

        if self.bbox_norm is not None:
            x0, y0, x1, y1 = self.bbox_norm
            if not all(0 <= value <= 1 for value in self.bbox_norm):
                raise ValueError("Surface-detail bbox_norm values must be in [0, 1]")
            if x1 <= x0 or y1 <= y0:
                raise ValueError("Surface-detail bbox_norm must have positive area")
        geometry_reasons = [
            name
            for name, required in (
                ("silhouette", self.silhouette_affecting),
                ("structural", self.structural),
                ("gameplay", self.gameplay_relevant),
                ("physical_transparency", self.physical_transparency_required),
            )
            if required
        ]
        if geometry_reasons:
            raise ValueError(
                "Geometry-worthy details belong in ModelingPlan.objects, not "
                f"surface_details; reasons={geometry_reasons}"
            )
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("Surface-detail PBR channels must be unique")
        if self.representation == "omit":
            if self.target_material_id is not None or self.channels or self.uv_strategy:
                raise ValueError(
                    "Omitted surface details cannot declare material, channels, or UV routing"
                )
            return self
        if not self.target_material_id:
            raise ValueError("Textured surface details require target_material_id")
        if not self.channels:
            raise ValueError("Textured surface details require at least one PBR channel")
        if self.uv_strategy is None:
            raise ValueError("Textured surface details require an explicit UV strategy")
        return self


class SurfaceDetailValidationCheck(StrictModel):
    """Record one host-side geometry or material binding check for a surface detail."""

    id: str
    status: Literal["passed", "warning", "failed"]
    phase: Literal["modeling", "geometry", "material", "qa"]
    message: str
    detail_id: str | None = None
    parent_object_id: str | None = None
    material_id: str | None = None


class SurfaceDetailValidationReport(StrictModel):
    """Summarize whether planned surface details remain non-mesh and texture-bound."""

    schema_version: Literal["0.5.0"] = "0.5.0"
    job_id: str
    ok: bool
    material_status: Literal["not_required", "pending", "validated"]
    total: int = Field(ge=0)
    textured: int = Field(ge=0)
    omitted: int = Field(ge=0)
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    checks: list[SurfaceDetailValidationCheck] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_summary(self) -> SurfaceDetailValidationReport:
        """Keep report counters and success status consistent with detailed checks."""

        counts = {
            status: sum(item.status == status for item in self.checks)
            for status in ("passed", "warning", "failed")
        }
        if (self.passed, self.warnings, self.failed) != (
            counts["passed"],
            counts["warning"],
            counts["failed"],
        ):
            raise ValueError("Surface-detail validation counts do not match checks")
        if self.ok != (self.failed == 0):
            raise ValueError("Surface-detail validation ok must match failed==0")
        if self.textured + self.omitted != self.total:
            raise ValueError("Surface-detail representation counts do not match total")
        return self


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
    surface_detail_policy: SurfaceDetailPolicy | None = None
    surface_details: list[SurfaceDetailDecision] = Field(default_factory=list)
    global_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_authored_objects(self) -> ModelingPlan:
        """Require a non-empty, uniquely identified object list for authored plans."""

        object_ids = [item.id for item in self.objects]
        detail_ids = [item.id for item in self.surface_details]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("Modeling plan object IDs must be unique")
        if len(detail_ids) != len(set(detail_ids)):
            raise ValueError("Surface-detail IDs must be unique")
        overlap = sorted(set(object_ids) & set(detail_ids))
        if overlap:
            raise ValueError(
                "Surface-detail IDs must not also be geometry object IDs: "
                f"{overlap}"
            )
        if self.stage == "authored" and not self.objects:
            raise ValueError("An authored modeling plan must contain at least one object")
        if self.surface_details and self.surface_detail_policy is None:
            raise ValueError("Surface details require an explicit surface_detail_policy")
        if self.stage == "authored":
            missing_parents = sorted(
                {
                    detail.parent_object_id
                    for detail in self.surface_details
                    if detail.parent_object_id not in set(object_ids)
                }
            )
            if missing_parents:
                raise ValueError(
                    "Surface details reference missing modeling-plan parents: "
                    f"{missing_parents}"
                )
        return self
