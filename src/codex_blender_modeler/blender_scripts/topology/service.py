"""Profile-driven topology evaluator that never converts missing evidence to pass."""

from __future__ import annotations

from .models import (
    TopologyCheckResult,
    TopologyCompanionReport,
    TopologyObservation,
    TopologyProfileName,
    TopologyProvenance,
)
from .profiles import get_topology_profile


def evaluate_topology_profile(
    *,
    report_id: str,
    provenance: TopologyProvenance,
    profile_name: TopologyProfileName,
    observations: list[TopologyObservation],
) -> TopologyCompanionReport:
    """Evaluate all profile checks with hard, warning, and unscorable outcomes."""

    profile = get_topology_profile(profile_name)
    by_name = {item.check: item for item in observations}
    if len(by_name) != len(observations):
        raise ValueError("topology observations must be unique by check")
    results: list[TopologyCheckResult] = []
    for policy in profile.checks:
        observation = by_name.get(policy.check)
        if observation is None:
            results.append(
                TopologyCheckResult(
                    check=policy.check,
                    outcome="unscorable",
                    profile_failure_severity=policy.failure_severity,
                    message="Required profile evidence was not supplied.",
                )
            )
            continue
        if observation.availability == "unavailable":
            outcome = "unscorable"
        elif observation.availability == "not_applicable":
            outcome = "not_applicable"
        elif observation.passed:
            outcome = "passed"
        else:
            outcome = policy.failure_severity
        results.append(
            TopologyCheckResult(
                check=policy.check,
                outcome=outcome,
                profile_failure_severity=policy.failure_severity,
                measured_value=observation.measured_value,
                threshold=observation.threshold,
                evidence=observation.evidence,
                message=observation.message,
            )
        )
    hard_failures = sum(item.outcome == "hard_failure" for item in results)
    warnings = sum(item.outcome == "warning" for item in results)
    unscorable = sum(item.outcome == "unscorable" for item in results)
    hard_unscorable = any(
        item.outcome == "unscorable" and item.profile_failure_severity == "hard_failure"
        for item in results
    )
    warning_unscorable = any(
        item.outcome == "unscorable" and item.profile_failure_severity == "warning"
        for item in results
    )
    status = (
        "failed"
        if hard_failures
        else "unscorable"
        if hard_unscorable
        else "warning"
        if warnings or warning_unscorable
        else "passed"
    )
    return TopologyCompanionReport(
        report_id=report_id,
        provenance=provenance,
        profile=profile,
        status=status,
        ok=status in {"passed", "warning"},
        results=results,
        hard_failures=hard_failures,
        warnings=warnings,
        unscorable=unscorable,
        notes=[
            "Unavailable UV, tangent, LOD, or round-trip evidence remains unscorable.",
            (
                "Unavailable warning-only checks remain explicit per-check unscorable "
                "evidence but do not convert passed hard checks into an aggregate failure."
            ),
            "This profile report does not claim manufacturing or runtime behavior parity.",
        ],
    )
