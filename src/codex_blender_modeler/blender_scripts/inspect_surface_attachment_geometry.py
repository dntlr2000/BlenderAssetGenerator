"""Fixed Blender 5.0.1 actual-triangle extraction for selected attachment checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from inspect_geometry_delivery_v02 import _stage_objects  # noqa: E402
from portable_asset_common import native_io_path, operator_kwargs  # noqa: E402

from codex_blender_modeler.build_provenance import (  # noqa: E402
    require_matching_build_provenance,
)


def sha256(path: Path) -> str:
    """Bind the actual inspected artifact before and after native extraction."""
    with open(native_io_path(path), "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(root: Path, value: str, *, exists: bool) -> Path:
    """Enforce contained native inputs/outputs without following linked components."""
    lexical = Path(value)
    if not lexical.is_absolute():
        lexical = root / lexical
    relative = lexical.relative_to(root)
    current = root
    for part in relative.parts:
        if part in {".", ".."}:
            raise ValueError("attachment extraction path contains traversal")
        current /= part
        if current.is_symlink():
            raise ValueError("attachment extraction path is linked")
    lexical.resolve().relative_to(root.resolve())
    if exists and not lexical.is_file():
        raise FileNotFoundError(lexical)
    return lexical


def parse_args() -> argparse.Namespace:
    """Accept only fixed artifacts, hashes and a bounded known extraction stage."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--source-fingerprint", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--intent-sha256", required=True)
    parser.add_argument(
        "--stage",
        choices=("native_evaluated", "optimized", "converted", "clean_import_glb"),
        required=True,
    )
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def main() -> None:
    """Read actual evaluated geometry, preserving full winding/material corner association."""
    args = parse_args()
    if bpy.app.version[:3] != (5, 0, 1):
        raise RuntimeError("Attachment extraction is verified only for Blender 5.0.1")
    root = Path(args.job_root).resolve()
    artifact = contained(root, args.artifact, exists=True)
    output = contained(root, args.output, exists=False)
    if output.exists():
        raise FileExistsError(output)
    if sha256(artifact) != args.artifact_sha256:
        raise ValueError("Attachment artifact changed before extraction")
    if args.stage == "clean_import_glb":
        if artifact.suffix.lower() != ".glb":
            raise ValueError("Attachment import requires actual GLB")
        bpy.ops.wm.read_factory_settings(use_empty=True)
        op = bpy.ops.import_scene.gltf
        op(**operator_kwargs(op, {"filepath": native_io_path(artifact)}))
        stage = "clean_import_glb"
    else:
        if Path(bpy.data.filepath).resolve() != artifact:
            raise ValueError("Loaded blend differs from exact requested artifact")
        embedded = require_matching_build_provenance(
            str(bpy.context.scene.get("cbm_build_provenance", "{}")),
            args.build_fingerprint,
            operation="surface attachment inspection",
        )
        if (
            embedded.get("fingerprint") != args.build_fingerprint
            or embedded.get("attachment_intent", {}).get("sha256") != args.intent_sha256
        ):
            raise ValueError("Loaded blend has stale or missing selected attachment provenance")
        if args.stage in {"optimized", "converted"} and (
            bpy.context.scene.get("cbm_portable_source_build_fingerprint") != args.build_fingerprint
        ):
            raise ValueError("Derived scene source build fingerprint changed")
        stage = "promoted_canonical" if args.stage == "native_evaluated" else "optimized_lod0"
    objects = _stage_objects(stage)
    if len(objects) > 128:
        raise ValueError("Attachment extraction object limit exceeded")
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    records, total = [], 0
    for obj in objects:
        if obj.get("cbm_instance_index") not in (None, 0):
            raise ValueError("Attachment extraction does not support generated instances")
        evaluated = obj.evaluated_get(dependency_graph)
        mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=dependency_graph)
        try:
            mesh.calc_loop_triangles()
            total += len(mesh.loop_triangles)
            if total > 25000:
                raise ValueError("Attachment extraction triangle limit exceeded")
            triangles = []
            for tri in mesh.loop_triangles:
                corners = [
                    tuple(float(x) for x in (evaluated.matrix_world @ mesh.vertices[i].co))
                    for i in tri.vertices
                ]
                if any(not math.isfinite(x) or abs(x) > 1e6 for p in corners for x in p):
                    raise ValueError("Attachment extraction has invalid world positions")
                index = int(tri.material_index)
                if not 0 <= index < len(mesh.materials) or mesh.materials[index] is None:
                    raise ValueError("Attachment triangle has no material")
                material = mesh.materials[index]
                material_id = str(material.get("cbm_id", ""))
                if not material_id:
                    raise ValueError("Attachment triangle material has no stable identity")
                triangles.append({"corners": corners, "material_id": material_id})
            records.append({"semantic_id": str(obj["cbm_id"]), "triangles": triangles})
        finally:
            evaluated.to_mesh_clear()
    if sha256(artifact) != args.artifact_sha256:
        raise ValueError("Attachment artifact changed during extraction")
    payload = {
        "schema_version": "0.1.0",
        "kind": "surface_attachment_actual_triangles",
        "blender_version": "5.0.1",
        "stage": args.stage,
        "artifact": {
            "path": artifact.relative_to(root).as_posix(),
            "sha256": args.artifact_sha256,
        },
        "source_fingerprint": args.source_fingerprint,
        "build_fingerprint": args.build_fingerprint,
        "intent_sha256": args.intent_sha256,
        "triangle_count": total,
        "objects": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(native_io_path(output), "x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
