"""Opt-in Blender 5.0.1 low-poly LOD feasibility fixture; no user asset mutation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from codex_blender_modeler.config import get_settings
from codex_blender_modeler.optimization.preflight import _lod_feasibility_warnings
from codex_blender_modeler.optimization.profiles import create_builtin_profile

ROOT = Path(__file__).resolve().parents[1]
PROBE = '''
import json, sys
from pathlib import Path
import bpy
sys.path.insert(0, str(Path(SOURCE) / "src/codex_blender_modeler/blender_scripts"))
from portable_asset_common import object_inventory
from prepare_optimized_asset import make_lod

def snapshot(obj):
    """Snapshot exact owned source geometry to prove the derived operation is isolated."""
    return {"vertices": [tuple(v.co) for v in obj.data.vertices],
            "polygons": [tuple(p.vertices) for p in obj.data.polygons]}

def main():
    """Reduce a closed eight-triangle octahedron under the unchanged LOD2 cap."""
    assert bpy.app.version_string == "5.0.1"
    vertices = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
    faces = [(0,2,4),(2,1,4),(1,3,4),(3,0,4),
             (2,0,5),(1,2,5),(3,1,5),(0,3,5)]
    mesh = bpy.data.meshes.new("lowpoly.source.mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    source = bpy.data.objects.new("lowpoly.source", mesh)
    bpy.context.scene.collection.objects.link(source)
    source["cbm_id"] = "lowpoly.gem"
    source["cbm_asset_role"] = "render"
    source["cbm_lod_level"] = 0
    before = snapshot(source)
    collection = bpy.data.collections.new("fixture.derived")
    bpy.context.scene.collection.children.link(collection)
    derived = make_lod(source, collection, 2, .3)
    payload = {"blender_version": bpy.app.version_string,
               "source_unchanged": before == snapshot(source),
               "source": object_inventory(source), "derived": object_inventory(derived)}
    print("CBM_LOD_QUALITY_LOW_POLY=" + json.dumps(payload))

main()
'''


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_LOD_QUALITY_SMOKE") != "1",
    reason="Set CBM_RUN_LOD_QUALITY_SMOKE=1 for the Blender 5.0.1 low-poly warning fixture",
)
def test_native_low_poly_cap_stays_visible_without_false_silhouette_pass(tmp_path: Path) -> None:
    """Flag the native low-poly closed-volume cap without relaxing the profile."""

    script = tmp_path / "low_poly_probe.py"
    script.write_text(f"SOURCE = {str(ROOT)!r}\n{PROBE}", encoding="utf-8")
    result = subprocess.run(
        [
            get_settings().blender_bin,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    (tmp_path / "blender.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    record = json.loads(
        next(
            line.split("=", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("CBM_LOD_QUALITY_LOW_POLY=")
        )
    )
    assert record["blender_version"] == "5.0.1" and record["source_unchanged"] is True
    assert record["source"]["topology"]["manifold_closed"] is True
    assert record["source"]["topology"]["triangles_estimated"] == 8
    assert record["derived"]["topology"]["triangles_estimated"] <= 3
    profile = create_builtin_profile("lod_test", "portable_gltf", "static_prop")
    warnings = _lod_feasibility_warnings({"objects": [record["source"]]}, profile, "native.json")
    assert len(warnings) == 1 and warnings[0].status == "warning"
    assert "cap is 3" in warnings[0].message and "remain unverified" in warnings[0].message
