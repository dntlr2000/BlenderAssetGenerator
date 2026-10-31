"""Strict stdlib-only selection validation for the additive closed-solid root-ball domain."""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

KIND = "solid_root_attachment_intent"
REGISTRATION_KIND = "solid_root_attachment_registration"
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _number(value: Any, label: str) -> Fraction:
    """Accept only bounded finite numeric JSON values without coercion."""
    if type(value) not in (int, float) or not -1e6 <= value <= 1e6 or not math.isfinite(value):
        raise ValueError(f"invalid solid-root {label}")
    return Fraction(value)


def _point(value: Any, label: str) -> tuple[Fraction, ...]:
    """Validate one exact three-coordinate point."""
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"invalid solid-root {label}")
    return tuple(_number(x, label) for x in value)


def _identity(value: Any) -> None:
    """Reject unknown semantic/connection identity forms."""
    if not isinstance(value, str) or IDENTITY.fullmatch(value) is None:
        raise ValueError("invalid solid-root identity")


def _artifact(value: Any) -> None:
    """Require an exact normalized path/digest pair; contained reads rehash it later."""
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError("invalid solid-root artifact")
    path, digest = value["path"], value["sha256"]
    if (
        not isinstance(path, str)
        or not 1 <= len(path) <= 1024
        or path.startswith("/")
        or any(x in path for x in ("\\", ":", "\x00"))
        or any(x in ("", ".", "..") for x in path.split("/"))
        or not isinstance(digest, str)
        or re.fullmatch(r"[a-f0-9]{64}", digest) is None
    ):
        raise ValueError("invalid solid-root artifact path/digest")


def validate_solid_root_contract(payload: Any) -> None:
    """Validate the complete explicit selector without geometry or native authority."""
    keys = {
        "schema_version",
        "contract_kind",
        "job_id",
        "source_reference",
        "source_modeling_plan",
        "source_scene",
        "source_geometry",
        "source_camera_hypothesis",
        "minimum_radius_m",
        "radius_basis",
        "required_semantics",
        "entries",
    }
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if version == "0.2.0":
        keys.add("source_triangle_views")
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("solid-root intent has unknown or missing fields")
    if version not in {"0.1.0", "0.2.0"} or payload["contract_kind"] != KIND:
        raise ValueError("unsupported solid-root intent")
    _identity(payload["job_id"])
    for key in (
        "source_reference",
        "source_modeling_plan",
        "source_scene",
        "source_camera_hypothesis",
    ):
        _artifact(payload[key])
    geometry = payload["source_geometry"]
    if not isinstance(geometry, list) or not 2 <= len(geometry) <= 128:
        raise ValueError("solid-root geometry list is outside limits")
    for artifact in geometry:
        _artifact(artifact)
    if len({x["path"] for x in geometry}) != len(geometry):
        raise ValueError("solid-root geometry repeats a path")
    if version == "0.2.0":
        views = payload["source_triangle_views"]
        if not isinstance(views, list) or len(views) != len(geometry):
            raise ValueError("solid-root triangle views must cover every source")
        for view in views:
            _artifact(view)
        paths = [item["path"] for item in [*geometry, *views]]
        if len(paths) != len(set(paths)):
            raise ValueError("solid-root triangle views repeat or alias a source")
    minimum = _number(payload["minimum_radius_m"], "minimum radius")
    if minimum <= 0:
        raise ValueError("solid-root minimum radius must be positive")
    basis = payload["radius_basis"]
    if not isinstance(basis, str) or not 1 <= len(basis.strip()) <= 2000:
        raise ValueError("solid-root radius needs a bounded authored rationale")
    semantics = payload["required_semantics"]
    if not isinstance(semantics, list) or not 2 <= len(semantics) <= 128:
        raise ValueError("solid-root required semantic list is outside limits")
    for semantic in semantics:
        _identity(semantic)
    if len(set(semantics)) != len(semantics):
        raise ValueError("solid-root required semantics repeat")
    graph: dict[str, set[str]] = {x: set() for x in semantics}
    entries = payload["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 256:
        raise ValueError("solid-root entries are outside limits")
    ids: set[str] = set()
    entry_keys = {
        "attachment_id",
        "scope",
        "owner_semantic_id",
        "subject_semantic_id",
        "joint_description",
        "center",
        "radius_m",
        "root_bounds",
    }
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != entry_keys:
            raise ValueError("solid-root entry has unknown or missing fields")
        for key in ("attachment_id", "owner_semantic_id", "subject_semantic_id"):
            _identity(entry[key])
        if entry["attachment_id"] in ids or entry["scope"] != "required_local_overlap_ball":
            raise ValueError("solid-root entry repeats or has unsupported scope")
        ids.add(entry["attachment_id"])
        owner, subject = entry["owner_semantic_id"], entry["subject_semantic_id"]
        if owner == subject or owner not in graph or subject not in graph:
            raise ValueError("solid-root relation uses unknown or identical solids")
        graph[owner].add(subject)
        graph[subject].add(owner)
        description = entry["joint_description"]
        if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1000:
            raise ValueError("solid-root relation lacks an intended semantic joint description")
        center = _point(entry["center"], "center")
        radius = _number(entry["radius_m"], "radius")
        if radius < minimum:
            raise ValueError("solid-root radius is below its immutable declared minimum")
        bounds = entry["root_bounds"]
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError("solid-root region must be one axis-aligned box")
        low, high = (_point(x, "region") for x in bounds)
        if any(not low[k] <= center[k] - radius <= center[k] + radius <= high[k] for k in range(3)):
            raise ValueError("entire solid-root ball must lie within the intended joint region")
    pending, seen = [semantics[0]], set()
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(graph[current] - seen)
    if seen != set(semantics):
        raise ValueError("solid-root required graph is disconnected")
