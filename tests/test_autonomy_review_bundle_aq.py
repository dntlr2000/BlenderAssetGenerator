"""Focused tests for immutable Autonomous Quality review-only bundles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy.reporting import (
    build_review_bundle,
    validate_review_bundle,
)
from codex_blender_modeler.blender_artifacts import sha256_file, write_json_atomic
from codex_blender_modeler.integrated_quality.models import (
    EvidenceAvailability,
    IntegratedQualityReport,
    ProducerIdentity,
    QualityArtifact,
    QualityAxisResult,
    QualityProvenance,
)

_NOW = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)


def _write(path: Path, content: bytes) -> Path:
    """Write one deterministic test artifact and return its path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_json(path: Path, payload: object) -> Path:
    """Write one UTF-8 JSON fixture without relying on production bundle code."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _quality_report(root: Path, *, passed: bool = False) -> Path:
    """Create one exact Integrated Quality report and its bound provenance artifact."""

    evidence_path = _write_json(root / "qa" / "source.json", {"evidence": "exact"})
    producer = ProducerIdentity(name="aq.tests", version="0.1.0")
    artifact = QualityArtifact(
        artifact_id="quality.source",
        kind="test_fixture",
        relative_path="qa/source.json",
        sha256=sha256_file(evidence_path),
        producer=producer,
        produced_at=_NOW,
    )
    if passed:
        availability = EvidenceAvailability(
            evidence_id="reference.available",
            axis="reference_alignment",
            status="available",
            artifact_id=artifact.artifact_id,
            confidence=1.0,
            reason="Exact fixture evidence is available.",
        )
        axis = QualityAxisResult(
            axis="reference_alignment",
            status="passed",
            score=1.0,
            confidence=1.0,
            evidence_ids=[availability.evidence_id],
        )
        outcome = "passed"
    else:
        availability = EvidenceAvailability(
            evidence_id="reference.unavailable",
            axis="reference_alignment",
            status="unavailable",
            confidence=0.0,
            reason="The bounded fixture intentionally omits a comparable reference mask.",
        )
        axis = QualityAxisResult(
            axis="reference_alignment",
            status="unscorable",
            confidence=0.0,
            limitations=["Reference alignment is unavailable in this fixture."],
        )
        outcome = "unscorable"
    report = IntegratedQualityReport(
        schema_version="0.1.0",
        report_id="aq-review-quality",
        job_id="review_prop_01",
        workflow_id="wf-review-01",
        dispatch_id="dispatch-review-01",
        input_sha256="c" * 64,
        source_fingerprint="b" * 64,
        gate_profile_id="aq-profile",
        gate_profile_sha256="a" * 64,
        provenance=QualityProvenance(
            job_id="review_prop_01",
            workflow_id="wf-review-01",
            dispatch_id="dispatch-review-01",
            source_fingerprint="b" * 64,
            input_sha256="c" * 64,
            artifacts=[artifact],
        ),
        producer=producer,
        created_at=_NOW,
        outcome=outcome,
        quality_accepted=passed,
        axes=[axis],
        evidence_availability=[availability],
    )
    report_path = root / "qa" / "integrated_quality_report.json"
    write_json_atomic(report_path, report.model_dump(mode="json"))
    return report_path


def _sources(root: Path, *, passed: bool = False) -> dict[str, object]:
    """Create every caller-owned artifact consumed by a review bundle."""

    return {
        "best_candidate_blend": _write(root / "candidates" / "best.blend", b"BLENDER-v500"),
        "preview_glb": _write(root / "candidates" / "preview.glb", b"glTF-review-preview"),
        "representative_renders": [
            _write(root / "candidates" / "front.png", b"PNG-front"),
            _write(root / "candidates" / "side.png", b"PNG-side"),
        ],
        "integrated_quality_report": _quality_report(root, passed=passed),
        "unresolved_findings": _write_json(
            root / "quality" / "unresolved.json",
            {"findings": [{"id": "silhouette", "severity": "high"}]},
        ),
        "iteration_history": _write_json(
            root / "quality" / "history.json",
            {"iterations": [{"index": 1, "outcome": "plateau"}]},
        ),
        "candidate_comparison": _write_json(
            root / "quality" / "comparison.json",
            {"best": "candidate-02", "weighted_score_used": False},
        ),
    }


def _build(root: Path, *, bundle_id: str = "review-bundle-01", passed: bool = False):
    """Build one deterministic fixture bundle through the public host service."""

    root.mkdir(parents=True, exist_ok=True)
    sources = _sources(root, passed=passed)
    return build_review_bundle(
        root,
        bundle_id=bundle_id,
        session_id="aq-session-01",
        job_id="review_prop_01",
        workflow_id="wf-review-01",
        dispatch_id="dispatch-review-01",
        termination_reason="plateau",
        next_manual_actions=[
            "V0.4 구조 작성으로 돌아가 주 실루엣을 검토한다.",
            "검토 후 새 품질 실행을 명시적으로 시작한다.",
        ],
        created_at=_NOW,
        **sources,
    )


def test_review_bundle_is_hash_bound_review_only_and_complete(tmp_path: Path) -> None:
    """Publish every required artifact without a package or destination-handoff claim."""

    manifest, receipt = _build(tmp_path)
    bundle = tmp_path / "exports" / "review_bundles" / "review-bundle-01"

    assert manifest.status == "review_only"
    assert manifest.production_ready is False
    assert manifest.destination_handoff_eligible is False
    assert receipt.production_ready is False
    assert receipt.destination_handoff_eligible is False
    assert receipt.canonical_unchanged is True
    assert (bundle / "best_candidate.blend").is_file()
    assert (bundle / "preview.glb").is_file()
    assert (bundle / "review_bundle_report.pdf").is_file()
    assert (bundle / "review_bundle_report.manifest.json").is_file()
    assert (bundle / "review_bundle_manifest.json").is_file()
    assert (bundle / "review_bundle_receipt.json").is_file()
    assert not (bundle / "package_manifest.json").exists()
    assert not (bundle / "codex_handoff").exists()
    validate_review_bundle(tmp_path, "review-bundle-01")


def test_review_bundle_is_immutable_and_rejects_tampering(tmp_path: Path) -> None:
    """Reject a duplicate publication and fail closed after an exact file changes."""

    _build(tmp_path)
    with pytest.raises(FileExistsError):
        _build(tmp_path)

    bundle = tmp_path / "exports" / "review_bundles" / "review-bundle-01"
    (bundle / "preview.glb").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_review_bundle(tmp_path, "review-bundle-01")


def test_review_bundle_rejects_passing_quality_and_leaves_no_bundle(tmp_path: Path) -> None:
    """Prevent successful quality evidence from being mislabeled as a review-only result."""

    with pytest.raises(ValueError, match="passing quality report"):
        _build(tmp_path, passed=True)
    assert not (tmp_path / "exports" / "review_bundles" / "review-bundle-01").exists()


def test_review_bundle_rejects_external_sources(tmp_path: Path) -> None:
    """Keep every copied source inside the owning job instead of following external paths."""

    root = tmp_path / "job"
    root.mkdir()
    sources = _sources(root)
    external = _write(tmp_path / "external.blend", b"outside")
    sources["best_candidate_blend"] = external
    with pytest.raises(ValueError, match="escapes"):
        build_review_bundle(
            root,
            bundle_id="review-bundle-01",
            session_id="aq-session-01",
            job_id="review_prop_01",
            workflow_id="wf-review-01",
            dispatch_id="dispatch-review-01",
            termination_reason="plateau",
            next_manual_actions=["수동 검토"],
            created_at=_NOW,
            **sources,
        )


def test_review_bundle_rejects_unbound_extra_files(tmp_path: Path) -> None:
    """Detect a package-like or otherwise unbound file added after publication."""

    _build(tmp_path)
    bundle = tmp_path / "exports" / "review_bundles" / "review-bundle-01"
    _write_json(bundle / "package_manifest.json", {"false_claim": True})
    with pytest.raises(ValueError, match="unbound extra files"):
        validate_review_bundle(tmp_path, "review-bundle-01")


def test_review_bundle_pdf_is_deterministic_for_exact_inputs(tmp_path: Path) -> None:
    """Produce the same derived PDF bytes from identical content and timestamps."""

    first = tmp_path / "first"
    second = tmp_path / "second"
    _build(first)
    _build(second)
    first_pdf = first / "exports" / "review_bundles" / "review-bundle-01" / _REPORT_NAME
    second_pdf = second / "exports" / "review_bundles" / "review-bundle-01" / _REPORT_NAME
    assert sha256_file(first_pdf) == sha256_file(second_pdf)


_REPORT_NAME = "review_bundle_report.pdf"
