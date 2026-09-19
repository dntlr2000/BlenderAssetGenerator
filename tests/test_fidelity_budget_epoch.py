"""Finite funding, history continuity and host binding; fixtures are not art acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from test_quality_revision_budget import loop as legacy_loop
from test_quality_revision_budget import reentry
from test_reference_fidelity import artifact, hypothesis

from codex_blender_modeler.autonomy_v2.approval_policy_service import _load_approval_boundary
from codex_blender_modeler.autonomy_v2.approval_supervisor_service import plan_one_prompt_run
from codex_blender_modeler.autonomy_v2.controller_bridge import (
    _session_bundle,
    _validate_controller_authority,
    cancel_autonomy_v2,
)
from codex_blender_modeler.autonomy_v2.fidelity_budget_models import (
    FidelityBudgetEpochV01,
    FidelityHistoryEntryV01,
    FidelityLifetimeUsageV01,
)
from codex_blender_modeler.autonomy_v2.fidelity_budget_service import (
    fidelity_epoch_admission,
    plan_fidelity_budget_epoch,
    read_fidelity_history,
    require_funded_loop,
    validate_fidelity_epoch_history,
)
from codex_blender_modeler.autonomy_v2.material_phase_service import _validate_budget_binding
from codex_blender_modeler.autonomy_v2.models import AutonomyBudgetV03, parse_autonomy_budget
from codex_blender_modeler.autonomy_v2.planner import plan_autonomous_static_prop_v2
from codex_blender_modeler.autonomy_v2.quality_revision_budget import (
    funded_route_usage,
    reserve_revision,
)
from codex_blender_modeler.autonomy_v2.quality_revision_models import (
    AQQualityRevisionLoopV03,
    RevisionCostV01,
    parse_quality_revision_loop,
)
from codex_blender_modeler.autonomy_v2.quality_revision_service import bind_quality_revision_loop
from codex_blender_modeler.material_closure.models import (
    MaterialDependencyEntry,
    MaterialPreflightBudget,
    MaterialResourceCounters,
)
from codex_blender_modeler.material_closure.service import _validate_fidelity_preflight_budget
from codex_blender_modeler.reference_fidelity.models import FidelityArtifact
from codex_blender_modeler.reference_fidelity.service import publish


def funding(**updates) -> FidelityBudgetEpochV01:
    """Build an explicit empty-history fixture within the unchanged 64-build envelope."""

    return FidelityBudgetEpochV01(**{
        "epoch_id": "epoch-1", "job_id": "fidelity_fixture", "reference_sha256": "a" * 64,
        "prior_history": [], "prior_usage": FidelityLifetimeUsageV01(),
        "initial_object_limit": 12, "correction_object_limit": 12, **updates,
    })


def funded_loop(plan: FidelityBudgetEpochV01) -> AQQualityRevisionLoopV03:
    """Compose the exact funded companion while keeping old fixture evidence untouched."""

    return AQQualityRevisionLoopV03.model_validate({
        **legacy_loop().model_dump(), "schema_version": "0.3.0", "funding": plan,
        "job_id": plan.job_id,
        "initial_pipeline_reserve": RevisionCostV01(**plan.initial_cost()),
        "cost_limit": RevisionCostV01(**plan.revision_cost()),
        "structural_revision_limit": plan.structural_rounds,
        "local_revision_limit": plan.parametric_rounds + plan.material_corrections,
    })


def reference_fixture(tmp_path, monkeypatch) -> Path:
    """Create a test-local reference and workspace with no production or destination writes."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (50, 100, 180)).save(reference)
    return reference


def propose(reference, *, job="funded_fixture", epoch="epoch-1") -> FidelityBudgetEpochV01:
    """Plan one exact test scope against freshly revalidated reference-wide history."""

    return plan_fidelity_budget_epoch(
        epoch_id=epoch, job_id=job, reference_path=reference,
        initial_object_limit=8, correction_object_limit=8,
        structural_rounds=3, parametric_rounds=1, material_corrections=1,
    )


def plan_session(reference, proposal, *, one_prompt=False):
    """Create a real isolated AQ plan; explicit delegation grants no human artifact acceptance."""

    options = dict(
        reference_path=reference, target_subject="fixture shape",
        requested_delivery_profiles=["review_only"], job_id=proposal.job_id,
        fidelity_budget_plan=proposal, allow_disabled_experimental=True,
    )
    if one_prompt:
        return plan_one_prompt_run(
            "Build the test shape.", explicit_autonomy_delegation_observed=True, **options,
        )
    return plan_autonomous_static_prop_v2("Build the test shape.", **options)


def test_costs_fund_all_three_structural_and_two_material_rounds():
    """The advertised five revisions cover every actual stage, including one QA retry per round."""

    proposal = funding()
    limits = proposal.required_limits(delivery_runs=1)
    assert limits["total_blender_builds"] == 64
    assert limits["material_rounds"] == 6
    assert limits["canonical_promotions"] == 10
    assert limits["total_quality_evaluations"] == 18
    assert proposal.preflight_limits()["preflight_blender_runs"] == 36
    assert proposal.human_approval_authority is False
    assert proposal.lifetime_limit().structural == 3
    with pytest.raises(ValueError, match="64-build"):
        funding(initial_object_limit=21, correction_object_limit=21)
    with pytest.raises(ValueError, match="initial object"):
        funding(initial_object_limit=21, correction_object_limit=9)
    with pytest.raises(ValueError, match="two-round"):
        funding(parametric_rounds=1, material_corrections=2)


