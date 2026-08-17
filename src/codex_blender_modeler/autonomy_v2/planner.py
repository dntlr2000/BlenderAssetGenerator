"""Plan an opt-in AQ v2 companion session over one immutable standard dispatch."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..analysis.models import ModelingPlan
from ..blender_artifacts import stable_json_digest
from ..integrated_quality.v02_models import IntegratedQualityPolicyV02
from ..production import create_asset_production_dispatch
from ..production.controller_executor import (
    ControllerArtifact,
    ControllerResult,
    build_phase_tool_profile,
)
from ..structural_geometry.models import SceneSpecV03
from ..workspace import job_dir
from .delivery_service import (
    artifact_for_v2,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .models import (
    AQV2Artifact,
    AutonomyBudgetV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    AutonomyStateV2,
    DeliveryProfileId,
    RootAuthorizationV2,
)
from .profiles import PROFILE_STATUS

_PHASE_PROFILE_SPECS: tuple[tuple[str, list[str], list[str]], ...] = (
    ("reference_readonly", ["reference", "workflow-request"], []),
    (
        "geometry_authoring",
        ["reference", "camera", "assignment", "baseline-scene"],
        ["modeling_plan.json", "scene_spec_v03.json", "completion.json"],
    ),
    (
        "material_authoring",
        ["assignment", "scene", "material-baseline", "scale-context"],
        ["material_plan.json", "material_graph.json", "completion.json"],
    ),
    ("quality_readonly", ["quality-input", "camera", "reference"], []),
    ("delivery", ["source-freeze", "delivery-plan"], []),
    ("handoff_plan", ["package", "roundtrip", "material-loss"], []),
    ("admin_audit", ["session-evidence", "receipt-chain"], []),
)


def _session_id() -> str:
    """Create one sortable, portable AQ v2 session identifier."""

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"aqv2-{stamp}-{uuid4().hex[:8]}"


def _sha256_text(value: str) -> str:
    """Hash user text exactly without persisting any absolute source path."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dispatch_purpose(
    *,
    exact_request: str,
    requested_delivery_profiles: list[DeliveryProfileId],
) -> str:
    """Summarize a long exact AQ request without weakening its hash binding."""

    deliveries = ",".join(requested_delivery_profiles)
    return (
        "AQ v2 exact initial request "
        f"sha256={_sha256_text(exact_request)}; "
        "mode=concept; scope=static,primary_object_only; "
        f"deliveries={deliveries}; destination=engine_neutral"
    )


