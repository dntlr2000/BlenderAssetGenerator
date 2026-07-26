from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..blender_artifacts import write_json_atomic
from ..constraints.models import ConstraintSet
from ..models import ObjectSpec, SceneSpec
from ..workspace import job_dir, load_job, sha256_file
from .models import InteriorScope, InteriorScopeApproval, InteriorScopeValidation

SCOPE_RELATIVE_PATH = Path("architecture/interior_scope.json")
APPROVAL_RELATIVE_PATH = Path("architecture/interior_scope.approval.json")
REPORT_RELATIVE_PATH = Path("reports/interior_scope_validation.json")

_INTERIOR_TAGS = {
    "interior",
    "room",
    "corridor",
    "interior_wall",
    "interior_floor",
    "interior_ceiling",
    "interior_stair",
    "interior_furniture",
}
_INTERIOR_ID_SEGMENTS = {
    "interior",
    "room",
    "rooms",
    "corridor",
    "hallway",
    "lobby",
    "foyer",
    "stairwell",
    "basement",
    "cellar",
    "attic",
}
_FURNITURE_TAGS = {"interior_furniture", "interior:furniture", "furnishing"}
_DETAILED_FURNITURE_TAGS = {
    "furnishing:detailed",
    "interior:furniture:detailed",
    "furniture:detailed",
}


def _utc_now() -> str:
    """Return one timezone-aware timestamp for versioned interior receipts."""

    return datetime.now(UTC).isoformat()


def _prefix_matches(object_id: str, prefix: str) -> bool:
    """Match one semantic prefix only at a dot-delimited ID boundary."""

    return object_id == prefix or object_id.startswith(f"{prefix}.")


def _is_interior_object(obj: ObjectSpec) -> bool:
    """Classify normalized interior tags and common dot-delimited room namespaces."""

    tags = {tag.strip().lower() for tag in obj.tags}
    tagged = bool(tags.intersection(_INTERIOR_TAGS)) or any(
        tag.startswith("interior:") for tag in tags
    )
    id_parts = {part.strip().lower() for part in obj.id.split(".")}
    return tagged or bool(id_parts.intersection(_INTERIOR_ID_SEGMENTS))


def list_interior_objects(scene_spec: SceneSpec) -> list[ObjectSpec]:
    """Return canonical objects that the shared InteriorScope classifier treats as interior."""

    return [obj for obj in scene_spec.objects if _is_interior_object(obj)]


def _load_approval(path: Path) -> InteriorScopeApproval | None:
    """Load an optional strict approval receipt from one job workspace."""

    if not path.is_file():
        return None
    return InteriorScopeApproval.model_validate_json(path.read_text(encoding="utf-8"))


def _measured_constraint_targets(
    job_root: Path,
    job_id: str,
) -> tuple[set[str], str | None]:
    """Load enabled measured target IDs or return one deterministic contract error."""

    path = job_root / "constraints" / "constraints.json"
    if not path.is_file():
        return set(), f"Measured interior scope requires constraints: {path}"
    try:
        contract = ConstraintSet.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return set(), f"Measured interior constraints are invalid: {exc}"
    if contract.job_id != job_id:
        return (
            set(),
            f"Measured interior constraint job_id {contract.job_id!r} does not match "
            f"{job_id!r}",
        )
    targets: set[str] = set()
    for constraint in contract.constraints:
        if not constraint.enabled:
            continue
        if hasattr(constraint, "target_id"):
            targets.add(str(constraint.target_id))
        if hasattr(constraint, "object_a"):
            targets.add(str(constraint.object_a))
            targets.add(str(constraint.object_b))
        if hasattr(constraint, "object_ids"):
            targets.update(str(value) for value in constraint.object_ids)
    return targets, None


def load_interior_scope(job_root: Path) -> InteriorScope | None:
    """Load an explicit scope while leaving absent legacy jobs synthetically disabled."""

    path = job_root.expanduser().resolve() / SCOPE_RELATIVE_PATH
    if not path.is_file():
        return None
    return InteriorScope.model_validate_json(path.read_text(encoding="utf-8"))


