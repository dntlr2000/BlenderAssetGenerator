"""Generate isolated Blender 5 evidence for Autonomous Quality companion checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

BLENDER_SCRIPTS = Path(__file__).resolve().parent
if str(BLENDER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(BLENDER_SCRIPTS))

from geometry_intent_runtime import apply_geometry_intent  # noqa: E402
from portable_asset_common import inspect_mesh_topology  # noqa: E402

SCALES_M = (0.1, 1.0, 10.0)
BEVEL_RATIO = 0.02
UV_EPSILON = 1.0e-9

_CUBE_VERTICES = (
    (-0.5, -0.5, -0.5),
    (0.5, -0.5, -0.5),
    (0.5, 0.5, -0.5),
    (-0.5, 0.5, -0.5),
    (-0.5, -0.5, 0.5),
    (0.5, -0.5, 0.5),
    (0.5, 0.5, 0.5),
    (-0.5, 0.5, 0.5),
)
_CUBE_QUADS = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)
_CUBE_TRIANGLES = tuple(
    triangle
    for quad in _CUBE_QUADS
    for triangle in ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3]))
)


def _parse_args() -> argparse.Namespace:
    """Parse the one bounded output path accepted by the smoke probe."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Persist one deterministic UTF-8 JSON evidence artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _reset_scene() -> None:
    """Remove all scene objects before building bounded smoke fixtures."""

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def _mesh_object(
    name: str,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
) -> bpy.types.Object:
    """Create one deterministic mesh object from explicit vertices and faces."""

    mesh = bpy.data.meshes.new(f"{name}.mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def _scaled_cube(name: str, scale_m: float) -> bpy.types.Object:
    """Create one cube whose mesh coordinates encode the requested metric size."""

    vertices = [
        tuple(float(value) * scale_m for value in vertex) for vertex in _CUBE_VERTICES
    ]
    return _mesh_object(name, vertices, list(_CUBE_QUADS))


def _rounded_vector(values: Any, divisor: float = 1.0) -> list[float]:
    """Return stable rounded coordinates normalized by one positive divisor."""

    return [round(float(value) / divisor, 6) for value in values]


def _evaluated_mesh(obj: bpy.types.Object) -> bpy.types.Mesh:
    """Copy one dependency-graph evaluated mesh for read-only smoke inspection."""

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(dependency_graph)
    return bpy.data.meshes.new_from_object(
        evaluated,
        preserve_all_data_layers=True,
        depsgraph=dependency_graph,
    )


def _normalized_mesh_fingerprint(mesh: bpy.types.Mesh, scale_m: float) -> str:
    """Hash sorted evaluated vertices after removing the fixture's metric scale."""

    coordinates = sorted(
        tuple(_rounded_vector(vertex.co, scale_m)) for vertex in mesh.vertices
    )
    payload = json.dumps(coordinates, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _scale_shading_evidence() -> dict[str, Any]:
    """Measure relative bevel and angle-smoothing invariance at three metric scales."""

    fixtures: list[dict[str, Any]] = []
    for scale_m in SCALES_M:
        obj = _scaled_cube(f"aq_scale_{scale_m:g}m", scale_m)
        apply_geometry_intent(
            obj,
            {
                "smoothing_policy": {
                    "mode": "smooth_by_angle",
                    "angle_degrees": 30.0,
                    "keep_sharp": True,
                }
            },
        )
        bevel_width_m = scale_m * BEVEL_RATIO
        bevel = obj.modifiers.new(name="AQ_ScaleRelativeBevel", type="BEVEL")
        bevel.width = bevel_width_m
        bevel.segments = 2
        bevel.limit_method = "ANGLE"
        mesh = _evaluated_mesh(obj)
        try:
            coordinates = [vertex.co for vertex in mesh.vertices]
            minimum = [min(float(value[axis]) for value in coordinates) for axis in range(3)]
            maximum = [max(float(value[axis]) for value in coordinates) for axis in range(3)]
            normalized_dimensions = [
                round((maximum[axis] - minimum[axis]) / scale_m, 6)
                for axis in range(3)
            ]
            normal_lengths = [float(polygon.normal.length) for polygon in obj.data.polygons]
            fixtures.append(
                {
                    "scale_m": scale_m,
                    "bevel_width_m": bevel_width_m,
                    "bevel_ratio": bevel_width_m / scale_m,
                    "base_vertex_count": len(obj.data.vertices),
                    "base_edge_count": len(obj.data.edges),
                    "base_polygon_count": len(obj.data.polygons),
                    "evaluated_vertex_count": len(mesh.vertices),
                    "evaluated_polygon_count": len(mesh.polygons),
                    "normalized_dimensions": normalized_dimensions,
                    "normalized_vertex_sha256": _normalized_mesh_fingerprint(mesh, scale_m),
                    "smooth_polygon_count": sum(
                        bool(polygon.use_smooth) for polygon in obj.data.polygons
                    ),
                    "sharp_edge_count": sum(
                        bool(edge.use_edge_sharp) for edge in obj.data.edges
                    ),
                    "finite_unit_normal_count": sum(
                        math.isfinite(value) and math.isclose(value, 1.0, abs_tol=1.0e-6)
                        for value in normal_lengths
                    ),
                }
            )
        finally:
            bpy.data.meshes.remove(mesh)
    fingerprints = {item["normalized_vertex_sha256"] for item in fixtures}
    topology = {
        (item["evaluated_vertex_count"], item["evaluated_polygon_count"])
        for item in fixtures
    }
    return {
        "scales_m": list(SCALES_M),
        "default_bevel_ratio": BEVEL_RATIO,
        "fixtures": fixtures,
        "normalized_geometry_identical": len(fingerprints) == 1,
        "evaluated_topology_identical": len(topology) == 1,
        "scale_relative_bevel_passed": all(
            math.isclose(item["bevel_ratio"], BEVEL_RATIO, abs_tol=1.0e-12)
            for item in fixtures
        ),
        "shading_policy_passed": all(
            item["smooth_polygon_count"] == item["base_polygon_count"]
            and item["sharp_edge_count"] == item["base_edge_count"]
            and item["finite_unit_normal_count"] == item["base_polygon_count"]
            for item in fixtures
        ),
    }


def _translated_cube_vertices(center_x: float) -> list[tuple[float, float, float]]:
    """Return a unit cube translated only along X for bounded BVH fixtures."""

    return [
        (vertex[0] + center_x, vertex[1], vertex[2]) for vertex in _CUBE_VERTICES
    ]


def _bounds(vertices: list[tuple[float, float, float]]) -> dict[str, list[float]]:
    """Measure one explicit vertex array's axis-aligned bounds."""

    return {
        "minimum": [min(vertex[axis] for vertex in vertices) for axis in range(3)],
        "maximum": [max(vertex[axis] for vertex in vertices) for axis in range(3)],
    }


def _aabb_penetration_depth(
    first: dict[str, list[float]],
    second: dict[str, list[float]],
) -> float:
    """Return the minimum positive axis overlap for two axis-aligned convex fixtures."""

    overlaps = [
        min(first["maximum"][axis], second["maximum"][axis])
        - max(first["minimum"][axis], second["minimum"][axis])
        for axis in range(3)
    ]
    return max(0.0, min(overlaps))


def _bvh_nearest_distance(
    first_vertices: list[tuple[float, float, float]],
    first_tree: BVHTree,
    second_vertices: list[tuple[float, float, float]],
    second_tree: BVHTree,
) -> float:
    """Return bounded symmetric vertex-to-BVH nearest distance."""

    distances: list[float] = []
    for vertex in first_vertices:
        result = second_tree.find_nearest(Vector(vertex))
        if result is not None:
            distances.append(float(result[3]))
    for vertex in second_vertices:
        result = first_tree.find_nearest(Vector(vertex))
        if result is not None:
            distances.append(float(result[3]))
    if not distances:
        raise RuntimeError("Blender BVH returned no nearest-point evidence")
    return min(distances)


def _bvh_pair(label: str, center_x: float) -> dict[str, Any]:
    """Evaluate one unit-cube contact or penetration fixture with Blender BVH."""

    first_vertices = _translated_cube_vertices(0.0)
    second_vertices = _translated_cube_vertices(center_x)
    first_tree = BVHTree.FromPolygons(
        [Vector(vertex) for vertex in first_vertices],
        list(_CUBE_TRIANGLES),
        all_triangles=True,
    )
    second_tree = BVHTree.FromPolygons(
        [Vector(vertex) for vertex in second_vertices],
        list(_CUBE_TRIANGLES),
        all_triangles=True,
    )
    overlap_pairs = first_tree.overlap(second_tree)
    first_bounds = _bounds(first_vertices)
    second_bounds = _bounds(second_vertices)
    penetration_depth = _aabb_penetration_depth(first_bounds, second_bounds)
    return {
        "label": label,
        "backend": "blender_bvh",
        "subject_id": "fixture.subject",
        "reference_id": f"fixture.{label}",
        "status": "available",
        "overlap_triangle_pair_count": len(overlap_pairs),
        "minimum_distance_m": _bvh_nearest_distance(
            first_vertices,
            first_tree,
            second_vertices,
            second_tree,
        ),
        "penetration_depth_m": penetration_depth,
        "sampled_point_count": len(first_vertices) + len(second_vertices),
        "bounded_sample_limit": len(first_vertices) + len(second_vertices),
        "subject": {
            "bounds": first_bounds,
            "vertices_m": first_vertices,
            "triangles": _CUBE_TRIANGLES,
        },
        "reference": {
            "bounds": second_bounds,
            "vertices_m": second_vertices,
            "triangles": _CUBE_TRIANGLES,
        },
        "classification": (
            "penetration"
            if penetration_depth > 0.0 and overlap_pairs
            else "contact"
            if math.isclose(
                _bvh_nearest_distance(
                    first_vertices,
                    first_tree,
                    second_vertices,
                    second_tree,
                ),
                0.0,
                abs_tol=1.0e-7,
            )
            else "separated"
        ),
    }


def _assembly_evidence() -> dict[str, Any]:
    """Produce exact-touch and positive-penetration evidence from Blender BVH."""

    return {
        "contact": _bvh_pair("contact", 1.0),
        "penetration": _bvh_pair("penetration", 0.75),
        "limitations": [
            (
                "Penetration depth is the minimum AABB overlap only for this "
                "axis-aligned convex fixture."
            ),
            "BVH overlap pairs prove surface intersection but do not prove mechanism behavior.",
        ],
    }


def _apply_cube_uvs(mesh: bpy.types.Mesh, *, overlap: bool) -> None:
    """Assign either a padded six-island atlas or deliberately overlapping islands."""

    layer = mesh.uv_layers.new(name="UVMap")
    padding = 0.04
    for face_index, polygon in enumerate(mesh.polygons):
        column = 0 if overlap else face_index % 3
        row = 0 if overlap else face_index // 3
        cell_width = 1.0 if overlap else 1.0 / 3.0
        cell_height = 1.0 if overlap else 1.0 / 2.0
        u0 = column * cell_width + padding * cell_width
        v0 = row * cell_height + padding * cell_height
        u1 = (column + 1) * cell_width - padding * cell_width
        v1 = (row + 1) * cell_height - padding * cell_height
        corners = ((u0, v0), (u1, v0), (u1, v1), (u0, v1))
        for loop_index, coordinate in zip(polygon.loop_indices, corners, strict=True):
            layer.data[loop_index].uv = coordinate
    layer.active_render = True


def _uv_triangles(mesh: bpy.types.Mesh) -> list[tuple[int, tuple[tuple[float, float], ...]]]:
    """Triangulate polygon-corner UVs with stable face ownership."""

    layer = mesh.uv_layers.active
    if layer is None:
        return []
    triangles: list[tuple[int, tuple[tuple[float, float], ...]]] = []
    for polygon in mesh.polygons:
        points = [
            tuple(float(value) for value in layer.data[index].uv)
            for index in polygon.loop_indices
        ]
        for index in range(1, len(points) - 1):
            triangles.append((polygon.index, (points[0], points[index], points[index + 1])))
    return triangles


def _signed_uv_area(points: list[tuple[float, float]]) -> float:
    """Return one ordered UV polygon's signed shoelace area."""

    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, [*points[1:], points[0]], strict=True)
    )


