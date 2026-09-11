"""Append-only Material Closure round contracts share one exact AQ session and budget."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import test_autonomy_v2_material_phase as phase_fixture
import test_material_closure_execution_profiles as profiles
import test_material_closure_service as fixture_support
from pydantic import ValidationError

from codex_blender_modeler import material_closure_public as public
from codex_blender_modeler.autonomy_v2.material_phase_service import (
    validate_and_promote_material_controller_result_v2,
)
from codex_blender_modeler.autonomy_v2.models import AutonomyPlanV2, AutonomyStateV2, BudgetUsageV2
from codex_blender_modeler.autonomy_v2.transitions import transition_state
from codex_blender_modeler.blender_artifacts import sha256_file, stable_json_digest
from codex_blender_modeler.material_closure.collector import build_material_plan_absence_evidence
from codex_blender_modeler.material_closure.graph_rebinding import serialize_rebound_material_graph
from codex_blender_modeler.material_closure.models import (
    ExactArtifact,
    MaterialClosureSourceBindingArtifact,
    MaterialGraphRebindingPlan,
    MaterialGraphRebindingReceipt,
    MaterialPreflightBudget,
    MaterialPromotionPreflightRequest,
)
from codex_blender_modeler.material_closure.preflight import MaterialPreflightValidationError
from codex_blender_modeler.material_closure.round_models import (
    MaterialClosureSourceBindingV02,
    MaterialGraphRebindingPlanV02,
    MaterialGraphRebindingReceiptV02,
    parse_material_closure_contract,
)
from codex_blender_modeler.material_closure.round_service import validate_round_source
from codex_blender_modeler.material_closure.service import MaterialClosureService
from codex_blender_modeler.material_closure.state_consistency import (
    build_material_canonical_snapshot,
)
from codex_blender_modeler.material_graph.models import MaterialGraphSpec


def _aq_states(root: Path, binding: dict, geometry: dict) -> tuple[AutonomyStateV2, ExactArtifact]:
    """Create a valid fixture state chain through the real transition functions."""
    plan = AutonomyPlanV2.model_validate_json((root / binding["autonomy_plan_path"]).read_bytes())
    plan_artifact = fixture_support._aq_artifact(
        root,
        binding["autonomy_plan_path"],
        artifact_id=plan.plan_id,
        kind="plan",
    )
    state = AutonomyStateV2(
        contract_id=f"state-{plan.session_id}-0000",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest({"plan": plan_artifact.sha256, "sequence": 0}),
        source_fingerprint=stable_json_digest({"plan": plan_artifact.sha256, "status": "planned"}),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[plan_artifact],
        created_at=plan.created_at,
        state_id=f"state-{plan.session_id}-0000",
        plan=plan_artifact,
        sequence=0,
        phase="planned",
        status="planned",
        next_action="collect_reference",
    )
    prefix = f"production/autonomy_v2/{plan.session_id}/states"
    profiles._write(root, f"{prefix}/0000.json", state)
    geometry_artifact = fixture_support._aq_artifact(
        root,
        binding["geometry_candidate_validation_receipt_path"],
        artifact_id=geometry["receipt_id"],
        kind="geometry_candidate_validation_receipt",
    )
    for event in (
        "reference_ready",
        "controller_required",
        "controller_output_ready",
        "candidate_validated",
    ):
        state = transition_state(
            state,
            event=event,
            evidence=geometry_artifact,
            created_at=plan.created_at,
            budget_usage=BudgetUsageV2.model_validate(geometry["budget_usage_after"]),
        )
        profiles._write(root, f"{prefix}/{state.sequence:04d}.json", state)
    return state, profiles._exact(root, f"{prefix}/0004.json", state.state_id, "autonomy_v2_state")


def _round_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    actual_blender: bool = False,
):
    """Prepare a valid current host profile pair while retaining the original legacy binding."""
    prepared = profiles._prepared(
        tmp_path,
        monkeypatch,
        material=True,
        actual_blender=actual_blender,
    )
    root, original, _source, outputs, binding, geometry = prepared
    state, state_artifact = _aq_states(root, binding, geometry)

    def fixture_job(_job_id: str) -> Path:
        """Route only this test's facade calls to its isolated fixture root."""
        return root

    monkeypatch.setattr(public, "_job_root", fixture_job)
    return root, original, outputs, binding, state, state_artifact


