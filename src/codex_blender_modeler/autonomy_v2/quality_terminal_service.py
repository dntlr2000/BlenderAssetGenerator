"""Strict AQ v2 quality review-bundle and terminal publication services."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ..blender_artifacts import native_io_path, stable_json_digest
from ..integrated_quality.v02_models import IntegratedQualityReportV02
from ..production.validation import (
    ensure_contained_production_path,
    validate_production_id,
)
from .delivery_service import (
    validate_quality_source_freeze,
    validate_v2_artifact,
    write_immutable_v2_model,
)
from .models import (
    AQV2Artifact,
    QualityApprovedSourceFreeze,
    QualityReviewActionV2,
    QualityReviewBundleV2,
    QualityTerminalV2,
)

_PRODUCER = "codex_blender_modeler.autonomy_v2.quality_terminal_service"


def _timestamp(value: datetime | None) -> datetime:
    """Return one timezone-aware publication timestamp."""

    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("AQ v2 quality publication timestamp must be timezone-aware")
    return timestamp


def _load_quality_report(
    root: Path,
    artifact: AQV2Artifact,
) -> IntegratedQualityReportV02:
    """Rehash and strict-parse one exact Integrated Quality 0.2 report."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        report = IntegratedQualityReportV02.model_validate_json(handle.read())
    if report.job_id != root.name:
        raise ValueError("IQ 0.2 report job identity does not match its workspace")
    return report


def _load_source_freeze(
    root: Path,
    artifact: AQV2Artifact,
) -> QualityApprovedSourceFreeze:
    """Rehash and strict-parse one exact quality-approved source freeze."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return QualityApprovedSourceFreeze.model_validate_json(handle.read())


def _load_review_bundle(
    root: Path,
    artifact: AQV2Artifact,
) -> QualityReviewBundleV2:
    """Rehash and strict-parse one exact AQ v2 non-production review bundle."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return QualityReviewBundleV2.model_validate_json(handle.read())


def _load_quality_terminal(
    root: Path,
    artifact: AQV2Artifact,
) -> QualityTerminalV2:
    """Rehash and strict-parse one exact AQ v2 quality terminal."""

    path = validate_v2_artifact(root, artifact)
    with open(native_io_path(path), "rb") as handle:
        return QualityTerminalV2.model_validate_json(handle.read())


def _quality_report_evidence_hashes(report: IntegratedQualityReportV02) -> set[str]:
    """Collect exact IQ 0.2 file hashes required by a quality-approved freeze."""

    hashes = {report.camera_sha256}
    if report.legacy_v06_report_sha256 is not None:
        hashes.add(report.legacy_v06_report_sha256)
    for value in (
        report.contour.reference_mask_sha256,
        report.contour.candidate_mask_sha256,
    ):
        if value is not None:
            hashes.add(value)
    for semantic in report.semantics:
        for value in (
            semantic.reference_evidence.artifact_sha256,
            semantic.reference_evidence.registration_receipt_sha256,
            semantic.contour.reference_mask_sha256,
            semantic.contour.candidate_mask_sha256,
        ):
            if value is not None:
                hashes.add(value)
    for landmark in report.landmarks:
        for value in (
            landmark.source_artifact_sha256,
            landmark.candidate_artifact_sha256,
        ):
            if value is not None:
                hashes.add(value)
    for observation in report.multiview.observations:
        if observation.artifact_sha256 is not None:
            hashes.add(observation.artifact_sha256)
    for metric in report.advisory_metrics:
        if metric.artifact_sha256 is not None:
            hashes.add(metric.artifact_sha256)
    return hashes


def _recommended_actions(
    report: IntegratedQualityReportV02,
) -> list[QualityReviewActionV2]:
    """Derive deterministic manual recommendations from exact IQ 0.2 reentry evidence."""

    actions = [
        QualityReviewActionV2(
            action_id=f"review-action-{index:03d}",
            finding_id=decision.finding_id,
            destination=decision.destination,
            reason_code=decision.reason_code,
            target_ids=decision.target_ids,
            message=decision.message,
        )
        for index, decision in enumerate(report.reentry, start=1)
    ]
    if not actions:
        actions = [
            QualityReviewActionV2(
                action_id=f"review-action-{index:03d}",
                finding_id=None,
                destination="manual_evidence_review",
                reason_code=gate.reason_code,
                target_ids=[],
                message=gate.message,
            )
            for index, gate in enumerate(
                (
                    item
                    for item in report.hard_gates
                    if item.required and item.status == "unscorable"
                ),
                start=1,
            )
        ]
    if not actions:
        raise ValueError("IQ 0.2 non-pass has no deterministic recommended review action")
    return actions


