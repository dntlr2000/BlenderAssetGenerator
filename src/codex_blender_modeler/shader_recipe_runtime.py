from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .material_manifest import MaterialManifestError, load_material_manifest

_SURFACE_LIMITS = {
    "metallic": (0.0, 1.0),
    "roughness": (0.0, 1.0),
    "ior": (1.0, 3.0),
    "transmission_weight": (0.0, 1.0),
    "alpha": (0.0, 1.0),
    "emission_strength": (0.0, None),
    "coat_weight": (0.0, 1.0),
    "subsurface_weight": (0.0, 1.0),
    "anisotropic": (0.0, 1.0),
}
_NOISE_PARAMETERS = {
    "seed",
    "scale",
    "detail",
    "roughness",
    "distortion",
    "base_color_ramp",
    "roughness_ramp",
    "bump_strength",
    "bump_distance",
}
_NOISE_CHANNELS = {"base_color", "roughness", "height"}
_SHADER_FAMILIES = {
    "standard_pbr",
    "rock",
    "terrain",
    "water",
    "glass",
    "foliage",
    "lava",
    "cloud",
    "emissive",
}
_TEXTURE_STRATEGIES = {"none", "procedural", "image", "hybrid"}
_MAPPING_MODES = {"uv", "object", "generated", "triplanar"}


class ShaderRecipeRuntimeError(ValueError):
    """Report a Blender-safe material plan or shader recipe validation failure."""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    """Load one JSON object without importing host-only validation dependencies."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ShaderRecipeRuntimeError(f"Invalid {label} JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ShaderRecipeRuntimeError(f"{label} root must be an object: {path}")
    return value


def _resolve_inside(job_root: Path, value: str, label: str) -> Path:
    """Resolve a recipe-owned path while rejecting traversal outside the job."""

    root = job_root.expanduser().resolve()
    resolved = (root / value).expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ShaderRecipeRuntimeError(f"{label} must stay inside job root: {resolved}") from exc
    return resolved


def _number(value: Any, label: str, minimum: float, maximum: float | None) -> float:
    """Validate and normalize one bounded numeric shader parameter."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShaderRecipeRuntimeError(f"{label} must be a number")
    result = float(value)
    if result < minimum or (maximum is not None and result > maximum):
        limit = f"[{minimum}, {maximum}]" if maximum is not None else f">= {minimum}"
        raise ShaderRecipeRuntimeError(f"{label} must be {limit}")
    return result


def _color(value: Any, label: str) -> list[float]:
    """Validate a four-component shader color."""

    if not isinstance(value, list) or len(value) != 4:
        raise ShaderRecipeRuntimeError(f"{label} must contain four numeric components")
    return [_number(component, label, 0.0, None) for component in value]


def _ramp(value: Any, label: str) -> list[list[Any]]:
    """Validate a deterministic position/color ramp used by runtime noise layers."""

    if not isinstance(value, list) or len(value) < 2:
        raise ShaderRecipeRuntimeError(f"{label} requires at least two entries")
    result: list[list[Any]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, list) or len(entry) != 2:
            raise ShaderRecipeRuntimeError(f"{label}[{index}] must be [position, color]")
        position = _number(entry[0], f"{label}[{index}].position", 0.0, 1.0)
        color = _color(entry[1], f"{label}[{index}].color")
        result.append([position, color])
    return result


def _validate_surface(value: Any, material_id: str) -> dict[str, Any]:
    """Validate the portable Principled surface subset consumed inside Blender."""

    if not isinstance(value, dict):
        raise ShaderRecipeRuntimeError(f"Shader recipe {material_id} surface must be an object")
    allowed = set(_SURFACE_LIMITS) | {"base_color", "emission_color"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} has unsupported surface fields: {unknown}"
        )
    result: dict[str, Any] = {}
    for name, raw in value.items():
        if name in {"base_color", "emission_color"}:
            result[name] = _color(raw, f"surface.{name}")
        else:
            minimum, maximum = _SURFACE_LIMITS[name]
            result[name] = _number(raw, f"surface.{name}", minimum, maximum)
    return result


