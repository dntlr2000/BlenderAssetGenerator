"""Material-fidelity adapters for V0.5 contract and raster evidence."""

from __future__ import annotations

from ..materials.fidelity_models import MaterialFidelityReport
from ..materials.models import MaterialValidationReport
from .models import AxisThreshold, QualityAxisResult, QualityMetric


def _status(score: float, threshold: AxisThreshold, *, failed: bool) -> str:
    """Classify material evidence while preserving deterministic failures."""

    if failed:
        return "failed"
    if score >= threshold.pass_score:
        return "passed"
    if score >= threshold.warning_score:
        return "warning"
    return "failed"


def material_fidelity_axis(
    *,
    threshold: AxisThreshold,
    evidence_id: str,
    validation: MaterialValidationReport | None = None,
    fidelity: MaterialFidelityReport | None = None,
    confidence: float = 1.0,
) -> QualityAxisResult:
    """Combine material contract and pixel evidence without treating either as geometry QA."""

    metrics: list[QualityMetric] = []
    scores: list[float] = []
    failed = False
    if validation is not None:
        total = validation.passed + validation.warnings + validation.failed
        score = validation.passed / total if total else 0.0
        local_failed = validation.failed > 0
        failed |= local_failed
        scores.append(score)
        metrics.append(
            QualityMetric(
                metric_id="material.contract_pass_ratio",
                status=_status(score, threshold, failed=local_failed),  # type: ignore[arg-type]
                value=score,
                unit="ratio",
                threshold=threshold.pass_score,
                direction="higher_is_better",
                confidence=confidence,
                critical=True,
                evidence_ids=[evidence_id],
                message=(
                    f"V0.5 contract checks: passed={validation.passed}, "
                    f"warnings={validation.warnings}, failed={validation.failed}."
                ),
            )
        )
    fidelity_scorable = fidelity is not None and fidelity.status != "unscorable"
    if fidelity_scorable and fidelity is not None:
        total = fidelity.passed + fidelity.warnings + fidelity.failed
        score = fidelity.passed / total if total else 0.0
        local_failed = fidelity.failed > 0
        failed |= local_failed
        scores.append(score)
        metrics.append(
            QualityMetric(
                metric_id="material.raster_fidelity_pass_ratio",
                status=_status(score, threshold, failed=local_failed),  # type: ignore[arg-type]
                value=score,
                unit="ratio",
                threshold=threshold.pass_score,
                direction="higher_is_better",
                confidence=confidence,
                critical=True,
                evidence_ids=[evidence_id],
                message=(
                    f"Raster fidelity findings: passed={fidelity.passed}, "
                    f"warnings={fidelity.warnings}, failed={fidelity.failed}."
                ),
            )
        )
    if fidelity is None or not fidelity_scorable:
        metrics.append(
            QualityMetric(
                metric_id="material.raster_fidelity_available",
                status="unscorable",
                value=None,
                confidence=0,
                critical=True,
                evidence_ids=[evidence_id],
                message="Material raster fidelity evidence is unavailable or unscorable.",
            )
        )
        return QualityAxisResult(
            axis="material_fidelity",
            required=threshold.required,
            status="unscorable",
            score=None,
            confidence=0,
            metrics=metrics,
            evidence_ids=[evidence_id],
            limitations=[
                "Material fidelity cannot pass from contract validation without raster evidence."
            ],
        )
    if not scores:
        return QualityAxisResult(
            axis="material_fidelity",
            required=threshold.required,
            status="unscorable",
            score=None,
            confidence=0,
            metrics=[
                QualityMetric(
                    metric_id="material.available_evidence",
                    status="unscorable",
                    value=None,
                    confidence=0,
                    critical=True,
                    evidence_ids=[evidence_id],
                    message="No material validation or fidelity evidence was supplied.",
                )
            ],
            evidence_ids=[evidence_id],
            limitations=["Material fidelity is unavailable without V0.5 evidence."],
        )
    score = min(scores)
    status = _status(score, threshold, failed=failed)
    return QualityAxisResult(
        axis="material_fidelity",
        required=threshold.required,
        status=status,  # type: ignore[arg-type]
        score=score,
        confidence=confidence,
        metrics=metrics,
        evidence_ids=[evidence_id],
        limitations=[],
    )
