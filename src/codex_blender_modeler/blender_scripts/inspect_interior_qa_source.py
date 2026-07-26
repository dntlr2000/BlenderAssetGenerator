"""Inspect current approved interior objects without modifying the authoring blend."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from portable_asset_common import object_inventory  # noqa: E402
from render_qa_passes import _validated_build_provenance  # noqa: E402

from codex_blender_modeler.blender_artifacts import (  # noqa: E402
    sha256_file,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    """Parse exact source hashes and selected semantic IDs for read-only inspection."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--scene-spec", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--scene-spec-sha256", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--scope-approval", required=True)
    parser.add_argument("--scope-approval-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--target-id", action="append", default=[])
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _require_file_hash(path: Path, expected: str, label: str) -> None:
    """Reject a missing or changed approval-bound source file."""

    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} hash changed: expected={expected} actual={actual}")


def _selected_object_record(obj: bpy.types.Object) -> dict:
    """Project the portable Blender inventory onto the strict interior-QA contract."""

    record = object_inventory(obj, include_topology=True)
    return {
        "name": record["name"],
        "type": record["type"],
        "semantic_id": str(record["semantic_id"]),
        "instance_index": record.get("instance_index"),
        "bbox_world": record["bbox_world"],
        "dimensions": record["dimensions"],
        "material_ids": record["material_ids"],
        "topology": record.get("topology"),
    }


def main() -> None:
    """Validate current build provenance and persist fresh interior bounds/topology evidence."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    scene_spec = Path(args.scene_spec).expanduser().resolve()
    scope = Path(args.scope).expanduser().resolve()
    approval = Path(args.scope_approval).expanduser().resolve()
    _require_file_hash(scope, args.scope_sha256, "InteriorScope")
    _require_file_hash(
        approval,
        args.scope_approval_sha256,
        "InteriorScope approval",
    )

    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("Interior QA source inspection requires the canonical camera")
    scene_hash, _camera_hash, build_fingerprint = _validated_build_provenance(
        scene,
        scene.camera,
        scene_spec,
        expected_build_fingerprint=args.build_fingerprint,
        expected_scene_spec_sha256=args.scene_spec_sha256,
        expected_camera_fingerprint=None,
    )
    target_ids = sorted(set(str(value) for value in args.target_id if str(value)))
    if not target_ids:
        raise ValueError("Interior QA source inspection requires at least one target ID")
    selected = [
        obj
        for obj in sorted(scene.objects, key=lambda item: item.name)
        if obj.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}
        and str(obj.get("cbm_id", "")) in target_ids
    ]
    found_ids = {str(obj.get("cbm_id")) for obj in selected}
    payload = {
        "schema_version": "0.6.0",
        "job_id": str(scene.get("cbm_job_id") or "__unknown__"),
        "run_id": args.run_id,
        "scene_spec_sha256": scene_hash,
        "build_fingerprint": build_fingerprint,
        "interior_scope_sha256": args.scope_sha256,
        "interior_scope_approval_sha256": args.scope_approval_sha256,
        "blender_version": bpy.app.version_string,
        "objects": [_selected_object_record(obj) for obj in selected],
        "missing_target_ids": sorted(set(target_ids) - found_ids),
        "warnings": [],
    }
    write_json_atomic(output, payload)
    print(
        "CBM_INTERIOR_QA_SOURCE_OK "
        f"objects={len(selected)} missing={len(payload['missing_target_ids'])}"
    )


if __name__ == "__main__":
    main()
