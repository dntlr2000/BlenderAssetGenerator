"""Finite parent mandate enforcement; synthetic fixtures never establish asset quality."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_fidelity_budget_epoch import reference_fixture
from test_reference_fidelity import hypothesis

from codex_blender_modeler.autonomy_v2 import delegation_service as service
from codex_blender_modeler.autonomy_v2.approval_policy_service import _load_approval_boundary
from codex_blender_modeler.autonomy_v2.approval_supervisor_service import plan_one_prompt_run
from codex_blender_modeler.autonomy_v2.controller_bridge import _session_bundle, cancel_autonomy_v2
from codex_blender_modeler.autonomy_v2.delegation_models import (
    DelegationAsset,
    DelegationBindingV01,
    DelegationCost,
    DelegationSlot,
    FidelityCampaignDelegationV01,
)
from codex_blender_modeler.autonomy_v2.models import AutonomyBudgetV04, parse_autonomy_budget
from codex_blender_modeler.autonomy_v2.planner import plan_autonomous_static_prop_v2

SOURCE_VALIDATOR = service._validate_source


def fixture(tmp_path, monkeypatch, *, approve=True):
    """Build isolated reference/criteria evidence and mock only the external Git baseline check."""
    reference = reference_fixture(tmp_path, monkeypatch)
    settings = service.get_settings()
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(
            repo_root=tmp_path,
            workspace_root=settings.workspace_root,
        ),
    )
    monkeypatch.setattr(service, "_validate_source", lambda _contract: None)
    ref = service.exact_artifact(tmp_path, reference, "reference_image")
    hyp = hypothesis().model_copy(
        update={
            "reference": hypothesis().reference.model_copy(update={"sha256": ref.sha256}),
        }
    )
    hyp_path = tmp_path / "hypothesis.json"
    hyp_path.write_text(hyp.model_dump_json(), encoding="utf-8")
    hyp_ref = service.exact_artifact(tmp_path, hyp_path, "modeling_hypothesis")
    slot = DelegationSlot(
        initial_object_limit=8,
        correction_object_limit=8,
        structural_rounds=2,
        parametric_rounds=0,
        material_corrections=1,
        strategy_switches=1,
    )
    reserve = DelegationSlot(
        initial_object_limit=8,
        correction_object_limit=8,
        structural_rounds=1,
        parametric_rounds=0,
        material_corrections=1,
        strategy_switches=0,
    )
    asset = DelegationAsset(
        asset_id="fixture",
        target_subject="fixture shape",
        reference=ref,
        hypothesis=hyp_ref,
        prior_history=[],
        prior_initial_candidates=0,
        inherited_evidence=[hyp_ref],
        slots=[slot, reserve],
    )
    proposal = FidelityCampaignDelegationV01(
        delegation_id="fixture-delegation",
        user_request="Build the bounded fixture campaign.",
        source_manifest=hyp_ref,
        baseline=hyp_ref,
        assets=[asset],
        total_budget=asset.cost(),
        expires_at=datetime.now(UTC) + timedelta(days=2),
    )
    planned = service.plan_fidelity_delegation(proposal)
    digest = planned["artifact"]["sha256"]
    if approve:
        service.approve_fidelity_delegation(
            proposal.delegation_id,
            contract_sha256=digest,
            exact_user_text=f"Approve this mandate {digest}",
        )
    return SimpleNamespace(
        contract=proposal,
        reference=reference,
        digest=digest,
        asset=asset,
        root=settings.workspace_root,
    )


def reserve(fix, *, job="delegated_fixture"):
    """Issue and resolve one exact host reservation without synthesizing another user decision."""
    result = service.issue_fidelity_scope(
        fix.contract.delegation_id, asset_id="fixture", job_id=job, strategy="solid_sections"
    )
    return DelegationBindingV01.model_validate(result["binding"])


def prepare(binding, index=0):
    """Publish a tiny staged data set used only for admission tests, not artistic validation."""
    path = (
        service._directory(binding.delegation_id)
        / "staging"
        / f"{binding.scope_sequence:04d}"
        / f"{index:04d}"
        / "data.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"fixture_version": index}), encoding="utf-8")
    return service.publish_fidelity_preparation(binding, [path])


def admit(fix, binding):
    """Use the real native One-Prompt planner with the exact mandate-derived finite epoch."""
    _contract, asset, scope, _scopes = service._bound_scope(binding)
    return plan_one_prompt_run(
        fix.contract.user_request,
        reference_path=fix.reference,
        target_subject=asset.target_subject,
        requested_delivery_profiles=["portable_gltf"],
        job_id=scope.job_id,
        fidelity_budget_plan=scope.funding,
        delegation_binding=binding,
        explicit_autonomy_delegation_observed=True,
        allow_disabled_experimental=True,
    )


def test_one_mandate_priced_scopes_and_no_human_acceptance(tmp_path, monkeypatch):
    """A single exact decision unlocks bounded policy issuance while retaining every human zero."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    status = service.get_fidelity_delegation_status(fix.contract.delegation_id)
    assert status["reserved"] == fix.asset.slots[0].cost().model_dump()
    assert status["reserved"]["closure_processes"] == 24
    assert status["scopes"][0]["is_user_approval"] is False
    assert status["human_beauty_accepted"] == status["human_package_accepted"] == 0
    assert status["human_activation_accepted"] is False
    assert reserve(fix) == binding
    assert len(list((service._directory(binding.delegation_id) / "scopes").glob("*.json"))) == 1