def _controller_artifact(artifact: AQV2Artifact, *, role: str) -> ControllerArtifact:
    """Convert an exact AQ artifact into the controller executor's strict envelope."""

    return ControllerArtifact(
        artifact_id=artifact.artifact_id,
        role=role,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _dispatch_artifact(
    root: Path,
    dispatch_plan: dict[str, object],
    field: str,
    *,
    artifact_id: str,
    kind: str,
) -> AQV2Artifact:
    """Rebind one V0.9 dispatch artifact from disk instead of trusting response bytes."""

    payload = dispatch_plan.get(field)
    if not isinstance(payload, dict) or not isinstance(payload.get("path"), str):
        raise ValueError(f"production dispatch is missing {field}")
    artifact = artifact_for_v2(
        root,
        root / payload["path"],
        artifact_id=artifact_id,
        kind=kind,
    )
    if artifact.sha256 != payload.get("sha256"):
        raise ValueError(f"production dispatch {field} hash is inconsistent")
    return artifact


def _write_phase_profiles(
    *,
    root: Path,
    session_root: Path,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    dispatch_plan_artifact: AQV2Artifact,
    created_at: datetime,
) -> list[AQV2Artifact]:
    """Publish every exact phase tool profile before controller work can be requested."""

    source = _controller_artifact(
        dispatch_plan_artifact,
        role="production-dispatch-plan",
    )
    artifacts: list[AQV2Artifact] = []
    output_root = f"production/autonomy_v2/{session_id}/controller_outputs"
    for profile_id, input_roles, output_names in _PHASE_PROFILE_SPECS:
        allowed_outputs = [
            f"{output_root}/{profile_id}/{name}" for name in output_names
        ]
        profile = build_phase_tool_profile(
            profile_id=profile_id,
            job_id=job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            session_id=session_id,
            source_artifact=source,
            allowed_input_roles=input_roles,
            allowed_output_paths=allowed_outputs,
            created_at=created_at,
            supporting_client_enforced=False,
        )
        artifacts.append(
            write_immutable_v2_model(
                root,
                session_root / "tool_profiles" / f"{profile_id}.json",
                profile,
            )
        )
    return artifacts


def plan_autonomous_static_prop_v2(
    request: str,
    *,
    reference_path: str | Path,
    target_subject: str,
    requested_delivery_profiles: list[DeliveryProfileId],
    job_id: str | None = None,
    controller_execution_mode: str = "desktop_in_session",
    destination_hint: str = "engine_neutral",
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Create a standard, object-only v2 session without granting later approvals."""

    exact_request = str(request)
    normalized_request = exact_request.strip()
    normalized_target = target_subject.strip()
    if not normalized_request or not normalized_target:
        raise ValueError("AQ v2 requires non-empty request text and target_subject")
    if not requested_delivery_profiles:
        raise ValueError("AQ v2 requires at least one requested delivery profile")
    if len(requested_delivery_profiles) != len(set(requested_delivery_profiles)):
        raise ValueError("AQ v2 requested delivery profiles must be unique")
    if "review_only" in requested_delivery_profiles and len(
        requested_delivery_profiles
    ) > 1:
        raise ValueError("review_only cannot be combined with portable delivery")
    if controller_execution_mode not in {"desktop_in_session", "client_mediated"}:
        raise ValueError("unsupported AQ v2 controller execution mode")
    if destination_hint not in {
        "engine_neutral",
        "unity_urp",
        "unity_hdrp",
        "custom_unverified",
    }:
        raise ValueError("unsupported AQ v2 destination hint")
    if PROFILE_STATUS != "verified_active" and not allow_disabled_experimental:
        raise PermissionError("autonomous_static_prop_v2 is disabled_experimental")

    production = create_asset_production_dispatch(
        normalized_request,
        reference_path=reference_path,
        purpose=_dispatch_purpose(
            exact_request=exact_request,
            requested_delivery_profiles=requested_delivery_profiles,
        ),
        job_id=job_id,
        mode="concept",
        reference_content_scope="primary_object_only",
        target_subject=normalized_target,
        execution_policy="standard",
        controller_execution_mode=controller_execution_mode,
        profile_id="portable_gltf",
        destination_kind="engine_neutral",
        include_destination_handoff=False,
        max_qa_iterations=1,
        external_provider_budget=0,
        convergence_mode="bounded_after_v06",
        convergence_target_direct_score=0.85,
        convergence_target_silhouette_iou=0.8,
        convergence_minimum_iteration_gain=0.001,
        convergence_minimum_candidate_confidence=0.8,
        convergence_max_iterations=3,
    )
    dispatch_plan = production.get("dispatch_plan")
    if not isinstance(dispatch_plan, dict):
        raise RuntimeError("production dispatcher returned no strict dispatch plan")
    created_job_id = str(dispatch_plan["job_id"])
    workflow_id = str(dispatch_plan["workflow_id"])
    dispatch_id = str(dispatch_plan["dispatch_id"])
    root = job_dir(created_job_id)
    session_id = _session_id()
    session_root = root / "production" / "autonomy_v2" / session_id
    session_root.mkdir(parents=True, exist_ok=False)
    created_at = datetime.now(UTC)

    dispatch_plan_artifact = artifact_for_v2(
        root,
        root / "production" / "dispatches" / dispatch_id / "dispatch_plan.json",
        artifact_id=f"dispatch-plan-{dispatch_id}",
        kind="production_dispatch_plan",
    )
    controller_plan_artifact = _dispatch_artifact(
        root,
        dispatch_plan,
        "controller_plan",
        artifact_id=f"controller-plan-{dispatch_id}",
        kind="production_controller_plan",
    )
    launch_artifact = _dispatch_artifact(
        root,
        dispatch_plan,
        "launch_manifest",
        artifact_id=f"launch-{dispatch_id}",
        kind="production_launch_manifest",
    )
    workflow_request_artifact = _dispatch_artifact(
        root,
        dispatch_plan,
        "workflow_request",
        artifact_id=f"workflow-request-{workflow_id}",
        kind="workflow_request",
    )
    workflow_request_path = validate_v2_artifact(root, workflow_request_artifact)
    workflow_request = json.loads(workflow_request_path.read_text(encoding="utf-8"))
    primary_payload = workflow_request.get("primary_reference")
    if not isinstance(primary_payload, dict) or not isinstance(
        primary_payload.get("path"), str
    ):
        raise RuntimeError("standard workflow has no exact primary reference")
    primary_reference = artifact_for_v2(
        root,
        root / primary_payload["path"],
        artifact_id=f"primary-reference-{session_id}",
        kind="primary_reference",
    )
    if primary_reference.sha256 != primary_payload.get("sha256"):
        raise RuntimeError("standard workflow primary reference hash is inconsistent")

    quality_policy = IntegratedQualityPolicyV02(
        profile_id="autonomous_static_prop_v2",
        lexicographic_metric_priority=[
            "hard_gate_status",
            "critical_semantic_iou",
            "contour_boundary_f_score",
            "minimum_change",
        ],
    )
    quality_policy_artifact = write_immutable_v2_model(
        root,
        session_root / "integrated_quality_policy.json",
        quality_policy,
    )
    phase_profiles = _write_phase_profiles(
        root=root,
        session_root=session_root,
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        dispatch_plan_artifact=dispatch_plan_artifact,
        created_at=created_at,
    )
    budget_input = {
        "dispatch_plan": dispatch_plan_artifact.sha256,
        "quality_policy": quality_policy_artifact.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
    }
    budget = AutonomyBudgetV2(
        contract_id=f"budget-{session_id}",
        budget_id=f"budget-{session_id}",
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(budget_input),
        source_fingerprint=stable_json_digest(
            {**budget_input, "profile": "autonomous_static_prop_v2"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[dispatch_plan_artifact, quality_policy_artifact, *phase_profiles],
        created_at=created_at,
        delivery_runs=sum(
            profile != "review_only" for profile in requested_delivery_profiles
        ),
    )
    budget_artifact = write_immutable_v2_model(
        root,
        session_root / "budget.json",
        budget,
    )
    profile_input = {
        "budget": budget_artifact.sha256,
        "quality_policy": quality_policy_artifact.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
    }
    profile = AutonomyProfileV2(
        contract_id=f"profile-{session_id}",
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(profile_input),
        source_fingerprint=stable_json_digest(
            {**profile_input, "status": PROFILE_STATUS}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[budget_artifact, quality_policy_artifact, *phase_profiles],
        created_at=created_at,
        status=PROFILE_STATUS,
        allowed_asset_kinds=["static_hard_surface", "static_prop"],
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        prohibited_capabilities=[
            "interior",
            "measured_or_blueprint",
            "rig",
            "skinning",
            "animation",
            "gameplay",
            "external_network_provider",
            "arbitrary_blender_python",
            "arbitrary_node_graph",
            "destination_project_write",
            "synthetic_user_approval",
        ],
    )
    profile_artifact = write_immutable_v2_model(
        root,
        session_root / "profile.json",
        profile,
    )
    authorization_inputs = {
        "request": _sha256_text(exact_request),
        "primary_reference": primary_reference.sha256,
        "profile": profile_artifact.sha256,
        "budget": budget_artifact.sha256,
        "launch": launch_artifact.sha256,
        "quality_policy": quality_policy_artifact.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
        "requested_deliveries": requested_delivery_profiles,
        "target_subject": normalized_target,
    }
    root_authorization = RootAuthorizationV2(
        contract_id=f"authorization-{session_id}",
        authorization_id=f"authorization-{session_id}",
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(authorization_inputs),
        source_fingerprint=stable_json_digest(
            {**authorization_inputs, "destination_hint": destination_hint}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[
            primary_reference,
            workflow_request_artifact,
            profile_artifact,
            budget_artifact,
            launch_artifact,
            quality_policy_artifact,
            *phase_profiles,
        ],
        created_at=created_at,
        original_request_sha256=_sha256_text(exact_request),
        primary_reference=primary_reference,
        profile=profile_artifact,
        budget=budget_artifact,
        production_launch_or_binding=launch_artifact,
        target_subject=normalized_target,
        quality_profile=quality_policy_artifact,
        phase_tool_profiles=phase_profiles,
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        requested_delivery_profiles=requested_delivery_profiles,
        destination_hint=destination_hint,
        prohibited_scopes=list(profile.prohibited_capabilities),
    )
    authorization_artifact = write_immutable_v2_model(
        root,
        session_root / "root_authorization.json",
        root_authorization,
    )
    plan_inputs = {
        "profile": profile_artifact.sha256,
        "authorization": authorization_artifact.sha256,
        "budget": budget_artifact.sha256,
        "dispatch": dispatch_plan_artifact.sha256,
        "controller": controller_plan_artifact.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
    }
    plan = AutonomyPlanV2(
        contract_id=f"plan-{session_id}",
        plan_id=f"plan-{session_id}",
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(plan_inputs),
        source_fingerprint=stable_json_digest(
            {**plan_inputs, "requested_deliveries": requested_delivery_profiles}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[
            profile_artifact,
            authorization_artifact,
            budget_artifact,
            dispatch_plan_artifact,
            controller_plan_artifact,
            *phase_profiles,
        ],
        created_at=created_at,
        profile=profile_artifact,
        root_authorization=authorization_artifact,
        budget=budget_artifact,
        production_dispatch_plan=dispatch_plan_artifact,
        production_controller_plan=controller_plan_artifact,
        phase_tool_profiles=phase_profiles,
        requested_delivery_profiles=requested_delivery_profiles,
        action_limit=budget.global_action_limit,
    )
    plan_artifact = write_immutable_v2_model(
        root,
        session_root / "plan.json",
        plan,
    )
    state = AutonomyStateV2(
        contract_id=f"state-{session_id}-0000",
        state_id=f"state-{session_id}-0000",
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest({"plan": plan_artifact.sha256, "sequence": 0}),
        source_fingerprint=stable_json_digest(
            {"plan": plan_artifact.sha256, "status": "planned"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[plan_artifact],
        created_at=created_at,
        plan=plan_artifact,
        sequence=0,
        phase="planned",
        status="planned",
        next_action="collect_reference",
    )
    state_artifact = write_immutable_v2_model(
        root,
        session_root / "states" / "0000.json",
        state,
    )
    return {
        "profile_status": PROFILE_STATUS,
        "experimental_override_used": allow_disabled_experimental,
        "job_id": created_job_id,
        "workflow_id": workflow_id,
        "dispatch_id": dispatch_id,
        "session_id": session_id,
        "profile": profile.model_dump(mode="json"),
        "root_authorization": root_authorization.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "artifacts": {
            "profile": profile_artifact.model_dump(mode="json"),
            "budget": budget_artifact.model_dump(mode="json"),
            "root_authorization": authorization_artifact.model_dump(mode="json"),
            "plan": plan_artifact.model_dump(mode="json"),
            "state": state_artifact.model_dump(mode="json"),
        },
        "task_created_by_repository": False,
        "automatic_user_approval": False,
        "destination_project_write": False,
    }


def plan_geometry_repair_session_v2(
    approval_request: str,
    *,
    job_id: str,
    source_session_id: str,
    source_state_sha256: str,
    source_controller_result_sha256: str,
    source_modeling_plan_sha256: str,
    source_scene_spec_v03_sha256: str,
    reference_sha256: str,
    target_material_changes: dict[str, tuple[str, str]],
    allow_disabled_experimental: bool = False,
) -> dict[str, object]:
    """Plan one append-only pre-canonical geometry repair bound to exact source evidence."""

    exact_request = str(approval_request)
    if not exact_request.strip():
        raise ValueError("AQ v2 geometry repair requires the exact approval request")
    if PROFILE_STATUS != "verified_active" and not allow_disabled_experimental:
        raise PermissionError("autonomous_static_prop_v2 is disabled_experimental")
    if not target_material_changes:
        raise ValueError("AQ v2 geometry repair requires at least one exact binding change")
    root = job_dir(job_id)
    source_root = root / "production" / "autonomy_v2" / source_session_id
    if not source_root.is_dir():
        raise FileNotFoundError("AQ v2 geometry repair source session does not exist")
    source_plan_path = source_root / "plan.json"
    source_plan = AutonomyPlanV2.model_validate_json(source_plan_path.read_bytes())
    source_authorization = RootAuthorizationV2.model_validate_json(
        (root / source_plan.root_authorization.path).read_bytes()
    )
    if (
        source_plan.job_id != job_id
        or source_plan.session_id != source_session_id
        or source_authorization.job_id != job_id
        or source_authorization.session_id != source_session_id
    ):
        raise ValueError("AQ v2 geometry repair source identity is inconsistent")
    state_paths = sorted((source_root / "states").glob("*.json"))
    if not state_paths:
        raise FileNotFoundError("AQ v2 geometry repair source has no state chain")
    source_state_path = state_paths[-1]
    source_state_artifact = artifact_for_v2(
        root,
        source_state_path,
        artifact_id=f"repair-source-state-{source_session_id}",
        kind="autonomy_v2_state",
    )
    if source_state_artifact.sha256 != source_state_sha256:
        raise ValueError("AQ v2 geometry repair source state hash differs from approval")
    source_state = AutonomyStateV2.model_validate_json(source_state_path.read_bytes())
    if (
        source_state.session_id != source_session_id
        or source_state.next_action != "validate_candidate"
        or not source_state.provenance
    ):
        raise PermissionError("AQ v2 geometry repair source is not a failed candidate boundary")
    source_result_artifact = source_state.provenance[-1]
    source_result_path = root / source_result_artifact.path
    observed_result = artifact_for_v2(
        root,
        source_result_path,
        artifact_id=source_result_artifact.artifact_id,
        kind=source_result_artifact.kind,
    )
    if (
        observed_result.sha256 != source_controller_result_sha256
        or observed_result.sha256 != source_result_artifact.sha256
    ):
        raise ValueError("AQ v2 geometry repair controller result hash differs from approval")
    source_result = ControllerResult.model_validate_json(source_result_path.read_bytes())
    if source_result.status != "completed" or not source_result.canonical_unchanged:
        raise PermissionError("AQ v2 geometry repair requires one isolated completed result")
    output_by_name = {Path(item.path).name: item for item in source_result.outputs}
    if set(output_by_name) != {
        "modeling_plan.json",
        "scene_spec_v03.json",
        "completion.json",
    }:
        raise ValueError("AQ v2 geometry repair source result has unexpected outputs")
    source_modeling_artifact = artifact_for_v2(
        root,
        root / output_by_name["modeling_plan.json"].path,
        artifact_id="repair-source-modeling-plan",
        kind="baseline-scene",
    )
    source_scene_artifact = artifact_for_v2(
        root,
        root / output_by_name["scene_spec_v03.json"].path,
        artifact_id="repair-source-scene-v03",
        kind="baseline-scene",
    )
    if source_modeling_artifact.sha256 != source_modeling_plan_sha256:
        raise ValueError("AQ v2 geometry repair ModelingPlan hash differs from approval")
    if source_scene_artifact.sha256 != source_scene_spec_v03_sha256:
        raise ValueError("AQ v2 geometry repair SceneSpecV03 hash differs from approval")
    modeling = ModelingPlan.model_validate_json(
        (root / source_modeling_artifact.path).read_bytes()
    )
    scene = SceneSpecV03.model_validate_json((root / source_scene_artifact.path).read_bytes())
    detail_by_id = {item.id: item for item in modeling.surface_details}
    object_by_id = {item.id: item for item in scene.objects}
    for detail_id, (before_material, after_material) in target_material_changes.items():
        detail = detail_by_id.get(detail_id)
        if detail is None or detail.target_material_id != before_material:
            raise ValueError(f"AQ v2 geometry repair source detail differs: {detail_id}")
        parent = object_by_id.get(detail.parent_object_id)
        if parent is None or parent.material_id != after_material:
            raise ValueError(f"AQ v2 geometry repair parent material differs: {detail_id}")
        if before_material == after_material:
            raise ValueError(f"AQ v2 geometry repair change is vacuous: {detail_id}")
    primary_reference = source_authorization.primary_reference
    validate_v2_artifact(root, primary_reference)
    if primary_reference.sha256 != reference_sha256:
        raise ValueError("AQ v2 geometry repair reference hash differs from approval")
    workflow_request = source_authorization.provenance[1]
    validate_v2_artifact(root, workflow_request)
    for artifact in (
        source_plan.production_dispatch_plan,
        source_plan.production_controller_plan,
        source_authorization.production_launch_or_binding,
    ):
        validate_v2_artifact(root, artifact)

    session_id = _session_id()
    session_root = root / "production" / "autonomy_v2" / session_id
    session_root.mkdir(parents=True, exist_ok=False)
    created_at = datetime.now(UTC)
    approval_path = session_root / "repair_approval.txt"
    with approval_path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(exact_request)
    approval_artifact = artifact_for_v2(
        root,
        approval_path,
        artifact_id=f"repair-approval-{session_id}",
        kind="geometry_repair_approval",
    )
    if approval_artifact.sha256 != _sha256_text(exact_request):
        raise RuntimeError("AQ v2 geometry repair approval bytes changed while writing")
    quality_policy = IntegratedQualityPolicyV02(
        profile_id="autonomous_static_prop_v2",
        lexicographic_metric_priority=[
            "hard_gate_status",
            "critical_semantic_iou",
            "contour_boundary_f_score",
            "minimum_change",
        ],
    )
    quality_policy_artifact = write_immutable_v2_model(
        root,
        session_root / "integrated_quality_policy.json",
        quality_policy,
    )
    phase_profiles = _write_phase_profiles(
        root=root,
        session_root=session_root,
        job_id=job_id,
        workflow_id=source_plan.workflow_id,
        dispatch_id=source_plan.dispatch_id,
        session_id=session_id,
        dispatch_plan_artifact=source_plan.production_dispatch_plan,
        created_at=created_at,
    )
    budget_input = {
        "dispatch_plan": source_plan.production_dispatch_plan.sha256,
        "quality_policy": quality_policy_artifact.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
    }
    budget = AutonomyBudgetV2(
        contract_id=f"budget-{session_id}",
        budget_id=f"budget-{session_id}",
        job_id=job_id,
        workflow_id=source_plan.workflow_id,
        dispatch_id=source_plan.dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(budget_input),
        source_fingerprint=stable_json_digest(
            {**budget_input, "profile": "autonomous_static_prop_v2"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[
            source_plan.production_dispatch_plan,
            quality_policy_artifact,
            *phase_profiles,
        ],
        created_at=created_at,
        delivery_runs=0,
    )
    budget_artifact = write_immutable_v2_model(root, session_root / "budget.json", budget)
    profile_input = {
        "budget": budget_artifact.sha256,
        "quality_policy": quality_policy_artifact.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
    }
    profile = AutonomyProfileV2(
        contract_id=f"profile-{session_id}",
        job_id=job_id,
        workflow_id=source_plan.workflow_id,
        dispatch_id=source_plan.dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(profile_input),
        source_fingerprint=stable_json_digest(
            {**profile_input, "status": PROFILE_STATUS}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[budget_artifact, quality_policy_artifact, *phase_profiles],
        created_at=created_at,
        status=PROFILE_STATUS,
        allowed_asset_kinds=["static_hard_surface", "static_prop"],
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        prohibited_capabilities=[
            "interior",
            "measured_or_blueprint",
            "rig",
            "skinning",
            "animation",
            "gameplay",
            "external_network_provider",
            "arbitrary_blender_python",
            "arbitrary_node_graph",
            "destination_project_write",
            "synthetic_user_approval",
        ],
    )
    profile_artifact = write_immutable_v2_model(
        root,
        session_root / "profile.json",
        profile,
    )
    requested_delivery_profiles: list[DeliveryProfileId] = ["review_only"]
    authorization_inputs = {
        "request": _sha256_text(exact_request),
        "primary_reference": primary_reference.sha256,
        "profile": profile_artifact.sha256,
        "budget": budget_artifact.sha256,
        "launch": source_authorization.production_launch_or_binding.sha256,
        "quality_policy": quality_policy_artifact.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
        "requested_deliveries": requested_delivery_profiles,
        "target_subject": source_authorization.target_subject,
    }
    root_authorization = RootAuthorizationV2(
        contract_id=f"authorization-{session_id}",
        authorization_id=f"authorization-{session_id}",
        job_id=job_id,
        workflow_id=source_plan.workflow_id,
        dispatch_id=source_plan.dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(authorization_inputs),
        source_fingerprint=stable_json_digest(
            {
                **authorization_inputs,
                "destination_hint": source_authorization.destination_hint,
            }
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[
            primary_reference,
            workflow_request,
            profile_artifact,
            budget_artifact,
            source_authorization.production_launch_or_binding,
            quality_policy_artifact,
            *phase_profiles,
        ],
        created_at=created_at,
        original_request_sha256=_sha256_text(exact_request),
        primary_reference=primary_reference,
        profile=profile_artifact,
        budget=budget_artifact,
        production_launch_or_binding=source_authorization.production_launch_or_binding,
        target_subject=source_authorization.target_subject,
        quality_profile=quality_policy_artifact,
        phase_tool_profiles=phase_profiles,
        allowed_delivery_profiles=["review_only", "portable_gltf", "portable_fbx"],
        requested_delivery_profiles=requested_delivery_profiles,
        destination_hint=source_authorization.destination_hint,
        prohibited_scopes=list(profile.prohibited_capabilities),
    )
    authorization_artifact = write_immutable_v2_model(
        root,
        session_root / "root_authorization.json",
        root_authorization,
    )
    plan_inputs = {
        "profile": profile_artifact.sha256,
        "authorization": authorization_artifact.sha256,
        "budget": budget_artifact.sha256,
        "dispatch": source_plan.production_dispatch_plan.sha256,
        "controller": source_plan.production_controller_plan.sha256,
        "phase_profiles": [item.sha256 for item in phase_profiles],
    }
    plan = AutonomyPlanV2(
        contract_id=f"plan-{session_id}",
        plan_id=f"plan-{session_id}",
        job_id=job_id,
        workflow_id=source_plan.workflow_id,
        dispatch_id=source_plan.dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(plan_inputs),
        source_fingerprint=stable_json_digest(
            {**plan_inputs, "requested_deliveries": requested_delivery_profiles}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[
            profile_artifact,
            authorization_artifact,
            budget_artifact,
            source_plan.production_dispatch_plan,
            source_plan.production_controller_plan,
            *phase_profiles,
        ],
        created_at=created_at,
        profile=profile_artifact,
        root_authorization=authorization_artifact,
        budget=budget_artifact,
        production_dispatch_plan=source_plan.production_dispatch_plan,
        production_controller_plan=source_plan.production_controller_plan,
        phase_tool_profiles=phase_profiles,
        requested_delivery_profiles=requested_delivery_profiles,
        action_limit=budget.global_action_limit,
    )
    plan_artifact = write_immutable_v2_model(root, session_root / "plan.json", plan)
    state = AutonomyStateV2(
        contract_id=f"state-{session_id}-0000",
        state_id=f"state-{session_id}-0000",
        job_id=job_id,
        workflow_id=source_plan.workflow_id,
        dispatch_id=source_plan.dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest({"plan": plan_artifact.sha256, "sequence": 0}),
        source_fingerprint=stable_json_digest(
            {"plan": plan_artifact.sha256, "status": "planned"}
        ),
        producer="codex_blender_modeler.autonomy_v2.planner",
        provenance=[plan_artifact],
        created_at=created_at,
        plan=plan_artifact,
        sequence=0,
        phase="planned",
        status="planned",
        next_action="collect_reference",
    )
    state_artifact = write_immutable_v2_model(
        root,
        session_root / "states" / "0000.json",
        state,
    )
    return {
        "profile_status": PROFILE_STATUS,
        "experimental_override_used": allow_disabled_experimental,
        "job_id": job_id,
        "workflow_id": source_plan.workflow_id,
        "dispatch_id": source_plan.dispatch_id,
        "session_id": session_id,
        "source_session_id": source_session_id,
        "repair_approval": approval_artifact.model_dump(mode="json"),
        "source_state": source_state_artifact.model_dump(mode="json"),
        "source_controller_result": observed_result.model_dump(mode="json"),
        "source_modeling_plan": source_modeling_artifact.model_dump(mode="json"),
        "source_scene_spec_v03": source_scene_artifact.model_dump(mode="json"),
        "target_material_changes": {
            key: {"before": value[0], "after": value[1]}
            for key, value in sorted(target_material_changes.items())
        },
        "artifacts": {
            "profile": profile_artifact.model_dump(mode="json"),
            "budget": budget_artifact.model_dump(mode="json"),
            "root_authorization": authorization_artifact.model_dump(mode="json"),
            "plan": plan_artifact.model_dump(mode="json"),
            "state": state_artifact.model_dump(mode="json"),
        },
        "material_imagegen_delivery_disabled": True,
        "automatic_user_approval": False,
        "destination_project_write": False,
    }
