from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from artifact_render_common import configure_artifact_render  # noqa: E402

from codex_blender_modeler.blender_artifacts import (  # noqa: E402
    artifact_path,
    linear_to_srgb,
    rgb_hex,
    sha256_file,
    stable_json_digest,
    unique_color_map,
    write_json_atomic,
)
from codex_blender_modeler.build_provenance import (  # noqa: E402
    camera_contract_fingerprint,
    require_matching_build_provenance,
)

PASS_KINDS = (
    "beauty",
    "silhouette",
    "object_id",
    "material_id",
    "normal",
    "depth",
    "wireframe",
)


def parse_args() -> argparse.Namespace:
    """Parse QA pass output, renderer, and reproducibility metadata arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--render-engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--scene-spec", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--camera-fingerprint")
    parser.add_argument("--scene-spec-sha256")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _new_material(name: str) -> tuple[bpy.types.Material, bpy.types.Nodes, bpy.types.NodeLinks]:
    """Create a clean node material for one deterministic QA override."""

    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    return material, nodes, links


def _emission_output(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    color_socket: bpy.types.NodeSocket | None = None,
    color: tuple[float, float, float, float] | None = None,
) -> None:
    """Connect a color socket or constant color to an unlit material output."""

    emission = nodes.new("ShaderNodeEmission")
    emission.name = "CBM_QA_Emission"
    if color_socket is not None:
        links.new(color_socket, emission.inputs["Color"])
    elif color is not None:
        emission.inputs["Color"].default_value = color
    emission.inputs["Strength"].default_value = 1.0
    output = nodes.new("ShaderNodeOutputMaterial")
    links.new(emission.outputs["Emission"], output.inputs["Surface"])


def _flat_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    """Create a constant emission override for silhouette rendering."""

    material, nodes, links = _new_material(name)
    _emission_output(nodes, links, color=color)
    return material


def _object_color_material(name: str) -> bpy.types.Material:
    """Create an override that emits each object's deterministic viewport color."""

    material, nodes, links = _new_material(name)
    info = nodes.new("ShaderNodeObjectInfo")
    _emission_output(nodes, links, color_socket=info.outputs["Color"])
    return material


def _normal_material() -> bpy.types.Material:
    """Create a world-normal override encoded from -1..1 into displayable 0..1 values."""

    material, nodes, links = _new_material("CBM_QA_Normal")
    geometry = nodes.new("ShaderNodeNewGeometry")
    multiply = nodes.new("ShaderNodeVectorMath")
    multiply.operation = "MULTIPLY"
    multiply.inputs[1].default_value = (0.5, 0.5, 0.5)
    add = nodes.new("ShaderNodeVectorMath")
    add.operation = "ADD"
    add.inputs[1].default_value = (0.5, 0.5, 0.5)
    links.new(geometry.outputs["Normal"], multiply.inputs[0])
    links.new(multiply.outputs["Vector"], add.inputs[0])
    _emission_output(nodes, links, color_socket=add.outputs["Vector"])
    return material


def _depth_material(near: float, far: float) -> bpy.types.Material:
    """Create a camera-depth override normalized from white-near to black-far."""

    material, nodes, links = _new_material("CBM_QA_Depth")
    camera_data = nodes.new("ShaderNodeCameraData")
    mapping = nodes.new("ShaderNodeMapRange")
    mapping.inputs["From Min"].default_value = near
    mapping.inputs["From Max"].default_value = far
    mapping.inputs["To Min"].default_value = 1.0
    mapping.inputs["To Max"].default_value = 0.0
    mapping.clamp = True
    links.new(camera_data.outputs["View Z Depth"], mapping.inputs["Value"])
    _emission_output(nodes, links, color_socket=mapping.outputs["Result"])
    return material


def _wireframe_material() -> bpy.types.Material:
    """Create a feature-probed pixel-width wireframe override material."""

    material, nodes, links = _new_material("CBM_QA_Wireframe")
    try:
        wire = nodes.new("ShaderNodeWireframe")
    except RuntimeError as exc:
        raise RuntimeError("The running Blender build has no Wireframe shader node") from exc
    wire.use_pixel_size = True
    wire.inputs["Size"].default_value = 1.25
    _emission_output(nodes, links, color_socket=wire.outputs["Fac"])
    return material


def _set_black_world(scene: bpy.types.Scene) -> None:
    """Set an opaque black machine-pass background without saving the blend."""

    world = scene.world or bpy.data.worlds.new("CBM_QA_World")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background is not None:
        background.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs["Strength"].default_value = 0.0
    scene.render.film_transparent = False


