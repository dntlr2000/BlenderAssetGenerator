"""Explicit derived-only material conversion for portable V0.7.1 packages."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_runner import run_blender
from ..config import load_feature_config
from ..materials.io import load_material_plan, load_shader_recipe, resolve_job_path
from ..optimization.io import (
    job_relative,
    load_model,
    resolve_inside,
    run_directory,
    utc_now,
    validate_filesystem_id,
    write_model,
)
from ..optimization.models import (
    AssetProfile,
    HashedArtifact,
    LODManifest,
    OptimizationPlan,
    PortableAtlasPolicy,
    PortableAtlasTile,
    PortableChannelOutput,
    PortableMaterialBinding,
    PortableMaterialContractArtifact,
    PortableMaterialConversionEntry,
    PortableMaterialConversionManifest,
    PortableMaterialConversionPlan,
    PortableSurfaceFactors,
    UVManifest,
)
from ..optimization.preflight import load_asset_profile, profile_artifact, profile_path
from ..optimization.provenance import (
    collect_source_build_provenance,
    require_unchanged_source,
)
from ..workspace import job_dir, sha256_file


@dataclass(frozen=True)
class MaterialConversionSelection:
    """Return one verified immutable conversion and its portable Blender scene."""

    conversion_id: str
    directory: Path
    plan: PortableMaterialConversionPlan
    manifest: PortableMaterialConversionManifest
    portable_blend: Path


def material_conversion_directory(
    root: Path,
    run_id: str,
    conversion_id: str,
) -> Path:
    """Resolve one job-owned conversion path without accepting path-like identifiers."""

    validate_filesystem_id(run_id, "run_id")
    validate_filesystem_id(conversion_id, "conversion_id")
    parent = root / "optimization" / "material_conversions" / run_id
    return resolve_inside(parent, conversion_id, "portable material conversion")


def _material_conversion_staging_directory(parent: Path) -> Path:
    """Create one short collision-safe transaction path for deep Windows workspaces."""

    return parent / f".tmp-{uuid4().hex[:8]}"


def _hashed_artifact(
    root: Path,
    artifact_id: str,
    kind: str,
    path: Path,
) -> HashedArtifact:
    """Bind one existing job-contained input to a role-correct hash receipt."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return HashedArtifact(
        id=artifact_id,
        kind=kind,
        path=job_relative(root, path),
        sha256=sha256_file(path),
    )


def _shader_artifact(
    root: Path,
    material_id: str,
    path: Path,
) -> PortableMaterialContractArtifact:
    """Bind one approved V0.5 ShaderRecipe to a portable conversion plan."""

    if not path.is_file():
        raise FileNotFoundError(path)
    return PortableMaterialContractArtifact(
        id=f"shader.recipe.{material_id}",
        kind="shader_recipe",
        path=job_relative(root, path),
        sha256=sha256_file(path),
    )


def _material_bindings(
    root: Path,
    job_id: str,
    lod: LODManifest,
    current_build: dict[str, Any],
) -> list[PortableMaterialBinding]:
    """Bind every exported material ID to its recipe, fingerprint, and LOD0 families."""

    material_plan_path = root / "analysis" / "material_plan.json"
    if not material_plan_path.is_file():
        raise RuntimeError(
            "Portable material conversion requires analysis/material_plan.json"
        )
    material_plan = load_material_plan(material_plan_path)
    if material_plan.job_id != job_id:
        raise RuntimeError("MaterialPlan job_id does not match the conversion job")
    plan_items = {item.material_id: item for item in material_plan.materials}
    required = sorted(
        {
            material_id
            for entry in lod.entries
            if entry.level == 0
            for material_id in entry.material_ids
        }
    )
    if not required:
        raise RuntimeError("Optimized LOD0 evidence contains no material identities")
    missing_plan = sorted(set(required) - set(plan_items))
    if missing_plan:
        raise RuntimeError(
            f"Exported materials are missing from MaterialPlan: {missing_plan}"
        )

    bindings: list[PortableMaterialBinding] = []
    build_materials = current_build.get("materials", {})
    for material_id in required:
        item = plan_items[material_id]
        if not item.shader_recipe:
            raise RuntimeError(f"{material_id} has no approved ShaderRecipe")
        recipe_path = resolve_job_path(root, item.shader_recipe, "shader_recipe")
        recipe = load_shader_recipe(recipe_path)
        if recipe.material_id != material_id:
            raise RuntimeError(
                f"ShaderRecipe material ID differs from MaterialPlan: {material_id}"
            )
        if recipe.mapping.mode == "generated":
            raise RuntimeError(
                f"{material_id} uses generated mapping, which V0.7.1 portable "
                "conversion does not support; use uv, object, or triplanar mapping"
            )
        build_record = build_materials.get(material_id)
        if not isinstance(build_record, dict) or not build_record.get("fingerprint"):
            raise RuntimeError(
                f"Current build provenance has no material fingerprint: {material_id}"
            )
        target_ids = sorted(
            {
                entry.target_id
                for entry in lod.entries
                if entry.level == 0 and material_id in entry.material_ids
            }
        )
        bindings.append(
            PortableMaterialBinding(
                material_id=material_id,
                source_shader_recipe=_shader_artifact(root, material_id, recipe_path),
                source_material_fingerprint=str(build_record["fingerprint"]),
                mapping_mode=recipe.mapping.mode,
                target_ids=target_ids,
                bake_required=True,
            )
        )
    return bindings


