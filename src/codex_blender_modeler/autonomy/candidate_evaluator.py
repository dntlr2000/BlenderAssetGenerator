"""Isolated Blender evaluation for controller-authored autonomy candidates."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..analysis.models import ModelingPlan
from ..architecture import list_interior_objects
from ..blender_artifacts import sha256_file, stable_json_digest
from ..blender_runner import run_blender
from ..integrated_quality import (
    EvidenceAvailability,
    HardGateEvidencePaths,
    HardGateRequirements,
    IntegratedQualityReport,
    ProducerIdentity,
    QualityArtifact,
    QualityGateProfile,
    QualityProvenance,
    apply_hard_gate_evidence,
    build_integrated_quality_report,
    discover_hard_gate_evidence_paths,
    write_integrated_quality_evidence,
)
from ..integrated_quality.blender_companion_service import (
    inspect_static_prop_authoring_companions,
)
from ..models import SceneSpec
from ..qa.models import RenderPassManifest, VisualQAReport
from ..qa.service import run_scene_spec_visual_qa_snapshot
from ..reference_evidence.models import CameraHypothesis, CameraHypothesisSet
from ..reference_scope import (
    validate_modeling_plan_content_scope,
    validate_scene_content_scope,
)
from ..structural_geometry.models import SceneSpecV03, StructuralGeometryCandidate
from ..structural_geometry.service import materialize_structural_candidate
from ..texturing.models import TextureManifest
from .authorization import artifact_for, canonical_digest
from .io import write_immutable_json
from .models import (
    AutonomyArtifact,
    AutonomyPlan,
    CandidateAuthoringAssignment,
    CandidateCompletionMarker,
    CandidateEvaluation,
    CandidateMetricVector,
    RootAuthorization,
    StructuralCandidateManifest,
    StructuralCandidatePlan,
)

_FORBIDDEN_CONTEXT_TOKENS = {
    "atmosphere",
    "background",
    "backdrop",
    "environment",
    "foliage",
    "ground",
    "landscape",
    "scenery",
    "sky",
    "terrain",
    "vegetation",
}
_CONTEXTUAL_ROCK_TOKENS = {"boulder", "boulders", "rock", "rocks"}
_ALLOWED_LOCAL_TEXTURE_PROVIDERS = {"cbm_pillow_procedural"}
_CANDIDATE_STAGE_PROFILE_ID = "candidate_reference_structural_v1"
_STRUCTURAL_GEOMETRY_KINDS = frozenset(
    {
        "loft",
        "sweep",
        "boolean_tree",
        "multi_loop_extrude",
        "geometry_nodes_template",
    }
)
_CANDIDATE_STAGE_GATE_IDS = (
    "gate.aq.evidence_binding",
    "gate.aq.build",
    "gate.aq.inspect",
    "gate.aq.validate",
    "gate.aq.required_semantics",
    "gate.aq.finite_transforms",
    "gate.aq.required_assembly",
    "gate.aq.topology_profile",
)
_CANDIDATE_TOPOLOGY_CHECKS = (
    "non_finite",
    "degenerate_face",
    "self_intersection",
    "winding",
    "flipped_normal",
    "loose_geometry",
    "open_boundary",
)


@dataclass(frozen=True, slots=True)
class _CandidateStageAssessment:
    """Carry the exact reference/structural stage verdict into candidate ranking."""

    hard_gate_failures: int
    structural_quality: float | None
    evidence_status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _StructuralCompilation:
    """Carry one optional SceneSpecV03 materialization into the normal candidate build."""

    scene: SceneSpec
    effective_scene_path: Path
    effective_scene_artifact: AutonomyArtifact
    scene_spec_v03_artifact: AutonomyArtifact | None
    compiled_scene_spec_artifact: AutonomyArtifact | None
    recipe_artifacts: tuple[AutonomyArtifact, ...]
    mesh_payload_artifacts: tuple[AutonomyArtifact, ...]
    materialization_receipts: tuple[AutonomyArtifact, ...]
    additional_provenance: tuple[AutonomyArtifact, ...]


def _candidate_stage_assessment(
    report: IntegratedQualityReport,
) -> _CandidateStageAssessment:
    """Summarize only candidate-stage reference and structural gates without later axes."""

    reference = next(
        (item for item in report.axes if item.axis == "reference_alignment"),
        None,
    )
    if reference is None:
        raise RuntimeError("candidate quality report has no reference-alignment axis")
    by_id = {item.gate_id: item for item in report.hard_gates}
    missing = [gate_id for gate_id in _CANDIDATE_STAGE_GATE_IDS if gate_id not in by_id]
    if missing:
        raise RuntimeError(f"candidate quality report omits stage hard gates: {missing}")
    gates = [by_id[gate_id] for gate_id in _CANDIDATE_STAGE_GATE_IDS]
    failed = [item.gate_id for item in gates if item.status == "failed"]
    unscorable = [item.gate_id for item in gates if item.status == "unscorable"]
    structural_quality = (
        None
        if unscorable
        else sum(item.status == "passed" for item in gates) / len(gates)
    )
    evidence_status = (
        "invalid"
        if failed
        else "unscorable"
        if reference.status == "unscorable" or unscorable
        else "scored"
    )
    reasons = [
        (
            f"{_CANDIDATE_STAGE_PROFILE_ID}: candidate reference evidence is "
            f"{reference.status} and remains independently scored."
        ),
        (
            "All candidate-stage build, semantic, finite, assembly, and topology gates passed."
            if not failed and not unscorable
            else "Candidate-stage structural gates did not all pass."
        ),
    ]
    if failed:
        reasons.append(f"Failed candidate-stage hard gates: {failed}.")
    if unscorable:
        reasons.append(f"Unscorable candidate-stage hard gates: {unscorable}.")
    return _CandidateStageAssessment(
        hard_gate_failures=len(failed),
        structural_quality=structural_quality,
        evidence_status=evidence_status,
        reasons=tuple(reasons),
    )


def _candidate_paths(root: Path) -> tuple[Path, Path, Path]:
    """Resolve the three controller-authored candidate contracts below one staging root."""

    return (
        root / "modeling_plan.json",
        root / "camera_hypothesis.json",
        root / "scene_spec.json",
    )


def _load_candidate_root_authorization(
    job_root: Path,
    assignment: CandidateAuthoringAssignment,
) -> RootAuthorization:
    """Load the exact active root authorization that bounds one AQ candidate."""

    session_root = (job_root / "production" / "autonomy" / assignment.session_id).resolve()
    try:
        session_root.relative_to(job_root.resolve())
    except ValueError as exc:
        raise ValueError("candidate autonomy session escaped its job") from exc
    authorization_path = session_root / "root_authorization.json"
    plan_path = session_root / "plan.json"
    if not authorization_path.is_file() or not plan_path.is_file():
        raise FileNotFoundError("candidate root authorization or autonomy plan is missing")
    authorization_artifact = artifact_for(job_root, authorization_path)
    authorization = RootAuthorization.model_validate_json(
        authorization_path.read_text(encoding="utf-8")
    )
    plan = AutonomyPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    expected_identity = (assignment.job_id, assignment.workflow_id, assignment.dispatch_id)
    if any(
        (item.job_id, item.workflow_id, item.dispatch_id) != expected_identity
        for item in (authorization, plan)
    ):
        raise PermissionError("candidate root authorization belongs to another production scope")
    if plan.root_authorization != authorization_artifact:
        raise ValueError("candidate root-authorization binding is stale")
    if (
        authorization.reference_content_scope != "primary_object_only"
        or plan.reference_content_scope != authorization.reference_content_scope
        or not authorization.target_subject.strip()
        or plan.target_subject != authorization.target_subject
    ):
        raise PermissionError(
            "AQ candidates require exact primary_object_only authorization and target_subject"
        )
    if authorization.status != "active":
        raise PermissionError("candidate root authorization is not active")
    if authorization.expires_at is not None and authorization.expires_at <= datetime.now(UTC):
        raise PermissionError("candidate root authorization has expired")
    required_prohibitions = {"interior", "external_network_provider"}
    if not required_prohibitions.issubset(set(authorization.prohibited_scopes)):
        raise PermissionError("candidate root authorization omits mandatory AQ prohibitions")
    if artifact_for(job_root, job_root / authorization.primary_reference.path) != (
        authorization.primary_reference
    ):
        raise ValueError("candidate primary-reference authorization is stale")
    return authorization


def _semantic_tokens(*values: str) -> set[str]:
    """Normalize semantic IDs, names, and tags into deterministic scope tokens."""

    return {
        token for value in values for token in re.findall(r"[a-z0-9]+", value.casefold()) if token
    }


def _scene_role(tags: list[str]) -> str | None:
    """Resolve the explicit primary/supporting role after shared scope validation."""

    normalized = {tag.strip().casefold() for tag in tags}
    if normalized.intersection({"qa_role:primary", "role:primary"}):
        return "primary"
    if normalized.intersection({"qa_role:supporting", "role:supporting"}):
        return "supporting"
    return None


def _assert_no_contextual_objects(
    modeling: ModelingPlan,
    scene: SceneSpec,
) -> None:
    """Reject environment geometry even when a candidate disguises it as subject content."""

    modeling_by_id = {item.id: item for item in modeling.objects}
    forbidden: list[str] = []
    for obj in scene.objects:
        planned = modeling_by_id[obj.id]
        role = _scene_role(list(obj.tags))
        tokens = _semantic_tokens(obj.id, obj.name, *obj.tags, planned.id, planned.label)
        hard_context = tokens.intersection(_FORBIDDEN_CONTEXT_TOKENS)
        contextual_rocks = tokens.intersection(_CONTEXTUAL_ROCK_TOKENS)
        if (
            planned.recommended_geometry == "terrain"
            or hard_context
            or (role != "primary" and contextual_rocks)
        ):
            forbidden.append(obj.id)
    if forbidden:
        raise PermissionError(
            "primary_object_only AQ candidate contains contextual terrain/ground/"
            f"background/vegetation/rocks/atmosphere objects: {sorted(forbidden)}"
        )


def _assert_local_candidate_sources(
    job_root: Path,
    authorization: RootAuthorization,
    scene: SceneSpec,
) -> None:
    """Bind candidate references and texture provenance to authorized local evidence only."""

    if not scene.sources:
        raise PermissionError("AQ candidate SceneSpec requires its authorized primary reference")
    unauthorized_sources = sorted(
        source.id
        for source in scene.sources
        if not source.immutable or source.path != authorization.primary_reference.path
    )
    if unauthorized_sources:
        raise PermissionError(
            f"AQ candidate introduced unauthorized source/provider evidence: {unauthorized_sources}"
        )
    for material in scene.materials:
        if material.texture_manifest is None:
            continue
        manifest_path = (job_root / material.texture_manifest).resolve()
        try:
            manifest_path.relative_to(job_root.resolve())
        except ValueError as exc:
            raise PermissionError("candidate texture manifest escaped its job") from exc
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise PermissionError("candidate texture manifest is missing or not a regular file")
        manifest = TextureManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        provider = manifest.provenance.provider if manifest.provenance is not None else None
        if provider not in _ALLOWED_LOCAL_TEXTURE_PROVIDERS:
            raise PermissionError(
                "AQ candidate texture manifest uses an external or unverifiable provider"
            )


def _validate_candidate_content_scope(
    job_root: Path,
    authorization: RootAuthorization,
    modeling: ModelingPlan,
    scene: SceneSpec,
) -> None:
    """Enforce object-only semantic roles and prohibited scopes before Blender execution."""

    if modeling.stage != "authored":
        raise PermissionError("AQ candidate ModelingPlan must be in authored stage")
    try:
        validate_modeling_plan_content_scope(
            modeling,
            scope=authorization.reference_content_scope,
            target_subject=authorization.target_subject,
        )
        validate_scene_content_scope(
            scene,
            scope=authorization.reference_content_scope,
            target_subject=authorization.target_subject,
        )
    except ValueError as exc:
        raise PermissionError(f"AQ candidate content scope is invalid: {exc}") from exc
    modeling_roles = {item.id: item.scope_role for item in modeling.objects}
    scene_roles = {item.id: _scene_role(list(item.tags)) for item in scene.objects}
    if set(modeling_roles) != set(scene_roles):
        raise PermissionError(
            "AQ candidate ModelingPlan and SceneSpec semantic ID sets must match exactly"
        )
    role_conflicts = sorted(
        object_id for object_id, role in modeling_roles.items() if role != scene_roles[object_id]
    )
    if role_conflicts:
        raise PermissionError(
            f"AQ candidate ModelingPlan/SceneSpec roles disagree: {role_conflicts}"
        )
    interior_ids = sorted(item.id for item in list_interior_objects(scene))
    if interior_ids:
        raise PermissionError(
            f"autonomous_static_prop_v1 has no InteriorScope authority; rejected: {interior_ids}"
        )
    _assert_no_contextual_objects(modeling, scene)
    _assert_local_candidate_sources(job_root, authorization, scene)


def _validate_authored_candidate(
    assignment: CandidateAuthoringAssignment,
    candidate_root: Path,
    job_root: Path,
) -> tuple[ModelingPlan, CameraHypothesis, SceneSpec]:
    """Strictly validate candidate contracts and their immutable assignment scope."""

    modeling_path, camera_path, scene_path = _candidate_paths(candidate_root)
    missing = [path.name for path in (modeling_path, camera_path, scene_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"controller candidate outputs are missing: {missing}")
    modeling = ModelingPlan.model_validate_json(modeling_path.read_text(encoding="utf-8"))
    camera = CameraHypothesis.model_validate_json(camera_path.read_text(encoding="utf-8"))
    scene = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    if modeling.job_id != assignment.job_id or scene.job_id != assignment.job_id:
        raise ValueError("candidate contracts belong to another job")
    if modeling.surface_detail_policy is None:
        raise ValueError(
            "autonomy candidate ModelingPlan requires an explicit surface_detail_policy"
        )
    if modeling.assembly_consistency_policy != "spatial_v1" or modeling.assembly_frame is None:
        raise ValueError("autonomy candidate ModelingPlan requires spatial_v1 assembly evidence")
    authorization = _load_candidate_root_authorization(job_root, assignment)
    _validate_candidate_content_scope(job_root, authorization, modeling, scene)
    hypothesis_set_path = job_root / assignment.camera_hypothesis_set.path
    if artifact_for(job_root, hypothesis_set_path) != assignment.camera_hypothesis_set:
        raise ValueError("candidate camera-hypothesis set is stale")
    hypothesis_set = CameraHypothesisSet.model_validate_json(
        hypothesis_set_path.read_text(encoding="utf-8")
    )
    declared = {item.hypothesis_id: item for item in hypothesis_set.hypotheses}.get(
        camera.hypothesis_id
    )
    if declared is None or declared != camera:
        raise PermissionError("candidate camera is not an exact declared hypothesis")
    expected_projection = "PERSP" if camera.projection == "perspective" else "ORTHO"
    if scene.camera.projection != expected_projection:
        raise PermissionError("SceneSpec camera projection differs from its hypothesis")
    if (
        camera.projection == "perspective"
        and camera.intrinsics.focal_length_mm is not None
        and abs(scene.camera.focal_length_mm - camera.intrinsics.focal_length_mm) > 1e-6
    ):
        raise PermissionError("SceneSpec focal length differs from its camera hypothesis")
    return modeling, camera, scene


def _assert_exact_baseline(
    job_root: Path,
    assignment: CandidateAuthoringAssignment,
) -> tuple[dict[str, Any] | None, CandidateEvaluation | None]:
    """Verify the exact canonical baseline and optional prior evaluation before scoring."""

    if assignment.workflow_modeling_plan is not None:
        current = artifact_for(job_root, job_root / assignment.workflow_modeling_plan.path)
        if current != assignment.workflow_modeling_plan:
            raise ValueError("candidate ModelingPlan baseline is stale")
    baseline_scene: dict[str, Any] | None = None
    if assignment.workflow_scene_spec is not None:
        current = artifact_for(job_root, job_root / assignment.workflow_scene_spec.path)
        if current != assignment.workflow_scene_spec:
            raise ValueError("candidate SceneSpec baseline is stale")
        baseline_scene = json.loads(
            (job_root / assignment.workflow_scene_spec.path).read_text(encoding="utf-8")
        )
    elif (job_root / "analysis" / "scene_spec.json").exists():
        raise ValueError("an unbound canonical SceneSpec appeared before candidate evaluation")
    baseline_evaluation = None
    if assignment.baseline_evaluation is not None:
        baseline_path = job_root / assignment.baseline_evaluation.path
        if artifact_for(job_root, baseline_path) != assignment.baseline_evaluation:
            raise ValueError("candidate baseline evaluation is stale")
        baseline_evaluation = CandidateEvaluation.model_validate_json(
            baseline_path.read_text(encoding="utf-8")
        )
    return baseline_scene, baseline_evaluation


def _validate_parametric_scope(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    """Permit only bounded camera, transform, and primitive/profile-depth edits."""

    immutable_top_level = {
        key for key in baseline if key not in {"camera", "objects", "assumptions", "revision_notes"}
    }
    for key in immutable_top_level:
        if candidate.get(key) != baseline.get(key):
            raise PermissionError(f"parametric candidate changed forbidden field: {key}")
    allowed_camera = {"location", "target", "focal_length_mm", "ortho_scale"}
    baseline_camera = baseline.get("camera", {})
    candidate_camera = candidate.get("camera", {})
    for key in set(baseline_camera) | set(candidate_camera):
        if key not in allowed_camera and candidate_camera.get(key) != baseline_camera.get(key):
            raise PermissionError(f"parametric candidate changed camera.{key}")
    baseline_objects = {
        str(item["id"]): item
        for item in baseline.get("objects", [])
        if isinstance(item, dict) and "id" in item
    }
    candidate_objects = {
        str(item["id"]): item
        for item in candidate.get("objects", [])
        if isinstance(item, dict) and "id" in item
    }
    if set(candidate_objects) != set(baseline_objects):
        raise PermissionError("parametric candidate cannot add or remove semantic objects")
    for object_id, original in baseline_objects.items():
        revised = candidate_objects[object_id]
        for key in set(original) | set(revised):
            if key in {"transform", "geometry"}:
                continue
            if revised.get(key) != original.get(key):
                raise PermissionError(f"parametric candidate changed {object_id}.{key}")
        original_geometry = original.get("geometry", {})
        revised_geometry = revised.get("geometry", {})
        kind = original_geometry.get("kind")
        if revised_geometry.get("kind") != kind:
            raise PermissionError("parametric candidate cannot change geometry kind")
        allowed_geometry = (
            {"dimensions"}
            if kind == "primitive"
            else {"depth"}
            if kind == "profile_extrude"
            else set()
        )
        for key in set(original_geometry) | set(revised_geometry):
            if key not in allowed_geometry and revised_geometry.get(key) != original_geometry.get(
                key
            ):
                raise PermissionError(f"parametric candidate changed {object_id}.geometry.{key}")


def _validate_candidate_phase(
    assignment: CandidateAuthoringAssignment,
    baseline: dict[str, Any] | None,
    modeling: ModelingPlan,
    candidate: SceneSpec,
    modeling_sha256: str,
    job_root: Path,
) -> None:
    """Enforce initial, structural, and parametric authoring boundaries."""

    if assignment.candidate_phase == "initial":
        if baseline is not None:
            raise ValueError("initial candidate unexpectedly has a canonical SceneSpec")
        return
    if baseline is None or assignment.workflow_scene_spec is None:
        raise ValueError("refinement candidate requires an exact canonical SceneSpec")
    candidate_payload = candidate.model_dump(mode="json")
    baseline_subject_ids = {
        str(item.get("id"))
        for item in baseline.get("objects", [])
        if isinstance(item, dict)
        and any(
            str(tag).casefold()
            in {
                "qa_role:primary",
                "role:primary",
                "qa_role:supporting",
                "role:supporting",
            }
            for tag in item.get("tags", [])
        )
    }
    missing_subject_ids = baseline_subject_ids - {item.id for item in candidate.objects}
    if missing_subject_ids:
        raise PermissionError(
            "refinement candidate removed required primary/supporting IDs: "
            f"{sorted(missing_subject_ids)}"
        )
    if assignment.workflow_modeling_plan is None:
        raise ValueError("refinement candidate requires an exact ModelingPlan baseline")
    baseline_modeling_path = job_root / assignment.workflow_modeling_plan.path
    baseline_modeling = ModelingPlan.model_validate_json(
        baseline_modeling_path.read_text(encoding="utf-8")
    )
    baseline_plan_roles = {item.id: item.scope_role for item in baseline_modeling.objects}
    candidate_plan_roles = {item.id: item.scope_role for item in modeling.objects}
    missing_plan_ids = set(baseline_plan_roles) - set(candidate_plan_roles)
    if missing_plan_ids:
        raise PermissionError(
            f"refinement candidate removed required ModelingPlan IDs: {sorted(missing_plan_ids)}"
        )
    changed_roles = sorted(
        object_id
        for object_id, role in baseline_plan_roles.items()
        if candidate_plan_roles.get(object_id) != role
    )
    if changed_roles:
        raise PermissionError(
            f"refinement candidate changed stable semantic roles: {changed_roles}"
        )
    if candidate_payload.get("materials") != baseline.get("materials"):
        raise PermissionError("structural candidates cannot change material identities")
    if assignment.candidate_phase == "parametric":
        if (
            assignment.workflow_modeling_plan is None
            or modeling_sha256 != assignment.workflow_modeling_plan.sha256
        ):
            raise PermissionError("parametric candidate must preserve ModelingPlan bytes")
        _validate_parametric_scope(baseline, candidate_payload)


def _change_magnitude(left: Any, right: Any) -> float:
    """Measure a deterministic normalized JSON change cost for tie-breaking only."""

    if type(left) is not type(right):
        return 1.0
    if isinstance(left, dict):
        keys = sorted(set(left) | set(right))
        return sum(_change_magnitude(left.get(key), right.get(key)) for key in keys)
    if isinstance(left, list):
        length = max(len(left), len(right))
        return sum(
            _change_magnitude(
                left[index] if index < len(left) else None,
                right[index] if index < len(right) else None,
            )
            for index in range(length)
        )
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        return abs(float(right) - float(left)) / max(1.0, abs(float(left)))
    return 0.0 if left == right else 1.0


def _validate_scene_spec_v03_mirror(legacy: SceneSpec, candidate: SceneSpecV03) -> None:
    """Allow structural recipes only when every legacy identity and non-geometry field matches."""

    legacy_payload = legacy.model_dump(mode="json")
    candidate_payload = candidate.model_dump(mode="json")
    for key, value in legacy_payload.items():
        if key in {"schema_version", "objects"}:
            continue
        if candidate_payload.get(key) != value:
            raise PermissionError(f"SceneSpecV03 changed legacy candidate field: {key}")
    legacy_objects = legacy_payload["objects"]
    candidate_objects = candidate_payload["objects"]
    if [item["id"] for item in legacy_objects] != [item["id"] for item in candidate_objects]:
        raise PermissionError("SceneSpecV03 must preserve exact object identity and order")
    structural_count = 0
    for legacy_object, candidate_object in zip(
        legacy_objects,
        candidate_objects,
        strict=True,
    ):
        for key, value in legacy_object.items():
            if key == "geometry":
                continue
            if candidate_object.get(key) != value:
                raise PermissionError(
                    "SceneSpecV03 changed legacy object identity, material, transform, "
                    f"hierarchy, or metadata: {legacy_object['id']}.{key}"
                )
        kind = str(candidate_object["geometry"]["kind"])
        if kind in _STRUCTURAL_GEOMETRY_KINDS:
            structural_count += 1
            continue
        if candidate_object["geometry"] != legacy_object["geometry"]:
            raise PermissionError(
                f"SceneSpecV03 changed non-structural geometry: {legacy_object['id']}"
            )
        if candidate_object.get("geometry_intent") is not None:
            raise PermissionError(
                f"non-structural SceneSpecV03 object has unapplied geometry intent: "
                f"{legacy_object['id']}"
            )
    if structural_count == 0:
        raise ValueError("SceneSpecV03 candidate contains no whitelisted structural geometry")


def _validate_structural_materialization_report(
    report_path: Path,
    recipe: StructuralGeometryCandidate,
    mesh_path: Path,
    blend_path: Path,
) -> None:
    """Verify Blender's receipt against the exact recipe, payload, and materialization blend."""

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    expected = {
        "status": "passed",
        "semantic_id": recipe.semantic_id,
        "builder_kind": recipe.geometry.kind,
        "candidate_sha256": stable_json_digest(recipe.model_dump(mode="json")),
        "mesh_sha256": sha256_file(mesh_path),
        "blend_sha256": sha256_file(blend_path),
    }
    if not isinstance(payload, dict) or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise RuntimeError(
            f"structural materialization receipt is stale or inconsistent: {recipe.semantic_id}"
        )
    if int(payload.get("vertex_count", 0)) < 3 or int(payload.get("polygon_count", 0)) < 1:
        raise RuntimeError(f"structural materialization is empty: {recipe.semantic_id}")


