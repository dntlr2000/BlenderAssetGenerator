"""Stable host facade for approval-bound Material Closure promotion authority."""

from ..autonomy_v2.controller_bridge import (
    ExactMaterialClosureAdoptionController,
    execute_material_closure_controller_v2,
    get_autonomy_v2_material_closure_status,
)
from ..autonomy_v2.material_phase_models import MaterialClosurePromotionBoundaryV2
from ..autonomy_v2.material_phase_service import (
    validate_and_promote_material_closure_controller_result_v2,
    validate_material_closure_controller_projections_v2,
    validate_material_phase_rollback_receipt_v2,
)
from ..material_closure.approval_policy import (
    approval_requirement_for_impact,
    classify_material_changes,
    material_approval_is_current,
)
from ..material_closure.models import (
    MaterialAppearanceApproval,
    MaterialAppearanceApprovalConsumptionReceipt,
    MaterialApprovalImpactReport,
)
from ..material_closure.service import publish_material_appearance_approval

__all__ = [
    "ExactMaterialClosureAdoptionController",
    "MaterialAppearanceApproval",
    "MaterialAppearanceApprovalConsumptionReceipt",
    "MaterialApprovalImpactReport",
    "MaterialClosurePromotionBoundaryV2",
    "approval_requirement_for_impact",
    "classify_material_changes",
    "execute_material_closure_controller_v2",
    "get_autonomy_v2_material_closure_status",
    "material_approval_is_current",
    "publish_material_appearance_approval",
    "validate_and_promote_material_closure_controller_result_v2",
    "validate_material_closure_controller_projections_v2",
    "validate_material_phase_rollback_receipt_v2",
]
