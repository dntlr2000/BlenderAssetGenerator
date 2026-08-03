from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import SceneSpec
from ..workspace import job_dir
from .models import (
    AssemblyRelationship,
    AssemblyValidationCheck,
    AssemblyValidationReport,
    AxisAlignmentRelationship,
    AxisClearanceRelationship,
    BBoxContainmentRelationship,
    BilateralPairRelationship,
    CenterPlaneRelationship,
    CoaxialRelationship,
    ModelingPlan,
    SideSpecificRelationship,
    SurfaceContactRelationship,
)

_AXIS = {"X": 0, "Y": 1, "Z": 2}


@dataclass(frozen=True)
class AssemblyBounds:
    """Represent one evaluated semantic instance in the declared assembly frame."""

    instance_index: int
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]
    basis: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] | None = None

    def __post_init__(self) -> None:
        """Reject non-finite, inverted, or degenerate evaluated bounds."""

        values = (*self.minimum, *self.maximum)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Assembly bounds values must be finite")
        if any(self.maximum[index] <= self.minimum[index] for index in range(3)):
            raise ValueError("Assembly bounds must have positive extent on every axis")
        if self.basis is not None:
            if len(self.basis) != 3 or any(len(axis) != 3 for axis in self.basis):
                raise ValueError("Assembly basis must contain three 3D axis vectors")
            if not all(
                math.isfinite(value) for axis in self.basis for value in axis
            ):
                raise ValueError("Assembly basis values must be finite")
            lengths = [math.sqrt(sum(value * value for value in axis)) for axis in self.basis]
            if any(length <= 1.0e-12 for length in lengths):
                raise ValueError("Assembly basis axes must be nonzero")
            normalized = tuple(
                tuple(value / lengths[index] for value in axis)
                for index, axis in enumerate(self.basis)
            )
            if any(
                abs(sum(normalized[left][i] * normalized[right][i] for i in range(3)))
                > 1.0e-5
                for left, right in ((0, 1), (0, 2), (1, 2))
            ):
                raise ValueError("Assembly basis axes must be orthogonal")
            object.__setattr__(self, "basis", normalized)

    @property
    def center(self) -> tuple[float, float, float]:
        """Return the arithmetic center of the evaluated bounds."""

        return tuple(
            (self.minimum[index] + self.maximum[index]) * 0.5
            for index in range(3)
        )

    @property
    def dimensions(self) -> tuple[float, float, float]:
        """Return positive evaluated bounds dimensions."""

        return tuple(
            self.maximum[index] - self.minimum[index] for index in range(3)
        )


def _report(
    plan: ModelingPlan,
    phase: str,
    checks: list[AssemblyValidationCheck],
    notes: list[str] | None = None,
) -> AssemblyValidationReport:
    """Build one counter-consistent assembly report from detailed checks."""

    return AssemblyValidationReport(
        job_id=plan.job_id,
        policy=plan.assembly_consistency_policy,
        phase=phase,
        ok=not any(item.status == "failed" for item in checks),
        passed=sum(item.status == "passed" for item in checks),
        warnings=sum(item.status == "warning" for item in checks),
        failed=sum(item.status == "failed" for item in checks),
        checks=checks,
        notes=notes or [],
    )


def _contract_check(
    *,
    check_id: str,
    passed: bool,
    message: str,
    required: bool = True,
    relation: AssemblyRelationship | None = None,
) -> AssemblyValidationCheck:
    """Create one required failure or optional warning for a prebuild assertion."""

    status = "passed" if passed else ("failed" if required else "warning")
    return AssemblyValidationCheck(
        id=check_id,
        relation_id=relation.id if relation is not None else None,
        kind=relation.kind if relation is not None else "contract",
        status=status,
        required=required,
        evidence_status=(
            relation.evidence_status if relation is not None else None
        ),
        source_ids=(list(relation.source_ids) if relation is not None else []),
        subject_id=relation.subject_id if relation is not None else None,
        reference_id=relation.reference_id if relation is not None else None,
        peer_id=(
            relation.peer_id
            if isinstance(relation, BilateralPairRelationship)
            else None
        ),
        message=message,
    )


