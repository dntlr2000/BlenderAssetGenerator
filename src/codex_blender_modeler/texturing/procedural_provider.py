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

from PIL import Image, ImageOps

from ..workspace import job_dir, sha256_file
from .models import TextureChannel, TextureManifest, TextureProvenance
from .providers import TextureGenerationRequest

PROCEDURAL_PBR_CHANNELS = frozenset(
    {"base_color", "roughness", "metallic", "normal", "height", "emission"}
)
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_PROVIDER_ID = "cbm_pillow_procedural"
_PROVIDER_VERSION = "1.0"

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
                top = grid[y0 * frequency + x0] * (1.0 - tx) + grid[
                    y0 * frequency + x1
                ] * tx
                bottom = grid[y1 * frequency + x0] * (1.0 - tx) + grid[
                    y1 * frequency + x1
                ] * tx
                value += (top * (1.0 - ty) + bottom * ty) * weight
            samples.append(value)

    minimum = min(samples)
    span = max(samples) - minimum
    pixels = bytes(
        round((value - minimum) / span * 255.0) if span > 1e-12 else 128
        for value in samples
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


def _render_channels(request: TextureGenerationRequest) -> dict[str, Image.Image]:
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
    rendered: dict[str, Image.Image] = {}
    for channel in request.channels:
        if channel == "base_color":
            rendered[channel] = ImageOps.colorize(
                noise, black=preset["base_low"], white=preset["base_high"]
            )
        elif channel == "roughness":
            rendered[channel] = _scalar_map(noise, preset["roughness"])
        elif channel == "metallic":
            rendered[channel] = _scalar_map(noise, preset["metallic"])
        elif channel == "normal":
            rendered[channel] = _normal_map(noise, float(preset["normal_strength"]))
        elif channel == "height":
            rendered[channel] = noise.copy()
        elif channel == "emission":
            rendered[channel] = _emission_map(noise, preset)
    return rendered


def _write_png(path: Path, image: Image.Image) -> None:
    """Atomically replace one deterministic PNG without embedded volatile metadata."""

    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    image.save(temporary, format="PNG", optimize=False, compress_level=9)
    os.replace(temporary, path)


def _write_manifest(path: Path, manifest: TextureManifest) -> None:
    """Write the manifest last so partial channel generation is never advertised."""

    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    temporary.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class PillowProceduralTextureProvider:
    """Generate reproducible offline PBR maps with only Pillow and seeded math."""

    provider_id = _PROVIDER_ID
    provider_version = _PROVIDER_VERSION

    def generate(self, request: TextureGenerationRequest, output_dir: Path) -> TextureManifest:
        """Generate requested maps and persist a hash-bearing TextureManifest."""

        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "texture_manifest.json"
        output_paths = {name: output_dir / f"{name}.png" for name in request.channels}
        conflicts = [path for path in [manifest_path, *output_paths.values()] if path.exists()]
        if conflicts and not request.overwrite:
            raise FileExistsError(
                "Texture outputs already exist and were not modified: "
                + ", ".join(str(path) for path in conflicts)
            )

        rendered = _render_channels(request)
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
        manifest = TextureManifest(
            material_id=request.material_id,
            uv_set=request.uv_set,
            intended_scale_m=request.intended_scale_m,
            resolution=request.resolution,
            source_type="image",
            channels=channels,
            procedural={
                "algorithm": "periodic_multioctave_value_noise",
                "algorithm_version": 1,
                "preset": request.preset,
                "seed": request.seed,
                "normal_strength": preset["normal_strength"],
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
            generation_notes="Offline deterministic provider; no network or external model used.",
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
        overwrite=overwrite,
    )
    output_dir = job_dir(job_id) / "textures" / _material_directory_name(material_id)
    provider = PillowProceduralTextureProvider()
    manifest = provider.generate(request, output_dir)
    channel_paths = {
        name: (output_dir / channel.path).resolve()
        for name, channel in manifest.channels.items()
        if channel.path is not None
    }
    hashes = dict(manifest.provenance.generated_sha256) if manifest.provenance else {}
    return ProceduralTextureResult(
        manifest=manifest,
        manifest_path=(output_dir / "texture_manifest.json").resolve(),
        channel_paths=channel_paths,
        channel_sha256=hashes,
    )
