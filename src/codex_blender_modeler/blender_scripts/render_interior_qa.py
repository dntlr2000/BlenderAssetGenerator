"""Render approved temporary interior cameras without saving the authoring blend."""

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
from render_qa_passes import (  # noqa: E402
    PASS_KINDS,
    _depth_material,
    _display_hex,
    _flat_material,
    _material_id_for_object,
    _normal_material,
    _object_color_material,
    _pass_record,
    _render_pass,
    _set_black_world,
    _set_machine_color_management,
    _validated_build_provenance,
    _visible_depth_range,
    _wireframe_material,
)

from codex_blender_modeler.blender_artifacts import (  # noqa: E402
    sha256_file,
    unique_color_map,
    write_json_atomic,
)


def parse_args() -> argparse.Namespace:
    """Parse an exact approved plan and Blender rendering configuration."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scene-spec", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--scope-approval", required=True)
    parser.add_argument("--render-engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load one required JSON object used as immutable Blender-render evidence."""

    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _require_hash(path: Path, expected: str, label: str) -> None:
    """Reject any changed plan, approval, scope, or source contract."""

    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} hash changed: expected={expected} actual={actual}")


def _temporary_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    """Create one run-local camera datablock that is never saved to the source blend."""

    camera_data = bpy.data.cameras.new("CBM_InteriorQA_CameraData")
    camera = bpy.data.objects.new("CBM_InteriorQA_Camera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = "PERSP"
    return camera


def _apply_view(camera: bpy.types.Object, view: dict[str, Any]) -> None:
    """Apply one approved plan view to the temporary Blender camera."""

    location = Vector(tuple(float(value) for value in view["location"]))
    target = Vector(tuple(float(value) for value in view["target"]))
    direction = target - location
    if direction.length <= 1e-9:
        raise ValueError(f"Interior QA view {view['view_id']} has an empty direction")
    camera.location = location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = float(view["focal_length_mm"])
    camera.data.clip_start = float(view["clip_start_m"])
    camera.data.clip_end = float(view["clip_end_m"])


def _camera_record(camera: bpy.types.Object, view: dict[str, Any]) -> dict[str, Any]:
    """Serialize the actual temporary camera used by one interior view."""

    return {
        "name": camera.name,
        "type": camera.data.type,
        "location": [round(float(value), 9) for value in camera.location],
        "rotation_deg": [
            round(math.degrees(float(value)), 9) for value in camera.rotation_euler
        ],
        "target": [round(float(value), 9) for value in view["target"]],
        "lens_mm": float(camera.data.lens),
        "clip_start": float(camera.data.clip_start),
        "clip_end": float(camera.data.clip_end),
    }


def _isolate_view_objects(
    semantic_objects: list[bpy.types.Object],
    target_ids: set[str],
) -> None:
    """Hide every renderable semantic object outside the approved interior view."""

    for obj in semantic_objects:
        obj.hide_render = str(obj.get("cbm_id", "")) not in target_ids


def _view_output(output_dir: Path, view_id: str, kind: str) -> Path:
    """Return one contained per-view pass path from validated portable identifiers."""

    return output_dir / "views" / view_id / f"{kind}.png"


def main() -> None:
    """Render beauty first, then six machine passes for every approved interior view."""

    args = parse_args()
    plan_path = Path(args.plan).expanduser().resolve()
    approval_path = Path(args.approval).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    scene_spec_path = Path(args.scene_spec).expanduser().resolve()
    scope_path = Path(args.scope).expanduser().resolve()
    scope_approval_path = Path(args.scope_approval).expanduser().resolve()
    _require_hash(plan_path, args.plan_sha256, "Interior QA plan")
    _require_hash(approval_path, args.approval_sha256, "Interior QA approval")
    plan = _load_json_object(plan_path, "Interior QA plan")
    approval = _load_json_object(approval_path, "Interior QA approval")
    if approval.get("status") != "consumed":
        raise PermissionError("Interior QA renderer requires a consumed single-use approval")
    if approval.get("plan_sha256") != args.plan_sha256:
        raise ValueError("Interior QA approval is not bound to the selected plan")
    if approval.get("source_fingerprint") != plan.get("source_fingerprint"):
        raise ValueError("Interior QA approval source fingerprint differs from the plan")
    _require_hash(
        scope_path,
        str(plan["interior_scope_sha256"]),
        "InteriorScope",
    )
    _require_hash(
        scope_approval_path,
        str(plan["interior_scope_approval_sha256"]),
        "InteriorScope approval",
    )

    approved_view_ids = set(str(value) for value in approval["approved_view_ids"])
    views = [
        view
        for view in plan.get("views", [])
        if str(view.get("view_id")) in approved_view_ids
    ]
    if {str(view["view_id"]) for view in views} != approved_view_ids:
        raise ValueError("Interior QA approval references unknown plan view IDs")
    if not views:
        raise ValueError("Interior QA approval selected no views")

    configure_artifact_render(args.render_engine, args.render_device)
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    if scene.camera is None:
        raise RuntimeError("Interior QA requires the canonical comparison camera for provenance")
    scene_hash, _camera_hash, build_fingerprint = _validated_build_provenance(
        scene,
        scene.camera,
        scene_spec_path,
        expected_build_fingerprint=args.build_fingerprint,
        expected_scene_spec_sha256=str(plan["scene_spec_sha256"]),
        expected_camera_fingerprint=None,
    )
    if build_fingerprint != plan["build_fingerprint"]:
        raise RuntimeError("Interior QA plan build fingerprint is stale")

    width, height = [int(value) for value in plan["resolution"]]
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    resolution = [width, height]
    warnings: list[str] = []
    semantic_objects = [
        obj
        for obj in sorted(scene.objects, key=lambda item: item.name)
        if obj.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}
    ]
    plan_target_ids = sorted(set(str(value) for value in plan["target_ids"]))
    object_colors = unique_color_map(plan_target_ids)
    selected_objects = [
        obj
        for obj in semantic_objects
        if str(obj.get("cbm_id", "")) in set(plan_target_ids)
    ]
    material_ids_by_object = {
        obj.name: _material_id_for_object(obj, warnings) for obj in selected_objects
    }
    material_colors = unique_color_map(list(material_ids_by_object.values()))
    camera = _temporary_camera(scene)
    scene.camera = camera
    records_by_view: dict[str, list[dict[str, Any]]] = {
        str(view["view_id"]): [] for view in views
    }
    camera_by_view: dict[str, dict[str, Any]] = {}
    depth_by_view: dict[str, tuple[float, float]] = {}

    for view in views:
        view_id = str(view["view_id"])
        target_ids = set(str(value) for value in view["target_ids"])
        _apply_view(camera, view)
        _isolate_view_objects(semantic_objects, target_ids)
        visible_objects = [
            obj
            for obj in semantic_objects
            if not obj.hide_render and str(obj.get("cbm_id", "")) in target_ids
        ]
        if not visible_objects:
            raise RuntimeError(f"Interior QA view has no renderable objects: {view_id}")
        depth_by_view[view_id] = _visible_depth_range(camera, visible_objects)
        camera_by_view[view_id] = _camera_record(camera, view)
        beauty_path = _view_output(output_dir, view_id, "beauty")
        _render_pass(scene, view_layer, beauty_path, None)
        records_by_view[view_id].append(
            _pass_record("beauty", beauty_path, manifest_path, resolution)
        )

    _set_black_world(scene)
    _set_machine_color_management(scene, warnings)
    static_overrides = {
        "silhouette": _flat_material(
            "CBM_InteriorQA_Silhouette",
            (1.0, 1.0, 1.0, 1.0),
        ),
        "object_id": _object_color_material("CBM_InteriorQA_ObjectID"),
        "material_id": _object_color_material("CBM_InteriorQA_MaterialID"),
        "normal": _normal_material(),
        "wireframe": _wireframe_material(),
    }
    for kind in PASS_KINDS[1:]:
        if kind == "object_id":
            for obj in selected_objects:
                color = object_colors[str(obj.get("cbm_id", ""))]
                obj.color = (*color, 1.0)
        elif kind == "material_id":
            for obj in selected_objects:
                color = material_colors[material_ids_by_object[obj.name]]
                obj.color = (*color, 1.0)
        for view in views:
            view_id = str(view["view_id"])
            target_ids = set(str(value) for value in view["target_ids"])
            _apply_view(camera, view)
            _isolate_view_objects(semantic_objects, target_ids)
            override = (
                _depth_material(*depth_by_view[view_id])
                if kind == "depth"
                else static_overrides[kind]
            )
            path = _view_output(output_dir, view_id, kind)
            _render_pass(scene, view_layer, path, override)
            records_by_view[view_id].append(
                _pass_record(kind, path, manifest_path, resolution)
            )

    view_layer.material_override = None
    rendered_views = []
    for view in views:
        view_id = str(view["view_id"])
        near, far = depth_by_view[view_id]
        rendered_views.append(
            {
                "view_id": view_id,
                "level_id": view.get("level_id"),
                "space_id": view.get("space_id"),
                "camera": camera_by_view[view_id],
                "target_ids": view["target_ids"],
                "depth_range": {"near": near, "far": far},
                "passes": records_by_view[view_id],
            }
        )
    manifest = {
        "schema_version": "0.6.0",
        "job_id": str(scene.get("cbm_job_id") or "__unknown__"),
        "run_id": plan["run_id"],
        "plan_sha256": args.plan_sha256,
        "plan_approval_sha256": args.approval_sha256,
        "scene_spec_sha256": scene_hash,
        "build_fingerprint": build_fingerprint,
        "interior_scope_sha256": plan["interior_scope_sha256"],
        "interior_scope_approval_sha256": plan[
            "interior_scope_approval_sha256"
        ],
        "blender_version": bpy.app.version_string,
        "render_engine": scene.get("cbm_render_engine", scene.render.engine),
        "render_device": scene.get("cbm_render_device", "DEFAULT"),
        "resolution": resolution,
        "object_id_colors": {
            identifier: _display_hex(color) for identifier, color in object_colors.items()
        },
        "material_id_colors": {
            identifier: _display_hex(color) for identifier, color in material_colors.items()
        },
        "views": rendered_views,
        "warnings": warnings,
    }
    write_json_atomic(manifest_path, manifest)
    print(
        "CBM_INTERIOR_QA_RENDER_OK "
        f"views={len(rendered_views)} passes={len(rendered_views) * len(PASS_KINDS)}"
    )


if __name__ == "__main__":
    main()
