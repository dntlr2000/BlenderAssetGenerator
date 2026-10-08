"""Native Blender 5.0.1 bounded patterned fixture for authored UV conversion v1."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/codex_blender_modeler/blender_scripts"))
from convert_portable_materials import (  # noqa: E402
    _bake_global_channels,
    _clone_authored_source_material,
    _create_atlas_uv,
    _create_authored_atlas_uv,
    _portable_material,
    _save_portable_blend,
    _surface_semantics,
    _verify_authored_tangents,
)
from portable_authored_uv_proof import prove_authored_uv  # noqa: E402
from portable_authored_uv_runtime import inspection, snapshot_object  # noqa: E402
from portable_material_conversion_runtime import (  # noqa: E402
    atlas_tile_bounds,
    sha256_file,
    write_json_atomic,
)


def expect_refusal(action, reason):
    """Require the exact eligible boundary to fail instead of silently repairing it."""
    try:
        action()
    except ValueError as error:
        assert reason in str(error), (reason, str(error))
        return
    raise AssertionError(f"Expected authored UV refusal: {reason}")


def make_object(name, offset=0.0):
    """Create a quad with different authored layout and actual source sampling layers."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(offset, 0, 0), (offset + 1, 0, 0), (offset + 1, 1, 0), (offset, 1, 0)], [], [(0, 1, 2, 3)]
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for name, coords in (
        ("Layout", [0, 0, 1, 0, 1, 1, 0, 1]),
        ("Sampling", [1, 0, 0, 0, 0, 1, 1, 1]),
    ):
        layer = mesh.uv_layers.new(name=name)
        layer.uv.foreach_set("vector", coords)
    mesh.uv_layers.active = mesh.uv_layers["Layout"]
    mesh.uv_layers["Sampling"].active_render = True
    material = bpy.data.materials.new(f"material_{obj.name}")
    material.use_nodes = True
    material["cbm_id"] = f"mat.{obj.name}"
    material["cbm_material_source_fingerprint"] = "a" * 64
    material["cbm_mapping_mode"] = "uv"
    material["cbm_uv_set"] = "Layout"
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    image = bpy.data.images.new(f"pattern_{obj.name}", 8, 8)
    pixels = []
    for _y in range(8):
        for x in range(8):
            pixels.extend((1, 0, 0, 1) if x < 4 else (0, 1, 0, 1))
    image.pixels.foreach_set(pixels)
    image.pack()
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Closest"
    links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    normal = nodes.new("ShaderNodeNormalMap")
    normal.inputs["Color"].default_value = (0.75, 0.5, 1.0, 1.0)
    links.new(normal.outputs["Normal"], shader.inputs["Normal"])
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = ""
    coordinate = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coordinate.outputs["UV"], separate.inputs["Vector"])
    mesh.materials.append(material)
    obj["cbm_id"] = f"part.{obj.name}"
    obj["cbm_source_object"] = f"source.{obj.name}"
    obj["cbm_asset_role"] = "render"
    obj["cbm_lod_level"] = 0
    source_mesh = mesh.copy()
    source = bpy.data.objects.new(f"source.{obj.name}", source_mesh)
    source["cbm_asset_role"] = "authoring"
    source.hide_render = True
    source.hide_viewport = True
    bpy.context.collection.objects.link(source)
    return obj, material


