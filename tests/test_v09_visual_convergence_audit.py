"""V0.9 semantic-audit coverage for bounded V0.6 visual convergence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import codex_blender_modeler.stabilization.service as stabilization_service
from codex_blender_modeler.auto_revision.candidate_builder import (
    build_revision_candidates,
)
from codex_blender_modeler.auto_revision.convergence_session import (
    approve_job_visual_convergence,
    plan_job_visual_convergence,
    run_job_visual_convergence,
)
from codex_blender_modeler.auto_revision.convergence_session_models import (
    HashBoundConvergenceArtifact,
    VisualConvergencePlan,
)
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.config import Settings
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.models import (
    REQUIRED_QA_PASS_KINDS,
    BoundingBoxMetric,
    DirectVisualMetrics,
    QAFinding,
    RenderPassManifest,
    RenderPassRecord,
    SuggestedEdit,
    VisualQAReport,
    VisualQARequest,
)
from codex_blender_modeler.qa.structural_regression import (
    AssemblySanityTerminalEvidence,
)
from codex_blender_modeler.stabilization import audit_workspace_state
from codex_blender_modeler.workspace import create_job, sha256_file

SHA = "0" * 64
TARGET_ID = "demo.profile_house"


def _settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Settings, Path]:
    """Create one isolated repository and route stabilization writes into it."""

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
    return settings, workspace


def _direct_metrics(score: float) -> DirectVisualMetrics:
    """Build deterministic semantic direct metrics for one convergence QA fixture."""

    return DirectVisualMetrics(
        scoring_version="semantic_bbox_v2",
        silhouette_iou=score,
        silhouette_union_fraction=0.5,
        global_bbox=BoundingBoxMetric(
            reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            rendered_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            center_error_norm=0.0,
            size_error_norm=0.0,
        ),
        overall_direct_score=score,
    )


def _finding() -> QAFinding:
    """Create one directly evidenced, bounded transform candidate."""

    return QAFinding(
        id="audit.raise-house",
        target_ids=[TARGET_ID],
        issue_type="position",
        severity="medium",
        description="Raise the fixture house inside the approved envelope.",
        evidence_sources=["direct_reference"],
        confidence=0.95,
        suggestion=SuggestedEdit(
            target_type="object",
            target_id=TARGET_ID,
            path=["transform", "location", 2],
            op="add",
            value=0.1,
        ),
    )


def _write_qa_run(
    root: Path,
    scene_spec_path: Path,
    *,
    run_id: str,
    score: float,
    findings: list[QAFinding],
) -> tuple[Path, Path]:
    """Write one complete seven-pass QA run and exact candidate bundle."""

    run_root = root / "qa" / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    pass_root = run_root / "passes"
    pass_root.mkdir()
    camera_sha256 = camera_fingerprint(scene_spec_path)
    pass_paths: dict[str, Path] = {}
    pass_records: list[RenderPassRecord] = []
    for kind in REQUIRED_QA_PASS_KINDS:
        pass_path = pass_root / f"{kind}.png"
        pass_path.write_bytes(f"{run_id}:{kind}".encode())
        pass_paths[kind] = pass_path
        pass_records.append(
            RenderPassRecord(
                kind=kind,
                path=str(pass_path),
                sha256=sha256_file(pass_path),
                width=64,
                height=64,
                encoding="fixture",
            )
        )
    manifest = RenderPassManifest(
        job_id="convergence_audit",
        run_id=run_id,
        scene_spec_sha256=sha256_file(scene_spec_path),
        camera_fingerprint=camera_sha256,
        build_fingerprint=str(
            collect_build_provenance(root, "convergence_audit")["fingerprint"]
        ),
        blender_version="5.0.1-fixture",
        render_engine="BLENDER_EEVEE",
        render_device="CPU",
        resolution=(64, 64),
        passes=pass_records,
    )
    manifest_path = run_root / "render_pass_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    reference = root / "input" / "reference.png"
    reference_mask = run_root / "reference_mask.png"
    reference_mask.write_bytes(b"audit-reference-mask")
    request = VisualQARequest(
        job_id="convergence_audit",
        run_id=run_id,
        mode="concept",
        reference_path=str(reference),
        reference_sha256=sha256_file(reference),
        reference_mask_path=str(reference_mask),
        reference_mask_sha256=sha256_file(reference_mask),
        preview_path=str(pass_paths["beauty"]),
        preview_sha256=sha256_file(pass_paths["beauty"]),
        render_pass_manifest_path=str(manifest_path),
        render_pass_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=sha256_file(scene_spec_path),
        camera_fingerprint=camera_sha256,
    )
    request_path = run_root / "request.json"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
    report = VisualQAReport(
        job_id="convergence_audit",
        run_id=run_id,
        request_sha256=sha256_file(request_path),
        camera_fingerprint=camera_sha256,
        direct_metrics=_direct_metrics(score),
        findings=findings,
        generated_target_status="not_requested",
    )
    report_path = run_root / "visual_qa_report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    candidates = build_revision_candidates(
        report,
        report_path=report_path,
        scene_spec_path=scene_spec_path,
    )
    candidates_path = run_root / "revision_candidates.json"
    candidates_path.write_text(candidates.model_dump_json(indent=2), encoding="utf-8")
    return report_path, candidates_path


def _job(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, str]:
    """Create one isolated valid SceneSpec and initial direct-QA run."""

    _settings(monkeypatch, tmp_path)
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 24), (80, 130, 180)).save(reference)
    create_job("convergence_audit", reference, "concept", [])
    root = tmp_path / "repo" / "workspaces" / "convergence_audit"
    repository = Path(__file__).resolve().parents[1]
    scene = json.loads(
        (
            repository
            / "examples"
            / "geometry_showcase"
            / "scene_spec.seed.json"
        ).read_text(encoding="utf-8")
    )
    scene["job_id"] = "convergence_audit"
    scene_spec_path = root / "analysis" / "scene_spec.json"
    scene_spec_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    run_id = "audit-initial"
    _write_qa_run(
        root,
        scene_spec_path,
        run_id=run_id,
        score=0.6,
        findings=[_finding()],
    )
    return root, scene_spec_path, run_id


def _pipeline(scene_spec_path: Path):
    """Return one deterministic non-Blender derived-pipeline replacement."""

    def run(
        job_id: str,
        root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, object]:
        """Report a successful isolated rebuild without touching source evidence."""

        assert job_id == "convergence_audit"
        assert render_engine == "eevee"
        assert render_device == "auto"
        scene = json.loads(scene_spec_path.read_text(encoding="utf-8"))
        return {
            "build": {"blend": str(root / "blender" / "scene.blend")},
            "preview": {"preview": str(root / "renders" / "preview.png")},
            "inventory_path": str(root / "reports" / "scene_inventory.json"),
            "object_count": len(scene["objects"]),
            "validation": {"ok": True, "errors": [], "warnings": []},
            "validation_path": str(root / "reports" / "validation.json"),
            "constraint_solution_path": None,
            "constraint_failures": 0,
            "constraint_results": [],
        }

    return run


def _post_qa(root: Path, scene_spec_path: Path, score: float):
    """Return one deterministic post-revision QA writer."""

    def run(
        job_id: str,
        render_engine: str,
        render_device: str,
        run_id: str | None = None,
    ) -> dict[str, object]:
        """Write the exact result QA run requested by the convergence host."""

        assert job_id == "convergence_audit"
        assert render_engine == "eevee"
        assert render_device == "auto"
        assert run_id is not None
        report_path, candidates_path = _write_qa_run(
            root,
            scene_spec_path,
            run_id=run_id,
            score=score,
            findings=[_finding()],
        )
        return {
            "ok": True,
            "job_id": job_id,
            "run_id": run_id,
            "visual_qa_report": str(report_path),
            "revision_candidates": str(candidates_path),
            "direct_score": score,
        }

    return run


def _complete_one_iteration(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    scene_spec_path: Path,
    run_id: str,
) -> None:
    """Create one real terminal session while replacing only Blender-dependent hosts."""

    from codex_blender_modeler.auto_revision import convergence_session

    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve one exact bounded audit iteration.",
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_job_pipeline",
        _pipeline(scene_spec_path),
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa(root, scene_spec_path, 0.75),
    )
    result = run_job_visual_convergence("convergence_audit", "audit-session")
    assert result["termination_reason"] == "target_reached"


def _complete_failed_after_result_build(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    scene_spec_path: Path,
    run_id: str,
) -> None:
    """Create a legitimate failed receipt after build but before result QA exists."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.8,
        target_silhouette_iou=0.8,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve one exact audit failure-boundary iteration.",
    )
    pipeline = _pipeline(scene_spec_path)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)

    def fail_before_qa(*args, **kwargs):
        """Simulate a host failure after result build provenance was captured."""

        del args, kwargs
        raise RuntimeError("simulated post-build QA failure")

    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        fail_before_qa,
    )
    result = run_job_visual_convergence("convergence_audit", "audit-session")
    assert result["termination_reason"] == "failed"


