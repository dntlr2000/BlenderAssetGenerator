"""Deterministic staging-only adapter from selected Codex images to raw PBR channels."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageStat
from pydantic import BaseModel

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest, write_json_atomic
from ..production.validation import ensure_contained_production_path
from ..structural_geometry.models import AssetScaleContext
from .codex_image_models import (
    CodexImageAuthoredMaterialManifestV021,
    CodexImageChannelDerivationV021,
    CodexImageMaterialAuthoringReceiptV021,
    CodexImageMaterialAuthoringRequestV021,
    CodexImageMaterialQualityV021,
    ExactSignageTextEvidenceV021,
    ExactTextCompositionReceiptV021,
)
from .models import ExactArtifact, RawPBRChannel, UVIdentitySnapshot

__all__ = [
    "author_codex_image_material_candidate",
    "validate_codex_image_material_candidate",
]


def _utc_now() -> datetime:
    """Return one timezone-aware timestamp for immutable staging evidence."""

    return datetime.now(UTC)


def _path_is_file(path: Path) -> bool:
    """Check one file through its native extended-length representation."""

    return os.path.isfile(native_io_path(path))


def _validate_artifact(root: Path, artifact: ExactArtifact) -> Path:
    """Reject missing, linked, resized, or rehashed material input evidence."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if not _path_is_file(path):
        raise ValueError(f"material source must be a regular file: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"material source byte size changed: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"material source hash changed: {artifact.path}")
    return path


def _load_exact_model(
    root: Path,
    artifact: ExactArtifact,
    model_type: type[BaseModel],
) -> BaseModel:
    """Rehash and strict-parse one exact job-contained JSON evidence model."""

    path = _validate_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model_type.model_validate_json(handle.read())


def _nested_contains_value(payload: Any, key: str, value: str) -> bool:
    """Find an exact scalar binding inside a strictly parsed nested evidence payload."""

    if isinstance(payload, dict):
        if payload.get(key) == value:
            return True
        return any(_nested_contains_value(item, key, value) for item in payload.values())
    if isinstance(payload, list):
        return any(_nested_contains_value(item, key, value) for item in payload)
    return False


def _same_artifact(left: Any, right: ExactArtifact) -> bool:
    """Compare one core artifact and one material artifact by every shared exact field."""

    return all(
        getattr(left, field) == getattr(right, field)
        for field in ("artifact_id", "kind", "path", "sha256", "byte_size", "media_type")
    )


