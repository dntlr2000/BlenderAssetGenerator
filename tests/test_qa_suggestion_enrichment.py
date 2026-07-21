from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from codex_blender_modeler.auto_revision import (
    apply_approved_revision,
    build_revision_candidates,
    compile_revision_plan,
    create_revision_approval,
)
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.models import (
    BoundingBoxMetric,
    DirectVisualMetrics,
    QAFinding,
    SemanticDeviation,
    VisualQAReport,
)
from codex_blender_modeler.qa.suggestion_enrichment import (
    _semantic_group_key,
    enrich_direct_qa_suggestions,
)
from codex_blender_modeler.revision import RevisionOperation, RevisionPlan

SHA = "0" * 64
TARGET_ID = "demo.profile_house"


def _scene_spec(
    *,
    projection: str = "ORTHO",
    parented: bool = False,
    generated: bool = False,
) -> SceneSpec:
    """Load an isolated showcase SceneSpec with a deterministic comparison camera."""

    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    raw["camera"].update(
        {
            "projection": projection,
            "location": [0.0, -10.0, 5.0],
            "target": [0.0, 0.0, 0.0],
            "ortho_scale": 10.0,
            "resolution": [100, 100],
        }
    )
    target = next(item for item in raw["objects"] if item["id"] == TARGET_ID)
    if parented:
        target["parent_id"] = "demo.custom_pyramid"
    if generated:
        target["generator"] = {"kind": "array", "count": 3, "offset": [2, 0, 0]}
    return SceneSpec.model_validate(raw)


def _report(
    metric: BoundingBoxMetric,
    *,
    issue_type: str,
    confidence: float = 0.95,
    evidence_sources: list[str] | None = None,
) -> VisualQAReport:
    """Build one localized direct-QA report around a supplied bounding-box mismatch."""

    deviation = SemanticDeviation(
        target_id=TARGET_ID,
        metric=metric,
        confidence=confidence,
    )
    finding = QAFinding(
        id=f"direct.{issue_type}.{TARGET_ID}",
        target_ids=[TARGET_ID],
        issue_type=issue_type,
        severity="medium",
        description="Fixture mismatch.",
        evidence_sources=evidence_sources or ["direct_reference"],
        confidence=confidence,
    )
    return VisualQAReport(
        job_id="geometry_showcase",
        run_id="run-001",
        request_sha256=SHA,
        camera_fingerprint=SHA,
        direct_metrics=DirectVisualMetrics(
            silhouette_iou=0.7,
            silhouette_union_fraction=0.4,
            global_bbox=metric,
            semantic_deviations=[deviation],
            overall_direct_score=0.7,
        ),
        findings=[finding],
        generated_target_status="not_requested",
    )


def _group_scene_spec() -> SceneSpec:
    """Create one semantic group with two observed and one inferred transform member."""

    raw = json.loads(_scene_spec().model_dump_json())
    template = next(item for item in raw["objects"] if item["id"] == TARGET_ID)
    objects = []
    for object_id, location in (
        ("island.ocean.plateau", [0.0, 0.0, 0.0]),
        ("island.ocean.temple", [2.0, 1.0, 0.5]),
        ("island.ocean.hidden_back", [5.0, -1.0, 2.0]),
        ("island.forest.plateau", [-5.0, 0.0, 0.0]),
    ):
        item = copy.deepcopy(template)
        item["id"] = object_id
        item["parent_id"] = None
        item["generator"] = None
        item["transform"]["location"] = location
        objects.append(item)
    raw["objects"] = objects
    return SceneSpec.model_validate(raw)


