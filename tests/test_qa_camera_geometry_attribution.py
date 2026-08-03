from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.qa.camera_attribution import attribute_camera_geometry
from codex_blender_modeler.qa.diagnostic_models import (
    AssemblyDiagnosticEvidence,
    BoundedCameraDelta,
    CameraProbeResult,
    CameraProbeSemanticScore,
    QADiagnosticRequest,
    SemanticMaskBinding,
    SemanticShapeMetrics,
)
from codex_blender_modeler.qa.diagnostics import build_qa_diagnostic_report
from codex_blender_modeler.workspace import sha256_file

SHA = "b" * 64


def _probe(
    probe_id: str,
    overall_score: float,
    semantic_scores: dict[str, float],
    *,
    baseline: bool = False,
    primary_silhouette_score: float | None = None,
) -> CameraProbeResult:
    """Build one deterministic scored camera probe fixture."""

    return CameraProbeResult(
        probe_id=probe_id,
        is_baseline=baseline,
        status="scored",
        camera_delta=(
            BoundedCameraDelta()
            if baseline
            else BoundedCameraDelta(target_offset_norm=(0.02, 0.0))
        ),
        overall_score=overall_score,
        primary_silhouette_score=primary_silhouette_score,
        semantic_scores=[
            CameraProbeSemanticScore(
                semantic_id=semantic_id,
                scorable=True,
                score=score,
            )
            for semantic_id, score in semantic_scores.items()
        ],
        evidence_path=f"qa/runs/run-001/diagnostics/diag-001/probes/{probe_id}.json",
        evidence_sha256=SHA,
    )


def test_camera_attribution_requires_broad_probe_improvement() -> None:
    """Broad bounded-camera improvement with low residuals is classified as camera."""

    baseline = _probe("baseline", 0.5, {"weapon.body": 0.50, "weapon.trigger": 0.55}, baseline=True)
    improved = _probe("camera-01", 0.91, {"weapon.body": 0.92, "weapon.trigger": 0.90})

    result = attribute_camera_geometry(baseline, [improved])

    assert result.classification == "camera"
    assert result.camera_gain == pytest.approx(0.41)
    assert result.semantic_consensus_fraction == pytest.approx(1.0)
    assert result.geometry_residual_fraction == pytest.approx(0.0)


def test_camera_attribution_accepts_exact_silhouette_gain_with_stable_bboxes() -> None:
    """An angle-sensitive subject silhouette can identify camera error despite stable boxes."""

    baseline = _probe(
        "baseline",
        0.9,
        {"weapon.body": 0.9, "weapon.trigger": 0.9},
        baseline=True,
        primary_silhouette_score=0.52,
    )
    improved = _probe(
        "camera-01",
        0.9,
        {"weapon.body": 0.9, "weapon.trigger": 0.9},
        primary_silhouette_score=0.78,
    )

    result = attribute_camera_geometry(baseline, [improved])

    assert result.classification == "camera"
    assert result.camera_gain == pytest.approx(0.0)
    assert result.semantic_consensus_fraction == pytest.approx(0.0)
    assert result.primary_silhouette_gain == pytest.approx(0.26)
    assert result.baseline_primary_silhouette_score == pytest.approx(0.52)
    assert result.best_primary_silhouette_score == pytest.approx(0.78)


def test_geometry_attribution_keeps_low_semantic_residuals_distinct() -> None:
    """Persistent poor shapes without camera gain are classified as geometry."""

    baseline = _probe(
        "baseline",
        0.60,
        {"weapon.body": 0.52, "weapon.trigger": 0.61},
        baseline=True,
    )
    probe = _probe("camera-01", 0.61, {"weapon.body": 0.54, "weapon.trigger": 0.62})

    result = attribute_camera_geometry(baseline, [probe])

    assert result.classification == "geometry"
    assert result.geometry_residual_fraction == pytest.approx(1.0)


def test_assembly_attribution_uses_deterministic_failures() -> None:
    """Explicit cross-section failures can isolate an assembly problem."""

    baseline = _probe("baseline", 0.94, {"weapon.body": 0.94}, baseline=True)
    probe = _probe("camera-01", 0.94, {"weapon.body": 0.94})
    assembly = AssemblyDiagnosticEvidence(
        status="failed",
        required_failure_ids=["weapon.trigger.center_plane"],
    )

    result = attribute_camera_geometry(baseline, [probe], assembly=assembly)

    assert result.classification == "assembly"
    assert result.assembly_failure_ids == ["weapon.trigger.center_plane"]
    assert result.confidence == pytest.approx(0.85)


