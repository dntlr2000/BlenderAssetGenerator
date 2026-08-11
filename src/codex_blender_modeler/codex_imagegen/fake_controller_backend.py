"""Deterministic test-only controller backend for ImageGen lifecycle tests."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image

from ..blender_artifacts import native_io_path
from ..production.controller_executor import PhaseToolProfile
from .completion import copy_imagegen_png_and_write_completion
from .models import (
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationCompletion,
)


class FakeCodexImagegenController:
    """Generate deterministic PNG fixtures inside the raw controller boundary."""

    controller_kind = "fake_for_tests"

    def __init__(
        self,
        *,
        assignment_artifact: CodexImageArtifact,
        behavior: str = "success",
        executed_at: datetime | None = None,
    ) -> None:
        """Configure one explicit success or failure behavior for a single invocation."""

        self.assignment_artifact = assignment_artifact
        self.behavior = behavior
        self.executed_at = executed_at
        self.calls = 0

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Write deterministic declared outputs while supporting bounded negative fixtures."""

        del immutable_inputs, timeout_seconds
        self.calls += 1
        if tool_profile.network_access != "denied":
            raise ValueError("fake ImageGen controller requires denied network authority")
        if self.behavior in {"timeout", "failed", "cancelled"}:
            return self.behavior
        assignment_model = CodexImageGenerationAssignment.model_validate_json(
            assignment.read_bytes()
        )
        if self.behavior == "partial":
            self._write_fixture_png(allowed_output_paths[0], assignment_model, 0)
            return "completed"
        with tempfile.TemporaryDirectory(prefix="cbm-codex-imagegen-fake-") as temporary:
            sources = []
            for ordinal in range(assignment_model.requested_candidate_count):
                source = Path(temporary) / f"candidate-{ordinal:02d}.png"
                self._write_fixture_png(source, assignment_model, ordinal)
                sources.append(source)
            copy_imagegen_png_and_write_completion(
                controller_workspace_root=Path(
                    os.path.commonpath([assignment, *allowed_output_paths])
                ),
                allowed_source_root=Path(temporary),
                assignment_path=assignment,
                assignment_artifact=self.assignment_artifact,
                source_png_paths=sources,
                allowed_output_paths=allowed_output_paths,
                output_roles=[
                    assignment_model.allowed_output_roles[
                        min(index, len(assignment_model.allowed_output_roles) - 1)
                    ]
                    for index in range(assignment_model.requested_candidate_count)
                ],
                completion_id=f"completion-{assignment_model.assignment_id}",
                controller_kind="fake_for_tests",
                controller_executed_at=self.executed_at or assignment_model.created_at,
            )
        if self.behavior == "wrong_hash":
            with open(native_io_path(allowed_output_paths[0]), "ab") as handle:
                handle.write(b"tampered-after-completion")
        if self.behavior in {"extra", "duplicate_completion"}:
            extra_name = (
                "duplicate-completion.json"
                if self.behavior == "duplicate_completion"
                else "unexpected.txt"
            )
            extra = allowed_output_paths[0].parent / extra_name
            with open(native_io_path(extra), "wb") as handle:
                handle.write(b"unexpected\n")
        if self.behavior == "over_budget":
            self._rewrite_generation_count(allowed_output_paths[-1], 4)
        return "completed"

    def _write_fixture_png(
        self,
        path: Path,
        assignment: CodexImageGenerationAssignment,
        ordinal: int,
    ) -> None:
        """Create a deterministic non-uniform RGBA PNG at the assignment dimensions."""

        width = assignment.image_size.width
        height = assignment.image_size.height
        image = Image.new("RGBA", (width, height))
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                value = (x * 17 + y * 31 + ordinal * 53) % 256
                pixels[x, y] = (value, (value * 3) % 256, (value * 7) % 256, 255)
        os.makedirs(native_io_path(path.parent), exist_ok=True)
        image.save(native_io_path(path), format="PNG")

    def _rewrite_generation_count(self, path: Path, generation_count: int) -> None:
        """Inject a model-valid but assignment-inconsistent budget claim for tests."""

        with open(native_io_path(path), "rb") as handle:
            completion = CodexImageGenerationCompletion.model_validate_json(handle.read())
        payload = completion.model_dump(mode="python")
        payload["generation_count"] = generation_count
        rewritten = CodexImageGenerationCompletion.model_validate(payload)
        with open(native_io_path(path), "w", encoding="utf-8") as handle:
            handle.write(rewritten.model_dump_json(indent=2) + "\n")
