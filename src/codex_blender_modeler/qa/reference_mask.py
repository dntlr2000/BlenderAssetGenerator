from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageChops, ImageDraw, ImageOps

from ..blender_artifacts import write_json_atomic
from ..models import EvidenceSpec, ObjectSpec, SceneSpec
from ..reference_scope import subject_object_ids
from ..workspace import sha256_file

if TYPE_CHECKING:
    from ..reference_fidelity.models import FidelityArtifact, ReferenceMaskSeedEvidence


@dataclass(frozen=True)
class EvidenceSeed:
    """Describe one observed semantic box used to seed deterministic mask refinement."""

    group_id: str
    object_id: str
    bbox_norm: tuple[float, float, float, float]
    confidence: float


def validate_explicit_reference_seeds(
    root: Path,
    reference_path: Path,
    spec: SceneSpec,
    evidence: ReferenceMaskSeedEvidence,
    *,
    allowed_object_ids: set[str] | None = None,
) -> list[EvidenceSeed]:
    """Validate local seeds, optional trimap and V0.3 source scope without part-extent changes."""
    from ..reference_fidelity.models import (
        ReferenceMaskSeedEvidenceV02,
        parse_reference_mask_seed_evidence,
    )
    from ..reference_fidelity.service import read_artifact

    evidence = parse_reference_mask_seed_evidence(evidence)
    if evidence.job_id != spec.job_id:
        raise ValueError("segmentation seed evidence belongs to another job")
    read_artifact(root, evidence.reference)
    if (root / evidence.reference.path).resolve() != reference_path.resolve():
        raise ValueError("segmentation seed evidence names another reference path")
    objects = {obj.id: obj for obj in spec.objects}
    reference_ids = {
        source.id for source in spec.sources if source.kind == "reference"
        and (root / source.path).resolve() == reference_path.resolve()
    }
    result = []
    for seed in evidence.seeds:
        obj = objects.get(seed.object_id)
        if obj is None or seed.source_id not in reference_ids:
            raise ValueError("segmentation seed names an unknown object or reference source")
        if allowed_object_ids is not None and obj.id not in allowed_object_ids:
            raise ValueError("segmentation seed escapes the selected subject")
        x0, y0, x1, y1 = seed.bbox_norm
        if not any(
            item.status == "observed" and item.source_id == seed.source_id
            and item.bbox_norm[0] <= x0 and item.bbox_norm[1] <= y0
            and item.bbox_norm[2] >= x1 and item.bbox_norm[3] >= y1
            for item in obj.evidence
        ):
            raise ValueError("segmentation sample is outside observed whole-part bounds")
        result.append(EvidenceSeed(
            group_id=_semantic_group_id(obj.id), object_id=obj.id,
            bbox_norm=seed.bbox_norm, confidence=seed.confidence,
        ))
    if len({seed.group_id for seed in result}) != len(result):
        raise ValueError("explicit segmentation requires one sample per semantic group")
    if isinstance(evidence, ReferenceMaskSeedEvidenceV02):
        from .reference_mask_constraints import validate_reference_trimap

        validate_reference_trimap(
            root, reference_path, spec, evidence, allowed_object_ids=allowed_object_ids
        )
    return sorted(result, key=lambda seed: seed.group_id)


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


def select_reference_evidence_seeds(
    spec: SceneSpec,
    *,
    allowed_object_ids: set[str] | None = None,
) -> list[EvidenceSeed]:
    """Choose one observed seed per group, optionally limited to the selected subject."""

    reference_source_ids = {
        source.id for source in spec.sources if source.kind == "reference"
    }
    grouped: dict[str, list[tuple[ObjectSpec, EvidenceSpec]]] = {}
    for obj in spec.objects:
        if allowed_object_ids is not None and obj.id not in allowed_object_ids:
            continue
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


