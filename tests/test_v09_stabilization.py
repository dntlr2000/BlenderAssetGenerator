from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader

import codex_blender_modeler.stabilization.pdf_report as stability_pdf
import codex_blender_modeler.stabilization.service as stabilization_service
from codex_blender_modeler.config import Settings
from codex_blender_modeler.orchestration.service import plan_workflow
from codex_blender_modeler.stabilization import (
    audit_workspace_state,
    enqueue_short_workflow,
    generate_stability_pdf_report,
    get_local_workflow_queue,
    probe_release_environment,
    requeue_local_workflow,
    run_local_workflow_queue,
)
from codex_blender_modeler.stabilization.locks import (
    acquire_queue_lock,
    release_queue_lock,
    write_expired_queue_lock_for_test,
)
from codex_blender_modeler.workspace import create_job, sha256_file


def _image(path: Path, color: tuple[int, int, int] = (80, 130, 180)) -> Path:
    """Create one deterministic image fixture for isolated V0.9 jobs."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path)
    return path


def _isolated_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Settings, Path]:
    """Route job, report, and queue writes into one isolated temporary repository."""

    repo = tmp_path / "repo"
    workspace = repo / "workspaces"
    repo.mkdir(parents=True)
    workspace.mkdir(parents=True)
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    settings = Settings(
        repo_root=repo,
        workspace_root=workspace,
        blender_bin=str(tmp_path / "Blender 5.0" / "blender.exe"),
        codex_bin="codex",
        blender_timeout=900,
    )
    monkeypatch.setattr(stabilization_service, "get_settings", lambda: settings)
    monkeypatch.setattr(stability_pdf, "get_settings", lambda: settings)
    return settings, workspace


def test_environment_probe_is_hash_bound_and_redacts_absolute_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reuse Blender evidence by digest without copying its absolute output paths."""

    settings, _workspace = _isolated_settings(monkeypatch, tmp_path)
    evidence = settings.repo_root / "reports" / "blender_compatibility.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps(
            {
                "ok": True,
                "blender_version": "5.0.1",
                "absolute_secret_path": str(tmp_path / "should-not-leak"),
            }
        ),
        encoding="utf-8",
    )
    report = probe_release_environment(probe_id="probe-test")
    serialized = report.model_dump_json()
    assert report.blender_report_status == "valid"
    assert report.blender_version == "5.0.1"
    assert report.evidence[0].sha256 == sha256_file(evidence)
    assert str(tmp_path) not in serialized
    assert report.blender_executable_name == "blender.exe"
    output = (
        settings.repo_root
        / "reports/v09/environment/probe-test/environment_probe.json"
    )
    assert output.is_file()


def test_workspace_audit_verifies_sources_and_reports_legacy_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pass an intact legacy job without mutating or migrating its metadata."""

    settings, workspace = _isolated_settings(monkeypatch, tmp_path)
    reference = _image(tmp_path / "reference.png")
    metadata = create_job("audit_asset", reference, "concept", [])
    job_json = workspace / "audit_asset" / "job.json"
    payload = json.loads(job_json.read_text(encoding="utf-8"))
    payload["project_version_created"] = "0.8.0"
    job_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    before = job_json.read_bytes()
    report = audit_workspace_state(job_id="audit_asset", audit_id="audit-healthy")
    assert report.status == "passed"
    assert report.jobs[0].migration_status == "compatible_legacy"
    assert report.jobs[0].source_count == 1
    assert report.jobs[0].verified_source_count == 1
    assert job_json.read_bytes() == before
    serialized = report.model_dump_json()
    assert str(settings.workspace_root) not in serialized
    assert metadata["reference_sha256"] in job_json.read_text(encoding="utf-8")


def test_workspace_audit_fails_on_source_tamper_and_dangling_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Detect immutable input changes and a stale latest-workflow pointer together."""

    _settings, workspace = _isolated_settings(monkeypatch, tmp_path)
    reference = _image(tmp_path / "reference.png")
    create_job("tampered_asset", reference, "concept", [])
    root = workspace / "tampered_asset"
    (root / "input" / "reference.png").write_bytes(b"tampered")
    latest = root / "workflows" / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(
        json.dumps(
            {
                "schema_version": "0.8.0",
                "job_id": "tampered_asset",
                "workflow_id": "wf-missing",
                "status": "planned",
            }
        ),
        encoding="utf-8",
    )
    report = audit_workspace_state(
        job_id="tampered_asset",
        audit_id="audit-tampered",
    )
    codes = {finding.code for finding in report.jobs[0].findings}
    assert report.status == "failed"
    assert "SOURCE_HASH_MISMATCH" in codes
    assert "DANGLING_WORKFLOW_POINTER" in codes


