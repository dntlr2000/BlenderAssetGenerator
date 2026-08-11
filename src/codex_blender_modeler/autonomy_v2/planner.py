"""Plan an opt-in AQ v2 companion session over one immutable standard dispatch."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..blender_artifacts import stable_json_digest
from ..integrated_quality.v02_models import IntegratedQualityPolicyV02
from ..production import create_asset_production_dispatch
from ..production.controller_executor import (
    ControllerArtifact,
    build_phase_tool_profile,
)
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
        purpose=normalized_request,
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
