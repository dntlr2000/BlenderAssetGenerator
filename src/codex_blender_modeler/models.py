from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Color4 = tuple[float, float, float, float]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoordinateSystem(StrictModel):
    handedness: Literal["RIGHT"] = "RIGHT"
    up: Literal["+Z"] = "+Z"
    forward: Literal["-Y"] = "-Y"


class SourceSpec(StrictModel):
    id: str
    path: str
    kind: Literal["reference", "front", "right", "top", "blueprint", "cad"]
    immutable: bool = True
    scale_anchors: list[str] = Field(default_factory=list)


class MaterialSpec(StrictModel):
    id: str
    name: str
    shader: Literal["principled", "water", "glass", "emissive", "cloud"] = "principled"
    base_color: Color4
    roughness: float = Field(ge=0, le=1)
    metallic: float = Field(ge=0, le=1)
    emission_strength: float = Field(default=0, ge=0)
    texture_manifest: str | None = None


class EvidenceSpec(StrictModel):
    source_id: str
    bbox_norm: tuple[float, float, float, float]
    status: Literal["observed", "inferred"]
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_bbox(self) -> EvidenceSpec:
        x0, y0, x1, y1 = self.bbox_norm
        if not all(0 <= value <= 1 for value in self.bbox_norm):
            raise ValueError("bbox_norm values must be in [0, 1]")
        if x1 <= x0 or y1 <= y0:
            raise ValueError("bbox_norm must have positive area")
        return self


class TransformSpec(StrictModel):
    location: Vec3 = (0.0, 0.0, 0.0)
    rotation_deg: Vec3 = (0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)

    @model_validator(mode="after")
    def validate_scale(self) -> TransformSpec:
        if any(value <= 0 for value in self.scale):
            raise ValueError("Transform scale values must be positive; use a mirror modifier")
        return self


class PrimitiveGeometry(StrictModel):
    kind: Literal["primitive"] = "primitive"
    primitive: Literal["cube", "cylinder", "sphere", "cone", "torus"]
    dimensions: Vec3
    segments: int = Field(default=32, ge=3, le=512)
    ring_segments: int = Field(default=16, ge=3, le=256)

    @model_validator(mode="after")
    def validate_dimensions(self) -> PrimitiveGeometry:
        if any(value <= 0 for value in self.dimensions):
            raise ValueError("Primitive dimensions must be positive")
        return self


class CustomMeshGeometry(StrictModel):
    kind: Literal["custom_mesh"] = "custom_mesh"
    vertices: list[Vec3] | None = None
    faces: list[list[int]] | None = None
    path: str | None = None
    format: Literal["mesh_json"] = "mesh_json"
    recalculate_normals: bool = True

    @model_validator(mode="after")
    def validate_payload(self) -> CustomMeshGeometry:
        has_inline = self.vertices is not None or self.faces is not None
        if has_inline:
            if not self.vertices or not self.faces:
                raise ValueError("custom_mesh inline payload needs both vertices and faces")
            vertex_count = len(self.vertices)
            for face in self.faces:
                if len(face) < 3:
                    raise ValueError("Every custom_mesh face needs at least three indices")
                if any(index < 0 or index >= vertex_count for index in face):
                    raise ValueError("custom_mesh face index is outside the vertex array")
        if not has_inline and not self.path:
            raise ValueError("custom_mesh needs inline vertices/faces or a mesh_json path")
        if has_inline and self.path:
            raise ValueError("custom_mesh must use either inline data or path, not both")
        return self


class ProfileExtrudeGeometry(StrictModel):
    kind: Literal["profile_extrude"] = "profile_extrude"
    profile: list[Vec2] = Field(min_length=3)
    depth: float = Field(gt=0)
    axis: Literal["X", "Y", "Z"] = "Y"
    cap: bool = True


class RevolveGeometry(StrictModel):
    kind: Literal["revolve"] = "revolve"
    profile: list[Vec2] = Field(min_length=2, description="Pairs of [radius, height]")
    axis: Literal["X", "Y", "Z"] = "Z"
    angle_deg: float = Field(default=360.0, gt=0, le=360)
    segments: int = Field(default=48, ge=3, le=512)
    cap_ends: bool = True

    @model_validator(mode="after")
    def validate_profile(self) -> RevolveGeometry:
        if any(radius < 0 for radius, _height in self.profile):
            raise ValueError("Revolve radius values cannot be negative")
        return self


class CurveGeometry(StrictModel):
    kind: Literal["curve"] = "curve"
    points: list[Vec3] = Field(min_length=2)
    spline_type: Literal["POLY", "NURBS"] = "POLY"
    cyclic: bool = False
    bevel_depth: float = Field(default=0.05, gt=0)
    bevel_resolution: int = Field(default=3, ge=0, le=12)
    resolution_u: int = Field(default=12, ge=1, le=64)
    convert_to_mesh: bool = True


class TerrainGeometry(StrictModel):
    kind: Literal["terrain"] = "terrain"
    mode: Literal["height_grid", "heightmap"]
    size: Vec3
    heights: list[list[float]] | None = None
    heightmap_path: str | None = None
    resolution: tuple[int, int] = (128, 128)
    skirt_depth: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_terrain(self) -> TerrainGeometry:
        if any(value <= 0 for value in self.size):
            raise ValueError("Terrain size values must be positive")
        if self.mode == "height_grid":
            if not self.heights or len(self.heights) < 2 or len(self.heights[0]) < 2:
                raise ValueError("height_grid terrain needs a matrix of at least 2x2")
            width = len(self.heights[0])
            if any(len(row) != width for row in self.heights):
                raise ValueError("All terrain height rows must have equal length")
            if self.heightmap_path:
                raise ValueError("height_grid terrain cannot also set heightmap_path")
        else:
            if not self.heightmap_path:
                raise ValueError("heightmap terrain needs heightmap_path")
            if self.heights is not None:
                raise ValueError("heightmap terrain cannot also set inline heights")
            if any(value < 2 or value > 1024 for value in self.resolution):
                raise ValueError("Terrain resolution values must be within [2, 1024]")
        return self


