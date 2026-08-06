"""Engine-neutral V0.7 portable package construction and clean-import validation."""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from ..baking.io import load_bake_manifest
from ..blender_artifacts import safe_artifact_name, write_json_atomic
from ..blender_runner import run_blender
from ..build_provenance import collect_build_provenance
from ..config import load_feature_config
from ..material_manifest import load_material_manifest
from ..materials.io import load_material_plan, load_shader_recipe, resolve_job_path
from ..optimization.io import (
    job_relative,
    latest_complete_run_id,
    load_model,
    new_run_id,
    resolve_inside,
    run_directory,
    utc_now,
    validate_filesystem_id,
    write_model,
)
from ..optimization.models import (
    AssetProfile,
    Bounds3D,
    CollisionManifest,
    HashedArtifact,
    LODManifest,
    OptimizationApproval,
    OptimizationPlan,
    OptimizationReview,
    PortableChannelOutput,
    PortableMaterialContractArtifact,
    SourceProvenance,
    StaticAssetCostReport,
    UVManifest,
)
from ..optimization.preflight import load_asset_profile, profile_path
from ..optimization.provenance import require_unchanged_source
from ..workspace import job_dir, native_io_path, sha256_file
from .material_conversion import (
    MaterialConversionSelection,
    load_portable_material_conversion,
)
from .models import (
    BoundsComparison,
    ExportPackageManifest,
    PackageFile,
    PackedTexture,
    RoundTripCheck,
    RoundTripValidation,
    TextureChannelMapping,
    TexturePackManifest,
)
from .texture_packing import build_portable_texture_package

MEDIA_TYPES = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".bin": "application/octet-stream",
    ".fbx": "application/octet-stream",
    ".obj": "text/plain",
    ".mtl": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
}
COLOR_SPACES = {
    "base_color": "sRGB",
    "emission": "sRGB",
    "roughness": "Non-Color",
    "metallic": "Non-Color",
    "normal": "Non-Color",
    "height": "Non-Color",
    "occlusion": "Non-Color",
    "opacity": "Non-Color",
    "orm": "Non-Color",
}

ABSOLUTE_PATH_AUDIT_SUFFIXES = {
    ".fbx",
    ".glb",
    ".gltf",
    ".json",
    ".mtl",
    ".obj",
}


def _copyfile_long_path_safe(source: Path, target: Path) -> None:
    """Copy one package file through native extended paths on Windows."""

    shutil.copyfile(native_io_path(source), native_io_path(target))


WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9_])(?:"
    r"[a-z]:[\\/]+(?:[a-z0-9._ -]+[\\/]+)*[a-z0-9._ -]+"
    r"|\\{2,}[a-z0-9._ -]+[\\/]+[a-z0-9._ -]+"
    r"(?:[\\/]+[a-z0-9._ -]+)*"
    r")"
)
POSIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])/(?:home|Users|Volumes|private|tmp|var|opt|mnt|root|data|workspace|srv)/"
    r"[A-Za-z0-9._ /-]+"
)
BINARY_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9_])(?:"
    r"[a-z]:[\\/]+|\\{2,}[a-z0-9._ -]+[\\/]+"
    r")(?:[a-z0-9._ -]+[\\/]+)*[a-z0-9._ -]+\."
    r"(?:blend|png|jpe?g|exr|tga|fbx|obj|mtl|gltf|glb|json)"
)
BINARY_POSIX_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?<![a-z0-9_])/(?:home|Users|Volumes|private|tmp|var|opt|mnt|root|data|workspace|srv)/"
    r"(?:[a-z0-9._ -]+/)*[a-z0-9._ -]+\."
    r"(?:blend|png|jpe?g|exr|tga|fbx|obj|mtl|gltf|glb|json)"
)


@dataclass(frozen=True)
class CanonicalTextureContract:
    """Bind one canonical TextureManifest to its image and procedural channels."""

    material_id: str
    manifest_path: Path
    manifest_sha256: str
    image_channels: dict[str, Path]
    image_channel_hashes: dict[str, str]
    procedural_channels: frozenset[str]


def _run_for_package(job_id: str, run_id: str | None) -> tuple[Path, str, Path]:
    """Resolve an explicit or latest complete optimization run for packaging."""

    root = job_dir(job_id)
    selected = run_id or latest_complete_run_id(root)
    if not selected:
        raise FileNotFoundError("No V0.7 optimization run is available")
    run_root = run_directory(root, selected)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    if plan.status != "complete":
        raise RuntimeError(f"Optimization run is not complete: {selected}")
    optimized_blend = run_root / "optimized" / "scene.blend"
    if not optimized_blend.is_file():
        raise FileNotFoundError(optimized_blend)
    return root, selected, run_root


def _package_id(profile: AssetProfile, value: str | None) -> str:
    """Create or validate one path-safe immutable package identifier."""

    selected = value or new_run_id("package")
    validate_filesystem_id(selected, "package_id")
    if profile.profile_id not in {"portable_gltf", "fbx_interchange", "obj_legacy"}:
        raise ValueError("Unsupported portable profile")
    return selected


def _require_collider_export(profile: AssetProfile, include_colliders: bool) -> None:
    """Reject delivery settings that omit colliders required by the selected profile."""

    if not include_colliders and profile.collision.strategy != "none":
        raise ValueError(
            "include_colliders=false conflicts with the selected profile collision strategy"
        )


def _load_run_manifests(
    run_root: Path,
    plan: OptimizationPlan,
) -> tuple[LODManifest, CollisionManifest, UVManifest, StaticAssetCostReport | None]:
    """Load and cross-check all required optimization manifests against their plan."""

    core_manifests = (
        load_model(run_root / "lod_manifest.json", LODManifest),
        load_model(run_root / "collision_manifest.json", CollisionManifest),
        load_model(run_root / "uv_manifest.json", UVManifest),
    )
    cost_path = run_root / "asset_cost_report.json"
    cost = load_model(cost_path, StaticAssetCostReport) if cost_path.is_file() else None
    for manifest in core_manifests:
        if (
            manifest.job_id != plan.job_id
            or manifest.run_id != run_root.name
            or manifest.profile_id != plan.profile_id
            or manifest.source != plan.source
            or manifest.status != "complete"
        ):
            raise RuntimeError(
                f"Optimization manifest is inconsistent with its plan: {manifest.manifest_id}"
            )
    if cost is not None and (
        cost.job_id != plan.job_id
        or cost.run_id != run_root.name
        or cost.profile_id != plan.profile_id
        or cost.source != plan.source
        or not cost.ok
    ):
        raise RuntimeError(
            f"Asset cost report is inconsistent with its plan: {cost.report_id}"
        )
    return (*core_manifests, cost)


def _bounded_resolution(width: int, height: int, maximum: int) -> tuple[int, int]:
    """Scale a derived packed texture down to one profile maximum without upscaling."""

    largest = max(width, height)
    if largest <= maximum:
        return width, height
    scale = maximum / largest
    return max(1, round(width * scale)), max(1, round(height * scale))


def _verify_hashed_artifact(
    root: Path,
    artifact: HashedArtifact,
    label: str,
    *,
    required_parent: Path | None = None,
) -> Path:
    """Resolve and hash-check one job-contained artifact before derived packaging."""

    path = resolve_inside(root, artifact.path, label)
    if required_parent is not None:
        try:
            path.relative_to(required_parent.resolve())
        except ValueError as exc:
            raise RuntimeError(f"{label} is outside its required directory: {path}") from exc
    if not path.is_file() or sha256_file(path) != artifact.sha256:
        raise RuntimeError(f"{label} is missing or its SHA-256 changed: {path}")
    return path


