"""Compile fixed MaterialAuthoring fixtures into isolated Blender 5 evidence.

This script is intentionally not a public material compiler.  It accepts one exact
run-owned MaterialAuthoring manifest, recognizes five fixed material families, and
publishes only a disposable compile/reopen/render receipt under an isolated smoke
root.  No node type, socket name, expression, callback, driver, or Python payload is
accepted from JSON input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

import bpy
from mathutils import Vector

FIXTURE_VERSION = "0.1.0"
OUTPUT_PREFIX = "material_authoring/blender_smoke/runs/"
MANIFEST_PREFIX = "material_authoring/runs/"
FAMILY_STRATEGIES = {
    "wood": "procedural_wood_v1",
    "metal": "procedural_metal_v1",
    "signage_decal": "localized_decal_v1",
    "emissive": "emissive_pattern_v1",
    "crystal": "crystal_portable_approximation_v1",
}
FAMILY_CHANNELS = {
    "wood": {"base_color", "height", "normal", "occlusion", "roughness"},
    "metal": {"base_color", "metallic", "normal", "roughness"},
    "signage_decal": {"base_color", "emission", "normal", "opacity", "roughness"},
    "emissive": {"base_color", "emission", "opacity"},
    "crystal": {"base_color", "emission", "normal", "opacity", "roughness"},
}
CHANNEL_COLOR_SPACE = {
    "base_color": "srgb",
    "emission": "srgb",
    "height": "non_color",
    "metallic": "non_color",
    "normal": "non_color",
    "occlusion": "non_color",
    "opacity": "non_color",
    "roughness": "non_color",
}
PRINCIPLED_INPUT_ALIASES = {
    "alpha": ("Alpha",),
    "base_color": ("Base Color",),
    "coat_weight": ("Coat Weight", "Coat"),
    "emission_color": ("Emission Color", "Emission"),
    "emission_strength": ("Emission Strength",),
    "ior": ("IOR",),
    "metallic": ("Metallic",),
    "normal": ("Normal",),
    "roughness": ("Roughness",),
    "transmission_weight": ("Transmission Weight", "Transmission"),
}
TOP_LEVEL_FIELDS = {
    "canonical_v05_unchanged",
    "channels",
    "created_at",
    "destination_write_performed",
    "job_id",
    "limitations",
    "manifest_id",
    "master_intent",
    "material_family",
    "material_id",
    "preview_evidence",
    "request",
    "resolution",
    "run_id",
    "runtime_parity_verified",
    "scale_context",
    "schema_version",
    "source_to_output_provenance_sha256",
    "source_v05_contracts",
    "status",
    "strategy",
    "workflow_id",
}
CHANNEL_FIELDS = {
    "artifact",
    "channel",
    "color_space",
    "height",
    "normal_convention",
    "source_artifact_sha256",
    "uv_identity",
    "width",
}
ARTIFACT_FIELDS = {
    "artifact_id",
    "byte_size",
    "kind",
    "media_type",
    "path",
    "sha256",
}
REQUEST_FIELDS = {
    "canonical_write_authority",
    "created_at",
    "crystal",
    "destination_write_authority",
    "emissive_pattern",
    "high_resolution_authorization",
    "job_id",
    "localized_decal",
    "material_id",
    "output_root",
    "planar_reference_patch",
    "preview_policy",
    "procedural_metal",
    "procedural_wood",
    "request_id",
    "resolution",
    "run_id",
    "scale_context",
    "schema_version",
    "source_v05_contracts",
    "strategy",
    "uniform_fallback",
    "user_image_pbr",
    "workflow_id",
}
METAL_FIELDS = {
    "base_color",
    "base_metal",
    "brush_scale_m",
    "brushed_direction",
    "deterministic_seed",
    "edge_wear_mask",
    "intended_real_world_scale_m",
    "roughness_base",
    "roughness_variation",
    "subtle_normal_strength",
    "unsupported_scratches",
    "uv_identity",
}
UV_IDENTITY_FIELDS = {
    "evidence",
    "ordered_polygon_corner_count",
    "schema_version",
    "semantic_id",
    "texel_density_px_m",
    "uv_fingerprint",
    "uv_set",
}
UV_SNAPSHOT_FIELDS = UV_IDENTITY_FIELDS - {"evidence"}
SCALE_BINDING_FIELDS = {
    "artifact",
    "asset_id",
    "longest_dimension_m",
    "shortest_dimension_m",
    "source_fingerprint",
    "target_texel_density_px_m",
}
SCALE_CONTEXT_FIELDS = {
    "absolute_overrides_m",
    "assembly_bbox",
    "asset_id",
    "created_at",
    "dispatch_id",
    "input_sha256",
    "job_id",
    "local_bbox",
    "producer",
    "producer_version",
    "projected_pixel_size",
    "provenance",
    "ratio_overrides",
    "schema_version",
    "shortest_dimension_m",
    "source_fingerprint",
    "target_texel_density_px_m",
    "workflow_id",
}
BOUNDS_FIELDS = {"maximum", "minimum"}
STRUCTURAL_EVIDENCE_FIELDS = {"path", "role", "sha256"}
RESOLUTION_SELECTOR_FIELDS = {
    "longest_object_dimension_m",
    "mapping_kind",
    "material_family",
    "package_budget_bytes",
    "projected_pixel_footprint",
    "requested_pixels",
    "selector_id",
    "target_texel_density_px_m",
}
RESOLUTION_SELECTION_FIELDS = {
    "budget_limited",
    "high_resolution_authorized",
    "reasons",
    "scale_context_recommendation",
    "selected_pixels",
    "selector_input_sha256",
    "unclamped_target_pixels",
}


class FixtureContractError(RuntimeError):
    """Signal a fail-closed fixed-fixture contract or Blender feature error."""


def _argv_after_separator() -> list[str]:
    """Return only arguments explicitly supplied to this fixed Blender script."""

    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _parse_args() -> argparse.Namespace:
    """Parse one exact source manifest and one isolated run-owned output root."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--job-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    return parser.parse_args(_argv_after_separator())


