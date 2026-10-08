"""Fixed native inspection/provenance finalization for explicit-profile authored identity splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = SCRIPT_DIR.parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from codex_blender_modeler import authored_split_runtime as runtime  # noqa: E402
from codex_blender_modeler.build_provenance import (  # noqa: E402
    canonical_json_text,
)
from codex_blender_modeler.paired_revision_runtime import _file  # noqa: E402


def file_sha256(path: Path) -> str:
    """Hash a trusted native executable or script in bounded streaming chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    """Accept only fixed source/candidate stages within one exact authored plan."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--stage", choices=("source", "candidate"), required=True)
    parser.add_argument("--finalize", action="store_true")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def matrix(value) -> list[list[float]]:
    """Preserve every native matrix component without display rounding."""
    return [[float(item) for item in row] for row in value]


def attributes(mesh) -> list[dict]:
    """Capture all supported native mesh attribute values with no silent omissions."""
    result = []
    fields = {
        "FLOAT": "value",
        "INT": "value",
        "BOOLEAN": "value",
        "INT8": "value",
        "FLOAT_VECTOR": "vector",
        "FLOAT2": "vector",
        "FLOAT_COLOR": "color",
        "BYTE_COLOR": "color",
        "INT32_2D": "value",
    }
    for attribute in sorted(mesh.attributes, key=lambda item: item.name):
        # Blender edit-selection UI flags are not geometry or authored custom attributes.
        if attribute.name in {".select_vert", ".select_edge", ".select_poly"}:
            continue
        field = fields.get(attribute.data_type)
        if field is None:
            raise ValueError("authored split native mesh has unsupported attribute type")
        values = []
        for item in attribute.data:
            value = getattr(item, field)
            values.append(list(value) if hasattr(value, "__len__") else value)
        result.append(
            {
                "name": attribute.name,
                "data_type": attribute.data_type,
                "domain": attribute.domain,
                "values": values,
            }
        )
    return result


def mesh_projection(mesh) -> dict:
    """Capture complete native position/topology/loop/UV/smoothing/attribute information."""
    full = {
        "vertices": [list(vertex.co) for vertex in mesh.vertices],
        "faces": [list(polygon.vertices) for polygon in mesh.polygons],
        "loops": [[loop.vertex_index, loop.edge_index] for loop in mesh.loops],
        "edges": [
            {
                "vertices": list(edge.vertices),
                "sharp": bool(edge.use_edge_sharp),
                "seam": bool(edge.use_seam),
            }
            for edge in mesh.edges
        ],
        "uv_layers": [
            {"name": layer.name, "uvs": [list(item.uv) for item in layer.data]}
            for layer in mesh.uv_layers
        ],
        "active_uv": mesh.uv_layers.active.name if mesh.uv_layers.active else None,
        "polygon_material_indices": [polygon.material_index for polygon in mesh.polygons],
        "smooth_polygon_flags": [bool(polygon.use_smooth) for polygon in mesh.polygons],
        "corner_normals": [list(item.vector) for item in mesh.corner_normals],
        "attributes": attributes(mesh),
    }
    # Hash every complete typed array; never sample or serialize a multi-megabyte
    # geometry diagnostic into the bounded authority JSON.
    result = {
        f"{key}_sha256": runtime.stable(full[key])
        for key in (
            "vertices",
            "faces",
            "uv_layers",
            "polygon_material_indices",
            "smooth_polygon_flags",
        )
    }
    result.update(
        full_geometry_sha256=runtime.stable(full),
        sharp_edges_sha256=runtime.stable(
            sorted(sorted(edge["vertices"]) for edge in full["edges"] if edge["sharp"])
        ),
        uv_seams_sha256=runtime.stable(
            sorted(sorted(edge["vertices"]) for edge in full["edges"] if edge["seam"])
        ),
        vertex_count=len(mesh.vertices),
        face_count=len(mesh.polygons),
        loop_count=len(mesh.loops),
        active_uv=full["active_uv"],
        uv_layer_names=[layer["name"] for layer in full["uv_layers"]],
    )
    return result


def inventory() -> dict:
    """Extract exact raw/evaluated geometry and the unchanged native camera/light setup."""
    objects, cameras, lights = {}, [], []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in sorted(bpy.context.scene.objects, key=lambda item: item.name):
        semantic = obj.get("cbm_id")
        static_id(obj)
        static_id(obj.data)
        if obj.constraints or getattr(obj.data, "shape_keys", None) is not None:
            raise ValueError("authored split does not support object constraints or shape keys")
        if obj.type == "MESH":
            if not isinstance(semantic, str) or semantic in objects or obj.modifiers or obj.parent:
                raise ValueError(
                    "authored split native source is not an exclusive unmodified solid"
                )
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
            try:
                objects[semantic] = {
                    "name": obj.name,
                    "matrix_world": matrix(obj.matrix_world),
                    "dimensions": list(obj.dimensions),
                    "native_custom": {key: scalar(value) for key, value in obj.items()},
                    "raw_mesh": mesh_projection(obj.data),
                    "evaluated_mesh": mesh_projection(mesh),
                    "materials": [
                        str(slot.material.get("cbm_id", "")) if slot.material else None
                        for slot in obj.material_slots
                    ],
                }
            finally:
                evaluated.to_mesh_clear()
        elif obj.type == "CAMERA":
            camera = obj.data
            cameras.append(
                {
                    "name": obj.name,
                    "matrix_world": matrix(obj.matrix_world),
                    "type": camera.type,
                    "lens": camera.lens,
                    "ortho_scale": camera.ortho_scale,
                    "shift_x": camera.shift_x,
                    "shift_y": camera.shift_y,
                    "clip_start": camera.clip_start,
                    "clip_end": camera.clip_end,
                    "sensor_width": camera.sensor_width,
                    "sensor_height": camera.sensor_height,
                }
            )
        elif obj.type == "LIGHT":
            lights.append(
                {
                    "name": obj.name,
                    "matrix_world": matrix(obj.matrix_world),
                    "type": obj.data.type,
                    "energy": obj.data.energy,
                    "color": list(obj.data.color),
                }
            )
        else:
            raise ValueError("authored split native scene has an unsupported extra object")
    return {
        "objects": objects,
        "cameras": cameras,
        "lights": lights,
        "active_camera": bpy.context.scene.camera.name if bpy.context.scene.camera else None,
    }


def material_images(root: Path) -> dict:
    """Bind every image texture node to exact contained physical media bytes."""
    result = {}
    for material in bpy.data.materials:
        identity = material.get("cbm_id")
        if not identity:
            continue
        refs = {}
        if material.node_tree:
            for node in material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image is not None:
                    path = Path(bpy.path.abspath(node.image.filepath)).resolve(strict=True)
                    relative = path.relative_to(root).as_posix()
                    refs[relative] = runtime.reference(root, relative)
        result[str(identity)] = [refs[key] for key in sorted(refs)]
    return result


# Only fixed built-in shader nodes emitted by the repository's constrained recipes.
SHADER_NODES = {
    "ShaderNodeBsdfPrincipled",
    "ShaderNodeOutputMaterial",
    "ShaderNodeEmission",
    "ShaderNodeBump",
    "ShaderNodeMapping",
    "ShaderNodeMixRGB",
    "ShaderNodeNewGeometry",
    "ShaderNodeNormalMap",
    "ShaderNodeTexCoord",
    "ShaderNodeTexImage",
    "ShaderNodeTexNoise",
    "ShaderNodeUVMap",
    "ShaderNodeValToRGB",
    "ShaderNodeMath",
    "ShaderNodeVectorMath",
    "ShaderNodeVolumeAbsorption",
    "ShaderNodeBackground",
    "ShaderNodeOutputWorld",
}
# ID bookkeeping and editor-only fields do not affect shading and are not stable on copy/reopen.
RNA_BOOKKEEPING = {
    "rna_type",
    "id_data",
    "name_full",
    "session_uid",
    "original",
    "users",
    "is_evaluated",
    "is_embedded_data",
    "is_runtime_data",
    "is_editable",
    "tag",
    "preview",
    "asset_data",
    "texture_paint_images",
    "texture_paint_slots",
    "paint_active_slot",
    "paint_clone_slot",
    "preview_render_type",
    "use_preview_world",
}
NODE_UI = {
    "location",
    "location_absolute",
    "width",
    "height",
    "dimensions",
    "select",
    "show_options",
    "show_preview",
    "show_texture",
    "hide",
    "use_custom_color",
    "color",
    "color_tag",
    "label",
    "warning_propagation",
}


def scalar(value, *, depth=0):
    """Copy a complete finite RNA/ID-property scalar or array, rejecting opaque objects."""
    if depth > 12:
        raise ValueError("authored split nested native metadata exceeds bound")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("authored split native scalar must be finite")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, dict):
        return {key: scalar(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, set):
        return sorted(value)
    if hasattr(value, "to_dict"):
        return scalar(value.to_dict(), depth=depth + 1)
    if hasattr(value, "__iter__") or hasattr(value, "__len__"):
        return [scalar(item, depth=depth + 1) for item in value]
    raise ValueError("authored split cannot inspect opaque native property")


def static_id(value):
    """Reject animation, drivers, linked IDs and library overrides rather than ignoring them."""
    if any(
        getattr(value, key, None) is not None
        for key in (
            "animation_data",
            "library",
            "library_weak_reference",
            "override_library",
        )
    ):
        raise ValueError("authored split supports only local static undriven native IDs")


def rna_state(value, *, skip=(), children=(), depth=0):
    """Capture every scalar RNA property and explicitly bounded nested setting collection."""
    if depth > 12:
        raise ValueError("authored split native settings exceed recursion bound")
    result = {}
    for prop in value.bl_rna.properties:
        key = prop.identifier
        if (
            key in RNA_BOOKKEEPING
            or key in skip
            or (key == "name" and isinstance(value, (bpy.types.ID, bpy.types.Node)))
        ):
            continue
        item = getattr(value, key)
        if prop.type in {"POINTER", "COLLECTION"}:
            if key in children:
                if prop.type == "COLLECTION":
                    if len(item) > 4096:
                        raise ValueError("authored split native setting collection exceeds bound")
                    result[key] = [
                        rna_state(entry, children=children, depth=depth + 1) for entry in item
                    ]
                else:
                    result[key] = (
                        None
                        if item is None
                        else rna_state(item, children=children, depth=depth + 1)
                    )
            elif item is not None and (prop.type == "POINTER" or len(item)):
                raise ValueError(
                    f"authored split unsupported native property {type(value).__name__}.{key}"
                )
            else:
                result[key] = None if prop.type == "POINTER" else []
        else:
            result[key] = scalar(item)
    return result


def custom_state(value, root):
    """Preserve all custom properties; normalize only declared contained graph locators."""
    result = {key: scalar(item) for key, item in value.items()}
    for key in ("cbm_texture_manifest", "cbm_shader_recipe", "cbm_source_spec"):
        if key in result:
            path = Path(result[key])
            if not path.is_absolute():
                path = root / path
            relative = path.resolve(strict=True).relative_to(root).as_posix()
            runtime.reference(root, relative)
            result[key] = relative
    return result


def image_state(image, root):
    """Bind clean external FILE bytes and all interpretation settings without decoding pixels."""
    static_id(image)
    if (
        image.source != "FILE"
        or image.type != "IMAGE"
        or image.use_multiview
        or image.is_dirty
        or image.packed_file
        or image.packed_files
    ):
        raise ValueError("authored split image must be a clean unpacked FILE image")
    path = Path(bpy.path.abspath(image.filepath)).resolve(strict=True)
    ref = runtime.reference(root, path.relative_to(root).as_posix())
    state = rna_state(
        image,
        skip={
            "filepath",
            "filepath_raw",
            "pixels",
            "packed_file",
            "packed_files",
            "tiles",
            "is_dirty",
            "has_data",
            "bindcode",
            "render_slots",
            "views",
        },
        children={"colorspace_settings", "stereo_3d_format"},
    )
    return {"bytes_sha256": ref["sha256"], "settings": state, "custom": custom_state(image, root)}


def node_graph(tree, root):
    """Digest all static built-in nodes, sockets, values, links, ramps and image interpretation."""
    static_id(tree)
    if len(tree.nodes) > 1024 or len(tree.links) > 4096:
        raise ValueError("authored split shader graph exceeds fixed node/link bound")
    nodes = []
    for node in tree.nodes:
        if node.bl_idname not in SHADER_NODES and node.bl_idname != "ShaderNodeGroup":
            raise ValueError("authored split unsupported shader node")
        if node.parent is not None:
            raise ValueError("authored split unsupported node parenting")
        state = rna_state(
            node,
            skip=NODE_UI | {"inputs", "outputs", "internal_links", "image", "node_tree"},
            children={
                "texture_mapping",
                "color_mapping",
                "color_ramp",
                "elements",
                "image_user",
            },
        )
        state["name"] = node.name
        state["custom"] = custom_state(node, root)
        for side in ("inputs", "outputs"):
            state[side] = [
                rna_state(socket, skip={"node", "links"}) for socket in getattr(node, side)
            ]
        state["internal_links"] = [
            [list(node.inputs).index(link.from_socket), list(node.outputs).index(link.to_socket)]
            for link in node.internal_links
        ]
        if node.bl_idname == "ShaderNodeGroup":
            group = node.node_tree
            # The sole supported group is the repository's empty optical-volume export marker.
            if (
                node.name != "CBM_OpticalVolume_Thickness"
                or group is None
                or not group.name.startswith("glTF Material Output")
                or group.nodes
                or group.links
                or len(group.interface.items_tree) != 1
            ):
                raise ValueError("authored split unsupported shader group")
            static_id(group)
            state["group_interface"] = [
                rna_state(item, skip={"parent"}) for item in group.interface.items_tree
            ]
            state["group_custom"] = custom_state(group, root)
        if node.bl_idname == "ShaderNodeTexImage":
            state["image"] = None if node.image is None else image_state(node.image, root)
        nodes.append(state)
    links = [
        [
            link.from_node.name,
            list(link.from_node.outputs).index(link.from_socket),
            link.to_node.name,
            list(link.to_node.inputs).index(link.to_socket),
            rna_state(link, skip={"from_node", "from_socket", "to_node", "to_socket"}),
        ]
        for link in tree.links
    ]
    return {
        "nodes": nodes,
        "links": links,
        "custom": custom_state(tree, root),
        "settings": rna_state(tree, skip={"nodes", "links", "interface", "view_center"}),
    }


def native_materials(root):
    """Inspect every material, including retained originals, with no unbound extra material."""
    result = {}
    for material in bpy.data.materials:
        identity = material.get("cbm_id")
        if not isinstance(identity, str) or identity in result:
            raise ValueError("authored split native material identity is missing or duplicate")
        static_id(material)
        if material.node_tree is None or not material.use_nodes:
            raise ValueError("authored split material requires a complete node graph")
        graph = node_graph(material.node_tree, root)
        settings = rna_state(material, skip={"node_tree"}, children={"lineart", "cycles"})
        result[identity] = {
            "graph_sha256": runtime.stable(graph),
            "settings_sha256": runtime.stable(settings),
            "custom": custom_state(material, root),
        }
    return result


def object_render_state(obj, root):
    """Bind complete object render flags and static camera/light settings and shader nodes."""
    static_id(obj)
    static_id(obj.data)
    if obj.constraints or getattr(obj.data, "shape_keys", None) is not None:
        raise ValueError("authored split does not support constraints or shape keys")
    value = rna_state(
        obj,
        skip={
            "data",
            "material_slots",
            "users_collection",
            "users_scene",
            "active_material",
            "animation_visualization",
            "bound_box",
            "dimensions",
            "matrix_world",
            "matrix_basis",
            "matrix_local",
        },
        children={
            "cycles",
            "visibility",
            "field",
            "collision",
            "light_linking",
            "display",
            "lineart",
        },
    )
    value["name"] = obj.name
    value["collections"] = sorted(collection.name for collection in obj.users_collection)
    if obj.type in {"CAMERA", "LIGHT"}:
        value["data"] = rna_state(
            obj.data,
            skip={"node_tree"},
            children={
                "dof",
                "cycles",
                "cycles_custom",
                "stereo",
                "falloff_curve",
                "curves",
                "points",
            },
        )
        value["data_custom"] = custom_state(obj.data, root)
        tree = getattr(obj.data, "node_tree", None)
        if tree is not None:
            if any(node.bl_idname == "ShaderNodeTexImage" for node in tree.nodes):
                raise ValueError("authored split does not support external light textures")
            value["graph"] = node_graph(tree, root)
    return value


def collection_state(collection, *, depth=0):
    """Bind bounded render collection membership and exclusions without accepting extra users."""
    if depth > 32 or len(collection.children) > 128 or len(collection.objects) > 256:
        raise ValueError("authored split scene collection exceeds bound")
    return {
        "name": collection.name,
        "hide_render": collection.hide_render,
        "objects": sorted(obj.name for obj in collection.objects),
        "children": [collection_state(child, depth=depth + 1) for child in collection.children],
    }


def layer_collection_state(layer, *, depth=0):
    """Bind the exact view-layer visibility/holdout interpretation of the same collection tree."""
    if depth > 32 or len(layer.children) > 128:
        raise ValueError("authored split view-layer collection exceeds bound")
    return {
        "name": layer.name,
        "exclude": layer.exclude,
        "holdout": layer.holdout,
        "indirect_only": layer.indirect_only,
        "hide_viewport": layer.hide_viewport,
        "children": [layer_collection_state(child, depth=depth + 1) for child in layer.children],
    }


def render_state(root):
    """Bind world graph and complete render/color-management state preserved by source cloning."""
    scene = bpy.context.scene
    static_id(scene)
    if scene.compositing_node_group is not None or (
        scene.sequence_editor is not None and len(scene.sequence_editor.strips)
    ):
        raise ValueError("authored split does not support compositor or sequence processing")
    world = scene.world
    if world is not None:
        static_id(world)
        if world.node_tree and any(
            node.bl_idname == "ShaderNodeTexImage" for node in world.node_tree.nodes
        ):
            raise ValueError("authored split does not support external world textures")
    if len(bpy.data.scenes) != 1 or len(scene.view_layers) != 1 or scene.render.use_freestyle:
        raise ValueError("authored split requires one scene/view layer without Freestyle")
    state = {
        "objects": [
            object_render_state(obj, root)
            for obj in sorted(scene.objects, key=lambda obj: obj.name)
        ],
        "collections": collection_state(scene.collection),
        "view_layer": layer_collection_state(scene.view_layers[0].layer_collection),
        "view_layer_settings": rna_state(
            scene.view_layers[0],
            skip={
                "objects",
                "layer_collection",
                "active_layer_collection",
                "depsgraph",
                "freestyle_settings",
            },
            children={"cycles", "eevee", "aovs", "lightgroups"},
        ),
        "world": None
        if world is None
        else {
            "settings": rna_state(
                world,
                skip={"node_tree"},
                children={"light_settings", "mist_settings", "cycles", "cycles_visibility"},
            ),
            "graph": node_graph(world.node_tree, root) if world.node_tree else None,
            "custom": custom_state(world, root),
        },
        "render": rna_state(
            scene.render,
            children={
                "image_settings",
                "view_settings",
                "display_settings",
                "linear_colorspace_settings",
                "motion_blur_shutter_curve",
                "ffmpeg",
                "bake",
                "stereo_3d_format",
                "views",
                "stereo_views",
                "curve_mapping",
                "curves",
                "points",
            },
        ),
        "view": rna_state(scene.view_settings, children={"curve_mapping", "curves", "points"}),
        "display": rna_state(scene.display_settings),
        "sequencer": rna_state(scene.sequencer_colorspace_settings),
        "cycles": rna_state(scene.cycles),
        "eevee": rna_state(scene.eevee, children={"ray_tracing_options"}),
        "frame": [scene.frame_current, scene.frame_subframe],
    }
    return runtime.stable(state)


def clone_source_materials(root, checked):
    """Copy source graphs with only exact assignment and metadata-locator changes."""
    plan = checked["plan"]
    # Fully inspect the input before copying; unsupported executable/dynamic graphs fail closed.
    native_materials(root)
    render_state(root)
    materials = {material["cbm_id"]: material for material in bpy.data.materials}
    objects = {obj.get("cbm_id"): obj for obj in bpy.context.scene.objects if obj.type == "MESH"}
    # The exact prebuilt bytes move from shadow to canonical, so retain absolute contained
    # image locators for originals as well as clones; Blender must not remap on save.
    for material in materials.values():
        for node in material.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                path = Path(bpy.path.abspath(node.image.filepath)).resolve(strict=True)
                runtime.reference(root, path.relative_to(root).as_posix())
                node.image.filepath = str(path)
    copied_images = {}
    for rule, derivative, geometry in zip(
        plan["clone_rules"], plan["material_derivatives"], plan["derivatives"], strict=True
    ):
        source = materials[rule["source_material_id"]]
        clone = source.copy()
        clone.name = rule["new_material_id"]
        expected = runtime.cloned_native_metadata(custom_state(source, root), rule, derivative)
        for key, value in expected.items():
            clone[key] = (
                str(root / value) if key in {"cbm_texture_manifest", "cbm_shader_recipe"} else value
            )
        for node in clone.node_tree.nodes:
            if node.bl_idname != "ShaderNodeTexImage" or node.image is None:
                continue
            image = node.image
            path = (
                Path(bpy.path.abspath(image.filepath))
                .resolve(strict=True)
                .relative_to(root)
                .as_posix()
            )
            target = derivative["media_copies"].get(path)
            if target is None:
                raise ValueError("authored split clone image lacks an exact declared copy")
            key = (image.name, target["path"])
            if key not in copied_images:
                copied = image.copy()
                copied.filepath = str(root / target["path"])
                copied_images[key] = copied
            node.image = copied_images[key]
        obj = objects[rule["target_object_id"]]
        if len(obj.material_slots) != 1 or obj.material_slots[0].material != source:
            raise ValueError("authored split source slot is not exclusive")
        obj.data.materials[0] = clone
        payload = json.loads(runtime.read(root, geometry["candidate"]))
        for key, value in runtime.native_mesh_metadata(payload, geometry["candidate"]).items():
            obj[key] = value
        if "cbm_source_fingerprint" in obj:
            obj["cbm_source_fingerprint"] = payload["source_fingerprint_sha256"]
    for obj in objects.values():
        if "cbm_assembly_modeling_plan_sha256" in obj:
            obj["cbm_assembly_modeling_plan_sha256"] = plan["candidate_modeling_plan"]["sha256"]
    projected = runtime.cloned_native_scene_metadata(
        custom_state(bpy.context.scene, root),
        plan,
        checked["candidates"]["prospective_build_provenance"],
        {identity: {"name": obj.name} for identity, obj in objects.items()},
    )
    for key, value in projected.items():
        bpy.context.scene[key] = str(root / value) if key == "cbm_source_spec" else value


def main() -> None:
    """Inspect fixed native inputs or finalize only the exact candidate's prospective provenance."""
    args = parse_args()
    root = Path(args.job_root).resolve(strict=True)
    plan_ref = {"path": args.plan, "sha256": args.plan_sha256}
    checked = runtime.validate_plan(root, plan_ref, current=True)
    plan, base = checked["plan"], runtime.prefix(checked["plan"]["run_id"])
    if bpy.app.version_string != "5.0.1":
        raise ValueError("authored split native evidence requires Blender 5.0.1")
    if args.finalize and args.stage != "candidate":
        raise ValueError("authored split can finalize only the isolated candidate")
    expected_path = root / (
        "blender/scene.blend"
        if args.stage == "source" or args.finalize
        else f"{base}/shadow/{'build' if args.finalize else 'final'}.blend"
    )
    if Path(bpy.data.filepath).resolve(strict=True) != expected_path.resolve(strict=True):
        raise ValueError("authored split native process loaded another Blend")
    stored = json.loads(str(bpy.context.scene.get("cbm_build_provenance", "null")))
    expected = checked["candidates"][
        "source_build_provenance" if args.stage == "source" else "prospective_build_provenance"
    ]
    if args.finalize:
        if runtime.stable(stored) != runtime.stable(
            checked["candidates"]["source_build_provenance"]
        ):
            raise ValueError("authored split source Blend provenance is stale")
        clone_source_materials(root, checked)
        # Exact source appearance is preserved; only declared assignments and provenance change.
        bpy.context.scene["cbm_build_provenance"] = canonical_json_text(expected)
        bpy.context.scene["cbm_material_build_fingerprint"] = expected["fingerprint"]
        bpy.context.scene["cbm_scene_spec_sha256"] = expected["scene_spec_sha256"]
        bpy.context.scene["cbm_camera_fingerprint"] = expected["camera_fingerprint"]
        output = _file(root, f"{base}/shadow/final.blend", exists=False)
        if output.exists():
            raise FileExistsError("authored split native final Blend already exists")
        bpy.ops.wm.save_as_mainfile(filepath=str(output), relative_remap=False)
        return
    if runtime.stable(stored) != runtime.stable(expected):
        raise ValueError("authored split native embedded provenance differs from the exact plan")
    body = inventory()
    report = {
        "schema_version": "0.2.0",
        "profile": plan["profile"],
        "job_id": root.name,
        "run_id": plan["run_id"],
        "plan": plan_ref,
        "stage": args.stage,
        "blender_version": bpy.app.version_string,
        "blender_executable_sha256": file_sha256(Path(bpy.app.binary_path)),
        "native_script_sha256": file_sha256(Path(__file__)),
        "blend": runtime.reference(root, expected_path.relative_to(root).as_posix()),
        "build_provenance": stored,
        "material_images": material_images(root),
        "native_materials": native_materials(root),
        "scene_custom": custom_state(bpy.context.scene, root),
        "render_state_sha256": render_state(root),
        **body,
        "appearance_or_human_acceptance": False,
    }
    output = _file(root, f"{base}/{args.stage}_native.json", exists=False)
    content = runtime.encode(report)
    if len(content) > 8 * 1024 * 1024:
        raise ValueError("authored split native inventory exceeds bounded JSON size")
    with output.open("xb") as stream:
        stream.write(content)


if __name__ == "__main__":
    main()
