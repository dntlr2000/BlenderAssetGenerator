from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from codex_blender_modeler.texturing import (
    generate_procedural_pbr,
    list_material_family_presets,
)


def _validate_texture_schema(payload: dict) -> None:
    """Check one generated manifest against the checked-in contract schema."""

    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "schemas" / "texture_manifest.schema.json").read_text())
    errors = list(Draft202012Validator(schema).iter_errors(payload))
    assert not errors, [error.message for error in errors]


def test_seeded_provider_is_deterministic_and_hashes_every_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal requests in isolated jobs yield byte-identical, hash-recorded PNG maps."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    channels = ("base_color", "roughness", "metallic", "normal", "height", "emission")
    first = generate_procedural_pbr(
        "texture_a",
        "mat.test",
        preset="lava",
        channels=channels,
        resolution=(32, 24),
        seed=57,
        intended_scale_m=1.25,
    )
    second = generate_procedural_pbr(
        "texture_b",
        "mat.test",
        preset="lava",
        channels=channels,
        resolution=(32, 24),
        seed=57,
        intended_scale_m=1.25,
    )

    assert first.channel_sha256 == second.channel_sha256
    assert set(first.channel_paths) == set(channels)
    assert first.manifest.provenance is not None
    assert first.manifest.provenance.generated_sha256 == first.channel_sha256
    assert first.manifest.channels["base_color"].color_space == "sRGB"
    assert first.manifest.channels["emission"].color_space == "sRGB"
    assert first.manifest.channels["normal"].color_space == "Non-Color"
    payload = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    _validate_texture_schema(payload)


def test_provider_honors_channel_subset_seed_and_overwrite_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only requested maps are written, seeds matter, and outputs are not overwritten silently."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    first = generate_procedural_pbr(
        "texture_a",
        "mat.rock",
        preset="rock",
        channels=("height", "normal"),
        resolution=(24, 24),
        seed=2,
    )
    second = generate_procedural_pbr(
        "texture_b",
        "mat.rock",
        preset="rock",
        channels=("height", "normal"),
        resolution=(24, 24),
        seed=3,
    )

    assert set(first.manifest.channels) == {"height", "normal"}
    assert first.channel_sha256["height"] != second.channel_sha256["height"]
    assert not (first.manifest_path.parent / "base_color.png").exists()
    with pytest.raises(FileExistsError, match="already exist"):
        generate_procedural_pbr(
            "texture_a",
            "mat.rock",
            preset="rock",
            channels=("height", "normal"),
            resolution=(24, 24),
            seed=2,
        )


def test_provider_rejects_invalid_channels_and_returns_isolated_presets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public provider rejects ambiguous requests and protects preset globals from mutation."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    with pytest.raises(ValidationError, match="unique"):
        generate_procedural_pbr(
            "texture_a",
            "mat.test",
            channels=("height", "height"),
            resolution=(16, 16),
        )
    with pytest.raises(ValueError, match="Unsupported procedural PBR channels"):
        generate_procedural_pbr(
            "texture_a",
            "mat.test",
            channels=("opacity",),
            resolution=(16, 16),
        )

    presets = list_material_family_presets()
    assert set(presets) == {
        "standard_pbr",
        "rock",
        "terrain",
        "water",
        "glass",
        "foliage",
        "lava",
        "cloud",
        "emissive",
    }
    presets["rock"]["normal_strength"] = -1
    assert list_material_family_presets()["rock"]["normal_strength"] > 0
