"""Desktop-in-session adapter that adopts only explicitly supplied output files."""

from __future__ import annotations

from pathlib import Path

from .models import PhaseToolProfile


class DesktopInSessionController:
    """Represent the current Codex task without claiming repository-side task creation."""

    controller_kind = "desktop_in_session"

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Return completed only when every declared desktop-authored output already exists."""

        del assignment, immutable_inputs, tool_profile, timeout_seconds
        if not allowed_output_paths or any(
            not output.is_absolute() for output in allowed_output_paths
        ):
            return "rejected"
        return "adopt_existing"
