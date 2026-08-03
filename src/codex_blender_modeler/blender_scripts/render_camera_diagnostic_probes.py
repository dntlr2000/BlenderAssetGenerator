"""Render bounded comparison-camera probes without saving the authoring blend."""

from __future__ import annotations

import argparse
import json
import math
import re
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
from render_qa_passes import (  # noqa: E402
    _camera_record,
    _display_hex,
    _flat_material,
    _object_color_material,
    _render_pass,
    _set_black_world,
    _set_machine_color_management,
    _validated_build_provenance,
)

from codex_blender_modeler.blender_artifacts import (  # noqa: E402
    sha256_file,
    unique_color_map,
    write_json_atomic,
)

_SAFE_PROBE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_NONBASELINE_PROBES = 12
_PRIMARY_MASK_SOURCES = {
    "canonical_primary_object_reference",
    "semantic_primary_supporting_union",
}


def parse_args() -> argparse.Namespace:
    """Parse exact source bindings and bounded diagnostic render arguments."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--probe-plan", required=True)
    parser.add_argument("--probe-plan-sha256", required=True)
    parser.add_argument("--role-map", required=True)
    parser.add_argument("--role-map-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--scene-spec", required=True)
    parser.add_argument("--build-fingerprint", required=True)
    parser.add_argument("--scene-spec-sha256", required=True)
    parser.add_argument("--camera-fingerprint", required=True)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--render-engine", choices=("eevee", "cycles"), default="eevee")
    parser.add_argument("--render-device", choices=("auto", "cpu", "gpu"), default="auto")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    """Load one required JSON object and reject malformed probe evidence."""

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
    """Resolve one diagnostic path and require containment by the owning job."""

    resolved_root = root.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} is outside the owning job: {resolved}") from exc
    return resolved


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one contained diagnostic artifact as a portable relative path."""

    return _require_contained(root, path, "camera probe artifact").relative_to(
        root.resolve()
    ).as_posix()


