from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_blender_modeler.build_provenance import (
    BuildProvenanceError,
    canonical_json_text,
    collect_build_provenance,
    require_matching_build_provenance,
    sha256_file,
)
from codex_blender_modeler.models import CameraSpec
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint


def _provenance_job(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Create a complete job whose external geometry and image texture are build inputs."""

    root = tmp_path / "provenance_test"
    analysis = root / "analysis"
    geometry = root / "geometry"
    recipe_dir = root / "materials" / "mat.test"
    texture_dir = root / "textures" / "mat.test"
    for directory in (analysis, geometry, recipe_dir, texture_dir):
        directory.mkdir(parents=True, exist_ok=True)

    geometry_path = geometry / "body.mesh.json"
    geometry_path.write_text(
        json.dumps(
            {
                "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                "faces": [[0, 1, 2]],
            }
        ),
        encoding="utf-8",
    )
    image_path = texture_dir / "base_color.png"
    image_path.write_bytes(b"source-image")
    manifest_path = texture_dir / "texture_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "uv_set": "UVMap",
                "intended_scale_m": 1.0,
                "resolution": [64, 64],
                "source_type": "image",
                "channels": {
                    "base_color": {
                        "source": "image",
                        "path": "base_color.png",
                        "color_space": "sRGB",
                    }
                },
                "procedural": {},
            }
        ),
        encoding="utf-8",
    )
    recipe_path = recipe_dir / "shader_recipe.json"
    recipe_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "family": "standard_pbr",
                "mapping": {
                    "mode": "uv",
                    "uv_set": "UVMap",
                    "real_world_scale_m": 1.0,
                },
                "texture_manifest": "textures/mat.test/texture_manifest.json",
            }
        ),
        encoding="utf-8",
    )
    scene_spec_path = analysis / "scene_spec.json"
    scene_spec_path.write_text(
        json.dumps(
            {
                "job_id": "provenance_test",
                "camera": {
                    "projection": "ORTHO",
                    "location": [3, -4, 2],
                    "target": [0, 0, 0],
                    "focal_length_mm": 50,
                    "ortho_scale": 5,
                    "resolution": [64, 64],
                },
                "materials": [{"id": "mat.test"}],
                "objects": [
                    {
                        "id": "asset.body",
                        "geometry": {
                            "kind": "custom_mesh",
                            "path": "geometry/body.mesh.json",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (analysis / "material_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": "provenance_test",
                "materials": [
                    {
                        "material_id": "mat.test",
                        "shader_family": "standard_pbr",
                        "texture_strategy": "image",
                        "mapping": {
                            "mode": "uv",
                            "uv_set": "UVMap",
                            "real_world_scale_m": 1.0,
                        },
                        "texture_manifest": "textures/mat.test/texture_manifest.json",
                        "shader_recipe": "materials/mat.test/shader_recipe.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root, scene_spec_path, geometry_path, recipe_path


def test_build_provenance_tracks_every_external_build_input(tmp_path: Path) -> None:
    """The canonical fingerprint covers camera, geometry, plan, recipe, manifest, and maps."""

    root, scene_spec_path, geometry_path, _ = _provenance_job(tmp_path)
    provenance = collect_build_provenance(root, "provenance_test")
    scene_spec = json.loads(scene_spec_path.read_text(encoding="utf-8"))
    material = provenance["materials"]["mat.test"]
    normalized_camera = CameraSpec.model_validate(scene_spec["camera"]).model_dump(mode="json")

    assert provenance["camera_fingerprint"] == camera_fingerprint(normalized_camera)
    assert provenance["geometry_payloads_sha256"] == {
        "geometry/body.mesh.json": sha256_file(geometry_path)
    }
    assert material["texture_manifest_sha256"] is not None
    assert material["texture_channels"]["base_color"]["sha256"] == sha256_file(
        root / "textures" / "mat.test" / "base_color.png"
    )
    assert require_matching_build_provenance(
        canonical_json_text(provenance), provenance["fingerprint"]
    ) == provenance


@pytest.mark.parametrize("source", ["recipe", "geometry", "texture"])
def test_changed_build_input_requires_rebuild_before_bake(
    tmp_path: Path,
    source: str,
) -> None:
    """Any changed external material or geometry input invalidates the embedded blend state."""

    root, _, geometry_path, recipe_path = _provenance_job(tmp_path)
    built = collect_build_provenance(root, "provenance_test")
    if source == "recipe":
        recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        recipe["surface"] = {"roughness": 0.73}
        recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    elif source == "geometry":
        geometry_path.write_text(
            geometry_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
    else:
        (root / "textures" / "mat.test" / "base_color.png").write_bytes(b"changed-image")
    current = collect_build_provenance(root, "provenance_test")

    assert current["fingerprint"] != built["fingerprint"]
    with pytest.raises(BuildProvenanceError, match="rebuild before baking"):
        require_matching_build_provenance(
            canonical_json_text(built),
            current["fingerprint"],
        )
