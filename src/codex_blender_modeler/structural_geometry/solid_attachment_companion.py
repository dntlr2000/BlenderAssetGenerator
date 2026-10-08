"""Explicit additive closed-solid root-ball intent, distinct from heightfield patch proof."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from ..solid_attachment_contract import validate_solid_root_contract
from .attachment_companion import Artifact, Strict

Identity = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]


class SolidRootBallEntryV01(Strict):
    """Bind one intended local volumetric joint, never a seam-wide coverage claim."""

    attachment_id: Identity
    scope: Literal["required_local_overlap_ball"]
    owner_semantic_id: Identity
    subject_semantic_id: Identity
    joint_description: str = Field(min_length=1, max_length=1000)
    center: list[float] = Field(min_length=3, max_length=3)
    radius_m: float = Field(gt=0, le=1e6)
    root_bounds: list[list[float]] = Field(min_length=2, max_length=2)


class SolidRootAttachmentIntentV01(Strict):
    """Select a separately named bounded proof domain with immutable source/camera intent."""

    schema_version: Literal["0.1.0"]
    contract_kind: Literal["solid_root_attachment_intent"]
    job_id: Identity
    source_reference: Artifact
    source_modeling_plan: Artifact
    source_scene: Artifact
    source_geometry: list[Artifact] = Field(min_length=2, max_length=128)
    source_camera_hypothesis: Artifact
    minimum_radius_m: float = Field(gt=0, le=1e6)
    radius_basis: str = Field(min_length=1, max_length=2000)
    required_semantics: list[Identity] = Field(min_length=2, max_length=128)
    entries: list[SolidRootBallEntryV01] = Field(min_length=1, max_length=256)

    @model_validator(mode="before")
    @classmethod
    def require_complete_serialized_contract(cls, value: Any) -> Any:
        """Reject omitted headers/defaults before an immutable registration can be written."""
        validate_solid_root_contract(value)
        return value

    @model_validator(mode="after")
    def validate_complete_contract(self) -> Self:
        """Keep host and fixed stdlib reader selection rules identical."""
        validate_solid_root_contract(self.model_dump(mode="json"))
        return self

    @property
    def reference_region_evidence(self) -> None:
        """Never imply applicability of the legacy axis-aligned occupancy proof."""
        return None
