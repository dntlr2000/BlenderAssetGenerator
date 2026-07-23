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
    object_inventory,
    operator_kwargs,
    package_dependency_path,
    read_json_object,
    sha256_file,
    write_json,
)


def parse_args() -> argparse.Namespace:
    """Parse one clean-import round-trip validation request."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--format", required=True, choices=["glb", "gltf", "fbx", "obj"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--bounds-tolerance", type=float, default=0.0001)
    parser.add_argument("--triangle-relative-tolerance", type=float, default=0.01)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def clear_scene() -> None:
    """Remove all current objects so validation always starts from an empty scene."""

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)


def import_gltf(path: Path) -> str:
    """Import GLB or glTF through Blender's feature-probed glTF operator."""

    operator = getattr(getattr(bpy.ops, "import_scene", None), "gltf", None)
    if operator is None:
        raise RuntimeError("This Blender build exposes no glTF importer")
    operator(**operator_kwargs(operator, {"filepath": str(path)}))
    return "bpy.ops.import_scene.gltf"


def import_fbx(path: Path) -> str:
    """Import FBX through Blender's feature-probed interchange operator."""

    operator = getattr(getattr(bpy.ops, "import_scene", None), "fbx", None)
    if operator is None:
        raise RuntimeError("This Blender build exposes no FBX importer")
    candidates = {
        "filepath": str(path),
        "use_custom_props": True,
        "use_custom_props_enum_as_string": True,
        "automatic_bone_orientation": False,
    }
    operator(**operator_kwargs(operator, candidates))
    return "bpy.ops.import_scene.fbx"


def import_obj(path: Path) -> str:
    """Import OBJ with Blender 5's modern operator and a Blender 4 fallback."""

    modern = getattr(getattr(bpy.ops, "wm", None), "obj_import", None)
    if modern is not None:
        candidates = {
            "filepath": str(path),
            "forward_axis": "NEGATIVE_Z",
            "up_axis": "Y",
        }
        modern(**operator_kwargs(modern, candidates))
        return "bpy.ops.wm.obj_import"
    legacy = getattr(getattr(bpy.ops, "import_scene", None), "obj", None)
    if legacy is not None:
        candidates = {
            "filepath": str(path),
            "axis_forward": "-Z",
            "axis_up": "Y",
        }
        legacy(**operator_kwargs(legacy, candidates))
        return "bpy.ops.import_scene.obj"
    raise RuntimeError("This Blender build exposes no OBJ importer")


def import_asset(format_name: str, path: Path) -> str:
    """Dispatch one whitelisted clean-import format."""

    if format_name in {"glb", "gltf"}:
        return import_gltf(path)
    if format_name == "fbx":
        return import_fbx(path)
    if format_name == "obj":
        return import_obj(path)
    raise ValueError(f"Unsupported import format: {format_name!r}")


def _record_key(record: dict[str, Any]) -> tuple[str, int | None, str, int | None]:
    """Build a stable semantic/instance/role/LOD key for exported object matching."""

    semantic_id = str(record.get("semantic_id") or "")
    instance = record.get("instance_index")
    role = str(record.get("asset_role") or "")
    lod = record.get("lod_level")
    return semantic_id, instance, role, lod


def match_records(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]], format_name: str
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[str]]:
    """Match imported objects by semantic metadata, falling back to names for OBJ only."""

    errors: list[str] = []
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    available = list(actual)
    for expected_record in expected:
        match = next(
            (
                item
                for item in available
                if _record_key(item) == _record_key(expected_record)
            ),
            None,
        )
        if match is None and format_name == "obj":
            match = next(
                (item for item in available if item["name"] == expected_record["name"]),
                None,
            )
        if match is None:
            errors.append(f"Missing imported object: {expected_record['name']}")
            continue
        available.remove(match)
        matches.append((expected_record, match))
    if available:
        errors.append(
            "Unexpected imported objects: " + ", ".join(item["name"] for item in available)
        )
    return matches, errors


