"""Deterministic local MaterialAuthoring 0.1.0 host service."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
from pydantic import BaseModel

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest, write_json_atomic
from ..production.validation import ensure_contained_production_path
from ..structural_geometry.models import AssetScaleContext
from .models import (
    SUPPORTED_RESOLUTION_TIERS,
    AuthoredChannel,
    AuthoredMaterialManifest,
    ColorSpace,
    ExactArtifact,
    HighResolutionAuthorization,
    ImageEvidence,
    MasterMaterialIntent,
    MaterialAuthoringReceipt,
    MaterialAuthoringRequest,
    PreviewEvidenceState,
    RawPBRChannel,
    ResolutionSelection,
    ResolutionSelectorInput,
    UVIdentity,
    UVIdentitySnapshot,
)


def _utc_now() -> datetime:
    """Return one timezone-aware timestamp for immutable material evidence."""

    return datetime.now(UTC)


def _path_is_file(path: Path) -> bool:
    """Check one regular file through its native extended-length representation."""

    return os.path.isfile(native_io_path(path))


def _artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> ExactArtifact:
    """Bind one contained non-empty regular file to exact immutable bytes."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    if not _path_is_file(safe):
        raise ValueError(f"material artifact must be a regular file: {safe.name}")
    size = os.path.getsize(native_io_path(safe))
    if size <= 0:
        raise ValueError(f"material artifact must be non-empty: {safe.name}")
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=size,
        media_type=media_type,
    )


