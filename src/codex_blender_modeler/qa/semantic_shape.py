from __future__ import annotations

import math
from pathlib import Path
from typing import TypeAlias

from PIL import Image, ImageFilter

from .diagnostic_models import SemanticRole, SemanticShapeMetrics
from .image_io import open_image

MaskInput: TypeAlias = Image.Image | Path


def _load_grayscale_mask(value: MaskInput) -> Image.Image:
    """Load a mask as an owned grayscale image without retaining an open file handle."""

    if isinstance(value, Image.Image):
        return value.convert("L")
    with open_image(value) as image:
        return image.convert("L")


def _binary_pixels(image: Image.Image) -> bytearray:
    """Convert grayscale pixels into a deterministic foreground byte mask."""

    return bytearray(1 if value >= 128 else 0 for value in image.tobytes())


def _centroid(pixels: bytearray, width: int) -> tuple[float, float]:
    """Compute a foreground centroid in pixel-center coordinates."""

    count = sum(pixels)
    total_x = 0.0
    total_y = 0.0
    for index, value in enumerate(pixels):
        if not value:
            continue
        y, x = divmod(index, width)
        total_x += x + 0.5
        total_y += y + 0.5
    return total_x / count, total_y / count


def _boundary_points(
    pixels: bytearray,
    width: int,
    height: int,
) -> tuple[list[tuple[int, int]], bytearray]:
    """Extract a four-connected one-pixel boundary and its binary image."""

    points: list[tuple[int, int]] = []
    boundary = bytearray(width * height)
    for index, value in enumerate(pixels):
        if not value:
            continue
        y, x = divmod(index, width)
        exposed = (
            x == 0
            or x == width - 1
            or y == 0
            or y == height - 1
            or not pixels[index - 1]
            or not pixels[index + 1]
            or not pixels[index - width]
            or not pixels[index + width]
        )
        if exposed:
            boundary[index] = 255
            points.append((x, y))
    return points, boundary


def _dilated_boundary(
    boundary: bytearray,
    width: int,
    height: int,
    tolerance_px: int,
) -> bytes:
    """Dilate a boundary by the declared pixel tolerance using Pillow only."""

    image = Image.frombytes("L", (width, height), bytes(boundary))
    if tolerance_px <= 0:
        return image.tobytes()
    return image.filter(ImageFilter.MaxFilter(tolerance_px * 2 + 1)).tobytes()


def _boundary_f_score(
    reference_boundary: bytearray,
    rendered_boundary: bytearray,
    width: int,
    height: int,
    tolerance_px: int,
) -> float:
    """Compute symmetric boundary precision/recall within a bounded pixel tolerance."""

    reference_count = sum(1 for value in reference_boundary if value)
    rendered_count = sum(1 for value in rendered_boundary if value)
    if reference_count == 0 or rendered_count == 0:
        return 0.0
    dilated_reference = _dilated_boundary(
        reference_boundary,
        width,
        height,
        tolerance_px,
    )
    dilated_rendered = _dilated_boundary(
        rendered_boundary,
        width,
        height,
        tolerance_px,
    )
    precision_hits = sum(
        1
        for index, value in enumerate(rendered_boundary)
        if value and dilated_reference[index]
    )
    recall_hits = sum(
        1
        for index, value in enumerate(reference_boundary)
        if value and dilated_rendered[index]
    )
    precision = precision_hits / rendered_count
    recall = recall_hits / reference_count
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _sample_contour(
    points: list[tuple[int, int]],
    maximum: int,
) -> list[tuple[int, int]]:
    """Downsample an ordered contour deterministically for bounded distance work."""

    if len(points) <= maximum:
        return points
    scale = len(points) / maximum
    return [points[min(len(points) - 1, int(index * scale))] for index in range(maximum)]


def _directed_contour_distance(
    source: list[tuple[int, int]],
    target: list[tuple[int, int]],
) -> float:
    """Return the mean nearest Euclidean distance from one sampled contour to another."""

    total = 0.0
    for source_x, source_y in source:
        nearest_squared = min(
            (source_x - target_x) ** 2 + (source_y - target_y) ** 2
            for target_x, target_y in target
        )
        total += math.sqrt(nearest_squared)
    return total / len(source)


