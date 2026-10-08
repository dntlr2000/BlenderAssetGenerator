from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import secrets
import shutil
import struct
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import bmesh
import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from optical_volume_runtime import (  # noqa: E402
    validate_optical_volume_objects,
    verify_exported_optical_volume,
)
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
STATIC_PAYLOAD_OBJECT_PROPERTIES = frozenset(
    {
        "cbm_id",
        "cbm_instance_index",
        "cbm_asset_role",
    }
)
PORTABLE_MATERIAL_PROPERTIES = frozenset({"cbm_id"})
PORTABLE_ATLAS_UV_DEFAULT = "CBMPortableAtlas"
LIGHTMAP_UV_DEFAULT = "LightmapUV"
NON_RENDER_BOOLEAN_TAG = "hidden-boolean-target"


def _portable_temp_mkdir_mode(path: Any, mode: int, temp_root: Path) -> int:
    """Use inherited Windows ACLs only for glTF exporter's isolated temp children."""

    if sys.platform != "win32" or mode != 0o700:
        return mode
    try:
        candidate = Path(path).resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return mode
    return 0o777 if candidate.is_relative_to(temp_root) else mode


def _create_portable_gltf_temp_root(package_root: Path) -> Path:
    """Create a short normal-path temp root that Blender image APIs can write on Windows."""

    temp_base = Path(tempfile.gettempdir()).resolve()
    if not temp_base.is_dir():
        raise FileNotFoundError(f"Portable glTF temp base does not exist: {temp_base}")
    package_token = re.sub(r"[^A-Za-z0-9]+", "-", package_root.name).strip("-")[:16]
    package_token = package_token or "package"
    for _attempt in range(16):
        candidate = temp_base / (f"cbm-gltf-{package_token}-{os.getpid()}-{secrets.token_hex(4)}")
        try:
            candidate.mkdir(mode=0o777)
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError(f"Could not allocate a unique portable glTF temp root: {temp_base}")


