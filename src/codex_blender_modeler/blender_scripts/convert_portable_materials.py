from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import bmesh
import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from compat import configure_render_compat, set_material_transparency  # noqa: E402
from portable_asset_common import operator_kwargs, scene_source_provenance  # noqa: E402
from portable_material_conversion_runtime import (  # noqa: E402
    atlas_tile_bounds,
    blender_relative_path,
    fingerprint_json,
    grid_shape,
    safe_component,
    sha256_file,
    stable_identifier,
    stable_object_key,
    write_json_atomic,
)

SCHEMA_VERSION = "0.7.0"
ATLAS_UV_SET = "CBMPortableAtlas"
CHANNELS = ("base_color", "roughness", "metallic", "normal", "emission")
COLOR_SPACES = {
    "base_color": "sRGB",
    "roughness": "Non-Color",
    "metallic": "Non-Color",
    "normal": "Non-Color",
    "emission": "sRGB",
}
CONVERTIBLE_ROLES = {"render", "lod"}
SUPPORTED_MAPPING_MODES = {"uv", "object", "triplanar"}


def parse_args() -> argparse.Namespace:
    """Parse the hash-bound V0.7.1 derived material conversion request."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--conversion-plan", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output-blend", required=True)
    parser.add_argument("--output-evidence", required=True)
    parser.add_argument("--output-texture-root", required=True)
    parser.add_argument("--resolution", required=True, type=int)
    parser.add_argument("--margin-px", required=True, type=int)
    parser.add_argument("--render-device", default="AUTO")
    parser.add_argument("--source-blend-sha256", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    """Read one required conversion contract and reject a non-object root."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root must be a JSON object: {path}")
    return payload


def _artifact_sha256(container: dict[str, Any], names: tuple[str, ...]) -> str | None:
    """Resolve a hashed artifact from compatible conversion-plan field names."""

    for name in names:
        value = container.get(name)
        if isinstance(value, dict) and isinstance(value.get("sha256"), str):
            return str(value["sha256"]).lower()
        if isinstance(value, str) and name.endswith("_sha256"):
            return value.lower()
    source = container.get("source")
    if isinstance(source, dict):
        for name in names:
            value = source.get(name)
            if isinstance(value, dict) and isinstance(value.get("sha256"), str):
                return str(value["sha256"]).lower()
            if isinstance(value, str) and name.endswith("_sha256"):
                return value.lower()
    return None


def _expected_build_fingerprint(plan: dict[str, Any]) -> str | None:
    """Read the canonical build fingerprint without confusing it with a run hash."""

    for name in ("source_build_fingerprint", "build_fingerprint"):
        value = plan.get(name)
        if isinstance(value, str) and value:
            return value.lower()
    source = plan.get("source")
    if isinstance(source, dict):
        value = source.get("build_fingerprint")
        if isinstance(value, str) and value:
            return value.lower()
    return None


def _validate_output_boundary(
    source_blend: Path,
    output_blend: Path,
    output_evidence: Path,
    texture_root: Path,
) -> None:
    """Refuse canonical overwrite and immutable run-output replacement before conversion."""

    if output_blend == source_blend:
        raise RuntimeError("Portable material conversion cannot overwrite the optimized source")
    if output_blend.exists():
        raise FileExistsError(f"Portable output blend already exists: {output_blend}")
    if output_evidence.exists():
        raise FileExistsError(f"Portable conversion evidence already exists: {output_evidence}")
    if texture_root.exists() and any(texture_root.iterdir()):
        raise FileExistsError(f"Portable texture root is not empty: {texture_root}")


def _verify_contracts(
    plan_path: Path,
    profile_path: Path,
    source_blend: Path,
    expected_plan_sha256: str,
    expected_source_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str, str]:
    """Bind the loaded optimized scene to exact plan, profile, source, and build hashes."""

    plan = _read_json_object(plan_path, "PortableMaterialConversionPlan")
    profile = _read_json_object(profile_path, "AssetProfile")
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Portable material conversion plan must use schema_version 0.7.0")
    if profile.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("AssetProfile must use schema_version 0.7.0")
    if plan.get("status") != "approved":
        raise RuntimeError("Portable material conversion plan must be approved")
    if plan.get("job_id") != profile.get("job_id"):
        raise ValueError("Conversion plan job_id does not match AssetProfile")
    if plan.get("profile_id") != profile.get("profile_id"):
        raise ValueError("Conversion plan profile_id does not match AssetProfile")
    if plan.get("canonical_unchanged") is not True:
        raise RuntimeError("Conversion plan must preserve canonical authoring inputs")
    profile_artifact = plan.get("profile_artifact")
    if not isinstance(profile_artifact, dict) or profile_artifact.get("kind") != "asset_profile":
        raise ValueError("Conversion plan profile_artifact must use kind=asset_profile")
    optimized_artifact = plan.get("optimized_blend")
    if not isinstance(optimized_artifact, dict) or optimized_artifact.get("kind") != "blend":
        raise ValueError("Conversion plan optimized_blend must use kind=blend")

    plan_sha256 = sha256_file(plan_path)
    if plan_sha256 != expected_plan_sha256.lower():
        raise RuntimeError("Portable material conversion plan hash changed before execution")
    profile_sha256 = sha256_file(profile_path)
    expected_profile = _artifact_sha256(
        plan,
        ("profile_artifact",),
    )
    if expected_profile and profile_sha256 != expected_profile:
        raise RuntimeError("AssetProfile hash does not match conversion plan")

    source_sha256 = sha256_file(source_blend)
    if source_sha256 != expected_source_sha256.lower():
        raise RuntimeError("Loaded optimized blend hash changed before conversion")
    expected_source = _artifact_sha256(
        plan,
        ("optimized_blend",),
    )
    if expected_source and source_sha256 != expected_source:
        raise RuntimeError("Optimized blend hash does not match conversion plan")

    scene = bpy.context.scene
    provenance = scene_source_provenance(scene)
    if str(scene.get("cbm_job_id") or "") != str(plan.get("job_id") or ""):
        raise RuntimeError("Loaded optimized scene job_id does not match conversion plan")
    expected_build = _expected_build_fingerprint(plan)
    actual_build = str(
        scene.get("cbm_portable_source_build_fingerprint")
        or provenance.get("build_fingerprint")
        or ""
    ).lower()
    if expected_build and actual_build != expected_build:
        raise RuntimeError("Loaded optimized scene build fingerprint is stale")
    embedded_optimization_plan = str(scene.get("cbm_portable_plan_sha256") or "").lower()
    if not embedded_optimization_plan:
        raise RuntimeError("Loaded optimized scene lacks embedded execution-plan provenance")
    # The conversion plan deliberately binds immutable execution_plan.json here;
    # the later completed optimization_plan.json is bound by host/package layers.
    expected_optimization_plan = _artifact_sha256(plan, ("optimization_plan",))
    if embedded_optimization_plan != expected_optimization_plan:
        raise RuntimeError("Loaded optimized scene does not match its execution-plan hash")
    return (
        plan,
        profile,
        provenance,
        plan_sha256,
        profile_sha256,
        source_sha256,
    )