def _round(context, binding_id: str):
    """Publish a new typed binding, absence, snapshots, graph derivative and full closure."""
    root, original, outputs, legacy, state, state_artifact = context
    common = fixture_support._bound_fields()
    prefix = f"production/material_closure/{state.session_id}/bindings/{binding_id}"
    for field, filename in (
        ("canonical_build_provenance_path", "build_provenance.json"),
        ("canonical_scene_inventory_path", "scene_inventory.json"),
    ):
        destination = root / prefix / "canonical_observations" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write((root / legacy[field]).read_bytes())
    scene = profiles._exact(root, "analysis/scene_spec.json", "scene", "scene_spec")
    blend = profiles._exact(root, "blender/scene.blend", "blend", "canonical_blend")
    modeling = profiles._exact(root, "analysis/modeling_plan.json", "modeling", "modeling_plan")
    absence = build_material_plan_absence_evidence(
        job_root=root,
        absence_id=f"absence-{binding_id}",
        observation_state=state_artifact,
        canonical_scene_spec=scene,
        canonical_blend=blend,
        **common,
    )
    profiles._write(root, f"{prefix}/absence.json", absence)
    absence_artifact = profiles._exact(
        root, f"{prefix}/absence.json", absence.absence_id, "material_plan_absence"
    )
    snapshot = build_material_canonical_snapshot(
        job_root=root,
        snapshot_id=f"snapshot-{binding_id}",
        scene_spec=scene,
        modeling_plan=modeling,
        blend=blend,
        material_plan_absence=absence_artifact,
        build_provenance=profiles._exact(
            root,
            f"{prefix}/canonical_observations/build_provenance.json",
            f"build-{binding_id}",
            "build_provenance",
        ),
        **common,
    )
    profiles._write(root, f"{prefix}/snapshot.json", snapshot)
    snapshot_artifact = profiles._exact(
        root, f"{prefix}/snapshot.json", snapshot.snapshot_id, "material_canonical_snapshot"
    )
    rebind_prefix = f"production/material_closure/{state.session_id}/graph_rebindings/{binding_id}"
    graph = MaterialGraphSpec.model_validate_json(
        (root / legacy["material_graph_path"]).read_bytes()
    )
    source_graph_path = f"{prefix}/source_graph.json"
    with (root / source_graph_path).open("xb") as handle:
        handle.write(serialize_rebound_material_graph(graph.model_dump(mode="json")))
    source_graph = profiles._exact(
        root,
        source_graph_path,
        f"graph-{binding_id}",
        "source_material_graph",
    )
    data = dict(legacy)
    data.update(
        schema_version="0.2.0",
        binding_id=binding_id,
        execution_id="exec-0005-material_authoring",
        source_state=state_artifact.model_dump(mode="json"),
        canonical_build_provenance_path=f"{prefix}/canonical_observations/build_provenance.json",
        canonical_scene_inventory_path=f"{prefix}/canonical_observations/scene_inventory.json",
        material_plan_absence_evidence_path=absence_artifact.path,
        rollback_baseline_path=snapshot_artifact.path,
        material_graph_path=source_graph_path,
        graph_rebinding_plan_path=f"{rebind_prefix}/plan.json",
        graph_rebinding_receipt_path=f"{rebind_prefix}/receipt.json",
        rebound_material_graph_path=f"{rebind_prefix}/rebound_material_graph.json",
    )
    binding = MaterialClosureSourceBindingV02.model_validate_json(json.dumps(data))
    profiles._write(root, binding.source_binding_path(), binding)
    source = profiles._exact(
        root, binding.source_binding_path(), binding.binding_id, "material_closure_source_binding"
    )
    plan = json.loads((root / legacy["graph_rebinding_plan_path"]).read_bytes())
    plan.update(
        schema_version="0.2.0",
        binding_id=binding_id,
        plan_id=binding_id,
        source_binding=source.model_dump(mode="json"),
        source_graph=source_graph.model_dump(mode="json"),
        output_path=binding.rebound_material_graph_path,
    )
    plan = MaterialGraphRebindingPlanV02.model_validate_json(json.dumps(plan))
    profiles._write(root, binding.graph_rebinding_plan_path, plan)
    rebound = public.rebind_material_graph(
        binding.job_id,
        source_graph_path=binding.material_graph_path,
        plan_path=binding.graph_rebinding_plan_path,
    )
    profiles._write(
        root,
        f"{prefix}/outputs.json",
        {"planned_outputs": [item.model_dump(mode="json") for item in outputs]},
    )
    closure = public.plan_material_closure(
        binding.job_id,
        source_binding_path=source.path,
        planned_outputs_path=f"{prefix}/outputs.json",
        closure_id=binding_id,
    )
    return binding, closure, rebound, snapshot, snapshot_artifact


