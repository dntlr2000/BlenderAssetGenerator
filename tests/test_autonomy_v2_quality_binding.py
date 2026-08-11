"""Focused AQ v2 canonical-quality and promotion-evidence binding tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2.delivery_service import (
    validate_quality_promotion_evidence_v2,
)
from codex_blender_modeler.autonomy_v2.models import AQV2Artifact
from codex_blender_modeler.blender_artifacts import stable_json_digest


def _artifact(name: str, kind: str) -> AQV2Artifact:
    """Create one deterministic exact artifact binding for pure host-boundary tests."""

    return AQV2Artifact(
        artifact_id=name,
        kind=kind,
        path=f"production/autonomy_v2/quality-binding/{name}.json",
        sha256=stable_json_digest({"artifact": name}),
        byte_size=32,
    )


def test_quality_promotion_rejects_survival_outside_accepted_geometry_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a submitted survival report not named by the accepted geometry receipt."""

    root = tmp_path / "aq_v2_delivery"
    root.mkdir()
    geometry_receipt_artifact = _artifact(
        "geometry-receipt-binding",
        "geometry_candidate_validation_receipt",
    )
    material_receipt_artifact = _artifact(
        "material-receipt-binding",
        "material_phase_receipt",
    )
    accepted_survival = _artifact("accepted-survival", "geometry_survival")
    substituted_survival = _artifact("substituted-survival", "geometry_survival")
    modeling = _artifact("canonical-modeling", "modeling_plan")
    scene = _artifact("canonical-scene-binding", "scene_spec")
    old_blend = _artifact("geometry-blend-binding", "blend")
    current_blend = _artifact("material-blend-binding", "blend")
    build = _artifact("material-build-binding", "build_provenance")
    material_plan = _artifact("material-plan-binding", "material_plan")
    source_snapshot_artifact = _artifact(
        "candidate-geometry-snapshot",
        "geometry_snapshot",
    )
    target_snapshot_artifact = _artifact(
        "canonical-geometry-snapshot",
        "geometry_snapshot",
    )
    source_snapshot = SimpleNamespace(stage="candidate")
    target_snapshot = SimpleNamespace(stage="canonical")
    survival_model = SimpleNamespace(report_id="survival-exact", overall_status="exact")
    geometry_receipt = SimpleNamespace(
        job_id="aq_v2_delivery",
        workflow_id="wf-aq-v2-delivery",
        dispatch_id="dispatch-aq-v2-delivery",
        session_id="aq-v2-delivery",
        geometry_intent_survival=accepted_survival,
        provenance=[],
        canonical_blend=old_blend,
        candidate_geometry_snapshot=source_snapshot_artifact,
        canonical_geometry_snapshot=target_snapshot_artifact,
        canonical_modeling_plan=modeling,
        canonical_scene_spec=scene,
    )
    material_receipt = SimpleNamespace(
        job_id="aq_v2_delivery",
        workflow_id="wf-aq-v2-delivery",
        dispatch_id="dispatch-aq-v2-delivery",
        session_id="aq-v2-delivery",
        provenance=[],
        canonical_scene_spec_sha256=scene.sha256,
        canonical_material_plan_sha256=material_plan.sha256,
        authoring_blend_snapshot=current_blend,
        build_provenance_snapshot=build,
        build_fingerprint="f" * 64,
    )

    def fake_load(
        _root: Path,
        artifact: object,
        _model: object,
    ) -> object:
        """Return the exact parsed receipt or snapshot selected by artifact identity."""

        values = {
            geometry_receipt_artifact.path: geometry_receipt,
            material_receipt_artifact.path: material_receipt,
            source_snapshot_artifact.path: source_snapshot,
            target_snapshot_artifact.path: target_snapshot,
            accepted_survival.path: survival_model,
        }
        return values[artifact.path]  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service._load_model",
        fake_load,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.artifact_for_v2",
        lambda *_args, **_kwargs: modeling,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service._load_build_snapshot",
        lambda *_args, **_kwargs: {"fingerprint": "f" * 64},
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.compare_geometry_stage_snapshots_v02",
        lambda **_kwargs: survival_model,
    )

    with pytest.raises(ValueError, match="not the accepted promotion evidence"):
        validate_quality_promotion_evidence_v2(
            job_root=root,
            job_id="aq_v2_delivery",
            workflow_id="wf-aq-v2-delivery",
            dispatch_id="dispatch-aq-v2-delivery",
            session_id="aq-v2-delivery",
            geometry_candidate_validation_receipt=geometry_receipt_artifact,
            material_phase_receipt=material_receipt_artifact,
            geometry_intent_survival=substituted_survival,
            scene_spec=scene,
            authoring_blend=current_blend,
            build_provenance=build,
            material_plan=material_plan,
        )
