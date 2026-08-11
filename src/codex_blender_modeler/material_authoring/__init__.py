"""AQ 0.2 companion contracts for deterministic local material authoring."""

from .models import (
    AdvancedPreviewPolicy,
    AuthoredMaterialManifest,
    HighResolutionAuthorization,
    MaterialAuthoringReceipt,
    MaterialAuthoringRequest,
    MaterialAuthoringStrategy,
    ResolutionSelection,
    ResolutionSelectorInput,
    V05StrategyCompanionMapping,
)
from .service import author_material_candidate, select_texture_resolution

__all__ = [
    "AdvancedPreviewPolicy",
    "AuthoredMaterialManifest",
    "HighResolutionAuthorization",
    "MaterialAuthoringRequest",
    "MaterialAuthoringReceipt",
    "MaterialAuthoringStrategy",
    "ResolutionSelection",
    "ResolutionSelectorInput",
    "V05StrategyCompanionMapping",
    "author_material_candidate",
    "select_texture_resolution",
]