def _rebind_terminal_manifest(
    root: Path,
    session_id: str,
    *,
    changed_source_paths: list[str],
) -> None:
    """Rebind a test-only sidecar after a deliberate self-consistent evidence edit."""

    session_root = root / "qa" / "convergence" / session_id
    report_path = session_root / "convergence_report.json"
    manifest_path = session_root / "convergence_report.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed_hashes = {
        relative_path: sha256_file(root / relative_path)
        for relative_path in changed_source_paths
    }
    report_relative = report_path.relative_to(root).as_posix()
    manifest["report_json"]["sha256"] = changed_hashes[report_relative]
    for source in manifest["sources"]:
        changed_sha256 = changed_hashes.get(source["relative_path"])
        if changed_sha256 is not None:
            source["sha256"] = changed_sha256
    fingerprint_payload = [
        {
            "relative_path": source["relative_path"],
            "sha256": source["sha256"],
        }
        for source in manifest["sources"]
    ]
    canonical = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest["source_fingerprint"] = hashlib.sha256(canonical).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_v09_audit_accepts_terminal_chain_and_later_canonical_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep completed session evidence valid after a later legitimate canonical edit."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve one exact bounded audit iteration.",
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_job_pipeline",
        _pipeline(scene_spec_path),
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa(root, scene_spec_path, 0.75),
    )
    result = run_job_visual_convergence("convergence_audit", "audit-session")
    assert result["termination_reason"] == "target_reached"

    first = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-current",
    )
    assert first.status == "passed", [
        (item.code, item.message) for item in first.jobs[0].findings
    ]
    assert first.jobs[0].visual_convergence_status == "valid"
    assert first.jobs[0].valid_visual_convergence_session_count == 1

    scene = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    scene["assumptions"].append("Later separately approved authoring revision.")
    scene_spec_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    second = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-historical",
    )
    assert second.status == "passed"
    assert second.jobs[0].visual_convergence_status == "valid"


