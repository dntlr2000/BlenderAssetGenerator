"""Checked-in JSON Schema and registry parity for Material Closure 0.1.0."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialClosurePromotionBoundaryV2,
)
from codex_blender_modeler.material_closure.models import (
    AQV2StatusProjection,
    ExactArtifact,
    IncidentStateDiscrepancyReport,
    JobSpecificRecoverySourceInventory,
    MaterialAppearanceApproval,
    MaterialAppearanceApprovalConsumptionReceipt,
    MaterialApprovalImpactReport,
    MaterialAQBudgetObservation,
    MaterialAttemptState,
    MaterialCanonicalMaterialPlanAbsence,
    MaterialCanonicalSnapshot,
    MaterialClosureSourceBindingArtifact,
    MaterialDependencyClosure,
    MaterialDependencyClosureReceipt,
    MaterialFrameworkFailureReport,
    MaterialGraphRebindingPlan,
    MaterialGraphRebindingReceipt,
    MaterialNeutralPreviewManifest,
    MaterialPreflightBudget,
    MaterialPreflightResourceReceipt,
    MaterialPromotionPreflightFailure,
    MaterialPromotionPreflightReport,
    MaterialPromotionPreflightRequest,
    MaterialRepairSessionPlan,
    MaterialRepairSourceBinding,
    MaterialRetryApprovalAbsence,
    MaterialRetrySupersessionReceipt,
    MaterialRollbackRestorationObservation,
    MaterialSessionSupersessionReceipt,
    MaterialShadowCompileReceipt,
    MaterialStateConsistencyReport,
)
from codex_blender_modeler.versioning import (
    MATERIAL_CLOSURE_SCHEMA_VERSION,
    MATERIAL_PREFLIGHT_SCHEMA_VERSION,
    MATERIAL_REPAIR_SCHEMA_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
MATERIAL_CLOSURE_SCHEMAS = {
    "material_closure_source_binding.schema.json": MaterialClosureSourceBindingArtifact,
    "material_dependency_closure.schema.json": MaterialDependencyClosure,
    "material_dependency_closure_receipt.schema.json": MaterialDependencyClosureReceipt,
    "material_graph_rebinding_plan.schema.json": MaterialGraphRebindingPlan,
    "material_graph_rebinding_receipt.schema.json": MaterialGraphRebindingReceipt,
    "material_promotion_preflight_request.schema.json": MaterialPromotionPreflightRequest,
    "material_promotion_preflight_report.schema.json": MaterialPromotionPreflightReport,
    "material_promotion_preflight_failure.schema.json": MaterialPromotionPreflightFailure,
    "material_shadow_compile_receipt.schema.json": MaterialShadowCompileReceipt,
    "material_neutral_preview_manifest.schema.json": MaterialNeutralPreviewManifest,
    "material_preflight_budget.schema.json": MaterialPreflightBudget,
    "material_preflight_resource_receipt.schema.json": MaterialPreflightResourceReceipt,
    "material_aq_budget_observation.schema.json": MaterialAQBudgetObservation,
    "material_approval_impact_report.schema.json": MaterialApprovalImpactReport,
    "material_appearance_approval.schema.json": MaterialAppearanceApproval,
    "material_appearance_approval_consumption_receipt.schema.json": (
        MaterialAppearanceApprovalConsumptionReceipt
    ),
    "material_attempt_state.schema.json": MaterialAttemptState,
    "material_canonical_material_plan_absence.schema.json": (
        MaterialCanonicalMaterialPlanAbsence
    ),
    "material_canonical_snapshot.schema.json": MaterialCanonicalSnapshot,
    "material_state_consistency_report.schema.json": MaterialStateConsistencyReport,
    "aq_v2_status_projection.schema.json": AQV2StatusProjection,
    "material_framework_failure_report.schema.json": MaterialFrameworkFailureReport,
    "incident_state_discrepancy_report.schema.json": IncidentStateDiscrepancyReport,
    "material_retry_supersession_receipt.schema.json": (
        MaterialRetrySupersessionReceipt
    ),
    "material_retry_approval_absence.schema.json": MaterialRetryApprovalAbsence,
    "material_repair_session_plan.schema.json": MaterialRepairSessionPlan,
    "material_repair_source_binding.schema.json": MaterialRepairSourceBinding,
    "material_rollback_restoration_observation.schema.json": (
        MaterialRollbackRestorationObservation
    ),
    "material_session_supersession_receipt.schema.json": (
        MaterialSessionSupersessionReceipt
    ),
    "job_specific_recovery_source_inventory.schema.json": (
        JobSpecificRecoverySourceInventory
    ),
}


@pytest.mark.parametrize(("schema_name", "model"), MATERIAL_CLOSURE_SCHEMAS.items())
def test_material_closure_checked_in_schema_matches_model(
    schema_name: str,
    model: type,
) -> None:
    """Keep every persisted closure contract byte-structurally equal to Pydantic output."""

    checked_in = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(checked_in)
    assert checked_in == model.model_json_schema()


def test_material_closure_schema_registry_is_complete_and_additive() -> None:
    """Register every closure schema once without replacing legacy schema names."""

    registry = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))["SCHEMAS"]
    for schema_name, model in MATERIAL_CLOSURE_SCHEMAS.items():
        assert registry[schema_name] is model
    assert registry["autonomy_v02_material_closure_promotion_boundary.schema.json"] is (
        MaterialClosurePromotionBoundaryV2
    )
    assert "material_dependency_closure_v2.schema.json" not in registry
    assert len(MATERIAL_CLOSURE_SCHEMAS) == len(set(MATERIAL_CLOSURE_SCHEMAS))


def test_material_closure_schema_versions_and_unknown_fields_fail_closed() -> None:
    """Keep the companion versions explicit and every top-level contract extra-forbid."""

    assert MATERIAL_CLOSURE_SCHEMA_VERSION == "0.1.0"
    assert MATERIAL_PREFLIGHT_SCHEMA_VERSION == "0.1.0"
    assert MATERIAL_REPAIR_SCHEMA_VERSION == "0.1.0"
    for model in MATERIAL_CLOSURE_SCHEMAS.values():
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.1.0"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        ExactArtifact.model_validate(
            {
                "artifact_id": "artifact-a",
                "kind": "fixture",
                "path": "evidence/a.json",
                "sha256": "a" * 64,
                "byte_size": 1,
                "media_type": "application/json",
                "unknown": True,
            }
        )


@pytest.mark.parametrize("path", ["../escape.json", "/absolute.json", "a\\b.json"])
def test_material_closure_exact_artifact_rejects_nonportable_paths(path: str) -> None:
    """Reject traversal, absolute, and native-separator paths at the public schema edge."""

    with pytest.raises(ValidationError, match="path"):
        ExactArtifact(
            artifact_id="artifact-a",
            kind="fixture",
            path=path,
            sha256="a" * 64,
            byte_size=1,
            media_type="application/json",
        )
