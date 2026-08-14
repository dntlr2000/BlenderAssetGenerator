"""Central Schema parity, strictness, and version isolation for AQ 0.2 companions."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from codex_blender_modeler.autonomy_benchmarks.models import BenchmarkManifest
from codex_blender_modeler.autonomy_benchmarks.v02_models import (
    RUNNER_VERSION as BENCHMARK_V02_RUNNER_MODEL_VERSION,
)
from codex_blender_modeler.autonomy_benchmarks.v02_models import (
    SCHEMA_VERSION as BENCHMARK_V02_MODEL_VERSION,
)
from codex_blender_modeler.autonomy_benchmarks.v02_models import (
    BenchmarkCaseV02,
    BenchmarkManifestV02,
    BenchmarkReportV02,
    BlenderBenchmarkReceiptV02,
)
from codex_blender_modeler.autonomy_v2.candidate_validation_models import (
    GeometryAuthoringCompletionV2,
    GeometryCandidateValidationReceiptV2,
)
from codex_blender_modeler.autonomy_v2.material_phase_models import (
    MaterialControllerCompletionV2,
    MaterialPhaseReceiptV2,
    MaterialPhaseRollbackReceiptV2,
    MaterialPromotionIntentV2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AUTONOMY_SCHEMA_VERSION as AUTONOMY_V02_MODEL_VERSION,
)
from codex_blender_modeler.autonomy_v2.models import (
    DELIVERY_SCHEMA_VERSION as AUTONOMY_V02_DELIVERY_MODEL_VERSION,
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
from codex_blender_modeler.handoff.advanced_material_models import (
    AdvancedMaterialHandoffPlan,
    AdvancedMaterialHandoffReceipt,
    AdvancedMaterialHandoffRequest,
)
from codex_blender_modeler.integrated_quality.models import IntegratedQualityReport
from codex_blender_modeler.integrated_quality.v02_dispatch import (
    integrated_quality_report_model_for_version,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    SCHEMA_VERSION as INTEGRATED_QUALITY_V02_MODEL_VERSION,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    CandidateRankingV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
    ReentryDecisionV02,
)
from codex_blender_modeler.material_authoring.models import (
    AuthoredMaterialManifest,
    HighResolutionAuthorization,
    MaterialAuthoringReceipt,
    MaterialAuthoringRequest,
)
from codex_blender_modeler.material_graph.runtime_models import (
    RUNTIME_SCHEMA_VERSION as MATERIAL_GRAPH_RUNTIME_MODEL_VERSION,
)
from codex_blender_modeler.material_graph.runtime_models import (
    MaterialGraphCompileReport,
    MaterialGraphCompileRequest,
    MaterialGraphDependencyManifest,
    MaterialPreviewManifest,
    NormalizedMaterialGraphPlan,
    NormalizedMaterialNodeInventory,
    PortableMaterialApproximationReport,
)
from codex_blender_modeler.production.controller_executor.models import (
    SCHEMA_VERSION as CONTROLLER_EXECUTOR_MODEL_VERSION,
)
from codex_blender_modeler.production.controller_executor.models import (
    ControllerExecutionRequest,
    ControllerResult,
    PhaseToolProfile,
)
from codex_blender_modeler.structural_geometry.geometry_survival_v02 import (
    GeometryIntentSurvivalReportV02,
    GeometryStageSnapshotV02,
)
from codex_blender_modeler.structural_geometry.mesh_payload_compiler_v02 import (
    MeshPayloadV02CompileReport,
)
from codex_blender_modeler.structural_geometry.mesh_payload_io_v02 import (
    LegacyVertexUvMeshPayload,
    load_compatible_mesh_payload,
)
from codex_blender_modeler.structural_geometry.mesh_payload_migration_v02 import (
    MeshPayloadV02MigrationPlan,
    MeshPayloadV02MigrationReceipt,
)
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import (
    MESH_PAYLOAD_V02_VERSION as MESH_PAYLOAD_V02_MODEL_VERSION,
)
from codex_blender_modeler.structural_geometry.mesh_payload_v02 import MeshPayloadV02
from codex_blender_modeler.versioning import (
    ADVANCED_MATERIAL_HANDOFF_SCHEMA_VERSION,
    AUTONOMY_BENCHMARK_V02_RUNNER_VERSION,
    AUTONOMY_BENCHMARK_V02_SCHEMA_VERSION,
    AUTONOMY_SCHEMA_VERSION,
    AUTONOMY_V02_DELIVERY_SCHEMA_VERSION,
    AUTONOMY_V02_SCHEMA_VERSION,
    CONTROLLER_EXECUTOR_SCHEMA_VERSION,
    GEOMETRY_RUNTIME_V02_SCHEMA_VERSION,
    INTEGRATED_QUALITY_SCHEMA_VERSION,
    INTEGRATED_QUALITY_V02_SCHEMA_VERSION,
    MATERIAL_AUTHORING_SCHEMA_VERSION,
    MATERIAL_GRAPH_RUNTIME_SCHEMA_VERSION,
    MATERIAL_GRAPH_SCHEMA_VERSION,
    MESH_PAYLOAD_V02_SCHEMA_VERSION,
    SCENE_SPEC_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]

AQ_V02_SCHEMA_MODELS = {
    "mesh_payload_v02.schema.json": MeshPayloadV02,
    "mesh_payload_v02_compile_report.schema.json": MeshPayloadV02CompileReport,
    "mesh_payload_v02_migration_plan.schema.json": MeshPayloadV02MigrationPlan,
    "mesh_payload_v02_migration_receipt.schema.json": MeshPayloadV02MigrationReceipt,
    "geometry_stage_snapshot_v02.schema.json": GeometryStageSnapshotV02,
    "geometry_intent_survival_report.schema.json": GeometryIntentSurvivalReportV02,
    "integrated_quality_v02_report.schema.json": IntegratedQualityReportV02,
    "integrated_quality_v02_policy.schema.json": IntegratedQualityPolicyV02,
    "integrated_quality_v02_candidate_ranking.schema.json": CandidateRankingV02,
    "integrated_quality_v02_reentry.schema.json": ReentryDecisionV02,
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
    "controller_executor_phase_tool_profile.schema.json": PhaseToolProfile,
    "controller_executor_execution_request.schema.json": ControllerExecutionRequest,
    "controller_executor_result.schema.json": ControllerResult,
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
    "autonomy_benchmark_v02_case.schema.json": BenchmarkCaseV02,
    "autonomy_benchmark_v02_manifest.schema.json": BenchmarkManifestV02,
    "autonomy_benchmark_v02_blender_receipt.schema.json": BlenderBenchmarkReceiptV02,
    "autonomy_benchmark_v02_report.schema.json": BenchmarkReportV02,
    "material_authoring_request.schema.json": MaterialAuthoringRequest,
    "authored_material_manifest.schema.json": AuthoredMaterialManifest,
    "material_authoring_receipt.schema.json": MaterialAuthoringReceipt,
    "material_high_resolution_authorization.schema.json": HighResolutionAuthorization,
    "advanced_material_handoff_request.schema.json": AdvancedMaterialHandoffRequest,
    "advanced_material_handoff_plan.schema.json": AdvancedMaterialHandoffPlan,
    "advanced_material_handoff_receipt.schema.json": AdvancedMaterialHandoffReceipt,
}


def test_aq_v02_checked_in_schemas_match_every_registered_model() -> None:
    """Require exact generated parity and root strictness for every AQ 0.2 Schema."""

    for filename, model in AQ_V02_SCHEMA_MODELS.items():
        checked_in = json.loads((ROOT / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(checked_in)
        assert checked_in == model.model_json_schema()
        assert checked_in["additionalProperties"] is False
        assert model.model_config["extra"] == "forbid"
        assert model.model_config["strict"] is True
        unknown_field_errors = list(
            Draft202012Validator(checked_in).iter_errors({"unexpected": True})
        )
        assert any(error.validator == "additionalProperties" for error in unknown_field_errors)


def test_schema_generator_registers_exact_aq_v02_model_identities() -> None:
    """Prevent generated files from drifting to a similarly named legacy model."""

    registered = runpy.run_path(str(ROOT / "scripts" / "generate_schemas.py"))[
        "SCHEMAS"
    ]
    for filename, model in AQ_V02_SCHEMA_MODELS.items():
        assert registered[filename] is model
    new_names = set(AQ_V02_SCHEMA_MODELS)
    assert len(new_names) == 50
    geometry_names = {
        "mesh_payload_v02.schema.json",
        "mesh_payload_v02_compile_report.schema.json",
        "mesh_payload_v02_migration_plan.schema.json",
        "mesh_payload_v02_migration_receipt.schema.json",
        "geometry_stage_snapshot_v02.schema.json",
        "geometry_intent_survival_report.schema.json",
    }
    prefixes = (
        "integrated_quality_v02_",
        "material_graph_runtime_",
        "controller_executor_",
        "autonomy_v02_",
        "autonomy_benchmark_v02_",
        "material_authoring_",
        "material_high_resolution_",
        "authored_material_",
        "advanced_material_handoff_",
    )
    registered_aq_v02 = {
        name
        for name in registered
        if (
            name in geometry_names
            or (
                name.startswith(prefixes)
                and not name.startswith("material_authoring_codex_image_")
                and name
                != "autonomy_v02_material_closure_promotion_boundary.schema.json"
            )
        )
    }
    assert registered_aq_v02 == new_names


def test_aq_v02_versions_remain_parallel_to_legacy_contracts() -> None:
    """Bind central constants while leaving SceneSpec, AQ 0.1, and graph 0.1 intact."""

    assert SCENE_SPEC_VERSION == "0.2.0"
    assert INTEGRATED_QUALITY_SCHEMA_VERSION == "0.1.0"
    assert MATERIAL_GRAPH_SCHEMA_VERSION == "0.1.0"
    assert AUTONOMY_SCHEMA_VERSION == "0.1.0"
    assert MESH_PAYLOAD_V02_SCHEMA_VERSION == MESH_PAYLOAD_V02_MODEL_VERSION == "0.2.0"
    assert GEOMETRY_RUNTIME_V02_SCHEMA_VERSION == "0.1.0"
    for model in (
        MeshPayloadV02CompileReport,
        MeshPayloadV02MigrationPlan,
        MeshPayloadV02MigrationReceipt,
        GeometryStageSnapshotV02,
        GeometryIntentSurvivalReportV02,
    ):
        assert model.model_json_schema()["properties"]["schema_version"]["const"] == (
            GEOMETRY_RUNTIME_V02_SCHEMA_VERSION
        )
    assert (
        INTEGRATED_QUALITY_V02_SCHEMA_VERSION
        == INTEGRATED_QUALITY_V02_MODEL_VERSION
        == "0.2.0"
    )
    assert (
        MATERIAL_GRAPH_RUNTIME_SCHEMA_VERSION
        == MATERIAL_GRAPH_RUNTIME_MODEL_VERSION
        == "0.1.0"
    )
    for model in (
        NormalizedMaterialGraphPlan,
        MaterialGraphDependencyManifest,
        MaterialGraphCompileRequest,
        MaterialGraphCompileReport,
        NormalizedMaterialNodeInventory,
        PortableMaterialApproximationReport,
        MaterialPreviewManifest,
    ):
        assert model.model_json_schema()["properties"]["schema_version"]["const"] == (
            MATERIAL_GRAPH_RUNTIME_SCHEMA_VERSION
        )
    assert (
        CONTROLLER_EXECUTOR_SCHEMA_VERSION
        == CONTROLLER_EXECUTOR_MODEL_VERSION
        == "0.1.0"
    )
    for model in (PhaseToolProfile, ControllerExecutionRequest, ControllerResult):
        assert model.model_json_schema()["properties"]["schema_version"]["const"] == (
            CONTROLLER_EXECUTOR_SCHEMA_VERSION
        )
    assert AUTONOMY_V02_SCHEMA_VERSION == AUTONOMY_V02_MODEL_VERSION == "0.2.0"
    assert (
        AUTONOMY_V02_DELIVERY_SCHEMA_VERSION
        == AUTONOMY_V02_DELIVERY_MODEL_VERSION
        == "0.1.0"
    )
    assert (
        AUTONOMY_BENCHMARK_V02_SCHEMA_VERSION
        == BENCHMARK_V02_MODEL_VERSION
        == "0.2.0"
    )
    assert (
        AUTONOMY_BENCHMARK_V02_RUNNER_VERSION
        == BENCHMARK_V02_RUNNER_MODEL_VERSION
        == "0.2.0"
    )
    assert MATERIAL_AUTHORING_SCHEMA_VERSION == "0.1.0"
    assert ADVANCED_MATERIAL_HANDOFF_SCHEMA_VERSION == "0.1.0"


def test_explicit_version_dispatch_keeps_legacy_and_v02_separate() -> None:
    """Dispatch only declared IQ/mesh versions and reject unknown future contracts."""

    assert integrated_quality_report_model_for_version("0.1.0") is IntegratedQualityReport
    assert integrated_quality_report_model_for_version("0.2.0") is IntegratedQualityReportV02
    with pytest.raises(ValueError, match="unsupported"):
        integrated_quality_report_model_for_version("0.3.0")

    legacy = load_compatible_mesh_payload(
        {
            "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
            "faces": [[0, 1, 2]],
            "vertex_uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        }
    )
    assert isinstance(legacy, LegacyVertexUvMeshPayload)
    with pytest.raises(ValueError, match="unsupported"):
        load_compatible_mesh_payload({"schema_version": "0.3.0"})
    assert BenchmarkManifest.model_json_schema()["properties"]["schema_version"][
        "const"
    ] == "0.1.0"
    assert BenchmarkManifestV02.model_json_schema()["properties"]["schema_version"][
        "const"
    ] == "0.2.0"