def _validate_core_evidence(
    root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
) -> set[str]:
    """Strict-parse and cross-hash the core selection, quality, evidence, and adoption chain."""

    from ..codex_imagegen.models import (  # Imported lazily to keep the additive module acyclic.
        CodexGeneratedImageEvidence,
        CodexImageGenerationQualityReport,
        CodexImageGenerationSelection,
        ImageToMaterialAdoption,
    )

    bindings = request.core_evidence
    selection = _load_exact_model(root, bindings.selection, CodexImageGenerationSelection)
    evidence = _load_exact_model(root, bindings.selected_evidence, CodexGeneratedImageEvidence)
    quality = _load_exact_model(
        root,
        bindings.selected_quality_report,
        CodexImageGenerationQualityReport,
    )
    adoption = _load_exact_model(root, bindings.adoption, ImageToMaterialAdoption)
    payloads = {
        "selection": selection.model_dump(mode="json"),
        "evidence": evidence.model_dump(mode="json"),
        "quality": quality.model_dump(mode="json"),
        "adoption": adoption.model_dump(mode="json"),
    }
    if not _nested_contains_value(payloads["evidence"], "sha256", request.source.artifact.sha256):
        raise ValueError("selected image evidence does not bind the requested source bytes")
    if not _nested_contains_value(
        payloads["quality"], "sha256", bindings.selected_evidence.sha256
    ):
        raise ValueError("selected quality report does not bind selected image evidence")
    if not _nested_contains_value(
        payloads["selection"], "sha256", bindings.selected_quality_report.sha256
    ):
        raise ValueError("selection does not bind its selected quality report")
    for name, artifact in (
        ("selection", bindings.selection),
        ("selected evidence", bindings.selected_evidence),
        ("selected quality report", bindings.selected_quality_report),
    ):
        if not _nested_contains_value(payloads["adoption"], "sha256", artifact.sha256):
            raise ValueError(f"image-to-material adoption does not bind {name}")
    if request.material_id not in set(getattr(adoption, "target_material_ids", [])):
        raise ValueError("image-to-material adoption does not target this material")
    if request.source.direct_role not in set(getattr(adoption, "direct_channels", [])):
        raise ValueError("image-to-material adoption does not authorize the selected direct role")
    if selection.outcome != "selected" or selection.selected_quality_report is None:
        raise ValueError("material authoring requires one deterministically selected candidate")
    if quality.outcome != "passed" or not quality.selection_eligible:
        raise ValueError("material authoring requires a passed selection-eligible quality report")
    if adoption.material_strategy != request.strategy:
        raise ValueError("image-to-material adoption strategy differs from the request")
    if adoption.derived_channels:
        raise ValueError(
            "pre-derived adoption channels cannot be silently replaced by local derivation"
        )
    if adoption.selected_source_sha256 != request.source.artifact.sha256:
        raise ValueError("image-to-material adoption source hash differs from selected bytes")
    if evidence.generated_file.output_role != request.source.direct_role:
        raise ValueError("generated image role differs from the requested direct role")
    if not _same_artifact(evidence.generated_file.artifact, request.source.artifact):
        raise ValueError("selected generated file differs from the exact material source")
    exact_links = (
        (selection.selected_quality_report, bindings.selected_quality_report, "selection quality"),
        (quality.generated_image_evidence, bindings.selected_evidence, "quality evidence"),
        (adoption.selection, bindings.selection, "adoption selection"),
        (adoption.generated_image_evidence, bindings.selected_evidence, "adoption evidence"),
        (adoption.quality_report, bindings.selected_quality_report, "adoption quality"),
    )
    for actual, expected, label in exact_links:
        if not _same_artifact(actual, expected):
            raise ValueError(f"{label} exact artifact binding differs")
    identities = (selection, evidence, quality, adoption)
    if any(item.job_id != request.job_id for item in identities):
        raise ValueError("core image evidence job identity differs from material request")
    if any(item.workflow_id != request.workflow_id for item in identities):
        raise ValueError("core image evidence workflow identity differs from material request")
    text_config = request.exact_text
    exact_text_artifact = (
        text_config.text_evidence_artifact if text_config is not None else None
    )
    if adoption.exact_text_composition is None:
        if exact_text_artifact is not None:
            raise ValueError("exact text request is missing its adoption evidence binding")
    elif exact_text_artifact is None or not _same_artifact(
        adoption.exact_text_composition,
        exact_text_artifact,
    ):
        raise ValueError("adoption exact-text artifact differs from the material request")
    selected_candidate = selection.selected_candidate
    if selected_candidate is None:
        raise ValueError("selected outcome is missing selected candidate evidence")
    candidate_links = (
        (quality.candidate, selected_candidate, "quality selected candidate"),
        (evidence.candidate, selected_candidate, "evidence selected candidate"),
        (adoption.selected_candidate, selected_candidate, "adoption selected candidate"),
    )
    for actual, expected, label in candidate_links:
        if actual != expected:
            raise ValueError(f"{label} exact artifact binding differs")
    return set(adoption.direct_channels)


def _validate_uv_identity(root: Path, request: CodexImageMaterialAuthoringRequestV021) -> None:
    """Rehash and compare the trusted UV snapshot before deriving any channel."""

    loaded = _load_exact_model(root, request.uv_identity.evidence, UVIdentitySnapshot)
    expected = request.uv_identity.model_dump(mode="python", exclude={"evidence"})
    if loaded.model_dump(mode="python") != expected:
        raise ValueError("UV identity evidence is stale or mismatched")


def _validate_scale_context(root: Path, request: CodexImageMaterialAuthoringRequestV021) -> None:
    """Rehash AssetScaleContext and compare every cached material-scale binding."""

    loaded = _load_exact_model(root, request.scale_context.artifact, AssetScaleContext)
    binding = request.scale_context
    if loaded.asset_id != binding.asset_id:
        raise ValueError("scale context asset identity changed")
    if loaded.job_id != request.job_id or loaded.workflow_id != request.workflow_id:
        raise ValueError("scale context job or workflow identity differs from material request")
    if loaded.source_fingerprint != binding.source_fingerprint:
        raise ValueError("scale context source fingerprint changed")
    comparisons = (
        (loaded.shortest_dimension_m, binding.shortest_dimension_m, "shortest dimension"),
        (max(loaded.assembly_bbox.dimensions()), binding.longest_dimension_m, "longest dimension"),
        (
            loaded.target_texel_density_px_m,
            binding.target_texel_density_px_m,
            "texel density",
        ),
    )
    for actual, expected, label in comparisons:
        if not math.isclose(actual, expected, rel_tol=0, abs_tol=1.0e-9):
            raise ValueError(f"scale context {label} binding is stale")


