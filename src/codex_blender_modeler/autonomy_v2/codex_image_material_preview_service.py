"""Fixed Blender neutral-preview evidence for promoted ImageGen materials."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from ..blender_artifacts import (
    native_io_path,
    safe_artifact_name,
    sha256_file,
    stable_json_digest,
)
from ..blender_runner import run_blender
from ..codex_imagegen.artifacts import (
    artifact_for_codex_image,
    ensure_contained_codex_image_path,
    load_codex_image_model,
    validate_codex_image_artifact,
    write_immutable_codex_image_model,
)
from ..codex_imagegen.material_loop_models import (
    ImageGeneratedMaterialNeutralPreview,
)
from ..codex_imagegen.models import CodexImageArtifact
from ..config import get_settings
from .material_phase_service import validate_material_phase_receipt_v2
from .models import AQV2Artifact

_PRODUCER = (
    "codex_blender_modeler.autonomy_v2.codex_image_material_preview_service"
)
_PORTABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _aq_artifact(artifact: CodexImageArtifact) -> AQV2Artifact:
    """Project a media-aware companion artifact onto the exact AQ v2 binding."""

    return AQV2Artifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
    )


def _codex_artifact(
    artifact: AQV2Artifact,
    *,
    media_type: str,
) -> CodexImageArtifact:
    """Project one AQ v2 artifact into the companion media-aware evidence shape."""

    return CodexImageArtifact(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        path=artifact.path,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
        media_type=media_type,
    )


def _require_portable_id(value: str, *, label: str) -> str:
    """Reject path-like or otherwise non-portable caller identifiers before IO."""

    if not _PORTABLE_ID.fullmatch(value):
        raise ValueError(f"{label} is not a portable identifier")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    """Read one Blender-published JSON object through the native long-path form."""

    with open(native_io_path(path), encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("material swatch manifest must be a JSON object")
    return payload


def _publish_renderer_snapshot(source: Path, destination: Path) -> None:
    """Copy or exact-adopt the fixed renderer bytes beneath the run-owned evidence root."""

    if not source.is_file():
        raise FileNotFoundError(source)
    os.makedirs(native_io_path(destination.parent), exist_ok=True)
    if os.path.exists(native_io_path(destination)):
        if (
            os.path.getsize(native_io_path(destination))
            != os.path.getsize(native_io_path(source))
            or sha256_file(destination) != sha256_file(source)
        ):
            raise ValueError("neutral preview renderer snapshot differs from repository code")
        return
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    with open(native_io_path(source), "rb") as source_handle, open(
        native_io_path(temporary), "xb"
    ) as destination_handle:
        while chunk := source_handle.read(1024 * 1024):
            destination_handle.write(chunk)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())
    os.replace(native_io_path(temporary), native_io_path(destination))


def _validate_swatch_manifest(
    root: Path,
    manifest_path: Path,
    *,
    expected_image: Path,
    material_id: str,
    size: int,
) -> CodexImageArtifact:
    """Validate the fixed renderer manifest and return its exact PNG binding."""

    payload = _read_json(manifest_path)
    if (
        payload.get("schema_version") != "0.5.0"
        or payload.get("material_count") != 1
        or payload.get("resolution") != [size, size]
    ):
        raise ValueError("material swatch manifest has an unexpected fixed-render shape")
    records = payload.get("swatches")
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("material swatch manifest must contain exactly one swatch")
    record = records[0]
    if not isinstance(record, dict):
        raise ValueError("material swatch record must be a JSON object")
    if (
        record.get("material_id") != material_id
        or record.get("width") != size
        or record.get("height") != size
        or record.get("encoding") != "png-rgba8"
    ):
        raise ValueError("material swatch record differs from the fixed preview request")
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("material swatch record omits its image path")
    record_path = ensure_contained_codex_image_path(
        root,
        manifest_path.parent / Path(raw_path),
        must_exist=True,
    )
    expected = ensure_contained_codex_image_path(root, expected_image, must_exist=True)
    if os.path.normcase(os.path.abspath(record_path)) != os.path.normcase(
        os.path.abspath(expected)
    ):
        raise ValueError("material swatch manifest points outside the fixed output path")
    image = artifact_for_codex_image(
        root,
        expected,
        artifact_id=f"neutral-preview-image-{stable_json_digest([material_id, size])[:16]}",
        kind="material-neutral-preview-image",
        media_type="image/png",
    )
    if record.get("sha256") != image.sha256:
        raise ValueError("material swatch manifest image hash is stale")
    _validate_preview_png(expected, width=size, height=size)
    return image


def _validate_preview_png(path: Path, *, width: int, height: int) -> None:
    """Decode the fixed preview and require one exact RGBA PNG at the declared size."""

    try:
        with open(native_io_path(path), "rb") as handle, Image.open(handle) as image:
            if image.format != "PNG":
                raise ValueError("neutral material preview is not a PNG")
            image.load()
            if image.size != (width, height) or image.mode != "RGBA":
                raise ValueError("neutral material preview dimensions or mode are invalid")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("neutral material preview cannot be decoded as PNG") from exc


def validate_promoted_codex_image_material_preview(
    job_root: Path,
    preview_artifact: CodexImageArtifact,
    *,
    require_current: bool = True,
) -> ImageGeneratedMaterialNeutralPreview:
    """Recursively rehash and validate one fixed promoted-material preview receipt."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    validate_codex_image_artifact(root, preview_artifact)
    preview = load_codex_image_model(
        root,
        preview_artifact,
        ImageGeneratedMaterialNeutralPreview,
    )
    if preview.producer != _PRODUCER:
        raise ValueError("neutral material preview has an unexpected producer")
    for artifact in preview.provenance:
        validate_codex_image_artifact(root, artifact)
    receipt = validate_material_phase_receipt_v2(
        root,
        _aq_artifact(preview.material_phase_receipt),
        require_current=require_current,
    )
    expected_blend = _codex_artifact(
        receipt.authoring_blend_snapshot,
        media_type="application/x-blender",
    )
    if preview.authoring_blend != expected_blend:
        raise ValueError("neutral preview authoring blend differs from the promoted snapshot")
    evidence_path = validate_codex_image_artifact(root, preview_artifact)
    expected_script_path = evidence_path.parent / "renderer" / "render_material_swatches.py"
    script_path = validate_codex_image_artifact(root, preview.renderer_script)
    repository_script = (
        get_settings().repo_root
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "render_material_swatches.py"
    )
    if os.path.normcase(os.path.abspath(script_path)) != os.path.normcase(
        os.path.abspath(expected_script_path)
    ):
        raise ValueError("neutral preview renderer snapshot has an unexpected path")
    if require_current and sha256_file(script_path) != sha256_file(repository_script):
        raise ValueError("neutral preview renderer is not the current fixed repository script")
    manifest_path = validate_codex_image_artifact(root, preview.raw_swatch_manifest)
    image_path = validate_codex_image_artifact(root, preview.preview_image)
    bound_image = _validate_swatch_manifest(
        root,
        manifest_path,
        expected_image=image_path,
        material_id=preview.material_id,
        size=preview.width,
    )
    if preview.width != preview.height or bound_image != preview.preview_image:
        raise ValueError("neutral preview manifest and image binding changed")
    expected_input = stable_json_digest(
        {
            "material_phase_receipt": preview.material_phase_receipt.model_dump(mode="json"),
            "renderer_script": preview.renderer_script.model_dump(mode="json"),
            "material_id": preview.material_id,
            "size": preview.width,
        }
    )
    if preview.input_sha256 != expected_input:
        raise ValueError("neutral material preview input digest is inconsistent")
    return preview