def _symmetric_contour_distance(
    reference: list[tuple[int, int]],
    rendered: list[tuple[int, int]],
    width: int,
    height: int,
    maximum_points: int,
) -> float:
    """Compute a symmetric mean contour distance normalized by image diagonal."""

    reference_sample = _sample_contour(reference, maximum_points)
    rendered_sample = _sample_contour(rendered, maximum_points)
    forward = _directed_contour_distance(reference_sample, rendered_sample)
    reverse = _directed_contour_distance(rendered_sample, reference_sample)
    diagonal = math.hypot(width, height)
    return (forward + reverse) / (2.0 * diagonal)


def _principal_axis(
    pixels: bytearray,
    width: int,
    height: int,
) -> tuple[float | None, float | None]:
    """Estimate a 180-degree-periodic PCA axis and its eccentricity."""

    count = sum(pixels)
    if count < 2:
        return None, None
    center_x, center_y = _centroid(pixels, width)
    covariance_xx = 0.0
    covariance_xy = 0.0
    covariance_yy = 0.0
    for index, value in enumerate(pixels):
        if not value:
            continue
        y, x = divmod(index, width)
        centered_x = x + 0.5 - center_x
        centered_y = y + 0.5 - center_y
        covariance_xx += centered_x * centered_x
        covariance_xy += centered_x * centered_y
        covariance_yy += centered_y * centered_y
    covariance_xx /= count
    covariance_xy /= count
    covariance_yy /= count
    trace = covariance_xx + covariance_yy
    discriminant = math.sqrt(
        max(0.0, (covariance_xx - covariance_yy) ** 2 + 4.0 * covariance_xy**2)
    )
    major = (trace + discriminant) / 2.0
    minor = max(0.0, (trace - discriminant) / 2.0)
    if major <= 1e-15:
        return None, None
    eccentricity = math.sqrt(max(0.0, 1.0 - minor / major))
    angle = math.degrees(
        0.5 * math.atan2(2.0 * covariance_xy, covariance_xx - covariance_yy)
    ) % 180.0
    return angle, eccentricity


def undirected_axis_error_degrees(reference_deg: float, rendered_deg: float) -> float:
    """Measure orientation error on an undirected 180-degree-periodic axis."""

    difference = abs((reference_deg % 180.0) - (rendered_deg % 180.0))
    return min(difference, 180.0 - difference)


