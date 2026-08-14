"""Host-owned, path/hash-only MaterialGraph provenance rebinding helpers."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

from .models import MaterialGraphRebindingChange, MaterialGraphRebindingPlan


def serialize_rebound_material_graph(graph: Mapping[str, Any]) -> bytes:
    """Serialize a rebound graph deterministically for exact planned-output hashing."""

    return (json.dumps(graph, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def rebound_material_graph_sha256(graph: Mapping[str, Any]) -> str:
    """Hash the deterministic bytes used to publish a rebound graph derivative."""

    return hashlib.sha256(serialize_rebound_material_graph(graph)).hexdigest()


def _decode_pointer_token(token: str) -> str:
    """Decode one RFC 6901 JSON Pointer token."""

    return token.replace("~1", "/").replace("~0", "~")


def _pointer_parts(pointer: str) -> list[str]:
    """Split one validated absolute JSON pointer into decoded components."""

    if not pointer.startswith("/"):
        raise ValueError("rebinding pointer must be absolute")
    return [_decode_pointer_token(item) for item in pointer[1:].split("/")]


def _read_pointer(document: object, pointer: str) -> object:
    """Read an existing mapping/list field without permitting implicit creation."""

    current = document
    for part in _pointer_parts(pointer):
        if isinstance(current, Mapping):
            if part not in current:
                raise ValueError(f"rebinding pointer does not exist: {pointer}")
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            if not part.isdecimal() or int(part) >= len(current):
                raise ValueError(f"rebinding pointer index does not exist: {pointer}")
            current = current[int(part)]
        else:
            raise ValueError(f"rebinding pointer traverses a scalar: {pointer}")
    return current


def _write_pointer(document: object, pointer: str, value: str) -> None:
    """Replace one existing leaf without adding structure or changing graph semantics."""

    parts = _pointer_parts(pointer)
    parent = document
    for part in parts[:-1]:
        if isinstance(parent, MutableMapping):
            if part not in parent:
                raise ValueError(f"rebinding pointer does not exist: {pointer}")
            parent = parent[part]
        elif isinstance(parent, list):
            if not part.isdecimal() or int(part) >= len(parent):
                raise ValueError(f"rebinding pointer index does not exist: {pointer}")
            parent = parent[int(part)]
        else:
            raise ValueError(f"rebinding pointer traverses a scalar: {pointer}")
    leaf = parts[-1]
    if isinstance(parent, MutableMapping):
        if leaf not in parent:
            raise ValueError(f"rebinding pointer does not exist: {pointer}")
        parent[leaf] = value
    elif isinstance(parent, list):
        if not leaf.isdecimal() or int(leaf) >= len(parent):
            raise ValueError(f"rebinding pointer index does not exist: {pointer}")
        parent[int(leaf)] = value
    else:
        raise ValueError(f"rebinding pointer parent is a scalar: {pointer}")


def _all_changed_pointers(before: object, after: object, prefix: str = "") -> set[str]:
    """Return every changed leaf pointer to prove that only declared fields changed."""

    if type(before) is not type(after):
        return {prefix or "/"}
    if isinstance(before, Mapping):
        if set(before) != set(after):
            return {prefix or "/"}
        changes: set[str] = set()
        for key in before:
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            changes |= _all_changed_pointers(
                before[key], after[key], f"{prefix}/{escaped}"
            )
        return changes
    if isinstance(before, list):
        if len(before) != len(after):
            return {prefix or "/"}
        changes = set()
        for index, item in enumerate(before):
            changes |= _all_changed_pointers(item, after[index], f"{prefix}/{index}")
        return changes
    return set() if before == after else {prefix or "/"}


def apply_material_graph_rebinding(
    source_graph: Mapping[str, Any],
    plan: MaterialGraphRebindingPlan,
) -> tuple[dict[str, Any], list[MaterialGraphRebindingChange]]:
    """Replay a declared path/hash diff and reject any semantic or undeclared mutation."""

    rebound: dict[str, Any] = copy.deepcopy(dict(source_graph))
    for change in plan.changes:
        before_path = _read_pointer(rebound, change.path_pointer)
        before_hash = _read_pointer(rebound, change.hash_pointer)
        artifact_parent_pointer = change.path_pointer.rsplit("/", 1)[0]
        artifact_parent = _read_pointer(rebound, artifact_parent_pointer)
        if not isinstance(artifact_parent, Mapping) or artifact_parent.get("role") not in {
            "scene_spec",
            "material_plan",
            "shader_recipe",
            "texture",
            "reference",
            "mask",
            "other",
        }:
            raise ValueError(
                "rebinding pointers must target one declared MaterialGraphArtifact"
            )
        if artifact_parent["role"] != change.dependency_role:
            raise ValueError(
                "rebinding dependency role differs from its MaterialGraphArtifact"
            )
        if before_path != change.before_path or before_hash != change.before_sha256:
            raise ValueError(
                f"rebinding source is stale for dependency role {change.dependency_role}"
            )
        _write_pointer(rebound, change.path_pointer, change.after_path)
        _write_pointer(rebound, change.hash_pointer, change.after_sha256)
    allowed = set()
    for change in plan.changes:
        if change.before_path != change.after_path:
            allowed.add(change.path_pointer)
        if change.before_sha256 != change.after_sha256:
            allowed.add(change.hash_pointer)
    changed = _all_changed_pointers(source_graph, rebound)
    if changed != allowed:
        raise ValueError(
            "material graph rebinding changed undeclared fields "
            f"(expected={sorted(allowed)}, observed={sorted(changed)})"
        )
    if rebound_material_graph_sha256(rebound) != plan.expected_rebound_sha256:
        raise ValueError("rebound graph bytes differ from the planned exact hash")
    return rebound, list(plan.changes)


__all__ = [
    "apply_material_graph_rebinding",
    "rebound_material_graph_sha256",
    "serialize_rebound_material_graph",
]
