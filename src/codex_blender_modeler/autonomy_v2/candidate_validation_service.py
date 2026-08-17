"""Host-only AQ v2 geometry candidate validation and atomic promotion."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from ..analysis.assembly import validate_assembly_prebuild_contract
from ..analysis.models import CameraSolution, ModelingPlan, ReferenceAnalysis
from ..architecture import list_interior_objects
from ..autonomy.io import write_immutable_json
from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..models import SceneSpec
from ..production.controller_executor import (
    ControllerArtifact,
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
)
from ..production.validation import ensure_contained_production_path
from ..reference_scope import (
    reference_content_scope_from_metadata,
    validate_modeling_plan_content_scope,
    validate_scene_content_scope,
)
from ..structural_geometry.geometry_delivery_inspector_v02 import (
    inspect_delivery_geometry_stage_v02,
)
from ..structural_geometry.geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
    compare_geometry_stage_snapshots_v02,
    publish_geometry_survival_report_v02,
)
from ..structural_geometry.mesh_payload_io_v02 import (
    load_mesh_payload_v02,
    verify_mesh_payload_v02_source_hashes,
)
from ..structural_geometry.models import SceneSpecV03, StructuralGeometryCandidate
from ..structural_geometry.service import materialize_structural_candidate
from ..workspace import canonical_scene_spec_write_lock
from .candidate_validation_models import (
    GeometryAuthoringCompletionV2,
    GeometryCandidateValidationReceiptV2,
)
from .delivery_service import (
    artifact_for_v2,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyStateV2,
    BudgetUsageV2,
    RootAuthorizationV2,
)

_STRUCTURAL_KINDS = frozenset(
    {"loft", "sweep", "boolean_tree", "multi_loop_extrude", "geometry_nodes_template"}
)
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ROLE_TAGS = {
    "qa_role:primary": "primary",
    "role:primary": "primary",
    "qa_role:supporting": "supporting",
    "role:supporting": "supporting",
}


@dataclass(frozen=True, slots=True)
class _ControllerBundle:
    """Carry one fully rehashed geometry ControllerExecutor result boundary."""

    result: ControllerResult
    result_artifact: AQV2Artifact
    request: ControllerExecutionRequest
    request_artifact: AQV2Artifact
    profile: PhaseToolProfile
    profile_artifact: AQV2Artifact
    completion: GeometryAuthoringCompletionV2
    completion_artifact: AQV2Artifact
    modeling_artifact: AQV2Artifact
    scene_v03_artifact: AQV2Artifact


@dataclass(frozen=True, slots=True)
class _CandidateCompilation:
    """Carry one V03-to-V02 compilation and all exact materialization artifacts."""

    scene: SceneSpec
    scene_artifact: AQV2Artifact
    recipes: tuple[AQV2Artifact, ...]
    payloads: tuple[AQV2Artifact, ...]
    receipts: tuple[AQV2Artifact, ...]
    blends: tuple[AQV2Artifact, ...]
    topology_profile: str


@dataclass(frozen=True, slots=True)
class _CandidateBuild:
    """Carry isolated build, inspection, validation, and provenance evidence."""

    blend: AQV2Artifact
    inventory: AQV2Artifact
    validation: AQV2Artifact
    provenance: AQV2Artifact
    build_fingerprint: str


@dataclass(frozen=True, slots=True)
class _CanonicalBaseline:
    """Capture one canonical target's exact pre-promotion state."""

    target: Path
    previous_sha256: str | None
    archive: AQV2Artifact | None
    candidate: AQV2Artifact


def _controller_artifact_path(root: Path, artifact: ControllerArtifact) -> Path:
    """Rehash one ControllerExecutor artifact and reject links or path escape."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if (
        not os.path.isfile(native_io_path(path))
        or os.path.getsize(native_io_path(path)) != artifact.byte_size
        or sha256_file(path) != artifact.sha256
    ):
        raise ValueError(f"controller artifact changed: {artifact.path}")
    return path


def _aq_from_controller(
    root: Path,
    artifact: ControllerArtifact,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Project one rehashed controller artifact into the AQ v2 evidence envelope."""

    path = _controller_artifact_path(root, artifact)
    observed = artifact_for_v2(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
    )
    if observed.path != artifact.path or (
        observed.sha256,
        observed.byte_size,
    ) != (artifact.sha256, artifact.byte_size):
        raise ValueError(f"controller artifact projection changed: {artifact.path}")
    return observed


def _read_controller_model(
    root: Path,
    artifact: ControllerArtifact,
    model: type[ControllerExecutionRequest] | type[PhaseToolProfile],
) -> ControllerExecutionRequest | PhaseToolProfile:
    """Strict-parse one exact ControllerExecutor request or phase profile."""

    with open(native_io_path(_controller_artifact_path(root, artifact)), "rb") as handle:
        return model.model_validate_json(handle.read())


def _validate_output_paths(
    request: ControllerExecutionRequest,
    profile: PhaseToolProfile,
    result: ControllerResult,
) -> None:
    """Require exactly the three immediate geometry-authoring leaves and no others."""

    expected_names = ["modeling_plan.json", "scene_spec_v03.json", "completion.json"]
    paths = request.allowed_output_paths
    if [PurePosixPath(item).name for item in paths] != expected_names:
        raise ValueError("geometry controller request has an unexpected output set")
    if any(PurePosixPath(item).parent.as_posix() != request.output_root for item in paths):
        raise ValueError("geometry controller outputs must be immediate output-root children")
    if profile.allowed_output_paths != paths:
        raise ValueError("geometry controller request broadened its phase output profile")
    if [item.path for item in result.outputs] != paths:
        raise ValueError("geometry controller result output order or paths changed")


