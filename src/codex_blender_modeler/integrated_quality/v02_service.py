"""Orchestration-neutral Integrated Quality 0.2 report service."""

from __future__ import annotations

from datetime import datetime

from .v02_models import (
    AdvisoryMetricV02,
    ContourMetricsV02,
    HardGateResultV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
    LandmarkMetricV02,
    MultiviewMetricV02,
    ProducerIdentityV02,
    QualityFindingV02,
    SemanticMetricV02,
)
from .v02_reentry import route_quality_findings_v02


def _gate(
    gate_id: str,
    *,
    status: str,
    required: bool,
    evidence_ids: list[str],
    finding_ids: list[str] | None = None,
    reason_code: str,
    message: str,
) -> HardGateResultV02:
    """Build one internally consistent hard-gate result."""

    return HardGateResultV02(
        gate_id=gate_id,
        status=status,  # type: ignore[arg-type]
        required=required,
        blocking=required and status == "failed",
        evidence_ids=evidence_ids,
        finding_ids=finding_ids or [],
        reason_code=reason_code,
        message=message,
    )


def _authoritative_finding_gate(
    findings: list[QualityFindingV02],
) -> HardGateResultV02 | None:
    """Bind every non-scope authoritative hard finding to one required failed gate."""

    hard_findings = [
        item
        for item in findings
        if item.authoritative
        and item.severity == "hard"
        and item.category != "restricted_scope"
    ]
    if not hard_findings:
        return None
    return _gate(
        "gate.findings.authoritative_hard_v02",
        status="failed",
        required=True,
        evidence_ids=list(
            dict.fromkeys(
                evidence_id
                for finding in hard_findings
                for evidence_id in finding.evidence_ids
            )
        ),
        finding_ids=[item.finding_id for item in hard_findings],
        reason_code="authoritative_hard_finding",
        message="One or more authoritative hard findings block quality acceptance.",
    )


def _contour_gate(
    contour: ContourMetricsV02,
    policy: IntegratedQualityPolicyV02,
) -> HardGateResultV02:
    """Evaluate authoritative contour thresholds without using advisory evidence as a pass."""

    if contour.status == "unscorable" or contour.authority != "authoritative":
        return _gate(
            "gate.reference.contour_v02",
            status="unscorable",
            required=policy.require_contour,
            evidence_ids=contour.evidence_ids,
            reason_code="contour_evidence_unavailable",
            message="Required authoritative contour evidence is unavailable.",
        )
    assert contour.boundary_f_score is not None
    assert contour.edge_distance_transform_chamfer_norm is not None
    passed = (
        contour.boundary_f_score >= policy.minimum_boundary_f_score
        and contour.edge_distance_transform_chamfer_norm
        <= policy.maximum_edge_distance_transform_chamfer_norm
    )
    return _gate(
        "gate.reference.contour_v02",
        status="passed" if passed else "failed",
        required=policy.require_contour,
        evidence_ids=contour.evidence_ids,
        reason_code="contour_threshold_passed" if passed else "contour_threshold_failed",
        message=(
            "Exact contour boundary and distance-transform thresholds passed."
            if passed
            else "Exact contour boundary or distance-transform threshold failed."
        ),
    )


def _semantic_gates(
    semantics: list[SemanticMetricV02],
    policy: IntegratedQualityPolicyV02,
) -> list[HardGateResultV02]:
    """Evaluate each configured critical semantic independently and fail closed."""

    metric_by_id = {item.semantic_id: item for item in semantics}
    if len(metric_by_id) != len(semantics):
        raise ValueError("semantic metric IDs must be unique")
    gates: list[HardGateResultV02] = []
    for semantic_id in policy.critical_semantic_ids:
        metric = metric_by_id.get(semantic_id)
        gate_id = f"gate.semantic.{semantic_id}"
        if metric is None:
            gates.append(
                _gate(
                    gate_id,
                    status="unscorable",
                    required=True,
                    evidence_ids=[],
                    reason_code="critical_semantic_evidence_missing",
                    message=f"Critical semantic {semantic_id} has no registered metric.",
                )
            )
            continue
        if not metric.critical:
            raise ValueError("policy-critical semantic metrics must set critical=true")
        evidence_ids = [
            metric.reference_evidence.evidence_id,
            metric.candidate_evidence_id,
        ]
        if metric.authority != "authoritative" or metric.status == "unscorable":
            gates.append(
                _gate(
                    gate_id,
                    status="unscorable",
                    required=True,
                    evidence_ids=evidence_ids,
                    reason_code="critical_semantic_evidence_unavailable",
                    message=(
                        f"Critical semantic {semantic_id} lacks registered observed evidence."
                    ),
                )
            )
            continue
        assert metric.mask_iou is not None
        passed = (
            not metric.missing_candidate
            and metric.mask_iou >= policy.minimum_semantic_iou
        )
        gates.append(
            _gate(
                gate_id,
                status="passed" if passed else "failed",
                required=True,
                evidence_ids=evidence_ids,
                reason_code=(
                    "critical_semantic_passed"
                    if passed
                    else "critical_semantic_missing_or_misaligned"
                ),
                message=(
                    f"Critical semantic {semantic_id} passed observed-mask thresholds."
                    if passed
                    else f"Critical semantic {semantic_id} is missing or misaligned."
                ),
            )
        )
    unexpected_critical = [
        item.semantic_id
        for item in semantics
        if item.critical and item.semantic_id not in policy.critical_semantic_ids
    ]
    if unexpected_critical:
        raise ValueError(
            "semantic metrics cannot broaden policy critical IDs: "
            + ", ".join(unexpected_critical)
        )
    return gates


