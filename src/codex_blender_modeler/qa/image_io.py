"""Long-path-safe Pillow I/O for deeply nested immutable QA evidence."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

from PIL import Image
from PIL.Image import Image as PillowImage


def _native_path(path: Path) -> str:
    """Return an absolute OS path with the Windows extended-length prefix when needed."""

    resolved = os.path.abspath(os.fspath(path.expanduser()))
    if os.name != "nt" or resolved.startswith("\\\\?\\"):
        return resolved
    if resolved.startswith("\\\\"):
        return "\\\\?\\UNC\\" + resolved[2:]
    return "\\\\?\\" + resolved


def open_image(path: Path) -> Image.Image:
    """Open an image through a Windows-long-path-safe native filename."""

    return Image.open(_native_path(path))


def save_png_atomic(image: PillowImage, destination: Path) -> Path:
    """Atomically save deterministic PNG evidence without truncating long paths."""

    resolved = destination.expanduser().resolve()
    os.makedirs(_native_path(resolved.parent), exist_ok=True)
    temporary = resolved.parent / f".tmp-{os.getpid()}-{uuid4().hex[:8]}"
    try:
        with open(_native_path(temporary), "wb") as stream:
            image.save(stream, format="PNG", optimize=False)
        os.replace(_native_path(temporary), _native_path(resolved))
    finally:
        try:
            os.unlink(_native_path(temporary))
        except FileNotFoundError:
            pass
    return resolved


def copy_file_atomic(source: Path, destination: Path) -> Path:
    """Copy exact file bytes atomically while supporting extended Windows paths."""

    resolved_source = source.expanduser().resolve()
    resolved_destination = destination.expanduser().resolve()
    os.makedirs(_native_path(resolved_destination.parent), exist_ok=True)
    temporary = resolved_destination.parent / (
        f".tmp-{os.getpid()}-{uuid4().hex[:8]}"
    )
    try:
        with (
            open(_native_path(resolved_source), "rb") as source_stream,
            open(_native_path(temporary), "wb") as destination_stream,
        ):
            shutil.copyfileobj(source_stream, destination_stream)
        os.replace(_native_path(temporary), _native_path(resolved_destination))
    finally:
        try:
            os.unlink(_native_path(temporary))
        except FileNotFoundError:
            pass
    return resolved_destination
