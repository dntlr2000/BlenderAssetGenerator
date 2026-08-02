from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.texturing import (
    generate_procedural_pbr,
    list_material_family_presets,
)
from codex_blender_modeler.texturing.models import (
    SurfaceDetailBinding,
    SurfaceDetailPlacement,
    TextureManifest,
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
        "standardgun_red_paint",
        "standardgun_dark_polymer",
        "standardgun_gunmetal",
        "standardgun_gold_accent",
        "standardgun_bore_dark",
        "standardgun_simple_red_paint",
        "standardgun_simple_dark_polymer",
        "standardgun_simple_gunmetal",
        "standardgun_simple_gold_accent",
        "standardgun_simple_bore_dark",
        "stylized_clean_red_paint",
        "stylized_clean_dark_polymer",
        "stylized_clean_gunmetal",
        "stylized_clean_gold_metal",
        "stylized_clean_dark_recess",
    }
    presets["rock"]["normal_strength"] = -1
    assert list_material_family_presets()["rock"]["normal_strength"] > 0


def test_surface_detail_pattern_writes_png_pixels_and_exact_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Declared surface-detail coverage must correspond to rendered PNG pattern pixels."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    result = generate_procedural_pbr(
        "texture_detail",
        "mat.detail",
        preset="standardgun_red_paint",
        channels=("base_color", "roughness", "normal", "emission"),
        resolution=(64, 64),
        seed=12,
        uv_set="UVMap",
        surface_detail_ids=("detail.panel",),
        detail_pattern="panel_atlas",
        output_dir=tmp_path / "texture_detail" / "workflows" / "wf" / "textures",
    )

    assert result.manifest.surface_detail_ids == ["detail.panel"]
    assert result.manifest.procedural["detail_pattern"] == "panel_atlas"
    assert result.manifest_path.suffix == ".json"
    base_color = Image.open(result.channel_paths["base_color"])
    assert base_color.format == "PNG"
    assert len(set(base_color.getdata())) > 2


def test_surface_detail_ids_require_a_rendered_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider rejects coverage-only metadata without corresponding mark generation."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    with pytest.raises(ValidationError, match="rendered detail_pattern"):
        generate_procedural_pbr(
            "texture_detail",
            "mat.detail",
            channels=("base_color",),
            resolution=(16, 16),
            surface_detail_ids=("detail.panel",),
        )


def test_detail_patterns_require_one_uv_bound_semantic_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generic detail maps reject missing, ambiguous, or non-UV semantic placement claims."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="requires one exact surface_detail_id"):
        generate_procedural_pbr(
            "texture_missing_id",
            "mat.detail",
            channels=("base_color",),
            resolution=(16, 16),
            detail_pattern="panel_atlas",
        )
    with pytest.raises(ValueError, match="only one exact surface_detail_id"):
        generate_procedural_pbr(
            "texture_ambiguous",
            "mat.detail",
            channels=("base_color",),
            resolution=(16, 16),
            uv_set="UVMap",
            surface_detail_ids=("detail.panel", "detail.seam"),
            detail_pattern="panel_atlas",
        )
    with pytest.raises(ValueError, match="requires UVMap"):
        generate_procedural_pbr(
            "texture_object_coordinates",
            "mat.detail",
            channels=("base_color",),
            resolution=(16, 16),
            uv_set="Object",
            surface_detail_ids=("detail.panel",),
            detail_pattern="panel_atlas",
        )


def test_simple_standardgun_preset_keeps_detail_contrast_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simple pickup presets retain real detail pixels without recreating harsh black marks."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    result = generate_procedural_pbr(
        "texture_simple",
        "mat.simple",
        preset="standardgun_simple_red_paint",
        channels=("base_color", "roughness", "metallic", "normal", "emission"),
        resolution=(64, 64),
        seed=31,
        uv_set="UVMap",
        surface_detail_ids=("detail.panel",),
        detail_pattern="panel_atlas",
    )

    base_color = Image.open(result.channel_paths["base_color"])
    red_minimum, red_maximum = base_color.getextrema()[0]
    assert red_minimum >= 100
    assert red_maximum - red_minimum <= 44
    assert result.manifest.procedural["detail_pattern"] == "panel_atlas"
    assert result.manifest.surface_detail_ids == ["detail.panel"]


def test_legacy_preset_uses_safe_default_detail_contrast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regenerated legacy presets no longer turn semantic marks into half-black lines."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    result = generate_procedural_pbr(
        "texture_legacy_safe",
        "mat.legacy",
        preset="standardgun_red_paint",
        channels=("base_color", "roughness", "normal"),
        resolution=(64, 64),
        seed=18,
        uv_set="UVMap",
        surface_detail_ids=("detail.panel",),
        detail_pattern="panel_atlas",
    )

    base_color = Image.open(result.channel_paths["base_color"])
    red_minimum, _red_maximum = base_color.getextrema()[0]
    assert red_minimum >= 65
    assert result.manifest.procedural["detail_tone_factor"] == pytest.approx(0.85)
    assert result.manifest.procedural["detail_placement_scope"] == "legacy_unbound"