def test_stability_pdf_is_hash_bound_private_and_immutable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Project strict V0.9 evidence into a readable PDF without leaking host paths."""

    settings, _workspace = _isolated_settings(monkeypatch, tmp_path)
    reference = _image(tmp_path / "reference.png")
    create_job("pdf_asset", reference, "concept", [])
    probe = probe_release_environment(probe_id="probe-pdf")
    audit = audit_workspace_state(job_id="pdf_asset", audit_id="audit-pdf")
    probe_path = (
        settings.repo_root
        / "reports/v09/environment/probe-pdf/environment_probe.json"
    )
    audit_path = settings.repo_root / "reports/v09/audits/audit-pdf/workspace_audit.json"
    before = (probe_path.read_bytes(), audit_path.read_bytes())

    result = generate_stability_pdf_report(
        probe.probe_id,
        audit.audit_id,
        report_id="stability-pdf",
    )
    pdf = Path(result["pdf"])
    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)

    assert pdf.is_file()
    assert len(PdfReader(pdf).pages) >= 2
    assert "V0.9" in extracted
    assert "stability-pdf" in extracted
    assert str(tmp_path) not in extracted
    assert str(tmp_path) not in manifest_path.read_text(encoding="utf-8")
    assert manifest["pdf_sha256"] == result["pdf_sha256"] == sha256_file(pdf)
    assert {item["kind"] for item in manifest["sources"]} == {
        "environment_probe",
        "workspace_audit",
    }
    assert probe_path.read_bytes() == before[0]
    assert audit_path.read_bytes() == before[1]
    with pytest.raises(FileExistsError, match="already exists"):
        generate_stability_pdf_report(
            probe.probe_id,
            audit.audit_id,
            report_id="stability-pdf",
        )
    with pytest.raises(ValueError, match="report_id must match"):
        generate_stability_pdf_report(
            probe.probe_id,
            audit.audit_id,
            report_id="../escape",
        )


def test_local_queue_stops_at_agent_boundary_and_rejects_duplicate_job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Run deterministic analysis once, then wait instead of bypassing agent authorship."""

    _settings, _workspace = _isolated_settings(monkeypatch, tmp_path)
    reference = _image(tmp_path / "reference.png")
    state = plan_workflow(
        "Create a proxy from this reference.",
        job_id="queued_asset",
        reference_path=reference,
    )
    queue = enqueue_short_workflow("queued_asset", state.workflow_id)
    assert queue.entries[0].status == "queued"
    with pytest.raises(FileExistsError, match="active local queue entry"):
        enqueue_short_workflow("queued_asset", state.workflow_id)
    queue = run_local_workflow_queue(max_entries=1, max_host_steps=1)
    entry = queue.entries[0]
    assert entry.status == "waiting"
    assert entry.last_workflow_status == "waiting_for_agent"
    receipts = list(
        (_settings.workspace_root / ".cbm/queue/receipts" / entry.entry_id).glob(
            "*.json"
        )
    )
    assert len(receipts) == 1


