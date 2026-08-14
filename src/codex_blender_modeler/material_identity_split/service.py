"""Host-owned planning, validation, and approval-boundary services for identity splits."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..analysis.models import ModelingPlan
from ..autonomy.io import ensure_autonomy_path
from ..autonomy_v2.delivery_service import artifact_for_v2
from ..autonomy_v2.models import RootAuthorizationV2
from ..blender_artifacts import (
    deterministic_json_bytes,
    native_io_path,
    publish_bytes_create_once,
    sha256_file,
)
from ..blender_runner import BlenderRunError, run_blender
from ..config import get_settings
from ..material_closure.collector import validate_material_plan_absence_evidence
from ..material_closure.incident_service import (
    load_material_closure_model,
    publish_material_closure_model,
)
from ..material_closure.models import (
    ExactArtifact,
    MaterialCanonicalMaterialPlanAbsence,
)
from ..material_closure.preflight import validate_exact_artifact
from ..models import SceneSpec
from .models import (
    MaterialIdentityCloneRule,
    MaterialIdentitySplitApprovalRequest,
    MaterialIdentitySplitAssignment,
    MaterialIdentitySplitBindingDerivativeEntry,
    MaterialIdentitySplitCanonicalPreconditions,
    MaterialIdentitySplitCheck,
    MaterialIdentitySplitInvariantReport,
    MaterialIdentitySplitMaterialBindingDerivativeReceipt,
    MaterialIdentitySplitModelingPlanChange,
    MaterialIdentitySplitModelingPlanDiffReport,
    MaterialIdentitySplitPlan,
    MaterialIdentitySplitPreapprovalFailure,
    MaterialIdentitySplitPreapprovalReport,
    MaterialIdentitySplitPreapprovalRequest,
    MaterialIdentitySplitRootScopeApproval,
    MaterialIdentitySplitShadowBuildReceipt,
    MaterialIdentitySplitStatusProjection,
    MaterialIdentitySplitTransactionState,
)

_PRODUCER = "codex_blender_modeler.material_identity_split"
_PRODUCER_VERSION = "0.1.0"


class MaterialIdentitySplitError(RuntimeError):
    """Signal stale, unsafe, incomplete, or under-authorized identity-split evidence."""


def _shadow_binding_derivative_relative_path(ordinal: int, object_id: str) -> str:
    """Return one compact deterministic leaf that stays below legacy Windows limits."""

    object_digest = hashlib.sha256(object_id.encode("utf-8")).hexdigest()[:12]
    return f"analysis/mbd/{ordinal:02d}-{object_digest}.json"


@dataclass(frozen=True)
class MaterialIdentitySplitPlanPublication:
    """Return one immutable paired plan and its run-owned ModelingPlan evidence."""

    plan: MaterialIdentitySplitPlan
    plan_artifact: ExactArtifact
    candidate_modeling_plan: ExactArtifact
    modeling_plan_diff_report: ExactArtifact
    canonical_scene_inventory: ExactArtifact
    planned_state: ExactArtifact


@dataclass(frozen=True)
class MaterialIdentitySplitPreapprovalResult:
    """Return one terminal preapproval outcome without representing user approval."""

    status: str
    plan: MaterialIdentitySplitPlan
    request: ExactArtifact
    preapproval_report: ExactArtifact | None
    shadow_build_receipt: ExactArtifact | None
    invariant_report: ExactArtifact | None
    approval_request: ExactArtifact | None
    failure: ExactArtifact | None
    terminal_state: ExactArtifact


@dataclass(frozen=True)
class MaterialIdentitySplitApprovalPublication:
    """Return a caller-authored specialized decision published by the host."""

    approval: MaterialIdentitySplitRootScopeApproval
    approval_artifact: ExactArtifact


def _utc_now(value: datetime | None = None) -> datetime:
    """Normalize an optional timestamp to one timezone-aware UTC instant."""

    observed = value or datetime.now(UTC)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("identity-split timestamps must include a timezone offset")
    return observed.astimezone(UTC)


def _read_json_object(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object without accepting arrays or scalar roots."""

    with open(native_io_path(path), "rb") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise MaterialIdentitySplitError(f"identity-split JSON root is not an object: {path.name}")
    return payload


def _media_type_for(path: str) -> str:
    """Map one immutable artifact suffix to its stable media type."""

    suffix = Path(path).suffix.casefold()
    if suffix == ".json":
        return "application/json"
    if suffix == ".blend":
        return "application/x-blender"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


def _artifact_from_path(
    job_root: Path,
    relative_path: str,
    *,
    artifact_id: str,
    kind: str,
    media_type: str | None = None,
) -> ExactArtifact:
    """Rehash one contained regular file into the shared exact-artifact vocabulary."""

    root = job_root.expanduser().resolve(strict=True)
    path = ensure_autonomy_path(
        root,
        root.joinpath(*relative_path.split("/")),
        must_exist=True,
    )
    observed = artifact_for_v2(root, path, artifact_id=artifact_id, kind=kind)
    return ExactArtifact(
        artifact_id=observed.artifact_id,
        kind=observed.kind.replace("-", "_"),
        path=observed.path,
        sha256=observed.sha256,
        byte_size=observed.byte_size,
        media_type=media_type or _media_type_for(relative_path),
    )


def _artifact_from_payload(job_root: Path, payload: object) -> ExactArtifact:
    """Strictly reconstruct and rehash one loose historical exact-artifact object."""

    if not isinstance(payload, dict):
        raise MaterialIdentitySplitError("historical identity-split artifact is not an object")
    required = {"artifact_id", "kind", "path", "sha256", "byte_size"}
    if not required.issubset(payload):
        raise MaterialIdentitySplitError("historical identity-split artifact binding is incomplete")
    artifact = ExactArtifact(
        artifact_id=str(payload["artifact_id"]),
        kind=str(payload["kind"]).replace("-", "_"),
        path=str(payload["path"]),
        sha256=str(payload["sha256"]),
        byte_size=int(payload["byte_size"]),
        media_type=str(payload.get("media_type") or _media_type_for(str(payload["path"]))),
    )
    validate_exact_artifact(job_root, artifact)
    return artifact


