"""Deterministic constructors for bounded structural component composition."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .models import BooleanOperand, BooleanOperation, BooleanTreeGeometry


def build_balanced_component_union(
    components: Sequence[BooleanOperand | dict[str, Any]],
    *,
    operation_id_prefix: str = "component_union",
    fail_on_non_manifold: bool = True,
) -> BooleanTreeGeometry:
    """Compose two to 32 validated components into one balanced exact-union recipe."""

    if not 2 <= len(components) <= 32:
        raise ValueError("component union requires between two and 32 operands")
    operands = [
        item if isinstance(item, BooleanOperand) else BooleanOperand.model_validate(item)
        for item in components
    ]
    operand_ids = [item.id for item in operands]
    if len(operand_ids) != len(set(operand_ids)):
        raise ValueError("component union operand IDs must be unique")

    available = list(operand_ids)
    operations: list[BooleanOperation] = []
    reserved_ids = set(operand_ids)
    operation_index = 1
    while len(available) > 1:
        next_level: list[str] = []
        for index in range(0, len(available), 2):
            if index + 1 == len(available):
                next_level.append(available[index])
                continue
            operation_id = f"{operation_id_prefix}.{operation_index:02d}"
            if operation_id in reserved_ids:
                raise ValueError(
                    f"component union operation ID collides with an operand: {operation_id}"
                )
            operation = BooleanOperation(
                id=operation_id,
                operation="UNION",
                left_id=available[index],
                right_id=available[index + 1],
                solver="EXACT",
            )
            operations.append(operation)
            reserved_ids.add(operation_id)
            next_level.append(operation_id)
            operation_index += 1
        available = next_level

    return BooleanTreeGeometry(
        operands=operands,
        operations=operations,
        root_id=available[0],
        fail_on_non_manifold=fail_on_non_manifold,
    )
