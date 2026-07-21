from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """Hash one conversion input or output without loading the file at once."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_component(value: str) -> str:
    """Convert one stable material ID into a traversal-safe directory component."""

    if re.fullmatch(r"[A-Za-z0-9._-]+", value) and value not in {".", ".."}:
        return value
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "material"
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{suffix}"


def stable_identifier(value: str, prefix: str) -> str:
    """Create a deterministic V0.7 StableId without filesystem-only underscores."""

    normalized_prefix = re.sub(r"[^A-Za-z0-9.:-]+", ".", prefix).strip(".:-")
    normalized_value = re.sub(r"[^A-Za-z0-9.:-]+", ".", value).strip(".:-")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    base = f"{normalized_prefix}.{normalized_value}" if normalized_value else normalized_prefix
    maximum_base = 127 - len(digest) - 1
    base = base[:maximum_base].rstrip(".:-")
    return f"{base}.{digest}"


def fingerprint_json(value: Any) -> str:
    """Hash one JSON-compatible conversion record using canonical key ordering."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def grid_shape(count: int) -> tuple[int, int]:
    """Return the smallest near-square deterministic atlas grid for an object count."""

    if count < 1:
        raise ValueError("Atlas object count must be positive")
    columns = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / columns))
    return columns, rows


def atlas_tile_bounds(
    index: int,
    count: int,
    resolution: int,
    margin_px: int,
) -> tuple[float, float, float, float]:
    """Allocate one inset non-overlapping UV tile in stable row-major order."""

    if index < 0 or index >= count:
        raise ValueError(f"Atlas tile index {index} is outside [0, {count})")
    if resolution < 1:
        raise ValueError("Atlas resolution must be positive")
    if margin_px < 0:
        raise ValueError("Atlas margin must be non-negative")
    columns, rows = grid_shape(count)
    column = index % columns
    row = index // columns
    cell_width = 1.0 / columns
    cell_height = 1.0 / rows
    # Reserve the full bake dilation on every tile edge so neighboring margins meet
    # at the cell boundary without writing into another object's usable UV region.
    inset = margin_px / resolution
    if inset * 2.0 >= min(cell_width, cell_height):
        raise ValueError(
            "Atlas resolution is too small for the requested object count and margin"
        )
    return (
        column * cell_width + inset,
        row * cell_height + inset,
        (column + 1) * cell_width - inset,
        (row + 1) * cell_height - inset,
    )


def blender_relative_path(path: Path, blend_directory: Path) -> str:
    """Serialize one image path using Blender's relocatable double-slash notation."""

    relative = os.path.relpath(path.resolve(), blend_directory.resolve()).replace("\\", "/")
    return f"//{relative}"


def stable_object_key(record: dict[str, Any]) -> tuple[str, str, int, str]:
    """Sort derived render and LOD objects independently of Blender insertion order."""

    return (
        str(record.get("semantic_id") or record.get("cbm_id") or ""),
        str(record.get("source_object") or record.get("cbm_source_object") or ""),
        int(record.get("lod_level") or record.get("cbm_lod_level") or 0),
        str(record.get("name") or ""),
    )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Publish deterministic JSON without exposing a partially written evidence file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
