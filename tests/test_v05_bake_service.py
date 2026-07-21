from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from codex_blender_modeler import baking
from codex_blender_modeler.build_provenance import collect_build_provenance


def _built_job(tmp_path: Path, monkeypatch) -> Path:
    """Create one isolated built job for host bake-service tests."""

    root = tmp_path / "workspaces" / "bake_test"
    blend = root / "blender" / "scene.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"blend")
    analysis = root / "analysis"
    recipe_dir = root / "materials" / "mat.test"
    analysis.mkdir(parents=True)
    recipe_dir.mkdir(parents=True)
    (analysis / "scene_spec.json").write_text(
        json.dumps(
            {
                "job_id": "bake_test",
                "camera": {
                    "projection": "ORTHO",
                    "location": [3.0, -4.0, 2.0],
                    "target": [0.0, 0.0, 0.0],
                    "focal_length_mm": 50.0,
                    "ortho_scale": 5.0,
                    "resolution": [64, 64],
                },
                "materials": [{"id": "mat.test"}],
                "objects": [],
            }
        ),
        encoding="utf-8",
    )
    (analysis / "material_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": "bake_test",
                "materials": [
                    {
                        "material_id": "mat.test",
                        "shader_family": "standard_pbr",
                        "texture_strategy": "procedural",
                        "mapping": {
                            "mode": "uv",
                            "uv_set": "UVMap",
                            "real_world_scale_m": 1.0,
                        },
                        "shader_recipe": "materials/mat.test/shader_recipe.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (recipe_dir / "shader_recipe.json").write_text(
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    return root


def _fake_bake_result(args: list[str], *, ok: bool = True) -> None:
    """Write a complete or failed Blender report at the paths passed by the host."""

    root = Path(args[args.index("--job-root") + 1])
    report_path = Path(args[args.index("--report") + 1])
    output_path = root / "bakes" / "mat.test" / "gltf_pbr" / "base_color.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"png")
    digest = hashlib.sha256(b"png").hexdigest()
    provenance = collect_build_provenance(root, "bake_test")
    material_source = provenance["materials"]["mat.test"]
    blend_digest = hashlib.sha256((root / "blender" / "scene.blend").read_bytes()).hexdigest()
    manifest_path = output_path.parent / "bake_manifest.json"
    manifest = {
        "schema_version": "0.5.0",
        "job_id": "bake_test",
        "material_id": "mat.test",
        "source_shader_recipe": "materials/mat.test/shader_recipe.json",
        "source_scene_spec_sha256": provenance["scene_spec_sha256"],
        "source_geometry_payloads_sha256": provenance["geometry_payloads_sha256"],
        "source_camera_fingerprint": provenance["camera_fingerprint"],
        "source_material_plan_sha256": provenance["material_plan_sha256"],
        "source_shader_recipe_sha256": material_source["shader_recipe_sha256"],
        "source_texture_manifest": None,
        "source_texture_manifest_sha256": None,
        "source_texture_channels_sha256": {},
        "source_blend_sha256": blend_digest,
        "source_build_fingerprint": provenance["fingerprint"],
        "source_material_fingerprint": material_source["fingerprint"],
        "profile": "gltf_pbr",
        "resolution": [64, 64],
        "uv_set": "UVMap",
        "margin_px": 4,
        "outputs": (
            [
                {
                    "channel": "base_color",
                    "path": "bakes/mat.test/gltf_pbr/base_color.png",
                    "color_space": "sRGB",
                    "sha256": digest,
                }
            ]
            if ok
            else []
        ),
        "status": "complete" if ok else "failed",
        "blender_version": "5.0.1",
        "notes": [] if ok else ["UVMap is missing"],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": "bake_test",
                "ok": ok,
                "profile": "gltf_pbr",
                "resolution": [64, 64],
                "manifest_paths": ["bakes/mat.test/gltf_pbr/bake_manifest.json"],
                "failed_material_ids": [] if ok else ["mat.test"],
                "source_blend_sha256": blend_digest,
                "source_build_fingerprint": provenance["fingerprint"],
            }
        ),
        encoding="utf-8",
    )


def test_bake_service_validates_manifests_and_hashes(tmp_path: Path, monkeypatch) -> None:
    """The public host API returns only schema-validated and hash-verified bake outputs."""

    _built_job(tmp_path, monkeypatch)
    calls = []

    def fake_run(script: str, args: list[str], blend_file: Path | None = None):
        """Capture the bounded Blender invocation and emit its deterministic report."""

        calls.append((script, args, blend_file))
        _fake_bake_result(args)

    monkeypatch.setattr("codex_blender_modeler.baking.service.run_blender", fake_run)
    report = baking.bake_job_materials(
        "bake_test",
        profile="gltf_pbr",
        resolution=64,
        margin_px=4,
        material_ids=["mat.test"],
    )

    assert report["ok"] is True
    assert report["manifests"][0]["status"] == "complete"
    assert calls[0][0] == "bake_materials.py"
    assert calls[0][2] is not None
    assert "--expected-build-fingerprint" in calls[0][1]
    assert "--source-blend-sha256" in calls[0][1]


def test_bake_service_reports_unsupported_uv_as_explicit_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Strict mode raises with the validated failed manifest instead of hiding UV errors."""

    _built_job(tmp_path, monkeypatch)

    def fake_run(script: str, args: list[str], blend_file: Path | None = None):
        """Emit a Blender-style failure report for a material without approved UVs."""

        assert script == "bake_materials.py"
        _fake_bake_result(args, ok=False)

    monkeypatch.setattr("codex_blender_modeler.baking.service.run_blender", fake_run)
    with pytest.raises(baking.BakeJobError, match="mat.test") as captured:
        baking.bake_job_materials(
            "bake_test",
            profile="gltf_pbr",
            resolution=64,
            margin_px=4,
        )
    assert captured.value.report["manifests"][0]["status"] == "failed"


def test_bake_service_rejects_unimplemented_unity_packing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """V0.5 never labels separate raw channels as a Unity-packed material set."""

    _built_job(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="runtime-specific channel packing"):
        baking.bake_job_materials(
            "bake_test",
            profile="unity_urp_lit",  # type: ignore[arg-type]
            resolution=64,
        )
