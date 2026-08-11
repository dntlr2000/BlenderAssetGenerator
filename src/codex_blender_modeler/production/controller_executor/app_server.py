"""Optional Codex App Server adapter with an explicit unverified boundary."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .models import ControllerCapabilityStatus, PhaseToolProfile

ControllerInvoke = Callable[
    [Path, tuple[Path, ...], tuple[Path, ...], PhaseToolProfile, int],
    str,
]


class OptionalCodexAppServerController:
    """Use only an injected, officially identified adapter and never guess a private API."""

    controller_kind = "optional_codex_app_server"

    def __init__(
        self,
        *,
        official_interface_id: str | None = None,
        invoke: ControllerInvoke | None = None,
    ) -> None:
        """Bind an optional callable only when the supporting client supplies its identity."""

        self.official_interface_id = official_interface_id
        self.invoke = invoke

    def capability_status(self) -> ControllerCapabilityStatus:
        """Report the adapter as unverified even when an official callable is injected."""

        detected = bool(self.official_interface_id and self.invoke)
        return ControllerCapabilityStatus(
            controller_kind=self.controller_kind,
            status="experimental_unverified" if detected else "unavailable",
            official_interface_detected=detected,
            limitations=[
                "repository code does not create a Codex task",
                "supporting-client sandbox and capability enforcement require separate evidence",
            ],
        )

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Invoke only the explicitly injected interface or fail closed as unavailable."""

        if not self.official_interface_id or self.invoke is None:
            return "unavailable"
        return self.invoke(
            assignment,
            immutable_inputs,
            allowed_output_paths,
            tool_profile,
            timeout_seconds,
        )
