"""Exact-approved append-only recovery for localized spatial surface-detail contracts."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from pydantic import Field, model_validator

from ..analysis.models import ModelingPlan
from ..analysis.surface_details import validate_surface_detail_contract
from ..autonomy.worker import autonomy_session_lock
from ..blender_artifacts import (
    deterministic_directory_files,
    native_io_path,
    sha256_file,
    stable_json_digest,
)
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..material_graph.models import (
    BakePolicy,
    ChannelBinding,
    MaterialGraphArtifact,
    MaterialGraphProvenance,
    MaterialGraphSpec,
    NormalDisplacementPolicy,
    PreviewLightingPolicy,
    TextureScale,
)
from ..materials.io import load_shader_recipe
from ..materials.models import MaterialPlan, MaterialPlanItem, ShaderRecipe
from ..models import SceneSpec
from ..production.controller_executor import (
    ControllerArtifact,
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
    execute_controller_request,
    validate_controller_execution_result,
    write_controller_contract,
)
from ..production.validation import ensure_contained_production_path
from ..stabilization.models import PortableId, RelativePath, Sha256
from ..texturing.models import (
    SurfaceDetailBinding,
    SurfaceDetailPlacement,
    TextureChannel,
    TextureManifest,
    TextureProvenance,
)
from ..texturing.procedural_provider import generate_procedural_pbr
from ..workspace import job_dir
from .delivery_service import (
    artifact_for_v2,
    write_immutable_v2_model,
)
from .material_phase_models import MaterialControllerCompletionV2
from .models import (
    AQV2Artifact,
    AQV2Evidence,
    AQV2StrictModel,
    AutonomyBudgetV2,
    AutonomyProfileV2,
    AutonomyStateV2,
    BudgetUsageV2,
)
from .transitions import transition_state

_PRODUCER = "codex_blender_modeler.autonomy_v2.surface_detail_spatial_recovery"
_RECOVERY_DIR = "surface_detail_spatial_recoveries"
_EXPECTED_BASE_PROFILE = "autonomous_static_prop_v2"
_EXPECTED_PROFILE = "autonomous_static_prop_v2_codex_imagegen"
_EXPECTED_REFERENCE_SHA256 = "dd2ecc1bfeb403595d8a4f77875980fd7cad7d29582d661a248fa2d639c846bf"
_EXPECTED_REFERENCE_IMAGEGEN_SHA256 = (
    "6b3ad58f645f74a05cc4dd4b0388a81d9f7a2ae1b9c0a8de3fd42f082ac900d4"
)
_ADDITIVE_MATERIAL_IDS = (
    "mat.metal.trim.filigree_body",
    "mat.crystal.translucent.facet_crown",
)
_ASSIGNMENT_SPECIALIZATIONS = {
    "prop.crystalgun.frame.trim": "mat.metal.trim.filigree_body",
    "prop.crystalgun.rear.crown": "mat.crystal.translucent.facet_crown",
}
_DETAIL_CONTRACTS: dict[str, dict[str, object]] = {
    "detail.filigree.body": {
        "parent_object_id": "prop.crystalgun.frame.trim",
        "source_material_id": "mat.metal.trim",
        "material_id": "mat.metal.trim.filigree_body",
        "texture_strategy": "hybrid",
        "channels": ["base_color", "roughness", "emission"],
        "resolution": (512, 512),
        "preset": "crystalgun_ornate_gold",
        "pattern": "ornate_filigree",
        "strength": 0.72,
    },
    "detail.filigree.grip": {
        "parent_object_id": "prop.crystalgun.grip.inlay",
        "source_material_id": "mat.grip.leather",
        "material_id": "mat.grip.leather",
        "texture_strategy": "hybrid",
        "channels": ["base_color", "roughness"],
        "resolution": (256, 256),
        "preset": "crystalgun_dark_leather",
        "pattern": "grip_filigree",
        "strength": 0.62,
    },
    "detail.crystal.internal_emission": {
        "parent_object_id": "prop.crystalgun.barrel.core",
        "source_material_id": "mat.crystal.emission",
        "material_id": "mat.crystal.emission",
        "texture_strategy": "image",
        "channels": ["emission"],
        "resolution": (1024, 1024),
        "strength": 1.0,
    },
    "detail.crystal.facet_lines": {
        "parent_object_id": "prop.crystalgun.rear.crown",
        "source_material_id": "mat.crystal.translucent",
        "material_id": "mat.crystal.translucent.facet_crown",
        "texture_strategy": "hybrid",
        "channels": ["base_color", "roughness"],
        "resolution": (512, 512),
        "preset": "crystalgun_mint_crystal",
        "pattern": "crystal_facet_lines",
        "strength": 0.68,
    },
}


class SurfaceDetailSpatialControllerInput(AQV2StrictModel):
    """Bind one exact-copy controller assignment to approved recovery blueprints."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    assignment_id: PortableId
    job_id: str
    workflow_id: str
    dispatch_id: PortableId
    session_id: PortableId
    recovery_id: PortableId
    recovery_plan_sha256: Sha256
    source_aq_state_sha256: Sha256
    candidate_scene_spec: AQV2Artifact
    candidate_modeling_plan: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    candidate_material_graph: AQV2Artifact
    source_material_plan_sha256: Sha256
    phase_tool_profile_sha256: Sha256
    immutable_input_sha256: dict[RelativePath, Sha256] = Field(min_length=4)
    allowed_output_paths: list[RelativePath] = Field(min_length=3, max_length=3)
    expected_output_sha256: dict[RelativePath, Sha256] = Field(min_length=2, max_length=2)
    new_imagegen_invocation_allowed: Literal[False] = False
    canonical_write_authority: Literal["supervisor_only"] = "supervisor_only"

    @model_validator(mode="after")
    def validate_spatial_assignment(self) -> SurfaceDetailSpatialControllerInput:
        """Require the two exact material outputs plus one controller completion leaf."""

        names = [PurePosixPath(item).name for item in self.allowed_output_paths]
        if names != ["material_plan.json", "material_graph.json", "completion.json"]:
            raise ValueError("spatial recovery controller outputs are not exact")
        expected = {
            self.allowed_output_paths[0]: self.candidate_material_plan.sha256,
            self.allowed_output_paths[1]: self.candidate_material_graph.sha256,
        }
        if self.expected_output_sha256 != expected:
            raise ValueError("spatial recovery expected hashes differ from blueprints")
        logical_scene = self.immutable_input_sha256.get("analysis/scene_spec.json")
        if logical_scene != self.candidate_scene_spec.sha256:
            raise ValueError("spatial recovery assignment omits the candidate SceneSpec")
        if self.candidate_material_plan.sha256 not in self.immutable_input_sha256.values():
            raise ValueError("spatial recovery assignment omits its MaterialPlan blueprint")
        if self.candidate_material_graph.sha256 not in self.immutable_input_sha256.values():
            raise ValueError("spatial recovery assignment omits its MaterialGraph blueprint")
        return self


class SurfaceDetailSpatialRecoveryPreparation(AQV2Evidence):
    """Freeze exact approval, source closure, and host-authored recovery candidates."""

    recovery_id: PortableId
    recovery_plan: AQV2Artifact
    approval: AQV2Artifact
    source_aq_state: AQV2Artifact
    source_material_loop_state: AQV2Artifact
    source_material_loop_terminal: AQV2Artifact
    source_retry_receipt: AQV2Artifact
    source_bridge_plan: AQV2Artifact
    rollback_receipt: AQV2Artifact
    source_scene_spec: AQV2Artifact
    source_modeling_plan: AQV2Artifact
    source_rollback_blend: AQV2Artifact
    source_inventory: AQV2Artifact
    source_build_provenance: AQV2Artifact
    candidate_scene_spec: AQV2Artifact
    candidate_modeling_plan: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    candidate_material_graph: AQV2Artifact
    texture_manifests: list[AQV2Artifact] = Field(min_length=4, max_length=4)
    shader_recipes: list[AQV2Artifact] = Field(min_length=4, max_length=4)
    texture_channels: list[AQV2Artifact] = Field(min_length=8)
    imagegen_source: AQV2Artifact
    imagegen_semantic_review: AQV2Artifact
    additive_material_ids: list[str] = Field(min_length=2, max_length=2)
    material_assignment_specializations: dict[str, str] = Field(min_length=2, max_length=2)
    status: Literal["prepared"] = "prepared"
    geometry_topology_changed: Literal[False] = False
    semantic_ids_changed: Literal[False] = False
    existing_material_ids_changed: Literal[False] = False
    imagegen_invocation_performed: Literal[False] = False
    human_reviewed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_preparation_scope(self) -> SurfaceDetailSpatialRecoveryPreparation:
        """Require exact named provenance and the approved additive material delta."""

        named = [
            self.recovery_plan,
            self.approval,
            self.source_aq_state,
            self.source_material_loop_state,
            self.source_material_loop_terminal,
            self.source_retry_receipt,
            self.source_bridge_plan,
            self.rollback_receipt,
            self.source_scene_spec,
            self.source_modeling_plan,
            self.source_rollback_blend,
            self.source_inventory,
            self.source_build_provenance,
            self.candidate_scene_spec,
            self.candidate_modeling_plan,
            self.candidate_material_plan,
            self.candidate_material_graph,
            *self.texture_manifests,
            *self.shader_recipes,
            *self.texture_channels,
            self.imagegen_source,
            self.imagegen_semantic_review,
        ]
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("spatial recovery preparation provenance is incomplete")
        if self.additive_material_ids != list(_ADDITIVE_MATERIAL_IDS):
            raise ValueError("spatial recovery additive material IDs changed")
        if self.material_assignment_specializations != _ASSIGNMENT_SPECIALIZATIONS:
            raise ValueError("spatial recovery assignments changed")
        if self.source_fingerprint != self.source_material_loop_terminal.sha256:
            raise ValueError("spatial recovery source terminal changed")
        return self


class SurfaceDetailSpatialGeometryReviewReceipt(AQV2Evidence):
    """Bind one exact ControllerExecutor result to unchanged-topology Blender evidence."""

    recovery_id: PortableId
    preparation: AQV2Artifact
    controller_profile: AQV2Artifact
    controller_assignment: AQV2Artifact
    controller_request: AQV2Artifact
    controller_result: AQV2Artifact
    controller_completion: AQV2Artifact
    candidate_scene_spec: AQV2Artifact
    candidate_modeling_plan: AQV2Artifact
    candidate_material_plan: AQV2Artifact
    candidate_material_graph: AQV2Artifact
    candidate_blend: AQV2Artifact
    candidate_inventory: AQV2Artifact
    candidate_validation: AQV2Artifact
    candidate_build_provenance: AQV2Artifact
    surface_detail_validation: AQV2Artifact
    topology_comparison: AQV2Artifact
    preview: AQV2Artifact
    material_binding_derivative: AQV2Artifact | None = None
    blender_version: Literal["5.0.1"]
    surface_detail_failed_count: Literal[0] = 0
    topology_unchanged: Literal[True] = True
    semantic_ids_unchanged: Literal[True] = True
    geometry_review_required: Literal[True] = True
    material_promoted: Literal[False] = False
    canonical_scene_unchanged: Literal[True] = True
    human_reviewed: Literal[False] = False
    destination_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_geometry_review_evidence(self) -> SurfaceDetailSpatialGeometryReviewReceipt:
        """Require provenance to equal every named controller and Blender artifact."""

        named = [
            self.preparation,
            self.controller_profile,
            self.controller_assignment,
            self.controller_request,
            self.controller_result,
            self.controller_completion,
            self.candidate_scene_spec,
            self.candidate_modeling_plan,
            self.candidate_material_plan,
            self.candidate_material_graph,
            self.candidate_blend,
            self.candidate_inventory,
            self.candidate_validation,
            self.candidate_build_provenance,
            self.surface_detail_validation,
            self.topology_comparison,
            self.preview,
        ]
        if self.material_binding_derivative is not None:
            named.append(self.material_binding_derivative)
        expected = {(item.path, item.sha256, item.byte_size) for item in named}
        observed = {(item.path, item.sha256, item.byte_size) for item in self.provenance}
        if expected != observed or len(expected) != len(self.provenance):
            raise ValueError("spatial geometry review provenance is incomplete")
        if self.source_fingerprint != self.controller_result.sha256:
            raise ValueError("spatial geometry review source result changed")
        return self


