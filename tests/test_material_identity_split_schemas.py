"""Checked-in JSON Schema and registry parity for Material Identity Split 0.1.0."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from codex_blender_modeler.material_identity_split.models import (
    MaterialIdentitySplitApplyIntent,
    MaterialIdentitySplitApplyReceipt,
    MaterialIdentitySplitApprovalConsumptionReceipt,
    MaterialIdentitySplitApprovalRequest,
    MaterialIdentitySplitGeometryContinuationReceipt,
    MaterialIdentitySplitInvariantReport,
    MaterialIdentitySplitMaterialBindingDerivativeReceipt,
    MaterialIdentitySplitModelingPlanDiffReport,
    MaterialIdentitySplitPlan,
    MaterialIdentitySplitPreapprovalFailure,
    MaterialIdentitySplitPreapprovalReport,
    MaterialIdentitySplitPreapprovalRequest,
    MaterialIdentitySplitRecoveryReceipt,
    MaterialIdentitySplitRollbackReceipt,
    MaterialIdentitySplitRootScopeApproval,
    MaterialIdentitySplitShadowBuildReceipt,
    MaterialIdentitySplitStatusProjection,
    MaterialIdentitySplitTransactionState,
)
from codex_blender_modeler.versioning import MATERIAL_IDENTITY_SPLIT_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_SPLIT_SCHEMAS = {
    "material_identity_split_plan.schema.json": MaterialIdentitySplitPlan,
    "material_identity_split_modeling_plan_diff_report.schema.json": (
        MaterialIdentitySplitModelingPlanDiffReport
    ),
    "material_identity_split_preapproval_request.schema.json": (
        MaterialIdentitySplitPreapprovalRequest
    ),
    "material_identity_split_shadow_build_receipt.schema.json": (
        MaterialIdentitySplitShadowBuildReceipt
    ),
    "material_identity_split_binding_derivative_receipt.schema.json": (
        MaterialIdentitySplitMaterialBindingDerivativeReceipt
    ),
    "material_identity_split_invariant_report.schema.json": (
        MaterialIdentitySplitInvariantReport
    ),
    "material_identity_split_preapproval_report.schema.json": (
        MaterialIdentitySplitPreapprovalReport
    ),
    "material_identity_split_preapproval_failure.schema.json": (
        MaterialIdentitySplitPreapprovalFailure
    ),
    "material_identity_split_approval_request.schema.json": (
        MaterialIdentitySplitApprovalRequest
    ),
    "material_identity_split_root_scope_approval.schema.json": (
        MaterialIdentitySplitRootScopeApproval
    ),
    "material_identity_split_approval_consumption_receipt.schema.json": (
        MaterialIdentitySplitApprovalConsumptionReceipt
    ),
    "material_identity_split_apply_intent.schema.json": MaterialIdentitySplitApplyIntent,
    "material_identity_split_transaction_state.schema.json": (
        MaterialIdentitySplitTransactionState
    ),
    "material_identity_split_apply_receipt.schema.json": MaterialIdentitySplitApplyReceipt,
    "material_identity_split_rollback_receipt.schema.json": (
        MaterialIdentitySplitRollbackReceipt
    ),
    "material_identity_split_recovery_receipt.schema.json": (
        MaterialIdentitySplitRecoveryReceipt
    ),
    "material_identity_split_geometry_continuation_receipt.schema.json": (
        MaterialIdentitySplitGeometryContinuationReceipt
    ),
    "material_identity_split_status_projection.schema.json": (
        MaterialIdentitySplitStatusProjection
    ),
}


@pytest.mark.parametrize(("schema_name", "model"), IDENTITY_SPLIT_SCHEMAS.items())
def test_material_identity_split_checked_in_schema_matches_model(
    schema_name: str,
    model: type,
) -> None:
    """Keep every persisted identity-split contract equal to Pydantic output."""

    checked_in = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(checked_in)
    assert checked_in == model.model_json_schema()


def test_material_identity_split_schema_registry_is_complete() -> None:
    """Register every additive schema once without replacing historical names."""

    registry = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))["SCHEMAS"]
    for schema_name, model in IDENTITY_SPLIT_SCHEMAS.items():
        assert registry[schema_name] is model
    assert len(IDENTITY_SPLIT_SCHEMAS) == len(set(IDENTITY_SPLIT_SCHEMAS))


def test_material_identity_split_versions_and_unknown_fields_fail_closed() -> None:
    """Keep version 0.1.0 explicit and all top-level contracts extra-forbid."""

    assert MATERIAL_IDENTITY_SPLIT_SCHEMA_VERSION == "0.1.0"
    for model in IDENTITY_SPLIT_SCHEMAS.values():
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.1.0"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        MaterialIdentitySplitPlan.model_validate({"schema_version": "0.1.0", "unknown": 1})

