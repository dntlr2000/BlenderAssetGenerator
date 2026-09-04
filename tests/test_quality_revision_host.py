"""Exact new-loop host boundaries; fixture-only tests do not claim Blender/visual success."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_aq_approval_envelope import _base_plan, _enable_autonomous_envelope
from test_autonomy_v2_candidate_validation import NOW, _artifact, _candidate_state
from test_reference_fidelity import hypothesis

from codex_blender_modeler.autonomy.io import write_immutable_json
from codex_blender_modeler.autonomy_v2 import quality_revision_service as service
from codex_blender_modeler.autonomy_v2.approval_policy_service import _load_approval_boundary
from codex_blender_modeler.autonomy_v2.controller_bridge import _session_bundle
from codex_blender_modeler.autonomy_v2.quality_revision_models import (
    AQQualityRevisionLoopV01,
    RevisionCostV01,
)
from codex_blender_modeler.autonomy_v2.supervisor_service import QualitySubmissionV2
from codex_blender_modeler.autonomy_v2.transitions import (
    transition_state,
    validate_state_transition,
)
from codex_blender_modeler.reference_fidelity.models import FidelityArtifact
from codex_blender_modeler.reference_fidelity.service import artifact_at, publish, read_artifact


def prepare_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a genuine planner/envelope and an independently bound observation companion."""

    root, base = _base_plan(tmp_path, monkeypatch, job_id="fidelity_loop_test")
    job, session = _enable_autonomous_envelope(base)
    bundle = _session_bundle(job, session)
    boundary = _load_approval_boundary(job, session)
    reference = boundary[2].primary_reference
    observation = hypothesis().model_copy(
        update={
            "job_id": job,
            "reference": FidelityArtifact(path=reference.path, sha256=reference.sha256),
        }
    )
    hyp = publish(root, root / "fidelity/hypothesis.json", observation)
    loop = AQQualityRevisionLoopV01(
        job_id=job,
        session_id=session,
        root_authorization=FidelityArtifact(path=boundary[3].path, sha256=boundary[3].sha256),
        approval_envelope=FidelityArtifact(path=boundary[9].path, sha256=boundary[9].sha256),
        hypothesis=hyp,
        initial_state=FidelityArtifact(path=bundle[5].path, sha256=bundle[5].sha256),
        structural_revision_limit=2,
        local_revision_limit=2,
        cost_limit=RevisionCostV01(
            materializations=2, builds=3, qa_runs=3, closure_runs=2, promotions=3
        ),
        allow_disabled_experimental=True,
    )
    path = root / "fidelity/proposed_loop.json"
    publish(root, path, loop)
    return root, job, session, loop, path


def test_loop_binding_keeps_root_state_and_reference_immutable(tmp_path, monkeypatch) -> None:
    """Opt-in is additive, before initial geometry, and grants no human/canonical authority."""

    root, job, session, loop, path = prepare_loop(tmp_path, monkeypatch)
    before = _session_bundle(job, session)
    frozen = {
        item.path: read_artifact(root, item)
        for item in (
            loop.root_authorization,
            loop.approval_envelope,
            loop.initial_state,
            loop.hypothesis,
        )
    }
    selected = service.bind_quality_revision_loop(job, session, path)
    assert service.load_optional_loop(root, session) == (loop, selected)
    assert _session_bundle(job, session)[4:] == before[4:]
    for name, content in frozen.items():
        assert (root / name).read_bytes() == content
    assert loop.human_approval_authority is False


def test_loop_cannot_expand_the_frozen_root_budget(tmp_path, monkeypatch) -> None:
    """The approved maximum of three is not permission to enlarge an older root's two rounds."""

    root, job, session, loop, _path = prepare_loop(tmp_path, monkeypatch)
    path = root / "fidelity/too_many_rounds.json"
    publish(root, path, loop.model_copy(update={"structural_revision_limit": 3}))
    with pytest.raises(PermissionError, match="frozen AQ root budget"):
        service.bind_quality_revision_loop(job, session, path)
    assert service.load_optional_loop(root, session) is None


def test_tampered_loop_dependency_is_rejected(tmp_path, monkeypatch) -> None:
    """Changing a hypothesis after exact binding cannot silently alter expected observations."""

    root, job, session, loop, path = prepare_loop(tmp_path, monkeypatch)
    service.bind_quality_revision_loop(job, session, path)
    (root / loop.hypothesis.path).write_bytes(b"{}")
    with pytest.raises(ValueError, match="evidence changed"):
        service.load_optional_loop(root, session)


