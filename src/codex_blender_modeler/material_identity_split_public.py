"""Thin public host adapters for guarded Material Identity Split 0.1.0."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from pydantic import BaseModel

from .blender_artifacts import native_io_path, sha256_file
from .material_closure.models import ExactArtifact, MaterialCanonicalMaterialPlanAbsence
from .material_identity_split import (
    MaterialIdentitySplitApplyIntent,
    MaterialIdentitySplitApprovalRequest,
    MaterialIdentitySplitPlan,
    MaterialIdentitySplitRootScopeApproval,
    MaterialIdentitySplitService,
    apply_material_identity_split,
    recover_material_identity_split,
)
from .workspace import job_dir

ModelT = TypeVar("ModelT", bound=BaseModel)


def _path_is_link_or_reparse(path: Path) -> bool:
    """Detect symbolic links, junctions, and Windows reparse points without traversal."""

    try:
        metadata = os.lstat(native_io_path(path))
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _job_root(job_id: str) -> Path:
    """Resolve one existing workspace job without creating or migrating it."""

    root = job_dir(job_id).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root


def _contained_file(root: Path, relative_path: str) -> Path:
    """Resolve one regular non-link POSIX file below the owning workspace job."""

    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or "\\" in relative_path
    ):
        raise ValueError("identity-split input must be a contained relative POSIX path")
    current = root
    for part in pure.parts:
        current = current / part
        if _path_is_link_or_reparse(current):
            raise ValueError("identity-split public inputs cannot traverse links")
    resolved = current.resolve(strict=True)
    resolved.relative_to(root)
    if not os.path.isfile(native_io_path(resolved)):
        raise FileNotFoundError(resolved)
    return resolved


def _load_model(root: Path, relative_path: str, model: type[ModelT]) -> ModelT:
    """Strict-load one caller-named immutable JSON model from the job."""

    return model.model_validate_json(
        Path(native_io_path(_contained_file(root, relative_path))).read_bytes()
    )


def _artifact(
    root: Path,
    relative_path: str,
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Bind one current contained file to its exact hash, size, kind, and path."""

    path = _contained_file(root, relative_path)
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=relative_path,
        sha256=sha256_file(path),
        byte_size=os.path.getsize(native_io_path(path)),
        media_type="application/json",
    )


def _publication_payload(publication: Any) -> dict[str, Any]:
    """Project one dataclass publication into deterministic JSON-ready values."""

    result: dict[str, Any] = {}
    for name in publication.__dataclass_fields__:
        value = getattr(publication, name)
        result[name] = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )
    return result


def plan_material_identity_split(
    job_id: str,
    *,
    planning_root: str,
    run_id: str,
    material_plan_absence_path: str,
) -> dict[str, Any]:
    """Replay loose immutable planning evidence into one strict paired plan."""

    root = _job_root(job_id)
    absence = _load_model(
        root,
        material_plan_absence_path,
        MaterialCanonicalMaterialPlanAbsence,
    )
    if absence.job_id != job_id:
        raise ValueError("MaterialPlan absence belongs to another job")
    absence_artifact = _artifact(
        root,
        material_plan_absence_path,
        artifact_id=absence.absence_id,
        kind="material_plan_absence",
    )
    return _publication_payload(
        MaterialIdentitySplitService(root).prepare_plan_from_planning_root(
            planning_root=planning_root,
            run_id=run_id,
            material_plan_absence=absence_artifact,
        )
    )


def get_material_identity_split_status(job_id: str, *, run_id: str) -> dict[str, Any]:
    """Return one read-only projection over the append-only transaction chain."""

    status = MaterialIdentitySplitService(_job_root(job_id)).get_status(run_id)
    return status.model_dump(mode="json")