def validate_assembly_prebuild_contract(
    plan: ModelingPlan,
    scene_spec: SceneSpec,
) -> AssemblyValidationReport:
    """Validate ModelingPlan assembly identities against one canonical SceneSpec."""

    checks: list[AssemblyValidationCheck] = []
    if plan.assembly_consistency_policy == "legacy_unbound":
        checks.append(
            _contract_check(
                check_id="assembly.policy.legacy_unbound",
                passed=False,
                required=False,
                message=(
                    "Legacy ModelingPlan has no verifiable 3D assembly contract; "
                    "existing geometry remains readable without a spatial claim."
                ),
            )
        )
        return _report(
            plan,
            "prebuild",
            checks,
            ["Legacy plans are not retroactively classified as spatially verified."],
        )

    checks.append(
        _contract_check(
            check_id="assembly.job_id",
            passed=plan.job_id == scene_spec.job_id,
            message=(
                "ModelingPlan and SceneSpec job IDs match."
                if plan.job_id == scene_spec.job_id
                else "ModelingPlan and SceneSpec job IDs differ."
            ),
        )
    )
    plan_ids = {item.id for item in plan.objects}
    scene_ids = {item.id for item in scene_spec.objects}
    checks.append(
        _contract_check(
            check_id="assembly.object_identity",
            passed=plan_ids == scene_ids,
            message=(
                "Assembly ModelingPlan and SceneSpec semantic object IDs match."
                if plan_ids == scene_ids
                else (
                    "Assembly ModelingPlan and SceneSpec object IDs differ; "
                    f"missing_in_scene={sorted(plan_ids - scene_ids)} "
                    f"missing_in_plan={sorted(scene_ids - plan_ids)}"
                )
            ),
        )
    )
    source_ids = {item.id for item in scene_spec.sources}
    frame = plan.assembly_frame
    frame_sources = set(frame.source_ids) if frame is not None else set()
    checks.append(
        _contract_check(
            check_id="assembly.frame_sources",
            passed=not (frame_sources - source_ids),
            message=(
                "Assembly frame source evidence exists in SceneSpec."
                if not (frame_sources - source_ids)
                else (
                    "Assembly frame references missing SceneSpec sources: "
                    f"{sorted(frame_sources - source_ids)}"
                )
            ),
        )
    )
    for relation in plan.assembly_relationships:
        relation_links = {relation.subject_id, relation.reference_id}
        if isinstance(relation, BilateralPairRelationship):
            relation_links.add(relation.peer_id)
        checks.append(
            _contract_check(
                check_id=f"assembly.relationship.{relation.id}.objects",
                passed=not (relation_links - scene_ids),
                required=relation.required,
                relation=relation,
                message=(
                    "Assembly relationship object identities exist in SceneSpec."
                    if not (relation_links - scene_ids)
                    else (
                        "Assembly relationship references missing SceneSpec objects: "
                        f"{sorted(relation_links - scene_ids)}"
                    )
                ),
            )
        )
        missing_sources = set(relation.source_ids) - source_ids
        checks.append(
            _contract_check(
                check_id=f"assembly.relationship.{relation.id}.sources",
                passed=not missing_sources,
                required=relation.required,
                relation=relation,
                message=(
                    "Assembly relationship source evidence exists in SceneSpec."
                    if not missing_sources
                    else (
                        "Assembly relationship references missing SceneSpec sources: "
                        f"{sorted(missing_sources)}"
                    )
                ),
            )
        )
    return _report(plan, "prebuild", checks)


def _union_bounds(bounds: Sequence[AssemblyBounds]) -> AssemblyBounds:
    """Aggregate one semantic family into deterministic assembly-frame bounds."""

    if not bounds:
        raise ValueError("Cannot aggregate an empty assembly-bounds family")
    return AssemblyBounds(
        instance_index=0,
        minimum=tuple(min(item.minimum[index] for item in bounds) for index in range(3)),
        maximum=tuple(max(item.maximum[index] for item in bounds) for index in range(3)),
        basis=bounds[0].basis if len(bounds) == 1 else None,
    )


