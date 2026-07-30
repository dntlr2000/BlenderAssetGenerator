from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import get_settings
from .reference_scope import normalize_reference_content_scope
from .versioning import PROJECT_VERSION

JOB_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
NEW_JOB_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RESERVED_JOB_IDS = {
    "floating_island",
    "geometry_showcase",
    "measured_box",
    "first_reference_test",
    "portable_prop",
    "portable_environment",
    "portable_materials",
    "lod_collider_showcase",
    "portable_invalid",
}
SUBDIRS = [
    "input",
    "analysis",
    "analysis/diagnostics",
    "analysis/masks",
    "analysis/materials",
    "materials",
    "history",
    "history/input",
    "geometry",
    "constraints",
    "blender",
    "renders",
    "renders/materials",
    "renders/qa",
    "reports",
    "exports",
    "exports/packages",
    "exports/destination_handoffs",
    "textures",
    "bakes",
    "asset_profiles",
    "optimization",
    "optimization/runs",
    "optimized",
    "qa",
    "qa/runs",
    "qa/convergence",
    "qa/interior",
    "qa/interior/runs",
    "qa/cache/generated_targets",
    "workflows",
    "handoffs",
]
SOURCE_KINDS = {"reference", "front", "right", "top", "blueprint", "cad"}
SOURCE_ORDER = {"reference": 0, "front": 1, "right": 2, "top": 3, "blueprint": 4, "cad": 5}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def validate_job_id(job_id: str) -> str:
    """Validate an existing job path, preserving v0.2 mixed-case compatibility."""

    if not JOB_RE.fullmatch(job_id):
        raise ValueError("job_id must match [a-zA-Z0-9][a-zA-Z0-9_-]{0,63}")
    return job_id


def validate_new_job_id(job_id: str) -> str:
    """Require collision-safe lowercase IDs for newly created jobs."""

    if not NEW_JOB_RE.fullmatch(job_id):
        raise ValueError("new job_id must match [a-z0-9][a-z0-9_-]{0,63}")
    if job_id in RESERVED_JOB_IDS:
        raise ValueError(f"job_id is reserved for a bundled example: {job_id}")
    return job_id


def job_dir(job_id: str) -> Path:
    validate_job_id(job_id)
    return get_settings().workspace_root / job_id


def _create_subdirs(root: Path) -> None:
    for subdir in SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)


def ensure_job_dirs(job_id: str) -> Path:
    root = job_dir(job_id)
    _create_subdirs(root)
    return root


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(get_settings().repo_root))
    except ValueError:
        return str(resolved)


def resolve_metadata_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (get_settings().repo_root / candidate).resolve()


def _validate_source(kind: str, source_path: Path) -> tuple[Path, str]:
    if kind not in SOURCE_KINDS:
        raise ValueError(f"Unsupported source kind: {kind}")
    source = source_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower() or ".png"
    if kind != "cad" and suffix not in IMAGE_EXTENSIONS:
        raise ValueError(f"Source kind {kind} requires a supported image file: {source}")
    return source, suffix


def _copy_source(
    temp_root: Path,
    final_root: Path,
    kind: str,
    source_path: Path,
) -> dict[str, str]:
    source, suffix = _validate_source(kind, source_path)
    temp_target = temp_root / "input" / f"{kind}{suffix}"
    final_target = final_root / "input" / f"{kind}{suffix}"
    if temp_target.exists():
        raise FileExistsError(f"Duplicate source kind in one job: {kind}")
    shutil.copy2(source, temp_target)
    return {
        "kind": kind,
        "path": metadata_path(final_target),
        "sha256": sha256_file(temp_target),
    }