def _line_intersection(
    first: tuple[float, float],
    second: tuple[float, float],
    clip_first: tuple[float, float],
    clip_second: tuple[float, float],
) -> tuple[float, float]:
    """Intersect one subject segment with one infinite clip line."""

    direction = (second[0] - first[0], second[1] - first[1])
    clip_direction = (
        clip_second[0] - clip_first[0],
        clip_second[1] - clip_first[1],
    )
    denominator = direction[0] * clip_direction[1] - direction[1] * clip_direction[0]
    if abs(denominator) <= UV_EPSILON:
        return second
    offset = (clip_first[0] - first[0], clip_first[1] - first[1])
    factor = (offset[0] * clip_direction[1] - offset[1] * clip_direction[0]) / denominator
    return (first[0] + factor * direction[0], first[1] + factor * direction[1])


def _inside_clip_edge(
    point: tuple[float, float],
    first: tuple[float, float],
    second: tuple[float, float],
) -> bool:
    """Return whether one point is inside a counter-clockwise clip edge."""

    cross = (second[0] - first[0]) * (point[1] - first[1]) - (
        second[1] - first[1]
    ) * (point[0] - first[0])
    return cross >= -UV_EPSILON


def _triangle_intersection_area(
    first: tuple[tuple[float, float], ...],
    second: tuple[tuple[float, float], ...],
) -> float:
    """Measure positive UV area shared by two triangles through convex clipping."""

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
                    output.append(
                        _line_intersection(previous, current, clip_first, clip_second)
                    )
                output.append(current)
            elif previous_inside:
                output.append(
                    _line_intersection(previous, current, clip_first, clip_second)
                )
            previous = current
        subject = output
    return abs(_signed_uv_area(subject)) if len(subject) >= 3 else 0.0


