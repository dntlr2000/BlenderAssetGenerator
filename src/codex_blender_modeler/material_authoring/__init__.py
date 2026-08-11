"""AQ 0.2 companion contracts for deterministic local material authoring."""

from .codex_image_adapter import (
    author_codex_image_material_candidate,
    validate_codex_image_material_candidate,
)
from .codex_image_models import (
    CodexImageAuthoredMaterialManifestV021,
    CodexImageMaterialAuthoringReceiptV021,
    CodexImageMaterialAuthoringRequestV021,
    ExactSignageTextEvidenceV021,
)
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
    "CodexImageAuthoredMaterialManifestV021",
    "CodexImageMaterialAuthoringReceiptV021",
    "CodexImageMaterialAuthoringRequestV021",
    "ExactSignageTextEvidenceV021",
    "HighResolutionAuthorization",
    "MaterialAuthoringRequest",
    "MaterialAuthoringReceipt",
    "MaterialAuthoringStrategy",
    "ResolutionSelection",
    "ResolutionSelectorInput",
    "V05StrategyCompanionMapping",
    "author_material_candidate",
    "author_codex_image_material_candidate",
    "select_texture_resolution",
    "validate_codex_image_material_candidate",
]