def test_v09_initial_snapshot_audit_binds_spatial_five_view_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Include approved five-view terminals in the exact convergence evidence set."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    plan = VisualConvergencePlan.model_validate_json(
        Path(planned["plan"]).read_text(encoding="utf-8")
    )
    evidence = AssemblySanityTerminalEvidence(
        run_id="audit-structural",
        plan_path="qa/assembly_sanity/runs/audit-structural/plan.json",
        plan_sha256=SHA,
        render_manifest_path=(
            "qa/assembly_sanity/runs/audit-structural/render_manifest.json"
        ),
        render_manifest_sha256=SHA,
        report_path="qa/assembly_sanity/runs/audit-structural/report.json",
        report_sha256=SHA,
    )
    spatial_plan = plan.model_copy(
        update={
            "structural_multiview_policy": "spatial_v1_required",
            "initial_structural_evidence": evidence,
        }
    )
    expected = [
        HashBoundConvergenceArtifact(
            relative_path=evidence.plan_path,
            sha256=evidence.plan_sha256,
        ),
        HashBoundConvergenceArtifact(
            relative_path=evidence.render_manifest_path,
            sha256=evidence.render_manifest_sha256,
        ),
        HashBoundConvergenceArtifact(
            relative_path=evidence.report_path,
            sha256=evidence.report_sha256,
        ),
    ]

    def structural_artifacts(*args, **kwargs):
        """Verify the audit forwards the exact structural ownership bindings."""

        assert args[0] == root
        assert args[1] == evidence
        assert kwargs["expected_job_id"] == "convergence_audit"
        assert kwargs["expected_scene_spec_sha256"] == plan.initial_scene_spec_sha256
        return expected

    monkeypatch.setattr(
        stabilization_service,
        "_structural_terminal_artifacts",
        structural_artifacts,
    )

    def host_safety(root_value, session_root, plan_value):
        """Keep this focused test isolated from host-envelope re-derivation."""

        assert root_value == root
        assert session_root.name == "audit-session"
        assert plan_value == spatial_plan

    monkeypatch.setattr(
        stabilization_service,
        "_require_host_safety_envelope",
        host_safety,
    )
    artifacts = stabilization_service._audit_initial_convergence_snapshots(
        root,
        root / "qa" / "convergence" / "audit-session",
        spatial_plan,
    )
    for artifact in expected:
        assert artifacts[artifact.relative_path] == artifact.sha256


