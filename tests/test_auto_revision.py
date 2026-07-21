import json
from pathlib import Path

import pytest

from codex_blender_modeler.auto_revision import (
    apply_approved_revision,
    build_revision_candidates,
    compile_revision_plan,
    create_revision_approval,
    evaluate_convergence,
)
from codex_blender_modeler.auto_revision.models import RevisionCandidates
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.models import (
    BoundingBoxMetric,
    DirectVisualMetrics,
    QAFinding,
    SuggestedEdit,
    VisualQAReport,
)
from codex_blender_modeler.workspace import sha256_file

SHA = "0" * 64


def _scene_fixture(tmp_path: Path) -> Path:
    """Copy the geometry showcase SceneSpec to an isolated canonical fixture."""

    root = Path(__file__).resolve().parents[1]
    source = root / "examples" / "geometry_showcase" / "scene_spec.seed.json"
    destination = tmp_path / "scene_spec.json"
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def _metrics(score: float) -> DirectVisualMetrics:
    """Build compact valid direct metrics for revision and convergence tests."""

    return DirectVisualMetrics(
        silhouette_iou=score,
        silhouette_union_fraction=0.5,
        global_bbox=BoundingBoxMetric(
            reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            rendered_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            center_error_norm=0,
            size_error_norm=0,
        ),
        overall_direct_score=score,
    )


def _report(scene_path: Path, findings: list[QAFinding], score: float = 0.7) -> VisualQAReport:
    """Create a report bound to the fixture comparison camera."""

    return VisualQAReport(
        job_id="geometry_showcase",
        run_id="run-001",
        request_sha256=SHA,
        camera_fingerprint=camera_fingerprint(scene_path),
        direct_metrics=_metrics(score),
        findings=findings,
        generated_target_status="not_requested",
    )


def _safe_finding() -> QAFinding:
    """Create one direct-reference suggestion against an inline SceneSpec numeric path."""

    return QAFinding(
        id="house.raise",
        target_ids=["demo.profile_house"],
        issue_type="position",
        severity="medium",
        description="Raise only the profile house.",
        evidence_sources=["direct_reference"],
        confidence=0.9,
        suggestion=SuggestedEdit(
            target_type="object",
            target_id="demo.profile_house",
            path=["transform", "location", 2],
            op="add",
            value=0.25,
        ),
    )


def test_candidate_builder_keeps_custom_mesh_payload_manual(tmp_path: Path) -> None:
    """External or inline custom-mesh geometry edits never become automatically applicable."""

    scene_path = _scene_fixture(tmp_path)
    findings = [
        _safe_finding(),
        QAFinding(
            id="pyramid.vertices",
            target_ids=["demo.custom_pyramid"],
            issue_type="proportion",
            severity="medium",
            description="Change custom mesh vertices.",
            evidence_sources=["direct_reference"],
            confidence=0.8,
            suggestion=SuggestedEdit(
                target_type="object",
                target_id="demo.custom_pyramid",
                path=["geometry", "vertices", 0, 2],
                op="add",
                value=0.1,
            ),
        ),
    ]
    report = _report(scene_path, findings)
    report_path = tmp_path / "visual_qa_report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    candidates = build_revision_candidates(
        report,
        report_path=report_path,
        scene_spec_path=scene_path,
    )
    by_id = {candidate.id: candidate for candidate in candidates.candidates}
    assert by_id["candidate.house.raise"].applicability == "approval_required"
    assert by_id["candidate.pyramid.vertices"].applicability == "manual_required"


def test_generated_target_only_candidate_cannot_be_auto_safe() -> None:
    """Advisory generated imagery alone cannot authorize a model mutation."""

    from codex_blender_modeler.auto_revision.models import RevisionCandidate

    with pytest.raises(ValueError, match="generated-target-only"):
        RevisionCandidate(
            id="candidate.generated",
            finding_id="generated",
            target_type="object",
            target_id="demo.profile_house",
            path=["transform", "scale", 2],
            op="multiply",
            value=1.1,
            reason="advisory only",
            evidence_sources=["generated_target"],
            confidence=0.8,
            applicability="auto_safe",
            acceptance_criteria=["looks taller"],
        )


