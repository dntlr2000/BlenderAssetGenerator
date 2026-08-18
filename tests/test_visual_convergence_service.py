"""Isolated service tests for bounded V0.6 visual-convergence sessions."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.architecture import (
    approve_interior_scope,
    initialize_interior_scope,
)
from codex_blender_modeler.auto_revision.candidate_builder import (
    build_revision_candidates,
)
from codex_blender_modeler.auto_revision.convergence_session import (
    approve_job_visual_convergence,
    cancel_job_visual_convergence,
    get_job_visual_convergence_status,
    plan_job_visual_convergence,
    run_job_visual_convergence,
)
from codex_blender_modeler.auto_revision.convergence_session_models import (
    HashBoundConvergenceArtifact,
    VisualConvergenceApproval,
    VisualConvergenceReportManifest,
)
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.orchestration import plan_workflow
from codex_blender_modeler.orchestration.locks import workflow_write_lock
from codex_blender_modeler.orchestration.models import (
    ArtifactFreshness,
    WorkflowStepCompletion,
)
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.hashing import canonical_model_sha256
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
    StructuralRegressionFinding,
    StructuralRegressionReport,
)
from codex_blender_modeler.workspace import sha256_file

SHA = "0" * 64
TARGET_ID = "demo.profile_house"


def _metrics(
    score: float,
    *,
    silhouette_iou: float | None = None,
) -> DirectVisualMetrics:
    """Build direct metrics with an optional independently controlled silhouette score."""

    return DirectVisualMetrics(
        scoring_version="semantic_bbox_v2",
        silhouette_iou=score if silhouette_iou is None else silhouette_iou,
        silhouette_union_fraction=0.5,
        global_bbox=BoundingBoxMetric(
            reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            rendered_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            center_error_norm=0.0,
            size_error_norm=0.0,
        ),
        overall_direct_score=score,
    )


def _finding(*, confidence: float = 0.95) -> QAFinding:
    """Create one safe directly evidenced edit for the fixture profile object."""

    return QAFinding(
        id="fixture.raise-house",
        target_ids=[TARGET_ID],
        issue_type="position",
        severity="medium",
        description="Raise the profile house within the approved envelope.",
        evidence_sources=["direct_reference"],
        confidence=confidence,
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
    silhouette_iou: float | None = None,
    findings: list[QAFinding],
) -> tuple[Path, Path]:
    """Persist one complete seven-pass QA run and its hash-bound candidate bundle."""

    run_root = root / "qa" / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    pass_root = run_root / "passes"
    pass_root.mkdir()
    camera_sha256 = camera_fingerprint(scene_spec_path)
    pass_records: list[RenderPassRecord] = []
    pass_paths: dict[str, Path] = {}
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
        job_id="convergence_asset",
        run_id=run_id,
        scene_spec_sha256=sha256_file(scene_spec_path),
        camera_fingerprint=camera_sha256,
        build_fingerprint=str(
            collect_build_provenance(root, "convergence_asset")["fingerprint"]
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
    reference_mask.write_bytes(b"fixture-reference-mask")
    request = VisualQARequest(
        job_id="convergence_asset",
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
        job_id="convergence_asset",
        run_id=run_id,
        request_sha256=canonical_model_sha256(request),
        camera_fingerprint=camera_sha256,
        direct_metrics=_metrics(score, silhouette_iou=silhouette_iou),
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


def _write_fast_qa_owner_completion(
    root: Path,
    *,
    workflow_id: str,
    plan_path: Path,
    run_id: str,
) -> Path:
    """Write immutable V0.8 completion evidence proving fast ownership of one QA run."""

    completion = WorkflowStepCompletion(
        completion_id=f"completion-{workflow_id}-qa",
        workflow_id=workflow_id,
        job_id="convergence_asset",
        step_id="qa.run",
        plan_sha256=sha256_file(plan_path),
        input_fingerprint="1" * 64,
        output_fingerprint="2" * 64,
        output_artifacts=[
            ArtifactFreshness(
                artifact_id="qa.run.output",
                path=f"qa/runs/{run_id}",
                sha256="3" * 64,
                integrity="valid",
                currency="current",
                verification="verified",
                reason="Fixture immutable ownership evidence.",
            )
        ],
        note="Fixture fast QA completion.",
        recorded_at="2026-07-30T00:00:00+00:00",
    )
    completion_path = (
        root
        / "workflows"
        / workflow_id
        / "completions"
        / "qa.run.json"
    )
    completion_path.parent.mkdir(parents=True, exist_ok=True)
    completion_path.write_text(
        completion.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return completion_path


def _job_fixture(
    tmp_path: Path,
    monkeypatch,
    *,
    finding_confidence: float = 0.95,
    qa_run_id: str = "run-initial",
    external_geometry: bool = False,
    material_plan: bool = False,
    constraints_present: bool = False,
    interior_target: bool = False,
    spatial_modeling_plan: bool = False,
) -> tuple[Path, Path, str]:
    """Create a complete job and one selectable initial QA run without Blender."""

    workspace = tmp_path / "workspaces"
    root = workspace / "convergence_asset"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    for path in (
        root / "input",
        root / "analysis",
        root / "history",
        root / "qa" / "runs",
        root / "workflows",
    ):
        path.mkdir(parents=True, exist_ok=True)
    reference = root / "input" / "reference.png"
    reference.write_bytes(b"immutable-reference")
    (root / "job.json").write_text(
        json.dumps(
            {
                "job_id": "convergence_asset",
                "mode": "concept",
                "sources": [
                    {
                        "kind": "reference",
                        "path": str(reference),
                        "sha256": sha256_file(reference),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    repository = Path(__file__).resolve().parents[1]
    scene = json.loads(
        (
            repository
            / "examples"
            / "geometry_showcase"
            / "scene_spec.seed.json"
        ).read_text(encoding="utf-8")
    )
    scene["job_id"] = "convergence_asset"
    if interior_target:
        target = next(item for item in scene["objects"] if item["id"] == TARGET_ID)
        target["tags"] = sorted(set(target.get("tags", [])) | {"interior"})
    if external_geometry:
        geometry_root = root / "geometry"
        geometry_root.mkdir(parents=True)
        payload_path = geometry_root / "custom_pyramid.mesh.json"
        custom = next(
            item for item in scene["objects"] if item["id"] == "demo.custom_pyramid"
        )
        geometry = custom["geometry"]
        payload_path.write_text(
            json.dumps(
                {
                    "vertices": geometry["vertices"],
                    "faces": geometry["faces"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        geometry["vertices"] = None
        geometry["faces"] = None
        geometry["path"] = "geometry/custom_pyramid.mesh.json"
    scene_spec_path = root / "analysis" / "scene_spec.json"
    scene_spec_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    if spatial_modeling_plan:
        _write_authored_spatial_modeling_plan(root)
    if interior_target:
        initialize_interior_scope(
            "convergence_asset",
            policy="proxy",
            request="Approve the fixture interior while keeping convergence locked.",
            allowed_semantic_prefixes=[TARGET_ID],
            evidence_status="inferred",
        )
        scope_path = root / "architecture" / "interior_scope.json"
        approve_interior_scope(
            "convergence_asset",
            scope_sha256=sha256_file(scope_path),
            approval_note="Fixture exact interior approval.",
            manual_confirmation=True,
        )
    if material_plan:
        (root / "analysis" / "material_plan.json").write_text(
            json.dumps(
                {
                    "schema_version": "0.5.0",
                    "job_id": "convergence_asset",
                    "scene_spec_path": "analysis/scene_spec.json",
                    "stage": "scaffold",
                    "materials": [
                        {
                            "material_id": item["id"],
                            "label": item["name"],
                            "shader_family": "standard_pbr",
                            "texture_strategy": "none",
                            "mapping": {
                                "mode": "object",
                                "uv_set": "UVMap",
                                "real_world_scale_m": 1.0,
                            },
                            "export_profiles": ["blender_eevee"],
                            "evidence_status": "observed",
                            "confidence": 0.5,
                            "notes": [],
                        }
                        for item in scene["materials"]
                    ],
                    "global_notes": ["fixture material dependency"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    if constraints_present:
        constraints_path = root / "constraints" / "constraints.json"
        constraints_path.parent.mkdir(parents=True)
        constraints_path.write_text(
            json.dumps({"fixture_constraint_contract": 1}, indent=2),
            encoding="utf-8",
        )
    run_id = qa_run_id
    _write_qa_run(
        root,
        scene_spec_path,
        run_id=run_id,
        score=0.6,
        findings=[_finding(confidence=finding_confidence)],
    )
    return root, scene_spec_path, run_id


def _write_authored_spatial_modeling_plan(root: Path) -> Path:
    """Write one valid authored spatial plan covering every fixture SceneSpec object."""

    scene = json.loads(
        (root / "analysis" / "scene_spec.json").read_text(encoding="utf-8")
    )
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    modeling_plan_path.write_text(
        json.dumps(
            {
                "job_id": "convergence_asset",
                "reference_analysis_path": "analysis/reference_analysis.json",
                "camera_solution_path": "analysis/camera_solution.json",
                "stage": "authored",
                "objects": [
                    {
                        "id": item["id"],
                        "label": item["id"],
                        "scope_role": (
                            "primary" if item["id"] == TARGET_ID else "supporting"
                        ),
                        "assembly_role": (
                            "root" if item["id"] == TARGET_ID else "free_standing"
                        ),
                    }
                    for item in scene["objects"]
                ],
                "assembly_consistency_policy": "spatial_v1",
                "assembly_frame": {
                    "root_object_id": TARGET_ID,
                    "longitudinal_axis": "X",
                    "lateral_axis": "Y",
                    "vertical_axis": "Z",
                    "evidence_status": "authored",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return modeling_plan_path


def _structural_evidence(run_id: str, digit: str) -> AssemblySanityTerminalEvidence:
    """Create one path-valid exact-hash five-view binding for service-level tests."""

    run_root = f"qa/assembly_sanity/runs/{run_id}"
    return AssemblySanityTerminalEvidence(
        run_id=run_id,
        plan_path=f"{run_root}/plan.json",
        plan_sha256=digit * 64,
        render_manifest_path=f"{run_root}/render_manifest.json",
        render_manifest_sha256=str((int(digit) + 1) % 10) * 64,
        report_path=f"{run_root}/report.json",
        report_sha256=str((int(digit) + 2) % 10) * 64,
    )


def _fake_pdf(root: Path):
    """Return a PDF writer stub that preserves terminal report service semantics."""

    def generate(
        job_id: str,
        session_id: str,
        *,
        report_relative_path: str | None = None,
        source_relative_paths=(),
    ) -> dict[str, Any]:
        """Write small immutable PDF placeholders for service-only tests."""

        del report_relative_path
        assert job_id == "convergence_asset"
        session_root = root / "qa" / "convergence" / session_id
        pdf = session_root / "convergence_report.pdf"
        manifest = session_root / "convergence_report.manifest.json"
        pdf.write_bytes(b"%PDF-test")
        report = session_root / "convergence_report.json"
        report_artifact = HashBoundConvergenceArtifact(
            relative_path=report.relative_to(root).as_posix(),
            sha256=sha256_file(report),
        )
        source_artifacts = [report_artifact]
        for relative_path in source_relative_paths:
            source_path = root / Path(*relative_path.split("/"))
            artifact = HashBoundConvergenceArtifact(
                relative_path=relative_path,
                sha256=sha256_file(source_path),
            )
            if artifact.relative_path not in {
                item.relative_path for item in source_artifacts
            }:
                source_artifacts.append(artifact)
        sidecar = VisualConvergenceReportManifest(
            session_id=session_id,
            job_id=job_id,
            source_fingerprint=hashlib.sha256(
                json.dumps(
                    [
                        {
                            "relative_path": artifact.relative_path,
                            "sha256": artifact.sha256,
                        }
                        for artifact in source_artifacts
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest(),
            report_json=report_artifact,
            pdf=HashBoundConvergenceArtifact(
                relative_path=pdf.relative_to(root).as_posix(),
                sha256=sha256_file(pdf),
            ),
            sources=source_artifacts,
            generated_at="2026-07-30T00:00:00+00:00",
        )
        manifest.write_text(sidecar.model_dump_json(indent=2), encoding="utf-8")
        return {"pdf": str(pdf), "manifest": str(manifest)}

    return generate


def _pipeline(scene_spec_path: Path, *, constraint_failures: list[int] | None = None):
    """Return a deterministic derived pipeline and a record of canonical heights."""

    heights: list[float] = []
    failures = list(constraint_failures or [])

    def run(
        job_id: str,
        root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Record the active canonical edit and return validated derived evidence."""

        assert job_id == "convergence_asset"
        assert render_engine == "eevee"
        assert render_device == "auto"
        raw = json.loads(scene_spec_path.read_text(encoding="utf-8"))
        target = next(item for item in raw["objects"] if item["id"] == TARGET_ID)
        heights.append(float(target["transform"]["location"][2]))
        failed = failures.pop(0) if failures else 0
        results = (
            [
                {
                    "id": "fixture.constraint",
                    "kind": "dimension",
                    "status": "failed",
                    "requested": 1.0,
                    "actual": 1.2,
                    "residual_m": 0.2,
                    "tolerance_m": 0.1,
                    "message": "fixture regression",
                }
            ]
            if failed
            else []
        )
        return {
            "build": {"blend": str(root / "blender" / "scene.blend")},
            "preview": {"preview": str(root / "renders" / "preview.png")},
            "inventory_path": str(root / "reports" / "scene_inventory.json"),
            "object_count": len(raw["objects"]),
            "validation": {"ok": True, "errors": [], "warnings": []},
            "validation_path": str(root / "reports" / "validation.json"),
            "constraint_solution_path": None,
            "constraint_failures": failed,
            "constraint_results": results,
        }

    return run, heights