def _archive_contract(path: Path, history_root: Path) -> Path | None:
    """Archive one replaced scope or approval without deleting its audit evidence."""

    if not path.is_file():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = history_root / f"{stamp}_{path.name}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def initialize_interior_scope(
    job_id: str,
    *,
    policy: str = "disabled",
    request: str = "",
    allowed_semantic_prefixes: list[str] | None = None,
    excluded_semantic_prefixes: list[str] | None = None,
    levels: list[str] | None = None,
    spaces: list[str] | None = None,
    furnishing: str = "none",
    evidence_status: str = "not_applicable",
    assumptions: list[str] | None = None,
    notes: list[str] | None = None,
    overwrite: bool = False,
) -> InteriorScope:
    """Create or explicitly replace one opt-in interior boundary without editing SceneSpec."""

    load_job(job_id)
    root = job_dir(job_id)
    scope_path = root / SCOPE_RELATIVE_PATH
    approval_path = root / APPROVAL_RELATIVE_PATH
    if scope_path.exists() and not overwrite:
        raise FileExistsError(
            f"Interior scope already exists and was not modified: {scope_path}. "
            "Use overwrite=True only after explicitly reviewing the replacement scope."
        )
    scope = InteriorScope.model_validate(
        {
            "job_id": job_id,
            "policy": policy,
            "request": request,
            "allowed_semantic_prefixes": allowed_semantic_prefixes or [],
            "excluded_semantic_prefixes": excluded_semantic_prefixes or [],
            "levels": levels or [],
            "spaces": spaces or [],
            "furnishing": furnishing,
            "evidence_status": evidence_status,
            "assumptions": assumptions or [],
            "notes": notes or [],
            "created_at": _utc_now(),
        }
    )
    if scope_path.exists():
        history_root = root / "history" / "architecture"
        _archive_contract(scope_path, history_root)
        _archive_contract(approval_path, history_root)
    write_json_atomic(scope_path, scope.model_dump(mode="json"))
    return scope


def approve_interior_scope(
    job_id: str,
    *,
    scope_sha256: str,
    approval_note: str,
    manual_confirmation: bool,
) -> InteriorScopeApproval:
    """Record a manually confirmed exact scope and reject noninteractive callers."""

    if not manual_confirmation:
        raise PermissionError(
            "Interior scope approval requires the interactive CLI confirmation flow"
        )
    load_job(job_id)
    root = job_dir(job_id)
    scope_path = root / SCOPE_RELATIVE_PATH
    if not scope_path.is_file():
        raise FileNotFoundError(f"Interior scope does not exist: {scope_path}")
    scope = InteriorScope.model_validate_json(scope_path.read_text(encoding="utf-8"))
    actual_hash = sha256_file(scope_path)
    if actual_hash != scope_sha256:
        raise ValueError(
            "Interior approval hash does not match the current scope: "
            f"expected={actual_hash} supplied={scope_sha256}"
        )
    if scope.job_id != job_id:
        raise ValueError(f"Interior scope job_id {scope.job_id!r} does not match {job_id!r}")
    if scope.policy == "disabled":
        raise ValueError("Disabled interior scope cannot be approved")
    approval = InteriorScopeApproval(
        approval_id=f"interior-{uuid4().hex}",
        job_id=job_id,
        scope_sha256=actual_hash,
        approved_policy=scope.policy,
        approved_semantic_prefixes=scope.allowed_semantic_prefixes,
        excluded_semantic_prefixes=scope.excluded_semantic_prefixes,
        approved_levels=scope.levels,
        approved_spaces=scope.spaces,
        furnishing=scope.furnishing,
        approved_at=_utc_now(),
        approval_note=approval_note,
    )
    approval_path = root / APPROVAL_RELATIVE_PATH
    if approval_path.is_file():
        _archive_contract(approval_path, root / "history" / "architecture")
    write_json_atomic(approval_path, approval.model_dump(mode="json"))
    return approval


def _approval_matches_scope(
    approval: InteriorScopeApproval | None,
    scope: InteriorScope,
    scope_hash: str,
) -> bool:
    """Verify an approval's job, hash, state, and complete authorization snapshot."""

    if approval is None or approval.status != "approved":
        return False
    return (
        approval.job_id == scope.job_id
        and approval.scope_sha256 == scope_hash
        and approval.approved_policy == scope.policy
        and approval.approved_semantic_prefixes == scope.allowed_semantic_prefixes
        and approval.excluded_semantic_prefixes == scope.excluded_semantic_prefixes
        and approval.approved_levels == scope.levels
        and approval.approved_spaces == scope.spaces
        and approval.furnishing == scope.furnishing
    )


