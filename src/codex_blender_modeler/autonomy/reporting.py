"""Immutable non-production review bundles for Autonomous Quality sessions."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..integrated_quality.models import IntegratedQualityReport
from ..production.validation import validate_production_id
from ..reporting.pdf_renderer import _register_report_fonts
from .io import ensure_autonomy_path, load_json, write_immutable_json
from .models import (
    AutonomyArtifact,
    ReviewBundleManifest,
    ReviewBundleReceipt,
    TerminalReason,
)

_REPORT_NAME = "review_bundle_report.pdf"
_REPORT_SIDECAR_NAME = "review_bundle_report.manifest.json"
_MANIFEST_NAME = "review_bundle_manifest.json"
_RECEIPT_NAME = "review_bundle_receipt.json"
_PRODUCER = "codex_blender_modeler.autonomy.review_bundle"
_PRODUCER_VERSION = "0.1.0"


def _path_exists(path: Path) -> bool:
    """Check one review path through Windows extended-length path semantics."""

    return os.path.exists(native_io_path(path))


def _path_is_file(path: Path) -> bool:
    """Check one regular review file without the Windows legacy path-length limit."""

    return os.path.isfile(native_io_path(path))


def _path_is_dir(path: Path) -> bool:
    """Check one review directory without the Windows legacy path-length limit."""

    return os.path.isdir(native_io_path(path))


def _mkdir(path: Path, *, exist_ok: bool) -> None:
    """Create one review directory tree through its native extended-length path."""

    os.makedirs(native_io_path(path), exist_ok=exist_ok)


def _read_utf8(path: Path) -> str:
    """Read one review contract through its native extended-length path."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return handle.read()


def _write_utf8(path: Path, value: str) -> None:
    """Write one review document through its native extended-length path."""

    with open(native_io_path(path), "w", encoding="utf-8") as handle:
        handle.write(value)


def _job_relative(root: Path, path: Path) -> str:
    """Return one normalized job-relative path without exposing its host location."""

    safe = ensure_autonomy_path(root, path, must_exist=True)
    return safe.relative_to(root.resolve()).as_posix()


def _source_file(root: Path, path: Path, *, label: str, suffix: str | None = None) -> Path:
    """Resolve one required regular source file and optionally enforce its file suffix."""

    source = ensure_autonomy_path(root, path, must_exist=True)
    if not _path_is_file(source):
        raise ValueError(f"{label} must be one regular file")
    if suffix is not None and source.suffix.casefold() != suffix.casefold():
        raise ValueError(f"{label} must use the {suffix} file extension")
    return source


def _artifact(root: Path, path: Path) -> AutonomyArtifact:
    """Hash one exact job-contained artifact using a portable relative path."""

    source = _source_file(root, path, label="review bundle artifact")
    return AutonomyArtifact(path=_job_relative(root, source), sha256=sha256_file(source))


def _staged_artifact(
    root: Path,
    staging_root: Path,
    final_root: Path,
    staged_path: Path,
) -> AutonomyArtifact:
    """Describe a staged file by its final immutable job-relative destination."""

    safe_staged = _source_file(root, staged_path, label="staged review bundle artifact")
    relative = safe_staged.relative_to(staging_root).as_posix()
    final_path = final_root / Path(*relative.split("/"))
    return AutonomyArtifact(
        path=final_path.relative_to(root.resolve()).as_posix(),
        sha256=sha256_file(safe_staged),
    )


def _copy_exact(root: Path, source: Path, destination: Path) -> None:
    """Copy one source atomically and prove that the resulting bytes are unchanged."""

    safe_source = _source_file(root, source, label="review bundle source")
    safe_destination = ensure_autonomy_path(root, destination, must_exist=False)
    if _path_exists(safe_destination):
        raise FileExistsError(safe_destination)
    _mkdir(safe_destination.parent, exist_ok=True)
    ensure_autonomy_path(root, safe_destination.parent, must_exist=True)
    temporary = safe_destination.with_name(f".{safe_destination.name}.{uuid4().hex}.tmp")
    with open(native_io_path(safe_source), "rb") as source_handle:
        with open(native_io_path(temporary), "xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
    if sha256_file(temporary) != sha256_file(safe_source):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"review bundle copy hash mismatch: {safe_source.name}")
    os.replace(native_io_path(temporary), native_io_path(safe_destination))


