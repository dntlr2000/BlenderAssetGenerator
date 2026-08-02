"""Host-side material planning and contract validation for project v0.5."""

from .fidelity import (
    evaluate_material_fidelity,
    load_job_material_fidelity_report,
    validate_job_material_fidelity,
)
from .fidelity_models import MaterialFidelityReport, MaterialFidelityThresholds
from .io import load_material_plan, load_shader_recipe
from .models import (
    MaterialPlan,
    MaterialPlanItem,
    MaterialPromotionReceipt,
    MaterialValidationCheck,
    MaterialValidationReport,
    ShaderRecipe,
)
from .promotion import promote_workflow_material_candidate
from .scaffold import create_material_scaffold, create_workflow_material_candidates
from .service import load_job_material_contract_report, validate_job_material_contracts
from .validation import validate_material_contracts, write_material_validation_report

__all__ = [
    "MaterialPlan",
    "MaterialPlanItem",
    "MaterialPromotionReceipt",
    "MaterialValidationCheck",
    "MaterialValidationReport",
    "MaterialFidelityReport",
    "MaterialFidelityThresholds",
    "ShaderRecipe",
    "create_material_scaffold",
    "create_workflow_material_candidates",
    "evaluate_material_fidelity",
    "load_material_plan",
    "load_job_material_contract_report",
    "load_job_material_fidelity_report",
    "load_shader_recipe",
    "promote_workflow_material_candidate",
    "validate_job_material_contracts",
    "validate_job_material_fidelity",
    "validate_material_contracts",
    "write_material_validation_report",
]
