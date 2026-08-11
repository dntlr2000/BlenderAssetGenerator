"""Focused hard-gate, Pareto, and minimum-change ranking tests for IQ 0.2."""

from __future__ import annotations

from datetime import UTC, datetime

from codex_blender_modeler.integrated_quality.v02_models import (
    IntegratedQualityPolicyV02,
    ProducerIdentityV02,
    RankableCandidateV02,
)
from codex_blender_modeler.integrated_quality.v02_ranking import (
    rank_quality_candidates_v02,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)
SHA_A = "a" * 64
PRODUCER = ProducerIdentityV02(name="cbm_integrated_quality_v02", version="0.2.0")
POLICY = IntegratedQualityPolicyV02(
    profile_id="quality.static_prop_v02",
    lexicographic_metric_priority=["reference.contour", "semantic.critical"],
)


def _candidate(
    candidate_id: str,
    *,
    contour: float,
    semantic: float,
    hard_gate_status: str = "passed",
    evidence: bool = True,
    regressions: list[str] | None = None,
    meaningful_gain: bool = True,
    paths: int = 1,
    magnitude: float = 0.1,
) -> RankableCandidateV02:
    """Build one deterministic ranking input."""

    return RankableCandidateV02(
        candidate_id=candidate_id,
        candidate_sha256=SHA_A,
        report_path=f"candidates/{candidate_id}/report.json",
        report_sha256=SHA_A,
        hard_gate_status=hard_gate_status,
        required_evidence_available=evidence,
        critical_regressions=regressions or [],
        meaningful_gain=meaningful_gain,
        gains={
            "reference.contour": contour,
            "semantic.critical": semantic,
        },
        changed_path_count=paths,
        change_magnitude=magnitude,
    )


def test_pareto_then_lexicographic_then_minimum_change_ranking() -> None:
    """Keep the non-dominated set and select by explicit priority before change cost."""

    candidates = [
        _candidate("candidate-a", contour=0.05, semantic=0.04, paths=2),
        _candidate("candidate-b", contour=0.04, semantic=0.06, paths=1),
        _candidate("candidate-c", contour=0.02, semantic=0.02, paths=1),
    ]
    ranking = rank_quality_candidates_v02(
        candidates,
        ranking_id="ranking-a",
        source_fingerprint=SHA_A,
        policy=POLICY,
        producer=PRODUCER,
        created_at=NOW,
    )
    assert ranking.outcome == "selected"
    assert ranking.selected_candidate_id == "candidate-a"
    assert ranking.pareto_candidate_ids == ["candidate-a", "candidate-b"]
    record_c = next(item for item in ranking.records if item.candidate_id == "candidate-c")
    assert record_c.pareto_front == 1


def test_hard_gate_regression_and_missing_evidence_are_removed_before_ranking() -> None:
    """Exclude unsafe candidates even when their numerical gains dominate."""

    candidates = [
        _candidate(
            "failed-gate",
            contour=1.0,
            semantic=1.0,
            hard_gate_status="failed",
        ),
        _candidate(
            "regression",
            contour=0.9,
            semantic=0.9,
            regressions=["semantic.trigger"],
        ),
        _candidate(
            "missing-evidence",
            contour=0.8,
            semantic=0.8,
            evidence=False,
        ),
        _candidate("eligible", contour=0.02, semantic=0.02),
    ]
    ranking = rank_quality_candidates_v02(
        candidates,
        ranking_id="ranking-safe",
        source_fingerprint=SHA_A,
        policy=POLICY,
        producer=PRODUCER,
        created_at=NOW,
    )
    assert ranking.selected_candidate_id == "eligible"
    rejected = {item.candidate_id: item for item in ranking.records if not item.eligible}
    assert "hard_gate_failed" in rejected["failed-gate"].rejection_reasons
    assert "critical_regression" in rejected["regression"].rejection_reasons
    assert "required_evidence_unavailable" in rejected["missing-evidence"].rejection_reasons


def test_all_ineligible_returns_null_selection_and_explicit_reason() -> None:
    """Return selected=null rather than promoting the least-bad unsafe candidate."""

    candidates = [
        _candidate(
            "unscorable",
            contour=0.2,
            semantic=0.2,
            hard_gate_status="unscorable",
        ),
        _candidate(
            "plateau",
            contour=0.0,
            semantic=0.0,
            meaningful_gain=False,
        ),
        _candidate(
            "below-policy-gain",
            contour=0.001,
            semantic=0.001,
            meaningful_gain=True,
        ),
    ]
    ranking = rank_quality_candidates_v02(
        candidates,
        ranking_id="ranking-none",
        source_fingerprint=SHA_A,
        policy=POLICY,
        producer=PRODUCER,
        created_at=NOW,
    )
    assert ranking.outcome == "rejected_no_eligible_candidate"
    assert ranking.selected_candidate_id is None
    assert ranking.pareto_candidate_ids == []
    assert all(not item.eligible for item in ranking.records)
    below = next(
        item for item in ranking.records if item.candidate_id == "below-policy-gain"
    )
    assert "no_meaningful_gain" in below.rejection_reasons
