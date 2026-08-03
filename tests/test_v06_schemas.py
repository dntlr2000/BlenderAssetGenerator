import json
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.qa.diagnostic_models import (
    QADiagnosticBundleManifest,
    QADiagnosticReport,
    QADiagnosticRequest,
    SemanticReferenceMaskManifest,
)
from codex_blender_modeler.qa.multiview_sanity import (
    AssemblySanityPlan,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
)


def test_v06_contract_schemas_are_valid_draft_2020_12() -> None:
    """Validate every new V0.6 host contract before MCP or CLI integration uses it."""

    root = Path(__file__).resolve().parents[1]
    names = [
        "render_pass_manifest.schema.json",
        "visual_qa_request.schema.json",
        "visual_qa_report.schema.json",
        "semantic_reference_mask_manifest.schema.json",
        "qa_diagnostic_request.schema.json",
        "qa_diagnostic_report.schema.json",
        "qa_diagnostic_bundle.schema.json",
        "assembly_sanity_plan.schema.json",
        "assembly_sanity_render_manifest.schema.json",
        "assembly_sanity_report.schema.json",
        "qa_target_manifest.schema.json",
        "revision_candidates.schema.json",
        "revision_approval.schema.json",
        "convergence_report.schema.json",
        "visual_convergence_plan.schema.json",
        "visual_convergence_approval.schema.json",
        "visual_convergence_cancellation.schema.json",
        "visual_convergence_host_safety_envelope.schema.json",
        "visual_convergence_selection.schema.json",
        "visual_convergence_iteration_authorization.schema.json",
        "visual_convergence_iteration.schema.json",
        "visual_convergence_report.schema.json",
        "visual_convergence_report_manifest.schema.json",
        "human_report_manifest.schema.json",
    ]
    for name in names:
        schema = json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_v06_companion_schemas_match_strict_models() -> None:
    """Keep additive diagnostic schemas in exact parity with their host contracts."""

    root = Path(__file__).resolve().parents[1]
    contracts = {
        "semantic_reference_mask_manifest.schema.json": SemanticReferenceMaskManifest,
        "qa_diagnostic_request.schema.json": QADiagnosticRequest,
        "qa_diagnostic_report.schema.json": QADiagnosticReport,
        "qa_diagnostic_bundle.schema.json": QADiagnosticBundleManifest,
        "assembly_sanity_plan.schema.json": AssemblySanityPlan,
        "assembly_sanity_render_manifest.schema.json": AssemblySanityRenderManifest,
        "assembly_sanity_report.schema.json": AssemblySanityReport,
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