def test_aq_loop_cannot_start_with_no_required_observations(tmp_path, monkeypatch) -> None:
    """A wholly optional/N-A checklist cannot certify a newly generated AQ asset."""

    from codex_blender_modeler.reference_fidelity.models import ModelingHypothesisV01

    root, job, session, loop, _path = prepare_loop(tmp_path, monkeypatch)
    original = ModelingHypothesisV01.model_validate_json(read_artifact(root, loop.hypothesis))
    empty_requirements = original.model_copy(
        update={
            "requirements": [
                item.model_copy(update={"required": False}) for item in original.requirements
            ]
        }
    )
    hypothesis_artifact = publish(
        root, root / "fidelity/no_required_hypothesis.json", empty_requirements
    )
    proposal = root / "fidelity/no_required_loop.json"
    publish(root, proposal, loop.model_copy(update={"hypothesis": hypothesis_artifact}))
    with pytest.raises(ValueError, match="at least one applicable"):
        service.bind_quality_revision_loop(job, session, proposal)
    assert service.load_optional_loop(root, session) is None


def test_geometry_controller_receives_exact_observations_once(tmp_path, monkeypatch) -> None:
    """Attach immutable observation/loop context using existing read-only assignment authority."""

    root, job, session, loop, path = prepare_loop(tmp_path, monkeypatch)
    binding = service.bind_quality_revision_loop(job, session, path)
    _, _, plan, _, state, _ = _session_bundle(job, session)
    original = service.fidelity_geometry_inputs(root, plan, state, [])
    assert {item.path for item in original} == {loop.hypothesis.path, binding.path}
    assert {item.kind for item in original} == {"assignment"}
    assert service.fidelity_geometry_inputs(root, plan, state, original) == original
    substituted = original[0].model_copy(update={"sha256": "b" * 64})
    with pytest.raises(ValueError, match="substitutes"):
        service.fidelity_geometry_inputs(root, plan, state, [substituted])


def test_parametric_round_does_not_consume_initial_or_structural_count(tmp_path, monkeypatch):
    """Separate initial-candidate and structural promotion counters from bounded local geometry."""

    from codex_blender_modeler.autonomy_v2.candidate_validation_service import (
        _reserve_candidate_budget,
    )
    from codex_blender_modeler.autonomy_v2.models import BudgetUsageV2

    _root, job, session, _loop, _path = prepare_loop(tmp_path, monkeypatch)
    budget = _session_bundle(job, session)[3]
    original = BudgetUsageV2(initial_candidates=1)
    updated = _reserve_candidate_budget(
        original, budget, materialization_builds=1, parametric_reentry=True
    )
    assert updated.initial_candidates == 1
    assert updated.structural_rounds == 0
    assert updated.parametric_convergence_iterations == 1
    assert updated.total_blender_builds == 2


def test_round_selector_never_borrows_old_material_receipts(tmp_path, monkeypatch) -> None:
    """Two valid historical pairs are not ambiguous when the current reentry is explicitly bound."""

    monkeypatch.setattr(service, "load_optional_loop", lambda *_: (object(), object()))
    monkeypatch.setattr(
        service, "active_reentry", lambda *_: SimpleNamespace(route="structural_reentry")
    )
    old_g = _artifact("geometry-old", "geometry_candidate_validation_receipt")
    old_m = _artifact("material-old", "material_phase_receipt")
    new_g = _artifact("geometry-new", "geometry_candidate_validation_receipt")
    new_m = _artifact("material-new", "material_phase_receipt")
    marker = _artifact("reentry", service.REENTRY_KIND)
    state = _candidate_state().model_copy(
        update={"provenance": [old_g, old_m, marker, new_g, new_m]}
    )
    plan = SimpleNamespace(session_id=state.session_id)
    assert service.current_round_receipts(tmp_path, plan, state) == (new_g, new_m)
    mixed = state.model_copy(update={"provenance": [old_g, old_m, marker, new_g]})
    with pytest.raises(ValueError, match="exactly one"):
        service.current_round_receipts(tmp_path, plan, mixed)


