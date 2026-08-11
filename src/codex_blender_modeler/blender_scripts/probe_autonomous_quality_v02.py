"""Render one fixed, hash-bound AQ 0.2 synthetic benchmark case in Blender 5."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

_CASE_FIELDS = {
    "case_id",
    "category",
    "seed",
    "contract_sha256",
    "known_camera",
    "reference_recipe",
    "stages",
    "expected_metric_directions",
    "blender_smoke_supported",
    "claim_scope",
}


def _parse_args() -> argparse.Namespace:
    """Parse only the fixed case and contained output paths accepted by this probe."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--case-contract", required=True)
    parser.add_argument("--case-contract-file-sha256", required=True)
    parser.add_argument("--blend-output", required=True)
    parser.add_argument("--render-output", required=True)
    parser.add_argument("--receipt-output", required=True)
    parser.add_argument("--camera-sha256", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _file_sha256(path: Path) -> str:
    """Return the exact SHA-256 of one probe input or output file."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    """Hash one JSON-compatible value with the host benchmark canonical encoding."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _contained_path(root: Path, relative: str) -> Path:
    """Resolve one normalized relative output while rejecting every path escape."""

    if not relative or "\\" in relative or ":" in relative or relative.startswith("/"):
        raise ValueError("probe paths must be normalized POSIX relative paths")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("probe paths cannot contain empty, current, or parent segments")
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("probe path escapes the output root") from exc
    return candidate


def _read_case(path: Path, expected_file_sha256: str, camera_sha256: str) -> dict[str, Any]:
    """Load and verify the exact host-validated case before touching Blender state."""

    if _file_sha256(path) != expected_file_sha256:
        raise ValueError("case contract file SHA-256 does not match the fixed request")
    case = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(case, dict) or set(case) != _CASE_FIELDS:
        raise ValueError("case contract does not use the fixed AQ 0.2 field set")
    contract_payload = dict(case)
    declared_contract_sha256 = contract_payload.pop("contract_sha256", None)
    if _canonical_sha256(contract_payload) != declared_contract_sha256:
        raise ValueError("case canonical contract SHA-256 does not match")
    if _canonical_sha256(case["known_camera"]) != camera_sha256:
        raise ValueError("known camera SHA-256 does not match the fixed request")
    if case.get("blender_smoke_supported") is not True:
        raise ValueError("case did not explicitly opt in to the fixed Blender smoke")
    return case


def _reset_scene() -> None:
    """Remove factory-startup scene objects before creating bounded fixtures."""

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _feature_probe_render_engine(scene: bpy.types.Scene) -> None:
    """Select the supported Eevee identifier in the repository-required order."""

    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = engine
        except TypeError:
            continue
        if scene.render.engine == engine:
            return
    raise RuntimeError("Blender does not expose a supported Eevee render engine")


def _material(name: str, color_rgb: list[int]) -> bpy.types.Material:
    """Create one bounded Principled material from the fixture's declared RGB bytes."""

    material = bpy.data.materials.new(name=name)
    material.diffuse_color = tuple(component / 255.0 for component in color_rgb) + (1.0,)
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is None:
        raise RuntimeError("Blender did not create the expected Principled BSDF node")
    principled.inputs["Base Color"].default_value = material.diffuse_color
    principled.inputs["Roughness"].default_value = 0.55
    return material


def _primitive_object(
    primitive: dict[str, Any],
    *,
    width: int,
    height: int,
) -> bpy.types.Object:
    """Create one cube or ellipsoid from the fixed rectangle/ellipse whitelist."""

    required = {
        "primitive_id",
        "semantic_id",
        "qa_role",
        "critical",
        "shape",
        "bbox_px",
        "object_id",
        "color_rgb",
    }
    if set(primitive) != required:
        raise ValueError("synthetic primitive does not use the fixed field set")
    x0, y0, x1, y1 = primitive["bbox_px"]
    world_width = (x1 - x0) / width * 4.0
    world_height = (y1 - y0) / height * 4.0
    center_x = ((x0 + x1) / (2.0 * width) - 0.5) * 4.0
    center_z = (0.5 - (y0 + y1) / (2.0 * height)) * 4.0
    if primitive["shape"] == "rectangle":
        bpy.ops.mesh.primitive_cube_add(location=(center_x, 0.0, center_z))
        obj = bpy.context.object
        obj.dimensions = (world_width, 0.35, world_height)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    elif primitive["shape"] == "ellipse":
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=24,
            ring_count=12,
            location=(center_x, 0.0, center_z),
        )
        obj = bpy.context.object
        obj.scale = (world_width / 2.0, 0.22, world_height / 2.0)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    else:
        raise ValueError("Blender probe supports only rectangle and ellipse fixtures")
    obj.name = primitive["semantic_id"]
    obj.data.materials.append(_material(f"mat.{primitive['semantic_id']}", primitive["color_rgb"]))
    obj["cbm_semantic_id"] = primitive["semantic_id"]
    obj["cbm_qa_role"] = primitive["qa_role"]
    return obj


