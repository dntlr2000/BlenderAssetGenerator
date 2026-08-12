"""Host-only preservation of native Codex ImageGen PNG bytes before normalization."""

from __future__ import annotations

import hashlib
import io
import os
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from ..blender_artifacts import native_io_path
from .artifacts import (
    artifact_for_codex_image,
    ensure_contained_codex_image_path,
    load_codex_image_model,
    validate_codex_image_artifact,
)
from .assignment import validate_codex_imagegen_assignment_boundary
from .material_loop_models import (
    CodexImageNativeOutputAdoptionReceipt,
    MaterialLoopRasterSize,
    codex_image_native_output_adoption_input_sha256,
    codex_image_native_output_original_artifact_id,
    codex_image_native_output_original_path,
)
from .material_loop_normalization import _adopt_exact_output_bytes
from .models import (
    CodexImageArtifact,
    CodexImageGenerationAssignment,
    DirectOutputRole,
)


def adopt_codex_imagegen_native_output_bytes(
    job_root: Path,
    *,
    assignment_artifact: CodexImageArtifact,
    allowed_source_root: Path,
    native_source_path: Path,
    native_output_id: str,
    ordinal: int,
    output_role: DirectOutputRole,
    receipt_contract_id: str,
    producer: str = "codex_imagegen_native_output_adoption_service",
    created_at: datetime | None = None,
) -> CodexImageNativeOutputAdoptionReceipt:
    """Preserve exact native PNG bytes under one assignment-owned immutable leaf."""

    assignment = load_codex_image_model(
        job_root,
        assignment_artifact,
        CodexImageGenerationAssignment,
    )
    validate_codex_imagegen_assignment_boundary(job_root, assignment)
    _validate_assignment_artifact_path(assignment, assignment_artifact)
    if ordinal >= assignment.requested_candidate_count:
        raise ValueError("native output ordinal is outside the assignment candidate set")
    if output_role not in assignment.allowed_output_roles:
        raise ValueError("native output role is outside the assignment")
    source_root = ensure_contained_codex_image_path(
        allowed_source_root,
        allowed_source_root,
        must_exist=True,
    )
    source_path = ensure_contained_codex_image_path(
        source_root,
        native_source_path,
        must_exist=True,
    )
    if not os.path.isfile(native_io_path(source_path)):
        raise ValueError("native ImageGen source must be a regular file")
    if source_path.suffix.casefold() != ".png":
        raise ValueError("native ImageGen source path must end in .png")
    with open(native_io_path(source_path), "rb") as handle:
        source_bytes = handle.read()
    if not source_bytes:
        raise ValueError("native ImageGen source PNG must be non-empty")
    native_size, source_mode, source_has_alpha, source_icc_sha256 = (
        _inspect_exact_png(source_bytes)
    )
    original_path = codex_image_native_output_original_path(
        assignment.session_id,
        assignment.assignment_id,
        native_output_id,
    )
    preserved_path = _adopt_exact_output_bytes(job_root, original_path, source_bytes)
    original_image = artifact_for_codex_image(
        job_root,
        preserved_path,
        artifact_id=codex_image_native_output_original_artifact_id(native_output_id),
        kind="codex-imagegen-native-original",
        media_type="image/png",
    )
    expected_size = MaterialLoopRasterSize(
        width=assignment.image_size.width,
        height=assignment.image_size.height,
    )
    return CodexImageNativeOutputAdoptionReceipt(
        contract_id=receipt_contract_id,
        job_id=assignment.job_id,
        workflow_id=assignment.workflow_id,
        dispatch_id=assignment.dispatch_id,
        session_id=assignment.session_id,
        input_sha256=codex_image_native_output_adoption_input_sha256(
            assignment=assignment_artifact,
            assignment_id=assignment.assignment_id,
            native_output_id=native_output_id,
            ordinal=ordinal,
            output_role=output_role,
            expected_assignment_size=expected_size,
            native_size=native_size,
            original_image=original_image,
            source_mode=source_mode,
            source_has_alpha=source_has_alpha,
            source_icc_profile_sha256=source_icc_sha256,
        ),
        source_fingerprint=original_image.sha256,
        producer=producer,
        provenance=[assignment_artifact, original_image],
        created_at=created_at or datetime.now(UTC),
        native_output_id=native_output_id,
        assignment=assignment_artifact,
        assignment_id=assignment.assignment_id,
        ordinal=ordinal,
        output_role=output_role,
        expected_assignment_size=expected_size,
        native_size=native_size,
        original_image=original_image,
        source_mode=source_mode,
        source_has_alpha=source_has_alpha,
        source_icc_profile_sha256=source_icc_sha256,
    )


