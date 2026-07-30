import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_v06_contract_schemas_are_valid_draft_2020_12() -> None:
    """Validate every new V0.6 host contract before MCP or CLI integration uses it."""

    root = Path(__file__).resolve().parents[1]
    names = [
        "render_pass_manifest.schema.json",
        "visual_qa_request.schema.json",
        "visual_qa_report.schema.json",
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
