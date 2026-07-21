from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from compat import configure_render_compat, export_obj  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--smoke-exports", action="store_true")
    parser.add_argument("--export-dir")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def attempt(label: str, callback) -> dict:
    try:
        callback()
    except Exception as exc:  # Blender reports exact API failures in the JSON probe.
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True}


def main() -> None:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    engine, look = configure_render_compat(scene)

    report: dict = {
        "ok": True,
        "blender_version": bpy.app.version_string,
        "python_version": sys.version,
        "render_engine": engine,
        "color_management_look": look,
        "operators": {
            "gltf": hasattr(getattr(bpy.ops, "export_scene", None), "gltf"),
            "fbx": hasattr(getattr(bpy.ops, "export_scene", None), "fbx"),
            "obj_modern": hasattr(getattr(bpy.ops, "wm", None), "obj_export"),
            "obj_legacy": hasattr(getattr(bpy.ops, "export_scene", None), "obj"),
        },
        "smoke_exports": {},
    }

    if args.smoke_exports:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        export_root = (
            Path(args.export_dir).expanduser().resolve()
            if args.export_dir
            else Path(tempfile.mkdtemp(prefix="cbm-compat-"))
        )
        export_root.mkdir(parents=True, exist_ok=True)

        glb = export_root / "compat.glb"
        obj = export_root / "compat.obj"
        fbx = export_root / "compat.fbx"
        report["smoke_exports"]["glb"] = attempt(
            "glb",
            lambda: bpy.ops.export_scene.gltf(
                filepath=str(glb), export_format="GLB", use_selection=False
            ),
        )
        report["smoke_exports"]["obj"] = attempt("obj", lambda: export_obj(str(obj)))
        report["smoke_exports"]["fbx"] = attempt(
            "fbx", lambda: bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=False)
        )
        for name, path in {"glb": glb, "obj": obj, "fbx": fbx}.items():
            result = report["smoke_exports"][name]
            result["path"] = str(path)
            result["exists"] = path.exists()
            result["size_bytes"] = path.stat().st_size if path.exists() else 0
        report["ok"] = all(item["ok"] for item in report["smoke_exports"].values())

    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"CBM_COMPAT_{'OK' if report['ok'] else 'FAILED'} output={output}")
    if not report["ok"]:
        raise RuntimeError("One or more Blender compatibility smoke exports failed")


if __name__ == "__main__":
    main()