def _structural_bundle_artifacts(compilation: _StructuralCompilation) -> list[AutonomyArtifact]:
    """Return every immutable artifact that must participate in structural fingerprints."""

    artifacts: list[AutonomyArtifact] = []
    if compilation.scene_spec_v03_artifact is not None:
        artifacts.append(compilation.scene_spec_v03_artifact)
    if compilation.compiled_scene_spec_artifact is not None:
        artifacts.append(compilation.compiled_scene_spec_artifact)
    artifacts.extend(compilation.recipe_artifacts)
    artifacts.extend(compilation.mesh_payload_artifacts)
    artifacts.extend(compilation.materialization_receipts)
    artifacts.extend(compilation.additional_provenance)
    return artifacts


def _compile_optional_structural_scene(
    job_root: Path,
    candidate_root: Path,
    assignment: CandidateAuthoringAssignment,
    legacy_scene: SceneSpec,
    legacy_scene_artifact: AutonomyArtifact,
) -> _StructuralCompilation:
    """Materialize a mirrored SceneSpecV03 and compile its recipes to path-backed v0.2."""

    expected_path = candidate_root / "scene_spec_v03.json"
    if assignment.scene_spec_v03_output is None:
        if expected_path.is_file():
            raise PermissionError("candidate authored an undeclared SceneSpecV03 artifact")
        return _StructuralCompilation(
            scene=legacy_scene,
            effective_scene_path=candidate_root / "scene_spec.json",
            effective_scene_artifact=legacy_scene_artifact,
            scene_spec_v03_artifact=None,
            compiled_scene_spec_artifact=None,
            recipe_artifacts=(),
            mesh_payload_artifacts=(),
            materialization_receipts=(),
            additional_provenance=(),
        )
    declared_path = (job_root / assignment.scene_spec_v03_output).resolve()
    if declared_path != expected_path.resolve():
        raise PermissionError("candidate SceneSpecV03 path differs from its assignment")
    if not declared_path.is_file():
        return _StructuralCompilation(
            scene=legacy_scene,
            effective_scene_path=candidate_root / "scene_spec.json",
            effective_scene_artifact=legacy_scene_artifact,
            scene_spec_v03_artifact=None,
            compiled_scene_spec_artifact=None,
            recipe_artifacts=(),
            mesh_payload_artifacts=(),
            materialization_receipts=(),
            additional_provenance=(),
        )

    scene_v03 = SceneSpecV03.model_validate_json(declared_path.read_text(encoding="utf-8"))
    _validate_scene_spec_v03_mirror(legacy_scene, scene_v03)
    structural_root = candidate_root / "structural_geometry"
    compiled_objects = [item.model_dump(mode="json") for item in legacy_scene.objects]
    compiled_by_id = {str(item["id"]): item for item in compiled_objects}
    recipe_artifacts: list[AutonomyArtifact] = []
    mesh_artifacts: list[AutonomyArtifact] = []
    receipt_artifacts: list[AutonomyArtifact] = []
    blend_artifacts: list[AutonomyArtifact] = []
    structural_objects = [
        item for item in scene_v03.objects if item.geometry.kind in _STRUCTURAL_GEOMETRY_KINDS
    ]
    for index, item in enumerate(structural_objects, start=1):
        recipe = StructuralGeometryCandidate(
            semantic_id=item.id,
            geometry=item.geometry,  # type: ignore[arg-type]
            geometry_intent=item.geometry_intent,
        )
        component = f"object-{index:03d}-{stable_json_digest(item.id)[:12]}"
        object_root = structural_root / component
        recipe_path = object_root / "recipe.json"
        mesh_path = object_root / "mesh_payload.json"
        blend_path = object_root / "materialization.blend"
        report_path = object_root / "materialization_receipt.json"
        relative = {
            path: path.resolve().relative_to(job_root.resolve()).as_posix()
            for path in (recipe_path, mesh_path, blend_path, report_path)
        }
        materialize_structural_candidate(
            job_root=job_root,
            candidate=recipe,
            candidate_relative_path=relative[recipe_path],
            mesh_relative_path=relative[mesh_path],
            blend_relative_path=relative[blend_path],
            report_relative_path=relative[report_path],
        )
        _validate_structural_materialization_report(
            report_path,
            recipe,
            mesh_path,
            blend_path,
        )
        recipe_artifacts.append(artifact_for(job_root, recipe_path))
        mesh_artifacts.append(artifact_for(job_root, mesh_path))
        receipt_artifacts.append(artifact_for(job_root, report_path))
        blend_artifacts.append(artifact_for(job_root, blend_path))
        compiled_by_id[item.id]["geometry"] = {
            "kind": "custom_mesh",
            "path": relative[mesh_path],
            "format": "mesh_json",
            "recalculate_normals": True,
        }

    compiled_payload = legacy_scene.model_dump(mode="json")
    compiled_payload["objects"] = [compiled_by_id[item.id] for item in legacy_scene.objects]
    compiled_scene = SceneSpec.model_validate(compiled_payload)
    compiled_path = candidate_root / "compiled_scene_spec.json"
    write_immutable_json(job_root, compiled_path, compiled_scene.model_dump(mode="json"))
    compiled_artifact = artifact_for(job_root, compiled_path)
    return _StructuralCompilation(
        scene=compiled_scene,
        effective_scene_path=compiled_path,
        effective_scene_artifact=compiled_artifact,
        scene_spec_v03_artifact=artifact_for(job_root, declared_path),
        compiled_scene_spec_artifact=compiled_artifact,
        recipe_artifacts=tuple(recipe_artifacts),
        mesh_payload_artifacts=tuple(mesh_artifacts),
        materialization_receipts=tuple(receipt_artifacts),
        additional_provenance=tuple(blend_artifacts),
    )