def _relation_instances(
    relation: AssemblyRelationship,
    bounds_by_id: Mapping[str, Sequence[AssemblyBounds]],
) -> tuple[list[tuple[AssemblyBounds, AssemblyBounds, AssemblyBounds | None]], str | None]:
    """Resolve family, pairwise, or broadcast operands for one relationship."""

    subjects = sorted(
        bounds_by_id.get(relation.subject_id, []),
        key=lambda item: item.instance_index,
    )
    references = sorted(
        bounds_by_id.get(relation.reference_id, []),
        key=lambda item: item.instance_index,
    )
    peers = (
        sorted(
            bounds_by_id.get(relation.peer_id, []),
            key=lambda item: item.instance_index,
        )
        if isinstance(relation, BilateralPairRelationship)
        else []
    )
    missing = [
        object_id
        for object_id, values in (
            (relation.subject_id, subjects),
            (relation.reference_id, references),
            *(
                [(relation.peer_id, peers)]
                if isinstance(relation, BilateralPairRelationship)
                else []
            ),
        )
        if not values
    ]
    if missing:
        return [], f"Evaluated bounds are missing for: {sorted(missing)}"
    if relation.instance_policy == "family_bounds":
        if isinstance(relation, AxisAlignmentRelationship) and (
            len(subjects) != 1 or len(references) != 1
        ):
            return [], (
                "axis_alignment family_bounds requires exactly one concrete subject "
                "and reference instance"
            )
        return [
            (
                _union_bounds(subjects),
                _union_bounds(references),
                _union_bounds(peers) if peers else None,
            )
        ], None
    if relation.instance_policy == "broadcast_reference":
        if isinstance(relation, AxisAlignmentRelationship) and len(references) != 1:
            return [], (
                "axis_alignment broadcast_reference requires exactly one concrete "
                "reference instance"
            )
        reference = _union_bounds(references)
        if isinstance(relation, BilateralPairRelationship):
            if len(subjects) != len(peers):
                return [], "Bilateral broadcast subjects and peers require equal counts"
            return [
                (subject, reference, peer)
                for subject, peer in zip(subjects, peers, strict=True)
            ], None
        return [(subject, reference, None) for subject in subjects], None
    expected_counts = [len(subjects), len(references)]
    if isinstance(relation, BilateralPairRelationship):
        expected_counts.append(len(peers))
    if len(set(expected_counts)) != 1:
        return [], f"Pairwise assembly instance counts differ: {expected_counts}"
    return [
        (
            subjects[index],
            references[index],
            peers[index] if peers else None,
        )
        for index in range(len(subjects))
    ], None


def _axis_residual(
    difference_m: float,
    reference_extent_m: float,
    relation: AssemblyRelationship,
) -> tuple[float, float]:
    """Normalize one metric residual when the relationship uses relative tolerance."""

    if relation.tolerance.mode == "meters":
        return abs(difference_m), relation.tolerance.value
    extent = max(reference_extent_m, 1e-12)
    return abs(difference_m) / extent, relation.tolerance.value


def _normalize_vector(values: Sequence[float]) -> tuple[float, float, float]:
    """Normalize one finite nonzero 3D direction for angular comparison."""

    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("Assembly direction must contain three finite values")
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude <= 1.0e-12:
        raise ValueError("Assembly direction must be nonzero")
    return tuple(value / magnitude for value in values)


def _basis_direction(
    basis: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    values: Sequence[float],
) -> tuple[float, float, float]:
    """Resolve local vector components through an evaluated assembly-frame basis."""

    local = _normalize_vector(values)
    return _normalize_vector(
        tuple(
            sum(local[axis] * basis[axis][component] for axis in range(3))
            for component in range(3)
        )
    )


def _signed_basis_axis(
    basis: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    signed_axis: str,
) -> tuple[float, float, float]:
    """Select one signed local basis direction from a compact +X/-X token."""

    if len(signed_axis) != 2 or signed_axis[0] not in {"+", "-"}:
        raise ValueError(f"Unsupported signed assembly axis: {signed_axis!r}")
    axis_name = signed_axis[1]
    if axis_name not in _AXIS:
        raise ValueError(f"Unsupported signed assembly axis: {signed_axis!r}")
    sign = 1.0 if signed_axis[0] == "+" else -1.0
    return tuple(sign * value for value in basis[_AXIS[axis_name]])