def _landmark_gates(
    landmarks: list[LandmarkMetricV02],
    policy: IntegratedQualityPolicyV02,
) -> list[HardGateResultV02]:
    """Keep missing required landmarks unscorable and observed errors thresholded."""

    metric_by_id = {item.landmark_id: item for item in landmarks}
    if len(metric_by_id) != len(landmarks):
        raise ValueError("landmark metric IDs must be unique")
    gates: list[HardGateResultV02] = []
    for landmark_id in policy.required_landmark_ids:
        metric = metric_by_id.get(landmark_id)
        gate_id = f"gate.landmark.{landmark_id}"
        if (
            metric is None
            or metric.status == "unscorable"
            or metric.authority != "authoritative"
        ):
            gates.append(
                _gate(
                    gate_id,
                    status="unscorable",
                    required=True,
                    evidence_ids=[],
                    reason_code="required_landmark_unavailable",
                    message=f"Required observed landmark {landmark_id} is unavailable.",
                )
            )
            continue
        assert metric.reprojection_error_norm is not None
        passed = (
            metric.reprojection_error_norm
            <= policy.maximum_landmark_reprojection_error_norm
        )
        gates.append(
            _gate(
                gate_id,
                status="passed" if passed else "failed",
                required=True,
                evidence_ids=[],
                reason_code=(
                    "landmark_reprojection_passed"
                    if passed
                    else "landmark_reprojection_failed"
                ),
                message=(
                    f"Landmark {landmark_id} passed reprojection tolerance."
                    if passed
                    else f"Landmark {landmark_id} exceeded reprojection tolerance."
                ),
            )
        )
    return gates


def _multiview_gate(
    multiview: MultiviewMetricV02,
    policy: IntegratedQualityPolicyV02,
) -> HardGateResultV02:
    """Evaluate optional actual-Blender multi-view evidence as a separate gate."""

    evidence_ids = [item.view_id for item in multiview.observations]
    if multiview.status == "unscorable":
        return _gate(
            "gate.structural.multiview_v02",
            status="unscorable",
            required=policy.require_multiview,
            evidence_ids=evidence_ids,
            reason_code="multiview_evidence_unavailable",
            message="At least two authoritative actual-Blender views are unavailable.",
        )
    assert multiview.minimum_silhouette_stability is not None
    assert multiview.mean_semantic_placement_score is not None
    passed = (
        multiview.minimum_silhouette_stability
        >= policy.minimum_multiview_silhouette_stability
        and multiview.mean_semantic_placement_score
        >= policy.minimum_multiview_semantic_placement
    )
    return _gate(
        "gate.structural.multiview_v02",
        status="passed" if passed else "failed",
        required=policy.require_multiview,
        evidence_ids=evidence_ids,
        reason_code="multiview_passed" if passed else "multiview_failed",
        message=(
            "Authoritative multi-view structural thresholds passed."
            if passed
            else "Authoritative multi-view structural thresholds failed."
        ),
    )


