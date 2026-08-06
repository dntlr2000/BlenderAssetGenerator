from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from pypdf import PdfReader

from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.diagnostic_models import (
    AssemblyDiagnosticEvidence,
    AssemblyMultiviewBundleEvidence,
    AuthoringRecommendation,
    BoundedCameraDelta,
    CameraProbeResult,
    CameraProbeSemanticScore,
    DiagnosticAttribution,
    QADiagnosticBundleManifest,
    QADiagnosticReport,
    QADiagnosticRequest,
    SemanticMaskBinding,
    SemanticShapeMetrics,
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
from codex_blender_modeler.reporting import (
    collect_job_report_payload,
    generate_job_pdf_report,
)
from codex_blender_modeler.reporting.models import ReportSource
from codex_blender_modeler.reporting.pdf_renderer import render_job_pdf
from codex_blender_modeler.workspace import sha256_file


def _write_json(path: Path, payload: dict) -> None:
    """Write one compact UTF-8 JSON fixture for the reporting tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    """Write one deterministic RGB image used as reference or report evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (96, 64), color).save(path)


def test_report_source_schema_rejects_absolute_and_traversal_paths() -> None:
    """Keep generated ReportSource schemas aligned with runtime path containment."""

    schema = ReportSource.model_json_schema()
    validator = Draft202012Validator(schema)
    base = {
        "kind": "visual_qa_report",
        "sha256": "a" * 64,
        "size_bytes": 1,
    }
    assert not list(validator.iter_errors({**base, "path": "qa/runs/report.json"}))
    unsafe_paths = (
        "/etc/passwd",
        "C:/Windows/system.ini",
        r"C:\Windows\system.ini",
        "../secret.json",
        "reports/../../secret.json",
        "reports//report.json",
        "reports/./report.json",
        "reports/",
    )
    for unsafe_path in unsafe_paths:
        assert list(validator.iter_errors({**base, "path": unsafe_path}))
        with pytest.raises(ValueError, match="normalized and job-relative"):
            ReportSource.model_validate({**base, "path": unsafe_path})


