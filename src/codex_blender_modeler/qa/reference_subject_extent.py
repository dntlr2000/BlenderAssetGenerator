"""Exact source-alpha subject scope for opt-in V0.3 reference-mask evidence."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from ..models import SceneSpec
from ..reference_fidelity.models import (
    FidelityArtifact,
    ReferenceMaskSeedEvidenceV03,
    ReferenceSubjectExtentEvidenceV01,
)
from ..reference_scope import subject_object_ids

SNAPSHOT_NAME = "reference_subject_extent.json"


def validate_recorded_primary_reference(
    root: Path, job_id: str, reference: FidelityArtifact
) -> None:
    """Bind opt-in source masks to recorded job input bytes and exact relocation rules."""

    from ..production.validation import ensure_contained_production_path
    from ..workspace import resolve_job_input_path

    metadata_path = ensure_contained_production_path(root, root / "job.json", must_exist=True)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    sources = [item for item in metadata.get("sources", []) if item.get("kind") == "reference"]
    if (
        metadata.get("job_id") != job_id or len(sources) != 1
        or metadata.get("reference_content_scope", "full_reference") != "primary_object_only"
        or sources[0].get("sha256") != reference.sha256
        or metadata.get("reference_sha256", reference.sha256) != reference.sha256
    ):
        raise ValueError("subject extent differs from recorded immutable job reference/scope")
    original = resolve_job_input_path(root, sources[0]["path"], sources[0]["sha256"])
    selected = ensure_contained_production_path(root, root / reference.path, must_exist=True)
    if selected != original or not selected.is_relative_to((root / "input").resolve()):
        raise ValueError("subject extent must bind the recorded immutable job input reference")


def validate_reference_subject_extent(
    root: Path,
    reference_path: Path,
    spec: SceneSpec,
    evidence: ReferenceMaskSeedEvidenceV03,
    *,
    allowed_object_ids: set[str] | None,
) -> tuple[ReferenceSubjectExtentEvidenceV01, bytes]:
    """Recompute source-alpha bounds/count and reject foreign, stale or rendered provenance."""

    from ..reference_fidelity.service import read_artifact

    evidence = ReferenceMaskSeedEvidenceV03.model_validate_json(evidence.model_dump_json())
    raw = read_artifact(root, evidence.subject_extent)
    if len(raw) > 65536:
        raise ValueError("subject extent JSON exceeds the bounded byte budget")
    extent = ReferenceSubjectExtentEvidenceV01.model_validate_json(raw)
    if extent.job_id != spec.job_id or evidence.job_id != spec.job_id:
        raise ValueError("subject extent belongs to another job")
    if extent.reference != evidence.reference:
        raise ValueError("subject extent reference binding differs from mask evidence")
    if (root / extent.reference.path).resolve() != reference_path.resolve():
        raise ValueError("subject extent names another original reference path")
    if (
        allowed_object_ids is None
        or allowed_object_ids != subject_object_ids(spec)
        or extent.subject_object_ids != sorted(allowed_object_ids)
        or evidence.subject_object_ids != extent.subject_object_ids
        or evidence.reference_content_scope != extent.reference_content_scope
    ):
        raise ValueError("subject extent content scope or subject membership changed")
    if extent.reference_resolution != evidence.reference_resolution:
        raise ValueError("subject extent reference resolution differs from mask evidence")
    if not any(
        source.kind == "reference"
        and source.immutable
        and (root / source.path).resolve() == reference_path.resolve()
        for source in spec.sources
    ):
        raise ValueError("subject extent must use an immutable original SceneSpec reference")
    reference_bytes = read_artifact(root, extent.reference)
    validate_recorded_primary_reference(root, spec.job_id, extent.reference)
    with Image.open(BytesIO(reference_bytes)) as opened:
        if getattr(opened, "n_frames", 1) != 1:
            raise ValueError("subject extent requires a single-frame static original reference")
        if opened.size != extent.reference_resolution or opened.mode != "RGBA":
            raise ValueError(
                "subject extent requires exact source resolution and original RGBA alpha"
            )
        alpha = opened.getchannel("A")
        support = alpha.point(lambda value: 255 if value > 0 else 0)
    if support.getextrema() != (0, 255):
        raise ValueError("subject alpha evidence needs visible support and transparent exterior")
    if support.getbbox() != extent.bbox_pixels:
        raise ValueError("subject extent differs from exact original-reference alpha bounds")
    if support.histogram()[255] != extent.foreground_pixel_count:
        raise ValueError("subject extent alpha support count differs from original reference")
    return extent, raw


def clip_to_subject_extent(
    mask: Image.Image, extent: ReferenceSubjectExtentEvidenceV01
) -> Image.Image:
    """Clip to the exact source-pixel ROI without inferred bounds, padding or render pixels."""

    if mask.size != extent.reference_resolution:
        raise ValueError("subject extent and source-mask resolutions differ")
    clipped = Image.new("L", mask.size, 0)
    clipped.paste(mask.crop(extent.bbox_pixels), extent.bbox_pixels[:2])
    return clipped


def normalized_subject_extent(extent: ReferenceSubjectExtentEvidenceV01) -> tuple[float, ...]:
    """Project exact exclusive pixel bounds into diagnostic normalized coordinates."""

    width, height = extent.reference_resolution
    return tuple(
        value / size
        for value, size in zip(extent.bbox_pixels, (width, height, width, height), strict=True)
    )


def validate_subject_extent_manifest(
    root: Path,
    directory: Path,
    manifest: dict,
    evidence: ReferenceMaskSeedEvidenceV03,
) -> None:
    """Bind a run-owned extent snapshot and ROI to the exact declared source companion."""

    from ..reference_fidelity.service import read_artifact

    evidence = ReferenceMaskSeedEvidenceV03.model_validate_json(evidence.model_dump_json())
    source = read_artifact(root, evidence.subject_extent)
    extent = ReferenceSubjectExtentEvidenceV01.model_validate_json(source)
    if (
        extent.reference != evidence.reference
        or extent.subject_object_ids != evidence.subject_object_ids
        or extent.reference_resolution != evidence.reference_resolution
    ):
        raise ValueError("subject extent snapshot source binding differs from mask evidence")
    read_artifact(root, extent.reference)
    validate_recorded_primary_reference(root, evidence.job_id, extent.reference)
    snapshot = FidelityArtifact(
        path=(directory / SNAPSHOT_NAME).relative_to(root).as_posix(),
        sha256=evidence.subject_extent.sha256,
    )
    if (
        manifest.get("subject_extent_snapshot") != snapshot.model_dump(mode="json")
        or manifest.get("subject_evidence_bbox_norm") != list(normalized_subject_extent(extent))
        or manifest.get("subject_object_ids") != extent.subject_object_ids
        or manifest.get("reference_content_scope") != extent.reference_content_scope
    ):
        raise ValueError("subject extent manifest differs from its exact source companion")
    if read_artifact(root, snapshot) != source:
        raise ValueError("subject extent snapshot differs from exact source bytes")