def _write_completion_marker(
    job_root: Path,
    candidate_root: Path,
    assignment: CandidateAuthoringAssignment,
    assignment_artifact: AutonomyArtifact,
    compilation: _StructuralCompilation,
    created_at: datetime,
) -> AutonomyArtifact:
    """Bind exact controller outputs before Blender is allowed to evaluate them."""

    modeling_path, camera_path, scene_path = _candidate_paths(candidate_root)
    outputs = [artifact_for(job_root, path) for path in (modeling_path, camera_path, scene_path)]
    structural_artifacts = _structural_bundle_artifacts(compilation)
    completion = CandidateCompletionMarker(
        contract_id=f"completion-{assignment.candidate_id}",
        completion_id=f"completion-{assignment.candidate_id}",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        input_sha256=assignment_artifact.sha256,
        source_fingerprint=canonical_digest(
            {item.path: item.sha256 for item in [*outputs, *structural_artifacts]}
        ),
        producer="codex_blender_modeler.autonomy.candidate_evaluator",
        producer_version="0.1.0",
        provenance=[assignment_artifact, *outputs, *structural_artifacts],
        created_at=created_at,
        session_id=assignment.session_id,
        candidate_id=assignment.candidate_id,
        assignment=assignment_artifact,
        authoring_prompt_sha256=assignment.authoring_prompt_sha256,
        modeling_plan=outputs[0],
        camera_hypothesis=outputs[1],
        scene_spec_candidate=outputs[2],
        scene_spec_v03_candidate=compilation.scene_spec_v03_artifact,
        compiled_scene_spec_candidate=compilation.compiled_scene_spec_artifact,
        structural_recipes=list(compilation.recipe_artifacts),
        structural_mesh_payloads=list(compilation.mesh_payload_artifacts),
        structural_materialization_receipts=list(compilation.materialization_receipts),
    )
    path = candidate_root / "completion_marker.json"
    write_immutable_json(job_root, path, completion.model_dump(mode="json"))
    return artifact_for(job_root, path)