class SurfaceDetailSpatialGeometryReviewPlan(AQV2StrictModel):
    """Declare the exact user decision boundary after isolated geometry validation."""

    schema_version: Literal["0.1.0"] = "0.1.0"
    plan_id: PortableId
    status: Literal["awaiting_user_approval"] = "awaiting_user_approval"
    job_id: str
    source_session_id: PortableId
    source_aq_state_sha256: Sha256
    recovery_plan_sha256: Sha256
    recovery_preparation_sha256: Sha256
    controller_result_sha256: Sha256
    candidate_scene_spec_v02_sha256: Sha256
    candidate_modeling_plan_sha256: Sha256
    candidate_material_plan_sha256: Sha256
    candidate_material_graph_sha256: Sha256
    candidate_blend_sha256: Sha256
    candidate_inventory_sha256: Sha256
    candidate_validation_sha256: Sha256
    topology_comparison_sha256: Sha256
    surface_detail_validation_sha256: Sha256
    preview_sha256: Sha256
    geometry_review_receipt_sha256: Sha256
    material_binding_derivative_sha256: Sha256 | None = None
    additive_material_ids: list[str]
    material_assignment_specializations: dict[str, str]
    topology_unchanged: Literal[True] = True
    semantic_ids_unchanged: Literal[True] = True
    material_promotion_allowed: Literal[False] = False
    delivery_disabled: Literal[True] = True
    optimization_disabled: Literal[True] = True
    lod_disabled: Literal[True] = True
    collider_disabled: Literal[True] = True
    destination_write_disabled: Literal[True] = True
    approval_granted: Literal[False] = False


class ExactSurfaceDetailSpatialMaterialController:
    """Copy exact approved material blueprints inside one ControllerExecutor workspace."""

    controller_kind = "desktop_in_session"

    @staticmethod
    def _read_bytes(path: Path) -> bytes:
        """Read one controller snapshot using the native long-path representation."""

        with open(native_io_path(path), "rb") as handle:
            return handle.read()

    @staticmethod
    def _write_exact(path: Path, payload: bytes) -> None:
        """Write one output once and adopt only byte-identical replay bytes."""

        os.makedirs(native_io_path(path.parent), exist_ok=True)
        if os.path.exists(native_io_path(path)):
            with open(native_io_path(path), "rb") as handle:
                if handle.read() != payload:
                    raise FileExistsError("spatial controller output differs on replay")
            return
        with open(native_io_path(path), "xb") as handle:
            handle.write(payload)

    @staticmethod
    def _snapshot_by_sha256(immutable_inputs: tuple[Path, ...], expected_sha256: str) -> Path:
        """Select exactly one immutable input snapshot by its approved digest."""

        matches = [item for item in immutable_inputs if sha256_file(item) == expected_sha256]
        if len(matches) != 1:
            raise ValueError("spatial controller blueprint snapshot is not unique")
        return matches[0]

    @staticmethod
    def _execution_id(allowed_output_paths: tuple[Path, ...]) -> str:
        """Recover the request execution ID from the ControllerExecutor workspace path."""

        if not allowed_output_paths:
            raise ValueError("spatial controller received no allowed outputs")
        parts = allowed_output_paths[0].parts
        indices = [
            index for index, part in enumerate(parts[:-1]) if part == "controller_executions"
        ]
        if len(indices) != 1 or indices[0] + 1 >= len(parts):
            raise ValueError("spatial controller cannot resolve execution identity")
        return parts[indices[0] + 1]

    def execute(
        self,
        *,
        assignment: Path,
        immutable_inputs: tuple[Path, ...],
        allowed_output_paths: tuple[Path, ...],
        tool_profile: PhaseToolProfile,
        timeout_seconds: int,
    ) -> str:
        """Publish exact material blueprints and a host-validated completion contract."""

        del timeout_seconds
        payload = SurfaceDetailSpatialControllerInput.model_validate_json(
            self._read_bytes(assignment)
        )
        if tool_profile.profile_id != "material_authoring":
            raise PermissionError("spatial recovery requires the material profile")
        outputs = {item.name: item for item in allowed_output_paths}
        if set(outputs) != {"material_plan.json", "material_graph.json", "completion.json"}:
            raise ValueError("spatial controller output boundary changed")
        plan_source = self._snapshot_by_sha256(
            immutable_inputs, payload.candidate_material_plan.sha256
        )
        graph_source = self._snapshot_by_sha256(
            immutable_inputs, payload.candidate_material_graph.sha256
        )
        self._write_exact(outputs["material_plan.json"], self._read_bytes(plan_source))
        self._write_exact(outputs["material_graph.json"], self._read_bytes(graph_source))
        output_by_name = {PurePosixPath(item).name: item for item in payload.allowed_output_paths}
        completion = MaterialControllerCompletionV2(
            completion_id=f"material-completion-{payload.recovery_id}",
            job_id=payload.job_id,
            workflow_id=payload.workflow_id,
            dispatch_id=payload.dispatch_id,
            session_id=payload.session_id,
            execution_id=self._execution_id(allowed_output_paths),
            assignment_sha256=sha256_file(assignment),
            tool_profile_sha256=payload.phase_tool_profile_sha256,
            immutable_input_sha256=payload.immutable_input_sha256,
            source_scene_spec_sha256=payload.candidate_scene_spec.sha256,
            source_material_plan_sha256=None,
            material_plan_path=output_by_name["material_plan.json"],
            material_plan_sha256=payload.candidate_material_plan.sha256,
            material_graph_path=output_by_name["material_graph.json"],
            material_graph_sha256=payload.candidate_material_graph.sha256,
        )
        self._write_exact(
            outputs["completion.json"],
            (completion.model_dump_json(indent=2) + "\n").encode("utf-8"),
        )
        return "completed"


def _model_bytes(
    model: AQV2StrictModel
    | SceneSpec
    | ModelingPlan
    | MaterialPlan
    | ShaderRecipe
    | TextureManifest
    | MaterialGraphSpec,
) -> bytes:
    """Serialize one strict model with stable UTF-8 JSON formatting."""

    return (model.model_dump_json(indent=2, exclude_none=False) + "\n").encode("utf-8")


def _write_exact_bytes(path: Path, payload: bytes) -> None:
    """Publish one immutable file or adopt only byte-identical existing evidence."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    if os.path.exists(native_io_path(path)):
        with open(native_io_path(path), "rb") as handle:
            if handle.read() != payload:
                raise FileExistsError(f"immutable recovery artifact differs: {path.name}")
        return
    with open(native_io_path(path), "xb") as handle:
        handle.write(payload)


def _write_model(path: Path, model: Any) -> None:
    """Publish one Pydantic model through the immutable byte writer."""

    _write_exact_bytes(path, _model_bytes(model))


def _write_or_adopt_v2_model(
    *,
    root: Path,
    path: Path,
    model: AQV2StrictModel,
    kind: str,
) -> AQV2Artifact:
    """Write one AQ v2 model once or adopt an existing semantically identical record."""

    if os.path.exists(native_io_path(path)):
        with open(native_io_path(path), "rb") as handle:
            existing = type(model).model_validate_json(handle.read())
        if existing.model_dump(mode="json", exclude={"created_at"}) != model.model_dump(
            mode="json", exclude={"created_at"}
        ):
            raise FileExistsError(f"existing AQ v2 recovery record differs: {path.name}")
    else:
        write_immutable_v2_model(root, path, model)
    return artifact_for_v2(
        root,
        path,
        artifact_id=model.contract_id,
        kind=kind,
    )


def _artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Create one exact AQ v2 artifact after contained-path validation."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    return artifact_for_v2(
        root,
        safe,
        artifact_id=artifact_id,
        kind=kind,
    )


def _controller_artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    role: str,
) -> ControllerArtifact:
    """Project one contained immutable file into ControllerExecutor evidence."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    return ControllerArtifact(
        artifact_id=artifact_id,
        role=role,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=os.path.getsize(native_io_path(safe)),
    )


def _find_single_hash(root: Path, expected_sha256: str) -> Path:
    """Find exactly one regular JSON evidence file beneath a bounded source root."""

    matches: list[Path] = []
    for path in sorted(root.rglob("*.json")):
        if path.is_symlink() or not path.is_file():
            continue
        if sha256_file(path) == expected_sha256:
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(
            f"expected one source artifact with SHA-256 {expected_sha256}, found {len(matches)}"
        )
    return matches[0]


def _expected_recovery_approval(payload: dict[str, Any], plan_sha256: str) -> str:
    """Render the sole exact user approval accepted for this spatial recovery plan."""

    return (
        "APPROVE MATERIAL SURFACE DETAIL SPATIAL RECOVERY "
        f"job_id={payload['job_id']} source_session_id={payload['source_session_id']} "
        f"source_aq_state_sha256={payload['source_aq_state_sha256']} "
        f"source_material_loop_state_sha256={payload['source_material_loop_state_sha256']} "
        "source_material_loop_terminal_sha256="
        f"{payload['source_material_loop_terminal_sha256']} "
        f"recovery_plan_sha256={plan_sha256} "
        f"rollback_receipt_sha256={payload['rollback_receipt_sha256']} "
        f"source_scene_spec_v02_sha256={payload['source_scene_spec_v02_sha256']} "
        f"source_modeling_plan_sha256={payload['source_modeling_plan_sha256']} "
        f"source_rollback_blend_sha256={payload['source_rollback_blend_sha256']} "
        f"reference_sha256={payload['reference_sha256']} "
        "add_material_ids=mat.metal.trim.filigree_body,"
        "mat.crystal.translucent.facet_crown "
        "assignments=prop.crystalgun.frame.trim->mat.metal.trim.filigree_body,"
        "prop.crystalgun.rear.crown->mat.crystal.translucent.facet_crown "
        "details=detail.filigree.body,detail.filigree.grip,"
        "detail.crystal.internal_emission,detail.crystal.facet_lines "
        "new_controller_invocation_allowed=true controller_invocation_limit=1 "
        "new_imagegen_invocation_allowed=false preserve_geometry_topology=true "
        "preserve_semantic_ids=true preserve_existing_material_ids=true "
        "allow_additive_localized_material_ids=true "
        "scope=append_only_surface_detail_spatial_contract_recovery "
        "delivery_disabled=true optimization_disabled=true lod_disabled=true "
        "collider_disabled=true destination_write_disabled=true"
    )


