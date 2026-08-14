from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Any

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUIRED_FIELDS = {
    "payload_kind",
    "schema_version",
    "job_id",
    "object_id",
    "source_scene_spec_path",
    "source_scene_spec_sha256",
    "source_blend_path",
    "source_blend_sha256",
    "vertices",
    "faces",
    "loop_uvs",
    "uv_set",
    "source_coordinate_fingerprint",
    "source_vertex_uv_binding_fingerprint",
    "ordered_corner_topology_sha256",
}


def _canonical_json_sha256(value: object) -> str:
    """Hash one runtime JSON value using the host canonical encoding."""

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
    return _canonical_json_sha256(
        {
            "polygon_count": len(faces),
            "ordered_corner_count": loop_start,
            "polygons": polygons,
        }
    )


def uv_coordinate_fingerprint(loop_uvs: list[list[float]]) -> str:
    """Mirror the inventory fingerprint over sorted six-decimal loop coordinates."""

    stable_coordinates = sorted(
        (round(float(first), 6), round(float(second), 6))
        for first, second in loop_uvs
    )
    return hashlib.sha256(
        json.dumps(stable_coordinates, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_stable_id(value: object, label: str) -> str:
    """Require one exact nonempty Standard job, object, or UV identity."""

    if not isinstance(value, str) or _STABLE_ID_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"Standard custom_mesh {label} is invalid")
    return value


def _require_sha256(value: object, label: str) -> str:
    """Require one lowercase exact SHA-256 value."""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"Standard custom_mesh {label} is invalid")
    return value


def _require_relative_path(value: object, label: str) -> str:
    """Require one normalized POSIX dependency path with no escape segment."""

    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
        or ":" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or str(PurePosixPath(value)) != value
    ):
        raise RuntimeError(f"Standard custom_mesh {label} is not job-relative")
    return value


def _require_vector_array(
    value: object,
    *,
    label: str,
    width: int,
    minimum_count: int,
) -> list[list[float]]:
    """Require one finite, fixed-width numeric vector array without coercion."""

    if not isinstance(value, list) or len(value) < minimum_count:
        raise RuntimeError(f"Standard custom_mesh {label} count is invalid")
    result: list[list[float]] = []
    for index, item in enumerate(value):
        if not isinstance(item, list) or len(item) != width:
            raise RuntimeError(
                f"Standard custom_mesh {label}[{index}] width is invalid"
            )
        if any(
            isinstance(component, bool)
            or not isinstance(component, (int, float))
            or not math.isfinite(float(component))
            for component in item
        ):
            raise RuntimeError(
                f"Standard custom_mesh {label}[{index}] must be finite numeric data"
            )
        result.append([float(component) for component in item])
    return result


def validate_standard_custom_mesh_payload(payload: object) -> dict[str, Any]:
    """Validate the exact Standard loop-UV dialect without host-only dependencies."""

    if not isinstance(payload, dict) or set(payload) != _REQUIRED_FIELDS:
        raise RuntimeError("Standard custom_mesh fields are missing or undeclared")
    if (
        payload.get("payload_kind") != "standard_custom_mesh"
        or payload.get("schema_version") != "0.1.0"
    ):
        raise RuntimeError("Standard custom_mesh kind or version is unsupported")
    _require_stable_id(payload.get("job_id"), "job_id")
    _require_stable_id(payload.get("object_id"), "object_id")
    _require_stable_id(payload.get("uv_set"), "uv_set")
    _require_relative_path(payload.get("source_scene_spec_path"), "source SceneSpec")
    _require_relative_path(payload.get("source_blend_path"), "source Blend")
    for label in (
        "source_scene_spec_sha256",
        "source_blend_sha256",
        "source_coordinate_fingerprint",
        "source_vertex_uv_binding_fingerprint",
        "ordered_corner_topology_sha256",
    ):
        _require_sha256(payload.get(label), label)
    vertices = _require_vector_array(
        payload.get("vertices"),
        label="vertices",
        width=3,
        minimum_count=3,
    )
    loop_uvs = _require_vector_array(
        payload.get("loop_uvs"),
        label="loop_uvs",
        width=2,
        minimum_count=3,
    )
    raw_faces = payload.get("faces")
    if not isinstance(raw_faces, list) or not raw_faces:
        raise RuntimeError("Standard custom_mesh faces count is invalid")
    faces: list[list[int]] = []
    ordered_corner_count = 0
    for face_index, face in enumerate(raw_faces):
        if (
            not isinstance(face, list)
            or len(face) < 3
            or len(set(face)) != len(face)
            or any(
                type(index) is not int or index < 0 or index >= len(vertices)
                for index in face
            )
        ):
            raise RuntimeError(f"Standard custom_mesh face {face_index} is invalid")
        faces.append(list(face))
        ordered_corner_count += len(face)
    if len(loop_uvs) != ordered_corner_count:
        raise RuntimeError(
            "Standard custom_mesh loop_uvs must match all ordered polygon corners"
        )
    if payload["ordered_corner_topology_sha256"] != ordered_corner_topology_sha256(
        faces
    ):
        raise RuntimeError("Standard custom_mesh ordered topology hash is stale")
    if payload["source_coordinate_fingerprint"] != uv_coordinate_fingerprint(loop_uvs):
        raise RuntimeError("Standard custom_mesh coordinate fingerprint is stale")
    return payload
