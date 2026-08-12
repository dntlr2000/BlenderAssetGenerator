"""Focused companion-to-IQ boundary tests for promoted ImageGen materials."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2 import codex_image_material_quality_service as service
from codex_blender_modeler.autonomy_v2.models import AutonomyStateV2
from codex_blender_modeler.autonomy_v2.supervisor_service import QualitySubmissionV2
from codex_blender_modeler.codex_imagegen.models import CodexImageArtifact


def _artifact(name: str, *, media_type: str = "application/json") -> CodexImageArtifact:
    """Create one stable companion artifact identity for a no-IO validator fixture."""

    return CodexImageArtifact(
        artifact_id=name,
        kind=name.replace("_", "-"),
        path=f"evidence/{name}.json",
        sha256=(name.encode().hex() + "0" * 64)[:64],
        byte_size=1,
        media_type=media_type,
    )


def _fixture() -> tuple[
    CodexImageArtifact,
    object,
    AutonomyStateV2,
    QualitySubmissionV2,
]:
    """Create one complete promoted companion chain at the base IQ boundary."""

    material_phase = _artifact("material_phase_receipt")
    preview_manifest = _artifact("preview_manifest")
    preview_image = _artifact("preview_image", media_type="image/png")
    preview_blend = _artifact("preview_blend", media_type="application/x-blender")
    renderer_script = _artifact("renderer_script", media_type="text/x-python")
    neutral_preview = _artifact("neutral_preview")
    named = {
        key: _artifact(key)
        for key in (
            "generated_image_evidence",
            "semantic_review",
            "normalization_receipt",
            "adoption",
            "material_authoring_manifest",
            "material_authoring_receipt",
            "graph_compile_report",
            "material_validation",
        )
    }
    promotion_artifact = _artifact("promotion_receipt")
    promotion = SimpleNamespace(
        job_id="quality-loop-job",
        session_id="session-quality-loop",
        material_phase_receipt=material_phase,
        canonical_material_plan_sha256="a" * 64,
        canonical_scene_spec_sha256="b" * 64,
        neutral_preview=neutral_preview,
        neutral_preview_manifest=preview_manifest,
        neutral_preview_image=preview_image,
        provenance=[
            material_phase,
            preview_manifest,
            preview_image,
            neutral_preview,
            *named.values(),
        ],
        **named,
    )
    preview = SimpleNamespace(
        material_phase_receipt=material_phase,
        authoring_blend=preview_blend,
        renderer_script=renderer_script,
        raw_swatch_manifest=preview_manifest,
        preview_image=preview_image,
    )
    state = AutonomyStateV2.model_construct(
        job_id="quality-loop-job",
        phase="quality",
        next_action="run_integrated_quality",
        provenance=[
            service._aq_artifact(
                material_phase,
                kind="material_phase_receipt",
            )
        ],
    )
    required = [
        promotion_artifact,
        neutral_preview,
        renderer_script,
        preview_manifest,
        preview_image,
        *named.values(),
    ]
    submission = QualitySubmissionV2.model_construct(
        quality_evidence=[service._aq_artifact(item) for item in required],
        authoring_blend=service._aq_artifact(preview_blend),
    )
    return promotion_artifact, (promotion, preview), state, submission


def test_material_loop_quality_requires_complete_promotion_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accept a complete chain and reject IQ submission with one companion artifact absent."""

    promotion_artifact, models, state, submission = _fixture()
    promotion, preview = models

    monkeypatch.setattr(
        service,
        "validate_codex_image_material_promotion_receipt",
        lambda *_args, **_kwargs: promotion,
    )
    monkeypatch.setattr(
        service,
        "validate_promoted_codex_image_material_preview",
        lambda *_args, **_kwargs: preview,
    )
    monkeypatch.setattr(service, "validate_codex_image_artifact", lambda *_: tmp_path)
    monkeypatch.setattr(
        service,
        "validate_material_phase_receipt_v2",
        lambda *_args, **_kwargs: SimpleNamespace(
            contract_id=promotion.material_phase_receipt.artifact_id,
            session_id=promotion.session_id,
            canonical_material_plan_sha256=promotion.canonical_material_plan_sha256,
            canonical_scene_spec_sha256=promotion.canonical_scene_spec_sha256,
        ),
    )
    observed = service.validate_codex_image_material_quality_boundary(
        tmp_path,
        session_id=promotion.session_id,
        promotion_receipt_artifact=promotion_artifact,
        quality_submission=submission,
        state=state,
    )
    assert observed is promotion
    submission.quality_evidence.pop()
    with pytest.raises(ValueError, match="omits required ImageGen material evidence"):
        service.validate_codex_image_material_quality_boundary(
            tmp_path,
            session_id=promotion.session_id,
            promotion_receipt_artifact=promotion_artifact,
            quality_submission=submission,
            state=state,
        )

    wrong_blend = service._aq_artifact(_artifact("wrong_preview_blend"))
    submission.authoring_blend = wrong_blend.model_copy(
        update={"path": submission.authoring_blend.path}
    )
    with pytest.raises(ValueError, match="exact promoted authoring blend"):
        service.validate_codex_image_material_quality_boundary(
            tmp_path,
            session_id=promotion.session_id,
            promotion_receipt_artifact=promotion_artifact,
            quality_submission=submission,
            state=state,
        )