def _validate_controller_bundle(
    *,
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
) -> _ControllerBundle:
    """Rebuild the exact request/profile/output chain behind the current controller result."""

    if not state.provenance or not state.provenance[-1].path.endswith("/result.json"):
        raise ValueError("current candidate boundary is not anchored by a controller result")
    result_artifact = state.provenance[-1]
    result_path = validate_v2_artifact(root, result_artifact)
    result = ControllerResult.model_validate_json(
        Path(native_io_path(result_path)).read_bytes()
    )
    if result.producer != "codex_blender_modeler.production.controller_executor.service":
        raise PermissionError("geometry candidate result was not published by the executor")
    if result.status != "completed" or not result.canonical_unchanged:
        raise PermissionError("geometry candidate requires a completed isolated result")
    if result.extra_output_count or result.partial_output_count:
        raise PermissionError("geometry candidate result contains incomplete or extra output")
    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    if (result.job_id, result.workflow_id, result.dispatch_id, result.session_id) != identity:
        raise ValueError("geometry controller result belongs to another AQ v2 session")
    for artifact in result.provenance:
        _controller_artifact_path(root, artifact)
    request = _read_controller_model(root, result.request, ControllerExecutionRequest)
    profile = _read_controller_model(root, result.tool_profile, PhaseToolProfile)
    if not isinstance(request, ControllerExecutionRequest) or not isinstance(
        profile, PhaseToolProfile
    ):
        raise TypeError("controller boundary loaded an unexpected contract type")
    if profile.profile_id != "geometry_authoring":
        raise PermissionError("candidate validator accepts only geometry_authoring output")
    if (
        request.producer != "codex_blender_modeler.autonomy_v2.controller_bridge"
        or profile.producer
        != "codex_blender_modeler.production.controller_executor.profiles"
    ):
        raise PermissionError("geometry request or phase profile has an unknown producer")
    planned_profiles = [
        item
        for item in plan.phase_tool_profiles
        if item.path == result.tool_profile.path
        and item.sha256 == result.tool_profile.sha256
        and item.byte_size == result.tool_profile.byte_size
    ]
    if len(planned_profiles) != 1:
        raise PermissionError(
            "geometry controller used a phase profile outside the immutable AQ v2 plan"
        )
    validate_v2_artifact(root, planned_profiles[0])
    if (
        (request.job_id, request.workflow_id, request.dispatch_id, request.session_id)
        != identity
        or (profile.job_id, profile.workflow_id, profile.dispatch_id, profile.session_id)
        != identity
        or request.execution_id != result.execution_id
        or request.tool_profile != result.tool_profile
        or request.controller_kind != result.controller_kind
    ):
        raise ValueError("geometry controller request/profile identity is inconsistent")
    named_provenance = {
        (item.path, item.sha256, item.byte_size) for item in result.provenance
    }
    required_result_artifacts = [result.request, result.tool_profile, *result.outputs]
    if any(
        (item.path, item.sha256, item.byte_size) not in named_provenance
        for item in required_result_artifacts
    ):
        raise ValueError("geometry controller result omits named evidence from provenance")
    request_provenance = {
        (item.path, item.sha256, item.byte_size) for item in request.provenance
    }
    required_request_artifacts = [
        request.assignment,
        *request.immutable_inputs,
        request.tool_profile,
    ]
    if any(
        (item.path, item.sha256, item.byte_size) not in request_provenance
        for item in required_request_artifacts
    ):
        raise ValueError("geometry controller request omits named input provenance")
    _validate_output_paths(request, profile, result)
    output_by_name = {PurePosixPath(item.path).name: item for item in result.outputs}
    modeling_artifact = _aq_from_controller(
        root,
        output_by_name["modeling_plan.json"],
        artifact_id=f"{result.execution_id}-modeling-plan",
        kind="geometry_candidate_modeling_plan",
    )
    scene_artifact = _aq_from_controller(
        root,
        output_by_name["scene_spec_v03.json"],
        artifact_id=f"{result.execution_id}-scene-v03",
        kind="geometry_candidate_scene_spec_v03",
    )
    completion_artifact = _aq_from_controller(
        root,
        output_by_name["completion.json"],
        artifact_id=f"{result.execution_id}-completion",
        kind="geometry_authoring_completion",
    )
    completion = GeometryAuthoringCompletionV2.model_validate_json(
        Path(native_io_path(root / completion_artifact.path)).read_bytes()
    )
    if (
        (
            completion.job_id,
            completion.workflow_id,
            completion.dispatch_id,
            completion.session_id,
        )
        != identity
        or completion.assignment_sha256 != request.assignment.sha256
        or completion.tool_profile_sha256 != result.tool_profile.sha256
        or completion.execution_id != result.execution_id
    ):
        raise ValueError("geometry completion does not bind the exact request inputs")
    expected_siblings = [modeling_artifact, scene_artifact]
    for binding, artifact in zip(completion.outputs, expected_siblings, strict=True):
        if (binding.sha256, binding.byte_size) != (artifact.sha256, artifact.byte_size):
            raise ValueError(f"geometry completion sibling changed: {binding.name}")
    return _ControllerBundle(
        result=result,
        result_artifact=result_artifact,
        request=request,
        request_artifact=_aq_from_controller(
            root,
            result.request,
            artifact_id=f"{result.execution_id}-request",
            kind="controller_execution_request",
        ),
        profile=profile,
        profile_artifact=_aq_from_controller(
            root,
            result.tool_profile,
            artifact_id=f"{result.execution_id}-profile",
            kind="controller_phase_tool_profile",
        ),
        completion=completion,
        completion_artifact=completion_artifact,
        modeling_artifact=modeling_artifact,
        scene_v03_artifact=scene_artifact,
    )


def _require_bound_current_file(
    root: Path,
    request: ControllerExecutionRequest,
    path: Path,
) -> str:
    """Require one current canonical/input file in the request's immutable input map."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    relative = safe.relative_to(root).as_posix()
    matches = [item for item in request.immutable_inputs if item.path == relative]
    if len(matches) != 1:
        raise PermissionError(f"controller request did not bind current input: {relative}")
    _controller_artifact_path(root, matches[0])
    return matches[0].sha256


def _require_current_inputs(
    *,
    root: Path,
    authorization: RootAuthorizationV2,
    bundle: _ControllerBundle,
) -> tuple[str, str | None, str | None]:
    """Revalidate root evidence and every existing canonical source before promotion."""

    primary_path = validate_v2_artifact(root, authorization.primary_reference)
    _require_bound_current_file(root, bundle.request, primary_path)
    _require_bound_current_file(root, bundle.request, root / "analysis/reference_analysis.json")
    _require_bound_current_file(root, bundle.request, root / "analysis/camera_solution.json")
    modeling_hash = _require_bound_current_file(
        root,
        bundle.request,
        root / "analysis/modeling_plan.json",
    )
    optional_hashes: list[str | None] = []
    for path in (root / "analysis/scene_spec.json", root / "blender/scene.blend"):
        if os.path.isfile(native_io_path(path)):
            optional_hashes.append(_require_bound_current_file(root, bundle.request, path))
        else:
            optional_hashes.append(None)
    return modeling_hash, optional_hashes[0], optional_hashes[1]


def _finite_tree(value: object, *, label: str) -> None:
    """Reject non-finite numeric values hidden in nested legacy SceneSpec components."""

    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError(f"{label} contains a non-finite numeric value")
        return
    if isinstance(value, list):
        for item in value:
            _finite_tree(item, label=label)
        return
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item, label=label)


def _object_role(tags: list[str], object_id: str) -> str:
    """Resolve exactly one primary/supporting role from a V03 object's tags."""

    roles = {
        role
        for tag, role in _ROLE_TAGS.items()
        if tag in {str(value).strip().casefold() for value in tags}
    }
    if len(roles) != 1:
        raise ValueError(f"{object_id} requires exactly one primary/supporting QA role")
    return next(iter(roles))