def _verify_run_artifacts(
    root: Path,
    run_root: Path,
    plan: OptimizationPlan,
    profile: AssetProfile,
) -> dict[str, Any]:
    """Verify profile, plan outputs, optimized blend, and Blender evidence as one run."""

    stored_profile = _verify_hashed_artifact(
        root,
        plan.profile_artifact,
        "asset profile",
    )
    expected_profile = profile_path(root, profile.profile_id).resolve()
    if stored_profile != expected_profile:
        raise RuntimeError("OptimizationPlan references an unexpected asset profile path")
    preflight_path = _verify_hashed_artifact(
        root,
        plan.preflight_report,
        "mesh preflight report",
        required_parent=run_root,
    )
    if preflight_path != (run_root / "mesh_preflight_report.json").resolve():
        raise RuntimeError("OptimizationPlan references an unexpected preflight report path")

    approval_paths = {
        "review_plan": run_root / "review_plan.json",
        "review": run_root / "optimization_review.json",
        "approval": run_root / "optimization_approval.json",
    }
    existing_approval_paths = {
        name for name, path in approval_paths.items() if path.is_file()
    }
    if existing_approval_paths and existing_approval_paths != set(approval_paths):
        raise RuntimeError("Optimization review and approval evidence is incomplete")
    if existing_approval_paths:
        reviewed_plan = load_model(approval_paths["review_plan"], OptimizationPlan)
        review = load_model(approval_paths["review"], OptimizationReview)
        approval = load_model(approval_paths["approval"], OptimizationApproval)
        if (
            reviewed_plan.status != "draft"
            or reviewed_plan.plan_id != plan.plan_id
            or reviewed_plan.source != plan.source
            or reviewed_plan.profile_artifact != plan.profile_artifact
            or reviewed_plan.preflight_report != plan.preflight_report
            or reviewed_plan.directives != plan.directives
            or review.plan_sha256 != sha256_file(approval_paths["review_plan"])
            or approval.plan_sha256 != review.plan_sha256
            or approval.review_sha256 != sha256_file(approval_paths["review"])
            or approval.profile_sha256 != plan.profile_artifact.sha256
            or approval.preflight_sha256 != plan.preflight_report.sha256
            or approval.source_fingerprint != plan.source.source_fingerprint
            or not approval.used
        ):
            raise RuntimeError("Optimization review approval does not match the completed run")

    verified_paths: set[Path] = set()
    for artifact in plan.output_manifests:
        verified_paths.add(
            _verify_hashed_artifact(
                root,
                artifact,
                f"optimization output {artifact.id}",
                required_parent=run_root,
            )
        )
    required = {
        (run_root / "lod_manifest.json").resolve(),
        (run_root / "collision_manifest.json").resolve(),
        (run_root / "uv_manifest.json").resolve(),
        (run_root / "optimized" / "scene.blend").resolve(),
        (run_root / "optimized_asset_evidence.json").resolve(),
        (run_root / "execution_plan.json").resolve(),
    }
    if any(artifact.kind == "asset_cost_report" for artifact in plan.output_manifests):
        required.add((run_root / "asset_cost_report.json").resolve())
    if not required <= verified_paths:
        missing = sorted(path.as_posix() for path in required - verified_paths)
        raise RuntimeError(f"OptimizationPlan does not bind every required run artifact: {missing}")

    evidence_path = run_root / "optimized_asset_evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or not evidence.get("ok"):
        raise RuntimeError("Optimized Blender evidence is missing or unsuccessful")
    derived = evidence.get("derived")
    if not isinstance(derived, dict):
        raise RuntimeError("Optimized Blender evidence has no derived artifact record")
    optimized_blend = run_root / "optimized" / "scene.blend"
    if str(derived.get("blend_sha256", "")).lower() != sha256_file(optimized_blend):
        raise RuntimeError("Optimized blend hash differs from its Blender evidence")
    if str(evidence.get("plan_sha256", "")).lower() != sha256_file(
        run_root / "execution_plan.json"
    ):
        raise RuntimeError("Optimized evidence is not bound to the immutable execution plan")
    return evidence


def _snapshot_package_metadata(
    root: Path,
    run_root: Path,
    profile: AssetProfile,
    staging_root: Path,
    material_conversion: MaterialConversionSelection | None = None,
) -> dict[str, Path]:
    """Copy immutable optimization and optional material-conversion receipts."""

    metadata_root = staging_root / "metadata"
    metadata_root.mkdir(parents=True, exist_ok=False)
    sources = {
        "asset_profile": profile_path(root, profile.profile_id),
        "optimization_plan": run_root / "optimization_plan.json",
        "execution_plan": run_root / "execution_plan.json",
        "mesh_preflight_report": run_root / "mesh_preflight_report.json",
        "lod_manifest": run_root / "lod_manifest.json",
        "collision_manifest": run_root / "collision_manifest.json",
        "uv_manifest": run_root / "uv_manifest.json",
        "optimized_asset_evidence": run_root / "optimized_asset_evidence.json",
    }
    optional_approval_sources = {
        "review_plan": run_root / "review_plan.json",
        "optimization_review": run_root / "optimization_review.json",
        "optimization_approval": run_root / "optimization_approval.json",
    }
    if any(path.is_file() for path in optional_approval_sources.values()):
        if not all(path.is_file() for path in optional_approval_sources.values()):
            raise RuntimeError("Optimization review and approval snapshot set is incomplete")
        sources.update(optional_approval_sources)
    cost_report = run_root / "asset_cost_report.json"
    if cost_report.is_file():
        sources["asset_cost_report"] = cost_report
    if material_conversion is not None:
        sources.update(
            {
                "material_conversion_plan": (
                    material_conversion.directory / "conversion_plan.json"
                ),
                "material_conversion_manifest": (
                    material_conversion.directory / "conversion_manifest.json"
                ),
            }
        )
    if (root / "intake" / "external_asset_manifest.json").is_file():
        external_sources = {
            "external_asset_manifest": root / "intake" / "external_asset_manifest.json",
            "external_normalization_receipt": root / "intake" / "normalization_receipt.json",
            "external_intake_validation": root / "intake" / "validation.json",
        }
        if not all(path.is_file() for path in external_sources.values()):
            raise RuntimeError("External intake metadata snapshot set is incomplete")
        sources.update(external_sources)
    snapshots: dict[str, Path] = {}
    for key, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        target = metadata_root / f"{key}.json"
        _copyfile_long_path_safe(source, target)
        if sha256_file(target) != sha256_file(source):
            raise RuntimeError(f"Portable metadata snapshot hash mismatch: {key}")
        snapshots[key] = target
    if material_conversion is not None:
        evidence_source = material_conversion.directory / "conversion_evidence.json"
        if not evidence_source.is_file():
            raise FileNotFoundError(evidence_source)
        raw_evidence = json.loads(evidence_source.read_text(encoding="utf-8"))
        if not isinstance(raw_evidence, dict) or not raw_evidence.get("ok"):
            raise RuntimeError("Portable material conversion evidence is unsuccessful")
        normalized = dict(raw_evidence)
        normalized["source_evidence_sha256"] = sha256_file(evidence_source)
        source_record = dict(normalized.get("source", {}))
        source_record.update(
            {
                "optimized_blend_path": material_conversion.manifest.optimized_blend.path,
                "conversion_plan_path": material_conversion.manifest.plan_artifact.path,
                "profile_path": material_conversion.manifest.profile_artifact.path,
            }
        )
        normalized["source"] = source_record
        normalized["portable_blend"] = {
            "path": material_conversion.manifest.portable_blend.path,
            "sha256": material_conversion.manifest.portable_blend.sha256,
        }
        normalized["outputs"] = [
            output.model_dump(mode="json")
            for output in material_conversion.manifest.outputs
        ]
        normalized["texture_root"] = job_relative(
            root,
            material_conversion.directory / "textures",
        )
        evidence_target = metadata_root / "material_conversion_evidence.json"
        write_json_atomic(evidence_target, normalized)
        snapshots["material_conversion_evidence"] = evidence_target
    return snapshots


def _canonical_texture_contracts(
    root: Path,
) -> tuple[dict[str, CanonicalTextureContract], set[str], str | None]:
    """Load canonical manifests and require baking for every manifest-associated material."""

    plan_path = root / "analysis" / "material_plan.json"
    if not plan_path.is_file():
        return {}, set(), None
    plan = load_material_plan(plan_path)
    contracts: dict[str, CanonicalTextureContract] = {}
    required: set[str] = set()
    for item in plan.materials:
        recipe = None
        if item.shader_recipe:
            recipe_path = resolve_job_path(root, item.shader_recipe, "shader_recipe")
            recipe = load_shader_recipe(recipe_path)
            if recipe.material_id != item.material_id:
                raise RuntimeError(
                    f"ShaderRecipe material ID differs from MaterialPlan: {item.material_id}"
                )
            if recipe.bake_required:
                required.add(item.material_id)
        recipe_manifest = recipe.texture_manifest if recipe is not None else None
        if (
            item.texture_manifest
            and recipe_manifest
            and item.texture_manifest != recipe_manifest
        ):
            raise RuntimeError(
                "MaterialPlan and ShaderRecipe TextureManifest paths differ for "
                f"{item.material_id}"
            )
        manifest_value = item.texture_manifest or recipe_manifest
        if not manifest_value:
            continue
        required.add(item.material_id)
        manifest, manifest_path = load_material_manifest(
            {"id": item.material_id, "texture_manifest": manifest_value},
            root,
        )
        if manifest is None or manifest_path is None:
            raise RuntimeError(
                f"TextureManifest could not be loaded for {item.material_id}"
            )
        image_channels: dict[str, Path] = {}
        image_hashes: dict[str, str] = {}
        procedural_channels: set[str] = set()
        for channel, record in sorted(manifest["channels"].items()):
            if record["source"] == "procedural":
                procedural_channels.add(str(channel))
                continue
            resolved = Path(str(record["resolved_path"])).expanduser().resolve()
            image_channels[str(channel)] = resolved
            image_hashes[str(channel)] = sha256_file(resolved)
        contracts[item.material_id] = CanonicalTextureContract(
            material_id=item.material_id,
            manifest_path=manifest_path.resolve(),
            manifest_sha256=sha256_file(manifest_path),
            image_channels=image_channels,
            image_channel_hashes=image_hashes,
            procedural_channels=frozenset(procedural_channels),
        )
    return contracts, required, plan.job_id


