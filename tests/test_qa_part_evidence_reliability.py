"""Narrow shared whole-object evidence guards without score or historical model migration."""

from __future__ import annotations

import copy
import json

import pytest
from test_autonomy_candidate_quality_aq import _report as _candidate_projection
from test_integrated_quality_aq import _visual_report
from test_qa_suggestion_enrichment import (
    TARGET_ID,
    _scene_spec,
)
from test_qa_suggestion_enrichment import (
    _report as _suggestion_report,
)
from test_reference_fidelity_files import file_fixture
from test_visual_convergence_contracts import _plan
from test_visual_qa import _rectangle_image, _request

from codex_blender_modeler.auto_revision.convergence import evaluate_convergence
from codex_blender_modeler.auto_revision.convergence_session import _target_reached
from codex_blender_modeler.autonomy.candidate_evaluator import _candidate_stage_assessment
from codex_blender_modeler.integrated_quality import AxisThreshold, reference_alignment_axis
from codex_blender_modeler.qa import direct_compare
from codex_blender_modeler.qa.direct_compare import (
    ambiguous_semantic_targets,
    compare_reference_to_render,
    direct_evidence_requires_review,
)
from codex_blender_modeler.qa.models import (
    BoundingBoxMetric,
    QAFinding,
    SemanticDeviation,
    SuggestedEdit,
    VisualQAReport,
)
from codex_blender_modeler.qa.suggestion_enrichment import enrich_direct_qa_suggestions
from codex_blender_modeler.reference_fidelity.models import VisualFindingSetV01
from codex_blender_modeler.reference_fidelity.service import (
    artifact_at,
    evaluate_review_file,
    publish,
)
from codex_blender_modeler.reporting.pdf_renderer import _append_qa_section, _report_styles

WHOLE = (0.1, 0.1, 0.9, 0.9)
SMALL = (0.2, 0.2, 0.3, 0.3)


def _deviation(target: str, box=WHOLE, confidence=0.91) -> SemanticDeviation:
    """Construct an observed reference box independently of rendered visibility."""

    return SemanticDeviation(
        target_id=target,
        metric=BoundingBoxMetric(reference_bbox_norm=box, rendered_bbox_norm=None),
        confidence=confidence,
    )


def _report_with_boxes(boxes, *, confidence=0.91) -> VisualQAReport:
    """Create immutable metric fixtures whose direct numbers have a known baseline."""

    report = _visual_report(0.99, silhouette_iou=0.99)
    return report.model_copy(
        update={
            "direct_metrics": report.direct_metrics.model_copy(
                update={
                    "semantic_deviations": [
                        _deviation(target, box, confidence) for target, box in boxes.items()
                    ],
                }
            ),
        }
    )


def _flag(report: VisualQAReport, *, warning_only=False) -> VisualQAReport:
    """Add the new evidence marker to a derivative without changing source fixture bytes."""

    if warning_only:
        return report.model_copy(
            update={
                "warnings": ["SEMANTIC_PART_EVIDENCE_REVIEW_REQUIRED: fixture evidence ambiguity"],
            }
        )
    return report.model_copy(
        update={
            "findings": [
                *report.findings,
                QAFinding(
                    id="direct.evidence.shared_whole_object_bbox",
                    target_ids=["asset.a", "asset.b"],
                    issue_type="other",
                    severity="medium",
                    description="Fixture evidence ambiguity, not a geometry defect verdict.",
                    evidence_sources=["direct_reference"],
                    confidence=1.0,
                ),
            ]
        }
    )


@pytest.mark.parametrize("confidence", [0.0, 0.69, 0.7, 0.91, 1.0])
def test_duplicate_whole_boxes_are_evidence_ambiguity_at_any_confidence(confidence) -> None:
    """Self-reported confidence and missing rendered pixels cannot validate shared boxes."""

    report = _report_with_boxes({"z": WHOLE, "a": WHOLE}, confidence=confidence)
    before = report.model_dump_json()
    assert ambiguous_semantic_targets(report.direct_metrics) == ("a", "z")
    assert report.model_dump_json() == before
    assert not direct_evidence_requires_review(report)  # Legacy reads are never relabeled.