def _validate_camera_binding(root: Path, scene: SceneSpecV03) -> None:
    """Bind the candidate camera to the deterministic V0.4 camera solution."""

    solution = CameraSolution.model_validate_json(
        (root / "analysis/camera_solution.json").read_bytes()
    )
    if solution.job_id != scene.job_id or solution.projection != scene.camera.projection:
        raise ValueError("SceneSpecV03 camera projection differs from its camera solution")
    if abs(solution.focal_length_mm - scene.camera.focal_length_mm) > 1.0e-6:
        raise ValueError("SceneSpecV03 focal length differs from its camera solution")
    direction = [
        scene.camera.target[index] - scene.camera.location[index] for index in range(3)
    ]
    length = math.sqrt(sum(value * value for value in direction))
    reference_length = math.sqrt(sum(value * value for value in solution.view_direction))
    if length <= 1.0e-9 or reference_length <= 1.0e-9:
        raise ValueError("SceneSpecV03 camera has a degenerate view direction")
    dot = sum(
        direction[index] * solution.view_direction[index] for index in range(3)
    ) / (length * reference_length)
    if dot < 0.95:
        raise ValueError("SceneSpecV03 camera direction conflicts with its camera solution")
    width, height = scene.camera.resolution
    if min(width, height) <= 0 or max(width, height) > 8192:
        raise ValueError("SceneSpecV03 camera resolution is outside [1, 8192]")


def _validate_candidate_contracts(
    *,
    root: Path,
    authorization: RootAuthorizationV2,
    bundle: _ControllerBundle,
) -> tuple[ModelingPlan, SceneSpecV03]:
    """Validate object-only semantic, material, source, and camera candidate contracts."""

    modeling = ModelingPlan.model_validate_json(
        Path(native_io_path(root / bundle.modeling_artifact.path)).read_bytes()
    )
    scene = SceneSpecV03.model_validate_json(
        Path(native_io_path(root / bundle.scene_v03_artifact.path)).read_bytes()
    )
    if modeling.job_id != authorization.job_id or scene.job_id != authorization.job_id:
        raise ValueError("geometry controller authored contracts for another job")
    if modeling.stage != "authored" or scene.mode != "concept":
        raise ValueError("AQ v2 geometry candidate must be an authored concept")
    metadata_payload = json.loads((root / "job.json").read_text(encoding="utf-8"))
    if not isinstance(metadata_payload, dict):
        raise ValueError("job metadata must be a JSON object")
    metadata = metadata_payload
    scope, target = reference_content_scope_from_metadata(metadata)
    if (
        scope != "primary_object_only"
        or target != authorization.target_subject
        or authorization.reference_content_scope != scope
    ):
        raise PermissionError("candidate content scope or target differs from authorization")
    validate_modeling_plan_content_scope(
        modeling,
        scope="primary_object_only",
        target_subject=authorization.target_subject,
    )
    expected_reference_path = "analysis/reference_analysis.json"
    expected_camera_path = "analysis/camera_solution.json"
    if (
        modeling.reference_analysis_path != expected_reference_path
        or modeling.camera_solution_path != expected_camera_path
    ):
        raise ValueError("ModelingPlan does not bind the canonical reference diagnostics")
    reference = ReferenceAnalysis.model_validate_json(
        (root / expected_reference_path).read_bytes()
    )
    if reference.job_id != authorization.job_id:
        raise ValueError("reference analysis belongs to another job")
    plan_ids = [item.id for item in modeling.objects]
    scene_ids = [item.id for item in scene.objects]
    if plan_ids != scene_ids:
        raise ValueError("ModelingPlan and SceneSpecV03 semantic IDs/order differ")
    plan_roles = {item.id: item.scope_role for item in modeling.objects}
    for item in scene.objects:
        if _object_role(list(item.tags), item.id) != plan_roles[item.id]:
            raise ValueError(f"semantic QA role differs between contracts: {item.id}")
    if not scene.objects or not scene.materials:
        raise ValueError("SceneSpecV03 requires nonempty objects and materials")
    if any(
        _STABLE_ID.fullmatch(item.id) is None or not item.name.strip()
        for item in scene.materials
    ):
        raise ValueError("SceneSpecV03 material IDs must be stable portable identities")
    if any(
        any(channel < 0.0 or channel > 1.0 for channel in item.base_color)
        for item in scene.materials
    ):
        raise ValueError("SceneSpecV03 material colors must stay within [0, 1]")
    if any(item.texture_manifest is not None for item in scene.materials):
        raise PermissionError("geometry_authoring cannot introduce texture manifests")
    structural = [item for item in scene.objects if item.geometry.kind in _STRUCTURAL_KINDS]
    if len(structural) != len(scene.objects):
        unsupported = sorted(
            f"{item.id}:{item.geometry.kind}"
            for item in scene.objects
            if item.geometry.kind not in _STRUCTURAL_KINDS
        )
        raise ValueError(
            "AQ v2 geometry candidate accepts only whitelisted structural V03 "
            f"objects: {unsupported}"
        )
    for item in scene.objects:
        if (
            item.geometry_intent is None
            or item.geometry_intent.smoothing_policy.mode == "legacy"
        ):
            raise ValueError(
                f"{item.id} requires explicit non-legacy GeometryIntent for MeshPayload 0.2"
            )
        if item.modifiers or item.generator is not None or item.editable:
            raise PermissionError(
                f"{item.id} must express structural effects only through GeometryIntent"
            )
    reference_sources = [item for item in scene.sources if item.kind == "reference"]
    if len(reference_sources) != 1:
        raise ValueError("SceneSpecV03 requires one primary reference source")
    source_ids = [item.id for item in scene.sources]
    if (
        len(source_ids) != len(set(source_ids))
        or any(_STABLE_ID.fullmatch(item) is None for item in source_ids)
    ):
        raise ValueError("SceneSpecV03 source IDs must be unique stable identities")
    declared_sources = set(source_ids)
    missing_evidence_sources = sorted(
        {
            evidence.source_id
            for item in scene.objects
            for evidence in item.evidence
        }
        - declared_sources
    )
    missing_plan_sources = sorted(
        {source_id for item in modeling.objects for source_id in item.source_ids}
        - declared_sources
    )
    missing_reference_sources = sorted(
        {item.source_id for item in reference.images} - declared_sources
    )
    if missing_evidence_sources or missing_plan_sources or missing_reference_sources:
        raise ValueError(
            "candidate semantic evidence references undeclared sources: "
            f"scene={missing_evidence_sources}, plan={missing_plan_sources}, "
            f"analysis={missing_reference_sources}"
        )
    primary = authorization.primary_reference
    if reference_sources[0].path != primary.path or not reference_sources[0].immutable:
        raise PermissionError("SceneSpecV03 primary source differs from RootAuthorization")
    for source in scene.sources:
        source_path = ensure_contained_production_path(
            root,
            root / source.path,
            must_exist=True,
        )
        if not source.immutable or not os.path.isfile(native_io_path(source_path)):
            raise PermissionError("SceneSpecV03 source is not immutable contained evidence")
    _finite_tree(scene.model_dump(mode="json"), label="SceneSpecV03")
    _validate_camera_binding(root, scene)
    return modeling, scene


