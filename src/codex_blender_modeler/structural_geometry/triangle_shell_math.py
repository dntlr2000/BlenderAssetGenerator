"""Standard-library validation shared by the strict host model and fixed Blender builder."""

from __future__ import annotations

import math
from collections import defaultdict


def _cross(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, float, float]:
    """Return a triangle cross product without importing host or Blender libraries."""
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _connected(graph: dict[int, set[int]]) -> bool:
    """Check one explicitly enumerated adjacency graph in linear time."""
    if not graph:
        return False
    pending = [next(iter(graph))]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(graph[current] - seen)
    return len(seen) == len(graph)


def _vectors(value: object, width: int, minimum: int, maximum: int) -> None:
    """Validate finite bounded vector arrays without coercing strings or booleans."""
    if not isinstance(value, (list, tuple)) or not minimum <= len(value) <= maximum:
        raise ValueError("triangulated shell vector array has invalid cardinality")
    for vector in value:
        if not isinstance(vector, (list, tuple)) or len(vector) != width:
            raise ValueError("triangulated shell vector has invalid dimensions")
        for coordinate in vector:
            if (
                isinstance(coordinate, bool)
                or not isinstance(coordinate, (int, float))
                or not -1.0e6 <= coordinate <= 1.0e6
                or not math.isfinite(coordinate)
            ):
                raise ValueError("triangulated shell coordinates must be finite bounded numbers")


def validate_triangle_shell_data(geometry: object) -> None:
    """Reject malformed data and non-closed, degenerate, disconnected or inward shells."""
    if not isinstance(geometry, dict):
        raise ValueError("triangulated shell requires an explicit data object")
    if (
        set(geometry) - {"kind", "vertices", "triangles", "loop_uvs"}
        or geometry.get("kind") != "triangulated_shell"
    ):
        raise ValueError("triangulated shell contains an unknown field or kind")
    vertices = geometry.get("vertices")
    triangles = geometry.get("triangles")
    loop_uvs = geometry.get("loop_uvs")
    _vectors(vertices, 3, 4, 65536)
    if not isinstance(triangles, (list, tuple)) or not 4 <= len(triangles) <= 131072:
        raise ValueError("triangulated shell triangle array has invalid cardinality")
    if loop_uvs is not None:
        _vectors(loop_uvs, 2, 12, 393216)
        if len(loop_uvs) != 3 * len(triangles):
            raise ValueError("triangulated shell loop_uvs must match every triangle corner")
    if len({tuple(vertex) for vertex in vertices}) != len(vertices):
        raise ValueError("triangulated shell contains coincident vertex positions")
    count = len(vertices)
    edges: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    links: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    faces: set[tuple[int, ...]] = set()
    used: set[int] = set()
    volumes: list[float] = []
    origin = vertices[0]
    for face_index, face in enumerate(triangles):
        if (
            not isinstance(face, (list, tuple))
            or len(face) != 3
            or any(type(index) is not int or not 0 <= index < count for index in face)
            or len(set(face)) != 3
        ):
            raise ValueError("triangulated shell triangle has invalid or repeated indices")
        key = tuple(sorted(face))
        if key in faces:
            raise ValueError("triangulated shell repeats a triangle")
        faces.add(key)
        used.update(face)
        first, second, third = (vertices[index] for index in face)
        ab = tuple(second[axis] - first[axis] for axis in range(3))
        ac = tuple(third[axis] - first[axis] for axis in range(3))
        normal = _cross(ab, ac)
        if math.fsum(value * value for value in normal) <= 4.0e-28:
            raise ValueError("triangulated shell triangle has zero or sub-tolerance area")
        offset = tuple(first[axis] - origin[axis] for axis in range(3))
        volumes.append(math.fsum(offset[axis] * normal[axis] for axis in range(3)))
        for index in range(3):
            a, b, c = face[index], face[(index + 1) % 3], face[(index + 2) % 3]
            edge = (min(a, b), max(a, b))
            edges[edge].append((face_index, 1 if a < b else -1))
            links[a][b].add(c)
            links[a][c].add(b)
    if len(used) != count:
        raise ValueError("triangulated shell contains unused vertices")
    adjacency: dict[int, set[int]] = {index: set() for index in range(len(triangles))}
    for entries in edges.values():
        if len(entries) != 2 or entries[0][1] + entries[1][1] != 0:
            raise ValueError("triangulated shell requires two oppositely wound faces per edge")
        first, second = entries[0][0], entries[1][0]
        adjacency[first].add(second)
        adjacency[second].add(first)
    if not _connected(adjacency):
        raise ValueError("triangulated shell must contain one connected surface")
    for link in links.values():
        if any(len(neighbors) != 2 for neighbors in link.values()) or not _connected(link):
            raise ValueError("triangulated shell has a non-manifold vertex link")
    if math.fsum(volumes) <= 0.0:
        raise ValueError("triangulated shell must have positive outward signed volume")
