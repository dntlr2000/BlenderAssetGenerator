from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterable
from pathlib import Path

import bpy
from builders.registry import create_geometry
from compat import configure_render_compat, set_material_transparency
from mathutils import Vector
from modifiers import apply_deferred_modifiers, apply_immediate_modifiers

PACKAGE_SRC = Path(__file__).resolve().parents[2]
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from codex_blender_modeler.material_manifest import (  # noqa: E402
    MaterialManifestError,
    load_material_manifest,
)
from codex_blender_modeler.shader_recipe_runtime import (  # noqa: E402
    load_runtime_material_mappings as load_runtime_material_mappings,  # noqa: F401
)
from codex_blender_modeler.shader_recipe_runtime import (  # noqa: E402
    load_runtime_shader_recipes as load_runtime_shader_recipes,  # noqa: F401
)

_MATERIAL_PROVENANCE_KEYS = (
    "cbm_shader_recipe",
    "cbm_shader_family",
    "cbm_texture_strategy",
    "cbm_texture_manifest",
    "cbm_material_source_type",
    "cbm_uv_set",
    "cbm_intended_scale_m",
    "cbm_spatial_binding_count",
    "cbm_image_wrap",
    "cbm_sampling_mode",
    "cbm_spatial_bindings",
    "cbm_material_source_fingerprint",
    "cbm_shader_recipe_sha256",
    "cbm_texture_manifest_sha256",
)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.curves,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
    ):
        if datablocks is bpy.data.materials:
            continue
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def ensure_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def move_to_collection(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def _set_input(node: bpy.types.Node, name: str, value) -> None:
    """Set a shader input only when the running Blender version exposes it."""

    socket = node.inputs.get(name)
    if socket is not None:
        socket.default_value = value


def _set_first_input(node: bpy.types.Node, names: tuple[str, ...], value) -> bool:
    """Set the first compatible named shader socket exposed by Blender."""

    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return True
    return False


def _clear_material_provenance(material: bpy.types.Material) -> None:
    """Remove prior-build CBM metadata before repopulating current material evidence."""

    for key in _MATERIAL_PROVENANCE_KEYS:
        if key in material:
            del material[key]


def _coordinate_socket(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    manifest: dict,
    *,
    identity_uv: bool = False,
) -> bpy.types.NodeSocket:
    """Create deterministic world, object, generated, or UV coordinates at the declared scale."""

    mapping = nodes.new("ShaderNodeMapping")
    mapping.label = "CBM Spatial UV Identity" if identity_uv else "CBM Real-World Scale"
    scale = 1.0 if identity_uv else 1.0 / float(manifest["intended_scale_m"])
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    coordinate_kind = manifest.get("uv_set", "Object")
    if identity_uv:
        if coordinate_kind != "UVMap":
            raise RuntimeError("Spatial surface-detail manifests require UVMap coordinates")
        coordinates = nodes.new("ShaderNodeUVMap")
        coordinates.label = "CBM Spatial UVMap"
        coordinates.uv_map = str(coordinate_kind)
        links.new(coordinates.outputs["UV"], mapping.inputs["Vector"])
    elif coordinate_kind == "World":
        geometry = nodes.new("ShaderNodeNewGeometry")
        geometry.label = "CBM Shared World Coordinates"
        links.new(geometry.outputs["Position"], mapping.inputs["Vector"])
    else:
        coordinates = nodes.new("ShaderNodeTexCoord")
        coordinates.label = "CBM Texture Coordinates"
        coordinate_name = {
            "UVMap": "UV",
            "Generated": "Generated",
            "Object": "Object",
        }[coordinate_kind]
        links.new(coordinates.outputs[coordinate_name], mapping.inputs["Vector"])
    return mapping.outputs["Vector"]


def _image_node(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    vector_socket: bpy.types.NodeSocket,
    channel_name: str,
    channel: dict,
    *,
    extension: str = "REPEAT",
) -> bpy.types.Node:
    """Load one validated image channel with its declared Cycles color space."""

    node = nodes.new("ShaderNodeTexImage")
    node.name = f"CBM_{channel_name}"
    node.label = f"CBM {channel_name}"
    node.image = bpy.data.images.load(channel["resolved_path"], check_existing=True)
    node.image.colorspace_settings.name = channel["color_space"]
    node.extension = extension
    links.new(vector_socket, node.inputs["Vector"])
    return node


def _color_ramp_node(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    factor_socket: bpy.types.NodeSocket,
    label: str,
    entries: list,
) -> bpy.types.Node:
    """Build a reproducible ColorRamp from manifest position/color pairs."""

    if len(entries) < 2:
        raise RuntimeError(f"{label} requires at least two ramp entries")
    node = nodes.new("ShaderNodeValToRGB")
    node.name = f"CBM_{label}"
    node.label = f"CBM {label}"
    ramp = node.color_ramp
    while len(ramp.elements) > 2:
        ramp.elements.remove(ramp.elements[-1])
    ordered = sorted(entries, key=lambda item: float(item[0]))
    ramp.elements[0].position = float(ordered[0][0])
    ramp.elements[0].color = tuple(float(value) for value in ordered[0][1])
    ramp.elements[1].position = float(ordered[-1][0])
    ramp.elements[1].color = tuple(float(value) for value in ordered[-1][1])
    for position, color in ordered[1:-1]:
        element = ramp.elements.new(float(position))
        element.color = tuple(float(value) for value in color)
    links.new(factor_socket, node.inputs["Fac"])
    return node


def _noise_node(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    vector_socket: bpy.types.NodeSocket,
    procedural: dict,
) -> bpy.types.Node | None:
    """Create a seeded, parameterized Noise Texture when the manifest requests one."""

    settings = procedural.get("noise")
    if not settings:
        return None
    node = nodes.new("ShaderNodeTexNoise")
    node.name = "CBM_ProceduralNoise"
    node.label = f"CBM Noise seed={procedural.get('seed', 0)}"
    _set_input(node, "Scale", float(settings.get("scale", 4.0)))
    _set_input(node, "Detail", float(settings.get("detail", 3.0)))
    _set_input(node, "Roughness", float(settings.get("roughness", 0.5)))
    _set_input(node, "Distortion", float(settings.get("distortion", 0.0)))
    links.new(vector_socket, node.inputs["Vector"])
    return node


def _apply_manifest_graph(
    material: bpy.types.Material,
    shader: bpy.types.Node,
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    manifest: dict,
) -> None:
    """Apply the constrained image/procedural manifest graph to a Principled shader."""

    channels = manifest.get("channels", {})
    procedural = manifest.get("procedural", {})
    spatial_bindings = manifest.get("surface_detail_bindings", [])
    spatial_mode = bool(spatial_bindings)
    image_extension = "REPEAT"
    if spatial_mode:
        wrap = str(spatial_bindings[0]["wrap"])
        image_extension = {"clip": "CLIP", "clamp": "EXTEND"}[wrap]
    image_vector_socket = _coordinate_socket(
        nodes,
        links,
        manifest,
        identity_uv=spatial_mode,
    )
    procedural_vector_socket = image_vector_socket
    procedural_uv_set = procedural.get("coordinate_uv_set")
    if spatial_mode or procedural_uv_set is not None:
        procedural_vector_socket = _coordinate_socket(
            nodes,
            links,
            {
                "uv_set": procedural_uv_set or manifest["uv_set"],
                "intended_scale_m": procedural.get(
                    "coordinate_scale_m",
                    manifest["intended_scale_m"],
                ),
            },
        )
    noise = _noise_node(nodes, links, procedural_vector_socket, procedural)

    image_nodes = {
        name: _image_node(
            nodes,
            links,
            image_vector_socket,
            name,
            channel,
            extension=image_extension,
        )
        for name, channel in channels.items()
        if channel.get("source") == "image"
    }
    material["cbm_spatial_binding_count"] = len(spatial_bindings)
    material["cbm_image_wrap"] = image_extension
    material["cbm_sampling_mode"] = "spatial_uv_identity" if spatial_mode else "legacy_scaled"
    material["cbm_spatial_bindings"] = json.dumps(
        [
            {
                "detail_id": binding["detail_id"],
                "parent_object_id": binding["parent_object_id"],
                "uv_set": binding["uv_set"],
                "uv_layout_sha256": binding["uv_layout_sha256"],
                "wrap": binding["wrap"],
            }
            for binding in spatial_bindings
        ],
        sort_keys=True,
        separators=(",", ":"),
    )

    base_output = image_nodes.get("base_color")
    base_socket = base_output.outputs["Color"] if base_output else None
    base_ramp_entries = procedural.get("base_color_ramp")
    if base_ramp_entries:
        if noise is None:
            raise RuntimeError("base_color_ramp requires procedural.noise")
        ramp = _color_ramp_node(
            nodes,
            links,
            noise.outputs["Fac"],
            "Base Color Ramp",
            base_ramp_entries,
        )
        if base_socket is None:
            base_socket = ramp.outputs["Color"]
        else:
            mix = nodes.new("ShaderNodeMixRGB")
            mix.name = "CBM_BaseColorHybrid"
            mix.label = "CBM Image + Procedural Base Color"
            mix.blend_type = procedural.get("image_blend", "MULTIPLY")
            mix.inputs["Fac"].default_value = float(
                procedural.get("image_mix_factor", 0.45)
            )
            links.new(base_socket, mix.inputs[1])
            links.new(ramp.outputs["Color"], mix.inputs[2])
            base_socket = mix.outputs["Color"]
    if base_socket is not None and shader.inputs.get("Base Color") is not None:
        links.new(base_socket, shader.inputs["Base Color"])

    roughness_image = image_nodes.get("roughness")
    if roughness_image is not None:
        links.new(roughness_image.outputs["Color"], shader.inputs["Roughness"])
    elif procedural.get("roughness_ramp"):
        if noise is None:
            raise RuntimeError("roughness_ramp requires procedural.noise")
        roughness_ramp = _color_ramp_node(
            nodes,
            links,
            noise.outputs["Fac"],
            "Roughness Ramp",
            procedural["roughness_ramp"],
        )
        links.new(roughness_ramp.outputs["Color"], shader.inputs["Roughness"])

    metallic_image = image_nodes.get("metallic")
    if metallic_image is not None:
        links.new(metallic_image.outputs["Color"], shader.inputs["Metallic"])

    normal_socket = None
    normal_image = image_nodes.get("normal")
    if normal_image is not None:
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.name = "CBM_NormalMap"
        normal_map.inputs["Strength"].default_value = float(
            procedural.get("normal_strength", 1.0)
        )
        links.new(normal_image.outputs["Color"], normal_map.inputs["Color"])
        normal_socket = normal_map.outputs["Normal"]

    height_image = image_nodes.get("height")
    height_socket = height_image.outputs["Color"] if height_image is not None else None
    if height_socket is None and noise is not None and procedural.get("bump_strength", 0) > 0:
        height_socket = noise.outputs["Fac"]
    if height_socket is not None:
        bump = nodes.new("ShaderNodeBump")
        bump.name = "CBM_Bump"
        bump.label = "CBM Surface Relief"
        bump.inputs["Strength"].default_value = float(procedural.get("bump_strength", 0.15))
        bump.inputs["Distance"].default_value = float(procedural.get("bump_distance", 0.05))
        links.new(height_socket, bump.inputs["Height"])
        if normal_socket is not None:
            links.new(normal_socket, bump.inputs["Normal"])
        normal_socket = bump.outputs["Normal"]
    if normal_socket is not None:
        links.new(normal_socket, shader.inputs["Normal"])

    opacity_image = image_nodes.get("opacity")
    if opacity_image is not None and shader.inputs.get("Alpha") is not None:
        links.new(opacity_image.outputs["Color"], shader.inputs["Alpha"])
        set_material_transparency(material)

    emission_image = image_nodes.get("emission")
    if emission_image is not None:
        emission_socket = shader.inputs.get("Emission Color")
        if emission_socket is None:
            emission_socket = shader.inputs.get("Emission")
        if emission_socket is not None:
            links.new(emission_image.outputs["Color"], emission_socket)
            _set_first_input(
                shader,
                ("Emission Strength",),
                float(procedural.get("emission_strength", 1.0)),
            )


def _apply_shader_recipe_surface(
    material: bpy.types.Material,
    shader: bpy.types.Node,
    recipe: dict,
) -> tuple[float, float, float, float] | None:
    """Apply the portable Principled surface subset using feature-probed sockets."""

    surface = recipe.get("surface", {})
    socket_map = {
        "base_color": ("Base Color",),
        "metallic": ("Metallic",),
        "roughness": ("Roughness",),
        "ior": ("IOR",),
        "transmission_weight": ("Transmission Weight", "Transmission"),
        "alpha": ("Alpha",),
        "emission_color": ("Emission Color", "Emission"),
        "emission_strength": ("Emission Strength",),
        "coat_weight": ("Coat Weight", "Clearcoat"),
        "subsurface_weight": ("Subsurface Weight", "Subsurface"),
        "anisotropic": ("Anisotropic IOR Level", "Anisotropic"),
    }
    for field, value in surface.items():
        names = socket_map.get(field)
        if names is not None:
            _set_first_input(shader, names, tuple(value) if field.endswith("color") else value)
    base_color = surface.get("base_color")
    alpha = float(surface.get("alpha", base_color[3] if base_color else 1.0))
    if alpha < 1.0:
        set_material_transparency(material)
    return tuple(base_color) if base_color else None


def _apply_shader_recipe_layer(
    material: bpy.types.Material,
    shader: bpy.types.Node,
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    recipe: dict,
) -> None:
    """Translate one validated recipe Noise layer into the existing manifest graph."""

    layers = recipe.get("layers", [])
    if not layers:
        return
    layer = layers[0]
    parameters = layer["parameters"]
    noise = {"scale": parameters.get("scale", 4.0)}
    noise.update(
        {
            key: parameters[key]
            for key in ("detail", "roughness", "distortion")
            if key in parameters
        }
    )
    procedural = {"seed": parameters.get("seed", 0), "noise": noise}
    for key in (
        "base_color_ramp",
        "roughness_ramp",
        "bump_strength",
        "bump_distance",
    ):
        if key in parameters:
            procedural[key] = parameters[key]
    mapping = recipe["mapping"]
    manifest = {
        "channels": {},
        "procedural": procedural,
        "uv_set": {
            "uv": "UVMap",
            "object": "Object",
            "generated": "Generated",
        }[mapping["mode"]],
        "intended_scale_m": mapping["real_world_scale_m"],
    }
    _apply_manifest_graph(material, shader, nodes, links, manifest)


def make_material(
    spec: dict,
    base_dir: Path | None = None,
    shader_recipe: dict | None = None,
) -> bpy.types.Material:
    """Build a material from SceneSpec defaults and an optional constrained manifest."""

    material = bpy.data.materials.get(spec["id"]) or bpy.data.materials.new(spec["id"])
    material.use_nodes = True
    _clear_material_provenance(material)
    material["cbm_id"] = spec["id"]
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    shader_kind = spec.get("shader", "principled")
    color = tuple(spec.get("base_color", [0.8, 0.8, 0.8, 1.0]))
    roughness = float(spec.get("roughness", 0.5))
    metallic = float(spec.get("metallic", 0.0))
    effective_manifest_value = (
        shader_recipe.get("cbm_texture_manifest")
        if shader_recipe is not None
        else spec.get("texture_manifest")
    )

    principled_shader = None
    if shader_kind == "emissive" and not effective_manifest_value:
        shader = nodes.new("ShaderNodeEmission")
        shader.inputs["Color"].default_value = color
        shader.inputs["Strength"].default_value = float(spec.get("emission_strength", 3.0))
        links.new(shader.outputs["Emission"], output.inputs["Surface"])
    elif shader_kind == "cloud":
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        principled_shader = shader
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = max(roughness, 0.7)
        shader.inputs["Alpha"].default_value = min(color[3], 0.85)
        set_material_transparency(material)
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    else:
        shader = nodes.new("ShaderNodeBsdfPrincipled")
        principled_shader = shader
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = metallic
        if shader_kind == "emissive":
            _set_first_input(shader, ("Emission Color", "Emission"), color)
            _set_first_input(
                shader,
                ("Emission Strength",),
                float(spec.get("emission_strength", 3.0)),
            )
        if shader_kind in {"water", "glass"}:
            if "Transmission Weight" in shader.inputs:
                shader.inputs["Transmission Weight"].default_value = (
                    0.85 if shader_kind == "water" else 1.0
                )
            shader.inputs["IOR"].default_value = 1.333 if shader_kind == "water" else 1.45
            shader.inputs["Roughness"].default_value = min(roughness, 0.18)
            shader.inputs["Alpha"].default_value = min(color[3], 0.82)
            set_material_transparency(material)
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    if shader_recipe is not None:
        recipe_path = shader_recipe.get("cbm_recipe_path")
        if recipe_path:
            material["cbm_shader_recipe"] = recipe_path
        material["cbm_shader_family"] = shader_recipe.get("family", "standard_pbr")
        material["cbm_texture_strategy"] = shader_recipe.get(
            "cbm_texture_strategy", "none"
        )
        if principled_shader is not None:
            recipe_color = _apply_shader_recipe_surface(
                material,
                principled_shader,
                shader_recipe,
            )
            if recipe_color is not None:
                color = recipe_color
            if shader_recipe.get("layers") and effective_manifest_value:
                raise RuntimeError(
                    f"Material {spec['id']} cannot combine runtime recipe layers with "
                    "an image texture manifest"
                )
            _apply_shader_recipe_layer(
                material,
                principled_shader,
                nodes,
                links,
                shader_recipe,
            )

    effective_spec = dict(spec)
    if shader_recipe is not None:
        effective_spec["texture_manifest"] = shader_recipe.get("cbm_texture_manifest")
    if effective_spec.get("texture_manifest"):
        if base_dir is None:
            raise RuntimeError("base_dir is required when texture_manifest is set")
        try:
            manifest, manifest_path = load_material_manifest(effective_spec, base_dir)
        except MaterialManifestError as exc:
            raise RuntimeError(f"Material {spec['id']} manifest error: {exc}") from exc
        if manifest is not None:
            if principled_shader is None:
                raise RuntimeError(
                    f"Material {spec['id']} manifest requires a Principled-compatible shader"
                )
            _apply_manifest_graph(material, principled_shader, nodes, links, manifest)
            material["cbm_texture_manifest"] = str(manifest_path)
            material["cbm_material_source_type"] = manifest["source_type"]
            material["cbm_uv_set"] = manifest["uv_set"]
            material["cbm_intended_scale_m"] = manifest["intended_scale_m"]

    material.diffuse_color = color
    return material


def _activate(obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_object_spec(
    spec: dict,
    materials: dict[str, bpy.types.Material],
    collection: bpy.types.Collection,
    base_dir: Path,
    index: int = 0,
) -> bpy.types.Object:
    """Build one generated instance and attach stable SceneSpec provenance metadata."""

    generator = spec.get("generator")
    offset = (0.0, 0.0, 0.0)
    if generator:
        offset = tuple(float(value) * index for value in generator["offset"])

    transform = spec.get("transform", {})
    base_location = transform.get("location", [0.0, 0.0, 0.0])
    location = tuple(float(a) + float(b) for a, b in zip(base_location, offset, strict=True))

    obj = create_geometry(spec["geometry"], base_dir)
    obj.name = spec["id"] if index == 0 else f"{spec['id']}__{index:03d}"
    obj["cbm_id"] = spec["id"]
    obj["cbm_instance_index"] = index
    obj["cbm_geometry_kind"] = spec["geometry"]["kind"]
    obj["cbm_tags"] = ",".join(spec.get("tags", []))
    obj["cbm_declared_modifier_kinds"] = ",".join(
        modifier["kind"] for modifier in spec.get("modifiers", [])
    )
    obj["cbm_applied_modifier_kinds"] = ""
    obj.location = location
    obj.rotation_euler = [
        math.radians(value) for value in transform.get("rotation_deg", [0.0, 0.0, 0.0])
    ]
    obj.scale = tuple(float(value) for value in transform.get("scale", [1.0, 1.0, 1.0]))
    _activate(obj)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    if hasattr(obj.data, "materials"):
        obj.data.materials.append(materials[spec["material_id"]])
    if spec.get("shade_smooth", False) and obj.type == "MESH":
        for polygon in obj.data.polygons:
            polygon.use_smooth = True

    move_to_collection(obj, collection)
    apply_immediate_modifiers(obj, spec.get("modifiers", []))
    return obj


def apply_scene_relationships(
    object_specs: list[dict], object_map: dict[str, list[bpy.types.Object]]
) -> None:
    specs_by_id = {spec["id"]: spec for spec in object_specs}
    for object_id, objects in object_map.items():
        spec = specs_by_id[object_id]
        parent_id = spec.get("parent_id")
        for index, obj in enumerate(objects):
            if parent_id:
                parents = object_map[parent_id]
                obj.parent = parents[min(index, len(parents) - 1)]
            apply_deferred_modifiers(
                obj,
                spec.get("modifiers", []),
                object_map,
                index,
            )


def point_camera(camera_obj: bpy.types.Object, target: Iterable[float]) -> None:
    direction = Vector(target) - camera_obj.location
    camera_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_camera(spec: dict) -> bpy.types.Object:
    camera_data = bpy.data.cameras.new("CBM_ComparisonCamera")
    camera_obj = bpy.data.objects.new("CBM_ComparisonCamera", camera_data)
    bpy.context.scene.collection.objects.link(camera_obj)
    camera_obj.location = tuple(spec["location"])
    camera_data.type = spec["projection"]
    camera_data.lens = float(spec["focal_length_mm"])
    camera_data.ortho_scale = float(spec["ortho_scale"])
    point_camera(camera_obj, spec["target"])
    bpy.context.scene.camera = camera_obj
    width, height = spec["resolution"]
    bpy.context.scene.render.resolution_x = int(width)
    bpy.context.scene.render.resolution_y = int(height)
    bpy.context.scene.render.resolution_percentage = 100
    return camera_obj


def setup_lighting() -> None:
    world = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.15, 0.22, 0.35, 1.0)
        background.inputs["Strength"].default_value = 0.55

    light_data = bpy.data.lights.new("CBM_Key", type="AREA")
    light_data.energy = 1700
    light_data.shape = "DISK"
    light_data.size = 18
    light = bpy.data.objects.new("CBM_Key", light_data)
    light.location = (35, -40, 55)
    bpy.context.scene.collection.objects.link(light)
    point_camera(light, (0, 0, 0))

    sun_data = bpy.data.lights.new("CBM_Sun", type="SUN")
    sun_data.energy = 2.0
    sun = bpy.data.objects.new("CBM_Sun", sun_data)
    sun.rotation_euler = (math.radians(25), math.radians(-20), math.radians(-35))
    bpy.context.scene.collection.objects.link(sun)


def configure_render(render_engine: str = "EEVEE", render_device: str = "AUTO") -> None:
    """Configure deterministic image output with an explicitly requested renderer/device."""

    scene = bpy.context.scene
    configure_render_compat(scene, render_engine, render_device)
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = 64
        scene.cycles.use_denoising = True
        scene["cbm_cycles_samples"] = 64
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.resolution_percentage = 100


def ensure_parent(path: str | Path) -> Path:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
