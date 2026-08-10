from __future__ import annotations

import json
from pathlib import Path

from codex_blender_modeler.analysis.models import (
    AssemblyValidationReport,
    CameraSolution,
    ModelingPlan,
    ReferenceAnalysis,
    SurfaceDetailValidationReport,
)
from codex_blender_modeler.architecture.models import (
    InteriorScope,
    InteriorScopeApproval,
    InteriorScopeValidation,
)
from codex_blender_modeler.auto_revision.candidate_review_models import (
    CandidateReviewApproval,
    CandidateReviewDecision,
    CandidateReviewPromotionReceipt,
    CandidateReviewReportManifest,
)
from codex_blender_modeler.auto_revision.convergence_policy import (
    ConvergenceCandidateSelection,
)
from codex_blender_modeler.auto_revision.convergence_session_models import (
    VisualConvergenceApproval,
    VisualConvergenceCancellation,
    VisualConvergenceHostSafetyEnvelope,
    VisualConvergenceIteration,
    VisualConvergenceIterationAuthorization,
    VisualConvergencePlan,
    VisualConvergenceReport,
    VisualConvergenceReportManifest,
)
from codex_blender_modeler.auto_revision.models import (
    ConvergenceReport,
    RevisionApproval,
    RevisionCandidates,
)
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
from codex_blender_modeler.background_quality.models import (
    BackgroundFitReport,
    BackgroundQualityReport,
    BackgroundRoleMap,
    BackgroundScenePromotionReceipt,
)
from codex_blender_modeler.baking.models import BakeManifest
from codex_blender_modeler.blender_scripts.assembly.models import (
    AssemblyCompanionReport,
    AssemblyCompanionRequest,
)
from codex_blender_modeler.blender_scripts.topology.models import (
    TopologyCompanionReport,
    TopologyProfile,
)
from codex_blender_modeler.constraints.models import ConstraintSet, ConstraintSolution
from codex_blender_modeler.external_intake.models import (
    ExternalAssetIntakeApproval,
    ExternalAssetIntakePlan,
    ExternalAssetIntakeValidation,
    ExternalAssetManifest,
    ExternalNormalizationReceipt,
)
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
from codex_blender_modeler.integrated_quality.models import (
    CandidateRanking,
    IntegratedQualityReport,
    IntegratedQualityReportManifest,
    QualityGateProfile,
)
from codex_blender_modeler.interior_qa.models import (
    InteriorQALatest,
    InteriorQAPlan,
    InteriorQAPlanApproval,
    InteriorQARenderManifest,
    InteriorQAReport,
    InteriorQARevisionCandidates,
    InteriorQASourceInventory,
)
from codex_blender_modeler.material_graph.models import MaterialGraphSpec
from codex_blender_modeler.materials.fidelity_models import MaterialFidelityReport
from codex_blender_modeler.materials.models import (
    MaterialPlan,
    MaterialPromotionReceipt,
    ShaderRecipe,
)
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.optimization.models import (
    AssetProfile,
    CollisionManifest,
    LODManifest,
    MeshPreflightReport,
    OptimizationApproval,
    OptimizationPlan,
    OptimizationReview,
    PortableMaterialConversionManifest,
    PortableMaterialConversionPlan,
    StaticAssetCostReport,
    UVManifest,
)
from codex_blender_modeler.orchestration.models import (
    IntentRouting,
    WorkflowApproval,
    WorkflowAttempt,
    WorkflowLock,
    WorkflowPlan,
    WorkflowRequest,
    WorkflowState,
    WorkflowStepCompletion,
)
from codex_blender_modeler.packaging.models import (
    ExportPackageManifest,
    RoundTripValidation,
    TexturePackManifest,
)
from codex_blender_modeler.production.models import (
    AssetProductionDispatchPlan,
    AssetProductionDispatchRequest,
    CodexTaskBinding,
    CodexTaskBindingReceipt,
    CodexTaskLaunchManifest,
    DelegatedProductionAdvanceReceipt,
    DelegatedProductionControllerPlan,
    DelegatedProductionState,
    DelegatedWorkAssignment,
    ProductionConvergenceBinding,
    ProductionPostflightAuditReceipt,
)
from codex_blender_modeler.qa.diagnostic_models import (
    QADiagnosticBundleManifest,
    QADiagnosticReport,
    QADiagnosticRequest,
    SemanticReferenceMaskManifest,
)
from codex_blender_modeler.qa.models import (
    QATargetManifest,
    RenderPassManifest,
    VisualQAReport,
    VisualQARequest,
)
from codex_blender_modeler.qa.multiview_sanity import (
    AssemblySanityPlan,
    AssemblySanityRenderManifest,
    AssemblySanityReport,
    GeometryMultiviewVisualReview,
)
from codex_blender_modeler.qa.semantic_mask_registry_models import (
    SemanticReferenceMaskPromotionReceipt,
    SemanticReferenceMaskRegistryStatus,
)
from codex_blender_modeler.qa.structural_regression import StructuralRegressionReport
from codex_blender_modeler.reference_evidence.models import (
    CameraHypothesisSet,
    ReferenceEvidence,
    ReferenceEvidenceRunResult,
)
from codex_blender_modeler.reporting.models import HumanReportManifest
from codex_blender_modeler.stabilization.models import (
    EnvironmentProbeReport,
    LocalWorkflowQueue,
    QueueAttemptReceipt,
    QueueLock,
    StabilityReportManifest,
    WorkspaceAuditReport,
)
from codex_blender_modeler.structural_geometry.migration import (
    SceneSpecV03MigrationPlan,
    SceneSpecV03MigrationReceipt,
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    SceneSpecV03,
    StructuralGeometryCandidate,
    StructuralMeshPayload,
)
from codex_blender_modeler.texturing.models import TextureManifest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "scene_spec.schema.json": SceneSpec,
    "reference_analysis.schema.json": ReferenceAnalysis,
    "camera_solution.schema.json": CameraSolution,
    "modeling_plan.schema.json": ModelingPlan,
    "assembly_validation.schema.json": AssemblyValidationReport,
    "surface_detail_validation.schema.json": SurfaceDetailValidationReport,
    "constraints.schema.json": ConstraintSet,
    "constraint_solution.schema.json": ConstraintSolution,
    "external_asset_intake_plan.schema.json": ExternalAssetIntakePlan,
    "external_asset_intake_approval.schema.json": ExternalAssetIntakeApproval,
    "external_asset_manifest.schema.json": ExternalAssetManifest,
    "external_normalization_receipt.schema.json": ExternalNormalizationReceipt,
    "external_asset_intake_validation.schema.json": ExternalAssetIntakeValidation,
    "material_plan.schema.json": MaterialPlan,
    "material_promotion_receipt.schema.json": MaterialPromotionReceipt,
    "material_fidelity_report.schema.json": MaterialFidelityReport,
    "shader_recipe.schema.json": ShaderRecipe,
    "texture_manifest.schema.json": TextureManifest,
    "bake_manifest.schema.json": BakeManifest,
    "background_role_map.schema.json": BackgroundRoleMap,
    "background_fit_report.schema.json": BackgroundFitReport,
    "background_scene_promotion_receipt.schema.json": (BackgroundScenePromotionReceipt),
    "background_quality_report.schema.json": BackgroundQualityReport,
    "render_pass_manifest.schema.json": RenderPassManifest,
    "visual_qa_request.schema.json": VisualQARequest,
    "visual_qa_report.schema.json": VisualQAReport,
    "semantic_reference_mask_manifest.schema.json": SemanticReferenceMaskManifest,
    "semantic_reference_mask_promotion_receipt.schema.json": (
        SemanticReferenceMaskPromotionReceipt
    ),
    "semantic_reference_mask_registry_status.schema.json": (SemanticReferenceMaskRegistryStatus),
    "qa_diagnostic_request.schema.json": QADiagnosticRequest,
    "qa_diagnostic_report.schema.json": QADiagnosticReport,
    "qa_diagnostic_bundle.schema.json": QADiagnosticBundleManifest,
    "assembly_sanity_plan.schema.json": AssemblySanityPlan,
    "assembly_sanity_render_manifest.schema.json": AssemblySanityRenderManifest,
    "assembly_sanity_report.schema.json": AssemblySanityReport,
    "geometry_multiview_visual_review.schema.json": GeometryMultiviewVisualReview,
    "qa_target_manifest.schema.json": QATargetManifest,
    "revision_candidates.schema.json": RevisionCandidates,
    "revision_approval.schema.json": RevisionApproval,
    "convergence_report.schema.json": ConvergenceReport,
    "structural_regression_report.schema.json": StructuralRegressionReport,
    "visual_convergence_plan.schema.json": VisualConvergencePlan,
    "visual_convergence_approval.schema.json": VisualConvergenceApproval,
    "visual_convergence_cancellation.schema.json": VisualConvergenceCancellation,
    "visual_convergence_host_safety_envelope.schema.json": (VisualConvergenceHostSafetyEnvelope),
    "visual_convergence_selection.schema.json": ConvergenceCandidateSelection,
    "visual_convergence_iteration.schema.json": VisualConvergenceIteration,
    "visual_convergence_iteration_authorization.schema.json": (
        VisualConvergenceIterationAuthorization
    ),
    "visual_convergence_report.schema.json": VisualConvergenceReport,
    "visual_convergence_report_manifest.schema.json": VisualConvergenceReportManifest,
    "candidate_review_decision.schema.json": CandidateReviewDecision,
    "candidate_review_approval.schema.json": CandidateReviewApproval,
    "candidate_review_promotion_receipt.schema.json": CandidateReviewPromotionReceipt,
    "candidate_review_report_manifest.schema.json": CandidateReviewReportManifest,
    "asset_profile.schema.json": AssetProfile,
    "optimization_plan.schema.json": OptimizationPlan,
    "optimization_review.schema.json": OptimizationReview,
    "optimization_approval.schema.json": OptimizationApproval,
    "mesh_preflight_report.schema.json": MeshPreflightReport,
    "lod_manifest.schema.json": LODManifest,
    "collision_manifest.schema.json": CollisionManifest,
    "uv_manifest.schema.json": UVManifest,
    "asset_cost_report.schema.json": StaticAssetCostReport,
    "portable_material_conversion_plan.schema.json": PortableMaterialConversionPlan,
    "portable_material_conversion_manifest.schema.json": PortableMaterialConversionManifest,
    "texture_pack_manifest.schema.json": TexturePackManifest,
    "export_package_manifest.schema.json": ExportPackageManifest,
    "roundtrip_validation.schema.json": RoundTripValidation,
    "interior_scope.schema.json": InteriorScope,
    "interior_scope_approval.schema.json": InteriorScopeApproval,
    "interior_scope_validation.schema.json": InteriorScopeValidation,
    "interior_qa_source_inventory.schema.json": InteriorQASourceInventory,
    "interior_qa_plan.schema.json": InteriorQAPlan,
    "interior_qa_plan_approval.schema.json": InteriorQAPlanApproval,
    "interior_qa_render_manifest.schema.json": InteriorQARenderManifest,
    "interior_qa_report.schema.json": InteriorQAReport,
    "interior_qa_revision_candidates.schema.json": InteriorQARevisionCandidates,
    "interior_qa_latest.schema.json": InteriorQALatest,
    "workflow_request.schema.json": WorkflowRequest,
    "intent_routing.schema.json": IntentRouting,
    "workflow_plan.schema.json": WorkflowPlan,
    "workflow_state.schema.json": WorkflowState,
    "workflow_approval.schema.json": WorkflowApproval,
    "workflow_step_completion.schema.json": WorkflowStepCompletion,
    "workflow_attempt.schema.json": WorkflowAttempt,
    "workflow_lock.schema.json": WorkflowLock,
    "environment_probe.schema.json": EnvironmentProbeReport,
    "workspace_audit.schema.json": WorkspaceAuditReport,
    "local_workflow_queue.schema.json": LocalWorkflowQueue,
    "queue_attempt_receipt.schema.json": QueueAttemptReceipt,
    "queue_lock.schema.json": QueueLock,
    "stability_report_manifest.schema.json": StabilityReportManifest,
    "asset_production_dispatch_request.schema.json": AssetProductionDispatchRequest,
    "delegated_production_controller_plan.schema.json": DelegatedProductionControllerPlan,
    "codex_task_launch_manifest.schema.json": CodexTaskLaunchManifest,
    "asset_production_dispatch_plan.schema.json": AssetProductionDispatchPlan,
    "codex_task_binding.schema.json": CodexTaskBinding,
    "codex_task_binding_receipt.schema.json": CodexTaskBindingReceipt,
    "delegated_work_assignment.schema.json": DelegatedWorkAssignment,
    "delegated_production_advance_receipt.schema.json": (
        DelegatedProductionAdvanceReceipt
    ),
    "delegated_production_state.schema.json": DelegatedProductionState,
    "production_convergence_binding.schema.json": ProductionConvergenceBinding,
    "production_postflight_audit_receipt.schema.json": (
        ProductionPostflightAuditReceipt
    ),
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
    "human_report_manifest.schema.json": HumanReportManifest,
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


def main() -> None:
    """Regenerate host-model schemas while retaining manual Blender report schemas."""

    for filename, model in SCHEMAS.items():
        output = ROOT / "schemas" / filename
        output.write_text(
            json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(output)


if __name__ == "__main__":
    main()
