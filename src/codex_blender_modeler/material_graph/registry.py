"""Semantic-only whitelist registry for the MaterialGraph runtime compiler."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..blender_scripts.material_graph_runtime_registry import (
    LEGACY_REGISTRY_SHA256,
    LEGACY_REGISTRY_SNAPSHOT,
    PUBLIC_TEMPLATE_REGISTRY,
    REGISTRY_SHA256,
    REGISTRY_SNAPSHOT,
    REGISTRY_VERSION,
    SUPPORTED_REGISTRIES_BY_SHA256,
)
from ..blender_scripts.material_graph_runtime_registry import (
    registry_for_sha256 as _registry_for_sha256,
)
from .runtime_models import NormalizedMaterialGraphPlan, RuntimeNodePlan

__all__ = [
    "LEGACY_REGISTRY_SHA256",
    "PUBLIC_TEMPLATE_REGISTRY",
    "REGISTRY_VERSION",
    "MaterialGraphRegistryError",
    "is_supported_registry_sha256",
    "legacy_registry_sha256",
    "legacy_registry_snapshot",
    "registry_sha256",
    "registry_snapshot",
    "supported_registry_sha256s",
    "validate_runtime_plan",
]


class MaterialGraphRegistryError(ValueError):
    """Signal a fail-closed registry or graph-shape violation."""


def registry_snapshot() -> dict[str, object]:
    """Return the current Blender-independent semantic registry snapshot."""

    return REGISTRY_SNAPSHOT


def legacy_registry_snapshot() -> dict[str, object]:
    """Return the exact seven-template v1 snapshot for historical verification."""

    return LEGACY_REGISTRY_SNAPSHOT


def registry_sha256() -> str:
    """Return the current semantic registry digest shared with fixed Blender code."""

    return REGISTRY_SHA256


def legacy_registry_sha256() -> str:
    """Return the exact historical seven-template registry digest."""

    return LEGACY_REGISTRY_SHA256


def supported_registry_sha256s() -> frozenset[str]:
    """Return exact current and legacy registry digests accepted for verification."""

    return frozenset(SUPPORTED_REGISTRIES_BY_SHA256)


def is_supported_registry_sha256(value: str) -> bool:
    """Report whether an exact registry digest is current or preserved legacy data."""

    return value in SUPPORTED_REGISTRIES_BY_SHA256


def _setting_map(node: RuntimeNodePlan) -> dict[str, bool | int | float | str]:
    """Normalize one node's unique typed settings for registry validation."""

    return {item.setting_id: item.value for item in node.settings}


def _validate_setting_value(setting_id: str, value: object, rule: dict[str, Any]) -> None:
    """Validate a semantic setting without evaluating expressions or callbacks."""

    kind = rule["kind"]
    if kind == "enum":
        if not isinstance(value, str) or value not in rule["values"]:
            raise MaterialGraphRegistryError(f"setting {setting_id!r} is outside its semantic enum")
        return
    if kind == "dependency_id":
        if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
            raise MaterialGraphRegistryError(
                f"setting {setting_id!r} must be a portable dependency ID"
            )
        return
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MaterialGraphRegistryError(f"setting {setting_id!r} requires a numeric scalar")
        if not rule["minimum"] <= value <= rule["maximum"]:
            raise MaterialGraphRegistryError(f"setting {setting_id!r} is outside its numeric range")
        return
    if kind == "boolean":
        if not isinstance(value, bool):
            raise MaterialGraphRegistryError(f"setting {setting_id!r} requires a strict boolean")
        return
    raise MaterialGraphRegistryError(f"unsupported registry setting kind: {kind}")


def _socket_type(rule: str | dict[str, Any]) -> str:
    """Read one legacy or bounded-v2 semantic socket type."""

    return rule if isinstance(rule, str) else str(rule["type"])


def _validate_numeric_range(values: tuple[float | int, ...], rule: str | dict[str, Any]) -> None:
    """Reject default components outside a bounded-v2 socket declaration."""

    if isinstance(rule, str):
        return
    minimum = rule.get("minimum")
    maximum = rule.get("maximum")
    if minimum is None or maximum is None:
        return
    if any(not minimum <= item <= maximum for item in values):
        raise MaterialGraphRegistryError("semantic socket default is outside its range")


def _validate_socket_default(rule: str | dict[str, Any], value: object) -> None:
    """Require exact semantic value shapes and reject shader defaults."""

    socket_type = _socket_type(rule)
    if socket_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MaterialGraphRegistryError("float socket requires a numeric scalar")
        _validate_numeric_range((value,), rule)
        return
    expected_length = {"vector": 3, "color": 4}.get(socket_type)
    if expected_length is None:
        raise MaterialGraphRegistryError(f"{socket_type} sockets cannot have defaults")
    if not isinstance(value, (tuple, list)) or len(value) != expected_length:
        raise MaterialGraphRegistryError(
            f"{socket_type} socket requires {expected_length} numeric values"
        )
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise MaterialGraphRegistryError(f"{socket_type} socket requires only numeric values")
    _validate_numeric_range(tuple(value), rule)


