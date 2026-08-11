"""Controller protocol used by the AQ 0.2 isolated authoring harness."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import PhaseToolProfile


class CandidateAuthoringController(Protocol):
    """Define the only host-visible operation for one bounded controller adapter."""

    controller_kind: str

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Execute inside supplied snapshots without receiving the canonical job root."""

        ...
