"""Reference-content scope contracts shared by job creation, authoring, and QA."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .analysis.models import ModelingPlan
    from .models import SceneSpec

ReferenceContentScope = Literal["primary_object_only", "full_reference"]
REFERENCE_CONTENT_SCOPES = {"primary_object_only", "full_reference"}
_PRIMARY_TAGS = {"qa_role:primary", "role:primary"}
_SUPPORTING_TAGS = {"qa_role:supporting", "role:supporting"}
_CONTEXT_TAGS = {
    "qa_role:decorative",
    "role:decorative",
    "qa_role:ground_background",
    "role:ground_background",
    "qa_role:ground",
    "role:ground",
    "qa_role:background",
    "role:background",
}


def normalize_reference_content_scope(
    scope: str | None,
    target_subject: str | None,
) -> tuple[ReferenceContentScope, str | None]:
    """Validate one immutable modeling-content choice and its optional subject label."""

    normalized_scope = str(scope or "full_reference").strip().lower()
    if normalized_scope not in REFERENCE_CONTENT_SCOPES:
        raise ValueError(
            "reference_content_scope must be primary_object_only or full_reference"
        )
    normalized_target = (
        str(target_subject).strip() if target_subject is not None else None
    )
    if normalized_target == "":
        normalized_target = None
    if normalized_target is not None and len(normalized_target) > 256:
        raise ValueError("target_subject must contain at most 256 characters")
    if normalized_scope == "primary_object_only" and normalized_target is None:
        raise ValueError(
            "primary_object_only requires an explicit target_subject"
        )
    return normalized_scope, normalized_target  # type: ignore[return-value]


def reference_content_scope_from_metadata(
    metadata: dict[str, object],
) -> tuple[ReferenceContentScope, str | None]:
    """Read a job's immutable content scope while preserving legacy full-scene jobs."""

    return normalize_reference_content_scope(
        str(metadata.get("reference_content_scope", "full_reference")),
        (
            str(metadata["target_subject"])
            if metadata.get("target_subject") is not None
            else None
        ),
    )


def validate_modeling_plan_content_scope(
    plan: ModelingPlan,
    *,
    scope: ReferenceContentScope,
    target_subject: str | None,
) -> None:
    """Reject authored object-only plans that contain context or ambiguous roles."""

    if scope != "primary_object_only" or plan.stage != "authored":
        return
    invalid = [
        item.id
        for item in plan.objects
        if item.scope_role not in {"primary", "supporting"}
    ]
    if invalid:
        raise ValueError(
            "primary_object_only modeling plans require every object to declare "
            f"scope_role=primary or supporting; invalid objects: {invalid}"
        )
    if not any(item.scope_role == "primary" for item in plan.objects):
        raise ValueError(
            "primary_object_only modeling plans require at least one primary object"
        )
    if target_subject is None:
        raise ValueError("primary_object_only modeling plan has no target_subject")


def _explicit_scene_role(tags: list[str]) -> str | None:
    """Resolve one explicit subject/context role from normalized SceneSpec tags."""

    normalized = {str(tag).strip().lower() for tag in tags}
    roles: set[str] = set()
    if normalized & _PRIMARY_TAGS:
        roles.add("primary")
    if normalized & _SUPPORTING_TAGS:
        roles.add("supporting")
    if normalized & _CONTEXT_TAGS:
        roles.add("context")
    if len(roles) > 1:
        raise ValueError("SceneSpec object declares conflicting content-role tags")
    return next(iter(roles), None)


def validate_scene_content_scope(
    spec: SceneSpec,
    *,
    scope: ReferenceContentScope,
    target_subject: str | None,
) -> None:
    """Fail closed when an object-only SceneSpec includes surrounding scene geometry."""

    if scope != "primary_object_only":
        return
    roles: dict[str, str | None] = {}
    for item in spec.objects:
        try:
            roles[item.id] = _explicit_scene_role(list(item.tags))
        except ValueError as exc:
            raise ValueError(f"{item.id}: {exc}") from exc
    missing = sorted(
        identifier for identifier, role in roles.items() if role is None
    )
    context = sorted(
        identifier for identifier, role in roles.items() if role == "context"
    )
    if missing:
        raise ValueError(
            "primary_object_only requires every SceneSpec object to declare an "
            f"explicit primary/supporting QA role; missing: {missing}"
        )
    if context:
        raise ValueError(
            "primary_object_only forbids independent terrain, ground, decoration, "
            f"and background objects: {context}"
        )
    if not any(role == "primary" for role in roles.values()):
        raise ValueError(
            "primary_object_only SceneSpec requires at least one qa_role:primary object"
        )
    if target_subject is None:
        raise ValueError("primary_object_only SceneSpec has no target_subject")


def subject_object_ids(spec: SceneSpec) -> set[str]:
    """Return explicitly scoped primary/supporting IDs for subject-only QA masks."""

    selected: set[str] = set()
    for item in spec.objects:
        role = _explicit_scene_role(list(item.tags))
        if role in {"primary", "supporting"}:
            selected.add(item.id)
    return selected
