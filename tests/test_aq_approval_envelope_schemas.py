"""Schema parity and version isolation for Approval Envelope 0.3 companions."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.autonomy_v2.approval_models import (
    AQV2ApprovalBudget,
    AQV2ApprovalTelemetryReport,
    AQV2ConsolidatedEscalationRequest,
    AQV2EscalationDecision,
    AQV2OnePromptRunPlan,
    AQV2OnePromptRunTerminal,
    AQV2PolicyDecisionReceipt,
    AQV2RoutineGateEligibilityReport,
    AQV2RoutinePolicyAuthorization,
    AQV2TechnicalFailureReport,
    AutonomyApprovalEnvelope,
    AutonomyApprovalPolicyProfile,
    FrameworkChangeJustification,
    HistoricalSessionAutonomyEligibilityReport,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialClosurePolicyPromotionBoundaryV03,
    MaterialPolicyAuthorizationConsumptionReceiptV03,
)
from codex_blender_modeler.material_identity_split.models import (
    MaterialIdentitySplitPolicyApplyIntent,
    MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt,
)
from codex_blender_modeler.versioning import (
    AUTONOMY_APPROVAL_ENVELOPE_SCHEMA_VERSION,
    AUTONOMY_ONE_PROMPT_SCHEMA_VERSION,
    FRAMEWORK_CHANGE_JUSTIFICATION_SCHEMA_VERSION,
    PROJECT_VERSION,
    SCENE_SPEC_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]

APPROVAL_SCHEMA_MODELS = {
    "autonomy_approval_envelope.schema.json": AutonomyApprovalEnvelope,
    "autonomy_approval_policy_profile.schema.json": AutonomyApprovalPolicyProfile,
    "aq_v2_routine_gate_eligibility_report.schema.json": (
        AQV2RoutineGateEligibilityReport
    ),
    "aq_v2_routine_policy_authorization.schema.json": AQV2RoutinePolicyAuthorization,
    "aq_v2_policy_decision_receipt.schema.json": AQV2PolicyDecisionReceipt,
    "aq_v2_approval_budget.schema.json": AQV2ApprovalBudget,
    "aq_v2_consolidated_escalation_request.schema.json": (
        AQV2ConsolidatedEscalationRequest
    ),
    "aq_v2_escalation_decision.schema.json": AQV2EscalationDecision,
    "aq_v2_approval_telemetry_report.schema.json": AQV2ApprovalTelemetryReport,
    "aq_v2_technical_failure_report.schema.json": AQV2TechnicalFailureReport,
    "aq_v2_one_prompt_run_plan.schema.json": AQV2OnePromptRunPlan,
    "aq_v2_one_prompt_run_terminal.schema.json": AQV2OnePromptRunTerminal,
    "framework_change_justification.schema.json": FrameworkChangeJustification,
    "historical_session_autonomy_eligibility_report.schema.json": (
        HistoricalSessionAutonomyEligibilityReport
    ),
    "aq_v2_material_closure_policy_promotion_boundary.schema.json": (
        MaterialClosurePolicyPromotionBoundaryV03
    ),
    "aq_v2_material_policy_authorization_consumption_receipt.schema.json": (
        MaterialPolicyAuthorizationConsumptionReceiptV03
    ),
    "material_identity_split_policy_apply_intent.schema.json": (
        MaterialIdentitySplitPolicyApplyIntent
    ),
    "material_identity_split_policy_authorization_consumption_receipt.schema.json": (
        MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt
    ),
}


def test_approval_schemas_match_strict_models_and_draft_202012() -> None:
    """Require exact checked-in parity, strict roots, and valid Draft 2020-12 schemas."""

    for filename, model in APPROVAL_SCHEMA_MODELS.items():
        checked_in = json.loads(
            (ROOT / "schemas" / filename).read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(checked_in)
        assert checked_in == model.model_json_schema()
        assert checked_in["additionalProperties"] is False
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True
        assert model.model_config["frozen"] is True
        assert model.model_config["allow_inf_nan"] is False


def test_schema_generator_registers_exact_approval_model_identities() -> None:
    """Keep every public approval schema mapped to its intended companion model."""

    registered = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))[
        "SCHEMAS"
    ]
    for filename, model in APPROVAL_SCHEMA_MODELS.items():
        assert registered[filename] is model


def test_companion_versions_do_not_bump_project_or_scene_spec() -> None:
    """Keep project 0.9.0 and canonical SceneSpec 0.2.0 unchanged."""

    assert PROJECT_VERSION == "0.9.0"
    assert SCENE_SPEC_VERSION == "0.2.0"
    assert AUTONOMY_APPROVAL_ENVELOPE_SCHEMA_VERSION == "0.3.0"
    assert AUTONOMY_ONE_PROMPT_SCHEMA_VERSION == "0.1.0"
    assert FRAMEWORK_CHANGE_JUSTIFICATION_SCHEMA_VERSION == "0.1.0"