def _validate_recovery_plan(
    payload: dict[str, Any],
    *,
    job_id: str,
    session_id: str,
) -> None:
    """Fail closed unless the plan retains the approved material-only authority ceiling."""

    required = {
        "status": "proposal_only",
        "job_id": job_id,
        "source_session_id": session_id,
        "profile_id": _EXPECTED_PROFILE,
        "profile_status": "disabled_experimental",
        "reference_sha256": _EXPECTED_REFERENCE_SHA256,
        "scope": "append_only_surface_detail_spatial_contract_recovery",
        "preserve_geometry_topology": True,
        "preserve_semantic_ids": True,
        "preserve_existing_material_ids": True,
        "allow_additive_localized_material_ids": True,
        "delivery_disabled": True,
        "optimization_disabled": True,
        "lod_disabled": True,
        "collider_disabled": True,
        "destination_write_disabled": True,
        "approval_granted": False,
    }
    if any(payload.get(key) != value for key, value in required.items()):
        raise ValueError("surface-detail spatial recovery authority fields changed")
    changes = payload.get("approved_changes_if_authorized")
    lifecycle = payload.get("required_lifecycle")
    if not isinstance(changes, dict) or not isinstance(lifecycle, dict):
        raise ValueError("surface-detail spatial recovery plan is incomplete")
    if changes.get("additive_material_ids") != list(_ADDITIVE_MATERIAL_IDS):
        raise ValueError("surface-detail spatial recovery material IDs changed")
    if changes.get("material_assignment_specializations") != _ASSIGNMENT_SPECIALIZATIONS:
        raise ValueError("surface-detail spatial recovery assignments changed")
    observed_contracts = changes.get("surface_detail_contracts")
    if not isinstance(observed_contracts, dict) or set(observed_contracts) != set(
        _DETAIL_CONTRACTS
    ):
        raise ValueError("surface-detail spatial recovery detail set changed")
    for detail_id, contract in _DETAIL_CONTRACTS.items():
        observed = observed_contracts[detail_id]
        expected = {
            "material_id": contract["material_id"],
            "texture_strategy": contract["texture_strategy"],
            "channels": contract["channels"],
        }
        if any(observed.get(key) != value for key, value in expected.items()):
            raise ValueError(f"surface-detail recovery contract changed: {detail_id}")
    lifecycle_required = {
        "append_only_recovery": True,
        "controller_executor_required": True,
        "new_controller_invocation_allowed": True,
        "controller_invocation_limit": 1,
        "new_imagegen_invocation_allowed": False,
        "reuse_imagegen_evidence": True,
        "deterministic_texture_derivatives_required": True,
        "geometry_topology_change_allowed": False,
        "semantic_id_change_allowed": False,
        "existing_material_id_removal_or_rename_allowed": False,
        "additive_material_ids_only": True,
        "geometry_revalidation_required": True,
        "new_geometry_review_approval_required": True,
        "material_promotion_before_geometry_review_allowed": False,
        "human_reviewed": False,
    }
    if any(lifecycle.get(key) != value for key, value in lifecycle_required.items()):
        raise ValueError("surface-detail spatial recovery lifecycle changed")


def _inventory_uv_fingerprints(inventory_path: Path) -> dict[str, str]:
    """Index current ordered polygon-corner UV fingerprints by semantic object ID."""

    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for record in payload.get("objects", []):
        object_id = record.get("cbm_id") if isinstance(record, dict) else None
        if not object_id:
            continue
        layer = next(
            (item for item in record.get("uv_layers", []) if item.get("name") == "UVMap"),
            None,
        )
        if layer and layer.get("vertex_uv_binding_fingerprint"):
            result[str(object_id)] = str(layer["vertex_uv_binding_fingerprint"])
    missing = sorted(
        str(contract["parent_object_id"])
        for contract in _DETAIL_CONTRACTS.values()
        if str(contract["parent_object_id"]) not in result
    )
    if missing:
        raise ValueError(f"source inventory lacks recovery UV fingerprints: {missing}")
    return result


def _scene_candidates(source: SceneSpec) -> SceneSpec:
    """Add two localized material definitions and specialize only approved assignments."""

    material_by_id = {item.id: item for item in source.materials}
    additions = [
        material_by_id["mat.metal.trim"].model_copy(
            update={
                "id": "mat.metal.trim.filigree_body",
                "name": "Localized bright metal body filigree",
            }
        ),
        material_by_id["mat.crystal.translucent"].model_copy(
            update={
                "id": "mat.crystal.translucent.facet_crown",
                "name": "Localized translucent crown facet lines",
            }
        ),
    ]
    objects = [
        item.model_copy(
            update={"material_id": _ASSIGNMENT_SPECIALIZATIONS.get(item.id, item.material_id)}
        )
        for item in source.objects
    ]
    candidate = source.model_copy(
        update={"materials": [*source.materials, *additions], "objects": objects}
    )
    return SceneSpec.model_validate(candidate.model_dump(mode="json"))


def _modeling_candidate(source: ModelingPlan) -> ModelingPlan:
    """Retarget only the two details whose prior materials were shared by other objects."""

    target_by_detail = {
        detail_id: str(contract["material_id"]) for detail_id, contract in _DETAIL_CONTRACTS.items()
    }
    details = [
        item.model_copy(update={"target_material_id": target_by_detail[item.id]})
        for item in source.surface_details
    ]
    candidate = source.model_copy(update={"surface_details": details})
    return ModelingPlan.model_validate(candidate.model_dump(mode="json"))


def _seed_for_detail(detail_id: str) -> int:
    """Derive one stable non-secret procedural seed from a semantic detail ID."""

    return int(sha256(detail_id.encode("utf-8")).hexdigest()[:8], 16)


def _spatial_staging_root(root: Path) -> Path:
    """Return the short, job-contained staging root required by Windows path limits."""

    return root / "a2" / "sdsr01"


def _texture_asset_path(root: Path, detail_id: str) -> Path:
    """Map one stable detail ID to a short contained recovery texture directory."""

    suffixes = {
        "detail.filigree.body": "fb",
        "detail.filigree.grip": "fg",
        "detail.crystal.internal_emission": "ce",
        "detail.crystal.facet_lines": "cf",
    }
    return _spatial_staging_root(root) / "tex" / suffixes[detail_id]


def _shader_recipe_path(root: Path, material_id: str) -> Path:
    """Map one stable material ID to a short contained ShaderRecipe path."""

    suffixes = {
        "mat.metal.trim.filigree_body": "mtfb",
        "mat.grip.leather": "gl",
        "mat.crystal.emission": "ce",
        "mat.crystal.translucent.facet_crown": "ctfc",
    }
    return _spatial_staging_root(root) / "sh" / suffixes[material_id] / "recipe.json"


def _copy_exact(source: Path, destination: Path, expected_sha256: str) -> None:
    """Copy one immutable file once and verify its exact digest after publication."""

    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    if os.path.exists(native_io_path(destination)):
        if not os.path.isfile(native_io_path(destination)):
            raise ValueError(f"recovery destination is not a regular file: {destination}")
        if sha256_file(destination) != expected_sha256:
            raise FileExistsError(f"recovery copy differs: {destination}")
        return
    shutil.copy2(native_io_path(source), native_io_path(destination))
    if sha256_file(destination) != expected_sha256:
        raise RuntimeError(f"recovery copy hash changed: {destination}")


def _prepare_controller_mirror(
    *,
    root: Path,
    request_path: Path,
    request: ControllerExecutionRequest,
) -> tuple[Path, Path]:
    """Mirror exact controller inputs into a symlink-free, job-contained execution root."""

    mirror_root = _spatial_staging_root(root) / "cx"
    mirror_request_path = mirror_root / request_path.relative_to(root)
    for artifact in request.provenance:
        _copy_exact(root / artifact.path, mirror_root / artifact.path, artifact.sha256)
    _copy_exact(request_path, mirror_request_path, sha256_file(request_path))
    return mirror_root, mirror_request_path


def _publish_controller_mirror(
    *,
    root: Path,
    mirror_root: Path,
    mirror_execution_root: Path,
    result: ControllerResult,
) -> None:
    """Publish byte-identical ControllerExecutor lifecycle evidence from the isolated mirror."""

    for source in deterministic_directory_files(mirror_execution_root):
        _copy_exact(source, root / source.relative_to(mirror_root), sha256_file(source))
    for output in result.outputs:
        source = mirror_root / output.path
        _copy_exact(source, root / output.path, output.sha256)


def _author_texture_assets(
    *,
    root: Path,
    uv_fingerprints: dict[str, str],
    imagegen_source: Path,
    imagegen_semantic_review: Path,
) -> tuple[dict[str, TextureManifest], list[AQV2Artifact], list[AQV2Artifact]]:
    """Author four bounded manifests without invoking ImageGen or authoritative data maps."""

    manifests: dict[str, TextureManifest] = {}
    manifest_artifacts: list[AQV2Artifact] = []
    channel_artifacts: list[AQV2Artifact] = []
    for detail_id, contract in _DETAIL_CONTRACTS.items():
        output_dir = _texture_asset_path(root, detail_id)
        material_id = str(contract["material_id"])
        parent_id = str(contract["parent_object_id"])
        channels = cast(list[str], contract["channels"])
        resolution = cast(tuple[int, int], contract["resolution"])
        binding = SurfaceDetailBinding(
            detail_id=detail_id,
            parent_object_id=parent_id,
            material_id=material_id,
            uv_layout_sha256=uv_fingerprints[parent_id],
            placement=SurfaceDetailPlacement(
                mode="uv_rect",
                uv_rect=(0.0, 0.0, 1.0, 1.0),
            ),
            channels=cast(Any, channels),
            strength=float(contract["strength"]),
            wrap="clip",
        )
        shader_recipe_path = _shader_recipe_path(root, material_id).relative_to(root).as_posix()
        manifest_path = output_dir / "spatial_texture_manifest.json"
        if manifest_path.is_file():
            manifest = TextureManifest.model_validate_json(manifest_path.read_bytes())
            expected_manifest_fields = {
                "material_id": material_id,
                "uv_set": "UVMap",
                "resolution": resolution,
                "surface_detail_ids": [detail_id],
                "surface_detail_bindings": [binding],
                "shader_recipe": shader_recipe_path,
            }
            observed_manifest_fields = {
                "material_id": manifest.material_id,
                "uv_set": manifest.uv_set,
                "resolution": manifest.resolution,
                "surface_detail_ids": manifest.surface_detail_ids,
                "surface_detail_bindings": manifest.surface_detail_bindings,
                "shader_recipe": manifest.shader_recipe,
            }
            if observed_manifest_fields != expected_manifest_fields:
                raise FileExistsError(f"existing spatial manifest differs: {detail_id}")
            for channel, expected_sha256 in manifest.provenance.generated_sha256.items():
                descriptor = manifest.channels[channel]
                if descriptor.path is None:
                    raise ValueError(
                        f"generated spatial channel lacks a path: {detail_id}/{channel}"
                    )
                if sha256_file(manifest_path.parent / descriptor.path) != expected_sha256:
                    raise ValueError(f"existing spatial channel is stale: {detail_id}/{channel}")
        elif detail_id == "detail.crystal.internal_emission":
            os.makedirs(native_io_path(output_dir), exist_ok=True)
            emission_path = output_dir / "emission.png"
            _copy_exact(imagegen_source, emission_path, _EXPECTED_REFERENCE_IMAGEGEN_SHA256)
            manifest = TextureManifest(
                material_id=material_id,
                uv_set="UVMap",
                intended_scale_m=0.76,
                resolution=resolution,
                source_type="image",
                channels={
                    "emission": TextureChannel(
                        source="image",
                        path="emission.png",
                        color_space="sRGB",
                    )
                },
                surface_detail_ids=[detail_id],
                surface_detail_bindings=[binding],
                shader_recipe=shader_recipe_path,
                provenance=TextureProvenance(
                    provider="codex_builtin_imagegen_immutable_reuse",
                    provider_version="current-task-evidence",
                    model="codex_builtin_imagegen",
                    prompt="Reused exact bounded crystal emission candidate; no new invocation.",
                    source_hashes=[
                        sha256_file(imagegen_source),
                        sha256_file(imagegen_semantic_review),
                    ],
                    generated_sha256={"emission": sha256_file(emission_path)},
                    license="Immutable current-task ImageGen evidence; project use only.",
                ),
                node_graph_summary=(
                    "UVMap identity mapping with clip sampling; emission is the only "
                    "ImageGen-driven channel."
                ),
                color_space_rules={
                    "emission": "sRGB",
                    "data_channels": "No ImageGen-authored data channels are present.",
                },
                generation_notes=(
                    "Byte-identical copy of the approved normalized candidate; no stretch, "
                    "crop, pad, resample, or new ImageGen call."
                ),
            )
            _write_model(manifest_path, manifest)
        else:
            result = generate_procedural_pbr(
                root.name,
                material_id,
                preset=str(contract["preset"]),
                channels=channels,
                resolution=resolution,
                seed=_seed_for_detail(detail_id),
                intended_scale_m={
                    "detail.filigree.body": 1.05,
                    "detail.filigree.grip": 0.49,
                    "detail.crystal.facet_lines": 0.84,
                }[detail_id],
                prompt=(
                    f"Deterministic bounded {detail_id} controller-authored completion; "
                    "no external provider."
                ),
                uv_set="UVMap",
                surface_detail_ids=(detail_id,),
                surface_detail_bindings=(binding,),
                detail_pattern=str(contract["pattern"]),
                output_dir=output_dir,
                overwrite=False,
            )
            provider_manifest_path = output_dir / "provider_texture_manifest.json"
            _copy_exact(
                result.manifest_path,
                provider_manifest_path,
                sha256_file(result.manifest_path),
            )
            hybrid_channels = dict(result.manifest.channels)
            hybrid_channels["metallic"] = TextureChannel(source="procedural")
            manifest = result.manifest.model_copy(
                update={
                    "source_type": "hybrid",
                    "channels": hybrid_channels,
                    "shader_recipe": shader_recipe_path,
                    "procedural": {
                        **result.manifest.procedural,
                        "neutral_procedural_channel": "metallic",
                        "neutral_procedural_value_source": "ShaderRecipe base surface",
                    },
                    "generation_notes": (
                        f"{result.manifest.generation_notes} The hybrid companion retains "
                        "a neutral procedural metallic channel; every localized planned "
                        "channel remains image-backed."
                    ),
                }
            )
            manifest = TextureManifest.model_validate(manifest.model_dump(mode="json"))
            _write_model(manifest_path, manifest)
        manifests[material_id] = manifest
        manifest_artifacts.append(
            _artifact(
                root,
                manifest_path,
                artifact_id=f"spatial-manifest-{detail_id.replace('.', '-')}",
                kind="surface_detail_texture_manifest",
            )
        )
        for channel, descriptor in sorted(manifest.channels.items()):
            if descriptor.path is None:
                continue
            channel_path = manifest_path.parent / descriptor.path
            channel_artifacts.append(
                _artifact(
                    root,
                    channel_path,
                    artifact_id=(f"spatial-texture-{detail_id.replace('.', '-')}-{channel}"),
                    kind="surface_detail_texture_channel",
                )
            )
    return manifests, manifest_artifacts, channel_artifacts


