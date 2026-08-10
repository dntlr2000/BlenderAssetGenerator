"""Focused tests for Autonomous Quality integrated evidence and ranking."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from codex_blender_modeler.integrated_quality import (
    AxisThreshold,
    EvidenceAvailability,
    ProducerIdentity,
    QualityArtifact,
    QualityAxisResult,
    QualityGateProfile,
    QualityGateRule,
    QualityMetric,
    QualityProvenance,
    RankableQualityCandidate,
    build_default_quality_gate_profile,
    build_integrated_quality_report,
    evaluate_hard_gates,
    quality_artifact_input_sha256,
    rank_quality_candidates,
    reference_alignment_axis,
    write_integrated_quality_evidence,
)
from codex_blender_modeler.integrated_quality import reporting as quality_reporting
from codex_blender_modeler.qa.models import (
    BoundingBoxMetric,
    DirectVisualMetrics,
    QAFinding,
    VisualQAReport,
)

NOW = datetime(2026, 8, 10, 1, 2, 3, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _producer() -> ProducerIdentity:
    """Return one deterministic producer identity for isolated contracts."""

    return ProducerIdentity(name="integrated_quality", version="0.1.0")


def _provenance() -> QualityProvenance:
    """Create exact identity and artifact provenance for one QA fixture."""

    return QualityProvenance(
        job_id="quality_test",
        workflow_id="workflow.001",
        dispatch_id="dispatch.001",
        source_fingerprint=SHA_A,
        input_sha256=SHA_B,
        artifacts=[
            QualityArtifact(
                artifact_id="artifact.visual_qa",
                kind="visual_qa_report",
                relative_path="qa/runs/run-001/visual_qa_report.json",
                sha256=SHA_C,
                producer=ProducerIdentity(name="visual_qa", version="0.6.0"),
                produced_at=NOW,
            )
        ],
    )


def _visual_report(
    score: float,
    *,
    silhouette_iou: float = 0.72,
    findings: list[QAFinding] | None = None,
) -> VisualQAReport:
    """Build a canonical V0.6 report whose direct score must remain unchanged."""

    return VisualQAReport(
        job_id="quality_test",
        run_id="run-001",
        request_sha256=SHA_A,
        camera_fingerprint=SHA_B,
        direct_metrics=DirectVisualMetrics(
            scoring_version="semantic_bbox_v2",
            silhouette_iou=silhouette_iou,
            silhouette_union_fraction=0.5,
            global_bbox=BoundingBoxMetric(
                reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
                rendered_bbox_norm=(0.12, 0.1, 0.88, 0.9),
                center_error_norm=0.01,
                size_error_norm=0.02,
            ),
            semantic_deviations=[],
            overall_direct_score=score,
        ),
        findings=findings or [],
        generated_target_status="not_requested",
        warnings=[],
    )


def test_reference_axis_uses_worst_critical_metric_not_only_direct_score() -> None:
    """A passing direct score cannot conceal a failed canonical silhouette metric."""

    axis = reference_alignment_axis(
        _visual_report(0.92, silhouette_iou=0.42),
        threshold=AxisThreshold(
            axis="reference_alignment",
            pass_score=0.8,
            warning_score=0.6,
        ),
        evidence_id="evidence.reference",
    )

    assert axis.status == "failed"
    assert axis.score == 0.92
    assert next(
        metric for metric in axis.metrics if metric.metric_id == "reference.silhouette_iou"
    ).status == "failed"


def test_reference_axis_fails_authoritative_high_findings_but_not_advisory_only() -> None:
    """High direct evidence is critical while generated-target-only findings stay advisory."""

    direct_finding = QAFinding(
        id="finding.primary_body",
        target_ids=["asset.body"],
        issue_type="proportion",
        severity="high",
        description="The primary body proportion remains incorrect.",
        evidence_sources=["direct_reference"],
        confidence=0.95,
    )
    advisory_finding = QAFinding(
        id="finding.generated_advice",
        target_ids=["asset.body"],
        issue_type="other",
        severity="high",
        description="Generated target advice is non-authoritative.",
        evidence_sources=["generated_target"],
        confidence=0.8,
    )
    threshold = AxisThreshold(
        axis="reference_alignment",
        pass_score=0.8,
        warning_score=0.6,
    )

    failed = reference_alignment_axis(
        _visual_report(0.9, silhouette_iou=0.9, findings=[direct_finding]),
        threshold=threshold,
        evidence_id="evidence.reference",
    )
    passed = reference_alignment_axis(
        _visual_report(0.9, silhouette_iou=0.9, findings=[advisory_finding]),
        threshold=threshold,
        evidence_id="evidence.reference",
    )

    assert failed.status == "failed"
    assert passed.status == "passed"
    finding_metric = next(
        metric
        for metric in failed.metrics
        if metric.metric_id == "reference.authoritative_high_finding_count"
    )
    assert finding_metric.value == 1
    assert finding_metric.status == "failed"


def _availability() -> list[EvidenceAvailability]:
    """Declare direct QA as available and the remaining staged evidence as unavailable."""

    return [
        EvidenceAvailability(
            evidence_id="evidence.reference",
            axis="reference_alignment",
            status="available",
            artifact_id="artifact.visual_qa",
            confidence=1.0,
            reason="Canonical fixed-camera QA is current.",
        ),
        EvidenceAvailability(
            evidence_id="evidence.structural",
            axis="structural_integrity",
            status="unavailable",
            confidence=0,
            reason="Structural fixture intentionally omitted.",
        ),
        EvidenceAvailability(
            evidence_id="evidence.material",
            axis="material_fidelity",
            status="unavailable",
            confidence=0,
            reason="Material fixture intentionally omitted.",
        ),
        EvidenceAvailability(
            evidence_id="evidence.production",
            axis="production_readiness",
            status="unavailable",
            confidence=0,
            reason="V0.7 fixture intentionally omitted.",
        ),
    ]


def test_default_profile_is_strict_and_identity_bound() -> None:
    """The static-prop profile freezes all four axes and terminal hard gates."""

    profile = build_default_quality_gate_profile(
        profile_id="autonomous_static_prop_v1",
        job_id="quality_test",
        workflow_id="workflow.001",
        dispatch_id="dispatch.001",
        source_fingerprint=SHA_A,
        producer=_producer(),
        created_at=NOW,
    )

    assert {item.axis for item in profile.axis_thresholds} == {
        "reference_alignment",
        "structural_integrity",
        "material_fidelity",
        "production_readiness",
    }
    assert {item.gate_id for item in profile.gate_rules} == {
        "gate.structural_integrity",
        "gate.material_fidelity",
        "gate.production_readiness",
    }
    assert profile.input_sha256 == quality_artifact_input_sha256([])
    assert profile.provenance == []


def test_quality_profile_rejects_missing_or_stale_aq_envelopes() -> None:
    """Reject omitted AQ 0.1.0 envelope fields and stale exact provenance bindings."""

    profile = build_default_quality_gate_profile(
        profile_id="autonomous_static_prop_v1",
        job_id="quality_test",
        workflow_id="workflow.001",
        dispatch_id="dispatch.001",
        source_fingerprint=SHA_A,
        producer=_producer(),
        provenance=_provenance().artifacts,
        created_at=NOW,
    )
    missing = profile.model_dump(mode="json")
    missing.pop("input_sha256")
    missing.pop("provenance")
    with pytest.raises(ValidationError):
        QualityGateProfile.model_validate_json(json.dumps(missing))
    partial = profile.model_dump(mode="json")
    partial.pop("input_sha256")
    with pytest.raises(ValidationError):
        QualityGateProfile.model_validate_json(json.dumps(partial))
    stale = profile.model_dump(mode="json")
    stale["provenance"][0]["sha256"] = SHA_A
    with pytest.raises(ValidationError, match="differs from provenance"):
        QualityGateProfile.model_validate_json(json.dumps(stale))


def test_integrated_report_preserves_v06_score_and_marks_missing_axes_unscorable() -> None:
    """Missing staged evidence is unscorable and never changes the canonical direct score."""

    profile = build_default_quality_gate_profile(
        profile_id="autonomous_static_prop_v1",
        job_id="quality_test",
        workflow_id="workflow.001",
        dispatch_id="dispatch.001",
        source_fingerprint=SHA_A,
        producer=_producer(),
        created_at=NOW,
    )
    report = build_integrated_quality_report(
        report_id="quality.report.001",
        provenance=_provenance(),
        gate_profile=profile,
        gate_profile_sha256=SHA_C,
        producer=_producer(),
        created_at=NOW,
        evidence_availability=_availability(),
        reference_evidence_id="evidence.reference",
        structural_evidence_id="evidence.structural",
        material_evidence_id="evidence.material",
        production_evidence_id="evidence.production",
        visual_qa=_visual_report(0.706882),
    )

    reference = next(item for item in report.axes if item.axis == "reference_alignment")
    assert report.legacy_v06_direct_score == 0.706882
    assert reference.metrics[0].value == 0.706882
    assert report.outcome == "unscorable"
    assert report.quality_accepted is False
    assert report.blocking_reasons == []
    assert all(
        gate.status == "unscorable"
        for gate in report.hard_gates
    )


def test_hard_gate_failure_is_blocking_but_unavailable_gate_is_not() -> None:
    """Definitive required failures block while unavailable evidence remains unscorable."""

    profile = QualityGateProfile(
        schema_version="0.1.0",
        profile_id="gate.profile",
        job_id="quality_test",
        workflow_id="workflow.001",
        dispatch_id="dispatch.001",
        input_sha256=quality_artifact_input_sha256([]),
        source_fingerprint=SHA_A,
        producer=_producer(),
        provenance=[],
        created_at=NOW,
        axis_thresholds=[
            AxisThreshold(
                axis="structural_integrity",
                pass_score=1,
                warning_score=0.9,
            ),
            AxisThreshold(
                axis="production_readiness",
                pass_score=1,
                warning_score=0.9,
            ),
        ],
        gate_rules=[
            QualityGateRule(
                gate_id="gate.structure",
                axis="structural_integrity",
                message="Structure must pass.",
            ),
            QualityGateRule(
                gate_id="gate.production",
                axis="production_readiness",
                message="Production must pass.",
            ),
        ],
    )
    axes = [
        QualityAxisResult(
            axis="structural_integrity",
            status="failed",
            score=0.5,
            confidence=1,
            metrics=[
                QualityMetric(
                    metric_id="structural.test",
                    status="failed",
                    value=0.5,
                    confidence=1,
                    evidence_ids=["evidence.structural"],
                    message="A deterministic topology failure exists.",
                )
            ],
            evidence_ids=["evidence.structural"],
        ),
        QualityAxisResult(
            axis="production_readiness",
            status="unscorable",
            score=None,
            confidence=0,
            metrics=[],
            evidence_ids=["evidence.production"],
            limitations=["Package not built."],
        ),
    ]

    gates = evaluate_hard_gates(profile, axes)

    assert gates[0].status == "failed" and gates[0].blocking is True
    assert gates[1].status == "unscorable" and gates[1].blocking is False


def test_candidate_ranking_uses_gate_regression_pareto_and_minimum_change() -> None:
    """A smaller Pareto candidate wins while failed gates and regressions rank later."""

    candidates = [
        RankableQualityCandidate(
            candidate_id="candidate.a",
            candidate_sha256=SHA_A,
            report_path="candidates/a/report.json",
            report_sha256=SHA_B,
            gate_status="passed",
            critical_regressions=[],
            meaningful_gain=True,
            gains={"reference_alignment": 0.02, "structural_integrity": 0.0},
            changed_path_count=3,
            change_magnitude=0.1,
        ),
        RankableQualityCandidate(
            candidate_id="candidate.b",
            candidate_sha256=SHA_B,
            report_path="candidates/b/report.json",
            report_sha256=SHA_C,
            gate_status="passed",
            critical_regressions=[],
            meaningful_gain=True,
            gains={"reference_alignment": 0.01, "structural_integrity": 0.01},
            changed_path_count=1,
            change_magnitude=0.02,
        ),
        RankableQualityCandidate(
            candidate_id="candidate.c",
            candidate_sha256=SHA_C,
            report_path="candidates/c/report.json",
            report_sha256=SHA_A,
            gate_status="failed",
            critical_regressions=[],
            meaningful_gain=True,
            gains={"reference_alignment": 0.5, "structural_integrity": 0.5},
            changed_path_count=1,
            change_magnitude=0.01,
        ),
        RankableQualityCandidate(
            candidate_id="candidate.d",
            candidate_sha256=SHA_C,
            report_path="candidates/d/report.json",
            report_sha256=SHA_B,
            gate_status="passed",
            critical_regressions=["regression.constraint"],
            meaningful_gain=True,
            gains={"reference_alignment": 0.8, "structural_integrity": 0.8},
            changed_path_count=1,
            change_magnitude=0.01,
        ),
    ]

    ranking_artifacts = [
        QualityArtifact(
            artifact_id=item.candidate_id,
            kind="integrated-quality-report",
            relative_path=item.report_path,
            sha256=item.report_sha256,
            producer=_producer(),
            produced_at=NOW,
        )
        for item in candidates
    ]
    ranking_provenance = QualityProvenance(
        job_id="quality_test",
        workflow_id="workflow.001",
        dispatch_id="dispatch.001",
        input_sha256=quality_artifact_input_sha256(ranking_artifacts),
        source_fingerprint=SHA_A,
        artifacts=ranking_artifacts,
    )
    ranking = rank_quality_candidates(
        candidates,
        ranking_id="ranking.001",
        provenance=ranking_provenance,
        producer=_producer(),
        created_at=NOW,
    )

    assert set(ranking.pareto_candidate_ids) == {"candidate.a", "candidate.b"}
    assert ranking.selected_candidate_id == "candidate.b"
    assert ranking.records[-1].candidate_id == "candidate.c"


def test_contracts_reject_unknown_fields_and_escaping_paths() -> None:
    """Strict contracts reject undeclared fields and non-contained evidence paths."""

    with pytest.raises(ValidationError):
        EvidenceAvailability(
            evidence_id="evidence.bad",
            axis="reference_alignment",
            status="unavailable",
            confidence=0,
            reason="Missing.",
            invented=True,
        )
    with pytest.raises(ValidationError, match="path must"):
        QualityArtifact(
            artifact_id="artifact.bad",
            kind="qa",
            relative_path="../escape.json",
            sha256=SHA_A,
            producer=_producer(),
            produced_at=NOW,
        )


def test_reporting_writes_authoritative_json_and_hash_bound_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reporting persists exact JSON evidence and refuses an implicit overwrite."""

    profile = build_default_quality_gate_profile(
        profile_id="autonomous_static_prop_v1",
        job_id="quality_test",
        workflow_id="workflow.001",
        dispatch_id="dispatch.001",
        source_fingerprint=SHA_A,
        producer=_producer(),
        created_at=NOW,
    )
    report = build_integrated_quality_report(
        report_id="quality.report.001",
        provenance=_provenance(),
        gate_profile=profile,
        gate_profile_sha256=SHA_C,
        producer=_producer(),
        created_at=NOW,
        evidence_availability=_availability(),
        reference_evidence_id="evidence.reference",
        structural_evidence_id="evidence.structural",
        material_evidence_id="evidence.material",
        production_evidence_id="evidence.production",
        visual_qa=_visual_report(0.706882),
    )

    manifest = write_integrated_quality_evidence(
        tmp_path,
        report,
        output_dir=tmp_path / "run-001",
        include_pdf=False,
    )

    payload = json.loads((tmp_path / manifest.json_path).read_text(encoding="utf-8"))
    assert payload["legacy_v06_direct_score"] == 0.706882
    assert manifest.pdf_path is None
    with pytest.raises(FileExistsError, match="immutable"):
        write_integrated_quality_evidence(
            tmp_path,
            report,
            output_dir=tmp_path / "run-001",
            include_pdf=False,
        )

    original_write_pdf = quality_reporting._write_pdf

    def fail_pdf(_path: Path, _report: object) -> None:
        """Simulate a process-visible render failure before atomic directory publication."""

        raise RuntimeError("simulated PDF failure")

    interrupted_output = tmp_path / "run-interrupted"
    monkeypatch.setattr(quality_reporting, "_write_pdf", fail_pdf)
    with pytest.raises(RuntimeError, match="simulated PDF failure"):
        write_integrated_quality_evidence(
            tmp_path,
            report,
            output_dir=interrupted_output,
            include_pdf=True,
        )
    assert not interrupted_output.exists()
    assert not list(tmp_path.glob(".run-interrupted.publishing-*"))

    monkeypatch.setattr(quality_reporting, "_write_pdf", original_write_pdf)
    recovered = write_integrated_quality_evidence(
        tmp_path,
        report,
        output_dir=interrupted_output,
        include_pdf=True,
    )
    assert (tmp_path / recovered.json_path).is_file()
    assert (tmp_path / str(recovered.pdf_path)).is_file()
