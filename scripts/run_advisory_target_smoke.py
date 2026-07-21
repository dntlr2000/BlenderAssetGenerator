from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codex_blender_modeler.config import get_settings
from codex_blender_modeler.qa import ExistingFileQATargetProvider, run_job_visual_qa
from codex_blender_modeler.qa.models import QATargetManifest, VisualQAReport
from codex_blender_modeler.workspace import job_dir


def _load_json(path: Path) -> dict[str, Any]:
    """Load one required smoke artifact as a JSON object."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def main() -> None:
    """Exercise the explicit advisory-target adapter without changing direct QA authority."""

    root = job_dir("geometry_showcase")
    latest = _load_json(root / "qa" / "latest.json")
    baseline_run = root / "qa" / "runs" / str(latest["run_id"])
    baseline_report = VisualQAReport.model_validate_json(
        (baseline_run / "visual_qa_report.json").read_text(encoding="utf-8")
    )
    baseline_candidates = _load_json(baseline_run / "revision_candidates.json")
    source = (root / "renders" / "preview.png").resolve(strict=True)
    prompt = (
        "V0.6 integration fixture: use reference content and the preview camera exactly; "
        "do not invent geometry."
    )
    provider = ExistingFileQATargetProvider(
        source,
        model="existing-file-integration-fixture",
        model_version="1",
        seed=606,
        allowed_root=source.parent,
    )
    result = run_job_visual_qa(
        "geometry_showcase",
        include_generated_target=True,
        provider=provider,
        target_prompt=prompt,
    )
    target_manifest = QATargetManifest.model_validate_json(
        Path(str(result["qa_target_manifest"])).read_text(encoding="utf-8")
    )
    target_prompt = Path(str(result["qa_target_prompt"]))
    report = VisualQAReport.model_validate_json(
        Path(str(result["visual_qa_report"])).read_text(encoding="utf-8")
    )
    if target_manifest.status != "generated" or not target_manifest.advisory_only:
        raise RuntimeError("Advisory target was not recorded as generated advisory evidence")
    if target_prompt.read_text(encoding="utf-8") != prompt:
        raise RuntimeError("The exact advisory target prompt was not preserved")
    if report.direct_metrics != baseline_report.direct_metrics:
        raise RuntimeError("Advisory target changed authoritative direct metrics")
    if result["candidate_count"] != len(baseline_candidates.get("candidates", [])):
        raise RuntimeError("Advisory target changed the direct revision candidate count")
    generated_findings = [
        finding
        for finding in report.findings
        if finding.evidence_sources == ["generated_target"]
    ]
    if any(finding.suggestion is not None for finding in generated_findings):
        raise RuntimeError("Generated-target-only evidence produced an executable suggestion")
    smoke_report = {
        "schema_version": "0.6.0",
        "job_id": "geometry_showcase",
        "run_id": result["run_id"],
        "generated_target_status": report.generated_target_status,
        "direct_score_unchanged": True,
        "candidate_count_unchanged": True,
        "prompt_preserved": True,
        "generated_finding_count": len(generated_findings),
        "ok": True,
    }
    output = get_settings().repo_root / "reports" / "v06_advisory_target_regression.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(smoke_report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(smoke_report, indent=2))


if __name__ == "__main__":
    main()
