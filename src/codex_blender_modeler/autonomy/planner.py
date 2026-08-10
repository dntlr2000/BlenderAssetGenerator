"""Create a bounded autonomy session over one new standard production dispatch."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_artifacts import stable_json_digest
from ..production import create_asset_production_dispatch
from ..workspace import job_dir
from .authorization import artifact_for, canonical_digest, create_root_authorization
from .io import ensure_autonomy_path, write_immutable_json, write_mutable_projection
from .models import (
    AutonomyArtifact,
    AutonomyControllerBinding,
    AutonomyPlan,
    AutonomyState,
    BudgetUsage,
)
from .profiles import build_default_budget, build_profile_snapshot


def _session_id() -> str:
    """Create a sortable portable autonomy session identifier."""

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ").lower()
    return f"aq-{stamp}-{uuid4().hex[:8]}"


def _write_model(root: Path, path: Path, model: Any) -> AutonomyArtifact:
    """Publish one strict model and return its exact job-relative artifact binding."""

    write_immutable_json(root, path, model.model_dump(mode="json"))
    return artifact_for(root, path)


def _quality_profile(
    *,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    source_fingerprint: str,
    primary_reference: AutonomyArtifact,
    workflow_request: AutonomyArtifact,
    created_at: datetime,
) -> Any:
    """Construct the Integrated Quality default without a module-level dependency cycle."""

    from ..integrated_quality import (
        ProducerIdentity,
        QualityArtifact,
        build_default_quality_gate_profile,
    )

    input_producer = ProducerIdentity(
        name="autonomy-planner-input",
        version="0.1.0",
    )

    return build_default_quality_gate_profile(
        profile_id="autonomous-static-prop-v1",
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        source_fingerprint=source_fingerprint,
        producer=ProducerIdentity(
            name="autonomy-planner",
            version="0.1.0",
        ),
        provenance=[
            QualityArtifact(
                artifact_id="autonomy-primary-reference",
                kind="reference",
                relative_path=primary_reference.path,
                sha256=primary_reference.sha256,
                producer=input_producer,
                produced_at=created_at,
            ),
            QualityArtifact(
                artifact_id="autonomy-workflow-request",
                kind="workflow-request",
                relative_path=workflow_request.path,
                sha256=workflow_request.sha256,
                producer=input_producer,
                produced_at=created_at,
            ),
        ],
        created_at=created_at,
    )


def plan_autonomous_static_prop(
    request: str,
    *,
    reference_path: str | Path,
    target_subject: str,
    job_id: str | None = None,
    controller_execution_mode: str = "desktop_in_session",
    include_destination_handoff_envelope: bool = False,
    initial_candidate_limit: int = 3,
) -> dict[str, Any]:
    """Plan one primary-object-only static-prop session on a new standard workflow."""

    exact_request = str(request)
    normalized_request = exact_request.strip()
    normalized_target = target_subject.strip()
    if not normalized_request:
        raise ValueError("Autonomy request text must not be empty")
    if not normalized_target:
        raise ValueError("autonomous_static_prop_v1 requires target_subject")
    if controller_execution_mode not in {"desktop_in_session", "client_mediated"}:
        raise ValueError("Unsupported autonomy controller execution mode")
    if initial_candidate_limit < 1 or initial_candidate_limit > 3:
        raise ValueError("verified profile initial_candidate_limit must be within 1..3")

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
        include_destination_handoff=include_destination_handoff_envelope,
        max_qa_iterations=1,
        external_provider_budget=0,
    )
    dispatch_plan_payload = production["dispatch_plan"]
    created_job_id = str(dispatch_plan_payload["job_id"])
    workflow_id = str(dispatch_plan_payload["workflow_id"])
    dispatch_id = str(dispatch_plan_payload["dispatch_id"])
    controller_id = str(dispatch_plan_payload["controller_id"])
    root = job_dir(created_job_id)
    dispatch_root = root / "production" / "dispatches" / dispatch_id
    session_id = _session_id()
    session_root = ensure_autonomy_path(
        root,
        root / "production" / "autonomy" / session_id,
        must_exist=False,
    )
    session_root.mkdir(parents=True, exist_ok=False)
    session_root = ensure_autonomy_path(root, session_root, must_exist=True)
    now = datetime.now(UTC)

    launch_artifact = artifact_for(root, dispatch_root / "task_launch_manifest.json")
    controller_artifact = artifact_for(root, dispatch_root / "controller_plan.json")
    dispatch_plan_artifact = artifact_for(root, dispatch_root / "dispatch_plan.json")
    primary = dispatch_plan_payload["workflow_request"]
    workflow_request_path = root / str(primary["path"])
    workflow_request_payload = json.loads(
        workflow_request_path.read_text(encoding="utf-8")
    )
    primary_reference = workflow_request_payload["primary_reference"]
    primary_reference_artifact = AutonomyArtifact(
        path=str(primary_reference["path"]),
        sha256=str(primary_reference["sha256"]),
    )
    workflow_request_artifact = artifact_for(root, workflow_request_path)

    quality_profile = _quality_profile(
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        source_fingerprint=stable_json_digest(
            {
                "primary_reference": primary_reference_artifact.model_dump(mode="json"),
                "workflow_request": workflow_request_artifact.sha256,
            }
        ),
        primary_reference=primary_reference_artifact,
        workflow_request=workflow_request_artifact,
        created_at=now,
    )
    quality_profile_artifact = _write_model(
        root,
        session_root / "quality_gate_profile.json",
        quality_profile,
    )
    budget = build_default_budget(
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        source_artifact=quality_profile_artifact,
        created_at=now,
    )
    budget_path = session_root / "budget.json"
    budget_artifact = _write_model(root, budget_path, budget)
    profile = build_profile_snapshot(
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        budget=budget,
        budget_artifact=budget_artifact,
        quality_gate_profile=quality_profile_artifact,
        created_at=now,
    )
    profile_artifact = _write_model(root, session_root / "profile.json", profile)
    root_authorization = create_root_authorization(
        request_text=exact_request,
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        launch_or_binding=launch_artifact,
        primary_reference=primary_reference_artifact,
        profile_artifact=profile_artifact,
        profile=profile,
        budget_artifact=budget_artifact,
        target_subject=normalized_target,
        created_at=now,
    )
    root_authorization_artifact = _write_model(
        root,
        session_root / "root_authorization.json",
        root_authorization,
    )
    plan_inputs = {
        "dispatch_plan": dispatch_plan_artifact.sha256,
        "profile": profile_artifact.sha256,
        "budget": budget_artifact.sha256,
        "root_authorization": root_authorization_artifact.sha256,
    }
    plan = AutonomyPlan(
        contract_id=f"plan-{session_id}",
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=stable_json_digest(plan_inputs),
        source_fingerprint=stable_json_digest(
            {**plan_inputs, "target_subject": normalized_target}
        ),
        producer="codex_blender_modeler.autonomy.planner",
        producer_version="0.1.0",
        provenance=[
            dispatch_plan_artifact,
            controller_artifact,
            profile_artifact,
            budget_artifact,
            root_authorization_artifact,
        ],
        created_at=now,
        session_id=session_id,
        profile=profile_artifact,
        budget=budget_artifact,
        root_authorization=root_authorization_artifact,
        production_dispatch_plan=dispatch_plan_artifact,
        production_controller_plan=controller_artifact,
        target_subject=normalized_target,
        include_destination_handoff_envelope=include_destination_handoff_envelope,
        initial_candidate_limit=initial_candidate_limit,
        action_limit=budget.global_action_limit,
    )
    plan_artifact = _write_model(root, session_root / "plan.json", plan)

    binding: AutonomyControllerBinding | None = None
    binding_artifact: AutonomyArtifact | None = None
    if controller_execution_mode == "desktop_in_session":
        binding = AutonomyControllerBinding(
            contract_id=f"binding-{session_id}",
            binding_id=f"binding-{session_id}",
            job_id=created_job_id,
            workflow_id=workflow_id,
            dispatch_id=dispatch_id,
            input_sha256=stable_json_digest(
                {
                    "launch": launch_artifact.sha256,
                    "controller": controller_artifact.sha256,
                }
            ),
            source_fingerprint=stable_json_digest(
                {"plan": plan_artifact.sha256, "controller_id": controller_id}
            ),
            producer="codex_blender_modeler.autonomy.planner",
            producer_version="0.1.0",
            provenance=[launch_artifact, controller_artifact, plan_artifact],
            created_at=now,
            session_id=session_id,
            controller_id=controller_id,
            production_launch=launch_artifact,
            production_controller_plan=controller_artifact,
            execution_mode="desktop_in_session",
            bound_at=now,
        )
        binding_artifact = _write_model(
            root,
            session_root / "controller_binding.json",
            binding,
        )

    state_provenance = [plan_artifact]
    if binding_artifact is not None:
        state_provenance.append(binding_artifact)
    state = AutonomyState(
        contract_id=f"state-{session_id}-0000",
        job_id=created_job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        input_sha256=plan_artifact.sha256,
        source_fingerprint=canonical_digest(
            {
                "plan": plan_artifact.sha256,
                "binding": binding_artifact.sha256 if binding_artifact else None,
            }
        ),
        producer="codex_blender_modeler.autonomy.planner",
        producer_version="0.1.0",
        provenance=state_provenance,
        created_at=now,
        session_id=session_id,
        root_authorization=root_authorization_artifact,
        profile=profile_artifact,
        budget=budget_artifact,
        status="planned",
        phase="reference_evidence",
        next_action="collect_reference_evidence",
        action_sequence=0,
        budget_usage=BudgetUsage(),
        observed_at=now,
    )
    state_path = session_root / "transitions" / "0000" / "state.json"
    state_artifact = _write_model(root, state_path, state)
    write_mutable_projection(root, session_root / "state.json", state.model_dump(mode="json"))
    return {
        "job_id": created_job_id,
        "workflow_id": workflow_id,
        "dispatch_id": dispatch_id,
        "controller_id": controller_id,
        "session_id": session_id,
        "plan_path": plan_artifact.path,
        "plan_sha256": plan_artifact.sha256,
        "root_authorization_path": root_authorization_artifact.path,
        "root_authorization_sha256": root_authorization_artifact.sha256,
        "controller_binding": (
            binding_artifact.model_dump(mode="json") if binding_artifact else None
        ),
        "state_path": state_artifact.path,
        "state_sha256": state_artifact.sha256,
        "production": production,
    }