def test_prior_consumption_is_added_and_never_reset():
    """A new finite epoch displays inherited reservations separately from its new allowance."""

    used = FidelityLifetimeUsageV01(structural=4, local=3, blender_builds=52, strategy_switches=2)
    entry = FidelityHistoryEntryV01(
        job_id="previous_job", session_id="previous_session",
        session_evidence_sha256="b" * 64, last_state_sha256="c" * 64,
        budget_sha256="d" * 64, status="review_required", next_action="none",
        funded_epoch=False, usage=used,
    )
    proposal = funding(prior_history=[entry], prior_usage=used)
    assert proposal.lifetime_limit().structural == 7
    assert proposal.lifetime_limit().local == 5
    assert proposal.lifetime_limit().blender_builds == 116
    with pytest.raises(ValueError, match="reset or hide"):
        funding(prior_history=[entry])


def test_route_reserves_cannot_borrow_or_duplicate_a_round():
    """Each local route has a finite allocation and exact replay cannot recharge a round."""

    proposal = funding(initial_object_limit=8, correction_object_limit=8,
                       parametric_rounds=1, material_corrections=1)
    selected = funded_loop(proposal)
    previous = None
    for index, route in enumerate([
        "structural_reentry", "structural_reentry", "structural_reentry",
        "parametric_revision", "material_revision",
    ], 1):
        correction = reentry(index, route).model_copy(update={
            "cost": RevisionCostV01(**proposal.route_cost(route)),
            "change_strategy": index == 2,
        })
        arguments = dict(loop_artifact=artifact("loop"), plan_artifact=artifact(f"plan-{index}"),
                         previous=previous,
                         previous_artifact=artifact(f"ledger-{index-1}") if previous else None)
        reserved = reserve_revision(selected, correction, **arguments)
        assert reserve_revision(selected, correction, **arguments) == reserved
        with pytest.raises(ValueError, match="reset or skip"):
            reserve_revision(selected, correction, **{**arguments, "previous": reserved,
                             "previous_artifact": artifact(f"ledger-{index}")})
        previous = reserved
    assert previous.cost_used == selected.cost_limit
    assert funded_route_usage(previous) == proposal.route_limits()
    # Local route allocation is enforced even if the shared slot count has headroom.
    first = reentry(1, "parametric_revision").model_copy(update={
        "cost": RevisionCostV01(**proposal.route_cost("parametric_revision")),
    })
    one = reserve_revision(selected, first, loop_artifact=artifact("loop"),
                           plan_artifact=artifact("p1"), previous=None, previous_artifact=None)
    with pytest.raises(PermissionError, match="route budget"):
        reserve_revision(selected, first.model_copy(update={"round_index": 2}),
                         loop_artifact=artifact("loop"), plan_artifact=artifact("p2"),
                         previous=one, previous_artifact=artifact("l1"))


