"""Opt-in reference-fidelity companions; never migrate canonical or historical evidence."""

from .material import evaluate_directional_material, publish_directional_material_preflight
from .models import (
    DirectionalMappingEvidenceV01,
    DirectionalMaterialPreflightV01,
    DirectionalTextureThresholdsV01,
)


def reference_fidelity_capability() -> dict[str, object]:
    """Describe the additive development boundary without claiming campaign or human success."""

    return {
        "schema_version": "0.1.0",
        "status": "disabled_experimental",
        "canonical_scene_spec": "0.2.0",
        "standard_mode": "advisory_with_existing_approvals",
        "aq_mode": "explicit_new_session_companion",
        "quality_revision_loop_versions": ["0.1.0", "0.2.0", "0.3.0"],
        "quality_revision_routing": {
            "0.1.0": "legacy_strictest", "0.2.0": "causal_v2", "0.3.0": "causal_v2",
        },
        "funded_autonomy_budget_version": "0.3.0",
        "fidelity_budget_epoch_version": "0.1.0",
        "correction_routes": ["structural_reentry", "parametric_revision", "material_revision"],
        "hold_routes": ["evidence_required", "calibration", "technical_recovery"],
        "legacy_behavior_changed": False,
        "automatic_migration": False,
        "nonhuman_review_is_approval": False,
        "new_campaign_visual_success_claimed": False,
        "destination_write": False,
    }


__all__ = [
    "DirectionalMappingEvidenceV01",
    "DirectionalMaterialPreflightV01",
    "DirectionalTextureThresholdsV01",
    "evaluate_directional_material",
    "publish_directional_material_preflight",
    "reference_fidelity_capability",
]