def _verify_current_bake_provenance(
    manifest: Any,
    material_source: dict[str, Any],
    current_build: dict[str, Any],
    source: SourceProvenance,
) -> None:
    """Require one complete bake to match every current canonical build input exactly."""

    expected = {
        "source_scene_spec_sha256": current_build["scene_spec_sha256"],
        "source_geometry_payloads_sha256": current_build[
            "geometry_payloads_sha256"
        ],
        "source_camera_fingerprint": current_build["camera_fingerprint"],
        "source_material_plan_sha256": current_build["material_plan_sha256"],
        "source_shader_recipe": material_source["shader_recipe_path"],
        "source_shader_recipe_sha256": material_source["shader_recipe_sha256"],
        "source_texture_manifest": material_source["texture_manifest_path"],
        "source_texture_manifest_sha256": material_source[
            "texture_manifest_sha256"
        ],
        "source_texture_channels_sha256": {
            channel: record["sha256"]
            for channel, record in material_source["texture_channels"].items()
        },
        "source_blend_sha256": source.blend.sha256,
        "source_build_fingerprint": current_build["fingerprint"],
        "source_material_fingerprint": material_source["fingerprint"],
    }
    mismatches = {
        field: {"expected": expected_value, "actual": getattr(manifest, field)}
        for field, expected_value in expected.items()
        if getattr(manifest, field) != expected_value
    }
    if mismatches:
        raise RuntimeError(
            f"Material bake provenance is stale for {manifest.material_id}: {mismatches}"
        )


def _latest_bake_manifests(
    root: Path,
    source: SourceProvenance,
) -> tuple[list[Any], set[str], dict[str, CanonicalTextureContract]]:
    """Load fresh complete bakes and exact canonical TextureManifest channel coverage."""

    contracts, required_material_ids, job_id = _canonical_texture_contracts(root)
    if not required_material_ids:
        return [], required_material_ids, contracts

    report_path = root / "reports" / "material_bakes.json"
    if not report_path.is_file():
        raise RuntimeError(
            "Bake-required or TextureManifest-associated materials have no "
            "reports/material_bakes.json evidence"
        )
    if job_id is None:
        raise RuntimeError("Portable material baking requires a canonical MaterialPlan")
    current_build = collect_build_provenance(root, job_id)
    if current_build["fingerprint"] != source.build_fingerprint:
        raise RuntimeError("Current material build provenance differs from V0.7 source")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    values = report.get("manifest_paths", []) if isinstance(report, dict) else []
    if not isinstance(values, list):
        raise ValueError("material_bakes manifest_paths must be an array")
    manifests = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("material bake manifest paths must be strings")
        path = resolve_inside(root, value, "material bake manifest")
        manifest = load_bake_manifest(path)
        if manifest.status != "complete":
            continue
        material_source = current_build["materials"].get(manifest.material_id)
        if not isinstance(material_source, dict):
            raise RuntimeError(
                "Material bake has no current canonical material provenance: "
                f"{manifest.material_id}"
            )
        _verify_current_bake_provenance(
            manifest,
            material_source,
            current_build,
            source,
        )
        for output in manifest.outputs:
            output_path = resolve_inside(root, output.path, "material bake output")
            if not output_path.is_file() or sha256_file(output_path) != output.sha256:
                raise RuntimeError(f"Material bake output hash mismatch: {output_path}")
        manifests.append(manifest)
    actual_material_ids = [str(manifest.material_id) for manifest in manifests]
    if len(actual_material_ids) != len(set(actual_material_ids)):
        raise RuntimeError("Material bake report contains duplicate complete material manifests")
    if set(actual_material_ids) != required_material_ids:
        missing = sorted(required_material_ids - set(actual_material_ids))
        unexpected = sorted(set(actual_material_ids) - required_material_ids)
        raise RuntimeError(
            "Complete material bake coverage differs from required material contracts: "
            f"missing={missing}, unexpected={unexpected}"
        )
    for manifest in manifests:
        contract = contracts.get(str(manifest.material_id))
        if contract is None:
            continue
        output_channels = {str(output.channel) for output in manifest.outputs}
        missing_procedural = sorted(contract.procedural_channels - output_channels)
        if missing_procedural:
            raise RuntimeError(
                "Procedural TextureManifest channels lack corresponding fresh bake outputs "
                f"for {manifest.material_id}: {missing_procedural}"
            )
        if manifest.source_texture_manifest_sha256 != contract.manifest_sha256:
            raise RuntimeError(
                f"Material bake TextureManifest hash is stale for {manifest.material_id}"
            )
        if manifest.source_texture_channels_sha256 != contract.image_channel_hashes:
            raise RuntimeError(
                f"Material bake image-channel hashes are stale for {manifest.material_id}"
            )
    return manifests, required_material_ids, contracts


def _future_path(root: Path, final_root: Path, staging_root: Path, staging_path: Path) -> str:
    """Return the job-relative path an artifact will have after atomic package promotion."""

    relative = staging_path.resolve().relative_to(staging_root.resolve())
    return job_relative(root, final_root / relative)


def _hashed_texture_source(
    root: Path,
    channel: str,
    material_id: str,
    path: Path,
) -> HashedArtifact:
    """Bind one canonical baked image to a portable channel mapping."""

    return HashedArtifact(
        id=f"texture.source.{material_id}.{channel}",
        kind="other",
        path=job_relative(root, path),
        sha256=sha256_file(path),
    )


def _raw_channel_texture(
    root: Path,
    final_root: Path,
    staging_root: Path,
    material_id: str,
    channel: str,
    source_path: Path,
    output_path: Path,
) -> PackedTexture:
    """Create a canonical raw-channel receipt for one byte-preserved image."""

    with Image.open(output_path) as image:
        width, height = image.size
    scalar = channel in {
        "roughness",
        "metallic",
        "height",
        "occlusion",
        "opacity",
    }
    return PackedTexture(
        texture_id=f"texture.raw.{material_id}.{channel}",
        material_ids=[material_id],
        packing="raw_channels",
        output=HashedArtifact(
            id=f"texture.output.{material_id}.{channel}",
            kind="packed_texture",
            path=_future_path(root, final_root, staging_root, output_path),
            sha256=sha256_file(output_path),
        ),
        color_space=COLOR_SPACES[channel],  # type: ignore[arg-type]
        width=width,
        height=height,
        mappings=[
            TextureChannelMapping(
                output_channel="R" if scalar else "RGB",
                source_channel=channel,  # type: ignore[arg-type]
                source=_hashed_texture_source(
                    root,
                    channel,
                    material_id,
                    source_path,
                ),
            )
        ],
    )


def _canonical_image_texture(
    root: Path,
    final_root: Path,
    staging_root: Path,
    contract: CanonicalTextureContract,
    channel: str,
    source_path: Path,
    output_path: Path,
) -> PackedTexture:
    """Record one byte-preserved canonical TextureManifest image channel."""

    with Image.open(output_path) as image:
        width, height = image.size
    scalar = channel in {
        "roughness",
        "metallic",
        "height",
        "occlusion",
        "opacity",
    }
    return PackedTexture(
        texture_id=f"texture.canonical.{contract.material_id}.{channel}",
        material_ids=[contract.material_id],
        packing="raw_channels",
        output=HashedArtifact(
            id=f"texture.output.canonical.{contract.material_id}.{channel}",
            kind="packed_texture",
            path=_future_path(root, final_root, staging_root, output_path),
            sha256=sha256_file(output_path),
        ),
        color_space=COLOR_SPACES[channel],  # type: ignore[arg-type]
        width=width,
        height=height,
        mappings=[
            TextureChannelMapping(
                output_channel="R" if scalar else "RGB",
                source_channel=channel,  # type: ignore[arg-type]
                source=HashedArtifact(
                    id=f"texture.source.canonical.{contract.material_id}.{channel}",
                    kind="other",
                    path=job_relative(root, source_path),
                    sha256=contract.image_channel_hashes[channel],
                ),
            )
        ],
    )


