"""Human-readable PDF projection for one bounded visual-convergence session."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate, Spacer

from ..blender_artifacts import write_json_atomic
from ..reporting.pdf_renderer import (
    LINE,
    MUTED,
    _data_table,
    _metric_table,
    _paragraph,
    _register_report_fonts,
    _report_styles,
)
from ..workspace import job_dir, sha256_file, validate_job_id
from .convergence_session_models import (
    HashBoundConvergenceArtifact,
    VisualConvergenceReport,
    VisualConvergenceReportManifest,
)

_SESSION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?i)\b[a-z]:[\\/][^\s,;]+")
_POSIX_ABSOLUTE_RE = re.compile(r"(?<![\w.])/(?:[^/\s]+/)*[^/\s]*")


def _validate_session_id(session_id: str) -> str:
    """Reject traversal and non-portable visual-convergence session identifiers."""

    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(
            "session_id must match [a-z0-9][a-z0-9_-]{0,63}: "
            f"{session_id!r}"
        )
    return session_id


def _normalize_relative_path(value: str, *, label: str) -> str:
    """Normalize one slash-separated relative path and reject absolute or escaping input."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty job-relative path")
    raw = value.strip()
    windows_path = PureWindowsPath(raw)
    posix_path = PurePosixPath(raw.replace("\\", "/"))
    if windows_path.is_absolute() or windows_path.drive or posix_path.is_absolute():
        raise ValueError(f"{label} must not be absolute: {value!r}")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise ValueError(f"{label} must not contain empty, dot, or parent segments: {value!r}")
    return posix_path.as_posix()


def _resolve_job_source(root: Path, relative_path: str, *, label: str) -> Path:
    """Resolve one required source while proving that it remains inside the job root."""

    normalized = _normalize_relative_path(relative_path, label=label)
    resolved_root = root.resolve()
    resolved = (resolved_root / Path(*PurePosixPath(normalized).parts)).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the selected job root") from exc
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _job_relative(root: Path, path: Path) -> str:
    """Return one normalized job-relative path without disclosing the host location."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("Convergence report artifacts must remain inside the job root") from exc


def _source_record(root: Path, kind: str, path: Path) -> dict[str, Any]:
    """Hash one exact report source and retain only its job-relative path."""

    return {
        "kind": kind,
        "path": _job_relative(root, path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _source_fingerprint(sources: list[dict[str, Any]]) -> str:
    """Create a deterministic digest over the ordered convergence evidence list."""

    canonical = json.dumps(
        sources,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_final_report(path: Path) -> VisualConvergenceReport:
    """Load and strictly validate one authoritative terminal convergence report."""

    return VisualConvergenceReport.model_validate_json(path.read_text(encoding="utf-8"))


def _redact_host_paths(value: Any) -> str:
    """Render a compact value while redacting accidental absolute host paths."""

    if value is None:
        return "-"
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple, set)):
        rendered = ", ".join(_redact_host_paths(item) for item in value)
    else:
        rendered = str(value)
    rendered = _WINDOWS_ABSOLUTE_RE.sub("<redacted-absolute-path>", rendered)
    return _POSIX_ABSOLUTE_RE.sub("<redacted-absolute-path>", rendered)


def _first_value(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first present top-level report value from compatible field names."""

    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _score_delta(payload: dict[str, Any]) -> float | None:
    """Read or derive the final direct-score delta from a duck-typed report."""

    recorded = _first_value(payload, "score_delta", "direct_score_delta")
    if isinstance(recorded, (int, float)) and not isinstance(recorded, bool):
        return float(recorded)
    before = _first_value(
        payload,
        "baseline_direct_score",
        "before_direct_score",
        "initial_direct_score",
    )
    after = _first_value(
        payload,
        "final_direct_score",
        "after_direct_score",
        "ending_direct_score",
    )
    if all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in (before, after)
    ):
        return float(after) - float(before)
    return None


def _iteration_rows(
    payload: dict[str, Any],
    receipt_payloads: dict[str, dict[str, Any]],
) -> list[list[Any]]:
    """Project the report's exact iteration receipts into a bounded PDF table."""

    raw_receipts = payload.get("iteration_receipts")
    if not isinstance(raw_receipts, list):
        return []
    rows: list[list[Any]] = []
    for index, artifact in enumerate(raw_receipts[:50], start=1):
        if not isinstance(artifact, dict):
            continue
        relative_path = artifact.get("relative_path")
        if not isinstance(relative_path, str):
            continue
        item = receipt_payloads.get(relative_path, {})
        before = _first_value(
            item,
            "before_direct_score",
            "baseline_direct_score",
            default="-",
        )
        after = _first_value(
            item,
            "after_direct_score",
            "final_direct_score",
            default="-",
        )
        changed = _first_value(
            item,
            "changed_ids",
            "selected_candidate_ids",
            "candidate_ids",
            default=[],
        )
        rows.append(
            [
                _first_value(item, "iteration", "iteration_index", default=index),
                _first_value(item, "status", "outcome", default="unknown"),
                before,
                after,
                _first_value(item, "score_delta", "direct_score_delta", default="-"),
                _redact_host_paths(changed),
            ]
        )
    return rows


