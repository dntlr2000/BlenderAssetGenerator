from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_blender_modeler.blender_artifacts import sha256_file
from codex_blender_modeler.storage_retention import (
    apply_storage_cleanup,
    finalize_gate_run,
    inventory_repository_storage,
    plan_storage_cleanup,
    resume_gate_run_retention,
    resume_storage_cleanup,
    verify_gate_retention_recovery_receipt,
    verify_storage_cleanup_receipt,
)
from codex_blender_modeler.storage_retention import service as retention_service


def _run_git(repo: Path, *arguments: str) -> None:
    """Run one deterministic local Git fixture command without a shell."""

    subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path, *, readme: str = "fixture\n") -> Path:
    """Create one isolated committed repository with retention roots."""

    repo = tmp_path / "repo"
    repo.mkdir()
    for relative in (".b", ".t", "reports", "workspaces", "workspace_archive"):
        (repo / relative).mkdir()
    (repo / "README.md").write_text(readme, encoding="utf-8")
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.name", "Retention Test")
    _run_git(repo, "config", "user.email", "retention@example.invalid")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-qm", "fixture")
    return repo


def _write_tree(repo: Path, relative: str, content: bytes = b"fixture") -> Path:
    """Create one small run-owned tree for a retention test."""

    root = repo / Path(*relative.split("/"))
    root.mkdir(parents=True)
    (root / "artifact.bin").write_bytes(content)
    return root


def _directory_link(link: Path, target: Path) -> None:
    """Create a directory symlink or Windows junction for retention safety tests."""

    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"Windows junction creation is unavailable: {result.stderr}")
        return
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink creation is unavailable: {exc}")


def _age_tree(root: Path, *, hours: int = 48) -> None:
    """Set a whole fixture tree safely beyond the minimum retention age."""

    timestamp = (datetime.now(UTC) - timedelta(hours=hours)).timestamp()
    for path in sorted(root.rglob("*"), reverse=True):
        os.utime(path, (timestamp, timestamp))
    os.utime(root, (timestamp, timestamp))


def test_inventory_protects_references_unknown_runs_and_paired_failures(
    tmp_path: Path,
) -> None:
    """Delete only old caches and orphan process temp in a legacy inventory."""

    repo = _repository(
        tmp_path,
        readme="Preserve `.b/referenced/artifact.bin` as historical evidence.\n",
    )
    cache = _write_tree(repo, ".t/uv-cache")
    orphan = _write_tree(repo, ".t/orphan-process-temp")
    referenced = _write_tree(repo, ".b/referenced")
    unknown = _write_tree(repo, ".b/unknown")
    paired = _write_tree(repo, ".t/failed")
    paired_temp = _write_tree(repo, ".t/failed-process-temp")
    for root in (cache, orphan, referenced, unknown, paired, paired_temp):
        _age_tree(root)

    inventory = inventory_repository_storage(repo_root=repo)
    entries = {entry.path: entry for entry in inventory.entries}

    assert entries[".t/uv-cache"].disposition == "eligible"
    assert entries[".t/orphan-process-temp"].disposition == "eligible"
    assert entries[".b/referenced"].reasons == ["REFERENCED_BY_PRESERVED_EVIDENCE"]
    assert entries[".b/unknown"].reasons == ["UNKNOWN_RUN_OUTCOME"]
    assert entries[".t/failed-process-temp"].reasons == [
        "UNKNOWN_PAIRED_RUN_OUTCOME"
    ]
    assert entries[".t/failed"].disposition == "protected"


def test_inventory_protects_hash_anchored_recent_and_active_trees(tmp_path: Path) -> None:
    """Treat hash-only evidence, recent scratch, and live PID roots as non-deletable."""

    repo = _repository(tmp_path)
    hash_anchored = _write_tree(repo, ".t/uv-cache", b"hash-anchored")
    anchored_sha256 = sha256_file(hash_anchored / "artifact.bin")
    (repo / "reports" / "anchor.json").write_text(
        json.dumps({"artifact_sha256": anchored_sha256}),
        encoding="utf-8",
    )
    _write_tree(repo, ".t/.ruff_cache")
    active = _write_tree(repo, f".t/gate-active-{os.getpid()}")
    _age_tree(hash_anchored)
    _age_tree(active)

    inventory = inventory_repository_storage(repo_root=repo)
    entries = {entry.path: entry for entry in inventory.entries}

    assert entries[".t/uv-cache"].reasons == ["MATCHES_PROTECTED_ARTIFACT_HASH"]
    assert entries[".t/uv-cache"].matched_protected_hashes == [anchored_sha256]
    assert entries[".t/.ruff_cache"].reasons == ["MINIMUM_AGE_NOT_REACHED"]
    assert entries[f".t/gate-active-{os.getpid()}"].reasons == ["ACTIVE_OR_LOCKED"]