def _install_pipeline_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    convergence_pipeline: Any,
    rollback_pipeline: Any,
) -> dict[str, int]:
    """Install separate deterministic main and rollback pipelines without Blender."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    calls = {"convergence": 0, "rollback": 0}

    def run_convergence(
        job_id: str,
        root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Route the active convergence build through its selected test pipeline."""

        calls["convergence"] += 1
        return convergence_pipeline(job_id, root, render_engine, render_device)

    def run_rollback(
        job_id: str,
        root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Route the restored-baseline rebuild through its selected test pipeline."""

        calls["rollback"] += 1
        return rollback_pipeline(job_id, root, render_engine, render_device)

    def reject_blender(*_args: Any, **_kwargs: Any) -> None:
        """Fail immediately if a non-Blender unit test escapes into Blender."""

        raise AssertionError("non-Blender pipeline fixture invoked run_blender")

    monkeypatch.setattr(convergence_session, "_run_job_pipeline", run_convergence)
    monkeypatch.setattr(service, "_run_job_pipeline", run_rollback)
    monkeypatch.setattr(service, "run_blender", reject_blender)
    return calls


def _post_qa_sequence(
    root: Path,
    scene_spec_path: Path,
    scores: list[float],
) -> Any:
    """Return a named QA stub that emits fresh candidates for every accepted iteration."""

    queued = list(scores)

    def run(
        job_id: str,
        render_engine: str,
        render_device: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist the next exact QA run while keeping the fixed comparison camera."""

        assert job_id == "convergence_asset"
        assert run_id is not None
        score = queued.pop(0)
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


def _plan_and_approve(
    initial_run_id: str,
    *,
    target: float,
    max_iterations: int = 3,
    minimum_confidence: float = 0.8,
) -> tuple[str, str]:
    """Create and explicitly activate one exact fixture convergence plan."""

    planned = plan_job_visual_convergence(
        "convergence_asset",
        initial_run_id,
        session_id="session-fixture",
        target_direct_score=target,
        target_silhouette_iou=target,
        allowed_target_ids=[TARGET_ID],
        max_iterations=max_iterations,
        minimum_candidate_confidence=minimum_confidence,
    )
    approved = approve_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve only the exact bounded fixture envelope.",
    )
    return planned["plan_sha256"], approved["approval_sha256"]


def _run_one_accepted_session(
    root: Path,
    scene_spec_path: Path,
    initial_run_id: str,
    monkeypatch,
    *,
    result_score: float = 0.72,
) -> dict[str, Any]:
    """Execute one accepted fixture iteration and write terminal evidence."""

    from codex_blender_modeler.auto_revision import convergence_session

    _plan_and_approve(initial_run_id, target=0.7, max_iterations=1)
    pipeline, _heights = _pipeline(scene_spec_path)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec_path, [result_score]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    return run_job_visual_convergence("convergence_asset", "session-fixture")


def _remove_terminal_projection(session_root: Path) -> None:
    """Remove only terminal projection files so an accepted-chain audit can be isolated."""

    for name in (
        "convergence_report.json",
        "final_scene_spec.json",
        "final_build_provenance.json",
        "convergence_report.pdf",
        "convergence_report.manifest.json",
    ):
        path = session_root / name
        if path.exists():
            path.unlink()