def _subject_evidence_bbox(
    spec: SceneSpec,
    selected_ids: set[str],
) -> tuple[float, float, float, float] | None:
    """Union observed primary-reference boxes for the immutable subject-only scope."""

    reference_source_ids = {
        source.id for source in spec.sources if source.kind == "reference"
    }
    boxes = [
        evidence.bbox_norm
        for obj in spec.objects
        if obj.id in selected_ids
        for evidence in obj.evidence
        if (
            evidence.status == "observed"
            and evidence.source_id in reference_source_ids
            and evidence.confidence >= 0.5
        )
    ]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _clip_mask_to_normalized_bbox(
    mask: Image.Image,
    bbox_norm: tuple[float, float, float, float],
) -> Image.Image:
    """Remove unrelated reference foreground outside a padded subject evidence box."""

    x0, y0, x1, y1 = bbox_norm
    padding_x = max(0.01, (x1 - x0) * 0.03)
    padding_y = max(0.01, (y1 - y0) * 0.03)
    padded = (
        max(0.0, x0 - padding_x),
        max(0.0, y0 - padding_y),
        min(1.0, x1 + padding_x),
        min(1.0, y1 + padding_y),
    )
    bounds = _pixel_bbox(padded, width=mask.width, height=mask.height)
    clipped = Image.new("L", mask.size, 0)
    clipped.paste(mask.crop(bounds), (bounds[0], bounds[1]))
    return clipped


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


def _closed_exterior_subject(spec: SceneSpec, selected_ids: set[str] | None) -> bool:
    """Require an explicit primary-object closed-exterior tag before filling mask holes."""

    if selected_ids is None:
        return False
    for obj in spec.objects:
        if obj.id not in selected_ids:
            continue
        tags = {str(tag).strip().lower() for tag in obj.tags}
        if (
            "scope:closed_exterior" in tags
            and tags.intersection({"qa_role:primary", "role:primary"})
        ):
            return True
    return False