def _angular_error_deg(
    subject_direction: Sequence[float],
    target_direction: Sequence[float],
    *,
    undirected: bool,
) -> float:
    """Return a stable directed or axis-equivalent angle in degrees."""

    subject = _normalize_vector(subject_direction)
    target = _normalize_vector(target_direction)
    dot = sum(subject[index] * target[index] for index in range(3))
    if undirected:
        dot = abs(dot)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _clearance_value(
    value_m: float,
    reference_extent_m: float,
    mode: str,
) -> float:
    """Express one signed clearance in meters or normalized reference extent."""

    if mode == "meters":
        return value_m
    if mode != "relative":
        raise ValueError(f"Unsupported assembly clearance mode: {mode!r}")
    return value_m / max(reference_extent_m, 1.0e-12)


def _transverse_overlap_metrics(
    subject: AssemblyBounds,
    reference: AssemblyBounds,
    contact_axis: int,
    minimum_ratio: float,
) -> tuple[bool, dict[str, Any]]:
    """Measure broad overlap on both axes transverse to a declared contact face."""

    ratios: dict[str, float] = {}
    for axis_name, axis in _AXIS.items():
        if axis == contact_axis:
            continue
        overlap = max(
            0.0,
            min(subject.maximum[axis], reference.maximum[axis])
            - max(subject.minimum[axis], reference.minimum[axis]),
        )
        denominator = max(
            min(subject.dimensions[axis], reference.dimensions[axis]),
            1e-12,
        )
        ratios[axis_name] = overlap / denominator
    return (
        all(value + 1e-12 >= minimum_ratio for value in ratios.values()),
        {
            "transverse_overlap_ratios": {
                key: round(value, 9) for key, value in sorted(ratios.items())
            },
            "min_transverse_overlap_ratio": minimum_ratio,
        },
    )


