"""Per-semantic observed-mask metrics for Integrated Quality 0.2."""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

from PIL import Image

from .v02_contour_metrics import compare_contours_v02
from .v02_models import (
    ContourEvidenceBindingV02,
    SemanticEvidenceBindingV02,
    SemanticMetricV02,
)

MaskInput: TypeAlias = Image.Image | Path


def _load_binary_mask(value: MaskInput) -> tuple[Image.Image, bytearray]:
    """Load an owned grayscale image and its deterministic binary pixel mask."""

    if isinstance(value, Image.Image):
        image = value.convert("L")
    else:
        with Image.open(value) as source:
            image = source.convert("L")
    return image, bytearray(1 if pixel >= 128 else 0 for pixel in image.tobytes())


def compare_semantic_masks_v02(
    reference: MaskInput,
    candidate: MaskInput,
    *,
    reference_evidence: SemanticEvidenceBindingV02,
    candidate_evidence_id: str,
    candidate_artifact_sha256: str,
    candidate_camera_sha256: str,
    critical: bool,
    boundary_tolerance_diagonal_fraction: float = 0.005,
) -> SemanticMetricV02:
    """Compare one semantic while preserving registration-derived authority."""

    reference_image, reference_pixels = _load_binary_mask(reference)
    candidate_image, candidate_pixels = _load_binary_mask(candidate)
    if reference_image.size != candidate_image.size:
        raise ValueError("semantic masks must use the same resolution")
    contour_binding = ContourEvidenceBindingV02(
        evidence_id=reference_evidence.evidence_id,
        origin=(
            "observed"
            if reference_evidence.origin == "registered_observed"
            else reference_evidence.origin
            if reference_evidence.origin
            in {"inferred", "generated", "provider", "unavailable"}
            else "inferred"
        ),
        authority=reference_evidence.authority,
        artifact_path=reference_evidence.artifact_path,
        artifact_sha256=reference_evidence.artifact_sha256,
        camera_sha256=reference_evidence.camera_sha256,
    )
    contour = compare_contours_v02(
        reference_image,
        candidate_image,
        reference_evidence=contour_binding,
        candidate_evidence_id=candidate_evidence_id,
        candidate_artifact_sha256=candidate_artifact_sha256,
        candidate_camera_sha256=candidate_camera_sha256,
        metric_id=f"semantic.{reference_evidence.semantic_id}.contour_v02",
        boundary_tolerance_diagonal_fraction=boundary_tolerance_diagonal_fraction,
    )
    reference_count = sum(reference_pixels)
    candidate_count = sum(candidate_pixels)
    limitations: list[str] = []
    if reference_evidence.authority == "unavailable":
        limitations.append("semantic reference evidence is unavailable")
    if reference_count == 0:
        limitations.append("semantic reference mask has no observed foreground")
    if limitations:
        return SemanticMetricV02(
            metric_id=f"semantic.{reference_evidence.semantic_id}.v02",
            semantic_id=reference_evidence.semantic_id,
            critical=critical,
            authority=reference_evidence.authority,
            reference_evidence=reference_evidence,
            candidate_evidence_id=candidate_evidence_id,
            status="unscorable",
            contour=contour,
            limitations=limitations,
        )
    intersection = sum(
        1
        for reference_value, candidate_value in zip(
            reference_pixels,
            candidate_pixels,
            strict=True,
        )
        if reference_value and candidate_value
    )
    union = reference_count + candidate_count - intersection
    mask_iou = intersection / union
    missing = candidate_count == 0
    if missing:
        limitations.append("candidate semantic mask has no foreground")
    if reference_evidence.authority == "advisory":
        limitations.append(
            "unregistered, inferred, generated, or provider semantic evidence is advisory"
        )
    return SemanticMetricV02(
        metric_id=f"semantic.{reference_evidence.semantic_id}.v02",
        semantic_id=reference_evidence.semantic_id,
        critical=critical,
        authority=reference_evidence.authority,
        reference_evidence=reference_evidence,
        candidate_evidence_id=candidate_evidence_id,
        status="scored",
        mask_iou=mask_iou,
        missing_candidate=missing,
        contour=contour,
        limitations=limitations,
    )
