"""Deterministic source-preserving native normalization for ImageGen material inputs."""

from __future__ import annotations

import hashlib
import io
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from PIL import Image

from ..blender_artifacts import native_io_path, stable_json_digest
from .artifacts import (
    artifact_for_codex_image,
    ensure_contained_codex_image_path,
    load_codex_image_model,
    validate_codex_image_artifact,
)
from .material_loop_models import (
    CodexImageNativeOutputAdoptionReceipt,
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
    MaterialLoopRasterSize,
    NormalizationPreference,
    canonical_native_normalization_geometry,
    imagegen_native_normalization_output_artifact_id,
    imagegen_native_normalization_output_path,
    imagegen_native_normalization_plan_input_sha256,
    imagegen_native_normalization_plan_path,
)
from .models import CodexImageArtifact


def plan_native_image_normalization(
    job_root: Path,
    *,
    contract_id: str,
    job_id: str,
    workflow_id: str,
    dispatch_id: str,
    session_id: str,
    source_image: CodexImageArtifact,
    output_path: str,
    target_size: MaterialLoopRasterSize,
    source_color_space: Literal["srgb", "non_color"],
    alpha_policy: Literal["preserve", "drop", "opaque_add"] = "preserve",
    native_output_policy: Literal[
        "exact_known_size",
        "allowed_size_set",
        "bounded_native_size",
        "preserve_native_then_normalize",
    ] = "preserve_native_then_normalize",
    allowed_native_sizes: list[MaterialLoopRasterSize] | None = None,
    preferred_operation: NormalizationPreference = "contain_pad",
    maximum_automatic_aspect_delta: float = 0.35,
    pad_rgba: tuple[int, int, int, int] = (0, 0, 0, 0),
    producer: str = "codex_imagegen_native_normalization_service",
    created_at: datetime | None = None,
) -> ImageGenNativeNormalizationPlan:
    """Inspect exact source bytes and construct one bounded, non-stretch plan."""

    source_path = validate_codex_image_artifact(job_root, source_image)
    with Image.open(native_io_path(source_path)) as opened:
        if opened.format != "PNG":
            raise ValueError("native normalization source bytes must decode as PNG")
        source_size = MaterialLoopRasterSize(width=opened.width, height=opened.height)
        source_mode = opened.mode
        if source_mode not in {"L", "LA", "RGB", "RGBA", "P"}:
            raise ValueError("native normalization source mode is unsupported")
        opened.load()
        source_has_alpha = _image_has_alpha(opened)
        source_icc_profile_sha256 = _icc_profile_sha256(opened.info.get("icc_profile"))
    source_aspect = source_size.width / source_size.height
    target_aspect = target_size.width / target_size.height
    aspect_delta = abs(source_aspect / target_aspect - 1.0)
    expected_output_path = imagegen_native_normalization_output_path(
        session_id,
        contract_id,
    )
    if output_path != expected_output_path:
        raise ValueError("normalization output must use its exact run-owned PNG leaf")
    operation, crop, content, padding = canonical_native_normalization_geometry(
        source_size,
        target_size,
        requested_operation=preferred_operation,
        maximum_automatic_aspect_delta=maximum_automatic_aspect_delta,
        alpha_policy=alpha_policy,
    )
    output_media_type: Literal["image/png", "source_media_type"] = (
        "source_media_type" if operation == "pass_through" else "image/png"
    )
    allowed_sizes = allowed_native_sizes or []
    input_sha256 = imagegen_native_normalization_plan_input_sha256(
        source_image=source_image,
        output_path=output_path,
        source_size=source_size,
        target_size=target_size,
        native_output_policy=native_output_policy,
        allowed_native_sizes=allowed_sizes,
        requested_operation=preferred_operation,
        maximum_automatic_aspect_delta=maximum_automatic_aspect_delta,
        source_color_space=source_color_space,
        source_mode=source_mode,
        source_has_alpha=source_has_alpha,
        source_icc_profile_sha256=source_icc_profile_sha256,
        alpha_policy=alpha_policy,
        pad_rgba=pad_rgba,
    )
    return ImageGenNativeNormalizationPlan(
        contract_id=contract_id,
        job_id=job_id,
        workflow_id=workflow_id,
        dispatch_id=dispatch_id,
        session_id=session_id,
        input_sha256=input_sha256,
        source_fingerprint=source_image.sha256,
        producer=producer,
        provenance=[source_image],
        created_at=created_at or datetime.now(UTC),
        source_image=source_image,
        output_path=output_path,
        source_size=source_size,
        target_size=target_size,
        native_output_policy=native_output_policy,
        allowed_native_sizes=allowed_sizes,
        requested_operation=preferred_operation,
        operation=operation,
        crop_rectangle=crop,
        content_size=content,
        padding=padding,
        pad_rgba=pad_rgba,
        source_color_space=source_color_space,
        source_mode=source_mode,
        source_has_alpha=source_has_alpha,
        source_icc_profile_sha256=source_icc_profile_sha256,
        alpha_policy=alpha_policy,
        source_aspect_ratio=source_aspect,
        target_aspect_ratio=target_aspect,
        aspect_ratio_relative_delta=aspect_delta,
        maximum_automatic_aspect_delta=maximum_automatic_aspect_delta,
        output_media_type=output_media_type,
    )


