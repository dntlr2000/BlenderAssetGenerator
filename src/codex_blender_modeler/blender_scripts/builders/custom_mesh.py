from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

import bpy
from compile_mesh_payload_v02 import (
    _apply_data_intent,
    _apply_modifier_intent,
    _required_payload_shape,
)


def _resolve(path: str, base_dir: Path) -> Path:
    """Resolve one path-backed custom-mesh payload inside the active job context."""

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return _material_binding_override_path(path, base_dir, candidate)


def _apply_vertex_uvs(mesh: bpy.types.Mesh, raw_uvs: object) -> None:
    """Create UVMap from an optional deterministic UV pair stored per mesh vertex."""

    if raw_uvs is None:
        return
    if not isinstance(raw_uvs, list) or len(raw_uvs) != len(mesh.vertices):
        raise RuntimeError(
            "custom_mesh vertex_uvs must contain one UV pair per mesh vertex"
        )
    vertex_uvs: list[tuple[float, float]] = []
    for index, item in enumerate(raw_uvs):
        if not isinstance(item, list) or len(item) != 2:
            raise RuntimeError(
                f"custom_mesh vertex_uvs[{index}] must be a two-value array"
            )
        uv = (float(item[0]), float(item[1]))
        if not all(math.isfinite(value) for value in uv):
            raise RuntimeError(
                f"custom_mesh vertex_uvs[{index}] must contain finite values"
            )
        vertex_uvs.append(uv)
    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = vertex_uvs[vertex_index]


