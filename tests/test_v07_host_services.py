from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from codex_blender_modeler.optimization.io import latest_complete_run_id, run_directory
from codex_blender_modeler.optimization.models import Bounds3D
from codex_blender_modeler.optimization.profiles import create_builtin_profile
from codex_blender_modeler.optimization.service import initialize_asset_profile
from codex_blender_modeler.packaging.service import (
    _bounded_resolution,
    _bounds_error,
    _canonical_texture_contracts,
    _copy_canonical_image_channels,
    _delivery_mapping,
    _embedded_absolute_path_findings,
    _gltf_packed_textures,
    _latest_bake_manifests,
    _package_id,
    _require_collider_export,
    _roundtrip_object_sets_match,
    _verify_package_receipts,
    validate_asset_package,
)
from codex_blender_modeler.workspace import sha256_file


def test_embedded_absolute_path_audit_covers_text_utf8_and_utf16(tmp_path: Path) -> None:
    """Reject Windows, UNC, and common POSIX absolute paths embedded in package files."""

    clean = tmp_path / "clean.glb"
    clean.write_bytes(b'glTF{"uri":"textures/base_color.png"}')
    windows = tmp_path / "windows.glb"
    windows.write_bytes(b'{"source":"E:\\\\private.json"}')
    unc = tmp_path / "asset.fbx"
    unc.write_bytes("\\\\server\\share\\asset.png".encode("utf-16le"))
    posix = tmp_path / "asset.obj"
    posix.write_text("# /workspace/artist/private/source.blend", encoding="utf-8")
    false_binary = tmp_path / "false.fbx"
    false_binary.write_bytes(b"K:\\Kyi/Ew")

    assert _embedded_absolute_path_findings([clean], tmp_path) == []
    findings = _embedded_absolute_path_findings([windows, unc, posix, false_binary], tmp_path)
    assert len(findings) == 3
    assert any(":windows:" in finding for finding in findings)
    assert any(":utf16le:" in finding for finding in findings)
    assert any(":posix:" in finding for finding in findings)


