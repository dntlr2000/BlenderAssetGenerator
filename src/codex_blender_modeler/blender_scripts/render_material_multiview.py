from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def _parse_args() -> argparse.Namespace:
    """Parse a bounded material-continuity render request after Blender's separator."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _visible_semantic_meshes() -> list[bpy.types.Object]:
    """Collect render-enabled semantic meshes without exposing hidden Boolean helpers."""

    objects = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.get("cbm_id") and not obj.hide_render
    ]
    if not objects:
        raise RuntimeError("No render-enabled semantic meshes were found")
    return objects


def _world_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    """Compute a world-space AABB for the render-enabled semantic meshes."""

    points = [
        obj.matrix_world @ Vector(corner)
        for obj in objects
        for corner in obj.bound_box
    ]
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


def _configure_render(output: Path) -> None:
    """Configure a deterministic Eevee PNG without saving the authoring blend."""

    scene = bpy.context.scene
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = engine
            break
        except TypeError:
            continue
    else:
        raise RuntimeError("No supported Eevee render engine is available")
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.filepath = str(output)


def _temporary_camera(
    center: Vector,
    location: Vector,
    *,
    horizontal_extent: float,
    vertical_extent: float,
) -> bpy.types.Object:
    """Create one orthographic camera that frames the supplied projected bounds."""

    camera_data = bpy.data.cameras.new("CBM_MATERIAL_CONTINUITY_CAMERA")
    camera_data.type = "ORTHO"
    aspect = 1024.0 / 768.0
    camera_data.ortho_scale = max(vertical_extent, horizontal_extent / aspect) * 1.18
    camera = bpy.data.objects.new("CBM_MATERIAL_CONTINUITY_CAMERA", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = location
    camera.rotation_euler = (center - location).to_track_quat("-Z", "Y").to_euler()
    return camera


def _render_view(
    output_dir: Path,
    view_id: str,
    center: Vector,
    location: Vector,
    *,
    horizontal_extent: float,
    vertical_extent: float,
) -> dict:
    """Render one temporary diagnostic view and return its immutable file evidence."""

    output = output_dir / f"{view_id}.png"
    camera = _temporary_camera(
        center,
        location,
        horizontal_extent=horizontal_extent,
        vertical_extent=vertical_extent,
    )
    scene = bpy.context.scene
    previous_camera = scene.camera
    try:
        scene.camera = camera
        _configure_render(output)
        bpy.ops.render.render(write_still=True)
    finally:
        scene.camera = previous_camera
        camera_data = camera.data
        bpy.data.objects.remove(camera, do_unlink=True)
        bpy.data.cameras.remove(camera_data)
    if not output.is_file():
        raise RuntimeError(f"Diagnostic render was not created: {output}")
    return {
        "view_id": view_id,
        "path": output.name,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "camera_location": [float(value) for value in location],
        "target": [float(value) for value in center],
    }


def main() -> None:
    """Render temporary nose-on and top material-continuity views with a sidecar."""

    args = _parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    objects = _visible_semantic_meshes()
    minimum, maximum = _world_bounds(objects)
    center = (minimum + maximum) * 0.5
    extent = maximum - minimum
    distance = max(extent) * 2.0 + 10.0
    views = [
        _render_view(
            output_dir,
            "front",
            center,
            center + Vector((-distance, 0.0, 0.0)),
            horizontal_extent=max(extent.y, 0.1),
            vertical_extent=max(extent.z, 0.1),
        ),
        _render_view(
            output_dir,
            "up",
            center,
            center + Vector((0.0, 0.0, distance)),
            horizontal_extent=max(extent.x, 0.1),
            vertical_extent=max(extent.y, 0.1),
        ),
    ]
    manifest = {
        "schema_version": "0.1.0",
        "purpose": "supplemental_material_continuity_review",
        "authoring_blend_saved": False,
        "bounds": {
            "minimum": [float(value) for value in minimum],
            "maximum": [float(value) for value in maximum],
        },
        "views": views,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
