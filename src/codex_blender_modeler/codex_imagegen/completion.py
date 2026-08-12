"""Controller completion writing and host-side staged result validation."""

from __future__ import annotations

import os
import shutil
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath

from PIL import Image

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest
from ..production.controller_executor import ControllerResult
from .artifacts import (
    ensure_contained_codex_image_path,
    load_codex_image_model,
    validate_codex_image_artifact,
)
from .assignment import validate_codex_imagegen_assignment_boundary
from .models import (
    CodexGeneratedFile,
    CodexGeneratedImageEvidence,
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    CodexImageGenerationCandidate,
    CodexImageGenerationCompletion,
)


def copy_imagegen_png_and_write_completion(
    *,
    controller_workspace_root: Path,
    allowed_source_root: Path,
    assignment_path: Path,
    assignment_artifact: CodexImageArtifact,
    source_png_paths: list[Path],
    allowed_output_paths: tuple[Path, ...],
    output_roles: list[str],
    completion_id: str,
    controller_kind: str,
    controller_executed_at: datetime,
) -> CodexImageGenerationCompletion:
    """Copy already-produced local PNGs into declared outputs and write completion last."""

    workspace_root = ensure_contained_codex_image_path(
        controller_workspace_root,
        controller_workspace_root,
        must_exist=True,
    )
    source_root = ensure_contained_codex_image_path(
        allowed_source_root,
        allowed_source_root,
        must_exist=True,
    )
    safe_assignment = ensure_contained_codex_image_path(
        workspace_root,
        assignment_path,
        must_exist=True,
    )
    _validate_assignment_snapshot(safe_assignment, assignment_artifact)
    with open(native_io_path(safe_assignment), "rb") as handle:
        assignment = CodexImageGenerationAssignment.model_validate_json(handle.read())
    if len(source_png_paths) != assignment.requested_candidate_count:
        raise ValueError("source PNG count differs from the assignment request")
    if len(output_roles) != len(source_png_paths):
        raise ValueError("every source PNG requires exactly one output role")
    if len(allowed_output_paths) != len(source_png_paths) + 1:
        raise ValueError("allowed controller outputs must include candidates and completion")
    expected_leaves = [
        PurePosixPath(path).name
        for path in [
            *assignment.candidate_output_paths,
            assignment.completion_file_target,
        ]
    ]
    actual_leaves = [path.name for path in allowed_output_paths]
    if actual_leaves != expected_leaves:
        raise ValueError("controller output leaves differ from the assignment")
    safe_outputs = tuple(
        ensure_contained_codex_image_path(workspace_root, path, must_exist=False)
        for path in allowed_output_paths
    )
    if len({path.parent for path in safe_outputs}) != 1:
        raise ValueError("controller outputs must share one assignment-owned directory")
    safe_sources = [
        ensure_contained_codex_image_path(source_root, path, must_exist=True)
        for path in source_png_paths
    ]
    source_inventory = [
        {
            "ordinal": ordinal,
            "sha256": sha256_file(path),
            "byte_size": os.path.getsize(native_io_path(path)),
        }
        for ordinal, path in enumerate(safe_sources)
    ]
    generated: list[CodexGeneratedFile] = []
    for ordinal, (source, destination, output_role) in enumerate(
        zip(safe_sources, safe_outputs[:-1], output_roles, strict=True)
    ):
        if output_role not in assignment.allowed_output_roles:
            raise ValueError("generated file output role is outside the assignment")
        _copy_local_regular_file_once(source, destination)
        source_receipt = source_inventory[ordinal]
        if (
            sha256_file(destination) != source_receipt["sha256"]
            or os.path.getsize(native_io_path(destination))
            != source_receipt["byte_size"]
        ):
            raise ValueError("local generated source changed while it was copied")
        width, height, alpha_present = _inspect_png(destination)
        generated.append(
            CodexGeneratedFile(
                candidate_id=f"{assignment.assignment_id}-candidate-{ordinal:02d}",
                ordinal=ordinal,
                output_role=output_role,
                artifact=CodexImageArtifact(
                    artifact_id=f"{assignment.assignment_id}-png-{ordinal:02d}",
                    kind="codex-image-generated-png",
                    path=assignment.candidate_output_paths[ordinal],
                    sha256=sha256_file(destination),
                    byte_size=os.path.getsize(native_io_path(destination)),
                    media_type="image/png",
                ),
                width=width,
                height=height,
                alpha_present=alpha_present,
            )
        )
    execution_scope = (
        "deterministic_fake" if controller_kind == "fake_for_tests" else "codex_built_in"
    )
    source_kind = (
        "deterministic_fake"
        if controller_kind == "fake_for_tests"
        else "codex_builtin_generated_image"
    )
    input_payload = {
        "assignment": assignment_artifact.model_dump(mode="json"),
        "assignment_payload_sha256": assignment.assignment_payload_sha256,
        "generated_files": [item.model_dump(mode="json") for item in generated],
        "source_inventory_sha256": stable_json_digest(source_inventory),
    }
    completion = CodexImageGenerationCompletion(
        contract_id=completion_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=stable_json_digest(input_payload),
        source_fingerprint=stable_json_digest(
            {**input_payload, "controller_kind": controller_kind}
        ),
        producer="codex_blender_modeler.codex_imagegen.completion.controller_helper",
        provenance=[assignment_artifact, *[item.artifact for item in generated]],
        created_at=controller_executed_at,
        completion_id=completion_id,
        assignment=assignment_artifact,
        assignment_payload_sha256=assignment.assignment_payload_sha256,
        controller_kind=controller_kind,
        execution_scope=execution_scope,
        source_kind=source_kind,
        source_inventory_sha256=stable_json_digest(source_inventory),
        generated_files=generated,
        generation_count=len(generated),
        prompt_echo_sha256=assignment.prompt_sha256,
        controller_executed_at=controller_executed_at,
        status="completed",
    )
    _write_model_once(safe_outputs[-1], completion)
    return completion