def test_plan_is_canonical_read_only_and_requires_exact_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Planning writes only session evidence and an incorrect hash cannot activate it."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    scene_hash = sha256_file(scene_spec)
    input_hash = sha256_file(root / "input" / "reference.png")
    planned = plan_job_visual_convergence(
        "convergence_asset",
        run_id,
        session_id="session-fixture",
        target_direct_score=0.8,
        target_silhouette_iou=0.8,
        allowed_target_ids=[TARGET_ID],
    )
    assert planned["status"] == "waiting_for_exact_approval"
    assert planned["canonical_modified"] is False
    assert planned["host_safety_envelope_sha256"]
    assert Path(planned["host_safety_envelope"]).is_file()
    assert planned["minimum_iteration_gain"] == pytest.approx(0.001)
    assert planned["minimum_candidate_confidence"] == pytest.approx(0.8)
    assert planned["max_candidate_groups_per_iteration"] == 3
    assert planned["max_candidates_per_iteration"] == 12
    assert planned["max_changed_ids_per_iteration"] == 6
    assert planned["path_limits"]
    assert sha256_file(scene_spec) == scene_hash
    assert sha256_file(root / "input" / "reference.png") == input_hash
    with pytest.raises(ValueError, match="exact plan SHA-256"):
        approve_job_visual_convergence(
            "convergence_asset",
            "session-fixture",
            plan_sha256="f" * 64,
            approval_note="Wrong plan.",
        )


def test_plan_binds_authored_spatial_asset_to_exact_five_view_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Planning accepts spatial assets only with one exact five-view baseline."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        spatial_modeling_plan=True,
    )
    scene_sha256 = sha256_file(scene_spec)
    evidence = AssemblySanityTerminalEvidence(
        run_id="conv-session-spatial-initial",
        plan_path=(
            "qa/assembly_sanity/runs/conv-session-spatial-initial/plan.json"
        ),
        plan_sha256="1" * 64,
        render_manifest_path=(
            "qa/assembly_sanity/runs/conv-session-spatial-initial/"
            "render_manifest.json"
        ),
        render_manifest_sha256="2" * 64,
        report_path=(
            "qa/assembly_sanity/runs/conv-session-spatial-initial/report.json"
        ),
        report_sha256="3" * 64,
    )
    monkeypatch.setattr(
        convergence_session,
        "_capture_convergence_structural_terminal",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(
        convergence_session,
        "_structural_terminal_artifacts",
        lambda *_args, **_kwargs: [],
    )
    planned = plan_job_visual_convergence(
        "convergence_asset",
        run_id,
        session_id="session-spatial",
        target_direct_score=0.8,
        target_silhouette_iou=0.8,
        allowed_target_ids=[TARGET_ID],
    )
    approved = approve_job_visual_convergence(
        "convergence_asset",
        "session-spatial",
        plan_sha256=planned["plan_sha256"],
        approval_note="Approve the exact spatial five-view convergence baseline.",
    )

    assert planned["structural_multiview_policy"] == "spatial_v1_required"
    assert planned["initial_structural_evidence"] == evidence.model_dump(mode="json")
    assert approved["status"] == "approved_bounded_session"
    assert sha256_file(scene_spec) == scene_sha256


def test_run_rechecks_authored_spatial_policy_for_existing_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An older approved plan cannot begin after its job becomes authored spatial_v1."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    scene_sha256 = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    _write_authored_spatial_modeling_plan(root)
    iteration_root = (
        root / "qa" / "convergence" / "session-fixture" / "iterations"
    )

    with pytest.raises(
        ValueError,
        match="canonical build inputs|host safety envelope",
    ):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert not iteration_root.exists()
    assert sha256_file(scene_spec) == scene_sha256


@pytest.mark.parametrize(
    ("structural_status", "expected_iteration_status", "termination_reason"),
    [
        ("passed", "accepted", "target_reached"),
        ("regressed", "rolled_back", "structural_regression"),
    ],
)
def test_spatial_iteration_uses_five_view_result_as_acceptance_veto(
    tmp_path: Path,
    monkeypatch,
    structural_status: str,
    expected_iteration_status: str,
    termination_reason: str,
) -> None:
    """Accept visual gains only when exact five-view structural evidence does not regress."""

    from codex_blender_modeler.auto_revision import convergence, convergence_session

    root, scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        spatial_modeling_plan=True,
    )
    baseline_sha256 = sha256_file(scene_spec)
    baseline = _structural_evidence("conv-fixture-initial", "1")
    result_evidence = _structural_evidence("conv-fixture-result", "4")
    captures = iter([baseline, result_evidence])
    comparison_result_sha256: list[str] = []

    monkeypatch.setattr(
        convergence_session,
        "_capture_convergence_structural_terminal",
        lambda *_args, **_kwargs: next(captures),
    )
    monkeypatch.setattr(
        convergence_session,
        "_structural_terminal_artifacts",
        lambda *_args, **_kwargs: [],
    )

    def compare(
        _root: Path,
        *,
        baseline: AssemblySanityTerminalEvidence,
        result: AssemblySanityTerminalEvidence,
        expected_job_id: str | None = None,
        generated_at: datetime | None = None,
    ) -> StructuralRegressionReport:
        """Return a stable comparison fixture while preserving the recorded timestamp."""

        assert expected_job_id == "convergence_asset"
        if not comparison_result_sha256:
            comparison_result_sha256.append(sha256_file(scene_spec))
        regressions = (
            [
                StructuralRegressionFinding(
                    id="structural.fixture_regression",
                    category="structural_status",
                    before="passed",
                    after="failed",
                    message="Fixture five-view structure regressed.",
                )
            ]
            if structural_status == "regressed"
            else []
        )
        return StructuralRegressionReport(
            job_id="convergence_asset",
            status=structural_status,
            baseline=baseline,
            result=result,
            baseline_scene_spec_sha256=baseline_sha256,
            result_scene_spec_sha256=comparison_result_sha256[0],
            modeling_plan_sha256=sha256_file(
                root / "analysis" / "modeling_plan.json"
            ),
            regressions=regressions,
            generated_at=generated_at or datetime(2026, 8, 1, tzinfo=UTC),
        )

    monkeypatch.setattr(
        convergence_session,
        "compare_assembly_sanity_terminals",
        compare,
    )
    monkeypatch.setattr(
        convergence,
        "compare_assembly_sanity_terminals",
        compare,
    )
    _plan_and_approve(run_id, target=0.7, max_iterations=1)
    pipeline, _heights = _pipeline(scene_spec)
    pipeline_calls = _install_pipeline_stubs(
        monkeypatch,
        convergence_pipeline=pipeline,
        rollback_pipeline=pipeline,
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.72]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    result = run_job_visual_convergence("convergence_asset", "session-fixture")
    receipt_path = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == expected_iteration_status, json.dumps(
        result,
        indent=2,
        default=str,
    )
    assert receipt["structural_multiview_status"] == structural_status
    assert result["termination_reason"] == termination_reason
    assert pipeline_calls == {
        "convergence": 1,
        "rollback": 1 if structural_status == "regressed" else 0,
    }
    assert sha256_file(scene_spec) == (
        comparison_result_sha256[0]
        if structural_status == "passed"
        else baseline_sha256
    )


