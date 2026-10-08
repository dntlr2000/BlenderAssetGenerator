"""Additive V0.6 finding projection for Integrated Quality 0.2."""

from __future__ import annotations

import hashlib

from ..qa.direct_compare import direct_evidence_requires_review
from ..qa.models import QAFinding, VisualQAReport
from .v02_models import FindingCategory, QualityFindingV02

PART_EVIDENCE_FINDING_ID_V02 = "finding.v06.semantic_part_evidence_reliability"

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
    """Project high findings and explicit evidence blockers without changing V0.6 scores."""

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
    if direct_evidence_requires_review(report):
        projected.append(
            QualityFindingV02(
                finding_id=PART_EVIDENCE_FINDING_ID_V02,
                category="missing_evidence",
                severity="high",
                authoritative=True,
                target_ids=[],
                evidence_ids=[evidence_id],
                message=(
                    "Semantic part evidence requires review: shared whole-object boxes "
                    "do not establish distinct part-local support. This is not a geometry verdict."
                ),
            )
        )
    return projected
