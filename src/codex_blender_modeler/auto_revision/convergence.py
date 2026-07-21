from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..constraints.models import ConstraintResult
from ..qa.models import VisualQAReport
from ..workspace import sha256_file
from .models import ConstraintRegression, ConvergenceReport

_STATUS_SEVERITY = {"passed": 0, "failed": 1, "missing": 2}


def _load_constraint_results(
    records: list[ConstraintResult | dict[str, Any]],
) -> dict[str, ConstraintResult]:
    """Validate and index measured results by stable constraint ID."""

    indexed: dict[str, ConstraintResult] = {}
    for record in records:
        result = (
            record
            if isinstance(record, ConstraintResult)
            else ConstraintResult.model_validate(record)
        )
        if result.id in indexed:
            raise ValueError(f"duplicate measured constraint result ID: {result.id}")
        indexed[result.id] = result
    return indexed


def _residual_ratio(result: ConstraintResult | None) -> float | None:
    """Normalize an absolute residual by its declared positive tolerance."""

    if (
        result is None
        or result.residual_m is None
        or result.tolerance_m is None
        or result.tolerance_m <= 0
    ):
        return None
    return abs(float(result.residual_m)) / float(result.tolerance_m)


def compare_constraint_results(
    before_records: list[ConstraintResult | dict[str, Any]],
    after_records: list[ConstraintResult | dict[str, Any]],
) -> list[ConstraintRegression]:
    """Find per-ID status, tolerance, and normalized-residual regressions."""

    before = _load_constraint_results(before_records)
    after = _load_constraint_results(after_records)
    regressions: list[ConstraintRegression] = []
    for constraint_id in sorted(set(before) | set(after)):
        baseline = before.get(constraint_id)
        revised = after.get(constraint_id)
        reasons: list[str] = []
        if baseline is None:
            if revised is not None and revised.status in {"failed", "missing"}:
                reasons.append("A new unsatisfied constraint appeared after revision.")
        elif revised is None:
            reasons.append("The baseline constraint result disappeared after revision.")
        elif baseline.status == "disabled" or revised.status == "disabled":
            if baseline.status != revised.status:
                reasons.append("The constraint enabled/disabled status changed after revision.")
        else:
            if _STATUS_SEVERITY[revised.status] > _STATUS_SEVERITY[baseline.status]:
                reasons.append(
                    f"Constraint status worsened from {baseline.status} to {revised.status}."
                )
            if (
                baseline.tolerance_m is not None
                and revised.tolerance_m is not None
                and not math.isclose(
                    float(baseline.tolerance_m),
                    float(revised.tolerance_m),
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
            ):
                reasons.append("Constraint tolerance changed during visual revision.")
            before_ratio = _residual_ratio(baseline)
            after_ratio = _residual_ratio(revised)
            if (
                before_ratio is not None
                and after_ratio is not None
                and after_ratio > before_ratio + 1e-9
            ):
                reasons.append(
                    "Residual-to-tolerance ratio increased "
                    f"from {before_ratio:.9g} to {after_ratio:.9g}."
                )
        if not reasons:
            continue
        regressions.append(
            ConstraintRegression(
                constraint_id=constraint_id,
                before_status=baseline.status if baseline is not None else None,
                after_status=revised.status if revised is not None else None,
                before_residual_m=(
                    baseline.residual_m if baseline is not None else None
                ),
                after_residual_m=revised.residual_m if revised is not None else None,
                before_tolerance_m=(
                    baseline.tolerance_m if baseline is not None else None
                ),
                after_tolerance_m=revised.tolerance_m if revised is not None else None,
                before_residual_ratio=_residual_ratio(baseline),
                after_residual_ratio=_residual_ratio(revised),
                reasons=reasons,
            )
        )
    return regressions


def evaluate_convergence(
    *,
    before_report_path: Path,
    after_report_path: Path,
    changed_ids: list[str],
    preserved_ids: list[str],
    before_failed_constraints: int = 0,
    after_failed_constraints: int = 0,
    before_constraint_results: list[ConstraintResult | dict[str, Any]] | None = None,
    after_constraint_results: list[ConstraintResult | dict[str, Any]] | None = None,
    minimum_improvement: float = 0.001,
) -> ConvergenceReport:
    """Accept only direct-score improvements that do not worsen measured constraints."""

    before = VisualQAReport.model_validate_json(
        before_report_path.read_text(encoding="utf-8")
    )
    after = VisualQAReport.model_validate_json(after_report_path.read_text(encoding="utf-8"))
    if before.job_id != after.job_id:
        raise ValueError("convergence reports belong to different jobs")
    if before.camera_fingerprint != after.camera_fingerprint:
        raise ValueError("convergence requires the same fixed comparison camera")
    before_score = before.direct_metrics.overall_direct_score
    after_score = after.direct_metrics.overall_direct_score
    delta = round(after_score - before_score, 6)
    scoring_versions_match = (
        before.direct_metrics.scoring_version == after.direct_metrics.scoring_version
    )
    reasons: list[str] = []
    result_level_comparison = (
        before_constraint_results is not None or after_constraint_results is not None
    )
    constraint_regressions = compare_constraint_results(
        before_constraint_results or [],
        after_constraint_results or [],
    )
    if not scoring_versions_match:
        status = "regressed"
        reasons.append(
            "Direct-score contracts differ and cannot establish convergence: "
            f"{before.direct_metrics.scoring_version} -> "
            f"{after.direct_metrics.scoring_version}."
        )
    elif constraint_regressions:
        status = "regressed"
        reasons.append(
            "Measured constraints regressed by stable constraint ID, status, or "
            "residual-to-tolerance ratio."
        )
    elif not result_level_comparison and after_failed_constraints > before_failed_constraints:
        status = "regressed"
        reasons.append("Measured constraint failures increased (legacy count comparison).")
    elif delta >= minimum_improvement:
        status = "improved"
        reasons.append("Direct-reference score improved beyond the configured threshold.")
    elif delta < -minimum_improvement:
        status = "regressed"
        reasons.append("Direct-reference score decreased.")
    else:
        status = "no_change"
        reasons.append("Direct-reference score change is below the improvement threshold.")
    accepted = status == "improved"
    return ConvergenceReport(
        job_id=before.job_id,
        before_report_sha256=sha256_file(before_report_path),
        after_report_sha256=sha256_file(after_report_path),
        before_direct_score=before_score,
        after_direct_score=after_score,
        score_delta=delta,
        before_failed_constraints=before_failed_constraints,
        after_failed_constraints=after_failed_constraints,
        constraint_regressions=constraint_regressions,
        changed_ids=changed_ids,
        preserved_ids=preserved_ids,
        status=status,
        accepted=accepted,
        rollback_required=not accepted,
        reasons=reasons,
    )