def _set_machine_color_management(scene: bpy.types.Scene, warnings: list[str]) -> None:
    """Feature-probe a neutral Standard/None transform for ID and metric passes."""

    try:
        scene.view_settings.view_transform = "Standard"
    except (TypeError, ValueError, RuntimeError) as exc:
        warnings.append(f"Standard view transform unavailable: {exc}")
    try:
        scene.view_settings.look = "None"
    except (TypeError, ValueError, RuntimeError) as exc:
        warnings.append(f"Neutral color-management look unavailable: {exc}")
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def _camera_record(camera: bpy.types.Object) -> dict[str, Any]:
    """Serialize the fixed comparison camera values used by every QA pass."""

    data = camera.data
    return {
        "name": camera.name,
        "type": data.type,
        "location": [round(float(value), 9) for value in camera.location],
        "rotation_deg": [round(math.degrees(float(value)), 9) for value in camera.rotation_euler],
        "lens_mm": float(data.lens),
        "ortho_scale": float(data.ortho_scale),
        "clip_start": float(data.clip_start),
        "clip_end": float(data.clip_end),
    }


def _visible_depth_range(
    camera: bpy.types.Object,
    objects: list[bpy.types.Object],
) -> tuple[float, float]:
    """Fit the normalized depth pass to visible object bounding boxes instead of clip limits."""

    inverse_camera = camera.matrix_world.inverted()
    depths = [
        float(-(inverse_camera @ (obj.matrix_world @ Vector(corner))).z)
        for obj in objects
        for corner in obj.bound_box
    ]
    depths = [value for value in depths if value > 0.0 and math.isfinite(value)]
    if not depths:
        return float(camera.data.clip_start), float(camera.data.clip_end)
    minimum = max(float(camera.data.clip_start), min(depths))
    maximum = min(float(camera.data.clip_end), max(depths))
    span = maximum - minimum
    if span <= 1e-6:
        padding = max(0.01, minimum * 0.01)
        return max(float(camera.data.clip_start), minimum - padding), maximum + padding
    padding = span * 0.02
    return (
        max(float(camera.data.clip_start), minimum - padding),
        min(float(camera.data.clip_end), maximum + padding),
    )


def _load_scene_spec(path: Path) -> dict[str, Any]:
    """Load the canonical SceneSpec used to verify the built Blender scene."""

    if not path.is_file():
        raise FileNotFoundError(f"Canonical SceneSpec is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Canonical SceneSpec is invalid JSON: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("camera"), dict):
        raise RuntimeError("Canonical SceneSpec must contain an object-valued camera")
    return value


def _require_close(actual: float, expected: float, label: str) -> None:
    """Reject one changed Blender camera scalar outside deterministic build tolerance."""

    if not math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-6):
        raise RuntimeError(
            f"Built Blender camera {label} is stale or edited: {actual} != {expected}"
        )


def _validate_actual_camera(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    expected: dict[str, Any],
) -> None:
    """Compare the active Blender camera to every fixed SceneSpec camera field."""

    if camera.data.type != expected["projection"]:
        raise RuntimeError(
            "Built Blender camera projection is stale or edited: "
            f"{camera.data.type} != {expected['projection']}"
        )
    expected_location = Vector(expected["location"])
    actual_location = camera.matrix_world.translation
    if (actual_location - expected_location).length > 1e-6:
        raise RuntimeError(
            "Built Blender camera location is stale or edited: "
            f"{list(actual_location)} != {list(expected_location)}"
        )
    _require_close(float(camera.data.lens), float(expected["focal_length_mm"]), "lens")
    _require_close(
        float(camera.data.ortho_scale),
        float(expected["ortho_scale"]),
        "ortho scale",
    )
    target_direction = Vector(expected["target"]) - expected_location
    if target_direction.length <= 1e-9:
        raise RuntimeError("SceneSpec camera target must differ from its location")
    target_direction.normalize()
    actual_direction = camera.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))
    actual_direction.normalize()
    if actual_direction.dot(target_direction) < 1.0 - 1e-6:
        raise RuntimeError("Built Blender camera direction no longer targets SceneSpec target")
    resolution = [
        round(scene.render.resolution_x * scene.render.resolution_percentage / 100),
        round(scene.render.resolution_y * scene.render.resolution_percentage / 100),
    ]
    if resolution != [int(value) for value in expected["resolution"]]:
        raise RuntimeError(
            "Built Blender camera resolution is stale or edited: "
            f"{resolution} != {expected['resolution']}"
        )


