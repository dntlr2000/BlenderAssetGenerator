"""Explicit interior mask samples never become semantic whole-part measurements."""

from __future__ import annotations

import json

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError
from test_reference_fidelity import hypothesis
from test_reference_mask_refinement import _showcase_spec

from codex_blender_modeler.blender_artifacts import stable_json_digest
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa import reference_mask
from codex_blender_modeler.qa.direct_compare import observed_regions_from_scene_spec
from codex_blender_modeler.qa.models import VisualQARequest
from codex_blender_modeler.reference_fidelity.models import (
    FidelityArtifact,
    ModelingHypothesisV01,
    ReferenceMaskSeedEvidenceV01,
    ReferenceMaskSeedV01,
    ReferenceObservation,
)
from codex_blender_modeler.reference_fidelity.service import (
    _validate_reference_seed_manifest,
    artifact_at,
)
from codex_blender_modeler.workspace import sha256_file


def _fixture(root):
    """Build a reference/scene with a whole-part box and a distinct inner sample."""
    reference = root / "input/reference.png"
    reference.parent.mkdir(parents=True)
    Image.new("RGB", (100, 100), (30, 70, 170)).save(reference)
    data = _showcase_spec().model_dump(mode="json")
    data["sources"][0]["path"] = "input/reference.png"
    spec = SceneSpec.model_validate_json(json.dumps(data))
    seed = ReferenceMaskSeedEvidenceV01(
        job_id=spec.job_id,
        reference=FidelityArtifact(path="input/reference.png", sha256=sha256_file(reference)),
        seeds=[ReferenceMaskSeedV01(
            object_id=spec.objects[0].id, source_id="ref.main", observation_id="blue-interior",
            bbox_norm=(.35, .35, .65, .65), confidence=.99,
        )],
    )
    return reference, spec, seed


def test_explicit_seed_preserves_whole_part_comparison_and_records_exact_selection(
    tmp_path, monkeypatch
):
    """Select a high-confidence interior for masking while direct QA keeps the whole box."""
    reference, spec, seed = _fixture(tmp_path)
    source = tmp_path / "scene.json"
    source.write_text(spec.model_dump_json(), encoding="utf-8")
    original = source.read_bytes()
    analysis_mask = tmp_path / "analysis.png"
    Image.new("L", (100, 100), 255).save(analysis_mask)

    def refined(_reference, _mask, seeds):
        """Expose exactly which independently supplied sample the mask algorithm receives."""
        assert seeds[0].bbox_norm == (.35, .35, .65, .65)
        candidate = Image.new("L", (100, 100), 0)
        ImageDraw.Draw(candidate).rectangle((15, 15, 85, 85), fill=255)
        return candidate

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", refined)
    output = tmp_path / "run"
    output.mkdir()
    mask, manifest_path = reference_mask.prepare_run_reference_mask(
        root=tmp_path, run_dir=output, reference_path=reference,
        analysis_mask_path=analysis_mask, spec=spec, seed_evidence=seed,
    )
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["seed_evidence"] == seed.model_dump(mode="json")
    assert manifest["seed_evidence_sha256"] == stable_json_digest(seed.model_dump(mode="json"))
    assert manifest["output_sha256"] == sha256_file(mask)
    assert observed_regions_from_scene_spec(source)[spec.objects[0].id][0] == (.1, .1, .9, .9)
    assert source.read_bytes() == original
    data = hypothesis().model_dump(mode="json")
    data.update(job_id=spec.job_id, reference=seed.reference.model_dump(mode="json"),
                reference_mask_seed_evidence=seed.model_dump(mode="json"))
    data["observations"].append(ReferenceObservation(
        observation_id="blue-interior", region=(.35, .35, .65, .65), status="observed",
        confidence=.99, description="Observed blue patch used solely as a segmentation seed.",
        uncertainty="This interior patch does not describe the entire object's extent.",
    ).model_dump(mode="json"))
    bound = ModelingHypothesisV01.model_validate_json(json.dumps(data))
    request = VisualQARequest(
        job_id=spec.job_id, run_id="run", mode="concept",
        reference_path=seed.reference.path, reference_sha256=seed.reference.sha256,
        reference_mask_path="run/reference_mask.png", reference_mask_sha256=sha256_file(mask),
        preview_path="run/beauty.png", preview_sha256="1" * 64,
        render_pass_manifest_path="run/manifest.json", render_pass_manifest_sha256="1" * 64,
        scene_spec_sha256=sha256_file(source), camera_fingerprint="1" * 64,
    )
    request_path = output / "request.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    request_ref = artifact_at(tmp_path, request_path)
    _validate_reference_seed_manifest(tmp_path, bound, spec, request, request_ref)
    # Reject independent tampering of each cross-artifact binding without repairing evidence.
    manifest_bytes = manifest_path.read_bytes()
    for key, value in (
        ("seed_evidence", None), ("seed_evidence_sha256", "0" * 64),
        ("reference_sha256", "0" * 64), ("output_sha256", "0" * 64),
        ("seeds", []), ("method", "analysis_mask_fallback"),
    ):
        changed = dict(manifest, **{key: value})
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError, match="explicit segmentation evidence"):
            _validate_reference_seed_manifest(tmp_path, bound, spec, request, request_ref)
        assert json.loads(manifest_path.read_bytes()) == changed
    manifest_path.write_bytes(manifest_bytes)
    mask.write_bytes(mask.read_bytes() + b"altered-mask-fixture")
    with pytest.raises(ValueError, match="mask bytes changed"):
        _validate_reference_seed_manifest(tmp_path, bound, spec, request, request_ref)
    assert source.read_bytes() == original