def validate_codex_imagegen_completion(
    *,
    job_root: Path,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    controller_result_artifact: CodexImageArtifact | None = None,
    require_current_protected_inventory: bool = True,
) -> tuple[
    CodexImageGenerationAssignment,
    CodexImageGenerationCompletion,
    list[Path],
]:
    """Replay completion bindings, requiring the assignment-era inventory by default."""

    assignment = load_codex_image_model(
        job_root,
        assignment_artifact,
        CodexImageGenerationAssignment,
    )
    _plan, _provider, budget, _plan_item = (
        validate_codex_imagegen_assignment_boundary(
            job_root,
            assignment,
            require_current_protected_inventory=require_current_protected_inventory,
        )
    )
    completion = load_codex_image_model(
        job_root,
        completion_artifact,
        CodexImageGenerationCompletion,
    )
    if completion.status != "completed":
        raise ValueError("only a completed ImageGen result can be adopted")
    _validate_completion_identity(assignment, completion)
    if completion.assignment != assignment_artifact:
        raise ValueError("completion binds a different assignment artifact")
    if completion.assignment_payload_sha256 != assignment.assignment_payload_sha256:
        raise ValueError("completion binds a stale assignment payload")
    if completion.prompt_echo_sha256 != assignment.prompt_sha256:
        raise ValueError("completion prompt echo differs from the assignment")
    if len(completion.generated_files) != assignment.requested_candidate_count:
        raise ValueError("completed output count differs from the assignment request")
    if completion.generation_count > budget.max_total_generations:
        raise ValueError("completion generation count exceeds immutable budget")
    if completion.generation_count > budget.max_generations_per_assignment:
        raise ValueError("completion generation count exceeds per-assignment budget")
    if completion.edit_or_refinement_count > budget.max_edits_or_refinements:
        raise ValueError("completion refinement count exceeds immutable budget")
    if completion.controller_executed_at < assignment.created_at:
        raise ValueError("controller completion predates the immutable assignment")
    generated_paths: list[Path] = []
    for ordinal, generated_file in enumerate(completion.generated_files):
        expected_path = assignment.candidate_output_paths[ordinal]
        if generated_file.ordinal != ordinal or generated_file.artifact.path != expected_path:
            raise ValueError("completion file order or path differs from the assignment")
        if generated_file.candidate_id != (
            f"{assignment.assignment_id}-candidate-{ordinal:02d}"
        ):
            raise ValueError("completion candidate identity differs from the assignment")
        if generated_file.output_role not in assignment.allowed_output_roles:
            raise ValueError("completion file role is outside the assignment")
        path = validate_codex_image_artifact(job_root, generated_file.artifact)
        width, height, alpha_present = _inspect_png(path)
        if (width, height) != (
            assignment.image_size.width,
            assignment.image_size.height,
        ):
            raise ValueError("generated PNG dimensions differ from the assignment")
        if (generated_file.width, generated_file.height) != (width, height):
            raise ValueError("completion PNG dimensions differ from decoded bytes")
        if generated_file.alpha_present != alpha_present:
            raise ValueError("completion alpha claim differs from decoded PNG bytes")
        generated_paths.append(path)
    if controller_result_artifact is not None:
        _validate_controller_result_binding(
            job_root=job_root,
            assignment=assignment,
            completion_artifact=completion_artifact,
            generated_files=completion.generated_files,
            controller_result_artifact=controller_result_artifact,
        )
    return assignment, completion, generated_paths


