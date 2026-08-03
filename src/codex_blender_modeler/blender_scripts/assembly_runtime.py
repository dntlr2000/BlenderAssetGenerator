from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import bpy
from mathutils import Matrix, Vector

_AXIS = {"X": 0, "Y": 1, "Z": 2}


def sha256_file(path: Path) -> str:
    """Hash one raw assembly contract without host-only dependencies."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    """Serialize Blender custom-property metadata deterministically."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_assembly_contract(job_root: Path) -> dict[str, Any]:
    """Load the optional raw ModelingPlan assembly contract and its exact hash."""

    path = job_root / "analysis" / "modeling_plan.json"
    if not path.is_file():
        return {
            "declared": False,
            "path": None,
            "sha256": None,
            "policy": "legacy_unbound",
            "frame": None,
            "relationships": [],
            "roles": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ModelingPlan is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ModelingPlan must contain one JSON object")
    policy = str(payload.get("assembly_consistency_policy", "legacy_unbound"))
    if policy not in {"legacy_unbound", "spatial_v1"}:
        raise RuntimeError(f"Unsupported assembly_consistency_policy: {policy!r}")
    frame = payload.get("assembly_frame")
    relationships = payload.get("assembly_relationships", [])
    objects = payload.get("objects", [])
    if frame is not None and not isinstance(frame, dict):
        raise RuntimeError("ModelingPlan assembly_frame must be an object or null")
    if not isinstance(relationships, list) or not all(
        isinstance(item, dict) for item in relationships
    ):
        raise RuntimeError("ModelingPlan assembly_relationships must be an object array")
    if not isinstance(objects, list):
        raise RuntimeError("ModelingPlan objects must be an array")
    roles: dict[str, str] = {}
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        roles[str(item["id"])] = str(item.get("assembly_role", "unclassified"))
    return {
        "declared": policy == "spatial_v1",
        "path": path,
        "sha256": sha256_file(path),
        "policy": policy,
        "frame": frame,
        "relationships": relationships,
        "roles": roles,
    }


def relationship_ids_by_object(contract: dict[str, Any]) -> dict[str, list[str]]:
    """Index every declared relation ID by all semantic objects it mentions."""

    result: dict[str, set[str]] = {}
    for relation in contract["relationships"]:
        relation_id = relation.get("id")
        if not isinstance(relation_id, str):
            continue
        for field in ("subject_id", "reference_id", "peer_id"):
            object_id = relation.get(field)
            if isinstance(object_id, str):
                result.setdefault(object_id, set()).add(relation_id)
    return {key: sorted(values) for key, values in sorted(result.items())}


def attach_assembly_metadata(
    scene: bpy.types.Scene,
    object_map: dict[str, list[bpy.types.Object]],
    contract: dict[str, Any],
) -> None:
    """Embed exact assembly provenance and per-object roles in the built scene."""

    scene["cbm_assembly_policy"] = contract["policy"]
    if contract["sha256"] is not None:
        scene["cbm_assembly_modeling_plan_sha256"] = contract["sha256"]
    scene["cbm_assembly_frame_json"] = canonical_json(contract["frame"])
    scene["cbm_assembly_relationships_json"] = canonical_json(
        contract["relationships"]
    )
    relationship_index = relationship_ids_by_object(contract)
    for object_id, objects in object_map.items():
        role = contract["roles"].get(object_id, "unclassified")
        relation_ids = relationship_index.get(object_id, [])
        for obj in objects:
            obj["cbm_assembly_role"] = role
            obj["cbm_assembly_relationship_ids"] = canonical_json(relation_ids)
            if contract["sha256"] is not None:
                obj["cbm_assembly_modeling_plan_sha256"] = contract["sha256"]


def matrix_rows(matrix: Any) -> list[list[float]]:
    """Convert one Blender matrix into portable rounded row-major values."""

    return [
        [round(float(matrix[row][column]), 9) for column in range(4)]
        for row in range(4)
    ]


def evaluated_world_corners(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> list[Vector]:
    """Return evaluated object bound-box corners in world coordinates."""

    evaluated = obj.evaluated_get(depsgraph)
    return [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]


def bounds_from_points(points: list[Vector]) -> dict[str, list[float]]:
    """Reduce nonempty 3D points to a rounded axis-aligned bounds record."""

    if not points:
        raise ValueError("Assembly bounds require at least one point")
    minimum = [min(float(point[axis]) for point in points) for axis in range(3)]
    maximum = [max(float(point[axis]) for point in points) for axis in range(3)]
    return {
        "min": [round(value, 9) for value in minimum],
        "max": [round(value, 9) for value in maximum],
    }


def evaluated_world_bounds(
    obj: bpy.types.Object,
    depsgraph: bpy.types.Depsgraph,
) -> dict[str, list[float]]:
    """Measure evaluated geometry bounds in world coordinates."""

    return bounds_from_points(evaluated_world_corners(obj, depsgraph))


def resolve_assembly_world_to_frame(
    frame: dict[str, Any] | None,
    object_map: dict[str, list[bpy.types.Object]],
    depsgraph: bpy.types.Depsgraph,
) -> tuple[Matrix | None, str | None]:
    """Resolve one unique root's translation-and-rotation-only inverse meter frame."""

    if not isinstance(frame, dict):
        return None, "Assembly frame is missing or invalid"
    root_id = frame.get("root_object_id")
    if not isinstance(root_id, str) or not root_id:
        return None, "Assembly frame root_object_id is missing or invalid"
    roots = _sorted_instances(object_map.get(root_id, []))
    if len(roots) != 1:
        return None, (
            "Assembly frame requires exactly one evaluated root instance: "
            f"root_object_id={root_id!r} count={len(roots)}"
        )
    evaluated_matrix = roots[0].evaluated_get(depsgraph).matrix_world
    translation, rotation, _scale = evaluated_matrix.decompose()
    frame_to_world = Matrix.Translation(translation) @ rotation.to_matrix().to_4x4()
    return frame_to_world.inverted(), None


def evaluated_bounds_in_frame(
    objects: list[bpy.types.Object],
    world_to_frame: Matrix,
    depsgraph: bpy.types.Depsgraph,
) -> dict[str, list[float]]:
    """Transform evaluated object corners into an orthonormal assembly meter frame."""

    points = [
        world_to_frame @ point
        for obj in objects
        for point in evaluated_world_corners(obj, depsgraph)
    ]
    return bounds_from_points(points)


def _center(bounds: dict[str, list[float]]) -> list[float]:
    """Return the center of one min/max bounds record."""

    return [
        (float(bounds["min"][axis]) + float(bounds["max"][axis])) * 0.5
        for axis in range(3)
    ]


def _dimensions(bounds: dict[str, list[float]]) -> list[float]:
    """Return nonnegative dimensions of one min/max bounds record."""

    return [
        float(bounds["max"][axis]) - float(bounds["min"][axis])
        for axis in range(3)
    ]


def _instance_index(obj: bpy.types.Object) -> int:
    """Read a generated instance index with a deterministic zero fallback."""

    return int(obj.get("cbm_instance_index", 0))


def _sorted_instances(objects: list[bpy.types.Object]) -> list[bpy.types.Object]:
    """Sort semantic instances by declared instance index and Blender name."""

    return sorted(objects, key=lambda item: (_instance_index(item), item.name))


def _relationship_operands(
    relation: dict[str, Any],
    object_map: dict[str, list[bpy.types.Object]],
) -> tuple[
    list[
        tuple[
            list[bpy.types.Object],
            list[bpy.types.Object],
            list[bpy.types.Object],
        ]
    ],
    str | None,
]:
    """Resolve unambiguous family, pairwise, or broadcast Blender operands."""

    subjects = _sorted_instances(object_map.get(str(relation.get("subject_id")), []))
    references = _sorted_instances(object_map.get(str(relation.get("reference_id")), []))
    peer_id = relation.get("peer_id")
    peers = _sorted_instances(object_map.get(str(peer_id), [])) if peer_id else []
    missing = []
    if not subjects:
        missing.append(str(relation.get("subject_id")))
    if not references:
        missing.append(str(relation.get("reference_id")))
    if peer_id and not peers:
        missing.append(str(peer_id))
    if missing:
        return [], f"Evaluated Blender objects are missing for: {sorted(missing)}"
    policy = str(relation.get("instance_policy", "family_bounds"))
    if policy == "family_bounds":
        if len(references) != 1:
            return [], (
                "family_bounds requires exactly one concrete reference instance for "
                "assembly-frame evaluation"
            )
        return [(subjects, references, peers)], None
    if policy == "broadcast_reference":
        if len(references) != 1:
            return [], (
                "broadcast_reference requires exactly one concrete reference instance"
            )
        if peer_id and len(peers) != len(subjects):
            return [], "Bilateral broadcast subjects and peers require equal counts"
        return [
            ([subject], references, [peers[index]] if peers else [])
            for index, subject in enumerate(subjects)
        ], None
    if policy != "pairwise":
        return [], f"Unsupported assembly instance_policy: {policy!r}"
    reference_indices = [_instance_index(obj) for obj in references]
    peer_indices = [_instance_index(obj) for obj in peers]
    reference_by_index = {_instance_index(obj): obj for obj in references}
    peer_by_index = {_instance_index(obj): obj for obj in peers}
    subject_indices = [_instance_index(obj) for obj in subjects]
    if len(subject_indices) != len(set(subject_indices)):
        return [], "Pairwise subject instance indices are ambiguous"
    if len(reference_indices) != len(set(reference_indices)):
        return [], "Pairwise reference instance indices are ambiguous"
    if len(peer_indices) != len(set(peer_indices)):
        return [], "Pairwise peer instance indices are ambiguous"
    if set(subject_indices) != set(reference_by_index):
        return [], "Pairwise subject/reference instance indices differ"
    if peer_id and set(subject_indices) != set(peer_by_index):
        return [], "Pairwise subject/peer instance indices differ"
    return [
        (
            [subject],
            [reference_by_index[_instance_index(subject)]],
            [peer_by_index[_instance_index(subject)]] if peer_id else [],
        )
        for subject in subjects
    ], None


def _axis_residual(
    difference_m: float,
    reference_extent_m: float,
    tolerance: dict[str, Any],
) -> tuple[float, float, str]:
    """Express one assembly residual in meters or normalized reference extent."""

    mode = str(tolerance.get("mode", "relative"))
    value = float(tolerance.get("value", 0.05))
    if mode == "meters":
        return abs(difference_m), value, mode
    if mode != "relative":
        raise ValueError(f"Unsupported assembly tolerance mode: {mode!r}")
    return abs(difference_m) / max(reference_extent_m, 1.0e-12), value, mode


def _transverse_overlap_metrics(
    subject: dict[str, list[float]],
    reference: dict[str, list[float]],
    contact_axis: int,
    minimum_ratio: float,
) -> tuple[bool, dict[str, Any]]:
    """Measure broad bbox overlap on both axes transverse to a contact normal."""

    subject_dimensions = _dimensions(subject)
    reference_dimensions = _dimensions(reference)
    ratios: dict[str, float] = {}
    for axis_name, axis in _AXIS.items():
        if axis == contact_axis:
            continue
        overlap = max(
            0.0,
            min(float(subject["max"][axis]), float(reference["max"][axis]))
            - max(float(subject["min"][axis]), float(reference["min"][axis])),
        )
        denominator = max(
            min(subject_dimensions[axis], reference_dimensions[axis]),
            1.0e-12,
        )
        ratios[axis_name] = overlap / denominator
    return (
        all(value + 1.0e-12 >= minimum_ratio for value in ratios.values()),
        {
            "transverse_overlap_ratios": {
                key: round(value, 9) for key, value in sorted(ratios.items())
            },
            "min_transverse_overlap_ratio": minimum_ratio,
        },
    )


def _evaluate_bounds_relation(
    relation: dict[str, Any],
    subject: dict[str, list[float]],
    reference: dict[str, list[float]],
    peer: dict[str, list[float]] | None,
) -> tuple[float, float, str, dict[str, Any]]:
    """Evaluate one raw relationship from common assembly-frame meter bounds."""

    kind = str(relation.get("kind"))
    tolerance = relation.get("tolerance", {})
    if not isinstance(tolerance, dict):
        raise ValueError("Assembly relationship tolerance must be an object")
    subject_center = _center(subject)
    reference_center = _center(reference)
    reference_dimensions = _dimensions(reference)
    metrics: dict[str, Any] = {
        "scorable": True,
        "bbox_basis": "evaluated_bbox_corners_in_assembly_frame_meters",
        "subject_bbox_assembly_frame": subject,
        "reference_bbox_assembly_frame": reference,
    }
    if peer is not None:
        metrics["peer_bbox_assembly_frame"] = peer
    if kind == "center_plane":
        axis_name = str(relation["axis"])
        axis = _AXIS[axis_name]
        residual, allowed, mode = _axis_residual(
            subject_center[axis] - reference_center[axis],
            reference_dimensions[axis],
            tolerance,
        )
        return residual, allowed, mode, metrics
    if kind == "coaxial":
        axes = [str(value) for value in relation["axes"]]
        values = [
            _axis_residual(
                subject_center[_AXIS[axis_name]] - reference_center[_AXIS[axis_name]],
                reference_dimensions[_AXIS[axis_name]],
                tolerance,
            )
            for axis_name in axes
        ]
        return max(value[0] for value in values), values[0][1], values[0][2], metrics
    if kind == "bbox_containment":
        values = []
        for axis_name in [str(value) for value in relation["axes"]]:
            axis = _AXIS[axis_name]
            overflow = max(
                float(reference["min"][axis]) - float(subject["min"][axis]),
                float(subject["max"][axis]) - float(reference["max"][axis]),
                0.0,
            )
            values.append(
                _axis_residual(
                    overflow,
                    reference_dimensions[axis],
                    tolerance,
                )
            )
        return max(value[0] for value in values), values[0][1], values[0][2], metrics
    if kind == "surface_contact":
        axis_name = str(relation["axis"])
        axis = _AXIS[axis_name]
        subject_side = str(relation["subject_side"])
        reference_side = str(relation["reference_side"])
        subject_value = float(subject["min" if subject_side == "MIN" else "max"][axis])
        reference_value = float(
            reference["min" if reference_side == "MIN" else "max"][axis]
        )
        residual, allowed, mode = _axis_residual(
            subject_value - reference_value,
            reference_dimensions[axis],
            tolerance,
        )
        overlap_ok, overlap_metrics = _transverse_overlap_metrics(
            subject,
            reference,
            axis,
            float(relation.get("min_transverse_overlap_ratio", 0.05)),
        )
        metrics["signed_surface_delta_m"] = round(subject_value - reference_value, 9)
        metrics["transverse_overlap_ok"] = overlap_ok
        metrics.update(overlap_metrics)
        return residual, allowed, mode, metrics
    if kind == "side_specific":
        axis_name = str(relation["axis"])
        axis = _AXIS[axis_name]
        signed = subject_center[axis] - reference_center[axis]
        mode = str(tolerance.get("mode", "relative"))
        allowed = float(tolerance.get("value", 0.05))
        if mode == "relative":
            signed /= max(reference_dimensions[axis], 1.0e-12)
        directed = -signed if str(relation["side"]) == "MIN" else signed
        metrics["directed_side_distance"] = round(directed, 9)
        return max(0.0, allowed - directed), 0.0, mode, metrics
    if kind == "bilateral_pair":
        if peer is None:
            raise ValueError("Bilateral relationship has no evaluated peer bounds")
        axis_name = str(relation["axis"])
        axis = _AXIS[axis_name]
        peer_center = _center(peer)
        peer_dimensions = _dimensions(peer)
        mirror_center_error = abs(
            (subject_center[axis] - reference_center[axis])
            + (peer_center[axis] - reference_center[axis])
        )
        values = [
            _axis_residual(
                mirror_center_error,
                reference_dimensions[axis],
                tolerance,
            )
        ]
        subject_dimensions = _dimensions(subject)
        for current_axis in range(3):
            if current_axis != axis:
                values.append(
                    _axis_residual(
                        subject_center[current_axis] - peer_center[current_axis],
                        reference_dimensions[current_axis],
                        tolerance,
                    )
                )
            values.append(
                _axis_residual(
                    subject_dimensions[current_axis] - peer_dimensions[current_axis],
                    reference_dimensions[current_axis],
                    tolerance,
                )
            )
        return max(value[0] for value in values), values[0][1], values[0][2], metrics
    raise ValueError(f"Unsupported assembly relationship kind: {kind!r}")


def evaluate_assembly_relationships(
    contract: dict[str, Any],
    object_map: dict[str, list[bpy.types.Object]],
) -> dict[str, Any]:
    """Evaluate raw assembly relationships against live Blender evaluated bounds."""

    if contract["policy"] != "spatial_v1":
        return {
            "policy": contract["policy"],
            "status": "not_declared",
            "ok": True,
            "checks": [],
            "metrics": {
                "relationship_count": 0,
                "evaluated_check_count": 0,
                "bbox_basis": "not_applicable",
            },
            "notes": [],
        }
    depsgraph = bpy.context.evaluated_depsgraph_get()
    world_to_frame, frame_error = resolve_assembly_world_to_frame(
        contract["frame"], object_map, depsgraph
    )
    if frame_error is not None or world_to_frame is None:
        root_id = (
            contract["frame"].get("root_object_id")
            if isinstance(contract["frame"], dict)
            else None
        )
        return {
            "policy": contract["policy"],
            "status": "failed",
            "ok": False,
            "checks": [
                {
                    "id": "assembly.frame.root",
                    "relation_id": None,
                    "kind": "contract",
                    "required": True,
                    "subject_id": root_id,
                    "reference_id": None,
                    "peer_id": None,
                    "evidence_status": (
                        contract["frame"].get("evidence_status")
                        if isinstance(contract["frame"], dict)
                        else None
                    ),
                    "source_ids": (
                        [str(value) for value in contract["frame"].get("source_ids", [])]
                        if isinstance(contract["frame"], dict)
                        else []
                    ),
                    "status": "failed",
                    "instance_index": None,
                    "residual": None,
                    "tolerance": None,
                    "tolerance_mode": None,
                    "message": str(frame_error),
                    "metrics": {
                        "scorable": False,
                        "bbox_basis": (
                            "evaluated_bbox_corners_in_assembly_frame_meters"
                        ),
                    },
                }
            ],
            "metrics": {
                "relationship_count": len(contract["relationships"]),
                "evaluated_check_count": 1,
                "instance_policies": sorted(
                    {
                        str(item.get("instance_policy", "family_bounds"))
                        for item in contract["relationships"]
                    }
                ),
                "bbox_basis": "evaluated_bbox_corners_in_assembly_frame_meters",
                "assembly_frame_root_id": root_id,
            },
            "notes": ["Assembly evaluation failed closed before relationship scoring."],
        }
    checks: list[dict[str, Any]] = []
    policies: set[str] = set()
    for relation in contract["relationships"]:
        required = bool(relation.get("required", True))
        relation_id = str(relation.get("id", "__invalid__"))
        policy = str(relation.get("instance_policy", "family_bounds"))
        policies.add(policy)
        operands, error = _relationship_operands(relation, object_map)
        base = {
            "relation_id": relation_id,
            "kind": str(relation.get("kind", "contract")),
            "required": required,
            "subject_id": relation.get("subject_id"),
            "reference_id": relation.get("reference_id"),
            "peer_id": relation.get("peer_id"),
            "evidence_status": str(relation.get("evidence_status", "inferred")),
            "source_ids": [str(value) for value in relation.get("source_ids", [])],
        }
        if error is not None:
            checks.append(
                {
                    "id": f"assembly.bounds.{relation_id}",
                    **base,
                    "status": "failed" if required else "warning",
                    "instance_index": None,
                    "residual": None,
                    "tolerance": None,
                    "tolerance_mode": None,
                    "message": error,
                    "metrics": {
                        "scorable": False,
                        "bbox_basis": (
                            "evaluated_bbox_corners_in_assembly_frame_meters"
                        ),
                    },
                }
            )
            continue
        for subjects, reference_objects, peers in operands:
            index = _instance_index(subjects[0]) if len(subjects) == 1 else 0
            try:
                subject_bounds = evaluated_bounds_in_frame(
                    subjects, world_to_frame, depsgraph
                )
                reference_bounds = evaluated_bounds_in_frame(
                    reference_objects, world_to_frame, depsgraph
                )
                peer_bounds = (
                    evaluated_bounds_in_frame(peers, world_to_frame, depsgraph)
                    if peers
                    else None
                )
                residual, tolerance, mode, metrics = _evaluate_bounds_relation(
                    relation,
                    subject_bounds,
                    reference_bounds,
                    peer_bounds,
                )
                passed = residual <= tolerance + 1.0e-12 and bool(
                    metrics.get("transverse_overlap_ok", True)
                )
                checks.append(
                    {
                        "id": f"assembly.bounds.{relation_id}.{index}",
                        **base,
                        "status": (
                            "passed" if passed else ("failed" if required else "warning")
                        ),
                        "instance_index": index,
                        "residual": round(float(residual), 9),
                        "tolerance": round(float(tolerance), 9),
                        "tolerance_mode": mode,
                        "message": (
                            f"{relation.get('kind')} residual={residual:.6g} "
                            f"tolerance={tolerance:.6g} ({mode}); measured from "
                            "evaluated bbox corners in the assembly root meter frame."
                        ),
                        "metrics": metrics,
                    }
                )
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                checks.append(
                    {
                        "id": f"assembly.bounds.{relation_id}.{index}",
                        **base,
                        "status": "failed" if required else "warning",
                        "instance_index": index,
                        "residual": None,
                        "tolerance": None,
                        "tolerance_mode": None,
                        "message": f"Assembly relation is unscorable: {exc}",
                        "metrics": {
                            "scorable": False,
                            "bbox_basis": (
                            "evaluated_bbox_corners_in_assembly_frame_meters"
                            ),
                        },
                    }
                )
    failed = sum(item["status"] == "failed" for item in checks)
    warned = sum(item["status"] == "warning" for item in checks)
    status = "failed" if failed else ("warning" if warned else "passed")
    return {
        "policy": contract["policy"],
        "status": status,
        "ok": failed == 0,
        "checks": checks,
        "metrics": {
            "relationship_count": len(contract["relationships"]),
            "evaluated_check_count": len(checks),
            "instance_policies": sorted(policies),
            "bbox_basis": "evaluated_bbox_corners_in_assembly_frame_meters",
            "assembly_frame_root_id": contract["frame"]["root_object_id"],
        },
        "notes": [
            (
                "Assembly checks use evaluated bounding-box corners in the root object's "
                "translation-and-rotation-only orthonormal meter frame, not "
                "transform.location."
            ),
            "BBox contact/containment is deterministic broad evidence, not triangle/BVH proof.",
            (
                "Hidden-side inferred relationships remain authored consistency "
                "assumptions, not recovered truth."
            ),
        ],
    }
