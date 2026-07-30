from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def _parse_args() -> argparse.Namespace:
    """Parse a bounded UV-diagnostic render request after Blender's argument separator."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--object-id", action="append", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _find_semantic_object(semantic_id: str) -> bpy.types.Object:
    """Resolve exactly one Blender object by its stable CBM semantic ID."""

    matches = [obj for obj in bpy.data.objects if obj.get("cbm_id") == semantic_id]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one object with cbm_id={semantic_id!r}, found {len(matches)}"
        )
    return matches[0]


def _make_uv_material() -> bpy.types.Material:
    """Build an emission shader whose red and green channels encode active UV coordinates."""

    material = bpy.data.materials.new("CBM_UV_DIAGNOSTIC")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    coordinates = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    combine = nodes.new("ShaderNodeCombineColor")
    emission = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    combine.inputs["Blue"].default_value = 0.0
    emission.inputs["Strength"].default_value = 1.0

    links.new(coordinates.outputs["UV"], separate.inputs["Vector"])
    links.new(separate.outputs["X"], combine.inputs["Red"])
    links.new(separate.outputs["Y"], combine.inputs["Green"])
    links.new(combine.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _configure_render(output: Path) -> None:
    """Configure a stable transparent PNG render without saving the authoring blend."""

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
    scene.render.film_transparent = True
    scene.render.filepath = str(output)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def main() -> None:
    """Render selected semantic meshes with UV values encoded as pixel color."""

    args = _parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    targets = {_find_semantic_object(value) for value in args.object_id}
    diagnostic = _make_uv_material()

    for obj in bpy.data.objects:
        obj.hide_render = obj not in targets
    for obj in targets:
        if obj.type != "MESH" or obj.data is None:
            raise RuntimeError(f"UV diagnostic target is not a mesh: {obj.name}")
        if not obj.data.uv_layers:
            raise RuntimeError(f"UV diagnostic target has no UV layer: {obj.name}")
        obj.data.materials.clear()
        obj.data.materials.append(diagnostic)

    _configure_render(output)
    bpy.ops.render.render(write_still=True)
    if not output.is_file():
        raise RuntimeError(f"UV diagnostic render was not created: {output}")


if __name__ == "__main__":
    main()
