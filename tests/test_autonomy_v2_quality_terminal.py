"""AQ v2 quality review-bundle and terminal publication tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    QualityApprovedSourceFreeze,
)
from codex_blender_modeler.autonomy_v2.quality_terminal_service import (
    build_quality_review_bundle_v2,
    publish_quality_terminal_v2,
    validate_quality_review_bundle_v2,
    validate_quality_terminal_v2,
)
from codex_blender_modeler.blender_artifacts import stable_json_digest
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourMetricsV02,
    HardGateResultV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
    MultiviewMetricV02,
    ProducerIdentityV02,
    QualityFindingV02,
    ReentryDecisionV02,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def _file_artifact(
    root: Path,
    relative: str,
    *,
    artifact_id: str,
    kind: str,
    content: bytes,
) -> AQV2Artifact:
    """Write and bind one deterministic non-empty AQ v2 fixture file."""

    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return artifact_for_v2(
        root,
        path,
        artifact_id=artifact_id,
        kind=kind,
    )


def _quality_report(
    root: Path,
    *,
    outcome: str,
    evidence_sha256: str,
    suffix: str = "main",
) -> AQV2Artifact:
    """Publish one strict IQ 0.2 fixture for a selected terminal branch."""

    unscorable = outcome == "unscorable"
    blocked = outcome == "blocked"
    needs_revision = outcome == "needs_revision"
    contour = ContourMetricsV02(
        metric_id="reference.contour_v02",
        status="unscorable" if unscorable else "scored",
        authority="unavailable" if unscorable else "authoritative",
        evidence_ids=["reference.contour", "candidate.contour"],
        reference_mask_sha256=None if unscorable else evidence_sha256,
        candidate_mask_sha256=evidence_sha256,
        camera_sha256=evidence_sha256,
        width=32,
        height=32,
        reference_boundary_pixels=0 if unscorable else 20,
        candidate_boundary_pixels=20,
        boundary_tolerance_px=0.25,
        boundary_tolerance_diagonal_fraction=0.005,
        boundary_precision=None if unscorable else 0.95,
        boundary_recall=None if unscorable else 0.95,
        boundary_f_score=None if unscorable else 0.95,
        edge_distance_transform_chamfer_norm=None if unscorable else 0.01,
        limitations=["reference contour unavailable"] if unscorable else [],
    )
    gate_status = "failed" if blocked else "unscorable" if unscorable else "passed"
    hard_gate = HardGateResultV02(
        gate_id="gate.reference.contour_v02",
        status=gate_status,
        required=True,
        blocking=blocked,
        evidence_ids=["reference.contour", "candidate.contour"],
        reason_code=(
            "contour_failed"
            if blocked
            else "contour_unavailable"
            if unscorable
            else "contour_passed"
        ),
        message=(
            "Required contour evidence is blocked."
            if blocked
            else "Required contour evidence needs manual review."
            if unscorable
            else "Required contour evidence passed."
        ),
    )
    findings: list[QualityFindingV02] = []
    reentry: list[ReentryDecisionV02] = []
    revision_reasons: list[str] = []
    if needs_revision or unscorable:
        finding = QualityFindingV02(
            finding_id="finding.primary.silhouette",
            category="missing_evidence" if unscorable else "contour",
            severity="high",
            target_ids=["asset.primary"],
            evidence_ids=["reference.contour", "candidate.contour"],
            message="Primary silhouette requires another authoring review.",
        )
        findings = [finding]
        reentry = [
            ReentryDecisionV02(
                finding_id=finding.finding_id,
                category=finding.category,
                destination=(
                    "manual_evidence_review"
                    if unscorable
                    else "v0.4_structural_authoring"
                ),
                target_ids=finding.target_ids,
                reason_code="review.primary_silhouette",
                message="Review the primary silhouette against the fixed camera.",
            )
        ]
        revision_reasons = [finding.finding_id]
    report = IntegratedQualityReportV02(
        report_id=f"iq-v02-{suffix}",
        job_id=root.name,
        workflow_id="wf-quality-v2",
        dispatch_id="dispatch-quality-v2",
        source_fingerprint="f" * 64,
        camera_sha256=evidence_sha256,
        input_sha256="e" * 64,
        policy=IntegratedQualityPolicyV02(profile_id="quality.static-prop-v02"),
        contour=contour,
        multiview=MultiviewMetricV02(
            metric_id="structural.multiview_v02",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["optional multiview evidence was not supplied"],
        ),
        hard_gates=[hard_gate],
        findings=findings,
        reentry=reentry,
        outcome=outcome,
        quality_accepted=outcome == "passed",
        revision_reasons=revision_reasons,
        producer=ProducerIdentityV02(
            name="cbm_integrated_quality_v02",
            version="0.2.0",
        ),
        created_at=NOW,
    )
    path = root / "reports" / "integrated_quality_v02" / f"{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return artifact_for_v2(
        root,
        path,
        artifact_id=report.report_id,
        kind="integrated_quality_report",
    )


def _review_inputs(
    root: Path,
    *,
    outcome: str = "needs_revision",
) -> tuple[AQV2Artifact, AQV2Artifact, AQV2Artifact, AQV2Artifact]:
    """Create one quality report plus exact evidence, blend, and render artifacts."""

    evidence = _file_artifact(
        root,
        "quality/evidence.bin",
        artifact_id="quality-evidence",
        kind="quality_evidence",
        content=b"quality-evidence\n",
    )
    report = _quality_report(
        root,
        outcome=outcome,
        evidence_sha256=evidence.sha256,
    )
    blend = _file_artifact(
        root,
        "candidates/best_candidate.blend",
        artifact_id="best-candidate",
        kind="candidate_blend",
        content=b"BLENDER-v500",
    )
    render = _file_artifact(
        root,
        "candidates/render.png",
        artifact_id="representative-render",
        kind="representative_render",
        content=b"PNG-review-fixture",
    )
    return evidence, report, blend, render


def _quality_freeze(
    root: Path,
    *,
    session_id: str,
    report: AQV2Artifact,
    quality_evidence: AQV2Artifact,
) -> tuple[QualityApprovedSourceFreeze, AQV2Artifact]:
    """Publish one internally consistent source-freeze fixture for terminal validation."""

    scene = _file_artifact(
        root,
        "analysis/scene_spec.json",
        artifact_id="scene-spec",
        kind="scene_spec",
        content=b'{"schema_version":"0.2.0"}\n',
    )
    authoring_blend = _file_artifact(
        root,
        "blender/scene.blend",
        artifact_id="authoring-blend",
        kind="blend",
        content=b"BLENDER-v500-source",
    )
    build = _file_artifact(
        root,
        "build/build_provenance.json",
        artifact_id="build-provenance",
        kind="build_provenance",
        content=b'{"build":"exact"}\n',
    )
    material = _file_artifact(
        root,
        "analysis/material_plan.json",
        artifact_id="material-plan",
        kind="material_plan",
        content=b'{"material":"exact"}\n',
    )
    survival = _file_artifact(
        root,
        "reports/geometry_survival.json",
        artifact_id="geometry-survival",
        kind="geometry_survival",
        content=b'{"survival":"passed"}\n',
    )
    geometry_receipt = _file_artifact(
        root,
        "aq2/quality-pass/receipt.json",
        artifact_id=f"geometry-validation-{session_id}",
        kind="geometry_candidate_validation_receipt",
        content=b'{"geometry":"accepted"}\n',
    )
    material_receipt = _file_artifact(
        root,
        f"production/autonomy_v2/{session_id}/material_phase/0001/promotion_receipt.json",
        artifact_id=f"material-phase-{session_id}",
        kind="material_phase_receipt",
        content=b'{"material":"accepted"}\n',
    )
    frozen = {
        "scene_spec": scene.sha256,
        "authoring_blend": authoring_blend.sha256,
        "build_provenance": build.sha256,
        "integrated_quality_report": report.sha256,
        "quality_evidence": [quality_evidence.sha256],
        "material_plan": material.sha256,
        "shader_recipes": [],
        "texture_manifests": [],
        "geometry_payloads": [],
        "geometry_intent_survival": survival.sha256,
        "geometry_candidate_validation_receipt": geometry_receipt.sha256,
        "material_phase_receipt": material_receipt.sha256,
        "quality_source_fingerprint": "f" * 64,
        "quality_input_sha256": "e" * 64,
        "v07_source_fingerprint": "c" * 64,
    }
    provenance = [
        scene,
        authoring_blend,
        build,
        report,
        quality_evidence,
        material,
        survival,
        geometry_receipt,
        material_receipt,
    ]
    freeze = QualityApprovedSourceFreeze(
        contract_id=f"quality-freeze-{session_id}",
        freeze_id=f"quality-freeze-{session_id}",
        job_id=root.name,
        workflow_id="wf-quality-v2",
        dispatch_id="dispatch-quality-v2",
        session_id=session_id,
        input_sha256=stable_json_digest({"report": report.sha256}),
        source_fingerprint=stable_json_digest(frozen),
        producer="codex_blender_modeler.autonomy_v2.delivery_service",
        provenance=provenance,
        created_at=NOW,
        scene_spec=scene,
        authoring_blend=authoring_blend,
        build_provenance=build,
        integrated_quality_report=report,
        quality_evidence=[quality_evidence],
        material_plan=material,
        shader_recipes=[],
        texture_manifests=[],
        geometry_payloads=[],
        geometry_intent_survival=survival,
        geometry_candidate_validation_receipt=geometry_receipt,
        material_phase_receipt=material_receipt,
        v07_source_fingerprint="c" * 64,
        frozen_source_sha256=stable_json_digest(frozen),
    )
    path = root / "production" / "autonomy_v2" / session_id / "source_freeze.json"
    return freeze, write_immutable_v2_model(root, path, freeze)


def test_review_bundle_and_terminal_bind_exact_nonpass_evidence(tmp_path: Path) -> None:
    """Review publication derives actions and remains explicitly non-production."""

    root = tmp_path / "quality_job"
    root.mkdir()
    _evidence, report, blend, render = _review_inputs(root)
    bundle, bundle_artifact = build_quality_review_bundle_v2(
        job_root=root,
        session_id="quality-review-session",
        integrated_quality_report=report,
        candidate_blend=blend,
        representative_render=render,
        created_at=NOW,
    )

    assert bundle.quality_outcome == "needs_revision"
    assert bundle.production_ready is False
    assert bundle.destination_handoff_eligible is False
    assert bundle.canonical_unchanged is True
    assert bundle.recommended_actions[0].destination == "v0.4_structural_authoring"
    assert validate_quality_review_bundle_v2(root, bundle_artifact) == bundle

    terminal, terminal_artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id="quality-review-session",
        status="review_required",
        integrated_quality_report=report,
        review_bundle=bundle_artifact,
        reason="IQ 0.2 requires another structural authoring review.",
        created_at=NOW,
    )
    assert terminal.status == "review_required"
    assert terminal.source_freeze is None
    assert terminal.production_ready is False
    assert validate_quality_terminal_v2(root, terminal_artifact) == terminal


def test_review_bundle_rejects_pass_and_arbitrary_json(tmp_path: Path) -> None:
    """Passing IQ and untyped JSON can never masquerade as review-only evidence."""

    root = tmp_path / "quality_job"
    root.mkdir()
    evidence, passed, blend, render = _review_inputs(root, outcome="passed")
    del evidence
    with pytest.raises(ValueError, match="needs_revision or unscorable"):
        build_quality_review_bundle_v2(
            job_root=root,
            session_id="invalid-review-session",
            integrated_quality_report=passed,
            candidate_blend=blend,
            representative_render=render,
            created_at=NOW,
        )

    _evidence, nonpass, _blend, _render = _review_inputs(
        root,
        outcome="needs_revision",
    )
    arbitrary = _file_artifact(
        root,
        "production/autonomy_v2/arbitrary-review/quality_review_bundle.json",
        artifact_id="arbitrary-review",
        kind="quality-review-bundle",
        content=b'{"production_ready":false}\n',
    )
    with pytest.raises(ValueError):
        publish_quality_terminal_v2(
            job_root=root,
            session_id="arbitrary-review",
            status="review_required",
            integrated_quality_report=nonpass,
            review_bundle=arbitrary,
            reason="arbitrary JSON must fail strict parsing",
            created_at=NOW,
        )


def test_unscorable_report_delivers_manual_review_without_quality_claim(
    tmp_path: Path,
) -> None:
    """Unscorable IQ produces review evidence while retaining a non-pass outcome."""

    root = tmp_path / "quality_job"
    root.mkdir()
    _evidence, report, blend, render = _review_inputs(root, outcome="unscorable")
    bundle, bundle_artifact = build_quality_review_bundle_v2(
        job_root=root,
        session_id="quality-unscorable-session",
        integrated_quality_report=report,
        candidate_blend=blend,
        representative_render=render,
        created_at=NOW,
    )
    terminal, _terminal_artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id="quality-unscorable-session",
        status="review_required",
        integrated_quality_report=report,
        review_bundle=bundle_artifact,
        reason="Required contour evidence is unscorable.",
        created_at=NOW,
    )

    assert bundle.quality_outcome == "unscorable"
    assert bundle.recommended_actions[0].destination == "manual_evidence_review"
    assert terminal.status == "review_required"
    assert terminal.production_ready is False


def test_quality_approved_terminal_revalidates_exact_source_freeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A passed terminal survives only while every frozen source remains exact."""

    root = tmp_path / "quality_job"
    root.mkdir()
    evidence, report, _blend, _render = _review_inputs(root, outcome="passed")
    freeze, freeze_artifact = _quality_freeze(
        root,
        session_id="quality-pass-session",
        report=report,
        quality_evidence=evidence,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.delivery_service.collect_source_provenance",
        lambda _root, _job: SimpleNamespace(source_fingerprint="c" * 64),
    )

    def validate_frozen_files(job_root: Path, value: QualityApprovedSourceFreeze) -> None:
        """Rehash every named freeze artifact for this isolated terminal test."""

        for artifact in value.provenance:
            validate_v2_artifact(job_root, artifact)

    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.quality_terminal_service.validate_quality_source_freeze",
        validate_frozen_files,
    )

    terminal, terminal_artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id="quality-pass-session",
        status="quality_approved",
        integrated_quality_report=report,
        source_freeze=freeze_artifact,
        reason="All required IQ 0.2 hard gates passed.",
        created_at=NOW,
    )
    assert terminal.status == "quality_approved"
    assert terminal.source_freeze == freeze_artifact
    assert terminal.review_bundle is None

    (root / freeze.scene_spec.path).write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        validate_quality_terminal_v2(root, terminal_artifact)


