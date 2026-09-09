"""Exact prebuild cost failures are job-local; no fixture is campaign or art evidence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import test_autonomy_v2_candidate_validation_blender as geometry_fixture

from codex_blender_modeler.autonomy_v2 import approval_supervisor_service as supervisor
from codex_blender_modeler.autonomy_v2.approval_policy_service import (
    approval_artifact_for,
    assert_user_approval_category_allowed,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_service import (
    CandidateBudgetExhausted,
    _candidate_validation_root,
    _require_candidate_materialization_reserve,
    preflight_geometry_candidate_budget_v2,
)
from codex_blender_modeler.autonomy_v2.controller_bridge import _session_bundle
from codex_blender_modeler.autonomy_v2.models import RootAuthorizationV2
from codex_blender_modeler.production.controller_executor.models import ControllerResult


class _CandidateStaged(Exception):
    """Stop the shared controller fixture before eligibility, authorization or Blender."""


def staged_candidate(tmp_path, monkeypatch, *, object_count=21):
    """Use real immutable controller output with a configurable semantic part inventory."""

    old_scene = geometry_fixture._scene_v03
    old_modeling = geometry_fixture._modeling_plan

    def scene(job_id, reference_path):
        """Clone a legal recipe into distinct parts without invoking a geometry builder."""

        result = old_scene(job_id, reference_path)
        result["objects"] = [copy.deepcopy(result["objects"][0]) for _ in range(object_count)]
        for index, item in enumerate(result["objects"]):
            item["id"] = f"asset.part{index}"
        return result

    def modeling(job_id, note):
        """Preserve the source roles and ordered semantic membership of the scene fixture."""

        result = old_modeling(job_id, note)
        result["objects"] = [copy.deepcopy(result["objects"][0]) for _ in range(object_count)]
        for index, item in enumerate(result["objects"]):
            item["id"] = f"asset.part{index}"
        return result

    def stop_before_policy(*_args, **_kwargs):
        """Mark the exact boundary before the shared smoke would issue promotion authority."""

        raise _CandidateStaged

    with monkeypatch.context() as fixture_patch:
        fixture_patch.setattr(geometry_fixture, "_scene_v03", scene)
        fixture_patch.setattr(geometry_fixture, "_modeling_plan", modeling)
        fixture_patch.setattr(
            geometry_fixture, "evaluate_routine_gate_eligibility", stop_before_policy,
        )
        with pytest.raises(_CandidateStaged):
            geometry_fixture.test_geometry_controller_candidate_builds_and_promotes_exactly(
                tmp_path, monkeypatch,
            )
    root = tmp_path / "workspaces/aqv2_candidate_smoke"
    session = next((root / "production/autonomy_v2").iterdir())
    return _session_bundle(root.name, session.name)


def test_exact_materialization_count_reproduces_prebuild_budget_failure(tmp_path, monkeypatch):
    """Reproduce the observed 21 objects/14 builds failure after real source validation."""

    observed = json.loads((Path(__file__).parent / "fixtures/reference_fidelity/"
                           "candidate_budget_failure.json").read_bytes())
    root, session, plan, budget, state, _artifact = staged_candidate(
        tmp_path, monkeypatch, object_count=observed["candidate_object_count"],
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    before = (root / "analysis/modeling_plan.json").read_bytes()
    with pytest.raises(CandidateBudgetExhausted) as caught:
        preflight_geometry_candidate_budget_v2(
            root=root, plan=plan, budget=budget, state=state, authorization=authorization,
        )
    assert (caught.value.field, caught.value.required, caught.value.limit) == (
        "total_blender_builds", 22, 14,
    )
    assert not (root / "aq2").exists()
    assert not (session / "approval_envelope/authorizations").exists()
    assert (root / "analysis/modeling_plan.json").read_bytes() == before


def test_supervisor_classifies_budget_without_policy_or_canonical_side_effects(
    tmp_path, monkeypatch,
):
    """Publish a source-bound job-local terminal and preserve used counters without approval."""

    root, session, plan, _budget, state, _artifact = staged_candidate(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in (root / "analysis").glob("*.json")}
    result = supervisor._advance_geometry_with_policy(
        plan.job_id, plan.session_id, state, quality_submission=None,
    )
    current = _session_bundle(plan.job_id, plan.session_id)[4]
    assert result["state"]["status"] == "failed"
    assert current.budget_usage == state.budget_usage
    assert not (session / "approval_envelope/authorizations").exists()
    assert not (root / "aq2").exists()
    assert not (root / "analysis/scene_spec.json").exists()
    assert all(p.read_bytes() == contents for p, contents in before.items())
    artifact = approval_artifact_for(
        root, session / f"states/{current.sequence:04d}.json",
        artifact_id=current.state_id, kind="autonomy_v2_state",
    )
    failure, justification = supervisor._publish_blocked_failure_evidence(
        plan.job_id, plan.session_id, current, artifact,
    )
    report = json.loads((root / failure.path).read_bytes())
    classified = json.loads((root / justification.path).read_bytes())
    assert report["category"] == "candidate_budget_exhaustion"
    assert report["user_approval_requested"] is False
    assert classified["classification"] == "job_local_candidate_error"
    with pytest.raises(PermissionError, match="technical failure"):
        assert_user_approval_category_allowed("candidate_budget_exhaustion")
    with pytest.raises(ValueError, match="state changed"):
        supervisor._advance_geometry_with_policy(
            plan.job_id, plan.session_id, state, quality_submission=None,
        )
    assert len(list((session / "states").glob("*.json"))) == current.sequence + 1


def test_preflight_rejects_stale_source_before_calling_it_a_budget_failure(tmp_path, monkeypatch):
    """A changed bound candidate remains a hash failure even when its cost is excessive."""

    root, _session, plan, budget, state, _artifact = staged_candidate(tmp_path, monkeypatch)
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    path = root / "analysis/modeling_plan.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="artifact changed"):
        preflight_geometry_candidate_budget_v2(
            root=root, plan=plan, budget=budget, state=state, authorization=authorization,
        )


def test_funded_preflight_does_not_consume_builds_or_change_the_source(tmp_path, monkeypatch):
    """Return a proposed reservation while leaving the persisted usage unchanged."""

    root, _session, plan, budget, state, _artifact = staged_candidate(
        tmp_path, monkeypatch, object_count=1,
    )
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    reservation = preflight_geometry_candidate_budget_v2(
        root=root, plan=plan, budget=budget, state=state, authorization=authorization,
    )
    assert reservation.total_blender_builds == 2
    assert _session_bundle(plan.job_id, plan.session_id)[4] == state


def test_initial_and_reentry_reserves_cannot_borrow_unallocated_root_headroom():
    """Even sufficient root builds cannot replace the exact initial or revision object reserve."""

    from test_quality_revision_budget import loop, reentry
    from test_quality_revision_host import causal_loop

    proposal = causal_loop(loop(), closure_runs=1)
    with pytest.raises(CandidateBudgetExhausted) as initial:
        _require_candidate_materialization_reserve((proposal, None), None, 2)
    assert initial.value.field == "initial_materializations"
    with pytest.raises(CandidateBudgetExhausted) as revision:
        _require_candidate_materialization_reserve((proposal, None), reentry(1), 3)
    assert revision.value.field == "revision_materializations"


def test_an_unverified_receipt_cannot_bypass_preflight(tmp_path, monkeypatch):
    """A receipt filename alone cannot convert stale sources into an adopted promotion."""

    root, _session, plan, budget, state, _artifact = staged_candidate(tmp_path, monkeypatch)
    authorization = RootAuthorizationV2.model_validate_json(
        (root / plan.root_authorization.path).read_bytes()
    )
    result = ControllerResult.model_validate_json((root / state.provenance[-1].path).read_bytes())
    receipt_root = _candidate_validation_root(root, plan, result)
    receipt_root.mkdir(parents=True)
    (receipt_root / "receipt.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        preflight_geometry_candidate_budget_v2(
            root=root, plan=plan, budget=budget, state=state, authorization=authorization,
        )
    assert _session_bundle(plan.job_id, plan.session_id)[4] == state