def _compile_scene_v03(
    *,
    root: Path,
    validation_root: Path,
    scene_v03: SceneSpecV03,
) -> _CandidateCompilation:
    """Materialize every structural V03 object as MeshPayload 0.2 and compile V02."""

    compiled_objects: list[dict[str, Any]] = []
    recipes: list[AQV2Artifact] = []
    payloads: list[AQV2Artifact] = []
    receipts: list[AQV2Artifact] = []
    blends: list[AQV2Artifact] = []
    topology_profiles: set[str] = set()
    for index, item in enumerate(scene_v03.objects, start=1):
        object_payload = item.model_dump(mode="json")
        object_payload.pop("geometry_intent", None)
        if item.geometry.kind in _STRUCTURAL_KINDS:
            intent = item.geometry_intent
            if intent is None:
                raise RuntimeError("validated structural object lost GeometryIntent")
            topology_profiles.add(intent.topology_policy)
            component = f"o{index:03d}-{stable_json_digest(item.id)[:8]}"
            component_root = validation_root / "s" / component
            recipe_path = component_root / "r.json"
            payload_path = component_root / "m.json"
            blend_path = component_root / "m.blend"
            report_path = component_root / "receipt.json"
            recipe = StructuralGeometryCandidate(
                semantic_id=item.id,
                geometry=item.geometry,  # type: ignore[arg-type]
                geometry_intent=intent,
            )
            relative = {
                path: path.relative_to(root).as_posix()
                for path in (recipe_path, payload_path, blend_path, report_path)
            }
            materialize_structural_candidate(
                job_root=root,
                candidate=recipe,
                candidate_relative_path=relative[recipe_path],
                mesh_relative_path=relative[payload_path],
                blend_relative_path=relative[blend_path],
                report_relative_path=relative[report_path],
                mesh_payload_version="0.2.0",
                material_id=item.material_id,
            )
            payload = load_mesh_payload_v02(payload_path)
            payload.assert_compilable()
            verify_mesh_payload_v02_source_hashes(payload, job_root=root)
            if payload.semantic_id != item.id or payload.schema_version != "0.2.0":
                raise RuntimeError("materialized MeshPayload 0.2 changed semantic identity")
            object_payload["geometry"] = {
                "kind": "custom_mesh",
                "path": relative[payload_path],
                "format": "mesh_json",
                "recalculate_normals": True,
            }
            recipes.append(
                artifact_for_v2(
                    root, recipe_path, artifact_id=f"{component}-recipe", kind="structural_recipe"
                )
            )
            payloads.append(
                artifact_for_v2(
                    root,
                    payload_path,
                    artifact_id=f"{component}-mesh-v02",
                    kind="mesh_payload_v02",
                )
            )
            receipts.append(
                artifact_for_v2(
                    root,
                    report_path,
                    artifact_id=f"{component}-materialization-receipt",
                    kind="structural_materialization_receipt",
                )
            )
            blends.append(
                artifact_for_v2(
                    root,
                    blend_path,
                    artifact_id=f"{component}-materialization-blend",
                    kind="structural_materialization_blend",
                )
            )
        compiled_objects.append(object_payload)
    payload = scene_v03.model_dump(mode="json")
    payload["schema_version"] = "0.2.0"
    payload["objects"] = compiled_objects
    compiled = SceneSpec.model_validate(payload)
    compiled_path = validation_root / "scene.json"
    write_immutable_json(root, compiled_path, compiled.model_dump(mode="json"))
    topology_profile = (
        next(iter(topology_profiles))
        if len(topology_profiles) == 1
        else f"mixed.{stable_json_digest(sorted(topology_profiles))[:16]}"
    )
    return _CandidateCompilation(
        scene=compiled,
        scene_artifact=artifact_for_v2(
            root,
            compiled_path,
            artifact_id=f"compiled-{validation_root.name}",
            kind="compiled_scene_spec_v02",
        ),
        recipes=tuple(recipes),
        payloads=tuple(payloads),
        receipts=tuple(receipts),
        blends=tuple(blends),
        topology_profile=topology_profile,
    )