def _evaluate_pair(
    relation: AssemblyRelationship,
    subject: AssemblyBounds,
    reference: AssemblyBounds,
    peer: AssemblyBounds | None,
) -> tuple[float, float, str, str, dict[str, Any]]:
    """Evaluate one resolved subject/reference pair using its relation semantics."""

    metrics: dict[str, Any] = {
        "scorable": True,
        "bbox_basis": "evaluated_bbox_corners_in_assembly_frame_meters",
        "subject_bbox_assembly_frame": {
            "min": list(subject.minimum),
            "max": list(subject.maximum),
        },
        "reference_bbox_assembly_frame": {
            "min": list(reference.minimum),
            "max": list(reference.maximum),
        },
    }
    if peer is not None:
        metrics["peer_bbox_assembly_frame"] = {
            "min": list(peer.minimum),
            "max": list(peer.maximum),
        }

    if isinstance(relation, CenterPlaneRelationship):
        axis = _AXIS[relation.axis]
        residual, tolerance = _axis_residual(
            subject.center[axis] - reference.center[axis],
            reference.dimensions[axis],
            relation,
        )
        return (
            residual,
            tolerance,
            relation.tolerance.mode,
            f"center_plane axis={relation.axis}",
            metrics,
        )
    if isinstance(relation, CoaxialRelationship):
        residuals = [
            _axis_residual(
                subject.center[_AXIS[axis]] - reference.center[_AXIS[axis]],
                reference.dimensions[_AXIS[axis]],
                relation,
            )[0]
            for axis in relation.axes
        ]
        return (
            max(residuals),
            relation.tolerance.value,
            relation.tolerance.mode,
            f"coaxial axes={relation.axes}",
            metrics,
        )
    if isinstance(relation, BBoxContainmentRelationship):
        overflows: list[float] = []
        for axis_name in relation.axes:
            axis = _AXIS[axis_name]
            overflow = max(
                reference.minimum[axis] - subject.minimum[axis],
                subject.maximum[axis] - reference.maximum[axis],
                0.0,
            )
            overflows.append(
                _axis_residual(
                    overflow,
                    reference.dimensions[axis],
                    relation,
                )[0]
            )
        return (
            max(overflows),
            relation.tolerance.value,
            relation.tolerance.mode,
            f"bbox_containment axes={relation.axes}",
            metrics,
        )
    if isinstance(relation, SurfaceContactRelationship):
        axis = _AXIS[relation.axis]
        subject_value = (
            subject.minimum[axis]
            if relation.subject_side == "MIN"
            else subject.maximum[axis]
        )
        reference_value = (
            reference.minimum[axis]
            if relation.reference_side == "MIN"
            else reference.maximum[axis]
        )
        residual, tolerance = _axis_residual(
            subject_value - reference_value,
            reference.dimensions[axis],
            relation,
        )
        overlap_ok, overlap_metrics = _transverse_overlap_metrics(
            subject,
            reference,
            axis,
            relation.min_transverse_overlap_ratio,
        )
        metrics["signed_surface_delta_m"] = round(subject_value - reference_value, 9)
        metrics["transverse_overlap_ok"] = overlap_ok
        metrics.update(overlap_metrics)
        return (
            residual,
            tolerance,
            relation.tolerance.mode,
            (
                f"surface_contact axis={relation.axis} "
                f"subject={relation.subject_side} reference={relation.reference_side}"
            ),
            metrics,
        )
    if isinstance(relation, SideSpecificRelationship):
        axis = _AXIS[relation.axis]
        signed = subject.center[axis] - reference.center[axis]
        if relation.tolerance.mode == "relative":
            signed /= max(reference.dimensions[axis], 1e-12)
        directed = -signed if relation.side == "MIN" else signed
        residual = max(0.0, relation.tolerance.value - directed)
        metrics["directed_side_distance"] = round(directed, 9)
        return (
            residual,
            0.0,
            relation.tolerance.mode,
            f"side_specific axis={relation.axis} side={relation.side}",
            metrics,
        )
    if isinstance(relation, BilateralPairRelationship):
        if peer is None:
            raise ValueError("Bilateral relationship requires evaluated peer bounds")
        axis = _AXIS[relation.axis]
        center_error = abs(
            (subject.center[axis] - reference.center[axis])
            + (peer.center[axis] - reference.center[axis])
        )
        size_error = abs(subject.dimensions[axis] - peer.dimensions[axis])
        residuals = [
            _axis_residual(error, reference.dimensions[axis], relation)[0]
            for error in (center_error, size_error)
        ]
        return (
            max(residuals),
            relation.tolerance.value,
            relation.tolerance.mode,
            f"bilateral_pair axis={relation.axis} peer={relation.peer_id}",
            metrics,
        )
    if isinstance(relation, AxisAlignmentRelationship):
        if subject.basis is None:
            raise ValueError("Subject evaluated orientation basis is unavailable")
        subject_direction = _signed_basis_axis(subject.basis, relation.subject_axis)
        if relation.target_space == "reference_local":
            if reference.basis is None:
                raise ValueError("Reference evaluated orientation basis is unavailable")
            target_direction = _basis_direction(
                reference.basis,
                relation.target_direction,
            )
        else:
            target_direction = _normalize_vector(relation.target_direction)
        residual = _angular_error_deg(
            subject_direction,
            target_direction,
            undirected=relation.directionality == "undirected",
        )
        metrics.update(
            {
                "evaluation_basis": "evaluated_object_axes_in_assembly_frame",
                "subject_axis": relation.subject_axis,
                "subject_direction_assembly_frame": [
                    round(value, 9) for value in subject_direction
                ],
                "target_direction_assembly_frame": [
                    round(value, 9) for value in target_direction
                ],
                "target_space": relation.target_space,
                "directionality": relation.directionality,
                "angular_error_deg": round(residual, 9),
            }
        )
        return (
            residual,
            relation.angular_tolerance_deg,
            "degrees",
            (
                f"axis_alignment subject_axis={relation.subject_axis} "
                f"target_space={relation.target_space}"
            ),
            metrics,
        )
    if isinstance(relation, AxisClearanceRelationship):
        axis = _AXIS[relation.axis]
        if relation.direction == "POSITIVE":
            gap_m = reference.minimum[axis] - subject.maximum[axis]
        else:
            gap_m = subject.minimum[axis] - reference.maximum[axis]
        mode = relation.minimum_gap.mode
        gap = _clearance_value(gap_m, reference.dimensions[axis], mode)
        minimum = relation.minimum_gap.value
        maximum = (
            relation.maximum_gap.value
            if relation.maximum_gap is not None
            else None
        )
        residual = max(
            minimum - gap,
            (gap - maximum) if maximum is not None else 0.0,
            0.0,
        )
        overlap_ok, overlap_metrics = _transverse_overlap_metrics(
            subject,
            reference,
            axis,
            relation.min_transverse_overlap_ratio,
        )
        metrics.update(overlap_metrics)
        metrics.update(
            {
                "signed_axis_gap_m": round(gap_m, 9),
                "evaluated_gap": round(gap, 9),
                "minimum_gap": minimum,
                "maximum_gap": maximum,
                "clearance_direction": relation.direction,
                "transverse_overlap_ok": overlap_ok,
            }
        )
        return (
            residual,
            relation.tolerance.value,
            mode,
            f"axis_clearance axis={relation.axis} direction={relation.direction}",
            metrics,
        )
    raise TypeError(f"Unsupported assembly relationship: {type(relation)!r}")