def _validate_artifact(root: Path, artifact: ExactArtifact) -> Path:
    """Reject missing, linked, resized, or rehashed source evidence."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if not _path_is_file(path):
        raise ValueError(f"material source must be a regular file: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"material source byte size changed: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"material source hash changed: {artifact.path}")
    return path


def _load_exact_model(root: Path, artifact: ExactArtifact, model: type[BaseModel]) -> BaseModel:
    """Rehash and strict-parse one exact job-contained JSON model."""

    path = _validate_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model.model_validate_json(handle.read())


def _write_model(path: Path, model: BaseModel) -> None:
    """Write one deterministic UTF-8 JSON model to an unpublished staging path."""

    write_json_atomic(path, model.model_dump(mode="json"))


def _budget_resolution_cap(
    package_budget_bytes: int,
    material_family: str,
) -> int:
    """Estimate a family-aware raw-RGBA tier cap from one package texture budget."""

    bytes_per_pixel = 4
    channel_count = {
        "uniform_fallback": 4,
        "user_image_pbr": 8,
        "signage_decal": 5,
        "planar_reference_patch": 2,
        "wood": 5,
        "metal": 4,
        "emissive": 3,
        "crystal": 5,
    }[material_family]
    minimum_bytes = 256 * 256 * channel_count * bytes_per_pixel
    if package_budget_bytes < minimum_bytes:
        raise ValueError("package texture budget cannot hold the minimum 256 tier")
    estimated_side = math.sqrt(package_budget_bytes / max(channel_count * bytes_per_pixel, 1))
    tiers = (*SUPPORTED_RESOLUTION_TIERS, 8192)
    eligible = [tier for tier in tiers if tier <= estimated_side]
    return max(eligible, default=256)


def select_texture_resolution(
    selector: ResolutionSelectorInput,
    *,
    scale_context_recommendation: int,
    authorization: HighResolutionAuthorization | None = None,
) -> ResolutionSelection:
    """Select a scale-aware 256..4096 tier, permitting 8192 only by exact authorization."""

    family_factor = {
        "uniform_fallback": 0.5,
        "user_image_pbr": 1.0,
        "signage_decal": 1.25,
        "planar_reference_patch": 1.25,
        "wood": 1.0,
        "metal": 1.0,
        "emissive": 1.0,
        "crystal": 0.75,
    }[selector.material_family]
    mapping_factor = {
        "fallback": 0.5,
        "tileable": 0.75,
        "unique": 1.0,
        "decal": 1.25,
    }[selector.mapping_kind]
    scale_target = max(
        selector.projected_pixel_footprint,
        selector.longest_object_dimension_m * selector.target_texel_density_px_m,
        float(scale_context_recommendation),
    ) * max(family_factor, mapping_factor)
    tiers = (*SUPPORTED_RESOLUTION_TIERS, 8192)
    desired = selector.requested_pixels or next(
        (tier for tier in tiers if tier >= scale_target),
        8192,
    )
    budget_cap = _budget_resolution_cap(
        selector.package_budget_bytes,
        selector.material_family,
    )
    selected = min(desired, budget_cap)
    reasons = [
        f"scale_target={scale_target:.6f}",
        f"requested={selector.requested_pixels or 'auto'}",
        f"budget_cap={budget_cap}",
        f"material_family={selector.material_family};factor={family_factor}",
        f"mapping_kind={selector.mapping_kind};factor={mapping_factor}",
    ]
    authorized = False
    if selected > 4096 or desired > 4096:
        if authorization is None:
            raise PermissionError("texture resolutions above 4096 require separate authorization")
        if authorization.selector_input_sha256 != selector.exact_sha256():
            raise ValueError("high-resolution authorization is stale or bound to another selector")
        if authorization.authorized_pixels != 8192:
            raise ValueError("high-resolution authorization does not cover the selected tier")
        selected = min(desired, budget_cap, authorization.authorized_pixels)
        authorized = selected > 4096
        reasons.append(f"authorization={authorization.authorization_id}")
    if selected > 4096 and not authorized:
        raise PermissionError("selected resolution exceeds the normal 4096 cap")
    return ResolutionSelection(
        selector_input_sha256=selector.exact_sha256(),
        selected_pixels=selected,  # type: ignore[arg-type]
        unclamped_target_pixels=scale_target,
        scale_context_recommendation=scale_context_recommendation,
        budget_limited=selected < desired,
        high_resolution_authorized=authorized,
        reasons=reasons,
    )


def _validate_image_evidence(root: Path, evidence: ImageEvidence) -> Path:
    """Rehash an image and verify its exact recorded pixel dimensions."""

    path = _validate_artifact(root, evidence.artifact)
    with Image.open(native_io_path(path)) as opened:
        if opened.size != (evidence.width, evidence.height):
            raise ValueError(f"image dimensions changed: {evidence.artifact.path}")
        opened.verify()
    return path


def _validate_uv_identity(root: Path, identity: UVIdentity) -> None:
    """Rehash and compare one trusted UV snapshot before authoring any channel."""

    loaded = _load_exact_model(root, identity.evidence, UVIdentitySnapshot)
    if not isinstance(loaded, UVIdentitySnapshot):
        raise TypeError("UV identity loader returned an unexpected contract")
    expected = identity.model_dump(mode="python", exclude={"evidence"})
    if loaded.model_dump(mode="python") != expected:
        raise ValueError("UV identity evidence is stale or contradicts the requested binding")


def _request_uv_identities(request: MaterialAuthoringRequest) -> list[UVIdentity]:
    """Collect every strategy-specific UV identity for exact preflight validation."""

    if request.uniform_fallback is not None:
        return [item.uv_identity for item in request.uniform_fallback.existing_channels]
    if request.user_image_pbr is not None:
        return [item.uv_identity for item in request.user_image_pbr.channels]
    if request.localized_decal is not None:
        return [request.localized_decal.uv_identity]
    if request.planar_reference_patch is not None:
        return [request.planar_reference_patch.uv_identity]
    if request.procedural_wood is not None:
        return [request.procedural_wood.uv_identity]
    if request.procedural_metal is not None:
        return [request.procedural_metal.uv_identity]
    if request.emissive_pattern is not None:
        return [request.emissive_pattern.uv_identity]
    if request.crystal is not None:
        return [request.crystal.uv_identity]
    return []


def _validate_strategy_scale(
    request: MaterialAuthoringRequest,
    scale: AssetScaleContext,
) -> None:
    """Bind family-specific physical authoring parameters to the exact scale context."""

    configurations = (
        request.procedural_wood,
        request.procedural_metal,
        request.emissive_pattern,
        request.crystal,
    )
    configured = next((item for item in configurations if item is not None), None)
    if configured is None:
        return
    longest = max(scale.assembly_bbox.dimensions())
    if not math.isclose(
        configured.intended_real_world_scale_m,
        longest,
        rel_tol=0,
        abs_tol=1.0e-9,
    ):
        raise ValueError("material intended scale differs from the exact AssetScaleContext")


def _validate_scale_context(root: Path, request: MaterialAuthoringRequest) -> AssetScaleContext:
    """Rehash AssetScaleContext 0.1.0 and compare every cached selector value."""

    loaded = _load_exact_model(root, request.scale_context.artifact, AssetScaleContext)
    if not isinstance(loaded, AssetScaleContext):
        raise TypeError("scale context loader returned an unexpected contract")
    binding = request.scale_context
    if loaded.asset_id != binding.asset_id:
        raise ValueError("scale context asset identity changed")
    if loaded.source_fingerprint != binding.source_fingerprint:
        raise ValueError("scale context source fingerprint changed")
    longest = max(loaded.assembly_bbox.dimensions())
    comparisons = (
        (loaded.shortest_dimension_m, binding.shortest_dimension_m, "shortest dimension"),
        (longest, binding.longest_dimension_m, "longest dimension"),
        (
            loaded.target_texel_density_px_m,
            binding.target_texel_density_px_m,
            "texel density",
        ),
    )
    for actual, expected, label in comparisons:
        if not math.isclose(actual, expected, rel_tol=0, abs_tol=1.0e-9):
            raise ValueError(f"scale context {label} binding is stale")
    if not math.isclose(
        request.resolution.longest_object_dimension_m,
        longest,
        rel_tol=0,
        abs_tol=1.0e-9,
    ):
        raise ValueError("resolution selector does not use the exact scale context bounds")
    if not math.isclose(
        request.resolution.target_texel_density_px_m,
        loaded.target_texel_density_px_m,
        rel_tol=0,
        abs_tol=1.0e-9,
    ):
        raise ValueError("resolution selector does not use the exact scale context texel density")
    return loaded


def _load_high_resolution_authorization(
    root: Path,
    request: MaterialAuthoringRequest,
) -> HighResolutionAuthorization | None:
    """Load a separate exact authorization only when the request names one."""

    if request.high_resolution_authorization is None:
        return None
    loaded = _load_exact_model(
        root,
        request.high_resolution_authorization,
        HighResolutionAuthorization,
    )
    if not isinstance(loaded, HighResolutionAuthorization):
        raise TypeError("high-resolution loader returned an unexpected contract")
    return loaded


def _save_png(image: Image.Image, path: Path) -> None:
    """Write deterministic PNG bytes without metadata or adaptive optimization."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    image.save(native_io_path(path), format="PNG", compress_level=9, optimize=False)


def _to_byte(value: float) -> int:
    """Clamp one normalized scalar to an unsigned byte."""

    return int(round(max(0.0, min(1.0, value)) * 255.0))


def _rgb_bytes(color: tuple[float, float, float]) -> tuple[int, int, int]:
    """Convert one normalized RGB tuple to exact bytes."""

    return tuple(_to_byte(value) for value in color)  # type: ignore[return-value]


