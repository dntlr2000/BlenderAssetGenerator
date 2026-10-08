"""Opt-in reference-only trimap validation and bounded deterministic segmentation."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from ..models import SceneSpec
    from ..reference_fidelity.models import ReferenceMaskSeedEvidenceV02

METHOD = "opencv_grabcut_evidence_seeded_trimap_v02"
SNAPSHOT_NAME = "reference_trimap.png"


def validate_reference_trimap(
    root: Path,
    reference_path: Path,
    spec: SceneSpec,
    evidence: ReferenceMaskSeedEvidenceV02,
    *,
    allowed_object_ids: set[str] | None,
) -> tuple[Image.Image, bytes]:
    """Validate exact labels against legacy observed bounds or independent V0.3 source scope."""
    from ..reference_fidelity.service import read_artifact
    from .reference_mask import _inset_bbox, _pixel_bbox

    if evidence.job_id != spec.job_id:
        raise ValueError("trimap evidence belongs to another job")
    reference_bytes = read_artifact(root, evidence.reference)
    if (root / evidence.reference.path).resolve() != reference_path.resolve():
        raise ValueError("trimap evidence names another reference path")
    scope = "full_reference" if allowed_object_ids is None else "primary_object_only"
    if evidence.reference_content_scope != scope or evidence.subject_object_ids != sorted(
        allowed_object_ids or []
    ):
        raise ValueError("trimap content scope or subject membership changed")
    raw = read_artifact(root, evidence.trimap)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("trimap PNG exceeds the bounded byte budget")
    with Image.open(BytesIO(reference_bytes)) as reference:
        if reference.size != evidence.reference_resolution:
            raise ValueError("trimap reference resolution changed")
    with Image.open(BytesIO(raw)) as opened:
        if (
            opened.format != "PNG" or opened.mode != "L"
            or opened.size != evidence.reference_resolution
            or getattr(opened, "n_frames", 1) != 1
        ):
            raise ValueError("trimap must be a single grayscale PNG at exact reference resolution")
        trimap = opened.copy()
    histogram = trimap.histogram()
    labels = {index for index, count in enumerate(histogram) if count}
    if not labels <= {0, 85, 170, 255} or not {0, 255} <= labels:
        raise ValueError("trimap has unknown labels or lacks sure foreground/background")
    for observation in evidence.label_observations:
        bounds = _pixel_bbox(
            observation.bbox_norm, width=trimap.width, height=trimap.height
        )
        expected = 255 if observation.label == "foreground" else 0
        if trimap.crop(bounds).getextrema() != (expected, expected):
            raise ValueError("trimap pixels contradict an observed label region")
    for seed in evidence.seeds:
        core = _inset_bbox(_pixel_bbox(seed.bbox_norm, width=trimap.width, height=trimap.height))
        if trimap.crop(core).getextrema() != (255, 255):
            raise ValueError("trimap contradicts an exact foreground seed core")
    if allowed_object_ids is not None:
        from ..reference_fidelity.models import ReferenceMaskSeedEvidenceV03
        from .reference_mask import _clip_mask_to_normalized_bbox, _subject_evidence_bbox
        from .reference_subject_extent import (
            clip_to_subject_extent,
            validate_reference_subject_extent,
        )

        foreground = trimap.point(lambda value: 255 if value in {170, 255} else 0)
        if isinstance(evidence, ReferenceMaskSeedEvidenceV03):
            extent, _raw = validate_reference_subject_extent(
                root, reference_path, spec, evidence, allowed_object_ids=allowed_object_ids
            )
            scoped_foreground = clip_to_subject_extent(foreground, extent)
        else:
            bbox = _subject_evidence_bbox(spec, allowed_object_ids)
            if bbox is None:
                raise ValueError("trimap subject has no observed reference extent")
            scoped_foreground = _clip_mask_to_normalized_bbox(foreground, bbox)
        if scoped_foreground.tobytes() != foreground.tobytes():
            raise ValueError("trimap foreground escapes the observed subject extent")
    return trimap, raw


def refine_reference_trimap(reference: Image.Image, trimap: Image.Image) -> Image.Image:
    """Run only five seeded GrabCut iterations while retaining every sure reference label."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("OpenCV vision extras are unavailable") from exc

    if reference.size != trimap.size:
        raise ValueError("trimap and reference dimensions differ")
    labels = np.asarray(trimap, dtype=np.uint8)
    gc = np.zeros(labels.shape, dtype=np.uint8)
    for value, target in ((0, cv2.GC_BGD), (85, cv2.GC_PR_BGD),
                          (170, cv2.GC_PR_FGD), (255, cv2.GC_FGD)):
        gc[labels == value] = target
    cv2.setRNGSeed(0)
    cv2.grabCut(
        cv2.cvtColor(np.asarray(reference.convert("RGB")), cv2.COLOR_RGB2BGR), gc, None,
        np.zeros((1, 65), dtype=np.float64), np.zeros((1, 65), dtype=np.float64),
        5, cv2.GC_INIT_WITH_MASK,
    )
    foreground = np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD))
    if np.any(foreground[labels == 0]) or not np.all(foreground[labels == 255]):
        raise ValueError("segmentation violated sure reference labels")
    return Image.fromarray(foreground.astype(np.uint8) * 255)


def validate_trimap_manifest(root, directory, manifest, evidence) -> None:
    """Reject missing, mixed or changed run-local trimap snapshots and algorithm selection."""
    from ..reference_fidelity.models import FidelityArtifact
    from ..reference_fidelity.service import read_artifact

    snapshot = FidelityArtifact(
        path=(directory / SNAPSHOT_NAME).relative_to(root).as_posix(),
        sha256=evidence.trimap.sha256,
    )
    if (
        manifest.get("method") != METHOD
        or manifest.get("trimap_snapshot") != snapshot.model_dump(mode="json")
        or manifest.get("closed_exterior_hole_fill") != {
            "authorized": False, "applied": False, "filled_pixel_count": 0,
        }
    ):
        raise ValueError("reference trimap manifest differs from its selected companion")
    read_artifact(root, snapshot)
