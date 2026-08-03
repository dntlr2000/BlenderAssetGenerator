from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from assembly_runtime import (  # noqa: E402
    attach_assembly_metadata,
    load_assembly_contract,
)
from common import (  # noqa: E402
    apply_object_spec,
    apply_scene_relationships,
    clear_scene,
    configure_render,
    ensure_collection,
    ensure_parent,
    load_runtime_material_mappings,
    load_runtime_shader_recipes,
    make_material,
    setup_camera,
    setup_lighting,
)
from uv_runtime import ensure_uv_mapping  # noqa: E402

from codex_blender_modeler.build_provenance import (  # noqa: E402
    camera_contract_payload,
    canonical_json_text,
    collect_build_provenance,
)


def parse_args() -> argparse.Namespace:
    """Parse deterministic scene build and renderer selection arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--job-root")
    parser.add_argument("--output", required=True)
    parser.add_argument("--render-engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def main() -> None:
    """Build one canonical scene and apply optional V0.5 mapping contracts."""

    args = parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    job_root = (
        Path(args.job_root).expanduser().resolve()
        if args.job_root
        else spec_path.parent.parent
    )
    try:
        spec_path.relative_to(job_root)
    except ValueError as exc:
        raise RuntimeError("SceneSpec must remain inside the declared job root") from exc
    output = ensure_parent(args.output)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    build_provenance = collect_build_provenance(
        job_root,
        str(spec["job_id"]),
        scene_spec_path=spec_path,
        # The host CLI/MCP validates SceneSpec and InteriorScope before Blender starts.
        validate_contracts=False,
    )
    assembly_contract = load_assembly_contract(job_root)

    clear_scene()
    configure_render(args.render_engine, args.render_device)
    collection = ensure_collection("CBM_Generated")
    shader_recipes = load_runtime_shader_recipes(job_root, str(spec["job_id"]))
    material_mappings = load_runtime_material_mappings(job_root, str(spec["job_id"]))
    material_ids = {str(material["id"]) for material in spec["materials"]}
    unknown_recipe_ids = sorted(set(shader_recipes) - material_ids)
    if unknown_recipe_ids:
        raise RuntimeError(
            f"Material plan references SceneSpec materials that do not exist: {unknown_recipe_ids}"
        )
    materials = {
        material["id"]: make_material(
            material,
            job_root,
            shader_recipes.get(str(material["id"])),
        )
        for material in spec["materials"]
    }
    for material_id, material in materials.items():
        source = build_provenance["materials"].get(str(material_id))
        if source is None:
            continue
        material["cbm_material_source_fingerprint"] = source["fingerprint"]
        if source["shader_recipe_sha256"]:
            material["cbm_shader_recipe_sha256"] = source["shader_recipe_sha256"]
        if source["texture_manifest_sha256"]:
            material["cbm_texture_manifest_sha256"] = source["texture_manifest_sha256"]
    for material_id, mapping in material_mappings.items():
        material = materials.get(material_id)
        if material is None:
            raise RuntimeError(
                f"Material plan mapping references a missing SceneSpec material: {material_id}"
            )
        material["cbm_mapping_mode"] = mapping["mode"]
        material["cbm_uv_set"] = mapping["uv_set"]
        material["cbm_intended_scale_m"] = mapping["real_world_scale_m"]

    object_map: dict[str, list[bpy.types.Object]] = {}
    count = 0
    for object_spec in spec["objects"]:
        generator = object_spec.get("generator")
        instances = int(generator["count"]) if generator else 1
        built: list[bpy.types.Object] = []
        for index in range(instances):
            built_object = apply_object_spec(
                object_spec,
                materials,
                collection,
                job_root,
                index,
            )
            mapping = material_mappings.get(str(object_spec["material_id"]))
            if mapping is not None:
                ensure_uv_mapping(built_object, mapping)
            built.append(built_object)
            count += 1
        object_map[object_spec["id"]] = built

    apply_scene_relationships(spec["objects"], object_map)
    setup_camera(spec["camera"])
    setup_lighting()
    bpy.context.scene["cbm_job_id"] = spec["job_id"]
    bpy.context.scene["cbm_schema_version"] = spec["schema_version"]
    bpy.context.scene["cbm_source_spec"] = str(spec_path)
    bpy.context.scene["cbm_scene_spec_sha256"] = build_provenance["scene_spec_sha256"]
    bpy.context.scene["cbm_camera_fingerprint"] = build_provenance["camera_fingerprint"]
    bpy.context.scene["cbm_camera_source_json"] = canonical_json_text(
        camera_contract_payload(spec["camera"])
    )
    bpy.context.scene["cbm_material_build_fingerprint"] = build_provenance["fingerprint"]
    bpy.context.scene["cbm_build_provenance"] = canonical_json_text(build_provenance)
    attach_assembly_metadata(bpy.context.scene, object_map, assembly_contract)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    print(f"CBM_BUILD_OK objects={count} output={output}")


if __name__ == "__main__":
    main()
