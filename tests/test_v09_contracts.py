from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.handoff.models import (
    AssemblyManifest,
    DestinationContext,
    DestinationHandoffManifest,
    DestinationHandoffPlan,
    DestinationHandoffValidation,
    DestinationImportPlan,
    DestinationImportReceipt,
    DestinationImportValidation,
    HandoffReportManifest,
    ImportChecklist,
    MaterialMappingManifest,
)
from codex_blender_modeler.stabilization.archive_models import (
    WorkspaceRelocationPlan,
    WorkspaceRelocationReceipt,
)
from codex_blender_modeler.stabilization.models import (
    EnvironmentProbeReport,
    LocalWorkflowQueue,
    QueueAttemptReceipt,
    QueueLock,
    StabilityReportManifest,
    WorkspaceAuditReport,
)


def test_v09_contract_schemas_are_current_and_strict() -> None:
    """Require every checked-in V0.9 schema to match its strict Pydantic contract."""

    root = Path(__file__).resolve().parents[1]
    contracts = {
        "environment_probe.schema.json": EnvironmentProbeReport,
        "workspace_audit.schema.json": WorkspaceAuditReport,
        "workspace_relocation_plan.schema.json": WorkspaceRelocationPlan,
        "workspace_relocation_receipt.schema.json": WorkspaceRelocationReceipt,
        "local_workflow_queue.schema.json": LocalWorkflowQueue,
        "queue_attempt_receipt.schema.json": QueueAttemptReceipt,
        "queue_lock.schema.json": QueueLock,
        "stability_report_manifest.schema.json": StabilityReportManifest,
        "destination_handoff_plan.schema.json": DestinationHandoffPlan,
        "destination_context.schema.json": DestinationContext,
        "assembly_manifest.schema.json": AssemblyManifest,
        "material_mapping.schema.json": MaterialMappingManifest,
        "import_checklist.schema.json": ImportChecklist,
        "destination_handoff_manifest.schema.json": DestinationHandoffManifest,
        "destination_handoff_validation.schema.json": DestinationHandoffValidation,
        "handoff_report_manifest.schema.json": HandoffReportManifest,
        "destination_import_plan.schema.json": DestinationImportPlan,
        "destination_import_receipt.schema.json": DestinationImportReceipt,
        "destination_import_validation.schema.json": DestinationImportValidation,
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.9.0"