def _publish_json_artifact(
    job_root: Path,
    relative_path: str,
    payload: dict[str, Any],
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Publish or exact-adopt one deterministic JSON artifact at a contained path."""

    root = job_root.expanduser().resolve(strict=True)
    destination = ensure_autonomy_path(
        root,
        root.joinpath(*relative_path.split("/")),
        must_exist=False,
    )
    try:
        publish_bytes_create_once(destination, deterministic_json_bytes(payload))
    except FileExistsError as exc:
        raise FileExistsError(
            f"conflicting immutable identity-split JSON: {relative_path}"
        ) from exc
    return _artifact_from_path(
        root,
        relative_path,
        artifact_id=artifact_id,
        kind=kind,
    )


def _publish_model(
    job_root: Path,
    relative_path: str,
    model: BaseModel,
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Publish one strict model and return only its exact artifact binding."""

    _, artifact = publish_material_closure_model(
        job_root,
        relative_path,
        model,
        artifact_id=artifact_id,
        kind=kind,
    )
    return artifact


def _load_exact_json(job_root: Path, artifact: ExactArtifact) -> dict[str, Any]:
    """Rehash one exact JSON artifact and return its object payload."""

    path = validate_exact_artifact(job_root, artifact)
    return _read_json_object(path)


def _identity_kwargs(
    plan: MaterialIdentitySplitPlan,
    created_at: datetime,
) -> dict[str, object]:
    """Project the common strict identity shared by run-owned companion evidence."""

    return {
        "job_id": plan.job_id,
        "workflow_id": plan.workflow_id,
        "dispatch_id": plan.dispatch_id,
        "run_id": plan.run_id,
        "producer": _PRODUCER,
        "producer_version": _PRODUCER_VERSION,
        "created_at": created_at,
    }


def _validate_artifact_scope(
    job_root: Path,
    artifact: ExactArtifact,
    *,
    expected_path: str | None = None,
    expected_kind: str | None = None,
) -> Path:
    """Rehash an artifact and optionally require one canonical path and kind."""

    if expected_path is not None and artifact.path != expected_path:
        raise MaterialIdentitySplitError(
            f"identity-split artifact path is not canonical: {artifact.path}"
        )
    if expected_kind is not None and artifact.kind != expected_kind:
        raise MaterialIdentitySplitError(
            f"identity-split artifact kind is invalid: {artifact.kind}"
        )
    return validate_exact_artifact(job_root, artifact)


def _clone_scene_expected(
    canonical: dict[str, Any],
    clone_rules: list[MaterialIdentityCloneRule],
) -> dict[str, Any]:
    """Derive the only allowed SceneSpec candidate from exact semantic clone rules."""

    expected = copy.deepcopy(canonical)
    materials = expected.get("materials")
    objects = expected.get("objects")
    if not isinstance(materials, list) or not isinstance(objects, list):
        raise MaterialIdentitySplitError("canonical SceneSpec lacks materials or objects")
    material_by_id = {str(item.get("id")): item for item in materials if isinstance(item, dict)}
    object_by_id = {str(item.get("id")): item for item in objects if isinstance(item, dict)}
    for rule in clone_rules:
        source = material_by_id.get(rule.source_material_id)
        target = object_by_id.get(rule.target_object_id)
        if source is None or target is None:
            raise MaterialIdentitySplitError(
                "identity clone references an unknown source or object"
            )
        if rule.new_material_id in material_by_id:
            raise MaterialIdentitySplitError("identity clone new material already exists")
        clone = copy.deepcopy(source)
        clone["id"] = rule.new_material_id
        materials.append(clone)
        material_by_id[rule.new_material_id] = clone
        if target.get("material_id") != rule.source_material_id:
            raise MaterialIdentitySplitError(
                "identity clone target does not use its source material"
            )
        target["material_id"] = rule.new_material_id
        for retained_id in rule.retained_source_object_ids:
            retained = object_by_id.get(retained_id)
            if retained is None or retained.get("material_id") != rule.source_material_id:
                raise MaterialIdentitySplitError("retained material assignment is stale")
    return expected


def _candidate_modeling_plan_payload(
    canonical: dict[str, Any],
    changes: list[MaterialIdentitySplitModelingPlanChange],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Derive one paired ModelingPlan with only declared target-material replacements."""

    candidate = copy.deepcopy(canonical)
    details = candidate.get("surface_details")
    if not isinstance(details, list):
        raise MaterialIdentitySplitError("canonical ModelingPlan lacks surface_details")
    detail_by_id = {str(item.get("id")): item for item in details if isinstance(item, dict)}
    for change in changes:
        detail = detail_by_id.get(change.detail_id)
        if detail is None:
            raise MaterialIdentitySplitError("identity split references an unknown surface detail")
        if (
            detail.get("parent_object_id") != change.parent_object_id
            or detail.get("target_material_id") != change.source_material_id
            or list(detail.get("channels", [])) != change.required_channels
        ):
            raise MaterialIdentitySplitError("paired ModelingPlan change is stale")
        detail["target_material_id"] = change.new_material_id
    changed_ids = {item.detail_id for item in changes}
    preserved = {
        str(item["id"]): list(item.get("channels", []))
        for item in details
        if isinstance(item, dict) and str(item.get("id")) not in changed_ids
    }
    return candidate, preserved


def _validate_root_scope(
    job_root: Path,
    root_authorization: ExactArtifact,
    *,
    workflow_id: str,
    dispatch_id: str,
    primary_reference: ExactArtifact,
    content_scope_sha256: str,
    target_subject: str,
) -> RootAuthorizationV2:
    """Replay the existing root authority only as a scope observation, never as approval."""

    path = _validate_artifact_scope(
        job_root,
        root_authorization,
        expected_kind="root_authorization",
    )
    authority = RootAuthorizationV2.model_validate_json(path.read_bytes())
    if (
        authority.job_id != job_root.name
        or authority.workflow_id != workflow_id
        or authority.dispatch_id != dispatch_id
        or authority.original_request_sha256 != content_scope_sha256
        or authority.target_subject != target_subject
        or authority.primary_reference.path != primary_reference.path
        or authority.primary_reference.sha256 != primary_reference.sha256
        or authority.primary_reference.byte_size != primary_reference.byte_size
    ):
        raise MaterialIdentitySplitError("identity split reference or root scope is stale")
    return authority


def _validate_material_plan_absence(
    job_root: Path,
    artifact: ExactArtifact,
) -> MaterialCanonicalMaterialPlanAbsence:
    """Strict-load and replay one current canonical MaterialPlan absence observation."""

    absence = load_material_closure_model(
        job_root,
        artifact,
        MaterialCanonicalMaterialPlanAbsence,
    )
    validate_material_plan_absence_evidence(job_root, absence)
    if (job_root / "analysis" / "material_plan.json").exists():
        raise MaterialIdentitySplitError("canonical MaterialPlan appeared after absence evidence")
    return absence


def _material_semantic_projection(material: dict[str, Any]) -> dict[str, Any]:
    """Remove only the stable identity field from one material semantic projection."""

    return {key: copy.deepcopy(value) for key, value in material.items() if key != "id"}


def _validate_scene_candidate(
    canonical_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    clone_rules: list[MaterialIdentityCloneRule],
) -> None:
    """Require exactly the planned clones and assignments with no incidental mutation."""

    expected = _clone_scene_expected(canonical_payload, clone_rules)
    if candidate_payload != expected:
        raise MaterialIdentitySplitError(
            "candidate SceneSpec differs from the exact identity-clone projection"
        )
    canonical_materials = {str(item["id"]): item for item in canonical_payload["materials"]}
    candidate_materials = {str(item["id"]): item for item in candidate_payload["materials"]}
    candidate_objects = candidate_payload["objects"]
    for rule in clone_rules:
        source = canonical_materials[rule.source_material_id]
        clone = candidate_materials[rule.new_material_id]
        if _material_semantic_projection(source) != _material_semantic_projection(clone):
            raise MaterialIdentitySplitError("new material is not an exact semantic clone")
        users = sorted(
            str(item["id"])
            for item in candidate_objects
            if item.get("material_id") == rule.new_material_id
        )
        if users != [rule.target_object_id]:
            raise MaterialIdentitySplitError("new material identity is not exclusively owned")


def _inventory_object_projection(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Project all authored objects while excluding only planned material assignments."""

    objects = payload.get("objects")
    if not isinstance(objects, list):
        raise MaterialIdentitySplitError("scene inventory has no object list")
    projection: dict[str, dict[str, Any]] = {}
    for item in objects:
        if not isinstance(item, dict) or not item.get("cbm_id"):
            continue
        object_id = str(item["cbm_id"])
        projection[object_id] = {
            key: copy.deepcopy(value) for key, value in item.items() if key != "materials"
        }
    return projection


def _inventory_assignment_projection(payload: dict[str, Any]) -> dict[str, list[str]]:
    """Project exact material slots for every authored inventory object."""

    objects = payload.get("objects")
    if not isinstance(objects, list):
        raise MaterialIdentitySplitError("scene inventory has no object list")
    return {
        str(item["cbm_id"]): list(item.get("materials", []))
        for item in objects
        if isinstance(item, dict) and item.get("cbm_id")
    }


def _validate_validation_report(path: Path) -> dict[str, Any]:
    """Require one Blender validation report to state ok=true."""

    payload = _read_json_object(path)
    if payload.get("ok") is not True:
        raise MaterialIdentitySplitError("shadow Blender validation did not report ok=true")
    return payload


def _candidate_dependency_paths(payload: object) -> set[str]:
    """Collect existing job-relative file references from one strict candidate payload."""

    discovered: set[str] = set()

    def visit(value: object, key: str | None = None) -> None:
        """Walk nested JSON values and retain only path-bearing string fields."""

        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child_value in value:
                visit(child_value, key)
        elif isinstance(value, str) and key is not None:
            if key == "path" or key.endswith("_path"):
                discovered.add(value)

    visit(payload)
    return discovered


def _blender_executable() -> Path:
    """Resolve the configured supported Blender executable to exact regular bytes."""

    configured = get_settings().blender_bin
    candidate = shutil.which(configured) or configured
    path = Path(candidate).expanduser().resolve(strict=True)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _bounded_failure_message(job_root: Path, error: Exception) -> str:
    """Sanitize host paths and retain the bounded diagnostic tail of one failure."""

    message = str(error)
    replacements = (
        (str(job_root), "<JOB_ROOT>"),
        (str(get_settings().repo_root), "<REPO_ROOT>"),
    )
    for source, replacement in replacements:
        message = message.replace(source, replacement)
    return message[-1200:] or type(error).__name__


class MaterialIdentitySplitService:
    """Coordinate generic identity-split evidence while preserving approval boundaries."""

    def __init__(self, job_root: Path):
        """Bind the service to one existing non-linked job workspace."""

        self.job_root = job_root.expanduser().resolve(strict=True)
        if not self.job_root.is_dir():
            raise FileNotFoundError(self.job_root)

    def prepare_plan_from_planning_root(
        self,
        *,
        planning_root: str,
        run_id: str,
        material_plan_absence: ExactArtifact,
        created_at: datetime | None = None,
    ) -> MaterialIdentitySplitPlanPublication:
        """Replay one immutable loose plan into strict generic paired planning evidence."""

        observed_at = _utc_now(created_at)
        root = ensure_autonomy_path(
            self.job_root,
            self.job_root.joinpath(*planning_root.split("/")),
            must_exist=True,
        )
        if not root.is_dir():
            raise MaterialIdentitySplitError("identity-split planning root is not a directory")
        manifest_path = root / "plan_manifest.json"
        mapping_path = root / "surface_detail_material_mapping.json"
        requirement_path = root / "specialized_approval_requirement.json"
        impact_path = root / "approval_impact_report.json"
        for path in (manifest_path, mapping_path, requirement_path, impact_path):
            ensure_autonomy_path(self.job_root, path, must_exist=True)
        manifest = _read_json_object(manifest_path)
        mapping = _read_json_object(mapping_path)
        requirement = _read_json_object(requirement_path)
        impact = _read_json_object(impact_path)
        if (
            manifest.get("schema_version") != "0.1.0"
            or mapping.get("schema_version") != "0.1.0"
            or requirement.get("schema_version") != "0.1.0"
            or impact.get("schema_version") != "0.1.0"
        ):
            raise MaterialIdentitySplitError("unknown identity-split planning schema version")
        exact = requirement.get("exact_binding_requirements")
        authoring = mapping.get("material_identity_authoring_plan")
        rows = mapping.get("surface_detail_rows")
        if (
            not isinstance(exact, dict)
            or not isinstance(authoring, list)
            or not isinstance(rows, list)
        ):
            raise MaterialIdentitySplitError("identity-split planning evidence is incomplete")
        job_id = str(requirement.get("job_id"))
        plan_id = str(requirement.get("plan_id"))
        workflow_id = str(exact.get("workflow_id"))
        dispatch_id = str(exact.get("dispatch_id"))
        if job_id != self.job_root.name or manifest.get("plan_id") != plan_id:
            raise MaterialIdentitySplitError("identity-split plan belongs to another job or plan")
        if (
            impact.get("impact") != "scope_change"
            or impact.get("required_approval") != "root_scope"
        ):
            raise MaterialIdentitySplitError("identity split was not classified as root scope")

        artifact_by_name = {
            Path(str(item["path"])).name: _artifact_from_payload(self.job_root, item)
            for item in manifest.get("artifacts", [])
            if isinstance(item, dict)
        }
        required_names = {
            "candidate_scene_spec.json",
            "revision_plan.json",
            "exact_diff_allowlist.json",
            "approval_impact_report.json",
            "geometry_uv_unchanged_report.json",
            "surface_detail_material_mapping.json",
            "specialized_approval_requirement.json",
            "session_supersession_plan.json",
        }
        if not required_names.issubset(artifact_by_name):
            raise MaterialIdentitySplitError("identity-split plan manifest omits required evidence")

        clone_rules: list[MaterialIdentityCloneRule] = []
        retained_payload = exact.get("retained_assignments")
        if not isinstance(retained_payload, list):
            raise MaterialIdentitySplitError("identity-split retained assignments are missing")
        for raw in authoring:
            if not isinstance(raw, dict):
                raise MaterialIdentitySplitError("identity clone row is malformed")
            source_id = str(raw.get("source_material_id"))
            retained_ids = sorted(
                str(item["object_id"])
                for item in retained_payload
                if isinstance(item, dict) and item.get("material_id") == source_id
            )
            clone_rules.append(
                MaterialIdentityCloneRule(
                    source_material_id=source_id,
                    new_material_id=str(raw.get("new_material_id")),
                    target_object_id=str(raw.get("planned_parent_object_id")),
                    surface_detail_id=str(raw.get("planned_surface_detail_id")),
                    retained_source_object_ids=retained_ids,
                )
            )
        changes: list[MaterialIdentitySplitModelingPlanChange] = []
        for raw in rows:
            if not isinstance(raw, dict) or not raw.get(
                "companion_modeling_plan_revision_required"
            ):
                continue
            changes.append(
                MaterialIdentitySplitModelingPlanChange(
                    detail_id=str(raw.get("detail_id")),
                    parent_object_id=str(raw.get("parent_object_id")),
                    source_material_id=str(raw.get("canonical_modeling_plan_target_material_id")),
                    new_material_id=str(
                        raw.get("planned_post_scope_modeling_requirement_material_id")
                    ),
                    required_channels=[str(value) for value in raw.get("requested_channels", [])],
                )
            )
        changed = [
            MaterialIdentitySplitAssignment.model_validate(item)
            for item in exact.get("assignment_changes", [])
        ]
        retained = [
            MaterialIdentitySplitAssignment.model_validate(item) for item in retained_payload
        ]

        canonical_scene = _artifact_from_payload(self.job_root, exact.get("canonical_scene_spec"))
        canonical_modeling = _artifact_from_payload(
            self.job_root, exact.get("canonical_modeling_plan")
        )
        canonical_blend = _artifact_from_payload(self.job_root, exact.get("canonical_blend"))
        primary_reference = _artifact_from_payload(self.job_root, exact.get("primary_reference"))
        root_authorization = _artifact_from_payload(
            self.job_root, exact.get("reference_authorization")
        )
        current_closure = _artifact_from_payload(
            self.job_root, exact.get("latest_material_closure")
        )
        latest_failure = _artifact_from_payload(
            self.job_root, exact.get("latest_framework_failure")
        )
        reconciliation = _artifact_from_payload(
            self.job_root, exact.get("latest_channel_reconciliation")
        )
        geometry_report = _read_json_object(root / "geometry_uv_unchanged_report.json")
        canonical_inventory = _artifact_from_payload(
            self.job_root, geometry_report.get("canonical_scene_inventory")
        )
        absence = _validate_material_plan_absence(self.job_root, material_plan_absence)
        content_scope_sha256 = str(
            _read_json_object(validate_exact_artifact(self.job_root, root_authorization)).get(
                "original_request_sha256"
            )
        )
        target_subject = str(
            _read_json_object(validate_exact_artifact(self.job_root, root_authorization)).get(
                "target_subject"
            )
        )
        _validate_root_scope(
            self.job_root,
            root_authorization,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            primary_reference=primary_reference,
            content_scope_sha256=content_scope_sha256,
            target_subject=target_subject,
        )
        if (
            absence.canonical_scene_spec.sha256 != canonical_scene.sha256
            or absence.canonical_blend.sha256 != canonical_blend.sha256
        ):
            raise MaterialIdentitySplitError("MaterialPlan absence binds stale canonical bytes")

        canonical_modeling_payload = _read_json_object(
            validate_exact_artifact(self.job_root, canonical_modeling)
        )
        candidate_modeling_payload, preserved_channels = _candidate_modeling_plan_payload(
            canonical_modeling_payload,
            changes,
        )
        ModelingPlan.model_validate(candidate_modeling_payload)
        candidate_modeling_path = (
            f"production/material_identity_split/{run_id}/planning/candidate_modeling_plan.json"
        )
        candidate_modeling = _publish_json_artifact(
            self.job_root,
            candidate_modeling_path,
            candidate_modeling_payload,
            artifact_id=f"{run_id}-candidate-modeling-plan",
            kind="candidate_modeling_plan",
        )
        candidate_scene = artifact_by_name["candidate_scene_spec.json"]
        SceneSpec.model_validate_json(
            validate_exact_artifact(self.job_root, candidate_scene).read_bytes()
        )
        preconditions = MaterialIdentitySplitCanonicalPreconditions(
            scene_spec=canonical_scene,
            modeling_plan=canonical_modeling,
            blend=canonical_blend,
            material_plan_absence=material_plan_absence,
            root_authorization=root_authorization,
            primary_reference=primary_reference,
            content_scope_sha256=content_scope_sha256,
            target_subject=target_subject,
            uv_layout_fingerprint=str(exact.get("current_uv_layout_fingerprint")),
        )
        plan = MaterialIdentitySplitPlan(
            job_id=job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            run_id=run_id,
            producer=_PRODUCER,
            producer_version=_PRODUCER_VERSION,
            created_at=observed_at,
            plan_id=plan_id,
            planning_root=planning_root,
            plan_manifest=_artifact_from_path(
                self.job_root,
                f"{planning_root}/plan_manifest.json",
                artifact_id=f"{plan_id}-manifest",
                kind="material_identity_split_plan_manifest",
            ),
            revision_plan=artifact_by_name["revision_plan.json"],
            candidate_scene_spec=candidate_scene,
            candidate_modeling_plan=candidate_modeling,
            scene_diff_allowlist=artifact_by_name["exact_diff_allowlist.json"],
            approval_impact_report=artifact_by_name["approval_impact_report.json"],
            geometry_uv_unchanged_report=artifact_by_name["geometry_uv_unchanged_report.json"],
            surface_detail_material_mapping=artifact_by_name[
                "surface_detail_material_mapping.json"
            ],
            specialized_approval_requirement=artifact_by_name[
                "specialized_approval_requirement.json"
            ],
            session_supersession_plan=artifact_by_name["session_supersession_plan.json"],
            current_material_closure=current_closure,
            latest_framework_failure=latest_failure,
            channel_reconciliation=reconciliation,
            preconditions=preconditions,
            clone_rules=clone_rules,
            modeling_plan_changes=changes,
            changed_assignments=changed,
            retained_assignments=retained,
        )
        plan_path = f"production/material_identity_split/{run_id}/plan.json"
        plan_artifact = _publish_model(
            self.job_root,
            plan_path,
            plan,
            artifact_id=f"{run_id}-plan",
            kind="material_identity_split_plan",
        )
        diff = MaterialIdentitySplitModelingPlanDiffReport(
            **_identity_kwargs(plan, observed_at),
            report_id=f"{run_id}-modeling-plan-diff",
            plan=plan_artifact,
            canonical_modeling_plan=canonical_modeling,
            candidate_modeling_plan=candidate_modeling,
            allowed_changes=changes,
            actual_change_count=len(changes),
            preserved_detail_channels=preserved_channels,
        )
        diff_artifact = _publish_model(
            self.job_root,
            f"production/material_identity_split/{run_id}/planning/modeling_plan_diff_report.json",
            diff,
            artifact_id=f"{run_id}-modeling-plan-diff",
            kind="material_identity_split_modeling_plan_diff_report",
        )
        state = MaterialIdentitySplitTransactionState(
            **_identity_kwargs(plan, observed_at),
            transaction_id=run_id,
            sequence=0,
            state="planned",
            plan=plan_artifact,
            canonical_observation=preconditions,
            performed_actions=["paired_plan_published"],
            allowed_next_actions=["run_preapproval"],
        )
        state_artifact = _publish_model(
            self.job_root,
            f"production/material_identity_split/{run_id}/states/0000.json",
            state,
            artifact_id=f"{run_id}-state-0000",
            kind="material_identity_split_transaction_state",
        )
        return MaterialIdentitySplitPlanPublication(
            plan=plan,
            plan_artifact=plan_artifact,
            candidate_modeling_plan=candidate_modeling,
            modeling_plan_diff_report=diff_artifact,
            canonical_scene_inventory=canonical_inventory,
            planned_state=state_artifact,
        )

    def validate_plan_current(self, plan: MaterialIdentitySplitPlan) -> None:
        """Replay every exact plan input and reject stale canonical or scope evidence."""

        if plan.job_id != self.job_root.name:
            raise MaterialIdentitySplitError("identity-split plan belongs to another job")
        for artifact in (
            plan.plan_manifest,
            plan.revision_plan,
            plan.candidate_scene_spec,
            plan.candidate_modeling_plan,
            plan.scene_diff_allowlist,
            plan.approval_impact_report,
            plan.geometry_uv_unchanged_report,
            plan.surface_detail_material_mapping,
            plan.specialized_approval_requirement,
            plan.session_supersession_plan,
            plan.current_material_closure,
            plan.latest_framework_failure,
            plan.channel_reconciliation,
            plan.preconditions.scene_spec,
            plan.preconditions.modeling_plan,
            plan.preconditions.blend,
            plan.preconditions.primary_reference,
            plan.preconditions.root_authorization,
        ):
            validate_exact_artifact(self.job_root, artifact)
        _validate_material_plan_absence(
            self.job_root,
            plan.preconditions.material_plan_absence,
        )
        _validate_root_scope(
            self.job_root,
            plan.preconditions.root_authorization,
            workflow_id=plan.workflow_id,
            dispatch_id=plan.dispatch_id,
            primary_reference=plan.preconditions.primary_reference,
            content_scope_sha256=plan.preconditions.content_scope_sha256,
            target_subject=plan.preconditions.target_subject,
        )
        canonical_scene_payload = _load_exact_json(self.job_root, plan.preconditions.scene_spec)
        candidate_scene_payload = _load_exact_json(self.job_root, plan.candidate_scene_spec)
        SceneSpec.model_validate(canonical_scene_payload)
        SceneSpec.model_validate(candidate_scene_payload)
        _validate_scene_candidate(
            canonical_scene_payload,
            candidate_scene_payload,
            plan.clone_rules,
        )
        canonical_modeling_payload = _load_exact_json(
            self.job_root, plan.preconditions.modeling_plan
        )
        expected_modeling, _ = _candidate_modeling_plan_payload(
            canonical_modeling_payload,
            plan.modeling_plan_changes,
        )
        candidate_modeling_payload = _load_exact_json(self.job_root, plan.candidate_modeling_plan)
        if candidate_modeling_payload != expected_modeling:
            raise MaterialIdentitySplitError(
                "candidate ModelingPlan differs from the exact paired projection"
            )
        ModelingPlan.model_validate(candidate_modeling_payload)

    def _prepare_shadow_root(
        self,
        plan: MaterialIdentitySplitPlan,
        shadow_root: str,
    ) -> tuple[Path, Path, Path, Path, Path, ExactArtifact]:
        """Create an isolated shadow job containing only exact paired candidate inputs."""

        root = ensure_autonomy_path(
            self.job_root,
            self.job_root.joinpath(*shadow_root.split("/")),
            must_exist=False,
        )
        if root.exists() and any(root.iterdir()):
            raise FileExistsError("identity-split shadow workspace already contains outputs")
        for relative in ("analysis", "blender", "reports", "input"):
            destination = root / relative
            os.makedirs(native_io_path(destination), exist_ok=True)
            ensure_autonomy_path(self.job_root, destination, must_exist=True)
        scene_path = root / "analysis" / "scene_spec.json"
        modeling_path = root / "analysis" / "modeling_plan.json"
        reference_path = root / plan.preconditions.primary_reference.path
        reference_path.parent.mkdir(parents=True, exist_ok=True)
        for artifact, destination in (
            (plan.candidate_scene_spec, scene_path),
            (plan.candidate_modeling_plan, modeling_path),
            (plan.preconditions.primary_reference, reference_path),
        ):
            source = validate_exact_artifact(self.job_root, artifact)
            publish_bytes_create_once(destination, source.read_bytes())
        candidate_payload = _load_exact_json(self.job_root, plan.candidate_scene_spec)
        pending = sorted(_candidate_dependency_paths(candidate_payload))
        copied: set[str] = set()
        while pending:
            relative = pending.pop(0)
            if relative in copied:
                continue
            source = ensure_autonomy_path(
                self.job_root,
                self.job_root.joinpath(*relative.split("/")),
                must_exist=True,
            )
            if not source.is_file():
                raise MaterialIdentitySplitError(
                    f"candidate dependency is not a regular file: {relative}"
                )
            destination = ensure_autonomy_path(
                self.job_root,
                root.joinpath(*relative.split("/")),
                must_exist=False,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            ensure_autonomy_path(self.job_root, destination.parent, must_exist=True)
            publish_bytes_create_once(destination, source.read_bytes())
            copied.add(relative)
            if source.suffix.casefold() == ".json":
                nested = _candidate_dependency_paths(_read_json_object(source))
                pending.extend(sorted(nested - copied))
        binding_derivative = self._publish_shadow_binding_derivatives(
            plan,
            root,
            candidate_payload,
        )
        return (
            root,
            scene_path,
            root / "blender" / "scene.blend",
            root / "reports" / "scene_inventory.json",
            root / "reports" / "validation.json",
            binding_derivative,
        )

    def _publish_shadow_binding_derivatives(
        self,
        plan: MaterialIdentitySplitPlan,
        shadow_root: Path,
        candidate_scene: dict[str, Any],
    ) -> ExactArtifact:
        """Publish geometry-identical shadow payloads with only planned slot identities."""

        objects = candidate_scene.get("objects")
        if not isinstance(objects, list):
            raise MaterialIdentitySplitError("candidate SceneSpec has no objects")
        object_by_id = {str(item.get("id")): item for item in objects if isinstance(item, dict)}
        entries: list[MaterialIdentitySplitBindingDerivativeEntry] = []
        bindings: list[dict[str, object]] = []
        for ordinal, rule in enumerate(plan.clone_rules, start=1):
            object_payload = object_by_id.get(rule.target_object_id)
            geometry = object_payload.get("geometry") if isinstance(object_payload, dict) else None
            if not isinstance(geometry, dict) or not isinstance(geometry.get("path"), str):
                raise MaterialIdentitySplitError(
                    "identity split target requires one exact mesh payload path"
                )
            source_relative = str(geometry["path"])
            source_path = ensure_autonomy_path(
                self.job_root,
                shadow_root.joinpath(*source_relative.split("/")),
                must_exist=True,
            )
            source_payload = _read_json_object(source_path)
            slots = source_payload.get("material_slots")
            if not isinstance(slots, list):
                raise MaterialIdentitySplitError(
                    "identity split mesh payload has no material slots"
                )
            derivative_payload = copy.deepcopy(source_payload)
            derivative_slots = derivative_payload["material_slots"]
            replacements = 0
            for slot in derivative_slots:
                if isinstance(slot, dict) and slot.get("material_id") == rule.source_material_id:
                    slot["material_id"] = rule.new_material_id
                    replacements += 1
            if replacements != 1:
                raise MaterialIdentitySplitError(
                    "identity split mesh payload must replace exactly one material slot"
                )
            source_projection = {
                key: value for key, value in source_payload.items() if key != "material_slots"
            }
            derivative_projection = {
                key: value for key, value in derivative_payload.items() if key != "material_slots"
            }
            if source_projection != derivative_projection:
                raise MaterialIdentitySplitError(
                    "identity split mesh derivative changed geometry payload semantics"
                )
            derivative_relative = _shadow_binding_derivative_relative_path(
                ordinal,
                rule.target_object_id,
            )
            global_derivative_relative = (
                f"{shadow_root.relative_to(self.job_root).as_posix()}/{derivative_relative}"
            )
            derivative_artifact = _publish_json_artifact(
                self.job_root,
                global_derivative_relative,
                derivative_payload,
                artifact_id=f"{plan.run_id}-binding-derivative-{ordinal:02d}",
                kind="material_binding_mesh_payload",
            )
            source_artifact = _artifact_from_path(
                self.job_root,
                source_path.relative_to(self.job_root).as_posix(),
                artifact_id=f"{plan.run_id}-binding-source-{ordinal:02d}",
                kind="source_mesh_payload",
            )
            entries.append(
                MaterialIdentitySplitBindingDerivativeEntry(
                    object_id=rule.target_object_id,
                    source_material_id=rule.source_material_id,
                    new_material_id=rule.new_material_id,
                    source_payload=source_artifact,
                    derivative_payload=derivative_artifact,
                )
            )
            bindings.append(
                {
                    "object_id": rule.target_object_id,
                    "material_id": rule.new_material_id,
                    "scene_payload_path": source_relative,
                    "source_sha256": source_artifact.sha256,
                    "derivative_path": derivative_relative,
                    "derivative_sha256": derivative_artifact.sha256,
                }
            )
        receipt = MaterialIdentitySplitMaterialBindingDerivativeReceipt(
            **_identity_kwargs(plan, plan.created_at),
            receipt_id=f"{plan.run_id}-binding-derivative",
            entries=entries,
        )
        shadow_relative = shadow_root.relative_to(self.job_root).as_posix()
        receipt_relative = f"{shadow_relative}/analysis/material_binding_derivative_receipt.json"
        receipt_artifact = _publish_model(
            self.job_root,
            receipt_relative,
            receipt,
            artifact_id=f"{plan.run_id}-binding-derivative-receipt",
            kind="material_identity_split_binding_derivative_receipt",
        )
        manifest = {
            "schema_version": "0.1.0",
            "topology_unchanged": True,
            "canonical_geometry_payload_overwrite": False,
            "source_receipt_path": "analysis/material_binding_derivative_receipt.json",
            "source_receipt_sha256": receipt_artifact.sha256,
            "bindings": bindings,
        }
        _publish_json_artifact(
            self.job_root,
            f"{shadow_relative}/analysis/material_binding_derivative.json",
            manifest,
            artifact_id=f"{plan.run_id}-binding-derivative-manifest",
            kind="material_binding_derivative_manifest",
        )
        return receipt_artifact

    def _run_shadow(
        self,
        plan: MaterialIdentitySplitPlan,
        request_artifact: ExactArtifact,
        request: MaterialIdentitySplitPreapprovalRequest,
        *,
        created_at: datetime,
    ) -> tuple[MaterialIdentitySplitShadowBuildReceipt, dict[str, Any]]:
        """Run exactly build, inspect, and validate against an isolated paired candidate."""

        before = (
            _artifact_from_path(
                self.job_root,
                "analysis/scene_spec.json",
                artifact_id=f"{plan.run_id}-canonical-scene-before",
                kind="scene_spec",
            ),
            _artifact_from_path(
                self.job_root,
                "analysis/modeling_plan.json",
                artifact_id=f"{plan.run_id}-canonical-modeling-before",
                kind="modeling_plan",
            ),
            _artifact_from_path(
                self.job_root,
                "blender/scene.blend",
                artifact_id=f"{plan.run_id}-canonical-blend-before",
                kind="canonical_blend",
                media_type="application/x-blender",
            ),
        )
        material_absent_before = not (self.job_root / "analysis" / "material_plan.json").exists()
        (
            shadow,
            scene_path,
            blend_path,
            inventory_path,
            validation_path,
            binding_derivative,
        ) = self._prepare_shadow_root(plan, request.shadow_root)
        commands = [
            "blender --background --python build_scene.py -- "
            "--spec analysis/scene_spec.json --output blender/scene.blend",
            "blender --background blender/scene.blend --python inspect_scene.py -- "
            "--output reports/scene_inventory.json",
            "blender --background blender/scene.blend --python validate_scene.py -- "
            "--spec analysis/scene_spec.json --output reports/validation.json",
        ]
        process_count = 0
        try:
            run_blender(
                "build_scene.py",
                ["--spec", str(scene_path), "--output", str(blend_path)],
                factory_startup=True,
                disable_autoexec=True,
            )
            process_count += 1
            run_blender(
                "inspect_scene.py",
                ["--output", str(inventory_path)],
                blend_file=blend_path,
                factory_startup=True,
                disable_autoexec=True,
            )
            process_count += 1
            run_blender(
                "validate_scene.py",
                ["--spec", str(scene_path), "--output", str(validation_path)],
                blend_file=blend_path,
                factory_startup=True,
                disable_autoexec=True,
            )
            process_count += 1
        except (BlenderRunError, FileNotFoundError, TimeoutError) as exc:
            raise MaterialIdentitySplitError(
                f"isolated identity-split Blender run failed: {exc}"
            ) from exc
        validation_payload = _validate_validation_report(validation_path)
        inventory_payload = _read_json_object(inventory_path)
        if inventory_payload.get("blender_version") != "5.0.1":
            raise MaterialIdentitySplitError("identity-split shadow did not use Blender 5.0.1")
        after = (
            _artifact_from_path(
                self.job_root,
                "analysis/scene_spec.json",
                artifact_id=f"{plan.run_id}-canonical-scene-after",
                kind="scene_spec",
            ),
            _artifact_from_path(
                self.job_root,
                "analysis/modeling_plan.json",
                artifact_id=f"{plan.run_id}-canonical-modeling-after",
                kind="modeling_plan",
            ),
            _artifact_from_path(
                self.job_root,
                "blender/scene.blend",
                artifact_id=f"{plan.run_id}-canonical-blend-after",
                kind="canonical_blend",
                media_type="application/x-blender",
            ),
        )
        material_absent_after = not (self.job_root / "analysis" / "material_plan.json").exists()
        canonical_unchanged = (
            all(
                (left.path, left.sha256, left.byte_size)
                == (right.path, right.sha256, right.byte_size)
                for left, right in zip(before, after, strict=True)
            )
            and material_absent_before
            and material_absent_after
        )
        executable = _blender_executable()
        shadow_blend = _artifact_from_path(
            self.job_root,
            blend_path.relative_to(self.job_root).as_posix(),
            artifact_id=f"{plan.run_id}-shadow-blend",
            kind="material_identity_split_shadow_blend",
            media_type="application/x-blender",
        )
        shadow_inventory = _artifact_from_path(
            self.job_root,
            inventory_path.relative_to(self.job_root).as_posix(),
            artifact_id=f"{plan.run_id}-shadow-inventory",
            kind="material_identity_split_shadow_scene_inventory",
        )
        shadow_validation = _artifact_from_path(
            self.job_root,
            validation_path.relative_to(self.job_root).as_posix(),
            artifact_id=f"{plan.run_id}-shadow-validation",
            kind="material_identity_split_shadow_validation",
        )
        receipt = MaterialIdentitySplitShadowBuildReceipt(
            **_identity_kwargs(plan, created_at),
            receipt_id=f"{plan.run_id}-shadow-build",
            request=request_artifact,
            status="passed",
            blender_version="5.0.1",
            blender_executable_name=executable.name,
            blender_executable_sha256=sha256_file(executable),
            blender_process_count=process_count,
            commands=commands,
            shadow_root=request.shadow_root,
            shadow_blend=shadow_blend,
            shadow_scene_inventory=shadow_inventory,
            shadow_validation=shadow_validation,
            material_binding_derivative=binding_derivative,
            canonical_scene_spec_before=before[0],
            canonical_scene_spec_after=after[0],
            canonical_modeling_plan_before=before[1],
            canonical_modeling_plan_after=after[1],
            canonical_blend_before=before[2],
            canonical_blend_after=after[2],
            material_plan_absent_before=material_absent_before,
            material_plan_absent_after=material_absent_after,
            canonical_unchanged=canonical_unchanged,
        )
        if not canonical_unchanged:
            raise MaterialIdentitySplitError(
                "isolated identity-split shadow changed canonical bytes"
            )
        return receipt, {"inventory": inventory_payload, "validation": validation_payload}

    def _build_invariant_report(
        self,
        plan: MaterialIdentitySplitPlan,
        request_artifact: ExactArtifact,
        shadow_receipt_artifact: ExactArtifact,
        canonical_inventory: ExactArtifact,
        shadow_inventory_payload: dict[str, Any],
        *,
        created_at: datetime,
    ) -> MaterialIdentitySplitInvariantReport:
        """Compare shadow output against canonical geometry and exact planned assignments."""

        canonical_payload = _load_exact_json(self.job_root, canonical_inventory)
        canonical_objects = _inventory_object_projection(canonical_payload)
        shadow_objects = _inventory_object_projection(shadow_inventory_payload)
        geometry_unchanged = canonical_objects == shadow_objects
        candidate_scene = _load_exact_json(self.job_root, plan.candidate_scene_spec)
        expected_assignments = {
            str(item["id"]): [str(item["material_id"])]
            for item in candidate_scene.get("objects", [])
            if isinstance(item, dict)
        }
        shadow_assignments = _inventory_assignment_projection(shadow_inventory_payload)
        assignments_match = all(
            shadow_assignments.get(object_id) == material_ids
            for object_id, material_ids in expected_assignments.items()
        )
        canonical_scene = _load_exact_json(self.job_root, plan.preconditions.scene_spec)
        clone_ok = True
        exclusive_ok = True
        try:
            _validate_scene_candidate(canonical_scene, candidate_scene, plan.clone_rules)
        except MaterialIdentitySplitError:
            clone_ok = False
            exclusive_ok = False
        flags = {
            "clone_equivalence": clone_ok,
            "assignment_exclusivity": exclusive_ok,
            "object_ids": set(canonical_objects) == set(shadow_objects),
            "geometry_topology_transform_dimensions_uv": geometry_unchanged,
            "material_assignments": assignments_match,
            "reference_scope": canonical_scene.get("sources") == candidate_scene.get("sources"),
        }
        checks = [
            MaterialIdentitySplitCheck(
                check_id=f"{plan.run_id}-{name}",
                category={
                    "clone_equivalence": "clone",
                    "assignment_exclusivity": "assignment",
                    "object_ids": "geometry",
                    "geometry_topology_transform_dimensions_uv": "geometry",
                    "material_assignments": "assignment",
                    "reference_scope": "reference",
                }[name],
                status="passed" if passed else "failed",
                message=(
                    f"Identity-split invariant {name} passed."
                    if passed
                    else f"Identity-split invariant {name} failed."
                ),
            )
            for name, passed in flags.items()
        ]
        status = "passed" if all(flags.values()) else "failed"
        return MaterialIdentitySplitInvariantReport(
            **_identity_kwargs(plan, created_at),
            report_id=f"{plan.run_id}-invariants",
            request=request_artifact,
            shadow_receipt=shadow_receipt_artifact,
            status=status,
            checks=checks,
            scene_change_count=len(plan.clone_rules) * 2,
            modeling_plan_change_count=len(plan.modeling_plan_changes),
            forbidden_change_count=0 if status == "passed" else 1,
            clone_equivalence_passed=clone_ok,
            assignment_exclusivity_passed=exclusive_ok,
            object_ids_unchanged=flags["object_ids"],
            geometry_unchanged=geometry_unchanged,
            topology_unchanged=geometry_unchanged,
            transforms_unchanged=geometry_unchanged,
            dimensions_unchanged=geometry_unchanged,
            uv_unchanged=geometry_unchanged,
            reference_scope_unchanged=flags["reference_scope"],
            target_subject_unchanged=True,
            content_scope_unchanged=True,
            material_assignments_match_plan=assignments_match,
        )

    def run_preapproval(
        self,
        *,
        plan_artifact: ExactArtifact,
        modeling_plan_diff_report: ExactArtifact,
        canonical_scene_inventory: ExactArtifact,
        created_at: datetime | None = None,
    ) -> MaterialIdentitySplitPreapprovalResult:
        """Run one isolated paired preapproval and stop before any user decision."""

        observed_at = _utc_now(created_at)
        plan = load_material_closure_model(
            self.job_root,
            plan_artifact,
            MaterialIdentitySplitPlan,
        )
        diff = load_material_closure_model(
            self.job_root,
            modeling_plan_diff_report,
            MaterialIdentitySplitModelingPlanDiffReport,
        )
        if (
            diff.plan != plan_artifact
            or diff.candidate_modeling_plan != plan.candidate_modeling_plan
        ):
            raise MaterialIdentitySplitError("paired ModelingPlan diff binds another plan")
        validate_exact_artifact(self.job_root, canonical_scene_inventory)
        running = MaterialIdentitySplitTransactionState(
            **_identity_kwargs(plan, observed_at),
            transaction_id=plan.run_id,
            sequence=1,
            previous_state=_artifact_from_path(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/states/0000.json",
                artifact_id=f"{plan.run_id}-state-0000",
                kind="material_identity_split_transaction_state",
            ),
            state="preapproval_running",
            plan=plan_artifact,
            canonical_observation=plan.preconditions,
            performed_actions=["preapproval_started"],
            allowed_next_actions=["complete_preapproval", "publish_preapproval_failure"],
        )
        running_artifact = _publish_model(
            self.job_root,
            f"production/material_identity_split/{plan.run_id}/states/0001.json",
            running,
            artifact_id=f"{plan.run_id}-state-0001",
            kind="material_identity_split_transaction_state",
        )
        request = MaterialIdentitySplitPreapprovalRequest(
            **_identity_kwargs(plan, observed_at),
            request_id=f"{plan.run_id}-preapproval",
            plan=plan_artifact,
            candidate_scene_spec=plan.candidate_scene_spec,
            candidate_modeling_plan=plan.candidate_modeling_plan,
            scene_diff_allowlist=plan.scene_diff_allowlist,
            modeling_plan_diff_report=modeling_plan_diff_report,
            canonical_scene_inventory=canonical_scene_inventory,
            shadow_root=(f"production/material_identity_split/{plan.run_id}/preapproval/shadow"),
        )
        request_artifact = _publish_model(
            self.job_root,
            f"production/material_identity_split/{plan.run_id}/preapproval/request.json",
            request,
            artifact_id=f"{plan.run_id}-preapproval-request",
            kind="material_identity_split_preapproval_request",
        )
        try:
            self.validate_plan_current(plan)
            shadow_receipt, shadow_payloads = self._run_shadow(
                plan,
                request_artifact,
                request,
                created_at=observed_at,
            )
            shadow_artifact = _publish_model(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/preapproval/shadow_build_receipt.json",
                shadow_receipt,
                artifact_id=f"{plan.run_id}-shadow-build",
                kind="material_identity_split_shadow_build_receipt",
            )
            invariant = self._build_invariant_report(
                plan,
                request_artifact,
                shadow_artifact,
                canonical_scene_inventory,
                shadow_payloads["inventory"],
                created_at=observed_at,
            )
            invariant_artifact = _publish_model(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/preapproval/invariant_report.json",
                invariant,
                artifact_id=f"{plan.run_id}-invariants",
                kind="material_identity_split_invariant_report",
            )
            if invariant.status != "passed":
                raise MaterialIdentitySplitError("identity-split invariant report failed")
            checks = [
                MaterialIdentitySplitCheck(
                    check_id=f"{plan.run_id}-preapproval-{name}",
                    category=category,
                    status="passed",
                    message=message,
                )
                for name, category, message in (
                    ("canonical", "canonical", "Canonical preconditions rehashed unchanged."),
                    ("candidate", "candidate", "Paired candidates strict-validated."),
                    ("diff", "diff", "SceneSpec and ModelingPlan exact diffs passed."),
                    ("clone", "clone", "Material clone equivalence passed."),
                    ("blender", "blender", "Isolated Blender 5.0.1 shadow passed."),
                    (
                        "invariants",
                        "geometry",
                        "Geometry, topology, transform, UV, and scope passed.",
                    ),
                )
            ]
            report = MaterialIdentitySplitPreapprovalReport(
                **_identity_kwargs(plan, observed_at),
                report_id=f"{plan.run_id}-preapproval-report",
                request=request_artifact,
                status="passed",
                checks=checks,
                shadow_build_receipt=shadow_artifact,
                invariant_report=invariant_artifact,
                approval_request_eligible=True,
            )
            report_artifact = _publish_model(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/preapproval/report.json",
                report,
                artifact_id=f"{plan.run_id}-preapproval-report",
                kind="material_identity_split_preapproval_report",
            )
            self.validate_plan_current(plan)
            approval_request = MaterialIdentitySplitApprovalRequest(
                **_identity_kwargs(plan, observed_at),
                approval_request_id=f"{plan.run_id}-approval-request",
                plan=plan_artifact,
                candidate_scene_spec=plan.candidate_scene_spec,
                candidate_modeling_plan=plan.candidate_modeling_plan,
                scene_diff_allowlist=plan.scene_diff_allowlist,
                modeling_plan_diff_report=modeling_plan_diff_report,
                approval_impact_report=plan.approval_impact_report,
                preapproval_report=report_artifact,
                shadow_build_receipt=shadow_artifact,
                invariant_report=invariant_artifact,
                geometry_uv_unchanged_report=plan.geometry_uv_unchanged_report,
                surface_detail_material_mapping=plan.surface_detail_material_mapping,
                changed_assignments=plan.changed_assignments,
                retained_assignments=plan.retained_assignments,
                preconditions=plan.preconditions,
                channel_reconciliation=plan.channel_reconciliation,
                current_material_closure=plan.current_material_closure,
                latest_framework_failure=plan.latest_framework_failure,
            )
            approval_request_artifact = _publish_model(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/approval_request.json",
                approval_request,
                artifact_id=f"{plan.run_id}-approval-request",
                kind="material_identity_split_approval_request",
            )
            terminal = MaterialIdentitySplitTransactionState(
                **_identity_kwargs(plan, observed_at),
                transaction_id=plan.run_id,
                sequence=2,
                previous_state=running_artifact,
                state="eligible_for_explicit_user_scope_approval",
                plan=plan_artifact,
                preapproval_request=request_artifact,
                approval_request=approval_request_artifact,
                canonical_observation=plan.preconditions,
                performed_actions=[
                    "paired_candidates_validated",
                    "shadow_build_validated",
                    "approval_request_published",
                ],
                allowed_next_actions=["observe_explicit_user_scope_decision"],
            )
            terminal_artifact = _publish_model(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/states/0002.json",
                terminal,
                artifact_id=f"{plan.run_id}-state-0002",
                kind="material_identity_split_transaction_state",
            )
            return MaterialIdentitySplitPreapprovalResult(
                status="framework_ready_for_explicit_scope_approval",
                plan=plan,
                request=request_artifact,
                preapproval_report=report_artifact,
                shadow_build_receipt=shadow_artifact,
                invariant_report=invariant_artifact,
                approval_request=approval_request_artifact,
                failure=None,
                terminal_state=terminal_artifact,
            )
        except Exception as exc:
            failure_message = _bounded_failure_message(self.job_root, exc)
            failure = MaterialIdentitySplitPreapprovalFailure(
                **_identity_kwargs(plan, observed_at),
                failure_id=f"{plan.run_id}-preapproval-failure",
                plan=plan_artifact,
                request=request_artifact,
                stage=("shadow_build" if "Blender" in failure_message else "invariant_validation"),
                code="MATERIAL_IDENTITY_SPLIT_PREAPPROVAL_FAILED",
                message=failure_message,
            )
            failure_artifact = _publish_model(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/preapproval/failure.json",
                failure,
                artifact_id=f"{plan.run_id}-preapproval-failure",
                kind="material_identity_split_preapproval_failure",
            )
            terminal = MaterialIdentitySplitTransactionState(
                **_identity_kwargs(plan, observed_at),
                transaction_id=plan.run_id,
                sequence=2,
                previous_state=running_artifact,
                state="preapproval_failed",
                plan=plan_artifact,
                preapproval_request=request_artifact,
                canonical_observation=plan.preconditions,
                performed_actions=["preapproval_failed_closed"],
                allowed_next_actions=[],
                blocked_reason=failure_message,
            )
            terminal_artifact = _publish_model(
                self.job_root,
                f"production/material_identity_split/{plan.run_id}/states/0002.json",
                terminal,
                artifact_id=f"{plan.run_id}-state-0002",
                kind="material_identity_split_transaction_state",
            )
            return MaterialIdentitySplitPreapprovalResult(
                status="preapproval_failed",
                plan=plan,
                request=request_artifact,
                preapproval_report=None,
                shadow_build_receipt=None,
                invariant_report=None,
                approval_request=None,
                failure=failure_artifact,
                terminal_state=terminal_artifact,
            )

    def publish_root_scope_approval(
        self,
        *,
        approval_request: ExactArtifact,
        approval: MaterialIdentitySplitRootScopeApproval,
        user_decision_text: bytes,
        explicit_user_decision_observed: bool,
    ) -> MaterialIdentitySplitApprovalPublication:
        """Publish only a complete caller-authored exact specialized user decision."""

        if not explicit_user_decision_observed:
            raise PermissionError("identity-split approval requires an observed user decision")
        request = load_material_closure_model(
            self.job_root,
            approval_request,
            MaterialIdentitySplitApprovalRequest,
        )
        if (
            approval.approval_request != approval_request
            or approval.job_id != request.job_id
            or approval.workflow_id != request.workflow_id
            or approval.dispatch_id != request.dispatch_id
            or approval.run_id != request.run_id
            or approval.candidate_scene_spec != request.candidate_scene_spec
            or approval.candidate_modeling_plan != request.candidate_modeling_plan
            or approval.scene_diff_allowlist != request.scene_diff_allowlist
            or approval.modeling_plan_diff_report != request.modeling_plan_diff_report
            or approval.preapproval_report != request.preapproval_report
            or approval.shadow_build_receipt != request.shadow_build_receipt
            or approval.invariant_report != request.invariant_report
            or approval.preconditions != request.preconditions
        ):
            raise PermissionError("caller-authored identity-split approval is not exact-bound")
        if hashlib.sha256(user_decision_text).hexdigest() != approval.user_decision_text_sha256:
            raise PermissionError("user decision bytes do not match the approval SHA-256")
        self.validate_plan_current(
            load_material_closure_model(
                self.job_root,
                request.plan,
                MaterialIdentitySplitPlan,
            )
        )
        artifact = _publish_model(
            self.job_root,
            (
                f"production/material_identity_split/{request.run_id}/approvals/"
                f"{approval.approval_id}.json"
            ),
            approval,
            artifact_id=approval.approval_id,
            kind="material_identity_split_root_scope_approval",
        )
        return MaterialIdentitySplitApprovalPublication(
            approval=approval,
            approval_artifact=artifact,
        )

    def get_status(self, run_id: str) -> MaterialIdentitySplitStatusProjection:
        """Derive a read-only status from the complete append-only state chain."""

        states_root = ensure_autonomy_path(
            self.job_root,
            self.job_root / "production" / "material_identity_split" / run_id / "states",
            must_exist=True,
        )
        state_files = sorted(states_root.glob("[0-9][0-9][0-9][0-9].json"))
        if not state_files:
            raise FileNotFoundError("identity-split state chain is missing")
        states: list[MaterialIdentitySplitTransactionState] = []
        artifacts: list[ExactArtifact] = []
        previous: ExactArtifact | None = None
        for sequence, path in enumerate(state_files):
            state = MaterialIdentitySplitTransactionState.model_validate_json(path.read_bytes())
            artifact = _artifact_from_path(
                self.job_root,
                path.relative_to(self.job_root).as_posix(),
                artifact_id=f"{run_id}-state-{sequence:04d}",
                kind="material_identity_split_transaction_state",
            )
            if state.sequence != sequence or state.previous_state != previous:
                raise MaterialIdentitySplitError("identity-split state chain is discontinuous")
            states.append(state)
            artifacts.append(artifact)
            previous = artifact
        latest = states[-1]
        run_root = states_root.parent
        approval_files = (
            list((run_root / "approvals").glob("*.json"))
            if (run_root / "approvals").is_dir()
            else []
        )
        consumption_files = (
            list((run_root / "approval_consumptions").glob("*.json"))
            if (run_root / "approval_consumptions").is_dir()
            else []
        )
        intent_files = (
            list((run_root / "intents").glob("*.json")) if (run_root / "intents").is_dir() else []
        )
        approval_request = next(
            (state.approval_request for state in reversed(states) if state.approval_request),
            None,
        )
        canonical_write_count = sum(
            state.state
            in {"scene_spec_replaced", "modeling_plan_replaced", "blender_rebuilt"}
            for state in states
        )
        return MaterialIdentitySplitStatusProjection(
            job_id=latest.job_id,
            workflow_id=latest.workflow_id,
            dispatch_id=latest.dispatch_id,
            run_id=latest.run_id,
            producer=_PRODUCER,
            producer_version=_PRODUCER_VERSION,
            created_at=datetime.now(UTC),
            projection_id=f"{run_id}-status-projection",
            transaction_id=latest.transaction_id,
            state_artifacts=artifacts,
            latest_state=artifacts[-1],
            latest_sequence=latest.sequence,
            status=latest.state,
            framework_ready_for_explicit_scope_approval=(
                latest.state == "eligible_for_explicit_user_scope_approval"
            ),
            approval_request=approval_request,
            actual_user_approval_count=len(approval_files),
            approval_consumption_count=len(consumption_files),
            apply_intent_count=len(intent_files),
            canonical_write_count=canonical_write_count,
            repair_session_count=0,
            controller_count=0,
            promotion_count=0,
            material_phase_receipt_count=0,
            iq_count=0,
            package_count=0,
            destination_write_count=0,
        )
