from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from codex_blender_modeler.auto_revision.models import RevisionCandidates
from codex_blender_modeler.baking import load_bake_manifest
from codex_blender_modeler.materials import load_material_plan
from codex_blender_modeler.qa.models import RenderPassManifest, VisualQAReport
from codex_blender_modeler.reporting import (
    HumanReportManifest,
    ReportScope,
    collect_job_report_payload,
    report_output_dir,
)
from codex_blender_modeler.texturing import load_texture_manifest
from codex_blender_modeler.workspace import job_dir, sha256_file

EXPECTED_PASSES = {
    "beauty",
    "silhouette",
    "object_id",
    "material_id",
    "normal",
    "depth",
    "wireframe",
}


def _load_json(path: Path) -> dict[str, Any]:
    """Load one required V0.6 gate artifact as a JSON object."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _resolve_artifact(owner: Path, value: str) -> Path:
    """Resolve an absolute or owner-relative generated artifact path."""

    candidate = Path(value)
    return candidate.resolve() if candidate.is_absolute() else (owner.parent / candidate).resolve()


def verify_material_gate(job_id: str) -> dict[str, Any]:
    """Verify the material plan, Blender inspection report, and hashed swatches."""

    root = job_dir(job_id)
    plan_path = root / "analysis" / "material_plan.json"
    plan = load_material_plan(plan_path)
    contract = _load_json(root / "reports" / "material_contract_validation.json")
    blender_report = _load_json(root / "reports" / "material_validation.json")
    swatch_path = root / "reports" / "material_swatches.json"
    swatches = _load_json(swatch_path)
    if contract.get("ok") is not True or blender_report.get("ok") is not True:
        raise RuntimeError("Material host or Blender validation did not pass")
    records = swatches.get("swatches", [])
    if len(records) != len(plan.materials):
        raise RuntimeError("Material swatch count does not match MaterialPlan")
    for record in records:
        artifact = _resolve_artifact(swatch_path, str(record["path"]))
        if not artifact.is_file() or sha256_file(artifact) != record["sha256"]:
            raise RuntimeError(f"Material swatch is missing or stale: {artifact}")
    attached = [item for item in plan.materials if item.texture_manifest]
    if not attached:
        raise RuntimeError("Material gate requires at least one attached TextureManifest")
    texture_channels = 0
    for item in attached:
        manifest_path = (root / str(item.texture_manifest)).resolve()
        manifest = load_texture_manifest(manifest_path)
        if manifest.material_id != item.material_id:
            raise RuntimeError(f"Texture manifest material mismatch: {manifest_path}")
        hashes = manifest.provenance.generated_sha256 if manifest.provenance else {}
        for channel_name, channel in manifest.channels.items():
            if channel.source != "image" or not channel.path:
                continue
            artifact = (manifest_path.parent / channel.path).resolve()
            expected = hashes.get(channel_name)
            if not artifact.is_file() or not expected or sha256_file(artifact) != expected:
                raise RuntimeError(f"Texture channel is missing or stale: {artifact}")
            texture_channels += 1
    bake_report = _load_json(root / "reports" / "material_bakes.json")
    if bake_report.get("ok") is not True:
        raise RuntimeError("Material bake report did not pass")
    baked_outputs = 0
    for relative in bake_report.get("manifest_paths", []):
        manifest_path = (root / str(relative)).resolve()
        manifest = load_bake_manifest(manifest_path)
        if manifest.status != "complete":
            raise RuntimeError(f"Material bake is incomplete: {manifest_path}")
        for output in manifest.outputs:
            artifact = (root / output.path).resolve()
            if not artifact.is_file() or sha256_file(artifact) != output.sha256:
                raise RuntimeError(f"Baked channel is missing or stale: {artifact}")
            baked_outputs += 1
    return {
        "job_id": job_id,
        "material_count": len(plan.materials),
        "swatch_count": len(records),
        "warning_count": len(blender_report.get("warnings", [])),
        "attached_texture_count": len(attached),
        "texture_channel_count": texture_channels,
        "baked_output_count": baked_outputs,
        "ok": True,
    }


def verify_visual_qa_gate(job_id: str) -> dict[str, Any]:
    """Verify the latest fixed-camera pass, report, and non-executable candidates."""

    root = job_dir(job_id)
    latest = _load_json(root / "qa" / "latest.json")
    run_dir = root / "qa" / "runs" / str(latest["run_id"])
    manifest_path = run_dir / "render_pass_manifest.json"
    manifest = RenderPassManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    report_path = run_dir / "visual_qa_report.json"
    report = VisualQAReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    candidates_path = run_dir / "revision_candidates.json"
    candidates = RevisionCandidates.model_validate_json(
        candidates_path.read_text(encoding="utf-8")
    )
    kinds = {record.kind for record in manifest.passes}
    if kinds != EXPECTED_PASSES:
        raise RuntimeError(f"QA pass coverage mismatch: {sorted(kinds)}")
    for record in manifest.passes:
        artifact = _resolve_artifact(manifest_path, record.path)
        if not artifact.is_file() or sha256_file(artifact) != record.sha256:
            raise RuntimeError(f"QA pass is missing or stale: {record.kind}")
    if manifest.camera_fingerprint != report.camera_fingerprint:
        raise RuntimeError("QA manifest and report camera fingerprints differ")
    if report.generated_target_status not in {"not_requested", "failed", "generated", "cached"}:
        raise RuntimeError("Unexpected generated target status")
    if any(item.applicability == "auto_safe" for item in candidates.candidates):
        raise RuntimeError("Visual QA produced an implicitly auto-safe revision candidate")
    return {
        "job_id": job_id,
        "run_id": manifest.run_id,
        "pass_count": len(manifest.passes),
        "direct_score": report.direct_metrics.overall_direct_score,
        "finding_count": len(report.findings),
        "candidate_count": len(candidates.candidates),
        "generated_target_status": report.generated_target_status,
        "ok": True,
    }


def verify_pdf_gate(job_id: str, scope: ReportScope) -> dict[str, Any]:
    """Verify one derived PDF, its sidecar hash, and its current source fingerprint."""

    pdf_path = report_output_dir(job_id) / f"{scope}_report.pdf"
    manifest_path = pdf_path.with_suffix(".manifest.json")
    manifest = HumanReportManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if not pdf_path.is_file() or sha256_file(pdf_path) != manifest.pdf_sha256:
        raise RuntimeError(f"Human-readable PDF is missing or stale: {pdf_path}")
    payload = collect_job_report_payload(
        job_id,
        scope,
        qa_run_id=manifest.qa_run_id,
    )
    if payload["source_fingerprint"] != manifest.source_fingerprint:
        raise RuntimeError(f"Human-readable PDF sources are stale: {pdf_path}")
    return {
        "job_id": job_id,
        "scope": scope,
        "pdf": str(pdf_path),
        "source_count": len(manifest.sources),
        "warning_count": len(manifest.warnings),
        "ok": True,
    }


def main() -> None:
    """Write one durable V0.5/V0.6 artifact verification report."""

    material_job = os.getenv("CBM_V06_MATERIAL_JOB", "geometry_showcase")
    qa_job = os.getenv("CBM_V06_QA_JOB", "first_reference_test")
    report = {
        "schema_version": "0.6.0",
        "material": verify_material_gate(material_job),
        "visual_qa": verify_visual_qa_gate(qa_job),
        "material_pdf": verify_pdf_gate(material_job, "material"),
        "qa_pdf": verify_pdf_gate(qa_job, "qa"),
        "full_pdf": verify_pdf_gate(material_job, "full"),
        "ok": True,
    }
    output = Path(__file__).resolve().parents[1] / "reports" / "v06_completion_regression.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
