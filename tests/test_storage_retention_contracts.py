from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.storage_retention.models import (
    GateRetentionRecoveryReceiptV01,
    GateRunReceiptV01,
    StorageCleanupPlanV01,
    StorageCleanupReceiptV01,
    StorageInventoryV01,
)


def test_storage_retention_schemas_match_strict_models() -> None:
    """Keep every additive retention schema synchronized with its Pydantic model."""

    root = Path(__file__).resolve().parents[1]
    contracts = {
        "storage_inventory_v01.schema.json": StorageInventoryV01,
        "storage_cleanup_plan_v01.schema.json": StorageCleanupPlanV01,
        "storage_cleanup_receipt_v01.schema.json": StorageCleanupReceiptV01,
        "gate_run_receipt_v01.schema.json": GateRunReceiptV01,
        "gate_retention_recovery_receipt_v01.schema.json": GateRetentionRecoveryReceiptV01,
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.1.0"
