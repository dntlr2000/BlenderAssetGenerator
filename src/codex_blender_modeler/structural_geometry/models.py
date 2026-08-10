"""Strict parallel geometry contracts for autonomous structural candidates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from ..models import (
    ArrayGenerator,
    CameraSpec,
    CoordinateSystem,
    CurveGeometry,
    CustomMeshGeometry,
    EvidenceSpec,
    MaterialSpec,
    ModifierSpec,
    PrimitiveGeometry,
    ProfileExtrudeGeometry,
    RevolveGeometry,
    SourceSpec,
    TerrainGeometry,
    TransformSpec,
)

SCHEMA_VERSION = "0.3.0"
CONTRACT_VERSION = "0.1.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
STABLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
JOB_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
JOB_RELATIVE_SCHEMA_PATTERN = (
    r"^(?!/)(?![A-Za-z]:)(?!.*:)(?!.*(?:^|/)\.\.(?:/|$))(?!.*\\)(?!.*//)"
    r"[^\u0000]+$"
)

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


def _validate_job_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by its owning job workspace."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty POSIX job-relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be job-relative, not absolute")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path must not contain empty, current, or parent segments")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
StableId = Annotated[str, Field(pattern=STABLE_ID_PATTERN)]
JobId = Annotated[str, Field(pattern=JOB_ID_PATTERN)]
JobRelativePath = Annotated[
    str,
    Field(min_length=1, json_schema_extra={"pattern": JOB_RELATIVE_SCHEMA_PATTERN}),
    AfterValidator(_validate_job_relative_path),
]


class StructuralStrictModel(BaseModel):
    """Reject undeclared fields and non-finite values in structural contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


def _point_distance_squared(left: Vec3, right: Vec3) -> float:
    """Return squared Euclidean distance for strict geometry validation."""

    return sum((left[index] - right[index]) ** 2 for index in range(3))


def _validate_polyline(
    points: list[Vec3],
    *,
    closed: bool,
    label: str,
) -> None:
    """Reject duplicate consecutive points and degenerate open or closed polylines."""

    minimum = 3 if closed else 2
    if len(points) < minimum:
        raise ValueError(f"{label} requires at least {minimum} points")
    pairs = list(zip(points, points[1:], strict=False))
    if closed:
        pairs.append((points[-1], points[0]))
    if any(_point_distance_squared(left, right) <= 1.0e-18 for left, right in pairs):
        raise ValueError(f"{label} contains a zero-length segment")
    unique = {tuple(round(value, 12) for value in point) for point in points}
    if len(unique) < minimum:
        raise ValueError(f"{label} does not contain enough unique points")


def _signed_area(loop: list[Vec2]) -> float:
    """Return one closed 2D loop's signed shoelace area."""

    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(loop, [*loop[1:], loop[0]], strict=True)
    )


def _segments_intersect(
    first: Vec2,
    second: Vec2,
    third: Vec2,
    fourth: Vec2,
) -> bool:
    """Return whether two 2D segments intersect, including collinear contact."""

    def orientation(a: Vec2, b: Vec2, c: Vec2) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a: Vec2, b: Vec2, c: Vec2) -> bool:
        return (
            min(a[0], b[0]) - 1.0e-12 <= c[0] <= max(a[0], b[0]) + 1.0e-12
            and min(a[1], b[1]) - 1.0e-12 <= c[1] <= max(a[1], b[1]) + 1.0e-12
        )

    values = (
        orientation(first, second, third),
        orientation(first, second, fourth),
        orientation(third, fourth, first),
        orientation(third, fourth, second),
    )
    if values[0] * values[1] < -1.0e-18 and values[2] * values[3] < -1.0e-18:
        return True
    checks = (
        (values[0], first, second, third),
        (values[1], first, second, fourth),
        (values[2], third, fourth, first),
        (values[3], third, fourth, second),
    )
    return any(abs(value) <= 1.0e-12 and on_segment(a, b, c) for value, a, b, c in checks)