def _write_texture_contract_fixture(root: Path) -> tuple[Path, Path, Path]:
    """Create one image/procedural TextureManifest whose recipe does not request baking."""

    image_path = root / "textures" / "mat.test" / "base_color.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (4, 3), color=(12, 34, 56)).save(image_path)
    manifest_path = image_path.parent / "texture_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "uv_set": "UVMap",
                "intended_scale_m": 1.0,
                "resolution": [4, 3],
                "source_type": "hybrid",
                "channels": {
                    "base_color": {
                        "source": "image",
                        "path": "base_color.png",
                        "color_space": "sRGB",
                    },
                    "roughness": {"source": "procedural"},
                },
                "procedural": {
                    "noise": {"scale": 2.0},
                    "roughness_ramp": [
                        [0.0, [0.2, 0.2, 0.2, 1.0]],
                        [1.0, [0.8, 0.8, 0.8, 1.0]],
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    recipe_path = root / "materials" / "mat.test" / "shader_recipe.json"
    recipe_path.parent.mkdir(parents=True)
    recipe_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "texture_manifest": "textures/mat.test/texture_manifest.json",
                "bake_required": False,
            }
        ),
        encoding="utf-8",
    )
    plan_path = root / "analysis" / "material_plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": "portable_asset_case",
                "stage": "authored",
                "materials": [
                    {
                        "material_id": "mat.test",
                        "label": "Test",
                        "texture_strategy": "hybrid",
                        "texture_manifest": "textures/mat.test/texture_manifest.json",
                        "shader_recipe": "materials/mat.test/shader_recipe.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return image_path, manifest_path, recipe_path


def test_asset_profile_initialization_is_job_scoped_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist one profile inside its job without changing an identical second request."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    first = initialize_asset_profile("portable_asset_case")
    profile_path = workspace / "portable_asset_case" / "asset_profiles" / "portable_gltf.json"
    before = profile_path.read_bytes()
    second = initialize_asset_profile("portable_asset_case")
    assert first == second
    assert profile_path.read_bytes() == before


def test_asset_profile_initialization_persists_pickup_delivery_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persist explicit pickup LOD, UV1, pivot, collider, and proxy budgets."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    profile = initialize_asset_profile(
        "pickup_profile_case",
        profile_id="fbx_interchange",
        lod_mode="disabled",
        generate_uv1=False,
        pivot_policy="bounds_center",
        collision_strategy="compound",
        budget_enforcement="fail",
        max_lod0_render_objects=16,
        max_lod0_material_slots=16,
        max_lod0_estimated_draw_calls=16,
        max_lod0_triangles=5000,
        max_collider_triangles=256,
    )

    assert profile.lod.enabled is False
    assert profile.uv.generate_uv1 is False
    assert profile.pivot_policy == "bounds_center"
    assert profile.collision.strategy == "compound"
    assert profile.budgets.enforcement == "fail"
    assert profile.budgets.max_lod0_triangles == 5000
    assert profile.budgets.max_lod0_estimated_draw_calls == 16
    assert profile.budgets.max_collider_triangles == 256


@pytest.mark.parametrize(
    "value",
    [
        "../escape",
        "nested/run",
        "nested\\run",
        ".hidden",
        "bad space",
        "bad:stream",
        "CON",
        "trailing.",
    ],
)
def test_run_directory_rejects_path_like_or_unstable_ids(
    tmp_path: Path,
    value: str,
) -> None:
    """Keep optimization run selection inside one stable job-owned directory."""

    with pytest.raises(ValueError, match="run_id"):
        run_directory(tmp_path, value)


@pytest.mark.parametrize(
    ("width", "height", "maximum", "expected"),
    [
        (1024, 512, 2048, (1024, 512)),
        (4096, 2048, 2048, (2048, 1024)),
        (1000, 4000, 2000, (500, 2000)),
    ],
)
def test_packed_texture_resolution_obeys_profile_maximum(
    width: int,
    height: int,
    maximum: int,
    expected: tuple[int, int],
) -> None:
    """Downscale derived packed maps proportionally without upscaling raw evidence."""

    assert _bounded_resolution(width, height, maximum) == expected


def test_package_id_validation_accepts_stable_ids_and_rejects_paths() -> None:
    """Require immutable package identifiers that cannot escape the profile directory."""

    profile = create_builtin_profile(
        "portable_asset_case",
        "portable_gltf",
        "static_prop",
    )
    assert _package_id(profile, "release.preview-01") == "release.preview-01"
    for invalid in (
        "../escape",
        "folder/package",
        ".hidden",
        "bad space",
        "bad:stream",
        "NUL",
        "trailing.",
    ):
        with pytest.raises(ValueError, match="package_id"):
            _package_id(profile, invalid)


def _receipt(path: Path, root: Path, *, receipt_id: str = "package.primary") -> SimpleNamespace:
    """Build one minimal package receipt fixture from an existing file."""

    return SimpleNamespace(
        id=receipt_id,
        path=path.relative_to(root).as_posix(),
        byte_size=path.stat().st_size,
        sha256=sha256_file(path),
    )


def test_package_receipts_verify_exact_root_hash_size_and_file_set(tmp_path: Path) -> None:
    """Accept only fully tracked files beneath the exact declared immutable package root."""

    root = tmp_path / "job"
    package_root = root / "exports" / "packages" / "portable_gltf" / "package-001"
    package_root.mkdir(parents=True)
    primary = package_root / "asset.glb"
    metadata = package_root / "metadata.json"
    manifest_path = package_root / "package_manifest.json"
    primary.write_bytes(b"portable asset")
    metadata.write_text("{}", encoding="utf-8")
    manifest_path.write_text("{}", encoding="utf-8")
    package = SimpleNamespace(
        package_root=package_root.relative_to(root).as_posix(),
        files=[_receipt(primary, root), _receipt(metadata, root, receipt_id="metadata")],
    )

    verified = _verify_package_receipts(root, package_root, package, manifest_path)

    assert set(verified) == {"package.primary", "metadata"}
    untracked = package_root / "untracked.bin"
    untracked.write_bytes(b"unexpected")
    with pytest.raises(RuntimeError, match="untracked files"):
        _verify_package_receipts(root, package_root, package, manifest_path)


def test_package_receipts_reject_changed_size_hash_and_declared_root(tmp_path: Path) -> None:
    """Reject package tampering and manifests that claim a different package root."""

    root = tmp_path / "job"
    package_root = root / "exports" / "packages" / "portable_gltf" / "package-001"
    package_root.mkdir(parents=True)
    primary = package_root / "asset.glb"
    manifest_path = package_root / "package_manifest.json"
    primary.write_bytes(b"before")
    manifest_path.write_text("{}", encoding="utf-8")
    receipt = _receipt(primary, root)
    package = SimpleNamespace(
        package_root=package_root.relative_to(root).as_posix(),
        files=[receipt],
    )
    primary.write_bytes(b"after-change")
    with pytest.raises(RuntimeError, match="size changed|SHA-256 changed"):
        _verify_package_receipts(root, package_root, package, manifest_path)
    primary.write_bytes(b"before")
    package.package_root = "exports/packages/portable_gltf/different"
    with pytest.raises(RuntimeError, match="package_root"):
        _verify_package_receipts(root, package_root, package, manifest_path)


def test_roundtrip_bounds_require_nonempty_exact_object_sets_and_aggregate_match() -> None:
    """Reject zero/partial object matches and measure the complete aggregate bounds."""

    assert not _roundtrip_object_sets_match([], [], [])
    expected = [{"name": "asset", "bbox_world": {"min": [0, 0, 0], "max": [1, 1, 1]}}]
    imported = [{"name": "asset.imported", "bbox_world": {"min": [0, 0, 0], "max": [2, 1, 1]}}]
    comparisons = [{"expected_name": "asset", "actual_name": "asset.imported"}]
    assert _roundtrip_object_sets_match(expected, imported, comparisons)
    assert (
        _bounds_error(
            Bounds3D(minimum=(0, 0, 0), maximum=(1, 1, 1)),
            Bounds3D(minimum=(0, 0, 0), maximum=(2, 1, 1)),
        )
        == 1.0
    )
    assert not _roundtrip_object_sets_match(expected, imported, [])


def test_required_collision_profile_cannot_omit_colliders() -> None:
    """Prohibit package flags that discard collision required by the asset profile."""

    profile = create_builtin_profile("portable_asset_case", "portable_gltf", "static_prop")
    assert profile.collision.strategy != "none"
    with pytest.raises(ValueError, match="include_colliders=false"):
        _require_collider_export(profile, False)
    _require_collider_export(profile, True)


def test_delivery_mapping_is_package_relative_and_preserves_stable_identity(
    tmp_path: Path,
) -> None:
    """Expose portable semantic, role, LOD, collider, and material mapping metadata."""

    staging = tmp_path / "package"
    staging.mkdir()
    primary = staging / "asset.glb"
    primary.write_bytes(b"asset")
    profile = create_builtin_profile("portable_asset_case", "portable_gltf", "static_prop")
    mapping = _delivery_mapping(
        "portable_asset_case",
        "run-001",
        profile,
        primary,
        staging,
        {
            "objects": [
                {
                    "name": "asset.body.LOD1",
                    "semantic_id": "asset.body",
                    "instance_index": 0,
                    "asset_role": "lod",
                    "lod_level": 1,
                    "material_ids": ["mat.body"],
                }
            ]
        },
    )

    assert mapping["primary_asset"] == "asset.glb"
    assert mapping["objects"][0]["semantic_id"] == "asset.body"
    assert mapping["objects"][0]["lod_level"] == 1
    assert mapping["objects"][0]["collider"] is False


def test_roundtrip_validation_failure_cleans_staging_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove run-owned validation staging when the clean Blender process fails."""

    root = tmp_path / "job"
    package_root = root / "exports" / "packages" / "portable_gltf" / "package-001"
    package_root.mkdir(parents=True)
    (package_root / "package_manifest.json").write_text("{}", encoding="utf-8")
    primary = package_root / "asset.glb"
    primary.write_bytes(b"asset")
    run_root = root / "optimization" / "runs" / "run-001"
    run_root.mkdir(parents=True)
    package = SimpleNamespace(
        job_id="portable_asset_case",
        profile_id="portable_gltf",
        package_id="package-001",
        run_id="run-001",
        files=[SimpleNamespace(id="package.primary", path="unused")],
        primary_file_id="package.primary",
    )
    monkeypatch.setattr(
        "codex_blender_modeler.packaging.service.load_feature_config",
        lambda: SimpleNamespace(features=SimpleNamespace(portable_asset_core=True)),
    )
    monkeypatch.setattr("codex_blender_modeler.packaging.service.job_dir", lambda _job: root)
    monkeypatch.setattr("codex_blender_modeler.packaging.service.load_model", lambda *_: package)
    monkeypatch.setattr(
        "codex_blender_modeler.packaging.service._verify_package_receipts",
        lambda *_: {"package.primary": primary},
    )
    monkeypatch.setattr(
        "codex_blender_modeler.packaging.service.run_blender",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Blender failed")),
    )

    with pytest.raises(RuntimeError, match="Blender failed"):
        validate_asset_package("portable_asset_case", "package-001")

    roundtrip = run_root / "roundtrip"
    assert not (roundtrip / "package-001").exists()
    assert not list(roundtrip.glob(".package-001.*.tmp"))


def test_bake_required_shader_recipe_requires_current_manifest_report(
    tmp_path: Path,
) -> None:
    """Fail packaging when an approved bake-required material has no complete bake report."""

    root = tmp_path / "job"
    (root / "analysis").mkdir(parents=True)
    recipe = root / "materials" / "mat.test" / "shader_recipe.json"
    recipe.parent.mkdir(parents=True)
    recipe.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "bake_required": True,
            }
        ),
        encoding="utf-8",
    )
    (root / "analysis" / "material_plan.json").write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": "portable_asset_case",
                "stage": "authored",
                "materials": [
                    {
                        "material_id": "mat.test",
                        "label": "Test",
                        "shader_recipe": "materials/mat.test/shader_recipe.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source = SimpleNamespace(build_fingerprint="a" * 64)

    with pytest.raises(RuntimeError, match="no reports/material_bakes.json"):
        _latest_bake_manifests(root, source)  # type: ignore[arg-type]


def test_texture_manifest_requires_bake_and_preserves_canonical_image_bytes(
    tmp_path: Path,
) -> None:
    """Require manifest-associated baking and copy every canonical image channel exactly."""

    root = tmp_path / "job"
    image_path, _, _ = _write_texture_contract_fixture(root)
    contracts, required, job_id = _canonical_texture_contracts(root)
    assert required == {"mat.test"}
    assert job_id == "portable_asset_case"
    assert contracts["mat.test"].procedural_channels == frozenset({"roughness"})

    source = SimpleNamespace(build_fingerprint="a" * 64)
    with pytest.raises(RuntimeError, match="TextureManifest-associated"):
        _latest_bake_manifests(root, source)  # type: ignore[arg-type]

    staging = root / "exports" / ".package.tmp"
    final = root / "exports" / "packages" / "portable_gltf" / "package-001"
    staging.mkdir(parents=True)
    records = _copy_canonical_image_channels(root, staging, final, contracts)
    assert len(records) == 1
    copied = next((staging / "textures" / "canonical").rglob("base_color.png"))
    assert copied.read_bytes() == image_path.read_bytes()
    assert records[0].output.sha256 == sha256_file(image_path)
    assert records[0].mappings[0].source.sha256 == sha256_file(image_path)
    assert records[0].mappings[0].source.path == "textures/mat.test/base_color.png"


def test_raw_pbr_sidecar_occlusion_is_hash_verified_and_packaged(
    tmp_path: Path,
) -> None:
    """Preserve sidecar-only Occlusion without changing the canonical TextureManifest."""

    root = tmp_path / "job"
    _, manifest_path, _ = _write_texture_contract_fixture(root)
    manifest_sha256 = sha256_file(manifest_path)
    occlusion_path = manifest_path.parent / "occlusion.png"
    Image.new("L", (4, 3), color=255).save(occlusion_path)
    sidecar_path = manifest_path.parent / "raw_pbr_channels.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "status": "authored_source_channels",
                "channels": {
                    "occlusion": {
                        "path": "occlusion.png",
                        "sha256": sha256_file(occlusion_path),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    contracts, _, _ = _canonical_texture_contracts(root)
    contract = contracts["mat.test"]
    assert contract.image_channels["occlusion"] == occlusion_path.resolve()
    assert contract.raw_sidecar_sha256 == sha256_file(sidecar_path)
    assert sha256_file(manifest_path) == manifest_sha256

    staging = root / "exports" / ".package.tmp"
    final = root / "exports" / "packages" / "portable_gltf" / "package-001"
    staging.mkdir(parents=True)
    records = _copy_canonical_image_channels(root, staging, final, contracts)
    copied_root = next((staging / "textures" / "canonical").iterdir())
    assert (copied_root / "occlusion.png").read_bytes() == occlusion_path.read_bytes()
    assert (copied_root / "raw_pbr_channels.json").read_bytes() == sidecar_path.read_bytes()
    assert {record.mappings[0].source_channel for record in records} == {
        "base_color",
        "occlusion",
    }


def test_raw_pbr_sidecar_accepts_manifest_backed_legacy_string_channels(
    tmp_path: Path,
) -> None:
    """Accept v0.1 string paths only when they duplicate canonical image channels."""

    root = tmp_path / "job"
    image_path, manifest_path, _ = _write_texture_contract_fixture(root)
    sidecar_path = manifest_path.parent / "raw_pbr_channels.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "material_id": "mat.test",
                "channels": {
                    "base_color": "base_color.png",
                    "occlusion": {"constant": 1.0},
                },
            }
        ),
        encoding="utf-8",
    )

    contracts, _, _ = _canonical_texture_contracts(root)
    contract = contracts["mat.test"]

    assert contract.image_channels["base_color"] == image_path.resolve()
    assert contract.image_channel_hashes["base_color"] == sha256_file(image_path)
    assert contract.raw_sidecar_sha256 == sha256_file(sidecar_path)


def test_raw_pbr_sidecar_rejects_unbound_legacy_string_channels(tmp_path: Path) -> None:
    """Reject legacy paths that are not identical image channels in the TextureManifest."""

    root = tmp_path / "job"
    _, manifest_path, _ = _write_texture_contract_fixture(root)
    (manifest_path.parent / "raw_pbr_channels.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "material_id": "mat.test",
                "channels": {"roughness": "roughness.png"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="must duplicate one TextureManifest image"):
        _canonical_texture_contracts(root)


def test_raw_pbr_sidecar_rejects_changed_occlusion_hash(tmp_path: Path) -> None:
    """Fail closed when a sidecar channel no longer matches its declared SHA-256."""

    root = tmp_path / "job"
    _, manifest_path, _ = _write_texture_contract_fixture(root)
    occlusion_path = manifest_path.parent / "occlusion.png"
    Image.new("L", (4, 3), color=255).save(occlusion_path)
    (manifest_path.parent / "raw_pbr_channels.json").write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "material_id": "mat.test",
                "channels": {
                    "occlusion": {
                        "path": "occlusion.png",
                        "sha256": "0" * 64,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="sidecar channel hash changed"):
        _canonical_texture_contracts(root)


def test_procedural_manifest_channel_requires_matching_fresh_bake_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a fresh material bake that omits one declared procedural channel."""

    root = tmp_path / "job"
    image_path, manifest_path, recipe_path = _write_texture_contract_fixture(root)
    bake_output = root / "bakes" / "mat.test" / "base_color.png"
    bake_output.parent.mkdir(parents=True)
    Image.new("RGB", (4, 3), color=(12, 34, 56)).save(bake_output)
    fingerprint = "a" * 64
    blend_sha256 = "b" * 64
    material_fingerprint = "c" * 64
    current_build = {
        "fingerprint": fingerprint,
        "scene_spec_sha256": "d" * 64,
        "geometry_payloads_sha256": {},
        "camera_fingerprint": "e" * 64,
        "material_plan_sha256": sha256_file(root / "analysis" / "material_plan.json"),
        "materials": {
            "mat.test": {
                "shader_recipe_path": "materials/mat.test/shader_recipe.json",
                "shader_recipe_sha256": sha256_file(recipe_path),
                "texture_manifest_path": "textures/mat.test/texture_manifest.json",
                "texture_manifest_sha256": sha256_file(manifest_path),
                "texture_channels": {
                    "base_color": {
                        "path": "textures/mat.test/base_color.png",
                        "sha256": sha256_file(image_path),
                    }
                },
                "fingerprint": material_fingerprint,
            }
        },
    }
    monkeypatch.setattr(
        "codex_blender_modeler.packaging.service.collect_build_provenance",
        lambda *_args, **_kwargs: current_build,
    )
    bake_manifest = root / "bakes" / "mat.test" / "bake_manifest.json"
    bake_manifest.write_text(
        json.dumps(
            {
                "schema_version": "0.5.0",
                "job_id": "portable_asset_case",
                "material_id": "mat.test",
                "source_shader_recipe": "materials/mat.test/shader_recipe.json",
                "source_scene_spec_sha256": "d" * 64,
                "source_geometry_payloads_sha256": {},
                "source_camera_fingerprint": "e" * 64,
                "source_material_plan_sha256": current_build["material_plan_sha256"],
                "source_shader_recipe_sha256": sha256_file(recipe_path),
                "source_texture_manifest": "textures/mat.test/texture_manifest.json",
                "source_texture_manifest_sha256": sha256_file(manifest_path),
                "source_texture_channels_sha256": {"base_color": sha256_file(image_path)},
                "source_blend_sha256": blend_sha256,
                "source_build_fingerprint": fingerprint,
                "source_material_fingerprint": material_fingerprint,
                "profile": "gltf_pbr",
                "resolution": [4, 3],
                "outputs": [
                    {
                        "channel": "base_color",
                        "path": "bakes/mat.test/base_color.png",
                        "color_space": "sRGB",
                        "sha256": sha256_file(bake_output),
                    }
                ],
                "status": "complete",
            }
        ),
        encoding="utf-8",
    )
    report = root / "reports" / "material_bakes.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps({"manifest_paths": ["bakes/mat.test/bake_manifest.json"]}),
        encoding="utf-8",
    )
    source = SimpleNamespace(
        build_fingerprint=fingerprint,
        blend=SimpleNamespace(sha256=blend_sha256),
    )

    with pytest.raises(RuntimeError, match="Procedural TextureManifest channels"):
        _latest_bake_manifests(root, source)  # type: ignore[arg-type]

    roughness_output = root / "bakes" / "mat.test" / "roughness.png"
    Image.new("L", (4, 3), color=128).save(roughness_output)
    payload = json.loads(bake_manifest.read_text(encoding="utf-8"))
    payload["outputs"].append(
        {
            "channel": "roughness",
            "path": "bakes/mat.test/roughness.png",
            "color_space": "Non-Color",
            "sha256": sha256_file(roughness_output),
        }
    )
    bake_manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifests, required, contracts = _latest_bake_manifests(
        root,
        source,  # type: ignore[arg-type]
    )
    assert [manifest.material_id for manifest in manifests] == ["mat.test"]
    assert required == {"mat.test"}
    assert contracts["mat.test"].image_channel_hashes == {"base_color": sha256_file(image_path)}


