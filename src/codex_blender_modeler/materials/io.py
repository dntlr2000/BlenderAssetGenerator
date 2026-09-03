from __future__ import annotations

from pathlib import Path

from ..blender_artifacts import native_io_path
from .models import MaterialPlan, ShaderRecipe


def resolve_job_path(job_root: Path, value: str, label: str) -> Path:
    """Resolve a workspace-owned contract path while blocking path traversal."""

    resolved_root = job_root.expanduser().resolve()
    resolved = (resolved_root / value).expanduser().resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside job root: {resolved}") from exc
    return resolved


def load_material_plan(path: Path) -> MaterialPlan:
    """Load a strict material plan through the native long-path I/O boundary."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return MaterialPlan.model_validate_json(handle.read())


def load_shader_recipe(path: Path) -> ShaderRecipe:
    """Load a whitelisted shader recipe through the native long-path I/O boundary."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        return ShaderRecipe.model_validate_json(handle.read())