def test_protection_scan_accepts_only_separately_scanned_internal_link_aliases(
    tmp_path: Path,
) -> None:
    """Skip an internal evidence alias only when its real target is independently scanned."""

    repo = _repository(tmp_path)
    cache = _write_tree(repo, ".t/uv-cache")
    _age_tree(cache)
    target = repo / "reports" / "actual"
    target.mkdir()
    (target / "anchor.json").write_text(
        json.dumps({"temporary_path": ".t/uv-cache/artifact.bin"}),
        encoding="utf-8",
    )
    _directory_link(repo / "reports" / "alias", target)

    inventory = inventory_repository_storage(repo_root=repo)
    entry = next(item for item in inventory.entries if item.path == ".t/uv-cache")

    assert inventory.status == "complete"
    assert entry.reasons == ["REFERENCED_BY_PRESERVED_EVIDENCE"]
    assert "reports/alias" not in inventory.inaccessible_paths


def test_protection_scan_rejects_a_link_alias_outside_its_evidence_root(
    tmp_path: Path,
) -> None:
    """Keep the global protection index incomplete for an external evidence alias."""

    repo = _repository(tmp_path)
    cache = _write_tree(repo, ".t/uv-cache")
    _age_tree(cache)
    outside = _write_tree(repo, "outside")
    _directory_link(repo / "reports" / "external", outside)

    inventory = inventory_repository_storage(repo_root=repo)
    entry = next(item for item in inventory.entries if item.path == ".t/uv-cache")

    assert inventory.status == "partial"
    assert entry.reasons == ["PROTECTION_INDEX_INCOMPLETE"]
    assert "reports/external" in inventory.inaccessible_paths


def test_exact_plan_apply_and_receipt_remove_only_candidates(tmp_path: Path) -> None:
    """Require exact plan confirmation and preserve every excluded sibling."""

    repo = _repository(tmp_path)
    cache = _write_tree(repo, ".t/uv-cache", b"remove")
    protected = _write_tree(repo, ".b/unknown", b"keep")
    _age_tree(cache)
    _age_tree(protected)
    inventory = inventory_repository_storage(repo_root=repo)
    plan = plan_storage_cleanup(inventory.inventory_id, repo_root=repo)
    plan_path = (
        repo / "reports" / "storage_retention" / "plans" / f"{plan.plan_id}.json"
    )

    with pytest.raises(PermissionError):
        apply_storage_cleanup(
            plan.plan_id,
            confirm_plan_sha256="0" * 64,
            repo_root=repo,
        )
    receipt = apply_storage_cleanup(
        plan.plan_id,
        confirm_plan_sha256=sha256_file(plan_path),
        repo_root=repo,
    )

    assert receipt.status == "completed"
    assert receipt.reclaimed_byte_size == len(b"remove")
    assert not cache.exists()
    assert protected.is_dir()
    assert verify_storage_cleanup_receipt(receipt.receipt_id, repo_root=repo) == receipt


