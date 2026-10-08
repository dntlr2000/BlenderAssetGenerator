"""Real Blender 5.0.1 authored-UV pin/bake/volume conversion and hostile graph controls."""
# ruff: noqa: E402

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--baseline-runtime", type=Path)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
sys.path[:0] = [
    str(args.repo / "src"),
    str(args.repo / "src/codex_blender_modeler/blender_scripts"),
]

import bpy
from convert_portable_materials import (
    _bake_global_channels,
    _bake_scalar_coverage,
    _channel_socket,
    _clone_authored_source_material,
    _create_authored_atlas_uv,
    _emission_strength_socket,
    _portable_material,
    _save_portable_blend,
    _surface_semantics,
    _verify_authored_tangents,
)
from optical_volume_runtime import (
    CONTRACT_KEY,
    THICKNESS_NODE,
    apply_optical_volume,
    read_optical_volume,
    validate_optical_volume_objects,
    verify_exported_optical_volume,
)
from portable_authored_uv_proof import prove_authored_uv
from portable_authored_uv_runtime import inspection, sampling_bindings, snapshot_object
from portable_material_conversion_runtime import atlas_tile_bounds, sha256_file, write_json_atomic
from portable_uv_scalar_bake import coverage_pixel_box
from portable_uv_scalar_runtime import make_scalar_proxy, remove_scalar_proxies

VOLUME = {
    "schema_version": "0.1.0",
    "thickness_factor": 0.2,
    "attenuation_distance": 2.5,
    "attenuation_color": [0.72, 0.96, 0.83],
}


