from typing import Any

from .approval import create_revision_approval, load_revision_approval
from .candidate_builder import build_revision_candidates
from .convergence import evaluate_convergence
from .convergence_policy import (
    ConvergenceCandidateRejection,
    ConvergenceCandidateSelection,
    select_convergence_candidates,
    validate_convergence_activation,
    validate_iteration_receipt_chain,
)
from .convergence_session_models import (
    ConvergencePathLimit,
    HashBoundConvergenceArtifact,
    VisualConvergenceApproval,
    VisualConvergenceCancellation,
    VisualConvergenceHostSafetyEnvelope,
    VisualConvergenceIteration,
    VisualConvergenceIterationAuthorization,
    VisualConvergencePlan,
    VisualConvergenceReport,
    VisualConvergenceReportManifest,
)
from .guard import apply_approved_revision, compile_revision_plan
from .models import (
    ConvergenceReport,
    RevisionApproval,
    RevisionCandidate,
    RevisionCandidates,
)


def compile_job_qa_revision(
    job_id: str,
    run_id: str,
    *,
    selected_candidate_ids: list[str],
    request: str,
) -> dict[str, Any]:
    """Load the job-level compile service lazily to avoid QA package import cycles."""

    from .service import compile_job_qa_revision as compile_service

    return compile_service(
        job_id,
        run_id,
        selected_candidate_ids=selected_candidate_ids,
        request=request,
    )


def approve_job_qa_revision(
    job_id: str,
    run_id: str,
    *,
    approved_candidate_ids: list[str],
) -> dict[str, Any]:
    """Load the explicit one-time approval service lazily."""

    from .service import approve_job_qa_revision as approve_service

    return approve_service(
        job_id,
        run_id,
        approved_candidate_ids=approved_candidate_ids,
    )


def apply_job_approved_revision(
    job_id: str,
    run_id: str,
    *,
    run_pipeline: bool = True,
    render_engine: str = "eevee",
    render_device: str = "auto",
    minimum_improvement: float = 0.001,
) -> dict[str, Any]:
    """Load the bounded apply, convergence, and rollback service lazily."""

    from .service import apply_job_approved_revision as apply_service

    return apply_service(
        job_id,
        run_id,
        run_pipeline=run_pipeline,
        render_engine=render_engine,
        render_device=render_device,
        minimum_improvement=minimum_improvement,
    )


def plan_job_visual_convergence(
    job_id: str,
    initial_qa_run_id: str,
    *,
    target_direct_score: float,
    target_silhouette_iou: float,
    allowed_target_ids: list[str] | None = None,
    session_id: str | None = None,
    minimum_iteration_gain: float = 0.001,
    minimum_candidate_confidence: float = 0.8,
    max_iterations: int = 3,
    max_candidate_groups_per_iteration: int = 3,
    max_candidates_per_iteration: int = 12,
    max_changed_ids_per_iteration: int = 6,
    path_limits: list[ConvergencePathLimit] | None = None,
) -> dict[str, Any]:
    """Load the exact-plan bounded convergence planner lazily."""

    from .convergence_session import plan_job_visual_convergence as plan_service

    return plan_service(
        job_id,
        initial_qa_run_id,
        target_direct_score=target_direct_score,
        target_silhouette_iou=target_silhouette_iou,
        allowed_target_ids=allowed_target_ids,
        session_id=session_id,
        minimum_iteration_gain=minimum_iteration_gain,
        minimum_candidate_confidence=minimum_candidate_confidence,
        max_iterations=max_iterations,
        max_candidate_groups_per_iteration=max_candidate_groups_per_iteration,
        max_candidates_per_iteration=max_candidates_per_iteration,
        max_changed_ids_per_iteration=max_changed_ids_per_iteration,
        path_limits=path_limits,
    )


def approve_job_visual_convergence(
    job_id: str,
    session_id: str,
    *,
    plan_sha256: str,
    approval_note: str,
) -> dict[str, Any]:
    """Load the exact-hash bounded convergence approval service lazily."""

    from .convergence_session import approve_job_visual_convergence as approve_service

    return approve_service(
        job_id,
        session_id,
        plan_sha256=plan_sha256,
        approval_note=approval_note,
    )


def run_job_visual_convergence(
    job_id: str,
    session_id: str,
    *,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, Any]:
    """Load one resumable approved convergence host step lazily."""

    from .convergence_session import run_job_visual_convergence as run_service

    return run_service(
        job_id,
        session_id,
        render_engine=render_engine,
        render_device=render_device,
    )


def get_job_visual_convergence_status(
    job_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Load the read-only bounded convergence status service lazily."""

    from .convergence_session import (
        get_job_visual_convergence_status as status_service,
    )

    return status_service(job_id, session_id)


def cancel_job_visual_convergence(
    job_id: str,
    session_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    """Load the explicit bounded convergence cancellation service lazily."""

    from .convergence_session import cancel_job_visual_convergence as cancel_service

    return cancel_service(job_id, session_id, reason=reason)


__all__ = [
    "ConvergenceReport",
    "ConvergenceCandidateRejection",
    "ConvergenceCandidateSelection",
    "ConvergencePathLimit",
    "HashBoundConvergenceArtifact",
    "RevisionApproval",
    "RevisionCandidate",
    "RevisionCandidates",
    "apply_approved_revision",
    "apply_job_approved_revision",
    "approve_job_qa_revision",
    "approve_job_visual_convergence",
    "build_revision_candidates",
    "cancel_job_visual_convergence",
    "compile_job_qa_revision",
    "compile_revision_plan",
    "create_revision_approval",
    "evaluate_convergence",
    "get_job_visual_convergence_status",
    "load_revision_approval",
    "plan_job_visual_convergence",
    "run_job_visual_convergence",
    "select_convergence_candidates",
    "validate_convergence_activation",
    "validate_iteration_receipt_chain",
    "VisualConvergenceApproval",
    "VisualConvergenceCancellation",
    "VisualConvergenceHostSafetyEnvelope",
    "VisualConvergenceIteration",
    "VisualConvergenceIterationAuthorization",
    "VisualConvergencePlan",
    "VisualConvergenceReport",
    "VisualConvergenceReportManifest",
]