def test_v09_audit_rejects_terminal_session_with_receiptless_staging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a terminal chain that conceals an incomplete iteration staging area."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    session_root = root / "qa" / "convergence" / "audit-session"
    (session_root / "staging" / "002").mkdir(parents=True)

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-terminal-staging",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_keeps_legacy_terminal_session_with_input_addition_as_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve legacy terminal history when an exact original-input map is unavailable."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.6,
        target_silhouette_iou=0.6,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    plan_path = Path(planned["plan"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan.pop("initial_input_hashes", None)
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        convergence_session,
        "_require_executable_plan_bindings",
        lambda _plan: None,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=sha256_file(plan_path),
        approval_note="Approve a legacy-compatible exact convergence plan.",
    )
    result = run_job_visual_convergence("convergence_audit", "audit-session")
    assert result["termination_reason"] == "target_reached"
    (root / "input" / "front.png").write_bytes(b"later-additional-view")

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-legacy-input-addition",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "warning"
    assert audit.jobs[0].visual_convergence_status == "valid"
    assert audit.jobs[0].valid_visual_convergence_session_count == 1
    assert "VISUAL_CONVERGENCE_HISTORICAL_INPUT_SET_UNVERIFIABLE" in codes


def test_v09_audit_verifies_original_inputs_and_allows_later_added_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep new terminal evidence valid when exact original inputs still match."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.6,
        target_silhouette_iou=0.6,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve an exact input-bound convergence baseline.",
    )
    result = run_job_visual_convergence("convergence_audit", "audit-session")
    assert result["termination_reason"] == "target_reached"
    (root / "input" / "front.png").write_bytes(b"later-additional-view")

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-exact-input-addition",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "passed", [
        (item.code, item.message) for item in audit.jobs[0].findings
    ]
    assert audit.jobs[0].visual_convergence_status == "valid"
    assert audit.jobs[0].valid_visual_convergence_session_count == 1
    assert "VISUAL_CONVERGENCE_HISTORICAL_INPUT_ADDITIONS" in codes


