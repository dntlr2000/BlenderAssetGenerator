"""Fail-closed evaluation helpers for integrated quality hard gates."""

from __future__ import annotations

from datetime import datetime

from .models import (
    AxisThreshold,
    HardGateResult,
    ProducerIdentity,
    QualityArtifact,
    QualityAxisResult,
    QualityGateProfile,
    QualityGateRule,
    quality_artifact_input_sha256,
)


def build_default_quality_gate_profile(
    *,
    profile_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    source_fingerprint: str,
    producer: ProducerIdentity,
    created_at: datetime,
    provenance: list[QualityArtifact] | None = None,
) -> QualityGateProfile:
    """Build the strict static-prop profile used by the first autonomous controller."""

    exact_inputs = list(provenance or [])
    return QualityGateProfile(
        schema_version="0.1.0",
        profile_id=profile_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=quality_artifact_input_sha256(exact_inputs),
        source_fingerprint=source_fingerprint,
        producer=producer,
        provenance=exact_inputs,
        created_at=created_at,
        axis_thresholds=[
            AxisThreshold(
                axis="reference_alignment",
                required=True,
                pass_score=0.78,
                warning_score=0.60,
            ),
            AxisThreshold(
                axis="structural_integrity",
                required=True,
                pass_score=1.0,
                warning_score=0.95,
            ),
            AxisThreshold(
                axis="material_fidelity",
                required=True,
                pass_score=0.90,
                warning_score=0.75,
            ),
            AxisThreshold(
                axis="production_readiness",
                required=True,
                pass_score=1.0,
                warning_score=0.95,
            ),
        ],
        gate_rules=[
            QualityGateRule(
                gate_id="gate.structural_integrity",
                axis="structural_integrity",
                required=True,
                accepted_statuses=["passed"],
                message="Structural integrity must pass before terminal acceptance.",
            ),
            QualityGateRule(
                gate_id="gate.material_fidelity",
                axis="material_fidelity",
                required=True,
                accepted_statuses=["passed"],
                message="Material fidelity must pass before terminal acceptance.",
            ),
            QualityGateRule(
                gate_id="gate.production_readiness",
                axis="production_readiness",
                required=True,
                accepted_statuses=["passed"],
                message="Clean package readiness must pass before terminal acceptance.",
            ),
        ],
        meaningful_gain_min=0.01,
        critical_regression_tolerance=0.0,
    )


def evaluate_hard_gates(
    profile: QualityGateProfile,
    axes: list[QualityAxisResult],
) -> list[HardGateResult]:
    """Evaluate profile rules without converting unavailable evidence into a failure score."""

    by_axis = {axis.axis: axis for axis in axes}
    results: list[HardGateResult] = []
    for rule in profile.gate_rules:
        axis = by_axis.get(rule.axis)
        if axis is None or axis.status == "unscorable":
            results.append(
                HardGateResult(
                    gate_id=rule.gate_id,
                    axis=rule.axis,
                    status="unscorable",
                    required=rule.required,
                    blocking=False,
                    evidence_ids=[] if axis is None else axis.evidence_ids,
                    message=(
                        f"{rule.message} Required evidence is unavailable, so the gate "
                        "is unscorable rather than failed."
                    ),
                )
            )
            continue
        passed = axis.status in set(rule.accepted_statuses)
        results.append(
            HardGateResult(
                gate_id=rule.gate_id,
                axis=rule.axis,
                status="passed" if passed else "failed",
                required=rule.required,
                blocking=rule.required and not passed,
                evidence_ids=axis.evidence_ids,
                message=rule.message if passed else f"{rule.message} Axis status={axis.status}.",
            )
        )
    return results


def blocking_gate_messages(results: list[HardGateResult]) -> list[str]:
    """Return stable human-readable reasons for definitive required-gate failures."""

    return [f"{item.gate_id}: {item.message}" for item in results if item.blocking]
