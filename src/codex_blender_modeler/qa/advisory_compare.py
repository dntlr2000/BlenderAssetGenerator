from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from .models import QAFinding

_NORMALIZED_SIZE = (96, 96)
_COARSE_SIZE = (8, 8)
_EDGE_THRESHOLD = 32


def _normalized_rgb(path: Path) -> Image.Image:
    """Load one image into a deterministic, orientation-corrected comparison canvas."""

    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    return ImageOps.pad(
        image,
        _NORMALIZED_SIZE,
        method=Image.Resampling.LANCZOS,
        color=(0, 0, 0),
        centering=(0.5, 0.5),
    )


def _edge_pixels(image: Image.Image) -> set[int]:
    """Extract a deterministic thresholded Pillow edge mask without border artifacts."""

    grayscale = ImageOps.grayscale(image)
    edges = grayscale.filter(ImageFilter.FIND_EDGES)
    width, height = edges.size
    pixels = edges.load()
    return {
        y * width + x
        for y in range(1, height - 1)
        for x in range(1, width - 1)
        if int(pixels[x, y]) >= _EDGE_THRESHOLD
    }


def _edge_iou(first: Image.Image, second: Image.Image) -> float:
    """Measure overlap between two coarse edge masks on the normalized canvas."""

    first_edges = _edge_pixels(first)
    second_edges = _edge_pixels(second)
    union = first_edges | second_edges
    if not union:
        return 1.0
    return len(first_edges & second_edges) / len(union)


def _coarse_color_similarity(first: Image.Image, second: Image.Image) -> float:
    """Compare spatial color blocks using normalized mean absolute RGB distance."""

    first_blocks = first.resize(_COARSE_SIZE, Image.Resampling.BOX)
    second_blocks = second.resize(_COARSE_SIZE, Image.Resampling.BOX)
    total = sum(
        abs(first_channel - second_channel)
        for first_pixel, second_pixel in zip(
            first_blocks.getdata(), second_blocks.getdata(), strict=True
        )
        for first_channel, second_channel in zip(first_pixel, second_pixel, strict=True)
    )
    maximum = _COARSE_SIZE[0] * _COARSE_SIZE[1] * 3 * 255
    return max(0.0, 1.0 - total / maximum)


def _coarse_histogram(image: Image.Image) -> list[float]:
    """Collapse each RGB channel into sixteen normalized bins."""

    histogram = image.histogram()
    pixel_count = image.width * image.height
    bins: list[float] = []
    for channel in range(3):
        channel_start = channel * 256
        for bin_index in range(16):
            start = channel_start + bin_index * 16
            bins.append(sum(histogram[start : start + 16]) / pixel_count)
    return bins


def _histogram_similarity(first: Image.Image, second: Image.Image) -> float:
    """Compare global coarse RGB distributions with normalized L1 distance."""

    first_bins = _coarse_histogram(first)
    second_bins = _coarse_histogram(second)
    distance = sum(
        abs(first_value - second_value)
        for first_value, second_value in zip(first_bins, second_bins, strict=True)
    )
    return max(0.0, 1.0 - distance / 6.0)


def _low_confidence(difference: float, advisory_weight: float) -> float:
    """Cap advisory confidence by the configured weight and the hard 0.35 ceiling."""

    base = min(0.35, max(0.15, 0.15 + difference * 0.2))
    return round(min(base, advisory_weight), 6)


def compare_preview_to_generated_target(
    preview_path: Path,
    target_path: Path,
    *,
    advisory_weight: float = 0.15,
) -> list[QAFinding]:
    """Return weighted, non-actionable findings from deterministic advisory comparison."""

    if advisory_weight < 0 or advisory_weight > 1:
        raise ValueError("advisory_weight must be within [0, 1]")

    preview = _normalized_rgb(preview_path)
    target = _normalized_rgb(target_path)
    edge_similarity = _edge_iou(preview, target)
    color_block_similarity = _coarse_color_similarity(preview, target)
    histogram_similarity = _histogram_similarity(preview, target)
    color_similarity = 0.65 * color_block_similarity + 0.35 * histogram_similarity
    overall_similarity = (
        0.45 * edge_similarity
        + 0.35 * color_block_similarity
        + 0.20 * histogram_similarity
    )
    metrics = {
        "advisory_edge_iou": round(edge_similarity, 6),
        "advisory_color_block_similarity": round(color_block_similarity, 6),
        "advisory_histogram_similarity": round(histogram_similarity, 6),
        "advisory_overall_similarity": round(overall_similarity, 6),
        "configured_advisory_weight": round(advisory_weight, 6),
    }
    findings: list[QAFinding] = []
    if edge_similarity < 0.7:
        findings.append(
            QAFinding(
                id="advisory.generated_target.edge_mismatch",
                issue_type="silhouette",
                severity="low",
                description=(
                    "Advisory generated target edges differ from the fixed-camera beauty "
                    "preview; this generated image is not direct reference evidence."
                ),
                evidence_sources=["generated_target"],
                confidence=_low_confidence(1.0 - edge_similarity, advisory_weight),
                metrics=metrics,
                suggestion=None,
            )
        )
    if color_similarity < 0.7:
        findings.append(
            QAFinding(
                id="advisory.generated_target.color_block_mismatch",
                issue_type="color_block",
                severity="low",
                description=(
                    "Advisory generated target color blocks differ from the fixed-camera "
                    "beauty preview; inspect visually before drawing any conclusion."
                ),
                evidence_sources=["generated_target"],
                confidence=_low_confidence(1.0 - color_similarity, advisory_weight),
                metrics=metrics,
                suggestion=None,
            )
        )
    return findings
