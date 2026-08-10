"""Host-side isolated Blender materialization for strict structural candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..blender_runner import run_blender
from .models import StructuralGeometryCandidate, StructuralMeshPayload


def _resolve_job_path(job_root: Path, relative_path: str) -> Path:
    """Resolve one normalized relative path and reject workspace escape."""

    if not relative_path or "\\" in relative_path or Path(relative_path).is_absolute():
        raise ValueError("structural output paths must be normalized job-relative paths")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("structural output paths must not contain unsafe segments")
    root = job_root.resolve()
    candidate = (root / Path(*parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("structural output path escapes the job workspace") from exc
    return candidate


def _canonical_sha256(value: Any) -> str:
    """Hash one JSON-compatible value with deterministic compact serialization."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def materialize_structural_candidate(
    *,
    job_root: Path,
    candidate: StructuralGeometryCandidate | dict[str, Any],
    candidate_relative_path: str,
    mesh_relative_path: str,
    blend_relative_path: str,
    report_relative_path: str,
) -> StructuralMeshPayload:
    """Validate, persist, and materialize one candidate through a fixed Blender script."""

    validated = (
        candidate
        if isinstance(candidate, StructuralGeometryCandidate)
        else StructuralGeometryCandidate.model_validate(candidate)
    )
    candidate_path = _resolve_job_path(job_root, candidate_relative_path)
    mesh_path = _resolve_job_path(job_root, mesh_relative_path)
    blend_path = _resolve_job_path(job_root, blend_relative_path)
    report_path = _resolve_job_path(job_root, report_relative_path)
    for path in (candidate_path, mesh_path, blend_path, report_path):
        if path.exists():
            raise FileExistsError(f"structural materialization will not overwrite {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
    payload = validated.model_dump(mode="json")
    with candidate_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    run_blender(
        "materialize_structural_geometry.py",
        [
            "--candidate",
            str(candidate_path),
            "--job-root",
            str(job_root.resolve()),
            "--output-mesh",
            str(mesh_path),
            "--output-blend",
            str(blend_path),
            "--report",
            str(report_path),
            "--candidate-sha256",
            _canonical_sha256(payload),
        ],
        factory_startup=True,
        disable_autoexec=True,
    )
    materialized = StructuralMeshPayload.model_validate_json(
        mesh_path.read_text(encoding="utf-8")
    )
    if materialized.semantic_id != validated.semantic_id:
        raise RuntimeError("materialized structural mesh changed its semantic ID")
    if materialized.builder_kind != validated.geometry.kind:
        raise RuntimeError("materialized structural mesh changed its builder kind")
    return materialized