def run_material_identity_split_preapproval(
    job_id: str,
    *,
    plan_path: str,
    modeling_plan_diff_path: str,
    canonical_scene_inventory_path: str,
) -> dict[str, Any]:
    """Run isolated paired Blender validation and stop before user approval."""

    root = _job_root(job_id)
    plan = _load_model(root, plan_path, MaterialIdentitySplitPlan)
    if plan.job_id != job_id:
        raise ValueError("identity-split plan belongs to another job")
    plan_artifact = _artifact(
        root,
        plan_path,
        artifact_id=f"{plan.run_id}-plan",
        kind="material_identity_split_plan",
    )
    diff_artifact = _artifact(
        root,
        modeling_plan_diff_path,
        artifact_id=f"{plan.run_id}-modeling-plan-diff",
        kind="material_identity_split_modeling_plan_diff_report",
    )
    inventory_artifact = _artifact(
        root,
        canonical_scene_inventory_path,
        artifact_id=f"{plan.run_id}-canonical-scene-inventory",
        kind="scene_inventory",
    )
    return _publication_payload(
        MaterialIdentitySplitService(root).run_preapproval(
            plan_artifact=plan_artifact,
            modeling_plan_diff_report=diff_artifact,
            canonical_scene_inventory=inventory_artifact,
        )
    )


def get_material_identity_split_approval_request(
    job_id: str,
    *,
    approval_request_path: str,
) -> dict[str, Any]:
    """Read one approval-eligible request without turning it into an approval."""

    root = _job_root(job_id)
    request = _load_model(
        root,
        approval_request_path,
        MaterialIdentitySplitApprovalRequest,
    )
    if request.job_id != job_id:
        raise ValueError("identity-split approval request belongs to another job")
    artifact = _artifact(
        root,
        approval_request_path,
        artifact_id=request.approval_request_id,
        kind="material_identity_split_approval_request",
    )
    return {
        "status": request.status,
        "is_user_approval": False,
        "approval_request": request.model_dump(mode="json"),
        "approval_request_artifact": artifact.model_dump(mode="json"),
    }


def approve_material_identity_split(
    job_id: str,
    *,
    approval_request_path: str,
    approval_path: str,
    user_decision_path: str,
    explicit_user_decision_observed: bool,
) -> dict[str, Any]:
    """Publish only a complete caller-authored specialized user decision."""

    root = _job_root(job_id)
    request = _load_model(
        root,
        approval_request_path,
        MaterialIdentitySplitApprovalRequest,
    )
    approval = _load_model(root, approval_path, MaterialIdentitySplitRootScopeApproval)
    request_artifact = _artifact(
        root,
        approval_request_path,
        artifact_id=request.approval_request_id,
        kind="material_identity_split_approval_request",
    )
    decision_bytes = Path(native_io_path(_contained_file(root, user_decision_path))).read_bytes()
    publication = MaterialIdentitySplitService(root).publish_root_scope_approval(
        approval_request=request_artifact,
        approval=approval,
        user_decision_text=decision_bytes,
        explicit_user_decision_observed=explicit_user_decision_observed,
    )
    return _publication_payload(publication)


def apply_material_identity_split_public(
    job_id: str,
    *,
    apply_intent_path: str,
    canonical_scene_inventory_path: str,
) -> dict[str, Any]:
    """Apply one caller-authored approved intent through the host-owned transaction."""

    root = _job_root(job_id)
    intent = _load_model(root, apply_intent_path, MaterialIdentitySplitApplyIntent)
    if intent.job_id != job_id:
        raise ValueError("identity-split ApplyIntent belongs to another job")
    inventory = _artifact(
        root,
        canonical_scene_inventory_path,
        artifact_id=f"{intent.run_id}-canonical-scene-inventory",
        kind="scene_inventory",
    )
    return _publication_payload(
        apply_material_identity_split(
            root,
            intent=intent,
            canonical_scene_inventory=inventory,
        )
    )


def recover_material_identity_split_public(
    job_id: str,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Recover one partial approved transaction without creating new authority."""

    return _publication_payload(
        recover_material_identity_split(_job_root(job_id), run_id=run_id)
    )
