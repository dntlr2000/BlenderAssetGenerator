"""Alternative camera hypotheses derived without mutating canonical camera evidence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .models import (
    CameraEvidenceCue,
    CameraHypothesis,
    CameraHypothesisSet,
    CameraIntrinsics,
    CameraPoseHypothesis,
    EvidenceProvenance,
    ReferenceEvidence,
)


def _line_orientation_dispersion(image_path: Path) -> tuple[float | None, str]:
    """Estimate optional OpenCV line-angle dispersion as a weak projection cue."""

    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, "pillow"
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    lines = cv2.HoughLinesP(
        cv2.Canny(gray, 60, 160),
        1,
        np.pi / 180.0,
        threshold=40,
        minLineLength=max(12, min(gray.shape) // 10),
        maxLineGap=8,
    )
    if lines is None or len(lines) < 3:
        return None, "opencv"
    angles: list[float] = []
    for line in lines[:64]:
        x0, y0, x1, y1 = (float(value) for value in line[0])
        angle = float(np.degrees(np.arctan2(y1 - y0, x1 - x0))) % 180.0
        angles.append(min(angle, 180.0 - angle))
    if not angles:
        return None, "opencv"
    dispersion = min(1.0, float(np.std(np.asarray(angles))) / 45.0)
    return round(dispersion, 6), "opencv"


def _pillow_edge_density(image_path: Path) -> float:
    """Calculate a deterministic edge-density cue when OpenCV is absent or inconclusive."""

    with Image.open(image_path) as opened:
        gray = ImageOps.grayscale(opened)
        gray.thumbnail((384, 384), Image.Resampling.LANCZOS)
    edges = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES))
    threshold = max(24.0, ImageStat.Stat(edges).mean[0] * 1.35)
    pixels = list(edges.getdata())
    if not pixels:
        return 0.0
    return round(sum(value >= threshold for value in pixels) / len(pixels), 6)


def build_camera_hypothesis_set(
    evidence: ReferenceEvidence,
    image_path: Path,
    *,
    reference_evidence_path: str,
    reference_evidence_sha256: str,
    input_sha256: str,
    created_at: datetime,
) -> CameraHypothesisSet:
    """Build perspective and orthographic staging alternatives from bounded image cues."""

    selected = next(
        item
        for item in evidence.mask_candidates
        if item.candidate_id == evidence.selected_candidate_id
    )
    dispersion, line_provider = _line_orientation_dispersion(image_path)
    edge_density = _pillow_edge_density(image_path)
    cues = [
        CameraEvidenceCue(
            cue_id="cue-silhouette-symmetry",
            cue_type="silhouette_symmetry",
            supports=(
                "orthographic"
                if selected.metrics.bilateral_symmetry >= 0.78
                else "ambiguous"
            ),
            strength=selected.metrics.bilateral_symmetry,
            description=(
                "Bilateral foreground symmetry is compatible with a centered or orthographic "
                "view, but does not prove projection type."
            ),
            source_artifact_ids=[selected.artifact.artifact_id],
        ),
        CameraEvidenceCue(
            cue_id="cue-projection-ambiguity",
            cue_type="projection_ambiguity",
            supports="ambiguous",
            strength=round(max(0.25, 1.0 - selected.metrics.confidence), 6),
            description=(
                "A single uncalibrated image does not uniquely determine camera intrinsics, "
                "distance, or projection."
            ),
            source_artifact_ids=[evidence.source_image.artifact_id],
        ),
    ]
    if dispersion is not None:
        cues.append(
            CameraEvidenceCue(
                cue_id="cue-line-orientation",
                cue_type="line_orientation",
                supports="perspective" if dispersion >= 0.42 else "orthographic",
                strength=dispersion if dispersion >= 0.42 else 1.0 - dispersion,
                description=(
                    "Bounded line-orientation dispersion is a weak projection cue and is not a "
                    "vanishing-point calibration."
                ),
                source_artifact_ids=[evidence.source_image.artifact_id],
            )
        )
    else:
        cues.append(
            CameraEvidenceCue(
                cue_id="cue-line-orientation",
                cue_type="line_orientation",
                supports="ambiguous",
                strength=min(1.0, edge_density * 3.0),
                description=(
                    "No stable bounded line grouping was available; Pillow edge density remains "
                    "non-directional evidence only."
                ),
                source_artifact_ids=[evidence.source_image.artifact_id],
            )
        )

    perspective_strength = max(
        (item.strength for item in cues if item.supports == "perspective"),
        default=0.32,
    )
    orthographic_strength = max(
        (item.strength for item in cues if item.supports == "orthographic"),
        default=0.32,
    )
    hypotheses = [
        CameraHypothesis(
            hypothesis_id="camera-perspective-50mm",
            rank=1,
            projection="perspective",
            intrinsics=CameraIntrinsics(
                focal_length_mm=50.0,
                sensor_width_mm=36.0,
            ),
            pose=CameraPoseHypothesis(
                azimuth_deg=35.0,
                elevation_deg=25.0,
                roll_deg=0.0,
                distance_scale=3.0,
            ),
            confidence=round(min(0.75, 0.25 + perspective_strength * 0.45), 6),
            evidence_cue_ids=["cue-line-orientation", "cue-projection-ambiguity"],
            assumptions=["A neutral 50 mm staging lens is used, not recovered calibration."],
            underconstrained=[
                "absolute_camera_distance",
                "principal_point",
                "scene_scale",
                "hidden_depth",
            ],
        ),
        CameraHypothesis(
            hypothesis_id="camera-orthographic",
            rank=2,
            projection="orthographic",
            intrinsics=CameraIntrinsics(ortho_scale_normalized=1.15),
            pose=CameraPoseHypothesis(
                azimuth_deg=35.0,
                elevation_deg=25.0,
                roll_deg=0.0,
            ),
            confidence=round(min(0.75, 0.25 + orthographic_strength * 0.45), 6),
            evidence_cue_ids=["cue-silhouette-symmetry", "cue-projection-ambiguity"],
            assumptions=["Normalized orthographic scale is a staging value only."],
            underconstrained=["ortho_scale", "scene_scale", "hidden_depth"],
        ),
    ]
    hypotheses.sort(key=lambda item: (-item.confidence, item.hypothesis_id))
    hypotheses = [
        item.model_copy(update={"rank": index})
        for index, item in enumerate(hypotheses, 1)
    ]
    ambiguity = (
        "underconstrained"
        if evidence.status in {"underconstrained", "unscorable"}
        else "ambiguous"
    )
    provider = "mixed" if line_provider == "opencv" else "pillow"
    return CameraHypothesisSet(
        schema_version="0.1.0",
        hypothesis_set_id=f"{evidence.run_id}-camera-set",
        run_id=evidence.run_id,
        job_id=evidence.job_id,
        workflow_id=evidence.workflow_id,
        dispatch_id=evidence.dispatch_id,
        input_sha256=input_sha256,
        source_fingerprint=evidence.source_fingerprint,
        reference_evidence_path=reference_evidence_path,
        reference_evidence_sha256=reference_evidence_sha256,
        evidence_cues=cues,
        hypotheses=hypotheses,
        staging_hypothesis_id=hypotheses[0].hypothesis_id,
        projection_ambiguity=ambiguity,
        ambiguity_reasons=[
            "Single-view projection and pose are not uniquely recoverable.",
            "Hypotheses are staging candidates and do not modify camera_solution.json.",
        ],
        canonical_camera_mutated=False,
        canonical_promotion_allowed=False,
        provenance=EvidenceProvenance(
            producer="codex_blender_modeler.reference_evidence.camera_hypotheses",
            producer_version="0.1.0",
            provider=provider,
            method="bounded_projection_alternatives_v1",
            deterministic=True,
            parameters={"maximum_hypotheses": 2, "line_provider": line_provider},
        ),
        created_at=created_at,
    )
