"""Additive V0.6 finding projection for Integrated Quality 0.2."""

from __future__ import annotations

import hashlib

from ..qa.models import QAFinding, VisualQAReport
from .v02_models import FindingCategory, QualityFindingV02

_AUTHORITATIVE_SOURCES = frozenset({"direct_reference", "constraint"})
_CATEGORY_BY_ISSUE_TYPE: dict[str, FindingCategory] = {
    "silhouette": "contour",
    "position": "local_proportion",
    "proportion": "local_proportion",
    "missing": "semantic",
    "camera": "camera",
    "depth_order": "local_proportion",
    "color_block": "missing_evidence",
    "constraint": "local_proportion",
    "other": "missing_evidence",
}


def _finding_id(finding: QAFinding, index: int) -> str:
    """Create one stable IQ-safe identity without trusting free-form V0.6 IDs."""

    digest = hashlib.sha256(f"{index}\0{finding.id}".encode()).hexdigest()
    return f"finding.v06.{digest[:24]}"


def project_authoritative_v06_findings_v02(
    report: VisualQAReport,
    *,
    evidence_id: str,
) -> list[QualityFindingV02]:
    """Project high authoritative V0.6 findings without changing the direct score."""

    projected: list[QualityFindingV02] = []
    for index, finding in enumerate(report.findings):
        if finding.severity != "high" or not _AUTHORITATIVE_SOURCES.intersection(
            finding.evidence_sources
        ):
            continue
        projected.append(
            QualityFindingV02(
                finding_id=_finding_id(finding, index),
                category=_CATEGORY_BY_ISSUE_TYPE[finding.issue_type],
                severity="high",
                authoritative=True,
                target_ids=list(finding.target_ids),
                evidence_ids=[evidence_id],
                message=f"V0.6 finding {finding.id}: {finding.description}",
            )
        )
    return projected