def test_unapproved_and_wrong_exact_decision_fail_closed(tmp_path, monkeypatch):
    """Generic consent or another hash cannot start the campaign or create a scope."""
    fix = fixture(tmp_path, monkeypatch, approve=False)
    with pytest.raises(FileNotFoundError):
        reserve(fix)
    with pytest.raises(PermissionError, match="exact delegation"):
        service.approve_fidelity_delegation(
            fix.contract.delegation_id, contract_sha256=fix.digest, exact_user_text="yes"
        )
    assert not (service._directory(fix.contract.delegation_id) / "decision.json").exists()


@pytest.mark.parametrize("mutation", ["structural", "local", "strategy", "aggregate", "human"])
def test_contract_rejects_expansion_or_human_aliases(tmp_path, monkeypatch, mutation):
    """Strict aggregate constraints prevent per-job quota reset and policy-to-human conversion."""
    fix = fixture(tmp_path, monkeypatch, approve=False)
    raw = fix.contract.model_dump(mode="json")
    slot = raw["assets"][0]["slots"][1]
    if mutation == "structural":
        slot["structural_rounds"] = 2
    elif mutation == "local":
        slot["material_corrections"] = 2
    elif mutation == "strategy":
        slot["strategy_switches"] = 1
    elif mutation == "aggregate":
        raw["total_budget"]["aq_builds"] += 1
    else:
        raw["human_package_acceptance"] = True
    with pytest.raises(ValueError):
        FidelityCampaignDelegationV01.model_validate_json(json.dumps(raw))


def test_preparation_costs_freeze_and_require_bounded_data(tmp_path, monkeypatch):
    """The initial set plus two repairs exhaust their own finite pre-admission allowance."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    for index in range(3):
        prepare(binding, index)
    with pytest.raises(PermissionError, match="repair allowance exhausted"):
        service.publish_fidelity_preparation(binding, [])
    assert len(service._preparations(binding)) == 3


def test_native_admission_requires_preparation_and_cannot_be_renamed(tmp_path, monkeypatch):
    """Direct native planning cannot bypass a governed reference by omitting the parent binding."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    with pytest.raises(PermissionError, match="preparation"):
        admit(fix, binding)
    with pytest.raises(PermissionError, match="no unbound reset"):
        plan_autonomous_static_prop_v2(
            "Rename and reset",
            reference_path=fix.reference,
            target_subject="fixture",
            requested_delivery_profiles=["portable_gltf"],
            job_id="unbound_renamed",
            allow_disabled_experimental=True,
        )
    assert not (fix.root / "unbound_renamed").exists()
    prepare(binding)
    result = admit(fix, binding)
    budget = _session_bundle(str(result["job_id"]), str(result["session_id"]))[3]
    assert isinstance(budget, AutonomyBudgetV04)
    assert parse_autonomy_budget(budget.model_dump_json()) == budget
    assert (
        _load_approval_boundary(str(result["job_id"]), str(result["session_id"]))[8].approval_mode
        == "autonomous"
    )
    with pytest.raises(PermissionError, match="already started"):
        admit(fix, binding)
    with pytest.raises(PermissionError, match="admitted preparation"):
        service.publish_fidelity_preparation(binding, [])