def validate_simple_loop(loop: list[Vec2], label: str) -> None:
    """Reject a zero-area or self-intersecting closed 2D profile."""

    if len(loop) < 3:
        raise ValueError(f"{label} requires at least three points")
    if len({tuple(round(value, 12) for value in point) for point in loop}) != len(loop):
        raise ValueError(f"{label} contains duplicate points")
    if abs(_signed_area(loop)) <= 1.0e-12:
        raise ValueError(f"{label} has zero signed area")
    edges = list(zip(loop, [*loop[1:], loop[0]], strict=True))
    for left_index, left in enumerate(edges):
        for right_index in range(left_index + 1, len(edges)):
            if right_index in {left_index, left_index + 1}:
                continue
            if left_index == 0 and right_index == len(edges) - 1:
                continue
            if _segments_intersect(*left, *edges[right_index]):
                raise ValueError(f"{label} is self-intersecting")


def _validate_convex_loop(loop: list[Vec2], label: str) -> None:
    """Require one simple loop to be strictly convex for deterministic fan caps."""

    signs: set[int] = set()
    for index in range(len(loop)):
        first = loop[index - 1]
        second = loop[index]
        third = loop[(index + 1) % len(loop)]
        cross = (second[0] - first[0]) * (third[1] - second[1]) - (
            second[1] - first[1]
        ) * (third[0] - second[0])
        if abs(cross) <= 1.0e-12:
            raise ValueError(f"{label} contains a collinear cap corner")
        signs.add(1 if cross > 0 else -1)
    if len(signs) != 1:
        raise ValueError(f"{label} must be convex when cap_policy is ends")


def _validate_planar_convex_section(points: list[Vec3], label: str) -> None:
    """Project one planar 3D section and require a strictly convex cap boundary."""

    origin = points[0]
    normal: Vec3 | None = None
    for index in range(1, len(points) - 1):
        first = tuple(points[index][axis] - origin[axis] for axis in range(3))
        second = tuple(points[index + 1][axis] - origin[axis] for axis in range(3))
        candidate = (
            first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0],
        )
        magnitude = math.sqrt(sum(value * value for value in candidate))
        if magnitude > 1.0e-12:
            normal = tuple(value / magnitude for value in candidate)
            break
    if normal is None:
        raise ValueError(f"{label} cap points are collinear")
    for point in points:
        offset = tuple(point[axis] - origin[axis] for axis in range(3))
        if abs(sum(normal[axis] * offset[axis] for axis in range(3))) > 1.0e-9:
            raise ValueError(f"{label} cap points must be planar")
    dropped_axis = max(range(3), key=lambda axis: abs(normal[axis]))
    projected = [
        tuple(point[axis] for axis in range(3) if axis != dropped_axis)
        for point in points
    ]
    validate_simple_loop(projected, label)
    _validate_convex_loop(projected, label)


class LoftSection(StructuralStrictModel):
    """Declare one ordered 3D section in a deterministic loft recipe."""

    points: list[Vec3] = Field(min_length=2, max_length=512)
    closed: bool

    @model_validator(mode="after")
    def validate_section(self) -> LoftSection:
        """Reject a degenerate loft section before deterministic resampling."""

        _validate_polyline(self.points, closed=self.closed, label="loft section")
        return self