def _validate_template_constraints(
    node: RuntimeNodePlan, settings: dict[str, bool | int | float | str]
) -> None:
    """Enforce deterministic relationships that individual setting ranges cannot express."""

    if node.template_id == "color_ramp" and settings["position_0"] >= settings["position_1"]:
        raise MaterialGraphRegistryError("color ramp position_0 must be lower than position_1")


def _validate_node(node: RuntimeNodePlan, templates: dict[str, dict[str, Any]]) -> None:
    """Validate one runtime node against semantic templates and typed controls."""

    template = templates.get(node.template_id)
    if template is None:
        raise MaterialGraphRegistryError(
            f"unknown or forbidden material node template: {node.template_id}"
        )
    settings = _setting_map(node)
    if set(settings) != set(template["settings"]):
        raise MaterialGraphRegistryError(
            f"node {node.node_id} must declare the exact semantic setting set"
        )
    for setting_id, value in settings.items():
        _validate_setting_value(setting_id, value, template["settings"][setting_id])
    _validate_template_constraints(node, settings)
    seen_defaults: set[str] = set()
    for default in node.input_defaults:
        if default.socket_id not in template["inputs"]:
            raise MaterialGraphRegistryError(
                f"node {node.node_id} uses an unknown semantic input socket"
            )
        _validate_socket_default(template["inputs"][default.socket_id], default.value)
        seen_defaults.add(default.socket_id)
    if len(seen_defaults) != len(node.input_defaults):
        raise MaterialGraphRegistryError("duplicate semantic socket default")


def _types_are_compatible(source_type: str, target_type: str) -> bool:
    """Allow only explicit safe semantic socket conversions supported by Blender."""

    return source_type == target_type or (source_type, target_type) == ("color", "float")


def validate_runtime_plan(plan: NormalizedMaterialGraphPlan) -> int:
    """Validate registry use, dependencies, DAG order, and maximum graph depth."""

    templates = _registry_for_sha256(plan.registry_sha256)
    if templates is None:
        raise MaterialGraphRegistryError("runtime registry SHA-256 mismatch")
    if len(plan.nodes) > plan.policy.maximum_nodes:
        raise MaterialGraphRegistryError("runtime node cap exceeded")
    if plan.layer_count > plan.policy.maximum_layers:
        raise MaterialGraphRegistryError("runtime layer cap exceeded")
    if plan.texture_count > plan.policy.maximum_textures:
        raise MaterialGraphRegistryError("runtime texture cap exceeded")

    nodes = {node.node_id: node for node in plan.nodes}
    for node in plan.nodes:
        _validate_node(node, templates)

    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree = {node_id: 0 for node_id in nodes}
    depths = {node_id: 1 for node_id in nodes}
    linked_inputs: set[tuple[str, str]] = set()
    for link in plan.links:
        source = nodes.get(link.source_node_id)
        target = nodes.get(link.target_node_id)
        if source is None or target is None:
            raise MaterialGraphRegistryError("runtime link references an unknown node")
        source_template = templates[source.template_id]
        target_template = templates[target.template_id]
        source_type = source_template["outputs"].get(link.source_socket_id)
        target_rule = target_template["inputs"].get(link.target_socket_id)
        target_type = None if target_rule is None else _socket_type(target_rule)
        if source_type is None or target_type is None:
            raise MaterialGraphRegistryError("runtime link uses an unknown semantic socket")
        if not _types_are_compatible(source_type, target_type):
            raise MaterialGraphRegistryError("runtime link socket types are incompatible")
        target_key = (link.target_node_id, link.target_socket_id)
        if target_key in linked_inputs:
            raise MaterialGraphRegistryError("runtime input socket has multiple links")
        linked_inputs.add(target_key)
        if link.target_node_id not in adjacency[link.source_node_id]:
            adjacency[link.source_node_id].add(link.target_node_id)
            indegree[link.target_node_id] += 1

    ready = sorted(node_id for node_id, value in indegree.items() if value == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target_id in sorted(adjacency[node_id]):
            depths[target_id] = max(depths[target_id], depths[node_id] + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
                ready.sort()
    if len(order) != len(nodes):
        raise MaterialGraphRegistryError("runtime graph contains a cycle")
    if order != list(plan.topological_order):
        raise MaterialGraphRegistryError("runtime topological order is not canonical")
    maximum_depth = max(depths.values(), default=0)
    if maximum_depth > plan.policy.maximum_depth:
        raise MaterialGraphRegistryError("runtime graph depth cap exceeded")
    return maximum_depth
