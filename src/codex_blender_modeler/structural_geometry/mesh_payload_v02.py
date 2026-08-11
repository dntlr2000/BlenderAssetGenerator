"""Strict MeshPayload 0.2 contracts for opt-in AQ v2 structural compilation."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

MESH_PAYLOAD_V02_VERSION = "0.2.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
STABLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
JOB_RELATIVE_SCHEMA_PATTERN = (
    r"^(?!/)(?![A-Za-z]:)(?!.*:)(?!.*(?:^|/)\.\.(?:/|$))(?!.*\\)(?!.*//)"
    r"[^\u0000]+$"
)

Vec2: TypeAlias = tuple[float, float]
Vec3: TypeAlias = tuple[float, float, float]
ScalarAttributeValue: TypeAlias = bool | int | float


def _validate_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by an owning job workspace."""

    if not value or "\x00" in value or "\\" in value or ":" in value:
        raise ValueError("path must be a non-empty POSIX job-relative path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must be job-relative")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("path contains an unsafe segment")
    if str(PurePosixPath(value)) != value:
        raise ValueError("path must use normalized POSIX syntax")
    return value


Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
StableId = Annotated[str, Field(pattern=STABLE_ID_PATTERN)]
JobRelativePath = Annotated[
    str,
    Field(min_length=1, json_schema_extra={"pattern": JOB_RELATIVE_SCHEMA_PATTERN}),
    AfterValidator(_validate_relative_path),
]


class MeshPayloadV02StrictModel(BaseModel):
    """Reject unknown fields and non-finite values in every v2 payload record."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


def canonical_json_sha256(value: object) -> str:
    """Return a deterministic SHA-256 for one JSON-compatible value or model."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class EdgeReferenceV02(MeshPayloadV02StrictModel):
    """Address one materialized edge by its canonical ordered vertex pair."""

    vertices: tuple[int, int]

    @model_validator(mode="after")
    def validate_vertices(self) -> EdgeReferenceV02:
        """Require nonnegative, distinct, ascending vertex indices."""

        first, second = self.vertices
        if first < 0 or second < 0 or first >= second:
            raise ValueError("edge vertices must be nonnegative, distinct, and ascending")
        return self


class WeightedEdgeV02(EdgeReferenceV02):
    """Attach one normalized crease or bevel weight to an exact edge."""

    weight: float = Field(gt=0, le=1)


class FaceGroupV02(MeshPayloadV02StrictModel):
    """Bind a stable face-group ID to ordered materialized polygon indices."""

    id: StableId
    face_indices: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_indices(self) -> FaceGroupV02:
        """Require sorted unique nonnegative face indices."""

        if self.face_indices != sorted(set(self.face_indices)):
            raise ValueError("face-group indices must be sorted and unique")
        if any(index < 0 for index in self.face_indices):
            raise ValueError("face-group indices must be nonnegative")
        return self


class MaterialSlotV02(MeshPayloadV02StrictModel):
    """Declare one ordered Blender material slot with a stable portable identity."""

    slot_index: int = Field(ge=0)
    material_id: StableId


class FaceMaterialIntentV02(MeshPayloadV02StrictModel):
    """Bind one source face group to one exact stable material identity."""

    face_group_id: StableId
    material_id: StableId


class SmoothingPolicyV02(MeshPayloadV02StrictModel):
    """Describe the source polygon-smoothing and explicit-sharp precedence policy."""

    mode: Literal["flat", "smooth", "smooth_by_angle", "weighted_normals"]
    angle_degrees: float | None
    keep_explicit_sharp: bool

    @model_validator(mode="after")
    def validate_angle(self) -> SmoothingPolicyV02:
        """Require a bounded angle only for angle-derived smoothing."""

        if self.mode == "smooth_by_angle":
            if self.angle_degrees is None or not 0 < self.angle_degrees < 180:
                raise ValueError("smooth_by_angle requires angle_degrees within (0, 180)")
        elif self.angle_degrees is not None:
            raise ValueError("angle_degrees is only valid for smooth_by_angle")
        return self


class ModifierDispositionV02(MeshPayloadV02StrictModel):
    """Classify one geometry effect as recreated, baked, or explicitly rejected."""

    effect: Literal[
        "boolean",
        "geometry_nodes",
        "weighted_normal",
        "subdivision",
        "bevel",
        "mirror",
        "solidify",
        "array",
        "decimate",
        "remesh",
        "normal_transfer",
        "custom_attribute",
        "unsupported",
    ]
    disposition: Literal[
        "recreate_in_compiled_build",
        "bake_into_mesh",
        "reject",
    ]
    source_id: StableId
    details_sha256: Sha256


