"""Windows long-path regression coverage for portable-package staging."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image

from codex_blender_modeler.packaging import build_portable_texture_package
from codex_blender_modeler.packaging.service import (
    _image_size_long_path_safe,
    _iter_package_files_long_path_safe,
    _mkdir_long_path_safe,
    _package_file,
    _verify_package_receipts,
)
from codex_blender_modeler.workspace import native_io_path


def test_package_staging_directory_supports_extended_windows_paths(
    tmp_path: Path,
) -> None:
    """Create a nested texture staging directory beyond legacy MAX_PATH."""

    target = tmp_path
    for index in range(8):
        target /= f"canonical-material-component-{index:02d}-0123456789abcdef"
    _mkdir_long_path_safe(target, parents=True, exist_ok=False)
    assert os.path.isdir(native_io_path(target))

    image_path = target / "base_color.png"
    with open(native_io_path(image_path), "wb") as handle:
        Image.new("RGB", (7, 5), (12, 34, 56)).save(handle, format="PNG")
    assert _image_size_long_path_safe(image_path) == (7, 5)


def test_portable_texture_package_supports_long_staging_paths(tmp_path: Path) -> None:
    """Commit raw and packed texture evidence below a legacy MAX_PATH boundary."""

    source = tmp_path / "source"
    source.mkdir(parents=True)
    Image.new("RGB", (4, 4), (20, 40, 60)).save(source / "base_color.png")
    output_dir = Path(
        *[
            f"portable-material-component-{index:02d}-0123456789abcdef"
            for index in range(6)
        ]
    )
    result = build_portable_texture_package(
        source_root=source,
        package_root=tmp_path / "packages",
        output_dir=output_dir,
        channels={"base_color": "base_color.png"},
        orm_defaults={"occlusion": 1.0, "roughness": 0.5, "metallic": 0.0},
        orm_resolution=(4, 4),
    )
    assert os.path.isfile(native_io_path(result.orm_path))
    assert os.path.isfile(native_io_path(result.evidence_path))
    assert os.path.isfile(native_io_path(result.raw_paths["base_color"]))


def test_long_staging_descendants_receive_exact_package_receipts(tmp_path: Path) -> None:
    """Track deep metadata, raw channels, packed maps, and evidence before promotion."""

    root = tmp_path / "job"
    profile_root = root / "exports" / "packages" / "portable_gltf"
    profile_root.mkdir(parents=True)
    final_root = profile_root / "package-001"
    staging_root = profile_root / (
        ".package-001.0123456789abcdef0123456789abcdef"
        "fedcba9876543210fedcba9876543210.tmp"
    )
    _mkdir_long_path_safe(staging_root, parents=False, exist_ok=False)

    primary = staging_root / "asset.glb"
    metadata = staging_root / "metadata" / "material_conversion_evidence.json"
    canonical = (
        staging_root
        / "textures"
        / "canonical"
        / "mat.product-blue-0123456789abcdef0123456789abcdef"
        / "base_color.png"
    )
    packed = staging_root / "textures" / "portable_atlas" / "packed" / "gltf_orm.png"
    evidence = staging_root / "textures" / "portable_atlas" / "texture_pack_evidence.json"
    if os.name == "nt":
        assert len(os.path.abspath(canonical)) > 260
    for path in (metadata, canonical, packed, evidence):
        _mkdir_long_path_safe(path.parent, parents=True, exist_ok=True)
    with open(native_io_path(primary), "wb") as handle:
        handle.write(b"glTF-package")
    with open(native_io_path(metadata), "w", encoding="utf-8") as handle:
        handle.write("{}")
    for path in (canonical, packed):
        with open(native_io_path(path), "wb") as handle:
            Image.new("RGB", (2, 2), (12, 34, 56)).save(handle, format="PNG")
    with open(native_io_path(evidence), "w", encoding="utf-8") as handle:
        handle.write("{}")

    staged_files = _iter_package_files_long_path_safe(staging_root)
    staged_relative = {
        path.relative_to(staging_root).as_posix() for path in staged_files
    }
    assert staged_relative == {
        "asset.glb",
        "metadata/material_conversion_evidence.json",
        "textures/canonical/mat.product-blue-0123456789abcdef0123456789abcdef/base_color.png",
        "textures/portable_atlas/packed/gltf_orm.png",
        "textures/portable_atlas/texture_pack_evidence.json",
    }
    receipts = [
        _package_file(root, final_root, staging_root, path, primary, index)
        for index, path in enumerate(staged_files, start=1)
    ]

    os.replace(native_io_path(staging_root), native_io_path(final_root))
    manifest_path = final_root / "package_manifest.json"
    with open(native_io_path(manifest_path), "w", encoding="utf-8") as handle:
        handle.write("{}")
    package = type(
        "PackageFixture",
        (),
        {
            "package_root": final_root.relative_to(root).as_posix(),
            "files": receipts,
        },
    )()

    verified = _verify_package_receipts(root, final_root, package, manifest_path)
    assert len(verified) == len(staged_relative)
    assert {receipt.path for receipt in receipts} == {
        (final_root / relative).relative_to(root).as_posix()
        for relative in staged_relative
    }