def validate_codex_image_native_output_adoption(
    job_root: Path,
    receipt: CodexImageNativeOutputAdoptionReceipt,
    *,
    require_current_protected_inventory: bool = True,
) -> CodexImageGenerationAssignment:
    """Replay adoption bytes and optionally require the assignment-era job inventory."""

    assignment = load_codex_image_model(
        job_root,
        receipt.assignment,
        CodexImageGenerationAssignment,
    )
    validate_codex_imagegen_assignment_boundary(
        job_root,
        assignment,
        require_current_protected_inventory=require_current_protected_inventory,
    )
    _validate_assignment_artifact_path(assignment, receipt.assignment)
    identity = (
        receipt.job_id,
        receipt.workflow_id,
        receipt.dispatch_id,
        receipt.session_id,
    )
    if identity != (
        assignment.job_id,
        assignment.workflow_id,
        assignment.dispatch_id,
        assignment.session_id,
    ):
        raise ValueError("native output receipt identity differs from its assignment")
    if receipt.assignment_id != assignment.assignment_id:
        raise ValueError("native output receipt binds another assignment identity")
    if receipt.ordinal >= assignment.requested_candidate_count:
        raise ValueError("native output receipt ordinal is outside the assignment")
    if receipt.output_role not in assignment.allowed_output_roles:
        raise ValueError("native output receipt role is outside the assignment")
    expected_size = MaterialLoopRasterSize(
        width=assignment.image_size.width,
        height=assignment.image_size.height,
    )
    if receipt.expected_assignment_size != expected_size:
        raise ValueError("native output receipt expected size differs from the assignment")
    original_path = validate_codex_image_artifact(job_root, receipt.original_image)
    expected_path = codex_image_native_output_original_path(
        assignment.session_id,
        assignment.assignment_id,
        receipt.native_output_id,
    )
    if receipt.original_image.path != expected_path:
        raise ValueError("native output receipt original path differs from its owned leaf")
    with open(native_io_path(original_path), "rb") as handle:
        source_bytes = handle.read()
    native_size, source_mode, source_has_alpha, source_icc_sha256 = (
        _inspect_exact_png(source_bytes)
    )
    if (
        receipt.native_size,
        receipt.source_mode,
        receipt.source_has_alpha,
        receipt.source_icc_profile_sha256,
    ) != (native_size, source_mode, source_has_alpha, source_icc_sha256):
        raise ValueError("native output receipt metadata differs from original PNG bytes")
    expected_input = codex_image_native_output_adoption_input_sha256(
        assignment=receipt.assignment,
        assignment_id=receipt.assignment_id,
        native_output_id=receipt.native_output_id,
        ordinal=receipt.ordinal,
        output_role=receipt.output_role,
        expected_assignment_size=receipt.expected_assignment_size,
        native_size=receipt.native_size,
        original_image=receipt.original_image,
        source_mode=receipt.source_mode,
        source_has_alpha=receipt.source_has_alpha,
        source_icc_profile_sha256=receipt.source_icc_profile_sha256,
    )
    if receipt.input_sha256 != expected_input:
        raise ValueError("native output receipt digest differs from exact replay")
    return assignment


def _validate_assignment_artifact_path(
    assignment: CodexImageGenerationAssignment,
    assignment_artifact: CodexImageArtifact,
) -> None:
    """Require the exact canonical assignment leaf before adopting native bytes."""

    expected = (
        f"production/autonomy_v2/{assignment.session_id}/codex_imagegen/"
        f"assignments/{assignment.assignment_id}/assignment.json"
    )
    if assignment_artifact.path != expected:
        raise ValueError("native output adoption requires the canonical assignment artifact")
    if (
        assignment_artifact.artifact_id != assignment.contract_id
        or assignment_artifact.kind != "codex-image-generation-assignment"
    ):
        raise ValueError("native output adoption assignment artifact identity is inconsistent")


def _inspect_exact_png(
    payload: bytes,
) -> tuple[MaterialLoopRasterSize, str, bool, str | None]:
    """Decode exact in-memory bytes and reject renamed or unsupported raster content."""

    with Image.open(io.BytesIO(payload)) as opened:
        if opened.format != "PNG":
            raise ValueError("native ImageGen source bytes must decode as PNG")
        if opened.mode not in {"L", "LA", "RGB", "RGBA", "P"}:
            raise ValueError("native ImageGen source mode is unsupported")
        size = MaterialLoopRasterSize(width=opened.width, height=opened.height)
        mode = opened.mode
        opened.load()
        has_alpha = "A" in opened.getbands() or (
            opened.mode == "P" and opened.info.get("transparency") is not None
        )
        icc_profile = opened.info.get("icc_profile")
        if icc_profile is not None and not isinstance(icc_profile, bytes):
            raise ValueError("native ImageGen ICC profile must be exact bytes")
        icc_sha256 = (
            hashlib.sha256(icc_profile).hexdigest()
            if isinstance(icc_profile, bytes)
            else None
        )
    return size, mode, has_alpha, icc_sha256


__all__ = [
    "adopt_codex_imagegen_native_output_bytes",
    "validate_codex_image_native_output_adoption",
]
