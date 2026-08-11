"""Actual-Blender multi-view companion metrics for Integrated Quality 0.2."""

from __future__ import annotations

from .v02_models import MultiviewMetricV02, MultiviewObservationV02


def evaluate_multiview_v02(
    observations: list[MultiviewObservationV02],
    *,
    metric_id: str = "structural.multiview_v02",
) -> MultiviewMetricV02:
    """Summarize only actual Blender views and leave provider/generated views advisory."""

    identifiers = [item.view_id for item in observations]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("multiview observation IDs must be unique")
    authoritative = [
        item for item in observations if item.authority == "authoritative"
    ]
    if len(authoritative) < 2:
        return MultiviewMetricV02(
            metric_id=metric_id,
            status="unscorable",
            observations=observations,
            authoritative_view_count=len(authoritative),
            limitations=[
                "at least two exact actual-Blender views are required for multi-view scoring"
            ],
        )
    silhouette_values = [
        item.silhouette_stability for item in authoritative
    ]
    semantic_values = [
        item.semantic_placement_score for item in authoritative
    ]
    if any(value is None for value in silhouette_values + semantic_values):
        raise ValueError("authoritative multiview observations require complete scores")
    return MultiviewMetricV02(
        metric_id=metric_id,
        status="scored",
        observations=observations,
        authoritative_view_count=len(authoritative),
        minimum_silhouette_stability=min(
            value for value in silhouette_values if value is not None
        ),
        mean_semantic_placement_score=(
            sum(value for value in semantic_values if value is not None)
            / len(semantic_values)
        ),
        limitations=(
            ["generated/provider views were excluded from authoritative aggregation"]
            if len(authoritative) != len(observations)
            else []
        ),
    )
