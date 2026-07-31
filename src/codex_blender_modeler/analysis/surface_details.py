"""Cross-contract validation for non-mesh, surface-attached reference details."""

from __future__ import annotations

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


def validate_surface_detail_contract(
    plan: ModelingPlan,
    scene_spec: SceneSpec,
    job_root: Path,
    *,
    material_plan: MaterialPlan | None = None,
    require_materials: bool = False,
) -> SurfaceDetailValidationReport:
    """Verify non-mesh decisions against SceneSpec and optional V0.5 texture contracts."""

    from ..material_manifest import load_material_manifest
    from ..texturing.manifest import load_texture_manifest

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
            "Surface-detail coverage is a contract assertion, not pixel-level visual proof.",
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
