"""Explicit exact-hash migration evidence for legacy mesh payloads to v0.2."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime

from .mesh_payload_io_v02 import (
    CompatibleMeshPayload,
    LegacyVertexUvMeshPayload,
    file_sha256,
    load_compatible_mesh_payload,
    load_mesh_payload_v02,
    verify_mesh_payload_v02_source_hashes,
)
from .mesh_payload_v02 import (
    JobRelativePath,
    MeshPayloadV02,
    MeshPayloadV02StrictModel,
    Sha256,
    StableId,
    canonical_json_sha256,
)
from .models import StructuralMeshPayload

_MIGRATION_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class MeshPayloadV02MigrationPlan(MeshPayloadV02StrictModel):
    """Bind one legacy source and fully authored v2 candidate before explicit apply."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    migration_id: StableId
    source_path: JobRelativePath
    source_schema_version: Literal["unversioned", "0.1.0"]
    source_file_sha256: Sha256
    source_canonical_sha256: Sha256
    candidate_path: JobRelativePath
    candidate_file_sha256: Sha256
    candidate_canonical_sha256: Sha256
    evidence_status: Literal["exact_available_evidence", "candidate_supplied_gaps"]
    verified_fields: list[str]
    limitations: list[str]
    canonical_mutation_allowed: Literal[False] = False
    created_at: AwareDatetime