@pytest.mark.parametrize(
    "boxes",
    [
        {},
        {"one": WHOLE},
        {"a": SMALL, "b": SMALL},
        {"a": WHOLE, "b": (0.10001, 0.1, 0.9, 0.9)},
        {"a": (0.1, 0.1, 0.7, 0.7), "b": (0.3, 0.3, 0.9, 0.9)},
        {"a": (0.1, 0.1, 0.5, 0.9), "b": (0.1, 0.1, 0.5, 0.9)},
    ],
)
def test_distinct_single_missing_and_local_overlap_boxes_are_not_flagged(boxes) -> None:
    """Avoid treating legitimate localized overlap or an entire single object as a defect."""

    assert ambiguous_semantic_targets(_report_with_boxes(boxes).direct_metrics) == ()


def test_duplicate_detection_is_sorted_and_only_targets_whole_box_groups() -> None:
    """Multiple exact groups have deterministic output independent of source insertion order."""

    another = (0.0, 0.0, 1.0, 1.0)
    boxes = {"z": WHOLE, "q": SMALL, "d": another, "b": another, "a": WHOLE, "s": SMALL}
    expected = ("a", "b", "d", "z")
    assert ambiguous_semantic_targets(_report_with_boxes(boxes).direct_metrics) == expected
    assert (
        ambiguous_semantic_targets(
            _report_with_boxes(dict(reversed(list(boxes.items())))).direct_metrics
        )
        == expected
    )


def test_actual_comparison_preserves_numbers_and_all_existing_findings(tmp_path, monkeypatch):
    """A new diagnostic adds evidence provenance without improving scores or resolving defects."""

    mask = tmp_path / "reference.png"
    object_id = tmp_path / "object.png"
    _rectangle_image(mask)
    _rectangle_image(object_id, rgb=True, box=(35, 20, 54, 39))
    regions = {
        "asset.z": ((0.2, 0.125, 0.6, 0.625), 0.91),
        "asset.a": ((0.2, 0.125, 0.6, 0.625), 0.91),
    }
    original_regions = copy.deepcopy(regions)
    kwargs = dict(
        silhouette_path=mask,
        object_id_path=object_id,
        object_id_colors={"asset.a": "#ff0000", "asset.z": "#00ff00"},
        observed_regions=regions,
    )
    with monkeypatch.context() as local:
        local.setattr(direct_compare, "ambiguous_semantic_targets", lambda _metrics: ())
        baseline = compare_reference_to_render(_request(mask, True), **kwargs)
    report = compare_reference_to_render(_request(mask, True), **kwargs)
    assert report.direct_metrics == baseline.direct_metrics
    assert report.findings[:-1] == baseline.findings
    assert report.findings[-1].issue_type == "other"
    assert report.findings[-1].target_ids == ["asset.a", "asset.z"]
    assert "not a geometry defect verdict" in report.findings[-1].description
    assert report.warnings[:-1] == baseline.warnings
    assert direct_evidence_requires_review(report)
    assert regions == original_regions
    assert VisualQAReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("preexisting", [False, True])
def test_only_affected_part_transform_suggestions_are_withheld(preexisting) -> None:
    """Ambiguous reference parts cannot create or preserve unsafe derivative transform edits."""

    spec = _scene_spec()
    metric = BoundingBoxMetric(
        reference_bbox_norm=WHOLE,
        rendered_bbox_norm=(0.2, 0.1, 1.0, 0.9),
        center_error_norm=0.070711,
        size_error_norm=0,
    )
    report = _suggestion_report(metric, issue_type="position")
    other_target = "demo.custom_pyramid"
    distinct_target = next(
        item.id for item in spec.objects if item.id not in {TARGET_ID, other_target}
    )
    distinct_metric = metric.model_copy(
        update={
            "reference_bbox_norm": (0.4, 0.4, 0.6, 0.6),
            "rendered_bbox_norm": (0.3, 0.4, 0.5, 0.6),
        }
    )
    report.direct_metrics.semantic_deviations.extend(
        [
            _deviation(other_target),
            SemanticDeviation(target_id=distinct_target, metric=distinct_metric, confidence=0.95),
        ]
    )
    report.findings.append(
        report.findings[0].model_copy(
            update={
                "id": "direct.position.distinct",
                "target_ids": [distinct_target],
            }
        )
    )
    if preexisting:
        report.findings[0].suggestion = SuggestedEdit(
            target_type="object",
            target_id=TARGET_ID,
            path=["transform", "location"],
            op="set",
            value=[0, 0, 0],
        )
    before = report.model_dump_json()
    enriched = enrich_direct_qa_suggestions(report, spec)
    assert enriched.findings[0].suggestion is None
    assert enriched.findings[1].suggestion is not None
    assert enriched.direct_metrics == report.direct_metrics
    assert report.model_dump_json() == before