def test_v09_audit_rejects_original_input_tamper_after_terminal_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject changed original evidence even after a session became historical."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.6,
        target_silhouette_iou=0.6,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve one exact original-input baseline.",
    )
    result = run_job_visual_convergence("convergence_audit", "audit-session")
    assert result["termination_reason"] == "target_reached"
    original_input = next(path for path in (root / "input").iterdir() if path.is_file())
    original_input.write_bytes(b"tampered-original-input")

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-original-input-tamper",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_fails_closed_on_convergence_receipt_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a changed immutable receipt even when the edited JSON remains parseable."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve one exact bounded audit iteration.",
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_job_pipeline",
        _pipeline(scene_spec_path),
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa(root, scene_spec_path, 0.75),
    )
    run_job_visual_convergence("convergence_audit", "audit-session")
    receipt = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "iterations"
        / "001"
        / "receipt.json"
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["reason_codes"].append("tampered-but-parseable")
    receipt.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    report = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-tampered",
    )
    codes = {finding.code for finding in report.jobs[0].findings}
    assert report.status == "failed"
    assert report.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_incomplete_terminal_iteration_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a terminal report that omits one immutable receipt support artifact."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    report_path = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "convergence_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["iteration_evidence"]
    report["iteration_evidence"].pop()
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _rebind_terminal_manifest(
        root,
        "audit-session",
        changed_source_paths=[report_path.relative_to(root).as_posix()],
    )

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-incomplete-support-evidence",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_new_terminal_downgraded_to_legacy_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Use the immutable new-plan contract instead of a mutable report field."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    report_path = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "convergence_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report.pop("final_scene_spec_snapshot") is not None
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _rebind_terminal_manifest(
        root,
        "audit-session",
        changed_source_paths=[report_path.relative_to(root).as_posix()],
    )

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-downgrade",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_rebound_terminal_plan_metric_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject false terminal target metrics even after local sidecar hashes are rebound."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    report_path = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "convergence_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["target_direct_score"] = 0.71
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _rebind_terminal_manifest(
        root,
        "audit-session",
        changed_source_paths=[report_path.relative_to(root).as_posix()],
    )

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-false-summary",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_false_target_reached_termination_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a non-target terminal relabeled as target_reached after hash rebinding."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.9,
        target_silhouette_iou=0.9,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    approve_job_visual_convergence(
        "convergence_audit",
        "audit-session",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve one sub-target audit iteration.",
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_job_pipeline",
        _pipeline(scene_spec_path),
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa(root, scene_spec_path, 0.65),
    )
    result = run_job_visual_convergence("convergence_audit", "audit-session")
    assert result["termination_reason"] == "iteration_budget_exhausted"

    report_path = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "convergence_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["target_reached"] is False
    report["termination_reason"] = "target_reached"
    report["manual_review_required"] = False
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _rebind_terminal_manifest(
        root,
        "audit-session",
        changed_source_paths=[report_path.relative_to(root).as_posix()],
    )

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-false-target-reason",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_false_terminal_manual_review_semantics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a reached-target terminal falsely relabeled as needing manual review."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    report_path = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "convergence_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["termination_reason"] == "target_reached"
    report["manual_review_required"] = True
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _rebind_terminal_manifest(
        root,
        "audit-session",
        changed_source_paths=[report_path.relative_to(root).as_posix()],
    )

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-false-manual-review",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_rebound_receipt_score_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cross-check receipt metrics against exact source and result QA evidence."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    session_root = root / "qa" / "convergence" / "audit-session"
    receipt_path = session_root / "iterations" / "001" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["before_direct_score"] = 0.55
    receipt["score_delta"] = round(
        receipt["after_direct_score"] - receipt["before_direct_score"],
        6,
    )
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    report_path = session_root / "convergence_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["iteration_receipts"][0]["sha256"] = sha256_file(receipt_path)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _rebind_terminal_manifest(
        root,
        "audit-session",
        changed_source_paths=[
            receipt_path.relative_to(root).as_posix(),
            report_path.relative_to(root).as_posix(),
        ],
    )

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-false-receipt-score",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_requires_fixed_convergence_pdf_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a hash-correct PDF rebound outside the fixed session report path."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    session_root = root / "qa" / "convergence" / "audit-session"
    manifest_path = session_root / "convergence_report.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_pdf = root / manifest["pdf"]["relative_path"]
    alternate_pdf = session_root / "alternate_convergence_report.pdf"
    alternate_pdf.write_bytes(original_pdf.read_bytes())
    manifest["pdf"] = {
        "relative_path": alternate_pdf.relative_to(root).as_posix(),
        "sha256": sha256_file(alternate_pdf),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-pdf-path",
    )
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"


def test_v09_audit_rejects_terminal_receipt_without_terminal_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject consumed iteration authority when its terminal JSON was removed."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "convergence_report.json"
    ).unlink()

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-terminal-json-missing",
    )
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"


