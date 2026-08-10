"""Deterministic bounded foreground-mask candidates for reference evidence."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat

from .models import (
    EvidenceArtifact,
    EvidenceProvenance,
    ForegroundMaskCandidate,
    ForegroundMaskMetrics,
)

_MAX_WORKING_SIZE = 512


@dataclass(frozen=True)
class _RawCandidate:
    """Keep one in-memory mask and its deterministic method identity."""

    provider: Literal["pillow", "opencv"]
    method: str
    mask: Image.Image
    parameters: dict[str, bool | int | float | str]
    limitations: tuple[str, ...] = ()


def _sha256_file(path: Path) -> str:
    """Hash one generated artifact without depending on repository-global settings."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binary(mask: Image.Image) -> Image.Image:
    """Normalize a candidate into deterministic one-bit foreground values."""

    return mask.convert("L").point(lambda value: 255 if value >= 128 else 0)


def _pillow_candidates(image: Image.Image) -> list[_RawCandidate]:
    """Always return bounded Pillow candidates, including a safe weak fallback."""

    rgba = image.convert("RGBA")
    sample = rgba.copy()
    sample.thumbnail((_MAX_WORKING_SIZE, _MAX_WORKING_SIZE), Image.Resampling.LANCZOS)
    output: list[_RawCandidate] = []
    alpha = sample.getchannel("A")
    if alpha.getextrema()[0] < 250:
        output.append(
            _RawCandidate(
                provider="pillow",
                method="alpha_threshold",
                mask=alpha.point(lambda value: 255 if value > 8 else 0),
                parameters={"alpha_threshold": 8},
            )
        )

    rgb = sample.convert("RGB")
    width, height = rgb.size
    corners = (
        rgb.getpixel((0, 0)),
        rgb.getpixel((width - 1, 0)),
        rgb.getpixel((0, height - 1)),
        rgb.getpixel((width - 1, height - 1)),
    )
    background = tuple(
        round(sum(color[channel] for color in corners) / len(corners))
        for channel in range(3)
    )
    for threshold in (28, 48):
        mask = Image.new("L", rgb.size)
        values: list[int] = []
        for pixel in rgb.getdata():
            distance = math.sqrt(
                sum((float(pixel[channel]) - background[channel]) ** 2 for channel in range(3))
            )
            values.append(255 if distance >= threshold else 0)
        mask.putdata(values)
        mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
        output.append(
            _RawCandidate(
                provider="pillow",
                method="corner_color_distance",
                mask=mask,
                parameters={"rgb_distance_threshold": threshold},
                limitations=(
                    "Corner-color segmentation can confuse cast shadows or matching backgrounds.",
                ),
            )
        )

    usable = [item for item in output if _foreground_fraction(item.mask) not in {0.0, 1.0}]
    if usable:
        return usable
    inset = Image.new("L", sample.size, 0)
    left = max(0, round(width * 0.08))
    top = max(0, round(height * 0.08))
    right = min(width, round(width * 0.92))
    bottom = min(height, round(height * 0.92))
    if right <= left or bottom <= top:
        inset = Image.new("L", sample.size, 255)
    else:
        inset.paste(255, (left, top, right, bottom))
    return [
        _RawCandidate(
            provider="pillow",
            method="underconstrained_center_inset",
            mask=inset,
            parameters={"inset_fraction": 0.08},
            limitations=(
                "The image lacks enough corner contrast; this is a low-confidence framing mask.",
            ),
        )
    ]


def _opencv_candidates(image: Image.Image) -> list[_RawCandidate]:
    """Return optional deterministic OpenCV candidates without making OpenCV mandatory."""

    try:
        import cv2
        import numpy as np
    except ImportError:
        return []

    sample = image.convert("RGB")
    sample.thumbnail((_MAX_WORKING_SIZE, _MAX_WORKING_SIZE), Image.Resampling.LANCZOS)
    array = np.asarray(sample)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        4,
    )
    adaptive = cv2.morphologyEx(
        adaptive,
        cv2.MORPH_CLOSE,
        np.ones((5, 5), dtype=np.uint8),
        iterations=1,
    )
    candidates = [
        _RawCandidate(
            provider="opencv",
            method="adaptive_threshold",
            mask=Image.fromarray(adaptive, mode="L"),
            parameters={"block_size": 31, "constant": 4, "close_kernel": 5},
            limitations=(
                "Adaptive thresholding may select internal texture instead of the subject.",
            ),
        )
    ]
    height, width = gray.shape
    if width >= 10 and height >= 10:
        cv2.setRNGSeed(0)
        grab_mask = np.zeros((height, width), np.uint8)
        background_model = np.zeros((1, 65), np.float64)
        foreground_model = np.zeros((1, 65), np.float64)
        margin_x = max(1, round(width * 0.04))
        margin_y = max(1, round(height * 0.04))
        rect = (
            margin_x,
            margin_y,
            max(1, width - 2 * margin_x),
            max(1, height - 2 * margin_y),
        )
        try:
            cv2.grabCut(
                array,
                grab_mask,
                rect,
                background_model,
                foreground_model,
                1,
                cv2.GC_INIT_WITH_RECT,
            )
        except cv2.error:
            pass
        else:
            foreground = np.where(
                (grab_mask == cv2.GC_FGD) | (grab_mask == cv2.GC_PR_FGD),
                255,
                0,
            ).astype("uint8")
            candidates.append(
                _RawCandidate(
                    provider="opencv",
                    method="bounded_grabcut",
                    mask=Image.fromarray(foreground, mode="L"),
                    parameters={"iterations": 1, "rectangle_margin_fraction": 0.04},
                    limitations=(
                        "Rectangle-initialized GrabCut assumes the primary subject is not flush "
                        "with every image border.",
                    ),
                )
            )
    return [item for item in candidates if 0.0 < _foreground_fraction(item.mask) < 1.0]


