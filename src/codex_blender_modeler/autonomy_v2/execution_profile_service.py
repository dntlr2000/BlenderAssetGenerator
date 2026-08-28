"""Derive immutable execution-scoped controller profiles from an AQ v2 plan."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from ..blender_artifacts import native_io_path
from ..production.controller_executor import (
    ControllerArtifact,
    PhaseToolProfile,
    build_phase_tool_profile,
)
from .delivery_service import (
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .models import AQV2Artifact, AutonomyPlanV2

_EXECUTION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def _read_profile(root: Path, artifact: AQV2Artifact) -> PhaseToolProfile:
    """Rehash and parse one exact phase-tool profile artifact."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return PhaseToolProfile.model_validate_json(handle.read())


def _controller_artifact(artifact: AQV2Artifact) -> ControllerArtifact:
    """Project one AQ plan artifact into the controller provenance shape."""

    return ControllerArtifact(
        artifact_id=artifact.artifact_id,
        role="plan_phase_tool_profile",
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _artifact_binding(artifact: AQV2Artifact) -> tuple[str, str, int]:
    """Return the path, hash, and byte-size identity shared across artifact models."""

    return artifact.path, artifact.sha256, artifact.byte_size


def select_plan_phase_profile(
    root: Path,
    plan: AutonomyPlanV2,
    profile_id: str,
) -> tuple[PhaseToolProfile, AQV2Artifact]:
    """Select exactly one immutable plan template for the requested phase."""

    matches: list[tuple[PhaseToolProfile, AQV2Artifact]] = []
    for artifact in plan.phase_tool_profiles:
        profile = _read_profile(root, artifact)
        if profile.profile_id == profile_id:
            matches.append((profile, artifact))
    if len(matches) != 1:
        raise ValueError("AQ v2 plan must contain exactly one requested phase profile")
    return matches[0]


def execution_output_paths(
    template: PhaseToolProfile,
    execution_id: str,
) -> list[str]:
    """Insert one exact execution namespace below the template output root."""

    if _EXECUTION_ID.fullmatch(execution_id) is None:
        raise ValueError("controller execution ID is not a portable identifier")
    if not template.allowed_output_paths:
        raise ValueError("read-only phase profiles cannot be execution scoped")
    parents = {
        PurePosixPath(path).parent for path in template.allowed_output_paths
    }
    if len(parents) != 1:
        raise ValueError("AQ v2 phase outputs must share one isolated output root")
    parent = next(iter(parents))
    names = [PurePosixPath(path).name for path in template.allowed_output_paths]
    if len(names) != len(set(names)):
        raise ValueError("AQ v2 phase output leaf names must be unique")
    return [(parent / execution_id / name).as_posix() for name in names]


def _expected_execution_profile(
    template: PhaseToolProfile,
    template_artifact: AQV2Artifact,
    execution_id: str,
) -> PhaseToolProfile:
    """Rebuild the only profile derivation permitted for one controller execution."""

    return build_phase_tool_profile(
        profile_id=template.profile_id,
        job_id=template.job_id,
        workflow_id=template.workflow_id,
        dispatch_id=template.dispatch_id,
        session_id=template.session_id,
        source_artifact=_controller_artifact(template_artifact),
        allowed_input_roles=list(template.allowed_input_roles),
        allowed_output_paths=execution_output_paths(template, execution_id),
        created_at=template.created_at,
        supporting_client_enforced=(
            template.sandbox_attestation == "supporting_client_enforced"
        ),
        contract_id_suffix=execution_id,
    )


def publish_execution_phase_profile(
    root: Path,
    plan: AutonomyPlanV2,
    *,
    profile_id: str,
    execution_id: str,
) -> tuple[PhaseToolProfile, AQV2Artifact]:
    """Create or exact-adopt one execution-scoped profile under its request root."""

    template, template_artifact = select_plan_phase_profile(root, plan, profile_id)
    profile = _expected_execution_profile(
        template,
        template_artifact,
        execution_id,
    )
    path = (
        root
        / "production"
        / "autonomy_v2"
        / plan.session_id
        / "controller_executions"
        / execution_id
        / "phase_tool_profile.json"
    )
    artifact = write_immutable_v2_model(root, path, profile)
    validate_plan_or_execution_phase_profile(
        root,
        plan,
        artifact,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return profile, artifact


def validate_plan_or_execution_phase_profile(
    root: Path,
    plan: AutonomyPlanV2,
    artifact: AQV2Artifact,
    *,
    profile_id: str,
    execution_id: str,
) -> PhaseToolProfile:
    """Accept a legacy plan profile or an exact execution-scoped derivation only."""

    template, template_artifact = select_plan_phase_profile(root, plan, profile_id)
    observed = _read_profile(root, artifact)
    if _artifact_binding(artifact) == _artifact_binding(template_artifact):
        if observed != template:
            raise ValueError("legacy plan phase profile changed after planning")
        return observed
    expected_path = (
        PurePosixPath("production")
        / "autonomy_v2"
        / plan.session_id
        / "controller_executions"
        / execution_id
        / "phase_tool_profile.json"
    ).as_posix()
    if artifact.path != expected_path:
        raise PermissionError(
            "controller used a phase profile outside its exact execution root"
        )
    expected = _expected_execution_profile(
        template,
        template_artifact,
        execution_id,
    )
    if observed != expected:
        raise PermissionError(
            "controller execution profile is not an exact plan-template derivation"
        )
    return observed
