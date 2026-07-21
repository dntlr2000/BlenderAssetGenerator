from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from pathlib import Path

from PIL import Image

from ..models import SceneSpec
from .hashing import canonical_model_sha256
from .models import (
    BoundingBoxMetric,
    DirectScoringVersion,
    DirectVisualMetrics,
    QAFinding,
    SemanticDeviation,
    VisualQAReport,
    VisualQARequest,
)
from .semantic_localizer import extract_semantic_bboxes

BBox = tuple[float, float, float, float]

_LEGACY_SILHOUETTE_WEIGHT = 0.75
_LEGACY_GLOBAL_BBOX_WEIGHT = 0.25
_SILHOUETTE_WEIGHT = 0.60
_GLOBAL_BBOX_WEIGHT = 0.15
_SEMANTIC_BBOX_WEIGHT = 0.25
_MIN_SEMANTIC_CONFIDENCE = 0.7


def observed_regions_from_scene_spec(
    scene_spec_path: Path,
    *,
    source_id: str | None = None,
    source_ids: Collection[str] | None = None,
) -> dict[str, tuple[BBox, float]]:
    """Select observed evidence from one explicit source set for semantic comparison."""

    if source_id is not None and source_ids is not None:
        raise ValueError("source_id and source_ids are mutually exclusive")
    allowed_sources = (
        frozenset(source_ids)
        if source_ids is not None
        else (frozenset({source_id}) if source_id is not None else None)
    )

    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    regions: dict[str, tuple[BBox, float]] = {}
    for item in spec.objects:
        evidence = [
            entry
            for entry in item.evidence
            if entry.status == "observed"
            and (allowed_sources is None or entry.source_id in allowed_sources)
        ]
        if evidence:
            selected = max(evidence, key=lambda entry: entry.confidence)
            regions[item.id] = (selected.bbox_norm, selected.confidence)
    return regions