def _foreground_fraction(mask: Image.Image) -> float:
    """Return the exact binary foreground fraction for one candidate."""

    binary = _binary(mask)
    histogram = binary.histogram()
    total = max(1, binary.width * binary.height)
    return histogram[255] / total


def _normalized_bbox(mask: Image.Image) -> tuple[float, float, float, float]:
    """Convert a non-empty mask bounding box to normalized image coordinates."""

    binary = _binary(mask)
    bbox = binary.getbbox()
    if bbox is None:
        return (0.0, 0.0, 1.0, 1.0)
    left, top, right, bottom = bbox
    width, height = binary.size
    return (
        round(left / width, 6),
        round(top / height, 6),
        round(right / width, 6),
        round(bottom / height, 6),
    )


def _edge_agreement(image: Image.Image, mask: Image.Image) -> float:
    """Estimate how often mask-boundary pixels coincide with image edges."""

    gray = ImageOps.grayscale(image).resize(mask.size, Image.Resampling.LANCZOS)
    image_edges = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES))
    threshold = max(24.0, ImageStat.Stat(image_edges).mean[0] * 1.35)
    image_binary = image_edges.point(lambda value: 255 if value >= threshold else 0)
    boundary = _binary(mask).filter(ImageFilter.FIND_EDGES).point(
        lambda value: 255 if value >= 32 else 0
    )
    boundary_count = boundary.histogram()[255]
    if boundary_count == 0:
        return 0.0
    overlap = ImageChops.multiply(boundary, image_binary).histogram()[255]
    return round(max(0.0, min(1.0, overlap / boundary_count)), 6)


def _border_contact(mask: Image.Image) -> float:
    """Measure the fraction of image-border samples labeled as foreground."""

    binary = _binary(mask)
    width, height = binary.size
    coordinates = [(x, 0) for x in range(width)] + [
        (x, height - 1) for x in range(width)
    ]
    if height > 2:
        coordinates += [(0, y) for y in range(1, height - 1)]
        coordinates += [(width - 1, y) for y in range(1, height - 1)]
    if not coordinates:
        return 0.0
    contacts = sum(binary.getpixel(point) > 0 for point in coordinates)
    return round(contacts / len(coordinates), 6)


def _mask_symmetry(mask: Image.Image) -> float:
    """Estimate bilateral mask agreement without treating symmetry as truth."""

    binary = _binary(mask)
    mirrored = ImageOps.mirror(binary)
    difference = ImageChops.difference(binary, mirrored)
    changed = difference.histogram()[255]
    total = max(1, binary.width * binary.height)
    return round(max(0.0, min(1.0, 1.0 - changed / total)), 6)


def _appearance_likelihoods(image: Image.Image, mask: Image.Image) -> tuple[float, float]:
    """Estimate shadow and reflection risk inside a mask from luminance and saturation."""

    rgb = image.convert("RGB").resize(mask.size, Image.Resampling.LANCZOS)
    hsv = rgb.convert("HSV")
    binary = _binary(mask)
    luminance = ImageOps.grayscale(rgb)
    saturation = hsv.getchannel("S")
    selected = max(1, binary.histogram()[255])
    shadow = sum(
        mask_value > 0 and lum < 48
        for mask_value, lum in zip(binary.getdata(), luminance.getdata(), strict=True)
    ) / selected
    reflection = sum(
        mask_value > 0 and lum > 220 and sat < 48
        for mask_value, lum, sat in zip(
            binary.getdata(),
            luminance.getdata(),
            saturation.getdata(),
            strict=True,
        )
    ) / selected
    return (
        round(max(0.0, min(1.0, shadow)), 6),
        round(max(0.0, min(1.0, reflection)), 6),
    )


