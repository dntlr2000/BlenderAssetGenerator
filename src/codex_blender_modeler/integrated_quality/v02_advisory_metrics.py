"""Advisory-only depth, normal, and generated-target metrics for IQ 0.2."""

from __future__ import annotations

from typing import Literal

from .v02_models import AdvisoryMetricV02


def build_advisory_metric_v02(
    *,
    metric_id: str,
    kind: Literal["estimated_depth", "estimated_normal", "generated_target"],
    value: float | None,
    confidence: float,
    provider: str | None = None,
    model: str | None = None,
    version: str | None = None,
    artifact_sha256: str | None = None,
    unavailable_reason: str | None = None,
) -> AdvisoryMetricV02:
    """Build a provenance-complete advisory metric or an explicit unscorable record."""

    if value is None:
        return AdvisoryMetricV02(
            metric_id=metric_id,
            kind=kind,
            status="unscorable",
            value=None,
            confidence=0,
            limitations=[unavailable_reason or "advisory provider evidence is unavailable"],
        )
    return AdvisoryMetricV02(
        metric_id=metric_id,
        kind=kind,
        status="scored",
        value=value,
        confidence=confidence,
        provider=provider,
        model=model,
        version=version,
        artifact_sha256=artifact_sha256,
        limitations=["advisory evidence has no hard-gate or promotion authority"],
    )