def _request(context, round_data, *, budget_runs: int = 12) -> MaterialPromotionPreflightRequest:
    """Bind a round to one immutable session-wide preflight allowance and current state."""
    root, _original, _outputs, _legacy, state, state_artifact = context
    binding, closure, rebound, snapshot, snapshot_artifact = round_data
    template = MaterialPromotionPreflightRequest.model_validate_json(
        (root / "production/preflight_template.json").read_bytes()
    )
    budget_path = "production/session_preflight_budget.json"
    if not (root / budget_path).exists():
        budget = MaterialPreflightBudget.model_validate_json(
            (root / template.budget.path).read_bytes()
        )
        budget = budget.model_copy(
            update={
                "budget_id": "one-session-budget",
                "limits": budget.limits.model_copy(update={"preflight_blender_runs": budget_runs}),
            }
        )
        profiles._write(root, budget_path, budget)
    failure_context = template.framework_failure_context.model_copy(
        update={
            "state_sequence": state.sequence,
            "current_state": state_artifact,
            "canonical_snapshot": snapshot,
            "controller_execution_count": state.budget_usage.controller_invocations,
        }
    )
    return template.model_copy(
        update={
            "request_id": binding.binding_id,
            "closure": ExactArtifact.model_validate(closure["closure_artifact"]),
            "closure_receipt": ExactArtifact.model_validate(closure["receipt_artifact"]),
            "graph_rebinding_receipt": ExactArtifact.model_validate(rebound["receipt_artifact"]),
            "rebound_material_graph": ExactArtifact.model_validate(
                rebound["rebound_graph_artifact"]
            ),
            "canonical_snapshot": snapshot_artifact,
            "budget": profiles._exact(
                root, budget_path, "one-session-budget", "material_preflight_budget"
            ),
            "framework_failure_context": failure_context,
            "planned_output_projection": closure["receipt"]["planned_output_projection"],
        }
    )