@pytest.mark.parametrize("mutation", [
    "reference_hash", "job", "source", "object", "outside", "non_subject", "unknown_version",
])
def test_explicit_seed_rejects_stale_foreign_or_unbound_samples(tmp_path, mutation):
    """Reject mismatched reference/subject bindings before producing any mask."""
    reference, spec, seed = _fixture(tmp_path)
    data = seed.model_dump(mode="json")
    allowed = {spec.objects[0].id}
    if mutation == "reference_hash":
        data["reference"]["sha256"] = "0" * 64
    elif mutation == "job":
        data["job_id"] = "foreign_job"
    elif mutation == "source":
        data["seeds"][0]["source_id"] = "unknown"
    elif mutation == "object":
        data["seeds"][0]["object_id"] = "unknown"
    elif mutation == "outside":
        data["seeds"][0]["bbox_norm"] = [.0, .0, .4, .4]
    elif mutation == "non_subject":
        allowed = {spec.objects[1].id}
    elif mutation == "unknown_version":
        data["schema_version"] = "0.9.0"
    with pytest.raises(ValueError):
        changed = ReferenceMaskSeedEvidenceV01.model_validate_json(json.dumps(data))
        reference_mask.validate_explicit_reference_seeds(
            tmp_path, reference, spec, changed, allowed_object_ids=allowed
        )


@pytest.mark.parametrize("failure", ["unavailable", "untrustworthy"])
def test_explicit_segmentation_failure_cannot_silently_fall_back(tmp_path, monkeypatch, failure):
    """Keep an explicit comparison contract fail-closed when segmentation is unavailable/bad."""
    reference, spec, seed = _fixture(tmp_path)
    source_mask = tmp_path / "analysis.png"
    Image.new("L", (100, 100), 255).save(source_mask)

    def failed(_reference, _mask, _seeds):
        """Return an empty result or reproduce a missing OpenCV dependency."""
        if failure == "unavailable":
            raise RuntimeError("vision unavailable")
        return Image.new("L", (100, 100), 0)

    monkeypatch.setattr(reference_mask, "_grabcut_refinement", failed)
    output = tmp_path / "run"
    output.mkdir()
    with pytest.raises(ValueError, match="silent fallback"):
        reference_mask.prepare_run_reference_mask(
            root=tmp_path, run_dir=output, reference_path=reference,
            analysis_mask_path=source_mask, spec=spec, seed_evidence=seed,
        )
    assert list(output.iterdir()) == []


def test_hypothesis_requires_exact_observed_seed_and_preserves_legacy_absence():
    """Bind each seed to an independent observation without auto-creating legacy evidence."""
    legacy = hypothesis()
    raw = legacy.model_dump(mode="json")
    raw.pop("reference_mask_seed_evidence")
    loaded = ModelingHypothesisV01.model_validate_json(json.dumps(raw))
    assert loaded.reference_mask_seed_evidence is None
    observation = ReferenceObservation(
        observation_id="interior-patch", region=(.3, .3, .6, .6), status="observed",
        confidence=.9, description="Visible foreground patch inside the observed body.",
        uncertainty="Interior foreground sampling only, not a whole-part size observation.",
    )
    seed = ReferenceMaskSeedEvidenceV01(job_id=legacy.job_id, reference=legacy.reference,
        seeds=[ReferenceMaskSeedV01(object_id="body", source_id="reference",
            observation_id=observation.observation_id, bbox_norm=observation.region,
            confidence=.9)])
    raw["observations"].append(observation.model_dump(mode="json"))
    raw["reference_mask_seed_evidence"] = seed.model_dump(mode="json")
    loaded = ModelingHypothesisV01.model_validate_json(json.dumps(raw))
    assert loaded.reference_mask_seed_evidence == seed
    raw["observations"][-1]["status"] = "inferred"
    with pytest.raises(ValidationError, match="exact observed region"):
        ModelingHypothesisV01.model_validate_json(json.dumps(raw))