def create_job(
    job_id: str,
    image: Path,
    mode: str,
    scale_anchors: list[str],
    additional_views: dict[str, Path] | None = None,
    *,
    reference_content_scope: str = "full_reference",
    target_subject: str | None = None,
) -> dict[str, Any]:
    """Atomically create an isolated job with one immutable modeling-content scope."""

    validate_new_job_id(job_id)
    if mode not in {"concept", "measured"}:
        raise ValueError("mode must be concept or measured")
    resolved_content_scope, resolved_target = normalize_reference_content_scope(
        reference_content_scope,
        target_subject,
    )
    workspace = get_settings().workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    root = workspace / job_id
    if root.exists():
        raise FileExistsError(
            f"Job already exists and was not modified: {root}. Use a new job_id for a new "
            "asset, or use the revision workflow for the existing asset."
        )

    temp_root = workspace / f".{job_id}.creating-{uuid4().hex}"
    _create_subdirs(temp_root)
    try:
        sources = [_copy_source(temp_root, root, "reference", image)]
        for kind, source_path in sorted(
            (additional_views or {}).items(), key=lambda item: SOURCE_ORDER.get(item[0], 999)
        ):
            if kind == "reference":
                raise ValueError("Use the primary --image argument for the reference source")
            sources.append(_copy_source(temp_root, root, kind, source_path))

        metadata = {
            "job_id": job_id,
            "mode": mode,
            "project_version_created": PROJECT_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "reference_path": sources[0]["path"],
            "reference_sha256": sources[0]["sha256"],
            "sources": sources,
            "scale_anchors": scale_anchors,
            "reference_content_scope": resolved_content_scope,
            "target_subject": resolved_target,
        }
        (temp_root / "job.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temp_root, root)
        return metadata
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def load_job(job_id: str) -> dict[str, Any]:
    path = job_dir(job_id) / "job.json"
    if not path.is_file():
        raise FileNotFoundError(f"Job does not exist: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def add_job_view(
    job_id: str,
    kind: str,
    source_path: Path,
    *,
    replace: bool = False,
    scale_anchors: list[str] | None = None,
) -> dict[str, Any]:
    """Add one view without recreating or partially overwriting the job."""

    if kind == "reference":
        raise ValueError("The immutable primary reference cannot be replaced with add_job_view")
    root = job_dir(job_id)
    metadata = load_job(job_id)
    source, suffix = _validate_source(kind, source_path)
    existing_records = [record for record in metadata.get("sources", []) if record["kind"] == kind]
    existing_files = list((root / "input").glob(f"{kind}.*"))
    if (existing_records or existing_files) and not replace:
        raise FileExistsError(
            f"View kind {kind!r} already exists for {job_id}; pass replace=True explicitly"
        )

    temp_target = root / "input" / f".{kind}.{uuid4().hex}{suffix}"
    shutil.copy2(source, temp_target)
    new_hash = sha256_file(temp_target)
    final_target = root / "input" / f"{kind}{suffix}"

    archived: list[str] = []
    if existing_files:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        for old in existing_files:
            archive = root / "history" / "input" / f"{stamp}_{old.name}"
            archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(archive))
            archived.append(metadata_path(archive))
    os.replace(temp_target, final_target)

    records = [record for record in metadata.get("sources", []) if record["kind"] != kind]
    records.append({"kind": kind, "path": metadata_path(final_target), "sha256": new_hash})
    records.sort(key=lambda item: SOURCE_ORDER.get(item["kind"], 999))
    metadata["sources"] = records
    metadata["updated_at"] = datetime.now(UTC).isoformat()
    if scale_anchors:
        metadata.setdefault("scale_anchors", []).extend(scale_anchors)
    job_json = root / "job.json"
    temp_json = root / ".job.json.tmp"
    temp_json.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temp_json, job_json)
    return {
        "job_id": job_id,
        "kind": kind,
        "path": metadata_path(final_target),
        "sha256": new_hash,
        "archived": archived,
    }


