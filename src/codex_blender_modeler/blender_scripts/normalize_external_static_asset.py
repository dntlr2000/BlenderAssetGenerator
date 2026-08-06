from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bmesh
import bpy
from mathutils import Matrix

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import (  # noqa: E402
    object_inventory,
    operator_kwargs,
    sha256_file,
    write_json,
)


def parse_args() -> argparse.Namespace:
    """Parse one exact-plan-approved static normalization request."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-format", choices=("blend", "fbx", "glb"), required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--build-contract", required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--output-evidence", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def read_json_object(path: Path) -> dict[str, Any]:
    """Read one strict-enough JSON object for Blender-side plan enforcement."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def import_source(source: Path, source_format: str) -> None:
    """Import FBX/GLB sources or retain the already loaded source .blend."""

    if source_format == "blend":
        return
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    if source_format == "fbx":
        bpy.ops.import_scene.fbx(
            **operator_kwargs(bpy.ops.import_scene.fbx, {"filepath": str(source)})
        )
        return
    bpy.ops.import_scene.gltf(
        **operator_kwargs(bpy.ops.import_scene.gltf, {"filepath": str(source)})
    )


def bind_dependency_images(plan: dict[str, Any], source_root: Path) -> None:
    """Redirect unpacked image datablocks to immutable job-copied dependencies."""

    for dependency in plan.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        names = dependency.get("source_names", [])
        relative = dependency.get("path")
        if not isinstance(relative, str):
            continue
        target = (source_root / relative).resolve()
        if not target.is_file():
            raise FileNotFoundError(target)
        expected_sha256 = str(dependency.get("sha256") or "").lower()
        if not expected_sha256 or sha256_file(target) != expected_sha256:
            raise RuntimeError(f"Planned image dependency hash mismatch: {relative}")
        for name in names if isinstance(names, list) else []:
            image = bpy.data.images.get(str(name))
            if image is None:
                raise RuntimeError(f"Planned image dependency is absent after import: {name}")
            image.filepath = str(target)
            image.filepath_raw = str(target)
            image.reload()


def default_material() -> bpy.types.Material:
    """Create the deterministic neutral fallback used by material-less source objects."""

    material = bpy.data.materials.get("__cbm_default__")
    if material is None:
        material = bpy.data.materials.new("__cbm_default__")
        material.use_nodes = True
    return material


def evaluated_mesh(source: bpy.types.Object) -> bpy.types.Mesh:
    """Freeze evaluated static geometry while preserving UV and material data layers."""

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(depsgraph)
    return bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )


def retain_material_partition(
    mesh: bpy.types.Mesh,
    material_indices: list[int],
) -> None:
    """Keep only one planned material partition and normalize its slot index to zero."""

    if not material_indices:
        for polygon in mesh.polygons:
            polygon.material_index = 0
        return
    allowed = set(material_indices)
    editable = bmesh.new()
    try:
        editable.from_mesh(mesh)
        rejected = [face for face in editable.faces if int(face.material_index) not in allowed]
        if rejected:
            bmesh.ops.delete(editable, geom=rejected, context="FACES")
        loose_edges = [edge for edge in editable.edges if not edge.link_faces]
        if loose_edges:
            bmesh.ops.delete(editable, geom=loose_edges, context="EDGES")
        loose_vertices = [vertex for vertex in editable.verts if not vertex.link_faces]
        if loose_vertices:
            bmesh.ops.delete(editable, geom=loose_vertices, context="VERTS")
        for face in editable.faces:
            face.material_index = 0
        editable.to_mesh(mesh)
    finally:
        editable.free()
    mesh.validate(verbose=False, clean_customdata=False)
    mesh.update()


def apply_scale(obj: bpy.types.Object) -> None:
    """Apply only object scale so V0.7 preflight receives unit scale transforms."""

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.select_set(False)


def sanitize_normalized_file(current_scene: bpy.types.Scene) -> None:
    """Strip scripts and unused source datablocks before publishing the derivative blend."""

    for text in list(bpy.data.texts):
        bpy.data.texts.remove(text)
    for scene in list(bpy.data.scenes):
        if scene != current_scene:
            bpy.data.scenes.remove(scene)
    current_scene.use_nodes = False
    current_scene.world = None
    try:
        bpy.data.orphans_purge(do_recursive=True)
    except TypeError:
        bpy.data.orphans_purge()


