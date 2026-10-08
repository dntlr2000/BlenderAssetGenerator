"""Independent native mesh/triangle evidence for the fixed helper smoke fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_blender_modeler.blender_scripts.self_intersection_runtime import (  # noqa: E402
    bounded_self_intersection,
)


def main():
    """Inspect saved native geometry without mutating it or invoking host helper code."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expect-intersections", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    bpy.ops.wm.open_mainfile(filepath=args.blend)
    objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    results = []
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        vertices = [tuple(vertex.co) for vertex in mesh.vertices]
        triangles = [tuple(triangle.vertices) for triangle in mesh.loop_triangles]
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.normal_update()
        edge_defects = sum(not edge.is_manifold or not edge.is_contiguous for edge in bm.edges)
        vertex_defects = sum(not vertex.is_manifold for vertex in bm.verts)
        volume = bm.calc_volume(signed=True)
        bm.free()
        proof = bounded_self_intersection(
            vertices, triangles, max_triangles=4092, max_pair_tests=65536
        )
        tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True, epsilon=0.0)
        overlaps = sorted(
            set(tuple(sorted(pair)) for pair in tree.overlap(tree) if pair[0] != pair[1])
        )
        results.append(
            {
                "name": obj.name,
                "vertices": len(vertices),
                "triangles": len(triangles),
                "nonmanifold_or_noncontiguous_edges": edge_defects,
                "nonmanifold_vertices": vertex_defects,
                "signed_volume": volume,
                "exact_native_intersection": proof,
                "bvh_candidate_pairs": len(overlaps),
                "triangle_min_area": min(t.area for t in mesh.loop_triangles),
            }
        )
        assert edge_defects == vertex_defects == 0 and volume > 0
        assert proof["availability"] == "available"
        assert proof["passed"] is not args.expect_intersections
    assert objects and tuple(bpy.app.version) == (5, 0, 1)
    Path(args.output).write_text(
        json.dumps({"blender_version": bpy.app.version_string, "objects": results}, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
