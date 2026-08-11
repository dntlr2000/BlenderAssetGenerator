"""Focused report, gate, dispatch, and reentry tests for Integrated Quality 0.2."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from codex_blender_modeler.integrated_quality.models import (
    EvidenceAvailability,
    IntegratedQualityReport,
    ProducerIdentity,
    QualityArtifact,
    QualityAxisResult,
    QualityMetric,
    QualityProvenance,
    quality_artifact_input_sha256,
)
from codex_blender_modeler.integrated_quality.v02_advisory_metrics import (
    build_advisory_metric_v02,
)
from codex_blender_modeler.integrated_quality.v02_contour_metrics import (
    compare_contours_v02,
)
from codex_blender_modeler.integrated_quality.v02_dispatch import (
    integrated_quality_report_model_for_version,
    load_integrated_quality_report_versioned,
)
from codex_blender_modeler.integrated_quality.v02_models import (
    ContourEvidenceBindingV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
    MultiviewObservationV02,
    ProducerIdentityV02,
    QualityFindingV02,
    SemanticEvidenceBindingV02,
)
from codex_blender_modeler.integrated_quality.v02_multiview_metrics import (
    evaluate_multiview_v02,
)
from codex_blender_modeler.integrated_quality.v02_reentry import (
    route_quality_findings_v02,
)
from codex_blender_modeler.integrated_quality.v02_semantic_metrics import (
    compare_semantic_masks_v02,
)
from codex_blender_modeler.integrated_quality.v02_service import (
    build_integrated_quality_report_v02,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
PRODUCER = ProducerIdentityV02(name="cbm_integrated_quality_v02", version="0.2.0")


def _mask(*, empty: bool = False) -> Image.Image:
    """Build one deterministic reference/candidate mask."""

    image = Image.new("L", (32, 32), 0)
    if not empty:
        ImageDraw.Draw(image).rectangle((8, 8, 23, 23), fill=255)
    return image


def _contour(*, authoritative: bool = True):
    """Create one exact authoritative contour result."""

    return compare_contours_v02(
        _mask(),
        _mask(),
        reference_evidence=ContourEvidenceBindingV02(
            evidence_id="reference.contour",
            origin="observed" if authoritative else "generated",
            authority="authoritative" if authoritative else "advisory",
            artifact_path="analysis/masks/reference.png",
            artifact_sha256=SHA_A,
            camera_sha256=SHA_B,
        ),
        candidate_evidence_id="candidate.contour",
        candidate_artifact_sha256=SHA_D,
        candidate_camera_sha256=SHA_B,
    )


def _semantic(*, empty: bool = False, registered: bool = True):
    """Create one critical semantic comparison with configurable authority and presence."""

    return compare_semantic_masks_v02(
        _mask(),
        _mask(empty=empty),
        reference_evidence=SemanticEvidenceBindingV02(
            evidence_id="reference.semantic.body",
            semantic_id="asset.body",
            origin="registered_observed" if registered else "observed",
            authority="authoritative" if registered else "advisory",
            artifact_path="analysis/masks/body.png",
            artifact_sha256=SHA_A,
            camera_sha256=SHA_B,
            registration_receipt_sha256=SHA_C if registered else None,
        ),
        candidate_evidence_id="candidate.semantic.body",
        candidate_artifact_sha256=SHA_D,
        candidate_camera_sha256=SHA_B,
        critical=True,
    )


def _multiview(*, scored: bool = False):
    """Create optional unscorable or two-view actual Blender companion evidence."""

    if not scored:
        return evaluate_multiview_v02([])
    return evaluate_multiview_v02(
        [
            MultiviewObservationV02(
                view_id=f"view.{name}",
                origin="actual_blender",
                authority="authoritative",
                artifact_path=f"qa/views/{name}.png",
                artifact_sha256=SHA_A,
                camera_sha256=SHA_B,
                silhouette_stability=0.9,
                semantic_placement_score=0.9,
            )
            for name in ("front", "side")
        ]
    )


def _policy(**updates) -> IntegratedQualityPolicyV02:
    """Build one strict focused quality policy."""

    return IntegratedQualityPolicyV02(
        profile_id="quality.static_prop_v02",
        critical_semantic_ids=["asset.body"],
        **updates,
    )


def _report(
    *,
    contour=None,
    semantic=None,
    policy=None,
    extras=None,
) -> IntegratedQualityReportV02:
    """Build one complete report using a copied legacy V0.6 score."""

    return build_integrated_quality_report_v02(
        report_id="iq-v02-report-a",
        job_id="prop_a",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        source_fingerprint=SHA_A,
        camera_sha256=SHA_B,
        input_sha256=SHA_C,
        legacy_v06_report_sha256=SHA_D,
        legacy_v06_direct_score=0.812345,
        policy=policy or _policy(),
        contour=contour or _contour(),
        semantics=[semantic or _semantic()],
        landmarks=[],
        multiview=_multiview(),
        advisory_metrics=[
            build_advisory_metric_v02(
                metric_id="advisory.depth",
                kind="estimated_depth",
                value=None,
                confidence=0,
            )
        ],
        producer=PRODUCER,
        created_at=NOW,
        additional_findings=extras,
    )


def _legacy_v01_report() -> IntegratedQualityReport:
    """Build one minimal valid IQ 0.1 report for explicit dispatcher regression."""

    producer = ProducerIdentity(name="cbm_integrated_quality", version="0.1.0")
    artifact = QualityArtifact(
        artifact_id="artifact.reference",
        kind="visual_qa_report",
        relative_path="qa/runs/run-a/report.json",
        sha256=SHA_A,
        producer=producer,
        produced_at=NOW,
    )
    provenance = QualityProvenance(
        job_id="prop_a",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        source_fingerprint=SHA_B,
        input_sha256=quality_artifact_input_sha256([artifact]),
        artifacts=[artifact],
    )
    evidence = EvidenceAvailability(
        evidence_id="evidence.reference",
        axis="reference_alignment",
        status="unavailable",
        confidence=0,
        reason="Legacy fixture intentionally has no direct reference score.",
    )
    metric = QualityMetric(
        metric_id="reference.v06_overall_direct_score",
        status="unscorable",
        confidence=0,
        critical=True,
        evidence_ids=[evidence.evidence_id],
        message="Legacy fixture direct score is unavailable.",
    )
    axis = QualityAxisResult(
        axis="reference_alignment",
        required=True,
        status="unscorable",
        confidence=0,
        metrics=[metric],
        evidence_ids=[evidence.evidence_id],
        limitations=["Legacy fixture reference evidence is unavailable."],
    )
    return IntegratedQualityReport(
        schema_version="0.1.0",
        report_id="iq-v01-dispatch-fixture",
        job_id="prop_a",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        input_sha256=provenance.input_sha256,
        source_fingerprint=provenance.source_fingerprint,
        gate_profile_id="quality.v01-fixture",
        gate_profile_sha256=SHA_C,
        provenance=provenance,
        producer=producer,
        created_at=NOW,
        outcome="unscorable",
        quality_accepted=False,
        axes=[axis],
        evidence_availability=[evidence],
    )


def test_pass_preserves_legacy_direct_score_and_advisory_has_no_authority() -> None:
    """Accept exact required evidence while copying V0.6 direct score byte-for-value."""

    report = _report()
    assert report.outcome == "passed"
    assert report.quality_accepted is True
    assert report.legacy_v06_direct_score == 0.812345
    assert all(metric.authoritative is False for metric in report.advisory_metrics)
    assert next(
        gate for gate in report.hard_gates if gate.gate_id == "gate.reference.contour_v02"
    ).status == "passed"


def test_critical_semantic_missing_blocks_before_aggregate_quality() -> None:
    """Block a missing critical part even when contour and all other evidence pass."""

    report = _report(semantic=_semantic(empty=True))
    gate = next(
        item for item in report.hard_gates if item.gate_id == "gate.semantic.asset.body"
    )
    assert gate.status == "failed"
    assert gate.blocking is True
    assert report.outcome == "blocked"
    assert report.quality_accepted is False
    assert any(item.category == "semantic" for item in report.findings)


def test_unregistered_semantic_is_unscorable_not_a_quality_pass() -> None:
    """Refuse to use an otherwise perfect unregistered observed mask as pass authority."""

    report = _report(semantic=_semantic(registered=False))
    gate = next(
        item for item in report.hard_gates if item.gate_id == "gate.semantic.asset.body"
    )
    assert gate.status == "unscorable"
    assert report.outcome == "unscorable"
    assert report.quality_accepted is False


def test_generated_contour_is_advisory_and_cannot_satisfy_required_gate() -> None:
    """Refuse an exact generated contour as authoritative acceptance evidence."""

    report = _report(contour=_contour(authoritative=False))
    gate = next(
        item
        for item in report.hard_gates
        if item.gate_id == "gate.reference.contour_v02"
    )
    assert report.contour.boundary_f_score == 1.0
    assert report.contour.authority == "advisory"
    assert gate.status == "unscorable"
    assert report.outcome == "unscorable"


def test_required_multiview_unavailable_is_unscorable() -> None:
    """Keep absent actual-Blender multi-view evidence unavailable rather than passing."""

    report = _report(policy=_policy(require_multiview=True))
    gate = next(
        item
        for item in report.hard_gates
        if item.gate_id == "gate.structural.multiview_v02"
    )
    assert gate.status == "unscorable"
    assert report.outcome == "unscorable"


def test_restricted_scope_is_a_definitive_blocker() -> None:
    """Preserve prohibited scope as a hard blocker with explicit reentry."""

    finding = QualityFindingV02(
        finding_id="finding.scope.interior",
        category="restricted_scope",
        severity="hard",
        message="Interior work is outside this static-prop policy.",
    )
    report = _report(extras=[finding])
    assert report.outcome == "blocked"
    decision = next(item for item in report.reentry if item.finding_id == finding.finding_id)
    assert decision.destination == "restricted_scope_required"
    assert decision.automatic_action_allowed is False


def test_authoritative_hard_finding_requires_exact_failed_gate_binding() -> None:
    """Block a host-authoritative topology failure and bind its exact finding ID."""

    finding = QualityFindingV02(
        finding_id="finding.topology.nonmanifold",
        category="topology",
        severity="hard",
        authoritative=True,
        evidence_ids=["evidence.topology.nonmanifold"],
        message="The candidate contains a non-manifold edge.",
    )
    report = _report(extras=[finding])
    gate = next(
        item
        for item in report.hard_gates
        if item.gate_id == "gate.findings.authoritative_hard_v02"
    )
    assert gate.status == "failed"
    assert gate.required is True
    assert gate.blocking is True
    assert gate.finding_ids == [finding.finding_id]
    assert report.outcome == "blocked"
    assert report.quality_accepted is False
    assert report.legacy_v06_direct_score == 0.812345


def test_non_authoritative_finding_cannot_claim_hard_severity() -> None:
    """Reject an advisory finding before it can acquire hard-gate authority."""

    with pytest.raises(ValidationError, match="hard findings must be authoritative"):
        QualityFindingV02(
            finding_id="finding.advisory.generated-normal",
            category="normal",
            severity="hard",
            authoritative=False,
            message="A generated normal estimate reports a possible mismatch.",
        )


def test_report_rejects_unbound_authoritative_hard_finding() -> None:
    """Reject self-consistent report tampering that removes the exact finding gate."""

    finding = QualityFindingV02(
        finding_id="finding.normal.inverted",
        category="normal",
        severity="hard",
        authoritative=True,
        message="An authoritative mesh inspection found an inverted normal.",
    )
    payload = _report(extras=[finding]).model_dump(mode="python")
    payload["hard_gates"] = [
        gate
        for gate in payload["hard_gates"]
        if gate["gate_id"] != "gate.findings.authoritative_hard_v02"
    ]
    payload["outcome"] = "passed"
    payload["quality_accepted"] = True
    with pytest.raises(ValidationError, match="exact hard-gate bindings"):
        IntegratedQualityReportV02.model_validate(payload)


def test_report_rejects_omitted_warning_or_high_revision_reason() -> None:
    """Require every warning and high finding to remain exactly revision-bound."""

    finding = QualityFindingV02(
        finding_id="finding.uv.overlap",
        category="uv",
        severity="warning",
        authoritative=True,
        message="An authoritative UV inspection found an overlap.",
    )
    payload = _report(extras=[finding]).model_dump(mode="python")
    payload["revision_reasons"] = []
    payload["outcome"] = "passed"
    payload["quality_accepted"] = True
    with pytest.raises(ValidationError, match="exactly bind every warning and high"):
        IntegratedQualityReportV02.model_validate(payload)


def test_all_reentry_categories_have_machine_readable_destinations() -> None:
    """Route every requested category without authorizing a canonical write."""

    categories = [
        "camera",
        "contour",
        "semantic",
        "local_proportion",
        "topology",
        "uv",
        "normal",
        "missing_evidence",
        "restricted_scope",
    ]
    findings = [
        QualityFindingV02(
            finding_id=f"finding.{category}",
            category=category,
            severity="high",
            message=f"Fixture finding for {category}.",
        )
        for category in categories
    ]
    decisions = route_quality_findings_v02(findings)
    assert {item.category for item in decisions} == set(categories)
    assert all(item.automatic_action_allowed is False for item in decisions)
    assert next(item for item in decisions if item.category == "local_proportion").destination == (
        "v0.6_parametric_convergence"
    )
    assert next(item for item in decisions if item.category == "uv").destination == (
        "v0.7_production_repair"
    )


def test_parallel_dispatch_selects_explicit_versions_without_default_migration() -> None:
    """Dispatch valid 0.2 payloads and preserve the exact existing 0.1 model selection."""

    report = _report()
    loaded = load_integrated_quality_report_versioned(report.model_dump(mode="json"))
    legacy = _legacy_v01_report()
    loaded_legacy = load_integrated_quality_report_versioned(
        legacy.model_dump(mode="json")
    )
    assert isinstance(loaded, IntegratedQualityReportV02)
    assert loaded == report
    assert isinstance(loaded_legacy, IntegratedQualityReport)
    assert loaded_legacy == legacy
    assert integrated_quality_report_model_for_version("0.1.0") is IntegratedQualityReport
    assert integrated_quality_report_model_for_version("0.2.0") is IntegratedQualityReportV02
    with pytest.raises(ValueError, match="unsupported"):
        integrated_quality_report_model_for_version("0.3.0")


def test_v02_contracts_reject_unknown_and_non_finite_values() -> None:
    """Reject undeclared fields and non-finite thresholds in the new strict contract."""

    payload = _policy().model_dump(mode="python")
    payload["unknown"] = True
    with pytest.raises(ValidationError, match="Extra inputs"):
        IntegratedQualityPolicyV02.model_validate(payload)
    payload = _policy().model_dump(mode="python")
    payload["minimum_boundary_f_score"] = float("nan")
    with pytest.raises(ValidationError):
        IntegratedQualityPolicyV02.model_validate(payload)
