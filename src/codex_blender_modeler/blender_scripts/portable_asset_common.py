from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one required JSON object and reject non-object top-level values."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one deterministic UTF-8 JSON report after creating its parent directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest without loading the complete file into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_path(path: Path, root: Path) -> str:
    """Serialize a path relative to a declared package root and reject escape paths."""

    resolved_path = path.expanduser().resolve()
    resolved_root = root.expanduser().resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Path is outside the portable root: {resolved_path}") from exc


def package_dependency_path(raw: str, root: Path) -> tuple[str, Path | None]:
    """Classify and resolve one Blender image path against an immutable package root."""

    if not raw or "\x00" in raw:
        return "invalid", None
    resolved_root = root.expanduser().resolve()
    normalized = raw.replace("\\", "/")
    windows_path = PureWindowsPath(raw)
    if raw.startswith("\\\\"):
        return "absolute", None
    if normalized.startswith("//"):
        relative_text = normalized[2:]
    elif (
        PurePosixPath(normalized).is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ":" in normalized
    ):
        candidate = Path(raw).expanduser().resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            return "absolute", candidate
        return "package_absolute", candidate
    else:
        relative_text = normalized
    segments = relative_text.split("/")
    if not relative_text or any(part in {"", "."} for part in segments):
        return "invalid", None
    candidate = (resolved_root / PurePosixPath(relative_text)).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        return "outside", candidate
    return "portable", candidate


def rounded(values: Iterable[float], digits: int = 6) -> list[float]:
    """Return a stable rounded float list for machine-readable Blender inventories."""

    return [round(float(value), digits) for value in values]


def is_finite_vector(values: Iterable[float]) -> bool:
    """Return whether every coordinate in a Blender vector is finite."""

    return all(math.isfinite(float(value)) for value in values)


def world_bbox(obj: Any) -> tuple[list[float], list[float]]:
    """Return one object's rounded world-space axis-aligned bounds."""

    from mathutils import Vector  # type: ignore

    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = [min(float(corner[axis]) for corner in corners) for axis in range(3)]
    maximum = [max(float(corner[axis]) for corner in corners) for axis in range(3)]
    return rounded(minimum), rounded(maximum)


def material_ids(obj: Any) -> list[str]:
    """Return stable material IDs from slots, falling back to material datablock names."""

    result: list[str] = []
    for slot in obj.material_slots:
        material = slot.material
        if material is None:
            continue
        result.append(str(material.get("cbm_id", material.name)))
    return result


def _polygon_edge_counts(mesh: Any) -> Counter[tuple[int, int]]:
    """Count face incidence for each undirected mesh edge using polygon loops."""

    counts: Counter[tuple[int, int]] = Counter()
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        for index, first in enumerate(vertices):
            second = vertices[(index + 1) % len(vertices)]
            counts[tuple(sorted((int(first), int(second))))] += 1
    return counts


def _uv_face_area(mesh: Any, polygon: Any, layer: Any) -> float:
    """Measure one polygon's UV area by fan triangulation in loop order."""

    coordinates = [layer.data[index].uv for index in polygon.loop_indices]
    if len(coordinates) < 3:
        return 0.0
    origin = coordinates[0]
    area = 0.0
    for index in range(1, len(coordinates) - 1):
        first = coordinates[index] - origin
        second = coordinates[index + 1] - origin
        area += abs(float(first.x * second.y - first.y * second.x)) * 0.5
    return area


