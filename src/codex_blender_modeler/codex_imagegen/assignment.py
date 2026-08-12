"""Host-owned assignment construction for controller-mediated image generation."""

from __future__ import annotations

import os
import re
import stat
import unicodedata
from datetime import datetime
from pathlib import Path

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from .artifacts import (
    artifact_for_codex_image,
    ensure_contained_codex_image_path,
    load_codex_image_model,
    validate_codex_image_artifact,
    write_immutable_codex_image_model,
)
from .budget import (
    CodexImageGenerationCapacityError,
    budget_snapshot_sha256,
    validate_assignment_capacity,
)
from .models import (
    CodexBuiltinImageProviderProfile,
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationBudget,
    CodexImageGenerationBudgetUsage,
    CodexImageGenerationPlan,
    CodexImageGenerationPlanItem,
    assignment_payload_sha256,
    text_sha256,
)

__all__ = [
    "artifact_for_codex_image",
    "build_codex_imagegen_assignment",
    "codex_image_source_inventory_sha256",
    "validate_codex_imagegen_assignment_boundary",
    "validate_codex_image_artifact",
    "write_immutable_codex_image_model",
]


def build_codex_imagegen_assignment(
    *,
    contract_id: str,
    assignment_id: str,
    sequence: int,
    plan: CodexImageGenerationPlan,
    plan_artifact: CodexImageArtifact,
    plan_item: CodexImageGenerationPlanItem,
    provider_profile_artifact: CodexImageArtifact,
    budget: CodexImageGenerationBudget,
    budget_artifact: CodexImageArtifact,
    usage: CodexImageGenerationBudgetUsage,
    base_state_artifact: CodexImageArtifact,
    job_root: Path,
    rendered_prompt_text: str,
    reference_images: list[CodexImageArtifact],
    created_at: datetime,
    exact_text_value: str | None = None,
    forbidden_content_notes: list[str] | None = None,
    forbidden_text_notes: list[str] | None = None,
    producer: str = "codex_blender_modeler.codex_imagegen.assignment",
) -> CodexImageGenerationAssignment:
    """Freeze one bounded assignment without invoking an image generator."""

    if plan_item not in plan.items:
        raise ValueError("assignment plan item is not present in the bound plan")
    if plan.provider_profile != provider_profile_artifact:
        raise ValueError("assignment provider profile differs from the bound plan")
    if plan.budget != budget_artifact:
        raise ValueError("assignment budget differs from the bound plan")
    validate_assignment_capacity(
        budget,
        usage,
        requested_candidate_count=plan_item.requested_candidate_count,
    )
    size_cap = budget.max_draft_size if plan_item.quality_level == "low" else budget.max_final_size
    if (
        plan_item.image_size.width > size_cap.width
        or plan_item.image_size.height > size_cap.height
    ):
        raise CodexImageGenerationCapacityError(
            "assignment image size exceeds its quality-level budget cap"
        )
    staging = (
        f"production/autonomy_v2/{plan.session_id}/codex_imagegen/"
        f"assignments/{assignment_id}/staging"
    )
    candidate_paths = [
        f"{staging}/candidate-{index:02d}.png"
        for index in range(plan_item.requested_candidate_count)
    ]
    protected_source_inventory_sha256 = codex_image_source_inventory_sha256(
        job_root,
        plan.session_id,
    )
    prompt_hash = text_sha256(rendered_prompt_text)
    exact_text_hash = _validate_exact_text_exclusion(
        rendered_prompt_text,
        exact_text_value,
    )
    provenance = _unique_artifacts(
        [
            plan_artifact,
            provider_profile_artifact,
            budget_artifact,
            base_state_artifact,
            *reference_images,
        ]
    )
    input_payload = {
        "plan": plan_artifact.model_dump(mode="json"),
        "plan_item": plan_item.model_dump(mode="json"),
        "provider_profile": provider_profile_artifact.model_dump(mode="json"),
        "budget": budget_artifact.model_dump(mode="json"),
        "base_state": base_state_artifact.model_dump(mode="json"),
        "prompt_sha256": prompt_hash,
        "exact_text_sha256": exact_text_hash,
        "reference_images": [item.model_dump(mode="json") for item in reference_images],
    }
    fields: dict[str, object] = {
        "contract_id": contract_id,
        "job_id": plan.job_id,
        "workflow_id": plan.workflow_id,
        "dispatch_id": plan.dispatch_id,
        "session_id": plan.session_id,
        "input_sha256": stable_json_digest(input_payload),
        "source_fingerprint": stable_json_digest(
            {
                **input_payload,
                "protected_source_inventory_sha256": protected_source_inventory_sha256,
            }
        ),
        "producer": producer,
        "provenance": provenance,
        "created_at": created_at,
        "assignment_id": assignment_id,
        "sequence": sequence,
        "plan_item_id": plan_item.plan_item_id,
        "plan": plan_artifact,
        "provider_profile": provider_profile_artifact,
        "budget": budget_artifact,
        "base_state": base_state_artifact,
        "target_material_ids": list(plan_item.target_material_ids),
        "semantic_roles": list(plan_item.semantic_roles),
        "allowed_output_roles": list(plan_item.allowed_output_roles),
        "prompt_template_id": plan_item.prompt_template_id,
        "rendered_prompt_text": rendered_prompt_text,
        "prompt_sha256": prompt_hash,
        "exact_text_sha256": exact_text_hash,
        "exact_text_in_prompt": False,
        "reference_images": list(reference_images),
        "staging_output_directory": staging,
        "candidate_output_paths": candidate_paths,
        "completion_file_target": f"{staging}/completion.json",
        "candidate_count_upper_bound": budget.max_candidates,
        "requested_candidate_count": plan_item.requested_candidate_count,
        "image_size": plan_item.image_size,
        "quality_level": plan_item.quality_level,
        "aspect_ratio": plan_item.aspect_ratio,
        "generation_intent": plan_item.generation_intent,
        "forbidden_content_notes": forbidden_content_notes
        or ["no undeclared objects, marks, logos, or text"],
        "forbidden_text_notes": forbidden_text_notes
        or ["exact signage text is excluded and composed locally"],
        "budget_snapshot_sha256": budget_snapshot_sha256(budget),
        "protected_source_inventory_sha256": protected_source_inventory_sha256,
    }
    draft = CodexImageGenerationAssignment.model_construct(
        **fields,
        assignment_payload_sha256="0" * 64,
    )
    payload = draft.model_dump(mode="json", exclude={"assignment_payload_sha256"})
    return CodexImageGenerationAssignment.model_validate(
        {
            **fields,
            "assignment_payload_sha256": assignment_payload_sha256(payload),
        }
    )


