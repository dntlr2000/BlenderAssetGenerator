from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from .diagnostic_models import (
    AssemblyDiagnosticEvidence,
    CameraProbeResult,
    DiagnosticAttribution,
    DiagnosticStrictModel,
    SemanticShapeMetrics,
)

_ASSEMBLY_CONTRACT_CONFIDENCE = 0.85


class AttributionThresholds(DiagnosticStrictModel):
    """Configure conservative thresholds for advisory camera-versus-shape attribution."""

    minimum_camera_gain: float = Field(default=0.03, ge=0, le=1)
    minimum_primary_silhouette_gain: float = Field(default=0.03, ge=0, le=1)
    minimum_semantic_gain: float = Field(default=0.02, ge=0, le=1)
    minimum_semantic_consensus: float = Field(default=0.67, ge=0, le=1)
    acceptable_semantic_score: float = Field(default=0.85, ge=0, le=1)
    minimum_geometry_residual_fraction: float = Field(default=0.34, ge=0, le=1)
    acceptable_mask_iou: float = Field(default=0.80, ge=0, le=1)
    acceptable_boundary_f_score: float = Field(default=0.80, ge=0, le=1)
    maximum_contour_distance_norm: float = Field(default=0.04, ge=0, le=1)
    maximum_axis_error_deg: float = Field(default=15.0, ge=0, le=90)


def _scored_semantic_map(probe: CameraProbeResult) -> dict[str, float]:
    """Return only semantic probe scores backed by scorable evidence."""

    return {
        item.semantic_id: item.score
        for item in probe.semantic_scores
        if item.scorable and item.score is not None
    }


def _bounded_ratio(value: float, denominator: float) -> float:
    """Convert a non-negative threshold ratio into the closed unit interval."""

    if denominator <= 0:
        return 1.0 if value > 0 else 0.0
    return max(0.0, min(1.0, value / denominator))


def _primary_silhouette_gain(
    baseline: CameraProbeResult,
    probe: CameraProbeResult,
) -> float | None:
    """Return exact broad-subject silhouette gain when both probes provide it."""

    if (
        baseline.primary_silhouette_score is None
        or probe.primary_silhouette_score is None
    ):
        return None
    return probe.primary_silhouette_score - baseline.primary_silhouette_score


def _semantic_shape_residuals(
    metrics: Sequence[SemanticShapeMetrics],
    policy: AttributionThresholds,
) -> tuple[float | None, list[str], list[str]]:
    """Summarize explicit mask-shape and undirected orientation residuals."""

    scored = [
        item
        for item in metrics
        if item.status == "scored"
        and item.role in {"primary", "supporting", "unscoped"}
    ]
    if not scored:
        return None, [], []
    residual_ids: list[str] = []
    orientation_ids: list[str] = []
    for item in scored:
        assert item.mask_iou is not None
        assert item.boundary_f_score is not None
        assert item.symmetric_contour_distance_norm is not None
        orientation_failed = bool(
            item.oriented_axis_scorable
            and item.undirected_axis_error_deg is not None
            and item.undirected_axis_error_deg > policy.maximum_axis_error_deg
        )
        shape_failed = (
            item.mask_iou < policy.acceptable_mask_iou
            or item.boundary_f_score < policy.acceptable_boundary_f_score
            or item.symmetric_contour_distance_norm
            > policy.maximum_contour_distance_norm
            or orientation_failed
        )
        if shape_failed:
            residual_ids.append(item.semantic_id)
        if orientation_failed:
            orientation_ids.append(item.semantic_id)
    return len(residual_ids) / len(scored), residual_ids, orientation_ids


def _probe_rank_gain(
    baseline: CameraProbeResult,
    probe: CameraProbeResult,
) -> float:
    """Rank a bounded probe by its strongest exact bbox or silhouette improvement."""

    assert baseline.overall_score is not None
    assert probe.overall_score is not None
    overall_gain = probe.overall_score - baseline.overall_score
    silhouette_gain = _primary_silhouette_gain(baseline, probe)
    return max(overall_gain, silhouette_gain if silhouette_gain is not None else -1.0)


def _unscorable_attribution(
    baseline_probe_id: str,
    reasons: list[str],
) -> DiagnosticAttribution:
    """Create a consistent advisory result for insufficient camera evidence."""

    return DiagnosticAttribution(
        classification="unscorable",
        confidence=1.0,
        baseline_probe_id=baseline_probe_id,
        reasons=reasons,
    )


