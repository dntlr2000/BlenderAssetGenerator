"""Keep Standard and AQ material readers exact below Windows MAX_PATH boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codex_blender_modeler.autonomy_v2.material_phase_service import (
    MaterialPhaseError,
    _validate_material_plan_dependencies,
)
from codex_blender_modeler.blender_artifacts import native_io_path, sha256_file
from codex_blender_modeler.material_manifest import MaterialManifestError, load_material_manifest
from codex_blender_modeler.materials import (
    MaterialPlan,
    MaterialPlanItem,
    ShaderRecipe,
    load_material_plan,
    load_shader_recipe,
    validate_material_contracts,
)
from codex_blender_modeler.shader_recipe_runtime import (
    load_runtime_material_mappings,
    load_runtime_shader_recipes,
)
from codex_blender_modeler.texturing.manifest import load_texture_manifest


def _write_bytes(path: Path, payload: bytes) -> None:
    """Write a test-owned dependency through the existing native I/O boundary."""

    os.makedirs(native_io_path(path.parent), exist_ok=True)
    with open(native_io_path(path), "wb") as handle:
        handle.write(payload)


def _write_json(path: Path, payload: dict) -> None:
    """Serialize a fixture without relying on short-path pathlib I/O."""

    _write_bytes(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def _material_bundle(root: Path) -> tuple[MaterialPlan, dict[str, Path], dict[str, str]]:
    """Create an exact recipe, image manifest, mask, and plan at campaign-scale depth."""

    dependency_root = root.joinpath(
        "production",
        "autonomy_v2",
        "aq-session-" + "a" * 32,
        "material_inputs",
        "material-candidate-" + "b" * 56,
        "dependency-set-" + "c" * 56,
    )
    paths = {
        "plan": dependency_root / "analysis" / "material_plan.json",
        "recipe": dependency_root / "shader_recipes" / "mat_panel.json",
        "manifest": dependency_root / "textures" / "mat_panel" / "texture_manifest.json",
        "image": dependency_root / "textures" / "mat_panel" / "base_color.png",
        "mask": dependency_root / "textures" / "mat_panel" / "masks" / "detail.png",
    }
    assert all(len(os.path.abspath(path)) > 260 for path in paths.values())
    _write_bytes(paths["image"], b"exact-base-color-fixture")
    _write_bytes(paths["mask"], b"exact-mask-fixture")
    manifest_relative = paths["manifest"].relative_to(root).as_posix()
    _write_json(
        paths["manifest"],
        {
            "schema_version": "0.5.0",
            "material_id": "mat.panel",
            "uv_set": "UVMap",
            "intended_scale_m": 1.0,
            "resolution": [32, 32],
            "source_type": "image",
            "channels": {
                "base_color": {
                    "source": "image",
                    "path": "base_color.png",
                    "color_space": "sRGB",
                }
            },
            "procedural": {},
            "provenance": {
                "provider": "fixture",
                "generated_sha256": {"base_color": sha256_file(paths["image"])},
            },
            "surface_detail_ids": ["detail.panel"],
            "surface_detail_bindings": [
                {
                    "detail_id": "detail.panel",
                    "parent_object_id": "panel",
                    "material_id": "mat.panel",
                    "uv_set": "UVMap",
                    "uv_layout_sha256": "a" * 64,
                    "placement": {
                        "mode": "mask_image",
                        "mask_path": "masks/detail.png",
                        "mask_sha256": sha256_file(paths["mask"]),
                    },
                    "channels": ["base_color"],
                    "strength": 1.0,
                    "wrap": "clamp",
                }
            ],
        },
    )
    recipe = ShaderRecipe(
        material_id="mat.panel",
        mapping={"mode": "uv", "uv_set": "UVMap"},
        texture_manifest=manifest_relative,
    )
    _write_json(paths["recipe"], recipe.model_dump(mode="json"))
    plan = MaterialPlan(
        job_id="material_path_fixture",
        stage="authored",
        surface_detail_binding_policy="spatial_v1",
        materials=[
            MaterialPlanItem(
                material_id="mat.panel",
                label="Panel",
                texture_strategy="image",
                mapping=recipe.mapping,
                texture_manifest=manifest_relative,
                shader_recipe=paths["recipe"].relative_to(root).as_posix(),
            )
        ],
    )
    _write_json(paths["plan"], plan.model_dump(mode="json"))
    inputs = {path.relative_to(root).as_posix(): sha256_file(path) for path in paths.values()}
    return plan, paths, inputs


@pytest.mark.parametrize("contract", ["plan", "recipe", "manifest"])
def test_versioned_material_loaders_support_long_paths(tmp_path: Path, contract: str) -> None:
    """Load strict V0.5 contracts without changing any serialized source bytes."""

    plan, paths, inputs = _material_bundle(tmp_path)
    loader = {
        "plan": load_material_plan,
        "recipe": load_shader_recipe,
        "manifest": load_texture_manifest,
    }[contract]
    loaded = loader(paths[contract])
    assert loaded.schema_version == "0.5.0"
    if contract == "plan":
        assert loaded == plan
    else:
        assert loaded.material_id == "mat.panel"
    assert inputs == {
        path.relative_to(tmp_path).as_posix(): sha256_file(path) for path in paths.values()
    }


def test_standard_material_validation_accepts_long_dependencies(tmp_path: Path) -> None:
    """Standard validation resolves the same deep recipe, image, and exact mask."""

    plan, _paths, _inputs = _material_bundle(tmp_path)
    report = validate_material_contracts(
        plan,
        {"job_id": plan.job_id, "materials": [{"id": "mat.panel"}]},
        tmp_path,
    )
    assert report.ok, report.model_dump(mode="json")
    assert report.failed == 0


@pytest.mark.parametrize("deep_job_root", [False, True])
def test_blender_runtime_material_readers_support_long_paths(
    tmp_path: Path, deep_job_root: bool
) -> None:
    """Keep Blender's stdlib readers aligned with host plan and dependency loading."""

    root = tmp_path
    if deep_job_root:
        root = root.joinpath(*[f"nested-job-{index}-" + "d" * 48 for index in range(4)])
        assert len(os.path.abspath(root)) > 260
    plan, paths, _inputs = _material_bundle(root)
    _write_json(root / "analysis" / "material_plan.json", plan.model_dump(mode="json"))
    _write_json(
        root / "analysis" / "scene_spec.json",
        {"job_id": plan.job_id, "materials": [{"id": "mat.panel"}]},
    )
    recipes = load_runtime_shader_recipes(root, plan.job_id)
    assert recipes["mat.panel"]["cbm_texture_manifest_path"] == str(paths["manifest"])
    mappings = load_runtime_material_mappings(root, plan.job_id)
    assert mappings["mat.panel"]["mode"] == "uv"
    assert mappings["mat.panel"]["uv_set"] == "UVMap"


