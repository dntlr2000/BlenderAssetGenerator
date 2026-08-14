"""Prepare non-promoted Standard UV-compatible SceneSpec candidates in immutable history."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from .models import SceneSpec
from .standard_custom_mesh import StandardCustomMeshPayload


class StandardCustomMeshCandidateError(RuntimeError):
    """Report a stale, broadened, escaped, or already-written candidate request."""


def _sha256_file(path: Path) -> str:
    """Hash one exact candidate source or output without normalizing its bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained_file(root: Path, path: Path, label: str) -> Path:
    """Resolve one existing candidate dependency inside its owning job root."""

    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise StandardCustomMeshCandidateError(f"{label} escapes the job root") from exc
    if not resolved.is_file():
        raise StandardCustomMeshCandidateError(f"{label} does not exist: {resolved}")
    return resolved


def _history_output_dir(root: Path, output_dir: Path) -> Path:
    """Contain all prepared candidate outputs below immutable revision-plan history."""

    resolved = output_dir.expanduser().resolve()
    allowed = (root / "history" / "geometry_revision_plans").resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise StandardCustomMeshCandidateError(
            "candidate output must remain below history/geometry_revision_plans"
        ) from exc
    return resolved


def _write_new_json(path: Path, payload: dict[str, object]) -> None:
    """Create one immutable candidate artifact and reject any existing destination."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def prepare_standard_uv_candidate(
    *,
    job_root: Path,
    job_id: str,
    base_scene_spec_path: Path,
    expected_base_scene_spec_sha256: str,
    mesh_payload_path: Path,
    expected_mesh_payload_sha256: str,
    target_object_id: str,
    uniform_scale: float,
    output_dir: Path,
) -> dict[str, object]:
    """Freeze one payload-transport plus uniform-scale candidate without promotion."""

    root = job_root.expanduser().resolve()
    if not root.is_dir() or root.name != job_id:
        raise StandardCustomMeshCandidateError("job root identity differs from job_id")
    if (
        isinstance(uniform_scale, bool)
        or not isinstance(uniform_scale, (int, float))
        or not math.isfinite(float(uniform_scale))
        or float(uniform_scale) <= 0.0
    ):
        raise StandardCustomMeshCandidateError("uniform_scale must be finite and positive")
    base_path = _contained_file(root, base_scene_spec_path, "base SceneSpec")
    payload_path = _contained_file(root, mesh_payload_path, "Standard mesh payload")
    if _sha256_file(base_path) != expected_base_scene_spec_sha256:
        raise StandardCustomMeshCandidateError("base SceneSpec hash is stale")
    if _sha256_file(payload_path) != expected_mesh_payload_sha256:
        raise StandardCustomMeshCandidateError("Standard mesh payload hash is stale")
    try:
        base_raw = json.loads(base_path.read_text(encoding="utf-8"))
        payload_raw = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StandardCustomMeshCandidateError("candidate source JSON is invalid") from exc
    base = SceneSpec.model_validate(base_raw)
    payload = StandardCustomMeshPayload.model_validate(payload_raw)
    if base.job_id != job_id or payload.job_id != job_id:
        raise StandardCustomMeshCandidateError("candidate source job identity is stale")
    matches = [item for item in base_raw["objects"] if item.get("id") == target_object_id]
    if len(matches) != 1 or payload.object_id != target_object_id:
        raise StandardCustomMeshCandidateError("candidate target identity is stale")
    source_geometry = matches[0].get("geometry")
    payload_data = payload.model_dump(mode="json")
    if (
        not isinstance(source_geometry, dict)
        or source_geometry.get("kind") != "custom_mesh"
        or source_geometry.get("path") is not None
        or source_geometry.get("vertices") != payload_data["vertices"]
        or source_geometry.get("faces") != payload_data["faces"]
        or matches[0].get("transform", {}).get("scale") != [1.0, 1.0, 1.0]
    ):
        raise StandardCustomMeshCandidateError(
            "candidate source topology or baseline scale is incompatible"
        )

    candidate = copy.deepcopy(base_raw)
    target = next(
        item for item in candidate["objects"] if item.get("id") == target_object_id
    )
    relative_payload = payload_path.relative_to(root).as_posix()
    target["geometry"] = {
        "kind": "custom_mesh",
        "vertices": None,
        "faces": None,
        "path": relative_payload,
        "format": "mesh_json",
        "recalculate_normals": bool(source_geometry.get("recalculate_normals", True)),
    }
    scale = float(uniform_scale)
    target["transform"]["scale"] = [scale, scale, scale]
    SceneSpec.model_validate(candidate)

    destination = _history_output_dir(root, output_dir)
    scene_path = destination / "scene_spec.json"
    receipt_path = destination / "candidate_compile_receipt.json"
    if scene_path.exists() or receipt_path.exists():
        raise StandardCustomMeshCandidateError("candidate outputs are immutable")
    _write_new_json(scene_path, candidate)
    scene_sha256 = _sha256_file(scene_path)
    receipt: dict[str, object] = {
        "schema_version": "standard-uv-candidate-compile-receipt-0.1.0",
        "job_id": job_id,
        "target_object_id": target_object_id,
        "status": "prepared_not_promoted",
        "canonical_write_performed": False,
        "base_scene_spec_path": base_path.relative_to(root).as_posix(),
        "base_scene_spec_sha256": expected_base_scene_spec_sha256,
        "mesh_payload_path": relative_payload,
        "mesh_payload_sha256": expected_mesh_payload_sha256,
        "candidate_scene_spec_path": scene_path.relative_to(root).as_posix(),
        "candidate_scene_spec_sha256": scene_sha256,
        "changes": [
            {
                "path": ["objects", target_object_id, "geometry"],
                "operation": "inline_to_exact_standard_payload_transport",
            },
            {
                "path": ["objects", target_object_id, "transform", "scale"],
                "before": [1.0, 1.0, 1.0],
                "after": [scale, scale, scale],
            },
        ],
    }
    _write_new_json(receipt_path, receipt)
    return receipt
