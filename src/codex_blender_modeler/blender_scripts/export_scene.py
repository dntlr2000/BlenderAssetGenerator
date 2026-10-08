from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from compat import export_obj  # noqa: E402
from optical_volume_runtime import (  # noqa: E402
    validate_optical_volume_objects,
    verify_exported_optical_volume,
)


def parse_args() -> argparse.Namespace:
    """Parse one bounded raw-export format and destination."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--format", required=True, choices=["glb", "gltf", "obj", "fbx"])
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def gltf_apply_modifiers() -> bool:
    """Evaluate static modifiers while preserving legacy glTF shape-key export behavior."""

    has_shape_keys = any(
        obj.type == "MESH" and obj.data.shape_keys is not None for obj in bpy.data.objects
    )
    if has_shape_keys:
        # Blender's apply option prevents morph export, so retain the previous
        # scene-wide behavior instead of silently dropping existing shape keys.
        print(
            "CBM_EXPORT_WARNING code=SHAPE_KEYS_PRESERVE_LEGACY "
            "glTF modifier evaluation is disabled to preserve shape keys; "
            "active mesh modifiers may be absent from this raw export"
        )
    return not has_shape_keys


def raw_export_objects(format_name):
    """Match actual all-scene glTF or active-scene interchange object scope."""
    if format_name in {"glb", "gltf"} and hasattr(bpy.data, "scenes"):
        return list({obj.name: obj for scene in bpy.data.scenes for obj in scene.objects}.values())
    scene = getattr(getattr(bpy, "context", None), "scene", None)
    return list(scene.objects) if scene is not None else list(bpy.data.objects)


def main() -> None:
    """Export evaluated static geometry without saving or changing the authoring blend."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    optics = validate_optical_volume_objects(raw_export_objects(args.format))
    optical_active = bool(optics)
    if optics and args.format not in {"glb", "gltf"}:
        raise ValueError("Opt-in optical volume export currently requires glTF/GLB")
    if optics and not gltf_apply_modifiers():
        raise ValueError("Optical-volume raw export refuses the mixed shape-key modifier branch")
    operator = ""
    if args.format == "glb":
        bpy.ops.export_scene.gltf(
            filepath=str(output),
            export_format="GLB",
            use_selection=False,
            export_apply=gltf_apply_modifiers(),
        )
        operator = "bpy.ops.export_scene.gltf(GLB)"
    elif args.format == "gltf":
        bpy.ops.export_scene.gltf(
            filepath=str(output),
            export_format="GLTF_SEPARATE",
            use_selection=False,
            export_apply=gltf_apply_modifiers(),
        )
        operator = "bpy.ops.export_scene.gltf(GLTF_SEPARATE)"
    elif args.format == "fbx":
        bpy.ops.export_scene.fbx(filepath=str(output), use_selection=False)
        operator = "bpy.ops.export_scene.fbx"
    elif args.format == "obj":
        operator = export_obj(str(output))
    verify_exported_optical_volume(output, args.format, optics, strict_opt_in=optical_active)
    print(f"CBM_EXPORT_OK format={args.format} operator={operator} output={output}")


if __name__ == "__main__":
    main()