def test_v09_recomputes_exact_candidate_selection_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a self-consistent selection that differs from deterministic host policy."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    session_root = root / "qa" / "convergence" / "audit-session"
    plan = stabilization_service.VisualConvergencePlan.model_validate_json(
        (session_root / "plan.json").read_text(encoding="utf-8")
    )
    iteration_root = session_root / "iterations" / "001"
    selection = stabilization_service.ConvergenceCandidateSelection.model_validate_json(
        (iteration_root / "selection.json").read_text(encoding="utf-8")
    )
    candidates_path = (
        root / "qa" / "runs" / run_id / "revision_candidates.json"
    )
    candidates = stabilization_service.RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    forged = selection.model_copy(
        update={
            "selected_candidate_ids": [],
            "rejected": [],
            "selection_sha256": "0" * 64,
        }
    )

    with pytest.raises(ValueError, match="exact approved envelope"):
        stabilization_service._recompute_convergence_selection(
            plan,
            candidates,
            forged,
            candidates_sha256=sha256_file(candidates_path),
            base_scene_spec_path=iteration_root / "base_scene_spec.json",
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "after_direct_score": 0.6005,
                "score_delta": 0.0005,
            },
            "runtime acceptance predicates",
        ),
        (
            {
                "after_silhouette_iou": 0.59,
                "score_delta": 0.15,
            },
            "runtime acceptance predicates",
        ),
        (
            {
                "constraint_regression_count": 1,
                "score_delta": 0.15,
            },
            "runtime acceptance predicates",
        ),
    ],
)
def test_v09_rechecks_accepted_iteration_predicates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changes: dict[str, object],
    message: str,
) -> None:
    """Reject accepted receipts that fail gain, silhouette, or constraint predicates."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    session_root = root / "qa" / "convergence" / "audit-session"
    plan = stabilization_service.VisualConvergencePlan.model_validate_json(
        (session_root / "plan.json").read_text(encoding="utf-8")
    )
    receipt = stabilization_service.VisualConvergenceIteration.model_validate_json(
        (
            session_root
            / "iterations"
            / "001"
            / "receipt.json"
        ).read_text(encoding="utf-8")
    )
    forged = receipt.model_copy(update=changes)

    with pytest.raises(ValueError, match=message):
        stabilization_service._validate_convergence_iteration_outcome(plan, forged)


def test_v09_audit_tracks_active_session_and_rejects_stale_canonical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Classify an unapproved plan as active only while its canonical baseline is current."""

    _root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    active = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-active",
    )
    assert active.status == "passed"
    assert active.jobs[0].visual_convergence_status == "active"
    assert active.jobs[0].valid_visual_convergence_session_count == 0

    scene = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    scene["assumptions"].append("Unexpected active-session mutation.")
    scene_spec_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    stale = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-stale",
    )
    codes = {finding.code for finding in stale.jobs[0].findings}
    assert stale.status == "failed"
    assert stale.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_active_session_with_tampered_render_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Audit the active current QA request, manifest, mask, beauty, and seven passes."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    wireframe = root / "qa" / "runs" / run_id / "passes" / "wireframe.png"
    wireframe.write_bytes(wireframe.read_bytes() + b"tampered")

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-active-pass-tamper",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_active_plan_with_rebound_input_map(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject an active plan whose exact input map no longer hashes to its fingerprint."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    planned = plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    plan_path = Path(planned["plan"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    input_name = next(iter(plan["initial_input_hashes"]))
    plan["initial_input_hashes"][input_name] = "f" * 64
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-rebound-input-map",
    )
    codes = {finding.code for finding in audit.jobs[0].findings}
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes
    assert (root / "input" / input_name).is_file()


def test_v09_audit_rejects_active_session_with_missing_current_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Fail active-session audit when its resumable candidate bundle is missing."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    (
        root
        / "qa"
        / "runs"
        / run_id
        / "revision_candidates.json"
    ).unlink()
    report = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-missing-candidates",
    )
    codes = {finding.code for finding in report.jobs[0].findings}
    assert report.status == "failed"
    assert report.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_orphan_and_noncontiguous_iteration_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Treat receipt-less or noncontiguous iteration directories as interrupted evidence."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.7,
        target_silhouette_iou=0.7,
        allowed_target_ids=[TARGET_ID],
        max_iterations=2,
    )
    (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "iterations"
        / "002"
    ).mkdir(parents=True)
    report = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-orphan-iteration",
    )
    codes = {finding.code for finding in report.jobs[0].findings}
    assert report.status == "failed"
    assert report.jobs[0].visual_convergence_status == "invalid"
    assert "VISUAL_CONVERGENCE_INVALID" in codes


