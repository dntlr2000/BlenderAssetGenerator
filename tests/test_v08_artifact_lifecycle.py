from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import codex_blender_modeler.orchestration.service as orchestration_service
from codex_blender_modeler.background_quality.models import BackgroundQualityReport
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.interior_qa.models import InteriorQAPlanApproval
from codex_blender_modeler.materials import promote_workflow_material_candidate
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.optimization.models import OptimizationApproval
from codex_blender_modeler.orchestration.models import ArtifactFreshness, WorkflowStep
from codex_blender_modeler.orchestration.service import (
    complete_workflow_step,
    plan_workflow,
    reconcile_workflow,
    resume_workflow,
)
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.diagnostic_models import (
    AssemblyDiagnosticEvidence,
    AssemblyMultiviewBundleEvidence,
    BoundedCameraDelta,
    CameraProbeResult,
    DiagnosticAttribution,
    QADiagnosticBundleManifest,
    QADiagnosticReport,
    QADiagnosticRequest,
)
from codex_blender_modeler.qa.hashing import canonical_model_sha256
from codex_blender_modeler.qa.models import (
    BoundingBoxMetric,
    DirectVisualMetrics,
    RenderPassManifest,
    RenderPassRecord,
    VisualQAReport,
    VisualQARequest,
)
from codex_blender_modeler.workspace import sha256_file

ROOT = Path(__file__).resolve().parents[1]
PASS_KINDS = [
    "beauty",
    "silhouette",
    "object_id",
    "material_id",
    "normal",
    "depth",
    "wireframe",
]


