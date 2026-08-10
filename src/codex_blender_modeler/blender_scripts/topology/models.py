"""Strict contracts for profile-specific topology and portability evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...stabilization.models import JobId, PortableId, RelativePath, Sha256, WorkflowId

SCHEMA_VERSION = "0.1.0"
TopologyProfileName = Literal[
    "static_prop_closed",
    "static_prop_open",
    "game_ready_lowpoly",
    "highpoly_bake_source",
    "modular_architecture",
    "terrain",
]
TopologyCheckName = Literal[
    "non_finite",
    "degenerate_face",
    "self_intersection",
    "winding",
    "flipped_normal",
    "loose_geometry",
    "open_boundary",
    "triangle_aspect",
    "ngon_limit",
    "uv0",
    "uv_overlap",
    "island_padding",
    "texel_density",
    "tangent",
    "subdivision_pinching",
    "lod_silhouette_error",
    "clean_import_normal_preservation",
    "clean_import_material_preservation",
]


class TopologyStrictModel(BaseModel):
    """Reject undeclared fields and non-finite values in topology contracts."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class TopologyArtifact(TopologyStrictModel):
    """Bind one topology evidence artifact to a portable path and digest."""

    role: Literal[
        "scene_spec",
        "blend",
        "topology_inventory",
        "uv_report",
        "tangent_report",
        "lod_report",
        "roundtrip_report",
        "other",
    ]
    path: RelativePath
    sha256: Sha256


class TopologyProvenance(TopologyStrictModel):
    """Freeze job, workflow, dispatch, versions, and exact inspection inputs."""

    job_id: JobId
    workflow_id: WorkflowId
    dispatch_id: PortableId
    project_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    topology_contract_version: Literal["0.1.0"] = SCHEMA_VERSION
    inputs: list[TopologyArtifact] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_inputs(self) -> TopologyProvenance:
        """Require unique paths and current scene/build evidence."""

        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("topology provenance paths must be unique")
        roles = {item.role for item in self.inputs}
        if not {"scene_spec", "blend"}.issubset(roles):
            raise ValueError("topology provenance requires scene_spec and blend")
        return self


class TopologyCheckPolicy(TopologyStrictModel):
    """Classify one profile check as a hard failure or warning."""

    check: TopologyCheckName
    failure_severity: Literal["hard_failure", "warning"]
    rationale: str = Field(min_length=1, max_length=1000)


class TopologyProfile(TopologyStrictModel):
    """Define one of the six immutable topology acceptance profiles."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    name: TopologyProfileName
    checks: list[TopologyCheckPolicy] = Field(min_length=18, max_length=18)

    @model_validator(mode="after")
    def validate_checks(self) -> TopologyProfile:
        """Require each supported check exactly once in every profile."""

        names = [item.check for item in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("topology profile checks must be unique")
        if len(names) != 18:
            raise ValueError("topology profile must classify all 18 checks")
        return self


class TopologyObservation(TopologyStrictModel):
    """Record one check as available, unavailable, or explicitly not applicable."""

    check: TopologyCheckName
    availability: Literal["available", "unavailable", "not_applicable"]
    passed: bool | None = None
    measured_value: float | int | str | bool | None = None
    threshold: float | int | str | None = None
    evidence: TopologyArtifact | None = None
    message: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_availability(self) -> TopologyObservation:
        """Prevent missing evidence from being encoded as a passing check."""

        if self.availability == "available":
            if self.passed is None or self.evidence is None:
                raise ValueError("available topology evidence requires passed and evidence")
        elif (
            self.passed is not None or self.measured_value is not None or self.evidence is not None
        ):
            raise ValueError("unavailable or not-applicable evidence cannot claim a result")
        return self


class TopologyCheckResult(TopologyStrictModel):
    """Apply one profile severity while retaining evidence availability."""

    check: TopologyCheckName
    outcome: Literal[
        "passed",
        "hard_failure",
        "warning",
        "unscorable",
        "not_applicable",
    ]
    profile_failure_severity: Literal["hard_failure", "warning"]
    measured_value: float | int | str | bool | None = None
    threshold: float | int | str | None = None
    evidence: TopologyArtifact | None = None
    message: str


class TopologyCompanionReport(TopologyStrictModel):
    """Summarize profile evaluation while preserving unavailable evidence."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    report_id: PortableId
    provenance: TopologyProvenance
    profile: TopologyProfile
    status: Literal["passed", "warning", "failed", "unscorable"]
    ok: bool
    results: list[TopologyCheckResult] = Field(min_length=18, max_length=18)
    hard_failures: int = Field(ge=0)
    warnings: int = Field(ge=0)
    unscorable: int = Field(ge=0)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_summary(self) -> TopologyCompanionReport:
        """Keep report counts, profile coverage, and conservative status consistent."""

        result_names = [item.check for item in self.results]
        if len(result_names) != len(set(result_names)):
            raise ValueError("topology report result checks must be unique")
        if set(result_names) != {item.check for item in self.profile.checks}:
            raise ValueError("topology report results must match the selected profile")
        counts = {
            outcome: sum(item.outcome == outcome for item in self.results)
            for outcome in ("hard_failure", "warning", "unscorable")
        }
        if (self.hard_failures, self.warnings, self.unscorable) != (
            counts["hard_failure"],
            counts["warning"],
            counts["unscorable"],
        ):
            raise ValueError("topology report counters do not match results")
        hard_unscorable = any(
            item.outcome == "unscorable" and item.profile_failure_severity == "hard_failure"
            for item in self.results
        )
        warning_unscorable = any(
            item.outcome == "unscorable" and item.profile_failure_severity == "warning"
            for item in self.results
        )
        expected = (
            "failed"
            if self.hard_failures
            else "unscorable"
            if hard_unscorable
            else "warning"
            if self.warnings or warning_unscorable
            else "passed"
        )
        if self.status != expected or self.ok != (expected in {"passed", "warning"}):
            raise ValueError("topology report status or ok value is inconsistent")
        return self
