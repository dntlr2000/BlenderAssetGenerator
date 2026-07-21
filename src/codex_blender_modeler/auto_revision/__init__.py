from typing import Any

from .approval import create_revision_approval, load_revision_approval
from .candidate_builder import build_revision_candidates
from .convergence import evaluate_convergence
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

__all__ = [
    "ConvergenceReport",
    "RevisionApproval",
    "RevisionCandidate",
    "RevisionCandidates",
    "apply_approved_revision",
    "apply_job_approved_revision",
    "approve_job_qa_revision",
    "build_revision_candidates",
    "compile_job_qa_revision",
    "compile_revision_plan",
    "create_revision_approval",
    "evaluate_convergence",
    "load_revision_approval",
]
