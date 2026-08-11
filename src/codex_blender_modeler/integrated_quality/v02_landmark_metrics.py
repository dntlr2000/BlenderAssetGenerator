"""Observed-landmark companion metrics for Integrated Quality 0.2."""

from __future__ import annotations

import math

from .v02_models import LandmarkEvidenceV02, LandmarkMetricV02


def evaluate_landmark_v02(evidence: LandmarkEvidenceV02) -> LandmarkMetricV02:
    """Measure normalized reprojection error or preserve a missing landmark as unscorable."""

    limitations: list[str] = []
    if evidence.source_position_norm is None:
        limitations.append("source landmark is unavailable and must not be invented")
    if evidence.candidate_position_norm is None:
        limitations.append("candidate landmark is absent")
    if limitations:
        return LandmarkMetricV02(
            metric_id=f"landmark.{evidence.landmark_id}.reprojection_v02",
            landmark_id=evidence.landmark_id,
            semantic_id=evidence.semantic_id,
            authority=evidence.authority,
            status="unscorable",
            source_artifact_sha256=evidence.source_artifact_sha256,
            candidate_artifact_sha256=evidence.candidate_artifact_sha256,
            camera_sha256=evidence.camera_sha256,
            confidence=0,
            limitations=limitations,
        )
    assert evidence.source_position_norm is not None
    assert evidence.candidate_position_norm is not None
    error = math.dist(
        evidence.source_position_norm,
        evidence.candidate_position_norm,
    ) / math.sqrt(2)
    limitations = []
    if evidence.authority != "authoritative":
        limitations.append("non-observed landmark evidence is advisory only")
    return LandmarkMetricV02(
        metric_id=f"landmark.{evidence.landmark_id}.reprojection_v02",
        landmark_id=evidence.landmark_id,
        semantic_id=evidence.semantic_id,
        authority=evidence.authority,
        status="scored",
        source_artifact_sha256=evidence.source_artifact_sha256,
        candidate_artifact_sha256=evidence.candidate_artifact_sha256,
        camera_sha256=evidence.camera_sha256,
        reprojection_error_norm=error,
        confidence=evidence.confidence,
        limitations=limitations,
    )