def _build_candidate(
    job_root: Path,
    candidate_root: Path,
    scene_path: Path,
) -> tuple[Path, Path, Path]:
    """Produce isolated build evidence and defer its verdict to exact AQ hard gates."""

    build_root = candidate_root / "build"
    build_root.mkdir(parents=True, exist_ok=False)
    blend = build_root / "scene.blend"
    inventory = build_root / "scene_inventory.json"
    validation = build_root / "validation.json"
    run_blender(
        "build_scene.py",
        [
            "--spec",
            str(scene_path),
            "--job-root",
            str(job_root),
            "--output",
            str(blend),
        ],
    )
    run_blender("inspect_scene.py", ["--output", str(inventory)], blend_file=blend)
    run_blender(
        "validate_scene.py",
        [
            "--spec",
            str(scene_path),
            "--job-root",
            str(job_root),
            "--output",
            str(validation),
        ],
        blend_file=blend,
    )
    return blend, inventory, validation


def _quality_artifact(
    job_root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
    produced_at: datetime,
) -> QualityArtifact:
    """Convert one exact candidate file to Integrated Quality provenance."""

    relative = path.resolve().relative_to(job_root.resolve()).as_posix()
    return QualityArtifact(
        artifact_id=artifact_id,
        kind=kind,
        relative_path=relative,
        sha256=sha256_file(path),
        producer=ProducerIdentity(name="autonomy-candidate-evaluator", version="0.1.0"),
        produced_at=produced_at,
    )


