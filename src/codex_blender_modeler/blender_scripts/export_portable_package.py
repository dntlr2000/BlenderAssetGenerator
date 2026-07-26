from __future__ import annotations

import argparse
import copy
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import (  # noqa: E402
    object_inventory,
    operator_kwargs,
    portable_path,
    scene_source_provenance,
    sha256_file,
    write_json,
)

PORTABLE_OBJECT_PROPERTIES = frozenset(
    {
        "cbm_id",
        "cbm_instance_index",
        "cbm_asset_role",
        "cbm_lod_level",
        "cbm_collider_strategy",
    }
)
PORTABLE_MATERIAL_PROPERTIES = frozenset({"cbm_id"})
PORTABLE_ATLAS_UV_DEFAULT = "CBMPortableAtlas"
LIGHTMAP_UV_DEFAULT = "LightmapUV"
NON_RENDER_BOOLEAN_TAG = "hidden-boolean-target"


def parse_args() -> argparse.Namespace:
    """Parse one immutable portable-package export request."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--format", required=True, choices=["glb", "gltf", "fbx", "obj"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--package-root")
    parser.add_argument("--include-colliders", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--expected-material-conversion-plan-sha256")
    parser.add_argument("--expected-input-blend-sha256", required=True)
    parser.add_argument("--overwrite", action="store_true")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def verify_derived_scene(
    expected_plan_sha256: str | None,
    expected_material_conversion_plan_sha256: str | None,
) -> dict[str, Any]:
    """Verify optimization and optional material-conversion provenance in the scene."""

    scene = bpy.context.scene
    version = scene.get("cbm_portable_schema_version")
    if version != "0.7.0":
        raise RuntimeError(f"Loaded scene is not a V0.7 optimized derivative: {version!r}")
    plan_sha256 = str(scene.get("cbm_portable_plan_sha256", ""))
    if not plan_sha256:
        raise RuntimeError("Optimized scene has no embedded optimization-plan hash")
    if expected_plan_sha256 and expected_plan_sha256.lower() != plan_sha256.lower():
        raise RuntimeError("Requested optimization-plan hash does not match optimized scene")
    source_fingerprint = scene.get("cbm_portable_source_build_fingerprint")
    if not source_fingerprint:
        raise RuntimeError("Optimized scene has no embedded canonical build fingerprint")
    conversion_plan_sha256 = str(
        scene.get("cbm_portable_material_conversion_plan_sha256", "")
    )
    if expected_material_conversion_plan_sha256:
        if not conversion_plan_sha256:
            raise RuntimeError(
                "Portable scene has no embedded material-conversion-plan hash"
            )
        if (
            expected_material_conversion_plan_sha256.lower()
            != conversion_plan_sha256.lower()
        ):
            raise RuntimeError(
                "Requested material-conversion-plan hash does not match portable scene"
            )
    return {
        "plan_sha256": plan_sha256,
        "material_conversion_plan_sha256": conversion_plan_sha256 or None,
        "source_build_fingerprint": str(source_fingerprint),
        "source_scene_spec_sha256": scene.get(
            "cbm_portable_source_scene_spec_sha256"
        ),
    }


def object_source_tags(source: bpy.types.Object) -> set[str]:
    """Normalize CBM source tags before selecting portable export geometry."""

    raw_tags = source.get("cbm_tags", "")
    if isinstance(raw_tags, str):
        return {
            item.strip().casefold()
            for item in raw_tags.split(",")
            if item.strip()
        }
    if isinstance(raw_tags, (list, tuple)):
        return {
            str(item).strip().casefold()
            for item in raw_tags
            if str(item).strip()
        }
    return set()


def select_portable_objects(include_colliders: bool) -> list[bpy.types.Object]:
    """Select only derived render/LOD objects and optionally their collider proxies."""

    permitted = {"render", "lod"}
    if include_colliders:
        permitted.add("collider")
    unsafe_helpers = sorted(
        obj.name
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and str(obj.get("cbm_asset_role", "")) in permitted
        and (
            NON_RENDER_BOOLEAN_TAG in object_source_tags(obj)
            or (
                str(obj.get("cbm_asset_role", "")) in {"render", "lod"}
                and (
                    bool(obj.hide_render)
                    or bool(obj.get("cbm_source_hide_render", False))
                )
            )
        )
    )
    if unsafe_helpers:
        raise RuntimeError(
            "Portable export scene contains canonical non-render helpers in export roles: "
            f"{unsafe_helpers}"
        )
    bpy.ops.object.select_all(action="DESELECT")
    selected = []
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        if obj.type != "MESH" or str(obj.get("cbm_asset_role", "")) not in permitted:
            continue
        obj.hide_set(False)
        obj.select_set(True)
        selected.append(obj)
    if not selected:
        raise RuntimeError("No portable derived objects matched the export policy")
    bpy.context.view_layer.objects.active = selected[0]
    return selected


def _uv_layer_snapshots(mesh: bpy.types.Mesh) -> list[dict[str, Any]]:
    """Copy UV names, flags, and per-loop coordinates before collection reordering."""

    snapshots: list[dict[str, Any]] = []
    for layer in mesh.uv_layers:
        snapshots.append(
            {
                "name": str(layer.name),
                "active_render": bool(layer.active_render),
                "coordinates": [
                    (float(loop.uv.x), float(loop.uv.y)) for loop in layer.data
                ],
            }
        )
    return snapshots


def _replace_uv_layers(
    mesh: bpy.types.Mesh,
    snapshots: list[dict[str, Any]],
) -> None:
    """Rebuild one mesh UV collection in a deterministic order without changing values."""

    while mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[0])
    for index, snapshot in enumerate(snapshots):
        layer = mesh.uv_layers.new(name=str(snapshot["name"]), do_init=False)
        coordinates = list(snapshot["coordinates"])
        if len(coordinates) != len(layer.data):
            raise RuntimeError(
                f"UV loop count changed while reordering {mesh.name!r}: "
                f"{len(coordinates)} -> {len(layer.data)}"
            )
        for loop, coordinate in zip(layer.data, coordinates, strict=True):
            loop.uv = coordinate
        layer.active_render = index == 0
    mesh.uv_layers.active_index = 0
    mesh.update()


def _verify_fbx_tangent_basis(
    obj: bpy.types.Object,
    uv_set: str,
) -> None:
    """Fail closed when a render mesh cannot produce finite tangents from portable UV0."""

    mesh = obj.data
    calculator = getattr(mesh, "calc_tangents", None)
    if calculator is None:
        raise RuntimeError("Blender runtime exposes no tangent calculator for FBX export")
    try:
        calculator(uvmap=uv_set)
        invalid = 0
        for loop in mesh.loops:
            values = tuple(float(value) for value in loop.tangent)
            sign = float(loop.bitangent_sign)
            if not all(value == value and abs(value) != float("inf") for value in (*values, sign)):
                invalid += 1
        if invalid:
            raise RuntimeError(
                f"{obj.name!r} has {invalid} invalid tangent loops on {uv_set!r}"
            )
    finally:
        freer = getattr(mesh, "free_tangents", None)
        if freer is not None:
            freer()


def normalize_fbx_uv_bindings(
    selected: list[bpy.types.Object],
    *,
    material_conversion_plan_sha256: str | None,
) -> dict[str, Any]:
    """Promote the portable atlas to FBX UV0 and bind tangent generation to that set."""

    if not material_conversion_plan_sha256:
        return {"status": "not_applicable", "reason": "no_material_conversion"}
    atlas_uv_set = str(
        bpy.context.scene.get(
            "cbm_portable_material_atlas_uv", PORTABLE_ATLAS_UV_DEFAULT
        )
    )
    if not atlas_uv_set:
        raise RuntimeError("Portable material conversion did not declare an atlas UV set")
    mesh_records: dict[int, dict[str, Any]] = {}
    object_records: list[dict[str, Any]] = []
    for obj in selected:
        if str(obj.get("cbm_asset_role", "")) not in {"render", "lod"}:
            continue
        mesh = obj.data
        mesh_key = int(mesh.as_pointer())
        if mesh_key not in mesh_records:
            snapshots = _uv_layer_snapshots(mesh)
            by_name = {str(item["name"]): item for item in snapshots}
            if atlas_uv_set not in by_name:
                raise RuntimeError(
                    f"{obj.name!r} is missing portable atlas UV {atlas_uv_set!r}"
                )
            ordered_names = [atlas_uv_set]
            if LIGHTMAP_UV_DEFAULT in by_name:
                ordered_names.append(LIGHTMAP_UV_DEFAULT)
            ordered_names.extend(
                name for name in by_name if name not in set(ordered_names)
            )
            _replace_uv_layers(mesh, [by_name[name] for name in ordered_names])
            actual_names = [str(layer.name) for layer in mesh.uv_layers]
            if actual_names != ordered_names or not mesh.uv_layers[0].active_render:
                raise RuntimeError(
                    f"FBX UV ordering verification failed for {obj.name!r}: {actual_names}"
                )
            mesh_records[mesh_key] = {
                "uv_layers": actual_names,
                "lightmap_uv_channel_index": (
                    actual_names.index(LIGHTMAP_UV_DEFAULT)
                    if LIGHTMAP_UV_DEFAULT in actual_names
                    else None
                ),
            }
        _verify_fbx_tangent_basis(obj, atlas_uv_set)
        object_records.append(
            {
                "object_name": str(obj.name),
                "semantic_id": str(obj.get("cbm_id", "")),
                "asset_role": str(obj.get("cbm_asset_role", "")),
                "required_uv_set": atlas_uv_set,
                "required_uv_channel_index": 0,
                "tangent_uv_set": atlas_uv_set,
                **mesh_records[mesh_key],
            }
        )
    if not object_records:
        raise RuntimeError("Portable FBX material conversion has no render or LOD meshes")
    lightmap_indices = {
        item["lightmap_uv_channel_index"]
        for item in object_records
        if item["lightmap_uv_channel_index"] is not None
    }
    if lightmap_indices - {1}:
        raise RuntimeError("Portable FBX lightmap UV must occupy channel index 1")
    return {
        "status": "verified",
        "scope": "all_render_and_lod_objects",
        "required_uv_set": atlas_uv_set,
        "required_uv_channel_index": 0,
        "destination_semantic": "TEXCOORD_0",
        "tangent_uv_set": atlas_uv_set,
        "normal_map_uv_set": atlas_uv_set,
        "lightmap_uv_set": LIGHTMAP_UV_DEFAULT if lightmap_indices else None,
        "lightmap_uv_channel_index": 1 if lightmap_indices else None,
        "verified_object_count": len(object_records),
        "objects": object_records,
    }


def _retain_custom_properties(owner: Any, allowed: frozenset[str]) -> int:
    """Remove every exportable custom property except an explicit portable whitelist."""

    removed = 0
    for key in list(owner.keys()):
        if str(key) in allowed:
            continue
        del owner[key]
        removed += 1
    return removed


def sanitize_export_custom_properties(
    selected: list[bpy.types.Object],
) -> dict[str, int]:
    """Strip path-bearing authoring metadata while retaining portable identity fields."""

    counts = {"scene": 0, "collection": 0, "object": 0, "mesh": 0, "material": 0}
    counts["scene"] += _retain_custom_properties(bpy.context.scene, frozenset())
    for collection in bpy.data.collections:
        counts["collection"] += _retain_custom_properties(collection, frozenset())

    materials: set[bpy.types.Material] = set()
    meshes: set[bpy.types.Mesh] = set()
    for obj in selected:
        counts["object"] += _retain_custom_properties(
            obj, PORTABLE_OBJECT_PROPERTIES
        )
        if obj.type == "MESH" and obj.data is not None:
            meshes.add(obj.data)
        for slot in obj.material_slots:
            if slot.material is not None:
                materials.add(slot.material)
    for mesh in meshes:
        counts["mesh"] += _retain_custom_properties(mesh, frozenset())
    for material in materials:
        counts["material"] += _retain_custom_properties(
            material, PORTABLE_MATERIAL_PROPERTIES
        )
    return counts


def normalize_obj_material_names(selected: list[bpy.types.Object]) -> None:
    """Expose stable CBM material IDs through OBJ's material-name-only contract."""

    by_id: dict[str, set[bpy.types.Material]] = {}
    for obj in selected:
        for slot in obj.material_slots:
            material = slot.material
            if material is None:
                continue
            material_id = str(material.get("cbm_id") or material.name)
            by_id.setdefault(material_id, set()).add(material)
    duplicates = sorted(
        material_id for material_id, materials in by_id.items() if len(materials) != 1
    )
    if duplicates:
        raise RuntimeError(
            "OBJ export requires one material datablock per stable material ID: "
            + ", ".join(duplicates)
        )
    for material_id, materials in sorted(by_id.items()):
        material = next(iter(materials))
        collision = bpy.data.materials.get(material_id)
        if collision is not None and collision is not material:
            collision.name = f"CBM_UNEXPORTED_{collision.name}"
        material.name = material_id
        if material.name != material_id:
            raise RuntimeError(f"OBJ material name could not preserve ID {material_id!r}")