def _group_report(spec: SceneSpec) -> VisualQAReport:
    """Build partial per-object evidence that can still support one complete group move."""

    metrics = {
        "island.ocean.plateau": BoundingBoxMetric(
            reference_bbox_norm=(0.4, 0.2, 0.5, 0.3),
            rendered_bbox_norm=(0.2, 0.2, 0.3, 0.3),
            center_error_norm=0.141421,
            size_error_norm=0,
        ),
        "island.ocean.temple": BoundingBoxMetric(
            reference_bbox_norm=(0.5, 0.3, 0.6, 0.4),
            rendered_bbox_norm=(0.3, 0.3, 0.4, 0.4),
            center_error_norm=0.141421,
            size_error_norm=0,
        ),
    }
    finding = QAFinding(
        id="direct.position.island.ocean.plateau",
        target_ids=["island.ocean.plateau"],
        issue_type="position",
        severity="medium",
        description="Only one member has an executable per-object finding.",
        evidence_sources=["direct_reference"],
        confidence=0.95,
    )
    return VisualQAReport(
        job_id=spec.job_id,
        run_id="group-run",
        request_sha256=SHA,
        camera_fingerprint=camera_fingerprint(spec),
        direct_metrics=DirectVisualMetrics(
            silhouette_iou=0.7,
            silhouette_union_fraction=0.4,
            global_bbox=next(iter(metrics.values())),
            semantic_deviations=[
                SemanticDeviation(target_id=target_id, metric=metric, confidence=0.95)
                for target_id, metric in metrics.items()
            ],
            overall_direct_score=0.7,
        ),
        findings=[finding],
        generated_target_status="not_requested",
    )


def _group_candidate_fixture(tmp_path: Path):
    """Persist one enriched group report and return its hash-bound candidate bundle."""

    spec = _group_scene_spec()
    report = enrich_direct_qa_suggestions(_group_report(spec), spec)
    scene_path = tmp_path / "scene_spec.json"
    report_path = tmp_path / "visual_qa_report.json"
    scene_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    candidates = build_revision_candidates(
        report,
        report_path=report_path,
        scene_spec_path=scene_path,
    )
    return spec, report, scene_path, candidates


def test_position_suggestion_maps_screen_direction_through_ortho_camera() -> None:
    """Reference-right and reference-up errors move along camera right and up, not axes blindly."""

    spec = _scene_spec()
    metric = BoundingBoxMetric(
        reference_bbox_norm=(0.5, 0.2, 0.7, 0.4),
        rendered_bbox_norm=(0.3, 0.4, 0.5, 0.6),
        center_error_norm=0.2,
        size_error_norm=0,
    )
    enriched = enrich_direct_qa_suggestions(
        _report(metric, issue_type="position"),
        spec,
    )
    finding = enriched.findings[0]
    assert finding.suggestion is not None
    assert finding.suggestion.path == ["transform", "location"]
    assert finding.suggestion.op == "set"
    original = next(item for item in spec.objects if item.id == TARGET_ID).transform.location
    proposed = finding.suggestion.value
    assert proposed[0] > original[0]
    assert proposed[1] > original[1]
    assert proposed[2] > original[2]
    assert finding.confidence == pytest.approx(0.7125)


def test_position_suggestion_clamps_large_but_non_extreme_center_delta() -> None:
    """One positional proposal cannot consume the full observed image-space error."""

    spec = _scene_spec()
    metric = BoundingBoxMetric(
        reference_bbox_norm=(0.6, 0.4, 0.8, 0.6),
        rendered_bbox_norm=(0.4, 0.4, 0.6, 0.6),
        center_error_norm=0.141421,
        size_error_norm=0,
    )
    enriched = enrich_direct_qa_suggestions(
        _report(metric, issue_type="position"),
        spec,
    )
    suggestion = enriched.findings[0].suggestion
    assert suggestion is not None
    original_x = next(item for item in spec.objects if item.id == TARGET_ID).transform.location[0]
    assert suggestion.value[0] - original_x == pytest.approx(0.4)
    assert suggestion.value[0] - original_x < 2.0


def test_proportion_suggestion_uses_clamped_uniform_scale_factor() -> None:
    """Consistent width and height ratios produce only one bounded uniform scale step."""

    spec = _scene_spec()
    metric = BoundingBoxMetric(
        reference_bbox_norm=(0.3, 0.3, 0.7, 0.7),
        rendered_bbox_norm=(0.357, 0.357, 0.643, 0.643),
        center_error_norm=0,
        size_error_norm=0.114,
    )
    enriched = enrich_direct_qa_suggestions(
        _report(metric, issue_type="proportion"),
        spec,
    )
    suggestion = enriched.findings[0].suggestion
    assert suggestion is not None
    assert suggestion.path == ["transform", "scale"]
    assert suggestion.op == "set"
    assert suggestion.value == pytest.approx([1.1, 1.1, 1.1])


