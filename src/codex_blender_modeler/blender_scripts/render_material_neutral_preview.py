from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import bpy
from mathutils import Vector


class NeutralPreviewError(RuntimeError):
    """Signal a missing material or failed bounded neutral-studio render."""


def _argv_after_separator() -> list[str]:
    """Return only arguments explicitly passed to this fixed Blender script."""

    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _parse_args() -> argparse.Namespace:
    """Parse one material identity and two exact output paths."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--material-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(_argv_after_separator())


def _sha256_file(path: Path) -> str:
    """Hash one rendered preview without interpreting or normalizing its bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _point_at(obj: bpy.types.Object, target: Vector) -> None:
    """Aim one camera or area light along Blender's negative local Z axis."""

    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def _clear_objects() -> None:
    """Remove scene objects while retaining the exact compiled material datablock."""

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _build_neutral_scene(material: bpy.types.Material) -> bpy.types.Object:
    """Create a fixed sphere, camera, lights, and dark neutral world."""

    _clear_objects()
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64,
        ring_count=32,
        location=(0.0, 0.0, 0.0),
    )
    sphere = bpy.context.object
    sphere.name = "CBM_NeutralMaterialSphere"
    sphere.data.materials.append(material)
    bpy.ops.object.shade_smooth()
    bpy.ops.object.camera_add(location=(2.8, -2.8, 2.15))
    camera = bpy.context.object
    camera.name = "CBM_NeutralCamera"
    _point_at(camera, Vector((0.0, 0.0, 0.15)))
    camera.data.lens = 58.0
    bpy.context.scene.camera = camera
    for name, location, energy, size in (
        ("CBM_NeutralKey", (3.5, -2.0, 4.5), 850.0, 3.0),
        ("CBM_NeutralFill", (-3.0, -1.0, 2.0), 420.0, 2.5),
        ("CBM_NeutralRim", (0.5, 3.0, 3.5), 600.0, 2.0),
    ):
        data = bpy.data.lights.new(name=name, type="AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        light = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(light)
        light.location = location
        _point_at(light, Vector((0.0, 0.0, 0.0)))
    world = bpy.context.scene.world or bpy.data.worlds.new("CBM_NeutralWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.025, 0.025, 0.025, 1.0)
        background.inputs["Strength"].default_value = 0.35
    return sphere


def _render(output: Path) -> None:
    """Render the fixed neutral studio to a 512-square RGBA PNG."""

    output.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    if not output.is_file():
        raise NeutralPreviewError("neutral preview PNG was not rendered")


def _write_report(
    path: Path,
    *,
    material: bpy.types.Material,
    preview: Path,
) -> None:
    """Write deterministic inventory and exact preview hash after rendering."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tree = material.node_tree
    payload = {
        "schema_version": "0.1.0",
        "status": "passed",
        "scope": "neutral_studio",
        "material_id": material.name,
        "blender_version": bpy.app.version_string,
        "blender_python_version": platform.python_version(),
        "preview_path": preview.name,
        "preview_sha256": _sha256_file(preview),
        "resolution": [512, 512],
        "render_engine": "BLENDER_EEVEE_NEXT",
        "node_count": len(tree.nodes) if tree is not None else 0,
        "link_count": len(tree.links) if tree is not None else 0,
        "human_reviewed": False,
        "reference_matched": False,
        "destination_runtime_parity_verified": False,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> None:
    """Render and inventory one already-compiled exact Blender material graph."""

    args = _parse_args()
    material = bpy.data.materials.get(args.material_id)
    if material is None or not material.use_nodes or material.node_tree is None:
        raise NeutralPreviewError("compiled material is missing or has no node graph")
    output = Path(args.output).expanduser().resolve()
    report = Path(args.report).expanduser().resolve()
    if output.exists() or report.exists():
        raise FileExistsError("neutral preview outputs already exist")
    _build_neutral_scene(material)
    _render(output)
    _write_report(report, material=material, preview=output)
    print(f"CBM_NEUTRAL_PREVIEW_OK material={material.name} output={output}")


if __name__ == "__main__":
    main()
