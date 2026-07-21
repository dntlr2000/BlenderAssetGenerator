from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.orchestration.models import (
    IntentRouting,
    WorkflowApproval,
    WorkflowAttempt,
    WorkflowLock,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowState,
    WorkflowStepCompletion,
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
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.8.0"