def max_bbox_error(expected: dict[str, Any], actual: dict[str, Any]) -> float:
    """Return the greatest absolute per-axis world-bound difference for one match."""

    differences = []
    for boundary in ("min", "max"):
        differences.extend(
            abs(float(first) - float(second))
            for first, second in zip(
                expected["bbox_world"][boundary],
                actual["bbox_world"][boundary],
                strict=True,
            )
        )
    return max(differences, default=0.0)


def _require_inside(path: Path, root: Path, label: str) -> Path:
    """Resolve one validation input and reject escape outside its immutable package."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.expanduser().resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside package root: {resolved}") from exc
    return resolved


def texture_path_findings(package_root: Path) -> dict[str, list[str]]:
    """Classify missing, outside, absolute, and malformed imported image dependencies."""

    missing: list[str] = []
    outside: list[str] = []
    absolute: list[str] = []
    package_absolute: list[str] = []
    invalid: list[str] = []
    for image in sorted(bpy.data.images, key=lambda item: item.name):
        raw = str(image.filepath or "")
        if not raw or image.packed_file is not None or image.source == "GENERATED":
            continue
        status, resolved = package_dependency_path(raw, package_root)
        if status == "absolute":
            absolute.append(image.name)
            continue
        if status == "package_absolute":
            if resolved is None or not resolved.is_file():
                missing.append(image.name)
            else:
                package_absolute.append(image.name)
            continue
        if status == "outside":
            outside.append(image.name)
            continue
        if status != "portable" or resolved is None:
            invalid.append(image.name)
            continue
        if not resolved.is_file():
            missing.append(image.name)
    return {
        "missing": missing,
        "outside": outside,
        "absolute": absolute,
        "package_absolute": package_absolute,
        "invalid": invalid,
    }


def tangent_readiness(obj: bpy.types.Object) -> dict[str, Any]:
    """Verify finite tangents from the material normal-map UV or active fallback."""

    role = str(obj.get("cbm_asset_role", ""))
    if role == "collider":
        return {"status": "not_applicable", "reason": "collider"}
    mesh = obj.data
    if not mesh.uv_layers:
        return {"status": "unverified", "reason": "missing_uv"}
    material_uv_sets = sorted(
        {
            str(node.uv_map)
            for slot in obj.material_slots
            if slot.material is not None
            and slot.material.node_tree is not None
            for node in slot.material.node_tree.nodes
            if node.type == "NORMAL_MAP" and str(getattr(node, "uv_map", ""))
        }
    )
    if len(material_uv_sets) > 1:
        return {
            "status": "failed",
            "reason": "declared_normal_uv_ambiguous",
            "declared_uv_sets": material_uv_sets,
        }
    if material_uv_sets:
        uv_layer = mesh.uv_layers.get(material_uv_sets[0])
        if uv_layer is None:
            return {
                "status": "failed",
                "reason": "declared_normal_uv_missing",
                "declared_uv_sets": material_uv_sets,
            }
        selection_basis = "material_normal_map"
    else:
        uv_layer = next(
            (layer for layer in mesh.uv_layers if bool(layer.active_render)),
            mesh.uv_layers.active or mesh.uv_layers[0],
        )
        selection_basis = "active_render_fallback"
    calculator = getattr(mesh, "calc_tangents", None)
    if calculator is None:
        return {"status": "unverified", "reason": "runtime_unsupported"}
    invalid = 0
    try:
        calculator(uvmap=uv_layer.name)
        for loop in mesh.loops:
            values = tuple(float(value) for value in loop.tangent)
            sign = float(loop.bitangent_sign)
            length_squared = sum(value * value for value in values)
            if (
                not all(math.isfinite(value) for value in values)
                or not math.isfinite(sign)
                or length_squared <= 1e-18
            ):
                invalid += 1
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "status": "failed",
            "reason": "tangent_calculation_error",
            "detail": f"{type(exc).__name__}: {exc}",
            "uv_set": uv_layer.name,
            "selection_basis": selection_basis,
        }
    finally:
        freer = getattr(mesh, "free_tangents", None)
        if freer is not None:
            try:
                freer()
            except (AttributeError, RuntimeError):
                pass
    return {
        "status": "ready" if invalid == 0 else "failed",
        "uv_set": uv_layer.name,
        "selection_basis": selection_basis,
        "loop_count": len(mesh.loops),
        "invalid_loop_count": invalid,
        "preserved_exported_tangents_verified": False,
    }


def imported_object_record(obj: bpy.types.Object) -> dict[str, Any]:
    """Add runtime normal and tangent readiness to one imported object inventory."""

    record = object_inventory(obj)
    topology = record.get("topology", {})
    record["runtime_readiness"] = {
        "face_normals": {
            "status": (
                "ready"
                if int(topology.get("invalid_normal_face_count", 0)) == 0
                else "failed"
            ),
            "invalid_face_count": int(topology.get("invalid_normal_face_count", 0)),
            "custom_normal_equivalence_verified": False,
        },
        "tangents": tangent_readiness(obj),
    }
    return record


def _uv_metric_error(first: Any, second: Any) -> float | None:
    """Return a finite UV metric delta, or None when either summary is unavailable."""

    if first is None or second is None:
        return None
    if isinstance(first, dict) and isinstance(second, dict):
        try:
            values = [
                abs(float(first[boundary][axis]) - float(second[boundary][axis]))
                for boundary in ("min", "max")
                for axis in range(2)
            ]
        except (KeyError, TypeError, ValueError, IndexError):
            return None
        return max(values, default=0.0)
    try:
        return abs(float(first) - float(second))
    except (TypeError, ValueError):
        return None


def uv_coordinate_readiness(
    expected: dict[str, Any],
    actual: dict[str, Any],
    tolerance: float = 1e-5,
    *,
    enforce_layer_identity: bool = False,
) -> dict[str, Any]:
    """Compare UV summaries and vertex-bound loop associations across clean import."""

    expected_layers = list(expected.get("topology", {}).get("uv_layers", []))
    actual_layers = list(actual.get("topology", {}).get("uv_layers", []))
    if not expected_layers and not actual_layers:
        return {"status": "not_applicable", "layer_count": 0}
    if len(expected_layers) != len(actual_layers):
        return {
            "status": "failed",
            "expected_layer_count": len(expected_layers),
            "actual_layer_count": len(actual_layers),
        }
    layers: list[dict[str, Any]] = []
    summary_ready = True
    summary_failed = False
    for expected_layer, actual_layer in zip(expected_layers, actual_layers, strict=True):
        non_finite = int(actual_layer.get("non_finite_coordinate_count", 0))
        bounds_error = _uv_metric_error(
            expected_layer.get("coordinate_bounds"),
            actual_layer.get("coordinate_bounds"),
        )
        area_error = _uv_metric_error(
            expected_layer.get("total_face_area"),
            actual_layer.get("total_face_area"),
        )
        name_matches = expected_layer.get("name") == actual_layer.get("name")
        active_render_matches = bool(expected_layer.get("active_render")) == bool(
            actual_layer.get("active_render")
        )
        fingerprint_matches = (
            expected_layer.get("coordinate_fingerprint")
            == actual_layer.get("coordinate_fingerprint")
            if expected_layer.get("coordinate_fingerprint") is not None
            and actual_layer.get("coordinate_fingerprint") is not None
            else None
        )
        binding_fingerprint_matches = (
            expected_layer.get("vertex_uv_binding_fingerprint")
            == actual_layer.get("vertex_uv_binding_fingerprint")
            if expected_layer.get("vertex_uv_binding_fingerprint") is not None
            and actual_layer.get("vertex_uv_binding_fingerprint") is not None
            else None
        )
        identity_ready = (
            name_matches and active_render_matches
            if enforce_layer_identity
            else True
        )
        layer_ready = (
            non_finite == 0
            and identity_ready
            and bounds_error is not None
            and area_error is not None
            and bounds_error <= tolerance
            and area_error <= tolerance
            and fingerprint_matches is not False
            and binding_fingerprint_matches is True
        )
        summary_ready = summary_ready and layer_ready
        summary_failed = (
            summary_failed
            or non_finite > 0
            or (enforce_layer_identity and fingerprint_matches is False)
            or (enforce_layer_identity and binding_fingerprint_matches is False)
            or (enforce_layer_identity and not identity_ready)
            or (
                bounds_error is not None
                and area_error is not None
                and (bounds_error > tolerance or area_error > tolerance)
            )
        )
        layers.append(
            {
                "expected_name": expected_layer.get("name"),
                "actual_name": actual_layer.get("name"),
                "name_preserved": name_matches,
                "active_render_preserved": active_render_matches,
                "non_finite_coordinate_count": non_finite,
                "bounds_max_abs_error": bounds_error,
                "total_area_abs_error": area_error,
                "coordinate_multiset_fingerprint_preserved": fingerprint_matches,
                "vertex_uv_binding_fingerprint_preserved": (
                    binding_fingerprint_matches
                ),
            }
        )
    loop_association_verified = bool(layers) and all(
        item["vertex_uv_binding_fingerprint_preserved"] is True for item in layers
    )
    return {
        "status": (
            "summary_ready"
            if summary_ready
            else "failed"
            if summary_failed
            else "unverified"
        ),
        "layer_count": len(layers),
        "summary_tolerance": tolerance,
        "layer_identity_enforced": enforce_layer_identity,
        "loop_association_verified": loop_association_verified,
        "layers": layers,
    }


def portable_uv_binding_readiness(
    expected_manifest: dict[str, Any],
    expected: dict[str, Any],
    actual: dict[str, Any],
    uv_readiness: dict[str, Any],
    tangent: dict[str, Any],
) -> dict[str, Any]:
    """Verify one converted FBX mesh binds atlas sampling and tangents to UV0."""

    contract = expected_manifest.get("uv_binding_contract")
    if not isinstance(contract, dict) or contract.get("status") != "verified":
        return {"status": "not_applicable", "reason": "no_verified_contract"}
    if expected.get("asset_role") == "collider":
        return {"status": "not_applicable", "reason": "collider"}
    required_name = contract.get("required_uv_set")
    required_index = contract.get("required_uv_channel_index")
    if not isinstance(required_name, str) or required_index != 0:
        return {"status": "failed", "reason": "invalid_export_contract"}
    expected_layers = list(expected.get("topology", {}).get("uv_layers", []))
    actual_layers = list(actual.get("topology", {}).get("uv_layers", []))
    expected_uv0 = expected_layers[0] if expected_layers else {}
    actual_uv0 = actual_layers[0] if actual_layers else {}
    association_verified = bool(uv_readiness.get("loop_association_verified"))
    checks = {
        "expected_uv0_name": expected_uv0.get("name") == required_name,
        "actual_uv0_name": actual_uv0.get("name") == required_name,
        "expected_uv0_active_render": bool(expected_uv0.get("active_render")),
        "actual_uv0_active_render": bool(actual_uv0.get("active_render")),
        "tangent_uv_set": tangent.get("uv_set") == required_name,
        "tangent_status": tangent.get("status") == "ready",
        "loop_association": association_verified,
    }
    return {
        "status": "verified" if all(checks.values()) else "failed",
        "required_uv_set": required_name,
        "required_uv_channel_index": 0,
        "destination_semantic": contract.get("destination_semantic", "TEXCOORD_0"),
        "tangent_uv_set": tangent.get("uv_set"),
        "checks": checks,
    }


def coordinate_readiness(expected_manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate declared axis/unit configuration while marking file metadata unverified."""

    contract = expected_manifest.get("coordinate_contract")
    expected = {
        "source_up_axis": "+Z",
        "export_up_axis": "+Y",
        "export_forward_axis": "-Z",
        "source_contract_units": "meters",
        "unit_scale_m": 1.0,
    }
    if not isinstance(contract, dict):
        return {"status": "unverified", "reason": "missing_export_coordinate_contract"}
    mismatches = {
        key: {"expected": value, "actual": contract.get(key)}
        for key, value in expected.items()
        if contract.get(key) != value
    }
    return {
        "status": "declared_not_file_inspected" if not mismatches else "failed",
        "declared": contract,
        "mismatches": mismatches,
        "axis_file_metadata_verified": False,
        "unit_file_metadata_verified": False,
    }


