"""Schema parity and version isolation for Autonomous Quality companion contracts."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

from jsonschema import Draft202012Validator

from codex_blender_modeler.autonomy.failure_recovery import (
    HostAttemptFailure,
    HostAttemptIntent,
    HostFailureTerminalReceipt,
)
from codex_blender_modeler.autonomy.material_models import (
    MaterialCandidateAssignment,
    MaterialCandidateCompletionMarker,
    MaterialCandidateEvaluation,
    MaterialCandidatePromotionReceipt,
    MaterialCandidateRanking,
    MaterialRoundInputSnapshot,
)
from codex_blender_modeler.autonomy.models import (
    SCHEMA_VERSION as AUTONOMY_MODEL_VERSION,
)
from codex_blender_modeler.autonomy.models import (
    AutonomyBudget,
    AutonomyControllerBinding,
    AutonomyIterationReceipt,
    AutonomyPlan,
    AutonomyProfile,
    AutonomyState,
    AutonomyTerminal,
    AutonomyTerminalIntent,
    CandidateAuthoringAssignment,
    CandidateCompletionMarker,
    CandidateEvaluation,
    CandidatePromotionReceipt,
    PolicyAuthorization,
    PolicyGateTarget,
    ReviewBundleManifest,
    ReviewBundleReceipt,
    RootAuthorization,
    StructuralCandidateManifest,
    StructuralCandidatePlan,
)
from codex_blender_modeler.autonomy.production_budget import (
    PackageRepairFailure,
    PackageRepairPlan,
    PackageRepairReceipt,
    ProductionResourceReceipt,
    ProductionResourceReservation,
)
from codex_blender_modeler.blender_scripts.assembly.models import (
    SCHEMA_VERSION as ASSEMBLY_MODEL_VERSION,
)
from codex_blender_modeler.blender_scripts.assembly.models import (
    AssemblyCompanionReport,
    AssemblyCompanionRequest,
)
from codex_blender_modeler.blender_scripts.topology.models import (
    SCHEMA_VERSION as TOPOLOGY_MODEL_VERSION,
)
from codex_blender_modeler.blender_scripts.topology.models import (
    TopologyCompanionReport,
    TopologyProfile,
)
from codex_blender_modeler.integrated_quality.models import (
    SCHEMA_VERSION as INTEGRATED_QUALITY_MODEL_VERSION,
)
from codex_blender_modeler.integrated_quality.models import (
    CandidateRanking,
    IntegratedQualityReport,
    IntegratedQualityReportManifest,
    QualityGateProfile,
)
from codex_blender_modeler.material_graph.models import (
    SCHEMA_VERSION as MATERIAL_GRAPH_MODEL_VERSION,
)
from codex_blender_modeler.material_graph.models import (
    MaterialGraphSpec,
)
from codex_blender_modeler.reference_evidence.models import (
    SCHEMA_VERSION as REFERENCE_EVIDENCE_MODEL_VERSION,
)
from codex_blender_modeler.reference_evidence.models import (
    CameraHypothesisSet,
    ReferenceEvidence,
    ReferenceEvidenceRunResult,
)
from codex_blender_modeler.structural_geometry.migration import (
    SceneSpecV03MigrationPlan,
    SceneSpecV03MigrationReceipt,
)
from codex_blender_modeler.structural_geometry.models import (
    CONTRACT_VERSION as STRUCTURAL_GEOMETRY_MODEL_VERSION,
)
from codex_blender_modeler.structural_geometry.models import (
    SCHEMA_VERSION as SCENE_SPEC_V03_MODEL_VERSION,
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    SceneSpecV03,
    StructuralGeometryCandidate,
    StructuralMeshPayload,
)
from codex_blender_modeler.versioning import (
    ASSEMBLY_COMPANION_SCHEMA_VERSION,
    AUTONOMY_SCHEMA_VERSION,
    INTEGRATED_QUALITY_SCHEMA_VERSION,
    MATERIAL_GRAPH_SCHEMA_VERSION,
    REFERENCE_EVIDENCE_SCHEMA_VERSION,
    SCENE_SPEC_V03_VERSION,
    SCENE_SPEC_VERSION,
    STRUCTURAL_GEOMETRY_SCHEMA_VERSION,
    TOPOLOGY_COMPANION_SCHEMA_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]

AQ_SCHEMA_MODELS = {
    "reference_evidence.schema.json": ReferenceEvidence,
    "camera_hypothesis_set.schema.json": CameraHypothesisSet,
    "reference_evidence_run_result.schema.json": ReferenceEvidenceRunResult,
    "integrated_quality_report.schema.json": IntegratedQualityReport,
    "integrated_quality_report_manifest.schema.json": IntegratedQualityReportManifest,
    "quality_gate_profile.schema.json": QualityGateProfile,
    "candidate_ranking.schema.json": CandidateRanking,
    "scene_spec_v03.schema.json": SceneSpecV03,
    "scene_spec_v03_migration_plan.schema.json": SceneSpecV03MigrationPlan,
    "scene_spec_v03_migration_receipt.schema.json": SceneSpecV03MigrationReceipt,
    "structural_geometry_candidate.schema.json": StructuralGeometryCandidate,
    "structural_mesh_payload.schema.json": StructuralMeshPayload,
    "asset_scale_context.schema.json": AssetScaleContext,
    "material_graph_spec.schema.json": MaterialGraphSpec,
    "assembly_companion_request.schema.json": AssemblyCompanionRequest,
    "assembly_companion_report.schema.json": AssemblyCompanionReport,
    "topology_profile.schema.json": TopologyProfile,
    "topology_companion_report.schema.json": TopologyCompanionReport,
    "autonomy_budget.schema.json": AutonomyBudget,
    "autonomy_profile.schema.json": AutonomyProfile,
    "root_authorization.schema.json": RootAuthorization,
    "autonomy_plan.schema.json": AutonomyPlan,
    "autonomy_controller_binding.schema.json": AutonomyControllerBinding,
    "policy_gate_target.schema.json": PolicyGateTarget,
    "policy_authorization.schema.json": PolicyAuthorization,
    "candidate_authoring_assignment.schema.json": CandidateAuthoringAssignment,
    "candidate_completion_marker.schema.json": CandidateCompletionMarker,
    "structural_candidate_plan.schema.json": StructuralCandidatePlan,
    "structural_candidate_manifest.schema.json": StructuralCandidateManifest,
    "candidate_evaluation.schema.json": CandidateEvaluation,
    "candidate_promotion_receipt.schema.json": CandidatePromotionReceipt,
    "autonomy_state.schema.json": AutonomyState,
    "autonomy_iteration_receipt.schema.json": AutonomyIterationReceipt,
    "autonomy_terminal.schema.json": AutonomyTerminal,
    "autonomy_terminal_intent.schema.json": AutonomyTerminalIntent,
    "review_bundle_manifest.schema.json": ReviewBundleManifest,
    "review_bundle_receipt.schema.json": ReviewBundleReceipt,
    "material_round_input_snapshot.schema.json": MaterialRoundInputSnapshot,
    "material_candidate_assignment.schema.json": MaterialCandidateAssignment,
    "material_candidate_completion_marker.schema.json": MaterialCandidateCompletionMarker,
    "material_candidate_evaluation.schema.json": MaterialCandidateEvaluation,
    "material_candidate_ranking.schema.json": MaterialCandidateRanking,
    "material_candidate_promotion_receipt.schema.json": MaterialCandidatePromotionReceipt,
    "host_attempt_intent.schema.json": HostAttemptIntent,
    "host_attempt_failure.schema.json": HostAttemptFailure,
    "host_failure_terminal_receipt.schema.json": HostFailureTerminalReceipt,
    "production_resource_reservation.schema.json": ProductionResourceReservation,
    "production_resource_receipt.schema.json": ProductionResourceReceipt,
    "package_repair_failure.schema.json": PackageRepairFailure,
    "package_repair_plan.schema.json": PackageRepairPlan,
    "package_repair_receipt.schema.json": PackageRepairReceipt,
}


def test_autonomous_quality_checked_in_schemas_match_strict_models() -> None:
    """Keep every new checked-in contract in exact Draft 2020-12 model parity."""

    for filename, model in AQ_SCHEMA_MODELS.items():
        schema = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert model.model_config["extra"] == "forbid"


def test_schema_generator_registers_every_autonomous_quality_contract() -> None:
    """Prevent a valid checked-in schema from drifting outside the regeneration map."""

    generated_models = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))[
        "SCHEMAS"
    ]
    for filename, model in AQ_SCHEMA_MODELS.items():
        assert generated_models[filename] is model


def test_autonomous_quality_versions_are_parallel_to_legacy_scene_spec() -> None:
    """Preserve SceneSpec 0.2 while identifying opt-in companion contract versions."""

    assert SCENE_SPEC_VERSION == "0.2.0"
    assert SCENE_SPEC_V03_VERSION == "0.3.0"
    assert REFERENCE_EVIDENCE_SCHEMA_VERSION == "0.1.0"
    assert INTEGRATED_QUALITY_SCHEMA_VERSION == "0.1.0"
    assert AUTONOMY_SCHEMA_VERSION == "0.1.0"
    assert MATERIAL_GRAPH_SCHEMA_VERSION == "0.1.0"
    assert STRUCTURAL_GEOMETRY_SCHEMA_VERSION == "0.1.0"
    assert ASSEMBLY_COMPANION_SCHEMA_VERSION == "0.1.0"
    assert TOPOLOGY_COMPANION_SCHEMA_VERSION == "0.1.0"
    assert AUTONOMY_MODEL_VERSION == AUTONOMY_SCHEMA_VERSION
    assert REFERENCE_EVIDENCE_MODEL_VERSION == REFERENCE_EVIDENCE_SCHEMA_VERSION
    assert INTEGRATED_QUALITY_MODEL_VERSION == INTEGRATED_QUALITY_SCHEMA_VERSION
    assert MATERIAL_GRAPH_MODEL_VERSION == MATERIAL_GRAPH_SCHEMA_VERSION
    assert STRUCTURAL_GEOMETRY_MODEL_VERSION == STRUCTURAL_GEOMETRY_SCHEMA_VERSION
    assert ASSEMBLY_MODEL_VERSION == ASSEMBLY_COMPANION_SCHEMA_VERSION
    assert TOPOLOGY_MODEL_VERSION == TOPOLOGY_COMPANION_SCHEMA_VERSION
    assert SCENE_SPEC_V03_MODEL_VERSION == SCENE_SPEC_V03_VERSION
