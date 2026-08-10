"""Orchestration-neutral service for composing IntegratedQualityReport evidence."""

from __future__ import annotations

from datetime import datetime

from ..analysis.models import AssemblyValidationReport
from ..constraints.models import ConstraintSolution
from ..materials.fidelity_models import MaterialFidelityReport
from ..materials.models import MaterialValidationReport
from ..optimization.models import MeshPreflightReport
from ..packaging.models import RoundTripValidation
from ..qa.models import VisualQAReport
from .hard_gates import blocking_gate_messages, evaluate_hard_gates
from .material_metrics import material_fidelity_axis
from .models import (
    EvidenceAvailability,
    IntegratedQualityReport,
    ProducerIdentity,
    QualityAxis,
    QualityAxisResult,
    QualityGateProfile,
    QualityProvenance,
    ReentryRecommendation,
)
from .production_metrics import production_readiness_axis
from .reference_metrics import reference_alignment_axis
from .structural_metrics import structural_integrity_axis


def _threshold(profile: QualityGateProfile, axis: QualityAxis):
    """Return one explicitly configured axis threshold or reject an incomplete profile."""

    threshold = profile.threshold_for(axis)
    if threshold is None:
        raise ValueError(f"quality gate profile has no threshold for axis: {axis}")
    return threshold