def _sha256_file(path: Path) -> str:
    """Hash one exact contained v2 dependency without normalizing its bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    """Hash one JSON-compatible source map using the host canonical encoding."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _contained_v02_path(raw_path: str, base_dir: Path) -> Path:
    """Resolve one normalized package-relative v2 path inside the active job root."""

    if (
        not raw_path
        or raw_path != raw_path.replace("\\", "/")
        or raw_path.startswith("/")
        or ":" in raw_path
    ):
        raise RuntimeError("MeshPayload 0.2 source path is not job-relative")
    parts = PurePosixPath(raw_path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError("MeshPayload 0.2 source path is not normalized")
    root = base_dir.resolve()
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("MeshPayload 0.2 source path escapes job root") from exc
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _material_binding_override_path(
    raw_scene_path: str,
    base_dir: Path,
    source_path: Path,
) -> Path:
    """Resolve one optional exact material-slot derivative without changing source bytes."""

    manifest_path = base_dir / "analysis" / "material_binding_derivative.json"
    if not manifest_path.is_file():
        return source_path
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("material binding derivative companion is invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "0.1.0"
        or manifest.get("topology_unchanged") is not True
        or manifest.get("canonical_geometry_payload_overwrite") is not False
    ):
        raise RuntimeError("material binding derivative companion is out of scope")
    receipt_path = _contained_v02_path(
        str(manifest.get("source_receipt_path", "")),
        base_dir,
    )
    if _sha256_file(receipt_path) != str(manifest.get("source_receipt_sha256", "")):
        raise RuntimeError("material binding source receipt is stale")
    bindings = manifest.get("bindings")
    if not isinstance(bindings, list):
        raise RuntimeError("material binding derivative entries are invalid")
    matches = [
        item
        for item in bindings
        if isinstance(item, dict) and item.get("scene_payload_path") == raw_scene_path
    ]
    if not matches:
        return source_path
    if len(matches) != 1:
        raise RuntimeError("material binding source path is duplicated")
    binding = matches[0]
    if _sha256_file(source_path) != str(binding.get("source_sha256", "")):
        raise RuntimeError("material binding source payload is stale")
    derivative_path = _contained_v02_path(
        str(binding.get("derivative_path", "")),
        base_dir,
    )
    if _sha256_file(derivative_path) != str(binding.get("derivative_sha256", "")):
        raise RuntimeError("material binding derivative payload is stale")
    return derivative_path


def _verify_v02_payload(
    payload: dict[str, Any],
    *,
    payload_path: Path,
    base_dir: Path,
) -> None:
    """Revalidate fixed v2 shape, material indices, sources, and blocking findings."""

    root = base_dir.resolve()
    try:
        payload_path.resolve().relative_to(root)
    except ValueError as exc:
        raise RuntimeError("MeshPayload 0.2 path escapes job root") from exc
    _required_payload_shape(payload)
    if any(item.get("severity") == "error" for item in payload.get("findings", [])):
        raise RuntimeError("MeshPayload 0.2 has blocking findings")
    slots = payload["material_slots"]
    if not isinstance(slots, list) or not slots:
        raise RuntimeError("MeshPayload 0.2 requires material slots")
    slot_ids = [str(item.get("material_id", "")) for item in slots]
    if (
        [item.get("slot_index") for item in slots] != list(range(len(slots)))
        or any(not value for value in slot_ids)
        or len(slot_ids) != len(set(slot_ids))
    ):
        raise RuntimeError("MeshPayload 0.2 material slots are invalid")
    indices = payload["polygon_material_indices"]
    if len(indices) != len(payload["faces"]) or any(
        type(index) is not int or index < 0 or index >= len(slots) for index in indices
    ):
        raise RuntimeError("MeshPayload 0.2 polygon material indices are invalid")
    sources = payload.get("source_hashes")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("MeshPayload 0.2 requires exact source hashes")
    if payload.get("source_fingerprint_sha256") != _canonical_sha256(sources):
        raise RuntimeError("MeshPayload 0.2 source fingerprint is stale")
    seen_paths: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise RuntimeError("MeshPayload 0.2 source entry is invalid")
        relative_path = str(source.get("path", ""))
        if relative_path in seen_paths:
            raise RuntimeError("MeshPayload 0.2 source paths are duplicated")
        seen_paths.add(relative_path)
        dependency = _contained_v02_path(relative_path, root)
        if _sha256_file(dependency) != str(source.get("sha256", "")):
            raise RuntimeError(f"MeshPayload 0.2 source hash is stale: {relative_path}")


def _build_v02(
    payload: dict[str, Any],
    *,
    payload_path: Path,
    base_dir: Path,
) -> bpy.types.Object:
    """Build one host-authored v2 payload and retain SceneSpec material handoff data."""

    _verify_v02_payload(payload, payload_path=payload_path, base_dir=base_dir)
    mesh = bpy.data.meshes.new("CBM_CustomMeshV02")
    mesh.from_pydata(payload["vertices"], [], payload["faces"])
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("CBM_CustomMeshV02", mesh)
    bpy.context.scene.collection.objects.link(obj)
    _apply_data_intent(obj, payload, materialize_material_slots=False)
    _apply_modifier_intent(obj, payload)
    mesh.update(calc_edges=True)
    obj["cbm_mesh_payload_version"] = "0.2.0"
    obj["cbm_v02_payload_sha256"] = _sha256_file(payload_path)
    obj["cbm_v02_source_fingerprint"] = str(
        payload["source_fingerprint_sha256"]
    )
    obj["cbm_v02_material_ids"] = json.dumps(
        [str(item["material_id"]) for item in payload["material_slots"]],
        separators=(",", ":"),
    )
    obj["cbm_v02_polygon_material_indices"] = json.dumps(
        payload["polygon_material_indices"],
        separators=(",", ":"),
    )
    obj["cbm_v02_smoothing_mode"] = str(payload["smoothing_policy"]["mode"])
    obj["cbm_v02_recreated_effects"] = json.dumps(
        sorted(
            item["effect"]
            for item in payload["modifier_materialization_policy"]
            if item["disposition"] == "recreate_in_compiled_build"
        ),
        separators=(",", ":"),
    )
    return obj


def build(spec: dict, base_dir: Path) -> bpy.types.Object:
    """Build legacy custom meshes unchanged or explicitly dispatch MeshPayload 0.2."""

    vertex_uvs = None
    if spec.get("path"):
        payload_path = _resolve(spec["path"], base_dir)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        version = payload.get("schema_version")
        if version == "0.2.0":
            return _build_v02(
                payload,
                payload_path=payload_path,
                base_dir=base_dir,
            )
        if version not in {None, "0.1.0"}:
            raise RuntimeError(
                f"unsupported custom_mesh schema_version: {version!r}"
            )
        vertices = payload["vertices"]
        faces = payload["faces"]
        vertex_uvs = payload.get("vertex_uvs")
    else:
        vertices = spec["vertices"]
        faces = spec["faces"]

    mesh = bpy.data.meshes.new("CBM_CustomMesh")
    mesh.from_pydata(vertices, [], faces)
    if spec.get("recalculate_normals", True):
        mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    _apply_vertex_uvs(mesh, vertex_uvs)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("CBM_CustomMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