def _unique_artifacts(items: list[CodexImageArtifact]) -> list[CodexImageArtifact]:
    """Preserve artifact order while removing only byte-identical bindings."""

    result: list[CodexImageArtifact] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.path, item.sha256, item.kind)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _validate_exact_text_exclusion(prompt: str, exact_text: str | None) -> str | None:
    """Hash exact signage text only after proving it is absent from the provider prompt."""

    if exact_text is None:
        return None
    if not exact_text.strip():
        raise ValueError("exact signage text cannot be empty")
    normalized_prompt = unicodedata.normalize("NFKC", prompt).casefold()
    normalized_text = unicodedata.normalize("NFKC", exact_text).casefold()
    if normalized_text in normalized_prompt:
        raise ValueError("exact signage text must not appear in an ImageGen prompt")
    return text_sha256(exact_text)


def codex_image_source_inventory_sha256(job_root: Path, session_id: str) -> str:
    """Hash protected job files while excluding only this session's overlay subtree."""

    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", session_id) is None:
        raise ValueError("Codex ImageGen session ID is not portable")
    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    excluded = ensure_contained_codex_image_path(
        root,
        root / "production" / "autonomy_v2" / session_id / "codex_imagegen",
        must_exist=False,
    )
    pending = [root]
    records: list[dict[str, object]] = []
    while pending:
        current = pending.pop()
        with os.scandir(native_io_path(current)) as iterator:
            entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            member = current / entry.name
            metadata = entry.stat(follow_symlinks=False)
            attributes = getattr(metadata, "st_file_attributes", 0)
            if entry.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                raise ValueError("protected source inventory contains a link or junction")
            if stat.S_ISDIR(metadata.st_mode):
                if member != excluded:
                    pending.append(member)
            elif stat.S_ISREG(metadata.st_mode):
                records.append(
                    {
                        "path": member.relative_to(root).as_posix(),
                        "sha256": sha256_file(member),
                        "byte_size": metadata.st_size,
                    }
                )
            else:
                raise ValueError("protected source inventory contains a special file")
    return stable_json_digest(sorted(records, key=lambda item: str(item["path"])))