def test_gltf_pack_rejects_prepacked_orm_without_component_provenance(
    tmp_path: Path,
) -> None:
    """Do not silently replace an opaque prepacked ORM source with default components."""

    source = tmp_path / "orm.png"
    source.write_bytes(b"opaque-prepacked-orm")
    manifest = SimpleNamespace(
        material_id="mat.test",
        source_material_fingerprint="b" * 64,
        outputs=[SimpleNamespace(channel="orm", path="orm.png")],
        resolution=(4, 4),
    )

    with pytest.raises(RuntimeError, match="only a prepacked ORM"):
        _gltf_packed_textures(
            tmp_path,
            tmp_path / "staging",
            tmp_path / "final",
            [manifest],
            4096,
        )


def test_latest_complete_run_skips_newer_failed_pointer(tmp_path: Path) -> None:
    """Resolve the newest usable optimization output even when latest points to failure."""

    complete = tmp_path / "optimization" / "runs" / "20260716-complete"
    failed = tmp_path / "optimization" / "runs" / "20260716-failed"
    (complete / "optimized").mkdir(parents=True)
    failed.mkdir(parents=True)
    (complete / "optimization_plan.json").write_text('{"status":"complete"}', encoding="utf-8")
    (complete / "optimized" / "scene.blend").write_bytes(b"blend")
    (failed / "optimization_plan.json").write_text('{"status":"failed"}', encoding="utf-8")
    latest = tmp_path / "optimization" / "latest.json"
    latest.write_text(
        '{"run_id":"20260716-failed","status":"optimization_failed"}',
        encoding="utf-8",
    )

    assert latest_complete_run_id(tmp_path) == "20260716-complete"
