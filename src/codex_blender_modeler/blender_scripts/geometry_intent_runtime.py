"""Apply validated structural geometry intent through Blender's bounded data API."""

from __future__ import annotations

import math

import bpy


def _edge_lookup(mesh: bpy.types.Mesh) -> dict[tuple[int, int], bpy.types.MeshEdge]:
    """Index mesh edges by their canonical ordered vertex pair."""

    return {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))): edge
        for edge in mesh.edges
    }


def _require_edge(
    lookup: dict[tuple[int, int], bpy.types.MeshEdge],
    raw: dict,
) -> bpy.types.MeshEdge:
    """Resolve one declared edge and reject stale compiled topology references."""

    key = tuple(int(value) for value in raw["vertices"])
    edge = lookup.get(key)
    if edge is None:
        raise RuntimeError(f"geometry intent references missing edge {key}")
    return edge


def _ensure_float_edge_attribute(mesh: bpy.types.Mesh, name: str) -> bpy.types.Attribute:
    """Create or reuse one Blender 4/5 float edge-domain attribute."""

    attribute = mesh.attributes.get(name)
    if attribute is None:
        attribute = mesh.attributes.new(name=name, type="FLOAT", domain="EDGE")
    if attribute.domain != "EDGE" or attribute.data_type != "FLOAT":
        raise RuntimeError(f"mesh attribute {name} has an incompatible type")
    return attribute


def _apply_face_groups(mesh: bpy.types.Mesh, groups: list[dict]) -> None:
    """Persist stable face-group membership as Boolean FACE attributes."""

    for group in groups:
        name = f"cbm_face_group__{group['id']}"
        attribute = mesh.attributes.get(name)
        if attribute is None:
            attribute = mesh.attributes.new(name=name, type="BOOLEAN", domain="FACE")
        if attribute.domain != "FACE" or attribute.data_type != "BOOLEAN":
            raise RuntimeError(f"face-group attribute {name} has an incompatible type")
        for item in attribute.data:
            item.value = False
        for index in group["face_indices"]:
            polygon_index = int(index)
            if polygon_index < 0 or polygon_index >= len(mesh.polygons):
                raise RuntimeError(
                    f"geometry intent face group {group['id']} references face {polygon_index}"
                )
            attribute.data[polygon_index].value = True


def _apply_weighted_edges(
    mesh: bpy.types.Mesh,
    lookup: dict[tuple[int, int], bpy.types.MeshEdge],
    declarations: list[dict],
    attribute_name: str,
) -> None:
    """Apply normalized crease or bevel weights to exact compiled edges."""

    attribute = _ensure_float_edge_attribute(mesh, attribute_name)
    for item in attribute.data:
        item.value = 0.0
    for declaration in declarations:
        edge = _require_edge(lookup, declaration)
        attribute.data[edge.index].value = float(declaration["weight"])


def _apply_smoothing(obj: bpy.types.Object, policy: dict) -> None:
    """Apply flat, angle-based, or weighted-normal shading without topology edits."""

    mesh = obj.data
    mode = str(policy.get("mode", "legacy"))
    if mode == "legacy":
        return
    if mode == "flat":
        for polygon in mesh.polygons:
            polygon.use_smooth = False
        return
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    threshold = math.radians(float(policy.get("angle_degrees", 30.0)))
    if mode == "smooth_by_angle":
        polygons_by_edge: dict[tuple[int, int], list[int]] = {}
        for polygon in mesh.polygons:
            for key in polygon.edge_keys:
                canonical = tuple(sorted((int(key[0]), int(key[1]))))
                polygons_by_edge.setdefault(canonical, []).append(polygon.index)
        for edge in mesh.edges:
            key = tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1]))))
            adjacent = polygons_by_edge.get(key, [])
            if len(adjacent) == 2:
                first = mesh.polygons[adjacent[0]].normal
                second = mesh.polygons[adjacent[1]].normal
                dot_value = max(-1.0, min(1.0, float(first.dot(second))))
                edge.use_edge_sharp = math.acos(dot_value) > threshold
        return
    if mode == "weighted_normals":
        modifier = obj.modifiers.new(name="CBM_WeightedNormals", type="WEIGHTED_NORMAL")
        modifier.keep_sharp = bool(policy.get("keep_sharp", True))
        return
    raise RuntimeError(f"unsupported geometry intent smoothing mode: {mode}")


def _apply_subdivision(obj: bpy.types.Object, intent: dict) -> None:
    """Attach one bounded subdivision modifier only when explicit intent enables it."""

    if not intent.get("enabled", False):
        return
    modifier = obj.modifiers.new(name="CBM_IntentSubdivision", type="SUBSURF")
    modifier.levels = int(intent["levels"])
    modifier.render_levels = int(intent["levels"])
    modifier.subdivision_type = "CATMULL_CLARK"


def apply_geometry_intent(obj: bpy.types.Object, intent: dict | None) -> None:
    """Apply one validated intent contract and fail on stale edge or face references."""

    if intent is None:
        return
    if obj.type != "MESH" or obj.data is None:
        raise RuntimeError("geometry intent requires a Blender mesh object")
    mesh = obj.data
    lookup = _edge_lookup(mesh)
    _apply_face_groups(mesh, intent.get("face_groups", []))
    for declaration in intent.get("sharp_edges", []):
        _require_edge(lookup, declaration).use_edge_sharp = True
    for declaration in intent.get("uv_seams", []):
        _require_edge(lookup, declaration).use_seam = True
    _apply_weighted_edges(
        mesh,
        lookup,
        intent.get("crease_edges", []),
        "crease_edge",
    )
    _apply_weighted_edges(
        mesh,
        lookup,
        intent.get("bevel_weights", []),
        "bevel_weight_edge",
    )
    _apply_smoothing(obj, intent.get("smoothing_policy", {}))
    _apply_subdivision(obj, intent.get("subdivision_intent", {}))
    obj["cbm_topology_policy"] = str(intent.get("topology_policy", ""))
    obj["cbm_lod_preserve_silhouette"] = bool(
        intent.get("lod_intent", {}).get("preserve_silhouette", True)
    )