def _candidate_metrics(image: Image.Image, mask: Image.Image) -> ForegroundMaskMetrics:
    """Calculate bounded metrics and a conservative diagnostic confidence."""

    binary = _binary(mask)
    area = _foreground_fraction(binary)
    edge = _edge_agreement(image, binary)
    border = _border_contact(binary)
    symmetry = _mask_symmetry(binary)
    shadow, reflection = _appearance_likelihoods(image, binary)
    size_plausibility = max(0.0, 1.0 - abs(area - 0.45) / 0.55)
    confidence = (
        0.38 * edge
        + 0.25 * size_plausibility
        + 0.12 * symmetry
        + 0.15 * (1.0 - border)
        + 0.05 * (1.0 - shadow)
        + 0.05 * (1.0 - reflection)
    )
    return ForegroundMaskMetrics(
        bbox_norm=_normalized_bbox(binary),
        area_ratio=round(area, 6),
        edge_agreement=edge,
        border_contact_ratio=border,
        bilateral_symmetry=symmetry,
        shadow_likelihood=shadow,
        reflection_likelihood=reflection,
        confidence=round(max(0.0, min(1.0, confidence)), 6),
    )


def _deduplicate(raw_candidates: list[_RawCandidate]) -> list[_RawCandidate]:
    """Remove identical in-memory masks while preserving deterministic provider order."""

    unique: list[_RawCandidate] = []
    seen: set[str] = set()
    for candidate in raw_candidates:
        binary = _binary(candidate.mask)
        digest = hashlib.sha256(binary.tobytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append(
            _RawCandidate(
                provider=candidate.provider,
                method=candidate.method,
                mask=binary,
                parameters=candidate.parameters,
                limitations=candidate.limitations,
            )
        )
    return unique


def generate_foreground_mask_candidates(
    image_path: Path,
    masks_dir: Path,
    masks_relative_dir: str,
    *,
    provider: Literal["auto", "pillow", "opencv"] = "auto",
) -> tuple[list[ForegroundMaskCandidate], list[str]]:
    """Generate at most three ranked masks while always retaining a Pillow fallback."""

    source = image_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    masks_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = opened.copy()
    pillow = _pillow_candidates(image)
    opencv = _opencv_candidates(image) if provider in {"auto", "opencv"} else []
    warnings: list[str] = []
    if provider == "opencv" and not opencv:
        warnings.append(
            "OpenCV candidates were unavailable or empty; deterministic Pillow evidence was used."
        )
    raw = _deduplicate(pillow + opencv)
    scored = [(item, _candidate_metrics(image, item.mask)) for item in raw]
    scored.sort(
        key=lambda item: (
            -item[1].confidence,
            0 if item[0].provider == "pillow" else 1,
            item[0].method,
            str(sorted(item[0].parameters.items())),
        )
    )
    selected = scored[:3]
    if not any(item[0].provider == "pillow" for item in selected):
        best_pillow = next(item for item in scored if item[0].provider == "pillow")
        selected[-1] = best_pillow
        selected.sort(
            key=lambda item: (
                -item[1].confidence,
                0 if item[0].provider == "pillow" else 1,
                item[0].method,
            )
        )

    results: list[ForegroundMaskCandidate] = []
    for rank, (raw_candidate, metrics) in enumerate(selected, start=1):
        candidate_id = f"mask-{rank:02d}"
        output = masks_dir / f"{candidate_id}.png"
        _binary(raw_candidate.mask).resize(image.size, Image.Resampling.NEAREST).save(
            output,
            format="PNG",
            optimize=False,
        )
        relative_path = f"{masks_relative_dir}/{output.name}"
        underconstrained = (
            raw_candidate.method == "underconstrained_center_inset"
            or metrics.area_ratio >= 0.98
            or metrics.confidence < 0.2
        )
        results.append(
            ForegroundMaskCandidate(
                candidate_id=candidate_id,
                rank=rank,
                artifact=EvidenceArtifact(
                    artifact_id=f"{candidate_id}-artifact",
                    path=relative_path,
                    sha256=_sha256_file(output),
                    media_type="image/png",
                    byte_size=output.stat().st_size,
                ),
                provenance=EvidenceProvenance(
                    producer="codex_blender_modeler.reference_evidence.segmentation",
                    producer_version="0.1.0",
                    provider=raw_candidate.provider,
                    method=raw_candidate.method,
                    deterministic=True,
                    parameters=raw_candidate.parameters,
                ),
                metrics=metrics,
                status="underconstrained" if underconstrained else "usable",
                assumptions=[
                    "The mask is a foreground hypothesis, not recovered object ground truth."
                ],
                limitations=list(raw_candidate.limitations),
            )
        )
    return results, warnings