@pytest.mark.parametrize(
    ("spec", "metric", "confidence", "sources"),
    [
        (
            _scene_spec(projection="PERSP"),
            BoundingBoxMetric(
                reference_bbox_norm=(0.5, 0.4, 0.7, 0.6),
                rendered_bbox_norm=(0.3, 0.4, 0.5, 0.6),
                center_error_norm=0.141421,
                size_error_norm=0,
            ),
            0.95,
            ["direct_reference"],
        ),
        (
            _scene_spec(),
            BoundingBoxMetric(
                reference_bbox_norm=(0.5, 0.4, 0.7, 0.6),
                rendered_bbox_norm=None,
            ),
            0.95,
            ["direct_reference"],
        ),
        (
            _scene_spec(),
            BoundingBoxMetric(
                reference_bbox_norm=(0.5, 0.4, 0.7, 0.6),
                rendered_bbox_norm=(0.3, 0.4, 0.5, 0.6),
                center_error_norm=0.141421,
                size_error_norm=0,
            ),
            0.6,
            ["direct_reference"],
        ),
        (
            _scene_spec(),
            BoundingBoxMetric(
                reference_bbox_norm=(0.5, 0.4, 0.7, 0.6),
                rendered_bbox_norm=(0.3, 0.4, 0.5, 0.6),
                center_error_norm=0.141421,
                size_error_norm=0,
            ),
            0.95,
            ["generated_target"],
        ),
        (
            _scene_spec(parented=True),
            BoundingBoxMetric(
                reference_bbox_norm=(0.5, 0.4, 0.7, 0.6),
                rendered_bbox_norm=(0.3, 0.4, 0.5, 0.6),
                center_error_norm=0.141421,
                size_error_norm=0,
            ),
            0.95,
            ["direct_reference"],
        ),
        (
            _scene_spec(),
            BoundingBoxMetric(
                reference_bbox_norm=(0.75, 0.75, 0.95, 0.95),
                rendered_bbox_norm=(0.05, 0.05, 0.25, 0.25),
                center_error_norm=0.7,
                size_error_norm=0,
            ),
            0.95,
            ["direct_reference"],
        ),
    ],
)
def test_position_suggestion_skips_ambiguous_or_untrusted_cases(
    spec: SceneSpec,
    metric: BoundingBoxMetric,
    confidence: float,
    sources: list[str],
) -> None:
    """Perspective, missing, weak, advisory, parented, and extreme cases remain manual."""

    enriched = enrich_direct_qa_suggestions(
        _report(
            metric,
            issue_type="position",
            confidence=confidence,
            evidence_sources=sources,
        ),
        spec,
    )
    assert enriched.findings[0].suggestion is None


@pytest.mark.parametrize(
    ("spec", "reference", "rendered"),
    [
        (_scene_spec(), (0.2, 0.2, 0.8, 0.8), (0.45, 0.45, 0.55, 0.55)),
        (_scene_spec(), (0.2, 0.3, 0.8, 0.7), (0.3, 0.2, 0.7, 0.8)),
        (_scene_spec(generated=True), (0.2, 0.2, 0.8, 0.8), (0.3, 0.3, 0.7, 0.7)),
    ],
)
def test_proportion_suggestion_skips_extreme_anisotropic_and_array_cases(
    spec: SceneSpec,
    reference: tuple[float, float, float, float],
    rendered: tuple[float, float, float, float],
) -> None:
    """Unsafe size mismatches do not become scale edits or custom geometry payload edits."""

    metric = BoundingBoxMetric(
        reference_bbox_norm=reference,
        rendered_bbox_norm=rendered,
        center_error_norm=0,
        size_error_norm=0.2,
    )
    enriched = enrich_direct_qa_suggestions(
        _report(metric, issue_type="proportion"),
        spec,
    )
    assert enriched.findings[0].suggestion is None


def test_group_finding_covers_inferred_members_despite_partial_object_findings() -> None:
    """Two observed components generate one group finding covering every stable group ID."""

    spec = _group_scene_spec()
    enriched = enrich_direct_qa_suggestions(_group_report(spec), spec)
    group = next(
        finding
        for finding in enriched.findings
        if finding.id == "direct.group_position.island.ocean"
    )

    assert group.target_ids == [
        "island.ocean.hidden_back",
        "island.ocean.plateau",
        "island.ocean.temple",
    ]
    assert group.metrics["observed_component_count"] == 2
    assert group.metrics["target_component_count"] == 3
    assert group.suggestion is None


