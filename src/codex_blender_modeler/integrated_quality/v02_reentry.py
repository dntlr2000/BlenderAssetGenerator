"""Machine-readable quality finding reentry routing for IQ 0.2."""

from __future__ import annotations

from .v02_models import QualityFindingV02, ReentryDecisionV02

_DESTINATIONS = {
    "camera": "v0.4_structural_authoring",
    "contour": "v0.4_structural_authoring",
    "semantic": "v0.4_structural_authoring",
    "local_proportion": "v0.6_parametric_convergence",
    "topology": "v0.7_production_repair",
    "uv": "v0.7_production_repair",
    "normal": "v0.7_production_repair",
    "missing_evidence": "manual_evidence_review",
    "restricted_scope": "restricted_scope_required",
}


def route_quality_finding_v02(finding: QualityFindingV02) -> ReentryDecisionV02:
    """Route one finding without authorizing an automatic canonical change."""

    destination = _DESTINATIONS[finding.category]
    return ReentryDecisionV02(
        finding_id=finding.finding_id,
        category=finding.category,
        destination=destination,  # type: ignore[arg-type]
        target_ids=finding.target_ids,
        reason_code=f"reentry.{finding.category}",
        message=(
            f"Route {finding.category} evidence to {destination}; this report does not "
            "authorize an automatic canonical write."
        ),
    )


def route_quality_findings_v02(
    findings: list[QualityFindingV02],
) -> list[ReentryDecisionV02]:
    """Route a unique set of findings in their stable input order."""

    identifiers = [item.finding_id for item in findings]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("quality finding IDs must be unique")
    return [route_quality_finding_v02(item) for item in findings]