def _validate_noise_layer(layer: Any, material_id: str) -> dict[str, Any]:
    """Validate the single whitelisted procedural Noise layer recipe."""

    if not isinstance(layer, dict) or layer.get("kind") != "noise":
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} supports only procedural noise layers"
        )
    channels = layer.get("channels", [])
    if not isinstance(channels, list) or not channels:
        raise ShaderRecipeRuntimeError(f"Shader recipe {material_id} noise layer needs channels")
    channel_set = set(channels)
    if not channel_set <= _NOISE_CHANNELS:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} noise channels must be {sorted(_NOISE_CHANNELS)}"
        )
    if layer.get("mask", "none") not in {"none", "noise"}:
        raise ShaderRecipeRuntimeError(f"Shader recipe {material_id} noise mask is unsupported")
    if layer.get("blend", "mix") != "replace":
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} runtime noise blend must be replace"
        )
    factor = layer.get("factor", 1.0)
    if _number(factor, "noise.factor", 0.0, 1.0) != 1.0:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} runtime noise factor must be 1.0"
        )
    parameters = layer.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} noise parameters must be an object"
        )
    unknown = sorted(set(parameters) - _NOISE_PARAMETERS)
    if unknown:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} has unsupported noise parameters: {unknown}"
        )
    normalized = dict(layer)
    normalized["channels"] = list(dict.fromkeys(channels))
    normalized["parameters"] = dict(parameters)
    if "base_color" in channel_set:
        normalized["parameters"]["base_color_ramp"] = _ramp(
            parameters.get("base_color_ramp"), "base_color_ramp"
        )
    if "roughness" in channel_set:
        normalized["parameters"]["roughness_ramp"] = _ramp(
            parameters.get("roughness_ramp"), "roughness_ramp"
        )
    if "height" in channel_set:
        strength = _number(parameters.get("bump_strength", 0.15), "bump_strength", 0.0, 1.0)
        distance = _number(parameters.get("bump_distance", 0.05), "bump_distance", 0.0, None)
        normalized["parameters"]["bump_strength"] = strength
        normalized["parameters"]["bump_distance"] = distance
    for name in ("scale", "detail", "roughness", "distortion"):
        if name in parameters:
            normalized["parameters"][name] = _number(
                parameters[name], f"noise.{name}", 0.0, None
            )
    seed = parameters.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ShaderRecipeRuntimeError("noise.seed must be a non-negative integer")
    normalized["parameters"]["seed"] = seed
    return normalized


def _validate_recipe(
    raw: dict[str, Any],
    material_id: str,
    recipe_path: Path,
    texture_strategy: str,
) -> dict[str, Any]:
    """Validate one recipe and attach runtime provenance fields."""

    if raw.get("schema_version") != "0.5.0":
        raise ShaderRecipeRuntimeError(f"Unsupported shader recipe version: {recipe_path}")
    if raw.get("material_id") != material_id:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe material_id must match material plan item {material_id!r}"
        )
    if raw.get("family") not in _SHADER_FAMILIES:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} uses an unsupported shader family"
        )
    surface = _validate_surface(raw.get("surface", {}), material_id)
    mapping = raw.get("mapping", {})
    if not isinstance(mapping, dict):
        raise ShaderRecipeRuntimeError(f"Shader recipe {material_id} mapping must be an object")
    mode = mapping.get("mode", "object")
    if mode not in {"uv", "object", "generated", "triplanar"}:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} runtime mapping is unsupported: {mode!r}"
        )
    runtime_mode = mode
    if mode == "triplanar":
        if texture_strategy != "procedural":
            raise ShaderRecipeRuntimeError(
                f"Shader recipe {material_id} triplanar mapping is currently supported only "
                "for procedural materials"
            )
        runtime_mode = "object"
    scale = _number(mapping.get("real_world_scale_m", 1.0), "real_world_scale_m", 0.000001, None)
    layers = raw.get("layers", [])
    if not isinstance(layers, list) or len(layers) > 1:
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} supports at most one runtime procedural layer"
        )
    if layers and texture_strategy != "procedural":
        raise ShaderRecipeRuntimeError(
            f"Shader recipe {material_id} layers require texture_strategy='procedural'"
        )
    result = dict(raw)
    result["surface"] = surface
    result["mapping"] = {
        "mode": runtime_mode,
        "uv_set": str(mapping.get("uv_set", "UVMap")),
        "real_world_scale_m": scale,
    }
    if runtime_mode != mode:
        result["cbm_mapping_fallback"] = f"{mode}->{runtime_mode}"
    result["layers"] = [_validate_noise_layer(layers[0], material_id)] if layers else []
    result["cbm_recipe_path"] = str(recipe_path)
    result["cbm_texture_strategy"] = texture_strategy
    return result


