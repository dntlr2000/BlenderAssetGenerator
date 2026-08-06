"""Create one deterministic multi-material .blend for opt-in intake smoke tests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    """Parse the output path supplied by the host-side integration test."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def create_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    """Create one simple Principled material with a deterministic base color."""

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    principled = next(
        node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
    )
    principled.inputs["Base Color"].default_value = color
    return material


def main() -> None:
    """Save one two-material mesh plus a removable embedded text datablock."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 0.01
    bpy.ops.mesh.primitive_cube_add(size=2.0)
    obj = bpy.context.object
    obj.name = "Manual Body"
    paint = create_material("Paint", (0.1, 0.25, 0.8, 1.0))
    glass = create_material("Glass", (0.2, 0.8, 1.0, 0.35))
    obj.data.materials.append(paint)
    obj.data.materials.append(glass)
    for index, polygon in enumerate(obj.data.polygons):
        polygon.material_index = 0 if index < len(obj.data.polygons) // 2 else 1
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    text = bpy.data.texts.new("embedded_example.py")
    text.write("raise RuntimeError('this text must never enter normalized output')\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))


if __name__ == "__main__":
    main()
