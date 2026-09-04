"""Deterministic directional-material preflight for exact staged image evidence."""

from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from .models import (
    DirectionalMappingEvidenceV01,
    DirectionalMaterialPreflightV01,
    DirectionalTextureThresholdsV01,
    FidelityArtifact,
)
from .service import publish, read_artifact


def _sample_image(content: bytes) -> Image.Image:
    """Decode and bound one image to a deterministic maximum 256-pixel sample."""

    with Image.open(BytesIO(content)) as opened:
        opened.verify()
    with Image.open(BytesIO(content)) as opened:
        image = opened.convert("L")
    if min(image.size) < 8:
        raise ValueError("directional material preflight requires at least 8x8 pixels")
    if max(image.size) > 256:
        scale = 256.0 / max(image.size)
        dimensions = tuple(max(8, round(value * scale)) for value in image.size)
        image = image.resize(dimensions, Image.Resampling.LANCZOS)
    return image


def _gradient_energy(image: Image.Image) -> tuple[float, float]:
    """Measure normalized neighbor-change energy on both image axes."""

    horizontal = ImageChops.difference(
        image.crop((1, 0, image.width, image.height)),
        image.crop((0, 0, image.width - 1, image.height)),
    )
    vertical = ImageChops.difference(
        image.crop((0, 1, image.width, image.height)),
        image.crop((0, 0, image.width, image.height - 1)),
    )
    return (
        float(ImageStat.Stat(horizontal).mean[0]) / 255.0,
        float(ImageStat.Stat(vertical).mean[0]) / 255.0,
    )


def _cross_axis_profile(image: Image.Image, fibre_axis: str) -> list[float]:
    """Average along fibres so the remaining profile describes cross-grain variation."""

    pixels = image.load()
    if fibre_axis == "x":
        return [
            sum(float(pixels[x, y]) for x in range(image.width)) / image.width
            for y in range(image.height)
        ]
    return [
        sum(float(pixels[x, y]) for y in range(image.height)) / image.height
        for x in range(image.width)
    ]


def _dominant_harmonic_fraction(profile: list[float]) -> float:
    """Measure whether one Fourier harmonic dominates the cross-grain signal."""

    mean = sum(profile) / len(profile)
    centered = [value - mean for value in profile]
    energies = []
    for frequency in range(1, len(profile) // 2 + 1):
        real = sum(
            value * math.cos(math.tau * frequency * index / len(profile))
            for index, value in enumerate(centered)
        )
        imaginary = sum(
            value * math.sin(math.tau * frequency * index / len(profile))
            for index, value in enumerate(centered)
        )
        energies.append(real * real + imaginary * imaginary)
    total = sum(energies)
    return max(energies, default=0.0) / total if total > 1.0e-12 else 0.0


def evaluate_directional_material(
    root: Path,
    *,
    job_id: str,
    preflight_id: str,
    image: FidelityArtifact,
    mapping_evidence: FidelityArtifact,
    expected_fibre_axis: str,
    coordinate_domain: str,
    sampled_tile_span: float,
    thresholds: DirectionalTextureThresholdsV01 | None = None,
) -> DirectionalMaterialPreflightV01:
    """Rehash a staged tile and classify only local direction, periodicity, and sampling."""

    mapping = DirectionalMappingEvidenceV01.model_validate_json(
        read_artifact(root, mapping_evidence)
    )
    if mapping.job_id != job_id:
        raise ValueError("directional mapping evidence belongs to another job")
    read_artifact(root, mapping.texture_manifest)
    read_artifact(root, mapping.coordinate_binding)
    if mapping.coordinate_domain != coordinate_domain:
        raise ValueError("coordinate domain differs from exact mapping evidence")
    if abs(mapping.sampled_tile_span - sampled_tile_span) > 1.0e-9:
        raise ValueError("sampled tile span differs from exact mapping evidence")
    sampled = _sample_image(read_artifact(root, image))
    limits = thresholds or DirectionalTextureThresholdsV01()
    gradient_x, gradient_y = _gradient_energy(sampled)
    total = gradient_x + gradient_y
    anisotropy = abs(gradient_x - gradient_y) / total if total > 1.0e-12 else 0.0
    if total < limits.minimum_gradient_energy:
        detected = "none"
    elif anisotropy < limits.minimum_anisotropy:
        detected = "ambiguous"
    else:
        detected = "x" if gradient_x < gradient_y else "y"
    dominance = _dominant_harmonic_fraction(
        _cross_axis_profile(sampled, expected_fibre_axis)
    )
    findings = []
    if total < limits.minimum_gradient_energy:
        findings.append("insufficient_spatial_variation")
    elif anisotropy < limits.minimum_anisotropy:
        findings.append("direction_ambiguous")
    elif detected != expected_fibre_axis:
        findings.append("direction_mismatch")
    if dominance > limits.maximum_dominant_harmonic_fraction:
        findings.append("single_period_dominance")
    if sampled_tile_span < limits.minimum_sampled_tile_span:
        findings.append("insufficient_sampled_span")
    return DirectionalMaterialPreflightV01(
        job_id=job_id,
        preflight_id=preflight_id,
        image=image,
        mapping_evidence=mapping_evidence,
        expected_fibre_axis=expected_fibre_axis,
        coordinate_domain=coordinate_domain,
        sampled_tile_span=sampled_tile_span,
        sampled_resolution=sampled.size,
        thresholds=limits,
        gradient_x=round(gradient_x, 9),
        gradient_y=round(gradient_y, 9),
        anisotropy=round(anisotropy, 9),
        detected_fibre_axis=detected,
        dominant_harmonic_fraction=round(dominance, 9),
        finding_codes=findings,
        outcome="review_required" if findings else "preflight_passed",
    )


def publish_directional_material_preflight(
    root: Path,
    *,
    output: Path,
    job_id: str,
    preflight_id: str,
    image: FidelityArtifact,
    mapping_evidence: FidelityArtifact,
    expected_fibre_axis: str,
    coordinate_domain: str,
    sampled_tile_span: float,
    thresholds: DirectionalTextureThresholdsV01 | None = None,
) -> FidelityArtifact:
    """Publish one append-only preflight while granting no quality or write authority."""

    result = evaluate_directional_material(
        root,
        job_id=job_id,
        preflight_id=preflight_id,
        image=image,
        mapping_evidence=mapping_evidence,
        expected_fibre_axis=expected_fibre_axis,
        coordinate_domain=coordinate_domain,
        sampled_tile_span=sampled_tile_span,
        thresholds=thresholds,
    )
    return publish(root, output, result)