class MeshPayloadV02MigrationReceipt(MeshPayloadV02StrictModel):
    """Prove one exact-plan application published only a derived v2 payload copy."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    migration_id: StableId
    plan_path: JobRelativePath
    plan_file_sha256: Sha256
    source_path: JobRelativePath
    source_file_sha256: Sha256
    candidate_path: JobRelativePath
    candidate_file_sha256: Sha256
    derived_payload_path: JobRelativePath
    derived_payload_file_sha256: Sha256
    evidence_status: Literal["exact_available_evidence", "candidate_supplied_gaps"]
    limitations: list[str]
    canonical_mutation_allowed: Literal[False] = False
    applied: Literal[True] = True
    created_at: AwareDatetime


def _resolve_job_path(job_root: Path, relative_path: str) -> Path:
    """Resolve one normalized job-relative path and reject workspace escape."""

    if not relative_path or "\\" in relative_path or Path(relative_path).is_absolute():
        raise ValueError("migration paths must be normalized job-relative paths")
    if any(part in {"", ".", ".."} for part in relative_path.split("/")):
        raise ValueError("migration path contains an unsafe segment")
    root = job_root.resolve()
    path = (root / Path(*relative_path.split("/"))).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("migration path escapes job root") from exc
    return path


def _relative(job_root: Path, path: Path) -> str:
    """Return one normalized path relative to the verified owning job root."""

    return path.resolve().relative_to(job_root.resolve()).as_posix()


def _flatten_legacy_uvs(source: CompatibleMeshPayload) -> list[tuple[float, float]] | None:
    """Expand either legacy UV dialect into polygon-loop order when evidence exists."""

    if isinstance(source, StructuralMeshPayload):
        if source.loop_uvs is None:
            return None
        return [uv for face_uvs in source.loop_uvs for uv in face_uvs]
    if isinstance(source, LegacyVertexUvMeshPayload):
        if source.vertex_uvs is None:
            return None
        return [source.vertex_uvs[index] for face in source.faces for index in face]
    raise TypeError("migration source must be legacy MeshPayload 0.1 or unversioned")


def _compare_source_candidate(
    source: CompatibleMeshPayload,
    candidate: MeshPayloadV02,
) -> tuple[str, list[str], list[str]]:
    """Compare every legacy field that can be proven and disclose unavailable evidence."""

    if isinstance(source, MeshPayloadV02):
        raise ValueError("MeshPayload 0.2 does not require a legacy migration")
    if list(source.vertices) != list(candidate.vertices):
        raise ValueError("migration candidate vertices differ from legacy source")
    if source.faces != candidate.faces:
        raise ValueError("migration candidate faces differ from legacy source")
    verified = ["vertices", "faces"]
    limitations: list[str] = []
    if isinstance(source, StructuralMeshPayload):
        if source.semantic_id != candidate.semantic_id:
            raise ValueError("migration candidate semantic_id differs from source")
        if source.builder_kind != candidate.builder_kind:
            raise ValueError("migration candidate builder_kind differs from source")
        verified.extend(["semantic_id", "builder_kind"])
        if source.geometry_intent is None:
            limitations.append("legacy_source_geometry_intent_unavailable")
        else:
            limitations.append("legacy_geometry_intent_requires_v02_normalization_review")
    else:
        limitations.extend(
            [
                "unversioned_source_has_no_semantic_id",
                "unversioned_source_has_no_builder_kind",
                "unversioned_source_has_no_geometry_intent",
            ]
        )
    source_uvs = _flatten_legacy_uvs(source)
    if source_uvs is None:
        limitations.append("legacy_source_uvs_unavailable")
    elif source_uvs != candidate.loop_uvs:
        raise ValueError("migration candidate loop UVs differ from legacy source")
    else:
        verified.append("loop_uvs")
    limitations.extend(
        [
            "legacy_source_material_slots_unavailable",
            "legacy_source_polygon_smoothing_snapshot_unavailable",
            "legacy_source_custom_attribute_snapshot_unavailable",
        ]
    )
    status = "exact_available_evidence" if not limitations else "candidate_supplied_gaps"
    return status, verified, limitations


def _write_json_exclusive(path: Path, value: object) -> None:
    """Write deterministic UTF-8 JSON without overwriting an existing artifact."""

    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def plan_mesh_payload_v02_migration(
    *,
    job_root: Path,
    migration_id: str,
    source_relative_path: str,
    candidate_relative_path: str,
) -> dict[str, object]:
    """Publish an immutable migration plan without modifying either payload or canonical data."""

    if not _MIGRATION_ID.fullmatch(migration_id):
        raise ValueError("migration_id must match [a-z0-9][a-z0-9_-]{0,63}")
    source_path = _resolve_job_path(job_root, source_relative_path)
    candidate_path = _resolve_job_path(job_root, candidate_relative_path)
    if not source_path.is_file() or not candidate_path.is_file():
        raise FileNotFoundError("migration source and candidate must already exist")
    source = load_compatible_mesh_payload(source_path)
    candidate = load_mesh_payload_v02(candidate_path)
    candidate.assert_compilable()
    verify_mesh_payload_v02_source_hashes(candidate, job_root=job_root)
    source_binding = [
        item
        for item in candidate.source_hashes
        if item.role == "source_mesh_payload" and item.path == source_relative_path
    ]
    if len(source_binding) != 1 or source_binding[0].sha256 != file_sha256(source_path):
        raise ValueError("v2 candidate is not hash-bound to the exact legacy source file")
    status, verified, limitations = _compare_source_candidate(source, candidate)
    run_root = _resolve_job_path(
        job_root,
        f"structural_migrations/mesh_payload_v02/{migration_id}",
    )
    if run_root.exists():
        raise FileExistsError(f"mesh payload migration already exists: {migration_id}")
    source_payload = source.model_dump(mode="json")
    plan = MeshPayloadV02MigrationPlan(
        schema_version="0.1.0",
        migration_id=migration_id,
        source_path=source_relative_path,
        source_schema_version=(
            "0.1.0" if isinstance(source, StructuralMeshPayload) else "unversioned"
        ),
        source_file_sha256=file_sha256(source_path),
        source_canonical_sha256=canonical_json_sha256(source_payload),
        candidate_path=candidate_relative_path,
        candidate_file_sha256=file_sha256(candidate_path),
        candidate_canonical_sha256=canonical_json_sha256(candidate),
        evidence_status=status,
        verified_fields=verified,
        limitations=limitations,
        canonical_mutation_allowed=False,
        created_at=datetime.now(UTC),
    )
    staging = run_root.parent / f".m-{uuid4().hex[:12]}"
    try:
        _write_json_exclusive(staging / "migration_plan.json", plan)
        run_root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(run_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    plan_path = run_root / "migration_plan.json"
    return {
        "status": "awaiting_exact_plan_hash",
        "migration_id": migration_id,
        "plan_path": _relative(job_root, plan_path),
        "plan_file_sha256": file_sha256(plan_path),
        "evidence_status": status,
        "limitations": limitations,
        "canonical_mutated": False,
    }


def apply_mesh_payload_v02_migration(
    *,
    job_root: Path,
    migration_id: str,
    exact_plan_sha256: str,
) -> dict[str, object]:
    """Apply one exact immutable plan by publishing only a derived v2 copy and receipt."""

    if not re.fullmatch(r"[0-9a-f]{64}", exact_plan_sha256):
        raise ValueError("exact_plan_sha256 must be a lowercase SHA-256")
    run_root = _resolve_job_path(
        job_root,
        f"structural_migrations/mesh_payload_v02/{migration_id}",
    )
    plan_path = run_root / "migration_plan.json"
    applied_root = run_root / "applied"
    if not plan_path.is_file():
        raise FileNotFoundError(plan_path)
    if applied_root.exists():
        raise FileExistsError("mesh payload migration plan has already been applied")
    if file_sha256(plan_path) != exact_plan_sha256:
        raise ValueError("exact migration plan SHA-256 does not match")
    plan = MeshPayloadV02MigrationPlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
    source_path = _resolve_job_path(job_root, plan.source_path)
    candidate_path = _resolve_job_path(job_root, plan.candidate_path)
    if file_sha256(source_path) != plan.source_file_sha256:
        raise ValueError("legacy source changed after migration planning")
    if file_sha256(candidate_path) != plan.candidate_file_sha256:
        raise ValueError("v2 candidate changed after migration planning")
    source = load_compatible_mesh_payload(source_path)
    candidate = load_mesh_payload_v02(candidate_path)
    candidate.assert_compilable()
    verify_mesh_payload_v02_source_hashes(candidate, job_root=job_root)
    if canonical_json_sha256(source.model_dump(mode="json")) != plan.source_canonical_sha256:
        raise ValueError("legacy source canonical representation changed")
    if canonical_json_sha256(candidate) != plan.candidate_canonical_sha256:
        raise ValueError("v2 candidate canonical representation changed")
    status, verified, limitations = _compare_source_candidate(source, candidate)
    if (
        status != plan.evidence_status
        or verified != plan.verified_fields
        or limitations != plan.limitations
    ):
        raise ValueError("migration compatibility result differs from immutable plan")

    staging = run_root / f".a-{uuid4().hex[:12]}"
    try:
        derived_path = staging / "mesh_payload_v02.derived.json"
        _write_json_exclusive(derived_path, candidate)
        final_derived = applied_root / "mesh_payload_v02.derived.json"
        receipt = MeshPayloadV02MigrationReceipt(
            schema_version="0.1.0",
            migration_id=migration_id,
            plan_path=_relative(job_root, plan_path),
            plan_file_sha256=exact_plan_sha256,
            source_path=plan.source_path,
            source_file_sha256=plan.source_file_sha256,
            candidate_path=plan.candidate_path,
            candidate_file_sha256=plan.candidate_file_sha256,
            derived_payload_path=_relative(job_root, final_derived),
            derived_payload_file_sha256=file_sha256(derived_path),
            evidence_status=status,
            limitations=limitations,
            canonical_mutation_allowed=False,
            applied=True,
            created_at=datetime.now(UTC),
        )
        _write_json_exclusive(staging / "migration_receipt.json", receipt)
        staging.rename(applied_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    receipt_path = applied_root / "migration_receipt.json"
    return {
        "status": "derived_payload_applied",
        "migration_id": migration_id,
        "derived_payload_path": _relative(
            job_root, applied_root / "mesh_payload_v02.derived.json"
        ),
        "receipt_path": _relative(job_root, receipt_path),
        "receipt_file_sha256": file_sha256(receipt_path),
        "evidence_status": status,
        "limitations": limitations,
        "canonical_mutated": False,
    }
