from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..analysis import validate_job_surface_details
from ..auto_revision.candidate_builder import build_revision_candidates
from ..blender_artifacts import write_json_atomic
from ..build_provenance import collect_build_provenance
from ..config import load_feature_config
from ..models import SceneSpec
from ..workspace import find_reference, job_dir, load_job, sha256_file
from .advisory_compare import compare_preview_to_generated_target
from .camera_fingerprint import camera_fingerprint
from .direct_compare import compare_reference_to_render, observed_regions_from_scene_spec
from .models import (
    REQUIRED_QA_PASS_KINDS,
    QAFinding,
    QATargetManifest,
    RenderPassManifest,
    RenderPassRecord,
    SurfaceDetailQASummary,
    VisualQARequest,
)
from .reference_mask import prepare_run_reference_mask
from .reporting import merge_advisory_target_result
from .request import create_visual_qa_request, validate_visual_qa_request
from .suggestion_enrichment import enrich_direct_qa_suggestions
from .target_provider import QATargetProvider, generate_optional_qa_target

_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")


def _render_job_qa_passes(
    job_id: str,
    *,
    render_engine: str,
    render_device: str,
    run_id: str,
    camera_fingerprint: str,
    scene_spec_sha256: str,
) -> RenderPassManifest:
    """Load the Blender artifact runner lazily to avoid package initialization cycles."""

    from ..blender_artifact_runner import render_job_qa_passes

    return render_job_qa_passes(
        job_id,
        render_engine=render_engine,
        render_device=render_device,
        run_id=run_id,
        camera_fingerprint=camera_fingerprint,
        scene_spec_sha256=scene_spec_sha256,
    )


def _new_run_id(scene_spec_sha256: str) -> str:
    """Generate a collision-resistant, sortable QA run ID tied to the SceneSpec revision."""

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-{scene_spec_sha256[:12]}"


def _validate_run_id(value: str) -> str:
    """Reject traversal and non-portable QA run IDs before creating directories."""

    if not _RUN_ID_RE.fullmatch(value):
        raise ValueError("QA run_id must match [a-zA-Z0-9][a-zA-Z0-9._-]{0,95}")
    return value