def test_crash_after_native_plan_preserves_reserve_and_returns_same_session(tmp_path, monkeypatch):
    """A missing outer start receipt cannot replan, recharge or consume a second candidate."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    prepare(binding)
    first = admit(fix, binding)
    resumed = service.start_fidelity_scope(binding)
    assert resumed["status"] == "existing_session"
    assert resumed["session_id"] == first["session_id"]
    assert resumed["new_reservation"] is False
    assert (
        service.get_fidelity_delegation_status(fix.contract.delegation_id)["reserved"]["candidates"]
        == 1
    )
    with pytest.raises(PermissionError, match="closure"):
        reserve(fix, job="next_candidate")


@pytest.mark.parametrize("mutation", ["source", "scope", "preparation", "decision"])
def test_native_resume_revalidates_exact_parent_before_effects(tmp_path, monkeypatch, mutation):
    """Reject stale source and changed parent evidence in native session and policy validation."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    prepare(binding)
    result = admit(fix, binding)
    if mutation == "source":

        def stale(_contract):
            """Simulate a changed source checkpoint independently of the native policy path."""
            raise PermissionError("delegation source/baseline is stale")

        monkeypatch.setattr(service, "_validate_source", stale)
    else:
        directory = service._directory(binding.delegation_id)
        path = {
            "scope": directory / "scopes/0001.json",
            "decision": directory / "decision.json",
            "preparation": directory / "staging/0001/0000/data.json",
        }[mutation]
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, PermissionError)):
        _session_bundle(str(result["job_id"]), str(result["session_id"]))
    with pytest.raises((ValueError, PermissionError)):
        _load_approval_boundary(str(result["job_id"]), str(result["session_id"]))


def test_cancelled_scope_closes_without_success_and_never_refunds(tmp_path, monkeypatch):
    """Terminal nonpass stays nonpass; only the unused exact slot can be issued afterward."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    prepare(binding)
    result = admit(fix, binding)
    cancel_autonomy_v2(
        str(result["job_id"]), str(result["session_id"]), reason="fixture cancellation"
    )
    outcome = service.close_fidelity_scope(binding, session_id=str(result["session_id"]))
    assert outcome["technical_passed"] is False and outcome["visual_passed"] is False
    second = reserve(fix, job="second_candidate")
    assert second.scope_sequence == 2
    status = service.get_fidelity_delegation_status(fix.contract.delegation_id)
    assert status["reserved"] == fix.contract.total_budget.model_dump()
    assert (
        service.delegated_switch_offset(
            _session_bundle(str(result["job_id"]), str(result["session_id"]))[3]
        )
        == 0
    )


def test_guard_releases_after_exception_without_erasing_reservation(tmp_path, monkeypatch):
    """The OS lock permits resume after a crash while immutable reservations remain charged."""
    fix = fixture(tmp_path, monkeypatch)
    reserve(fix)
    with pytest.raises(RuntimeError, match="crash"):
        with service._guard():
            with pytest.raises(OSError):
                with service._guard():
                    pytest.fail("duplicate campaign writer")
            raise RuntimeError("crash")
    with service._guard():
        assert (
            service.get_fidelity_delegation_status(fix.contract.delegation_id)["reserved"][
                "candidates"
            ]
            == 1
        )


def test_no_contract_or_scope_can_launder_unknown_versions(tmp_path, monkeypatch):
    """Select V0.4 explicitly; preserve V0.3 and reject unknown versions."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    prepare(binding)
    result = admit(fix, binding)
    budget = _session_bundle(str(result["job_id"]), str(result["session_id"]))[3]
    raw = budget.model_dump(mode="json")
    raw["schema_version"] = "0.5.0"
    with pytest.raises(ValueError, match="unsupported"):
        parse_autonomy_budget(raw)
    raw["schema_version"] = "0.3.0"
    with pytest.raises(ValueError):
        parse_autonomy_budget(raw)


