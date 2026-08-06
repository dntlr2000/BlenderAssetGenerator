"""Host-side planning, approval, normalization, and validation for external static assets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..blender_artifacts import file_exists, stable_json_digest, write_json_atomic
from ..blender_runner import run_blender
from ..config import get_settings
from ..materials.models import (
    MappingSpec,
    MaterialPlan,
    MaterialPlanItem,
    ShaderRecipe,
    SurfaceSpec,
)
from ..workspace import SUBDIRS, job_dir, metadata_path, sha256_file, validate_new_job_id
from .models import (
    ExternalAssetIntakeApproval,
    ExternalAssetIntakePlan,
    ExternalAssetIntakeValidation,
    ExternalAssetManifest,
    ExternalIntakeArtifact,
    ExternalMaterialPlan,
    ExternalNormalizationPolicy,
    ExternalNormalizationReceipt,
    ExternalNormalizedMaterial,
    ExternalNormalizedObject,
    ExternalObjectPlan,
)

_PLAN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SOURCE_FORMATS = {".blend": "blend", ".fbx": "fbx", ".glb": "glb"}


def _utc_now() -> datetime:
    """Return a timezone-aware timestamp for immutable intake evidence."""

    return datetime.now(UTC)


def _new_plan_id() -> str:
    """Create one collision-resistant filesystem-safe intake plan identity."""

    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ").lower()
    return f"intake-{stamp}-{uuid4().hex[:8]}"


def _validate_plan_id(plan_id: str) -> str:
    """Reject path-like or uppercase plan identifiers."""

    if not _PLAN_ID_RE.fullmatch(plan_id):
        raise ValueError("plan_id must match [a-z0-9][a-z0-9_-]{0,63}")
    return plan_id


def _job_relative(root: Path, path: Path) -> str:
    """Return a POSIX job-relative path after containment verification."""

    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"External intake path escaped its job: {path}") from exc


def _resolve_job_path(root: Path, value: str, label: str) -> Path:
    """Resolve one contract path and reject absolute or escaping values."""

    if not value or "\\" in value:
        raise ValueError(f"{label} must use a non-empty POSIX job-relative path")
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{label} escaped the job root")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escaped the job root") from exc
    return resolved


def _artifact(
    root: Path,
    artifact_id: str,
    kind: str,
    path: Path,
    *,
    source_names: list[str] | None = None,
) -> ExternalIntakeArtifact:
    """Bind one existing contained file to its exact intake role and digest."""

    if not file_exists(path):
        raise FileNotFoundError(path)
    return ExternalIntakeArtifact(
        id=artifact_id,
        kind=kind,
        path=_job_relative(root, path),
        sha256=sha256_file(path),
        source_names=sorted(set(source_names or [])),
    )


def _write_model(path: Path, model: Any) -> Path:
    """Persist one strict model atomically with a stable trailing newline."""

    write_json_atomic(path, model.model_dump(mode="json"))
    return path


def _create_subdirs(root: Path) -> None:
    """Create the shared workspace skeleton plus external-intake directories."""

    for subdir in SUBDIRS:
        (root / subdir).mkdir(parents=True, exist_ok=True)
    (root / "intake" / "plans").mkdir(parents=True, exist_ok=True)
    (root / "intake" / "history").mkdir(parents=True, exist_ok=True)
    (root / "input" / "external_asset" / "dependencies").mkdir(
        parents=True,
        exist_ok=True,
    )


def _slug(value: str, fallback: str) -> str:
    """Normalize one source name into a stable ASCII semantic component."""

    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", ".", normalized.casefold()).strip(".")
    return slug[:80] or fallback


def _unique_ids(names: list[str], prefix: str) -> dict[str, str]:
    """Assign deterministic semantic IDs while resolving normalized-name collisions."""

    result: dict[str, str] = {}
    used: set[str] = set()
    for index, name in enumerate(sorted(names), start=1):
        component = _slug(name, f"item{index:03d}")
        base = component if component == prefix or component.startswith(f"{prefix}.") else (
            f"{prefix}.{component}"
        )
        candidate = base
        if candidate in used:
            suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
            candidate = f"{base}.{suffix}"
        while candidate in used:
            candidate = f"{base}.{index:03d}"
        used.add(candidate)
        result[name] = candidate
    return result


def _source_format(path: Path) -> str:
    """Map the supported static input suffix to its normalized format identity."""

    source_format = _SOURCE_FORMATS.get(path.suffix.casefold())
    if source_format is None:
        raise ValueError("External Static Asset Intake supports .blend, .fbx, and .glb")
    return source_format


def _volume(record: dict[str, Any]) -> float:
    """Calculate a bounded object-volume proxy for deterministic primary-role selection."""

    dimensions = record.get("dimensions", [0.0, 0.0, 0.0])
    try:
        values = [max(0.0, float(item)) for item in dimensions]
    except (TypeError, ValueError):
        return 0.0
    return values[0] * values[1] * values[2] if len(values) == 3 else 0.0


def _qa_roles(records: list[dict[str, Any]]) -> dict[str, str]:
    """Classify the largest object as primary and obvious context by stable name tokens."""

    if not records:
        return {}
    primary_name = max(records, key=lambda item: (_volume(item), str(item.get("name"))))[
        "name"
    ]
    roles: dict[str, str] = {}
    for record in records:
        name = str(record["name"])
        lowered = name.casefold()
        if name == primary_name:
            role = "primary"
        elif any(token in lowered for token in ("ground", "floor", "backdrop", "background")):
            role = "ground_background"
        elif any(
            token in lowered
            for token in ("rock", "grass", "plant", "debris", "weed", "decoration")
        ):
            role = "decorative"
        else:
            role = "supporting"
        roles[name] = role
    return roles


def _object_material_groups(record: dict[str, Any]) -> list[tuple[str, list[int]]]:
    """Group evaluated source material slots into one portable submesh per material."""

    grouped: dict[str, list[int]] = {}
    for item in record.get("material_slots", []):
        if not isinstance(item, dict) or int(item.get("polygon_count", 0)) <= 0:
            continue
        name = str(item.get("material_name") or "__cbm_default__")
        index = item.get("material_index")
        if index is None:
            grouped.setdefault(name, [])
        else:
            grouped.setdefault(name, []).append(int(index))
    if not grouped:
        return [("__cbm_default__", [])]
    return [
        (name, sorted(set(indices)))
        for name, indices in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _external_object_plans(
    records: list[dict[str, Any]],
    material_ids: dict[str, str],
    roles: dict[str, str],
) -> list[ExternalObjectPlan]:
    """Expand multi-material sources into stable single-material semantic submeshes."""

    base_ids = _unique_ids([str(item["name"]) for item in records], "asset")
    partitions: dict[str, list[tuple[str, list[int], str]]] = {}
    used_semantic_ids: set[str] = set()
    for record in records:
        source_name = str(record["name"])
        groups = _object_material_groups(record)
        entries: list[tuple[str, list[int], str]] = []
        for index, (material_name, indices) in enumerate(groups, start=1):
            semantic_id = base_ids[source_name]
            if len(groups) > 1:
                component = _slug(material_ids[material_name], f"part{index:03d}")
                semantic_id = f"{semantic_id}.part.{component}"
            candidate = semantic_id
            counter = index
            while candidate in used_semantic_ids:
                counter += 1
                candidate = f"{semantic_id}.{counter:03d}"
            used_semantic_ids.add(candidate)
            entries.append((material_name, indices, candidate))
        partitions[source_name] = entries

    primary_by_source = {
        source_name: entries[0][2] for source_name, entries in partitions.items()
    }
    plans: list[ExternalObjectPlan] = []
    for record in records:
        source_name = str(record["name"])
        source_parent = next(
            (
                primary_by_source[name]
                for name in record.get("parent_chain", [])
                if name in primary_by_source
            ),
            None,
        )
        for index, (material_name, indices, semantic_id) in enumerate(
            partitions[source_name]
        ):
            plans.append(
                ExternalObjectPlan(
                    source_name=source_name,
                    source_material_indices=indices,
                    semantic_id=semantic_id,
                    parent_semantic_id=(
                        source_parent if index == 0 else partitions[source_name][0][2]
                    ),
                    object_type=str(record["type"]),
                    material_ids=[material_ids[material_name]],
                    qa_role=roles[source_name],
                )
            )
    return plans


def _sanitize_inspection_and_copy_dependencies(
    temp_root: Path,
    raw: dict[str, Any],
) -> tuple[dict[str, Any], list[ExternalIntakeArtifact], dict[str, str]]:
    """Copy unpacked image dependencies and remove every absolute host path from evidence."""

    grouped: dict[str, set[str]] = {}
    for material in raw.get("materials", []):
        if not isinstance(material, dict):
            continue
        for image in material.get("images", []):
            if not isinstance(image, dict) or image.get("packed"):
                continue
            resolved = str(image.get("resolved_path") or "")
            if resolved:
                grouped.setdefault(resolved, set()).add(str(image.get("image_name") or ""))

    dependencies: list[ExternalIntakeArtifact] = []
    dependency_by_image: dict[str, str] = {}
    dependency_root = temp_root / "input" / "external_asset" / "dependencies"
    for resolved, image_names in sorted(grouped.items()):
        source = Path(resolved).expanduser().resolve()
        if not file_exists(source):
            continue
        digest = sha256_file(source)
        suffix = source.suffix.casefold() or ".bin"
        target = dependency_root / f"dep-{digest[:16]}{suffix}"
        if not target.exists():
            shutil.copy2(source, target)
        if sha256_file(target) != digest:
            raise RuntimeError(f"Copied external dependency hash mismatch: {source.name}")
        artifact = _artifact(
            temp_root,
            f"external.dependency.{digest[:16]}",
            "external_dependency",
            target,
            source_names=sorted(name for name in image_names if name),
        )
        dependencies.append(artifact)
        for image_name in image_names:
            if image_name:
                dependency_by_image[image_name] = artifact.id

    sanitized = json.loads(json.dumps(raw))
    by_id = {artifact.id: artifact for artifact in dependencies}
    for material in sanitized.get("materials", []):
        if not isinstance(material, dict):
            continue
        for image in material.get("images", []):
            if not isinstance(image, dict):
                continue
            image_name = str(image.get("image_name") or "")
            dependency_id = dependency_by_image.get(image_name)
            image.pop("resolved_path", None)
            image["dependency_id"] = dependency_id
            image["dependency_path"] = (
                by_id[dependency_id].path if dependency_id in by_id else None
            )
    return sanitized, dependencies, dependency_by_image


def _material_contracts(
    root: Path,
    plan_root: Path,
    job_id: str,
    materials: list[ExternalMaterialPlan],
    *,
    blocked: bool,
) -> tuple[ExternalIntakeArtifact, list[ExternalIntakeArtifact]]:
    """Create hash-bound V0.5 bridge contracts for baking preserved external node graphs."""

    contract_root = plan_root / "contracts"
    contract_root.mkdir(parents=True, exist_ok=False)
    recipe_artifacts: list[ExternalIntakeArtifact] = []
    plan_items: list[MaterialPlanItem] = []
    for material in materials:
        recipe_path = contract_root / "m" / material.material_id / "shader_recipe.json"
        recipe = ShaderRecipe(
            material_id=material.material_id,
            family="standard_pbr",
            surface=material.surface,
            mapping=MappingSpec(mode=material.mapping_mode, uv_set="UVMap"),
            layers=[],
            texture_manifest=None,
            blender_master=True,
            bake_required=True,
            assumptions=[
                "The normalized master .blend preserves the evaluated external node graph.",
                "This recipe records portable factors and mapping only; V0.7 bakes the actual "
                "preserved Blender material into raw PBR channels.",
            ],
        )
        recipe_path.parent.mkdir(parents=True, exist_ok=True)
        _write_model(recipe_path, recipe)
        recipe_artifacts.append(
            _artifact(
                root,
                f"external.shader_recipe.{material.material_id}",
                "shader_recipe",
                recipe_path,
            )
        )
        plan_items.append(
            MaterialPlanItem(
                material_id=material.material_id,
                label=material.source_name,
                shader_family="standard_pbr",
                texture_strategy="none",
                mapping=MappingSpec(mode=material.mapping_mode, uv_set="UVMap"),
                shader_recipe=f"materials/{material.material_id}/shader_recipe.json",
                export_profiles=["blender_eevee", "blender_cycles", "gltf_pbr"],
                evidence_status="observed",
                confidence=1.0,
                notes=[
                    "External node graph is preserved in blender/scene.blend and must be baked "
                    "for engine-neutral delivery."
                ],
            )
        )
    material_plan = MaterialPlan(
        job_id=job_id,
        scene_spec_path="intake/external_asset_manifest.json",
        stage="scaffold" if blocked or not plan_items else "authored",
        materials=plan_items,
        global_notes=[
            "External Static Asset Intake bridge; no SceneSpec geometry was fabricated.",
            "Portable delivery must use the V0.7 material conversion and raw PBR package.",
        ],
    )
    material_plan_path = contract_root / "material_plan.json"
    _write_model(material_plan_path, material_plan)
    return (
        _artifact(
            root,
            "external.candidate.material_plan",
            "material_plan",
            material_plan_path,
        ),
        recipe_artifacts,
    )


def plan_external_static_asset_intake(
    job_id: str,
    source_path: Path,
    *,
    plan_id: str | None = None,
) -> ExternalAssetIntakePlan:
    """Inspect a source read-only, copy exact evidence, and publish a new immutable plan."""

    validate_new_job_id(job_id)
    selected_plan_id = _validate_plan_id(plan_id or _new_plan_id())
    source = source_path.expanduser().resolve()
    if not file_exists(source):
        raise FileNotFoundError(source)
    source_format = _source_format(source)
    workspace = get_settings().workspace_root
    workspace.mkdir(parents=True, exist_ok=True)
    final_root = workspace / job_id
    if final_root.exists():
        raise FileExistsError(
            f"Job already exists and was not modified: {final_root}. External intake requires "
            "a new lowercase job_id."
        )
    temp_root = workspace / f".{job_id}.creating-{uuid4().hex}"
    _create_subdirs(temp_root)
    try:
        source_sha256 = sha256_file(source)
        source_target = temp_root / "input" / "external_asset" / f"source{source.suffix.casefold()}"
        plan_root = temp_root / "intake" / "plans" / selected_plan_id
        plan_root.mkdir(parents=True, exist_ok=False)
        raw_path = plan_root / ".inspection.raw.json"
        run_blender(
            "inspect_external_static_asset.py",
            [
                "--source",
                str(source),
                "--source-format",
                source_format,
                "--expected-source-sha256",
                source_sha256,
                "--output",
                str(raw_path),
            ],
            blend_file=source if source_format == "blend" else None,
            factory_startup=source_format != "blend",
            disable_autoexec=True,
        )
        if sha256_file(source) != source_sha256:
            raise RuntimeError("External source changed while Blender inspected it")
        shutil.copy2(source, source_target)
        if sha256_file(source_target) != source_sha256:
            raise RuntimeError("Copied external source hash differs from inspected evidence")
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("External Blender inspection root must be an object")
        sanitized, dependencies, dependency_by_image = (
            _sanitize_inspection_and_copy_dependencies(temp_root, raw)
        )
        inspection_path = plan_root / "inspection.json"
        write_json_atomic(inspection_path, sanitized)
        raw_path.unlink(missing_ok=True)

        raw_objects = [
            item
            for item in sanitized.get("objects", [])
            if isinstance(item, dict) and not bool(item.get("hide_render"))
        ]
        used_material_names = {
            material_name
            for item in raw_objects
            for material_name, _indices in _object_material_groups(item)
            if material_name != "__cbm_default__"
        }
        raw_materials = [
            item
            for item in sanitized.get("materials", [])
            if isinstance(item, dict) and str(item.get("name")) in used_material_names
        ]
        material_names = [str(item["name"]) for item in raw_materials]
        if any(
            any(name == "__cbm_default__" for name, _indices in _object_material_groups(item))
            for item in raw_objects
        ):
            material_names.append("__cbm_default__")
        material_ids = _unique_ids(material_names, "mat")
        if "__cbm_default__" in material_ids:
            material_ids["__cbm_default__"] = "mat.default"
        roles = _qa_roles(raw_objects)
        object_plans = _external_object_plans(raw_objects, material_ids, roles)

        uv_by_material: dict[str, list[bool]] = {name: [] for name in material_names}
        for item in raw_objects:
            for name, _indices in _object_material_groups(item):
                if name in uv_by_material:
                    uv_by_material[name].append(bool(item.get("has_uv0")))
        material_plans: list[ExternalMaterialPlan] = []
        for item in raw_materials:
            name = str(item["name"])
            dependency_ids = sorted(
                {
                    dependency_by_image[image_name]
                    for image_name in (
                        str(image.get("image_name") or "")
                        for image in item.get("images", [])
                        if isinstance(image, dict)
                    )
                    if image_name in dependency_by_image
                }
            )
            has_uv = uv_by_material.get(name, [])
            material_plans.append(
                ExternalMaterialPlan(
                    source_name=name,
                    material_id=material_ids[name],
                    node_fingerprint=str(item["node_fingerprint"]),
                    mapping_mode="uv" if has_uv and all(has_uv) else "object",
                    surface=SurfaceSpec.model_validate(item.get("surface", {})),
                    image_dependency_ids=dependency_ids,
                    limitations=[
                        "Arbitrary Blender nodes are not destination-runtime portable and will "
                        "be baked to raw PBR channels during V0.7 conversion."
                    ],
                )
            )
        if "__cbm_default__" in material_ids:
            material_plans.append(
                ExternalMaterialPlan(
                    source_name="__cbm_default__",
                    material_id="mat.default",
                    node_fingerprint=stable_json_digest(
                        {"kind": "neutral_default", "base_color": [0.8, 0.8, 0.8, 1.0]}
                    ),
                    mapping_mode="object",
                    surface=SurfaceSpec(),
                    limitations=["A neutral fallback replaced a missing source material."],
                )
            )

        blockers = [str(item) for item in sanitized.get("blockers", [])]
        if not raw_objects:
            blockers.append("No render-visible mesh or curve objects are eligible for intake.")
        candidate_plan, candidate_recipes = _material_contracts(
            temp_root,
            plan_root,
            job_id,
            material_plans,
            blocked=bool(blockers),
        )
        unit_record = sanitized.get("units", {})
        source_unit_scale = float(
            unit_record.get("scale_length", 1.0)
            if isinstance(unit_record, dict)
            else 1.0
        )
        warnings = [str(item) for item in sanitized.get("warnings", [])]
        if source_unit_scale != 1.0:
            warnings.append(
                "Normalization will convert source coordinates to meters with scale factor "
                f"{source_unit_scale:.12g}."
            )
        plan = ExternalAssetIntakePlan(
            plan_id=selected_plan_id,
            job_id=job_id,
            source=_artifact(
                temp_root,
                "external.source.primary",
                "external_source",
                source_target,
            ),
            source_format=source_format,
            dependencies=dependencies,
            inspection=_artifact(
                temp_root,
                "external.inspection.primary",
                "external_inspection",
                inspection_path,
            ),
            candidate_material_plan=candidate_plan,
            candidate_shader_recipes=candidate_recipes,
            normalization=ExternalNormalizationPolicy(
                source_unit_scale_to_meters=source_unit_scale
            ),
            objects=object_plans,
            materials=material_plans,
            blockers=blockers,
            warnings=warnings,
            status="blocked" if blockers else "awaiting_user_approval",
            created_at=_utc_now(),
        )
        plan_path = plan_root / "plan.json"
        _write_model(plan_path, plan)
        final_source = final_root / plan.source.path
        job_metadata = {
            "job_id": job_id,
            "job_kind": "external_static_asset",
            "mode": "external_static_asset",
            "project_version_created": "0.9.0",
            "created_at": _utc_now().isoformat(),
            "updated_at": _utc_now().isoformat(),
            "sources": [
                {
                    "kind": "external_static_asset",
                    "path": metadata_path(final_source),
                    "sha256": plan.source.sha256,
                },
                *[
                    {
                        "kind": "external_dependency",
                        "path": metadata_path(final_root / dependency.path),
                        "sha256": dependency.sha256,
                    }
                    for dependency in dependencies
                ],
            ],
            "external_intake_plan": f"intake/plans/{selected_plan_id}/plan.json",
            "external_intake_plan_sha256": sha256_file(plan_path),
        }
        write_json_atomic(temp_root / "job.json", job_metadata)
        os.replace(temp_root, final_root)
        return plan
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


def _plan_path(root: Path, plan_id: str) -> Path:
    """Resolve one immutable external-intake plan path."""

    return root / "intake" / "plans" / _validate_plan_id(plan_id) / "plan.json"


def _load_plan(root: Path, plan_id: str) -> ExternalAssetIntakePlan:
    """Load one strict external-intake plan from its immutable run directory."""

    path = _plan_path(root, plan_id)
    if not file_exists(path):
        raise FileNotFoundError(path)
    return ExternalAssetIntakePlan.model_validate_json(path.read_text(encoding="utf-8"))


def approve_external_static_asset_intake(
    job_id: str,
    plan_id: str,
    plan_sha256: str,
    *,
    approval_note: str,
) -> ExternalAssetIntakeApproval:
    """Record exact user approval without normalizing or consuming it."""

    root = job_dir(job_id)
    plan = _load_plan(root, plan_id)
    plan_path = _plan_path(root, plan_id)
    actual_plan_sha256 = sha256_file(plan_path)
    if actual_plan_sha256 != plan_sha256.casefold():
        raise RuntimeError("External intake plan SHA-256 differs from the approved value")
    if plan.job_id != job_id or plan.status != "awaiting_user_approval":
        raise RuntimeError("External intake plan is blocked or belongs to another job")
    source = _resolve_job_path(root, plan.source.path, "external source")
    if not file_exists(source) or sha256_file(source) != plan.source.sha256:
        raise RuntimeError("External source changed after intake planning")
    _verify_plan_artifacts(root, plan)
    approval_path = plan_path.parent / "approval.json"
    if approval_path.exists():
        raise FileExistsError(f"External intake approval already exists: {approval_path}")
    approval = ExternalAssetIntakeApproval(
        approval_id=f"approval.{plan_id}",
        job_id=job_id,
        plan_id=plan_id,
        plan_sha256=actual_plan_sha256,
        source_sha256=plan.source.sha256,
        approval_note=approval_note,
        approved_at=_utc_now(),
    )
    _write_model(approval_path, approval)
    return approval


def _verify_plan_artifacts(root: Path, plan: ExternalAssetIntakePlan) -> None:
    """Fail closed when immutable inputs or strict candidate contracts changed."""

    artifacts = [
        plan.source,
        *plan.dependencies,
        plan.inspection,
        plan.candidate_material_plan,
        *plan.candidate_shader_recipes,
    ]
    for artifact in artifacts:
        path = _resolve_job_path(root, artifact.path, artifact.kind)
        if not file_exists(path) or sha256_file(path) != artifact.sha256:
            raise RuntimeError(
                f"External intake artifact is stale or missing: {artifact.path}"
            )
    material_plan_path = _resolve_job_path(
        root,
        plan.candidate_material_plan.path,
        "candidate MaterialPlan",
    )
    material_plan = MaterialPlan.model_validate_json(
        material_plan_path.read_text(encoding="utf-8")
    )
    expected_material_ids = [item.material_id for item in plan.materials]
    if material_plan.job_id != plan.job_id or [
        item.material_id for item in material_plan.materials
    ] != expected_material_ids:
        raise RuntimeError("Candidate MaterialPlan does not exactly match the intake plan")
    if plan.status == "awaiting_user_approval" and material_plan.stage != "authored":
        raise RuntimeError("Approvable intake requires an authored candidate MaterialPlan")
    recipe_by_id: dict[str, ExternalIntakeArtifact] = {}
    for artifact in plan.candidate_shader_recipes:
        prefix = "external.shader_recipe."
        if not artifact.id.startswith(prefix):
            raise RuntimeError("Candidate ShaderRecipe artifact ID has an invalid role")
        material_id = artifact.id[len(prefix) :]
        if material_id in recipe_by_id:
            raise RuntimeError(f"Duplicate candidate ShaderRecipe: {material_id}")
        recipe_by_id[material_id] = artifact
        recipe_path = _resolve_job_path(root, artifact.path, "candidate ShaderRecipe")
        recipe = ShaderRecipe.model_validate_json(recipe_path.read_text(encoding="utf-8"))
        if recipe.material_id != material_id or not recipe.bake_required:
            raise RuntimeError(
                f"Candidate ShaderRecipe is not a bake-bound material bridge: {material_id}"
            )
    if set(recipe_by_id) != set(expected_material_ids):
        raise RuntimeError("Candidate ShaderRecipe coverage differs from intake materials")


def _external_build_payload(
    plan: ExternalAssetIntakePlan,
    plan_sha256: str,
    material_plan_sha256: str,
    recipe_sha256: dict[str, str],
) -> tuple[dict[str, Any], str, str]:
    """Derive stable external source-contract and Blender build fingerprints."""

    source_contract = {
        "source_kind": "external_static_asset",
        "job_id": plan.job_id,
        "source": plan.source.model_dump(mode="json"),
        "dependencies": [item.model_dump(mode="json") for item in plan.dependencies],
        "intake_plan_sha256": plan_sha256,
        "candidate_material_plan_sha256": plan.candidate_material_plan.sha256,
        "candidate_shader_recipe_sha256": {
            item.id: item.sha256 for item in plan.candidate_shader_recipes
        },
        "objects": [item.model_dump(mode="json") for item in plan.objects],
        "materials": [item.model_dump(mode="json") for item in plan.materials],
    }
    source_contract_fingerprint = stable_json_digest(source_contract)
    material_records = {
        material.material_id: {
            "shader_recipe_path": f"materials/{material.material_id}/shader_recipe.json",
            "shader_recipe_sha256": recipe_sha256[material.material_id],
            "texture_manifest_path": None,
            "texture_manifest_sha256": None,
            "texture_channels": {},
            "mapping_mode": material.mapping_mode,
            "external_node_fingerprint": material.node_fingerprint,
            "fingerprint": stable_json_digest(
                {
                    "material_id": material.material_id,
                    "node_fingerprint": material.node_fingerprint,
                    "recipe_sha256": recipe_sha256[material.material_id],
                    "mapping_mode": material.mapping_mode,
                }
            ),
        }
        for material in plan.materials
    }
    build = {
        "source_kind": "external_static_asset",
        "job_id": plan.job_id,
        "scene_spec_sha256": None,
        "geometry_payloads_sha256": {},
        "camera_fingerprint": stable_json_digest(
            {"source_kind": "external_static_asset", "camera_independent": True}
        ),
        "external_source_sha256": plan.source.sha256,
        "intake_plan_sha256": plan_sha256,
        "source_contract_fingerprint": source_contract_fingerprint,
        "material_plan_path": "analysis/material_plan.json",
        "material_plan_sha256": material_plan_sha256,
        "materials": material_records,
    }
    fingerprint = stable_json_digest(build)
    build["fingerprint"] = fingerprint
    return build, source_contract_fingerprint, fingerprint


def collect_external_build_provenance(root: Path, job_id: str) -> dict[str, Any]:
    """Recompute current external build provenance from exact manifest-bound inputs."""

    manifest_path = root / "intake" / "external_asset_manifest.json"
    if not file_exists(manifest_path):
        raise FileNotFoundError(manifest_path)
    manifest = ExternalAssetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.job_id != job_id:
        raise RuntimeError("External asset manifest job_id does not match its workspace")
    plan_path = _resolve_job_path(root, manifest.intake_plan.path, "intake plan")
    if sha256_file(plan_path) != manifest.intake_plan.sha256:
        raise RuntimeError("External intake plan differs from the manifest binding")
    plan = ExternalAssetIntakePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    _verify_plan_artifacts(root, plan)
    if (
        manifest.source != plan.source
        or manifest.dependencies != plan.dependencies
        or manifest.source_format != plan.source_format
    ):
        raise RuntimeError("External manifest source evidence differs from the intake plan")
    approval_path = _resolve_job_path(root, manifest.intake_approval.path, "intake approval")
    if (
        not file_exists(approval_path)
        or sha256_file(approval_path) != manifest.intake_approval.sha256
    ):
        raise RuntimeError("External intake approval differs from the manifest binding")
    approval = ExternalAssetIntakeApproval.model_validate_json(
        approval_path.read_text(encoding="utf-8")
    )
    if (
        not approval.used
        or approval.job_id != job_id
        or approval.plan_id != plan.plan_id
        or approval.plan_sha256 != manifest.intake_plan.sha256
        or approval.source_sha256 != manifest.source.sha256
    ):
        raise RuntimeError("External intake approval was not consumed by this exact plan")
    material_plan_path = _resolve_job_path(root, manifest.material_plan.path, "material plan")
    if sha256_file(material_plan_path) != manifest.material_plan.sha256:
        raise RuntimeError("External canonical MaterialPlan changed")
    material_plan = MaterialPlan.model_validate_json(
        material_plan_path.read_text(encoding="utf-8")
    )
    if material_plan.job_id != job_id or [
        item.material_id for item in material_plan.materials
    ] != [item.material_id for item in manifest.materials]:
        raise RuntimeError("External canonical MaterialPlan identity coverage changed")
    recipe_hashes: dict[str, str] = {}
    for material in manifest.materials:
        path = _resolve_job_path(root, material.shader_recipe.path, "shader recipe")
        if sha256_file(path) != material.shader_recipe.sha256:
            raise RuntimeError(f"External shader recipe changed: {material.material_id}")
        recipe_hashes[material.material_id] = material.shader_recipe.sha256
    build, source_contract, fingerprint = _external_build_payload(
        plan,
        manifest.intake_plan.sha256,
        manifest.material_plan.sha256,
        recipe_hashes,
    )
    if source_contract != manifest.source_contract_fingerprint:
        raise RuntimeError("External source-contract fingerprint changed")
    if fingerprint != manifest.build_fingerprint:
        raise RuntimeError("External build fingerprint changed")
    normalized_blend_path = _resolve_job_path(
        root,
        manifest.normalized_blend.path,
        "normalized blend",
    )
    evidence_path = _resolve_job_path(
        root,
        manifest.normalization_evidence.path,
        "normalization evidence",
    )
    if (
        not file_exists(normalized_blend_path)
        or sha256_file(normalized_blend_path) != manifest.normalized_blend.sha256
        or not file_exists(evidence_path)
        or sha256_file(evidence_path) != manifest.normalization_evidence.sha256
    ):
        raise RuntimeError("External normalized blend or evidence changed")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        not isinstance(evidence, dict)
        or not evidence.get("ok")
        or evidence.get("source_sha256") != manifest.source.sha256
        or evidence.get("plan_sha256") != manifest.intake_plan.sha256
        or evidence.get("build_fingerprint") != manifest.build_fingerprint
        or evidence.get("source_unit_scale_to_meters")
        != plan.normalization.source_unit_scale_to_meters
        or evidence.get("normalized_unit_system") != "METRIC"
        or evidence.get("normalized_unit_scale_length") != 1.0
        or evidence.get("normalized_length_unit") != "METERS"
        or evidence.get("normalized_blend_sha256") != manifest.normalized_blend.sha256
    ):
        raise RuntimeError("External normalization evidence differs from the manifest")
    receipt_path = root / "intake" / "normalization_receipt.json"
    if not file_exists(receipt_path):
        raise RuntimeError("External normalization receipt is missing")
    receipt = ExternalNormalizationReceipt.model_validate_json(
        receipt_path.read_text(encoding="utf-8")
    )
    expected_recipe_hashes = {
        material.material_id: material.shader_recipe.sha256
        for material in manifest.materials
    }
    if (
        receipt.job_id != job_id
        or receipt.plan_sha256 != manifest.intake_plan.sha256
        or receipt.approval_sha256 != manifest.intake_approval.sha256
        or receipt.source_sha256 != manifest.source.sha256
        or receipt.material_plan_sha256 != manifest.material_plan.sha256
        or receipt.shader_recipe_sha256 != expected_recipe_hashes
        or receipt.normalized_blend_sha256 != manifest.normalized_blend.sha256
        or receipt.normalization_evidence_sha256
        != manifest.normalization_evidence.sha256
        or receipt.manifest_sha256 != sha256_file(manifest_path)
        or receipt.source_contract_fingerprint != manifest.source_contract_fingerprint
        or receipt.build_fingerprint != manifest.build_fingerprint
    ):
        raise RuntimeError("External normalization receipt differs from the manifest")
    build["external_asset_manifest_path"] = "intake/external_asset_manifest.json"
    build["external_asset_manifest_sha256"] = sha256_file(manifest_path)
    return build


def normalize_external_static_asset(
    job_id: str,
    plan_id: str,
    plan_sha256: str,
) -> ExternalAssetManifest:
    """Consume one exact approval and publish a normalized static authoring derivative."""

    root = job_dir(job_id)
    plan_path = _plan_path(root, plan_id)
    plan = _load_plan(root, plan_id)
    actual_plan_sha256 = sha256_file(plan_path)
    if actual_plan_sha256 != plan_sha256.casefold():
        raise RuntimeError("External intake plan SHA-256 changed before normalization")
    if plan.status != "awaiting_user_approval" or plan.job_id != job_id:
        raise RuntimeError("External intake plan is not eligible for normalization")
    _verify_plan_artifacts(root, plan)
    approval_path = plan_path.parent / "approval.json"
    if not file_exists(approval_path):
        raise RuntimeError("External intake requires an exact user approval")
    approval_bytes = approval_path.read_bytes()
    approval = ExternalAssetIntakeApproval.model_validate_json(
        approval_bytes.decode("utf-8")
    )
    if (
        approval.used
        or approval.job_id != job_id
        or approval.plan_id != plan_id
        or approval.plan_sha256 != actual_plan_sha256
        or approval.source_sha256 != plan.source.sha256
    ):
        raise RuntimeError("External intake approval is stale, mismatched, or already used")

    manifest_path = root / "intake" / "external_asset_manifest.json"
    blend_path = root / "blender" / "scene.blend"
    material_plan_path = root / "analysis" / "material_plan.json"
    receipt_path = root / "intake" / "normalization_receipt.json"
    evidence_path = root / "intake" / "normalization_evidence.json"
    validation_path = root / "intake" / "validation.json"
    protected = [
        manifest_path,
        blend_path,
        material_plan_path,
        receipt_path,
        evidence_path,
        validation_path,
    ]
    if any(path.exists() for path in protected):
        raise FileExistsError(
            "External normalization never overwrites canonical or prior intake outputs"
        )
    for material in plan.materials:
        target = root / "materials" / material.material_id / "shader_recipe.json"
        if target.exists():
            raise FileExistsError(target)

    staging = root / "intake" / f".normalizing-{uuid4().hex[:12]}"
    staging.mkdir(parents=False, exist_ok=False)
    created_paths: list[Path] = []
    try:
        candidate_plan = _resolve_job_path(
            root,
            plan.candidate_material_plan.path,
            "candidate MaterialPlan",
        )
        staged_material_plan = staging / "material_plan.json"
        shutil.copy2(candidate_plan, staged_material_plan)
        staged_recipes: dict[str, Path] = {}
        candidate_by_material = {
            artifact.path.split("/")[-2]: artifact
            for artifact in plan.candidate_shader_recipes
        }
        for material in plan.materials:
            artifact = candidate_by_material.get(material.material_id)
            if artifact is None:
                raise RuntimeError(
                    f"Intake plan lacks candidate recipe for {material.material_id}"
                )
            source_recipe = _resolve_job_path(root, artifact.path, "candidate shader recipe")
            target = staging / "materials" / material.material_id / "shader_recipe.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_recipe, target)
            staged_recipes[material.material_id] = target
        recipe_hashes = {
            material_id: sha256_file(path)
            for material_id, path in sorted(staged_recipes.items())
        }
        build, source_contract_fingerprint, build_fingerprint = _external_build_payload(
            plan,
            actual_plan_sha256,
            sha256_file(staged_material_plan),
            recipe_hashes,
        )
        staged_build_contract = staging / "build_contract.json"
        write_json_atomic(staged_build_contract, build)
        staged_blend = staging / "scene.blend"
        staged_evidence = staging / "normalization_evidence.json"
        source = _resolve_job_path(root, plan.source.path, "external source")
        run_blender(
            "normalize_external_static_asset.py",
            [
                "--source",
                str(source),
                "--source-format",
                plan.source_format,
                "--plan",
                str(plan_path),
                "--expected-source-sha256",
                plan.source.sha256,
                "--expected-plan-sha256",
                actual_plan_sha256,
                "--build-fingerprint",
                build_fingerprint,
                "--build-contract",
                str(staged_build_contract),
                "--output-blend",
                str(staged_blend),
                "--output-evidence",
                str(staged_evidence),
            ],
            blend_file=source if plan.source_format == "blend" else None,
            factory_startup=plan.source_format != "blend",
            disable_autoexec=True,
        )
        evidence = json.loads(staged_evidence.read_text(encoding="utf-8"))
        if (
            not isinstance(evidence, dict)
            or not evidence.get("ok")
            or evidence.get("plan_sha256") != actual_plan_sha256
            or evidence.get("source_sha256") != plan.source.sha256
            or evidence.get("build_fingerprint") != build_fingerprint
            or evidence.get("source_unit_scale_to_meters")
            != plan.normalization.source_unit_scale_to_meters
            or evidence.get("normalized_unit_system") != "METRIC"
            or evidence.get("normalized_unit_scale_length") != 1.0
            or evidence.get("normalized_length_unit") != "METERS"
            or evidence.get("normalized_blend_sha256") != sha256_file(staged_blend)
        ):
            raise RuntimeError("Blender external normalization evidence is stale or invalid")

        material_plan_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_material_plan, material_plan_path)
        created_paths.append(material_plan_path)
        canonical_recipes: dict[str, Path] = {}
        for material_id, staged in staged_recipes.items():
            target = root / "materials" / material_id / "shader_recipe.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            created_paths.append(target)
            canonical_recipes[material_id] = target
        blend_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_blend, blend_path)
        created_paths.append(blend_path)
        os.replace(staged_evidence, evidence_path)
        created_paths.append(evidence_path)

        used_approval = approval.model_copy(update={"used": True, "used_at": _utc_now()})
        _write_model(approval_path, used_approval)
        used_approval_artifact = _artifact(
            root,
            f"external.approval.{plan_id}",
            "external_intake_approval",
            approval_path,
        )
        plan_artifact = _artifact(
            root,
            f"external.plan.{plan_id}",
            "external_intake_plan",
            plan_path,
        )
        recipe_artifacts = {
            material_id: _artifact(
                root,
                f"external.shader_recipe.canonical.{material_id}",
                "shader_recipe",
                path,
            )
            for material_id, path in canonical_recipes.items()
        }
        evidence_objects = {
            str(item.get("semantic_id")): item
            for item in evidence.get("objects", [])
            if isinstance(item, dict)
        }
        normalized_objects: list[ExternalNormalizedObject] = []
        for item in plan.objects:
            record = evidence_objects.get(item.semantic_id)
            if record is None:
                raise RuntimeError(
                    f"Normalization omitted semantic object: {item.semantic_id}"
                )
            normalized_objects.append(
                ExternalNormalizedObject(
                    source_name=item.source_name,
                    object_name=str(record["name"]),
                    semantic_id=item.semantic_id,
                    parent_semantic_id=item.parent_semantic_id,
                    object_type=str(record["type"]),
                    material_ids=[str(value) for value in record.get("material_ids", [])],
                    qa_role=item.qa_role,
                    location=tuple(float(value) for value in record["location"]),
                    rotation_euler=tuple(
                        float(value) for value in record["rotation_euler"]
                    ),
                    scale=tuple(float(value) for value in record["scale"]),
                    dimensions=tuple(float(value) for value in record["dimensions"]),
                )
            )
        normalized_materials = [
            ExternalNormalizedMaterial(
                source_name=item.source_name,
                material_name=item.material_id,
                material_id=item.material_id,
                node_fingerprint=item.node_fingerprint,
                shader_recipe=recipe_artifacts[item.material_id],
                limitations=item.limitations,
            )
            for item in plan.materials
        ]
        manifest = ExternalAssetManifest(
            manifest_id=f"external.asset.{job_id}",
            job_id=job_id,
            source_format=plan.source_format,
            source=plan.source,
            dependencies=plan.dependencies,
            intake_plan=plan_artifact,
            intake_approval=used_approval_artifact,
            normalized_blend=_artifact(
                root,
                "external.normalized.blend",
                "blend",
                blend_path,
            ),
            normalization_evidence=_artifact(
                root,
                "external.normalization.evidence",
                "external_normalization_evidence",
                evidence_path,
            ),
            material_plan=_artifact(
                root,
                "external.material_plan",
                "material_plan",
                material_plan_path,
            ),
            shader_recipes=list(recipe_artifacts.values()),
            objects=normalized_objects,
            materials=normalized_materials,
            source_contract_fingerprint=source_contract_fingerprint,
            build_fingerprint=build_fingerprint,
            created_at=plan.created_at,
            completed_at=_utc_now(),
            limitations=[
                "Static mesh/curve evaluation only; rig, animation, drivers, gameplay, and "
                "engine-specific graphs are excluded.",
                "Arbitrary Blender master shaders require V0.7 derived baking before portable "
                "delivery; runtime parity is not claimed.",
                "Source coordinates were normalized to meters with approved scale factor "
                f"{plan.normalization.source_unit_scale_to_meters:.12g}.",
            ],
        )
        _write_model(manifest_path, manifest)
        created_paths.append(manifest_path)
        receipt = ExternalNormalizationReceipt(
            receipt_id=f"external.normalization.{plan_id}",
            job_id=job_id,
            plan_sha256=actual_plan_sha256,
            approval_sha256=used_approval_artifact.sha256,
            source_sha256=plan.source.sha256,
            material_plan_sha256=manifest.material_plan.sha256,
            shader_recipe_sha256={
                material_id: artifact.sha256
                for material_id, artifact in sorted(recipe_artifacts.items())
            },
            normalized_blend_sha256=manifest.normalized_blend.sha256,
            normalization_evidence_sha256=manifest.normalization_evidence.sha256,
            manifest_sha256=sha256_file(manifest_path),
            source_contract_fingerprint=source_contract_fingerprint,
            build_fingerprint=build_fingerprint,
            completed_at=_utc_now(),
        )
        _write_model(receipt_path, receipt)
        created_paths.append(receipt_path)
        created_paths.append(validation_path)
        validation = validate_external_static_asset_intake(job_id)
        if not validation.ok:
            raise RuntimeError(
                f"External intake validation failed after normalization: {validation.errors}"
            )
        return manifest
    except Exception:
        approval_path.write_bytes(approval_bytes)
        for path in reversed(created_paths):
            path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _artifact_current(root: Path, artifact: ExternalIntakeArtifact) -> bool:
    """Return whether one manifest-bound file still matches its exact digest."""

    try:
        path = _resolve_job_path(root, artifact.path, artifact.kind)
    except ValueError:
        return False
    return file_exists(path) and sha256_file(path) == artifact.sha256


def _evaluate_external_static_asset_intake(
    job_id: str,
) -> ExternalAssetIntakeValidation:
    """Evaluate current intake hashes without writing or repairing workspace evidence."""

    root = job_dir(job_id)
    manifest_path = root / "intake" / "external_asset_manifest.json"
    errors: list[str] = []
    warnings: list[str] = []
    if not file_exists(manifest_path):
        raise FileNotFoundError(manifest_path)
    manifest = ExternalAssetManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    plan_path = _resolve_job_path(root, manifest.intake_plan.path, "intake plan")
    plan = ExternalAssetIntakePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    source_current = _artifact_current(root, manifest.source)
    dependencies_current = all(
        _artifact_current(root, dependency) for dependency in manifest.dependencies
    )
    approval_current = _artifact_current(root, manifest.intake_approval)
    approval_used = False
    if approval_current:
        approval_path = _resolve_job_path(
            root,
            manifest.intake_approval.path,
            "intake approval",
        )
        approval = ExternalAssetIntakeApproval.model_validate_json(
            approval_path.read_text(encoding="utf-8")
        )
        approval_used = bool(approval.used and approval.plan_sha256 == manifest.intake_plan.sha256)
    contracts_current = _artifact_current(root, manifest.material_plan) and all(
        _artifact_current(root, artifact) for artifact in manifest.shader_recipes
    )
    normalized_blend_current = _artifact_current(root, manifest.normalized_blend)
    evidence_current = _artifact_current(root, manifest.normalization_evidence)
    receipt_path = root / "intake" / "normalization_receipt.json"
    normalization_receipt_current = False
    if file_exists(receipt_path):
        receipt = ExternalNormalizationReceipt.model_validate_json(
            receipt_path.read_text(encoding="utf-8")
        )
        normalization_receipt_current = bool(
            receipt.job_id == job_id
            and receipt.plan_sha256 == manifest.intake_plan.sha256
            and receipt.approval_sha256 == manifest.intake_approval.sha256
            and receipt.source_sha256 == manifest.source.sha256
            and receipt.material_plan_sha256 == manifest.material_plan.sha256
            and receipt.normalized_blend_sha256 == manifest.normalized_blend.sha256
            and receipt.normalization_evidence_sha256
            == manifest.normalization_evidence.sha256
            and receipt.manifest_sha256 == sha256_file(manifest_path)
            and receipt.source_contract_fingerprint
            == manifest.source_contract_fingerprint
            and receipt.build_fingerprint == manifest.build_fingerprint
        )
    embedded_build_current = False
    if evidence_current:
        evidence_path = _resolve_job_path(
            root,
            manifest.normalization_evidence.path,
            "normalization evidence",
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        sanitization = evidence.get("sanitization", {}) if isinstance(evidence, dict) else {}
        embedded_build_current = bool(
            isinstance(evidence, dict)
            and evidence.get("ok")
            and evidence.get("build_fingerprint") == manifest.build_fingerprint
            and evidence.get("normalized_blend_sha256") == manifest.normalized_blend.sha256
            and evidence.get("plan_sha256") == manifest.intake_plan.sha256
            and evidence.get("source_unit_scale_to_meters")
            == plan.normalization.source_unit_scale_to_meters
            and evidence.get("normalized_unit_system") == "METRIC"
            and evidence.get("normalized_unit_scale_length") == 1.0
            and evidence.get("normalized_length_unit") == "METERS"
            and isinstance(sanitization, dict)
            and sanitization.get("text_block_count") == 0
            and sanitization.get("scene_count") == 1
            and sanitization.get("action_count") == 0
            and sanitization.get("armature_count") == 0
            and sanitization.get("autoexec_disabled") is True
        )
    try:
        current_build = collect_external_build_provenance(root, job_id)
        if current_build["fingerprint"] != manifest.build_fingerprint:
            errors.append("Current external build fingerprint differs from the manifest")
    except (OSError, ValueError, RuntimeError) as exc:
        errors.append(f"External build provenance is invalid: {exc}")
    checks = {
        "source_current": source_current,
        "dependencies_current": dependencies_current,
        "approval_current_and_used": approval_current and approval_used,
        "contracts_current": contracts_current,
        "normalized_blend_current": normalized_blend_current,
        "embedded_build_current": embedded_build_current,
        "normalization_receipt_current": normalization_receipt_current,
    }
    errors.extend(label for label, passed in checks.items() if not passed)
    if not manifest.dependencies:
        warnings.append(
            "No external image sidecars were copied; images may have been packed or absent."
        )
    ok = not errors and bool(manifest.objects) and bool(manifest.materials)
    report = ExternalAssetIntakeValidation(
        job_id=job_id,
        plan_id=plan.plan_id,
        status="passed" if ok else "failed",
        ok=ok,
        source_current=source_current,
        dependencies_current=dependencies_current,
        approval_current_and_used=approval_current and approval_used,
        contracts_current=contracts_current,
        normalized_blend_current=normalized_blend_current,
        embedded_build_current=embedded_build_current,
        normalization_receipt_current=normalization_receipt_current,
        semantic_object_count=len(manifest.objects),
        material_count=len(manifest.materials),
        errors=errors,
        warnings=warnings,
        checked_at=_utc_now(),
    )
    return report


def validate_external_static_asset_intake(job_id: str) -> ExternalAssetIntakeValidation:
    """Validate current intake hashes and publish a machine-readable readiness report."""

    report = _evaluate_external_static_asset_intake(job_id)
    _write_model(job_dir(job_id) / "intake" / "validation.json", report)
    return report


def get_external_static_asset_intake_status(job_id: str) -> dict[str, Any]:
    """Return a read-only summary of plan, approval, normalization, and V0.7 readiness."""

    root = job_dir(job_id)
    metadata_path_value = root / "job.json"
    if not file_exists(metadata_path_value):
        raise FileNotFoundError(metadata_path_value)
    metadata = json.loads(metadata_path_value.read_text(encoding="utf-8"))
    if metadata.get("job_kind") != "external_static_asset":
        raise ValueError(f"Job is not an external static-asset intake: {job_id}")
    plan_value = metadata.get("external_intake_plan")
    plan_path = _resolve_job_path(root, str(plan_value), "external intake plan")
    plan = ExternalAssetIntakePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    approval_path = plan_path.parent / "approval.json"
    approval_status = "not_approved"
    if file_exists(approval_path):
        approval = ExternalAssetIntakeApproval.model_validate_json(
            approval_path.read_text(encoding="utf-8")
        )
        approval_status = "used" if approval.used else "approved"
    manifest_path = root / "intake" / "external_asset_manifest.json"
    validation_status = "not_run"
    ready = False
    if file_exists(manifest_path):
        try:
            live_validation = _evaluate_external_static_asset_intake(job_id)
        except (OSError, ValueError, RuntimeError):
            validation_status = "failed"
        else:
            validation_status = live_validation.status
            ready = live_validation.ok
    return {
        "schema_version": "0.9.0",
        "job_id": job_id,
        "job_kind": "external_static_asset",
        "plan_id": plan.plan_id,
        "plan_path": _job_relative(root, plan_path),
        "plan_sha256": sha256_file(plan_path),
        "plan_status": plan.status,
        "approval_status": approval_status,
        "manifest_path": (
            _job_relative(root, manifest_path) if file_exists(manifest_path) else None
        ),
        "validation_status": validation_status,
        "ready_for_v07_preflight": ready,
        "limitations": [
            "Static assets only.",
            "Portable shader delivery requires V0.7 material conversion and PBR baking.",
            "Destination runtime parity remains unverified until destination-side import.",
        ],
    }


__all__ = [
    "approve_external_static_asset_intake",
    "collect_external_build_provenance",
    "get_external_static_asset_intake_status",
    "normalize_external_static_asset",
    "plan_external_static_asset_intake",
    "validate_external_static_asset_intake",
]