def _image(path: Path) -> Path:
    """Create one deterministic exterior reference image."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 32), (60, 110, 170)).save(path)
    return path


def _plan_step(root: Path, workflow_id: str, step_id: str) -> dict:
    """Load one immutable plan step by its stable identifier."""

    plan = json.loads(
        (root / "workflows" / workflow_id / "plan.json").read_text(
            encoding="utf-8"
        )
    )
    return next(item for item in plan["steps"] if item["step_id"] == step_id)


def _author_modeling_plan(root: Path, state) -> object:
    """Write and complete one minimal authored semantic modeling plan."""

    scene_seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    path = root / "analysis" / "modeling_plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload["objects"] = [
        {
            "id": item["id"],
            "label": item["name"],
            "recommended_geometry": item["geometry"]["kind"],
            "source_ids": ["ref.main"],
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "observed": True,
            "confidence": 0.9,
            "assembly_role": "root" if index == 0 else "free_standing",
            "notes": [],
        }
        for index, item in enumerate(scene_seed["objects"])
    ]
    payload["assembly_consistency_policy"] = "spatial_v1"
    payload["assembly_frame"] = {
        "root_object_id": scene_seed["objects"][0]["id"],
        "longitudinal_axis": "X",
        "lateral_axis": "Y",
        "vertical_axis": "Z",
        "symmetry": "unknown",
        "evidence_status": "inferred",
        "source_ids": [],
        "confidence": 0.5,
        "notes": ["Test-only inferred assembly frame."],
    }
    payload["assembly_relationships"] = []
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = next(
        item for item in state.steps if item.step_id == "geometry.modeling_plan"
    )
    return complete_workflow_step(
        state.job_id,
        state.workflow_id,
        "geometry.modeling_plan",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored one bounded background semantic object.",
    )


def _author_background_scene(root: Path, state) -> object:
    """Write and complete one moderate-detail exterior SceneSpec fixture."""

    seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    seed["job_id"] = state.job_id
    (root / "analysis" / "scene_spec.json").write_text(
        json.dumps(seed, indent=2) + "\n",
        encoding="utf-8",
    )
    current = next(
        item for item in state.steps if item.step_id == "geometry.background_author"
    )
    return complete_workflow_step(
        state.job_id,
        state.workflow_id,
        "geometry.background_author",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored one bounded moderate-detail exterior SceneSpec.",
    )


def _author_material_candidate(root: Path, state) -> object:
    """Promote only the workflow-owned authored candidate from scaffold to authored."""

    step = _plan_step(root, state.workflow_id, "material.author")
    candidate = root / str(step["parameters"]["candidate_plan_path"])
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    candidate.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = next(item for item in state.steps if item.step_id == "material.author")
    return complete_workflow_step(
        state.job_id,
        state.workflow_id,
        "material.author",
        input_fingerprint=str(current.input_fingerprint),
        note="Authored the exact local procedural material candidate.",
    )


def _write_direct_qa(root: Path, request, step) -> None:
    """Write one exact direct-only QA run containing all seven required pass kinds."""

    run_id = str(step.parameters["run_id"])
    run_root = root / "qa" / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    scene_path = root / "analysis" / "scene_spec.json"
    spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    reference_path = root / "input" / "reference.png"
    reference_mask_path = run_root / "reference_mask.png"
    Image.new("L", (48, 32), 255).save(reference_mask_path)
    pass_root = run_root / "passes"
    pass_root.mkdir(parents=True, exist_ok=False)
    passes: list[RenderPassRecord] = []
    for index, kind in enumerate(PASS_KINDS):
        path = pass_root / f"{kind}.png"
        Image.new("RGB", (48, 32), (20 + index * 10, 80, 120)).save(path)
        passes.append(
            RenderPassRecord(
                kind=kind,  # type: ignore[arg-type]
                path=f"passes/{path.name}",
                sha256=sha256_file(path),
                width=48,
                height=32,
                encoding="png-rgb8",
            )
        )
    fingerprint = camera_fingerprint(spec)
    build_fingerprint = str(
        collect_build_provenance(root, request.job_id, scene_spec_path=scene_path)[
            "fingerprint"
        ]
    )
    manifest = RenderPassManifest(
        job_id=request.job_id,
        run_id=run_id,
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=fingerprint,
        build_fingerprint=build_fingerprint,
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="CPU",
        resolution=(48, 32),
        passes=passes,
    )
    manifest_path = run_root / "render_pass_manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    visual_request = VisualQARequest(
        job_id=request.job_id,
        run_id=run_id,
        mode="concept",
        reference_path=str(reference_path.resolve()),
        reference_sha256=sha256_file(reference_path),
        reference_mask_path=str(reference_mask_path.resolve()),
        reference_mask_sha256=sha256_file(reference_mask_path),
        preview_path=str((pass_root / "beauty.png").resolve()),
        preview_sha256=sha256_file(pass_root / "beauty.png"),
        render_pass_manifest_path=str(manifest_path.resolve()),
        render_pass_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=fingerprint,
    )
    request_path = run_root / "request.json"
    request_path.write_text(visual_request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (run_root / "reference_mask_manifest.json").write_text(
        json.dumps(
            {
                "reference_sha256": visual_request.reference_sha256,
                "output_path": "reference_mask.png",
                "output_sha256": visual_request.reference_mask_sha256,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report = VisualQAReport(
        job_id=request.job_id,
        run_id=run_id,
        request_sha256=canonical_model_sha256(visual_request),
        camera_fingerprint=fingerprint,
        direct_metrics=DirectVisualMetrics(
            silhouette_iou=0.9,
            silhouette_union_fraction=0.9,
            global_bbox=BoundingBoxMetric(
                reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
                rendered_bbox_norm=(0.1, 0.1, 0.9, 0.9),
                center_error_norm=0.0,
                size_error_norm=0.0,
            ),
            overall_direct_score=0.9,
        ),
        generated_target_status="not_requested",
    )
    (run_root / "visual_qa_report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (run_root / "revision_candidates.json").write_text(
        '{"candidates":[]}\n',
        encoding="utf-8",
    )
    latest = {
        "schema_version": "0.6.0",
        "job_id": request.job_id,
        "run_id": run_id,
        "visual_qa_report": f"qa/runs/{run_id}/visual_qa_report.json",
    }
    (root / "qa" / "latest.json").write_text(
        json.dumps(latest, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_qa_diagnostics(root: Path, request, step) -> None:
    """Write one recursively hash-bound companion bundle for lifecycle tests."""

    qa_run_id = str(step.parameters["qa_run_id"])
    diagnostic_id = str(step.parameters["diagnostic_id"])
    qa_root = root / "qa" / "runs" / qa_run_id
    diagnostic_root = qa_root / "diagnostics" / diagnostic_id
    attempt_root = diagnostic_root / "attempts" / "attempt-001"
    probe_root = attempt_root / "camera_probes"
    render_root = probe_root / "renders" / "baseline"
    render_root.mkdir(parents=True, exist_ok=False)
    role_map_path = attempt_root / "role_map.json"
    role_map_path.write_text('{"fixture":"diagnostic-role-map"}\n', encoding="utf-8")
    role_map_sha256 = sha256_file(role_map_path)
    passes: list[dict[str, str]] = []
    for kind in ("silhouette", "object_id"):
        path = render_root / f"{kind}.png"
        path.write_bytes(kind.encode("utf-8"))
        passes.append(
            {
                "kind": kind,
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    probe_plan = {
        "schema_version": "0.6.0",
        "diagnostic_kind": "bounded_camera_probe",
        "job_id": request.job_id,
        "qa_run_id": qa_run_id,
        "diagnostic_id": diagnostic_id,
        "role_map_sha256": role_map_sha256,
        "probes": [
            {
                "probe_id": "baseline",
                "camera_delta": BoundedCameraDelta().model_dump(mode="json"),
            }
        ],
    }
    probe_plan_path = probe_root / "plan.json"
    probe_plan_path.write_text(
        json.dumps(probe_plan, indent=2) + "\n",
        encoding="utf-8",
    )
    probe_manifest = {
        "schema_version": "0.6.0",
        "diagnostic_kind": "bounded_camera_probe",
        "job_id": request.job_id,
        "qa_run_id": qa_run_id,
        "diagnostic_id": diagnostic_id,
        "probe_plan_sha256": sha256_file(probe_plan_path),
        "role_map_sha256": role_map_sha256,
        "probes": [{"probe_id": "baseline", "passes": passes}],
    }
    probe_manifest_path = probe_root / "render_manifest.json"
    probe_manifest_path.write_text(
        json.dumps(probe_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    diagnostic_request = QADiagnosticRequest(
        job_id=request.job_id,
        qa_run_id=qa_run_id,
        diagnostic_id=diagnostic_id,
        artifact_root=diagnostic_root.relative_to(root).as_posix(),
        visual_qa_request_path=(qa_root / "request.json").relative_to(root).as_posix(),
        visual_qa_request_sha256=sha256_file(qa_root / "request.json"),
        visual_qa_report_path=(
            qa_root / "visual_qa_report.json"
        ).relative_to(root).as_posix(),
        visual_qa_report_sha256=sha256_file(qa_root / "visual_qa_report.json"),
        render_pass_manifest_path=(
            qa_root / "render_pass_manifest.json"
        ).relative_to(root).as_posix(),
        render_pass_manifest_sha256=sha256_file(
            qa_root / "render_pass_manifest.json"
        ),
        scene_spec_sha256=sha256_file(root / "analysis" / "scene_spec.json"),
        camera_role_map_path=role_map_path.relative_to(root).as_posix(),
        camera_role_map_sha256=role_map_sha256,
        max_camera_probes=1,
    )
    diagnostic_request_path = attempt_root / "request.json"
    diagnostic_request_path.write_text(
        diagnostic_request.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    probe_result = CameraProbeResult(
        probe_id="baseline",
        is_baseline=True,
        status="unscorable",
        camera_delta=BoundedCameraDelta(),
        evidence_path=probe_manifest_path.relative_to(root).as_posix(),
        evidence_sha256=sha256_file(probe_manifest_path),
        limitations=["Lifecycle fixture has no semantic masks."],
    )
    diagnostic_report = QADiagnosticReport(
        job_id=request.job_id,
        qa_run_id=qa_run_id,
        diagnostic_id=diagnostic_id,
        request_path=diagnostic_request_path.relative_to(root).as_posix(),
        request_sha256=sha256_file(diagnostic_request_path),
        status="unscorable",
        camera_probes=[probe_result],
        assembly_evidence=AssemblyDiagnosticEvidence(
            limitations=["Assembly evidence is not included in this lifecycle fixture."]
        ),
        attribution=DiagnosticAttribution(
            classification="unscorable",
            confidence=0.0,
            baseline_probe_id="baseline",
            reasons=["Lifecycle fixture has no semantic evidence."],
        ),
        limitations=["Lifecycle fixture has no semantic evidence."],
        generated_at=datetime.now(UTC),
    )
    diagnostic_report_path = attempt_root / "report.json"
    diagnostic_report_path.write_text(
        diagnostic_report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    bundle = QADiagnosticBundleManifest(
        job_id=request.job_id,
        qa_run_id=qa_run_id,
        diagnostic_id=diagnostic_id,
        visual_qa_report_path=(
            qa_root / "visual_qa_report.json"
        ).relative_to(root).as_posix(),
        visual_qa_report_sha256=sha256_file(qa_root / "visual_qa_report.json"),
        diagnostic_request_path=diagnostic_request_path.relative_to(root).as_posix(),
        diagnostic_request_sha256=sha256_file(diagnostic_request_path),
        diagnostic_report_path=diagnostic_report_path.relative_to(root).as_posix(),
        diagnostic_report_sha256=sha256_file(diagnostic_report_path),
        camera_probe_plan_path=probe_plan_path.relative_to(root).as_posix(),
        camera_probe_plan_sha256=sha256_file(probe_plan_path),
        camera_probe_manifest_path=probe_manifest_path.relative_to(root).as_posix(),
        camera_probe_manifest_sha256=sha256_file(probe_manifest_path),
        assembly_multiview=AssemblyMultiviewBundleEvidence(status="not_requested"),
        created_at=datetime.now(UTC),
    )
    (diagnostic_root / "bundle_manifest.json").write_text(
        bundle.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _install_fake_blender_host(
    monkeypatch: pytest.MonkeyPatch,
    *,
    quality_status: str = "passed",
) -> None:
    """Replace Blender-heavy host calls while preserving lifecycle host operations."""

    original = orchestration_service._execute_host_tool

    def execute(root, workflow_root, request, step, *, input_fingerprint) -> None:
        """Produce deterministic fixtures or delegate contract lifecycle operations."""

        tool = step.tool_name
        if tool == "build_scene":
            marker = (
                b"material-build"
                if (root / "analysis" / "material_plan.json").is_file()
                else b"geometry-build"
            )
            (root / "blender").mkdir(exist_ok=True)
            (root / "blender" / "scene.blend").write_bytes(marker)
            return
        if tool == "fit_background_exterior":
            fit_root = root / str(step.parameters["fit_root"])
            fit_root.mkdir(parents=True, exist_ok=False)
            (fit_root / "role_map.json").write_text(
                '{"fixture":"role-map"}\n',
                encoding="utf-8",
            )
            (fit_root / "fit_report.json").write_text(
                '{"fixture":"fit-report"}\n',
                encoding="utf-8",
            )
            (fit_root / "promotion_receipt.json").write_text(
                '{"fixture":"promotion"}\n',
                encoding="utf-8",
            )
            return
        if tool == "render_preview":
            (root / "renders").mkdir(exist_ok=True)
            Image.new("RGB", (32, 32), (80, 100, 120)).save(
                root / "renders" / "preview.png"
            )
            return
        if tool == "inspect_scene":
            (root / "reports").mkdir(exist_ok=True)
            (root / "reports" / "scene_inventory.json").write_text(
                json.dumps({"job_id": request.job_id, "objects": []}) + "\n",
                encoding="utf-8",
            )
            return
        if tool == "validate_scene":
            (root / "reports" / "validation.json").write_text(
                '{"ok":true,"errors":[],"warnings":[]}\n',
                encoding="utf-8",
            )
            return
        if tool == "inspect_materials":
            (root / "reports" / "material_validation.json").write_text(
                '{"ok":true,"materials":[]}\n',
                encoding="utf-8",
            )
            return
        if tool == "validate_material_fidelity":
            (root / "reports" / "material_fidelity_validation.json").write_text(
                '{"ok":true,"status":"passed","findings":[]}\n',
                encoding="utf-8",
            )
            return
        if tool == "render_material_swatches":
            (root / "reports" / "material_swatches.json").write_text(
                '{"materials":[]}\n',
                encoding="utf-8",
            )
            return
        if tool == "run_visual_qa":
            _write_direct_qa(root, request, step)
            return
        if tool == "run_visual_diagnostics":
            _write_qa_diagnostics(root, request, step)
            return
        if tool == "evaluate_background_delivery":
            qa_run_id = str(step.parameters["qa_run_id"])
            qa_root = root / "qa" / "runs" / qa_run_id
            role_map = root / str(step.parameters["role_map_path"])
            fit_report = root / str(step.parameters["fit_report_path"])
            report = BackgroundQualityReport(
                job_id=request.job_id,
                workflow_id=request.workflow_id,
                quality_status=quality_status,  # type: ignore[arg-type]
                quality_accepted=quality_status == "passed",
                standard_workflow_recommended=quality_status != "passed",
                overall_direct_score=0.9,
                primary_silhouette_score=(
                    None if quality_status == "unscorable" else 0.9
                ),
                primary_bbox_similarity=(
                    None if quality_status == "unscorable" else 0.9
                ),
                primary_high_findings=(
                    ["direct.asset.body"]
                    if quality_status == "needs_revision"
                    else []
                ),
                unscorable_evidence=(
                    ["Primary role mask is unavailable."]
                    if quality_status == "unscorable"
                    else []
                ),
                recommended_standard_revision_targets=(
                    ["asset.body"]
                    if quality_status == "needs_revision"
                    else []
                ),
                qa_run_id=qa_run_id,
                qa_request_path=(
                    f"qa/runs/{qa_run_id}/request.json"
                ),
                qa_request_sha256=sha256_file(qa_root / "request.json"),
                visual_qa_report_path=(
                    f"qa/runs/{qa_run_id}/visual_qa_report.json"
                ),
                visual_qa_report_sha256=sha256_file(
                    qa_root / "visual_qa_report.json"
                ),
                render_pass_manifest_path=(
                    f"qa/runs/{qa_run_id}/render_pass_manifest.json"
                ),
                render_pass_manifest_sha256=sha256_file(
                    qa_root / "render_pass_manifest.json"
                ),
                role_map_path=role_map.relative_to(root).as_posix(),
                role_map_sha256=sha256_file(role_map),
                fit_report_path=fit_report.relative_to(root).as_posix(),
                fit_report_sha256=sha256_file(fit_report),
                source_fingerprint="a" * 64,
                build_fingerprint="b" * 64,
                qa_scene_spec_sha256=sha256_file(
                    root / "analysis" / "scene_spec.json"
                ),
                qa_camera_fingerprint="1" * 64,
                evaluated_at=datetime.now(UTC),
            )
            output = root / str(step.parameters["output_path"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                report.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            return
        if tool == "generate_pdf_report":
            output = root / str(step.parameters["output_path"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.4\n% lifecycle fixture\n")
            output.with_suffix(".manifest.json").write_text(
                '{"status":"complete"}\n',
                encoding="utf-8",
            )
            return
        original(
            root,
            workflow_root,
            request,
            step,
            input_fingerprint=input_fingerprint,
        )

    monkeypatch.setattr(orchestration_service, "_execute_host_tool", execute)
    monkeypatch.setattr(
        orchestration_service,
        "collect_source_provenance",
        lambda *_args, **_kwargs: SimpleNamespace(
            source_fingerprint="a" * 64,
            build_fingerprint="b" * 64,
        ),
    )


def _fast_workflow_to_material_author(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    quality_status: str = "passed",
) -> tuple[Path, object]:
    """Advance one isolated fast workflow to its authored material candidate gate."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    _install_fake_blender_host(monkeypatch, quality_status=quality_status)
    state = plan_workflow(
        "Create one static background exterior preview.",
        job_id="fast_lifecycle_asset",
        reference_path=_image(tmp_path / "reference.png"),
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)
    root = workspace / state.job_id
    state = _author_modeling_plan(root, state)
    state = _author_background_scene(root, state)
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=64)
    assert state.current_step_id == "material.author"
    return root, state