def test_pricing_is_not_quality_evidence():
    """A fully priced two-slot reserve has no acceptance fields or qualitative success proxy."""
    first = DelegationSlot(
        initial_object_limit=17,
        correction_object_limit=17,
        structural_rounds=2,
        parametric_rounds=0,
        material_corrections=2,
        strategy_switches=1,
    )
    second = DelegationSlot(
        initial_object_limit=17,
        correction_object_limit=17,
        structural_rounds=1,
        parametric_rounds=0,
        material_corrections=0,
        strategy_switches=0,
    )
    total = first.cost().plus(second.cost())
    assert total.aq_builds == 104 and total.closure_processes == 42
    assert total.structural == 3 and total.local == 2 and total.candidates == 2
    assert not any("accepted" in key for key in DelegationCost.model_fields)


def test_unlocked_nonterminal_history_is_preserved_without_reclassification(tmp_path, monkeypatch):
    """Freeze a real legacy unfinished session; never cancel it merely to admit a new mandate."""
    fix = fixture(tmp_path, monkeypatch, approve=False)
    legacy = plan_autonomous_static_prop_v2(
        "Legacy fixture request", reference_path=fix.reference,
        target_subject="fixture shape", requested_delivery_profiles=["review_only"],
        job_id="inherited_unfinished",
        allow_disabled_experimental=True,
    )
    history = service.read_fidelity_history(fix.asset.reference.sha256)
    assert len(history) == 1 and history[0].next_action != "none"
    session = (
        fix.root / str(legacy["job_id"]) / "production/autonomy_v2" / str(legacy["session_id"])
    )
    original = {p.name: p.read_bytes() for p in (session / "states").glob("*.json")}
    asset = fix.asset.model_copy(update={"prior_history": history})
    contract = fix.contract.model_copy(update={
        "delegation_id": "preserve-unfinished", "assets": [asset],
    })
    planned = service.plan_fidelity_delegation(contract)
    digest = planned["artifact"]["sha256"]
    service.approve_fidelity_delegation(
        contract.delegation_id, contract_sha256=digest,
        exact_user_text=f"Synthetic preservation fixture {digest}",
    )
    assert {p.name: p.read_bytes() for p in (session / "states").glob("*.json")} == original
    assert service.read_fidelity_history(fix.asset.reference.sha256) == history
    lock = session / "autonomy.lock"
    lock.write_text("Fixture active or unknown owner; no recovery authority", encoding="utf-8")
    with pytest.raises(PermissionError, match="execution lock"):
        service.issue_fidelity_scope(
            contract.delegation_id, asset_id=asset.asset_id,
            job_id="forbidden_while_old_writer_exists", strategy="solid_sections",
        )
    assert lock.is_file()
    assert {p.name: p.read_bytes() for p in (session / "states").glob("*.json")} == original


@pytest.mark.parametrize("same_defect", [True, False])
def test_stagnation_spans_closed_candidate_and_successor(tmp_path, monkeypatch, same_defect):
    """The last closed observation plus a new initial observation cannot evade the two-hit rule."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    prepare(first)
    started = admit(fix, first)
    cancel_autonomy_v2(
        str(started["job_id"]), str(started["session_id"]), reason="fixture terminal"
    )
    service.close_fidelity_scope(first, session_id=str(started["session_id"]))
    second = reserve(fix, job="successor_fixture")
    prepare(second)
    next_session = admit(fix, second)
    budget = _session_bundle(str(next_session["job_id"]), str(next_session["session_id"]))[3]
    older = SimpleNamespace(
        strategy="solid_sections", next_action="structural_reentry", unresolved_features=["cap"]
    )
    current = SimpleNamespace(
        strategy="solid_sections", next_action="structural_reentry",
        unresolved_features=["cap" if same_defect else "grain"],
    )
    visited = []

    def previous_attempts(scope):
        """Supply a synthetic visual observation at the otherwise real native session boundary."""
        visited.append(scope.sequence)
        return [older]

    monkeypatch.setattr(service, "_verified_scope_attempts", previous_attempts)
    assert service.delegated_attempt_history(budget, [current]) == [older, current]
    assert visited == [1]
    if same_defect:
        with pytest.raises(PermissionError, match="stagnated twice"):
            service.validate_delegated_strategy(
                budget, [current], strategy="solid_sections", reserved_switches=0
            )
    else:
        service.validate_delegated_strategy(
            budget, [current], strategy="solid_sections", reserved_switches=0
        )


def test_cancelled_outcome_cannot_be_forged_into_canary_success(tmp_path, monkeypatch):
    """A tampered success flag is recomputed against the real immutable native terminal."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    prepare(binding)
    result = admit(fix, binding)
    cancel_autonomy_v2(str(result["job_id"]), str(result["session_id"]), reason="canary failed")
    service.close_fidelity_scope(binding, session_id=str(result["session_id"]))
    path = service._directory(binding.delegation_id) / "outcomes/0001.json"
    raw = json.loads(path.read_bytes())
    raw["technical_passed"] = True
    raw["visual_passed"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="host-recomputed"):
        service.get_fidelity_delegation_status(binding.delegation_id)
    with pytest.raises(ValueError, match="host-recomputed"):
        reserve(fix, job="forged_canary_successor")


