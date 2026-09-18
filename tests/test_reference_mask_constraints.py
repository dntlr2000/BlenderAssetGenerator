"""Exact opt-in trimaps preserve legacy QA and add no geometry, budget or approval authority."""

from __future__ import annotations

import json

import pytest
from PIL import Image, ImageDraw
from test_reference_fidelity import hypothesis
from test_reference_mask_seed_evidence import _fixture as legacy_fixture

from codex_blender_modeler.qa import reference_mask, reference_mask_constraints
from codex_blender_modeler.qa.models import VisualQARequest
from codex_blender_modeler.reference_fidelity.models import (
    FidelityArtifact,
    ModelingHypothesisV01,
    ReferenceMaskLabelObservationV02,
    ReferenceMaskSeedEvidenceV02,
    ReferenceObservation,
    parse_reference_mask_seed_evidence,
)
from codex_blender_modeler.reference_fidelity.service import (
    _validate_reference_seed_manifest,
    artifact_at,
)
from codex_blender_modeler.workspace import sha256_file


def constraint_fixture(root):
    """Create an independently known rectangle and contiguous identically colored shadow."""
    reference, scene, legacy = legacy_fixture(root)
    image = Image.new("RGB", (100, 100), (200, 200, 200))
    ImageDraw.Draw(image).rectangle((20, 20, 80, 85), fill=(80, 80, 80))
    image.save(reference)
    reference_binding = FidelityArtifact(path=legacy.reference.path, sha256=sha256_file(reference))
    legacy = legacy.model_copy(update={"reference": reference_binding})
    analysis = root / "analysis.png"
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rectangle((15, 15, 85, 90), fill=255)
    mask.save(analysis)
    trimap_path = root / "reference_evidence/trimap.png"
    trimap_path.parent.mkdir(parents=True)
    trimap = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(trimap)
    draw.rectangle((18, 18, 82, 62), fill=85)
    draw.rectangle((20, 20, 80, 60), fill=170)
    draw.rectangle((22, 22, 78, 58), fill=255)
    trimap.save(trimap_path)
    seed = ReferenceMaskSeedEvidenceV02(
        **legacy.model_dump(exclude={"schema_version"}),
        trimap=artifact_at(root, trimap_path),
        reference_resolution=(100, 100),
        reference_content_scope="full_reference",
        subject_object_ids=[],
        label_observations=[
            ReferenceMaskLabelObservationV02(
                observation_id="known-metal",
                label="foreground",
                bbox_norm=(0.35, 0.35, 0.65, 0.45),
                confidence=0.99,
            ),
            ReferenceMaskLabelObservationV02(
                observation_id="known-shadow",
                label="background",
                bbox_norm=(0.35, 0.72, 0.65, 0.82),
                confidence=0.99,
            ),
        ],
    )
    data = hypothesis().model_dump(mode="json")
    data.update(
        job_id=scene.job_id,
        reference=reference_binding.model_dump(mode="json"),
        reference_mask_seed_evidence=seed.model_dump(mode="json"),
    )
    samples = [(item.observation_id, item.bbox_norm, item.confidence) for item in seed.seeds]
    samples += [
        (item.observation_id, item.bbox_norm, item.confidence) for item in seed.label_observations
    ]
    data["observations"].extend(
        ReferenceObservation(
            observation_id=name,
            region=region,
            confidence=confidence,
            status="observed",
            description="Known synthetic reference label, independent of any rendered candidate.",
            uncertainty="Fixture boundary tests only; this is not art or human acceptance.",
        ).model_dump(mode="json")
        for name, region, confidence in samples
    )
    observed = ModelingHypothesisV01.model_validate_json(json.dumps(data))
    return reference, scene, legacy, seed, analysis, observed


def prepare(root, reference, scene, seed, analysis, name):
    """Call the real run-mask host with isolated, create-once fixture output."""
    directory = root / name
    directory.mkdir()
    mask, manifest = reference_mask.prepare_run_reference_mask(
        root=root,
        run_dir=directory,
        reference_path=reference,
        analysis_mask_path=analysis,
        spec=scene,
        seed_evidence=seed,
    )
    return mask, manifest