def _author_shader_recipes(
    *,
    root: Path,
    baseline: MaterialPlan,
    manifests: dict[str, TextureManifest],
) -> tuple[dict[str, ShaderRecipe], list[AQV2Artifact]]:
    """Clone approved shader families into four localized UVMap recipe companions."""

    baseline_by_id = {item.material_id: item for item in baseline.materials}
    recipes: dict[str, ShaderRecipe] = {}
    artifacts: list[AQV2Artifact] = []
    for detail_id, contract in _DETAIL_CONTRACTS.items():
        material_id = str(contract["material_id"])
        source_id = str(contract["source_material_id"])
        source_item = baseline_by_id[source_id]
        if source_item.shader_recipe is None:
            raise ValueError(f"baseline material lacks a ShaderRecipe: {source_id}")
        source_recipe = load_shader_recipe(root / source_item.shader_recipe)
        manifest_path = (
            (_texture_asset_path(root, detail_id) / "spatial_texture_manifest.json")
            .relative_to(root)
            .as_posix()
        )
        recipe = source_recipe.model_copy(
            update={
                "material_id": material_id,
                "mapping": source_recipe.mapping.model_copy(
                    update={"mode": "uv", "uv_set": "UVMap"}
                ),
                "texture_manifest": manifest_path,
                "bake_required": True,
                "assumptions": [
                    *source_recipe.assumptions,
                    f"Localized spatial-v1 binding for {detail_id}.",
                    "UVMap identity placement is non-repeating and requires geometry review.",
                    "No authoritative normal, roughness, metallic, height, displacement, "
                    "AO, or tangent channel was taken from ImageGen.",
                ],
            }
        )
        recipe = ShaderRecipe.model_validate(recipe.model_dump(mode="json"))
        recipe_path = _shader_recipe_path(root, material_id)
        _write_model(recipe_path, recipe)
        recipes[material_id] = recipe
        artifacts.append(
            _artifact(
                root,
                recipe_path,
                artifact_id=f"spatial-recipe-{material_id}",
                kind="surface_detail_shader_recipe",
            )
        )
        manifest = manifests[material_id]
        if manifest.shader_recipe != recipe_path.relative_to(root).as_posix():
            raise ValueError(f"manifest and ShaderRecipe disagree: {material_id}")
    return recipes, artifacts


def _material_candidate(
    *,
    root: Path,
    baseline: MaterialPlan,
) -> MaterialPlan:
    """Create exact material coverage while preserving every existing stable ID."""

    baseline_by_id = {item.material_id: item for item in baseline.materials}
    detailed_ids = {
        str(contract["material_id"]): detail_id for detail_id, contract in _DETAIL_CONTRACTS.items()
    }
    materials: list[MaterialPlanItem] = []
    for item in baseline.materials:
        detail_id = detailed_ids.get(item.material_id)
        if detail_id is None:
            materials.append(item)
            continue
        contract = _DETAIL_CONTRACTS[detail_id]
        manifest_path = (
            (_texture_asset_path(root, detail_id) / "spatial_texture_manifest.json")
            .relative_to(root)
            .as_posix()
        )
        recipe_path = _shader_recipe_path(root, item.material_id).relative_to(root).as_posix()
        materials.append(
            item.model_copy(
                update={
                    "texture_strategy": contract["texture_strategy"],
                    "mapping": item.mapping.model_copy(update={"mode": "uv", "uv_set": "UVMap"}),
                    "texture_manifest": manifest_path,
                    "shader_recipe": recipe_path,
                    "notes": [
                        *item.notes,
                        f"Exact spatial-v1 coverage for {detail_id}.",
                    ],
                }
            )
        )
    for material_id, source_id, detail_id, label in (
        (
            "mat.metal.trim.filigree_body",
            "mat.metal.trim",
            "detail.filigree.body",
            "Localized bright metal body filigree",
        ),
        (
            "mat.crystal.translucent.facet_crown",
            "mat.crystal.translucent",
            "detail.crystal.facet_lines",
            "Localized translucent crown facet lines",
        ),
    ):
        source = baseline_by_id[source_id]
        manifest_path = (
            (_texture_asset_path(root, detail_id) / "spatial_texture_manifest.json")
            .relative_to(root)
            .as_posix()
        )
        recipe_path = _shader_recipe_path(root, material_id).relative_to(root).as_posix()
        materials.append(
            source.model_copy(
                update={
                    "material_id": material_id,
                    "label": label,
                    "texture_strategy": "hybrid",
                    "mapping": source.mapping.model_copy(update={"mode": "uv", "uv_set": "UVMap"}),
                    "texture_manifest": manifest_path,
                    "shader_recipe": recipe_path,
                    "notes": [
                        *source.notes,
                        f"Additive localized identity for {detail_id} only.",
                    ],
                }
            )
        )
    candidate = MaterialPlan(
        job_id=baseline.job_id,
        scene_spec_path="analysis/scene_spec.json",
        stage="authored",
        surface_detail_binding_policy="spatial_v1",
        materials=materials,
        global_notes=[
            *baseline.global_notes,
            "Two additive material IDs isolate bounded detail pixels from shared materials.",
            "Geometry topology and semantic IDs remain outside this material candidate.",
            "Human review has not been performed.",
        ],
    )
    return MaterialPlan.model_validate(candidate.model_dump(mode="json"))


def _material_graph_candidate(
    *,
    root: Path,
    recovery_root: Path,
    workflow_id: str,
    dispatch_id: str,
    candidate_scene_artifact: AQV2Artifact,
    candidate_plan_path: str,
    candidate_plan_sha256: str,
    manifest_artifacts: list[AQV2Artifact],
    recipe_artifacts: list[AQV2Artifact],
    channel_artifacts: list[AQV2Artifact],
) -> MaterialGraphSpec:
    """Author one whitelist-only emission graph while binding all spatial dependencies."""

    emission_manifest = next(
        item for item in manifest_artifacts if "crystal-internal_emission" in item.artifact_id
    )
    emission_channel = next(
        item
        for item in channel_artifacts
        if item.artifact_id.endswith("crystal-internal_emission-emission")
    )
    reference_path = root / "input" / "reference.png"
    reference = MaterialGraphArtifact(
        role="reference",
        path=reference_path.relative_to(root).as_posix(),
        sha256=sha256_file(reference_path),
    )
    graph_inputs = [
        MaterialGraphArtifact(
            role="scene_spec",
            path=candidate_scene_artifact.path,
            sha256=candidate_scene_artifact.sha256,
        ),
        MaterialGraphArtifact(
            role="material_plan",
            path=candidate_plan_path,
            sha256=candidate_plan_sha256,
        ),
        *[
            MaterialGraphArtifact(
                role="shader_recipe",
                path=item.path,
                sha256=item.sha256,
            )
            for item in recipe_artifacts
        ],
        *[
            MaterialGraphArtifact(
                role="other",
                path=item.path,
                sha256=item.sha256,
            )
            for item in manifest_artifacts
        ],
        *[
            MaterialGraphArtifact(
                role="texture",
                path=item.path,
                sha256=item.sha256,
            )
            for item in channel_artifacts
        ],
        reference,
    ]
    graph = MaterialGraphSpec(
        graph_id="crystalgun-spatial-recovery-emission-01",
        provenance=MaterialGraphProvenance(
            job_id=root.name,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            project_version="0.9.0",
            inputs=graph_inputs,
        ),
        material_id="mat.crystal.emission",
        base_channels=[
            ChannelBinding(
                channel="emission",
                source_kind="image",
                color_space="sRGB",
                image=MaterialGraphArtifact(
                    role="texture",
                    path=emission_channel.path,
                    sha256=emission_channel.sha256,
                ),
                physical_scale=TextureScale(
                    width_m=0.76,
                    height_m=0.76,
                    uv_set="UVMap",
                ),
                sampling="clip",
                localized_detail=True,
            )
        ],
        normal_displacement=NormalDisplacementPolicy(
            normal_mode="disabled",
            displacement_mode="disabled",
            maximum_displacement_m=0.0,
            require_subdivision=False,
        ),
        bake=BakePolicy(required=False, channels=[]),
        preview_lighting=PreviewLightingPolicy(
            neutral_profile="neutral_studio",
            neutral_exposure=0.0,
            reference_profile="reference_matched",
            reference_source=reference,
            reference_confidence=0.5,
        ),
        assumptions=[
            f"Emission manifest is {emission_manifest.path}.",
            "Only bounded emission uses immutable Codex ImageGen pixels.",
            "All other localized channels are deterministic local derivatives.",
            "Geometry review is required before canonical material promotion.",
            "Human review has not been performed.",
        ],
    )
    return graph


def _usage_after_controller(
    usage: BudgetUsageV2,
    budget: AutonomyBudgetV2,
    *,
    controller_increment: int = 1,
    blender_build_increment: int = 1,
    action_increment: int = 2,
) -> BudgetUsageV2:
    """Consume exact controller, Blender-build, and bounded-action increments."""

    next_usage = usage.model_copy(
        update={
            "controller_invocations": usage.controller_invocations + controller_increment,
            "total_blender_builds": usage.total_blender_builds + blender_build_increment,
            "total_actions": usage.total_actions + action_increment,
        }
    )
    if next_usage.controller_invocations > budget.controller_invocations:
        raise PermissionError("AQ controller invocation budget is exhausted")
    if next_usage.total_blender_builds > budget.total_blender_builds:
        raise PermissionError("AQ Blender build budget is exhausted")
    if next_usage.total_actions > budget.global_action_limit:
        raise PermissionError("AQ global action budget is exhausted")
    return next_usage