def validate_scene_interior_scope(
    scene_spec: SceneSpec,
    job_root: Path,
    *,
    write_report: bool = False,
) -> InteriorScopeValidation:
    """Cross-check explicit interior objects against the current scope and user approval."""

    root = job_root.expanduser().resolve()
    scope_path = root / SCOPE_RELATIVE_PATH
    approval_path = root / APPROVAL_RELATIVE_PATH
    scope = load_interior_scope(root)
    approval = _load_approval(approval_path)
    scope_hash = sha256_file(scope_path) if scope_path.is_file() else None
    approval_hash = sha256_file(approval_path) if approval_path.is_file() else None
    interior_objects = list_interior_objects(scene_spec)
    errors: list[str] = []
    warnings: list[str] = []

    if scope is None:
        effective_policy = "disabled"
        scope_state = "default_disabled"
        approval_valid = False
    else:
        if scope.job_id != scene_spec.job_id:
            errors.append(
                f"Interior scope job_id {scope.job_id!r} does not match SceneSpec "
                f"{scene_spec.job_id!r}"
            )
        effective_policy = scope.policy
        approval_valid = bool(
            scope.job_id == scene_spec.job_id
            and scope_hash
            and _approval_matches_scope(approval, scope, scope_hash)
        )
        if scope.policy == "disabled":
            scope_state = "explicit_disabled"
        elif approval is not None and approval.status == "revoked":
            scope_state = "revoked"
        elif approval is None:
            scope_state = "draft"
        elif approval_valid:
            scope_state = "approved"
        else:
            scope_state = "stale"

    if interior_objects and effective_policy == "disabled":
        errors.append(
            "Interior objects are forbidden by the default/explicit disabled policy: "
            + ", ".join(obj.id for obj in interior_objects)
        )
    elif interior_objects and not approval_valid:
        errors.append(
            "Interior objects require a matching user-approved scope: "
            + ", ".join(obj.id for obj in interior_objects)
        )

    if scope is not None and approval_valid:
        if scope.policy == "measured" and scene_spec.mode != "measured":
            errors.append("Measured interior scope requires SceneSpec mode='measured'")
        if scope.policy == "measured" and interior_objects:
            measured_targets, measured_error = _measured_constraint_targets(
                root,
                scene_spec.job_id,
            )
            if measured_error:
                errors.append(measured_error)
            else:
                for prefix in scope.allowed_semantic_prefixes:
                    if not any(
                        _prefix_matches(target, prefix)
                        or _prefix_matches(prefix, target)
                        for target in measured_targets
                    ):
                        errors.append(
                            "Measured interior prefix has no enabled constraint target: "
                            f"{prefix}"
                        )
        for obj in interior_objects:
            if any(
                _prefix_matches(obj.id, prefix)
                for prefix in scope.excluded_semantic_prefixes
            ):
                errors.append(f"Interior object is inside an excluded semantic prefix: {obj.id}")
                continue
            if not any(
                _prefix_matches(obj.id, prefix)
                for prefix in scope.allowed_semantic_prefixes
            ):
                errors.append(f"Interior object is outside approved semantic prefixes: {obj.id}")
            level_tags = {
                tag.removeprefix("level:")
                for tag in obj.tags
                if tag.startswith("level:")
            }
            space_tags = {
                tag.removeprefix("space:")
                for tag in obj.tags
                if tag.startswith("space:")
            }
            if scope.levels and not level_tags:
                errors.append(f"Interior object is missing a level:<id> locator tag: {obj.id}")
            if scope.spaces and not space_tags:
                errors.append(f"Interior object is missing a space:<id> locator tag: {obj.id}")
            unknown_levels = sorted(level_tags - set(scope.levels))
            unknown_spaces = sorted(space_tags - set(scope.spaces))
            if unknown_levels:
                errors.append(f"Interior object {obj.id} uses unapproved levels: {unknown_levels}")
            if unknown_spaces:
                errors.append(f"Interior object {obj.id} uses unapproved spaces: {unknown_spaces}")
            normalized_tags = {tag.strip().lower() for tag in obj.tags}
            if scope.furnishing == "none" and normalized_tags.intersection(
                _FURNITURE_TAGS
            ):
                errors.append(f"Interior furnishing is not approved for object: {obj.id}")
            if scope.furnishing == "proxy" and normalized_tags.intersection(
                _DETAILED_FURNITURE_TAGS
            ):
                errors.append(
                    f"Detailed interior furnishing exceeds proxy approval: {obj.id}"
                )
            if scope.policy == "visible_only":
                if not obj.evidence:
                    errors.append(
                        f"Visible-only interior object has no observed evidence: {obj.id}"
                    )
                elif any(evidence.status != "observed" for evidence in obj.evidence):
                    errors.append(
                        f"Visible-only interior object has inferred evidence: {obj.id}"
                    )
            if scope.policy == "measured":
                if not obj.evidence:
                    errors.append(f"Measured interior object has no source evidence: {obj.id}")
                elif any(evidence.status != "observed" for evidence in obj.evidence):
                    errors.append(
                        f"Measured interior object has inferred source evidence: {obj.id}"
                    )

    if scope is not None and scope.policy != "disabled" and not interior_objects:
        warnings.append(
            "Interior scope is enabled but SceneSpec currently contains no interior objects"
        )

    report = InteriorScopeValidation(
        job_id=scene_spec.job_id,
        ok=not errors,
        effective_policy=effective_policy,
        scope_state=scope_state,
        scope_present=scope is not None,
        approval_present=approval is not None,
        approval_valid=approval_valid,
        scope_sha256=scope_hash,
        approval_sha256=approval_hash,
        interior_object_ids=[obj.id for obj in interior_objects],
        errors=errors,
        warnings=warnings,
    )
    if write_report:
        write_json_atomic(root / REPORT_RELATIVE_PATH, report.model_dump(mode="json"))
    return report