@pytest.mark.parametrize('selected_lighting', [False, True])
def test_funded_planner_loop_and_public_readers_bind_exactly(
    tmp_path, monkeypatch, selected_lighting,
):
    """A real funded root accepts legacy or exact opt-in lighting with identical reserves."""

    reference = reference_fixture(tmp_path, monkeypatch)
    proposal = propose(reference)
    result = plan_session(reference, proposal, one_prompt=True)
    session = str(result["session_id"])
    root, _session, plan, budget, _state, state_artifact = _session_bundle(proposal.job_id, session)
    assert isinstance(budget, AutonomyBudgetV03)
    assert parse_autonomy_budget(budget.model_dump_json()) == budget
    assert parse_autonomy_budget(budget.model_dump(mode="json")) == budget
    assert parse_autonomy_budget(budget) == budget
    with pytest.raises(PermissionError, match="V0.3 quality loop"):
        require_funded_loop(root, session, budget)
    boundary = _load_approval_boundary(proposal.job_id, session)
    reference_artifact = boundary[2].primary_reference
    observation = hypothesis().model_copy(update={
        "job_id": proposal.job_id,
        "reference": FidelityArtifact(
            path=reference_artifact.path, sha256=reference_artifact.sha256,
        ),
    })
    hyp = publish(root, root / "fidelity/hypothesis.json", observation)
    selected = funded_loop(proposal).model_copy(update={
        "job_id": proposal.job_id, "session_id": session, "hypothesis": hyp,
        "root_authorization": FidelityArtifact(path=plan.root_authorization.path,
                                               sha256=plan.root_authorization.sha256),
        "approval_envelope": FidelityArtifact(path=boundary[9].path, sha256=boundary[9].sha256),
        "initial_state": FidelityArtifact(path=state_artifact.path, sha256=state_artifact.sha256),
    })
    # Revalidate the constructed fixture before publication, rather than relying on model_copy.
    if selected_lighting:
        from codex_blender_modeler.autonomy_v2.quality_revision_models import (
            AQQualityRevisionLoopV04,
        )
        from codex_blender_modeler.comparison_lighting import (
            CAMERA_STUDIO_PROFILE,
            lighting_implementation_sha256,
        )

        selected = AQQualityRevisionLoopV04.model_validate({
            **selected.model_dump(), 'schema_version': '0.4.0',
            'comparison_lighting_profile': CAMERA_STUDIO_PROFILE,
            'lighting_implementation_sha256': lighting_implementation_sha256(),
        })
    selected = parse_quality_revision_loop(selected.model_dump_json().encode())
    path = root / "fidelity/proposal.json"
    publish(root, path, selected)
    bind_quality_revision_loop(proposal.job_id, session, path)
    require_funded_loop(root, session, budget)
    _validate_budget_binding(root, plan, budget)
    _validate_controller_authority(root, plan, budget)
    # The closure stage has its own six-process-per-round ledger, never AQ build units.
    entry = MaterialDependencyEntry(
        entry_id="budget", role="aq_autonomy_budget", path=plan.budget.path,
        sha256=plan.budget.sha256, byte_size=plan.budget.byte_size,
        source_kind="policy_evidence", required=True, producer="test", ownership="canonical",
    )
    closure = SimpleNamespace(entries=[entry])
    preflight = MaterialPreflightBudget(
        job_id=plan.job_id, workflow_id=plan.workflow_id, dispatch_id=plan.dispatch_id,
        session_id=session, producer="test", producer_version="0.1.0", created_at=datetime.now(UTC),
        budget_id="preflight-budget",
        limits=MaterialResourceCounters(**proposal.preflight_limits()),
        consumed=MaterialResourceCounters(**dict.fromkeys(proposal.preflight_limits(), 0)),
    )
    _validate_fidelity_preflight_budget(root, closure, preflight, require_current=True)
    for amount in (6, 42):
        mismatch = preflight.model_copy(update={
            "limits": preflight.limits.model_copy(update={"preflight_blender_runs": amount}),
        })
        with pytest.raises(RuntimeError, match="exact funded schedule"):
            _validate_fidelity_preflight_budget(root, closure, mismatch, require_current=True)
    assert boundary[8].max_blender_builds == 57
    with pytest.raises(ValueError, match="priced schedule"):
        parse_autonomy_budget({**budget.model_dump(mode="json"), "total_blender_builds": 64})


def test_history_change_and_renaming_do_not_reset_epoch(tmp_path, monkeypatch):
    """Another reference-identical job stales an earlier scope before any funded job write."""

    reference = reference_fixture(tmp_path, monkeypatch)
    proposal = propose(reference)
    old = plan_autonomous_static_prop_v2(
        "Keep the old fixture.", reference_path=reference, target_subject="old fixture",
        requested_delivery_profiles=["review_only"], job_id="renamed_old_job",
        allow_disabled_experimental=True,
    )
    with pytest.raises(ValueError, match="history changed"):
        plan_session(reference, proposal)
    assert not (tmp_path / "workspaces" / proposal.job_id).exists()
    fresh = propose(reference)
    assert len(fresh.prior_history) == 1
    cancel_autonomy_v2("renamed_old_job", str(old["session_id"]), reason="fixture terminal")
    with pytest.raises(ValueError, match="history changed"):
        validate_fidelity_epoch_history(fresh)
    assert read_fidelity_history(fresh.reference_sha256)[0].status == "cancelled"


def test_active_epoch_and_consumed_epoch_cannot_be_renamed(tmp_path, monkeypatch):
    """Only an explicit epoch after terminalization adds allowance; old bytes stay readable."""

    reference = reference_fixture(tmp_path, monkeypatch)
    first = propose(reference)
    result = plan_session(reference, first)
    second = propose(reference, job="another_job", epoch="epoch-2")
    with pytest.raises(PermissionError, match="still active"):
        plan_session(reference, second)
    session = str(result["session_id"])
    cancel_autonomy_v2(first.job_id, session, reason="fixture terminal")
    reused = propose(reference, job="another_job", epoch="epoch-1")
    with pytest.raises(PermissionError, match="cannot be reused"):
        plan_session(reference, reused)
    next_epoch = propose(reference, job="another_job", epoch="epoch-2")
    plan_session(reference, next_epoch)
    assert _session_bundle(first.job_id, session)[4].status == "cancelled"


def test_epoch_admission_has_one_writer_and_releases_after_crash(tmp_path, monkeypatch):
    """An OS guard serializes competing admission and retains no refunded or resettable counter."""

    reference = reference_fixture(tmp_path, monkeypatch)
    proposal = propose(reference)
    with pytest.raises(RuntimeError, match="simulated crash"):
        with fidelity_epoch_admission(proposal):
            with pytest.raises(OSError):
                with fidelity_epoch_admission(proposal):
                    pytest.fail("duplicate admission acquired the same reference guard")
            raise RuntimeError("simulated crash")
    with fidelity_epoch_admission(proposal):
        assert read_fidelity_history(proposal.reference_sha256) == []