def _copy_canonical_image_channels(
    root: Path,
    staging_root: Path,
    final_root: Path,
    contracts: dict[str, CanonicalTextureContract],
) -> list[PackedTexture]:
    """Copy every canonical TextureManifest image channel without byte conversion."""

    textures: list[PackedTexture] = []
    for material_id, contract in sorted(contracts.items()):
        component = (
            f"{safe_artifact_name(material_id)}-"
            f"{contract.manifest_sha256[:8]}"
        )
        output_root = staging_root / "textures" / "canonical" / component
        output_root.mkdir(parents=True, exist_ok=False)
        for channel, source_path in sorted(contract.image_channels.items()):
            target = output_root / f"{channel}{source_path.suffix.lower()}"
            _copyfile_long_path_safe(source_path, target)
            expected = contract.image_channel_hashes[channel]
            if sha256_file(target) != expected:
                raise RuntimeError(
                    "Canonical TextureManifest channel copy hash mismatch: "
                    f"{material_id}.{channel}"
                )
            textures.append(
                _canonical_image_texture(
                    root,
                    final_root,
                    staging_root,
                    contract,
                    channel,
                    source_path,
                    target,
                )
            )
    return textures


def _copy_raw_bakes(
    root: Path,
    staging_root: Path,
    final_root: Path,
    manifests: list[Any],
) -> list[PackedTexture]:
    """Copy V0.5 baked channels byte-for-byte for raw interchange profiles."""

    textures: list[PackedTexture] = []
    for manifest in manifests:
        component = (
            f"{safe_artifact_name(manifest.material_id)}-"
            f"{manifest.source_material_fingerprint[:8]}"
        )
        output_root = staging_root / "textures" / component / "raw"
        output_root.mkdir(parents=True, exist_ok=False)
        for output in manifest.outputs:
            if output.channel not in COLOR_SPACES:
                continue
            source_path = resolve_inside(root, output.path, "material bake output")
            target = output_root / f"{output.channel}{source_path.suffix.lower()}"
            _copyfile_long_path_safe(source_path, target)
            if sha256_file(target) != output.sha256:
                raise RuntimeError(f"Raw texture copy hash mismatch: {target}")
            textures.append(
                _raw_channel_texture(
                    root,
                    final_root,
                    staging_root,
                    manifest.material_id,
                    output.channel,
                    source_path,
                    target,
                )
            )
    return textures


def _gltf_packed_textures(
    root: Path,
    staging_root: Path,
    final_root: Path,
    manifests: list[Any],
    maximum_resolution: int,
) -> list[PackedTexture]:
    """Preserve raw bake channels and derive deterministic glTF ORM maps."""

    textures: list[PackedTexture] = []
    for manifest in manifests:
        component = (
            f"{safe_artifact_name(manifest.material_id)}-"
            f"{manifest.source_material_fingerprint[:8]}"
        )
        channels = {
            output.channel: output.path
            for output in manifest.outputs
            if output.channel in COLOR_SPACES
        }
        portable_components = {"occlusion", "roughness", "metallic"} & set(channels)
        if "orm" in channels and not portable_components:
            raise RuntimeError(
                f"Material {manifest.material_id} provides only a prepacked ORM image; "
                "portable_gltf requires separate occlusion, roughness, or metallic "
                "provenance before deriving a new ORM texture"
            )
        pack_channels = {
            channel: path for channel, path in channels.items() if channel != "orm"
        }
        packed_resolution = _bounded_resolution(
            int(manifest.resolution[0]),
            int(manifest.resolution[1]),
            maximum_resolution,
        )
        result = build_portable_texture_package(
            source_root=root,
            package_root=staging_root,
            output_dir=Path("textures") / component,
            channels=pack_channels,
            orm_defaults={"occlusion": 1.0, "roughness": 0.5, "metallic": 0.0},
            orm_resolution=packed_resolution,
            allow_orm_resample=(
                packed_resolution
                != (int(manifest.resolution[0]), int(manifest.resolution[1]))
            ),
            # The outer package transaction already owns atomic publication. Writing
            # directly here avoids a second deeply nested temp path on Windows.
            atomic_commit=False,
        )
        for channel, copied in sorted(result.raw_paths.items()):
            source_path = resolve_inside(root, channels[channel], "material bake output")
            textures.append(
                _raw_channel_texture(
                    root,
                    final_root,
                    staging_root,
                    manifest.material_id,
                    channel,
                    source_path,
                    copied,
                )
            )
        if "orm" in channels:
            source_path = resolve_inside(root, channels["orm"], "material bake output")
            target = result.package_dir / "raw" / f"orm{source_path.suffix.lower()}"
            _copyfile_long_path_safe(source_path, target)
            if sha256_file(target) != sha256_file(source_path):
                raise RuntimeError(f"Raw texture copy hash mismatch: {target}")
            textures.append(
                _raw_channel_texture(
                    root,
                    final_root,
                    staging_root,
                    manifest.material_id,
                    "orm",
                    source_path,
                    target,
                )
            )
        evidence_source = HashedArtifact(
            id=f"texture.orm.evidence.{manifest.material_id}",
            kind="other",
            path=_future_path(
                root,
                final_root,
                staging_root,
                result.evidence_path,
            ),
            sha256=sha256_file(result.evidence_path),
        )
        mappings = []
        for output_channel, source_channel in (
            ("R", "occlusion"),
            ("G", "roughness"),
            ("B", "metallic"),
        ):
            source_record = (
                _hashed_texture_source(
                    root,
                    source_channel,
                    manifest.material_id,
                    resolve_inside(root, channels[source_channel], "material bake output"),
                )
                if source_channel in channels
                else evidence_source
            )
            mappings.append(
                TextureChannelMapping(
                    output_channel=output_channel,  # type: ignore[arg-type]
                    source_channel=source_channel,  # type: ignore[arg-type]
                    source=source_record,
                )
            )
        with Image.open(result.orm_path) as orm_image:
            orm_width, orm_height = orm_image.size
        textures.append(
            PackedTexture(
                texture_id=f"texture.orm.{manifest.material_id}",
                material_ids=[manifest.material_id],
                packing="gltf_orm",
                output=HashedArtifact(
                    id=f"texture.output.orm.{manifest.material_id}",
                    kind="packed_texture",
                    path=_future_path(
                        root,
                        final_root,
                        staging_root,
                        result.orm_path,
                    ),
                    sha256=result.orm_sha256,
                ),
                color_space="Non-Color",
                width=orm_width,
                height=orm_height,
                mappings=mappings,
            )
        )
    return textures


def _conversion_source_artifact(
    root: Path,
    conversion_id: str,
    output: PortableChannelOutput,
) -> HashedArtifact:
    """Bind one verified global-atlas channel as portable package provenance."""

    source_path = resolve_inside(
        root,
        output.path,
        f"portable conversion {output.channel} channel",
    )
    if not source_path.is_file() or sha256_file(source_path) != output.sha256:
        raise RuntimeError(
            f"Portable conversion channel changed: {output.channel}"
        )
    return HashedArtifact(
        id=f"texture.source.conversion.{conversion_id}.{output.channel}",
        kind="other",
        path=job_relative(root, source_path),
        sha256=output.sha256,
    )


def _conversion_raw_texture(
    root: Path,
    final_root: Path,
    staging_root: Path,
    conversion: MaterialConversionSelection,
    output: PortableChannelOutput,
    copied_path: Path,
) -> PackedTexture:
    """Create one receipt for a byte-preserved global portable atlas channel."""

    if sha256_file(copied_path) != output.sha256:
        raise RuntimeError(
            f"Portable atlas copy hash mismatch: {output.channel}"
        )
    with Image.open(copied_path) as image:
        width, height = image.size
    scalar = output.channel in {"roughness", "metallic"}
    return PackedTexture(
        texture_id=(
            f"texture.conversion.{conversion.conversion_id}.{output.channel}"
        ),
        material_ids=output.material_ids,
        packing="raw_channels",
        output=HashedArtifact(
            id=(
                f"texture.output.conversion.{conversion.conversion_id}."
                f"{output.channel}"
            ),
            kind="packed_texture",
            path=_future_path(root, final_root, staging_root, copied_path),
            sha256=output.sha256,
        ),
        color_space=output.color_space,
        width=width,
        height=height,
        mappings=[
            TextureChannelMapping(
                output_channel="R" if scalar else "RGB",
                source_channel=output.channel,
                source=_conversion_source_artifact(
                    root,
                    conversion.conversion_id,
                    output,
                ),
            )
        ],
    )