def _canonical_json_bytes(value: object) -> bytes:
    """Serialize normalized inventory evidence with stable JSON rules."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    """Hash one normalized JSON value without relying on Blender file bytes."""

    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    """Hash exact source or derived bytes in bounded chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_keys(value: object, expected: set[str], label: str) -> dict:
    """Require an exact object field set so undeclared controls fail closed."""

    if not isinstance(value, dict) or set(value) != expected:
        raise FixtureContractError(f"{label} does not have the exact contract fields")
    return value


def _sha256(value: object, label: str) -> str:
    """Validate one lowercase exact SHA-256 binding."""

    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise FixtureContractError(f"{label} is not a lowercase SHA-256")
    return value


def _portable_id(value: object, label: str) -> str:
    """Validate a bounded identifier used only for evidence and Blender names."""

    if not isinstance(value, str) or re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,127}", value
    ) is None:
        raise FixtureContractError(f"{label} is not a portable identifier")
    return value


def _relative_path(value: object, label: str) -> str:
    """Reject absolute, escaping, Windows, empty, and non-normalized paths."""

    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise FixtureContractError(f"{label} must be a normalized relative path")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")):
        raise FixtureContractError(f"{label} contains an unsafe path segment")
    return value


def _resolve_contained(root: Path, relative_path: object, *, must_exist: bool) -> Path:
    """Resolve a job-relative path while rejecting symlink and containment escape."""

    normalized = _relative_path(relative_path, "fixture path")
    current = root
    for part in normalized.split("/"):
        current = current / part
        if current.is_symlink():
            raise FixtureContractError(f"fixture path traverses a symlink: {normalized}")
    candidate = root.joinpath(*normalized.split("/"))
    try:
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise FixtureContractError(f"fixture path escapes or is missing: {normalized}") from exc
    if must_exist and not resolved.is_file():
        raise FixtureContractError(f"fixture input is not a file: {normalized}")
    return resolved


def _load_json(path: Path, label: str) -> dict:
    """Load one UTF-8 JSON object strictly as inert data."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixtureContractError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise FixtureContractError(f"{label} must be a JSON object")
    return value


def _validate_artifact(root: Path, value: object, label: str) -> tuple[dict, Path]:
    """Validate exact artifact metadata, containment, byte size, and digest."""

    artifact = _strict_keys(value, ARTIFACT_FIELDS, label)
    _portable_id(artifact["artifact_id"], f"{label} artifact_id")
    path = _resolve_contained(root, artifact["path"], must_exist=True)
    if not isinstance(artifact["byte_size"], int) or artifact["byte_size"] <= 0:
        raise FixtureContractError(f"{label} byte_size is invalid")
    if path.stat().st_size != artifact["byte_size"]:
        raise FixtureContractError(f"{label} byte size changed")
    expected_hash = _sha256(artifact["sha256"], f"{label} sha256")
    if _sha256_file(path) != expected_hash:
        raise FixtureContractError(f"{label} SHA-256 changed")
    return artifact, path


def _validate_manifest(root: Path, path: Path, expected_hash: str) -> tuple[dict, dict, dict]:
    """Validate an unmodified host-authored manifest and every exact channel input."""

    if _sha256_file(path) != _sha256(expected_hash, "manifest SHA-256"):
        raise FixtureContractError("material authoring manifest SHA-256 mismatch")
    manifest = _strict_keys(_load_json(path, "material manifest"), TOP_LEVEL_FIELDS, "manifest")
    family = manifest.get("material_family")
    if family not in FAMILY_STRATEGIES:
        raise FixtureContractError("material family is outside the fixed fixture registry")
    if manifest.get("schema_version") != FIXTURE_VERSION:
        raise FixtureContractError("unsupported material authoring manifest version")
    if manifest.get("strategy") != FAMILY_STRATEGIES[family]:
        raise FixtureContractError("material family and authoring strategy disagree")
    if manifest.get("status") != "unverified":
        raise FixtureContractError("fixture accepts only an unverified run-owned candidate")
    if manifest.get("canonical_v05_unchanged") is not True:
        raise FixtureContractError("canonical V0.5 immutability is not declared")
    if manifest.get("destination_write_performed") is not False:
        raise FixtureContractError("destination writes are forbidden in a Blender fixture")
    if manifest.get("runtime_parity_verified") is not False:
        raise FixtureContractError("runtime parity cannot pre-exist this fixture")
    master = _strict_keys(
        manifest.get("master_intent"),
        {
            "blender_compilation_status",
            "blender_fixture",
            "features",
            "known_losses",
            "portable_approximation",
            "shader_family",
        },
        "master intent",
    )
    if (
        master.get("shader_family") != family
        or master.get("blender_compilation_status") != "not_run"
        or master.get("blender_fixture") is not None
    ):
        raise FixtureContractError("fixture must not rewrite or reuse claimed Blender evidence")
    preview = _strict_keys(
        manifest.get("preview_evidence"),
        {
            "neutral_studio_artifact",
            "neutral_studio_required_for_quality",
            "neutral_studio_status",
            "reference_matched_artifact",
            "reference_matched_never_sufficient_alone",
            "reference_matched_status",
        },
        "preview evidence",
    )
    if preview.get("neutral_studio_status") != "not_run" or (
        preview.get("neutral_studio_artifact") is not None
    ):
        raise FixtureContractError("fixture requires an unrendered neutral preview state")
    request_artifact, request_path = _validate_artifact(root, manifest["request"], "request")
    if request_artifact.get("kind") != "material-authoring-request":
        raise FixtureContractError("manifest request has the wrong artifact role")
    request = _strict_keys(
        _load_json(request_path, "material authoring request"),
        REQUEST_FIELDS,
        "material authoring request",
    )
    if request.get("schema_version") != FIXTURE_VERSION:
        raise FixtureContractError("unsupported material authoring request version")
    if request.get("strategy") != manifest["strategy"]:
        raise FixtureContractError("request and manifest strategy disagree")
    if request.get("canonical_write_authority") is not False or (
        request.get("destination_write_authority") is not False
    ):
        raise FixtureContractError("fixture request carries forbidden write authority")
    channels = manifest.get("channels")
    if not isinstance(channels, list):
        raise FixtureContractError("manifest channels must be a list")
    channel_map: dict[str, dict] = {}
    for index, raw_channel in enumerate(channels):
        channel = _strict_keys(raw_channel, CHANNEL_FIELDS, f"channel {index}")
        channel_id = channel.get("channel")
        if channel_id not in CHANNEL_COLOR_SPACE or channel_id in channel_map:
            raise FixtureContractError("channel identifier is unknown or duplicated")
        if channel.get("color_space") != CHANNEL_COLOR_SPACE[channel_id]:
            raise FixtureContractError(f"{channel_id} color-space declaration is invalid")
        if channel_id == "normal" and channel.get("normal_convention") != "opengl_y_plus":
            raise FixtureContractError("normal fixture requires OpenGL +Y convention")
        if channel_id != "normal" and channel.get("normal_convention") is not None:
            raise FixtureContractError("non-normal channel declares a normal convention")
        if not isinstance(channel.get("width"), int) or not 1 <= channel["width"] <= 8192:
            raise FixtureContractError("channel width is outside the fixture cap")
        if not isinstance(channel.get("height"), int) or not 1 <= channel["height"] <= 8192:
            raise FixtureContractError("channel height is outside the fixture cap")
        artifact, channel_path = _validate_artifact(root, channel["artifact"], channel_id)
        if artifact.get("media_type") != "image/png":
            raise FixtureContractError("fixed fixture accepts only host-authored PNG channels")
        channel_map[channel_id] = {**channel, "resolved_path": channel_path}
    if set(channel_map) != FAMILY_CHANNELS[family]:
        raise FixtureContractError("material family channel set is not exact")
    manifest["_fixture_validated_family_contract"] = (
        _validate_metal_contract(root, manifest, request, channel_map)
        if family == "metal"
        else {"strategy": manifest["strategy"]}
    )
    return manifest, request, channel_map


def _bounded_number(value: object, label: str, minimum: float, maximum: float) -> float:
    """Validate one finite family parameter before applying a fixed socket default."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FixtureContractError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise FixtureContractError(f"{label} is outside the fixture range")
    return result