def test_two_round_bindings_preserve_prior_bytes_and_use_one_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create distinct current candidates without rewriting any earlier companion or AQ budget."""
    context = _round_context(tmp_path, monkeypatch)
    root = context[0]
    first = _round(context, "round-alpha")
    protected = {path.relative_to(root): sha256_file(path) for path in root.rglob("*.json")}
    second = _round(context, "round-beta")
    assert first[0].session_id == second[0].session_id
    assert first[0].source_state == second[0].source_state
    assert first[0].source_binding_path() != second[0].source_binding_path()
    assert protected == {path: sha256_file(root / path) for path in protected}
    assert first[1]["closure_artifact"]["sha256"] != second[1]["closure_artifact"]["sha256"]


def test_round_and_legacy_companion_versions_never_auto_migrate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require explicit versions and reject attempts to reuse the legacy singleton namespace."""
    context = _round_context(tmp_path, monkeypatch)
    root = context[0]
    binding, _closure, rebound, _snapshot, _artifact = _round(context, "round-alpha")
    payload = (root / binding.source_binding_path()).read_bytes()
    assert isinstance(
        parse_material_closure_contract(payload, MaterialClosureSourceBindingArtifact),
        MaterialClosureSourceBindingV02,
    )
    with pytest.raises(ValidationError):
        MaterialClosureSourceBindingArtifact.model_validate_json(payload)
    receipt = rebound["receipt"]
    assert isinstance(
        parse_material_closure_contract(json.dumps(receipt), MaterialGraphRebindingReceipt),
        MaterialGraphRebindingReceiptV02,
    )
    legacy = json.loads(payload)
    legacy["schema_version"] = "0.9.9"
    with pytest.raises(ValueError, match="unknown"):
        parse_material_closure_contract(json.dumps(legacy), MaterialClosureSourceBindingArtifact)
    plan = json.loads((root / binding.graph_rebinding_plan_path).read_bytes())
    plan["source_binding"]["path"] = (
        f"production/material_closure/{binding.session_id}/source_binding.json"
    )
    with pytest.raises(ValidationError, match="canonical"):
        MaterialGraphRebindingPlanV02.model_validate_json(json.dumps(plan))
    plan["source_binding"]["path"] = binding.source_binding_path()
    plan["schema_version"] = "0.1.0"
    plan.pop("binding_id")
    with pytest.raises(ValidationError, match="canonical"):
        MaterialGraphRebindingPlan.model_validate_json(json.dumps(plan))


def test_round_rejects_stale_source_without_reopening_a_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a once-current binding after an append-only terminal transition."""
    context = _round_context(tmp_path, monkeypatch)
    root, _original, _outputs, legacy, state, _state_artifact = context
    binding = _round(context, "round-alpha")[0]
    plan = AutonomyPlanV2.model_validate_json((root / legacy["autonomy_plan_path"]).read_bytes())
    assert validate_round_source(root, binding, plan, require_current_state=True) is None
    cancelled = transition_state(
        state,
        event="cancelled",
        evidence=state.plan,
        created_at=state.created_at,
        reason="fixture stop",
    )
    profiles._write(root, f"production/autonomy_v2/{state.session_id}/states/0005.json", cancelled)
    with pytest.raises(ValueError, match="stale"):
        validate_round_source(root, binding, plan, require_current_state=True)


def test_round_rebinding_rejects_mixed_binding_identity_before_derivative_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject valid-looking metadata from another round before publishing graph evidence."""
    context = _round_context(tmp_path, monkeypatch)
    root = context[0]
    binding, _closure, _rebound, _snapshot, _artifact = _round(context, "round-alpha")
    plan = json.loads((root / binding.graph_rebinding_plan_path).read_bytes())
    plan["plan_id"] = "mixed-round"
    plan["output_path"] = (
        f"production/material_closure/{binding.session_id}/graph_rebindings/mixed-round/rebound_material_graph.json"
    )
    path = (
        f"production/material_closure/{binding.session_id}/graph_rebindings/mixed-round/plan.json"
    )
    profiles._write(root, path, plan)
    with pytest.raises(ValueError, match="different rounds"):
        public.rebind_material_graph(
            binding.job_id, source_graph_path=binding.material_graph_path, plan_path=path
        )
    assert not (root / plan["output_path"]).exists()


