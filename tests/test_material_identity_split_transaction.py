"""Authority, single-use, lock-order, and recovery seams for identity split 0.1.0."""

from __future__ import annotations

import hashlib
import inspect
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.material_closure.models import ExactArtifact
from codex_blender_modeler.material_identity_split import transaction
from codex_blender_modeler.material_identity_split.models import (
    MaterialIdentitySplitApplyIntent,
    MaterialIdentitySplitCanonicalPreconditions,
    MaterialIdentitySplitPolicyApplyIntent,
    MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)


@contextmanager
def _held_lock(*_args: object, **_kwargs: object):
    """Stand in for the canonical host lock in sequencing-only transaction tests."""

    yield


def _artifact(artifact_id: str, path: str, kind: str, sha: str = "a" * 64) -> ExactArtifact:
    """Build one exact synthetic artifact envelope for a transaction fixture."""

    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=path,
        sha256=sha,
        byte_size=10,
        media_type="application/json",
    )


def _preconditions() -> MaterialIdentitySplitCanonicalPreconditions:
    """Build canonical path-bound preconditions without touching canonical files."""

    return MaterialIdentitySplitCanonicalPreconditions(
        scene_spec=_artifact("scene", "analysis/scene_spec.json", "scene_spec"),
        modeling_plan=_artifact(
            "modeling", "analysis/modeling_plan.json", "modeling_plan", "b" * 64
        ),
        blend=_artifact("blend", "blender/scene.blend", "canonical_blend", "c" * 64),
        material_plan_absence=_artifact(
            "absence",
            "production/material_repair/session/material_plan_absence.json",
            "material_plan_absence",
        ),
        root_authorization=_artifact(
            "authority",
            "production/autonomy_v2/session/root_authorization.json",
            "root_authorization",
        ),
        primary_reference=_artifact("reference", "input/reference.png", "primary_reference"),
        content_scope_sha256="d" * 64,
        target_subject="bounded fixture prop",
        uv_layout_fingerprint="e" * 64,
    )


def _intent(*, intent_id: str = "intent-1") -> MaterialIdentitySplitApplyIntent:
    """Build one strict caller-authored intent for publication-boundary tests."""

    candidate_scene = _artifact(
        "candidate-scene",
        "production/material_identity_split/run-1/planning/candidate_scene.json",
        "candidate_scene_spec",
        "1" * 64,
    )
    candidate_modeling = _artifact(
        "candidate-modeling",
        "production/material_identity_split/run-1/planning/candidate_modeling.json",
        "candidate_modeling_plan",
        "2" * 64,
    )
    return MaterialIdentitySplitApplyIntent(
        job_id="fixture_job",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        run_id="run-1",
        producer="caller_fixture",
        producer_version="0.1.0",
        created_at=NOW,
        intent_id=intent_id,
        transaction_id="run-1",
        approval=_artifact(
            "approval-1",
            "production/material_identity_split/run-1/approvals/approval-1.json",
            "material_identity_split_root_scope_approval",
        ),
        approval_request=_artifact(
            "request-1",
            "production/material_identity_split/run-1/approval_request.json",
            "material_identity_split_approval_request",
        ),
        plan=_artifact(
            "plan-1",
            "production/material_identity_split/run-1/plan.json",
            "material_identity_split_plan",
        ),
        candidate_scene_spec=candidate_scene,
        candidate_modeling_plan=candidate_modeling,
        scene_diff_allowlist=_artifact(
            "scene-diff",
            "history/material_identity_split_plans/plan/exact_diff_allowlist.json",
            "material_identity_split_scene_diff_allowlist",
        ),
        modeling_plan_diff_report=_artifact(
            "modeling-diff",
            "production/material_identity_split/run-1/planning/modeling_plan_diff_report.json",
            "material_identity_split_modeling_plan_diff_report",
        ),
        preapproval_report=_artifact(
            "preapproval",
            "production/material_identity_split/run-1/preapproval/report.json",
            "material_identity_split_preapproval_report",
        ),
        shadow_build_receipt=_artifact(
            "shadow",
            "production/material_identity_split/run-1/preapproval/shadow_build_receipt.json",
            "material_identity_split_shadow_build_receipt",
        ),
        invariant_report=_artifact(
            "invariant",
            "production/material_identity_split/run-1/preapproval/invariant_report.json",
            "material_identity_split_invariant_report",
        ),
        preconditions=_preconditions(),
        expected_scene_spec_sha256=candidate_scene.sha256,
        expected_modeling_plan_sha256=candidate_modeling.sha256,
        expected_material_assignment_sha256="3" * 64,
    )


