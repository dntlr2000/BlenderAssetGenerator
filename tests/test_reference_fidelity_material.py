"""Directional-material preflight tests; these do not claim reference similarity."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from codex_blender_modeler.material_authoring.models import (
    ExactArtifact,
    ProceduralWoodInput,
    UVIdentity,
)
from codex_blender_modeler.material_authoring.wood import generate_directional_wood_v2
from codex_blender_modeler.reference_fidelity.material import evaluate_directional_material
from codex_blender_modeler.reference_fidelity.models import (
    DirectionalMappingEvidenceV01,
    FidelityArtifact,
)
from codex_blender_modeler.reference_fidelity.service import artifact_at


def _wood(axis: str = "y") -> ProceduralWoodInput:
    """Create one strict image-only Wood v2 fixture with inert UV evidence metadata."""

    evidence = ExactArtifact(
        artifact_id="uv-evidence",
        kind="uv-identity-snapshot",
        path="fidelity/fixture/uv.json",
        sha256="a" * 64,
        byte_size=1,
        media_type="application/json",
    )
    identity = UVIdentity(
        semantic_id="asset.main",
        uv_set="Generated",
        uv_fingerprint="b" * 64,
        ordered_polygon_corner_count=24,
        texel_density_px_m=256.0,
        evidence=evidence,
    )
    return ProceduralWoodInput(
        grain_axis=axis,
        grain_frequency_m=0.36,
        growth_ring_scale_m=0.30,
        knot_seed=417,
        knot_count=4,
        earlywood_color=(0.58, 0.34, 0.15),
        latewood_color=(0.17, 0.065, 0.018),
        earlywood_latewood_contrast=0.58,
        roughness_base=0.82,
        roughness_variation=0.10,
        pore_bump_scale_m=0.0006,
        finish_coating_amount=0.02,
        intended_real_world_scale_m=6.3,
        deterministic_seed=90217,
        mapping="triplanar",
        uv_identity=identity,
    )


def _evidence(
    root: Path,
    image: Image.Image,
    name: str,
    *,
    coordinate_domain: str = "uv",
    sampled_tile_span: float = 1.0,
) -> tuple[FidelityArtifact, FidelityArtifact]:
    """Persist an exact image and internally consistent typed mapping evidence."""

    directory = root / "fidelity/fixture"
    directory.mkdir(parents=True, exist_ok=True)
    image_path = directory / f"{name}.png"
    image.save(image_path, format="PNG", compress_level=9, optimize=False)
    texture_manifest_path = directory / f"{name}.texture.json"
    texture_manifest_path.write_text(
        json.dumps({"fixture": True, "name": name}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    coordinate_binding_path = directory / f"{name}.coordinates.json"
    coordinate_binding_path.write_text(
        json.dumps({"fixture": True, "coordinate_domain": coordinate_domain}, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    mapping_path = directory / f"{name}.mapping.json"
    mapping = DirectionalMappingEvidenceV01(
        job_id="wood_fixture",
        mapping_id=f"mapping-{name}",
        texture_manifest=artifact_at(root, texture_manifest_path),
        coordinate_binding=artifact_at(root, coordinate_binding_path),
        coordinate_domain=coordinate_domain,
        coordinate_extent=(1.0, 1.0),
        runtime_mapping_scale=(sampled_tile_span, sampled_tile_span),
        sampled_tile_span=sampled_tile_span,
        limitations=["synthetic unit-test coordinate evidence"],
    )
    mapping_path.write_text(mapping.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return artifact_at(root, image_path), artifact_at(root, mapping_path)


def _correlation(left: list[int], right: list[int]) -> float:
    """Measure deterministic profile similarity without adding a NumPy test dependency."""

    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_energy = sum((value - left_mean) ** 2 for value in left)
    right_energy = sum((value - right_mean) ** 2 for value in right)
    return numerator / math.sqrt(left_energy * right_energy)


def test_directional_wood_v2_is_deterministic_and_passes_local_preflight(tmp_path: Path) -> None:
    """Accept the non-single-period v2 tile while keeping the result nonhuman and advisory."""

    first = generate_directional_wood_v2(_wood())
    second = generate_directional_wood_v2(_wood())
    assert first["base_color"].tobytes() == second["base_color"].tobytes()
    image, mapping = _evidence(
        tmp_path,
        first["base_color"],
        "wood-v2",
        coordinate_domain="normalized_generated",
    )
    result = evaluate_directional_material(
        tmp_path,
        job_id="wood_fixture",
        preflight_id="wood-v2-preflight",
        image=image,
        mapping_evidence=mapping,
        expected_fibre_axis="y",
        coordinate_domain="normalized_generated",
        sampled_tile_span=1.0,
    )
    assert result.outcome == "preflight_passed"
    assert result.detected_fibre_axis == "y"
    assert result.dominant_harmonic_fraction < 0.8
    assert result.human_quality_disposition == "not_recorded"


def test_directional_wood_v2_avoids_straight_band_and_flat_channel_regression() -> None:
    """Require irregular longitudinal profiles and useful non-color channel variation."""

    channels = generate_directional_wood_v2(_wood())
    luminance = channels["base_color"].convert("L")
    sample_rows = [
        [luminance.getpixel((x, y)) for x in range(luminance.width)]
        for y in range(0, luminance.height, luminance.height // 8)
    ]
    correlations = [
        abs(_correlation(left, right))
        for index, left in enumerate(sample_rows)
        for right in sample_rows[index + 1 :]
    ]
    assert max(correlations) < 0.65
    base_extrema = channels["base_color"].getextrema()
    assert base_extrema[0][1] - base_extrema[0][0] >= 40
    height_extrema = channels["height"].getextrema()
    assert height_extrema[1] - height_extrema[0] >= 50
    normal_extrema = channels["normal"].getextrema()
    assert normal_extrema[0][1] - normal_extrema[0][0] >= 12
    roughness_extrema = channels["roughness"].getextrema()
    assert roughness_extrema[1] - roughness_extrema[0] >= 25


def test_single_period_and_under_sampled_tile_fail_before_blender(tmp_path: Path) -> None:
    """Catch the broad-band failure mode without spending a Blender render attempt."""

    image = Image.new("L", (128, 128))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            pixels[x, y] = round(128 + 96 * math.sin(math.tau * x * 12 / image.width))
    source, mapping = _evidence(
        tmp_path,
        image.convert("RGB"),
        "single-period",
        coordinate_domain="normalized_generated",
        sampled_tile_span=0.16,
    )
    result = evaluate_directional_material(
        tmp_path,
        job_id="wood_fixture",
        preflight_id="single-period-preflight",
        image=source,
        mapping_evidence=mapping,
        expected_fibre_axis="y",
        coordinate_domain="normalized_generated",
        sampled_tile_span=0.16,
    )
    assert result.outcome == "review_required"
    assert result.finding_codes == [
        "single_period_dominance",
        "insufficient_sampled_span",
    ]


def test_uniform_or_wrong_direction_does_not_invent_a_pass(tmp_path: Path) -> None:
    """Separate missing direction evidence from an explicitly opposite fibre direction."""

    uniform, mapping = _evidence(tmp_path, Image.new("RGB", (32, 32), "gray"), "uniform")
    empty = evaluate_directional_material(
        tmp_path,
        job_id="wood_fixture",
        preflight_id="uniform-preflight",
        image=uniform,
        mapping_evidence=mapping,
        expected_fibre_axis="y",
        coordinate_domain="uv",
        sampled_tile_span=1.0,
    )
    assert empty.detected_fibre_axis == "none"
    assert empty.finding_codes == ["insufficient_spatial_variation"]

    wrong_image, wrong_mapping = _evidence(
        tmp_path,
        generate_directional_wood_v2(_wood("x"))["base_color"],
        "wrong-axis",
    )
    wrong = evaluate_directional_material(
        tmp_path,
        job_id="wood_fixture",
        preflight_id="wrong-axis-preflight",
        image=wrong_image,
        mapping_evidence=wrong_mapping,
        expected_fibre_axis="y",
        coordinate_domain="uv",
        sampled_tile_span=1.0,
    )
    assert wrong.detected_fibre_axis == "x"
    assert "direction_mismatch" in wrong.finding_codes


def test_preflight_rehashes_inputs_and_rejects_reclassified_metrics(tmp_path: Path) -> None:
    """Fail closed on changed bytes or an attempt to rewrite deterministic classification."""

    image, mapping = _evidence(
        tmp_path,
        generate_directional_wood_v2(_wood())["base_color"],
        "tamper",
    )
    result = evaluate_directional_material(
        tmp_path,
        job_id="wood_fixture",
        preflight_id="tamper-preflight",
        image=image,
        mapping_evidence=mapping,
        expected_fibre_axis="y",
        coordinate_domain="uv",
        sampled_tile_span=1.0,
    )
    with pytest.raises(ValidationError, match="outcome contradicts"):
        result.model_copy(update={"outcome": "review_required"}).model_validate(
            result.model_copy(update={"outcome": "review_required"}).model_dump()
        )
    (tmp_path / image.path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="evidence changed"):
        evaluate_directional_material(
            tmp_path,
            job_id="wood_fixture",
            preflight_id="changed-preflight",
            image=image,
            mapping_evidence=mapping,
            expected_fibre_axis="y",
            coordinate_domain="uv",
            sampled_tile_span=1.0,
        )


def test_preflight_rejects_mapping_arguments_that_differ_from_exact_evidence(
    tmp_path: Path,
) -> None:
    """Prevent callers from masking an under-sampled mapping with replacement arguments."""

    image, mapping = _evidence(
        tmp_path,
        generate_directional_wood_v2(_wood())["base_color"],
        "mapping-mismatch",
        coordinate_domain="normalized_generated",
        sampled_tile_span=0.16,
    )
    with pytest.raises(ValueError, match="coordinate domain differs"):
        evaluate_directional_material(
            tmp_path,
            job_id="wood_fixture",
            preflight_id="mapping-domain-mismatch",
            image=image,
            mapping_evidence=mapping,
            expected_fibre_axis="y",
            coordinate_domain="uv",
            sampled_tile_span=0.16,
        )
    with pytest.raises(ValueError, match="sampled tile span differs"):
        evaluate_directional_material(
            tmp_path,
            job_id="wood_fixture",
            preflight_id="mapping-span-mismatch",
            image=image,
            mapping_evidence=mapping,
            expected_fibre_axis="y",
            coordinate_domain="normalized_generated",
            sampled_tile_span=1.0,
        )