def test_approved_revision_is_exact_single_use_and_preserves_camera(tmp_path: Path) -> None:
    """A hash-bound approval applies one safe candidate once without camera drift."""

    scene_path = _scene_fixture(tmp_path)
    report = _report(scene_path, [_safe_finding()])
    report_path = tmp_path / "visual_qa_report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    candidates = build_revision_candidates(
        report,
        report_path=report_path,
        scene_spec_path=scene_path,
    )
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(candidates.model_dump_json(indent=2), encoding="utf-8")
    plan_path = tmp_path / "revision_plan.json"
    compile_revision_plan(
        candidates_path=candidates_path,
        scene_spec_path=scene_path,
        selected_candidate_ids=["candidate.house.raise"],
        request="Raise the house only.",
        output_path=plan_path,
    )
    approval_path = tmp_path / "approval.json"
    create_revision_approval(
        candidates_path=candidates_path,
        plan_path=plan_path,
        approved_candidate_ids=["candidate.house.raise"],
        output_path=approval_path,
    )
    before = json.loads(scene_path.read_text(encoding="utf-8"))
    output = tmp_path / "scene_spec.next.json"
    result = apply_approved_revision(
        scene_spec_path=scene_path,
        candidates_path=candidates_path,
        plan_path=plan_path,
        approval_path=approval_path,
        output_path=output,
    )
    after = json.loads(output.read_text(encoding="utf-8"))
    before_house = next(item for item in before["objects"] if item["id"] == "demo.profile_house")
    after_house = next(item for item in after["objects"] if item["id"] == "demo.profile_house")
    assert after_house["transform"]["location"][2] == pytest.approx(
        before_house["transform"]["location"][2] + 0.25
    )
    assert before["camera"] == after["camera"]
    assert result["approval_used"] is True
    with pytest.raises(ValueError, match="already used"):
        apply_approved_revision(
            scene_spec_path=scene_path,
            candidates_path=candidates_path,
            plan_path=plan_path,
            approval_path=approval_path,
            output_path=tmp_path / "second.json",
        )


def test_convergence_requires_direct_improvement_without_constraint_regression(
    tmp_path: Path,
) -> None:
    """Convergence rejects higher visual scores when measured constraints regress."""

    scene_path = _scene_fixture(tmp_path)
    before = _report(scene_path, [], score=0.7)
    after = _report(scene_path, [], score=0.8)
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(before.model_dump_json(indent=2), encoding="utf-8")
    after_path.write_text(after.model_dump_json(indent=2), encoding="utf-8")
    result = evaluate_convergence(
        before_report_path=before_path,
        after_report_path=after_path,
        changed_ids=["demo.profile_house"],
        preserved_ids=["demo.custom_pyramid"],
        before_failed_constraints=0,
        after_failed_constraints=1,
    )
    assert result.status == "regressed"
    assert result.accepted is False
    assert result.rollback_required is True


def test_convergence_rejects_mixed_direct_scoring_contracts(tmp_path: Path) -> None:
    """A numerically higher V2 score cannot authorize revision against a legacy baseline."""

    scene_path = _scene_fixture(tmp_path)
    before = _report(scene_path, [], score=0.7)
    after = _report(scene_path, [], score=0.8)
    after = after.model_copy(
        update={
            "direct_metrics": after.direct_metrics.model_copy(
                update={"scoring_version": "semantic_bbox_v2"}
            )
        }
    )
    before_path = tmp_path / "before-version.json"
    after_path = tmp_path / "after-version.json"
    before_path.write_text(before.model_dump_json(indent=2), encoding="utf-8")
    after_path.write_text(after.model_dump_json(indent=2), encoding="utf-8")

    result = evaluate_convergence(
        before_report_path=before_path,
        after_report_path=after_path,
        changed_ids=["demo.profile_house"],
        preserved_ids=[],
    )

    assert result.status == "regressed"
    assert result.accepted is False
    assert result.rollback_required is True
    assert "legacy_bbox_v1 -> semantic_bbox_v2" in result.reasons[0]


