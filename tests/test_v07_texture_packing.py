from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import codex_blender_modeler.packaging.texture_packing as texture_packing
from codex_blender_modeler.packaging import (
    TexturePackingError,
    build_portable_texture_package,
)


def _write_image(
    path: Path,
    mode: str,
    color: int | tuple[int, ...],
    *,
    size: tuple[int, int] = (4, 3),
) -> Path:
    """Create one small deterministic image fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color=color).save(path)
    return path


def _sha256(path: Path) -> str:
    """Hash one test artifact for byte-preservation assertions."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_portable_package_preserves_raw_channels_and_packs_gltf_orm(
    tmp_path: Path,
) -> None:
    """Raw sources remain exact while ORM bytes follow glTF channel semantics."""

    source = tmp_path / "source"
    package_root = tmp_path / "packages"
    base = _write_image(source / "albedo.png", "RGB", (20, 40, 60))
    ao = _write_image(source / "ao.png", "L", 17)
    roughness = _write_image(source / "rough.png", "L", 129)
    metallic = _write_image(source / "metal.png", "L", 231)
    normal = _write_image(source / "normal.png", "RGB", (128, 128, 255))

    result = build_portable_texture_package(
        source_root=source,
        package_root=package_root,
        output_dir="asset_a/textures",
        channels={
            "base_color": "albedo.png",
            "occlusion": "ao.png",
            "roughness": "rough.png",
            "metallic": "metal.png",
            "normal": "normal.png",
        },
    )

    assert result.package_dir == (package_root / "asset_a" / "textures").resolve()
    assert result.raw_paths["base_color"].read_bytes() == base.read_bytes()
    assert result.raw_paths["normal"].read_bytes() == normal.read_bytes()
    assert result.evidence["raw_channels"]["base_color"]["color_space"] == "sRGB"
    assert result.evidence["raw_channels"]["normal"]["color_space"] == "Non-Color"
    assert result.evidence["raw_channels"]["occlusion"]["source_sha256"] == _sha256(ao)
    assert result.evidence["raw_channels"]["roughness"]["source_sha256"] == _sha256(
        roughness
    )
    assert result.evidence["raw_channels"]["metallic"]["source_sha256"] == _sha256(
        metallic
    )
    with Image.open(result.orm_path) as orm:
        assert orm.mode == "RGB"
        assert orm.size == (4, 3)
        assert orm.getpixel((0, 0)) == (17, 129, 231)
    evidence = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    assert result.evidence_path.name == "texture_pack_evidence.json"
    assert evidence["kind"] == "low_level_texture_pack_evidence"
    assert evidence["packed_textures"]["gltf_orm"]["channel_mapping"] == {
        "B": "metallic",
        "G": "roughness",
        "R": "occlusion",
    }
    assert evidence["packed_textures"]["gltf_orm"]["color_space"] == "Non-Color"
    assert all(
        not Path(record["source_path"]).is_absolute()
        for record in evidence["raw_channels"].values()
    )


def test_gltf_orm_is_deterministic_across_independent_packages(tmp_path: Path) -> None:
    """Identical source bytes and constants produce identical ORM PNG hashes."""

    source = tmp_path / "source"
    _write_image(source / "roughness.png", "L", 77)
    first = build_portable_texture_package(
        source_root=source,
        package_root=tmp_path / "packages",
        output_dir="first",
        channels={"roughness": "roughness.png"},
        orm_defaults={"occlusion": 1.0, "metallic": 0.0},
    )
    second = build_portable_texture_package(
        source_root=source,
        package_root=tmp_path / "packages",
        output_dir="second",
        channels={"roughness": "roughness.png"},
        orm_defaults={"occlusion": 1.0, "metallic": 0.0},
    )

    assert first.orm_sha256 == second.orm_sha256
    assert first.orm_path.read_bytes() == second.orm_path.read_bytes()
    with Image.open(first.orm_path) as orm:
        assert orm.getpixel((0, 0)) == (255, 77, 0)
    inputs = first.evidence["packed_textures"]["gltf_orm"]["inputs"]
    assert inputs["occlusion"] == {
        "kind": "constant",
        "normalized_value": 1.0,
        "encoded_byte": 255,
    }


def test_missing_orm_channel_requires_explicit_default_and_leaves_no_output(
    tmp_path: Path,
) -> None:
    """An undeclared fallback fails before an immutable package is committed."""

    source = tmp_path / "source"
    _write_image(source / "roughness.png", "L", 100)
    destination = tmp_path / "packages" / "failed"

    with pytest.raises(TexturePackingError, match="Missing ORM channel occlusion"):
        build_portable_texture_package(
            source_root=source,
            package_root=tmp_path / "packages",
            output_dir="failed",
            channels={"roughness": "roughness.png"},
            orm_defaults={"metallic": 0.0},
        )

    assert not destination.exists()
    assert not list((tmp_path / "packages").glob(".failed.*.tmp"))


