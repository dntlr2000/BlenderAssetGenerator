"""Focused host-package integration tests for V0.7.1 material conversion."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

import codex_blender_modeler.packaging.service as packaging_service
from codex_blender_modeler.optimization.models import (
    HashedArtifact,
    PortableChannelOutput,
    PortableMaterialContractArtifact,
    SourceProvenance,
)
from codex_blender_modeler.packaging import material_conversion as conversion_service
from codex_blender_modeler.packaging.models import ExportPackageManifest, PackageFile
from codex_blender_modeler.workspace import sha256_file

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
MATERIAL_IDS = ["mat.rock", "mat.water"]
CHANNELS = ["base_color", "roughness", "metallic", "normal", "emission"]


def test_fbx_package_uses_model_filename_without_changing_other_formats() -> None:
    """Honor the FBX delivery contract while preserving existing format filenames."""

    assert packaging_service._primary_asset_filename("fbx") == "model.fbx"
    assert packaging_service._primary_asset_filename("glb") == "asset.glb"
    assert packaging_service._primary_asset_filename("obj") == "asset.obj"


def test_material_conversion_staging_name_stays_short_for_windows() -> None:
    """Keep atomic staging names bounded when the job path is already deeply nested."""

    staging = conversion_service._material_conversion_staging_directory(Path("deep"))
    assert staging.parent == Path("deep")
    assert staging.name.startswith(".tmp-")
    assert len(staging.name) == 13


def _artifact(
    artifact_id: str,
    kind: str,
    path: str,
    digest: str = "a" * 64,
) -> HashedArtifact:
    """Create one deterministic hashed-artifact fixture."""

    return HashedArtifact(id=artifact_id, kind=kind, path=path, sha256=digest)


def _source() -> SourceProvenance:
    """Create canonical provenance sufficient for package-contract validation."""

    return SourceProvenance(
        scene_spec=_artifact(
            "scene-spec",
            "scene_spec",
            "analysis/scene_spec.json",
            "1" * 64,
        ),
        blend=_artifact(
            "canonical-blend",
            "blend",
            "blender/scene.blend",
            "2" * 64,
        ),
        source_fingerprint="3" * 64,
        build_fingerprint="4" * 64,
    )


def test_material_plan_job_requires_explicit_conversion_id_before_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop a material-authored job before export unless a conversion is selected."""

    root = tmp_path / "portable_asset"
    run_root = root / "optimization" / "runs" / "run-001"
    material_plan = root / "analysis" / "material_plan.json"
    material_plan.parent.mkdir(parents=True)
    material_plan.write_text("{}", encoding="utf-8")
    run_root.mkdir(parents=True)
    plan = SimpleNamespace(profile_id="portable_gltf", source=object())
    profile = SimpleNamespace(
        profile_id="portable_gltf",
        collision=SimpleNamespace(strategy="compound"),
    )

    monkeypatch.setattr(
        packaging_service,
        "load_feature_config",
        lambda: SimpleNamespace(features=SimpleNamespace(portable_asset_core=True)),
    )
    monkeypatch.setattr(
        packaging_service,
        "_run_for_package",
        lambda *_args, **_kwargs: (root, "run-001", run_root),
    )
    monkeypatch.setattr(packaging_service, "load_model", lambda *_args, **_kwargs: plan)
    monkeypatch.setattr(
        packaging_service,
        "load_asset_profile",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(packaging_service, "_require_collider_export", lambda *_args: None)
    monkeypatch.setattr(packaging_service, "require_unchanged_source", lambda *_args: None)
    monkeypatch.setattr(packaging_service, "_load_run_manifests", lambda *_args: ())
    monkeypatch.setattr(
        packaging_service,
        "_verify_run_artifacts",
        lambda *_args: {"plan_sha256": "5" * 64},
    )

    with pytest.raises(RuntimeError, match="provide material_conversion_id"):
        packaging_service.package_asset(
            "portable_asset",
            profile_id="portable_gltf",
            run_id="run-001",
            package_id="package-001",
        )


def _conversion_outputs(root: Path) -> list[PortableChannelOutput]:
    """Write five global channel images and return their hash-bound contracts."""

    output_root = root / "optimization" / "material_conversions" / "conversion-001"
    outputs: list[PortableChannelOutput] = []
    for index, channel in enumerate(CHANNELS):
        path = output_root / f"{channel}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), color=(index * 20, 40, 80)).save(path)
        outputs.append(
            PortableChannelOutput(
                id=f"portable-atlas-{channel}",
                channel=channel,
                path=path.relative_to(root).as_posix(),
                sha256=sha256_file(path),
                color_space=(
                    "sRGB" if channel in {"base_color", "emission"} else "Non-Color"
                ),
                resolution=(4, 4),
                material_ids=MATERIAL_IDS,
            )
        )
    return outputs


def test_global_conversion_texture_receipts_preserve_materials_and_color_space(
    tmp_path: Path,
) -> None:
    """Keep full material coverage and sRGB emission in every copied atlas receipt."""

    root = tmp_path / "portable_asset"
    staging = root / "exports" / "packages" / "portable_gltf" / ".package.tmp"
    final_root = root / "exports" / "packages" / "portable_gltf" / "package-001"
    staging.mkdir(parents=True)
    conversion = SimpleNamespace(
        conversion_id="conversion-001",
        manifest=SimpleNamespace(outputs=_conversion_outputs(root)),
    )

    receipts = packaging_service._copy_conversion_raw_channels(
        root,
        staging,
        final_root,
        conversion,
    )

    by_channel = {
        receipt.mappings[0].source_channel: receipt for receipt in receipts
    }
    assert sorted(by_channel) == sorted(CHANNELS)
    assert all(receipt.material_ids == MATERIAL_IDS for receipt in receipts)
    assert by_channel["base_color"].color_space == "sRGB"
    assert by_channel["emission"].color_space == "sRGB"
    assert by_channel["roughness"].color_space == "Non-Color"
    assert by_channel["metallic"].color_space == "Non-Color"
    assert by_channel["normal"].color_space == "Non-Color"


def _package_manifest(
    material_conversion: PortableMaterialContractArtifact,
) -> ExportPackageManifest:
    """Create one complete package with a contained material-conversion receipt."""

    package_root = "exports/packages/portable_gltf/package-001"
    return ExportPackageManifest(
        package_id="package-001",
        job_id="portable_asset",
        run_id="run-001",
        profile_id="portable_gltf",
        source=_source(),
        optimization_plan=_artifact(
            "optimization-plan",
            "optimization_plan",
            f"{package_root}/metadata/optimization_plan.json",
            "6" * 64,
        ),
        material_conversion=material_conversion,
        status="complete",
        package_root=package_root,
        files=[
            PackageFile(
                id="primary-glb",
                kind="primary_asset",
                path=f"{package_root}/asset.glb",
                sha256="7" * 64,
                byte_size=4096,
                media_type="model/gltf-binary",
            )
        ],
        primary_file_id="primary-glb",
        semantic_ids=["asset.body"],
        material_ids=MATERIAL_IDS,
        created_at=NOW,
        completed_at=NOW,
    )


def test_package_manifest_requires_conversion_role_and_package_containment() -> None:
    """Accept only a contained portable-conversion manifest snapshot as package evidence."""

    package_root = "exports/packages/portable_gltf/package-001"
    receipt = PortableMaterialContractArtifact(
        id="material-conversion-manifest",
        kind="portable_material_conversion_manifest",
        path=f"{package_root}/metadata/material_conversion_manifest.json",
        sha256="8" * 64,
    )
    package = _package_manifest(receipt)
    assert package.material_conversion == receipt

    wrong_role = PortableMaterialContractArtifact(
        **{**receipt.model_dump(), "kind": "shader_recipe"}
    )
    with pytest.raises(ValidationError, match="material_conversion must use kind"):
        _package_manifest(wrong_role)

    outside = PortableMaterialContractArtifact(
        **{
            **receipt.model_dump(),
            "path": "optimization/material_conversions/conversion_manifest.json",
        }
    )
    with pytest.raises(ValidationError, match="must stay below package_root"):
        _package_manifest(outside)