def main() -> None:
    """Clean-import one package and compare normalized inventory to its export manifest."""

    args = parse_args()
    if not math.isfinite(args.bounds_tolerance) or args.bounds_tolerance < 0.0:
        raise ValueError("Bounds tolerance must be a finite non-negative number")
    if (
        not math.isfinite(args.triangle_relative_tolerance)
        or args.triangle_relative_tolerance < 0.0
    ):
        raise ValueError(
            "Triangle relative tolerance must be a finite non-negative number"
        )
    package_root = Path(args.package_root).expanduser().resolve()
    if not package_root.is_dir():
        raise NotADirectoryError(package_root)
    input_path = _require_inside(Path(args.input), package_root, "Primary asset")
    expected_path = _require_inside(
        Path(args.expected), package_root, "Export evidence"
    )
    output_path = Path(args.output).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    if not expected_path.is_file():
        raise FileNotFoundError(expected_path)
    expected_manifest = read_json_object(expected_path)
    if expected_manifest.get("kind") != "portable_export_evidence":
        raise ValueError("Expected report is not V0.7 portable export evidence")
    if expected_manifest.get("format") != args.format:
        raise ValueError("Requested round-trip format differs from package manifest")

    clear_scene()
    operator = import_asset(args.format, input_path)
    actual_records = [
        imported_object_record(obj)
        for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name)
        if obj.type == "MESH"
    ]
    expected_records = list(expected_manifest.get("objects", []))
    matches, errors = match_records(expected_records, actual_records, args.format)
    warnings = [str(value) for value in expected_manifest.get("warnings", [])]
    coordinate = coordinate_readiness(expected_manifest)
    if coordinate["status"] == "failed":
        errors.append("Export coordinate declaration differs from the V0.7 contract")
    elif coordinate["status"] == "unverified":
        warnings.append("Export axis and unit declaration is unavailable for verification.")
    else:
        warnings.extend(
            [
                "Axis conversion is declared by the export operator but file metadata "
                "was not independently inspected; imported bounds provide indirect "
                "evidence only.",
                "Meter units and unit scale are declared by the export operator but "
                "file metadata was not independently inspected; imported numeric "
                "bounds provide indirect evidence only.",
            ]
        )
    comparisons: list[dict[str, Any]] = []
    invalid_normal_objects: list[str] = []
    tangent_unverified_objects: list[str] = []
    uv_unverified_objects: list[str] = []
    uv_association_unverified_objects: list[str] = []
    portable_binding_records: list[dict[str, Any]] = []
    for expected_record, actual_record in matches:
        bounds_error = max_bbox_error(expected_record, actual_record)
        expected_triangles = int(
            expected_record.get("topology", {}).get("triangles_estimated", 0)
        )
        actual_triangles = int(
            actual_record.get("topology", {}).get("triangles_estimated", 0)
        )
        triangle_relative_error = (
            abs(actual_triangles - expected_triangles) / max(expected_triangles, 1)
        )
        expected_materials = set(expected_record.get("material_ids", []))
        actual_materials = set(actual_record.get("material_ids", []))
        expected_uv_count = len(expected_record.get("topology", {}).get("uv_layers", []))
        actual_uv_count = len(actual_record.get("topology", {}).get("uv_layers", []))
        uv_readiness = uv_coordinate_readiness(
            expected_record,
            actual_record,
            enforce_layer_identity=args.format == "fbx",
        )
        face_normal_readiness = actual_record.get("runtime_readiness", {}).get(
            "face_normals", {}
        )
        tangent = actual_record.get("runtime_readiness", {}).get("tangents", {})
        portable_binding = portable_uv_binding_readiness(
            expected_manifest,
            expected_record,
            actual_record,
            uv_readiness,
            tangent,
        )
        if bounds_error > args.bounds_tolerance:
            errors.append(
                f"{expected_record['name']}: bounds error {bounds_error:.9f} exceeds "
                f"{args.bounds_tolerance:.9f}"
            )
        if triangle_relative_error > args.triangle_relative_tolerance:
            errors.append(
                f"{expected_record['name']}: triangle relative error "
                f"{triangle_relative_error:.6f} exceeds {args.triangle_relative_tolerance:.6f}"
            )
        if expected_materials != actual_materials:
            errors.append(
                f"{expected_record['name']}: material IDs changed "
                f"{sorted(expected_materials)} -> {sorted(actual_materials)}"
            )
        if expected_uv_count != actual_uv_count:
            errors.append(
                f"{expected_record['name']}: UV layer count changed "
                f"{expected_uv_count} -> {actual_uv_count}"
            )
        if face_normal_readiness.get("status") == "failed":
            invalid_normal_objects.append(str(actual_record["name"]))
            errors.append(f"{actual_record['name']}: imported face normals are invalid")
        if tangent.get("status") == "failed":
            errors.append(f"{actual_record['name']}: imported tangent basis is invalid")
        elif tangent.get("status") == "unverified":
            tangent_unverified_objects.append(str(actual_record["name"]))
        if uv_readiness.get("status") == "failed":
            errors.append(
                f"{actual_record['name']}: imported UV coordinate readiness failed"
            )
        elif uv_readiness.get("status") == "unverified":
            uv_unverified_objects.append(str(actual_record["name"]))
        if not bool(uv_readiness.get("loop_association_verified")):
            uv_association_unverified_objects.append(str(actual_record["name"]))
        if portable_binding.get("status") == "failed":
            errors.append(
                f"{actual_record['name']}: portable material UV0/tangent binding failed"
            )
        if portable_binding.get("status") != "not_applicable":
            portable_binding_records.append(
                {"object_name": str(actual_record["name"]), **portable_binding}
            )
        comparisons.append(
            {
                "expected_name": expected_record["name"],
                "actual_name": actual_record["name"],
                "semantic_id": expected_record.get("semantic_id"),
                "asset_role": expected_record.get("asset_role"),
                "lod_level": expected_record.get("lod_level"),
                "bounds_max_abs_error_m": round(bounds_error, 9),
                "triangles_expected": expected_triangles,
                "triangles_actual": actual_triangles,
                "triangle_relative_error": round(triangle_relative_error, 9),
                "material_ids_preserved": expected_materials == actual_materials,
                "uv_layer_count_expected": expected_uv_count,
                "uv_layer_count_actual": actual_uv_count,
                "uv_coordinate_readiness": uv_readiness,
                "face_normal_readiness": face_normal_readiness,
                "tangent_readiness": tangent,
                "portable_uv_binding": portable_binding,
            }
        )

    texture_findings = texture_path_findings(package_root)
    if texture_findings["missing"]:
        errors.append(
            "Missing imported textures: " + ", ".join(texture_findings["missing"])
        )
    if texture_findings["outside"]:
        errors.append(
            "Imported texture paths escape the package root: "
            + ", ".join(texture_findings["outside"])
        )
    if texture_findings["absolute"]:
        errors.append(
            "Imported package contains absolute texture paths: "
            + ", ".join(texture_findings["absolute"])
        )
    if texture_findings["invalid"]:
        errors.append(
            "Imported package contains malformed texture paths: "
            + ", ".join(texture_findings["invalid"])
        )
    if texture_findings["package_absolute"]:
        warnings.append(
            "Blender resolved package-local texture references to runtime absolute "
            "paths for: " + ", ".join(texture_findings["package_absolute"])
        )
    if args.format == "obj":
        warnings.append(
            "OBJ round-trip uses object names because the format cannot preserve CBM properties."
        )
    warnings.extend(
        [
            "Custom split-normal equivalence is not verified; runtime face-normal "
            "validity is checked instead.",
            "Exported tangent vector equivalence is not verified; V0.7 checks only "
            "whether a finite basis can be recomputed from the imported UV set.",
        ]
    )
    if uv_association_unverified_objects:
        warnings.append(
            "UV loop-to-vertex association could not be verified for: "
            + ", ".join(uv_association_unverified_objects)
        )
    if tangent_unverified_objects:
        warnings.append(
            "Tangent readiness could not be verified for: "
            + ", ".join(tangent_unverified_objects)
        )
    if uv_unverified_objects:
        warnings.append(
            "UV coordinate summary preservation could not be verified for: "
            + ", ".join(uv_unverified_objects)
        )
    warnings = list(dict.fromkeys(warnings))

    finite_errors = [
        record["name"]
        for record in actual_records
        if record.get("topology", {}).get("non_finite_vertex_count", 0)
    ]
    if finite_errors:
        errors.append("Non-finite imported geometry: " + ", ".join(finite_errors))

    report = {
        "schema_version": "0.7.0",
        "kind": "roundtrip_validation",
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "format": args.format,
        "import_operator": operator,
        "input": {
            "filename": input_path.name,
            "sha256": sha256_file(input_path),
            "expected_manifest_sha256": sha256_file(expected_path),
        },
        "source": expected_manifest.get("source", {}),
        "runtime": {"blender_version": bpy.app.version_string},
        "readiness": {
            "coordinate_system": coordinate,
            "face_normals": {
                "status": "ready" if not invalid_normal_objects else "failed",
                "invalid_objects": invalid_normal_objects,
                "custom_normal_equivalence_verified": False,
            },
            "tangents": {
                "recomputability_checked": True,
                "unverified_objects": tangent_unverified_objects,
                "preserved_exported_tangents_verified": False,
            },
            "uv_coordinates": {
                "summary_metrics_checked": True,
                "unverified_objects": uv_unverified_objects,
                "loop_association_verified": not uv_association_unverified_objects,
            },
            "portable_uv_binding": {
                "status": (
                    "verified"
                    if portable_binding_records
                    and all(item.get("status") == "verified" for item in portable_binding_records)
                    else "failed"
                    if portable_binding_records
                    else "not_applicable"
                ),
                "required_uv_set": expected_manifest.get(
                    "uv_binding_contract", {}
                ).get("required_uv_set"),
                "required_uv_channel_index": expected_manifest.get(
                    "uv_binding_contract", {}
                ).get("required_uv_channel_index"),
                "verified_object_count": sum(
                    item.get("status") == "verified" for item in portable_binding_records
                ),
                "objects": portable_binding_records,
            },
        },
        "tolerances": {
            "bounds_m": args.bounds_tolerance,
            "triangle_relative": args.triangle_relative_tolerance,
        },
        "metrics": {
            "expected_object_count": len(expected_records),
            "actual_object_count": len(actual_records),
            "matched_object_count": len(matches),
            "missing_texture_count": len(texture_findings["missing"]),
            "outside_texture_path_count": len(texture_findings["outside"]),
            "absolute_texture_path_count": len(texture_findings["absolute"]),
            "package_absolute_texture_path_count": len(
                texture_findings["package_absolute"]
            ),
            "invalid_texture_path_count": len(texture_findings["invalid"]),
            "invalid_normal_object_count": len(invalid_normal_objects),
            "tangent_unverified_object_count": len(tangent_unverified_objects),
            "uv_unverified_object_count": len(uv_unverified_objects),
        },
        "comparisons": comparisons,
        "imported_objects": actual_records,
    }
    write_json(output_path, report)
    state = "OK" if report["ok"] else "FAILED"
    print(f"CBM_ASSET_ROUNDTRIP_{state} output={output_path}")


if __name__ == "__main__":
    main()