def _bounded_vec3(value: object, label: str) -> tuple[float, float, float]:
    """Validate one finite normalized RGB or metric vector without coercing strings."""

    if not isinstance(value, list) or len(value) != 3:
        raise FixtureContractError(f"{label} must contain exactly three numbers")
    return tuple(
        _bounded_number(component, f"{label}[{index}]", -1.0e12, 1.0e12)
        for index, component in enumerate(value)
    )


def _same_number(actual: object, expected: object, label: str) -> float:
    """Require two finite cached contract numbers to match at host precision."""

    actual_value = _bounded_number(actual, f"{label} actual", -1.0e12, 1.0e12)
    expected_value = _bounded_number(expected, f"{label} expected", -1.0e12, 1.0e12)
    if not math.isclose(actual_value, expected_value, rel_tol=0.0, abs_tol=1.0e-9):
        raise FixtureContractError(f"{label} binding is stale")
    return actual_value


def _validate_bounds(value: object, label: str) -> tuple[float, float, float]:
    """Validate strict metric bounds and return their positive dimensions."""

    bounds = _strict_keys(value, BOUNDS_FIELDS, label)
    minimum = _bounded_vec3(bounds["minimum"], f"{label} minimum")
    maximum = _bounded_vec3(bounds["maximum"], f"{label} maximum")
    dimensions = tuple(high - low for low, high in zip(minimum, maximum, strict=True))
    if any(dimension <= 0.0 for dimension in dimensions):
        raise FixtureContractError(f"{label} dimensions must be positive")
    return dimensions