def _validate_json_source(root: Path, path: Path, *, label: str) -> Path:
    """Require one exact UTF-8 JSON source without rewriting or normalizing its bytes."""

    source = _source_file(root, path, label=label, suffix=".json")
    try:
        json.loads(_read_utf8(source))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain valid UTF-8 JSON") from exc
    return source


def _validate_quality_report(
    root: Path,
    path: Path,
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
) -> tuple[Path, IntegratedQualityReport]:
    """Validate one current non-passing Integrated Quality report and its provenance."""

    source = _validate_json_source(root, path, label="integrated quality report")
    report = IntegratedQualityReport.model_validate_json(_read_utf8(source))
    if (report.job_id, report.workflow_id, report.dispatch_id) != (
        job_id,
        workflow_id,
        dispatch_id,
    ):
        raise ValueError("integrated quality identity differs from the review bundle")
    if report.quality_accepted or report.outcome == "passed":
        raise ValueError("a passing quality report must not be published as a review bundle")
    for evidence in report.provenance.artifacts:
        evidence_path = ensure_autonomy_path(
            root,
            root / Path(*evidence.relative_path.split("/")),
            must_exist=True,
        )
        if not _path_is_file(evidence_path) or sha256_file(evidence_path) != evidence.sha256:
            raise ValueError(
                "integrated quality provenance is missing or stale: "
                f"{evidence.relative_path}"
            )
    return source, report


def _action_lines(actions: Sequence[str]) -> list[str]:
    """Normalize manual recommendations as inert one-line review data."""

    normalized: list[str] = []
    for action in actions:
        compact = " ".join(str(action).replace("\x00", "").split())
        if compact:
            normalized.append(compact[:1000])
    if not normalized:
        raise ValueError("next_manual_actions must contain at least one non-empty action")
    return normalized


def _write_actions(path: Path, actions: Sequence[str]) -> None:
    """Write manual actions as data-only Korean Markdown with no executable payload."""

    lines = [
        "# 다음 수동 검토 작업",
        "",
        "> 이 파일은 검토 제안 데이터입니다. 명령 또는 자동 실행 권한이 아닙니다.",
        "",
    ]
    lines.extend(f"- {action}" for action in _action_lines(actions))
    _write_utf8(path, "\n".join(lines) + "\n")


def _draw_wrapped(
    canvas: Canvas,
    text: str,
    *,
    x: float,
    y: float,
    font: str,
    size: float,
    max_chars: int,
    leading: float,
) -> float:
    """Draw bounded Korean-capable lines and return the next vertical position."""

    remaining = " ".join(text.split())
    while remaining:
        chunk = remaining[:max_chars]
        if len(remaining) > max_chars and " " in chunk:
            chunk = chunk.rsplit(" ", 1)[0]
        if not chunk:
            chunk = remaining[:max_chars]
        canvas.setFont(font, size)
        canvas.drawString(x, y, chunk)
        remaining = remaining[len(chunk) :].lstrip()
        y -= leading
    return y