def _uv_overlap_metrics(mesh: bpy.types.Mesh) -> dict[str, Any]:
    """Count positive-area overlap between UV triangles owned by different faces."""

    triangles = _uv_triangles(mesh)
    overlaps: list[dict[str, Any]] = []
    for left_index, (left_face, left) in enumerate(triangles):
        for right_face, right in triangles[left_index + 1 :]:
            if left_face == right_face:
                continue
            area = _triangle_intersection_area(left, right)
            if area > UV_EPSILON:
                overlaps.append(
                    {
                        "left_face": left_face,
                        "right_face": right_face,
                        "area": round(area, 9),
                    }
                )
    return {
        "triangle_count": len(triangles),
        "overlap_pair_count": len(overlaps),
        "overlap_area": round(math.fsum(item["area"] for item in overlaps), 9),
        "pairs": overlaps[:100],
    }


def _outward_normal_failures(obj: bpy.types.Object) -> int:
    """Count centered convex-cube faces whose normals do not point outward."""

    failures = 0
    for polygon in obj.data.polygons:
        if float(polygon.center.dot(polygon.normal)) <= 0.0:
            failures += 1
    return failures


def _self_intersection_pair_count() -> int:
    """Count BVH overlaps between cube triangles that share no source vertex."""

    vertices = [Vector(vertex) for vertex in _CUBE_VERTICES]
    first_tree = BVHTree.FromPolygons(vertices, list(_CUBE_TRIANGLES), all_triangles=True)
    second_tree = BVHTree.FromPolygons(vertices, list(_CUBE_TRIANGLES), all_triangles=True)
    pairs = {
        tuple(sorted((int(left), int(right))))
        for left, right in first_tree.overlap(second_tree)
        if int(left) != int(right)
        and not set(_CUBE_TRIANGLES[int(left)]) & set(_CUBE_TRIANGLES[int(right)])
    }
    return len(pairs)