def _validate_inputs(
    root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
) -> tuple[Path, set[str]]:
    """Validate every exact dependency and return source path plus direct permissions."""

    authorized_direct_roles = _validate_core_evidence(root, request)
    source_path = _validate_artifact(root, request.source.artifact)
    for artifact in request.source_v05_contracts:
        _validate_artifact(root, artifact)
    _validate_uv_identity(root, request)
    _validate_scale_context(root, request)
    if request.exact_text is not None and request.exact_text.font is not None:
        _validate_artifact(root, request.exact_text.font.artifact)
    if (
        request.exact_text is not None
        and request.exact_text.text_evidence_artifact is not None
    ):
        loaded_text = _load_exact_model(
            root,
            request.exact_text.text_evidence_artifact,
            ExactSignageTextEvidenceV021,
        )
        if loaded_text.text != request.exact_text.text:
            raise ValueError("exact signage text differs from its immutable evidence")
    with Image.open(native_io_path(source_path)) as opened:
        if opened.size != (request.source.width, request.source.height):
            raise ValueError("selected image dimensions changed")
        opened.verify()
    return source_path, authorized_direct_roles


def _staged_artifact(
    root: Path,
    staged_path: Path,
    final_path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> ExactArtifact:
    """Bind staged bytes using the final portable path they receive after publication."""

    safe_staged = ensure_contained_production_path(root, staged_path, must_exist=True)
    safe_final = ensure_contained_production_path(root, final_path, must_exist=False)
    if not _path_is_file(safe_staged):
        raise ValueError(f"staged material output must be a regular file: {staged_path.name}")
    byte_size = os.path.getsize(native_io_path(safe_staged))
    if byte_size <= 0:
        raise ValueError(f"staged material output must be non-empty: {staged_path.name}")
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=safe_final.relative_to(root).as_posix(),
        sha256=sha256_file(safe_staged),
        byte_size=byte_size,
        media_type=media_type,
    )


def _write_model(path: Path, model: BaseModel) -> None:
    """Write one deterministic UTF-8 JSON model to an unpublished staging path."""

    write_json_atomic(path, model.model_dump(mode="json"))


def _save_png(image: Image.Image, path: Path) -> None:
    """Write deterministic PNG bytes without metadata or adaptive optimization."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    image.save(native_io_path(path), format="PNG", compress_level=9, optimize=False)


def _to_byte(value: float) -> int:
    """Clamp one normalized scalar to an unsigned byte."""

    return int(round(max(0.0, min(1.0, value)) * 255.0))


def _rgba_bytes(color: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Convert one normalized RGBA tuple to exact bytes."""

    return tuple(_to_byte(value) for value in color)  # type: ignore[return-value]


def _load_source_rgba(path: Path, resolution: int) -> Image.Image:
    """Decode and normalize one selected raster to a deterministic square RGBA tile."""

    with Image.open(native_io_path(path)) as opened:
        source = opened.convert("RGBA")
    return source.resize((resolution, resolution), resample=Image.Resampling.LANCZOS)


def _lighting_normalized(image: Image.Image, radius: int, strength: float) -> Image.Image:
    """Remove bounded low-frequency lighting while preserving generated local color detail."""

    rgb = image.convert("RGB")
    blurred = rgb.filter(ImageFilter.BoxBlur(radius=radius))
    means = tuple(int(round(value)) for value in ImageStat.Stat(rgb).mean)
    neutral = Image.new("RGB", rgb.size, means)
    corrected = ImageChops.add(ImageChops.subtract(rgb, blurred), neutral)
    normalized = Image.blend(rgb, corrected, strength)
    return Image.merge("RGBA", (*normalized.split(), image.getchannel("A")))


