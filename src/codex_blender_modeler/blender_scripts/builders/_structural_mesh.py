"""Shared fail-closed Blender mesh construction for structural geometry builders."""

from __future__ import annotations

import json
import math
from typing import Any

import bpy


def create_mesh_object(
    name: str,
    payload: dict[str, Any],
    *,
    builder_kind: str,
) -> bpy.types.Object:
    """Create one linked mesh object and reject destructive Blender validation fixes."""

    vertices = [tuple(float(value) for value in point) for point in payload["vertices"]]
    faces = [[int(value) for value in face] for face in payload["faces"]]
    if not vertices or not faces:
        raise RuntimeError(f"{builder_kind} produced an empty mesh")
    if any(not all(math.isfinite(value) for value in point) for point in vertices):
        raise RuntimeError(f"{builder_kind} produced non-finite vertices")
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    changed = bool(mesh.validate(clean_customdata=False, verbose=False))
    mesh.update(calc_edges=True)
    if changed:
        bpy.data.meshes.remove(mesh)
        raise RuntimeError(f"{builder_kind} required destructive Blender mesh repair")
    if not mesh.polygons or any(polygon.area <= 1.0e-14 for polygon in mesh.polygons):
        bpy.data.meshes.remove(mesh)
        raise RuntimeError(f"{builder_kind} produced empty or degenerate polygons")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["cbm_structural_builder_kind"] = builder_kind
    obj["cbm_structural_findings"] = json.dumps(
        payload.get("findings", []),
        sort_keys=True,
        separators=(",", ":"),
    )
    return obj


def edge_incidence_findings(obj: bpy.types.Object) -> list[dict[str, str]]:
    """Return deterministic boundary and non-manifold edge-incidence findings."""

    counts: dict[tuple[int, int], int] = {}
    for polygon in obj.data.polygons:
        vertices = list(polygon.vertices)
        for index, first in enumerate(vertices):
            second = vertices[(index + 1) % len(vertices)]
            key = tuple(sorted((int(first), int(second))))
            counts[key] = counts.get(key, 0) + 1
    findings: list[dict[str, str]] = []
    boundary = sum(value == 1 for value in counts.values())
    non_manifold = sum(value > 2 for value in counts.values())
    if boundary:
        findings.append(
            {
                "code": "boundary_edges",
                "severity": "warning",
                "message": f"mesh contains {boundary} boundary edges",
            }
        )
    if non_manifold:
        findings.append(
            {
                "code": "non_manifold_edges",
                "severity": "error",
                "message": f"mesh contains {non_manifold} overused edges",
            }
        )
    return findings
