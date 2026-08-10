"""Lexicographic and Pareto candidate ranking without a synthetic weighted score."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from .models import (
    CandidateRanking,
    CandidateRankRecord,
    ProducerIdentity,
    QualityProvenance,
    RankableQualityCandidate,
)

_GATE_ORDER = {"passed": 0, "unscorable": 1, "failed": 2}


def _dominates(
    left: RankableQualityCandidate,
    right: RankableQualityCandidate,
) -> bool:
    """Return whether left is at least as good on every gain axis and better on one."""

    axes = set(left.gains) | set(right.gains)
    left_values = [left.gains.get(axis, float("-inf")) for axis in axes]
    right_values = [right.gains.get(axis, float("-inf")) for axis in axes]
    return all(a >= b for a, b in zip(left_values, right_values, strict=True)) and any(
        a > b for a, b in zip(left_values, right_values, strict=True)
    )


def _pareto_fronts(
    candidates: list[RankableQualityCandidate],
) -> dict[str, int]:
    """Assign zero-based Pareto fronts within one lexicographically equal candidate group."""

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
        for candidate in current:
            fronts[candidate.candidate_id] = front_index
            del remaining[candidate.candidate_id]
        front_index += 1
    return fronts


def rank_quality_candidates(
    candidates: list[RankableQualityCandidate],
    *,
    ranking_id: str,
    provenance: QualityProvenance,
    producer: ProducerIdentity,
    created_at: datetime,
) -> CandidateRanking:
    """Rank by gates, regressions, meaningful gain, Pareto front, then minimum change."""

    if not candidates:
        raise ValueError("candidate ranking requires at least one candidate")
    identifiers = [item.candidate_id for item in candidates]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("candidate ranking input IDs must be unique")
    grouped: dict[tuple[int, int, bool], list[RankableQualityCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[
            (
                _GATE_ORDER[candidate.gate_status],
                len(candidate.critical_regressions),
                not candidate.meaningful_gain,
            )
        ].append(candidate)
    pareto: dict[str, int] = {}
    for group in grouped.values():
        pareto.update(_pareto_fronts(group))
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            _GATE_ORDER[candidate.gate_status],
            len(candidate.critical_regressions),
            not candidate.meaningful_gain,
            pareto[candidate.candidate_id],
            candidate.changed_path_count,
            candidate.change_magnitude,
            candidate.candidate_id,
        ),
    )
    selected = ordered[0]
    best_prefix = (
        _GATE_ORDER[selected.gate_status],
        len(selected.critical_regressions),
        not selected.meaningful_gain,
    )
    pareto_ids = sorted(
        item.candidate_id
        for item in candidates
        if (
            _GATE_ORDER[item.gate_status],
            len(item.critical_regressions),
            not item.meaningful_gain,
        )
        == best_prefix
        and pareto[item.candidate_id] == 0
    )
    records = [
        CandidateRankRecord(
            candidate_id=item.candidate_id,
            rank=index,
            pareto_front=pareto[item.candidate_id],
            selected=item.candidate_id == selected.candidate_id,
            reason=(
                "Selected by hard-gate status, critical-regression count, meaningful gain, "
                "Pareto dominance, and minimum-change tie-break."
                if item.candidate_id == selected.candidate_id
                else "Ordered by the immutable lexicographic/Pareto policy."
            ),
        )
        for index, item in enumerate(ordered, start=1)
    ]
    return CandidateRanking(
        schema_version="0.1.0",
        ranking_id=ranking_id,
        job_id=provenance.job_id,
        workflow_id=provenance.workflow_id,
        dispatch_id=provenance.dispatch_id,
        input_sha256=provenance.input_sha256,
        source_fingerprint=provenance.source_fingerprint,
        provenance=provenance,
        created_at=created_at,
        producer=producer,
        selected_candidate_id=selected.candidate_id,
        pareto_candidate_ids=pareto_ids,
        records=records,
    )
