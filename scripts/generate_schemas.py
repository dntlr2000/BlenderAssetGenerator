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
from codex_blender_modeler.autonomy_benchmarks.v02_models import (
    BenchmarkCaseV02,
    BenchmarkManifestV02,
    BenchmarkReportV02,
    BlenderBenchmarkReceiptV02,
)
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
from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryAuthoringCompletionV2,
    GeometryCandidateValidationReceiptV2,
)
from codex_blender_modeler.autonomy_v2.codex_image_overlay import (
    AutonomyCodexImageOverlay,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialClosurePolicyPromotionBoundaryV03,
    MaterialClosurePromotionBoundaryV2,
    MaterialControllerCompletionV2,
    MaterialPhaseReceiptV2,
    MaterialPhaseRollbackReceiptV2,
    MaterialPolicyAuthorizationConsumptionReceiptV03,
    MaterialPromotionIntentV2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AutonomyBudgetV2,
    AutonomyCancellationV2,
    AutonomyPlanV2,
    AutonomyProfileV2,
    AutonomyStateV2,
    DeliveryPlan,
    DeliveryProfile,
    DeliveryReviewBinding,
    DeliveryTerminalV2,
    QualityApprovedSourceFreeze,
    QualityReviewBundleV2,
    QualityTerminalV2,
    RootAuthorizationV2,
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
from codex_blender_modeler.codex_imagegen.material_loop_models import (
    CodexImageCandidateRankingEvidence,
    CodexImageCompanionSelectionReceipt,
    CodexImageMaterialLoopState,
    CodexImageMaterialLoopTerminal,
    CodexImageNativeCorePreparationReceipt,
    CodexImageNativeOutputAdoptionReceipt,
    CodexImageSemanticReview,
    CodexImageV05ExactAdoptionPreflightReceipt,
    ImageGeneratedMaterialBridgePlan,
    ImageGeneratedMaterialControllerBinding,
    ImageGeneratedMaterialControllerInput,
    ImageGeneratedMaterialNeutralPreview,
    ImageGeneratedMaterialPromotionReceipt,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
    ImageMaterialPromotionRetryReceipt,
)
from codex_blender_modeler.codex_imagegen.models import (
    CodexBuiltinImageProviderProfile,
    CodexGeneratedImageEvidence,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
    CodexImageGenerationPlan,
    CodexImageGenerationQualityReport,
    CodexImageGenerationSelection,
    CodexImageGenerationTerminal,
    ImageToMaterialAdoption,
)
from codex_blender_modeler.constraints.models import ConstraintSet, ConstraintSolution
from codex_blender_modeler.external_intake.models import (
    ExternalAssetIntakeApproval,
    ExternalAssetIntakePlan,
    ExternalAssetIntakeValidation,
    ExternalAssetManifest,
    ExternalNormalizationReceipt,
)
from codex_blender_modeler.handoff.advanced_material_models import (
    AdvancedMaterialHandoffPlan,
    AdvancedMaterialHandoffReceipt,
    AdvancedMaterialHandoffRequest,
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
from codex_blender_modeler.integrated_quality.v02_models import (
    CandidateRankingV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
    ReentryDecisionV02,
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
from codex_blender_modeler.material_authoring.codex_image_models import (
    CodexImageAuthoredMaterialManifestV021,
    CodexImageMaterialAuthoringReceiptV021,
    CodexImageMaterialAuthoringRequestV021,
    ExactSignageTextEvidenceV021,
)
from codex_blender_modeler.material_authoring.codex_image_normalized_models import (
    CodexImageNormalizedAuthoredMaterialManifestV010,
    CodexImageNormalizedMaterialAuthoringReceiptV010,
    CodexImageNormalizedMaterialAuthoringRequestV010,
)
from codex_blender_modeler.material_authoring.codex_image_v05_bridge import (
    CodexImageV05BridgeReceipt,
    CodexImageV05CanonicalMaterialAbsence,
    CodexImageV05ControllerBlueprint,
)
from codex_blender_modeler.material_authoring.models import (
    AuthoredMaterialManifest,
    HighResolutionAuthorization,
    MaterialAuthoringReceipt,
    MaterialAuthoringRequest,
)
from codex_blender_modeler.material_closure.models import (
    AQV2StatusProjection,
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
from codex_blender_modeler.material_graph.models import MaterialGraphSpec
from codex_blender_modeler.material_graph.runtime_models import (
    MaterialGraphCompileReport,
    MaterialGraphCompileRequest,
    MaterialGraphDependencyManifest,
    MaterialPreviewManifest,
    NormalizedMaterialGraphPlan,
    NormalizedMaterialNodeInventory,
    PortableMaterialApproximationReport,
)
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
    MaterialIdentitySplitPolicyApplyIntent,
    MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt,
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
from codex_blender_modeler.production.activation_models import (
    ActivationAssetCandidateIndex,
    ActivationAssetCandidateRegistry,
    ActivationAssetEligibilityReport,
    ActivationAssetEvidence,
    ActivationBaseline,
    ActivationReadinessReport,
    ActivationSourceManifest,
    HumanActivationAcceptance,
)
from codex_blender_modeler.production.controller_executor.models import (
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
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
from codex_blender_modeler.stabilization.archive_models import (
    WorkspaceRelocationPlan,
    WorkspaceRelocationReceipt,
)
from codex_blender_modeler.stabilization.models import (
    EnvironmentProbeReport,
    LocalWorkflowQueue,
    QueueAttemptReceipt,
    QueueLock,
    StabilityReportManifest,
    WorkspaceAuditReport,
)
from codex_blender_modeler.standard_custom_mesh import StandardCustomMeshPayload
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
)
from codex_blender_modeler.structural_geometry.mesh_payload_compiler_v02 import (
    MeshPayloadV02CompileReport,
)
from codex_blender_modeler.structural_geometry.mesh_payload_migration_v02 import (
    MeshPayloadV02MigrationPlan,
    MeshPayloadV02MigrationReceipt,
)
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import MeshPayloadV02
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
    "standard_custom_mesh_payload.schema.json": StandardCustomMeshPayload,
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
    "workspace_relocation_plan.schema.json": WorkspaceRelocationPlan,
    "workspace_relocation_receipt.schema.json": WorkspaceRelocationReceipt,
    "local_workflow_queue.schema.json": LocalWorkflowQueue,
    "queue_attempt_receipt.schema.json": QueueAttemptReceipt,
    "queue_lock.schema.json": QueueLock,
    "stability_report_manifest.schema.json": StabilityReportManifest,
    # Disabled-experimental AQ activation-readiness 0.1 contracts.
    "activation_source_manifest.schema.json": ActivationSourceManifest,
    "activation_baseline.schema.json": ActivationBaseline,
    "activation_readiness_report.schema.json": ActivationReadinessReport,
    "activation_asset_evidence.schema.json": ActivationAssetEvidence,
    "activation_asset_eligibility_report.schema.json": (
        ActivationAssetEligibilityReport
    ),
    "activation_asset_candidate_registry.schema.json": (
        ActivationAssetCandidateRegistry
    ),
    "activation_asset_candidate_index.schema.json": ActivationAssetCandidateIndex,
    "human_activation_acceptance.schema.json": HumanActivationAcceptance,
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
    # AQ 0.2 structural geometry companion roots.
    "mesh_payload_v02.schema.json": MeshPayloadV02,
    "mesh_payload_v02_compile_report.schema.json": MeshPayloadV02CompileReport,
    "mesh_payload_v02_migration_plan.schema.json": MeshPayloadV02MigrationPlan,
    "mesh_payload_v02_migration_receipt.schema.json": MeshPayloadV02MigrationReceipt,
    "geometry_stage_snapshot_v02.schema.json": GeometryStageSnapshotV02,
    "geometry_intent_survival_report.schema.json": GeometryIntentSurvivalReportV02,
    # Integrated Quality 0.2 remains parallel to the registered 0.1 contracts.
    "integrated_quality_v02_report.schema.json": IntegratedQualityReportV02,
    "integrated_quality_v02_policy.schema.json": IntegratedQualityPolicyV02,
    "integrated_quality_v02_candidate_ranking.schema.json": CandidateRankingV02,
    "integrated_quality_v02_reentry.schema.json": ReentryDecisionV02,
    # MaterialGraph runtime evidence consumes, but never replaces, MaterialGraphSpec 0.1.
    "material_graph_runtime_plan.schema.json": NormalizedMaterialGraphPlan,
    "material_graph_runtime_dependency_manifest.schema.json": (
        MaterialGraphDependencyManifest
    ),
    "material_graph_runtime_compile_request.schema.json": MaterialGraphCompileRequest,
    "material_graph_runtime_compile_report.schema.json": MaterialGraphCompileReport,
    "material_graph_runtime_inventory.schema.json": NormalizedMaterialNodeInventory,
    "material_graph_runtime_portable_approximation.schema.json": (
        PortableMaterialApproximationReport
    ),
    "material_graph_runtime_preview_manifest.schema.json": MaterialPreviewManifest,
    # ControllerExecutor is an isolated 0.1 protocol used by AQ 0.2.
    "controller_executor_phase_tool_profile.schema.json": PhaseToolProfile,
    "controller_executor_execution_request.schema.json": ControllerExecutionRequest,
    "controller_executor_result.schema.json": ControllerResult,
    # Autonomous Quality 0.2 policy and independent delivery evidence.
    "autonomy_v02_profile.schema.json": AutonomyProfileV2,
    "autonomy_v02_budget.schema.json": AutonomyBudgetV2,
    "autonomy_v02_root_authorization.schema.json": RootAuthorizationV2,
    "autonomy_v02_quality_source_freeze.schema.json": QualityApprovedSourceFreeze,
    "autonomy_v02_quality_review_bundle.schema.json": QualityReviewBundleV2,
    "autonomy_v02_delivery_profile.schema.json": DeliveryProfile,
    "autonomy_v02_delivery_plan.schema.json": DeliveryPlan,
    "autonomy_v02_delivery_review_binding.schema.json": DeliveryReviewBinding,
    "autonomy_v02_quality_terminal.schema.json": QualityTerminalV2,
    "autonomy_v02_delivery_terminal.schema.json": DeliveryTerminalV2,
    "autonomy_v02_plan.schema.json": AutonomyPlanV2,
    "autonomy_v02_state.schema.json": AutonomyStateV2,
    "autonomy_v02_cancellation.schema.json": AutonomyCancellationV2,
    "autonomy_v02_geometry_authoring_completion.schema.json": (
        GeometryAuthoringCompletionV2
    ),
    "autonomy_v02_geometry_candidate_validation_receipt.schema.json": (
        GeometryCandidateValidationReceiptV2
    ),
    "autonomy_v02_material_controller_completion.schema.json": (
        MaterialControllerCompletionV2
    ),
    "autonomy_v02_material_promotion_intent.schema.json": MaterialPromotionIntentV2,
    "autonomy_v02_material_phase_receipt.schema.json": MaterialPhaseReceiptV2,
    "autonomy_v02_material_rollback_receipt.schema.json": (
        MaterialPhaseRollbackReceiptV2
    ),
    "autonomy_v02_material_closure_promotion_boundary.schema.json": (
        MaterialClosurePromotionBoundaryV2
    ),
    "aq_v2_material_closure_policy_promotion_boundary.schema.json": (
        MaterialClosurePolicyPromotionBoundaryV03
    ),
    "aq_v2_material_policy_authorization_consumption_receipt.schema.json": (
        MaterialPolicyAuthorizationConsumptionReceiptV03
    ),
    # Optional AQ v2 Approval Envelope 0.3 and one-prompt companion evidence.
    "autonomy_approval_envelope.schema.json": AutonomyApprovalEnvelope,
    "autonomy_approval_policy_profile.schema.json": AutonomyApprovalPolicyProfile,
    "aq_v2_routine_gate_eligibility_report.schema.json": (
        AQV2RoutineGateEligibilityReport
    ),
    "aq_v2_routine_policy_authorization.schema.json": (
        AQV2RoutinePolicyAuthorization
    ),
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
    # Material Closure 0.1.0 is a strict pre-controller companion, not a new pipeline.
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
    # Material Identity Split 0.1.0 stops at a specialized explicit approval request.
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
    "material_identity_split_policy_apply_intent.schema.json": (
        MaterialIdentitySplitPolicyApplyIntent
    ),
    "material_identity_split_policy_authorization_consumption_receipt.schema.json": (
        MaterialIdentitySplitPolicyAuthorizationConsumptionReceipt
    ),
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
    # Codex built-in ImageGen is a controller-mediated additive AQ v2 overlay.
    "codex_builtin_image_provider_profile.schema.json": (
        CodexBuiltinImageProviderProfile
    ),
    "codex_image_generation_budget.schema.json": CodexImageGenerationBudget,
    "codex_image_generation_plan.schema.json": CodexImageGenerationPlan,
    "codex_image_generation_assignment.schema.json": CodexImageGenerationAssignment,
    "codex_image_generation_completion.schema.json": CodexImageGenerationCompletion,
    "codex_generated_image_evidence.schema.json": CodexGeneratedImageEvidence,
    "codex_image_generation_candidate.schema.json": CodexImageGenerationCandidate,
    "codex_image_generation_quality_report.schema.json": (
        CodexImageGenerationQualityReport
    ),
    "codex_image_generation_selection.schema.json": CodexImageGenerationSelection,
    "codex_image_generation_terminal.schema.json": CodexImageGenerationTerminal,
    "image_to_material_adoption.schema.json": ImageToMaterialAdoption,
    "autonomy_codex_image_overlay.schema.json": AutonomyCodexImageOverlay,
    "material_authoring_codex_image_request_v021.schema.json": (
        CodexImageMaterialAuthoringRequestV021
    ),
    "material_authoring_codex_image_manifest_v021.schema.json": (
        CodexImageAuthoredMaterialManifestV021
    ),
    "material_authoring_codex_image_receipt_v021.schema.json": (
        CodexImageMaterialAuthoringReceiptV021
    ),
    "exact_signage_text_evidence_v021.schema.json": ExactSignageTextEvidenceV021,
    "material_authoring_codex_image_normalized_request_0_1_0.schema.json": (
        CodexImageNormalizedMaterialAuthoringRequestV010
    ),
    "material_authoring_codex_image_normalized_manifest_0_1_0.schema.json": (
        CodexImageNormalizedAuthoredMaterialManifestV010
    ),
    "material_authoring_codex_image_normalized_receipt_0_1_0.schema.json": (
        CodexImageNormalizedMaterialAuthoringReceiptV010
    ),
    # ImageGen material-loop closure keeps staging, controller, and host authority distinct.
    "image_generated_material_bridge_plan_0_1_0.schema.json": (
        ImageGeneratedMaterialBridgePlan
    ),
    "image_generated_material_controller_input_0_1_0.schema.json": (
        ImageGeneratedMaterialControllerInput
    ),
    "image_generated_material_controller_binding_0_1_0.schema.json": (
        ImageGeneratedMaterialControllerBinding
    ),
    "image_generated_material_promotion_receipt_0_1_0.schema.json": (
        ImageGeneratedMaterialPromotionReceipt
    ),
    "image_material_promotion_retry_receipt_0_1_0.schema.json": (
        ImageMaterialPromotionRetryReceipt
    ),
    "image_generated_material_neutral_preview_0_1_0.schema.json": (
        ImageGeneratedMaterialNeutralPreview
    ),
    "imagegen_native_normalization_plan_0_1_0.schema.json": (
        ImageGenNativeNormalizationPlan
    ),
    "imagegen_native_normalization_receipt_0_1_0.schema.json": (
        ImageGenNativeNormalizationReceipt
    ),
    "codex_image_semantic_review_0_1_0.schema.json": CodexImageSemanticReview,
    "codex_image_candidate_ranking_evidence_0_1_0.schema.json": (
        CodexImageCandidateRankingEvidence
    ),
    "codex_image_companion_selection_receipt_0_1_0.schema.json": (
        CodexImageCompanionSelectionReceipt
    ),
    "codex_image_material_loop_terminal_0_1_0.schema.json": (
        CodexImageMaterialLoopTerminal
    ),
    "codex_image_material_loop_state_0_1_0.schema.json": CodexImageMaterialLoopState,
    "codex_image_native_output_adoption_receipt_0_1_0.schema.json": (
        CodexImageNativeOutputAdoptionReceipt
    ),
    "codex_image_native_core_preparation_receipt_0_1_0.schema.json": (
        CodexImageNativeCorePreparationReceipt
    ),
    "codex_image_v05_exact_adoption_preflight_receipt_0_1_0.schema.json": (
        CodexImageV05ExactAdoptionPreflightReceipt
    ),
    "codex_image_v05_controller_blueprint_0_1_0.schema.json": (
        CodexImageV05ControllerBlueprint
    ),
    "codex_image_v05_bridge_receipt_0_1_0.schema.json": CodexImageV05BridgeReceipt,
    "codex_image_v05_canonical_material_absence_0_1_0.schema.json": (
        CodexImageV05CanonicalMaterialAbsence
    ),
    # Deterministic AQ 0.2 benchmark contracts and result evidence.
    "autonomy_benchmark_v02_case.schema.json": BenchmarkCaseV02,
    "autonomy_benchmark_v02_manifest.schema.json": BenchmarkManifestV02,
    "autonomy_benchmark_v02_blender_receipt.schema.json": BlenderBenchmarkReceiptV02,
    "autonomy_benchmark_v02_report.schema.json": BenchmarkReportV02,
    # Scale-aware local MaterialAuthoring and advisory destination mapping companions.
    "material_authoring_request.schema.json": MaterialAuthoringRequest,
    "authored_material_manifest.schema.json": AuthoredMaterialManifest,
    "material_authoring_receipt.schema.json": MaterialAuthoringReceipt,
    "material_high_resolution_authorization.schema.json": HighResolutionAuthorization,
    "advanced_material_handoff_request.schema.json": AdvancedMaterialHandoffRequest,
    "advanced_material_handoff_plan.schema.json": AdvancedMaterialHandoffPlan,
    "advanced_material_handoff_receipt.schema.json": AdvancedMaterialHandoffReceipt,
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