def test_group_position_policy_is_limited_to_the_island_root() -> None:
    """Only the explicitly allow-listed island assembly namespace can form move groups."""

    assert _semantic_group_key("island.ocean.temple") == "island.ocean"
    assert _semantic_group_key("asset.ocean.temple") is None
    assert _semantic_group_key("building.block.window") is None


def test_group_finding_requires_reliable_observed_coverage() -> None:
    """Two observations cannot move an assembly when they cover under 60% of its members."""

    raw = json.loads(_group_scene_spec().model_dump_json())
    template = copy.deepcopy(raw["objects"][0])
    template["id"] = "island.ocean.auxiliary"
    template["transform"]["location"] = [7.0, -2.0, 1.0]
    raw["objects"].append(template)
    spec = SceneSpec.model_validate(raw)

    enriched = enrich_direct_qa_suggestions(_group_report(spec), spec)

    assert not any(
        finding.id == "direct.group_position.island.ocean"
        for finding in enriched.findings
    )


def test_group_finding_rejects_opposing_component_motion() -> None:
    """A member whose image correction opposes the union direction prevents a group move."""

    spec = _group_scene_spec()
    report = _group_report(spec)
    deviations = []
    for deviation in report.direct_metrics.semantic_deviations:
        if deviation.target_id == "island.ocean.temple":
            metric = deviation.metric.model_copy(
                update={
                    "rendered_bbox_norm": (0.6, 0.3, 0.7, 0.4),
                    "center_error_norm": 0.070711,
                }
            )
            deviation = deviation.model_copy(update={"metric": metric})
        deviations.append(deviation)
    direct_metrics = report.direct_metrics.model_copy(
        update={"semantic_deviations": deviations}
    )
    report = report.model_copy(update={"direct_metrics": direct_metrics})

    enriched = enrich_direct_qa_suggestions(report, spec)

    assert not any(
        finding.id == "direct.group_position.island.ocean"
        for finding in enriched.findings
    )


def test_group_candidates_preserve_all_pairwise_relative_offsets(tmp_path: Path) -> None:
    """Every generated group member receives exactly one identical bounded displacement."""

    spec, _report_value, _scene_path, candidates = _group_candidate_fixture(tmp_path)
    group_candidates = [
        candidate
        for candidate in candidates.candidates
        if candidate.finding_id == "direct.group_position.island.ocean"
    ]
    locations = {item.id: item.transform.location for item in spec.objects}
    deltas = {
        tuple(
            round(float(candidate.value[index]) - locations[str(candidate.target_id)][index], 6)
            for index in range(3)
        )
        for candidate in group_candidates
    }

    assert len(group_candidates) == 3
    assert len(deltas) == 1
    assert all(
        "candidate.direct.group_position.island.ocean.member." in item.id
        for item in group_candidates
    )
    before_offset = tuple(
        locations["island.ocean.hidden_back"][index]
        - locations["island.ocean.plateau"][index]
        for index in range(3)
    )
    proposed = {str(item.target_id): item.value for item in group_candidates}
    after_offset = tuple(
        proposed["island.ocean.hidden_back"][index]
        - proposed["island.ocean.plateau"][index]
        for index in range(3)
    )
    assert after_offset == pytest.approx(before_offset)


def test_group_candidates_lock_other_groups_and_require_atomic_selection(
    tmp_path: Path,
) -> None:
    """Non-target groups stay locked and compile rejects partial or conflicting selection."""

    _spec, _report_value, scene_path, candidates = _group_candidate_fixture(tmp_path)
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(candidates.model_dump_json(indent=2), encoding="utf-8")
    group_ids = [
        candidate.id
        for candidate in candidates.candidates
        if candidate.finding_id == "direct.group_position.island.ocean"
    ]
    individual_id = "candidate.direct.position.island.ocean.plateau"

    assert "island.forest.plateau" in candidates.locked_ids
    assert not any(target.startswith("island.ocean.") for target in candidates.locked_ids)
    with pytest.raises(ValueError, match="must be selected together"):
        compile_revision_plan(
            candidates_path=candidates_path,
            scene_spec_path=scene_path,
            selected_candidate_ids=group_ids[:-1],
            request="Unsafe partial group selection.",
            output_path=tmp_path / "partial_plan.json",
        )
    with pytest.raises(ValueError, match="conflicting target/path"):
        compile_revision_plan(
            candidates_path=candidates_path,
            scene_spec_path=scene_path,
            selected_candidate_ids=[*group_ids, individual_id],
            request="Unsafe group plus individual selection.",
            output_path=tmp_path / "conflicting_plan.json",
        )

    plan = compile_revision_plan(
        candidates_path=candidates_path,
        scene_spec_path=scene_path,
        selected_candidate_ids=group_ids,
        request="Move the complete ocean group coherently.",
        output_path=tmp_path / "group_plan.json",
    )
    assert len(plan.operations) == 3


