from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from ..workspace import sha256_file
from .hashing import canonical_model_sha256
from .models import QATargetManifest, VisualQARequest


@dataclass(frozen=True)
class GeneratedTarget:
    """Describe the artifact and reproducibility metadata returned by a QA image provider."""

    path: Path
    model: str
    model_version: str | None = None
    seed: int | None = None


class QATargetProvider(Protocol):
    """Define the narrow provider interface for advisory QA target generation."""

    name: str

    def generate(
        self,
        request: VisualQARequest,
        prompt: str,
        output_path: Path,
    ) -> GeneratedTarget:
        """Generate one fixed-camera advisory target image."""


class ExistingFileQATargetProvider:
    """Copy one explicitly selected external image into an isolated QA run."""

    name = "existing_file"

    def __init__(
        self,
        source_path: Path,
        *,
        model: str,
        model_version: str | None = None,
        seed: int | None = None,
        allowed_root: Path | None = None,
    ) -> None:
        """Validate an absolute image source and optional containment boundary."""

        expanded = source_path.expanduser()
        if not expanded.is_absolute():
            raise ValueError("existing QA target source_path must be absolute")
        resolved = expanded.resolve(strict=True)
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        if allowed_root is not None:
            boundary = allowed_root.expanduser().resolve(strict=True)
            if not boundary.is_dir():
                raise NotADirectoryError(boundary)
            try:
                resolved.relative_to(boundary)
            except ValueError as exc:
                raise ValueError(
                    f"existing QA target is outside allowed_root: {resolved}"
                ) from exc
        if not model.strip():
            raise ValueError("existing QA target model metadata must not be empty")
        with Image.open(resolved) as image:
            image.verify()
        self.source_path = resolved
        self.model = model.strip()
        self.model_version = model_version
        self.seed = seed

    def generate(
        self,
        request: VisualQARequest,
        prompt: str,
        output_path: Path,
    ) -> GeneratedTarget:
        """Copy the validated source to the service-owned output and retain provenance."""

        del request, prompt
        destination = output_path.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination != self.source_path:
            shutil.copy2(self.source_path, destination)
        return GeneratedTarget(
            path=destination,
            model=self.model,
            model_version=self.model_version,
            seed=self.seed,
        )


def _prompt_sha256(prompt: str) -> str:
    """Hash the exact target-generation prompt for caching and provenance."""

    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def generate_optional_qa_target(
    request: VisualQARequest,
    *,
    provider: QATargetProvider | None,
    prompt: str,
    output_path: Path,
    cached_path: Path | None = None,
) -> QATargetManifest:
    """Generate or reuse an advisory target while converting provider failures to warnings."""

    request_hash = canonical_model_sha256(request)
    prompt_hash = _prompt_sha256(prompt)
    if not request.include_generated_target or provider is None:
        return QATargetManifest(
            job_id=request.job_id,
            run_id=request.run_id,
            request_sha256=request_hash,
            camera_fingerprint=request.camera_fingerprint,
            status="disabled",
            provider=getattr(provider, "name", "disabled"),
            prompt_sha256=prompt_hash,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if cached_path is not None and cached_path.is_file():
        if cached_path.resolve() != output_path.resolve():
            shutil.copy2(cached_path, output_path)
        return QATargetManifest(
            job_id=request.job_id,
            run_id=request.run_id,
            request_sha256=request_hash,
            camera_fingerprint=request.camera_fingerprint,
            status="cached",
            provider=provider.name,
            prompt_sha256=prompt_hash,
            output_path=str(output_path),
            output_sha256=sha256_file(output_path),
        )

    try:
        generated = provider.generate(request, prompt, output_path)
        source = generated.path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"QA target provider did not create an image: {source}")
        if source != output_path.resolve():
            shutil.copy2(source, output_path)
        return QATargetManifest(
            job_id=request.job_id,
            run_id=request.run_id,
            request_sha256=request_hash,
            camera_fingerprint=request.camera_fingerprint,
            status="generated",
            provider=provider.name,
            model=generated.model,
            model_version=generated.model_version,
            seed=generated.seed,
            prompt_sha256=prompt_hash,
            output_path=str(output_path),
            output_sha256=sha256_file(output_path),
        )
    except Exception as exc:  # noqa: BLE001 - provider failures are explicitly non-fatal.
        return QATargetManifest(
            job_id=request.job_id,
            run_id=request.run_id,
            request_sha256=request_hash,
            camera_fingerprint=request.camera_fingerprint,
            status="failed",
            provider=provider.name,
            prompt_sha256=prompt_hash,
            error=f"{type(exc).__name__}: {exc}",
        )
