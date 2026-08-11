"""Generate immutable advisory-only AdvancedMaterialHandoff 0.1.0 plans."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..blender_artifacts import native_io_path, sha256_file, stable_json_digest, write_json_atomic
from ..material_authoring.models import (
    AuthoredMaterialManifest,
    ExactArtifact,
    MaterialAuthoringReceipt,
    MaterialAuthoringRequest,
    RawPBRChannel,
)
from ..production.validation import ensure_contained_production_path
from .advanced_material_models import (
    AdvancedMaterialContract,
    AdvancedMaterialHandoffPlan,
    AdvancedMaterialHandoffReceipt,
    AdvancedMaterialHandoffRequest,
    DestinationMaterialTarget,
    RawChannelHandoffMapping,
)


def _utc_now() -> datetime:
    """Return one timezone-aware timestamp for immutable handoff evidence."""

    return datetime.now(UTC)


def _validate_artifact(root: Path, artifact: ExactArtifact) -> Path:
    """Reject missing, resized, or rehashed advanced-material source evidence."""

    path = ensure_contained_production_path(root, root / artifact.path, must_exist=True)
    if not os.path.isfile(native_io_path(path)):
        raise ValueError(f"advanced material artifact must be a regular file: {artifact.path}")
    if os.path.getsize(native_io_path(path)) != artifact.byte_size:
        raise ValueError(f"advanced material artifact size changed: {artifact.path}")
    if sha256_file(path) != artifact.sha256:
        raise ValueError(f"advanced material artifact hash changed: {artifact.path}")
    return path


def _artifact(
    root: Path,
    path: Path,
    *,
    artifact_id: str,
    kind: str,
) -> ExactArtifact:
    """Bind one contained non-empty JSON file to its exact immutable bytes."""

    safe = ensure_contained_production_path(root, path, must_exist=True)
    if not os.path.isfile(native_io_path(safe)):
        raise ValueError(f"advanced material output must be a regular file: {safe.name}")
    size = os.path.getsize(native_io_path(safe))
    if size <= 0:
        raise ValueError(f"advanced material output must be non-empty: {safe.name}")
    return ExactArtifact(
        artifact_id=artifact_id,
        kind=kind,
        path=safe.relative_to(root).as_posix(),
        sha256=sha256_file(safe),
        byte_size=size,
        media_type="application/json",
    )


def destination_channel_mapping(
    channel: RawPBRChannel,
    target: DestinationMaterialTarget,
) -> tuple[str, str, str | None]:
    """Return one conservative Unity-family property and explicit conversion rule."""

    if target == "unity_urp":
        mappings = {
            "base_color": ("_BaseMap", "assign sRGB texture; preserve alpha if declared", None),
            "roughness": ("_MetallicGlossMap", "invert roughness to smoothness", "A"),
            "metallic": ("_MetallicGlossMap", "pack metallic scalar", "R"),
            "normal": ("_BumpMap", "import as normal map; verify green-channel convention", None),
            "height": ("unsupported_by_default_urp_lit", "retain as advisory source", None),
            "occlusion": ("_OcclusionMap", "assign non-color occlusion", "G"),
            "opacity": ("_BaseMap", "map to base alpha and choose clip/blend manually", "A"),
            "emission": ("_EmissionMap", "assign sRGB emission and set intensity manually", None),
        }
    else:
        mappings = {
            "base_color": (
                "_BaseColorMap",
                "assign sRGB texture; preserve alpha if declared",
                None,
            ),
            "roughness": ("_MaskMap", "invert roughness to perceptual smoothness", "A"),
            "metallic": ("_MaskMap", "pack metallic scalar", "R"),
            "normal": ("_NormalMap", "import as normal map; verify green-channel convention", None),
            "height": ("_HeightMap", "assign only after HDRP displacement policy review", None),
            "occlusion": ("_MaskMap", "pack ambient occlusion", "G"),
            "opacity": ("_BaseColorMap", "map to alpha and select surface type manually", "A"),
            "emission": ("_EmissiveColorMap", "assign sRGB emission and intensity manually", None),
        }
    return mappings[channel]  # type: ignore[return-value]


def _preferred_shader(manifest: AuthoredMaterialManifest, target: DestinationMaterialTarget) -> str:
    """Choose only an advisory shader family based on declared portable intent."""

    if manifest.material_family == "crystal":
        return "Shader Graph required for transmission intent"
    if target == "unity_urp" and "clear coat" in manifest.master_intent.features:
        return "URP Complex Lit"
    if target == "unity_urp":
        return "URP Lit"
    return "HDRP Lit"


def _contract(
    manifest: AuthoredMaterialManifest,
    authoring_request: MaterialAuthoringRequest,
    target: DestinationMaterialTarget,
) -> AdvancedMaterialContract:
    """Convert exact authored channels into one conservative destination contract."""

    mappings: list[RawChannelHandoffMapping] = []
    for channel in manifest.channels:
        property_name, conversion, packed = destination_channel_mapping(channel.channel, target)
        mappings.append(
            RawChannelHandoffMapping(
                channel=channel.channel,
                source_path=channel.artifact.path,
                source_sha256=channel.artifact.sha256,
                source_color_space=channel.color_space,
                destination_property=property_name,
                conversion=conversion,
                destination_color_space=channel.color_space,
                packed_destination_channel=packed,  # type: ignore[arg-type]
            )
        )
    family = manifest.material_family
    crystal = authoring_request.crystal
    emissive = authoring_request.emissive_pattern
    transmission = crystal.transmission if crystal is not None else 0.0
    has_opacity = any(item.channel == "opacity" for item in manifest.channels)
    unsupported = list(manifest.master_intent.known_losses)
    required_features: list[str] = []
    policy = "direct_portable_mapping"
    if any(item.packed_destination_channel is not None for item in mappings):
        policy = "packed_channel_conversion_required"
    if family == "crystal":
        policy = "custom_shader_reconstruction_required"
        required_features = ["transmission", "Fresnel", "IOR", "absorption or tint approximation"]
        unsupported.extend(
            [
                "Unity shader graph is not generated by this plan",
                "portable textures cannot prove transmission or thickness parity",
            ]
        )
    limitations = list(
        dict.fromkeys(
            [
                *manifest.limitations,
                *unsupported,
                "double-sided intent is not declared by MaterialAuthoring 0.1.0",
            ]
        )
    )
    return AdvancedMaterialContract(
        material_id=manifest.material_id,
        material_family=family,
        raw_pbr_channel_mapping=mappings,
        authoring_shader_features=manifest.master_intent.features,
        portable_approximation=manifest.master_intent.portable_approximation,
        required_destination_features=required_features,
        unsupported_features=list(dict.fromkeys(unsupported)),
        preferred_shader_family=_preferred_shader(manifest, target),
        approximation_policy=policy,  # type: ignore[arg-type]
        source_hashes=[
            manifest.request.sha256,
            *[item.artifact.sha256 for item in manifest.channels],
        ],
        texture_color_spaces={item.channel: item.color_space for item in manifest.channels},
        normal_convention=(
            "opengl_y_plus"
            if any(item.channel == "normal" for item in manifest.channels)
            else "not_present"
        ),
        transparency_mode=(
            "approximate_transmission"
            if family == "crystal"
            else ("unspecified" if has_opacity else "opaque")
        ),
        double_sided_intent=None,
        emission=any(item.channel == "emission" for item in manifest.channels),
        emission_color=(
            crystal.emission_color
            if crystal is not None
            else emissive.emission_color
            if emissive is not None
            else None
        ),
        emission_strength=(
            crystal.emission_strength
            if crystal is not None
            else emissive.emission_strength
            if emissive is not None
            else None
        ),
        clear_coat="clear coat" in manifest.master_intent.features,
        transmission=transmission,
        ior=crystal.ior if crystal is not None else None,
        thickness_m=crystal.thickness_approximation_m if crystal is not None else None,
        absorption_distance_m=(crystal.absorption_distance_m if crystal is not None else None),
        confidence=0.45 if family == "crystal" else 0.75,
        limitations=limitations,
    )


def _operations(
    contract: AdvancedMaterialContract,
    target: DestinationMaterialTarget,
) -> list[str]:
    """Describe user-reviewable destination operations without executing them."""

    operations = [
        f"detect the actual Unity version and render pipeline before applying {target}",
        f"create or select {contract.preferred_shader_family} only after user approval",
    ]
    operations.extend(
        f"map {item.channel} to {item.destination_property}: {item.conversion}"
        for item in contract.raw_pbr_channel_mapping
    )
    if target == "unity_hdrp" and any(
        item.destination_property == "_MaskMap" for item in contract.raw_pbr_channel_mapping
    ):
        operations.append(
            "choose the HDRP MaskMap B detail-mask value explicitly; no source value is invented"
        )
    operations.append("validate neutral lighting, transparency, emission, and scale in destination")
    return operations


def generate_advanced_material_handoff_plan(
    job_root: Path,
    request: AdvancedMaterialHandoffRequest,
) -> AdvancedMaterialHandoffReceipt:
    """Publish an advisory JSON plan without copying assets or touching a destination project."""

    root = ensure_contained_production_path(job_root, job_root, must_exist=True)
    manifest_path = _validate_artifact(root, request.material_authoring_manifest)
    with open(native_io_path(manifest_path), "rb") as handle:
        manifest = AuthoredMaterialManifest.model_validate_json(handle.read())
    receipt_path = _validate_artifact(root, request.material_authoring_receipt)
    with open(native_io_path(receipt_path), "rb") as handle:
        authoring_receipt = MaterialAuthoringReceipt.model_validate_json(handle.read())
    if authoring_receipt.manifest != request.material_authoring_manifest:
        raise ValueError("material authoring receipt does not bind the requested manifest")
    if authoring_receipt.request != manifest.request:
        raise ValueError("material authoring receipt does not bind the manifest request")
    if authoring_receipt.run_id != manifest.run_id:
        raise ValueError("material authoring receipt and manifest run IDs differ")
    expected_outputs = [item.artifact for item in manifest.channels]
    if authoring_receipt.outputs != expected_outputs:
        raise ValueError("material authoring receipt outputs differ from the manifest channels")
    expected_bundle = stable_json_digest(
        [
            item.model_dump(mode="json")
            for item in sorted(expected_outputs, key=lambda artifact: artifact.path)
        ]
    )
    if authoring_receipt.output_bundle_sha256 != expected_bundle:
        raise ValueError("material authoring receipt output bundle digest is inconsistent")
    expected_provenance = stable_json_digest(
        {
            "strategy": manifest.strategy,
            "source_v05_contracts": [item.sha256 for item in manifest.source_v05_contracts],
            "scale_context": manifest.scale_context.artifact.sha256,
            "channels": [item.model_dump(mode="json") for item in manifest.channels],
        }
    )
    if manifest.source_to_output_provenance_sha256 != expected_provenance:
        raise ValueError("material authoring source-to-output provenance digest is inconsistent")
    authoring_request_path = _validate_artifact(root, manifest.request)
    with open(native_io_path(authoring_request_path), "rb") as handle:
        authoring_request = MaterialAuthoringRequest.model_validate_json(handle.read())
    if authoring_request.job_id != manifest.job_id:
        raise ValueError("material authoring request and manifest job IDs differ")
    if authoring_request.material_id != manifest.material_id:
        raise ValueError("material authoring request and manifest material IDs differ")
    for artifact in manifest.source_v05_contracts:
        _validate_artifact(root, artifact)
    _validate_artifact(root, manifest.scale_context.artifact)
    for channel in manifest.channels:
        _validate_artifact(root, channel.artifact)
        _validate_artifact(root, channel.uv_identity.evidence)
    output_root = ensure_contained_production_path(
        root,
        root / request.output_root,
        must_exist=False,
    )
    if os.path.exists(native_io_path(output_root)):
        raise FileExistsError(output_root)
    stage_root = ensure_contained_production_path(
        root,
        output_root.parent / f".{request.plan_id}.staging-{uuid4().hex}",
        must_exist=False,
    )
    os.makedirs(native_io_path(stage_root), exist_ok=False)
    request_path = stage_root / "advanced_material_handoff_request.json"
    write_json_atomic(request_path, request.model_dump(mode="json"))
    request_artifact = _artifact(
        root,
        request_path,
        artifact_id=request.request_id,
        kind="advanced-material-handoff-request",
    ).model_copy(
        update={
            "path": (output_root / "advanced_material_handoff_request.json")
            .relative_to(root)
            .as_posix()
        }
    )
    contract = _contract(manifest, authoring_request, request.destination_target)
    plan = AdvancedMaterialHandoffPlan(
        plan_id=request.plan_id,
        job_id=request.job_id,
        destination_target=request.destination_target,
        destination_hint=request.destination_hint,
        request=request_artifact,
        material_authoring_manifest=request.material_authoring_manifest,
        material_authoring_receipt=request.material_authoring_receipt,
        contract=contract,
        operations=_operations(contract, request.destination_target),
        known_limitations=list(
            dict.fromkeys(
                [
                    *contract.limitations,
                    "destination engine/version/render pipeline has not been detected",
                    "no Unity project files, material assets, or Shader Graph assets were written",
                    "runtime parity remains unverified",
                ]
            )
        ),
        created_at=_utc_now(),
    )
    filename = (
        "unity_urp_material_plan.json"
        if request.destination_target == "unity_urp"
        else "unity_hdrp_material_plan.json"
    )
    plan_path = stage_root / filename
    write_json_atomic(plan_path, plan.model_dump(mode="json"))
    staged_plan = _artifact(
        root,
        plan_path,
        artifact_id=request.plan_id,
        kind="advanced-material-handoff-plan",
    )
    plan_artifact = staged_plan.model_copy(
        update={"path": (output_root / filename).relative_to(root).as_posix()}
    )
    receipt = AdvancedMaterialHandoffReceipt(
        receipt_id=f"receipt-{request.plan_id}",
        plan_id=request.plan_id,
        job_id=request.job_id,
        request=request_artifact,
        plan=plan_artifact,
        source_manifest_sha256=request.material_authoring_manifest.sha256,
        plan_sha256=plan_artifact.sha256,
        created_at=_utc_now(),
    )
    write_json_atomic(
        stage_root / "advanced_material_handoff_receipt.json",
        receipt.model_dump(mode="json"),
    )
    os.makedirs(native_io_path(output_root.parent), exist_ok=True)
    os.replace(native_io_path(stage_root), native_io_path(output_root))
    _validate_artifact(root, receipt.request)
    _validate_artifact(root, receipt.plan)
    with open(
        native_io_path(output_root / "advanced_material_handoff_receipt.json"),
        "rb",
    ) as handle:
        published_receipt = AdvancedMaterialHandoffReceipt.model_validate_json(handle.read())
    if published_receipt != receipt:
        raise RuntimeError("published advanced material receipt differs from staged evidence")
    return receipt