@pytest.mark.parametrize("warning_only", [False, True])
def test_iq_and_aq_candidate_do_not_trust_flagged_high_score(warning_only) -> None:
    """New markers make reference evidence unscorable despite perfect scores and clean gates."""

    report = _flag(_visual_report(1.0, silhouette_iou=1.0), warning_only=warning_only)
    before = report.model_dump_json()
    axis = reference_alignment_axis(
        report,
        threshold=AxisThreshold(axis="reference_alignment", pass_score=0.8, warning_score=0.6),
        evidence_id="reference",
    )
    assert axis.status == "unscorable" and axis.score is None and axis.confidence == 0
    assert axis.metrics[0].value == 1.0
    projection = _candidate_projection()
    projection.axes = [axis]
    assert _candidate_stage_assessment(projection).evidence_status == "unscorable"
    assert report.model_dump_json() == before


def test_fidelity_consumer_refuses_flagged_evidence_with_exact_valid_hashes(tmp_path, monkeypatch):
    """The campaign's review gate rejects ambiguous evidence rather than accepting high floors."""

    root, evidence = file_fixture(tmp_path, monkeypatch)
    original_path = root / evidence.qa_report.path
    before = original_path.read_bytes()
    report = _flag(VisualQAReport.model_validate_json(before))
    derivative = root / "fidelity/flagged_report.json"
    derivative.write_text(report.model_dump_json())
    rating = VisualFindingSetV01.model_validate_json((root / "fidelity/review.json").read_bytes())
    rating = rating.model_copy(
        update={
            "evidence": rating.evidence.model_copy(
                update={
                    "qa_report": artifact_at(root, derivative),
                }
            )
        }
    )
    publish(root, root / "fidelity/flagged_review.json", rating)
    with pytest.raises(ValueError, match="semantic part evidence requires review"):
        evaluate_review_file(
            root, root / "fidelity/flagged_review.json", root / "fidelity/blocked.json"
        )
    assert not (root / "fidelity/blocked.json").exists()
    assert original_path.read_bytes() == before


@pytest.mark.parametrize("flag_before", [False, True])
def test_convergence_refuses_flagged_score_even_when_it_improves(tmp_path, flag_before) -> None:
    """Do not mislabel evidence ambiguity as a geometry regression or accept a numeric gain."""

    before = _visual_report(0.8)
    after = _visual_report(1.0)
    reports = [_flag(before) if flag_before else before, after if flag_before else _flag(after)]
    paths = [tmp_path / "before.json", tmp_path / "after.json"]
    for path, report in zip(paths, reports, strict=True):
        path.write_text(report.model_dump_json())
    original_bytes = [path.read_bytes() for path in paths]
    with pytest.raises(ValueError, match="evidence requires review before convergence scoring"):
        evaluate_convergence(
            before_report_path=paths[0],
            after_report_path=paths[1],
            changed_ids=[],
            preserved_ids=[],
        )
    assert [path.read_bytes() for path in paths] == original_bytes


def test_convergence_target_cannot_be_reached_with_flagged_evidence() -> None:
    """A perfect direct score cannot complete a bounded session with an evidence blocker."""

    report = _visual_report(1.0, silhouette_iou=1.0)
    assert _target_reached(_plan(), report)
    with pytest.raises(ValueError, match="evidence requires review before convergence targets"):
        _target_reached(_plan(), _flag(report))


def test_pdf_places_evidence_warning_next_to_direct_score(monkeypatch) -> None:
    """Derived score displays retain a visible reliability warning without altering raw data."""

    from codex_blender_modeler.reporting import pdf_renderer

    report = _flag(_visual_report(1.0), warning_only=True)
    monkeypatch.setattr(pdf_renderer, "_append_qa_companion_section", lambda *args: None)
    monkeypatch.setattr(pdf_renderer, "_append_qa_images", lambda *args, **kwargs: None)
    story = []
    _append_qa_section(
        story,
        {"visual_qa_report": json.loads(report.model_dump_json())},
        {},
        _report_styles({"regular": "Helvetica", "bold": "Helvetica-Bold"}),
    )
    paragraphs = [item.getPlainText() for item in story if hasattr(item, "getPlainText")]
    assert any("SEMANTIC_PART_EVIDENCE_REVIEW_REQUIRED" in text for text in paragraphs)


