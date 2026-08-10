"""Run-owned public SceneSpec 0.2 to 0.3 migration evidence service."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..models import SceneSpec
from ..workspace import job_dir
from .migration import (
    SceneSpecV03MigrationPlan,
    SceneSpecV03MigrationReceipt,
    apply_v03_migration_plan,
    canonical_json_sha256,
    create_v03_migration_plan,
)
from .models import SceneSpecV03

_MIGRATION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 of one exact file representation."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_migration_id(migration_id: str) -> str:
    """Reject identifiers that could escape or alias a run-owned migration directory."""

    if not _MIGRATION_ID_PATTERN.fullmatch(migration_id):
        raise ValueError(
            "migration_id must match [a-z0-9][a-z0-9_-]{0,63}"
        )
    return migration_id


def _validate_sha256(value: str, *, label: str) -> str:
    """Require one lowercase exact SHA-256 approval binding."""

    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase 64-character SHA-256")
    return value


def _write_json(path: Path, payload: object) -> None:
    """Write deterministic UTF-8 JSON into a not-yet-published staging path."""

    if hasattr(payload, "model_dump"):
        value = payload.model_dump(mode="json")  # type: ignore[union-attr]
    else:
        value = payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _job_relative(root: Path, path: Path) -> str:
    """Return one normalized job-relative path after containment verification."""

    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError("migration artifact path escapes its owning job")
    return resolved_path.relative_to(resolved_root).as_posix()


def _migration_paths(job_id: str, migration_id: str) -> tuple[Path, Path, Path]:
    """Resolve canonical source and run-owned migration paths for one job."""

    safe_id = _validate_migration_id(migration_id)
    root = job_dir(job_id)
    source_path = root / "analysis" / "scene_spec.json"
    run_root = root / "structural_migrations" / safe_id
    return root, source_path, run_root


def plan_scene_spec_v03_migration(job_id: str, migration_id: str) -> dict:
    """Publish an immutable derived migration plan and candidate from SceneSpec 0.2."""

    root, source_path, run_root = _migration_paths(job_id, migration_id)
    if not source_path.is_file():
        raise FileNotFoundError(f"canonical SceneSpec does not exist: {source_path}")
    _job_relative(root, source_path)
    if run_root.exists():
        raise FileExistsError(f"migration run already exists: {migration_id}")

    source = SceneSpec.model_validate_json(source_path.read_text(encoding="utf-8"))
    plan, candidate = create_v03_migration_plan(source)
    staging = run_root.parent / f".m-{uuid4().hex[:12]}"
    try:
        plan_path = staging / "migration_plan.json"
        candidate_path = staging / "scene_spec_v03.candidate.json"
        _write_json(candidate_path, candidate)
        plan = plan.model_copy(
            update={
                "source_file_sha256": _sha256_file(source_path),
                "candidate_file_sha256": _sha256_file(candidate_path),
            }
        )
        _write_json(plan_path, plan)
        run_root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(run_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    published_plan = run_root / "migration_plan.json"
    published_candidate = run_root / "scene_spec_v03.candidate.json"
    return {
        "job_id": job_id,
        "migration_id": migration_id,
        "status": "awaiting_exact_plan_hash",
        "canonical_source_mutated": False,
        "source_path": _job_relative(root, source_path),
        "source_file_sha256": _sha256_file(source_path),
        "migration_plan_path": _job_relative(root, published_plan),
        "migration_plan_sha256": _sha256_file(published_plan),
        "candidate_path": _job_relative(root, published_candidate),
        "candidate_file_sha256": _sha256_file(published_candidate),
        "plan": plan.model_dump(mode="json"),
    }


def apply_scene_spec_v03_migration(
    job_id: str,
    migration_id: str,
    *,
    exact_plan_sha256: str,
) -> dict:
    """Validate an exact plan and publish only a derived accepted 0.3 copy and receipt."""

    root, source_path, run_root = _migration_paths(job_id, migration_id)
    expected_plan_hash = _validate_sha256(
        exact_plan_sha256,
        label="exact_plan_sha256",
    )
    plan_path = run_root / "migration_plan.json"
    candidate_path = run_root / "scene_spec_v03.candidate.json"
    applied_root = run_root / "applied"
    if not source_path.is_file() or not plan_path.is_file() or not candidate_path.is_file():
        raise FileNotFoundError("migration source, plan, or candidate is missing")
    _job_relative(root, source_path)
    _job_relative(root, plan_path)
    _job_relative(root, candidate_path)
    if applied_root.exists():
        raise FileExistsError("migration plan has already been applied")
    current_plan_hash = _sha256_file(plan_path)
    if current_plan_hash != expected_plan_hash:
        raise ValueError("exact migration plan SHA-256 does not match")

    source = SceneSpec.model_validate_json(source_path.read_text(encoding="utf-8"))
    plan = SceneSpecV03MigrationPlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    )
    if plan.source_file_sha256 != _sha256_file(source_path):
        raise ValueError("SceneSpec 0.2 source file no longer matches the migration plan")
    if plan.candidate_file_sha256 != _sha256_file(candidate_path):
        raise ValueError("SceneSpec 0.3 candidate file no longer matches the migration plan")
    candidate = SceneSpecV03.model_validate_json(
        candidate_path.read_text(encoding="utf-8")
    )
    accepted = apply_v03_migration_plan(source, candidate, plan)

    staging = run_root / f".a-{uuid4().hex[:12]}"
    try:
        derived_path = staging / "scene_spec_v03.derived.json"
        _write_json(derived_path, accepted)
        final_derived_path = applied_root / "scene_spec_v03.derived.json"
        receipt = SceneSpecV03MigrationReceipt(
            migration_id=migration_id,
            source_path=_job_relative(root, source_path),
            source_file_sha256=_sha256_file(source_path),
            source_canonical_sha256=canonical_json_sha256(
                source.model_dump(mode="json")
            ),
            migration_plan_path=_job_relative(root, plan_path),
            migration_plan_file_sha256=current_plan_hash,
            candidate_path=_job_relative(root, candidate_path),
            candidate_file_sha256=_sha256_file(candidate_path),
            candidate_canonical_sha256=canonical_json_sha256(
                candidate.model_dump(mode="json")
            ),
            derived_scene_spec_path=_job_relative(root, final_derived_path),
            derived_scene_spec_file_sha256=_sha256_file(derived_path),
            created_at=datetime.now(UTC),
        )
        _write_json(staging / "migration_receipt.json", receipt)
        staging.rename(applied_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    published_receipt = applied_root / "migration_receipt.json"
    return {
        "job_id": job_id,
        "migration_id": migration_id,
        "status": "derived_candidate_applied",
        "canonical_source_mutated": False,
        "derived_scene_spec_path": _job_relative(
            root, applied_root / "scene_spec_v03.derived.json"
        ),
        "migration_receipt_path": _job_relative(root, published_receipt),
        "migration_receipt_sha256": _sha256_file(published_receipt),
        "receipt": receipt.model_dump(mode="json"),
    }