@contextmanager
def portable_gltf_temp_environment(package_root: Path) -> Iterator[None]:
    """Keep Blender glTF image encoding in a short Windows-compatible temp root."""

    if sys.platform != "win32":
        yield
        return

    temp_root = _create_portable_gltf_temp_root(package_root)
    original_tempdir = tempfile.tempdir
    original_mkdir = os.mkdir
    completed = False

    def inherited_acl_mkdir(
        path: Any,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        """Translate only package-local 0o700 temp children to inherited Windows ACLs."""

        effective_mode = _portable_temp_mkdir_mode(path, mode, temp_root)
        if dir_fd is None:
            original_mkdir(path, effective_mode)
        else:
            original_mkdir(path, effective_mode, dir_fd=dir_fd)

    tempfile.tempdir = str(temp_root)
    os.mkdir = inherited_acl_mkdir
    try:
        yield
        completed = True
    finally:
        os.mkdir = original_mkdir
        tempfile.tempdir = original_tempdir
        if completed:
            temp_root.rmdir()


def parse_args() -> argparse.Namespace:
    """Parse one immutable portable-package export request."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--format", required=True, choices=["glb", "gltf", "fbx", "obj"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--package-root")
    parser.add_argument("--include-colliders", action="store_true")
    parser.add_argument("--static-payload", action="store_true")
    parser.add_argument("--asset-name")
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
    conversion_plan_sha256 = str(scene.get("cbm_portable_material_conversion_plan_sha256", ""))
    if expected_material_conversion_plan_sha256:
        if not conversion_plan_sha256:
            raise RuntimeError("Portable scene has no embedded material-conversion-plan hash")
        if expected_material_conversion_plan_sha256.lower() != conversion_plan_sha256.lower():
            raise RuntimeError(
                "Requested material-conversion-plan hash does not match portable scene"
            )
    return {
        "plan_sha256": plan_sha256,
        "material_conversion_plan_sha256": conversion_plan_sha256 or None,
        "source_build_fingerprint": str(source_fingerprint),
        "source_scene_spec_sha256": scene.get("cbm_portable_source_scene_spec_sha256"),
        "source_kind": scene.get("cbm_portable_source_kind") or "scene_spec",
        "source_external_manifest_sha256": scene.get(
            "cbm_portable_source_external_manifest_sha256"
        ),
    }


def object_source_tags(source: bpy.types.Object) -> set[str]:
    """Normalize CBM source tags before selecting portable export geometry."""

    raw_tags = source.get("cbm_tags", "")
    if isinstance(raw_tags, str):
        return {item.strip().casefold() for item in raw_tags.split(",") if item.strip()}
    if isinstance(raw_tags, (list, tuple)):
        return {str(item).strip().casefold() for item in raw_tags if str(item).strip()}
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
                and (bool(obj.hide_render) or bool(obj.get("cbm_source_hide_render", False)))
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


def normalize_static_payload_objects(
    selected: list[bpy.types.Object],
    asset_name: str,
) -> None:
    """Remove disabled-feature identity and assign deterministic consumer-facing names."""

    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", asset_name):
        raise ValueError("Static payload asset name must be one safe lowercase job ID")
    invalid = [
        obj.name
        for obj in selected
        if str(obj.get("cbm_asset_role", "")) != "render"
        or obj.get("cbm_lod_level") not in {None, 0}
        or obj.get("cbm_collider_strategy") not in {None, "", "none"}
    ]
    if invalid:
        raise RuntimeError(
            "Static payload mode requires only base render objects without physics "
            f"proxies: {sorted(invalid)}"
        )
    width = max(4, len(str(len(selected))))
    for index, obj in enumerate(selected, start=1):
        target_name = asset_name if len(selected) == 1 else f"{asset_name}_{index:0{width}d}"
        obj.name = target_name
        if obj.name != target_name:
            raise RuntimeError(f"Static payload object name is not unique: {target_name!r}")
        if obj.type == "MESH" and obj.data is not None:
            obj.data.name = f"{target_name}_mesh"
        for key in ("cbm_lod_level", "cbm_collider_strategy"):
            if key in obj:
                del obj[key]


def _uv_layer_snapshots(mesh: bpy.types.Mesh) -> list[dict[str, Any]]:
    """Copy UV names, flags, and per-loop coordinates before collection reordering."""

    snapshots: list[dict[str, Any]] = []
    for layer in mesh.uv_layers:
        snapshots.append(
            {
                "name": str(layer.name),
                "active_render": bool(layer.active_render),
                "coordinates": [(float(loop.uv.x), float(loop.uv.y)) for loop in layer.data],
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


@contextmanager
def _portable_tangent_probe(
    obj: bpy.types.Object,
) -> Iterator[bpy.types.Object]:
    """Yield the source mesh or a disposable triangulated copy for tangent checks."""

    mesh = obj.data
    if not any(len(polygon.vertices) > 4 for polygon in mesh.polygons):
        yield obj
        return

    temporary_mesh = mesh.copy()
    temporary = bpy.data.objects.new(f"{obj.name}__CBM_EXPORT_TANGENT_PROBE", temporary_mesh)
    temporary.matrix_world = obj.matrix_world.copy()
    editable = bmesh.new()
    try:
        editable.from_mesh(temporary_mesh)
        non_triangles = [face for face in editable.faces if len(face.verts) != 3]
        if non_triangles:
            bmesh.ops.triangulate(
                editable,
                faces=non_triangles,
                quad_method="FIXED",
                ngon_method="EAR_CLIP",
            )
            editable.to_mesh(temporary_mesh)
            temporary_mesh.update()
        yield temporary
    finally:
        editable.free()
        bpy.data.objects.remove(temporary, do_unlink=True)
        if temporary_mesh.users == 0:
            bpy.data.meshes.remove(temporary_mesh)


def _verify_portable_tangent_basis(
    obj: bpy.types.Object,
    uv_set: str,
) -> None:
    """Fail closed when a render mesh cannot produce finite tangents from portable UV0."""

    with _portable_tangent_probe(obj) as probe:
        mesh = probe.data
        calculator = getattr(mesh, "calc_tangents", None)
        if calculator is None:
            raise RuntimeError("Blender runtime exposes no portable tangent calculator")
        try:
            calculator(uvmap=uv_set)
            invalid = 0
            for loop in mesh.loops:
                values = tuple(float(value) for value in loop.tangent)
                sign = float(loop.bitangent_sign)
                if not all(
                    value == value and abs(value) != float("inf") for value in (*values, sign)
                ):
                    invalid += 1
            if invalid:
                raise RuntimeError(
                    f"{obj.name!r} has {invalid} invalid tangent loops on {uv_set!r}"
                )
        finally:
            freer = getattr(mesh, "free_tangents", None)
            if freer is not None:
                freer()


def normalize_portable_uv_bindings(
    selected: list[bpy.types.Object],
    *,
    material_conversion_plan_sha256: str | None,
    export_format: str,
    static_payload: bool = False,
) -> dict[str, Any]:
    """Promote the portable atlas to UV0 for FBX or glTF material interchange."""

    if not material_conversion_plan_sha256:
        return {"status": "not_applicable", "reason": "no_material_conversion"}
    if export_format not in {"fbx", "glb", "gltf"}:
        return {
            "status": "not_applicable",
            "reason": "format_has_no_portable_uv0_contract",
        }
    atlas_uv_set = str(
        bpy.context.scene.get("cbm_portable_material_atlas_uv", PORTABLE_ATLAS_UV_DEFAULT)
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
                raise RuntimeError(f"{obj.name!r} is missing portable atlas UV {atlas_uv_set!r}")
            ordered_names = [atlas_uv_set]
            if LIGHTMAP_UV_DEFAULT in by_name:
                ordered_names.append(LIGHTMAP_UV_DEFAULT)
            ordered_names.extend(name for name in by_name if name not in set(ordered_names))
            _replace_uv_layers(mesh, [by_name[name] for name in ordered_names])
            actual_names = [str(layer.name) for layer in mesh.uv_layers]
            if actual_names != ordered_names or not mesh.uv_layers[0].active_render:
                raise RuntimeError(
                    f"Portable UV ordering verification failed for {obj.name!r}: {actual_names}"
                )
            mesh_records[mesh_key] = {
                "uv_layers": actual_names,
                "lightmap_uv_channel_index": (
                    actual_names.index(LIGHTMAP_UV_DEFAULT)
                    if LIGHTMAP_UV_DEFAULT in actual_names
                    else None
                ),
            }
        _verify_portable_tangent_basis(obj, atlas_uv_set)
        object_records.append(
            {
                "object_name": str(obj.name),
                "semantic_id": str(obj.get("cbm_id", "")),
                "asset_role": str(obj.get("cbm_asset_role", "")),
                "material_ids": list(object_inventory(obj, include_topology=False)["material_ids"]),
                "required_uv_set": atlas_uv_set,
                "required_uv_channel_index": 0,
                "tangent_uv_set": atlas_uv_set,
                **mesh_records[mesh_key],
            }
        )
    if not object_records:
        raise RuntimeError("Portable material conversion has no render or LOD meshes")
    lightmap_indices = {
        item["lightmap_uv_channel_index"]
        for item in object_records
        if item["lightmap_uv_channel_index"] is not None
    }
    if lightmap_indices - {1}:
        raise RuntimeError("Portable lightmap UV must occupy channel index 1")
    return {
        "status": "verified",
        "export_format": export_format,
        "verification_basis": "blender_uv0_and_tangent_preflight",
        "scope": ("all_render_objects" if static_payload else "all_render_and_lod_objects"),
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


def normalize_fbx_uv_bindings(
    selected: list[bpy.types.Object],
    *,
    material_conversion_plan_sha256: str | None,
) -> dict[str, Any]:
    """Preserve the historical FBX helper while delegating to portable UV0 policy."""

    return normalize_portable_uv_bindings(
        selected,
        material_conversion_plan_sha256=material_conversion_plan_sha256,
        export_format="fbx",
    )


def _gltf_document(path: Path, format_name: str) -> dict[str, Any]:
    """Read the JSON document from one exported GLB or separate glTF file."""

    if format_name == "gltf":
        payload = json.loads(path.read_text(encoding="utf-8"))
    elif format_name == "glb":
        data = path.read_bytes()
        if len(data) < 20:
            raise RuntimeError("Exported GLB is too short to contain a JSON chunk")
        magic, version, total_length = struct.unpack_from("<4sII", data, 0)
        chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
        if magic != b"glTF" or version != 2 or total_length != len(data):
            raise RuntimeError("Exported GLB header is invalid")
        if chunk_type != 0x4E4F534A or 20 + chunk_length > len(data):
            raise RuntimeError("Exported GLB has no valid leading JSON chunk")
        text = data[20 : 20 + chunk_length].decode("utf-8").rstrip(" \t\r\n\x00")
        payload = json.loads(text)
    else:
        raise ValueError(f"Unsupported glTF document format: {format_name!r}")
    if not isinstance(payload, dict):
        raise RuntimeError("Exported glTF JSON root is not an object")
    return payload


def _material_texture_bindings(material: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect and validate every standard or extension TextureInfo object."""

    bindings: list[dict[str, Any]] = []

    def visit(value: Any, path: tuple[str, ...]) -> None:
        """Walk one material JSON subtree and collect texture-info dictionaries."""

        if path and path[-1].casefold().endswith("texture"):
            if not isinstance(value, dict):
                raise RuntimeError("Exported glTF TextureInfo is not an object")
            texture_index = value.get("index")
            if type(texture_index) is not int:
                raise RuntimeError("Exported glTF TextureInfo has no exact integer texture index")
            extensions = value.get("extensions", {})
            if not isinstance(extensions, dict):
                raise RuntimeError("Exported glTF TextureInfo extensions are malformed")
            transform = extensions.get("KHR_texture_transform", {})
            if not isinstance(transform, dict):
                raise RuntimeError("Exported glTF texture-transform extension is malformed")
            tex_coord = (
                transform.get("texCoord") if "texCoord" in transform else value.get("texCoord", 0)
            )
            if type(tex_coord) is not int:
                raise RuntimeError("Exported glTF TextureInfo has no exact integer texCoord")
            bindings.append(
                {
                    "slot": ".".join(path),
                    "texture_index": texture_index,
                    "tex_coord": tex_coord,
                }
            )
        if isinstance(value, dict):
            if not (path and path[-1].casefold().endswith("texture")):
                for key, child in value.items():
                    visit(child, (*path, str(key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, str(index)))

    visit(material, ())
    return bindings


def verify_gltf_texture_coordinate_binding(
    output: Path,
    format_name: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Verify glTF texture slots and mesh primitives use portable UV0 and tangents."""

    if contract.get("status") != "verified":
        return contract
    if contract.get("export_format") != format_name:
        raise RuntimeError("Portable UV contract format differs from the glTF export")
    document = _gltf_document(output, format_name)
    textures = document.get("textures", [])
    materials = document.get("materials", [])
    meshes = document.get("meshes", [])
    if (
        not isinstance(textures, list)
        or not isinstance(materials, list)
        or not isinstance(meshes, list)
    ):
        raise RuntimeError("Exported glTF materials, textures, or meshes are malformed")
    expected_material_ids = {
        str(material_id)
        for item in contract.get("objects", [])
        if isinstance(item, dict)
        for material_id in item.get("material_ids", [])
        if isinstance(material_id, str) and material_id
    }
    if not expected_material_ids:
        raise RuntimeError("Portable UV contract declares no converted material IDs")
    material_indices: dict[str, int] = {}
    for material_index, material in enumerate(materials):
        if not isinstance(material, dict):
            raise RuntimeError("Exported glTF contains a malformed material")
        extras = material.get("extras", {})
        material_id = extras.get("cbm_id") if isinstance(extras, dict) else None
        if material_id not in expected_material_ids:
            continue
        if material_id in material_indices:
            raise RuntimeError("Exported glTF duplicates one portable material ID")
        material_indices[str(material_id)] = material_index
    if set(material_indices) != expected_material_ids:
        raise RuntimeError("Exported glTF is missing one or more portable material IDs")
    expected_material_indices = set(material_indices.values())
    records: list[dict[str, Any]] = []
    textured_materials: set[int] = set()
    normal_mapped_materials: set[int] = set()
    for material_index, material in enumerate(materials):
        if not isinstance(material, dict):
            raise RuntimeError("Exported glTF contains a malformed material")
        if material_index not in expected_material_indices:
            continue
        material_id = str(material.get("extras", {}).get("cbm_id"))
        bindings = _material_texture_bindings(material)
        if not bindings:
            raise RuntimeError("Exported portable glTF material has no texture bindings")
        for binding in bindings:
            texture_index = binding["texture_index"]
            tex_coord = binding["tex_coord"]
            if not 0 <= texture_index < len(textures):
                raise RuntimeError("Exported glTF material references an invalid texture index")
            if tex_coord != 0:
                raise RuntimeError(
                    "Exported glTF portable material does not bind every texture to TEXCOORD_0"
                )
            records.append(
                {
                    "material_id": material_id,
                    "material_index": material_index,
                    **binding,
                }
            )
            textured_materials.add(material_index)
            if str(binding["slot"]).casefold().endswith("normaltexture"):
                normal_mapped_materials.add(material_index)
    if not records:
        raise RuntimeError("Exported glTF portable material exposes no texture bindings")
    primitive_records: list[dict[str, Any]] = []
    referenced_materials: set[int] = set()
    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives", []), list):
            raise RuntimeError("Exported glTF contains a malformed mesh")
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            if not isinstance(primitive, dict):
                raise RuntimeError("Exported glTF contains a malformed primitive")
            material_index = primitive.get("material")
            if material_index not in textured_materials:
                continue
            referenced_materials.add(material_index)
            attributes = primitive.get("attributes", {})
            if not isinstance(attributes, dict) or "TEXCOORD_0" not in attributes:
                raise RuntimeError(
                    "Exported glTF textured primitive exposes no TEXCOORD_0 attribute"
                )
            tangent_required = material_index in normal_mapped_materials
            tangent_present = "TANGENT" in attributes
            if tangent_required and not tangent_present:
                raise RuntimeError(
                    "Exported glTF normal-mapped primitive exposes no TANGENT attribute"
                )
            primitive_records.append(
                {
                    "mesh_index": mesh_index,
                    "primitive_index": primitive_index,
                    "material_index": material_index,
                    "material_id": next(
                        material_id
                        for material_id, index in material_indices.items()
                        if index == material_index
                    ),
                    "texcoord_0_present": True,
                    "tangent_required": tangent_required,
                    "tangent_present": tangent_present,
                }
            )
    if not primitive_records:
        raise RuntimeError("Exported glTF has no textured mesh primitive")
    if referenced_materials != expected_material_indices:
        raise RuntimeError("Exported glTF leaves one or more portable materials unreferenced")
    verified = copy.deepcopy(contract)
    verified.update(
        {
            "status": "verified",
            "verification_basis": "gltf_material_textureinfo_texcoord0",
            "file_metadata_verified": True,
            "verified_texture_binding_count": len(records),
            "verified_primitive_count": len(primitive_records),
            "texture_bindings": records,
            "primitives": primitive_records,
        }
    )
    return verified


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
    *,
    allowed_object_properties: frozenset[str] = PORTABLE_OBJECT_PROPERTIES,
) -> dict[str, int]:
    """Strip path-bearing authoring metadata while retaining portable identity fields."""

    counts = {"scene": 0, "collection": 0, "object": 0, "mesh": 0, "material": 0}
    counts["scene"] += _retain_custom_properties(bpy.context.scene, frozenset())
    for collection in bpy.data.collections:
        counts["collection"] += _retain_custom_properties(collection, frozenset())

    materials: set[bpy.types.Material] = set()
    meshes: set[bpy.types.Mesh] = set()
    for obj in selected:
        counts["object"] += _retain_custom_properties(obj, allowed_object_properties)
        if obj.type == "MESH" and obj.data is not None:
            meshes.add(obj.data)
        for slot in obj.material_slots:
            if slot.material is not None:
                materials.add(slot.material)
    for mesh in meshes:
        counts["mesh"] += _retain_custom_properties(mesh, frozenset())
    for material in materials:
        counts["material"] += _retain_custom_properties(material, PORTABLE_MATERIAL_PROPERTIES)
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
                source = Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()
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
        data = bytearray(data.replace(original, _same_length_relative_path(original)))
        rewritten += occurrences
    leftovers = [value for value in encoded_paths if value in data]
    if leftovers:
        raise RuntimeError("FBX path sanitizer left an expected absolute path")
    if rewritten:
        path.write_bytes(data)
    return rewritten


def export_object_inventory(
    obj: bpy.types.Object,
    format_name: str,
    *,
    static_payload: bool = False,
) -> dict[str, Any]:
    """Describe only the topology and identity semantics serialized by one format."""

    record = object_inventory(obj)
    if static_payload:
        record.pop("lod_level", None)
        record.pop("collider_strategy", None)
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


def _cyclic_triangle_key(vertices: Any) -> tuple[int, int, int]:
    """Canonicalize one oriented triangle across cyclic loop-order rotations."""

    values = tuple(int(value) for value in vertices)
    if len(values) != 3 or len(set(values)) != 3:
        raise RuntimeError("glTF serialization encountered an invalid triangle")
    rotations = tuple(values[index:] + values[:index] for index in range(3))
    return min(rotations)


def _mesh_corner_normals(mesh: bpy.types.Mesh) -> list[Any]:
    """Copy one finite loop-aligned evaluated normal vector from the source mesh."""

    mesh.update()
    normals = getattr(mesh, "corner_normals", None)
    if normals is not None and len(normals) == len(mesh.loops):
        values = [item.vector.copy() for item in normals]
    else:
        values = [None] * len(mesh.loops)
        for polygon in mesh.polygons:
            for loop_index in polygon.loop_indices:
                values[loop_index] = polygon.normal.copy()
    if any(value is None for value in values):
        raise RuntimeError("glTF serialization could not resolve every corner normal")
    if any(not all(math.isfinite(float(value[index])) for index in range(3)) for value in values):
        raise RuntimeError("glTF serialization encountered a non-finite corner normal")
    return values


def _capture_polygon_corner_normals(
    mesh: bpy.types.Mesh,
) -> dict[int, tuple[int, dict[int, tuple[float, float, float]]]]:
    """Capture each source polygon's evaluated normal at every original vertex."""

    corner_normals = _mesh_corner_normals(mesh)
    records: dict[int, tuple[int, dict[int, tuple[float, float, float]]]] = {}
    for polygon in mesh.polygons:
        by_vertex: dict[int, tuple[float, float, float]] = {}
        for vertex_index, loop_index in zip(
            polygon.vertices,
            polygon.loop_indices,
            strict=True,
        ):
            vertex_key = int(vertex_index)
            if vertex_key in by_vertex:
                raise RuntimeError("glTF serialization source polygon repeats a corner vertex")
            normal = corner_normals[loop_index]
            by_vertex[vertex_key] = tuple(float(normal[index]) for index in range(3))
        if len(by_vertex) < 3:
            raise RuntimeError("glTF serialization encountered an invalid source polygon")
        records[int(polygon.index)] = (int(polygon.material_index), by_vertex)
    return records


def _capture_bmesh_triangle_corner_normals(
    editable: Any,
    source_face_layer: Any,
    source_records: dict[int, tuple[int, dict[int, tuple[float, float, float]]]],
) -> dict[tuple[tuple[int, int, int], int], list[dict[int, tuple[float, float, float]]]]:
    """Project source polygon normals onto the exact BMesh triangles being written."""

    editable.verts.index_update()
    editable.faces.index_update()
    records: dict[
        tuple[tuple[int, int, int], int],
        list[dict[int, tuple[float, float, float]]],
    ] = {}
    for face in editable.faces:
        if len(face.verts) != 3:
            raise RuntimeError("glTF serialization BMesh remains non-triangular")
        source_polygon_index = int(face[source_face_layer])
        source_record = source_records.get(source_polygon_index)
        if source_record is None:
            raise RuntimeError("glTF serialization triangulation lost source polygon identity")
        source_material_index, source_normals = source_record
        if int(face.material_index) != source_material_index:
            raise RuntimeError("glTF serialization triangulation changed source material identity")
        vertices = tuple(int(vertex.index) for vertex in face.verts)
        try:
            by_vertex = {vertex: source_normals[vertex] for vertex in vertices}
        except KeyError as exc:
            raise RuntimeError(
                "glTF serialization triangulation introduced a source polygon corner"
            ) from exc
        key = (_cyclic_triangle_key(vertices), source_material_index)
        records.setdefault(key, []).append(by_vertex)
    return records


def _restore_triangulated_corner_normals(
    mesh: bpy.types.Mesh,
    records: dict[
        tuple[tuple[int, int, int], int],
        list[dict[int, tuple[float, float, float]]],
    ],
) -> None:
    """Restore captured evaluated normals after deterministic physical triangulation."""

    mesh.calc_loop_triangles()
    remaining = {key: list(values) for key, values in records.items()}
    restored: list[tuple[float, float, float] | None] = [None] * len(mesh.loops)
    for triangle in mesh.loop_triangles:
        polygon = mesh.polygons[triangle.polygon_index]
        key = (_cyclic_triangle_key(triangle.vertices), int(polygon.material_index))
        candidates = remaining.get(key)
        if not candidates:
            raise RuntimeError(
                "glTF serialization triangulation changed oriented triangle identity"
            )
        by_vertex = candidates.pop(0)
        for vertex_index, loop_index in zip(
            triangle.vertices,
            triangle.loops,
            strict=True,
        ):
            try:
                restored[loop_index] = by_vertex[int(vertex_index)]
            except KeyError as exc:
                raise RuntimeError(
                    "glTF serialization triangulation changed triangle corners"
                ) from exc
    if any(values for values in remaining.values()) or any(normal is None for normal in restored):
        raise RuntimeError(
            "glTF serialization triangulation did not preserve every source corner normal"
        )
    mesh.normals_split_custom_set(restored)
    mesh.update()


def _serialization_collinear_slivers(
    editable: Any,
    obj: bpy.types.Object,
    *,
    maximum_area_m2: float,
    maximum_ratio: float,
) -> list[Any]:
    """Find negligible triangulation faces before custom corner normals are restored."""

    result: list[Any] = []
    for face in editable.faces:
        if len(face.verts) != 3:
            continue
        coordinates = [obj.matrix_world @ vertex.co for vertex in face.verts]
        edges = [coordinates[(index + 1) % 3] - coordinates[index] for index in range(3)]
        maximum_edge_squared = max(edge.length_squared for edge in edges)
        if maximum_edge_squared <= 0.0:
            result.append(face)
            continue
        doubled_area = edges[0].cross(coordinates[2] - coordinates[0]).length
        if (
            doubled_area * 0.5 <= maximum_area_m2
            and doubled_area / maximum_edge_squared <= maximum_ratio
        ):
            result.append(face)
    return result


def normalize_gltf_serialization_topology(
    objects: list[bpy.types.Object],
    format_name: str,
    *,
    collinear_sliver_maximum_area_m2: float | None = None,
    collinear_sliver_maximum_ratio: float | None = None,
) -> dict[str, Any]:
    """Triangulate only in-memory glTF meshes before evidence and serialization."""

    if format_name not in {"glb", "gltf"}:
        return {
            "status": "not_applicable",
            "format": format_name,
            "reason": "format_does_not_require_gltf_triangle_serialization",
        }
    if (collinear_sliver_maximum_area_m2 is None) != (collinear_sliver_maximum_ratio is None):
        raise ValueError("glTF collinear-sliver thresholds must be supplied together")
    if collinear_sliver_maximum_area_m2 is not None and (
        collinear_sliver_maximum_area_m2 <= 0.0
        or collinear_sliver_maximum_ratio is None
        or collinear_sliver_maximum_ratio <= 0.0
    ):
        raise ValueError("glTF collinear-sliver thresholds must be positive")
    import bmesh

    mesh_objects = sorted(
        (obj for obj in objects if obj.type == "MESH"), key=lambda item: item.name
    )
    seen_meshes: set[int] = set()
    records: list[dict[str, Any]] = []
    for obj in mesh_objects:
        mesh = obj.data
        mesh_key = int(mesh.as_pointer())
        if mesh_key in seen_meshes:
            continue
        seen_meshes.add(mesh_key)
        mesh.calc_loop_triangles()
        polygons_before = len(mesh.polygons)
        triangles_before = len(mesh.loop_triangles)
        non_tri_faces_before = sum(1 for polygon in mesh.polygons if len(polygon.vertices) != 3)
        removed_collinear_face_count = 0
        expected_triangles_after = triangles_before
        rewrite_requested = bool(
            non_tri_faces_before or collinear_sliver_maximum_area_m2 is not None
        )
        if rewrite_requested:
            source_normal_records = _capture_polygon_corner_normals(mesh)
            editable = bmesh.new()
            try:
                editable.from_mesh(mesh)
                editable.faces.ensure_lookup_table()
                editable.faces.index_update()
                source_face_layer = editable.faces.layers.int.new("cbm_source_polygon_index")
                for face in editable.faces:
                    face[source_face_layer] = int(face.index)
                faces = [face for face in editable.faces if len(face.verts) != 3]
                bmesh.ops.triangulate(
                    editable,
                    faces=faces,
                    quad_method="FIXED",
                    ngon_method="EAR_CLIP",
                )
                if collinear_sliver_maximum_area_m2 is not None:
                    collinear_faces = _serialization_collinear_slivers(
                        editable,
                        obj,
                        maximum_area_m2=collinear_sliver_maximum_area_m2,
                        maximum_ratio=float(collinear_sliver_maximum_ratio),
                    )
                    removed_collinear_face_count = len(collinear_faces)
                    if collinear_faces:
                        bmesh.ops.delete(
                            editable,
                            geom=collinear_faces,
                            context="FACES_ONLY",
                        )
                expected_triangles_after = len(editable.faces)
                normal_records = _capture_bmesh_triangle_corner_normals(
                    editable,
                    source_face_layer,
                    source_normal_records,
                )
                editable.faces.layers.int.remove(source_face_layer)
                editable.to_mesh(mesh)
            finally:
                editable.free()
            mesh.update()
            _restore_triangulated_corner_normals(mesh, normal_records)
        mesh.calc_loop_triangles()
        polygons_after = len(mesh.polygons)
        triangles_after = len(mesh.loop_triangles)
        remaining_non_tri_faces = sum(1 for polygon in mesh.polygons if len(polygon.vertices) != 3)
        if remaining_non_tri_faces:
            raise RuntimeError(f"glTF serialization mesh remains non-triangular: {obj.name}")
        if triangles_after != expected_triangles_after or polygons_after != triangles_after:
            raise RuntimeError(
                f"glTF serialization triangulation changed triangle identity: {obj.name}"
            )
        records.append(
            {
                "object_name": obj.name,
                "mesh_name": mesh.name,
                "polygons_before": polygons_before,
                "polygons_after": polygons_after,
                "triangles_before": triangles_before,
                "triangles_after": triangles_after,
                "non_tri_faces_before": non_tri_faces_before,
                "removed_collinear_face_count": removed_collinear_face_count,
            }
        )
    return {
        "status": "applied",
        "format": format_name,
        "policy": "in_memory_pre_evidence_triangulation",
        "object_count": len(mesh_objects),
        "unique_mesh_count": len(records),
        "triangulated_mesh_count": sum(1 for record in records if record["non_tri_faces_before"]),
        "removed_collinear_face_count": sum(
            int(record["removed_collinear_face_count"]) for record in records
        ),
        "non_tri_face_count_before": sum(int(record["non_tri_faces_before"]) for record in records),
        "triangle_count_before": sum(int(record["triangles_before"]) for record in records),
        "triangle_count_after": sum(int(record["triangles_after"]) for record in records),
        "records": records,
    }


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
    with portable_gltf_temp_environment(path.parent):
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
        warnings.append("OBJ cannot preserve CBM custom semantic properties during round-trip.")
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
    root = Path(args.package_root).expanduser().resolve() if args.package_root else output.parent
    root.mkdir(parents=True, exist_ok=True)
    portable_path(output, root)
    portable_path(manifest_path, root)
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Portable export already exists: {output}")
    if manifest_path.exists() and not args.overwrite:
        raise FileExistsError(f"Package manifest already exists: {manifest_path}")
    if args.static_payload and not args.asset_name:
        raise ValueError("Static payload export requires --asset-name")
    if args.asset_name and not args.static_payload:
        raise ValueError("--asset-name is valid only with --static-payload")
    if args.static_payload and args.include_colliders:
        raise ValueError("Static payload export cannot include physics proxies")

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
    if args.static_payload:
        normalize_static_payload_objects(selected, str(args.asset_name))
    uv_binding_contract = (
        normalize_portable_uv_bindings(
            selected,
            material_conversion_plan_sha256=derivative.get("material_conversion_plan_sha256"),
            export_format=args.format,
            static_payload=bool(args.static_payload),
        )
        if args.format in {"fbx", "glb", "gltf"}
        else {
            "status": "not_applicable",
            "reason": "format_has_no_portable_uv0_contract",
        }
    )
    serialization_topology = normalize_gltf_serialization_topology(selected, args.format)
    optics = validate_optical_volume_objects(selected, require_stored_geometry=True)
    optical_active = bool(optics)
    if optics and args.format not in {"glb", "gltf"}:
        raise ValueError("Opt-in optical-volume packages currently require glTF/GLB")
    allowed_object_properties = (
        STATIC_PAYLOAD_OBJECT_PROPERTIES if args.static_payload else PORTABLE_OBJECT_PROPERTIES
    )
    sanitization = sanitize_export_custom_properties(
        selected,
        allowed_object_properties=allowed_object_properties,
    )
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
    optical_serialization = verify_exported_optical_volume(
        output, args.format, optics, strict_opt_in=optical_active
    )
    fbx_path_rewrite_count = (
        sanitize_fbx_absolute_paths(
            output,
            [input_blend, output, *staged_dependencies],
        )
        if args.format == "fbx"
        else 0
    )
    if args.format in {"glb", "gltf"}:
        uv_binding_contract = verify_gltf_texture_coordinate_binding(
            output,
            args.format,
            uv_binding_contract,
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
        "content_mode": ("static_payload" if args.static_payload else "full_evidence"),
        "source": {
            **source_provenance,
            **derivative,
            "optimized_blend_sha256": sha256_file(Path(bpy.data.filepath).resolve()),
        },
        "runtime": {"blender_version": bpy.app.version_string},
        "custom_property_sanitization": {
            "policy": (
                "static_identity_whitelist"
                if args.static_payload
                else "portable_identity_whitelist"
            ),
            "allowed_object_properties": sorted(allowed_object_properties),
            "allowed_material_properties": sorted(PORTABLE_MATERIAL_PROPERTIES),
            "removed_property_counts": sanitization,
        },
        "path_sanitization": {
            "fbx_same_length_relative_rewrite_count": fbx_path_rewrite_count,
        },
        "coordinate_contract": coordinate_contract(args.format),
        "uv_binding_contract": uv_binding_contract,
        "serialization_topology": serialization_topology,
        "objects": [
            export_object_inventory(
                obj,
                args.format,
                static_payload=bool(args.static_payload),
            )
            for obj in selected
        ],
        "semantic_ids": sorted({str(obj.get("cbm_id")) for obj in selected if obj.get("cbm_id")}),
        "material_ids": sorted(
            {
                material_id
                for obj in selected
                for material_id in object_inventory(obj, include_topology=False)["material_ids"]
            }
        ),
        "files": files,
        "warnings": format_warnings(args.format),
    }
    if not args.static_payload:
        manifest["include_colliders"] = bool(args.include_colliders)
    if optics:
        manifest["optical_volume_boundary_evidence"] = optics
        manifest["optical_volume_serialization"] = optical_serialization
    write_json(manifest_path, manifest)
    print(
        "CBM_ASSET_PACKAGE_OK "
        f"format={args.format} objects={len(selected)} output={output} "
        f"manifest={manifest_path}"
    )


if __name__ == "__main__":
    main()
