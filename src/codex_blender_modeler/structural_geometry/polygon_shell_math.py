"""Bounded polygon authoring and reversible triangle views without Blender dependencies."""

from __future__ import annotations

import math

from .triangle_shell_math import _cross, _vectors, validate_triangle_shell_data


def triangle_view(vertices, faces, loop_triangles=None):
    """Map oriented triangle corners to original polygons without changing authoring data."""
    if not isinstance(faces, (list, tuple)) or not 1 <= len(faces) <= 131072:
        raise ValueError("polygon face count exceeds limits")
    offsets, cursor = [], 0
    for face in faces:
        if (
            not isinstance(face, (list, tuple)) or len(face) not in (3, 4)
            or any(type(i) is not int or not 0 <= i < len(vertices) for i in face)
            or len(set(face)) != len(face)
        ):
            raise ValueError("polygon faces require three or four distinct valid indices")
        offsets.append(cursor)
        cursor += len(face)
    if sum(len(face) - 2 for face in faces) > 131072:
        raise ValueError("polygon expanded triangle count exceeds limits")
    owner = [i for i, face in enumerate(faces) for _ in face]
    corners = [v for face in faces for v in face]
    if loop_triangles is None:
        loop_triangles = [
            [offset, offset + j, offset + j + 1]
            for offset, face in zip(offsets, faces, strict=True)
            for j in range(1, len(face) - 1)
        ]
    if not isinstance(loop_triangles, (list, tuple)) or len(loop_triangles) != sum(
        len(face) - 2 for face in faces
    ):
        raise ValueError("triangle view has missing or extra triangles")
    groups = [[] for _ in faces]
    for tri in loop_triangles:
        if (
            not isinstance(tri, (list, tuple)) or len(tri) != 3
            or any(type(i) is not int or not 0 <= i < cursor for i in tri)
            or len(set(tri)) != 3 or len({owner[i] for i in tri}) != 1
        ):
            raise ValueError("triangle view contains invalid or cross-polygon corners")
        groups[owner[tri[0]]].append(tuple(i - offsets[owner[tri[0]]] for i in tri))
    for face, group in zip(faces, groups, strict=True):
        normalized = sorted(min(t[k:] + t[:k] for k in range(3)) for t in group)
        choices = [[(0, 1, 2)]] if len(face) == 3 else [
            [(0, 1, 2), (0, 2, 3)], [(0, 1, 3), (1, 2, 3)]
        ]
        if normalized not in choices:
            raise ValueError("triangle view changes winding or polygon coverage")
    return {
        "triangles": [[corners[i] for i in tri] for tri in loop_triangles],
        "polygon_indices": [owner[tri[0]] for tri in loop_triangles],
        "loop_indices": [list(tri) for tri in loop_triangles],
    }


def validate_polygon_shell_data(geometry):
    """Validate a closed oriented mixed shell while retaining every authored polygon."""
    if not isinstance(geometry, dict) or geometry.get("kind") != "polygon_shell" or (
        set(geometry) - {"kind", "vertices", "faces", "loop_uvs"}
    ):
        raise ValueError("polygon shell contains an unknown field or kind")
    vertices, faces = geometry.get("vertices"), geometry.get("faces")
    _vectors(vertices, 3, 4, 65536)
    view = triangle_view(vertices, faces)
    for face in faces:
        if len(face) != 4:
            continue
        points = [vertices[i] for i in face]
        normals = []
        for i in range(4):
            a, b, c = points[i], points[(i + 1) % 4], points[(i + 2) % 4]
            normals.append(_cross(tuple(b[k] - a[k] for k in range(3)),
                                  tuple(c[k] - b[k] for k in range(3))))
        average = tuple(math.fsum(n[k] for n in normals) for k in range(3))
        if any(sum(n[k] * average[k] for k in range(3)) <= 0 for n in normals):
            raise ValueError("polygon shell quad is concave, crossed or degenerate")
    uvs = geometry.get("loop_uvs")
    if uvs is not None:
        _vectors(uvs, 2, 12, 393216)
        if len(uvs) != sum(map(len, faces)):
            raise ValueError("polygon shell UV count differs from authored corners")
    validate_triangle_shell_data({
        "kind": "triangulated_shell", "vertices": vertices, "triangles": view["triangles"],
        "loop_uvs": None if uvs is None else [uvs[i] for t in view["loop_indices"] for i in t],
    })


def topology_statistics(vertices, faces, loop_triangles=None):
    """Report base or evaluated face composition and quad warp without a quality score."""
    view = triangle_view(vertices, faces, loop_triangles)
    areas = [0.0] * len(faces)
    normals = [[] for _ in faces]
    for triangle, polygon in zip(view["triangles"], view["polygon_indices"], strict=True):
        a, b, c = [vertices[i] for i in triangle]
        n = _cross(tuple(b[k] - a[k] for k in range(3)),
                   tuple(c[k] - a[k] for k in range(3)))
        length = math.sqrt(sum(x * x for x in n))
        areas[polygon] += length / 2
        normals[polygon].append(tuple(x / length for x in n) if length else (0., 0., 0.))
    quads = [i for i, f in enumerate(faces) if len(f) == 4]
    edges = {}
    for face in faces:
        for a, b in zip(face, [*face[1:], face[0]], strict=True):
            edges.setdefault(tuple(sorted((a, b))), []).append(1 if a < b else -1)
    total = math.fsum(areas)
    warp = [math.degrees(math.acos(max(-1., min(1., sum(a*b for a, b in zip(
        normals[i][0], normals[i][1], strict=True)))))) for i in quads]
    origin = vertices[0]
    volumes = []
    for triangle in view["triangles"]:
        a, b, c = [tuple(vertices[i][k] - origin[k] for k in range(3)) for i in triangle]
        normal = _cross(b, c)
        volumes.append(sum(a[k] * normal[k] for k in range(3)) / 6)
    return {
        "face_count": len(faces), "triangle_faces": len(faces) - len(quads),
        "quad_faces": len(quads), "ngon_faces": 0,
        "quad_face_ratio": len(quads) / len(faces),
        "quad_area_ratio": math.fsum(areas[i] for i in quads) / total if total else 0.,
        "surface_area": total, "expanded_triangles": len(view["triangles"]),
        "degenerate_faces": sum(a <= 1e-14 for a in areas),
        "boundary_edges": sum(len(values) == 1 for values in edges.values()),
        "non_manifold_edges": sum(len(values) > 2 for values in edges.values()),
        "edge_winding_conflicts": sum(
            len(values) == 2 and sum(values) != 0 for values in edges.values()
        ),
        "signed_volume": math.fsum(volumes),
        "closed_outward_orientation": (math.fsum(volumes) > 0
            and all(sum(values) == 0 for values in edges.values())
            if all(len(values) == 2 for values in edges.values()) else None),
        "maximum_quad_warp_degrees": max(warp, default=0.),
    }
