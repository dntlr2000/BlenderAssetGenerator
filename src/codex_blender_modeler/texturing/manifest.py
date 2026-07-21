from __future__ import annotations

import json
from pathlib import Path

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
    """Load a v0.5 texture contract, normalizing a missing legacy version field."""

    raw = json.loads(path.read_text(encoding="utf-8"))
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