def _policy_intent(
    *, intent_id: str = "policy-intent-1"
) -> MaterialIdentitySplitPolicyApplyIntent:
    """Build one strict non-user policy intent for separated consumption tests."""

    explicit = _intent(intent_id=intent_id)
    payload = explicit.model_dump()
    payload.pop("approval")
    payload.update(
        {
            "schema_version": "0.3.0",
            "session_id": "session-1",
            "producer_version": "0.3.0",
            "policy_authorization": _artifact(
                "policy-auth-1",
                "production/autonomy_v2/session-1/policy_authorizations/policy-auth-1.json",
                "aq_v2_routine_policy_authorization",
                "4" * 64,
            ),
        }
    )
    return MaterialIdentitySplitPolicyApplyIntent.model_validate(payload)


def _binding_chain(
    intent: MaterialIdentitySplitApplyIntent,
) -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    """Build one exact synthetic plan/request/approval chain for replay tests."""

    plan = SimpleNamespace(
        run_id=intent.run_id,
        candidate_scene_spec=intent.candidate_scene_spec,
        candidate_modeling_plan=intent.candidate_modeling_plan,
        scene_diff_allowlist=intent.scene_diff_allowlist,
        preconditions=intent.preconditions,
    )
    request = SimpleNamespace(
        job_id=intent.job_id,
        workflow_id=intent.workflow_id,
        dispatch_id=intent.dispatch_id,
        run_id=intent.run_id,
        plan=intent.plan,
        candidate_scene_spec=intent.candidate_scene_spec,
        candidate_modeling_plan=intent.candidate_modeling_plan,
        scene_diff_allowlist=intent.scene_diff_allowlist,
        modeling_plan_diff_report=intent.modeling_plan_diff_report,
        preapproval_report=intent.preapproval_report,
        shadow_build_receipt=intent.shadow_build_receipt,
        invariant_report=intent.invariant_report,
        preconditions=intent.preconditions,
    )
    approval = SimpleNamespace(
        job_id=intent.job_id,
        workflow_id=intent.workflow_id,
        dispatch_id=intent.dispatch_id,
        run_id=intent.run_id,
        decision="approved",
        approval_request=intent.approval_request,
        candidate_scene_spec=intent.candidate_scene_spec,
        candidate_modeling_plan=intent.candidate_modeling_plan,
        scene_diff_allowlist=intent.scene_diff_allowlist,
        modeling_plan_diff_report=intent.modeling_plan_diff_report,
        preapproval_report=intent.preapproval_report,
        shadow_build_receipt=intent.shadow_build_receipt,
        invariant_report=intent.invariant_report,
        preconditions=intent.preconditions,
    )
    return plan, request, approval


def test_single_approval_exact_adopts_one_intent_and_rejects_another(tmp_path: Path) -> None:
    """Allow exact replay but reject a second substantive intent for one approval."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    first_intent, first_consumption = transaction._publish_intent_and_consumption(
        root, _intent()
    )
    replay_intent, replay_consumption = transaction._publish_intent_and_consumption(
        root, _intent()
    )
    assert replay_intent == first_intent
    assert replay_consumption == first_consumption
    with pytest.raises(PermissionError, match="another ApplyIntent"):
        transaction._publish_intent_and_consumption(root, _intent(intent_id="intent-2"))


def test_single_policy_authorization_is_separate_non_user_and_single_use(
    tmp_path: Path,
) -> None:
    """Keep policy consumption non-user and reject authorization rebinding."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    first_intent, first_consumption = transaction._publish_intent_and_consumption(
        root, _policy_intent()
    )
    replay_intent, replay_consumption = transaction._publish_intent_and_consumption(
        root, _policy_intent()
    )

    assert replay_intent == first_intent
    assert replay_consumption == first_consumption
    receipt_path = root / first_consumption.path
    receipt = MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt.model_validate_json(
        receipt_path.read_bytes()
    )
    assert receipt.policy_authorization == _policy_intent().policy_authorization
    assert receipt.is_user_approval is False
    assert receipt.approved_by_user is False
    assert receipt.user_approval_created is False
    with pytest.raises(PermissionError, match="another ApplyIntent"):
        transaction._publish_intent_and_consumption(
            root, _policy_intent(intent_id="policy-intent-2")
        )


