from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ..workspace import file_exists, sha256_file
from .camera_attribution import AttributionThresholds, attribute_camera_geometry
from .diagnostic_models import (
    AssemblyDiagnosticEvidence,
    CameraProbeResult,
    QADiagnosticReport,
    QADiagnosticRequest,
    SemanticShapeMetrics,
)
from .semantic_shape import compare_semantic_masks


def _resolve_job_relative_path(job_root: Path, value: str) -> Path:
    """Resolve one validated POSIX job-relative path without permitting escape."""

    resolved_root = job_root.resolve()
    candidate = (resolved_root / Path(*PurePosixPath(value).parts)).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"diagnostic artifact escapes the job workspace: {value}") from exc
    return candidate


def _job_relative_path(job_root: Path, path: Path) -> str:
    """Return a normalized POSIX path for one artifact contained by the job root."""

    resolved_root = job_root.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"diagnostic request is outside the job workspace: {path}") from exc


def _verify_exact_hash(job_root: Path, relative_path: str, expected_sha256: str) -> Path:
    """Require one declared artifact to exist and match its exact SHA-256 binding."""

    path = _resolve_job_relative_path(job_root, relative_path)
    if not file_exists(path):
        raise FileNotFoundError(f"diagnostic artifact does not exist: {relative_path}")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"diagnostic artifact hash mismatch for {relative_path}: "
            f"expected {expected_sha256}, found {actual_sha256}"
        )
    return path


def _verify_request_sources(job_root: Path, request: QADiagnosticRequest) -> None:
    """Verify every exact source and semantic-mask hash frozen by a request."""

    declared_sources = [
        (request.visual_qa_request_path, request.visual_qa_request_sha256),
        (request.visual_qa_report_path, request.visual_qa_report_sha256),
        (request.render_pass_manifest_path, request.render_pass_manifest_sha256),
        (request.scene_spec_path, request.scene_spec_sha256),
    ]
    if request.modeling_plan_path and request.modeling_plan_sha256:
        declared_sources.append((request.modeling_plan_path, request.modeling_plan_sha256))
    if request.camera_role_map_path and request.camera_role_map_sha256:
        declared_sources.append(
            (request.camera_role_map_path, request.camera_role_map_sha256)
        )
    if (
        request.semantic_reference_manifest_path
        and request.semantic_reference_manifest_sha256
    ):
        declared_sources.append(
            (
                request.semantic_reference_manifest_path,
                request.semantic_reference_manifest_sha256,
            )
        )
    if request.assembly_report_path and request.assembly_report_sha256:
        declared_sources.append((request.assembly_report_path, request.assembly_report_sha256))
    if request.primary_reference_mask_path and request.primary_reference_mask_sha256:
        declared_sources.append(
            (
                request.primary_reference_mask_path,
                request.primary_reference_mask_sha256,
            )
        )
    for relative_path, expected_sha256 in declared_sources:
        _verify_exact_hash(job_root, relative_path, expected_sha256)
    for binding in request.semantic_masks:
        _verify_exact_hash(
            job_root,
            binding.reference_mask_path,
            binding.reference_mask_sha256,
        )
        _verify_exact_hash(
            job_root,
            binding.rendered_mask_path,
            binding.rendered_mask_sha256,
        )


def load_qa_diagnostic_request(
    job_root: Path,
    request_path: Path,
) -> QADiagnosticRequest:
    """Load a run-owned request and fail closed on stale or escaped source evidence."""

    relative_request_path = _job_relative_path(job_root, request_path)
    if not file_exists(request_path):
        raise FileNotFoundError(f"QA diagnostic request does not exist: {request_path}")
    request = QADiagnosticRequest.model_validate_json(
        request_path.read_text(encoding="utf-8")
    )
    if not relative_request_path.startswith(f"{request.artifact_root}/"):
        raise ValueError("QA diagnostic request must live inside its artifact_root")
    _verify_request_sources(job_root, request)
    return request


def evaluate_semantic_shape_bindings(
    job_root: Path,
    request: QADiagnosticRequest,
    *,
    boundary_tolerance_px: int = 2,
) -> list[SemanticShapeMetrics]:
    """Evaluate all exact semantic mask pairs declared by one diagnostic request."""

    metrics: list[SemanticShapeMetrics] = []
    for binding in request.semantic_masks:
        reference_path = _verify_exact_hash(
            job_root,
            binding.reference_mask_path,
            binding.reference_mask_sha256,
        )
        rendered_path = _verify_exact_hash(
            job_root,
            binding.rendered_mask_path,
            binding.rendered_mask_sha256,
        )
        metrics.append(
            compare_semantic_masks(
                reference_path,
                rendered_path,
                semantic_id=binding.semantic_id,
                role=binding.role,
                boundary_tolerance_px=boundary_tolerance_px,
            )
        )
    return metrics


