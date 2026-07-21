"""Preserve raw PBR channels and derive deterministic glTF ORM textures."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

PORTABLE_PBR_CHANNELS = frozenset(
    {
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "occlusion",
        "emission",
        "opacity",
        "height",
    }
)
ORM_CHANNELS = ("occlusion", "roughness", "metallic")
RAW_CHANNEL_COLOR_SPACES = {
    "base_color": "sRGB",
    "emission": "sRGB",
    "roughness": "Non-Color",
    "metallic": "Non-Color",
    "normal": "Non-Color",
    "occlusion": "Non-Color",
    "opacity": "Non-Color",
    "height": "Non-Color",
}


class TexturePackingError(ValueError):
    """Report a deterministic portable-texture packaging failure."""


@dataclass(frozen=True)
class TexturePackingResult:
    """Return committed paths, hashes, and low-level deterministic pack evidence."""

    package_dir: Path
    evidence_path: Path
    orm_path: Path
    raw_paths: dict[str, Path]
    evidence_sha256: str
    orm_sha256: str
    evidence: dict[str, Any]


def _sha256_file(path: Path) -> str:
    """Hash a file without loading the entire payload into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_inside(root: Path, candidate: str | Path, label: str) -> Path:
    """Resolve one path while rejecting traversal and symlink escape."""

    resolved_root = root.expanduser().resolve()
    value = Path(candidate).expanduser()
    resolved = (value if value.is_absolute() else resolved_root / value).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise TexturePackingError(f"{label} must stay inside {resolved_root}") from exc
    return resolved


def _validate_resolution(value: tuple[int, int] | None) -> tuple[int, int] | None:
    """Validate an optional explicit ORM resolution."""

    if value is None:
        return None
    if (
        len(value) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or any(item < 1 or item > 8192 for item in value)
    ):
        raise TexturePackingError("resolution must contain two integers in [1, 8192]")
    return (value[0], value[1])