def test_apply_rejects_wrong_boundary_before_consuming_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check the status before writing an intent or consumption receipt."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    intent = _intent()
    plan = SimpleNamespace(run_id="run-1", job_id="fixture_job")
    request = SimpleNamespace(plan=intent.plan)
    approval = SimpleNamespace(decision="approved")
    monkeypatch.setattr(
        transaction,
        "_validate_apply_bindings",
        lambda *_args, **_kwargs: (plan, request, approval),
    )
    monkeypatch.setattr(
        transaction.MaterialIdentitySplitService,
        "get_status",
        lambda *_args, **_kwargs: SimpleNamespace(status="planned"),
    )
    with pytest.raises(PermissionError, match="approval boundary"):
        transaction.apply_material_identity_split(
            root,
            intent=intent,
            canonical_scene_inventory=_artifact(
                "inventory", "reports/scene_inventory.json", "scene_inventory"
            ),
        )
    assert not (root / "production" / "material_identity_split" / "run-1" / "intents").exists()
    assert not (
        root
        / "production"
        / "material_identity_split"
        / "run-1"
        / "approval_consumptions"
    ).exists()


def test_rejected_specialized_decision_cannot_enter_apply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject an exact specialized rejection before any candidate binding is used."""

    values = iter(
        (
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(decision="rejected"),
        )
    )
    monkeypatch.setattr(
        transaction,
        "load_material_closure_model",
        lambda *_args, **_kwargs: next(values),
    )
    with pytest.raises(PermissionError, match="rejected"):
        transaction._validate_apply_bindings(tmp_path, _intent())


def test_apply_binding_replay_rejects_a_spliced_specialized_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a strict approval whose exact candidate differs from its request chain."""

    intent = _intent()
    plan, request, approval = _binding_chain(intent)
    approval.candidate_scene_spec = _artifact(
        "other-scene",
        "production/material_identity_split/run-1/planning/other-scene.json",
        "candidate_scene_spec",
        "9" * 64,
    )
    values = iter((plan, request, approval))
    monkeypatch.setattr(
        transaction,
        "load_material_closure_model",
        lambda *_args, **_kwargs: next(values),
    )
    with pytest.raises(PermissionError, match="exact-bound"):
        transaction._validate_apply_bindings(tmp_path, intent)


