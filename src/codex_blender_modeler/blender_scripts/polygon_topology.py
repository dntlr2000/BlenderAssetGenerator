"""Native polygon diagnostics and tessellation-preserving derived serialization."""

import math
import sys
from pathlib import Path

# Native inventory/export scripts may start without host package paths or PYTHONPATH.
SOURCE_ROOT = str(Path(__file__).resolve().parents[2])
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

from codex_blender_modeler.structural_geometry.polygon_shell_math import (  # noqa: E402
    topology_statistics,
    triangle_view,
)


def mesh_triangle_view(mesh):
    """Capture actual Blender corner triangulation without modifying authored polygons."""
    mesh.calc_loop_triangles()
    vertices = [list(v.co) for v in mesh.vertices]
    faces = [list(p.vertices) for p in mesh.polygons]
    loops = [list(t.loops) for t in mesh.loop_triangles]
    return triangle_view(vertices, faces, loops)


def mesh_topology_statistics(mesh):
    """Count native polygons separately from evaluated tessellation, including n-gons."""
    mesh.calc_loop_triangles()
    faces = [list(p.vertices) for p in mesh.polygons]
    if faces and all(len(face) in (3, 4) for face in faces):
        return topology_statistics([list(v.co) for v in mesh.vertices], faces,
                                   [list(t.loops) for t in mesh.loop_triangles])
    areas = [float(p.area) for p in mesh.polygons]
    quads = [p.index for p in mesh.polygons if len(p.vertices) == 4]
    return {
        "face_count": len(faces), "triangle_faces": sum(len(f) == 3 for f in faces),
        "quad_faces": len(quads), "ngon_faces": sum(len(f) > 4 for f in faces),
        "quad_face_ratio": len(quads) / len(faces) if faces else 0.,
        "quad_area_ratio": math.fsum(areas[i] for i in quads) / math.fsum(areas)
        if math.fsum(areas) else 0.,
        "expanded_triangles": len(mesh.loop_triangles),
        "degenerate_faces": sum(a <= 1e-14 for a in areas),
        "maximum_quad_warp_degrees": None,
    }


def object_topology_statistics(obj):
    """Inspect base and evaluated meshes independently, releasing the evaluated temporary."""
    import bpy

    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return {"authored": mesh_topology_statistics(obj.data),
                "evaluated": mesh_topology_statistics(mesh)}
    finally:
        evaluated.to_mesh_clear()


def triangulate_preserving_tessellation(editable, mesh, faces):
    """Triangulate a disposable bmesh with each native quad diagonal, preserving loop data."""
    import bmesh

    mesh.calc_loop_triangles()
    expected = {}
    for tri in mesh.loop_triangles:
        expected.setdefault(tri.polygon_index, set()).add(frozenset(tri.vertices))
    for face in faces:
        if len(face.verts) != 4:
            raise ValueError("polygon-shell serialization expects triangles and quads")
        ids = [v.index for v in face.verts]
        original = expected[face.index]
        method = "FIXED" if frozenset(ids[:3]) in original else "FIXED_ALTERNATE"
        result = bmesh.ops.triangulate(editable, faces=[face], quad_method=method)
        actual = {frozenset(v.index for v in t.verts) for t in result["faces"]}
        if actual != original:
            raise ValueError("native quad tessellation changed during serialization")
