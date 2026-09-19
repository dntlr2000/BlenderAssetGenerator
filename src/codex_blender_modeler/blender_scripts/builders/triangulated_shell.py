"""Fixed Blender construction for strictly validated, data-only triangular shells."""

from __future__ import annotations

from pathlib import Path

import bpy

from codex_blender_modeler.structural_geometry.triangle_shell_math import (
    validate_triangle_shell_data,
)

from ._structural_mesh import create_mesh_object


def build(spec: dict, _base_dir: Path) -> bpy.types.Object:
    """Preserve the exact declared vertex/triangle order and optional per-corner UV values."""
    validate_triangle_shell_data(spec)
    obj = create_mesh_object(
        "CBM_TriangulatedShell",
        {"vertices": spec["vertices"], "faces": spec["triangles"], "findings": []},
        builder_kind="triangulated_shell",
    )
    loop_uvs = spec.get("loop_uvs")
    if loop_uvs is not None:
        if len(obj.data.loops) != len(loop_uvs):
            raise RuntimeError("triangulated shell construction changed corner order")
        layer = obj.data.uv_layers.new(name="UVMap", do_init=False)
        layer.uv.foreach_set("vector", [value for uv in loop_uvs for value in uv])
        obj.data.uv_layers.active = layer
        layer.active_render = True
        obj.data.update()
    return obj