def test_distinct_round_preflights_share_budget_and_exact_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Charge each closure once across binding IDs and stop when the finite reserve is exhausted."""
    context = _round_context(tmp_path, monkeypatch)
    root = context[0]
    calls = 0

    def counted_shadow(*args, **kwargs):
        """Count test-only shadow calls without using Blender in Python CI."""
        nonlocal calls
        calls += 1
        return fixture_support._fake_shadow(*args, **kwargs)

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        counted_shadow,
    )
    service = MaterialClosureService(root)
    first_request = _request(context, _round(context, "round-alpha"))
    first = service.run_preflight(first_request, preview_size=64, created_at=fixture_support.NOW)
    assert first.report is not None, first.failure
    resumed = service.run_preflight(first_request, preview_size=64, created_at=fixture_support.NOW)
    assert resumed.report == first.report
    assert calls == 1
    second_request = _request(context, _round(context, "round-beta"))
    second = service.run_preflight(second_request, preview_size=64, created_at=fixture_support.NOW)
    assert second.report is not None, second.failure
    assert calls == 2
    assert first_request.budget == second_request.budget
    third_request = _request(context, _round(context, "round-gamma"))
    third = service.run_preflight(third_request, preview_size=64, created_at=fixture_support.NOW)
    assert third.failure is not None
    assert "budget" in str(third.failure.issues).lower()
    assert calls == 2
    assert third.failure.canonical_write_performed is False


def test_round_preflight_rejects_a_receipt_from_another_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop receipt mixing before Blender, controller invocation or canonical promotion."""
    context = _round_context(tmp_path, monkeypatch)
    root = context[0]
    first = _request(context, _round(context, "round-alpha"))
    second = _request(context, _round(context, "round-beta"))
    mixed = second.model_copy(update={"graph_rebinding_receipt": first.graph_rebinding_receipt})

    def forbidden_shadow(*_args, **_kwargs):
        """Fail if a mismatched round can reach any Blender operation."""
        raise AssertionError("mixed round reached Blender")

    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        forbidden_shadow,
    )
    result = MaterialClosureService(root).run_preflight(
        mixed, preview_size=64, created_at=fixture_support.NOW
    )
    assert result.failure is not None
    assert result.failure.controller_invocations_consumed == 0
    assert result.failure.canonical_promotions_consumed == 0
    assert result.failure.canonical_write_performed is False


def test_completed_round_replays_after_controller_but_cannot_spend_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep predecessor preflight evidence readable while forbidding stale new execution."""
    context = _round_context(tmp_path, monkeypatch)
    root, _original, _outputs, _legacy, state, _state_artifact = context
    monkeypatch.setattr(
        "codex_blender_modeler.material_closure.service._run_material_shadow_compile",
        fixture_support._fake_shadow,
    )
    service = MaterialClosureService(root)
    result = service.run_preflight(
        _request(context, _round(context, "alpha")),
        preview_size=64,
        created_at=fixture_support.NOW,
    )
    assert result.report is not None, result.failure
    next_state = transition_state(
        state,
        event="controller_output_ready",
        evidence=state.plan,
        created_at=state.created_at,
    )
    profiles._write(root, f"production/autonomy_v2/{state.session_id}/states/0005.json", next_state)
    assert service.validate_published_preflight(result.report_artifact) == result.report
    with pytest.raises(MaterialPreflightValidationError, match="stale"):
        service.validate_preflight_for_approval(result.report_artifact)


def _promoted_lineage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Combine a typed round with a real host promotion receipt for source-lineage unit tests."""
    (tmp_path / "template").mkdir()
    template = _round(_round_context(tmp_path / "template", monkeypatch), "alpha")[0]
    root, plan, budget, previous, output, _baseline = phase_fixture._fixture(
        tmp_path / "promotion", monkeypatch, execution_scoped=True
    )
    receipt, promoted = validate_and_promote_material_controller_result_v2(
        root, plan, budget, previous, output
    )
    profiles._write(root, "production/geometry.json", {"fixture": "prior-geometry-evidence"})
    geometry = fixture_support._aq_artifact(
        root,
        "production/geometry.json",
        artifact_id="geometry",
        kind="geometry_candidate_validation_receipt",
    )
    state = AutonomyStateV2.model_validate_json(
        previous.model_copy(
            update={
                "sequence": 3,
                "state_id": "lineage-state-0003",
                "contract_id": "lineage-state-0003",
                "next_action": "execute_controller",
                "provenance": [*previous.provenance, geometry, promoted],
                "budget_usage": receipt.budget_usage_after,
            }
        ).model_dump_json()
    )
    state_path = f"production/autonomy_v2/{plan.session_id}/states/0003.json"
    profiles._write(root, state_path, state)
    payload = json.loads(template.model_dump_json().replace(template.session_id, plan.session_id))
    for key in ("job_id", "workflow_id", "dispatch_id", "session_id"):
        payload[key] = getattr(plan, key)
    payload.update(
        execution_id="exec-0004-material_authoring",
        source_state=profiles._exact(root, state_path, state.state_id, "state").model_dump(
            mode="json"
        ),
        previous_material_phase_receipt=profiles._exact(
            root, promoted.path, promoted.artifact_id, "material_phase_receipt"
        ).model_dump(mode="json"),
        autonomy_plan_path=state.plan.path,
        geometry_candidate_validation_receipt_path=geometry.path,
    )
    binding = MaterialClosureSourceBindingV02.model_validate_json(json.dumps(payload))
    for path, source in (
        (binding.canonical_scene_inventory_path, receipt.scene_inventory_snapshot),
        (binding.canonical_build_provenance_path, receipt.build_provenance_snapshot),
    ):
        profiles._write(root, path, json.loads((root / source.path).read_bytes()))
    return root, plan, binding, receipt


