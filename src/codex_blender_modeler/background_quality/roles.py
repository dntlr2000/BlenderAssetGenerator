from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from ..models import ObjectSpec, SceneSpec
from ..workspace import sha256_file
from .models import BackgroundRoleAssignment, BackgroundRoleMap, ObjectRole

_EXPLICIT_TAGS: dict[str, ObjectRole] = {
    "qa_role:primary": "primary",
    "role:primary": "primary",
    "qa_role:supporting": "supporting",
    "role:supporting": "supporting",
    "qa_role:decorative": "decorative",
    "role:decorative": "decorative",
    "qa_role:ground_background": "ground_background",
    "role:ground_background": "ground_background",
    "qa_role:ground": "ground_background",
    "role:ground": "ground_background",
    "qa_role:background": "ground_background",
    "role:background": "ground_background",
}
_GROUND_TOKENS = {
    "background",
    "backdrop",
    "ground",
    "seabed",
    "terrain",
    "floor_plane",
    "base_plane",
}
_DECORATIVE_TOKENS = {
    "rock",
    "rocks",
    "foliage",
    "plant",
    "grass",
    "coral",
    "vine",
    "vines",
    "growth",
    "debris",
    "rubble",
    "ornament",
    "decoration",
    "seaweed",
}
_SUPPORTING_TOKENS = {
    "wheel",
    "hub",
    "bumper",
    "door",
    "window",
    "roof",
    "hood",
    "trunk",
    "handle",
    "grille",
    "headlamp",
    "lamp",
    "mirror",
    "trim",
    "rocker",
    "intake",
    "plate",
    "badge",
    "stair",
    "column",
    "pillar",
}
_PRIMARY_TOKENS = {
    "body",
    "hull",
    "cabin",
    "building",
    "house",
    "tower",
    "temple",
    "vehicle",
    "structure",
    "main",
}


def _tokens(item: ObjectSpec) -> set[str]:
    """Normalize semantic-ID segments and tags into one deterministic token set."""

    values = [*item.id.replace("-", ".").split("."), *item.tags]
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _explicit_role(item: ObjectSpec) -> ObjectRole | None:
    """Resolve an explicit SceneSpec role tag before applying any fallback rule."""

    normalized = {str(tag).strip().lower() for tag in item.tags}
    matches = {_EXPLICIT_TAGS[tag] for tag in normalized if tag in _EXPLICIT_TAGS}
    if len(matches) > 1:
        raise ValueError(f"Object {item.id} declares conflicting QA role tags")
    return next(iter(matches), None)


def _semantic_role(item: ObjectSpec) -> tuple[ObjectRole | None, str]:
    """Classify common primary, supporting, decoration, and background namespaces."""

    tokens = _tokens(item)
    if tokens & _DECORATIVE_TOKENS:
        return "decorative", "decorative/environment semantic token"
    if tokens & _GROUND_TOKENS:
        return "ground_background", "ground/background semantic token"
    if tokens & _SUPPORTING_TOKENS:
        return "supporting", "supporting-part semantic token"
    if tokens & _PRIMARY_TOKENS:
        return "primary", "primary-asset semantic token"
    return None, "no deterministic semantic role token"


def _observed_area(item: ObjectSpec) -> float:
    """Return the largest observed normalized reference area for fallback selection."""

    areas = [
        max(0.0, evidence.bbox_norm[2] - evidence.bbox_norm[0])
        * max(0.0, evidence.bbox_norm[3] - evidence.bbox_norm[1])
        for evidence in item.evidence
        if evidence.status == "observed"
    ]
    return max(areas, default=0.0)


def _namespace(identifier: str) -> str:
    """Return the top-level semantic namespace used by the conservative fallback."""

    return identifier.split(".", 1)[0]


def derive_background_role_map(
    scene_spec_path: Path,
    *,
    job_id: str,
    workflow_id: str,
) -> BackgroundRoleMap:
    """Derive a run-owned role map without changing SceneSpec 0.2.0."""

    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    if spec.job_id != job_id:
        raise ValueError("role-map SceneSpec job_id does not match the workflow job")

    resolved: dict[str, tuple[ObjectRole, str, str]] = {}
    unresolved: list[ObjectSpec] = []
    for item in spec.objects:
        explicit = _explicit_role(item)
        if explicit is not None:
            resolved[item.id] = (
                explicit,
                "explicit_tag",
                "SceneSpec declares an explicit QA role tag.",
            )
            continue
        role, reason = _semantic_role(item)
        if role is not None:
            resolved[item.id] = (role, "semantic_rule", reason)
        else:
            unresolved.append(item)

    remaining: list[ObjectSpec] = []
    for item in unresolved:
        parent = resolved.get(str(item.parent_id)) if item.parent_id else None
        if parent is not None and parent[0] in {"primary", "supporting"}:
            resolved[item.id] = (
                "supporting",
                "parent_rule",
                f"Parent {item.parent_id} is part of the primary subject.",
            )
        else:
            remaining.append(item)

    if not any(role == "primary" for role, _source, _reason in resolved.values()):
        candidates = [
            item
            for item in spec.objects
            if resolved.get(item.id, (None, "", ""))[0]
            not in {"ground_background", "decorative"}
        ]
        selected = max(
            candidates or list(spec.objects),
            key=lambda item: (_observed_area(item), item.id),
            default=None,
        )
        if selected is not None:
            resolved[selected.id] = (
                "primary",
                "largest_observed_fallback",
                "No explicit primary existed; selected the largest observed semantic region.",
            )
            remaining = [item for item in remaining if item.id != selected.id]

    primary_namespaces = {
        _namespace(identifier)
        for identifier, (role, _source, _reason) in resolved.items()
        if role == "primary"
    }
    for item in remaining:
        role: ObjectRole = (
            "supporting"
            if _namespace(item.id) in primary_namespaces
            else "decorative"
        )
        resolved[item.id] = (
            role,
            "namespace_fallback",
            (
                "Unclassified object shares the primary semantic namespace."
                if role == "supporting"
                else "Unclassified object is treated as non-blocking decoration."
            ),
        )

    assignments = [
        BackgroundRoleAssignment(
            object_id=item.id,
            role=resolved[item.id][0],
            source=resolved[item.id][1],  # type: ignore[arg-type]
            tags=[str(tag) for tag in item.tags],
            reason=resolved[item.id][2],
        )
        for item in sorted(spec.objects, key=lambda value: value.id)
    ]
    return BackgroundRoleMap(
        job_id=job_id,
        workflow_id=workflow_id,
        scene_spec_sha256=sha256_file(scene_spec_path),
        assignments=assignments,
        generated_at=datetime.now(UTC),
    )


def assignment_roles(role_map: BackgroundRoleMap) -> dict[str, ObjectRole]:
    """Return an object-ID lookup for fit and final quality evaluation."""

    return {item.object_id: item.role for item in role_map.assignments}


def observed_role_bbox(
    spec: SceneSpec,
    roles: dict[str, ObjectRole],
    selected_roles: Iterable[ObjectRole],
) -> tuple[float, float, float, float] | None:
    """Union reliable observed evidence boxes for the requested QA roles."""

    allowed = set(selected_roles)
    boxes = [
        evidence.bbox_norm
        for item in spec.objects
        if roles.get(item.id) in allowed
        for evidence in item.evidence
        if evidence.status == "observed" and evidence.confidence >= 0.5
    ]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
