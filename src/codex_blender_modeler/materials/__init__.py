"""Host-side material planning and contract validation for project v0.5."""

from .io import load_material_plan, load_shader_recipe
from .models import (
    MaterialPlan,
    MaterialPlanItem,
    MaterialValidationCheck,
    MaterialValidationReport,
    ShaderRecipe,
)
from .scaffold import create_material_scaffold
from .service import load_job_material_contract_report, validate_job_material_contracts
from .validation import validate_material_contracts, write_material_validation_report

__all__ = [
    "MaterialPlan",
    "MaterialPlanItem",
    "MaterialValidationCheck",
    "MaterialValidationReport",
    "ShaderRecipe",
    "create_material_scaffold",
    "load_material_plan",
    "load_job_material_contract_report",
    "load_shader_recipe",
    "validate_job_material_contracts",
    "validate_material_contracts",
    "write_material_validation_report",
]