def test_historical_unmarked_report_serialization_and_scoring_are_unchanged() -> None:
    """Loading old V0.6 bytes neither adds a marker nor changes legacy axis interpretation."""

    original = _report_with_boxes({"a": WHOLE, "b": WHOLE})
    encoded = original.model_dump_json()
    loaded = VisualQAReport.model_validate_json(encoded)
    assert loaded.model_dump_json() == encoded
    assert not direct_evidence_requires_review(loaded)
    axis = reference_alignment_axis(
        loaded,
        threshold=AxisThreshold(axis="reference_alignment", pass_score=0.8, warning_score=0.6),
        evidence_id="reference",
    )
    assert axis.status == "passed" and axis.score == 0.99


@pytest.mark.parametrize("warning_only", [False, True])
def test_iq_v02_bridge_projects_ambiguity_as_unscorable_source_evidence(warning_only) -> None:
    """Independent companion numbers cannot conceal an explicit legacy evidence blocker."""

    from test_integrated_quality_v02_service import _report as _iq_report

    from codex_blender_modeler.integrated_quality.v02_v06_bridge import (
        project_authoritative_v06_findings_v02,
    )

    source = _flag(_visual_report(1.0, silhouette_iou=1.0), warning_only=warning_only)
    projected = project_authoritative_v06_findings_v02(source, evidence_id="v06-source")
    assert len(projected) == 1
    assert projected[0].category == "missing_evidence"
    report = _iq_report(extras=projected)
    assert report.outcome == "unscorable" and not report.quality_accepted
    assert report.legacy_v06_direct_score == 0.812345
    gate = next(
        item
        for item in report.hard_gates
        if item.reason_code == "semantic_part_evidence_requires_review"
    )
    assert gate.status == "unscorable" and not gate.blocking
    route = next(item for item in report.reentry if item.finding_id == projected[0].finding_id)
    assert route.destination == "manual_evidence_review"


def test_background_fast_review_retains_evidence_blocker_at_medium_severity(tmp_path, monkeypatch):
    """A medium diagnostic cannot disappear into decorative or supporting delivery roles."""

    from test_v08_background_quality import _evaluate, _quality_fixture

    diagnostic = (
        _flag(_visual_report(1.0))
        .findings[-1]
        .model_copy(
            update={
                "target_ids": ["environment.rocks", "environment.seabed"],
            }
        )
    )
    root, run_id, roles, fit_report, _scene = _quality_fixture(
        tmp_path,
        primary_box=(8, 8, 23, 23),
        findings=[diagnostic],
    )
    source_path = root / "qa" / "runs" / run_id / "visual_qa_report.json"
    before = source_path.read_bytes()
    report = _evaluate(monkeypatch, root, run_id, roles, fit_report)
    assert report.quality_status == "unscorable" and not report.quality_accepted
    assert any(
        "Semantic part evidence requires review" in item for item in report.unscorable_evidence
    )
    assert report.primary_silhouette_score == 0.929688
    assert source_path.read_bytes() == before


def test_partial_observation_coverage_is_visible_without_new_hard_failure(tmp_path) -> None:
    """Inferred parts stay outside direct scoring with a coverage notice, not a new gate."""

    mask = tmp_path / "mask.png"
    _rectangle_image(mask)
    report = compare_reference_to_render(
        _request(mask),
        silhouette_path=mask,
        object_id_colors={"asset.observed": "#ff0000", "asset.inferred": "#00ff00"},
        observed_regions={"asset.observed": ((0.2, 0.125, 0.6, 0.625), 0.91)},
    )
    assert not direct_evidence_requires_review(report)
    assert any("1/2 declared semantic targets" in warning for warning in report.warnings)
    assert len(report.direct_metrics.semantic_deviations) == 1