def main():
    """Bake the positive case and exercise refusal paths without any production job."""
    directory = Path(sys.argv[sys.argv.index("--") + 1])
    directory.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    obj, material = make_object("fixture")
    # Synthetic contract bytes allow a later host/native pipeline smoke without a real job.
    for filename, payload in {
        "profile.json": {
            "schema_version": "0.7.0",
            "job_id": "fixture",
            "profile_id": "portable_gltf",
            "primary_format": "glb",
        },
        "execution_plan.json": {"fixture": True},
        "uv_manifest.json": {"fixture": True},
        "recipe.json": {"fixture": True},
    }.items():
        write_json_atomic(directory / filename, payload)
    material["cbm_shader_recipe"] = str(directory / "recipe.json")
    material["cbm_shader_recipe_sha256"] = sha256_file(directory / "recipe.json")
    bpy.context.scene["cbm_job_id"] = "fixture"
    bpy.context.scene["cbm_portable_source_build_fingerprint"] = "4" * 64
    bpy.context.scene["cbm_portable_plan_sha256"] = sha256_file(directory / "execution_plan.json")
    source_path = directory / "source.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(source_path))
    source = inspection([obj], sha256_file(source_path))
    write_json_atomic(directory / "authored_uv_source.json", source)
    original = source["objects"][0]
    # Linked mesh users and source/target collisions cannot be repaired implicitly.
    shared = bpy.data.objects.new("shared", obj.data)
    expect_refusal(lambda: snapshot_object(obj), "shared mesh")
    bpy.data.objects.remove(shared)
    collision = obj.data.uv_layers.new(name="CBMPortableAtlas")
    expect_refusal(lambda: snapshot_object(obj), "collision")
    obj.data.uv_layers.remove(collision)
    group = material.node_tree.nodes.new("ShaderNodeGroup")
    expect_refusal(lambda: snapshot_object(obj), "unsupported sampling node GROUP")
    material.node_tree.nodes.remove(group)
    tangent = material.node_tree.nodes.new("ShaderNodeTangent")
    expect_refusal(lambda: snapshot_object(obj), "unsupported sampling node TANGENT")
    material.node_tree.nodes.remove(tangent)
    original_material, clone, mode, coordinates = _clone_authored_source_material(obj, original)
    assert mode == "uv" and coordinates["source_uv_set"] == "Layout"
    for node in clone.node_tree.nodes:
        if node.type in {"UVMAP", "NORMAL_MAP"}:
            assert node.uv_map == "Sampling"
    bounds = atlas_tile_bounds(0, 1, 128, 16)
    _create_authored_atlas_uv(obj, bounds, original)
    _verify_authored_tangents(obj)
    stored = snapshot_object(obj, source=original)
    for name, values in original["uv_layers"].items():
        assert stored["uv_layers"][name] == values
    prove_authored_uv(
        original["uv_layers"]["Layout"],
        original["triangles"],
        bounds,
        actual_target_uvs=stored["uv_layers"]["CBMPortableAtlas"],
    )
    # Measured two-layer color inversion must survive the actual Cycles bake.
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    output = directory / "converted" / "scene.blend"
    images, outputs = _bake_global_channels(
        [obj], [clone], [material["cbm_id"]], directory / "textures", output, 128, 16
    )
    baked_image = bpy.data.images.load(
        str(directory / "textures" / "base_color.png"), check_existing=False
    )
    pixel_values = list(baked_image.pixels)

    def pixel(u, v):
        """Read one interior atlas sample in linear image storage."""
        index = (int(v * 128) * 128 + int(u * 128)) * 4
        return pixel_values[index : index + 3]

    left = pixel(0.3125, 0.5)
    right = pixel(0.6875, 0.5)
    assert left[1] > 0.95 and left[0] < 0.05, left
    assert right[0] > 0.95 and right[1] < 0.05, right
    baked_normal = bpy.data.images.load(
        str(directory / "textures" / "normal.png"), check_existing=False
    )
    baked_normal.colorspace_settings.name = "Non-Color"
    normal_pixels = list(baked_normal.pixels)
    normal_index = (64 * 128 + 40) * 4
    normal_rgb = normal_pixels[normal_index : normal_index + 3]
    assert normal_rgb[0] < 0.45 and normal_rgb[2] > 0.8, normal_rgb
    portable = _portable_material(
        original_material, material["cbm_id"], _surface_semantics(original_material), images
    )
    obj.data.materials[0] = portable
    _save_portable_blend(output)
    target = inspection([obj], sha256_file(output), sources=source["objects"])
    write_json_atomic(directory / "target_inspection.json", target)
    # Legacy path still accepts a repeated source layout and uses Smart Project.
    legacy, _legacy_material = make_object("legacy", 3.0)
    legacy.data.uv_layers["Layout"].uv.foreach_set("vector", [0, 0] * 4)
    legacy_record = _create_atlas_uv(legacy, bounds)
    assert legacy_record["unwrap_method"] in {"smart_project", "lightmap_pack_fallback"}
    write_json_atomic(
        directory / "NATIVE_FIXTURE_RESULT.json",
        {
            "ok": True,
            "blender_version": bpy.app.version_string,
            "left_target_rgb": left,
            "right_target_rgb": right,
            "source_layer_preservation": True,
            "mirrored_source_normal_rgb": normal_rgb,
            "shared_mesh_refused": True,
            "source_target_collision_refused": True,
            "nested_group_refused": True,
            "tangent_node_refused": True,
            "legacy_repeated_source_uv_accepted": True,
            "outputs": outputs,
            "source_blend_sha256": sha256_file(source_path),
            "target_blend_sha256": sha256_file(output),
        },
    )
    print(json.dumps({"ok": True, "directory": str(directory)}))


if __name__ == "__main__":
    main()