def evaluate_assembly_bounds(
    plan: ModelingPlan,
    scene_spec: SceneSpec,
    bounds_by_id: Mapping[str, Sequence[AssemblyBounds]],
) -> AssemblyValidationReport:
    """Evaluate required assembly relations against geometry-derived 3D bounds."""

    contract = validate_assembly_prebuild_contract(plan, scene_spec)
    if plan.assembly_consistency_policy == "legacy_unbound" or not contract.ok:
        return AssemblyValidationReport(
            **{
                **contract.model_dump(mode="python"),
                "phase": "bounds",
            }
        )
    checks = list(contract.checks)
    for relation in plan.assembly_relationships:
        operands, error = _relation_instances(relation, bounds_by_id)
        if error is not None:
            checks.append(
                AssemblyValidationCheck(
                    id=f"assembly.bounds.{relation.id}",
                    relation_id=relation.id,
                    kind=relation.kind,
                    status="failed" if relation.required else "warning",
                    required=relation.required,
                    evidence_status=relation.evidence_status,
                    source_ids=list(relation.source_ids),
                    subject_id=relation.subject_id,
                    reference_id=relation.reference_id,
                    peer_id=(
                        relation.peer_id
                        if isinstance(relation, BilateralPairRelationship)
                        else None
                    ),
                    message=error,
                )
            )
            continue
        for subject, reference, peer in operands:
            try:
                residual, tolerance, mode, description, metrics = _evaluate_pair(
                    relation,
                    subject,
                    reference,
                    peer,
                )
            except (TypeError, ValueError, ZeroDivisionError) as exc:
                checks.append(
                    AssemblyValidationCheck(
                        id=f"assembly.bounds.{relation.id}.{subject.instance_index}",
                        relation_id=relation.id,
                        kind=relation.kind,
                        status="failed" if relation.required else "warning",
                        required=relation.required,
                        evidence_status=relation.evidence_status,
                        source_ids=list(relation.source_ids),
                        subject_id=relation.subject_id,
                        reference_id=relation.reference_id,
                        peer_id=(
                            relation.peer_id
                            if isinstance(relation, BilateralPairRelationship)
                            else None
                        ),
                        instance_index=subject.instance_index,
                        message=f"Assembly relation is unscorable: {exc}",
                        metrics={
                            "scorable": False,
                            "bbox_basis": (
                                "evaluated_bbox_corners_in_assembly_frame_meters"
                            ),
                        },
                    )
                )
                continue
            passed = residual <= tolerance + 1e-12 and bool(
                metrics.get("transverse_overlap_ok", True)
            )
            checks.append(
                AssemblyValidationCheck(
                    id=f"assembly.bounds.{relation.id}.{subject.instance_index}",
                    relation_id=relation.id,
                    kind=relation.kind,
                    status=(
                        "passed"
                        if passed
                        else ("failed" if relation.required else "warning")
                    ),
                    required=relation.required,
                    evidence_status=relation.evidence_status,
                    source_ids=list(relation.source_ids),
                    subject_id=relation.subject_id,
                    reference_id=relation.reference_id,
                    peer_id=(
                        relation.peer_id
                        if isinstance(relation, BilateralPairRelationship)
                        else None
                    ),
                    instance_index=subject.instance_index,
                    residual=round(residual, 9),
                    tolerance=round(tolerance, 9),
                    tolerance_mode=mode,
                    message=(
                        f"{description}: residual={residual:.6g} "
                        f"tolerance={tolerance:.6g} ({mode})"
                    ),
                    metrics=metrics,
                )
            )
    return _report(
        plan,
        "bounds",
        checks,
        [
            "Assembly bounds are geometric consistency evidence, not hidden-side truth.",
            "Relative residuals are normalized by the selected reference-axis extent.",
        ],
    )


