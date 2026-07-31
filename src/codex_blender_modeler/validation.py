from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .analysis.surface_details import validate_scene_surface_details
from .architecture import validate_scene_interior_scope
from .config import get_settings
from .models import SceneSpec


def _job_root_for_scene_spec(path: Path) -> Path | None:
    """Resolve a job-local analysis contract without treating arbitrary fixtures as jobs."""

    resolved = path.expanduser().resolve()
    if resolved.parent.name != "analysis":
        return None
    root = resolved.parent.parent
    if (root / "job.json").is_file() or (root / "architecture").is_dir():
        return root
    return None


def validate_scene_spec_interior_contract(scene_spec: SceneSpec, path: Path) -> None:
    """Reject job-local SceneSpecs that create interiors outside explicit user approval."""

    root = _job_root_for_scene_spec(path)
    if root is None:
        return
    report = validate_scene_interior_scope(scene_spec, root, write_report=False)
    if not report.ok:
        formatted = "\n".join(f"- {message}" for message in report.errors)
        raise ValueError(f"InteriorScope validation failed:\n{formatted}")


def load_scene_spec(path: Path) -> SceneSpec:
    """Load a schema-valid SceneSpec and enforce optional job-owned cross-contracts."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    schema_path = get_settings().repo_root / "schemas" / "scene_spec.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(raw), key=lambda e: list(e.path))
    if errors:
        formatted = "\n".join(f"- {'/'.join(map(str, e.path))}: {e.message}" for e in errors)
        raise ValueError(f"SceneSpec JSON Schema validation failed:\n{formatted}")
    scene_spec = SceneSpec.model_validate(raw)
    validate_scene_spec_interior_contract(scene_spec, path)
    validate_scene_surface_details(scene_spec, path)
    return scene_spec