def compare_semantic_masks(
    reference: MaskInput,
    rendered: MaskInput,
    *,
    semantic_id: str,
    role: SemanticRole = "unscoped",
    boundary_tolerance_px: int = 2,
    min_axis_pixels: int = 16,
    min_axis_eccentricity: float = 0.15,
    max_contour_points: int = 2048,
) -> SemanticShapeMetrics:
    """Compare two semantic masks without altering the canonical V0.6 score contract."""

    if boundary_tolerance_px < 0 or boundary_tolerance_px > 32:
        raise ValueError("boundary_tolerance_px must be within [0, 32]")
    if min_axis_pixels < 2:
        raise ValueError("min_axis_pixels must be at least two")
    if not 0 <= min_axis_eccentricity <= 1:
        raise ValueError("min_axis_eccentricity must be within [0, 1]")
    if max_contour_points < 16:
        raise ValueError("max_contour_points must be at least 16")

    reference_image = _load_grayscale_mask(reference)
    rendered_image = _load_grayscale_mask(rendered)
    if reference_image.size != rendered_image.size:
        raise ValueError("semantic masks must use the same resolution")
    width, height = reference_image.size
    reference_pixels = _binary_pixels(reference_image)
    rendered_pixels = _binary_pixels(rendered_image)
    reference_count = sum(reference_pixels)
    rendered_count = sum(rendered_pixels)
    if reference_count == 0 or rendered_count == 0:
        missing = []
        if reference_count == 0:
            missing.append("reference semantic mask has no foreground pixels")
        if rendered_count == 0:
            missing.append("rendered semantic mask has no foreground pixels")
        return SemanticShapeMetrics(
            semantic_id=semantic_id,
            role=role,
            status="unscorable",
            width=width,
            height=height,
            reference_foreground_pixels=reference_count,
            rendered_foreground_pixels=rendered_count,
            boundary_tolerance_px=boundary_tolerance_px,
            limitations=missing,
        )

    intersection = sum(
        1
        for reference_value, rendered_value in zip(
            reference_pixels,
            rendered_pixels,
            strict=True,
        )
        if reference_value and rendered_value
    )
    union = reference_count + rendered_count - intersection
    mask_iou = intersection / union
    reference_centroid = _centroid(reference_pixels, width)
    rendered_centroid = _centroid(rendered_pixels, width)
    centroid_error = math.dist(reference_centroid, rendered_centroid) / math.hypot(
        width,
        height,
    )
    area_ratio = rendered_count / reference_count

    reference_contour, reference_boundary = _boundary_points(
        reference_pixels,
        width,
        height,
    )
    rendered_contour, rendered_boundary = _boundary_points(
        rendered_pixels,
        width,
        height,
    )
    boundary_f_score = _boundary_f_score(
        reference_boundary,
        rendered_boundary,
        width,
        height,
        boundary_tolerance_px,
    )
    contour_distance = _symmetric_contour_distance(
        reference_contour,
        rendered_contour,
        width,
        height,
        max_contour_points,
    )

    limitations: list[str] = []
    reference_axis, reference_eccentricity = _principal_axis(
        reference_pixels,
        width,
        height,
    )
    rendered_axis, rendered_eccentricity = _principal_axis(
        rendered_pixels,
        width,
        height,
    )
    axis_scorable = (
        reference_count >= min_axis_pixels
        and rendered_count >= min_axis_pixels
        and reference_axis is not None
        and rendered_axis is not None
        and reference_eccentricity is not None
        and rendered_eccentricity is not None
        and reference_eccentricity >= min_axis_eccentricity
        and rendered_eccentricity >= min_axis_eccentricity
    )
    if not axis_scorable:
        limitations.append(
            "oriented axis is unscorable because a mask is too small or insufficiently elongated"
        )
        reference_axis = None
        rendered_axis = None
        reference_eccentricity = None
        rendered_eccentricity = None

    return SemanticShapeMetrics(
        semantic_id=semantic_id,
        role=role,
        status="scored",
        width=width,
        height=height,
        reference_foreground_pixels=reference_count,
        rendered_foreground_pixels=rendered_count,
        mask_iou=mask_iou,
        centroid_error_norm=centroid_error,
        area_ratio=area_ratio,
        boundary_f_score=boundary_f_score,
        boundary_tolerance_px=boundary_tolerance_px,
        symmetric_contour_distance_norm=contour_distance,
        oriented_axis_scorable=axis_scorable,
        reference_axis_deg=reference_axis,
        rendered_axis_deg=rendered_axis,
        undirected_axis_error_deg=(
            undirected_axis_error_degrees(reference_axis, rendered_axis)
            if axis_scorable and reference_axis is not None and rendered_axis is not None
            else None
        ),
        reference_axis_eccentricity=reference_eccentricity,
        rendered_axis_eccentricity=rendered_eccentricity,
        limitations=limitations,
    )


def semantic_shape_similarity_score(metrics: SemanticShapeMetrics) -> float | None:
    """Project scored companion metrics to one advisory camera-probe score."""

    if metrics.status != "scored":
        return None
    assert metrics.mask_iou is not None
    assert metrics.centroid_error_norm is not None
    assert metrics.area_ratio is not None
    assert metrics.boundary_f_score is not None
    assert metrics.symmetric_contour_distance_norm is not None
    components = [
        metrics.mask_iou,
        metrics.boundary_f_score,
        max(0.0, 1.0 - metrics.centroid_error_norm),
        min(metrics.area_ratio, 1.0 / metrics.area_ratio),
        max(0.0, 1.0 - metrics.symmetric_contour_distance_norm * 4.0),
    ]
    if metrics.oriented_axis_scorable and metrics.undirected_axis_error_deg is not None:
        components.append(max(0.0, 1.0 - metrics.undirected_axis_error_deg / 90.0))
    return sum(components) / len(components)
