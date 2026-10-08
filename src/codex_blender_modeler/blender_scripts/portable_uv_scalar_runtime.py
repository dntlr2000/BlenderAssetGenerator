"""Temporary UV-domain scalar proxies with strict geometry-independent shader eligibility."""

from __future__ import annotations

import bpy
from portable_authored_uv_proof import mapped_uvs
from portable_material_conversion_runtime import resolve_atlas_tiles
from portable_uv_scalar_bake import SCALAR_CHANNELS, affine_layer_corners, snapshot_digest


def scalar_dependencies(material, sockets, source):
    """Reject every non-allowlisted upstream dependency, including position/normal/object inputs."""
    records = []
    sampled = set()
    visited = set()
    visiting = set()
    allowed = {"TEX_IMAGE", "MAPPING", "UVMAP", "VALUE", "RGB"}

    def walk(node, output):
        """Walk the actual scalar output graph without trusting unused node names or metadata."""
        key = (node.name, output.name)
        if key in visiting:
            raise ValueError("UV scalar bake ineligible: cyclic source dependency")
        if key in visited:
            return
        if len(visited) + len(visiting) >= 512:
            raise ValueError("UV scalar bake dependency resource limit exceeded")
        visiting.add(key)
        if node.type not in allowed:
            raise ValueError(f"UV scalar bake ineligible dependency: {node.name} ({node.type})")
        row = {"node_name": node.name, "node_type": node.type, "output": output.name}
        if node.type == "UVMAP":
            if node.from_instancer or node.uv_map not in source["uv_layers"]:
                raise ValueError("UV scalar bake ineligible: ambiguous sampled UV source")
            sampled.add(node.uv_map)
            row["uv_set"] = node.uv_map
        if node.type == "TEX_IMAGE":
            if (
                node.image is None
                or node.projection != "FLAT"
                or not node.inputs["Vector"].is_linked
            ):
                raise ValueError(
                    "UV scalar bake ineligible: image requires explicit flat UV sampling"
                )
            if node.image.source not in {"FILE", "GENERATED"}:
                raise ValueError("UV scalar bake ineligible: animated, tiled or unsupported image")
            row.update(
                image_name=node.image.name,
                interpolation=node.interpolation,
                extension=node.extension,
                projection=node.projection,
            )
        for socket in node.inputs:
            for link in socket.links:
                walk(link.from_node, link.from_socket)
        records.append(row)
        visiting.remove(key)
        visited.add(key)

    for socket in sockets:
        if socket is not None:
            for link in socket.links:
                walk(link.from_node, link.from_socket)
    return sorted(records, key=lambda row: (row["node_name"], row["output"])), sorted(sampled)


def make_scalar_proxy(
    obj, source, index, count, resolution, margin_px, channel_socket, strength_socket,
    *, atlas_policy=None, source_objects=None, precomputed_bounds=None,
):
    """Create a UV-only scalar proxy, reusing a resolved tile or retaining allocator fallback."""
    material = obj.material_slots[0].material
    if material.node_tree is None or material.animation_data or material.node_tree.animation_data:
        raise ValueError("UV scalar bake ineligible: missing or animated source shader")
    dependencies = {}
    sampled = set()
    for channel in SCALAR_CHANNELS:
        sockets = [channel_socket(material, channel)]
        if channel == "emission":
            sockets.append(strength_socket(material))
        nodes, layers = scalar_dependencies(material, sockets, source)
        dependencies[channel] = nodes
        sampled.update(layers)
    selected = source["source_uv_set"]
    layout = source["uv_layers"][selected]
    minimum = [min(point[axis] for point in layout) for axis in (0, 1)]
    maximum = [max(point[axis] for point in layout) for axis in (0, 1)]
    corners = [
        [minimum[0], minimum[1]],
        [maximum[0], minimum[1]],
        [maximum[0], maximum[1]],
        [minimum[0], maximum[1]],
    ]
    layer_corners = {
        name: affine_layer_corners(layout, source["uv_layers"][name], corners)
        for name in sorted(sampled | {selected})
    }
    bounds = precomputed_bounds
    if bounds is None:
        policy = atlas_policy or {"resolution": resolution, "margin_px": margin_px}
        bounds = resolve_atlas_tiles(policy, count, source_objects)[index]
    target = mapped_uvs(corners, bounds)
    mesh = bpy.data.meshes.new(f"CBM_SCALAR_PROXY_{index:04d}")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    mesh.materials.append(material)
    for name, values in layer_corners.items():
        layer = mesh.uv_layers.new(name=name)
        expected = [value for point in values for value in point]
        layer.uv.foreach_set("vector", expected)
        actual = [0.0] * len(expected)
        layer.uv.foreach_get("vector", actual)
        if actual != expected:
            bpy.data.meshes.remove(mesh)
            raise ValueError(
                "UV scalar bake ineligible: proxy source corners lose float32 precision"
            )
    atlas = mesh.uv_layers.new(name="CBMPortableAtlas")
    atlas.uv.foreach_set("vector", [value for point in target for value in point])
    mesh.uv_layers.active = atlas
    atlas.active_render = True
    mesh.update()
    for name, expected_points in {**layer_corners, "CBMPortableAtlas": target}.items():
        actual = [0.0] * 8
        mesh.uv_layers[name].uv.foreach_get("vector", actual)
        if actual != [component for point in expected_points for component in point]:
            bpy.data.meshes.remove(mesh)
            raise ValueError("UV scalar bake source/target Float2 storage changed")
    plane = bpy.data.objects.new(f"CBM_SCALAR_PROXY_{index:04d}", mesh)
    bpy.context.collection.objects.link(plane)
    record = {
        "name": obj.name,
        "material_id": source["identity"]["material_id"],
        "source_snapshot_sha256": snapshot_digest(source),
        "source_uv_set": selected,
        "source_bounds": minimum + maximum,
        "target_bounds": list(bounds),
        "target_corners": target,
        "sampled_uv_layers": sorted(sampled),
        "layer_corners": layer_corners,
        "dependencies": dependencies,
    }
    return plane, record


def remove_scalar_proxies(proxies):
    """Remove only temporary proxy objects/meshes so none can enter a saved converted scene."""
    for obj in proxies:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
