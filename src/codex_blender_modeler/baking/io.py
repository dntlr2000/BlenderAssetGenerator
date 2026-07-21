from __future__ import annotations

from pathlib import Path

from .models import BakeManifest


def load_bake_manifest(path: Path) -> BakeManifest:
    """Load and validate one bake manifest from disk."""

    return BakeManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_bake_manifest(manifest: BakeManifest, path: Path) -> Path:
    """Persist a bake manifest without writing or modifying texture pixels."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