def request_for(root, scene, seed, mask):
    """Bind an isolated mask result to an exact QA request for manifest validation."""
    request = VisualQARequest(
        job_id=scene.job_id,
        run_id=mask.parent.name,
        mode="concept",
        reference_path=seed.reference.path,
        reference_sha256=seed.reference.sha256,
        reference_mask_path=mask.relative_to(root).as_posix(),
        reference_mask_sha256=sha256_file(mask),
        preview_path="fixture/beauty.png",
        preview_sha256="1" * 64,
        render_pass_manifest_path="fixture/manifest.json",
        render_pass_manifest_sha256="1" * 64,
        scene_spec_sha256="1" * 64,
        camera_fingerprint="1" * 64,
    )
    path = mask.parent / "request.json"
    path.write_text(request.model_dump_json(), encoding="utf-8")
    return request, artifact_at(root, path)


def test_reference_constraints_separate_ambiguous_shadow_and_freeze_exact_input(tmp_path):
    """The opt-in preserves sure labels while V0.1 retains its reproducible prior behavior."""
    pytest.importorskip("cv2")
    reference, scene, legacy, seed, analysis, observed = constraint_fixture(tmp_path)
    original = {
        path: path.read_bytes() for path in (reference, analysis, tmp_path / seed.trimap.path)
    }
    old, _old_manifest = prepare(tmp_path, reference, scene, legacy, analysis, "legacy")
    mask, manifest_path = prepare(tmp_path, reference, scene, seed, analysis, "constrained")
    with Image.open(old) as image:
        assert image.getpixel((50, 77)) == 255
    with Image.open(mask) as image:
        assert image.getpixel((50, 77)) == 0
        assert image.getpixel((50, 40)) == 255
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["method"] == reference_mask_constraints.METHOD
    assert manifest["seed_evidence"] == seed.model_dump(mode="json")
    snapshot = tmp_path / manifest["trimap_snapshot"]["path"]
    assert snapshot.read_bytes() == original[tmp_path / seed.trimap.path]
    request, binding = request_for(tmp_path, scene, seed, mask)
    _validate_reference_seed_manifest(tmp_path, observed, scene, request, binding)
    # No rerender, mutation or second snapshot is permitted for the same output path.
    frozen = {path: path.read_bytes() for path in mask.parent.iterdir()}
    with pytest.raises(FileExistsError):
        reference_mask.prepare_run_reference_mask(
            root=tmp_path,
            run_dir=mask.parent,
            reference_path=reference,
            analysis_mask_path=analysis,
            spec=scene,
            seed_evidence=seed,
        )
    assert {path: path.read_bytes() for path in mask.parent.iterdir()} == frozen
    assert all(path.read_bytes() == data for path, data in original.items())


@pytest.mark.parametrize(
    "defect",
    [
        "reference_hash",
        "trimap_hash",
        "resolution",
        "unknown_labels",
        "mode",
        "frame_count",
        "wrong_observation",
        "seed_conflict",
        "scope",
        "subject",
        "escape",
        "unknown_version",
    ],
)
def test_stale_foreign_or_invalid_constraint_rejected_before_output(tmp_path, defect):
    """Reject invalid source/labels/scope before a run mask or snapshot is written."""
    reference, scene, _legacy, seed, analysis, _observed = constraint_fixture(tmp_path)
    raw = seed.model_dump(mode="json")
    trimap_path = tmp_path / seed.trimap.path
    if defect in {"unknown_labels", "mode", "frame_count", "wrong_observation", "seed_conflict"}:
        with Image.open(trimap_path) as image:
            image = image.copy()
        if defect == "unknown_labels":
            image.putpixel((10, 10), 42)
        elif defect == "mode":
            image = image.convert("RGB")
        elif defect == "wrong_observation":
            image.putpixel((50, 77), 255)
        elif defect == "seed_conflict":
            image.putpixel((50, 52), 0)
        if defect == "frame_count":
            image.save(trimap_path, save_all=True, append_images=[Image.new("L", image.size, 0)])
        else:
            image.save(trimap_path)
        raw["trimap"]["sha256"] = sha256_file(trimap_path)
    elif defect in {"reference_hash", "trimap_hash"}:
        raw["reference" if defect == "reference_hash" else "trimap"]["sha256"] = "0" * 64
    elif defect == "resolution":
        raw["reference_resolution"] = [99, 100]
    elif defect == "scope":
        raw.update(
            reference_content_scope="primary_object_only", subject_object_ids=[scene.objects[0].id]
        )
    elif defect == "subject":
        raw["subject_object_ids"] = ["foreign"]
    elif defect == "escape":
        raw["trimap"]["path"] = "../escaped.png"
    elif defect == "unknown_version":
        raw["schema_version"] = "0.3.0"
    output = tmp_path / "rejected"
    output.mkdir()
    with pytest.raises(ValueError):
        mutated = ReferenceMaskSeedEvidenceV02.model_validate_json(json.dumps(raw))
        reference_mask.prepare_run_reference_mask(
            root=tmp_path,
            run_dir=output,
            reference_path=reference,
            analysis_mask_path=analysis,
            spec=scene,
            seed_evidence=mutated,
        )
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("failure", ["dependency", "empty"])
def test_selected_constraints_never_silently_fallback(tmp_path, monkeypatch, failure):
    """An explicit constraint failure cannot produce legacy-mask pass evidence."""
    reference, scene, _legacy, seed, analysis, _observed = constraint_fixture(tmp_path)

    def failed(_reference, _trimap):
        """Simulate only a missing vision dependency or an invalid empty segmentation."""
        if failure == "dependency":
            raise RuntimeError("vision unavailable")
        return Image.new("L", (100, 100), 0)

    monkeypatch.setattr(reference_mask_constraints, "refine_reference_trimap", failed)
    with pytest.raises(ValueError, match="silent fallback"):
        prepare(tmp_path, reference, scene, seed, analysis, "failed")
    assert list((tmp_path / "failed").iterdir()) == []