def _write_pdf(
    path: Path,
    *,
    bundle_id: str,
    session_id: str,
    report: IntegratedQualityReport,
    termination_reason: TerminalReason,
    actions: Sequence[str],
    source_artifacts: Sequence[AutonomyArtifact],
) -> str:
    """Render a deterministic Korean review summary that clearly rejects production use."""

    fonts = _register_report_fonts()
    canvas = Canvas(native_io_path(path), pagesize=A4, invariant=1)
    canvas.setTitle(f"Autonomous Quality Review Bundle {bundle_id}")
    regular = fonts["regular"]
    bold = fonts["bold"]
    canvas.setFillColorRGB(0.58, 0.05, 0.05)
    canvas.rect(36, 742, 523, 70, fill=1, stroke=0)
    canvas.setFillColorRGB(1, 1, 1)
    canvas.setFont(bold, 18)
    canvas.drawString(50, 785, "품질 미달 검토 번들")
    canvas.setFont(bold, 10)
    canvas.drawString(50, 762, "PRODUCTION PACKAGE 아님 · DESTINATION HANDOFF 사용 금지")
    canvas.setFillColorRGB(0.08, 0.11, 0.17)
    canvas.setFont(bold, 14)
    canvas.drawString(48, 716, "Autonomous Quality 검토 요약")
    canvas.setFont(regular, 8)
    y = 696.0
    for label, value in (
        ("Bundle", bundle_id),
        ("Session", session_id),
        ("Quality outcome", report.outcome),
        ("Termination", termination_reason),
        ("Authority", "integrated_quality_report.json 및 bundle JSON evidence"),
    ):
        canvas.setFont(bold, 8)
        canvas.drawString(48, y, f"{label}:")
        y = _draw_wrapped(
            canvas,
            str(value),
            x=145,
            y=y,
            font=regular,
            size=8,
            max_chars=72,
            leading=11,
        )
    y -= 8
    canvas.setFont(bold, 11)
    canvas.drawString(48, y, "독립 품질 축")
    y -= 17
    for axis in report.axes:
        score = "unscorable" if axis.score is None else f"{axis.score:.6f}"
        y = _draw_wrapped(
            canvas,
            f"- {axis.axis}: {axis.status} / {score}",
            x=58,
            y=y,
            font=regular,
            size=8,
            max_chars=72,
            leading=11,
        )
    y -= 8
    canvas.setFont(bold, 11)
    canvas.drawString(48, y, "권장 수동 작업")
    y -= 17
    for action in _action_lines(actions)[:8]:
        if y < 90:
            canvas.showPage()
            y = 792
        y = _draw_wrapped(
            canvas,
            f"- {action}",
            x=58,
            y=y,
            font=regular,
            size=8,
            max_chars=68,
            leading=11,
        )
    if y < 130:
        canvas.showPage()
        y = 792
    y -= 8
    canvas.setFont(bold, 10)
    canvas.drawString(48, y, "Hash-bound machine evidence")
    y -= 15
    for artifact in source_artifacts:
        if y < 72:
            canvas.showPage()
            y = 792
        y = _draw_wrapped(
            canvas,
            f"{artifact.path}  {artifact.sha256}",
            x=48,
            y=y,
            font=regular,
            size=6.5,
            max_chars=100,
            leading=9,
        )
    canvas.save()
    return fonts["source"]


def _bundle_input_fingerprint(
    artifacts: Sequence[AutonomyArtifact],
    *,
    termination_reason: TerminalReason,
    actions: Sequence[str],
) -> str:
    """Hash exact source artifacts and manual guidance into one bundle input digest."""

    return stable_json_digest(
        {
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "termination_reason": termination_reason,
            "next_manual_actions": list(_action_lines(actions)),
        }
    )


def _write_pdf_sidecar(
    root: Path,
    path: Path,
    *,
    bundle_id: str,
    job_id: str,
    pdf: AutonomyArtifact,
    sources: Sequence[AutonomyArtifact],
    source_fingerprint: str,
    font_source: str,
    created_at: datetime,
) -> None:
    """Bind the derived PDF to every exact JSON source and its deterministic font choice."""

    write_immutable_json(
        root,
        path,
        {
            "schema_version": "0.1.0",
            "bundle_id": bundle_id,
            "job_id": job_id,
            "pdf": pdf.model_dump(mode="json"),
            "source_fingerprint": source_fingerprint,
            "sources": [item.model_dump(mode="json") for item in sources],
            "font": font_source,
            "producer": _PRODUCER,
            "producer_version": _PRODUCER_VERSION,
            "created_at": created_at.isoformat(),
            "authority_notice": "PDF is derived; machine-readable JSON remains authoritative.",
        },
    )


def _copy_bundle_inputs(
    root: Path,
    staging_root: Path,
    *,
    best_candidate_blend: Path,
    preview_glb: Path,
    representative_renders: Sequence[Path],
    integrated_quality_report: Path,
    unresolved_findings: Path,
    iteration_history: Path,
    candidate_comparison: Path,
) -> dict[str, Path | list[Path]]:
    """Copy exact caller-supplied review artifacts into deterministic bundle names."""

    copies: dict[str, Path | list[Path]] = {}
    scalar_sources = (
        ("best_candidate_blend", best_candidate_blend, staging_root / "best_candidate.blend"),
        ("preview_glb", preview_glb, staging_root / "preview.glb"),
        (
            "integrated_quality_report",
            integrated_quality_report,
            staging_root / "integrated_quality_report.json",
        ),
        (
            "unresolved_findings",
            unresolved_findings,
            staging_root / "unresolved_findings.json",
        ),
        ("iteration_history", iteration_history, staging_root / "iteration_history.json"),
        (
            "candidate_comparison",
            candidate_comparison,
            staging_root / "candidate_comparison.json",
        ),
    )
    for key, source, destination in scalar_sources:
        _copy_exact(root, source, destination)
        copies[key] = destination
    render_outputs: list[Path] = []
    for index, source in enumerate(representative_renders, start=1):
        safe_source = _source_file(root, source, label="representative render")
        if safe_source.suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("representative renders must use PNG, JPEG, or WEBP")
        destination = staging_root / "renders" / f"{index:02d}{safe_source.suffix.casefold()}"
        _copy_exact(root, safe_source, destination)
        render_outputs.append(destination)
    copies["representative_renders"] = render_outputs
    return copies