def _constant_byte(value: float | int, channel: str) -> int:
    """Convert one explicit normalized default into an unsigned channel byte."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TexturePackingError(f"Default {channel} must be a number in [0, 1]")
    normalized = float(value)
    if not 0.0 <= normalized <= 1.0:
        raise TexturePackingError(f"Default {channel} must be within [0, 1]")
    return int(normalized * 255.0 + 0.5)


def _load_source_images(
    source_root: Path,
    channels: Mapping[str, str | Path],
) -> tuple[dict[str, Path], dict[str, dict[str, Any]]]:
    """Validate supported source channels and collect portable image metadata."""

    unsupported = sorted(set(channels) - PORTABLE_PBR_CHANNELS)
    if unsupported:
        raise TexturePackingError(f"Unsupported raw PBR channels: {unsupported}")
    resolved: dict[str, Path] = {}
    metadata: dict[str, dict[str, Any]] = {}
    root = source_root.expanduser().resolve()
    for channel in sorted(channels):
        path = _resolve_inside(root, channels[channel], f"Source channel {channel}")
        if not path.is_file():
            raise TexturePackingError(f"Source channel {channel} does not exist: {path}")
        try:
            with Image.open(path) as image:
                image.load()
                size = [int(image.width), int(image.height)]
                mode = image.mode
                image_format = image.format or path.suffix.removeprefix(".").upper()
        except (OSError, ValueError) as exc:
            raise TexturePackingError(
                f"Source channel {channel} is not a readable image: {path}"
            ) from exc
        relative = path.relative_to(root).as_posix()
        resolved[channel] = path
        metadata[channel] = {
            "source_path": relative,
            "source_sha256": _sha256_file(path),
            "color_space": RAW_CHANNEL_COLOR_SPACES[channel],
            "resolution": size,
            "source_mode": mode,
            "source_format": image_format,
        }
    return resolved, metadata


def _orm_resolution(
    sources: Mapping[str, Path],
    requested: tuple[int, int] | None,
    allow_resample: bool,
) -> tuple[int, int]:
    """Choose one ORM size while requiring explicit permission for any resampling."""

    discovered: set[tuple[int, int]] = set()
    for channel in ORM_CHANNELS:
        path = sources.get(channel)
        if path is None:
            continue
        with Image.open(path) as image:
            discovered.add((image.width, image.height))
    if len(discovered) > 1 and not (allow_resample and requested is not None):
        raise TexturePackingError("ORM source channels must have identical resolutions")
    source_resolution = next(iter(discovered), None)
    if requested is not None and source_resolution is not None and requested != source_resolution:
        if not allow_resample:
            raise TexturePackingError(
                "Explicit ORM resolution must match image channels; implicit resampling is "
                "forbidden"
            )
    if requested is not None:
        return requested
    if source_resolution is not None:
        return source_resolution
    raise TexturePackingError(
        "resolution is required when all ORM channels use explicit constant defaults"
    )


def _orm_planes(
    sources: Mapping[str, Path],
    defaults: Mapping[str, float | int],
    resolution: tuple[int, int],
    allow_resample: bool,
) -> tuple[list[Image.Image], dict[str, dict[str, Any]]]:
    """Load grayscale ORM planes or create explicitly requested constant planes."""

    invalid_defaults = sorted(set(defaults) - set(ORM_CHANNELS))
    if invalid_defaults:
        raise TexturePackingError(f"Unsupported ORM defaults: {invalid_defaults}")
    planes: list[Image.Image] = []
    inputs: dict[str, dict[str, Any]] = {}
    for channel in ORM_CHANNELS:
        path = sources.get(channel)
        if path is not None:
            with Image.open(path) as image:
                plane = image.convert("L")
                plane.load()
            source_resolution = plane.size
            if source_resolution != resolution:
                if not allow_resample:
                    plane.close()
                    raise TexturePackingError(
                        f"ORM channel {channel} requires explicit resampling permission"
                    )
                resized = plane.resize(resolution, resample=Image.Resampling.BOX)
                plane.close()
                plane = resized
            planes.append(plane)
            inputs[channel] = {
                "kind": "image",
                "source_resolution": list(source_resolution),
                "output_resolution": list(resolution),
                "resampled": source_resolution != resolution,
                "resample_filter": "BOX" if source_resolution != resolution else None,
            }
            continue
        if channel not in defaults:
            raise TexturePackingError(
                f"Missing ORM channel {channel}; provide an image or explicit normalized default"
            )
        byte = _constant_byte(defaults[channel], channel)
        normalized = float(defaults[channel])
        planes.append(Image.new("L", resolution, color=byte))
        inputs[channel] = {
            "kind": "constant",
            "normalized_value": normalized,
            "encoded_byte": byte,
        }
    return planes, inputs


def _save_deterministic_png(image: Image.Image, path: Path) -> None:
    """Write a PNG without variable metadata using fixed encoder settings."""

    image.save(path, format="PNG", optimize=False, compress_level=9)


def _write_evidence(path: Path, payload: Mapping[str, Any]) -> None:
    """Write low-level pack evidence inside the uncommitted staging directory."""

    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_portable_texture_package(
    *,
    source_root: Path,
    package_root: Path,
    output_dir: str | Path,
    channels: Mapping[str, str | Path],
    orm_defaults: Mapping[str, float | int] | None = None,
    orm_resolution: tuple[int, int] | None = None,
    allow_orm_resample: bool = False,
    atomic_commit: bool = True,
) -> TexturePackingResult:
    """Create an immutable raw-channel package plus a deterministic glTF ORM map.

    Raw source bytes are copied without modification. The derived ORM PNG uses
    occlusion, roughness, and metallic in its red, green, and blue channels.
    Missing ORM inputs are accepted only when their normalized constants are
    explicitly supplied by the caller.
    """

    resolved_source_root = source_root.expanduser().resolve()
    resolved_package_root = package_root.expanduser().resolve()
    destination = _resolve_inside(resolved_package_root, output_dir, "Texture package output")
    if destination == resolved_package_root:
        raise TexturePackingError("Texture package output must be below package_root")
    if destination.exists():
        raise FileExistsError(f"Texture package already exists: {destination}")

    requested_resolution = _validate_resolution(orm_resolution)
    resolved_channels, source_records = _load_source_images(
        resolved_source_root,
        channels,
    )
    resolution = _orm_resolution(
        resolved_channels,
        requested_resolution,
        allow_orm_resample,
    )
    defaults = dict(orm_defaults or {})
    planes, orm_inputs = _orm_planes(
        resolved_channels,
        defaults,
        resolution,
        allow_orm_resample,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = (
        destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
        if atomic_commit
        else destination
    )
    raw_dir = staging / "raw"
    packed_dir = staging / "packed"
    try:
        raw_dir.mkdir(parents=True)
        packed_dir.mkdir(parents=True)
        raw_records: dict[str, dict[str, Any]] = {}
        for channel in sorted(resolved_channels):
            source = resolved_channels[channel]
            suffix = source.suffix.lower() or ".bin"
            target = raw_dir / f"{channel}{suffix}"
            shutil.copyfile(source, target)
            copied_sha256 = _sha256_file(target)
            source_record = source_records[channel]
            if copied_sha256 != source_record["source_sha256"]:
                raise TexturePackingError(f"Raw channel copy hash mismatch: {channel}")
            raw_records[channel] = {
                **source_record,
                "package_path": target.relative_to(staging).as_posix(),
                "package_sha256": copied_sha256,
                "preserved_byte_for_byte": True,
            }

        orm_path = packed_dir / "gltf_orm.png"
        orm_image: Image.Image | None = None
        try:
            orm_image = Image.merge("RGB", tuple(planes))
            _save_deterministic_png(orm_image, orm_path)
        finally:
            if orm_image is not None:
                orm_image.close()
            for plane in planes:
                plane.close()
        orm_sha256 = _sha256_file(orm_path)
        evidence: dict[str, Any] = {
            "kind": "low_level_texture_pack_evidence",
            "evidence_version": "0.7.0",
            "profile": "gltf_metallic_roughness",
            "raw_channels": raw_records,
            "packed_textures": {
                "gltf_orm": {
                    "path": orm_path.relative_to(staging).as_posix(),
                    "sha256": orm_sha256,
                    "format": "PNG",
                    "mode": "RGB",
                    "resolution": [resolution[0], resolution[1]],
                    "color_space": "Non-Color",
                    "channel_mapping": {
                        "R": "occlusion",
                        "G": "roughness",
                        "B": "metallic",
                    },
                    "inputs": orm_inputs,
                }
            },
            "provenance": {
                "generator": "codex_blender_modeler.packaging.texture_packing",
                "generator_contract_version": "0.7.0",
                "deterministic": True,
                "input_paths_are_source_root_relative": True,
                "raw_channels_preserved": True,
                "engine_specific_packing": False,
                "orm_resampling": bool(
                    any(
                        record.get("resampled", False)
                        for record in orm_inputs.values()
                    )
                ),
                "orm_resample_filter": "BOX" if allow_orm_resample else None,
            },
            "color_space_semantics": {
                "color_channels": ["base_color", "emission"],
                "color_channels_space": "sRGB",
                "data_channels": sorted(PORTABLE_PBR_CHANNELS - {"base_color", "emission"}),
                "data_channels_space": "Non-Color",
                "gltf_orm": "Non-Color",
            },
        }
        evidence_path = staging / "texture_pack_evidence.json"
        _write_evidence(evidence_path, evidence)
        if atomic_commit:
            os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    committed_evidence = destination / "texture_pack_evidence.json"
    committed_orm = destination / "packed" / "gltf_orm.png"
    return TexturePackingResult(
        package_dir=destination,
        evidence_path=committed_evidence,
        orm_path=committed_orm,
        raw_paths={
            channel: destination / record["package_path"] for channel, record in raw_records.items()
        },
        evidence_sha256=_sha256_file(committed_evidence),
        orm_sha256=orm_sha256,
        evidence=evidence,
    )