def validate_native_normalization_plan(
    job_root: Path,
    plan: ImageGenNativeNormalizationPlan,
) -> None:
    """Replay caller intent, source bytes, metadata, and canonical output placement."""

    expected_output = imagegen_native_normalization_output_path(
        plan.session_id,
        plan.contract_id,
    )
    if plan.output_path != expected_output:
        raise ValueError("normalization output differs from its exact run-owned PNG leaf")
    expected_input = imagegen_native_normalization_plan_input_sha256(
        source_image=plan.source_image,
        output_path=plan.output_path,
        source_size=plan.source_size,
        target_size=plan.target_size,
        native_output_policy=plan.native_output_policy,
        allowed_native_sizes=plan.allowed_native_sizes,
        requested_operation=plan.requested_operation,
        maximum_automatic_aspect_delta=plan.maximum_automatic_aspect_delta,
        source_color_space=plan.source_color_space,
        source_mode=plan.source_mode,
        source_has_alpha=plan.source_has_alpha,
        source_icc_profile_sha256=plan.source_icc_profile_sha256,
        alpha_policy=plan.alpha_policy,
        pad_rgba=plan.pad_rgba,
    )
    if plan.input_sha256 != expected_input:
        raise ValueError("normalization plan input digest differs from exact replay")
    expected_geometry = canonical_native_normalization_geometry(
        plan.source_size,
        plan.target_size,
        requested_operation=plan.requested_operation,
        maximum_automatic_aspect_delta=plan.maximum_automatic_aspect_delta,
        alpha_policy=plan.alpha_policy,
    )
    if (
        plan.operation,
        plan.crop_rectangle,
        plan.content_size,
        plan.padding,
    ) != expected_geometry:
        raise ValueError("normalization geometry differs from exact caller-intent replay")
    source_path = validate_codex_image_artifact(job_root, plan.source_image)
    _validate_source_metadata(source_path, plan)


def execute_native_image_normalization(
    job_root: Path,
    plan: ImageGenNativeNormalizationPlan,
    plan_artifact: CodexImageArtifact,
    *,
    receipt_contract_id: str,
    native_output_adoption_receipt: CodexImageArtifact | None = None,
    producer: str = "codex_imagegen_native_normalization_service",
    created_at: datetime | None = None,
) -> ImageGenNativeNormalizationReceipt:
    """Adopt only exact deterministic output bytes and return an unpersisted receipt."""

    expected_plan_path = imagegen_native_normalization_plan_path(
        plan.session_id,
        plan.contract_id,
    )
    if plan_artifact.path != expected_plan_path:
        raise ValueError("normalization plan artifact is outside its exact run-owned leaf")
    if (
        plan_artifact.artifact_id != plan.contract_id
        or plan_artifact.kind != "imagegen-native-normalization-plan"
    ):
        raise ValueError("normalization plan artifact identity is inconsistent")
    persisted_plan = load_codex_image_model(
        job_root,
        plan_artifact,
        ImageGenNativeNormalizationPlan,
    )
    if persisted_plan != plan:
        raise ValueError("normalization plan object does not match its exact artifact")
    validate_native_normalization_plan(job_root, plan)
    source_path = validate_codex_image_artifact(job_root, plan.source_image)
    _validate_source_metadata(source_path, plan)
    if plan.operation == "review_required":
        return _normalization_receipt(
            plan,
            plan_artifact,
            normalized_image=None,
            native_output_adoption_receipt=native_output_adoption_receipt,
            receipt_contract_id=receipt_contract_id,
            producer=producer,
            created_at=created_at,
            output_mode=None,
            output_has_alpha=None,
            output_icc_profile_sha256=None,
        )
    payload, output_mode, output_has_alpha, output_icc_profile_sha256 = (
        _render_normalized_bytes(source_path, plan)
    )
    destination = _adopt_exact_output_bytes(job_root, plan.output_path, payload)
    media_type = (
        plan.source_image.media_type
        if plan.output_media_type == "source_media_type"
        else "image/png"
    )
    normalized_image = artifact_for_codex_image(
        job_root,
        destination,
        artifact_id=imagegen_native_normalization_output_artifact_id(plan.contract_id),
        kind="codex-imagegen-normalized-material-source",
        media_type=media_type,
    )
    validate_codex_image_artifact(job_root, plan.source_image)
    return _normalization_receipt(
        plan,
        plan_artifact,
        normalized_image=normalized_image,
        native_output_adoption_receipt=native_output_adoption_receipt,
        receipt_contract_id=receipt_contract_id,
        producer=producer,
        created_at=created_at,
        output_mode=output_mode,
        output_has_alpha=output_has_alpha,
        output_icc_profile_sha256=output_icc_profile_sha256,
    )