def test_recovery_replays_authority_without_requiring_precrash_canonical_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Let exact recovery load its authority after a journaled canonical replacement."""

    intent = _intent()
    plan, request, approval = _binding_chain(intent)
    values = iter((plan, request, approval))
    currentness_calls: list[object] = []
    monkeypatch.setattr(
        transaction,
        "load_material_closure_model",
        lambda *_args, **_kwargs: next(values),
    )
    monkeypatch.setattr(
        transaction.MaterialIdentitySplitService,
        "validate_plan_current",
        lambda _self, value: currentness_calls.append(value),
    )
    observed = transaction._validate_apply_bindings(
        tmp_path,
        intent,
        require_current_preconditions=False,
    )
    assert observed == (plan, request, approval)
    assert currentness_calls == []


def test_recovery_allows_only_one_exact_technical_reattempt(tmp_path: Path) -> None:
    """Bound recovery_required replay to one host-technical retry without new approval."""

    root = tmp_path / "fixture_job"
    root.mkdir()
    first = SimpleNamespace(state="recovery_required", technical_retry_count=0)
    exhausted = SimpleNamespace(state="recovery_required", technical_retry_count=1)
    assert transaction._recovery_retry_count(root, "run-1", first) == 1
    with pytest.raises(PermissionError, match="retry is exhausted"):
        transaction._recovery_retry_count(root, "run-1", exhausted)


def _install_apply_harness(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> tuple[MaterialIdentitySplitApplyIntent, list[str], list[str]]:
    """Install one deterministic host-only apply harness for commit and crash tests."""

    (root / "analysis").mkdir(parents=True)
    (root / "blender").mkdir()
    intent = _intent()
    preconditions = intent.preconditions
    plan = SimpleNamespace(
        job_id=intent.job_id,
        workflow_id=intent.workflow_id,
        dispatch_id=intent.dispatch_id,
        run_id=intent.run_id,
        producer="fixture",
        producer_version="0.1.0",
        created_at=NOW,
        preconditions=preconditions,
        candidate_scene_spec=intent.candidate_scene_spec,
        candidate_modeling_plan=intent.candidate_modeling_plan,
    )
    request = SimpleNamespace(plan=intent.plan, invariant_report=intent.invariant_report)
    ready = SimpleNamespace(
        status="eligible_for_explicit_user_scope_approval",
        latest_sequence=2,
        latest_state=_artifact(
            "state-2",
            "production/material_identity_split/run-1/states/0002.json",
            "material_identity_split_transaction_state",
        ),
    )
    consumption_calls: list[str] = []
    states: list[str] = []
    archives = [
        _artifact("archive-scene", "archive/scene.json", "archived_scene_spec", "a" * 64),
        _artifact(
            "archive-modeling",
            "archive/modeling.json",
            "archived_modeling_plan",
            "b" * 64,
        ),
        _artifact("archive-blend", "archive/scene.blend", "archived_blend", "c" * 64),
    ]

    def publish_state(*_args: object, **kwargs: object) -> ExactArtifact:
        """Record one append-only state and return its exact synthetic envelope."""

        state = str(kwargs["state"])
        states.append(state)
        return _artifact(
            f"state-{len(states) + 2}",
            f"production/material_identity_split/run-1/states/{len(states) + 2:04d}.json",
            "material_identity_split_transaction_state",
        )

    def publish_consumption(
        *_args: object,
        **_kwargs: object,
    ) -> tuple[ExactArtifact, ExactArtifact]:
        """Record exactly one caller-authored intent and approval consumption."""

        consumption_calls.append("consumed")
        return (
            _artifact("intent-1", "intents/intent-1.json", "material_identity_split_apply_intent"),
            _artifact(
                "consumption-1",
                "approval_consumptions/0001.json",
                "material_identity_split_approval_consumption_receipt",
            ),
        )

    def artifact_from_path(
        _root: Path,
        relative: str,
        *,
        artifact_id: str,
        kind: str,
        media_type: str = "application/json",
    ) -> ExactArtifact:
        """Return the expected post-apply artifact hashes for receipt construction."""

        sha = {
            "analysis/scene_spec.json": intent.expected_scene_spec_sha256,
            "analysis/modeling_plan.json": intent.expected_modeling_plan_sha256,
            "blender/scene.blend": "f" * 64,
        }[relative]
        return ExactArtifact(
            artifact_id=artifact_id,
            kind=kind,
            path=relative,
            sha256=sha,
            byte_size=10,
            media_type=media_type,
        )

    refresh_artifacts = {
        "geometry_continuation": _artifact(
            "continuation",
            "production/material_identity_split/run-1/post_apply/geometry_continuation.json",
            "material_identity_split_geometry_continuation_receipt",
        ),
        "canonical_scene_inventory": _artifact(
            "inventory-new",
            "production/material_identity_split/run-1/post_apply/scene_inventory.json",
            "scene_inventory",
        ),
        "canonical_build_provenance": _artifact(
            "build-new",
            "production/material_identity_split/run-1/post_apply/build_provenance.json",
            "build_provenance",
        ),
        "material_plan_absence": _artifact(
            "absence-new",
            "production/material_identity_split/run-1/post_apply/material_plan_absence.json",
            "material_plan_absence",
        ),
        "canonical_snapshot": _artifact(
            "snapshot-new",
            "production/material_identity_split/run-1/post_apply/canonical_snapshot.json",
            "material_canonical_snapshot",
        ),
    }
    monkeypatch.setattr(
        transaction,
        "_validate_apply_bindings",
        lambda *_args, **_kwargs: (plan, request, SimpleNamespace(decision="approved")),
    )
    monkeypatch.setattr(
        transaction.MaterialIdentitySplitService,
        "get_status",
        lambda *_args, **_kwargs: ready,
    )
    monkeypatch.setattr(
        transaction.MaterialIdentitySplitService,
        "validate_plan_current",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(transaction, "canonical_scene_spec_write_lock", _held_lock)
    monkeypatch.setattr(transaction, "_publish_intent_and_consumption", publish_consumption)
    monkeypatch.setattr(transaction, "_publish_state", publish_state)
    monkeypatch.setattr(transaction, "_archive_canonical", lambda *_args: archives)
    monkeypatch.setattr(transaction, "validate_exact_artifact", lambda *_args: root / "input")
    monkeypatch.setattr(transaction, "_atomic_replace_exact", lambda *_args: None)
    monkeypatch.setattr(
        transaction,
        "_run_canonical_blender",
        lambda *_args: (
            root / "blender" / "scene.blend",
            root / "reports" / "scene_inventory.json",
            root / "reports" / "validation.json",
        ),
    )
    monkeypatch.setattr(transaction, "_validate_post_apply_inventory", lambda *_args: None)
    monkeypatch.setattr(transaction, "_artifact_from_path", artifact_from_path)
    monkeypatch.setattr(
        transaction,
        "_publish_model",
        lambda *_args, **kwargs: _artifact(
            str(kwargs["artifact_id"]),
            "production/material_identity_split/run-1/apply_receipt.json",
            str(kwargs["kind"]),
        ),
    )
    monkeypatch.setattr(
        transaction,
        "_publish_post_apply_authority_refresh",
        lambda *_args, **_kwargs: SimpleNamespace(**refresh_artifacts),
    )
    return intent, states, consumption_calls


@pytest.mark.parametrize(
    "crash_point",
    [
        "after_scene_spec",
        "after_modeling_plan",
        "after_blender_rebuild",
        "after_invariant_validation",
        "before_apply_receipt",
        "after_apply_receipt",
    ],
)
def test_apply_crash_points_preserve_one_consumption_and_append_only_progress(
    crash_point: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Inject every apply crash without synthesizing a second intent or consumption."""

    root = tmp_path / "fixture_job"
    intent, states, consumption_calls = _install_apply_harness(monkeypatch, root)
    with pytest.raises(RuntimeError, match="injected identity-split crash"):
        transaction.apply_material_identity_split(
            root,
            intent=intent,
            canonical_scene_inventory=_artifact(
                "inventory",
                "reports/scene_inventory.json",
                "scene_inventory",
            ),
            crash_after=crash_point,  # type: ignore[arg-type]
        )
    assert consumption_calls == ["consumed"]
    assert len(states) == len(set(states))


