"""Strict material framework-failure and retry-supersession construction helpers."""

from __future__ import annotations

from datetime import datetime

from .models import (
    ExactArtifact,
    MaterialClosureIssue,
    MaterialFrameworkFailureContext,
    MaterialFrameworkFailureReport,
    MaterialRetrySupersessionReceipt,
)


def build_material_framework_failure_report(
    *,
    report_id: str,
    context: MaterialFrameworkFailureContext,
    issues: list[MaterialClosureIssue],
    failure_categories: list[str],
    recommended_action: str,
    retry_forbidden_reason: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    producer: str,
    producer_version: str,
    created_at: datetime,
) -> MaterialFrameworkFailureReport:
    """Build one complete framework report from the request-bound failure context."""

    return MaterialFrameworkFailureReport(
        report_id=report_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        producer=producer,
        producer_version=producer_version,
        created_at=created_at,
        state_sequence=context.state_sequence,
        current_state=context.current_state,
        canonical_snapshot=context.canonical_snapshot,
        latest_successful_rollback_receipt=(
            context.latest_successful_rollback_receipt
        ),
        pending_retry_plan=context.pending_retry_plan,
        pending_retry_approval=context.pending_retry_approval,
        controller_execution_count=context.controller_execution_count,
        rollback_count=context.rollback_count,
        budget_usage=context.budget_usage,
        aq_budget_observation=context.aq_budget_observation,
        neutral_preview_present=context.neutral_preview_present,
        material_phase_receipt_present=context.material_phase_receipt_present,
        integrated_quality_entered=context.integrated_quality_entered,
        failure_categories=failure_categories,
        missing_or_invalid_dependencies=issues,
        asset_quality_failure="unknown",
        recommended_action=recommended_action,
        retry_forbidden_reason=retry_forbidden_reason,
    )


def build_material_retry_supersession_receipt(
    *,
    receipt_id: str,
    retry_plan: ExactArtifact,
    retry_approval: ExactArtifact | None,
    retry_approval_absence: ExactArtifact | None,
    current_state: ExactArtifact,
    framework_failure_report: ExactArtifact,
    supersession_reason: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    producer: str,
    producer_version: str,
    created_at: datetime,
) -> MaterialRetrySupersessionReceipt:
    """Supersede an approved or unapproved retry without changing historical artifacts."""

    return MaterialRetrySupersessionReceipt(
        receipt_id=receipt_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        producer=producer,
        producer_version=producer_version,
        created_at=created_at,
        retry_plan=retry_plan,
        retry_approval=retry_approval,
        retry_approval_absence=retry_approval_absence,
        current_state=current_state,
        framework_failure_report=framework_failure_report,
        supersession_reason=supersession_reason,
    )


def retry_is_executable(
    *,
    retry_plan: ExactArtifact,
    supersession_receipts: list[MaterialRetrySupersessionReceipt],
) -> bool:
    """Deny an exact retry whenever one current supersession receipt binds its bytes."""

    return not any(
        receipt.retry_plan.path == retry_plan.path
        and receipt.retry_plan.sha256 == retry_plan.sha256
        for receipt in supersession_receipts
    )


__all__ = [
    "build_material_framework_failure_report",
    "build_material_retry_supersession_receipt",
    "retry_is_executable",
]
