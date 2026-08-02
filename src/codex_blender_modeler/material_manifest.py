from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

IMAGE_CHANNELS = {"base_color", "roughness", "metallic", "normal", "height", "opacity", "emission"}
COLOR_CHANNELS = {"base_color", "emission"}
DATA_CHANNELS = IMAGE_CHANNELS - COLOR_CHANNELS
SOURCE_TYPES = {"image", "procedural", "hybrid"}
UV_SETS = {"UVMap", "Generated", "Object"}
PROCEDURAL_COORDINATE_SETS = UV_SETS | {"World"}
RUNTIME_PROCEDURAL_CHANNELS = {"base_color", "roughness", "height"}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class MaterialManifestError(ValueError):
    """Report a deterministic material-manifest validation failure."""


def _resolve_inside(root: Path, candidate: Path, label: str) -> Path:
    """Resolve a manifest-owned path while rejecting workspace traversal."""

    resolved_root = root.expanduser().resolve()
    resolved = candidate.expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise MaterialManifestError(f"{label} must stay inside job root: {resolved}") from exc
    return resolved


def _validate_resolution(value: Any) -> list[int]:
    """Validate the declared draft texture dimensions."""

    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, int) or item < 1 or item > 8192 for item in value)
    ):
        raise MaterialManifestError("resolution must be [width, height] integers in [1, 8192]")
    return value


def _validate_channel(
    name: str,
    value: Any,
    *,
    job_root: Path,
    manifest_dir: Path,
) -> dict[str, Any]:
    """Validate one image or procedural channel and resolve its optional file."""

    if name not in IMAGE_CHANNELS:
        raise MaterialManifestError(f"Unsupported material channel: {name}")
    if not isinstance(value, dict):
        raise MaterialManifestError(f"Channel {name} must be an object")

    result = dict(value)
    source = result.get("source", "image" if result.get("path") else "procedural")
    if source not in {"image", "procedural"}:
        raise MaterialManifestError(f"Channel {name} source must be image or procedural")
    result["source"] = source

    if source == "image":
        path_value = result.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise MaterialManifestError(f"Image channel {name} requires a path")
        resolved = _resolve_inside(job_root, manifest_dir / path_value, f"Channel {name} path")
        if not resolved.is_file():
            raise MaterialManifestError(f"Channel {name} file does not exist: {resolved}")
        result["resolved_path"] = str(resolved)

        expected_color_space = "sRGB" if name in COLOR_CHANNELS else "Non-Color"
        color_space = result.get("color_space", expected_color_space)
        if color_space != expected_color_space:
            raise MaterialManifestError(
                f"Channel {name} color_space must be {expected_color_space}, got {color_space}"
            )
        result["color_space"] = color_space
    elif result.get("path") is not None:
        raise MaterialManifestError(f"Procedural channel {name} must not declare a path")

    return result


def _validate_ramp(value: Any, label: str) -> None:
    """Validate one runtime ColorRamp contract before Blender node construction."""

    if not isinstance(value, list) or len(value) < 2:
        raise MaterialManifestError(f"{label} requires at least two ramp entries")
    for index, entry in enumerate(value):
        if not isinstance(entry, list) or len(entry) != 2:
            raise MaterialManifestError(f"{label}[{index}] must be [position, color]")
        position, color = entry
        if not isinstance(position, (int, float)) or not 0 <= float(position) <= 1:
            raise MaterialManifestError(f"{label}[{index}] position must be within [0, 1]")
        if (
            not isinstance(color, list)
            or len(color) != 4
            or any(not isinstance(component, (int, float)) for component in color)
        ):
            raise MaterialManifestError(f"{label}[{index}] color must have four numbers")


