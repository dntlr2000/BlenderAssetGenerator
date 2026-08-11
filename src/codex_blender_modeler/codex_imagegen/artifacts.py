"""Contained immutable artifact helpers for Codex ImageGen evidence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..blender_artifacts import native_io_path, sha256_file, write_json_atomic
from ..production.validation import ensure_contained_production_path
from .models import CodexImageArtifact

ModelT = TypeVar("ModelT", bound=BaseModel)


def artifact_for_codex_image(
    job_root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    media_type: str,
) -> CodexImageArtifact:
    """Bind one contained, non-empty regular file to exact bytes and media type."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    safe = ensure_contained_codex_image_path(root, path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ValueError(f"Codex ImageGen artifact is not a regular file: {safe.name}")
    size = os.path.getsize(native_io_path(safe))
    if size <= 0:
        raise ValueError(f"Codex ImageGen artifact must be non-empty: {safe.name}")
    return CodexImageArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=size,
        media_type=media_type,
    )


def validate_codex_image_artifact(
    job_root: Path,
    artifact: CodexImageArtifact,
) -> Path:
    """Reject a missing, linked, resized, or rehashed ImageGen artifact."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    path = ensure_contained_codex_image_path(
        root,
        root / artifact.path,
        must_exist=True,
    )
    if not os.path.isfile(native_io_path(path)):
        raise ValueError(f"Codex ImageGen artifact is not a regular file: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"Codex ImageGen artifact size changed: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"Codex ImageGen artifact hash changed: {artifact.path}")
    return path


def write_immutable_codex_image_model(
    job_root: Path,
    path: Path,
    model: BaseModel,
    *,
    kind: str,
) -> CodexImageArtifact:
    """Publish one strict JSON contract exactly once and return its exact binding."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    destination = ensure_contained_codex_image_path(root, path, must_exist=False)
    if os.path.exists(native_io_path(destination)):
        raise FileExistsError(destination)
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    ensure_contained_codex_image_path(root, destination.parent, must_exist=True)
    write_json_atomic(destination, model.model_dump(mode="json"))
    return artifact_for_codex_image(
        root,
        destination,
        artifact_id=str(getattr(model, "contract_id", destination.stem)),
        kind=kind,
        media_type="application/json",
    )


def load_codex_image_model(
    job_root: Path,
    artifact: CodexImageArtifact,
    model_type: type[ModelT],
) -> ModelT:
    """Rehash and strict-parse one exact JSON evidence artifact."""

    if artifact.media_type != "application/json":
        raise ValueError("Codex ImageGen model artifact must use application/json")
    path = validate_codex_image_artifact(job_root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return model_type.model_validate_json(handle.read())


def ensure_contained_codex_image_path(
    root: Path,
    path: Path,
    *,
    must_exist: bool,
) -> Path:
    """Apply central containment through extended Windows paths and return lexical paths."""

    lexical_root = Path(os.path.abspath(os.fspath(root)))
    lexical_path = Path(os.path.abspath(os.fspath(path)))
    ensure_contained_production_path(
        Path(native_io_path(lexical_root)),
        Path(native_io_path(lexical_path)),
        must_exist=must_exist,
    )
    return lexical_path
