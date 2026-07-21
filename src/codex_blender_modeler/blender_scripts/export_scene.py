from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from compat import export_obj  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", required=True, choices=["glb", "gltf", "obj", "fbx"])
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    operator = ""
    if args.format == "glb":
        bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", use_selection=False)
        operator = "bpy.ops.export_scene.gltf(GLB)"
    elif args.format == "gltf":
        bpy.ops.export_scene.gltf(
            filepath=str(output), export_format="GLTF_SEPARATE", use_selection=False
        )
        operator = "bpy.ops.export_scene.gltf(GLTF_SEPARATE)"
    elif args.format == "fbx":
        bpy.ops.export_scene.fbx(filepath=str(output), use_selection=False)
        operator = "bpy.ops.export_scene.fbx"
    elif args.format == "obj":
        operator = export_obj(str(output))
    print(f"CBM_EXPORT_OK format={args.format} operator={operator} output={output}")


if __name__ == "__main__":
    main()
