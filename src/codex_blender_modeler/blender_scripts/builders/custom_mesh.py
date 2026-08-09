from __future__ import annotations

import json
import math
from pathlib import Path

import bpy


def _resolve(path: str, base_dir: Path) -> Path:
    """Resolve one path-backed custom-mesh payload inside the active job context."""

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _apply_vertex_uvs(mesh: bpy.types.Mesh, raw_uvs: object) -> None:
    """Create UVMap from an optional deterministic UV pair stored per mesh vertex."""

    if raw_uvs is None:
        return
    if not isinstance(raw_uvs, list) or len(raw_uvs) != len(mesh.vertices):
        raise RuntimeError(
            "custom_mesh vertex_uvs must contain one UV pair per mesh vertex"
        )
    vertex_uvs: list[tuple[float, float]] = []
    for index, item in enumerate(raw_uvs):
        if not isinstance(item, list) or len(item) != 2:
            raise RuntimeError(
                f"custom_mesh vertex_uvs[{index}] must be a two-value array"
            )
        uv = (float(item[0]), float(item[1]))
        if not all(math.isfinite(value) for value in uv):
            raise RuntimeError(
                f"custom_mesh vertex_uvs[{index}] must contain finite values"
            )
        vertex_uvs.append(uv)
    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = vertex_uvs[vertex_index]


def build(spec: dict, base_dir: Path) -> bpy.types.Object:
    """Build custom-mesh geometry and preserve optional path-backed vertex UV evidence."""

    vertex_uvs = None
    if spec.get("path"):
        payload_path = _resolve(spec["path"], base_dir)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        vertices = payload["vertices"]
        faces = payload["faces"]
        vertex_uvs = payload.get("vertex_uvs")
    else:
        vertices = spec["vertices"]
        faces = spec["faces"]

    mesh = bpy.data.meshes.new("CBM_CustomMesh")
    mesh.from_pydata(vertices, [], faces)
    if spec.get("recalculate_normals", True):
        mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    _apply_vertex_uvs(mesh, vertex_uvs)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("CBM_CustomMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