@pytest.mark.parametrize("status,confidence", [("inferred", 0.99), ("observed", 0.49)])
def test_partial_scope_clipping_fails_before_mask_publication(
    tmp_path, monkeypatch, status, confidence
):
    """A partial observed-part union cannot discard pixels from the independent source mask."""

    from test_reference_mask_refinement import _rectangle, _showcase_spec

    from codex_blender_modeler.models import SceneSpec
    from codex_blender_modeler.qa import reference_mask

    raw = _showcase_spec().model_dump(mode="json")
    raw["objects"] = raw["objects"][:2]
    raw["objects"][0]["tags"] = ["qa_role:primary"]
    raw["objects"][0]["evidence"][0]["bbox_norm"] = [0.4, 0.2, 0.8, 0.8]
    raw["objects"][1]["tags"] = ["qa_role:supporting"]
    raw["objects"][1]["evidence"][0].update(
        status=status, confidence=confidence, bbox_norm=[0.1, 0.1, 0.9, 0.9]
    )
    spec = SceneSpec.model_validate(raw)
    reference = tmp_path / "input/reference.png"
    source = tmp_path / "analysis/mask.png"
    _rectangle(reference, (10, 10, 89, 89))
    _rectangle(source, (10, 10, 89, 89))
    run = tmp_path / "run"
    run.mkdir()
    before = (reference.read_bytes(), source.read_bytes(), spec.model_dump_json())
    calls = []

    def no_refinement(*_args):
        """Record any attempted refinement, which must not happen after an unscorable scope."""
        calls.append(True)
        raise AssertionError("refinement must not be called")

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", no_refinement)
    with pytest.raises(ValueError, match="reference mask scope is unscorable.*1/2.*clip"):
        reference_mask.prepare_run_reference_mask(
            root=tmp_path,
            run_dir=run,
            reference_path=reference,
            analysis_mask_path=source,
            spec=spec,
            reference_content_scope="primary_object_only",
        )
    assert not calls and list(run.iterdir()) == []
    assert before == (reference.read_bytes(), source.read_bytes(), spec.model_dump_json())


def test_partial_scope_without_foreground_clipping_keeps_existing_behavior(tmp_path, monkeypatch):
    """An inferred part alone is not a new hard failure when observed bounds retain all pixels."""

    from test_reference_mask_refinement import _rectangle, _showcase_spec

    from codex_blender_modeler.models import SceneSpec
    from codex_blender_modeler.qa import reference_mask

    raw = _showcase_spec().model_dump(mode="json")
    raw["objects"] = raw["objects"][:2]
    raw["objects"][0]["tags"] = ["qa_role:primary"]
    raw["objects"][1]["tags"] = ["qa_role:supporting"]
    raw["objects"][1]["evidence"][0]["status"] = "inferred"
    spec = SceneSpec.model_validate(raw)
    reference = tmp_path / "input/reference.png"
    source = tmp_path / "analysis/mask.png"
    _rectangle(reference, (20, 20, 79, 79))
    _rectangle(source, (20, 20, 79, 79))
    run = tmp_path / "run"
    run.mkdir()
    before = source.read_bytes()

    def unavailable(*_args):
        """Exercise the ordinary existing fallback after the independent scope check passes."""
        raise RuntimeError("OpenCV unavailable for this fixture")

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", unavailable)
    output, _manifest = reference_mask.prepare_run_reference_mask(
        root=tmp_path,
        run_dir=run,
        reference_path=reference,
        analysis_mask_path=source,
        spec=spec,
        reference_content_scope="primary_object_only",
    )
    assert output.read_bytes() == before and source.read_bytes() == before


def test_explicit_trimap_cannot_bypass_partial_subject_scope_guard(tmp_path):
    """Existing V0.2 seeds do not authorize a different independent whole-subject extent."""

    from test_reference_mask_constraints import constraint_fixture

    from codex_blender_modeler.models import SceneSpec
    from codex_blender_modeler.qa.reference_mask import prepare_run_reference_mask

    reference, scene, _legacy, seed, source, _hypothesis = constraint_fixture(tmp_path)
    raw = scene.model_dump(mode="json")
    raw["objects"] = raw["objects"][:2]
    raw["objects"][0]["tags"] = ["qa_role:primary"]
    raw["objects"][0]["evidence"][0]["bbox_norm"] = [0.2, 0.2, 0.8, 0.8]
    raw["objects"][1]["tags"] = ["qa_role:supporting"]
    raw["objects"][1]["evidence"][0]["status"] = "inferred"
    scene = SceneSpec.model_validate(raw)
    seed = seed.model_copy(
        update={
            "reference_content_scope": "primary_object_only",
            "subject_object_ids": sorted(item.id for item in scene.objects),
        }
    )
    run = tmp_path / "run-partial-trimap"
    run.mkdir()
    before = (
        reference.read_bytes(),
        source.read_bytes(),
        (tmp_path / seed.trimap.path).read_bytes(),
    )
    with pytest.raises(ValueError, match="reference mask scope is unscorable"):
        prepare_run_reference_mask(
            root=tmp_path,
            run_dir=run,
            reference_path=reference,
            analysis_mask_path=source,
            spec=scene,
            seed_evidence=seed,
            reference_content_scope="primary_object_only",
        )
    assert list(run.iterdir()) == []
    assert before == (
        reference.read_bytes(),
        source.read_bytes(),
        (tmp_path / seed.trimap.path).read_bytes(),
    )
