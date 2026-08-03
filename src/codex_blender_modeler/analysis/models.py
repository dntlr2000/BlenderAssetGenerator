from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
BBox4 = tuple[float, float, float, float]
RGB = tuple[int, int, int]
Axis = Literal["X", "Y", "Z"]
SignedAxis = Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
RequiredAssemblyCheck = Literal["position", "axis", "orientation", "clearance"]


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
        """Require one normalized, positive-area reference content box."""

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
    assembly_role: Literal[
        "unclassified",
        "root",
        "attached",
        "free_standing",
    ] = "unclassified"
    required_assembly_checks: list[RequiredAssemblyCheck] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_required_assembly_checks(self) -> ModelingPlanObject:
        """Keep per-object assembly-check requirements unique and deterministic."""

        if len(self.required_assembly_checks) != len(
            set(self.required_assembly_checks)
        ):
            raise ValueError("required_assembly_checks values must be unique")
        return self


class AssemblyTolerance(StrictModel):
    """Define one unambiguous absolute or reference-relative assembly tolerance."""

    mode: Literal["relative", "meters"] = "relative"
    value: float = Field(default=0.05, gt=0)

    @model_validator(mode="after")
    def validate_relative_value(self) -> AssemblyTolerance:
        """Keep normalized tolerances inside one reference-object extent."""

        if not math.isfinite(self.value):
            raise ValueError("Assembly tolerance must be finite")
        if self.mode == "relative" and self.value > 1:
            raise ValueError("Relative assembly tolerance must be within (0, 1]")
        return self


class AssemblyDistance(StrictModel):
    """Define one nonnegative meter or reference-relative assembly gap."""

    mode: Literal["relative", "meters"] = "relative"
    value: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def validate_finite_value(self) -> AssemblyDistance:
        """Reject an infinite gap that could never be verified geometrically."""

        if not math.isfinite(self.value):
            raise ValueError("Assembly distance must be finite")
        return self


class AssemblyFrame(StrictModel):
    """Describe the intrinsic 3D axes used to judge one assembled asset."""

    root_object_id: str
    longitudinal_axis: Axis
    lateral_axis: Axis
    vertical_axis: Axis
    symmetry: Literal["bilateral", "asymmetric", "unknown"] = "unknown"
    evidence_status: Literal["observed", "inferred", "measured", "authored"] = "inferred"
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_frame_axes_and_evidence(self) -> AssemblyFrame:
        """Require an orthogonal axis permutation and traceable claimed evidence."""

        axes = [self.longitudinal_axis, self.lateral_axis, self.vertical_axis]
        if len(set(axes)) != 3:
            raise ValueError("Assembly frame axes must be a unique X/Y/Z permutation")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Assembly frame source IDs must be unique")
        if any(not item.strip() for item in self.source_ids):
            raise ValueError("Assembly frame source IDs cannot be blank")
        if self.evidence_status in {"observed", "measured"} and not self.source_ids:
            raise ValueError(
                "Observed or measured assembly frames require at least one source ID"
            )
        return self


class AssemblyRelationshipBase(StrictModel):
    """Store identity, evidence, tolerance, and instance policy shared by all relations."""

    id: str
    subject_id: str
    reference_id: str
    evidence_status: Literal["observed", "inferred", "measured", "authored"] = "inferred"
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    required: bool = True
    tolerance: AssemblyTolerance = Field(default_factory=AssemblyTolerance)
    instance_policy: Literal[
        "family_bounds",
        "pairwise",
        "broadcast_reference",
    ] = "family_bounds"
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity_and_evidence(self) -> AssemblyRelationshipBase:
        """Reject ambiguous links, blank stable IDs, and untraceable claimed evidence."""

        stable_ids = [self.id, self.subject_id, self.reference_id]
        if any(
            not item.strip() or any(character.isspace() for character in item)
            for item in stable_ids
        ):
            raise ValueError("Assembly relationship IDs must be nonblank and whitespace-free")
        if self.subject_id == self.reference_id:
            raise ValueError("Assembly relationship subject and reference must differ")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("Assembly relationship source IDs must be unique")
        if any(not item.strip() for item in self.source_ids):
            raise ValueError("Assembly relationship source IDs cannot be blank")
        if self.evidence_status in {"observed", "measured"} and not self.source_ids:
            raise ValueError(
                "Observed or measured assembly relationships require source IDs"
            )
        return self


class CenterPlaneRelationship(AssemblyRelationshipBase):
    """Require one subject center to remain on a reference center plane."""

    kind: Literal["center_plane"] = "center_plane"
    axis: Axis