def _validate_scale_context_binding(root: Path, request: dict) -> tuple[str, float, float]:
    """Rehash and compare the exact scale artifact, binding, selector, and provenance."""

    binding = _strict_keys(request.get("scale_context"), SCALE_BINDING_FIELDS, "scale binding")
    artifact, scale_path = _validate_artifact(root, binding["artifact"], "scale context")
    if artifact.get("kind") != "asset-scale-context" or artifact.get(
        "media_type"
    ) != "application/json":
        raise FixtureContractError("scale context artifact has the wrong role")
    scale = _strict_keys(
        _load_json(scale_path, "asset scale context"),
        SCALE_CONTEXT_FIELDS,
        "asset scale context",
    )
    if scale.get("schema_version") != FIXTURE_VERSION:
        raise FixtureContractError("unsupported asset scale context version")
    if scale.get("asset_id") != binding.get("asset_id") or scale.get(
        "source_fingerprint"
    ) != binding.get("source_fingerprint"):
        raise FixtureContractError("scale context identity or source fingerprint changed")
    _sha256(scale.get("source_fingerprint"), "scale source fingerprint")
    provenance = scale.get("provenance")
    if not isinstance(provenance, list) or not provenance:
        raise FixtureContractError("scale context provenance is missing")
    seen_paths: set[str] = set()
    for index, raw_item in enumerate(provenance):
        item = _strict_keys(
            raw_item,
            STRUCTURAL_EVIDENCE_FIELDS,
            f"scale provenance {index}",
        )
        relative = _relative_path(item.get("path"), f"scale provenance {index} path")
        if relative in seen_paths:
            raise FixtureContractError("scale context provenance paths are duplicated")
        seen_paths.add(relative)
        source = _resolve_contained(root, relative, must_exist=True)
        if _sha256_file(source) != _sha256(
            item.get("sha256"), f"scale provenance {index} sha256"
        ):
            raise FixtureContractError("scale context provenance changed")
    if _canonical_sha256(provenance) != _sha256(
        scale.get("input_sha256"), "scale context input SHA-256"
    ):
        raise FixtureContractError("scale context input digest contradicts provenance")
    local_dimensions = _validate_bounds(scale.get("local_bbox"), "local scale bounds")
    assembly_dimensions = _validate_bounds(
        scale.get("assembly_bbox"), "assembly scale bounds"
    )
    shortest = _same_number(
        min(local_dimensions), scale.get("shortest_dimension_m"), "scale shortest dimension"
    )
    _same_number(shortest, binding.get("shortest_dimension_m"), "bound shortest dimension")
    longest = max(assembly_dimensions)
    _same_number(longest, binding.get("longest_dimension_m"), "bound longest dimension")
    density = _same_number(
        scale.get("target_texel_density_px_m"),
        binding.get("target_texel_density_px_m"),
        "bound texel density",
    )
    selector = _strict_keys(
        request.get("resolution"), RESOLUTION_SELECTOR_FIELDS, "resolution selector"
    )
    if selector.get("material_family") != "metal" or selector.get(
        "mapping_kind"
    ) != "tileable":
        raise FixtureContractError("metal fixture requires a tileable metal selector")
    _same_number(
        selector.get("longest_object_dimension_m"),
        longest,
        "selector longest dimension",
    )
    _same_number(
        selector.get("target_texel_density_px_m"),
        density,
        "selector texel density",
    )
    return artifact["sha256"], longest, density


def _validate_uv_identity(root: Path, value: object, density: float) -> tuple[dict, str]:
    """Rehash one UV snapshot and compare every identity field to its exact evidence."""

    identity = _strict_keys(value, UV_IDENTITY_FIELDS, "metal UV identity")
    if identity.get("schema_version") != FIXTURE_VERSION:
        raise FixtureContractError("unsupported metal UV identity version")
    if not isinstance(identity.get("semantic_id"), str) or not identity["semantic_id"]:
        raise FixtureContractError("metal UV semantic identity is missing")
    if not isinstance(identity.get("uv_set"), str) or not identity["uv_set"]:
        raise FixtureContractError("metal UV set is missing")
    _sha256(identity.get("uv_fingerprint"), "metal UV fingerprint")
    if (
        not isinstance(identity.get("ordered_polygon_corner_count"), int)
        or isinstance(identity.get("ordered_polygon_corner_count"), bool)
        or identity["ordered_polygon_corner_count"] < 3
    ):
        raise FixtureContractError("metal UV corner count is invalid")
    _same_number(identity.get("texel_density_px_m"), density, "metal UV texel density")
    artifact, snapshot_path = _validate_artifact(root, identity["evidence"], "metal UV evidence")
    if artifact.get("kind") != "uv-identity-snapshot" or artifact.get(
        "media_type"
    ) != "application/json":
        raise FixtureContractError("metal UV evidence has the wrong role")
    snapshot = _strict_keys(
        _load_json(snapshot_path, "metal UV snapshot"),
        UV_SNAPSHOT_FIELDS,
        "metal UV snapshot",
    )
    expected = {key: identity[key] for key in UV_SNAPSHOT_FIELDS}
    if snapshot != expected:
        raise FixtureContractError("metal UV evidence is stale or contradictory")
    return identity, artifact["sha256"]


