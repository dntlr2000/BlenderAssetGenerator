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
from codex_blender_modeler.background_quality.models import (
    BackgroundFitReport,
    BackgroundQualityReport,
    BackgroundRoleMap,
    BackgroundScenePromotionReceipt,
)
from codex_blender_modeler.baking.models import BakeManifest
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
from codex_blender_modeler.interior_qa.models import (
    InteriorQALatest,
    InteriorQAPlan,
    InteriorQAPlanApproval,
    InteriorQARenderManifest,
    InteriorQAReport,
    InteriorQARevisionCandidates,
    InteriorQASourceInventory,
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
from codex_blender_modeler.reporting.models import HumanReportManifest
from codex_blender_modeler.stabilization.models import (
    EnvironmentProbeReport,
    LocalWorkflowQueue,
    QueueAttemptReceipt,
    QueueLock,
    StabilityReportManifest,
    WorkspaceAuditReport,
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
    "background_scene_promotion_receipt.schema.json": (
        BackgroundScenePromotionReceipt
    ),
    "background_quality_report.schema.json": BackgroundQualityReport,
    "render_pass_manifest.schema.json": RenderPassManifest,
    "visual_qa_request.schema.json": VisualQARequest,
    "visual_qa_report.schema.json": VisualQAReport,
    "semantic_reference_mask_manifest.schema.json": SemanticReferenceMaskManifest,
    "semantic_reference_mask_promotion_receipt.schema.json": (
        SemanticReferenceMaskPromotionReceipt
    ),
    "semantic_reference_mask_registry_status.schema.json": (
        SemanticReferenceMaskRegistryStatus
    ),
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
    "visual_convergence_host_safety_envelope.schema.json": (
        VisualConvergenceHostSafetyEnvelope
    ),
    "visual_convergence_selection.schema.json": ConvergenceCandidateSelection,
    "visual_convergence_iteration.schema.json": VisualConvergenceIteration,
    "visual_convergence_iteration_authorization.schema.json": (
        VisualConvergenceIterationAuthorization
    ),
    "visual_convergence_report.schema.json": VisualConvergenceReport,
    "visual_convergence_report_manifest.schema.json": VisualConvergenceReportManifest,
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
