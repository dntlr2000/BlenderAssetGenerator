"""Host-owned AQ v2 material candidate validation, compilation, and promotion."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest, write_json_atomic
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..material_graph import MaterialGraphSpec
from ..material_graph.compiler_service import (
    MaterialGraphCompileBundle,
    MaterialGraphCompileError,
    MaterialGraphCompilerService,
)
from ..material_graph.models import ImageMask, SemanticObjectMask
from ..material_graph.runtime_models import MaterialGraphCompileReport
from ..materials.io import load_shader_recipe, resolve_job_path
from ..materials.models import MaterialPlan, MaterialValidationReport
from ..materials.validation import validate_material_contracts
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
    validate_scene_content_scope,
)
from ..texturing.manifest import load_material_manifest
from ..workspace import canonical_scene_spec_write_lock
from .delivery_service import (
    artifact_for_v2,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .material_phase_models import (
    MaterialControllerCompletionV2,
    MaterialPhaseReceiptV2,
    MaterialPhaseRollbackReceiptV2,
    MaterialPromotionIntentV2,
)
from .models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyStateV2,
    BudgetUsageV2,
    RootAuthorizationV2,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

_PRODUCER = "codex_blender_modeler.autonomy_v2.material_phase_service"
_MATERIAL_OUTPUT_NAMES = frozenset(
    {"material_plan.json", "material_graph.json", "completion.json"}
)


class MaterialPhaseError(RuntimeError):
    """Signal stale, invalid, incomplete, or rolled-back AQ v2 material evidence."""


@dataclass(frozen=True)
class _ControllerMaterialBundle:
    """Hold revalidated controller contracts and the three exact material outputs."""

    result: ControllerResult
    request: ControllerExecutionRequest
    profile: PhaseToolProfile
    result_artifact: AQV2Artifact
    completion: MaterialControllerCompletionV2
    completion_artifact: AQV2Artifact
    material_plan: MaterialPlan
    material_plan_artifact: AQV2Artifact
    material_graph: MaterialGraphSpec
    material_graph_artifact: AQV2Artifact


@dataclass(frozen=True)
class _RebuildSnapshots:
    """Hold immutable execution-time copies of canonical Blender build evidence."""

    material_plan: AQV2Artifact | None
    scene_spec: AQV2Artifact
    blend: AQV2Artifact
    inventory: AQV2Artifact
    validation: AQV2Artifact
    build_provenance: AQV2Artifact
    build_fingerprint: str


def _reserve_material_budget(
    usage: BudgetUsageV2,
    budget: AutonomyBudgetV2,
) -> BudgetUsageV2:
    """Reserve one material round, two Blender runs, and one canonical promotion."""

    updated = usage.model_copy(
        update={
            "material_rounds": usage.material_rounds + 1,
            "total_blender_builds": usage.total_blender_builds + 2,
            "canonical_promotions": usage.canonical_promotions + 1,
            "total_actions": usage.total_actions + 1,
        }
    )
    limits = {
        "material_rounds": budget.material_rounds,
        "total_blender_builds": budget.total_blender_builds,
        "canonical_promotions": budget.canonical_promotions,
        "total_actions": budget.global_action_limit,
    }
    for field, limit in limits.items():
        if getattr(updated, field) > limit:
            raise PermissionError(f"AQ v2 {field} budget is exhausted")
    return updated


def _read_exact_model(
    root: Path,
    artifact: AQV2Artifact,
    model: type[ModelT],
) -> ModelT:
    """Rehash and strict-parse one exact AQ v2 material-phase artifact."""

    path = validate_v2_artifact(root, artifact)
    try:
        return model.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise MaterialPhaseError(f"invalid {model.__name__} material evidence") from exc


def _controller_to_aq(
    root: Path,
    artifact: ControllerArtifact,
    *,
    kind: str,
) -> AQV2Artifact:
    """Rebind and compare one nested ControllerArtifact through central containment."""

    rebound = artifact_for_v2(
        root,
        root / artifact.path,
        artifact_id=artifact.artifact_id,
        kind=kind,
    )
    if (
        rebound.path != artifact.path
        or rebound.sha256 != artifact.sha256
        or rebound.byte_size != artifact.byte_size
    ):
        raise MaterialPhaseError(
            f"controller nested artifact changed: {artifact.path}"
        )
    return rebound


def _phase_profile_artifact(
    root: Path,
    plan: AutonomyPlanV2,
) -> tuple[PhaseToolProfile, AQV2Artifact]:
    """Select exactly one plan-bound material_authoring phase profile."""

    matches: list[tuple[PhaseToolProfile, AQV2Artifact]] = []
    for artifact in plan.phase_tool_profiles:
        profile = _read_exact_model(root, artifact, PhaseToolProfile)
        if profile.profile_id == "material_authoring":
            matches.append((profile, artifact))
    if len(matches) != 1:
        raise MaterialPhaseError(
            "AQ v2 plan must bind exactly one material_authoring profile"
        )
    return matches[0]


def _validate_controller_identity(
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    result: ControllerResult,
    request: ControllerExecutionRequest,
    profile: PhaseToolProfile,
) -> None:
    """Require every controller envelope to match the current AQ session identity."""

    identity = (plan.job_id, plan.workflow_id, plan.dispatch_id, plan.session_id)
    for label, evidence in (
        ("state", state),
        ("controller result", result),
        ("controller request", request),
        ("phase profile", profile),
    ):
        observed = (
            evidence.job_id,
            evidence.workflow_id,
            evidence.dispatch_id,
            evidence.session_id,
        )
        if observed != identity:
            raise MaterialPhaseError(f"{label} identity differs from the AQ v2 plan")
    if result.status != "completed":
        raise MaterialPhaseError("material phase requires a completed controller result")
    if result.execution_id != request.execution_id:
        raise MaterialPhaseError("controller result and request execution IDs differ")
    if result.producer != "codex_blender_modeler.production.controller_executor.service":
        raise MaterialPhaseError("material phase requires a host-validated controller result")
    if state.phase != "authoring" or state.next_action != "validate_candidate":
        raise MaterialPhaseError("AQ v2 state is not at the candidate validation boundary")


def _request_input_map(
    root: Path,
    request: ControllerExecutionRequest,
) -> dict[str, str]:
    """Rehash every immutable request input and return its exact path-to-hash map."""

    records: dict[str, str] = {}
    for artifact in request.immutable_inputs:
        _controller_to_aq(root, artifact, kind=artifact.role)
        if artifact.path in records:
            raise MaterialPhaseError("controller immutable input paths are duplicated")
        records[artifact.path] = artifact.sha256
    _controller_to_aq(root, request.assignment, kind="controller-assignment")
    return records


def _load_controller_material_bundle(
    root: Path,
    plan: AutonomyPlanV2,
    state: AutonomyStateV2,
    result_artifact: AQV2Artifact,
) -> _ControllerMaterialBundle:
    """Validate result, request, profile, inventory, completion, plan, and graph bytes."""

    if not state.provenance or state.provenance[-1] != result_artifact:
        raise MaterialPhaseError(
            "material controller result is not the current state evidence"
        )
    result = _read_exact_model(root, result_artifact, ControllerResult)
    request_artifact = _controller_to_aq(
        root,
        result.request,
        kind="controller-request",
    )
    request = _read_exact_model(root, request_artifact, ControllerExecutionRequest)
    bound_profile, bound_profile_artifact = _phase_profile_artifact(root, plan)
    result_profile_artifact = _controller_to_aq(
        root,
        result.tool_profile,
        kind="phase-tool-profile",
    )
    if (
        result.tool_profile.path != request.tool_profile.path
        or result.tool_profile.sha256 != request.tool_profile.sha256
        or result.tool_profile.byte_size != request.tool_profile.byte_size
        or result_profile_artifact.path != bound_profile_artifact.path
        or result_profile_artifact.sha256 != bound_profile_artifact.sha256
        or result_profile_artifact.byte_size != bound_profile_artifact.byte_size
    ):
        raise MaterialPhaseError("controller result is not bound to the plan material profile")
    profile = _read_exact_model(root, result_profile_artifact, PhaseToolProfile)
    if profile != bound_profile or profile.profile_id != "material_authoring":
        raise MaterialPhaseError("controller used an unexpected phase tool profile")
    _validate_controller_identity(plan, state, result, request, profile)
    if request.tool_profile.sha256 != result.tool_profile.sha256:
        raise MaterialPhaseError("controller request and result use different profiles")
    if request.allowed_output_paths != profile.allowed_output_paths:
        raise MaterialPhaseError("controller request broadened material output paths")
    expected_paths = set(profile.allowed_output_paths)
    if len(expected_paths) != 3 or {
        Path(path).name for path in expected_paths
    } != _MATERIAL_OUTPUT_NAMES:
        raise MaterialPhaseError("material phase profile must declare exactly three outputs")
    if result.extra_output_count or result.partial_output_count:
        raise MaterialPhaseError("material controller result is partial or has extra outputs")
    output_by_path: dict[str, AQV2Artifact] = {}
    for output in result.outputs:
        if output.path in output_by_path:
            raise MaterialPhaseError("material controller output paths are duplicated")
        output_by_path[output.path] = _controller_to_aq(
            root,
            output,
            kind="material-controller-output",
        )
    if set(output_by_path) != expected_paths:
        raise MaterialPhaseError("material controller output inventory is incomplete")
    provenance_roles: dict[str, list[ControllerArtifact]] = {}
    for nested in result.provenance:
        _controller_to_aq(root, nested, kind=nested.role)
        provenance_roles.setdefault(nested.role, []).append(nested)
    for required_role in (
        "controller_started_receipt",
        "controller_completed_receipt",
        "controller_published_receipt",
    ):
        if len(provenance_roles.get(required_role, [])) != 1:
            raise MaterialPhaseError(
                f"controller result lacks one exact {required_role}"
            )
    provenance_outputs = {
        (item.path, item.sha256, item.byte_size)
        for item in provenance_roles.get("controller_output", [])
    }
    expected_outputs = {
        (item.path, item.sha256, item.byte_size) for item in result.outputs
    }
    if provenance_outputs != expected_outputs:
        raise MaterialPhaseError("controller result provenance omits exact outputs")
    declared_root = PurePosixPath(request.output_root)
    inventory_payload = [
        {
            "path": relative,
            "workspace_path": (
                PurePosixPath("outputs")
                / PurePosixPath(relative).relative_to(declared_root)
            ).as_posix(),
            "sha256": output_by_path[relative].sha256,
            "byte_size": output_by_path[relative].byte_size,
        }
        for relative in sorted(
            expected_paths,
            key=lambda item: (
                PurePosixPath("outputs")
                / PurePosixPath(item).relative_to(declared_root)
            ).as_posix(),
        )
    ]
    if stable_json_digest(inventory_payload) != result.output_inventory_sha256:
        raise MaterialPhaseError("controller output inventory digest is inconsistent")
    for relative, expected_sha in request.expected_output_sha256.items():
        if output_by_path[relative].sha256 != expected_sha:
            raise MaterialPhaseError("controller output differs from its request-bound hash")
    input_map = _request_input_map(root, request)
    completion_path = next(
        path for path in expected_paths if path.endswith("/completion.json")
    )
    plan_path = next(
        path for path in expected_paths if path.endswith("/material_plan.json")
    )
    graph_path = next(
        path for path in expected_paths if path.endswith("/material_graph.json")
    )
    completion_artifact = output_by_path[completion_path]
    material_plan_artifact = output_by_path[plan_path]
    material_graph_artifact = output_by_path[graph_path]
    completion = _read_exact_model(
        root,
        completion_artifact,
        MaterialControllerCompletionV2,
    )
    if (
        completion.job_id != plan.job_id
        or completion.workflow_id != plan.workflow_id
        or completion.dispatch_id != plan.dispatch_id
        or completion.session_id != plan.session_id
        or completion.execution_id != request.execution_id
        or completion.assignment_sha256 != request.assignment.sha256
        or completion.tool_profile_sha256 != request.tool_profile.sha256
        or completion.immutable_input_sha256 != input_map
        or completion.material_plan_path != plan_path
        or completion.material_plan_sha256 != material_plan_artifact.sha256
        or completion.material_graph_path != graph_path
        or completion.material_graph_sha256 != material_graph_artifact.sha256
    ):
        raise MaterialPhaseError("material controller completion binding is inconsistent")
    material_plan = _read_exact_model(root, material_plan_artifact, MaterialPlan)
    material_graph = _read_exact_model(root, material_graph_artifact, MaterialGraphSpec)
    return _ControllerMaterialBundle(
        result=result,
        request=request,
        profile=profile,
        result_artifact=result_artifact,
        completion=completion,
        completion_artifact=completion_artifact,
        material_plan=material_plan,
        material_plan_artifact=material_plan_artifact,
        material_graph=material_graph,
        material_graph_artifact=material_graph_artifact,
    )


def _load_root_authorization(
    root: Path,
    plan: AutonomyPlanV2,
) -> RootAuthorizationV2:
    """Revalidate the exact active root authorization for material promotion scope."""

    authorization = _read_exact_model(root, plan.root_authorization, RootAuthorizationV2)
    if (
        authorization.job_id != plan.job_id
        or authorization.workflow_id != plan.workflow_id
        or authorization.dispatch_id != plan.dispatch_id
        or authorization.session_id != plan.session_id
        or authorization.status != "active"
        or authorization.reference_content_scope != "primary_object_only"
    ):
        raise MaterialPhaseError("material phase root authorization is inactive or mismatched")
    if (
        authorization.profile != plan.profile
        or authorization.budget != plan.budget
        or authorization.phase_tool_profiles != plan.phase_tool_profiles
        or authorization.requested_delivery_profiles
        != plan.requested_delivery_profiles
    ):
        raise MaterialPhaseError(
            "material phase plan exceeds its exact root authorization bindings"
        )
    if (
        authorization.expires_at is not None
        and authorization.expires_at <= datetime.now(UTC)
    ):
        raise MaterialPhaseError("material phase root authorization expired")
    return authorization


def _validate_budget_binding(
    root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
) -> None:
    """Require the supplied budget to equal the exact immutable plan-bound contract."""

    bound = _read_exact_model(root, plan.budget, AutonomyBudgetV2)
    if bound != budget or (
        budget.job_id,
        budget.workflow_id,
        budget.dispatch_id,
        budget.session_id,
    ) != (
        plan.job_id,
        plan.workflow_id,
        plan.dispatch_id,
        plan.session_id,
    ):
        raise MaterialPhaseError("material phase budget differs from its plan binding")


def _canonical_scene_and_scope(
    root: Path,
    plan: AutonomyPlanV2,
) -> tuple[SceneSpec, str]:
    """Load canonical SceneSpec and enforce immutable primary-object-only scope."""

    authorization = _load_root_authorization(root, plan)
    scene_path = ensure_contained_production_path(
        root,
        root / "analysis" / "scene_spec.json",
        must_exist=True,
    )
    try:
        scene = SceneSpec.model_validate_json(scene_path.read_bytes())
        metadata = json.loads((root / "job.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as exc:
        raise MaterialPhaseError("canonical SceneSpec or job scope metadata is invalid") from exc
    scope, target_subject = reference_content_scope_from_metadata(metadata)
    if (
        scope != "primary_object_only"
        or target_subject != authorization.target_subject
    ):
        raise MaterialPhaseError("job content scope differs from the root authorization")
    validate_scene_content_scope(
        scene,
        scope=scope,
        target_subject=target_subject,
    )
    if scene.job_id != plan.job_id:
        raise MaterialPhaseError("canonical SceneSpec belongs to another job")
    return scene, sha256_file(scene_path)


def _require_request_dependency(
    root: Path,
    input_map: dict[str, str],
    path: Path,
    *,
    label: str,
) -> None:
    """Require one candidate dependency to be an exact immutable controller input."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    relative = safe.relative_to(root).as_posix()
    if input_map.get(relative) != sha256_file(safe):
        raise MaterialPhaseError(
            f"{label} is not bound as an exact immutable controller input"
        )


