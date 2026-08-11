"""Schema parity for MaterialAuthoring and AdvancedMaterialHandoff 0.1.0."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.handoff.advanced_material_models import (
    AdvancedMaterialHandoffPlan,
    AdvancedMaterialHandoffReceipt,
    AdvancedMaterialHandoffRequest,
)
from codex_blender_modeler.material_authoring.models import (
    AuthoredMaterialManifest,
    HighResolutionAuthorization,
    MaterialAuthoringReceipt,
    MaterialAuthoringRequest,
)

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_MODELS = {
    "material_authoring_request.schema.json": MaterialAuthoringRequest,
    "authored_material_manifest.schema.json": AuthoredMaterialManifest,
    "material_authoring_receipt.schema.json": MaterialAuthoringReceipt,
    "material_high_resolution_authorization.schema.json": HighResolutionAuthorization,
    "advanced_material_handoff_request.schema.json": AdvancedMaterialHandoffRequest,
    "advanced_material_handoff_plan.schema.json": AdvancedMaterialHandoffPlan,
    "advanced_material_handoff_receipt.schema.json": AdvancedMaterialHandoffReceipt,
}


def test_material_authoring_companion_schemas_match_strict_models() -> None:
    """Keep every checked-in companion schema in exact Pydantic model parity."""

    for filename, model in SCHEMA_MODELS.items():
        checked_in = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        generated = model.model_json_schema()
        Draft202012Validator.check_schema(checked_in)
        assert checked_in == generated, filename


def test_advisory_schema_cannot_claim_destination_write_or_runtime_parity() -> None:
    """Keep destination mutation and parity fields const-false in public JSON contracts."""

    plan = json.loads(
        (ROOT / "schemas" / "advanced_material_handoff_plan.schema.json").read_text(
            encoding="utf-8"
        )
    )
    properties = plan["properties"]
    assert properties["destination_write_performed"]["const"] is False
    assert properties["engine_execution_performed"]["const"] is False
    assert properties["runtime_parity_verified"]["const"] is False