def main() -> None:
    """Create a clean, semantic, static authoring derivative without touching the source."""

    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    plan_path = Path(args.plan).expanduser().resolve()
    output_blend = Path(args.output_blend).expanduser().resolve()
    output_evidence = Path(args.output_evidence).expanduser().resolve()
    build_contract_path = Path(args.build_contract).expanduser().resolve()
    if sha256_file(source) != args.expected_source_sha256.lower():
        raise RuntimeError("External source hash changed before normalization")
    if sha256_file(plan_path) != args.expected_plan_sha256.lower():
        raise RuntimeError("External intake plan hash changed before normalization")
    if output_blend.exists() or output_evidence.exists():
        raise FileExistsError("External normalization outputs must not overwrite existing files")
    plan = read_json_object(plan_path)
    build_contract = read_json_object(build_contract_path)
    if str(build_contract.get("fingerprint") or "") != args.build_fingerprint.lower():
        raise RuntimeError("External build contract fingerprint is stale")
    if plan.get("status") != "awaiting_user_approval":
        raise RuntimeError("Only an approvable external intake plan may be normalized")
    import_source(source, args.source_format)
    bind_dependency_images(plan, source.parents[2])

    source_objects = {obj.name: obj for obj in bpy.context.scene.objects}
    source_materials = {material.name: material for material in bpy.data.materials}
    build_materials = build_contract.get("materials")
    if not isinstance(build_materials, dict):
        raise ValueError("External build contract lacks material provenance")
    job_root = source.parents[2]
    material_by_id: dict[str, bpy.types.Material] = {}
    for record in plan.get("materials", []):
        source_name = str(record["source_name"])
        material_id = str(record["material_id"])
        material = (
            default_material()
            if source_name == "__cbm_default__"
            else source_materials.get(source_name)
        )
        if material is None:
            raise RuntimeError(f"Planned source material is missing: {source_name}")
        material.name = material_id
        material["cbm_id"] = material_id
        material["cbm_external_source_name"] = source_name
        material["cbm_external_node_fingerprint"] = str(record["node_fingerprint"])
        build_material = build_materials.get(material_id)
        if not isinstance(build_material, dict):
            raise RuntimeError(f"Build provenance lacks material {material_id}")
        material["cbm_material_source_fingerprint"] = str(
            build_material["fingerprint"]
        )
        material["cbm_shader_recipe"] = str(
            (job_root / str(build_material["shader_recipe_path"])).resolve()
        )
        material["cbm_shader_recipe_sha256"] = str(
            build_material["shader_recipe_sha256"]
        )
        material["cbm_mapping_mode"] = str(build_material["mapping_mode"])
        material["cbm_uv_set"] = "UVMap"
        material["cbm_intended_scale_m"] = 1.0
        material["cbm_shader_family"] = "standard_pbr"
        material["cbm_texture_strategy"] = "none"
        material_by_id[material_id] = material

    clean_collection = bpy.data.collections.new("CBM_EXTERNAL_AUTHORING")
    bpy.context.scene.collection.children.link(clean_collection)
    normalized: dict[str, bpy.types.Object] = {}
    source_world: dict[str, Any] = {}
    normalization = plan.get("normalization", {})
    unit_scale = float(normalization.get("source_unit_scale_to_meters", 1.0))
    if not 1e-9 <= unit_scale <= 1e9:
        raise ValueError("External source unit scale is outside the approved bounds")
    unit_matrix = Matrix.Scale(unit_scale, 4)
    for record in plan.get("objects", []):
        source_name = str(record["source_name"])
        semantic_id = str(record["semantic_id"])
        source_obj = source_objects.get(source_name)
        if source_obj is None or source_obj.type not in {"MESH", "CURVE"}:
            raise RuntimeError(f"Planned static source object is missing: {source_name}")
        mesh = evaluated_mesh(source_obj)
        retain_material_partition(
            mesh,
            [int(value) for value in record.get("source_material_indices", [])],
        )
        if not mesh.polygons:
            bpy.data.meshes.remove(mesh)
            raise RuntimeError(f"Planned external submesh has no polygons: {semantic_id}")
        target = bpy.data.objects.new(semantic_id, mesh)
        clean_collection.objects.link(target)
        target.matrix_world = unit_matrix @ source_obj.matrix_world.copy()
        target["cbm_id"] = semantic_id
        target["cbm_asset_role"] = "authoring"
        target["cbm_qa_role"] = str(record.get("qa_role", "supporting"))
        target["cbm_external_source_name"] = source_name
        planned_materials = [str(value) for value in record.get("material_ids", [])]
        if not planned_materials:
            planned_materials = ["mat.default"]
        target.data.materials.clear()
        for material_id in planned_materials:
            material = material_by_id.get(material_id)
            if material is None:
                raise RuntimeError(
                    f"Object {semantic_id} references missing material {material_id}"
                )
            target.data.materials.append(material)
        source_world[semantic_id] = target.matrix_world.copy()
        normalized[semantic_id] = target

    for semantic_id, target in normalized.items():
        apply_scale(target)
        source_world[semantic_id] = target.matrix_world.copy()
    for record in plan.get("objects", []):
        semantic_id = str(record["semantic_id"])
        parent_id = record.get("parent_semantic_id")
        if parent_id:
            target = normalized[semantic_id]
            target.parent = normalized[str(parent_id)]
            target.matrix_world = source_world[semantic_id]

    for obj in list(bpy.data.objects):
        if obj not in normalized.values():
            bpy.data.objects.remove(obj, do_unlink=True)
    for collection in list(bpy.data.collections):
        if collection != clean_collection and collection.users == 0:
            bpy.data.collections.remove(collection)

    scene = bpy.context.scene
    sanitize_normalized_file(scene)
    # The geometry has already been converted into meter-valued coordinates above.
    # Reset display/export units so downstream exporters cannot apply the source scale twice.
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.unit_settings.length_unit = "METERS"

    try:
        bpy.ops.file.pack_all()
    except RuntimeError as exc:
        raise RuntimeError(f"External image dependencies could not be packed: {exc}") from exc

    scene["cbm_job_id"] = str(plan["job_id"])
    scene["cbm_source_kind"] = "external_static_asset"
    scene["cbm_schema_version"] = "external-static-asset-0.9.0"
    scene["cbm_external_intake_plan_sha256"] = args.expected_plan_sha256.lower()
    scene["cbm_external_source_sha256"] = args.expected_source_sha256.lower()
    scene["cbm_external_asset_manifest_sha256"] = "pending-host-manifest"
    scene["cbm_material_build_fingerprint"] = args.build_fingerprint.lower()
    scene["cbm_build_provenance"] = json.dumps(
        {
            "source_kind": "external_static_asset",
            "job_id": str(plan["job_id"]),
            "intake_plan_sha256": args.expected_plan_sha256.lower(),
            "external_source_sha256": args.expected_source_sha256.lower(),
            "fingerprint": args.build_fingerprint.lower(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    output_blend.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_blend.with_name(output_blend.stem + ".partial.blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(temporary))
    temporary.replace(output_blend)
    records = [
        {
            **object_inventory(obj),
            "source_name": str(obj.get("cbm_external_source_name")),
            "qa_role": str(obj.get("cbm_qa_role")),
            "parent_semantic_id": obj.parent.get("cbm_id") if obj.parent else None,
        }
        for obj in sorted(normalized.values(), key=lambda item: str(item.get("cbm_id")))
    ]
    evidence = {
        "schema_version": "0.9.0",
        "kind": "external_static_asset_normalization_evidence",
        "ok": True,
        "job_id": str(plan["job_id"]),
        "source_sha256": args.expected_source_sha256.lower(),
        "plan_sha256": args.expected_plan_sha256.lower(),
        "build_fingerprint": args.build_fingerprint.lower(),
        "source_unit_scale_to_meters": unit_scale,
        "normalized_unit_system": scene.unit_settings.system,
        "normalized_unit_scale_length": float(scene.unit_settings.scale_length),
        "normalized_length_unit": scene.unit_settings.length_unit,
        "normalized_blend_sha256": sha256_file(output_blend),
        "objects": records,
        "materials": [
            {
                "source_name": str(material.get("cbm_external_source_name")),
                "material_name": material.name,
                "material_id": str(material.get("cbm_id")),
                "node_fingerprint": str(material.get("cbm_external_node_fingerprint")),
            }
            for material in sorted(material_by_id.values(), key=lambda item: item.name)
        ],
        "sanitization": {
            "text_block_count": len(bpy.data.texts),
            "scene_count": len(bpy.data.scenes),
            "action_count": len(bpy.data.actions),
            "armature_count": len(bpy.data.armatures),
            "autoexec_disabled": True,
        },
        "runtime": {"blender_version": bpy.app.version_string},
    }
    write_json(output_evidence, evidence)
    print(f"CBM_EXTERNAL_INTAKE_NORMALIZED output={output_blend}")


if __name__ == "__main__":
    main()