def _report_artifact_hashes(
    report: VisualConvergenceReport,
) -> dict[str, str]:
    """Merge receipt and evidence bindings while rejecting conflicting hashes."""

    expected: dict[str, str] = {}
    for artifact in [*report.iteration_receipts, *report.iteration_evidence]:
        existing = expected.get(artifact.relative_path)
        if existing is not None and existing != artifact.sha256:
            raise ValueError(
                "Convergence report binds one evidence path to conflicting hashes: "
                f"{artifact.relative_path}"
            )
        expected[artifact.relative_path] = artifact.sha256
    return expected


def _load_receipt_payloads(
    root: Path,
    report: VisualConvergenceReport,
) -> dict[str, dict[str, Any]]:
    """Load exact hash-bound receipt JSON solely for the human PDF projection."""

    payloads: dict[str, dict[str, Any]] = {}
    for index, artifact in enumerate(report.iteration_receipts):
        path = _resolve_job_source(
            root,
            artifact.relative_path,
            label=f"iteration_receipts[{index}]",
        )
        if sha256_file(path) != artifact.sha256:
            raise ValueError(
                "Convergence iteration receipt changed after terminal reporting: "
                f"{artifact.relative_path}"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Convergence iteration receipt is not valid UTF-8 JSON: "
                f"{artifact.relative_path}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(
                "Convergence iteration receipt must contain a JSON object: "
                f"{artifact.relative_path}"
            )
        payloads[artifact.relative_path] = payload
    return payloads


def _report_reasons(payload: dict[str, Any]) -> list[str]:
    """Collect bounded final reasons and limitations for human review."""

    collected: list[str] = []
    for key in ("reasons", "warnings", "limitations", "remaining_findings"):
        value = payload.get(key)
        if isinstance(value, list):
            collected.extend(_redact_host_paths(item) for item in value)
        elif value not in (None, "", []):
            collected.append(_redact_host_paths(value))
    return collected[:40]


def _page_callback(fonts: dict[str, str], session_id: str):
    """Create stable page furniture for one visual-convergence report."""

    def draw_page(canvas: Canvas, document: SimpleDocTemplate) -> None:
        """Draw a privacy-safe header and footer outside the A4 content frame."""

        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.4)
        canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
        canvas.setFont(fonts["regular"], 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, height - 11 * mm, "BlenderAssetGenerator - V0.6")
        canvas.drawRightString(width - 18 * mm, height - 11 * mm, session_id)
        canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
        canvas.drawString(18 * mm, 9 * mm, "Machine-readable JSON remains authoritative")
        canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    return draw_page