def _reference_content_mask(root: Path) -> Path:
    """Resolve the deterministic V0.4 primary-reference content mask."""

    preferred = root / "analysis" / "masks" / "reference_content.png"
    if preferred.is_file():
        return preferred
    candidates = sorted((root / "analysis" / "masks").glob("*reference*_content.png"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(
            f"Reference content mask is missing; run analyze_reference first: {preferred}"
        )
    raise ValueError(f"Multiple primary-reference mask candidates were found: {candidates}")


def _resolve_manifest_artifact(manifest_path: Path, record: RenderPassRecord) -> Path:
    """Resolve an absolute or manifest-relative Blender artifact path."""

    path = Path(record.path).expanduser()
    return path.resolve() if path.is_absolute() else (manifest_path.parent / path).resolve()


def _snapshot_render_passes(
    manifest: RenderPassManifest,
    *,
    source_manifest_path: Path,
    run_dir: Path,
) -> tuple[RenderPassManifest, Path, dict[str, Path]]:
    """Copy shared Blender pass outputs into one immutable QA run and rewrite its manifest."""

    kinds = {record.kind for record in manifest.passes}
    missing = sorted(set(REQUIRED_QA_PASS_KINDS) - kinds)
    if missing:
        raise ValueError(f"QA render manifest is missing required seven-pass outputs: {missing}")
    pass_dir = run_dir / "passes"
    pass_dir.mkdir(parents=True, exist_ok=False)
    copied: dict[str, Path] = {}
    records: list[RenderPassRecord] = []
    for record in manifest.passes:
        source = _resolve_manifest_artifact(source_manifest_path, record)
        if not source.is_file():
            raise FileNotFoundError(f"Blender QA pass is missing: {source}")
        if sha256_file(source) != record.sha256:
            raise ValueError(f"Blender QA pass hash does not match manifest: {record.kind}")
        suffix = source.suffix.lower() or ".png"
        destination = pass_dir / f"{record.kind}{suffix}"
        shutil.copy2(source, destination)
        copied[record.kind] = destination
        records.append(record.model_copy(update={"path": f"passes/{destination.name}"}))
    run_manifest = manifest.model_copy(update={"passes": records})
    manifest_path = run_dir / "render_pass_manifest.json"
    write_json_atomic(manifest_path, run_manifest.model_dump(mode="json"))
    return run_manifest, manifest_path, copied


def _resume_interrupted_render_snapshot(
    root: Path,
    run_dir: Path,
    *,
    job_id: str,
    run_id: str,
    scene_spec_sha256: str,
    camera_fingerprint: str,
) -> tuple[RenderPassManifest, Path, dict[str, Path]]:
    """Resume QA only from an exact, hash-valid seven-pass snapshot with no later outputs."""

    allowed_entries = {"passes", "render_pass_manifest.json"}
    actual_entries = {path.name for path in run_dir.iterdir()}
    if actual_entries != allowed_entries:
        raise FileExistsError(run_dir)
    manifest_path = run_dir / "render_pass_manifest.json"
    manifest = RenderPassManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    expected_build = collect_build_provenance(root, job_id)
    if (
        manifest.job_id != job_id
        or manifest.run_id != run_id
        or manifest.scene_spec_sha256 != scene_spec_sha256
        or manifest.camera_fingerprint != camera_fingerprint
        or manifest.build_fingerprint != expected_build["fingerprint"]
    ):
        raise ValueError("Interrupted QA pass snapshot no longer matches canonical inputs")
    kinds = [record.kind for record in manifest.passes]
    if len(kinds) != len(REQUIRED_QA_PASS_KINDS) or set(kinds) != set(
        REQUIRED_QA_PASS_KINDS
    ):
        raise ValueError("Interrupted QA pass snapshot is not the exact seven-pass set")
    pass_dir = (run_dir / "passes").resolve()
    passes: dict[str, Path] = {}
    for record in manifest.passes:
        artifact = _resolve_manifest_artifact(manifest_path, record)
        try:
            artifact.relative_to(pass_dir)
        except ValueError as exc:
            raise ValueError("Interrupted QA pass escapes the run-local pass directory") from exc
        if not artifact.is_file() or sha256_file(artifact) != record.sha256:
            raise ValueError(f"Interrupted QA pass is missing or changed: {record.kind}")
        passes[record.kind] = artifact
    return manifest, manifest_path, passes


def _target_prompt(job_id: str, request: VisualQARequest) -> str:
    """Create a constrained advisory-target prompt that preserves reference and camera roles."""

    return (
        f"Create an advisory visual-QA target for job {job_id}. "
        "Use the immutable reference only for visible structure, silhouette, landmarks, and "
        "large color regions. Use the current preview only for fixed camera angle, framing, "
        f"and resolution. Camera fingerprint: {request.camera_fingerprint}. "
        "Do not invent hidden landmarks or treat the generated result as recovered truth."
    )


def _relative_job_path(root: Path, path: Path) -> str:
    """Serialize a job-relative artifact path for portable latest-run metadata."""

    return path.resolve().relative_to(root.resolve()).as_posix()


def _generated_target_comparison(
    manifest: QATargetManifest,
    *,
    preview_path: Path,
    run_dir: Path,
    advisory_weight: float,
) -> tuple[list[QAFinding], list[str]]:
    """Compare only intact successful run-local targets and degrade failures to warnings."""

    if manifest.status not in {"generated", "cached"} or not manifest.output_path:
        return [], []
    target_path = Path(manifest.output_path).expanduser().resolve()
    try:
        target_path.relative_to(run_dir.resolve())
    except ValueError:
        return [], ["Advisory QA target comparison skipped: output is outside the QA run."]
    if not target_path.is_file():
        return [], ["Advisory QA target comparison skipped: output image is missing."]
    if manifest.output_sha256 is None or sha256_file(target_path) != manifest.output_sha256:
        return [], ["Advisory QA target comparison skipped: output image hash changed."]
    try:
        findings = compare_preview_to_generated_target(
            preview_path,
            target_path,
            advisory_weight=advisory_weight,
        )
    except (OSError, ValueError) as exc:
        return [], [
            "Advisory QA target comparison skipped: "
            f"{type(exc).__name__}: {exc}"
        ]
    return findings, []


def run_job_visual_qa(
    job_id: str,
    *,
    render_engine: str = "eevee",
    render_device: str = "auto",
    run_id: str | None = None,
    include_generated_target: bool = False,
    provider: QATargetProvider | None = None,
    target_prompt: str | None = None,
) -> dict[str, Any]:
    """Run one fixed-camera QA cycle and stop after non-executable revision candidates."""

    root = job_dir(job_id)
    metadata = load_job(job_id)
    scene_spec_path = root / "analysis" / "scene_spec.json"
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if spec.job_id != job_id:
        raise ValueError("job metadata and SceneSpec job_id do not match")
    spec_hash = sha256_file(scene_spec_path)
    fingerprint = camera_fingerprint(spec)
    selected_run_id = _validate_run_id(run_id or _new_run_id(spec_hash))
    run_dir = root / "qa" / "runs" / selected_run_id
    if run_dir.exists():
        run_manifest, manifest_path, passes = _resume_interrupted_render_snapshot(
            root,
            run_dir,
            job_id=job_id,
            run_id=selected_run_id,
            scene_spec_sha256=spec_hash,
            camera_fingerprint=fingerprint,
        )
    else:
        run_dir.mkdir(parents=True, exist_ok=False)
        rendered = _render_job_qa_passes(
            job_id,
            render_engine=render_engine,
            render_device=render_device,
            run_id=selected_run_id,
            camera_fingerprint=fingerprint,
            scene_spec_sha256=spec_hash,
        )
        shared_manifest_path = root / "reports" / "qa_pass_manifest.json"
        run_manifest, manifest_path, passes = _snapshot_render_passes(
            rendered,
            source_manifest_path=shared_manifest_path,
            run_dir=run_dir,
        )
    reference_path = find_reference(job_id)
    reference_mask_path, reference_mask_manifest_path = prepare_run_reference_mask(
        root=root,
        run_dir=run_dir,
        reference_path=reference_path,
        analysis_mask_path=_reference_content_mask(root),
        spec=spec,
        reference_content_scope=str(
            metadata.get("reference_content_scope", "full_reference")
        ),
    )
    request = create_visual_qa_request(
        job_id=job_id,
        run_id=selected_run_id,
        mode=str(metadata.get("mode", spec.mode)),
        reference_path=reference_path,
        reference_mask_path=reference_mask_path,
        preview_path=passes["beauty"],
        render_pass_manifest_path=manifest_path,
        scene_spec_path=scene_spec_path,
        include_generated_target=include_generated_target,
    )
    request_path = run_dir / "request.json"
    write_json_atomic(request_path, request.model_dump(mode="json"))
    validate_visual_qa_request(request, scene_spec_path=scene_spec_path)

    reference_source_ids = {
        source.id for source in spec.sources if source.kind == "reference"
    }
    report = compare_reference_to_render(
        request,
        silhouette_path=passes["silhouette"],
        object_id_path=passes["object_id"],
        object_id_colors=run_manifest.object_id_colors,
        observed_regions=observed_regions_from_scene_spec(
            scene_spec_path,
            source_ids=reference_source_ids,
        ),
    )
    target_manifest_path: Path | None = None
    target_prompt_path: Path | None = None
    if include_generated_target:
        advisory_weight = load_feature_config().qa.generated_target_weight
        prompt = target_prompt or _target_prompt(job_id, request)
        target_prompt_path = run_dir / "target" / "prompt.txt"
        target_prompt_path.parent.mkdir(parents=True, exist_ok=True)
        target_prompt_path.write_text(prompt, encoding="utf-8")
        target_manifest = generate_optional_qa_target(
            request,
            provider=provider,
            prompt=prompt,
            output_path=run_dir / "target" / "qa_target.png",
        )
        target_manifest = target_manifest.model_copy(
            update={"prompt_path": str(target_prompt_path)}
        )
        target_manifest_path = run_dir / "qa_target_manifest.json"
        write_json_atomic(target_manifest_path, target_manifest.model_dump(mode="json"))
        advisory_findings, advisory_warnings = _generated_target_comparison(
            target_manifest,
            preview_path=passes["beauty"],
            run_dir=run_dir,
            advisory_weight=advisory_weight,
        )
        report = merge_advisory_target_result(
            report,
            target_manifest,
            findings=advisory_findings,
        )
        if advisory_warnings:
            report = report.model_copy(
                update={"warnings": [*report.warnings, *advisory_warnings]}
            )

    surface_report = validate_job_surface_details(
        job_id,
        require_materials=None,
        write_report=True,
    )
    if not surface_report.ok:
        failures = "; ".join(
            item.message
            for item in surface_report.checks
            if item.status == "failed"
        )
        raise ValueError(f"Surface-detail QA prerequisite failed: {failures}")
    surface_warnings = [
        item.message for item in surface_report.checks if item.status == "warning"
    ]
    surface_status = (
        surface_report.material_status
        if (root / "analysis" / "modeling_plan.json").is_file()
        else "not_declared"
    )
    report = report.model_copy(
        update={
            "surface_detail_summary": SurfaceDetailQASummary(
                contract_status=surface_status,
                declared_details=surface_report.total,
                texture_bound_details=(
                    surface_report.textured
                    if surface_report.material_status == "validated"
                    else 0
                ),
                omitted_details=surface_report.omitted,
                failed_checks=surface_report.failed,
                report_path="reports/surface_detail_validation.json",
                warnings=surface_warnings,
            )
        }
    )
    report = enrich_direct_qa_suggestions(report, spec)
    report_path = run_dir / "visual_qa_report.json"
    write_json_atomic(report_path, report.model_dump(mode="json"))
    candidates = build_revision_candidates(
        report,
        report_path=report_path,
        scene_spec_path=scene_spec_path,
    )
    candidates_path = run_dir / "revision_candidates.json"
    write_json_atomic(candidates_path, candidates.model_dump(mode="json"))
    group_suggestions = [
        finding
        for finding in report.findings
        if finding.id.startswith("direct.group_position.")
    ]
    direct_findings = [
        finding
        for finding in report.findings
        if (
            not finding.id.startswith("direct.group_position.")
            and "direct_reference" in finding.evidence_sources
        )
    ]
    generated_target_advisories = [
        finding
        for finding in report.findings
        if (
            not finding.id.startswith("direct.group_position.")
            and set(finding.evidence_sources) == {"generated_target"}
        )
    ]
    latest_path = root / "qa" / "latest.json"
    latest = {
        "schema_version": "0.6.0",
        "job_id": job_id,
        "run_id": selected_run_id,
        "scene_spec_sha256": spec_hash,
        "camera_fingerprint": fingerprint,
        "request": _relative_job_path(root, request_path),
        "reference_mask": _relative_job_path(root, reference_mask_path),
        "reference_mask_manifest": _relative_job_path(root, reference_mask_manifest_path),
        "render_pass_manifest": _relative_job_path(root, manifest_path),
        "visual_qa_report": _relative_job_path(root, report_path),
        "revision_candidates": _relative_job_path(root, candidates_path),
        "qa_target_manifest": (
            _relative_job_path(root, target_manifest_path)
            if target_manifest_path is not None
            else None
        ),
        "qa_target_prompt": (
            _relative_job_path(root, target_prompt_path)
            if target_prompt_path is not None
            else None
        ),
    }
    write_json_atomic(latest_path, latest)
    return {
        "ok": True,
        "job_id": job_id,
        "run_id": selected_run_id,
        "run_dir": str(run_dir),
        "request": str(request_path),
        "reference_mask": str(reference_mask_path),
        "reference_mask_manifest": str(reference_mask_manifest_path),
        "render_pass_manifest": str(manifest_path),
        "visual_qa_report": str(report_path),
        "revision_candidates": str(candidates_path),
        "qa_target_manifest": str(target_manifest_path) if target_manifest_path else None,
        "qa_target_prompt": str(target_prompt_path) if target_prompt_path else None,
        "direct_score": report.direct_metrics.overall_direct_score,
        # finding_count remains the compatibility alias for direct-reference findings.
        "finding_count": len(direct_findings),
        "direct_finding_count": len(direct_findings),
        "generated_target_advisory_count": len(generated_target_advisories),
        "group_suggestion_count": len(group_suggestions),
        "candidate_count": len(candidates.candidates),
        "generated_target_status": report.generated_target_status,
        "latest": str(latest_path),
    }