def attribute_camera_geometry(
    baseline: CameraProbeResult,
    probes: Sequence[CameraProbeResult],
    *,
    assembly: AssemblyDiagnosticEvidence | None = None,
    semantic_metrics: Sequence[SemanticShapeMetrics] = (),
    thresholds: AttributionThresholds | None = None,
) -> DiagnosticAttribution:
    """Attribute mismatches from bounded probe gains, residuals, and assembly evidence."""

    policy = thresholds or AttributionThresholds()
    assembly_evidence = assembly or AssemblyDiagnosticEvidence()
    assembly_signal = bool(assembly_evidence.required_failure_ids)
    (
        semantic_shape_residual_fraction,
        semantic_shape_residual_ids,
        semantic_orientation_residual_ids,
    ) = _semantic_shape_residuals(semantic_metrics, policy)

    if baseline.status != "scored" or baseline.overall_score is None:
        if assembly_signal:
            return DiagnosticAttribution(
                classification="assembly",
                confidence=_ASSEMBLY_CONTRACT_CONFIDENCE,
                baseline_probe_id=baseline.probe_id,
                assembly_failure_ids=assembly_evidence.required_failure_ids,
                semantic_shape_residual_fraction=semantic_shape_residual_fraction,
                semantic_shape_residual_ids=semantic_shape_residual_ids,
                semantic_orientation_residual_ids=semantic_orientation_residual_ids,
                reasons=[
                    "camera evidence is unscorable, while declared or inferred "
                    "assembly-consistency checks failed"
                ],
            )
        return _unscorable_attribution(
            baseline.probe_id,
            ["baseline camera evidence is unscorable"],
        )

    scored_probes = [
        probe
        for probe in probes
        if probe.probe_id != baseline.probe_id
        and probe.status == "scored"
        and probe.overall_score is not None
    ]
    if not scored_probes:
        if assembly_signal:
            return DiagnosticAttribution(
                classification="assembly",
                confidence=_ASSEMBLY_CONTRACT_CONFIDENCE,
                baseline_probe_id=baseline.probe_id,
                baseline_score=baseline.overall_score,
                assembly_failure_ids=assembly_evidence.required_failure_ids,
                semantic_shape_residual_fraction=semantic_shape_residual_fraction,
                semantic_shape_residual_ids=semantic_shape_residual_ids,
                semantic_orientation_residual_ids=semantic_orientation_residual_ids,
                reasons=[
                    "no bounded camera probe is scorable, while declared or inferred "
                    "assembly-consistency checks failed"
                ],
            )
        return _unscorable_attribution(
            baseline.probe_id,
            ["no bounded non-baseline camera probe is scorable"],
        )

    best = max(
        scored_probes,
        key=lambda item: (
            _probe_rank_gain(baseline, item),
            item.overall_score,
            item.primary_silhouette_score
            if item.primary_silhouette_score is not None
            else -1.0,
            item.probe_id,
        ),
    )
    assert best.overall_score is not None
    baseline_scores = _scored_semantic_map(baseline)
    best_scores = _scored_semantic_map(best)
    common_ids = sorted(set(baseline_scores) & set(best_scores))
    if not common_ids:
        if assembly_signal:
            return DiagnosticAttribution(
                classification="assembly",
                confidence=_ASSEMBLY_CONTRACT_CONFIDENCE,
                baseline_probe_id=baseline.probe_id,
                best_probe_id=best.probe_id,
                baseline_score=baseline.overall_score,
                best_score=best.overall_score,
                camera_gain=best.overall_score - baseline.overall_score,
                assembly_failure_ids=assembly_evidence.required_failure_ids,
                semantic_shape_residual_fraction=semantic_shape_residual_fraction,
                semantic_shape_residual_ids=semantic_shape_residual_ids,
                semantic_orientation_residual_ids=semantic_orientation_residual_ids,
                reasons=[
                    "camera probes have no common semantic evidence, while declared or "
                    "inferred assembly-consistency checks failed"
                ],
            )
        return _unscorable_attribution(
            baseline.probe_id,
            ["baseline and best camera probe have no common scorable semantic IDs"],
        )

    camera_gain = best.overall_score - baseline.overall_score
    silhouette_gain = _primary_silhouette_gain(baseline, best)
    improved_count = sum(
        1
        for semantic_id in common_ids
        if best_scores[semantic_id] - baseline_scores[semantic_id]
        >= policy.minimum_semantic_gain
    )
    consensus = improved_count / len(common_ids)
    residual_count = sum(
        1
        for semantic_id in common_ids
        if best_scores[semantic_id] < policy.acceptable_semantic_score
    )
    residual_fraction = residual_count / len(common_ids)
    broad_silhouette_signal = (
        silhouette_gain is not None
        and silhouette_gain >= policy.minimum_primary_silhouette_gain
    )
    camera_signal = (
        (
            camera_gain >= policy.minimum_camera_gain
            and consensus >= policy.minimum_semantic_consensus
        )
        or broad_silhouette_signal
    )
    combined_geometry_residual = max(
        residual_fraction,
        semantic_shape_residual_fraction or 0.0,
    )
    geometry_signal = (
        combined_geometry_residual >= policy.minimum_geometry_residual_fraction
    )
    signal_count = sum((camera_signal, geometry_signal, assembly_signal))

    if signal_count > 1:
        classification = "mixed"
    elif camera_signal:
        classification = "camera"
    elif geometry_signal:
        classification = "geometry"
    elif assembly_signal:
        classification = "assembly"
    else:
        classification = "ambiguous"

    bbox_camera_strength = (
        _bounded_ratio(camera_gain, max(policy.minimum_camera_gain * 2.0, 1e-9))
        * consensus
    )
    silhouette_camera_strength = (
        _bounded_ratio(
            silhouette_gain,
            max(policy.minimum_primary_silhouette_gain * 2.0, 1e-9),
        )
        if silhouette_gain is not None
        else 0.0
    )
    camera_strength = max(bbox_camera_strength, silhouette_camera_strength)
    geometry_strength = combined_geometry_residual
    assembly_strength = _ASSEMBLY_CONTRACT_CONFIDENCE if assembly_signal else 0.0
    if classification == "camera":
        confidence = max(0.5, camera_strength)
    elif classification == "geometry":
        confidence = max(0.5, geometry_strength)
    elif classification == "assembly":
        confidence = _ASSEMBLY_CONTRACT_CONFIDENCE
    elif classification == "mixed":
        active_strengths = [
            strength
            for strength, active in (
                (camera_strength, camera_signal),
                (geometry_strength, geometry_signal),
                (assembly_strength, assembly_signal),
            )
            if active
        ]
        confidence = max(0.5, sum(active_strengths) / len(active_strengths))
    else:
        confidence = 0.35

    reasons = [
        (
            f"best bounded camera probe changed the overall score by {camera_gain:+.6f} "
            f"with semantic consensus {consensus:.3f}"
        ),
        (
            f"{residual_count}/{len(common_ids)} common semantic scores remain below "
            f"{policy.acceptable_semantic_score:.3f}"
        ),
    ]
    if silhouette_gain is not None:
        reasons.append(
            "best bounded camera probe changed the exact primary-subject silhouette "
            f"score by {silhouette_gain:+.6f}"
        )
    if assembly_signal:
        reasons.append(
            "declared or inferred assembly-consistency checks failed: "
            + ", ".join(assembly_evidence.required_failure_ids)
        )
    if semantic_shape_residual_fraction is not None:
        reasons.append(
            f"{len(semantic_shape_residual_ids)}/{len(semantic_metrics)} explicit "
            "semantic masks retain contour, shape, or orientation residuals"
        )
    if semantic_orientation_residual_ids:
        reasons.append(
            "undirected 2D principal-axis residuals remain for: "
            + ", ".join(semantic_orientation_residual_ids)
        )
    if classification == "ambiguous":
        reasons.append("evidence does not cross camera, geometry, or assembly thresholds")

    return DiagnosticAttribution(
        classification=classification,
        confidence=min(1.0, confidence),
        baseline_probe_id=baseline.probe_id,
        best_probe_id=best.probe_id,
        baseline_score=baseline.overall_score,
        best_score=best.overall_score,
        camera_gain=camera_gain,
        baseline_primary_silhouette_score=baseline.primary_silhouette_score,
        best_primary_silhouette_score=best.primary_silhouette_score,
        primary_silhouette_gain=silhouette_gain,
        semantic_consensus_fraction=consensus,
        geometry_residual_fraction=combined_geometry_residual,
        semantic_shape_residual_fraction=semantic_shape_residual_fraction,
        semantic_shape_residual_ids=semantic_shape_residual_ids,
        semantic_orientation_residual_ids=semantic_orientation_residual_ids,
        assembly_failure_ids=assembly_evidence.required_failure_ids,
        reasons=reasons,
    )
