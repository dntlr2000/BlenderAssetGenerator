from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PIL import Image

from .image_io import open_image, save_png_atomic


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Convert a manifest RGB hex string to an integer color tuple."""

    normalized = value.strip().lower()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if len(normalized) != 6:
        raise ValueError(f"expected #rrggbb color, got {value!r}")
    try:
        return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise ValueError(f"invalid RGB color: {value!r}") from exc


def _bbox_from_pixels(
    pixels: list[tuple[int, int, int]],
    width: int,
    height: int,
    color: tuple[int, int, int],
) -> tuple[float, float, float, float] | None:
    """Find a normalized exact-color bounding box in one flat semantic-ID pass."""

    matches = [index for index, pixel in enumerate(pixels) if pixel == color]
    if not matches:
        return None
    xs = [index % width for index in matches]
    ys = [index // width for index in matches]
    return (
        min(xs) / width,
        min(ys) / height,
        (max(xs) + 1) / width,
        (max(ys) + 1) / height,
    )


def extract_semantic_bboxes(
    object_id_path: Path,
    color_mapping: Mapping[str, str],
) -> dict[str, tuple[float, float, float, float] | None]:
    """Project stable semantic IDs to normalized image-space bounding boxes."""

    with open_image(object_id_path) as opened:
        rgb = opened.convert("RGB")
        width, height = rgb.size
        pixels = list(rgb.getdata())
    return {
        semantic_id: _bbox_from_pixels(
            pixels,
            width,
            height,
            parse_hex_color(color),
        )
        for semantic_id, color in sorted(color_mapping.items())
    }


def semantic_mask_image(object_id_path: Path, color: str) -> Image.Image:
    """Return an owned binary mask for one exact semantic color in an object-ID pass."""

    expected = parse_hex_color(color)
    with open_image(object_id_path.expanduser().resolve()) as opened:
        rgb = opened.convert("RGB")
        mask = Image.new("L", rgb.size, 0)
        mask.putdata([255 if pixel == expected else 0 for pixel in rgb.getdata()])
    return mask


def extract_semantic_mask(
    object_id_path: Path,
    color: str,
    output_path: Path,
) -> Path:
    """Extract one exact-color mask atomically without overwriting source evidence."""

    source = object_id_path.expanduser().resolve()
    destination = output_path.expanduser().resolve()
    if source == destination:
        raise ValueError("semantic mask output must not overwrite the object-ID pass")
    mask = semantic_mask_image(source, color)
    return save_png_atomic(mask, destination)
