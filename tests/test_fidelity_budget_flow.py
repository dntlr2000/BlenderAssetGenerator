"""Funded host reentry safety over explicit synthetic prior-promotion fixtures."""

from __future__ import annotations

import json

import pytest
from test_quality_revision_flow import quality_fixture

from codex_blender_modeler.autonomy_v2 import quality_revision_service as service
from codex_blender_modeler.autonomy_v2 import supervisor_service
from codex_blender_modeler.autonomy_v2.quality_revision_models import RevisionCostV01
from codex_blender_modeler.autonomy_v2.transitions import validate_state_transition
from codex_blender_modeler.reference_fidelity.models import FidelityArtifact


def test_funded_reentry_crash_adopts_exact_reservation_once(tmp_path, monkeypatch):
    """A pre-transition crash preserves the priced reservation without a second charge."""

    fixture = quality_fixture(tmp_path, monkeypatch, funded=True)
    cost = RevisionCostV01(**fixture.loop.funding.route_cost("structural_reentry"))
    before = fixture.holder.state
    original_write = supervisor_service._write_next_state

    def crash(*_args):
        """Interrupt only after the exact source snapshot and cost ledger are durably published."""

        raise RuntimeError("simulated funded crash")

    monkeypatch.setattr(supervisor_service, "_write_next_state", crash)
    with pytest.raises(RuntimeError, match="simulated funded"):
        service.begin_quality_reentry(fixture.job, fixture.session,
                                      strategy=fixture.attempt.strategy, cost=cost)
    ledger = fixture.session_path / "fidelity/reservations/0001.json"
    preserved = ledger.read_bytes()
    monkeypatch.setattr(supervisor_service, "_write_next_state", original_write)
    result = service.begin_quality_reentry(fixture.job, fixture.session,
                                           strategy=fixture.attempt.strategy, cost=cost)
    after = type(before).model_validate_json(json.dumps(result["state"]))
    validate_state_transition(before, after)
    service.validate_reentry_transition(fixture.root, before, after)
    assert ledger.read_bytes() == preserved
    assert len(list(ledger.parent.glob("*.json"))) == 1


@pytest.mark.parametrize("defect", ["stale_source", "mixed_receipt", "underfunded_cost"])
def test_funded_reentry_rejects_stale_or_mixed_evidence_before_snapshot(
    tmp_path, monkeypatch, defect,
):
    """Funding grants no stale-source, cross-round receipt or cheaper-cost bypass."""

    fixture = quality_fixture(tmp_path, monkeypatch, funded=True)
    cost = RevisionCostV01(**fixture.loop.funding.route_cost("structural_reentry"))
    if defect == "stale_source":
        # This file is created by the synthetic QA fixture; no user evidence is modified.
        path = fixture.root / "analysis/scene_spec.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif defect == "mixed_receipt":
        original_receipts = service.current_round_receipts

        def mixed(root, plan, state):
            """Substitute only the fixture's reported material receipt to exercise exact binding."""

            geometry, material = original_receipts(root, plan, state)
            return geometry, FidelityArtifact(path=material.path, sha256="f" * 64)

        monkeypatch.setattr(service, "current_round_receipts", mixed)
    else:
        cost.builds -= 1
    with pytest.raises((ValueError, PermissionError)):
        service.begin_quality_reentry(fixture.job, fixture.session,
                                      strategy=fixture.attempt.strategy, cost=cost)
    assert not (fixture.session_path / "fidelity/sources").exists()
    assert not (fixture.session_path / "fidelity/reservations").exists()


def test_funded_exhaustion_stops_with_exact_attempt_preserved(tmp_path, monkeypatch):
    """A real priced next round cannot borrow remaining nominal slots after root cost exhaustion."""

    fixture = quality_fixture(tmp_path, monkeypatch, funded=True, builds_used=18)
    preserved = (fixture.root / fixture.attempt_ref.path).read_bytes()
    boundary = service.quality_revision_boundary(fixture.root, fixture.plan, fixture.holder.state)
    assert boundary["next_action"] == "review_required"
    assert boundary["attempt"] == fixture.attempt_ref.model_dump(mode="json")
    assert boundary["human_quality_disposition"] == "not_recorded"
    assert (fixture.root / fixture.attempt_ref.path).read_bytes() == preserved
    assert not (fixture.session_path / "fidelity/reservations").exists()


def test_closure_history_retains_consumption_and_rejects_mixed_receipts(tmp_path, monkeypatch):
    """Inherit verified preflight costs once and reject later receipt tampering during planning."""

    from test_material_closure_service import NOW, _fake_shadow, _fixture

    from codex_blender_modeler.autonomy_v2.fidelity_budget_service import _preflight_history
    from codex_blender_modeler.material_closure.service import MaterialClosureService

    fixture = _fixture(tmp_path)
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile", _fake_shadow,
    )
    closure_service = MaterialClosureService(fixture.root)
    first = closure_service.run_preflight(fixture.request, preview_size=64, created_at=NOW)
    assert first.failure is None
    before = _preflight_history(fixture.root, fixture.request.session_id)
    assert before[0] == 6
    closure_service.run_preflight(fixture.request, preview_size=64, created_at=NOW)
    assert _preflight_history(fixture.root, fixture.request.session_id) == before
    receipt = fixture.root / first.resource_receipt_artifact.path
    payload = json.loads(receipt.read_bytes())
    payload["session_id"] = "mixed-session"
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="another session or budget"):
        _preflight_history(fixture.root, fixture.request.session_id)
