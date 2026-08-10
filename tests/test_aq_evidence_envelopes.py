"""Cross-contract coverage tests for the Autonomous Quality evidence envelope."""

from __future__ import annotations

from pydantic import BaseModel

from codex_blender_modeler.integrated_quality.models import (
    CandidateRanking,
    IntegratedQualityReport,
    IntegratedQualityReportManifest,
    ProducerIdentity,
    QualityArtifact,
    QualityGateProfile,
    QualityProvenance,
)
from codex_blender_modeler.reference_evidence.models import (
    CameraHypothesisSet,
    EvidenceArtifact,
    EvidenceProvenance,
    ReferenceEvidence,
    ReferenceEvidenceRunResult,
)
from codex_blender_modeler.structural_geometry.models import (
    AssetScaleContext,
    StructuralEvidenceArtifact,
)


def _assert_required_fields(
    model: type[BaseModel],
    expected: set[str],
) -> None:
    """Require contract fields in both the Pydantic model and JSON Schema envelope."""

    schema = model.model_json_schema()
    assert expected.issubset(model.model_fields)
    assert expected.issubset(set(schema.get("required", [])))
    assert schema.get("additionalProperties") is False


def test_public_aq_contracts_expose_the_required_evidence_envelope() -> None:
    """Document each public envelope field, including strict nested provenance mappings."""

    _assert_required_fields(AssetScaleContext, {
        "schema_version",
        "asset_id",
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "producer",
        "producer_version",
        "provenance",
        "created_at",
    })
    assert {"path", "sha256"}.issubset(StructuralEvidenceArtifact.model_fields)

    _assert_required_fields(ReferenceEvidence, {
        "schema_version",
        "evidence_id",
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "provenance",
        "created_at",
    })
    assert {"producer", "producer_version"}.issubset(
        EvidenceProvenance.model_fields
    )
    assert {"path", "sha256"}.issubset(EvidenceArtifact.model_fields)

    _assert_required_fields(CameraHypothesisSet, {
        "schema_version",
        "hypothesis_set_id",
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "reference_evidence_path",
        "reference_evidence_sha256",
        "provenance",
        "created_at",
    })

    _assert_required_fields(ReferenceEvidenceRunResult, {
        "schema_version",
        "run_id",
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "reference_evidence_path",
        "reference_evidence_sha256",
        "camera_hypothesis_set_path",
        "camera_hypothesis_set_sha256",
        "provenance",
        "created_at",
    })

    _assert_required_fields(QualityGateProfile, {
        "schema_version",
        "profile_id",
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "producer",
        "provenance",
        "created_at",
    })
    assert {"name", "version"}.issubset(ProducerIdentity.model_fields)
    assert {"relative_path", "sha256"}.issubset(QualityArtifact.model_fields)


def test_integrated_artifacts_require_top_level_and_nested_provenance_envelopes() -> None:
    """Require authoritative quality artifacts to expose and cross-bind every envelope field."""

    common = {
        "schema_version",
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "provenance",
        "producer",
        "created_at",
    }
    _assert_required_fields(IntegratedQualityReport, common | {"report_id"})
    _assert_required_fields(CandidateRanking, common | {"ranking_id"})
    _assert_required_fields(IntegratedQualityReportManifest, common | {"report_id"})
    assert {
        "job_id",
        "workflow_id",
        "dispatch_id",
        "input_sha256",
        "source_fingerprint",
        "artifacts",
    }.issubset(QualityProvenance.model_fields)
    assert {"relative_path", "sha256", "producer", "produced_at"}.issubset(
        QualityArtifact.model_fields
    )
