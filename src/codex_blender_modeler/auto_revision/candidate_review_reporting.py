"""Human-readable before/after PDF rendering for isolated candidate review."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..blender_artifacts import stable_json_digest, write_json_atomic
from ..qa.models import RenderPassManifest
from ..reporting.pdf_renderer import _register_report_fonts
from ..workspace import job_dir, sha256_file
from .candidate_review_models import (
    CandidateReviewArtifact,
    CandidateReviewReportManifest,
)
from .candidate_review_service import validate_candidate_review_decision


def _job_relative(root: Path, path: Path) -> str:
    """Serialize one candidate-report artifact relative to its owning job."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("candidate-review report artifact escaped the owning job") from exc


def _artifact(root: Path, path: Path) -> CandidateReviewArtifact:
    """Create one exact path/hash binding for a report source or output."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return CandidateReviewArtifact(path=_job_relative(root, path), sha256=sha256_file(path))


def _resolve(root: Path, relative: str) -> Path:
    """Resolve one previously validated job-relative candidate artifact path."""

    path = (root / Path(*relative.split("/"))).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("candidate-review report source escaped the owning job") from exc
    return path


def _beauty_path(root: Path, manifest_artifact: CandidateReviewArtifact) -> Path:
    """Resolve the exact beauty pass from one hash-bound seven-pass manifest."""

    manifest_path = _resolve(root, manifest_artifact.path)
    manifest = RenderPassManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    record = next(item for item in manifest.passes if item.kind == "beauty")
    path = Path(record.path)
    resolved = path.resolve() if path.is_absolute() else (manifest_path.parent / path).resolve()
    if not resolved.is_file() or sha256_file(resolved) != record.sha256:
        raise ValueError("candidate-review beauty pass is missing or changed")
    return resolved


def _scaled_image(path: Path, max_width: float, max_height: float) -> Image:
    """Create one aspect-preserving report image bounded to the comparison panel."""

    image = Image(str(path))
    scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return image


def validate_candidate_review_pdf_manifest(
    root: Path,
    manifest_path: Path,
) -> CandidateReviewReportManifest:
    """Revalidate a candidate PDF, every recorded source, and its source fingerprint."""

    manifest = CandidateReviewReportManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.job_id != root.name:
        raise ValueError("candidate-review PDF manifest belongs to another job")
    for artifact in [*manifest.sources, manifest.pdf]:
        path = _resolve(root, artifact.path)
        if not path.is_file() or sha256_file(path) != artifact.sha256:
            raise ValueError(
                f"candidate-review PDF artifact is missing or changed: {artifact.path}"
            )
    expected_fingerprint = stable_json_digest(
        [item.model_dump(mode="json") for item in manifest.sources]
    )
    if manifest.source_fingerprint != expected_fingerprint:
        raise ValueError("candidate-review PDF source fingerprint changed")
    return manifest


def generate_candidate_review_pdf(job_id: str, trial_id: str) -> dict[str, str]:
    """Render one immutable before/after PDF and hash-bound sidecar manifest."""

    root = job_dir(job_id).resolve()
    trial_root = root / "qa" / "candidate_reviews" / trial_id
    decision_path = trial_root / "decision_manifest.json"
    decision = validate_candidate_review_decision(
        root,
        decision_path,
        require_current_sources=True,
    )
    output_path = trial_root / "candidate_review_report.pdf"
    manifest_path = trial_root / "candidate_review_report.manifest.json"
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("candidate-review PDF evidence already exists")
    baseline_beauty = _beauty_path(root, decision.baseline_qa_manifest)
    candidate_beauty = _beauty_path(root, decision.candidate_qa_manifest)
    fonts = _register_report_fonts()
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "CandidateReviewTitle",
        parent=base["Title"],
        fontName=fonts["bold"],
        fontSize=20,
        leading=25,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#14213D"),
    )
    body = ParagraphStyle(
        "CandidateReviewBody",
        parent=base["BodyText"],
        fontName=fonts["regular"],
        fontSize=9,
        leading=13,
        wordWrap="CJK",
    )
    heading = ParagraphStyle(
        "CandidateReviewHeading",
        parent=body,
        fontName=fonts["bold"],
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2F6FED"),
    )
    story = [
        Paragraph("Candidate Review — Before / After", title),
        Paragraph(
            "이 PDF는 exact JSON decision의 파생 검토 자료이며 승인 원본이 아닙니다. "
            "Canonical SceneSpec은 아래 decision SHA-256을 사용자가 승인하기 전까지 "
            "변경되지 않습니다.",
            body,
        ),
        Spacer(1, 5 * mm),
    ]
    summary = [
        ["Job / Trial", f"{escape(decision.job_id)} / {escape(decision.trial_id)}"],
        ["Decision", f"{decision.status} (promotable={decision.promotable})"],
        [
            "Direct score",
            f"{decision.scores.baseline_direct_score:.6f} → "
            f"{decision.scores.candidate_direct_score:.6f} "
            f"({decision.scores.direct_score_delta:+.6f})",
        ],
        [
            "Silhouette IoU",
            f"{decision.scores.baseline_silhouette_iou:.6f} → "
            f"{decision.scores.candidate_silhouette_iou:.6f} "
            f"({decision.scores.silhouette_delta:+.6f})",
        ],
        ["Changed IDs", escape(", ".join(decision.changed_ids)) or "none"],
        ["Decision SHA-256", sha256_file(decision_path)],
    ]
    table = Table(summary, colWidths=[38 * mm, 143 * mm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), fonts["bold"]),
                ("FONTNAME", (1, 0), (1, -1), fonts["regular"]),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D0D5DD")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF1FF")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.extend([table, Spacer(1, 6 * mm), Paragraph("고정 카메라 비교", heading)])
    images = Table(
        [
            [Paragraph("Before", body), Paragraph("Candidate", body)],
            [
                _scaled_image(baseline_beauty, 87 * mm, 70 * mm),
                _scaled_image(candidate_beauty, 87 * mm, 70 * mm),
            ],
        ],
        colWidths=[90 * mm, 90 * mm],
    )
    images.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D0D5DD")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
            ]
        )
    )
    story.extend([images, Spacer(1, 6 * mm)])
    for label, values in (
        ("Changed paths", [" / ".join(map(str, path)) for path in decision.changed_paths]),
        ("Blockers", decision.blockers),
        ("Limitations", decision.limitations),
    ):
        story.append(Paragraph(label, heading))
        story.append(
            Paragraph("<br/>".join(escape(value) for value in values) if values else "none", body)
        )
        story.append(Spacer(1, 3 * mm))
    temporary = output_path.parent / f".{output_path.name}.{uuid4().hex}.tmp"
    try:
        document = SimpleDocTemplate(
            str(temporary),
            pagesize=A4,
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
            title="Candidate Review",
            author="Codex Blender Modeler",
        )
        document.build(story)
        os.replace(temporary, output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    sources = [
        _artifact(root, decision_path),
        _artifact(root, _resolve(root, decision.baseline_qa_report.path)),
        _artifact(root, _resolve(root, decision.candidate_qa_report.path)),
        _artifact(root, _resolve(root, decision.baseline_qa_manifest.path)),
        _artifact(root, _resolve(root, decision.candidate_qa_manifest.path)),
        _artifact(root, baseline_beauty),
        _artifact(root, candidate_beauty),
    ]
    source_fingerprint = stable_json_digest([item.model_dump(mode="json") for item in sources])
    manifest = CandidateReviewReportManifest(
        job_id=job_id,
        trial_id=trial_id,
        decision=sources[0],
        pdf=_artifact(root, output_path),
        sources=sources,
        source_fingerprint=source_fingerprint,
        font=fonts["source"],
        generated_at=datetime.now(UTC),
        warnings=["PDF is derived review evidence; decision_manifest.json remains authoritative."],
    )
    write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    return {
        "pdf": str(output_path),
        "manifest": str(manifest_path),
        "decision_sha256": sha256_file(decision_path),
        "pdf_sha256": sha256_file(output_path),
    }
