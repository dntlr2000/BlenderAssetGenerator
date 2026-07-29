from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from artifact_render_common import configure_artifact_render  # noqa: E402
from render_qa_passes import (  # noqa: E402
    _camera_record,
    _flat_material,
    _render_pass,
    _set_black_world,
    _set_machine_color_management,
    _validated_build_provenance,
)

from codex_blender_modeler.blender_artifacts import (  # noqa: E402
    artifact_path,
    sha256_file,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    """Parse bounded subject-only diagnostic rendering arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--scene-spec", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--scene-spec-sha256", required=True)
    parser.add_argument("--camera-fingerprint", required=True)
    parser.add_argument("--role-map", required=True)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--render-engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _bounded_resolution(scene: bpy.types.Scene, maximum: int) -> tuple[int, int]:
    """Fit the existing camera aspect ratio into a bounded diagnostic resolution."""

    if maximum < 64 or maximum > 512:
        raise ValueError("fit diagnostic resolution must be within [64, 512]")
    width = int(scene.render.resolution_x)
    height = int(scene.render.resolution_y)
    scale = min(1.0, maximum / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _subject_ids(role_map_path: Path) -> set[str]:
    """Load only primary semantic IDs for subject silhouette fitting."""

    payload = json.loads(role_map_path.read_text(encoding="utf-8"))
    assignments = payload.get("assignments")
    if not isinstance(assignments, list):
        raise RuntimeError("background role map assignments are missing")
    return {
        str(item["object_id"])
        for item in assignments
        if isinstance(item, dict) and item.get("role") == "primary"
    }


def main() -> None:
    """Render one low-resolution primary-only silhouette without saving the blend."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    manifest = Path(args.manifest).expanduser().resolve()
    scene_spec = Path(args.scene_spec).expanduser().resolve()
    role_map = Path(args.role_map).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    configure_artifact_render(args.render_engine, args.render_device)
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("fit diagnostic requires the built comparison camera")
    scene_sha, camera_sha, build_sha = _validated_build_provenance(
        scene,
        scene.camera,
        scene_spec,
        expected_build_fingerprint=args.build_fingerprint,
        expected_scene_spec_sha256=args.scene_spec_sha256,
        expected_camera_fingerprint=args.camera_fingerprint,
    )
    width, height = _bounded_resolution(scene, int(args.resolution))
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    subjects = _subject_ids(role_map)
    if not subjects:
        raise RuntimeError("fit diagnostic role map has no primary semantic object")
    visible = []
    for item in scene.objects:
        if item.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
            continue
        identifier = str(item.get("cbm_id", item.name))
        item.hide_render = bool(item.hide_render) or identifier not in subjects
        if not item.hide_render:
            visible.append(identifier)
    if not visible:
        raise RuntimeError("fit diagnostic found no renderable primary semantic object")
    warnings: list[str] = []
    _set_black_world(scene)
    _set_machine_color_management(scene, warnings)
    override = _flat_material("CBM_Fit_Primary", (1.0, 1.0, 1.0, 1.0))
    _render_pass(scene, bpy.context.view_layer, output, override)
    bpy.context.view_layer.material_override = None
    write_json_atomic(
        manifest,
        {
            "schema_version": "0.8.0",
            "kind": "background_primary_fit",
            "scene_spec_sha256": scene_sha,
            "camera_fingerprint": camera_sha,
            "build_fingerprint": build_sha,
            "role_map_sha256": sha256_file(role_map),
            "primary_ids": sorted(set(visible)),
            "camera": _camera_record(scene.camera),
            "resolution": [width, height],
            "silhouette_path": artifact_path(output, manifest),
            "silhouette_sha256": sha256_file(output),
            "warnings": warnings,
        },
    )
    print(f"CBM_BACKGROUND_FIT_OK output={output} subjects={len(set(visible))}")


if __name__ == "__main__":
    main()
