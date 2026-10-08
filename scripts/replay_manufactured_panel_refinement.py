"""Replay a strict, bounded manufactured-prop refinement as BAG MeshPayload v0.2 staging.
The public data contract cannot execute code, scripts, callbacks or node graphs.
"""

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy


def sha(path):
    """Hash exact input bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    """Hash canonical data, matching BAG canonical JSON encoding."""
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_recipe(root):
    """Use the independently testable bounded contract before any Blender operation."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from manufactured_panel_refinement_contract import validate_recipe

    return validate_recipe(root)


def convex_core(c):
    """Create a capped 12-facet elliptical core along its local X centerline."""
    n = c["radial_segments"]
    verts = []
    faces = []
    for x, s in zip(c["x_sections"], c["radius_factors"], strict=True):
        for i in range(n):
            a = 2 * math.pi * i / n
            verts.append(
                (
                    x,
                    c["center_y"] - c["radius_y"] * s * math.cos(a),
                    c["center_z"] + c["radius_z"] * s * math.sin(a),
                )
            )
    for q in range(3):
        for i in range(n):
            j = (i + 1) % n
            faces.append((q * n + i, q * n + j, (q + 1) * n + j, (q + 1) * n + i))
    faces.extend([tuple(reversed(range(n))), tuple(3 * n + i for i in range(n))])
    return verts, faces


def rail_geometry(r):
    """Create a closed sloped support rail with an explicit receiver-contact underside."""
    x0, x1 = r["rail_x"]
    y = r["rail_half_depth"]
    z0, z1 = r["bottom_z"]
    h = r["height"]
    v = [
        (x0, -y, z0),
        (x1, -y, z1),
        (x1, y, z1),
        (x0, y, z0),
        (x0, -y, z0 + h),
        (x1, -y, z1 + h),
        (x1, y, z1 + h),
        (x0, y, z0 + h),
    ]
    return v, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def backstrap_geometry(r):
    """Extrude a reference-visible pale rear grip trim with explicitly inferred depth."""
    p = r["profile_xz"]
    n = len(p)
    y = r["half_depth"]
    v = [(x, d, z) for d in (-y, y) for x, z in p]
    f = [tuple(reversed(range(n))), tuple(n + i for i in range(n))]
    f += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    return v, f


def rebuilt_section(section, base):
    """Rebuild broad source-bound sections instead of tiny legacy rings."""
    if section["kind"] == "source_profile":
        profile = [(base["vertices"][i][0], base["vertices"][i][2]) for i in section["indices"]]
        n = len(profile)
        y = section["half_depth"]
        v = [(x, d, z) for d in (-y, y) for x, z in profile]
        f = [tuple(reversed(range(n))), tuple(n + i for i in range(n))]
        f.extend((i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n))
        return v, f
    outer = section["outer_yz"]
    inner = section["inner_yz"]
    n = len(outer)
    v = [(x, y, z) for x in section["x_range"] for contour in (outer, inner) for y, z in contour]
    f = []
    for i in range(n):
        j = (i + 1) % n
        f.extend(
            [
                (i, j, n + j, n + i),
                (2 * n + i, 3 * n + i, 3 * n + j, 2 * n + j),
                (i, 2 * n + i, 2 * n + j, j),
                (n + i, n + j, 3 * n + j, 3 * n + i),
            ]
        )
    return v, f


