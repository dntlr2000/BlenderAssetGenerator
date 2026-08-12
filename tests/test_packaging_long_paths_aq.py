"""Windows long-path regression coverage for portable-package staging."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import BaseModel

import codex_blender_modeler.packaging.service as packaging_service
from codex_blender_modeler.packaging import build_portable_texture_package
from codex_blender_modeler.packaging.service import (
    _image_size_long_path_safe,
    _iter_package_files_long_path_safe,
    _mkdir_long_path_safe,
    _package_file,
    _remove_staging_tree_long_path_safe,
    _verify_package_receipts,
)
from codex_blender_modeler.workspace import native_io_path


class _RoundTripReportFixture(BaseModel):
    """Provide the smallest serializable report needed to test atomic publication."""

    status: str = "passed"


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
        / (
            "mat.product-blue-0123456789abcdef0123456789abcdef-"
            "long-path-regression"
        )
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
        (
            "textures/canonical/"
            "mat.product-blue-0123456789abcdef0123456789abcdef-"
            "long-path-regression/base_color.png"
        ),
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


def test_roundtrip_validation_recovers_and_publishes_beyond_legacy_max_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read, clean, and atomically publish long-path roundtrip evidence."""

    root = tmp_path
    index = 0
    final_suffix = Path("optimization/runs/run-001/roundtrip/package-001")
    while len(os.path.abspath(root / final_suffix)) < 215:
        root /= f"roundtrip-depth-{index:02d}-0123456789abcdef"
        index += 1
    _mkdir_long_path_safe(root, parents=True, exist_ok=False)

    package_root = root / "exports" / "packages" / "portable_gltf" / "package-001"
    run_root = root / "optimization" / "runs" / "run-001"
    _mkdir_long_path_safe(package_root, parents=True, exist_ok=False)
    _mkdir_long_path_safe(run_root, parents=True, exist_ok=False)
    primary = package_root / "asset.glb"
    manifest = package_root / "package_manifest.json"
    raw_export = package_root / "export_evidence.json"
    for path, content in (
        (primary, "glTF"),
        (manifest, "{}"),
        (raw_export, "{}"),
    ):
        with open(native_io_path(path), "w", encoding="utf-8") as handle:
            handle.write(content)

    package = SimpleNamespace(
        job_id="long-roundtrip",
        profile_id="portable_gltf",
        package_id="package-001",
        run_id="run-001",
        primary_file_id="primary-glb",
        files=[SimpleNamespace(id="primary-glb")],
    )
    monkeypatch.setattr(
        packaging_service,
        "load_feature_config",
        lambda: SimpleNamespace(features=SimpleNamespace(portable_asset_core=True)),
    )
    monkeypatch.setattr(packaging_service, "job_dir", lambda _job_id: root)
    monkeypatch.setattr(packaging_service, "load_model", lambda *_args: package)
    monkeypatch.setattr(
        packaging_service,
        "_verify_package_receipts",
        lambda *_args: {"primary-glb": primary},
    )
    monkeypatch.setattr(
        packaging_service,
        "_embedded_absolute_path_findings",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        packaging_service,
        "run_directory",
        lambda *_args: run_root,
    )
    monkeypatch.setattr(
        packaging_service,
        "_build_roundtrip_report",
        lambda **_kwargs: _RoundTripReportFixture(),
    )

    attempts = 0
    output_lengths: list[int] = []

    def fake_run_blender(
        _script: str,
        arguments: list[str],
        *,
        factory_startup: bool,
    ) -> None:
        """Write malformed evidence once, then a valid object, at the requested path."""

        nonlocal attempts
        assert factory_startup is True
        output = Path(arguments[arguments.index("--output") + 1])
        output_lengths.append(len(os.path.abspath(output)))
        payload = "{" if attempts == 0 else '{"status":"passed"}'
        attempts += 1
        with open(native_io_path(output), "w", encoding="utf-8") as handle:
            handle.write(payload)

    monkeypatch.setattr(packaging_service, "run_blender", fake_run_blender)
    validation_parent = run_root / "roundtrip"

    with pytest.raises(json.JSONDecodeError):
        packaging_service.validate_asset_package(
            "long-roundtrip",
            "package-001",
        )
    with os.scandir(native_io_path(validation_parent)) as iterator:
        assert list(iterator) == []

    report = packaging_service.validate_asset_package(
        "long-roundtrip",
        "package-001",
    )
    validation_root = validation_parent / "package-001"
    assert report.status == "passed"
    assert os.path.isfile(native_io_path(validation_root / "roundtrip_evidence.json"))
    assert os.path.isfile(native_io_path(validation_root / "roundtrip_validation.json"))
    with os.scandir(native_io_path(validation_parent)) as iterator:
        names = sorted(entry.name for entry in iterator)
    assert names == ["package-001"]
    if os.name == "nt":
        assert min(output_lengths) > 260


def test_roundtrip_staging_cleanup_rejects_escape_and_does_not_follow_links(
    tmp_path: Path,
) -> None:
    """Keep cleanup contained and remove a link leaf without touching its target."""

    parent = tmp_path / "roundtrip"
    staging = parent / ".package-001.0123456789abcdef.tmp"
    outside = tmp_path / "outside"
    staging.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    try:
        os.symlink(outside, staging / "linked", target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlink creation is unavailable on this host")

    _remove_staging_tree_long_path_safe(staging, expected_parent=parent)

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not os.path.lexists(native_io_path(staging))
    with pytest.raises(ValueError, match="escaped its expected parent"):
        _remove_staging_tree_long_path_safe(
            parent.parent / ".escaped.tmp",
            expected_parent=parent,
        )