def _derive_height(image: Image.Image, radius: int, strength: float) -> Image.Image:
    """Derive bounded local height only from the selected source luminance."""

    luminance = image.convert("L")
    low = luminance.filter(ImageFilter.BoxBlur(radius=max(1, radius // 4)))
    detail = ImageChops.add(ImageChops.subtract(luminance, low), Image.new("L", image.size, 128))
    return Image.blend(Image.new("L", image.size, 128), detail, strength)


def _height_to_normal(height: Image.Image, strength: float) -> Image.Image:
    """Derive one deterministic OpenGL +Y tangent-space normal from local height."""

    gain = max(0.0, min(strength, 8.0))
    gradient_x = height.filter(
        ImageFilter.Kernel(
            (3, 3),
            (-gain, 0.0, gain, -2.0 * gain, 0.0, 2.0 * gain, -gain, 0.0, gain),
            scale=8.0,
            offset=128.0,
        )
    )
    gradient_y = height.filter(
        ImageFilter.Kernel(
            (3, 3),
            (-gain, -2.0 * gain, -gain, 0.0, 0.0, 0.0, gain, 2.0 * gain, gain),
            scale=8.0,
            offset=128.0,
        )
    )
    return Image.merge(
        "RGB",
        (
            ImageChops.invert(gradient_x),
            ImageChops.invert(gradient_y),
            Image.new("L", height.size, 255),
        ),
    )


def _derive_roughness(
    image: Image.Image,
    radius: int,
    base: float,
    variation: float,
) -> Image.Image:
    """Derive bounded roughness from source-local luminance variation."""

    luminance = image.convert("L")
    low = luminance.filter(ImageFilter.BoxBlur(radius=max(1, radius // 4)))
    variation_map = ImageChops.difference(luminance, low)
    base_byte = _to_byte(base)
    amplitude = _to_byte(variation)
    return variation_map.point(
        lambda value: max(0, min(255, base_byte + ((value - 64) * amplitude // 255)))
    )


def _derive_occlusion(height: Image.Image, strength: float) -> Image.Image:
    """Derive optional bounded ambient-occlusion approximation from local height only."""

    cavities = ImageChops.invert(height).filter(ImageFilter.GaussianBlur(radius=1.0))
    return Image.blend(Image.new("L", height.size, 255), cavities, strength)


def _constant_scalar(size: tuple[int, int], value: float) -> Image.Image:
    """Create one deterministic non-color scalar fallback channel."""

    return Image.new("L", size, _to_byte(value))


def _flat_normal(size: tuple[int, int]) -> Image.Image:
    """Create one deterministic OpenGL +Y flat-normal fallback channel."""

    return Image.new("RGB", size, (128, 128, 255))


def _draw_bitmap_text(
    layer: Image.Image,
    font_path: Path,
    text: str,
    *,
    origin: tuple[int, int],
    bounds: tuple[int, int],
    color: tuple[int, int, int, int],
    horizontal_alignment: str,
    vertical_alignment: str,
) -> None:
    """Rasterize exact text from one strict project-local bitmap-font JSON artifact."""

    with open(native_io_path(font_path), encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or payload.get("schema_version") != "0.1.0":
        raise ValueError("project bitmap font must use schema_version 0.1.0")
    width, height = payload.get("glyph_width"), payload.get("glyph_height")
    spacing, glyphs = payload.get("spacing", 1), payload.get("glyphs")
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
        raise ValueError("project bitmap text does not fit its exact composition rectangle")
    rendered = (logical_width * scale, height * scale)
    x_offsets = {
        "left": 0,
        "center": (bounds[0] - rendered[0]) // 2,
        "right": bounds[0] - rendered[0],
    }
    y_offsets = {
        "top": 0,
        "center": (bounds[1] - rendered[1]) // 2,
        "bottom": bounds[1] - rendered[1],
    }
    offset_x = origin[0] + x_offsets[horizontal_alignment]
    offset_y = origin[1] + y_offsets[vertical_alignment]
    draw = ImageDraw.Draw(layer)
    for character_index, character in enumerate(text):
        if character == " ":
            continue
        glyph_x = offset_x + character_index * (width + spacing) * scale
        for row_index, row in enumerate(parsed[character]):
            for column_index, pixel in enumerate(row):
                if pixel == "1":
                    left = glyph_x + column_index * scale
                    top = offset_y + row_index * scale
                    draw.rectangle((left, top, left + scale - 1, top + scale - 1), fill=color)


def _draw_outline_text(
    layer: Image.Image,
    font_path: Path,
    text: str,
    *,
    origin: tuple[int, int],
    bounds: tuple[int, int],
    color: tuple[int, int, int, int],
    font_size: int,
    face_index: int,
    horizontal_alignment: str,
    vertical_alignment: str,
) -> None:
    """Rasterize exact text with one hash-bound project-local TTF or OTF face."""

    font = ImageFont.truetype(native_io_path(font_path), font_size, index=face_index)
    draw = ImageDraw.Draw(layer)
    text_bounds = draw.textbbox((0, 0), text, font=font)
    rendered_width = text_bounds[2] - text_bounds[0]
    rendered_height = text_bounds[3] - text_bounds[1]
    if rendered_width > bounds[0] or rendered_height > bounds[1]:
        raise ValueError("project outline text does not fit its exact composition rectangle")
    x_offsets = {
        "left": 0,
        "center": (bounds[0] - rendered_width) // 2,
        "right": bounds[0] - rendered_width,
    }
    y_offsets = {
        "top": 0,
        "center": (bounds[1] - rendered_height) // 2,
        "bottom": bounds[1] - rendered_height,
    }
    position = (
        origin[0] + x_offsets[horizontal_alignment] - text_bounds[0],
        origin[1] + y_offsets[vertical_alignment] - text_bounds[1],
    )
    draw.text(position, text, font=font, fill=color)


def _compose_exact_text(
    root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
    background: Image.Image,
) -> tuple[Image.Image, dict[str, Any] | None]:
    """Composite exact user text locally, or preserve unknown text as a no-glyph state."""

    config = request.exact_text
    if config is None:
        return background, None
    if config.evidence != "exact_user_text":
        return background, {
            "evidence": config.evidence,
            "rendered": False,
            "text_sha256": None,
            "font": None,
            "glyph_count": 0,
        }
    if config.text is None or config.font is None:
        raise ValueError("exact user text is missing its local text or font evidence")
    resolution = background.width
    left = int(round(config.uv_rect.minimum[0] * resolution))
    right = int(round(config.uv_rect.maximum[0] * resolution))
    top = int(round((1.0 - config.uv_rect.maximum[1]) * resolution))
    bottom = int(round((1.0 - config.uv_rect.minimum[1]) * resolution))
    bounds = (max(1, right - left), max(1, bottom - top))
    layer = Image.new("RGBA", background.size, (0, 0, 0, 0))
    font_path = _validate_artifact(root, config.font.artifact)
    arguments = {
        "origin": (left, top),
        "bounds": bounds,
        "color": _rgba_bytes(config.color),
        "horizontal_alignment": config.horizontal_alignment,
        "vertical_alignment": config.vertical_alignment,
    }
    if config.font.font_format == "bitmap_json_v1":
        _draw_bitmap_text(layer, font_path, config.text, **arguments)
    else:
        _draw_outline_text(
            layer,
            font_path,
            config.text,
            font_size=config.font_size_px,
            face_index=config.font.face_index,
            **arguments,
        )
    composed = background.convert("RGBA")
    composed.alpha_composite(layer)
    return composed, {
        "evidence": config.evidence,
        "rendered": True,
        "text_sha256": hashlib.sha256(config.text.encode("utf-8")).hexdigest(),
        "font": config.font.artifact,
        "glyph_count": len(config.text),
    }


def _quality_metrics(
    image: Image.Image,
    request: CodexImageMaterialAuthoringRequestV021,
) -> CodexImageMaterialQualityV021:
    """Evaluate spatial detail, offset-edge continuity, and optional wood grain direction."""

    luminance = image.convert("L")
    standard_deviation = float(ImageStat.Stat(luminance).stddev[0]) / 255.0
    left = luminance.crop((0, 0, 1, luminance.height))
    right = luminance.crop((luminance.width - 1, 0, luminance.width, luminance.height))
    top = luminance.crop((0, 0, luminance.width, 1))
    bottom = luminance.crop((0, luminance.height - 1, luminance.width, luminance.height))
    edge_rmse = max(
        ImageStat.Stat(ImageChops.difference(left, right)).rms[0],
        ImageStat.Stat(ImageChops.difference(top, bottom)).rms[0],
    ) / 255.0
    horizontal = ImageStat.Stat(
        ImageChops.difference(
            luminance.crop((1, 0, luminance.width, luminance.height)),
            luminance.crop((0, 0, luminance.width - 1, luminance.height)),
        )
    ).mean[0]
    vertical = ImageStat.Stat(
        ImageChops.difference(
            luminance.crop((0, 1, luminance.width, luminance.height)),
            luminance.crop((0, 0, luminance.width, luminance.height - 1)),
        )
    ).mean[0]
    if max(horizontal, vertical) <= 1.0e-9:
        detected = "none"
    elif abs(horizontal - vertical) / max(horizontal, vertical) < 0.1:
        detected = "ambiguous"
    else:
        detected = "x" if horizontal < vertical else "y"
    policy = request.derivation
    reasons: list[str] = []
    if standard_deviation < policy.minimum_spatial_standard_deviation:
        reasons.append("source lacks the bounded minimum spatial variation")
    grain_matches: bool | None = None
    if request.material_family == "wood":
        if edge_rmse > policy.maximum_offset_edge_rmse:
            reasons.append("wood source exceeds the offset-edge continuity threshold")
        if policy.expected_grain_axis != "none":
            grain_matches = detected == policy.expected_grain_axis
            if not grain_matches:
                reasons.append("wood grain direction does not match the exact requested axis")
    if request.source.rights_status == "unknown":
        reasons.append("source rights remain unknown")
    outcome = "passed" if not reasons else "review_required"
    return CodexImageMaterialQualityV021(
        decoded=True,
        dimensions_match=True,
        spatial_standard_deviation=standard_deviation,
        offset_edge_rmse=edge_rmse,
        detected_grain_axis=detected,  # type: ignore[arg-type]
        grain_axis_matches=grain_matches,
        outcome=outcome,
        reasons=reasons,
    )


def _material_images(
    root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
    source_path: Path,
    authorized_direct_roles: set[str],
) -> tuple[dict[RawPBRChannel, Image.Image], dict[str, Any] | None, list[str]]:
    """Build direct and source-bound local channels for one declared material strategy."""

    policy = request.derivation
    source = _load_source_rgba(source_path, policy.output_resolution)
    images: dict[RawPBRChannel, Image.Image] = {}
    provenance: dict[RawPBRChannel, str] = {}
    direct_role = request.source.direct_role
    if request.strategy == "codex_generated_procedural_hybrid_v1":
        source = _lighting_normalized(
            source,
            policy.low_frequency_radius_px,
            policy.lighting_removal_strength,
        )
    text_state: dict[str, Any] | None = None
    if request.strategy == "codex_generated_decal_v1":
        source, text_state = _compose_exact_text(root, request, source)
        images["base_color"] = source
        provenance["base_color"] = (
            "local_exact_text_composition"
            if text_state is not None and text_state["rendered"]
            else "codex_generated_direct"
        )
    elif direct_role == "opacity_source":
        images["opacity"] = source.convert("L")
        provenance["opacity"] = "codex_generated_direct"
        images["base_color"] = Image.new("RGB", source.size, (255, 255, 255))
        provenance["base_color"] = "local_constant"
    elif direct_role == "emission":
        images["emission"] = source.convert("RGB")
        provenance["emission"] = "codex_generated_direct"
        images["base_color"] = Image.blend(
            Image.new("RGB", source.size, (0, 0, 0)), source.convert("RGB"), 0.2
        )
        provenance["base_color"] = "local_deterministic_derivation"
    else:
        images["base_color"] = source
        provenance["base_color"] = (
            "local_deterministic_derivation"
            if request.strategy == "codex_generated_procedural_hybrid_v1"
            else "codex_generated_direct"
        )
    if "opacity" not in images:
        alpha = source.getchannel("A")
        if alpha.getextrema() == (255, 255):
            images["opacity"] = _constant_scalar(source.size, 1.0)
            provenance["opacity"] = "local_constant"
        else:
            if "opacity_source" not in authorized_direct_roles:
                raise ValueError("generated alpha requires explicit opacity_source adoption")
            images["opacity"] = alpha
            provenance["opacity"] = "codex_generated_direct"
    if "emission" not in images and request.material_family in {"emissive", "crystal"}:
        images["emission"] = source.convert("RGB")
        provenance["emission"] = (
            "codex_generated_direct"
            if direct_role == "emission"
            else "local_deterministic_derivation"
        )
    height = _derive_height(source, policy.low_frequency_radius_px, policy.height_strength)
    images["height"] = height
    provenance["height"] = "local_deterministic_derivation"
    images["normal"] = _height_to_normal(height, policy.normal_strength)
    provenance["normal"] = "local_deterministic_derivation"
    images["roughness"] = _derive_roughness(
        source,
        policy.low_frequency_radius_px,
        policy.roughness_base if request.material_family == "wood" else request.base_roughness,
        policy.roughness_variation,
    )
    provenance["roughness"] = "local_deterministic_derivation"
    images["metallic"] = _constant_scalar(source.size, 0.0)
    provenance["metallic"] = "local_constant"
    if policy.derive_occlusion:
        images["occlusion"] = _derive_occlusion(height, policy.occlusion_strength)
        provenance["occlusion"] = "local_deterministic_derivation"
    return images, text_state, [f"{channel}:{provenance[channel]}" for channel in sorted(images)]


def _write_channels(
    root: Path,
    stage_root: Path,
    final_root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
    images: dict[RawPBRChannel, Image.Image],
    provenance_records: list[str],
) -> list[CodexImageChannelDerivationV021]:
    """Write raw PNG channels and bind every output to exact local derivation evidence."""

    provenance = dict(record.split(":", 1) for record in provenance_records)
    outputs: list[CodexImageChannelDerivationV021] = []
    for channel in sorted(images):
        filename = f"{channel}.png"
        staged_path = stage_root / "textures" / filename
        final_path = final_root / "textures" / filename
        _save_png(images[channel], staged_path)
        artifact = _staged_artifact(
            root,
            staged_path,
            final_path,
            artifact_id=f"{request.run_id}-{channel}",
            kind=f"raw-pbr-{channel}",
            media_type="image/png",
        )
        parameters: dict[str, bool | int | float | str] = {
            "derivation_policy_sha256": request.derivation.exact_sha256(),
            "output_resolution": request.derivation.output_resolution,
            "source_direct_role": request.source.direct_role,
        }
        if channel == "normal":
            parameters["normal_strength"] = request.derivation.normal_strength
        elif channel == "roughness":
            parameters["roughness_base"] = (
                request.derivation.roughness_base
                if request.material_family == "wood"
                else request.base_roughness
            )
            parameters["roughness_variation"] = request.derivation.roughness_variation
        elif channel == "occlusion":
            parameters["occlusion_strength"] = request.derivation.occlusion_strength
        elif channel == "height":
            parameters["height_strength"] = request.derivation.height_strength
        parameters_sha256 = stable_json_digest(parameters)
        kind = provenance[channel]
        algorithm = {
            "codex_generated_direct": "codex_image_decode_resize_direct_v1",
            "local_deterministic_derivation": "codex_image_local_pbr_derivation_v1",
            "local_exact_text_composition": "project_local_exact_text_composition_v1",
            "local_constant": "portable_constant_channel_v1",
        }[kind]
        source_hashes = [request.source.artifact.sha256, request.uv_identity.evidence.sha256]
        if request.exact_text is not None and request.exact_text.font is not None:
            source_hashes.append(request.exact_text.font.artifact.sha256)
        if (
            request.exact_text is not None
            and request.exact_text.text_evidence_artifact is not None
        ):
            source_hashes.append(request.exact_text.text_evidence_artifact.sha256)
        outputs.append(
            CodexImageChannelDerivationV021(
                channel=channel,
                provenance_kind=kind,  # type: ignore[arg-type]
                algorithm_id=algorithm,
                algorithm_version="1.0.0",
                source_sha256=source_hashes,
                parameters=parameters,
                parameters_sha256=parameters_sha256,
                output=artifact,
                width=images[channel].width,
                height=images[channel].height,
                color_space="srgb" if channel in {"base_color", "emission"} else "non_color",
                uv_identity=request.uv_identity,
                normal_convention="opengl_y_plus" if channel == "normal" else None,
            )
        )
    return outputs


def _text_receipt(
    text_state: dict[str, Any] | None,
    request: CodexImageMaterialAuthoringRequestV021,
    channels: list[CodexImageChannelDerivationV021],
) -> ExactTextCompositionReceiptV021 | None:
    """Turn local text composition state into strict exact output evidence."""

    if text_state is None:
        return None
    base_output = next(channel.output for channel in channels if channel.channel == "base_color")
    return ExactTextCompositionReceiptV021(
        evidence=text_state["evidence"],
        rendered=text_state["rendered"],
        text_sha256=text_state["text_sha256"],
        font=text_state["font"],
        output=base_output if text_state["rendered"] else None,
        glyph_count=text_state["glyph_count"],
        algorithm_id="project_local_exact_text_composition_v1",
    )


def _validate_published_receipt(
    root: Path,
    receipt: CodexImageMaterialAuthoringReceiptV021,
) -> None:
    """Rehash every published staging artifact before returning success to the caller."""

    for artifact in (receipt.request, receipt.manifest, *receipt.outputs):
        _validate_artifact(root, artifact)
    bundle = stable_json_digest(
        [
            artifact.model_dump(mode="json")
            for artifact in sorted(receipt.outputs, key=lambda item: item.path)
        ]
    )
    if bundle != receipt.output_bundle_sha256:
        raise ValueError("published image material output bundle hash changed")


def author_codex_image_material_candidate(
    job_root: Path,
    request: CodexImageMaterialAuthoringRequestV021,
) -> CodexImageMaterialAuthoringReceiptV021:
    """Derive and atomically publish one staging-only MaterialAuthoring 0.2.1 candidate."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    source_path, authorized_direct_roles = _validate_inputs(root, request)
    final_root = ensure_contained_production_path(
        root,
        root / request.output_root,
        must_exist=False,
    )
    if os.path.exists(native_io_path(final_root)):
        raise FileExistsError(f"image material run already exists: {request.output_root}")
    parent = ensure_contained_production_path(root, final_root.parent, must_exist=False)
    os.makedirs(native_io_path(parent), exist_ok=True)
    stage_root = parent / f".{request.run_id}.staging-{uuid4().hex}"
    ensure_contained_production_path(root, stage_root, must_exist=False)
    os.makedirs(native_io_path(stage_root), exist_ok=False)
    try:
        request_path = stage_root / "request.json"
        _write_model(request_path, request)
        request_artifact = _staged_artifact(
            root,
            request_path,
            final_root / "request.json",
            artifact_id=f"{request.run_id}-request",
            kind="codex-image-material-authoring-request",
            media_type="application/json",
        )
        source = _load_source_rgba(source_path, request.derivation.output_resolution)
        quality = _quality_metrics(source, request)
        images, text_state, provenance = _material_images(
            root,
            request,
            source_path,
            authorized_direct_roles,
        )
        channels = _write_channels(root, stage_root, final_root, request, images, provenance)
        text_receipt = _text_receipt(text_state, request, channels)
        limitations = [*quality.reasons]
        if text_receipt is not None and not text_receipt.rendered:
            limitations.append(
                f"text evidence is {text_receipt.evidence}; no glyphs were invented or rasterized"
            )
        limitations.extend(
            [
                "raw candidate remains staging-only until authorized controller promotion",
                "actual Codex built-in ImageGen execution is not verified by this local adapter",
                "Blender compilation and destination runtime parity were not run",
            ]
        )
        status = (
            "candidate_ready"
            if quality.outcome == "passed"
            and (text_receipt is None or text_receipt.rendered)
            else "review_required"
        )
        manifest = CodexImageAuthoredMaterialManifestV021(
            manifest_id=f"{request.run_id}-manifest",
            job_id=request.job_id,
            workflow_id=request.workflow_id,
            run_id=request.run_id,
            material_id=request.material_id,
            strategy=request.strategy,
            material_family=request.material_family,
            request=request_artifact,
            core_evidence=request.core_evidence,
            source=request.source,
            source_v05_contracts=request.source_v05_contracts,
            uv_identity=request.uv_identity,
            scale_context=request.scale_context,
            derivation_policy_sha256=request.derivation.exact_sha256(),
            channels=channels,
            exact_text=text_receipt,
            quality=quality,
            status=status,
            limitations=limitations,
            created_at=_utc_now(),
        )
        manifest_path = stage_root / "manifest.json"
        _write_model(manifest_path, manifest)
        manifest_artifact = _staged_artifact(
            root,
            manifest_path,
            final_root / "manifest.json",
            artifact_id=f"{request.run_id}-manifest",
            kind="codex-image-authored-material-manifest",
            media_type="application/json",
        )
        output_artifacts = [channel.output for channel in channels]
        bundle_sha256 = stable_json_digest(
            [
                artifact.model_dump(mode="json")
                for artifact in sorted(output_artifacts, key=lambda item: item.path)
            ]
        )
        receipt = CodexImageMaterialAuthoringReceiptV021(
            receipt_id=f"{request.run_id}-receipt",
            job_id=request.job_id,
            workflow_id=request.workflow_id,
            run_id=request.run_id,
            request=request_artifact,
            manifest=manifest_artifact,
            outputs=output_artifacts,
            output_bundle_sha256=bundle_sha256,
            created_at=_utc_now(),
        )
        _write_model(stage_root / "receipt.json", receipt)
        os.replace(native_io_path(stage_root), native_io_path(final_root))
        _validate_published_receipt(root, receipt)
        return receipt
    except Exception:
        if os.path.isdir(native_io_path(stage_root)):
            shutil.rmtree(native_io_path(stage_root))
        raise


def validate_codex_image_material_candidate(
    job_root: Path,
    receipt: CodexImageMaterialAuthoringReceiptV021,
) -> CodexImageAuthoredMaterialManifestV021:
    """Replay exact inputs and outputs for one already-published staging-only candidate."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    _validate_published_receipt(root, receipt)
    request = _load_exact_model(
        root,
        receipt.request,
        CodexImageMaterialAuthoringRequestV021,
    )
    manifest = _load_exact_model(
        root,
        receipt.manifest,
        CodexImageAuthoredMaterialManifestV021,
    )
    if not isinstance(request, CodexImageMaterialAuthoringRequestV021):
        raise TypeError("material request loader returned an unexpected contract")
    if not isinstance(manifest, CodexImageAuthoredMaterialManifestV021):
        raise TypeError("material manifest loader returned an unexpected contract")
    receipt_path = root / request.output_root / "receipt.json"
    safe_receipt = ensure_contained_production_path(root, receipt_path, must_exist=True)
    with open(native_io_path(safe_receipt), "rb") as handle:
        published_receipt = CodexImageMaterialAuthoringReceiptV021.model_validate_json(
            handle.read()
        )
    if published_receipt != receipt:
        raise ValueError("provided receipt differs from its published staging bytes")
    if manifest.request != receipt.request:
        raise ValueError("manifest request binding differs from the receipt")
    manifest_outputs = sorted(
        (channel.output for channel in manifest.channels),
        key=lambda item: item.path,
    )
    if manifest_outputs != sorted(receipt.outputs, key=lambda item: item.path):
        raise ValueError("manifest channel outputs differ from the receipt bundle")
    identities = ("job_id", "workflow_id", "run_id")
    for field in identities:
        expected = getattr(receipt, field)
        if getattr(request, field) != expected or getattr(manifest, field) != expected:
            raise ValueError(f"material {field} differs across request, manifest, and receipt")
    _validate_inputs(root, request)
    for channel in manifest.channels:
        path = _validate_artifact(root, channel.output)
        with Image.open(native_io_path(path)) as opened:
            if opened.size != (channel.width, channel.height):
                raise ValueError(f"published {channel.channel} dimensions changed")
            opened.verify()
    return manifest