def _copy_conversion_raw_channels(
    root: Path,
    staging_root: Path,
    final_root: Path,
    conversion: MaterialConversionSelection,
) -> list[PackedTexture]:
    """Copy all five global portable atlas channels without byte conversion."""

    output_root = staging_root / "textures" / "portable_atlas" / "raw"
    output_root.mkdir(parents=True, exist_ok=False)
    textures: list[PackedTexture] = []
    for output in conversion.manifest.outputs:
        source = resolve_inside(
            root,
            output.path,
            f"portable conversion {output.channel} channel",
        )
        target = output_root / f"{output.channel}.png"
        _copyfile_long_path_safe(source, target)
        textures.append(
            _conversion_raw_texture(
                root,
                final_root,
                staging_root,
                conversion,
                output,
                target,
            )
        )
    return textures


def _gltf_conversion_textures(
    root: Path,
    staging_root: Path,
    final_root: Path,
    conversion: MaterialConversionSelection,
    maximum_resolution: int,
) -> list[PackedTexture]:
    """Preserve global atlas channels and derive one deterministic glTF ORM map."""

    outputs = {item.channel: item for item in conversion.manifest.outputs}
    channels = {
        channel: resolve_inside(
            root,
            output.path,
            f"portable conversion {channel} channel",
        )
        for channel, output in outputs.items()
    }
    source_resolution = conversion.manifest.atlas_policy.resolution
    packed_resolution = _bounded_resolution(
        source_resolution,
        source_resolution,
        maximum_resolution,
    )
    result = build_portable_texture_package(
        source_root=root,
        package_root=staging_root,
        output_dir=Path("textures") / "portable_atlas",
        channels=channels,
        orm_defaults={"occlusion": 1.0},
        orm_resolution=packed_resolution,
        allow_orm_resample=packed_resolution != (source_resolution, source_resolution),
        # The surrounding package transaction owns publication of this staging tree.
        atomic_commit=False,
    )
    textures = [
        _conversion_raw_texture(
            root,
            final_root,
            staging_root,
            conversion,
            outputs[channel],
            copied,
        )
        for channel, copied in sorted(result.raw_paths.items())
    ]
    evidence_source = HashedArtifact(
        id=f"texture.orm.evidence.{conversion.conversion_id}",
        kind="other",
        path=_future_path(root, final_root, staging_root, result.evidence_path),
        sha256=sha256_file(result.evidence_path),
    )
    mappings: list[TextureChannelMapping] = []
    for output_channel, source_channel in (
        ("R", "occlusion"),
        ("G", "roughness"),
        ("B", "metallic"),
    ):
        source = (
            _conversion_source_artifact(
                root,
                conversion.conversion_id,
                outputs[source_channel],
            )
            if source_channel in outputs
            else evidence_source
        )
        mappings.append(
            TextureChannelMapping(
                output_channel=output_channel,  # type: ignore[arg-type]
                source_channel=source_channel,  # type: ignore[arg-type]
                source=source,
            )
        )
    with Image.open(result.orm_path) as orm_image:
        orm_width, orm_height = orm_image.size
    textures.append(
        PackedTexture(
            texture_id=f"texture.orm.{conversion.conversion_id}",
            material_ids=conversion.manifest.required_material_ids,
            packing="gltf_orm",
            output=HashedArtifact(
                id=f"texture.output.orm.{conversion.conversion_id}",
                kind="packed_texture",
                path=_future_path(
                    root,
                    final_root,
                    staging_root,
                    result.orm_path,
                ),
                sha256=result.orm_sha256,
            ),
            color_space="Non-Color",
            width=orm_width,
            height=orm_height,
            mappings=mappings,
        )
    )
    return textures


def _texture_manifest(
    root: Path,
    run_id: str,
    profile: AssetProfile,
    source: SourceProvenance,
    staging_root: Path,
    final_root: Path,
    material_conversion: MaterialConversionSelection | None = None,
) -> TexturePackManifest:
    """Preserve canonical images and package either V0.5 or V0.7.1 outputs."""

    if material_conversion is not None:
        contracts, _, _ = _canonical_texture_contracts(root)
        canonical_textures = _copy_canonical_image_channels(
            root,
            staging_root,
            final_root,
            contracts,
        )
        if profile.textures.packing == "gltf_orm":
            converted_textures = _gltf_conversion_textures(
                root,
                staging_root,
                final_root,
                material_conversion,
                profile.textures.maximum_resolution,
            )
        else:
            converted_textures = _copy_conversion_raw_channels(
                root,
                staging_root,
                final_root,
                material_conversion,
            )
        now = utc_now()
        return TexturePackManifest(
            manifest_id=f"texture.pack.{run_id}",
            job_id=profile.job_id,
            run_id=run_id,
            profile_id=profile.profile_id,
            source=source,
            status="complete",
            packing_required=True,
            textures=[*canonical_textures, *converted_textures],
            created_at=now,
            completed_at=now,
            notes=[
                "Canonical TextureManifest images remain byte-preserved.",
                "The five portable atlas channels were produced from an explicit "
                "hash-bound V0.7.1 derived material conversion.",
                "glTF ORM, when present, is derived while raw channels remain included.",
            ],
        )

    manifests, required_material_ids, contracts = _latest_bake_manifests(root, source)
    canonical_textures = _copy_canonical_image_channels(
        root,
        staging_root,
        final_root,
        contracts,
    )
    if profile.textures.packing == "gltf_orm":
        baked_textures = _gltf_packed_textures(
            root,
            staging_root,
            final_root,
            manifests,
            profile.textures.maximum_resolution,
        )
    elif profile.textures.packing == "raw_channels":
        baked_textures = _copy_raw_bakes(root, staging_root, final_root, manifests)
    else:
        baked_textures = _copy_raw_bakes(root, staging_root, final_root, manifests)
    textures = [*canonical_textures, *baked_textures]
    now = utc_now()
    return TexturePackManifest(
        manifest_id=f"texture.pack.{run_id}",
        job_id=profile.job_id,
        run_id=run_id,
        profile_id=profile.profile_id,
        source=source,
        status="complete",
        packing_required=bool(textures),
        textures=textures,
        created_at=now,
        completed_at=now,
        notes=(
            [
                "No ShaderRecipe or TextureManifest requires portable texture outputs."
            ]
            if not required_material_ids
            else [
                "Canonical TextureManifest image channels and fresh portable bake outputs "
                "are byte-preserved; glTF ORM is a derived portable texture."
            ]
        ),
    )


def _delivery_mapping(
    job_id: str,
    run_id: str,
    profile: AssetProfile,
    primary: Path,
    staging_root: Path,
    raw_export: dict[str, Any],
) -> dict[str, Any]:
    """Build a package-relative consumer mapping from Blender export evidence."""

    objects: list[dict[str, Any]] = []
    for index, record in enumerate(raw_export.get("objects", []), start=1):
        if not isinstance(record, dict):
            raise ValueError("Portable export object evidence must contain JSON objects")
        semantic_id = str(record.get("semantic_id") or "")
        role = str(record.get("asset_role") or "authoring")
        instance_index = record.get("instance_index")
        lod_level = record.get("lod_level")
        stable_parts = [semantic_id, str(instance_index), role, str(lod_level)]
        export_key = "|".join(stable_parts) if semantic_id else f"name:{record.get('name')}"
        objects.append(
            {
                "export_key": export_key,
                "name": str(record.get("name") or f"object-{index:04d}"),
                "semantic_id": semantic_id or None,
                "instance_index": instance_index,
                "asset_role": role,
                "lod_level": lod_level,
                "collider": role == "collider",
                "material_ids": sorted(str(value) for value in record.get("material_ids", [])),
            }
        )
    return {
        "schema_version": "0.7.0",
        "kind": "portable_delivery_mapping",
        "job_id": job_id,
        "run_id": run_id,
        "profile_id": profile.profile_id,
        "primary_asset": primary.resolve().relative_to(staging_root.resolve()).as_posix(),
        "objects": objects,
    }


def _package_file(
    root: Path,
    final_root: Path,
    staging_root: Path,
    path: Path,
    primary: Path,
    index: int,
) -> PackageFile:
    """Create one immutable package file receipt using its future final path."""

    size = path.stat().st_size
    if size <= 0:
        raise RuntimeError(f"Portable package contains an empty file: {path}")
    suffix = path.suffix.lower()
    relative = path.resolve().relative_to(staging_root.resolve())
    is_primary = path.resolve() == primary.resolve()
    if is_primary:
        kind = "primary_asset"
    elif suffix in {".png", ".jpg", ".jpeg"}:
        kind = "texture"
    elif suffix == ".json":
        kind = "metadata"
    else:
        kind = "other"
    return PackageFile(
        id="package.primary" if is_primary else f"package.file.{index:04d}",
        kind=kind,  # type: ignore[arg-type]
        path=job_relative(root, final_root / relative),
        sha256=sha256_file(path),
        byte_size=size,
        media_type=MEDIA_TYPES.get(suffix, "application/octet-stream"),
    )


