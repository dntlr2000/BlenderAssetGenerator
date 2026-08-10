"""Production-readiness adapters for V0.7 preflight and clean-import evidence."""

from __future__ import annotations

from ..optimization.models import MeshPreflightReport
from ..packaging.models import RoundTripValidation
from .models import AxisThreshold, QualityAxisResult, QualityMetric


def _status(score: float, threshold: AxisThreshold, *, failed: bool) -> str:
    """Classify production evidence with export failures taking precedence."""

    if failed:
        return "failed"
    if score >= threshold.pass_score:
        return "passed"
    if score >= threshold.warning_score:
        return "warning"
    return "failed"


def production_readiness_axis(
    *,
    threshold: AxisThreshold,
    evidence_id: str,
    preflight: MeshPreflightReport | None = None,
    roundtrip: RoundTripValidation | None = None,
    confidence: float = 1.0,
) -> QualityAxisResult:
    """Combine derived-package checks without claiming destination-runtime parity."""

    metrics: list[QualityMetric] = []
    scores: list[float] = []
    failed = False
    if preflight is not None:
        total = preflight.passed + preflight.warnings + preflight.failed
        score = preflight.passed / total if total else 0.0
        local_failed = not preflight.ok
        failed |= local_failed
        scores.append(score)
        metrics.append(
            QualityMetric(
                metric_id="production.mesh_preflight_pass_ratio",
                status=_status(score, threshold, failed=local_failed),  # type: ignore[arg-type]
                value=score,
                unit="ratio",
                threshold=threshold.pass_score,
                direction="higher_is_better",
                confidence=confidence,
                critical=True,
                evidence_ids=[evidence_id],
                message="V0.7 derived mesh preflight evidence.",
            )
        )
    if roundtrip is not None:
        score = min(
            roundtrip.semantic_id_coverage,
            roundtrip.material_id_coverage,
            1.0 if roundtrip.bounds.passed else 0.0,
        )
        local_failed = not roundtrip.ok
        failed |= local_failed
        scores.append(score)
        metrics.extend(
            [
                QualityMetric(
                    metric_id="production.roundtrip_semantic_coverage",
                    status=_status(
                        roundtrip.semantic_id_coverage,
                        threshold,
                        failed=local_failed,
                    ),  # type: ignore[arg-type]
                    value=roundtrip.semantic_id_coverage,
                    unit="ratio",
                    threshold=threshold.pass_score,
                    direction="higher_is_better",
                    confidence=confidence,
                    critical=True,
                    evidence_ids=[evidence_id],
                    message="Clean-import semantic-ID coverage.",
                ),
                QualityMetric(
                    metric_id="production.roundtrip_material_coverage",
                    status=_status(
                        roundtrip.material_id_coverage,
                        threshold,
                        failed=local_failed,
                    ),  # type: ignore[arg-type]
                    value=roundtrip.material_id_coverage,
                    unit="ratio",
                    threshold=threshold.pass_score,
                    direction="higher_is_better",
                    confidence=confidence,
                    critical=True,
                    evidence_ids=[evidence_id],
                    message="Clean-import material-ID coverage.",
                ),
                QualityMetric(
                    metric_id="production.roundtrip_bounds",
                    status="passed" if roundtrip.bounds.passed else "failed",
                    value=1.0 if roundtrip.bounds.passed else 0.0,
                    unit="boolean",
                    threshold=1.0,
                    direction="boolean",
                    confidence=confidence,
                    critical=True,
                    evidence_ids=[evidence_id],
                    message="Clean-import bounds tolerance result.",
                ),
            ]
        )
    if roundtrip is None:
        metrics.append(
            QualityMetric(
                metric_id="production.roundtrip_available",
                status="unscorable",
                value=None,
                confidence=0,
                critical=True,
                evidence_ids=[evidence_id],
                message="A clean-import round-trip report was not supplied.",
            )
        )
        return QualityAxisResult(
            axis="production_readiness",
            required=threshold.required,
            status="unscorable",
            score=None,
            confidence=0,
            metrics=metrics,
            evidence_ids=[evidence_id],
            limitations=[
                "Production readiness cannot pass before clean-import round-trip validation."
            ],
        )
    if not scores:
        return QualityAxisResult(
            axis="production_readiness",
            required=threshold.required,
            status="unscorable",
            score=None,
            confidence=0,
            metrics=[
                QualityMetric(
                    metric_id="production.available_evidence",
                    status="unscorable",
                    value=None,
                    confidence=0,
                    critical=True,
                    evidence_ids=[evidence_id],
                    message="No V0.7 preflight or round-trip evidence was supplied.",
                )
            ],
            evidence_ids=[evidence_id],
            limitations=["Production readiness is unavailable before V0.7 evidence exists."],
        )
    score = min(scores)
    status = _status(score, threshold, failed=failed)
    return QualityAxisResult(
        axis="production_readiness",
        required=threshold.required,
        status=status,  # type: ignore[arg-type]
        score=score,
        confidence=confidence,
        metrics=metrics,
        evidence_ids=[evidence_id],
        limitations=["Destination-runtime parity remains outside this evidence."],
    )