@pytest.mark.parametrize("defect", ["method", "snapshot", "snapshot_bytes", "fill", "mixed_round"])
def test_exact_manifest_and_snapshot_are_required_after_render(tmp_path, defect):
    """Reject a different round or altered constraint/result binding without repairing it."""
    pytest.importorskip("cv2")
    reference, scene, _legacy, seed, analysis, observed = constraint_fixture(tmp_path)
    mask, path = prepare(tmp_path, reference, scene, seed, analysis, "round1")
    request, binding = request_for(tmp_path, scene, seed, mask)
    manifest = json.loads(path.read_bytes())
    if defect == "method":
        manifest["method"] = "opencv_grabcut_evidence_seeded"
    elif defect == "snapshot":
        manifest.pop("trimap_snapshot")
    elif defect == "snapshot_bytes":
        (tmp_path / manifest["trimap_snapshot"]["path"]).write_bytes(b"changed fixture")
    elif defect == "fill":
        manifest["closed_exterior_hole_fill"]["authorized"] = True
    else:
        second, _second_manifest = prepare(tmp_path, reference, scene, seed, analysis, "round2")
        manifest["trimap_snapshot"]["path"] = (
            (second.parent / "reference_trimap.png").relative_to(tmp_path).as_posix()
        )
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        _validate_reference_seed_manifest(tmp_path, observed, scene, request, binding)
    assert json.loads(path.read_bytes()) == manifest


def test_v02_labels_are_observed_and_legacy_serialization_is_unchanged(tmp_path):
    """Version dispatch is explicit, and new label evidence cannot be inferred or auto-created."""
    _reference, _scene, legacy, seed, _analysis, observed = constraint_fixture(tmp_path)
    original = legacy.model_dump_json()
    assert parse_reference_mask_seed_evidence(legacy).model_dump_json() == original
    assert parse_reference_mask_seed_evidence(seed) == seed
    original_hypothesis = hypothesis().model_dump_json()
    assert (
        ModelingHypothesisV01.model_validate_json(original_hypothesis).model_dump_json()
        == original_hypothesis
    )
    assert (
        ModelingHypothesisV01.model_validate_json(original_hypothesis).reference_mask_seed_evidence
        is None
    )
    raw = observed.model_dump(mode="json")
    raw["observations"][-1]["status"] = "inferred"
    with pytest.raises(ValueError, match="exact observed region"):
        ModelingHypothesisV01.model_validate_json(json.dumps(raw))
    with pytest.raises(ValueError):
        parse_reference_mask_seed_evidence(seed.model_copy(update={"schema_version": "0.1.0"}))