def _review_input_payload(
    *,
    report_artifact: AQV2Artifact,
    report: IntegratedQualityReportV02,
    candidate_blend: AQV2Artifact,
    representative_render: AQV2Artifact,
    actions: list[QualityReviewActionV2],
) -> dict[str, object]:
    """Build the deterministic input map shared by review builders and validators."""

    return {
        "integrated_quality_report": report_artifact.sha256,
        "quality_input_sha256": report.input_sha256,
        "candidate_blend": candidate_blend.sha256,
        "representative_render": representative_render.sha256,
        "quality_outcome": report.outcome,
        "recommended_actions": [item.model_dump(mode="json") for item in actions],
    }


def _validate_review_bundle_model(
    *,
    root: Path,
    bundle: QualityReviewBundleV2,
    bundle_artifact: AQV2Artifact | None,
) -> IntegratedQualityReportV02:
    """Recompute a review bundle's report, recommendations, identity, and digests."""

    for artifact in bundle.provenance:
        validate_v2_artifact(root, artifact)
    expected_id = f"quality-review-{bundle.session_id}"
    if (
        bundle.contract_id != expected_id
        or bundle.bundle_id != expected_id
        or bundle.producer != _PRODUCER
    ):
        raise ValueError("AQ v2 review bundle was not emitted by its host builder")
    report = _load_quality_report(root, bundle.integrated_quality_report)
    if report.outcome not in {"needs_revision", "unscorable"} or report.quality_accepted:
        raise ValueError("AQ v2 review bundle requires an exact non-passing IQ 0.2 report")
    if (
        bundle.job_id != report.job_id
        or bundle.workflow_id != report.workflow_id
        or bundle.dispatch_id != report.dispatch_id
        or bundle.quality_outcome != report.outcome
    ):
        raise ValueError("AQ v2 review bundle identity does not match its IQ 0.2 report")
    actions = _recommended_actions(report)
    if bundle.recommended_actions != actions:
        raise ValueError("AQ v2 review actions do not match exact IQ 0.2 reentry evidence")
    input_payload = _review_input_payload(
        report_artifact=bundle.integrated_quality_report,
        report=report,
        candidate_blend=bundle.candidate_blend,
        representative_render=bundle.representative_render,
        actions=actions,
    )
    expected_input = stable_json_digest(input_payload)
    expected_source = stable_json_digest(
        {
            "input_sha256": expected_input,
            "quality_source_fingerprint": report.source_fingerprint,
            "quality_outcome": report.outcome,
        }
    )
    if bundle.input_sha256 != expected_input or bundle.source_fingerprint != expected_source:
        raise ValueError("AQ v2 review bundle digest is inconsistent")
    if bundle_artifact is not None:
        expected_path = (
            f"production/autonomy_v2/{bundle.session_id}/quality_review_bundle.json"
        )
        if (
            bundle_artifact.path != expected_path
            or bundle_artifact.kind != "quality-review-bundle"
            or bundle_artifact.artifact_id != bundle.contract_id
        ):
            raise ValueError("AQ v2 review bundle is outside its immutable builder path")
    return report


def build_quality_review_bundle_v2(
    *,
    job_root: Path,
    session_id: str,
    integrated_quality_report: AQV2Artifact,
    candidate_blend: AQV2Artifact,
    representative_render: AQV2Artifact,
    created_at: datetime | None = None,
) -> tuple[QualityReviewBundleV2, AQV2Artifact]:
    """Atomically publish one deterministic IQ 0.2 non-pass review bundle."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    validate_production_id(session_id, "AQ v2 session ID")
    report = _load_quality_report(root, integrated_quality_report)
    if report.outcome not in {"needs_revision", "unscorable"} or report.quality_accepted:
        raise ValueError("AQ v2 review bundle requires needs_revision or unscorable IQ 0.2")
    for artifact in (candidate_blend, representative_render):
        validate_v2_artifact(root, artifact)
    actions = _recommended_actions(report)
    input_payload = _review_input_payload(
        report_artifact=integrated_quality_report,
        report=report,
        candidate_blend=candidate_blend,
        representative_render=representative_render,
        actions=actions,
    )
    input_sha256 = stable_json_digest(input_payload)
    bundle = QualityReviewBundleV2(
        contract_id=f"quality-review-{session_id}",
        job_id=report.job_id,
        workflow_id=report.workflow_id,
        dispatch_id=report.dispatch_id,
        session_id=session_id,
        input_sha256=input_sha256,
        source_fingerprint=stable_json_digest(
            {
                "input_sha256": input_sha256,
                "quality_source_fingerprint": report.source_fingerprint,
                "quality_outcome": report.outcome,
            }
        ),
        producer=_PRODUCER,
        provenance=[integrated_quality_report, candidate_blend, representative_render],
        created_at=_timestamp(created_at),
        bundle_id=f"quality-review-{session_id}",
        quality_outcome=report.outcome,
        integrated_quality_report=integrated_quality_report,
        candidate_blend=candidate_blend,
        representative_render=representative_render,
        recommended_actions=actions,
    )
    _validate_review_bundle_model(root=root, bundle=bundle, bundle_artifact=None)
    path = (
        root
        / "production"
        / "autonomy_v2"
        / session_id
        / "quality_review_bundle.json"
    )
    artifact = write_immutable_v2_model(root, path, bundle)
    validated = validate_quality_review_bundle_v2(root, artifact)
    return validated, artifact


def validate_quality_review_bundle_v2(
    job_root: Path,
    bundle_artifact: AQV2Artifact,
) -> QualityReviewBundleV2:
    """Rehash and fully recompute one immutable AQ v2 review-only bundle."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    bundle = _load_review_bundle(root, bundle_artifact)
    _validate_review_bundle_model(
        root=root,
        bundle=bundle,
        bundle_artifact=bundle_artifact,
    )
    return bundle


