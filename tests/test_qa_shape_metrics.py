from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.qa.semantic_shape import (
    compare_semantic_masks,
    semantic_shape_similarity_score,
    undirected_axis_error_degrees,
)


def _rectangle(
    box: tuple[int, int, int, int],
    *,
    size: tuple[int, int] = (64, 64),
) -> Image.Image:
    """Create one deterministic binary rectangle fixture."""

    image = Image.new("L", size, 0)
    ImageDraw.Draw(image).rectangle(box, fill=255)
    return image


def test_identical_semantic_masks_score_every_core_shape_metric() -> None:
    """Identical elongated masks produce perfect overlap, boundary, and axis evidence."""

    mask = _rectangle((10, 24, 53, 39))

    metrics = compare_semantic_masks(mask, mask, semantic_id="weapon.receiver")

    assert metrics.status == "scored"
    assert metrics.mask_iou == pytest.approx(1.0)
    assert metrics.centroid_error_norm == pytest.approx(0.0)
    assert metrics.area_ratio == pytest.approx(1.0)
    assert metrics.boundary_f_score == pytest.approx(1.0)
    assert metrics.symmetric_contour_distance_norm == pytest.approx(0.0)
    assert metrics.oriented_axis_scorable is True
    assert metrics.undirected_axis_error_deg == pytest.approx(0.0)
    assert semantic_shape_similarity_score(metrics) == pytest.approx(1.0)


def test_translation_reduces_overlap_and_reports_centroid_and_contour_error() -> None:
    """A translated part remains measurable while exposing positional shape error."""

    reference = _rectangle((8, 25, 35, 38))
    rendered = _rectangle((22, 25, 49, 38))

    metrics = compare_semantic_masks(
        reference,
        rendered,
        semantic_id="weapon.trigger",
        boundary_tolerance_px=1,
    )

    assert metrics.mask_iou is not None and metrics.mask_iou < 0.5
    assert metrics.centroid_error_norm is not None and metrics.centroid_error_norm > 0.1
    assert metrics.area_ratio == pytest.approx(1.0)
    assert metrics.boundary_f_score is not None and metrics.boundary_f_score < 0.6
    assert (
        metrics.symmetric_contour_distance_norm is not None
        and metrics.symmetric_contour_distance_norm > 0
    )


def test_area_ratio_reports_a_larger_rendered_semantic_part() -> None:
    """Rendered semantic area is expressed relative to exact reference pixels."""

    reference = _rectangle((20, 28, 43, 35))
    rendered = _rectangle((16, 24, 47, 39))

    metrics = compare_semantic_masks(reference, rendered, semantic_id="weapon.magazine")

    expected_ratio = metrics.rendered_foreground_pixels / metrics.reference_foreground_pixels
    assert metrics.area_ratio == pytest.approx(expected_ratio)
    assert metrics.area_ratio is not None and metrics.area_ratio > 2.0


def test_pca_axis_detects_undirected_rotation() -> None:
    """Elongated masks expose camera-independent 180-degree orientation error."""

    reference = _rectangle((12, 28, 51, 35))
    rendered = reference.rotate(45, resample=Image.Resampling.NEAREST)

    metrics = compare_semantic_masks(reference, rendered, semantic_id="weapon.barrel")

    assert metrics.oriented_axis_scorable is True
    assert metrics.undirected_axis_error_deg == pytest.approx(45.0, abs=2.0)
    assert undirected_axis_error_degrees(5.0, 175.0) == pytest.approx(10.0)
    assert undirected_axis_error_degrees(0.0, 180.0) == pytest.approx(0.0)


def test_nearly_isotropic_mask_keeps_axis_explicitly_unscorable() -> None:
    """A circular mask does not fabricate a stable PCA orientation."""

    mask = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(mask).ellipse((16, 16, 47, 47), fill=255)

    metrics = compare_semantic_masks(mask, mask, semantic_id="weapon.round_detail")

    assert metrics.status == "scored"
    assert metrics.oriented_axis_scorable is False
    assert metrics.reference_axis_deg is None
    assert metrics.undirected_axis_error_deg is None
    assert any("insufficiently elongated" in value for value in metrics.limitations)


def test_empty_semantic_mask_is_unscorable_instead_of_an_invented_zero() -> None:
    """Missing foreground produces an honest unscorable result."""

    empty = Image.new("L", (32, 32), 0)
    visible = _rectangle((8, 8, 15, 15), size=(32, 32))

    metrics = compare_semantic_masks(empty, visible, semantic_id="weapon.trigger")

    assert metrics.status == "unscorable"
    assert metrics.mask_iou is None
    assert semantic_shape_similarity_score(metrics) is None
    assert "reference semantic mask has no foreground pixels" in metrics.limitations


def test_semantic_masks_must_use_one_comparison_resolution() -> None:
    """Cross-resolution mask comparison fails instead of silently resampling evidence."""

    with pytest.raises(ValueError, match="same resolution"):
        compare_semantic_masks(
            Image.new("L", (32, 32), 255),
            Image.new("L", (64, 64), 255),
            semantic_id="weapon.body",
        )
