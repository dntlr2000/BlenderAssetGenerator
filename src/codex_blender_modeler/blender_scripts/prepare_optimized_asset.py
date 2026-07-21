from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import bmesh
import bpy
from mathutils import Matrix, Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import (  # noqa: E402
    material_ids,
    object_inventory,
    read_json_object,
    scene_source_provenance,
    sha256_file,
    write_json,
)
from uv_runtime import ensure_uv_mapping  # noqa: E402

DERIVED_COLLECTION = "CBM_PORTABLE_DERIVED"


def parse_args() -> argparse.Namespace:
    """Parse a bounded optimization plan and two derived output paths."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--output-manifest", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _nested(plan: dict[str, Any], name: str) -> dict[str, Any]:
    """Resolve a policy section from root, profile, or asset_profile containers."""

    direct = plan.get(name)
    if isinstance(direct, dict):
        return direct
    for container_name in ("profile", "asset_profile"):
        container = plan.get(container_name)
        if isinstance(container, dict) and isinstance(container.get(name), dict):
            return container[name]
    return {}


def _expected_fingerprint(plan: dict[str, Any]) -> str | None:
    """Resolve the host-approved source build fingerprint from compatible plan shapes."""

    for key in ("source_build_fingerprint", "build_fingerprint"):
        value = plan.get(key)
        if isinstance(value, str) and value:
            return value
    source = plan.get("source") or plan.get("source_fingerprint")
    if isinstance(source, dict):
        value = source.get("build_fingerprint") or source.get("fingerprint")
        if isinstance(value, str) and value:
            return value
    return None


def verify_source(plan: dict[str, Any], scene: bpy.types.Scene) -> dict[str, Any]:
    """Reject a stale optimization plan before any derived datablock is created."""

    provenance = scene_source_provenance(scene)
    expected = _expected_fingerprint(plan)
    actual = provenance.get("build_fingerprint")
    if not actual:
        raise RuntimeError("Loaded source scene has no embedded CBM build fingerprint")
    if expected and str(expected).lower() != str(actual).lower():
        raise RuntimeError(
            "Optimization plan build fingerprint does not match the loaded source scene: "
            f"{expected} != {actual}"
        )
    expected_spec = plan.get("source_scene_spec_sha256")
    source = plan.get("source")
    if expected_spec is None and isinstance(source, dict):
        scene_spec = source.get("scene_spec")
        if isinstance(scene_spec, dict):
            expected_spec = scene_spec.get("sha256")
    if expected_spec and str(expected_spec).lower() != str(
        provenance.get("scene_spec_sha256") or ""
    ).lower():
        raise RuntimeError("Optimization plan SceneSpec hash does not match the source scene")
    return provenance


def verify_input_artifacts(
    plan: dict[str, Any], profile_path: Path, source_blend: Path
) -> tuple[str, str]:
    """Verify separately supplied profile and source blend against canonical plan hashes."""

    profile_sha256 = sha256_file(profile_path)
    profile_artifact = plan.get("profile_artifact")
    if not isinstance(profile_artifact, dict) or not profile_artifact.get("sha256"):
        raise ValueError("OptimizationPlan requires a hashed profile_artifact")
    if profile_sha256 != str(profile_artifact["sha256"]).lower():
        raise RuntimeError("AssetProfile hash does not match OptimizationPlan")

    source_blend_sha256 = sha256_file(source_blend)
    source = plan.get("source")
    blend_artifact = source.get("blend") if isinstance(source, dict) else None
    if not isinstance(blend_artifact, dict) or not blend_artifact.get("sha256"):
        raise ValueError("OptimizationPlan requires a hashed source blend artifact")
    if source_blend_sha256 != str(blend_artifact["sha256"]).lower():
        raise RuntimeError("Loaded source .blend hash does not match OptimizationPlan")
    return profile_sha256, source_blend_sha256


def recreate_collection(name: str) -> bpy.types.Collection:
    """Replace only the named derived collection inside the in-memory output scene."""

    existing = bpy.data.collections.get(name)
    if existing is not None:
        for obj in list(existing.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(existing)
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def copy_custom_properties(source: bpy.types.Object, target: bpy.types.Object) -> None:
    """Copy serializable CBM provenance properties onto a derived portable object."""

    for key in sorted(source.keys()):
        if str(key).startswith("cbm_"):
            target[key] = source[key]


def evaluated_mesh_copy(
    source: bpy.types.Object,
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    """Convert evaluated source geometry into an independent derived mesh datablock."""

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )
    target = bpy.data.objects.new(f"{source.name}__LOD0", mesh)
    collection.objects.link(target)
    target.matrix_world = source.matrix_world.copy()
    copy_custom_properties(source, target)
    target["cbm_source_object"] = source.name
    target["cbm_asset_role"] = "render"
    target["cbm_lod_level"] = 0
    return target


def apply_transform_policy(obj: bpy.types.Object, policy: str) -> None:
    """Bake none, rotation/scale, or the complete world transform into derived geometry."""

    normalized = policy.strip().lower()
    world = obj.matrix_world.copy()
    if normalized in {"none", "preserve"}:
        return
    if normalized in {"rotation_scale", "rotation-scale"}:
        translation = world.to_translation()
        without_translation = world.copy()
        without_translation.translation = Vector((0.0, 0.0, 0.0))
        obj.data.transform(without_translation)
        obj.matrix_world = Matrix.Translation(translation)
        return
    if normalized in {"all", "world"}:
        obj.data.transform(world)
        obj.matrix_world = Matrix.Identity(4)
        return
    raise ValueError(f"Unsupported transform policy: {policy!r}")


def apply_pivot_policy(obj: bpy.types.Object, policy: str) -> None:
    """Move a derived object's pivot while preserving every world-space vertex."""

    normalized = policy.strip().lower()
    if normalized in {"keep", "preserve"}:
        return
    if normalized == "world_origin":
        obj.data.transform(obj.matrix_world)
        obj.matrix_world = Matrix.Identity(4)
        return
    if normalized == "bounds_center":
        local_corners = [Vector(corner) for corner in obj.bound_box]
        center = sum(local_corners, Vector()) / len(local_corners)
        obj.data.transform(Matrix.Translation(-center))
        obj.matrix_world = obj.matrix_world @ Matrix.Translation(center)
        return
    raise ValueError(f"Unsupported pivot policy: {policy!r}")