def _validate_atlas_policy(
    plan: dict[str, Any],
    resolution: int,
    margin_px: int,
) -> dict[str, Any]:
    """Require the exact V0.7.1 global shared-atlas policy approved by the host."""

    policy = plan.get("atlas_policy")
    if not isinstance(policy, dict):
        raise ValueError("Conversion plan requires atlas_policy")
    expected = {
        "layout": "global_shared",
        "atlas_scope": "all_render_lod",
        "conversion_phase": "after_optimization_with_canonical_source_frame",
        "tile_strategy": "deterministic_grid",
        "uv_set": ATLAS_UV_SET,
        "preserve_existing_uv_sets": True,
        "required_channels": list(CHANNELS),
    }
    mismatches = {
        name: (policy.get(name), value)
        for name, value in expected.items()
        if policy.get(name) != value
    }
    if mismatches:
        raise ValueError(f"Conversion atlas policy is incompatible: {mismatches}")
    if int(policy.get("resolution", 0)) != resolution:
        raise ValueError("--resolution must match conversion plan atlas_policy")
    if int(policy.get("margin_px", -1)) != margin_px:
        raise ValueError("--margin-px must match conversion plan atlas_policy")
    if resolution & (resolution - 1):
        raise ValueError("Portable atlas resolution must be a power of two")
    if float(policy.get("maximum_overlap_fraction", -1.0)) < 0.0:
        raise ValueError("atlas_policy.maximum_overlap_fraction must be non-negative")
    return policy


def _verify_bound_job_artifact(
    plan: dict[str, Any],
    field: str,
    expected_kind: str,
    job_root: Path,
) -> Path:
    """Verify one job-relative plan dependency before any Blender mutation."""

    artifact = plan.get(field)
    if not isinstance(artifact, dict) or artifact.get("kind") != expected_kind:
        raise ValueError(f"Conversion plan {field} must use kind={expected_kind}")
    path = (job_root / str(artifact.get("path", ""))).resolve()
    try:
        path.relative_to(job_root)
    except ValueError as exc:
        raise RuntimeError(f"Conversion plan {field} escapes the job: {path}") from exc
    if not path.is_file() or sha256_file(path) != str(artifact.get("sha256")):
        raise RuntimeError(f"Conversion plan {field} artifact changed: {path}")
    return path


def _material_id(material: bpy.types.Material) -> str:
    """Return the stable material identity stored by the canonical V0.5 build."""

    return str(material.get("cbm_id") or material.name)


def _conversion_objects() -> list[bpy.types.Object]:
    """Select stable derived render and LOD meshes while excluding source and colliders."""

    candidates = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and str(obj.get("cbm_asset_role") or "") in CONVERTIBLE_ROLES
    ]
    records = [
        {
            "object": obj,
            "name": obj.name,
            "semantic_id": obj.get("cbm_id"),
            "source_object": obj.get("cbm_source_object"),
            "lod_level": obj.get("cbm_lod_level", 0),
        }
        for obj in candidates
    ]
    records.sort(key=stable_object_key)
    objects = [record["object"] for record in records]
    if not objects:
        raise RuntimeError("Optimized scene has no derived render or LOD meshes to convert")
    for obj in objects:
        if not obj.get("cbm_id") or not obj.get("cbm_source_object"):
            raise RuntimeError(f"Derived object lacks semantic/source identity: {obj.name}")
        materials = [slot.material for slot in obj.material_slots if slot.material is not None]
        if len(materials) != 1 or len(obj.material_slots) != 1:
            raise RuntimeError(
                f"Portable atlas baking requires exactly one material slot: {obj.name}"
            )
        material = materials[0]
        if not material.get("cbm_id"):
            raise RuntimeError(f"Derived material lacks stable cbm_id: {material.name}")
        if not material.get("cbm_material_source_fingerprint"):
            raise RuntimeError(
                f"Material {_material_id(material)} lacks V0.5 source fingerprint"
            )
        mode = str(material.get("cbm_mapping_mode") or "")
        if mode == "generated":
            raise RuntimeError(
                f"Material {_material_id(material)} uses generated mapping; "
                "V0.7.1 conversion requires an explicit authored fallback"
            )
        if mode not in SUPPORTED_MAPPING_MODES:
            raise RuntimeError(
                f"Material {_material_id(material)} has unsupported mapping mode {mode!r}"
            )
        source = bpy.data.objects.get(str(obj.get("cbm_source_object")))
        if source is None or str(source.get("cbm_asset_role") or "authoring") != "authoring":
            raise RuntimeError(f"Canonical source object is unavailable for {obj.name}")
    return objects


def _validate_conversion_scope(
    plan: dict[str, Any],
    objects: list[bpy.types.Object],
    job_root: Path,
) -> dict[str, dict[str, Any]]:
    """Match planned material bindings to exact derived users and V0.5 provenance."""

    actual_materials: dict[str, bpy.types.Material] = {}
    actual_targets: dict[str, set[str]] = defaultdict(set)
    for obj in objects:
        material = obj.material_slots[0].material
        if material is None:
            raise RuntimeError(f"Missing source material: {obj.name}")
        material_id = _material_id(material)
        actual_materials.setdefault(material_id, material)
        actual_targets[material_id].add(str(obj.get("cbm_id")))
    actual_ids = sorted(actual_materials)
    required_ids = plan.get("required_material_ids")
    if required_ids != actual_ids:
        raise RuntimeError(
            "Conversion required_material_ids must exactly match derived material IDs: "
            f"{required_ids!r} != {actual_ids!r}"
        )
    bindings = plan.get("materials")
    if not isinstance(bindings, list):
        raise ValueError("Conversion plan materials must be an array")
    planned_ids = [
        str(item.get("material_id")) for item in bindings if isinstance(item, dict)
    ]
    if planned_ids != actual_ids or len(bindings) != len(actual_ids):
        raise RuntimeError("Conversion plan material bindings must match required IDs in order")
    by_id: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError("Each conversion plan material binding must be an object")
        material_id = str(binding["material_id"])
        material = actual_materials[material_id]
        if binding.get("target_ids") != sorted(actual_targets[material_id]):
            raise RuntimeError(f"Conversion target_ids are stale for {material_id}")
        if binding.get("bake_required") is not True:
            raise RuntimeError(f"Conversion binding must require baking: {material_id}")
        if str(binding.get("mapping_mode")) != str(material.get("cbm_mapping_mode")):
            raise RuntimeError(f"Conversion mapping mode is stale for {material_id}")
        if str(binding.get("source_material_fingerprint")) != str(
            material.get("cbm_material_source_fingerprint")
        ):
            raise RuntimeError(f"Conversion material fingerprint is stale for {material_id}")
        recipe = binding.get("source_shader_recipe")
        if not isinstance(recipe, dict) or recipe.get("kind") != "shader_recipe":
            raise ValueError(f"Conversion binding lacks shader recipe artifact: {material_id}")
        recipe_path = (job_root / str(recipe.get("path", ""))).resolve()
        try:
            recipe_path.relative_to(job_root)
        except ValueError as exc:
            raise RuntimeError(f"Shader recipe escapes the job: {recipe_path}") from exc
        if not recipe_path.is_file() or sha256_file(recipe_path) != str(recipe.get("sha256")):
            raise RuntimeError(f"Shader recipe artifact changed for {material_id}")
        embedded_recipe_path = Path(
            str(material.get("cbm_shader_recipe") or "")
        ).expanduser().resolve()
        if embedded_recipe_path != recipe_path:
            raise RuntimeError(f"Loaded shader recipe path is stale for {material_id}")
        if str(material.get("cbm_shader_recipe_sha256") or "") != str(
            recipe.get("sha256")
        ):
            raise RuntimeError(f"Loaded shader recipe provenance is stale for {material_id}")
        by_id[material_id] = binding
    return by_id