def _validate_metal_contract(
    root: Path,
    manifest: dict,
    request: dict,
    channel_map: dict[str, dict],
) -> dict[str, object]:
    """Validate exact metal scale, UV, channels, semantics, and no-scratch policy."""

    for field in ("job_id", "workflow_id", "run_id", "material_id", "strategy"):
        if request.get(field) != manifest.get(field):
            raise FixtureContractError(f"metal request and manifest disagree on {field}")
    if request.get("schema_version") != FIXTURE_VERSION:
        raise FixtureContractError("unsupported metal request version")
    if request.get("canonical_write_authority") is not False or request.get(
        "destination_write_authority"
    ) is not False:
        raise FixtureContractError("metal request carries forbidden write authority")
    if request.get("high_resolution_authorization") is not None:
        raise FixtureContractError("fixed metal fixture does not accept high-resolution authority")
    inactive_payloads = (
        "uniform_fallback",
        "user_image_pbr",
        "localized_decal",
        "planar_reference_patch",
        "procedural_wood",
        "emissive_pattern",
        "crystal",
    )
    if any(request.get(name) is not None for name in inactive_payloads):
        raise FixtureContractError("metal request contains another strategy payload")
    source_contracts = request.get("source_v05_contracts")
    if (
        not isinstance(source_contracts, list)
        or not source_contracts
        or source_contracts != manifest.get("source_v05_contracts")
    ):
        raise FixtureContractError("metal V0.5 source contracts are missing or changed")
    source_kinds: set[str] = set()
    for index, source_contract in enumerate(source_contracts):
        artifact, _path = _validate_artifact(
            root, source_contract, f"metal V0.5 source {index}"
        )
        source_kinds.add(str(artifact.get("kind")))
    if "v05-material-plan" not in source_kinds:
        raise FixtureContractError("metal fixture requires an exact V0.5 MaterialPlan")
    if manifest.get("scale_context") != request.get("scale_context"):
        raise FixtureContractError("metal request and manifest scale bindings differ")
    scale_sha256, longest_dimension, texel_density = _validate_scale_context_binding(
        root, request
    )
    metal = _strict_keys(request.get("procedural_metal"), METAL_FIELDS, "procedural metal")
    if metal.get("base_metal") not in {
        "aluminum",
        "steel",
        "iron",
        "copper",
        "brass",
        "custom",
    }:
        raise FixtureContractError("metal base identity is outside the fixed contract")
    base_color = _bounded_vec3(metal.get("base_color"), "metal base color")
    if any(component < 0.0 or component > 1.0 for component in base_color):
        raise FixtureContractError("metal base color is outside normalized RGB")
    roughness_base = _bounded_number(
        metal.get("roughness_base"), "metal roughness base", 0.0, 1.0
    )
    roughness_variation = _bounded_number(
        metal.get("roughness_variation"), "metal roughness variation", 0.0, 0.35
    )
    subtle_normal_strength = _bounded_number(
        metal.get("subtle_normal_strength"), "metal subtle normal", 0.0, 0.35
    )
    _bounded_number(metal.get("brush_scale_m"), "metal brush scale", 1.0e-12, 1.0e12)
    _same_number(
        metal.get("intended_real_world_scale_m"),
        longest_dimension,
        "metal intended scale",
    )
    if metal.get("brushed_direction") not in {"x", "y", "radial", "none"}:
        raise FixtureContractError("metal brushed direction is invalid")
    if (
        not isinstance(metal.get("deterministic_seed"), int)
        or isinstance(metal.get("deterministic_seed"), bool)
        or not 0 <= metal["deterministic_seed"] <= 2**31 - 1
    ):
        raise FixtureContractError("metal deterministic seed is invalid")
    if metal.get("edge_wear_mask") is not None:
        raise FixtureContractError("fixed metal fixture does not synthesize edge wear")
    if metal.get("unsupported_scratches") is not False:
        raise FixtureContractError("unsupported scratches are forbidden")
    uv_identity, uv_sha256 = _validate_uv_identity(
        root, metal.get("uv_identity"), texel_density
    )
    selection = _strict_keys(
        manifest.get("resolution"),
        RESOLUTION_SELECTION_FIELDS,
        "metal resolution selection",
    )
    if selection.get("selector_input_sha256") != _canonical_sha256(request["resolution"]):
        raise FixtureContractError("metal resolution selection is bound to another selector")
    selected_pixels = selection.get("selected_pixels")
    if (
        not isinstance(selected_pixels, int)
        or isinstance(selected_pixels, bool)
        or selected_pixels not in {256, 512, 1024, 2048, 4096}
        or selection.get("high_resolution_authorized") is not False
    ):
        raise FixtureContractError("fixed metal fixture resolution is not a normal tier")
    expected_source_hashes = [scale_sha256, uv_sha256]
    for channel_id, channel in channel_map.items():
        if channel.get("uv_identity") != uv_identity:
            raise FixtureContractError(f"metal {channel_id} UV binding changed")
        if channel.get("source_artifact_sha256") != expected_source_hashes:
            raise FixtureContractError(f"metal {channel_id} provenance hashes changed")
        if (channel.get("width"), channel.get("height")) != (
            selected_pixels,
            selected_pixels,
        ):
            raise FixtureContractError(f"metal {channel_id} resolution changed")
    expected_provenance = {
        "strategy": request["strategy"],
        "source_v05_contracts": [item["sha256"] for item in source_contracts],
        "scale_context": scale_sha256,
        "channels": manifest["channels"],
    }
    if manifest.get("source_to_output_provenance_sha256") != _canonical_sha256(
        expected_provenance
    ):
        raise FixtureContractError("metal source-to-output provenance digest changed")
    features = manifest.get("master_intent", {}).get("features")
    if features != ["metallic workflow", "bounded brushed roughness", "subtle normal"]:
        raise FixtureContractError("metal master intent contains an unsupported feature")
    return {
        "brushed_direction": metal["brushed_direction"],
        "metallic_channel_bound": True,
        "roughness_base": roughness_base,
        "roughness_channel_bound": True,
        "roughness_variation": roughness_variation,
        "scale_context_sha256": scale_sha256,
        "strategy": request["strategy"],
        "subtle_normal_channel_bound": True,
        "subtle_normal_strength": subtle_normal_strength,
        "unsupported_scratches": False,
        "uv_identity_sha256": uv_sha256,
    }


