from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from ..blender_artifacts import write_json_atomic
from ..models import EvidenceSpec, ObjectSpec, SceneSpec
from ..workspace import sha256_file


@dataclass(frozen=True)
class EvidenceSeed:
    """Describe one observed semantic box used to seed deterministic mask refinement."""

    group_id: str
    object_id: str
    bbox_norm: tuple[float, float, float, float]
    confidence: float


def _semantic_group_id(object_id: str) -> str:
    """Derive a stable broad group from a dotted semantic object ID."""

    parts = [part for part in object_id.split(".") if part]
    if len(parts) >= 2 and parts[0] == "island":
        return ".".join(parts[:2])
    return parts[0] if parts else object_id


def _best_reference_evidence(
    obj: ObjectSpec,
    *,
    reference_source_ids: set[str],
) -> EvidenceSpec | None:
    """Select the strongest observed primary-reference evidence for one object."""

    observed = [
        evidence
        for evidence in obj.evidence
        if evidence.status == "observed" and evidence.source_id in reference_source_ids
    ]
    return max(observed, key=lambda evidence: evidence.confidence, default=None)


def select_reference_evidence_seeds(spec: SceneSpec) -> list[EvidenceSeed]:
    """Choose one broad, high-confidence observed seed per semantic asset group."""

    reference_source_ids = {
        source.id for source in spec.sources if source.kind == "reference"
    }
    grouped: dict[str, list[tuple[ObjectSpec, EvidenceSpec]]] = {}
    for obj in spec.objects:
        evidence = _best_reference_evidence(
            obj,
            reference_source_ids=reference_source_ids,
        )
        if evidence is None:
            continue
        grouped.setdefault(_semantic_group_id(obj.id), []).append((obj, evidence))

    seeds: list[EvidenceSeed] = []
    for group_id, candidates in sorted(grouped.items()):
        obj, evidence = max(
            candidates,
            key=lambda item: (
                int("underside" in item[0].id.split(".") or "underside" in item[0].tags),
                int("root" in item[0].id.split(".") or "root" in item[0].tags),
                item[1].confidence,
                -len(item[0].id.split(".")),
                item[0].id,
            ),
        )
        seeds.append(
            EvidenceSeed(
                group_id=group_id,
                object_id=obj.id,
                bbox_norm=evidence.bbox_norm,
                confidence=evidence.confidence,
            )
        )
    return seeds


