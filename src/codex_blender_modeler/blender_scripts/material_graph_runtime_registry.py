"""Blender-independent semantic data for the fixed MaterialGraph compiler."""

from __future__ import annotations

import hashlib
import json
from typing import Any

LEGACY_REGISTRY_VERSION = "material_graph_runtime_registry_v1"
REGISTRY_VERSION = "material_graph_runtime_registry_v2"


def _float_socket(minimum: float, maximum: float) -> dict[str, object]:
    """Describe one bounded scalar socket without naming a Blender socket."""

    return {"type": "float", "minimum": minimum, "maximum": maximum}


def _vector_socket(minimum: float, maximum: float) -> dict[str, object]:
    """Describe one component-bounded three-dimensional vector socket."""

    return {"type": "vector", "minimum": minimum, "maximum": maximum}


def _color_socket(minimum: float = 0.0, maximum: float = 1.0) -> dict[str, object]:
    """Describe one component-bounded RGBA color socket."""

    return {"type": "color", "minimum": minimum, "maximum": maximum}


def _shader_socket() -> dict[str, object]:
    """Describe one link-only shader socket that cannot receive a JSON default."""

    return {"type": "shader"}


def _enum_setting(*values: str) -> dict[str, object]:
    """Describe one closed semantic enum setting."""

    return {"kind": "enum", "values": list(values)}


def _float_setting(minimum: float, maximum: float) -> dict[str, object]:
    """Describe one bounded scalar node setting."""

    return {"kind": "float", "minimum": minimum, "maximum": maximum}


def _boolean_setting() -> dict[str, object]:
    """Describe one strict boolean node setting."""

    return {"kind": "boolean"}


# Keep this exact semantic v1 payload byte-compatible for historical plan validation.
LEGACY_TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "texture_coordinate": {
        "inputs": {},
        "outputs": {"uv": "vector"},
        "settings": {},
    },
    "mapping": {
        "inputs": {"vector": "vector", "scale": "vector", "location": "vector"},
        "outputs": {"vector": "vector"},
        "settings": {},
    },
    "image_texture": {
        "inputs": {"vector": "vector"},
        "outputs": {"color": "color", "alpha": "float"},
        "settings": {
            "dependency_id": {"kind": "dependency_id"},
            "color_space": {"kind": "enum", "values": ["sRGB", "Non-Color"]},
            "sampling": {
                "kind": "enum",
                "values": ["repeat", "clamp", "clip"],
            },
        },
    },
    "normal_map": {
        "inputs": {"color": "color", "strength": "float"},
        "outputs": {"normal": "vector"},
        "settings": {},
    },
    "bump": {
        "inputs": {
            "height": "float",
            "normal": "vector",
            "strength": "float",
            "distance": "float",
        },
        "outputs": {"normal": "vector"},
        "settings": {},
    },
    "principled_bsdf": {
        "inputs": {
            "base_color": "color",
            "roughness": "float",
            "metallic": "float",
            "normal": "vector",
            "emission_color": "color",
            "emission_strength": "float",
            "alpha": "float",
        },
        "outputs": {"bsdf": "shader"},
        "settings": {},
    },
    "material_output": {
        "inputs": {"surface": "shader"},
        "outputs": {},
        "settings": {},
    },
}


