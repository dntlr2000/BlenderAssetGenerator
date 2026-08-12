"""Deterministic staging adapter for the normalized MaterialAuthoring companion."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image

from ..blender_artifacts import native_io_path, stable_json_digest
from ..codex_imagegen.artifacts import load_codex_image_model
from ..codex_imagegen.material_loop_models import (
    ImageGenNativeNormalizationPlan,
    ImageGenNativeNormalizationReceipt,
)
from ..codex_imagegen.material_loop_normalization import (
    validate_native_normalization_receipt,
)
from ..codex_imagegen.models import CodexImageArtifact
from ..production.validation import ensure_contained_production_path
from .codex_image_adapter import (
    _load_exact_model,
    _load_source_rgba,
    _material_images,
    _quality_metrics,
    _staged_artifact,
    _text_receipt,
    _validate_artifact,
    _validate_inputs,
    _write_channels,
    _write_model,
)
from .codex_image_models import (
    CodexImageMaterialAuthoringRequestV021,
    CodexImageMaterialSourceV021,
    ExactTextCompositionV021,
    LocalImageDerivationPolicyV021,
)
from .codex_image_normalized_models import (
    CodexImageNormalizedAuthoredMaterialManifestV010,
    CodexImageNormalizedMaterialAuthoringReceiptV010,
    CodexImageNormalizedMaterialAuthoringRequestV010,
    _manifest_input_sha256,
    _receipt_input_sha256,
    _request_input_sha256,
)
from .models import ExactArtifact, UVIdentity

PRODUCER = "codex_image_normalized_material_authoring_service"

__all__ = [
    "author_codex_image_normalized_material_candidate",
    "build_codex_image_normalized_material_request",
    "validate_codex_image_normalized_material_candidate",
]


@dataclass(frozen=True)
class _NormalizedDerivationRecipe:
    """Expose only pure derivation fields, without assigning a legacy schema version."""

    run_id: str
    material_id: str
    strategy: str
    material_family: str
    source: CodexImageMaterialSourceV021
    uv_identity: UVIdentity
    derivation: LocalImageDerivationPolicyV021
    exact_text: ExactTextCompositionV021 | None
    base_roughness: float


def _utc_now() -> datetime:
    """Return one timezone-aware timestamp for immutable companion evidence."""

    return datetime.now(UTC)


def _as_exact_artifact(artifact: CodexImageArtifact) -> ExactArtifact:
    """Convert identical Codex artifact fields into the material evidence type."""

    return ExactArtifact.model_validate(artifact.model_dump(mode="python"))


def _as_codex_artifact(artifact: ExactArtifact) -> CodexImageArtifact:
    """Convert identical material artifact fields into the Codex evidence type."""

    return CodexImageArtifact.model_validate(artifact.model_dump(mode="python"))


def _same_artifact(
    left: CodexImageArtifact | ExactArtifact,
    right: CodexImageArtifact | ExactArtifact,
) -> bool:
    """Compare exact artifact metadata across the two structurally identical models."""

    return left.model_dump(mode="json") == right.model_dump(mode="json")


def _load_normalization_chain(
    root: Path,
    *,
    base_request: CodexImageMaterialAuthoringRequestV021,
    normalization_plan_artifact: CodexImageArtifact,
    normalization_receipt_artifact: CodexImageArtifact,
    effective_source: CodexImageMaterialSourceV021,
) -> tuple[ImageGenNativeNormalizationPlan, ImageGenNativeNormalizationReceipt]:
    """Replay normalization and bind its original and derivative to the base request."""

    plan = load_codex_image_model(
        root,
        normalization_plan_artifact,
        ImageGenNativeNormalizationPlan,
    )
    receipt = load_codex_image_model(
        root,
        normalization_receipt_artifact,
        ImageGenNativeNormalizationReceipt,
    )
    validate_native_normalization_receipt(root, plan, receipt)
    selected_source = _as_codex_artifact(base_request.source.artifact)
    if plan.source_image != selected_source or receipt.source_image != selected_source:
        raise ValueError("normalization source differs from the exact 0.2.1 selected source")
    if receipt.plan != normalization_plan_artifact:
        raise ValueError("normalization receipt does not bind the declared exact plan")
    if receipt.status == "review_required" or receipt.normalized_image is None:
        raise PermissionError("review-required normalization cannot enter material authoring")
    if not _same_artifact(receipt.normalized_image, effective_source.artifact):
        raise ValueError("effective material source differs from normalized derivative bytes")
    if (
        plan.source_size.width,
        plan.source_size.height,
        plan.source_color_space,
    ) != (
        base_request.source.width,
        base_request.source.height,
        base_request.source.color_space,
    ):
        raise ValueError("normalization plan metadata differs from the selected source")
    if (effective_source.width, effective_source.height) != (
        plan.target_size.width,
        plan.target_size.height,
    ):
        raise ValueError("effective material dimensions differ from normalization target")
    preserved_fields = ("direct_role", "color_space", "license_id", "rights_status")
    if any(
        getattr(effective_source, field) != getattr(base_request.source, field)
        for field in preserved_fields
    ):
        raise ValueError("effective material source changed selected-source semantics")
    return plan, receipt


def _validate_normalized_dependencies(
    root: Path,
    request: CodexImageNormalizedMaterialAuthoringRequestV010,
    *,
    source_v05_contract_overrides: list[ExactArtifact] | None = None,
) -> tuple[Path, set[str]]:
    """Rehash selected evidence, using only byte-identical immutable V0.5 snapshots."""

    loaded_base = _load_exact_model(
        root,
        _as_exact_artifact(request.base_request_artifact),
        CodexImageMaterialAuthoringRequestV021,
    )
    if not isinstance(loaded_base, CodexImageMaterialAuthoringRequestV021):
        raise TypeError("base material request loader returned an unexpected contract")
    if loaded_base != request.base_request:
        raise ValueError("embedded 0.2.1 request differs from its exact artifact")
    validation_request = loaded_base
    if source_v05_contract_overrides is not None:
        if len(source_v05_contract_overrides) != len(loaded_base.source_v05_contracts):
            raise ValueError("V0.5 snapshot override count differs from the base request")
        for original, snapshot in zip(
            loaded_base.source_v05_contracts,
            source_v05_contract_overrides,
            strict=True,
        ):
            expected_kind = (
                "v05-material-plan-baseline-snapshot"
                if original.kind == "v05-material-plan"
                else original.kind
            )
            if snapshot.kind != expected_kind:
                raise ValueError("V0.5 snapshot override has the wrong contract role")
            if original.kind == "v05-material-plan" and not (
                snapshot.path.startswith(
                    "material_authoring/codex_imagegen/v05_bridge/runs/"
                )
                and snapshot.path.endswith("/source/baseline_material_plan.json")
            ):
                raise ValueError("V0.5 MaterialPlan snapshot is not bridge-run-owned")
            if (
                original.sha256,
                original.byte_size,
                original.media_type,
            ) != (
                snapshot.sha256,
                snapshot.byte_size,
                snapshot.media_type,
            ):
                raise ValueError("V0.5 snapshot override differs from exact source bytes")
        validation_request = loaded_base.model_copy(
            update={"source_v05_contracts": source_v05_contract_overrides}
        )
    _, authorized_direct_roles = _validate_inputs(root, validation_request)
    plan, _ = _load_normalization_chain(
        root,
        base_request=loaded_base,
        normalization_plan_artifact=request.normalization_plan,
        normalization_receipt_artifact=request.normalization_receipt,
        effective_source=request.effective_source,
    )
    identity = (
        "job_id",
        "workflow_id",
        "dispatch_id",
        "session_id",
        "profile_id",
        "provider_id",
    )
    if any(getattr(request, field) != getattr(plan, field) for field in identity):
        raise ValueError("normalized material request identity differs from normalization")
    if (
        loaded_base.job_id != request.job_id
        or loaded_base.workflow_id != request.workflow_id
    ):
        raise ValueError("base material request identity differs from normalized companion")
    source_path = _validate_artifact(
        root,
        request.effective_source.artifact,
    )
    with Image.open(native_io_path(source_path)) as opened:
        opened.load()
        if opened.size != (
            request.effective_source.width,
            request.effective_source.height,
        ):
            raise ValueError("effective normalized source dimensions changed")
    return source_path, authorized_direct_roles


def build_codex_image_normalized_material_request(
    job_root: Path,
    *,
    contract_id: str,
    run_id: str,
    base_request: CodexImageMaterialAuthoringRequestV021,
    base_request_artifact: CodexImageArtifact,
    normalization_plan: CodexImageArtifact,
    normalization_receipt: CodexImageArtifact,
    effective_source: CodexImageMaterialSourceV021,
    created_at: datetime | None = None,
) -> CodexImageNormalizedMaterialAuthoringRequestV010:
    """Build a hash-closed companion only after replaying every exact dependency."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    loaded_base = _load_exact_model(
        root,
        _as_exact_artifact(base_request_artifact),
        CodexImageMaterialAuthoringRequestV021,
    )
    if loaded_base != base_request:
        raise ValueError("base 0.2.1 request object differs from its exact artifact")
    plan, _ = _load_normalization_chain(
        root,
        base_request=base_request,
        normalization_plan_artifact=normalization_plan,
        normalization_receipt_artifact=normalization_receipt,
        effective_source=effective_source,
    )
    output_root = f"material_authoring/codex_imagegen/normalized_runs/{run_id}"
    provenance = [
        base_request_artifact,
        _as_codex_artifact(base_request.source.artifact),
        normalization_plan,
        normalization_receipt,
        _as_codex_artifact(effective_source.artifact),
    ]
    return CodexImageNormalizedMaterialAuthoringRequestV010(
        contract_id=contract_id,
        job_id=plan.job_id,
        workflow_id=plan.workflow_id,
        dispatch_id=plan.dispatch_id,
        session_id=plan.session_id,
        input_sha256=_request_input_sha256(
            base_request=base_request,
            base_request_artifact=base_request_artifact,
            normalization_plan=normalization_plan,
            normalization_receipt=normalization_receipt,
            effective_source=effective_source,
            run_id=run_id,
            output_root=output_root,
        ),
        source_fingerprint=base_request.source.artifact.sha256,
        producer=PRODUCER,
        provenance=provenance,
        created_at=created_at or _utc_now(),
        base_request=base_request,
        base_request_artifact=base_request_artifact,
        normalization_plan=normalization_plan,
        normalization_receipt=normalization_receipt,
        effective_source=effective_source,
        run_id=run_id,
        output_root=output_root,
    )


