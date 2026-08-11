"""Deterministic fake controller for executor failure and recovery tests only."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from ...blender_artifacts import native_io_path
from .models import PhaseToolProfile


class FakeControllerForTests:
    """Inject one bounded output behavior without touching canonical workspace paths."""

    controller_kind = "fake_for_tests"

    def __init__(
        self,
        *,
        behavior: str = "success",
        payloads: dict[str, bytes] | None = None,
    ) -> None:
        """Configure deterministic success or one explicit negative test behavior."""

        self.behavior = behavior
        self.payloads = payloads or {}
        self.calls = 0
        self.last_assignment: Path | None = None
        self.last_immutable_inputs: tuple[Path, ...] = ()
        self.last_allowed_output_paths: tuple[Path, ...] = ()

    def _payload_for_output(self, path: Path) -> bytes:
        """Resolve basename keys while retaining unambiguous legacy relative-path keys."""

        direct = self.payloads.get(path.name)
        if direct is not None:
            return direct
        legacy_matches = [
            payload
            for key, payload in self.payloads.items()
            if PurePosixPath(key.replace("\\", "/")).name == path.name
        ]
        if len(legacy_matches) > 1:
            raise ValueError(f"ambiguous fake payload key for {path.name}")
        if legacy_matches:
            return legacy_matches[0]
        return f"fixture:{path.name}\n".encode()

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Write only requested test outputs, except for the named negative fixture."""

        del tool_profile, timeout_seconds
        self.calls += 1
        self.last_assignment = assignment
        self.last_immutable_inputs = immutable_inputs
        self.last_allowed_output_paths = allowed_output_paths
        if self.behavior in {"timeout", "failed", "cancelled", "crash"}:
            if self.behavior == "crash":
                raise RuntimeError("injected controller crash")
            return self.behavior
        selected = list(allowed_output_paths)
        if self.behavior == "partial":
            selected = selected[:1]
        for path in selected:
            os.makedirs(native_io_path(path.parent), exist_ok=True)
            payload = self._payload_for_output(path)
            with open(native_io_path(path), "wb") as handle:
                handle.write(payload)
        if self.behavior == "extra":
            extra = allowed_output_paths[0].parent / "unexpected.txt"
            os.makedirs(native_io_path(extra.parent), exist_ok=True)
            with open(native_io_path(extra), "wb") as handle:
                handle.write(b"unexpected\n")
        if self.behavior == "mutate_input":
            with open(native_io_path(assignment), "ab") as handle:
                handle.write(b"mutated\n")
        if self.behavior == "escape":
            escaped = allowed_output_paths[0].parents[2] / "escaped.txt"
            with open(native_io_path(escaped), "wb") as handle:
                handle.write(b"escaped\n")
        return "completed"