def _bounded_resolution(scene: bpy.types.Scene, maximum: int) -> tuple[int, int]:
    """Fit the canonical camera aspect ratio into one low-resolution probe frame."""

    if maximum < 64 or maximum > 512:
        raise ValueError("camera probe resolution must be within [64, 512]")
    width = int(scene.render.resolution_x)
    height = int(scene.render.resolution_y)
    scale = min(1.0, maximum / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def _role_targets(role_map: dict[str, Any]) -> list[str]:
    """Select primary and supporting semantic IDs while excluding environment context."""

    assignments = role_map.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("camera probe role map has no assignments")
    targets = sorted(
        {
            str(item["object_id"])
            for item in assignments
            if isinstance(item, dict)
            and item.get("role") in {"primary", "supporting"}
            and item.get("object_id")
        }
    )
    if not targets:
        raise ValueError("camera probe role map has no primary/supporting targets")
    return targets


def _validated_camera_delta(value: Any) -> dict[str, Any]:
    """Normalize one finite bounded delta without relying on host-only Pydantic."""

    if not isinstance(value, dict):
        raise ValueError("camera probe delta must be a JSON object")
    allowed = {
        "target_offset_norm",
        "distance_scale",
        "projection_scale",
        "rotation_delta_deg",
    }
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ValueError(f"camera probe delta has unsupported fields: {unexpected}")
    target_offset = [float(item) for item in value.get("target_offset_norm", [0, 0])]
    rotations = [float(item) for item in value.get("rotation_delta_deg", [0, 0, 0])]
    distance_scale = float(value.get("distance_scale", 1.0))
    projection_scale = float(value.get("projection_scale", 1.0))
    numbers = [*target_offset, *rotations, distance_scale, projection_scale]
    if not all(math.isfinite(item) for item in numbers):
        raise ValueError("camera probe delta values must be finite")
    if len(target_offset) != 2 or any(abs(item) > 0.25 for item in target_offset):
        raise ValueError("camera target offsets must be two values within +/-0.25")
    if len(rotations) != 3 or any(abs(item) > 15.0 for item in rotations):
        raise ValueError("camera rotations must be three values within +/-15 degrees")
    if not 0.5 <= distance_scale <= 2.0 or not 0.5 <= projection_scale <= 2.0:
        raise ValueError("camera probe scale values must be within [0.5, 2.0]")
    return {
        "target_offset_norm": target_offset,
        "distance_scale": distance_scale,
        "projection_scale": projection_scale,
        "rotation_delta_deg": rotations,
    }


def _validated_probe_entries(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Require one neutral baseline and at most twelve exact bounded probes."""

    raw_probes = plan.get("probes")
    if not isinstance(raw_probes, list) or len(raw_probes) < 2:
        raise ValueError("camera probe plan requires baseline plus a bounded probe")
    if len(raw_probes) > _MAX_NONBASELINE_PROBES + 1:
        raise ValueError("camera probe plan exceeds the bounded probe limit")
    probes: list[dict[str, Any]] = []
    probe_ids: list[str] = []
    for raw_probe in raw_probes:
        if not isinstance(raw_probe, dict):
            raise ValueError("camera probe entries must be JSON objects")
        probe_id = str(raw_probe.get("probe_id", ""))
        if not _SAFE_PROBE_ID.fullmatch(probe_id):
            raise ValueError(f"unsafe camera probe ID: {probe_id}")
        probe_ids.append(probe_id)
        probes.append(
            {
                "probe_id": probe_id,
                "camera_delta": _validated_camera_delta(raw_probe.get("camera_delta", {})),
            }
        )
    if len(probe_ids) != len(set(probe_ids)):
        raise ValueError("camera probe IDs must be unique")
    baseline = probes[0]
    neutral = {
        "target_offset_norm": [0.0, 0.0],
        "distance_scale": 1.0,
        "projection_scale": 1.0,
        "rotation_delta_deg": [0.0, 0.0, 0.0],
    }
    if baseline["probe_id"] != "baseline" or baseline["camera_delta"] != neutral:
        raise ValueError("the first camera probe must be the neutral baseline")
    return probes


def _validated_primary_reference_mask(
    root: Path,
    plan: dict[str, Any],
) -> dict[str, str] | None:
    """Verify and normalize the optional exact primary-subject mask plan binding."""

    raw = plan.get("primary_reference_mask")
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != {"path", "sha256", "source"}:
        raise ValueError("primary reference mask binding is malformed")
    relative_path = raw.get("path")
    expected_sha256 = raw.get("sha256")
    source = raw.get("source")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("primary reference mask path is invalid")
    if not _SHA256.fullmatch(str(expected_sha256)):
        raise ValueError("primary reference mask hash is invalid")
    if source not in _PRIMARY_MASK_SOURCES:
        raise ValueError("primary reference mask source is unsupported")
    path = _require_contained(root, root / relative_path, "primary reference mask")
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise RuntimeError("primary reference mask is missing or changed")
    return {
        "path": _job_relative(root, path),
        "sha256": str(expected_sha256),
        "source": str(source),
    }


def _validate_plan_bindings(
    plan: dict[str, Any],
    role_map: dict[str, Any],
    *,
    scene_job_id: str,
    probe_plan_sha256: str,
    role_map_sha256: str,
    scene_spec_sha256: str,
    camera_fingerprint: str,
) -> None:
    """Bind a noncanonical probe plan and role map to exact render inputs."""

    expected = (
        plan.get("schema_version") == "0.6.0"
        and plan.get("diagnostic_kind") == "bounded_camera_probe"
        and plan.get("canonical_v06_qa_run") is False
        and plan.get("job_id") == scene_job_id
        and plan.get("scene_spec_sha256") == scene_spec_sha256
        and plan.get("camera_fingerprint") == camera_fingerprint
        and plan.get("role_map_sha256") == role_map_sha256
        and role_map.get("job_id") == scene_job_id
        and role_map.get("scene_spec_sha256") == scene_spec_sha256
    )
    if not expected:
        raise RuntimeError("camera probe plan or role map is not bound to current inputs")
    if not probe_plan_sha256 or not role_map_sha256:
        raise RuntimeError("camera probe inputs require exact SHA-256 bindings")


def _semantic_objects() -> dict[str, list[bpy.types.Object]]:
    """Index visible renderable objects by their stable semantic identity."""

    result: dict[str, list[bpy.types.Object]] = {}
    for item in bpy.context.scene.objects:
        identifier = item.get("cbm_id")
        if identifier and item.type in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
            result.setdefault(str(identifier), []).append(item)
    return result


def _apply_probe(
    camera: bpy.types.Object,
    canonical: dict[str, Any],
    delta: dict[str, Any],
) -> None:
    """Apply one bounded orbit/framing delta around the canonical camera target."""

    original_location = Vector(tuple(float(value) for value in canonical["location"]))
    target = Vector(tuple(float(value) for value in canonical["target"]))
    offset = original_location - target
    if offset.length <= 1e-9:
        raise ValueError("canonical camera location and target must differ")
    target_offsets = [
        float(value) for value in delta.get("target_offset_norm", [0, 0])
    ]
    rotations = [float(value) for value in delta.get("rotation_delta_deg", [0, 0, 0])]
    distance_scale = float(delta.get("distance_scale", 1.0))
    projection_scale = float(delta.get("projection_scale", 1.0))
    numeric_values = [*target_offsets, *rotations, distance_scale, projection_scale]
    if not all(math.isfinite(value) for value in numeric_values):
        raise ValueError("camera probe values must be finite")
    if len(target_offsets) != 2 or any(abs(value) > 0.25 for value in target_offsets):
        raise ValueError("camera target offsets must be two values within +/-0.25")
    if len(rotations) != 3 or any(abs(value) > 15.0 for value in rotations):
        raise ValueError("camera probe rotations must be three values within +/-15 degrees")
    original_distance = offset.length
    canonical_forward = (-offset).normalized()
    canonical_right = canonical_forward.cross(Vector((0.0, 0.0, 1.0)))
    if canonical_right.length <= 1e-9:
        canonical_right = Vector((1.0, 0.0, 0.0))
    else:
        canonical_right.normalize()
    canonical_up = canonical_right.cross(canonical_forward).normalized()
    target += (
        canonical_right * target_offsets[0] * original_distance
        + canonical_up * target_offsets[1] * original_distance
    )
    offset = original_location - target
    yaw = Matrix.Rotation(math.radians(rotations[0]), 4, "Z")
    offset = yaw @ offset
    forward = (-offset).normalized()
    right = forward.cross(Vector((0.0, 0.0, 1.0)))
    if right.length <= 1e-9:
        right = Vector((1.0, 0.0, 0.0))
    else:
        right.normalize()
    pitch = Matrix.Rotation(math.radians(rotations[1]), 4, right)
    offset = pitch @ offset
    if not 0.5 <= distance_scale <= 2.0 or not 0.5 <= projection_scale <= 2.0:
        raise ValueError("camera probe scale values must be within [0.5, 2.0]")
    offset *= distance_scale
    location = target + offset
    view = target - location
    camera.location = location
    camera.rotation_euler = view.to_track_quat("-Z", "Y").to_euler()
    if abs(rotations[2]) > 1e-9:
        camera.rotation_euler.rotate_axis("Z", math.radians(rotations[2]))
    camera.data.type = str(canonical["projection"])
    camera.data.lens = float(canonical["focal_length_mm"])
    camera.data.ortho_scale = float(canonical["ortho_scale"])
    if camera.data.type == "ORTHO":
        camera.data.ortho_scale *= projection_scale
    else:
        camera.data.lens /= projection_scale


def _pass_record(
    root: Path,
    kind: str,
    path: Path,
    resolution: tuple[int, int],
) -> dict[str, Any]:
    """Hash one probe render and serialize its job-relative artifact path."""

    return {
        "kind": kind,
        "path": _job_relative(root, path),
        "sha256": sha256_file(path),
        "width": resolution[0],
        "height": resolution[1],
        "encoding": "png-rgb8",
    }


def main() -> None:
    """Render all bounded probes in one Blender process without saving source changes."""

    args = parse_args()
    root = Path(args.job_root).expanduser().resolve()
    plan_path = _require_contained(root, Path(args.probe_plan), "camera probe plan")
    role_map_path = _require_contained(root, Path(args.role_map), "camera probe role map")
    output_dir = _require_contained(root, Path(args.output_dir), "camera probe output")
    manifest_path = _require_contained(root, Path(args.manifest), "camera probe manifest")
    scene_spec_path = _require_contained(root, Path(args.scene_spec), "SceneSpec")
    probe_root = plan_path.parent.resolve()
    try:
        output_dir.relative_to(probe_root)
        manifest_path.relative_to(probe_root)
    except ValueError as exc:
        raise ValueError(
            "camera probe outputs must remain inside the probe-plan directory"
        ) from exc
    protected_paths = {
        plan_path,
        role_map_path,
        scene_spec_path,
        Path(bpy.data.filepath).expanduser().resolve(),
    }
    if manifest_path in protected_paths or output_dir in protected_paths:
        raise ValueError("camera probe outputs must not overwrite source evidence")
    if sha256_file(plan_path) != args.probe_plan_sha256:
        raise RuntimeError("camera probe plan changed before rendering")
    if sha256_file(role_map_path) != args.role_map_sha256:
        raise RuntimeError("camera probe role map changed before rendering")
    plan = _load_json_object(plan_path, "Camera probe plan")
    role_map = _load_json_object(role_map_path, "Camera probe role map")
    canonical = _load_json_object(scene_spec_path, "SceneSpec")["camera"]
    configure_artifact_render(args.render_engine, args.render_device)
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("camera diagnostics require the canonical comparison camera")
    scene_hash, camera_hash, build_hash = _validated_build_provenance(
        scene,
        scene.camera,
        scene_spec_path,
        expected_build_fingerprint=args.build_fingerprint,
        expected_scene_spec_sha256=args.scene_spec_sha256,
        expected_camera_fingerprint=args.camera_fingerprint,
    )
    _validate_plan_bindings(
        plan,
        role_map,
        scene_job_id=str(scene.get("cbm_job_id") or "__unknown__"),
        probe_plan_sha256=args.probe_plan_sha256,
        role_map_sha256=args.role_map_sha256,
        scene_spec_sha256=scene_hash,
        camera_fingerprint=camera_hash,
    )
    primary_reference_mask = _validated_primary_reference_mask(root, plan)
    blend_path = Path(bpy.data.filepath).expanduser().resolve()
    blend_hash = sha256_file(blend_path)
    targets = _role_targets(role_map)
    semantic_map = _semantic_objects()
    missing = sorted(set(targets) - set(semantic_map))
    if missing:
        raise RuntimeError(f"camera probe targets are absent from Blender scene: {missing}")
    target_set = set(targets)
    selected = [item for identifier in targets for item in semantic_map[identifier]]
    for objects in semantic_map.values():
        for item in objects:
            item.hide_render = str(item.get("cbm_id", "")) not in target_set
    width, height = _bounded_resolution(scene, int(args.resolution))
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    warnings: list[str] = []
    _set_black_world(scene)
    _set_machine_color_management(scene, warnings)
    silhouette_material = _flat_material(
        "CBM_CameraDiagnostic_Silhouette",
        (1.0, 1.0, 1.0, 1.0),
    )
    object_id_material = _object_color_material("CBM_CameraDiagnostic_ObjectID")
    colors = unique_color_map(targets)
    for item in selected:
        item.color = (*colors[str(item.get("cbm_id", ""))], 1.0)
    probes = _validated_probe_entries(plan)
    records: list[dict[str, Any]] = []
    for probe in probes:
        probe_id = str(probe["probe_id"])
        _apply_probe(scene.camera, canonical, dict(probe.get("camera_delta", {})))
        probe_dir = output_dir / probe_id
        silhouette_path = probe_dir / "silhouette.png"
        object_id_path = probe_dir / "object_id.png"
        _render_pass(scene, bpy.context.view_layer, silhouette_path, silhouette_material)
        _render_pass(scene, bpy.context.view_layer, object_id_path, object_id_material)
        records.append(
            {
                "probe_id": probe_id,
                "camera_delta": probe.get("camera_delta", {}),
                "camera": _camera_record(scene.camera),
                "passes": [
                    _pass_record(root, "silhouette", silhouette_path, (width, height)),
                    _pass_record(root, "object_id", object_id_path, (width, height)),
                ],
            }
        )
    bpy.context.view_layer.material_override = None
    manifest = {
        "schema_version": "0.6.0",
        "diagnostic_kind": "bounded_camera_probe",
        "canonical_v06_qa_run": False,
        "job_id": str(scene.get("cbm_job_id") or "__unknown__"),
        "qa_run_id": plan.get("qa_run_id"),
        "diagnostic_id": plan.get("diagnostic_id"),
        "probe_plan_sha256": args.probe_plan_sha256,
        "role_map_sha256": args.role_map_sha256,
        "scene_spec_sha256": scene_hash,
        "camera_fingerprint": camera_hash,
        "build_fingerprint": build_hash,
        "source_blend_sha256": blend_hash,
        "resolution": [width, height],
        "target_ids": targets,
        "object_id_colors": {
            identifier: _display_hex(color) for identifier, color in colors.items()
        },
        "primary_reference_mask": primary_reference_mask,
        "probes": records,
        "warnings": warnings,
    }
    write_json_atomic(manifest_path, manifest)
    if sha256_file(blend_path) != blend_hash:
        raise RuntimeError("camera probe rendering changed the authoring blend on disk")
    print(f"CBM_CAMERA_DIAGNOSTIC_OK probes={len(records)} targets={len(targets)}")


if __name__ == "__main__":
    main()
