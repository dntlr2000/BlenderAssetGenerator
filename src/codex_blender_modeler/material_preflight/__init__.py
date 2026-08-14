"""Stable pre-controller facade for Material Closure preflight services."""

from ..material_closure.models import (
    MaterialNeutralPreviewManifest,
    MaterialPreflightBudget,
    MaterialPreflightResourceReceipt,
    MaterialPromotionPreflightFailure,
    MaterialPromotionPreflightReport,
    MaterialPromotionPreflightRequest,
    MaterialShadowCompileReceipt,
)
from ..material_closure.preflight import collect_current_uv_layout_fingerprint
from ..material_closure.service import (
    MaterialClosureService,
    MaterialPromotionPreflightResult,
    material_shadow_compile,
)
from ..material_closure.surface_detail_preflight import (
    validate_surface_detail_bindings,
)

__all__ = [
    "MaterialClosureService",
    "MaterialNeutralPreviewManifest",
    "MaterialPreflightBudget",
    "MaterialPreflightResourceReceipt",
    "MaterialPromotionPreflightFailure",
    "MaterialPromotionPreflightReport",
    "MaterialPromotionPreflightRequest",
    "MaterialPromotionPreflightResult",
    "MaterialShadowCompileReceipt",
    "collect_current_uv_layout_fingerprint",
    "material_shadow_compile",
    "validate_surface_detail_bindings",
]
