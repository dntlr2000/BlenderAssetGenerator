from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path, PurePosixPath

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import uv_layer_metrics  # noqa: E402
from standard_custom_mesh_runtime import (  # noqa: E402
    ordered_corner_topology_sha256,
    validate_standard_custom_mesh_payload,
)


def parse_args() -> argparse.Namespace:
    """Parse one hash-bound approved-UV extraction request."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-scene-spec", required=True)
    parser.add_argument("--source-scene-spec-sha256", required=True)
    parser.add_argument("--source-blend", required=True)
    parser.add_argument("--source-blend-sha256", required=True)
    parser.add_argument("--object-id", required=True)
    parser.add_argument("--uv-set", required=True)
    parser.add_argument("--expected-coordinate-fingerprint", required=True)
    parser.add_argument("--expected-binding-fingerprint", required=True)
    parser.add_argument("--expected-vertex-count", required=True, type=int)
    parser.add_argument("--expected-polygon-count", required=True, type=int)
    parser.add_argument("--expected-corner-count", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _sha256_file(path: Path) -> str:
    """Hash one exact source or generated artifact without normalizing its bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained_path(
    root: Path,
    raw_path: str,
    *,
    label: str,
    required_prefix: str,
) -> Path:
    """Resolve one normalized path below an explicitly allowed job-relative prefix."""

    if (
        not raw_path
        or raw_path != raw_path.replace("\\", "/")
        or raw_path.startswith("/")
        or ":" in raw_path
    ):
        raise RuntimeError(f"{label} must be a normalized job-relative path")
    parts = PurePosixPath(raw_path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError(f"{label} contains an unsafe path segment")
    normalized_prefix = required_prefix.rstrip("/")
    if raw_path != normalized_prefix and not raw_path.startswith(
        f"{normalized_prefix}/"
    ):
        raise RuntimeError(f"{label} must remain below {normalized_prefix}/")
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{label} escapes the job root") from exc
    return candidate


def _float32(value: float) -> float:
    """Round one SceneSpec scalar exactly as Blender mesh storage does."""

    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


def _write_new_json(path: Path, payload: dict[str, object]) -> None:
    """Create one immutable JSON artifact and fail if its destination already exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _source_object(scene_spec: dict[str, object], object_id: str) -> dict[str, object]:
    """Resolve exactly one inline custom-mesh object from the approved SceneSpec."""

    raw_objects = scene_spec.get("objects")
    if not isinstance(raw_objects, list):
        raise RuntimeError("Source SceneSpec objects must be an array")
    matches = [
        item
        for item in raw_objects
        if isinstance(item, dict) and item.get("id") == object_id
    ]
    if len(matches) != 1:
        raise RuntimeError("Source SceneSpec must contain exactly one target object")
    geometry = matches[0].get("geometry")
    if (
        not isinstance(geometry, dict)
        or geometry.get("kind") != "custom_mesh"
        or geometry.get("path") is not None
        or not isinstance(geometry.get("vertices"), list)
        or not isinstance(geometry.get("faces"), list)
    ):
        raise RuntimeError("Source object must use one inline custom_mesh payload")
    return matches[0]


def _blender_object(object_id: str) -> bpy.types.Object:
    """Resolve exactly one source mesh by stable semantic identity."""

    matches = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and (str(obj.get("cbm_id", "")) == object_id or obj.name == object_id)
    ]
    if len(matches) != 1:
        raise RuntimeError("Loaded Blend must contain exactly one target semantic mesh")
    return matches[0]


def main() -> None:
    """Extract approved loop UVs only after verifying exact source bytes and topology."""

    args = parse_args()
    root = Path(args.job_root).expanduser().resolve()
    if not root.is_dir() or root.name != args.job_id:
        raise RuntimeError("job-root identity does not match job-id")
    source_spec_path = _contained_path(
        root,
        args.source_scene_spec,
        label="source SceneSpec",
        required_prefix="history",
    )
    source_blend_path = _contained_path(
        root,
        args.source_blend,
        label="source Blend",
        required_prefix="history",
    )
    output_path = _contained_path(
        root,
        args.output,
        label="payload output",
        required_prefix="geometry",
    )
    receipt_path = _contained_path(
        root,
        args.receipt,
        label="extraction receipt",
        required_prefix="history/geometry_revision_plans",
    )
    if output_path.exists() or receipt_path.exists():
        raise RuntimeError("Standard extraction outputs are immutable and already exist")
    if not source_spec_path.is_file() or not source_blend_path.is_file():
        raise FileNotFoundError("Standard extraction source is missing")
    if _sha256_file(source_spec_path) != args.source_scene_spec_sha256:
        raise RuntimeError("source SceneSpec hash does not match the request")
    if _sha256_file(source_blend_path) != args.source_blend_sha256:
        raise RuntimeError("source Blend hash does not match the request")
    loaded_blend = Path(bpy.data.filepath).resolve()
    if loaded_blend != source_blend_path:
        raise RuntimeError("Blender loaded a different source Blend")

    try:
        source_spec = json.loads(source_spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Source SceneSpec is not valid JSON") from exc
    if source_spec.get("job_id") != args.job_id:
        raise RuntimeError("Source SceneSpec job_id differs from the request")
    source_object = _source_object(source_spec, args.object_id)
    source_geometry = source_object["geometry"]
    vertices = source_geometry["vertices"]
    faces = source_geometry["faces"]

    obj = _blender_object(args.object_id)
    mesh = obj.data
    observed_faces = [list(polygon.vertices) for polygon in mesh.polygons]
    observed_vertices = [list(vertex.co) for vertex in mesh.vertices]
    expected_vertices = [
        [_float32(value) for value in vertex]
        for vertex in vertices
    ]
    if observed_faces != faces or observed_vertices != expected_vertices:
        raise RuntimeError("Loaded Blend topology differs from the approved SceneSpec")
    if (
        len(mesh.vertices) != args.expected_vertex_count
        or len(mesh.polygons) != args.expected_polygon_count
        or len(mesh.loops) != args.expected_corner_count
    ):
        raise RuntimeError("Loaded Blend topology counts differ from the request")
    uv_layer = mesh.uv_layers.get(args.uv_set)
    if uv_layer is None:
        raise RuntimeError("Requested approved UV set is missing")
    metrics = uv_layer_metrics(mesh, uv_layer)
    if (
        metrics["coordinate_fingerprint"]
        != args.expected_coordinate_fingerprint
        or metrics["vertex_uv_binding_fingerprint"]
        != args.expected_binding_fingerprint
        or metrics["coordinate_count"] != args.expected_corner_count
        or metrics["non_finite_coordinate_count"] != 0
    ):
        raise RuntimeError("Loaded Blend UV identity differs from the request")
    loop_uvs = [
        [float(item.uv.x), float(item.uv.y)]
        for item in uv_layer.data
    ]
    payload = validate_standard_custom_mesh_payload(
        {
            "payload_kind": "standard_custom_mesh",
            "schema_version": "0.1.0",
            "job_id": args.job_id,
            "object_id": args.object_id,
            "source_scene_spec_path": args.source_scene_spec,
            "source_scene_spec_sha256": args.source_scene_spec_sha256,
            "source_blend_path": args.source_blend,
            "source_blend_sha256": args.source_blend_sha256,
            "vertices": vertices,
            "faces": faces,
            "loop_uvs": loop_uvs,
            "uv_set": args.uv_set,
            "source_coordinate_fingerprint": metrics["coordinate_fingerprint"],
            "source_vertex_uv_binding_fingerprint": metrics[
                "vertex_uv_binding_fingerprint"
            ],
            "ordered_corner_topology_sha256": ordered_corner_topology_sha256(faces),
        }
    )
    _write_new_json(output_path, payload)
    payload_sha256 = _sha256_file(output_path)
    receipt = {
        "schema_version": "standard-custom-mesh-extraction-receipt-0.1.0",
        "job_id": args.job_id,
        "object_id": args.object_id,
        "status": "passed",
        "canonical_write_performed": False,
        "source_scene_spec_path": args.source_scene_spec,
        "source_scene_spec_sha256": args.source_scene_spec_sha256,
        "source_blend_path": args.source_blend,
        "source_blend_sha256": args.source_blend_sha256,
        "payload_path": args.output,
        "payload_sha256": payload_sha256,
        "uv_set": args.uv_set,
        "vertex_count": len(mesh.vertices),
        "polygon_count": len(mesh.polygons),
        "ordered_polygon_corner_count": len(mesh.loops),
        "ordered_corner_topology_sha256": payload[
            "ordered_corner_topology_sha256"
        ],
        "uv_metrics": metrics,
        "runtime": {
            "blender_version": bpy.app.version_string,
            "autoexec_disabled": True,
        },
    }
    _write_new_json(receipt_path, receipt)
    print(
        "CBM_STANDARD_CUSTOM_MESH_EXTRACT_OK "
        f"object={args.object_id} payload={output_path} receipt={receipt_path}"
    )


if __name__ == "__main__":
    main()
