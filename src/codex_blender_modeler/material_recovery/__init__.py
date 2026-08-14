"""Stable append-only facade for Material Closure failure and repair evidence."""

from ..material_closure.failure_reporting import (
    build_material_framework_failure_report,
    build_material_retry_supersession_receipt,
    retry_is_executable,
)
from ..material_closure.incident_service import (
    MaterialCanonicalObservationPublication,
    MaterialRepairSessionRunResult,
    RecoverySourceArchiveSpec,
    archive_job_specific_recovery_sources,
    load_material_closure_model,
    publish_current_material_canonical_observations,
    publish_material_closure_model,
    publish_material_repair_session_plan,
    publish_material_session_supersession,
    run_material_repair_session,
    supersede_material_retry,
)
from ..material_closure.models import (
    IncidentStateDiscrepancyReport,
    JobSpecificRecoverySourceInventory,
    MaterialFrameworkFailureReport,
    MaterialRepairSessionPlan,
    MaterialRepairSourceBinding,
    MaterialRetrySupersessionReceipt,
    MaterialSessionSupersessionReceipt,
)
from ..material_closure.repair_session import (
    material_repair_automatic_steps,
    validate_material_repair_preapproval_outcome,
    validate_material_repair_session,
    verify_material_repair_geometry,
)

__all__ = [
    "IncidentStateDiscrepancyReport",
    "JobSpecificRecoverySourceInventory",
    "MaterialCanonicalObservationPublication",
    "MaterialFrameworkFailureReport",
    "MaterialRepairSessionPlan",
    "MaterialRepairSessionRunResult",
    "MaterialRepairSourceBinding",
    "MaterialRetrySupersessionReceipt",
    "MaterialSessionSupersessionReceipt",
    "RecoverySourceArchiveSpec",
    "archive_job_specific_recovery_sources",
    "build_material_framework_failure_report",
    "build_material_retry_supersession_receipt",
    "load_material_closure_model",
    "material_repair_automatic_steps",
    "publish_material_closure_model",
    "publish_current_material_canonical_observations",
    "publish_material_repair_session_plan",
    "publish_material_session_supersession",
    "retry_is_executable",
    "run_material_repair_session",
    "supersede_material_retry",
    "validate_material_repair_preapproval_outcome",
    "validate_material_repair_session",
    "verify_material_repair_geometry",
]
