"""Host-side isolated Blender materialization for strict structural candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from ..blender_runner import run_blender
from .geometry_intent_runtime_v02 import classify_geometry_intent_v02
from .mesh_payload_io_v02 import (
    CompatibleMeshPayload,
    file_sha256,
    load_compatible_mesh_payload,
    verify_mesh_payload_v02_source_hashes,
)
from .mesh_payload_v02 import (
    MaterialSlotV02,
    MeshPayloadSourceHashV02,
    MeshPayloadV02,
)
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
    mesh_payload_version: Literal["0.1.0", "0.2.0"] = "0.1.0",
    material_id: str | None = None,
) -> CompatibleMeshPayload:
    """Materialize legacy 0.1 by default or an explicit strict MeshPayload 0.2."""

    validated = (
        candidate
        if isinstance(candidate, StructuralGeometryCandidate)
        else StructuralGeometryCandidate.model_validate(candidate)
    )
    if mesh_payload_version == "0.2.0":
        if validated.geometry_intent is None:
            raise ValueError("MeshPayload 0.2 requires explicit GeometryIntent")
        if material_id is None:
            raise ValueError("MeshPayload 0.2 requires one stable material ID")
        MaterialSlotV02(slot_index=0, material_id=material_id)
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
    blender_args = [
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
    ]
    if mesh_payload_version == "0.2.0":
        blender_args.extend(
            [
                "--mesh-payload-version",
                "0.2.0",
                "--material-id",
                str(material_id),
            ]
        )
    run_blender(
        "materialize_structural_geometry.py",
        blender_args,
        factory_startup=True,
        disable_autoexec=True,
    )
    materialized = load_compatible_mesh_payload(mesh_path)
    if mesh_payload_version == "0.1.0" and not isinstance(
        materialized, StructuralMeshPayload
    ):
        raise RuntimeError("legacy structural materialization changed payload version")
    if mesh_payload_version == "0.2.0" and not isinstance(materialized, MeshPayloadV02):
        raise RuntimeError("opt-in structural materialization did not emit MeshPayload 0.2")
    if materialized.semantic_id != validated.semantic_id:
        raise RuntimeError("materialized structural mesh changed its semantic ID")
    if materialized.builder_kind != validated.geometry.kind:
        raise RuntimeError("materialized structural mesh changed its builder kind")
    if isinstance(materialized, MeshPayloadV02):
        materialized.assert_compilable()
        verify_mesh_payload_v02_source_hashes(materialized, job_root=job_root)
        v02_intent = validated.geometry_intent
        if v02_intent is None:
            raise RuntimeError("MeshPayload 0.2 lost its required GeometryIntent")
        expected_source, expected_policy = classify_geometry_intent_v02(
            v02_intent,
            builder_kind=validated.geometry.kind,
        )
        if materialized.source_geometry_intent != expected_source:
            raise RuntimeError("materialized MeshPayload 0.2 changed GeometryIntent")
        if materialized.modifier_materialization_policy != expected_policy:
            raise RuntimeError("materialized MeshPayload 0.2 changed modifier policy")
        expected_slot = MaterialSlotV02(slot_index=0, material_id=str(material_id))
        if materialized.material_slots != [expected_slot] or any(
            index != 0 for index in materialized.polygon_material_indices
        ):
            raise RuntimeError("materialized MeshPayload 0.2 changed material assignment")
        expected_source_hash = MeshPayloadSourceHashV02(
            role="structural_candidate",
            path=candidate_path.relative_to(job_root.resolve()).as_posix(),
            sha256=file_sha256(candidate_path),
        )
        if materialized.source_hashes != [expected_source_hash]:
            raise RuntimeError("materialized MeshPayload 0.2 changed source binding")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("mesh_payload_version") != "0.2.0":
            raise RuntimeError("materialization report omitted MeshPayload 0.2 dispatch")
    return materialized