def _verify_camera_probes(
    job_root: Path,
    request: QADiagnosticRequest,
    probes: Sequence[CameraProbeResult],
) -> CameraProbeResult:
    """Verify bounded probe count, exact evidence hashes, and the named baseline."""

    probe_ids = [probe.probe_id for probe in probes]
    if len(probe_ids) != len(set(probe_ids)):
        raise ValueError("camera probes must use unique probe IDs")
    baselines = [probe for probe in probes if probe.is_baseline]
    if len(baselines) != 1:
        raise ValueError("camera diagnostics require exactly one baseline probe")
    baseline = baselines[0]
    if baseline.probe_id != request.baseline_probe_id:
        raise ValueError("camera diagnostic baseline does not match the request")
    if len(probes) - 1 > request.max_camera_probes:
        raise ValueError("camera diagnostic exceeds the request's bounded probe count")
    for probe in probes:
        if not probe.evidence_path.startswith(f"{request.artifact_root}/"):
            raise ValueError("camera probe evidence must live inside artifact_root")
        _verify_exact_hash(job_root, probe.evidence_path, probe.evidence_sha256)
    return baseline


def _verify_assembly_evidence(
    job_root: Path,
    request: QADiagnosticRequest,
    assembly: AssemblyDiagnosticEvidence,
) -> None:
    """Require optional assembly attribution to match the request's exact source binding."""

    if request.assembly_report_path is None:
        if assembly.status != "not_available":
            raise ValueError("assembly evidence was not declared by the diagnostic request")
        return
    if (
        assembly.report_path != request.assembly_report_path
        or assembly.report_sha256 != request.assembly_report_sha256
    ):
        raise ValueError("assembly evidence does not match the request's exact report binding")
    assert assembly.report_path is not None
    assert assembly.report_sha256 is not None
    _verify_exact_hash(job_root, assembly.report_path, assembly.report_sha256)


def build_qa_diagnostic_report(
    job_root: Path,
    request_path: Path,
    camera_probes: Sequence[CameraProbeResult],
    *,
    assembly_evidence: AssemblyDiagnosticEvidence | None = None,
    thresholds: AttributionThresholds | None = None,
    boundary_tolerance_px: int = 2,
    limitations: Sequence[str] = (),
    generated_at: datetime | None = None,
) -> QADiagnosticReport:
    """Build one advisory, hash-bound companion report without changing canonical QA."""

    request = load_qa_diagnostic_request(job_root, request_path)
    probes = list(camera_probes)
    baseline = _verify_camera_probes(job_root, request, probes)
    assembly = assembly_evidence or AssemblyDiagnosticEvidence()
    _verify_assembly_evidence(job_root, request, assembly)
    semantic_metrics = evaluate_semantic_shape_bindings(
        job_root,
        request,
        boundary_tolerance_px=boundary_tolerance_px,
    )
    attribution = attribute_camera_geometry(
        baseline,
        probes,
        assembly=assembly,
        semantic_metrics=semantic_metrics,
        thresholds=thresholds,
    )
    report_limitations = list(limitations)
    if not semantic_metrics:
        report_limitations.append(
            "no explicit evidence-backed semantic reference masks were supplied"
        )
    report_limitations.extend(
        limitation
        for metric in semantic_metrics
        if metric.status == "unscorable"
        for limitation in metric.limitations
    )
    report_limitations.extend(
        limitation
        for probe in probes
        if probe.status == "unscorable"
        for limitation in probe.limitations
    )
    report_limitations = list(dict.fromkeys(report_limitations))
    if attribution.classification == "unscorable":
        status = "unscorable"
    elif not semantic_metrics or any(
        item.status == "unscorable" for item in semantic_metrics
    ) or any(
        probe.status == "unscorable" for probe in probes
    ):
        status = "degraded"
    else:
        status = "completed"
    return QADiagnosticReport(
        job_id=request.job_id,
        qa_run_id=request.qa_run_id,
        diagnostic_id=request.diagnostic_id,
        request_path=_job_relative_path(job_root, request_path),
        request_sha256=sha256_file(request_path),
        status=status,
        semantic_metrics=semantic_metrics,
        camera_probes=probes,
        assembly_evidence=assembly,
        attribution=attribution,
        limitations=report_limitations,
        generated_at=generated_at or datetime.now(UTC),
    )
