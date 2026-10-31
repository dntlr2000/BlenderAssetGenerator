"""Exact source-bound triangle projections for opt-in polygon attachment inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from .attachment_companion import Artifact, Strict
from .mesh_payload_v02 import MeshPayloadV02
from .polygon_shell_math import triangle_view


class MeshTriangleViewV01(Strict):
    """Bind a complete oriented corner partition to one immutable authored payload."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["mesh_triangle_view"] = "mesh_triangle_view"
    source_mesh: Artifact
    loop_triangles: list[tuple[int, int, int]] = Field(min_length=1, max_length=131072)


@dataclass(frozen=True)
class TriangleInspectionMesh:
    """Expose an ephemeral mapped mesh; never serialize it as an authored MeshPayload."""

    source: MeshPayloadV02
    faces: list[list[int]]
    face_groups: list
    loop_uvs: list
    polygon_material_indices: list[int]
    smooth_polygon_flags: list[bool]
    loop_count: int
    source_polygon_indices: list[int]
    source_loop_indices: list[list[int]]

    def __getattr__(self, name):
        """Delegate unchanged identity, vertices, edge attributes and source binding."""
        return getattr(self.source, name)


def project_triangle_view(mesh: MeshPayloadV02, view: MeshTriangleViewV01):
    """Expand face groups and corner attributes after verifying the complete partition."""
    mapping = triangle_view(mesh.vertices, mesh.faces, view.loop_triangles)
    polygons, loops = mapping["polygon_indices"], mapping["loop_indices"]
    groups = [group.model_copy(update={"face_indices": [
        i for i, p in enumerate(polygons) if p in set(group.face_indices)
    ]}) for group in mesh.face_groups]
    return TriangleInspectionMesh(
        source=mesh, faces=mapping["triangles"], face_groups=groups,
        loop_uvs=[mesh.loop_uvs[i] for tri in loops for i in tri],
        polygon_material_indices=[mesh.polygon_material_indices[i] for i in polygons],
        smooth_polygon_flags=[mesh.smooth_polygon_flags[i] for i in polygons],
        loop_count=3 * len(loops), source_polygon_indices=polygons, source_loop_indices=loops,
    )


def selected_triangle_mesh(root, intent, artifact, mesh):
    """Rehash the explicitly selected view and source; legacy requests keep original semantics."""
    if intent.schema_version == "0.1.0":
        return mesh
    if intent.schema_version != "0.2.0":
        raise ValueError("unsupported polygon attachment version")
    from ..attachment_runtime import artifact_bytes

    selected = {}
    total_bytes = total_triangles = 0
    for item in intent.source_triangle_views:
        data = artifact_bytes(root, item.model_dump(mode="json"))
        total_bytes += len(data)
        if total_bytes > 32 * 1024 * 1024:
            raise ValueError("triangle views exceed bounded aggregate bytes")
        view = MeshTriangleViewV01.model_validate_json(data)
        total_triangles += len(view.loop_triangles)
        if total_triangles > 25000:
            raise ValueError("triangle views exceed aggregate triangle limit")
        if view.source_mesh.path in selected:
            raise ValueError("triangle view repeats a source mesh")
        selected[view.source_mesh.path] = view
    expected = {item.path: item.sha256 for item in intent.source_geometry}
    if set(selected) != set(expected) or any(
        selected[p].source_mesh.sha256 != digest for p, digest in expected.items()
    ):
        raise ValueError("triangle views have stale, mixed or incomplete source bindings")
    return project_triangle_view(mesh, selected[artifact.path])