PUBLIC_TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "texture_coordinate": {
        "inputs": {},
        "outputs": {"uv": "vector"},
        "settings": {},
    },
    "mapping": {
        "inputs": {
            "vector": _vector_socket(-1_000_000.0, 1_000_000.0),
            "scale": _vector_socket(0.000001, 1_000_000.0),
            "location": _vector_socket(-1_000_000.0, 1_000_000.0),
        },
        "outputs": {"vector": "vector"},
        "settings": {},
    },
    "image_texture": {
        "inputs": {"vector": _vector_socket(-1_000_000.0, 1_000_000.0)},
        "outputs": {"color": "color", "alpha": "float"},
        "settings": {
            "dependency_id": {"kind": "dependency_id"},
            "color_space": _enum_setting("sRGB", "Non-Color"),
            "sampling": _enum_setting("repeat", "clamp", "clip"),
        },
    },
    "noise_texture": {
        "inputs": {
            "vector": _vector_socket(-1_000_000.0, 1_000_000.0),
            "scale": _float_socket(0.0001, 100_000.0),
            "detail": _float_socket(0.0, 15.0),
            "roughness": _float_socket(0.0, 1.0),
            "lacunarity": _float_socket(0.0, 100.0),
            "distortion": _float_socket(0.0, 1_000.0),
        },
        "outputs": {"factor": "float", "color": "color"},
        "settings": {"dimensions": _enum_setting("3d")},
    },
    "voronoi_texture": {
        "inputs": {
            "vector": _vector_socket(-1_000_000.0, 1_000_000.0),
            "scale": _float_socket(0.0001, 100_000.0),
            "randomness": _float_socket(0.0, 1.0),
        },
        "outputs": {"distance": "float", "color": "color"},
        "settings": {
            "dimensions": _enum_setting("3d"),
            "feature": _enum_setting("f1"),
            "distance_metric": _enum_setting("euclidean", "manhattan", "chebychev"),
        },
    },
    "wave_texture": {
        "inputs": {
            "vector": _vector_socket(-1_000_000.0, 1_000_000.0),
            "scale": _float_socket(0.0001, 100_000.0),
            "distortion": _float_socket(0.0, 1_000.0),
            "detail": _float_socket(0.0, 15.0),
            "detail_scale": _float_socket(0.0, 1_000.0),
            "detail_roughness": _float_socket(0.0, 1.0),
            "phase": _float_socket(-1_000_000.0, 1_000_000.0),
        },
        "outputs": {"factor": "float", "color": "color"},
        "settings": {
            "wave_type": _enum_setting("bands", "rings"),
            "direction": _enum_setting("x", "y", "z"),
            "profile": _enum_setting("sine", "saw", "triangle"),
        },
    },
    "gradient_texture": {
        "inputs": {"vector": _vector_socket(-1_000_000.0, 1_000_000.0)},
        "outputs": {"factor": "float", "color": "color"},
        "settings": {
            "gradient_type": _enum_setting(
                "linear",
                "quadratic",
                "easing",
                "diagonal",
                "radial",
                "quadratic_sphere",
                "spherical",
            )
        },
    },
    "color_ramp": {
        "inputs": {"factor": _float_socket(0.0, 1.0)},
        "outputs": {"color": "color", "alpha": "float"},
        "settings": {
            "interpolation": _enum_setting("constant", "linear", "ease"),
            "position_0": _float_setting(0.0, 1.0),
            "red_0": _float_setting(0.0, 1.0),
            "green_0": _float_setting(0.0, 1.0),
            "blue_0": _float_setting(0.0, 1.0),
            "alpha_0": _float_setting(0.0, 1.0),
            "position_1": _float_setting(0.0, 1.0),
            "red_1": _float_setting(0.0, 1.0),
            "green_1": _float_setting(0.0, 1.0),
            "blue_1": _float_setting(0.0, 1.0),
            "alpha_1": _float_setting(0.0, 1.0),
        },
    },
    "mix_color": {
        "inputs": {
            "factor": _float_socket(0.0, 1.0),
            "color_a": _color_socket(),
            "color_b": _color_socket(),
        },
        "outputs": {"color": "color"},
        "settings": {
            "blend_mode": _enum_setting("mix", "multiply", "add", "screen", "overlay"),
            "clamp_factor": _boolean_setting(),
            "clamp_result": _boolean_setting(),
        },
    },
    "math": {
        "inputs": {
            "value_a": _float_socket(-1_000_000.0, 1_000_000.0),
            "value_b": _float_socket(-1_000_000.0, 1_000_000.0),
        },
        "outputs": {"value": "float"},
        "settings": {
            "operation": _enum_setting(
                "add", "subtract", "multiply", "divide", "minimum", "maximum"
            ),
            "clamp": _boolean_setting(),
        },
    },
    "separate_color": {
        "inputs": {"color": _color_socket()},
        "outputs": {
            "red": "float",
            "green": "float",
            "blue": "float",
        },
        "settings": {"mode": _enum_setting("rgb")},
    },
    "combine_color": {
        "inputs": {
            "red": _float_socket(0.0, 1.0),
            "green": _float_socket(0.0, 1.0),
            "blue": _float_socket(0.0, 1.0),
        },
        "outputs": {"color": "color"},
        "settings": {"mode": _enum_setting("rgb")},
    },
    "normal_map": {
        "inputs": {
            "color": _color_socket(),
            "strength": _float_socket(0.0, 1.0),
        },
        "outputs": {"normal": "vector"},
        "settings": {},
    },
    "bump": {
        "inputs": {
            "height": _float_socket(-1_000_000.0, 1_000_000.0),
            "normal": _vector_socket(-1.0, 1.0),
            "strength": _float_socket(0.0, 1.0),
            "distance": _float_socket(0.0, 1_000.0),
        },
        "outputs": {"normal": "vector"},
        "settings": {},
    },
    "fresnel": {
        "inputs": {
            "ior": _float_socket(1.0, 10.0),
            "normal": _vector_socket(-1.0, 1.0),
        },
        "outputs": {"factor": "float"},
        "settings": {},
    },
    "principled_bsdf": {
        "inputs": {
            "base_color": _color_socket(),
            "roughness": _float_socket(0.0, 1.0),
            "metallic": _float_socket(0.0, 1.0),
            "normal": _vector_socket(-1.0, 1.0),
            "emission_color": _color_socket(),
            "emission_strength": _float_socket(0.0, 1_000.0),
            "alpha": _float_socket(0.0, 1.0),
        },
        "outputs": {"bsdf": "shader"},
        "settings": {},
    },
    "transparent_bsdf": {
        "inputs": {"color": _color_socket()},
        "outputs": {"bsdf": "shader"},
        "settings": {},
    },
    "emission": {
        "inputs": {
            "color": _color_socket(),
            "strength": _float_socket(0.0, 1_000.0),
        },
        "outputs": {"shader": "shader"},
        "settings": {},
    },
    "mix_shader": {
        "inputs": {
            "factor": _float_socket(0.0, 1.0),
            "shader_a": _shader_socket(),
            "shader_b": _shader_socket(),
        },
        "outputs": {"shader": "shader"},
        "settings": {},
    },
    "material_output": {
        "inputs": {"surface": _shader_socket()},
        "outputs": {},
        "settings": {},
    },
}


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize registry data identically in host Python and Blender Python."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _snapshot(version: str, templates: dict[str, dict[str, Any]]) -> dict[str, object]:
    """Build one immutable semantic registry snapshot."""

    return {"registry_version": version, "templates": templates}


LEGACY_REGISTRY_SNAPSHOT = _snapshot(LEGACY_REGISTRY_VERSION, LEGACY_TEMPLATE_REGISTRY)
REGISTRY_SNAPSHOT = _snapshot(REGISTRY_VERSION, PUBLIC_TEMPLATE_REGISTRY)
LEGACY_REGISTRY_SHA256 = hashlib.sha256(_canonical_json_bytes(LEGACY_REGISTRY_SNAPSHOT)).hexdigest()
REGISTRY_SHA256 = hashlib.sha256(_canonical_json_bytes(REGISTRY_SNAPSHOT)).hexdigest()
SUPPORTED_REGISTRIES_BY_SHA256 = {
    LEGACY_REGISTRY_SHA256: LEGACY_TEMPLATE_REGISTRY,
    REGISTRY_SHA256: PUBLIC_TEMPLATE_REGISTRY,
}


def registry_for_sha256(value: str) -> dict[str, dict[str, Any]] | None:
    """Resolve only an exact supported semantic registry digest."""

    return SUPPORTED_REGISTRIES_BY_SHA256.get(value)
