from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from portable_asset_common import (  # noqa: E402
    inspect_mesh_topology_data,
    object_inventory,
    read_json_object,
    scene_source_provenance,
    write_json,
)


def evaluated_topology(obj: bpy.types.Object) -> dict[str, Any]:
    """Inspect the evaluated mesh that deterministic optimization will copy as LOD0."""

    dependencies = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(dependencies)
    mesh = evaluated.to_mesh()
    try:
        return inspect_mesh_topology_data(mesh, evaluated.matrix_world)
    finally:
        evaluated.to_mesh_clear()


def parse_args() -> argparse.Namespace:
    """Parse the bounded asset-preflight arguments passed after Blender's separator."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--policy")
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def load_policy(path_text: str | None) -> dict[str, Any]:
    """Load an optional preflight policy or return conservative engine-neutral defaults."""

    defaults: dict[str, Any] = {
        "require_uv0": False,
        "require_material": True,
        "require_applied_scale": True,
        "fail_on_negative_determinant": True,
        "fail_on_non_finite": True,
        "fail_on_degenerate_faces": True,
        "fail_on_loose_geometry": False,
        "fail_on_open_boundaries": False,
        "allowed_open_semantic_ids": [],
        "max_triangles_total": None,
        "max_triangles_per_object": None,
    }
    if path_text:
        supplied = read_json_object(Path(path_text).expanduser().resolve())
        defaults.update(supplied)
    return defaults


def _scale_is_applied(obj: bpy.types.Object, tolerance: float = 1e-6) -> bool:
    """Return whether object scale is effectively one on every axis."""

    return all(abs(float(value) - 1.0) <= tolerance for value in obj.scale)


def evaluate_object(
    record: dict[str, Any], policy: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Evaluate one portable object record against explicit preflight policy switches."""

    errors: list[str] = []
    warnings: list[str] = []
    name = str(record["name"])
    semantic_id = str(record.get("semantic_id") or name)
    topology = record.get("topology")

    if not record["material_ids"]:
        target = errors if policy["require_material"] else warnings
        target.append(f"{name}: no material assignment")
    if any(not math.isfinite(float(value)) for value in record["dimensions"]):
        errors.append(f"{name}: non-finite object dimensions")
    if any(float(value) <= 0.0 for value in record["dimensions"]):
        errors.append(f"{name}: non-positive object dimensions")

    if topology is None:
        warnings.append(f"{name}: non-mesh object is not portable geometry")
        return errors, warnings

    if policy["fail_on_non_finite"] and topology["non_finite_vertex_count"]:
        errors.append(f"{name}: non-finite vertices={topology['non_finite_vertex_count']}")
    if policy["fail_on_degenerate_faces"] and topology["degenerate_face_count"]:
        errors.append(f"{name}: degenerate faces={topology['degenerate_face_count']}")
    if topology["invalid_normal_face_count"]:
        errors.append(f"{name}: invalid face normals={topology['invalid_normal_face_count']}")
    if policy["fail_on_negative_determinant"] and topology["negative_determinant"]:
        errors.append(f"{name}: negative world transform determinant")
    if policy["fail_on_loose_geometry"] and (
        topology["loose_vertex_count"] or topology["loose_edge_count"]
    ):
        errors.append(
            f"{name}: loose vertices={topology['loose_vertex_count']} "
            f"edges={topology['loose_edge_count']}"
        )
    allowed_open = {str(item) for item in policy["allowed_open_semantic_ids"]}
    if (
        policy["fail_on_open_boundaries"]
        and topology["boundary_edge_count"]
        and semantic_id not in allowed_open
    ):
        errors.append(f"{name}: open boundary edges={topology['boundary_edge_count']}")
    elif topology["boundary_edge_count"] and semantic_id not in allowed_open:
        warnings.append(f"{name}: open boundary edges={topology['boundary_edge_count']}")
    if topology["overused_edge_count"]:
        errors.append(f"{name}: non-manifold overused edges={topology['overused_edge_count']}")
    if policy["require_uv0"] and not topology["uv_layers"]:
        errors.append(f"{name}: required UV0 is missing")
    max_triangles = policy.get("max_triangles_per_object")
    if max_triangles is not None and topology["triangles_estimated"] > int(max_triangles):
        errors.append(
            f"{name}: triangle budget exceeded "
            f"{topology['triangles_estimated']} > {int(max_triangles)}"
        )
    return errors, warnings


def main() -> None:
    """Inspect the loaded authoring scene without changing any object or datablock."""

    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    policy = load_policy(args.policy)
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    eligible = sorted(
        (obj for obj in bpy.context.scene.objects if obj.type in {"MESH", "CURVE"}),
        key=lambda item: item.name,
    )
    candidates = []
    for obj in eligible:
        if not obj.get("cbm_id"):
            errors.append(f"{obj.name}: renderable geometry is missing stable cbm_id")
            continue
        role = str(obj.get("cbm_asset_role", "authoring") or "authoring")
        if role != "authoring":
            errors.append(f"{obj.name}: canonical geometry has unexpected asset role {role}")
            continue
        candidates.append(obj)
    for obj in candidates:
        record = object_inventory(obj)
        source_topology = record.get("topology")
        if source_topology is not None:
            record["source_topology"] = source_topology
        record["topology"] = evaluated_topology(obj)
        record["hide_render"] = bool(obj.hide_render)
        if policy["require_applied_scale"] and not _scale_is_applied(obj):
            errors.append(f"{obj.name}: unapplied scale={record['scale']}")
        object_errors, object_warnings = evaluate_object(record, policy)
        errors.extend(object_errors)
        warnings.extend(object_warnings)
        records.append(record)

    triangle_total = sum(
        int(record.get("topology", {}).get("triangles_estimated", 0))
        for record in records
    )
    maximum = policy.get("max_triangles_total")
    if maximum is not None and triangle_total > int(maximum):
        errors.append(f"Scene triangle budget exceeded {triangle_total} > {int(maximum)}")
    if not records:
        errors.append("No semantic mesh or curve objects were found")

    report = {
        "schema_version": "0.7.0",
        "kind": "mesh_preflight_report",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "policy": policy,
        "source": scene_source_provenance(bpy.context.scene),
        "runtime": {"blender_version": bpy.app.version_string},
        "metrics": {
            "object_count": len(records),
            "mesh_count": sum(record["type"] == "MESH" for record in records),
            "curve_count": sum(record["type"] == "CURVE" for record in records),
            "triangles_estimated": triangle_total,
        },
        "objects": records,
    }
    write_json(output, report)
    state = "OK" if report["ok"] else "FAILED"
    print(f"CBM_ASSET_PREFLIGHT_{state} output={output}")


if __name__ == "__main__":
    main()