def _pixel_bbox(
    bbox_norm: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """Convert a normalized min/max evidence box into clipped pixel bounds."""

    x0, y0, x1, y1 = bbox_norm
    left = max(0, min(width - 1, int(x0 * width)))
    top = max(0, min(height - 1, int(y0 * height)))
    right = max(left + 1, min(width, int(round(x1 * width))))
    bottom = max(top + 1, min(height, int(round(y1 * height))))
    return left, top, right, bottom


def _inset_bbox(
    bounds: tuple[int, int, int, int],
    *,
    fraction: float = 0.3,
) -> tuple[int, int, int, int]:
    """Inset an evidence box to form a conservative sure-foreground core."""

    left, top, right, bottom = bounds
    inset_x = min(max(1, int((right - left) * fraction)), max(0, (right - left - 1) // 2))
    inset_y = min(max(1, int((bottom - top) * fraction)), max(0, (bottom - top - 1) // 2))
    return left + inset_x, top + inset_y, right - inset_x, bottom - inset_y


def _grabcut_refinement(
    reference: Image.Image,
    analysis_mask: Image.Image,
    seeds: list[EvidenceSeed],
) -> Image.Image:
    """Run evidence-seeded OpenCV GrabCut and return a binary Pillow mask."""

    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("OpenCV vision extras are unavailable") from exc

    rgb = np.asarray(reference.convert("RGB"), dtype=np.uint8)
    original = np.asarray(analysis_mask.convert("L"), dtype=np.uint8) >= 128
    height, width = original.shape
    grabcut_mask = np.full((height, width), cv2.GC_BGD, dtype=np.uint8)
    grabcut_mask[original] = cv2.GC_PR_FGD

    border = max(1, min(width, height) // 100)
    grabcut_mask[:border, :] = cv2.GC_BGD
    grabcut_mask[-border:, :] = cv2.GC_BGD
    grabcut_mask[:, :border] = cv2.GC_BGD
    grabcut_mask[:, -border:] = cv2.GC_BGD
    for seed in seeds:
        bounds = _pixel_bbox(seed.bbox_norm, width=width, height=height)
        left, top, right, bottom = bounds
        grabcut_mask[top:bottom, left:right] = cv2.GC_PR_FGD
        core_left, core_top, core_right, core_bottom = _inset_bbox(bounds)
        grabcut_mask[core_top:core_bottom, core_left:core_right] = cv2.GC_FGD

    if not seeds:
        raise RuntimeError("SceneSpec contains no observed primary-reference evidence seeds")
    cv2.setRNGSeed(0)
    background_model = np.zeros((1, 65), dtype=np.float64)
    foreground_model = np.zeros((1, 65), dtype=np.float64)
    cv2.grabCut(
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        grabcut_mask,
        None,
        background_model,
        foreground_model,
        5,
        cv2.GC_INIT_WITH_MASK,
    )
    foreground = np.isin(grabcut_mask, (cv2.GC_FGD, cv2.GC_PR_FGD))
    return Image.fromarray(foreground.astype(np.uint8) * 255)


def _mask_is_trustworthy(
    original: Image.Image,
    refined: Image.Image,
    seeds: list[EvidenceSeed],
) -> tuple[bool, str]:
    """Reject empty, explosive, destructive, or seed-dropping refinements."""

    if refined.size != original.size:
        return False, "refined mask resolution changed"
    original_binary = original.convert("L").point(lambda value: 255 if value >= 128 else 0)
    refined_binary = refined.convert("L").point(lambda value: 255 if value >= 128 else 0)
    original_area = original_binary.histogram()[255]
    refined_area = refined_binary.histogram()[255]
    total_area = original_binary.width * original_binary.height
    if original_area == 0 or refined_area == 0:
        return False, "source or refined mask has no foreground"
    if refined_area > original_area * 1.02:
        return False, "refined foreground unexpectedly expanded"
    if refined_area < original_area * 0.10:
        return False, "refined foreground discarded more than 90 percent of the source mask"
    if refined_area > total_area * 0.92:
        return False, "refined foreground still covers nearly the entire image"

    width, height = refined_binary.size
    for seed in seeds:
        left, top, right, bottom = _inset_bbox(
            _pixel_bbox(seed.bbox_norm, width=width, height=height)
        )
        core_area = max(1, (right - left) * (bottom - top))
        retained = refined_binary.crop((left, top, right, bottom)).histogram()[255]
        if retained / core_area < 0.20:
            return False, f"refinement dropped semantic seed {seed.object_id}"
    return True, "evidence-seeded GrabCut passed trust checks"


def _mask_diagnostics(mask: Image.Image) -> dict[str, Any]:
    """Summarize binary foreground coverage and bounds for mask provenance."""

    binary = mask.convert("L").point(lambda value: 255 if value >= 128 else 0)
    foreground = binary.histogram()[255]
    total = binary.width * binary.height
    bounds = binary.getbbox()
    bbox_norm = None
    if bounds is not None:
        left, top, right, bottom = bounds
        bbox_norm = [
            round(left / binary.width, 8),
            round(top / binary.height, 8),
            round(right / binary.width, 8),
            round(bottom / binary.height, 8),
        ]
    return {
        "foreground_fraction": round(foreground / total, 8) if total else 0.0,
        "bbox_norm": bbox_norm,
    }


def prepare_run_reference_mask(
    *,
    root: Path,
    run_dir: Path,
    reference_path: Path,
    analysis_mask_path: Path,
    spec: SceneSpec,
) -> tuple[Path, Path]:
    """Write one immutable run-local refined mask and its provenance manifest."""

    output_path = run_dir / "reference_mask.png"
    manifest_path = run_dir / "reference_mask_manifest.json"
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("QA run-local reference mask artifacts already exist")

    with Image.open(reference_path) as opened_reference:
        reference = opened_reference.convert("RGB")
    with Image.open(analysis_mask_path) as opened_mask:
        analysis_mask = opened_mask.convert("L")
    if analysis_mask.size != reference.size:
        analysis_mask = analysis_mask.resize(reference.size, Image.Resampling.NEAREST)
    analysis_mask = analysis_mask.point(lambda value: 255 if value >= 128 else 0)
    seeds = select_reference_evidence_seeds(spec)

    method = "analysis_mask_fallback"
    reason = "OpenCV refinement was not attempted"
    selected = analysis_mask
    try:
        candidate = _grabcut_refinement(reference, analysis_mask, seeds)
        trustworthy, reason = _mask_is_trustworthy(analysis_mask, candidate, seeds)
        if trustworthy:
            method = "opencv_grabcut_evidence_seeded"
            selected = candidate
    except (RuntimeError, ValueError, OSError) as exc:
        reason = f"{type(exc).__name__}: {exc}"

    selected.save(output_path, format="PNG", optimize=False)
    manifest: dict[str, Any] = {
        "schema_version": "0.6.0",
        "method": method,
        "reason": reason,
        "source_mask_path": analysis_mask_path.resolve().relative_to(root.resolve()).as_posix(),
        "source_mask_sha256": sha256_file(analysis_mask_path),
        "source_mask_metrics": _mask_diagnostics(analysis_mask),
        "reference_sha256": sha256_file(reference_path),
        "output_path": output_path.name,
        "output_sha256": sha256_file(output_path),
        "output_mask_metrics": _mask_diagnostics(selected),
        "seed_count": len(seeds),
        "seeds": [
            {
                "group_id": seed.group_id,
                "object_id": seed.object_id,
                "bbox_norm": list(seed.bbox_norm),
                "confidence": seed.confidence,
            }
            for seed in seeds
        ],
    }
    write_json_atomic(manifest_path, manifest)
    return output_path, manifest_path