def test_guarded_paired_transaction_commits_once_without_broadening_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Complete one synthetic paired transaction with one intent and one consumption."""

    root = tmp_path / "fixture_job"
    intent, states, consumption_calls = _install_apply_harness(monkeypatch, root)
    result = transaction.apply_material_identity_split(
        root,
        intent=intent,
        canonical_scene_inventory=_artifact(
            "inventory",
            "reports/scene_inventory.json",
            "scene_inventory",
        ),
    )
    assert consumption_calls == ["consumed"]
    assert states == [
        "approval_consumed",
        "archives_written",
        "scene_spec_replaced",
        "modeling_plan_replaced",
        "blender_rebuilt",
        "invariants_verified",
        "committed",
    ]
    assert result.apply_receipt.kind == "material_identity_split_apply_receipt"
    assert result.geometry_continuation.kind == (
        "material_identity_split_geometry_continuation_receipt"
    )
    assert result.terminal_state.kind == "material_identity_split_transaction_state"


def _install_recovery_harness(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
) -> tuple[dict[str, bytes], list[str]]:
    """Install exact archives and a partial journal for rollback recovery tests."""

    originals = {
        "analysis/scene_spec.json": b'{"scene":"original"}\n',
        "analysis/modeling_plan.json": b'{"modeling":"original"}\n',
        "blender/scene.blend": b"original-blend-bytes",
    }
    changed = {
        "analysis/scene_spec.json": b'{"scene":"candidate"}\n',
        "analysis/modeling_plan.json": b'{"modeling":"candidate"}\n',
        "blender/scene.blend": b"candidate-blend-bytes",
    }

    def artifact_for_bytes(
        *,
        artifact_id: str,
        kind: str,
        relative: str,
        payload: bytes,
        media_type: str = "application/json",
    ) -> ExactArtifact:
        """Build one exact artifact envelope for known fixture bytes."""

        return ExactArtifact(
            artifact_id=artifact_id,
            kind=kind,
            path=relative,
            sha256=hashlib.sha256(payload).hexdigest(),
            byte_size=len(payload),
            media_type=media_type,
        )

    archive_paths = (
        "production/material_identity_split/run-1/archives/scene_spec.json",
        "production/material_identity_split/run-1/archives/modeling_plan.json",
        "production/material_identity_split/run-1/archives/scene.blend",
    )
    canonical_paths = tuple(originals)
    kinds = ("scene_spec", "modeling_plan", "canonical_blend")
    archive_kinds = ("archived_scene_spec", "archived_modeling_plan", "archived_blend")
    archives: list[ExactArtifact] = []
    canonical_artifacts: list[ExactArtifact] = []
    for index, (canonical, archive, kind, archive_kind) in enumerate(
        zip(canonical_paths, archive_paths, kinds, archive_kinds, strict=True),
        start=1,
    ):
        canonical_path = root.joinpath(*canonical.split("/"))
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        canonical_path.write_bytes(changed[canonical])
        archive_path = root.joinpath(*archive.split("/"))
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(originals[canonical])
        media_type = "application/x-blender" if canonical.endswith(".blend") else "application/json"
        canonical_artifacts.append(
            artifact_for_bytes(
                artifact_id=f"canonical-{index}",
                kind=kind,
                relative=canonical,
                payload=originals[canonical],
                media_type=media_type,
            )
        )
        archives.append(
            artifact_for_bytes(
                artifact_id=f"archive-{index}",
                kind=archive_kind,
                relative=archive,
                payload=originals[canonical],
                media_type=media_type,
            )
        )
    base = _preconditions()
    preconditions = MaterialIdentitySplitCanonicalPreconditions(
        scene_spec=canonical_artifacts[0],
        modeling_plan=canonical_artifacts[1],
        blend=canonical_artifacts[2],
        material_plan_absence=base.material_plan_absence,
        root_authorization=base.root_authorization,
        primary_reference=base.primary_reference,
        content_scope_sha256=base.content_scope_sha256,
        target_subject=base.target_subject,
        uv_layout_fingerprint=base.uv_layout_fingerprint,
    )
    intent = _intent().model_copy(update={"preconditions": preconditions})
    plan = SimpleNamespace(
        job_id=intent.job_id,
        workflow_id=intent.workflow_id,
        dispatch_id=intent.dispatch_id,
        run_id=intent.run_id,
        producer="fixture",
        producer_version="0.1.0",
        created_at=NOW,
        preconditions=preconditions,
    )
    request = SimpleNamespace(plan=intent.plan)
    intent_artifact = _artifact(
        "intent-1",
        "production/material_identity_split/run-1/intents/intent-1.json",
        "material_identity_split_apply_intent",
    )
    consumption = _artifact(
        "consumption-1",
        "production/material_identity_split/run-1/approval_consumptions/0001.json",
        "material_identity_split_approval_consumption_receipt",
    )
    latest_state = _artifact(
        "state-5",
        "production/material_identity_split/run-1/states/0005.json",
        "material_identity_split_transaction_state",
    )
    latest = SimpleNamespace(
        state="scene_spec_replaced",
        apply_intent=intent_artifact,
        approval_consumption=consumption,
        archives=archives,
        technical_retry_count=0,
    )
    status = SimpleNamespace(
        status="recovery_required",
        latest_sequence=5,
        latest_state=latest_state,
    )
    values = iter((latest, intent, latest, intent))
    states: list[str] = []

    def publish_state(*_args: object, **kwargs: object) -> ExactArtifact:
        """Record recovery progression without mutating the synthetic journal source."""

        state = str(kwargs["state"])
        states.append(state)
        return _artifact(
            f"recovery-state-{len(states)}",
            f"production/material_identity_split/run-1/states/recovery-{len(states):04d}.json",
            "material_identity_split_transaction_state",
        )

    def publish_model(
        _root: Path,
        relative: str,
        _model: object,
        *,
        artifact_id: str,
        kind: str,
    ) -> ExactArtifact:
        """Return one immutable recovery or rollback publication envelope."""

        return _artifact(artifact_id, relative, kind)

    monkeypatch.setattr(
        transaction,
        "load_material_closure_model",
        lambda *_args, **_kwargs: next(values),
    )
    monkeypatch.setattr(
        transaction,
        "_validate_apply_bindings",
        lambda *_args, **_kwargs: (plan, request, SimpleNamespace(decision="approved")),
    )
    monkeypatch.setattr(
        transaction.MaterialIdentitySplitService,
        "get_status",
        lambda *_args, **_kwargs: status,
    )
    monkeypatch.setattr(transaction, "_recovery_retry_count", lambda *_args: 1)
    monkeypatch.setattr(transaction, "canonical_scene_spec_write_lock", _held_lock)
    monkeypatch.setattr(transaction, "_publish_state", publish_state)
    monkeypatch.setattr(transaction, "_publish_model", publish_model)
    return originals, states


def test_rollback_crash_fails_closed_then_exact_retry_restores_all_archives(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Crash during rollback, publish recovery_required, then restore all exact bytes once."""

    root = tmp_path / "fixture_job"
    originals, states = _install_recovery_harness(monkeypatch, root)
    failed = transaction.recover_material_identity_split(
        root,
        run_id="run-1",
        crash_after="during_rollback",
        created_at=NOW,
    )
    assert failed.outcome == "recovery_required"
    assert failed.rollback_receipt is None
    assert states == ["rollback_started", "recovery_required"]
    assert (root / "analysis" / "scene_spec.json").read_bytes() == originals[
        "analysis/scene_spec.json"
    ]
    assert (root / "analysis" / "modeling_plan.json").read_bytes() != originals[
        "analysis/modeling_plan.json"
    ]

    recovered = transaction.recover_material_identity_split(
        root,
        run_id="run-1",
        created_at=NOW,
    )
    assert recovered.outcome == "rolled_back"
    assert recovered.rollback_receipt is not None
    assert states[-2:] == ["rollback_started", "rolled_back"]
    for relative, payload in originals.items():
        assert root.joinpath(*relative.split("/")).read_bytes() == payload