def _validate_material_plan_dependencies(
    root: Path,
    plan: MaterialPlan,
    input_map: dict[str, str],
) -> None:
    """Bind every recipe, texture manifest, and image channel to request inputs."""

    for item in plan.materials:
        manifest_value = item.texture_manifest
        if item.shader_recipe is not None:
            recipe_path = resolve_job_path(root, item.shader_recipe, "shader recipe")
            _require_request_dependency(
                root,
                input_map,
                recipe_path,
                label="material shader recipe",
            )
            recipe = load_shader_recipe(recipe_path)
            manifest_value = manifest_value or recipe.texture_manifest
        if manifest_value is None:
            continue
        manifest, manifest_path = load_material_manifest(
            {"id": item.material_id, "texture_manifest": manifest_value},
            root,
        )
        if manifest is None or manifest_path is None:
            raise MaterialPhaseError("declared material manifest could not be loaded")
        _require_request_dependency(
            root,
            input_map,
            manifest_path,
            label="material texture manifest",
        )
        for channel in manifest["channels"].values():
            resolved = channel.get("resolved_path")
            if resolved is not None:
                _require_request_dependency(
                    root,
                    input_map,
                    Path(str(resolved)),
                    label="material texture channel",
                )


def _graph_artifacts(graph: MaterialGraphSpec) -> list[Any]:
    """Collect every declared graph dependency, including channel and mask bindings."""

    artifacts = list(graph.provenance.inputs)
    for channel in graph.base_channels:
        if channel.image is not None:
            artifacts.append(channel.image)
    for layer in graph.layers:
        for channel in layer.channels:
            if channel.image is not None:
                artifacts.append(channel.image)
        if isinstance(layer.mask, ImageMask):
            artifacts.append(layer.mask.image)
    artifacts.append(graph.preview_lighting.reference_source)
    return artifacts


