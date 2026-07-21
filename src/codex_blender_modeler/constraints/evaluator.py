from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..workspace import job_dir, load_job
from .models import (
    AlignConstraint,
    ConstraintResult,
    ConstraintSet,
    ConstraintSolution,
    DimensionConstraint,
    DistanceConstraint,
    EqualDimensionConstraint,
    LocationConstraint,
)

_AXIS = {"X": 0, "Y": 1, "Z": 2}


@dataclass(frozen=True)
class Measurement:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    @property
    def dimensions(self) -> tuple[float, float, float]:
        return tuple(self.maximum[i] - self.minimum[i] for i in range(3))

    @property
    def center(self) -> tuple[float, float, float]:
        return tuple((self.maximum[i] + self.minimum[i]) / 2 for i in range(3))


def _measurement(record: dict[str, Any]) -> Measurement:
    bbox = record["bbox_world"]
    return Measurement(tuple(bbox["min"]), tuple(bbox["max"]))


def _inventory_index(
    inventory: dict[str, Any],
) -> tuple[dict[str, Measurement], dict[tuple[str, int], Measurement]]:
    families = {record["cbm_id"]: _measurement(record) for record in inventory.get("families", [])}
    instances: dict[tuple[str, int], Measurement] = {}
    for record in inventory.get("objects", []):
        object_id = record.get("cbm_id")
        index = record.get("instance_index")
        if object_id is None or index is None:
            continue
        instances[(str(object_id), int(index))] = _measurement(record)

    generated = list(families.values())
    if generated:
        families["__scene__"] = Measurement(
            tuple(min(item.minimum[axis] for item in generated) for axis in range(3)),
            tuple(max(item.maximum[axis] for item in generated) for axis in range(3)),
        )
    return families, instances


def _get(
    target_id: str,
    instance_index: int | None,
    families: dict[str, Measurement],
    instances: dict[tuple[str, int], Measurement],
) -> Measurement | None:
    if instance_index is not None:
        return instances.get((target_id, instance_index))
    return families.get(target_id)


def _result(
    constraint,
    *,
    actual: float | list[float] | None,
    requested: float | list[float] | None,
    residual: float | None,
    tolerance: float | None,
    missing: str | None = None,
) -> ConstraintResult:
    if not constraint.enabled:
        status = "disabled"
        message = "Constraint disabled"
    elif missing:
        status = "missing"
        message = missing
    elif residual is not None and tolerance is not None and residual <= tolerance:
        status = "passed"
        message = f"Residual {residual:.6g} m is within tolerance {tolerance:.6g} m"
    else:
        status = "failed"
        message = f"Residual {residual:.6g} m exceeds tolerance {tolerance:.6g} m"
    return ConstraintResult(
        id=constraint.id,
        kind=constraint.kind,
        status=status,
        requested=requested,
        actual=actual,
        residual_m=residual,
        tolerance_m=tolerance,
        message=message,
    )


def _evaluate_one(constraint, families, instances) -> ConstraintResult:
    if not constraint.enabled:
        return _result(
            constraint,
            actual=None,
            requested=None,
            residual=None,
            tolerance=None,
        )

    if isinstance(constraint, DimensionConstraint):
        measurement = _get(constraint.target_id, constraint.instance_index, families, instances)
        if measurement is None:
            return _result(
                constraint,
                actual=None,
                requested=constraint.value_m,
                residual=None,
                tolerance=constraint.tolerance_m,
                missing=f"Target not found: {constraint.target_id}",
            )
        actual = measurement.dimensions[_AXIS[constraint.axis]]
        return _result(
            constraint,
            actual=round(actual, 9),
            requested=constraint.value_m,
            residual=abs(actual - constraint.value_m),
            tolerance=constraint.tolerance_m,
        )

    if isinstance(constraint, LocationConstraint):
        measurement = _get(constraint.target_id, constraint.instance_index, families, instances)
        if measurement is None:
            return _result(
                constraint,
                actual=None,
                requested=constraint.value_m,
                residual=None,
                tolerance=constraint.tolerance_m,
                missing=f"Target not found: {constraint.target_id}",
            )
        actual = measurement.center[_AXIS[constraint.axis]]
        return _result(
            constraint,
            actual=round(actual, 9),
            requested=constraint.value_m,
            residual=abs(actual - constraint.value_m),
            tolerance=constraint.tolerance_m,
        )

    if isinstance(constraint, DistanceConstraint):
        a = _get(constraint.object_a, constraint.instance_a, families, instances)
        b = _get(constraint.object_b, constraint.instance_b, families, instances)
        if a is None or b is None:
            missing = constraint.object_a if a is None else constraint.object_b
            return _result(
                constraint,
                actual=None,
                requested=constraint.value_m,
                residual=None,
                tolerance=constraint.tolerance_m,
                missing=f"Target not found: {missing}",
            )
        if constraint.axis == "XYZ":
            actual = math.dist(a.center, b.center)
        else:
            axis = _AXIS[constraint.axis]
            actual = abs(a.center[axis] - b.center[axis])
        return _result(
            constraint,
            actual=round(actual, 9),
            requested=constraint.value_m,
            residual=abs(actual - constraint.value_m),
            tolerance=constraint.tolerance_m,
        )

    if isinstance(constraint, AlignConstraint):
        measurements = [families.get(object_id) for object_id in constraint.object_ids]
        missing = [
            object_id
            for object_id, measurement in zip(constraint.object_ids, measurements, strict=True)
            if measurement is None
        ]
        if missing:
            return _result(
                constraint,
                actual=None,
                requested=0.0,
                residual=None,
                tolerance=constraint.tolerance_m,
                missing=f"Targets not found: {missing}",
            )
        axis = _AXIS[constraint.axis]
        typed = [item for item in measurements if item is not None]
        if constraint.anchor == "CENTER":
            values = [item.center[axis] for item in typed]
        elif constraint.anchor == "MIN":
            values = [item.minimum[axis] for item in typed]
        else:
            values = [item.maximum[axis] for item in typed]
        residual = max(values) - min(values)
        return _result(
            constraint,
            actual=[round(value, 9) for value in values],
            requested=0.0,
            residual=residual,
            tolerance=constraint.tolerance_m,
        )

    if isinstance(constraint, EqualDimensionConstraint):
        measurements = [families.get(object_id) for object_id in constraint.object_ids]
        missing = [
            object_id
            for object_id, measurement in zip(constraint.object_ids, measurements, strict=True)
            if measurement is None
        ]
        if missing:
            return _result(
                constraint,
                actual=None,
                requested=0.0,
                residual=None,
                tolerance=constraint.tolerance_m,
                missing=f"Targets not found: {missing}",
            )
        axis = _AXIS[constraint.axis]
        values = [item.dimensions[axis] for item in measurements if item is not None]
        residual = max(values) - min(values)
        return _result(
            constraint,
            actual=[round(value, 9) for value in values],
            requested=0.0,
            residual=residual,
            tolerance=constraint.tolerance_m,
        )

    raise TypeError(f"Unsupported constraint type: {type(constraint)!r}")