def test_expired_parent_is_readable_but_cannot_issue_or_resume(tmp_path, monkeypatch):
    """Time expiration retains historical records without supplying fresh execution authority."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    real_datetime = datetime

    class FutureClock:
        """Advance only the service clock; immutable expiry bytes are never rewritten."""

        @staticmethod
        def now(tz):
            """Observe a time after the original contract expiry."""
            return real_datetime.now(tz) + timedelta(days=3)

    monkeypatch.setattr(service, "datetime", FutureClock)
    assert service.get_fidelity_delegation_status(binding.delegation_id)["expired"] is True
    with pytest.raises(PermissionError, match="expired"):
        reserve(fix, job="expired_successor")
    with pytest.raises(PermissionError, match="expired"):
        service.start_fidelity_scope(binding)


def test_bound_loop_preserves_criteria_and_all_native_budget_paths(tmp_path, monkeypatch):
    """Bind a V0.4 loop and enforce frozen criteria plus native controller fingerprints."""
    from test_fidelity_budget_epoch import funded_loop

    from codex_blender_modeler.autonomy_v2.controller_bridge import _validate_controller_authority
    from codex_blender_modeler.autonomy_v2.material_phase_service import _validate_budget_binding
    from codex_blender_modeler.autonomy_v2.quality_revision_models import (
        parse_quality_revision_loop,
    )
    from codex_blender_modeler.autonomy_v2.quality_revision_service import (
        bind_quality_revision_loop,
    )
    from codex_blender_modeler.comparison_lighting import (
        CAMERA_STUDIO_PROFILE,
        lighting_implementation_sha256,
    )
    from codex_blender_modeler.reference_fidelity.models import FidelityArtifact
    from codex_blender_modeler.reference_fidelity.service import publish

    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    prepare(binding)
    result = admit(fix, binding)
    job, session = str(result["job_id"]), str(result["session_id"])
    root, _session, plan, budget, _state, state_ref = _session_bundle(job, session)
    envelope = _load_approval_boundary(job, session)
    template = service._validate_asset_evidence(fix.asset)
    selected = template.model_copy(
        update={
            "job_id": job,
            "authoring_strategy": "solid_sections",
            "reference": FidelityArtifact(
                path=envelope[2].primary_reference.path, sha256=envelope[2].primary_reference.sha256
            ),
        }
    )
    hyp = publish(root, root / "fidelity/hypothesis.json", selected)
    loop_raw = funded_loop(budget.funding).model_dump(mode="json")
    loop_raw.update(
        {
            "schema_version": "0.4.0",
            "job_id": job,
            "session_id": session,
            "hypothesis": hyp.model_dump(mode="json"),
            "root_authorization": {
                "path": plan.root_authorization.path,
                "sha256": plan.root_authorization.sha256,
            },
            "approval_envelope": {"path": envelope[9].path, "sha256": envelope[9].sha256},
            "initial_state": {"path": state_ref.path, "sha256": state_ref.sha256},
            "comparison_lighting_profile": CAMERA_STUDIO_PROFILE,
            "lighting_implementation_sha256": lighting_implementation_sha256(),
        }
    )
    loop = parse_quality_revision_loop(json.dumps(loop_raw))
    proposal = root / "fidelity/proposal.json"
    publish(root, proposal, loop)
    bind_quality_revision_loop(job, session, proposal)
    _validate_controller_authority(root, plan, budget)
    _validate_budget_binding(root, plan, budget)
    weakened = selected.model_copy(update={"requirements": selected.requirements[:-1]})
    with pytest.raises(PermissionError, match="frozen observations"):
        service.validate_delegated_budget(root, budget, loop=loop, hypothesis=weakened)
    with pytest.raises(PermissionError, match="strategy switch budget"):
        service.validate_delegated_strategy(budget, [], strategy="changed", reserved_switches=2)


def test_explicit_new_mandate_preserves_prior_reserved_capacity(tmp_path, monkeypatch):
    """A separately approved replacement preserves all old reservations."""
    fix = fixture(tmp_path, monkeypatch)
    first = reserve(fix)
    status = service.get_fidelity_delegation_status(first.delegation_id)
    from codex_blender_modeler.production.activation_models import ActivationArtifact

    next_contract = fix.contract.model_copy(
        update={
            "delegation_id": "successor-mandate",
            "supersedes": ActivationArtifact.model_validate(status["contract"]),
            "prior_delegated_reservations": DelegationCost.model_validate(status["reserved"]),
        }
    )
    with pytest.raises(ValueError, match="reset previously reserved"):
        service.plan_fidelity_delegation(
            next_contract.model_copy(
                update={
                    "prior_delegated_reservations": DelegationCost(),
                }
            )
        )
    proposal = service.plan_fidelity_delegation(next_contract)
    digest = proposal["artifact"]["sha256"]
    service.approve_fidelity_delegation(
        next_contract.delegation_id,
        contract_sha256=digest,
        exact_user_text=f"Approve new finite mandate {digest}",
    )
    with pytest.raises(PermissionError, match="superseded"):
        reserve(fix, job="reuse_old_mandate")
    assert (
        service.get_fidelity_delegation_status(first.delegation_id)["reserved"]
        == status["reserved"]
    )
    assert (
        service.get_fidelity_delegation_status(next_contract.delegation_id)[
            "prior_delegated_reservations"
        ]
        == status["reserved"]
    )


@pytest.mark.parametrize("change", ["clean", "dirty", "commit", "tree", "bytes"])
def test_source_guard_checks_actual_bytes_and_clean_checkpoint(tmp_path, monkeypatch, change):
    """Check source bytes and the clean checkpoint, with Git text EOL normalization."""
    import hashlib

    from codex_blender_modeler.production import activation_service

    fix = fixture(tmp_path, monkeypatch)
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    source = tmp_path / "source.py"
    source.write_bytes(b"# fixture\r\n")
    record = SimpleNamespace(path="source.py", sha256=hashlib.sha256(b"# fixture\n").hexdigest())
    manifest = SimpleNamespace(
        git_commit_sha="a" * 40, git_tree_sha="b" * 40, source_files=[record]
    )
    baseline = SimpleNamespace(source_manifest=fix.contract.source_manifest)
    checkpoint = {
        "working_tree_clean": True,
        "staged_tree_clean": True,
        "git_commit_sha": manifest.git_commit_sha,
        "git_tree_sha": manifest.git_tree_sha,
    }
    if change == "dirty":
        checkpoint["working_tree_clean"] = False
    elif change in {"commit", "tree"}:
        checkpoint[f"git_{change}_sha"] = "c" * 40
    elif change == "bytes":
        source.write_bytes(b"# changed fixture\r\n")
    monkeypatch.setattr(activation_service, "load_activation_source_manifest", lambda *_a: manifest)
    monkeypatch.setattr(activation_service, "load_activation_baseline", lambda *_a: baseline)
    monkeypatch.setattr(
        activation_service, "inspect_activation_source_checkpoint", lambda *_a: checkpoint
    )
    if change == "clean":
        SOURCE_VALIDATOR(fix.contract)
    else:
        with pytest.raises((ValueError, PermissionError)):
            SOURCE_VALIDATOR(fix.contract)


def test_stale_parent_can_cancel_safely_but_cannot_run(tmp_path, monkeypatch):
    """Cancelling appends a terminal without granting execution authority from a stale parent."""
    fix = fixture(tmp_path, monkeypatch)
    binding = reserve(fix)
    prepare(binding)
    result = admit(fix, binding)

    def stale(_contract):
        """Represent a changed code checkpoint while keeping every session file intact."""
        raise PermissionError("source changed")

    monkeypatch.setattr(service, "_validate_source", stale)
    cancelled = cancel_autonomy_v2(
        str(result["job_id"]),
        str(result["session_id"]),
        reason="source changed; preserve immutable evidence",
    )
    assert cancelled["state"]["status"] == "cancelled"
    assert (
        service.get_fidelity_delegation_status(binding.delegation_id)["reserved"]["candidates"] == 1
    )