def mesh_from_geometry(name, verts, faces):
    """Build an in-memory mesh and orient all closed component normals outward."""
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def apply_edge_roll(ob, e):
    """Roll real dihedral edges, excluding coplanar triangle diagonals; apply all geometry."""
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    m = ob.modifiers.new("BoundedEdgeRoll", "BEVEL")
    m.width = e["width_m"]
    m.segments = e["segments"]
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(e["angle_degrees"])
    m.use_clamp_overlap = True
    m.affect = "EDGES"
    bpy.ops.object.modifier_apply(modifier=m.name)
    ob.select_set(False)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bmesh.ops.triangulate(bm, faces=list(bm.faces), quad_method="BEAUTY", ngon_method="BEAUTY")
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def finalize_topology(ob, tolerance):
    """Weld only submicron duplicates and orient each closed component to positive volume."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=tolerance)
    bmesh.ops.dissolve_degenerate(bm, dist=tolerance, edges=list(bm.edges))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bmesh.ops.triangulate(bm, faces=list(bm.faces), quad_method="BEAUTY", ngon_method="BEAUTY")
    todo = set(bm.faces)
    while todo:
        seed = todo.pop()
        group = [seed]
        stack = [seed]
        while stack:
            f = stack.pop()
            for e in f.edges:
                for other in e.link_faces:
                    if other in todo:
                        todo.remove(other)
                        group.append(other)
                        stack.append(other)
        volume = sum(f.verts[0].co.dot(f.verts[1].co.cross(f.verts[2].co)) / 6 for f in group)
        if volume < 0:
            bmesh.ops.reverse_faces(bm, faces=group)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.update()


def layout_uvs(me):
    """Create nonoverlapping per-triangle UV islands with positive area and a fixed gutter."""
    n = len(me.polygons)
    side = math.ceil(math.sqrt(n))
    out = []
    for i, p in enumerate(me.polygons):
        co = [me.vertices[k].co for k in p.vertices]
        a = co[1] - co[0]
        length = a.length
        u = a.normalized()
        v = p.normal.cross(u).normalized()
        xy = [(0.0, 0.0), (length, 0.0), ((co[2] - co[0]).dot(u), (co[2] - co[0]).dot(v))]
        mnx = min(q[0] for q in xy)
        mny = min(q[1] for q in xy)
        scale = 0.86 / max(max(q[0] for q in xy) - mnx, max(q[1] for q in xy) - mny, 1e-12)
        out.extend(
            [
                (
                    (i % side + 0.07 + (x - mnx) * scale) / side,
                    (i // side + 0.07 + (y - mny) * scale) / side,
                )
                for x, y in xy
            ]
        )
    return out


def payload_from_object(ob, base, recipe, source_rows):
    """Publish evaluated closed geometry plus explicit triangulated UV and smoothing intent."""
    me = ob.data
    g = copy.deepcopy(base)
    g["vertices"] = [list(v.co) for v in me.vertices]
    g["faces"] = [list(p.vertices) for p in me.polygons]
    g["loop_count"] = len(me.loops)
    g["loop_uvs"] = layout_uvs(me)
    g["polygon_material_indices"] = [0] * len(me.polygons)
    g["face_groups"] = [{"id": "laser.exterior", "face_indices": list(range(len(me.polygons)))}]
    g["smooth_polygon_flags"] = [False] * len(me.polygons)
    g["sharp_edges"] = []
    g["uv_seams"] = []
    g["edge_creases"] = []
    g["bevel_weights"] = []
    g["source_geometry_intent"]["face_groups"] = g["face_groups"]
    g["source_geometry_intent"]["source_intent_sha256"] = digest(
        {k: v for k, v in g["source_geometry_intent"].items() if k != "source_intent_sha256"}
    )
    g["source_hashes"] = source_rows
    g["source_fingerprint_sha256"] = digest(source_rows)
    g["findings"] = [
        {
            "code": "staged.manufactured_refinement",
            "severity": "info",
            "message": (
                "Bounded deterministic edge roll, convex core and independent rail, "
                "staged only; no earlier approval inherited."
            ),
        }
    ]
    return g


def main():
    """Read fixed source hashes and write only a new contained BAG-ready staging root."""
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True)
    a = p.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    root = Path(a.root).resolve()
    r = load_recipe(root)
    assert not (root / "geometry").exists() and not (root / "analysis").exists(), (
        "Refusing to overwrite existing generated staging"
    )
    spec = json.loads((root / "sources/baseline_scene_spec.json").read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    (root / "geometry").mkdir(exist_ok=True)
    (root / "analysis").mkdir(exist_ok=True)
    summary = []
    for o in spec["objects"]:
        sid = o["id"]
        base = json.loads((root / r["inputs"][sid]["path"]).read_text())
        v = copy.deepcopy(base["vertices"])
        f = copy.deepcopy(base["faces"])
        if sid == r["core"]["semantic_id"]:
            v, f = convex_core(r["core"])
        if sid in r["section_rebuilds"]:
            v, f = rebuilt_section(r["section_rebuilds"][sid], base)
        if sid == r["stock_inlay_reseat"]["semantic_id"]:
            t = r["stock_inlay_reseat"]
            cx, cz = t["xz_center"]
            for i in range(t["start_index"], t["end_index"]):
                v[i][0] = cx + (v[i][0] - cx) * t["xz_scale"]
                v[i][2] = cz + (v[i][2] - cz) * t["xz_scale"] + t["z_offset"]
        if sid == r["sight_mount"]["semantic_id"]:
            if sid not in r["section_rebuilds"]:
                for i, pt in r["sight_mount"]["housing_restore"].items():
                    v[int(i)] = pt
            rv, rf = rail_geometry(r["sight_mount"])
            offset = len(v)
            v += rv
            f += [tuple(k + offset for k in q) for q in rf]
        if sid == r["grip_backstrap"]["semantic_id"]:
            tv, tf = backstrap_geometry(r["grip_backstrap"])
            offset = len(v)
            v += tv
            f += [tuple(k + offset for k in q) for q in tf]
        ob = mesh_from_geometry(sid, v, f)
        edge = copy.deepcopy(r["edge_roll"])
        edge["width_m"] = r["edge_roll_overrides"].get(sid, edge["width_m"])
        edge["segments"] = r["edge_segments_by_id"][sid]
        if sid in r["section_rebuilds"]:
            edge["width_m"] = r["section_rebuilds"][sid]["bevel_width"]
            edge["segments"] = r["section_rebuilds"][sid]["segments"]
        if sid != r["core"]["semantic_id"]:
            apply_edge_roll(ob, edge)
        else:
            bm = bmesh.new()
            bm.from_mesh(ob.data)
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
            bm.to_mesh(ob.data)
            bm.free()
            ob.data.update()
        finalize_topology(ob, r["weld_tolerance_m"])
        rows = [
            {
                "role": "other",
                "path": "refinement_recipe.json",
                "sha256": sha(root / "refinement_recipe.json"),
            },
            {"role": "source_mesh_payload", **r["inputs"][sid]},
        ]
        g = payload_from_object(ob, base, r, rows)
        rel = "geometry/" + sid + ".json"
        (root / rel).write_text(json.dumps(g, indent=2) + "\n")
        o["geometry"]["path"] = rel
        o["modifiers"] = []
        o["shade_smooth"] = False
        summary.append({"id": sid, "vertices": len(g["vertices"]), "triangles": len(g["faces"])})
    spec["assumptions"] += r["limits"]
    spec["revision_notes"].append(

            "Staged manufactured refinement 0.1: bounded physical edge roll, "
            "elliptic longitudinal energy core and separate sloped sight mounting rail. "
            "All camera transforms unchanged."

    )
    (root / "analysis/scene_spec.json").write_text(json.dumps(spec, indent=2) + "\n")
    (root / "geometry_receipt.json").write_text(
        json.dumps(
            {
                "recipe_sha256": sha(root / "refinement_recipe.json"),
                "blender": bpy.app.version_string,
                "objects": summary,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
