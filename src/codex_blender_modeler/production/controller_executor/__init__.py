"""Public ControllerExecutor 0.1.0 contracts and bounded adapters."""

from .app_server import OptionalCodexAppServerController
from .desktop import DesktopInSessionController
from .fake import FakeControllerForTests
from .models import (
    ControllerArtifact,
    ControllerCapabilityStatus,
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
)
from .profiles import (
    build_phase_tool_profile,
    controller_capability_catalog,
    phase_tool_profile_catalog,
)
from .protocol import CandidateAuthoringController
from .service import (
    execute_controller_request,
    validate_controller_execution_result,
    write_controller_contract,
)

__all__ = [
    "CandidateAuthoringController",
    "ControllerArtifact",
    "ControllerCapabilityStatus",
    "ControllerExecutionRequest",
    "ControllerResult",
    "DesktopInSessionController",
    "FakeControllerForTests",
    "OptionalCodexAppServerController",
    "PhaseToolProfile",
    "build_phase_tool_profile",
    "controller_capability_catalog",
    "execute_controller_request",
    "phase_tool_profile_catalog",
    "validate_controller_execution_result",
    "write_controller_contract",
]