def repair_mesh(obj: bpy.types.Object, recalculate_normals: bool) -> None:
    """Validate a derived mesh and optionally recalculate consistent face normals."""

    mesh = obj.data
    mesh.validate(verbose=False, clean_customdata=False)
    if recalculate_normals and mesh.polygons:
        editable = bmesh.new()
        try:
            editable.from_mesh(mesh)
            bmesh.ops.recalc_face_normals(editable, faces=list(editable.faces))
            editable.to_mesh(mesh)
        finally:
            editable.free()
    mesh.update()


def triangulate_ngons_for_tangent_basis(obj: bpy.types.Object) -> int:
    """Triangulate only derived n-gons so Blender can calculate portable tangents."""

    mesh = obj.data
    editable = bmesh.new()
    try:
        editable.from_mesh(mesh)
        ngons = [face for face in editable.faces if len(face.verts) > 4]
        ngon_count = len(ngons)
        if ngons:
            bmesh.ops.triangulate(editable, faces=ngons)
            editable.to_mesh(mesh)
    finally:
        editable.free()
    if ngon_count:
        mesh.update()
    return ngon_count


def ensure_uvs(
    obj: bpy.types.Object,
    policy: dict[str, Any],
) -> tuple[list[str], str]:
    """Preserve UV0 as render-active while generating an independent lightmap UV1."""

    actions: list[str] = []
    uv0_name = str(policy.get("uv0_name", "UVMap"))
    uv0_generated = False
    if not obj.data.uv_layers and policy.get("generate_uv0", False):
        uv0_result = ensure_uv_mapping(obj, {"mode": "uv", "uv_set": uv0_name})
        actions.append(f"uv0:{uv0_result}")
        uv0_generated = uv0_result == "generated"
    elif obj.data.uv_layers:
        actions.append(f"uv0:preserved:{obj.data.uv_layers[0].name}")
    else:
        raise RuntimeError(
            "Portable render mesh has no UV0 and generation is disabled: "
            f"{obj.name}"
        )
    uv0 = obj.data.uv_layers.get(uv0_name) or obj.data.uv_layers[0]
    material_uv_name = str(uv0.name)
    if not material_uv_name:
        raise RuntimeError(f"Portable render mesh has an unnamed UV0: {obj.name}")
    if policy.get("generate_uv1", False):
        uv1_name = str(policy.get("uv1_name", "LightmapUV"))
        if uv1_name == material_uv_name:
            raise RuntimeError(
                "Portable render and lightmap UV sets must use distinct names: "
                f"{obj.name} ({material_uv_name})"
            )
        actions.append(
            f"uv1:{ensure_uv_mapping(obj, {'mode': 'uv', 'uv_set': uv1_name})}"
        )
    # Blender may invalidate collection-element wrappers when a new UV layer is added.
    # Reacquire UV0 by its stable name before selecting it or calculating tangents.
    uv0 = obj.data.uv_layers.get(material_uv_name)
    if uv0 is None:
        raise RuntimeError(
            f"Portable render UV0 disappeared during UV preparation: "
            f"{obj.name} ({material_uv_name})"
        )
    for layer in obj.data.uv_layers:
        layer.active_render = layer.name == material_uv_name
    obj.data.uv_layers.active = uv0
    obj["cbm_uv_policy"] = "smart_project" if uv0_generated else "preserved"
    obj["cbm_uv_set"] = material_uv_name
    obj["cbm_uv_generated"] = uv0_generated
    uv1_name = str(policy.get("uv1_name", "LightmapUV"))
    if policy.get("generate_uv1", False) and obj.data.uv_layers.get(uv1_name):
        obj["cbm_lightmap_uv_set"] = uv1_name
    elif "cbm_lightmap_uv_set" in obj:
        del obj["cbm_lightmap_uv_set"]
    return actions, material_uv_name


def generate_tangents(obj: bpy.types.Object, uv_set: str) -> str:
    """Feature-probe tangent calculation explicitly against the material UV0 layer."""

    mesh = obj.data
    if not mesh.uv_layers:
        return "skipped:no_uv"
    calculator = getattr(mesh, "calc_tangents", None)
    if calculator is None:
        return "unsupported"
    active = mesh.uv_layers.get(uv_set)
    if active is None:
        return f"failed:missing_uv:{uv_set}"
    try:
        calculator(uvmap=active.name)
    except (RuntimeError, TypeError, ValueError) as exc:
        return f"failed:{type(exc).__name__}:{exc}"
    # Tangent calculation may invalidate the RNA wrapper; retain the stable input name.
    return f"generated:{uv_set}"


def _activate(obj: bpy.types.Object) -> None:
    """Make one derived object the sole active selection for Blender operators."""

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def estimated_triangle_count(obj: bpy.types.Object) -> int:
    """Count polygon-fan triangles using the same contract as portable evidence."""

    return sum(max(0, len(face.vertices) - 2) for face in obj.data.polygons)


