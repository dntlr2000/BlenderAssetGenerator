from __future__ import annotations

from pathlib import Path

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
    """Load and validate a versioned material plan from disk."""

    return MaterialPlan.model_validate_json(path.read_text(encoding="utf-8"))


def load_shader_recipe(path: Path) -> ShaderRecipe:
    """Load and validate a whitelisted shader recipe from disk."""

    return ShaderRecipe.model_validate_json(path.read_text(encoding="utf-8"))
