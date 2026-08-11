"""Immutable budget construction and reconstructed usage validation."""

from __future__ import annotations

from datetime import datetime

from ..blender_artifacts import stable_json_digest
from .models import (
    CodexImageArtifact,
    CodexImageGenerationBudget,
    CodexImageGenerationBudgetUsage,
    CodexImageGenerationCompletion,
)


class CodexImageGenerationCapacityError(ValueError):
    """Signal a bounded assignment rejection that must use the plan fallback."""


def build_default_codex_imagegen_budget(
    *,
    contract_id: str,
    budget_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    provider_profile: CodexImageArtifact,
    created_at: datetime,
    producer: str = "codex_blender_modeler.codex_imagegen.budget",
) -> CodexImageGenerationBudget:
    """Create the bounded default budget without credentials or monetary estimates."""

    inputs = {
        "provider_profile": provider_profile.model_dump(mode="json"),
        "caps": {
            "max_total_generations": 4,
            "max_candidates": 3,
            "max_edits_or_refinements": 1,
            "max_generations_per_assignment": 3,
        },
    }
    return CodexImageGenerationBudget(
        contract_id=contract_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest({**inputs, "immutable": True}),
        producer=producer,
        provenance=[provider_profile],
        created_at=created_at,
        budget_id=budget_id,
    )


def budget_snapshot_sha256(budget: CodexImageGenerationBudget) -> str:
    """Hash the complete immutable budget payload for assignment binding."""

    return stable_json_digest(budget.model_dump(mode="json"))


def validate_assignment_capacity(
    budget: CodexImageGenerationBudget,
    usage: CodexImageGenerationBudgetUsage,
    *,
    requested_candidate_count: int,
    edit_or_refinement_count: int = 0,
) -> None:
    """Fail closed before dispatch when any immutable generation cap would be exceeded."""

    _validate_usage_within_budget(budget, usage)
    if requested_candidate_count < 1:
        raise CodexImageGenerationCapacityError(
            "an assignment must request at least one candidate"
        )
    if requested_candidate_count > budget.max_generations_per_assignment:
        raise CodexImageGenerationCapacityError(
            "assignment request exceeds per-assignment generation cap"
        )
    if requested_candidate_count > budget.max_candidates:
        raise CodexImageGenerationCapacityError(
            "assignment request exceeds candidate cap"
        )
    if usage.total_generations + requested_candidate_count > budget.max_total_generations:
        raise CodexImageGenerationCapacityError(
            "assignment request exceeds total generation cap"
        )
    if usage.candidates + requested_candidate_count > budget.max_candidates:
        raise CodexImageGenerationCapacityError(
            "assignment request exceeds remaining candidate cap"
        )
    if usage.edits_or_refinements + edit_or_refinement_count > budget.max_edits_or_refinements:
        raise CodexImageGenerationCapacityError(
            "assignment request exceeds refinement cap"
        )


def apply_completion_usage(
    budget: CodexImageGenerationBudget,
    usage: CodexImageGenerationBudgetUsage,
    completion: CodexImageGenerationCompletion,
    *,
    elapsed_seconds: int,
) -> CodexImageGenerationBudgetUsage:
    """Return reconstructed post-completion usage and reject every cap overflow."""

    if elapsed_seconds < 0:
        raise ValueError("completion elapsed time cannot be negative")
    if elapsed_seconds > budget.timeout_per_assignment_seconds:
        raise ValueError("completion exceeded the immutable assignment timeout")
    updated = CodexImageGenerationBudgetUsage(
        assignments=usage.assignments + 1,
        total_generations=usage.total_generations + completion.generation_count,
        candidates=usage.candidates + len(completion.generated_files),
        edits_or_refinements=(
            usage.edits_or_refinements + completion.edit_or_refinement_count
        ),
        elapsed_seconds=usage.elapsed_seconds + elapsed_seconds,
    )
    _validate_usage_within_budget(budget, updated)
    return updated


def remaining_budget(
    budget: CodexImageGenerationBudget,
    usage: CodexImageGenerationBudgetUsage,
) -> dict[str, int]:
    """Report non-negative remaining caps after validating reconstructed usage."""

    _validate_usage_within_budget(budget, usage)
    return {
        "generations": budget.max_total_generations - usage.total_generations,
        "candidates": budget.max_candidates - usage.candidates,
        "edits_or_refinements": (
            budget.max_edits_or_refinements - usage.edits_or_refinements
        ),
        "elapsed_seconds": budget.max_total_elapsed_seconds - usage.elapsed_seconds,
    }


def _validate_usage_within_budget(
    budget: CodexImageGenerationBudget,
    usage: CodexImageGenerationBudgetUsage,
) -> None:
    """Reject reconstructed usage that already exceeds an immutable cap."""

    checks = {
        "total generation": usage.total_generations <= budget.max_total_generations,
        "candidate": usage.candidates <= budget.max_candidates,
        "refinement": usage.edits_or_refinements <= budget.max_edits_or_refinements,
        "elapsed time": usage.elapsed_seconds <= budget.max_total_elapsed_seconds,
    }
    exceeded = [label for label, passed in checks.items() if not passed]
    if exceeded:
        raise CodexImageGenerationCapacityError(
            "Codex ImageGen budget exceeded: " + ", ".join(exceeded)
        )