def _absolute_path_audit_payloads(path: Path, data: bytes) -> list[tuple[str, str]]:
    """Decode only text-bearing regions so binary geometry bytes cannot mimic paths."""

    if path.suffix.lower() == ".glb" and data.startswith(b"glTF") and len(data) >= 20:
        payloads: list[tuple[str, str]] = []
        offset = 12
        while offset + 8 <= len(data):
            length, chunk_type = struct.unpack_from("<II", data, offset)
            offset += 8
            chunk = data[offset : offset + length]
            offset += length
            if chunk_type == 0x4E4F534A:
                payloads.append(("glb_json", chunk.decode("utf-8", errors="ignore")))
        return payloads

    payloads = [("utf8", data.decode("utf-8", errors="ignore"))]
    if path.suffix.lower() in {".bin", ".fbx"} and b"\x00" in data:
        payloads.append(("utf16le", data.decode("utf-16le", errors="ignore")))
    return payloads


def _embedded_absolute_path_findings(
    paths: list[Path], package_root: Path
) -> list[str]:
    """Find absolute-path markers in portable text and primary binary containers."""

    findings: set[str] = set()
    resolved_root = package_root.resolve()
    for path in paths:
        if path.suffix.lower() not in ABSOLUTE_PATH_AUDIT_SUFFIXES:
            continue
        data = path.read_bytes()
        decoded = _absolute_path_audit_payloads(path, data)
        try:
            label = path.resolve().relative_to(resolved_root).as_posix()
        except ValueError:
            label = path.name
        for encoding, text in decoded:
            patterns = (
                (
                    ("windows", BINARY_WINDOWS_ABSOLUTE_PATH_PATTERN),
                    ("posix", BINARY_POSIX_ABSOLUTE_PATH_PATTERN),
                )
                if path.suffix.lower() == ".fbx"
                else (
                    ("windows", WINDOWS_ABSOLUTE_PATH_PATTERN),
                    ("posix", POSIX_ABSOLUTE_PATH_PATTERN),
                )
            )
            for kind, pattern in patterns:
                for match in pattern.finditer(text):
                    findings.add(f"{label}:{encoding}:{kind}:{match.start()}")
    return sorted(findings)


def _verify_package_receipts(
    root: Path,
    package_root: Path,
    package: ExportPackageManifest,
    manifest_path: Path,
) -> dict[str, Path]:
    """Verify exact package containment, receipt hashes/sizes, and untracked files."""

    resolved_root = package_root.resolve()
    declared_root = resolve_inside(root, package.package_root, "declared package root")
    if declared_root != resolved_root:
        raise RuntimeError(
            "Package manifest package_root does not equal the requested package directory"
        )
    verified: dict[str, Path] = {}
    for receipt in package.files:
        path = resolve_inside(root, receipt.path, f"package file {receipt.id}")
        try:
            path.relative_to(resolved_root)
        except ValueError as exc:
            raise RuntimeError(
                f"Package receipt escapes its immutable package root: {receipt.id}"
            ) from exc
        if not path.is_file():
            raise RuntimeError(f"Package receipt is missing: {receipt.id}")
        if path.stat().st_size != receipt.byte_size:
            raise RuntimeError(f"Package receipt size changed: {receipt.id}")
        if sha256_file(path) != receipt.sha256:
            raise RuntimeError(f"Package receipt SHA-256 changed: {receipt.id}")
        verified[receipt.id] = path

    actual_files: set[Path] = set()
    for candidate in package_root.rglob("*"):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise RuntimeError(f"Package contains an escaping file: {candidate}") from exc
        actual_files.add(resolved)
    tracked_files = {path.resolve() for path in verified.values()}
    allowed_unreceipted = {manifest_path.resolve()}
    untracked = sorted(
        path.relative_to(resolved_root).as_posix()
        for path in actual_files - tracked_files - allowed_unreceipted
    )
    if untracked:
        raise RuntimeError(f"Portable package contains untracked files: {untracked}")
    unexpected_receipts = sorted(
        path.relative_to(resolved_root).as_posix()
        for path in tracked_files - actual_files
    )
    if unexpected_receipts:
        raise RuntimeError(f"Portable package receipts have no files: {unexpected_receipts}")
    return verified


def _primary_asset_filename(primary_format: str) -> str:
    """Choose the stable package filename expected by each interchange format."""

    normalized = primary_format.strip().lower()
    return "model.fbx" if normalized == "fbx" else f"asset.{normalized}"


