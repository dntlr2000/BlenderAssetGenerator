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
from .codex_image_normalized_adapter import (
    author_codex_image_normalized_material_candidate,
    build_codex_image_normalized_material_request,
    validate_codex_image_normalized_material_candidate,
)
from .codex_image_normalized_models import (
    CodexImageNormalizedAuthoredMaterialManifestV010,
    CodexImageNormalizedMaterialAuthoringReceiptV010,
    CodexImageNormalizedMaterialAuthoringRequestV010,
)
from .codex_image_v05_bridge import (
    CodexImageV05BridgeChannel,
    CodexImageV05BridgeReceipt,
    CodexImageV05CanonicalMaterialAbsence,
    CodexImageV05ControllerBlueprint,
    CodexImageV05ControllerInput,
    build_codex_image_v05_controller_blueprint,
    publish_codex_image_v05_bridge,
    publish_codex_image_v05_canonical_material_absence,
    validate_codex_image_v05_bridge,
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
    "CodexImageNormalizedAuthoredMaterialManifestV010",
    "CodexImageNormalizedMaterialAuthoringReceiptV010",
    "CodexImageNormalizedMaterialAuthoringRequestV010",
    "CodexImageV05BridgeChannel",
    "CodexImageV05BridgeReceipt",
    "CodexImageV05CanonicalMaterialAbsence",
    "CodexImageV05ControllerBlueprint",
    "CodexImageV05ControllerInput",
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
    "author_codex_image_normalized_material_candidate",
    "build_codex_image_normalized_material_request",
    "build_codex_image_v05_controller_blueprint",
    "publish_codex_image_v05_bridge",
    "publish_codex_image_v05_canonical_material_absence",
    "select_texture_resolution",
    "validate_codex_image_material_candidate",
    "validate_codex_image_normalized_material_candidate",
    "validate_codex_image_v05_bridge",
]