def test_fast_preview_lifecycle_completes_with_one_direct_qa(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Complete the required fast preview without retroactively staling prior steps."""

    root, state = _fast_workflow_to_material_author(monkeypatch, tmp_path)
    state = _author_material_candidate(root, state)
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=64)

    assert state.status == "completed"
    assert state.milestone == "delivered_for_review"
    assert state.quality_status == "passed"
    assert state.standard_workflow_recommended is False
    states = {item.step_id: item for item in state.steps}
    assert states["material.author"].status == "complete"
    assert states["material.scaffold"].status == "complete"
    assert states["background_geometry.build"].status == "complete"
    assert states["background_geometry.render"].status == "complete"
    assert states["qa.run"].status == "complete"
    assert states["qa.diagnostics"].status == "complete"
    qa_runs = list((root / "qa" / "runs").iterdir())
    assert len(qa_runs) == 1
    manifest = json.loads(
        (qa_runs[0] / "render_pass_manifest.json").read_text(encoding="utf-8")
    )
    assert [item["kind"] for item in manifest["passes"]] == PASS_KINDS
    assert not (qa_runs[0] / "target").exists()
    assert not list(root.glob("qa/runs/*/qa_target_manifest.json"))
    promotion = _plan_step(root, state.workflow_id, "material.promote")
    receipt = root / promotion["parameters"]["promotion_receipt_path"]
    assert json.loads(receipt.read_text(encoding="utf-8"))["ok"] is True

    (root / "renders" / "preview.png").write_bytes(b"new-workflow-preview")
    (root / "qa" / "latest.json").write_text(
        '{"run_id":"another-run"}\n',
        encoding="utf-8",
    )
    reconstructed = reconcile_workflow(state.job_id, state.workflow_id)
    assert reconstructed.status == "completed"
    assert reconstructed.milestone == "delivered_for_review"
    reconstructed_steps = {item.step_id: item for item in reconstructed.steps}
    assert reconstructed_steps["qa.run"].status == "complete"
    assert reconstructed_steps["qa.diagnostics"].status == "complete"


def test_visual_diagnostic_host_adopts_terminal_bundle_after_exact_interruption(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Resume an exact interrupted diagnostic attempt without rendering it again."""

    real_execute = orchestration_service._execute_host_tool
    root, state = _fast_workflow_to_material_author(monkeypatch, tmp_path)
    state = _author_material_candidate(root, state)
    fake_execute = orchestration_service._execute_host_tool
    while state.current_step_id != "qa.diagnostics":
        state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)

    def publish_then_interrupt(
        root_arg: Path,
        workflow_root_arg: Path,
        request: object,
        step: WorkflowStep,
        *,
        input_fingerprint: str,
    ) -> None:
        """Simulate process loss after terminal publication and before receipt finalization."""

        fake_execute(
            root_arg,
            workflow_root_arg,
            request,
            step,
            input_fingerprint=input_fingerprint,
        )
        if step.tool_name == "run_visual_diagnostics":
            raise KeyboardInterrupt("simulated process loss after terminal publication")

    monkeypatch.setattr(
        orchestration_service,
        "_execute_host_tool",
        publish_then_interrupt,
    )
    with pytest.raises(KeyboardInterrupt, match="simulated process loss"):
        resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)

    def unexpected_rerun(*_args: object, **_kwargs: object) -> None:
        """Fail if adoption tries to create a second immutable diagnostic run."""

        raise AssertionError("a current terminal diagnostic bundle must be adopted")

    monkeypatch.setattr(
        orchestration_service,
        "run_job_visual_diagnostics",
        unexpected_rerun,
    )
    monkeypatch.setattr(orchestration_service, "_execute_host_tool", real_execute)
    resumed = resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)

    diagnostic_state = next(
        item for item in resumed.steps if item.step_id == "qa.diagnostics"
    )
    assert diagnostic_state.status == "complete"
    attempt_root = (
        root / "workflows" / state.workflow_id / "attempts" / "qa.diagnostics"
    )
    attempts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(attempt_root.glob("*.json"))
    ]
    assert sorted(item["status"] for item in attempts) == ["failed", "succeeded"]
    interrupted = next(item for item in attempts if item["status"] == "failed")
    succeeded = next(item for item in attempts if item["status"] == "succeeded")
    assert interrupted["error_type"] == "InterruptedAttempt"
    assert interrupted["plan_sha256"] == succeeded["plan_sha256"]
    assert interrupted["input_fingerprint"] == succeeded["input_fingerprint"]


