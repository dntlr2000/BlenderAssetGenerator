from __future__ import annotations

import bpy
from compat import configure_render_compat


def configure_artifact_render(render_engine: str, render_device: str) -> None:
    """Configure Blender 4/5 rendering without importing host-only material dependencies."""

    scene = bpy.context.scene
    configure_render_compat(scene, render_engine, render_device)
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = 64
        scene.cycles.use_denoising = True
        scene["cbm_cycles_samples"] = 64
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.resolution_percentage = 100