def _family_parameters(request: dict, family: str) -> dict[str, float]:
    """Extract only bounded semantic constants from the fixed strategy companion."""

    if family == "wood":
        payload = request.get("procedural_wood")
        if not isinstance(payload, dict):
            raise FixtureContractError("wood request payload is missing")
        return {
            "coat_weight": _bounded_number(
                payload.get("finish_coating_amount"), "wood coat", 0.0, 1.0
            )
        }
    if family == "metal":
        if not isinstance(request.get("procedural_metal"), dict):
            raise FixtureContractError("metal request payload is missing")
        return {}
    if family == "signage_decal":
        payload = request.get("localized_decal")
        if not isinstance(payload, dict):
            raise FixtureContractError("signage request payload is missing")
        return {
            "emission_strength": _bounded_number(
                payload.get("emission_strength"), "signage emission", 0.0, 1000.0
            )
        }
    if family == "emissive":
        payload = request.get("emissive_pattern")
        if not isinstance(payload, dict):
            raise FixtureContractError("emissive request payload is missing")
        return {
            "emission_strength": _bounded_number(
                payload.get("emission_strength"), "emission strength", 0.0, 1000.0
            )
        }
    payload = request.get("crystal")
    if not isinstance(payload, dict):
        raise FixtureContractError("crystal request payload is missing")
    return {
        "emission_strength": _bounded_number(
            payload.get("emission_strength"), "crystal emission", 0.0, 1000.0
        ),
        "ior": _bounded_number(payload.get("ior"), "crystal IOR", 1.0, 3.0),
        "transmission_weight": _bounded_number(
            payload.get("transmission"), "crystal transmission", 0.0, 1.0
        ),
    }


def _engine_identifier(scene: object) -> str:
    """Feature-probe Blender's EEVEE identifiers in the required preference order."""

    failures = []
    for identifier in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = identifier
        except (TypeError, ValueError, RuntimeError) as exc:
            failures.append(f"{identifier}: {exc}")
        else:
            return identifier
    raise FixtureContractError(
        "no supported EEVEE engine is available: " + "; ".join(failures)
    )


def _find_socket(node: object, semantic_id: str) -> object:
    """Resolve one Principled semantic through a fixed Blender-version alias list."""

    aliases = PRINCIPLED_INPUT_ALIASES[semantic_id]
    for name in aliases:
        socket = node.inputs.get(name)
        if socket is not None:
            return socket
    raise FixtureContractError(f"Principled semantic socket is unavailable: {semantic_id}")


def _set_node_identity(node: object, semantic_id: str, template_id: str) -> None:
    """Attach fixed semantic inventory identity to one compiled Blender node."""

    node.name = semantic_id
    node.label = semantic_id
    node["cbm_semantic_id"] = semantic_id
    node["cbm_template_id"] = template_id


def _load_channel_image(channel_id: str, channel: dict) -> object:
    """Load, interpret, and pack one exact host-authored channel without source writes."""

    image = bpy.data.images.load(str(channel["resolved_path"]), check_existing=False)
    image.name = f"channel.{channel_id}"
    if tuple(image.size) != (channel["width"], channel["height"]):
        raise FixtureContractError(f"{channel_id} Blender dimensions differ from the manifest")
    image.colorspace_settings.name = (
        "sRGB" if channel["color_space"] == "srgb" else "Non-Color"
    )
    image.pack()
    image.filepath = f"//packed/{channel_id}.png"
    return image


def _link(
    nodes: object,
    source: object,
    source_name: str,
    target_socket: object,
) -> None:
    """Create one fixed node link and fail if the declared output is unavailable."""

    source_socket = source.outputs.get(source_name)
    if source_socket is None:
        raise FixtureContractError(f"fixed source socket is unavailable: {source_name}")
    nodes.links.new(source_socket, target_socket)


def _compile_material(
    manifest: dict,
    request: dict,
    channel_map: dict[str, dict],
) -> tuple[object, dict[str, str], list[str]]:
    """Compile one family through a fixed image/normal/bump/Principled whitelist."""

    family = manifest["material_family"]
    parameters = _family_parameters(request, family)
    material = bpy.data.materials.new(name=f"fixture.{family}")
    material.use_nodes = True
    node_tree = material.node_tree
    node_tree.nodes.clear()
    output = node_tree.nodes.new("ShaderNodeOutputMaterial")
    _set_node_identity(output, "output", "material_output")
    output.location = (650.0, 0.0)
    principled = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    _set_node_identity(principled, "principled", "principled_bsdf")
    principled.location = (350.0, 0.0)
    output_surface = output.inputs.get("Surface")
    principled_output = principled.outputs.get("BSDF")
    if output_surface is None or principled_output is None:
        raise FixtureContractError("required shader surface sockets are unavailable")
    node_tree.links.new(principled_output, output_surface)
    socket_resolution: dict[str, str] = {}

    image_nodes: dict[str, object] = {}
    for index, channel_id in enumerate(sorted(channel_map)):
        image = _load_channel_image(channel_id, channel_map[channel_id])
        node = node_tree.nodes.new("ShaderNodeTexImage")
        _set_node_identity(node, f"channel.{channel_id}", "image_texture")
        node.location = (-700.0, 250.0 - index * 180.0)
        node.image = image
        node.interpolation = "Linear"
        node.extension = "CLIP" if family == "signage_decal" else "REPEAT"
        image_nodes[channel_id] = node

    for channel_id, semantic_id in (
        ("base_color", "base_color"),
        ("roughness", "roughness"),
        ("metallic", "metallic"),
        ("emission", "emission_color"),
        ("opacity", "alpha"),
    ):
        node = image_nodes.get(channel_id)
        if node is None:
            continue
        target = _find_socket(principled, semantic_id)
        socket_resolution[semantic_id] = target.name
        _link(node_tree, node, "Color", target)

    normal_node = None
    if "normal" in image_nodes:
        normal_node = node_tree.nodes.new("ShaderNodeNormalMap")
        _set_node_identity(normal_node, "normal_map", "normal_map")
        normal_node.location = (-300.0, -250.0)
        _link(node_tree, image_nodes["normal"], "Color", normal_node.inputs["Color"])
    if "height" in image_nodes:
        bump = node_tree.nodes.new("ShaderNodeBump")
        _set_node_identity(bump, "height_bump", "bump")
        bump.location = (20.0, -250.0)
        bump.inputs["Strength"].default_value = 0.2
        bump.inputs["Distance"].default_value = 0.02
        _link(node_tree, image_nodes["height"], "Color", bump.inputs["Height"])
        if normal_node is not None:
            _link(node_tree, normal_node, "Normal", bump.inputs["Normal"])
        normal_target = _find_socket(principled, "normal")
        socket_resolution["normal"] = normal_target.name
        _link(node_tree, bump, "Normal", normal_target)
    elif normal_node is not None:
        normal_target = _find_socket(principled, "normal")
        socket_resolution["normal"] = normal_target.name
        _link(node_tree, normal_node, "Normal", normal_target)

    for semantic_id, value in parameters.items():
        target = _find_socket(principled, semantic_id)
        target.default_value = value
        socket_resolution[semantic_id] = target.name

    render_method = "opaque"
    if "opacity" in image_nodes:
        if hasattr(material, "surface_render_method"):
            for value in ("DITHERED", "BLENDED"):
                try:
                    material.surface_render_method = value
                except (TypeError, ValueError, RuntimeError):
                    continue
                render_method = f"surface_render_method:{value}"
                break
        elif hasattr(material, "blend_method"):
            for value in ("HASHED", "BLEND"):
                try:
                    material.blend_method = value
                except (TypeError, ValueError, RuntimeError):
                    continue
                render_method = f"blend_method:{value}"
                break
        if render_method == "opaque":
            raise FixtureContractError("Blender alpha render method is unavailable")
    material["cbm_material_family"] = family
    material["cbm_manifest_sha256"] = manifest["_fixture_manifest_sha256"]
    limitations = {
        "wood": [
            "occlusion remains a packed portable channel and is not connected to Principled BSDF",
            "fixture UV orientation does not verify an asset object's authored grain basis",
        ],
        "metal": [
            "the fixed fixture validates declared brush-map direction, not object-basis alignment",
            "edge wear and unsupported scratch detail were not synthesized",
        ],
        "signage_decal": [
            "the fixed fixture verifies alpha compilation but not destination decal behavior",
        ],
        "emissive": [
            "the fixed fixture does not verify destination emission intensity or bloom parity",
        ],
        "crystal": [
            "volumetric absorption, explicit Fresnel weighting, and thickness are not compiled",
            "the fixed fixture does not verify destination transmission or refraction parity",
        ],
    }[family]
    socket_resolution["alpha_render_method"] = render_method
    return material, socket_resolution, limitations