def _conversion_plan(
    root: Path,
    job_id: str,
    run_id: str,
    conversion_id: str,
    profile: AssetProfile,
    optimization: OptimizationPlan,
    lod: LODManifest,
    current_build: dict[str, Any],
    *,
    resolution: int,
    margin_px: int,
) -> PortableMaterialConversionPlan:
    """Create an approved immutable-input plan for one explicit conversion request."""

    run_root = run_directory(root, run_id)
    bindings = _material_bindings(root, job_id, lod, current_build)
    now = utc_now()
    return PortableMaterialConversionPlan(
        plan_id=f"material.conversion.plan.{conversion_id}",
        job_id=job_id,
        run_id=run_id,
        profile_id=profile.profile_id,
        source=optimization.source,
        profile_artifact=profile_artifact(root, profile),
        optimization_plan=_hashed_artifact(
            root,
            f"optimization.execution.{run_id}",
            "optimization_plan",
            run_root / "execution_plan.json",
        ),
        optimized_blend=_hashed_artifact(
            root,
            f"blend.optimized.{run_id}",
            "blend",
            run_root / "optimized" / "scene.blend",
        ),
        uv_manifest=_hashed_artifact(
            root,
            f"uv.manifest.{run_id}",
            "uv_manifest",
            run_root / "uv_manifest.json",
        ),
        required_material_ids=[item.material_id for item in bindings],
        atlas_policy=PortableAtlasPolicy(
            resolution=resolution,
            margin_px=margin_px,
        ),
        materials=bindings,
        status="approved",
        created_at=now,
        approved_at=now,
        notes=[
            "The explicit command authorizes only run-owned derived material outputs.",
            "Canonical SceneSpec, geometry, materials, textures, and authoring blend "
            "stay read-only.",
        ],
    )


def _require_raw_object(value: Any, label: str) -> dict[str, Any]:
    """Require one Blender evidence field to contain a JSON object."""

    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_raw_list(value: Any, label: str) -> list[dict[str, Any]]:
    """Require one Blender evidence field to contain only JSON objects."""

    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be an array of JSON objects")
    return value


def _surface_factors(value: Any) -> PortableSurfaceFactors:
    """Normalize feature-probed portable Principled factors from Blender evidence."""

    record = value if isinstance(value, dict) else {}
    return PortableSurfaceFactors(
        base_color_factor=tuple(
            float(item)
            for item in record.get("base_color_factor", (1.0, 1.0, 1.0, 1.0))
        ),
        roughness_factor=float(record.get("roughness_factor", 1.0)),
        metallic_factor=float(record.get("metallic_factor", 1.0)),
        emission_factor=tuple(
            float(item)
            for item in record.get("emission_factor", (1.0, 1.0, 1.0))
        ),
        alpha_factor=float(record.get("alpha_factor", 1.0)),
        transmission_factor=float(record.get("transmission_factor", 0.0)),
    )


