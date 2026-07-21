"""Checked-in JSON Schema parity tests for V0.7 portable-asset contracts."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

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
from codex_blender_modeler.packaging.models import (
    ExportPackageManifest,
    RoundTripValidation,
    TexturePackManifest,
)


def test_v07_contract_schemas_are_current_and_valid_draft_2020_12() -> None:
    """Require each checked-in V0.7 schema to equal its strict Pydantic contract."""

    root = Path(__file__).resolve().parents[1]
    contracts = {
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
    }
    for filename, model in contracts.items():
        schema = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema == model.model_json_schema()
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schema_version"]["const"] == "0.7.0"
