import json
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.auto_revision.candidate_review_models import (
    CandidateReviewApproval,
    CandidateReviewDecision,
    CandidateReviewPromotionReceipt,
    CandidateReviewReportManifest,
)
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
    GeometryMultiviewVisualReview,
)
from codex_blender_modeler.qa.structural_regression import StructuralRegressionReport
from codex_blender_modeler.reporting.models import HumanReportManifest


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
        "geometry_multiview_visual_review.schema.json",
        "qa_target_manifest.schema.json",
        "revision_candidates.schema.json",
        "revision_approval.schema.json",
        "convergence_report.schema.json",
        "structural_regression_report.schema.json",
        "visual_convergence_plan.schema.json",
        "visual_convergence_approval.schema.json",
        "visual_convergence_cancellation.schema.json",
        "visual_convergence_host_safety_envelope.schema.json",
        "visual_convergence_selection.schema.json",
        "visual_convergence_iteration_authorization.schema.json",
        "visual_convergence_iteration.schema.json",
        "visual_convergence_report.schema.json",
        "visual_convergence_report_manifest.schema.json",
        "candidate_review_decision.schema.json",
        "candidate_review_approval.schema.json",
        "candidate_review_promotion_receipt.schema.json",
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
        "geometry_multiview_visual_review.schema.json": GeometryMultiviewVisualReview,
        "structural_regression_report.schema.json": StructuralRegressionReport,
        "candidate_review_decision.schema.json": CandidateReviewDecision,
        "candidate_review_approval.schema.json": CandidateReviewApproval,
        "candidate_review_promotion_receipt.schema.json": (CandidateReviewPromotionReceipt),
        "candidate_review_report_manifest.schema.json": CandidateReviewReportManifest,
        "human_report_manifest.schema.json": HumanReportManifest,
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False


def test_geometry_visual_review_schema_enforces_exact_order_and_reentry() -> None:
    """Expose the same ordered-view and outcome rules to schema-only agent authors."""

    schema = GeometryMultiviewVisualReview.model_json_schema()
    validator = Draft202012Validator(schema)
    payload = GeometryMultiviewVisualReview(
        job_id="schema_asset",
        run_id="schema-review",
        plan_sha256="a" * 64,
        render_manifest_sha256="b" * 64,
        structural_report_sha256="c" * 64,
        reviewed_view_ids=["front", "right", "top", "rear", "oblique"],
        reviewed_pass_kinds=["beauty", "wireframe"],
        outcome="visually_coherent",
        v04_reentry="not_indicated",
        reviewed_at=datetime.now(UTC),
    ).model_dump(mode="json")
    assert not list(validator.iter_errors(payload))

    duplicate_views = {**payload, "reviewed_view_ids": ["front"] * 5}
    duplicate_passes = {**payload, "reviewed_pass_kinds": ["beauty"] * 2}
    contradictory_reentry = {**payload, "v04_reentry": "required"}
    assert list(validator.iter_errors(duplicate_views))
    assert list(validator.iter_errors(duplicate_passes))
    assert list(validator.iter_errors(contradictory_reentry))


def _ordered_assembly_schema_payloads() -> tuple[dict, dict]:
    """Build valid plan and manifest documents for ordered-array schema checks."""

    view_specs = [
        ("front", [1.0, 0.0, 0.0], "vertical"),
        ("right", [0.0, 1.0, 0.0], "vertical"),
        ("top", [0.0, 0.0, 1.0], "longitudinal"),
        ("rear", [-1.0, 0.0, 0.0], "vertical"),
        ("oblique", [0.577, 0.577, 0.577], "vertical"),
    ]
    target_ids = ["asset.root"]
    plan = AssemblySanityPlan.model_validate(
        {
            "job_id": "schema_asset",
            "run_id": "schema-assembly",
            "scene_spec_path": "analysis/scene_spec.json",
            "scene_spec_sha256": "a" * 64,
            "modeling_plan_path": "analysis/modeling_plan.json",
            "modeling_plan_sha256": "b" * 64,
            "source_blend_path": "blender/scene.blend",
            "source_blend_sha256": "c" * 64,
            "build_fingerprint": "d" * 64,
            "source_fingerprint": "e" * 64,
            "assembly_frame": {
                "root_object_id": "asset.root",
                "longitudinal_axis": "X",
                "lateral_axis": "Y",
                "vertical_axis": "Z",
            },
            "target_ids": target_ids,
            "resolution": [128, 128],
            "views": [
                {
                    "view_id": view_id,
                    "camera_direction_frame": direction,
                    "screen_up_role": screen_up_role,
                    "target_ids": target_ids,
                }
                for view_id, direction, screen_up_role in view_specs
            ],
            "created_at": "2026-08-05T00:00:00Z",
        }
    )
    pass_kinds = ["beauty", "silhouette", "object_id", "wireframe"]
    manifest = AssemblySanityRenderManifest.model_validate(
        {
            "job_id": "schema_asset",
            "run_id": "schema-assembly",
            "plan_sha256": "f" * 64,
            "scene_spec_sha256": "a" * 64,
            "modeling_plan_sha256": "b" * 64,
            "source_blend_path": "blender/scene.blend",
            "source_blend_sha256": "c" * 64,
            "build_fingerprint": "d" * 64,
            "blender_version": "5.0.1",
            "render_engine": "BLENDER_EEVEE",
            "render_device": "CPU",
            "resolution": [128, 128],
            "object_id_colors": {"asset.root": "#ff0000"},
            "assembly_frame_bounds": {
                "min": [-1.0, -1.0, -1.0],
                "max": [1.0, 1.0, 1.0],
            },
            "assembly_evaluation": {"status": "passed"},
            "views": [
                {
                    "view_id": view_id,
                    "camera": {"type": "PERSP"},
                    "target_ids": target_ids,
                    "passes": [
                        {
                            "kind": kind,
                            "path": (
                                "qa/assembly_sanity/runs/schema-assembly/views/"
                                f"{view_id}/{kind}.png"
                            ),
                            "sha256": f"{index + 1:x}" * 64,
                            "width": 128,
                            "height": 128,
                        }
                        for index, kind in enumerate(pass_kinds)
                    ],
                }
                for view_id, _direction, _screen_up_role in view_specs
            ],
        }
    )
    return plan.model_dump(mode="json"), manifest.model_dump(mode="json")


def test_assembly_schemas_reject_reordered_views_and_passes() -> None:
    """Expose exact view and pass ordering to schema-only producers."""

    plan, manifest = _ordered_assembly_schema_payloads()
    plan_validator = Draft202012Validator(AssemblySanityPlan.model_json_schema())
    manifest_validator = Draft202012Validator(AssemblySanityRenderManifest.model_json_schema())
    assert not list(plan_validator.iter_errors(plan))
    assert not list(manifest_validator.iter_errors(manifest))

    reordered_plan = json.loads(json.dumps(plan))
    reordered_plan["views"][0], reordered_plan["views"][1] = (
        reordered_plan["views"][1],
        reordered_plan["views"][0],
    )
    reordered_manifest = json.loads(json.dumps(manifest))
    reordered_manifest["views"][0], reordered_manifest["views"][1] = (
        reordered_manifest["views"][1],
        reordered_manifest["views"][0],
    )
    reordered_passes = json.loads(json.dumps(manifest))
    first_passes = reordered_passes["views"][0]["passes"]
    first_passes[0], first_passes[1] = first_passes[1], first_passes[0]

    assert list(plan_validator.iter_errors(reordered_plan))
    assert list(manifest_validator.iter_errors(reordered_manifest))
    assert list(manifest_validator.iter_errors(reordered_passes))
