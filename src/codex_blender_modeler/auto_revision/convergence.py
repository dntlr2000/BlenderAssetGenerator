from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from ..analysis.models import ModelingPlan
from ..constraints.models import ConstraintResult
from ..qa.models import VisualQAReport
from ..qa.structural_regression import (
    StructuralRegressionReport,
    compare_assembly_sanity_terminals,
)
from ..workspace import job_dir, sha256_file
from .models import ConstraintRegression, ConvergenceReport

_STATUS_SEVERITY = {"passed": 0, "failed": 1, "missing": 2}


def _authored_spatial_multiview_required(job_id: str) -> bool:
    """Require exact multi-view evidence only for authored spatial ModelingPlans."""

    modeling_plan_path = job_dir(job_id) / "analysis" / "modeling_plan.json"
    if not modeling_plan_path.is_file():
        return False
    raw = json.loads(modeling_plan_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("ModelingPlan root must be an object")
    if raw.get("assembly_consistency_policy", "legacy_unbound") != "spatial_v1":
        return False
    if raw.get("stage", "scaffold") != "authored":
        return False
    plan = ModelingPlan.model_validate(raw)
    if plan.job_id != job_id:
        raise ValueError("ModelingPlan belongs to another job")
    return True


def _load_revalidated_multiview_comparison(
    comparison_path: Path,
    *,
    expected_job_id: str,
) -> tuple[StructuralRegressionReport, str]:
    """Replay exact terminal evidence and bind the bytes used for convergence."""

    root = job_dir(expected_job_id).resolve()
    resolved_path = comparison_path.expanduser().resolve()
    try:
        resolved_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("multi-view comparison is outside the owning job") from exc
    comparison_bytes = resolved_path.read_bytes()
    comparison = StructuralRegressionReport.model_validate_json(comparison_bytes)
    if comparison.job_id != expected_job_id:
        raise ValueError("multi-view structural comparison belongs to another job")
    if comparison.baseline.run_id == comparison.result.run_id:
        raise ValueError("multi-view comparison requires distinct baseline and result runs")
    recomputed = compare_assembly_sanity_terminals(
        root,
        baseline=comparison.baseline,
        result=comparison.result,
        expected_job_id=expected_job_id,
        generated_at=comparison.generated_at,
    )
    if recomputed != comparison:
        raise ValueError(
            "multi-view structural comparison does not match recomputed exact terminals"
        )
    return comparison, hashlib.sha256(comparison_bytes).hexdigest()


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
    multiview_comparison_path: Path | None = None,
    minimum_improvement: float = 0.001,
) -> ConvergenceReport:
    """Accept only direct improvements without measured or structural regressions."""

    before = VisualQAReport.model_validate_json(
        before_report_path.read_text(encoding="utf-8")
    )
    after = VisualQAReport.model_validate_json(after_report_path.read_text(encoding="utf-8"))
    if before.job_id != after.job_id:
        raise ValueError("convergence reports belong to different jobs")
    if before.camera_fingerprint != after.camera_fingerprint:
        raise ValueError("convergence requires the same fixed comparison camera")
    multiview_required = _authored_spatial_multiview_required(before.job_id)
    if multiview_required and multiview_comparison_path is None:
        raise ValueError(
            "authored spatial_v1 convergence requires an exact per-iteration "
            "multi-view structural comparison"
        )
    multiview_comparison: StructuralRegressionReport | None = None
    multiview_comparison_sha256: str | None = None
    if multiview_comparison_path is not None:
        (
            multiview_comparison,
            multiview_comparison_sha256,
        ) = _load_revalidated_multiview_comparison(
            multiview_comparison_path,
            expected_job_id=before.job_id,
        )
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
    elif multiview_comparison is not None and (multiview_comparison.status == "regressed"):
        status = "regressed"
        reasons.append(
            "Exact five-view assembly evidence regressed; this evidence is a "
            "veto-only rollback guard."
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
        multiview_status=(
            multiview_comparison.status if multiview_comparison is not None else "not_applicable"
        ),
        multiview_baseline_run_id=(
            multiview_comparison.baseline.run_id if multiview_comparison is not None else None
        ),
        multiview_baseline_report_sha256=(
            multiview_comparison.baseline.report_sha256
            if multiview_comparison is not None
            else None
        ),
        multiview_result_run_id=(
            multiview_comparison.result.run_id if multiview_comparison is not None else None
        ),
        multiview_result_report_sha256=(
            multiview_comparison.result.report_sha256 if multiview_comparison is not None else None
        ),
        multiview_comparison_sha256=(
            multiview_comparison_sha256
        ),
        multiview_regression_ids=(
            [item.id for item in multiview_comparison.regressions]
            if multiview_comparison is not None
            else []
        ),
        changed_ids=changed_ids,
        preserved_ids=preserved_ids,
        status=status,
        accepted=accepted,
        rollback_required=not accepted,
        reasons=reasons,
    )