def _seed_material_report_job(tmp_path: Path, monkeypatch) -> Path:
    """Create one isolated job with canonical material reports and a safe swatch image."""

    workspace = tmp_path / "workspaces"
    root = workspace / "pdf_report_test"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = root / "input" / "reference.png"
    preview = root / "renders" / "preview.png"
    swatch = root / "renders" / "materials" / "mat.stone" / "swatch.png"
    _write_png(reference, (80, 130, 180))
    _write_png(preview, (90, 140, 90))
    _write_png(swatch, (110, 105, 95))
    _write_json(
        root / "job.json",
        {
            "job_id": "pdf_report_test",
            "mode": "concept",
            "project_version_created": "0.6.0",
            "reference_path": str(reference),
        },
    )
    spec = SceneSpec.model_validate(
        {
            "job_id": "pdf_report_test",
            "mode": "concept",
            "nominal_scene_size": [4.0, 2.0, 2.0],
            "sources": [
                {
                    "id": "reference",
                    "path": "input/reference.png",
                    "kind": "reference",
                }
            ],
            "materials": [
                {
                    "id": "mat.stone",
                    "name": "Stone",
                    "base_color": [0.5, 0.5, 0.5, 1.0],
                    "roughness": 0.7,
                    "metallic": 0.0,
                }
            ],
            "objects": [
                {
                    "id": "weapon.body",
                    "name": "Body",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [3.0, 1.0, 1.0],
                    },
                    "material_id": "mat.stone",
                    "tags": ["qa_role:primary"],
                    "evidence": [
                        {
                            "source_id": "reference",
                            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
                            "status": "observed",
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            "camera": {
                "projection": "PERSP",
                "location": [5.0, -8.0, 4.0],
                "target": [0.0, 0.0, 0.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 6.0,
                "resolution": [96, 64],
            },
        }
    )
    _write_json(root / "analysis" / "scene_spec.json", spec.model_dump(mode="json"))
    _write_json(
        root / "analysis" / "material_plan.json",
        {
            "schema_version": "0.5.0",
            "job_id": "pdf_report_test",
            "materials": [
                {
                    "material_id": "mat.stone",
                    "label": "Stone",
                    "shader_family": "rock",
                    "texture_strategy": "procedural",
                    "mapping": {"mode": "object"},
                }
            ],
        },
    )
    _write_json(
        root / "reports" / "material_contract_validation.json",
        {"ok": True, "passed": 3, "warnings": 0, "failed": 0},
    )
    _write_json(
        root / "reports" / "material_validation.json",
        {
            "ok": True,
            "summary": {"material_count": 1},
            "errors": [],
            "warnings": [],
            "materials": [
                {
                    "material_id": "mat.stone",
                    "source_type": "procedural",
                    "users": 1,
                    "node_count": 6,
                    "images": [],
                    "warnings": [],
                }
            ],
        },
    )
    _write_json(
        root / "reports" / "material_swatches.json",
        {
            "schema_version": "0.5.0",
            "job_id": "pdf_report_test",
            "material_count": 1,
            "swatches": [
                {
                    "material_id": "mat.stone",
                    "path": str(swatch),
                    "sha256": sha256_file(swatch),
                    "width": 96,
                    "height": 64,
                    "encoding": "png-rgb8",
                }
            ],
        },
    )
    return root


def _canonical_hashes(root: Path) -> dict[str, str]:
    """Hash every canonical fixture file so PDF generation can prove read-only behavior."""

    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_qa_companion_report(root: Path) -> str:
    """Create one exact QA companion bundle plus optional assembly multi-view report."""

    run_id = "run-companion"
    run_dir = root / "qa" / "runs" / run_id
    diagnostic_id = "camera-geometry-v1"
    diagnostic_root = run_dir / "diagnostics" / diagnostic_id
    attempt_root = diagnostic_root / "attempts" / "attempt-001"
    qa_request_path = run_dir / "request.json"
    pass_manifest_path = run_dir / "render_pass_manifest.json"
    visual_report_path = run_dir / "visual_qa_report.json"
    scene_path = root / "analysis" / "scene_spec.json"
    reference_path = root / "input" / "reference.png"
    spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    camera_hash = camera_fingerprint(spec)
    modeling_plan_path = root / "analysis" / "modeling_plan.json"
    _write_json(
        modeling_plan_path,
        {
            "schema_version": "0.4.0",
            "job_id": "pdf_report_test",
            "reference_analysis_path": "analysis/reference_analysis.json",
            "camera_solution_path": "analysis/camera_solution.json",
            "stage": "authored",
            "objects": [
                {
                    "id": "weapon.body",
                    "label": "Body",
                    "source_ids": ["reference"],
                    "scope_role": "primary",
                    "assembly_role": "root",
                }
            ],
            "assembly_consistency_policy": "spatial_v1",
            "assembly_frame": {
                "root_object_id": "weapon.body",
                "longitudinal_axis": "X",
                "lateral_axis": "Y",
                "vertical_axis": "Z",
                "evidence_status": "inferred",
            },
        },
    )
    reference_mask_path = run_dir / "reference_mask.png"
    _write_png(reference_mask_path, (255, 255, 255))
    pass_records: list[RenderPassRecord] = []
    for index, kind in enumerate(
        ("beauty", "silhouette", "object_id", "material_id", "normal", "depth", "wireframe")
    ):
        pass_path = run_dir / "passes" / f"{kind}.png"
        _write_png(pass_path, (20 + index * 15, 70, 120))
        pass_records.append(
            RenderPassRecord(
                kind=kind,  # type: ignore[arg-type]
                path=f"passes/{kind}.png",
                sha256=sha256_file(pass_path),
                width=96,
                height=64,
                encoding="png-rgb8",
            )
        )
    pass_manifest = RenderPassManifest(
        job_id="pdf_report_test",
        run_id=run_id,
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=camera_hash,
        build_fingerprint=str(
            collect_build_provenance(
                root,
                "pdf_report_test",
                scene_spec_path=scene_path,
            )["fingerprint"]
        ),
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="CPU",
        resolution=(96, 64),
        passes=pass_records,
    )
    _write_json(pass_manifest_path, pass_manifest.model_dump(mode="json"))
    qa_request = VisualQARequest(
        job_id="pdf_report_test",
        run_id=run_id,
        mode="concept",
        reference_path=str(reference_path.resolve()),
        reference_sha256=sha256_file(reference_path),
        reference_mask_path=str(reference_mask_path.resolve()),
        reference_mask_sha256=sha256_file(reference_mask_path),
        preview_path=str((run_dir / "passes" / "beauty.png").resolve()),
        preview_sha256=sha256_file(run_dir / "passes" / "beauty.png"),
        render_pass_manifest_path=str(pass_manifest_path.resolve()),
        render_pass_manifest_sha256=sha256_file(pass_manifest_path),
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=camera_hash,
    )
    _write_json(qa_request_path, qa_request.model_dump(mode="json"))
    _write_json(
        run_dir / "reference_mask_manifest.json",
        {
            "reference_sha256": qa_request.reference_sha256,
            "output_path": "reference_mask.png",
            "output_sha256": qa_request.reference_mask_sha256,
        },
    )
    visual_report = VisualQAReport(
        job_id="pdf_report_test",
        run_id=run_id,
        request_sha256=canonical_model_sha256(qa_request),
        camera_fingerprint=camera_hash,
        direct_metrics=DirectVisualMetrics(
            silhouette_iou=0.68,
            silhouette_union_fraction=0.8,
            global_bbox=BoundingBoxMetric(
                reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
                rendered_bbox_norm=(0.16, 0.14, 0.84, 0.86),
                center_error_norm=0.08,
                size_error_norm=0.11,
            ),
            overall_direct_score=0.72,
        ),
        generated_target_status="not_requested",
    )
    _write_json(visual_report_path, visual_report.model_dump(mode="json"))
    reference_mask = attempt_root / "masks" / "trigger.reference.png"
    rendered_mask = attempt_root / "masks" / "trigger.rendered.png"
    _write_png(reference_mask, (255, 255, 255))
    _write_png(rendered_mask, (250, 250, 250))
    role_map_path = attempt_root / "role_map.json"
    _write_json(role_map_path, {"fixture": "camera-role-map"})
    role_map_sha256 = sha256_file(role_map_path)
    camera_plan_path = attempt_root / "camera_probes" / "plan.json"
    camera_manifest_path = attempt_root / "camera_probes" / "render_manifest.json"
    _write_json(
        camera_plan_path,
        {
            "schema_version": "0.6.0",
            "diagnostic_kind": "bounded_camera_probe",
            "job_id": "pdf_report_test",
            "qa_run_id": run_id,
            "diagnostic_id": diagnostic_id,
            "role_map_sha256": role_map_sha256,
            "probes": [
                {
                    "probe_id": "baseline",
                    "camera_delta": BoundedCameraDelta().model_dump(mode="json"),
                },
                {
                    "probe_id": "camera-01",
                    "camera_delta": BoundedCameraDelta(
                        target_offset_norm=(0.02, 0.0)
                    ).model_dump(mode="json"),
                },
            ],
        },
    )
    probe_records = []
    for probe_id in ("baseline", "camera-01"):
        pass_records = []
        for index, kind in enumerate(("silhouette", "object_id")):
            path = attempt_root / "camera_probes" / "renders" / probe_id / f"{kind}.png"
            _write_png(path, (20 + index * 40, 80, 120))
            pass_records.append(
                {
                    "kind": kind,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256_file(path),
                }
            )
        probe_records.append({"probe_id": probe_id, "passes": pass_records})
    _write_json(
        camera_manifest_path,
        {
            "schema_version": "0.6.0",
            "diagnostic_kind": "bounded_camera_probe",
            "job_id": "pdf_report_test",
            "qa_run_id": run_id,
            "diagnostic_id": diagnostic_id,
            "probe_plan_sha256": sha256_file(camera_plan_path),
            "role_map_sha256": role_map_sha256,
            "probes": probe_records,
        },
    )
    request = QADiagnosticRequest(
        job_id="pdf_report_test",
        qa_run_id=run_id,
        diagnostic_id=diagnostic_id,
        artifact_root=f"qa/runs/{run_id}/diagnostics/{diagnostic_id}",
        visual_qa_request_path=f"qa/runs/{run_id}/request.json",
        visual_qa_request_sha256=sha256_file(qa_request_path),
        visual_qa_report_path=f"qa/runs/{run_id}/visual_qa_report.json",
        visual_qa_report_sha256=sha256_file(visual_report_path),
        render_pass_manifest_path=f"qa/runs/{run_id}/render_pass_manifest.json",
        render_pass_manifest_sha256=sha256_file(pass_manifest_path),
        scene_spec_sha256=sha256_file(root / "analysis" / "scene_spec.json"),
        modeling_plan_path="analysis/modeling_plan.json",
        modeling_plan_sha256=sha256_file(modeling_plan_path),
        camera_role_map_path=role_map_path.relative_to(root).as_posix(),
        camera_role_map_sha256=role_map_sha256,
        semantic_masks=[
            SemanticMaskBinding(
                semantic_id="weapon.trigger",
                role="supporting",
                source_id="reference",
                confidence=0.9,
                reference_mask_path=(
                    f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/"
                    "masks/trigger.reference.png"
                ),
                reference_mask_sha256=sha256_file(reference_mask),
                rendered_mask_path=(
                    f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/"
                    "masks/trigger.rendered.png"
                ),
                rendered_mask_sha256=sha256_file(rendered_mask),
            )
        ],
        max_camera_probes=4,
    )
    diagnostic_request_path = attempt_root / "request.json"
    _write_json(diagnostic_request_path, request.model_dump(mode="json"))
    evidence_path = (
        f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/"
        "camera_probes/render_manifest.json"
    )
    baseline = CameraProbeResult(
        probe_id="baseline",
        is_baseline=True,
        status="scored",
        overall_score=0.65,
        semantic_scores=[
            CameraProbeSemanticScore(
                semantic_id="weapon.trigger",
                scorable=True,
                score=0.64,
            )
        ],
        evidence_path=evidence_path,
        evidence_sha256=sha256_file(camera_manifest_path),
    )
    camera_probe = CameraProbeResult(
        probe_id="camera-01",
        status="scored",
        camera_delta=BoundedCameraDelta(target_offset_norm=(0.02, 0.0)),
        overall_score=0.78,
        semantic_scores=[
            CameraProbeSemanticScore(
                semantic_id="weapon.trigger",
                scorable=True,
                score=0.77,
            )
        ],
        evidence_path=evidence_path,
        evidence_sha256=sha256_file(camera_manifest_path),
    )
    report = QADiagnosticReport(
        job_id="pdf_report_test",
        qa_run_id=run_id,
        diagnostic_id=diagnostic_id,
        request_path=(
            f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/request.json"
        ),
        request_sha256=sha256_file(diagnostic_request_path),
        status="completed",
        semantic_metrics=[
            SemanticShapeMetrics(
                semantic_id="weapon.trigger",
                status="scored",
                width=96,
                height=64,
                reference_foreground_pixels=240,
                rendered_foreground_pixels=228,
                mask_iou=0.76,
                centroid_error_norm=0.035,
                area_ratio=0.95,
                boundary_f_score=0.81,
                symmetric_contour_distance_norm=0.021,
                oriented_axis_scorable=True,
                reference_axis_deg=88.0,
                rendered_axis_deg=84.0,
                undirected_axis_error_deg=4.0,
                reference_axis_eccentricity=0.84,
                rendered_axis_eccentricity=0.80,
            )
        ],
        camera_probes=[baseline, camera_probe],
        assembly_evidence=AssemblyDiagnosticEvidence(),
        attribution=DiagnosticAttribution(
            classification="camera",
            confidence=0.82,
            baseline_probe_id="baseline",
            best_probe_id="camera-01",
            baseline_score=0.65,
            best_score=0.78,
            camera_gain=0.13,
            semantic_consensus_fraction=1.0,
            geometry_residual_fraction=0.0,
            reasons=["A bounded camera probe improved the semantic evidence."],
        ),
        limitations=["PCA orientation is undirected."],
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    diagnostic_report_path = attempt_root / "report.json"
    assembly_run_id = "assembly-companion"
    assembly_root = root / "qa" / "assembly_sanity" / "runs" / assembly_run_id
    assembly_plan = assembly_root / "plan.json"
    assembly_manifest = assembly_root / "render_manifest.json"
    assembly_report = assembly_root / "report.json"
    blend_path = root / "blender" / "scene.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    blend_path.write_bytes(b"assembly-companion-blend")
    target_ids = ["weapon.body", "weapon.trigger"]
    view_specs = [
        ("front", [1.0, 0.0, 0.0], "vertical"),
        ("right", [0.0, 1.0, 0.0], "vertical"),
        ("top", [0.0, 0.0, 1.0], "longitudinal"),
        ("rear", [-1.0, 0.0, 0.0], "vertical"),
        ("oblique", [0.577, 0.577, 0.577], "vertical"),
    ]
    assembly_plan_payload = {
        "schema_version": "0.6.0",
        "diagnostic_kind": "assembly_multiview_sanity",
        "canonical_v06_qa_run": False,
        "job_id": "pdf_report_test",
        "run_id": assembly_run_id,
        "scene_spec_path": "analysis/scene_spec.json",
        "scene_spec_sha256": sha256_file(root / "analysis" / "scene_spec.json"),
        "modeling_plan_path": "analysis/modeling_plan.json",
        "modeling_plan_sha256": sha256_file(modeling_plan_path),
        "source_blend_path": "blender/scene.blend",
        "source_blend_sha256": sha256_file(blend_path),
        "build_fingerprint": "1" * 64,
        "source_fingerprint": "2" * 64,
        "assembly_frame": {
            "root_object_id": "weapon.body",
            "longitudinal_axis": "X",
            "lateral_axis": "Y",
            "vertical_axis": "Z",
        },
        "target_ids": target_ids,
        "resolution": [128, 128],
        "views": [
            {
                "view_id": view_id,
                "camera_direction_frame": direction,
                "screen_up_role": up_role,
                "target_ids": target_ids,
            }
            for view_id, direction, up_role in view_specs
        ],
        "reference_sources": [],
        "reference_comparison_mode": "structural_only",
        "created_at": "2026-08-03T00:00:00Z",
        "limitations": ["No calibrated side-view reference was supplied."],
    }
    _write_json(assembly_plan, assembly_plan_payload)
    rendered_views = []
    for view_id, _direction, _up_role in view_specs:
        pass_records = []
        for index, kind in enumerate(("beauty", "silhouette", "object_id", "wireframe")):
            path = assembly_root / "views" / view_id / f"{kind}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (128, 128), (30 + index * 20, 60, 90)).save(path)
            pass_records.append(
                {
                    "kind": kind,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256_file(path),
                    "width": 128,
                    "height": 128,
                    "encoding": "png-rgb8",
                }
            )
        rendered_views.append(
            {
                "view_id": view_id,
                "camera": {"type": "PERSP"},
                "target_ids": target_ids,
                "passes": pass_records,
            }
        )
    assembly_evaluation = {
        "policy": "spatial_v1",
        "status": "passed",
        "ok": True,
        "checks": [],
    }
    assembly_manifest_payload = {
        "schema_version": "0.6.0",
        "diagnostic_kind": "assembly_multiview_sanity",
        "canonical_v06_qa_run": False,
        "job_id": "pdf_report_test",
        "run_id": assembly_run_id,
        "plan_sha256": sha256_file(assembly_plan),
        "scene_spec_sha256": sha256_file(root / "analysis" / "scene_spec.json"),
        "modeling_plan_sha256": sha256_file(modeling_plan_path),
        "source_blend_path": "blender/scene.blend",
        "source_blend_sha256": sha256_file(blend_path),
        "build_fingerprint": "1" * 64,
        "blender_version": "5.0.1",
        "render_engine": "BLENDER_EEVEE",
        "render_device": "CPU",
        "resolution": [128, 128],
        "object_id_colors": {"weapon.body": "#ff0000", "weapon.trigger": "#00ff00"},
        "assembly_frame_bounds": {"min": [-1.0, -1.0, -1.0], "max": [1.0, 1.0, 1.0]},
        "assembly_evaluation": assembly_evaluation,
        "views": rendered_views,
        "warnings": [],
    }
    _write_json(assembly_manifest, assembly_manifest_payload)
    _write_json(
        assembly_report,
        {
            "schema_version": "0.6.0",
            "diagnostic_kind": "assembly_multiview_sanity",
            "job_id": "pdf_report_test",
            "run_id": assembly_run_id,
            "plan_sha256": sha256_file(assembly_plan),
            "render_manifest_sha256": sha256_file(assembly_manifest),
            "scene_spec_sha256": sha256_file(root / "analysis" / "scene_spec.json"),
            "modeling_plan_sha256": sha256_file(modeling_plan_path),
            "source_blend_sha256": sha256_file(blend_path),
            "build_fingerprint": "1" * 64,
            "structural_status": "warning",
            "reference_comparison_status": "unscorable",
            "reference_comparison_note": "Structural-only fixture.",
            "quality_claimed": False,
            "semantic_visibility_fraction": 0.8,
            "target_ids": target_ids,
            "visible_target_ids": ["weapon.body"],
            "unseen_target_ids": ["weapon.trigger"],
            "view_coverage": [
                {
                    "view_id": view_id,
                    "visible_target_ids": ["weapon.body"],
                    "unseen_target_ids": ["weapon.trigger"],
                    "semantic_visibility_fraction": 0.5,
                }
                for view_id, _direction, _up_role in view_specs
            ],
            "assembly_evaluation": assembly_evaluation,
            "findings": [
                {
                    "finding_id": "visibility.trigger",
                    "category": "visibility",
                    "severity": "warning",
                    "target_ids": ["weapon.trigger"],
                    "view_ids": ["front"],
                    "description": "Trigger needs another structural view.",
                    "evidence_paths": [],
                }
            ],
            "limitations": ["No calibrated side-view reference was supplied."],
            "generated_at": "2026-08-03T00:00:00Z",
        },
    )
    report = report.model_copy(
        update={
            "assembly_evidence": AssemblyDiagnosticEvidence(
                status="warning",
                report_path=(
                    f"qa/assembly_sanity/runs/{assembly_run_id}/report.json"
                ),
                report_sha256=sha256_file(assembly_report),
                warning_ids=["visibility.trigger"],
                limitations=[
                    "Five-view evaluated bounds, visibility, and declared or inferred "
                    "signed axes are structural-consistency evidence, not proof of "
                    "real-world facing, triangle-level clearance, or kinematics."
                ],
            ),
            "authoring_recommendation": AuthoringRecommendation(
                action="camera_recalibration",
                reason_ids=["attribution.camera"],
                rationale=[
                    *report.attribution.reasons,
                    "Review the comparison-camera calibration before authoring geometry.",
                ],
            ),
        }
    )
    _write_json(diagnostic_report_path, report.model_dump(mode="json"))
    bundle = QADiagnosticBundleManifest(
        job_id="pdf_report_test",
        qa_run_id=run_id,
        diagnostic_id=diagnostic_id,
        visual_qa_report_path=f"qa/runs/{run_id}/visual_qa_report.json",
        visual_qa_report_sha256=sha256_file(visual_report_path),
        diagnostic_request_path=(
            f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/request.json"
        ),
        diagnostic_request_sha256=sha256_file(diagnostic_request_path),
        diagnostic_report_path=(
            f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/report.json"
        ),
        diagnostic_report_sha256=sha256_file(diagnostic_report_path),
        camera_probe_plan_path=(
            f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/camera_probes/plan.json"
        ),
        camera_probe_plan_sha256=sha256_file(camera_plan_path),
        camera_probe_manifest_path=(
            f"qa/runs/{run_id}/diagnostics/{diagnostic_id}/attempts/attempt-001/"
            "camera_probes/render_manifest.json"
        ),
        camera_probe_manifest_sha256=sha256_file(camera_manifest_path),
        assembly_multiview=AssemblyMultiviewBundleEvidence(
            status="warning",
            run_id=assembly_run_id,
            plan_path=(
                f"qa/assembly_sanity/runs/{assembly_run_id}/plan.json"
            ),
            plan_sha256=sha256_file(assembly_plan),
            report_path=(
                f"qa/assembly_sanity/runs/{assembly_run_id}/report.json"
            ),
            report_sha256=sha256_file(assembly_report),
            render_manifest_path=(
                f"qa/assembly_sanity/runs/{assembly_run_id}/render_manifest.json"
            ),
            render_manifest_sha256=sha256_file(assembly_manifest),
            reference_comparison_status="unscorable",
        ),
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    _write_json(
        diagnostic_root / "bundle_manifest.json",
        bundle.model_dump(mode="json"),
    )
    return run_id


def test_material_pdf_is_human_readable_hashed_and_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Generate a material PDF with safe provenance without mutating canonical job files."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    before = _canonical_hashes(root)

    result = generate_job_pdf_report("pdf_report_test", scope="material")

    pdf_path = Path(result["pdf"])
    manifest_path = Path(result["manifest"])
    assert pdf_path == tmp_path / "output" / "pdf" / "pdf_report_test" / "material_report.pdf"
    assert pdf_path.is_file()
    assert manifest_path.is_file()
    assert _canonical_hashes(root) == before
    assert sha256_file(pdf_path) == result["pdf_sha256"]

    reader = PdfReader(pdf_path)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) >= 2
    assert "pdf_report_test" in extracted

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "human_report_manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=None).validate(manifest)
    assert manifest["source_fingerprint"] == result["source_fingerprint"]
    assert manifest["pdf_sha256"] == result["pdf_sha256"]
    assert all(not Path(source["path"]).is_absolute() for source in manifest["sources"])
    assert all(str(tmp_path) not in source["path"] for source in manifest["sources"])
    repeated = collect_job_report_payload("pdf_report_test", "material")
    assert repeated["source_fingerprint"] == result["source_fingerprint"]


def test_external_report_image_is_skipped_without_path_disclosure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject report images outside the job while retaining a useful warning and PDF."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    outside = tmp_path / "external-swatch.png"
    _write_png(outside, (255, 0, 0))
    manifest_path = root / "reports" / "material_swatches.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["swatches"][0]["path"] = str(outside)
    _write_json(manifest_path, manifest)

    payload = collect_job_report_payload("pdf_report_test", "material")

    assert payload["images"]["material_swatches"] == []
    assert any("Skipped an external report asset" in item for item in payload["warnings"])
    assert all(str(outside) not in source.path for source in payload["sources"])


def test_fast_quality_warning_is_prominent_on_qa_pdf_cover(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Show delivered execution and needs-revision quality separately on page one."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    quality_path = (
        root
        / "reports"
        / "background_delivery"
        / "wf-quality_quality.json"
    )
    _write_json(
        quality_path,
        {
            "schema_version": "0.8.0",
            "job_id": "pdf_report_test",
            "workflow_id": "wf-quality",
            "execution_status": "completed",
            "delivery_status": "ready_for_review",
            "quality_status": "needs_revision",
            "quality_accepted": False,
            "standard_workflow_recommended": True,
            "overall_direct_score": 0.706882,
            "primary_silhouette_score": 0.690166,
            "primary_high_findings": ["quality.primary_silhouette"],
            "decorative_warnings": ["direct.environment.rocks"],
        },
    )

    result = generate_job_pdf_report(
        "pdf_report_test",
        scope="qa",
        qa_run_id=None,
        background_quality_report_path=quality_path.relative_to(root).as_posix(),
        output_path=tmp_path / "quality-review.pdf",
    )

    reader = PdfReader(Path(result["pdf"]))
    first_page = reader.pages[0].extract_text() or ""
    assert "needs_revision" in first_page
    assert "Direct score: 0.706882" in first_page
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert any(
        source["kind"] == "background_quality_report"
        and source["sha256"] == sha256_file(quality_path)
        for source in manifest["sources"]
    )


def test_stale_swatch_is_excluded_from_human_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Exclude changed visual evidence instead of presenting it under an obsolete hash."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    swatch = root / "renders" / "materials" / "mat.stone" / "swatch.png"
    _write_png(swatch, (0, 0, 0))

    payload = collect_job_report_payload("pdf_report_test", "material")

    assert payload["images"]["material_swatches"] == []
    assert any("Skipped stale report evidence" in item for item in payload["warnings"])


def test_pdf_report_rejects_unknown_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject presentation scopes outside the four public reporting contracts."""

    _seed_material_report_job(tmp_path, monkeypatch)
    try:
        collect_job_report_payload("pdf_report_test", "unknown")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "scope must be one of" in str(exc)
    else:
        raise AssertionError("Unknown report scope was accepted")


def test_applied_qa_pdf_includes_revision_and_convergence_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Render accepted revision evidence instead of reporting only pre-apply candidates."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = "run-applied"
    run_dir = root / "qa" / "runs" / run_id
    beauty_path = run_dir / "passes" / "beauty.png"
    _write_png(beauty_path, (45, 65, 85))
    _write_json(
        run_dir / "render_pass_manifest.json",
        {
            "passes": [
                {
                    "kind": "beauty",
                    "path": "passes/beauty.png",
                    "sha256": sha256_file(beauty_path),
                }
            ]
        },
    )
    _write_json(
        run_dir / "visual_qa_report.json",
        {
            "direct_metrics": {
                "overall_direct_score": 0.6,
                "silhouette_iou": 0.5,
                "global_bbox": {
                    "center_error_norm": 0.1,
                    "size_error_norm": 0.2,
                },
            },
            "findings": [
                {
                    "id": "direct.position.asset.body",
                    "severity": "medium",
                    "issue_type": "position",
                    "target_ids": ["asset.body"],
                    "description": "Direct fixture mismatch.",
                    "evidence_sources": ["direct_reference"],
                    "confidence": 0.9,
                },
                {
                    "id": "advisory.color.asset.body",
                    "severity": "low",
                    "issue_type": "color_block",
                    "target_ids": ["asset.body"],
                    "description": "Generated target advisory only.",
                    "evidence_sources": ["generated_target"],
                    "confidence": 0.25,
                },
                {
                    "id": "direct.group_position.asset.main",
                    "severity": "medium",
                    "issue_type": "position",
                    "target_ids": ["asset.body", "asset.detail"],
                    "description": "Coherent group candidate bundle.",
                    "evidence_sources": ["direct_reference"],
                    "confidence": 0.8,
                },
            ],
        },
    )
    _write_json(
        run_dir / "revision_candidates.json",
        {
            "candidates": [
                {"id": "c1", "finding_id": "direct.position.asset.body"},
                {
                    "id": "group-body",
                    "finding_id": "direct.group_position.asset.main",
                },
                {
                    "id": "group-detail",
                    "finding_id": "direct.group_position.asset.main",
                },
            ]
        },
    )
    _write_json(run_dir / "revision_plan.json", {"operations": [{"candidate_id": "c1"}]})
    _write_json(run_dir / "revision_approval.json", {"used": True})
    _write_json(
        run_dir / "application_report.json",
        {
            "status": "accepted",
            "approved_candidate_ids": ["c1"],
            "changes": [
                {
                    "target_id": "asset.body",
                    "path": ["transform", "location"],
                    "before": [0, 0, 0],
                    "after": [1, 0, 0],
                }
            ],
        },
    )
    _write_json(
        run_dir / "convergence.json",
        {
            "before_direct_score": 0.6,
            "after_direct_score": 0.7,
            "score_delta": 0.1,
            "status": "improved",
            "reasons": ["Direct-reference score improved."],
        },
    )

    payload = collect_job_report_payload("pdf_report_test", "qa", qa_run_id=run_id)
    assert "revision_application" in payload["documents"]
    assert "convergence" in payload["documents"]
    assert any(source.kind == "revision_application" for source in payload["sources"])
    result = generate_job_pdf_report("pdf_report_test", scope="qa", qa_run_id=run_id)
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )
    assert "0.7" in extracted
    assert "asset.body" in extracted
    assert "직접 QA 발견: 1개" in extracted
    assert "생성 타깃 보조 발견: 1개" in extracted
    assert "일관 그룹 이동 제안: 1개 묶음" in extracted
    assert "Direct fixture mismatch." in extracted
    assert "Generated target advisory only." in extracted
    assert "Coherent group candidate bundle." in extracted
    assert "일반 후보: 1개" in extracted
    assert "그룹 이동 묶음: 1개" in extracted
    assert "그룹 member 연산: 2개" in extracted
    assert "수정 결과" in extracted
    assert "승인 전 QA beauty" in extracted
    assert "QA beauty는 승인 수정 전 기준선" in extracted


def test_qa_pdf_collects_exact_companion_and_multiview_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Render advisory diagnostics while preserving the canonical V0.6 direct score."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = _seed_qa_companion_report(root)

    payload = collect_job_report_payload("pdf_report_test", "qa", qa_run_id=run_id)

    assert "qa_diagnostic_request" in payload["documents"]
    assert "qa_diagnostic_report" in payload["documents"]
    assert "qa_diagnostic_bundle" in payload["documents"]
    assert "assembly_sanity_plan" in payload["documents"]
    assert "assembly_sanity_render_manifest" in payload["documents"]
    assert "assembly_sanity_report" in payload["documents"]
    assembly_views = payload["images"]["assembly_sanity_views"]
    assert [item["view_id"] for item in assembly_views] == [
        "front",
        "right",
        "top",
        "rear",
        "oblique",
    ]
    assert all(item["beauty"]["path"] for item in assembly_views)
    assert all(item["wireframe"]["path"] for item in assembly_views)
    source_kinds = {source.kind for source in payload["sources"]}
    assert {
        "qa_diagnostic_request",
        "qa_diagnostic_report",
        "qa_diagnostic_bundle",
        "assembly_sanity_plan",
        "assembly_sanity_render_manifest",
        "assembly_sanity_report",
    } <= source_kinds
    assert sum(kind.startswith("assembly_sanity_view:") for kind in source_kinds) == 20
    full_payload = collect_job_report_payload(
        "pdf_report_test",
        "full",
        qa_run_id=run_id,
    )
    assert "qa_diagnostic_report" in full_payload["documents"]
    assert "assembly_sanity_report" in full_payload["documents"]

    result = generate_job_pdf_report(
        "pdf_report_test",
        scope="qa",
        qa_run_id=run_id,
        output_path=tmp_path / "companion-report.pdf",
    )
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )
    assert "canonical V0.6 direct score shown above is unchanged" in extracted
    assert "Camera / Geometry / Assembly Companion" in extracted
    assert "weapon.trigger" in extracted
    assert "Assembly multi-view" in extracted
    assert "Exterior five-view geometry review" in extracted
    assert all(view_id in extracted for view_id in ("front", "right", "top", "rear", "oblique"))
    assert "Reference similarity is unscorable" in extracted
    assert "No calibrated side-view reference was supplied" in extracted


def test_build_pdf_collects_an_explicit_standalone_assembly_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Include one exact pre-material five-view run without requiring a canonical QA run."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    _seed_qa_companion_report(root)

    payload = collect_job_report_payload(
        "pdf_report_test",
        "build",
        assembly_sanity_run_id="assembly-companion",
    )

    assert payload["qa_run_id"] is None
    assert payload["assembly_sanity_run_id"] == "assembly-companion"
    assert "qa_diagnostic_report" not in payload["documents"]
    assert "assembly_sanity_plan" in payload["documents"]
    assert "assembly_sanity_render_manifest" in payload["documents"]
    assert "assembly_sanity_report" in payload["documents"]
    assert len(payload["images"]["assembly_sanity_views"]) == 5

    result = generate_job_pdf_report(
        "pdf_report_test",
        scope="build",
        assembly_sanity_run_id="assembly-companion",
        output_path=tmp_path / "standalone-assembly-build.pdf",
    )
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )
    assert result["assembly_sanity_run_id"] == "assembly-companion"
    assert "Exterior five-view geometry review" in extracted
    assert "advisory-only" in extracted
    assert "wireframe images remain" in extracted


def test_pdf_renders_v04_reentry_and_redesign_assessment_from_review_json(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Project v2 geometry-review decisions without treating the PDF as authority."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    _seed_qa_companion_report(root)
    payload = collect_job_report_payload(
        "pdf_report_test",
        "build",
        assembly_sanity_run_id="assembly-companion",
    )
    report = payload["documents"]["assembly_sanity_report"]
    report["review_policy"] = "exterior_geometry_review_v2"
    report["geometry_review"] = {
        "outcome": "v04_reentry_required",
        "reference_similarity_status": "unscorable",
        "reference_unscorable_reason": "no_calibrated_per_view_references",
        "v04_reentry": "required",
        "redesign_assessment": "manual_review_required",
        "redesign_scopes": [
            "geometry_recipe",
            "semantic_recomposition",
            "assembly",
        ],
        "reason_finding_ids": ["visibility.all_views"],
        "automatic_revision_authorized": False,
    }
    output = tmp_path / "geometry-review-v2.pdf"

    render_job_pdf(payload, output)

    extracted = "\n".join(page.extract_text() or "" for page in PdfReader(output).pages)
    assert "v04_reentry_required" in extracted
    assert "V0.4 re-entry" in extracted
    assert "manual_review_required" in extracted
    assert "geometry_recipe, semantic_recomposition, assembly" in extracted
    assert "No calibrated per-view reference exists" in extracted
    assert "machine JSON remain authoritative" in extracted


def test_stale_standalone_assembly_image_is_excluded_from_build_pdf_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a five-view run when one manifest-bound image changes after publication."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    _seed_qa_companion_report(root)
    beauty = (
        root
        / "qa"
        / "assembly_sanity"
        / "runs"
        / "assembly-companion"
        / "views"
        / "front"
        / "beauty.png"
    )
    Image.new("RGB", (128, 128), (240, 10, 10)).save(beauty)

    with pytest.raises(
        ValueError,
        match="Explicit assembly-sanity run is incomplete, stale, or unavailable",
    ):
        collect_job_report_payload(
            "pdf_report_test",
            "build",
            assembly_sanity_run_id="assembly-companion",
        )


def test_legacy_qa_pdf_warns_when_companion_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A legacy QA run remains reportable when companion diagnostics do not exist."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = "run-legacy"
    run_dir = root / "qa" / "runs" / run_id
    _write_json(run_dir / "request.json", {"run_id": run_id})
    _write_json(run_dir / "render_pass_manifest.json", {"passes": []})
    _write_json(
        run_dir / "visual_qa_report.json",
        {
            "direct_metrics": {
                "overall_direct_score": 0.55,
                "silhouette_iou": 0.5,
                "global_bbox": {
                    "center_error_norm": 0.1,
                    "size_error_norm": 0.2,
                },
            },
            "findings": [],
        },
    )

    payload = collect_job_report_payload("pdf_report_test", "qa", qa_run_id=run_id)

    assert "qa_diagnostic_report" not in payload["documents"]
    assert any(
        "unavailable for this legacy or standalone QA run" in item
        for item in payload["warnings"]
    )
    result = generate_job_pdf_report(
        "pdf_report_test",
        scope="qa",
        qa_run_id=run_id,
        output_path=tmp_path / "legacy-report.pdf",
    )
    assert Path(result["pdf"]).is_file()


def test_stale_companion_report_is_excluded_without_blocking_qa_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A changed report breaks its bundle binding but not legacy QA PDF generation."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = _seed_qa_companion_report(root)
    report_path = (
        root
        / "qa"
        / "runs"
        / run_id
        / "diagnostics"
        / "camera-geometry-v1"
        / "attempts"
        / "attempt-001"
        / "report.json"
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["generated_at"] = "2026-08-03T12:00:00Z"
    _write_json(report_path, payload)

    collected = collect_job_report_payload(
        "pdf_report_test",
        "qa",
        qa_run_id=run_id,
    )

    assert "qa_diagnostic_report" not in collected["documents"]
    assert any("malformed and unavailable" in item for item in collected["warnings"])
    result = generate_job_pdf_report(
        "pdf_report_test",
        scope="qa",
        qa_run_id=run_id,
        output_path=tmp_path / "stale-companion-report.pdf",
    )
    assert Path(result["pdf"]).is_file()


def test_stale_assembly_report_invalidates_its_bound_companion_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A changed multi-view report invalidates the terminal bundle used by the PDF."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = _seed_qa_companion_report(root)
    assembly_path = (
        root
        / "qa"
        / "assembly_sanity"
        / "runs"
        / "assembly-companion"
        / "report.json"
    )
    payload = json.loads(assembly_path.read_text(encoding="utf-8"))
    payload["structural_status"] = "passed"
    _write_json(assembly_path, payload)

    collected = collect_job_report_payload(
        "pdf_report_test",
        "qa",
        qa_run_id=run_id,
    )

    assert "qa_diagnostic_report" not in collected["documents"]
    assert "assembly_sanity_report" not in collected["documents"]
    assert any("malformed and unavailable" in item for item in collected["warnings"])


def test_unapproved_qa_pdf_labels_plan_and_beauty_as_pre_apply(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Mark an unapproved RevisionPlan and its QA beauty as pre-application evidence."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = "run-unapproved"
    run_dir = root / "qa" / "runs" / run_id
    beauty_path = run_dir / "passes" / "beauty.png"
    _write_png(beauty_path, (55, 75, 95))
    _write_json(
        run_dir / "render_pass_manifest.json",
        {
            "passes": [
                {
                    "kind": "beauty",
                    "path": "passes/beauty.png",
                    "sha256": sha256_file(beauty_path),
                }
            ]
        },
    )
    _write_json(
        run_dir / "visual_qa_report.json",
        {
            "direct_metrics": {
                "overall_direct_score": 0.5,
                "silhouette_iou": 0.4,
                "global_bbox": {
                    "center_error_norm": 0.1,
                    "size_error_norm": 0.2,
                },
            },
            "findings": [],
        },
    )
    _write_json(run_dir / "revision_candidates.json", {"candidates": []})
    _write_json(run_dir / "revision_plan.json", {"operations": []})

    result = generate_job_pdf_report("pdf_report_test", scope="qa", qa_run_id=run_id)
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )

    assert "수정 계획" in extracted
    assert "승인 대기" in extracted
    assert "현재 QA 기준 프리뷰 (후보 적용 전)" in extracted
    assert "아직 적용되지 않았습니다" in extracted