@pytest.mark.parametrize(
    ("status", "report_outcome"),
    [("blocked", "blocked"), ("failed", "needs_revision")],
)
def test_blocked_and_failed_terminals_bind_only_exact_report(
    tmp_path: Path,
    status: str,
    report_outcome: str,
) -> None:
    """Blocked and failed terminals carry no review or source-freeze claim."""

    root = tmp_path / "quality_job"
    root.mkdir()
    _evidence, report, _blend, _render = _review_inputs(root, outcome=report_outcome)
    terminal, terminal_artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id=f"quality-{status}-session",
        status=status,
        integrated_quality_report=report,
        reason=f"Exact IQ 0.2 evidence produced a {status} terminal.",
        created_at=NOW,
    )

    assert terminal.source_freeze is None
    assert terminal.review_bundle is None
    assert terminal.provenance == [report]
    assert validate_quality_terminal_v2(root, terminal_artifact) == terminal


def test_quality_terminal_does_not_downgrade_pass_or_overwrite_history(
    tmp_path: Path,
) -> None:
    """Accepted IQ cannot become failed, and an immutable terminal cannot be replaced."""

    root = tmp_path / "quality_job"
    root.mkdir()
    _evidence, passed, _blend, _render = _review_inputs(root, outcome="passed")
    with pytest.raises(ValueError, match="cannot downgrade"):
        publish_quality_terminal_v2(
            job_root=root,
            session_id="quality-failed-session",
            status="failed",
            integrated_quality_report=passed,
            reason="A passed report cannot be downgraded.",
            created_at=NOW,
        )

    _evidence, blocked, _blend, _render = _review_inputs(root, outcome="blocked")
    publish_quality_terminal_v2(
        job_root=root,
        session_id="quality-blocked-session",
        status="blocked",
        integrated_quality_report=blocked,
        reason="Blocked hard gate.",
        created_at=NOW,
    )
    with pytest.raises(FileExistsError):
        publish_quality_terminal_v2(
            job_root=root,
            session_id="quality-blocked-session",
            status="blocked",
            integrated_quality_report=blocked,
            reason="Blocked hard gate.",
            created_at=NOW,
        )