def _camera(case: dict[str, Any], expected_sha256: str) -> bpy.types.Object:
    """Create the exact known camera and orient it toward its declared target."""

    camera_contract = case["known_camera"]
    camera_data = bpy.data.cameras.new("AQ_V02_KnownCamera")
    camera = bpy.data.objects.new("AQ_V02_KnownCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = camera_contract["location_m"]
    target = Vector(camera_contract["target_m"])
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    if camera_contract["projection"] == "orthographic":
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = camera_contract["ortho_scale_m"]
    else:
        camera_data.type = "PERSP"
        camera_data.lens = camera_contract["focal_length_mm"]
    camera["cbm_known_camera_sha256"] = expected_sha256
    return camera


def _configure_scene(case: dict[str, Any], camera_sha256: str, render_path: Path) -> int:
    """Build the reference fixture, known camera, lights, and deterministic render settings."""

    scene = bpy.context.scene
    _feature_probe_render_engine(scene)
    width, height = case["known_camera"]["resolution_px"]
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.filepath = str(render_path)
    scene.render.film_transparent = False
    scene.world.color = tuple(
        value / 255.0 for value in case["reference_recipe"]["background_rgb"]
    )
    objects = [
        _primitive_object(primitive, width=width, height=height)
        for primitive in case["reference_recipe"]["primitives"]
    ]
    camera = _camera(case, camera_sha256)
    scene.camera = camera
    bpy.ops.object.light_add(type="AREA", location=(2.5, -3.5, 5.0))
    key = bpy.context.object
    key.name = "AQ_V02_Key"
    key.data.energy = 900.0
    key.data.shape = "DISK"
    key.data.size = 5.0
    key.rotation_euler = (
        Vector((0.0, 0.0, 0.0)) - key.location
    ).to_track_quat("-Z", "Y").to_euler()
    return len(objects)


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Write one immutable deterministic JSON receipt after every output exists."""

    if path.exists():
        raise FileExistsError("Blender benchmark receipt already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    """Verify one case, render it with fixed operations, and bind all output hashes."""

    args = _parse_args()
    root = Path(args.output_root).resolve()
    contract_path = _contained_path(root, args.case_contract)
    blend_path = _contained_path(root, args.blend_output)
    render_path = _contained_path(root, args.render_output)
    receipt_path = _contained_path(root, args.receipt_output)
    for path in (blend_path, render_path, receipt_path):
        if path.exists():
            raise FileExistsError(f"Blender benchmark output already exists: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
    case = _read_case(
        contract_path,
        args.case_contract_file_sha256,
        args.camera_sha256,
    )
    _reset_scene()
    object_count = _configure_scene(case, args.camera_sha256, render_path)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
    bpy.ops.render.render(write_still=True)
    if not blend_path.is_file() or not render_path.is_file():
        raise RuntimeError("Blender probe did not create both required outputs")
    _write_receipt(
        receipt_path,
        {
            "schema_version": "0.2.0",
            "case_id": case["case_id"],
            "case_contract_path": args.case_contract,
            "case_contract_file_sha256": args.case_contract_file_sha256,
            "blend_path": args.blend_output,
            "blend_sha256": _file_sha256(blend_path),
            "render_path": args.render_output,
            "render_sha256": _file_sha256(render_path),
            "object_count": object_count,
            "camera_sha256": args.camera_sha256,
            "external_downloads_used": False,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