def test_approved_interior_objects_remain_locked_out_of_convergence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An exact InteriorScope approval never grants automatic geometry authority."""

    root, _scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        interior_target=True,
    )
    planned = plan_job_visual_convergence(
        "convergence_asset",
        run_id,
        session_id="session-interior-default",
        target_direct_score=0.8,
        target_silhouette_iou=0.8,
    )
    plan = json.loads(Path(planned["plan"]).read_text(encoding="utf-8"))
    assert TARGET_ID not in plan["allowed_target_ids"]
    assert TARGET_ID in plan["locked_target_ids"]
    envelope = json.loads(
        (
            root
            / "qa"
            / "convergence"
            / "session-interior-default"
            / "host_safety_envelope.json"
        ).read_text(encoding="utf-8")
    )
    assert TARGET_ID in envelope["interior_target_ids"]

    with pytest.raises(ValueError, match="never edits InteriorScope-classified"):
        plan_job_visual_convergence(
            "convergence_asset",
            run_id,
            session_id="session-interior-explicit",
            target_direct_score=0.8,
            target_silhouette_iou=0.8,
            allowed_target_ids=[TARGET_ID],
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "material",
        "allowed_ids",
        "custom_mesh",
        "path_limit",
        "candidate_budget",
    ],
)
def test_approval_rejects_user_relaxed_host_safety_plan(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    """Exact hash approval still rejects a plan broadened beyond host-derived policy."""

    root, _scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    planned = plan_job_visual_convergence(
        "convergence_asset",
        run_id,
        session_id="session-fixture",
        target_direct_score=0.8,
        target_silhouette_iou=0.8,
        allowed_target_ids=[TARGET_ID],
    )
    plan_path = Path(planned["plan"])
    raw = json.loads(plan_path.read_text(encoding="utf-8"))
    if mutation == "material":
        raw["allow_material_edits"] = True
        raw["path_limits"].append(
            {
                "path_family": "material.roughness",
                "allowed_operations": ["set"],
                "max_absolute_delta": 0.1,
                "max_relative_delta": None,
            }
        )
    elif mutation == "allowed_ids":
        added = next(
            item
            for item in raw["locked_target_ids"]
            if not item.startswith("mat.")
        )
        raw["allowed_target_ids"].append(added)
        raw["allowed_target_ids"].sort()
        raw["locked_target_ids"].remove(added)
    elif mutation == "custom_mesh":
        raw["custom_mesh_target_ids"] = []
    elif mutation == "path_limit":
        raw["path_limits"][0]["max_absolute_delta"] *= 10.0
    else:
        raw["max_candidates_per_iteration"] += 1
    plan_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="host-derived envelope"):
        approve_job_visual_convergence(
            "convergence_asset",
            "session-fixture",
            plan_sha256=sha256_file(plan_path),
            approval_note="Attempt to approve an edited plan.",
        )
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "approval.json"
    ).exists()


def test_run_rechecks_exact_host_safety_envelope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Execution fails closed when the approved host envelope changes afterward."""

    root, _scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8)
    envelope_path = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "host_safety_envelope.json"
    )
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["max_candidates_per_iteration"] += 1
    envelope_path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="host safety envelope"):
        run_job_visual_convergence("convergence_asset", "session-fixture")