def _load_existing_preview(
    root: Path,
    evidence_path: Path,
    *,
    material_phase_receipt: CodexImageArtifact,
    material_id: str,
    size: int,
) -> ImageGeneratedMaterialNeutralPreview:
    """Adopt one immutable preview only after rehashing its complete evidence chain."""

    evidence_artifact = artifact_for_codex_image(
        root,
        evidence_path,
        artifact_id=evidence_path.stem,
        kind="material-neutral-preview",
        media_type="application/json",
    )
    preview = validate_promoted_codex_image_material_preview(root, evidence_artifact)
    if (
        preview.material_phase_receipt != material_phase_receipt
        or preview.material_id != material_id
        or preview.width != size
        or preview.height != size
    ):
        raise ValueError("existing neutral preview targets another immutable request")
    return preview


def render_promoted_codex_image_material_preview(
    job_root: Path,
    *,
    material_phase_receipt: CodexImageArtifact,
    preview_id: str,
    material_id: str,
    size: int = 512,
    created_at: datetime | None = None,
) -> tuple[ImageGeneratedMaterialNeutralPreview, CodexImageArtifact]:
    """Render or crash-adopt one fixed neutral swatch from a promoted blend snapshot."""

    root = ensure_contained_codex_image_path(job_root, job_root, must_exist=True)
    preview_id = _require_portable_id(preview_id, label="preview_id")
    material_id = _require_portable_id(material_id, label="material_id")
    if size < 64 or size > 2048:
        raise ValueError("neutral preview size must be between 64 and 2048")
    receipt = validate_material_phase_receipt_v2(
        root,
        _aq_artifact(material_phase_receipt),
        require_current=True,
    )
    validate_codex_image_artifact(root, material_phase_receipt)
    authoring_blend = _codex_artifact(
        receipt.authoring_blend_snapshot,
        media_type="application/x-blender",
    )
    blend_path = validate_codex_image_artifact(root, authoring_blend)
    script_source = (
        get_settings().repo_root
        / "src"
        / "codex_blender_modeler"
        / "blender_scripts"
        / "render_material_swatches.py"
    )
    output_root = ensure_contained_codex_image_path(
        root,
        root
        / "production"
        / "autonomy_v2"
        / receipt.session_id
        / "codex_imagegen"
        / "material_loop"
        / "previews"
        / preview_id,
        must_exist=False,
    )
    evidence_path = output_root / "neutral_preview.json"
    manifest_path = output_root / "swatch_manifest.json"
    image_path = output_root / "renders" / safe_artifact_name(material_id) / "swatch.png"
    script_path = output_root / "renderer" / "render_material_swatches.py"
    if os.path.exists(native_io_path(evidence_path)):
        preview = _load_existing_preview(
            root,
            evidence_path,
            material_phase_receipt=material_phase_receipt,
            material_id=material_id,
            size=size,
        )
        return preview, artifact_for_codex_image(
            root,
            evidence_path,
            artifact_id=preview.contract_id,
            kind="material-neutral-preview",
            media_type="application/json",
        )
    _publish_renderer_snapshot(script_source, script_path)
    renderer_script = artifact_for_codex_image(
        root,
        script_path,
        artifact_id="fixed-material-swatch-renderer-v1",
        kind="fixed-material-swatch-renderer",
        media_type="text/x-python",
    )
    manifest_exists = os.path.exists(native_io_path(manifest_path))
    image_exists = os.path.exists(native_io_path(image_path))
    if manifest_exists != image_exists:
        raise ValueError("partial neutral preview output requires explicit review")
    if not manifest_exists:
        os.makedirs(native_io_path(output_root), exist_ok=True)
        run_blender(
            "render_material_swatches.py",
            [
                "--output-dir",
                str(output_root / "renders"),
                "--manifest",
                str(manifest_path),
                "--render-engine",
                "eevee",
                "--render-device",
                "auto",
                "--size",
                str(size),
                "--material-id",
                material_id,
            ],
            blend_file=blend_path,
            disable_autoexec=True,
        )
    preview_image = _validate_swatch_manifest(
        root,
        manifest_path,
        expected_image=image_path,
        material_id=material_id,
        size=size,
    )
    raw_manifest = artifact_for_codex_image(
        root,
        manifest_path,
        artifact_id=f"neutral-preview-manifest-{preview_id}",
        kind="material-neutral-preview-raw-manifest",
        media_type="application/json",
    )
    provenance = [
        material_phase_receipt,
        authoring_blend,
        renderer_script,
        raw_manifest,
        preview_image,
    ]
    input_sha256 = stable_json_digest(
        {
            "material_phase_receipt": material_phase_receipt.model_dump(mode="json"),
            "renderer_script": renderer_script.model_dump(mode="json"),
            "material_id": material_id,
            "size": size,
        }
    )
    preview = ImageGeneratedMaterialNeutralPreview(
        contract_id=preview_id,
        job_id=receipt.job_id,
        workflow_id=receipt.workflow_id,
        dispatch_id=receipt.dispatch_id,
        session_id=receipt.session_id,
        input_sha256=input_sha256,
        source_fingerprint=material_phase_receipt.sha256,
        producer=_PRODUCER,
        provenance=provenance,
        created_at=created_at or datetime.now(UTC),
        material_phase_receipt=material_phase_receipt,
        authoring_blend=authoring_blend,
        renderer_script=renderer_script,
        raw_swatch_manifest=raw_manifest,
        preview_image=preview_image,
        material_id=material_id,
        width=size,
        height=size,
        preview_image_path=preview_image.path,
        preview_image_sha256=preview_image.sha256,
        preview_image_byte_size=preview_image.byte_size,
    )
    evidence_artifact = write_immutable_codex_image_model(
        root,
        evidence_path,
        preview,
        kind="material-neutral-preview",
    )
    return preview, evidence_artifact


__all__ = [
    "render_promoted_codex_image_material_preview",
    "validate_promoted_codex_image_material_preview",
]