def _validate_profile_opt_in(
    root: Path,
    session_root: Path,
    *,
    allow_disabled_experimental: bool,
    state_sequence: int = 7,
) -> tuple[AutonomyProfileV2, AutonomyBudgetV2, AutonomyStateV2, AQV2Artifact]:
    """Reload current AQ profile, budget, and exact approved source state."""

    profile_path = session_root / "profile.json"
    budget_path = session_root / "budget.json"
    state_path = session_root / "states" / f"{state_sequence:04d}.json"
    profile = AutonomyProfileV2.model_validate_json(profile_path.read_bytes())
    budget = AutonomyBudgetV2.model_validate_json(budget_path.read_bytes())
    state = AutonomyStateV2.model_validate_json(state_path.read_bytes())
    state_artifact = _artifact(
        root,
        state_path,
        artifact_id=state.contract_id,
        kind="state",
    )
    if profile.profile_id != _EXPECTED_BASE_PROFILE:
        raise ValueError("surface-detail recovery base profile identity changed")
    if profile.status != "verified_active" and not allow_disabled_experimental:
        raise PermissionError("autonomous_static_prop_v2 is disabled_experimental")
    provider_profile_path = session_root / "codex_imagegen" / "provider-profile.json"
    provider_profile = json.loads(provider_profile_path.read_text(encoding="utf-8"))
    expected_provider_fields = {
        "job_id": state.job_id,
        "session_id": state.session_id,
        "profile_id": _EXPECTED_PROFILE,
        "base_profile": _EXPECTED_BASE_PROFILE,
        "provider_id": "codex_builtin_gpt_image_v1",
        "status": "disabled_experimental",
        "network_required": False,
        "api_key_required": False,
        "controller_required": True,
        "canonical_material_write": False,
        "destination_project_write": False,
    }
    if any(provider_profile.get(key) != value for key, value in expected_provider_fields.items()):
        raise ValueError("surface-detail recovery Codex ImageGen overlay identity changed")
    if (state.phase, state.status, state.next_action) != (
        "authoring",
        "running",
        "validate_candidate",
    ):
        raise PermissionError("surface-detail recovery AQ state is not reviewable")
    return profile, budget, state, state_artifact


def _copy_shadow_material_dependencies(
    *,
    root: Path,
    shadow_root: Path,
    material_plan: MaterialPlan,
) -> None:
    """Copy every recipe, manifest, and image channel into the isolated shadow job."""

    copied_manifests: set[str] = set()
    for item in material_plan.materials:
        if item.shader_recipe is not None:
            source_recipe = root / item.shader_recipe
            _copy_exact(
                source_recipe,
                shadow_root / item.shader_recipe,
                sha256_file(source_recipe),
            )
            recipe = load_shader_recipe(source_recipe)
            manifest_values = [item.texture_manifest, recipe.texture_manifest]
        else:
            manifest_values = [item.texture_manifest]
        for manifest_value in manifest_values:
            if not manifest_value or manifest_value in copied_manifests:
                continue
            copied_manifests.add(manifest_value)
            source_manifest = root / manifest_value
            manifest = TextureManifest.model_validate_json(source_manifest.read_bytes())
            _copy_exact(
                source_manifest,
                shadow_root / manifest_value,
                sha256_file(source_manifest),
            )
            for descriptor in manifest.channels.values():
                if descriptor.path is None:
                    continue
                channel_source = source_manifest.parent / descriptor.path
                channel_relative = (
                    PurePosixPath(manifest_value).parent / descriptor.path
                ).as_posix()
                _copy_exact(
                    channel_source,
                    shadow_root / channel_relative,
                    sha256_file(channel_source),
                )


def _prepare_shadow_job(
    *,
    root: Path,
    shadow_root: Path,
    candidate_scene_path: Path,
    candidate_modeling_path: Path,
    candidate_material_plan_path: Path,
) -> tuple[SceneSpec, ModelingPlan, MaterialPlan]:
    """Create one candidate-owned job root with every exact build dependency."""

    if shadow_root.exists() and not shadow_root.is_dir():
        raise FileExistsError(f"spatial recovery shadow job is not a directory: {shadow_root}")
    (shadow_root / "analysis").mkdir(parents=True, exist_ok=True)
    source_scene = SceneSpec.model_validate_json(candidate_scene_path.read_bytes())
    source_modeling = ModelingPlan.model_validate_json(candidate_modeling_path.read_bytes())
    source_material = MaterialPlan.model_validate_json(candidate_material_plan_path.read_bytes())
    _copy_exact(root / "job.json", shadow_root / "job.json", sha256_file(root / "job.json"))
    for relative in (
        "analysis/reference_analysis.json",
        "analysis/camera_solution.json",
        "input/reference.png",
    ):
        source = root / relative
        _copy_exact(source, shadow_root / relative, sha256_file(source))
    _copy_exact(
        candidate_scene_path,
        shadow_root / "analysis/scene_spec.json",
        sha256_file(candidate_scene_path),
    )
    _copy_exact(
        candidate_modeling_path,
        shadow_root / "analysis/modeling_plan.json",
        sha256_file(candidate_modeling_path),
    )
    _copy_exact(
        candidate_material_plan_path,
        shadow_root / "analysis/material_plan.json",
        sha256_file(candidate_material_plan_path),
    )
    for scene_source in source_scene.sources:
        source = root / scene_source.path
        _copy_exact(source, shadow_root / scene_source.path, sha256_file(source))
    for item in source_scene.objects:
        geometry_path = getattr(item.geometry, "path", None)
        if not geometry_path:
            continue
        source = root / geometry_path
        _copy_exact(source, shadow_root / geometry_path, sha256_file(source))
    _copy_shadow_material_dependencies(
        root=root,
        shadow_root=shadow_root,
        material_plan=source_material,
    )
    return source_scene, source_modeling, source_material


def _topology_comparison(
    *,
    source_scene: SceneSpec,
    candidate_scene: SceneSpec,
    source_inventory_path: Path,
    candidate_inventory_path: Path,
) -> dict[str, Any]:
    """Compare geometry recipes and Blender mesh counts while allowing material-only deltas."""

    source_inventory = json.loads(source_inventory_path.read_text(encoding="utf-8"))
    candidate_inventory = json.loads(candidate_inventory_path.read_text(encoding="utf-8"))
    source_records = {
        str(item["cbm_id"]): item
        for item in source_inventory.get("objects", [])
        if isinstance(item, dict) and item.get("cbm_id")
    }
    candidate_records = {
        str(item["cbm_id"]): item
        for item in candidate_inventory.get("objects", [])
        if isinstance(item, dict) and item.get("cbm_id")
    }
    source_objects = {item.id: item for item in source_scene.objects}
    candidate_objects = {item.id: item for item in candidate_scene.objects}
    semantic_ids_unchanged = set(source_objects) == set(candidate_objects)
    geometry_recipe_checks: list[dict[str, object]] = []
    blender_topology_checks: list[dict[str, object]] = []
    for object_id in sorted(set(source_objects) | set(candidate_objects)):
        source_object = source_objects.get(object_id)
        candidate_object = candidate_objects.get(object_id)
        recipe_equal = bool(
            source_object is not None
            and candidate_object is not None
            and source_object.geometry.model_dump(mode="json")
            == candidate_object.geometry.model_dump(mode="json")
            and source_object.transform == candidate_object.transform
            and source_object.modifiers == candidate_object.modifiers
            and source_object.parent_id == candidate_object.parent_id
        )
        geometry_recipe_checks.append(
            {
                "object_id": object_id,
                "status": "passed" if recipe_equal else "failed",
                "geometry_recipe_unchanged": recipe_equal,
            }
        )
        source_record = source_records.get(object_id, {})
        candidate_record = candidate_records.get(object_id, {})
        compared = {
            key: (source_record.get(key), candidate_record.get(key))
            for key in ("geometry_kind", "vertices", "polygons", "dimensions")
        }
        counts_equal = bool(
            source_record
            and candidate_record
            and all(before == after for before, after in compared.values())
        )
        blender_topology_checks.append(
            {
                "object_id": object_id,
                "status": "passed" if counts_equal else "failed",
                "compared": compared,
            }
        )
    expected_material_changes = {
        object_id: {
            "before": source_objects[object_id].material_id,
            "after": candidate_objects[object_id].material_id,
        }
        for object_id in sorted(_ASSIGNMENT_SPECIALIZATIONS)
    }
    observed_material_changes = {
        object_id: {
            "before": source_objects[object_id].material_id,
            "after": candidate_objects[object_id].material_id,
        }
        for object_id in sorted(source_objects)
        if source_objects[object_id].material_id != candidate_objects[object_id].material_id
    }
    topology_unchanged = bool(
        semantic_ids_unchanged
        and all(item["status"] == "passed" for item in geometry_recipe_checks)
        and all(item["status"] == "passed" for item in blender_topology_checks)
        and observed_material_changes == expected_material_changes
    )
    return {
        "schema_version": "0.1.0",
        "status": "passed" if topology_unchanged else "failed",
        "topology_unchanged": topology_unchanged,
        "semantic_ids_unchanged": semantic_ids_unchanged,
        "source_scene_spec_sha256": stable_json_digest(source_scene.model_dump(mode="json")),
        "candidate_scene_spec_sha256": stable_json_digest(candidate_scene.model_dump(mode="json")),
        "source_inventory_sha256": sha256_file(source_inventory_path),
        "candidate_inventory_sha256": sha256_file(candidate_inventory_path),
        "geometry_recipe_checks": geometry_recipe_checks,
        "blender_topology_checks": blender_topology_checks,
        "expected_material_assignment_changes": expected_material_changes,
        "observed_material_assignment_changes": observed_material_changes,
        "limitations": [
            "This proves unchanged SceneSpec geometry recipes and matching Blender mesh counts; "
            "it does not prove hidden real-product construction.",
            "A single concept reference does not establish exact dimensions or "
            "opposite-side truth.",
        ],
    }


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    """Write one deterministic JSON object without changing an existing differing record."""

    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _write_exact_bytes(path, encoded)


def _validate_exact_hash(path: Path, expected_sha256: str, label: str) -> Path:
    """Rehash one exact source artifact before any authorized recovery side effect."""

    if not os.path.isfile(native_io_path(path)) or sha256_file(path) != expected_sha256:
        raise ValueError(f"{label} is missing or stale")
    return path


