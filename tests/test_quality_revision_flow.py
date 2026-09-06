"""Host revision/resume contracts over mocked prior promotions, not an actual AQ campaign."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_quality_revision_host import prepare_loop
from test_reference_fidelity_files import file_fixture

from codex_blender_modeler.autonomy_v2 import controller_bridge, supervisor_service
from codex_blender_modeler.autonomy_v2 import quality_revision_service as service
from codex_blender_modeler.autonomy_v2.delivery_service import artifact_for_v2
from codex_blender_modeler.autonomy_v2.quality_revision_models import (
    QualityAttemptV01,
    QualityRenderReservationV01,
    RevisionCostV01,
)
from codex_blender_modeler.autonomy_v2.transitions import validate_state_transition
from codex_blender_modeler.reference_fidelity.models import (
    FidelityArtifact,
    ModelingHypothesisV01,
    VisualFindingSetV01,
)
from codex_blender_modeler.reference_fidelity.service import (
    artifact_at,
    evaluate_review_file,
    publish,
    read_artifact,
)


def quality_fixture(tmp_path, monkeypatch, *, missing=False, object_count=1, builds_used=0):
    """Combine a real schema/QA file fixture with explicitly mocked prior AQ promotions."""

    (tmp_path / "planner").mkdir()
    _planner_root, job, session_id, loop, _path = prepare_loop(tmp_path / "planner", monkeypatch)
    _root, _session, plan, budget, initial, _initial_artifact = controller_bridge._session_bundle(
        job, session_id
    )
    root, evidence = file_fixture(tmp_path / "qa", monkeypatch, object_limit=object_count)
    hyp_ref = artifact_at(root, root / "fidelity/hypothesis.json")
    hypothesis = ModelingHypothesisV01.model_validate_json(read_artifact(root, hyp_ref))
    original = VisualFindingSetV01.model_validate_json((root / "fidelity/review.json").read_bytes())
    review = original.model_copy(update={"assessments": []}) if missing else original
    review_ref = publish(root, root / "fidelity/current_review.json", review)
    evaluation_ref = evaluate_review_file(
        root, root / review_ref.path, root / "fidelity/current_eval.json"
    )
    evaluation = service.FidelityEvaluationV01.model_validate_json(
        read_artifact(root, evaluation_ref)
    )
    plan = plan.model_copy(update={"job_id": root.name})
    plan_ref = publish(root, root / "fidelity/base_plan.json", plan)
    plan_aq = artifact_for_v2(root, root / plan_ref.path, artifact_id="plan", kind="autonomy_plan")
    receipts = []
    for name, kind in (
        ("geometry", "geometry_candidate_validation_receipt"),
        ("material", "material_phase_receipt"),
    ):
        # Deliberately fixture receipts: these are not executed Blender promotion evidence.
        path = root / "fidelity" / f"{name}_receipt.json"
        path.write_text('{"fixture_only": true}\n', encoding="utf-8")
        receipts.append(artifact_for_v2(root, path, artifact_id=name, kind=kind))
    state = initial.model_copy(
        update={
            "job_id": root.name,
            "plan": plan_aq,
            "phase": "quality",
            "status": "running",
            "next_action": "run_integrated_quality",
            "provenance": [plan_aq, *receipts],
            "budget_usage": initial.budget_usage.model_copy(
                update={
                    "total_blender_builds": builds_used,
                }
            ),
        }
    )
    state_ref = publish(root, root / "fidelity/quality_state.json", state)
    state_aq = artifact_for_v2(
        root, root / state_ref.path, artifact_id="state", kind="autonomy_state"
    )
    loop = loop.model_copy(
        update={
            "job_id": root.name,
            "hypothesis": hyp_ref,
            "initial_state": state_ref,
        }
    )
    loop_ref = publish(root, root / "fidelity/bound_loop.json", loop)
    budget_ref = publish(root, root / "fidelity/budget.json", budget)
    plan = plan.model_copy(
        update={
            "budget": artifact_for_v2(
                root, root / budget_ref.path, artifact_id="budget", kind="autonomy_budget"
            )
        }
    )
    session = root / "production/autonomy_v2" / session_id
    session.mkdir(parents=True, exist_ok=True)
    holder = SimpleNamespace(state=state, state_artifact=state_aq)

    def session_bundle(*_args):
        """Supply the fixture quality boundary without claiming historical promotion execution."""

        return root, session, plan, budget, holder.state, holder.state_artifact

    monkeypatch.setattr(controller_bridge, "_session_bundle", session_bundle)
    monkeypatch.setattr(service, "load_optional_loop", lambda *_: (loop, loop_ref))
    (root / "analysis/modeling_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "0.4.0",
                "job_id": root.name,
                "reference_analysis_path": "analysis/reference_analysis.json",
                "camera_solution_path": "analysis/camera_solution.json",
                "stage": "scaffold",
                "objects": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "blender").mkdir(exist_ok=True)
    (root / "blender/scene.blend").write_bytes(b"fixture-only; not a Blender binary")
    attempt = QualityAttemptV01(
        loop=loop_ref,
        round_index=0,
        source_state=state_ref,
        scene_spec=evidence.scene_spec,
        geometry_receipt=FidelityArtifact(path=receipts[0].path, sha256=receipts[0].sha256),
        material_receipt=FidelityArtifact(path=receipts[1].path, sha256=receipts[1].sha256),
        quality_submission=review_ref,
        visual_review=review_ref,
        fidelity_evaluation=evaluation_ref,
        strategy=hypothesis.authoring_strategy,
        unresolved_features=[item.feature_id for item in evaluation.findings],
        next_action=evaluation.next_action,
    )
    attempt_ref = publish(root, session / "fidelity/attempts/0000.json", attempt)
    return SimpleNamespace(
        root=root,
        job=root.name,
        session=session_id,
        session_path=session,
        holder=holder,
        plan=plan,
        budget=budget,
        loop=loop,
        loop_ref=loop_ref,
        attempt=attempt,
        attempt_ref=attempt_ref,
        review=original,
        evidence=evidence,
    )


def correction_cost():
    """Reserve one geometry materialization, both builds/promotions and its next quality render."""

    return RevisionCostV01(materializations=1, builds=2, promotions=2, qa_runs=1, closure_runs=1)


def test_reentry_crash_resume_adopts_one_reservation_and_same_sources(tmp_path, monkeypatch):
    """A crash after reservation cannot reset counts, overwrite history or duplicate a round."""

    fixture = quality_fixture(tmp_path, monkeypatch)
    original_write = supervisor_service._write_next_state
    before = fixture.holder.state
    source = (fixture.root / "analysis/scene_spec.json").read_bytes()

    def crash(*_args):
        """Simulate interruption only after the immutable source/plan/reservation were published."""

        raise RuntimeError("simulated pre-transition crash")

    monkeypatch.setattr(supervisor_service, "_write_next_state", crash)
    with pytest.raises(RuntimeError, match="simulated"):
        service.begin_quality_reentry(
            fixture.job, fixture.session, strategy=fixture.attempt.strategy, cost=correction_cost()
        )
    ledger = fixture.session_path / "fidelity/reservations/0001.json"
    reserved = ledger.read_bytes()
    assert len(list(ledger.parent.glob("*.json"))) == 1
    monkeypatch.setattr(supervisor_service, "_write_next_state", original_write)
    result = service.begin_quality_reentry(
        fixture.job, fixture.session, strategy=fixture.attempt.strategy, cost=correction_cost()
    )
    after = type(before).model_validate_json(json.dumps(result["state"]))
    validate_state_transition(before, after)
    service.validate_reentry_transition(fixture.root, before, after)
    assert after.next_action == "execute_controller"
    assert (
        after.budget_usage.total_quality_evaluations
        == before.budget_usage.total_quality_evaluations + 1
    )
    assert ledger.read_bytes() == reserved
    assert (fixture.root / "analysis/scene_spec.json").read_bytes() == source
    assert len(list(ledger.parent.glob("*.json"))) == 1


def test_over_budget_reentry_writes_no_source_snapshot(tmp_path, monkeypatch):
    """Oversized cost fails before copying even the Blender source or reserving a new round."""

    fixture = quality_fixture(tmp_path, monkeypatch)
    with pytest.raises(PermissionError, match="build budget"):
        service.begin_quality_reentry(
            fixture.job,
            fixture.session,
            strategy=fixture.attempt.strategy,
            cost=correction_cost().model_copy(update={"builds": 15}),
        )
    assert not (fixture.session_path / "fidelity/sources").exists()
    assert not (fixture.session_path / "fidelity/reservations").exists()


def test_six_object_rebuild_floor_stops_before_an_unaffordable_reentry(tmp_path, monkeypatch):
    """Nine of fourteen builds used cannot cover six materializations plus two builds."""

    fixture = quality_fixture(tmp_path, monkeypatch, object_count=6, builds_used=9)
    boundary = service.quality_revision_boundary(fixture.root, fixture.plan, fixture.holder.state)
    assert boundary["next_action"] == "review_required"
    with pytest.raises(PermissionError, match="do not authorize"):
        service.begin_quality_reentry(
            fixture.job, fixture.session, strategy=fixture.attempt.strategy, cost=correction_cost()
        )
    assert not (fixture.session_path / "fidelity/sources").exists()


def test_render_failure_is_reserved_before_effect_and_only_retried_once(tmp_path, monkeypatch):
    """A technical failure consumes real QA cost; a new run label cannot replenish it."""

    from codex_blender_modeler.qa import service as qa_service

    fixture = quality_fixture(tmp_path, monkeypatch)
    calls = []

    def fail_render(*_args, **kwargs):
        """Observe the already-published reservation and simulate Blender failure, not success."""

        entries = service._render_reservations(fixture.root, fixture.session, fixture.loop_ref)
        assert entries[-1][0].run_id == kwargs["run_id"]
        calls.append(kwargs["run_id"])
        raise RuntimeError("simulated renderer failure")

    monkeypatch.setattr(qa_service, "run_scene_spec_visual_qa_snapshot", fail_render)
    for run in ("initial_failure", "one_technical_retry"):
        with pytest.raises(RuntimeError, match="renderer failure"):
            service.render_quality_evidence(fixture.job, fixture.session, run_id=run)
    with pytest.raises(PermissionError, match="budget exhausted"):
        service.render_quality_evidence(fixture.job, fixture.session, run_id="renamed_retry")
    assert calls == ["initial_failure", "one_technical_retry"]
    assert len(service._render_reservations(fixture.root, fixture.session, fixture.loop_ref)) == 2


def test_successful_render_cannot_be_called_a_technical_retry(tmp_path, monkeypatch):
    """An already emitted QA report excludes the technical retry branch."""

    from codex_blender_modeler.qa import service as qa_service

    fixture = quality_fixture(tmp_path, monkeypatch)

    def emit_then_interrupt(*_args, **kwargs):
        """Emulate interruption after a report exists; recovery must adopt, not rerender it."""

        directory = kwargs["run_dir"]
        directory.mkdir(parents=True)
        (directory / "visual_qa_report.json").write_bytes(b"fixture completed report")
        raise RuntimeError("interrupted after report")

    monkeypatch.setattr(qa_service, "run_scene_spec_visual_qa_snapshot", emit_then_interrupt)
    with pytest.raises(RuntimeError):
        service.render_quality_evidence(fixture.job, fixture.session, run_id="complete")
    with pytest.raises(PermissionError, match="successful QA render"):
        service.render_quality_evidence(fixture.job, fixture.session, run_id="not_a_retry")


def test_missing_observation_can_be_supplemented_without_replacing_original(tmp_path, monkeypatch):
    """Append one assessment on identical pixels; preserve the original missing-evidence attempt."""

    fixture = quality_fixture(tmp_path, monkeypatch, missing=True)
    original_bytes = read_artifact(fixture.root, fixture.attempt_ref)
    review_ref = publish(
        fixture.root, fixture.root / "fidelity/supplement_review.json", fixture.review
    )
    artifact = service.supplement_quality_evidence(
        fixture.job, fixture.session, review_path=Path(review_ref.path)
    )
    selected, selected_ref = service._attempts(fixture.root, fixture.session, fixture.loop_ref)[0]
    assert selected_ref == artifact and selected.supplements_attempt == fixture.attempt_ref
    assert selected.next_action == "structural_reentry"
    assert read_artifact(fixture.root, fixture.attempt_ref) == original_bytes
    assert (
        service.supplement_quality_evidence(
            fixture.job, fixture.session, review_path=Path(review_ref.path)
        )
        == artifact
    )
    other = publish(fixture.root, fixture.root / "fidelity/second_review.json", fixture.review)
    with pytest.raises(PermissionError, match="already used"):
        service.supplement_quality_evidence(
            fixture.job, fixture.session, review_path=Path(other.path)
        )
    assert not (fixture.session_path / "fidelity/reservations").exists()


def test_supplement_cannot_erase_an_observed_defect_or_substitute_pixels(tmp_path, monkeypatch):
    """Only missing slots, never known failures or renderer sources, can change."""

    fixture = quality_fixture(tmp_path, monkeypatch)
    new_review = fixture.review.model_copy(
        update={
            "assessments": [
                item.model_copy(update={"outcome": "satisfied"})
                for item in fixture.review.assessments
            ]
        }
    )
    artifact = publish(fixture.root, fixture.root / "fidelity/rerated.json", new_review)
    with pytest.raises(PermissionError, match="only missing-evidence"):
        service.supplement_quality_evidence(
            fixture.job, fixture.session, review_path=Path(artifact.path)
        )


def test_attempt_cannot_hide_unresolved_features_from_plateau_detection(tmp_path, monkeypatch):
    """Derive unresolved features from the exact evaluation instead of caller counters."""

    fixture = quality_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="exact evaluated findings"):
        service._validate_attempt_artifacts(
            fixture.root, fixture.attempt.model_copy(update={"unresolved_features": []})
        )


def test_iq_structural_failure_precedes_a_visual_material_revision():
    """Keep an authoritative IQ contour defect visible when visual review requests material work."""

    evaluation = SimpleNamespace(
        next_action="material_revision",
        findings=[SimpleNamespace(feature_id="plastic-wear")],
    )
    report = SimpleNamespace(
        quality_accepted=False,
        findings=[SimpleNamespace(finding_id="finding.reference.contour_v02")],
        reentry=[
            SimpleNamespace(
                destination="v0.4_structural_authoring",
                category="contour",
            )
        ],
    )
    route, unresolved = service._combined_attempt_routing(evaluation, report)
    assert route == "structural_reentry"
    assert unresolved == ["plastic-wear", "iq:finding.reference.contour_v02"]


def test_completed_reserved_qa_is_adopted_without_new_render_or_charge(tmp_path, monkeypatch):
    """Adopt published QA without rerendering the candidate or charging it twice."""

    from codex_blender_modeler.build_provenance import collect_build_provenance
    from codex_blender_modeler.qa import service as qa_service

    fixture = quality_fixture(tmp_path, monkeypatch)
    state = fixture.holder.state_artifact
    reservation = QualityRenderReservationV01(
        loop=fixture.loop_ref,
        sequence=1,
        previous=None,
        round_index=0,
        attempt_index=0,
        source_state=FidelityArtifact(path=state.path, sha256=state.sha256),
        source=artifact_at(fixture.root, fixture.root / "analysis/scene_spec.json"),
        build_fingerprint=collect_build_provenance(fixture.root, fixture.job)["fingerprint"],
        run_id="fixture",
    )
    publish(
        fixture.root,
        fixture.session_path / "fidelity/render_reservations/0000-0000.json",
        reservation,
    )

    def forbidden(*_args, **_kwargs):
        """Fail if source adoption attempts any additional renderer invocation."""

        raise AssertionError("adoption must not render")

    monkeypatch.setattr(qa_service, "run_scene_spec_visual_qa_snapshot", forbidden)
    first = service.render_quality_evidence(fixture.job, fixture.session, run_id="fixture")
    second = service.render_quality_evidence(fixture.job, fixture.session, run_id="fixture")
    assert first == second and first["status"] == "existing"
    assert len(service._render_reservations(fixture.root, fixture.session, fixture.loop_ref)) == 1