def _terminal_input_payload(
    *,
    report_artifact: AQV2Artifact,
    report: IntegratedQualityReportV02,
    status: str,
    source_freeze: AQV2Artifact | None,
    review_bundle: AQV2Artifact | None,
    reason: str,
) -> dict[str, object]:
    """Build the deterministic terminal input map shared by publication and validation."""

    return {
        "integrated_quality_report": report_artifact.sha256,
        "quality_input_sha256": report.input_sha256,
        "status": status,
        "source_freeze": source_freeze.sha256 if source_freeze is not None else None,
        "review_bundle": review_bundle.sha256 if review_bundle is not None else None,
        "reason": reason,
    }


def _validate_quality_terminal_model(
    *,
    root: Path,
    terminal: QualityTerminalV2,
    terminal_artifact: AQV2Artifact | None,
) -> None:
    """Recompute terminal branch eligibility and every exact dependency binding."""

    report = _load_quality_report(root, terminal.integrated_quality_report)
    expected_id = f"quality-terminal-{terminal.session_id}"
    if (
        terminal.contract_id != expected_id
        or terminal.terminal_id != expected_id
        or terminal.producer != _PRODUCER
    ):
        raise ValueError("AQ v2 quality terminal was not emitted by its host publisher")
    if (
        terminal.job_id != report.job_id
        or terminal.workflow_id != report.workflow_id
        or terminal.dispatch_id != report.dispatch_id
    ):
        raise ValueError("AQ v2 quality terminal identity does not match its IQ 0.2 report")
    expected_provenance = [terminal.integrated_quality_report]
    if terminal.status == "quality_approved":
        if report.outcome != "passed" or not report.quality_accepted:
            raise ValueError("quality_approved requires an exact accepted IQ 0.2 report")
        if terminal.source_freeze is None:
            raise ValueError("quality_approved requires an exact source freeze")
        freeze = _load_source_freeze(root, terminal.source_freeze)
        expected_freeze_id = f"quality-freeze-{terminal.session_id}"
        expected_freeze_path = (
            f"production/autonomy_v2/{terminal.session_id}/source_freeze.json"
        )
        if (
            terminal.source_freeze.path != expected_freeze_path
            or terminal.source_freeze.kind != "source-freeze"
            or terminal.source_freeze.artifact_id != expected_freeze_id
            or freeze.contract_id != expected_freeze_id
            or freeze.freeze_id != expected_freeze_id
            or freeze.producer
            != "codex_blender_modeler.autonomy_v2.delivery_service"
            or freeze.job_id != terminal.job_id
            or freeze.workflow_id != terminal.workflow_id
            or freeze.dispatch_id != terminal.dispatch_id
            or freeze.session_id != terminal.session_id
            or freeze.integrated_quality_report != terminal.integrated_quality_report
        ):
            raise ValueError("quality terminal source freeze does not match its exact report")
        validate_quality_source_freeze(root, freeze)
        frozen_evidence_hashes = {item.sha256 for item in freeze.quality_evidence}
        if _quality_report_evidence_hashes(report) - frozen_evidence_hashes:
            raise ValueError(
                "quality terminal source freeze omits exact IQ 0.2 evidence"
            )
        expected_provenance.append(terminal.source_freeze)
    elif terminal.status == "review_required":
        if report.outcome not in {"needs_revision", "unscorable"} or report.quality_accepted:
            raise ValueError("review_required requires an exact IQ 0.2 review outcome")
        if terminal.review_bundle is None:
            raise ValueError("review_required requires an exact review bundle")
        bundle = validate_quality_review_bundle_v2(root, terminal.review_bundle)
        if (
            bundle.job_id != terminal.job_id
            or bundle.workflow_id != terminal.workflow_id
            or bundle.dispatch_id != terminal.dispatch_id
            or bundle.session_id != terminal.session_id
            or bundle.integrated_quality_report != terminal.integrated_quality_report
        ):
            raise ValueError("quality terminal review bundle does not match its exact report")
        expected_provenance.append(terminal.review_bundle)
    elif terminal.status == "blocked":
        if report.outcome != "blocked" or report.quality_accepted:
            raise ValueError("blocked terminal requires an exact blocked IQ 0.2 report")
    elif report.outcome == "passed" or report.quality_accepted:
        raise ValueError("failed terminal cannot downgrade an accepted IQ 0.2 report")
    expected_bindings = {
        (item.path, item.sha256, item.byte_size) for item in expected_provenance
    }
    actual_bindings = {
        (item.path, item.sha256, item.byte_size) for item in terminal.provenance
    }
    if actual_bindings != expected_bindings or len(terminal.provenance) != len(
        expected_provenance
    ):
        raise ValueError("AQ v2 quality terminal provenance does not match its branch")
    input_payload = _terminal_input_payload(
        report_artifact=terminal.integrated_quality_report,
        report=report,
        status=terminal.status,
        source_freeze=terminal.source_freeze,
        review_bundle=terminal.review_bundle,
        reason=terminal.reason,
    )
    expected_input = stable_json_digest(input_payload)
    expected_source = stable_json_digest(
        {
            "input_sha256": expected_input,
            "quality_source_fingerprint": report.source_fingerprint,
            "status": terminal.status,
        }
    )
    if terminal.input_sha256 != expected_input or terminal.source_fingerprint != expected_source:
        raise ValueError("AQ v2 quality terminal digest is inconsistent")
    if terminal_artifact is not None:
        expected_path = f"production/autonomy_v2/{terminal.session_id}/quality_terminal.json"
        if (
            terminal_artifact.path != expected_path
            or terminal_artifact.kind != "quality-terminal"
            or terminal_artifact.artifact_id != terminal.contract_id
        ):
            raise ValueError("AQ v2 quality terminal is outside its immutable publisher path")