def _validate_runtime_procedural(channels: dict[str, dict[str, Any]], value: Any) -> dict:
    """Reject procedural declarations that the current Blender graph cannot consume."""

    if not isinstance(value, dict):
        raise MaterialManifestError("procedural must be an object")
    result = dict(value)
    procedural_uv_set = result.get("coordinate_uv_set")
    if (
        procedural_uv_set is not None
        and procedural_uv_set not in PROCEDURAL_COORDINATE_SETS
    ):
        raise MaterialManifestError(
            "procedural.coordinate_uv_set must be one of "
            f"{sorted(PROCEDURAL_COORDINATE_SETS)}"
        )
    procedural_scale = result.get("coordinate_scale_m")
    if procedural_scale is not None and (
        not isinstance(procedural_scale, (int, float))
        or isinstance(procedural_scale, bool)
        or float(procedural_scale) <= 0
    ):
        raise MaterialManifestError(
            "procedural.coordinate_scale_m must be a positive number"
        )
    if procedural_scale is not None:
        result["coordinate_scale_m"] = float(procedural_scale)
    procedural_channels = {
        name for name, channel in channels.items() if channel["source"] == "procedural"
    }
    if not procedural_channels:
        return result
    unsupported = sorted(procedural_channels - RUNTIME_PROCEDURAL_CHANNELS)
    if unsupported:
        raise MaterialManifestError(
            f"Procedural channels are outside the Blender runtime subset: {unsupported}"
        )
    noise = result.get("noise")
    if not isinstance(noise, dict):
        raise MaterialManifestError("Procedural channels require procedural.noise")
    for name in ("scale", "detail", "roughness", "distortion"):
        setting = noise.get(name)
        if setting is not None and (
            not isinstance(setting, (int, float)) or float(setting) < 0
        ):
            raise MaterialManifestError(f"procedural.noise.{name} must be non-negative")
    if "base_color" in procedural_channels:
        _validate_ramp(result.get("base_color_ramp"), "procedural.base_color_ramp")
    if "roughness" in procedural_channels:
        _validate_ramp(result.get("roughness_ramp"), "procedural.roughness_ramp")
    if "height" in procedural_channels:
        strength = result.get("bump_strength")
        if not isinstance(strength, (int, float)) or float(strength) <= 0:
            raise MaterialManifestError(
                "Procedural height requires a positive procedural.bump_strength"
            )
    return result