def test_mixed_attribution_preserves_camera_gain_and_shape_residual() -> None:
    """A useful camera correction does not hide residual semantic geometry mismatch."""

    baseline = _probe(
        "baseline",
        0.50,
        {"weapon.body": 0.50, "weapon.trigger": 0.45},
        baseline=True,
    )
    probe = _probe("camera-01", 0.78, {"weapon.body": 0.95, "weapon.trigger": 0.68})

    result = attribute_camera_geometry(baseline, [probe])

    assert result.classification == "mixed"
    assert result.camera_gain == pytest.approx(0.28)
    assert result.geometry_residual_fraction == pytest.approx(0.5)


def test_ambiguous_attribution_does_not_invent_a_cause() -> None:
    """Small probe changes with acceptable semantics remain explicitly ambiguous."""

    baseline = _probe("baseline", 0.90, {"weapon.body": 0.90}, baseline=True)
    probe = _probe("camera-01", 0.91, {"weapon.body": 0.91})

    result = attribute_camera_geometry(baseline, [probe])

    assert result.classification == "ambiguous"
    assert result.confidence == pytest.approx(0.35)


def test_semantic_axis_residual_identifies_geometry_when_bboxes_match() -> None:
    """Per-part orientation evidence prevents a bbox-only ambiguous diagnosis."""

    baseline = _probe("baseline", 0.92, {"weapon.trigger": 0.92}, baseline=True)
    probe = _probe("camera-01", 0.92, {"weapon.trigger": 0.92})
    shape = SemanticShapeMetrics(
        semantic_id="weapon.trigger",
        status="scored",
        width=128,
        height=128,
        reference_foreground_pixels=500,
        rendered_foreground_pixels=500,
        mask_iou=0.88,
        centroid_error_norm=0.0,
        area_ratio=1.0,
        boundary_f_score=0.84,
        symmetric_contour_distance_norm=0.02,
        oriented_axis_scorable=True,
        reference_axis_deg=15.0,
        rendered_axis_deg=65.0,
        undirected_axis_error_deg=50.0,
        reference_axis_eccentricity=0.9,
        rendered_axis_eccentricity=0.9,
    )

    result = attribute_camera_geometry(
        baseline,
        [probe],
        semantic_metrics=[shape],
    )

    assert result.classification == "geometry"
    assert result.geometry_residual_fraction == pytest.approx(1.0)
    assert result.semantic_shape_residual_ids == ["weapon.trigger"]
    assert result.semantic_orientation_residual_ids == ["weapon.trigger"]


def test_unscorable_baseline_remains_unscorable_without_assembly_evidence() -> None:
    """Missing baseline evidence cannot be converted into a geometry diagnosis."""

    baseline = CameraProbeResult(
        probe_id="baseline",
        is_baseline=True,
        status="unscorable",
        evidence_path="qa/runs/run-001/diagnostics/diag-001/probes/baseline.json",
        evidence_sha256=SHA,
        limitations=["primary semantic mask missing"],
    )

    result = attribute_camera_geometry(baseline, [])

    assert result.classification == "unscorable"
    assert result.baseline_score is None