class CoaxialRelationship(AssemblyRelationshipBase):
    """Require subject and reference centers to align on two transverse axes."""

    kind: Literal["coaxial"] = "coaxial"
    axes: tuple[Axis, Axis]

    @model_validator(mode="after")
    def validate_axes(self) -> CoaxialRelationship:
        """Reject a degenerate coaxial relation that repeats one axis."""

        if len(set(self.axes)) != 2:
            raise ValueError("Coaxial relationship axes must be unique")
        return self


class BBoxContainmentRelationship(AssemblyRelationshipBase):
    """Require subject bounds to stay inside reference bounds on selected axes."""

    kind: Literal["bbox_containment"] = "bbox_containment"
    axes: list[Axis] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_axes(self) -> BBoxContainmentRelationship:
        """Keep containment axes unique so residuals remain deterministic."""

        if len(self.axes) != len(set(self.axes)):
            raise ValueError("BBox-containment axes must be unique")
        return self


class SurfaceContactRelationship(AssemblyRelationshipBase):
    """Require one subject bound face to meet one reference bound face."""

    kind: Literal["surface_contact"] = "surface_contact"
    axis: Axis
    subject_side: Literal["MIN", "MAX"]
    reference_side: Literal["MIN", "MAX"]
    min_transverse_overlap_ratio: float = Field(default=0.05, gt=0, le=1)


class SideSpecificRelationship(AssemblyRelationshipBase):
    """Require an explicitly justified subject to remain on one side of a reference."""

    kind: Literal["side_specific"] = "side_specific"
    axis: Axis
    side: Literal["MIN", "MAX"]

    @model_validator(mode="after")
    def validate_side_evidence(self) -> SideSpecificRelationship:
        """Forbid an inferred-only claim that moves a component onto one side."""

        if self.evidence_status == "inferred":
            raise ValueError(
                "side_specific relationships require observed, measured, or authored evidence"
            )
        return self


class BilateralPairRelationship(AssemblyRelationshipBase):
    """Require two peer subjects to mirror around one reference center plane."""

    kind: Literal["bilateral_pair"] = "bilateral_pair"
    axis: Axis
    peer_id: str

    @model_validator(mode="after")
    def validate_peer_identity(self) -> BilateralPairRelationship:
        """Reject blank, self, reference, or whitespace-bearing peer IDs."""

        if not self.peer_id.strip() or any(character.isspace() for character in self.peer_id):
            raise ValueError("Bilateral peer ID must be nonblank and whitespace-free")
        if self.peer_id in {self.subject_id, self.reference_id}:
            raise ValueError("Bilateral peer must differ from subject and reference")
        return self


class AxisAlignmentRelationship(AssemblyRelationshipBase):
    """Require one evaluated local subject axis to follow a declared 3D direction."""

    kind: Literal["axis_alignment"] = "axis_alignment"
    subject_axis: SignedAxis
    target_direction: Vec3
    target_space: Literal["reference_local", "assembly_frame"] = "reference_local"
    directionality: Literal["directed", "undirected"] = "directed"
    angular_tolerance_deg: float = Field(default=5.0, gt=0, le=90)

    @model_validator(mode="after")
    def validate_target_direction(self) -> AxisAlignmentRelationship:
        """Reject zero, non-finite, or otherwise unscorable target directions."""

        if not all(math.isfinite(value) for value in self.target_direction):
            raise ValueError("Axis-alignment target_direction values must be finite")
        magnitude_squared = sum(value * value for value in self.target_direction)
        if magnitude_squared <= 1.0e-18:
            raise ValueError("Axis-alignment target_direction must be nonzero")
        return self


class AxisClearanceRelationship(AssemblyRelationshipBase):
    """Require an axis-directed broad-phase gap between two evaluated bounds."""

    kind: Literal["axis_clearance"] = "axis_clearance"
    axis: Axis
    direction: Literal["POSITIVE", "NEGATIVE"] = Field(
        description=(
            "POSITIVE measures reference.min-subject.max; NEGATIVE measures "
            "subject.min-reference.max on the declared assembly-frame axis."
        )
    )
    minimum_gap: AssemblyDistance = Field(default_factory=AssemblyDistance)
    maximum_gap: AssemblyDistance | None = None
    min_transverse_overlap_ratio: float = Field(default=0.05, gt=0, le=1)

    @model_validator(mode="after")
    def validate_gap_contract(self) -> AxisClearanceRelationship:
        """Keep clearance limits and their tolerance in one comparable unit system."""

        if self.tolerance.mode != self.minimum_gap.mode:
            raise ValueError("Axis-clearance tolerance and minimum_gap modes must match")
        if self.maximum_gap is not None:
            if self.maximum_gap.mode != self.minimum_gap.mode:
                raise ValueError(
                    "Axis-clearance minimum_gap and maximum_gap modes must match"
                )
            if self.maximum_gap.value < self.minimum_gap.value:
                raise ValueError(
                    "Axis-clearance maximum_gap cannot be smaller than minimum_gap"
                )
        return self