def test_aq_material_dependencies_accept_exact_long_paths(tmp_path: Path) -> None:
    """AQ request binding accepts valid deep dependencies before any promotion."""

    plan, _paths, inputs = _material_bundle(tmp_path)
    _validate_material_plan_dependencies(tmp_path, plan, inputs)


@pytest.mark.parametrize("dependency", ["recipe", "manifest", "image"])
def test_aq_material_long_paths_do_not_relax_exact_input_hashes(
    tmp_path: Path, dependency: str
) -> None:
    """A readable long path still needs its exact immutable request hash."""

    plan, paths, inputs = _material_bundle(tmp_path)
    inputs[paths[dependency].relative_to(tmp_path).as_posix()] = "0" * 64
    with pytest.raises(MaterialPhaseError, match="exact immutable controller input"):
        _validate_material_plan_dependencies(tmp_path, plan, inputs)


@pytest.mark.parametrize("dependency", ["image", "mask"])
def test_material_long_paths_reject_changed_image_and_mask_bytes(
    tmp_path: Path, dependency: str
) -> None:
    """Native reads retain channel-provenance and spatial-mask tamper rejection."""

    plan, paths, _inputs = _material_bundle(tmp_path)
    _write_bytes(paths[dependency], b"changed-fixture")
    with pytest.raises(MaterialManifestError, match="differs"):
        load_material_manifest(
            {"id": "mat.panel", "texture_manifest": plan.materials[0].texture_manifest},
            tmp_path,
        )


def test_material_long_paths_still_reject_dependency_escape(tmp_path: Path) -> None:
    """A deep dependency cannot use traversal to leave its owning job root."""

    root = tmp_path / "job"
    plan, paths, _inputs = _material_bundle(root)
    with open(native_io_path(paths["manifest"]), encoding="utf-8") as handle:
        manifest = json.load(handle)
    outside = tmp_path / "outside.png"
    _write_bytes(outside, b"outside-fixture")
    manifest["channels"]["base_color"]["path"] = Path(
        os.path.relpath(outside, paths["manifest"].parent)
    ).as_posix()
    _write_json(paths["manifest"], manifest)
    with pytest.raises(MaterialManifestError, match="must stay inside job root"):
        load_material_manifest(
            {"id": "mat.panel", "texture_manifest": plan.materials[0].texture_manifest},
            root,
        )
