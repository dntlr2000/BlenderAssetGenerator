"""Materialize one strict structural candidate without arbitrary Python execution."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    """Extract stable base-mesh vertices, polygons, intent, and builder findings."""

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
    _write_json(report_path, report)


if __name__ == "__main__":
    main()