def test_convergence_detects_per_id_status_swap_with_same_failure_count(
    tmp_path: Path,
) -> None:
    """A pass-to-fail regression cannot be hidden by another constraint improving."""

    scene_path = _scene_fixture(tmp_path)
    before = _report(scene_path, [], score=0.7)
    after = _report(scene_path, [], score=0.8)
    before_path = tmp_path / "before-swap.json"
    after_path = tmp_path / "after-swap.json"
    before_path.write_text(before.model_dump_json(indent=2), encoding="utf-8")
    after_path.write_text(after.model_dump_json(indent=2), encoding="utf-8")
    common = {
        "kind": "dimension",
        "requested": 1.0,
        "actual": 1.0,
        "tolerance_m": 0.1,
        "message": "mock",
    }
    result = evaluate_convergence(
        before_report_path=before_path,
        after_report_path=after_path,
        changed_ids=["demo.profile_house"],
        preserved_ids=[],
        before_failed_constraints=1,
        after_failed_constraints=1,
        before_constraint_results=[
            {**common, "id": "constraint.a", "status": "passed", "residual_m": 0.02},
            {**common, "id": "constraint.b", "status": "failed", "residual_m": 0.2},
        ],
        after_constraint_results=[
            {**common, "id": "constraint.a", "status": "failed", "residual_m": 0.2},
            {**common, "id": "constraint.b", "status": "passed", "residual_m": 0.02},
        ],
    )
    assert result.status == "regressed"
    assert [item.constraint_id for item in result.constraint_regressions] == [
        "constraint.a"
    ]


def test_convergence_detects_worse_residual_ratio_while_still_passing(
    tmp_path: Path,
) -> None:
    """A same-status residual/tolerance increase is a measured regression."""

    scene_path = _scene_fixture(tmp_path)
    before = _report(scene_path, [], score=0.7)
    after = _report(scene_path, [], score=0.8)
    before_path = tmp_path / "before-residual.json"
    after_path = tmp_path / "after-residual.json"
    before_path.write_text(before.model_dump_json(indent=2), encoding="utf-8")
    after_path.write_text(after.model_dump_json(indent=2), encoding="utf-8")
    common = {
        "id": "constraint.width",
        "kind": "dimension",
        "status": "passed",
        "requested": 1.0,
        "actual": 1.0,
        "tolerance_m": 0.1,
        "message": "mock",
    }
    result = evaluate_convergence(
        before_report_path=before_path,
        after_report_path=after_path,
        changed_ids=["demo.profile_house"],
        preserved_ids=[],
        before_constraint_results=[{**common, "residual_m": 0.02}],
        after_constraint_results=[{**common, "residual_m": 0.08}],
    )
    regression = result.constraint_regressions[0]
    assert result.status == "regressed"
    assert regression.constraint_id == "constraint.width"
    assert regression.before_residual_ratio == pytest.approx(0.2)
    assert regression.after_residual_ratio == pytest.approx(0.8)


def test_candidate_bundle_hash_matches_source_scene(tmp_path: Path) -> None:
    """Candidate bundles remain bound to the exact SceneSpec content hash."""

    scene_path = _scene_fixture(tmp_path)
    report = _report(scene_path, [_safe_finding()])
    report_path = tmp_path / "report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    candidates = build_revision_candidates(
        report,
        report_path=report_path,
        scene_spec_path=scene_path,
    )
    assert isinstance(candidates, RevisionCandidates)
    assert candidates.base_spec_sha256 == sha256_file(scene_path)