def test_visual_diagnostic_host_rejects_terminal_bundle_without_interruption(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reject a pre-existing terminal bundle without an exact interrupted receipt."""

    real_execute = orchestration_service._execute_host_tool
    root, state = _fast_workflow_to_material_author(monkeypatch, tmp_path)
    state = _author_material_candidate(root, state)
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=64)
    assert state.status == "completed"
    step_payload = _plan_step(root, state.workflow_id, "qa.diagnostics")
    step = WorkflowStep.model_validate(step_payload)
    request = SimpleNamespace(job_id=state.job_id, workflow_id=state.workflow_id)

    with pytest.raises(
        orchestration_service.OrchestrationArtifactConflict,
        match="no exact recovered InterruptedAttempt receipt",
    ):
        real_execute(
            root,
            root / "workflows" / state.workflow_id,
            request,
            step,
            input_fingerprint="a" * 64,
        )


def test_exact_qa_output_tampering_remains_an_artifact_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep exact authoritative QA files fail-closed after descendant separation."""

    root, state = _fast_workflow_to_material_author(monkeypatch, tmp_path)
    state = _author_material_candidate(root, state)
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=64)
    assert state.status == "completed"
    qa_step = _plan_step(root, state.workflow_id, "qa.run")
    report = root / str(
        next(
            item["path"]
            for item in qa_step["outputs"]
            if item["artifact_id"] == "qa.run.visual_report"
        )
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["warnings"].append("unexpected external mutation")
    report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    blocked = reconcile_workflow(state.job_id, state.workflow_id)
    assert blocked.status == "blocked"
    assert blocked.reason_code == "orchestration_artifact_conflict"
    qa_state = next(item for item in blocked.steps if item.step_id == "qa.run")
    assert qa_state.reason_code == "orchestration_artifact_conflict"


def test_nested_diagnostic_pass_tampering_remains_an_artifact_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Recurse through a terminal bundle so changed probe pixels stale completion."""

    root, state = _fast_workflow_to_material_author(monkeypatch, tmp_path)
    state = _author_material_candidate(root, state)
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=64)
    assert state.status == "completed"
    diagnostic_step = _plan_step(root, state.workflow_id, "qa.diagnostics")
    bundle_path = root / str(diagnostic_step["outputs"][0]["path"])
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    manifest_path = root / str(bundle["camera_probe_manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pass_path = root / str(manifest["probes"][0]["passes"][0]["path"])
    pass_path.write_bytes(b"unexpected external mutation")

    blocked = reconcile_workflow(state.job_id, state.workflow_id)

    assert blocked.status == "blocked"
    assert blocked.reason_code == "orchestration_artifact_conflict"
    diagnostic_state = next(
        item for item in blocked.steps if item.step_id == "qa.diagnostics"
    )
    assert diagnostic_state.reason_code == "orchestration_artifact_conflict"


def test_new_material_authoring_rejects_policy_downgrade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Do not let a new authored candidate silently fall back to legacy unbound placement."""

    root, state = _fast_workflow_to_material_author(monkeypatch, tmp_path)
    step = _plan_step(root, state.workflow_id, "material.author")
    candidate = root / str(step["parameters"]["candidate_plan_path"])
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["stage"] = "authored"
    payload.pop("surface_detail_binding_policy", None)
    candidate.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    current = next(item for item in state.steps if item.step_id == "material.author")

    with pytest.raises(RuntimeError, match="requires surface_detail_binding_policy=spatial_v1"):
        complete_workflow_step(
            state.job_id,
            state.workflow_id,
            "material.author",
            input_fingerprint=str(current.input_fingerprint),
            note="Attempted policy downgrade fixture.",
        )


@pytest.mark.parametrize("quality_status", ["needs_revision", "unscorable"])
def test_fast_preview_delivers_nonpassing_quality_for_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    quality_status: str,
) -> None:
    """Complete execution while preserving non-passing quality as visible evidence."""

    root, state = _fast_workflow_to_material_author(
        monkeypatch,
        tmp_path,
        quality_status=quality_status,
    )
    state = _author_material_candidate(root, state)
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=64)

    assert state.status == "completed"
    assert state.milestone == "delivered_for_review"
    assert state.quality_status == quality_status
    assert state.standard_workflow_recommended is True
    assert state.reason_code is None
    assert state.quality_report_path
    assert state.quality_report_sha256 == sha256_file(
        root / state.quality_report_path
    )
    assert len(list((root / "qa" / "runs").iterdir())) == 1


