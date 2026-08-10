"""Strict contracts for companion mesh-level assembly evidence."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

SCHEMA_VERSION = "0.1.0"
Vec3 = tuple[float, float, float]
Triangle = tuple[int, int, int]


class AssemblyStrictModel(BaseModel):
    """Reject undeclared fields and non-finite numbers in assembly contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class AssemblyArtifact(AssemblyStrictModel):
    """Bind one assembly input or result to a contained path and exact digest."""

    role: Literal[
        "scene_spec",
        "modeling_plan",
        "blend",
        "mesh_snapshot",
        "assembly_request",
        "broad_phase",
        "narrow_phase",
        "other",
    ]
    path: RelativePath
    sha256: Sha256


class AssemblyProvenance(AssemblyStrictModel):
    """Freeze the job, workflow, dispatch, contract, and evaluated source inputs."""

    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    project_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    assembly_contract_version: Literal["0.1.0"] = SCHEMA_VERSION
    inputs: list[AssemblyArtifact] = Field(min_length=3)

    @model_validator(mode="after")
    def validate_inputs(self) -> AssemblyProvenance:
        """Require unique input paths and canonical geometry/build roles."""

        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("assembly provenance paths must be unique")
        roles = {item.role for item in self.inputs}
        if not {"scene_spec", "modeling_plan", "blend"}.issubset(roles):
            raise ValueError(
                "assembly provenance requires scene_spec, modeling_plan, and blend"
            )
        return self


class AABB(AssemblyStrictModel):
    """Represent one finite, non-inverted axis-aligned meter-space bound."""

    minimum: Vec3
    maximum: Vec3

    @model_validator(mode="after")
    def validate_bounds(self) -> AABB:
        """Reject non-finite, inverted, or point-only bounds while allowing planes."""

        if not all(math.isfinite(value) for value in (*self.minimum, *self.maximum)):
            raise ValueError("AABB coordinates must be finite")
        extents = tuple(
            high - low for low, high in zip(self.minimum, self.maximum, strict=True)
        )
        if any(value < 0 for value in extents) or not any(value > 0 for value in extents):
            raise ValueError("AABB must be non-inverted with at least one positive extent")
        return self


class TriangleMeshEvidence(AssemblyStrictModel):
    """Store one evaluated triangle mesh in a form accepted by BVH backends."""

    object_id: str = Field(min_length=1, max_length=128)
    snapshot: AssemblyArtifact
    bounds: AABB
    vertices_m: list[Vec3]
    triangles: list[Triangle]

    @model_validator(mode="after")
    def validate_mesh(self) -> TriangleMeshEvidence:
        """Require finite vertices and valid, non-repeating triangle indices."""

        if self.snapshot.role != "mesh_snapshot":
            raise ValueError("mesh evidence snapshot must use role=mesh_snapshot")
        if not all(math.isfinite(value) for vertex in self.vertices_m for value in vertex):
            raise ValueError("mesh vertices must be finite")
        vertex_count = len(self.vertices_m)
        for triangle in self.triangles:
            if len(set(triangle)) != 3:
                raise ValueError("triangle indices must be distinct")
            if min(triangle) < 0 or max(triangle) >= vertex_count:
                raise ValueError("triangle index is outside the vertex array")
        return self


class BroadPhasePair(AssemblyStrictModel):
    """Record deterministic AABB overlap or separation for one semantic pair."""

    subject_id: str
    reference_id: str
    status: Literal["overlap_candidate", "separated"]
    axis_gap_m: Vec3
    overlap_extent_m: Vec3


class BVHNarrowObservation(AssemblyStrictModel):
    """Capture bounded nearest-distance and optional evaluated BVH overlap evidence."""

    subject_id: str
    reference_id: str
    status: Literal["available", "empty", "evaluation_failure"]
    backend: Literal["blender_bvh", "pure_python_bounded"]
    overlap_triangle_pair_count: int | None = Field(default=None, ge=0)
    minimum_distance_m: float | None = Field(default=None, ge=0)
    penetration_depth_m: float | None = Field(default=None, ge=0)
    sampled_point_count: int = Field(default=0, ge=0)
    bounded_sample_limit: int = Field(ge=1, le=8192)
    error: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> BVHNarrowObservation:
        """Prevent empty or failed evaluation from masquerading as usable evidence."""

        values = (
            self.overlap_triangle_pair_count,
            self.minimum_distance_m,
            self.penetration_depth_m,
        )
        if self.status == "available":
            if self.minimum_distance_m is None or self.error is not None:
                raise ValueError("available narrow evidence requires distance and no error")
        elif any(value is not None for value in values) or self.sampled_point_count != 0:
            raise ValueError("unavailable narrow evidence cannot contain measured values")
        if self.status == "evaluation_failure" and not self.error:
            raise ValueError("evaluation failure requires an error summary")
        if self.status != "evaluation_failure" and self.error is not None:
            raise ValueError("only evaluation_failure may contain an error")
        return self