class LoftGeometry(StructuralStrictModel):
    """Connect two or more open or closed sections with stable correspondence."""

    kind: Literal["loft"] = "loft"
    sections: list[LoftSection] = Field(min_length=2, max_length=64)
    resample_count: int | None = Field(default=None, ge=2, le=512)
    cap_policy: Literal["none", "ends"] = "ends"
    correspondence_policy: Literal["index", "minimum_twist"] = "minimum_twist"
    twist_offsets: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_loft(self) -> LoftGeometry:
        """Require compatible section closure and complete optional twist offsets."""

        states = {section.closed for section in self.sections}
        if len(states) != 1:
            raise ValueError("loft sections must all be open or all be closed")
        if self.cap_policy == "ends" and not self.sections[0].closed:
            raise ValueError("loft end caps require closed sections")
        if self.cap_policy == "ends":
            _validate_planar_convex_section(
                self.sections[0].points,
                "loft first section",
            )
            _validate_planar_convex_section(
                self.sections[-1].points,
                "loft final section",
            )
        if self.resample_count is not None:
            minimum = 3 if self.sections[0].closed else 2
            if self.resample_count < minimum:
                raise ValueError(f"loft resample_count must be at least {minimum}")
        if self.twist_offsets and len(self.twist_offsets) != len(self.sections):
            raise ValueError("loft twist_offsets must match section count")
        if not self.sections[0].closed and any(self.twist_offsets):
            raise ValueError("open loft sections cannot use cyclic twist offsets")
        return self


class SweepGeometry(StructuralStrictModel):
    """Sweep one 2D profile along a 3D path using a stable transported frame."""

    kind: Literal["sweep"] = "sweep"
    profile: list[Vec2] = Field(min_length=2, max_length=256)
    profile_closed: bool = True
    path: list[Vec3] = Field(min_length=2, max_length=1024)
    path_closed: bool = False
    scales: list[float] = Field(default_factory=list)
    twist_degrees: list[float] = Field(default_factory=list)
    cap_policy: Literal["none", "ends"] = "ends"

    @model_validator(mode="after")
    def validate_sweep(self) -> SweepGeometry:
        """Reject zero-length paths and incomplete scale or twist tracks."""

        _validate_polyline(self.path, closed=self.path_closed, label="sweep path")
        minimum = 3 if self.profile_closed else 2
        if len(self.profile) < minimum:
            raise ValueError(f"sweep profile requires at least {minimum} points")
        profile3 = [(point[0], point[1], 0.0) for point in self.profile]
        _validate_polyline(profile3, closed=self.profile_closed, label="sweep profile")
        if self.profile_closed and abs(_signed_area(self.profile)) <= 1.0e-12:
            raise ValueError("sweep profile has zero signed area")
        if self.scales and len(self.scales) != len(self.path):
            raise ValueError("sweep scales must match path point count")
        if any(value <= 0 for value in self.scales):
            raise ValueError("sweep scales must be positive")
        if self.twist_degrees and len(self.twist_degrees) != len(self.path):
            raise ValueError("sweep twist_degrees must match path point count")
        if self.cap_policy == "ends" and (self.path_closed or not self.profile_closed):
            raise ValueError("sweep caps require an open path and closed profile")
        if self.cap_policy == "ends":
            validate_simple_loop(self.profile, "sweep cap profile")
            _validate_convex_loop(self.profile, "sweep cap profile")
        return self


class MultiLoopExtrudeGeometry(StructuralStrictModel):
    """Extrude one outer profile and optional hole loops along a principal axis."""

    kind: Literal["multi_loop_extrude"] = "multi_loop_extrude"
    outer_loop: list[Vec2] = Field(min_length=3, max_length=2048)
    hole_loops: list[list[Vec2]] = Field(default_factory=list, max_length=64)
    depth: float = Field(gt=0)
    axis: Literal["X", "Y", "Z"] = "Z"
    cap: bool = True

    @model_validator(mode="after")
    def validate_loops(self) -> MultiLoopExtrudeGeometry:
        """Reject self-intersections, crossing loops, and holes outside the outer profile."""

        validate_simple_loop(self.outer_loop, "multi-loop outer")
        for index, hole in enumerate(self.hole_loops):
            validate_simple_loop(hole, f"multi-loop hole {index}")
        for hole_index, hole in enumerate(self.hole_loops):
            if not _point_in_polygon(hole[0], self.outer_loop):
                raise ValueError(f"multi-loop hole {hole_index} lies outside outer loop")
            if _loops_intersect(self.outer_loop, hole):
                raise ValueError(f"multi-loop hole {hole_index} crosses outer loop")
            for prior_index, prior in enumerate(self.hole_loops[:hole_index]):
                if _loops_intersect(prior, hole) or _point_in_polygon(hole[0], prior):
                    raise ValueError(
                        f"multi-loop holes {prior_index} and {hole_index} overlap"
                    )
        return self