def test_legacy_partial_plan_is_status_readable_but_cannot_approve_or_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Historical plans without new source bindings remain inspectable but non-executable."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    planned = plan_job_visual_convergence(
        "convergence_asset",
        run_id,
        session_id="session-fixture",
        target_direct_score=0.8,
        target_silhouette_iou=0.8,
        allowed_target_ids=[TARGET_ID],
    )
    session_root = root / "qa" / "convergence" / "session-fixture"
    plan_path = session_root / "plan.json"
    legacy_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for field in (
        "initial_input_hashes",
        "initial_candidates_sha256",
            "initial_build_fingerprint",
            "initial_build_provenance_sha256",
            "host_safety_envelope_sha256",
            "initial_constraints_present",
        "initial_constraints_sha256",
    ):
        legacy_plan.pop(field, None)
    plan_path.write_text(json.dumps(legacy_plan, indent=2), encoding="utf-8")
    legacy_plan_sha256 = sha256_file(plan_path)

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["status"] == "waiting_for_exact_approval"
    assert status["integrity"] == "current"
    assert status["status_only_legacy"] is True
    assert status["execution_eligible"] is False
    assert "initial_input_hashes" in status["execution_binding_gaps"]
    assert status["execution_block_reason"].startswith(
        "legacy_status_only_missing_bindings:"
    )
    assert status["next_action"] is None

    with pytest.raises(ValueError, match="status-only"):
        approve_job_visual_convergence(
            "convergence_asset",
            "session-fixture",
            plan_sha256=legacy_plan_sha256,
            approval_note="A legacy partial plan must not gain execution authority.",
        )

    approval = VisualConvergenceApproval(
        approval_id="approval-legacy-fixture",
        session_id="session-fixture",
        job_id="convergence_asset",
        plan_sha256=legacy_plan_sha256,
        input_fingerprint=legacy_plan["input_fingerprint"],
        initial_scene_spec_sha256=legacy_plan["initial_scene_spec_sha256"],
        initial_qa_report_sha256=legacy_plan["initial_qa_report_sha256"],
        camera_fingerprint=legacy_plan["camera_fingerprint"],
        approval_note="Historical fixture approval without executable bindings.",
        approved_at="2026-07-30T00:00:00+00:00",
    )
    (session_root / "approval.json").write_text(
        approval.model_dump_json(indent=2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="status-only"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_hash
    assert planned["plan_sha256"] != legacy_plan_sha256
    assert not (session_root / "iterations").exists()


def test_two_accepted_iterations_reach_target_with_one_user_approval(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """One plan approval authorizes two improving host-policy iterations."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    pipeline, heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.7, 0.82]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    first = run_job_visual_convergence("convergence_asset", "session-fixture")
    assert first["execution_outcome"] == "iteration_completed"
    assert first["iterations_executed_this_invocation"] == 1
    assert first["host_step_iteration_limit"] == 1
    assert first["iteration_count"] == 1
    assert first["next_action"] == "invoke_run_again"
    active_status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert active_status["execution_eligible"] is True
    assert active_status["status_only_legacy"] is False
    assert active_status["execution_block_reason"] is None
    assert active_status["next_action"] == "invoke_run_again"

    result = run_job_visual_convergence("convergence_asset", "session-fixture")

    assert result["termination_reason"] == "target_reached"
    assert result["accepted_iterations"] == 2
    assert result["rolled_back_iterations"] == 0
    assert sha256_file(scene_spec) != before_hash
    assert len(heights) == 2
    receipts = sorted(
        (root / "qa" / "convergence" / "session-fixture" / "iterations").glob(
            "*/receipt.json"
        )
    )
    assert len(receipts) == 2
    second = json.loads(receipts[1].read_text(encoding="utf-8"))
    assert second["previous_iteration_receipt_sha256"] == sha256_file(receipts[0])
    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["integrity"] == "current"
    assert status["target_reached"] is True


def test_non_improving_iteration_rolls_back_and_ends_plateau(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A sub-threshold result restores canonical state and stops the bounded session."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    pipeline, heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.6005]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    result = run_job_visual_convergence("convergence_asset", "session-fixture")

    assert result["termination_reason"] == "plateau"
    assert result["rolled_back_iterations"] == 1
    assert sha256_file(scene_spec) == before_hash
    assert len(heights) == 2
    receipt = json.loads(
        (
            root
            / "qa"
            / "convergence"
            / "session-fixture"
            / "iterations"
            / "001"
            / "receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["status"] == "rolled_back"


def test_low_confidence_candidate_finishes_without_canonical_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An empty safe selection terminates for review without applying any edit."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        finding_confidence=0.5,
    )
    before_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, minimum_confidence=0.8)
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    result = run_job_visual_convergence("convergence_asset", "session-fixture")

    assert result["termination_reason"] == "no_eligible_candidates"
    assert result["manual_review_required"] is True
    assert sha256_file(scene_spec) == before_hash


def test_iteration_budget_stops_after_only_the_approved_count(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Accepted improvements cannot exceed the plan's exact iteration budget."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.95, max_iterations=2)
    pipeline, _heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.7, 0.8]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    first = run_job_visual_convergence("convergence_asset", "session-fixture")
    assert first["execution_outcome"] == "iteration_completed"
    assert first["iteration_count"] == 1

    result = run_job_visual_convergence("convergence_asset", "session-fixture")

    assert result["termination_reason"] == "iteration_budget_exhausted"
    assert result["accepted_iterations"] == 2
    assert result["target_reached"] is False


def test_constraint_regression_rolls_back_despite_visual_gain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A new measured failure overrides a higher direct-reference score."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    pipeline, _heights = _pipeline(scene_spec, constraint_failures=[1, 0])
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.8]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    result = run_job_visual_convergence("convergence_asset", "session-fixture")

    assert result["termination_reason"] == "constraint_regression"
    assert sha256_file(scene_spec) == before_hash
    receipt = json.loads(
        (
            root
            / "qa"
            / "convergence"
            / "session-fixture"
            / "iterations"
            / "001"
            / "receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["constraint_regression_count"] == 1
    assert receipt["status"] == "rolled_back"


@pytest.mark.parametrize("predicate", ["minimum_gain", "silhouette_non_regression"])
def test_rewritten_accepted_receipt_cannot_bypass_runtime_acceptance_predicates(
    tmp_path: Path,
    monkeypatch,
    predicate: str,
) -> None:
    """Core status and run recompute score and silhouette predicates from exact QA."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, max_iterations=1)
    pipeline, _heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    if predicate == "minimum_gain":
        post_qa = _post_qa_sequence(root, scene_spec, [0.6005])
    else:

        def post_qa(
            job_id: str,
            render_engine: str,
            render_device: str,
            run_id: str | None = None,
        ) -> dict[str, Any]:
            """Emit direct-score gain with a regressing exact silhouette metric."""

            del render_engine, render_device
            assert job_id == "convergence_asset"
            assert run_id is not None
            report_path, candidates_path = _write_qa_run(
                root,
                scene_spec,
                run_id=run_id,
                score=0.72,
                silhouette_iou=0.55,
                findings=[_finding()],
            )
            return {
                "ok": True,
                "job_id": job_id,
                "run_id": run_id,
                "visual_qa_report": str(report_path),
                "revision_candidates": str(candidates_path),
                "direct_score": 0.72,
            }

    monkeypatch.setattr(convergence_session, "_run_post_visual_qa", post_qa)
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    result = run_job_visual_convergence("convergence_asset", "session-fixture")
    assert result["termination_reason"] == "plateau"
    assert sha256_file(scene_spec) == baseline_hash

    session_root = root / "qa" / "convergence" / "session-fixture"
    _remove_terminal_projection(session_root)
    receipt_path = session_root / "iterations" / "001" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "accepted"
    receipt["canonical_scene_spec_sha256"] = receipt["result_scene_spec_sha256"]
    receipt["constraint_regression_count"] = 0
    receipt["reason_codes"] = ["improved"]
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    result_snapshot = session_root / "iterations" / "001" / "result_scene_spec.json"
    scene_spec.write_bytes(result_snapshot.read_bytes())
    rewritten_canonical_hash = sha256_file(scene_spec)

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["integrity"] == "stale_or_tampered"
    assert "contradicts recomputed" in status["integrity_error"]
    with pytest.raises(ValueError, match="contradicts recomputed"):
        run_job_visual_convergence("convergence_asset", "session-fixture")
    assert rewritten_canonical_hash != baseline_hash
    assert sha256_file(scene_spec) == rewritten_canonical_hash


def test_scene_tampering_after_approval_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A changed canonical SceneSpec cannot consume bounded session authority."""

    _root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8)
    payload = json.loads(scene_spec.read_text(encoding="utf-8"))
    payload["revision_notes"].append("unplanned mutation")
    scene_spec.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="receipt chain"):
        run_job_visual_convergence("convergence_asset", "session-fixture")


def test_initial_candidates_tampering_after_approval_blocks_before_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a changed approved candidate bundle before creating an iteration."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    candidates = root / "qa" / "runs" / run_id / "revision_candidates.json"
    candidates.write_text(
        candidates.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="candidates changed"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_hash
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
    ).exists()


@pytest.mark.parametrize("source_kind", ["geometry", "material"])
def test_canonical_build_source_tampering_blocks_before_mutation(
    tmp_path: Path,
    monkeypatch,
    source_kind: str,
) -> None:
    """Bind external geometry and material-plan sources to the approved build."""

    root, scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        external_geometry=source_kind == "geometry",
        material_plan=source_kind == "material",
    )
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    if source_kind == "geometry":
        dependency = root / "geometry" / "custom_pyramid.mesh.json"
        payload = json.loads(dependency.read_text(encoding="utf-8"))
        payload["vertices"][0][0] = -1.25
    else:
        dependency = root / "analysis" / "material_plan.json"
        payload = json.loads(dependency.read_text(encoding="utf-8"))
        payload["global_notes"].append("unplanned material-plan change")
    dependency.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="build inputs changed"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_hash
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
    ).exists()


def test_build_contract_change_between_iteration_check_and_promotion_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Recheck external build inputs after candidate compilation and before CAS promotion."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        external_geometry=True,
    )
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    original_apply = convergence_session._apply_iteration_authorization

    def apply_then_tamper(**kwargs: Any) -> dict[str, Any]:
        """Change one external geometry input after the initial active-state check."""

        result = original_apply(**kwargs)
        dependency = root / "geometry" / "custom_pyramid.mesh.json"
        payload = json.loads(dependency.read_text(encoding="utf-8"))
        payload["vertices"][0][0] = -1.125
        dependency.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return result

    monkeypatch.setattr(
        convergence_session,
        "_apply_iteration_authorization",
        apply_then_tamper,
    )

    with pytest.raises(
        RuntimeError,
        match="source build provenance|build inputs",
    ):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_hash
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    ).exists()


def test_build_contract_change_during_pipeline_rolls_back_canonical_scene(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Restore canonical geometry when a pipeline mutates another build-contract source."""

    root, scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        material_plan=True,
    )
    baseline_hash = sha256_file(scene_spec)
    material_plan = root / "analysis" / "material_plan.json"
    baseline_material_hash = sha256_file(material_plan)
    _plan_and_approve(run_id, target=0.8)
    base_pipeline, _heights = _pipeline(scene_spec)

    def tampering_pipeline(
        job_id: str,
        job_root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Mutate the material contract only after convergence promoted its candidate."""

        result = base_pipeline(job_id, job_root, render_engine, render_device)
        dependency = root / "analysis" / "material_plan.json"
        payload = json.loads(dependency.read_text(encoding="utf-8"))
        payload["global_notes"].append("mid-pipeline external material mutation")
        dependency.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return result

    pipeline_calls = _install_pipeline_stubs(
        monkeypatch,
        convergence_pipeline=tampering_pipeline,
        rollback_pipeline=base_pipeline,
    )

    with pytest.raises(
        RuntimeError,
        match="source build provenance|build inputs",
    ):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_hash
    assert pipeline_calls == {"convergence": 1, "rollback": 1}
    assert sha256_file(material_plan) != baseline_material_hash
    assert "mid-pipeline external material mutation" in json.loads(
        material_plan.read_text(encoding="utf-8")
    )["global_notes"]
    rollback = json.loads(
        (
            root
            / "qa"
            / "convergence"
            / "session-fixture"
            / "staging"
            / "001"
            / "rollback_report.json"
        ).read_text(encoding="utf-8")
    )
    assert rollback["rollback_ok"] is True
    assert rollback["status"] == "restored"
    assert rollback["restored_scene_spec_sha256"] == baseline_hash
    assert rollback["expected_scene_spec_sha256"] == baseline_hash
    assert rollback["input_hashes_unchanged"] is True
    assert rollback["rebuild_requested"] is True
    assert rollback["rebuild_error"] is None
    assert "build inputs changed" in rollback["reason"]
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    ).exists()


def test_rollback_rebuild_failure_remains_restore_incomplete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a canonical rollback whose restored-baseline rebuild still fails."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    base_pipeline, _heights = _pipeline(scene_spec)

    def failing_convergence_pipeline(
        job_id: str,
        job_root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Fail after the promoted candidate has entered the derived pipeline."""

        base_pipeline(job_id, job_root, render_engine, render_device)
        raise RuntimeError("mock convergence pipeline failure")

    def failing_rollback_pipeline(
        _job_id: str,
        _job_root: Path,
        _render_engine: str,
        _render_device: str,
    ) -> dict[str, Any]:
        """Simulate a genuine restored-baseline rebuild failure."""

        raise RuntimeError("mock rollback rebuild failure")

    pipeline_calls = _install_pipeline_stubs(
        monkeypatch,
        convergence_pipeline=failing_convergence_pipeline,
        rollback_pipeline=failing_rollback_pipeline,
    )

    with pytest.raises(
        RuntimeError,
        match="rollback did not fully restore and rebuild the baseline",
    ):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    rollback = json.loads(
        (
            root
            / "qa"
            / "convergence"
            / "session-fixture"
            / "staging"
            / "001"
            / "rollback_report.json"
        ).read_text(encoding="utf-8")
    )
    assert pipeline_calls == {"convergence": 1, "rollback": 1}
    assert sha256_file(scene_spec) == baseline_hash
    assert rollback["rollback_ok"] is False
    assert rollback["status"] == "restore_incomplete"
    assert rollback["restored_scene_spec_sha256"] == baseline_hash
    assert rollback["expected_scene_spec_sha256"] == baseline_hash
    assert rollback["input_hashes_unchanged"] is True
    assert rollback["rebuild_requested"] is True
    assert rollback["rebuild_error"] == "RuntimeError: mock rollback rebuild failure"
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    ).exists()


@pytest.mark.parametrize("mutation", ["create", "delete", "change"])
def test_constraint_contract_presence_and_hash_are_approval_bound(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    """Reject creation, deletion, or replacement of measured constraints after approval."""

    root, scene_spec, run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        constraints_present=mutation in {"delete", "change"},
    )
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    constraints = root / "constraints" / "constraints.json"
    if mutation == "create":
        constraints.parent.mkdir(parents=True)
        constraints.write_text('{"fixture_constraint_contract":2}', encoding="utf-8")
    elif mutation == "delete":
        constraints.unlink()
    else:
        constraints.write_text('{"fixture_constraint_contract":2}', encoding="utf-8")

    with pytest.raises(ValueError, match="constraint contract changed"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_hash
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
    ).exists()


def test_terminal_receipt_tampering_is_machine_detected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A changed historical receipt makes status fail closed without rewriting it."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.7, max_iterations=1)
    pipeline, _heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.72]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    run_job_visual_convergence("convergence_asset", "session-fixture")
    receipt_path = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["reason_codes"].append("tampered")
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["ok"] is False
    assert status["integrity"] == "stale_or_tampered"


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("source_qa_run_id", "run-spliced", "source QA chain"),
        ("candidates_sha256", "f" * 64, "source candidates chain"),
        ("source_build_fingerprint", "e" * 64, "source build chain"),
    ],
)
def test_core_rejects_spliced_second_receipt_source_chain(
    tmp_path: Path,
    monkeypatch,
    field: str,
    replacement: str,
    message: str,
) -> None:
    """Status and run reject a model-valid splice in the second iteration lineage."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8)
    pipeline, _heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.7, 0.82]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    run_job_visual_convergence("convergence_asset", "session-fixture")
    run_job_visual_convergence("convergence_asset", "session-fixture")
    canonical_hash = sha256_file(scene_spec)
    session_root = root / "qa" / "convergence" / "session-fixture"
    _remove_terminal_projection(session_root)
    receipt_path = session_root / "iterations" / "002" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt[field] = replacement
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["integrity"] == "stale_or_tampered"
    assert message in status["integrity_error"]
    with pytest.raises(ValueError, match=message):
        run_job_visual_convergence("convergence_asset", "session-fixture")
    assert sha256_file(scene_spec) == canonical_hash


def test_approved_session_can_be_cancelled_without_editing_scene(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Cancellation writes terminal evidence and leaves authoring data untouched."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    result = cancel_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
        reason="Stop before any automatic iteration.",
    )

    assert result["termination_reason"] == "cancelled"
    assert sha256_file(scene_spec) == before_hash
    snapshot = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "final_scene_spec.json"
    )
    assert sha256_file(snapshot) == before_hash


def test_cancellation_requires_receiptless_staging_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Refuse to consume cancellation authority while an iteration needs recovery."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    session_root = root / "qa" / "convergence" / "session-fixture"
    (session_root / "staging" / "001").mkdir(parents=True)

    with pytest.raises(
        RuntimeError,
        match="invoke the convergence run once to recover",
    ):
        cancel_job_visual_convergence(
            "convergence_asset",
            "session-fixture",
            reason="Cancel only after the interrupted attempt is recovered.",
        )

    assert sha256_file(scene_spec) == before_hash
    assert not (session_root / "cancellation_receipt.json").exists()
    assert not (session_root / "convergence_report.json").exists()
    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["ok"] is True
    assert status["status"] == "recovery_required"
    assert status["next_action"] == "invoke_run_to_recover"


def test_terminal_session_rejects_late_receiptless_staging(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Classify terminal evidence plus receipt-less staging as an integrity conflict."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, _scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8)
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    cancel_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
        reason="Create one legitimate terminal cancellation fixture.",
    )
    session_root = root / "qa" / "convergence" / "session-fixture"
    (session_root / "staging" / "001").mkdir(parents=True)

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["ok"] is False
    assert status["status"] == "invalid_terminal"
    assert status["integrity"] == "stale_or_tampered"
    assert "conflicts with receipt-less iteration staging" in status["integrity_error"]
    assert status["next_action"] is None


def test_cancellation_receipt_prevents_replay_after_terminal_report_deletion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Keep consumed cancellation authority closed even when terminal JSON is deleted."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    cancel_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
        reason="Consume the exact fixture approval.",
    )
    session_root = root / "qa" / "convergence" / "session-fixture"
    assert (session_root / "cancellation_receipt.json").is_file()
    (session_root / "convergence_report.json").unlink()
    for name in (
        "final_scene_spec.json",
        "final_build_provenance.json",
        "convergence_report.pdf",
        "convergence_report.manifest.json",
    ):
        (session_root / name).unlink()

    with pytest.raises(
        RuntimeError,
        match="consumed by cancellation|cancellation receipt",
    ):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_hash
    assert not (session_root / "iterations").exists()


@pytest.mark.parametrize(
    "relative_path",
    [
        "iterations/001/selection.json",
        "iterations/001/revision_plan.json",
        "iterations/001/authorization.json",
        "iterations/001/result_scene_spec.json",
        "../../runs/run-initial/visual_qa_report.json",
        "../../runs/run-initial/revision_candidates.json",
        "../../runs/conv-700fed96e1-i01/visual_qa_report.json",
        "../../runs/conv-700fed96e1-i01/revision_candidates.json",
    ],
)
def test_iteration_support_evidence_deletion_is_detected(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
) -> None:
    """Every selection, authorization, SceneSpec, and QA dependency remains hash-bound."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    session_root = root / "qa" / "convergence" / "session-fixture"
    target = (session_root / relative_path).resolve()
    assert target.is_file()
    target.unlink()

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["ok"] is False
    assert status["integrity"] == "stale_or_tampered"


