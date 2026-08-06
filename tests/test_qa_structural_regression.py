from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from codex_blender_modeler.analysis.models import AssemblyFrame
from codex_blender_modeler.qa.multiview_sanity import (
    ASSEMBLY_SANITY_VIEW_IDS,
    AssemblySanityPlan,
    AssemblySanityReport,
    AssemblySanityViewCoverage,
    AssemblySanityViewPlan,
    GeometryReviewAssessment,
)
from codex_blender_modeler.qa.structural_regression import (
    AssemblySanityTerminalEvidence,
    compare_assembly_sanity_terminals,
    validate_terminal_evidence,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _evidence(run_id: str, sha256: str = SHA_A) -> AssemblySanityTerminalEvidence:
    """Build one exact run-owned terminal binding for comparison tests."""

    root = f"qa/assembly_sanity/runs/{run_id}"
    return AssemblySanityTerminalEvidence(
        run_id=run_id,
        plan_path=f"{root}/plan.json",
        plan_sha256=sha256,
        render_manifest_path=f"{root}/render_manifest.json",
        render_manifest_sha256=sha256,
        report_path=f"{root}/report.json",
        report_sha256=sha256,
    )


def _frame(*, changed: bool = False) -> AssemblyFrame:
    """Build a valid authored asset-local frame, optionally with changed axes."""

    return AssemblyFrame(
        root_object_id="asset.root",
        longitudinal_axis="X",
        lateral_axis="Z" if changed else "Y",
        vertical_axis="Y" if changed else "Z",
        evidence_status="authored",
    )


def _views(
    target_ids: list[str],
    *,
    changed: bool = False,
) -> list[AssemblySanityViewPlan]:
    """Build the exact ordered five-view contract used by structural diagnostics."""

    directions = {
        "front": (1.0, 0.0, 0.0),
        "right": (0.0, 1.0, 0.0),
        "top": (0.0, 0.0, 1.0),
        "rear": (-1.0, 0.0, 0.0),
        "oblique": (1.0, 1.0, 0.5),
    }
    if changed:
        directions["front"] = (0.5, 1.0, 0.0)
    return [
        AssemblySanityViewPlan(
            view_id=view_id,
            camera_direction_frame=directions[view_id],
            screen_up_role="longitudinal" if view_id == "top" else "vertical",
            target_ids=target_ids,
        )
        for view_id in ASSEMBLY_SANITY_VIEW_IDS
    ]


def _plan(
    run_id: str,
    *,
    targets: list[str] | None = None,
    changed_frame: bool = False,
    changed_views: bool = False,
    scene_sha256: str = SHA_A,
) -> AssemblySanityPlan:
    """Build one valid exterior-geometry-review plan for a fake exact terminal."""

    target_ids = targets or ["asset.root", "asset.wing"]
    return AssemblySanityPlan(
        job_id="asset",
        run_id=run_id,
        scene_spec_path="analysis/scene_spec.json",
        scene_spec_sha256=scene_sha256,
        modeling_plan_path="analysis/modeling_plan.json",
        modeling_plan_sha256=SHA_B,
        source_blend_path="blender/scene.blend",
        source_blend_sha256=SHA_C,
        build_fingerprint=SHA_A,
        source_fingerprint=SHA_B,
        review_policy="exterior_geometry_review_v2",
        assembly_frame=_frame(changed=changed_frame),
        target_ids=target_ids,
        resolution=(256, 256),
        views=_views(target_ids, changed=changed_views),
        created_at="2026-08-04T00:00:00+00:00",
    )


def _geometry_review(outcome: str) -> GeometryReviewAssessment:
    """Build a valid geometry-review outcome at the requested severity."""

    if outcome == "structurally_consistent":
        return GeometryReviewAssessment(
            outcome=outcome,
            v04_reentry="not_indicated",
            redesign_assessment="not_indicated",
        )
    return GeometryReviewAssessment(
        outcome=outcome,
        v04_reentry=("required" if outcome == "v04_reentry_required" else "recommended"),
        redesign_assessment="manual_review_required",
        redesign_scopes=["assembly"],
        reason_finding_ids=["assembly.regression"],
    )


def _report(
    run_id: str,
    *,
    targets: list[str] | None = None,
    visible: list[str] | None = None,
    structural_status: str = "passed",
    checks: list[dict[str, Any]] | None = None,
    geometry_outcome: str = "structurally_consistent",
    scene_sha256: str = SHA_A,
) -> AssemblySanityReport:
    """Build one valid report with explicit visibility and stable assembly checks."""

    target_ids = targets or ["asset.root", "asset.wing"]
    visible_ids = target_ids if visible is None else visible
    unseen_ids = sorted(set(target_ids) - set(visible_ids))
    coverage = [
        AssemblySanityViewCoverage(
            view_id=view_id,
            visible_target_ids=visible_ids,
            unseen_target_ids=unseen_ids,
            semantic_visibility_fraction=len(visible_ids) / len(target_ids),
        )
        for view_id in ASSEMBLY_SANITY_VIEW_IDS
    ]
    return AssemblySanityReport(
        job_id="asset",
        run_id=run_id,
        plan_sha256=SHA_A,
        render_manifest_sha256=SHA_A,
        scene_spec_sha256=scene_sha256,
        modeling_plan_sha256=SHA_B,
        source_blend_sha256=SHA_C,
        build_fingerprint=SHA_A,
        review_policy="exterior_geometry_review_v2",
        structural_status=structural_status,
        reference_comparison_note="No calibrated per-view references.",
        target_ids=target_ids,
        visible_target_ids=visible_ids,
        unseen_target_ids=unseen_ids,
        semantic_visibility_fraction=len(visible_ids) / len(target_ids),
        view_coverage=coverage,
        assembly_evaluation={"checks": checks or []},
        geometry_review=_geometry_review(geometry_outcome),
        generated_at="2026-08-04T00:00:00+00:00",
    )


def test_terminal_binding_rejects_non_run_owned_and_drive_paths() -> None:
    """Terminal evidence cannot bind an arbitrary path or Windows drive escape."""

    with pytest.raises(ValidationError, match="report_path must equal"):
        AssemblySanityTerminalEvidence(
            **{
                **_evidence("baseline").model_dump(),
                "report_path": "qa/assembly_sanity/report.json",
            }
        )
    with pytest.raises(ValidationError, match="job-relative POSIX"):
        AssemblySanityTerminalEvidence(
            **{
                **_evidence("baseline").model_dump(),
                "report_path": "C:/report.json",
            }
        )


def test_validate_terminal_evidence_replays_exact_hash_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The comparison wrapper delegates every exact path and hash to terminal replay."""

    from codex_blender_modeler.qa import structural_regression

    captured: dict[str, Any] = {}
    sentinels = (object(), object(), object())

    def fake_validate(root: Path, **kwargs: Any) -> tuple[object, object, object]:
        """Capture the authoritative replay arguments without reading Blender evidence."""

        captured["root"] = root
        captured.update(kwargs)
        return sentinels

    monkeypatch.setattr(
        structural_regression,
        "validate_assembly_sanity_terminal",
        fake_validate,
    )
    evidence = _evidence("baseline")

    result = validate_terminal_evidence(
        tmp_path,
        evidence,
        expected_job_id="asset",
    )

    assert result == sentinels
    assert captured["root"] == tmp_path
    assert (
        captured["plan_path"]
        == (tmp_path / "qa" / "assembly_sanity" / "runs" / "baseline" / "plan.json").resolve()
    )
    assert captured["plan_sha256"] == SHA_A
    assert captured["expected_job_id"] == "asset"
    assert captured["expected_run_id"] == "baseline"


def test_identical_contract_with_changed_scene_passes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A revised SceneSpec passes when every structural contract and outcome is stable."""

    from codex_blender_modeler.qa import structural_regression

    terminals = {
        "baseline": (_plan("baseline"), object(), _report("baseline")),
        "result": (
            _plan("result", scene_sha256=SHA_C),
            object(),
            _report("result", scene_sha256=SHA_C),
        ),
    }

    def fake_validate(
        root: Path,
        evidence: AssemblySanityTerminalEvidence,
        *,
        expected_job_id: str | None = None,
    ) -> tuple[Any, Any, Any]:
        """Return already-validated fake terminals selected by immutable run ID."""

        assert root == tmp_path
        assert expected_job_id == "asset"
        return terminals[evidence.run_id]

    monkeypatch.setattr(structural_regression, "validate_terminal_evidence", fake_validate)

    comparison = compare_assembly_sanity_terminals(
        tmp_path,
        baseline=_evidence("baseline"),
        result=_evidence("result"),
        expected_job_id="asset",
    )

    assert comparison.status == "passed"
    assert comparison.regressions == []
    assert comparison.veto_only is True
    assert comparison.automatic_revision_authorized is False
    assert comparison.reference_similarity_scored is False


def test_per_view_occlusion_change_does_not_veto_stable_aggregate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Ordinary one-view occlusion is advisory while all-view and aggregate state hold."""

    from codex_blender_modeler.qa import structural_regression

    baseline_report = _report("baseline", structural_status="warning")
    result_payload = _report(
        "result",
        structural_status="warning",
        scene_sha256=SHA_C,
    ).model_dump(mode="json")
    result_payload["view_coverage"][0] = {
        "view_id": "front",
        "visible_target_ids": ["asset.root"],
        "unseen_target_ids": ["asset.wing"],
        "semantic_visibility_fraction": 0.5,
    }
    result_report = AssemblySanityReport.model_validate(result_payload)
    terminals = {
        "baseline": (_plan("baseline"), object(), baseline_report),
        "result": (
            _plan("result", scene_sha256=SHA_C),
            object(),
            result_report,
        ),
    }

    def fake_validate(
        root: Path,
        evidence: AssemblySanityTerminalEvidence,
        *,
        expected_job_id: str | None = None,
    ) -> tuple[Any, Any, Any]:
        """Return terminals whose aggregate evidence is stable despite one occlusion."""

        assert root == tmp_path
        assert expected_job_id == "asset"
        return terminals[evidence.run_id]

    monkeypatch.setattr(structural_regression, "validate_terminal_evidence", fake_validate)

    comparison = compare_assembly_sanity_terminals(
        tmp_path,
        baseline=_evidence("baseline"),
        result=_evidence("result"),
        expected_job_id="asset",
    )

    assert comparison.status == "passed"
    assert comparison.regressions == []


def test_comparison_reports_every_required_structural_worsening(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Stable membership, required checks, visibility, and outcomes all veto on worsening."""

    from codex_blender_modeler.qa import structural_regression

    baseline_checks = [
        {"id": "check.axis", "required": True, "status": "passed"},
        {"id": "check.policy", "required": False, "status": "warning"},
        {"id": "check.removed", "required": True, "status": "passed"},
    ]
    result_checks = [
        {"id": "check.axis", "required": True, "status": "failed"},
        {"id": "check.policy", "required": True, "status": "warning"},
        {"id": "check.added", "required": True, "status": "passed"},
    ]
    terminals = {
        "baseline": (
            _plan("baseline"),
            object(),
            _report("baseline", checks=baseline_checks),
        ),
        "result": (
            _plan(
                "result",
                targets=["asset.root", "asset.pod"],
                changed_frame=True,
                changed_views=True,
                scene_sha256=SHA_C,
            ),
            object(),
            _report(
                "result",
                targets=["asset.root", "asset.pod"],
                visible=["asset.root"],
                structural_status="failed",
                checks=result_checks,
                geometry_outcome="v04_reentry_required",
                scene_sha256=SHA_C,
            ),
        ),
    }

    def fake_validate(
        root: Path,
        evidence: AssemblySanityTerminalEvidence,
        *,
        expected_job_id: str | None = None,
    ) -> tuple[Any, Any, Any]:
        """Return controlled terminal pairs for all regression dimensions."""

        assert root == tmp_path
        assert expected_job_id == "asset"
        return terminals[evidence.run_id]

    monkeypatch.setattr(structural_regression, "validate_terminal_evidence", fake_validate)

    comparison = compare_assembly_sanity_terminals(
        tmp_path,
        baseline=_evidence("baseline"),
        result=_evidence("result"),
        expected_job_id="asset",
    )

    categories = {item.category for item in comparison.regressions}
    assert comparison.status == "regressed"
    assert categories == {
        "target_membership",
        "assembly_frame",
        "view_contract",
        "check_membership",
        "required_check_contract",
        "required_check_status",
        "all_view_visibility",
        "structural_status",
        "geometry_review",
    }
    assert comparison.automatic_revision_authorized is False
