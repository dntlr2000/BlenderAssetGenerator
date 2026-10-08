"""Pinned native regressions for actual graph, export branch and imported-boundary failures."""
# ruff: noqa: E402

import argparse
import hashlib
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
sys.path[:0] = [
    str(args.repo / "src"),
    str(args.repo / "src/codex_blender_modeler/blender_scripts"),
]
import bpy
import export_portable_package
import export_scene
import validate_export_roundtrip
from common import make_material
from optical_volume_runtime import (
    read_optical_volume,
    validate_imported_optical_volume,
    validate_optical_volume_objects,
    verify_exported_optical_volume,
)

from codex_blender_modeler.shader_recipe_runtime import _validate_recipe

out = args.output
out.mkdir(exist_ok=False)
results = []
assert bpy.app.version[:3] == (5, 0, 1)


def call_main(module, argv):
    """Invoke the real entrypoint with only its documented CLI arguments."""
    previous = sys.argv
    sys.argv = ["blender", "--", *map(str, argv)]
    try:
        module.main()
    finally:
        sys.argv = previous


def material(volume=None):
    """Author the exact whitelist recipe through the production builder."""
    volume = volume or {
        "schema_version": "0.1.0",
        "thickness_factor": 0.2,
        "attenuation_distance": None,
        "attenuation_color": [1, 1, 1],
    }
    raw = {
        "schema_version": "0.5.1",
        "material_id": "glass",
        "family": "glass",
        "surface": {"metallic": 0, "alpha": 1, "ior": 1.46, "transmission_weight": 0.9},
        "mapping": {"mode": "uv"},
        "layers": [],
        "volume": volume,
    }
    return make_material(
        {"id": "glass", "shader": "principled"},
        shader_recipe=_validate_recipe(raw, "glass", Path("probe.json"), "none"),
    )


