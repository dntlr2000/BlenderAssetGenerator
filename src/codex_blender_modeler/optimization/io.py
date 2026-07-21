"""Safe filesystem helpers for derived V0.7 portable-asset runs."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from ..blender_artifacts import write_json_atomic

ModelT = TypeVar("ModelT", bound=BaseModel)
FILESYSTEM_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def validate_filesystem_id(value: str, label: str) -> str:
    """Reject path syntax, trailing dots, and Windows device names in directory IDs."""

    stem = value.split(".", 1)[0].upper()
    if (
        FILESYSTEM_ID_PATTERN.fullmatch(value) is None
        or value.endswith(".")
        or stem in WINDOWS_RESERVED_NAMES
    ):
        raise ValueError(
            f"{label} must be a portable filesystem identifier using letters, numbers, "
            "'.', '_', or '-'"
        )
    return value


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for versioned run contracts."""

    return datetime.now(UTC)


def new_run_id(prefix: str = "asset") -> str:
    """Create a sortable stable run ID without depending on workspace contents."""

    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{prefix}-{uuid4().hex[:8]}"


def resolve_inside(root: Path, value: str | Path, label: str) -> Path:
    """Resolve one path and reject traversal or symlink escape outside its root."""

    resolved_root = root.expanduser().resolve()
    candidate = Path(value).expanduser()
    resolved = (candidate if candidate.is_absolute() else resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside {resolved_root}: {resolved}") from exc
    return resolved


def job_relative(root: Path, path: Path) -> str:
    """Return a normalized POSIX job-relative path for a contained artifact."""

    resolved_root = root.expanduser().resolve()
    resolved_path = path.expanduser().resolve()
    try:
        return resolved_path.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Artifact is outside the job workspace: {resolved_path}") from exc


def write_model(path: Path, model: BaseModel) -> None:
    """Persist one validated Pydantic contract atomically in JSON mode."""

    write_json_atomic(path, model.model_dump(mode="json"))


def load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    """Load and validate one required JSON object as the requested model type."""

    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON contract: {path}") from exc
    return model_type.model_validate(payload)


def run_directory(job_root: Path, run_id: str, *, create: bool = False) -> Path:
    """Resolve one V0.7 run directory without accepting path-like run IDs."""

    validate_filesystem_id(run_id, "run_id")
    root = job_root / "optimization" / "runs"
    run = resolve_inside(root, run_id, "optimization run")
    if create:
        run.mkdir(parents=True, exist_ok=False)
    return run


def latest_run_id(job_root: Path) -> str | None:
    """Read the latest successful or in-progress V0.7 run pointer when present."""

    path = job_root / "optimization" / "latest.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("run_id") if isinstance(payload, dict) else None
    return str(value) if value else None


def latest_complete_run_id(job_root: Path) -> str | None:
    """Find the newest complete run instead of trusting a failed latest-run pointer."""

    runs_root = job_root / "optimization" / "runs"
    if not runs_root.is_dir():
        return None
    pointer = latest_run_id(job_root)
    candidates = [pointer] if pointer else []
    candidates.extend(
        path.name
        for path in sorted(runs_root.iterdir(), reverse=True)
        if path.is_dir() and path.name != pointer
    )
    for run_id in candidates:
        if not run_id:
            continue
        try:
            validate_filesystem_id(run_id, "run_id")
            plan_path = runs_root / run_id / "optimization_plan.json"
            blend_path = runs_root / run_id / "optimized" / "scene.blend"
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("status") == "complete"
            and blend_path.is_file()
        ):
            return run_id
    return None


def write_latest_run(job_root: Path, run_id: str, status: str) -> None:
    """Atomically update the derived latest-run pointer without changing canonical inputs."""

    write_json_atomic(
        job_root / "optimization" / "latest.json",
        {
            "schema_version": "0.7.0",
            "run_id": run_id,
            "status": status,
            "updated_at": utc_now().isoformat(),
        },
    )