def _aim_at(obj: object, target: tuple[float, float, float]) -> None:
    """Aim one fixed camera or light local -Z axis at a declared scene point."""

    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _create_scene(material: object, family: str, stage_root: Path) -> tuple[object, str]:
    """Create one fixed neutral studio without touching any authoring blend."""

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    engine = _engine_identifier(scene)
    scene.render.engine = engine
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.world.color = (0.04, 0.04, 0.04)

    if family == "signage_decal":
        bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0.0, 0.0, 0.0))
        preview = bpy.context.object
        preview.scale = (1.35, 0.75, 1.0)
    else:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
        preview = bpy.context.object
        preview.scale = (1.15, 1.15, 1.15)
    preview.name = f"fixture.{family}.preview"
    preview.data.materials.append(material)

    bpy.ops.object.camera_add(location=(0.0, -4.4, 2.3))
    camera = bpy.context.object
    camera.name = "fixture.camera"
    _aim_at(camera, (0.0, 0.0, 0.0))
    camera.data.lens = 52.0
    scene.camera = camera

    bpy.ops.object.light_add(type="AREA", location=(-2.5, -2.0, 4.0))
    key = bpy.context.object
    key.name = "fixture.light.key"
    key.data.energy = 850.0
    key.data.shape = "DISK"
    key.data.size = 4.0
    _aim_at(key, (0.0, 0.0, 0.0))
    bpy.ops.object.light_add(type="AREA", location=(3.0, 1.0, 1.8))
    fill = bpy.context.object
    fill.name = "fixture.light.fill"
    fill.data.energy = 450.0
    fill.data.size = 3.0
    _aim_at(fill, (0.0, 0.0, 0.0))

    blend_path = stage_root / "compiled_fixture.blend"
    scene.render.filepath = "//neutral_preview.png"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
    bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
    return blend_path, engine


def _inventory_material(material_name: str, socket_resolution: dict[str, str]) -> dict:
    """Reopen and normalize actual Blender nodes, links, and packed image state."""

    material = bpy.data.materials.get(material_name)
    if material is None or material.node_tree is None:
        raise FixtureContractError("compiled material is missing after reopen")
    nodes = []
    for node in material.node_tree.nodes:
        semantic_id = node.get("cbm_semantic_id")
        template_id = node.get("cbm_template_id")
        if not isinstance(semantic_id, str) or not isinstance(template_id, str):
            raise FixtureContractError("compiled node is missing fixed semantic identity")
        nodes.append(
            {
                "blender_type": node.bl_idname,
                "semantic_id": semantic_id,
                "template_id": template_id,
            }
        )
    links = []
    for link in material.node_tree.links:
        links.append(
            {
                "source_node_id": link.from_node["cbm_semantic_id"],
                "source_socket": link.from_socket.name,
                "target_node_id": link.to_node["cbm_semantic_id"],
                "target_socket": link.to_socket.name,
            }
        )
    images = []
    for image in bpy.data.images:
        if not image.name.startswith("channel."):
            continue
        packed = image.packed_file is not None or bool(getattr(image, "packed_files", []))
        if not packed:
            raise FixtureContractError(f"compiled image is not packed: {image.name}")
        images.append(
            {
                "channel": image.name.removeprefix("channel."),
                "color_space": image.colorspace_settings.name,
                "height": image.size[1],
                "packed": True,
                "width": image.size[0],
            }
        )
    normalized = {
        "images": sorted(images, key=lambda item: item["channel"]),
        "links": sorted(
            links,
            key=lambda item: (
                item["target_node_id"],
                item["target_socket"],
                item["source_node_id"],
                item["source_socket"],
            ),
        ),
        "nodes": sorted(nodes, key=lambda item: item["semantic_id"]),
        "principled_socket_resolution": dict(sorted(socket_resolution.items())),
    }
    return {
        "schema_version": FIXTURE_VERSION,
        "normalized_inventory": normalized,
        "normalized_inventory_sha256": _canonical_sha256(normalized),
    }


