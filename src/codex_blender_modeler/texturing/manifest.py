from __future__ import annotations

import json
from pathlib import Path

from ..blender_artifacts import native_io_path
from ..material_manifest import (
    COLOR_CHANNELS,
    DATA_CHANNELS,
    IMAGE_CHANNELS,
    SOURCE_TYPES,
    UV_SETS,
    MaterialManifestError,
    load_material_manifest,
)
from .models import TextureManifest


def load_texture_manifest(path: Path) -> TextureManifest:
    """Read native long paths while retaining the existing V0.5 legacy-version default."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise MaterialManifestError("texture manifest root must be an object")
    raw.setdefault("schema_version", "0.5.0")
    return TextureManifest.model_validate(raw)


__all__ = [
    "DATA_CHANNELS",
    "COLOR_CHANNELS",
    "IMAGE_CHANNELS",
    "SOURCE_TYPES",
    "UV_SETS",
    "MaterialManifestError",
    "load_material_manifest",
    "load_texture_manifest",
]