def fresh_cube(volume=None, assign=True):
    """Start every case with isolated Blender state and one unit cube."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mat = material(volume)
    bpy.ops.mesh.primitive_cube_add(size=1)
    obj = bpy.context.object
    obj.name = "OpticalCube"
    if assign:
        obj.data.materials.append(mat)
    return obj, mat


def rejected(label, action, expected_text, output=None):
    """Require a specific bounded refusal and, when relevant, no partially written asset."""
    try:
        action()
    except ValueError as error:
        assert expected_text in str(error), (label, str(error))
        assert output is None or not output.exists(), label
        results.append({"case": label, "rejected": str(error), "output_absent": output is not None})
    else:
        raise AssertionError(label + " was accepted")


for scalar, value, message in [
    ("Metallic", 1, "metallic zero"),
    ("IOR", 4, "IOR"),
    ("Alpha", 0.5, "alpha one"),
]:
    obj, mat = fresh_cube()
    mat.node_tree.nodes.get("Principled BSDF").inputs[scalar].default_value = value
    rejected("actual_" + scalar, lambda obj=obj: validate_optical_volume_objects([obj]), message)
obj, mat = fresh_cube()
value = mat.node_tree.nodes.new("ShaderNodeValue")
value.outputs[0].default_value = 0
mat.node_tree.links.new(
    value.outputs[0], mat.node_tree.nodes.get("Principled BSDF").inputs["Metallic"]
)
rejected("linked_zero_metallic", lambda: read_optical_volume(mat), "metallic zero")
obj, mat = fresh_cube()
obj.scale = (2, 2, 2)
rejected("fresh_lazy_world_scale", lambda: validate_optical_volume_objects([obj]), "unit-scale")
obj, mat = fresh_cube()
bpy.ops.curve.primitive_bezier_curve_add()
curve = bpy.context.object
curve.data.bevel_depth = 0.1
curve.data.use_fill_caps = True
curve.data.materials.append(mat)
rejected("unsupported_curve", lambda: validate_optical_volume_objects([curve]), "mesh objects")
obj, mat = fresh_cube(assign=False)
group = bpy.data.node_groups.new("Test assignment", "GeometryNodeTree")
group.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
a = group.nodes.new("NodeGroupInput")
b = group.nodes.new("GeometryNodeSetMaterial")
b.inputs["Material"].default_value = mat
c = group.nodes.new("NodeGroupOutput")
group.links.new(a.outputs["Geometry"], b.inputs["Geometry"])
group.links.new(b.outputs["Geometry"], c.inputs["Geometry"])
obj.modifiers.new("Changed material", "NODES").node_group = group
rejected("evaluated_material_added", lambda: validate_optical_volume_objects([obj]), "bindings")
obj, mat = fresh_cube()
obj.modifiers.new("No stored proof", "BEVEL")
rejected(
    "package_stored_modifier",
    lambda: validate_optical_volume_objects([obj], require_stored_geometry=True),
    "materialized",
)
obj, mat = fresh_cube()
bpy.ops.mesh.primitive_cube_add(location=(3, 0, 0))
bpy.context.object.shape_key_add(name="Basis")
path = out / "must_not_write_shape.glb"
rejected(
    "raw_mixed_shape_key",
    lambda: call_main(export_scene, ["--format", "glb", "--output", path]),
    "shape-key",
    path,
)
for fmt in ["obj", "fbx"]:
    obj, mat = fresh_cube()
    path = out / ("must_not_write." + fmt)
    rejected(
        "volume_format_" + fmt,
        lambda fmt=fmt, path=path: call_main(export_scene, ["--format", fmt, "--output", path]),
        "requires glTF",
        path,
    )

# Orphan and unused-slot materials do not change actual legacy export behavior.
for unused_slot in [False, True]:
    obj, mat = fresh_cube(assign=False)
    if unused_slot:
        plain = bpy.data.materials.new("plain")
        obj.data.materials.append(plain)
        obj.data.materials.append(mat)
    assert validate_optical_volume_objects([obj]) == []
    for fmt in ["obj", "fbx", "glb"]:
        path = out / (f"legacy_unused_{unused_slot}." + fmt)
        call_main(export_scene, ["--format", fmt, "--output", path])
        assert path.is_file()
        results.append(
            {
                "case": f"legacy_unused_{unused_slot}_{fmt}",
                "exported": True,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

# Exercise null attenuation and both supported numeric bounds in the actual native graph.
for label, thickness, distance, color in [
    ("clear", 0.2, None, [1, 1, 1]),
    ("minimum", 1e-6, 1e-6, [1e-6] * 3),
    ("maximum", 1e6, 1e6, [1] * 3),
]:
    obj, mat = fresh_cube(
        {
            "schema_version": "0.1.0",
            "thickness_factor": thickness,
            "attenuation_distance": distance,
            "attenuation_color": color,
        }
    )
    expected = validate_optical_volume_objects([obj])
    path = out / (label + ".glb")
    call_main(export_scene, ["--format", "glb", "--output", path])
    serialized = verify_exported_optical_volume(path, "glb", expected)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = validate_imported_optical_volume(list(bpy.context.scene.objects), expected)
    results.append({"case": label, "serialization": serialized, "actual_import": imported})

# The real package and clean-import CLI path must expose the new graph/boundary evidence.
obj, mat = fresh_cube()
obj["cbm_id"] = "cube"
obj["cbm_asset_role"] = "render"
scene = bpy.context.scene
scene["cbm_portable_schema_version"] = "0.7.0"
scene["cbm_portable_plan_sha256"] = "a" * 64
scene["cbm_portable_source_build_fingerprint"] = "b" * 64
blend = out / "unit_source.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
package = out / "package"
package.mkdir()
asset = package / "asset.glb"
manifest = package / "export.json"
call_main(
    export_portable_package,
    [
        "--format",
        "glb",
        "--output",
        asset,
        "--manifest",
        manifest,
        "--package-root",
        package,
        "--expected-input-blend-sha256",
        hashlib.sha256(blend.read_bytes()).hexdigest(),
    ],
)
report = package / "roundtrip.json"
call_main(
    validate_export_roundtrip,
    [
        "--format",
        "glb",
        "--input",
        asset,
        "--expected",
        manifest,
        "--output",
        report,
        "--package-root",
        package,
    ],
)
data = json.loads(report.read_text())
assert data["ok"], data
assert data["optical_volume_roundtrip"]["status"] == "passed"
results.append(
    {
        "case": "actual_package_clean_import",
        "report": str(report),
        "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    }
)
(out / "RESULT.json").write_text(
    json.dumps(
        {"status": "passed", "blender": bpy.app.version_string, "results": results}, indent=2
    )
    + "\n"
)
print("OPTICAL_HARDENING_PASS", flush=True)