@pytest.mark.parametrize(
    "relative_path",
    [
        "iterations/001/before_constraints.json",
        "iterations/001/after_constraints.json",
    ],
)
def test_iteration_constraint_evidence_tampering_is_detected(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
) -> None:
    """Every executed receipt keeps exact before/after constraint evidence immutable."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    session_root = root / "qa" / "convergence" / "session-fixture"
    target = session_root / relative_path
    assert target.is_file()
    target.write_bytes(target.read_bytes() + b"\n")

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["ok"] is False
    assert status["integrity"] == "stale_or_tampered"
    assert "constraint evidence changed" in status["integrity_error"]


def test_rewritten_constraint_regression_count_cannot_authorize_acceptance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Recompute constraint regressions instead of trusting a rewritten receipt count."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, max_iterations=1)
    pipeline, _heights = _pipeline(scene_spec, constraint_failures=[1, 0])
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.8]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    result = run_job_visual_convergence("convergence_asset", "session-fixture")
    assert result["termination_reason"] == "constraint_regression"
    assert sha256_file(scene_spec) == baseline_hash

    session_root = root / "qa" / "convergence" / "session-fixture"
    _remove_terminal_projection(session_root)
    receipt_path = session_root / "iterations" / "001" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "accepted"
    receipt["canonical_scene_spec_sha256"] = receipt["result_scene_spec_sha256"]
    receipt["constraint_regression_count"] = 0
    receipt["reason_codes"] = ["improved"]
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    result_snapshot = session_root / "iterations" / "001" / "result_scene_spec.json"
    scene_spec.write_bytes(result_snapshot.read_bytes())
    rewritten_canonical_hash = sha256_file(scene_spec)

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["integrity"] == "stale_or_tampered"
    assert "constraint-regression count changed" in status["integrity_error"]
    with pytest.raises(ValueError, match="constraint-regression count changed"):
        run_job_visual_convergence("convergence_asset", "session-fixture")
    assert rewritten_canonical_hash != baseline_hash
    assert sha256_file(scene_spec) == rewritten_canonical_hash


@pytest.mark.parametrize(
    "relative_path",
    [
        "initial_build_provenance.json",
        "iterations/001/base_scene_spec.json",
        "iterations/001/result_build_provenance.json",
    ],
)
def test_convergence_source_and_build_snapshot_tampering_is_detected(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
) -> None:
    """Detect tampering of initial, per-iteration base, and result-build snapshots."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    session_root = root / "qa" / "convergence" / "session-fixture"
    target = session_root / relative_path
    assert target.is_file()
    target.write_bytes(target.read_bytes() + b"\n")

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["ok"] is False
    assert status["integrity"] == "stale_or_tampered"


def test_terminal_receipt_without_terminal_report_cannot_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Deleting terminal JSON after rollback never reopens the bounded approval."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8)
    pipeline, _heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.6005]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )
    run_job_visual_convergence("convergence_asset", "session-fixture")
    terminal = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "convergence_report.json"
    )
    terminal.unlink()

    with pytest.raises(RuntimeError, match="terminal convergence receipt"):
        run_job_visual_convergence("convergence_asset", "session-fixture")