def test_material_loop_quality_rejects_wrong_base_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not let a companion receipt skip the existing base AQ material boundary."""

    promotion_artifact, models, state, submission = _fixture()
    promotion, _preview = models
    monkeypatch.setattr(
        service,
        "validate_codex_image_material_promotion_receipt",
        lambda *_args, **_kwargs: promotion,
    )
    state.phase = "authoring"
    with pytest.raises(PermissionError, match="not at the IQ 0.2 boundary"):
        service.validate_codex_image_material_quality_boundary(
            tmp_path,
            session_id=promotion.session_id,
            promotion_receipt_artifact=promotion_artifact,
            quality_submission=submission,
            state=state,
        )


def test_public_quality_wrapper_recovers_base_terminal_and_reports_real_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A base IQ crash window reaches companion recovery and reports its terminal status."""

    promotion_artifact, models, _state, submission = _fixture()
    promotion, _preview = models
    plan = service._aq_artifact(_artifact("quality_plan"), kind="plan")
    terminal = service._aq_artifact(_artifact("quality_terminal"), kind="quality_terminal")
    freeze = service._aq_artifact(_artifact("quality_freeze"), kind="source_freeze")
    recovered_state = AutonomyStateV2(
        contract_id="state-quality-recovery",
        state_id="state-quality-recovery",
        job_id="quality-loop-job",
        workflow_id="workflow-quality-loop",
        dispatch_id="dispatch-quality-loop",
        session_id="session-quality-loop",
        input_sha256="a" * 64,
        source_fingerprint="b" * 64,
        producer="pytest.material-loop-quality",
        provenance=[terminal],
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        plan=plan,
        sequence=5,
        phase="quality",
        status="quality_approved",
        next_action="plan_delivery",
        quality_terminal=terminal,
        source_freeze=freeze,
    )
    monkeypatch.setattr(service.workspace, "job_dir", lambda _job_id: tmp_path)
    monkeypatch.setattr(
        service,
        "get_autonomy_v2_status",
        lambda *_: {"state": recovered_state.model_dump(mode="json")},
    )
    monkeypatch.setattr(
        service,
        "validate_codex_image_material_quality_boundary",
        lambda *_args, **_kwargs: pytest.fail("pre-quality validator reran after IQ terminal"),
    )
    monkeypatch.setattr(
        service,
        "validate_codex_image_material_promotion_receipt",
        lambda *_args, **_kwargs: promotion,
    )
    monkeypatch.setattr(
        service,
        "advance_autonomy_v2",
        lambda *_args, **_kwargs: {
            "advanced": False,
            "outcome": "material_loop_quality_terminal_recovered",
        },
    )
    loop_statuses = iter(
        [
            {"terminal": None},
            {"terminal": {"status": "quality_approved"}},
        ]
    )
    monkeypatch.setattr(
        service,
        "get_codex_image_material_loop_status",
        lambda *_: next(loop_statuses),
    )

    result = service.advance_codex_image_material_loop_quality(
        "quality-loop-job",
        "session-quality-loop",
        promotion_receipt_artifact=promotion_artifact,
        quality_submission=submission,
        allow_disabled_experimental=True,
    )

    assert result["material_loop_terminal_status"] == "quality_approved"
    assert result["quality_companion_completed"] is True


def test_public_quality_wrapper_is_idempotent_after_companion_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing companion terminal is reported without advancing later AQ delivery."""

    promotion_artifact, models, _state, submission = _fixture()
    promotion, _preview = models
    plan = service._aq_artifact(_artifact("idempotent_plan"), kind="plan")
    terminal = service._aq_artifact(
        _artifact("idempotent_quality_terminal"), kind="quality_terminal"
    )
    freeze = service._aq_artifact(
        _artifact("idempotent_quality_freeze"), kind="source_freeze"
    )
    later_state = AutonomyStateV2(
        contract_id="state-quality-idempotent",
        state_id="state-quality-idempotent",
        job_id="quality-loop-job",
        workflow_id="workflow-quality-loop",
        dispatch_id="dispatch-quality-loop",
        session_id="session-quality-loop",
        input_sha256="a" * 64,
        source_fingerprint="b" * 64,
        producer="pytest.material-loop-quality",
        provenance=[terminal],
        created_at=datetime(2026, 8, 13, tzinfo=UTC),
        plan=plan,
        sequence=6,
        phase="delivery",
        status="quality_approved",
        next_action="plan_delivery",
        quality_terminal=terminal,
        source_freeze=freeze,
    )
    monkeypatch.setattr(service.workspace, "job_dir", lambda _job_id: tmp_path)
    monkeypatch.setattr(
        service,
        "get_autonomy_v2_status",
        lambda *_: {
            "state": later_state.model_dump(mode="json"),
            "state_artifact": {"path": "states/0006.json"},
        },
    )
    monkeypatch.setattr(
        service,
        "get_codex_image_material_loop_status",
        lambda *_: {"terminal": {"status": "quality_approved"}},
    )
    monkeypatch.setattr(
        service,
        "validate_codex_image_material_promotion_receipt",
        lambda *_args, **_kwargs: promotion,
    )
    monkeypatch.setattr(
        service,
        "advance_autonomy_v2",
        lambda *_args, **_kwargs: pytest.fail("idempotent quality call advanced delivery"),
    )

    result = service.advance_codex_image_material_loop_quality(
        "quality-loop-job",
        "session-quality-loop",
        promotion_receipt_artifact=promotion_artifact,
        quality_submission=submission,
        allow_disabled_experimental=True,
    )

    assert result["advanced"] is False
    assert result["outcome"] == "material_loop_quality_terminal_already_recorded"
    assert result["quality_companion_completed"] is True
