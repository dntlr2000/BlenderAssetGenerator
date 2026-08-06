"""Compare exact five-view assembly terminals as a revision veto-only guard."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ..models import StrictModel
from .multiview_sanity import (
    AssemblySanityPlan,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
    validate_assembly_sanity_terminal,
)

SHA256_PATTERN = r"^[0-9a-f]{64}$"
RUN_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,95}$"

_STATUS_SEVERITY = {"passed": 0, "warning": 1, "failed": 2}
_GEOMETRY_OUTCOME_SEVERITY = {
    "structurally_consistent": 0,
    "v04_reentry_recommended": 1,
    "v04_reentry_required": 2,
    "unscorable": 3,
}


def _validate_relative_path(value: str) -> str:
    """Require one normalized POSIX path contained by the owning job workspace."""

    if not value or "\x00" in value or "\\" in value or ":" in value or value.startswith("/"):
        raise ValueError("structural evidence path must be job-relative POSIX")
    parts = PurePosixPath(value).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("structural evidence path must not escape its job")
    return value


def _resolve_job_relative(root: Path, value: str) -> Path:
    """Resolve one strict job-relative evidence path without allowing escape."""

    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*PurePosixPath(value).parts)).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"structural evidence escapes the job: {value}") from exc
    return resolved


def _job_relative(root: Path, path: Path) -> str:
    """Convert one exact structural artifact path to portable job-relative form."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"structural artifact is outside the job: {path}") from exc


class AssemblySanityTerminalEvidence(StrictModel):
    """Bind one immutable five-view plan, manifest, and report terminal by exact hash."""

    run_id: str = Field(pattern=RUN_ID_PATTERN)
    plan_path: str
    plan_sha256: str = Field(pattern=SHA256_PATTERN)
    render_manifest_path: str
    render_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    report_path: str
    report_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("plan_path", "render_manifest_path", "report_path")
    @classmethod
    def validate_paths(cls, value: str) -> str:
        """Keep every terminal artifact path normalized and job-relative."""

        return _validate_relative_path(value)

    @model_validator(mode="after")
    def validate_run_ownership(self) -> AssemblySanityTerminalEvidence:
        """Require the three exact filenames below the declared assembly run root."""

        run_root = f"qa/assembly_sanity/runs/{self.run_id}"
        expected = {
            "plan_path": f"{run_root}/plan.json",
            "render_manifest_path": f"{run_root}/render_manifest.json",
            "report_path": f"{run_root}/report.json",
        }
        for field, value in expected.items():
            if getattr(self, field) != value:
                raise ValueError(f"{field} must equal {value}")
        return self


class StructuralRegressionFinding(StrictModel):
    """Describe one machine-verifiable structural worsening between exact terminals."""

    id: str
    category: Literal[
        "target_membership",
        "assembly_frame",
        "view_contract",
        "check_membership",
        "required_check_contract",
        "required_check_status",
        "all_view_visibility",
        "structural_status",
        "geometry_review",
    ]
    target_ids: list[str] = Field(default_factory=list)
    check_ids: list[str] = Field(default_factory=list)
    before: str | None = None
    after: str | None = None
    message: str