def test_local_queue_failed_retry_is_explicit_and_single_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Require an explicit requeue token and consume it on exactly one dispatch."""

    _settings, _workspace = _isolated_settings(monkeypatch, tmp_path)
    statuses = {"value": "running"}

    def fake_status(job_id: str, workflow_id: str) -> dict:
        """Return one controlled workflow state for queue-only failure tests."""

        return {
            "job_id": job_id,
            "workflow_id": workflow_id,
            "state": {"status": statuses["value"]},
        }

    retry_values: list[bool] = []

    def fail_resume(*args, retry_failed: bool = False, **kwargs):
        """Return one failed V0.8 state while recording retry authorization."""

        retry_values.append(retry_failed)
        statuses["value"] = "failed"
        return SimpleNamespace(status="failed")

    monkeypatch.setattr(stabilization_service, "get_workflow_status", fake_status)
    monkeypatch.setattr(stabilization_service, "resume_workflow", fail_resume)
    queue = enqueue_short_workflow("queue_asset", "wf-test", max_attempts=2)
    entry_id = queue.entries[0].entry_id
    queue = run_local_workflow_queue()
    assert queue.entries[0].status == "failed"
    assert retry_values == [False]
    with pytest.raises(PermissionError, match="retry_failed=True"):
        requeue_local_workflow(entry_id, retry_failed=False)
    queue = requeue_local_workflow(entry_id, retry_failed=True)
    assert queue.entries[0].retry_failed_once is True

    def successful_resume(*args, retry_failed: bool = False, **kwargs):
        """Return a waiting workflow after observing one explicit retry token."""

        retry_values.append(retry_failed)
        return SimpleNamespace(status="waiting_for_approval")

    monkeypatch.setattr(stabilization_service, "resume_workflow", successful_resume)
    statuses["value"] = "failed"
    queue = run_local_workflow_queue()
    assert queue.entries[0].status == "waiting"
    assert queue.entries[0].retry_failed_once is False
    assert retry_values == [False, True]


def test_queue_lock_recovers_only_a_valid_expired_lock(tmp_path: Path) -> None:
    """Archive one expired queue lock while refusing to steal a current lock."""

    queue_root = tmp_path / "queue"
    write_expired_queue_lock_for_test(queue_root)
    acquired = acquire_queue_lock(queue_root, ttl_seconds=60)
    assert list((queue_root / "stale_locks").glob("*.json"))
    with pytest.raises(RuntimeError, match="owns the local workflow queue lock"):
        acquire_queue_lock(queue_root, ttl_seconds=60)
    release_queue_lock(queue_root, acquired)
    assert not (queue_root / ".lock.json").exists()


def test_expired_execution_lease_writes_one_interrupted_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recover one abandoned queue attempt with exactly one immutable receipt."""

    settings, _workspace = _isolated_settings(monkeypatch, tmp_path)

    def fake_status(job_id: str, workflow_id: str) -> dict:
        """Expose a controlled non-terminal workflow to the queue fixture."""

        return {
            "job_id": job_id,
            "workflow_id": workflow_id,
            "state": {"status": "running"},
        }

    monkeypatch.setattr(stabilization_service, "get_workflow_status", fake_status)
    queue = enqueue_short_workflow("lease_asset", "wf-lease")
    now = datetime.now(UTC)
    abandoned = queue.entries[0].model_copy(
        update={
            "status": "running",
            "attempt_count": 1,
            "enqueued_at": now - timedelta(minutes=10),
            "started_at": now - timedelta(minutes=5),
            "updated_at": now - timedelta(minutes=5),
            "lease_id": "a" * 32,
            "lease_expires_at": now - timedelta(minutes=1),
        }
    )
    queue = queue.model_copy(update={"entries": [abandoned]})
    queue_path = settings.workspace_root / ".cbm/queue/local_queue.json"
    queue_path.write_text(queue.model_dump_json(indent=2), encoding="utf-8")

    recovered = run_local_workflow_queue()
    assert recovered.entries[0].status == "failed"
    assert recovered.entries[0].last_error.startswith("InterruptedQueueAttempt")
    receipts = list(
        (settings.workspace_root / ".cbm/queue/receipts" / abandoned.entry_id).glob(
            "*.json"
        )
    )
    assert len(receipts) == 1
    payload = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert payload["attempt_number"] == 1
    assert payload["error_type"] == "InterruptedQueueAttempt"
    assert payload["outcome"] == "failed"

    recovered_again = run_local_workflow_queue()
    assert recovered_again.entries[0].status == "failed"
    assert len(list(receipts[0].parent.glob("*.json"))) == 1


def test_empty_queue_status_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Return an empty in-memory queue without creating operational files."""

    settings, _workspace = _isolated_settings(monkeypatch, tmp_path)
    queue = get_local_workflow_queue()
    assert queue.entries == []
    assert not (settings.workspace_root / ".cbm/queue/local_queue.json").exists()
