"""IQ continuation boundary for one promoted Codex ImageGen material companion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import workspace
from ..codex_imagegen.artifacts import validate_codex_image_artifact
from ..codex_imagegen.material_loop_models import (
    ImageGeneratedMaterialPromotionReceipt,
)
from ..codex_imagegen.models import CodexImageArtifact
from .codex_image_material_loop_service import (
    get_codex_image_material_loop_status,
    validate_codex_image_material_promotion_receipt,
)
from .codex_image_material_preview_service import (
    validate_promoted_codex_image_material_preview,
)
from .controller_bridge import get_autonomy_v2_status
from .material_phase_service import validate_material_phase_receipt_v2
from .models import AQV2Artifact, AutonomyStateV2
from .supervisor_service import QualitySubmissionV2, advance_autonomy_v2


def _aq_artifact(
    artifact: CodexImageArtifact,
    *,
    kind: str | None = None,
) -> AQV2Artifact:
    """Project one companion artifact with an optional authoritative AQ role alias."""

    return AQV2Artifact(
        artifact_id=artifact.artifact_id,
        kind=kind or artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def validate_codex_image_material_quality_boundary(
    job_root: Path,
    *,
    session_id: str,
    promotion_receipt_artifact: CodexImageArtifact,
    quality_submission: QualitySubmissionV2,
    state: AutonomyStateV2,
) -> ImageGeneratedMaterialPromotionReceipt:
    """Require the complete companion promotion chain in the next exact IQ submission."""

    promotion = validate_codex_image_material_promotion_receipt(
        job_root,
        promotion_receipt_artifact,
        require_current=True,
    )
    identity = (promotion.job_id, promotion.session_id)
    if identity != (state.job_id, session_id):
        raise ValueError("material-loop promotion belongs to another AQ v2 session")
    if state.phase != "quality" or state.next_action != "run_integrated_quality":
        raise PermissionError("base AQ v2 state is not at the IQ 0.2 boundary")
    material_phase = _aq_artifact(
        promotion.material_phase_receipt,
        kind="material_phase_receipt",
    )
    if state.provenance[-1] != material_phase:
        raise ValueError("base AQ v2 state did not adopt this material promotion receipt")
    validated_phase = validate_material_phase_receipt_v2(
        job_root,
        material_phase,
        require_current=True,
    )
    if (
        validated_phase.contract_id != promotion.material_phase_receipt.artifact_id
        or validated_phase.session_id != session_id
        or validated_phase.canonical_material_plan_sha256
        != promotion.canonical_material_plan_sha256
        or validated_phase.canonical_scene_spec_sha256
        != promotion.canonical_scene_spec_sha256
    ):
        raise ValueError("companion promotion differs from MaterialPhaseReceiptV2")
    neutral_preview = validate_promoted_codex_image_material_preview(
        job_root,
        promotion.neutral_preview,
        require_current=True,
    )
    if (
        neutral_preview.material_phase_receipt != promotion.material_phase_receipt
        or neutral_preview.raw_swatch_manifest != promotion.neutral_preview_manifest
        or neutral_preview.preview_image != promotion.neutral_preview_image
    ):
        raise ValueError("neutral preview does not bind the promoted material receipt")
    for artifact in promotion.provenance:
        validate_codex_image_artifact(job_root, artifact)
    required_artifacts = [
        promotion_receipt_artifact,
        promotion.generated_image_evidence,
        promotion.semantic_review,
        promotion.normalization_receipt,
        promotion.adoption,
        promotion.material_authoring_manifest,
        promotion.material_authoring_receipt,
        promotion.graph_compile_report,
        promotion.material_validation,
        promotion.neutral_preview,
        neutral_preview.renderer_script,
        neutral_preview.raw_swatch_manifest,
        promotion.neutral_preview_image,
    ]
    submitted_blend = quality_submission.authoring_blend
    if submitted_blend is None or (
        submitted_blend.sha256,
        submitted_blend.byte_size,
    ) != (
        neutral_preview.authoring_blend.sha256,
        neutral_preview.authoring_blend.byte_size,
    ):
        raise ValueError("IQ 0.2 submission omits the exact promoted authoring blend")
    required_quality = {(item.path, item.sha256) for item in required_artifacts}
    submitted = {(item.path, item.sha256) for item in quality_submission.quality_evidence}
    if not required_quality.issubset(submitted):
        raise ValueError("IQ 0.2 submission omits required ImageGen material evidence")
    return promotion


def advance_codex_image_material_loop_quality(
    job_id: str,
    session_id: str,
    *,
    promotion_receipt_artifact: CodexImageArtifact,
    quality_submission: QualitySubmissionV2 | dict[str, object],
    allow_disabled_experimental: bool = False,
) -> dict[str, Any]:
    """Validate the companion chain, then delegate one action to the existing AQ supervisor."""

    root = workspace.job_dir(job_id)
    submission = (
        quality_submission
        if isinstance(quality_submission, QualitySubmissionV2)
        else QualitySubmissionV2.model_validate(quality_submission)
    )
    status = get_autonomy_v2_status(job_id, session_id)
    raw_state = status.get("state")
    if not isinstance(raw_state, dict):
        raise ValueError("AQ v2 status omitted its strict current state")
    state = AutonomyStateV2.model_validate_json(
        json.dumps(raw_state, ensure_ascii=False)
    )
    if state.quality_terminal is not None:
        existing_loop_status = get_codex_image_material_loop_status(root, session_id)
        existing_terminal = existing_loop_status.get("terminal")
        if isinstance(existing_terminal, dict):
            promotion = validate_codex_image_material_promotion_receipt(
                root,
                promotion_receipt_artifact,
                require_current=True,
            )
            if (promotion.job_id, promotion.session_id) != (job_id, session_id):
                raise ValueError(
                    "material-loop recovery promotion belongs to another session"
                )
            terminal_status = existing_terminal.get("status")
            return {
                "advanced": False,
                "outcome": "material_loop_quality_terminal_already_recorded",
                "next_action": state.next_action,
                "state": raw_state,
                "state_artifact": status.get("state_artifact"),
                "material_loop_promotion": promotion_receipt_artifact.model_dump(
                    mode="json"
                ),
                "material_loop_terminal_status": terminal_status,
                "quality_companion_completed": terminal_status == "quality_approved",
                "human_reviewed": False,
            }
    if state.quality_terminal is None:
        validate_codex_image_material_quality_boundary(
            root,
            session_id=session_id,
            promotion_receipt_artifact=promotion_receipt_artifact,
            quality_submission=submission,
            state=state,
        )
    else:
        promotion = validate_codex_image_material_promotion_receipt(
            root,
            promotion_receipt_artifact,
            require_current=True,
        )
        if (promotion.job_id, promotion.session_id) != (job_id, session_id):
            raise ValueError("material-loop recovery promotion belongs to another session")
    result = advance_autonomy_v2(
        job_id,
        session_id,
        quality_submission=submission,
        allow_disabled_experimental=allow_disabled_experimental,
    )
    loop_status = get_codex_image_material_loop_status(root, session_id)
    terminal = loop_status.get("terminal")
    terminal_status = terminal.get("status") if isinstance(terminal, dict) else None
    return {
        **result,
        "material_loop_promotion": promotion_receipt_artifact.model_dump(mode="json"),
        "material_loop_terminal_status": terminal_status,
        "quality_companion_completed": terminal_status == "quality_approved",
        "human_reviewed": False,
    }


__all__ = [
    "advance_codex_image_material_loop_quality",
    "validate_codex_image_material_quality_boundary",
]