def _execute_controller(
    *,
    root: Path,
    session_root: Path,
    recovery_id: str,
    preparation_artifact: AQV2Artifact,
    state: AutonomyStateV2,
    state_artifact: AQV2Artifact,
    budget: AutonomyBudgetV2,
    candidate_scene_artifact: AQV2Artifact,
    candidate_modeling_artifact: AQV2Artifact,
    candidate_material_artifact: AQV2Artifact,
    candidate_graph_artifact: AQV2Artifact,
    dependency_artifacts: list[AQV2Artifact],
    plan_artifact: AQV2Artifact,
    execution_id: str = "exec-0008-material-surface-detail-spatial-recovery",
    output_leaf: str = "material_surface_detail_spatial_recovery_01",
    controller_increment: int = 1,
    blender_build_increment: int = 1,
    action_increment: int = 2,
    controller_staging_root: Path | None = None,
    completion_input_binding: Literal[
        "logical_assignment_map", "full_request_input_map"
    ] = "logical_assignment_map",
) -> tuple[
    ControllerResult,
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    AQV2Artifact,
    BudgetUsageV2,
]:
    """Execute exactly one material controller and return its strict output boundary."""

    output_root = f"production/autonomy_v2/{state.session_id}/controller_outputs/{output_leaf}"
    output_paths = [
        f"{output_root}/material_plan.json",
        f"{output_root}/material_graph.json",
        f"{output_root}/completion.json",
    ]
    staging_root = controller_staging_root or _spatial_staging_root(root)
    profile_path = staging_root / "controller_profile.json"
    profile_provenance = [
        _controller_artifact(
            root,
            root / plan_artifact.path,
            artifact_id=plan_artifact.artifact_id,
            role="material-baseline",
        ),
        _controller_artifact(
            root,
            root / preparation_artifact.path,
            artifact_id=preparation_artifact.artifact_id,
            role="material-baseline",
        ),
    ]
    profile = PhaseToolProfile(
        contract_id=f"tool-profile-material-spatial-{recovery_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
        input_sha256=stable_json_digest({item.path: item.sha256 for item in profile_provenance}),
        source_fingerprint=plan_artifact.sha256,
        producer="codex_blender_modeler.production.controller_executor.profiles",
        provenance=profile_provenance,
        created_at=datetime.now(UTC),
        profile_id="material_authoring",
        allowed_tools=["get_workflow_state", "record_delegated_production_step"],
        forbidden_tools=[
            "approve_workflow_checkpoint",
            "approve_visual_revision",
            "approve_optimization_plan",
            "approve_destination_handoff",
            "resume_short_workflow_retry_failed",
            "run_arbitrary_blender_python",
            "run_shell_command",
            "write_destination_project",
        ],
        allowed_input_roles=["assignment", "scene", "material-baseline"],
        allowed_output_paths=output_paths,
        canonical_write_authority="supervisor_only",
        network_access="denied",
        destination_project_write=False,
        sandbox_attestation="repository_path_validation_only",
    )
    if profile_path.exists():
        stored_profile = PhaseToolProfile.model_validate_json(profile_path.read_bytes())
        if stored_profile.model_dump(mode="json", exclude={"created_at"}) != profile.model_dump(
            mode="json", exclude={"created_at"}
        ):
            raise FileExistsError("spatial recovery controller profile differs")
        profile = stored_profile
    else:
        write_controller_contract(profile_path, profile)
    profile_artifact = _artifact(
        root,
        profile_path,
        artifact_id=profile.contract_id,
        kind="controller_phase_tool_profile",
    )
    immutable_by_path: dict[str, ControllerArtifact] = {}
    for item in [
        candidate_scene_artifact,
        candidate_modeling_artifact,
        candidate_material_artifact,
        candidate_graph_artifact,
        preparation_artifact,
        plan_artifact,
        *dependency_artifacts,
    ]:
        immutable_by_path[item.path] = _controller_artifact(
            root,
            root / item.path,
            artifact_id=item.artifact_id,
            role="scene" if item.path == candidate_scene_artifact.path else "material-baseline",
        )
    immutable_inputs = [immutable_by_path[path] for path in sorted(immutable_by_path)]
    logical_inputs = (
        {item.path: item.sha256 for item in immutable_inputs}
        if completion_input_binding == "full_request_input_map"
        else {
            "analysis/scene_spec.json": candidate_scene_artifact.sha256,
            candidate_modeling_artifact.path: candidate_modeling_artifact.sha256,
            candidate_material_artifact.path: candidate_material_artifact.sha256,
            candidate_graph_artifact.path: candidate_graph_artifact.sha256,
            preparation_artifact.path: preparation_artifact.sha256,
        }
    )
    assignment = SurfaceDetailSpatialControllerInput(
        assignment_id=f"assignment-{recovery_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
        recovery_id=recovery_id,
        recovery_plan_sha256=plan_artifact.sha256,
        source_aq_state_sha256=state_artifact.sha256,
        candidate_scene_spec=candidate_scene_artifact,
        candidate_modeling_plan=candidate_modeling_artifact,
        candidate_material_plan=candidate_material_artifact,
        candidate_material_graph=candidate_graph_artifact,
        source_material_plan_sha256=candidate_material_artifact.sha256,
        phase_tool_profile_sha256=profile_artifact.sha256,
        immutable_input_sha256=logical_inputs,
        allowed_output_paths=output_paths,
        expected_output_sha256={
            output_paths[0]: candidate_material_artifact.sha256,
            output_paths[1]: candidate_graph_artifact.sha256,
        },
    )
    assignment_path = staging_root / "controller_assignment.json"
    _write_model(assignment_path, assignment)
    assignment_artifact = _artifact(
        root,
        assignment_path,
        artifact_id=assignment.assignment_id,
        kind="controller_assignment",
    )
    controller_assignment = _controller_artifact(
        root,
        assignment_path,
        artifact_id=assignment.assignment_id,
        role="assignment",
    )
    controller_profile = _controller_artifact(
        root,
        profile_path,
        artifact_id=profile.contract_id,
        role="tool_profile",
    )
    request_provenance = [controller_assignment, *immutable_inputs, controller_profile]
    request = ControllerExecutionRequest(
        contract_id=f"request-{execution_id}",
        job_id=state.job_id,
        workflow_id=state.workflow_id,
        dispatch_id=state.dispatch_id,
        session_id=state.session_id,
        input_sha256=stable_json_digest({item.path: item.sha256 for item in request_provenance}),
        source_fingerprint=stable_json_digest(
            {
                "recovery_plan": plan_artifact.sha256,
                "preparation": preparation_artifact.sha256,
                "controller_kind": ExactSurfaceDetailSpatialMaterialController.controller_kind,
            }
        ),
        producer="codex_blender_modeler.autonomy_v2.controller_bridge",
        provenance=request_provenance,
        created_at=datetime.now(UTC),
        execution_id=execution_id,
        controller_kind="desktop_in_session",
        assignment=controller_assignment,
        immutable_inputs=immutable_inputs,
        tool_profile=controller_profile,
        output_root=output_root,
        allowed_output_paths=output_paths,
        expected_output_sha256=assignment.expected_output_sha256,
        timeout_seconds=900,
    )
    execution_root = session_root / "controller_executions" / execution_id
    request_path = execution_root / "request.json"
    result_path = execution_root / "result.json"
    controller = ExactSurfaceDetailSpatialMaterialController()
    if request_path.exists():
        stored = ControllerExecutionRequest.model_validate_json(request_path.read_bytes())
        if stored.model_dump(mode="json", exclude={"created_at"}) != request.model_dump(
            mode="json", exclude={"created_at"}
        ):
            raise FileExistsError("spatial recovery controller request differs")
        request = stored
    else:
        write_controller_contract(request_path, request)
    request_artifact = _artifact(
        root,
        request_path,
        artifact_id=request.contract_id,
        kind="controller_request",
    )
    mirror_root, mirror_request_path = _prepare_controller_mirror(
        root=root,
        request_path=request_path,
        request=request,
    )
    mirror_result_path = mirror_request_path.parent / "result.json"
    if mirror_result_path.exists():
        result = validate_controller_execution_result(
            job_root=mirror_root,
            request_path=mirror_request_path,
            result_path=mirror_result_path,
            controller=controller,
        )
    else:
        result = execute_controller_request(
            job_root=mirror_root,
            request_path=mirror_request_path,
            controller=controller,
        )
        write_immutable_v2_model(mirror_root, mirror_result_path, result)
        result = validate_controller_execution_result(
            job_root=mirror_root,
            request_path=mirror_request_path,
            result_path=mirror_result_path,
            controller=controller,
        )
    _publish_controller_mirror(
        root=root,
        mirror_root=mirror_root,
        mirror_execution_root=mirror_request_path.parent,
        result=result,
    )
    if result.status != "completed" or len(result.outputs) != 3:
        raise RuntimeError(f"spatial recovery controller did not complete: {result.status}")
    result_artifact = _artifact(
        root,
        result_path,
        artifact_id=result.contract_id,
        kind="controller_result",
    )
    output_by_name = {PurePosixPath(item.path).name: item for item in result.outputs}
    plan_output = output_by_name["material_plan.json"]
    graph_output = output_by_name["material_graph.json"]
    completion_output = output_by_name["completion.json"]
    if (
        plan_output.sha256 != candidate_material_artifact.sha256
        or graph_output.sha256 != candidate_graph_artifact.sha256
    ):
        raise ValueError("spatial recovery controller outputs differ from blueprints")
    plan_output_artifact = _artifact(
        root,
        root / plan_output.path,
        artifact_id=f"{recovery_id}-material-plan-output",
        kind="material_plan_candidate",
    )
    graph_output_artifact = _artifact(
        root,
        root / graph_output.path,
        artifact_id=f"{recovery_id}-material-graph-output",
        kind="material_graph_candidate",
    )
    completion_artifact = _artifact(
        root,
        root / completion_output.path,
        artifact_id=f"{recovery_id}-controller-completion",
        kind="material_controller_completion",
    )
    completion = MaterialControllerCompletionV2.model_validate_json(
        (root / completion_output.path).read_bytes()
    )
    if (
        completion.assignment_sha256 != assignment_artifact.sha256
        or completion.tool_profile_sha256 != profile_artifact.sha256
        or completion.material_plan_sha256 != plan_output_artifact.sha256
        or completion.material_graph_sha256 != graph_output_artifact.sha256
    ):
        raise ValueError("spatial recovery controller completion binding changed")
    usage = _usage_after_controller(
        state.budget_usage,
        budget,
        controller_increment=controller_increment,
        blender_build_increment=blender_build_increment,
        action_increment=action_increment,
    )
    return (
        result,
        request_artifact,
        result_artifact,
        profile_artifact,
        assignment_artifact,
        completion_artifact,
        plan_output_artifact,
        graph_output_artifact,
        usage,
    )


