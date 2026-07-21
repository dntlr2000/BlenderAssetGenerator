from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.qa import (
    ExistingFileQATargetProvider,
    VisualQARequest,
    compare_preview_to_generated_target,
    generate_optional_qa_target,
)
from codex_blender_modeler.workspace import sha256_file

SHA = "0" * 64


def _request(image_path: Path) -> VisualQARequest:
    """Build one explicit generated-target request for adapter tests."""

    return VisualQARequest(
        job_id="advisory_test",
        run_id="run-001",
        mode="concept",
        reference_path=str(image_path),
        reference_sha256=SHA,
        reference_mask_path=str(image_path),
        reference_mask_sha256=SHA,
        preview_path=str(image_path),
        preview_sha256=SHA,
        render_pass_manifest_path="render_pass_manifest.json",
        render_pass_manifest_sha256=SHA,
        scene_spec_sha256=SHA,
        camera_fingerprint=SHA,
        include_generated_target=True,
    )


def _preview_fixture(path: Path) -> None:
    """Write one deterministic fixed-camera beauty-like image."""

    image = Image.new("RGB", (128, 96), (8, 12, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 18, 64, 76), fill=(220, 64, 32))
    draw.rectangle((72, 30, 108, 70), fill=(42, 170, 96))
    image.save(path)


def _divergent_fixture(path: Path) -> None:
    """Write a spatially and chromatically divergent advisory target."""

    image = Image.new("RGB", (128, 96), (220, 220, 210))
    draw = ImageDraw.Draw(image)
    draw.ellipse((72, 8, 124, 60), fill=(20, 50, 230))
    draw.polygon([(8, 90), (45, 35), (66, 90)], fill=(240, 210, 20))
    image.save(path)


def test_identical_generated_target_produces_no_advisory_findings(tmp_path: Path) -> None:
    """Pixel-identical same-camera inputs do not create advisory discrepancy findings."""

    preview = tmp_path / "preview.png"
    target = tmp_path / "target.png"
    _preview_fixture(preview)
    target.write_bytes(preview.read_bytes())

    findings = compare_preview_to_generated_target(preview, target)

    assert findings == []


def test_divergent_generated_target_is_low_confidence_and_non_actionable(
    tmp_path: Path,
) -> None:
    """Divergent imagery yields only low-confidence generated-target observations."""

    preview = tmp_path / "preview.png"
    target = tmp_path / "target.png"
    _preview_fixture(preview)
    _divergent_fixture(target)

    findings = compare_preview_to_generated_target(preview, target)

    assert {finding.issue_type for finding in findings} == {"silhouette", "color_block"}
    assert all(finding.evidence_sources == ["generated_target"] for finding in findings)
    assert all(finding.confidence <= 0.35 for finding in findings)
    assert all(finding.suggestion is None for finding in findings)
    assert all("advisory_overall_similarity" in finding.metrics for finding in findings)


def test_generated_target_weight_caps_only_advisory_confidence(tmp_path: Path) -> None:
    """Configured target weight affects advisory confidence without making edits executable."""

    preview = tmp_path / "preview.png"
    target = tmp_path / "target.png"
    _preview_fixture(preview)
    _divergent_fixture(target)

    findings = compare_preview_to_generated_target(
        preview,
        target,
        advisory_weight=0.05,
    )

    assert findings
    assert all(finding.confidence <= 0.05 for finding in findings)
    assert all(finding.metrics["configured_advisory_weight"] == 0.05 for finding in findings)
    assert all(finding.suggestion is None for finding in findings)

    with pytest.raises(ValueError, match="advisory_weight"):
        compare_preview_to_generated_target(preview, target, advisory_weight=1.1)


def test_existing_file_provider_copies_explicit_image_and_records_provenance(
    tmp_path: Path,
) -> None:
    """The file adapter copies a bounded absolute image and retains model metadata."""

    generated_root = tmp_path / "generated"
    generated_root.mkdir()
    source = generated_root / "imagen_target.png"
    _preview_fixture(source)
    provider = ExistingFileQATargetProvider(
        source.resolve(),
        model="imagen-test",
        model_version="2026-07",
        seed=17,
        allowed_root=generated_root.resolve(),
    )
    output = tmp_path / "job" / "qa" / "runs" / "run-001" / "target" / "qa_target.png"

    manifest = generate_optional_qa_target(
        _request(source),
        provider=provider,
        prompt="same fixed camera",
        output_path=output,
    )

    assert manifest.status == "generated"
    assert manifest.provider == "existing_file"
    assert manifest.model == "imagen-test"
    assert manifest.model_version == "2026-07"
    assert manifest.seed == 17
    assert output.read_bytes() == source.read_bytes()
    assert manifest.output_sha256 == sha256_file(output)


def test_existing_file_provider_rejects_relative_and_out_of_root_paths(
    tmp_path: Path,
) -> None:
    """The adapter rejects ambiguous relative sources and resolved boundary escapes."""

    with pytest.raises(ValueError, match="must be absolute"):
        ExistingFileQATargetProvider(Path("target.png"), model="imagen-test")

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.png"
    _preview_fixture(outside)
    with pytest.raises(ValueError, match="outside allowed_root"):
        ExistingFileQATargetProvider(
            outside.resolve(),
            model="imagen-test",
            allowed_root=allowed.resolve(),
        )