def fresh_cube(*, volume=True, pattern=False):
    """Make one closed, independently owned unit cube with two distinct authored UV sets."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.object
    obj.name = "AuthoredOpticalCube"
    obj["cbm_id"] = "part.optical_cube"
    obj["cbm_source_object"] = "source.optical_cube"
    obj["cbm_asset_role"] = "render"
    obj["cbm_lod_level"] = 0
    layout = obj.data.uv_layers.active
    layout.name = "Layout"
    uv = [0.0] * (2 * len(obj.data.loops))
    layout.uv.foreach_get("vector", uv)
    sampling = obj.data.uv_layers.new(name="Sampling")
    sampling.uv.foreach_set("vector", [1 - v if i % 2 == 0 else v for i, v in enumerate(uv)])
    obj.data.uv_layers.active = layout
    sampling.active_render = True
    mat = bpy.data.materials.new("OpticalCubeMaterial")
    mat.use_nodes = True
    mat["cbm_id"] = "mat.optical_cube"
    mat["cbm_mapping_mode"] = "uv"
    mat["cbm_uv_set"] = "Layout"
    mat["cbm_material_source_fingerprint"] = "a" * 64
    shader = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    shader.inputs["Transmission Weight"].default_value = 0.95
    shader.inputs["Metallic"].default_value = 0
    shader.inputs["IOR"].default_value = 1.46
    shader.inputs["Alpha"].default_value = 1
    if pattern:
        im = bpy.data.images.new("Pattern", 8, 8)
        im.pixels[:] = [
            c for y in range(8) for x in range(8) for c in ((1, 0, 0, 1) if x < 4 else (0, 1, 0, 1))
        ]
        im.pack()
        texture = mat.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = im
        texture.interpolation = "Closest"
        mat.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        normal = mat.node_tree.nodes.new("ShaderNodeNormalMap")
        normal.inputs["Color"].default_value = (0.5, 0.5, 1, 1)
        mat.node_tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
    if volume:
        apply_optical_volume(mat, VOLUME)
    obj.data.materials.append(mat)
    return obj, mat


def reject(label, mutate):
    """Require an actual hostile native graph to fail authored-UV eligibility."""
    obj, mat = fresh_cube()
    node = mat.node_tree.nodes[THICKNESS_NODE]
    mutate(mat, node, node.node_tree)
    try:
        snapshot_object(obj)
    except ValueError as error:
        negatives.append({"case": label, "rejected": str(error)})
    else:
        raise AssertionError(f"Accepted hostile case: {label}")


def add_link(mat, node, tree):
    """Feed the thickness input from a root value node instead of a constant."""
    value = mat.node_tree.nodes.new("ShaderNodeValue")
    mat.node_tree.links.new(value.outputs[0], node.inputs[0])


def add_output_link(mat, node, tree):
    """Make the formerly inert group feed a live surface scalar through an added output."""
    tree.interface.new_socket(name="Value", in_out="OUTPUT", socket_type="NodeSocketFloat")
    shader = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    mat.node_tree.links.new(node.outputs[0], shader.inputs["Roughness"])


def add_internal_link(mat, node, tree):
    """Insert internal computation and a link even when no group output exists."""
    a = tree.nodes.new("ShaderNodeValue")
    b = tree.nodes.new("ShaderNodeMath")
    tree.links.new(a.outputs[0], b.inputs[0])


def group_driver(mat, node, tree):
    """Attach a constant driver to the group ID; no arbitrary script is enabled."""
    tree["probe"] = 0.0
    tree.driver_add('["probe"]').driver.expression = "0.0"


def parent_driver(mat, node, tree):
    """Attach a socket driver to the parent tree to verify existing animation rejection."""
    node.inputs[0].driver_add("default_value").driver.expression = "0.2"


def wrong_type(mat, node, tree):
    """Replace the sole interface scalar with a same-name vector socket."""
    tree.interface.remove(tree.interface.items_tree[0])
    tree.interface.new_socket(name="Thickness", in_out="INPUT", socket_type="NodeSocketVector")


def material_driver(mat, node, tree):
    """Attach an ordinary constant material driver and require static refusal."""
    mat.driver_add("diffuse_color", 0).driver.expression = "0.5"


assert bpy.app.version[:3] == (5, 0, 1)
out = args.output
out.mkdir(exist_ok=False)
negatives = []
for label, mutate in [
    ("same_name_without_contract", lambda m, n, t: m.__delitem__(CONTRACT_KEY)),
    ("malformed_contract", lambda m, n, t: m.__setitem__(CONTRACT_KEY, "{}")),
    ("changed_thickness", lambda m, n, t: setattr(n.inputs[0], "default_value", 0.4)),
    ("unknown_extra_group", lambda m, n, t: m.node_tree.nodes.new("ShaderNodeGroup")),
    ("renamed_node", lambda m, n, t: setattr(n, "name", THICKNESS_NODE + ".001")),
    ("broad_prefix_tree", lambda m, n, t: setattr(t, "name", "glTF Material Output arbitrary")),
    ("bad_suffix_tree", lambda m, n, t: setattr(t, "name", t.name + ".001evil")),
    ("unused_nested_texture", lambda m, n, t: t.nodes.new("ShaderNodeTexImage")),
    ("unused_nested_group", lambda m, n, t: t.nodes.new("ShaderNodeGroup")),
    ("unused_group_input", lambda m, n, t: t.nodes.new("NodeGroupInput")),
    ("internal_link", add_internal_link),
    ("root_input_link", add_link),
    ("root_output_link", add_output_link),
    ("group_animation", lambda m, n, t: t.animation_data_create()),
    ("group_driver", group_driver),
    ("parent_driver", parent_driver),
    ("material_driver", material_driver),
    ("parent_animation", lambda m, n, t: m.node_tree.animation_data_create()),
    ("interface_panel", lambda m, n, t: t.interface.new_panel(name="Unexpected")),
    (
        "extra_input",
        lambda m, n, t: t.interface.new_socket(
            name="Vector", in_out="INPUT", socket_type="NodeSocketVector"
        ),
    ),
    (
        "extra_output",
        lambda m, n, t: t.interface.new_socket(
            name="Shader", in_out="OUTPUT", socket_type="NodeSocketShader"
        ),
    ),
    ("wrong_socket_type", wrong_type),
    (
        "changed_absorption",
        lambda m, n, t: setattr(
            m.node_tree.nodes["CBM_OpticalVolume_Absorption"].inputs["Density"], "default_value", 4
        ),
    ),
]:
    reject(label, mutate)

# A locally generated signature does not authorize a linked-library metadata tree.
obj, mat = fresh_cube()
group = mat.node_tree.nodes[THICKNESS_NODE].node_tree
library_path = out / "metadata_library.blend"
bpy.data.libraries.write(str(library_path), {group})
obj, mat = fresh_cube()
with bpy.data.libraries.load(str(library_path), link=True) as (available, requested):
    requested.node_groups = available.node_groups
linked = requested.node_groups[0]
node = mat.node_tree.nodes[THICKNESS_NODE]
node.node_tree = linked
node.inputs["Thickness"].default_value = VOLUME["thickness_factor"]
assert read_optical_volume(mat) == VOLUME
try:
    snapshot_object(obj)
except ValueError as error:
    negatives.append({"case": "linked_library_metadata", "rejected": str(error)})
else:
    raise AssertionError("Accepted linked-library metadata")


# Numeric datablock collision suffixes and shared empty metadata in material copies are valid.
obj, mat = fresh_cube()
mat.node_tree.nodes[THICKNESS_NODE].node_tree.name += ".1000"
assert sampling_bindings(obj, mat) == []
clone = mat.copy()
assert (
    clone.node_tree.nodes[THICKNESS_NODE].node_tree == mat.node_tree.nodes[THICKNESS_NODE].node_tree
)
assert sampling_bindings(obj, clone) == []

# Same bytes for the entire old no-volume inspection, measured against the frozen old module.
obj, mat = fresh_cube(volume=False, pattern=True)
legacy = inspection([obj], "b" * 64)
legacy_bytes = json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
baseline_equal = None
if args.baseline_runtime:
    spec = importlib.util.spec_from_file_location(
        "frozen_authored_uv_runtime", args.baseline_runtime
    )
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    old_bytes = json.dumps(
        old.inspection([obj], "b" * 64), sort_keys=True, separators=(",", ":")
    ).encode()
    assert legacy_bytes == old_bytes
    baseline_equal = True
write_json_atomic(out / "LEGACY_INSPECTION.json", legacy)

# Save fixture source once, then drive the existing pin/atlas/bake/portable conversion helpers.
apply_optical_volume(mat, VOLUME)
authoring = obj.copy()
authoring.data = obj.data.copy()
authoring.name = obj["cbm_source_object"]
authoring["cbm_asset_role"] = "authoring"
authoring.hide_render = True
authoring.hide_viewport = True
bpy.context.collection.objects.link(authoring)
source_path = out / "source.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(source_path))
source_hash = sha256_file(source_path)
source = inspection([obj], source_hash)
write_json_atomic(out / "authored_uv_source.json", source)
original = source["objects"][0]
assert original["sampling"] == legacy["objects"][0]["sampling"]
source_boundary = validate_optical_volume_objects([obj], require_stored_geometry=True)
original_mat, clone, mode, coords = _clone_authored_source_material(obj, original)
assert mode == "uv" and coords["source_uv_set"] == "Layout"
assert read_optical_volume(clone) == VOLUME
assert all(binding["uv_set"] == "Sampling" for binding in sampling_bindings(obj, clone))
bounds = atlas_tile_bounds(0, 1, 128, 8)
_create_authored_atlas_uv(obj, bounds, original)
_verify_authored_tangents(obj)
stored = snapshot_object(obj, source=original)
for name, values in original["uv_layers"].items():
    assert stored["uv_layers"][name] == values
proof = prove_authored_uv(
    original["uv_layers"]["Layout"],
    original["triangles"],
    bounds,
    actual_target_uvs=stored["uv_layers"]["CBMPortableAtlas"],
)
bpy.context.scene.render.engine = "CYCLES"
bpy.context.scene.cycles.device = "CPU"
bpy.context.scene.cycles.samples = 1
output = out / "converted/scene.blend"
proxy, scalar_row = make_scalar_proxy(
    obj,
    original,
    0,
    1,
    128,
    8,
    _channel_socket,
    _emission_strength_socket,
    precomputed_bounds=bounds,
)
try:
    coverage = _bake_scalar_coverage([proxy], out / "authored_uv_coverage.png", 128, 8)
    images, outputs = _bake_global_channels(
        [obj],
        [clone],
        [mat["cbm_id"]],
        out / "textures",
        output,
        128,
        8,
        preserve_constant_emission=True,
        scalar_objects=[proxy],
    )
finally:
    remove_scalar_proxies([proxy])
assert not any(o.name.startswith("CBM_SCALAR_PROXY_") for o in bpy.data.objects)
coverage_image = bpy.data.images.load(str(out / "authored_uv_coverage.png"), check_existing=False)
coverage_values = list(coverage_image.pixels)
x0, y0, x1, y1 = coverage_pixel_box(bounds, 128)
assert all(
    min(coverage_values[(y * 128 + x) * 4 : (y * 128 + x) * 4 + 3]) > 0.99
    for y in range(y0, y1)
    for x in range(x0, x1)
)
assert read_optical_volume(clone) == VOLUME
baked = bpy.data.images.load(str(out / "textures/base_color.png"), check_existing=False)
pixels = list(baked.pixels)
measured = []
for polygon in obj.data.polygons:
    indices = list(polygon.loop_indices)
    u = sum(original["uv_layers"]["Layout"][i][0] for i in indices) / len(indices)
    if abs(u - 0.5) < 0.05:
        continue
    target = stored["uv_layers"]["CBMPortableAtlas"]
    x = int(sum(target[i][0] for i in indices) / len(indices) * 128)
    y = int(sum(target[i][1] for i in indices) / len(indices) * 128)
    rgb = pixels[(y * 128 + x) * 4 : (y * 128 + x) * 4 + 3]
    wanted = 0 if 1 - u < 0.5 else 1
    assert rgb[wanted] > 0.95 and rgb[1 - wanted] < 0.05, (u, rgb)
    measured.append({"source_layout_u": u, "rgb": rgb, "expected_color": wanted})
assert len(measured) >= 2
portable = _portable_material(original_mat, mat["cbm_id"], _surface_semantics(original_mat), images)
obj.data.materials[0] = portable
assert read_optical_volume(portable) == VOLUME
converted_boundary = validate_optical_volume_objects([obj], require_stored_geometry=True)
_save_portable_blend(output)
target = inspection([obj], sha256_file(output), sources=source["objects"])
write_json_atomic(out / "target_inspection.json", target)
for name, values in original["uv_layers"].items():
    assert target["objects"][0]["uv_layers"][name] == values
assert sha256_file(source_path) == source_hash
# Native exporter additionally proves preserved optical constants in the fixture asset.
path = out / "converted/fixture.glb"
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(
    filepath=str(path), export_format="GLB", export_apply=False, use_selection=True
)
serialized = verify_exported_optical_volume(path, "glb", converted_boundary)
write_json_atomic(
    out / "RESULT.json",
    {
        "status": "passed",
        "blender": bpy.app.version_string,
        "source_blend_sha256": source_hash,
        "source_unchanged": True,
        "converted_blend_sha256": sha256_file(output),
        "glb_sha256": sha256_file(path),
        "legacy_inspection_bytes_equal": baseline_equal,
        "negative_controls": negatives,
        "group_suffix_and_shared_group_accepted": True,
        "source_layers_preserved": True,
        "authored_uv_proof": proof,
        "source_boundary": source_boundary,
        "converted_boundary": converted_boundary,
        "baked_color_samples": measured,
        "outputs": outputs,
        "scalar_proxy_row": scalar_row,
        "scalar_coverage": coverage,
        "scalar_coverage_pixel_box": [x0, y0, x1, y1],
        "normal_method": "unchanged_actual_mesh_tangent_bake",
        "temporary_proxies_removed": True,
        "serialized_optical_volume": serialized,
    },
)
print("AUTHORED_OPTICAL_METADATA_PASS", flush=True)