GeometrySpec = Annotated[
    PrimitiveGeometry
    | CustomMeshGeometry
    | ProfileExtrudeGeometry
    | RevolveGeometry
    | CurveGeometry
    | TerrainGeometry,
    Field(discriminator="kind"),
]


class BevelModifier(StrictModel):
    kind: Literal["bevel"] = "bevel"
    width: float = Field(gt=0)
    segments: int = Field(default=2, ge=1, le=16)
    limit_method: Literal["NONE", "ANGLE", "WEIGHT", "VGROUP"] = "ANGLE"


class MirrorModifier(StrictModel):
    kind: Literal["mirror"] = "mirror"
    axes: list[Literal["X", "Y", "Z"]] = Field(default_factory=lambda: ["X"], min_length=1)
    merge: bool = True
    merge_threshold: float = Field(default=0.001, ge=0)


class SubdivisionModifier(StrictModel):
    kind: Literal["subdivision"] = "subdivision"
    levels: int = Field(default=2, ge=0, le=6)
    render_levels: int = Field(default=2, ge=0, le=6)
    subdivision_type: Literal["CATMULL_CLARK", "SIMPLE"] = "CATMULL_CLARK"


class SolidifyModifier(StrictModel):
    kind: Literal["solidify"] = "solidify"
    thickness: float
    offset: float = Field(default=0.0, ge=-1, le=1)


class ArrayModifier(StrictModel):
    kind: Literal["array"] = "array"
    count: int = Field(ge=1)
    offset: Vec3


class DecimateModifier(StrictModel):
    kind: Literal["decimate"] = "decimate"
    ratio: float = Field(gt=0, le=1)


class RemeshModifier(StrictModel):
    kind: Literal["remesh"] = "remesh"
    voxel_size: float = Field(gt=0)
    smooth: bool = False


class BooleanModifier(StrictModel):
    kind: Literal["boolean"] = "boolean"
    operation: Literal["UNION", "DIFFERENCE", "INTERSECT"]
    target_id: str
    solver: Literal["EXACT", "FAST"] = "EXACT"
    hide_target: bool = True


class NormalTransferModifier(StrictModel):
    """Transfer split normals only across a bounded source-facing boundary ring."""

    kind: Literal["normal_transfer"] = "normal_transfer"
    target_id: str
    max_distance: float = Field(default=0.08, gt=0)
    boundary_axis: Literal["X", "Y", "Z"] = "X"
    boundary_side: Literal["MIN", "MAX"] = "MIN"
    boundary_width: float = Field(default=0.12, gt=0)
    mix_factor: float = Field(default=1.0, gt=0, le=1)


ModifierSpec = Annotated[
    BevelModifier
    | MirrorModifier
    | SubdivisionModifier
    | SolidifyModifier
    | ArrayModifier
    | DecimateModifier
    | RemeshModifier
    | BooleanModifier
    | NormalTransferModifier,
    Field(discriminator="kind"),
]


class ArrayGenerator(StrictModel):
    kind: Literal["array"] = "array"
    count: int = Field(ge=1)
    offset: Vec3


class ObjectSpec(StrictModel):
    id: str
    name: str
    geometry: GeometrySpec
    transform: TransformSpec = Field(default_factory=TransformSpec)
    material_id: str
    modifiers: list[ModifierSpec] = Field(default_factory=list)
    generator: ArrayGenerator | None = None
    parent_id: str | None = None
    shade_smooth: bool = False
    tags: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSpec] = Field(default_factory=list)
    editable: dict[str, Any] = Field(default_factory=dict)


class CameraSpec(StrictModel):
    projection: Literal["PERSP", "ORTHO"]
    location: Vec3
    target: Vec3
    focal_length_mm: float = Field(gt=0)
    ortho_scale: float = Field(gt=0)
    resolution: tuple[int, int]


class SceneSpec(StrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    job_id: str
    mode: Literal["concept", "measured"]
    units: Literal["METERS"] = "METERS"
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    nominal_scene_size: Vec3
    sources: list[SourceSpec]
    materials: list[MaterialSpec]
    objects: list[ObjectSpec]
    camera: CameraSpec
    assumptions: list[str] = Field(default_factory=list)
    revision_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids_and_links(self) -> SceneSpec:
        """Validate stable identities and every object-to-object modifier link."""

        material_ids = [material.id for material in self.materials]
        object_ids = [obj.id for obj in self.objects]
        object_id_set = set(object_ids)
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("Duplicate material IDs")
        if len(object_ids) != len(object_id_set):
            raise ValueError("Duplicate object IDs")
        missing_materials = sorted({obj.material_id for obj in self.objects} - set(material_ids))
        if missing_materials:
            raise ValueError(f"Objects reference missing materials: {missing_materials}")
        missing_parents = sorted(
            {obj.parent_id for obj in self.objects if obj.parent_id} - object_id_set
        )
        if missing_parents:
            raise ValueError(f"Objects reference missing parents: {missing_parents}")
        modifier_targets = {
            modifier.target_id
            for obj in self.objects
            for modifier in obj.modifiers
            if isinstance(modifier, (BooleanModifier, NormalTransferModifier))
        }
        missing_targets = sorted(modifier_targets - object_id_set)
        if missing_targets:
            raise ValueError(f"Object modifiers reference missing objects: {missing_targets}")
        if any(value <= 0 for value in self.nominal_scene_size):
            raise ValueError("nominal_scene_size must be positive")
        return self