def _candidate_hard_gate_artifacts(
    job_root: Path,
    paths: HardGateEvidencePaths,
    *,
    produced_at: datetime,
) -> list[QualityArtifact]:
    """Bind every discovered candidate-owned hard-gate input with a semantic artifact ID."""

    declared = {
        path.resolve(): (artifact_id, kind)
        for path, artifact_id, kind in (
            (paths.blend, "candidate-blend", "blender-build"),
            (paths.inventory, "candidate-inventory", "scene-inventory"),
            (paths.validation, "candidate-validation", "scene-validation"),
            (paths.modeling_plan, "candidate-modeling-plan", "modeling-plan"),
            (paths.scene_spec, "candidate-scene-spec", "scene-spec"),
            (
                paths.assembly_companion,
                "candidate-assembly-companion",
                "assembly-companion",
            ),
            (
                paths.topology_companion,
                "candidate-topology-companion",
                "topology-companion",
            ),
        )
        if path is not None
    }
    artifacts: list[QualityArtifact] = []
    for index, path in enumerate(
        discover_hard_gate_evidence_paths(job_root, paths),
        start=1,
    ):
        artifact_id, kind = declared.get(
            path.resolve(),
            (f"candidate-hard-gate-{index:02d}", "hard-gate-evidence"),
        )
        artifacts.append(
            _quality_artifact(
                job_root,
                path,
                artifact_id=artifact_id,
                kind=kind,
                produced_at=produced_at,
            )
        )
    return artifacts


