"""Reference-alignment adapters that preserve the canonical V0.6 direct score."""

from __future__ import annotations

from typing import Literal

from ..qa.models import VisualQAReport
from .models import AxisThreshold, QualityAxisResult, QualityMetric

_MetricStatus = Literal["passed", "warning", "failed", "unscorable"]


def _metric_status(score: float, threshold: AxisThreshold) -> str:
    """Classify one normalized score using explicit profile thresholds."""

    if score >= threshold.pass_score:
        return "passed"
    if score >= threshold.warning_score:
        return "warning"
    return "failed"


def _axis_status(metrics: list[QualityMetric]) -> _MetricStatus:
    """Derive the axis result from every critical metric instead of one summary score."""

    critical_statuses = {item.status for item in metrics if item.critical}
    for status in ("unscorable", "failed", "warning", "passed"):
        if status in critical_statuses:
            return status  # type: ignore[return-value]
    return "unscorable"


def _authoritative_high_findings(report: VisualQAReport) -> list[str]:
    """Return high findings backed by direct-reference or constraint evidence.

    The legacy V0.6 finding contract does not carry a stable QA-role field.  A high
    authoritative finding therefore cannot safely be downgraded as decorative at
    this adapter boundary and remains a critical reference-alignment observation.
    Generated-target-only findings stay advisory and are excluded.
    """

    authoritative_sources = {"direct_reference", "constraint"}
    return [
        finding.id
        for finding in report.findings
        if finding.severity == "high"
        and authoritative_sources.intersection(finding.evidence_sources)
    ]


def reference_alignment_axis(
    report: VisualQAReport | None,
    *,
    threshold: AxisThreshold,
    evidence_id: str,
    confidence: float = 1.0,
) -> QualityAxisResult:
    """Project immutable V0.6 metrics into one axis without changing their values."""

    if report is None:
        return QualityAxisResult(
            axis="reference_alignment",
            required=threshold.required,
            status="unscorable",
            score=None,
            confidence=0,
            metrics=[
                QualityMetric(
                    metric_id="reference.v06_overall_direct_score",
                    status="unscorable",
                    value=None,
                    confidence=0,
                    critical=True,
                    evidence_ids=[evidence_id],
                    message="A current V0.6 VisualQA report was not supplied.",
                )
            ],
            evidence_ids=[evidence_id],
            limitations=["Reference alignment is unavailable without direct V0.6 evidence."],
        )
    direct_score = report.direct_metrics.overall_direct_score
    direct_status = _metric_status(direct_score, threshold)
    silhouette_score = report.direct_metrics.silhouette_iou
    high_findings = _authoritative_high_findings(report)
    metrics = [
        QualityMetric(
            metric_id="reference.v06_overall_direct_score",
            status=direct_status,  # type: ignore[arg-type]
            value=direct_score,
            unit="normalized",
            threshold=threshold.pass_score,
            direction="higher_is_better",
            confidence=confidence,
            critical=True,
            evidence_ids=[evidence_id],
            message="Copied exactly from VisualQAReport.direct_metrics.overall_direct_score.",
        ),
        QualityMetric(
            metric_id="reference.silhouette_iou",
            status=_metric_status(silhouette_score, threshold),  # type: ignore[arg-type]
            value=silhouette_score,
            unit="normalized",
            threshold=threshold.pass_score,
            direction="higher_is_better",
            confidence=confidence,
            critical=True,
            evidence_ids=[evidence_id],
            message="Canonical fixed-camera V0.6 silhouette overlap.",
        ),
        QualityMetric(
            metric_id="reference.authoritative_high_finding_count",
            status="failed" if high_findings else "passed",
            value=float(len(high_findings)),
            unit="findings",
            threshold=0,
            direction="lower_is_better",
            confidence=confidence,
            critical=True,
            evidence_ids=[evidence_id],
            message=(
                "No high authoritative V0.6 finding is present."
                if not high_findings
                else "High direct-reference or constraint findings remain: "
                + ", ".join(high_findings)
            ),
        ),
    ]
    status = _axis_status(metrics)
    limitations = list(report.warnings)
    if high_findings:
        limitations.append(
            "High authoritative findings remain unresolved: " + ", ".join(high_findings)
        )
    return QualityAxisResult(
        axis="reference_alignment",
        required=threshold.required,
        status=status,  # type: ignore[arg-type]
        score=direct_score,
        confidence=confidence,
        metrics=metrics,
        evidence_ids=[evidence_id],
        limitations=limitations,
    )
