"""Derived contact-sheet and terminal evidence helpers for ImageGen sessions."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from ..blender_artifacts import native_io_path, stable_json_digest
from .artifacts import (
    artifact_for_codex_image,
    ensure_contained_codex_image_path,
    validate_codex_image_artifact,
)
from .budget import remaining_budget
from .models import (
    CodexImageArtifact,
    CodexImageGenerationBudget,
    CodexImageGenerationBudgetUsage,
    CodexImageGenerationTerminal,
)


def write_candidate_contact_sheet(
    *,
    job_root: Path,
    output_path: Path,
    candidate_images: list[CodexImageArtifact],
    artifact_id: str,
) -> CodexImageArtifact:
    """Write a derived PNG contact sheet without altering or approving source candidates."""

    if not candidate_images:
        raise ValueError("contact sheet requires at least one candidate image")
    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    destination = ensure_contained_codex_image_path(root, output_path, must_exist=False)
    if os.path.exists(native_io_path(destination)):
        raise FileExistsError(destination)
    thumbnails: list[Image.Image] = []
    for artifact in candidate_images:
        source = validate_codex_image_artifact(root, artifact)
        with Image.open(native_io_path(source)) as opened:
            opened.load()
            thumbnail = opened.convert("RGB")
            thumbnail.thumbnail((384, 384))
            thumbnails.append(thumbnail.copy())
    cell_width = 400
    cell_height = 430
    sheet = Image.new("RGB", (cell_width * len(thumbnails), cell_height), "#202124")
    draw = ImageDraw.Draw(sheet)
    for index, (thumbnail, artifact) in enumerate(
        zip(thumbnails, candidate_images, strict=True)
    ):
        x = index * cell_width + (cell_width - thumbnail.width) // 2
        y = 10 + (384 - thumbnail.height) // 2
        sheet.paste(thumbnail, (x, y))
        draw.text((index * cell_width + 12, 402), artifact.artifact_id, fill="white")
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    sheet.save(native_io_path(temporary), format="PNG")
    os.replace(native_io_path(temporary), native_io_path(destination))
    return artifact_for_codex_image(
        root,
        destination,
        artifact_id=artifact_id,
        kind="codex-image-contact-sheet",
        media_type="image/png",
    )


def build_codex_imagegen_terminal(
    *,
    contract_id: str,
    terminal_id: str,
    plan_artifact: CodexImageArtifact,
    budget: CodexImageGenerationBudget,
    budget_artifact: CodexImageArtifact,
    budget_usage: CodexImageGenerationBudgetUsage,
    status: str,
    reason: str,
    created_at: datetime,
    plan_item_id: str | None = None,
    runtime_trigger: str | None = None,
    assignment_artifact: CodexImageArtifact | None = None,
    controller_request_artifact: CodexImageArtifact | None = None,
    controller_result_artifact: CodexImageArtifact | None = None,
    completion_artifact: CodexImageArtifact | None = None,
    selection_artifact: CodexImageArtifact | None = None,
    adoption_artifact: CodexImageArtifact | None = None,
    candidates: list[CodexImageArtifact] | None = None,
    quality_reports: list[CodexImageArtifact] | None = None,
) -> CodexImageGenerationTerminal:
    """Build a terminal record that preserves all supplied candidate evidence."""

    candidate_items = list(candidates or [])
    report_items = list(quality_reports or [])
    remaining_budget(budget, budget_usage)
    provenance = _unique_artifacts(
        [
            plan_artifact,
            budget_artifact,
            *([assignment_artifact] if assignment_artifact is not None else []),
            *(
                [controller_request_artifact]
                if controller_request_artifact is not None
                else []
            ),
            *(
                [controller_result_artifact]
                if controller_result_artifact is not None
                else []
            ),
            *([completion_artifact] if completion_artifact is not None else []),
            *([selection_artifact] if selection_artifact is not None else []),
            *([adoption_artifact] if adoption_artifact is not None else []),
            *candidate_items,
            *report_items,
        ]
    )
    inputs = {
        "plan": plan_artifact.model_dump(mode="json"),
        "budget": budget_artifact.model_dump(mode="json"),
        "budget_usage": budget_usage.model_dump(mode="json"),
        "plan_item_id": plan_item_id,
        "runtime_trigger": runtime_trigger,
        "status": status,
        "reason": reason,
        "assignment": (
            assignment_artifact.model_dump(mode="json")
            if assignment_artifact is not None
            else None
        ),
        "controller_request": (
            controller_request_artifact.model_dump(mode="json")
            if controller_request_artifact is not None
            else None
        ),
        "controller_result": (
            controller_result_artifact.model_dump(mode="json")
            if controller_result_artifact is not None
            else None
        ),
    }
    return CodexImageGenerationTerminal(
        contract_id=contract_id,
        job_id=budget.job_id,
        workflow_id=budget.workflow_id,
        dispatch_id=budget.dispatch_id,
        session_id=budget.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "provenance_sha256": [item.sha256 for item in provenance]}
        ),
        producer="codex_blender_modeler.codex_imagegen.reporting",
        provenance=provenance,
        created_at=created_at,
        terminal_id=terminal_id,
        plan=plan_artifact,
        budget=budget_artifact,
        budget_usage=budget_usage,
        plan_item_id=plan_item_id,
        runtime_trigger=runtime_trigger,
        status=status,
        assignment=assignment_artifact,
        controller_request=controller_request_artifact,
        controller_result=controller_result_artifact,
        completion=completion_artifact,
        selection=selection_artifact,
        adoption=adoption_artifact,
        candidates=candidate_items,
        quality_reports=report_items,
        reason=reason,
    )


def _unique_artifacts(items: list[CodexImageArtifact]) -> list[CodexImageArtifact]:
    """Preserve provenance order while removing byte-identical bindings."""

    result: list[CodexImageArtifact] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.path, item.sha256, item.kind)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result
