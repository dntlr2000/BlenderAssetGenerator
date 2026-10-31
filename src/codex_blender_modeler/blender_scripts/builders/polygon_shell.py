"""Whitelisted Blender construction preserving explicit triangle and quad faces."""

from pathlib import Path

import bpy

from codex_blender_modeler.structural_geometry.polygon_shell_math import (
    validate_polygon_shell_data,
)

from ._structural_mesh import create_mesh_object


def build(spec: dict, _base_dir: Path) -> bpy.types.Object:
    """Build exact polygons and UV corners; triangle views remain disposable derivatives."""
    validate_polygon_shell_data(spec)
    obj = create_mesh_object("CBM_PolygonShell", {**spec, "findings": []},
                             builder_kind="polygon_shell")
    if spec.get("loop_uvs") is not None:
        layer = obj.data.uv_layers.new(name="UVMap", do_init=False)
        layer.uv.foreach_set("vector", [v for uv in spec["loop_uvs"] for v in uv])
        layer.active_render = True
        obj.data.update()
    obj["cbm_preserve_polygon_tessellation"] = True
    return obj
