from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..models import SceneSpec


def _camera_payload(value: SceneSpec | Mapping[str, Any] | Path) -> dict[str, Any]:
    """Normalize a SceneSpec source to the camera fields relevant to image-space QA."""

    if isinstance(value, Path):
        raw = json.loads(value.read_text(encoding="utf-8"))
        spec = SceneSpec.model_validate(raw)
        return spec.camera.model_dump(mode="json")
    if isinstance(value, SceneSpec):
        return value.camera.model_dump(mode="json")
    camera = value.get("camera", value)
    if not isinstance(camera, Mapping):
        raise TypeError("camera fingerprint input must contain an object-valued camera")
    required = {
        "projection",
        "location",
        "target",
        "focal_length_mm",
        "ortho_scale",
        "resolution",
    }
    missing = sorted(required - set(camera))
    if missing:
        raise ValueError(f"camera fingerprint input is missing fields: {missing}")
    return {key: camera[key] for key in sorted(required)}


def camera_fingerprint(value: SceneSpec | Mapping[str, Any] | Path) -> str:
    """Hash the fixed comparison camera using canonical JSON serialization."""

    encoded = json.dumps(
        _camera_payload(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_camera_fingerprint(
    value: SceneSpec | Mapping[str, Any] | Path,
    expected: str,
) -> str:
    """Reject QA or revisions created for a different comparison camera."""

    actual = camera_fingerprint(value)
    if actual != expected:
        raise ValueError(f"comparison camera changed: {expected} != {actual}")
    return actual
