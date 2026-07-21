from __future__ import annotations

import json
from pathlib import Path

from codex_blender_modeler.analysis.models import CameraSolution, ModelingPlan, ReferenceAnalysis
from codex_blender_modeler.architecture.models import (
    InteriorScope,
    InteriorScopeApproval,
    InteriorScopeValidation,
)
from codex_blender_modeler.auto_revision.models import (
    ConvergenceReport,
    RevisionApproval,
    RevisionCandidates,
)
from codex_blender_modeler.baking.models import BakeManifest
from codex_blender_modeler.constraints.models import ConstraintSet, ConstraintSolution
from codex_blender_modeler.materials.models import MaterialPlan, ShaderRecipe
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
from codex_blender_modeler.qa.models import (
    QATargetManifest,
    RenderPassManifest,
    VisualQAReport,
    VisualQARequest,
)
from codex_blender_modeler.texturing.models import TextureManifest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {
    "scene_spec.schema.json": SceneSpec,
    "reference_analysis.schema.json": ReferenceAnalysis,
    "camera_solution.schema.json": CameraSolution,
    "modeling_plan.schema.json": ModelingPlan,
    "constraints.schema.json": ConstraintSet,
    "constraint_solution.schema.json": ConstraintSolution,
    "material_plan.schema.json": MaterialPlan,
    "shader_recipe.schema.json": ShaderRecipe,
    "texture_manifest.schema.json": TextureManifest,
    "bake_manifest.schema.json": BakeManifest,
    "render_pass_manifest.schema.json": RenderPassManifest,
    "visual_qa_request.schema.json": VisualQARequest,
    "visual_qa_report.schema.json": VisualQAReport,
    "qa_target_manifest.schema.json": QATargetManifest,
    "revision_candidates.schema.json": RevisionCandidates,
    "revision_approval.schema.json": RevisionApproval,
    "convergence_report.schema.json": ConvergenceReport,
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
    "workflow_request.schema.json": WorkflowRequest,
    "intent_routing.schema.json": IntentRouting,
    "workflow_plan.schema.json": WorkflowPlan,
    "workflow_state.schema.json": WorkflowState,
    "workflow_approval.schema.json": WorkflowApproval,
    "workflow_step_completion.schema.json": WorkflowStepCompletion,
    "workflow_attempt.schema.json": WorkflowAttempt,
    "workflow_lock.schema.json": WorkflowLock,
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