def find_input_assets(job_id: str) -> list[Path]:
    metadata = load_job(job_id)
    candidates: list[Path] = []
    for record in metadata.get("sources", []):
        path = resolve_metadata_path(record["path"])
        if path.is_file():
            candidates.append(path)
    if not candidates:
        input_dir = job_dir(job_id) / "input"
        candidates = [path for path in input_dir.iterdir() if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No input assets for job {job_id}")
    return sorted(candidates, key=lambda path: (SOURCE_ORDER.get(path.stem, 999), path.name))


def find_input_images(job_id: str) -> list[Path]:
    candidates = [
        path for path in find_input_assets(job_id) if path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not candidates:
        raise FileNotFoundError(f"No Codex-compatible image input for job {job_id}")
    return candidates


def find_reference(job_id: str) -> Path:
    metadata = load_job(job_id)
    reference = next(
        (
            resolve_metadata_path(item["path"])
            for item in metadata["sources"]
            if item["kind"] == "reference"
        ),
        None,
    )
    if reference is None or not reference.is_file():
        raise FileNotFoundError(f"Primary reference is missing for job {job_id}")
    return reference


def archive_scene_spec(job_id: str) -> Path | None:
    """Copy the current SceneSpec into timestamped history without replacing it."""

    root = job_dir(job_id)
    current = root / "analysis" / "scene_spec.json"
    if not current.exists():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    target = root / "history" / f"{stamp}_scene_spec.json"
    shutil.copy2(current, target)
    return target


def _require_scene_spec_lock_owner(
    root: Path,
    job_id: str,
    lock_owner_id: str,
) -> None:
    """Require the current process to own the exact shared job writer lock."""

    from .orchestration.models import WorkflowLock

    lock_path = root / "workflows" / ".lock.json"
    if not lock_path.is_file():
        raise RuntimeError(
            "Canonical SceneSpec replacement requires the shared job write lock"
        )
    try:
        lock = WorkflowLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Canonical SceneSpec replacement found an unreadable job write lock"
        ) from exc
    if (
        lock.job_id != job_id
        or lock.workflow_id != lock_owner_id
        or lock.process_id != os.getpid()
        or lock.expires_at <= datetime.now(UTC)
    ):
        raise RuntimeError(
            "Canonical SceneSpec replacement does not own the current job write lock"
        )


def current_job_write_lock_owner(job_id: str) -> str:
    """Return the exact valid shared-lock owner held by the current process."""

    from .orchestration.models import WorkflowLock

    root = job_dir(job_id)
    lock_path = root / "workflows" / ".lock.json"
    if not lock_path.is_file():
        raise RuntimeError("No shared job write lock is active")
    try:
        lock = WorkflowLock.model_validate_json(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("The shared job write lock is unreadable") from exc
    _require_scene_spec_lock_owner(root, job_id, lock.workflow_id)
    return lock.workflow_id


@contextmanager
def canonical_scene_spec_write_lock(
    job_id: str,
    lock_owner_id: str,
    *,
    ttl_seconds: int = 86400,
) -> Iterator[Any]:
    """Serialize one canonical SceneSpec writer through the V0.8 job-global lock."""

    from .orchestration.locks import workflow_write_lock

    root = job_dir(job_id)
    with workflow_write_lock(
        root,
        job_id,
        lock_owner_id,
        ttl_seconds=ttl_seconds,
    ) as lock:
        yield lock


def replace_scene_spec_if_current(
    job_id: str,
    candidate_path: Path,
    *,
    expected_current_sha256: str | None,
    expected_candidate_sha256: str,
    lock_owner_id: str,
    archive_current: bool = True,
) -> dict[str, Any]:
    """Atomically promote one validated candidate only over the expected canonical hash."""

    from .models import SceneSpec
    from .validation import validate_scene_spec_interior_contract

    root = job_dir(job_id).resolve()
    current = root / "analysis" / "scene_spec.json"
    candidate = candidate_path.expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("SceneSpec candidate must stay inside the owning job") from exc
    if candidate == current:
        raise ValueError("SceneSpec candidate must differ from the canonical path")
    if not candidate.is_file():
        raise FileNotFoundError(f"SceneSpec candidate is missing: {candidate}")

    _require_scene_spec_lock_owner(root, job_id, lock_owner_id)
    candidate_hash = sha256_file(candidate)
    if candidate_hash != expected_candidate_sha256:
        raise RuntimeError(
            "SceneSpec candidate changed before canonical replacement; "
            "refusing stale or tampered content"
        )
    candidate_model = SceneSpec.model_validate_json(
        candidate.read_text(encoding="utf-8")
    )
    if candidate_model.job_id != job_id:
        raise ValueError(
            f"SceneSpec candidate job_id changed to {candidate_model.job_id!r}"
        )
    validate_scene_spec_interior_contract(candidate_model, current)

    if expected_current_sha256 is None:
        if current.exists():
            raise RuntimeError(
                "Canonical SceneSpec appeared after candidate generation; "
                "refusing to overwrite it"
            )
    elif (
        not current.is_file()
        or sha256_file(current) != expected_current_sha256
    ):
        raise RuntimeError(
            "Canonical SceneSpec changed before replacement; refusing a stale writer"
        )

    archived: Path | None = None
    if archive_current and expected_current_sha256 is not None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        archived = (
            root
            / "history"
            / f"{stamp}_{uuid4().hex[:8]}_scene_spec.json"
        )
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current, archived)
        if sha256_file(archived) != expected_current_sha256:
            raise RuntimeError(
                "Archived SceneSpec does not match the expected canonical hash"
            )

    temporary = current.with_name(f".scene_spec.replace-{uuid4().hex}.json")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, temporary)
    try:
        if sha256_file(temporary) != expected_candidate_sha256:
            raise RuntimeError(
                "SceneSpec replacement copy does not match the approved candidate hash"
            )
        _require_scene_spec_lock_owner(root, job_id, lock_owner_id)
        if expected_current_sha256 is None:
            if current.exists():
                raise RuntimeError(
                    "Canonical SceneSpec appeared immediately before replacement"
                )
        elif (
            not current.is_file()
            or sha256_file(current) != expected_current_sha256
        ):
            raise RuntimeError(
                "Canonical SceneSpec changed immediately before replacement"
            )
        os.replace(temporary, current)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    result_hash = sha256_file(current)
    if result_hash != expected_candidate_sha256:
        raise RuntimeError("Canonical SceneSpec hash does not match the promoted candidate")
    return {
        "job_id": job_id,
        "previous_scene_spec_sha256": expected_current_sha256,
        "candidate_scene_spec_sha256": expected_candidate_sha256,
        "result_scene_spec_sha256": result_hash,
        "archived_scene_spec": str(archived) if archived is not None else None,
        "lock_owner_id": lock_owner_id,
    }
