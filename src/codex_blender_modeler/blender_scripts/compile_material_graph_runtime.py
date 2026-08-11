"""Compile a validated semantic MaterialGraph plan inside Blender 5."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import bpy

# Blender's --python runner does not add this fixed script directory to sys.path.
_SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if _SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, _SCRIPT_DIRECTORY)

from material_graph_runtime_registry import (  # noqa: E402
    PUBLIC_TEMPLATE_REGISTRY,
    REGISTRY_SHA256,
    registry_for_sha256,
)

BLENDER_NODE_TYPES = {
    "texture_coordinate": "ShaderNodeTexCoord",
    "mapping": "ShaderNodeMapping",
    "image_texture": "ShaderNodeTexImage",
    "noise_texture": "ShaderNodeTexNoise",
    "voronoi_texture": "ShaderNodeTexVoronoi",
    "wave_texture": "ShaderNodeTexWave",
    "gradient_texture": "ShaderNodeTexGradient",
    "color_ramp": "ShaderNodeValToRGB",
    "mix_color": "ShaderNodeMix",
    "math": "ShaderNodeMath",
    "separate_color": "ShaderNodeSeparateColor",
    "combine_color": "ShaderNodeCombineColor",
    "normal_map": "ShaderNodeNormalMap",
    "bump": "ShaderNodeBump",
    "fresnel": "ShaderNodeFresnel",
    "principled_bsdf": "ShaderNodeBsdfPrincipled",
    "transparent_bsdf": "ShaderNodeBsdfTransparent",
    "emission": "ShaderNodeEmission",
    "mix_shader": "ShaderNodeMixShader",
    "material_output": "ShaderNodeOutputMaterial",
}

INPUT_ALIASES = {
    "mapping": {
        "vector": ("Vector",),
        "scale": ("Scale",),
        "location": ("Location",),
    },
    "image_texture": {"vector": ("Vector",)},
    "noise_texture": {
        "vector": ("Vector",),
        "scale": ("Scale",),
        "detail": ("Detail",),
        "roughness": ("Roughness",),
        "lacunarity": ("Lacunarity",),
        "distortion": ("Distortion",),
    },
    "voronoi_texture": {
        "vector": ("Vector",),
        "scale": ("Scale",),
        "randomness": ("Randomness",),
    },
    "wave_texture": {
        "vector": ("Vector",),
        "scale": ("Scale",),
        "distortion": ("Distortion",),
        "detail": ("Detail",),
        "detail_scale": ("Detail Scale",),
        "detail_roughness": ("Detail Roughness",),
        "phase": ("Phase Offset",),
    },
    "gradient_texture": {"vector": ("Vector",)},
    "color_ramp": {"factor": ("Fac", "Factor")},
    "mix_color": {
        "factor": ("Factor", "Fac"),
        "color_a": ("A",),
        "color_b": ("B",),
    },
    "math": {"value_a": ("Value",), "value_b": ("Value",)},
    "separate_color": {"color": ("Color",)},
    "combine_color": {
        "red": ("Red", "R"),
        "green": ("Green", "G"),
        "blue": ("Blue", "B"),
    },
    "normal_map": {"color": ("Color",), "strength": ("Strength",)},
    "bump": {
        "height": ("Height",),
        "normal": ("Normal",),
        "strength": ("Strength",),
        "distance": ("Distance",),
    },
    "fresnel": {"ior": ("IOR",), "normal": ("Normal",)},
    "principled_bsdf": {
        "base_color": ("Base Color",),
        "roughness": ("Roughness",),
        "metallic": ("Metallic",),
        "normal": ("Normal",),
        "emission_color": ("Emission Color", "Emission"),
        "emission_strength": ("Emission Strength",),
        "alpha": ("Alpha",),
    },
    "transparent_bsdf": {"color": ("Color",)},
    "emission": {"color": ("Color",), "strength": ("Strength",)},
    "mix_shader": {
        "factor": ("Fac", "Factor"),
        "shader_a": ("Shader",),
        "shader_b": ("Shader",),
    },
    "material_output": {"surface": ("Surface",)},
}

INPUT_OCCURRENCES = {
    ("math", "value_b"): 1,
    ("mix_shader", "shader_b"): 1,
}

OUTPUT_ALIASES = {
    "texture_coordinate": {"uv": ("UV",)},
    "mapping": {"vector": ("Vector",)},
    "image_texture": {"color": ("Color",), "alpha": ("Alpha",)},
    "noise_texture": {"factor": ("Fac", "Factor"), "color": ("Color",)},
    "voronoi_texture": {"distance": ("Distance",), "color": ("Color",)},
    "wave_texture": {"factor": ("Fac", "Factor"), "color": ("Color",)},
    "gradient_texture": {"factor": ("Fac", "Factor"), "color": ("Color",)},
    "color_ramp": {"color": ("Color",), "alpha": ("Alpha",)},
    "mix_color": {"color": ("Result", "Color")},
    "math": {"value": ("Value",)},
    "separate_color": {
        "red": ("Red", "R"),
        "green": ("Green", "G"),
        "blue": ("Blue", "B"),
    },
    "combine_color": {"color": ("Color",)},
    "normal_map": {"normal": ("Normal",)},
    "bump": {"normal": ("Normal",)},
    "fresnel": {"factor": ("Fac", "Factor")},
    "principled_bsdf": {"bsdf": ("BSDF",)},
    "transparent_bsdf": {"bsdf": ("BSDF",)},
    "emission": {"shader": ("Emission", "Shader")},
    "mix_shader": {"shader": ("Shader",)},
}


class CompilerContractError(RuntimeError):
    """Signal a strict fixed-script contract or Blender feature failure."""


def _argv_after_separator() -> list[str]:
    """Return only arguments explicitly passed to this fixed Blender script."""

    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _parse_args() -> argparse.Namespace:
    """Parse bounded roots and one contained request path."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--request", required=True)
    return parser.parse_args(_argv_after_separator())