def _render_convergence_pdf(
    output: Path,
    *,
    job_id: str,
    session_id: str,
    report: dict[str, Any],
    receipt_payloads: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    source_fingerprint: str,
) -> dict[str, str]:
    """Render a Korean-capable A4 summary from one final machine convergence report."""

    fonts = _register_report_fonts()
    styles = _report_styles(fonts)
    status = _first_value(
        report,
        "status",
        "termination_reason",
        "outcome",
        default="unknown",
    )
    baseline = _first_value(
        report,
        "baseline_direct_score",
        "before_direct_score",
        "initial_direct_score",
        default="-",
    )
    final = _first_value(
        report,
        "final_direct_score",
        "after_direct_score",
        "ending_direct_score",
        default="-",
    )
    target = _first_value(
        report,
        "target_direct_score",
        "direct_score_target",
        default="-",
    )
    iteration_rows = _iteration_rows(report, receipt_payloads)
    iteration_receipts = report.get("iteration_receipts", [])
    iteration_evidence = report.get("iteration_evidence", [])
    remaining_high_ids = report.get("remaining_high_finding_ids", [])
    if not isinstance(iteration_receipts, list):
        iteration_receipts = []
    if not isinstance(iteration_evidence, list):
        iteration_evidence = []
    if not isinstance(remaining_high_ids, list):
        remaining_high_ids = []
    reasons = _report_reasons(report)
    document = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="BlenderAssetGenerator Visual Convergence Report",
        author="Codex Blender Modeler",
        subject=f"Bounded visual convergence session {session_id}",
    )
    story: list[Any] = [
        _paragraph("V0.6 제한형 시각 수렴 보고서", styles["title"]),
        _paragraph(
            "이 PDF는 검토용 파생 문서입니다. 최종 JSON과 정확한 SHA-256 "
            "증거가 판단 원본입니다.",
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        _data_table(
            ["항목", "값"],
            [
                ["Job ID", job_id],
                ["Session ID", session_id],
                ["종료 상태", _redact_host_paths(status)],
                ["목표 도달", _redact_host_paths(report.get("target_reached"))],
                ["수동 검토 필요", _redact_host_paths(report.get("manual_review_required"))],
                ["Source fingerprint", source_fingerprint],
            ],
            [48 * mm, 126 * mm],
            styles,
        ),
        Spacer(1, 5 * mm),
        _metric_table(
            [
                ("시작 direct score", baseline),
                ("종료 direct score", final),
                ("변화량", _score_delta(report) if _score_delta(report) is not None else "-"),
                ("목표 direct score", target),
            ],
            styles,
        ),
        _paragraph("반복 실행 요약", styles["h1"]),
        _metric_table(
            [
                ("승인된 반복", report.get("accepted_iterations", 0)),
                ("롤백된 반복", report.get("rolled_back_iterations", 0)),
                ("반복 receipt", len(iteration_receipts)),
                ("결속된 증거 파일", len(iteration_evidence)),
            ],
            styles,
        ),
        _paragraph("반복 결과", styles["h1"]),
    ]
    if iteration_rows:
        story.append(
            _data_table(
                ["회차", "상태", "이전", "이후", "변화", "변경 ID/후보"],
                iteration_rows,
                [13 * mm, 29 * mm, 23 * mm, 23 * mm, 20 * mm, 66 * mm],
                styles,
            )
        )
    else:
        story.append(
            _paragraph(
                "실행된 반복 receipt가 없습니다. 초기 QA 상태에서 종료된 세션일 수 있습니다.",
                styles["body"],
            )
        )
    story.append(_paragraph("미해결 High Finding", styles["h1"]))
    if remaining_high_ids:
        story.append(
            _paragraph(
                f"미해결 High Finding {len(remaining_high_ids)}건이 남아 있어 "
                "목표 도달 여부와 별개로 추가 품질 검토를 권장합니다.",
                styles["body"],
            )
        )
        for finding_id in remaining_high_ids[:50]:
            story.append(_paragraph(f"- {_redact_host_paths(finding_id)}", styles["body"]))
    else:
        story.append(_paragraph("기록된 미해결 High Finding ID가 없습니다.", styles["body"]))
    story.append(_paragraph("종료 이유와 남은 제한", styles["h1"]))
    if reasons:
        for reason in reasons:
            story.append(_paragraph(f"- {reason}", styles["body"]))
    else:
        story.append(_paragraph("기록된 추가 제한이 없습니다.", styles["body"]))
    story.append(_paragraph("Authoritative source appendix", styles["h1"]))
    story.append(
        _paragraph(
            "아래 job-relative 파일과 전체 해시가 이 PDF의 정확한 입력 증거입니다.",
            styles["body"],
        )
    )
    story.append(
        _data_table(
            ["Kind", "Job-relative path", "SHA-256", "Bytes"],
            [
                [item["kind"], item["path"], item["sha256"], item["size_bytes"]]
                for item in sources
            ],
            [34 * mm, 72 * mm, 53 * mm, 15 * mm],
            styles,
        )
    )
    callback = _page_callback(fonts, session_id)
    document.build(story, onFirstPage=callback, onLaterPages=callback)
    return {"font": fonts["source"]}


def _verify_sources_current(paths: list[Path], sources: list[dict[str, Any]]) -> None:
    """Fail closed when any source changes while the derived PDF is being rendered."""

    for path, source in zip(paths, sources, strict=True):
        if not path.is_file():
            raise RuntimeError(f"Convergence report source disappeared: {source['path']}")
        if (
            sha256_file(path) != source["sha256"]
            or path.stat().st_size != source["size_bytes"]
        ):
            raise RuntimeError(
                "Convergence report source changed during rendering: "
                f"{source['path']}"
            )


def generate_visual_convergence_pdf_report(
    job_id: str,
    session_id: str,
    *,
    report_relative_path: str | None = None,
    source_relative_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Generate an immutable session PDF and hash sidecar from exact job-local evidence."""

    validate_job_id(job_id)
    session_id = _validate_session_id(session_id)
    root = job_dir(job_id).resolve()
    session_relative = f"qa/convergence/{session_id}"
    expected_report = f"{session_relative}/convergence_report.json"
    normalized_report = _normalize_relative_path(
        report_relative_path or expected_report,
        label="report_relative_path",
    )
    if PurePosixPath(normalized_report).parent.as_posix() != session_relative:
        raise ValueError(
            "The final machine convergence report must remain in the selected "
            f"session directory: {session_relative}"
        )
    report_path = _resolve_job_source(
        root,
        normalized_report,
        label="report_relative_path",
    )
    final_report = _load_final_report(report_path)
    report = final_report.model_dump(mode="json")
    if final_report.job_id != job_id:
        raise ValueError("Machine convergence report belongs to a different job")
    if final_report.session_id != session_id:
        raise ValueError("Machine convergence report belongs to a different session")

    receipt_payloads = _load_receipt_payloads(root, final_report)
    normalized_sources: list[str] = [normalized_report]
    expected_source_hashes = _report_artifact_hashes(final_report)
    normalized_sources.extend(expected_source_hashes)
    for index, value in enumerate(source_relative_paths):
        normalized = _normalize_relative_path(value, label=f"source_relative_paths[{index}]")
        if normalized not in normalized_sources:
            normalized_sources.append(normalized)
    if len(normalized_sources) < 2:
        raise ValueError(
            "Convergence PDF requires the terminal report and at least one exact "
            "job-relative evidence source"
        )
    source_paths = [
        _resolve_job_source(root, value, label=f"source_relative_paths[{index}]")
        for index, value in enumerate(normalized_sources)
    ]
    sources = [
        _source_record(
            root,
            "machine_convergence_report" if index == 0 else "convergence_evidence",
            path,
        )
        for index, path in enumerate(source_paths)
    ]
    for source in sources:
        expected_hash = expected_source_hashes.get(source["path"])
        if expected_hash is not None and source["sha256"] != expected_hash:
            raise ValueError(
                "Convergence iteration receipt changed after terminal reporting: "
                f"{source['path']}"
            )
    artifact_sources = [
        HashBoundConvergenceArtifact(
            relative_path=source["path"],
            sha256=source["sha256"],
        )
        for source in sources
    ]
    fingerprint = _source_fingerprint(
        [
            {
                "relative_path": artifact.relative_path,
                "sha256": artifact.sha256,
            }
            for artifact in artifact_sources
        ]
    )
    session_root = root / Path(*PurePosixPath(session_relative).parts)
    output = session_root / "convergence_report.pdf"
    manifest_path = session_root / "convergence_report.manifest.json"
    if output.exists() or manifest_path.exists():
        raise FileExistsError(
            f"Visual convergence PDF report already exists for session: {session_id}"
        )

    session_root.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    temporary_pdf = session_root / f".convergence_report.{token}.pdf.tmp"
    temporary_manifest = session_root / f".convergence_report.{token}.manifest.json.tmp"
    installed_pdf = False
    try:
        _render_convergence_pdf(
            temporary_pdf,
            job_id=job_id,
            session_id=session_id,
            report=report,
            receipt_payloads=receipt_payloads,
            sources=sources,
            source_fingerprint=fingerprint,
        )
        _verify_sources_current(source_paths, sources)
        manifest = VisualConvergenceReportManifest(
            session_id=session_id,
            job_id=job_id,
            source_fingerprint=fingerprint,
            report_json=artifact_sources[0],
            pdf=HashBoundConvergenceArtifact(
                relative_path=_job_relative(root, output),
                sha256=sha256_file(temporary_pdf),
            ),
            sources=artifact_sources,
            generated_at=datetime.now(UTC).isoformat(),
        )
        write_json_atomic(temporary_manifest, manifest.model_dump(mode="json"))
        _verify_sources_current(source_paths, sources)
        os.replace(temporary_pdf, output)
        installed_pdf = True
        os.replace(temporary_manifest, manifest_path)
    except Exception:
        temporary_pdf.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        if installed_pdf and not manifest_path.exists():
            output.unlink(missing_ok=True)
        raise
    return {
        "ok": True,
        "job_id": job_id,
        "session_id": session_id,
        "pdf": str(output),
        "manifest": str(manifest_path),
        "pdf_sha256": manifest.pdf.sha256,
        "source_fingerprint": fingerprint,
        "source_count": len(sources),
    }


__all__ = ["generate_visual_convergence_pdf_report"]
