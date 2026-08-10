"""Duplicate, plateau, and bounded oscillation detection for autonomy states."""

from __future__ import annotations

from dataclasses import dataclass

from .models import StateFingerprint


@dataclass(frozen=True)
class CycleFinding:
    """Describe one detected state-cycle pattern and the involved indices."""

    kind: str
    indices: tuple[int, ...]
    reason: str


def detect_state_cycle(history: list[StateFingerprint]) -> CycleFinding | None:
    """Detect duplicate, A-B-A, A-B-C-B, or metric-direction oscillation patterns."""

    if len(history) < 2:
        return None
    current = history[-1]
    for index, previous in enumerate(history[:-1]):
        if previous.scene_spec_sha256 == current.scene_spec_sha256:
            return CycleFinding(
                "duplicate_candidate_state",
                (index, len(history) - 1),
                "The exact SceneSpec candidate state was already evaluated.",
            )
    if len(history) >= 3:
        first, middle, last = history[-3:]
        if _normalized_state_equal(first, last) and not _normalized_state_equal(
            first, middle
        ):
            return CycleFinding(
                "oscillation_detected",
                (len(history) - 3, len(history) - 2, len(history) - 1),
                "Normalized quality state followed an A-B-A pattern.",
            )
    if len(history) >= 4:
        first, second, third, fourth = history[-4:]
        if _normalized_state_equal(second, fourth) and not _normalized_state_equal(
            first, second
        ) and not _normalized_state_equal(second, third):
            return CycleFinding(
                "oscillation_detected",
                tuple(range(len(history) - 4, len(history))),
                "Normalized quality state followed an A-B-C-B pattern.",
            )
    if len(history) >= 3:
        directions = [item.change_direction for item in history[-3:]]
        metrics = [item.normalized_metric_vector_sha256 for item in history[-3:]]
        if directions[0] and directions[0] == directions[1] == directions[2] and len(
            set(metrics)
        ) <= 2:
            return CycleFinding(
                "oscillation_detected",
                tuple(range(len(history) - 3, len(history))),
                "The same change direction repeated without a distinct metric state.",
            )
    return None


def _normalized_state_equal(left: StateFingerprint, right: StateFingerprint) -> bool:
    """Compare metric and change direction without requiring identical SceneSpec bytes."""

    return (
        left.normalized_metric_vector_sha256
        == right.normalized_metric_vector_sha256
        and left.change_direction == right.change_direction
    )

