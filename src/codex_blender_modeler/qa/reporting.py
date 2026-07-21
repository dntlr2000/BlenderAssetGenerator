from __future__ import annotations

from .models import QAFinding, QATargetManifest, VisualQAReport


def merge_advisory_target_result(
    report: VisualQAReport,
    manifest: QATargetManifest,
    *,
    findings: list[QAFinding] | None = None,
) -> VisualQAReport:
    """Attach advisory target findings without changing direct-reference metrics."""

    if (report.job_id, report.run_id) != (manifest.job_id, manifest.run_id):
        raise ValueError("QA target manifest does not belong to the direct report run")
    if report.request_sha256 != manifest.request_sha256:
        raise ValueError("QA target manifest was generated from a different request")
    if report.camera_fingerprint != manifest.camera_fingerprint:
        raise ValueError("QA target manifest was generated from a different camera")
    advisory_findings = findings or []
    if any(
        set(finding.evidence_sources) != {"generated_target"}
        for finding in advisory_findings
    ):
        raise ValueError("advisory target findings must cite only generated_target evidence")
    if any(finding.suggestion is not None for finding in advisory_findings):
        raise ValueError("advisory target findings cannot include executable suggestions")
    warnings = list(report.warnings)
    if manifest.status == "failed":
        warnings.append(f"Optional QA target provider failed: {manifest.error}")
    elif manifest.status == "disabled":
        warnings.append("Optional QA target provider is disabled.")
    status = {
        "disabled": "not_requested",
        "generated": "generated",
        "cached": "cached",
        "failed": "failed",
    }[manifest.status]
    return report.model_copy(
        update={
            "findings": [*report.findings, *advisory_findings],
            "generated_target_status": status,
            "warnings": warnings,
        }
    )