def test_round_accepts_exact_promoted_material_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revalidate the real host receipt and exact current Blend before accepting its successor."""
    root, plan, binding, receipt = _promoted_lineage(tmp_path, monkeypatch)
    assert validate_round_source(root, binding, plan) == receipt


@pytest.mark.parametrize("mutation", ["omitted", "mixed", "blend", "inventory", "geometry"])
def test_round_rejects_unproven_material_supersession(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    """Reject omitted, mixed, stale or out-of-order lineage without changing the host receipt."""
    root, plan, binding, _receipt = _promoted_lineage(tmp_path, monkeypatch)
    protected = sha256_file(root / binding.previous_material_phase_receipt.path)
    if mutation == "omitted":
        binding = binding.model_copy(update={"previous_material_phase_receipt": None})
    elif mutation == "mixed":
        mixed = binding.previous_material_phase_receipt.model_copy(update={"sha256": "0" * 64})
        binding = binding.model_copy(
            update={"previous_material_phase_receipt": mixed}
        )
    elif mutation == "blend":
        (root / "blender/scene.blend").write_bytes(b"unproven-fixture-blend")
    elif mutation == "inventory":
        profiles._write(root, binding.canonical_scene_inventory_path, {"changed": True})
    else:
        state = AutonomyStateV2.model_validate_json((root / binding.source_state.path).read_bytes())
        geometry = next(
            item
            for item in state.provenance
            if item.kind == "geometry_candidate_validation_receipt"
        )
        state = state.model_copy(update={"provenance": [*state.provenance, geometry]})
        profiles._write(root, binding.source_state.path, state)
        binding = binding.model_copy(
            update={
                "source_state": profiles._exact(
                    root, binding.source_state.path, state.state_id, "state"
                )
            }
        )
    with pytest.raises(ValueError):
        validate_round_source(root, binding, plan)
    receipt_path = next(
        root.glob("production/autonomy_v2/*/material_phase/*/promotion_receipt.json")
    )
    assert sha256_file(receipt_path) == protected


@pytest.mark.skipif(
    os.environ.get("CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE") != "1",
    reason="set CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE=1 for real round preflights",
)
def test_rounds_run_two_real_blender_preflights_with_one_finite_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run two six-process Blender closures while preserving geometry and prior evidence."""
    context = _round_context(tmp_path, monkeypatch, actual_blender=True)
    root = context[0]
    service = MaterialClosureService(root)
    canonical = {
        path: sha256_file(root / path)
        for path in (
            "analysis/scene_spec.json",
            "analysis/modeling_plan.json",
            "blender/scene.blend",
        )
    }
    results = []
    for binding_id in ("alpha", "beta"):
        request = _request(context, _round(context, binding_id))
        result = service.run_preflight(request, preview_size=64)
        assert result.status == "complete_preflight_passed", result.failure
        assert result.shadow_receipt.blender_version == "5.0.1"
        assert result.resource_receipt.consumed_by_event.preflight_blender_runs == 6
        assert result.resource_receipt.consumed_by_event.canonical_promotions == 0
        assert result.report.canonical_unchanged is True
        results.append(result)
    assert canonical == {path: sha256_file(root / path) for path in canonical}
    assert not (root / "analysis/material_plan.json").exists()
    for result in results:
        assert service.validate_published_preflight(result.report_artifact) == result.report