def build_review_bundle(
    job_root: Path,
    *,
    bundle_id: str,
    session_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    termination_reason: TerminalReason,
    best_candidate_blend: Path,
    preview_glb: Path,
    representative_renders: Sequence[Path],
    integrated_quality_report: Path,
    unresolved_findings: Path,
    iteration_history: Path,
    candidate_comparison: Path,
    next_manual_actions: Sequence[str],
    created_at: datetime | None = None,
) -> tuple[ReviewBundleManifest, ReviewBundleReceipt]:
    """Atomically publish one hash-bound review-only bundle from current job evidence."""

    root = job_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    validate_production_id(bundle_id, "review bundle ID")
    validate_production_id(session_id, "autonomy session ID")
    validate_production_id(workflow_id, "workflow ID")
    validate_production_id(dispatch_id, "dispatch ID")
    if not representative_renders:
        raise ValueError("at least one representative render is required")
    actions = _action_lines(next_manual_actions)
    quality_source, quality_report = _validate_quality_report(
        root,
        integrated_quality_report,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
    )
    blend_source = _source_file(root, best_candidate_blend, label="best candidate", suffix=".blend")
    glb_source = _source_file(root, preview_glb, label="review preview", suffix=".glb")
    findings_source = _validate_json_source(
        root,
        unresolved_findings,
        label="unresolved findings",
    )
    history_source = _validate_json_source(root, iteration_history, label="iteration history")
    comparison_source = _validate_json_source(
        root,
        candidate_comparison,
        label="candidate comparison",
    )
    render_sources = [
        _source_file(root, item, label="representative render")
        for item in representative_renders
    ]
    source_paths = [
        blend_source,
        glb_source,
        *render_sources,
        quality_source,
        findings_source,
        history_source,
        comparison_source,
    ]
    source_artifacts = [_artifact(root, item) for item in source_paths]
    input_sha256 = _bundle_input_fingerprint(
        source_artifacts,
        termination_reason=termination_reason,
        actions=actions,
    )
    source_fingerprint = stable_json_digest(
        {
            "integrated_quality_source_fingerprint": (
                quality_report.provenance.source_fingerprint
            ),
            "bundle_input_sha256": input_sha256,
        }
    )
    timestamp = created_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    final_root = ensure_autonomy_path(
        root,
        root / "exports" / "review_bundles" / bundle_id,
        must_exist=False,
    )
    if _path_exists(final_root):
        raise FileExistsError(final_root)
    staging_root = ensure_autonomy_path(
        root,
        final_root.parent / f".{bundle_id}.staging-{uuid4().hex}",
        must_exist=False,
    )
    _mkdir(staging_root, exist_ok=False)
    try:
        copied = _copy_bundle_inputs(
            root,
            staging_root,
            best_candidate_blend=blend_source,
            preview_glb=glb_source,
            representative_renders=render_sources,
            integrated_quality_report=quality_source,
            unresolved_findings=findings_source,
            iteration_history=history_source,
            candidate_comparison=comparison_source,
        )
        actions_path = staging_root / "next_manual_actions.md"
        _write_actions(actions_path, actions)
        copied_artifacts = {
            key: _staged_artifact(root, staging_root, final_root, value)
            for key, value in copied.items()
            if isinstance(value, Path)
        }
        render_artifacts = [
            _staged_artifact(root, staging_root, final_root, item)
            for item in copied["representative_renders"]
            if isinstance(item, Path)
        ]
        actions_artifact = _staged_artifact(root, staging_root, final_root, actions_path)
        report_sources = [
            copied_artifacts["integrated_quality_report"],
            copied_artifacts["unresolved_findings"],
            copied_artifacts["iteration_history"],
            copied_artifacts["candidate_comparison"],
            actions_artifact,
        ]
        pdf_path = staging_root / _REPORT_NAME
        font_source = _write_pdf(
            pdf_path,
            bundle_id=bundle_id,
            session_id=session_id,
            report=quality_report,
            termination_reason=termination_reason,
            actions=actions,
            source_artifacts=report_sources,
        )
        pdf_artifact = _staged_artifact(root, staging_root, final_root, pdf_path)
        sidecar_path = staging_root / _REPORT_SIDECAR_NAME
        _write_pdf_sidecar(
            root,
            sidecar_path,
            bundle_id=bundle_id,
            job_id=job_id,
            pdf=pdf_artifact,
            sources=report_sources,
            source_fingerprint=source_fingerprint,
            font_source=font_source,
            created_at=timestamp,
        )
        sidecar_artifact = _staged_artifact(root, staging_root, final_root, sidecar_path)
        manifest = ReviewBundleManifest(
            contract_id=f"{bundle_id}.manifest",
            job_id=job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            input_sha256=input_sha256,
            source_fingerprint=source_fingerprint,
            producer=_PRODUCER,
            producer_version=_PRODUCER_VERSION,
            provenance=source_artifacts,
            created_at=timestamp,
            bundle_id=bundle_id,
            session_id=session_id,
            best_candidate_blend=copied_artifacts["best_candidate_blend"],
            preview_glb=copied_artifacts["preview_glb"],
            representative_renders=render_artifacts,
            integrated_quality_report=copied_artifacts["integrated_quality_report"],
            unresolved_findings=copied_artifacts["unresolved_findings"],
            iteration_history=copied_artifacts["iteration_history"],
            candidate_comparison=copied_artifacts["candidate_comparison"],
            next_manual_actions=actions_artifact,
            termination_reason=termination_reason,
            pdf=pdf_artifact,
            pdf_sidecar=sidecar_artifact,
        )
        manifest_path = staging_root / _MANIFEST_NAME
        write_immutable_json(root, manifest_path, manifest.model_dump(mode="json"))
        manifest_artifact = _staged_artifact(root, staging_root, final_root, manifest_path)
        receipt_files = sorted(
            [
                *copied_artifacts.values(),
                *render_artifacts,
                actions_artifact,
                pdf_artifact,
                sidecar_artifact,
                manifest_artifact,
            ],
            key=lambda item: item.path,
        )
        receipt = ReviewBundleReceipt(
            contract_id=f"{bundle_id}.receipt",
            job_id=job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            input_sha256=input_sha256,
            source_fingerprint=source_fingerprint,
            producer=_PRODUCER,
            producer_version=_PRODUCER_VERSION,
            provenance=[manifest_artifact],
            created_at=timestamp,
            receipt_id=f"{bundle_id}.receipt",
            bundle_id=bundle_id,
            manifest=manifest_artifact,
            files=receipt_files,
        )
        receipt_path = staging_root / _RECEIPT_NAME
        write_immutable_json(root, receipt_path, receipt.model_dump(mode="json"))
        _mkdir(final_root.parent, exist_ok=True)
        ensure_autonomy_path(root, final_root.parent, must_exist=True)
        os.replace(native_io_path(staging_root), native_io_path(final_root))
    except Exception:
        if _path_exists(staging_root):
            shutil.rmtree(native_io_path(staging_root))
        raise
    return validate_review_bundle(root, bundle_id)