def validate_job_interior_scope(
    job_id: str,
    *,
    write_report: bool = True,
) -> InteriorScopeValidation:
    """Validate the canonical SceneSpec for one job and optionally persist its report."""

    root = job_dir(job_id)
    scene_spec_path = root / "analysis" / "scene_spec.json"
    if not scene_spec_path.is_file():
        raise FileNotFoundError(f"SceneSpec does not exist: {scene_spec_path}")
    scene_spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    return validate_scene_interior_scope(scene_spec, root, write_report=write_report)


def get_interior_scope_status(job_id: str) -> dict[str, object]:
    """Return scope and approval state without creating files or requiring SceneSpec."""

    load_job(job_id)
    root = job_dir(job_id)
    scope_path = root / SCOPE_RELATIVE_PATH
    approval_path = root / APPROVAL_RELATIVE_PATH
    scope = load_interior_scope(root)
    approval = _load_approval(approval_path)
    scope_hash = sha256_file(scope_path) if scope_path.is_file() else None
    approval_valid = bool(
        scope is not None
        and scope.job_id == job_id
        and scope_hash
        and _approval_matches_scope(approval, scope, scope_hash)
    )
    if scope is None:
        state = "default_disabled"
        policy = "disabled"
    elif scope.policy == "disabled":
        state = "explicit_disabled"
        policy = scope.policy
    elif approval is not None and approval.status == "revoked":
        state = "revoked"
        policy = scope.policy
    elif approval is None:
        state = "draft"
        policy = scope.policy
    elif approval_valid:
        state = "approved"
        policy = scope.policy
    else:
        state = "stale"
        policy = scope.policy
    return {
        "job_id": job_id,
        "effective_policy": policy,
        "scope_state": state,
        "scope_present": scope is not None,
        "approval_present": approval is not None,
        "approval_valid": approval_valid,
        "scope_path": SCOPE_RELATIVE_PATH.as_posix() if scope is not None else None,
        "scope_sha256": scope_hash,
        "approval_path": APPROVAL_RELATIVE_PATH.as_posix() if approval is not None else None,
        "approval_sha256": sha256_file(approval_path) if approval_path.is_file() else None,
        "scope": scope.model_dump(mode="json") if scope is not None else None,
    }