def _write_json(path: Path, value: object) -> None:
    """Write stable UTF-8 JSON evidence without absolute host paths."""

    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact_receipt(stage_path: Path, final_relative_path: str, role: str) -> dict:
    """Describe one derived fixture artifact by final job-relative path and exact bytes."""

    return {
        "byte_size": stage_path.stat().st_size,
        "path": final_relative_path,
        "role": role,
        "sha256": _sha256_file(stage_path),
    }


def _revalidate_sources(root: Path, manifest_path: Path, manifest: dict) -> None:
    """Rehash immutable manifest, request, and channels after Blender work completes."""

    expected_manifest = _sha256_file(manifest_path)
    if expected_manifest != manifest["_fixture_manifest_sha256"]:
        raise FixtureContractError("material manifest changed during Blender fixture execution")
    _validate_artifact(root, manifest["request"], "request recheck")
    for channel in manifest["channels"]:
        _validate_artifact(root, channel["artifact"], f"{channel['channel']} recheck")


def main() -> None:
    """Validate, compile, reopen, render, and atomically publish isolated evidence."""

    args = _parse_args()
    root = Path(args.job_root).resolve(strict=True)
    if not root.is_dir():
        raise FixtureContractError("job root is not a directory")
    manifest_relative = _relative_path(args.manifest, "manifest path")
    output_relative = _relative_path(args.output_root, "output root")
    if not manifest_relative.startswith(MANIFEST_PREFIX):
        raise FixtureContractError("manifest is outside the run-owned authoring root")
    if not output_relative.startswith(OUTPUT_PREFIX):
        raise FixtureContractError("output root is outside the isolated Blender smoke root")
    _portable_id(output_relative.removeprefix(OUTPUT_PREFIX), "fixture run ID")
    manifest_path = _resolve_contained(root, manifest_relative, must_exist=True)
    manifest_hash = _sha256(args.manifest_sha256, "manifest SHA-256")
    manifest, request, channels = _validate_manifest(root, manifest_path, manifest_hash)
    manifest["_fixture_manifest_sha256"] = manifest_hash

    final_root = _resolve_contained(root, output_relative, must_exist=False)
    if final_root.exists():
        raise FixtureContractError("fixture output root already exists")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    stage_root = final_root.parent / f".{final_root.name}.staging-{uuid4().hex}"
    stage_root.mkdir()

    material, sockets, limitations = _compile_material(manifest, request, channels)
    material_name = material.name
    blend_path, engine = _create_scene(material, manifest["material_family"], stage_root)
    preview_path = stage_root / "neutral_preview.png"
    if not preview_path.is_file() or preview_path.stat().st_size == 0:
        raise FixtureContractError("neutral preview was not rendered")
    bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=False)
    inventory = _inventory_material(material_name, sockets)
    inventory_path = stage_root / "normalized_inventory.json"
    _write_json(inventory_path, inventory)
    _revalidate_sources(root, manifest_path, manifest)
    if manifest["material_family"] == "metal":
        revalidated = _validate_metal_contract(root, manifest, request, channels)
        if revalidated != manifest["_fixture_validated_family_contract"]:
            raise FixtureContractError("metal fixture contract changed during Blender execution")

    final_prefix = output_relative + "/"
    artifacts = [
        _artifact_receipt(
            blend_path, final_prefix + "compiled_fixture.blend", "compiled_blend"
        ),
        _artifact_receipt(
            preview_path, final_prefix + "neutral_preview.png", "neutral_preview"
        ),
        _artifact_receipt(
            inventory_path,
            final_prefix + "normalized_inventory.json",
            "normalized_inventory",
        ),
    ]
    receipt = {
        "arbitrary_code_used": False,
        "artifacts": artifacts,
        "blender_version": bpy.app.version_string,
        "canonical_write_performed": False,
        "compiled_blend_determinism_basis": False,
        "destination_write_performed": False,
        "external_provider_used": False,
        "fixture_id": final_root.name,
        "fixture_scope": "compile_reopen_and_neutral_preview_only",
        "limitations": limitations,
        "manifest_path": manifest_relative,
        "manifest_sha256": manifest_hash,
        "material_family": manifest["material_family"],
        "normalized_inventory_sha256": inventory["normalized_inventory_sha256"],
        "render_engine": engine,
        "runtime_parity_verified": False,
        "schema_version": FIXTURE_VERSION,
        "source_manifest_unchanged": True,
        "status": "passed",
        "validated_family_contract": manifest["_fixture_validated_family_contract"],
    }
    _write_json(stage_root / "blender_smoke_receipt.json", receipt)
    os.replace(stage_root, final_root)
    print(
        json.dumps(
            {
                "blender_version": bpy.app.version_string,
                "fixture_id": final_root.name,
                "material_family": manifest["material_family"],
                "status": "passed",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
