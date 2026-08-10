"""Contained and atomic filesystem helpers for autonomy evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..blender_artifacts import native_io_path, write_json_atomic
from ..production.validation import ensure_contained_production_path


def ensure_autonomy_path(
    root: Path,
    path: Path,
    *,
    must_exist: bool,
) -> Path:
    """Apply production-grade containment and no-link checks to autonomy paths."""

    return ensure_contained_production_path(root, path, must_exist=must_exist)


def write_immutable_json(root: Path, path: Path, payload: dict[str, Any]) -> None:
    """Atomically publish one JSON file exactly once under the owning job root."""

    destination = ensure_autonomy_path(root, path, must_exist=False)
    if os.path.exists(native_io_path(destination)):
        raise FileExistsError(destination)
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    ensure_autonomy_path(root, destination.parent, must_exist=True)
    ensure_autonomy_path(root, destination, must_exist=False)
    write_json_atomic(destination, payload)
    ensure_autonomy_path(root, destination, must_exist=True)


def write_mutable_projection(root: Path, path: Path, payload: dict[str, Any]) -> None:
    """Atomically refresh a derived projection that never serves as authority evidence."""

    destination = ensure_autonomy_path(root, path, must_exist=False)
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    ensure_autonomy_path(root, destination.parent, must_exist=True)
    ensure_autonomy_path(root, destination, must_exist=False)
    write_json_atomic(destination, payload)


def load_json(root: Path, path: Path) -> dict[str, Any]:
    """Load one contained UTF-8 JSON object without following linked paths."""

    source = ensure_autonomy_path(root, path, must_exist=True)
    if not os.path.isfile(native_io_path(source)):
        raise FileNotFoundError(source)
    with open(native_io_path(source), encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Autonomy JSON root must be an object")
    return payload
