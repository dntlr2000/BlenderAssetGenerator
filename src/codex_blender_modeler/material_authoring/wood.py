"""Deterministic directional Wood v2 image synthesis.

The legacy ``procedural_wood_v1`` generator remains in ``service.py`` so its output
bytes and historical meaning cannot drift.  This module implements the additive v2
strategy with explicit 2D fibre-axis semantics and a less periodic multi-scale field.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageFilter

from .models import ProceduralWoodInput, RawPBRChannel


def _to_byte(value: float) -> int:
    """Clamp one normalized scalar to an unsigned byte."""

    return round(max(0.0, min(1.0, value)) * 255.0)


def _wrap_delta(value: float) -> float:
    """Return the shortest signed distance on a unit-periodic axis."""

    return (value + 0.5) % 1.0 - 0.5


def _noise_grid(rng: random.Random, along_cells: int, across_cells: int) -> list[float]:
    """Create one deterministic periodic value-noise lattice."""

    return [rng.uniform(-1.0, 1.0) for _ in range(along_cells * across_cells)]


def _sample_noise(
    grid: list[float],
    along_cells: int,
    across_cells: int,
    along: float,
    across: float,
) -> float:
    """Smoothly sample one wrapping value-noise lattice."""

    gx, gy = along * along_cells, across * across_cells
    x0, y0 = math.floor(gx), math.floor(gy)
    tx, ty = gx - x0, gy - y0
    tx, ty = tx * tx * (3.0 - 2.0 * tx), ty * ty * (3.0 - 2.0 * ty)

    def value(x: int, y: int) -> float:
        """Read one lattice cell through periodic integer addressing."""

        return grid[(y % across_cells) * along_cells + (x % along_cells)]

    top = value(x0, y0) * (1.0 - tx) + value(x0 + 1, y0) * tx
    bottom = value(x0, y0 + 1) * (1.0 - tx) + value(x0 + 1, y0 + 1) * tx
    return top * (1.0 - ty) + bottom * ty


def _noise_fields(
    rng: random.Random,
    entries: tuple[tuple[int, int, float], ...],
) -> list[tuple[int, int, float, list[float]]]:
    """Freeze weighted anisotropic noise octaves from one deterministic seed."""

    return [
        (along, across, weight, _noise_grid(rng, along, across))
        for along, across, weight in entries
    ]


def _fractal_noise(
    fields: list[tuple[int, int, float, list[float]]],
    along: float,
    across: float,
) -> float:
    """Combine frozen periodic fields into one bounded multi-scale sample."""

    total = sum(weight for _nx, _ny, weight, _grid in fields)
    return sum(
        weight * _sample_noise(grid, nx, ny, along, across)
        for nx, ny, weight, grid in fields
    ) / total


def _ridge_wave(phase: float, sharpness: float) -> float:
    """Return one narrow periodic ridge while phase warping breaks visible repetition."""

    return (1.0 - abs(math.sin(math.tau * phase))) ** sharpness


def _normal_from_height(height: Image.Image, strength: float) -> Image.Image:
    """Create a seam-safe OpenGL +Y normal from a periodic height tile."""

    source = height.convert("L")
    width, height_px = source.size
    pixels = source.load()
    output = Image.new("RGB", source.size, (128, 128, 255))
    normals = output.load()
    gain = max(0.0, min(strength, 1.0)) * 4.0
    for y in range(height_px):
        for x in range(width):
            dx = (pixels[(x + 1) % width, y] - pixels[(x - 1) % width, y]) / 255.0
            dy = (pixels[x, (y + 1) % height_px] - pixels[x, (y - 1) % height_px]) / 255.0
            nx, ny, nz = -dx * gain, -dy * gain, 1.0
            inverse_length = 1.0 / math.sqrt(nx * nx + ny * ny + nz * nz)
            normals[x, y] = (
                _to_byte(nx * inverse_length * 0.5 + 0.5),
                _to_byte(ny * inverse_length * 0.5 + 0.5),
                _to_byte(nz * inverse_length * 0.5 + 0.5),
            )
    return output


def generate_directional_wood_v2(
    config: ProceduralWoodInput,
    *,
    size: int = 256,
    end_grain_mask: Image.Image | None = None,
) -> dict[RawPBRChannel, Image.Image]:
    """Generate irregular multi-scale Wood channels along the declared image axis."""

    if config.grain_axis not in {"x", "y"}:
        raise ValueError("procedural_wood_v2 requires a 2D x or y fibre axis")
    if size < 64 or size > 4096:
        raise ValueError("procedural_wood_v2 tile size must remain in [64, 4096]")
    rng = random.Random(config.deterministic_seed ^ config.knot_seed ^ 0x57564F32)
    warp_fields = _noise_fields(
        rng,
        ((1, 2, 0.52), (2, 4, 0.30), (4, 8, 0.18)),
    )
    tone_fields = _noise_fields(
        rng,
        ((1, 2, 0.42), (2, 4, 0.30), (4, 8, 0.18), (8, 16, 0.10)),
    )
    fibre_fields = _noise_fields(
        rng,
        ((1, 16, 0.31), (2, 29, 0.27), (4, 47, 0.21), (8, 71, 0.13), (16, 97, 0.08)),
    )
    knots = [
        (rng.random(), rng.random(), rng.uniform(0.035, 0.065), rng.uniform(0.06, 0.12))
        for _ in range(config.knot_count)
    ]
    early = tuple(_to_byte(value) for value in config.earlywood_color)
    late = tuple(_to_byte(value) for value in config.latewood_color)
    base = Image.new("RGB", (size, size))
    height = Image.new("L", (size, size))
    roughness = Image.new("L", (size, size))
    base_pixels = base.load()
    height_pixels = height.load()
    roughness_pixels = roughness.load()
    ring_cycles = max(
        2.0,
        min(48.0, config.intended_real_world_scale_m / config.growth_ring_scale_m),
    )
    fibre_cycles = max(
        8.0,
        min(96.0, config.intended_real_world_scale_m / config.grain_frequency_m * 3.0),
    )
    end_pixels = None
    if end_grain_mask is not None:
        end_pixels = end_grain_mask.convert("L").resize(
            (size, size), Image.Resampling.LANCZOS
        ).load()
    end_center = (0.5 + rng.uniform(-0.07, 0.07), 0.5 + rng.uniform(-0.07, 0.07))
    for y in range(size):
        for x in range(size):
            u, v = x / size, y / size
            along, across = (u, v) if config.grain_axis == "x" else (v, u)
            macro_tone = _fractal_noise(tone_fields, along, across)
            warp = _fractal_noise(warp_fields, along, across)
            knot_core = 0.0
            knot_ring = 0.0
            knot_bend = 0.0
            for knot_along, knot_across, radius_across, radius_along in knots:
                da = _wrap_delta(along - knot_along) / radius_along
                dc = _wrap_delta(across - knot_across) / radius_across
                distance = math.sqrt(da * da + dc * dc)
                if distance < 3.0:
                    envelope = math.exp(-(distance * distance) * 0.52)
                    knot_core = max(knot_core, envelope)
                    knot_ring += math.cos(math.tau * distance * 1.35) * envelope
                    knot_bend += (
                        math.tanh(dc * 1.8)
                        * envelope
                        * (0.022 + 0.026 * abs(math.sin(math.pi * da)))
                    )
            warped = across + warp * 0.09 + macro_tone * 0.025 + knot_bend
            tone = _fractal_noise(tone_fields, along, warped)
            fibre_noise = _fractal_noise(fibre_fields, along, warped)
            growth_phase = warped * ring_cycles + tone * 0.38 + knot_ring * 0.08
            fine_phase = (
                warped * fibre_cycles
                + fibre_noise * 0.62
                + tone * 0.31
                + warp * 0.19
            )
            secondary_phase = (
                warped * (fibre_cycles * 1.61803398875 + 1.0)
                - fibre_noise * 0.43
                + tone * 0.57
            )
            growth_ridge = _ridge_wave(growth_phase, 1.65)
            fine_ridge = _ridge_wave(fine_phase, 3.4)
            secondary_ridge = _ridge_wave(secondary_phase, 2.6)
            pore = max(
                0.0,
                0.55 * fine_ridge
                + 0.35 * secondary_ridge
                + 0.20 * fibre_noise
                - 0.48,
            )
            mixture = 0.34 + config.earlywood_latewood_contrast * (
                0.22 * (growth_ridge - 0.34)
                + 0.19 * (fine_ridge - 0.26)
                + 0.10 * (secondary_ridge - 0.31)
                + 0.14 * tone
                + 0.08 * macro_tone
                + 0.12 * pore
                - 0.29 * knot_core
                + 0.07 * knot_ring
            )
            relief = (
                0.5
                + 0.075 * (fine_ridge - 0.26)
                + 0.035 * (secondary_ridge - 0.31)
                + 0.026 * (growth_ridge - 0.34)
                + 0.025 * tone
                + 0.035 * pore
                - 0.085 * knot_core
                + 0.025 * knot_ring
            )
            if end_pixels is not None:
                end_mix = end_pixels[x, y] / 255.0
                radius = math.hypot(u - end_center[0], v - end_center[1])
                end_ring = _ridge_wave(
                    radius * ring_cycles * 1.6 + tone * 0.24,
                    1.8,
                )
                end_mixture = 0.34 + config.earlywood_latewood_contrast * (
                    0.22 * (end_ring - 0.34) + 0.12 * tone - 0.18 * knot_core
                )
                mixture = mixture * (1.0 - end_mix) + end_mixture * end_mix
                end_relief = 0.5 + 0.07 * (end_ring - 0.34) + 0.025 * tone
                relief = relief * (1.0 - end_mix) + end_relief * end_mix
            mixture = max(0.08, min(0.88, mixture))
            base_pixels[x, y] = tuple(
                round(early[channel] * (1.0 - mixture) + late[channel] * mixture)
                for channel in range(3)
            )
            height_pixels[x, y] = _to_byte(relief)
            rough = (
                config.roughness_base
                + config.roughness_variation * (
                    0.62 * tone
                    - 0.58 * (fine_ridge - 0.26)
                    - 0.28 * (secondary_ridge - 0.31)
                    + 0.72 * knot_core
                    + 0.35 * pore
                )
                - config.finish_coating_amount * 0.2
            )
            roughness_pixels[x, y] = _to_byte(rough)
    normal_strength = max(
        0.06,
        min(
            0.32,
            config.pore_bump_scale_m
            / min(config.grain_frequency_m, config.growth_ring_scale_m)
            * 64.0,
        ),
    )
    normal = _normal_from_height(height, normal_strength)
    blurred = height.filter(ImageFilter.GaussianBlur(radius=2.0))
    occlusion = blurred.point(
        lambda value: round(max(0, min(255, 238 - max(0, 128 - value) * 0.35)))
    )
    return {
        "base_color": base,
        "height": height,
        "normal": normal,
        "occlusion": occlusion,
        "roughness": roughness,
    }
