"""Fixed Blender validation for three approved references; never saves the authoring scene."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(SOURCE / "codex_blender_modeler/blender_scripts"))

from common import configure_render  # noqa: E402
from polygon_topology import object_topology_statistics  # noqa: E402
from self_intersection_runtime import bounded_self_intersection  # noqa: E402


def sha(path):
    """Hash an actual native artifact before and after read-only validation."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    """Publish one immutable validation result using JSON-safe values only."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def mesh_objects():
    """Return the asset's mesh objects in stable order, excluding cameras and lights."""
    return sorted((o for o in bpy.context.scene.objects if o.type == "MESH"), key=lambda o: o.name)


def snapshot():
    """Capture oriented world triangles, UVs, normals and basic materials independently."""
    triangles, vertices, materials, topologies = [], [], [], []
    for obj in mesh_objects():
        mesh = obj.data
        mesh.calc_loop_triangles()
        world = [obj.matrix_world @ v.co for v in mesh.vertices]
        vertices.extend([list(v) for v in world])
        layer = mesh.uv_layers.active
        if layer is None:
            raise ValueError("actual asset is missing UV0")
        normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
        for tri in mesh.loop_triangles:
            corners = []
            for vertex, loop in zip(tri.vertices, tri.loops, strict=True):
                normal = (normal_matrix @ mesh.corner_normals[loop].vector).normalized()
                corners.append({"position": list(world[vertex]), "uv": list(layer.data[loop].uv),
                                "normal": list(normal)})
            triangles.append(corners)
        for slot in obj.material_slots:
            material = slot.material
            node = next(n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            materials.append({"base_color": list(node.inputs["Base Color"].default_value),
                              "roughness": float(node.inputs["Roughness"].default_value),
                              "metallic": float(node.inputs["Metallic"].default_value)})
        topologies.append(object_topology_statistics(obj))
    return {"triangles": triangles, "materials": materials, "topology": topologies,
            "bounds": [[min(v[k] for v in vertices) for k in range(3)],
                       [max(v[k] for v in vertices) for k in range(3)]]}


def compare(source, imported):
    """Match every oriented triangle without welding gaps or borrowing source mesh data."""
    def key(triangle):
        """Use a coarse correspondence key; exact component residuals decide acceptance."""
        positions = tuple(tuple(round(x, 4) for x in c["position"]) for c in triangle)
        return min(positions[i:] + positions[:i] for i in range(3))

    actual = {}
    for tri in imported["triangles"]:
        actual.setdefault(key(tri), []).append(tri)
    if len(source["triangles"]) != len(imported["triangles"]):
        raise ValueError("clean import changed triangle count")
    errors = {"position": 0., "uv": 0., "normal_degrees": 0.}
    for tri in source["triangles"]:
        matches = actual.pop(key(tri), [])
        if len(matches) != 1:
            raise ValueError("clean import triangle correspondence is absent or ambiguous")
        other = matches[0]
        rotations = [other[i:] + other[:i] for i in range(3)]
        other = min(rotations, key=lambda row: sum(
            sum((x-y)**2 for x, y in zip(a["position"], b["position"], strict=True))
            for a, b in zip(tri, row, strict=True)))
        for a, b in zip(tri, other, strict=True):
            for field in ("position", "uv"):
                errors[field] = max(errors[field], max(abs(x-y) for x, y in zip(
                    a[field], b[field], strict=True)))
            dot = Vector(a["normal"]).normalized().dot(Vector(b["normal"]).normalized())
            errors["normal_degrees"] = max(errors["normal_degrees"],
                                           math.degrees(math.acos(max(-1., min(1., dot)))))
    materials_equal = len(source["materials"]) == len(imported["materials"]) and all(
        max(abs(x-y) for x, y in zip(a["base_color"], b["base_color"], strict=True)) <= 2e-6
        and abs(a["roughness"] - b["roughness"]) <= 2e-6
        and abs(a["metallic"] - b["metallic"]) <= 2e-6
        for a, b in zip(source["materials"], imported["materials"], strict=True)
    )
    bounds_error = max(abs(x-y) for a, b in zip(source["bounds"], imported["bounds"], strict=True)
                       for x, y in zip(a, b, strict=True))
    passed = (not actual and errors["position"] <= 2e-6 and errors["uv"] <= 2e-6
              and errors["normal_degrees"] <= .1 and bounds_error <= 2e-6 and materials_equal)
    return {"status": "passed" if passed else "failed", "maximum_errors": errors,
            "bounds_error_m": bounds_error, "basic_materials_preserved": materials_equal,
            "triangle_count": len(source["triangles"]), "source_topology": source["topology"],
            "import_topology": imported["topology"], "independent_import": True,
            "production_package": False, "human_acceptance": False}


def diagnostics(asset, output):
    """Render four fixed neutral views and perform bounded geometry/editability diagnostics."""
    objects = mesh_objects()
    original = snapshot()
    report = {"asset": asset, "topology": original["topology"], "self_intersection": [],
              "editability": [], "views": [], "human_acceptance": False}
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        report["self_intersection"].append(bounded_self_intersection(
            [obj.matrix_world @ v.co for v in mesh.vertices],
            [tuple(t.vertices) for t in mesh.loop_triangles],
            max_triangles=5000, max_pair_tests=100000))
        copy = mesh.copy()
        before = [tuple(v.co) for v in copy.vertices]
        middle = min(abs(p[0]) for p in before)
        selected = [i for i, p in enumerate(before) if abs(abs(p[0]) - middle) <= 1e-6]
        for i in selected:
            copy.vertices[i].co.z += .002
        changed = sum(tuple(v.co) != before[v.index] for v in copy.vertices)
        for vertex, value in zip(copy.vertices, before, strict=True):
            vertex.co = value
        restored = all(tuple(v.co) == before[v.index] for v in copy.vertices)
        report["editability"].append({"moved_vertices": changed, "offset_m": .002,
                                      "restored_exactly": restored, "original_untouched": True})
        bpy.data.meshes.remove(copy)
    neutral = bpy.data.materials.new("Validation neutral clay")
    neutral.use_nodes = True
    node = neutral.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (.42, .42, .42, 1.)
    node.inputs["Roughness"].default_value = .8
    for obj in objects:
        obj.data.materials.clear()
        obj.data.materials.append(neutral)
    scene, camera = bpy.context.scene, bpy.context.scene.camera
    original_camera = camera.matrix_world.copy()
    original_scale = camera.data.ortho_scale
    center = Vector([(a+b)/2 for a, b in zip(*original["bounds"], strict=True)])
    span = max(b-a for a, b in zip(*original["bounds"], strict=True))
    views = [("profile", (0., -3., .5)), ("reverse", (0., 3., .6)),
             ("end", (-3., 0., .25)), ("top", (0., 0., 3.))]
    if asset == "cloth":
        views[0] = ("subdivision", None)
    configure_render("eevee", "auto")
    scene.render.resolution_x = scene.render.resolution_y = 512
    for name, direction in views:
        modifiers = []
        if direction is None:
            camera.matrix_world = original_camera
            for obj in objects:
                modifier = obj.modifiers.new("Validation temporary subdivision", "SUBSURF")
                modifier.levels = modifier.render_levels = 1
                modifiers.append((obj, modifier))
            bpy.context.view_layer.update()
            report["subdivision"] = [object_topology_statistics(obj) for obj in objects]
        else:
            camera.location = center + Vector(direction) * span
            camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera.data.type = "ORTHO"
        camera.data.ortho_scale = original_scale if direction is None else span * 1.25
        scene.render.filepath = str(output / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        report["views"].append({"name": name, "sha256": sha(output / f"{name}.png")})
        for obj, modifier in modifiers:
            obj.modifiers.remove(modifier)
    return report


def main():
    """Run diagnostics or an independent import with exact source and fresh output guards."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", choices=("cloth", "rock", "wood"), required=True)
    parser.add_argument("--stage", choices=("diagnostics", "roundtrip"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--blend", type=Path, required=True)
    parser.add_argument("--blend-sha256", required=True)
    parser.add_argument("--glb", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if bpy.app.version_string != "5.0.1" or sha(args.blend) != args.blend_sha256:
        raise ValueError("unsupported Blender or stale source")
    output = args.output.resolve()
    output.relative_to(Path("E:/CodexValidation").resolve())
    output.mkdir(parents=True, exist_ok=False)
    if args.stage == "diagnostics":
        report = diagnostics(args.asset, output)
    else:
        before = snapshot()
        glb_hash = sha(args.glb)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(args.glb))
        imported = snapshot()
        report = compare(before, imported)
        report["glb_sha256"] = glb_hash
        bpy.ops.wm.save_as_mainfile(filepath=str(output / "imported.blend"))
        if sha(args.glb) != glb_hash:
            raise ValueError("import changed exported bytes")
    report.update(blender_version=bpy.app.version_string, source_blend_sha256=args.blend_sha256,
                  source_unchanged=sha(args.blend) == args.blend_sha256)
    write(output / "report.json", report)
    if not report["source_unchanged"] or report.get("status") == "failed":
        raise ValueError("native validation failed; evidence retained")


if __name__ == "__main__":
    main()