def execute_surface_detail_spatial_recovery(
    job_id: str,
    session_id: str,
    *,
    recovery_plan_path: Path,
    recovery_plan_sha256: str,
    exact_approval: str,
    allow_disabled_experimental: bool = False,
) -> dict[str, Any]:
    """Prepare, execute, Blender-validate, and stop at exact geometry review approval."""

    root = ensure_contained_production_path(job_dir(job_id), job_dir(job_id), must_exist=True)
    session_root = ensure_contained_production_path(
        root,
        root / "production" / "autonomy_v2" / session_id,
        must_exist=True,
    )
    plan_path = ensure_contained_production_path(root, recovery_plan_path, must_exist=True)
    _validate_exact_hash(plan_path, recovery_plan_sha256, "spatial recovery plan")
    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan_payload, dict):
        raise ValueError("surface-detail spatial recovery plan is not an object")
    _validate_recovery_plan(plan_payload, job_id=job_id, session_id=session_id)
    if exact_approval != _expected_recovery_approval(plan_payload, recovery_plan_sha256):
        raise PermissionError("surface-detail spatial recovery approval is not exact")
    _profile, budget, state, state_artifact = _validate_profile_opt_in(
        root,
        session_root,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    if state_artifact.sha256 != plan_payload["source_aq_state_sha256"]:
        raise ValueError("surface-detail spatial recovery source AQ state is stale")
    retry_root = (
        session_root
        / "codex_image_material_loop_promotion_retries"
        / "item-crystalgun-material-promotion-guard-retry-07"
    )
    source_loop_state_path = _validate_exact_hash(
        retry_root / "states" / "0002.json",
        plan_payload["source_material_loop_state_sha256"],
        "source material-loop state",
    )
    source_loop_terminal_path = _validate_exact_hash(
        retry_root / "terminal.json",
        plan_payload["source_material_loop_terminal_sha256"],
        "source material-loop terminal",
    )
    source_retry_receipt_path = _validate_exact_hash(
        retry_root / "retry_receipt.json",
        plan_payload["source_retry_receipt_sha256"],
        "source retry receipt",
    )
    source_bridge_path = _validate_exact_hash(
        retry_root / "bridge_plan.json",
        plan_payload["source_bridge_plan_sha256"],
        "source bridge plan",
    )
    rollback_root = session_root / "material_phase" / "0007"
    rollback_receipt_path = _validate_exact_hash(
        rollback_root / "rollback_receipt.json",
        plan_payload["rollback_receipt_sha256"],
        "rollback receipt",
    )
    source_scene_path = _validate_exact_hash(
        root / "analysis" / "scene_spec.json",
        plan_payload["source_scene_spec_v02_sha256"],
        "source SceneSpec",
    )
    source_modeling_path = _validate_exact_hash(
        root / "analysis" / "modeling_plan.json",
        plan_payload["source_modeling_plan_sha256"],
        "source ModelingPlan",
    )
    source_blend_path = _validate_exact_hash(
        root / "blender" / "scene.blend",
        plan_payload["source_rollback_blend_sha256"],
        "source rollback blend",
    )
    source_inventory_path = _validate_exact_hash(
        rollback_root / "rollback" / "scene_inventory.json",
        plan_payload["source_geometry_inventory_sha256"],
        "source geometry inventory",
    )
    source_provenance_path = _validate_exact_hash(
        rollback_root / "rollback" / "build_provenance.json",
        plan_payload["source_build_provenance_sha256"],
        "source build provenance",
    )
    reference_path = _validate_exact_hash(
        root / "input" / "reference.png",
        plan_payload["reference_sha256"],
        "primary reference",
    )
    source_imagegen_path = _validate_exact_hash(
        session_root
        / "codex_imagegen"
        / "native_normalizations"
        / "crystal-emission-core-pass-through-repair-00"
        / "normalized.png",
        _EXPECTED_REFERENCE_IMAGEGEN_SHA256,
        "immutable ImageGen normalization",
    )
    source_semantic_review_path = _validate_exact_hash(
        session_root
        / "codex_imagegen"
        / "assignments"
        / "material-00"
        / "evidence"
        / "semantic-review-00.json",
        "17122deaa2ab0e7998f30b155f56cd2e2da8c305a63968ccca8db8e9aeb4316d",
        "ImageGen semantic review",
    )
    failed_plan_path = _validate_exact_hash(
        session_root / "controller_outputs" / "material_authoring_repair_00" / "material_plan.json",
        plan_payload["failed_material_plan_sha256"],
        "failed material candidate",
    )
    if sha256_file(reference_path) != _EXPECTED_REFERENCE_SHA256:
        raise ValueError("primary reference hash differs from recovery authorization")
    recovery_id = str(plan_payload["plan_id"])
    recovery_root = session_root / _RECOVERY_DIR / recovery_id
    approval_path = recovery_root / "approval.txt"
    preparation_path = recovery_root / "preparation_receipt.json"
    geometry_review_path = recovery_root / "geometry_review_receipt.json"
    review_plan_path = recovery_root / "geometry_review_plan.json"
    if review_plan_path.exists():
        review_plan = SurfaceDetailSpatialGeometryReviewPlan.model_validate_json(
            review_plan_path.read_bytes()
        )
        receipt_artifact = _artifact(
            root,
            geometry_review_path,
            artifact_id=f"geometry-review-{recovery_id}",
            kind="surface_detail_geometry_review_receipt",
        )
        if receipt_artifact.sha256 != review_plan.geometry_review_receipt_sha256:
            raise ValueError("published spatial geometry review evidence changed")
        return {
            "outcome": "awaiting_geometry_review_approval",
            "review_plan": review_plan.model_dump(mode="json"),
            "review_plan_artifact": _artifact(
                root,
                review_plan_path,
                artifact_id=review_plan.plan_id,
                kind="surface_detail_geometry_review_plan",
            ).model_dump(mode="json"),
            "geometry_review_receipt_artifact": receipt_artifact.model_dump(mode="json"),
            "exact_approval": expected_surface_detail_geometry_review_approval(
                review_plan,
                sha256_file(review_plan_path),
            ),
        }

    with autonomy_session_lock(
        root,
        session_root,
        owner_id="aqv2-surface-detail-spatial-recovery",
        ttl_seconds=3600,
    ):
        os.makedirs(native_io_path(recovery_root / "candidate"), exist_ok=True)
        _write_exact_bytes(approval_path, exact_approval.encode("utf-8"))
        approval_artifact = _artifact(
            root,
            approval_path,
            artifact_id=f"approval-{recovery_id}",
            kind="surface_detail_spatial_recovery_approval",
        )
        source_scene = SceneSpec.model_validate_json(source_scene_path.read_bytes())
        source_modeling = ModelingPlan.model_validate_json(source_modeling_path.read_bytes())
        baseline_material = MaterialPlan.model_validate_json(failed_plan_path.read_bytes())
        candidate_scene = _scene_candidates(source_scene)
        candidate_modeling = _modeling_candidate(source_modeling)
        candidate_scene_path = recovery_root / "candidate" / "scene_spec_v02.json"
        candidate_modeling_path = recovery_root / "candidate" / "modeling_plan.json"
        _write_model(candidate_scene_path, candidate_scene)
        _write_model(candidate_modeling_path, candidate_modeling)
        candidate_scene_artifact = _artifact(
            root,
            candidate_scene_path,
            artifact_id=f"scene-{recovery_id}",
            kind="candidate_scene_spec_v02",
        )
        candidate_modeling_artifact = _artifact(
            root,
            candidate_modeling_path,
            artifact_id=f"modeling-{recovery_id}",
            kind="candidate_modeling_plan",
        )
        uv_fingerprints = _inventory_uv_fingerprints(source_inventory_path)
        manifests, manifest_artifacts, channel_artifacts = _author_texture_assets(
            root=root,
            uv_fingerprints=uv_fingerprints,
            imagegen_source=source_imagegen_path,
            imagegen_semantic_review=source_semantic_review_path,
        )
        _recipes, recipe_artifacts = _author_shader_recipes(
            root=root,
            baseline=baseline_material,
            manifests=manifests,
        )
        candidate_material = _material_candidate(
            root=root,
            baseline=baseline_material,
        )
        candidate_material_path = recovery_root / "candidate" / "material_plan.json"
        _write_model(candidate_material_path, candidate_material)
        candidate_material_artifact = _artifact(
            root,
            candidate_material_path,
            artifact_id=f"material-{recovery_id}",
            kind="candidate_material_plan",
        )
        candidate_graph = _material_graph_candidate(
            root=root,
            recovery_root=recovery_root,
            workflow_id=state.workflow_id,
            dispatch_id=state.dispatch_id,
            candidate_scene_artifact=candidate_scene_artifact,
            candidate_plan_path=candidate_material_artifact.path,
            candidate_plan_sha256=candidate_material_artifact.sha256,
            manifest_artifacts=manifest_artifacts,
            recipe_artifacts=recipe_artifacts,
            channel_artifacts=channel_artifacts,
        )
        candidate_graph_path = recovery_root / "candidate" / "material_graph.json"
        _write_model(candidate_graph_path, candidate_graph)
        candidate_graph_artifact = _artifact(
            root,
            candidate_graph_path,
            artifact_id=f"graph-{recovery_id}",
            kind="candidate_material_graph",
        )
        source_artifacts = [
            _artifact(root, plan_path, artifact_id=f"plan-{recovery_id}", kind="recovery_plan"),
            approval_artifact,
            state_artifact,
            _artifact(
                root,
                source_loop_state_path,
                artifact_id=f"loop-state-{recovery_id}",
                kind="source_material_loop_state",
            ),
            _artifact(
                root,
                source_loop_terminal_path,
                artifact_id=f"loop-terminal-{recovery_id}",
                kind="source_material_loop_terminal",
            ),
            _artifact(
                root,
                source_retry_receipt_path,
                artifact_id=f"retry-{recovery_id}",
                kind="source_retry_receipt",
            ),
            _artifact(
                root,
                source_bridge_path,
                artifact_id=f"bridge-{recovery_id}",
                kind="source_bridge_plan",
            ),
            _artifact(
                root,
                rollback_receipt_path,
                artifact_id=f"rollback-{recovery_id}",
                kind="source_rollback_receipt",
            ),
            _artifact(
                root,
                source_scene_path,
                artifact_id=f"source-scene-{recovery_id}",
                kind="source_scene_spec",
            ),
            _artifact(
                root,
                source_modeling_path,
                artifact_id=f"source-modeling-{recovery_id}",
                kind="source_modeling_plan",
            ),
            _artifact(
                root,
                source_blend_path,
                artifact_id=f"source-blend-{recovery_id}",
                kind="source_rollback_blend",
            ),
            _artifact(
                root,
                source_inventory_path,
                artifact_id=f"source-inventory-{recovery_id}",
                kind="source_inventory",
            ),
            _artifact(
                root,
                source_provenance_path,
                artifact_id=f"source-provenance-{recovery_id}",
                kind="source_build_provenance",
            ),
            candidate_scene_artifact,
            candidate_modeling_artifact,
            candidate_material_artifact,
            candidate_graph_artifact,
            *manifest_artifacts,
            *recipe_artifacts,
            *channel_artifacts,
            _artifact(
                root,
                source_imagegen_path,
                artifact_id=f"imagegen-source-{recovery_id}",
                kind="imagegen_normalized_source",
            ),
            _artifact(
                root,
                source_semantic_review_path,
                artifact_id=f"imagegen-review-{recovery_id}",
                kind="imagegen_semantic_review",
            ),
        ]
        source_by_kind = {item.kind: item for item in source_artifacts}
        preparation = SurfaceDetailSpatialRecoveryPreparation(
            contract_id=f"preparation-{recovery_id}",
            job_id=job_id,
            workflow_id=state.workflow_id,
            dispatch_id=state.dispatch_id,
            session_id=session_id,
            input_sha256=stable_json_digest({item.path: item.sha256 for item in source_artifacts}),
            source_fingerprint=source_by_kind["source_material_loop_terminal"].sha256,
            producer=_PRODUCER,
            provenance=source_artifacts,
            created_at=datetime.now(UTC),
            recovery_id=recovery_id,
            recovery_plan=source_by_kind["recovery_plan"],
            approval=approval_artifact,
            source_aq_state=state_artifact,
            source_material_loop_state=source_by_kind["source_material_loop_state"],
            source_material_loop_terminal=source_by_kind["source_material_loop_terminal"],
            source_retry_receipt=source_by_kind["source_retry_receipt"],
            source_bridge_plan=source_by_kind["source_bridge_plan"],
            rollback_receipt=source_by_kind["source_rollback_receipt"],
            source_scene_spec=source_by_kind["source_scene_spec"],
            source_modeling_plan=source_by_kind["source_modeling_plan"],
            source_rollback_blend=source_by_kind["source_rollback_blend"],
            source_inventory=source_by_kind["source_inventory"],
            source_build_provenance=source_by_kind["source_build_provenance"],
            candidate_scene_spec=candidate_scene_artifact,
            candidate_modeling_plan=candidate_modeling_artifact,
            candidate_material_plan=candidate_material_artifact,
            candidate_material_graph=candidate_graph_artifact,
            texture_manifests=manifest_artifacts,
            shader_recipes=recipe_artifacts,
            texture_channels=channel_artifacts,
            imagegen_source=source_by_kind["imagegen_normalized_source"],
            imagegen_semantic_review=source_by_kind["imagegen_semantic_review"],
            additive_material_ids=list(_ADDITIVE_MATERIAL_IDS),
            material_assignment_specializations=_ASSIGNMENT_SPECIALIZATIONS,
        )
        preparation_artifact = _write_or_adopt_v2_model(
            root=root,
            path=preparation_path,
            model=preparation,
            kind="surface_detail_spatial_recovery_preparation",
        )
        dependency_artifacts = [
            *manifest_artifacts,
            *recipe_artifacts,
            *channel_artifacts,
            source_by_kind["imagegen_normalized_source"],
            source_by_kind["imagegen_semantic_review"],
        ]
        (
            result,
            request_artifact,
            result_artifact,
            profile_artifact,
            assignment_artifact,
            completion_artifact,
            controller_plan_artifact,
            controller_graph_artifact,
            usage,
        ) = _execute_controller(
            root=root,
            session_root=session_root,
            recovery_id=recovery_id,
            preparation_artifact=preparation_artifact,
            state=state,
            state_artifact=state_artifact,
            budget=budget,
            candidate_scene_artifact=candidate_scene_artifact,
            candidate_modeling_artifact=candidate_modeling_artifact,
            candidate_material_artifact=candidate_material_artifact,
            candidate_graph_artifact=candidate_graph_artifact,
            dependency_artifacts=dependency_artifacts,
            plan_artifact=source_by_kind["recovery_plan"],
        )
        del result
        shadow_root = root / "aq2w" / "surface-detail-spatial-recovery-01"
        candidate_scene, candidate_modeling, candidate_material = _prepare_shadow_job(
            root=root,
            shadow_root=shadow_root,
            candidate_scene_path=candidate_scene_path,
            candidate_modeling_path=candidate_modeling_path,
            candidate_material_plan_path=root / controller_plan_artifact.path,
        )
        surface_report = validate_surface_detail_contract(
            candidate_modeling,
            candidate_scene,
            shadow_root,
            material_plan=candidate_material,
            require_materials=True,
            inventory_path=source_inventory_path,
        )
        validation_root = _spatial_staging_root(root) / "val"
        preflight_surface_report_path = validation_root / "surface_preflight.json"
        _write_model(preflight_surface_report_path, surface_report)
        if not surface_report.ok:
            failures = [item.message for item in surface_report.checks if item.status == "failed"]
            raise ValueError(
                "spatial recovery surface-detail validation failed: " + "; ".join(failures)
            )
        provenance = collect_build_provenance(
            shadow_root,
            job_id,
            scene_spec_path=shadow_root / "analysis" / "scene_spec.json",
            validate_contracts=True,
            surface_detail_inventory_path=source_inventory_path,
        )
        build_root = shadow_root / "build"
        blend_path = build_root / "scene.blend"
        inventory_path = build_root / "scene_inventory.json"
        validation_path = build_root / "validation.json"
        preview_path = build_root / "preview.png"
        provenance_path = build_root / "provenance.json"
        run_blender(
            "build_scene.py",
            [
                "--spec",
                str(shadow_root / "analysis" / "scene_spec.json"),
                "--job-root",
                str(shadow_root),
                "--output",
                str(blend_path),
                "--render-engine",
                "eevee",
                "--render-device",
                "auto",
            ],
            factory_startup=True,
            disable_autoexec=True,
        )
        run_blender(
            "inspect_scene.py",
            ["--output", str(inventory_path)],
            blend_file=blend_path,
            disable_autoexec=True,
        )
        run_blender(
            "validate_scene.py",
            [
                "--spec",
                str(shadow_root / "analysis" / "scene_spec.json"),
                "--job-root",
                str(shadow_root),
                "--output",
                str(validation_path),
            ],
            blend_file=blend_path,
            disable_autoexec=True,
        )
        run_blender(
            "render_preview.py",
            [
                "--output",
                str(preview_path),
                "--render-engine",
                "eevee",
                "--render-device",
                "auto",
            ],
            blend_file=blend_path,
            disable_autoexec=True,
        )
        _write_json_object(provenance_path, provenance)
        validation_payload = json.loads(validation_path.read_text(encoding="utf-8"))
        inventory_payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        if validation_payload.get("ok") is not True:
            raise RuntimeError("spatial recovery isolated Blender validation failed")
        if inventory_payload.get("blender_version") != "5.0.1":
            raise RuntimeError("spatial recovery requires actual Blender 5.0.1 evidence")
        surface_report = validate_surface_detail_contract(
            candidate_modeling,
            candidate_scene,
            shadow_root,
            material_plan=candidate_material,
            require_materials=True,
            inventory_path=inventory_path,
        )
        surface_report_path = validation_root / "surface.json"
        _write_model(surface_report_path, surface_report)
        if not surface_report.ok:
            failures = [item.message for item in surface_report.checks if item.status == "failed"]
            raise ValueError(
                "candidate surface-detail inventory validation failed: " + "; ".join(failures)
            )
        candidate_provenance = collect_build_provenance(
            shadow_root,
            job_id,
            scene_spec_path=shadow_root / "analysis" / "scene_spec.json",
            validate_contracts=True,
            surface_detail_inventory_path=inventory_path,
        )
        if candidate_provenance != provenance:
            raise RuntimeError("candidate inventory changed the exact build provenance")
        topology = _topology_comparison(
            source_scene=source_scene,
            candidate_scene=candidate_scene,
            source_inventory_path=source_inventory_path,
            candidate_inventory_path=inventory_path,
        )
        topology_path = validation_root / "topology.json"
        _write_json_object(topology_path, topology)
        if topology["topology_unchanged"] is not True:
            raise RuntimeError("spatial recovery changed geometry topology")
        review_artifacts = [
            preparation_artifact,
            profile_artifact,
            assignment_artifact,
            request_artifact,
            result_artifact,
            completion_artifact,
            candidate_scene_artifact,
            candidate_modeling_artifact,
            controller_plan_artifact,
            controller_graph_artifact,
            _artifact(root, blend_path, artifact_id=f"blend-{recovery_id}", kind="candidate_blend"),
            _artifact(
                root,
                inventory_path,
                artifact_id=f"inventory-{recovery_id}",
                kind="candidate_inventory",
            ),
            _artifact(
                root,
                validation_path,
                artifact_id=f"validation-{recovery_id}",
                kind="candidate_validation",
            ),
            _artifact(
                root,
                provenance_path,
                artifact_id=f"provenance-{recovery_id}",
                kind="candidate_build_provenance",
            ),
            _artifact(
                root,
                surface_report_path,
                artifact_id=f"surface-validation-{recovery_id}",
                kind="surface_detail_validation",
            ),
            _artifact(
                root,
                topology_path,
                artifact_id=f"topology-{recovery_id}",
                kind="topology_comparison",
            ),
            _artifact(
                root, preview_path, artifact_id=f"preview-{recovery_id}", kind="candidate_preview"
            ),
        ]
        by_kind = {item.kind: item for item in review_artifacts}
        geometry_receipt = SurfaceDetailSpatialGeometryReviewReceipt(
            contract_id=f"geometry-review-{recovery_id}",
            job_id=job_id,
            workflow_id=state.workflow_id,
            dispatch_id=state.dispatch_id,
            session_id=session_id,
            input_sha256=stable_json_digest({item.path: item.sha256 for item in review_artifacts}),
            source_fingerprint=result_artifact.sha256,
            producer=_PRODUCER,
            provenance=review_artifacts,
            created_at=datetime.now(UTC),
            recovery_id=recovery_id,
            preparation=preparation_artifact,
            controller_profile=profile_artifact,
            controller_assignment=assignment_artifact,
            controller_request=request_artifact,
            controller_result=result_artifact,
            controller_completion=completion_artifact,
            candidate_scene_spec=candidate_scene_artifact,
            candidate_modeling_plan=candidate_modeling_artifact,
            candidate_material_plan=controller_plan_artifact,
            candidate_material_graph=controller_graph_artifact,
            candidate_blend=by_kind["candidate_blend"],
            candidate_inventory=by_kind["candidate_inventory"],
            candidate_validation=by_kind["candidate_validation"],
            candidate_build_provenance=by_kind["candidate_build_provenance"],
            surface_detail_validation=by_kind["surface_detail_validation"],
            topology_comparison=by_kind["topology_comparison"],
            preview=by_kind["candidate_preview"],
            blender_version="5.0.1",
        )
        geometry_receipt_artifact = _write_or_adopt_v2_model(
            root=root,
            path=geometry_review_path,
            model=geometry_receipt,
            kind="surface_detail_geometry_review_receipt",
        )
        next_state = transition_state(
            state,
            event="controller_output_ready",
            evidence=result_artifact,
            created_at=geometry_receipt.created_at,
            budget_usage=usage,
        )
        next_state_path = session_root / "states" / f"{next_state.sequence:04d}.json"
        if next_state_path.exists():
            existing_state = AutonomyStateV2.model_validate_json(next_state_path.read_bytes())
            if existing_state != next_state:
                raise FileExistsError("spatial recovery AQ state differs")
        else:
            write_immutable_v2_model(root, next_state_path, next_state)
        review_plan = SurfaceDetailSpatialGeometryReviewPlan(
            plan_id=f"geometry-review-plan-{recovery_id}",
            job_id=job_id,
            source_session_id=session_id,
            source_aq_state_sha256=state_artifact.sha256,
            recovery_plan_sha256=recovery_plan_sha256,
            recovery_preparation_sha256=preparation_artifact.sha256,
            controller_result_sha256=result_artifact.sha256,
            candidate_scene_spec_v02_sha256=candidate_scene_artifact.sha256,
            candidate_modeling_plan_sha256=candidate_modeling_artifact.sha256,
            candidate_material_plan_sha256=controller_plan_artifact.sha256,
            candidate_material_graph_sha256=controller_graph_artifact.sha256,
            candidate_blend_sha256=by_kind["candidate_blend"].sha256,
            candidate_inventory_sha256=by_kind["candidate_inventory"].sha256,
            candidate_validation_sha256=by_kind["candidate_validation"].sha256,
            topology_comparison_sha256=by_kind["topology_comparison"].sha256,
            surface_detail_validation_sha256=by_kind["surface_detail_validation"].sha256,
            preview_sha256=by_kind["candidate_preview"].sha256,
            geometry_review_receipt_sha256=geometry_receipt_artifact.sha256,
            additive_material_ids=list(_ADDITIVE_MATERIAL_IDS),
            material_assignment_specializations=_ASSIGNMENT_SPECIALIZATIONS,
        )
        _write_model(review_plan_path, review_plan)
        review_plan_artifact = _artifact(
            root,
            review_plan_path,
            artifact_id=review_plan.plan_id,
            kind="surface_detail_geometry_review_plan",
        )
    return {
        "outcome": "awaiting_geometry_review_approval",
        "review_plan": review_plan.model_dump(mode="json"),
        "review_plan_artifact": review_plan_artifact.model_dump(mode="json"),
        "geometry_review_receipt": geometry_receipt.model_dump(mode="json"),
        "geometry_review_receipt_artifact": geometry_receipt_artifact.model_dump(mode="json"),
        "next_state": next_state.model_dump(mode="json"),
        "exact_approval": expected_surface_detail_geometry_review_approval(
            review_plan,
            review_plan_artifact.sha256,
        ),
    }


def expected_surface_detail_geometry_review_approval(
    plan: SurfaceDetailSpatialGeometryReviewPlan,
    plan_sha256: str,
) -> str:
    """Render the exact geometry review approval requested after spatial recovery validation."""

    derivative_clause = (
        f"material_binding_derivative_sha256={plan.material_binding_derivative_sha256} "
        if plan.material_binding_derivative_sha256 is not None
        else ""
    )
    return (
        "APPROVE MATERIAL SPATIAL RECOVERY GEOMETRY REVIEW "
        f"job_id={plan.job_id} source_session_id={plan.source_session_id} "
        f"source_aq_state_sha256={plan.source_aq_state_sha256} "
        f"recovery_plan_sha256={plan.recovery_plan_sha256} "
        f"geometry_review_plan_sha256={plan_sha256} "
        f"recovery_preparation_sha256={plan.recovery_preparation_sha256} "
        f"controller_result_sha256={plan.controller_result_sha256} "
        f"candidate_scene_spec_v02_sha256={plan.candidate_scene_spec_v02_sha256} "
        f"candidate_modeling_plan_sha256={plan.candidate_modeling_plan_sha256} "
        f"candidate_material_plan_sha256={plan.candidate_material_plan_sha256} "
        f"candidate_material_graph_sha256={plan.candidate_material_graph_sha256} "
        f"candidate_blend_sha256={plan.candidate_blend_sha256} "
        f"candidate_inventory_sha256={plan.candidate_inventory_sha256} "
        f"candidate_validation_sha256={plan.candidate_validation_sha256} "
        f"topology_comparison_sha256={plan.topology_comparison_sha256} "
        f"surface_detail_validation_sha256={plan.surface_detail_validation_sha256} "
        f"preview_sha256={plan.preview_sha256} "
        f"geometry_review_receipt_sha256={plan.geometry_review_receipt_sha256} "
        f"{derivative_clause}"
        "add_material_ids=mat.metal.trim.filigree_body,"
        "mat.crystal.translucent.facet_crown "
        "assignments=prop.crystalgun.frame.trim->mat.metal.trim.filigree_body,"
        "prop.crystalgun.rear.crown->mat.crystal.translucent.facet_crown "
        "topology_unchanged=true semantic_ids_unchanged=true "
        "material_promotion_allowed=false scope=geometry_review_only "
        "delivery_disabled=true optimization_disabled=true lod_disabled=true "
        "collider_disabled=true destination_write_disabled=true"
    )