class StructuralRegressionReport(StrictModel):
    """Record a veto-only comparison without granting any revision authority."""

    schema_version: Literal["0.6.0"] = "0.6.0"
    comparison_kind: Literal["assembly_multiview_non_regression_v1"] = (
        "assembly_multiview_non_regression_v1"
    )
    job_id: str
    status: Literal["passed", "regressed"]
    baseline: AssemblySanityTerminalEvidence
    result: AssemblySanityTerminalEvidence
    baseline_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    result_scene_spec_sha256: str = Field(pattern=SHA256_PATTERN)
    modeling_plan_sha256: str = Field(pattern=SHA256_PATTERN)
    regressions: list[StructuralRegressionFinding] = Field(default_factory=list)
    veto_only: Literal[True] = True
    reference_similarity_scored: Literal[False] = False
    automatic_revision_authorized: Literal[False] = False
    generated_at: datetime

    @model_validator(mode="after")
    def validate_status(self) -> StructuralRegressionReport:
        """Require regression membership to agree with the terminal comparison status."""

        if (self.status == "regressed") != bool(self.regressions):
            raise ValueError("structural comparison status must match regressions")
        identifiers = [item.id for item in self.regressions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("structural regression IDs must be unique")
        return self


def terminal_evidence_from_run_result(
    root: Path,
    result: dict[str, Any],
) -> AssemblySanityTerminalEvidence:
    """Create one exact portable binding from an assembly-sanity service result."""

    return AssemblySanityTerminalEvidence(
        run_id=str(result["run_id"]),
        plan_path=_job_relative(root, Path(str(result["plan"]))),
        plan_sha256=str(result["plan_sha256"]),
        render_manifest_path=_job_relative(root, Path(str(result["render_manifest"]))),
        render_manifest_sha256=str(result["render_manifest_sha256"]),
        report_path=_job_relative(root, Path(str(result["report"]))),
        report_sha256=str(result["report_sha256"]),
    )


def validate_terminal_evidence(
    root: Path,
    evidence: AssemblySanityTerminalEvidence,
    *,
    expected_job_id: str | None = None,
) -> tuple[AssemblySanityPlan, AssemblySanityRenderManifest, AssemblySanityReport]:
    """Replay one exact terminal binding through the authoritative sanity validator."""

    return validate_assembly_sanity_terminal(
        root,
        plan_path=_resolve_job_relative(root, evidence.plan_path),
        plan_sha256=evidence.plan_sha256,
        manifest_path=_resolve_job_relative(root, evidence.render_manifest_path),
        manifest_sha256=evidence.render_manifest_sha256,
        report_path=_resolve_job_relative(root, evidence.report_path),
        report_sha256=evidence.report_sha256,
        expected_job_id=expected_job_id,
        expected_run_id=evidence.run_id,
    )


def _check_map(report: AssemblySanityReport) -> dict[str, dict[str, Any]]:
    """Index stable evaluated check IDs while rejecting malformed or duplicate records."""

    checks = report.assembly_evaluation.get("checks")
    if not isinstance(checks, list):
        raise ValueError("assembly structural evidence has no check array")
    indexed: dict[str, dict[str, Any]] = {}
    for raw in checks:
        if not isinstance(raw, dict):
            raise ValueError("assembly structural evidence contains a malformed check")
        check_id = raw.get("id")
        status = raw.get("status")
        if not isinstance(check_id, str) or not check_id:
            raise ValueError("assembly structural check has no stable ID")
        if check_id in indexed:
            raise ValueError(f"duplicate assembly structural check ID: {check_id}")
        if status not in _STATUS_SEVERITY:
            raise ValueError(f"assembly structural check has invalid status: {check_id}")
        required = raw.get("required", True)
        if not isinstance(required, bool):
            raise ValueError(
                f"assembly structural check has invalid required policy: {check_id}"
            )
        indexed[check_id] = {
            "status": str(status),
            "required": required,
        }
    return indexed


def _view_contract(plan: AssemblySanityPlan) -> list[tuple[object, ...]]:
    """Normalize the five planned frame directions for stable contract comparison."""

    return [
        (
            view.view_id,
            tuple(float(value) for value in view.camera_direction_frame),
            view.screen_up_role,
        )
        for view in plan.views
    ]


def compare_assembly_sanity_terminals(
    root: Path,
    *,
    baseline: AssemblySanityTerminalEvidence,
    result: AssemblySanityTerminalEvidence,
    expected_job_id: str | None = None,
    generated_at: datetime | None = None,
) -> StructuralRegressionReport:
    """Validate exact terminals and report only machine-verifiable structural regressions."""

    baseline_plan, _baseline_manifest, baseline_report = validate_terminal_evidence(
        root,
        baseline,
        expected_job_id=expected_job_id,
    )
    result_plan, _result_manifest, result_report = validate_terminal_evidence(
        root,
        result,
        expected_job_id=expected_job_id,
    )
    job_id = baseline_plan.job_id
    if result_plan.job_id != job_id:
        raise ValueError("structural terminals belong to different jobs")

    regressions: list[StructuralRegressionFinding] = []
    baseline_targets = set(baseline_plan.target_ids)
    result_targets = set(result_plan.target_ids)
    if baseline_targets != result_targets:
        regressions.append(
            StructuralRegressionFinding(
                id="structural.target_membership_changed",
                category="target_membership",
                target_ids=sorted(baseline_targets.symmetric_difference(result_targets)),
                before=",".join(sorted(baseline_targets)),
                after=",".join(sorted(result_targets)),
                message="Assembly-sanity target membership changed during revision.",
            )
        )
    if (
        baseline_plan.modeling_plan_sha256 != result_plan.modeling_plan_sha256
        or baseline_plan.assembly_frame != result_plan.assembly_frame
    ):
        regressions.append(
            StructuralRegressionFinding(
                id="structural.assembly_frame_changed",
                category="assembly_frame",
                message="The ModelingPlan or declared assembly frame changed.",
            )
        )
    if baseline_plan.review_policy != result_plan.review_policy or _view_contract(
        baseline_plan
    ) != _view_contract(result_plan):
        regressions.append(
            StructuralRegressionFinding(
                id="structural.view_contract_changed",
                category="view_contract",
                before=baseline_plan.review_policy,
                after=result_plan.review_policy,
                message="The five-view structural comparison contract changed.",
            )
        )

    baseline_checks = _check_map(baseline_report)
    result_checks = _check_map(result_report)
    baseline_check_ids = set(baseline_checks)
    result_check_ids = set(result_checks)
    if baseline_check_ids != result_check_ids:
        regressions.append(
            StructuralRegressionFinding(
                id="structural.check_membership_changed",
                category="check_membership",
                check_ids=sorted(baseline_check_ids.symmetric_difference(result_check_ids)),
                before=",".join(sorted(baseline_check_ids)),
                after=",".join(sorted(result_check_ids)),
                message="Evaluated assembly-check membership changed during revision.",
            )
        )
    for check_id in sorted(baseline_check_ids.intersection(result_check_ids)):
        before_check = baseline_checks[check_id]
        after_check = result_checks[check_id]
        if before_check["required"] != after_check["required"]:
            regressions.append(
                StructuralRegressionFinding(
                    id=f"structural.required_contract_changed.{check_id}",
                    category="required_check_contract",
                    check_ids=[check_id],
                    before=str(before_check["required"]).lower(),
                    after=str(after_check["required"]).lower(),
                    message="An assembly check changed its required policy.",
                )
            )
            continue
        if before_check["required"] and (
            _STATUS_SEVERITY[str(after_check["status"])]
            > _STATUS_SEVERITY[str(before_check["status"])]
        ):
            regressions.append(
                StructuralRegressionFinding(
                    id=f"structural.required_status_worsened.{check_id}",
                    category="required_check_status",
                    check_ids=[check_id],
                    before=str(before_check["status"]),
                    after=str(after_check["status"]),
                    message="A required assembly check worsened after revision.",
                )
            )

    # Per-view occlusion remains advisory; only loss from the five-view union vetoes.
    lost_visibility = sorted(
        set(baseline_report.visible_target_ids) - set(result_report.visible_target_ids)
    )
    if lost_visibility:
        regressions.append(
            StructuralRegressionFinding(
                id="structural.all_view_visibility_lost",
                category="all_view_visibility",
                target_ids=lost_visibility,
                message="Targets visible in the baseline disappeared from all five views.",
            )
        )
    if (
        _STATUS_SEVERITY[result_report.structural_status]
        > _STATUS_SEVERITY[baseline_report.structural_status]
    ):
        regressions.append(
            StructuralRegressionFinding(
                id="structural.status_worsened",
                category="structural_status",
                before=baseline_report.structural_status,
                after=result_report.structural_status,
                message="The aggregate structural status worsened after revision.",
            )
        )
    baseline_review = baseline_report.geometry_review
    result_review = result_report.geometry_review
    if (baseline_review is None) != (result_review is None):
        regressions.append(
            StructuralRegressionFinding(
                id="structural.geometry_review_contract_changed",
                category="geometry_review",
                before=baseline_review.outcome if baseline_review is not None else None,
                after=result_review.outcome if result_review is not None else None,
                message="Geometry-review outcome availability changed during revision.",
            )
        )
    elif (
        baseline_review is not None
        and result_review is not None
        and (
            _GEOMETRY_OUTCOME_SEVERITY[result_review.outcome]
            > _GEOMETRY_OUTCOME_SEVERITY[baseline_review.outcome]
        )
    ):
        regressions.append(
            StructuralRegressionFinding(
                id="structural.geometry_review_worsened",
                category="geometry_review",
                before=baseline_review.outcome,
                after=result_review.outcome,
                message="The manual V0.4 geometry-review outcome worsened after revision.",
            )
        )

    return StructuralRegressionReport(
        job_id=job_id,
        status="regressed" if regressions else "passed",
        baseline=baseline,
        result=result,
        baseline_scene_spec_sha256=baseline_plan.scene_spec_sha256,
        result_scene_spec_sha256=result_plan.scene_spec_sha256,
        modeling_plan_sha256=baseline_plan.modeling_plan_sha256,
        regressions=regressions,
        generated_at=generated_at or datetime.now(UTC),
    )


__all__ = [
    "AssemblySanityTerminalEvidence",
    "StructuralRegressionFinding",
    "StructuralRegressionReport",
    "compare_assembly_sanity_terminals",
    "terminal_evidence_from_run_result",
    "validate_terminal_evidence",
]
