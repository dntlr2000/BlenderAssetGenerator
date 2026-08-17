"""Materialize one strict structural candidate without arbitrary Python execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import bpy

BLENDER_SCRIPTS = Path(__file__).resolve().parent
PACKAGE_SRC = Path(__file__).resolve().parents[2]
for import_root in (BLENDER_SCRIPTS, PACKAGE_SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from builders.structural_registry import create_structural_geometry  # noqa: E402
from geometry_intent_runtime import apply_geometry_intent  # noqa: E402


def _parse_args() -> argparse.Namespace:
    """Parse the fixed materializer's bounded file arguments after Blender's separator."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--output-mesh", required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument(
        "--mesh-payload-version",
        choices=("0.1.0", "0.2.0"),
        default="0.1.0",
    )
    parser.add_argument("--material-id")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _contained_file(path: str, job_root: Path, *, must_exist: bool) -> Path:
    """Resolve one file inside the active job root and enforce expected existence."""

    resolved = Path(path).resolve()
    try:
        resolved.relative_to(job_root)
    except ValueError as exc:
        raise RuntimeError("structural materializer path escapes job root") from exc
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _canonical_sha256(value: Any) -> str:
    """Hash one JSON-compatible value with deterministic compact serialization."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _mesh_payload(obj: bpy.types.Object, candidate: dict) -> dict[str, Any]:
    """Extract the unchanged legacy 0.1 base-mesh payload representation."""

    mesh = obj.data
    vertices = [
        [float(vertex.co.x), float(vertex.co.y), float(vertex.co.z)]
        for vertex in mesh.vertices
    ]
    faces = [[int(value) for value in polygon.vertices] for polygon in mesh.polygons]
    findings = json.loads(str(obj.get("cbm_structural_findings", "[]")))
    return {
        "schema_version": "0.1.0",
        "semantic_id": candidate["semantic_id"],
        "builder_kind": candidate["geometry"]["kind"],
        "vertices": vertices,
        "faces": faces,
        "loop_uvs": None,
        "geometry_intent": candidate.get("geometry_intent"),
        "findings": findings,
    }


def _file_sha256(path: Path) -> str:
    """Hash one exact materializer source without normalizing its bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _v02_smoothing(intent: dict[str, Any]) -> dict[str, Any]:
    """Normalize the legacy GeometryIntent smoothing policy for MeshPayload 0.2."""

    policy = intent.get("smoothing_policy")
    if not isinstance(policy, dict):
        raise RuntimeError("MeshPayload 0.2 requires an explicit smoothing policy")
    mode = str(policy.get("mode", "legacy"))
    if mode not in {"flat", "smooth_by_angle", "weighted_normals"}:
        raise RuntimeError("MeshPayload 0.2 rejects legacy or unknown smoothing policy")
    return {
        "mode": mode,
        "angle_degrees": (
            float(policy.get("angle_degrees", 30.0))
            if mode == "smooth_by_angle"
            else None
        ),
        "keep_explicit_sharp": bool(policy.get("keep_sharp", True)),
    }


def _v02_weighted_normal(smoothing: dict[str, Any]) -> dict[str, Any]:
    """Translate weighted-normal intent into the bounded recreation contract."""

    enabled = smoothing["mode"] == "weighted_normals"
    return {
        "enabled": enabled,
        "keep_sharp": smoothing["keep_explicit_sharp"],
        "weight_mode": "FACE_AREA_WITH_ANGLE",
        "disposition": "recreate_in_compiled_build" if enabled else "reject",
    }


def _v02_subdivision(intent: dict[str, Any]) -> dict[str, Any]:
    """Translate subdivision intent without applying or inventing topology settings."""

    source = intent.get("subdivision_intent")
    if not isinstance(source, dict):
        source = {}
    enabled = bool(source.get("enabled", False))
    levels = int(source.get("levels", 0))
    return {
        "enabled": enabled,
        "levels": levels,
        "render_levels": levels,
        "subdivision_type": "CATMULL_CLARK",
        "boundary_smoothing": (
            "PRESERVE_CORNERS"
            if source.get("boundary_smoothing", "preserve_corners")
            == "preserve_corners"
            else "ALL"
        ),
        "disposition": "recreate_in_compiled_build" if enabled else "reject",
    }


