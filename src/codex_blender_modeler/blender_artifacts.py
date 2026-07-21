from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_artifact_name(value: str) -> str:
    """Convert a stable semantic ID into a portable artifact directory name."""

    compact = _SAFE_NAME_RE.sub("_", value.strip()).strip("._")
    return compact or "unnamed"


def stable_rgb(value: str) -> tuple[float, float, float]:
    """Map an ID to a deterministic, non-black RGB color for machine-readable passes."""

    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return (
        0.18 + (digest[0] / 255.0) * 0.74,
        0.18 + (digest[1] / 255.0) * 0.74,
        0.18 + (digest[2] / 255.0) * 0.74,
    )


def linear_to_srgb(value: float) -> float:
    """Convert one linear channel to its standard sRGB display encoding."""

    bounded = max(0.0, min(1.0, value))
    if bounded <= 0.0031308:
        return 12.92 * bounded
    return 1.055 * (bounded ** (1.0 / 2.4)) - 0.055


def unique_color_map(values: list[str]) -> dict[str, tuple[float, float, float]]:
    """Assign deterministic collision-free linear colors to a set of semantic IDs."""

    result: dict[str, tuple[float, float, float]] = {}
    used: set[str] = set()
    for value in sorted(set(values)):
        attempt = 0
        while True:
            key = value if attempt == 0 else f"{value}#{attempt}"
            color = stable_rgb(key)
            display_color = tuple(linear_to_srgb(channel) for channel in color)
            encoded = rgb_hex(display_color)  # type: ignore[arg-type]
            if encoded not in used:
                result[value] = color
                used.add(encoded)
                break
            attempt += 1
    return result


def rgb_hex(color: tuple[float, float, float]) -> str:
    """Encode a normalized RGB triplet as a lowercase hexadecimal color."""

    values = [max(0, min(255, round(channel * 255))) for channel in color]
    return "#" + "".join(f"{value:02x}" for value in values)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one generated artifact."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_digest(value: Any) -> str:
    """Hash JSON-compatible content using canonical key ordering."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def artifact_path(path: Path, manifest_path: Path) -> str:
    """Prefer a manifest-relative path while retaining an absolute fallback."""

    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(manifest_path.parent.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON artifact atomically so interrupted Blender runs do not look complete."""

    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)