def _write_text(path: Path, value: str) -> str:
    """Write a small fixture artifact and return its exact SHA-256."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return sha256_file(path)


def _write_mask(path: Path, box: tuple[int, int, int, int]) -> str:
    """Write a deterministic semantic mask fixture and return its hash."""

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", (64, 64), 0)
    ImageDraw.Draw(image).rectangle(box, fill=255)
    image.save(path)
    return sha256_file(path)


def _diagnostic_fixture(job_root: Path) -> tuple[Path, CameraProbeResult, CameraProbeResult]:
    """Create one complete hash-bound request and probe evidence fixture."""

    qa_root = job_root / "qa" / "runs" / "run-001"
    diagnostic_root = qa_root / "diagnostics" / "diag-001"
    source_request = qa_root / "request.json"
    source_report = qa_root / "visual_qa_report.json"
    source_manifest = qa_root / "render_pass_manifest.json"
    scene_spec = job_root / "analysis" / "scene_spec.json"
    source_request_hash = _write_text(source_request, '{"source":"request"}')
    source_report_hash = _write_text(source_report, '{"source":"report"}')
    source_manifest_hash = _write_text(source_manifest, '{"source":"passes"}')
    scene_hash = _write_text(scene_spec, '{"source":"scene"}')
    reference_mask = diagnostic_root / "masks" / "trigger.reference.png"
    rendered_mask = diagnostic_root / "masks" / "trigger.rendered.png"
    reference_mask_hash = _write_mask(reference_mask, (20, 20, 43, 39))
    rendered_mask_hash = _write_mask(rendered_mask, (21, 20, 44, 39))
    baseline_evidence = diagnostic_root / "probes" / "baseline.json"
    camera_evidence = diagnostic_root / "probes" / "camera-01.json"
    baseline_hash = _write_text(baseline_evidence, '{"probe":"baseline"}')
    camera_hash = _write_text(camera_evidence, '{"probe":"camera-01"}')

    request = QADiagnosticRequest(
        job_id="weapon_test",
        qa_run_id="run-001",
        diagnostic_id="diag-001",
        artifact_root="qa/runs/run-001/diagnostics/diag-001",
        visual_qa_request_path="qa/runs/run-001/request.json",
        visual_qa_request_sha256=source_request_hash,
        visual_qa_report_path="qa/runs/run-001/visual_qa_report.json",
        visual_qa_report_sha256=source_report_hash,
        render_pass_manifest_path="qa/runs/run-001/render_pass_manifest.json",
        render_pass_manifest_sha256=source_manifest_hash,
        scene_spec_sha256=scene_hash,
        semantic_masks=[
            SemanticMaskBinding(
                semantic_id="weapon.trigger",
                role="supporting",
                source_id="reference",
                confidence=0.9,
                reference_mask_path=(
                    "qa/runs/run-001/diagnostics/diag-001/masks/trigger.reference.png"
                ),
                reference_mask_sha256=reference_mask_hash,
                rendered_mask_path=(
                    "qa/runs/run-001/diagnostics/diag-001/masks/trigger.rendered.png"
                ),
                rendered_mask_sha256=rendered_mask_hash,
            )
        ],
    )
    request_path = diagnostic_root / "request.json"
    _write_text(request_path, request.model_dump_json(indent=2))
    baseline = _probe("baseline", 0.70, {"weapon.trigger": 0.70}, baseline=True)
    candidate = _probe("camera-01", 0.91, {"weapon.trigger": 0.91})
    baseline.evidence_sha256 = baseline_hash
    candidate.evidence_sha256 = camera_hash
    return request_path, baseline, candidate


def test_report_builder_verifies_exact_sources_masks_and_probe_evidence(
    tmp_path: Path,
) -> None:
    """The report builder accepts only current hash-bound run-owned evidence."""

    request_path, baseline, candidate = _diagnostic_fixture(tmp_path)

    report = build_qa_diagnostic_report(
        tmp_path,
        request_path,
        [baseline, candidate],
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert report.status == "completed"
    assert report.attribution.classification == "camera"
    assert report.semantic_metrics[0].semantic_id == "weapon.trigger"
    assert report.request_sha256 == sha256_file(request_path)
    assert report.advisory_only is True


def test_report_builder_rejects_a_stale_canonical_source(tmp_path: Path) -> None:
    """A SceneSpec mutation after request creation fails closed as stale evidence."""

    request_path, baseline, candidate = _diagnostic_fixture(tmp_path)
    (tmp_path / "analysis" / "scene_spec.json").write_text(
        '{"source":"tampered"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash mismatch"):
        build_qa_diagnostic_report(tmp_path, request_path, [baseline, candidate])


def test_legacy_job_without_semantic_masks_produces_unscorable_report(
    tmp_path: Path,
) -> None:
    """Missing explicit masks remain visible and never become fabricated bbox shapes."""

    request_path, baseline, _candidate = _diagnostic_fixture(tmp_path)
    request = QADiagnosticRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    request_path.write_text(
        request.model_copy(update={"semantic_masks": []}).model_dump_json(indent=2),
        encoding="utf-8",
    )
    unscorable_baseline = CameraProbeResult(
        probe_id="baseline",
        is_baseline=True,
        status="unscorable",
        evidence_path=baseline.evidence_path,
        evidence_sha256=baseline.evidence_sha256,
        limitations=["explicit semantic reference masks are unavailable"],
    )

    report = build_qa_diagnostic_report(
        tmp_path,
        request_path,
        [unscorable_baseline],
    )

    assert report.status == "unscorable"
    assert report.semantic_metrics == []
    assert any("no explicit evidence-backed" in value for value in report.limitations)