def selected_image_dependencies(selected: list[bpy.types.Object]) -> list[Path]:
    """Collect unique file-backed images referenced by selected export materials."""

    dependencies: dict[str, Path] = {}
    for obj in selected:
        for slot in obj.material_slots:
            material = slot.material
            if material is None or not material.use_nodes or material.node_tree is None:
                continue
            for node in material.node_tree.nodes:
                image = getattr(node, "image", None)
                if image is None or image.packed_file is not None or not image.filepath:
                    continue
                source = Path(
                    bpy.path.abspath(image.filepath, library=image.library)
                ).resolve()
                if not source.is_file():
                    raise FileNotFoundError(
                        f"Selected material image dependency is missing: {source}"
                    )
                existing = dependencies.get(source.name)
                if existing is not None and sha256_file(existing) != sha256_file(source):
                    raise RuntimeError(
                        "OBJ image dependencies have a filename collision with different "
                        f"content: {source.name}"
                    )
                dependencies[source.name] = source
    return [dependencies[name] for name in sorted(dependencies)]


def stage_obj_image_dependencies(
    selected: list[bpy.types.Object], output_directory: Path
) -> list[Path]:
    """Copy OBJ/MTL image dependencies beside the primary asset for clean import."""

    staged: list[Path] = []
    for source in selected_image_dependencies(selected):
        target = output_directory / source.name
        if source == target.resolve():
            staged.append(target)
            continue
        if target.exists():
            if sha256_file(target) != sha256_file(source):
                raise FileExistsError(
                    f"OBJ dependency target already contains different bytes: {target}"
                )
        else:
            shutil.copy2(source, target)
        if sha256_file(target) != sha256_file(source):
            raise RuntimeError(f"OBJ dependency copy hash mismatch: {target}")
        staged.append(target)
    return staged


