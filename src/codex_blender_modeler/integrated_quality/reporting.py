"""Deterministic JSON evidence and optional derived PDF for integrated quality."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from ..blender_artifacts import native_io_path, sha256_file, write_json_atomic
from .models import (
    IntegratedQualityReport,
    IntegratedQualityReportManifest,
    QualityArtifact,
    QualityProvenance,
    quality_artifact_input_sha256,
)


def _contained(root: Path, path: Path) -> Path:
    """Resolve one output path and reject any attempt to escape the selected evidence root."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.expanduser().resolve())
    except ValueError as exc:
        raise ValueError(f"integrated quality output escaped its evidence root: {path}") from exc
    return resolved


def _relative(root: Path, path: Path) -> str:
    """Serialize one exact output path relative to the selected evidence root."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def _write_pdf(path: Path, report: IntegratedQualityReport) -> None:
    """Render a deterministic summary PDF while keeping JSON as the authority."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    canvas = Canvas(native_io_path(temporary), pagesize=A4, invariant=1)
    canvas.setTitle(f"Integrated Quality {report.report_id}")
    canvas.setFont("Helvetica-Bold", 16)
    canvas.drawString(48, 795, "Integrated Quality Report")
    canvas.setFont("Helvetica", 9)
    canvas.drawString(48, 777, f"Report: {report.report_id}")
    canvas.drawString(48, 763, f"Job: {report.job_id}")
    canvas.drawString(48, 749, f"Outcome: {report.outcome}")
    canvas.drawString(48, 735, "Authoritative evidence: integrated_quality_report.json")
    y = 705
    for axis in report.axes:
        canvas.setFont("Helvetica-Bold", 10)
        score = "unscorable" if axis.score is None else f"{axis.score:.6f}"
        canvas.drawString(48, y, f"{axis.axis}: {axis.status} ({score})")
        y -= 14
        canvas.setFont("Helvetica", 8)
        for metric in axis.metrics[:8]:
            value = "n/a" if metric.value is None else f"{metric.value:.6f}"
            canvas.drawString(60, y, f"- {metric.metric_id}: {metric.status}; {value}")
            y -= 11
            if y < 72:
                canvas.showPage()
                y = 795
        y -= 6
    if report.blocking_reasons:
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(48, y, "Blocking reasons")
        y -= 14
        canvas.setFont("Helvetica", 8)
        for reason in report.blocking_reasons:
            canvas.drawString(60, y, f"- {reason[:100]}")
            y -= 11
    canvas.save()
    os.replace(native_io_path(temporary), native_io_path(path))


def _write_staged_evidence(
    safe_root: Path,
    staging_dir: Path,
    final_dir: Path,
    report: IntegratedQualityReport,
    *,
    include_pdf: bool,
) -> IntegratedQualityReportManifest:
    """Create a complete evidence set in staging while binding final relative paths."""

    json_path = staging_dir / "integrated_quality_report.json"
    pdf_path = staging_dir / "integrated_quality_report.pdf"
    manifest_path = staging_dir / "integrated_quality_report.manifest.json"
    write_json_atomic(json_path, report.model_dump(mode="json"))
    if include_pdf:
        _write_pdf(pdf_path, report)
    json_relative = _relative(
        safe_root, final_dir / "integrated_quality_report.json"
    )
    pdf_relative = (
        _relative(safe_root, final_dir / "integrated_quality_report.pdf")
        if include_pdf
        else None
    )
    artifacts = [
        QualityArtifact(
            artifact_id="integrated-quality-report-json",
            kind="integrated-quality-report",
            relative_path=json_relative,
            sha256=sha256_file(json_path),
            producer=report.producer,
            produced_at=report.created_at,
        )
    ]
    if include_pdf and pdf_relative is not None:
        artifacts.append(
            QualityArtifact(
                artifact_id="integrated-quality-report-pdf",
                kind="integrated-quality-report-pdf",
                relative_path=pdf_relative,
                sha256=sha256_file(pdf_path),
                producer=report.producer,
                produced_at=report.created_at,
            )
        )
    provenance = QualityProvenance(
        job_id=report.job_id,
        workflow_id=report.workflow_id,
        dispatch_id=report.dispatch_id,
        source_fingerprint=report.source_fingerprint,
        input_sha256=quality_artifact_input_sha256(artifacts),
        artifacts=artifacts,
    )
    manifest = IntegratedQualityReportManifest(
        schema_version="0.1.0",
        report_id=report.report_id,
        job_id=report.job_id,
        workflow_id=report.workflow_id,
        dispatch_id=report.dispatch_id,
        input_sha256=provenance.input_sha256,
        source_fingerprint=report.source_fingerprint,
        json_path=json_relative,
        json_sha256=artifacts[0].sha256,
        pdf_path=pdf_relative,
        pdf_sha256=sha256_file(pdf_path) if include_pdf else None,
        provenance=provenance,
        producer=report.producer,
        created_at=report.created_at,
    )
    write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    return manifest


def _publish_overwrite(staging_dir: Path, output_dir: Path, *, include_pdf: bool) -> None:
    """Publish staged files to an existing directory with the manifest committed last."""

    os.makedirs(native_io_path(output_dir), exist_ok=True)
    names = ["integrated_quality_report.json"]
    if include_pdf:
        names.append("integrated_quality_report.pdf")
    names.append("integrated_quality_report.manifest.json")
    for name in names:
        os.replace(
            native_io_path(staging_dir / name),
            native_io_path(output_dir / name),
        )


def write_integrated_quality_evidence(
    root: Path,
    report: IntegratedQualityReport,
    *,
    output_dir: Path,
    include_pdf: bool = True,
    overwrite: bool = False,
) -> IntegratedQualityReportManifest:
    """Stage a complete evidence set and publish it without exposing a partial new run."""

    safe_root = root.expanduser().resolve()
    safe_output = _contained(safe_root, output_dir)
    if safe_output == safe_root:
        raise ValueError("integrated quality output must be a child directory")
    if os.path.exists(native_io_path(safe_output)) and not overwrite:
        raise FileExistsError("integrated quality evidence is immutable and already exists")
    os.makedirs(native_io_path(safe_output.parent), exist_ok=True)
    staging_dir = _contained(
        safe_root,
        safe_output.parent
        / f".{safe_output.name}.publishing-{uuid4().hex}",
    )
    os.mkdir(native_io_path(staging_dir))
    try:
        manifest = _write_staged_evidence(
            safe_root,
            staging_dir,
            safe_output,
            report,
            include_pdf=include_pdf,
        )
        if os.path.exists(native_io_path(safe_output)):
            if not overwrite:
                raise FileExistsError(
                    "integrated quality evidence is immutable and already exists"
                )
            _publish_overwrite(staging_dir, safe_output, include_pdf=include_pdf)
        else:
            os.replace(native_io_path(staging_dir), native_io_path(safe_output))
        return manifest
    finally:
        if os.path.exists(native_io_path(staging_dir)):
            shutil.rmtree(native_io_path(staging_dir), ignore_errors=True)
