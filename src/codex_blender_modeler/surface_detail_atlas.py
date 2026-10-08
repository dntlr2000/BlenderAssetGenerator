"""Bounded shared-atlas proof using declared cells and actual polygon-corner UVs.

This is not a texture-appearance or mip-map guarantee. Shared materials are eligible
only for explicit material_atlas decisions covering every consumer, with disjoint
cells and a two-source-texel inset. Each complete UV footprint must be inside its
own convex rectangular cell, so interpolation cannot visit another object's cell.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path, PurePosixPath
from typing import Any


def atlas_image_dimension_errors(manifest: dict[str, Any], manifest_path: Path) -> list[str]:
    """Verify actual bound raster dimensions before using declared texel padding."""

    from PIL import Image

    expected = tuple(manifest["resolution"])
    channels = {name for binding in manifest["surface_detail_bindings"]
                for name in binding["channels"]}
    errors: list[str] = []
    for name in sorted(channels):
        channel = manifest["channels"].get(name, {})
        value = channel.get("path")
        if channel.get("source") != "image" or not isinstance(value, str):
            errors.append(f"{name}: shared atlas requires an actual image channel")
            continue
        parts = value.split("/")
        if (not value or "\\" in value or ":" in value or PurePosixPath(value).is_absolute()
                or any(part in {"", ".", ".."} for part in parts)):
            errors.append(f"{name}: atlas image must be a contained nonlinked relative path")
            continue
        path = manifest_path.parent
        linked = False
        for part in parts:
            path = path / part
            linked = linked or path.is_symlink() or (
                hasattr(path, "is_junction") and path.is_junction()
            )
        if linked:
            errors.append(f"{name}: atlas image cannot use links or junctions")
            continue
        try:
            with Image.open(path) as opened:
                if opened.size != expected:
                    errors.append(f"{name}: decoded image dimensions differ from atlas resolution")
        except (OSError, ValueError):
            errors.append(f"{name}: decoded atlas image dimensions are unavailable")
    return errors


def _float32(value: object) -> float:
    """Match Blender mesh/UV storage and reject nonfinite or overflowing scalars."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("mesh/UV coordinates must be numeric")
    try:
        result = struct.unpack(">f", struct.pack(">f", value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError("mesh/UV coordinates exceed float32") from exc
    if not math.isfinite(result):
        raise ValueError("mesh/UV coordinates must be finite")
    return result


def declared_atlas_uv_metrics(
    root: Path,
    geometry: dict[str, Any],
    *,
    material_id: str,
) -> dict[str, Any]:
    """Recompute current path-backed custom-mesh corner hashes, not stale inventory claims.

        Only the existing explicit vertex-UV, Standard and V02 loop-UV payload dialects are
    supported. Other builders retain the previous shared-material refusal. Native
    inspection separately rechecks the realized source and evaluated UV footprints.
    """

    raw_path = geometry.get("path")
    if geometry.get("kind") != "custom_mesh" or not isinstance(raw_path, str):
        raise ValueError("shared atlas requires a path-backed explicit-UV custom_mesh")
    parts = raw_path.split("/")
    if (
        not raw_path
        or "\\" in raw_path
        or ":" in raw_path
        or PurePosixPath(raw_path).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("shared atlas mesh path must be contained and normalized")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("shared atlas mesh path cannot contain links or junctions")
    path.resolve().relative_to(root.resolve())
    source_text = path.read_text(encoding="utf-8")
    payload = json.loads(source_text)
    if not isinstance(payload, dict):
        raise ValueError("shared atlas mesh payload must be an object")
    version = payload.get("schema_version")
    kind = payload.get("payload_kind")
    if kind == "standard_custom_mesh" and version == "0.1.0":
        from .blender_scripts.standard_custom_mesh_runtime import (
            validate_standard_custom_mesh_payload,
        )

        try:
            payload = validate_standard_custom_mesh_payload(payload)
        except RuntimeError as exc:
            raise ValueError(f"invalid Standard atlas payload: {str(exc)[:240]}") from exc
        if payload["uv_set"] != "UVMap":
            raise ValueError("shared atlas requires the exact UVMap layer")
        loop_uvs = payload["loop_uvs"]
        vertex_uvs = None
    elif kind is None and version == "0.2.0":
        from .structural_geometry.mesh_payload_v02 import MeshPayloadV02

        payload = MeshPayloadV02.model_validate_json(source_text).model_dump(mode="json")
        slots = payload["material_slots"]
        if (
            len(slots) != 1
            or slots[0]["material_id"] != material_id
            or any(value != 0 for value in payload["polygon_material_indices"])
        ):
            raise ValueError("shared atlas requires an unambiguous single material slot")
        loop_uvs = payload["loop_uvs"]
        vertex_uvs = None
    elif kind is None and version in {None, "0.1.0"} and "loop_uvs" not in payload:
        loop_uvs = None
        vertex_uvs = payload.get("vertex_uvs")
    else:
        raise ValueError("shared atlas mesh payload dialect is unsupported")
    vertices = payload.get("vertices")
    faces = payload.get("faces")
    if not isinstance(vertices, list) or not vertices or not isinstance(faces, list) or not faces:
        raise ValueError("shared atlas needs nonempty explicit vertices and faces")
    if loop_uvs is None and (not isinstance(vertex_uvs, list) or len(vertex_uvs) != len(vertices)):
        raise ValueError("shared atlas needs exactly one explicit UV per vertex")
    coordinates: list[tuple[float, float]] = []
    digest = hashlib.sha256()
    digest.update(struct.pack(">Q", len(faces)))
    start = 0
    for polygon_index, face in enumerate(faces):
        if not isinstance(face, list) or len(face) < 3 or len(set(face)) != len(face):
            raise ValueError("shared atlas faces must have distinct valid corners")
        digest.update(struct.pack(">QQQ", polygon_index, start, len(face)))
        for index in face:
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < len(vertices)
            ):
                raise ValueError("shared atlas face index is invalid")
            vertex = vertices[index]
            if loop_uvs is not None and start >= len(loop_uvs):
                raise ValueError("shared atlas loop UV count differs from polygon corners")
            uv = loop_uvs[start] if loop_uvs is not None else vertex_uvs[index]
            if (
                not isinstance(vertex, list)
                or len(vertex) != 3
                or not isinstance(uv, list)
                or len(uv) != 2
            ):
                raise ValueError("shared atlas vertex/UV shape is invalid")
            xyz = tuple(_float32(value) for value in vertex)
            pair = tuple(_float32(value) for value in uv)
            digest.update(struct.pack(">Qddddd", index, *xyz, *pair))
            coordinates.append(pair)
            start += 1
    if loop_uvs is not None and start != len(loop_uvs):
        raise ValueError("shared atlas loop UV count differs from polygon corners")
    return {
        "name": "UVMap",
        "coordinate_count": len(coordinates),
        "non_finite_coordinate_count": 0,
        "vertex_uv_binding_fingerprint": digest.hexdigest(),
        "coordinate_bounds": {
            "min": [min(item[axis] for item in coordinates) for axis in (0, 1)],
            "max": [max(item[axis] for item in coordinates) for axis in (0, 1)],
        },
    }


def shared_atlas_errors(
    *,
    material_id: str,
    material_users: list[str],
    bindings: list[dict[str, Any]],
    strategies: dict[str, str],
    uv_metrics: dict[str, list[dict[str, Any]]],
    resolution: list[int] | tuple[int, int],
    check_fingerprints: bool = True,
    bounds_rounding_uncertainty: float = 0.0,
) -> list[str]:
    """Validate complete, disjoint atlas ownership against actual/current UV occupancy."""

    errors: list[str] = []
    if not math.isfinite(bounds_rounding_uncertainty) or bounds_rounding_uncertainty < 0:
        return ["shared atlas bounds uncertainty must be finite and nonnegative"]
    users = set(material_users)
    if len(users) != len(material_users):
        errors.append("shared atlas material users are ambiguous or duplicated")
    if len(users) < 2:
        return ["shared atlas proof requires multiple distinct material users"]
    if len(resolution) != 2 or any(
        isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in resolution
    ):
        return ["shared atlas texture resolution is invalid"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        parent = str(binding.get("parent_object_id", ""))
        grouped.setdefault(parent, []).append(binding)
        if strategies.get(str(binding.get("detail_id"))) != "material_atlas":
            errors.append("every shared detail must explicitly select material_atlas")
        if binding.get("material_id") != material_id or binding.get("uv_set") != "UVMap":
            errors.append("shared atlas binding has mixed material/UV identity")
    if set(grouped) != users:
        errors.append("shared atlas bindings must cover every material user exactly")
    cells: dict[str, tuple[float, float, float, float]] = {}
    padding = [2.0 / value + bounds_rounding_uncertainty for value in resolution]
    for parent, members in sorted(grouped.items()):
        rectangles = []
        for binding in members:
            placement = binding.get("placement", {})
            rect = placement.get("uv_rect")
            if (
                placement.get("mode") != "uv_rect"
                or not isinstance(rect, (list, tuple))
                or len(rect) != 4
                or any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    or not 0 <= v <= 1
                    for v in rect
                )
            ):
                errors.append(f"{parent}: shared atlas requires finite normalized uv_rect cells")
                continue
            rectangles.append(tuple(float(value) for value in rect))
        if len(rectangles) != len(members) or len(set(rectangles)) != 1:
            errors.append(f"{parent}: all details must use one unambiguous parent cell")
            continue
        rect = rectangles[0]
        cells[parent] = rect
        if any(rect[axis + 2] - rect[axis] <= 2 * padding[axis] for axis in (0, 1)):
            errors.append(f"{parent}: atlas cell is too small for two-texel padding")
        expected = {item.get("uv_layout_sha256") for item in members}
        layers = uv_metrics.get(parent, [])
        if not layers:
            errors.append(f"{parent}: current complete UV occupancy is missing")
        for layer in layers:
            if check_fingerprints and (
                {layer.get("vertex_uv_binding_fingerprint")} != expected or None in expected
            ):
                errors.append(f"{parent}: current polygon-corner UV hash is stale or ambiguous")
            if (
                layer.get("name") != "UVMap"
                or layer.get("non_finite_coordinate_count") != 0
                or not isinstance(layer.get("coordinate_count"), int)
                or layer.get("coordinate_count", 0) < 3
            ):
                errors.append(f"{parent}: complete finite UV occupancy is unavailable")
            bounds = layer.get("coordinate_bounds") or {}
            lo, hi = bounds.get("min", []), bounds.get("max", [])
            if (
                len(lo) != 2
                or len(hi) != 2
                or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in [*lo, *hi]
                )
            ):
                errors.append(f"{parent}: actual UV bounds are unavailable")
            elif any(
                not (rect[a] + padding[a] <= lo[a] <= hi[a] <= rect[a + 2] - padding[a])
                for a in (0, 1)
            ):
                errors.append(f"{parent}: actual UV occupancy escapes its padded atlas cell")
    ordered = sorted(cells)
    for index, first in enumerate(ordered):
        a = cells[first]
        for second in ordered[index + 1 :]:
            b = cells[second]
            if all(min(a[k + 2], b[k + 2]) > max(a[k], b[k]) for k in (0, 1)):
                errors.append(f"{first}/{second}: different material users have overlapping cells")
    return sorted(set(errors))