def mesh_fingerprint(obj: bpy.types.Object, *, world_space: bool) -> str:
    """Hash deterministic mesh coordinates, faces, and stable material identities."""

    matrix = obj.matrix_world if world_space else Matrix.Identity(4)
    vertices = [
        [round(float(value), 6) for value in matrix @ vertex.co]
        for vertex in obj.data.vertices
    ]
    faces = [
        {
            "vertices": [int(index) for index in polygon.vertices],
            "material_index": int(polygon.material_index),
        }
        for polygon in obj.data.polygons
    ]
    payload = {
        "vertices": vertices,
        "faces": faces,
        "materials": material_ids(obj),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def cleanup_loose_geometry(obj: bpy.types.Object) -> tuple[int, int]:
    """Remove only edge/vertex elements unused by faces from one derived mesh."""

    mesh = obj.data
    editable = bmesh.new()
    loose_edge_count = 0
    loose_vertex_count = 0
    try:
        editable.from_mesh(mesh)
        loose_edges = [edge for edge in editable.edges if not edge.link_faces]
        loose_edge_count = len(loose_edges)
        if loose_edges:
            bmesh.ops.delete(editable, geom=loose_edges, context="EDGES")
        loose_vertices = [vertex for vertex in editable.verts if not vertex.link_faces]
        loose_vertex_count = len(loose_vertices)
        if loose_vertices:
            bmesh.ops.delete(editable, geom=loose_vertices, context="VERTS")
        if loose_edges or loose_vertices:
            editable.to_mesh(mesh)
    finally:
        editable.free()
    if loose_edge_count or loose_vertex_count:
        mesh.validate(verbose=False, clean_customdata=False)
        mesh.update()
    return loose_vertex_count, loose_edge_count


def deduplicate_material_slots(obj: bpy.types.Object) -> int:
    """Collapse duplicate stable material slots while remapping derived polygons."""

    slots = list(obj.data.materials)
    if len(slots) < 2:
        return 0
    unique: list[Any] = []
    index_by_key: dict[str, int] = {}
    remap: dict[int, int] = {}
    for index, material in enumerate(slots):
        key = (
            str(material.get("cbm_id", material.name))
            if material is not None
            else f"__empty_slot_{index}"
        )
        if key not in index_by_key:
            index_by_key[key] = len(unique)
            unique.append(material)
        remap[index] = index_by_key[key]
    removed = len(slots) - len(unique)
    if not removed:
        return 0
    for polygon in obj.data.polygons:
        polygon.material_index = remap.get(int(polygon.material_index), 0)
    obj.data.materials.clear()
    for material in unique:
        obj.data.materials.append(material)
    obj.data.update()
    return removed


def _world_bounds(obj: bpy.types.Object) -> tuple[Vector, Vector]:
    """Calculate one derived object's world-space axis-aligned bounds."""

    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
    maximum = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
    return minimum, maximum


def _overlap_volume(
    left: tuple[Vector, Vector], right: tuple[Vector, Vector]
) -> float:
    """Return positive AABB intersection volume or zero for separated/touching bounds."""

    extents = [
        min(float(left[1][axis]), float(right[1][axis]))
        - max(float(left[0][axis]), float(right[0][axis]))
        for axis in range(3)
    ]
    if any(value <= 1.0e-9 for value in extents):
        return 0.0
    return float(extents[0] * extents[1] * extents[2])


def detect_exact_instances(objects: list[bpy.types.Object]) -> list[dict[str, Any]]:
    """Group equal local mesh payloads as advisory destination-instancing opportunities."""

    grouped: dict[tuple[str, tuple[str, ...]], list[bpy.types.Object]] = defaultdict(list)
    for obj in objects:
        if str(obj.get("cbm_asset_role")) != "render":
            continue
        fingerprint = str(obj.get("cbm_instance_fingerprint") or "")
        if fingerprint:
            grouped[(fingerprint, tuple(material_ids(obj)))].append(obj)
    results: list[dict[str, Any]] = []
    for index, ((fingerprint, materials), members) in enumerate(
        sorted(grouped.items(), key=lambda item: item[0]), start=1
    ):
        if len(members) < 2:
            continue
        results.append(
            {
                "group_id": f"instance.{index:04d}",
                "mesh_fingerprint": fingerprint,
                "objects": sorted(obj.name for obj in members),
                "semantic_ids": sorted({str(obj.get("cbm_id")) for obj in members}),
                "material_ids": list(materials),
                "potential_mesh_copies_saved": len(members) - 1,
            }
        )
    return results


def detect_overlap_candidates(
    objects: list[bpy.types.Object], *, phase: str, pair_limit: int
) -> tuple[list[dict[str, Any]], int, bool]:
    """Report exact duplicates and positive-volume AABB pairs without deleting faces."""

    render_objects = sorted(
        (obj for obj in objects if str(obj.get("cbm_asset_role")) == "render"),
        key=lambda item: item.name,
    )
    bounds = {obj.name: _world_bounds(obj) for obj in render_objects}
    fingerprints = {
        obj.name: mesh_fingerprint(obj, world_space=True) for obj in render_objects
    }
    findings: list[dict[str, Any]] = []
    total = 0
    for left, right in combinations(render_objects, 2):
        volume = _overlap_volume(bounds[left.name], bounds[right.name])
        if volume <= 0.0:
            continue
        total += 1
        if len(findings) >= pair_limit:
            continue
        exact = (
            fingerprints[left.name] == fingerprints[right.name]
            and material_ids(left) == material_ids(right)
        )
        findings.append(
            {
                "finding_id": f"overlap.{phase}.{len(findings) + 1:04d}",
                "left_object": left.name,
                "right_object": right.name,
                "left_semantic_id": str(left.get("cbm_id")),
                "right_semantic_id": str(right.get("cbm_id")),
                "classification": (
                    "exact_duplicate" if exact else "aabb_overlap_candidate"
                ),
                "overlap_volume_m3": round(volume, 9),
                "action": "report_only",
            }
        )
    return findings, total, total > len(findings)


def derived_cost_snapshot(
    objects: list[bpy.types.Object], overlap_candidates: int
) -> dict[str, int]:
    """Measure portable object, triangle, material, and draw-call cost proxies."""

    renders = [obj for obj in objects if str(obj.get("cbm_asset_role")) == "render"]
    lods = [obj for obj in objects if str(obj.get("cbm_asset_role")) == "lod"]
    colliders = [
        obj for obj in objects if str(obj.get("cbm_asset_role")) == "collider"
    ]
    all_meshes = [obj for obj in objects if obj.type == "MESH"]
    return {
        "lod0_render_objects": len(renders),
        "lod0_material_slots": sum(len(obj.material_slots) for obj in renders),
        "lod0_estimated_draw_calls": sum(
            max(1, len(set(material_ids(obj)))) for obj in renders
        ),
        "lod0_vertices": sum(len(obj.data.vertices) for obj in renders),
        "lod0_triangles": sum(estimated_triangle_count(obj) for obj in renders),
        "lod_objects": len(lods),
        "collider_objects": len(colliders),
        "collider_triangles": sum(estimated_triangle_count(obj) for obj in colliders),
        "total_derived_triangles": sum(
            estimated_triangle_count(obj) for obj in all_meshes
        ),
        "unique_materials": len(
            {material_id for obj in renders for material_id in material_ids(obj)}
        ),
        "overlap_candidates": overlap_candidates,
    }


def _batch_cell(obj: bpy.types.Object, policy: dict[str, Any]) -> tuple[int, int, int] | None:
    """Map one object center to a deterministic spatial cell when requested."""

    if str(policy.get("mode", "none")) != "by_spatial_cell":
        return None
    minimum, maximum = _world_bounds(obj)
    center = (minimum + maximum) * 0.5
    size = float(policy.get("spatial_cell_size_m", 25.0))
    return tuple(math.floor(float(center[axis]) / size) for axis in range(3))


def _batch_name(semantic_id: str, level: int, index: int) -> str:
    """Create one deterministic Blender-safe name for a semantic render batch."""

    safe = re.sub(r"[^A-Za-z0-9_]+", "_", semantic_id).strip("_") or "semantic"
    return f"CBM_{safe}__LOD{level}__BATCH{index:04d}"


def consolidate_semantic_batches(
    objects: list[bpy.types.Object], policy: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Join only equal semantic/material/UV groups inside the run-owned scene."""

    if str(policy.get("mode", "none")) == "none":
        return [], []
    maximum = int(policy.get("maximum_objects_per_batch", 64))
    grouped: dict[tuple[Any, ...], list[bpy.types.Object]] = defaultdict(list)
    for obj in objects:
        role = str(obj.get("cbm_asset_role"))
        if role not in {"render", "lod"} or obj.type != "MESH":
            continue
        semantic_id = str(obj.get("cbm_id"))
        level = int(obj.get("cbm_lod_level", 0))
        uv_signature = tuple(layer.name for layer in obj.data.uv_layers)
        grouped[
            (
                role,
                semantic_id,
                level,
                tuple(material_ids(obj)),
                uv_signature,
                _batch_cell(obj, policy),
            )
        ].append(obj)

    batches: list[dict[str, Any]] = []
    cleanups: list[dict[str, Any]] = []
    batch_index = 0
    for key, members in sorted(grouped.items(), key=lambda item: str(item[0])):
        role, semantic_id, level, materials, _uv_signature, cell = key
        ordered = sorted(members, key=lambda item: item.name)
        for offset in range(0, len(ordered), maximum):
            chunk = ordered[offset : offset + maximum]
            if len(chunk) < 2:
                continue
            batch_index += 1
            source_names = [obj.name for obj in chunk]
            triangles_before = sum(estimated_triangle_count(obj) for obj in chunk)
            material_slots_before = sum(len(obj.material_slots) for obj in chunk)
            bpy.ops.object.select_all(action="DESELECT")
            for obj in chunk:
                obj.hide_set(False)
                obj.select_set(True)
            target = chunk[0]
            bpy.context.view_layer.objects.active = target
            result = bpy.ops.object.join()
            if "FINISHED" not in result:
                raise RuntimeError(
                    f"Semantic batch join failed for {semantic_id}: {sorted(result)}"
                )
            target.name = _batch_name(semantic_id, level, batch_index)
            target["cbm_asset_role"] = role
            target["cbm_lod_level"] = level
            target["cbm_batch_id"] = f"batch.{batch_index:04d}"
            target["cbm_batch_source_count"] = len(source_names)
            target["cbm_batch_source_objects"] = json.dumps(
                source_names, ensure_ascii=True, separators=(",", ":")
            )
            if "cbm_instance_index" in target:
                del target["cbm_instance_index"]
            removed_slots = (
                deduplicate_material_slots(target)
                if bool(policy.get("deduplicate_material_slots", True))
                else 0
            )
            triangles_after = estimated_triangle_count(target)
            if triangles_after != triangles_before:
                raise RuntimeError(
                    f"Semantic batching changed triangle count for {semantic_id}: "
                    f"{triangles_before} != {triangles_after}"
                )
            batches.append(
                {
                    "batch_id": f"batch.{batch_index:04d}",
                    "semantic_id": semantic_id,
                    "lod_level": level,
                    "spatial_cell": list(cell) if cell is not None else None,
                    "material_ids": list(materials),
                    "source_objects": source_names,
                    "output_object": target.name,
                    "object_count_before": len(source_names),
                    "object_count_after": 1,
                    "triangle_count_before": triangles_before,
                    "triangle_count_after": triangles_after,
                    "material_slots_before": material_slots_before,
                    "material_slots_after": len(target.material_slots),
                }
            )
            if removed_slots:
                cleanups.append(
                    {
                        "semantic_id": semantic_id,
                        "object_name": target.name,
                        "asset_role": role,
                        "lod_level": level,
                        "loose_vertices_removed": 0,
                        "loose_edges_removed": 0,
                        "duplicate_material_slots_removed": removed_slots,
                        "exact_duplicate_colliders_removed": 0,
                    }
                )
    return batches, cleanups


def deduplicate_exact_colliders(
    objects: list[bpy.types.Object], enabled: bool
) -> list[dict[str, Any]]:
    """Remove exact duplicate derived colliders owned by the same semantic family."""

    if not enabled:
        return []
    grouped: dict[tuple[str, str, str], list[bpy.types.Object]] = defaultdict(list)
    for obj in objects:
        if str(obj.get("cbm_asset_role")) != "collider" or obj.type != "MESH":
            continue
        key = (
            str(obj.get("cbm_id")),
            str(obj.get("cbm_collider_strategy")),
            mesh_fingerprint(obj, world_space=True),
        )
        grouped[key].append(obj)
    records: list[dict[str, Any]] = []
    for (semantic_id, _strategy, _fingerprint), members in sorted(
        grouped.items(), key=lambda item: item[0]
    ):
        ordered = sorted(members, key=lambda item: item.name)
        if len(ordered) < 2:
            continue
        for duplicate in ordered[1:]:
            name = duplicate.name
            bpy.data.objects.remove(duplicate, do_unlink=True)
            records.append(
                {
                    "semantic_id": semantic_id,
                    "object_name": name,
                    "asset_role": "collider",
                    "lod_level": None,
                    "loose_vertices_removed": 0,
                    "loose_edges_removed": 0,
                    "duplicate_material_slots_removed": 0,
                    "exact_duplicate_colliders_removed": 1,
                }
            )
    return records


def apply_decimate_pass(
    target: bpy.types.Object,
    *,
    name: str,
    ratio: float,
) -> None:
    """Apply one bounded Decimate pass to a run-owned derived mesh."""

    modifier = target.modifiers.new(name=name, type="DECIMATE")
    if not hasattr(modifier, "ratio"):
        raise RuntimeError("Running Blender build exposes no Decimate ratio property")
    modifier.ratio = max(0.001, min(0.999, ratio))
    if hasattr(modifier, "use_collapse_triangulate"):
        modifier.use_collapse_triangulate = True
    _activate(target)
    result = bpy.ops.object.modifier_apply(modifier=modifier.name)
    if "FINISHED" not in result:
        raise RuntimeError(f"Decimate modifier failed for {target.name}: {sorted(result)}")
    target.data.validate(verbose=False, clean_customdata=False)
    target.data.update()


def normalize_derived_lod_for_budget(
    target: bpy.types.Object,
    *,
    area_epsilon: float = 1.0e-12,
) -> tuple[int, int]:
    """Triangulate a derived LOD and remove only non-rendering zero-area faces."""

    mesh = target.data
    editable = bmesh.new()
    try:
        editable.from_mesh(mesh)
        non_triangles = [face for face in editable.faces if len(face.verts) != 3]
        triangulated = len(non_triangles)
        if non_triangles:
            bmesh.ops.triangulate(editable, faces=non_triangles)
        zero_area_faces = [
            face for face in editable.faces if face.calc_area() <= area_epsilon
        ]
        removed = len(zero_area_faces)
        if zero_area_faces:
            bmesh.ops.delete(editable, geom=zero_area_faces, context="FACES")
        if triangulated or removed:
            editable.to_mesh(mesh)
    finally:
        editable.free()
    if triangulated or removed:
        mesh.validate(verbose=False, clean_customdata=False)
        mesh.update()
    return triangulated, removed


def make_lod(
    source: bpy.types.Object,
    collection: bpy.types.Collection,
    level: int,
    ratio: float,
) -> bpy.types.Object:
    """Create one deterministic decimated LOD copy without altering LOD0 geometry."""

    if level <= 0 or not 0.0 < ratio < 1.0:
        raise ValueError(f"LOD{level} requires a ratio between zero and one: {ratio}")
    target = source.copy()
    target.data = source.data.copy()
    target.name = f"{source.name.rsplit('__LOD0', 1)[0]}__LOD{level}"
    collection.objects.link(target)
    target["cbm_asset_role"] = "lod"
    target["cbm_lod_level"] = level
    target["cbm_lod_ratio"] = ratio
    source_triangles = estimated_triangle_count(source)
    maximum_triangles = (
        max(1, math.ceil(source_triangles * ratio)) if source_triangles else 0
    )
    decimate_passes = 0
    triangulated_faces = 0
    removed_zero_area_faces = 0
    if source_triangles:
        apply_decimate_pass(
            target,
            name=f"CBM_LOD{level}_DECIMATE",
            ratio=ratio,
        )
        decimate_passes += 1
    current_triangles = estimated_triangle_count(target)
    if current_triangles > maximum_triangles:
        triangulated_faces, removed_zero_area_faces = normalize_derived_lod_for_budget(
            target
        )
        current_triangles = estimated_triangle_count(target)
    if current_triangles > maximum_triangles:
        correction_ratio = maximum_triangles / current_triangles * 0.95
        apply_decimate_pass(
            target,
            name=f"CBM_LOD{level}_BUDGET_CORRECTION",
            ratio=correction_ratio,
        )
        decimate_passes += 1
        current_triangles = estimated_triangle_count(target)
    if current_triangles > maximum_triangles:
        raise RuntimeError(
            f"LOD{level} triangle budget remains exceeded for {target.name}: "
            f"actual={current_triangles}, maximum={maximum_triangles}"
        )
    target["cbm_lod_source_triangle_count"] = source_triangles
    target["cbm_lod_triangle_budget"] = maximum_triangles
    target["cbm_lod_triangle_count"] = current_triangles
    target["cbm_lod_decimate_passes"] = decimate_passes
    target["cbm_lod_triangulated_faces"] = triangulated_faces
    target["cbm_lod_removed_zero_area_faces"] = removed_zero_area_faces
    target.data.validate(verbose=False, clean_customdata=False)
    target.data.update()
    return target


def _box_mesh(name: str, minimum: Vector, maximum: Vector) -> bpy.types.Mesh:
    """Create one deterministic local-space axis-aligned box mesh."""

    x0, y0, z0 = minimum
    x1, y1, z1 = maximum
    vertices = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh


def _sphere_mesh(name: str, center: Vector, radius: float) -> bpy.types.Mesh:
    """Create a deterministic low-density icosphere collider around local bounds."""

    mesh = bpy.data.meshes.new(name)
    editable = bmesh.new()
    try:
        bmesh.ops.create_icosphere(editable, subdivisions=2, radius=radius)
        bmesh.ops.translate(editable, vec=center, verts=list(editable.verts))
        editable.to_mesh(mesh)
    finally:
        editable.free()
    mesh.update()
    return mesh


def _capsule_mesh(
    name: str, center: Vector, dimensions: Vector, segments: int = 12, rings: int = 8
) -> bpy.types.Mesh:
    """Create a deterministic capsule aligned to the longest local-bounds axis."""

    axis = max(range(3), key=lambda index: float(dimensions[index]))
    radial_axes = [index for index in range(3) if index != axis]
    radius = max(
        1e-6,
        max(float(dimensions[radial_axes[0]]), float(dimensions[radial_axes[1]]))
        * 0.5,
    )
    cylinder_half = max(0.0, float(dimensions[axis]) * 0.5 - radius)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    bottom = [float(center[index]) for index in range(3)]
    bottom[axis] -= cylinder_half + radius
    vertices.append(tuple(bottom))
    for ring in range(1, rings):
        phi = -math.pi * 0.5 + math.pi * ring / rings
        axial = math.sin(phi) * radius + (cylinder_half if phi > 0 else -cylinder_half)
        ring_radius = math.cos(phi) * radius
        for segment in range(segments):
            angle = 2.0 * math.pi * segment / segments
            coordinate = [float(center[index]) for index in range(3)]
            coordinate[axis] += axial
            coordinate[radial_axes[0]] += math.cos(angle) * ring_radius
            coordinate[radial_axes[1]] += math.sin(angle) * ring_radius
            vertices.append(tuple(coordinate))
    top_index = len(vertices)
    top = [float(center[index]) for index in range(3)]
    top[axis] += cylinder_half + radius
    vertices.append(tuple(top))

    first_ring = 1
    for segment in range(segments):
        faces.append((0, first_ring + (segment + 1) % segments, first_ring + segment))
    for ring in range(rings - 2):
        start = 1 + ring * segments
        next_start = start + segments
        for segment in range(segments):
            next_segment = (segment + 1) % segments
            faces.append(
                (
                    start + segment,
                    start + next_segment,
                    next_start + next_segment,
                    next_start + segment,
                )
            )
    last_ring = 1 + (rings - 2) * segments
    for segment in range(segments):
        faces.append(
            (last_ring + segment, last_ring + (segment + 1) % segments, top_index)
        )
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    return mesh


def make_collider(
    source: bpy.types.Object,
    collection: bpy.types.Collection,
    strategy: str,
) -> bpy.types.Object | None:
    """Create a box, convex-hull, or reduced mesh collider linked to one semantic object."""

    normalized = strategy.strip().lower()
    if normalized in {"none", "off", ""}:
        return None
    if normalized in {"box", "compound"}:
        corners = [Vector(corner) for corner in source.bound_box]
        minimum = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
        maximum = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
        mesh = _box_mesh(f"{source.name}__COLLIDER_MESH", minimum, maximum)
    elif normalized == "sphere":
        corners = [Vector(corner) for corner in source.bound_box]
        minimum = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
        maximum = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
        center = (minimum + maximum) * 0.5
        radius = float((maximum - minimum).length) * 0.5
        mesh = _sphere_mesh(f"{source.name}__COLLIDER_MESH", center, radius)
    elif normalized == "capsule":
        corners = [Vector(corner) for corner in source.bound_box]
        minimum = Vector(tuple(min(corner[axis] for corner in corners) for axis in range(3)))
        maximum = Vector(tuple(max(corner[axis] for corner in corners) for axis in range(3)))
        mesh = _capsule_mesh(
            f"{source.name}__COLLIDER_MESH",
            (minimum + maximum) * 0.5,
            maximum - minimum,
        )
    elif normalized in {"convex_hull", "convex"}:
        mesh = bpy.data.meshes.new(f"{source.name}__COLLIDER_MESH")
        editable = bmesh.new()
        try:
            for vertex in source.data.vertices:
                editable.verts.new(vertex.co)
            editable.verts.ensure_lookup_table()
            result = bmesh.ops.convex_hull(editable, input=list(editable.verts))
            unused = {
                item
                for key in ("geom_unused", "geom_interior")
                for item in result.get(key, [])
                if isinstance(item, bmesh.types.BMVert)
            }
            if unused:
                bmesh.ops.delete(editable, geom=list(unused), context="VERTS")
            editable.to_mesh(mesh)
        finally:
            editable.free()
    elif normalized in {"mesh_proxy", "mesh"}:
        mesh = source.data.copy()
    else:
        raise ValueError(f"Unsupported collider strategy: {strategy!r}")

    collider = bpy.data.objects.new(f"{source.name}__COLLIDER", mesh)
    collection.objects.link(collider)
    collider.matrix_world = source.matrix_world.copy()
    collider["cbm_id"] = source.get("cbm_id")
    collider["cbm_instance_index"] = source.get("cbm_instance_index")
    collider["cbm_source_object"] = source.name
    collider["cbm_asset_role"] = "collider"
    collider["cbm_collider_strategy"] = normalized
    collider.display_type = "WIRE"
    collider.hide_render = True
    return collider


def enforce_collider_triangle_budget(
    collider: bpy.types.Object,
    maximum: int,
) -> tuple[int, int]:
    """Decimate a complex collider when needed and enforce its explicit triangle budget."""

    before = sum(max(0, len(face.vertices) - 2) for face in collider.data.polygons)
    if before <= maximum:
        return before, before
    modifier = collider.modifiers.new(name="CBM_COLLIDER_BUDGET", type="DECIMATE")
    if not hasattr(modifier, "ratio"):
        raise RuntimeError("Running Blender build exposes no collider Decimate ratio")
    modifier.ratio = max(0.001, min(1.0, maximum / before * 0.95))
    if hasattr(modifier, "use_collapse_triangulate"):
        modifier.use_collapse_triangulate = True
    _activate(collider)
    result = bpy.ops.object.modifier_apply(modifier=modifier.name)
    if "FINISHED" not in result:
        raise RuntimeError(
            f"Collider decimation failed for {collider.name}: {sorted(result)}"
        )
    collider.data.validate(verbose=False, clean_customdata=False)
    collider.data.update()
    after = sum(max(0, len(face.vertices) - 2) for face in collider.data.polygons)
    if after > maximum:
        raise RuntimeError(
            f"Collider {collider.name} exceeds triangle budget {after} > {maximum}"
        )
    return before, after


def lod_levels(policy: dict[str, Any]) -> list[tuple[int, float]]:
    """Normalize explicit LOD level records or a compact ratio list."""

    if not policy.get("enabled", False):
        return [(0, 1.0)]
    supplied = policy.get("targets", policy.get("levels"))
    normalized: list[tuple[int, float]] = [(0, 1.0)]
    if isinstance(supplied, list):
        for index, item in enumerate(supplied):
            if isinstance(item, dict):
                level = int(item.get("level", index))
                ratio = float(
                    item.get(
                        "target_triangle_ratio",
                        item.get("ratio", item.get("reduction_ratio", 1.0)),
                    )
                )
            else:
                level = index
                ratio = float(item)
            if level > 0:
                normalized.append((level, ratio))
    elif int(policy.get("levels_count", 1)) > 1:
        defaults = [1.0, 0.6, 0.3, 0.12]
        count = min(int(policy["levels_count"]), len(defaults))
        normalized.extend((index, defaults[index]) for index in range(1, count))
    return sorted(set(normalized))


def object_policy(
    plan: dict[str, Any], semantic_id: str, section: str, default: Any
) -> Any:
    """Resolve one per-semantic override while retaining a stable global default."""

    overrides = plan.get("objects") or plan.get("object_policies")
    if isinstance(overrides, dict):
        item = overrides.get(semantic_id)
        if isinstance(item, dict) and section in item:
            return item[section]
    return default


def directive_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index canonical OptimizationPlan directives by stable semantic target ID."""

    directives = plan.get("directives", [])
    if not isinstance(directives, list):
        raise ValueError("OptimizationPlan directives must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in directives:
        if not isinstance(item, dict) or not item.get("target_id"):
            raise ValueError("Every optimization directive requires target_id")
        target_id = str(item["target_id"])
        if target_id in result:
            raise ValueError(f"Duplicate optimization directive: {target_id}")
        result[target_id] = item
    return result


def directive_lod_policy(
    base_policy: dict[str, Any], directive: dict[str, Any] | None
) -> dict[str, Any]:
    """Filter profile LOD targets to the exact levels requested by one directive."""

    if not directive or not directive.get("lod_levels"):
        return base_policy
    requested = {int(value) for value in directive["lod_levels"]}
    targets = base_policy.get("targets", base_policy.get("levels", []))
    if not isinstance(targets, list):
        raise ValueError("LOD policy targets must be an array")
    selected = [
        item
        for item in targets
        if isinstance(item, dict) and int(item.get("level", -1)) in requested
    ]
    missing = requested - {int(item["level"]) for item in selected}
    if missing:
        raise ValueError(f"Directive requests undefined LOD levels: {sorted(missing)}")
    return {**base_policy, "targets": selected}


def main() -> None:
    """Create a separate optimized Blender scene while leaving its source file untouched."""

    args = parse_args()
    plan_path = Path(args.plan).expanduser().resolve()
    profile_path = Path(args.profile).expanduser().resolve()
    output_blend = Path(args.output_blend).expanduser().resolve()
    output_manifest = Path(args.output_manifest).expanduser().resolve()
    source_blend = Path(bpy.data.filepath).expanduser().resolve()
    if not source_blend.is_file():
        raise FileNotFoundError("A saved canonical source .blend must be loaded")
    if output_blend == source_blend:
        raise RuntimeError("Derived output must not overwrite the canonical source .blend")

    plan = read_json_object(plan_path)
    profile = read_json_object(profile_path)
    if plan.get("schema_version") != "0.7.0" or profile.get("schema_version") != "0.7.0":
        raise ValueError("OptimizationPlan and AssetProfile must use schema_version 0.7.0")
    if plan.get("profile_id") != profile.get("profile_id"):
        raise ValueError("OptimizationPlan profile_id does not match AssetProfile")
    if plan.get("job_id") != profile.get("job_id"):
        raise ValueError("OptimizationPlan job_id does not match AssetProfile")
    if plan.get("status") not in {"approved", "running"}:
        raise RuntimeError("OptimizationPlan must be approved before derived preparation")
    plan_sha256 = sha256_file(plan_path)
    profile_sha256, source_blend_sha256 = verify_input_artifacts(
        plan, profile_path, source_blend
    )
    provenance = verify_source(plan, bpy.context.scene)
    transform_policy = "rotation_scale"
    pivot_policy = "keep"
    mesh_policy = {
        "recalculate_normals": True,
        "triangulate_ngons": True,
        "generate_tangents": True,
    }
    consolidation_policy = {
        "mode": "none",
        "maximum_objects_per_batch": 64,
        "spatial_cell_size_m": 25.0,
        "remove_loose_geometry": True,
        "deduplicate_material_slots": True,
        "deduplicate_exact_colliders": True,
        "detect_exact_instances": True,
        "detect_overlap_candidates": True,
        "overlap_pair_limit": 5000,
    }
    supplied_consolidation = profile.get("consolidation", {})
    if isinstance(supplied_consolidation, dict):
        consolidation_policy.update(supplied_consolidation)
    budget_policy = profile.get("budgets", {})
    if not isinstance(budget_policy, dict):
        raise ValueError("AssetProfile budgets must be an object")
    profile_uv = profile.get("uv", {})
    if not isinstance(profile_uv, dict):
        raise ValueError("AssetProfile uv must be an object")
    uv_policy = {
        **profile_uv,
        "generate_uv0": bool(profile_uv.get("generate_uv0_if_missing", True)),
    }
    lod_policy = profile.get("lod", {})
    collision_policy = profile.get("collision", {})
    if not isinstance(lod_policy, dict) or not isinstance(collision_policy, dict):
        raise ValueError("AssetProfile lod and collision must be objects")
    collider_default = str(collision_policy.get("strategy", "none"))
    directives = directive_map(plan)

    derived_collection = recreate_collection(DERIVED_COLLECTION)
    authoring_geometry = sorted(
        (
            obj
            for obj in bpy.context.scene.objects
            if obj.type in {"MESH", "CURVE"}
            and str(obj.get("cbm_asset_role") or "authoring") == "authoring"
        ),
        key=lambda item: item.name,
    )
    anonymous_authoring_geometry = [
        obj.name for obj in authoring_geometry if not obj.get("cbm_id")
    ]
    if anonymous_authoring_geometry:
        raise RuntimeError(
            "Canonical authoring geometry is missing stable cbm_id: "
            + ", ".join(anonymous_authoring_geometry)
        )
    source_objects = authoring_geometry
    if not source_objects:
        raise RuntimeError("No canonical semantic geometry was found in the loaded scene")
    source_ids = {str(obj.get("cbm_id")) for obj in source_objects}
    directive_ids = set(directives)
    missing_directives = sorted(source_ids - directive_ids)
    unknown_directives = sorted(directive_ids - source_ids)
    if missing_directives or unknown_directives:
        raise RuntimeError(
            "Optimization directives must match canonical semantic geometry exactly; "
            f"missing={missing_directives}, unknown={unknown_directives}"
        )

    derived_objects: list[bpy.types.Object] = []
    actions: list[dict[str, Any]] = []
    cleanup_records: list[dict[str, Any]] = []
    for source in source_objects:
        semantic_id = str(source.get("cbm_id"))
        directive = directives[semantic_id]
        if not bool(directive.get("include", True)):
            continue
        lod0 = evaluated_mesh_copy(source, derived_collection)
        lod0["cbm_instance_fingerprint"] = mesh_fingerprint(
            lod0, world_space=False
        )
        if str(lod0.get("cbm_id")) != semantic_id:
            raise RuntimeError(f"Derived semantic ID changed for {source.name}")
        if material_ids(lod0) != material_ids(source):
            raise RuntimeError(f"Derived material IDs changed for {source.name}")
        apply_transform_policy(lod0, transform_policy)
        apply_pivot_policy(lod0, pivot_policy)
        repair_mesh(lod0, bool(mesh_policy.get("recalculate_normals", True)))
        loose_vertices, loose_edges = (0, 0)
        if bool(consolidation_policy.get("remove_loose_geometry", True)):
            loose_vertices, loose_edges = cleanup_loose_geometry(lod0)
        if loose_vertices or loose_edges:
            cleanup_records.append(
                {
                    "semantic_id": semantic_id,
                    "object_name": lod0.name,
                    "asset_role": "render",
                    "lod_level": 0,
                    "loose_vertices_removed": loose_vertices,
                    "loose_edges_removed": loose_edges,
                    "duplicate_material_slots_removed": 0,
                    "exact_duplicate_colliders_removed": 0,
                }
            )
        triangulated_ngons = (
            triangulate_ngons_for_tangent_basis(lod0)
            if bool(mesh_policy.get("triangulate_ngons", True))
            else 0
        )
        uv_actions, material_uv_set = ensure_uvs(lod0, uv_policy)
        tangent_action = (
            generate_tangents(lod0, material_uv_set)
            if bool(mesh_policy.get("generate_tangents", True))
            else "disabled"
        )
        if tangent_action == "unsupported" or tangent_action.startswith("failed:"):
            raise RuntimeError(
                f"Tangent readiness failed for {semantic_id}: {tangent_action}"
            )
        derived_objects.append(lod0)
        object_actions: dict[str, Any] = {
            "source_object": source.name,
            "semantic_id": semantic_id,
            "lods": [0],
            "lod_triangle_counts": {"0": estimated_triangle_count(lod0)},
            "triangulated_ngons": triangulated_ngons,
            "uv": uv_actions,
            "tangents": tangent_action,
            "collider": None,
        }
        object_lod_policy = directive_lod_policy(lod_policy, directive)
        for level, ratio in lod_levels(object_lod_policy):
            if level == 0:
                continue
            lod = make_lod(lod0, derived_collection, level, ratio)
            derived_objects.append(lod)
            object_actions["lods"].append(level)
            object_actions["lod_triangle_counts"][str(level)] = estimated_triangle_count(
                lod
            )

        strategy = str((directive or {}).get("collision_strategy", "inherit"))
        if strategy == "inherit":
            strategy = collider_default
        collider = make_collider(lod0, derived_collection, strategy)
        if collider is not None:
            collider_before, collider_after = enforce_collider_triangle_budget(
                collider,
                int(collision_policy.get("max_triangles_per_object", 256)),
            )
            derived_objects.append(collider)
            object_actions["collider"] = strategy
            object_actions["collider_triangles"] = {
                "before": collider_before,
                "after": collider_after,
            }
        actions.append(object_actions)

    before_objects = sorted(list(derived_collection.objects), key=lambda item: item.name)
    instance_groups = (
        detect_exact_instances(before_objects)
        if bool(consolidation_policy.get("detect_exact_instances", True))
        else []
    )
    if bool(consolidation_policy.get("detect_overlap_candidates", True)):
        overlap_before, overlap_before_total, overlap_before_truncated = (
            detect_overlap_candidates(
                before_objects,
                phase="before",
                pair_limit=int(consolidation_policy.get("overlap_pair_limit", 5000)),
            )
        )
    else:
        overlap_before, overlap_before_total, overlap_before_truncated = [], 0, False
    before_cost = derived_cost_snapshot(before_objects, overlap_before_total)

    consolidation_batches, batch_cleanups = consolidate_semantic_batches(
        before_objects, consolidation_policy
    )
    cleanup_records.extend(batch_cleanups)
    cleanup_records.extend(
        deduplicate_exact_colliders(
            list(derived_collection.objects),
            bool(consolidation_policy.get("deduplicate_exact_colliders", True)),
        )
    )
    derived_objects = sorted(list(derived_collection.objects), key=lambda item: item.name)
    if bool(consolidation_policy.get("detect_overlap_candidates", True)):
        overlap_after, overlap_after_total, overlap_after_truncated = (
            detect_overlap_candidates(
                derived_objects,
                phase="after",
                pair_limit=int(consolidation_policy.get("overlap_pair_limit", 5000)),
            )
        )
    else:
        overlap_after, overlap_after_total, overlap_after_truncated = [], 0, False
    after_cost = derived_cost_snapshot(derived_objects, overlap_after_total)

    scene = bpy.context.scene
    scene["cbm_portable_schema_version"] = "0.7.0"
    scene["cbm_portable_plan_sha256"] = plan_sha256
    scene["cbm_portable_source_build_fingerprint"] = str(
        provenance["build_fingerprint"]
    )
    scene["cbm_portable_source_scene_spec_sha256"] = str(
        provenance.get("scene_spec_sha256") or ""
    )
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_blend.with_name(output_blend.stem + ".partial.blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(temporary))
    temporary.replace(output_blend)

    records = [
        object_inventory(obj)
        for obj in sorted(derived_objects, key=lambda item: item.name)
    ]
    manifest = {
        "schema_version": "0.7.0",
        "kind": "optimized_asset_manifest",
        "ok": True,
        "plan_sha256": plan_sha256,
        "profile_sha256": profile_sha256,
        "source": {
            **provenance,
            "blend_sha256": source_blend_sha256,
        },
        "derived": {
            "blend_filename": output_blend.name,
            "blend_sha256": sha256_file(output_blend),
            "collection": DERIVED_COLLECTION,
            "object_count": len(records),
            "render_object_count": sum(
                record["asset_role"] == "render" for record in records
            ),
            "lod_object_count": sum(record["asset_role"] == "lod" for record in records),
            "collider_object_count": sum(
                record["asset_role"] == "collider" for record in records
            ),
        },
        "policies": {
            "transform": transform_policy,
            "pivot": pivot_policy,
            "mesh": mesh_policy,
            "uv": uv_policy,
            "lod": lod_policy,
            "collision": collision_policy,
            "consolidation": consolidation_policy,
            "budgets": budget_policy,
        },
        "actions": actions,
        "cost_optimization": {
            "before": before_cost,
            "after": after_cost,
            "consolidation_batches": consolidation_batches,
            "cleanup_records": cleanup_records,
            "instance_groups": instance_groups,
            "overlap_findings_before": overlap_before,
            "overlap_findings_after": overlap_after,
            "overlap_before_truncated": overlap_before_truncated,
            "overlap_after_truncated": overlap_after_truncated,
            "limitations": [
                "AABB overlap findings are broad-phase candidates, not proven face intersections.",
                "Internal and coplanar hidden faces remain unclassified and are not removed.",
                "Instance groups are advisory until a destination adapter reconstructs them.",
                "Estimated draw calls are material-slot proxies, not runtime measurements.",
            ],
        },
        "objects": records,
        "runtime": {"blender_version": bpy.app.version_string},
    }
    write_json(output_manifest, manifest)
    print(
        "CBM_ASSET_PREPARE_OK "
        f"objects={len(records)} output={output_blend} manifest={output_manifest}"
    )


if __name__ == "__main__":
    main()
