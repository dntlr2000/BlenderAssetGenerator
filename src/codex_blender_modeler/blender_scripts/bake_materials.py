from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

PACKAGE_SRC = Path(__file__).resolve().parents[2]
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from compat import configure_render_compat  # noqa: E402

from codex_blender_modeler.build_provenance import (  # noqa: E402
    BuildProvenanceError,
    require_matching_build_provenance,
)

CHANNELS = ("base_color", "roughness", "metallic", "normal", "emission")
COLOR_SPACES = {
    "base_color": "sRGB",
    "roughness": "Non-Color",
    "metallic": "Non-Color",
    "normal": "Non-Color",
    "emission": "sRGB",
}


def parse_args() -> argparse.Namespace:
    """Parse bounded material-bake inputs from the host runner."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--resolution", type=int, default=1024)
    parser.add_argument("--margin", type=int, default=16)
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--material-id", action="append", default=[])
    parser.add_argument("--expected-build-fingerprint", required=True)
    parser.add_argument("--source-blend-sha256", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    """Hash one baked artifact for manifest reproducibility."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(material_id: str) -> str:
    """Map a stable material ID to a traversal-safe deterministic directory name."""

    if re.fullmatch(r"[A-Za-z0-9._-]+", material_id) and material_id not in {".", ".."}:
        return material_id
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", material_id).strip("._-") or "material"
    digest = hashlib.sha256(material_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _material_id(material: bpy.types.Material) -> str:
    """Return one stable material identity from the generated Blender scene."""

    return str(material.get("cbm_id", material.name))


def _selected_materials(requested: list[str]) -> list[bpy.types.Material]:
    """Resolve requested IDs or all recipe-backed materials in stable order."""

    materials = sorted(bpy.data.materials, key=_material_id)
    by_id = {_material_id(material): material for material in materials}
    if requested:
        missing = sorted(set(requested) - set(by_id))
        if missing:
            raise RuntimeError(f"Requested bake materials do not exist: {missing}")
        return [by_id[material_id] for material_id in sorted(set(requested))]
    return [material for material in materials if material.get("cbm_shader_recipe")]


def _objects_for_material(material: bpy.types.Material) -> list[bpy.types.Object]:
    """Find visible semantic mesh objects exclusively assigned to one material."""

    result: list[bpy.types.Object] = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not obj.get("cbm_id") or obj.hide_render:
            continue
        assigned = [slot.material for slot in obj.material_slots if slot.material is not None]
        if material not in assigned:
            continue
        unique = {item.as_pointer() for item in assigned}
        if len(unique) != 1:
            raise RuntimeError(
                f"{obj.name} uses multiple materials; bounded per-material baking is unsupported"
            )
        result.append(obj)
    return sorted(result, key=lambda item: item.name)


def _require_uv(objects: list[bpy.types.Object], material: bpy.types.Material) -> str:
    """Require the approved UV mapping mode and activate the requested layer on every mesh."""

    material_id = _material_id(material)
    mode = str(material.get("cbm_mapping_mode", ""))
    if mode != "uv":
        raise RuntimeError(
            f"{material_id} cannot be export-baked because mapping.mode is "
            f"{mode or 'unset'!r}, not 'uv'"
        )
    uv_set = str(material.get("cbm_uv_set", "UVMap"))
    if not objects:
        raise RuntimeError(f"{material_id} has no visible semantic mesh objects")
    for obj in objects:
        layer = obj.data.uv_layers.get(uv_set)
        if layer is None:
            raise RuntimeError(f"{obj.name} is missing required UV set {uv_set!r}")
        obj.data.uv_layers.active = layer
        layer.active_render = True
    return uv_set


def _source_recipe(job_root: Path, material: bpy.types.Material) -> str:
    """Normalize a recipe provenance path and reject paths outside the job."""

    raw = material.get("cbm_shader_recipe")
    if not raw:
        raise RuntimeError(f"{_material_id(material)} has no approved shader recipe provenance")
    path = Path(str(raw)).expanduser().resolve()
    try:
        return path.relative_to(job_root).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"Shader recipe is outside the job root: {path}") from exc


def _require_source_blend(expected_sha256: str) -> str:
    """Verify the opened Blender file bytes before baking or mutating any node graph."""

    source = Path(bpy.data.filepath).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Opened Blender source does not exist: {source}")
    actual = _sha256(source)
    if actual != expected_sha256:
        raise RuntimeError(
            f"Opened Blender source hash changed before bake: {expected_sha256} != {actual}"
        )
    return actual


