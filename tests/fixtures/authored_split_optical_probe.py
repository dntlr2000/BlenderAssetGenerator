"""Actual source/split GLB optical transport proof, with no package or human acceptance."""
# ruff: noqa: E402

import argparse
import hashlib
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--job-root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
sys.path[:0] = [
    str(args.repo / "src"),
    str(args.repo / "src/codex_blender_modeler/blender_scripts"),
]
import bpy
import export_scene
from authored_split_native import native_materials
from optical_volume_runtime import (
    validate_imported_optical_volume,
    validate_optical_volume_objects,
    verify_exported_optical_volume,
)

from codex_blender_modeler import authored_split_runtime as runtime
from codex_blender_modeler.optical_volume_gltf import load_optical_gltf

root = args.job_root.resolve(strict=True)
checked = runtime.validate_transaction(root, "split01")
assert (
    runtime.collect_preserved_authored_split_provenance(root)
    == checked["candidates"]["prospective_build_provenance"]
)
args.output.mkdir(exist_ok=False)
rows = {}
for stage in ("source", "preserved_split"):
    selected = (
        checked["plan"]["source_files"]["blender/scene.blend"]
        if stage == "source"
        else runtime.reference(root, "blender/scene.blend")
    )
    bpy.ops.wm.open_mainfile(filepath=str(root / selected["path"]), load_ui=False)
    if stage == "source":
        # Archived bytes were authored at canonical blender/scene.blend. Resolve their
        # original relative FILE locators against that exact original location only.
        for material in bpy.data.materials:
            for node in material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image is not None:
                    raw = node.image.filepath
                    path = (
                        (root / "blender" / raw[2:]).resolve(strict=True)
                        if raw.startswith("//")
                        else Path(raw).resolve(strict=True)
                    )
                    runtime.reference(root, path.relative_to(root).as_posix())
                    node.image.filepath = str(path)
    reference = checked["preapproval"][
        "source_native_inventory" if stage == "source" else "candidate_native_inventory"
    ]
    observed = json.loads(runtime.read(root, reference))
    assert native_materials(root) == observed["native_materials"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    native = validate_optical_volume_objects(meshes, require_stored_geometry=True)
    assert len(native) == 4
    output = args.output / f"{stage}.glb"
    argv = sys.argv
    sys.argv = ["blender", "--", "--format", "glb", "--output", str(output)]
    try:
        export_scene.main()
    finally:
        sys.argv = argv
    serialized = verify_exported_optical_volume(output, "glb", native, strict_opt_in=True)
    document = load_optical_gltf(output, "glb")
    serialized_materials = {
        item["name"]: item.get("extensions", {}) for item in document["materials"]
    }
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(output))
    imported = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    actual = validate_imported_optical_volume(imported, native)
    assert len(actual) == 4
    imported_factors = {}
    for obj in imported:
        material = obj.data.materials[0]
        shader = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
        absorption = next(
            node for node in material.node_tree.nodes if node.type == "VOLUME_ABSORPTION"
        )
        thickness = next(
            node
            for node in material.node_tree.nodes
            if node.type == "GROUP" and node.node_tree.name.startswith("glTF Material Output")
        )
        imported_factors[obj.name] = {
            "material": material.name,
            "transmission": shader.inputs["Transmission Weight"].default_value,
            "ior": shader.inputs["IOR"].default_value,
            "thickness": thickness.inputs["Thickness"].default_value,
            "attenuation_color": list(absorption.inputs["Color"].default_value),
            "absorption_density": absorption.inputs["Density"].default_value,
        }
    assert runtime.reference(root, selected["path"]) == selected
    rows[stage] = {
        "blend": selected,
        "glb_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "glb_path": str(output),
        "native_optical_boundaries": native,
        "serialized_verification": serialized,
        "serialized_extensions": serialized_materials,
        "imported_verification": actual,
        "actual_imported_factors": imported_factors,
    }
source = {row["object"]: row for row in rows["source"]["native_optical_boundaries"]}
for row in rows["preserved_split"]["native_optical_boundaries"]:
    old = source[row["object"]]
    assert row["contract"] == old["contract"] and row["surface"] == old["surface"]
    expected = next(
        (
            rule["new_material_id"]
            for rule in checked["plan"]["clone_rules"]
            if rule["target_object_id"] == row["object"]
        ),
        old["material_id"],
    )
    assert row["material_id"] == expected
    before = rows["source"]["actual_imported_factors"][row["object"]]
    after = rows["preserved_split"]["actual_imported_factors"][row["object"]]
    assert after["material"] == expected
    assert {key: value for key, value in before.items() if key != "material"} == {
        key: value for key, value in after.items() if key != "material"
    }
result = {
    "status": "passed",
    "blender": bpy.app.version_string,
    "kind": "synthetic_preserved_split_native_glb_optical_parity",
    "stages": rows,
    "canonical_material_plan_promoted": False,
    "package_accepted": False,
    "destination_support_verified": False,
    "final_human_acceptance": False,
    "conversion_or_recipe_projection_used": False,
}
(args.output / "RESULT.json").write_bytes(runtime.encode(result))
print("AUTHORED_SPLIT_OPTICAL_PARITY_PASSED")
