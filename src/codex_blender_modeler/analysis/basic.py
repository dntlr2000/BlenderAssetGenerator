from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps

from ..workspace import metadata_path, sha256_file
from .models import DominantColor, ImageAnalysis

_MAX_ANALYSIS_SIZE = 384


def _normalized_bbox(mask: Image.Image) -> tuple[float, float, float, float]:
    bbox = mask.getbbox()
    if bbox is None:
        return (0.0, 0.0, 1.0, 1.0)
    left, top, right, bottom = bbox
    width, height = mask.size
    x0 = max(0.0, min(1.0, left / width))
    y0 = max(0.0, min(1.0, top / height))
    x1 = max(0.0, min(1.0, right / width))
    y1 = max(0.0, min(1.0, bottom / height))
    if x1 <= x0 or y1 <= y0:
        return (0.0, 0.0, 1.0, 1.0)
    return (round(x0, 6), round(y0, 6), round(x1, 6), round(y1, 6))


def _content_mask(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 255:
        return alpha.point(lambda value: 255 if value > 8 else 0)

    sample = rgba.convert("RGB")
    sample.thumbnail((_MAX_ANALYSIS_SIZE, _MAX_ANALYSIS_SIZE), Image.Resampling.LANCZOS)
    width, height = sample.size
    corners = [
        sample.getpixel((0, 0)),
        sample.getpixel((width - 1, 0)),
        sample.getpixel((0, height - 1)),
        sample.getpixel((width - 1, height - 1)),
    ]
    background = tuple(round(sum(color[channel] for color in corners) / 4) for channel in range(3))
    threshold = 36.0
    mask = Image.new("L", sample.size)
    values = []
    for pixel in sample.getdata():
        distance = math.sqrt(sum((pixel[i] - background[i]) ** 2 for i in range(3)))
        values.append(255 if distance >= threshold else 0)
    mask.putdata(values)
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
    return mask


def _edge_metrics(image: Image.Image, diagnostic_path: Path) -> float:
    gray = ImageOps.grayscale(image)
    gray.thumbnail((_MAX_ANALYSIS_SIZE, _MAX_ANALYSIS_SIZE), Image.Resampling.LANCZOS)
    edges = gray.filter(ImageFilter.FIND_EDGES)
    pixels = list(edges.getdata())
    if not pixels:
        density = 0.0
    else:
        threshold = max(24, sum(pixels) / len(pixels) * 1.35)
        density = sum(value >= threshold for value in pixels) / len(pixels)
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    ImageOps.autocontrast(edges).save(diagnostic_path)
    return round(float(density), 6)


def _symmetry_score(image: Image.Image) -> float:
    gray = ImageOps.grayscale(image).resize((128, 128), Image.Resampling.LANCZOS)
    mirrored = ImageOps.mirror(gray)
    diff = ImageChops.difference(gray, mirrored)
    histogram = diff.histogram()
    mean_difference = sum(index * count for index, count in enumerate(histogram)) / (128 * 128)
    return round(max(0.0, min(1.0, 1.0 - mean_difference / 255.0)), 6)


def _dominant_colors(image: Image.Image, count: int = 6) -> list[DominantColor]:
    rgb = image.convert("RGB")
    rgb.thumbnail((256, 256), Image.Resampling.LANCZOS)
    quantized = rgb.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    total = max(1, rgb.width * rgb.height)
    result: list[DominantColor] = []
    for pixel_count, color_index in sorted(quantized.getcolors(total) or [], reverse=True):
        base = color_index * 3
        if base + 2 >= len(palette):
            continue
        result.append(
            DominantColor(
                rgb=(palette[base], palette[base + 1], palette[base + 2]),
                fraction=round(pixel_count / total, 6),
            )
        )
    return result


def analyze_image(source_id: str, image_path: Path, diagnostics_dir: Path) -> ImageAnalysis:
    path = image_path.expanduser().resolve()
    with Image.open(path) as opened:
        image = opened.copy()
        width, height = image.size
        has_alpha = "A" in image.getbands()
        mask = _content_mask(image)
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.Resampling.NEAREST)
        mask_path = diagnostics_dir.parent / "masks" / f"{source_id}_content.png"
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        mask.save(mask_path)
        edge_path = diagnostics_dir / f"{source_id}_edges.png"
        edge_density = _edge_metrics(image, edge_path)
        return ImageAnalysis(
            source_id=source_id,
            path=metadata_path(path),
            sha256=sha256_file(path),
            width=width,
            height=height,
            aspect_ratio=round(width / height, 6),
            color_mode=image.mode,
            has_alpha=has_alpha,
            content_bbox_norm=_normalized_bbox(mask),
            edge_density=edge_density,
            bilateral_symmetry_score=_symmetry_score(image),
            dominant_colors=_dominant_colors(image),
            diagnostics={
                "edge_map": metadata_path(edge_path),
                "content_mask": metadata_path(mask_path),
            },
        )