def _verify_artifact(root: Path, artifact: AutonomyArtifact) -> Path:
    """Resolve one recorded artifact and fail closed when its bytes changed."""

    path = ensure_autonomy_path(
        root,
        root / Path(*artifact.path.split("/")),
        must_exist=True,
    )
    if not _path_is_file(path) or sha256_file(path) != artifact.sha256:
        raise ValueError(f"review bundle artifact hash mismatch: {artifact.path}")
    return path


def _validate_pdf_sidecar(
    root: Path,
    manifest: ReviewBundleManifest,
) -> None:
    """Recompute the PDF and machine-source bindings recorded by its derived sidecar."""

    sidecar_path = _verify_artifact(root, manifest.pdf_sidecar)
    sidecar = load_json(root, sidecar_path)
    if sidecar.get("schema_version") != "0.1.0" or sidecar.get("bundle_id") != manifest.bundle_id:
        raise ValueError("review bundle PDF sidecar identity is invalid")
    if sidecar.get("source_fingerprint") != manifest.source_fingerprint:
        raise ValueError("review bundle PDF sidecar source fingerprint changed")
    if sidecar.get("pdf") != manifest.pdf.model_dump(mode="json"):
        raise ValueError("review bundle PDF sidecar no longer binds the manifest PDF")
    expected_sources = [
        manifest.integrated_quality_report,
        manifest.unresolved_findings,
        manifest.iteration_history,
        manifest.candidate_comparison,
        manifest.next_manual_actions,
    ]
    if sidecar.get("sources") != [item.model_dump(mode="json") for item in expected_sources]:
        raise ValueError("review bundle PDF sidecar source list changed")