def _validate_surface_detail_bindings(
    raw: dict[str, Any],
    *,
    material_id: str,
    uv_set: str,
    channels: dict[str, dict[str, Any]],
    manifest_dir: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Normalize strict spatial-detail bindings for the Blender-safe runtime loader."""

    detail_ids = raw.get("surface_detail_ids", [])
    if (
        not isinstance(detail_ids, list)
        or any(not isinstance(value, str) or not value.strip() for value in detail_ids)
        or len(detail_ids) != len(set(detail_ids))
    ):
        raise MaterialManifestError(
            "surface_detail_ids must be a unique list of non-empty strings"
        )
    bindings = raw.get("surface_detail_bindings", [])
    if not isinstance(bindings, list):
        raise MaterialManifestError("surface_detail_bindings must be a list")
    if not bindings:
        return list(detail_ids), []

    normalized: list[dict[str, Any]] = []
    binding_ids: list[str] = []
    wraps: set[str] = set()
    allowed_binding_keys = {
        "detail_id",
        "parent_object_id",
        "material_id",
        "uv_set",
        "uv_layout_sha256",
        "placement",
        "channels",
        "strength",
        "wrap",
    }
    for index, value in enumerate(bindings):
        if not isinstance(value, dict) or set(value) - allowed_binding_keys:
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}] contains invalid fields"
            )
        binding = dict(value)
        for name in ("detail_id", "parent_object_id", "material_id"):
            field = binding.get(name)
            if not isinstance(field, str) or not field.strip():
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}].{name} must be non-empty"
                )
        if binding["material_id"] != material_id:
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].material_id must match the manifest"
            )
        binding_uv_set = binding.get("uv_set", "UVMap")
        if binding_uv_set != "UVMap" or binding_uv_set != uv_set:
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].uv_set must match manifest UVMap"
            )
        uv_hash = binding.get("uv_layout_sha256")
        if not isinstance(uv_hash, str) or _SHA256_PATTERN.fullmatch(uv_hash) is None:
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].uv_layout_sha256 must be lowercase SHA-256"
            )
        binding_channels = binding.get("channels")
        if (
            not isinstance(binding_channels, list)
            or not binding_channels
            or any(name not in channels for name in binding_channels)
            or len(binding_channels) != len(set(binding_channels))
        ):
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].channels must be unique manifest channels"
            )
        non_image_channels = sorted(
            name for name in binding_channels if channels[name]["source"] != "image"
        )
        if non_image_channels:
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].channels must be image-backed: "
                f"{non_image_channels}"
            )
        strength = binding.get("strength", 1.0)
        if (
            not isinstance(strength, (int, float))
            or isinstance(strength, bool)
            or not 0.0 < float(strength) <= 1.0
        ):
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].strength must be within (0, 1]"
            )
        wrap = binding.get("wrap", "clamp")
        if wrap not in {"clip", "clamp"}:
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].wrap must be clip or clamp"
            )
        wraps.add(str(wrap))

        placement = binding.get("placement")
        if not isinstance(placement, dict):
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].placement must be an object"
            )
        mode = placement.get("mode")
        normalized_placement = dict(placement)
        if mode == "uv_rect":
            if set(placement) != {"mode", "uv_rect"}:
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}] uv_rect placement has invalid fields"
                )
            uv_rect = placement.get("uv_rect")
            if (
                not isinstance(uv_rect, list)
                or len(uv_rect) != 4
                or any(
                    not isinstance(item, (int, float))
                    or isinstance(item, bool)
                    or not 0.0 <= float(item) <= 1.0
                    for item in uv_rect
                )
            ):
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}].placement.uv_rect is invalid"
                )
            u0, v0, u1, v1 = (float(item) for item in uv_rect)
            if u1 <= u0 or v1 <= v0:
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}].placement.uv_rect has no area"
                )
            normalized_placement["uv_rect"] = [u0, v0, u1, v1]
        elif mode == "mask_image":
            if set(placement) != {"mode", "mask_path", "mask_sha256"}:
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}] mask placement has invalid fields"
                )
            mask_value = placement.get("mask_path")
            mask_hash = placement.get("mask_sha256")
            if not isinstance(mask_value, str) or not mask_value.strip():
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}].placement.mask_path is required"
                )
            candidate = PurePosixPath(mask_value)
            if (
                candidate.is_absolute()
                or "\\" in mask_value
                or ":" in mask_value
                or any(part in {"", ".", ".."} for part in candidate.parts)
            ):
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}].placement.mask_path must be contained"
                )
            mask_path = _resolve_inside(
                manifest_dir,
                manifest_dir / mask_value,
                f"surface_detail_bindings[{index}] mask_path",
            )
            if not mask_path.is_file():
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}] mask file does not exist"
                )
            if not isinstance(mask_hash, str) or _SHA256_PATTERN.fullmatch(mask_hash) is None:
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}].placement.mask_sha256 is invalid"
                )
            actual_hash = hashlib.sha256(mask_path.read_bytes()).hexdigest()
            if actual_hash != mask_hash:
                raise MaterialManifestError(
                    f"surface_detail_bindings[{index}] mask SHA-256 differs"
                )
            normalized_placement["resolved_mask_path"] = str(mask_path)
        else:
            raise MaterialManifestError(
                f"surface_detail_bindings[{index}].placement.mode is unsupported"
            )
        binding["uv_set"] = binding_uv_set
        binding["strength"] = float(strength)
        binding["wrap"] = wrap
        binding["placement"] = normalized_placement
        binding_ids.append(str(binding["detail_id"]))
        normalized.append(binding)

    if len(binding_ids) != len(set(binding_ids)) or set(binding_ids) != set(detail_ids):
        raise MaterialManifestError(
            "surface_detail_bindings must uniquely and exactly cover surface_detail_ids"
        )
    if len(wraps) != 1:
        raise MaterialManifestError(
            "surface_detail_bindings must use one shared non-repeating wrap mode"
        )
    return list(detail_ids), normalized


def load_material_manifest(
    material_spec: dict[str, Any], job_root: Path
) -> tuple[dict[str, Any] | None, Path | None]:
    """Load and validate one workspace-relative material manifest."""

    manifest_value = material_spec.get("texture_manifest")
    if not manifest_value:
        return None, None
    if not isinstance(manifest_value, str):
        raise MaterialManifestError("texture_manifest must be a string or null")

    resolved_root = job_root.expanduser().resolve()
    manifest_path = _resolve_inside(
        resolved_root,
        resolved_root / manifest_value,
        "texture_manifest",
    )
    if not manifest_path.is_file():
        raise MaterialManifestError(f"texture_manifest does not exist: {manifest_path}")

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MaterialManifestError(f"Invalid texture manifest JSON: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise MaterialManifestError("texture manifest root must be an object")
    schema_version = raw.get("schema_version", "0.5.0")
    if schema_version != "0.5.0":
        raise MaterialManifestError(
            f"Unsupported texture manifest schema_version: {schema_version!r}"
        )
    if raw.get("material_id") != material_spec.get("id"):
        raise MaterialManifestError(
            "texture manifest material_id must match SceneSpec material id"
        )

    source_type = raw.get("source_type")
    if source_type not in SOURCE_TYPES:
        raise MaterialManifestError(f"source_type must be one of {sorted(SOURCE_TYPES)}")
    uv_set = raw.get("uv_set", "Object")
    if uv_set not in UV_SETS:
        raise MaterialManifestError(f"uv_set must be one of {sorted(UV_SETS)}")
    intended_scale = raw.get("intended_scale_m")
    if not isinstance(intended_scale, (int, float)) or intended_scale <= 0:
        raise MaterialManifestError("intended_scale_m must be a positive number")

    result = dict(raw)
    result["schema_version"] = schema_version
    result["source_type"] = source_type
    result["uv_set"] = uv_set
    result["intended_scale_m"] = float(intended_scale)
    result["resolution"] = _validate_resolution(raw.get("resolution"))
    channels = raw.get("channels", {})
    if not isinstance(channels, dict):
        raise MaterialManifestError("channels must be an object")
    result["channels"] = {
        name: _validate_channel(
            name,
            value,
            job_root=resolved_root,
            manifest_dir=manifest_path.parent,
        )
        for name, value in channels.items()
    }
    image_count = sum(
        channel["source"] == "image" for channel in result["channels"].values()
    )
    procedural_count = sum(
        channel["source"] == "procedural" for channel in result["channels"].values()
    )
    if source_type == "image" and (not image_count or procedural_count):
        raise MaterialManifestError(
            "source_type image requires at least one image channel and no procedural channels"
        )
    if source_type == "procedural" and (not procedural_count or image_count):
        raise MaterialManifestError(
            "source_type procedural requires at least one procedural channel and no image channels"
        )
    if source_type == "hybrid" and (not image_count or not procedural_count):
        raise MaterialManifestError(
            "source_type hybrid requires both image and procedural channels"
        )
    shared_color_spaces: dict[str, str] = {}
    for name, channel in result["channels"].items():
        resolved_path = channel.get("resolved_path")
        if not resolved_path:
            continue
        color_space = str(channel["color_space"])
        previous = shared_color_spaces.setdefault(str(resolved_path), color_space)
        if previous != color_space:
            raise MaterialManifestError(
                f"Image file reused with conflicting color spaces: {resolved_path} "
                f"({previous} vs {color_space} for {name})"
            )
    result["procedural"] = _validate_runtime_procedural(
        result["channels"], raw.get("procedural", {})
    )
    detail_ids, bindings = _validate_surface_detail_bindings(
        raw,
        material_id=str(material_spec.get("id")),
        uv_set=uv_set,
        channels=result["channels"],
        manifest_dir=manifest_path.parent,
    )
    result["surface_detail_ids"] = detail_ids
    result["surface_detail_bindings"] = bindings
    result["resolved_manifest_path"] = str(manifest_path)
    return result, manifest_path