def test_v09_audit_rejects_constraint_evidence_tamper_and_count_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recompute constraint regressions instead of trusting a mutable receipt summary."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    session_root = root / "qa" / "convergence" / "audit-session"
    plan = stabilization_service.VisualConvergencePlan.model_validate_json(
        (session_root / "plan.json").read_text(encoding="utf-8")
    )
    receipt_path = session_root / "iterations" / "001" / "receipt.json"
    receipt = stabilization_service.VisualConvergenceIteration.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    forged = receipt.model_copy(update={"constraint_regression_count": 1})
    with pytest.raises(ValueError, match="differs from exact evidence"):
        stabilization_service._validate_convergence_iteration_outcome(
            plan,
            forged,
            recomputed_constraint_regression_count=0,
        )

    before_path = session_root / "iterations" / "001" / "before_constraints.json"
    before_payload = json.loads(before_path.read_text(encoding="utf-8"))
    before_payload["failures"] = 1
    before_path.write_text(json.dumps(before_payload, indent=2), encoding="utf-8")
    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-constraint-tamper",
    )
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("source_scene", "SceneSpec binding"),
        ("result_scene", "SceneSpec binding"),
        ("camera", "camera binding"),
        ("material_contract", "changed geometry, material"),
    ],
)
def test_v09_rejects_build_provenance_transition_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    """Permit only the approved SceneSpec hash transition across convergence builds."""

    root, _scene_spec_path, _run_id = _job(monkeypatch, tmp_path)
    baseline = collect_build_provenance(root, "convergence_audit")
    source = dict(baseline)
    result = dict(baseline)
    result["scene_spec_sha256"] = "1" * 64
    if mutation == "source_scene":
        source["scene_spec_sha256"] = "2" * 64
    elif mutation == "result_scene":
        result["scene_spec_sha256"] = "2" * 64
    elif mutation == "camera":
        result["camera_fingerprint"] = "3" * 64
    elif mutation == "material_contract":
        result["material_plan_sha256"] = "4" * 64

    with pytest.raises(ValueError, match=message):
        stabilization_service._validate_convergence_build_transition(
            source,
            result,
            expected_source_scene_spec_sha256=baseline["scene_spec_sha256"],
            expected_result_scene_spec_sha256="1" * 64,
            expected_camera_fingerprint=baseline["camera_fingerprint"],
        )


def test_v09_rejects_receipt_qa_and_build_chain_splice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a receipt rebound to another QA run or build-provenance chain element."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_one_iteration(monkeypatch, root, scene_spec_path, run_id)
    session_root = root / "qa" / "convergence" / "audit-session"
    plan = stabilization_service.VisualConvergencePlan.model_validate_json(
        (session_root / "plan.json").read_text(encoding="utf-8")
    )
    receipt_path = session_root / "iterations" / "001" / "receipt.json"
    receipt = stabilization_service.VisualConvergenceIteration.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )

    spliced_build = receipt.model_copy(
        update={"source_build_fingerprint": receipt.result_build_fingerprint}
    )
    with pytest.raises(ValueError, match="build-provenance fingerprint"):
        stabilization_service._verify_convergence_iteration_artifacts(
            root,
            session_root,
            plan,
            spliced_build,
            sha256_file(receipt_path),
        )

    alternate_report, alternate_candidates = _write_qa_run(
        root,
        scene_spec_path,
        run_id="audit-spliced",
        score=receipt.before_direct_score,
        findings=[_finding()],
    )
    spliced_qa = receipt.model_copy(
        update={
            "source_qa_run_id": "audit-spliced",
            "source_qa_report_sha256": sha256_file(alternate_report),
            "candidates_sha256": sha256_file(alternate_candidates),
        }
    )
    with pytest.raises(ValueError, match="selection does not match"):
        stabilization_service._verify_convergence_iteration_artifacts(
            root,
            session_root,
            plan,
            spliced_qa,
            sha256_file(receipt_path),
        )