def test_score_delta_preserves_more_than_six_decimal_places(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Iteration receipts store the exact direct-score difference without rounding."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    result_score = 0.700000123
    _run_one_accepted_session(
        root,
        scene_spec,
        run_id,
        monkeypatch,
        result_score=result_score,
    )
    receipt = json.loads(
        (
            root
            / "qa"
            / "convergence"
            / "session-fixture"
            / "iterations"
            / "001"
            / "receipt.json"
        ).read_text(encoding="utf-8")
    )

    assert receipt["score_delta"] == result_score - 0.6


def test_unexpected_canonical_tamper_is_not_overwritten_by_rollback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An external canonical hash is preserved and reported instead of silently restored."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8)

    def tampering_pipeline(
        job_id: str,
        job_root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Simulate an out-of-contract writer changing canonical data mid-iteration."""

        del job_id, job_root, render_engine, render_device
        payload = json.loads(scene_spec.read_text(encoding="utf-8"))
        payload["revision_notes"].append("external canonical tamper")
        scene_spec.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        raise RuntimeError("simulated downstream failure after external tamper")

    monkeypatch.setattr(
        convergence_session,
        "_run_job_pipeline",
        tampering_pipeline,
    )

    with pytest.raises(RuntimeError, match="outside the convergence-owned"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) != baseline_hash
    assert "external canonical tamper" in scene_spec.read_text(encoding="utf-8")
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    ).exists()


def test_tampered_archive_is_rejected_before_canonical_rollback(
    tmp_path: Path,
) -> None:
    """Keep caller-owned canonical content when its rollback archive was altered."""

    from codex_blender_modeler.auto_revision.service import _replace_with_archive

    scene_spec = tmp_path / "scene_spec.json"
    archive = tmp_path / "archived_scene_spec.json"
    scene_spec.write_bytes(b"convergence-owned-current")
    archive.write_bytes(b"verified-baseline")
    expected_current = sha256_file(scene_spec)
    expected_archive = sha256_file(archive)
    archive.write_bytes(b"tampered-baseline")

    with pytest.raises(RuntimeError, match="archived SceneSpec changed"):
        _replace_with_archive(
            "convergence_asset",
            scene_spec,
            archive,
            expected_archive_sha256=expected_archive,
            expected_current_sha256=expected_current,
            lock_owner_id="fixture-lock-owner",
        )

    assert scene_spec.read_bytes() == b"convergence-owned-current"
    assert not scene_spec.with_suffix(".json.rollback.tmp").exists()


def test_terminal_input_additions_do_not_invalidate_original_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A later auxiliary input may be added while every original input stays exact."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    view = root / "input" / "views" / "front.png"
    view.parent.mkdir(parents=True, exist_ok=True)
    view.write_bytes(b"later-approved-view")

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["integrity"] == "current"
    assert status["integrity_warnings"] == []


def test_later_canonical_revision_is_separate_from_valid_terminal_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Keep historical terminal evidence valid while reporting a later SceneSpec relation."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    terminal_report = json.loads(
        (
            root
            / "qa"
            / "convergence"
            / "session-fixture"
            / "convergence_report.json"
        ).read_text(encoding="utf-8")
    )
    terminal_hash = terminal_report["final_scene_spec_sha256"]
    payload = json.loads(scene_spec.read_text(encoding="utf-8"))
    payload["revision_notes"].append("later independently approved revision")
    scene_spec.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    snapshot = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "final_scene_spec.json"
    )

    assert status["integrity"] == "current"
    assert status["canonical_relation"] == "superseded_after_terminal"
    assert sha256_file(snapshot) == terminal_hash


def test_terminal_fast_path_does_not_regenerate_pdf_for_tampered_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Missing derived PDFs are restored only after authoritative evidence is current."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    session_root = root / "qa" / "convergence" / "session-fixture"
    (session_root / "convergence_report.pdf").unlink()
    (session_root / "convergence_report.manifest.json").unlink()
    selection_path = session_root / "iterations" / "001" / "selection.json"
    selection_path.write_text(
        selection_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stale or tampered"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert not (session_root / "convergence_report.pdf").exists()
    assert not (session_root / "convergence_report.manifest.json").exists()


def test_orphan_iteration_directory_is_detected_before_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A missing or non-contiguous receipt directory cannot be ignored by runtime state."""

    root, _scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8)
    orphan = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "002"
    )
    orphan.mkdir(parents=True)

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["integrity"] == "stale_or_tampered"
    assert "exactly contiguous" in status["integrity_error"]


def test_terminal_summary_is_cross_checked_after_immutable_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a model-valid terminal summary that lies about accepted iterations."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    session_root = root / "qa" / "convergence" / "session-fixture"
    report_path = session_root / "convergence_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["accepted_iterations"] = 0
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (session_root / "convergence_report.pdf").unlink()
    (session_root / "convergence_report.manifest.json").unlink()

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["status"] == "invalid_terminal"
    assert status["integrity"] == "stale_or_tampered"
    assert "terminal convergence summary mismatch" in status["integrity_error"]
    assert status["canonical_relation"] == "unknown_invalid"


def test_terminal_pdf_recovery_obeys_the_shared_job_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Serialize terminal fast-path PDF recovery with every other job writer."""

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _run_one_accepted_session(root, scene_spec, run_id, monkeypatch)
    session_root = root / "qa" / "convergence" / "session-fixture"
    (session_root / "convergence_report.pdf").unlink()
    (session_root / "convergence_report.manifest.json").unlink()

    with workflow_write_lock(
        root,
        "convergence_asset",
        "competing-writer",
        ttl_seconds=60,
    ):
        with pytest.raises(
            RuntimeError,
            match="Another workflow owns the job write lock",
        ):
            run_job_visual_convergence(
                "convergence_asset",
                "session-fixture",
            )

    recovered = run_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
    )
    assert recovered["status"] == "terminal"
    assert (session_root / "convergence_report.pdf").is_file()
    assert (session_root / "convergence_report.manifest.json").is_file()


def test_partial_post_qa_failure_writes_coherent_failed_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Keep partial QA files out of the receipt while restoring the exact baseline."""

    from codex_blender_modeler.auto_revision import convergence_session, service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, max_iterations=1)
    pipeline, _heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    def partial_qa_failure(
        job_id: str,
        render_engine: str,
        render_device: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Leave one non-authoritative partial file before simulating host failure."""

        del job_id, render_engine, render_device
        assert run_id is not None
        partial_root = root / "qa" / "runs" / run_id
        partial_root.mkdir(parents=True, exist_ok=False)
        (partial_root / "request.json").write_text("{}", encoding="utf-8")
        raise RuntimeError("simulated partial QA failure")

    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        partial_qa_failure,
    )
    result = run_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
    )
    receipt_path = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert result["termination_reason"] == "failed"
    assert receipt["status"] == "failed"
    assert receipt["result_scene_spec_sha256"] is not None
    assert receipt["result_qa_run_id"] is None
    assert receipt["result_qa_report_sha256"] is None
    assert receipt["result_candidates_sha256"] is None
    assert receipt["after_direct_score"] is None
    assert receipt["after_silhouette_iou"] is None
    assert receipt["score_delta"] is None
    assert sha256_file(scene_spec) == baseline_hash
    assert get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )["integrity"] == "current"


def test_interrupted_iteration_is_recovered_before_a_clean_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Recover a promoted receipt-less staging attempt before running a fresh iteration."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_hash = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, max_iterations=2)
    normal_pipeline, _heights = _pipeline(scene_spec)
    calls = 0

    def interrupt_once(
        job_id: str,
        job_root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Interrupt the first promoted build and run the fixture pipeline afterward."""

        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt("simulated host cancellation")
        return normal_pipeline(job_id, job_root, render_engine, render_device)

    monkeypatch.setattr(
        convergence_session,
        "_run_job_pipeline",
        interrupt_once,
    )
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.82]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    with pytest.raises(KeyboardInterrupt, match="simulated host cancellation"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    session_root = root / "qa" / "convergence" / "session-fixture"
    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )
    assert status["ok"] is True
    assert status["status"] == "recovery_required"
    assert status["recovery_required"] is True
    assert status["incomplete_iteration_index"] == 1
    assert status["canonical_relation"] == "recoverable_staged_result"
    assert not (session_root / "iterations" / "001").exists()

    recovered = run_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
    )
    assert recovered["execution_outcome"] == "interrupted_attempt_recovered"
    assert recovered["iterations_executed_this_invocation"] == 0
    assert recovered["next_action"] == "invoke_run_again"
    assert sha256_file(scene_spec) == baseline_hash
    assert not (session_root / "staging" / "001").exists()
    assert len(list((session_root / "interrupted_attempts").iterdir())) == 1
    assert not (session_root / "iterations" / "001").exists()

    completed = run_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
    )
    assert completed["execution_outcome"] == "iteration_completed_terminal"
    assert completed["iterations_executed_this_invocation"] == 1
    assert completed["termination_reason"] == "target_reached"
    assert (session_root / "iterations" / "001" / "receipt.json").is_file()


