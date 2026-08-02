from __future__ import annotations

from pathlib import Path
from typing import Any

from ..shader_recipe_runtime import (
    ShaderRecipeRuntimeError,
    validate_runtime_shader_recipe,
)
from ..texturing.manifest import MaterialManifestError, load_material_manifest
from .io import load_shader_recipe, resolve_job_path
from .models import MaterialPlan, MaterialValidationCheck, MaterialValidationReport


def _check(
    checks: list[MaterialValidationCheck],
    check_id: str,
    status: str,
    message: str,
    *,
    material_id: str | None = None,
    path: Path | None = None,
) -> None:
    """Append one normalized validation check to a report under construction."""

    checks.append(
        MaterialValidationCheck(
            id=check_id,
            status=status,
            message=message,
            material_id=material_id,
            path=str(path) if path else None,
        )
    )


def validate_material_contracts(
    plan: MaterialPlan,
    scene_spec: dict[str, Any],
    job_root: Path,
) -> MaterialValidationReport:
    """Cross-check material plans, recipes, manifests, and SceneSpec stable IDs."""

    checks: list[MaterialValidationCheck] = []
    scene_job_id = str(scene_spec.get("job_id", ""))
    if scene_job_id == plan.job_id:
        _check(checks, "job_id", "passed", "Material plan job_id matches SceneSpec")
    else:
        _check(
            checks,
            "job_id",
            "failed",
            f"Material plan job_id {plan.job_id!r} does not match SceneSpec {scene_job_id!r}",
        )

    scene_materials = {
        str(item.get("id")): item
        for item in scene_spec.get("materials", [])
        if isinstance(item, dict) and item.get("id")
    }
    plan_material_ids = {item.material_id for item in plan.materials}
    for missing_id in sorted(set(scene_materials) - plan_material_ids):
        _check(
            checks,
            f"material_plan_coverage:{missing_id}",
            "failed",
            "Material plan omits a SceneSpec material; partial plans are not executable",
            material_id=missing_id,
        )
    for item in plan.materials:
        material_id = item.material_id
        scene_material = scene_materials.get(material_id)
        if scene_material is None:
            _check(
                checks,
                f"scene_material:{material_id}",
                "failed",
                "Material plan references a missing SceneSpec material",
                material_id=material_id,
            )
            continue
        _check(
            checks,
            f"scene_material:{material_id}",
            "passed",
            "Stable material ID exists in SceneSpec",
            material_id=material_id,
        )

        recipe_manifest: str | None = None
        if item.shader_recipe:
            recipe_path = resolve_job_path(job_root, item.shader_recipe, "shader_recipe")
            try:
                recipe = load_shader_recipe(recipe_path)
            except (OSError, ValueError) as exc:
                _check(
                    checks,
                    f"shader_recipe:{material_id}",
                    "failed",
                    f"Shader recipe is invalid: {exc}",
                    material_id=material_id,
                    path=recipe_path,
                )
            else:
                recipe_manifest = recipe.texture_manifest
                status = "passed" if recipe.material_id == material_id else "failed"
                message = (
                    "Shader recipe material_id matches"
                    if status == "passed"
                    else f"Shader recipe targets {recipe.material_id!r}"
                )
                if status == "passed":
                    try:
                        validate_runtime_shader_recipe(
                            recipe.model_dump(mode="json"),
                            material_id,
                            recipe_path,
                            item.texture_strategy,
                            plan_family=item.shader_family,
                            plan_mapping=item.mapping.model_dump(mode="json"),
                        )
                    except ShaderRecipeRuntimeError as exc:
                        status = "failed"
                        message = f"Shader recipe is outside the Blender runtime subset: {exc}"
                _check(
                    checks,
                    f"shader_recipe:{material_id}",
                    status,
                    message,
                    material_id=material_id,
                    path=recipe_path,
                )
        else:
            _check(
                checks,
                f"shader_recipe:{material_id}",
                "warning",
                "No shader recipe is assigned; legacy SceneSpec shader behavior remains active",
                material_id=material_id,
            )

        if item.texture_manifest and recipe_manifest and item.texture_manifest != recipe_manifest:
            _check(
                checks,
                f"texture_manifest_pointer:{material_id}",
                "failed",
                "Material plan and shader recipe texture_manifest paths disagree",
                material_id=material_id,
            )
        manifest_value = item.texture_manifest or recipe_manifest
        scene_manifest = scene_material.get("texture_manifest")
        if scene_manifest and scene_manifest != manifest_value:
            _check(
                checks,
                f"texture_manifest_precedence:{material_id}",
                "warning",
                (
                    "MaterialPlan/ShaderRecipe manifest precedence suppresses a different "
                    "legacy SceneSpec texture_manifest"
                ),
                material_id=material_id,
            )
        if manifest_value:
            try:
                manifest, manifest_path = load_material_manifest(
                    {"id": material_id, "texture_manifest": manifest_value}, job_root
                )
            except (MaterialManifestError, OSError, ValueError) as exc:
                _check(
                    checks,
                    f"texture_manifest:{material_id}",
                    "failed",
                    f"Texture manifest is invalid: {exc}",
                    material_id=material_id,
                )
            else:
                source_type = str(manifest["source_type"]) if manifest else ""
                if source_type != item.texture_strategy:
                    _check(
                        checks,
                        f"texture_manifest:{material_id}",
                        "failed",
                        (
                            f"Texture strategy {item.texture_strategy!r} does not match "
                            f"manifest source_type {source_type!r}"
                        ),
                        material_id=material_id,
                        path=manifest_path,
                    )
                elif manifest.get("surface_detail_bindings") and (
                    item.mapping.mode != "uv"
                    or item.mapping.uv_set != "UVMap"
                    or manifest.get("uv_set") != "UVMap"
                ):
                    _check(
                        checks,
                        f"texture_manifest:{material_id}",
                        "failed",
                        (
                            "Spatial surface details require MaterialPlan UV mapping and "
                            "the exact UVMap manifest coordinates"
                        ),
                        material_id=material_id,
                        path=manifest_path,
                    )
                else:
                    _check(
                        checks,
                        f"texture_manifest:{material_id}",
                        "passed",
                        "Texture manifest and channel paths are valid",
                        material_id=material_id,
                        path=manifest_path,
                    )
        elif item.texture_strategy == "procedural" and item.shader_recipe:
            _check(
                checks,
                f"texture_manifest:{material_id}",
                "passed",
                "Procedural shader recipe does not require a texture manifest",
                material_id=material_id,
            )
        elif item.texture_strategy == "none":
            _check(
                checks,
                f"texture_manifest:{material_id}",
                "passed",
                "Texture strategy is none; no manifest is required",
                material_id=material_id,
            )
        else:
            _check(
                checks,
                f"texture_manifest:{material_id}",
                "failed",
                f"Texture strategy {item.texture_strategy!r} requires a manifest",
                material_id=material_id,
            )

    counts = {
        status: sum(item.status == status for item in checks)
        for status in ("passed", "warning", "failed")
    }
    return MaterialValidationReport(
        job_id=plan.job_id,
        ok=counts["failed"] == 0,
        passed=counts["passed"],
        warnings=counts["warning"],
        failed=counts["failed"],
        checks=checks,
        notes=["This host report does not replace Blender node, UV, swatch, or bake validation."],
    )


def write_material_validation_report(report: MaterialValidationReport, output: Path) -> Path:
    """Persist one material validation report without mutating source contracts."""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output
