"""Inspect evaluated authoring meshes for strict AQ assembly and topology evidence."""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from assembly_runtime import (  # noqa: E402
    evaluate_assembly_relationships,
    load_assembly_contract,
)
from portable_asset_common import (  # noqa: E402
    inspect_mesh_topology_data,
    write_json,
)

AREA_EPSILON = 1.0e-12
UV_EPSILON = 1.0e-10
MAX_SELF_INTERSECTION_TRIANGLES = 5000
MAX_UV_TRIANGLES = 2048
MAX_UV_PAIR_TESTS = 1_000_000
MAX_BVH_SAMPLES = 512


def _parse_args() -> argparse.Namespace:
    """Parse only the fixed evidence paths and exact host-provided source hashes."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--modeling-plan-relative", default="analysis/modeling_plan.json")
    parser.add_argument("--scene-spec-sha256", required=True)
    parser.add_argument("--modeling-plan-sha256", required=True)
    parser.add_argument("--blend-sha256", required=True)
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    return parser.parse_args(argv)


def _resolve_job_relative(job_root: Path, value: str) -> Path:
    """Resolve one normalized job-relative evidence path without allowing escape."""

    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise RuntimeError("ModelingPlan path must be normalized and job-relative")
    candidate = (job_root / Path(*pure.parts)).resolve()
    try:
        candidate.relative_to(job_root)
    except ValueError as exc:
        raise RuntimeError("ModelingPlan path escapes the job workspace") from exc
    return candidate


def _semantic_object_map() -> dict[str, list[bpy.types.Object]]:
    """Index authoring mesh/curve objects by stable semantic ID."""

    result: dict[str, list[bpy.types.Object]] = defaultdict(list)
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        if obj.type not in {"MESH", "CURVE"}:
            continue
        if str(obj.get("cbm_asset_role", "authoring") or "authoring") != "authoring":
            continue
        semantic_id = obj.get("cbm_id")
        if not isinstance(semantic_id, str) or not semantic_id.strip():
            raise RuntimeError(f"{obj.name}: authoring geometry is missing stable cbm_id")
        result[semantic_id].append(obj)
    if not result:
        raise RuntimeError("No semantic authoring mesh or curve objects were found")
    return dict(result)


def _finite_vector(vector: Any) -> bool:
    """Return whether every coordinate of a Blender vector is finite."""

    return all(math.isfinite(float(value)) for value in vector)


def _triangle_aspect(points: tuple[Vector, Vector, Vector]) -> float:
    """Measure longest edge divided by shortest triangle altitude."""

    lengths = [float((points[(index + 1) % 3] - points[index]).length) for index in range(3)]
    area = float((points[1] - points[0]).cross(points[2] - points[0]).length) * 0.5
    if area <= AREA_EPSILON or min(lengths) <= AREA_EPSILON:
        return math.inf
    minimum_altitude = min((2.0 * area) / length for length in lengths)
    return max(lengths) / minimum_altitude


def _winding_inconsistency_count(mesh: bpy.types.Mesh) -> int:
    """Count manifold edges traversed in the same direction by both incident faces."""

    directions: dict[tuple[int, int], list[int]] = defaultdict(list)
    for polygon in mesh.polygons:
        vertices = [int(value) for value in polygon.vertices]
        for first, second in zip(vertices, [*vertices[1:], vertices[0]], strict=True):
            key = tuple(sorted((first, second)))
            directions[key].append(1 if (first, second) == key else -1)
    return sum(len(values) == 2 and values[0] == values[1] for values in directions.values())


def _connected_vertex_components(mesh: bpy.types.Mesh) -> list[set[int]]:
    """Return deterministic vertex components joined by mesh edges."""

    adjacency: dict[int, set[int]] = {int(vertex.index): set() for vertex in mesh.vertices}
    for edge in mesh.edges:
        first, second = (int(value) for value in edge.vertices)
        adjacency[first].add(second)
        adjacency[second].add(first)
    remaining = set(adjacency)
    components: list[set[int]] = []
    while remaining:
        seed = min(remaining)
        stack = [seed]
        component: set[int] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(sorted(adjacency[current] - component, reverse=True))
        remaining -= component
        components.append(component)
    return components


def _flipped_component_metrics(
    mesh: bpy.types.Mesh,
    world_vertices: list[Vector],
    triangles: list[tuple[int, int, int]],
    topology: dict[str, Any],
) -> dict[str, Any]:
    """Use signed volume per closed component to detect globally reversed shells."""

    if topology["boundary_edge_count"] or topology["overused_edge_count"]:
        return {
            "availability": "unavailable",
            "message": "Signed-volume orientation requires closed two-manifold components.",
        }
    components = _connected_vertex_components(mesh)
    component_index = {
        vertex: index for index, component in enumerate(components) for vertex in component
    }
    volumes = [0.0 for _ in components]
    for first, second, third in triangles:
        component = component_index[first]
        a, b, c = world_vertices[first], world_vertices[second], world_vertices[third]
        volumes[component] += float(a.dot(b.cross(c))) / 6.0
    if any(not math.isfinite(value) or abs(value) <= AREA_EPSILON for value in volumes):
        return {
            "availability": "unavailable",
            "message": "At least one closed component has indeterminate signed volume.",
        }
    negative = sum(value < 0.0 for value in volumes)
    return {
        "availability": "available",
        "passed": negative == 0,
        "measured_value": negative,
        "threshold": 0,
        "message": (
            f"Signed volume found {negative} reversed closed component(s) across "
            f"{len(volumes)} component(s)."
        ),
    }


def _bounded_self_intersection(
    world_vertices: list[Vector], triangles: list[tuple[int, int, int]]
) -> dict[str, Any]:
    """Count non-adjacent BVH self-overlaps within a strict triangle budget."""

    if len(triangles) > MAX_SELF_INTERSECTION_TRIANGLES:
        return {
            "availability": "unavailable",
            "message": (
                "Self-intersection BVH budget exceeded: "
                f"{len(triangles)} > {MAX_SELF_INTERSECTION_TRIANGLES} triangles."
            ),
        }
    if not triangles:
        return {
            "availability": "unavailable",
            "message": "Self-intersection evidence requires at least one triangle.",
        }
    tree = BVHTree.FromPolygons(world_vertices, triangles, all_triangles=True)
    pairs = {
        tuple(sorted((int(left), int(right))))
        for left, right in tree.overlap(tree)
        if int(left) != int(right) and not set(triangles[int(left)]) & set(triangles[int(right)])
    }
    return {
        "availability": "available",
        "passed": not pairs,
        "measured_value": len(pairs),
        "threshold": 0,
        "message": f"Blender BVH found {len(pairs)} non-adjacent overlap pair(s).",
    }


def _signed_uv_area(points: list[tuple[float, float]]) -> float:
    """Return signed polygon area in UV space."""

    return 0.5 * sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, [*points[1:], points[0]], strict=True)
    )


def _inside_clip_edge(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> bool:
    """Return whether a point lies on the inclusive left side of a clip edge."""

    return (
        (second[0] - first[0]) * (point[1] - first[1])
        - (second[1] - first[1]) * (point[0] - first[0])
    ) >= -UV_EPSILON


def _line_intersection(
    start: tuple[float, float],
    end: tuple[float, float],
    clip_start: tuple[float, float],
    clip_end: tuple[float, float],
) -> tuple[float, float]:
    """Intersect two infinite 2D lines for convex polygon clipping."""

    direction = (end[0] - start[0], end[1] - start[1])
    clip_direction = (clip_end[0] - clip_start[0], clip_end[1] - clip_start[1])
    denominator = direction[0] * clip_direction[1] - direction[1] * clip_direction[0]
    if abs(denominator) <= UV_EPSILON:
        return end
    offset = (clip_start[0] - start[0], clip_start[1] - start[1])
    factor = (offset[0] * clip_direction[1] - offset[1] * clip_direction[0]) / denominator
    return (start[0] + factor * direction[0], start[1] + factor * direction[1])


def _triangle_intersection_area(
    first: list[tuple[float, float]], second: list[tuple[float, float]]
) -> float:
    """Return positive-area overlap between two UV triangles."""

    subject = list(first)
    clip = list(second)
    if _signed_uv_area(clip) < 0:
        clip.reverse()
    for clip_first, clip_second in zip(clip, [*clip[1:], clip[0]], strict=True):
        if not subject:
            return 0.0
        output: list[tuple[float, float]] = []
        previous = subject[-1]
        for current in subject:
            current_inside = _inside_clip_edge(current, clip_first, clip_second)
            previous_inside = _inside_clip_edge(previous, clip_first, clip_second)
            if current_inside:
                if not previous_inside:
                    output.append(_line_intersection(previous, current, clip_first, clip_second))
                output.append(current)
            elif previous_inside:
                output.append(_line_intersection(previous, current, clip_first, clip_second))
            previous = current
        subject = output
    return abs(_signed_uv_area(subject)) if len(subject) >= 3 else 0.0


def _uv_overlap_metrics(mesh: bpy.types.Mesh, layer: Any) -> dict[str, Any]:
    """Measure positive-area UV overlap between different source polygons."""

    mesh.calc_loop_triangles()
    triangles: list[tuple[int, list[tuple[float, float]]]] = []
    for triangle in mesh.loop_triangles:
        points = [tuple(float(value) for value in layer.data[index].uv) for index in triangle.loops]
        triangles.append((int(triangle.polygon_index), points))
    pair_tests = len(triangles) * max(0, len(triangles) - 1) // 2
    if len(triangles) > MAX_UV_TRIANGLES or pair_tests > MAX_UV_PAIR_TESTS:
        return {
            "availability": "unavailable",
            "message": (
                f"UV overlap budget exceeded: triangles={len(triangles)} pair_tests={pair_tests}."
            ),
        }
    overlaps = 0
    overlap_area = 0.0
    for index, (left_face, left) in enumerate(triangles):
        for right_face, right in triangles[index + 1 :]:
            if left_face == right_face:
                continue
            area = _triangle_intersection_area(left, right)
            if area > UV_EPSILON:
                overlaps += 1
                overlap_area += area
    return {
        "availability": "available",
        "passed": overlaps == 0,
        "measured_value": overlaps,
        "threshold": 0,
        "message": (
            f"Measured {overlaps} positive-area UV overlap pair(s); "
            f"summed clipped area={overlap_area:.9g}."
        ),
    }


def _tangent_metrics(mesh: bpy.types.Mesh, layer: Any | None) -> dict[str, Any]:
    """Calculate finite unit tangents for every evaluated polygon corner."""

    if layer is None:
        return {
            "availability": "available",
            "passed": False,
            "measured_value": 0,
            "threshold": len(mesh.loops),
            "message": "Tangents cannot exist because UV0 is missing.",
        }
    try:
        mesh.calc_tangents(uvmap=layer.name)
    except RuntimeError as exc:
        return {
            "availability": "unavailable",
            "message": f"Blender tangent calculation failed: {exc}",
        }
    finite = sum(
        _finite_vector(loop.tangent)
        and math.isclose(float(loop.tangent.length), 1.0, abs_tol=1.0e-4)
        for loop in mesh.loops
    )
    return {
        "availability": "available",
        "passed": finite == len(mesh.loops),
        "measured_value": finite,
        "threshold": len(mesh.loops),
        "message": f"Finite unit tangents cover {finite}/{len(mesh.loops)} loops.",
    }


def _has_bound_image_texture(obj: bpy.types.Object) -> bool:
    """Return whether any assigned material binds a concrete Blender image node."""

    for slot in obj.material_slots:
        material = slot.material
        if material is None or not material.use_nodes or material.node_tree is None:
            continue
        if any(
            node.type == "TEX_IMAGE" and getattr(node, "image", None) is not None
            for node in material.node_tree.nodes
        ):
            return True
    return False


def _available(
    check: str,
    passed: bool,
    measured_value: Any,
    threshold: Any,
    message: str,
) -> dict[str, Any]:
    """Build one compact available topology observation."""

    return {
        "check": check,
        "availability": "available",
        "passed": bool(passed),
        "measured_value": measured_value,
        "threshold": threshold,
        "message": message,
    }


def _unavailable(check: str, message: str) -> dict[str, Any]:
    """Build one compact unavailable topology observation."""

    return {"check": check, "availability": "unavailable", "message": message}


def _not_applicable(check: str, message: str) -> dict[str, Any]:
    """Build one explicit not-applicable topology observation."""

    return {"check": check, "availability": "not_applicable", "message": message}


def _object_topology_checks(
    obj: bpy.types.Object,
    mesh: bpy.types.Mesh,
    topology: dict[str, Any],
    world_vertices: list[Vector],
    triangles: list[tuple[int, int, int]],
) -> list[dict[str, Any]]:
    """Inspect all topology-profile checks that are supportable in the authoring blend."""

    non_finite = int(topology["non_finite_vertex_count"])
    degenerate = int(topology["degenerate_face_count"])
    winding = _winding_inconsistency_count(mesh)
    loose = int(topology["loose_edge_count"]) + int(topology["loose_vertex_count"])
    boundary = int(topology["boundary_edge_count"]) + int(topology["overused_edge_count"])
    aspect_values = [
        _triangle_aspect(tuple(world_vertices[index] for index in triangle))
        for triangle in triangles
    ]
    maximum_aspect = max(aspect_values, default=math.inf)
    maximum_sides = max((len(polygon.vertices) for polygon in mesh.polygons), default=0)
    layer = mesh.uv_layers.active if mesh.uv_layers else None
    degenerate_uv = 0
    if layer is not None:
        layer_record = next(item for item in topology["uv_layers"] if item["name"] == layer.name)
        degenerate_uv = int(layer_record["degenerate_face_count"])
    checks = [
        _available("non_finite", non_finite == 0, non_finite, 0, "Finite evaluated vertices."),
        _available("degenerate_face", degenerate == 0, degenerate, 0, "Evaluated face-area check."),
        {"check": "self_intersection", **_bounded_self_intersection(world_vertices, triangles)},
        _available("winding", winding == 0, winding, 0, "Manifold edge traversal consistency."),
        {
            "check": "flipped_normal",
            **_flipped_component_metrics(mesh, world_vertices, triangles, topology),
        },
        _available("loose_geometry", loose == 0, loose, 0, "Loose evaluated vertices and edges."),
        _available(
            "open_boundary", boundary == 0, boundary, 0, "Boundary plus overused edge count."
        ),
        _available(
            "triangle_aspect",
            math.isfinite(maximum_aspect) and maximum_aspect <= 50.0,
            round(maximum_aspect, 9) if math.isfinite(maximum_aspect) else "infinite",
            50.0,
            "Longest-edge to shortest-altitude ratio; static warning threshold=50.",
        ),
        _available(
            "ngon_limit", maximum_sides <= 8, maximum_sides, 8, "Maximum polygon side count."
        ),
        _available(
            "uv0",
            layer is not None and degenerate_uv == 0,
            (0 if layer is None else degenerate_uv),
            0,
            "Active UV0 presence and non-degenerate polygon-corner coverage.",
        ),
    ]
    if layer is None:
        checks.append(_not_applicable("uv_overlap", "UV overlap is not applicable without UV0."))
    else:
        checks.append({"check": "uv_overlap", **_uv_overlap_metrics(mesh, layer)})
    image_bound = _has_bound_image_texture(obj)
    checks.extend(
        [
            (
                _unavailable(
                    "island_padding",
                    "An image texture is bound, but no approved texture-resolution-bound "
                    "island-padding target is available in this inspection.",
                )
                if image_bound
                else _not_applicable(
                    "island_padding",
                    "No image texture is bound, so pixel-padding acceptance is not applicable.",
                )
            ),
            (
                _unavailable(
                    "texel_density",
                    "An image texture is bound, but no approved target texel density "
                    "is bound to this inspection.",
                )
                if image_bound
                else _not_applicable(
                    "texel_density",
                    "No image texture is bound, so pixel-per-meter acceptance is not applicable.",
                )
            ),
            {"check": "tangent", **_tangent_metrics(mesh, layer)},
            (
                _unavailable(
                    "subdivision_pinching",
                    "Subdivision modifiers exist, but pinching needs a dedicated "
                    "curvature reference.",
                )
                if any(modifier.type == "SUBSURF" for modifier in obj.modifiers)
                else _not_applicable("subdivision_pinching", "No subdivision modifier is present.")
            ),
            _not_applicable(
                "lod_silhouette_error", "Authoring blend inspection is not an LOD comparison."
            ),
            _not_applicable(
                "clean_import_normal_preservation",
                "Clean-import normal preservation belongs to V0.7 round-trip evidence.",
            ),
            _not_applicable(
                "clean_import_material_preservation",
                "Clean-import material preservation belongs to V0.7 round-trip evidence.",
            ),
        ]
    )
    return checks


def _aggregate_topology_checks(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate object checks conservatively without turning unavailable evidence into pass."""

    by_check: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in objects:
        for check in record["checks"]:
            by_check[str(check["check"])].append(check)
    results: list[dict[str, Any]] = []
    for check in sorted(by_check):
        values = by_check[check]
        unavailable = [item for item in values if item["availability"] == "unavailable"]
        available = [item for item in values if item["availability"] == "available"]
        if unavailable:
            results.append(
                _unavailable(
                    check,
                    f"{len(unavailable)}/{len(values)} object inspection(s) unavailable: "
                    + " | ".join(item["message"] for item in unavailable[:4]),
                )
            )
            continue
        if not available:
            results.append(
                _not_applicable(check, f"The check is not applicable to all {len(values)} objects.")
            )
            continue
        failed = sum(not bool(item["passed"]) for item in available)
        results.append(
            _available(
                check,
                failed == 0,
                f"failed_objects={failed};scored_objects={len(available)}",
                "all_scored_objects_pass",
                " | ".join(item["message"] for item in available[:4]),
            )
        )
    return results


