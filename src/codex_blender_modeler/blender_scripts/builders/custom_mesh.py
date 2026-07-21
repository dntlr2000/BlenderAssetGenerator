from __future__ import annotations

import json
from pathlib import Path

import bpy


def _resolve(path: str, base_dir: Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def build(spec: dict, base_dir: Path) -> bpy.types.Object:
    if spec.get("path"):
        payload_path = _resolve(spec["path"], base_dir)
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        vertices = payload["vertices"]
        faces = payload["faces"]
    else:
        vertices = spec["vertices"]
        faces = spec["faces"]

    mesh = bpy.data.meshes.new("CBM_CustomMesh")
    mesh.from_pydata(vertices, [], faces)
    if spec.get("recalculate_normals", True):
        mesh.validate(clean_customdata=False)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new("CBM_CustomMesh", mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj
