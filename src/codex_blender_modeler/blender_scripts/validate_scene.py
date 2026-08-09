from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from assembly_runtime import (  # noqa: E402
    evaluate_assembly_relationships,
    load_assembly_contract,
    relationship_ids_by_object,
)

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
    """Parse SceneSpec, optional job-root, and report paths from the Blender runner."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--job-root")
    parser.add_argument("--output", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def modifier_kinds(obj: bpy.types.Object, property_name: str) -> list[str]:
    """Decode comma-separated modifier provenance stored on a generated object."""

    value = str(obj.get(property_name, ""))
    return [item for item in value.split(",") if item]


def _assembly_metadata_checks(
    contract: dict,
    object_map: dict[str, list[bpy.types.Object]],
) -> list[dict]:
    """Verify exact assembly provenance and per-object metadata in the built scene."""

    scene = bpy.context.scene
    embedded_policy = str(scene.get("cbm_assembly_policy", "legacy_unbound"))
    if contract["policy"] != "spatial_v1" and embedded_policy != "spatial_v1":
        return []
    checks: list[dict] = []
    embedded_hash = scene.get("cbm_assembly_modeling_plan_sha256")
    current_hash = contract["sha256"]
    hash_matches = embedded_hash == current_hash
    checks.append(
        {
            "id": "assembly.provenance.modeling_plan",
            "relation_id": None,
            "kind": "contract",
            "status": "passed" if hash_matches else "failed",
            "required": True,
            "subject_id": None,
            "reference_id": None,
            "peer_id": None,
            "instance_index": None,
            "evidence_status": None,
            "source_ids": [],
            "residual": None,
            "tolerance": None,
            "tolerance_mode": None,
            "message": (
                "Embedded assembly ModelingPlan hash matches the current contract."
                if hash_matches
                else (
                    "Built scene assembly provenance is stale: "
                    f"embedded={embedded_hash!r} current={current_hash!r}"
                )
            ),
            "metrics": {"scorable": hash_matches},
        }
    )
    policy_matches = embedded_policy == contract["policy"]
    checks.append(
        {
            "id": "assembly.provenance.policy",
            "relation_id": None,
            "kind": "contract",
            "status": "passed" if policy_matches else "failed",
            "required": True,
            "subject_id": None,
            "reference_id": None,
            "peer_id": None,
            "instance_index": None,
            "evidence_status": None,
            "source_ids": [],
            "residual": None,
            "tolerance": None,
            "tolerance_mode": None,
            "message": (
                "Embedded assembly policy matches the current contract."
                if policy_matches
                else (
                    "Built scene assembly policy is stale: "
                    f"embedded={embedded_policy!r} current={contract['policy']!r}"
                )
            ),
            "metrics": {"scorable": policy_matches},
        }
    )
    expected_relationships = relationship_ids_by_object(contract)
    for object_id in sorted(contract["roles"]):
        instances = object_map.get(object_id, [])
        if not instances:
            continue
        expected_role = contract["roles"][object_id]
        expected_ids = expected_relationships.get(object_id, [])
        for obj in sorted(instances, key=lambda item: item.name):
            actual_role = str(obj.get("cbm_assembly_role", "unclassified"))
            try:
                actual_ids = json.loads(
                    str(obj.get("cbm_assembly_relationship_ids", "[]"))
                )
            except json.JSONDecodeError:
                actual_ids = None
            metadata_matches = (
                actual_role == expected_role
                and isinstance(actual_ids, list)
                and sorted(str(value) for value in actual_ids) == expected_ids
            )
            checks.append(
                {
                    "id": f"assembly.metadata.{object_id}.{obj.name}",
                    "relation_id": None,
                    "kind": "contract",
                    "status": "passed" if metadata_matches else "failed",
                    "required": True,
                    "subject_id": object_id,
                    "reference_id": None,
                    "peer_id": None,
                    "instance_index": int(obj.get("cbm_instance_index", 0)),
                    "evidence_status": None,
                    "source_ids": [],
                    "residual": None,
                    "tolerance": None,
                    "tolerance_mode": None,
                    "message": (
                        "Built object assembly role and relation IDs match the ModelingPlan."
                        if metadata_matches
                        else (
                            f"Built object assembly metadata differs: role={actual_role!r} "
                            f"relationship_ids={actual_ids!r}; expected_role={expected_role!r} "
                            f"expected_relationship_ids={expected_ids!r}"
                        )
                    ),
                    "metrics": {"scorable": metadata_matches},
                }
            )
    return checks


def _assembly_messages(report: dict) -> tuple[list[str], list[str]]:
    """Project required assembly failures and advisory checks into scene messages."""

    errors = [
        f"Assembly {item['id']}: {item['message']}"
        for item in report.get("checks", [])
        if item.get("status") == "failed"
    ]
    warnings = [
        f"Assembly {item['id']}: {item['message']}"
        for item in report.get("checks", [])
        if item.get("status") == "warning"
    ]
    return errors, warnings


def main() -> None:
    """Validate generated object families, geometry, and declared modifier execution."""

    args = parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    job_root = (
        Path(args.job_root).expanduser().resolve()
        if args.job_root
        else spec_path.parent.parent
    )
    assembly_contract = load_assembly_contract(job_root)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    warnings: list[str] = []
    generated = [obj for obj in bpy.context.scene.objects if obj.get("cbm_id")]
    object_map: dict[str, list[bpy.types.Object]] = {}
    for obj in generated:
        object_map.setdefault(str(obj.get("cbm_id")), []).append(obj)
    ids = [str(obj.get("cbm_id")) for obj in generated]
    counts = Counter(ids)

    expected_counts: dict[str, int] = {}
    geometry_kinds: dict[str, str] = {}
    expected_modifier_kinds: dict[str, list[str]] = {}
    expected_applied_modifier_kinds: dict[str, list[str]] = {}
    expected_parent_ids: dict[str, str | None] = {}
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
        expected_parent_ids[item["id"]] = item.get("parent_id")

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
        expected_parent = expected_parent_ids.get(str(obj.get("cbm_id")))
        actual_parent = (
            str(obj.parent.get("cbm_id", obj.parent.name))
            if obj.parent is not None
            else None
        )
        if actual_parent != expected_parent:
            errors.append(
                f"{obj.name}: Blender parent semantic ID mismatch "
                f"{actual_parent!r} != {expected_parent!r}"
            )

    if bpy.context.scene.camera is None:
        errors.append("No active comparison camera")

    assembly = evaluate_assembly_relationships(assembly_contract, object_map)
    metadata_checks = _assembly_metadata_checks(assembly_contract, object_map)
    assembly["checks"] = [*metadata_checks, *assembly["checks"]]
    assembly["modeling_plan_sha256"] = assembly_contract["sha256"]
    assembly["embedded_modeling_plan_sha256"] = bpy.context.scene.get(
        "cbm_assembly_modeling_plan_sha256"
    )
    assembly["frame"] = assembly_contract["frame"]
    failed_assembly = sum(
        item["status"] == "failed" for item in assembly["checks"]
    )
    warned_assembly = sum(
        item["status"] == "warning" for item in assembly["checks"]
    )
    assembly["ok"] = failed_assembly == 0
    embedded_policy = str(
        bpy.context.scene.get("cbm_assembly_policy", "legacy_unbound")
    )
    if (
        assembly_contract["policy"] == "spatial_v1"
        or embedded_policy == "spatial_v1"
    ):
        hashes_match = (
            assembly["embedded_modeling_plan_sha256"]
            == assembly["modeling_plan_sha256"]
        )
        policies_match = embedded_policy == assembly_contract["policy"]
        assembly["status"] = (
            "stale"
            if not hashes_match or not policies_match
            else ("failed" if failed_assembly else ("warning" if warned_assembly else "passed"))
        )
    assembly_errors, assembly_warnings = _assembly_messages(assembly)
    errors.extend(assembly_errors)
    warnings.extend(assembly_warnings)

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
        "assembly": assembly,
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"CBM_VALIDATE_{'OK' if report['ok'] else 'FAILED'} output={output}")


if __name__ == "__main__":
    main()