class WeightedNormalIntentV02(MeshPayloadV02StrictModel):
    """Carry a bounded weighted-normal modifier intent into the compiled build."""

    enabled: bool
    keep_sharp: bool
    weight_mode: Literal["FACE_AREA", "CORNER_ANGLE", "FACE_AREA_WITH_ANGLE"]
    disposition: Literal["recreate_in_compiled_build", "reject"]

    @model_validator(mode="after")
    def validate_enabled_disposition(self) -> WeightedNormalIntentV02:
        """Reject an enabled weighted-normal effect that is not recreated."""

        if self.enabled != (self.disposition == "recreate_in_compiled_build"):
            raise ValueError("weighted-normal enabled state disagrees with disposition")
        return self


class SubdivisionIntentV02(MeshPayloadV02StrictModel):
    """Carry one bounded non-destructive subdivision intent into compilation."""

    enabled: bool
    levels: int = Field(ge=0, le=4)
    render_levels: int = Field(ge=0, le=4)
    subdivision_type: Literal["CATMULL_CLARK", "SIMPLE"]
    boundary_smoothing: Literal["ALL", "PRESERVE_CORNERS"]
    disposition: Literal["recreate_in_compiled_build", "reject"]

    @model_validator(mode="after")
    def validate_enabled_disposition(self) -> SubdivisionIntentV02:
        """Reject contradictory levels or a non-recreated enabled subdivision."""

        if self.enabled:
            if self.disposition != "recreate_in_compiled_build":
                raise ValueError("enabled subdivision must be recreated")
            if self.levels < 1 or self.render_levels < self.levels:
                raise ValueError("enabled subdivision requires ordered positive levels")
        elif self.disposition != "reject" or self.levels != 0 or self.render_levels != 0:
            raise ValueError("disabled subdivision must reject zero levels")
        return self


class CustomAttributeManifestEntryV02(MeshPayloadV02StrictModel):
    """Store one bounded scalar custom attribute and its exact value fingerprint."""

    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
    domain: Literal["POINT", "EDGE", "FACE", "CORNER", "OBJECT"]
    data_type: Literal["BOOLEAN", "INT", "FLOAT"]
    value_count: int = Field(ge=1)
    values: list[ScalarAttributeValue] = Field(min_length=1)
    values_sha256: Sha256

    @model_validator(mode="after")
    def validate_values(self) -> CustomAttributeManifestEntryV02:
        """Require type-correct values and a matching deterministic fingerprint."""

        if self.value_count != len(self.values):
            raise ValueError("custom attribute value_count does not match values")
        for value in self.values:
            if self.data_type == "BOOLEAN" and type(value) is not bool:
                raise ValueError("BOOLEAN custom attributes require bool values")
            if self.data_type == "INT" and (type(value) is not int or isinstance(value, bool)):
                raise ValueError("INT custom attributes require integer values")
            if self.data_type == "FLOAT" and (
                isinstance(value, bool) or not isinstance(value, (int, float))
            ):
                raise ValueError("FLOAT custom attributes require numeric values")
        if self.values_sha256 != canonical_json_sha256(self.values):
            raise ValueError("custom attribute values_sha256 does not match values")
        return self


class MeshPayloadSourceHashV02(MeshPayloadV02StrictModel):
    """Bind one contained transitive input to its exact file SHA-256."""

    role: Literal[
        "scene_spec_v03",
        "structural_candidate",
        "geometry_payload",
        "material_binding",
        "source_mesh_payload",
        "other",
    ]
    path: JobRelativePath
    sha256: Sha256


def source_hash_fingerprint(values: list[MeshPayloadSourceHashV02]) -> str:
    """Hash the exact ordered source artifact map used by one payload."""

    return canonical_json_sha256([item.model_dump(mode="json") for item in values])


class MeshPayloadFindingV02(MeshPayloadV02StrictModel):
    """Record one deterministic payload materialization finding."""

    code: StableId
    severity: Literal["info", "warning", "error"]
    message: str = Field(min_length=1)


