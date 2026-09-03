"""Validate exact angle-based shading refresh on derived LODs, never source meshes."""

from __future__ import annotations

import ast
import copy
import json
import math
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from codex_blender_modeler.config import get_settings

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "src/codex_blender_modeler/blender_scripts"


def _runtime() -> Any:
    """Load the real data-only refresh function without importing bpy in ordinary pytest."""

    tree = ast.parse((SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8"))
    function = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "refresh_derived_lod_smoothing"
    )
    header = ast.parse("from __future__ import annotations").body
    module = ast.fix_missing_locations(ast.Module(body=[*header, function], type_ignores=[]))
    namespace: dict[str, Any] = {"json": json, "math": math}
    exec(compile(module, "<real_lod_smoothing_function>", "exec"), namespace)
    return namespace[function.name]


class _Normal(tuple):
    """Provide the Blender vector dot operation for deterministic normal fixtures."""

    def dot(self, other: tuple[float, ...]) -> float:
        """Return the exact scalar product used by the production angle comparison."""

        return sum(first * second for first, second in zip(self, other, strict=True))


class _Mesh:
    """Track shading-only mutations independently from geometry and UV fixture data."""

    def __init__(self) -> None:
        """Create one hard join, one pre-existing sharp join, and one boundary edge."""

        self.polygons = [
            SimpleNamespace(
                index=0,
                normal=_Normal((0.0, 0.0, 1.0)),
                edge_keys=[(0, 1), (1, 2), (2, 0)],
                use_smooth=True,
            ),
            SimpleNamespace(
                index=1, normal=_Normal((0.0, 1.0, 0.0)), edge_keys=[(1, 0)], use_smooth=True
            ),
            SimpleNamespace(
                index=2, normal=_Normal((0.0, 0.0, 1.0)), edge_keys=[(2, 1)], use_smooth=False
            ),
        ]
        self.edges = [
            SimpleNamespace(index=0, vertices=(0, 1), use_edge_sharp=False),
            SimpleNamespace(index=1, vertices=(1, 2), use_edge_sharp=True),
            SimpleNamespace(index=2, vertices=(2, 0), use_edge_sharp=False),
        ]
        self.loops = list(range(9))
        self.vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        self.uv_values = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)] * 3
        self.has_custom_normals = True
        self.custom_normals: list[tuple[float, ...]] | None = None
        self.updates = 0

    def update(self) -> None:
        """Record a Blender-style cache refresh without changing fixture coordinates."""

        self.updates += 1

    def normals_split_custom_set(self, values: list[tuple[float, ...]]) -> None:
        """Record the zero-vector request for recomputed derived corner normals."""

        self.custom_normals = values


class _Object(dict):
    """Represent the minimum strict v2 provenance and LOD ownership boundary."""

    def __init__(self) -> None:
        """Create a tagged LOD with a complete validated-angle policy fixture."""

        super().__init__(
            cbm_asset_role="lod",
            cbm_lod_level=1,
            cbm_mesh_payload_version="0.2.0",
            cbm_v02_smoothing_mode="smooth_by_angle",
            cbm_v02_smoothing_policy=json.dumps(
                {"mode": "smooth_by_angle", "angle_degrees": 45.0, "keep_explicit_sharp": True}
            ),
        )
        self.type = "MESH"
        self.data = _Mesh()


def test_lod_refresh_retains_geometry_uv_flags_and_existing_sharp_edges() -> None:
    """Apply the declared angle only to new LOD joins while preserving source-like data."""

    target = _Object()
    geometry = copy.deepcopy((target.data.vertices, target.data.uv_values))
    record = _runtime()(target)
    assert record["status"] == "applied"
    assert record["retained_sharp_edge_count"] == 1
    assert record["added_sharp_edge_count"] == 1
    assert [edge.use_edge_sharp for edge in target.data.edges] == [True, True, False]
    assert [face.use_smooth for face in target.data.polygons] == [True, True, False]
    assert target.data.custom_normals == [(0.0, 0.0, 0.0)] * 9
    assert (target.data.vertices, target.data.uv_values) == geometry


@pytest.mark.parametrize("role,level", [("authoring", 0), ("render", 0), ("lod", 0), ("lod", True)])
def test_lod_refresh_rejects_source_and_ambiguous_ownership(role: str, level: int) -> None:
    """Reject canonical, LOD0, and bool-as-integer metadata before touching any mesh."""

    target = _Object()
    target.update(cbm_asset_role=role, cbm_lod_level=level)
    with pytest.raises(RuntimeError, match="derived mesh above LOD0"):
        _runtime()(target)
    assert target.data.updates == 0


def test_historical_missing_policy_remains_unchanged_without_migration() -> None:
    """Missing legacy companion metadata never invents a smoothing angle or policy."""

    target = _Object()
    del target["cbm_v02_smoothing_policy"]
    assert _runtime()(target)["reason"] == "source_has_no_exact_smoothing_policy"
    assert target.data.updates == 0


@pytest.mark.parametrize("mode", ["flat", "smooth", "weighted_normals"])
def test_other_smoothing_modes_keep_their_existing_behavior(mode: str) -> None:
    """Do not reinterpret flat, plain-smooth, or weighted-normal sources as angle shading."""

    target = _Object()
    target["cbm_v02_smoothing_mode"] = mode
    target["cbm_v02_smoothing_policy"] = json.dumps(
        {"mode": mode, "angle_degrees": None, "keep_explicit_sharp": True}
    )
    assert _runtime()(target)["reason"] == "source_mode_is_not_angle_based"
    assert target.data.updates == 0


