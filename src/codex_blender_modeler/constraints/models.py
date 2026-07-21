from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Axis = Literal["X", "Y", "Z"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConstraintBase(StrictModel):
    id: str
    enabled: bool = True
    source: str | None = None
    notes: list[str] = Field(default_factory=list)


class DimensionConstraint(ConstraintBase):
    kind: Literal["dimension"] = "dimension"
    target_id: str = Field(description="Semantic object family ID or __scene__")
    axis: Axis
    value_m: float = Field(gt=0)
    tolerance_m: float = Field(default=0.001, gt=0)
    instance_index: int | None = Field(default=None, ge=0)


class LocationConstraint(ConstraintBase):
    kind: Literal["location"] = "location"
    target_id: str
    axis: Axis
    value_m: float
    tolerance_m: float = Field(default=0.001, gt=0)
    instance_index: int | None = Field(default=None, ge=0)


class DistanceConstraint(ConstraintBase):
    kind: Literal["distance"] = "distance"
    object_a: str
    object_b: str
    axis: Literal["X", "Y", "Z", "XYZ"] = "XYZ"
    value_m: float = Field(ge=0)
    tolerance_m: float = Field(default=0.001, gt=0)
    instance_a: int | None = Field(default=None, ge=0)
    instance_b: int | None = Field(default=None, ge=0)


class AlignConstraint(ConstraintBase):
    kind: Literal["align"] = "align"
    object_ids: list[str] = Field(min_length=2)
    axis: Axis
    anchor: Literal["CENTER", "MIN", "MAX"] = "CENTER"
    tolerance_m: float = Field(default=0.001, gt=0)


class EqualDimensionConstraint(ConstraintBase):
    kind: Literal["equal_dimension"] = "equal_dimension"
    object_ids: list[str] = Field(min_length=2)
    axis: Axis
    tolerance_m: float = Field(default=0.001, gt=0)


Constraint = Annotated[
    DimensionConstraint
    | LocationConstraint
    | DistanceConstraint
    | AlignConstraint
    | EqualDimensionConstraint,
    Field(discriminator="kind"),
]


class ConstraintSet(StrictModel):
    schema_version: Literal["0.4.0"] = "0.4.0"
    job_id: str
    units: Literal["METERS"] = "METERS"
    constraints: list[Constraint] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids(self) -> ConstraintSet:
        ids = [constraint.id for constraint in self.constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("Constraint IDs must be unique")
        return self


class ConstraintResult(StrictModel):
    id: str
    kind: str
    status: Literal["passed", "failed", "missing", "disabled"]
    requested: float | list[float] | None = None
    actual: float | list[float] | None = None
    residual_m: float | None = None
    tolerance_m: float | None = None
    message: str


class ConstraintSolution(StrictModel):
    schema_version: Literal["0.4.0"] = "0.4.0"
    job_id: str
    ok: bool
    evaluated: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    missing: int = Field(ge=0)
    disabled: int = Field(ge=0)
    max_residual_m: float | None = None
    results: list[ConstraintResult]
    notes: list[str] = Field(default_factory=list)