def _metric_findings(
    *,
    contour: ContourMetricsV02,
    semantics: list[SemanticMetricV02],
    landmarks: list[LandmarkMetricV02],
    multiview: MultiviewMetricV02,
    gates: list[HardGateResultV02],
    policy: IntegratedQualityPolicyV02,
) -> list[QualityFindingV02]:
    """Convert non-passing authoritative and advisory observations to explicit findings."""

    gate_by_id = {item.gate_id: item for item in gates}
    findings: list[QualityFindingV02] = []
    contour_gate = gate_by_id["gate.reference.contour_v02"]
    if contour_gate.status != "passed":
        category = (
            "missing_evidence"
            if contour_gate.status == "unscorable"
            else "contour"
        )
        findings.append(
            QualityFindingV02(
                finding_id="finding.reference.contour_v02",
                category=category,  # type: ignore[arg-type]
                severity="hard" if contour_gate.blocking else "high",
                evidence_ids=contour.evidence_ids,
                message=contour_gate.message,
            )
        )
    for metric in semantics:
        gate = gate_by_id.get(f"gate.semantic.{metric.semantic_id}")
        below_threshold = (
            metric.status == "scored"
            and metric.mask_iou is not None
            and metric.mask_iou < policy.minimum_semantic_iou
        )
        if gate is None and not below_threshold and not metric.missing_candidate:
            continue
        if gate is not None and gate.status == "passed":
            continue
        missing_evidence = (
            metric.status == "unscorable" or metric.authority != "authoritative"
        )
        findings.append(
            QualityFindingV02(
                finding_id=f"finding.semantic.{metric.semantic_id}",
                category="missing_evidence" if missing_evidence else "semantic",
                severity=(
                    "hard"
                    if gate is not None and gate.blocking
                    else "high"
                    if metric.critical
                    else "warning"
                ),
                target_ids=[metric.semantic_id],
                evidence_ids=[
                    metric.reference_evidence.evidence_id,
                    metric.candidate_evidence_id,
                ],
                message=(
                    "Semantic evidence is unavailable for authoritative quality acceptance."
                    if missing_evidence
                    else "Semantic mask is missing or below the configured IoU threshold."
                ),
            )
        )
    for landmark in landmarks:
        gate = gate_by_id.get(f"gate.landmark.{landmark.landmark_id}")
        if gate is None or gate.status == "passed":
            continue
        findings.append(
            QualityFindingV02(
                finding_id=f"finding.landmark.{landmark.landmark_id}",
                category=(
                    "missing_evidence" if gate.status == "unscorable" else "camera"
                ),
                severity="hard" if gate.blocking else "high",
                target_ids=[landmark.semantic_id],
                message=gate.message,
            )
        )
    multiview_gate = gate_by_id["gate.structural.multiview_v02"]
    if multiview_gate.status != "passed" and (
        policy.require_multiview or multiview.status == "scored"
    ):
        findings.append(
            QualityFindingV02(
                finding_id="finding.structural.multiview_v02",
                category=(
                    "missing_evidence"
                    if multiview_gate.status == "unscorable"
                    else "local_proportion"
                ),
                severity="hard" if multiview_gate.blocking else "high",
                evidence_ids=multiview_gate.evidence_ids,
                message=multiview_gate.message,
            )
        )
    return findings


def build_integrated_quality_report_v02(
    *,
    report_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    source_fingerprint: str,
    camera_sha256: str,
    input_sha256: str,
    policy: IntegratedQualityPolicyV02,
    contour: ContourMetricsV02,
    semantics: list[SemanticMetricV02],
    landmarks: list[LandmarkMetricV02],
    multiview: MultiviewMetricV02,
    advisory_metrics: list[AdvisoryMetricV02],
    producer: ProducerIdentityV02,
    created_at: datetime,
    legacy_v06_report_sha256: str | None = None,
    legacy_v06_direct_score: float | None = None,
    additional_findings: list[QualityFindingV02] | None = None,
) -> IntegratedQualityReportV02:
    """Build an IQ 0.2 report without changing V0.6 or Integrated Quality 0.1 evidence."""

    gates = [
        _contour_gate(contour, policy),
        *_semantic_gates(semantics, policy),
        *_landmark_gates(landmarks, policy),
        _multiview_gate(multiview, policy),
    ]
    extras = additional_findings or []
    if any(item.category == "restricted_scope" for item in extras):
        restricted = [item for item in extras if item.category == "restricted_scope"]
        gates.append(
            _gate(
                "gate.scope.restricted_v02",
                status="failed",
                required=True,
                evidence_ids=[
                    evidence_id
                    for finding in restricted
                    for evidence_id in finding.evidence_ids
                ],
                finding_ids=[item.finding_id for item in restricted],
                reason_code="restricted_scope_required",
                message="Requested work is outside the authorized AQ v2 static-prop scope.",
            )
        )
    findings = _metric_findings(
        contour=contour,
        semantics=semantics,
        landmarks=landmarks,
        multiview=multiview,
        gates=gates,
        policy=policy,
    ) + extras
    finding_ids = [item.finding_id for item in findings]
    if len(finding_ids) != len(set(finding_ids)):
        raise ValueError("integrated quality finding IDs must be unique")
    authoritative_finding_gate = _authoritative_finding_gate(findings)
    if authoritative_finding_gate is not None:
        gates.append(authoritative_finding_gate)
    blocked = any(item.blocking for item in gates)
    required_unscorable = any(
        item.required and item.status == "unscorable" for item in gates
    )
    revision_reasons = [
        item.finding_id for item in findings if item.severity in {"warning", "high"}
    ]
    outcome = (
        "blocked"
        if blocked
        else "unscorable"
        if required_unscorable
        else "needs_revision"
        if revision_reasons
        else "passed"
    )
    return IntegratedQualityReportV02(
        report_id=report_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        source_fingerprint=source_fingerprint,
        camera_sha256=camera_sha256,
        input_sha256=input_sha256,
        legacy_v06_report_sha256=legacy_v06_report_sha256,
        legacy_v06_direct_score=legacy_v06_direct_score,
        policy=policy,
        contour=contour,
        semantics=semantics,
        landmarks=landmarks,
        multiview=multiview,
        advisory_metrics=advisory_metrics,
        hard_gates=gates,
        findings=findings,
        reentry=route_quality_findings_v02(findings),
        outcome=outcome,  # type: ignore[arg-type]
        quality_accepted=outcome == "passed",
        revision_reasons=revision_reasons,
        producer=producer,
        created_at=created_at,
    )