class SemanticAssemblyRelation(AssemblyStrictModel):
    """Declare one semantic assembly expectation and its supported tolerance."""

    relation_id: str = Field(min_length=1, max_length=128)
    kind: Literal[
        "required_contact",
        "supported_insertion_depth",
        "supported_clearance",
        "bilateral_symmetry",
        "center_plane",
    ]
    subject_id: str
    reference_id: str
    peer_id: str | None = None
    required: bool = True
    minimum_m: float | None = Field(default=None, ge=0)
    maximum_m: float | None = Field(default=None, ge=0)
    tolerance_m: float = Field(default=0.001, ge=0)
    measured_value_m: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_relation(self) -> SemanticAssemblyRelation:
        """Reject ambiguous identities and invalid relation-specific bounds."""

        if self.subject_id == self.reference_id:
            raise ValueError("assembly relation subject and reference must differ")
        if self.kind == "bilateral_symmetry" and not self.peer_id:
            raise ValueError("bilateral symmetry requires peer_id")
        if self.kind != "bilateral_symmetry" and self.peer_id is not None:
            raise ValueError("peer_id is valid only for bilateral symmetry")
        if self.maximum_m is not None and self.minimum_m is not None:
            if self.maximum_m < self.minimum_m:
                raise ValueError("assembly relation maximum cannot be below minimum")
        if self.kind == "required_contact" and self.maximum_m is None:
            raise ValueError("required contact requires maximum_m contact distance")
        return self


class AssemblyCompanionRequest(AssemblyStrictModel):
    """Freeze the evaluated meshes, semantic relations, and bounded query budget."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    request_id: PortableId
    provenance: AssemblyProvenance
    meshes: list[TriangleMeshEvidence] = Field(min_length=1)
    semantic_relations: list[SemanticAssemblyRelation] = Field(default_factory=list)
    narrow_observations: list[BVHNarrowObservation] = Field(default_factory=list)
    maximum_distance_samples: int = Field(default=512, ge=1, le=8192)
    maximum_triangle_pair_tests: int = Field(default=4096, ge=1, le=65536)

    @model_validator(mode="after")
    def validate_request(self) -> AssemblyCompanionRequest:
        """Require unique mesh, relation, and unordered observation identities."""

        mesh_ids = [item.object_id for item in self.meshes]
        if len(mesh_ids) != len(set(mesh_ids)):
            raise ValueError("assembly mesh object IDs must be unique")
        relation_ids = [item.relation_id for item in self.semantic_relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("semantic assembly relation IDs must be unique")
        known = set(mesh_ids)
        for relation in self.semantic_relations:
            ids = {relation.subject_id, relation.reference_id}
            if relation.peer_id is not None:
                ids.add(relation.peer_id)
            if not ids.issubset(known):
                raise ValueError("semantic relation references an unknown mesh object")
        pairs = [
            tuple(sorted((item.subject_id, item.reference_id)))
            for item in self.narrow_observations
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError("narrow observation pairs must be unique")
        return self


class AssemblyFinding(AssemblyStrictModel):
    """Report one broad, narrow, or semantic assembly observation."""

    finding_id: str
    phase: Literal["broad", "narrow", "semantic"]
    severity: Literal["hard_failure", "warning", "info", "unscorable"]
    code: str = Field(pattern=r"^[A-Z0-9_]{3,96}$")
    subject_id: str | None = None
    reference_id: str | None = None
    relation_id: str | None = None
    measured_value_m: float | None = None
    limit_value_m: float | None = None
    message: str


class AssemblyCompanionReport(AssemblyStrictModel):
    """Summarize companion assembly evidence without claiming mechanical truth."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    report_id: PortableId
    provenance: AssemblyProvenance
    request: AssemblyArtifact
    status: Literal["passed", "warning", "failed", "unscorable"]
    ok: bool
    broad_pairs: list[BroadPhasePair]
    narrow_observations: list[BVHNarrowObservation]
    findings: list[AssemblyFinding]
    hard_failures: int = Field(ge=0)
    warnings: int = Field(ge=0)
    unscorable: int = Field(ge=0)
    limitations: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_summary(self) -> AssemblyCompanionReport:
        """Keep summary counters and conservative status aligned with findings."""

        counts = {
            severity: sum(item.severity == severity for item in self.findings)
            for severity in ("hard_failure", "warning", "unscorable")
        }
        if (self.hard_failures, self.warnings, self.unscorable) != (
            counts["hard_failure"],
            counts["warning"],
            counts["unscorable"],
        ):
            raise ValueError("assembly report counters do not match findings")
        expected = (
            "failed"
            if self.hard_failures
            else "unscorable"
            if self.unscorable
            else "warning"
            if self.warnings
            else "passed"
        )
        if self.status != expected or self.ok != (expected == "passed"):
            raise ValueError("assembly report status or ok value is inconsistent")
        return self
