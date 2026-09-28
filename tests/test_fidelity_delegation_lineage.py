"""Replacement mandate ancestry preserves observations, reservations and exact terminals."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_fidelity_campaign_delegation import admit, fixture, prepare, reserve

from codex_blender_modeler.autonomy_v2 import delegation_service as service
from codex_blender_modeler.autonomy_v2.controller_bridge import _session_bundle, cancel_autonomy_v2
from codex_blender_modeler.autonomy_v2.delegation_models import (
    DelegationBindingV01,
    DelegationCost,
)
from codex_blender_modeler.production.activation_models import ActivationArtifact


def close_candidate(fix, binding, *, publish_outcome=True):
    """Exercise real isolated native admission/cancellation without any production approval."""
    prepare(binding)
    started = admit(fix, binding)
    cancel_autonomy_v2(
        str(started["job_id"]), str(started["session_id"]), reason="lineage regression fixture"
    )
    if publish_outcome:
        service.close_fidelity_scope(binding, session_id=str(started["session_id"]))
    return started


def replacement(fix, identity, *, asset_id=None, entry_switches=1):
    """Approve only a synthetic successor, carrying the full cumulative reserved capacity."""
    status = service.get_fidelity_delegation_status(fix.contract.delegation_id)
    slots = [fix.asset.slots[0].model_copy(update={"strategy_switches": entry_switches})]
    asset = fix.asset.model_copy(update={
        "asset_id": asset_id or fix.asset.asset_id,
        "prior_history": service.read_fidelity_history(fix.asset.reference.sha256),
        "slots": slots,
    })
    contract = fix.contract.model_copy(update={
        "delegation_id": identity,
        "supersedes": ActivationArtifact.model_validate(status["contract"]),
        "prior_delegated_reservations": DelegationCost.model_validate(
            status["prior_delegated_reservations"]
        ).plus(DelegationCost.model_validate(status["reserved"])),
        "assets": [asset],
        "total_budget": asset.cost(),
    })
    planned = service.plan_fidelity_delegation(contract)
    digest = planned["artifact"]["sha256"]
    service.approve_fidelity_delegation(
        identity, contract_sha256=digest,
        exact_user_text=f"TEST FIXTURE ONLY: approve replacement {digest}",
    )
    return SimpleNamespace(contract=contract, asset=asset, digest=digest,
                           reference=fix.reference, root=fix.root)


def observation(*, strategy="solid_sections", feature="worn_surface"):
    """Create a synthetic observation at the existing verified-attempt test seam."""
    return SimpleNamespace(strategy=strategy, next_action="material_revision",
                           unresolved_features=[feature])


@pytest.mark.parametrize("rename_asset", [False, True])
def test_replacement_cannot_repeat_inherited_stagnation(tmp_path, monkeypatch, rename_asset):
    """The first new-parent slot retains the prior two-hit defect even if asset IDs change."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    close_candidate(fix, first)
    previous = [observation(), observation()]
    monkeypatch.setattr(service, "_verified_scope_attempts", lambda _scope: previous)
    successor = replacement(fix, "replacement", asset_id="renamed" if rename_asset else None)
    before = service.get_fidelity_delegation_status(successor.contract.delegation_id)
    with pytest.raises(PermissionError, match="stagnated"):
        service.issue_fidelity_scope(
            successor.contract.delegation_id, asset_id=successor.asset.asset_id,
            job_id="renamed_job", strategy="solid_sections",
        )
    after = service.get_fidelity_delegation_status(successor.contract.delegation_id)
    assert after == before
    assert after["prior_delegated_reservations"] == service.get_fidelity_delegation_status(
        first.delegation_id
    )["reserved"]


@pytest.mark.parametrize("entry_switches", [0, 1])
def test_replacement_strategy_change_consumes_exact_entry_reserve(
    tmp_path, monkeypatch, entry_switches
):
    """A real strategy change requires finite new reserve and consumes its one switch on entry."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    close_candidate(fix, first)
    monkeypatch.setattr(service, "_verified_scope_attempts", lambda _scope: [observation()] * 2)
    successor = replacement(fix, "replacement", entry_switches=entry_switches)
    if entry_switches == 0:
        with pytest.raises(PermissionError, match="no delegated reserve"):
            service.issue_fidelity_scope(
                "replacement", asset_id="fixture", job_id="changed", strategy="volumetric_wear"
            )
        return
    issued = service.issue_fidelity_scope(
        "replacement", asset_id="fixture", job_id="changed", strategy="volumetric_wear"
    )
    assert issued["scope"]["strategy_switch_reserved_on_entry"] is True
    binding = DelegationBindingV01.model_validate(issued["binding"])
    prepare(binding)
    native = admit(successor, binding)
    budget = _session_bundle(str(native["job_id"]), str(native["session_id"]))[3]
    assert service.delegated_switch_offset(budget) == 1
    with pytest.raises(PermissionError, match="switch budget exhausted"):
        service.validate_delegated_strategy(
            budget, [], strategy="another_strategy", reserved_switches=1
        )


@pytest.mark.parametrize("same_defect", [False, True])
def test_runtime_joins_predecessor_and_current_attempt_without_duplicate(
    tmp_path, monkeypatch, same_defect
):
    """A first new-parent observation completes the prior plateau under the same native budget."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    close_candidate(fix, first)
    older = observation()
    monkeypatch.setattr(service, "_verified_scope_attempts", lambda _scope: [older])
    successor = replacement(fix, "replacement")
    issued = service.issue_fidelity_scope(
        "replacement", asset_id="fixture", job_id="current", strategy="solid_sections"
    )
    binding = DelegationBindingV01.model_validate(issued["binding"])
    prepare(binding)
    native = admit(successor, binding)
    budget = _session_bundle(str(native["job_id"]), str(native["session_id"]))[3]
    current = observation(feature="worn_surface" if same_defect else "new_feature")
    assert service.delegated_attempt_history(budget, [current]) == [older, current]
    if same_defect:
        with pytest.raises(PermissionError, match="stagnated twice"):
            service.validate_delegated_strategy(
                budget, [current], strategy="solid_sections", reserved_switches=0
            )
    else:
        service.validate_delegated_strategy(
            budget, [current], strategy="solid_sections", reserved_switches=0
        )


