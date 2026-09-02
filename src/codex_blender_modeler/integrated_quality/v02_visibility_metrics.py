"""Direct fixed-camera interior-visibility metrics for Integrated Quality 0.2."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TypeAlias

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .v02_models import (
    FixedCameraVisibilityMetricV02,
    VisibilityChannelMeasurementV02,
)

ImageInput: TypeAlias = Image.Image | Path

_EDGE_REFERENCE_FLOOR = 0.01
_HIGH_FREQUENCY_REFERENCE_FLOOR = 0.005
_LUMINANCE_REFERENCE_FLOOR = 0.02


def _load_rgb(value: ImageInput, size: tuple[int, int] | None = None) -> Image.Image:
    """Load one owned RGB image and optionally align it to the candidate resolution."""

    if isinstance(value, Image.Image):
        image = value.convert("RGB")
    else:
        with Image.open(value) as opened:
            image = opened.convert("RGB")
    if size is not None and image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image


def _load_binary_mask(value: ImageInput, size: tuple[int, int]) -> Image.Image:
    """Load one owned binary mask with deterministic nearest-neighbor alignment."""

    if isinstance(value, Image.Image):
        image = value.convert("L")
    else:
        with Image.open(value) as opened:
            image = opened.convert("L")
    if image.size != size:
        image = image.resize(size, Image.Resampling.NEAREST)
    return image.point(lambda pixel: 255 if pixel >= 128 else 0)


def _erode_mask(mask: Image.Image, *, radius: int) -> Image.Image:
    """Remove the outer silhouette band so contour agreement cannot masquerade as detail."""

    return mask.filter(ImageFilter.MinFilter(radius * 2 + 1))


def _masked_mean(image: Image.Image, mask: Image.Image) -> float:
    """Return one normalized masked-channel mean from deterministic 8-bit pixels."""

    return float(ImageStat.Stat(image, mask).mean[0]) / 255.0


def _masked_stddev(image: Image.Image, mask: Image.Image) -> float:
    """Return one normalized masked-channel standard deviation."""

    return float(ImageStat.Stat(image, mask).stddev[0]) / 255.0


def _visibility_values(image: Image.Image, mask: Image.Image) -> dict[str, float]:
    """Measure interior edge energy, high frequency, and luminance variation."""

    gray = image.convert("L")
    edge = gray.filter(ImageFilter.FIND_EDGES)
    blurred = gray.filter(ImageFilter.GaussianBlur(radius=2.0))
    high_frequency = ImageChops.difference(gray, blurred)
    return {
        "interior_edge": _masked_mean(edge, mask),
        "high_frequency": _masked_mean(high_frequency, mask),
        "luminance_variation": _masked_stddev(gray, mask),
    }


def _channel(
    channel: str,
    *,
    reference_value: float,
    candidate_value: float,
    reference_floor: float,
) -> VisibilityChannelMeasurementV02:
    """Build one exact retention channel without inventing a ratio below its floor."""

    informative = reference_value >= reference_floor
    return VisibilityChannelMeasurementV02(
        channel=channel,  # type: ignore[arg-type]
        reference_value=reference_value,
        candidate_value=candidate_value,
        reference_floor=reference_floor,
        informative=informative,
        retention_ratio=(candidate_value / reference_value if informative else None),
    )


def compare_fixed_camera_visibility_v02(
    reference_image: ImageInput,
    candidate_beauty: ImageInput,
    reference_mask: ImageInput,
    candidate_mask: ImageInput,
    *,
    reference_image_sha256: str,
    candidate_beauty_sha256: str,
    reference_mask_sha256: str,
    candidate_mask_sha256: str,
    camera_sha256: str,
    evidence_ids: list[str],
    metric_id: str = "reference.fixed_camera_visibility_v02",
    mask_erosion_diagonal_fraction: float = 0.008,
    maximum_pixels: int = 16_777_216,
) -> FixedCameraVisibilityMetricV02:
    """Compare direct interior visibility while excluding the matched silhouette band."""

    if len(evidence_ids) != 4 or len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("fixed-camera visibility requires four unique evidence IDs")
    if not 0 < mask_erosion_diagonal_fraction <= 0.05:
        raise ValueError("visibility mask erosion fraction must be within (0, 0.05]")
    if maximum_pixels < 1:
        raise ValueError("maximum_pixels must be positive")
    candidate = _load_rgb(candidate_beauty)
    width, height = candidate.size
    if width < 1 or height < 1 or width * height > maximum_pixels:
        raise ValueError("fixed-camera visibility dimensions exceed the pixel budget")
    reference = _load_rgb(reference_image, candidate.size)
    reference_binary = _load_binary_mask(reference_mask, candidate.size)
    candidate_binary = _load_binary_mask(candidate_mask, candidate.size)
    erosion_radius = max(
        1,
        min(49, round(math.hypot(width, height) * mask_erosion_diagonal_fraction)),
    )
    reference_interior = _erode_mask(reference_binary, radius=erosion_radius)
    candidate_interior = _erode_mask(candidate_binary, radius=erosion_radius)
    reference_pixels = int(reference_interior.histogram()[255])
    candidate_pixels = int(candidate_interior.histogram()[255])
    common = {
        "metric_id": metric_id,
        "authority": "authoritative",
        "evidence_ids": evidence_ids,
        "reference_image_sha256": reference_image_sha256,
        "candidate_beauty_sha256": candidate_beauty_sha256,
        "reference_mask_sha256": reference_mask_sha256,
        "candidate_mask_sha256": candidate_mask_sha256,
        "camera_sha256": camera_sha256,
        "width": width,
        "height": height,
        "mask_erosion_diagonal_fraction": mask_erosion_diagonal_fraction,
        "mask_erosion_radius_px": erosion_radius,
        "reference_interior_pixels": reference_pixels,
        "candidate_interior_pixels": candidate_pixels,
    }
    if reference_pixels < 1 or candidate_pixels < 1:
        limitations = []
        if reference_pixels < 1:
            limitations.append("reference mask has no interior after contour-band erosion")
        if candidate_pixels < 1:
            limitations.append("candidate mask has no interior after contour-band erosion")
        return FixedCameraVisibilityMetricV02(
            **common,
            status="unscorable",
            informative_channel_count=0,
            limitations=limitations,
        )
    reference_values = _visibility_values(reference, reference_interior)
    candidate_values = _visibility_values(candidate, candidate_interior)
    channels = [
        _channel(
            "interior_edge",
            reference_value=reference_values["interior_edge"],
            candidate_value=candidate_values["interior_edge"],
            reference_floor=_EDGE_REFERENCE_FLOOR,
        ),
        _channel(
            "high_frequency",
            reference_value=reference_values["high_frequency"],
            candidate_value=candidate_values["high_frequency"],
            reference_floor=_HIGH_FREQUENCY_REFERENCE_FLOOR,
        ),
        _channel(
            "luminance_variation",
            reference_value=reference_values["luminance_variation"],
            candidate_value=candidate_values["luminance_variation"],
            reference_floor=_LUMINANCE_REFERENCE_FLOOR,
        ),
    ]
    uninformative = [item.channel for item in channels if not item.informative]
    return FixedCameraVisibilityMetricV02(
        **common,
        status="scored",
        informative_channel_count=sum(item.informative for item in channels),
        channels=channels,
        limitations=(
            ["Reference channels below deterministic floor: " + ", ".join(uninformative)]
            if uninformative
            else []
        ),
    )