def test_all_constant_orm_requires_resolution_and_records_exact_defaults(
    tmp_path: Path,
) -> None:
    """A texture-free ORM is allowed only with explicit constants and dimensions."""

    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(TexturePackingError, match="resolution is required"):
        build_portable_texture_package(
            source_root=source,
            package_root=tmp_path / "packages",
            output_dir="missing_resolution",
            channels={},
            orm_defaults={"occlusion": 1.0, "roughness": 0.5, "metallic": 0.0},
        )

    result = build_portable_texture_package(
        source_root=source,
        package_root=tmp_path / "packages",
        output_dir="constant_orm",
        channels={},
        orm_defaults={"occlusion": 1.0, "roughness": 0.5, "metallic": 0.0},
        orm_resolution=(2, 3),
    )
    with Image.open(result.orm_path) as orm:
        assert orm.size == (2, 3)
        assert orm.getpixel((1, 2)) == (255, 128, 0)


def test_texture_paths_must_remain_inside_declared_roots(tmp_path: Path) -> None:
    """Input traversal and output traversal are rejected before filesystem mutation."""

    source = tmp_path / "source"
    source.mkdir()
    _write_image(tmp_path / "outside.png", "L", 12)
    defaults = {"occlusion": 1.0, "roughness": 0.5, "metallic": 0.0}

    with pytest.raises(TexturePackingError, match="Source channel roughness must stay inside"):
        build_portable_texture_package(
            source_root=source,
            package_root=tmp_path / "packages",
            output_dir="input_escape",
            channels={"roughness": "../outside.png"},
            orm_defaults={"occlusion": 1.0, "metallic": 0.0},
        )
    with pytest.raises(TexturePackingError, match="Texture package output must stay inside"):
        build_portable_texture_package(
            source_root=source,
            package_root=tmp_path / "packages",
            output_dir="../output_escape",
            channels={},
            orm_defaults=defaults,
            orm_resolution=(2, 2),
        )
    assert not (tmp_path / "output_escape").exists()


def test_orm_input_resolution_mismatch_is_rejected_without_resampling(
    tmp_path: Path,
) -> None:
    """Data maps of different sizes fail instead of being silently resampled."""

    source = tmp_path / "source"
    _write_image(source / "ao.png", "L", 255, size=(4, 4))
    _write_image(source / "roughness.png", "L", 128, size=(2, 2))

    with pytest.raises(TexturePackingError, match="identical resolutions"):
        build_portable_texture_package(
            source_root=source,
            package_root=tmp_path / "packages",
            output_dir="mismatch",
            channels={"occlusion": "ao.png", "roughness": "roughness.png"},
            orm_defaults={"metallic": 0.0},
        )
    assert not (tmp_path / "packages" / "mismatch").exists()


def test_explicit_orm_resampling_is_deterministic_and_recorded(tmp_path: Path) -> None:
    """A bounded package may explicitly downsample derived ORM while preserving raw bytes."""

    source = tmp_path / "source"
    roughness = _write_image(
        source / "roughness.png",
        "L",
        128,
        size=(8, 4),
    )
    result = build_portable_texture_package(
        source_root=source,
        package_root=tmp_path / "packages",
        output_dir="resampled",
        channels={"roughness": "roughness.png"},
        orm_defaults={"occlusion": 1.0, "metallic": 0.0},
        orm_resolution=(4, 2),
        allow_orm_resample=True,
    )

    assert result.raw_paths["roughness"].read_bytes() == roughness.read_bytes()
    with Image.open(result.orm_path) as orm:
        assert orm.size == (4, 2)
        assert orm.getpixel((0, 0)) == (255, 128, 0)
    provenance = result.evidence["provenance"]
    roughness_input = result.evidence["packed_textures"]["gltf_orm"]["inputs"][
        "roughness"
    ]
    assert provenance["orm_resampling"] is True
    assert provenance["orm_resample_filter"] == "BOX"
    assert roughness_input["source_resolution"] == [8, 4]
    assert roughness_input["output_resolution"] == [4, 2]
    assert roughness_input["resampled"] is True


def test_staging_failure_does_not_publish_partial_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mid-write encoder failure cleans staging and leaves no visible destination."""

    source = tmp_path / "source"
    _write_image(source / "roughness.png", "L", 80)
    package_root = tmp_path / "packages"

    def fail_png_write(_image: Image.Image, _path: Path) -> None:
        """Simulate a deterministic encoder failure after raw files are staged."""

        raise OSError("simulated PNG encoder failure")

    monkeypatch.setattr(texture_packing, "_save_deterministic_png", fail_png_write)
    with pytest.raises(OSError, match="simulated PNG encoder failure"):
        build_portable_texture_package(
            source_root=source,
            package_root=package_root,
            output_dir="atomic_failure",
            channels={"roughness": "roughness.png"},
            orm_defaults={"occlusion": 1.0, "metallic": 0.0},
        )

    assert not (package_root / "atomic_failure").exists()
    assert not list(package_root.glob(".atomic_failure.*.tmp"))


def test_outer_transaction_can_disable_nested_texture_staging(tmp_path: Path) -> None:
    """Write below an existing package stage without creating a long nested temp path."""

    source = tmp_path / "source"
    _write_image(source / "roughness.png", "L", 80)
    package_root = tmp_path / "outer-stage"
    result = build_portable_texture_package(
        source_root=source,
        package_root=package_root,
        output_dir="textures/material-a",
        channels={"roughness": "roughness.png"},
        orm_defaults={"occlusion": 1.0, "metallic": 0.0},
        atomic_commit=False,
    )

    assert result.package_dir == (package_root / "textures" / "material-a").resolve()
    assert result.orm_path.is_file()
    assert not list((package_root / "textures").glob(".*.tmp"))
