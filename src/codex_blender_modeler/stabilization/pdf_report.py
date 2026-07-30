"""Human-readable V0.9 PDF projection from strict environment and audit JSON evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle

from ..blender_artifacts import sha256_file, write_json_atomic
from ..config import get_settings
from ..reporting.pdf_renderer import (
    AMBER,
    GREEN,
    LINE,
    MUTED,
    PALE_AMBER,
    PALE_GREEN,
    PALE_RED,
    RED,
    _data_table,
    _metric_table,
    _paragraph,
    _register_report_fonts,
    _report_styles,
)
from .models import (
    EnvironmentProbeReport,
    StabilityReportManifest,
    StabilityReportSource,
    WorkspaceAuditReport,
)

_PORTABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _validate_id(value: str, label: str) -> str:
    """Reject traversal, mixed-case, and non-portable report identifiers."""

    if not _PORTABLE_ID_RE.fullmatch(value):
        raise ValueError(
            f"{label} must match [a-z0-9][a-z0-9_-]{{0,63}}: {value!r}"
        )
    return value


def _repo_relative(path: Path) -> str:
    """Convert one contained report artifact to a normalized repository-relative path."""

    settings = get_settings()
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(settings.repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Stability PDF artifacts must remain inside the repository") from exc


def _load_environment_probe(probe_id: str) -> tuple[Path, EnvironmentProbeReport]:
    """Load one immutable environment probe by safe identifier."""

    probe_id = _validate_id(probe_id, "probe_id")
    path = (
        get_settings().repo_root
        / "reports"
        / "v09"
        / "environment"
        / probe_id
        / "environment_probe.json"
    )
    return path, EnvironmentProbeReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _load_workspace_audit(audit_id: str) -> tuple[Path, WorkspaceAuditReport]:
    """Load one immutable workspace audit by safe identifier."""

    audit_id = _validate_id(audit_id, "audit_id")
    path = (
        get_settings().repo_root
        / "reports"
        / "v09"
        / "audits"
        / audit_id
        / "workspace_audit.json"
    )
    return path, WorkspaceAuditReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def _source_record(kind: str, path: Path) -> StabilityReportSource:
    """Hash one authoritative JSON source without exposing its absolute path."""

    return StabilityReportSource(
        kind=kind,  # type: ignore[arg-type]
        path=_repo_relative(path),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
    )


def _source_fingerprint(sources: list[StabilityReportSource]) -> str:
    """Create a stable digest over the ordered V0.9 report evidence list."""

    encoded = json.dumps(
        [source.model_dump(mode="json") for source in sources],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _status_label(value: str | bool | None) -> tuple[str, colors.Color, colors.Color]:
    """Map V0.9 status values to concise Korean labels and accessible colors."""

    normalized = str(value).casefold()
    if value is True or normalized in {"passed", "valid", "true"}:
        return "통과", GREEN, PALE_GREEN
    if value is False or normalized in {"failed", "invalid", "false"}:
        return "실패", RED, PALE_RED
    return "주의", AMBER, PALE_AMBER


def _status_card(label: str, value: str | bool | None, styles: dict[str, Any]) -> Table:
    """Render one compact colored summary card for the stability cover."""

    status, foreground, background = _status_label(value)
    card = Table(
        [
            [_paragraph(label, styles["metric_label"])],
            [_paragraph(status, styles["metric_label"])],
        ],
        colWidths=[40 * mm],
    )
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("TEXTCOLOR", (0, 1), (-1, 1), foreground),
                ("BOX", (0, 0), (-1, -1), 0.6, foreground),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return card


def _page_callback(fonts: dict[str, str], report_id: str):
    """Create stable page furniture for the V0.9 human report."""

    def draw_page(canvas: Canvas, document: SimpleDocTemplate) -> None:
        """Draw a header and footer outside the A4 content frame."""

        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
        canvas.setFont(fonts["regular"], 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, height - 11 * mm, "BlenderAssetGenerator - V0.9")
        canvas.drawRightString(width - 18 * mm, height - 11 * mm, report_id)
        canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
        canvas.drawString(18 * mm, 9 * mm, "Machine JSON remains authoritative")
        canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    return draw_page


def _append_cover(
    story: list[Any],
    report_id: str,
    probe: EnvironmentProbeReport,
    audit: WorkspaceAuditReport,
    fingerprint: str,
    styles: dict[str, Any],
) -> None:
    """Append the stability title, provenance, status cards, and summary metrics."""

    findings = [
        *audit.findings,
        *[finding for job in audit.jobs for finding in job.findings],
    ]
    story.append(_paragraph("V0.9 안정화 검증 보고서", styles["title"]))
    story.append(
        _paragraph(
            f"Report ID: {report_id}\n"
            f"Project: {probe.project_version}\n"
            f"Source fingerprint: {fingerprint[:20]}...\n"
            "이 PDF는 환경 및 workspace 감사 JSON의 읽기 전용 표현입니다.",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 6 * mm))
    cards = Table(
        [[
            _status_card("Blender evidence", probe.blender_compatibility_ok, styles),
            _status_card("Workspace audit", audit.status, styles),
            _status_card(
                "Path privacy",
                not any(item.code == "SOURCE_PATH_ESCAPE" for item in findings),
                styles,
            ),
            _status_card("Release claim", "warning", styles),
        ]],
        colWidths=[43.5 * mm] * 4,
    )
    cards.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(cards)
    story.append(Spacer(1, 7 * mm))
    story.append(
        _metric_table(
            [
                ("Audited jobs", audit.scanned_job_count),
                ("Passed", audit.passed_job_count),
                ("Failed", audit.failed_job_count),
                (
                    "Valid handoffs",
                    f"{audit.valid_handoff_count}/{audit.handoff_count}",
                ),
                (
                    "Valid convergence",
                    (
                        f"{audit.valid_visual_convergence_session_count}/"
                        f"{audit.visual_convergence_session_count}"
                    ),
                ),
            ],
            styles,
        )
    )


def _append_environment(
    story: list[Any],
    probe: EnvironmentProbeReport,
    styles: dict[str, Any],
) -> None:
    """Append detected host facts and preserved contract boundaries."""

    story.append(_paragraph("1. 감지된 실행 환경", styles["h1"]))
    rows = [
        ["Operating system", probe.platform_system, probe.platform_release],
        ["Architecture", probe.architecture, "detected only"],
        ["Python", probe.python_version, "current gate runtime"],
        ["Blender", probe.blender_version or "unavailable", probe.blender_report_status],
        ["Blender executable", probe.blender_executable_name, "basename only"],
        ["Workspace", probe.workspace_mode, "absolute path redacted"],
    ]
    story.append(
        _data_table(
            ["항목", "값", "해석"],
            rows,
            [43 * mm, 67 * mm, 64 * mm],
            styles,
        )
    )
    story.append(_paragraph("계약 버전", styles["h2"]))
    story.append(
        _data_table(
            ["Contract", "Version"],
            [[item.contract, item.version] for item in probe.contracts],
            [110 * mm, 64 * mm],
            styles,
        )
    )
    if probe.warnings or probe.limitations:
        story.append(_paragraph("검증 제한", styles["h2"]))
        for line in [*probe.warnings, *probe.limitations]:
            story.append(_paragraph(f"- {line}", styles["body"]))


def _append_audit(
    story: list[Any],
    audit: WorkspaceAuditReport,
    styles: dict[str, Any],
) -> None:
    """Append per-job audit status and every actionable integrity finding."""

    story.append(_paragraph("2. Workspace 무결성 감사", styles["h1"]))
    story.append(
        _paragraph(
            f"감사 범위: {audit.job_filter or 'all jobs'} / "
            f"스캔 파일: {audit.scanned_file_count} / 제한: {audit.scan_limit}. "
            "감사는 canonical 데이터를 수정하거나 migration하지 않았습니다.",
            styles["body"],
        )
    )
    story.append(
        _data_table(
            [
                "Job",
                "Status",
                "Migration",
                "Sources",
                "Workflows",
                "Handoffs",
                "Convergence",
            ],
            [
                [
                    job.job_id,
                    job.status,
                    job.migration_status,
                    f"{job.verified_source_count}/{job.source_count}",
                    job.workflow_count,
                    f"{job.handoff_status} {job.valid_handoff_count}/{job.handoff_count}",
                    (
                        f"{job.visual_convergence_status} "
                        f"{job.valid_visual_convergence_session_count}/"
                        f"{job.visual_convergence_session_count}"
                    ),
                ]
                for job in audit.jobs
            ],
            [30 * mm, 19 * mm, 31 * mm, 20 * mm, 18 * mm, 28 * mm, 28 * mm],
            styles,
        )
    )
    findings = [*audit.findings, *[item for job in audit.jobs for item in job.findings]]
    story.append(_paragraph("감사 findings", styles["h2"]))
    if not findings:
        story.append(_paragraph("오류나 경고가 없습니다.", styles["body"]))
        return
    story.append(
        _data_table(
            ["Severity", "Code", "Job / Path", "설명"],
            [
                [
                    item.severity,
                    item.code,
                    " / ".join(value for value in [item.job_id, item.path] if value) or "-",
                    item.message,
                ]
                for item in findings
            ],
            [24 * mm, 43 * mm, 48 * mm, 59 * mm],
            styles,
        )
    )


def _append_source_appendix(
    story: list[Any],
    sources: list[StabilityReportSource],
    styles: dict[str, Any],
) -> None:
    """Append privacy-safe relative paths and full source hashes."""

    story.append(_paragraph("부록. Authoritative JSON sources", styles["h1"]))
    story.append(
        _paragraph(
            "판정과 복구는 PDF가 아니라 아래 JSON 및 전체 SHA-256을 사용합니다.",
            styles["body"],
        )
    )
    story.append(
        _data_table(
            ["Kind", "Repository-relative path", "SHA-256", "Bytes"],
            [
                [source.kind, source.path, source.sha256, source.size_bytes]
                for source in sources
            ],
            [34 * mm, 72 * mm, 53 * mm, 15 * mm],
            styles,
        )
    )


def _render_stability_pdf(
    output: Path,
    report_id: str,
    probe: EnvironmentProbeReport,
    audit: WorkspaceAuditReport,
    sources: list[StabilityReportSource],
    fingerprint: str,
) -> dict[str, str]:
    """Render one polished A4 V0.9 stability PDF from strict source models."""

    fonts = _register_report_fonts()
    styles = _report_styles(fonts)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="BlenderAssetGenerator V0.9 Stability Report",
        author="Codex Blender Modeler",
        subject=f"V0.9 environment and workspace audit {report_id}",
    )
    story: list[Any] = []
    _append_cover(story, report_id, probe, audit, fingerprint, styles)
    _append_environment(story, probe, styles)
    _append_audit(story, audit, styles)
    _append_source_appendix(story, sources, styles)
    callback = _page_callback(fonts, report_id)
    document.build(story, onFirstPage=callback, onLaterPages=callback)
    return {"font": fonts["source"]}


def generate_stability_pdf_report(
    probe_id: str,
    audit_id: str,
    *,
    report_id: str,
) -> dict[str, str]:
    """Generate one immutable PDF and sidecar bound to exact V0.9 JSON evidence."""

    report_id = _validate_id(report_id, "report_id")
    probe_path, probe = _load_environment_probe(probe_id)
    audit_path, audit = _load_workspace_audit(audit_id)
    sources = [
        _source_record("environment_probe", probe_path),
        _source_record("workspace_audit", audit_path),
    ]
    fingerprint = _source_fingerprint(sources)
    root = get_settings().repo_root / "output" / "pdf" / "v09" / report_id
    output = root / "stability_report.pdf"
    manifest_path = root / "stability_report.manifest.json"
    if output.exists() or manifest_path.exists():
        raise FileExistsError(f"Stability report already exists: {report_id}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / ".stability_report.pdf.tmp"
    metadata = _render_stability_pdf(
        temporary,
        report_id,
        probe,
        audit,
        sources,
        fingerprint,
    )
    os.replace(temporary, output)
    warnings = [*probe.warnings]
    if audit.status != "passed":
        warnings.append(f"Workspace audit status is {audit.status}.")
    manifest = StabilityReportManifest(
        report_id=report_id,
        generated_at=datetime.now(UTC),
        pdf_path=_repo_relative(output),
        pdf_sha256=sha256_file(output),
        source_fingerprint=fingerprint,
        font=metadata["font"],
        sources=sources,
        warnings=warnings,
    )
    write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    return {
        "pdf": str(output),
        "manifest": str(manifest_path),
        "pdf_sha256": manifest.pdf_sha256,
        "source_fingerprint": manifest.source_fingerprint,
    }