def _validated_build_provenance(
    scene: bpy.types.Scene,
    camera: bpy.types.Object,
    scene_spec_path: Path,
    *,
    expected_build_fingerprint: str,
    expected_scene_spec_sha256: str | None,
    expected_camera_fingerprint: str | None,
) -> tuple[str, str, str]:
    """Bind QA to current canonical inputs, embedded build metadata, and actual camera state."""

    spec = _load_scene_spec(scene_spec_path)
    current_scene_hash = sha256_file(scene_spec_path)
    current_camera_fingerprint = camera_contract_fingerprint(spec["camera"])
    if spec.get("job_id") != scene.get("cbm_job_id"):
        raise RuntimeError("Built Blender scene job_id does not match the canonical SceneSpec")
    if expected_scene_spec_sha256 not in {None, current_scene_hash}:
        raise RuntimeError("Requested QA SceneSpec hash does not match canonical input")
    if expected_camera_fingerprint not in {None, current_camera_fingerprint}:
        raise RuntimeError("Requested QA camera fingerprint does not match canonical input")

    stored_scene_hash = scene.get("cbm_scene_spec_sha256")
    stored_camera_fingerprint = scene.get("cbm_camera_fingerprint")
    if stored_scene_hash != current_scene_hash:
        raise RuntimeError(
            "Blender scene was built from a different SceneSpec; rebuild before visual QA"
        )
    if stored_camera_fingerprint != current_camera_fingerprint:
        raise RuntimeError(
            "Blender scene was built from a different camera; rebuild before visual QA"
        )

    stored_build_raw = scene.get("cbm_build_provenance")
    if not stored_build_raw:
        raise RuntimeError("Blender scene has no build provenance; rebuild before visual QA")
    stored_build = require_matching_build_provenance(
        str(stored_build_raw),
        expected_build_fingerprint,
        operation="visual QA",
    )
    actual_build_fingerprint = str(stored_build["fingerprint"])
    if stored_build.get("scene_spec_sha256") != current_scene_hash:
        raise RuntimeError("Embedded build provenance has a different SceneSpec hash")
    if stored_build.get("camera_fingerprint") != current_camera_fingerprint:
        raise RuntimeError("Embedded build provenance has a different camera fingerprint")

    stored_camera_source = scene.get("cbm_camera_source_json")
    if not stored_camera_source:
        raise RuntimeError("Blender scene has no camera source contract; rebuild before visual QA")
    try:
        source_camera = json.loads(str(stored_camera_source))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Blender scene camera source contract is invalid JSON") from exc
    if camera_contract_fingerprint(source_camera) != current_camera_fingerprint:
        raise RuntimeError("Embedded Blender camera source differs from canonical SceneSpec")
    _validate_actual_camera(scene, camera, source_camera)
    return current_scene_hash, current_camera_fingerprint, actual_build_fingerprint


def _material_id_for_object(obj: bpy.types.Object, warnings: list[str]) -> str:
    """Resolve the primary stable material ID used for the flat material-ID pass."""

    identifiers = [
        str(slot.material.get("cbm_id", slot.material.name))
        for slot in obj.material_slots
        if slot.material is not None
    ]
    unique = sorted(set(identifiers))
    if len(unique) > 1:
        warnings.append(
            f"{obj.name}: material_id pass uses primary material {unique[0]!r}; "
            f"additional material IDs={unique[1:]}"
        )
    return unique[0] if unique else "__unassigned__"


def _display_hex(color: tuple[float, float, float]) -> str:
    """Encode the expected Standard-view PNG value for a linear object color."""

    display = tuple(linear_to_srgb(channel) for channel in color)
    return rgb_hex(display)  # type: ignore[arg-type]


def _render_pass(
    scene: bpy.types.Scene,
    view_layer: bpy.types.ViewLayer,
    output: Path,
    override: bpy.types.Material | None,
) -> None:
    """Render one pass through the fixed camera with an optional material override."""

    output.parent.mkdir(parents=True, exist_ok=True)
    view_layer.material_override = override
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)


def _pass_record(
    kind: str,
    path: Path,
    manifest_path: Path,
    resolution: list[int],
) -> dict[str, Any]:
    """Build one hashed QA pass manifest record after a successful render."""

    return {
        "kind": kind,
        "path": artifact_path(path, manifest_path),
        "sha256": sha256_file(path),
        "width": resolution[0],
        "height": resolution[1],
        "encoding": "png-rgb8",
    }


