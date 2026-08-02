from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import bpy

DEFERRED_MODIFIER_KINDS = {"boolean", "normal_transfer"}


def scheduled_modifier_kinds(modifiers: list[dict]) -> list[str]:
    """Mirror the builder's immediate-then-deferred modifier scheduling order."""

    immediate = [
        modifier["kind"]
        for modifier in modifiers
        if modifier["kind"] not in DEFERRED_MODIFIER_KINDS
    ]
    deferred = [
        modifier["kind"]
        for modifier in modifiers
        if modifier["kind"] in DEFERRED_MODIFIER_KINDS
    ]
    return [*immediate, *deferred]


def parse_args() -> argparse.Namespace:
    """Parse the SceneSpec and validation-report paths passed by the Blender runner."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def modifier_kinds(obj: bpy.types.Object, property_name: str) -> list[str]:
    """Decode comma-separated modifier provenance stored on a generated object."""

    value = str(obj.get(property_name, ""))
    return [item for item in value.split(",") if item]


def main() -> None:
    """Validate generated object families, geometry, and declared modifier execution."""

    args = parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []
    generated = [obj for obj in bpy.context.scene.objects if obj.get("cbm_id")]
    ids = [str(obj.get("cbm_id")) for obj in generated]
    counts = Counter(ids)

    expected_counts: dict[str, int] = {}
    geometry_kinds: dict[str, str] = {}
    expected_modifier_kinds: dict[str, list[str]] = {}
    expected_applied_modifier_kinds: dict[str, list[str]] = {}
    for item in spec["objects"]:
        expected_counts[item["id"]] = (
            int(item.get("generator", {}).get("count", 1)) if item.get("generator") else 1
        )
        geometry_kinds[item["id"]] = item["geometry"]["kind"]
        modifier_specs = item.get("modifiers", [])
        expected_modifier_kinds[item["id"]] = [
            modifier["kind"] for modifier in modifier_specs
        ]
        expected_applied_modifier_kinds[item["id"]] = scheduled_modifier_kinds(
            modifier_specs
        )

    for object_id, expected in expected_counts.items():
        actual = counts.get(object_id, 0)
        if actual != expected:
            errors.append(
                f"Object ID {object_id}: expected {expected} generated instances, found {actual}"
            )

    extra = sorted(set(counts) - set(expected_counts))
    if extra:
        errors.append(f"Unexpected generated object IDs: {extra}")

    mesh_count = 0
    vertex_count = 0
    polygon_count = 0
    for obj in generated:
        dims = tuple(float(value) for value in obj.dimensions)
        if any((not math.isfinite(value)) or value <= 0 for value in dims):
            errors.append(f"{obj.name}: non-positive or non-finite dimensions {dims}")
        if obj.type == "MESH":
            mesh_count += 1
            vertex_count += len(obj.data.vertices)
            polygon_count += len(obj.data.polygons)
            if len(obj.data.polygons) == 0:
                errors.append(f"{obj.name}: mesh has no faces")
        elif obj.type == "CURVE":
            if not obj.data.splines:
                errors.append(f"{obj.name}: curve has no splines")
            warnings.append(f"{obj.name}: remains a CURVE; enable convert_to_mesh for mesh export")
        else:
            errors.append(f"{obj.name}: unsupported generated object type {obj.type}")
        if not obj.material_slots:
            warnings.append(f"{obj.name}: no material")
        expected_kind = geometry_kinds.get(str(obj.get("cbm_id")))
        actual_kind = obj.get("cbm_geometry_kind")
        if actual_kind != expected_kind:
            errors.append(
                f"{obj.name}: geometry kind metadata mismatch {actual_kind!r} != {expected_kind!r}"
            )
        expected_modifiers = expected_modifier_kinds.get(str(obj.get("cbm_id")), [])
        expected_applied_modifiers = expected_applied_modifier_kinds.get(
            str(obj.get("cbm_id")), []
        )
        declared_modifiers = modifier_kinds(obj, "cbm_declared_modifier_kinds")
        applied_modifiers = modifier_kinds(obj, "cbm_applied_modifier_kinds")
        if declared_modifiers != expected_modifiers:
            errors.append(
                f"{obj.name}: declared modifier metadata mismatch "
                f"{declared_modifiers!r} != {expected_modifiers!r}"
            )
        if applied_modifiers != expected_applied_modifiers:
            errors.append(
                f"{obj.name}: applied modifier metadata mismatch "
                f"{applied_modifiers!r} != {expected_applied_modifiers!r}"
            )

    if bpy.context.scene.camera is None:
        errors.append("No active comparison camera")

    scene = bpy.context.scene
    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "runtime": {
            "blender_version": bpy.app.version_string,
            "render_engine": scene.get("cbm_render_engine", scene.render.engine),
            "render_device": scene.get("cbm_render_device", "DEFAULT"),
            "cycles_compute_backend": scene.get("cbm_cycles_compute_backend"),
            "cycles_devices": scene.get("cbm_cycles_devices"),
            "cycles_samples": scene.get("cbm_cycles_samples"),
            "color_management_look": scene.get(
                "cbm_color_management_look", scene.view_settings.look
            ),
        },
        "metrics": {
            "generated_objects": len(generated),
            "generated_mesh_objects": mesh_count,
            "vertices_before_modifier_evaluation": vertex_count,
            "polygons_before_modifier_evaluation": polygon_count,
            "expected_object_families": len(expected_counts),
            "material_count": len(bpy.data.materials),
            "declared_modifier_kinds": sorted(
                {kind for kinds in expected_modifier_kinds.values() for kind in kinds}
            ),
            "applied_modifier_kinds": sorted(
                {
                    kind
                    for obj in generated
                    for kind in modifier_kinds(obj, "cbm_applied_modifier_kinds")
                }
            ),
        },
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"CBM_VALIDATE_{'OK' if report['ok'] else 'FAILED'} output={output}")


if __name__ == "__main__":
    main()
