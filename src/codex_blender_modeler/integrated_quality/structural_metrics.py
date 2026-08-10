"""Structural-integrity adapters for measured, assembly, and mesh evidence."""

from __future__ import annotations

from ..analysis.models import AssemblyValidationReport
from ..constraints.models import ConstraintSolution
from ..optimization.models import MeshPreflightReport
from .models import AxisThreshold, QualityAxisResult, QualityMetric


def _ratio(passed: int, total: int) -> float:
    """Return a bounded pass ratio while avoiding division by zero."""

    return passed / total if total else 0.0


def _score_status(score: float, threshold: AxisThreshold, *, failed: bool) -> str:
    """Classify structural evidence with deterministic failures taking precedence."""

    if failed:
        return "failed"
    if score >= threshold.pass_score:
        return "passed"
    if score >= threshold.warning_score:
        return "warning"
    return "failed"


def structural_integrity_axis(
    *,
    threshold: AxisThreshold,
    evidence_id: str,
    constraints: ConstraintSolution | None = None,
    assembly_reports: list[AssemblyValidationReport] | None = None,
    mesh_preflight: MeshPreflightReport | None = None,
    confidence: float = 1.0,
) -> QualityAxisResult:
    """Combine deterministic structural checks while retaining their separate measurements."""

    assembly_reports = assembly_reports or []
    metrics: list[QualityMetric] = []
    scores: list[float] = []
    definitive_failure = False
    if constraints is not None:
        score = _ratio(constraints.passed, constraints.evaluated)
        failed = constraints.failed > 0 or constraints.missing > 0
        definitive_failure |= failed
        scores.append(score)
        metrics.append(
            QualityMetric(
                metric_id="structural.constraint_pass_ratio",
                status=_score_status(score, threshold, failed=failed),  # type: ignore[arg-type]
                value=score,
                unit="ratio",
                threshold=threshold.pass_score,
                direction="higher_is_better",
                confidence=confidence,
                critical=True,
                evidence_ids=[evidence_id],
                message=(
                    f"Measured constraints: passed={constraints.passed}, "
                    f"failed={constraints.failed}, missing={constraints.missing}."
                ),
            )
        )
    for index, report in enumerate(assembly_reports):
        total = report.passed + report.warnings + report.failed
        score = _ratio(report.passed, total)
        failed = report.failed > 0
        definitive_failure |= failed
        scores.append(score)
        metrics.append(
            QualityMetric(
                metric_id=f"structural.assembly_{index}_{report.phase}",
                status=_score_status(score, threshold, failed=failed),  # type: ignore[arg-type]
                value=score,
                unit="ratio",
                threshold=threshold.pass_score,
                direction="higher_is_better",
                confidence=confidence,
                critical=True,
                evidence_ids=[evidence_id],
                message=(
                    f"Assembly {report.phase}: passed={report.passed}, "
                    f"warnings={report.warnings}, failed={report.failed}."
                ),
            )
        )
    if mesh_preflight is not None:
        total = mesh_preflight.passed + mesh_preflight.warnings + mesh_preflight.failed
        score = _ratio(mesh_preflight.passed, total)
        failed = mesh_preflight.failed > 0
        definitive_failure |= failed
        scores.append(score)
        metrics.append(
            QualityMetric(
                metric_id="structural.mesh_preflight_pass_ratio",
                status=_score_status(score, threshold, failed=failed),  # type: ignore[arg-type]
                value=score,
                unit="ratio",
                threshold=threshold.pass_score,
                direction="higher_is_better",
                confidence=confidence,
                critical=True,
                evidence_ids=[evidence_id],
                message=(
                    f"Mesh preflight: passed={mesh_preflight.passed}, "
                    f"warnings={mesh_preflight.warnings}, failed={mesh_preflight.failed}."
                ),
            )
        )
    if not scores:
        return QualityAxisResult(
            axis="structural_integrity",
            required=threshold.required,
            status="unscorable",
            score=None,
            confidence=0,
            metrics=[
                QualityMetric(
                    metric_id="structural.available_evidence",
                    status="unscorable",
                    value=None,
                    confidence=0,
                    critical=True,
                    evidence_ids=[evidence_id],
                    message="No structural evidence was supplied.",
                )
            ],
            evidence_ids=[evidence_id],
            limitations=["Structural integrity is unavailable without validation evidence."],
        )
    score = min(scores)
    status = _score_status(score, threshold, failed=definitive_failure)
    return QualityAxisResult(
        axis="structural_integrity",
        required=threshold.required,
        status=status,  # type: ignore[arg-type]
        score=score,
        confidence=confidence,
        metrics=metrics,
        evidence_ids=[evidence_id],
        limitations=[],
    )