def test_post_apply_refresh_publishes_new_authority_without_material_promotion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Publish continuation, observations, strict absence, and snapshot after commit bytes."""

    root = tmp_path / "fixture_job"
    (root / "analysis").mkdir(parents=True)
    (root / "reports").mkdir()
    (root / "reports" / "scene_inventory.json").write_text(
        '{"job_id":"fixture_job","blender_version":"5.0.1","objects":[]}',
        encoding="utf-8",
    )
    post_scene = _artifact("post-scene", "analysis/scene_spec.json", "scene_spec", "1" * 64)
    post_modeling = _artifact(
        "post-modeling",
        "analysis/modeling_plan.json",
        "modeling_plan",
        "2" * 64,
    )
    post_blend = _artifact(
        "post-blend",
        "blender/scene.blend",
        "canonical_blend",
        "3" * 64,
    )
    plan = SimpleNamespace(
        job_id="fixture_job",
        workflow_id="workflow-1",
        dispatch_id="dispatch-1",
        run_id="run-1",
        preconditions=_preconditions(),
        scene_diff_allowlist=_intent().scene_diff_allowlist,
        current_material_closure=_artifact(
            "closure",
            "production/material_closure/session/closure.json",
            "material_dependency_closure",
        ),
    )
    request = SimpleNamespace(
        preapproval_report=_intent().preapproval_report,
        invariant_report=_intent().invariant_report,
    )
    apply_receipt = SimpleNamespace(
        apply_intent=_artifact(
            "intent-1",
            "production/material_identity_split/run-1/intents/intent-1.json",
            "material_identity_split_apply_intent",
        ),
        post_scene_spec=post_scene,
        post_modeling_plan=post_modeling,
        post_blend=post_blend,
    )
    loaded = iter(
        (
            apply_receipt,
            SimpleNamespace(request=_artifact("pre-request", "pre/request.json", "request")),
            SimpleNamespace(
                canonical_scene_inventory=_artifact(
                    "old-inventory",
                    "old.json",
                    "scene_inventory",
                )
            ),
            SimpleNamespace(status="passed"),
        )
    )
    publications: list[str] = []

    def publish_json(
        _root: Path,
        relative: str,
        _payload: object,
        *,
        artifact_id: str,
        kind: str,
    ) -> ExactArtifact:
        """Record one exact run-owned JSON observation publication."""

        publications.append(relative)
        return _artifact(artifact_id, relative, kind)

    def publish_model(
        _root: Path,
        relative: str,
        _model: object,
        *,
        artifact_id: str,
        kind: str,
    ) -> ExactArtifact:
        """Record one exact run-owned strict model publication."""

        publications.append(relative)
        return _artifact(artifact_id, relative, kind)

    monkeypatch.setattr(
        transaction,
        "load_material_closure_model",
        lambda *_args, **_kwargs: next(loaded),
    )
    monkeypatch.setattr(transaction, "validate_exact_artifact", lambda *_args: root)
    monkeypatch.setattr(transaction, "_publish_json_artifact", publish_json)
    monkeypatch.setattr(
        transaction,
        "collect_build_provenance",
        lambda *_args, **_kwargs: {"job_id": "fixture_job"},
    )
    monkeypatch.setattr(
        transaction,
        "build_material_plan_absence_evidence",
        lambda **_kwargs: SimpleNamespace(absence_id="post-absence"),
    )
    monkeypatch.setattr(
        transaction,
        "build_material_canonical_snapshot",
        lambda **_kwargs: SimpleNamespace(snapshot_id="post-snapshot"),
    )
    monkeypatch.setattr(transaction, "_publish_model", publish_model)
    monkeypatch.setattr(
        transaction,
        "_closure_role_artifact",
        lambda *_args, **_kwargs: _artifact(
            "old-geometry-validation",
            "production/geometry/receipt.json",
            "geometry_candidate_validation_receipt",
        ),
    )
    monkeypatch.setattr(
        transaction,
        "_previous_geometry_approval_artifact",
        lambda *_args, **_kwargs: _artifact(
            "old-geometry-approval",
            "production/geometry/approval.txt",
            "geometry_review_approval",
        ),
    )
    result = transaction._publish_post_apply_authority_refresh(
        root,
        plan=plan,
        request=request,
        apply_receipt_artifact=_artifact(
            "apply-receipt",
            "production/material_identity_split/run-1/apply_receipt.json",
            "material_identity_split_apply_receipt",
        ),
        created_at=NOW,
    )
    assert result.geometry_continuation.kind == (
        "material_identity_split_geometry_continuation_receipt"
    )
    assert publications == [
        "production/material_identity_split/run-1/post_apply/scene_inventory.json",
        "production/material_identity_split/run-1/post_apply/build_provenance.json",
        "production/material_identity_split/run-1/post_apply/material_plan_absence.json",
        "production/material_identity_split/run-1/post_apply/canonical_snapshot.json",
        "production/material_identity_split/run-1/post_apply/geometry_continuation_receipt.json",
    ]
    assert not (root / "analysis" / "material_plan.json").exists()


def test_host_lock_precedes_intent_consumption_and_canonical_archives() -> None:
    """Keep authority replay, consumption, archive, and writes under one host lock."""

    source = inspect.getsource(transaction.apply_material_identity_split)
    lock = source.index("with canonical_scene_spec_write_lock")
    consumption = source.index("_publish_intent_and_consumption")
    archive = source.index("_archive_canonical")
    replace = source.index("_atomic_replace_exact")
    assert lock < consumption < archive < replace


def test_user_decision_hash_is_exact_bytes_not_normalized_text() -> None:
    """Document that newline and byte changes produce distinct approval decision hashes."""

    first = hashlib.sha256(b"approved").hexdigest()
    second = hashlib.sha256(b"approved\n").hexdigest()
    assert first != second