def _canonical_json_bytes(value: object, *, ascii_only: bool = False) -> bytes:
    """Serialize normalized evidence using deterministic JSON rules."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=ascii_only,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    """Hash an exact compiler input or output without interpreting its bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registry_sha256() -> str:
    """Return the current shared semantic registry digest."""

    return REGISTRY_SHA256


def _strict_keys(value: dict, expected: set[str], label: str) -> None:
    """Reject missing and undeclared fields, including raw Blender controls."""

    if not isinstance(value, dict) or set(value) != expected:
        raise CompilerContractError(f"{label} does not have the exact contract fields")


def _portable_id(value: object, label: str) -> str:
    """Validate a bounded portable identifier used only as data."""

    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise CompilerContractError(f"{label} is not a portable identifier")
    return value


def _validate_relative_path(value: object, label: str) -> str:
    """Reject absolute, escaping, empty, Windows, and non-normalized paths."""

    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise CompilerContractError(f"{label} must be a normalized relative path")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
        raise CompilerContractError(f"{label} contains an unsafe path segment")
    return value


def _resolve_contained(root: Path, relative_path: object, *, must_exist: bool) -> Path:
    """Resolve one path inside a declared root and reject symlink traversal."""

    normalized = _validate_relative_path(relative_path, "compiler path")
    candidate = root.joinpath(*normalized.split("/"))
    current = root
    for part in normalized.split("/"):
        current = current / part
        if current.is_symlink():
            raise CompilerContractError(f"compiler path traverses a symlink: {normalized}")
    try:
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(root.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise CompilerContractError(f"compiler path escapes or is missing: {normalized}") from exc
    if must_exist and not resolved.is_file():
        raise CompilerContractError(f"compiler input is not a file: {normalized}")
    return resolved


def _load_json(path: Path, label: str) -> dict:
    """Load one UTF-8 JSON object without executing embedded strings."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompilerContractError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CompilerContractError(f"{label} must be a JSON object")
    return value


def _load_request(run_root: Path, relative_path: str) -> tuple[Path, dict]:
    """Load the strict compile request from the unpublished run staging root."""

    request_path = _resolve_contained(run_root, relative_path, must_exist=True)
    request = _load_json(request_path, "compiler request")
    _strict_keys(
        request,
        {
            "schema_version",
            "request_id",
            "job_id",
            "workflow_id",
            "dispatch_id",
            "run_id",
            "registry_sha256",
            "plan_path",
            "plan_sha256",
            "dependency_manifest_path",
            "dependency_manifest_sha256",
            "portable_approximation_path",
            "neutral_preview_manifest_path",
            "reference_preview_manifest_path",
            "output_blend_path",
            "inventory_path",
            "report_path",
        },
        "compiler request",
    )
    if request["schema_version"] != "0.1.0":
        raise CompilerContractError("unsupported compiler request version")
    for key in ("request_id", "dispatch_id", "run_id"):
        _portable_id(request[key], f"request {key}")
    for key in (
        "plan_path",
        "dependency_manifest_path",
        "portable_approximation_path",
        "neutral_preview_manifest_path",
        "reference_preview_manifest_path",
        "output_blend_path",
        "inventory_path",
        "report_path",
    ):
        _validate_relative_path(request[key], f"request {key}")
    if registry_for_sha256(request["registry_sha256"]) is None:
        raise CompilerContractError("request registry SHA-256 mismatch")
    return request_path, request


def _validate_setting(setting_id: str, value: object, rule: dict) -> None:
    """Validate one inert semantic setting without interpreting expressions."""

    if rule["kind"] == "enum":
        if not isinstance(value, str) or value not in rule["values"]:
            raise CompilerContractError(f"setting {setting_id} is outside its enum")
        return
    if rule["kind"] == "dependency_id":
        _portable_id(value, f"setting {setting_id}")
        return
    if rule["kind"] == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CompilerContractError(f"setting {setting_id} requires a scalar")
        if not rule["minimum"] <= value <= rule["maximum"]:
            raise CompilerContractError(f"setting {setting_id} is outside its range")
        return
    if rule["kind"] == "boolean":
        if not isinstance(value, bool):
            raise CompilerContractError(f"setting {setting_id} requires a boolean")
        return
    raise CompilerContractError("unsupported semantic setting kind")


def _socket_type(rule: str | dict) -> str:
    """Read one legacy or bounded-v2 semantic socket type."""

    return rule if isinstance(rule, str) else rule["type"]


def _validate_default_range(values: tuple[float | int, ...], rule: str | dict) -> None:
    """Reject default values outside a bounded-v2 semantic socket declaration."""

    if isinstance(rule, str):
        return
    minimum = rule.get("minimum")
    maximum = rule.get("maximum")
    if minimum is None or maximum is None:
        return
    if any(not minimum <= item <= maximum for item in values):
        raise CompilerContractError("semantic socket default is outside its range")


def _validate_default(rule: str | dict, value: object) -> None:
    """Validate one semantic input default shape without raw socket access."""

    socket_type = _socket_type(rule)
    if socket_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CompilerContractError("float semantic socket requires a scalar")
        _validate_default_range((value,), rule)
        return
    expected = {"vector": 3, "color": 4}.get(socket_type)
    if expected is None or not isinstance(value, list) or len(value) != expected:
        raise CompilerContractError("semantic vector/color socket shape mismatch")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise CompilerContractError("semantic socket default contains a non-number")
    _validate_default_range(tuple(value), rule)


def _validate_template_constraints(template_id: str, settings: dict) -> None:
    """Check deterministic relationships not expressible as independent ranges."""

    if template_id == "color_ramp" and settings["position_0"] >= settings["position_1"]:
        raise CompilerContractError("color ramp position_0 must be lower than position_1")


def _validate_plan(plan: dict, request: dict) -> None:
    """Revalidate templates, sockets, caps, links, topological order, and depth."""

    _strict_keys(
        plan,
        {
            "schema_version",
            "plan_id",
            "graph_id",
            "material_id",
            "graph_spec_path",
            "graph_spec_sha256",
            "registry_sha256",
            "policy",
            "nodes",
            "links",
            "topological_order",
            "layer_count",
            "texture_count",
        },
        "normalized plan",
    )
    _strict_keys(
        plan["policy"],
        {
            "policy_id",
            "maximum_nodes",
            "maximum_layers",
            "maximum_depth",
            "maximum_textures",
        },
        "compiler policy",
    )
    if plan["schema_version"] != "0.1.0":
        raise CompilerContractError("unsupported normalized plan version")
    if plan["registry_sha256"] != request["registry_sha256"]:
        raise CompilerContractError("normalized plan registry SHA-256 mismatch")
    templates = registry_for_sha256(plan["registry_sha256"])
    if templates is None:
        raise CompilerContractError("normalized plan registry is unsupported")
    nodes = {}
    for node in plan["nodes"]:
        _strict_keys(
            node,
            {"node_id", "template_id", "settings", "input_defaults"},
            "runtime node",
        )
        node_id = _portable_id(node["node_id"], "runtime node ID")
        template_id = _portable_id(node["template_id"], "runtime template ID")
        template = templates.get(template_id)
        if template is None:
            raise CompilerContractError(f"unknown or forbidden runtime template: {template_id}")
        if node_id in nodes:
            raise CompilerContractError("duplicate runtime node ID")
        settings = {}
        for setting in node["settings"]:
            _strict_keys(setting, {"setting_id", "value"}, "runtime setting")
            setting_id = _portable_id(setting["setting_id"], "runtime setting ID")
            if setting_id in settings:
                raise CompilerContractError("duplicate runtime setting")
            settings[setting_id] = setting["value"]
        if set(settings) != set(template["settings"]):
            raise CompilerContractError("runtime node setting set is not exact")
        for setting_id, value in settings.items():
            _validate_setting(setting_id, value, template["settings"][setting_id])
        _validate_template_constraints(template_id, settings)
        defaults = set()
        for default in node["input_defaults"]:
            _strict_keys(default, {"socket_id", "value"}, "runtime socket default")
            socket_id = _portable_id(default["socket_id"], "runtime socket ID")
            if socket_id in defaults or socket_id not in template["inputs"]:
                raise CompilerContractError("runtime input default is duplicate or unknown")
            defaults.add(socket_id)
            _validate_default(template["inputs"][socket_id], default["value"])
        nodes[node_id] = node

    policy = plan["policy"]
    cap_ranges = {
        "maximum_nodes": (2, 128),
        "maximum_layers": (0, 16),
        "maximum_depth": (1, 32),
        "maximum_textures": (0, 32),
    }
    for key, (minimum, maximum) in cap_ranges.items():
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise CompilerContractError(f"{key} is not an integer")
        if not minimum <= value <= maximum:
            raise CompilerContractError(f"{key} is outside the hard limit")
    if len(nodes) > policy["maximum_nodes"]:
        raise CompilerContractError("runtime node cap exceeded")
    if plan["layer_count"] > policy["maximum_layers"]:
        raise CompilerContractError("runtime layer cap exceeded")
    if plan["texture_count"] > policy["maximum_textures"]:
        raise CompilerContractError("runtime texture cap exceeded")

    adjacency = defaultdict(set)
    indegree = {node_id: 0 for node_id in nodes}
    depths = {node_id: 1 for node_id in nodes}
    linked_inputs = set()
    link_ids = set()
    for link in plan["links"]:
        _strict_keys(
            link,
            {
                "link_id",
                "source_node_id",
                "source_socket_id",
                "target_node_id",
                "target_socket_id",
            },
            "runtime link",
        )
        link_id = _portable_id(link["link_id"], "runtime link ID")
        if link_id in link_ids:
            raise CompilerContractError("duplicate runtime link ID")
        link_ids.add(link_id)
        source = nodes.get(link["source_node_id"])
        target = nodes.get(link["target_node_id"])
        if source is None or target is None or source is target:
            raise CompilerContractError("runtime link has invalid endpoints")
        source_type = templates[source["template_id"]]["outputs"].get(link["source_socket_id"])
        target_rule = templates[target["template_id"]]["inputs"].get(link["target_socket_id"])
        target_type = None if target_rule is None else _socket_type(target_rule)
        if source_type is None or target_type is None:
            raise CompilerContractError("runtime link uses an unknown semantic socket")
        if source_type != target_type and (source_type, target_type) != ("color", "float"):
            raise CompilerContractError("runtime link semantic socket types are incompatible")
        target_key = (link["target_node_id"], link["target_socket_id"])
        if target_key in linked_inputs:
            raise CompilerContractError("runtime input socket has multiple links")
        linked_inputs.add(target_key)
        if link["target_node_id"] not in adjacency[link["source_node_id"]]:
            adjacency[link["source_node_id"]].add(link["target_node_id"])
            indegree[link["target_node_id"]] += 1
    ready = sorted(key for key, value in indegree.items() if value == 0)
    order = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target_id in sorted(adjacency[node_id]):
            depths[target_id] = max(depths[target_id], depths[node_id] + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
                ready.sort()
    if len(order) != len(nodes):
        raise CompilerContractError("runtime graph contains a cycle")
    if order != plan["topological_order"]:
        raise CompilerContractError("runtime graph topological order is not canonical")
    if max(depths.values(), default=0) > policy["maximum_depth"]:
        raise CompilerContractError("runtime graph depth cap exceeded")


def _load_dependencies(job_root: Path, path: Path, request: dict, plan: dict) -> dict:
    """Validate the complete dependency manifest and return exact ID bindings."""

    manifest = _load_json(path, "dependency manifest")
    _strict_keys(
        manifest,
        {
            "schema_version",
            "manifest_id",
            "job_id",
            "graph_id",
            "source_fingerprint",
            "dependencies",
        },
        "dependency manifest",
    )
    if manifest["schema_version"] != "0.1.0":
        raise CompilerContractError("unsupported dependency manifest version")
    if manifest["job_id"] != request["job_id"] or manifest["graph_id"] != plan["graph_id"]:
        raise CompilerContractError("dependency manifest identity binding mismatch")
    dependencies = {}
    paths = set()
    graph_dependencies = []
    material_plan_count = 0
    fingerprint_items = []
    for dependency in manifest["dependencies"]:
        _strict_keys(
            dependency,
            {"dependency_id", "role", "path", "sha256", "color_space"},
            "graph dependency",
        )
        dependency_id = _portable_id(dependency["dependency_id"], "graph dependency ID")
        if dependency_id in dependencies or dependency["path"] in paths:
            raise CompilerContractError("duplicate graph dependency ID or path")
        role = dependency["role"]
        if role not in {"graph_spec", "material_plan", "texture", "mask", "reference", "other"}:
            raise CompilerContractError("unknown graph dependency role")
        color_space = dependency["color_space"]
        if role in {"texture", "mask"}:
            if color_space not in {"sRGB", "Non-Color"}:
                raise CompilerContractError("texture dependency lacks exact color space")
        elif color_space is not None:
            raise CompilerContractError("non-texture dependency has a color space")
        resolved = _resolve_contained(job_root, dependency["path"], must_exist=True)
        if _sha256_file(resolved) != dependency["sha256"]:
            raise CompilerContractError(f"stale graph dependency: {dependency['path']}")
        dependencies[dependency_id] = {**dependency, "resolved_path": resolved}
        paths.add(dependency["path"])
        fingerprint_items.append({"path": dependency["path"], "sha256": dependency["sha256"]})
        if role == "graph_spec":
            graph_dependencies.append(dependency)
        if role == "material_plan":
            material_plan_count += 1
    expected_fingerprint = hashlib.sha256(
        _canonical_json_bytes(sorted(fingerprint_items, key=lambda item: item["path"]))
    ).hexdigest()
    if manifest["source_fingerprint"] != expected_fingerprint:
        raise CompilerContractError("dependency source fingerprint mismatch")
    if len(graph_dependencies) != 1 or material_plan_count < 1:
        raise CompilerContractError("dependency role requirements are incomplete")
    graph_dependency = graph_dependencies[0]
    if (
        graph_dependency["path"] != plan["graph_spec_path"]
        or graph_dependency["sha256"] != plan["graph_spec_sha256"]
    ):
        raise CompilerContractError("normalized plan graph-spec binding mismatch")
    for node in plan["nodes"]:
        if node["template_id"] != "image_texture":
            continue
        settings = {item["setting_id"]: item["value"] for item in node["settings"]}
        dependency = dependencies.get(settings["dependency_id"])
        if dependency is None or dependency["role"] != "texture":
            raise CompilerContractError("image node lacks a texture dependency")
        if dependency["color_space"] != settings["color_space"]:
            raise CompilerContractError("image node color-space binding mismatch")
    return dependencies


def _find_socket(collection, aliases: tuple[str, ...], label: str, *, occurrence: int = 0):
    """Feature-probe one Blender socket from a bounded alias set."""

    matches = [socket for socket in collection if socket.name in aliases]
    if occurrence < len(matches):
        return matches[occurrence]
    available = [socket.name for socket in collection]
    raise CompilerContractError(
        f"Blender socket unavailable for {label} occurrence {occurrence}: {available}"
    )


def _input_socket(node, template_id: str, socket_id: str):
    """Resolve one semantic input through the fixed private Blender alias table."""

    aliases = INPUT_ALIASES.get(template_id, {}).get(socket_id)
    if aliases is None:
        raise CompilerContractError("semantic input lacks a fixed Blender binding")
    return _find_socket(
        node.inputs,
        aliases,
        f"{template_id}.{socket_id}",
        occurrence=INPUT_OCCURRENCES.get((template_id, socket_id), 0),
    )


def _output_socket(node, template_id: str, socket_id: str):
    """Resolve one semantic output through the fixed private Blender alias table."""

    aliases = OUTPUT_ALIASES.get(template_id, {}).get(socket_id)
    if aliases is None:
        raise CompilerContractError("semantic output lacks a fixed Blender binding")
    return _find_socket(node.outputs, aliases, f"{template_id}.{socket_id}")


def _configure_image_node(node, settings: dict, dependencies: dict) -> None:
    """Load, pack, and configure one exact contained texture dependency."""

    dependency = dependencies[settings["dependency_id"]]
    image = bpy.data.images.load(str(dependency["resolved_path"]), check_existing=False)
    image.colorspace_settings.name = settings["color_space"]
    image.pack()
    image.filepath = dependency["path"]
    image["cbm_runtime_source_sha256"] = dependency["sha256"]
    node.image = image
    node["cbm_runtime_dependency_id"] = settings["dependency_id"]
    node.extension = {"repeat": "REPEAT", "clamp": "EXTEND", "clip": "CLIP"}[settings["sampling"]]


def _set_feature_property(node, property_name: str, value: object, label: str) -> None:
    """Set one fixed allowlisted RNA property and fail when Blender lacks the feature."""

    if not hasattr(node, property_name):
        raise CompilerContractError(f"Blender property unavailable for {label}")
    try:
        setattr(node, property_name, value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise CompilerContractError(f"Blender rejected fixed property value for {label}") from exc
    if getattr(node, property_name) != value:
        raise CompilerContractError(f"Blender did not preserve property value for {label}")


def _configure_color_ramp(node, settings: dict) -> None:
    """Configure one bounded two-stop RGBA ramp with a fixed interpolation subset."""

    ramp = getattr(node, "color_ramp", None)
    if ramp is None or len(ramp.elements) != 2:
        raise CompilerContractError("Blender two-stop Color Ramp feature is unavailable")
    ramp.interpolation = {
        "constant": "CONSTANT",
        "linear": "LINEAR",
        "ease": "EASE",
    }[settings["interpolation"]]
    for index in (0, 1):
        element = ramp.elements[index]
        element.position = settings[f"position_{index}"]
        element.color = (
            settings[f"red_{index}"],
            settings[f"green_{index}"],
            settings[f"blue_{index}"],
            settings[f"alpha_{index}"],
        )


def _configure_registered_node(node, template_id: str, settings: dict, dependencies: dict) -> None:
    """Apply only fixed per-template Blender properties selected by semantic enums."""

    if template_id == "image_texture":
        _configure_image_node(node, settings, dependencies)
    elif template_id == "noise_texture":
        _set_feature_property(
            node,
            "noise_dimensions",
            {"3d": "3D"}[settings["dimensions"]],
            "noise_texture.dimensions",
        )
    elif template_id == "voronoi_texture":
        _set_feature_property(
            node,
            "voronoi_dimensions",
            {"3d": "3D"}[settings["dimensions"]],
            "voronoi_texture.dimensions",
        )
        _set_feature_property(
            node,
            "feature",
            {"f1": "F1"}[settings["feature"]],
            "voronoi_texture.feature",
        )
        _set_feature_property(
            node,
            "distance",
            {
                "euclidean": "EUCLIDEAN",
                "manhattan": "MANHATTAN",
                "chebychev": "CHEBYCHEV",
            }[settings["distance_metric"]],
            "voronoi_texture.distance_metric",
        )
    elif template_id == "wave_texture":
        wave_type = {"bands": "BANDS", "rings": "RINGS"}[settings["wave_type"]]
        _set_feature_property(node, "wave_type", wave_type, "wave_texture.wave_type")
        direction_property = (
            "bands_direction" if settings["wave_type"] == "bands" else "rings_direction"
        )
        _set_feature_property(
            node,
            direction_property,
            {"x": "X", "y": "Y", "z": "Z"}[settings["direction"]],
            "wave_texture.direction",
        )
        _set_feature_property(
            node,
            "wave_profile",
            {"sine": "SIN", "saw": "SAW", "triangle": "TRI"}[settings["profile"]],
            "wave_texture.profile",
        )
    elif template_id == "gradient_texture":
        _set_feature_property(
            node,
            "gradient_type",
            {
                "linear": "LINEAR",
                "quadratic": "QUADRATIC",
                "easing": "EASING",
                "diagonal": "DIAGONAL",
                "radial": "RADIAL",
                "quadratic_sphere": "QUADRATIC_SPHERE",
                "spherical": "SPHERICAL",
            }[settings["gradient_type"]],
            "gradient_texture.gradient_type",
        )
    elif template_id == "color_ramp":
        _configure_color_ramp(node, settings)
    elif template_id == "mix_color":
        _set_feature_property(node, "data_type", "RGBA", "mix_color.data_type")
        _set_feature_property(
            node,
            "blend_type",
            {
                "mix": "MIX",
                "multiply": "MULTIPLY",
                "add": "ADD",
                "screen": "SCREEN",
                "overlay": "OVERLAY",
            }[settings["blend_mode"]],
            "mix_color.blend_mode",
        )
        _set_feature_property(
            node, "clamp_factor", settings["clamp_factor"], "mix_color.clamp_factor"
        )
        _set_feature_property(
            node, "clamp_result", settings["clamp_result"], "mix_color.clamp_result"
        )
    elif template_id == "math":
        _set_feature_property(
            node,
            "operation",
            {
                "add": "ADD",
                "subtract": "SUBTRACT",
                "multiply": "MULTIPLY",
                "divide": "DIVIDE",
                "minimum": "MINIMUM",
                "maximum": "MAXIMUM",
            }[settings["operation"]],
            "math.operation",
        )
        _set_feature_property(node, "use_clamp", settings["clamp"], "math.clamp")
    elif template_id in {"separate_color", "combine_color"}:
        _set_feature_property(
            node,
            "mode",
            {"rgb": "RGB"}[settings["mode"]],
            f"{template_id}.mode",
        )


def _new_registered_node(nodes, template_id: str):
    """Feature-probe creation of one fixed Blender node type from the private table."""

    node_type = BLENDER_NODE_TYPES.get(template_id)
    if node_type is None:
        raise CompilerContractError(f"template lacks a fixed Blender type: {template_id}")
    try:
        node = nodes.new(node_type)
    except RuntimeError as exc:
        raise CompilerContractError(
            f"Blender node type unavailable for semantic template: {template_id}"
        ) from exc
    if node.bl_idname != node_type:
        raise CompilerContractError(
            f"Blender created the wrong node type for semantic template: {template_id}"
        )
    return node


def _compile_graph(plan: dict, dependencies: dict, output_path: Path) -> None:
    """Create only registry-backed nodes, save the run-owned blend, and reopen it."""

    bpy.ops.wm.read_factory_settings(use_empty=True)
    material = bpy.data.materials.new(name=plan["material_id"])
    material.use_fake_user = True
    material.use_nodes = True
    node_tree = material.node_tree
    node_tree.nodes.clear()
    created = {}
    for node_plan in plan["nodes"]:
        template_id = node_plan["template_id"]
        node = _new_registered_node(node_tree.nodes, template_id)
        node.name = node_plan["node_id"]
        node.label = node_plan["node_id"]
        node["cbm_runtime_node_id"] = node_plan["node_id"]
        node["cbm_runtime_template_id"] = template_id
        settings = {item["setting_id"]: item["value"] for item in node_plan["settings"]}
        _configure_registered_node(node, template_id, settings, dependencies)
        for default in node_plan["input_defaults"]:
            socket = _input_socket(node, template_id, default["socket_id"])
            socket.default_value = default["value"]
        created[node_plan["node_id"]] = node
    for link in plan["links"]:
        source_plan = next(
            item for item in plan["nodes"] if item["node_id"] == link["source_node_id"]
        )
        target_plan = next(
            item for item in plan["nodes"] if item["node_id"] == link["target_node_id"]
        )
        source_socket = _output_socket(
            created[link["source_node_id"]],
            source_plan["template_id"],
            link["source_socket_id"],
        )
        target_socket = _input_socket(
            created[link["target_node_id"]],
            target_plan["template_id"],
            link["target_socket_id"],
        )
        node_tree.links.new(source_socket, target_socket)
    output_path.parent.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path), check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(output_path), load_ui=False)


def _numeric_values_match(actual: object, expected: object) -> bool:
    """Compare reopened Blender float32 socket/property values with a tight tolerance."""

    if isinstance(expected, (list, tuple)):
        try:
            actual_values = tuple(actual)
        except TypeError:
            return False
        return len(actual_values) == len(expected) and all(
            abs(float(left) - float(right)) <= 1e-6
            for left, right in zip(actual_values, expected, strict=True)
        )
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return abs(float(actual) - float(expected)) <= 1e-6
    return actual == expected


def _verify_color_ramp(node, settings: dict) -> None:
    """Verify the reopened bounded two-stop Color Ramp properties exactly enough."""

    ramp = getattr(node, "color_ramp", None)
    expected_interpolation = {
        "constant": "CONSTANT",
        "linear": "LINEAR",
        "ease": "EASE",
    }[settings["interpolation"]]
    if ramp is None or len(ramp.elements) != 2 or ramp.interpolation != expected_interpolation:
        raise CompilerContractError("reopened Color Ramp configuration differs")
    for index in (0, 1):
        element = ramp.elements[index]
        expected_color = (
            settings[f"red_{index}"],
            settings[f"green_{index}"],
            settings[f"blue_{index}"],
            settings[f"alpha_{index}"],
        )
        if not _numeric_values_match(element.position, settings[f"position_{index}"]):
            raise CompilerContractError("reopened Color Ramp position differs")
        if not _numeric_values_match(element.color, expected_color):
            raise CompilerContractError("reopened Color Ramp color differs")


def _verify_image_node(node, settings: dict, dependencies: dict) -> None:
    """Verify the reopened image dependency, color space, packing, and sampling."""

    dependency = dependencies[settings["dependency_id"]]
    expected_extension = {
        "repeat": "REPEAT",
        "clamp": "EXTEND",
        "clip": "CLIP",
    }[settings["sampling"]]
    if node.image is None or node.extension != expected_extension:
        raise CompilerContractError("reopened image texture configuration differs")
    if node.image.colorspace_settings.name != settings["color_space"]:
        raise CompilerContractError("reopened image texture color space differs")
    if node.image.packed_file is None:
        raise CompilerContractError("reopened image texture is not packed")
    if node.get("cbm_runtime_dependency_id") != settings["dependency_id"]:
        raise CompilerContractError("reopened image texture dependency ID differs")
    if node.image.get("cbm_runtime_source_sha256") != dependency["sha256"]:
        raise CompilerContractError("reopened image texture source digest differs")


def _expected_node_properties(template_id: str, settings: dict) -> dict[str, object]:
    """Map semantic settings to a fixed set of expected Blender RNA values."""

    if template_id == "noise_texture":
        return {"noise_dimensions": {"3d": "3D"}[settings["dimensions"]]}
    if template_id == "voronoi_texture":
        return {
            "voronoi_dimensions": {"3d": "3D"}[settings["dimensions"]],
            "feature": {"f1": "F1"}[settings["feature"]],
            "distance": {
                "euclidean": "EUCLIDEAN",
                "manhattan": "MANHATTAN",
                "chebychev": "CHEBYCHEV",
            }[settings["distance_metric"]],
        }
    if template_id == "wave_texture":
        direction_property = (
            "bands_direction" if settings["wave_type"] == "bands" else "rings_direction"
        )
        return {
            "wave_type": {"bands": "BANDS", "rings": "RINGS"}[settings["wave_type"]],
            direction_property: {"x": "X", "y": "Y", "z": "Z"}[settings["direction"]],
            "wave_profile": {"sine": "SIN", "saw": "SAW", "triangle": "TRI"}[settings["profile"]],
        }
    if template_id == "gradient_texture":
        return {
            "gradient_type": {
                "linear": "LINEAR",
                "quadratic": "QUADRATIC",
                "easing": "EASING",
                "diagonal": "DIAGONAL",
                "radial": "RADIAL",
                "quadratic_sphere": "QUADRATIC_SPHERE",
                "spherical": "SPHERICAL",
            }[settings["gradient_type"]]
        }
    if template_id == "mix_color":
        return {
            "data_type": "RGBA",
            "blend_type": {
                "mix": "MIX",
                "multiply": "MULTIPLY",
                "add": "ADD",
                "screen": "SCREEN",
                "overlay": "OVERLAY",
            }[settings["blend_mode"]],
            "clamp_factor": settings["clamp_factor"],
            "clamp_result": settings["clamp_result"],
        }
    if template_id == "math":
        return {
            "operation": {
                "add": "ADD",
                "subtract": "SUBTRACT",
                "multiply": "MULTIPLY",
                "divide": "DIVIDE",
                "minimum": "MINIMUM",
                "maximum": "MAXIMUM",
            }[settings["operation"]],
            "use_clamp": settings["clamp"],
        }
    if template_id in {"separate_color", "combine_color"}:
        return {"mode": {"rgb": "RGB"}[settings["mode"]]}
    return {}


def _verify_node_configuration(node, node_plan: dict, dependencies: dict) -> None:
    """Verify reopened node type, semantic settings, and declared socket defaults."""

    template_id = node_plan["template_id"]
    if node.bl_idname != BLENDER_NODE_TYPES[template_id]:
        raise CompilerContractError("reopened node has the wrong Blender type")
    settings = {item["setting_id"]: item["value"] for item in node_plan["settings"]}
    if template_id == "image_texture":
        _verify_image_node(node, settings, dependencies)
    elif template_id == "color_ramp":
        _verify_color_ramp(node, settings)
    else:
        for property_name, expected in _expected_node_properties(template_id, settings).items():
            if not hasattr(node, property_name) or not _numeric_values_match(
                getattr(node, property_name), expected
            ):
                raise CompilerContractError(
                    f"reopened node property differs: {template_id}.{property_name}"
                )
    for default in node_plan["input_defaults"]:
        socket = _input_socket(node, template_id, default["socket_id"])
        if not _numeric_values_match(socket.default_value, default["value"]):
            raise CompilerContractError(
                f"reopened socket default differs: {template_id}.{default['socket_id']}"
            )


def _inventory_graph(
    plan: dict, plan_sha256: str, registry_sha256: str, dependencies: dict
) -> dict:
    """Inspect the reopened Blender graph and normalize nodes, links, and socket aliases."""

    material = bpy.data.materials.get(plan["material_id"])
    if material is None or not material.use_nodes or material.node_tree is None:
        raise CompilerContractError("reopened compiled material is missing")
    node_tree = material.node_tree
    actual_nodes = {}
    node_entries = []
    principled_resolution = {}
    planned_nodes = {item["node_id"]: item for item in plan["nodes"]}
    for node in node_tree.nodes:
        node_id = node.get("cbm_runtime_node_id")
        template_id = node.get("cbm_runtime_template_id")
        if node_id is None or template_id is None:
            raise CompilerContractError("reopened graph contains an unregistered node")
        if node_id in actual_nodes:
            raise CompilerContractError("reopened graph has duplicate runtime node IDs")
        node_plan = planned_nodes.get(node_id)
        if node_plan is None or node_plan["template_id"] != template_id:
            raise CompilerContractError("reopened node identity differs from the plan")
        _verify_node_configuration(node, node_plan, dependencies)
        actual_nodes[node_id] = (node, template_id)
        node_entries.append({"node_id": node_id, "template_id": template_id})
        if template_id == "principled_bsdf":
            for socket_id in PUBLIC_TEMPLATE_REGISTRY[template_id]["inputs"]:
                principled_resolution[socket_id] = _input_socket(node, template_id, socket_id).name
    expected_nodes = {item["node_id"]: item["template_id"] for item in plan["nodes"]}
    actual_identity = {node_id: template_id for node_id, (_, template_id) in actual_nodes.items()}
    if actual_identity != expected_nodes:
        raise CompilerContractError("reopened node inventory differs from the plan")

    actual_link_keys = set()
    for link in node_tree.links:
        source_id = link.from_node.get("cbm_runtime_node_id")
        target_id = link.to_node.get("cbm_runtime_node_id")
        source_template = link.from_node.get("cbm_runtime_template_id")
        target_template = link.to_node.get("cbm_runtime_template_id")
        source_semantic = next(
            (
                socket_id
                for socket_id in PUBLIC_TEMPLATE_REGISTRY[source_template]["outputs"]
                if _output_socket(link.from_node, source_template, socket_id) == link.from_socket
            ),
            None,
        )
        target_semantic = next(
            (
                socket_id
                for socket_id in PUBLIC_TEMPLATE_REGISTRY[target_template]["inputs"]
                if _input_socket(link.to_node, target_template, socket_id) == link.to_socket
            ),
            None,
        )
        if source_semantic is None or target_semantic is None:
            raise CompilerContractError("reopened link uses an unregistered Blender socket")
        actual_link_keys.add((source_id, source_semantic, target_id, target_semantic))
    expected_link_keys = {
        (
            item["source_node_id"],
            item["source_socket_id"],
            item["target_node_id"],
            item["target_socket_id"],
        )
        for item in plan["links"]
    }
    if actual_link_keys != expected_link_keys:
        raise CompilerContractError("reopened link inventory differs from the plan")
    link_entries = [
        {
            "link_id": item["link_id"],
            "source_node_id": item["source_node_id"],
            "source_socket_id": item["source_socket_id"],
            "target_node_id": item["target_node_id"],
            "target_socket_id": item["target_socket_id"],
        }
        for item in sorted(plan["links"], key=lambda value: value["link_id"])
    ]
    core = {
        "graph_id": plan["graph_id"],
        "material_id": plan["material_id"],
        "registry_sha256": registry_sha256,
        "plan_sha256": plan_sha256,
        "nodes": sorted(node_entries, key=lambda value: value["node_id"]),
        "links": link_entries,
        "principled_socket_resolution": dict(sorted(principled_resolution.items())),
    }
    normalized_sha = hashlib.sha256(_canonical_json_bytes(core)).hexdigest()
    return {
        "schema_version": "0.1.0",
        "inventory_id": f"inventory-{plan['plan_id']}",
        **core,
        "normalized_inventory_sha256": normalized_sha,
    }


def _write_json_exclusive(path: Path, value: object) -> None:
    """Publish one deterministic JSON artifact without overwriting evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(_canonical_json_bytes(value) + b"\n")


def _artifact(role: str, run_root: Path, relative_path: str) -> dict:
    """Bind one contained compiler artifact to exact bytes and size."""

    path = _resolve_contained(run_root, relative_path, must_exist=True)
    return {
        "role": role,
        "path": relative_path,
        "sha256": _sha256_file(path),
        "byte_size": path.stat().st_size,
    }


def main() -> None:
    """Validate, compile, reopen, inventory, and report one atomic staging run."""

    args = _parse_args()
    job_root = Path(args.job_root).resolve(strict=True)
    run_root = Path(args.run_root).resolve(strict=True)
    if not job_root.is_dir() or not run_root.is_dir():
        raise CompilerContractError("job root and run root must be existing directories")
    request_path, request = _load_request(run_root, args.request)
    plan_path = _resolve_contained(run_root, request["plan_path"], must_exist=True)
    dependency_path = _resolve_contained(
        run_root, request["dependency_manifest_path"], must_exist=True
    )
    if _sha256_file(plan_path) != request["plan_sha256"]:
        raise CompilerContractError("normalized plan SHA-256 mismatch")
    if _sha256_file(dependency_path) != request["dependency_manifest_sha256"]:
        raise CompilerContractError("dependency manifest SHA-256 mismatch")
    plan = _load_json(plan_path, "normalized plan")
    _validate_plan(plan, request)
    dependencies = _load_dependencies(job_root, dependency_path, request, plan)
    output_path = _resolve_contained(run_root, request["output_blend_path"], must_exist=False)
    inventory_path = _resolve_contained(run_root, request["inventory_path"], must_exist=False)
    report_path = _resolve_contained(run_root, request["report_path"], must_exist=False)
    if output_path.exists() or inventory_path.exists() or report_path.exists():
        raise CompilerContractError("compiler output already exists")
    _compile_graph(plan, dependencies, output_path)
    inventory = _inventory_graph(
        plan,
        request["plan_sha256"],
        request["registry_sha256"],
        dependencies,
    )
    _write_json_exclusive(inventory_path, inventory)
    artifact_paths = [
        ("request", request_path.relative_to(run_root).as_posix()),
        ("normalized_plan", request["plan_path"]),
        ("dependency_manifest", request["dependency_manifest_path"]),
        ("compiled_blend", request["output_blend_path"]),
        ("normalized_inventory", request["inventory_path"]),
        ("portable_approximation", request["portable_approximation_path"]),
        ("neutral_preview_manifest", request["neutral_preview_manifest_path"]),
        ("reference_preview_manifest", request["reference_preview_manifest_path"]),
    ]
    report = {
        "schema_version": "0.1.0",
        "report_id": f"report-{request['run_id']}",
        "request_id": request["request_id"],
        "job_id": request["job_id"],
        "workflow_id": request["workflow_id"],
        "dispatch_id": request["dispatch_id"],
        "run_id": request["run_id"],
        "graph_id": plan["graph_id"],
        "material_id": plan["material_id"],
        "status": "passed",
        "ok": True,
        "blender_version": bpy.app.version_string,
        "blender_python_version": platform.python_version(),
        "registry_sha256": request["registry_sha256"],
        "normalized_plan_sha256": request["plan_sha256"],
        "normalized_inventory_sha256": inventory["normalized_inventory_sha256"],
        "artifacts": [_artifact(role, run_root, path) for role, path in artifact_paths],
        "canonical_material_unchanged": True,
        "canonical_scene_unchanged": True,
        "blend_bytes_deterministic": False,
        "warnings": ["Compiled .blend bytes are evidence, not a cross-run determinism claim."],
        "limitations": [
            "Determinism is bound to normalized plan and reopened inventory hashes.",
            "Neutral and reference-matched previews remain separate unrendered manifests.",
            "Destination runtime shader parity is unverified.",
        ],
        "completed_at": datetime.now(UTC).isoformat(),
    }
    _write_json_exclusive(report_path, report)


if __name__ == "__main__":
    main()