def _has_independent_orientation_axes(
    relationships: list[AxisAlignmentRelationship],
) -> bool:
    """Return whether two comparable directed constraints determine 3D facing."""

    directed = [
        relationship
        for relationship in relationships
        if relationship.directionality == "directed"
    ]
    for index, first in enumerate(directed):
        for second in directed[index + 1 :]:
            if first.subject_axis[-1] == second.subject_axis[-1]:
                continue
            if first.target_space != second.target_space:
                continue
            if (
                first.target_space == "reference_local"
                and first.reference_id != second.reference_id
            ):
                continue
            first_length = math.sqrt(sum(value * value for value in first.target_direction))
            second_length = math.sqrt(
                sum(value * value for value in second.target_direction)
            )
            normalized_dot = sum(
                left * right
                for left, right in zip(
                    first.target_direction,
                    second.target_direction,
                    strict=True,
                )
            ) / (first_length * second_length)
            target_angle_deg = math.degrees(
                math.acos(max(-1.0, min(1.0, normalized_dot)))
            )
            allowed_error_deg = (
                first.angular_tolerance_deg + second.angular_tolerance_deg
            )
            if abs(target_angle_deg - 90.0) <= allowed_error_deg + 1.0e-9:
                return True
    return False


AssemblyRelationship = Annotated[
    CenterPlaneRelationship
    | CoaxialRelationship
    | BBoxContainmentRelationship
    | SurfaceContactRelationship
    | SideSpecificRelationship
    | BilateralPairRelationship
    | AxisAlignmentRelationship
    | AxisClearanceRelationship,
    Field(discriminator="kind"),
]


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


class AssemblyValidationCheck(StrictModel):
    """Record one prebuild or evaluated-bounds assembly consistency check."""

    id: str
    relation_id: str | None = None
    kind: str
    status: Literal["passed", "warning", "failed"]
    required: bool = True
    evidence_status: Literal["observed", "inferred", "measured", "authored"] | None = None
    source_ids: list[str] = Field(default_factory=list)
    subject_id: str | None = None
    reference_id: str | None = None
    peer_id: str | None = None
    instance_index: int | None = Field(default=None, ge=0)
    residual: float | None = Field(default=None, ge=0)
    tolerance: float | None = Field(default=None, ge=0)
    tolerance_mode: Literal["relative", "meters", "degrees"] | None = None
    message: str
    metrics: dict[str, object] = Field(default_factory=dict)