def _uv_layer_metrics(mesh: Any, layer: Any) -> dict[str, Any]:
    """Summarize UV coordinates and bind each loop value to its mesh vertex position."""

    coordinates = [(float(loop.uv.x), float(loop.uv.y)) for loop in layer.data]
    finite = [item for item in coordinates if all(math.isfinite(value) for value in item)]
    non_finite_count = len(coordinates) - len(finite)
    bounds = None
    fingerprint = None
    vertex_uv_binding_fingerprint = None
    if finite:
        bounds = {
            "min": rounded(
                [min(item[0] for item in finite), min(item[1] for item in finite)]
            ),
            "max": rounded(
                [max(item[0] for item in finite), max(item[1] for item in finite)]
            ),
        }
        stable_coordinates = sorted(
            (round(first, 6), round(second, 6)) for first, second in finite
        )
        fingerprint = hashlib.sha256(
            json.dumps(stable_coordinates, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    vertex_uv_bindings: list[tuple[float, float, float, float, float]] = []
    for loop_index, loop in enumerate(mesh.loops):
        vertex = mesh.vertices[int(loop.vertex_index)].co
        uv = layer.data[loop_index].uv
        values = (
            float(vertex.x),
            float(vertex.y),
            float(vertex.z),
            float(uv.x),
            float(uv.y),
        )
        if all(math.isfinite(value) for value in values):
            vertex_uv_bindings.append(tuple(round(value, 6) for value in values))
    if len(vertex_uv_bindings) == len(mesh.loops):
        vertex_uv_binding_fingerprint = hashlib.sha256(
            json.dumps(
                sorted(vertex_uv_bindings), separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
    face_areas = [_uv_face_area(mesh, polygon, layer) for polygon in mesh.polygons]
    finite_face_areas = [value for value in face_areas if math.isfinite(value)]
    total_face_area = (
        round(math.fsum(finite_face_areas), 9)
        if len(finite_face_areas) == len(face_areas)
        else None
    )
    return {
        "coordinate_count": len(coordinates),
        "non_finite_coordinate_count": non_finite_count,
        "coordinate_bounds": bounds,
        "coordinate_fingerprint": fingerprint,
        "vertex_uv_binding_fingerprint": vertex_uv_binding_fingerprint,
        "total_face_area": total_face_area,
    }


def inspect_mesh_topology_data(
    mesh: Any,
    matrix_world: Any,
    area_epsilon: float = 1e-12,
) -> dict[str, Any]:
    """Inspect one mesh datablock with the supplied world transform."""

    incidence = _polygon_edge_counts(mesh)
    face_edge_keys = set(incidence)
    mesh_edge_keys = {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))) for edge in mesh.edges
    }
    referenced_vertices = {index for edge in mesh.edges for index in edge.vertices}
    non_finite_vertices = [
        int(vertex.index) for vertex in mesh.vertices if not is_finite_vector(vertex.co)
    ]
    degenerate_faces = [
        int(polygon.index)
        for polygon in mesh.polygons
        if (not math.isfinite(float(polygon.area))) or float(polygon.area) <= area_epsilon
    ]
    invalid_normal_faces = [
        int(polygon.index)
        for polygon in mesh.polygons
        if (not is_finite_vector(polygon.normal)) or float(polygon.normal.length) <= area_epsilon
    ]
    boundary_edges = sorted(key for key, count in incidence.items() if count == 1)
    overused_edges = sorted(key for key, count in incidence.items() if count > 2)
    loose_edges = sorted(mesh_edge_keys - face_edge_keys)
    loose_vertices = sorted(
        int(vertex.index) for vertex in mesh.vertices if vertex.index not in referenced_vertices
    )

    uv_layers = []
    for layer in mesh.uv_layers:
        degenerate_uv_faces = [
            int(polygon.index)
            for polygon in mesh.polygons
            if _uv_face_area(mesh, polygon, layer) <= area_epsilon
        ]
        uv_layers.append(
            {
                "name": layer.name,
                "active_render": bool(layer.active_render),
                "loop_count": len(layer.data),
                "degenerate_face_count": len(degenerate_uv_faces),
                "degenerate_faces": degenerate_uv_faces[:100],
                **_uv_layer_metrics(mesh, layer),
            }
        )

    triangle_count = sum(max(0, len(polygon.vertices) - 2) for polygon in mesh.polygons)
    determinant = float(matrix_world.to_3x3().determinant())
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "polygons": len(mesh.polygons),
        "triangles_estimated": triangle_count,
        "non_finite_vertex_count": len(non_finite_vertices),
        "non_finite_vertices": non_finite_vertices[:100],
        "degenerate_face_count": len(degenerate_faces),
        "degenerate_faces": degenerate_faces[:100],
        "invalid_normal_face_count": len(invalid_normal_faces),
        "invalid_normal_faces": invalid_normal_faces[:100],
        "boundary_edge_count": len(boundary_edges),
        "overused_edge_count": len(overused_edges),
        "loose_edge_count": len(loose_edges),
        "loose_vertex_count": len(loose_vertices),
        "manifold_closed": not boundary_edges and not overused_edges and not loose_edges,
        "negative_determinant": determinant < 0.0,
        "matrix_determinant": round(determinant, 9),
        "uv_layers": uv_layers,
    }


def inspect_mesh_topology(obj: Any, area_epsilon: float = 1e-12) -> dict[str, Any]:
    """Inspect deterministic topology, finite coordinates, normals, and UV coverage."""

    return inspect_mesh_topology_data(obj.data, obj.matrix_world, area_epsilon)


def object_inventory(obj: Any, include_topology: bool = True) -> dict[str, Any]:
    """Build a portable object record with semantic, material, transform, and mesh data."""

    bbox_min, bbox_max = world_bbox(obj)
    record: dict[str, Any] = {
        "name": obj.name,
        "type": obj.type,
        "semantic_id": obj.get("cbm_id"),
        "instance_index": obj.get("cbm_instance_index"),
        "asset_role": obj.get("cbm_asset_role", "authoring"),
        "lod_level": obj.get("cbm_lod_level"),
        "collider_strategy": obj.get("cbm_collider_strategy"),
        "location": rounded(obj.location),
        "rotation_euler": rounded(obj.rotation_euler),
        "scale": rounded(obj.scale),
        "bbox_world": {"min": bbox_min, "max": bbox_max},
        "dimensions": rounded(obj.dimensions),
        "material_ids": material_ids(obj),
        "custom_properties": {
            key: obj[key]
            for key in sorted(obj.keys())
            if str(key).startswith("cbm_")
            and isinstance(obj[key], (str, int, float, bool))
        },
    }
    if include_topology and obj.type == "MESH":
        record["topology"] = inspect_mesh_topology(obj)
    return record


def operator_kwargs(operator: Any, candidates: dict[str, Any]) -> dict[str, Any]:
    """Feature-probe a Blender operator and keep only arguments exposed at runtime."""

    try:
        identifiers = {prop.identifier for prop in operator.get_rna_type().properties}
    except (AttributeError, RuntimeError):
        return candidates
    return {key: value for key, value in candidates.items() if key in identifiers}


def scene_source_provenance(scene: Any) -> dict[str, Any]:
    """Extract bounded canonical build provenance from scene custom properties."""

    embedded: dict[str, Any] = {}
    raw_embedded = scene.get("cbm_build_provenance")
    if isinstance(raw_embedded, str):
        try:
            parsed = json.loads(raw_embedded)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            embedded = parsed
    build_fingerprint = scene.get("cbm_material_build_fingerprint") or embedded.get(
        "fingerprint"
    )
    return {
        "job_id": scene.get("cbm_job_id"),
        "scene_spec_version": scene.get("cbm_schema_version"),
        "scene_spec_sha256": scene.get("cbm_scene_spec_sha256"),
        "camera_fingerprint": scene.get("cbm_camera_fingerprint"),
        "build_fingerprint": build_fingerprint,
        "material_build_fingerprint": scene.get("cbm_material_build_fingerprint"),
        "embedded_build_provenance": embedded,
    }
