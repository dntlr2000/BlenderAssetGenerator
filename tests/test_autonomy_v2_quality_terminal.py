"""AQ v2 quality review-bundle and terminal publication tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_blender_modeler.autonomy_v2 import quality_terminal_service
from codex_blender_modeler.autonomy_v2.delivery_service import (
    artifact_for_v2,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from codex_blender_modeler.autonomy_v2.human_quality_review_service import (
    build_human_quality_review_bundle_v2,
    validate_human_quality_disposition_binding_v2,
    validate_human_quality_review_bundle_v2,
)
from codex_blender_modeler.autonomy_v2.models import (
    AQV2Artifact,
    DeliveryPlan,
    DeliveryRequest,
    QualityApprovedSourceFreeze,
)
from codex_blender_modeler.autonomy_v2.profiles import delivery_profile
from codex_blender_modeler.autonomy_v2.quality_terminal_service import (
    build_quality_review_bundle_v2,
    publish_quality_terminal_v2,
    validate_quality_review_bundle_v2,
    validate_quality_terminal_v2,
)
from codex_blender_modeler.blender_artifacts import sha256_file, stable_json_digest
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourMetricsV02,
    FixedCameraVisibilityMetricV02,
    HardGateResultV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
    MultiviewMetricV02,
    ProducerIdentityV02,
    QualityFindingV02,
    ReentryDecisionV02,
)
from codex_blender_modeler.production.activation_models import (
    ActivationArtifact,
    ActivationHumanQualityDisposition,
)
from codex_blender_modeler.qa.models import RenderPassManifest, RenderPassRecord

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


def test_quality_terminal_freeze_hashes_include_fixed_camera_visibility(
    tmp_path: Path,
) -> None:
    """Require all four direct visibility image bindings in an approved source freeze."""

    root = tmp_path / "quality_visibility_hashes"
    root.mkdir()
    evidence, report_artifact, _blend, _render = _review_inputs(
        root,
        outcome="passed",
    )
    report = IntegratedQualityReportV02.model_validate_json(
        (root / report_artifact.path).read_bytes()
    )
    visibility = FixedCameraVisibilityMetricV02(
        metric_id="reference.fixed_camera_visibility_v02",
        status="unscorable",
        authority="unavailable",
        evidence_ids=[
            "visibility-reference-image",
            "visibility-candidate-beauty",
            "visibility-reference-mask",
            "visibility-candidate-mask",
        ],
        reference_image_sha256="a" * 64,
        candidate_beauty_sha256="b" * 64,
        reference_mask_sha256="c" * 64,
        candidate_mask_sha256="d" * 64,
        camera_sha256=evidence.sha256,
        width=32,
        height=32,
        mask_erosion_diagonal_fraction=0.008,
        mask_erosion_radius_px=1,
        reference_interior_pixels=0,
        candidate_interior_pixels=0,
        informative_channel_count=0,
        limitations=["direct visibility fixture intentionally unavailable"],
    )
    bound_report = report.model_copy(update={"fixed_camera_visibility": visibility})
    hashes = quality_terminal_service._quality_report_evidence_hashes(bound_report)
    assert {"a" * 64, "b" * 64, "c" * 64, "d" * 64} <= hashes


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


def _delivery_plan(
    root: Path,
    *,
    session_id: str,
    freeze: AQV2Artifact,
) -> AQV2Artifact:
    """Publish one deterministic pending portable-delivery plan fixture."""

    authorization = _file_artifact(
        root,
        f"production/autonomy_v2/{session_id}/root_authorization.json",
        artifact_id=f"authorization-{session_id}",
        kind="root-authorization",
        content=b'{"authorization":"fixture"}\n',
    )
    plan = DeliveryPlan(
        contract_id=f"delivery-plan-{session_id}",
        job_id=root.name,
        workflow_id="wf-quality-v2",
        dispatch_id="dispatch-quality-v2",
        session_id=session_id,
        input_sha256="1" * 64,
        source_fingerprint="2" * 64,
        producer="codex_blender_modeler.autonomy_v2.delivery_service",
        provenance=[authorization, freeze],
        created_at=NOW,
        plan_id=f"delivery-plan-{session_id}",
        root_authorization=authorization,
        source_freeze=freeze,
        requests=[
            DeliveryRequest(
                delivery_id="delivery-01-gltf",
                profile=delivery_profile("portable_gltf"),
                source_freeze=freeze,
                run_id=f"{session_id}-gltf-run",
                package_id=f"{session_id}-gltf-package",
                status="planned",
            )
        ],
    )
    return write_immutable_v2_model(
        root,
        root / f"production/autonomy_v2/{session_id}/delivery_plan.json",
        plan,
    )


def _human_disposition(
    repository: Path,
    root: Path,
    *,
    skill_run_id: str,
    disposition: str = "needs_revision",
) -> tuple[ActivationHumanQualityDisposition, Path]:
    """Publish one exact activation disposition and Blender seven-pass fixture."""

    qa_root = root / "qa/runs/human-review-v06"
    pass_records: list[RenderPassRecord] = []
    for index, kind in enumerate(
        (
            "beauty",
            "silhouette",
            "object_id",
            "material_id",
            "normal",
            "depth",
            "wireframe",
        ),
        start=1,
    ):
        path = qa_root / "passes" / f"{kind}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"PNG-{kind}-{index}\n".encode())
        pass_records.append(
            RenderPassRecord(
                kind=kind,
                path=f"passes/{kind}.png",
                sha256=sha256_file(path),
                width=32,
                height=32,
                encoding="png-rgb8",
            )
        )
    manifest = RenderPassManifest(
        job_id=root.name,
        run_id="human-review-v06",
        scene_spec_sha256="3" * 64,
        camera_fingerprint="4" * 64,
        build_fingerprint="5" * 64,
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="DEFAULT",
        resolution=(32, 32),
        passes=pass_records,
    )
    manifest_path = qa_root / "render_pass_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    beauty_path = qa_root / "passes/beauty.png"
    beauty = ActivationArtifact(
        artifact_id="human-review-beauty",
        kind="representative_beauty",
        path=beauty_path.relative_to(repository).as_posix(),
        sha256=sha256_file(beauty_path),
        byte_size=beauty_path.stat().st_size,
    )
    payload = {
        "schema_version": "0.1.0",
        "job_id": root.name,
        "skill_run_id": skill_run_id,
        "representative_beauty": beauty.model_dump(mode="json"),
        "disposition": disposition,
        "reviewer_identity": "fixture-reviewer",
        "observed_statement_sha256": "6" * 64,
        "is_user_approval": False,
        "is_quality_disposition": True,
        "recorded_at": NOW.isoformat().replace("+00:00", "Z"),
    }
    digest = stable_json_digest(payload)
    model = ActivationHumanQualityDisposition(
        disposition_id=f"activation-quality-disposition-{digest[:24]}",
        disposition_sha256=digest,
        **{**payload, "recorded_at": NOW},
    )
    path = repository / "reports" / f"{disposition}_disposition.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return model, path


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


def test_human_nonpass_after_machine_pass_publishes_review_only_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-IQ human review binds exact Beauty evidence and never executes delivery."""

    repository = tmp_path
    root = repository / "workspaces" / "human_review_job"
    root.mkdir(parents=True)
    evidence, report, _blend, _render = _review_inputs(root, outcome="passed")
    _freeze, freeze_artifact = _quality_freeze(
        root,
        session_id="human-review-session",
        report=report,
        quality_evidence=evidence,
    )

    def validate_frozen_files(
        job_root: Path,
        value: QualityApprovedSourceFreeze,
    ) -> None:
        """Rehash every named source without repository provenance discovery."""

        for artifact in value.provenance:
            validate_v2_artifact(job_root, artifact)

    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.quality_terminal_service."
        "validate_quality_source_freeze",
        validate_frozen_files,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.autonomy_v2.human_quality_review_service."
        "validate_quality_source_freeze",
        validate_frozen_files,
    )
    terminal, terminal_artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id="human-review-session",
        status="quality_approved",
        integrated_quality_report=report,
        source_freeze=freeze_artifact,
        reason="Machine IQ passed before external human visual review.",
        created_at=NOW,
    )
    delivery_plan_artifact = _delivery_plan(
        root,
        session_id="human-review-session",
        freeze=freeze_artifact,
    )
    disposition, disposition_path = _human_disposition(
        repository,
        root,
        skill_run_id="human-review-skill-run",
    )

    bundle, bundle_artifact = build_human_quality_review_bundle_v2(
        repository_root=repository,
        job_root=root,
        session_id="human-review-session",
        skill_run_id="human-review-skill-run",
        disposition_path=disposition_path,
        machine_quality_terminal=terminal_artifact,
        source_freeze=freeze_artifact,
        delivery_plan=delivery_plan_artifact,
        delivery_runs=0,
        created_at=NOW,
    )

    assert terminal.status == "quality_approved"
    assert bundle.machine_quality_outcome == "passed"
    assert bundle.human_disposition == "needs_revision"
    assert bundle.delivery_runs == 0
    assert bundle.production_ready is False
    assert bundle.destination_handoff_eligible is False
    assert bundle.representative_render.sha256 == (
        disposition.representative_beauty.sha256
    )
    assert validate_human_quality_review_bundle_v2(root, bundle_artifact) == bundle
    assert (
        validate_human_quality_disposition_binding_v2(
            repository_root=repository,
            job_root=root,
            bundle=bundle,
            disposition_path=disposition_path,
        )
        == disposition
    )

    _accepted, accepted_path = _human_disposition(
        repository,
        root,
        skill_run_id="human-review-skill-run",
        disposition="accepted",
    )
    with pytest.raises(ValueError, match="differs from its exact review bundle"):
        validate_human_quality_disposition_binding_v2(
            repository_root=repository,
            job_root=root,
            bundle=bundle,
            disposition_path=accepted_path,
        )


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
    terminal_path = (
        root / "production/autonomy_v2/quality-blocked-session/quality_terminal.json"
    )
    original = terminal_path.read_bytes()
    replayed, _artifact = publish_quality_terminal_v2(
        job_root=root,
        session_id="quality-blocked-session",
        status="blocked",
        integrated_quality_report=blocked,
        reason="Blocked hard gate.",
        created_at=NOW,
    )
    assert replayed.status == "blocked"
    assert terminal_path.read_bytes() == original
