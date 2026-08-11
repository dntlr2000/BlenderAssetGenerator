"""Hard-gate-first Pareto and minimum-change ranking for IQ 0.2."""

from __future__ import annotations

from datetime import datetime

from .v02_models import (
    CandidateRankingV02,
    CandidateRankRecordV02,
    IntegratedQualityPolicyV02,
    ProducerIdentityV02,
    RankableCandidateV02,
)


def _rejection_reasons(
    candidate: RankableCandidateV02,
    policy: IntegratedQualityPolicyV02,
) -> list[str]:
    """Return every fail-closed eligibility reason in policy precedence order."""

    reasons: list[str] = []
    if candidate.hard_gate_status == "failed":
        reasons.append("hard_gate_failed")
    elif candidate.hard_gate_status == "unscorable":
        reasons.append("hard_gate_unscorable")
    if not candidate.required_evidence_available:
        reasons.append("required_evidence_unavailable")
    if candidate.critical_regressions:
        reasons.append("critical_regression")
    if (
        not candidate.meaningful_gain
        or max(candidate.gains.values()) < policy.meaningful_gain_min
    ):
        reasons.append("no_meaningful_gain")
    return reasons


def _dominates(left: RankableCandidateV02, right: RankableCandidateV02) -> bool:
    """Return whether left is no worse on every metric and better on at least one."""

    metric_ids = sorted(left.gains)
    left_values = [left.gains[metric_id] for metric_id in metric_ids]
    right_values = [right.gains[metric_id] for metric_id in metric_ids]
    return all(
        left_value >= right_value
        for left_value, right_value in zip(left_values, right_values, strict=True)
    ) and any(
        left_value > right_value
        for left_value, right_value in zip(left_values, right_values, strict=True)
    )


def _pareto_fronts(candidates: list[RankableCandidateV02]) -> dict[str, int]:
    """Assign deterministic zero-based Pareto fronts to eligible candidates."""

    remaining = {item.candidate_id: item for item in candidates}
    fronts: dict[str, int] = {}
    front_index = 0
    while remaining:
        current = [
            candidate
            for candidate in remaining.values()
            if not any(
                _dominates(other, candidate)
                for other in remaining.values()
                if other.candidate_id != candidate.candidate_id
            )
        ]
        if not current:
            raise RuntimeError("Pareto ranking could not identify a non-dominated candidate")
        for candidate in sorted(current, key=lambda item: item.candidate_id):
            fronts[candidate.candidate_id] = front_index
            del remaining[candidate.candidate_id]
        front_index += 1
    return fronts


def rank_quality_candidates_v02(
    candidates: list[RankableCandidateV02],
    *,
    ranking_id: str,
    source_fingerprint: str,
    policy: IntegratedQualityPolicyV02,
    producer: ProducerIdentityV02,
    created_at: datetime,
) -> CandidateRankingV02:
    """Reject ineligible candidates, then apply Pareto, lexicographic, and cost ordering."""

    if not candidates:
        raise ValueError("IQ 0.2 candidate ranking requires at least one candidate")
    identifiers = [item.candidate_id for item in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("IQ 0.2 candidate IDs must be unique")
    rejected = {
        item.candidate_id: _rejection_reasons(item, policy) for item in candidates
    }
    eligible = [item for item in candidates if not rejected[item.candidate_id]]
    if not eligible:
        records = [
            CandidateRankRecordV02(
                candidate_id=item.candidate_id,
                eligible=False,
                rejection_reasons=rejected[item.candidate_id],
                reason="Candidate was removed before Pareto ranking by fail-closed eligibility.",
            )
            for item in sorted(candidates, key=lambda candidate: candidate.candidate_id)
        ]
        return CandidateRankingV02(
            ranking_id=ranking_id,
            source_fingerprint=source_fingerprint,
            policy_id=policy.profile_id,
            outcome="rejected_no_eligible_candidate",
            records=records,
            producer=producer,
            created_at=created_at,
        )
    gain_sets = {tuple(sorted(item.gains)) for item in eligible}
    if len(gain_sets) != 1:
        raise ValueError("eligible candidates must expose an identical gain metric set")
    gain_ids = set(eligible[0].gains)
    if not set(policy.lexicographic_metric_priority).issubset(gain_ids):
        raise ValueError("lexicographic priority references an unavailable candidate metric")
    fronts = _pareto_fronts(eligible)
    ordered = sorted(
        eligible,
        key=lambda candidate: (
            fronts[candidate.candidate_id],
            *(
                -candidate.gains[metric_id]
                for metric_id in policy.lexicographic_metric_priority
            ),
            candidate.changed_path_count,
            candidate.change_magnitude,
            candidate.candidate_id,
        ),
    )
    selected = ordered[0]
    records = [
        CandidateRankRecordV02(
            candidate_id=item.candidate_id,
            eligible=True,
            rank=index,
            pareto_front=fronts[item.candidate_id],
            selected=item.candidate_id == selected.candidate_id,
            reason=(
                "Selected after hard-gate, evidence, regression, and meaningful-gain "
                "eligibility by Pareto, lexicographic, then minimum-change ordering."
                if item.candidate_id == selected.candidate_id
                else "Eligible candidate ordered by Pareto, lexicographic, and change cost."
            ),
        )
        for index, item in enumerate(ordered, start=1)
    ]
    records.extend(
        CandidateRankRecordV02(
            candidate_id=item.candidate_id,
            eligible=False,
            rejection_reasons=rejected[item.candidate_id],
            reason="Candidate was removed before Pareto ranking by fail-closed eligibility.",
        )
        for item in sorted(candidates, key=lambda candidate: candidate.candidate_id)
        if rejected[item.candidate_id]
    )
    return CandidateRankingV02(
        ranking_id=ranking_id,
        source_fingerprint=source_fingerprint,
        policy_id=policy.profile_id,
        outcome="selected",
        selected_candidate_id=selected.candidate_id,
        pareto_candidate_ids=sorted(
            item.candidate_id
            for item in eligible
            if fronts[item.candidate_id] == 0
        ),
        records=records,
        producer=producer,
        created_at=created_at,
    )