def _recipe(
    request: CodexImageNormalizedMaterialAuthoringRequestV010,
) -> _NormalizedDerivationRecipe:
    """Return a non-persisted, versionless derivation view for legacy-pure helpers."""

    base = request.base_request
    return _NormalizedDerivationRecipe(
        run_id=request.run_id,
        material_id=base.material_id,
        strategy=base.strategy,
        material_family=base.material_family,
        source=request.effective_source,
        uv_identity=base.uv_identity,
        derivation=base.derivation,
        exact_text=base.exact_text,
        base_roughness=base.base_roughness,
    )


def _validate_published_receipt(
    root: Path,
    receipt: CodexImageNormalizedMaterialAuthoringReceiptV010,
) -> None:
    """Rehash every normalized staging artifact before reporting publication."""

    for artifact in (
        _as_exact_artifact(receipt.request),
        _as_exact_artifact(receipt.manifest),
        *receipt.outputs,
    ):
        _validate_artifact(root, artifact)


def author_codex_image_normalized_material_candidate(
    job_root: Path,
    request: CodexImageNormalizedMaterialAuthoringRequestV010,
) -> CodexImageNormalizedMaterialAuthoringReceiptV010:
    """Derive and atomically publish one explicitly normalized staging candidate."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    source_path, authorized_direct_roles = _validate_normalized_dependencies(root, request)
    final_root = ensure_contained_production_path(
        root,
        root / request.output_root,
        must_exist=False,
    )
    if os.path.exists(native_io_path(final_root)):
        raise FileExistsError(
            f"normalized image material run already exists: {request.output_root}"
        )
    parent = ensure_contained_production_path(root, final_root.parent, must_exist=False)
    os.makedirs(native_io_path(parent), exist_ok=True)
    stage_root = parent / f".{request.run_id}.staging-{uuid4().hex}"
    ensure_contained_production_path(root, stage_root, must_exist=False)
    os.makedirs(native_io_path(stage_root), exist_ok=False)
    try:
        request_path = stage_root / "request.json"
        _write_model(request_path, request)
        request_artifact = _as_codex_artifact(
            _staged_artifact(
                root,
                request_path,
                final_root / "request.json",
                artifact_id=f"{request.run_id}-normalized-request",
                kind="codex-image-normalized-material-authoring-request",
                media_type="application/json",
            )
        )
        recipe = _recipe(request)
        source = _load_source_rgba(source_path, recipe.derivation.output_resolution)
        quality = _quality_metrics(source, recipe)
        images, text_state, provenance_records = _material_images(
            root,
            recipe,
            source_path,
            authorized_direct_roles,
        )
        channels = _write_channels(
            root,
            stage_root,
            final_root,
            recipe,
            images,
            provenance_records,
        )
        text_receipt = _text_receipt(text_state, recipe, channels)
        limitations = [*quality.reasons]
        if text_receipt is not None and not text_receipt.rendered:
            limitations.append(
                f"text evidence is {text_receipt.evidence}; no glyphs were invented or rasterized"
            )
        limitations.extend(
            [
                "effective raster is a deterministic derivative of the unchanged selected source",
                "candidate remains staging-only until authorized controller promotion",
                "actual Codex built-in ImageGen execution is not verified by this local adapter",
                "Blender compilation and destination runtime parity were not run",
            ]
        )
        status = (
            "candidate_ready"
            if quality.outcome == "passed"
            and (text_receipt is None or text_receipt.rendered)
            else "review_required"
        )
        manifest_provenance = [
            request_artifact,
            request.base_request_artifact,
            request.normalization_plan,
            request.normalization_receipt,
            _as_codex_artifact(request.base_request.source.artifact),
            _as_codex_artifact(request.effective_source.artifact),
            *[_as_codex_artifact(channel.output) for channel in channels],
        ]
        manifest = CodexImageNormalizedAuthoredMaterialManifestV010(
            contract_id=f"{request.run_id}-normalized-manifest-contract",
            manifest_id=f"{request.run_id}-normalized-manifest",
            job_id=request.job_id,
            workflow_id=request.workflow_id,
            dispatch_id=request.dispatch_id,
            session_id=request.session_id,
            input_sha256=_manifest_input_sha256(
                request=request_artifact,
                base_request_artifact=request.base_request_artifact,
                normalization_plan=request.normalization_plan,
                normalization_receipt=request.normalization_receipt,
                selected_source=request.base_request.source,
                effective_source=request.effective_source,
                channels=channels,
            ),
            source_fingerprint=request.source_fingerprint,
            producer=PRODUCER,
            provenance=manifest_provenance,
            created_at=_utc_now(),
            run_id=request.run_id,
            material_id=request.base_request.material_id,
            strategy=request.base_request.strategy,
            material_family=request.base_request.material_family,
            request=request_artifact,
            base_request_artifact=request.base_request_artifact,
            normalization_plan=request.normalization_plan,
            normalization_receipt=request.normalization_receipt,
            selected_source=request.base_request.source,
            effective_source=request.effective_source,
            derivation_policy_sha256=request.base_request.derivation.exact_sha256(),
            channels=channels,
            exact_text=text_receipt,
            quality=quality,
            status=status,
            limitations=limitations,
        )
        manifest_path = stage_root / "manifest.json"
        _write_model(manifest_path, manifest)
        manifest_artifact = _as_codex_artifact(
            _staged_artifact(
                root,
                manifest_path,
                final_root / "manifest.json",
                artifact_id=f"{request.run_id}-normalized-manifest",
                kind="codex-image-normalized-authored-material-manifest",
                media_type="application/json",
            )
        )
        outputs = [channel.output for channel in channels]
        output_bundle_sha256 = stable_json_digest(
            [
                artifact.model_dump(mode="json")
                for artifact in sorted(outputs, key=lambda item: item.path)
            ]
        )
        receipt = CodexImageNormalizedMaterialAuthoringReceiptV010(
            contract_id=f"{request.run_id}-normalized-receipt-contract",
            receipt_id=f"{request.run_id}-normalized-receipt",
            job_id=request.job_id,
            workflow_id=request.workflow_id,
            dispatch_id=request.dispatch_id,
            session_id=request.session_id,
            input_sha256=_receipt_input_sha256(
                request=request_artifact,
                manifest=manifest_artifact,
                outputs=outputs,
            ),
            source_fingerprint=request.source_fingerprint,
            producer=PRODUCER,
            provenance=[
                request_artifact,
                manifest_artifact,
                *[_as_codex_artifact(item) for item in outputs],
            ],
            created_at=_utc_now(),
            run_id=request.run_id,
            request=request_artifact,
            manifest=manifest_artifact,
            outputs=outputs,
            output_bundle_sha256=output_bundle_sha256,
        )
        _write_model(stage_root / "receipt.json", receipt)
        os.replace(native_io_path(stage_root), native_io_path(final_root))
        _validate_published_receipt(root, receipt)
        return receipt
    except Exception:
        if os.path.isdir(native_io_path(stage_root)):
            shutil.rmtree(native_io_path(stage_root))
        raise


def validate_codex_image_normalized_material_candidate(
    job_root: Path,
    receipt: CodexImageNormalizedMaterialAuthoringReceiptV010,
    *,
    source_v05_contract_overrides: list[ExactArtifact] | None = None,
) -> CodexImageNormalizedAuthoredMaterialManifestV010:
    """Replay normalized evidence with optional byte-identical immutable V0.5 snapshots."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    _validate_published_receipt(root, receipt)
    request = _load_exact_model(
        root,
        _as_exact_artifact(receipt.request),
        CodexImageNormalizedMaterialAuthoringRequestV010,
    )
    manifest = _load_exact_model(
        root,
        _as_exact_artifact(receipt.manifest),
        CodexImageNormalizedAuthoredMaterialManifestV010,
    )
    if not isinstance(request, CodexImageNormalizedMaterialAuthoringRequestV010):
        raise TypeError("normalized request loader returned an unexpected contract")
    if not isinstance(manifest, CodexImageNormalizedAuthoredMaterialManifestV010):
        raise TypeError("normalized manifest loader returned an unexpected contract")
    receipt_path = ensure_contained_production_path(
        root,
        root / request.output_root / "receipt.json",
        must_exist=True,
    )
    with open(native_io_path(receipt_path), "rb") as handle:
        published_receipt = (
            CodexImageNormalizedMaterialAuthoringReceiptV010.model_validate_json(
                handle.read()
            )
        )
    if published_receipt != receipt:
        raise ValueError("provided normalized receipt differs from published staging bytes")
    _validate_normalized_dependencies(
        root,
        request,
        source_v05_contract_overrides=source_v05_contract_overrides,
    )
    if manifest.request != receipt.request:
        raise ValueError("normalized manifest request differs from receipt")
    if manifest.base_request_artifact != request.base_request_artifact:
        raise ValueError("normalized manifest base request differs from companion request")
    if (
        manifest.normalization_plan != request.normalization_plan
        or manifest.normalization_receipt != request.normalization_receipt
        or manifest.selected_source != request.base_request.source
        or manifest.effective_source != request.effective_source
    ):
        raise ValueError("normalized manifest source chain differs from companion request")
    if (
        manifest.material_id != request.base_request.material_id
        or manifest.strategy != request.base_request.strategy
        or manifest.material_family != request.base_request.material_family
        or manifest.derivation_policy_sha256
        != request.base_request.derivation.exact_sha256()
    ):
        raise ValueError("normalized manifest derivation recipe differs from base request")
    identities = ("job_id", "workflow_id", "dispatch_id", "session_id", "run_id")
    if any(
        getattr(request, field) != getattr(manifest, field)
        or getattr(request, field) != getattr(receipt, field)
        for field in identities
    ):
        raise ValueError("normalized material identity differs across published evidence")
    manifest_outputs = sorted(
        (channel.output for channel in manifest.channels),
        key=lambda item: item.path,
    )
    if manifest_outputs != sorted(receipt.outputs, key=lambda item: item.path):
        raise ValueError("normalized manifest channels differ from receipt outputs")
    for channel in manifest.channels:
        if request.effective_source.artifact.sha256 not in channel.source_sha256:
            raise ValueError("normalized channel is not bound to effective derivative bytes")
        path = _validate_artifact(root, channel.output)
        with Image.open(native_io_path(path)) as opened:
            if opened.size != (channel.width, channel.height):
                raise ValueError(f"published {channel.channel} dimensions changed")
            opened.verify()
    return manifest