def test_isolated_qa_checks_constraints_before_blender_or_output(tmp_path, monkeypatch):
    """A stale constraint cannot create QA files, spend a render, or reach Blender."""
    from codex_blender_modeler import blender_artifact_runner
    from codex_blender_modeler.qa import service

    reference, scene, _legacy, seed, _analysis, _observed = constraint_fixture(tmp_path)
    source = tmp_path / "scene.json"
    source.write_text(scene.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(service, "job_dir", lambda _job: tmp_path)
    monkeypatch.setattr(
        service, "load_job", lambda _job: {"reference_content_scope": "full_reference"}
    )
    monkeypatch.setattr(service, "find_reference", lambda _job: reference)

    def unexpected(*_args, **_kwargs):
        """Fail if source validation was postponed until after a Blender call."""
        raise AssertionError("Blender must not run for a stale constraint")

    monkeypatch.setattr(blender_artifact_runner, "render_scene_qa_passes", unexpected)
    (tmp_path / seed.trimap.path).write_bytes(b"changed fixture")
    with pytest.raises(ValueError, match="evidence changed"):
        service.run_scene_spec_visual_qa_snapshot(
            scene.job_id,
            scene_spec_path=source,
            blend_path=tmp_path / "scene.blend",
            run_dir=tmp_path / "qa/run",
            run_id="run",
            reference_mask_seed_evidence=seed,
        )
    assert not (tmp_path / "qa").exists()


def test_trimap_change_during_segmentation_cannot_publish_result(tmp_path, monkeypatch):
    """Source drift after validation still fails before a run-owned mask is created."""
    reference, scene, _legacy, seed, analysis, _observed = constraint_fixture(tmp_path)

    def changed_source(_reference, trimap):
        """Return plausible fixture pixels while emulating concurrent source tampering."""
        (tmp_path / seed.trimap.path).write_bytes(b"concurrently altered fixture")
        return trimap.point(lambda value: 255 if value >= 170 else 0)

    monkeypatch.setattr(reference_mask_constraints, "refine_reference_trimap", changed_source)
    with pytest.raises(ValueError, match="evidence changed"):
        prepare(tmp_path, reference, scene, seed, analysis, "drift")
    assert list((tmp_path / "drift").iterdir()) == []


def test_aq_validates_trimap_before_render_reservation(tmp_path, monkeypatch):
    """The live funded render boundary rejects stale constraint bytes without charging QA."""
    from test_quality_revision_flow import quality_fixture

    from codex_blender_modeler import workspace
    from codex_blender_modeler.autonomy_v2 import quality_revision_service as service
    from codex_blender_modeler.models import SceneSpec
    from codex_blender_modeler.qa import service as qa_service
    from codex_blender_modeler.reference_fidelity.service import publish

    fixture = quality_fixture(tmp_path, monkeypatch, funded=True)
    root = fixture.root
    reference, scene, _legacy, seed, _analysis, observed = constraint_fixture(root / "constraints")
    source = FidelityArtifact(
        path=reference.relative_to(root).as_posix(), sha256=sha256_file(reference)
    )
    selected = seed.model_copy(
        update={
            "job_id": fixture.job,
            "reference": source,
            "trimap": artifact_at(root, root / "constraints" / seed.trimap.path),
        }
    )
    observed = observed.model_copy(
        update={
            "job_id": fixture.job,
            "reference": source,
            "reference_mask_seed_evidence": selected,
        }
    )
    observed = ModelingHypothesisV01.model_validate_json(observed.model_dump_json())
    hypothesis_ref = publish(root, root / "fidelity/constrained-hypothesis.json", observed)
    loop = fixture.loop.model_copy(update={"hypothesis": hypothesis_ref})
    loop_ref = publish(root, root / "fidelity/constrained-loop.json", loop)
    data = scene.model_dump(mode="json")
    data["job_id"] = fixture.job
    data["sources"][0]["path"] = source.path
    bound_scene = SceneSpec.model_validate_json(json.dumps(data))
    (root / "analysis/scene_spec.json").write_text(bound_scene.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(service, "load_optional_loop", lambda *_: (loop, loop_ref))
    monkeypatch.setattr(workspace, "find_reference", lambda _job: reference)
    monkeypatch.setattr(
        workspace, "load_job", lambda _job: {"reference_content_scope": "full_reference"}
    )

    def unexpected(*_args, **_kwargs):
        """Reject a renderer call reached before exact constraint validation."""
        raise AssertionError("Stale constraint reached the renderer")

    monkeypatch.setattr(qa_service, "run_scene_spec_visual_qa_snapshot", unexpected)
    before = fixture.holder.state.model_dump_json()
    (root / selected.trimap.path).write_bytes(b"stale constraint fixture")
    with pytest.raises(ValueError, match="evidence changed"):
        service.render_quality_evidence(fixture.job, fixture.session, run_id="constrained")
    assert not (fixture.session_path / "fidelity/render_reservations").exists()
    assert fixture.holder.state.model_dump_json() == before
