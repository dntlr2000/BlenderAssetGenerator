"""Exercise real host pair transactions using isolated, explicitly synthetic authority."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_revision_payload_binding import _approve, _complete, _fixture, _write

from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.orchestration import paired_revision as paired
from codex_blender_modeler.orchestration import service
from codex_blender_modeler.orchestration.locks import workflow_write_lock
from codex_blender_modeler.validation import load_scene_spec


def _paired(tmp_path, monkeypatch):
    """Select a bounded ModelPlan notes change in an ordinary manual fixture workflow."""

    root, _ = _fixture(tmp_path, monkeypatch, parametric=True)
    _write(root / "analysis/reference_analysis.json", {"test_only": True})
    _write(root / "analysis/camera_solution.json", {"test_only": True})
    model = json.loads((root / paired.MODEL_PATH).read_bytes())
    model["global_notes"] = ["Synthetic paired transaction fixture; never user acceptance."]
    candidate = root / "analysis/paired_candidate.json"
    _write(candidate, model)
    state = service.plan_workflow(
        "Revise fixture pair",
        job_id=root.name,
        intent="revise_asset",
        revision_strategy="manual_guarded",
        paired_modeling_plan_path="analysis/paired_candidate.json",
        paired_modeling_plan_sha256=sha256_file(candidate),
    )
    before = {path: (root / path).read_bytes() for path in (paired.SCENE_PATH, paired.MODEL_PATH)}
    state = _approve(root, _complete(root, state))
    return root, state, before


@pytest.mark.parametrize(
    "checkpoint",
    ["after_intent", "after_scene", "after_model", "after_validation", "before_receipt"],
)
def test_every_partial_apply_point_requires_exact_rollback(tmp_path, monkeypatch, checkpoint):
    """Every consumed but uncommitted crash remains blocked until hash-bound rollback."""

    root, state, before = _paired(tmp_path, monkeypatch)

    def fail(name):
        """Inject interruption only at the selected host boundary."""
        if name == checkpoint:
            raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(s.status for s in state.steps if s.step_id == "revision.apply") == "failed"
    for reader in (
        lambda: load_scene_spec(root / paired.SCENE_PATH),
        lambda: collect_build_provenance(root, root.name),
    ):
        with pytest.raises(ValueError, match="incomplete"):
            reader()
    monkeypatch.setattr(paired, "_checkpoint", lambda _name: None)
    intent = paired.transaction_path(root, state.workflow_id, "intent.json")
    with pytest.raises(ValueError, match="hash"):
        service.recover_paired_workflow_revision(
            root.name, state.workflow_id, intent_sha256="0" * 64
        )
    result = service.recover_paired_workflow_revision(
        root.name, state.workflow_id, intent_sha256=sha256_file(intent)
    )
    assert result["status"] == "rolled_back"
    assert all((root / path).read_bytes() == content for path, content in before.items())
    with pytest.raises(FileExistsError):
        service.recover_paired_workflow_revision(
            root.name, state.workflow_id, intent_sha256=sha256_file(intent)
        )
    with workflow_write_lock(root, root.name, state.workflow_id):
        with pytest.raises(FileExistsError, match="replay"):
            paired.apply_pair(root, state.workflow_id, {}, {})


def test_crash_after_receipt_finishes_host_evidence_without_reapplying(tmp_path, monkeypatch):
    """An exact committed pair can finalize lost host receipts without a second promotion."""

    root, state, _before = _paired(tmp_path, monkeypatch)

    def fail(name):
        """Interrupt after the canonical commit receipt has been published."""
        if name == "after_receipt":
            raise RuntimeError("synthetic postcommit interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    canonical = {
        path: (root / path).read_bytes() for path in (paired.SCENE_PATH, paired.MODEL_PATH)
    }
    intent = paired.transaction_path(root, state.workflow_id, "intent.json")
    monkeypatch.setattr(
        paired, "_cas", lambda *args: pytest.fail("finalization reapplied canonical state")
    )
    result = service.recover_paired_workflow_revision(
        root.name, state.workflow_id, intent_sha256=sha256_file(intent)
    )
    assert result["status"] == "committed_finalized"
    assert all((root / path).read_bytes() == content for path, content in canonical.items())
    checked = service.reconcile_workflow(root.name, state.workflow_id)
    assert next(s.status for s in checked.steps if s.step_id == "revision.apply") == "complete"
    assert checked.current_step_id == "revision.build"
    with pytest.raises(FileExistsError):
        service.recover_paired_workflow_revision(
            root.name, state.workflow_id, intent_sha256=sha256_file(intent)
        )


@pytest.mark.parametrize(
    "checkpoint", ["recovery_started", "recovery_after_scene", "recovery_after_model"]
)
def test_interrupted_rollback_is_resumable_without_replacing_edits(
    tmp_path, monkeypatch, checkpoint
):
    """Rollback crash states can resume safely from either exact transaction-owned hash."""

    root, state, before = _paired(tmp_path, monkeypatch)

    def fail_apply(name):
        """Leave both promoted files without a terminal receipt."""
        if name == "after_model":
            raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail_apply)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    intent = paired.transaction_path(root, state.workflow_id, "intent.json")

    def fail_recovery(name):
        """Interrupt only the selected rollback boundary."""
        if name == checkpoint:
            raise RuntimeError("synthetic recovery interruption")

    monkeypatch.setattr(paired, "_checkpoint", fail_recovery)
    with pytest.raises(RuntimeError):
        service.recover_paired_workflow_revision(
            root.name, state.workflow_id, intent_sha256=sha256_file(intent)
        )
    monkeypatch.setattr(paired, "_checkpoint", lambda _name: None)
    service.recover_paired_workflow_revision(
        root.name, state.workflow_id, intent_sha256=sha256_file(intent)
    )
    assert all((root / path).read_bytes() == content for path, content in before.items())


def test_late_cas_edit_survives_temporary_read(tmp_path, monkeypatch):
    """The final target check catches edits that appear while replacement bytes are read."""

    root, state, _before = _paired(tmp_path, monkeypatch)
    target = root / paired.MODEL_PATH
    original_read = Path.read_bytes
    edited = target.read_bytes() + b" \n"

    def mutate_during_read(path):
        """Simulate an external editor during the avoidable temporary-read race window."""
        content = original_read(path)
        if path.name.startswith(".modeling_plan.json.paired-"):
            target.write_bytes(edited)
        return content

    monkeypatch.setattr(Path, "read_bytes", mutate_during_read)
    with workflow_write_lock(root, root.name, state.workflow_id):
        with pytest.raises(ValueError, match="concurrent"):
            paired._cas(root, state.workflow_id, paired.MODEL_PATH, sha256_file(target), b"{}\n")
    assert target.read_bytes() == edited


def test_shared_lock_blocks_second_writer(tmp_path, monkeypatch):
    """Pair promotion retains the existing global lock instead of introducing a parallel writer."""

    root, state, _before = _paired(tmp_path, monkeypatch)
    with workflow_write_lock(root, root.name, "other-writer"):
        with pytest.raises(RuntimeError, match="write lock"):
            service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)


def test_unfinalized_commit_cannot_hide_mixed_current_pair(tmp_path, monkeypatch):
    """An unfinalized commit does not make a mixed pair safe for generic readers."""

    root, state, before = _paired(tmp_path, monkeypatch)

    def interrupt(name):
        """Stop after the canonical pair commits but before its workflow receipt."""
        if name == "after_receipt":
            raise RuntimeError("synthetic commit interruption")

    monkeypatch.setattr(paired, "_checkpoint", interrupt)
    service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    (root / paired.MODEL_PATH).write_bytes(before[paired.MODEL_PATH])
    with pytest.raises(ValueError, match="canonical"):
        load_scene_spec(root / paired.SCENE_PATH)


def test_committed_receipt_bytes_are_pinned_by_successful_host(tmp_path, monkeypatch):
    """Completed host evidence rejects receipt tampering without rereading later canonical bytes."""

    root, state, _before = _paired(tmp_path, monkeypatch)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    receipt = paired.transaction_path(root, state.workflow_id, "receipt.json")
    receipt.write_bytes(receipt.read_bytes() + b" ")
    with pytest.raises(ValueError, match="tampered"):
        load_scene_spec(root / paired.SCENE_PATH)


def test_preintent_archive_crash_can_retry_exact_unconsumed_authority(tmp_path, monkeypatch):
    """An interruption before intent publication has no canonical or approval-consumption effect."""
    root, state, before = _paired(tmp_path, monkeypatch)

    def interrupt(name):
        """Stop after safe immutable archives but before authority consumption."""
        if name == "after_archives":
            raise RuntimeError("synthetic pre-intent interruption")

    monkeypatch.setattr(paired, "_checkpoint", interrupt)
    state = service.resume_workflow(root.name, state.workflow_id, max_host_steps=1)
    assert next(item.status for item in state.steps if item.step_id == "revision.apply") == "failed"
    assert all((root / path).read_bytes() == content for path, content in before.items())
    assert not paired.transaction_path(root, state.workflow_id, "intent.json").exists()
    paired.assert_no_pending_pair(root)
    monkeypatch.setattr(paired, "_checkpoint", lambda _name: None)
    state = service.resume_workflow(
        root.name, state.workflow_id, max_host_steps=1, retry_failed=True
    )
    assert (
        next(item.status for item in state.steps if item.step_id == "revision.apply") == "complete"
    )


def test_paired_author_rejects_original_model_changed_after_planning(tmp_path, monkeypatch):
    """An early canonical change cannot create a new binding under an older workflow plan."""

    root, _state, _before = _paired(tmp_path, monkeypatch)
    candidate = root / "analysis/paired_candidate.json"
    state = service.plan_workflow(
        "Revise exact original fixture",
        job_id=root.name,
        intent="revise_asset",
        revision_strategy="manual_guarded",
        paired_modeling_plan_path="analysis/paired_candidate.json",
        paired_modeling_plan_sha256=sha256_file(candidate),
    )
    canonical = root / paired.MODEL_PATH
    canonical.write_bytes(canonical.read_bytes() + b" ")
    with pytest.raises(service.OrchestrationArtifactConflict, match="hash changed"):
        _complete(root, state)
    assert not (
        root / "workflows" / state.workflow_id / "artifacts/revision_payload_binding.json"
    ).exists()
    assert not (
        root / "workflows" / state.workflow_id / "completions/revision.author.json"
    ).exists()