def test_completed_iteration_receipt_remains_immutable_across_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Keep the first committed receipt byte-identical when a later call continues."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8, max_iterations=2)
    pipeline, _heights = _pipeline(scene_spec)
    monkeypatch.setattr(convergence_session, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(
        convergence_session,
        "_run_post_visual_qa",
        _post_qa_sequence(root, scene_spec, [0.7, 0.82]),
    )
    monkeypatch.setattr(
        convergence_session,
        "generate_visual_convergence_pdf_report",
        _fake_pdf(root),
    )

    first = run_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
    )
    receipt_path = (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
        / "001"
        / "receipt.json"
    )
    receipt_sha256 = sha256_file(receipt_path)
    assert first["execution_outcome"] == "iteration_completed"

    second = run_job_visual_convergence(
        "convergence_asset",
        "session-fixture",
    )
    assert second["termination_reason"] == "target_reached"
    assert sha256_file(receipt_path) == receipt_sha256


@pytest.mark.parametrize(
    "relative_path",
    [
        "request.json",
        "render_pass_manifest.json",
        "passes/wireframe.png",
    ],
)
def test_active_status_audits_full_qa_provenance(
    tmp_path: Path,
    monkeypatch,
    relative_path: str,
) -> None:
    """Detect changes to the QA request, manifest, or any exact seven-pass artifact."""

    root, _scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    _plan_and_approve(run_id, target=0.8)
    target = root / "qa" / "runs" / run_id / relative_path
    target.write_bytes(target.read_bytes() + b"\ntampered")

    status = get_job_visual_convergence_status(
        "convergence_asset",
        "session-fixture",
    )

    assert status["integrity"] == "stale_or_tampered"
    assert status["canonical_relation"] == "unknown_invalid"


def test_background_fast_owned_qa_requires_a_separate_standard_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject the exact current-key QA run emitted by the real fast planner."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "planner-reference.png"
    reference.write_bytes(b"immutable-reference")
    owner_state = plan_workflow(
        "Create a bounded exterior background preview.",
        job_id="convergence_asset",
        reference_path=reference,
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )
    owner_plan_path = (
        workspace
        / "convergence_asset"
        / "workflows"
        / owner_state.workflow_id
        / "plan.json"
    )
    owner_plan = json.loads(owner_plan_path.read_text(encoding="utf-8"))
    qa_step = next(
        step for step in owner_plan["steps"] if step["step_id"] == "qa.run"
    )
    assert "qa_run_id" not in qa_step["parameters"]
    run_id = qa_step["parameters"]["run_id"]
    root, scene_spec, fixture_run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        qa_run_id=run_id,
    )
    assert fixture_run_id == run_id
    baseline_hash = sha256_file(scene_spec)
    _write_fast_qa_owner_completion(
        root,
        workflow_id=owner_state.workflow_id,
        plan_path=owner_plan_path,
        run_id=run_id,
    )

    with pytest.raises(
        ValueError,
        match="separate standard/manual direct-reference QA",
    ):
        plan_job_visual_convergence(
            "convergence_asset",
            run_id,
            session_id="session-fast-owner",
            target_direct_score=0.8,
            target_silhouette_iou=0.8,
            allowed_target_ids=[TARGET_ID],
        )

    assert sha256_file(scene_spec) == baseline_hash
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fast-owner"
    ).exists()


@pytest.mark.parametrize("mutation", ["model_valid_change", "delete"])
def test_fast_qa_owner_receipt_prevents_plan_tamper_or_deletion_bypass(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    """Use immutable QA receipts to reject a changed or deleted fast-owner plan."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "planner-reference.png"
    reference.write_bytes(b"immutable-reference")
    owner_state = plan_workflow(
        "Create a bounded exterior background preview.",
        job_id="convergence_asset",
        reference_path=reference,
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )
    owner_plan_path = (
        workspace
        / "convergence_asset"
        / "workflows"
        / owner_state.workflow_id
        / "plan.json"
    )
    owner_plan = json.loads(owner_plan_path.read_text(encoding="utf-8"))
    qa_step = next(
        step for step in owner_plan["steps"] if step["step_id"] == "qa.run"
    )
    run_id = qa_step["parameters"]["run_id"]
    root, scene_spec, _fixture_run_id = _job_fixture(
        tmp_path,
        monkeypatch,
        qa_run_id=run_id,
    )
    baseline_hash = sha256_file(scene_spec)
    _write_fast_qa_owner_completion(
        root,
        workflow_id=owner_state.workflow_id,
        plan_path=owner_plan_path,
        run_id=run_id,
    )
    if mutation == "delete":
        owner_plan_path.unlink()
        expected = "owning the selected initial QA run is missing"
    else:
        owner_plan["notes"].append("model-valid but unapproved plan mutation")
        owner_plan_path.write_text(
            json.dumps(owner_plan, indent=2),
            encoding="utf-8",
        )
        expected = "plan hash changed"

    with pytest.raises(ValueError, match=expected):
        plan_job_visual_convergence(
            "convergence_asset",
            run_id,
            session_id=f"session-fast-{mutation}",
            target_direct_score=0.8,
            target_silhouette_iou=0.8,
            allowed_target_ids=[TARGET_ID],
        )

    assert sha256_file(scene_spec) == baseline_hash
    assert not (
        root
        / "qa"
        / "convergence"
        / f"session-fast-{mutation}"
    ).exists()


def test_background_fast_qa_owner_accepts_legacy_key_and_rejects_conflicts() -> None:
    """Preserve legacy QA ownership while failing closed on ambiguous bindings."""

    from codex_blender_modeler.auto_revision.convergence_session import (
        _planned_qa_run_id,
    )

    assert _planned_qa_run_id({"qa_run_id": "legacy-run"}) == "legacy-run"
    assert _planned_qa_run_id({"run_id": "current-run"}) == "current-run"
    with pytest.raises(ValueError, match="conflicting run_id"):
        _planned_qa_run_id(
            {
                "run_id": "current-run",
                "qa_run_id": "different-legacy-run",
            }
        )


def test_run_reloads_plan_after_acquiring_the_job_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a plan changed while the runner was waiting to acquire authority."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_sha256 = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, max_iterations=1)
    real_lock = convergence_session.workflow_write_lock
    plan_path = (
        root / "qa" / "convergence" / "session-fixture" / "plan.json"
    )

    @contextmanager
    def lock_with_waiting_writer(*args, **kwargs):
        """Simulate another writer changing immutable authority before lock entry."""

        with real_lock(*args, **kwargs):
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["minimum_iteration_gain"] = 0.02
            plan_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            yield

    monkeypatch.setattr(
        convergence_session,
        "workflow_write_lock",
        lock_with_waiting_writer,
    )

    with pytest.raises(ValueError, match="approval.*plan"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_sha256
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "iterations"
    ).exists()


def test_run_revalidates_approval_immediately_before_scene_promotion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject approval tampering after compilation but before canonical CAS."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_sha256 = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, max_iterations=1)
    approval_path = (
        root / "qa" / "convergence" / "session-fixture" / "approval.json"
    )
    original_apply = convergence_session._apply_iteration_authorization

    def apply_then_tamper(*args, **kwargs):
        """Change only the approval bytes after the candidate is compiled."""

        result = original_apply(*args, **kwargs)
        payload = json.loads(approval_path.read_text(encoding="utf-8"))
        payload["approval_note"] = "Tampered after host compilation."
        approval_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return result

    monkeypatch.setattr(
        convergence_session,
        "_apply_iteration_authorization",
        apply_then_tamper,
    )

    with pytest.raises(ValueError, match="approval changed"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_sha256


def test_run_revalidates_activation_at_terminalization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject authority tampering immediately before terminal evidence is written."""

    from codex_blender_modeler.auto_revision import convergence_session

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    baseline_sha256 = sha256_file(scene_spec)
    _plan_and_approve(run_id, target=0.8, max_iterations=1)
    approval_path = (
        root / "qa" / "convergence" / "session-fixture" / "approval.json"
    )
    tampered = False

    def target_then_tamper(plan, report):
        """Tamper once after activation validation but before terminalization."""

        nonlocal tampered
        del plan, report
        if not tampered:
            payload = json.loads(approval_path.read_text(encoding="utf-8"))
            payload["approval_note"] = "Tampered at terminal boundary."
            approval_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tampered = True
        return True

    monkeypatch.setattr(
        convergence_session,
        "_target_reached",
        target_then_tamper,
    )

    with pytest.raises(ValueError, match="approval changed"):
        run_job_visual_convergence("convergence_asset", "session-fixture")

    assert sha256_file(scene_spec) == baseline_sha256
    assert not (
        root
        / "qa"
        / "convergence"
        / "session-fixture"
        / "convergence_report.json"
    ).exists()
