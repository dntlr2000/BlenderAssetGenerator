"""Actual scalar-domain bake regression for unseeded strips and mirrored sampled UVs."""

import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src/codex_blender_modeler/blender_scripts")]
from blender_authored_uv_fixture import make_object  # noqa: E402
from convert_portable_materials import (  # noqa: E402
    _bake_global_channels,
    _bake_scalar_coverage,
    _channel_socket,
    _clone_authored_source_material,
    _create_authored_atlas_uv,
    _emission_strength_socket,
    _portable_material,
    _save_portable_blend,
    _surface_semantics,
)
from portable_authored_uv_runtime import inspection  # noqa: E402
from portable_material_conversion_runtime import (  # noqa: E402
    atlas_tile_bounds,
    sha256_file,
    write_json_atomic,
)
from portable_uv_scalar_runtime import make_scalar_proxy, remove_scalar_proxies  # noqa: E402


def main():
    """Compare unchanged real-mesh normals and scalar recovery at an actual unseeded UV strip."""
    directory = Path(sys.argv[sys.argv.index("--") + 1])
    directory.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    obj, material = make_object("fixture")
    source_image = next(node.image for node in material.node_tree.nodes if node.type == "TEX_IMAGE")
    pixels = list(source_image.pixels)
    for row in range(8):
        for column in range(2):
            offset = (row * 8 + column) * 4
            pixels[offset : offset + 3] = [0.0, 0.0, 0.0]
    source_image.pixels.foreach_set(pixels)
    source_image.pack()
    obj.data.clear_geometry()
    obj.data.from_pydata(
        [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (2, 0, 0), (3, 0, 0), (3, 1, 0), (2, 1, 0)],
        [],
        [(0, 1, 2, 3), (4, 5, 6, 7)],
    )
    layout = [
        [0.0, 0.0],
        [1.0, 0.0],
        [1.0, 0.5],
        [0.0, 0.5],
        [0.25, 0.998],
        [0.375, 0.998],
        [0.375, 1.0],
        [0.25, 1.0],
    ]
    for name, values in (("Layout", layout), ("Sampling", [[1 - u, v] for u, v in layout])):
        layer = obj.data.uv_layers.new(name=name)
        layer.uv.foreach_set("vector", [value for point in values for value in point])
    obj.data.uv_layers.active = obj.data.uv_layers["Layout"]
    obj.data.uv_layers["Sampling"].active_render = True
    obj.data.update()
    bpy.data.objects["source.fixture"].data = obj.data.copy()
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
    scene = bpy.context.scene
    scene["cbm_job_id"] = "fixture"
    scene["cbm_portable_source_build_fingerprint"] = "4" * 64
    scene["cbm_portable_plan_sha256"] = sha256_file(directory / "execution_plan.json")
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / "source.blend"))
    source = inspection([obj], sha256_file(directory / "source.blend"))
    write_json_atomic(directory / "authored_uv_source.json", source)
    raw = source["objects"][0]
    original, clone, _mode, _coordinates = _clone_authored_source_material(obj, raw)
    _create_authored_atlas_uv(obj, atlas_tile_bounds(0, 1, 128, 16), raw)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    _bake_global_channels(
        [obj],
        [clone],
        [material["cbm_id"]],
        directory / "geometry_textures",
        directory / "geometry_scene.blend",
        128,
        16,
    )
    dependency = clone.node_tree.nodes.new("ShaderNodeNewGeometry")
    base_socket = _channel_socket(clone, "base_color")
    original_link = base_socket.links[0].from_socket
    clone.node_tree.links.new(dependency.outputs["Position"], base_socket)
    try:
        make_scalar_proxy(obj, raw, 0, 1, 128, 16, _channel_socket, _emission_strength_socket)
    except ValueError as error:
        assert "ineligible dependency" in str(error)
    else:
        raise AssertionError("Geometry-dependent scalar source was not refused")
    clone.node_tree.links.new(original_link, base_socket)
    clone.node_tree.nodes.remove(dependency)
    proxy, record = make_scalar_proxy(
        obj, raw, 0, 1, 128, 16, _channel_socket, _emission_strength_socket
    )
    coverage = _bake_scalar_coverage([proxy], directory / "authored_uv_coverage.png", 128, 16)
    import convert_portable_materials as conversion

    original_operator = conversion._run_bake_operator
    normal_excluded = []

    def checked_operator(channel, margin):
        """Require proxy render exclusion during the actual real-mesh normal operator."""
        if channel == "normal":
            assert proxy.hide_render
            normal_excluded.append(True)
        return original_operator(channel, margin)

    conversion._run_bake_operator = checked_operator
    try:
        images, outputs = _bake_global_channels(
            [obj],
            [clone],
            [material["cbm_id"]],
            directory / "textures",
            directory / "converted/scene.blend",
            128,
            16,
            scalar_objects=[proxy],
        )
    finally:
        conversion._run_bake_operator = original_operator
        remove_scalar_proxies([proxy])
    assert sha256_file(directory / "geometry_textures/normal.png") == sha256_file(
        directory / "textures/normal.png"
    )

    def sample(path, x, y):
        """Read an actual saved linear image pixel with a fresh image datablock."""
        image = bpy.data.images.load(str(path), check_existing=False)
        values = list(image.pixels)
        start = (y * 128 + x) * 4
        return values[start : start + 3]

    old = sample(directory / "geometry_textures/base_color.png", 46, 111)
    new = sample(directory / "textures/base_color.png", 46, 111)
    assert max(old) < 0.01 and new[1] > 0.95 and new[0] < 0.05, (old, new)
    black = sample(directory / "textures/base_color.png", 100, 40)
    zero_emission = sample(directory / "textures/emission.png", 46, 40)
    assert max(black) < 0.01 and max(zero_emission) < 0.01
    portable = _portable_material(
        original, material["cbm_id"], _surface_semantics(original), images
    )
    obj.data.materials[0] = portable
    _save_portable_blend(directory / "converted/scene.blend")
    assert all(not ob.name.startswith("CBM_SCALAR_PROXY") for ob in bpy.data.objects)
    write_json_atomic(
        directory / "SCALAR_NATIVE_RESULT.json",
        {
            "ok": True,
            "old_unseeded_rgb": old,
            "source_evaluated_rgb": new,
            "normal_file_exactly_unchanged": True,
            "normal_pass_proxies_excluded": normal_excluded == [True],
            "geometry_dependent_scalar_refused": True,
            "legitimate_black_base_color": black,
            "legitimate_zero_emission": zero_emission,
            "proxy_record": record,
            "coverage": coverage,
            "outputs": outputs,
            "original_source_sha256": sha256_file(directory / "source.blend"),
        },
    )


if __name__ == "__main__":
    main()