def validate_native_normalization_receipt(
    job_root: Path,
    plan: ImageGenNativeNormalizationPlan,
    receipt: ImageGenNativeNormalizationReceipt,
    *,
    require_current_protected_inventory: bool = True,
) -> None:
    """Replay normalization bytes and optionally require assignment-era inventory."""

    persisted_plan = load_codex_image_model(
        job_root,
        receipt.plan,
        ImageGenNativeNormalizationPlan,
    )
    if persisted_plan != plan:
        raise ValueError("normalization receipt points to a different plan")
    expected_plan_path = imagegen_native_normalization_plan_path(
        plan.session_id,
        plan.contract_id,
    )
    if (
        receipt.plan.path != expected_plan_path
        or receipt.plan.artifact_id != plan.contract_id
        or receipt.plan.kind != "imagegen-native-normalization-plan"
    ):
        raise ValueError("normalization receipt plan artifact identity is inconsistent")
    validate_native_normalization_plan(job_root, plan)
    if (
        receipt.job_id,
        receipt.workflow_id,
        receipt.dispatch_id,
        receipt.session_id,
        receipt.profile_id,
    ) != (
        plan.job_id,
        plan.workflow_id,
        plan.dispatch_id,
        plan.session_id,
        plan.profile_id,
    ):
        raise ValueError("normalization receipt identity differs from its plan")
    shared_fields = (
        "source_image",
        "source_size",
        "target_size",
        "operation",
        "crop_rectangle",
        "content_size",
        "padding",
        "source_aspect_ratio",
        "target_aspect_ratio",
        "source_color_space",
        "source_mode",
        "source_has_alpha",
        "source_icc_profile_sha256",
        "alpha_policy",
        "algorithm_id",
        "resampling",
    )
    if any(getattr(receipt, field) != getattr(plan, field) for field in shared_fields):
        raise ValueError("normalization receipt fields differ from the exact plan")
    source_path = validate_codex_image_artifact(job_root, plan.source_image)
    _validate_source_metadata(source_path, plan)
    expected_input_sha256 = _normalization_receipt_input_sha256(
        plan_artifact=receipt.plan,
        source_image=plan.source_image,
        normalized_image=receipt.normalized_image,
        native_output_adoption_receipt=receipt.native_output_adoption_receipt,
    )
    if receipt.input_sha256 != expected_input_sha256:
        raise ValueError("normalization receipt input hash is inconsistent")
    _validate_native_adoption_binding(
        job_root,
        plan,
        receipt,
        require_current_protected_inventory=require_current_protected_inventory,
    )
    if plan.operation == "review_required":
        if receipt.status != "review_required" or receipt.normalized_image is not None:
            raise ValueError("review-required plan cannot claim normalized output bytes")
        return
    if receipt.normalized_image is None:
        raise ValueError("successful normalization receipt omits output bytes")
    expected_status = "pass_through" if plan.operation == "pass_through" else "normalized"
    if receipt.status != expected_status:
        raise ValueError("normalization receipt status differs from the exact plan")
    expected_payload, expected_mode, expected_alpha, expected_icc = (
        _render_normalized_bytes(source_path, plan)
    )
    expected_media_type = (
        plan.source_image.media_type
        if plan.output_media_type == "source_media_type"
        else "image/png"
    )
    expected_sha256 = hashlib.sha256(expected_payload).hexdigest()
    if (
        receipt.normalized_image.path != plan.output_path
        or receipt.normalized_image.artifact_id
        != imagegen_native_normalization_output_artifact_id(plan.contract_id)
        or receipt.normalized_image.media_type != expected_media_type
        or receipt.normalized_image.sha256 != expected_sha256
        or receipt.normalized_image.byte_size != len(expected_payload)
    ):
        raise ValueError("normalized output differs from deterministic plan bytes")
    if (
        receipt.output_mode,
        receipt.output_has_alpha,
        receipt.output_icc_profile_sha256,
    ) != (expected_mode, expected_alpha, expected_icc):
        raise ValueError("normalization receipt output metadata differs from replay")
    output_path = validate_codex_image_artifact(job_root, receipt.normalized_image)
    with Image.open(native_io_path(output_path)) as opened:
        opened.load()
        if opened.size != (plan.target_size.width, plan.target_size.height):
            raise ValueError("normalized output dimensions changed")
        if opened.mode != expected_mode:
            raise ValueError("normalized output mode changed")
        if _image_has_alpha(opened) != expected_alpha:
            raise ValueError("normalized output alpha state changed")
        if _icc_profile_sha256(opened.info.get("icc_profile")) != expected_icc:
            raise ValueError("normalized output ICC profile changed")