class GeometryNodesTemplateGeometry(StructuralStrictModel):
    """Instantiate one fully whitelisted Geometry Nodes template with bounded inputs."""

    kind: Literal["geometry_nodes_template"] = "geometry_nodes_template"
    template_id: Literal["linear_instance_v1"] = "linear_instance_v1"
    count: int = Field(ge=1, le=1024)
    spacing: Vec3
    instance_dimensions: Vec3
    realize_instances: Literal[True] = True

    @model_validator(mode="after")
    def validate_template_parameters(self) -> GeometryNodesTemplateGeometry:
        """Require a nonzero spacing direction and strictly positive instance dimensions."""

        if sum(value * value for value in self.spacing) <= 1.0e-18:
            raise ValueError("linear_instance_v1 spacing must be nonzero")
        if any(value <= 0 for value in self.instance_dimensions):
            raise ValueError("linear_instance_v1 instance dimensions must be positive")
        return self


def _point_in_polygon(point: Vec2, polygon: list[Vec2]) -> bool:
    """Return deterministic odd-even containment for a validated 2D polygon."""

    inside = False
    x, y = point
    for first, second in zip(polygon, [*polygon[1:], polygon[0]], strict=True):
        if (first[1] > y) == (second[1] > y):
            continue
        crossing_x = (second[0] - first[0]) * (y - first[1]) / (
            second[1] - first[1]
        ) + first[0]
        if x < crossing_x:
            inside = not inside
    return inside


def _loops_intersect(left: list[Vec2], right: list[Vec2]) -> bool:
    """Return whether any edge from two validated loops intersects."""

    left_edges = list(zip(left, [*left[1:], left[0]], strict=True))
    right_edges = list(zip(right, [*right[1:], right[0]], strict=True))
    return any(
        _segments_intersect(*left_edge, *right_edge)
        for left_edge in left_edges
        for right_edge in right_edges
    )


BooleanOperandGeometry = Annotated[
    PrimitiveGeometry
    | ProfileExtrudeGeometry
    | RevolveGeometry
    | LoftGeometry
    | SweepGeometry
    | MultiLoopExtrudeGeometry,
    Field(discriminator="kind"),
]


class BooleanOperand(StructuralStrictModel):
    """Declare one whitelisted mesh operand with a stable tree-local identity."""

    id: StableId
    geometry: BooleanOperandGeometry
    transform: TransformSpec = Field(default_factory=TransformSpec)


class BooleanOperation(StructuralStrictModel):
    """Combine two previously declared nodes in a topologically ordered Boolean tree."""

    id: StableId
    operation: Literal["UNION", "DIFFERENCE", "INTERSECT"]
    left_id: StableId
    right_id: StableId
    solver: Literal["EXACT"] = "EXACT"


class BooleanTreeGeometry(StructuralStrictModel):
    """Evaluate a bounded declarative binary Boolean tree without arbitrary code."""

    kind: Literal["boolean_tree"] = "boolean_tree"
    operands: list[BooleanOperand] = Field(min_length=2, max_length=32)
    operations: list[BooleanOperation] = Field(min_length=1, max_length=31)
    root_id: StableId
    fail_on_non_manifold: bool = True

    @model_validator(mode="after")
    def validate_tree(self) -> BooleanTreeGeometry:
        """Require one complete acyclic binary tree with no orphan or reused nodes."""

        operand_ids = [item.id for item in self.operands]
        operation_ids = [item.id for item in self.operations]
        ids = [*operand_ids, *operation_ids]
        if len(ids) != len(set(ids)):
            raise ValueError("boolean-tree operand and operation IDs must be unique")
        available = set(operand_ids)
        consumed: dict[str, int] = {item: 0 for item in ids}
        for operation in self.operations:
            if operation.left_id == operation.right_id:
                raise ValueError("boolean-tree operation cannot reuse one node as both inputs")
            missing = sorted({operation.left_id, operation.right_id} - available)
            if missing:
                raise ValueError(
                    f"boolean-tree operation {operation.id} references unavailable nodes: {missing}"
                )
            consumed[operation.left_id] += 1
            consumed[operation.right_id] += 1
            available.add(operation.id)
        if self.root_id != self.operations[-1].id:
            raise ValueError("boolean-tree root_id must name the final operation")
        if len(self.operations) != len(self.operands) - 1:
            raise ValueError("boolean-tree must contain exactly operands-1 operations")
        invalid_usage = sorted(
            node_id
            for node_id, count in consumed.items()
            if node_id != self.root_id and count != 1
        )
        if invalid_usage:
            raise ValueError(
                "boolean-tree nodes must be consumed exactly once: " + ", ".join(invalid_usage)
            )
        return self


