"""External static-asset intake contracts and host services."""

from .models import (
    ExternalAssetIntakeApproval,
    ExternalAssetIntakePlan,
    ExternalAssetIntakeValidation,
    ExternalAssetManifest,
    ExternalNormalizationReceipt,
)
from .service import (
    approve_external_static_asset_intake,
    collect_external_build_provenance,
    get_external_static_asset_intake_status,
    normalize_external_static_asset,
    plan_external_static_asset_intake,
    validate_external_static_asset_intake,
)

__all__ = [
    "ExternalAssetIntakeApproval",
    "ExternalAssetIntakePlan",
    "ExternalAssetIntakeValidation",
    "ExternalAssetManifest",
    "ExternalNormalizationReceipt",
    "approve_external_static_asset_intake",
    "collect_external_build_provenance",
    "get_external_static_asset_intake_status",
    "normalize_external_static_asset",
    "plan_external_static_asset_intake",
    "validate_external_static_asset_intake",
]