def package_asset(
    job_id: str,
    *,
    profile_id: str = "portable_gltf",
    run_id: str | None = None,
    package_id: str | None = None,
    material_conversion_id: str | None = None,
    include_colliders: bool = True,
) -> ExportPackageManifest:
    """Build one immutable package from a verified optimization and material run."""

    if not load_feature_config().features.portable_asset_core:
        raise RuntimeError("portable_asset_core is disabled in cbm.toml")
    root, selected, run_root = _run_for_package(job_id, run_id)
    plan = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    profile = load_asset_profile(root, profile_id)
    if plan.profile_id != profile.profile_id:
        raise ValueError("Optimization plan and requested package profiles do not match")
    _require_collider_export(profile, include_colliders)
    require_unchanged_source(plan.source, root, job_id)
    _load_run_manifests(run_root, plan)
    optimized_evidence = _verify_run_artifacts(root, run_root, plan, profile)
    has_material_plan = (root / "analysis" / "material_plan.json").is_file()
    if has_material_plan and not material_conversion_id:
        raise RuntimeError(
            "This job has V0.5 material contracts; run asset-material-convert and "
            "provide material_conversion_id before portable packaging"
        )
    material_conversion = (
        load_portable_material_conversion(
            root,
            selected,
            material_conversion_id,
            profile=profile,
            optimization=plan,
        )
        if material_conversion_id
        else None
    )
    chosen_package_id = _package_id(profile, package_id)
    profile_root = root / "exports" / "packages" / profile.profile_id
    final_root = resolve_inside(profile_root, chosen_package_id, "portable package")
    if final_root.exists():
        raise FileExistsError(f"Portable package already exists: {final_root}")
    profile_root.mkdir(parents=True, exist_ok=True)
    staging_root = profile_root / f".{chosen_package_id}.{uuid4().hex}.tmp"
    staging_root.mkdir(parents=False, exist_ok=False)
    try:
        extension = profile.primary_format
        primary = staging_root / _primary_asset_filename(extension)
        raw_export = staging_root / "export_evidence.json"
        export_blend = (
            material_conversion.portable_blend
            if material_conversion is not None
            else run_root / "optimized" / "scene.blend"
        )
        execution_plan_sha256 = str(optimized_evidence.get("plan_sha256", ""))
        if not execution_plan_sha256:
            raise RuntimeError("Optimized run evidence has no execution-plan hash")
        snapshots = _snapshot_package_metadata(
            root,
            run_root,
            profile,
            staging_root,
            material_conversion,
        )
        args = [
            "--format",
            profile.primary_format,
            "--output",
            str(primary),
            "--manifest",
            str(raw_export),
            "--package-root",
            str(staging_root),
            "--expected-plan-sha256",
            execution_plan_sha256,
            "--expected-input-blend-sha256",
            sha256_file(export_blend),
        ]
        if material_conversion is not None:
            args.extend(
                [
                    "--expected-material-conversion-plan-sha256",
                    material_conversion.manifest.plan_artifact.sha256,
                ]
            )
        if include_colliders and profile.collision.strategy != "none":
            args.append("--include-colliders")
        run_blender(
            "export_portable_package.py",
            args,
            blend_file=export_blend,
        )
        if sha256_file(export_blend) != args[args.index("--expected-input-blend-sha256") + 1]:
            raise RuntimeError("Portable input blend changed during package export")
        raw = json.loads(raw_export.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not raw.get("ok"):
            raise RuntimeError("Portable Blender export did not produce successful evidence")
        write_json_atomic(
            staging_root / "metadata" / "delivery_mapping.json",
            _delivery_mapping(
                job_id,
                selected,
                profile,
                primary,
                staging_root,
                raw,
            ),
        )
        texture_manifest = _texture_manifest(
            root,
            selected,
            profile,
            plan.source,
            staging_root,
            final_root,
            material_conversion,
        )
        texture_path = staging_root / "texture_pack_manifest.json"
        write_model(texture_path, texture_manifest)
        staged_files = sorted(path for path in staging_root.rglob("*") if path.is_file())
        absolute_path_findings = _embedded_absolute_path_findings(
            staged_files, staging_root
        )
        if absolute_path_findings:
            affected = sorted(
                {finding.split(":", 1)[0] for finding in absolute_path_findings}
            )
            raise RuntimeError(
                "Portable package contains embedded absolute-path markers "
                f"({len(absolute_path_findings)}) in: {affected}"
            )
        files = [
            _package_file(root, final_root, staging_root, path, primary, index)
            for index, path in enumerate(staged_files, start=1)
        ]
        primary_receipt = next(item for item in files if item.kind == "primary_asset")
        source_manifests = [
            HashedArtifact(
                id=f"manifest.lod.{selected}",
                kind="lod_manifest",
                path=_future_path(
                    root,
                    final_root,
                    staging_root,
                    snapshots["lod_manifest"],
                ),
                sha256=sha256_file(snapshots["lod_manifest"]),
            ),
            HashedArtifact(
                id=f"manifest.collision.{selected}",
                kind="collision_manifest",
                path=_future_path(
                    root,
                    final_root,
                    staging_root,
                    snapshots["collision_manifest"],
                ),
                sha256=sha256_file(snapshots["collision_manifest"]),
            ),
            HashedArtifact(
                id=f"manifest.uv.{selected}",
                kind="uv_manifest",
                path=_future_path(
                    root,
                    final_root,
                    staging_root,
                    snapshots["uv_manifest"],
                ),
                sha256=sha256_file(snapshots["uv_manifest"]),
            ),
            HashedArtifact(
                id=f"manifest.texture_pack.{selected}",
                kind="texture_pack_manifest",
                path=_future_path(
                    root,
                    final_root,
                    staging_root,
                    texture_path,
                ),
                sha256=sha256_file(texture_path),
            ),
        ]
        if "asset_cost_report" in snapshots:
            source_manifests.append(
                HashedArtifact(
                    id=f"report.asset_cost.{selected}",
                    kind="asset_cost_report",
                    path=_future_path(
                        root,
                        final_root,
                        staging_root,
                        snapshots["asset_cost_report"],
                    ),
                    sha256=sha256_file(snapshots["asset_cost_report"]),
                )
            )
        conversion_receipt = (
            PortableMaterialContractArtifact(
                id=f"manifest.material.conversion.{material_conversion_id}",
                kind="portable_material_conversion_manifest",
                path=_future_path(
                    root,
                    final_root,
                    staging_root,
                    snapshots["material_conversion_manifest"],
                ),
                sha256=sha256_file(
                    snapshots["material_conversion_manifest"]
                ),
            )
            if material_conversion is not None
            else None
        )
        conversion_losses = sorted(
            {
                loss
                for entry in (
                    material_conversion.manifest.entries
                    if material_conversion is not None
                    else []
                )
                for loss in entry.losses
            }
        )
        conversion_warnings = sorted(
            {
                warning
                for entry in (
                    material_conversion.manifest.entries
                    if material_conversion is not None
                    else []
                )
                for warning in entry.warnings
            }
        )
        now = utc_now()
        manifest = ExportPackageManifest(
            package_id=chosen_package_id,
            job_id=job_id,
            run_id=selected,
            profile_id=profile.profile_id,
            source=plan.source,
            optimization_plan=HashedArtifact(
                id=f"plan.{selected}",
                kind="optimization_plan",
                path=_future_path(
                    root,
                    final_root,
                    staging_root,
                    snapshots["optimization_plan"],
                ),
                sha256=sha256_file(snapshots["optimization_plan"]),
            ),
            material_conversion=conversion_receipt,
            source_manifests=source_manifests,
            status="complete",
            package_root=job_relative(root, final_root),
            files=files,
            primary_file_id=primary_receipt.id,
            semantic_ids=sorted(str(value) for value in raw.get("semantic_ids", [])),
            material_ids=sorted(str(value) for value in raw.get("material_ids", [])),
            absolute_path_count=len(absolute_path_findings),
            created_at=now,
            completed_at=now,
            known_losses=[
                *conversion_losses,
                *(
                    ["OBJ cannot preserve CBM custom semantic properties."]
                    if profile.primary_format == "obj"
                    else []
                ),
            ],
            warnings=sorted(
                {
                    *conversion_warnings,
                    *(str(value) for value in raw.get("warnings", [])),
                }
            ),
        )
        package_manifest_path = staging_root / "package_manifest.json"
        write_model(package_manifest_path, manifest)
        manifest_path_findings = _embedded_absolute_path_findings(
            [package_manifest_path], staging_root
        )
        if manifest_path_findings:
            raise RuntimeError("Portable package manifest contains an absolute path")
        require_unchanged_source(plan.source, root, job_id)
        os.replace(staging_root, final_root)
        return manifest
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def _all_bounds(records: list[dict[str, Any]]) -> Bounds3D:
    """Aggregate imported or expected object bounds for round-trip validation."""

    if not records:
        return Bounds3D(minimum=(0.0, 0.0, 0.0), maximum=(0.0, 0.0, 0.0))
    minima = [record["bbox_world"]["min"] for record in records]
    maxima = [record["bbox_world"]["max"] for record in records]
    return Bounds3D(
        minimum=tuple(min(float(value[axis]) for value in minima) for axis in range(3)),
        maximum=tuple(max(float(value[axis]) for value in maxima) for axis in range(3)),
    )


def _bounds_error(source: Bounds3D, imported: Bounds3D) -> float:
    """Return the maximum absolute aggregate-bound difference across all axes."""

    differences = [
        abs(float(first) - float(second))
        for first, second in zip(source.minimum, imported.minimum, strict=True)
    ]
    differences.extend(
        abs(float(first) - float(second))
        for first, second in zip(source.maximum, imported.maximum, strict=True)
    )
    return max(differences, default=0.0)


def _roundtrip_object_sets_match(
    expected_objects: list[dict[str, Any]],
    imported_objects: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
) -> bool:
    """Require non-empty expected/imported sets and one complete comparison per object."""

    expected_names = {str(item.get("name")) for item in expected_objects}
    imported_names = {str(item.get("name")) for item in imported_objects}
    compared_expected = {str(item.get("expected_name")) for item in comparisons}
    compared_imported = {str(item.get("actual_name")) for item in comparisons}
    return bool(expected_objects) and (
        len(expected_objects) == len(imported_objects) == len(comparisons)
        and expected_names == compared_expected
        and imported_names == compared_imported
    )


def _roundtrip_category(message: str) -> str:
    """Classify a clean-import finding into the round-trip contract taxonomy."""

    lowered = message.lower()
    if "dependency" in lowered or "outside" in lowered:
        return "dependency"
    if "material" in lowered:
        return "material_id"
    if "texture" in lowered or "path" in lowered:
        return "texture"
    if "tangent" in lowered:
        return "tangent"
    if "normal" in lowered:
        return "normal"
    if "axis" in lowered:
        return "axis"
    if "unit" in lowered:
        return "units"
    if "uv" in lowered:
        return "uv"
    if "bounds" in lowered:
        return "bounds"
    if "object" in lowered:
        return "object"
    return "format"


def _build_roundtrip_report(
    *,
    root: Path,
    job_id: str,
    profile_id: str,
    package: ExportPackageManifest,
    manifest_path: Path,
    raw_export: Path,
    raw_output: Path,
    final_raw_output: Path,
    bounds_tolerance_m: float,
    raw: dict[str, Any],
) -> RoundTripValidation:
    """Normalize clean-import evidence into one strict V0.7 round-trip report."""

    checks: list[RoundTripCheck] = []
    for status, key in (("failed", "errors"), ("warning", "warnings")):
        values = raw.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"Round-trip evidence {key} must be an array")
        for index, value in enumerate(values, start=1):
            message = str(value)
            checks.append(
                RoundTripCheck(
                    id=f"roundtrip.{status}.{index:04d}",
                    category=_roundtrip_category(message),  # type: ignore[arg-type]
                    status=status,  # type: ignore[arg-type]
                    message=message,
                )
            )
    checks.append(
        RoundTripCheck(
            id="roundtrip.clean_import.completed",
            category="format",
            status="passed",
            message="Blender completed a clean-scene package import.",
        )
    )
    raw_export_payload = json.loads(raw_export.read_text(encoding="utf-8"))
    if not isinstance(raw_export_payload, dict):
        raise ValueError("Portable export evidence must contain a JSON object")
    expected_objects = raw_export_payload.get("objects", [])
    imported_objects = raw.get("imported_objects", [])
    comparisons = raw.get("comparisons", [])
    roundtrip_arrays = (expected_objects, imported_objects, comparisons)
    if not all(isinstance(values, list) for values in roundtrip_arrays):
        raise ValueError("Round-trip object and comparison evidence must use arrays")
    if not all(
        isinstance(item, dict)
        for values in (expected_objects, imported_objects, comparisons)
        for item in values
    ):
        raise ValueError("Round-trip object and comparison arrays must contain JSON objects")
    expected_objects = list(expected_objects)
    imported_objects = list(imported_objects)
    comparisons = list(comparisons)
    per_object_error = max(
        (float(item.get("bounds_max_abs_error_m", 0.0)) for item in comparisons),
        default=0.0,
    )
    object_sets_match = _roundtrip_object_sets_match(
        expected_objects,
        imported_objects,
        comparisons,
    )
    if not object_sets_match:
        checks.append(
            RoundTripCheck(
                id="roundtrip.object_set.exact",
                category="object",
                status="failed",
                message=(
                    "Round-trip object sets do not match exactly or contain zero matched "
                    f"objects: expected={len(expected_objects)}, "
                    f"imported={len(imported_objects)}, matched={len(comparisons)}."
                ),
            )
        )
    source_bounds = _all_bounds(expected_objects)
    imported_bounds = _all_bounds(imported_objects)
    max_error = max(per_object_error, _bounds_error(source_bounds, imported_bounds))
    if not object_sets_match:
        max_error = max(
            max_error,
            bounds_tolerance_m + max(bounds_tolerance_m * 1e-6, 1e-12),
        )
    bounds = BoundsComparison(
        source=source_bounds,
        imported=imported_bounds,
        max_abs_error_m=max_error,
        tolerance_m=bounds_tolerance_m,
        passed=max_error <= bounds_tolerance_m,
    )
    if not bounds.passed:
        checks.append(
            RoundTripCheck(
                id="roundtrip.bounds.tolerance",
                category="bounds",
                status="failed",
                message=(
                    f"Imported aggregate/per-object bounds error {max_error:.9f} m exceeds "
                    f"{bounds_tolerance_m:.9f} m."
                ),
            )
        )
    expected_semantic = sorted(
        set(package.semantic_ids) if profile_id != "obj_legacy" else set()
    )
    observed_semantic = sorted(
        {
            str(record.get("semantic_id"))
            for record in imported_objects
            if record.get("semantic_id")
        }
    )
    if profile_id == "obj_legacy":
        observed_semantic = []
    expected_materials = sorted(set(package.material_ids))
    observed_materials = sorted(
        {
            str(value)
            for record in imported_objects
            for value in record.get("material_ids", [])
        }
    )
    semantic_coverage = (
        len(set(expected_semantic) & set(observed_semantic)) / len(expected_semantic)
        if expected_semantic
        else 1.0
    )
    material_coverage = (
        len(set(expected_materials) & set(observed_materials)) / len(expected_materials)
        if expected_materials
        else 1.0
    )
    if semantic_coverage < 1.0:
        checks.append(
            RoundTripCheck(
                id="roundtrip.semantic_id.coverage",
                category="semantic_id",
                status="failed",
                message=f"Semantic ID coverage is {semantic_coverage:.6f}.",
            )
        )
    if material_coverage < 1.0:
        checks.append(
            RoundTripCheck(
                id="roundtrip.material_id.coverage",
                category="material_id",
                status="failed",
                message=f"Material ID coverage is {material_coverage:.6f}.",
            )
        )
    counts = {
        status: sum(check.status == status for check in checks)
        for status in ("passed", "warning", "failed")
    }
    ok = (
        counts["failed"] == 0
        and bounds.passed
        and semantic_coverage == 1.0
        and material_coverage == 1.0
    )
    return RoundTripValidation(
        validation_id=f"roundtrip.{package.package_id}",
        job_id=job_id,
        run_id=package.run_id,
        package_id=package.package_id,
        profile_id=package.profile_id,
        package_manifest=HashedArtifact(
            id=f"package.manifest.{package.package_id}",
            kind="package_manifest",
            path=job_relative(root, manifest_path),
            sha256=sha256_file(manifest_path),
        ),
        imported_inventory=HashedArtifact(
            id=f"roundtrip.inventory.{package.package_id}",
            kind="roundtrip_inventory",
            path=job_relative(root, final_raw_output),
            sha256=sha256_file(raw_output),
        ),
        status="passed" if ok else "failed",
        ok=ok,
        passed=counts["passed"],
        warnings=counts["warning"],
        failed=counts["failed"],
        checks=checks,
        bounds=bounds,
        expected_semantic_ids=expected_semantic,
        observed_semantic_ids=observed_semantic,
        semantic_id_coverage=semantic_coverage,
        expected_material_ids=expected_materials,
        observed_material_ids=observed_materials,
        material_id_coverage=material_coverage,
        created_at=utc_now(),
    )


