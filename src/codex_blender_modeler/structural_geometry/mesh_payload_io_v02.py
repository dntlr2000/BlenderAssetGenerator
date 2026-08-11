"""Version-dispatched MeshPayload I/O without changing the legacy v1 builder path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .mesh_payload_v02 import MeshPayloadV02
from .models import StructuralMeshPayload


class LegacyVertexUvMeshPayload(BaseModel):
    """Describe the historical unversioned custom-mesh JSON accepted by the v1 builder."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False, strict=True)

    vertices: list[tuple[float, float, float]] = Field(min_length=3)
    faces: list[list[int]] = Field(min_length=1)
    vertex_uvs: list[tuple[float, float]] | None = None

    @model_validator(mode="after")
    def validate_legacy_mesh(self) -> LegacyVertexUvMeshPayload:
        """Reject invalid indices while preserving the historical per-vertex UV dialect."""

        for face_index, face in enumerate(self.faces):
            if len(face) < 3 or len(set(face)) < 3:
                raise ValueError(f"legacy face {face_index} is degenerate")
            if any(index < 0 or index >= len(self.vertices) for index in face):
                raise ValueError(f"legacy face {face_index} references an invalid vertex")
        if self.vertex_uvs is not None and len(self.vertex_uvs) != len(self.vertices):
            raise ValueError("legacy vertex_uvs must match vertex count")
        return self


CompatibleMeshPayload = StructuralMeshPayload | MeshPayloadV02 | LegacyVertexUvMeshPayload


def file_sha256(path: Path) -> str:
    """Return the exact SHA-256 of one file without normalizing its representation."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_payload(value: Path | str | bytes | dict[str, Any]) -> dict[str, Any]:
    """Read one JSON payload from an explicit object, bytes, text, or file path."""

    if isinstance(value, dict):
        return value
    if isinstance(value, Path):
        return json.loads(value.read_text(encoding="utf-8"))
    if isinstance(value, bytes):
        return json.loads(value.decode("utf-8"))
    if value.lstrip().startswith("{"):
        return json.loads(value)
    return json.loads(Path(value).read_text(encoding="utf-8"))


def load_mesh_payload_v02(
    value: Path | str | bytes | dict[str, Any],
) -> MeshPayloadV02:
    """Strictly load only a MeshPayload 0.2 representation."""

    return MeshPayloadV02.model_validate_json(json.dumps(_read_payload(value)))


def load_compatible_mesh_payload(
    value: Path | str | bytes | dict[str, Any],
) -> CompatibleMeshPayload:
    """Dispatch 0.2, existing 0.1, and unversioned vertex-UV payloads explicitly."""

    raw = _read_payload(value)
    version = raw.get("schema_version")
    if version == "0.2.0":
        return MeshPayloadV02.model_validate_json(json.dumps(raw))
    if version == "0.1.0":
        return StructuralMeshPayload.model_validate_json(json.dumps(raw))
    if version is None:
        return LegacyVertexUvMeshPayload.model_validate_json(json.dumps(raw))
    raise ValueError(f"unsupported mesh payload schema_version: {version!r}")


def verify_mesh_payload_v02_source_hashes(
    payload: MeshPayloadV02,
    *,
    job_root: Path,
) -> None:
    """Re-hash every contained transitive source and reject missing, stale, or escaped files."""

    root = job_root.resolve()
    for artifact in payload.source_hashes:
        candidate = (root / Path(*artifact.path.split("/"))).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"source artifact escapes job root: {artifact.path}") from exc
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        if file_sha256(candidate) != artifact.sha256:
            raise ValueError(f"source artifact hash is stale: {artifact.path}")