def build_codex_imagegen_candidate(
    *,
    contract_id: str,
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
    completion_artifact: CodexImageArtifact,
    controller_request_artifact: CodexImageArtifact,
    controller_result_artifact: CodexImageArtifact,
    generated_file: CodexGeneratedFile,
    created_at: datetime,
) -> CodexImageGenerationCandidate:
    """Build one host-owned candidate that binds controller execution evidence."""

    inputs = {
        "assignment": assignment_artifact.model_dump(mode="json"),
        "completion": completion_artifact.model_dump(mode="json"),
        "controller_request": controller_request_artifact.model_dump(mode="json"),
        "controller_result": controller_result_artifact.model_dump(mode="json"),
        "generated_file": generated_file.model_dump(mode="json"),
    }
    provenance = [
        assignment_artifact,
        completion_artifact,
        controller_request_artifact,
        controller_result_artifact,
        generated_file.artifact,
    ]
    return CodexImageGenerationCandidate(
        contract_id=contract_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "source_sha256": generated_file.artifact.sha256}
        ),
        producer="codex_blender_modeler.codex_imagegen.completion",
        provenance=provenance,
        created_at=created_at,
        candidate_id=generated_file.candidate_id,
        assignment=assignment_artifact,
        completion=completion_artifact,
        controller_request=controller_request_artifact,
        controller_result=controller_result_artifact,
        generated_file=generated_file,
        target_material_ids=list(assignment.target_material_ids),
        semantic_roles=list(assignment.semantic_roles),
        generation_intent=assignment.generation_intent,
    )


def build_generated_image_evidence(
    *,
    contract_id: str,
    candidate: CodexImageGenerationCandidate,
    candidate_artifact: CodexImageArtifact,
    created_at: datetime,
) -> CodexGeneratedImageEvidence:
    """Describe one generated candidate honestly without claiming a PBR texture set."""

    inputs = {
        "candidate": candidate_artifact.model_dump(mode="json"),
        "generated_file": candidate.generated_file.model_dump(mode="json"),
    }
    provenance = _unique_artifacts(
        [*candidate.provenance, candidate_artifact, candidate.generated_file.artifact]
    )
    return CodexGeneratedImageEvidence(
        contract_id=contract_id,
        job_id=candidate.job_id,
        workflow_id=candidate.workflow_id,
        dispatch_id=candidate.dispatch_id,
        session_id=candidate.session_id,
        input_sha256=stable_json_digest(inputs),
        source_fingerprint=stable_json_digest(
            {**inputs, "source_sha256": candidate.generated_file.artifact.sha256}
        ),
        producer="codex_blender_modeler.codex_imagegen.completion",
        provenance=provenance,
        created_at=created_at,
        evidence_id=contract_id,
        assignment=candidate.assignment,
        completion=candidate.completion,
        controller_request=candidate.controller_request,
        controller_result=candidate.controller_result,
        candidate=candidate_artifact,
        candidate_id=candidate.candidate_id,
        generated_file=candidate.generated_file,
        target_material_ids=list(candidate.target_material_ids),
        semantic_roles=list(candidate.semantic_roles),
        generation_intent=candidate.generation_intent,
    )


