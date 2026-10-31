"""Opt-in Blender 5.0.1 preservation and native diagonal evidence for polygon authoring."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from test_polygon_shell import cube

from codex_blender_modeler.blender_runner import run_blender
from codex_blender_modeler.config import get_settings
from codex_blender_modeler.structural_geometry.models import StructuralGeometryCandidate
from codex_blender_modeler.structural_geometry.service import materialize_structural_candidate
from codex_blender_modeler.structural_geometry.triangle_view import (
    MeshTriangleViewV01,
    project_triangle_view,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("CBM_RUN_POLYGON_SMOKE") != "1", reason="explicit native polygon smoke opt-in",
)


def test_native_polygons_views_export_and_reopen(tmp_path):
    """Prove quad storage, nonplanar native corners, UV mapping and independent GLB import."""
    value = cube()
    value["vertices"][6][2] = 1.4
    root = tmp_path / "native"
    mesh = materialize_structural_candidate(
        job_root=root, candidate=StructuralGeometryCandidate.model_validate_json(json.dumps({
            "semantic_id": "test.shell", "geometry": value,
            "geometry_intent": {"smoothing_policy": {"mode": "flat"}},
        })),
        candidate_relative_path="candidate.json", mesh_relative_path="mesh.json",
        blend_relative_path="author.blend", report_relative_path="materialize.json",
        mesh_payload_version="0.2.0", material_id="mat.shell",
    )
    report = json.loads((root / "materialize.json").read_bytes())
    assert report["blender_version"] == "5.0.1"
    assert mesh.faces == value["faces"]
    view = MeshTriangleViewV01.model_validate_json(json.dumps(report["triangle_view"]))
    assert len(project_triangle_view(mesh, view).faces) == 12
    assert report["topology"]["authored"]["quad_face_ratio"] == 1
    run_blender("inspect_scene.py", ["--output", str(root / "inventory.json")],
                blend_file=root / "author.blend", disable_autoexec=True)
    inventory = json.loads((root / "inventory.json").read_bytes())
    assert inventory["objects"][0]["polygon_topology"]["authored"]["quad_faces"] == 6
    before = hashlib.sha256((root / "author.blend").read_bytes()).hexdigest()
    scripts = Path(__file__).resolve().parents[1] / "src/codex_blender_modeler/blender_scripts"
    fixture = root / "native_check.py"
    fixture.write_text('''"""Fixed native test only; no public arbitrary execution input."""
import sys, json
from pathlib import Path
import bpy
root, scripts = map(Path, sys.argv[sys.argv.index("--") + 1:])
sys.path.insert(0, str(scripts))
from export_portable_package import normalize_gltf_serialization_topology
from polygon_topology import mesh_triangle_view
obj = next(o for o in bpy.data.objects if o.type == "MESH")
assert len(obj.data.polygons) == 6
assert all(len(p.vertices) == 4 for p in obj.data.polygons)
before = mesh_triangle_view(obj.data)
expected = sorted(tuple(sorted(t)) for t in before["triangles"])
obj["cbm_preserve_polygon_tessellation"] = True
normalize_gltf_serialization_topology([obj], "glb")
actual = sorted(tuple(sorted(p.vertices)) for p in obj.data.polygons)
assert actual == expected
uvs = [list(v.uv) for v in obj.data.uv_layers.active.data]
original = json.loads((root / "mesh.json").read_bytes())["loop_uvs"]
expected_uvs = sorted(tuple(original[i]) for t in before["loop_indices"] for i in t)
assert sorted(map(tuple, uvs)) == expected_uvs
bpy.ops.export_scene.gltf(filepath=str(root / "asset.glb"), export_format="GLB")
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(root / "asset.glb"))
objects = [o for o in bpy.data.objects if o.type == "MESH"]
assert sum(len(o.data.polygons) for o in objects) == 12
assert all(o.data.uv_layers for o in objects)
bpy.ops.wm.open_mainfile(filepath=str(root / "author.blend"))
obj = next(o for o in bpy.data.objects if o.type == "MESH")
assert len(obj.data.polygons) == 6
assert all(len(p.vertices) == 4 for p in obj.data.polygons)
result = {"status":"passed", "version":bpy.app.version_string,
    "quad_faces":6, "import_triangles":12, "native_triangle_mapping":True}
(root / "native_result.json").write_text(json.dumps(result), encoding="utf-8")
''', encoding="utf-8")
    result = subprocess.run(
        [get_settings().blender_bin, "--background", str(root / "author.blend"),
         "--disable-autoexec", "--python-exit-code", "1", "--python", str(fixture),
         "--", str(root), str(scripts)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert hashlib.sha256((root / "author.blend").read_bytes()).hexdigest() == before
