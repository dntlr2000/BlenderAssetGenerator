"""Additive read-only geometry authoring diagnostics; never an authorization receipt."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..stabilization.models import JobId, PortableId
from .models import AQV2Artifact, AQV2StrictModel, BudgetUsageV2


class GeometryAuthoringPreflightV01(AQV2StrictModel):
    """Bind one proposed candidate and its finite cost to the exact pre-controller state."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    contract_kind: Literal["geometry_authoring_preflight"] = "geometry_authoring_preflight"
    job_id: JobId
    session_id: PortableId
    current_state: AQV2Artifact
    root_authorization: AQV2Artifact
    budget: AQV2Artifact
    source_inputs: list[AQV2Artifact] = Field(min_length=4)
    candidate_modeling_plan: AQV2Artifact
    candidate_scene_spec_v03: AQV2Artifact
    structure_authoring: AQV2Artifact | None = None
    outcome: Literal["passed", "invalid_candidate", "budget_exhausted"]
    issues: list[str]
    candidate_object_count: int | None = Field(default=None, ge=1)
    required_blender_builds: int | None = Field(default=None, ge=2)
    budget_usage_after: BudgetUsageV2 | None = None
    controller_execution_authority: Literal[False] = False
    canonical_write_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    budget_consumed: Literal[False] = False

    @model_validator(mode="after")
    def validate_outcome(self) -> GeometryAuthoringPreflightV01:
        """Reject a pass without exact cost evidence or a failure disguised as funded output."""

        if len({item.path for item in self.source_inputs}) != len(self.source_inputs):
            raise ValueError("geometry preflight source inventory contains duplicate paths")
        if self.outcome == "passed":
            if (
                self.issues
                or self.budget_usage_after is None
                or self.candidate_object_count is None
            ):
                raise ValueError("passed geometry preflight requires funded cost and no issues")
        elif not self.issues or self.budget_usage_after is not None:
            raise ValueError("failed geometry preflight must retain issues without a reservation")
        if self.required_blender_builds != (
            self.candidate_object_count + 1 if self.candidate_object_count is not None else None
        ):
            raise ValueError(
                "geometry preflight cost must include every object and candidate build"
            )
        return self