@pytest.mark.parametrize("angle", [None, True, 0, 180, -1, "45", float("nan"), float("inf")])
def test_invalid_smoothing_angles_fail_before_mesh_changes(angle: object) -> None:
    """Reject absent, nonnumeric, nonfinite, and out-of-range declarations without guessing."""

    target = _Object()
    target["cbm_v02_smoothing_policy"] = json.dumps(
        {"mode": "smooth_by_angle", "angle_degrees": angle, "keep_explicit_sharp": True}
    )
    with pytest.raises(RuntimeError, match="outside its exact contract"):
        _runtime()(target)
    assert target.data.updates == 0


@pytest.mark.parametrize("raw", ["{", "[]", "{}", '{"mode":"flat"}'])
def test_malformed_or_partial_metadata_fails_closed(raw: str) -> None:
    """Treat invalid or incomplete optional metadata as an error, never as legacy absence."""

    target = _Object()
    target["cbm_v02_smoothing_policy"] = raw
    with pytest.raises(RuntimeError, match="metadata"):
        _runtime()(target)
    assert target.data.updates == 0


def test_nonfinite_face_normal_does_not_partially_mark_sharp_edges() -> None:
    """Resolve every angle before publishing sharp flags so invalid geometry fails closed."""

    target = _Object()
    target.data.polygons[2].normal = _Normal((float("nan"), 0.0, 0.0))
    with pytest.raises(RuntimeError, match="non-finite face normal"):
        _runtime()(target)
    assert not target.data.edges[0].use_edge_sharp
    assert target.data.custom_normals is None


def test_build_and_optimizer_bind_refresh_to_exact_policy_and_derived_evidence() -> None:
    """Ensure real builders publish the full policy and optimization records each refresh."""

    builder = (SCRIPT_ROOT / "builders/custom_mesh.py").read_text(encoding="utf-8")
    optimizer = (SCRIPT_ROOT / "prepare_optimized_asset.py").read_text(encoding="utf-8")
    assert 'obj["cbm_v02_smoothing_policy"] = json.dumps(' in builder
    assert "smoothing_record = refresh_derived_lod_smoothing(target)" in optimizer
    assert 'object_actions["lod_smoothing_refresh"][str(level)]' in optimizer


BLENDER_PROBE_SOURCE = '''
import json
import sys
from pathlib import Path
import bpy
sys.path.insert(0, SCRIPT_ROOT)
from prepare_optimized_asset import refresh_derived_lod_smoothing

def snapshot(mesh):
    """Capture geometry, UVs and smoothing flags independently of refreshed normals."""
    return {
        "vertices": [list(vertex.co) for vertex in mesh.vertices],
        "faces": [list(face.vertices) for face in mesh.polygons],
        "uv": [list(item.vector) for item in mesh.uv_layers["UVMap"].uv],
        "smooth": [bool(face.use_smooth) for face in mesh.polygons],
    }

def main():
    """Refresh only a folded derived fixture while proving source data is unchanged."""
    mesh = bpy.data.meshes.new("source")
    mesh.from_pydata([(0,0,0), (1,0,0), (1,1,0), (0,1,0), (0,0,1), (1,0,1)], [],
                     [(0,1,2,3), (1,0,4,5)])
    mesh.update(calc_edges=True)
    for face in mesh.polygons:
        face.use_smooth = True
    layer = mesh.uv_layers.new(name="UVMap")
    for index, uv in enumerate([(0,0), (1,0), (1,1), (0,1)] * 2):
        layer.uv[index].vector = uv
    source = bpy.data.objects.new("source", mesh)
    bpy.context.scene.collection.objects.link(source)
    before = snapshot(source.data)
    target = source.copy()
    target.data = source.data.copy()
    bpy.context.scene.collection.objects.link(target)
    target["cbm_asset_role"] = "lod"
    target["cbm_lod_level"] = 1
    target["cbm_mesh_payload_version"] = "0.2.0"
    target["cbm_v02_smoothing_mode"] = "smooth_by_angle"
    target["cbm_v02_smoothing_policy"] = json.dumps(
        {"mode":"smooth_by_angle", "angle_degrees":45.0, "keep_explicit_sharp":True})
    record = refresh_derived_lod_smoothing(target)
    assert record["added_sharp_edge_count"] == 1, record
    assert snapshot(source.data) == before
    assert snapshot(target.data) == before
    assert sum(bool(edge.use_edge_sharp) for edge in source.data.edges) == 0
    target.data.calc_tangents(uvmap="UVMap")
    assert all(loop.tangent.length > 0.99 for loop in target.data.loops)
    target.data.free_tangents()
    print("CBM_LOD_SMOOTHING_SMOKE=" + json.dumps(
        {"blender_version": bpy.app.version_string, "record": record,
         "source_unchanged": True, "geometry_uv_unchanged": True}))

main()
'''


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_LOD_SMOOTHING_SMOKE") != "1",
    reason="set CBM_RUN_LOD_SMOOTHING_SMOKE=1 for the real Blender shading regression",
)
def test_real_blender_refresh_keeps_source_geometry_and_uv_unchanged(tmp_path: Path) -> None:
    """Exercise the actual Blender data API and tangent calculation in an isolated fixture."""

    script = tmp_path / "lod_smoothing_smoke.py"
    script.write_text(
        f"SCRIPT_ROOT = {str(SCRIPT_ROOT)!r}\n{BLENDER_PROBE_SOURCE}", encoding="utf-8"
    )
    completed = subprocess.run(
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
    assert completed.returncode == 0, completed.stdout + completed.stderr
    line = next(
        line
        for line in completed.stdout.splitlines()
        if line.startswith("CBM_LOD_SMOOTHING_SMOKE=")
    )
    record = json.loads(line.split("=", 1)[1])
    assert record["blender_version"] == "5.0.1"
    assert record["source_unchanged"] and record["geometry_uv_unchanged"]
