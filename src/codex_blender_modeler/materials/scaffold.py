from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from uuid import uuid4

from ..material_manifest import load_material_manifest
from ..validation import load_scene_spec
from ..workspace import job_dir
from .models import MappingSpec, MaterialPlan, MaterialPlanItem, ShaderRecipe, SurfaceSpec

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def material_directory_name(material_id: str) -> str:
    """Create a deterministic, traversal-safe directory name for one material ID."""

    if _SAFE_COMPONENT.fullmatch(material_id) and material_id not in {".", ".."}:
        return material_id
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", material_id).strip("._-") or "material"
    digest = hashlib.sha256(material_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:48]}-{digest}"


def _material_directory_name(material_id: str) -> str:
    """Preserve the original private helper for existing internal callers."""

    return material_directory_name(material_id)


def _surface_from_scene_material(material: dict) -> tuple[str, SurfaceSpec]:
    """Translate legacy SceneSpec material defaults into a portable shader surface."""

    shader = str(material.get("shader", "principled"))
    family = {
        "principled": "standard_pbr",
        "water": "water",
        "glass": "glass",
        "emissive": "emissive",
        "cloud": "cloud",
    }[shader]
    color = tuple(float(value) for value in material.get("base_color", [0.8, 0.8, 0.8, 1.0]))
    roughness = float(material.get("roughness", 0.5))
    metallic = float(material.get("metallic", 0.0))
    values = {
        "base_color": color,
        "roughness": roughness,
        "metallic": metallic,
        "ior": 1.5,
    }
    if shader == "water":
        values.update(
            ior=1.333,
            transmission_weight=0.85,
            roughness=min(roughness, 0.18),
            alpha=min(color[3], 0.82),
        )
    elif shader == "glass":
        values.update(
            ior=1.45,
            transmission_weight=1.0,
            roughness=min(roughness, 0.18),
            alpha=min(color[3], 0.82),
        )
    elif shader == "cloud":
        values.update(
            metallic=0.0,
            roughness=max(roughness, 0.7),
            alpha=min(color[3], 0.85),
        )
    elif shader == "emissive":
        values.update(
            emission_color=color,
            emission_strength=float(material.get("emission_strength", 3.0)),
        )
    return family, SurfaceSpec(**values)


def _manifest_settings(material: dict, root: Path) -> tuple[str, MappingSpec]:
    """Read an existing texture manifest or choose recipe-only procedural defaults."""

    if not material.get("texture_manifest"):
        return "procedural", MappingSpec(mode="object", uv_set="UVMap", real_world_scale_m=1.0)
    manifest, _ = load_material_manifest(material, root)
    if manifest is None:
        return "procedural", MappingSpec(mode="object", uv_set="UVMap", real_world_scale_m=1.0)
    uv_set = str(manifest["uv_set"])
    mode = {"UVMap": "uv", "Generated": "generated", "Object": "object"}[uv_set]
    return str(manifest["source_type"]), MappingSpec(
        mode=mode,
        uv_set=uv_set,
        real_world_scale_m=float(manifest["intended_scale_m"]),
    )