def _require_scene_build_provenance(expected_fingerprint: str) -> dict[str, Any]:
    """Require the opened scene to have been built from the current canonical contracts."""

    scene = bpy.context.scene
    stored_json = scene.get("cbm_build_provenance")
    if not isinstance(stored_json, str):
        raise RuntimeError("Blender scene lacks build provenance; rebuild before baking")
    try:
        provenance = require_matching_build_provenance(stored_json, expected_fingerprint)
    except BuildProvenanceError as exc:
        raise RuntimeError(str(exc)) from exc
    if scene.get("cbm_material_build_fingerprint") != expected_fingerprint:
        raise RuntimeError("Blender scene material build fingerprint is missing or inconsistent")
    if scene.get("cbm_scene_spec_sha256") != provenance.get("scene_spec_sha256"):
        raise RuntimeError("Blender scene SceneSpec hash is inconsistent with build provenance")
    return provenance


def _material_build_provenance(
    material: bpy.types.Material,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Match one baked material datablock to its embedded recipe and texture fingerprints."""

    material_id = _material_id(material)
    materials = provenance.get("materials")
    source = materials.get(material_id) if isinstance(materials, dict) else None
    if not isinstance(source, dict) or not source.get("shader_recipe_sha256"):
        raise RuntimeError(f"{material_id} lacks recipe-backed build provenance; rebuild required")
    if material.get("cbm_material_source_fingerprint") != source.get("fingerprint"):
        raise RuntimeError(
            f"{material_id} material datablock provenance is stale; rebuild required"
        )
    if material.get("cbm_shader_recipe_sha256") != source.get("shader_recipe_sha256"):
        raise RuntimeError(f"{material_id} shader recipe provenance is stale; rebuild required")
    expected_manifest = source.get("texture_manifest_sha256")
    actual_manifest = material.get("cbm_texture_manifest_sha256")
    if expected_manifest and actual_manifest != expected_manifest:
        raise RuntimeError(f"{material_id} texture manifest provenance is stale; rebuild required")
    if not expected_manifest and actual_manifest:
        raise RuntimeError(f"{material_id} has unexpected texture manifest provenance")
    return source


def _activate_objects(objects: list[bpy.types.Object]) -> None:
    """Select all material users and make the first one active for Cycles baking."""

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]


def _material_output(material: bpy.types.Material) -> bpy.types.ShaderNodeOutputMaterial:
    """Find the active material output node used by the master shader."""

    outputs = [node for node in material.node_tree.nodes if node.type == "OUTPUT_MATERIAL"]
    active = next((node for node in outputs if getattr(node, "is_active_output", False)), None)
    if active is None and outputs:
        active = outputs[0]
    if active is None:
        raise RuntimeError(f"{_material_id(material)} has no material output node")
    return active


def _principled(material: bpy.types.Material) -> bpy.types.ShaderNodeBsdfPrincipled | None:
    """Return the first Principled BSDF node when the master shader uses one."""

    return next((node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"), None)


def _socket(node: Any, names: tuple[str, ...]) -> Any | None:
    """Feature-probe a semantic shader input across Blender socket renames."""

    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    return None


def _channel_input(material: bpy.types.Material, channel: str) -> Any | None:
    """Resolve the master shader input corresponding to one portable bake channel."""

    shader = _principled(material)
    if shader is not None:
        names = {
            "base_color": ("Base Color",),
            "roughness": ("Roughness",),
            "metallic": ("Metallic",),
            "emission": ("Emission Color", "Emission"),
        }[channel]
        return _socket(shader, names)
    if channel == "emission":
        emission = next(
            (node for node in material.node_tree.nodes if node.type == "EMISSION"), None
        )
        return emission.inputs.get("Color") if emission is not None else None
    return None


def _constant_color(
    material: bpy.types.Material,
    channel: str,
) -> tuple[float, float, float, float]:
    """Provide conservative constants when a legacy shader lacks Principled sockets."""

    if channel == "base_color":
        return tuple(float(value) for value in material.diffuse_color)
    if channel == "roughness":
        value = float(getattr(material, "roughness", 0.5))
        return (value, value, value, 1.0)
    if channel == "metallic":
        value = float(getattr(material, "metallic", 0.0))
        return (value, value, value, 1.0)
    return (0.0, 0.0, 0.0, 1.0)


def _route_channel_to_emission(material: bpy.types.Material, channel: str) -> tuple[Any, Any]:
    """Temporarily route a portable surface channel to emission for lossless baking."""

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    output = _material_output(material)
    surface = output.inputs["Surface"]
    original = surface.links[0].from_socket if surface.is_linked else None
    for link in list(surface.links):
        links.remove(link)
    emission = nodes.new("ShaderNodeEmission")
    emission.name = f"CBM_Bake_{channel}"
    source = _channel_input(material, channel)
    if source is not None and source.is_linked:
        links.new(source.links[0].from_socket, emission.inputs["Color"])
    elif source is not None:
        value = source.default_value
        if isinstance(value, (int, float)):
            emission.inputs["Color"].default_value = (float(value),) * 3 + (1.0,)
        else:
            emission.inputs["Color"].default_value = tuple(value)
    else:
        emission.inputs["Color"].default_value = _constant_color(material, channel)
    links.new(emission.outputs[0], surface)
    return emission, original


def _restore_surface(material: bpy.types.Material, emission: Any, original: Any) -> None:
    """Restore the unmodified master surface graph after one channel bake."""

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    output = _material_output(material)
    surface = output.inputs["Surface"]
    for link in list(surface.links):
        links.remove(link)
    if original is not None:
        links.new(original, surface)
    nodes.remove(emission)


def _new_target_image(
    material: bpy.types.Material,
    channel: str,
    resolution: int,
) -> tuple[bpy.types.Image, Any]:
    """Create one deterministic bake image and make its node the active target."""

    image = bpy.data.images.new(
        name=f"CBM_Bake_{_material_id(material)}_{channel}",
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
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    node.name = f"CBM_BakeTarget_{channel}"
    node.image = image
    material.node_tree.nodes.active = node
    node.select = True
    return image, node


def _bake_operator(bake_type: str, margin: int) -> None:
    """Feature-probe Cycles bake arguments and require a successful operator result."""

    scene_bake = bpy.context.scene.render.bake
    if hasattr(scene_bake, "margin"):
        scene_bake.margin = margin
    if hasattr(scene_bake, "use_clear"):
        scene_bake.use_clear = True
    identifiers = {prop.identifier for prop in bpy.ops.object.bake.get_rna_type().properties}
    kwargs: dict[str, Any] = {"type": bake_type}
    if "margin" in identifiers:
        kwargs["margin"] = margin
    if "use_clear" in identifiers:
        kwargs["use_clear"] = True
    result = bpy.ops.object.bake(**kwargs)
    if "FINISHED" not in result:
        raise RuntimeError(f"Cycles bake returned {sorted(result)}")


def _save_image(image: bpy.types.Image, path: Path) -> str:
    """Save a baked image as PNG and return its SHA-256 digest."""

    path.parent.mkdir(parents=True, exist_ok=True)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    if not path.is_file():
        raise RuntimeError(f"Blender did not write baked image: {path}")
    return _sha256(path)


def _bake_channel(
    material: bpy.types.Material,
    objects: list[bpy.types.Object],
    channel: str,
    output: Path,
    resolution: int,
    margin: int,
) -> dict[str, Any]:
    """Bake one supported PBR channel without saving mutations to the source blend."""

    image, target_node = _new_target_image(material, channel, resolution)
    emission = None
    original = None
    try:
        _activate_objects(objects)
        if channel == "normal":
            bake_type = "NORMAL"
        else:
            emission, original = _route_channel_to_emission(material, channel)
            material.node_tree.nodes.active = target_node
            bake_type = "EMIT"
        _bake_operator(bake_type, margin)
        digest = _save_image(image, output)
    finally:
        if emission is not None:
            _restore_surface(material, emission, original)
        material.node_tree.nodes.remove(target_node)
        bpy.data.images.remove(image)
    return {
        "channel": channel,
        "path": output.as_posix(),
        "color_space": COLOR_SPACES[channel],
        "sha256": digest,
    }


def _write_manifest(path: Path, payload: dict[str, Any]) -> None:
    """Write one complete or failed bake manifest atomically enough for host validation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _bake_material(
    material: bpy.types.Material,
    job_root: Path,
    profile: str,
    resolution: int,
    margin: int,
    build_provenance: dict[str, Any],
    source_blend_sha256: str,
) -> tuple[dict[str, Any], Path]:
    """Bake the five bounded export channels for one stable material ID."""

    material_id = _material_id(material)
    output_dir = job_root / "bakes" / _safe_component(material_id) / profile
    manifest_path = output_dir / "bake_manifest.json"
    source_recipe = _source_recipe(job_root, material)
    material_provenance = _material_build_provenance(material, build_provenance)
    channel_hashes = {
        channel: record["sha256"]
        for channel, record in material_provenance.get("texture_channels", {}).items()
    }
    manifest: dict[str, Any] = {
        "schema_version": "0.5.0",
        "job_id": str(bpy.context.scene.get("cbm_job_id", job_root.name)),
        "material_id": material_id,
        "source_shader_recipe": source_recipe,
        "source_scene_spec_sha256": build_provenance["scene_spec_sha256"],
        "source_geometry_payloads_sha256": build_provenance["geometry_payloads_sha256"],
        "source_camera_fingerprint": build_provenance["camera_fingerprint"],
        "source_material_plan_sha256": build_provenance["material_plan_sha256"],
        "source_shader_recipe_sha256": material_provenance["shader_recipe_sha256"],
        "source_texture_manifest": material_provenance["texture_manifest_path"],
        "source_texture_manifest_sha256": material_provenance["texture_manifest_sha256"],
        "source_texture_channels_sha256": channel_hashes,
        "source_blend_sha256": source_blend_sha256,
        "source_build_fingerprint": build_provenance["fingerprint"],
        "source_material_fingerprint": material_provenance["fingerprint"],
        "profile": profile,
        "resolution": [resolution, resolution],
        "uv_set": str(material.get("cbm_uv_set", "UVMap")),
        "margin_px": margin,
        "outputs": [],
        "status": "planned",
        "blender_version": bpy.app.version_string,
        "notes": [
            "Baked in Cycles from the approved generated .blend without saving graph mutations.",
            "Outputs are separate portable channels; profile-specific packing is not performed.",
        ],
    }
    try:
        objects = _objects_for_material(material)
        manifest["uv_set"] = _require_uv(objects, material)
        outputs = []
        for channel in CHANNELS:
            path = output_dir / f"{channel}.png"
            record = _bake_channel(material, objects, channel, path, resolution, margin)
            record["path"] = path.relative_to(job_root).as_posix()
            outputs.append(record)
        manifest["outputs"] = outputs
        manifest["status"] = "complete"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["notes"].append(str(exc))
    _write_manifest(manifest_path, manifest)
    return manifest, manifest_path


def main() -> None:
    """Bake requested materials and emit a host-readable aggregate report."""

    args = parse_args()
    job_root = Path(args.job_root).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    if args.profile not in {
        "blender_eevee",
        "blender_cycles",
        "gltf_pbr",
    }:
        raise ValueError(
            f"Unsupported implemented bake profile: {args.profile}. "
            "Runtime-specific channel packing requires a separately selected target adapter."
        )
    if args.resolution < 1 or args.resolution > 8192:
        raise ValueError("resolution must be in [1, 8192]")
    if args.margin < 0:
        raise ValueError("margin must be non-negative")

    source_blend_sha256 = _require_source_blend(args.source_blend_sha256)
    build_provenance = _require_scene_build_provenance(args.expected_build_fingerprint)
    configure_render_compat(bpy.context.scene, "CYCLES", args.render_device)
    materials = _selected_materials(args.material_id)
    if not materials:
        raise RuntimeError("No recipe-backed materials are available to bake")
    manifests: list[dict[str, Any]] = []
    paths: list[str] = []
    for material in materials:
        manifest, path = _bake_material(
            material,
            job_root,
            args.profile,
            args.resolution,
            args.margin,
            build_provenance,
            source_blend_sha256,
        )
        manifests.append(manifest)
        paths.append(path.relative_to(job_root).as_posix())
    failed = [item["material_id"] for item in manifests if item["status"] != "complete"]
    report = {
        "schema_version": "0.5.0",
        "job_id": str(bpy.context.scene.get("cbm_job_id", job_root.name)),
        "ok": not failed,
        "profile": args.profile,
        "resolution": [args.resolution, args.resolution],
        "blender_version": bpy.app.version_string,
        "render_engine": str(bpy.context.scene.render.engine),
        "render_device": str(bpy.context.scene.get("cbm_render_device", "CPU")),
        "channel_layout": "separate_portable_channels",
        "profile_packing_performed": False,
        "source_blend_sha256": source_blend_sha256,
        "source_build_fingerprint": build_provenance["fingerprint"],
        "manifest_paths": paths,
        "material_count": len(manifests),
        "failed_material_ids": failed,
    }
    _write_manifest(report_path, report)
    print(
        f"CBM_BAKE_MATERIALS_OK ok={report['ok']} materials={len(manifests)} "
        f"failed={len(failed)} report={report_path}"
    )


if __name__ == "__main__":
    main()