def _json_fingerprint(value: dict[str, Any]) -> str:
    """Hash one normalized Blender material record when it lacks an explicit digest."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_manifest(
    root: Path,
    final_root: Path,
    staging_root: Path,
    conversion_id: str,
    plan: PortableMaterialConversionPlan,
    raw: dict[str, Any],
) -> PortableMaterialConversionManifest:
    """Turn Blender evidence into the strict global-atlas conversion manifest."""

    if not raw.get("ok"):
        raise RuntimeError("Blender material conversion evidence is unsuccessful")
    expected_plan_sha256 = sha256_file(staging_root / "conversion_plan.json")
    if str(raw.get("conversion_plan_sha256", "")).lower() != expected_plan_sha256:
        raise RuntimeError("Blender conversion evidence has a stale plan hash")
    if str(raw.get("optimized_blend_sha256", "")).lower() != plan.optimized_blend.sha256:
        raise RuntimeError("Blender conversion evidence has a stale optimized blend hash")

    tiles: list[PortableAtlasTile] = []
    for record in _require_raw_list(raw.get("tiles"), "tiles"):
        tiles.append(
            PortableAtlasTile(
                binding_id=str(record["binding_id"]),
                material_id=str(record["material_id"]),
                target_id=str(record.get("target_id") or record.get("semantic_id")),
                derived_object_id=str(
                    record.get("derived_object_id") or record.get("object_name")
                ),
                lod_level=int(record.get("lod_level", 0)),
                uv_set=plan.atlas_policy.uv_set,
                resolution=(
                    plan.atlas_policy.resolution,
                    plan.atlas_policy.resolution,
                ),
                margin_px=plan.atlas_policy.margin_px,
                uv_minimum=tuple(float(item) for item in record["uv_minimum"]),
                uv_maximum=tuple(float(item) for item in record["uv_maximum"]),
                overlap_fraction=(
                    float(record["overlap_fraction"])
                    if record.get("overlap_fraction") is not None
                    else None
                ),
                quality_status=str(record.get("quality_status", "partially_verified")),
                unwrap_method=str(record.get("unwrap_method", "smart_project")),
                repaired_uv_degenerate_face_count=int(
                    record.get("repaired_uv_degenerate_face_count", 0)
                ),
                remaining_uv_degenerate_face_count=int(
                    record.get("remaining_uv_degenerate_face_count", 0)
                ),
                tangent_repair_method=str(
                    record.get("tangent_repair_method", "none")
                ),
                micro_sliver_face_count_before=int(
                    record.get("micro_sliver_face_count_before", 0)
                ),
                remaining_micro_sliver_face_count=int(
                    record.get("remaining_micro_sliver_face_count", 0)
                ),
                tangent_invalid_loop_count_before=int(
                    record.get("tangent_invalid_loop_count_before", 0)
                ),
                tangent_invalid_loop_count_after=int(
                    record.get("tangent_invalid_loop_count_after", 0)
                ),
                bounds_max_abs_delta_m=float(
                    record.get("bounds_max_abs_delta_m", 0.0)
                ),
            )
        )
    tiles.sort(key=lambda item: item.binding_id)

    output_root = staging_root / "textures"
    outputs: list[PortableChannelOutput] = []
    raw_outputs = {
        str(item.get("channel")): item
        for item in _require_raw_list(raw.get("outputs"), "outputs")
    }
    for channel in plan.atlas_policy.required_channels:
        record = raw_outputs.get(channel)
        if record is None:
            raise RuntimeError(f"Blender conversion omitted channel: {channel}")
        candidate = Path(str(record.get("path", output_root / f"{channel}.png"))).resolve()
        try:
            candidate.relative_to(output_root.resolve())
        except ValueError as exc:
            raise RuntimeError(f"Converted channel escaped its staging root: {candidate}") from exc
        expected = output_root / f"{channel}.png"
        if candidate != expected.resolve() or not expected.is_file():
            raise RuntimeError(f"Converted channel path is unexpected: {candidate}")
        digest = sha256_file(expected)
        if str(record.get("sha256", digest)).lower() != digest:
            raise RuntimeError(f"Converted channel hash mismatch: {channel}")
        outputs.append(
            PortableChannelOutput(
                id=f"portable.channel.{conversion_id}.{channel}",
                channel=channel,
                path=job_relative(root, final_root / "textures" / expected.name),
                sha256=digest,
                color_space=(
                    "sRGB"
                    if channel in {"base_color", "emission"}
                    else "Non-Color"
                ),
                resolution=(
                    plan.atlas_policy.resolution,
                    plan.atlas_policy.resolution,
                ),
                material_ids=plan.required_material_ids,
            )
        )

    raw_materials = {
        str(item.get("material_id")): item
        for item in _require_raw_list(raw.get("materials"), "materials")
    }
    entry_tiles: dict[str, list[str]] = {
        material_id: [] for material_id in plan.required_material_ids
    }
    for tile in tiles:
        entry_tiles.setdefault(tile.material_id, []).append(tile.binding_id)
    entries: list[PortableMaterialConversionEntry] = []
    by_id = {item.material_id: item for item in plan.materials}
    for material_id in plan.required_material_ids:
        record = raw_materials.get(material_id)
        if record is None:
            raise RuntimeError(f"Blender conversion omitted material: {material_id}")
        binding = by_id[material_id]
        entries.append(
            PortableMaterialConversionEntry(
                material_id=material_id,
                source_shader_recipe=binding.source_shader_recipe,
                source_material_fingerprint=binding.source_material_fingerprint,
                portable_material_fingerprint=str(
                    record.get("portable_material_fingerprint")
                    or _json_fingerprint(record)
                ),
                mapping_mode=binding.mapping_mode,
                binding_ids=sorted(entry_tiles.get(material_id, [])),
                surface_factors=_surface_factors(record.get("surface_factors")),
                losses=[str(item) for item in record.get("losses", [])],
                warnings=[str(item) for item in record.get("warnings", [])],
                notes=[str(item) for item in record.get("notes", [])],
            )
        )

    portable_blend = staging_root / "converted" / "scene.blend"
    if not portable_blend.is_file():
        raise RuntimeError("Blender conversion did not create converted/scene.blend")
    portable_digest = sha256_file(portable_blend)
    raw_portable = _require_raw_object(raw.get("portable_blend"), "portable_blend")
    if str(raw_portable.get("sha256", portable_digest)).lower() != portable_digest:
        raise RuntimeError("Portable Blender scene hash differs from conversion evidence")
    now = utc_now()
    return PortableMaterialConversionManifest(
        manifest_id=f"material.conversion.{conversion_id}",
        job_id=plan.job_id,
        run_id=plan.run_id,
        profile_id=plan.profile_id,
        source=plan.source,
        plan_artifact=PortableMaterialContractArtifact(
            id=f"material.conversion.plan.{conversion_id}",
            kind="portable_material_conversion_plan",
            path=job_relative(root, final_root / "conversion_plan.json"),
            sha256=expected_plan_sha256,
        ),
        profile_artifact=plan.profile_artifact,
        optimization_plan=plan.optimization_plan,
        optimized_blend=plan.optimized_blend,
        uv_manifest=plan.uv_manifest,
        atlas_policy=plan.atlas_policy,
        required_material_ids=plan.required_material_ids,
        converted_material_ids=plan.required_material_ids,
        missing_material_ids=[],
        entries=entries,
        tiles=tiles,
        outputs=outputs,
        portable_blend=HashedArtifact(
            id=f"blend.portable-materials.{conversion_id}",
            kind="blend",
            path=job_relative(root, final_root / "converted" / "scene.blend"),
            sha256=portable_digest,
        ),
        status="complete",
        created_at=now,
        completed_at=now,
        notes=[
            "Cross-object atlas tile bounds are deterministic and non-overlapping.",
            "Smart-project intra-object island overlap remains explicitly reported by "
            "Blender evidence.",
            *[str(item) for item in raw.get("notes", [])],
        ],
    )


def convert_portable_materials(
    job_id: str,
    *,
    profile_id: str,
    run_id: str,
    conversion_id: str,
    resolution: int = 2048,
    margin_px: int = 16,
    render_device: str = "auto",
) -> PortableMaterialConversionManifest:
    """Bake one immutable global PBR atlas and publish a separate portable scene."""

    if not load_feature_config().features.portable_asset_core:
        raise RuntimeError("portable_asset_core is disabled in cbm.toml")
    if render_device not in {"auto", "cpu", "gpu"}:
        raise ValueError("render_device must be auto, cpu, or gpu")
    root = job_dir(job_id)
    run_root = run_directory(root, run_id)
    optimization = load_model(run_root / "optimization_plan.json", OptimizationPlan)
    if optimization.status != "complete":
        raise RuntimeError(f"Optimization run is not complete: {run_id}")
    profile = load_asset_profile(root, profile_id)
    if optimization.profile_id != profile.profile_id:
        raise ValueError("Optimization plan and conversion profiles do not match")
    if resolution > profile.textures.maximum_resolution:
        raise ValueError(
            "conversion resolution exceeds the selected AssetProfile maximum"
        )
    lod = load_model(run_root / "lod_manifest.json", LODManifest)
    uv = load_model(run_root / "uv_manifest.json", UVManifest)
    if (
        lod.source != optimization.source
        or uv.source != optimization.source
        or lod.run_id != run_id
        or uv.run_id != run_id
    ):
        raise RuntimeError("Optimization manifests are stale or belong to another run")
    require_unchanged_source(optimization.source, root, job_id)
    current_build = collect_source_build_provenance(root, job_id)
    if current_build["fingerprint"] != optimization.source.build_fingerprint:
        raise RuntimeError("Current material build differs from the optimization source")

    final_root = material_conversion_directory(root, run_id, conversion_id)
    if final_root.exists():
        raise FileExistsError(f"Portable material conversion already exists: {final_root}")
    parent = final_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging_root = _material_conversion_staging_directory(parent)
    staging_root.mkdir(parents=False, exist_ok=False)
    plan = _conversion_plan(
        root,
        job_id,
        run_id,
        conversion_id,
        profile,
        optimization,
        lod,
        current_build,
        resolution=resolution,
        margin_px=margin_px,
    )
    plan_path = staging_root / "conversion_plan.json"
    write_model(plan_path, plan)
    evidence_path = staging_root / "conversion_evidence.json"
    output_blend = staging_root / "converted" / "scene.blend"
    texture_root = staging_root / "textures"
    args = [
        "--job-root",
        str(root),
        "--conversion-plan",
        str(plan_path),
        "--profile",
        str(profile_path(root, profile_id)),
        "--output-blend",
        str(output_blend),
        "--output-evidence",
        str(evidence_path),
        "--output-texture-root",
        str(texture_root),
        "--resolution",
        str(resolution),
        "--margin-px",
        str(margin_px),
        "--render-device",
        render_device,
        "--source-blend-sha256",
        plan.optimized_blend.sha256,
        "--expected-plan-sha256",
        sha256_file(plan_path),
    ]
    run_blender(
        "convert_portable_materials.py",
        args,
        blend_file=run_root / "optimized" / "scene.blend",
    )
    if not evidence_path.is_file():
        raise RuntimeError("Blender material conversion produced no evidence JSON")
    raw = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Blender material conversion evidence must be a JSON object")
    require_unchanged_source(optimization.source, root, job_id)
    if sha256_file(run_root / "optimized" / "scene.blend") != plan.optimized_blend.sha256:
        raise RuntimeError("Optimized input blend changed during material conversion")
    manifest = _normalize_manifest(
        root,
        final_root,
        staging_root,
        conversion_id,
        plan,
        raw,
    )
    write_model(staging_root / "conversion_manifest.json", manifest)
    os.replace(staging_root, final_root)
    return manifest


def load_portable_material_conversion(
    root: Path,
    run_id: str,
    conversion_id: str,
    *,
    profile: AssetProfile,
    optimization: OptimizationPlan,
) -> MaterialConversionSelection:
    """Load and hash-verify one explicit immutable conversion for packaging."""

    directory = material_conversion_directory(root, run_id, conversion_id)
    plan = load_model(
        directory / "conversion_plan.json",
        PortableMaterialConversionPlan,
    )
    manifest = load_model(
        directory / "conversion_manifest.json",
        PortableMaterialConversionManifest,
    )
    if (
        plan.job_id != optimization.job_id
        or plan.run_id != run_id
        or plan.profile_id != profile.profile_id
        or plan.source != optimization.source
        or manifest.job_id != optimization.job_id
        or manifest.run_id != run_id
        or manifest.profile_id != profile.profile_id
        or manifest.source != optimization.source
        or manifest.status != "complete"
    ):
        raise RuntimeError("Portable material conversion does not match the package run")
    plan_path = directory / "conversion_plan.json"
    if manifest.plan_artifact.sha256 != sha256_file(plan_path):
        raise RuntimeError("Portable material conversion plan hash changed")
    if manifest.plan_artifact.path != job_relative(root, plan_path):
        raise RuntimeError("Portable material conversion plan path is unexpected")
    for artifact, label in (
        (manifest.profile_artifact, "asset profile"),
        (manifest.optimization_plan, "optimization plan"),
        (manifest.optimized_blend, "optimized blend"),
        (manifest.uv_manifest, "UV manifest"),
    ):
        path = resolve_inside(root, artifact.path, label)
        if not path.is_file() or sha256_file(path) != artifact.sha256:
            raise RuntimeError(f"Portable material conversion input changed: {label}")
    if manifest.profile_artifact != profile_artifact(root, profile):
        raise RuntimeError("Portable material conversion AssetProfile is stale")
    portable_blend_artifact = manifest.portable_blend
    if portable_blend_artifact is None:
        raise RuntimeError("Complete material conversion has no portable blend")
    portable_blend = resolve_inside(
        root,
        portable_blend_artifact.path,
        "portable material scene",
    )
    if (
        not portable_blend.is_file()
        or sha256_file(portable_blend) != portable_blend_artifact.sha256
    ):
        raise RuntimeError("Portable material scene is missing or changed")
    for output in manifest.outputs:
        path = resolve_inside(root, output.path, f"portable {output.channel} channel")
        if not path.is_file() or sha256_file(path) != output.sha256:
            raise RuntimeError(f"Portable material channel is missing or changed: {output.channel}")
    require_unchanged_source(optimization.source, root, optimization.job_id)
    return MaterialConversionSelection(
        conversion_id=conversion_id,
        directory=directory,
        plan=plan,
        manifest=manifest,
        portable_blend=portable_blend,
    )