def initialize_constraints(job_id: str, *, overwrite: bool = False) -> Path:
    root = job_dir(job_id)
    metadata = load_job(job_id)
    output = root / "constraints" / "constraints.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and not overwrite:
        raise FileExistsError(f"Constraint set already exists: {output}")
    notes = [
        "Use semantic object IDs from SceneSpec/scene_inventory.json.",
        "Use __scene__ as target_id for an overall scene dimension constraint.",
    ]
    anchors = metadata.get("scale_anchors", [])
    if anchors:
        notes.append("Unparsed scale anchors from job metadata: " + " | ".join(anchors))
    constraint_set = ConstraintSet(job_id=job_id, notes=notes)
    output.write_text(constraint_set.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output


def load_constraints(path: Path) -> ConstraintSet:
    """Load and validate one constraint set from disk."""

    return ConstraintSet.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_constraint_set(
    constraint_set: ConstraintSet,
    inventory: dict[str, Any],
) -> ConstraintSolution:
    """Evaluate a constraint set against an in-memory Blender scene inventory."""

    families, instances = _inventory_index(inventory)
    results = [
        _evaluate_one(constraint, families, instances)
        for constraint in constraint_set.constraints
    ]
    statuses = ["passed", "failed", "missing", "disabled"]
    counts = {
        status: sum(result.status == status for result in results) for status in statuses
    }
    residuals = [result.residual_m for result in results if result.residual_m is not None]
    return ConstraintSolution(
        job_id=constraint_set.job_id,
        ok=counts["failed"] == 0 and counts["missing"] == 0,
        evaluated=len(results),
        passed=counts["passed"],
        failed=counts["failed"],
        missing=counts["missing"],
        disabled=counts["disabled"],
        max_residual_m=max(residuals) if residuals else None,
        results=results,
        notes=[
            (
                "Constraint validation measures the generated Blender scene; "
                "it does not infer missing dimensions."
            )
        ],
    )


def evaluate_job_constraints(job_id: str) -> ConstraintSolution:
    """Evaluate a workspace constraint set and persist its solution report."""

    root = job_dir(job_id)
    constraint_path = root / "constraints" / "constraints.json"
    inventory_path = root / "reports" / "scene_inventory.json"
    if not constraint_path.is_file():
        raise FileNotFoundError(
            f"Constraint set is missing: {constraint_path}. Run cbm init-constraints {job_id}."
        )
    if not inventory_path.is_file():
        raise FileNotFoundError(
            f"Scene inventory is missing: {inventory_path}. Build and inspect the scene first."
        )
    constraint_set = load_constraints(constraint_path)
    if constraint_set.job_id != job_id:
        raise ValueError(
            f"Constraint job_id {constraint_set.job_id!r} does not match requested job {job_id!r}"
        )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    solution = evaluate_constraint_set(constraint_set, inventory)
    output = root / "reports" / "constraint_solution.json"
    output.write_text(solution.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return solution