def evaluate_structural_candidate(
    job_root: Path,
    *,
    assignment_path: Path,
    quality_profile_path: Path,
) -> dict[str, Any]:
    """Run strict isolated build and direct QA, then publish immutable candidate evidence."""

    root = job_root.resolve()
    assignment_artifact = artifact_for(root, assignment_path)
    assignment = CandidateAuthoringAssignment.model_validate_json(
        assignment_path.read_text(encoding="utf-8")
    )
    candidate_root = root / assignment.output_root
    try:
        candidate_root.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError("candidate output escaped its job") from exc
    baseline_scene, baseline_evaluation = _assert_exact_baseline(root, assignment)
    modeling, _camera, authored_scene = _validate_authored_candidate(
        assignment,
        candidate_root,
        root,
    )
    now = datetime.now(UTC)
    modeling_artifact = artifact_for(root, candidate_root / "modeling_plan.json")
    camera_artifact = artifact_for(root, candidate_root / "camera_hypothesis.json")
    scene_artifact = artifact_for(root, candidate_root / "scene_spec.json")
    compilation = _compile_optional_structural_scene(
        root,
        candidate_root,
        assignment,
        authored_scene,
        scene_artifact,
    )
    scene = compilation.scene
    structural_artifacts = _structural_bundle_artifacts(compilation)
    _validate_candidate_phase(
        assignment,
        baseline_scene,
        modeling,
        scene,
        modeling_artifact.sha256,
        root,
    )
    completion_artifact = _write_completion_marker(
        root,
        candidate_root,
        assignment,
        assignment_artifact,
        compilation,
        now,
    )
    candidate_plan = StructuralCandidatePlan(
        contract_id=f"plan-{assignment.candidate_id}",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        input_sha256=assignment_artifact.sha256,
        source_fingerprint=stable_json_digest(
            {
                "assignment": assignment_artifact.sha256,
                "modeling_plan": modeling_artifact.sha256,
                "camera": camera_artifact.sha256,
                "scene_spec": scene_artifact.sha256,
                "effective_scene_spec": compilation.effective_scene_artifact.sha256,
                "structural_evidence": {
                    item.path: item.sha256 for item in structural_artifacts
                },
            }
        ),
        producer="codex_blender_modeler.autonomy.candidate_evaluator",
        producer_version="0.1.0",
        provenance=[
            assignment_artifact,
            modeling_artifact,
            camera_artifact,
            scene_artifact,
            *structural_artifacts,
        ],
        created_at=now,
        candidate_id=assignment.candidate_id,
        candidate_index=assignment.candidate_index,
        modeling_plan=modeling_artifact,
        camera_hypothesis=camera_artifact,
        scene_spec_candidate=scene_artifact,
        scene_spec_v03_candidate=compilation.scene_spec_v03_artifact,
        compiled_scene_spec_candidate=compilation.compiled_scene_spec_artifact,
        structural_recipes=list(compilation.recipe_artifacts),
        structural_mesh_payloads=list(compilation.mesh_payload_artifacts),
        structural_materialization_receipts=list(compilation.materialization_receipts),
        affected_semantic_ids=[item.id for item in scene.objects],
        assumptions=[
            "Hidden surfaces and absolute depth remain inferred from single-image evidence."
        ],
        expected_improvements=[
            "Improve direct-reference silhouette and semantic proportions without changing scope."
        ],
        exact_input_map={
            assignment_artifact.path: assignment_artifact.sha256,
            modeling_artifact.path: modeling_artifact.sha256,
            camera_artifact.path: camera_artifact.sha256,
            **{item.path: item.sha256 for item in structural_artifacts},
            **(
                {assignment.workflow_modeling_plan.path: assignment.workflow_modeling_plan.sha256}
                if assignment.workflow_modeling_plan is not None
                else {}
            ),
            **(
                {assignment.workflow_scene_spec.path: assignment.workflow_scene_spec.sha256}
                if assignment.workflow_scene_spec is not None
                else {}
            ),
            **(
                {assignment.baseline_evaluation.path: assignment.baseline_evaluation.sha256}
                if assignment.baseline_evaluation is not None
                else {}
            ),
        },
        authoring_prompt_sha256=assignment.authoring_prompt_sha256,
    )
    plan_path = candidate_root / "candidate_plan.json"
    write_immutable_json(root, plan_path, candidate_plan.model_dump(mode="json"))
    plan_artifact = artifact_for(root, plan_path)
    blend, inventory, validation = _build_candidate(
        root,
        candidate_root,
        compilation.effective_scene_path,
    )
    candidate_relative = candidate_root.relative_to(root).as_posix()
    effective_scene_relative = compilation.effective_scene_path.relative_to(root).as_posix()
    companion = inspect_static_prop_authoring_companions(
        job_root=root,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        output_root_relative=f"{candidate_relative}/quality_companions",
        scene_spec_relative=effective_scene_relative,
        modeling_plan_relative=f"{candidate_relative}/modeling_plan.json",
        blend_relative=f"{candidate_relative}/build/scene.blend",
    )
    hard_gate_paths = HardGateEvidencePaths(
        blend=blend,
        inventory=inventory,
        validation=validation,
        modeling_plan=candidate_root / "modeling_plan.json",
        scene_spec=compilation.effective_scene_path,
        assembly_companion=companion.assembly_report_path,
        topology_companion=companion.topology_report_path,
    )
    qa_result = run_scene_spec_visual_qa_snapshot(
        assignment.job_id,
        scene_spec_path=compilation.effective_scene_path,
        blend_path=blend,
        run_dir=candidate_root / "qa",
        run_id=f"aq-{assignment.candidate_id[:48]}",
    )
    qa_report_path = Path(str(qa_result["visual_qa_report"]))
    qa_report = VisualQAReport.model_validate_json(qa_report_path.read_text(encoding="utf-8"))
    manifest_path = Path(str(qa_result["render_pass_manifest"]))
    render_manifest = RenderPassManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    beauty = next(item for item in render_manifest.passes if item.kind == "beauty")
    beauty_path = (manifest_path.parent / beauty.path).resolve(strict=True)
    if sha256_file(beauty_path) != beauty.sha256:
        raise RuntimeError("candidate beauty pass changed after QA publication")
    quality_profile = QualityGateProfile.model_validate_json(
        quality_profile_path.read_text(encoding="utf-8")
    )
    provenance_artifacts = [
        _quality_artifact(
            root,
            qa_report_path,
            artifact_id="candidate-v06-qa",
            kind="visual-qa",
            produced_at=now,
        ),
        _quality_artifact(
            root,
            manifest_path,
            artifact_id="candidate-v06-pass-manifest",
            kind="render-pass-manifest",
            produced_at=now,
        ),
        *_candidate_hard_gate_artifacts(
            root,
            hard_gate_paths,
            produced_at=now,
        ),
    ]
    quality_provenance = QualityProvenance(
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        source_fingerprint=quality_profile.source_fingerprint,
        input_sha256=stable_json_digest(
            {item.relative_path: item.sha256 for item in provenance_artifacts}
        ),
        artifacts=provenance_artifacts,
    )
    quality_report = build_integrated_quality_report(
        report_id=f"quality-{assignment.candidate_id}",
        provenance=quality_provenance,
        gate_profile=quality_profile,
        gate_profile_sha256=sha256_file(quality_profile_path),
        producer=ProducerIdentity(name="autonomy-candidate-evaluator", version="0.1.0"),
        created_at=now,
        evidence_availability=[
            EvidenceAvailability(
                evidence_id="candidate-reference",
                axis="reference_alignment",
                status="available",
                artifact_id="candidate-v06-qa",
                confidence=1.0,
                reason="Exact direct V0.6 candidate QA is available.",
            ),
            EvidenceAvailability(
                evidence_id="candidate-structural",
                axis="structural_integrity",
                status="degraded",
                artifact_id="candidate-assembly-companion",
                confidence=1.0,
                reason=(
                    "Exact candidate build, semantic, finite, and assembly evidence is bound; "
                    "the terminal material/package axes remain outside this stage."
                ),
            ),
            EvidenceAvailability(
                evidence_id="candidate-topology",
                axis="production_readiness",
                status="degraded",
                artifact_id="candidate-topology-companion",
                confidence=1.0,
                reason=(
                    "Candidate-stage geometry topology is available while UV, tangent, export, "
                    "and clean-import evidence remain intentionally deferred."
                ),
            ),
            EvidenceAvailability(
                evidence_id="candidate-material",
                axis="material_fidelity",
                status="unavailable",
                confidence=0,
                reason="Initial structural candidates precede V0.5 material authoring.",
            ),
            EvidenceAvailability(
                evidence_id="candidate-production",
                axis="production_readiness",
                status="unavailable",
                confidence=0,
                reason="Initial candidates precede V0.7 package round trip.",
            ),
        ],
        reference_evidence_id="candidate-reference",
        structural_evidence_id="candidate-structural",
        material_evidence_id="candidate-material",
        production_evidence_id="candidate-production",
        visual_qa=qa_report,
        notes=[
            "Candidate-stage promotion requires scorable reference evidence and exact structural "
            "hard gates, independently from terminal quality acceptance.",
            "Material and full production axes remain unscorable until V0.5 and V0.7 evidence.",
        ],
    )
    quality_report = apply_hard_gate_evidence(
        quality_report,
        job_root=root,
        paths=hard_gate_paths,
        requirements=HardGateRequirements(
            require_build=True,
            require_assembly=True,
            require_topology=True,
            require_material_pbr=False,
            require_package=False,
            topology_required_checks=_CANDIDATE_TOPOLOGY_CHECKS,  # type: ignore[arg-type]
        ),
        structural_evidence_id="candidate-structural",
        material_evidence_id="candidate-material",
        production_evidence_id="candidate-production",
        topology_evidence_id="candidate-topology",
    )
    stage_assessment = _candidate_stage_assessment(quality_report)
    quality_manifest = write_integrated_quality_evidence(
        root,
        quality_report,
        output_dir=candidate_root / "integrated_quality",
    )
    quality_artifact = artifact_for(
        root,
        candidate_root / "integrated_quality" / "integrated_quality_report.json",
    )
    companion_artifacts = [
        artifact_for(root, path)
        for path in (
            companion.snapshot_path,
            companion.assembly_request_path,
            companion.assembly_report_path,
            companion.topology_report_path,
        )
    ]
    candidate_manifest = StructuralCandidateManifest(
        contract_id=f"manifest-{assignment.candidate_id}",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        input_sha256=completion_artifact.sha256,
        source_fingerprint=candidate_plan.source_fingerprint,
        producer="codex_blender_modeler.autonomy.candidate_evaluator",
        producer_version="0.1.0",
        provenance=[
            plan_artifact,
            completion_artifact,
            quality_artifact,
            *companion_artifacts,
            *structural_artifacts,
        ],
        created_at=now,
        candidate_id=assignment.candidate_id,
        plan=plan_artifact,
        scene_spec=compilation.effective_scene_artifact,
        scene_spec_v03_candidate=compilation.scene_spec_v03_artifact,
        compiled_scene_spec_candidate=compilation.compiled_scene_spec_artifact,
        structural_recipes=list(compilation.recipe_artifacts),
        structural_mesh_payloads=list(compilation.mesh_payload_artifacts),
        structural_materialization_receipts=list(compilation.materialization_receipts),
        completion_marker=completion_artifact,
        blend=artifact_for(root, blend),
        inventory=artifact_for(root, inventory),
        validation=artifact_for(root, validation),
        low_resolution_renders=[artifact_for(root, beauty_path)],
        integrated_quality_report=quality_artifact,
        status="evaluated",
    )
    candidate_manifest_path = candidate_root / "candidate_manifest.json"
    write_immutable_json(
        root,
        candidate_manifest_path,
        candidate_manifest.model_dump(mode="json"),
    )
    candidate_manifest_artifact = artifact_for(root, candidate_manifest_path)
    direct_score = qa_report.direct_metrics.overall_direct_score
    silhouette_iou = qa_report.direct_metrics.silhouette_iou
    direct_gain = None
    critical_regressions: list[str] = []
    meaningful_gain = True
    if baseline_evaluation is not None:
        baseline_direct = baseline_evaluation.metrics.reference_fidelity
        baseline_silhouette = baseline_evaluation.metrics.silhouette_iou
        if baseline_direct is None or baseline_silhouette is None:
            meaningful_gain = False
            critical_regressions.append("baseline_reference_unscorable")
        else:
            direct_gain = direct_score - baseline_direct
            meaningful_gain = direct_gain >= quality_profile.meaningful_gain_min
            if direct_gain < 0:
                critical_regressions.append("reference_direct_score_regression")
            if silhouette_iou < baseline_silhouette:
                critical_regressions.append("silhouette_iou_regression")
    candidate_change = (
        _change_magnitude(baseline_scene, scene.model_dump(mode="json"))
        if baseline_scene is not None
        else 0.0
    )
    eligible = (
        stage_assessment.evidence_status == "scored"
        and stage_assessment.hard_gate_failures == 0
        and not critical_regressions
        and meaningful_gain
    )
    evaluation = CandidateEvaluation(
        contract_id=f"evaluation-{assignment.candidate_id}",
        evaluation_id=f"evaluation-{assignment.candidate_id}",
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        input_sha256=candidate_manifest_artifact.sha256,
        source_fingerprint=candidate_plan.source_fingerprint,
        producer="codex_blender_modeler.autonomy.candidate_evaluator",
        producer_version="0.1.0",
        provenance=[
            candidate_manifest_artifact,
            quality_artifact,
            *companion_artifacts,
            *structural_artifacts,
        ],
        created_at=now,
        candidate_id=assignment.candidate_id,
        candidate_manifest=candidate_manifest_artifact,
        baseline_evaluation=assignment.baseline_evaluation,
        scene_spec_v03_candidate=compilation.scene_spec_v03_artifact,
        compiled_scene_spec_candidate=compilation.compiled_scene_spec_artifact,
        structural_recipes=list(compilation.recipe_artifacts),
        structural_mesh_payloads=list(compilation.mesh_payload_artifacts),
        structural_materialization_receipts=list(compilation.materialization_receipts),
        metrics=CandidateMetricVector(
            hard_gate_failures=stage_assessment.hard_gate_failures,
            critical_regressions=len(critical_regressions),
            reference_fidelity=direct_score,
            silhouette_iou=silhouette_iou,
            structural_quality=stage_assessment.structural_quality,
            material_quality=None,
            production_quality=None,
            change_magnitude=candidate_change,
        ),
        evidence_status=stage_assessment.evidence_status,  # type: ignore[arg-type]
        minimum_meaningful_gain=quality_profile.meaningful_gain_min,
        eligible_for_promotion=eligible,
        ranking_reasons=[
            *stage_assessment.reasons,
            "Reference fidelity uses exact V0.6 direct evidence.",
            (
                "Candidate met the minimum meaningful direct-score gain."
                if meaningful_gain
                else "Candidate did not meet the minimum meaningful direct-score gain."
            ),
            "Material and production axes remain unscorable until later phases.",
        ],
        regression_findings=critical_regressions,
    )
    evaluation_path = candidate_root / "candidate_evaluation.json"
    write_immutable_json(root, evaluation_path, evaluation.model_dump(mode="json"))
    return {
        "candidate_id": assignment.candidate_id,
        "candidate_manifest": artifact_for(root, candidate_manifest_path).model_dump(mode="json"),
        "candidate_evaluation": artifact_for(root, evaluation_path).model_dump(mode="json"),
        "integrated_quality_manifest": quality_manifest.model_dump(mode="json"),
        "direct_score": direct_score,
        "direct_gain": direct_gain,
        "silhouette_iou": silhouette_iou,
    }