def _principled(material: bpy.types.Material) -> Any | None:
    """Find the active Principled source node without relying on its Blender name."""

    if material.node_tree is None:
        return None
    return next(
        (node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"),
        None,
    )


def _socket(node: Any | None, names: tuple[str, ...]) -> Any | None:
    """Feature-probe one semantic shader socket across Blender API renames."""

    if node is None:
        return None
    for name in names:
        value = node.inputs.get(name)
        if value is not None:
            return value
    return None


def _json_value(value: Any) -> Any:
    """Normalize Blender scalar and array defaults into JSON-safe primitives."""

    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    try:
        return [float(item) for item in value]
    except TypeError:
        return str(value)


def _surface_semantics(material: bpy.types.Material) -> dict[str, Any]:
    """Capture portable scalar semantics that are not represented by the five maps."""

    shader = _principled(material)
    fields = {
        "base_color": ("Base Color",),
        "metallic": ("Metallic",),
        "roughness": ("Roughness",),
        "ior": ("IOR",),
        "transmission_weight": ("Transmission Weight", "Transmission"),
        "alpha": ("Alpha",),
        "emission_color": ("Emission Color", "Emission"),
        "emission_strength": ("Emission Strength",),
        "coat_weight": ("Coat Weight", "Clearcoat"),
        "subsurface_weight": ("Subsurface Weight", "Subsurface"),
        "anisotropic": ("Anisotropic IOR Level", "Anisotropic"),
    }
    semantics: dict[str, Any] = {}
    for field, names in fields.items():
        value = _socket(shader, names)
        if value is not None:
            semantics[field] = _json_value(value.default_value)
    if "base_color" not in semantics:
        semantics["base_color"] = [float(item) for item in material.diffuse_color]
    semantics.setdefault("metallic", float(getattr(material, "metallic", 0.0)))
    semantics.setdefault("roughness", float(getattr(material, "roughness", 0.5)))
    return semantics


def _pin_original_uv_links(material: bpy.types.Material, uv_set: str) -> int:
    """Replace implicit Texture Coordinate UV links with one explicit source UV node."""

    if material.node_tree is None:
        return 0
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    pending = []
    for node in nodes:
        if node.type != "TEX_COORD":
            continue
        output = node.outputs.get("UV")
        if output is not None:
            pending.extend((link, link.to_socket) for link in list(output.links))
    if not pending:
        return 0
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.name = "CBM_Portable_SourceUV"
    uv_node.label = f"CBM Source UV: {uv_set}"
    uv_node.uv_map = uv_set
    output = uv_node.outputs.get("UV")
    if output is None:
        nodes.remove(uv_node)
        raise RuntimeError("Running Blender exposes no UV output on ShaderNodeUVMap")
    for link, target in pending:
        links.remove(link)
        links.new(output, target)
    return len(pending)


def _bind_object_coordinates(
    material: bpy.types.Material,
    source_object: bpy.types.Object,
) -> int:
    """Anchor object/triplanar source coordinates to the canonical authoring object."""

    if material.node_tree is None:
        return 0
    count = 0
    for node in material.node_tree.nodes:
        if node.type == "TEX_COORD":
            node.object = source_object
            count += 1
    return count


def _clone_source_material(
    obj: bpy.types.Object,
) -> tuple[bpy.types.Material, bpy.types.Material, str, dict[str, Any]]:
    """Give one derived object a private graph whose coordinate source can be frozen."""

    source_material = obj.material_slots[0].material
    if source_material is None:
        raise RuntimeError(f"Missing source material: {obj.name}")
    material_id = _material_id(source_material)
    clone = source_material.copy()
    clone.name = f"CBM_BAKE_{safe_component(material_id)}_{safe_component(obj.name)}"
    mapping_mode = str(source_material.get("cbm_mapping_mode"))
    coordinate_bindings = 0
    original_uv_set = None
    if mapping_mode == "uv":
        original_uv_set = str(source_material.get("cbm_uv_set") or "UVMap")
        if obj.data.uv_layers.get(original_uv_set) is None:
            bpy.data.materials.remove(clone)
            raise RuntimeError(f"{obj.name} is missing source UV set {original_uv_set!r}")
        coordinate_bindings = _pin_original_uv_links(clone, original_uv_set)
    else:
        source_object = bpy.data.objects.get(str(obj.get("cbm_source_object")))
        if source_object is None:
            bpy.data.materials.remove(clone)
            raise RuntimeError(f"Missing canonical coordinate source for {obj.name}")
        coordinate_bindings = _bind_object_coordinates(clone, source_object)
    obj.data.materials[0] = clone
    return (
        source_material,
        clone,
        mapping_mode,
        {
            "source_uv_set": original_uv_set,
            "coordinate_bindings": coordinate_bindings,
        },
    )


def _activate_one(obj: bpy.types.Object) -> None:
    """Make one derived mesh the sole active object for Smart UV Project."""

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _smart_project_kwargs() -> dict[str, Any]:
    """Feature-probe Smart UV Project arguments supported by the running Blender."""

    identifiers = {
        item.identifier for item in bpy.ops.uv.smart_project.get_rna_type().properties
    }
    candidates = {
        "angle_limit": math.radians(66.0),
        "island_margin": 0.01,
        "area_weight": 0.0,
        "correct_aspect": True,
        "scale_to_bounds": True,
    }
    return {name: value for name, value in candidates.items() if name in identifiers}


def _lightmap_pack_kwargs() -> dict[str, Any]:
    """Feature-probe a per-face UV fallback that avoids zero-area Smart UV islands."""

    identifiers = {
        item.identifier for item in bpy.ops.uv.lightmap_pack.get_rna_type().properties
    }
    candidates = {
        "PREF_CONTEXT": "ALL_FACES",
        "PREF_PACK_IN_ONE": True,
        "PREF_NEW_UVLAYER": False,
        "PREF_BOX_DIV": 12,
        "PREF_MARGIN_DIV": 0.1,
    }
    return {name: value for name, value in candidates.items() if name in identifiers}


def _degenerate_uv_faces(
    mesh: bpy.types.Mesh,
    layer: bpy.types.MeshUVLoopLayer,
    epsilon: float = 1e-12,
) -> list[int]:
    """Return polygon indices whose active UV fan has non-finite or zero area."""

    uv_values = getattr(layer, "uv", None)
    if uv_values is None:
        raise RuntimeError("Blender exposes no Float2 UV attribute storage")
    coordinates = [0.0] * (len(uv_values) * 2)
    uv_values.foreach_get("vector", coordinates)
    degenerate: list[int] = []
    for polygon in mesh.polygons:
        values = [
            (
                float(coordinates[index * 2]),
                float(coordinates[index * 2 + 1]),
            )
            for index in polygon.loop_indices
        ]
        if len(values) < 3 or not all(
            math.isfinite(component) for value in values for component in value
        ):
            degenerate.append(int(polygon.index))
            continue
        origin_u, origin_v = values[0]
        area = 0.0
        for index in range(1, len(values) - 1):
            first_u = values[index][0] - origin_u
            first_v = values[index][1] - origin_v
            second_u = values[index + 1][0] - origin_u
            second_v = values[index + 1][1] - origin_v
            area += abs(first_u * second_v - first_v * second_u) * 0.5
        if not math.isfinite(area) or area <= epsilon:
            degenerate.append(int(polygon.index))
    return degenerate


def _lightmap_fallback(obj: bpy.types.Object) -> None:
    """Replace a degenerate Smart UV result with Blender's per-face lightmap packing."""

    layer = obj.data.uv_layers.get(ATLAS_UV_SET)
    if layer is None:
        raise RuntimeError(f"Portable atlas layer is missing before fallback: {obj.name}")
    obj.data.uv_layers.active = layer
    layer.active_render = True
    _activate_one(obj)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        if not bpy.ops.uv.lightmap_pack.poll():
            raise RuntimeError("Lightmap Pack is unavailable in the active context")
        result = bpy.ops.uv.lightmap_pack(**_lightmap_pack_kwargs())
        if "FINISHED" not in result:
            raise RuntimeError(f"Lightmap Pack returned {sorted(result)}")
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")


def _create_atlas_uv(
    obj: bpy.types.Object,
    bounds: tuple[float, float, float, float],
) -> dict[str, Any]:
    """Smart-unwrap one derived object and move it into its exclusive global tile."""

    mesh = obj.data
    if not mesh.polygons:
        raise RuntimeError(f"Portable atlas requires faces: {obj.name}")
    existing = mesh.uv_layers.get(ATLAS_UV_SET)
    if existing is not None:
        mesh.uv_layers.remove(existing)
    layer = mesh.uv_layers.new(name=ATLAS_UV_SET, do_init=False)
    mesh.uv_layers.active = layer
    layer.active_render = True
    _activate_one(obj)
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        if not bpy.ops.uv.smart_project.poll():
            raise RuntimeError("Smart UV Project is unavailable in the active context")
        result = bpy.ops.uv.smart_project(**_smart_project_kwargs())
        if "FINISHED" not in result:
            raise RuntimeError(f"Smart UV Project returned {sorted(result)}")
    finally:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    # Blender 5 can invalidate MeshUVLoopLayer RNA handles across the EDIT -> OBJECT
    # transition, so reacquire the mesh and layer before touching UV storage.
    mesh = obj.data
    layer = mesh.uv_layers.get(ATLAS_UV_SET)
    if layer is None:
        raise RuntimeError(f"Smart UV Project removed the atlas layer: {obj.name}")
    initial_degenerate_faces = _degenerate_uv_faces(mesh, layer)
    unwrap_method = "smart_project"
    if initial_degenerate_faces:
        _lightmap_fallback(obj)
        mesh = obj.data
        layer = mesh.uv_layers.get(ATLAS_UV_SET)
        if layer is None:
            raise RuntimeError(f"Lightmap Pack removed the atlas layer: {obj.name}")
        remaining = _degenerate_uv_faces(mesh, layer)
        if remaining:
            raise RuntimeError(
                f"Portable atlas retains {len(remaining)} degenerate UV faces after "
                f"Lightmap Pack: {obj.name}"
            )
        unwrap_method = "lightmap_pack_fallback"
    minimum_u, minimum_v, maximum_u, maximum_v = bounds
    width = maximum_u - minimum_u
    height = maximum_v - minimum_v
    uv_values = getattr(layer, "uv", None)
    if uv_values is None:
        raise RuntimeError(
            f"Blender does not expose Float2 UV attribute storage: {obj.name}"
        )
    coordinates = [0.0] * (len(uv_values) * 2)
    uv_values.foreach_get("vector", coordinates)
    for index in range(0, len(coordinates), 2):
        coordinates[index] = minimum_u + min(
            1.0, max(0.0, float(coordinates[index]))
        ) * width
        coordinates[index + 1] = minimum_v + min(
            1.0, max(0.0, float(coordinates[index + 1]))
        ) * height
    uv_values.foreach_set("vector", coordinates)
    mesh.uv_layers.active = layer
    layer.active_render = True
    mesh.update()
    obj["cbm_portable_uv_set"] = ATLAS_UV_SET
    obj["cbm_portable_uv_policy"] = f"global_grid_{unwrap_method}"
    return {
        "uv_set": ATLAS_UV_SET,
        "bounds": [round(value, 9) for value in bounds],
        "loop_count": len(uv_values),
        "unwrap_method": unwrap_method,
        "repaired_degenerate_face_count": len(initial_degenerate_faces),
        "remaining_degenerate_face_count": 0,
    }


def _mesh_world_bounds(obj: bpy.types.Object) -> tuple[float, float, float, float, float, float]:
    """Measure deterministic world-space bounds for one run-owned converted mesh."""

    values = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    if not values:
        raise RuntimeError(f"Portable tangent repair requires vertices: {obj.name}")
    return (
        min(value.x for value in values),
        min(value.y for value in values),
        min(value.z for value in values),
        max(value.x for value in values),
        max(value.y for value in values),
        max(value.z for value in values),
    )


def _invalid_tangent_faces(obj: bpy.types.Object, uv_name: str) -> dict[str, Any]:
    """Return invalid tangent loops and faces on the exact portable normal-map UV."""

    mesh = obj.data
    calculator = getattr(mesh, "calc_tangents", None)
    if calculator is None:
        raise RuntimeError("Blender runtime does not support tangent calculation")
    layer = mesh.uv_layers.get(uv_name)
    if layer is None:
        raise RuntimeError(f"Portable tangent UV is missing: {obj.name} ({uv_name})")
    loop_to_face = {
        int(loop_index): int(polygon.index)
        for polygon in mesh.polygons
        for loop_index in polygon.loop_indices
    }
    invalid_loops: list[int] = []
    try:
        calculator(uvmap=layer.name)
        for loop in mesh.loops:
            tangent = tuple(float(value) for value in loop.tangent)
            sign = float(loop.bitangent_sign)
            length_squared = sum(value * value for value in tangent)
            if (
                not all(math.isfinite(value) for value in tangent)
                or not math.isfinite(sign)
                or length_squared <= 1e-18
            ):
                invalid_loops.append(int(loop.index))
    finally:
        freer = getattr(mesh, "free_tangents", None)
        if freer is not None:
            freer()
    return {
        "invalid_loop_indices": invalid_loops,
        "invalid_face_indices": sorted(
            {loop_to_face[index] for index in invalid_loops}
        ),
    }


def _micro_sliver_faces(obj: bpy.types.Object, distance_m: float) -> list[int]:
    """Find polygons with an adjacent world-space edge below the repair threshold."""

    result: list[int] = []
    for polygon in obj.data.polygons:
        coordinates = [
            obj.matrix_world @ obj.data.vertices[index].co
            for index in polygon.vertices
        ]
        if any(
            (coordinates[(index + 1) % len(coordinates)] - value).length <= distance_m
            for index, value in enumerate(coordinates)
        ):
            result.append(int(polygon.index))
    return result


def _simulated_export_tangent_faces(
    obj: bpy.types.Object,
    uv_name: str,
) -> dict[str, Any]:
    """Check tangents on a temporary fully triangulated copy like an interchange export."""

    temporary_mesh = obj.data.copy()
    temporary = bpy.data.objects.new(f"{obj.name}__CBM_TANGENT_PROBE", temporary_mesh)
    temporary.matrix_world = obj.matrix_world.copy()
    editable = bmesh.new()
    try:
        editable.from_mesh(temporary_mesh)
        non_triangles = [face for face in editable.faces if len(face.verts) != 3]
        if non_triangles:
            bmesh.ops.triangulate(
                editable,
                faces=non_triangles,
                quad_method="BEAUTY",
                ngon_method="BEAUTY",
            )
            editable.to_mesh(temporary_mesh)
            temporary_mesh.update()
        result = _invalid_tangent_faces(temporary, uv_name)
        micro_faces = set(_micro_sliver_faces(temporary, 1e-6))
        result["repairable_invalid_face_indices"] = sorted(
            set(result["invalid_face_indices"]) & micro_faces
        )
        return result
    finally:
        editable.free()
        bpy.data.objects.remove(temporary, do_unlink=True)
        if temporary_mesh.users == 0:
            bpy.data.meshes.remove(temporary_mesh)


def _repair_tangent_micro_slivers(obj: bpy.types.Object, uv_name: str) -> dict[str, Any]:
    """Conditionally dissolve sub-micrometer slivers in the converted mesh only."""

    before_bounds = _mesh_world_bounds(obj)
    before_vertices = len(obj.data.vertices)
    before_polygons = len(obj.data.polygons)
    before_triangles = sum(max(0, len(face.vertices) - 2) for face in obj.data.polygons)
    before = _invalid_tangent_faces(obj, uv_name)
    invalid_loops = before["invalid_loop_indices"]
    invalid_faces = before["invalid_face_indices"]
    export_before = _simulated_export_tangent_faces(obj, uv_name)
    export_invalid_loops = export_before["invalid_loop_indices"]
    export_invalid_faces = export_before["invalid_face_indices"]
    repairable_export_faces = export_before["repairable_invalid_face_indices"]
    micro_slivers = _micro_sliver_faces(obj, 1e-6)
    if not repairable_export_faces:
        return {
            "repair_method": "none",
            "repair_distance_m": 0.0,
            "micro_sliver_face_count_before": len(micro_slivers),
            "remaining_micro_sliver_face_count": len(micro_slivers),
            "native_invalid_loop_count": len(invalid_loops),
            "native_invalid_face_count": len(invalid_faces),
            "invalid_loop_count_before": len(export_invalid_loops),
            "invalid_face_count_before": len(export_invalid_faces),
            "invalid_loop_count_after": len(export_invalid_loops),
            "invalid_face_count_after": len(export_invalid_faces),
            "vertices_before": before_vertices,
            "vertices_after": before_vertices,
            "polygons_before": before_polygons,
            "polygons_after": before_polygons,
            "triangles_before": before_triangles,
            "triangles_after": before_triangles,
            "bounds_max_abs_delta_m": 0.0,
        }
    editable = bmesh.new()
    try:
        editable.from_mesh(obj.data)
        bmesh.ops.dissolve_degenerate(
            editable,
            dist=1e-6,
            edges=list(editable.edges),
        )
        editable.to_mesh(obj.data)
    finally:
        editable.free()
    obj.data.validate(verbose=False, clean_customdata=False)
    obj.data.update()
    layer = obj.data.uv_layers.get(uv_name)
    if layer is None:
        raise RuntimeError(f"Tangent repair removed portable UV: {obj.name}")
    remaining_uv = _degenerate_uv_faces(obj.data, layer)
    native_after = _invalid_tangent_faces(obj, uv_name)
    export_after = _simulated_export_tangent_faces(obj, uv_name)
    remaining_micro_slivers = _micro_sliver_faces(obj, 1e-6)
    after_bounds = _mesh_world_bounds(obj)
    bounds_delta = max(
        abs(current - original)
        for original, current in zip(before_bounds, after_bounds, strict=True)
    )
    if (
        remaining_uv
        or remaining_micro_slivers
        or export_after["invalid_loop_indices"]
        or bounds_delta > 1e-6
    ):
        raise RuntimeError(
            f"Portable tangent repair failed for {obj.name}: "
            f"invalid_loops={len(export_after['invalid_loop_indices'])}, "
            f"micro_slivers={len(remaining_micro_slivers)}, "
            f"degenerate_uv_faces={len(remaining_uv)}, bounds_delta={bounds_delta}"
        )
    after_triangles = sum(
        max(0, len(face.vertices) - 2) for face in obj.data.polygons
    )
    return {
        "repair_method": "dissolve_degenerate",
        "repair_distance_m": 1e-6,
        "micro_sliver_face_count_before": len(micro_slivers),
        "remaining_micro_sliver_face_count": 0,
        "native_invalid_loop_count": len(invalid_loops),
        "native_invalid_face_count": len(invalid_faces),
        "native_invalid_loop_count_after": len(native_after["invalid_loop_indices"]),
        "native_invalid_face_count_after": len(native_after["invalid_face_indices"]),
        "invalid_loop_count_before": len(export_invalid_loops),
        "invalid_face_count_before": len(export_invalid_faces),
        "invalid_loop_count_after": 0,
        "invalid_face_count_after": 0,
        "vertices_before": before_vertices,
        "vertices_after": len(obj.data.vertices),
        "polygons_before": before_polygons,
        "polygons_after": len(obj.data.polygons),
        "triangles_before": before_triangles,
        "triangles_after": after_triangles,
        "bounds_max_abs_delta_m": round(bounds_delta, 12),
    }


def _activate_many(objects: list[bpy.types.Object]) -> None:
    """Select one stable material-user group for a shared Cycles atlas bake."""

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def _material_output(material: bpy.types.Material) -> Any:
    """Find the active material surface output used by the cloned master graph."""

    if material.node_tree is None:
        raise RuntimeError(f"Material has no node tree: {material.name}")
    outputs = [node for node in material.node_tree.nodes if node.type == "OUTPUT_MATERIAL"]
    active = next((node for node in outputs if getattr(node, "is_active_output", False)), None)
    if active is None and outputs:
        active = outputs[0]
    if active is None:
        raise RuntimeError(f"Material has no output node: {material.name}")
    return active


def _constant_channel(material: bpy.types.Material, channel: str) -> Any:
    """Provide a bounded fallback when a legacy material lacks a semantic socket."""

    if channel == "base_color":
        return tuple(float(item) for item in material.diffuse_color)
    if channel == "roughness":
        return float(getattr(material, "roughness", 0.5))
    if channel == "metallic":
        return float(getattr(material, "metallic", 0.0))
    return (0.0, 0.0, 0.0, 1.0)


def _channel_socket(material: bpy.types.Material, channel: str) -> Any | None:
    """Resolve a portable bake channel from Principled or legacy emission nodes."""

    shader = _principled(material)
    if shader is not None:
        names = {
            "base_color": ("Base Color",),
            "roughness": ("Roughness",),
            "metallic": ("Metallic",),
            "emission": ("Emission Color", "Emission"),
        }[channel]
        return _socket(shader, names)
    if channel == "emission" and material.node_tree is not None:
        emission = next(
            (node for node in material.node_tree.nodes if node.type == "EMISSION"),
            None,
        )
        return emission.inputs.get("Color") if emission is not None else None
    return None


def _emission_strength_socket(material: bpy.types.Material) -> Any | None:
    """Resolve original emission strength so the baked emission map includes intensity."""

    shader = _principled(material)
    strength = _socket(shader, ("Emission Strength",))
    if strength is not None:
        return strength
    if material.node_tree is not None:
        emission = next(
            (node for node in material.node_tree.nodes if node.type == "EMISSION"),
            None,
        )
        if emission is not None:
            return emission.inputs.get("Strength")
    return None


def _set_color_or_link(
    material: bpy.types.Material,
    source: Any | None,
    target: Any,
    fallback: Any,
) -> None:
    """Copy one scalar/color source into a color-compatible bake socket."""

    links = material.node_tree.links
    if source is not None and source.is_linked:
        links.new(source.links[0].from_socket, target)
        return
    value = source.default_value if source is not None else fallback
    if isinstance(value, (int, float)):
        target.default_value = (float(value), float(value), float(value), 1.0)
    else:
        values = tuple(float(item) for item in value)
        target.default_value = values if len(values) == 4 else (*values[:3], 1.0)


def _route_channel_to_emission(material: bpy.types.Material, channel: str) -> dict[str, Any]:
    """Temporarily expose one channel as emission, multiplying emission by its strength."""

    if material.node_tree is None:
        raise RuntimeError(f"Material has no node tree: {material.name}")
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    output = _material_output(material)
    surface = output.inputs.get("Surface")
    if surface is None:
        raise RuntimeError(f"Material output has no Surface socket: {material.name}")
    original = surface.links[0].from_socket if surface.is_linked else None
    for link in list(surface.links):
        links.remove(link)
    bake_emission = nodes.new("ShaderNodeEmission")
    bake_emission.name = f"CBM_PortableBake_{channel}"
    created = [bake_emission]
    source = _channel_socket(material, channel)
    if channel != "emission":
        _set_color_or_link(
            material,
            source,
            bake_emission.inputs["Color"],
            _constant_channel(material, channel),
        )
    else:
        multiply = nodes.new("ShaderNodeMixRGB")
        multiply.name = "CBM_PortableBake_EmissionStrength"
        multiply.blend_type = "MULTIPLY"
        multiply.inputs["Fac"].default_value = 1.0
        created.append(multiply)
        _set_color_or_link(material, source, multiply.inputs[1], (0.0, 0.0, 0.0, 1.0))
        strength = _emission_strength_socket(material)
        if strength is not None and strength.is_linked:
            combine = nodes.new("ShaderNodeCombineXYZ")
            combine.name = "CBM_PortableBake_EmissionStrengthRGB"
            created.append(combine)
            for socket_name in ("X", "Y", "Z"):
                links.new(strength.links[0].from_socket, combine.inputs[socket_name])
            links.new(combine.outputs[0], multiply.inputs[2])
        else:
            value = float(strength.default_value) if strength is not None else 0.0
            multiply.inputs[2].default_value = (value, value, value, 1.0)
        links.new(multiply.outputs[0], bake_emission.inputs["Color"])
    bake_emission.inputs["Strength"].default_value = 1.0
    links.new(bake_emission.outputs[0], surface)
    return {"surface": surface, "original": original, "created": created}


def _restore_channel_route(material: bpy.types.Material, state: dict[str, Any]) -> None:
    """Restore the cloned master graph after one channel has been baked."""

    links = material.node_tree.links
    surface = state["surface"]
    for link in list(surface.links):
        links.remove(link)
    if state["original"] is not None:
        links.new(state["original"], surface)
    for node in reversed(state["created"]):
        material.node_tree.nodes.remove(node)


def _new_bake_image(material_id: str, channel: str, resolution: int) -> bpy.types.Image:
    """Create one shared per-material atlas image with the declared channel color space."""

    image = bpy.data.images.new(
        name=f"CBM_PORTABLE_{safe_component(material_id)}_{channel}",
        width=resolution,
        height=resolution,
        alpha=False,
        float_buffer=False,
        is_data=COLOR_SPACES[channel] == "Non-Color",
    )
    try:
        image.colorspace_settings.name = COLOR_SPACES[channel]
    except (TypeError, ValueError, RuntimeError) as exc:
        bpy.data.images.remove(image)
        raise RuntimeError(
            f"Blender cannot assign {COLOR_SPACES[channel]} to {channel}: {exc}"
        ) from exc
    return image


def _attach_bake_target(material: bpy.types.Material, image: bpy.types.Image, channel: str) -> Any:
    """Attach and activate the shared image target on one private cloned material."""

    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.name = f"CBM_PortableBakeTarget_{channel}"
    node.image = image
    node.select = True
    material.node_tree.nodes.active = node
    return node


def _run_bake_operator(channel: str, margin_px: int) -> None:
    """Feature-probe Cycles bake arguments and require one successful global bake."""

    scene_bake = bpy.context.scene.render.bake
    if hasattr(scene_bake, "margin"):
        scene_bake.margin = margin_px
    if hasattr(scene_bake, "use_clear"):
        scene_bake.use_clear = True
    identifiers = {item.identifier for item in bpy.ops.object.bake.get_rna_type().properties}
    kwargs: dict[str, Any] = {"type": "NORMAL" if channel == "normal" else "EMIT"}
    if "margin" in identifiers:
        kwargs["margin"] = margin_px
    if "use_clear" in identifiers:
        kwargs["use_clear"] = True
    if channel == "normal" and "normal_space" in identifiers:
        kwargs["normal_space"] = "TANGENT"
    result = bpy.ops.object.bake(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"Cycles bake returned {sorted(result)} for {channel}")


def _save_bake_image(image: bpy.types.Image, output: Path) -> str:
    """Save one shared atlas channel and return its exact lowercase digest."""

    output.parent.mkdir(parents=True, exist_ok=True)
    image.filepath_raw = str(output)
    image.file_format = "PNG"
    image.save()
    if not output.is_file():
        raise RuntimeError(f"Blender did not write portable texture: {output}")
    return sha256_file(output)


def _bake_global_channels(
    objects: list[bpy.types.Object],
    clone_materials: list[bpy.types.Material],
    material_ids: list[str],
    output_root: Path,
    output_blend: Path,
    resolution: int,
    margin_px: int,
) -> tuple[dict[str, bpy.types.Image], list[dict[str, Any]]]:
    """Bake five global atlas channels across every planned material and derived user."""

    images: dict[str, bpy.types.Image] = {}
    outputs: list[dict[str, Any]] = []
    for channel in CHANNELS:
        image = _new_bake_image("global", channel, resolution)
        target_nodes = [
            _attach_bake_target(material, image, channel) for material in clone_materials
        ]
        routes: list[tuple[bpy.types.Material, dict[str, Any]]] = []
        try:
            _activate_many(objects)
            if channel != "normal":
                routes = [
                    (material, _route_channel_to_emission(material, channel))
                    for material in clone_materials
                ]
                for material, target in zip(clone_materials, target_nodes, strict=True):
                    material.node_tree.nodes.active = target
            _run_bake_operator(channel, margin_px)
            output = output_root / f"{channel}.png"
            digest = _save_bake_image(image, output)
            image.filepath_raw = blender_relative_path(output, output_blend.parent)
            outputs.append(
                {
                    "id": f"portable.global.{channel}",
                    "channel": channel,
                    "path": str(output.resolve()),
                    "sha256": digest,
                    "color_space": COLOR_SPACES[channel],
                    "resolution": [resolution, resolution],
                    "material_ids": material_ids,
                    "file_format": "png",
                }
            )
            images[channel] = image
        finally:
            for material, state in reversed(routes):
                _restore_channel_route(material, state)
            for material, target in zip(clone_materials, target_nodes, strict=True):
                if target.id_data is material.node_tree:
                    material.node_tree.nodes.remove(target)
        if channel not in images:
            bpy.data.images.remove(image)
    return images, outputs


def _set_socket_default(node: Any, names: tuple[str, ...], value: Any) -> bool:
    """Assign one portable surface default through Blender 4/5-compatible socket names."""

    socket = _socket(node, names)
    if socket is None:
        return False
    socket.default_value = value
    return True


def _portable_material(
    source: bpy.types.Material,
    material_id: str,
    semantics: dict[str, Any],
    images: dict[str, bpy.types.Image],
) -> bpy.types.Material:
    """Build one shared image-based Principled graph for engine-neutral export."""

    material = bpy.data.materials.new(f"{safe_component(material_id)}__PORTABLE")
    material.use_nodes = True
    for key in sorted(source.keys()):
        if str(key).startswith("cbm_"):
            material[key] = source[key]
    material["cbm_id"] = material_id
    material["cbm_mapping_mode"] = "uv"
    material["cbm_uv_set"] = ATLAS_UV_SET
    material["cbm_material_source_type"] = "portable_atlas_bake"
    material["cbm_portable_material_conversion"] = SCHEMA_VERSION
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(shader.outputs[0], output.inputs["Surface"])
    uv = nodes.new("ShaderNodeUVMap")
    uv.name = "CBM_PortableAtlasUV"
    uv.uv_map = ATLAS_UV_SET
    uv_output = uv.outputs.get("UV")
    if uv_output is None:
        raise RuntimeError("Running Blender exposes no UV output on ShaderNodeUVMap")

    image_nodes: dict[str, Any] = {}
    for channel in CHANNELS:
        node = nodes.new("ShaderNodeTexImage")
        node.name = f"CBM_Portable_{channel}"
        node.label = f"CBM Portable {channel}"
        node.image = images[channel]
        node.interpolation = "Linear"
        node.extension = "EXTEND"
        links.new(uv_output, node.inputs["Vector"])
        image_nodes[channel] = node
    links.new(image_nodes["base_color"].outputs["Color"], shader.inputs["Base Color"])
    links.new(image_nodes["roughness"].outputs["Color"], shader.inputs["Roughness"])
    links.new(image_nodes["metallic"].outputs["Color"], shader.inputs["Metallic"])
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.uv_map = ATLAS_UV_SET
    links.new(image_nodes["normal"].outputs["Color"], normal_map.inputs["Color"])
    links.new(normal_map.outputs["Normal"], shader.inputs["Normal"])
    emission_socket = _socket(shader, ("Emission Color", "Emission"))
    if emission_socket is not None:
        links.new(image_nodes["emission"].outputs["Color"], emission_socket)
    _set_socket_default(shader, ("Emission Strength",), 1.0)

    for field, names in {
        "ior": ("IOR",),
        "transmission_weight": ("Transmission Weight", "Transmission"),
        "alpha": ("Alpha",),
        "coat_weight": ("Coat Weight", "Clearcoat"),
        "subsurface_weight": ("Subsurface Weight", "Subsurface"),
        "anisotropic": ("Anisotropic IOR Level", "Anisotropic"),
    }.items():
        if field in semantics:
            _set_socket_default(shader, names, semantics[field])
    alpha = float(semantics.get("alpha", 1.0))
    if alpha < 1.0:
        set_material_transparency(material)
    material.diffuse_color = tuple(
        float(item) for item in semantics.get("base_color", [0.8, 0.8, 0.8, alpha])
    )
    return material


def _loss_notes(mapping_mode: str, semantics: dict[str, Any]) -> list[str]:
    """Record bounded conversion limitations instead of claiming shader graph parity."""

    notes = [
        "Procedural and master-shader detail is resolution-bounded by the derived atlas bake.",
        "Height/displacement is represented only through the baked tangent-space normal channel.",
        "The five-channel contract does not include an opacity texture; alpha is scalar-only.",
    ]
    if mapping_mode in {"object", "triplanar"}:
        notes.append(
            "Object-space appearance was sampled against cbm_source_object before "
            "portable UV rewiring."
        )
    if float(semantics.get("transmission_weight", 0.0)) > 0.0:
        notes.append(
            "Transmission is retained as a scalar Principled semantic and is not encoded in a map."
        )
    if float(semantics.get("coat_weight", 0.0)) > 0.0:
        notes.append("Coat weight is retained as a scalar and may be format-limited downstream.")
    if float(semantics.get("emission_strength", 0.0)) > 1.0:
        notes.append(
            "Emission color was multiplied by strength before an 8-bit PNG bake; "
            "values above display white may be clamped."
        )
    return notes


def _portable_surface_factors(semantics: dict[str, Any]) -> dict[str, Any]:
    """Separate already-baked channels from retained alpha and transmission scalars."""

    return {
        "base_color_factor": [1.0, 1.0, 1.0, 1.0],
        "roughness_factor": 1.0,
        "metallic_factor": 1.0,
        "emission_factor": [1.0, 1.0, 1.0],
        "alpha_factor": float(semantics.get("alpha", 1.0)),
        "transmission_factor": float(semantics.get("transmission_weight", 0.0)),
    }


def _save_portable_blend(output_blend: Path) -> str:
    """Atomically save a separate converted scene without replacing the optimized source."""

    output_blend.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_blend.with_name(output_blend.stem + ".partial.blend")
    if temporary.exists():
        raise FileExistsError(f"Partial portable blend already exists: {temporary}")
    operator = bpy.ops.wm.save_as_mainfile
    operator(
        **operator_kwargs(
            operator,
            {
                "filepath": str(temporary),
                "relative_remap": False,
            },
        )
    )
    if not temporary.is_file():
        raise RuntimeError(f"Blender did not save portable scene: {temporary}")
    temporary.replace(output_blend)
    return sha256_file(output_blend)


def main() -> None:
    """Bake portable atlases and publish one immutable converted scene plus raw evidence."""

    args = parse_args()
    job_root = Path(args.job_root).expanduser().resolve()
    plan_path = Path(args.conversion_plan).expanduser().resolve()
    profile_path = Path(args.profile).expanduser().resolve()
    output_blend = Path(args.output_blend).expanduser().resolve()
    output_evidence = Path(args.output_evidence).expanduser().resolve()
    texture_root = Path(args.output_texture_root).expanduser().resolve()
    source_blend = Path(bpy.data.filepath).expanduser().resolve()
    if not source_blend.is_file():
        raise FileNotFoundError("A saved optimized source .blend must be loaded")
    if not job_root.is_dir():
        raise FileNotFoundError(f"Job root does not exist: {job_root}")
    if args.resolution < 64 or args.resolution > 8192:
        raise ValueError("Portable atlas resolution must be in [64, 8192]")
    if args.margin_px < 0:
        raise ValueError("Portable atlas margin must be non-negative")
    _validate_output_boundary(source_blend, output_blend, output_evidence, texture_root)
    (
        plan,
        profile,
        provenance,
        plan_sha256,
        profile_sha256,
        source_blend_sha256,
    ) = _verify_contracts(
        plan_path,
        profile_path,
        source_blend,
        args.expected_plan_sha256,
        args.source_blend_sha256,
    )
    _verify_bound_job_artifact(plan, "optimization_plan", "optimization_plan", job_root)
    _verify_bound_job_artifact(plan, "uv_manifest", "uv_manifest", job_root)
    atlas_policy = _validate_atlas_policy(plan, args.resolution, args.margin_px)
    objects = _conversion_objects()
    planned_bindings = _validate_conversion_scope(plan, objects, job_root)
    columns, rows = grid_shape(len(objects))
    tiles = [
        atlas_tile_bounds(index, len(objects), args.resolution, args.margin_px)
        for index in range(len(objects))
    ]
    configure_render_compat(bpy.context.scene, "CYCLES", args.render_device)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    object_records: list[dict[str, Any]] = []
    source_materials: dict[str, bpy.types.Material] = {}
    surface_by_material: dict[str, dict[str, Any]] = {}
    for index, (obj, bounds) in enumerate(zip(objects, tiles, strict=True)):
        source_material, clone, mapping_mode, coordinate_record = _clone_source_material(obj)
        material_id = _material_id(source_material)
        existing_source = source_materials.get(material_id)
        if existing_source is not None and (
            str(existing_source.get("cbm_material_source_fingerprint"))
            != str(source_material.get("cbm_material_source_fingerprint"))
        ):
            raise RuntimeError(f"Material ID {material_id} has inconsistent source fingerprints")
        source_materials[material_id] = source_material
        surface_by_material.setdefault(material_id, _surface_semantics(source_material))
        atlas_record = _create_atlas_uv(obj, bounds)
        topology_record = _repair_tangent_micro_slivers(obj, ATLAS_UV_SET)
        binding_id = stable_identifier(f"{index:06d}.{obj.name}", "binding")
        record = {
            "binding_id": binding_id,
            "derived_object_id": stable_identifier(obj.name, "derived"),
            "name": obj.name,
            "semantic_id": str(obj.get("cbm_id")),
            "source_object": str(obj.get("cbm_source_object")),
            "asset_role": str(obj.get("cbm_asset_role")),
            "lod_level": int(obj.get("cbm_lod_level", 0)),
            "material_id": material_id,
            "mapping_mode": mapping_mode,
            "tile_index": index,
            "atlas": atlas_record,
            "portable_topology": topology_record,
            **coordinate_record,
        }
        object_records.append(record)
        groups[material_id].append({"object": obj, "clone": clone, "record": record})

    required_material_ids = sorted(groups)
    all_clones = [
        entry["clone"]
        for material_id in required_material_ids
        for entry in groups[material_id]
    ]
    global_images, channel_outputs = _bake_global_channels(
        objects,
        all_clones,
        required_material_ids,
        texture_root,
        output_blend,
        args.resolution,
        args.margin_px,
    )
    material_records: list[dict[str, Any]] = []
    for material_id in required_material_ids:
        entries = groups[material_id]
        material_objects = [entry["object"] for entry in entries]
        clone_materials = [entry["clone"] for entry in entries]
        mapping_modes = {entry["record"]["mapping_mode"] for entry in entries}
        if len(mapping_modes) != 1:
            raise RuntimeError(f"Material {material_id} has inconsistent mapping modes")
        mapping_mode = next(iter(mapping_modes))
        semantics = surface_by_material[material_id]
        surface_factors = _portable_surface_factors(semantics)
        portable = _portable_material(
            source_materials[material_id], material_id, semantics, global_images
        )
        for obj in material_objects:
            obj.data.materials[0] = portable
        for clone in clone_materials:
            if clone.users == 0:
                bpy.data.materials.remove(clone)
        material_records.append(
            {
                "material_id": material_id,
                "mapping_mode": mapping_mode,
                "source_shader_recipe": planned_bindings[material_id][
                    "source_shader_recipe"
                ],
                "source_material_fingerprint": str(
                    source_materials[material_id].get("cbm_material_source_fingerprint")
                ),
                "portable_material_fingerprint": fingerprint_json(
                    {
                        "material_id": material_id,
                        "source_material_fingerprint": str(
                            source_materials[material_id].get(
                                "cbm_material_source_fingerprint"
                            )
                        ),
                        "surface_factors": surface_factors,
                        "atlas_uv_set": ATLAS_UV_SET,
                        "channel_hashes": {
                            item["channel"]: item["sha256"]
                            for item in channel_outputs
                        },
                    }
                ),
                "binding_ids": sorted(
                    entry["record"]["binding_id"] for entry in entries
                ),
                "surface_factors": surface_factors,
                "losses": _loss_notes(mapping_mode, semantics),
                "warnings": [],
                "notes": [
                    "All derived users share the five global atlas channel files."
                ],
            }
        )

    scene = bpy.context.scene
    scene["cbm_portable_material_conversion_version"] = SCHEMA_VERSION
    scene["cbm_portable_material_conversion_plan_sha256"] = plan_sha256
    scene["cbm_portable_material_source_blend_sha256"] = source_blend_sha256
    scene["cbm_portable_material_atlas_uv"] = ATLAS_UV_SET
    output_blend_sha256 = _save_portable_blend(output_blend)
    if sha256_file(source_blend) != source_blend_sha256:
        raise RuntimeError("Optimized source blend changed during derived conversion")

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "kind": "portable_material_conversion_evidence",
        "ok": True,
        "job_id": str(plan["job_id"]),
        "profile_id": str(plan["profile_id"]),
        "run_id": plan.get("run_id"),
        "conversion_plan_sha256": plan_sha256,
        "optimized_blend_sha256": source_blend_sha256,
        "source": {
            "optimized_blend_path": str(source_blend),
            "optimized_blend_sha256": source_blend_sha256,
            "conversion_plan_path": str(plan_path),
            "conversion_plan_sha256": plan_sha256,
            "profile_path": str(profile_path),
            "profile_sha256": profile_sha256,
            "build_fingerprint": str(
                scene.get("cbm_portable_source_build_fingerprint")
                or provenance.get("build_fingerprint")
                or ""
            ),
            "optimization_plan_sha256": str(
                scene.get("cbm_portable_plan_sha256") or ""
            ),
        },
        "atlas": {
            **atlas_policy,
            "columns": columns,
            "rows": rows,
            "object_count": len(objects),
            "cross_object_overlap_prevented_by_grid": True,
            "pixel_overlap_measurement": "not_measured",
        },
        "entries": material_records,
        "materials": material_records,
        "tiles": [
            {
                "binding_id": record["binding_id"],
                "material_id": record["material_id"],
                "target_id": record["semantic_id"],
                "derived_object_id": record["derived_object_id"],
                "lod_level": record["lod_level"],
                "uv_set": ATLAS_UV_SET,
                "resolution": [args.resolution, args.resolution],
                "margin_px": args.margin_px,
                "uv_minimum": record["atlas"]["bounds"][:2],
                "uv_maximum": record["atlas"]["bounds"][2:],
                "overlap_fraction": None,
                "quality_status": "partially_verified",
                "unwrap_method": record["atlas"]["unwrap_method"],
                "repaired_uv_degenerate_face_count": record["atlas"][
                    "repaired_degenerate_face_count"
                ],
                "remaining_uv_degenerate_face_count": record["atlas"][
                    "remaining_degenerate_face_count"
                ],
                "tangent_repair_method": record["portable_topology"][
                    "repair_method"
                ],
                "micro_sliver_face_count_before": record[
                    "portable_topology"
                ]["micro_sliver_face_count_before"],
                "remaining_micro_sliver_face_count": record[
                    "portable_topology"
                ]["remaining_micro_sliver_face_count"],
                "tangent_invalid_loop_count_before": record[
                    "portable_topology"
                ]["invalid_loop_count_before"],
                "tangent_invalid_loop_count_after": record[
                    "portable_topology"
                ]["invalid_loop_count_after"],
                "bounds_max_abs_delta_m": record["portable_topology"][
                    "bounds_max_abs_delta_m"
                ],
            }
            for record in object_records
        ],
        "objects": object_records,
        "outputs": channel_outputs,
        "portable_blend": {
            "path": str(output_blend),
            "sha256": output_blend_sha256,
        },
        "texture_root": str(texture_root),
        "runtime": {
            "blender_version": bpy.app.version_string,
            "render_engine": str(scene.get("cbm_render_engine") or "CYCLES"),
            "render_device": str(scene.get("cbm_render_device") or ""),
        },
        "notes": [
            "Only derived render and LOD meshes were converted; authoring and collider "
            "objects were excluded.",
            "Absolute staging paths are raw Blender evidence and must be normalized by "
            "the host contract.",
            "Portable image nodes use paths relative to the converted blend for atomic "
            "directory promotion.",
        ],
    }
    write_json_atomic(output_evidence, evidence)
    print(
        "CBM_PORTABLE_MATERIAL_CONVERSION_OK "
        f"objects={len(objects)} materials={len(material_records)} output={output_blend}"
    )


if __name__ == "__main__":
    main()