def _rgba_bytes(color: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Convert one normalized RGBA tuple to exact bytes."""

    return tuple(_to_byte(value) for value in color)  # type: ignore[return-value]


def _channel_artifact(
    root: Path,
    stage_root: Path,
    final_root: Path,
    filename: str,
    *,
    channel: RawPBRChannel,
    uv_identity: UVIdentity,
    source_hashes: list[str],
) -> AuthoredChannel:
    """Bind one staged PNG using the portable path it will have after publication."""

    staged = stage_root / "textures" / filename
    with Image.open(native_io_path(staged)) as opened:
        width, height = opened.size
    final = final_root / "textures" / filename
    staged_artifact = _artifact(
        root,
        staged,
        artifact_id=f"{channel}-{hashlib.sha256(filename.encode()).hexdigest()[:12]}",
        kind=f"raw-pbr-{channel}",
        media_type="image/png",
    )
    final_artifact = staged_artifact.model_copy(update={"path": final.relative_to(root).as_posix()})
    color_space: ColorSpace = "srgb" if channel in {"base_color", "emission"} else "non_color"
    return AuthoredChannel(
        channel=channel,
        artifact=final_artifact,
        width=width,
        height=height,
        color_space=color_space,
        uv_identity=uv_identity,
        source_artifact_sha256=source_hashes,
        normal_convention="opengl_y_plus" if channel == "normal" else None,
    )


def _copy_user_channels(
    root: Path,
    stage_root: Path,
    final_root: Path,
    channels: list[ImageEvidence],
    *,
    resolution: int | None,
) -> list[AuthoredChannel]:
    """Copy legacy bytes or deterministically normalize user images to one tier."""

    outputs: list[AuthoredChannel] = []
    for item in channels:
        source = _validate_image_evidence(root, item)
        preserve_exact = resolution is None
        extension = source.suffix.casefold() or ".png"
        filename = f"{item.channel}{extension}" if preserve_exact else f"{item.channel}.png"
        target = stage_root / "textures" / filename
        os.makedirs(native_io_path(target.parent), exist_ok=True)
        if preserve_exact:
            shutil.copyfile(native_io_path(source), native_io_path(target))
            output_width, output_height = item.width, item.height
            media_type = item.artifact.media_type
        else:
            with Image.open(native_io_path(source)) as opened:
                if item.channel in {"base_color", "emission"}:
                    mode = "RGBA" if "A" in opened.getbands() else "RGB"
                else:
                    mode = "RGB" if item.channel == "normal" else "L"
                normalized = opened.convert(mode)
                if item.channel == "normal" and item.normal_convention == "directx_y_minus":
                    red, green, blue = normalized.convert("RGB").split()
                    normalized = Image.merge("RGB", (red, ImageOps.invert(green), blue))
                normalized = normalized.resize(
                    (resolution, resolution),
                    resample=(
                        Image.Resampling.BILINEAR
                        if item.channel == "normal"
                        else Image.Resampling.LANCZOS
                    ),
                )
                _save_png(normalized, target)
            output_width = output_height = resolution
            media_type = "image/png"
        staged = _artifact(
            root,
            target,
            artifact_id=f"{item.channel}-{item.artifact.sha256[:12]}",
            kind=f"raw-pbr-{item.channel}",
            media_type=media_type,
        )
        final = staged.model_copy(
            update={"path": (final_root / "textures" / filename).relative_to(root).as_posix()}
        )
        outputs.append(
            AuthoredChannel(
                channel=item.channel,
                artifact=final,
                width=output_width,
                height=output_height,
                color_space=item.color_space,
                uv_identity=item.uv_identity,
                source_artifact_sha256=[
                    item.artifact.sha256,
                    item.uv_identity.evidence.sha256,
                ],
                normal_convention=("opengl_y_plus" if item.channel == "normal" else None),
            )
        )
    return outputs


def _resized_tile(image: Image.Image, resolution: int) -> Image.Image:
    """Scale one bounded deterministic authoring tile to the requested output tier."""

    if image.size == (resolution, resolution):
        return image
    return image.resize((resolution, resolution), resample=Image.Resampling.BICUBIC)


def _height_to_normal(height: Image.Image, strength: float) -> Image.Image:
    """Derive one bounded OpenGL +Y tangent-space normal from a grayscale height tile."""

    source = height.convert("L")
    width, height_px = source.size
    pixels = source.load()
    result = Image.new("RGB", source.size, (128, 128, 255))
    output = result.load()
    gain = max(0.0, min(strength, 1.0)) * 4.0
    for y in range(height_px):
        y0 = max(0, y - 1)
        y1 = min(height_px - 1, y + 1)
        for x in range(width):
            x0 = max(0, x - 1)
            x1 = min(width - 1, x + 1)
            dx = (pixels[x1, y] - pixels[x0, y]) / 255.0
            dy = (pixels[x, y1] - pixels[x, y0]) / 255.0
            nx, ny, nz = -dx * gain, -dy * gain, 1.0
            length = math.sqrt(nx * nx + ny * ny + nz * nz)
            output[x, y] = (
                _to_byte(nx / length * 0.5 + 0.5),
                _to_byte(ny / length * 0.5 + 0.5),
                _to_byte(nz / length * 0.5 + 0.5),
            )
    return result


def _write_image_channels(
    root: Path,
    stage_root: Path,
    final_root: Path,
    images: dict[RawPBRChannel, Image.Image],
    *,
    resolution: int,
    uv_identity: UVIdentity,
    source_hashes: list[str],
) -> list[AuthoredChannel]:
    """Publish a deterministic set of channel images and return exact final receipts."""

    outputs: list[AuthoredChannel] = []
    for channel in sorted(images):
        filename = f"{channel}.png"
        _save_png(_resized_tile(images[channel], resolution), stage_root / "textures" / filename)
        outputs.append(
            _channel_artifact(
                root,
                stage_root,
                final_root,
                filename,
                channel=channel,
                uv_identity=uv_identity,
                source_hashes=[*source_hashes, uv_identity.evidence.sha256],
            )
        )
    return outputs


def _draw_bitmap_text(
    canvas: Image.Image,
    font_path: Path,
    text: str,
    *,
    origin: tuple[int, int],
    bounds: tuple[int, int],
    color: tuple[int, int, int, int],
) -> None:
    """Rasterize exact text from a strict project-local bitmap-font JSON artifact."""

    with open(native_io_path(font_path), encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("schema_version") != "0.1.0":
        raise ValueError("project bitmap font must use schema_version 0.1.0")
    width = payload.get("glyph_width")
    height = payload.get("glyph_height")
    spacing = payload.get("spacing", 1)
    glyphs = payload.get("glyphs")
    if not isinstance(width, int) or not 1 <= width <= 64:
        raise ValueError("project bitmap font glyph_width is invalid")
    if not isinstance(height, int) or not 1 <= height <= 64:
        raise ValueError("project bitmap font glyph_height is invalid")
    if not isinstance(spacing, int) or not 0 <= spacing <= 16:
        raise ValueError("project bitmap font spacing is invalid")
    if not isinstance(glyphs, dict):
        raise ValueError("project bitmap font glyphs must be an object")
    parsed: dict[str, list[str]] = {}
    for character in set(text) - {" "}:
        rows = glyphs.get(character)
        if not isinstance(rows, list) or len(rows) != height:
            raise ValueError(f"project bitmap font is missing exact glyph: {character!r}")
        if any(
            not isinstance(row, str) or len(row) != width or any(pixel not in "01" for pixel in row)
            for row in rows
        ):
            raise ValueError(f"project bitmap font glyph is malformed: {character!r}")
        parsed[character] = rows
    logical_width = len(text) * width + max(0, len(text) - 1) * spacing
    scale = min(bounds[0] // max(logical_width, 1), bounds[1] // height)
    if scale < 1:
        raise ValueError("project bitmap text does not fit the localized decal rectangle")
    rendered_width = logical_width * scale
    rendered_height = height * scale
    offset_x = origin[0] + (bounds[0] - rendered_width) // 2
    offset_y = origin[1] + (bounds[1] - rendered_height) // 2
    draw = ImageDraw.Draw(canvas)
    for character_index, character in enumerate(text):
        if character == " ":
            continue
        rows = parsed[character]
        glyph_x = offset_x + character_index * (width + spacing) * scale
        for row_index, row in enumerate(rows):
            for column_index, pixel in enumerate(row):
                if pixel != "1":
                    continue
                left = glyph_x + column_index * scale
                top = offset_y + row_index * scale
                draw.rectangle(
                    (left, top, left + scale - 1, top + scale - 1),
                    fill=color,
                )


def _mip_bleed_base_color(image: Image.Image, padding: int) -> Image.Image:
    """Dilate RGB only beneath transparent pixels while preserving the exact alpha edge."""

    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    red, green, blue = rgba.convert("RGB").split()
    expanded = tuple(
        channel.filter(ImageFilter.GaussianBlur(radius=float(padding)))
        for channel in (red, green, blue)
    )
    red = Image.composite(red, expanded[0], alpha)
    green = Image.composite(green, expanded[1], alpha)
    blue = Image.composite(blue, expanded[2], alpha)
    return Image.merge("RGBA", (red, green, blue, alpha))


def _decal_channels(
    root: Path,
    request: MaterialAuthoringRequest,
    resolution: int,
) -> tuple[dict[RawPBRChannel, Image.Image], UVIdentity, list[str], list[str]]:
    """Rasterize an exact image or exact user text without inventing unknown glyphs."""

    config = request.localized_decal
    if config is None:
        raise ValueError("localized decal configuration is missing")
    if config.source_kind == "text" and config.text_evidence != "exact_user_text":
        return (
            {},
            config.uv_identity,
            [],
            [f"text evidence is {config.text_evidence}; no glyphs were invented or rasterized"],
        )
    padding = min(config.mip_padding_px, max(2, resolution // 4))
    canvas = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 0))
    left = int(round(config.uv_rect.minimum[0] * resolution))
    right = int(round(config.uv_rect.maximum[0] * resolution))
    top = int(round((1.0 - config.uv_rect.maximum[1]) * resolution))
    bottom = int(round((1.0 - config.uv_rect.minimum[1]) * resolution))
    inner_width = max(1, right - left - 2 * padding)
    inner_height = max(1, bottom - top - 2 * padding)
    if right - left <= 2 * padding or bottom - top <= 2 * padding:
        raise ValueError("localized decal UV rectangle is too small for its mip padding")
    inner_origin = (left + padding, top + padding)
    source_hashes: list[str] = []
    if config.source_kind == "user_image":
        if config.image is None:
            raise ValueError("localized image evidence is missing")
        source = _validate_image_evidence(root, config.image)
        source_hashes.append(config.image.artifact.sha256)
        with Image.open(native_io_path(source)) as opened:
            decal = opened.convert("RGBA")
            decal.thumbnail((inner_width, inner_height))
            offset = (
                inner_origin[0] + (inner_width - decal.width) // 2,
                inner_origin[1] + (inner_height - decal.height) // 2,
            )
            canvas.alpha_composite(decal, dest=offset)
    else:
        if config.font is None or config.text is None:
            raise ValueError("exact localized text requires a font and text")
        font_path = _validate_artifact(root, config.font.artifact)
        source_hashes.append(config.font.artifact.sha256)
        if config.font.font_format == "bitmap_json_v1":
            _draw_bitmap_text(
                canvas,
                font_path,
                config.text,
                origin=inner_origin,
                bounds=(inner_width, inner_height),
                color=_rgba_bytes(config.base_color),
            )
        else:
            font_size = max(8, inner_height * 4 // 5)
            font = ImageFont.truetype(
                native_io_path(font_path),
                font_size,
                index=config.font.face_index,
            )
            draw = ImageDraw.Draw(canvas)
            bounds = draw.textbbox((0, 0), config.text, font=font)
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            position = (
                inner_origin[0] + (inner_width - width) // 2 - bounds[0],
                inner_origin[1] + (inner_height - height) // 2 - bounds[1],
            )
            draw.text(position, config.text, font=font, fill=_rgba_bytes(config.base_color))
    alpha = canvas.getchannel("A")
    base = _mip_bleed_base_color(canvas, padding)
    roughness = Image.new("L", canvas.size, _to_byte(config.roughness))
    normal = Image.new("RGB", canvas.size, (128, 128, 255))
    emission = Image.new("RGB", canvas.size, (0, 0, 0))
    if config.emission_strength > 0:
        emission = Image.composite(
            Image.new("RGB", canvas.size, _rgb_bytes(config.emission_color)),
            emission,
            alpha,
        )
    limitations: list[str] = []
    if config.source_kind == "user_image" and config.image is not None:
        if config.image.rights_status == "unknown":
            limitations.append("localized image rights status is unknown")
    elif config.font is not None and config.font.rights_status == "unknown":
        limitations.append("localized font rights status is unknown")
    return (
        {
            "base_color": base,
            "roughness": roughness,
            "normal": normal,
            "opacity": alpha,
            "emission": emission,
        },
        config.uv_identity,
        source_hashes,
        limitations,
    )


def _solve_linear_system(matrix: list[list[float]], values: list[float]) -> list[float]:
    """Solve one small deterministic square system with pivoted Gaussian elimination."""

    size = len(values)
    if len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValueError("perspective linear system must be square")
    augmented = [list(row) + [values[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1.0e-12:
            raise ValueError("planar patch corners produce a singular homography")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def _perspective_coefficients(
    corners: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ],
    output_size: int,
) -> tuple[float, float, float, float, float, float, float, float]:
    """Derive Pillow output-to-source homography coefficients from ordered corners."""

    maximum = float(max(output_size - 1, 1))
    output_points = ((0.0, 0.0), (maximum, 0.0), (maximum, maximum), (0.0, maximum))
    matrix: list[list[float]] = []
    values: list[float] = []
    for (x, y), (source_x, source_y) in zip(output_points, corners, strict=True):
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -source_x * x, -source_x * y])
        values.append(source_x)
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -source_y * x, -source_y * y])
        values.append(source_y)
    solved = _solve_linear_system(matrix, values)
    return tuple(solved)  # type: ignore[return-value]


def _planar_patch_channels(
    root: Path,
    request: MaterialAuthoringRequest,
    resolution: int,
) -> tuple[dict[RawPBRChannel, Image.Image], UVIdentity, list[str], list[str]]:
    """Rectify only caller-supplied corners and preserve exact source provenance."""

    config = request.planar_reference_patch
    if config is None:
        raise ValueError("planar patch configuration is missing")
    source_path = _validate_image_evidence(root, config.reference_image)
    with Image.open(native_io_path(source_path)) as opened:
        source = opened.convert("RGBA")
    corners = config.corners_px
    crop_left = crop_top = 0
    if config.crop_px is not None:
        crop_left, crop_top, crop_right, crop_bottom = config.crop_px
        source = source.crop((crop_left, crop_top, crop_right, crop_bottom))
        corners = tuple((x - crop_left, y - crop_top) for x, y in corners)  # type: ignore[assignment]
    padding = min(config.mip_padding_px, max(2, resolution // 4))
    inner_size = max(1, resolution - 2 * padding)
    coefficients = _perspective_coefficients(corners, inner_size)
    patch = source.transform(
        (inner_size, inner_size),
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
    )
    if config.cleanup == "alpha_trim":
        bounds = patch.getchannel("A").getbbox()
        if bounds is not None:
            patch = patch.crop(bounds).resize(
                (inner_size, inner_size),
                resample=Image.Resampling.BICUBIC,
            )
    source_hashes = [config.reference_image.artifact.sha256]
    if config.mask is not None:
        mask_path = _validate_artifact(root, config.mask)
        source_hashes.append(config.mask.sha256)
        with Image.open(native_io_path(mask_path)) as opened:
            if opened.size != (
                config.reference_image.width,
                config.reference_image.height,
            ):
                raise ValueError("planar patch mask dimensions differ from the reference image")
            mask_source = opened.convert("L")
        if config.crop_px is not None:
            mask_source = mask_source.crop(config.crop_px)
        rectified_mask = mask_source.transform(
            (inner_size, inner_size),
            Image.Transform.PERSPECTIVE,
            coefficients,
            resample=Image.Resampling.BILINEAR,
        )
        patch.putalpha(ImageChops.multiply(patch.getchannel("A"), rectified_mask))
    padded = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 0))
    padded.alpha_composite(patch, dest=(padding, padding))
    patch = _mip_bleed_base_color(padded, padding)
    opacity = patch.getchannel("A")
    limitations: list[str] = []
    if config.reference_image.rights_status == "unknown":
        limitations.append("planar reference image rights status is unknown")
    if config.corner_source == "advisory_candidate":
        limitations.append("rectification corners are advisory and require user confirmation")
    if config.evidence_status == "inferred":
        limitations.append("planar patch location is inferred rather than observed truth")
    return (
        {"base_color": patch, "opacity": opacity},
        config.uv_identity,
        source_hashes,
        limitations,
    )


def _wood_channels(
    root: Path,
    request: MaterialAuthoringRequest,
) -> tuple[dict[RawPBRChannel, Image.Image], UVIdentity, list[str], list[str]]:
    """Generate non-uniform deterministic wood maps using physical scale parameters."""

    config = request.procedural_wood
    if config is None:
        raise ValueError("wood configuration is missing")
    size = 256
    rng = random.Random(config.deterministic_seed ^ config.knot_seed)
    early = _rgb_bytes(config.earlywood_color)
    late = _rgb_bytes(config.latewood_color)
    base = Image.new("RGB", (size, size))
    height = Image.new("L", (size, size))
    rough = Image.new("L", (size, size))
    base_pixels, height_pixels, rough_pixels = base.load(), height.load(), rough.load()
    physical_cycles = max(
        1.0,
        config.intended_real_world_scale_m / config.growth_ring_scale_m,
    )
    grain_cycles = max(1.0, config.intended_real_world_scale_m / config.grain_frequency_m)
    source_hashes = [request.scale_context.artifact.sha256]
    end_grain: Image.Image | None = None
    if config.end_grain_mask is not None:
        mask_path = _validate_artifact(root, config.end_grain_mask)
        source_hashes.append(config.end_grain_mask.sha256)
        with Image.open(native_io_path(mask_path)) as opened:
            end_grain = opened.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    end_grain_pixels = end_grain.load() if end_grain is not None else None
    knots = [
        (rng.randrange(size), rng.randrange(size), rng.uniform(4.0, 18.0))
        for _ in range(config.knot_count)
    ]
    for y in range(size):
        for x in range(size):
            axis_coordinate = x if config.grain_axis == "x" else y
            orthogonal = y if config.grain_axis == "x" else x
            phase = axis_coordinate / size * grain_cycles * math.tau
            phase += math.sin(orthogonal / size * physical_cycles * math.tau) * 0.35
            if end_grain_pixels is not None:
                end_mix = end_grain_pixels[x, y] / 255.0
                radial = math.hypot(x - size / 2, y - size / 2) / size
                phase = phase * (1 - end_mix) + radial * physical_cycles * math.tau * end_mix
            for knot_x, knot_y, radius in knots:
                distance = math.hypot(x - knot_x, y - knot_y)
                if distance < radius * 3:
                    phase += math.exp(-distance / radius) * math.tau
            ring = 0.5 + 0.5 * math.sin(phase)
            mix = max(0.0, min(1.0, ring * config.earlywood_latewood_contrast))
            base_pixels[x, y] = tuple(
                int(round(early[index] * (1 - mix) + late[index] * mix)) for index in range(3)
            )
            height_pixels[x, y] = _to_byte(0.35 + ring * 0.3)
            rough_value = (
                config.roughness_base
                + (ring - 0.5) * config.roughness_variation
                - config.finish_coating_amount * 0.2
            )
            rough_pixels[x, y] = _to_byte(rough_value)
    normal = _height_to_normal(height, min(1.0, config.pore_bump_scale_m * 1000.0))
    occlusion = ImageOps.invert(height.filter(ImageFilter.GaussianBlur(radius=2)))
    return (
        {
            "base_color": base,
            "roughness": rough,
            "normal": normal,
            "height": height,
            "occlusion": occlusion,
        },
        config.uv_identity,
        source_hashes,
        [
            "procedural Blender master shader compilation and neutral preview are not run",
            "grain-axis agreement with the Blender object basis is not yet verified",
        ],
    )


def _metal_channels(
    root: Path,
    request: MaterialAuthoringRequest,
) -> tuple[dict[RawPBRChannel, Image.Image], UVIdentity, list[str], list[str]]:
    """Generate deterministic metallic maps with bounded brushed variation and no scratches."""

    config = request.procedural_metal
    if config is None:
        raise ValueError("metal configuration is missing")
    size = 256
    base = Image.new("RGB", (size, size), _rgb_bytes(config.base_color))
    metallic = Image.new("L", (size, size), 255)
    roughness = Image.new("L", (size, size))
    height = Image.new("L", (size, size))
    rough_pixels, height_pixels = roughness.load(), height.load()
    cycles = max(1.0, config.intended_real_world_scale_m / config.brush_scale_m)
    for y in range(size):
        for x in range(size):
            if config.brushed_direction == "x":
                coordinate = y
            elif config.brushed_direction == "y":
                coordinate = x
            elif config.brushed_direction == "radial":
                coordinate = int(math.hypot(x - size / 2, y - size / 2))
            else:
                coordinate = 0
            variation = math.sin(coordinate / size * cycles * math.tau) * 0.5
            rough_pixels[x, y] = _to_byte(
                config.roughness_base + variation * config.roughness_variation
            )
            height_pixels[x, y] = _to_byte(0.5 + variation * config.subtle_normal_strength)
    source_hashes = [request.scale_context.artifact.sha256]
    if config.edge_wear_mask is not None:
        mask_path = _validate_artifact(root, config.edge_wear_mask)
        source_hashes.append(config.edge_wear_mask.sha256)
        with Image.open(native_io_path(mask_path)) as opened:
            wear = opened.convert("L").resize((size, size), Image.Resampling.LANCZOS)
        roughness = Image.composite(
            Image.new("L", (size, size), 220),
            roughness,
            wear,
        )
    normal = _height_to_normal(height, config.subtle_normal_strength)
    limitations = [
        "edge wear is omitted unless an exact supplied mask is available",
        "brushed direction agreement with the Blender object basis is not yet verified",
    ]
    return (
        {
            "base_color": base,
            "roughness": roughness,
            "metallic": metallic,
            "normal": normal,
        },
        config.uv_identity,
        source_hashes,
        limitations,
    )


def _emissive_channels(
    request: MaterialAuthoringRequest,
) -> tuple[dict[RawPBRChannel, Image.Image], UVIdentity, list[str], list[str]]:
    """Generate deterministic scale-aware emission, color, and opacity maps."""

    config = request.emissive_pattern
    if config is None:
        raise ValueError("emissive configuration is missing")
    size = 256
    base = Image.new("RGB", (size, size), _rgb_bytes(config.base_color))
    emission = Image.new("RGB", (size, size), (0, 0, 0))
    opacity = Image.new("L", (size, size), _to_byte(config.opacity))
    draw = ImageDraw.Draw(emission)
    active = _rgb_bytes(config.emission_color)
    physical_cells = max(1, int(config.intended_real_world_scale_m / config.pattern_scale_m))
    cell = max(1, size // min(physical_cells, size))
    active_width = max(1, int(cell * config.duty_cycle))
    if config.pattern == "solid":
        draw.rectangle((0, 0, size, size), fill=active)
    elif config.pattern == "stripes":
        for x in range(0, size, cell):
            draw.rectangle((x, 0, min(size, x + active_width), size), fill=active)
    elif config.pattern == "grid":
        for coordinate in range(0, size, cell):
            draw.rectangle((coordinate, 0, min(size, coordinate + active_width), size), fill=active)
            draw.rectangle((0, coordinate, size, min(size, coordinate + active_width)), fill=active)
    else:
        for y in range(0, size, cell):
            for x in range(0, size, cell):
                inset = max(0, (cell - active_width) // 2)
                draw.rectangle(
                    (x + inset, y + inset, x + cell - inset, y + cell - inset),
                    fill=active,
                )
    return (
        {"base_color": base, "emission": emission, "opacity": opacity},
        config.uv_identity,
        [request.scale_context.artifact.sha256],
        ["destination emission strength must be reconstructed explicitly"],
    )


def _crystal_channels(
    request: MaterialAuthoringRequest,
) -> tuple[dict[RawPBRChannel, Image.Image], UVIdentity, list[str], list[str]]:
    """Generate a declared lossy portable crystal approximation without parity claims."""

    config = request.crystal
    if config is None:
        raise ValueError("crystal configuration is missing")
    size = 256
    tint = _rgb_bytes(config.absorption_tint)
    base = Image.new("RGB", (size, size), tint)
    roughness = Image.new("L", (size, size), _to_byte(config.roughness))
    normal = Image.new("RGB", (size, size), (128, 128, 255))
    emission = Image.new("RGB", (size, size), _rgb_bytes(config.emission_color))
    opacity = Image.new("L", (size, size), _to_byte(config.opacity_approximation))
    losses = [
        "portable maps do not preserve Blender transmission or volumetric absorption",
        "IOR, Fresnel, and thickness require destination shader reconstruction",
        "GLB/FBX runtime parity is unverified",
    ]
    return (
        {
            "base_color": base,
            "roughness": roughness,
            "normal": normal,
            "emission": emission,
            "opacity": opacity,
        },
        config.uv_identity,
        [request.scale_context.artifact.sha256],
        losses,
    )


def _author_strategy(
    root: Path,
    request: MaterialAuthoringRequest,
    stage_root: Path,
    final_root: Path,
    resolution: int,
) -> tuple[list[AuthoredChannel], list[str]]:
    """Dispatch one strictly modeled strategy to deterministic local authoring."""

    if request.strategy == "uniform_portable_fallback_v1":
        if request.uniform_fallback is None:
            raise ValueError("uniform fallback evidence is missing")
        return _copy_user_channels(
            root,
            stage_root,
            final_root,
            request.uniform_fallback.existing_channels,
            resolution=None,
        ), ["existing portable_pbr_v05 bytes were adopted unchanged"]
    if request.strategy == "user_image_pbr_v1":
        if request.user_image_pbr is None:
            raise ValueError("user image PBR evidence is missing")
        outputs = _copy_user_channels(
            root,
            stage_root,
            final_root,
            request.user_image_pbr.channels,
            resolution=resolution,
        )
        limitations = [
            f"rights status is unknown for {item.source_id}"
            for item in request.user_image_pbr.channels
            if item.rights_status == "unknown"
        ]
        limitations.extend(
            f"{item.channel} was deterministically resampled from "
            f"{item.width}x{item.height} to {resolution}x{resolution}"
            for item in request.user_image_pbr.channels
            if (item.width, item.height) != (resolution, resolution)
        )
        if any(
            item.channel == "normal" and item.normal_convention == "directx_y_minus"
            for item in request.user_image_pbr.channels
        ):
            limitations.append("DirectX -Y normal input was converted to portable OpenGL +Y")
        return outputs, limitations
    if request.strategy == "localized_decal_v1":
        images, uv, hashes, limitations = _decal_channels(root, request, resolution)
    elif request.strategy == "planar_reference_patch_v1":
        images, uv, hashes, limitations = _planar_patch_channels(root, request, resolution)
    elif request.strategy == "procedural_wood_v1":
        images, uv, hashes, limitations = _wood_channels(root, request)
    elif request.strategy == "procedural_metal_v1":
        images, uv, hashes, limitations = _metal_channels(root, request)
    elif request.strategy == "emissive_pattern_v1":
        images, uv, hashes, limitations = _emissive_channels(request)
    elif request.strategy == "crystal_portable_approximation_v1":
        images, uv, hashes, limitations = _crystal_channels(request)
    else:  # pragma: no cover - strict Literal validation makes this unreachable
        raise ValueError(f"unsupported material strategy: {request.strategy}")
    return (
        _write_image_channels(
            root,
            stage_root,
            final_root,
            images,
            resolution=resolution,
            uv_identity=uv,
            source_hashes=hashes,
        ),
        limitations,
    )


def _master_intent(
    request: MaterialAuthoringRequest, limitations: list[str]
) -> MasterMaterialIntent:
    """Describe family-specific Blender intent and honest portable feature loss."""

    features: dict[str, list[str]] = {
        "uniform_fallback": ["Principled BSDF", "uniform portable PBR"],
        "user_image_pbr": ["Principled BSDF", "raw image PBR channels"],
        "signage_decal": ["localized color/roughness/normal/emission", "alpha edge"],
        "planar_reference_patch": ["rectified planar source patch", "alpha placement"],
        "wood": ["physical grain", "growth rings", "pores", "finish coating"],
        "metal": ["metallic workflow", "bounded brushed roughness", "subtle normal"],
        "emissive": ["emission", "deterministic spatial pattern"],
        "crystal": ["IOR", "transmission", "Fresnel", "absorption", "emission"],
    }
    family = request.material_family()
    approximation = "Raw portable PBR channels only; destination shader reconstruction is advisory."
    return MasterMaterialIntent(
        shader_family=family,
        features=features[family],
        blender_compilation_status="not_run",
        portable_approximation=approximation,
        known_losses=limitations,
    )


def _source_output_digest(
    request: MaterialAuthoringRequest,
    channels: list[AuthoredChannel],
) -> str:
    """Hash exact source bindings and channel outputs into immutable provenance."""

    return stable_json_digest(
        {
            "strategy": request.strategy,
            "source_v05_contracts": [item.sha256 for item in request.source_v05_contracts],
            "scale_context": request.scale_context.artifact.sha256,
            "channels": [item.model_dump(mode="json") for item in channels],
        }
    )


def _validate_publication_artifacts(
    root: Path,
    manifest: AuthoredMaterialManifest,
) -> None:
    """Rehash every final output binding after atomic run publication."""

    for item in (channel.artifact for channel in manifest.channels):
        _validate_artifact(root, item)


def author_material_candidate(
    job_root: Path,
    request: MaterialAuthoringRequest,
) -> MaterialAuthoringReceipt:
    """Create one immutable run-owned local material bundle without canonical writes."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    for artifact in request.source_v05_contracts:
        _validate_artifact(root, artifact)
    if request.preview_policy.reference_artifact is not None:
        _validate_artifact(root, request.preview_policy.reference_artifact)
    scale = _validate_scale_context(root, request)
    _validate_strategy_scale(request, scale)
    for identity in _request_uv_identities(request):
        _validate_uv_identity(root, identity)
        if not math.isclose(
            identity.texel_density_px_m,
            scale.target_texel_density_px_m,
            rel_tol=0,
            abs_tol=1.0e-9,
        ):
            raise ValueError("UV texel density differs from the exact AssetScaleContext")
    authorization = _load_high_resolution_authorization(root, request)
    selection = select_texture_resolution(
        request.resolution,
        scale_context_recommendation=scale.recommended_texture_resolution(maximum=8192),
        authorization=authorization,
    )
    final_root = ensure_contained_production_path(
        root,
        root / request.output_root,
        must_exist=False,
    )
    if os.path.exists(native_io_path(final_root)):
        raise FileExistsError(final_root)
    stage_root = ensure_contained_production_path(
        root,
        final_root.parent / f".{request.run_id}.staging-{uuid4().hex}",
        must_exist=False,
    )
    os.makedirs(native_io_path(stage_root), exist_ok=False)
    request_path = stage_root / "request.json"
    _write_model(request_path, request)
    request_artifact = _artifact(
        root,
        request_path,
        artifact_id=request.request_id,
        kind="material-authoring-request",
        media_type="application/json",
    ).model_copy(update={"path": (final_root / "request.json").relative_to(root).as_posix()})
    channels, limitations = _author_strategy(
        root,
        request,
        stage_root,
        final_root,
        selection.selected_pixels,
    )
    if request.preview_policy.reference_matched_requested:
        limitations.append("reference-matched Blender preview was requested but not run")
    limitations.append("neutral-studio Blender preview was not run by the local host")
    status = "review_required" if not channels else "unverified"
    manifest = AuthoredMaterialManifest(
        manifest_id=f"manifest-{request.run_id}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        run_id=request.run_id,
        material_id=request.material_id,
        strategy=request.strategy,
        material_family=request.material_family(),
        request=request_artifact,
        source_v05_contracts=request.source_v05_contracts,
        scale_context=request.scale_context,
        resolution=selection,
        channels=channels,
        master_intent=_master_intent(request, limitations),
        preview_evidence=PreviewEvidenceState(
            neutral_studio_status="not_run",
            reference_matched_status=(
                "not_run" if request.preview_policy.reference_matched_requested else "not_requested"
            ),
        ),
        source_to_output_provenance_sha256=_source_output_digest(request, channels),
        status=status,
        limitations=limitations,
        created_at=_utc_now(),
    )
    manifest_path = stage_root / "material_authoring_manifest.json"
    _write_model(manifest_path, manifest)
    staged_manifest = _artifact(
        root,
        manifest_path,
        artifact_id=manifest.manifest_id,
        kind="material-authoring-manifest",
        media_type="application/json",
    )
    manifest_artifact = staged_manifest.model_copy(
        update={
            "path": (final_root / "material_authoring_manifest.json").relative_to(root).as_posix()
        }
    )
    output_artifacts = [item.artifact for item in channels]
    bundle_sha = stable_json_digest(
        [item.model_dump(mode="json") for item in sorted(output_artifacts, key=lambda x: x.path)]
    )
    receipt = MaterialAuthoringReceipt(
        receipt_id=f"receipt-{request.run_id}",
        job_id=request.job_id,
        workflow_id=request.workflow_id,
        run_id=request.run_id,
        request=request_artifact,
        manifest=manifest_artifact,
        outputs=output_artifacts,
        output_bundle_sha256=bundle_sha,
        created_at=_utc_now(),
    )
    _write_model(stage_root / "material_authoring_receipt.json", receipt)
    os.makedirs(native_io_path(final_root.parent), exist_ok=True)
    os.replace(native_io_path(stage_root), native_io_path(final_root))
    _validate_artifact(root, receipt.request)
    _validate_artifact(root, receipt.manifest)
    _validate_publication_artifacts(root, manifest)
    with open(native_io_path(final_root / "material_authoring_manifest.json"), "rb") as handle:
        published = AuthoredMaterialManifest.model_validate_json(handle.read())
    if published != manifest:
        raise RuntimeError("published material manifest differs from staged evidence")
    with open(native_io_path(final_root / "material_authoring_receipt.json"), "rb") as handle:
        published_receipt = MaterialAuthoringReceipt.model_validate_json(handle.read())
    if published_receipt != receipt:
        raise RuntimeError("published material receipt differs from staged evidence")
    return receipt
