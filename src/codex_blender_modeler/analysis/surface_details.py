"""Cross-contract validation for non-mesh, surface-attached reference details."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ..blender_artifacts import write_json_atomic
from ..models import SceneSpec
from .models import (
    ModelingPlan,
    SurfaceDetailValidationCheck,
    SurfaceDetailValidationReport,
)

if TYPE_CHECKING:
    from ..materials.models import MaterialPlan


def _check(
    checks: list[SurfaceDetailValidationCheck],
    check_id: str,
    status: str,
    phase: str,
    message: str,
    *,
    detail_id: str | None = None,
    parent_object_id: str | None = None,
    material_id: str | None = None,
) -> None:
    """Append one normalized surface-detail validation check."""

    checks.append(
        SurfaceDetailValidationCheck(
            id=check_id,
            status=status,
            phase=phase,
            message=message,
            detail_id=detail_id,
            parent_object_id=parent_object_id,
            material_id=material_id,
        )
    )


def _manifest_path_for_item(
    job_root: Path,
    item: object,
) -> Path | None:
    """Resolve the effective texture manifest declared by a material-plan item or recipe."""

    from ..materials.io import load_shader_recipe, resolve_job_path

    manifest_value = getattr(item, "texture_manifest", None)
    recipe_value = getattr(item, "shader_recipe", None)
    if recipe_value:
        recipe_path = resolve_job_path(job_root, str(recipe_value), "shader_recipe")
        recipe = load_shader_recipe(recipe_path)
        if manifest_value and recipe.texture_manifest:
            if str(manifest_value) != str(recipe.texture_manifest):
                raise ValueError(
                    "MaterialPlan and ShaderRecipe texture-manifest paths disagree"
                )
        manifest_value = manifest_value or recipe.texture_manifest
    if not manifest_value:
        return None
    return resolve_job_path(job_root, str(manifest_value), "texture_manifest")


def _load_inventory_uv_evidence(
    job_root: Path,
    *,
    inventory_path: Path | None = None,
) -> dict[str, list[dict]]:
    """Index canonical or isolated scene-inventory UV evidence by semantic ID."""

    path = (
        inventory_path.expanduser().resolve()
        if inventory_path is not None
        else job_root / "reports" / "scene_inventory.json"
    )
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    indexed: dict[str, list[dict]] = {}
    for record in payload.get("objects", []):
        if not isinstance(record, dict) or not record.get("cbm_id"):
            continue
        indexed.setdefault(str(record["cbm_id"]), []).append(record)
    return indexed


def validate_surface_detail_contract(
    plan: ModelingPlan,
    scene_spec: SceneSpec,
    job_root: Path,
    *,
    material_plan: MaterialPlan | None = None,
    require_materials: bool = False,
    inventory_path: Path | None = None,
) -> SurfaceDetailValidationReport:
    """Verify non-mesh decisions against SceneSpec and optional V0.5 texture contracts."""

    from ..material_manifest import load_material_manifest
    from ..texturing.manifest import load_texture_manifest
    from ..workspace import sha256_file

    checks: list[SurfaceDetailValidationCheck] = []
    if plan.job_id != scene_spec.job_id:
        _check(
            checks,
            "job_id",
            "failed",
            "modeling",
            "ModelingPlan job_id does not match SceneSpec",
        )
    else:
        _check(
            checks,
            "job_id",
            "passed",
            "modeling",
            "ModelingPlan job_id matches SceneSpec",
        )

    object_by_id = {item.id: item for item in scene_spec.objects}
    plan_material_by_id = (
        {item.material_id: item for item in material_plan.materials}
        if material_plan is not None
        else {}
    )
    binding_policy = (
        str(
            getattr(
                material_plan,
                "surface_detail_binding_policy",
                "legacy_unbound",
            )
        )
        if material_plan is not None
        else "legacy_unbound"
    )
    require_spatial_bindings = binding_policy == "spatial_v1"
    inventory_by_id = (
        _load_inventory_uv_evidence(job_root, inventory_path=inventory_path)
        if require_spatial_bindings
        else {}
    )
    textured = sum(
        detail.representation != "omit" for detail in plan.surface_details
    )
    omitted = len(plan.surface_details) - textured
    material_status = (
        "not_required"
        if textured == 0
        else "validated"
        if material_plan is not None and material_plan.stage == "authored"
        else "pending"
    )

    for detail in plan.surface_details:
        detail_prefix = f"surface_detail:{detail.id}"
        if detail.id in object_by_id:
            _check(
                checks,
                f"{detail_prefix}:non_mesh",
                "failed",
                "geometry",
                "A texture-routed surface detail must not exist as a SceneSpec object",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=detail.target_material_id,
            )
        else:
            _check(
                checks,
                f"{detail_prefix}:non_mesh",
                "passed",
                "geometry",
                "Surface detail remains outside the SceneSpec geometry object list",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=detail.target_material_id,
            )

        parent = object_by_id.get(detail.parent_object_id)
        if parent is None:
            _check(
                checks,
                f"{detail_prefix}:parent",
                "failed",
                "geometry",
                "Surface-detail parent is missing from SceneSpec",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=detail.target_material_id,
            )
            continue
        _check(
            checks,
            f"{detail_prefix}:parent",
            "passed",
            "geometry",
            "Surface-detail parent exists in SceneSpec",
            detail_id=detail.id,
            parent_object_id=detail.parent_object_id,
            material_id=detail.target_material_id,
        )
        if detail.representation == "omit":
            _check(
                checks,
                f"{detail_prefix}:omission",
                "passed",
                "modeling",
                "Surface detail is explicitly omitted rather than silently meshed",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
            )
            continue

        material_id = str(detail.target_material_id)
        if parent.material_id != material_id:
            _check(
                checks,
                f"{detail_prefix}:assignment",
                "failed",
                "geometry",
                "Surface-detail target material is not assigned to its parent object",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
            continue
        _check(
            checks,
            f"{detail_prefix}:assignment",
            "passed",
            "geometry",
            "Surface-detail target material is assigned to its parent object",
            detail_id=detail.id,
            parent_object_id=detail.parent_object_id,
            material_id=material_id,
        )

        if material_plan is None or material_plan.stage != "authored":
            status = "failed" if require_materials else "warning"
            _check(
                checks,
                f"{detail_prefix}:material_binding",
                status,
                "material",
                "V0.5 authored texture coverage is required before material build"
                if require_materials
                else "Surface detail awaits V0.5 authored texture coverage",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
            continue

        item = plan_material_by_id.get(material_id)
        if item is None:
            _check(
                checks,
                f"{detail_prefix}:material_binding",
                "failed",
                "material",
                "Authored MaterialPlan omits the target material",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
            continue
        if item.texture_strategy not in {"image", "hybrid"}:
            _check(
                checks,
                f"{detail_prefix}:material_binding",
                "failed",
                "material",
                "Localized surface details require an image or hybrid texture strategy",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
            continue
        try:
            manifest_path = _manifest_path_for_item(job_root, item)
            if manifest_path is None:
                raise ValueError("No texture manifest is assigned")
            load_material_manifest(
                {
                    "id": material_id,
                    "texture_manifest": manifest_path.relative_to(
                        job_root.resolve()
                    ).as_posix(),
                },
                job_root,
            )
            manifest = load_texture_manifest(manifest_path)
        except (OSError, ValueError) as exc:
            _check(
                checks,
                f"{detail_prefix}:material_binding",
                "failed",
                "material",
                f"Surface-detail texture manifest is invalid: {exc}",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
            continue
        if manifest.material_id != material_id:
            _check(
                checks,
                f"{detail_prefix}:manifest_material",
                "failed",
                "material",
                "TextureManifest material_id differs from the planned target material",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
        if detail.id not in manifest.surface_detail_ids:
            _check(
                checks,
                f"{detail_prefix}:coverage",
                "failed",
                "material",
                "TextureManifest does not claim exact coverage for this surface detail",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
        else:
            _check(
                checks,
                f"{detail_prefix}:coverage",
                "passed",
                "material",
                "TextureManifest is explicitly bound to this surface-detail ID",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
        binding = next(
            (
                item
                for item in manifest.surface_detail_bindings
                if item.detail_id == detail.id
            ),
            None,
        )
        if binding is None:
            _check(
                checks,
                f"{detail_prefix}:spatial_binding",
                "failed" if require_spatial_bindings else "warning",
                "material",
                (
                    "Spatial-v1 material authoring requires an object- and UV-bound "
                    "surface-detail placement"
                    if require_spatial_bindings
                    else "Legacy surface-detail coverage has no spatial placement evidence; "
                    "the manifest remains readable and executable but audit-only"
                ),
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
        else:
            binding_errors: list[str] = []
            if binding.parent_object_id != detail.parent_object_id:
                binding_errors.append("parent_object_id differs from ModelingPlan")
            if binding.material_id != material_id:
                binding_errors.append("material_id differs from ModelingPlan")
            if set(binding.channels) != set(detail.channels):
                binding_errors.append("channels differ from ModelingPlan")
            material_users = sorted(
                item.id
                for item in scene_spec.objects
                if item.material_id == material_id
            )
            if require_spatial_bindings and material_users != [detail.parent_object_id]:
                binding_errors.append(
                    "localized detail material is shared by objects outside its parent; "
                    f"users={material_users}"
                )
            if require_spatial_bindings:
                inventory_records = inventory_by_id.get(detail.parent_object_id, [])
                inventory_hashes: set[str] = set()
                unit_bounds = True
                for record in inventory_records:
                    layer = next(
                        (
                            item
                            for item in record.get("uv_layers", [])
                            if item.get("name") == binding.uv_set
                        ),
                        None,
                    )
                    if layer is None:
                        unit_bounds = False
                        continue
                    fingerprint = layer.get("vertex_uv_binding_fingerprint")
                    if fingerprint:
                        inventory_hashes.add(str(fingerprint))
                    bounds = layer.get("coordinate_bounds")
                    if not bounds:
                        unit_bounds = False
                    else:
                        values = [
                            *bounds.get("min", []),
                            *bounds.get("max", []),
                        ]
                        unit_bounds = unit_bounds and bool(
                            len(values) == 4
                            and all(0.0 <= float(value) <= 1.0 for value in values)
                        )
                if not inventory_records:
                    binding_errors.append(
                        "current scene inventory has no parent-object UV evidence"
                    )
                elif inventory_hashes != {binding.uv_layout_sha256}:
                    binding_errors.append(
                        "uv_layout_sha256 differs from the current parent UVMap fingerprint"
                    )
                elif not unit_bounds:
                    binding_errors.append(
                        "parent UVMap is missing or extends outside the non-repeating 0..1 tile"
                    )
            if binding.placement.mode == "mask_image":
                mask_value = str(binding.placement.mask_path)
                mask_path = (manifest_path.parent / mask_value).resolve()
                try:
                    mask_path.relative_to(manifest_path.parent.resolve())
                except ValueError:
                    binding_errors.append("mask_path escapes the texture-manifest directory")
                else:
                    if not mask_path.is_file():
                        binding_errors.append("mask_path does not exist")
                    elif sha256_file(mask_path) != binding.placement.mask_sha256:
                        binding_errors.append("mask_path SHA-256 differs from binding")
            if binding_errors:
                _check(
                    checks,
                    f"{detail_prefix}:spatial_binding",
                    "failed",
                    "material",
                    "Surface-detail spatial binding is invalid: "
                    + "; ".join(binding_errors),
                    detail_id=detail.id,
                    parent_object_id=detail.parent_object_id,
                    material_id=material_id,
                )
            else:
                _check(
                    checks,
                    f"{detail_prefix}:spatial_binding",
                    "passed",
                    "material",
                    "Surface detail is bound to its parent, material, UV layout, "
                    "channels, bounded placement, strength, and non-repeating wrap mode",
                    detail_id=detail.id,
                    parent_object_id=detail.parent_object_id,
                    material_id=material_id,
                )
        missing_channels = sorted(set(detail.channels) - set(manifest.channels))
        if missing_channels:
            _check(
                checks,
                f"{detail_prefix}:channels",
                "failed",
                "material",
                f"TextureManifest is missing required PBR channels: {missing_channels}",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
        else:
            _check(
                checks,
                f"{detail_prefix}:channels",
                "passed",
                "material",
                "TextureManifest contains every planned surface-detail PBR channel",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
        if manifest.uv_set != "UVMap":
            _check(
                checks,
                f"{detail_prefix}:uv",
                "failed",
                "material",
                "Localized surface details require a stable UVMap texture contract",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )
        else:
            _check(
                checks,
                f"{detail_prefix}:uv",
                "passed",
                "material",
                "Surface detail uses a portable UVMap texture contract",
                detail_id=detail.id,
                parent_object_id=detail.parent_object_id,
                material_id=material_id,
            )

    counts = {
        status: sum(item.status == status for item in checks)
        for status in ("passed", "warning", "failed")
    }
    return SurfaceDetailValidationReport(
        job_id=scene_spec.job_id,
        ok=counts["failed"] == 0,
        material_status=material_status,
        total=len(plan.surface_details),
        textured=textured,
        omitted=omitted,
        passed=counts["passed"],
        warnings=counts["warning"],
        failed=counts["failed"],
        checks=checks,
        notes=[
            (
                "Spatial-v1 bindings authorize bounded placement contracts but do not replace "
                "pixel-level visual QA."
            ),
            (
                "Legacy unbound TextureManifests remain readable and executable with an "
                "audit warning; new spatial-v1 authoring fails closed without exact bindings."
            ),
            "Silhouette, structural, transparent, or gameplay-relevant parts remain geometry.",
        ],
    )


def validate_job_surface_details(
    job_id: str,
    *,
    require_materials: bool | None = None,
    write_report: bool = True,
    raise_on_error: bool = False,
) -> SurfaceDetailValidationReport:
    """Validate one job and optionally persist the machine-readable cross-contract report."""

    from ..materials.io import load_material_plan
    from ..workspace import job_dir

    root = job_dir(job_id)
    plan_path = root / "analysis" / "modeling_plan.json"
    scene_path = root / "analysis" / "scene_spec.json"
    scene_spec = SceneSpec.model_validate_json(scene_path.read_text(encoding="utf-8"))
    if not plan_path.is_file():
        check = SurfaceDetailValidationCheck(
            id="modeling_plan",
            status="warning",
            phase="modeling",
            message=(
                "Legacy job has no ModelingPlan; no explicit surface-detail decisions "
                "were available to validate"
            ),
        )
        report = SurfaceDetailValidationReport(
            job_id=scene_spec.job_id,
            ok=True,
            material_status="not_required",
            total=0,
            textured=0,
            omitted=0,
            passed=0,
            warnings=1,
            failed=0,
            checks=[check],
            notes=[
                "Legacy compatibility does not retroactively infer surface-detail intent."
            ],
        )
        if write_report:
            write_json_atomic(
                root / "reports" / "surface_detail_validation.json",
                report.model_dump(mode="json"),
            )
        return report
    plan = ModelingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    material_path = root / "analysis" / "material_plan.json"
    material_plan = load_material_plan(material_path) if material_path.is_file() else None
    required = material_path.is_file() if require_materials is None else require_materials
    report = validate_surface_detail_contract(
        plan,
        scene_spec,
        root,
        material_plan=material_plan,
        require_materials=required,
    )
    if write_report:
        write_json_atomic(
            root / "reports" / "surface_detail_validation.json",
            report.model_dump(mode="json"),
        )
    if raise_on_error and not report.ok:
        failures = "; ".join(
            item.message for item in report.checks if item.status == "failed"
        )
        raise ValueError(f"Surface-detail validation failed: {failures}")
    return report


def validate_scene_surface_details(
    scene_spec: SceneSpec,
    scene_spec_path: Path,
) -> SurfaceDetailValidationReport | None:
    """Enforce geometry safety for a job-local SceneSpec without requiring V0.5 yet."""

    resolved = scene_spec_path.expanduser().resolve()
    if resolved.parent.name != "analysis":
        return None
    root = resolved.parent.parent
    plan_path = root / "analysis" / "modeling_plan.json"
    if not plan_path.is_file():
        return None
    plan = ModelingPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    report = validate_surface_detail_contract(
        plan,
        scene_spec,
        root,
        require_materials=False,
    )
    geometry_failures = [
        item for item in report.checks if item.status == "failed" and item.phase != "material"
    ]
    if geometry_failures:
        formatted = "\n".join(f"- {item.message}" for item in geometry_failures)
        raise ValueError(f"Surface-detail geometry validation failed:\n{formatted}")
    return report