def _fill_enclosed_holes(mask: Image.Image) -> tuple[Image.Image, int]:
    """Fill only background components disconnected from the mask image border."""

    binary = mask.convert("L").point(lambda value: 255 if value >= 128 else 0)
    exterior = binary.copy()
    width, height = exterior.size
    border_points = (
        [(x, 0) for x in range(width)]
        + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(1, max(1, height - 1))]
        + [(width - 1, y) for y in range(1, max(1, height - 1))]
    )
    for point in border_points:
        if exterior.getpixel(point) == 0:
            ImageDraw.floodfill(exterior, point, 255, thresh=0)
    holes = ImageOps.invert(exterior)
    filled = ImageChops.lighter(binary, holes)
    filled_pixel_count = filled.histogram()[255] - binary.histogram()[255]
    return filled, filled_pixel_count


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
    reference_content_scope: str = "full_reference",
    seed_evidence: ReferenceMaskSeedEvidence | None = None,
    seed_evidence_source: FidelityArtifact | None = None,
) -> tuple[Path, Path]:
    """Freeze masks and optional exact seed-file snapshots; reject unbound partial scope."""
    from ..reference_fidelity.models import (
        ReferenceMaskSeedEvidenceV02,
        ReferenceMaskSeedEvidenceV03,
        parse_reference_mask_seed_evidence,
    )
    from .evidence_selection import SEED_SNAPSHOT_NAME, load_reference_mask_selection
    from .reference_mask_constraints import (
        METHOD,
        SNAPSHOT_NAME,
        refine_reference_trimap,
        validate_reference_trimap,
    )
    from .reference_subject_extent import (
        SNAPSHOT_NAME as EXTENT_SNAPSHOT_NAME,
    )
    from .reference_subject_extent import (
        clip_to_subject_extent,
        normalized_subject_extent,
        validate_reference_subject_extent,
    )

    seed_source_bytes = None
    if seed_evidence_source is not None:
        selected, seed_source_bytes = load_reference_mask_selection(
            root, reference_path, spec, reference_content_scope, seed_evidence_source
        )
        if seed_evidence is None or selected.model_dump() != seed_evidence.model_dump():
            raise ValueError("selected seed file differs from supplied reference mask evidence")
        if (run_dir / SEED_SNAPSHOT_NAME).exists():
            raise FileExistsError("QA run-local seed source snapshot already exists")
    output_path = run_dir / "reference_mask.png"
    manifest_path = run_dir / "reference_mask_manifest.json"
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError("QA run-local reference mask artifacts already exist")
    if seed_evidence is not None:
        seed_evidence = parse_reference_mask_seed_evidence(seed_evidence)
    constrained = isinstance(seed_evidence, ReferenceMaskSeedEvidenceV02)
    extent_bytes = None
    if isinstance(seed_evidence, ReferenceMaskSeedEvidenceV03) and (
        run_dir / EXTENT_SNAPSHOT_NAME
    ).exists():
        raise FileExistsError("QA run-local subject extent snapshot already exists")
    if constrained and (run_dir / SNAPSHOT_NAME).exists():
        raise FileExistsError("QA run-local trimap snapshot already exists")

    with Image.open(reference_path) as opened_reference:
        reference = opened_reference.convert("RGB")
    with Image.open(analysis_mask_path) as opened_mask:
        source_analysis_mask = opened_mask.convert("L")
    analysis_mask = source_analysis_mask
    if analysis_mask.size != reference.size:
        analysis_mask = analysis_mask.resize(reference.size, Image.Resampling.NEAREST)
    analysis_mask = analysis_mask.point(lambda value: 255 if value >= 128 else 0)
    selected_subject_ids: set[str] | None = None
    subject_bbox = None
    if reference_content_scope == "primary_object_only":
        selected_subject_ids = subject_object_ids(spec)
        if not selected_subject_ids:
            raise ValueError(
                "primary_object_only QA requires explicit primary/supporting SceneSpec roles"
            )
        if isinstance(seed_evidence, ReferenceMaskSeedEvidenceV03):
            subject_extent, extent_bytes = validate_reference_subject_extent(
                root, reference_path, spec, seed_evidence, allowed_object_ids=selected_subject_ids
            )
            subject_bbox = normalized_subject_extent(subject_extent)
            analysis_mask = clip_to_subject_extent(analysis_mask, subject_extent)
        else:
            subject_bbox = _subject_evidence_bbox(spec, selected_subject_ids)
            if subject_bbox is None:
                raise ValueError(
                    "primary_object_only QA requires observed subject evidence bounds"
                )
            scoped_mask = _clip_mask_to_normalized_bbox(analysis_mask, subject_bbox)
            reference_sources = {source.id for source in spec.sources if source.kind == "reference"}
            observed_subject_ids = {
                obj.id for obj in spec.objects if obj.id in selected_subject_ids
                and any(entry.status == "observed" and entry.confidence >= 0.5
                        and entry.source_id in reference_sources for entry in obj.evidence)
            }
            removed_pixels = analysis_mask.histogram()[255] - scoped_mask.histogram()[255]
            if observed_subject_ids != selected_subject_ids and removed_pixels > 0:
                # Partial part observations cannot independently justify a smaller subject mask.
                raise ValueError(
                    "reference mask scope is unscorable: observed part bounds cover "
                    f"{len(observed_subject_ids)}/{len(selected_subject_ids)} subject targets "
                    f"and would clip {removed_pixels} source foreground pixels. Independently "
                    "scope-bound full-subject evidence is required; inferred part boxes cannot "
                    "supply that authority. No run mask or report was published."
                )
            analysis_mask = scoped_mask
    elif reference_content_scope != "full_reference":
        raise ValueError("unsupported reference_content_scope for QA")
    seeds = (
        select_reference_evidence_seeds(spec, allowed_object_ids=selected_subject_ids)
        if seed_evidence is None else validate_explicit_reference_seeds(
            root, reference_path, spec, seed_evidence, allowed_object_ids=selected_subject_ids
        )
    )

    method = "analysis_mask_fallback"
    reason = "OpenCV refinement was not attempted"
    selected = analysis_mask
    closed_exterior_fill = not constrained and _closed_exterior_subject(spec, selected_subject_ids)
    filled_hole_pixels = 0
    trimap_bytes = None
    try:
        if constrained:
            from io import BytesIO

            from ..reference_fidelity.service import read_artifact

            trimap, trimap_bytes = validate_reference_trimap(
                root, reference_path, spec, seed_evidence, allowed_object_ids=selected_subject_ids
            )
            reference_bytes = read_artifact(root, seed_evidence.reference)
            with Image.open(BytesIO(reference_bytes)) as exact_reference:
                reference = exact_reference.convert("RGB")
            candidate = refine_reference_trimap(reference, trimap)
        else:
            candidate = _grabcut_refinement(reference, analysis_mask, seeds)
        trustworthy, reason = _mask_is_trustworthy(analysis_mask, candidate, seeds)
        if seed_evidence is not None and not trustworthy:
            raise ValueError(f"explicit reference segmentation failed: {reason}")
        if trustworthy:
            method = METHOD if constrained else "opencv_grabcut_evidence_seeded"
            selected = candidate
    except (RuntimeError, ValueError, OSError) as exc:
        if seed_evidence is not None:
            raise ValueError(
                "explicit reference segmentation cannot use a silent fallback"
            ) from exc
        reason = f"{type(exc).__name__}: {exc}"

    if closed_exterior_fill:
        selected, filled_hole_pixels = _fill_enclosed_holes(selected)
        if filled_hole_pixels:
            method = f"{method}_closed_exterior_hole_fill"
            reason = (
                f"{reason}; filled {filled_hole_pixels} enclosed background pixels under "
                "explicit primary scope:closed_exterior evidence"
            )

    if constrained:
        # Refuse source changes during segmentation before publishing any run mask.
        read_artifact(root, seed_evidence.reference)
        read_artifact(root, seed_evidence.trimap)
        if isinstance(seed_evidence, ReferenceMaskSeedEvidenceV03):
            read_artifact(root, seed_evidence.subject_extent)
            from .reference_subject_extent import validate_recorded_primary_reference

            validate_recorded_primary_reference(root, spec.job_id, seed_evidence.reference)
    if seed_evidence_source is not None:
        _, final_seed_bytes = load_reference_mask_selection(
            root, reference_path, spec, reference_content_scope, seed_evidence_source
        )
        if final_seed_bytes != seed_source_bytes:
            raise ValueError("selected seed source changed before mask publication")
    selected.save(output_path, format="PNG", optimize=False)
    manifest: dict[str, Any] = {
        "schema_version": "0.6.0",
        "method": method,
        "reason": reason,
        "source_mask_path": analysis_mask_path.resolve().relative_to(root.resolve()).as_posix(),
        "source_mask_sha256": sha256_file(analysis_mask_path),
        "source_mask_metrics": _mask_diagnostics(source_analysis_mask),
        "scoped_source_mask_metrics": _mask_diagnostics(analysis_mask),
        "reference_content_scope": reference_content_scope,
        "subject_object_ids": sorted(selected_subject_ids or []),
        "subject_evidence_bbox_norm": (
            list(subject_bbox) if subject_bbox is not None else None
        ),
        "reference_sha256": sha256_file(reference_path),
        "output_path": output_path.name,
        "output_sha256": sha256_file(output_path),
        "output_mask_metrics": _mask_diagnostics(selected),
        "closed_exterior_hole_fill": {
            "authorized": closed_exterior_fill,
            "applied": filled_hole_pixels > 0,
            "filled_pixel_count": filled_hole_pixels,
        },
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
    if seed_evidence is not None:
        from ..blender_artifacts import stable_json_digest

        manifest["seed_evidence"] = seed_evidence.model_dump(mode="json")
        manifest["seed_evidence_sha256"] = stable_json_digest(manifest["seed_evidence"])
    if constrained:
        from ..reference_fidelity.models import FidelityArtifact

        assert trimap_bytes is not None
        snapshot = run_dir / SNAPSHOT_NAME
        with snapshot.open("xb") as stream:
            stream.write(trimap_bytes)
        manifest["trimap_snapshot"] = FidelityArtifact(
            path=snapshot.relative_to(root).as_posix(), sha256=sha256_file(snapshot)
        ).model_dump(mode="json")
    if extent_bytes is not None:
        from ..reference_fidelity.models import FidelityArtifact

        assert isinstance(seed_evidence, ReferenceMaskSeedEvidenceV03)
        extent_snapshot = run_dir / EXTENT_SNAPSHOT_NAME
        with extent_snapshot.open("xb") as stream:
            stream.write(extent_bytes)
        manifest["subject_extent_snapshot"] = FidelityArtifact(
            path=extent_snapshot.relative_to(root).as_posix(),
            sha256=sha256_file(extent_snapshot),
        ).model_dump(mode="json")
    if seed_source_bytes is not None:
        seed_snapshot = run_dir / SEED_SNAPSHOT_NAME
        with seed_snapshot.open("xb") as stream:
            stream.write(seed_source_bytes)
        manifest["seed_evidence_source"] = seed_evidence_source.model_dump(mode="json")
        manifest["seed_evidence_snapshot"] = {
            "path": seed_snapshot.relative_to(root).as_posix(),
            "sha256": sha256_file(seed_snapshot),
        }
    write_json_atomic(manifest_path, manifest)
    return output_path, manifest_path