def test_v09_accepts_failed_iteration_with_result_build_but_no_result_qa(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Audit result-build evidence independently when QA never started."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_failed_after_result_build(
        monkeypatch,
        root,
        scene_spec_path,
        run_id,
    )
    receipt_path = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "iterations"
        / "001"
        / "receipt.json"
    )
    receipt = stabilization_service.VisualConvergenceIteration.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )

    assert receipt.status == "failed"
    assert receipt.result_build_fingerprint is not None
    assert receipt.result_build_provenance_sha256 is not None
    assert receipt.result_qa_run_id is None
    stabilization_service._audit_one_visual_convergence_session(
        root,
        "convergence_audit",
        root / "qa" / "convergence" / "audit-session",
    )
    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-build-only-failure",
    )
    assert audit.status == "passed", audit.jobs[0].model_dump(mode="json")
    assert audit.jobs[0].visual_convergence_status == "valid"


def test_v09_rejects_partial_result_qa_tuple_even_with_valid_result_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep a partial QA identity invalid while accepting independent build evidence."""

    root, scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    _complete_failed_after_result_build(
        monkeypatch,
        root,
        scene_spec_path,
        run_id,
    )
    session_root = root / "qa" / "convergence" / "audit-session"
    plan = stabilization_service.VisualConvergencePlan.model_validate_json(
        (session_root / "plan.json").read_text(encoding="utf-8")
    )
    receipt_path = session_root / "iterations" / "001" / "receipt.json"
    receipt = stabilization_service.VisualConvergenceIteration.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    partial_qa = receipt.model_copy(
        update={"result_qa_run_id": "partial-result-qa"}
    )

    with pytest.raises(ValueError, match="result QA evidence is incomplete"):
        stabilization_service._verify_convergence_iteration_artifacts(
            root,
            session_root,
            plan,
            partial_qa,
            sha256_file(receipt_path),
        )


def test_v09_rejects_host_safety_envelope_tamper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bind the host-derived safety envelope into the authoritative V0.9 audit set."""

    root, _scene_spec_path, run_id = _job(monkeypatch, tmp_path)
    plan_job_visual_convergence(
        "convergence_audit",
        run_id,
        session_id="audit-session",
        target_direct_score=0.8,
        target_silhouette_iou=0.8,
        allowed_target_ids=[TARGET_ID],
        max_iterations=1,
    )
    envelope_path = (
        root
        / "qa"
        / "convergence"
        / "audit-session"
        / "host_safety_envelope.json"
    )
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["max_changed_ids_per_iteration"] = 2
    envelope_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")

    audit = audit_workspace_state(
        job_id="convergence_audit",
        audit_id="audit-convergence-host-safety-tamper",
    )
    assert audit.status == "failed"
    assert audit.jobs[0].visual_convergence_status == "invalid"


def test_v09_legacy_audit_defaults_to_no_convergence_sessions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Preserve legacy audit defaults when a job has no convergence directory evidence."""

    _settings(monkeypatch, tmp_path)
    reference = tmp_path / "legacy.png"
    Image.new("RGB", (16, 16), (100, 100, 100)).save(reference)
    create_job("legacy_audit", reference, "concept", [])
    report = audit_workspace_state(
        job_id="legacy_audit",
        audit_id="audit-legacy-no-convergence",
    )
    assert report.status == "passed"
    assert report.visual_convergence_session_count == 0
    assert report.jobs[0].visual_convergence_status == "not_requested"
    assert report.jobs[0].valid_visual_convergence_session_count == 0
    assert sha256_file(reference)