def validate_runtime_shader_recipe(
    raw: dict[str, Any],
    material_id: str,
    recipe_path: Path,
    texture_strategy: str,
    *,
    plan_family: str,
    plan_mapping: dict[str, Any],
) -> dict[str, Any]:
    """Preflight a host-authored recipe against Blender's current execution subset."""

    if raw.get("family") != plan_family:
        raise ShaderRecipeRuntimeError(
            f"Material plan family {plan_family!r} does not match recipe family "
            f"{raw.get('family')!r} for {material_id}"
        )
    recipe_mapping = raw.get("mapping", {})
    if not isinstance(recipe_mapping, dict):
        raise ShaderRecipeRuntimeError(f"Shader recipe {material_id} mapping must be an object")
    for field, default in (
        ("mode", "object"),
        ("uv_set", "UVMap"),
        ("real_world_scale_m", 1.0),
    ):
        if recipe_mapping.get(field, default) != plan_mapping.get(field, default):
            raise ShaderRecipeRuntimeError(
                f"Material plan and shader recipe mapping.{field} disagree for {material_id}"
            )
    return _validate_recipe(raw, material_id, recipe_path, texture_strategy)


def _effective_manifest(
    root: Path,
    material_id: str,
    texture_strategy: str,
    item_value: Any,
    recipe_value: Any,
) -> tuple[str | None, str | None]:
    """Resolve and validate the plan/recipe manifest without relying on SceneSpec."""

    for label, value in (("material plan", item_value), ("shader recipe", recipe_value)):
        if value is not None and not isinstance(value, str):
            raise ShaderRecipeRuntimeError(
                f"{label} texture_manifest for {material_id} must be a string or null"
            )
    if item_value and recipe_value and item_value != recipe_value:
        raise ShaderRecipeRuntimeError(
            f"Material plan and shader recipe texture_manifest disagree for {material_id}"
        )
    manifest_value = item_value or recipe_value
    if texture_strategy in {"image", "hybrid"} and not manifest_value:
        raise ShaderRecipeRuntimeError(
            f"Material plan {material_id} texture_strategy={texture_strategy!r} requires a manifest"
        )
    if not manifest_value:
        return None, None
    try:
        manifest, manifest_path = load_material_manifest(
            {"id": material_id, "texture_manifest": manifest_value}, root
        )
    except MaterialManifestError as exc:
        raise ShaderRecipeRuntimeError(
            f"Material plan manifest validation failed for {material_id}: {exc}"
        ) from exc
    if manifest is None or manifest_path is None:
        raise ShaderRecipeRuntimeError(f"Material plan manifest did not load for {material_id}")
    source_type = str(manifest["source_type"])
    if texture_strategy != source_type:
        raise ShaderRecipeRuntimeError(
            f"Material plan {material_id} strategy {texture_strategy!r} does not match "
            f"manifest source_type {source_type!r}"
        )
    return str(manifest_value), str(manifest_path)