def test_empty_intermediate_parent_cannot_hide_older_plateau(tmp_path, monkeypatch):
    """An approved parent with no scopes keeps the complete older reference lineage."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    close_candidate(fix, first)
    monkeypatch.setattr(service, "_verified_scope_attempts", lambda _scope: [observation()] * 2)
    middle = replacement(fix, "middle", asset_id="renamed_middle")
    last = replacement(middle, "last", asset_id="renamed_last")
    with pytest.raises(PermissionError, match="stagnated"):
        service.issue_fidelity_scope(
            "last", asset_id=last.asset.asset_id, job_id="last_job", strategy="solid_sections"
        )
    assert service.get_fidelity_delegation_status("last")[
        "prior_delegated_reservations"
    ] == service.get_fidelity_delegation_status(first.delegation_id)["reserved"]


def test_never_admitted_reservation_has_no_fake_visual_observation(tmp_path, monkeypatch):
    """Unstarted scopes preserve their full reserve without requiring an invented terminal."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    successor = replacement(fix, "replacement", entry_switches=0)
    issued = service.issue_fidelity_scope(
        "replacement", asset_id="fixture", job_id="first_actual", strategy="fresh_strategy"
    )
    assert issued["scope"]["strategy_switch_reserved_on_entry"] is False
    assert successor.contract.prior_delegated_reservations == DelegationCost.model_validate(
        service.get_fidelity_delegation_status(first.delegation_id)["reserved"]
    )


def test_cancelled_session_requires_exact_parent_outcome_before_replacement(tmp_path, monkeypatch):
    """Native terminal alone cannot hide missing delegation closeout during crash/resume."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    native = close_candidate(fix, first, publish_outcome=False)
    with pytest.raises(PermissionError, match="exact outcome"):
        replacement(fix, "replacement")
    service.close_fidelity_scope(first, session_id=str(native["session_id"]))
    replacement(fix, "replacement")


@pytest.mark.parametrize("mutation", ["contract", "outcome", "state"])
def test_changed_ancestor_evidence_blocks_new_scope(tmp_path, monkeypatch, mutation):
    """Each new boundary rehashes predecessor approval, outcome and native terminal evidence."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    native = close_candidate(fix, first)
    replacement(fix, "replacement")
    directory = service._directory(first.delegation_id)
    if mutation == "contract":
        path = directory / "contract.json"
        value = json.loads(path.read_bytes())
        value["user_request"] += " changed fixture"
    elif mutation == "outcome":
        path = directory / "outcomes/0001.json"
        value = json.loads(path.read_bytes())
        value["technical_passed"] = True
    else:
        states = (
            fix.root / native["job_id"] / "production/autonomy_v2" / native["session_id"] / "states"
        )
        path = sorted(states.glob("*.json"))[-1]
        value = json.loads(path.read_bytes())
        value["terminal_reason"] += " changed fixture"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        service.issue_fidelity_scope(
            "replacement", asset_id="fixture", job_id="blocked", strategy="solid_sections"
        )


def test_historical_status_does_not_reclassify_outcome_after_source_change(tmp_path, monkeypatch):
    """Terminal reads remain available after source drift while execution fails closed."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    close_candidate(fix, first)
    before = service.get_fidelity_delegation_status(first.delegation_id)

    def stale_source(_contract):
        """Model source drift without changing immutable contract or terminal bytes."""
        raise PermissionError("source changed")

    monkeypatch.setattr(service, "_validate_source", stale_source)
    assert service.get_fidelity_delegation_status(first.delegation_id) == before
    with pytest.raises(PermissionError, match="source changed"):
        reserve(fix, job="forbidden")


def test_native_resume_rechecks_predecessor_outcome_before_effects(tmp_path, monkeypatch):
    """A saved new-parent session cannot resume after its inherited outcome has been changed."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    close_candidate(fix, first)
    successor = replacement(fix, "replacement")
    issued = service.issue_fidelity_scope(
        "replacement", asset_id="fixture", job_id="current", strategy="solid_sections"
    )
    binding = DelegationBindingV01.model_validate(issued["binding"])
    prepare(binding)
    native = admit(successor, binding)
    _session_bundle(str(native["job_id"]), str(native["session_id"]))
    path = service._directory(first.delegation_id) / "outcomes/0001.json"
    value = json.loads(path.read_bytes())
    value["visual_passed"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="host-recomputed"):
        _session_bundle(str(native["job_id"]), str(native["session_id"]))
