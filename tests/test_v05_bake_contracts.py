from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from codex_blender_modeler.baking import BakeManifest, BakeOutput, load_bake_manifest


def _complete_provenance() -> dict[str, object]:
    """Return the minimum immutable input fingerprints required by a complete bake."""

    return {
        "source_scene_spec_sha256": "2" * 64,
        "source_geometry_payloads_sha256": {"geometry/body.mesh.json": "3" * 64},
        "source_camera_fingerprint": "4" * 64,
        "source_material_plan_sha256": "5" * 64,
        "source_shader_recipe_sha256": "6" * 64,
        "source_texture_manifest": None,
        "source_texture_manifest_sha256": None,
        "source_texture_channels_sha256": {},
        "source_blend_sha256": "7" * 64,
        "source_build_fingerprint": "8" * 64,
        "source_material_fingerprint": "9" * 64,
    }


def test_bake_manifest_round_trip_and_schema(tmp_path: Path) -> None:
    """Portable bake outputs validate through Pydantic and JSON Schema."""

    manifest = BakeManifest(
        job_id="material_test",
        material_id="mat.stone",
        source_shader_recipe="materials/mat.stone/shader_recipe.json",
        profile="gltf_pbr",
        resolution=(1024, 1024),
        status="complete",
        **_complete_provenance(),
        outputs=[
            BakeOutput(
                channel="base_color",
                path="bakes/gltf_pbr/mat.stone/base_color.png",
                color_space="sRGB",
                sha256="0" * 64,
            ),
            BakeOutput(
                channel="normal",
                path="bakes/gltf_pbr/mat.stone/normal.png",
                color_space="Non-Color",
                sha256="1" * 64,
            ),
        ],
    )
    path = tmp_path / "bake_manifest.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    assert load_bake_manifest(path) == manifest
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "bake_manifest.schema.json").read_text())
    errors = list(Draft202012Validator(schema).iter_errors(manifest.model_dump(mode="json")))
    assert not errors, [error.message for error in errors]


def test_complete_bake_rejects_duplicate_channels() -> None:
    """A bake cannot silently replace one output with another of the same channel."""

    output = BakeOutput(
        channel="normal",
        path="normal.png",
        color_space="Non-Color",
        sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="unique"):
        BakeManifest(
            job_id="material_test",
            material_id="mat.stone",
            source_shader_recipe="materials/mat.stone/shader_recipe.json",
            profile="gltf_pbr",
            resolution=(512, 512),
            status="complete",
            **_complete_provenance(),
            outputs=[output, output],
        )


def test_complete_bake_requires_output_integrity_hashes() -> None:
    """Complete bake manifests cannot claim unhashed artifacts."""

    with pytest.raises(ValueError, match="SHA-256"):
        BakeManifest(
            job_id="material_test",
            material_id="mat.stone",
            source_shader_recipe="materials/mat.stone/shader_recipe.json",
            profile="gltf_pbr",
            resolution=(512, 512),
            status="complete",
            **_complete_provenance(),
            outputs=[
                BakeOutput(channel="normal", path="normal.png", color_space="Non-Color")
            ],
        )


def test_complete_bake_requires_source_provenance() -> None:
    """A complete derived bake cannot omit the build and source-file fingerprints."""

    with pytest.raises(ValueError, match="provenance fields"):
        BakeManifest(
            job_id="material_test",
            material_id="mat.stone",
            source_shader_recipe="materials/mat.stone/shader_recipe.json",
            profile="gltf_pbr",
            resolution=(64, 64),
            status="complete",
            outputs=[
                BakeOutput(
                    channel="base_color",
                    path="base_color.png",
                    color_space="sRGB",
                    sha256="0" * 64,
                )
            ],
        )
