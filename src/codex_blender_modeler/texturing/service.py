from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..material_manifest import load_material_manifest
from ..materials.io import (
    load_material_plan,
    load_shader_recipe,
    resolve_job_path,
)
from ..materials.models import MappingSpec, MaterialPlan, ShaderRecipe
from ..workspace import job_dir
from .models import SurfaceDetailBinding
from .procedural_provider import (
    generate_procedural_pbr,
    list_material_family_presets,
    shader_family_for_preset,
)


def _atomic_contract(path: Path, content: str) -> None:
    """Atomically replace one JSON contract after validation has succeeded."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _attachment_context(
    job_id: str, material_id: str
) -> tuple[Path, Path, MaterialPlan, int, Path | None, ShaderRecipe | None]:
    """Load the target plan item and reject incompatible authored recipe layers."""

    root = job_dir(job_id)
    plan_path = root / "analysis" / "material_plan.json"
    plan = load_material_plan(plan_path)
    index = next(
        (
            position
            for position, item in enumerate(plan.materials)
            if item.material_id == material_id
        ),
        -1,
    )
    if index < 0:
        raise KeyError(f"Material plan does not contain stable material ID: {material_id}")
    item = plan.materials[index]
    recipe_path: Path | None = None
    recipe: ShaderRecipe | None = None
    if item.shader_recipe:
        recipe_path = resolve_job_path(root, item.shader_recipe, "shader_recipe")
        recipe = load_shader_recipe(recipe_path)
        if recipe.material_id != material_id:
            raise ValueError(
                f"Shader recipe targets {recipe.material_id!r}, expected {material_id!r}"
            )
        if recipe.layers:
            raise ValueError(
                f"Material {material_id} has procedural recipe layers; explicitly revise the "
                "recipe before attaching image-map textures"
            )
    return root, plan_path, plan, index, recipe_path, recipe


def attach_texture_manifest_to_plan(
    job_id: str,
    material_id: str,
    manifest_relative_path: str,
    *,
    shader_family: str | None = None,
) -> MaterialPlan:
    """Attach one validated manifest to its plan/recipe without changing SceneSpec geometry."""

    root, plan_path, plan, index, recipe_path, recipe = _attachment_context(
        job_id, material_id
    )
    if plan.job_id != job_id:
        raise ValueError(f"Material plan job_id {plan.job_id!r} does not match {job_id!r}")
    manifest, manifest_path = load_material_manifest(
        {"id": material_id, "texture_manifest": manifest_relative_path}, root
    )
    if manifest is None or manifest_path is None:
        raise ValueError(f"Texture manifest did not load for {material_id}")
    normalized_manifest_path = manifest_path.relative_to(root.resolve()).as_posix()
    source_type = str(manifest["source_type"])
    if source_type not in {"image", "hybrid"}:
        raise ValueError(
            "Generated image-map attachment requires manifest source_type image or hybrid"
        )
    uv_set = str(manifest["uv_set"])
    mapping = MappingSpec(
        mode={"UVMap": "uv", "Generated": "generated", "Object": "object"}[uv_set],
        uv_set=uv_set,
        real_world_scale_m=float(manifest["intended_scale_m"]),
    )
    item = plan.materials[index].model_copy(
        update={
            **({"shader_family": shader_family} if shader_family else {}),
            "texture_strategy": source_type,
            "texture_manifest": normalized_manifest_path,
            "mapping": mapping,
        }
    )
    materials = list(plan.materials)
    materials[index] = item
    updated_plan = plan.model_copy(update={"stage": "authored", "materials": materials})
    updated_plan = MaterialPlan.model_validate(updated_plan.model_dump(mode="json"))

    if recipe_path is not None and recipe is not None:
        updated_recipe = recipe.model_copy(
            update={
                **({"family": shader_family} if shader_family else {}),
                "mapping": mapping,
                "texture_manifest": normalized_manifest_path,
                "bake_required": True,
            }
        )
        updated_recipe = ShaderRecipe.model_validate(updated_recipe.model_dump(mode="json"))
        _atomic_contract(recipe_path, updated_recipe.model_dump_json(indent=2) + "\n")
    _atomic_contract(plan_path, updated_plan.model_dump_json(indent=2) + "\n")
    return updated_plan


def generate_job_procedural_textures(
    job_id: str,
    material_id: str,
    *,
    preset: str = "standard_pbr",
    channels: Sequence[str] = (
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "emission",
    ),
    resolution: tuple[int, int] = (512, 512),
    seed: int = 0,
    intended_scale_m: float = 1.0,
    prompt: str = "",
    uv_set: str = "Object",
    surface_detail_ids: Sequence[str] = (),
    surface_detail_bindings: Sequence[SurfaceDetailBinding | dict[str, Any]] = (),
    detail_pattern: str = "none",
    output_relative_dir: str | None = None,
    overwrite: bool = False,
    attach: bool = True,
) -> dict[str, Any]:
    """Generate deterministic local PBR maps and optionally connect them to a job plan."""

    if attach:
        _attachment_context(job_id, material_id)
    root = job_dir(job_id).resolve()
    output_dir = (
        resolve_job_path(root, output_relative_dir, "procedural texture output directory")
        if output_relative_dir is not None
        else None
    )
    result = generate_procedural_pbr(
        job_id,
        material_id,
        preset=preset,
        channels=channels,
        resolution=resolution,
        seed=seed,
        intended_scale_m=intended_scale_m,
        prompt=prompt,
        uv_set=uv_set,
        surface_detail_ids=surface_detail_ids,
        surface_detail_bindings=surface_detail_bindings,
        detail_pattern=detail_pattern,
        output_dir=output_dir,
        overwrite=overwrite,
    )
    relative_manifest = result.manifest_path.relative_to(root).as_posix()
    if attach:
        attach_texture_manifest_to_plan(
            job_id,
            material_id,
            relative_manifest,
            shader_family=shader_family_for_preset(preset),
        )
    return {
        "job_id": job_id,
        "material_id": material_id,
        "provider": "cbm_pillow_procedural",
        "preset": preset,
        "seed": seed,
        "detail_pattern": detail_pattern,
        "attached": attach,
        "manifest_path": str(result.manifest_path),
        "manifest_relative_path": relative_manifest,
        "channel_paths": {name: str(path) for name, path in result.channel_paths.items()},
        "channel_sha256": result.channel_sha256,
        "manifest": result.manifest.model_dump(mode="json"),
    }


def get_material_family_presets() -> dict[str, dict[str, Any]]:
    """Expose immutable-by-copy material family presets for CLI/MCP adapters."""

    return list_material_family_presets()