def _load_mask(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    """Load a deterministic binary mask and optionally align it to the render resolution."""

    with Image.open(path) as opened:
        mask = opened.convert("L")
        if size is not None and mask.size != size:
            mask = mask.resize(size, Image.Resampling.NEAREST)
        return mask.point(lambda value: 255 if value >= 128 else 0)


def _mask_bbox(mask: Image.Image) -> BBox | None:
    """Return a normalized foreground bounding box for one binary image."""

    bbox = mask.getbbox()
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    width, height = mask.size
    return (left / width, top / height, right / width, bottom / height)


def _bbox_metric(reference: BBox, rendered: BBox | None) -> BoundingBoxMetric:
    """Calculate normalized center and size errors between two image-space boxes."""

    if rendered is None:
        return BoundingBoxMetric(
            reference_bbox_norm=reference,
            rendered_bbox_norm=None,
        )
    ref_center = ((reference[0] + reference[2]) / 2, (reference[1] + reference[3]) / 2)
    out_center = ((rendered[0] + rendered[2]) / 2, (rendered[1] + rendered[3]) / 2)
    ref_size = (reference[2] - reference[0], reference[3] - reference[1])
    out_size = (rendered[2] - rendered[0], rendered[3] - rendered[1])
    center_error = math.dist(ref_center, out_center) / math.sqrt(2)
    size_error = math.dist(ref_size, out_size) / math.sqrt(2)
    return BoundingBoxMetric(
        reference_bbox_norm=reference,
        rendered_bbox_norm=rendered,
        center_error_norm=round(center_error, 6),
        size_error_norm=round(size_error, 6),
    )


def _silhouette_metrics(reference: Image.Image, rendered: Image.Image) -> tuple[float, float]:
    """Compute intersection-over-union and union image fraction for two masks."""

    reference_values = [value > 0 for value in reference.getdata()]
    rendered_values = [value > 0 for value in rendered.getdata()]
    intersection = sum(a and b for a, b in zip(reference_values, rendered_values, strict=True))
    union = sum(a or b for a, b in zip(reference_values, rendered_values, strict=True))
    if union == 0:
        return 1.0, 0.0
    return round(intersection / union, 6), round(union / len(reference_values), 6)


def _severity(error: float) -> str:
    """Map normalized image-space error to a stable finding severity."""

    if error >= 0.2:
        return "high"
    if error >= 0.1:
        return "medium"
    return "low"


def _bbox_similarity(metric: BoundingBoxMetric) -> float:
    """Convert one center-and-size bbox deviation into a bounded similarity score."""

    if (
        metric.rendered_bbox_norm is None
        or metric.center_error_norm is None
        or metric.size_error_norm is None
    ):
        return 0.0
    combined_error = metric.center_error_norm + metric.size_error_norm
    return max(0.0, 1.0 - min(1.0, combined_error))


def _semantic_group_key(target_id: str) -> str:
    """Map nested semantic IDs to one deterministic capped scoring group."""

    parts = target_id.split(".")
    if len(parts) >= 2 and parts[0] == "island":
        return ".".join(parts[:2])
    return parts[0]


def _semantic_bbox_score(deviations: list[SemanticDeviation]) -> float | None:
    """Average reliable semantic similarities hierarchically so each group has one vote."""

    grouped: dict[str, list[SemanticDeviation]] = {}
    for deviation in deviations:
        if deviation.confidence < _MIN_SEMANTIC_CONFIDENCE:
            continue
        grouped.setdefault(_semantic_group_key(deviation.target_id), []).append(deviation)
    if not grouped:
        return None

    weighted_group_score = 0.0
    group_confidence_total = 0.0
    for group_id in sorted(grouped):
        members = grouped[group_id]
        member_confidence_total = sum(item.confidence for item in members)
        group_score = sum(
            item.confidence * _bbox_similarity(item.metric) for item in members
        ) / member_confidence_total
        group_confidence = max(item.confidence for item in members)
        weighted_group_score += group_confidence * group_score
        group_confidence_total += group_confidence
    return weighted_group_score / group_confidence_total


def _overall_direct_score(
    silhouette_iou: float,
    global_bbox: BoundingBoxMetric,
    semantic_deviations: list[SemanticDeviation],
) -> tuple[float, DirectScoringVersion]:
    """Blend direct-reference components and identify the exact scoring contract used."""

    global_bbox_score = _bbox_similarity(global_bbox)
    semantic_score = _semantic_bbox_score(semantic_deviations)
    if semantic_score is None:
        score = (
            _LEGACY_SILHOUETTE_WEIGHT * silhouette_iou
            + _LEGACY_GLOBAL_BBOX_WEIGHT * global_bbox_score
        )
        scoring_version: DirectScoringVersion = "legacy_bbox_v1"
    else:
        score = (
            _SILHOUETTE_WEIGHT * silhouette_iou
            + _GLOBAL_BBOX_WEIGHT * global_bbox_score
            + _SEMANTIC_BBOX_WEIGHT * semantic_score
        )
        scoring_version = "semantic_bbox_v2"
    return round(max(0.0, min(1.0, score)), 6), scoring_version


def compare_reference_to_render(
    request: VisualQARequest,
    *,
    silhouette_path: Path,
    object_id_path: Path | None = None,
    object_id_colors: Mapping[str, str] | None = None,
    observed_regions: Mapping[str, tuple[BBox, float]] | None = None,
) -> VisualQAReport:
    """Compare reference evidence directly to shader-independent fixed-camera passes."""

    rendered_mask = _load_mask(silhouette_path)
    reference_mask = _load_mask(Path(request.reference_mask_path), rendered_mask.size)
    silhouette_iou, union_fraction = _silhouette_metrics(reference_mask, rendered_mask)
    reference_bbox = _mask_bbox(reference_mask)
    if reference_bbox is None:
        raise ValueError("reference content mask has no foreground pixels")
    rendered_bbox = _mask_bbox(rendered_mask)
    global_bbox = _bbox_metric(reference_bbox, rendered_bbox)

    rendered_regions: dict[str, BBox | None] = {}
    if object_id_path is not None and object_id_colors:
        rendered_regions = extract_semantic_bboxes(object_id_path, object_id_colors)

    semantic_deviations: list[SemanticDeviation] = []
    findings: list[QAFinding] = []
    if silhouette_iou < 0.85:
        findings.append(
            QAFinding(
                id="direct.global_silhouette",
                issue_type="silhouette",
                severity=_severity(1.0 - silhouette_iou),
                description="Rendered global silhouette differs from the reference content mask.",
                evidence_sources=["direct_reference"],
                confidence=0.9,
                metrics={"silhouette_iou": silhouette_iou},
            )
        )

    for target_id, (reference_region, confidence) in sorted((observed_regions or {}).items()):
        metric = _bbox_metric(reference_region, rendered_regions.get(target_id))
        semantic_deviations.append(
            SemanticDeviation(target_id=target_id, metric=metric, confidence=confidence)
        )
        if metric.rendered_bbox_norm is None:
            findings.append(
                QAFinding(
                    id=f"direct.missing.{target_id}",
                    target_ids=[target_id],
                    issue_type="missing",
                    severity="high",
                    description=(
                        f"Observed semantic region {target_id} is absent from object-ID pass."
                    ),
                    evidence_sources=["direct_reference"],
                    confidence=confidence,
                )
            )
            continue
        if metric.center_error_norm is not None and metric.center_error_norm > 0.05:
            findings.append(
                QAFinding(
                    id=f"direct.position.{target_id}",
                    target_ids=[target_id],
                    issue_type="position",
                    severity=_severity(metric.center_error_norm),
                    description=f"Rendered center for {target_id} differs from observed evidence.",
                    evidence_sources=["direct_reference"],
                    confidence=confidence,
                    metrics={"center_error_norm": metric.center_error_norm},
                )
            )
        if metric.size_error_norm is not None and metric.size_error_norm > 0.08:
            findings.append(
                QAFinding(
                    id=f"direct.proportion.{target_id}",
                    target_ids=[target_id],
                    issue_type="proportion",
                    severity=_severity(metric.size_error_norm),
                    description=f"Rendered image-space size for {target_id} differs from evidence.",
                    evidence_sources=["direct_reference"],
                    confidence=confidence,
                    metrics={"size_error_norm": metric.size_error_norm},
                )
            )

    direct_score, scoring_version = _overall_direct_score(
        silhouette_iou,
        global_bbox,
        semantic_deviations,
    )
    metrics = DirectVisualMetrics(
        scoring_version=scoring_version,
        silhouette_iou=silhouette_iou,
        silhouette_union_fraction=union_fraction,
        global_bbox=global_bbox,
        semantic_deviations=semantic_deviations,
        overall_direct_score=direct_score,
    )
    return VisualQAReport(
        job_id=request.job_id,
        run_id=request.run_id,
        request_sha256=canonical_model_sha256(request),
        camera_fingerprint=request.camera_fingerprint,
        direct_metrics=metrics,
        findings=findings,
        generated_target_status=(
            "pending" if request.include_generated_target else "not_requested"
        ),
        warnings=(
            ["Generated target is pending and cannot affect direct-reference metrics."]
            if request.include_generated_target
            else []
        ),
    )
