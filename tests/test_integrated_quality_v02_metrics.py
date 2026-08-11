"""Focused metric tests for the parallel Integrated Quality 0.2 slice."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from codex_blender_modeler.integrated_quality.v02_advisory_metrics import (
    build_advisory_metric_v02,
)
from codex_blender_modeler.integrated_quality.v02_contour_metrics import (
    compare_contours_v02,
)
from codex_blender_modeler.integrated_quality.v02_landmark_metrics import (
    evaluate_landmark_v02,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
    LandmarkEvidenceV02,
    MultiviewObservationV02,
    SemanticEvidenceBindingV02,
)
from codex_blender_modeler.integrated_quality.v02_multiview_metrics import (
    evaluate_multiview_v02,
)
from codex_blender_modeler.integrated_quality.v02_semantic_metrics import (
    compare_semantic_masks_v02,
)

FIXTURE = Path(__file__).parent / "fixtures" / "integrated_quality_v02" / "masks.json"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _image(rows: list[str]) -> Image.Image:
    """Convert compact checked-in mask rows to one binary Pillow image."""

    width = len(rows[0])
    image = Image.new("L", (width, len(rows)), 0)
    image.putdata([255 if value == "#" else 0 for row in rows for value in row])
    return image


def _rectangle(size: int, shift: int = 0) -> Image.Image:
    """Build one scale-controlled rectangle mask for normalized metric tests."""

    image = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(image)
    margin = size // 4
    draw.rectangle(
        (margin + shift, margin, size - margin - 1 + shift, size - margin - 1),
        fill=255,
    )
    return image


def _contour_evidence(authority: str = "authoritative") -> ContourEvidenceBindingV02:
    """Create one exact observed contour evidence binding."""

    return ContourEvidenceBindingV02(
        evidence_id="evidence.contour.reference",
        origin="observed" if authority == "authoritative" else "generated",
        authority=authority,
        artifact_path="analysis/masks/reference.png",
        artifact_sha256=SHA_A,
        camera_sha256=SHA_B,
    )


def _semantic_evidence(
    semantic_id: str = "asset.body",
    *,
    registered: bool = True,
) -> SemanticEvidenceBindingV02:
    """Create registered authoritative or unregistered advisory semantic evidence."""

    return SemanticEvidenceBindingV02(
        evidence_id=f"evidence.semantic.{semantic_id}",
        semantic_id=semantic_id,
        origin="registered_observed" if registered else "observed",
        authority="authoritative" if registered else "advisory",
        artifact_path=f"analysis/masks/{semantic_id}.png",
        artifact_sha256=SHA_A,
        camera_sha256=SHA_B,
        registration_receipt_sha256=SHA_C if registered else None,
    )


def test_exact_and_misaligned_contours_use_exact_edt_chamfer() -> None:
    """Report exact equality and a positive full-boundary EDT Chamfer after translation."""

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    exact = compare_contours_v02(
        _image(payload["exact"]["reference"]),
        _image(payload["exact"]["candidate"]),
        reference_evidence=_contour_evidence(),
        candidate_evidence_id="evidence.contour.exact",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        boundary_tolerance_diagonal_fraction=0,
    )
    shifted = compare_contours_v02(
        _image(payload["misaligned"]["reference"]),
        _image(payload["misaligned"]["candidate"]),
        reference_evidence=_contour_evidence(),
        candidate_evidence_id="evidence.contour.shifted",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        boundary_tolerance_diagonal_fraction=0,
    )
    assert exact.boundary_f_score == 1.0
    assert exact.edge_distance_transform_chamfer_norm == 0.0
    assert shifted.boundary_f_score is not None and shifted.boundary_f_score < 1.0
    assert (
        shifted.edge_distance_transform_chamfer_norm is not None
        and shifted.edge_distance_transform_chamfer_norm > 0
    )
    assert shifted.distance_transform_method == "exact_squared_euclidean_v1"
    assert "symmetric_contour_distance_norm" not in type(shifted).model_fields


def test_contour_distance_and_tolerance_are_scale_normalized() -> None:
    """Keep the same relative translation comparable at two image resolutions."""

    small = compare_contours_v02(
        _rectangle(32),
        _rectangle(32, shift=2),
        reference_evidence=_contour_evidence(),
        candidate_evidence_id="candidate.small",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        boundary_tolerance_diagonal_fraction=0.02,
    )
    large = compare_contours_v02(
        _rectangle(64),
        _rectangle(64, shift=4),
        reference_evidence=_contour_evidence(),
        candidate_evidence_id="candidate.large",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        boundary_tolerance_diagonal_fraction=0.02,
    )
    assert small.boundary_tolerance_diagonal_fraction == 0.02
    assert large.boundary_tolerance_diagonal_fraction == 0.02
    assert small.edge_distance_transform_chamfer_norm == pytest.approx(
        large.edge_distance_transform_chamfer_norm,
        abs=0.003,
    )


def test_edt_chamfer_matches_exact_euclidean_distance() -> None:
    """Match a known 3-4-5 pixel offset rather than a sampled contour approximation."""

    reference = Image.new("L", (8, 8), 0)
    candidate = Image.new("L", (8, 8), 0)
    reference.putpixel((1, 1), 255)
    candidate.putpixel((4, 5), 255)
    metric = compare_contours_v02(
        reference,
        candidate,
        reference_evidence=_contour_evidence(),
        candidate_evidence_id="candidate.single-pixel",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        boundary_tolerance_diagonal_fraction=0,
    )
    assert metric.edge_distance_transform_chamfer_norm == pytest.approx(
        5.0 / math.hypot(8, 8)
    )


def test_contour_rejects_cross_camera_comparison() -> None:
    """Fail closed when reference and candidate masks come from different cameras."""

    with pytest.raises(ValueError, match="camera hashes"):
        compare_contours_v02(
            _rectangle(32),
            _rectangle(32),
            reference_evidence=_contour_evidence(),
            candidate_evidence_id="candidate.cross-camera",
            candidate_artifact_sha256=SHA_C,
            candidate_camera_sha256=SHA_C,
        )


def test_contour_rejects_masks_over_the_bounded_pixel_budget() -> None:
    """Bound pure-host distance-transform memory before allocating full image grids."""

    with pytest.raises(ValueError, match="pixel budget"):
        compare_contours_v02(
            _rectangle(32),
            _rectangle(32),
            reference_evidence=_contour_evidence(),
            candidate_evidence_id="candidate.oversized",
            candidate_artifact_sha256=SHA_C,
            candidate_camera_sha256=SHA_B,
            maximum_pixels=100,
        )


def test_only_registered_observed_semantic_evidence_is_authoritative() -> None:
    """Keep an unregistered observed mask advisory and reject a forged authority flag."""

    mask = _rectangle(32)
    registered = compare_semantic_masks_v02(
        mask,
        mask,
        reference_evidence=_semantic_evidence(),
        candidate_evidence_id="candidate.semantic.body",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        critical=True,
    )
    advisory = compare_semantic_masks_v02(
        mask,
        mask,
        reference_evidence=_semantic_evidence(registered=False),
        candidate_evidence_id="candidate.semantic.body.advisory",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        critical=False,
    )
    assert registered.authority == "authoritative"
    assert registered.mask_iou == 1.0
    assert advisory.authority == "advisory"
    with pytest.raises(ValidationError, match="authority"):
        SemanticEvidenceBindingV02(
            evidence_id="forged.semantic",
            semantic_id="asset.body",
            origin="generated",
            authority="authoritative",
            artifact_path="analysis/masks/forged.png",
            artifact_sha256=SHA_A,
            camera_sha256=SHA_B,
        )


def test_missing_critical_semantic_is_scored_as_missing_not_hidden_by_average() -> None:
    """Expose a registered critical part with no candidate pixels as explicit IoU zero."""

    metric = compare_semantic_masks_v02(
        _rectangle(32),
        Image.new("L", (32, 32), 0),
        reference_evidence=_semantic_evidence("asset.trigger"),
        candidate_evidence_id="candidate.semantic.trigger",
        candidate_artifact_sha256=SHA_C,
        candidate_camera_sha256=SHA_B,
        critical=True,
    )
    assert metric.status == "scored"
    assert metric.mask_iou == 0.0
    assert metric.missing_candidate is True
    assert metric.contour.status == "unscorable"


def test_missing_landmark_is_unscorable_and_inferred_landmark_is_advisory() -> None:
    """Never invent a missing candidate landmark or grant inferred evidence authority."""

    missing = evaluate_landmark_v02(
        LandmarkEvidenceV02(
            landmark_id="landmark.trigger",
            semantic_id="asset.trigger",
            origin="observed",
            authority="authoritative",
            source_position_norm=(0.5, 0.5),
            source_artifact_sha256=SHA_A,
            camera_sha256=SHA_B,
            confidence=1.0,
        )
    )
    inferred = evaluate_landmark_v02(
        LandmarkEvidenceV02(
            landmark_id="landmark.inferred",
            semantic_id="asset.body",
            origin="inferred",
            authority="advisory",
            source_position_norm=(0.25, 0.25),
            candidate_position_norm=(0.5, 0.5),
            source_artifact_sha256=SHA_A,
            candidate_artifact_sha256=SHA_B,
            camera_sha256=SHA_C,
            confidence=0.4,
        )
    )
    assert missing.status == "unscorable"
    assert missing.reprojection_error_norm is None
    assert inferred.status == "scored"
    assert inferred.authority == "advisory"


def test_multiview_and_provider_metrics_preserve_authority_boundaries() -> None:
    """Aggregate actual Blender views while excluding generated views from authority."""

    observations = [
        MultiviewObservationV02(
            view_id=f"view.{name}",
            origin="actual_blender",
            authority="authoritative",
            artifact_path=f"qa/views/{name}.png",
            artifact_sha256=SHA_A,
            camera_sha256=SHA_B,
            silhouette_stability=score,
            semantic_placement_score=score,
        )
        for name, score in (("front", 0.9), ("side", 0.8))
    ]
    observations.append(
        MultiviewObservationV02(
            view_id="view.generated",
            origin="generated",
            authority="advisory",
            artifact_path="qa/views/generated.png",
            artifact_sha256=SHA_B,
            camera_sha256=SHA_C,
            silhouette_stability=1.0,
            semantic_placement_score=1.0,
        )
    )
    multiview = evaluate_multiview_v02(observations)
    unavailable_depth = build_advisory_metric_v02(
        metric_id="advisory.depth",
        kind="estimated_depth",
        value=None,
        confidence=0,
        unavailable_reason="provider was not configured",
    )
    scored_normal = build_advisory_metric_v02(
        metric_id="advisory.normal",
        kind="estimated_normal",
        value=0.95,
        confidence=0.7,
        provider="fixture_provider",
        model="fixture_normal_model",
        version="1.0",
        artifact_sha256=SHA_C,
    )
    generated_only = evaluate_multiview_v02([observations[-1]])
    assert multiview.authoritative_view_count == 2
    assert multiview.minimum_silhouette_stability == 0.8
    assert multiview.mean_semantic_placement_score == pytest.approx(0.85)
    assert unavailable_depth.status == "unscorable"
    assert unavailable_depth.authoritative is False
    assert scored_normal.status == "scored"
    assert scored_normal.authoritative is False
    assert generated_only.status == "unscorable"