class SourceGeometryIntentV02(MeshPayloadV02StrictModel):
    """Preserve the exact normalized source intent against materialized mesh state."""

    source_intent_sha256: Sha256
    face_groups: list[FaceGroupV02]
    material_assignments: list[FaceMaterialIntentV02]
    sharp_edges: list[EdgeReferenceV02]
    uv_seams: list[EdgeReferenceV02]
    edge_creases: list[WeightedEdgeV02]
    bevel_weights: list[WeightedEdgeV02]
    smoothing_policy: SmoothingPolicyV02
    topology_profile: Literal[
        "static_prop_closed",
        "static_prop_open",
        "game_ready_lowpoly",
        "highpoly_bake_source",
        "modular_architecture",
        "terrain",
    ]
    weighted_normal_intent: WeightedNormalIntentV02
    subdivision_intent: SubdivisionIntentV02

    @model_validator(mode="after")
    def validate_source_hash(self) -> SourceGeometryIntentV02:
        """Bind source_intent_sha256 to every normalized intent field except itself."""

        payload = self.model_dump(mode="json", exclude={"source_intent_sha256"})
        if self.source_intent_sha256 != canonical_json_sha256(payload):
            raise ValueError("source_intent_sha256 does not match normalized intent")
        return self


class MeshPayloadV02(MeshPayloadV02StrictModel):
    """Store a strict, hash-bound structural mesh with full loop and intent data."""

    schema_version: Literal["0.2.0"] = MESH_PAYLOAD_V02_VERSION
    semantic_id: StableId
    builder_kind: Literal[
        "loft",
        "sweep",
        "boolean_tree",
        "multi_loop_extrude",
        "geometry_nodes_template",
        "custom_mesh",
        "fixture",
    ]
    vertices: list[Vec3] = Field(min_length=3)
    faces: list[list[int]] = Field(min_length=1)
    loop_count: int = Field(ge=3)
    loop_uvs: list[Vec2] = Field(min_length=3)
    material_slots: list[MaterialSlotV02] = Field(min_length=1)
    polygon_material_indices: list[int] = Field(min_length=1)
    sharp_edges: list[EdgeReferenceV02]
    uv_seams: list[EdgeReferenceV02]
    edge_creases: list[WeightedEdgeV02]
    bevel_weights: list[WeightedEdgeV02]
    face_groups: list[FaceGroupV02]
    smooth_polygon_flags: list[bool] = Field(min_length=1)
    smoothing_policy: SmoothingPolicyV02
    custom_attribute_manifest: list[CustomAttributeManifestEntryV02]
    modifier_materialization_policy: list[ModifierDispositionV02]
    weighted_normal_intent: WeightedNormalIntentV02
    subdivision_intent: SubdivisionIntentV02
    source_geometry_intent: SourceGeometryIntentV02
    findings: list[MeshPayloadFindingV02]
    source_hashes: list[MeshPayloadSourceHashV02] = Field(min_length=1)
    source_fingerprint_sha256: Sha256

    @model_validator(mode="after")
    def validate_mesh_and_intent(self) -> MeshPayloadV02:
        """Fail closed on topology, UV, material, intent, and source-map conflicts."""

        vertex_count = len(self.vertices)
        loop_count = 0
        edge_counts: dict[tuple[int, int], int] = {}
        face_keys: set[tuple[int, ...]] = set()
        for face_index, face in enumerate(self.faces):
            if len(face) < 3 or len(set(face)) != len(face):
                raise ValueError(f"mesh face {face_index} is degenerate")
            if any(index < 0 or index >= vertex_count for index in face):
                raise ValueError(f"mesh face {face_index} references an invalid vertex")
            if self._face_area_squared(face) <= 1.0e-24:
                raise ValueError(f"mesh face {face_index} has zero geometric area")
            face_key = tuple(sorted(face))
            if face_key in face_keys:
                raise ValueError(f"mesh face {face_index} duplicates an existing face")
            face_keys.add(face_key)
            loop_count += len(face)
            for first, second in zip(face, [*face[1:], face[0]], strict=True):
                edge = tuple(sorted((first, second)))
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
        if any(count > 2 for count in edge_counts.values()):
            raise ValueError("mesh contains a non-manifold edge shared by more than two faces")
        if (
            self.source_geometry_intent.topology_profile == "static_prop_closed"
            and any(count != 2 for count in edge_counts.values())
        ):
            raise ValueError("static_prop_closed payload contains an open boundary edge")
        if self.loop_count != loop_count or len(self.loop_uvs) != loop_count:
            raise ValueError("loop_count and loop_uvs must match all polygon corners")
        if len(self.polygon_material_indices) != len(self.faces):
            raise ValueError("polygon_material_indices must match face count")
        if len(self.smooth_polygon_flags) != len(self.faces):
            raise ValueError("smooth_polygon_flags must match face count")
        expects_smooth = self.smoothing_policy.mode != "flat"
        if any(value != expects_smooth for value in self.smooth_polygon_flags):
            raise ValueError("smooth_polygon_flags disagree with smoothing_policy")
        if self.sharp_edges and not self.smoothing_policy.keep_explicit_sharp:
            raise ValueError("explicit sharp edges require keep_explicit_sharp=true")

        slot_indices = [slot.slot_index for slot in self.material_slots]
        if slot_indices != list(range(len(self.material_slots))):
            raise ValueError("material slots must be contiguous and ordered from zero")
        material_ids = [slot.material_id for slot in self.material_slots]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("material slot IDs must be unique")
        if any(
            index < 0 or index >= len(self.material_slots)
            for index in self.polygon_material_indices
        ):
            raise ValueError("polygon material index is outside material_slots")

        self._validate_edge_declarations(set(edge_counts))
        self._validate_face_groups_and_materials(material_ids)
        self._validate_custom_attributes(len(edge_counts))
        self._validate_modifier_policy()
        self._validate_source_intent_equivalence()

        paths = [item.path for item in self.source_hashes]
        if len(paths) != len(set(paths)):
            raise ValueError("source_hashes paths must be unique")
        if self.source_fingerprint_sha256 != source_hash_fingerprint(self.source_hashes):
            raise ValueError("source_fingerprint_sha256 does not match source_hashes")
        return self

    def _face_area_squared(self, face: list[int]) -> float:
        """Return the squared Newell normal magnitude for one polygon."""

        normal = [0.0, 0.0, 0.0]
        for first_index, second_index in zip(face, [*face[1:], face[0]], strict=True):
            first = self.vertices[first_index]
            second = self.vertices[second_index]
            normal[0] += (first[1] - second[1]) * (first[2] + second[2])
            normal[1] += (first[2] - second[2]) * (first[0] + second[0])
            normal[2] += (first[0] - second[0]) * (first[1] + second[1])
        return sum(value * value for value in normal)

    def _validate_edge_declarations(self, mesh_edges: set[tuple[int, int]]) -> None:
        """Require unique existing edges in every authored edge channel."""

        channel_values = (
            ("sharp_edges", self.sharp_edges),
            ("uv_seams", self.uv_seams),
            ("edge_creases", self.edge_creases),
            ("bevel_weights", self.bevel_weights),
        )
        for label, values in channel_values:
            keys = [item.vertices for item in values]
            if len(keys) != len(set(keys)):
                raise ValueError(f"{label} contains duplicate edges")
            missing = sorted(set(keys) - mesh_edges)
            if missing:
                raise ValueError(f"{label} references missing mesh edges: {missing}")

    def _validate_face_groups_and_materials(self, material_ids: list[str]) -> None:
        """Require valid groups and exact non-conflicting group material assignments."""

        group_ids = [group.id for group in self.face_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("face-group IDs must be unique")
        for group in self.face_groups:
            if any(index >= len(self.faces) for index in group.face_indices):
                raise ValueError(f"face group {group.id} references a missing polygon")
        assignments = self.source_geometry_intent.material_assignments
        assignment_ids = [item.face_group_id for item in assignments]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("material assignments must not repeat face groups")
        if any(item.face_group_id not in group_ids for item in assignments):
            raise ValueError("material assignment references an unknown face group")
        if any(item.material_id not in material_ids for item in assignments):
            raise ValueError("material assignment references an unknown material slot")
        group_by_id = {group.id: group for group in self.face_groups}
        slot_by_material = {
            slot.material_id: slot.slot_index for slot in self.material_slots
        }
        claimed_faces: dict[int, str] = {}
        for assignment in assignments:
            expected_index = slot_by_material[assignment.material_id]
            for face_index in group_by_id[assignment.face_group_id].face_indices:
                previous = claimed_faces.get(face_index)
                if previous is not None and previous != assignment.material_id:
                    raise ValueError("one polygon has conflicting material assignments")
                claimed_faces[face_index] = assignment.material_id
                if self.polygon_material_indices[face_index] != expected_index:
                    raise ValueError("polygon material index differs from source assignment")
        if len(self.material_slots) > 1:
            if set(claimed_faces) != set(range(len(self.faces))):
                raise ValueError("multi-material source assignments must cover every polygon")
            used = {self.polygon_material_indices[index] for index in claimed_faces}
            if used != set(self.polygon_material_indices):
                raise ValueError("multi-material polygons require source group assignments")

    def _validate_custom_attributes(self, edge_count: int) -> None:
        """Require unique non-reserved attributes with domain-correct value counts."""

        names = [item.name for item in self.custom_attribute_manifest]
        if len(names) != len(set(names)):
            raise ValueError("custom attribute names must be unique")
        reserved = {"crease_edge", "bevel_weight_edge"}
        reserved.update(f"cbm_face_group__{group.id}" for group in self.face_groups)
        overlap = sorted(set(names) & reserved)
        if overlap:
            raise ValueError(f"custom attributes duplicate reserved intent data: {overlap}")
        expected = {
            "POINT": len(self.vertices),
            "EDGE": edge_count,
            "FACE": len(self.faces),
            "CORNER": self.loop_count,
            "OBJECT": 1,
        }
        for item in self.custom_attribute_manifest:
            if item.value_count != expected[item.domain]:
                raise ValueError(
                    f"custom attribute {item.name} count differs from {item.domain} domain"
                )

    def _validate_modifier_policy(self) -> None:
        """Reject duplicate effects and require builder-appropriate bake dispositions."""

        effects = [item.effect for item in self.modifier_materialization_policy]
        if len(effects) != len(set(effects)):
            raise ValueError("modifier materialization policy repeats one effect")
        policy_by_effect = {
            item.effect: item for item in self.modifier_materialization_policy
        }
        by_effect = {
            effect: item.disposition for effect, item in policy_by_effect.items()
        }
        expected = {
            "weighted_normal": self.weighted_normal_intent,
            "subdivision": self.subdivision_intent,
        }
        for effect, intent in expected.items():
            if intent.enabled and by_effect.get(effect) != "recreate_in_compiled_build":
                raise ValueError(f"enabled {effect} intent lacks recreate disposition")
            if not intent.enabled and by_effect.get(effect) == "recreate_in_compiled_build":
                raise ValueError(f"disabled {effect} intent cannot be recreated")
            if intent.enabled and policy_by_effect[effect].details_sha256 != canonical_json_sha256(
                intent.model_dump(mode="json")
            ):
                raise ValueError(f"{effect} recreate policy hash differs from exact intent")
        if self.builder_kind == "boolean_tree" and by_effect.get("boolean") != "bake_into_mesh":
            raise ValueError("boolean_tree payload must classify Boolean evaluation as baked")
        if (
            self.builder_kind == "geometry_nodes_template"
            and by_effect.get("geometry_nodes") != "bake_into_mesh"
        ):
            raise ValueError("geometry_nodes payload must classify evaluated nodes as baked")
        if by_effect.get("bevel") == "recreate_in_compiled_build":
            raise ValueError("recreated bevel requires a future parameterized v2 contract")

    def _validate_source_intent_equivalence(self) -> None:
        """Require materialized data channels to equal the normalized source intent."""

        source = self.source_geometry_intent
        comparisons = (
            ("face groups", self.face_groups, source.face_groups),
            ("sharp edges", self.sharp_edges, source.sharp_edges),
            ("UV seams", self.uv_seams, source.uv_seams),
            ("edge creases", self.edge_creases, source.edge_creases),
            ("bevel weights", self.bevel_weights, source.bevel_weights),
        )
        for label, current, intended in comparisons:
            if current != intended:
                raise ValueError(f"materialized {label} differ from source geometry intent")
        if self.smoothing_policy != source.smoothing_policy:
            raise ValueError("materialized smoothing differs from source geometry intent")
        if self.weighted_normal_intent != source.weighted_normal_intent:
            raise ValueError("weighted-normal intent differs from source geometry intent")
        if self.subdivision_intent != source.subdivision_intent:
            raise ValueError("subdivision intent differs from source geometry intent")

    def assert_compilable(self) -> None:
        """Reject a structurally valid payload that still carries an error finding."""

        errors = [item.code for item in self.findings if item.severity == "error"]
        if errors:
            raise ValueError(f"MeshPayload 0.2 has blocking findings: {sorted(errors)}")
        rejected = [
            item.effect
            for item in self.modifier_materialization_policy
            if item.disposition == "reject"
        ]
        if rejected:
            raise ValueError(
                f"MeshPayload 0.2 has rejected modifier effects: {sorted(rejected)}"
            )


def normalized_source_intent_sha256(payload: dict[str, object]) -> str:
    """Hash normalized source-intent fields before constructing the strict model."""

    return canonical_json_sha256(payload)