class AssemblyValidationReport(StrictModel):
    """Summarize contract or evaluated-bounds assembly consistency evidence."""

    schema_version: Literal["0.4.0"] = "0.4.0"
    job_id: str
    policy: Literal["legacy_unbound", "spatial_v1"]
    phase: Literal["prebuild", "bounds"]
    ok: bool
    passed: int = Field(ge=0)
    warnings: int = Field(ge=0)
    failed: int = Field(ge=0)
    checks: list[AssemblyValidationCheck] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_summary(self) -> AssemblyValidationReport:
        """Keep report counters and success status consistent with its checks."""

        passed = sum(item.status == "passed" for item in self.checks)
        warnings = sum(item.status == "warning" for item in self.checks)
        failed = sum(item.status == "failed" for item in self.checks)
        if (self.passed, self.warnings, self.failed) != (passed, warnings, failed):
            raise ValueError("Assembly-validation counts do not match checks")
        if self.ok != (failed == 0):
            raise ValueError("Assembly-validation ok must match failed==0")
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
    assembly_consistency_policy: Literal[
        "legacy_unbound",
        "spatial_v1",
    ] = "legacy_unbound"
    assembly_frame: AssemblyFrame | None = None
    assembly_relationships: list[AssemblyRelationship] = Field(default_factory=list)
    surface_detail_policy: SurfaceDetailPolicy | None = None
    surface_details: list[SurfaceDetailDecision] = Field(default_factory=list)
    global_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_authored_objects(self) -> ModelingPlan:
        """Require stable authored objects plus a coherent optional spatial assembly contract."""

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
        relationship_ids = [item.id for item in self.assembly_relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("Assembly relationship IDs must be unique")
        if self.assembly_consistency_policy == "legacy_unbound":
            if self.assembly_frame is not None or self.assembly_relationships:
                raise ValueError(
                    "legacy_unbound plans cannot claim an assembly frame or relationships"
                )
            required_checks = sorted(
                item.id for item in self.objects if item.required_assembly_checks
            )
            if required_checks:
                raise ValueError(
                    "legacy_unbound plans cannot claim required assembly checks: "
                    f"{required_checks}"
                )
        elif self.stage == "authored":
            if self.assembly_frame is None:
                raise ValueError("spatial_v1 authored plans require an assembly frame")
            unclassified = sorted(
                item.id for item in self.objects if item.assembly_role == "unclassified"
            )
            if unclassified:
                raise ValueError(
                    "spatial_v1 authored objects require assembly_role classification: "
                    f"{unclassified}"
                )
            object_by_id = {item.id: item for item in self.objects}
            root = object_by_id.get(self.assembly_frame.root_object_id)
            if root is None:
                raise ValueError("Assembly frame root_object_id is missing from objects")
            if root.assembly_role != "root":
                raise ValueError("Assembly frame root object must use assembly_role='root'")
            source_ids = {
                source_id
                for item in self.objects
                for source_id in item.source_ids
            }
            missing_frame_sources = sorted(
                set(self.assembly_frame.source_ids) - source_ids
            )
            if missing_frame_sources:
                raise ValueError(
                    "Assembly frame references source IDs absent from modeling objects: "
                    f"{missing_frame_sources}"
                )
            linked_ids: set[str] = set()
            relationship_subjects: set[str] = set()
            required_relations_by_subject: dict[str, list[AssemblyRelationship]] = {}
            for relationship in self.assembly_relationships:
                linked_ids.update(
                    [relationship.subject_id, relationship.reference_id]
                )
                relationship_subjects.add(relationship.subject_id)
                if relationship.required:
                    required_relations_by_subject.setdefault(
                        relationship.subject_id, []
                    ).append(relationship)
                if isinstance(relationship, BilateralPairRelationship):
                    linked_ids.add(relationship.peer_id)
                if (
                    isinstance(relationship, AxisAlignmentRelationship)
                    and relationship.target_space == "assembly_frame"
                    and relationship.reference_id != self.assembly_frame.root_object_id
                ):
                    raise ValueError(
                        "Assembly-frame axis_alignment relationships must reference "
                        "the declared assembly-frame root object"
                    )
                missing_sources = sorted(
                    set(relationship.source_ids) - source_ids
                )
                if missing_sources:
                    raise ValueError(
                        f"Assembly relationship {relationship.id!r} references source IDs "
                        f"absent from modeling objects: {missing_sources}"
                    )
            missing_links = sorted(linked_ids - set(object_by_id))
            if missing_links:
                raise ValueError(
                    "Assembly relationships reference missing modeling objects: "
                    f"{missing_links}"
                )
            unattached = sorted(
                item.id
                for item in self.objects
                if item.assembly_role == "attached"
                and item.id not in relationship_subjects
            )
            if unattached:
                raise ValueError(
                    "Attached assembly objects require at least one subject relationship: "
                    f"{unattached}"
                )
            missing_required_checks: list[str] = []
            for item in self.objects:
                relations = required_relations_by_subject.get(item.id, [])
                axis_relations = [
                    relation
                    for relation in relations
                    if isinstance(relation, AxisAlignmentRelationship)
                ]
                position_relations = [
                    relation
                    for relation in relations
                    if not isinstance(relation, AxisAlignmentRelationship)
                ]
                for check in item.required_assembly_checks:
                    satisfied = True
                    if check == "position":
                        satisfied = bool(position_relations)
                    elif check == "axis":
                        satisfied = bool(axis_relations)
                    elif check == "orientation":
                        satisfied = _has_independent_orientation_axes(axis_relations)
                    elif check == "clearance":
                        satisfied = any(
                            isinstance(relation, AxisClearanceRelationship)
                            for relation in relations
                        )
                    if not satisfied:
                        missing_required_checks.append(f"{item.id}:{check}")
            if missing_required_checks:
                raise ValueError(
                    "Modeling objects lack required assembly-check relationships: "
                    f"{sorted(missing_required_checks)}"
                )
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
