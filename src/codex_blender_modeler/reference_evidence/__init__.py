"""Autonomous Quality 0.1.0 reference-evidence public API."""

from .camera_hypotheses import build_camera_hypothesis_set
from .models import (
    CameraHypothesis,
    CameraHypothesisSet,
    ForegroundMaskCandidate,
    ForegroundMaskMetrics,
    ReferenceEvidence,
    ReferenceEvidenceRunResult,
)
from .segmentation import generate_foreground_mask_candidates
from .service import (
    AdvisoryReferenceProvider,
    load_camera_hypothesis_set,
    load_reference_evidence,
    run_reference_evidence,
)

__all__ = [
    "AdvisoryReferenceProvider",
    "CameraHypothesis",
    "CameraHypothesisSet",
    "ForegroundMaskCandidate",
    "ForegroundMaskMetrics",
    "ReferenceEvidence",
    "ReferenceEvidenceRunResult",
    "build_camera_hypothesis_set",
    "generate_foreground_mask_candidates",
    "load_camera_hypothesis_set",
    "load_reference_evidence",
    "run_reference_evidence",
]
