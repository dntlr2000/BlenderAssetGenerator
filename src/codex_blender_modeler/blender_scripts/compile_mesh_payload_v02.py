"""Compile one host-validated MeshPayload 0.2 through bounded Blender data APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy


def _parse_args() -> argparse.Namespace:
    """Parse only fixed payload, output, report, and exact-hash arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--payload-sha256", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _contained(path: str, job_root: Path, *, must_exist: bool) -> Path:
    """Resolve one path inside the active job and enforce its expected existence."""

    resolved = Path(path).resolve()
    try:
        resolved.relative_to(job_root)
    except ValueError as exc:
        raise RuntimeError("MeshPayload 0.2 compiler path escapes job root") from exc
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    if not must_exist and resolved.exists():
        raise FileExistsError(resolved)
    return resolved


def _sha256_file(path: Path) -> str:
    """Return the exact file SHA-256 used by the host-to-Blender binding."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    """Hash one deterministic JSON-compatible value for stage evidence."""

    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _required_payload_shape(payload: dict[str, Any]) -> None:
    """Defend Blender from bypassed host validation using a narrow required-key check."""

    required = {
        "schema_version",
        "semantic_id",
        "vertices",
        "faces",
        "loop_count",
        "loop_uvs",
        "material_slots",
        "polygon_material_indices",
        "sharp_edges",
        "uv_seams",
        "edge_creases",
        "bevel_weights",
        "face_groups",
        "smooth_polygon_flags",
        "custom_attribute_manifest",
        "modifier_materialization_policy",
        "weighted_normal_intent",
        "subdivision_intent",
        "source_geometry_intent",
        "source_fingerprint_sha256",
    }
    missing = sorted(required - set(payload))
    if missing or payload.get("schema_version") != "0.2.0":
        raise RuntimeError(f"invalid MeshPayload 0.2 compiler input; missing={missing}")
    if payload["loop_count"] != sum(len(face) for face in payload["faces"]):
        raise RuntimeError("MeshPayload loop_count differs from faces")
    if len(payload["loop_uvs"]) != payload["loop_count"]:
        raise RuntimeError("MeshPayload loop_uvs differs from loop_count")


def _edge_lookup(mesh: bpy.types.Mesh) -> dict[tuple[int, int], bpy.types.MeshEdge]:
    """Index compiled Blender edges by canonical vertex pair."""

    return {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))): edge
        for edge in mesh.edges
    }


def _require_edge(
    lookup: dict[tuple[int, int], bpy.types.MeshEdge],
    declaration: dict[str, Any],
) -> bpy.types.MeshEdge:
    """Resolve one declared payload edge or fail on topology drift."""

    key = tuple(int(value) for value in declaration["vertices"])
    edge = lookup.get(key)
    if edge is None:
        raise RuntimeError(f"MeshPayload references missing edge {key}")
    return edge


def _float_edge_attribute(mesh: bpy.types.Mesh, name: str) -> bpy.types.Attribute:
    """Create one bounded FLOAT/EDGE attribute for crease or bevel weights."""

    attribute = mesh.attributes.new(name=name, type="FLOAT", domain="EDGE")
    return attribute


def _apply_data_intent(
    obj: bpy.types.Object,
    payload: dict[str, Any],
    *,
    materialize_material_slots: bool = True,
) -> None:
    """Apply v2 data intent, optionally deferring material slots to SceneSpec build."""

    mesh = obj.data
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop_index, raw_uv in enumerate(payload["loop_uvs"]):
        uv = (float(raw_uv[0]), float(raw_uv[1]))
        if not all(math.isfinite(value) for value in uv):
            raise RuntimeError("MeshPayload contains non-finite loop UVs")
        uv_layer.data[loop_index].uv = uv

    if materialize_material_slots:
        for slot in payload["material_slots"]:
            material = bpy.data.materials.new(name=str(slot["material_id"]))
            material["cbm_material_id"] = str(slot["material_id"])
            obj.data.materials.append(material)
    for polygon, material_index, smooth in zip(
        mesh.polygons,
        payload["polygon_material_indices"],
        payload["smooth_polygon_flags"],
        strict=True,
    ):
        if materialize_material_slots:
            polygon.material_index = int(material_index)
        polygon.use_smooth = bool(smooth)

    lookup = _edge_lookup(mesh)
    smoothing = payload["smoothing_policy"]
    if smoothing["mode"] == "smooth_by_angle":
        threshold = math.radians(float(smoothing["angle_degrees"]))
        polygons_by_edge: dict[tuple[int, int], list[int]] = {}
        for polygon in mesh.polygons:
            for raw_key in polygon.edge_keys:
                key = tuple(sorted((int(raw_key[0]), int(raw_key[1]))))
                polygons_by_edge.setdefault(key, []).append(polygon.index)
        for key, edge in lookup.items():
            adjacent = polygons_by_edge.get(key, [])
            if len(adjacent) != 2:
                continue
            first = mesh.polygons[adjacent[0]].normal
            second = mesh.polygons[adjacent[1]].normal
            dot_value = max(-1.0, min(1.0, float(first.dot(second))))
            edge.use_edge_sharp = math.acos(dot_value) > threshold
    for declaration in payload["sharp_edges"]:
        _require_edge(lookup, declaration).use_edge_sharp = True
    for declaration in payload["uv_seams"]:
        _require_edge(lookup, declaration).use_seam = True
    for key, attribute_name in (
        ("edge_creases", "crease_edge"),
        ("bevel_weights", "bevel_weight_edge"),
    ):
        attribute = _float_edge_attribute(mesh, attribute_name)
        for declaration in payload[key]:
            edge = _require_edge(lookup, declaration)
            attribute.data[edge.index].value = float(declaration["weight"])

    for group in payload["face_groups"]:
        attribute = mesh.attributes.new(
            name=f"cbm_face_group__{group['id']}",
            type="BOOLEAN",
            domain="FACE",
        )
        for face_index in group["face_indices"]:
            attribute.data[int(face_index)].value = True

    for item in payload["custom_attribute_manifest"]:
        if item["domain"] == "OBJECT":
            obj[f"cbm_attr__{item['name']}"] = item["values"][0]
            continue
        attribute = mesh.attributes.new(
            name=str(item["name"]),
            type=str(item["data_type"]),
            domain=str(item["domain"]),
        )
        for destination, value in zip(attribute.data, item["values"], strict=True):
            destination.value = value


def _apply_modifier_intent(obj: bpy.types.Object, payload: dict[str, Any]) -> None:
    """Recreate only declared non-destructive effects and reject forbidden dispositions."""

    policies = {item["effect"]: item for item in payload["modifier_materialization_policy"]}
    if any(item["disposition"] == "reject" for item in policies.values()):
        raise RuntimeError("MeshPayload contains an explicitly rejected modifier effect")
    weighted = payload["weighted_normal_intent"]
    if weighted["enabled"]:
        if policies.get("weighted_normal", {}).get("disposition") != (
            "recreate_in_compiled_build"
        ):
            raise RuntimeError("weighted-normal intent lacks recreate policy")
        modifier = obj.modifiers.new(name="CBM_V02_WeightedNormal", type="WEIGHTED_NORMAL")
        modifier.keep_sharp = bool(weighted["keep_sharp"])
        if hasattr(modifier, "mode"):
            modifier.mode = str(weighted["weight_mode"])
    subdivision = payload["subdivision_intent"]
    if subdivision["enabled"]:
        if policies.get("subdivision", {}).get("disposition") != (
            "recreate_in_compiled_build"
        ):
            raise RuntimeError("subdivision intent lacks recreate policy")
        modifier = obj.modifiers.new(name="CBM_V02_Subdivision", type="SUBSURF")
        modifier.levels = int(subdivision["levels"])
        modifier.render_levels = int(subdivision["render_levels"])
        modifier.subdivision_type = str(subdivision["subdivision_type"])
        if hasattr(modifier, "boundary_smooth"):
            modifier.boundary_smooth = str(subdivision["boundary_smoothing"])


def _available(value: object) -> dict[str, Any]:
    """Wrap one exact canonical fingerprint as available survival evidence."""

    return {"status": "available", "sha256": _canonical_sha256(value), "reason": None}


def _corner_normals(mesh: bpy.types.Mesh) -> list[list[float]]:
    """Extract one rounded evaluated corner-normal vector per mesh loop."""

    mesh.update()
    normals = getattr(mesh, "corner_normals", None)
    if normals is not None and len(normals) == len(mesh.loops):
        return [
            [round(float(item.vector[axis]), 8) for axis in range(3)]
            for item in normals
        ]
    values: list[list[float]] = []
    for polygon in mesh.polygons:
        normal = [round(float(polygon.normal[axis]), 8) for axis in range(3)]
        values.extend([normal] * len(polygon.loop_indices))
    return values


def _surface_records(
    mesh: bpy.types.Mesh,
    material_ids: list[str],
) -> list[object]:
    """Build reorder-tolerant triangle records from position, UV, normal, and material."""

    mesh.calc_loop_triangles()
    uv_data = mesh.uv_layers[0].data
    corner_normals = _corner_normals(mesh)
    records: list[object] = []
    for triangle in mesh.loop_triangles:
        corners = []
        for vertex_index, loop_index in zip(
            triangle.vertices,
            triangle.loops,
            strict=True,
        ):
            vertex = mesh.vertices[vertex_index].co
            uv = uv_data[loop_index].uv
            corners.append(
                [
                    [round(float(vertex[axis]), 8) for axis in range(3)],
                    [round(float(uv[axis]), 8) for axis in range(2)],
                    corner_normals[loop_index],
                ]
            )
        rotations = [corners[index:] + corners[:index] for index in range(3)]
        records.append(
            {
                "corners": min(rotations, key=lambda value: json.dumps(value)),
                "material": material_ids[
                    int(mesh.polygons[triangle.polygon_index].material_index)
                ],
            }
        )
    return sorted(records, key=lambda value: json.dumps(value, sort_keys=True))


def _modifier_records(
    obj: bpy.types.Object,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Inspect recreated modifiers and retain baked-effect policy as explicit evidence."""

    records: list[dict[str, Any]] = []
    for policy in sorted(
        payload["modifier_materialization_policy"],
        key=lambda value: value["effect"],
    ):
        effect = str(policy["effect"])
        disposition = str(policy["disposition"])
        if disposition == "bake_into_mesh":
            records.append(
                {
                    "effect": effect,
                    "disposition": disposition,
                    "details_sha256": policy["details_sha256"],
                }
            )
            continue
        if effect == "weighted_normal":
            modifier = obj.modifiers.get("CBM_V02_WeightedNormal")
            if modifier is None or modifier.type != "WEIGHTED_NORMAL":
                raise RuntimeError("compiled weighted-normal modifier is missing")
            records.append(
                {
                    "effect": effect,
                    "disposition": disposition,
                    "type": modifier.type,
                    "keep_sharp": bool(modifier.keep_sharp),
                    "mode": str(modifier.mode) if hasattr(modifier, "mode") else None,
                }
            )
            continue
        if effect == "subdivision":
            modifier = obj.modifiers.get("CBM_V02_Subdivision")
            if modifier is None or modifier.type != "SUBSURF":
                raise RuntimeError("compiled subdivision modifier is missing")
            records.append(
                {
                    "effect": effect,
                    "disposition": disposition,
                    "type": modifier.type,
                    "levels": int(modifier.levels),
                    "render_levels": int(modifier.render_levels),
                    "subdivision_type": str(modifier.subdivision_type),
                    "boundary_smoothing": (
                        str(modifier.boundary_smooth)
                        if hasattr(modifier, "boundary_smooth")
                        else None
                    ),
                }
            )
            continue
        raise RuntimeError(f"unsupported recreated modifier effect: {effect}")
    return records