def _validate_source_metadata(path: Path, plan: ImageGenNativeNormalizationPlan) -> None:
    """Reject changed dimensions, mode, alpha, or ICC metadata despite matching plan shape."""

    with Image.open(native_io_path(path)) as opened:
        if opened.format != "PNG":
            raise ValueError("normalization source bytes no longer decode as PNG")
        if opened.size != (plan.source_size.width, plan.source_size.height):
            raise ValueError("normalization source dimensions differ from the plan")
        if opened.mode != plan.source_mode:
            raise ValueError("normalization source mode differs from the plan")
        opened.load()
        if _image_has_alpha(opened) != plan.source_has_alpha:
            raise ValueError("normalization source alpha state differs from the plan")
        if _icc_profile_sha256(opened.info.get("icc_profile")) != (
            plan.source_icc_profile_sha256
        ):
            raise ValueError("normalization source ICC profile differs from the plan")


def _render_normalized_bytes(
    source_path: Path,
    plan: ImageGenNativeNormalizationPlan,
) -> tuple[bytes, Literal["L", "LA", "RGB", "RGBA", "P"], bool, str | None]:
    """Render the exact pass-through or transformed payload entirely before adoption."""

    if plan.operation == "pass_through":
        with open(native_io_path(source_path), "rb") as handle:
            return (
                handle.read(),
                plan.source_mode,  # type: ignore[return-value]
                plan.source_has_alpha,
                plan.source_icc_profile_sha256,
            )
    with Image.open(native_io_path(source_path)) as opened:
        opened.load()
        icc_profile = opened.info.get("icc_profile")
        working = _apply_alpha_policy(opened, plan.alpha_policy)
        if plan.operation in {"center_crop", "tile_crop"}:
            crop = plan.crop_rectangle
            if crop is None:
                raise ValueError("crop operation is missing its exact rectangle")
            working = working.crop(
                (crop.x, crop.y, crop.x + crop.width, crop.y + crop.height)
            ).resize(
                (plan.target_size.width, plan.target_size.height),
                resample=Image.Resampling.LANCZOS,
            )
        elif plan.operation == "contain_pad":
            content = plan.content_size
            padding = plan.padding
            if content is None or padding is None:
                raise ValueError("contain+pad operation is missing exact geometry")
            resized = working.resize(
                (content.width, content.height),
                resample=Image.Resampling.LANCZOS,
            )
            canvas_mode = "RGBA" if working.mode in {"RGBA", "LA"} else "RGB"
            if working.mode != canvas_mode:
                resized = resized.convert(canvas_mode)
            background = plan.pad_rgba if canvas_mode == "RGBA" else plan.pad_rgba[:3]
            working = Image.new(
                canvas_mode,
                (plan.target_size.width, plan.target_size.height),
                background,
            )
            working.paste(resized, (padding.left, padding.top))
        else:
            raise ValueError("review-required normalization cannot render output")
        buffer = io.BytesIO()
        save_options: dict[str, object] = {
            "format": "PNG",
            "optimize": False,
            "compress_level": 9,
        }
        if icc_profile is not None:
            save_options["icc_profile"] = icc_profile
        working.save(buffer, **save_options)
        output_mode = working.mode
        if output_mode not in {"L", "LA", "RGB", "RGBA", "P"}:
            raise ValueError("normalization produced an unsupported output mode")
        return (
            buffer.getvalue(),
            output_mode,  # type: ignore[return-value]
            _image_has_alpha(working),
            _icc_profile_sha256(icc_profile),
        )