def _v02_disposition(
    effect: str,
    disposition: str,
    *,
    source_id: str,
    details: object,
) -> dict[str, Any]:
    """Bind one fixed materialization disposition to its normalized details hash."""

    return {
        "effect": effect,
        "disposition": disposition,
        "source_id": source_id,
        "details_sha256": _canonical_sha256(details),
    }


def _v02_source_intent(
    candidate: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize source GeometryIntent exactly as the host v2 classifier does."""

    intent = candidate.get("geometry_intent")
    if not isinstance(intent, dict):
        raise RuntimeError("MeshPayload 0.2 materialization requires GeometryIntent")
    smoothing = _v02_smoothing(intent)
    weighted = _v02_weighted_normal(smoothing)
    subdivision = _v02_subdivision(intent)
    normalized = {
        "face_groups": intent.get("face_groups", []),
        "material_assignments": [],
        "sharp_edges": intent.get("sharp_edges", []),
        "uv_seams": intent.get("uv_seams", []),
        "edge_creases": intent.get("crease_edges", []),
        "bevel_weights": intent.get("bevel_weights", []),
        "smoothing_policy": smoothing,
        "topology_profile": intent.get("topology_policy", "static_prop_closed"),
        "weighted_normal_intent": weighted,
        "subdivision_intent": subdivision,
    }
    source_intent = {
        "source_intent_sha256": _canonical_sha256(normalized),
        **normalized,
    }
    builder_kind = str(candidate["geometry"]["kind"])
    policies: list[dict[str, Any]] = []
    if builder_kind == "boolean_tree":
        policies.append(
            _v02_disposition(
                "boolean",
                "bake_into_mesh",
                source_id="builder.boolean_tree",
                details={"builder_kind": builder_kind},
            )
        )
    if builder_kind == "geometry_nodes_template":
        policies.append(
            _v02_disposition(
                "geometry_nodes",
                "bake_into_mesh",
                source_id="builder.geometry_nodes_template",
                details={"builder_kind": builder_kind},
            )
        )
    if weighted["enabled"]:
        policies.append(
            _v02_disposition(
                "weighted_normal",
                "recreate_in_compiled_build",
                source_id="intent.smoothing_policy",
                details=weighted,
            )
        )
    if subdivision["enabled"]:
        policies.append(
            _v02_disposition(
                "subdivision",
                "recreate_in_compiled_build",
                source_id="intent.subdivision_intent",
                details=subdivision,
            )
        )
    return source_intent, policies


def _operator_keywords(operator: object, candidates: dict[str, Any]) -> dict[str, Any]:
    """Filter bounded UV operator arguments against the running Blender API."""

    identifiers = {item.identifier for item in operator.get_rna_type().properties}
    return {name: value for name, value in candidates.items() if name in identifiers}


def _unwrap_declared_uv_seams(obj: bpy.types.Object) -> None:
    """Create one deterministic packed UV layout from validated seam declarations."""

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        if not bpy.ops.uv.unwrap.poll():
            raise RuntimeError("UV unwrap operator is unavailable in the active context")
        unwrap_result = bpy.ops.uv.unwrap(
            **_operator_keywords(
                bpy.ops.uv.unwrap,
                {
                    "method": "ANGLE_BASED",
                    "fill_holes": True,
                    "correct_aspect": True,
                    "use_subsurf_data": False,
                    "margin": 0.02,
                },
            )
        )
        if "FINISHED" not in unwrap_result:
            raise RuntimeError(f"UV unwrap returned {sorted(unwrap_result)}")
        if not bpy.ops.uv.pack_islands.poll():
            raise RuntimeError("UV pack operator is unavailable in the active context")
        pack_result = bpy.ops.uv.pack_islands(
            **_operator_keywords(
                bpy.ops.uv.pack_islands,
                {
                    "rotate": True,
                    "scale": True,
                    "margin": 0.02,
                },
            )
        )
        if "FINISHED" not in pack_result:
            raise RuntimeError(f"UV pack returned {sorted(pack_result)}")
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")


def _degenerate_uv_triangle_count(
    mesh: bpy.types.Mesh,
    layer: bpy.types.MeshUVLoopLayer,
) -> int:
    """Count loop triangles whose active UV coordinates have effectively zero area."""

    mesh.calc_loop_triangles()
    count = 0
    for triangle in mesh.loop_triangles:
        first, second, third = (layer.data[index].uv for index in triangle.loops)
        area_twice = abs(
            (second.x - first.x) * (third.y - first.y)
            - (second.y - first.y) * (third.x - first.x)
        )
        if area_twice <= 1.0e-12:
            count += 1
    return count


def _ensure_v02_loop_uvs(
    obj: bpy.types.Object,
) -> tuple[list[list[float]], str]:
    """Preserve authored UVs or generate seam-aware/legacy fallback loop UVs."""

    mesh = obj.data
    layer = mesh.uv_layers.active
    generation = "preserved"
    if layer is None:
        layer = mesh.uv_layers.new(name="UVMap")
        mesh.uv_layers.active = layer
        layer.active_render = True
        if any(edge.use_seam for edge in mesh.edges):
            _unwrap_declared_uv_seams(obj)
            layer = mesh.uv_layers.active
            if layer is None:
                raise RuntimeError("declared-seam UV unwrap removed the active UV layer")
            generation = "seam_unwrap"
            degenerate_count = _degenerate_uv_triangle_count(mesh, layer)
            if degenerate_count:
                raise RuntimeError(
                    "declared-seam UV unwrap produced "
                    f"{degenerate_count} degenerate triangles"
                )
        else:
            generation = "planar_fallback"
        if generation == "planar_fallback":
            coordinates = [
                [float(vertex.co[axis]) for axis in range(3)]
                for vertex in mesh.vertices
            ]
            extents = [
                max(item[axis] for item in coordinates)
                - min(item[axis] for item in coordinates)
                for axis in range(3)
            ]
            axes = sorted(range(3), key=lambda axis: (-extents[axis], axis))[:2]
            bounds = [
                (
                    min(item[axis] for item in coordinates),
                    max(item[axis] for item in coordinates),
                )
                for axis in axes
            ]
            for loop in mesh.loops:
                vertex = mesh.vertices[loop.vertex_index].co
                uv = []
                for axis, (minimum, maximum) in zip(axes, bounds, strict=True):
                    span = maximum - minimum
                    uv.append(
                        0.5
                        if span <= 1.0e-12
                        else (float(vertex[axis]) - minimum) / span
                    )
                layer.data[loop.index].uv = uv
    result = []
    for item in layer.data:
        uv = [float(item.uv[0]), float(item.uv[1])]
        if not all(math.isfinite(value) for value in uv):
            raise RuntimeError("materialized MeshPayload 0.2 contains non-finite loop UVs")
        result.append(uv)
    return result, generation


def _mesh_payload_v02(
    obj: bpy.types.Object,
    candidate: dict[str, Any],
    *,
    candidate_path: Path,
    job_root: Path,
    material_id: str,
) -> dict[str, Any]:
    """Extract a strict-ready MeshPayload 0.2 from actual materialized Blender data."""

    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", material_id) is None:
        raise RuntimeError("MeshPayload 0.2 material ID is not stable")
    mesh = obj.data
    mesh.update(calc_edges=True)
    loop_uvs, uv_generation = _ensure_v02_loop_uvs(obj)
    source_intent, policies = _v02_source_intent(candidate)
    material = bpy.data.materials.new(name=material_id)
    material["cbm_material_id"] = material_id
    mesh.materials.append(material)
    for polygon in mesh.polygons:
        polygon.material_index = 0
    findings = json.loads(str(obj.get("cbm_structural_findings", "[]")))
    if uv_generation == "planar_fallback":
        findings.append(
            {
                "code": "generated_planar_uv_fallback",
                "severity": "warning",
                "message": (
                    "No structural UV evidence existed; materialization generated one "
                    "deterministic planar UVMap without unwrap-quality claims."
                ),
            }
        )
    elif uv_generation == "seam_unwrap":
        findings.append(
            {
                "code": "generated_declared_seam_uv",
                "severity": "info",
                "message": (
                    "Materialization generated one deterministic packed UVMap from "
                    "the candidate's validated seam declarations."
                ),
            }
        )
    source_hashes = [
        {
            "role": "structural_candidate",
            "path": candidate_path.relative_to(job_root).as_posix(),
            "sha256": _file_sha256(candidate_path),
        }
    ]
    return {
        "schema_version": "0.2.0",
        "semantic_id": candidate["semantic_id"],
        "builder_kind": candidate["geometry"]["kind"],
        "vertices": [
            [float(vertex.co.x), float(vertex.co.y), float(vertex.co.z)]
            for vertex in mesh.vertices
        ],
        "faces": [
            [int(value) for value in polygon.vertices] for polygon in mesh.polygons
        ],
        "loop_count": len(mesh.loops),
        "loop_uvs": loop_uvs,
        "material_slots": [{"slot_index": 0, "material_id": material_id}],
        "polygon_material_indices": [0 for _polygon in mesh.polygons],
        "sharp_edges": source_intent["sharp_edges"],
        "uv_seams": source_intent["uv_seams"],
        "edge_creases": source_intent["edge_creases"],
        "bevel_weights": source_intent["bevel_weights"],
        "face_groups": source_intent["face_groups"],
        "smooth_polygon_flags": [
            bool(polygon.use_smooth) for polygon in mesh.polygons
        ],
        "smoothing_policy": source_intent["smoothing_policy"],
        "custom_attribute_manifest": [],
        "modifier_materialization_policy": policies,
        "weighted_normal_intent": source_intent["weighted_normal_intent"],
        "subdivision_intent": source_intent["subdivision_intent"],
        "source_geometry_intent": source_intent,
        "findings": findings,
        "source_hashes": source_hashes,
        "source_fingerprint_sha256": _canonical_sha256(source_hashes),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write one UTF-8 JSON artifact only after successful materialization."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Build, intent-tag, inspect, save, and report one structural candidate."""

    args = _parse_args()
    job_root = Path(args.job_root).resolve()
    candidate_path = _contained_file(args.candidate, job_root, must_exist=True)
    output_mesh = _contained_file(args.output_mesh, job_root, must_exist=False)
    output_blend = _contained_file(args.output_blend, job_root, must_exist=False)
    report_path = _contained_file(args.report, job_root, must_exist=False)
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    actual_hash = _canonical_sha256(candidate)
    if actual_hash != args.candidate_sha256:
        raise RuntimeError("structural candidate changed after host validation")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    obj = create_structural_geometry(candidate["geometry"], job_root)
    obj.name = str(candidate["semantic_id"])
    obj["cbm_id"] = str(candidate["semantic_id"])
    apply_geometry_intent(obj, candidate.get("geometry_intent"))
    if args.mesh_payload_version == "0.2.0":
        if not args.material_id:
            raise RuntimeError("MeshPayload 0.2 materialization requires --material-id")
        payload = _mesh_payload_v02(
            obj,
            candidate,
            candidate_path=candidate_path,
            job_root=job_root,
            material_id=args.material_id,
        )
    else:
        payload = _mesh_payload(obj, candidate)
    _write_json(output_mesh, payload)
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    report = {
        "schema_version": "0.1.0",
        "status": "passed",
        "semantic_id": candidate["semantic_id"],
        "builder_kind": candidate["geometry"]["kind"],
        "candidate_sha256": actual_hash,
        "mesh_sha256": hashlib.sha256(output_mesh.read_bytes()).hexdigest(),
        "blend_sha256": hashlib.sha256(output_blend.read_bytes()).hexdigest(),
        "vertex_count": len(payload["vertices"]),
        "polygon_count": len(payload["faces"]),
    }
    if args.mesh_payload_version == "0.2.0":
        report["mesh_payload_version"] = "0.2.0"
    _write_json(report_path, report)


if __name__ == "__main__":
    main()