def _same_length_relative_path(original: bytes) -> bytes:
    """Replace one absolute FBX path with a non-escaping relative path of equal length."""

    basename = original.replace(b"\\", b"/").rsplit(b"/", 1)[-1]
    remaining = len(original) - len(basename)
    if remaining < 2 or remaining == 1:
        raise RuntimeError("FBX absolute path is too short for safe relative rewriting")
    prefix = b""
    if remaining % 2:
        prefix = b".//"
        remaining -= 3
    prefix += b"./" * (remaining // 2)
    replacement = prefix + basename
    if len(replacement) != len(original):
        raise RuntimeError("FBX path sanitizer changed a binary string length")
    return replacement


def sanitize_fbx_absolute_paths(path: Path, absolute_paths: list[Path]) -> int:
    """Rewrite every expected FBX absolute string without changing binary offsets."""

    data = bytearray(path.read_bytes())
    encoded_paths: set[bytes] = set()
    for absolute_path in absolute_paths:
        native = str(absolute_path.resolve()).encode("utf-8")
        encoded_paths.add(native)
        encoded_paths.add(native.replace(b"/", b"\\"))
        encoded_paths.add(native.replace(b"\\", b"/"))
    rewritten = 0
    for original in sorted(encoded_paths, key=len, reverse=True):
        occurrences = data.count(original)
        if not occurrences:
            continue
        data = bytearray(
            data.replace(original, _same_length_relative_path(original))
        )
        rewritten += occurrences
    leftovers = [value for value in encoded_paths if value in data]
    if leftovers:
        raise RuntimeError("FBX path sanitizer left an expected absolute path")
    if rewritten:
        path.write_bytes(data)
    return rewritten


def export_object_inventory(
    obj: bpy.types.Object, format_name: str
) -> dict[str, Any]:
    """Describe only the topology and identity semantics serialized by one format."""

    record = object_inventory(obj)
    if format_name != "obj" or obj.type != "MESH":
        return record
    topology = record.get("topology")
    if not isinstance(topology, dict):
        return record
    layers = topology.get("uv_layers")
    if not isinstance(layers, list) or not layers:
        return record
    active = next(
        (layer for layer in layers if bool(layer.get("active_render"))),
        layers[0],
    )
    serialized = copy.deepcopy(active)
    serialized["name"] = "UVMap"
    serialized["active_render"] = True
    topology["uv_layers"] = [serialized]
    return record


def export_gltf(path: Path, binary: bool) -> str:
    """Export selected objects through the runtime-probed glTF operator."""

    operator = getattr(getattr(bpy.ops, "export_scene", None), "gltf", None)
    if operator is None:
        raise RuntimeError("This Blender build exposes no glTF exporter")
    candidates = {
        "filepath": str(path),
        "export_format": "GLB" if binary else "GLTF_SEPARATE",
        "use_selection": True,
        "export_extras": True,
        "export_materials": "EXPORT",
        "export_texcoords": True,
        "export_normals": True,
        "export_tangents": True,
        "export_apply": False,
        "export_yup": True,
    }
    operator(**operator_kwargs(operator, candidates))
    return "bpy.ops.export_scene.gltf"


def export_fbx(path: Path) -> str:
    """Export selected objects through the feature-probed FBX operator."""

    operator = getattr(getattr(bpy.ops, "export_scene", None), "fbx", None)
    if operator is None:
        raise RuntimeError("This Blender build exposes no FBX exporter")
    candidates = {
        "filepath": str(path),
        "use_selection": True,
        "use_custom_props": True,
        "apply_unit_scale": True,
        "apply_scale_options": "FBX_SCALE_UNITS",
        "path_mode": "STRIP",
        "embed_textures": False,
        "use_metadata": False,
        "object_types": {"MESH"},
        "add_leaf_bones": False,
        "bake_anim": False,
        "use_tspace": True,
        "axis_forward": "-Z",
        "axis_up": "Y",
    }
    kwargs = operator_kwargs(operator, candidates)
    if kwargs.get("use_tspace") is not True:
        raise RuntimeError("Blender FBX exporter exposes no tangent-space export option")
    operator(**kwargs)
    return "bpy.ops.export_scene.fbx"


def export_obj(path: Path) -> str:
    """Export selected geometry using the modern OBJ operator with a legacy fallback."""

    modern = getattr(getattr(bpy.ops, "wm", None), "obj_export", None)
    if modern is not None:
        candidates = {
            "filepath": str(path),
            "export_selected_objects": True,
            "export_materials": True,
            "export_uv": True,
            "export_normals": True,
            "path_mode": "COPY",
            "forward_axis": "NEGATIVE_Z",
            "up_axis": "Y",
        }
        modern(**operator_kwargs(modern, candidates))
        return "bpy.ops.wm.obj_export"
    legacy = getattr(getattr(bpy.ops, "export_scene", None), "obj", None)
    if legacy is not None:
        candidates = {
            "filepath": str(path),
            "use_selection": True,
            "use_materials": True,
            "use_uvs": True,
            "use_normals": True,
            "path_mode": "COPY",
            "axis_forward": "-Z",
            "axis_up": "Y",
        }
        legacy(**operator_kwargs(legacy, candidates))
        return "bpy.ops.export_scene.obj"
    raise RuntimeError("This Blender build exposes no OBJ exporter")


def export_selected(format_name: str, output: Path) -> str:
    """Dispatch one whitelisted portable export format."""

    if format_name == "glb":
        return export_gltf(output, binary=True)
    if format_name == "gltf":
        return export_gltf(output, binary=False)
    if format_name == "fbx":
        return export_fbx(output)
    if format_name == "obj":
        return export_obj(output)
    raise ValueError(f"Unsupported export format: {format_name!r}")


def coordinate_contract(format_name: str) -> dict[str, Any]:
    """Record declared export axes and units without claiming file-metadata inspection."""

    return {
        "format": format_name,
        "source_up_axis": "+Z",
        "export_up_axis": "+Y",
        "export_forward_axis": "-Z",
        "source_contract_units": "meters",
        "unit_scale_m": 1.0,
        "evidence": "export_operator_configuration",
        "file_metadata_verified": False,
    }


def format_warnings(format_name: str) -> list[str]:
    """Describe format losses that V0.7 does not hide or reconstruct automatically."""

    warnings: list[str] = []
    if format_name == "obj":
        warnings.append(
            "OBJ cannot preserve CBM custom semantic properties during round-trip."
        )
        warnings.append(
            "OBJ preserves only the active render UV set; additional derived UV layers "
            "remain available only in the optimized Blender scene."
        )
    if format_name in {"fbx", "obj"}:
        warnings.append(
            f"{format_name.upper()} material semantics are format-limited; raw PBR "
            "sidecars remain authoritative for downstream material reconstruction."
        )
    return warnings


def package_files(root: Path) -> list[dict[str, Any]]:
    """Inventory every regular package file with a portable relative path and digest."""

    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        files.append(
            {
                "path": portable_path(path, root),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return files


def main() -> None:
    """Export an immutable package from derived objects and write its provenance manifest."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    root = (
        Path(args.package_root).expanduser().resolve()
        if args.package_root
        else output.parent
    )
    root.mkdir(parents=True, exist_ok=True)
    portable_path(output, root)
    portable_path(manifest_path, root)
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Portable export already exists: {output}")
    if manifest_path.exists() and not args.overwrite:
        raise FileExistsError(f"Package manifest already exists: {manifest_path}")

    source_provenance = scene_source_provenance(bpy.context.scene)
    input_blend = Path(bpy.data.filepath).resolve()
    input_blend_sha256 = sha256_file(input_blend)
    if input_blend_sha256 != args.expected_input_blend_sha256.lower():
        raise RuntimeError("Loaded portable input blend SHA-256 does not match the request")
    derivative = verify_derived_scene(
        args.expected_plan_sha256,
        args.expected_material_conversion_plan_sha256,
    )
    selected = select_portable_objects(args.include_colliders)
    uv_binding_contract = (
        normalize_fbx_uv_bindings(
            selected,
            material_conversion_plan_sha256=derivative.get(
                "material_conversion_plan_sha256"
            ),
        )
        if args.format == "fbx"
        else {"status": "not_applicable", "reason": "format_is_not_fbx"}
    )
    sanitization = sanitize_export_custom_properties(selected)
    if args.format == "obj":
        normalize_obj_material_names(selected)
    before = {path.resolve() for path in root.rglob("*") if path.is_file()}
    output.parent.mkdir(parents=True, exist_ok=True)
    staged_dependencies = (
        stage_obj_image_dependencies(selected, output.parent)
        if args.format in {"fbx", "obj"}
        else []
    )
    operator = export_selected(args.format, output)
    fbx_path_rewrite_count = (
        sanitize_fbx_absolute_paths(
            output,
            [input_blend, output, *staged_dependencies],
        )
        if args.format == "fbx"
        else 0
    )
    if sha256_file(input_blend) != input_blend_sha256:
        raise RuntimeError("Portable input blend changed while the export was running")
    after = {path.resolve() for path in root.rglob("*") if path.is_file()}
    created = sorted((after - before) | {output.resolve()})
    if output.resolve() not in after:
        raise RuntimeError(f"Exporter returned without creating its primary output: {output}")

    files = [
        {
            "path": portable_path(path, root),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in created
    ]
    manifest = {
        "schema_version": "0.7.0",
        "kind": "portable_export_evidence",
        "ok": True,
        "format": args.format,
        "operator": operator,
        "primary_file": portable_path(output, root),
        "include_colliders": bool(args.include_colliders),
        "source": {
            **source_provenance,
            **derivative,
            "optimized_blend_sha256": sha256_file(Path(bpy.data.filepath).resolve()),
        },
        "runtime": {"blender_version": bpy.app.version_string},
        "custom_property_sanitization": {
            "policy": "portable_identity_whitelist",
            "allowed_object_properties": sorted(PORTABLE_OBJECT_PROPERTIES),
            "allowed_material_properties": sorted(PORTABLE_MATERIAL_PROPERTIES),
            "removed_property_counts": sanitization,
        },
        "path_sanitization": {
            "fbx_same_length_relative_rewrite_count": fbx_path_rewrite_count,
        },
        "coordinate_contract": coordinate_contract(args.format),
        "uv_binding_contract": uv_binding_contract,
        "objects": [export_object_inventory(obj, args.format) for obj in selected],
        "semantic_ids": sorted(
            {str(obj.get("cbm_id")) for obj in selected if obj.get("cbm_id")}
        ),
        "material_ids": sorted(
            {
                material_id
                for obj in selected
                for material_id in object_inventory(obj, include_topology=False)[
                    "material_ids"
                ]
            }
        ),
        "files": files,
        "warnings": format_warnings(args.format),
    }
    write_json(manifest_path, manifest)
    print(
        "CBM_ASSET_PACKAGE_OK "
        f"format={args.format} objects={len(selected)} output={output} "
        f"manifest={manifest_path}"
    )


if __name__ == "__main__":
    main()