def publish_quality_terminal_v2(
    *,
    job_root: Path,
    session_id: str,
    status: Literal["quality_approved", "review_required", "blocked", "failed"],
    integrated_quality_report: AQV2Artifact,
    reason: str,
    source_freeze: AQV2Artifact | None = None,
    review_bundle: AQV2Artifact | None = None,
    created_at: datetime | None = None,
) -> tuple[QualityTerminalV2, AQV2Artifact]:
    """Publish one immutable quality terminal after strict branch-specific revalidation."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    validate_production_id(session_id, "AQ v2 session ID")
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("AQ v2 quality terminal reason must not be empty")
    report = _load_quality_report(root, integrated_quality_report)
    provenance = [integrated_quality_report]
    if source_freeze is not None:
        provenance.append(source_freeze)
    if review_bundle is not None:
        provenance.append(review_bundle)
    input_payload = _terminal_input_payload(
        report_artifact=integrated_quality_report,
        report=report,
        status=status,
        source_freeze=source_freeze,
        review_bundle=review_bundle,
        reason=normalized_reason,
    )
    input_sha256 = stable_json_digest(input_payload)
    terminal = QualityTerminalV2(
        contract_id=f"quality-terminal-{session_id}",
        job_id=report.job_id,
        workflow_id=report.workflow_id,
        dispatch_id=report.dispatch_id,
        session_id=session_id,
        input_sha256=input_sha256,
        source_fingerprint=stable_json_digest(
            {
                "input_sha256": input_sha256,
                "quality_source_fingerprint": report.source_fingerprint,
                "status": status,
            }
        ),
        producer=_PRODUCER,
        provenance=provenance,
        created_at=_timestamp(created_at),
        terminal_id=f"quality-terminal-{session_id}",
        status=status,
        integrated_quality_report=integrated_quality_report,
        source_freeze=source_freeze,
        review_bundle=review_bundle,
        reason=normalized_reason,
    )
    _validate_quality_terminal_model(
        root=root,
        terminal=terminal,
        terminal_artifact=None,
    )
    path = root / "production" / "autonomy_v2" / session_id / "quality_terminal.json"
    artifact = write_immutable_v2_model(root, path, terminal)
    validated = validate_quality_terminal_v2(root, artifact)
    return validated, artifact


def validate_quality_terminal_v2(
    job_root: Path,
    terminal_artifact: AQV2Artifact,
) -> QualityTerminalV2:
    """Rehash and fully recompute one immutable AQ v2 quality terminal."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    terminal = _load_quality_terminal(root, terminal_artifact)
    _validate_quality_terminal_model(
        root=root,
        terminal=terminal,
        terminal_artifact=terminal_artifact,
    )
    return terminal
