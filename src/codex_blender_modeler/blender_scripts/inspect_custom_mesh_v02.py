"""Inspect one MeshPayload 0.2 object inside a completed SceneSpec build."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from compile_mesh_payload_v02 import (  # noqa: E402
    _contained,
    _required_payload_shape,
    _sha256_file,
    _stage_snapshot,
    _write_json,
)


def _parse_args() -> argparse.Namespace:
    """Parse only fixed job, payload, semantic, report, and exact-hash arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--payload-sha256", required=True)
    parser.add_argument("--semantic-id", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _find_object(semantic_id: str) -> bpy.types.Object:
    """Find exactly one built mesh carrying the requested stable semantic ID."""

    matches = [
        obj
        for obj in bpy.data.objects
        if str(obj.get("cbm_id", "")) == semantic_id and obj.type == "MESH"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one MeshPayload 0.2 object for {semantic_id}; found {len(matches)}"
        )
    return matches[0]


def _verify_material_slots(obj: bpy.types.Object, payload: dict) -> None:
    """Verify the built SceneSpec materials preserve exact v2 order and assignments."""

    expected_ids = [str(item["material_id"]) for item in payload["material_slots"]]
    actual_ids = [
        str(material.get("cbm_id", material.get("cbm_material_id", "")))
        for material in obj.data.materials
    ]
    if actual_ids != expected_ids:
        raise RuntimeError(
            f"built material slots differ from MeshPayload 0.2: {actual_ids!r}"
        )
    actual_indices = [int(polygon.material_index) for polygon in obj.data.polygons]
    if actual_indices != payload["polygon_material_indices"]:
        raise RuntimeError("built polygon materials differ from MeshPayload 0.2")


def main() -> None:
    """Validate one exact payload against the current blend and publish a snapshot."""

    args = _parse_args()
    job_root = Path(args.job_root).resolve()
    payload_path = _contained(args.payload, job_root, must_exist=True)
    report_path = _contained(args.report, job_root, must_exist=False)
    blend_path = Path(bpy.data.filepath).resolve()
    try:
        blend_path.relative_to(job_root)
    except ValueError as exc:
        raise RuntimeError("inspected SceneSpec build escapes job root") from exc
    if _sha256_file(payload_path) != args.payload_sha256:
        raise RuntimeError("MeshPayload 0.2 changed before built-scene inspection")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    _required_payload_shape(payload)
    obj = _find_object(args.semantic_id)
    if str(obj.get("cbm_mesh_payload_version", "")) != "0.2.0":
        raise RuntimeError("built object omitted MeshPayload 0.2 provenance")
    if str(obj.get("cbm_v02_payload_sha256", "")) != args.payload_sha256:
        raise RuntimeError("built object payload provenance is stale")
    _verify_material_slots(obj, payload)
    snapshot = _stage_snapshot(
        obj,
        payload,
        job_root=job_root,
        output_blend=blend_path,
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