def _validate_scene_material_coverage(root: Path, items: list[Any]) -> None:
    """Require a present MaterialPlan to cover the full SceneSpec material ID set."""

    scene_spec_path = root / "analysis" / "scene_spec.json"
    if not scene_spec_path.is_file():
        return
    scene_spec = _load_object(scene_spec_path, "SceneSpec")
    scene_materials = scene_spec.get("materials", [])
    if not isinstance(scene_materials, list):
        raise ShaderRecipeRuntimeError("SceneSpec materials must be an array")
    scene_ids = {
        str(material["id"])
        for material in scene_materials
        if isinstance(material, dict) and isinstance(material.get("id"), str)
    }
    plan_ids = {
        str(item["material_id"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("material_id"), str)
    }
    missing = sorted(scene_ids - plan_ids)
    extra = sorted(plan_ids - scene_ids)
    if missing or extra:
        raise ShaderRecipeRuntimeError(
            f"Material plan must cover SceneSpec material IDs exactly; missing={missing}, "
            f"extra={extra}"
        )


def load_runtime_shader_recipes(job_root: Path, job_id: str) -> dict[str, dict[str, Any]]:
    """Load an optional material plan and its recipes using Blender-safe stdlib code."""

    root = job_root.expanduser().resolve()
    plan_path = root / "analysis" / "material_plan.json"
    if not plan_path.is_file():
        return {}
    plan = _load_object(plan_path, "material plan")
    if plan.get("schema_version") != "0.5.0":
        raise ShaderRecipeRuntimeError(f"Unsupported material plan version: {plan_path}")
    if plan.get("job_id") != job_id:
        raise ShaderRecipeRuntimeError(
            f"Material plan job_id {plan.get('job_id')!r} does not match {job_id!r}"
        )
    items = plan.get("materials", [])
    if not isinstance(items, list):
        raise ShaderRecipeRuntimeError("Material plan materials must be an array")
    _validate_scene_material_coverage(root, items)
    recipes: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("material_id"), str):
            raise ShaderRecipeRuntimeError("Each material plan item requires a material_id")
        material_id = item["material_id"]
        if material_id in seen_ids:
            raise ShaderRecipeRuntimeError(f"Duplicate material plan ID: {material_id}")
        seen_ids.add(material_id)
        texture_strategy = item.get("texture_strategy", "none")
        if texture_strategy not in _TEXTURE_STRATEGIES:
            raise ShaderRecipeRuntimeError(
                f"Material plan {material_id} has unsupported texture_strategy"
            )
        recipe_value = item.get("shader_recipe")
        if recipe_value:
            if not isinstance(recipe_value, str):
                raise ShaderRecipeRuntimeError(f"shader_recipe for {material_id} must be a string")
            recipe_path = _resolve_inside(root, recipe_value, "shader_recipe")
            if not recipe_path.is_file():
                raise ShaderRecipeRuntimeError(f"Shader recipe does not exist: {recipe_path}")
            recipe_raw = _load_object(recipe_path, "shader recipe")
            plan_mapping = item.get("mapping", {})
            if not isinstance(plan_mapping, dict):
                raise ShaderRecipeRuntimeError(
                    f"Material plan {material_id} mapping must be an object"
                )
            override = validate_runtime_shader_recipe(
                recipe_raw,
                material_id,
                recipe_path,
                str(texture_strategy),
                plan_family=str(item.get("shader_family", "standard_pbr")),
                plan_mapping=plan_mapping,
            )
            recipe_manifest = recipe_raw.get("texture_manifest")
        else:
            override = {}
            recipe_manifest = None
        manifest_value, manifest_path = _effective_manifest(
            root,
            material_id,
            str(texture_strategy),
            item.get("texture_manifest"),
            recipe_manifest,
        )
        override["cbm_plan_path"] = str(plan_path)
        override["cbm_texture_strategy"] = str(texture_strategy)
        override["cbm_texture_manifest"] = manifest_value
        override["cbm_texture_manifest_path"] = manifest_path
        recipes[material_id] = override
    return recipes


def load_runtime_material_mappings(job_root: Path, job_id: str) -> dict[str, dict[str, Any]]:
    """Load material mapping policies without requiring an authored shader recipe."""

    root = job_root.expanduser().resolve()
    plan_path = root / "analysis" / "material_plan.json"
    if not plan_path.is_file():
        return {}
    plan = _load_object(plan_path, "material plan")
    if plan.get("schema_version") != "0.5.0":
        raise ShaderRecipeRuntimeError(f"Unsupported material plan version: {plan_path}")
    if plan.get("job_id") != job_id:
        raise ShaderRecipeRuntimeError(
            f"Material plan job_id {plan.get('job_id')!r} does not match {job_id!r}"
        )
    items = plan.get("materials", [])
    if not isinstance(items, list):
        raise ShaderRecipeRuntimeError("Material plan materials must be an array")

    mappings: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("material_id"), str):
            raise ShaderRecipeRuntimeError("Each material plan item requires a material_id")
        material_id = item["material_id"]
        if material_id in mappings:
            raise ShaderRecipeRuntimeError(f"Duplicate material plan ID: {material_id}")
        raw_mapping = item.get("mapping", {})
        if not isinstance(raw_mapping, dict):
            raise ShaderRecipeRuntimeError(f"Material plan {material_id} mapping must be an object")
        mode = raw_mapping.get("mode", "object")
        if mode not in _MAPPING_MODES:
            raise ShaderRecipeRuntimeError(
                f"Material plan {material_id} mapping mode must be one of {sorted(_MAPPING_MODES)}"
            )
        uv_set = raw_mapping.get("uv_set", "UVMap")
        if not isinstance(uv_set, str) or not uv_set.strip():
            raise ShaderRecipeRuntimeError(f"Material plan {material_id} uv_set must be non-empty")
        mappings[material_id] = {
            "mode": str(mode),
            "uv_set": uv_set,
            "real_world_scale_m": _number(
                raw_mapping.get("real_world_scale_m", 1.0),
                f"material_plan.{material_id}.real_world_scale_m",
                0.000001,
                None,
            ),
        }
    return mappings