def _inventory_bounds(inventory: Mapping[str, Any]) -> dict[str, list[AssemblyBounds]]:
    """Decode explicitly assembly-frame bounds without treating world AABBs as local proof."""

    result: dict[str, list[AssemblyBounds]] = {}
    for record in inventory.get("objects", []):
        if not isinstance(record, dict):
            continue
        object_id = record.get("cbm_id")
        index = record.get("instance_index")
        bbox = record.get("bbox_assembly_frame")
        if object_id is None or index is None or not isinstance(bbox, dict):
            continue
        minimum = bbox.get("min")
        maximum = bbox.get("max")
        if not isinstance(minimum, list) or not isinstance(maximum, list):
            continue
        raw_basis = record.get("basis_assembly_frame")
        basis = None
        if isinstance(raw_basis, list) and len(raw_basis) == 3 and all(
            isinstance(axis, list) and len(axis) == 3 for axis in raw_basis
        ):
            basis = tuple(
                tuple(float(value) for value in axis) for axis in raw_basis
            )
        result.setdefault(str(object_id), []).append(
            AssemblyBounds(
                instance_index=int(index),
                minimum=tuple(float(value) for value in minimum),
                maximum=tuple(float(value) for value in maximum),
                basis=basis,
            )
        )
    return result


def _inventory_bounds_warning(plan: ModelingPlan) -> AssemblyValidationCheck:
    """Report that ordinary world AABBs cannot prove intrinsic assembly alignment."""

    return AssemblyValidationCheck(
        id="assembly.bounds.inventory_unscorable",
        kind="bounds_evidence",
        status="warning",
        required=False,
        message=(
            "Scene inventory has no explicitly assembly-frame bounds; world-space AABBs "
            "are not used because rotated reference geometry can produce false passes. "
            "The Blender runtime assembly validator must provide the bounds verdict."
        ),
    )


def validate_job_assembly(
    job_id: str,
    *,
    inventory_path: Path | None = None,
    write_report: bool = True,
    raise_on_error: bool = False,
) -> AssemblyValidationReport:
    """Validate one job's assembly contract and optional current scene inventory."""

    root = job_dir(job_id)
    plan_path = root / "analysis" / "modeling_plan.json"
    scene_path = root / "analysis" / "scene_spec.json"
    if not plan_path.is_file():
        plan = ModelingPlan(
            job_id=job_id,
            reference_analysis_path="analysis/reference_analysis.json",
            camera_solution_path="analysis/camera_solution.json",
        )
    else:
        plan = ModelingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    scene_spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    resolved_inventory = inventory_path or root / "reports" / "scene_inventory.json"
    if resolved_inventory.is_file():
        inventory = json.loads(resolved_inventory.read_text(encoding="utf-8"))
        bounds = _inventory_bounds(inventory)
        if bounds:
            report = evaluate_assembly_bounds(plan, scene_spec, bounds)
        else:
            prebuild = validate_assembly_prebuild_contract(plan, scene_spec)
            report = _report(
                plan,
                "prebuild",
                [*prebuild.checks, _inventory_bounds_warning(plan)],
                [
                    *prebuild.notes,
                    "Bounds evaluation is deferred to Blender runtime evidence.",
                ],
            )
    else:
        report = validate_assembly_prebuild_contract(plan, scene_spec)
    if write_report:
        output = root / "reports" / "assembly_validation.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if raise_on_error and not report.ok:
        failures = "; ".join(
            item.message for item in report.checks if item.status == "failed"
        )
        raise ValueError(f"Assembly consistency validation failed: {failures}")
    return report


def validate_scene_assembly_contract(scene_spec: SceneSpec, path: Path) -> None:
    """Enforce a job-local ModelingPlan assembly contract during SceneSpec loading."""

    resolved = path.expanduser().resolve()
    if resolved.parent.name != "analysis":
        return
    plan_path = resolved.parent / "modeling_plan.json"
    if not plan_path.is_file():
        return
    plan = ModelingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    report = validate_assembly_prebuild_contract(plan, scene_spec)
    if not report.ok:
        failures = "; ".join(
            item.message for item in report.checks if item.status == "failed"
        )
        raise ValueError(f"Assembly consistency contract failed: {failures}")