def validate_asset_package(
    job_id: str,
    package_id: str,
    *,
    profile_id: str = "portable_gltf",
    bounds_tolerance_m: float = 0.0001,
) -> RoundTripValidation:
    """Clean-import one immutable package and validate IDs, materials, bounds, and paths."""

    if not load_feature_config().features.portable_asset_core:
        raise RuntimeError("portable_asset_core is disabled in cbm.toml")
    if bounds_tolerance_m <= 0:
        raise ValueError("bounds_tolerance_m must be positive")
    portable_format = profile_id_to_format(profile_id)
    validate_filesystem_id(package_id, "package_id")
    root = job_dir(job_id)
    package_root = resolve_inside(
        root / "exports" / "packages" / profile_id,
        package_id,
        "portable package",
    )
    manifest_path = package_root / "package_manifest.json"
    package = load_model(manifest_path, ExportPackageManifest)
    if (
        package.job_id != job_id
        or package.profile_id != profile_id
        or package.package_id != package_id
    ):
        raise ValueError("Package manifest does not match the requested job/profile")
    verified_receipts = _verify_package_receipts(root, package_root, package, manifest_path)
    absolute_path_findings = _embedded_absolute_path_findings(
        [*verified_receipts.values(), manifest_path], package_root
    )
    if absolute_path_findings:
        affected = sorted(
            {finding.split(":", 1)[0] for finding in absolute_path_findings}
        )
        raise RuntimeError(
            "Portable package contains embedded absolute-path markers "
            f"({len(absolute_path_findings)}) in: {affected}"
        )
    primary_receipt = next(
        item for item in package.files if item.id == package.primary_file_id
    )
    primary = verified_receipts[primary_receipt.id]
    run_root = run_directory(root, package.run_id)
    validation_parent = run_root / "roundtrip"
    validation_root = validation_parent / package.package_id
    if validation_root.exists():
        raise FileExistsError(f"Round-trip validation already exists: {validation_root}")
    validation_parent.mkdir(parents=True, exist_ok=True)
    staging_root = validation_parent / f".{package.package_id}.{uuid4().hex}.tmp"
    staging_root.mkdir(parents=False, exist_ok=False)
    raw_export = package_root / "export_evidence.json"
    raw_output = staging_root / "roundtrip_evidence.json"
    try:
        run_blender(
            "validate_export_roundtrip.py",
            [
                "--format",
                portable_format,
                "--input",
                str(primary),
                "--expected",
                str(raw_export),
                "--output",
                str(raw_output),
                "--package-root",
                str(package_root),
                "--bounds-tolerance",
                str(bounds_tolerance_m),
            ],
            factory_startup=True,
        )
        raw = json.loads(raw_output.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Round-trip evidence must contain a JSON object")
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
    try:
        report = _build_roundtrip_report(
            root=root,
            job_id=job_id,
            profile_id=profile_id,
            package=package,
            manifest_path=manifest_path,
            raw_export=raw_export,
            raw_output=raw_output,
            final_raw_output=validation_root / raw_output.name,
            bounds_tolerance_m=bounds_tolerance_m,
            raw=raw,
        )
        write_model(staging_root / "roundtrip_validation.json", report)
        os.replace(staging_root, validation_root)
        return report
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise


def profile_id_to_format(profile_id: str) -> str:
    """Map one versioned portable profile to its clean-import file format."""

    try:
        return {
            "portable_gltf": "glb",
            "fbx_interchange": "fbx",
            "obj_legacy": "obj",
        }[profile_id]
    except KeyError as exc:
        raise ValueError("Unsupported portable profile") from exc