GeometrySpecV03 = Annotated[
    PrimitiveGeometry
    | CustomMeshGeometry
    | ProfileExtrudeGeometry
    | RevolveGeometry
    | CurveGeometry
    | TerrainGeometry
    | LoftGeometry
    | SweepGeometry
    | BooleanTreeGeometry
    | MultiLoopExtrudeGeometry
    | GeometryNodesTemplateGeometry,
    Field(discriminator="kind"),
]


class EdgeReference(StructuralStrictModel):
    """Address one compiled mesh edge by its canonical ordered vertex pair."""

    vertices: tuple[int, int]

    @model_validator(mode="after")
    def validate_vertices(self) -> EdgeReference:
        """Require nonnegative distinct vertex indices in canonical ascending order."""

        first, second = self.vertices
        if first < 0 or second < 0 or first >= second:
            raise ValueError("edge vertices must be nonnegative, distinct, and ascending")
        return self


class WeightedEdge(EdgeReference):
    """Attach one normalized crease or bevel weight to a canonical edge."""

    weight: float = Field(gt=0, le=1)


class FaceGroup(StructuralStrictModel):
    """Assign a stable group name to deterministic compiled polygon indices."""

    id: StableId
    face_indices: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_faces(self) -> FaceGroup:
        """Require ordered unique nonnegative polygon indices."""

        if self.face_indices != sorted(set(self.face_indices)) or any(
            index < 0 for index in self.face_indices
        ):
            raise ValueError("face group indices must be nonnegative, ordered, and unique")
        return self


class SmoothingPolicy(StructuralStrictModel):
    """Describe deterministic flat, angle-based, or weighted hard-surface shading."""

    mode: Literal["legacy", "flat", "smooth_by_angle", "weighted_normals"] = "legacy"
    angle_degrees: float = Field(default=30.0, gt=0, lt=180)
    keep_sharp: bool = True


class SubdivisionIntent(StructuralStrictModel):
    """Record bounded subdivision intent without silently adding unsupported topology."""

    enabled: bool = False
    levels: int = Field(default=0, ge=0, le=4)
    boundary_smoothing: Literal["preserve_corners", "smooth_all"] = "preserve_corners"

    @model_validator(mode="after")
    def validate_levels(self) -> SubdivisionIntent:
        """Require positive levels only when subdivision intent is enabled."""

        if self.enabled != (self.levels > 0):
            raise ValueError("enabled subdivision intent must use positive levels")
        return self


class LODIntent(StructuralStrictModel):
    """Carry advisory semantic LOD policy into later V0.7 review."""

    preserve_silhouette: bool = True
    protected_face_groups: list[StableId] = Field(default_factory=list)
    minimum_triangle_ratio: float = Field(default=0.25, gt=0, le=1)