def test_unexpected_material_plan_change_is_artifact_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Block an unplanned canonical MaterialPlan change after exact promotion."""

    root, state = _fast_workflow_to_material_author(monkeypatch, tmp_path)
    state = _author_material_candidate(root, state)
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)
    assert state.current_step_id == "material.contract_validate"
    canonical = root / "analysis" / "material_plan.json"
    payload = json.loads(canonical.read_text(encoding="utf-8"))
    payload["global_notes"].append("unexpected external mutation")
    canonical.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    blocked = resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)
    assert blocked.status == "blocked"
    assert blocked.reason_code == "orchestration_artifact_conflict"
    step = next(
        item
        for item in blocked.steps
        if item.step_id == "material.contract_validate"
    )
    assert step.reason_code == "orchestration_artifact_conflict"
    assert "Do not reinterpret it as a quality risk" in (blocked.next_action or "")


def test_unexpected_scene_spec_change_stales_exact_agent_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep unexpected canonical SceneSpec changes fail-closed before host build."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    _install_fake_blender_host(monkeypatch)
    state = plan_workflow(
        "Create one static background exterior preview.",
        job_id="fast_scene_conflict",
        reference_path=_image(tmp_path / "reference.png"),
        execution_policy="background_exterior",
        delivery_scope="preview_only",
    )
    state = resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)
    root = workspace / state.job_id
    state = _author_modeling_plan(root, state)
    state = _author_background_scene(root, state)
    scene = root / "analysis" / "scene_spec.json"
    payload = json.loads(scene.read_text(encoding="utf-8"))
    payload["assumptions"].append("unexpected external mutation")
    scene.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    current = reconcile_workflow(state.job_id, state.workflow_id)
    assert current.status == "running"
    assert current.current_step_id == "background.fit"
    blocked = resume_workflow(state.job_id, state.workflow_id, max_host_steps=1)
    assert blocked.status == "blocked"
    assert blocked.reason_code == "orchestration_artifact_conflict"
    authored = next(
        item
        for item in blocked.steps
        if item.step_id == "geometry.background_author"
    )
    assert authored.status == "complete"
    fit = next(item for item in blocked.steps if item.step_id == "background.fit")
    assert fit.reason_code == "orchestration_artifact_conflict"


def test_optimization_approval_identity_survives_expected_consumption(
    tmp_path: Path,
) -> None:
    """Keep V0.7 approval identity stable when optimization consumes it once."""

    root = tmp_path / "portable_approval_asset"
    run_id = "v08-approval-test"
    run_root = root / "optimization" / "runs" / run_id
    run_root.mkdir(parents=True)
    review_plan = run_root / "review_plan.json"
    review_plan.write_text('{"fixture":true}\n', encoding="utf-8")
    approval_path = run_root / "optimization_approval.json"
    approval = OptimizationApproval(
        approval_id=f"approval.{run_id}",
        job_id=root.name,
        run_id=run_id,
        profile_id="fbx_interchange",
        plan_sha256=sha256_file(review_plan),
        review_sha256="1" * 64,
        profile_sha256="2" * 64,
        preflight_sha256="3" * 64,
        source_fingerprint="4" * 64,
        approval_note="Lifecycle fixture approval.",
        approved_at=datetime.now(UTC),
    )
    approval_path.write_text(
        approval.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    step = WorkflowStep(
        step_id="portable.plan_approval",
        title="Approve exact plan",
        phase="portable",
        execution_mode="specialized_approval",
        approval_gate="optimization_plan",
        parameters={"run_id": run_id, "profile_id": "fbx_interchange"},
    )
    before = orchestration_service._specialized_approval_identity(
        root,
        step,
        "0" * 64,
    )
    consumed = approval.model_copy(
        update={"used": True, "used_at": datetime.now(UTC)}
    )
    approval_path.write_text(
        consumed.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    after = orchestration_service._specialized_approval_identity(
        root,
        step,
        "9" * 64,
    )
    assert before == after
    artifacts = [
        ArtifactFreshness(
            artifact_id="portable.optimization_approval",
            path=f"optimization/runs/{run_id}/optimization_approval.json",
            sha256=sha256_file(approval_path),
            integrity="valid",
            currency="current",
            verification="partially_verified",
            reason="fixture",
        )
    ]
    assert orchestration_service._specialized_approval_valid(root, step, artifacts)


def test_interior_qa_approval_identity_survives_expected_consumption(
    tmp_path: Path,
) -> None:
    """Keep one interior camera-plan approval stable when its render consumes it."""

    root = tmp_path / "interior_approval_asset"
    run_id = "v08-interior-approval-test"
    run_root = root / "qa" / "interior" / "runs" / run_id
    run_root.mkdir(parents=True)
    plan_path = run_root / "plan.json"
    plan_path.write_text('{"fixture":true}\n', encoding="utf-8")
    approval_path = run_root / "plan_approval.json"
    approval = InteriorQAPlanApproval(
        approval_id=f"approval.{run_id}",
        job_id=root.name,
        run_id=run_id,
        plan_sha256=sha256_file(plan_path),
        source_fingerprint="1" * 64,
        approved_view_ids=["level_01.main_hall.entry"],
        approval_note="Approve the exact fixture camera plan.",
        approved_at=datetime.now(UTC).isoformat(),
    )
    approval_path.write_text(
        approval.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    step = WorkflowStep(
        step_id="interior_qa.plan_approval",
        title="Approve exact interior camera plan",
        phase="qa",
        execution_mode="specialized_approval",
        approval_gate="interior_qa_plan",
        parameters={"run_id": run_id},
    )
    before = orchestration_service._specialized_approval_identity(
        root,
        step,
        "0" * 64,
    )
    consumed = approval.model_copy(
        update={
            "status": "consumed",
            "consumed_at": datetime.now(UTC).isoformat(),
        }
    )
    approval_path.write_text(
        consumed.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    after = orchestration_service._specialized_approval_identity(
        root,
        step,
        "9" * 64,
    )

    assert before == after
    artifacts = [
        ArtifactFreshness(
            artifact_id="interior_qa.plan_approval.output",
            path=f"qa/interior/runs/{run_id}/plan_approval.json",
            sha256=sha256_file(approval_path),
            integrity="valid",
            currency="current",
            verification="partially_verified",
            reason="fixture",
        )
    ]
    assert orchestration_service._specialized_approval_valid(root, step, artifacts)


def test_material_promotion_hashes_manifest_relative_image_channels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bind promoted image materials to manifest-relative channel file hashes."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    job_id = "image_dependency_asset"
    workflow_id = "wf-image-dependency"
    root = tmp_path / job_id
    scene = json.loads(
        (ROOT / "examples" / "measured_box" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    scene["job_id"] = job_id
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(json.dumps(scene, indent=2) + "\n", encoding="utf-8")

    texture_root = root / "textures" / "mat.box"
    texture_root.mkdir(parents=True)
    channel_path = texture_root / "base_color.png"
    Image.new("RGB", (8, 8), (30, 90, 160)).save(channel_path)
    manifest_path = texture_root / "texture_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.box",
                "uv_set": "UVMap",
                "intended_scale_m": 1.0,
                "resolution": [8, 8],
                "source_type": "image",
                "channels": {
                    "base_color": {
                        "source": "image",
                        "path": "base_color.png",
                        "color_space": "sRGB",
                        "strength": 1.0,
                    }
                },
                "procedural": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate = (
        root
        / "workflows"
        / workflow_id
        / "artifacts"
        / "m"
        / "authored"
        / "material_plan.json"
    )
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": job_id,
                "scene_spec_path": "analysis/scene_spec.json",
                "stage": "authored",
                "materials": [
                    {
                        "material_id": "mat.box",
                        "label": "Box blue",
                        "shader_family": "standard_pbr",
                        "texture_strategy": "image",
                        "mapping": {
                            "mode": "uv",
                            "uv_set": "UVMap",
                            "real_world_scale_m": 1.0,
                        },
                        "texture_manifest": "textures/mat.box/texture_manifest.json",
                        "shader_recipe": None,
                        "export_profiles": ["blender_eevee"],
                        "evidence_status": "observed",
                        "confidence": 1.0,
                        "notes": [],
                    }
                ],
                "global_notes": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    receipt = promote_workflow_material_candidate(
        job_id,
        workflow_id,
        candidate_plan_path=(
            f"workflows/{workflow_id}/artifacts/m/authored/material_plan.json"
        ),
        receipt_path=f"workflows/{workflow_id}/artifacts/m/promotion.json",
        input_fingerprint="1" * 64,
    )

    assert receipt.dependency_sha256 == {
        "textures/mat.box/base_color.png": sha256_file(channel_path),
        "textures/mat.box/texture_manifest.json": sha256_file(manifest_path),
    }