def test_group_candidate_conflict_detects_descendant_paths(tmp_path: Path) -> None:
    """A full location group edit conflicts with a selected location-axis descendant edit."""

    _spec, _report_value, scene_path, candidates = _group_candidate_fixture(tmp_path)
    group_ids = [
        candidate.id
        for candidate in candidates.candidates
        if candidate.finding_id == "direct.group_position.island.ocean"
    ]
    individual = next(
        candidate
        for candidate in candidates.candidates
        if candidate.id == "candidate.direct.position.island.ocean.plateau"
    )
    descendant = individual.model_copy(
        update={
            "id": "candidate.direct.position.island.ocean.plateau.location_x",
            "path": ["transform", "location", 0],
            "value": float(individual.value[0]),
        }
    )
    expanded = candidates.model_copy(
        update={"candidates": [*candidates.candidates, descendant]}
    )
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(expanded.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicting target/path"):
        compile_revision_plan(
            candidates_path=candidates_path,
            scene_spec_path=scene_path,
            selected_candidate_ids=[*group_ids, descendant.id],
            request="Unsafe ancestor and descendant edit selection.",
            output_path=tmp_path / "descendant_conflict_plan.json",
        )


def test_compile_rejects_deleted_group_candidate(tmp_path: Path) -> None:
    """The source report target set detects a candidate bundle with one deleted member."""

    _spec, _report_value, scene_path, candidates = _group_candidate_fixture(tmp_path)
    group_candidates = [
        candidate
        for candidate in candidates.candidates
        if candidate.finding_id == "direct.group_position.island.ocean"
    ]
    removed_id = group_candidates[-1].id
    incomplete = candidates.model_copy(
        update={
            "candidates": [
                candidate
                for candidate in candidates.candidates
                if candidate.id != removed_id
            ]
        }
    )
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(incomplete.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="target_ids do not match"):
        compile_revision_plan(
            candidates_path=candidates_path,
            scene_spec_path=scene_path,
            selected_candidate_ids=[candidate.id for candidate in group_candidates[:-1]],
            request="Reject a deleted coherent-group member.",
            output_path=tmp_path / "missing_group_member_plan.json",
        )


def test_compile_rejects_changed_source_report(tmp_path: Path) -> None:
    """Candidate compilation rejects even a whitespace mutation to the bound QA report."""

    _spec, _report_value, scene_path, candidates = _group_candidate_fixture(tmp_path)
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(candidates.model_dump_json(indent=2), encoding="utf-8")
    report_path = tmp_path / "visual_qa_report.json"
    report_path.write_text(
        report_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    group_ids = [
        candidate.id
        for candidate in candidates.candidates
        if candidate.finding_id == "direct.group_position.island.ocean"
    ]

    with pytest.raises(ValueError, match="source visual QA report changed"):
        compile_revision_plan(
            candidates_path=candidates_path,
            scene_spec_path=scene_path,
            selected_candidate_ids=group_ids,
            request="Reject candidates after report mutation.",
            output_path=tmp_path / "changed_report_plan.json",
        )


def test_approval_rejects_candidate_ids_not_compiled_into_plan(tmp_path: Path) -> None:
    """Approval IDs must reproduce the exact operation multiset in the compiled plan."""

    _spec, _report_value, scene_path, candidates = _group_candidate_fixture(tmp_path)
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(candidates.model_dump_json(indent=2), encoding="utf-8")
    group_ids = [
        candidate.id
        for candidate in candidates.candidates
        if candidate.finding_id == "direct.group_position.island.ocean"
    ]
    plan_path = tmp_path / "group_plan.json"
    compile_revision_plan(
        candidates_path=candidates_path,
        scene_spec_path=scene_path,
        selected_candidate_ids=group_ids,
        request="Compile only the coherent group.",
        output_path=plan_path,
    )

    with pytest.raises(ValueError, match="do not exactly match"):
        create_revision_approval(
            candidates_path=candidates_path,
            plan_path=plan_path,
            approved_candidate_ids=[
                *group_ids,
                "candidate.direct.position.island.ocean.plateau",
            ],
            output_path=tmp_path / "mismatched_approval.json",
        )


def test_apply_revalidates_group_members_share_the_same_world_delta(
    tmp_path: Path,
) -> None:
    """Apply rejects a hash-valid group bundle whose member displacement was tampered."""

    _spec, _report_value, scene_path, candidates = _group_candidate_fixture(tmp_path)
    group_candidates = [
        candidate
        for candidate in candidates.candidates
        if candidate.finding_id == "direct.group_position.island.ocean"
    ]
    tampered_value = list(group_candidates[0].value)
    tampered_value[0] = round(float(tampered_value[0]) + 0.25, 6)
    tampered_candidate = group_candidates[0].model_copy(
        update={"value": tampered_value}
    )
    tampered_candidates = candidates.model_copy(
        update={
            "candidates": [
                tampered_candidate if item.id == tampered_candidate.id else item
                for item in candidates.candidates
            ]
        }
    )
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(
        tampered_candidates.model_dump_json(indent=2),
        encoding="utf-8",
    )
    selected = [
        item
        for item in tampered_candidates.candidates
        if item.finding_id == "direct.group_position.island.ocean"
    ]
    plan = RevisionPlan(
        job_id=tampered_candidates.job_id,
        base_spec_sha256=tampered_candidates.base_spec_sha256,
        request="Tampered group fixture.",
        operations=[
            RevisionOperation(
                op=item.op,
                target_type=item.target_type,
                target_id=item.target_id,
                path=item.path,
                value=item.value,
                reason=item.reason,
            )
            for item in selected
        ],
        acceptance_criteria=["Reject inconsistent group movement."],
    )
    plan_path = tmp_path / "revision_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    approval_path = tmp_path / "revision_approval.json"
    create_revision_approval(
        candidates_path=candidates_path,
        plan_path=plan_path,
        approved_candidate_ids=[item.id for item in selected],
        output_path=approval_path,
    )

    with pytest.raises(ValueError, match="does not match source report displacement"):
        apply_approved_revision(
            scene_spec_path=scene_path,
            candidates_path=candidates_path,
            plan_path=plan_path,
            approval_path=approval_path,
            output_path=tmp_path / "scene_spec.next.json",
        )


def test_apply_rejects_group_and_individual_edits_to_the_same_address(
    tmp_path: Path,
) -> None:
    """Apply independently rejects a full group plus a duplicate per-object location edit."""

    _spec, _report_value, scene_path, candidates = _group_candidate_fixture(tmp_path)
    candidates_path = tmp_path / "revision_candidates.json"
    candidates_path.write_text(candidates.model_dump_json(indent=2), encoding="utf-8")
    selected = [
        item
        for item in candidates.candidates
        if item.finding_id == "direct.group_position.island.ocean"
        or item.id == "candidate.direct.position.island.ocean.plateau"
    ]
    plan = RevisionPlan(
        job_id=candidates.job_id,
        base_spec_sha256=candidates.base_spec_sha256,
        request="Conflicting group and individual fixture.",
        operations=[
            RevisionOperation(
                op=item.op,
                target_type=item.target_type,
                target_id=item.target_id,
                path=item.path,
                value=item.value,
                reason=item.reason,
            )
            for item in selected
        ],
        acceptance_criteria=["Reject duplicate target paths."],
    )
    plan_path = tmp_path / "revision_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    approval_path = tmp_path / "revision_approval.json"
    create_revision_approval(
        candidates_path=candidates_path,
        plan_path=plan_path,
        approved_candidate_ids=[item.id for item in selected],
        output_path=approval_path,
    )

    with pytest.raises(ValueError, match="conflicting target/path"):
        apply_approved_revision(
            scene_spec_path=scene_path,
            candidates_path=candidates_path,
            plan_path=plan_path,
            approval_path=approval_path,
            output_path=tmp_path / "scene_spec.next.json",
        )