class GeometryIntent(StructuralStrictModel):
    """Preserve face, edge, shading, topology, subdivision, and LOD intent."""

    face_groups: list[FaceGroup] = Field(default_factory=list)
    sharp_edges: list[EdgeReference] = Field(default_factory=list)
    crease_edges: list[WeightedEdge] = Field(default_factory=list)
    bevel_weights: list[WeightedEdge] = Field(default_factory=list)
    uv_seams: list[EdgeReference] = Field(default_factory=list)
    smoothing_policy: SmoothingPolicy = Field(default_factory=SmoothingPolicy)
    topology_policy: Literal[
        "static_prop_closed",
        "static_prop_open",
        "game_ready_lowpoly",
        "highpoly_bake_source",
        "modular_architecture",
        "terrain",
    ] = "static_prop_closed"
    subdivision_intent: SubdivisionIntent = Field(default_factory=SubdivisionIntent)
    lod_intent: LODIntent = Field(default_factory=LODIntent)

    @model_validator(mode="after")
    def validate_intent(self) -> GeometryIntent:
        """Require unique face groups and non-conflicting canonical edge declarations."""

        group_ids = [item.id for item in self.face_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("geometry intent face-group IDs must be unique")
        for label, values in (
            ("sharp_edges", self.sharp_edges),
            ("crease_edges", self.crease_edges),
            ("bevel_weights", self.bevel_weights),
            ("uv_seams", self.uv_seams),
        ):
            keys = [item.vertices for item in values]
            if len(keys) != len(set(keys)):
                raise ValueError(f"geometry intent {label} must not repeat edges")
        return self


class ObjectSpecV03(StructuralStrictModel):
    """Extend a SceneSpec object with structural recipes and explicit geometry intent."""

    id: StableId
    name: str = Field(min_length=1)
    geometry: GeometrySpecV03
    geometry_intent: GeometryIntent | None = None
    transform: TransformSpec = Field(default_factory=TransformSpec)
    material_id: StableId
    modifiers: list[ModifierSpec] = Field(default_factory=list)
    generator: ArrayGenerator | None = None
    parent_id: StableId | None = None
    shade_smooth: bool = False
    tags: list[str] = Field(default_factory=list)
    evidence: list[EvidenceSpec] = Field(default_factory=list)
    editable: dict[str, Any] = Field(default_factory=dict)


class StructuralGeometryCandidate(StructuralStrictModel):
    """Bind one opt-in structural recipe and intent before isolated materialization."""

    schema_version: Literal["0.1.0"] = CONTRACT_VERSION
    semantic_id: StableId
    geometry: Annotated[
        LoftGeometry
        | SweepGeometry
        | BooleanTreeGeometry
        | MultiLoopExtrudeGeometry
        | GeometryNodesTemplateGeometry,
        Field(discriminator="kind"),
    ]
    geometry_intent: GeometryIntent | None = None


class SceneSpecV03(StructuralStrictModel):
    """Provide a parallel opt-in SceneSpec without changing the legacy 0.2 contract."""

    schema_version: Literal["0.3.0"] = SCHEMA_VERSION
    job_id: JobId
    mode: Literal["concept", "measured"]
    units: Literal["METERS"] = "METERS"
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    nominal_scene_size: Vec3
    sources: list[SourceSpec]
    materials: list[MaterialSpec]
    objects: list[ObjectSpecV03]
    camera: CameraSpec
    assumptions: list[str] = Field(default_factory=list)
    revision_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids_and_links(self) -> SceneSpecV03:
        """Validate unique identities, object links, and finite positive scene scale."""

        material_ids = [item.id for item in self.materials]
        object_ids = [item.id for item in self.objects]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("duplicate material IDs")
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("duplicate object IDs")
        object_set = set(object_ids)
        missing_materials = sorted(
            {item.material_id for item in self.objects} - set(material_ids)
        )
        if missing_materials:
            raise ValueError(f"objects reference missing materials: {missing_materials}")
        missing_parents = sorted(
            {item.parent_id for item in self.objects if item.parent_id} - object_set
        )
        if missing_parents:
            raise ValueError(f"objects reference missing parents: {missing_parents}")
        parent_by_id = {
            item.id: item.parent_id for item in self.objects if item.parent_id is not None
        }
        for start in sorted(parent_by_id):
            visited = {start}
            current = start
            while current in parent_by_id:
                parent = parent_by_id[current]
                if parent is None:
                    break
                if parent in visited:
                    raise ValueError("object parent cycle detected")
                visited.add(parent)
                current = parent
        if any(not math.isfinite(value) or value <= 0 for value in self.nominal_scene_size):
            raise ValueError("nominal_scene_size must contain finite positive values")
        return self


class MeshFinding(StructuralStrictModel):
    """Record one deterministic warning or failure discovered during materialization."""

    code: StableId
    severity: Literal["info", "warning", "error"]
    message: str = Field(min_length=1)


class StructuralMeshPayload(StructuralStrictModel):
    """Store one strict materialized mesh with stable face ordering and optional intent."""

    schema_version: Literal["0.1.0"] = CONTRACT_VERSION
    semantic_id: StableId
    builder_kind: Literal[
        "loft",
        "sweep",
        "boolean_tree",
        "multi_loop_extrude",
        "geometry_nodes_template",
    ]
    vertices: list[Vec3] = Field(min_length=3)
    faces: list[list[int]] = Field(min_length=1)
    loop_uvs: list[list[Vec2]] | None = None
    geometry_intent: GeometryIntent | None = None
    findings: list[MeshFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mesh(self) -> StructuralMeshPayload:
        """Reject invalid indices, degenerate faces, and mismatched polygon-corner UVs."""

        count = len(self.vertices)
        for index, face in enumerate(self.faces):
            if len(face) < 3 or len(set(face)) < 3:
                raise ValueError(f"mesh face {index} is degenerate")
            if any(item < 0 or item >= count for item in face):
                raise ValueError(f"mesh face {index} references an invalid vertex")
        if self.loop_uvs is not None:
            if len(self.loop_uvs) != len(self.faces):
                raise ValueError("mesh loop_uvs must match face count")
            if any(
                len(uvs) != len(face)
                for face, uvs in zip(self.faces, self.loop_uvs, strict=True)
            ):
                raise ValueError("mesh loop_uvs must match every face corner count")
        return self


class Bounds3D(StructuralStrictModel):
    """Store one finite positive axis-aligned metric bounding box."""

    minimum: Vec3
    maximum: Vec3

    @model_validator(mode="after")
    def validate_bounds(self) -> Bounds3D:
        """Require strictly positive finite extents."""

        if any(
            not math.isfinite(low)
            or not math.isfinite(high)
            or high <= low
            for low, high in zip(self.minimum, self.maximum, strict=True)
        ):
            raise ValueError("bounds require finite maximum values above minimum values")
        return self

    def dimensions(self) -> Vec3:
        """Return metric dimensions in X, Y, Z order."""

        return tuple(
            high - low
            for low, high in zip(self.minimum, self.maximum, strict=True)
        )  # type: ignore[return-value]


class StructuralEvidenceArtifact(StructuralStrictModel):
    """Bind one scale-context input to a contained path and exact digest."""

    role: Literal[
        "scene_spec",
        "modeling_plan",
        "reference",
        "inventory",
        "constraint_report",
        "other",
    ]
    path: JobRelativePath
    sha256: Sha256


def structural_artifact_input_sha256(
    artifacts: list[StructuralEvidenceArtifact],
) -> str:
    """Hash an ordered structural provenance list as the exact context input."""

    payload = json.dumps(
        [item.model_dump(mode="json") for item in artifacts],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class AssetScaleContext(StructuralStrictModel):
    """Resolve scale parameters inside one exact immutable AQ evidence envelope."""

    schema_version: Literal["0.1.0"]
    asset_id: StableId
    job_id: JobId
    workflow_id: StableId
    dispatch_id: StableId
    input_sha256: Sha256
    source_fingerprint: Sha256
    producer: str = Field(min_length=1, max_length=128)
    producer_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    provenance: list[StructuralEvidenceArtifact] = Field(min_length=1)
    created_at: AwareDatetime
    local_bbox: Bounds3D
    assembly_bbox: Bounds3D
    shortest_dimension_m: float = Field(gt=0)
    projected_pixel_size: float = Field(gt=0)
    target_texel_density_px_m: float = Field(gt=0)
    ratio_overrides: dict[str, float] = Field(default_factory=dict)
    absolute_overrides_m: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_context(self) -> AssetScaleContext:
        """Bind the stored shortest dimension to the local evidence bounds."""

        if self.input_sha256 != structural_artifact_input_sha256(self.provenance):
            raise ValueError("AssetScaleContext input_sha256 differs from provenance")
        paths = [item.path for item in self.provenance]
        if len(paths) != len(set(paths)):
            raise ValueError("AssetScaleContext provenance paths must be unique")
        expected = min(self.local_bbox.dimensions())
        if not math.isclose(self.shortest_dimension_m, expected, abs_tol=1.0e-9):
            raise ValueError("shortest_dimension_m does not match local_bbox")
        if any(value <= 0 for value in self.ratio_overrides.values()):
            raise ValueError("scale ratio overrides must be positive")
        if any(value <= 0 for value in self.absolute_overrides_m.values()):
            raise ValueError("scale absolute overrides must be positive")
        overlap = sorted(set(self.ratio_overrides) & set(self.absolute_overrides_m))
        if overlap:
            raise ValueError(
                "scale parameters cannot have ratio and absolute overrides: "
                f"{overlap}"
            )
        return self

    @classmethod
    def from_bounds(
        cls,
        *,
        asset_id: str,
        job_id: str,
        workflow_id: str,
        dispatch_id: str,
        source_fingerprint: str,
        producer: str,
        producer_version: str,
        provenance: list[StructuralEvidenceArtifact],
        created_at: AwareDatetime,
        local_minimum: Vec3,
        local_maximum: Vec3,
        assembly_minimum: Vec3,
        assembly_maximum: Vec3,
        projected_pixel_size: float,
        target_texel_density_px_m: float,
        ratio_overrides: dict[str, float] | None = None,
        absolute_overrides_m: dict[str, float] | None = None,
    ) -> AssetScaleContext:
        """Construct a scale context and derive its shortest local dimension."""

        local = Bounds3D(minimum=local_minimum, maximum=local_maximum)
        assembly = Bounds3D(minimum=assembly_minimum, maximum=assembly_maximum)
        return cls(
            schema_version=CONTRACT_VERSION,
            asset_id=asset_id,
            job_id=job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            input_sha256=structural_artifact_input_sha256(provenance),
            source_fingerprint=source_fingerprint,
            producer=producer,
            producer_version=producer_version,
            provenance=provenance,
            created_at=created_at,
            local_bbox=local,
            assembly_bbox=assembly,
            shortest_dimension_m=min(local.dimensions()),
            projected_pixel_size=projected_pixel_size,
            target_texel_density_px_m=target_texel_density_px_m,
            ratio_overrides=ratio_overrides or {},
            absolute_overrides_m=absolute_overrides_m or {},
        )

    def resolve_length(self, parameter: str, default_ratio: float) -> float:
        """Resolve one length from an absolute override or shortest-dimension ratio."""

        if default_ratio <= 0:
            raise ValueError("default_ratio must be positive")
        if parameter in self.absolute_overrides_m:
            return self.absolute_overrides_m[parameter]
        ratio = self.ratio_overrides.get(parameter, default_ratio)
        return self.shortest_dimension_m * ratio

    def recommended_texture_resolution(self, maximum: int = 8192) -> int:
        """Return a bounded power-of-two texture resolution from scale evidence."""

        if maximum < 1:
            raise ValueError("maximum texture resolution must be positive")
        longest = max(self.assembly_bbox.dimensions())
        target = max(
            self.projected_pixel_size,
            longest * self.target_texel_density_px_m,
        )
        resolution = 1
        while resolution < target and resolution < maximum:
            resolution *= 2
        return min(resolution, maximum)
