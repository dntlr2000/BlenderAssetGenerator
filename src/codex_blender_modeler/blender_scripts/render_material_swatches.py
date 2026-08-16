from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from artifact_render_common import configure_artifact_render  # noqa: E402

from codex_blender_modeler.blender_artifacts import (  # noqa: E402
    artifact_path,
    native_io_path,
    safe_artifact_name,
    sha256_file,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    """Parse swatch output, renderer, and optional material filters."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--render-engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--material-id", action="append", default=[])
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    if args.size < 64 or args.size > 2048:
        parser.error("--size must be between 64 and 2048")
    return args


def _look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    """Aim a camera or light object's local -Z axis at a world-space target."""

    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _neutral_material() -> bpy.types.Material:
    """Create a neutral non-metallic floor material for transparency context."""

    material = bpy.data.materials.new("CBM_SwatchFloor")
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = (0.16, 0.16, 0.16, 1.0)
        shader.inputs["Roughness"].default_value = 0.72
    return material


def _create_swatch_scene() -> tuple[bpy.types.Object, bpy.types.Object]:
    """Hide asset geometry and create a fixed sphere/plane swatch stage."""

    for obj in bpy.context.scene.objects:
        obj.hide_render = True

    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64,
        ring_count=32,
        radius=0.82,
        location=(-0.78, 0.0, 0.92),
    )
    sphere = bpy.context.object
    sphere.name = "CBM_SwatchSphere"
    sphere.hide_render = False
    for polygon in sphere.data.polygons:
        polygon.use_smooth = True

    bpy.ops.mesh.primitive_plane_add(
        size=1.75,
        location=(1.05, 0.18, 0.92),
        rotation=(math.radians(90.0), 0.0, 0.0),
    )
    plane = bpy.context.object
    plane.name = "CBM_SwatchPlane"
    plane.hide_render = False

    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.object
    floor.name = "CBM_SwatchFloor"
    floor.hide_render = False
    floor.data.materials.append(_neutral_material())

    camera_data = bpy.data.cameras.new("CBM_SwatchCamera")
    camera = bpy.data.objects.new("CBM_SwatchCamera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.hide_render = False
    camera.location = (3.7, -6.2, 3.15)
    camera_data.lens = 56.0
    _look_at(camera, (0.1, 0.0, 0.78))
    bpy.context.scene.camera = camera

    for name, location, energy, size in (
        ("Key", (-3.4, -3.2, 5.0), 950.0, 3.2),
        ("Fill", (4.0, -1.0, 2.8), 620.0, 2.8),
        ("Rim", (0.0, 3.0, 4.5), 820.0, 2.4),
    ):
        light_data = bpy.data.lights.new(f"CBM_Swatch{name}", type="AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = size
        light = bpy.data.objects.new(f"CBM_Swatch{name}", light_data)
        bpy.context.scene.collection.objects.link(light)
        light.hide_render = False
        light.location = location
        _look_at(light, (0.0, 0.0, 0.8))

    world = bpy.context.scene.world or bpy.data.worlds.new("CBM_SwatchWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.035, 0.035, 0.045, 1.0)
        background.inputs["Strength"].default_value = 0.32
    return sphere, plane


def _assign_material(obj: bpy.types.Object, material: bpy.types.Material) -> None:
    """Replace one swatch object's material slots with the selected asset material."""

    obj.data.materials.clear()
    obj.data.materials.append(material)


def _material_id(material: bpy.types.Material) -> str:
    """Return the stable material ID recorded by the deterministic scene builder."""

    return str(material.get("cbm_id", material.name))


def _selected_materials(requested: list[str]) -> list[bpy.types.Material]:
    """Resolve optional material IDs while rejecting ambiguous or missing requests."""

    materials = sorted(
        (material for material in bpy.data.materials if material.name != "CBM_SwatchFloor"),
        key=_material_id,
    )
    if not requested:
        return materials
    by_id = {_material_id(material): material for material in materials}
    missing = sorted(set(requested) - set(by_id))
    if missing:
        raise ValueError(f"Unknown material IDs: {missing}")
    return [by_id[material_id] for material_id in requested]


def main() -> None:
    """Render one deterministic sphere/plane swatch per selected material."""

    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    os.makedirs(native_io_path(output_dir), exist_ok=True)
    configure_artifact_render(args.render_engine, args.render_device)
    scene = bpy.context.scene
    scene.render.resolution_x = args.size
    scene.render.resolution_y = args.size
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False

    source_materials = [
        material for material in bpy.data.materials if material.name != "CBM_SwatchFloor"
    ]
    sphere, plane = _create_swatch_scene()
    materials = _selected_materials(args.material_id)
    records: list[dict[str, Any]] = []
    for material in materials:
        _assign_material(sphere, material)
        _assign_material(plane, material)
        material_id = _material_id(material)
        swatch_path = output_dir / safe_artifact_name(material_id) / "swatch.png"
        os.makedirs(native_io_path(swatch_path.parent), exist_ok=True)
        scene.render.filepath = str(swatch_path)
        bpy.ops.render.render(write_still=True)
        records.append(
            {
                "material_id": material_id,
                "path": artifact_path(swatch_path, manifest_path),
                "sha256": sha256_file(swatch_path),
                "width": args.size,
                "height": args.size,
                "encoding": "png-rgba8",
            }
        )

    manifest = {
        "schema_version": "0.5.0",
        "job_id": scene.get("cbm_job_id"),
        "blender_version": bpy.app.version_string,
        "render_engine": scene.get("cbm_render_engine", scene.render.engine),
        "render_device": scene.get("cbm_render_device", "DEFAULT"),
        "color_management_look": scene.get(
            "cbm_color_management_look", scene.view_settings.look
        ),
        "resolution": [args.size, args.size],
        "material_count": len(records),
        "source_material_count": len(source_materials),
        "swatches": records,
    }
    write_json_atomic(manifest_path, manifest)
    print(f"CBM_MATERIAL_SWATCH_OK materials={len(records)} manifest={manifest_path}")


if __name__ == "__main__":
    main()