def _validate_graph_binding(
    root: Path,
    bundle: _ControllerMaterialBundle,
    scene: SceneSpec,
    scene_sha256: str,
) -> None:
    """Bind MaterialGraphSpec identity, material, scope, and dependencies exactly."""

    graph = bundle.material_graph
    plan = bundle.material_plan
    if (
        graph.provenance.job_id != bundle.result.job_id
        or graph.provenance.workflow_id != bundle.result.workflow_id
        or graph.provenance.dispatch_id != bundle.result.dispatch_id
        or graph.provenance.project_version != "0.9.0"
    ):
        raise MaterialPhaseError("MaterialGraphSpec identity differs from the AQ session")
    scene_material_ids = {item.id for item in scene.materials}
    plan_material_ids = {item.material_id for item in plan.materials}
    if plan_material_ids != scene_material_ids:
        raise MaterialPhaseError(
            "authored MaterialPlan IDs must exactly equal canonical SceneSpec materials"
        )
    if graph.material_id not in scene_material_ids:
        raise MaterialPhaseError("MaterialGraphSpec targets an unknown material ID")
    input_map = _request_input_map(root, bundle.request)
    material_inputs = [
        item for item in graph.provenance.inputs if item.role == "material_plan"
    ]
    scene_inputs = [
        item for item in graph.provenance.inputs if item.role == "scene_spec"
    ]
    if len(material_inputs) != 1 or (
        material_inputs[0].path != bundle.material_plan_artifact.path
        or material_inputs[0].sha256 != bundle.material_plan_artifact.sha256
    ):
        raise MaterialPhaseError(
            "MaterialGraphSpec must bind the exact controller MaterialPlan output"
        )
    if len(scene_inputs) != 1 or (
        scene_inputs[0].path != "analysis/scene_spec.json"
        or scene_inputs[0].sha256 != scene_sha256
    ):
        raise MaterialPhaseError(
            "MaterialGraphSpec must bind the exact canonical SceneSpec input"
        )
    for artifact in _graph_artifacts(graph):
        if (
            artifact.path == bundle.material_plan_artifact.path
            and artifact.sha256 == bundle.material_plan_artifact.sha256
        ):
            continue
        if input_map.get(artifact.path) != artifact.sha256:
            raise MaterialPhaseError(
                f"MaterialGraphSpec dependency is outside immutable inputs: {artifact.path}"
            )
        _require_request_dependency(
            root,
            input_map,
            root / artifact.path,
            label="MaterialGraphSpec dependency",
        )
    object_ids = {item.id for item in scene.objects}
    for layer in graph.layers:
        if isinstance(layer.mask, SemanticObjectMask):
            targets = {*layer.mask.semantic_ids, *layer.mask.object_ids}
            unknown = sorted(targets - object_ids)
            if unknown:
                raise MaterialPhaseError(
                    f"MaterialGraphSpec mask targets unknown object IDs: {unknown}"
                )


