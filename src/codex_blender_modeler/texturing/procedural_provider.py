from __future__ import annotations

import copy
import hashlib
import math
import os
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageOps

from ..workspace import job_dir, sha256_file
from .models import (
    SurfaceDetailBinding,
    TextureChannel,
    TextureManifest,
    TextureProvenance,
)
from .providers import TextureGenerationRequest

PROCEDURAL_PBR_CHANNELS = frozenset(
    {"base_color", "roughness", "metallic", "normal", "height", "emission"}
)
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_PROVIDER_ID = "cbm_pillow_procedural"
_PROVIDER_VERSION = "1.1"
_DEFAULT_DETAIL_TONE_FACTOR = 0.85
_DEFAULT_DETAIL_ROUGHNESS_VALUE = 180
_DEFAULT_DETAIL_RELIEF_MIX = 0.25

MATERIAL_FAMILY_PRESETS: dict[str, dict[str, Any]] = {
    "standard_pbr": {
        "base_low": (70, 75, 82),
        "base_high": (178, 184, 192),
        "roughness": (0.35, 0.72),
        "metallic": (0.0, 0.05),
        "normal_strength": 1.2,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "rock": {
        "base_low": (35, 31, 29),
        "base_high": (122, 112, 101),
        "roughness": (0.68, 0.96),
        "metallic": (0.0, 0.01),
        "normal_strength": 2.3,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "terrain": {
        "base_low": (42, 52, 26),
        "base_high": (132, 118, 66),
        "roughness": (0.58, 0.93),
        "metallic": (0.0, 0.0),
        "normal_strength": 1.8,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "water": {
        "base_low": (5, 33, 56),
        "base_high": (38, 132, 166),
        "roughness": (0.04, 0.2),
        "metallic": (0.0, 0.0),
        "normal_strength": 0.5,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "glass": {
        "base_low": (155, 184, 188),
        "base_high": (225, 241, 242),
        "roughness": (0.015, 0.11),
        "metallic": (0.0, 0.0),
        "normal_strength": 0.15,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "foliage": {
        "base_low": (18, 51, 13),
        "base_high": (99, 151, 45),
        "roughness": (0.48, 0.82),
        "metallic": (0.0, 0.0),
        "normal_strength": 1.0,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "lava": {
        "base_low": (35, 8, 2),
        "base_high": (245, 82, 4),
        "roughness": (0.28, 0.72),
        "metallic": (0.0, 0.02),
        "normal_strength": 1.7,
        "emission_low": (38, 2, 0),
        "emission_high": (255, 177, 18),
        "emission_threshold": 0.48,
    },
    "cloud": {
        "base_low": (159, 169, 181),
        "base_high": (249, 251, 255),
        "roughness": (0.72, 0.98),
        "metallic": (0.0, 0.0),
        "normal_strength": 0.35,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "emissive": {
        "base_low": (14, 24, 45),
        "base_high": (50, 112, 220),
        "roughness": (0.2, 0.5),
        "metallic": (0.0, 0.1),
        "normal_strength": 0.6,
        "emission_low": (1, 8, 24),
        "emission_high": (78, 190, 255),
        "emission_threshold": 0.35,
    },
    "standardgun_red_paint": {
        "base_low": (82, 6, 9),
        "base_high": (184, 34, 38),
        "roughness": (0.3, 0.48),
        "metallic": (0.03, 0.08),
        "normal_strength": 0.55,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "standardgun_dark_polymer": {
        "base_low": (11, 13, 16),
        "base_high": (43, 47, 51),
        "roughness": (0.55, 0.78),
        "metallic": (0.0, 0.01),
        "normal_strength": 0.8,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "standardgun_gunmetal": {
        "base_low": (42, 45, 49),
        "base_high": (124, 130, 136),
        "roughness": (0.24, 0.46),
        "metallic": (0.75, 0.92),
        "normal_strength": 0.7,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "standardgun_gold_accent": {
        "base_low": (92, 51, 7),
        "base_high": (216, 158, 47),
        "roughness": (0.2, 0.36),
        "metallic": (0.78, 0.95),
        "normal_strength": 0.4,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "crystalgun_ornate_gold": {
        "base_low": (86, 48, 9),
        "base_high": (222, 171, 64),
        "roughness": (0.2, 0.36),
        "metallic": (0.82, 0.96),
        "normal_strength": 0.2,
        "emission_low": (0, 8, 3),
        "emission_high": (62, 255, 148),
        "emission_threshold": 0.18,
        "detail_tone_factor": 0.58,
        "detail_roughness_value": 76,
        "detail_relief_mix": 0.0,
    },
    "crystalgun_dark_leather": {
        "base_low": (17, 7, 5),
        "base_high": (74, 35, 24),
        "roughness": (0.58, 0.78),
        "metallic": (0.0, 0.0),
        "normal_strength": 0.2,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 1.32,
        "detail_roughness_value": 116,
        "detail_relief_mix": 0.0,
    },
    "crystalgun_mint_crystal": {
        "base_low": (16, 93, 64),
        "base_high": (122, 255, 193),
        "roughness": (0.08, 0.2),
        "metallic": (0.0, 0.0),
        "normal_strength": 0.08,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.48,
        "detail_roughness_value": 54,
        "detail_relief_mix": 0.0,
    },
    "standardgun_bore_dark": {
        "base_low": (2, 3, 4),
        "base_high": (17, 19, 22),
        "roughness": (0.48, 0.72),
        "metallic": (0.1, 0.25),
        "normal_strength": 0.35,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
    },
    "standardgun_simple_red_paint": {
        "base_low": (116, 18, 24),
        "base_high": (144, 29, 34),
        "roughness": (0.42, 0.48),
        "metallic": (0.02, 0.03),
        "normal_strength": 0.08,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.88,
        "detail_roughness_value": 128,
        "detail_relief_mix": 0.2,
    },
    "standardgun_simple_dark_polymer": {
        "base_low": (20, 22, 24),
        "base_high": (31, 33, 35),
        "roughness": (0.65, 0.72),
        "metallic": (0.0, 0.0),
        "normal_strength": 0.08,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.9,
        "detail_roughness_value": 188,
        "detail_relief_mix": 0.2,
    },
    "standardgun_simple_gunmetal": {
        "base_low": (56, 60, 64),
        "base_high": (74, 78, 82),
        "roughness": (0.34, 0.4),
        "metallic": (0.82, 0.88),
        "normal_strength": 0.1,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.88,
        "detail_roughness_value": 108,
        "detail_relief_mix": 0.2,
    },
    "standardgun_simple_gold_accent": {
        "base_low": (158, 104, 28),
        "base_high": (184, 128, 39),
        "roughness": (0.3, 0.36),
        "metallic": (0.82, 0.9),
        "normal_strength": 0.06,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.92,
        "detail_roughness_value": 96,
        "detail_relief_mix": 0.15,
    },
    "standardgun_simple_bore_dark": {
        "base_low": (3, 4, 5),
        "base_high": (8, 9, 10),
        "roughness": (0.72, 0.78),
        "metallic": (0.05, 0.1),
        "normal_strength": 0.04,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.95,
        "detail_roughness_value": 196,
        "detail_relief_mix": 0.1,
    },
    "stylized_clean_red_paint": {
        "base_low": (116, 18, 24),
        "base_high": (144, 29, 34),
        "roughness": (0.42, 0.48),
        "metallic": (0.02, 0.03),
        "normal_strength": 0.08,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.9,
        "detail_roughness_value": 128,
        "detail_relief_mix": 0.2,
    },
    "stylized_clean_dark_polymer": {
        "base_low": (20, 22, 24),
        "base_high": (31, 33, 35),
        "roughness": (0.65, 0.72),
        "metallic": (0.0, 0.0),
        "normal_strength": 0.08,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.92,
        "detail_roughness_value": 188,
        "detail_relief_mix": 0.2,
    },
    "stylized_clean_gunmetal": {
        "base_low": (56, 60, 64),
        "base_high": (74, 78, 82),
        "roughness": (0.34, 0.4),
        "metallic": (0.82, 0.88),
        "normal_strength": 0.1,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.9,
        "detail_roughness_value": 108,
        "detail_relief_mix": 0.2,
    },
    "stylized_clean_gold_metal": {
        "base_low": (158, 104, 28),
        "base_high": (184, 128, 39),
        "roughness": (0.3, 0.36),
        "metallic": (0.82, 0.9),
        "normal_strength": 0.06,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.94,
        "detail_roughness_value": 96,
        "detail_relief_mix": 0.15,
    },
    "stylized_clean_dark_recess": {
        "base_low": (3, 4, 5),
        "base_high": (8, 9, 10),
        "roughness": (0.72, 0.78),
        "metallic": (0.05, 0.1),
        "normal_strength": 0.04,
        "emission_low": (0, 0, 0),
        "emission_high": (0, 0, 0),
        "emission_threshold": 1.0,
        "detail_tone_factor": 0.95,
        "detail_roughness_value": 196,
        "detail_relief_mix": 0.1,
    },
}

_DIRECT_SHADER_FAMILIES = {
    "standard_pbr",
    "rock",
    "terrain",
    "water",
    "glass",
    "foliage",
    "lava",
    "cloud",
    "emissive",
}


@dataclass(frozen=True)
class ProceduralTextureResult:
    """Return generated files and their validated portable manifest."""

    manifest: TextureManifest
    manifest_path: Path
    channel_paths: dict[str, Path]
    channel_sha256: dict[str, str]


def list_material_family_presets() -> dict[str, dict[str, Any]]:
    """Return isolated copies of deterministic material-family preset values."""

    return copy.deepcopy(MATERIAL_FAMILY_PRESETS)


def shader_family_for_preset(preset: str) -> str:
    """Map visual texture presets onto the supported portable shader-family contract."""

    return preset if preset in _DIRECT_SHADER_FAMILIES else "standard_pbr"


def _material_directory_name(material_id: str) -> str:
    """Create a deterministic traversal-safe folder name for a stable material ID."""

    if _SAFE_COMPONENT.fullmatch(material_id) and material_id not in {".", ".."}:
        return material_id
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", material_id).strip("._-") or "material"
    digest = hashlib.sha256(material_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:48]}-{digest}"


def _periodic_noise(resolution: tuple[int, int], seed: int) -> Image.Image:
    """Generate deterministic wrap-aware multi-octave value noise without NumPy."""

    width, height = resolution
    rng = random.Random(seed)
    octaves: list[tuple[int, float, list[float]]] = []
    for frequency, weight in ((2, 0.44), (4, 0.25), (8, 0.16), (16, 0.1), (32, 0.05)):
        values = [rng.random() for _ in range(frequency * frequency)]
        octaves.append((frequency, weight, values))

    samples: list[float] = []
    for y in range(height):
        for x in range(width):
            value = 0.0
            for frequency, weight, grid in octaves:
                gx = x * frequency / width
                gy = y * frequency / height
                x0 = int(gx) % frequency
                y0 = int(gy) % frequency
                x1 = (x0 + 1) % frequency
                y1 = (y0 + 1) % frequency
                tx = gx - int(gx)
                ty = gy - int(gy)
                top = grid[y0 * frequency + x0] * (1.0 - tx) + grid[y0 * frequency + x1] * tx
                bottom = grid[y1 * frequency + x0] * (1.0 - tx) + grid[y1 * frequency + x1] * tx
                value += (top * (1.0 - ty) + bottom * ty) * weight
            samples.append(value)

    minimum = min(samples)
    span = max(samples) - minimum
    pixels = bytes(
        round((value - minimum) / span * 255.0) if span > 1e-12 else 128 for value in samples
    )
    return Image.frombytes("L", resolution, pixels)


def _scalar_map(noise: Image.Image, value_range: tuple[float, float]) -> Image.Image:
    """Map normalized noise into one bounded scalar PBR channel."""

    low, high = value_range
    return noise.point(lambda value: round((low + (high - low) * value / 255.0) * 255.0))


def _normal_map(height_image: Image.Image, strength: float) -> Image.Image:
    """Convert periodic height samples into an OpenGL-style tangent normal map."""

    width, height = height_image.size
    source = height_image.tobytes()
    output = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            left = source[y * width + (x - 1) % width]
            right = source[y * width + (x + 1) % width]
            down = source[((y - 1) % height) * width + x]
            up = source[((y + 1) % height) * width + x]
            nx = -(right - left) / 255.0 * strength
            ny = -(up - down) / 255.0 * strength
            nz = 1.0
            inverse_length = 1.0 / math.sqrt(nx * nx + ny * ny + nz * nz)
            offset = (y * width + x) * 3
            output[offset] = round((nx * inverse_length * 0.5 + 0.5) * 255.0)
            output[offset + 1] = round((ny * inverse_length * 0.5 + 0.5) * 255.0)
            output[offset + 2] = round((nz * inverse_length * 0.5 + 0.5) * 255.0)
    return Image.frombytes("RGB", (width, height), bytes(output))


def _emission_map(noise: Image.Image, preset: dict[str, Any]) -> Image.Image:
    """Create a seeded emissive mask/color image from the preset threshold."""

    low = preset["emission_low"]
    high = preset["emission_high"]
    threshold = float(preset["emission_threshold"])
    span = max(1.0 - threshold, 1e-9)
    pixels: list[tuple[int, int, int]] = []
    for value in noise.getdata():
        factor = max(0.0, (float(value) / 255.0 - threshold) / span)
        pixels.append(
            tuple(round(low[index] + (high[index] - low[index]) * factor) for index in range(3))
        )
    image = Image.new("RGB", noise.size)
    image.putdata(pixels)
    return image


def _detail_relief(
    resolution: tuple[int, int], detail_pattern: str
) -> tuple[Image.Image, Image.Image]:
    """Render a bounded portable mark mask and neutral-centered relief field."""

    marks = Image.new("L", resolution, 0)
    relief = Image.new("L", resolution, 128)
    if detail_pattern == "none":
        return marks, relief

    width, height = resolution
    mark_draw = ImageDraw.Draw(marks)
    relief_draw = ImageDraw.Draw(relief)
    line_width = max(1, min(width, height) // 128)
    if detail_pattern == "panel_atlas":
        inset_x = max(2, width // 18)
        inset_y = max(2, height // 18)
        outer = (inset_x, inset_y, width - inset_x - 1, height - inset_y - 1)
        side_panel = (
            width // 5,
            height // 3,
            width * 4 // 5,
            height * 2 // 3,
        )
        for rectangle in (outer, side_panel):
            mark_draw.rectangle(rectangle, outline=255, width=line_width)
            relief_draw.rectangle(rectangle, outline=72, width=line_width)
        seam_y = height * 3 // 4
        mark_draw.line(
            (inset_x, seam_y, width - inset_x, seam_y),
            fill=220,
            width=line_width,
        )
        relief_draw.line(
            (inset_x, seam_y, width - inset_x, seam_y),
            fill=82,
            width=line_width,
        )
    elif detail_pattern == "horizontal_bands":
        for center in (height * 2 // 5, height // 2, height * 3 // 5):
            half = max(line_width, height // 64)
            box = (width // 8, center - half, width * 7 // 8, center + half)
            mark_draw.rectangle(box, fill=235)
            relief_draw.rectangle(box, fill=78)
    elif detail_pattern == "vertical_grooves":
        for center in (width * 2 // 5, width // 2, width * 3 // 5):
            half = max(line_width, width // 80)
            box = (center - half, height // 8, center + half, height * 7 // 8)
            mark_draw.rectangle(box, fill=235)
            relief_draw.rectangle(box, fill=74)
    elif detail_pattern == "ornate_filigree":
        margin_x = max(3, width // 14)
        margin_y = max(3, height // 10)
        center_y = height // 2
        flourish_box = (
            margin_x,
            margin_y,
            width - margin_x - 1,
            height - margin_y - 1,
        )
        mark_draw.arc(flourish_box, 198, 342, fill=255, width=line_width)
        mark_draw.arc(flourish_box, 18, 162, fill=255, width=line_width)
        relief_draw.arc(flourish_box, 198, 342, fill=82, width=line_width)
        relief_draw.arc(flourish_box, 18, 162, fill=82, width=line_width)
        for direction in (-1, 1):
            x0 = width // 2
            x1 = x0 + direction * width * 3 // 10
            x2 = x0 + direction * width * 2 // 5
            points = [
                (x0, center_y),
                (x1, center_y - height // 5),
                (x2, center_y),
                (x1, center_y + height // 5),
            ]
            mark_draw.line(points, fill=235, width=line_width, joint="curve")
            relief_draw.line(points, fill=88, width=line_width, joint="curve")
        hub_radius = max(2, min(width, height) // 28)
        hub = (
            width // 2 - hub_radius,
            center_y - hub_radius,
            width // 2 + hub_radius,
            center_y + hub_radius,
        )
        mark_draw.ellipse(hub, outline=255, width=line_width)
        relief_draw.ellipse(hub, outline=78, width=line_width)
    elif detail_pattern == "grip_filigree":
        inset_x = max(3, width // 7)
        inset_y = max(3, height // 12)
        centers = (height * 3 // 10, height // 2, height * 7 // 10)
        for center in centers:
            diamond = [
                (width // 2, center - height // 12),
                (width - inset_x, center),
                (width // 2, center + height // 12),
                (inset_x, center),
                (width // 2, center - height // 12),
            ]
            mark_draw.line(diamond, fill=238, width=line_width, joint="curve")
            relief_draw.line(diamond, fill=90, width=line_width, joint="curve")
        mark_draw.line(
            (width // 2, inset_y, width // 2, height - inset_y),
            fill=214,
            width=line_width,
        )
        relief_draw.line(
            (width // 2, inset_y, width // 2, height - inset_y),
            fill=96,
            width=line_width,
        )
    elif detail_pattern == "crystal_facet_lines":
        inset_x = max(3, width // 12)
        inset_y = max(3, height // 12)
        vertices = [
            (width // 2, inset_y),
            (width - inset_x, height // 3),
            (width * 4 // 5, height - inset_y),
            (width // 5, height - inset_y),
            (inset_x, height // 3),
        ]
        center = (width // 2, height // 2)
        polygon = [*vertices, vertices[0]]
        mark_draw.line(polygon, fill=246, width=line_width, joint="curve")
        relief_draw.line(polygon, fill=86, width=line_width, joint="curve")
        for vertex in vertices:
            mark_draw.line((*center, *vertex), fill=228, width=line_width)
            relief_draw.line((*center, *vertex), fill=94, width=line_width)
        mark_draw.line(
            (vertices[4][0], vertices[4][1], vertices[1][0], vertices[1][1]),
            fill=210,
            width=line_width,
        )
        relief_draw.line(
            (vertices[4][0], vertices[4][1], vertices[1][0], vertices[1][1]),
            fill=102,
            width=line_width,
        )
    else:
        raise ValueError(f"Unsupported detail_pattern: {detail_pattern!r}")
    return marks, relief


def _apply_mark_tone(image: Image.Image, marks: Image.Image, factor: float) -> Image.Image:
    """Darken marked texels while preserving the unmarked base field."""

    marked = image.point(lambda value: round(value * factor))
    return Image.composite(marked, image, marks)


def _validate_detail_generation_request(request: TextureGenerationRequest) -> None:
    """Reject unbound or ambiguous semantic-detail patterns before writing texture files."""

    has_pattern = request.detail_pattern != "none"
    if has_pattern and not request.surface_detail_ids:
        raise ValueError("A rendered detail_pattern requires one exact surface_detail_id")
    if not request.surface_detail_ids:
        return
    if request.uv_set != "UVMap":
        raise ValueError("Surface-detail texture generation requires UVMap coordinates")
    if len(request.surface_detail_ids) != 1:
        raise ValueError(
            "Generic procedural detail patterns may cover only one exact surface_detail_id; "
            "author separate placement-bound overlays for multiple details"
        )


def _uv_rect_pixels(
    uv_rect: tuple[float, float, float, float],
    resolution: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Convert a normalized bottom-left UV rectangle into a bounded Pillow paste box."""

    width, height = resolution
    u0, v0, u1, v1 = uv_rect
    x0 = max(0, min(width - 1, int(math.floor(u0 * width))))
    x1 = max(x0 + 1, min(width, int(math.ceil(u1 * width))))
    y0 = max(0, min(height - 1, int(math.floor((1.0 - v1) * height))))
    y1 = max(y0 + 1, min(height, int(math.ceil((1.0 - v0) * height))))
    return x0, y0, x1, y1


def _spatial_detail_relief(
    request: TextureGenerationRequest,
    output_dir: Path,
) -> tuple[Image.Image, Image.Image]:
    """Render one detail only inside its hash-bound UV rectangle or mask placement."""

    if not request.surface_detail_bindings:
        return _detail_relief(request.resolution, request.detail_pattern)
    binding = request.surface_detail_bindings[0]
    neutral = Image.new("L", request.resolution, 128)
    if binding.placement.mode == "uv_rect":
        box = _uv_rect_pixels(binding.placement.uv_rect, request.resolution)
        local_size = (box[2] - box[0], box[3] - box[1])
        local_marks, local_relief = _detail_relief(local_size, request.detail_pattern)
        local_marks = local_marks.point(lambda value: round(float(value) * binding.strength))
        local_neutral = Image.new("L", local_size, 128)
        local_relief = Image.blend(local_neutral, local_relief, binding.strength)
        marks = Image.new("L", request.resolution, 0)
        marks.paste(local_marks, box[:2])
        relief = neutral.copy()
        relief.paste(local_relief, box[:2])
        return marks, relief

    mask_path = (output_dir / str(binding.placement.mask_path)).resolve()
    try:
        mask_path.relative_to(output_dir.resolve())
    except ValueError as exc:
        raise ValueError(
            "Surface-detail mask must stay inside the texture output directory"
        ) from exc
    if not mask_path.is_file():
        raise FileNotFoundError(f"Surface-detail mask does not exist: {mask_path}")
    if sha256_file(mask_path) != binding.placement.mask_sha256:
        raise ValueError("Surface-detail mask SHA-256 differs from the binding")
    mask = Image.open(mask_path).convert("L")
    if mask.size != request.resolution:
        raise ValueError(
            "Surface-detail mask dimensions must match the generated texture resolution"
        )
    mask = mask.point(lambda value: round(float(value) * binding.strength))
    marks, relief = _detail_relief(request.resolution, request.detail_pattern)
    marks = ImageChops.multiply(marks, mask)
    relief = Image.composite(relief, neutral, mask)
    return marks, relief


def _render_channels(
    request: TextureGenerationRequest,
    output_dir: Path,
) -> dict[str, Image.Image]:
    """Render only requested PBR images from one shared deterministic noise field."""

    if request.preset not in MATERIAL_FAMILY_PRESETS:
        raise ValueError(
            f"Unknown material family preset {request.preset!r}; "
            f"expected one of {sorted(MATERIAL_FAMILY_PRESETS)}"
        )
    unsupported = sorted(set(request.channels) - PROCEDURAL_PBR_CHANNELS)
    if unsupported:
        raise ValueError(f"Unsupported procedural PBR channels: {unsupported}")
    preset = MATERIAL_FAMILY_PRESETS[request.preset]
    noise = _periodic_noise(request.resolution, request.seed)
    marks, relief = _spatial_detail_relief(request, output_dir)
    detail_channels = (
        set()
        if request.detail_pattern == "none"
        else set(request.surface_detail_bindings[0].channels)
        if request.surface_detail_bindings
        else set(request.channels)
    )
    empty_marks = Image.new("L", request.resolution, 0)
    detail_relief_mix = float(preset.get("detail_relief_mix", _DEFAULT_DETAIL_RELIEF_MIX))
    detail_tone_factor = float(preset.get("detail_tone_factor", _DEFAULT_DETAIL_TONE_FACTOR))
    detail_roughness_value = int(
        preset.get("detail_roughness_value", _DEFAULT_DETAIL_ROUGHNESS_VALUE)
    )
    rendered: dict[str, Image.Image] = {}
    for channel in request.channels:
        if channel == "base_color":
            base_color = ImageOps.colorize(
                noise, black=preset["base_low"], white=preset["base_high"]
            )
            rendered[channel] = _apply_mark_tone(
                base_color,
                marks if channel in detail_channels else empty_marks,
                detail_tone_factor,
            )
        elif channel == "roughness":
            roughness = _scalar_map(noise, preset["roughness"])
            marked_roughness = Image.new(
                "L",
                request.resolution,
                detail_roughness_value,
            )
            rendered[channel] = Image.composite(
                marked_roughness,
                roughness,
                marks if channel in detail_channels else empty_marks,
            )
        elif channel == "metallic":
            rendered[channel] = _scalar_map(noise, preset["metallic"])
        elif channel == "normal":
            normal_height = (
                ImageChops.blend(noise, relief, detail_relief_mix)
                if channel in detail_channels
                else noise
            )
            rendered[channel] = _normal_map(normal_height, float(preset["normal_strength"]))
        elif channel == "height":
            rendered[channel] = (
                ImageChops.blend(noise, relief, detail_relief_mix)
                if channel in detail_channels
                else noise.copy()
            )
        elif channel == "emission":
            emission = _emission_map(noise, preset)
            rendered[channel] = (
                Image.composite(
                    emission,
                    Image.new("RGB", request.resolution, (0, 0, 0)),
                    marks,
                )
                if request.surface_detail_bindings and channel in detail_channels
                else emission
            )
    return rendered


def _write_png(path: Path, image: Image.Image) -> None:
    """Atomically replace one deterministic PNG without embedded volatile metadata."""

    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    image.save(temporary, format="PNG", optimize=False, compress_level=9)
    os.replace(temporary, path)


def _write_manifest(path: Path, manifest: TextureManifest) -> None:
    """Write the manifest last so partial channel generation is never advertised."""

    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    temporary.write_text(
        manifest.model_dump_json(indent=2, exclude_none=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class PillowProceduralTextureProvider:
    """Generate reproducible offline PBR maps with only Pillow and seeded math."""

    provider_id = _PROVIDER_ID
    provider_version = _PROVIDER_VERSION

    def generate(self, request: TextureGenerationRequest, output_dir: Path) -> TextureManifest:
        """Generate requested maps and persist a hash-bearing TextureManifest."""

        _validate_detail_generation_request(request)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "texture_manifest.json"
        output_paths = {name: output_dir / f"{name}.png" for name in request.channels}
        conflicts = [path for path in [manifest_path, *output_paths.values()] if path.exists()]
        if conflicts and not request.overwrite:
            raise FileExistsError(
                "Texture outputs already exist and were not modified: "
                + ", ".join(str(path) for path in conflicts)
            )

        rendered = _render_channels(request, output_dir)
        for channel, image in rendered.items():
            _write_png(output_paths[channel], image)
        hashes = {name: sha256_file(path) for name, path in output_paths.items()}
        channels = {
            name: TextureChannel(
                source="image",
                path=output_paths[name].name,
                color_space="sRGB" if name in {"base_color", "emission"} else "Non-Color",
            )
            for name in request.channels
        }
        preset = MATERIAL_FAMILY_PRESETS[request.preset]
        detail_tone_factor = float(preset.get("detail_tone_factor", _DEFAULT_DETAIL_TONE_FACTOR))
        detail_roughness_value = int(
            preset.get("detail_roughness_value", _DEFAULT_DETAIL_ROUGHNESS_VALUE)
        )
        detail_relief_mix = float(preset.get("detail_relief_mix", _DEFAULT_DETAIL_RELIEF_MIX))
        manifest = TextureManifest(
            material_id=request.material_id,
            uv_set=request.uv_set,
            intended_scale_m=request.intended_scale_m,
            resolution=request.resolution,
            source_type="image",
            channels=channels,
            surface_detail_ids=request.surface_detail_ids,
            surface_detail_bindings=request.surface_detail_bindings,
            procedural={
                "algorithm": "periodic_multioctave_value_noise",
                "algorithm_version": 1,
                "preset": request.preset,
                "seed": request.seed,
                "normal_strength": preset["normal_strength"],
                "detail_pattern": request.detail_pattern,
                "detail_tone_factor": detail_tone_factor,
                "detail_roughness_value": detail_roughness_value,
                "detail_relief_mix": detail_relief_mix,
                "detail_placement_scope": (
                    "spatial_v1"
                    if request.surface_detail_bindings
                    else "legacy_unbound"
                    if request.surface_detail_ids
                    else "none"
                ),
            },
            provenance=TextureProvenance(
                provider=self.provider_id,
                provider_version=self.provider_version,
                model="pillow_periodic_pbr_v1",
                prompt=request.prompt or f"{request.preset} deterministic PBR material",
                seed=request.seed,
                generated_sha256=hashes,
                license="Generated locally; rights follow the user's project policy.",
            ),
            color_space_rules={
                "color": ["base_color", "emission"],
                "data": ["roughness", "metallic", "normal", "height"],
            },
            generation_notes=(
                "Offline deterministic PNG provider; declared surface details are rendered "
                f"with the bounded {request.detail_pattern} pattern. Spatial-v1 requests "
                "apply the declared UV rectangle or exact mask during raster generation; "
                "legacy unbound requests remain audit-only. No external model used."
            ),
        )
        _write_manifest(manifest_path, manifest)
        return manifest


def generate_procedural_pbr(
    job_id: str,
    material_id: str,
    *,
    preset: str = "standard_pbr",
    channels: Sequence[str] = (
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "emission",
    ),
    resolution: tuple[int, int] = (512, 512),
    seed: int = 0,
    intended_scale_m: float = 1.0,
    prompt: str = "",
    uv_set: str = "Object",
    surface_detail_ids: Sequence[str] = (),
    surface_detail_bindings: Sequence[SurfaceDetailBinding | dict[str, Any]] = (),
    detail_pattern: str = "none",
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> ProceduralTextureResult:
    """Generate a job-owned deterministic PBR set and return auditable paths/hashes."""

    request = TextureGenerationRequest(
        material_id=material_id,
        prompt=prompt,
        preset=preset,
        resolution=resolution,
        channels=list(channels),
        seed=seed,
        intended_scale_m=intended_scale_m,
        uv_set=uv_set,
        surface_detail_ids=list(surface_detail_ids),
        surface_detail_bindings=list(surface_detail_bindings),
        detail_pattern=detail_pattern,
        overwrite=overwrite,
    )
    root = job_dir(job_id).resolve()
    resolved_output_dir = (
        (root / "textures" / _material_directory_name(material_id)).resolve()
        if output_dir is None
        else output_dir.expanduser().resolve()
    )
    try:
        resolved_output_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("Procedural texture output_dir must stay inside job root") from exc
    provider = PillowProceduralTextureProvider()
    manifest = provider.generate(request, resolved_output_dir)
    channel_paths = {
        name: (resolved_output_dir / channel.path).resolve()
        for name, channel in manifest.channels.items()
        if channel.path is not None
    }
    hashes = dict(manifest.provenance.generated_sha256) if manifest.provenance else {}
    return ProceduralTextureResult(
        manifest=manifest,
        manifest_path=(resolved_output_dir / "texture_manifest.json").resolve(),
        channel_paths=channel_paths,
        channel_sha256=hashes,
    )