def _evaluated_evidence(
    object_map: dict[str, list[bpy.types.Object]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Capture per-object topology and combined semantic-family triangle meshes."""

    depsgraph = bpy.context.evaluated_depsgraph_get()
    object_records: list[dict[str, Any]] = []
    family_records: list[dict[str, Any]] = []
    for semantic_id, objects in sorted(object_map.items()):
        family_vertices: list[list[float]] = []
        family_triangles: list[list[int]] = []
        for obj in sorted(objects, key=lambda item: item.name):
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh()
            try:
                mesh.calc_loop_triangles()
                world_vertices = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
                triangles = [
                    tuple(int(value) for value in triangle.vertices)
                    for triangle in mesh.loop_triangles
                ]
                topology = inspect_mesh_topology_data(mesh, evaluated.matrix_world)
                checks = _object_topology_checks(obj, mesh, topology, world_vertices, triangles)
                object_records.append(
                    {
                        "semantic_id": semantic_id,
                        "object_name": obj.name,
                        "instance_index": int(obj.get("cbm_instance_index", 0) or 0),
                        "topology": topology,
                        "checks": checks,
                    }
                )
                offset = len(family_vertices)
                family_vertices.extend(
                    [[round(float(value), 9) for value in vertex] for vertex in world_vertices]
                )
                family_triangles.extend(
                    [[index + offset for index in triangle] for triangle in triangles]
                )
            finally:
                evaluated.to_mesh_clear()
        if not family_vertices or not family_triangles:
            raise RuntimeError(f"{semantic_id}: evaluated semantic mesh is empty")
        minimum = [min(vertex[axis] for vertex in family_vertices) for axis in range(3)]
        maximum = [max(vertex[axis] for vertex in family_vertices) for axis in range(3)]
        family_records.append(
            {
                "object_id": semantic_id,
                "bounds": {"minimum": minimum, "maximum": maximum},
                "vertices_m": family_vertices,
                "triangles": family_triangles,
            }
        )
    return object_records, family_records


def _sample_indices(count: int, limit: int) -> list[int]:
    """Choose stable, evenly spread BVH query vertices."""

    if count <= limit:
        return list(range(count))
    return sorted({min(count - 1, (index * count) // limit) for index in range(limit)})


def _bvh_observation(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """Measure symmetric nearest distance and surface overlap with Blender BVH."""

    try:
        first_vertices = [Vector(value) for value in first["vertices_m"]]
        second_vertices = [Vector(value) for value in second["vertices_m"]]
        first_triangles = [tuple(value) for value in first["triangles"]]
        second_triangles = [tuple(value) for value in second["triangles"]]
        if not first_vertices or not second_vertices or not first_triangles or not second_triangles:
            return {
                "subject_id": first["object_id"],
                "reference_id": second["object_id"],
                "status": "empty",
                "backend": "blender_bvh",
                "bounded_sample_limit": MAX_BVH_SAMPLES,
            }
        first_tree = BVHTree.FromPolygons(first_vertices, first_triangles, all_triangles=True)
        second_tree = BVHTree.FromPolygons(second_vertices, second_triangles, all_triangles=True)
        overlap_count = len(first_tree.overlap(second_tree))
        distances: list[float] = []
        per_direction = max(1, MAX_BVH_SAMPLES // 2)
        first_indices = _sample_indices(len(first_vertices), per_direction)
        second_indices = _sample_indices(len(second_vertices), per_direction)
        for index in first_indices:
            nearest = second_tree.find_nearest(first_vertices[index])
            if nearest is not None:
                distances.append(float(nearest[3]))
        for index in second_indices:
            nearest = first_tree.find_nearest(second_vertices[index])
            if nearest is not None:
                distances.append(float(nearest[3]))
        if not distances:
            raise RuntimeError("Blender BVH returned no nearest-point evidence")
        return {
            "subject_id": first["object_id"],
            "reference_id": second["object_id"],
            "status": "available",
            "backend": "blender_bvh",
            "overlap_triangle_pair_count": overlap_count,
            "minimum_distance_m": round(min(distances), 9),
            "penetration_depth_m": None,
            "sampled_point_count": len(distances),
            "bounded_sample_limit": MAX_BVH_SAMPLES,
        }
    except (IndexError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "subject_id": str(first.get("object_id", "unknown.subject")),
            "reference_id": str(second.get("object_id", "unknown.reference")),
            "status": "evaluation_failure",
            "backend": "blender_bvh",
            "bounded_sample_limit": MAX_BVH_SAMPLES,
            "error": str(exc),
        }


def _assembly_narrow_evidence(
    contract: dict[str, Any], families: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Evaluate each unique declared relation pair with actual Blender BVHs."""

    by_id = {item["object_id"]: item for item in families}
    pairs: set[tuple[str, str]] = set()
    for relation in contract["relationships"]:
        subject = relation.get("subject_id")
        reference = relation.get("reference_id")
        if isinstance(subject, str) and isinstance(reference, str):
            pairs.add(tuple(sorted((subject, reference))))
        peer = relation.get("peer_id")
        if isinstance(subject, str) and isinstance(peer, str):
            pairs.add(tuple(sorted((subject, peer))))
    observations: list[dict[str, Any]] = []
    for first_id, second_id in sorted(pairs):
        first = by_id.get(first_id)
        second = by_id.get(second_id)
        if first is None or second is None:
            observations.append(
                {
                    "subject_id": first_id,
                    "reference_id": second_id,
                    "status": "evaluation_failure",
                    "backend": "blender_bvh",
                    "bounded_sample_limit": MAX_BVH_SAMPLES,
                    "error": "Declared relationship references missing evaluated mesh evidence.",
                }
            )
        else:
            observations.append(_bvh_observation(first, second))
    return observations


def main() -> None:
    """Write read-only, bounded Blender evidence for host-side strict promotion."""

    args = _parse_args()
    job_root = Path(args.job_root).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    modeling_plan_path = _resolve_job_relative(job_root, args.modeling_plan_relative)
    contract = load_assembly_contract(job_root, modeling_plan_path=modeling_plan_path)
    if contract["sha256"] != args.modeling_plan_sha256:
        raise RuntimeError("Loaded ModelingPlan hash differs from the exact host binding")
    object_map = _semantic_object_map()
    object_records, families = _evaluated_evidence(object_map)
    assembly_evaluation = evaluate_assembly_relationships(contract, object_map)
    payload = {
        "schema_version": "0.1.0",
        "kind": "static_prop_authoring_companion_snapshot",
        "blender_version": bpy.app.version_string,
        "source_hashes": {
            "scene_spec": args.scene_spec_sha256,
            "modeling_plan": args.modeling_plan_sha256,
            "blend": args.blend_sha256,
        },
        "topology": {
            "profile": "static_prop_closed",
            "objects": object_records,
            "observations": _aggregate_topology_checks(object_records),
            "limits": {
                "self_intersection_triangles": MAX_SELF_INTERSECTION_TRIANGLES,
                "uv_triangles": MAX_UV_TRIANGLES,
                "uv_pair_tests": MAX_UV_PAIR_TESTS,
            },
        },
        "assembly": {
            "policy": contract["policy"],
            "meshes": families,
            "narrow_observations": _assembly_narrow_evidence(contract, families),
            "relationship_evaluation": assembly_evaluation,
            "limitations": [
                "BVH overlap is surface-intersection evidence, not signed penetration depth.",
                "Evaluated bounds and meshes do not prove mechanism motion or hidden "
                "structure truth.",
            ],
        },
    }
    write_json(output, payload)
    print(f"CBM_STATIC_PROP_COMPANION_OK output={output}")


if __name__ == "__main__":
    main()