def test_final_submission_cannot_replace_the_reviewed_iq(tmp_path, monkeypatch) -> None:
    """A passing visual attempt cannot authorize a different quality report before policy issue."""

    camera = _artifact("camera", "camera")
    submission = QualitySubmissionV2(
        integrated_quality_report=_artifact("iq", "iq"),
        camera_artifact=camera,
        quality_evidence=[camera],
    )
    path = tmp_path / "fidelity/submission.json"
    write_immutable_json(tmp_path, path, submission.model_dump(mode="json"))
    reference = artifact_at(tmp_path, path)
    monkeypatch.setattr(service, "load_optional_loop", lambda *_: (object(), object()))
    monkeypatch.setattr(
        service, "quality_revision_boundary", lambda *_: {"next_action": "quality_ready"}
    )
    monkeypatch.setattr(
        service, "_attempts", lambda *_: [(SimpleNamespace(quality_submission=reference), object())]
    )
    plan = SimpleNamespace(session_id="session")
    service.validate_final_quality_submission(tmp_path, plan, object(), submission)
    other = submission.model_copy(update={"integrated_quality_report": _artifact("other-iq", "iq")})
    with pytest.raises(ValueError, match="differs from the evaluated round"):
        service.validate_final_quality_submission(tmp_path, plan, object(), other)


def test_fidelity_review_terminal_does_not_reclassify_iq_or_human() -> None:
    """New terminal kind has a distinct transition and cannot create a source freeze."""

    state = _candidate_state().model_copy(
        update={
            "phase": "quality",
            "next_action": "run_integrated_quality",
        }
    )
    evidence = _artifact("terminal", "reference_fidelity_review_terminal_v01")
    terminal = transition_state(
        state,
        event="fidelity_review_required",
        evidence=evidence,
        quality_terminal=evidence,
        created_at=NOW,
        reason="Budget exhausted",
    )
    validate_state_transition(state, terminal)
    assert terminal.status == "review_required"
    assert terminal.source_freeze is None
    with pytest.raises(ValueError, match="typed non-production"):
        transition_state(
            state,
            event="fidelity_review_required",
            evidence=evidence,
            quality_terminal=evidence,
            source_freeze=_artifact("freeze", "freeze"),
            created_at=NOW,
            reason="Budget exhausted",
        )
    assert "human" not in json.dumps(terminal.model_dump(mode="json"))


def test_legacy_missing_companion_does_not_create_evidence(tmp_path) -> None:
    """Read-only absence preserves the legacy mode and never auto-migrates old sessions."""

    assert service.load_optional_loop(tmp_path, "legacy") is None
    assert list(tmp_path.iterdir()) == []


def test_active_round_adopts_crash_surviving_next_reservation(tmp_path, monkeypatch) -> None:
    """A pending next round cannot replace current receipts or prevent safe exact resume."""

    from test_quality_revision_budget import reentry

    first = reentry(1)
    path = tmp_path / "fidelity/reentry.json"
    first = first.model_copy(
        update={"loop": FidelityArtifact(path="fidelity/loop", sha256="a" * 64)}
    )
    reference = publish(tmp_path, path, first)
    marker = _artifact("reentry", service.REENTRY_KIND).model_copy(
        update={
            "path": reference.path,
            "sha256": reference.sha256,
        }
    )
    state = _candidate_state().model_copy(
        update={
            "phase": "quality",
            "next_action": "run_integrated_quality",
            "provenance": [marker],
        }
    )
    monkeypatch.setattr(service, "load_optional_loop", lambda *_: (object(), first.loop))
    monkeypatch.setattr(
        service,
        "_load_ledger",
        lambda *_: [
            (SimpleNamespace(plan=reference), object()),
            (SimpleNamespace(plan=FidelityArtifact(path="next", sha256="b" * 64)), object()),
        ],
    )
    original_read = service.read_artifact
    monkeypatch.setattr(
        service,
        "read_artifact",
        lambda root, item: b"{}" if item == first.attempt else original_read(root, item),
    )
    plan = SimpleNamespace(session_id="session")
    assert service.active_reentry(tmp_path, plan, state) == first
    with pytest.raises(ValueError, match="current reserved round"):
        service.active_reentry(
            tmp_path,
            plan,
            state.model_copy(
                update={
                    "phase": "authoring",
                    "next_action": "execute_controller",
                }
            ),
        )