def test_generic_clean_preset_limits_clouding_and_reads_legacy_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generic clean materials stay low-variance while old manifest metadata remains readable."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    result = generate_procedural_pbr(
        "texture_generic_clean",
        "mat.clean",
        preset="stylized_clean_red_paint",
        channels=("base_color", "roughness", "normal"),
        resolution=(64, 64),
        seed=41,
        uv_set="UVMap",
        surface_detail_ids=("detail.panel",),
        detail_pattern="panel_atlas",
    )

    base_color = Image.open(result.channel_paths["base_color"])
    red_minimum, red_maximum = base_color.getextrema()[0]
    assert red_minimum >= 100
    assert red_maximum - red_minimum <= 44

    legacy_payload = result.manifest.model_dump(mode="json")
    for field in (
        "detail_tone_factor",
        "detail_roughness_value",
        "detail_relief_mix",
        "detail_placement_scope",
    ):
        legacy_payload["procedural"].pop(field, None)
    parsed = TextureManifest.model_validate(legacy_payload)
    assert parsed.material_id == "mat.clean"
    assert parsed.procedural["detail_pattern"] == "panel_atlas"


def test_spatial_detail_changes_only_its_declared_uv_rectangle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A spatial-v1 procedural mark leaves every texel outside its UV rectangle unchanged."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    baseline = generate_procedural_pbr(
        "texture_spatial_baseline",
        "mat.clean",
        preset="stylized_clean_red_paint",
        channels=("base_color", "roughness", "normal"),
        resolution=(64, 64),
        seed=77,
        uv_set="UVMap",
        output_dir=tmp_path / "texture_spatial_baseline" / "textures" / "mat.clean",
    )
    binding = SurfaceDetailBinding(
        detail_id="detail.window",
        parent_object_id="asset.body",
        material_id="mat.clean",
        uv_layout_sha256="a" * 64,
        placement=SurfaceDetailPlacement(
            mode="uv_rect",
            uv_rect=(0.25, 0.25, 0.75, 0.75),
        ),
        channels=["base_color", "roughness", "normal"],
        strength=0.5,
        wrap="clip",
    )
    bounded = generate_procedural_pbr(
        "texture_spatial_bound",
        "mat.clean",
        preset="stylized_clean_red_paint",
        channels=("base_color", "roughness", "normal"),
        resolution=(64, 64),
        seed=77,
        uv_set="UVMap",
        surface_detail_ids=("detail.window",),
        surface_detail_bindings=(binding,),
        detail_pattern="panel_atlas",
        output_dir=tmp_path / "texture_spatial_bound" / "textures" / "mat.clean",
    )

    baseline_image = Image.open(baseline.channel_paths["base_color"]).convert("RGB")
    bounded_image = Image.open(bounded.channel_paths["base_color"]).convert("RGB")
    changed_inside = 0
    for y in range(64):
        for x in range(64):
            differs = baseline_image.getpixel((x, y)) != bounded_image.getpixel((x, y))
            if 16 <= x < 48 and 16 <= y < 48:
                changed_inside += int(differs)
            else:
                assert not differs
    assert changed_inside > 0
    assert bounded.manifest.surface_detail_bindings == [binding]
    assert bounded.manifest.procedural["detail_placement_scope"] == "spatial_v1"


def test_spatial_detail_changes_only_declared_pbr_channels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent a localized Base Color mark from leaking into roughness or normal maps."""

    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(tmp_path))
    baseline = generate_procedural_pbr(
        "texture_channel_baseline",
        "mat.clean",
        preset="stylized_clean_red_paint",
        channels=("base_color", "roughness", "normal"),
        resolution=(64, 64),
        seed=92,
        uv_set="UVMap",
        output_dir=tmp_path / "texture_channel_baseline" / "textures" / "mat.clean",
    )
    binding = SurfaceDetailBinding(
        detail_id="detail.label",
        parent_object_id="asset.body",
        material_id="mat.clean",
        uv_layout_sha256="b" * 64,
        placement=SurfaceDetailPlacement(
            mode="uv_rect",
            uv_rect=(0.2, 0.2, 0.8, 0.8),
        ),
        channels=["base_color"],
        wrap="clip",
    )
    bounded = generate_procedural_pbr(
        "texture_channel_bound",
        "mat.clean",
        preset="stylized_clean_red_paint",
        channels=("base_color", "roughness", "normal"),
        resolution=(64, 64),
        seed=92,
        uv_set="UVMap",
        surface_detail_ids=("detail.label",),
        surface_detail_bindings=(binding,),
        detail_pattern="panel_atlas",
        output_dir=tmp_path / "texture_channel_bound" / "textures" / "mat.clean",
    )

    assert (
        Image.open(baseline.channel_paths["base_color"]).tobytes()
        != Image.open(bounded.channel_paths["base_color"]).tobytes()
    )
    for channel in ("roughness", "normal"):
        assert (
            Image.open(baseline.channel_paths[channel]).tobytes()
            == Image.open(bounded.channel_paths[channel]).tobytes()
        )
