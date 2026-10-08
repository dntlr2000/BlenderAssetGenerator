"""Explicit exact-file V0.2/V0.3 mask selection for public QA and Standard continuations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..models import SceneSpec
from ..reference_fidelity.models import (
    FidelityArtifact,
    ReferenceMaskSeedEvidenceV02,
    ReferenceMaskSeedEvidenceV03,
)
from ..reference_fidelity.service import read_artifact
from ..reference_scope import subject_object_ids
from .reference_mask import validate_explicit_reference_seeds
from .reference_subject_extent import validate_recorded_primary_reference

SEED_SNAPSHOT_NAME = "reference_mask_seed_evidence.json"


def selection_artifact(path: str | None, sha256: str | None) -> FidelityArtifact | None:
    """Require both exact selection values, preserving complete absence as legacy behavior."""

    if path is None and sha256 is None:
        return None
    if not isinstance(path, str) or not isinstance(sha256, str):
        raise ValueError("reference mask seed selection requires both path and SHA-256")
    return FidelityArtifact(path=path, sha256=sha256)


def load_reference_mask_selection(
    root: Path,
    reference_path: Path,
    spec: SceneSpec,
    reference_content_scope: str,
    artifact: FidelityArtifact,
) -> tuple[ReferenceMaskSeedEvidenceV02 | ReferenceMaskSeedEvidenceV03, bytes]:
    """Rehash an explicit V0.2 trimap or V0.3 extent against recorded source-only evidence."""

    raw = read_artifact(root, artifact)
    if len(raw) > 1048576 or hashlib.sha256(raw).hexdigest() != artifact.sha256:
        raise ValueError("reference mask seed selection bytes changed or exceed byte budget")
    payload = json.loads(raw)
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if version == "0.2.0":
        evidence = ReferenceMaskSeedEvidenceV02.model_validate_json(raw)
    elif version == "0.3.0":
        evidence = ReferenceMaskSeedEvidenceV03.model_validate_json(raw)
    else:
        raise ValueError("public reference mask selection requires explicit V0.2 or V0.3")
    validate_recorded_primary_reference(root, spec.job_id, evidence.reference)
    if reference_content_scope != evidence.reference_content_scope:
        raise ValueError("reference mask seed selection differs from immutable job scope")
    validate_explicit_reference_seeds(
        root, reference_path, spec, evidence, allowed_object_ids=subject_object_ids(spec)
    )
    return evidence, raw