def _copy_local_regular_file_once(source: Path, destination: Path) -> None:
    """Copy one local regular file without overwriting a controller workspace output."""

    resolved_source = source.expanduser().resolve(strict=True)
    if not os.path.isfile(native_io_path(resolved_source)) or _is_link_like(source):
        raise ValueError("ImageGen source must be a non-linked local regular file")
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    with open(native_io_path(resolved_source), "rb") as source_handle, open(
        native_io_path(destination),
        "xb",
    ) as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)


def _validate_assignment_snapshot(
    path: Path,
    artifact: CodexImageArtifact,
) -> None:
    """Require the isolated assignment snapshot to match its canonical exact binding."""

    if not os.path.isfile(native_io_path(path)) or _is_link_like(path):
        raise ValueError("controller assignment snapshot must be a non-linked regular file")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError("controller assignment snapshot size differs")
    if sha256_file(path) != artifact.sha256:
        raise ValueError("controller assignment snapshot hash differs")


def _is_link_like(path: Path) -> bool:
    """Reject symbolic links and Windows reparse points for local controller sources."""

    metadata = os.lstat(native_io_path(path))
    attributes = getattr(metadata, "st_file_attributes", 0)
    return os.path.islink(native_io_path(path)) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _inspect_png(path: Path) -> tuple[int, int, bool]:
    """Fully decode one PNG and report exact dimensions and alpha-channel presence."""

    with Image.open(native_io_path(path)) as image:
        if image.format != "PNG":
            raise ValueError("generated image bytes must decode as PNG")
        image.load()
        alpha_present = "A" in image.getbands()
        return image.width, image.height, alpha_present


def _write_model_once(path: Path, model: CodexImageGenerationCompletion) -> None:
    """Write controller completion JSON last and refuse an existing output."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    encoded = model.model_dump_json(indent=2).encode("utf-8") + b"\n"
    with open(native_io_path(path), "xb") as handle:
        handle.write(encoded)


def _validate_completion_identity(
    assignment: CodexImageGenerationAssignment,
    completion: CodexImageGenerationCompletion,
) -> None:
    """Require assignment and completion to share every immutable identity field."""

    assignment_identity = (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
        assignment.profile_id,
        assignment.provider_id,
    )
    completion_identity = (
        completion.job_id,
        completion.workflow_id,
        completion.dispatch_id,
        completion.session_id,
        completion.profile_id,
        completion.provider_id,
    )
    if assignment_identity != completion_identity:
        raise ValueError("completion identity differs from the assignment")


def _validate_controller_result_binding(
    *,
    job_root: Path,
    assignment: CodexImageGenerationAssignment,
    completion_artifact: CodexImageArtifact,
    generated_files: list[CodexGeneratedFile],
    controller_result_artifact: CodexImageArtifact,
) -> None:
    """Require a completed raw controller result to publish the exact staged file set."""

    result = load_codex_image_model(
        job_root,
        controller_result_artifact,
        ControllerResult,
    )
    if result.status != "completed":
        raise ValueError("ImageGen completion requires a completed controller result")
    if result.controller_kind not in {"desktop_in_session", "fake_for_tests"}:
        raise ValueError("controller result kind cannot produce ImageGen evidence")
    if (
        result.job_id,
        result.workflow_id,
        result.dispatch_id,
        result.session_id,
    ) != (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
    ):
        raise ValueError("controller result identity differs from the assignment")
    expected = {
        (item.artifact.path, item.artifact.sha256, item.artifact.byte_size)
        for item in generated_files
    }
    expected.add(
        (
            completion_artifact.path,
            completion_artifact.sha256,
            completion_artifact.byte_size,
        )
    )
    actual = {(item.path, item.sha256, item.byte_size) for item in result.outputs}
    if actual != expected:
        raise ValueError("controller result output inventory differs from completion bytes")


def _unique_artifacts(items: list[CodexImageArtifact]) -> list[CodexImageArtifact]:
    """Preserve provenance order while removing byte-identical artifact bindings."""

    result: list[CodexImageArtifact] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (item.path, item.sha256, item.kind)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result