def _evidence_record(
    evidence: list[EvidenceAvailability],
    evidence_id: str,
) -> EvidenceAvailability:
    """Resolve one declared evidence channel by its exact stable identity."""

    matches = [item for item in evidence if item.evidence_id == evidence_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one evidence availability record: {evidence_id}")
    return matches[0]


def _effective_confidence(record: EvidenceAvailability) -> float:
    """Return zero for unavailable evidence and the declared confidence otherwise."""

    return 0.0 if record.status == "unavailable" else record.confidence


def _validate_source_job_ids(
    job_id: str,
    *,
    visual_qa: VisualQAReport | None,
    constraints: ConstraintSolution | None,
    assembly_reports: list[AssemblyValidationReport],
    material_validation: MaterialValidationReport | None,
    material_fidelity: MaterialFidelityReport | None,
    mesh_preflight: MeshPreflightReport | None,
    roundtrip: RoundTripValidation | None,
) -> None:
    """Reject accidental cross-job evidence before any integrated result is constructed."""

    labeled = [
        ("visual QA", visual_qa),
        ("constraints", constraints),
        *[(f"assembly[{index}]", report) for index, report in enumerate(assembly_reports)],
        ("material validation", material_validation),
        ("material fidelity", material_fidelity),
        ("mesh preflight", mesh_preflight),
        ("round trip", roundtrip),
    ]
    mismatched = [
        label
        for label, report in labeled
        if report is not None and getattr(report, "job_id", None) != job_id
    ]
    if mismatched:
        raise ValueError(f"integrated quality contains cross-job evidence: {mismatched}")


def _reentry_for_axes(axes: list[QualityAxisResult]) -> list[ReentryRecommendation]:
    """Route each non-passing axis to the earliest responsible pipeline stage."""

    stage = {
        "reference_alignment": "v0.4",
        "structural_integrity": "v0.4",
        "material_fidelity": "v0.5",
        "production_readiness": "v0.7",
    }
    recommendations: list[ReentryRecommendation] = []
    for axis in axes:
        if axis.status == "passed":
            continue
        reason_codes = [
            metric.metric_id for metric in axis.metrics if metric.status in {"failed", "unscorable"}
        ]
        if not reason_codes:
            reason_codes = [f"{axis.axis}.warning"]
        recommendations.append(
            ReentryRecommendation(
                recommendation_id=f"reentry.{axis.axis}",
                stage=stage[axis.axis],  # type: ignore[arg-type]
                axis=axis.axis,
                reason_codes=reason_codes,
                message=(
                    f"Return to {stage[axis.axis]} because {axis.axis} is {axis.status}; "
                    "do not repair a canonical source from this report automatically."
                ),
            )
        )
    return recommendations


def build_integrated_quality_report(
    *,
    report_id: str,
    provenance: QualityProvenance,
    gate_profile: QualityGateProfile,
    gate_profile_sha256: str,
    producer: ProducerIdentity,
    created_at: datetime,
    evidence_availability: list[EvidenceAvailability],
    reference_evidence_id: str,
    structural_evidence_id: str,
    material_evidence_id: str,
    production_evidence_id: str,
    visual_qa: VisualQAReport | None = None,
    constraints: ConstraintSolution | None = None,
    assembly_reports: list[AssemblyValidationReport] | None = None,
    material_validation: MaterialValidationReport | None = None,
    material_fidelity: MaterialFidelityReport | None = None,
    mesh_preflight: MeshPreflightReport | None = None,
    roundtrip: RoundTripValidation | None = None,
    notes: list[str] | None = None,
) -> IntegratedQualityReport:
    """Compose exact multi-axis evidence while leaving all source contracts unchanged."""

    profile_identity = (
        gate_profile.job_id,
        gate_profile.workflow_id,
        gate_profile.dispatch_id,
    )
    provenance_identity = (
        provenance.job_id,
        provenance.workflow_id,
        provenance.dispatch_id,
    )
    if profile_identity != provenance_identity:
        raise ValueError("quality profile and provenance identities do not match")
    if gate_profile.source_fingerprint != provenance.source_fingerprint:
        raise ValueError("quality profile is bound to a different source fingerprint")
    normalized_assembly = assembly_reports or []
    _validate_source_job_ids(
        provenance.job_id,
        visual_qa=visual_qa,
        constraints=constraints,
        assembly_reports=normalized_assembly,
        material_validation=material_validation,
        material_fidelity=material_fidelity,
        mesh_preflight=mesh_preflight,
        roundtrip=roundtrip,
    )
    records = {
        "reference_alignment": _evidence_record(
            evidence_availability, reference_evidence_id
        ),
        "structural_integrity": _evidence_record(
            evidence_availability, structural_evidence_id
        ),
        "material_fidelity": _evidence_record(evidence_availability, material_evidence_id),
        "production_readiness": _evidence_record(
            evidence_availability, production_evidence_id
        ),
    }
    axes = [
        reference_alignment_axis(
            visual_qa if records["reference_alignment"].status != "unavailable" else None,
            threshold=_threshold(gate_profile, "reference_alignment"),
            evidence_id=reference_evidence_id,
            confidence=_effective_confidence(records["reference_alignment"]),
        ),
        structural_integrity_axis(
            threshold=_threshold(gate_profile, "structural_integrity"),
            evidence_id=structural_evidence_id,
            constraints=(
                constraints if records["structural_integrity"].status != "unavailable" else None
            ),
            assembly_reports=(
                normalized_assembly
                if records["structural_integrity"].status != "unavailable"
                else None
            ),
            mesh_preflight=(
                mesh_preflight
                if records["structural_integrity"].status != "unavailable"
                else None
            ),
            confidence=_effective_confidence(records["structural_integrity"]),
        ),
        material_fidelity_axis(
            threshold=_threshold(gate_profile, "material_fidelity"),
            evidence_id=material_evidence_id,
            validation=(
                material_validation
                if records["material_fidelity"].status != "unavailable"
                else None
            ),
            fidelity=(
                material_fidelity
                if records["material_fidelity"].status != "unavailable"
                else None
            ),
            confidence=_effective_confidence(records["material_fidelity"]),
        ),
        production_readiness_axis(
            threshold=_threshold(gate_profile, "production_readiness"),
            evidence_id=production_evidence_id,
            preflight=(
                mesh_preflight
                if records["production_readiness"].status != "unavailable"
                else None
            ),
            roundtrip=(
                roundtrip if records["production_readiness"].status != "unavailable" else None
            ),
            confidence=_effective_confidence(records["production_readiness"]),
        ),
    ]
    gates = evaluate_hard_gates(gate_profile, axes)
    failed_required = any(item.blocking for item in gates)
    unscorable_required_gate = any(
        item.required and item.status == "unscorable" for item in gates
    )
    required_axes = {
        item.axis for item in gate_profile.axis_thresholds if item.required
    }
    required_results = [axis for axis in axes if axis.axis in required_axes]
    has_unscorable = any(axis.status == "unscorable" for axis in required_results)
    has_nonpassing = any(axis.status in {"warning", "failed"} for axis in required_results)
    outcome = (
        "blocked"
        if failed_required
        else "unscorable"
        if unscorable_required_gate or has_unscorable
        else "needs_revision"
        if has_nonpassing
        else "passed"
    )
    return IntegratedQualityReport(
        schema_version="0.1.0",
        report_id=report_id,
        job_id=provenance.job_id,
        workflow_id=provenance.workflow_id,
        dispatch_id=provenance.dispatch_id,
        input_sha256=provenance.input_sha256,
        source_fingerprint=provenance.source_fingerprint,
        gate_profile_id=gate_profile.profile_id,
        gate_profile_sha256=gate_profile_sha256,
        provenance=provenance,
        producer=producer,
        created_at=created_at,
        outcome=outcome,  # type: ignore[arg-type]
        quality_accepted=outcome == "passed",
        legacy_v06_direct_score=(
            visual_qa.direct_metrics.overall_direct_score
            if visual_qa is not None
            and records["reference_alignment"].status != "unavailable"
            else None
        ),
        hard_gates=gates,
        axes=axes,
        evidence_availability=evidence_availability,
        blocking_reasons=blocking_gate_messages(gates),
        reentry=_reentry_for_axes(axes),
        notes=notes or [],
    )