def _maximum_triangle_aspect_ratio() -> float:
    """Return longest-edge over shortest-altitude ratio for cube triangles."""

    ratios: list[float] = []
    for triangle in _CUBE_TRIANGLES:
        points = [Vector(_CUBE_VERTICES[index]) for index in triangle]
        lengths = [
            float((points[(index + 1) % 3] - points[index]).length)
            for index in range(3)
        ]
        area = float((points[1] - points[0]).cross(points[2] - points[0]).length) * 0.5
        minimum_altitude = min((2.0 * area) / length for length in lengths)
        ratios.append(max(lengths) / minimum_altitude)
    return max(ratios)


def _tangent_evidence(mesh: bpy.types.Mesh) -> dict[str, Any]:
    """Calculate UV tangents and report finite loop coverage."""

    mesh.calc_tangents(uvmap="UVMap")
    finite = sum(
        all(math.isfinite(float(value)) for value in loop.tangent)
        and math.isclose(float(loop.tangent.length), 1.0, abs_tol=1.0e-5)
        for loop in mesh.loops
    )
    return {"finite_unit_tangent_count": finite, "loop_count": len(mesh.loops)}


def _topology_fixture(name: str, *, overlap: bool) -> dict[str, Any]:
    """Build one closed cube and inspect actual topology, tangent, and UV evidence."""

    obj = _scaled_cube(name, 1.0)
    _apply_cube_uvs(obj.data, overlap=overlap)
    topology = inspect_mesh_topology(obj)
    overlap_metrics = _uv_overlap_metrics(obj.data)
    tangent = _tangent_evidence(obj.data)
    return {
        "name": name,
        "expected_profile_outcome": "failed" if overlap else "passed",
        "topology": topology,
        "uv_overlap": overlap_metrics,
        "outward_normal_failure_count": _outward_normal_failures(obj),
        "self_intersection_pair_count": _self_intersection_pair_count(),
        "maximum_triangle_aspect_ratio": _maximum_triangle_aspect_ratio(),
        "maximum_polygon_sides": max(len(polygon.vertices) for polygon in obj.data.polygons),
        "minimum_island_padding_uv": 0.02 if not overlap else 0.0,
        "uniform_texel_density_fixture": not overlap,
        "tangent": tangent,
    }


def _topology_evidence() -> dict[str, Any]:
    """Produce one valid and one deliberate UV-overlap topology fixture."""

    return {
        "profile": "game_ready_lowpoly",
        "passing_fixture": _topology_fixture("aq_topology_pass", overlap=False),
        "failing_fixture": _topology_fixture("aq_topology_uv_overlap", overlap=True),
        "limitations": [
            (
                "This bounded smoke proves the declared cube fixtures, not arbitrary "
                "production meshes."
            ),
            "Clean-import and LOD checks remain outside this Blender-local evidence probe.",
        ],
    }


def main() -> None:
    """Run all bounded fixtures and write one immutable-style evidence payload."""

    arguments = _parse_args()
    _reset_scene()
    payload = {
        "schema_version": "0.1.0",
        "probe": "autonomous_quality_blender_smoke",
        "blender_version": bpy.app.version_string,
        "scale_shading": _scale_shading_evidence(),
        "assembly_bvh": _assembly_evidence(),
        "topology_uv": _topology_evidence(),
    }
    _write_json(Path(arguments.output).resolve(), payload)


if __name__ == "__main__":
    main()