def validate_review_bundle(
    job_root: Path,
    bundle_id: str,
) -> tuple[ReviewBundleManifest, ReviewBundleReceipt]:
    """Validate one immutable review-only bundle, including exact file-set membership."""

    root = job_root.expanduser().resolve()
    validate_production_id(bundle_id, "review bundle ID")
    bundle_root = ensure_autonomy_path(
        root,
        root / "exports" / "review_bundles" / bundle_id,
        must_exist=True,
    )
    if not _path_is_dir(bundle_root):
        raise ValueError("review bundle root must be a directory")
    manifest_path = ensure_autonomy_path(root, bundle_root / _MANIFEST_NAME, must_exist=True)
    receipt_path = ensure_autonomy_path(root, bundle_root / _RECEIPT_NAME, must_exist=True)
    manifest = ReviewBundleManifest.model_validate_json(
        _read_utf8(manifest_path)
    )
    receipt = ReviewBundleReceipt.model_validate_json(
        _read_utf8(receipt_path)
    )
    if manifest.bundle_id != bundle_id or receipt.bundle_id != bundle_id:
        raise ValueError("review bundle IDs do not match the selected directory")
    if receipt.manifest != _artifact(root, manifest_path):
        raise ValueError("review bundle receipt does not bind the exact manifest")
    if manifest.production_ready or manifest.destination_handoff_eligible:
        raise ValueError("review bundles must remain non-production evidence")
    manifest_outputs = [
        manifest.best_candidate_blend,
        manifest.preview_glb,
        *manifest.representative_renders,
        manifest.integrated_quality_report,
        manifest.unresolved_findings,
        manifest.iteration_history,
        manifest.candidate_comparison,
        manifest.next_manual_actions,
        manifest.pdf,
        manifest.pdf_sidecar,
        receipt.manifest,
    ]
    expected = {item.path: item.sha256 for item in manifest_outputs}
    receipt_set = {item.path: item.sha256 for item in receipt.files}
    if expected != receipt_set:
        raise ValueError("review bundle receipt does not bind the complete manifest file set")
    for artifact in receipt.files:
        resolved = _verify_artifact(root, artifact)
        try:
            resolved.relative_to(bundle_root)
        except ValueError as exc:
            raise ValueError("review bundle receipt references a file outside its bundle") from exc
    quality_path = _verify_artifact(root, manifest.integrated_quality_report)
    quality_report = IntegratedQualityReport.model_validate_json(
        _read_utf8(quality_path)
    )
    if quality_report.quality_accepted or quality_report.outcome == "passed":
        raise ValueError("review bundle cannot claim a quality-passed report")
    _validate_pdf_sidecar(root, manifest)
    actual_files: set[str] = set()
    pending = [bundle_root]
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = list(iterator)
        for entry in entries:
            member = ensure_autonomy_path(root, current / entry.name, must_exist=True)
            if entry.is_dir(follow_symlinks=False):
                pending.append(member)
            elif entry.is_file(follow_symlinks=False):
                actual_files.add(member.relative_to(root).as_posix())
            else:
                raise ValueError("review bundle contains a linked or unsupported entry")
    expected_files = set(receipt_set) | {receipt_path.relative_to(root).as_posix()}
    if actual_files != expected_files:
        raise ValueError("review bundle contains missing or unbound extra files")
    return manifest, receipt