def _copy_exact(source: Path, destination: Path, expected_sha256: str) -> None:
    """Copy or adopt one exact contained file without silently replacing evidence."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != expected_sha256:
            raise FileExistsError(destination)
        return
    shutil.copy2(native_io_path(source), native_io_path(destination))
    if sha256_file(destination) != expected_sha256:
        raise RuntimeError(f"isolated copy hash changed: {destination.name}")


def _build_isolated_candidate(
    *,
    root: Path,
    validation_root: Path,
    modeling_artifact: AQV2Artifact,
    compilation: _CandidateCompilation,
) -> _CandidateBuild:
    """Build, inspect, and validate one candidate against a copied candidate-owned root."""

    workspace = root / "aq2w" / validation_root.name
    (workspace / "analysis").mkdir(parents=True, exist_ok=False)
    _copy_exact(root / "job.json", workspace / "job.json", sha256_file(root / "job.json"))
    _copy_exact(
        root / modeling_artifact.path,
        workspace / "analysis/modeling_plan.json",
        modeling_artifact.sha256,
    )
    modeling = ModelingPlan.model_validate_json(
        (root / modeling_artifact.path).read_bytes()
    )
    for relative in (
        modeling.reference_analysis_path,
        modeling.camera_solution_path,
    ):
        dependency = ensure_contained_production_path(
            root,
            root / relative,
            must_exist=True,
        )
        _copy_exact(
            dependency,
            workspace / relative,
            sha256_file(dependency),
        )
    _copy_exact(
        root / compilation.scene_artifact.path,
        workspace / "analysis/scene_spec.json",
        compilation.scene_artifact.sha256,
    )
    for source in compilation.scene.sources:
        source_path = root / source.path
        _copy_exact(source_path, workspace / source.path, sha256_file(source_path))
    for artifact in [*compilation.recipes, *compilation.payloads]:
        _copy_exact(root / artifact.path, workspace / artifact.path, artifact.sha256)
    scene_path = workspace / "analysis/scene_spec.json"
    provenance = collect_build_provenance(
        workspace,
        compilation.scene.job_id,
        scene_spec_path=scene_path,
        validate_contracts=True,
    )
    build_root = workspace / "build"
    blend = build_root / "scene.blend"
    inventory = build_root / "scene_inventory.json"
    validation = build_root / "validation.json"
    run_blender(
        "build_scene.py",
        ["--spec", str(scene_path), "--job-root", str(workspace), "--output", str(blend)],
        factory_startup=True,
        disable_autoexec=True,
    )
    run_blender(
        "inspect_scene.py",
        ["--output", str(inventory)],
        blend_file=blend,
        disable_autoexec=True,
    )
    run_blender(
        "validate_scene.py",
        ["--spec", str(scene_path), "--job-root", str(workspace), "--output", str(validation)],
        blend_file=blend,
        disable_autoexec=True,
    )
    validation_payload = json.loads(validation.read_text(encoding="utf-8"))
    inventory_payload = json.loads(inventory.read_text(encoding="utf-8"))
    if not isinstance(validation_payload, dict) or validation_payload.get("ok") is not True:
        raise RuntimeError("isolated geometry candidate validation did not pass")
    expected_ids = {item.id for item in compilation.scene.objects}
    observed_ids = {
        str(item.get("cbm_id"))
        for item in inventory_payload.get("families", [])
        if isinstance(item, dict) and item.get("cbm_id")
    }
    if observed_ids != expected_ids:
        raise RuntimeError("isolated candidate inventory changed semantic object IDs")
    missing_uv = sorted(
        str(item.get("cbm_id"))
        for item in inventory_payload.get("objects", [])
        if isinstance(item, dict)
        and item.get("cbm_id")
        and item.get("type") == "MESH"
        and not item.get("active_uv")
    )
    if missing_uv:
        raise RuntimeError(f"isolated candidate meshes lack UVMap evidence: {missing_uv}")
    observed_provenance = collect_build_provenance(
        workspace,
        compilation.scene.job_id,
        scene_spec_path=scene_path,
        validate_contracts=True,
    )
    if observed_provenance != provenance:
        raise RuntimeError("candidate build inputs changed during isolated Blender execution")
    provenance_path = build_root / "provenance.json"
    write_immutable_json(root, provenance_path, provenance)
    return _CandidateBuild(
        blend=artifact_for_v2(
            root, blend, artifact_id=f"{validation_root.name}-blend", kind="candidate_blend"
        ),
        inventory=artifact_for_v2(
            root,
            inventory,
            artifact_id=f"{validation_root.name}-inventory",
            kind="candidate_inventory",
        ),
        validation=artifact_for_v2(
            root,
            validation,
            artifact_id=f"{validation_root.name}-validation",
            kind="candidate_validation",
        ),
        provenance=artifact_for_v2(
            root,
            provenance_path,
            artifact_id=f"{validation_root.name}-build-provenance",
            kind="candidate_build_provenance",
        ),
        build_fingerprint=str(provenance["fingerprint"]),
    )


def _reserve_candidate_budget(
    usage: BudgetUsageV2,
    budget: AutonomyBudgetV2,
    *,
    materialization_builds: int,
) -> BudgetUsageV2:
    """Reserve structural materializations, one candidate build, and one promotion."""

    updated = usage.model_copy(
        update={
            "initial_candidates": usage.initial_candidates + 1,
            "total_blender_builds": (
                usage.total_blender_builds + materialization_builds + 1
            ),
            "canonical_promotions": usage.canonical_promotions + 1,
            "total_actions": usage.total_actions + 1,
        }
    )
    limits = {
        "initial_candidates": budget.initial_candidates,
        "total_blender_builds": budget.total_blender_builds,
        "canonical_promotions": budget.canonical_promotions,
        "total_actions": budget.global_action_limit,
    }
    for field, limit in limits.items():
        if getattr(updated, field) > limit:
            raise PermissionError(f"AQ v2 {field} budget is exhausted")
    return updated


def _archive_baseline(
    *,
    root: Path,
    session_id: str,
    target: Path,
    candidate: AQV2Artifact,
) -> _CanonicalBaseline:
    """Archive one existing canonical file before any grouped replacement starts."""

    previous = sha256_file(target) if os.path.isfile(native_io_path(target)) else None
    archive_artifact = None
    if previous is not None:
        archive_path = (
            root
            / "history"
            / "aq2"
            / stable_json_digest(session_id)[:16]
            / "g"
            / f"{target.stem}-{previous[:16]}.bak"
        )
        _copy_exact(target, archive_path, previous)
        archive_artifact = artifact_for_v2(
            root,
            archive_path,
            artifact_id=f"archive-{target.stem}-{previous[:12]}",
            kind="canonical_archive",
        )
    return _CanonicalBaseline(
        target=target,
        previous_sha256=previous,
        archive=archive_artifact,
        candidate=candidate,
    )


def _stage_canonical_copy(root: Path, baseline: _CanonicalBaseline) -> Path:
    """Create one exact adjacent promotion copy without touching its canonical target."""

    source = validate_v2_artifact(root, baseline.candidate)
    staging = baseline.target.with_name(
        f".{baseline.target.name}.aqv2-{uuid4().hex}.tmp"
    )
    staging.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(native_io_path(source), native_io_path(staging))
    if sha256_file(staging) != baseline.candidate.sha256:
        os.unlink(native_io_path(staging))
        raise RuntimeError("canonical promotion staging copy changed")
    return staging


def _rollback_canonical_files(root: Path, baselines: list[_CanonicalBaseline]) -> None:
    """Restore every exact baseline or remove only files introduced by this transaction."""

    errors: list[str] = []
    for baseline in reversed(baselines):
        try:
            if baseline.previous_sha256 is None:
                if os.path.isfile(native_io_path(baseline.target)):
                    if sha256_file(baseline.target) != baseline.candidate.sha256:
                        raise RuntimeError("new canonical target changed before rollback")
                    os.unlink(native_io_path(baseline.target))
                continue
            if baseline.archive is None:
                raise RuntimeError("existing canonical target has no exact archive")
            archive_path = baseline.target.with_name(
                f".{baseline.target.name}.{uuid4().hex}.rollback.tmp"
            )
            archive = validate_v2_artifact(root, baseline.archive)
            shutil.copy2(native_io_path(archive), native_io_path(archive_path))
            if sha256_file(archive_path) != baseline.previous_sha256:
                raise RuntimeError("rollback archive staging hash changed")
            os.replace(native_io_path(archive_path), native_io_path(baseline.target))
        except Exception as exc:  # pragma: no cover - exercised only on host IO failure
            errors.append(f"{baseline.target.name}: {exc}")
    if errors:
        raise RuntimeError("canonical rollback failed: " + "; ".join(errors))


def _validate_existing_receipt(
    *,
    root: Path,
    plan: AutonomyPlanV2,
    path: Path,
    expected_result: AQV2Artifact,
) -> tuple[GeometryCandidateValidationReceiptV2, AQV2Artifact]:
    """Adopt one completed promotion only after rehashing all canonical evidence."""

    artifact = artifact_for_v2(
        root,
        path,
        artifact_id=f"geometry-validation-{plan.session_id}",
        kind="geometry_candidate_validation_receipt",
    )
    receipt = GeometryCandidateValidationReceiptV2.model_validate_json(path.read_bytes())
    if (
        receipt.job_id != plan.job_id
        or receipt.workflow_id != plan.workflow_id
        or receipt.dispatch_id != plan.dispatch_id
        or receipt.session_id != plan.session_id
        or receipt.controller_result != expected_result
    ):
        raise ValueError("geometry validation receipt belongs to another AQ v2 session")
    for item in receipt.provenance:
        validate_v2_artifact(root, item)
    if (
        receipt.canonical_modeling_plan.path != "analysis/modeling_plan.json"
        or receipt.canonical_scene_spec.path != "analysis/scene_spec.json"
        or receipt.canonical_blend.path != "blender/scene.blend"
    ):
        raise ValueError("geometry validation receipt names unexpected canonical paths")
    source_snapshot = GeometryStageSnapshotV02.model_validate_json(
        (root / receipt.candidate_geometry_snapshot.path).read_bytes()
    )
    target_snapshot = GeometryStageSnapshotV02.model_validate_json(
        (root / receipt.canonical_geometry_snapshot.path).read_bytes()
    )
    report = GeometryIntentSurvivalReportV02.model_validate_json(
        (root / receipt.geometry_intent_survival.path).read_bytes()
    )
    recomputed = compare_geometry_stage_snapshots_v02(
        report_id=report.report_id,
        relation="candidate_to_canonical",
        source=source_snapshot,
        target=target_snapshot,
    )
    if report != recomputed or report.overall_status != "exact":
        raise ValueError("candidate-to-canonical GeometryIntent survival is stale")
    return receipt, artifact


def _validate_geometry_policy_authority(
    plan: AutonomyPlanV2,
    result_artifact: AQV2Artifact,
    policy_authorization_path: str | Path | None,
    *,
    require_unused: bool = True,
) -> bool:
    """Require policy presence and optionally replay unused geometry authority."""

    from .approval_policy_service import (
        policy_authorization_required,
        validate_routine_policy_authorization,
    )

    required = policy_authorization_required(
        plan.job_id,
        plan.session_id,
        "geometry_candidate_promotion",
    )
    if required and policy_authorization_path is None:
        raise PermissionError(
            "Approval Envelope geometry promotion requires PolicyAuthorization"
        )
    if not required:
        if policy_authorization_path is not None:
            raise PermissionError(
                "geometry policy authorization was supplied outside a required envelope gate"
            )
        return False
    if require_unused:
        validate_routine_policy_authorization(
            plan.job_id,
            plan.session_id,
            policy_authorization_path=policy_authorization_path,
            expected_gate_kind="geometry_candidate_promotion",
            expected_target_path=result_artifact.path,
        )
    return True


def _require_geometry_policy_decision(
    plan: AutonomyPlanV2,
    policy_authorization_path: str | Path,
    receipt_artifact: AQV2Artifact,
) -> dict[str, object]:
    """Require the unique applied decision that commits one geometry promotion receipt."""

    from .approval_policy_service import get_applied_policy_decision_receipt

    return get_applied_policy_decision_receipt(
        plan.job_id,
        plan.session_id,
        policy_authorization_path=policy_authorization_path,
        action_result_path=receipt_artifact.path,
    )


def validate_geometry_candidate_validation_receipt_v2(
    root: Path,
    plan: AutonomyPlanV2,
    artifact: AQV2Artifact,
) -> GeometryCandidateValidationReceiptV2:
    """Rehash one published geometry receipt and all current promotion evidence."""

    path = validate_v2_artifact(root, artifact)
    receipt = GeometryCandidateValidationReceiptV2.model_validate_json(path.read_bytes())
    validated, normalized = _validate_existing_receipt(
        root=root,
        plan=plan,
        path=path,
        expected_result=receipt.controller_result,
    )
    if normalized != artifact:
        raise ValueError("geometry validation receipt binding changed")
    return validated


def validate_and_promote_geometry_candidate_v2(
    *,
    job_root: Path,
    session_root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
    authorization: RootAuthorizationV2,
    policy_authorization_path: str | Path | None = None,
) -> tuple[GeometryCandidateValidationReceiptV2, AQV2Artifact]:
    """Validate and commit geometry with its required policy decision inside the lock."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    session = ensure_contained_production_path(root, session_root, must_exist=True)
    if state.next_action != "validate_candidate" or state.phase != "authoring":
        raise PermissionError("AQ v2 state is not at geometry candidate validation")
    expected_plan_path = (session / "plan.json").relative_to(root).as_posix()
    if state.plan.path != expected_plan_path:
        raise PermissionError("AQ v2 state does not bind the selected session plan")
    planned_plan = AutonomyPlanV2.model_validate_json(
        validate_v2_artifact(root, state.plan).read_bytes()
    )
    planned_budget = AutonomyBudgetV2.model_validate_json(
        validate_v2_artifact(root, plan.budget).read_bytes()
    )
    if plan != planned_plan or budget != planned_budget:
        raise PermissionError("AQ v2 plan or budget differs from immutable session evidence")
    authorization_path = validate_v2_artifact(root, plan.root_authorization)
    planned_authorization = RootAuthorizationV2.model_validate_json(
        authorization_path.read_bytes()
    )
    if authorization.status != "active" or authorization != planned_authorization:
        raise PermissionError("AQ v2 root authorization is not active or plan-bound")
    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    if (
        (
            authorization.job_id,
            authorization.workflow_id,
            authorization.dispatch_id,
            authorization.session_id,
        )
        != identity
        or (
            authorization.expires_at is not None
            and authorization.expires_at <= datetime.now(UTC)
        )
    ):
        raise PermissionError("AQ v2 root authorization identity or expiry is invalid")
    if (
        plan.profile != authorization.profile
        or plan.budget != authorization.budget
        or plan.phase_tool_profiles != authorization.phase_tool_profiles
        or plan.requested_delivery_profiles
        != authorization.requested_delivery_profiles
    ):
        raise PermissionError("AQ v2 plan broadens or changes root authorization")
    if not state.provenance or not state.provenance[-1].path.endswith("/result.json"):
        raise ValueError("current candidate boundary is not anchored by a controller result")
    current_result_artifact = state.provenance[-1]
    current_result = ControllerResult.model_validate_json(
        validate_v2_artifact(root, current_result_artifact).read_bytes()
    )
    if (
        current_result.status != "completed"
        or (
            current_result.job_id,
            current_result.workflow_id,
            current_result.dispatch_id,
            current_result.session_id,
        )
        != identity
    ):
        raise ValueError("current geometry result is incomplete or belongs to another session")
    validation_id = stable_json_digest(
        {
            "session_id": plan.session_id,
            "execution_id": current_result.execution_id,
        }
    )[:20]
    validation_root = ensure_contained_production_path(
        root,
        root / "aq2" / validation_id,
        must_exist=False,
    )
    receipt_path = validation_root / "receipt.json"
    policy_required = _validate_geometry_policy_authority(
        plan,
        current_result_artifact,
        policy_authorization_path,
        require_unused=not os.path.isfile(native_io_path(receipt_path)),
    )
    if os.path.isfile(native_io_path(receipt_path)):
        receipt, receipt_artifact = _validate_existing_receipt(
            root=root,
            plan=plan,
            path=receipt_path,
            expected_result=current_result_artifact,
        )
        if policy_required:
            if policy_authorization_path is None:  # pragma: no cover - guarded above.
                raise RuntimeError("required geometry policy authorization disappeared")
            _require_geometry_policy_decision(
                plan,
                policy_authorization_path,
                receipt_artifact,
            )
        return receipt, receipt_artifact
    bundle = _validate_controller_bundle(root=root, plan=plan, state=state)
    baseline_hashes = _require_current_inputs(
        root=root,
        authorization=authorization,
        bundle=bundle,
    )
    modeling, scene_v03 = _validate_candidate_contracts(
        root=root,
        authorization=authorization,
        bundle=bundle,
    )
    usage = _reserve_candidate_budget(
        state.budget_usage,
        budget,
        materialization_builds=len(scene_v03.objects),
    )
    validation_root.mkdir(parents=True, exist_ok=False)
    compilation = _compile_scene_v03(
        root=root,
        validation_root=validation_root,
        scene_v03=scene_v03,
    )
    validate_scene_content_scope(
        compilation.scene,
        scope="primary_object_only",
        target_subject=authorization.target_subject,
    )
    interiors = sorted(item.id for item in list_interior_objects(compilation.scene))
    if interiors:
        raise PermissionError(f"AQ v2 geometry candidate contains interiors: {interiors}")
    assembly = validate_assembly_prebuild_contract(modeling, compilation.scene)
    if not assembly.ok:
        failures = [item.message for item in assembly.checks if item.status == "failed"]
        raise ValueError("candidate assembly contract failed: " + "; ".join(failures))
    build = _build_isolated_candidate(
        root=root,
        validation_root=validation_root,
        modeling_artifact=bundle.modeling_artifact,
        compilation=compilation,
    )
    source_fingerprint = stable_json_digest(
        {
            "authorization": plan.root_authorization.sha256,
            "controller_result": bundle.result_artifact.sha256,
            "modeling_plan": bundle.modeling_artifact.sha256,
            "scene_v03": bundle.scene_v03_artifact.sha256,
            "compiled_scene": compilation.scene_artifact.sha256,
            "payloads": [item.sha256 for item in compilation.payloads],
        }
    )
    candidate_snapshot_path = validation_root / "candidate_geometry.json"
    candidate_snapshot = inspect_delivery_geometry_stage_v02(
        job_root=root,
        artifact_relative_path=build.blend.path,
        stage="compiled_candidate",
        output_relative_path=candidate_snapshot_path.relative_to(root).as_posix(),
        source_fingerprint_sha256=source_fingerprint,
        build_fingerprint_sha256=build.build_fingerprint,
        topology_profile=compilation.topology_profile,
    )
    candidate_snapshot_artifact = artifact_for_v2(
        root,
        candidate_snapshot_path,
        artifact_id=f"{bundle.result.execution_id}-candidate-geometry",
        kind="geometry_stage_snapshot_v02",
    )
    owner = f"aqv2-geometry-{plan.session_id}"
    with canonical_scene_spec_write_lock(plan.job_id, owner, ttl_seconds=3600):
        refreshed = _validate_controller_bundle(root=root, plan=plan, state=state)
        if refreshed.result_artifact != bundle.result_artifact:
            raise ValueError("controller result changed before canonical promotion")
        if _require_current_inputs(
            root=root,
            authorization=authorization,
            bundle=refreshed,
        ) != baseline_hashes:
            raise ValueError("canonical baseline changed before geometry promotion")
        baselines = [
            _archive_baseline(
                root=root,
                session_id=plan.session_id,
                target=root / "analysis/modeling_plan.json",
                candidate=bundle.modeling_artifact,
            ),
            _archive_baseline(
                root=root,
                session_id=plan.session_id,
                target=root / "analysis/scene_spec.json",
                candidate=compilation.scene_artifact,
            ),
            _archive_baseline(
                root=root,
                session_id=plan.session_id,
                target=root / "blender/scene.blend",
                candidate=build.blend,
            ),
        ]
        staged = [_stage_canonical_copy(root, item) for item in baselines]
        try:
            for baseline, staging in zip(baselines, staged, strict=True):
                os.replace(native_io_path(staging), native_io_path(baseline.target))
                if sha256_file(baseline.target) != baseline.candidate.sha256:
                    raise RuntimeError("canonical promotion changed validated bytes")
            canonical_provenance = collect_build_provenance(
                root,
                plan.job_id,
                scene_spec_path=root / "analysis/scene_spec.json",
                validate_contracts=True,
            )
            candidate_provenance = json.loads(
                (root / build.provenance.path).read_text(encoding="utf-8")
            )
            if canonical_provenance != candidate_provenance:
                raise RuntimeError("promoted canonical build provenance differs from candidate")
            canonical_snapshot_path = validation_root / "canonical_geometry.json"
            canonical_snapshot = inspect_delivery_geometry_stage_v02(
                job_root=root,
                artifact_relative_path="blender/scene.blend",
                stage="promoted_canonical",
                output_relative_path=canonical_snapshot_path.relative_to(root).as_posix(),
                source_fingerprint_sha256=source_fingerprint,
                build_fingerprint_sha256=build.build_fingerprint,
                topology_profile=compilation.topology_profile,
            )
            survival = compare_geometry_stage_snapshots_v02(
                report_id=f"survival-{bundle.result.execution_id}-candidate-canonical",
                relation="candidate_to_canonical",
                source=candidate_snapshot,
                target=canonical_snapshot,
            )
            if survival.overall_status != "exact":
                raise RuntimeError("candidate-to-canonical GeometryIntent survival failed")
            survival_path = validation_root / "survival.json"
            publish_geometry_survival_report_v02(survival_path, survival)
            canonical_modeling = artifact_for_v2(
                root,
                root / "analysis/modeling_plan.json",
                artifact_id=f"canonical-modeling-{plan.session_id}",
                kind="canonical_modeling_plan",
            )
            canonical_scene = artifact_for_v2(
                root,
                root / "analysis/scene_spec.json",
                artifact_id=f"canonical-scene-{plan.session_id}",
                kind="canonical_scene_spec",
            )
            canonical_blend = artifact_for_v2(
                root,
                root / "blender/scene.blend",
                artifact_id=f"canonical-blend-{plan.session_id}",
                kind="canonical_blend",
            )
            canonical_snapshot_artifact = artifact_for_v2(
                root,
                canonical_snapshot_path,
                artifact_id=f"{bundle.result.execution_id}-canonical-geometry",
                kind="geometry_stage_snapshot_v02",
            )
            survival_artifact = artifact_for_v2(
                root,
                survival_path,
                artifact_id=survival.report_id,
                kind="geometry_intent_survival_report",
            )
            archives = [item.archive for item in baselines if item.archive is not None]
            provenance = [
                plan.root_authorization,
                bundle.result_artifact,
                bundle.request_artifact,
                bundle.profile_artifact,
                bundle.completion_artifact,
                bundle.modeling_artifact,
                bundle.scene_v03_artifact,
                compilation.scene_artifact,
                *compilation.recipes,
                *compilation.payloads,
                *compilation.receipts,
                *compilation.blends,
                build.provenance,
                build.blend,
                build.inventory,
                build.validation,
                candidate_snapshot_artifact,
                *archives,
                canonical_modeling,
                canonical_scene,
                canonical_blend,
                canonical_snapshot_artifact,
                survival_artifact,
            ]
            receipt = GeometryCandidateValidationReceiptV2(
                contract_id=f"geometry-validation-{plan.session_id}",
                receipt_id=f"geometry-validation-{plan.session_id}",
                job_id=plan.job_id,
                workflow_id=plan.workflow_id,
                dispatch_id=plan.dispatch_id,
                session_id=plan.session_id,
                input_sha256=bundle.result_artifact.sha256,
                source_fingerprint=stable_json_digest(
                    {
                        "source": source_fingerprint,
                        "candidate": compilation.scene_artifact.sha256,
                        "canonical": canonical_scene.sha256,
                        "survival": survival_artifact.sha256,
                    }
                ),
                producer="codex_blender_modeler.autonomy_v2.candidate_validation_service",
                provenance=provenance,
                created_at=datetime.now(UTC),
                root_authorization=plan.root_authorization,
                controller_result=bundle.result_artifact,
                controller_request=bundle.request_artifact,
                phase_tool_profile=bundle.profile_artifact,
                controller_completion=bundle.completion_artifact,
                candidate_modeling_plan=bundle.modeling_artifact,
                candidate_scene_spec_v03=bundle.scene_v03_artifact,
                compiled_scene_spec=compilation.scene_artifact,
                structural_recipes=list(compilation.recipes),
                mesh_payloads_v02=list(compilation.payloads),
                materialization_receipts=list(compilation.receipts),
                materialization_blends=list(compilation.blends),
                candidate_build_provenance=build.provenance,
                candidate_blend=build.blend,
                candidate_inventory=build.inventory,
                candidate_validation=build.validation,
                candidate_geometry_snapshot=candidate_snapshot_artifact,
                previous_modeling_plan_sha256=baselines[0].previous_sha256,
                previous_scene_spec_sha256=baselines[1].previous_sha256,
                previous_blend_sha256=baselines[2].previous_sha256,
                canonical_archives=archives,
                canonical_modeling_plan=canonical_modeling,
                canonical_scene_spec=canonical_scene,
                canonical_blend=canonical_blend,
                canonical_geometry_snapshot=canonical_snapshot_artifact,
                geometry_intent_survival=survival_artifact,
                target_subject=authorization.target_subject,
                budget_usage_after=usage,
            )
            receipt_artifact = write_immutable_v2_model(
                root,
                receipt_path,
                receipt,
            ).model_copy(update={"kind": "geometry_candidate_validation_receipt"})
            if policy_required:
                if policy_authorization_path is None:  # pragma: no cover - guarded above.
                    raise RuntimeError("required geometry policy authorization disappeared")
                from .approval_policy_service import publish_policy_decision_receipt

                publish_policy_decision_receipt(
                    plan.job_id,
                    plan.session_id,
                    policy_authorization_path=policy_authorization_path,
                    canonical_snapshot_after_path=canonical_scene.path,
                    canonical_snapshot_after_kind="canonical-scene-snapshot",
                    outcome="applied",
                    action_result_path=receipt_artifact.path,
                    action_result_kind=receipt_artifact.kind,
                    allow_disabled_experimental=True,
                )
        except Exception:
            for staging in staged:
                if os.path.isfile(native_io_path(staging)):
                    os.unlink(native_io_path(staging))
            _rollback_canonical_files(root, baselines)
            raise
    return receipt, receipt_artifact
