"""Checked-in JSON Schema parity tests for Integrated Quality 0.2."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from codex_blender_modeler.integrated_quality.v02_models import (
    CandidateRankingV02,
    ContourMetricsV02,
    HardGateResultV02,
    IntegratedQualityPolicyV02,
    IntegratedQualityReportV02,
    MultiviewMetricV02,
    ProducerIdentityV02,
    QualityFindingV02,
    ReentryDecisionV02,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 11, tzinfo=UTC)
SHA_A = "a" * 64
SCHEMAS = {
    "integrated_quality_v02_report.schema.json": IntegratedQualityReportV02,
    "integrated_quality_v02_policy.schema.json": IntegratedQualityPolicyV02,
    "integrated_quality_v02_candidate_ranking.schema.json": CandidateRankingV02,
    "integrated_quality_v02_reentry.schema.json": ReentryDecisionV02,
}


def _schema(name: str) -> dict:
    """Load one checked-in IQ 0.2 Schema as authoritative JSON bytes."""

    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _unscorable_report() -> IntegratedQualityReportV02:
    """Build a minimal valid missing-evidence report for full Schema validation."""

    finding = QualityFindingV02(
        finding_id="finding.reference.contour_v02",
        category="missing_evidence",
        severity="high",
        evidence_ids=["reference.contour", "candidate.contour"],
        message="Reference contour evidence is unavailable.",
    )
    return IntegratedQualityReportV02(
        report_id="iq-v02-schema-fixture",
        job_id="schema_fixture",
        workflow_id="workflow-a",
        dispatch_id="dispatch-a",
        source_fingerprint=SHA_A,
        camera_sha256=SHA_A,
        input_sha256=SHA_A,
        policy=IntegratedQualityPolicyV02(profile_id="quality.schema-fixture"),
        contour=ContourMetricsV02(
            metric_id="reference.contour_v02",
            status="unscorable",
            authority="unavailable",
            evidence_ids=["reference.contour", "candidate.contour"],
            candidate_mask_sha256=SHA_A,
            camera_sha256=SHA_A,
            width=32,
            height=32,
            reference_boundary_pixels=0,
            candidate_boundary_pixels=0,
            boundary_tolerance_px=0.25,
            boundary_tolerance_diagonal_fraction=0.005,
            limitations=["reference contour evidence is unavailable"],
        ),
        multiview=MultiviewMetricV02(
            metric_id="structural.multiview_v02",
            status="unscorable",
            observations=[],
            authoritative_view_count=0,
            limitations=["actual Blender multi-view evidence is unavailable"],
        ),
        hard_gates=[
            HardGateResultV02(
                gate_id="gate.reference.contour_v02",
                status="unscorable",
                required=True,
                blocking=False,
                evidence_ids=["reference.contour", "candidate.contour"],
                reason_code="contour_evidence_unavailable",
                message="Required authoritative contour evidence is unavailable.",
            )
        ],
        findings=[finding],
        reentry=[
            ReentryDecisionV02(
                finding_id=finding.finding_id,
                category=finding.category,
                destination="manual_evidence_review",
                reason_code="reentry.missing_evidence",
                message="Missing evidence requires manual review.",
            )
        ],
        outcome="unscorable",
        quality_accepted=False,
        revision_reasons=[finding.finding_id],
        producer=ProducerIdentityV02(
            name="cbm_integrated_quality_v02",
            version="0.2.0",
        ),
        created_at=NOW,
    )


@pytest.mark.parametrize(("schema_name", "model"), SCHEMAS.items())
def test_checked_in_schema_matches_pydantic(schema_name: str, model: type) -> None:
    """Require byte-structure parity with each Pydantic-generated companion Schema."""

    checked_in = _schema(schema_name)
    Draft202012Validator.check_schema(checked_in)
    assert checked_in == model.model_json_schema()


def test_report_schema_accepts_valid_report_and_rejects_unknown_field() -> None:
    """Validate one full report and reject undeclared JSON fields at the Schema boundary."""

    schema = _schema("integrated_quality_v02_report.schema.json")
    payload = _unscorable_report().model_dump(mode="json")
    Draft202012Validator(schema).validate(payload)
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)
