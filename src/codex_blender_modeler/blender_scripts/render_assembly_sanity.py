"""Render five temporary assembly-frame cameras without saving the authoring blend."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Matrix, Vector

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_SRC = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from artifact_render_common import configure_artifact_render  # noqa: E402
from assembly_runtime import (  # noqa: E402
    evaluate_assembly_relationships,
    evaluated_bounds_in_frame,
    load_assembly_contract,
    resolve_assembly_world_to_frame,
)
from render_qa_passes import (  # noqa: E402
    _display_hex,
    _flat_material,
    _object_color_material,
    _render_pass,
    _set_black_world,
    _set_machine_color_management,
    _validated_build_provenance,
    _wireframe_material,
)

from codex_blender_modeler.blender_artifacts import (  # noqa: E402
    sha256_file,
    unique_color_map,
    write_json_atomic,
)

VIEW_IDS = ("front", "right", "top", "rear", "oblique")
PASS_KINDS = ("beauty", "silhouette", "object_id", "wireframe")


def parse_args() -> argparse.Namespace:
    """Parse exact plan, source, and bounded render configuration arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scene-spec", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--render-engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load one required immutable JSON object for Blender-side validation."""

    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _require_contained(root: Path, path: Path, label: str) -> Path:
    """Resolve one path and reject absolute evidence outside the owning job."""

    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} is outside the owning job: {resolved}") from exc
    return resolved


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one artifact as a normalized path relative to the job root."""

    return _require_contained(root, path, "diagnostic artifact").relative_to(
        root.resolve()
    ).as_posix()


def _temporary_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    """Create one in-memory camera that is never saved to the source blend."""

    camera_data = bpy.data.cameras.new("CBM_AssemblySanity_CameraData")
    camera = bpy.data.objects.new("CBM_AssemblySanity_Camera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = "PERSP"
    camera_data.lens = 50.0
    return camera


def _camera_record(
    camera: bpy.types.Object,
    target: Vector,
    view: dict[str, Any],
) -> dict[str, Any]:
    """Serialize the exact temporary camera used for one structural view."""

    return {
        "name": camera.name,
        "type": camera.data.type,
        "view_id": view["view_id"],
        "camera_direction_frame": [
            round(float(value), 9) for value in view["camera_direction_frame"]
        ],
        "screen_up_role": view["screen_up_role"],
        "location": [round(float(value), 9) for value in camera.location],
        "rotation_deg": [
            round(math.degrees(float(value)), 9) for value in camera.rotation_euler
        ],
        "target": [round(float(value), 9) for value in target],
        "lens_mm": float(camera.data.lens),
        "clip_start": float(camera.data.clip_start),
        "clip_end": float(camera.data.clip_end),
    }


def _apply_view(
    camera: bpy.types.Object,
    view: dict[str, Any],
    *,
    assembly_frame: dict[str, Any],
    target_frame: Vector,
    distance: float,
    radius: float,
    frame_to_world: Any,
) -> Vector:
    """Place and roll one camera from declared root-frame direction and up axes."""

    direction_frame = Vector(
        tuple(float(value) for value in view["camera_direction_frame"])
    )
    if direction_frame.length <= 1e-9:
        raise ValueError(f"Assembly sanity view {view['view_id']} has an empty direction")
    direction_frame.normalize()
    location_frame = target_frame + direction_frame * distance
    target_world = frame_to_world @ target_frame
    location_world = frame_to_world @ location_frame
    direction_world = target_world - location_world
    if direction_world.length <= 1e-9:
        raise ValueError(f"Assembly sanity view {view['view_id']} has an empty world direction")
    forward_world = direction_world.normalized()
    up_role = str(view["screen_up_role"])
    axis_name = assembly_frame.get(f"{up_role}_axis")
    axis_index = {"X": 0, "Y": 1, "Z": 2}.get(str(axis_name))
    if axis_index is None:
        raise ValueError(f"Assembly sanity view has invalid screen-up role: {up_role}")
    up_frame = Vector(
        tuple(1.0 if index == axis_index else 0.0 for index in range(3))
    )
    up_hint_world = (frame_to_world.to_3x3() @ up_frame).normalized()
    right_world = forward_world.cross(up_hint_world)
    if right_world.length <= 1e-9:
        raise ValueError(f"Assembly sanity view {view['view_id']} has parallel view/up axes")
    right_world.normalize()
    up_world = right_world.cross(forward_world).normalized()
    rotation = Matrix((right_world, up_world, -forward_world)).transposed().to_4x4()
    camera.matrix_world = Matrix.Translation(location_world) @ rotation
    camera.data.clip_start = max(0.001, min(distance * 0.01, radius * 0.1))
    camera.data.clip_end = max(camera.data.clip_start + 1.0, distance + radius * 5.0)
    return target_world


def _pass_record(
    root: Path,
    kind: str,
    path: Path,
    resolution: list[int],
) -> dict[str, Any]:
    """Hash one diagnostic pass and store only its job-relative path."""

    return {
        "kind": kind,
        "path": _job_relative(root, path),
        "sha256": sha256_file(path),
        "width": resolution[0],
        "height": resolution[1],
        "encoding": "png-rgb8",
    }


def _view_output(output_dir: Path, view_id: str, kind: str) -> Path:
    """Return one run-owned pass path for a validated fixed view identifier."""

    if view_id not in VIEW_IDS or kind not in PASS_KINDS:
        raise ValueError(f"unsupported assembly sanity output: {view_id}/{kind}")
    return output_dir / view_id / f"{kind}.png"


def _semantic_object_map() -> dict[str, list[bpy.types.Object]]:
    """Index generated renderable objects by stable semantic identity."""

    result: dict[str, list[bpy.types.Object]] = {}
    for obj in bpy.context.scene.objects:
        semantic_id = obj.get("cbm_id")
        if semantic_id and obj.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
            result.setdefault(str(semantic_id), []).append(obj)
    return result


def _isolate_targets(
    semantic_objects: list[bpy.types.Object],
    target_ids: set[str],
) -> None:
    """Hide semantic context outside the exact assembly target set for this run."""

    for obj in semantic_objects:
        obj.hide_render = str(obj.get("cbm_id", "")) not in target_ids


def main() -> None:
    """Render structural views and write an exact noncanonical diagnostic manifest."""

    args = parse_args()
    root = Path(args.job_root).expanduser().resolve()
    plan_path = _require_contained(root, Path(args.plan), "assembly sanity plan")
    manifest_path = _require_contained(root, Path(args.manifest), "render manifest")
    output_dir = _require_contained(root, Path(args.output_dir), "render output")
    scene_spec_path = _require_contained(root, Path(args.scene_spec), "SceneSpec")
    if sha256_file(plan_path) != args.plan_sha256:
        raise RuntimeError("Assembly sanity plan changed before Blender rendering")
    plan = _load_json_object(plan_path, "Assembly sanity plan")
    if plan.get("canonical_v06_qa_run") is not False:
        raise ValueError("Assembly sanity plan must remain outside canonical V0.6 QA")
    if [view.get("view_id") for view in plan.get("views", [])] != list(VIEW_IDS):
        raise ValueError("Assembly sanity plan requires exact five-view order")
    if plan.get("scene_spec_path") != _job_relative(root, scene_spec_path):
        raise ValueError("Assembly sanity plan SceneSpec path differs from invocation")
    if sha256_file(scene_spec_path) != plan.get("scene_spec_sha256"):
        raise RuntimeError("Assembly sanity SceneSpec changed before Blender rendering")
    modeling_plan_path = _require_contained(
        root,
        root / str(plan["modeling_plan_path"]),
        "ModelingPlan",
    )
    if sha256_file(modeling_plan_path) != plan.get("modeling_plan_sha256"):
        raise RuntimeError("Assembly sanity ModelingPlan changed before Blender rendering")
    blend_path = Path(bpy.data.filepath).expanduser().resolve()
    if _job_relative(root, blend_path) != plan.get("source_blend_path"):
        raise ValueError("Opened Blender file differs from the planned authoring blend")
    source_blend_sha256 = sha256_file(blend_path)
    if source_blend_sha256 != plan.get("source_blend_sha256"):
        raise RuntimeError("Authoring blend changed before assembly sanity rendering")

    configure_artifact_render(args.render_engine, args.render_device)
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    canonical_camera = scene.camera
    if canonical_camera is None:
        raise RuntimeError("Assembly sanity requires a canonical camera for build provenance")
    scene_hash, _camera_hash, build_fingerprint = _validated_build_provenance(
        scene,
        canonical_camera,
        scene_spec_path,
        expected_build_fingerprint=args.build_fingerprint,
        expected_scene_spec_sha256=str(plan["scene_spec_sha256"]),
        expected_camera_fingerprint=None,
    )
    if build_fingerprint != plan.get("build_fingerprint"):
        raise RuntimeError("Assembly sanity plan build fingerprint is stale")

    contract = load_assembly_contract(root)
    if contract["policy"] != "spatial_v1" or contract["frame"] is None:
        raise ValueError("Assembly sanity renderer requires spatial_v1 assembly evidence")
    if contract["sha256"] != plan.get("modeling_plan_sha256"):
        raise RuntimeError("Embedded assembly source differs from the planned ModelingPlan")
    object_map = _semantic_object_map()
    target_ids = [str(value) for value in plan["target_ids"]]
    missing = sorted(set(target_ids) - set(object_map))
    if missing:
        raise RuntimeError(f"Assembly sanity targets are missing from Blender: {missing}")
    selected_objects = [obj for target in target_ids for obj in object_map[target]]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    world_to_frame, frame_error = resolve_assembly_world_to_frame(
        contract["frame"], object_map, depsgraph
    )
    if frame_error is not None or world_to_frame is None:
        raise RuntimeError(f"Assembly sanity frame cannot be resolved: {frame_error}")
    frame_to_world = world_to_frame.inverted()
    frame_bounds = evaluated_bounds_in_frame(selected_objects, world_to_frame, depsgraph)
    target_frame = Vector(
        tuple(
            (float(frame_bounds["min"][axis]) + float(frame_bounds["max"][axis])) * 0.5
            for axis in range(3)
        )
    )
    dimensions = [
        float(frame_bounds["max"][axis]) - float(frame_bounds["min"][axis])
        for axis in range(3)
    ]
    radius = max(0.05, math.sqrt(sum(value * value for value in dimensions)) * 0.5)
    distance = max(0.25, radius * 3.25)
    assembly_evaluation = evaluate_assembly_relationships(contract, object_map)

    width, height = [int(value) for value in plan["resolution"]]
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    resolution = [width, height]
    warnings: list[str] = []
    semantic_objects = [obj for values in object_map.values() for obj in values]
    target_set = set(target_ids)
    _isolate_targets(semantic_objects, target_set)
    object_colors = unique_color_map(target_ids)
    camera = _temporary_camera(scene)
    scene.camera = camera
    records_by_view: dict[str, list[dict[str, Any]]] = {
        str(view["view_id"]): [] for view in plan["views"]
    }
    cameras: dict[str, dict[str, Any]] = {}

    for view in plan["views"]:
        view_id = str(view["view_id"])
        target_world = _apply_view(
            camera,
            view,
            assembly_frame=contract["frame"],
            target_frame=target_frame,
            distance=distance,
            radius=radius,
            frame_to_world=frame_to_world,
        )
        cameras[view_id] = _camera_record(camera, target_world, view)
        path = _view_output(output_dir, view_id, "beauty")
        _render_pass(scene, view_layer, path, None)
        records_by_view[view_id].append(
            _pass_record(root, "beauty", path, resolution)
        )

    _set_black_world(scene)
    _set_machine_color_management(scene, warnings)
    overrides = {
        "silhouette": _flat_material(
            "CBM_AssemblySanity_Silhouette",
            (1.0, 1.0, 1.0, 1.0),
        ),
        "object_id": _object_color_material("CBM_AssemblySanity_ObjectID"),
        "wireframe": _wireframe_material(),
    }
    for kind in PASS_KINDS[1:]:
        if kind == "object_id":
            for obj in selected_objects:
                obj.color = (*object_colors[str(obj.get("cbm_id", ""))], 1.0)
        for view in plan["views"]:
            view_id = str(view["view_id"])
            _apply_view(
                camera,
                view,
                assembly_frame=contract["frame"],
                target_frame=target_frame,
                distance=distance,
                radius=radius,
                frame_to_world=frame_to_world,
            )
            path = _view_output(output_dir, view_id, kind)
            _render_pass(scene, view_layer, path, overrides[kind])
            records_by_view[view_id].append(
                _pass_record(root, kind, path, resolution)
            )

    rendered_views = [
        {
            "view_id": view_id,
            "camera": cameras[view_id],
            "target_ids": target_ids,
            "passes": records_by_view[view_id],
        }
        for view_id in VIEW_IDS
    ]
    manifest = {
        "schema_version": "0.6.0",
        "diagnostic_kind": "assembly_multiview_sanity",
        "canonical_v06_qa_run": False,
        "job_id": str(scene.get("cbm_job_id") or "__unknown__"),
        "run_id": plan["run_id"],
        "plan_sha256": args.plan_sha256,
        "scene_spec_sha256": scene_hash,
        "modeling_plan_sha256": plan["modeling_plan_sha256"],
        "source_blend_path": plan["source_blend_path"],
        "source_blend_sha256": source_blend_sha256,
        "build_fingerprint": build_fingerprint,
        "blender_version": bpy.app.version_string,
        "render_engine": scene.get("cbm_render_engine", scene.render.engine),
        "render_device": scene.get("cbm_render_device", "DEFAULT"),
        "resolution": resolution,
        "object_id_colors": {
            identifier: _display_hex(color) for identifier, color in object_colors.items()
        },
        "assembly_frame_bounds": frame_bounds,
        "assembly_evaluation": assembly_evaluation,
        "views": rendered_views,
        "warnings": warnings,
    }
    write_json_atomic(manifest_path, manifest)
    if sha256_file(blend_path) != source_blend_sha256:
        raise RuntimeError("Assembly sanity rendering changed the authoring blend on disk")
    print(
        "CBM_ASSEMBLY_SANITY_RENDER_OK "
        f"views={len(rendered_views)} passes={len(rendered_views) * len(PASS_KINDS)}"
    )


if __name__ == "__main__":
    main()
