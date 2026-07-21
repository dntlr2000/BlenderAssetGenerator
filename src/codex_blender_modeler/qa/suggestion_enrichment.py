from __future__ import annotations

import math

from ..models import ObjectSpec, SceneSpec, Vec3
from .models import BoundingBoxMetric, QAFinding, SuggestedEdit, VisualQAReport

_MIN_DIRECT_CONFIDENCE = 0.7
_CONFIDENCE_DISCOUNT = 0.75
_MAX_CENTER_ERROR_NORM = 0.2
_MAX_IMAGE_SHIFT_NORM = 0.04
_MAX_WORLD_SHIFT_FRACTION = 0.05
_MIN_UNIFORM_RATIO = 0.67
_MAX_UNIFORM_RATIO = 1.5
_MAX_AXIS_RATIO_DIVERGENCE = 1.25
_MIN_SCALE_STEP = 0.9
_MAX_SCALE_STEP = 1.1
_EPSILON = 1e-9
_MIN_GROUP_OBSERVED_COMPONENTS = 2
_MIN_GROUP_OBSERVED_COVERAGE = 0.6
_MIN_GROUP_DIRECTION_COSINE = 0.5
_GROUP_ROOT_ALLOWLIST = frozenset({"island"})
_GROUP_FINDING_PREFIX = "direct.group_position."
_SAFE_PATHS = {
    ("transform", "location"),
    ("transform", "scale"),
}


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp one numeric correction to a closed safety interval."""

    return max(minimum, min(maximum, value))


def _subtract(left: Vec3, right: Vec3) -> Vec3:
    """Subtract one three-dimensional vector from another."""

    return tuple(a - b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _length(value: Vec3) -> float:
    """Return the Euclidean length of one three-dimensional vector."""

    return math.sqrt(sum(component * component for component in value))


def _normalize(value: Vec3) -> Vec3 | None:
    """Normalize a vector or return None when its direction is ambiguous."""

    magnitude = _length(value)
    if magnitude <= _EPSILON:
        return None
    return tuple(component / magnitude for component in value)  # type: ignore[return-value]


def _cross(left: Vec3, right: Vec3) -> Vec3:
    """Return the right-handed cross product of two three-dimensional vectors."""

    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _camera_screen_basis(spec: SceneSpec) -> tuple[Vec3, Vec3] | None:
    """Derive camera screen-right and screen-up vectors for an unrolled ORTHO camera."""

    camera = spec.camera
    if camera.projection != "ORTHO":
        return None
    forward = _normalize(_subtract(camera.target, camera.location))
    if forward is None:
        return None
    right = _normalize(_cross(forward, (0.0, 0.0, 1.0)))
    if right is None:
        # A vertical look direction has no recoverable roll in the current CameraSpec.
        return None
    up = _normalize(_cross(right, forward))
    if up is None:
        return None
    return right, up


def _valid_bbox(bbox: tuple[float, float, float, float] | None) -> bool:
    """Return whether a normalized bounding box is finite, bounded, and non-empty."""

    if bbox is None or not all(math.isfinite(value) and 0 <= value <= 1 for value in bbox):
        return False
    return bbox[2] > bbox[0] and bbox[3] > bbox[1]


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Return the normalized image-space center of one bounding box."""

    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _bbox_size(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Return the normalized image-space width and height of one bounding box."""

    return (bbox[2] - bbox[0], bbox[3] - bbox[1])


def _bbox_union(
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    """Return the smallest normalized box containing every supplied component box."""

    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _semantic_group_key(object_id: str) -> str | None:
    """Derive an allow-listed top-level assembly key from two semantic ID segments."""

    segments = object_id.split(".")
    if (
        len(segments) < 2
        or not all(segments[:2])
        or segments[0] not in _GROUP_ROOT_ALLOWLIST
    ):
        return None
    return ".".join(segments[:2])


def _safe_suggestion(edit: SuggestedEdit) -> SuggestedEdit | None:
    """Keep only the two host-approved transform paths emitted by this enrichment layer."""

    return edit if tuple(edit.path) in _SAFE_PATHS else None


def _image_center_displacement(
    reference: tuple[float, float, float, float],
    rendered: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    """Return screen-right, screen-up, and normalized magnitude for one bbox center error."""

    reference_center = _bbox_center(reference)
    rendered_center = _bbox_center(rendered)
    delta_x = reference_center[0] - rendered_center[0]
    delta_up = rendered_center[1] - reference_center[1]
    center_error = math.hypot(delta_x, delta_up) / math.sqrt(2)
    return delta_x, delta_up, center_error


def _direction_agrees(
    expected: tuple[float, float],
    actual: tuple[float, float],
) -> bool:
    """Require one component center correction to agree with the group union direction."""

    expected_length = math.hypot(*expected)
    actual_length = math.hypot(*actual)
    if expected_length <= _EPSILON or actual_length <= _EPSILON:
        return False
    cosine = (
        expected[0] * actual[0] + expected[1] * actual[1]
    ) / (expected_length * actual_length)
    return cosine >= _MIN_GROUP_DIRECTION_COSINE


def _bounded_position_displacement(
    spec: SceneSpec,
    reference: tuple[float, float, float, float],
    rendered: tuple[float, float, float, float],
) -> tuple[Vec3, float] | None:
    """Map one safe ORTHO bbox-center error to a bounded shared world displacement."""

    if not _valid_bbox(reference) or not _valid_bbox(rendered):
        return None
    delta_x, delta_up, center_error = _image_center_displacement(reference, rendered)
    if center_error <= _EPSILON or center_error > _MAX_CENTER_ERROR_NORM:
        return None
    basis = _camera_screen_basis(spec)
    if basis is None:
        return None
    right, up = basis
    width, height = spec.camera.resolution
    if width <= 0 or height <= 0:
        return None
    vertical_span = spec.camera.ortho_scale
    horizontal_span = vertical_span * (width / height)
    screen_x = _clamp(delta_x, -_MAX_IMAGE_SHIFT_NORM, _MAX_IMAGE_SHIFT_NORM)
    screen_up = _clamp(delta_up, -_MAX_IMAGE_SHIFT_NORM, _MAX_IMAGE_SHIFT_NORM)
    displacement: Vec3 = tuple(
        right[index] * screen_x * horizontal_span
        + up[index] * screen_up * vertical_span
        for index in range(3)
    )  # type: ignore[assignment]
    magnitude = _length(displacement)
    maximum = vertical_span * _MAX_WORLD_SHIFT_FRACTION
    if magnitude > maximum:
        ratio = maximum / magnitude
        displacement = tuple(component * ratio for component in displacement)  # type: ignore[assignment]
    return displacement, center_error


def _position_edit(
    spec: SceneSpec,
    target: ObjectSpec,
    metric: BoundingBoxMetric,
) -> SuggestedEdit | None:
    """Map a bounded ORTHO image-center error into a world-space location suggestion."""

    rendered = metric.rendered_bbox_norm
    if rendered is None:
        return None
    bounded = _bounded_position_displacement(
        spec,
        metric.reference_bbox_norm,
        rendered,
    )
    if bounded is None:
        return None
    displacement, _center_error = bounded
    value = [
        round(target.transform.location[index] + displacement[index], 6)
        for index in range(3)
    ]
    return _safe_suggestion(
        SuggestedEdit(
            target_type="object",
            target_id=target.id,
            path=["transform", "location"],
            op="set",
            value=value,
        )
    )


def _group_position_findings(
    spec: SceneSpec,
    metrics: dict[str, tuple[BoundingBoxMetric, float]],
) -> list[QAFinding]:
    """Create one coherent direct finding per reliably observed semantic object group."""

    groups: dict[str, list[ObjectSpec]] = {}
    for item in spec.objects:
        group_key = _semantic_group_key(item.id)
        if group_key is not None:
            groups.setdefault(group_key, []).append(item)

    findings: list[QAFinding] = []
    for group_key, members in sorted(groups.items()):
        if len(members) < _MIN_GROUP_OBSERVED_COMPONENTS:
            continue
        # Parent-relative transforms cannot share one world displacement safely.
        if any(member.parent_id is not None for member in members):
            continue
        reliable: list[tuple[BoundingBoxMetric, float]] = []
        for member in members:
            record = metrics.get(member.id)
            if record is None:
                continue
            metric, confidence = record
            if (
                confidence >= _MIN_DIRECT_CONFIDENCE
                and _valid_bbox(metric.reference_bbox_norm)
                and _valid_bbox(metric.rendered_bbox_norm)
            ):
                reliable.append((metric, confidence))
        if len(reliable) < _MIN_GROUP_OBSERVED_COMPONENTS:
            continue
        if len(reliable) / len(members) < _MIN_GROUP_OBSERVED_COVERAGE:
            continue
        reference_union = _bbox_union(
            [metric.reference_bbox_norm for metric, _confidence in reliable]
        )
        rendered_union = _bbox_union(
            [
                metric.rendered_bbox_norm
                for metric, _confidence in reliable
                if metric.rendered_bbox_norm is not None
            ]
        )
        bounded = _bounded_position_displacement(spec, reference_union, rendered_union)
        if bounded is None:
            continue
        displacement, center_error = bounded
        group_delta = _image_center_displacement(reference_union, rendered_union)[:2]
        if any(
            not _direction_agrees(
                group_delta,
                _image_center_displacement(
                    metric.reference_bbox_norm,
                    metric.rendered_bbox_norm,  # type: ignore[arg-type]
                )[:2],
            )
            for metric, _confidence in reliable
        ):
            continue
        confidence = min(value for _metric, value in reliable)
        findings.append(
            QAFinding(
                id=f"{_GROUP_FINDING_PREFIX}{group_key}",
                target_ids=sorted(member.id for member in members),
                issue_type="position",
                severity=("medium" if center_error >= 0.1 else "low"),
                description=(
                    f"Semantic group {group_key} has a coherent reference-to-render "
                    "center offset; move every group member by one shared displacement."
                ),
                evidence_sources=["direct_reference"],
                confidence=round(confidence * _CONFIDENCE_DISCOUNT, 6),
                metrics={
                    "group_center_error_norm": round(center_error, 6),
                    "world_displacement_x": round(displacement[0], 6),
                    "world_displacement_y": round(displacement[1], 6),
                    "world_displacement_z": round(displacement[2], 6),
                    "observed_component_count": float(len(reliable)),
                    "target_component_count": float(len(members)),
                },
            )
        )
    return findings


def _proportion_edit(
    target: ObjectSpec,
    metric: BoundingBoxMetric,
) -> SuggestedEdit | None:
    """Suggest one bounded uniform scale factor when both image axes support it."""

    rendered = metric.rendered_bbox_norm
    reference = metric.reference_bbox_norm
    if not _valid_bbox(reference) or not _valid_bbox(rendered):
        return None
    assert rendered is not None
    reference_size = _bbox_size(reference)
    rendered_size = _bbox_size(rendered)
    if min(*reference_size, *rendered_size) <= _EPSILON:
        return None
    width_ratio = reference_size[0] / rendered_size[0]
    height_ratio = reference_size[1] / rendered_size[1]
    if not all(math.isfinite(value) and value > 0 for value in (width_ratio, height_ratio)):
        return None
    axis_divergence = max(width_ratio, height_ratio) / min(width_ratio, height_ratio)
    if axis_divergence > _MAX_AXIS_RATIO_DIVERGENCE:
        return None
    uniform_ratio = math.sqrt(width_ratio * height_ratio)
    if not _MIN_UNIFORM_RATIO <= uniform_ratio <= _MAX_UNIFORM_RATIO:
        return None
    scale_step = _clamp(uniform_ratio, _MIN_SCALE_STEP, _MAX_SCALE_STEP)
    if math.isclose(scale_step, 1.0, abs_tol=1e-6):
        return None
    value = [round(component * scale_step, 6) for component in target.transform.scale]
    return _safe_suggestion(
        SuggestedEdit(
            target_type="object",
            target_id=target.id,
            path=["transform", "scale"],
            op="set",
            value=value,
        )
    )


def _enrich_finding(
    finding: QAFinding,
    *,
    spec: SceneSpec,
    objects: dict[str, ObjectSpec],
    metrics: dict[str, tuple[BoundingBoxMetric, float]],
) -> QAFinding:
    """Add one conservative suggestion only when direct semantic evidence is sufficient."""

    if finding.suggestion is not None or finding.issue_type not in {"position", "proportion"}:
        return finding
    if "direct_reference" not in finding.evidence_sources or len(finding.target_ids) != 1:
        return finding
    target_id = finding.target_ids[0]
    target = objects.get(target_id)
    metric_record = metrics.get(target_id)
    if target is None or metric_record is None or target.parent_id is not None:
        return finding
    metric, metric_confidence = metric_record
    if metric.rendered_bbox_norm is None:
        return finding
    direct_confidence = min(finding.confidence, metric_confidence)
    if direct_confidence < _MIN_DIRECT_CONFIDENCE:
        return finding
    if finding.issue_type == "position":
        suggestion = _position_edit(spec, target, metric)
    else:
        # A family array can be too large because of spacing, which object scale cannot fix.
        suggestion = None if target.generator is not None else _proportion_edit(target, metric)
    if suggestion is None:
        return finding
    return finding.model_copy(
        update={
            "suggestion": suggestion,
            "confidence": round(direct_confidence * _CONFIDENCE_DISCOUNT, 6),
        }
    )


def enrich_direct_qa_suggestions(
    report: VisualQAReport,
    spec: SceneSpec,
) -> VisualQAReport:
    """Enrich defensible direct findings with bounded, non-executable transform edits."""

    if report.job_id != spec.job_id:
        raise ValueError("visual QA report job_id does not match SceneSpec")
    objects = {item.id: item for item in spec.objects}
    metrics = {
        item.target_id: (item.metric, item.confidence)
        for item in report.direct_metrics.semantic_deviations
    }
    findings = [
        _enrich_finding(
            finding,
            spec=spec,
            objects=objects,
            metrics=metrics,
        )
        for finding in report.findings
    ]
    existing_ids = {finding.id for finding in findings}
    findings.extend(
        finding
        for finding in _group_position_findings(spec, metrics)
        if finding.id not in existing_ids
    )
    return report.model_copy(update={"findings": findings})