def validate_codex_imagegen_assignment_boundary(
    job_root: Path,
    assignment: CodexImageGenerationAssignment,
    *,
    require_current_protected_inventory: bool = True,
) -> tuple[
    CodexImageGenerationPlan,
    CodexBuiltinImageProviderProfile,
    CodexImageGenerationBudget,
    CodexImageGenerationPlanItem,
]:
    """Replay exact assignment inputs and optionally require its original job inventory."""

    plan = load_codex_image_model(job_root, assignment.plan, CodexImageGenerationPlan)
    provider = load_codex_image_model(
        job_root,
        assignment.provider_profile,
        CodexBuiltinImageProviderProfile,
    )
    budget = load_codex_image_model(
        job_root,
        assignment.budget,
        CodexImageGenerationBudget,
    )
    validate_codex_image_artifact(job_root, assignment.base_state)
    for reference in assignment.reference_images:
        validate_codex_image_artifact(job_root, reference)
    identity = (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
    )
    for label, model in (("plan", plan), ("provider", provider), ("budget", budget)):
        if (
            model.job_id,
            model.workflow_id,
            model.dispatch_id,
            model.session_id,
        ) != identity:
            raise ValueError(f"assignment {label} identity differs")
    if plan.provider_profile != assignment.provider_profile:
        raise ValueError("assignment provider profile differs from its exact plan")
    if plan.budget != assignment.budget:
        raise ValueError("assignment budget differs from its exact plan")
    matches = [
        item for item in plan.items if item.plan_item_id == assignment.plan_item_id
    ]
    if len(matches) != 1:
        raise ValueError("assignment plan item identity is missing or ambiguous")
    plan_item = matches[0]
    expected_item_fields = (
        plan_item.target_material_ids,
        plan_item.semantic_roles,
        plan_item.allowed_output_roles,
        plan_item.prompt_template_id,
        plan_item.requested_candidate_count,
        plan_item.image_size,
        plan_item.quality_level,
        plan_item.aspect_ratio,
        plan_item.generation_intent,
    )
    actual_item_fields = (
        assignment.target_material_ids,
        assignment.semantic_roles,
        assignment.allowed_output_roles,
        assignment.prompt_template_id,
        assignment.requested_candidate_count,
        assignment.image_size,
        assignment.quality_level,
        assignment.aspect_ratio,
        assignment.generation_intent,
    )
    if actual_item_fields != expected_item_fields:
        raise ValueError("assignment fields differ from its exact plan item")
    if assignment.budget_snapshot_sha256 != budget_snapshot_sha256(budget):
        raise ValueError("assignment immutable budget snapshot differs")
    protected = assignment.protected_source_inventory_sha256
    if require_current_protected_inventory:
        protected = codex_image_source_inventory_sha256(job_root, assignment.session_id)
        if assignment.protected_source_inventory_sha256 != protected:
            raise ValueError("protected job sources changed after ImageGen assignment")
    inputs = {
        "plan": assignment.plan.model_dump(mode="json"),
        "plan_item": plan_item.model_dump(mode="json"),
        "provider_profile": assignment.provider_profile.model_dump(mode="json"),
        "budget": assignment.budget.model_dump(mode="json"),
        "base_state": assignment.base_state.model_dump(mode="json"),
        "prompt_sha256": assignment.prompt_sha256,
        "exact_text_sha256": assignment.exact_text_sha256,
        "reference_images": [
            item.model_dump(mode="json") for item in assignment.reference_images
        ],
    }
    if assignment.input_sha256 != stable_json_digest(inputs):
        raise ValueError("assignment input digest differs from its exact sources")
    if assignment.source_fingerprint != stable_json_digest(
        {**inputs, "protected_source_inventory_sha256": protected}
    ):
        raise ValueError("assignment source fingerprint differs from its exact sources")
    return plan, provider, budget, plan_item
