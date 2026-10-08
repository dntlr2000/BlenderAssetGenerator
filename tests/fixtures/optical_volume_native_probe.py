"""Native opt-in volume build, conversion, GLB export/import and failure controls."""
# ruff: noqa: E402

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
S = args.repo
sys.path[:0] = [str(S / "src"), str(S / "src/codex_blender_modeler/blender_scripts")]
import bpy
from common import make_material
from convert_portable_materials import (
    _portable_material,
    _portable_surface_factors,
    _surface_semantics,
)
from optical_volume_runtime import (
    read_optical_volume,
    validate_imported_optical_volume,
    validate_optical_volume_objects,
    verify_exported_optical_volume,
)

from codex_blender_modeler.shader_recipe_runtime import _validate_recipe

bpy.ops.wm.read_factory_settings(use_empty=True)
assert bpy.app.version[:3] == (5, 0, 1)
out = args.output
out.mkdir(exist_ok=False)
volume = {
    "schema_version": "0.1.0",
    "thickness_factor": 0.2,
    "attenuation_distance": 2.5,
    "attenuation_color": [0.72, 0.96, 0.83],
}
recipe = {
    "schema_version": "0.5.1",
    "material_id": "glass",
    "family": "glass",
    "volume": volume,
    "surface": {
        "base_color": [1, 1, 1, 1],
        "transmission_weight": 0.95,
        "roughness": 0.07,
        "metallic": 0,
        "alpha": 1,
        "ior": 1.46,
    },
    "mapping": {"mode": "uv", "uv_set": "UVMap", "real_world_scale_m": 1},
    "layers": [],
}
validated = _validate_recipe(recipe, "glass", Path("test.json"), "none")
mat = make_material({"id": "glass", "shader": "principled"}, shader_recipe=validated)
bpy.ops.mesh.primitive_cube_add(size=1)
obj = bpy.context.object
obj.data.materials.append(mat)
source = validate_optical_volume_objects([obj])
sem = _surface_semantics(mat)
assert sem["optical_volume"] == volume
images = {}
for channel, color in {
    "base_color": (1, 1, 1, 1),
    "roughness": (0.07, 0.07, 0.07, 1),
    "metallic": (0, 0, 0, 1),
    "normal": (0.5, 0.5, 1, 1),
    "emission": (0, 0, 0, 1),
}.items():
    im = bpy.data.images.new(channel, 4, 4, alpha=True)
    im.pixels[:] = list(color) * 16
    im.pack()
    images[channel] = im
portable = _portable_material(mat, "glass", sem, images)
obj.data.materials[0] = portable
converted = validate_optical_volume_objects([obj])
assert read_optical_volume(portable) == volume
path = out / "volume.glb"
import export_scene

original_argv = sys.argv
sys.argv = ["blender", "--", "--format", "glb", "--output", str(path)]
try:
    export_scene.main()
finally:
    sys.argv = original_argv
b = path.read_bytes()
n, t = struct.unpack_from("<II", b, 12)
d = json.loads(b[20 : 20 + n])
m = d["materials"][0]
ext = m["extensions"]
assert "KHR_materials_volume" in ext, ext
serialized = verify_exported_optical_volume(path, "glb", converted)
assert len(serialized) == 1


def f32(x):
    """Expose the exact Blender socket storage conversion."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


assert ext["KHR_materials_volume"]["thicknessFactor"] == f32(0.2)
assert ext["KHR_materials_volume"]["attenuationDistance"] == 1 / f32(1 / 2.5)
assert ext["KHR_materials_volume"]["attenuationColor"] == [
    f32(x) for x in volume["attenuation_color"]
]
# Retain source-only negative controls, with the same actual native mesh and graph.
portable.node_tree.nodes["CBM_OpticalVolume_Thickness"].inputs["Thickness"].default_value = 0.3
try:
    read_optical_volume(portable)
    raise AssertionError("tamper accepted")
except ValueError:
    pass
portable.node_tree.nodes["CBM_OpticalVolume_Thickness"].inputs["Thickness"].default_value = 0.2
import bmesh

bm = bmesh.new()
bm.from_mesh(obj.data)
bm.faces.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES")
bm.to_mesh(obj.data)
bm.free()
try:
    validate_optical_volume_objects([obj])
    raise AssertionError("open mesh accepted")
except ValueError:
    pass
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(path))
imported = [o for o in bpy.data.objects if o.type == "MESH"]
assert len(imported) == 1
p = imported[0].data.materials[0]
absorp = [n for n in p.node_tree.nodes if n.type == "VOLUME_ABSORPTION"]
assert len(absorp) == 1
import_boundary = validate_imported_optical_volume(imported, converted)
# Actual clean-import controls must fail even when the pre-import source proof was valid.
metallic = next(n for n in p.node_tree.nodes if n.type == "BSDF_PRINCIPLED").inputs["Metallic"]
assert metallic.is_linked
zero_factor = metallic.links[0].from_node.inputs[1]
assert zero_factor.default_value == 0
zero_factor.default_value = 1
try:
    validate_imported_optical_volume(imported, converted)
    raise AssertionError("changed imported metallic factor accepted")
except ValueError:
    pass
zero_factor.default_value = 0
bm = bmesh.new()
bm.from_mesh(imported[0].data)
bm.faces.ensure_lookup_table()
bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES")
bm.to_mesh(imported[0].data)
bm.free()
try:
    validate_imported_optical_volume(imported, converted)
    raise AssertionError("open imported boundary accepted")
except ValueError:
    pass
result = {
    "status": "passed",
    "blender": bpy.app.version_string,
    "source_boundary": source,
    "converted_boundary": converted,
    "surface_factors": _portable_surface_factors(sem),
    "glb_sha256": hashlib.sha256(b).hexdigest(),
    "extensions": ext,
    "native_import_absorption_color": list(absorp[0].inputs["Color"].default_value),
    "native_import_density": absorp[0].inputs["Density"].default_value,
    "actual_import_boundary": import_boundary,
    "negative_controls": [
        "changed_thickness_rejected",
        "open_boundary_rejected",
        "changed_imported_metallic_rejected",
        "open_imported_boundary_rejected",
    ],
    "actual_Unity_test": False,
    "actual_serialization_verification": serialized,
}
(out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
print("VOLUME_SMOKE_PASS", flush=True)
