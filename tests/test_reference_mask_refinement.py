from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa import reference_mask
from codex_blender_modeler.workspace import sha256_file


def _showcase_spec() -> SceneSpec:
    """Load a compact valid SceneSpec and add competing observed evidence seeds."""

    repository = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (repository / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    raw["objects"][0]["evidence"] = [
        {
            "source_id": "ref.main",
            "bbox_norm": [0.1, 0.1, 0.9, 0.9],
            "status": "observed",
            "confidence": 0.99,
        }
    ]
    raw["objects"][1]["tags"].append("underside")
    raw["objects"][1]["evidence"] = [
        {
            "source_id": "ref.main",
            "bbox_norm": [0.2, 0.2, 0.8, 0.8],
            "status": "observed",
            "confidence": 0.8,
        }
    ]
    return SceneSpec.model_validate(raw)


def _rectangle(path: Path, bounds: tuple[int, int, int, int]) -> None:
    """Write one deterministic binary rectangle fixture."""

    image = Image.new("L", (100, 100), 0)
    ImageDraw.Draw(image).rectangle(bounds, fill=255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def test_seed_selection_prefers_one_underside_box_per_semantic_group() -> None:
    """Broad underside evidence wins over a more confident detail in the same group."""

    seeds = reference_mask.select_reference_evidence_seeds(_showcase_spec())
    assert len(seeds) == 1
    assert seeds[0].group_id == "demo.custom_pyramid".split(".")[0]
    assert seeds[0].object_id == "demo.profile_house"
    assert seeds[0].confidence == 0.8


def test_prepare_run_reference_mask_records_trusted_refinement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A trustworthy refinement becomes the run-local hashed request mask."""

    root = tmp_path / "job"
    run_dir = root / "qa" / "runs" / "run-refined"
    run_dir.mkdir(parents=True)
    reference = root / "input" / "reference.png"
    analysis_mask = root / "analysis" / "masks" / "reference_content.png"
    _rectangle(reference, (10, 10, 90, 90))
    _rectangle(analysis_mask, (5, 5, 95, 95))

    def trusted_candidate(reference_image, source_mask, seeds):
        """Return a smaller mask that retains the selected evidence core."""

        assert reference_image.size == source_mask.size == (100, 100)
        assert seeds
        candidate = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(candidate).rectangle((20, 20, 80, 80), fill=255)
        return candidate

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", trusted_candidate)
    output, manifest_path = reference_mask.prepare_run_reference_mask(
        root=root,
        run_dir=run_dir,
        reference_path=reference,
        analysis_mask_path=analysis_mask,
        spec=_showcase_spec(),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert output.parent == run_dir
    assert manifest["method"] == "opencv_grabcut_evidence_seeded"
    assert manifest["output_sha256"] == sha256_file(output)
    assert manifest["source_mask_sha256"] == sha256_file(analysis_mask)
    assert manifest["output_mask_metrics"]["foreground_fraction"] < (
        manifest["source_mask_metrics"]["foreground_fraction"]
    )
    assert manifest["output_mask_metrics"]["bbox_norm"] == [0.2, 0.2, 0.81, 0.81]


def test_prepare_run_reference_mask_falls_back_without_mutating_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Unavailable OpenCV preserves the analysis mask through a run-local binary copy."""

    root = tmp_path / "job"
    run_dir = root / "qa" / "runs" / "run-fallback"
    run_dir.mkdir(parents=True)
    reference = root / "input" / "reference.png"
    analysis_mask = root / "analysis" / "masks" / "reference_content.png"
    _rectangle(reference, (10, 10, 90, 90))
    _rectangle(analysis_mask, (5, 5, 95, 95))
    source_hash = sha256_file(analysis_mask)

    def unavailable(reference_image, source_mask, seeds):
        """Simulate an installation that omitted optional OpenCV vision extras."""

        raise RuntimeError("OpenCV vision extras are unavailable")

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", unavailable)
    output, manifest_path = reference_mask.prepare_run_reference_mask(
        root=root,
        run_dir=run_dir,
        reference_path=reference,
        analysis_mask_path=analysis_mask,
        spec=_showcase_spec(),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["method"] == "analysis_mask_fallback"
    assert "OpenCV vision extras are unavailable" in manifest["reason"]
    assert sha256_file(output) == source_hash
    assert sha256_file(analysis_mask) == source_hash


def test_primary_object_scope_excludes_surrounding_reference_foreground(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Clip object-only QA evidence to the explicitly tagged subject region."""

    root = tmp_path / "job"
    run_dir = root / "qa" / "runs" / "run-subject-only"
    run_dir.mkdir(parents=True)
    reference = root / "input" / "reference.png"
    analysis_mask = root / "analysis" / "masks" / "reference_content.png"
    _rectangle(reference, (5, 5, 95, 95))
    _rectangle(analysis_mask, (5, 5, 95, 95))
    raw = _showcase_spec().model_dump(mode="json")
    raw["objects"][0]["tags"] = ["qa_role:primary"]
    raw["objects"][0]["evidence"][0]["bbox_norm"] = [0.1, 0.1, 0.4, 0.9]
    raw["objects"][1]["tags"] = ["qa_role:decorative"]
    raw["objects"][1]["evidence"][0]["bbox_norm"] = [0.6, 0.1, 0.9, 0.9]
    spec = SceneSpec.model_validate(raw)

    def unavailable(reference_image, source_mask, seeds):
        """Force the deterministic scoped analysis-mask fallback."""

        assert [seed.object_id for seed in seeds] == [raw["objects"][0]["id"]]
        raise RuntimeError("OpenCV unavailable")

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", unavailable)
    output, manifest_path = reference_mask.prepare_run_reference_mask(
        root=root,
        run_dir=run_dir,
        reference_path=reference,
        analysis_mask_path=analysis_mask,
        spec=spec,
        reference_content_scope="primary_object_only",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["reference_content_scope"] == "primary_object_only"
    assert manifest["subject_object_ids"] == [raw["objects"][0]["id"]]
    assert manifest["output_mask_metrics"]["bbox_norm"][2] < 0.5
    assert sha256_file(analysis_mask) != ""
    assert output.is_file()


def test_closed_exterior_primary_scope_fills_only_enclosed_mask_holes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Explicit closed-exterior evidence removes highlight holes after trusted refinement."""

    root = tmp_path / "job"
    run_dir = root / "qa" / "runs" / "run-closed-exterior"
    run_dir.mkdir(parents=True)
    reference = root / "input" / "reference.png"
    analysis_mask = root / "analysis" / "masks" / "reference_content.png"
    _rectangle(reference, (10, 10, 90, 90))
    _rectangle(analysis_mask, (5, 5, 95, 95))
    raw = _showcase_spec().model_dump(mode="json")
    raw["objects"][0]["tags"] = ["qa_role:primary", "scope:closed_exterior"]
    raw["objects"][1]["tags"] = ["qa_role:supporting"]
    spec = SceneSpec.model_validate(raw)

    def holed_candidate(reference_image, source_mask, seeds):
        """Return one valid subject mask with a simulated metallic-highlight hole."""

        candidate = Image.new("L", (100, 100), 0)
        draw = ImageDraw.Draw(candidate)
        draw.rectangle((15, 15, 85, 85), fill=255)
        draw.rectangle((20, 45, 35, 70), fill=0)
        return candidate

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", holed_candidate)
    output, manifest_path = reference_mask.prepare_run_reference_mask(
        root=root,
        run_dir=run_dir,
        reference_path=reference,
        analysis_mask_path=analysis_mask,
        spec=spec,
        reference_content_scope="primary_object_only",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with Image.open(output) as opened:
        assert opened.convert("L").getpixel((25, 50)) == 255
        assert opened.convert("L").getpixel((0, 0)) == 0
    assert manifest["method"].endswith("_closed_exterior_hole_fill")
    assert manifest["closed_exterior_hole_fill"] == {
        "authorized": True,
        "applied": True,
        "filled_pixel_count": 416,
    }


def test_open_primary_scope_preserves_enclosed_reference_aperture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Without closed-exterior evidence, a real-looking aperture remains untouched."""

    root = tmp_path / "job"
    run_dir = root / "qa" / "runs" / "run-open-subject"
    run_dir.mkdir(parents=True)
    reference = root / "input" / "reference.png"
    analysis_mask = root / "analysis" / "masks" / "reference_content.png"
    _rectangle(reference, (10, 10, 90, 90))
    _rectangle(analysis_mask, (5, 5, 95, 95))
    raw = _showcase_spec().model_dump(mode="json")
    raw["objects"][0]["tags"] = ["qa_role:primary"]
    raw["objects"][1]["tags"] = ["qa_role:supporting"]
    spec = SceneSpec.model_validate(raw)

    def aperture_candidate(reference_image, source_mask, seeds):
        """Return one trusted mask containing an enclosed background aperture."""

        candidate = Image.new("L", (100, 100), 0)
        draw = ImageDraw.Draw(candidate)
        draw.rectangle((15, 15, 85, 85), fill=255)
        draw.rectangle((20, 45, 35, 70), fill=0)
        return candidate

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", aperture_candidate)
    output, manifest_path = reference_mask.prepare_run_reference_mask(
        root=root,
        run_dir=run_dir,
        reference_path=reference,
        analysis_mask_path=analysis_mask,
        spec=spec,
        reference_content_scope="primary_object_only",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with Image.open(output) as opened:
        assert opened.convert("L").getpixel((25, 50)) == 0
    assert manifest["method"] == "opencv_grabcut_evidence_seeded"
    assert manifest["closed_exterior_hole_fill"] == {
        "authorized": False,
        "applied": False,
        "filled_pixel_count": 0,
    }


def test_hole_fill_handles_foreground_touching_the_first_image_corner() -> None:
    """Flood exterior background from every border component, not only pixel zero."""

    source = Image.new("L", (20, 20), 0)
    draw = ImageDraw.Draw(source)
    draw.rectangle((0, 0, 14, 14), fill=255)
    draw.rectangle((5, 5, 8, 8), fill=0)

    filled, filled_pixel_count = reference_mask._fill_enclosed_holes(source)

    assert filled.getpixel((6, 6)) == 255
    assert filled.getpixel((19, 19)) == 0
    assert filled_pixel_count == 16