def test_apply_rejects_a_candidate_changed_after_planning(tmp_path: Path) -> None:
    """Fail before deletion when any exact candidate tree becomes stale."""

    repo = _repository(tmp_path)
    cache = _write_tree(repo, ".t/uv-cache")
    _age_tree(cache)
    inventory = inventory_repository_storage(repo_root=repo)
    plan = plan_storage_cleanup(inventory.inventory_id, repo_root=repo)
    plan_path = (
        repo / "reports" / "storage_retention" / "plans" / f"{plan.plan_id}.json"
    )
    (cache / "changed.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="stale"):
        apply_storage_cleanup(
            plan.plan_id,
            confirm_plan_sha256=sha256_file(plan_path),
            repo_root=repo,
        )
    assert cache.is_dir()


def test_cleanup_resumes_after_a_quarantined_partial_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume exact captured scratch without broadening or re-planning its target."""

    repo = _repository(tmp_path)
    cache = _write_tree(repo, ".t/uv-cache")
    _age_tree(cache)
    inventory = inventory_repository_storage(repo_root=repo)
    plan = plan_storage_cleanup(inventory.inventory_id, repo_root=repo)
    plan_path = (
        repo / "reports" / "storage_retention" / "plans" / f"{plan.plan_id}.json"
    )
    confirmation = sha256_file(plan_path)
    original_remove = retention_service._safe_remove_tree

    def fail_once(root: Path, *, quarantine_root: Path) -> None:
        """Simulate one post-capture filesystem failure without deleting fixture bytes."""

        raise OSError("simulated retention interruption")

    monkeypatch.setattr(retention_service, "_safe_remove_tree", fail_once)
    partial = apply_storage_cleanup(
        plan.plan_id,
        confirm_plan_sha256=confirmation,
        repo_root=repo,
    )
    assert partial.status == "partial"
    assert not cache.exists()

    monkeypatch.setattr(retention_service, "_safe_remove_tree", original_remove)
    completed = resume_storage_cleanup(
        plan.plan_id,
        confirm_plan_sha256=confirmation,
        repo_root=repo,
    )
    assert completed.status == "completed"
    assert verify_storage_cleanup_receipt(completed.receipt_id, repo_root=repo) == completed


def test_success_gate_compacts_scratch_and_failure_preserves_it(tmp_path: Path) -> None:
    """Separate technical gate outcome from automatic retention behavior."""

    repo = _repository(tmp_path)
    success = _write_tree(repo, ".t/gate-success-99101")
    process_temp = _write_tree(repo, ".t/gate-success-99101-process-temp")
    success_receipt = finalize_gate_run(
        run_id="gate-success-99101",
        gate_id="v09",
        run_root=".t/gate-success-99101",
        process_temp_root=".t/gate-success-99101-process-temp",
        repo_root=repo,
    )

    assert success_receipt.gate_outcome == "passed"
    assert success_receipt.retention_outcome == "compacted"
    assert success_receipt.retained_artifacts[0].kind == "gate_run_preflight"
    assert (
        repo / "reports" / "gate_runs" / "gate-success-99101" / "preflight.json"
    ).is_file()
    assert not success.exists()
    assert not process_temp.exists()
    assert not (
        repo / ".cbm" / "storage_retention" / "gate-quarantine" / "gate-success-99101"
    ).exists()

    failed = _write_tree(repo, ".t/gate-failed-99102")
    failed_receipt = finalize_gate_run(
        run_id="gate-failed-99102",
        gate_id="v09",
        run_root=".t/gate-failed-99102",
        gate_outcome="failed",
        repo_root=repo,
    )
    assert failed_receipt.retention_outcome == "preserved_failure"
    assert failed.is_dir()


def test_success_gate_unlinks_nested_link_without_touching_target(tmp_path: Path) -> None:
    """Compact trusted gate scratch links as entries while preserving their targets."""

    repo = _repository(tmp_path)
    outside = _write_tree(repo, "outside", b"preserve-target")
    success = _write_tree(repo, ".t/gate-linked-99104")
    _directory_link(success / "external", outside)

    receipt = finalize_gate_run(
        run_id="gate-linked-99104",
        gate_id="full-regression",
        run_root=".t/gate-linked-99104",
        repo_root=repo,
    )

    assert receipt.retention_outcome == "compacted"
    assert receipt.source_file_count == 2
    assert not success.exists()
    assert (outside / "artifact.bin").read_bytes() == b"preserve-target"


def test_success_gate_removes_read_only_regular_files(tmp_path: Path) -> None:
    """Compact a successful gate despite read-only files in nested test repositories."""

    repo = _repository(tmp_path)
    success = _write_tree(repo, ".t/gate-read-only-99105")
    artifact = success / "artifact.bin"
    os.chmod(artifact, stat.S_IREAD)

    receipt = finalize_gate_run(
        run_id="gate-read-only-99105",
        gate_id="full-regression",
        run_root=".t/gate-read-only-99105",
        repo_root=repo,
    )

    assert receipt.retention_outcome == "compacted"
    assert not success.exists()


def test_gate_retention_failure_resumes_only_from_quarantine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover an interrupted gate compaction without recapturing a source path."""

    repo = _repository(tmp_path)
    success = _write_tree(repo, ".t/gate-recovery-99106")
    original_remove = retention_service._safe_remove_tree

    def fail_gate_removal(
        root: Path,
        *,
        quarantine_root: Path,
        allow_link_members: bool = False,
    ) -> None:
        """Simulate one filesystem failure after the gate tree enters quarantine."""

        del root, quarantine_root, allow_link_members
        raise PermissionError("simulated read-only artifact")

    monkeypatch.setattr(retention_service, "_safe_remove_tree", fail_gate_removal)
    with pytest.raises(RuntimeError, match="retention failed closed"):
        finalize_gate_run(
            run_id="gate-recovery-99106",
            gate_id="full-regression",
            run_root=".t/gate-recovery-99106",
            repo_root=repo,
        )
    assert not success.exists()

    monkeypatch.setattr(retention_service, "_safe_remove_tree", original_remove)
    recovery = resume_gate_run_retention("gate-recovery-99106", repo_root=repo)

    assert recovery.status == "completed"
    assert recovery.removed_roots == [".t/gate-recovery-99106"]
    assert recovery.remaining_roots == []
    assert recovery.reclaimed_byte_size == len(b"fixture")
    assert (
        verify_gate_retention_recovery_receipt(
            recovery.run_id,
            recovery.recovery_id,
            repo_root=repo,
        )
        == recovery
    )


def test_gate_retention_resume_never_captures_a_source_left_by_move_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leave a never-quarantined source untouched during explicit retention recovery."""

    repo = _repository(tmp_path)
    success = _write_tree(repo, ".t/gate-move-failure-99107")
    original_replace = retention_service.os.replace

    def fail_gate_capture(source: str, destination: str) -> None:
        """Simulate a move failure before the exact gate source enters quarantine."""

        if "gate-move-failure-99107" in os.fspath(source):
            raise PermissionError("simulated move failure")
        original_replace(source, destination)

    monkeypatch.setattr(retention_service.os, "replace", fail_gate_capture)
    with pytest.raises(RuntimeError, match="retention failed closed"):
        finalize_gate_run(
            run_id="gate-move-failure-99107",
            gate_id="full-regression",
            run_root=".t/gate-move-failure-99107",
            repo_root=repo,
        )
    monkeypatch.setattr(retention_service.os, "replace", original_replace)

    recovery = resume_gate_run_retention("gate-move-failure-99107", repo_root=repo)

    assert recovery.status == "partial"
    assert recovery.removed_roots == []
    assert recovery.remaining_roots == [".t/gate-move-failure-99107"]
    assert recovery.reclaimed_byte_size == 0
    assert success.is_dir()


def test_preserved_success_receipt_makes_old_gate_root_eligible(tmp_path: Path) -> None:
    """Allow later cleanup only when a durable receipt proves the gate passed."""

    repo = _repository(tmp_path)
    run_root = _write_tree(repo, ".t/gate-preserved-99103")
    _age_tree(run_root)
    finalize_gate_run(
        run_id="gate-preserved-99103",
        gate_id="v08",
        run_root=".t/gate-preserved-99103",
        retention_policy="preserve",
        repo_root=repo,
    )

    inventory = inventory_repository_storage(repo_root=repo)
    entry = next(item for item in inventory.entries if item.path == ".t/gate-preserved-99103")
    assert entry.disposition == "eligible"
    assert entry.reasons == ["VERIFIED_SUCCESS_RUN"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink support unavailable")
def test_inventory_never_follows_a_link_candidate(tmp_path: Path) -> None:
    """Keep a linked immediate child protected instead of traversing its target."""

    repo = _repository(tmp_path)
    outside = _write_tree(repo, "outside")
    link = repo / ".t" / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit symlink creation")

    inventory = inventory_repository_storage(repo_root=repo)
    entry = next(item for item in inventory.entries if item.path == ".t/linked")
    assert entry.disposition == "protected"
    assert ".t/linked" in inventory.inaccessible_paths
    assert outside.is_dir()


def test_inventory_protects_a_candidate_with_a_nested_link(tmp_path: Path) -> None:
    """Keep legacy candidates with nested links protected despite gate-only cleanup support."""

    repo = _repository(tmp_path)
    outside = _write_tree(repo, "outside", b"preserve-target")
    cache = _write_tree(repo, ".t/uv-cache")
    _directory_link(cache / "external", outside)
    _age_tree(cache)

    inventory = inventory_repository_storage(repo_root=repo)
    entry = next(item for item in inventory.entries if item.path == ".t/uv-cache")

    assert inventory.status == "complete"
    assert entry.disposition == "protected"
    assert "CONTAINS_LINK_OR_REPARSE_POINT" in entry.reasons
    assert "MINIMUM_AGE_NOT_REACHED" in entry.reasons
    assert ".t/uv-cache" not in inventory.inaccessible_paths
    assert (outside / "artifact.bin").read_bytes() == b"preserve-target"