def main() -> None:
    """Render beauty and shader-independent QA passes plus a reproducibility manifest."""

    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    scene_spec_path = Path(args.scene_spec).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_artifact_render(args.render_engine, args.render_device)
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    if scene.camera is None:
        raise RuntimeError("QA pass rendering requires the fixed comparison camera")

    resolution = [
        round(scene.render.resolution_x * scene.render.resolution_percentage / 100),
        round(scene.render.resolution_y * scene.render.resolution_percentage / 100),
    ]
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    warnings: list[str] = []
    camera = _camera_record(scene.camera)
    scene_spec_sha256, camera_fingerprint, build_fingerprint = (
        _validated_build_provenance(
            scene,
            scene.camera,
            scene_spec_path,
            expected_build_fingerprint=args.build_fingerprint,
            expected_scene_spec_sha256=args.scene_spec_sha256,
            expected_camera_fingerprint=args.camera_fingerprint,
        )
    )
    semantic_objects = [
        obj
        for obj in sorted(scene.objects, key=lambda item: item.name)
        if obj.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}
    ]
    object_ids = [str(obj.get("cbm_id", obj.name)) for obj in semantic_objects]
    material_ids_by_object = {
        obj.name: _material_id_for_object(obj, warnings) for obj in semantic_objects
    }
    object_colors = unique_color_map(object_ids)
    material_colors = unique_color_map(list(material_ids_by_object.values()))
    depth_near, depth_far = _visible_depth_range(scene.camera, semantic_objects)

    records: list[dict[str, Any]] = []
    beauty_path = output_dir / "beauty.png"
    _render_pass(scene, view_layer, beauty_path, None)
    records.append(_pass_record("beauty", beauty_path, manifest_path, resolution))

    _set_black_world(scene)
    _set_machine_color_management(scene, warnings)
    overrides = {
        "silhouette": _flat_material("CBM_QA_Silhouette", (1.0, 1.0, 1.0, 1.0)),
        "object_id": _object_color_material("CBM_QA_ObjectID"),
        "material_id": _object_color_material("CBM_QA_MaterialID"),
        "normal": _normal_material(),
        "depth": _depth_material(depth_near, depth_far),
        "wireframe": _wireframe_material(),
    }
    for kind in PASS_KINDS[1:]:
        if kind == "object_id":
            for obj in semantic_objects:
                color = object_colors[str(obj.get("cbm_id", obj.name))]
                obj.color = (*color, 1.0)
        elif kind == "material_id":
            for obj in semantic_objects:
                color = material_colors[material_ids_by_object[obj.name]]
                obj.color = (*color, 1.0)
        path = output_dir / f"{kind}.png"
        _render_pass(scene, view_layer, path, overrides[kind])
        records.append(_pass_record(kind, path, manifest_path, resolution))

    view_layer.material_override = None
    run_seed = {
        "job_id": str(scene.get("cbm_job_id") or "__unknown__"),
        "scene_spec_sha256": scene_spec_sha256,
        "camera_fingerprint": camera_fingerprint,
        "build_fingerprint": build_fingerprint,
        "actual_camera": camera,
        "render_engine": scene.get("cbm_render_engine", scene.render.engine),
        "render_device": scene.get("cbm_render_device", "DEFAULT"),
        "passes": [record["sha256"] for record in records],
    }
    manifest = {
        "schema_version": "0.6.0",
        "job_id": str(scene.get("cbm_job_id") or "__unknown__"),
        "run_id": args.run_id or stable_json_digest(run_seed)[:20],
        "scene_spec_sha256": scene_spec_sha256,
        "camera_fingerprint": camera_fingerprint,
        "build_fingerprint": build_fingerprint,
        "blender_version": bpy.app.version_string,
        "render_engine": scene.get("cbm_render_engine", scene.render.engine),
        "render_device": scene.get("cbm_render_device", "DEFAULT"),
        "resolution": resolution,
        "passes": records,
        "object_id_colors": {
            identifier: _display_hex(color) for identifier, color in object_colors.items()
        },
        "material_id_colors": {
            identifier: _display_hex(color) for identifier, color in material_colors.items()
        },
        "depth_range": {
            "near": depth_near,
            "far": depth_far,
        },
        "warnings": warnings,
    }
    write_json_atomic(manifest_path, manifest)
    print(f"CBM_QA_PASSES_OK passes={len(records)} manifest={manifest_path}")


if __name__ == "__main__":
    main()