def _stage_snapshot(
    obj: bpy.types.Object,
    payload: dict[str, Any],
    *,
    job_root: Path,
    output_blend: Path,
) -> dict[str, Any]:
    """Capture the compiled candidate channels consumed by the survival API."""

    mesh = obj.data
    mesh.calc_loop_triangles()
    uv_values = [
        [round(float(item.uv[0]), 8), round(float(item.uv[1]), 8)]
        for item in mesh.uv_layers[0].data
    ]
    lookup = _edge_lookup(mesh)
    sharp = sorted(key for key, edge in lookup.items() if edge.use_edge_sharp)
    seams = sorted(key for key, edge in lookup.items() if edge.use_seam)
    crease = mesh.attributes.get("crease_edge")
    bevel = mesh.attributes.get("bevel_weight_edge")
    material_ids = [str(slot["material_id"]) for slot in payload["material_slots"]]
    material_surface_records = [
        {
            "positions": sorted(
                [
                    [round(float(mesh.vertices[index].co[axis]), 8) for axis in range(3)]
                    for index in triangle.vertices
                ]
            ),
            "material": material_ids[
                int(mesh.polygons[triangle.polygon_index].material_index)
            ],
        }
        for triangle in mesh.loop_triangles
    ]
    material_surface_records.sort(key=lambda value: json.dumps(value, sort_keys=True))
    custom_records = []
    for item in payload["custom_attribute_manifest"]:
        if item["domain"] == "OBJECT":
            values = [obj[f"cbm_attr__{item['name']}"]]
        else:
            values = [entry.value for entry in mesh.attributes[item["name"]].data]
        custom_records.append({"name": item["name"], "values": values})
    return {
        "schema_version": "0.1.0",
        "stage": "compiled_candidate",
        "artifact_path": output_blend.resolve().relative_to(job_root).as_posix(),
        "artifact_sha256": _sha256_file(output_blend),
        "source_fingerprint_sha256": payload["source_fingerprint_sha256"],
        "build_fingerprint_sha256": _canonical_sha256(payload),
        "semantic_id": payload["semantic_id"],
        "topology_profile": payload["source_geometry_intent"]["topology_profile"],
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
        "loop_count": len(mesh.loops),
        "evaluated_triangle_count": len(mesh.loop_triangles),
        "topology_fingerprint": _available(
            {
                "vertices": [list(vertex.co) for vertex in mesh.vertices],
                "faces": [list(polygon.vertices) for polygon in mesh.polygons],
            }
        ),
        "surface_equivalence_fingerprint": _available(
            _surface_records(mesh, material_ids)
        ),
        "uv_fingerprint": _available(uv_values),
        "material_slots_fingerprint": _available(
            sorted(material_ids)
        ),
        "polygon_material_fingerprint": _available(material_surface_records),
        "split_normal_fingerprint": _available(_corner_normals(mesh)),
        "sharp_edge_fingerprint": _available(sharp),
        "uv_seam_fingerprint": _available(seams),
        "crease_fingerprint": _available(
            [] if crease is None else [round(float(item.value), 8) for item in crease.data]
        ),
        "bevel_fingerprint": _available(
            [] if bevel is None else [round(float(item.value), 8) for item in bevel.data]
        ),
        "smoothing_fingerprint": _available(
            [bool(polygon.use_smooth) for polygon in mesh.polygons]
        ),
        "modifier_fingerprint": _available(_modifier_records(obj, payload)),
        "custom_attribute_fingerprint": _available(custom_records),
    }


