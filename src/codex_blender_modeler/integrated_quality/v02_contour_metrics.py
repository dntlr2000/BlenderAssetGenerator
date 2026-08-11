"""Exact scale-normalized contour metrics for Integrated Quality 0.2."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TypeAlias

from PIL import Image

from .v02_models import ContourEvidenceBindingV02, ContourMetricsV02

MaskInput: TypeAlias = Image.Image | Path


def _load_mask(value: MaskInput) -> Image.Image:
    """Load an owned grayscale mask without retaining an open file handle."""

    if isinstance(value, Image.Image):
        return value.convert("L")
    with Image.open(value) as image:
        return image.convert("L")


def _binary_pixels(image: Image.Image) -> bytearray:
    """Convert grayscale pixels to a deterministic binary foreground mask."""

    return bytearray(1 if value >= 128 else 0 for value in image.tobytes())


def _boundary_pixels(
    pixels: bytearray,
    width: int,
    height: int,
) -> bytearray:
    """Extract a four-connected one-pixel boundary from a binary mask."""

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
            boundary[index] = 1
    return boundary


def _squared_distance_transform_1d(values: list[float]) -> list[float]:
    """Compute an exact one-dimensional squared Euclidean distance transform."""

    count = len(values)
    if count == 0:
        return []
    sites = [0] * count
    breakpoints = [0.0] * (count + 1)
    sites[0] = 0
    breakpoints[0] = float("-inf")
    breakpoints[1] = float("inf")
    envelope_index = 0
    for position in range(1, count):
        site = sites[envelope_index]
        intersection = (
            (values[position] + position * position)
            - (values[site] + site * site)
        ) / (2.0 * (position - site))
        while intersection <= breakpoints[envelope_index]:
            envelope_index -= 1
            site = sites[envelope_index]
            intersection = (
                (values[position] + position * position)
                - (values[site] + site * site)
            ) / (2.0 * (position - site))
        envelope_index += 1
        sites[envelope_index] = position
        breakpoints[envelope_index] = intersection
        breakpoints[envelope_index + 1] = float("inf")
    output = [0.0] * count
    envelope_index = 0
    for position in range(count):
        while breakpoints[envelope_index + 1] < position:
            envelope_index += 1
        delta = position - sites[envelope_index]
        output[position] = delta * delta + values[sites[envelope_index]]
    return output


def _squared_euclidean_distance_transform(
    target_boundary: bytearray,
    width: int,
    height: int,
) -> list[float]:
    """Compute an exact two-dimensional squared Euclidean transform for target pixels."""

    if not any(target_boundary):
        raise ValueError("distance transform target boundary cannot be empty")
    unreachable = float((width * width + height * height) * 4 + 1)
    row_pass = [0.0] * (width * height)
    for y in range(height):
        row = [
            0.0 if target_boundary[y * width + x] else unreachable
            for x in range(width)
        ]
        transformed = _squared_distance_transform_1d(row)
        row_pass[y * width : (y + 1) * width] = transformed
    output = [0.0] * (width * height)
    for x in range(width):
        column = [row_pass[y * width + x] for y in range(height)]
        transformed = _squared_distance_transform_1d(column)
        for y, value in enumerate(transformed):
            output[y * width + x] = value
    return output


def _directed_boundary_distance(
    source_boundary: bytearray,
    target_squared_distances: list[float],
) -> float:
    """Return the mean exact Euclidean distance from one boundary to another."""

    distances = [
        math.sqrt(target_squared_distances[index])
        for index, value in enumerate(source_boundary)
        if value
    ]
    if not distances:
        raise ValueError("directed boundary distance source cannot be empty")
    return sum(distances) / len(distances)


def compare_contours_v02(
    reference: MaskInput,
    candidate: MaskInput,
    *,
    reference_evidence: ContourEvidenceBindingV02,
    candidate_evidence_id: str,
    candidate_artifact_sha256: str,
    candidate_camera_sha256: str,
    metric_id: str = "reference.contour_v02",
    boundary_tolerance_diagonal_fraction: float = 0.005,
    maximum_pixels: int = 16_777_216,
) -> ContourMetricsV02:
    """Compare full boundaries with exact EDT Chamfer normalized by image diagonal.

    This metric is intentionally distinct from the legacy sampled
    ``symmetric_contour_distance_norm`` metric and never changes that value.
    """

    if not 0 <= boundary_tolerance_diagonal_fraction <= 1:
        raise ValueError("boundary tolerance fraction must be within [0, 1]")
    if maximum_pixels < 1:
        raise ValueError("maximum_pixels must be positive")
    if candidate_camera_sha256 != reference_evidence.camera_sha256:
        raise ValueError("reference and candidate contour camera hashes must match")
    reference_image = _load_mask(reference)
    candidate_image = _load_mask(candidate)
    if reference_image.size != candidate_image.size:
        raise ValueError("contour masks must use the same resolution")
    width, height = reference_image.size
    if width < 1 or height < 1 or width * height > maximum_pixels:
        raise ValueError("contour mask dimensions exceed the bounded pixel budget")
    diagonal = math.hypot(width, height)
    tolerance_px = diagonal * boundary_tolerance_diagonal_fraction
    reference_boundary = _boundary_pixels(
        _binary_pixels(reference_image),
        width,
        height,
    )
    candidate_boundary = _boundary_pixels(
        _binary_pixels(candidate_image),
        width,
        height,
    )
    reference_count = sum(reference_boundary)
    candidate_count = sum(candidate_boundary)
    evidence_ids = [reference_evidence.evidence_id, candidate_evidence_id]
    limitations: list[str] = []
    if reference_evidence.authority == "unavailable":
        limitations.append("reference contour evidence is unavailable")
    if reference_count == 0:
        limitations.append("reference contour has no foreground boundary")
    if candidate_count == 0:
        limitations.append("candidate contour has no foreground boundary")
    if limitations:
        return ContourMetricsV02(
            metric_id=metric_id,
            status="unscorable",
            authority=reference_evidence.authority,
            evidence_ids=evidence_ids,
            reference_mask_sha256=reference_evidence.artifact_sha256,
            candidate_mask_sha256=candidate_artifact_sha256,
            camera_sha256=reference_evidence.camera_sha256,
            width=width,
            height=height,
            reference_boundary_pixels=reference_count,
            candidate_boundary_pixels=candidate_count,
            boundary_tolerance_px=tolerance_px,
            boundary_tolerance_diagonal_fraction=(
                boundary_tolerance_diagonal_fraction
            ),
            limitations=limitations,
        )
    reference_distances = _squared_euclidean_distance_transform(
        reference_boundary,
        width,
        height,
    )
    candidate_distances = _squared_euclidean_distance_transform(
        candidate_boundary,
        width,
        height,
    )
    precision_hits = sum(
        1
        for index, value in enumerate(candidate_boundary)
        if value and math.sqrt(reference_distances[index]) <= tolerance_px
    )
    recall_hits = sum(
        1
        for index, value in enumerate(reference_boundary)
        if value and math.sqrt(candidate_distances[index]) <= tolerance_px
    )
    precision = precision_hits / candidate_count
    recall = recall_hits / reference_count
    f_score = (
        0.0
        if precision + recall == 0
        else 2.0 * precision * recall / (precision + recall)
    )
    forward = _directed_boundary_distance(reference_boundary, candidate_distances)
    reverse = _directed_boundary_distance(candidate_boundary, reference_distances)
    chamfer = (forward + reverse) / (2.0 * diagonal)
    return ContourMetricsV02(
        metric_id=metric_id,
        status="scored",
        authority=reference_evidence.authority,
        evidence_ids=evidence_ids,
        reference_mask_sha256=reference_evidence.artifact_sha256,
        candidate_mask_sha256=candidate_artifact_sha256,
        camera_sha256=reference_evidence.camera_sha256,
        width=width,
        height=height,
        reference_boundary_pixels=reference_count,
        candidate_boundary_pixels=candidate_count,
        boundary_tolerance_px=tolerance_px,
        boundary_tolerance_diagonal_fraction=boundary_tolerance_diagonal_fraction,
        boundary_precision=precision,
        boundary_recall=recall,
        boundary_f_score=f_score,
        edge_distance_transform_chamfer_norm=chamfer,
    )
