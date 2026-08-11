"""Explicit opt-in AQ v2 geometry facade; legacy v1 imports do not load this module."""

from .geometry_delivery_inspector_v02 import inspect_delivery_geometry_stage_v02
from .geometry_intent_runtime_v02 import classify_geometry_intent_v02
from .geometry_survival_v02 import (
    GeometryEvidenceFingerprintV02,
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
    compare_geometry_stage_snapshots_v02,
    publish_geometry_survival_report_v02,
    validate_geometry_survival_chain_v02,
    verify_geometry_stage_snapshot_artifact_v02,
)
from .mesh_payload_compiler_v02 import (
    MeshPayloadV02CompileReport,
    compile_mesh_payload_v02,
)
from .mesh_payload_io_v02 import (
    LegacyVertexUvMeshPayload,
    load_compatible_mesh_payload,
    load_mesh_payload_v02,
    verify_mesh_payload_v02_source_hashes,
)
from .mesh_payload_migration_v02 import (
    MeshPayloadV02MigrationPlan,
    MeshPayloadV02MigrationReceipt,
    apply_mesh_payload_v02_migration,
    plan_mesh_payload_v02_migration,
)
from .mesh_payload_v02 import (
    MESH_PAYLOAD_V02_VERSION,
    MeshPayloadV02,
)

__all__ = [
    "MESH_PAYLOAD_V02_VERSION",
    "GeometryEvidenceFingerprintV02",
    "GeometryIntentSurvivalReportV02",
    "GeometryStageSnapshotV02",
    "LegacyVertexUvMeshPayload",
    "MeshPayloadV02",
    "MeshPayloadV02CompileReport",
    "MeshPayloadV02MigrationPlan",
    "MeshPayloadV02MigrationReceipt",
    "apply_mesh_payload_v02_migration",
    "classify_geometry_intent_v02",
    "compare_geometry_stage_snapshots_v02",
    "compile_mesh_payload_v02",
    "inspect_delivery_geometry_stage_v02",
    "load_compatible_mesh_payload",
    "load_mesh_payload_v02",
    "plan_mesh_payload_v02_migration",
    "publish_geometry_survival_report_v02",
    "validate_geometry_survival_chain_v02",
    "verify_geometry_stage_snapshot_artifact_v02",
    "verify_mesh_payload_v02_source_hashes",
]