def _apply_alpha_policy(
    image: Image.Image,
    alpha_policy: Literal["preserve", "drop", "opaque_add"],
) -> Image.Image:
    """Convert pixels without silently changing the declared alpha policy."""

    if alpha_policy == "drop":
        return image.convert("RGB")
    if alpha_policy == "opaque_add":
        result = image.convert("RGBA")
        result.putalpha(255)
        return result
    return image.convert("RGBA") if _image_has_alpha(image) else image.convert("RGB")


def _adopt_exact_output_bytes(job_root: Path, output_path: str, payload: bytes) -> Path:
    """Atomically create a derivative or adopt only an identical crash-left output."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    destination = ensure_contained_codex_image_path(
        root,
        root / output_path,
        must_exist=False,
    )
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    ensure_contained_codex_image_path(root, destination.parent, must_exist=True)
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    if os.path.exists(native_io_path(destination)):
        _require_existing_exact_bytes(destination, payload, expected_sha256)
        return ensure_contained_codex_image_path(root, destination, must_exist=True)
    temporary = ensure_contained_codex_image_path(
        root,
        destination.parent / f".{destination.name}.{uuid4().hex}.tmp",
        must_exist=False,
    )
    try:
        with open(native_io_path(temporary), "xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(native_io_path(temporary), native_io_path(destination))
        except FileExistsError:
            _require_existing_exact_bytes(destination, payload, expected_sha256)
        except OSError as error:
            if os.path.exists(native_io_path(destination)):
                _require_existing_exact_bytes(destination, payload, expected_sha256)
            else:
                raise OSError(
                    "atomic no-overwrite normalization publication is unavailable"
                ) from error
    finally:
        if os.path.exists(native_io_path(temporary)):
            os.remove(native_io_path(temporary))
    return ensure_contained_codex_image_path(root, destination, must_exist=True)


def _require_existing_exact_bytes(
    destination: Path,
    payload: bytes,
    expected_sha256: str,
) -> None:
    """Reject a receipt-less staging artifact unless its bytes are exactly reproducible."""

    if not os.path.isfile(native_io_path(destination)):
        raise FileExistsError("normalization output exists but is not a regular file")
    if os.path.getsize(native_io_path(destination)) != len(payload):
        raise FileExistsError("normalization output conflicts with deterministic bytes")
    digest = hashlib.sha256()
    with open(native_io_path(destination), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise FileExistsError("normalization output conflicts with deterministic bytes")


def _normalization_receipt(
    plan: ImageGenNativeNormalizationPlan,
    plan_artifact: CodexImageArtifact,
    *,
    normalized_image: CodexImageArtifact | None,
    native_output_adoption_receipt: CodexImageArtifact | None,
    receipt_contract_id: str,
    producer: str,
    created_at: datetime | None,
    output_mode: Literal["L", "LA", "RGB", "RGBA", "P"] | None,
    output_has_alpha: bool | None,
    output_icc_profile_sha256: str | None,
) -> ImageGenNativeNormalizationReceipt:
    """Construct one exact receipt without persisting or overwriting history."""

    status: Literal["pass_through", "normalized", "review_required"] = (
        "review_required"
        if plan.operation == "review_required"
        else "pass_through"
        if plan.operation == "pass_through"
        else "normalized"
    )
    provenance = [
        plan_artifact,
        plan.source_image,
        *([normalized_image] if normalized_image is not None else []),
        *(
            [native_output_adoption_receipt]
            if native_output_adoption_receipt is not None
            else []
        ),
    ]
    return ImageGenNativeNormalizationReceipt(
        contract_id=receipt_contract_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=_normalization_receipt_input_sha256(
            plan_artifact=plan_artifact,
            source_image=plan.source_image,
            normalized_image=normalized_image,
            native_output_adoption_receipt=native_output_adoption_receipt,
        ),
        source_fingerprint=plan.source_image.sha256,
        producer=producer,
        provenance=provenance,
        created_at=created_at or datetime.now(UTC),
        plan=plan_artifact,
        source_image=plan.source_image,
        native_output_adoption_receipt=native_output_adoption_receipt,
        normalized_image=normalized_image,
        source_size=plan.source_size,
        target_size=plan.target_size,
        operation=plan.operation,
        crop_rectangle=plan.crop_rectangle,
        content_size=plan.content_size,
        padding=plan.padding,
        source_aspect_ratio=plan.source_aspect_ratio,
        target_aspect_ratio=plan.target_aspect_ratio,
        source_color_space=plan.source_color_space,
        source_mode=plan.source_mode,
        output_mode=output_mode,
        source_has_alpha=plan.source_has_alpha,
        output_has_alpha=output_has_alpha,
        source_icc_profile_sha256=plan.source_icc_profile_sha256,
        output_icc_profile_sha256=output_icc_profile_sha256,
        alpha_policy=plan.alpha_policy,
        algorithm_id=plan.algorithm_id,
        resampling=plan.resampling,
        status=status,
    )


def _normalization_receipt_input_sha256(
    *,
    plan_artifact: CodexImageArtifact,
    source_image: CodexImageArtifact,
    normalized_image: CodexImageArtifact | None,
    native_output_adoption_receipt: CodexImageArtifact | None,
) -> str:
    """Hash the exact plan, immutable source, and optional deterministic output closure."""

    return stable_json_digest(
        {
            "plan_sha256": plan_artifact.sha256,
            "source_sha256": source_image.sha256,
            "output_sha256": normalized_image.sha256 if normalized_image else None,
            "native_output_adoption_receipt_sha256": (
                native_output_adoption_receipt.sha256
                if native_output_adoption_receipt
                else None
            ),
        }
    )


def _validate_native_adoption_binding(
    job_root: Path,
    plan: ImageGenNativeNormalizationPlan,
    receipt: ImageGenNativeNormalizationReceipt,
    *,
    require_current_protected_inventory: bool,
) -> None:
    """Recursively validate native-original provenance whenever its canonical path is used."""

    marker = "/native_outputs/"
    is_native_original = marker in f"/{plan.source_image.path}" and plan.source_image.path.endswith(
        "/original.png"
    )
    adoption_artifact = receipt.native_output_adoption_receipt
    if is_native_original != (adoption_artifact is not None):
        raise ValueError(
            "native-original normalization requires exactly one adoption receipt binding"
        )
    if adoption_artifact is None:
        return
    from .native_output_adoption import (  # Local import avoids a service import cycle.
        validate_codex_image_native_output_adoption,
    )

    adoption = load_codex_image_model(
        job_root,
        adoption_artifact,
        CodexImageNativeOutputAdoptionReceipt,
    )
    validate_codex_image_native_output_adoption(
        job_root,
        adoption,
        require_current_protected_inventory=require_current_protected_inventory,
    )
    if (
        adoption.original_image != plan.source_image
        or adoption.job_id != plan.job_id
        or adoption.workflow_id != plan.workflow_id
        or adoption.dispatch_id != plan.dispatch_id
        or adoption.session_id != plan.session_id
    ):
        raise ValueError("normalization native adoption binding is inconsistent")


def _image_has_alpha(image: Image.Image) -> bool:
    """Detect explicit or palette transparency without interpreting pixel semantics."""

    return "A" in image.getbands() or (
        image.mode == "P" and image.info.get("transparency") is not None
    )


def _icc_profile_sha256(value: object) -> str | None:
    """Hash exact ICC bytes when Pillow exposes an embedded source profile."""

    if value is None:
        return None
    if not isinstance(value, bytes):
        raise ValueError("embedded ICC profile must be exact bytes")
    return hashlib.sha256(value).hexdigest()


__all__ = [
    "execute_native_image_normalization",
    "plan_native_image_normalization",
    "validate_native_normalization_plan",
    "validate_native_normalization_receipt",
]