def _write_json(path: Path, payload: object) -> None:
    """Publish one UTF-8 report after the compiled blend is complete."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    """Compile one exact payload, save a blend, and emit a strict stage snapshot."""

    args = _parse_args()
    job_root = Path(args.job_root).resolve()
    payload_path = _contained(args.payload, job_root, must_exist=True)
    output_blend = _contained(args.output_blend, job_root, must_exist=False)
    report_path = _contained(args.report, job_root, must_exist=False)
    if _sha256_file(payload_path) != args.payload_sha256:
        raise RuntimeError("MeshPayload 0.2 changed after host validation")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    _required_payload_shape(payload)
    if any(item.get("severity") == "error" for item in payload.get("findings", [])):
        raise RuntimeError("MeshPayload 0.2 has blocking findings")

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    mesh = bpy.data.meshes.new("CBM_MeshPayloadV02")
    mesh.from_pydata(payload["vertices"], [], payload["faces"])
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(str(payload["semantic_id"]), mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["cbm_id"] = str(payload["semantic_id"])
    obj["cbm_mesh_payload_version"] = "0.2.0"
    obj["cbm_source_fingerprint"] = str(payload["source_fingerprint_sha256"])
    _apply_data_intent(obj, payload)
    _apply_modifier_intent(obj, payload)
    mesh.update(calc_edges=True)
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    snapshot = _stage_snapshot(
        obj,
        payload,
        job_root=job_root,
        output_blend=output_blend,
    )
    _write_json(
        report_path,
        {
            "schema_version": "0.1.0",
            "status": "passed",
            "payload_path": payload_path.relative_to(job_root).as_posix(),
            "payload_file_sha256": args.payload_sha256,
            "snapshot": snapshot,
        },
    )


if __name__ == "__main__":
    main()
