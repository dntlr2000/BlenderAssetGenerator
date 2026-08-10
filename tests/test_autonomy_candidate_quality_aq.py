"""Focused host tests for candidate-stage Autonomous Quality gate projection."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from codex_blender_modeler.autonomy.candidate_evaluator import (
    _CANDIDATE_STAGE_GATE_IDS,
    _candidate_stage_assessment,
)
from codex_blender_modeler.integrated_quality import HardGateResult, IntegratedQualityReport


def _report(
    *,
    reference_status: str = "warning",
    gate_statuses: dict[str, str] | None = None,
) -> IntegratedQualityReport:
    """Build the narrow report projection consumed by the private stage assessor."""

    statuses = gate_statuses or {}
    gates = [
        HardGateResult(
            gate_id=gate_id,
            axis=(
                "production_readiness"
                if gate_id == "gate.aq.topology_profile"
                else "structural_integrity"
            ),
            status=statuses.get(gate_id, "passed"),  # type: ignore[arg-type]
            required=True,
            blocking=statuses.get(gate_id, "passed") == "failed",
            evidence_ids=["candidate-structural"],
            message="candidate-stage fixture",
        )
        for gate_id in _CANDIDATE_STAGE_GATE_IDS
    ]
    gates.append(
        HardGateResult(
            gate_id="gate.aq.package_dependencies",
            axis="production_readiness",
            status="unscorable",
            required=False,
            blocking=False,
            evidence_ids=["candidate-production"],
            message="later-stage package evidence is intentionally unavailable",
        )
    )
    projection = SimpleNamespace(
        axes=[SimpleNamespace(axis="reference_alignment", status=reference_status)],
        hard_gates=gates,
    )
    return cast(IntegratedQualityReport, projection)


def test_candidate_stage_pass_ignores_only_later_unavailable_axes() -> None:
    """Allow ranking after exact reference/structural gates without inventing package pass."""

    assessment = _candidate_stage_assessment(_report())

    assert assessment.hard_gate_failures == 0
    assert assessment.structural_quality == 1.0
    assert assessment.evidence_status == "scored"


def test_candidate_stage_failure_and_unscorable_evidence_fail_closed() -> None:
    """Distinguish a definitive topology failure from unavailable required assembly evidence."""

    failed = _candidate_stage_assessment(
        _report(gate_statuses={"gate.aq.topology_profile": "failed"})
    )
    assert failed.hard_gate_failures == 1
    assert failed.structural_quality == 7 / 8
    assert failed.evidence_status == "invalid"

    unscorable = _candidate_stage_assessment(
        _report(gate_statuses={"gate.aq.required_assembly": "unscorable"})
    )
    assert unscorable.hard_gate_failures == 0
    assert unscorable.structural_quality is None
    assert unscorable.evidence_status == "unscorable"

