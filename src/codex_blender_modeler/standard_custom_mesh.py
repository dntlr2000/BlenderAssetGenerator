"""Strict Standard custom-mesh payloads that preserve approved polygon-corner UVs."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

STANDARD_CUSTOM_MESH_VERSION = "0.1.0"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
STABLE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
JOB_RELATIVE_SCHEMA_PATTERN = (
    r"^(?!/)(?![A-Za-z]:)(?!.*:)(?!.*(?:^|/)\.\.(?:/|$))(?!.*\\)(?!.*//)"
    r"[^\u0000]+$"
)

Vec2: TypeAlias = Annotated[list[float], Field(min_length=2, max_length=2)]
Vec3: TypeAlias = Annotated[list[float], Field(min_length=3, max_length=3)]


def _validate_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by the owning job workspace."""

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


class StandardCustomMeshStrictModel(BaseModel):
    """Reject unknown fields, coercion, and non-finite Standard payload values."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


def canonical_json_sha256(value: object) -> str:
    """Hash one JSON-compatible value using the repository canonical encoding."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def ordered_corner_topology_sha256(faces: list[list[int]]) -> str:
    """Hash exact polygon order, vertex order, and cumulative corner positions."""

    loop_start = 0
    polygons: list[dict[str, object]] = []
    for polygon_index, face in enumerate(faces):
        polygons.append(
            {
                "polygon_index": polygon_index,
                "loop_start": loop_start,
                "loop_total": len(face),
                "vertex_indices": face,
            }
        )
        loop_start += len(face)
    return canonical_json_sha256(
        {
            "polygon_count": len(faces),
            "ordered_corner_count": loop_start,
            "polygons": polygons,
        }
    )


def uv_coordinate_fingerprint(loop_uvs: list[Vec2]) -> str:
    """Mirror the inventory fingerprint over sorted six-decimal loop coordinates."""

    stable_coordinates = sorted(
        (round(float(first), 6), round(float(second), 6))
        for first, second in loop_uvs
    )
    return hashlib.sha256(
        json.dumps(stable_coordinates, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class StandardCustomMeshPayload(StandardCustomMeshStrictModel):
    """Carry exact Standard vertices, faces, and approved loop UVs without AQ authority."""

    payload_kind: Literal["standard_custom_mesh"] = "standard_custom_mesh"
    schema_version: Literal["0.1.0"] = STANDARD_CUSTOM_MESH_VERSION
    job_id: StableId
    object_id: StableId
    source_scene_spec_path: JobRelativePath
    source_scene_spec_sha256: Sha256
    source_blend_path: JobRelativePath
    source_blend_sha256: Sha256
    vertices: list[Vec3] = Field(min_length=3)
    faces: list[list[int]] = Field(min_length=1)
    loop_uvs: list[Vec2] = Field(min_length=3)
    uv_set: StableId
    source_coordinate_fingerprint: Sha256
    source_vertex_uv_binding_fingerprint: Sha256
    ordered_corner_topology_sha256: Sha256

    @model_validator(mode="after")
    def validate_mesh_and_uv_identity(self) -> StandardCustomMeshPayload:
        """Require valid ordered topology and fingerprints for every polygon corner."""

        vertex_count = len(self.vertices)
        ordered_corner_count = 0
        for face_index, face in enumerate(self.faces):
            if len(face) < 3 or len(set(face)) != len(face):
                raise ValueError(f"mesh face {face_index} is degenerate")
            if any(index < 0 or index >= vertex_count for index in face):
                raise ValueError(f"mesh face {face_index} references an invalid vertex")
            ordered_corner_count += len(face)
        if len(self.loop_uvs) != ordered_corner_count:
            raise ValueError("loop_uvs must contain one pair per ordered polygon corner")
        expected_topology = ordered_corner_topology_sha256(self.faces)
        if self.ordered_corner_topology_sha256 != expected_topology:
            raise ValueError("ordered_corner_topology_sha256 does not match faces")
        expected_coordinates = uv_coordinate_fingerprint(self.loop_uvs)
        if self.source_coordinate_fingerprint != expected_coordinates:
            raise ValueError("source_coordinate_fingerprint does not match loop_uvs")
        return self