def _relative_material_validation(
    root: Path,
    report: MaterialValidationReport,
) -> MaterialValidationReport:
    """Remove absolute host paths from a persisted material validation report."""

    checks = []
    for check in report.checks:
        value = check.path
        if value is not None:
            candidate = Path(value)
            if candidate.is_absolute():
                try:
                    value = candidate.resolve().relative_to(root.resolve()).as_posix()
                except ValueError:
                    value = None
        checks.append(check.model_copy(update={"path": value}))
    return report.model_copy(update={"checks": checks})


def _write_or_adopt_model(
    root: Path,
    path: Path,
    model: ModelT,
) -> tuple[ModelT, AQV2Artifact]:
    """Publish one deterministic model once or adopt only semantically identical bytes."""

    if path.exists():
        existing = type(model).model_validate_json(path.read_bytes())
        if existing != model:
            raise MaterialPhaseError(f"existing material evidence differs: {path.name}")
        artifact = artifact_for_v2(
            root,
            path,
            artifact_id=str(getattr(existing, "contract_id", path.stem)),
            kind=path.stem.replace("_", "-"),
        )
        return existing, artifact
    artifact = write_immutable_v2_model(root, path, model)
    return model, artifact


def _snapshot_exact(
    root: Path,
    source: Path,
    destination: Path,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Copy one exact contained file once and reject a conflicting prior snapshot."""

    safe_source = ensure_contained_production_path(root, source, must_exist=True)
    safe_destination = ensure_contained_production_path(
        root,
        destination,
        must_exist=False,
    )
    expected_sha = sha256_file(safe_source)
    expected_size = os.path.getsize(native_io_path(safe_source))
    if safe_destination.exists():
        artifact = artifact_for_v2(
            root,
            safe_destination,
            artifact_id=artifact_id,
            kind=kind,
        )
        if artifact.sha256 != expected_sha or artifact.byte_size != expected_size:
            raise MaterialPhaseError(
                f"existing material snapshot differs: {safe_destination.name}"
            )
        return artifact
    safe_destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe_destination.parent / f".{safe_destination.name}.{uuid4().hex}.tmp"
    shutil.copy2(safe_source, temporary)
    try:
        if (
            sha256_file(temporary) != expected_sha
            or os.path.getsize(native_io_path(temporary)) != expected_size
        ):
            raise MaterialPhaseError("material snapshot copy hash mismatch")
        os.replace(native_io_path(temporary), native_io_path(safe_destination))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return artifact_for_v2(
        root,
        safe_destination,
        artifact_id=artifact_id,
        kind=kind,
    )


def _archive_material_plan(
    root: Path,
    plan: AutonomyPlanV2,
    canonical_path: Path,
) -> AQV2Artifact | None:
    """Archive the exact previous canonical MaterialPlan before replacement."""

    if not canonical_path.is_file():
        return None
    digest = sha256_file(canonical_path)
    destination = (
        root
        / "history"
        / "materials"
        / f"aqv2_{plan.session_id}_{digest[:16]}.json"
    )
    return _snapshot_exact(
        root,
        canonical_path,
        destination,
        artifact_id=f"material-archive-{digest[:16]}",
        kind="archived_material_plan",
    )


def _replace_material_plan_if_current(
    root: Path,
    candidate_path: Path,
    *,
    expected_current_sha256: str | None,
    expected_candidate_sha256: str,
) -> None:
    """Atomically replace canonical MaterialPlan only over the expected exact baseline."""

    canonical = ensure_contained_production_path(
        root,
        root / "analysis" / "material_plan.json",
        must_exist=False,
    )
    candidate = ensure_contained_production_path(
        root,
        candidate_path,
        must_exist=True,
    )
    if sha256_file(candidate) != expected_candidate_sha256:
        raise MaterialPhaseError("material candidate changed before promotion")
    if expected_current_sha256 is None:
        if canonical.exists():
            raise MaterialPhaseError("canonical MaterialPlan appeared before promotion")
    elif not canonical.is_file() or sha256_file(canonical) != expected_current_sha256:
        raise MaterialPhaseError("canonical MaterialPlan changed before promotion")
    canonical.parent.mkdir(parents=True, exist_ok=True)
    temporary = canonical.parent / f".material_plan.{uuid4().hex}.tmp"
    shutil.copy2(candidate, temporary)
    try:
        if sha256_file(temporary) != expected_candidate_sha256:
            raise MaterialPhaseError("material promotion staging hash mismatch")
        if expected_current_sha256 is None:
            if canonical.exists():
                raise MaterialPhaseError(
                    "canonical MaterialPlan appeared immediately before promotion"
                )
        elif not canonical.is_file() or sha256_file(canonical) != expected_current_sha256:
            raise MaterialPhaseError(
                "canonical MaterialPlan changed immediately before promotion"
            )
        os.replace(native_io_path(temporary), native_io_path(canonical))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if sha256_file(canonical) != expected_candidate_sha256:
        raise MaterialPhaseError("canonical MaterialPlan differs from promoted candidate")


def _canonical_material_matches_candidate(
    root: Path,
    *,
    candidate_sha256: str,
) -> bool:
    """Detect an atomic candidate replacement even if the writer raised afterward."""

    canonical = ensure_contained_production_path(
        root,
        root / "analysis" / "material_plan.json",
        must_exist=False,
    )
    return canonical.is_file() and sha256_file(canonical) == candidate_sha256


def _restore_material_plan(
    root: Path,
    previous: AQV2Artifact | None,
    *,
    expected_candidate_sha256: str,
) -> None:
    """Restore the exact prior MaterialPlan or exact prior absence after host failure."""

    canonical = ensure_contained_production_path(
        root,
        root / "analysis" / "material_plan.json",
        must_exist=False,
    )
    if not canonical.is_file() or sha256_file(canonical) != expected_candidate_sha256:
        raise MaterialPhaseError("cannot rollback a changed canonical MaterialPlan")
    if previous is None:
        canonical.unlink()
        if canonical.exists():
            raise MaterialPhaseError("canonical MaterialPlan absence rollback failed")
        return
    source = validate_v2_artifact(root, previous)
    temporary = canonical.parent / f".material_rollback.{uuid4().hex}.tmp"
    shutil.copy2(source, temporary)
    try:
        if sha256_file(temporary) != previous.sha256:
            raise MaterialPhaseError("material rollback staging hash mismatch")
        os.replace(native_io_path(temporary), native_io_path(canonical))
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    if sha256_file(canonical) != previous.sha256:
        raise MaterialPhaseError("canonical MaterialPlan rollback hash mismatch")


def _write_build_provenance(path: Path, payload: dict[str, Any]) -> None:
    """Persist one deterministic build provenance snapshot without replacing evidence."""

    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise MaterialPhaseError("existing build provenance snapshot differs")
        return
    write_json_atomic(path, payload)


def _rebuild_and_snapshot(
    root: Path,
    plan: AutonomyPlanV2,
    phase_root: Path,
    *,
    prefix: str,
) -> _RebuildSnapshots:
    """Build, inspect, validate, and snapshot canonical scene evidence under one prefix."""

    scene_spec = root / "analysis" / "scene_spec.json"
    material_plan = root / "analysis" / "material_plan.json"
    blend = root / "blender" / "scene.blend"
    inventory = root / "reports" / "scene_inventory.json"
    validation = root / "reports" / "validation.json"
    run_blender("build_scene.py", ["--spec", str(scene_spec), "--output", str(blend)])
    run_blender("inspect_scene.py", ["--output", str(inventory)], blend_file=blend)
    run_blender(
        "validate_scene.py",
        ["--spec", str(scene_spec), "--output", str(validation)],
        blend_file=blend,
    )
    try:
        validation_payload = json.loads(validation.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterialPhaseError("canonical scene validation report is invalid") from exc
    if not isinstance(validation_payload, dict) or validation_payload.get("ok") is not True:
        raise MaterialPhaseError("canonical scene validation did not report ok=true")
    provenance = collect_build_provenance(root, plan.job_id, scene_spec_path=scene_spec)
    if provenance.get("material_plan_sha256") != (
        sha256_file(material_plan) if material_plan.is_file() else None
    ):
        raise MaterialPhaseError("fresh build provenance has a stale MaterialPlan hash")
    snapshot_root = phase_root / prefix
    snapshot_root.mkdir(parents=True, exist_ok=True)
    provenance_path = snapshot_root / "build_provenance.json"
    _write_build_provenance(provenance_path, provenance)
    material_artifact = (
        _snapshot_exact(
            root,
            material_plan,
            snapshot_root / "material_plan.json",
            artifact_id=f"{prefix}-material-plan",
            kind="canonical_material_plan_snapshot",
        )
        if material_plan.is_file()
        else None
    )
    return _RebuildSnapshots(
        material_plan=material_artifact,
        scene_spec=_snapshot_exact(
            root,
            scene_spec,
            snapshot_root / "scene_spec.json",
            artifact_id=f"{prefix}-scene-spec",
            kind="canonical_scene_spec_snapshot",
        ),
        blend=_snapshot_exact(
            root,
            blend,
            snapshot_root / "scene.blend",
            artifact_id=f"{prefix}-scene-blend",
            kind="authoring_blend_snapshot",
        ),
        inventory=_snapshot_exact(
            root,
            inventory,
            snapshot_root / "scene_inventory.json",
            artifact_id=f"{prefix}-scene-inventory",
            kind="scene_inventory_snapshot",
        ),
        validation=_snapshot_exact(
            root,
            validation,
            snapshot_root / "validation.json",
            artifact_id=f"{prefix}-scene-validation",
            kind="scene_validation_snapshot",
        ),
        build_provenance=artifact_for_v2(
            root,
            provenance_path,
            artifact_id=f"{prefix}-build-provenance",
            kind="build_provenance_snapshot",
        ),
        build_fingerprint=str(provenance["fingerprint"]),
    )


def _compile_or_adopt_graph(
    root: Path,
    phase_root: Path,
    bundle: _ControllerMaterialBundle,
) -> tuple[MaterialGraphCompileBundle, AQV2Artifact]:
    """Compile once or revalidate one exact published whitelist graph bundle."""

    run_id = f"material-{bundle.result.execution_id}"
    run_root = (
        phase_root / "graph_compile"
    ).relative_to(root).as_posix()
    compiler = MaterialGraphCompilerService(root)
    try:
        if (root / run_root).exists():
            compiled = compiler.validate_compile_run(run_root=run_root)
        else:
            compiled = compiler.compile_run(
                graph_spec_path=bundle.material_graph_artifact.path,
                run_root=run_root,
                run_id=run_id,
            )
    except MaterialGraphCompileError as exc:
        raise MaterialPhaseError("MaterialGraphSpec whitelist compilation failed") from exc
    report = compiled.report
    if (
        report.job_id != bundle.result.job_id
        or report.workflow_id != bundle.result.workflow_id
        or report.dispatch_id != bundle.result.dispatch_id
        or report.graph_id != bundle.material_graph.graph_id
        or report.material_id != bundle.material_graph.material_id
    ):
        raise MaterialPhaseError("material graph compile report identity is inconsistent")
    report_artifact = artifact_for_v2(
        root,
        root / run_root / "compile_report.json",
        artifact_id=report.report_id,
        kind="material_graph_compile_report",
    )
    return compiled, report_artifact


def _material_validation_artifact(
    root: Path,
    phase_root: Path,
    bundle: _ControllerMaterialBundle,
    scene: SceneSpec,
) -> AQV2Artifact:
    """Publish or adopt one strict, privacy-safe V0.5 contract validation report."""

    report = _relative_material_validation(
        root,
        validate_material_contracts(
            bundle.material_plan,
            scene.model_dump(mode="json"),
            root,
        ),
    )
    if not report.ok:
        raise MaterialPhaseError("authored MaterialPlan failed strict V0.5 validation")
    _report, artifact = _write_or_adopt_model(
        root,
        phase_root / "material_validation.json",
        report,
    )
    return artifact


def _load_promotion_intent(
    root: Path,
    intent_path: Path,
) -> tuple[MaterialPromotionIntentV2, AQV2Artifact] | None:
    """Load and recursively validate one interrupted material promotion intent."""

    if not intent_path.exists():
        return None
    artifact = artifact_for_v2(
        root,
        intent_path,
        artifact_id=intent_path.stem,
        kind="material_promotion_intent",
    )
    intent = _read_exact_model(root, artifact, MaterialPromotionIntentV2)
    for nested in intent.provenance:
        validate_v2_artifact(root, nested)
    return intent, artifact.model_copy(update={"artifact_id": intent.contract_id})


def _publish_or_adopt_intent(
    root: Path,
    plan: AutonomyPlanV2,
    phase_root: Path,
    bundle: _ControllerMaterialBundle,
    material_validation: AQV2Artifact,
    graph_compile_report: AQV2Artifact,
    scene_snapshot: AQV2Artifact,
    previous_material_plan: AQV2Artifact | None,
) -> tuple[MaterialPromotionIntentV2, AQV2Artifact]:
    """Journal the complete validated candidate before canonical replacement."""

    intent_path = phase_root / "promotion_intent.json"
    existing = _load_promotion_intent(root, intent_path)
    if existing is not None:
        intent, artifact = existing
        if (
            intent.controller_result != bundle.result_artifact
            or intent.controller_completion != bundle.completion_artifact
            or intent.material_plan_candidate != bundle.material_plan_artifact
            or intent.material_graph_spec != bundle.material_graph_artifact
            or intent.material_validation != material_validation
            or intent.graph_compile_report != graph_compile_report
            or intent.source_scene_spec != scene_snapshot
            or intent.previous_material_plan != previous_material_plan
        ):
            raise MaterialPhaseError("existing material promotion intent differs")
        return intent, artifact
    provenance = [
        bundle.result_artifact,
        bundle.completion_artifact,
        bundle.material_plan_artifact,
        bundle.material_graph_artifact,
        material_validation,
        graph_compile_report,
        scene_snapshot,
        *(
            [previous_material_plan]
            if previous_material_plan is not None
            else []
        ),
    ]
    payload = {
        "controller_result": bundle.result_artifact.sha256,
        "material_plan": bundle.material_plan_artifact.sha256,
        "material_graph": bundle.material_graph_artifact.sha256,
        "scene": scene_snapshot.sha256,
        "previous_material": (
            previous_material_plan.sha256
            if previous_material_plan is not None
            else None
        ),
        "compile_report": graph_compile_report.sha256,
    }
    intent = MaterialPromotionIntentV2(
        contract_id=f"material-intent-{bundle.result.execution_id}",
        intent_id=f"material-intent-{bundle.result.execution_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(payload),
        source_fingerprint=stable_json_digest({**payload, "stage": "validated"}),
        producer=_PRODUCER,
        provenance=provenance,
        created_at=datetime.now(UTC),
        controller_result=bundle.result_artifact,
        controller_completion=bundle.completion_artifact,
        material_plan_candidate=bundle.material_plan_artifact,
        material_graph_spec=bundle.material_graph_artifact,
        material_validation=material_validation,
        graph_compile_report=graph_compile_report,
        source_scene_spec=scene_snapshot,
        previous_material_plan=previous_material_plan,
        expected_canonical_material_sha256=(
            previous_material_plan.sha256
            if previous_material_plan is not None
            else None
        ),
        candidate_material_sha256=bundle.material_plan_artifact.sha256,
    )
    artifact = write_immutable_v2_model(root, intent_path, intent)
    return intent, artifact


def _safe_failure_reason(root: Path, exc: Exception) -> str:
    """Remove the absolute job path from one bounded rollback diagnostic."""

    message = str(exc).replace(str(root), "<job-root>")
    message = message.replace(str(Path(native_io_path(root))), "<job-root>")
    return f"{type(exc).__name__}: {message}"[:1024]


def _publish_rollback_receipt(
    root: Path,
    plan: AutonomyPlanV2,
    phase_root: Path,
    bundle: _ControllerMaterialBundle,
    intent: MaterialPromotionIntentV2,
    intent_artifact: AQV2Artifact,
    failure: Exception,
    *,
    snapshots: _RebuildSnapshots | None,
    rollback_error: Exception | None,
) -> AQV2Artifact:
    """Publish one immutable rollback or rollback-failed receipt after restoration."""

    path = phase_root / "rollback_receipt.json"
    if path.exists():
        raise MaterialPhaseError("material rollback receipt already exists")
    previous = intent.previous_material_plan
    restored_material = snapshots.material_plan if snapshots is not None else None
    restored = (
        [
            snapshots.blend,
            snapshots.inventory,
            snapshots.validation,
            snapshots.build_provenance,
        ]
        if snapshots is not None
        else []
    )
    provenance = [
        intent_artifact,
        bundle.result_artifact,
        bundle.material_plan_artifact,
        *([previous] if previous is not None else []),
        *([restored_material] if restored_material is not None else []),
        *restored,
    ]
    reason = _safe_failure_reason(root, failure)
    if rollback_error is not None:
        reason = f"{reason}; rollback={_safe_failure_reason(root, rollback_error)}"[:1024]
    payload = {
        "intent": intent_artifact.sha256,
        "candidate": bundle.material_plan_artifact.sha256,
        "status": "rolled_back" if rollback_error is None else "rollback_failed",
        "reason": reason,
    }
    receipt = MaterialPhaseRollbackReceiptV2(
        contract_id=f"material-rollback-{bundle.result.execution_id}",
        receipt_id=f"material-rollback-{bundle.result.execution_id}",
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=stable_json_digest(payload),
        source_fingerprint=stable_json_digest({**payload, "canonical": "restored"}),
        producer=_PRODUCER,
        provenance=provenance,
        created_at=datetime.now(UTC),
        status="rolled_back" if rollback_error is None else "rollback_failed",
        promotion_intent=intent_artifact,
        controller_result=bundle.result_artifact,
        material_plan_candidate=bundle.material_plan_artifact,
        previous_material_plan=previous,
        restored_material_snapshot=restored_material,
        restored_blend_snapshot=(snapshots.blend if snapshots is not None else None),
        restored_inventory_snapshot=(
            snapshots.inventory if snapshots is not None else None
        ),
        restored_validation_snapshot=(
            snapshots.validation if snapshots is not None else None
        ),
        restored_build_provenance_snapshot=(
            snapshots.build_provenance if snapshots is not None else None
        ),
        failure_type=type(failure).__name__,
        reason=reason,
    )
    return write_immutable_v2_model(root, path, receipt)


def _validate_material_phase_receipt_payload(
    root: Path,
    receipt: MaterialPhaseReceiptV2,
    *,
    require_current: bool = False,
) -> MaterialPhaseReceiptV2:
    """Revalidate one parsed material receipt chain and optional canonical state."""

    for nested in receipt.provenance:
        validate_v2_artifact(root, nested)
    intent = _read_exact_model(root, receipt.promotion_intent, MaterialPromotionIntentV2)
    compile_report = _read_exact_model(
        root,
        receipt.graph_compile_report,
        MaterialGraphCompileReport,
    )
    if (
        intent.controller_result != receipt.controller_result
        or intent.material_plan_candidate != receipt.material_plan_candidate
        or intent.material_graph_spec != receipt.material_graph_spec
        or intent.material_validation != receipt.material_validation
        or intent.graph_compile_report != receipt.graph_compile_report
        or receipt.canonical_material_plan_sha256
        != receipt.material_plan_candidate.sha256
        or compile_report.status != "passed"
        or compile_report.ok is not True
    ):
        raise MaterialPhaseError("material phase receipt chain is inconsistent")
    provenance_payload = json.loads(
        validate_v2_artifact(root, receipt.build_provenance_snapshot).read_text(
            encoding="utf-8"
        )
    )
    if provenance_payload.get("fingerprint") != receipt.build_fingerprint:
        raise MaterialPhaseError("material phase build fingerprint is inconsistent")
    if require_current:
        canonical_material = root / "analysis" / "material_plan.json"
        canonical_scene = root / "analysis" / "scene_spec.json"
        if (
            not canonical_material.is_file()
            or sha256_file(canonical_material)
            != receipt.canonical_material_plan_sha256
            or not canonical_scene.is_file()
            or sha256_file(canonical_scene) != receipt.canonical_scene_spec_sha256
        ):
            raise MaterialPhaseError("canonical source changed after material promotion")
        current = collect_build_provenance(root, receipt.job_id)
        if current.get("fingerprint") != receipt.build_fingerprint:
            raise MaterialPhaseError("canonical build provenance changed after promotion")
    return receipt


def validate_material_phase_receipt_v2(
    root: Path,
    artifact: AQV2Artifact,
    *,
    require_current: bool = False,
) -> MaterialPhaseReceiptV2:
    """Recursively revalidate one successful material receipt and optional current state."""

    receipt = _read_exact_model(root, artifact, MaterialPhaseReceiptV2)
    return _validate_material_phase_receipt_payload(
        root,
        receipt,
        require_current=require_current,
    )


def validate_and_promote_material_controller_result_v2(
    root: Path,
    plan: AutonomyPlanV2,
    budget: AutonomyBudgetV2,
    state: AutonomyStateV2,
    result_artifact: AQV2Artifact,
) -> tuple[MaterialPhaseReceiptV2, AQV2Artifact]:
    """Compile and promote one exact material controller result under host authority."""

    job_root = ensure_contained_production_path(root, root, must_exist=True)
    _validate_budget_binding(job_root, plan, budget)
    phase_root = ensure_contained_production_path(
        job_root,
        job_root
        / "production"
        / "autonomy_v2"
        / plan.session_id
        / "material_phase"
        / f"{state.sequence:04d}",
        must_exist=False,
    )
    receipt_path = phase_root / "promotion_receipt.json"
    rollback_path = phase_root / "rollback_receipt.json"
    if receipt_path.exists():
        artifact = artifact_for_v2(
            job_root,
            receipt_path,
            artifact_id=receipt_path.stem,
            kind="material_phase_receipt",
        )
        receipt = validate_material_phase_receipt_v2(
            job_root,
            artifact,
            require_current=True,
        )
        if receipt.controller_result != result_artifact:
            raise MaterialPhaseError("existing material receipt targets another result")
        if receipt.budget_usage_after != _reserve_material_budget(
            state.budget_usage,
            budget,
        ):
            raise MaterialPhaseError("existing material receipt budget usage is stale")
        return receipt, artifact.model_copy(update={"artifact_id": receipt.contract_id})
    if rollback_path.exists():
        rollback_artifact = artifact_for_v2(
            job_root,
            rollback_path,
            artifact_id=rollback_path.stem,
            kind="material_phase_rollback_receipt",
        )
        rollback = _read_exact_model(
            job_root,
            rollback_artifact,
            MaterialPhaseRollbackReceiptV2,
        )
        raise MaterialPhaseError(
            f"material candidate previously ended with {rollback.status}"
        )
    bundle = _load_controller_material_bundle(
        job_root,
        plan,
        state,
        result_artifact,
    )
    scene, scene_sha = _canonical_scene_and_scope(job_root, plan)
    if (
        bundle.material_plan.job_id != plan.job_id
        or bundle.material_plan.stage != "authored"
        or bundle.material_plan.scene_spec_path != "analysis/scene_spec.json"
    ):
        raise MaterialPhaseError("controller output is not this job's authored MaterialPlan")
    if bundle.completion.source_scene_spec_sha256 != scene_sha:
        raise MaterialPhaseError("material controller source SceneSpec is stale")
    canonical_material = job_root / "analysis" / "material_plan.json"
    current_material_sha = (
        sha256_file(canonical_material) if canonical_material.is_file() else None
    )
    intent_path = phase_root / "promotion_intent.json"
    existing_intent = _load_promotion_intent(job_root, intent_path)
    if existing_intent is None and (
        bundle.completion.source_material_plan_sha256 != current_material_sha
    ):
        raise MaterialPhaseError("material controller baseline MaterialPlan is stale")
    input_map = _request_input_map(job_root, bundle.request)
    _validate_material_plan_dependencies(job_root, bundle.material_plan, input_map)
    _validate_graph_binding(job_root, bundle, scene, scene_sha)
    usage = _reserve_material_budget(state.budget_usage, budget)
    phase_root.mkdir(parents=True, exist_ok=True)
    material_validation = _material_validation_artifact(
        job_root,
        phase_root,
        bundle,
        scene,
    )
    _compiled, compile_report = _compile_or_adopt_graph(
        job_root,
        phase_root,
        bundle,
    )
    with canonical_scene_spec_write_lock(
        plan.job_id,
        plan.session_id,
        ttl_seconds=3600,
    ):
        bundle = _load_controller_material_bundle(
            job_root,
            plan,
            state,
            result_artifact,
        )
        locked_scene, locked_scene_sha = _canonical_scene_and_scope(job_root, plan)
        if locked_scene_sha != scene_sha or locked_scene != scene:
            raise MaterialPhaseError("canonical SceneSpec changed before material promotion")
        _validate_material_plan_dependencies(job_root, bundle.material_plan, input_map)
        _validate_graph_binding(job_root, bundle, locked_scene, locked_scene_sha)
        MaterialGraphCompilerService(job_root).validate_compile_run(
            run_root=(phase_root / "graph_compile").relative_to(job_root).as_posix()
        )
        source_scene_snapshot = _snapshot_exact(
            job_root,
            job_root / "analysis" / "scene_spec.json",
            phase_root / "source_scene_spec.json",
            artifact_id=f"material-source-scene-{bundle.result.execution_id}",
            kind="source_scene_spec_snapshot",
        )
        previous_material = (
            existing_intent[0].previous_material_plan
            if existing_intent is not None
            else _archive_material_plan(job_root, plan, canonical_material)
        )
        intent, intent_artifact = _publish_or_adopt_intent(
            job_root,
            plan,
            phase_root,
            bundle,
            material_validation,
            compile_report,
            source_scene_snapshot,
            previous_material,
        )
        current_material_sha = (
            sha256_file(canonical_material) if canonical_material.is_file() else None
        )
        if current_material_sha not in {
            intent.expected_canonical_material_sha256,
            intent.candidate_material_sha256,
        }:
            raise MaterialPhaseError(
                "canonical MaterialPlan conflicts with the promotion intent"
            )
        wrote_candidate = current_material_sha == intent.candidate_material_sha256
        try:
            if not wrote_candidate:
                _replace_material_plan_if_current(
                    job_root,
                    validate_v2_artifact(job_root, bundle.material_plan_artifact),
                    expected_current_sha256=intent.expected_canonical_material_sha256,
                    expected_candidate_sha256=intent.candidate_material_sha256,
                )
                wrote_candidate = True
            snapshots = _rebuild_and_snapshot(
                job_root,
                plan,
                phase_root,
                prefix="promoted",
            )
            if snapshots.material_plan is None:
                raise MaterialPhaseError("promoted build omitted canonical MaterialPlan")
            if snapshots.scene_spec.sha256 != scene_sha:
                raise MaterialPhaseError("material promotion changed canonical SceneSpec")
            payload = {
                "intent": intent_artifact.sha256,
                "candidate": bundle.material_plan_artifact.sha256,
                "compile_report": compile_report.sha256,
                "build_fingerprint": snapshots.build_fingerprint,
            }
            provenance = [
                intent_artifact,
                bundle.result_artifact,
                bundle.material_plan_artifact,
                bundle.material_graph_artifact,
                material_validation,
                compile_report,
                *(
                    [previous_material]
                    if previous_material is not None
                    else []
                ),
                snapshots.material_plan,
                snapshots.scene_spec,
                snapshots.blend,
                snapshots.inventory,
                snapshots.validation,
                snapshots.build_provenance,
            ]
            receipt = MaterialPhaseReceiptV2(
                contract_id=f"material-receipt-{bundle.result.execution_id}",
                receipt_id=f"material-receipt-{bundle.result.execution_id}",
                job_id=plan.job_id,
                workflow_id=plan.workflow_id,
                dispatch_id=plan.dispatch_id,
                session_id=plan.session_id,
                input_sha256=stable_json_digest(payload),
                source_fingerprint=stable_json_digest(
                    {**payload, "canonical_material": snapshots.material_plan.sha256}
                ),
                producer=_PRODUCER,
                provenance=provenance,
                created_at=datetime.now(UTC),
                promotion_intent=intent_artifact,
                controller_result=bundle.result_artifact,
                material_plan_candidate=bundle.material_plan_artifact,
                material_graph_spec=bundle.material_graph_artifact,
                material_validation=material_validation,
                graph_compile_report=compile_report,
                archived_material_plan=previous_material,
                canonical_material_snapshot=snapshots.material_plan,
                canonical_scene_snapshot=snapshots.scene_spec,
                authoring_blend_snapshot=snapshots.blend,
                scene_inventory_snapshot=snapshots.inventory,
                scene_validation_snapshot=snapshots.validation,
                build_provenance_snapshot=snapshots.build_provenance,
                previous_canonical_material_sha256=(
                    previous_material.sha256
                    if previous_material is not None
                    else None
                ),
                canonical_material_plan_sha256=snapshots.material_plan.sha256,
                canonical_scene_spec_sha256=snapshots.scene_spec.sha256,
                build_fingerprint=snapshots.build_fingerprint,
                budget_usage_after=usage,
            )
            _validate_material_phase_receipt_payload(
                job_root,
                receipt,
                require_current=True,
            )
            receipt_artifact = write_immutable_v2_model(
                job_root,
                receipt_path,
                receipt,
            ).model_copy(update={"kind": "material_phase_receipt"})
            return receipt, receipt_artifact
        except Exception as failure:
            if not wrote_candidate:
                wrote_candidate = _canonical_material_matches_candidate(
                    job_root,
                    candidate_sha256=intent.candidate_material_sha256,
                )
            if not wrote_candidate:
                raise
            rollback_snapshots: _RebuildSnapshots | None = None
            rollback_error: Exception | None = None
            try:
                _restore_material_plan(
                    job_root,
                    previous_material,
                    expected_candidate_sha256=intent.candidate_material_sha256,
                )
                rollback_snapshots = _rebuild_and_snapshot(
                    job_root,
                    plan,
                    phase_root,
                    prefix="rollback",
                )
                if rollback_snapshots.scene_spec.sha256 != scene_sha:
                    raise MaterialPhaseError("material rollback changed canonical SceneSpec")
            except Exception as exc:  # noqa: BLE001 - immutable rollback evidence follows.
                rollback_error = exc
                rollback_snapshots = None
            rollback_artifact = _publish_rollback_receipt(
                job_root,
                plan,
                phase_root,
                bundle,
                intent,
                intent_artifact,
                failure,
                snapshots=rollback_snapshots,
                rollback_error=rollback_error,
            )
            raise MaterialPhaseError(
                "material promotion failed and wrote rollback evidence at "
                f"{rollback_artifact.path}"
            ) from failure
