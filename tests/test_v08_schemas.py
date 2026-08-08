from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.background_quality.models import (
    BackgroundFitReport,
    BackgroundQualityReport,
    BackgroundRoleMap,
    BackgroundScenePromotionReceipt,
)
from codex_blender_modeler.materials.models import MaterialPromotionReceipt
from codex_blender_modeler.orchestration.models import (
    DestinationRequest,
    DestinationResolution,
    IntentRouting,
    WorkflowApproval,
    WorkflowAttempt,
    WorkflowLock,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowState,
    WorkflowStep,
    WorkflowStepCompletion,
    WorkflowStepState,
)


def test_v08_contract_schemas_are_current_and_strict() -> None:
    """Require every checked-in V0.8 schema to match its strict Pydantic contract."""

    root = Path(__file__).resolve().parents[1]
    contracts = {
        "workflow_request.schema.json": WorkflowRequest,
        "intent_routing.schema.json": IntentRouting,
        "workflow_plan.schema.json": WorkflowPlan,
        "workflow_state.schema.json": WorkflowState,
        "workflow_approval.schema.json": WorkflowApproval,
        "workflow_step_completion.schema.json": WorkflowStepCompletion,
        "workflow_attempt.schema.json": WorkflowAttempt,
        "workflow_lock.schema.json": WorkflowLock,
        "material_promotion_receipt.schema.json": MaterialPromotionReceipt,
        "background_role_map.schema.json": BackgroundRoleMap,
        "background_fit_report.schema.json": BackgroundFitReport,
        "background_scene_promotion_receipt.schema.json": (
            BackgroundScenePromotionReceipt
        ),
        "background_quality_report.schema.json": BackgroundQualityReport,
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.8.0"


def test_v08_policy_fields_are_strict_but_legacy_optional() -> None:
    """Expose fast-lane enums while loading legacy V0.8 evidence without rewrites."""

    now = datetime.now(UTC)
    digest = "0" * 64
    destination = DestinationResolution(
        requested=DestinationRequest(),
        status="not_requested",
        reason="legacy fixture",
    )
    request = WorkflowRequest(
        workflow_id="wf-legacy",
        job_id="legacy_asset",
        raw_request="legacy request",
        requested_scope="proxy_only",
        created_at=now,
    )
    routing = IntentRouting(
        workflow_id="wf-legacy",
        job_id="legacy_asset",
        intent="new_asset",
        confidence=1.0,
        reasons=["legacy fixture"],
        destination=destination,
        routed_at=now,
    )
    step = WorkflowStep(
        step_id="job.created",
        title="Legacy job",
        phase="job",
        execution_mode="host",
        tool_name="create_job",
    )
    plan = WorkflowPlan(
        workflow_id="wf-legacy",
        job_id="legacy_asset",
        request_sha256=digest,
        routing_sha256=digest,
        intent="new_asset",
        scope="proxy_only",
        destination=destination,
        steps=[step],
        terminal_step_id="job.created",
        created_at=now,
    )
    state = WorkflowState(
        workflow_id="wf-legacy",
        job_id="legacy_asset",
        plan_sha256=digest,
        request_sha256=digest,
        status="planned",
        milestone="created",
        current_step_id="job.created",
        steps=[WorkflowStepState(step_id="job.created", status="ready")],
        created_at=now,
        updated_at=now,
    )
    for model, payload in (
        (WorkflowRequest, request.model_dump(mode="json")),
        (IntentRouting, routing.model_dump(mode="json")),
        (WorkflowPlan, plan.model_dump(mode="json")),
        (WorkflowState, state.model_dump(mode="json")),
    ):
        payload.pop("execution_policy")
        payload.pop("delivery_scope")
        if model in {WorkflowRequest, WorkflowPlan, WorkflowState}:
            payload.pop("reference_content_scope")
            payload.pop("target_subject")
        if model is WorkflowRequest:
            payload.pop("fast_quality_policy")
            payload.pop("background_preview_binding")
            payload.pop("revision_strategy")
        if model is WorkflowPlan:
            payload.pop("fast_quality_policy")
        if model is WorkflowState:
            payload.pop("quality_status")
            payload.pop("standard_workflow_recommended")
            payload.pop("quality_report_path")
            payload.pop("quality_report_sha256")
        parsed = model.model_validate(payload)
        assert parsed.execution_policy == "standard"
        assert parsed.delivery_scope is None
        if model in {WorkflowRequest, WorkflowPlan, WorkflowState}:
            assert parsed.reference_content_scope == "full_reference"
            assert parsed.target_subject is None
        if model is WorkflowRequest:
            assert parsed.revision_strategy is None

    request_schema = WorkflowRequest.model_json_schema()["properties"]
    assert request_schema["execution_policy"]["enum"] == [
        "standard",
        "background_exterior",
    ]
    assert request_schema["execution_policy"]["default"] == "standard"
    assert request_schema["delivery_scope"]["anyOf"][0]["enum"] == [
        "preview_only",
        "portable_package",
    ]
    assert request_schema["delivery_scope"]["default"] is None
    assert request_schema["revision_strategy"]["anyOf"][0]["enum"] == [
        "candidate_review",
        "manual_guarded",
    ]
    assert request_schema["revision_strategy"]["default"] is None
    assert request_schema["background_preview_binding"]["default"] is None
    assert request_schema["reference_content_scope"]["enum"] == [
        "primary_object_only",
        "full_reference",
    ]
    assert request_schema["reference_content_scope"]["default"] == "full_reference"