def _write_atomic(path: Path, content: str) -> None:
    """Atomically replace one generated contract file after its parent exists."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _material_scaffold_payload(
    job_id: str,
    root: Path,
    scene_spec: dict,
    recipe_root: Path,
    *,
    compact_paths: bool = False,
) -> tuple[MaterialPlan, list[tuple[Path, ShaderRecipe]]]:
    """Build one scaffold payload for a caller-selected contained recipe directory."""

    recipes: list[tuple[Path, ShaderRecipe]] = []
    plan_items: list[MaterialPlanItem] = []
    for material in sorted(scene_spec["materials"], key=lambda item: item["id"]):
        material_id = str(material["id"])
        family, surface = _surface_from_scene_material(material)
        texture_strategy, mapping = _manifest_settings(material, root)
        recipe_component = (
            hashlib.sha256(material_id.encode("utf-8")).hexdigest()[:12]
            if compact_paths
            else material_directory_name(material_id)
        )
        recipe_filename = "recipe.json" if compact_paths else "shader_recipe.json"
        recipe_relative = (
            recipe_root
            / recipe_component
            / recipe_filename
        ).as_posix()
        recipe = ShaderRecipe(
            material_id=material_id,
            family=family,
            surface=surface,
            mapping=mapping,
            texture_manifest=material.get("texture_manifest"),
            bake_required=texture_strategy in {"image", "hybrid"},
            assumptions=["Generated from approved SceneSpec material defaults."],
        )
        recipes.append((root / recipe_relative, recipe))
        plan_items.append(
            MaterialPlanItem(
                material_id=material_id,
                label=str(material.get("name", material_id)),
                shader_family=family,
                texture_strategy=texture_strategy,
                mapping=mapping,
                texture_manifest=material.get("texture_manifest"),
                shader_recipe=recipe_relative,
                evidence_status="observed",
                confidence=1.0,
                notes=["Scaffold preserves the current SceneSpec material appearance."],
            )
        )

    plan = MaterialPlan(
        job_id=job_id,
        scene_spec_path="analysis/scene_spec.json",
        stage="scaffold",
        materials=plan_items,
        global_notes=[
            "Review and approve material evidence before texture generation or baking."
        ],
    )
    return plan, recipes


def _write_scaffold_payload(
    plan_path: Path,
    plan: MaterialPlan,
    recipes: list[tuple[Path, ShaderRecipe]],
    *,
    overwrite: bool,
) -> None:
    """Persist one scaffold bundle only after checking every planned destination."""

    if not overwrite:
        conflicts = [path for path, _ in recipes if path.exists()]
        if plan_path.exists():
            conflicts.insert(0, plan_path)
        if conflicts:
            raise FileExistsError(
                "Material scaffold file already exists and was not modified: "
                + ", ".join(str(path) for path in conflicts)
            )
    for path, recipe in recipes:
        _write_atomic(path, recipe.model_dump_json(indent=2) + "\n")
    _write_atomic(plan_path, plan.model_dump_json(indent=2) + "\n")


def create_material_scaffold(job_id: str, *, overwrite: bool = False) -> MaterialPlan:
    """Create the legacy canonical material plan and recipes from one SceneSpec."""

    root = job_dir(job_id)
    scene_spec_path = root / "analysis" / "scene_spec.json"
    scene_spec = load_scene_spec(scene_spec_path).model_dump(mode="json")
    plan_path = root / "analysis" / "material_plan.json"
    plan, recipes = _material_scaffold_payload(
        job_id,
        root,
        scene_spec,
        Path("materials"),
    )
    _write_scaffold_payload(plan_path, plan, recipes, overwrite=overwrite)
    return plan


def create_workflow_material_candidates(
    job_id: str,
    workflow_id: str,
) -> dict[str, str]:
    """Create separate immutable scaffold and agent-authored candidate bundles."""

    root = job_dir(job_id)
    scene_spec = load_scene_spec(
        root / "analysis" / "scene_spec.json"
    ).model_dump(mode="json")
    material_root = (
        Path("workflows")
        / workflow_id
        / "artifacts"
        / "m"
    )
    if (root / material_root).exists():
        raise FileExistsError(
            "Workflow material artifact root already exists and was not modified: "
            f"{root / material_root}"
        )
    results: dict[str, str] = {}
    for bundle_name in ("scaffold", "authored"):
        bundle_root = material_root / bundle_name
        plan_path = root / bundle_root / "material_plan.json"
        recipe_root = bundle_root / "recipes"
        plan, recipes = _material_scaffold_payload(
            job_id,
            root,
            scene_spec,
            recipe_root,
            compact_paths=True,
        )
        _write_scaffold_payload(plan_path, plan, recipes, overwrite=False)
        results[f"{bundle_name}_root"] = bundle_root.as_posix()
        results[f"{bundle_name}_plan"] = (
            bundle_root / "material_plan.json"
        ).as_posix()
    return results
