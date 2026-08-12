"""Inspect one optimized or clean-import delivery stage for AQ v2 geometry survival."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import (  # noqa: E402
    native_io_path,
    operator_kwargs,
    sha256_file,
)


def _parse_args() -> argparse.Namespace:
    """Parse one fixed stage-inspection request without accepting executable input."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=[
            "compiled_candidate",
            "promoted_canonical",
            "optimized_lod0",
            "clean_import_glb",
            "clean_import_fbx",
        ],
    )
    parser.add_argument("--source-fingerprint-sha256", required=True)
    parser.add_argument("--build-fingerprint-sha256", required=True)
    parser.add_argument("--topology-profile", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _contained(path: str, root: Path, *, must_exist: bool) -> Path:
    """Resolve one lexical child and reject path escape before Blender file access."""

    candidate = Path(path).expanduser().resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("AQ v2 geometry inspection path escapes the job root") from exc
    if must_exist and not Path(native_io_path(candidate)).is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _canonical_sha256(value: object) -> str:
    """Hash one normalized JSON value with deterministic separators and key order."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sort_key(value: object) -> str:
    """Return one compact canonical JSON key for deterministic record ordering."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _round(value: float) -> float:
    """Quantize one finite geometry value for reorder-tolerant interchange comparison."""

    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError("delivery geometry contains a non-finite value")
    # A 2e-6 grid limits displacement to 1e-6 while avoiding decimal-boundary
    # instability from interchange serializer noise. V0.7 independently enforces
    # the materially wider 1e-4 m clean-import bounds contract.
    quantum = 0.000002
    rounded = round(round(number / quantum) * quantum, 6)
    return 0.0 if rounded == 0.0 else rounded


def _vector(values: Any, size: int) -> list[float]:
    """Project one Blender vector into a bounded finite rounded JSON array."""

    return [_round(values[index]) for index in range(size)]


def _normal_vector(values: Any) -> list[float]:
    """Quantize one unit normal within Blender interchange serialization precision."""

    result: list[float] = []
    for index in range(3):
        number = float(values[index])
        if not math.isfinite(number):
            raise RuntimeError("delivery geometry contains a non-finite normal")
        # Blender 5 glTF serializes normals at four decimal places and its importer
        # applies another bounded component quantization. A 1e-3 comparison cell
        # absorbs that round-trip noise while keeping flips and visible smoothing
        # changes outside the exact split-normal fingerprint.
        rounded = round(round(number / 0.001) * 0.001, 3)
        result.append(0.0 if rounded == 0.0 else rounded)
    return result


def _available(value: object) -> dict[str, object]:
    """Wrap one exact normalized fingerprint as available stage evidence."""

    return {"status": "available", "sha256": _canonical_sha256(value), "reason": None}


def _unavailable(reason: str) -> dict[str, object]:
    """Represent format-hidden authoring metadata without inventing a passing hash."""

    return {"status": "unavailable", "sha256": None, "reason": reason}


def _import_asset(stage: str, path: Path) -> None:
    """Import exactly GLB or FBX through Blender's whitelisted built-in operators."""

    bpy.ops.wm.read_factory_settings(use_empty=True)
    if stage == "clean_import_glb":
        operator = bpy.ops.import_scene.gltf
        operator(**operator_kwargs(operator, {"filepath": native_io_path(path)}))
        return
    operator = bpy.ops.import_scene.fbx
    operator(
        **operator_kwargs(
            operator,
            {
                "filepath": native_io_path(path),
                "use_custom_props": True,
                "use_custom_props_enum_as_string": True,
                "automatic_bone_orientation": False,
            },
        )
    )


def _object_identity(obj: bpy.types.Object) -> str:
    """Return one stable semantic plus optional instance identity for aggregate hashing."""

    semantic_id = str(obj.get("cbm_id", ""))
    instance = obj.get("cbm_instance_index")
    return f"{semantic_id}#{instance}" if instance is not None else semantic_id


def _stage_objects(stage: str) -> list[bpy.types.Object]:
    """Select visible authoring or non-collider LOD0 meshes for the requested stage."""

    selected: list[bpy.types.Object] = []
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        if obj.type != "MESH":
            continue
        role = str(obj.get("cbm_asset_role", ""))
        level = obj.get("cbm_lod_level")
        if stage in {"compiled_candidate", "promoted_canonical"}:
            if role in {"collider", "lod"} or bool(obj.hide_render):
                continue
        elif role not in {"render", "lod"} or int(level or 0) != 0:
            continue
        semantic_id = str(obj.get("cbm_id", ""))
        if not semantic_id:
            raise RuntimeError(f"{stage} mesh has no stable semantic ID: {obj.name}")
        selected.append(obj)
    if not selected:
        raise RuntimeError(f"{stage} contains no non-collider LOD0 mesh")
    identities = [_object_identity(obj) for obj in selected]
    if len(identities) != len(set(identities)):
        raise RuntimeError(f"{stage} contains duplicate LOD0 semantic IDs")
    return selected


def _material_ids(obj: bpy.types.Object) -> list[str]:
    """Read stable material IDs in exact slot order and reject unnamed assignments."""

    values: list[str] = []
    for slot in obj.material_slots:
        material = slot.material
        if material is None:
            raise RuntimeError(f"{obj.name} contains an empty material slot")
        material_id = str(material.get("cbm_id") or material.name)
        if not material_id:
            raise RuntimeError(f"{obj.name} contains an unnamed material")
        values.append(material_id)
    if not values:
        raise RuntimeError(f"{obj.name} contains no material slot")
    return values


def _corner_normals(mesh: bpy.types.Mesh) -> list[Any]:
    """Return one loop-aligned normal vector with a polygon-normal fallback."""

    mesh.update()
    normals = getattr(mesh, "corner_normals", None)
    if normals is not None and len(normals) == len(mesh.loops):
        return [item.vector.copy() for item in normals]
    values: list[Any] = [None] * len(mesh.loops)
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            values[loop_index] = polygon.normal.copy()
    if any(item is None for item in values):
        raise RuntimeError("mesh normal extraction produced an incomplete loop map")
    return values


def _delivery_uv_layer(mesh: bpy.types.Mesh) -> Any:
    """Select the same portable atlas or active-render UV layer used for export."""

    atlas = mesh.uv_layers.get("CBMPortableAtlas")
    if atlas is not None:
        return atlas
    return next(
        (layer for layer in mesh.uv_layers if bool(layer.active_render)),
        mesh.uv_layers.active or mesh.uv_layers[0],
    )


def _triangle_records(obj: bpy.types.Object) -> dict[str, list[object]]:
    """Create order-independent surface, UV, normal, and material triangle records."""

    mesh = obj.data
    if not mesh.uv_layers:
        raise RuntimeError(f"{obj.name} has no UV layer at the delivery boundary")
    mesh.calc_loop_triangles()
    uv_data = _delivery_uv_layer(mesh).data
    normals = _corner_normals(mesh)
    normal_matrix = obj.matrix_world.to_3x3().inverted_safe().transposed()
    material_ids = _material_ids(obj)
    surface: list[object] = []
    uv_records: list[object] = []
    normal_records: list[object] = []
    material_records: list[object] = []
    semantic_id = _object_identity(obj)
    for triangle in mesh.loop_triangles:
        corners: list[dict[str, object]] = []
        for vertex_index, loop_index in zip(
            triangle.vertices,
            triangle.loops,
            strict=True,
        ):
            position = obj.matrix_world @ mesh.vertices[vertex_index].co
            normal = (normal_matrix @ normals[loop_index]).normalized()
            corners.append(
                {
                    "position": _vector(position, 3),
                    "uv": _vector(uv_data[loop_index].uv, 2),
                    "normal": _normal_vector(normal),
                }
            )
        corners.sort(key=lambda item: json.dumps(item, sort_keys=True))
        polygon = mesh.polygons[triangle.polygon_index]
        material_index = int(polygon.material_index)
        if material_index >= len(material_ids):
            raise RuntimeError(f"{obj.name} polygon material index is out of range")
        material_id = material_ids[material_index]
        surface.append(
            {
                "semantic_id": semantic_id,
                "positions": sorted(item["position"] for item in corners),
            }
        )
        uv_records.extend(
            {
                "semantic_id": semantic_id,
                "position": item["position"],
                "uv": item["uv"],
            }
            for item in corners
        )
        normal_records.extend(
            {
                "semantic_id": semantic_id,
                "position": item["position"],
                "normal": item["normal"],
            }
            for item in corners
        )
        material_records.append(
            {
                "semantic_id": semantic_id,
                "material_id": material_id,
                "positions": sorted(item["position"] for item in corners),
            }
        )
    return {
        "surface": sorted(surface, key=_sort_key),
        "uv": sorted(uv_records, key=_sort_key),
        "normals": sorted(normal_records, key=_sort_key),
        "materials": sorted(material_records, key=_sort_key),
    }


def _topology_records(obj: bpy.types.Object) -> list[object]:
    """Create object-order-independent polygon records in world coordinates."""

    records: list[object] = []
    mesh = obj.data
    semantic_id = _object_identity(obj)
    for polygon in mesh.polygons:
        positions = sorted(
            _vector(obj.matrix_world @ mesh.vertices[index].co, 3)
            for index in polygon.vertices
        )
        records.append({"semantic_id": semantic_id, "positions": positions})
    return sorted(
        records,
        key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")),
    )


def _authoring_channels(objects: list[bpy.types.Object]) -> dict[str, object]:
    """Fingerprint optimized-stage authoring metadata before interchange export."""

    sharp: list[object] = []
    seams: list[object] = []
    creases: list[object] = []
    bevels: list[object] = []
    smoothing: list[object] = []
    modifiers: list[object] = []
    custom: list[object] = []
    for obj in objects:
        mesh = obj.data
        semantic_id = _object_identity(obj)
        for edge in mesh.edges:
            positions = sorted(
                _vector(obj.matrix_world @ mesh.vertices[index].co, 3)
                for index in edge.vertices
            )
            if edge.use_edge_sharp:
                sharp.append([semantic_id, positions])
            if edge.use_seam:
                seams.append([semantic_id, positions])
        for name, output in (("crease_edge", creases), ("bevel_weight_edge", bevels)):
            attribute = mesh.attributes.get(name)
            if attribute is not None:
                output.append(
                    [semantic_id, [_round(item.value) for item in attribute.data]]
                )
        smoothing.append(
            [semantic_id, [bool(polygon.use_smooth) for polygon in mesh.polygons]]
        )
        modifiers.append(
            [
                semantic_id,
                [
                    {"name": str(modifier.name), "type": str(modifier.type)}
                    for modifier in obj.modifiers
                ],
            ]
        )
        custom.append(
            [
                semantic_id,
                {
                    str(key): obj[key]
                    for key in sorted(obj.keys())
                    if str(key).startswith("cbm_")
                    and isinstance(obj[key], (str, int, float, bool))
                },
            ]
        )
    return {
        "sharp": _available(sorted(sharp)),
        "seams": _available(sorted(seams)),
        "creases": _available(sorted(creases)),
        "bevels": _available(sorted(bevels)),
        "smoothing": _available(sorted(smoothing)),
        "modifiers": _available(sorted(modifiers)),
        "custom": _available(sorted(custom)),
    }


def _snapshot(args: argparse.Namespace, artifact: Path) -> dict[str, object]:
    """Build one strict aggregate stage snapshot from all non-collider LOD0 objects."""

    objects = _stage_objects(args.stage)
    semantic_ids = sorted(_object_identity(obj) for obj in objects)
    topology: list[object] = []
    surface: list[object] = []
    uv: list[object] = []
    normals: list[object] = []
    polygon_materials: list[object] = []
    slot_records: list[object] = []
    vertex_count = face_count = loop_count = triangle_count = 0
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        vertex_count += len(mesh.vertices)
        face_count += len(mesh.polygons)
        loop_count += len(mesh.loops)
        triangle_count += len(mesh.loop_triangles)
        topology.extend(_topology_records(obj))
        records = _triangle_records(obj)
        surface.extend(records["surface"])
        uv.extend(records["uv"])
        normals.extend(records["normals"])
        polygon_materials.extend(records["materials"])
        slot_records.append(
            {"semantic_id": _object_identity(obj), "material_ids": _material_ids(obj)}
        )
    if args.stage not in {"clean_import_glb", "clean_import_fbx"}:
        authoring = _authoring_channels(objects)
    else:
        reason = "interchange import does not expose stable authoring metadata"
        authoring = {
            key: _unavailable(reason)
            for key in (
                "sharp",
                "seams",
                "creases",
                "bevels",
                "smoothing",
                "modifiers",
                "custom",
            )
        }
    return {
        "schema_version": "0.1.0",
        "stage": args.stage,
        "artifact_path": artifact.relative_to(Path(args.job_root).resolve()).as_posix(),
        "artifact_sha256": args.artifact_sha256,
        "source_fingerprint_sha256": args.source_fingerprint_sha256,
        "build_fingerprint_sha256": args.build_fingerprint_sha256,
        "semantic_id": "asset.aggregate",
        "topology_profile": args.topology_profile,
        "vertex_count": vertex_count,
        "face_count": face_count,
        "loop_count": loop_count,
        "evaluated_triangle_count": triangle_count,
        "topology_fingerprint": _available(sorted(topology, key=_sort_key)),
        "surface_equivalence_fingerprint": _available(sorted(surface, key=_sort_key)),
        "uv_fingerprint": _available(sorted(uv, key=_sort_key)),
        "material_slots_fingerprint": _available(
            {"semantic_ids": semantic_ids, "slots": sorted(slot_records, key=_sort_key)}
        ),
        "polygon_material_fingerprint": _available(
            sorted(polygon_materials, key=_sort_key)
        ),
        "split_normal_fingerprint": _available(sorted(normals, key=_sort_key)),
        "sharp_edge_fingerprint": authoring["sharp"],
        "uv_seam_fingerprint": authoring["seams"],
        "crease_fingerprint": authoring["creases"],
        "bevel_fingerprint": authoring["bevels"],
        "smoothing_fingerprint": authoring["smoothing"],
        "modifier_fingerprint": authoring["modifiers"],
        "custom_attribute_fingerprint": authoring["custom"],
    }


def _write_json(path: Path, payload: object) -> None:
    """Publish one immutable UTF-8 JSON report after all stage checks pass."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(native_io_path(path)).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    """Re-hash the inspected artifact, inspect its LOD0, and emit a strict snapshot."""

    args = _parse_args()
    root = Path(args.job_root).resolve()
    artifact = _contained(args.artifact, root, must_exist=True)
    output = _contained(args.output, root, must_exist=False)
    if sha256_file(artifact) != args.artifact_sha256:
        raise RuntimeError("delivery artifact changed before geometry inspection")
    if args.stage in {"clean_import_glb", "clean_import_fbx"}:
        _import_asset(args.stage, artifact)
    payload = _snapshot(args, artifact)
    if sha256_file(artifact) != args.artifact_sha256:
        raise RuntimeError("delivery artifact changed during geometry inspection")
    _write_json(output, payload)


if __name__ == "__main__":
    main()
