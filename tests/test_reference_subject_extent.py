"""Source-alpha-only V0.3 scope evidence; fixtures never establish artistic acceptance."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError
from test_reference_mask_refinement import _showcase_spec

from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa import reference_mask, reference_mask_constraints
from codex_blender_modeler.qa.reference_subject_extent import (
    SNAPSHOT_NAME,
    validate_reference_subject_extent,
    validate_subject_extent_manifest,
)
from codex_blender_modeler.reference_fidelity.models import (
    ReferenceMaskSeedEvidenceV01,
    ReferenceMaskSeedEvidenceV02,
    ReferenceMaskSeedEvidenceV03,
    ReferenceSubjectExtentEvidenceV01,
    parse_reference_mask_seed_evidence,
)
from codex_blender_modeler.reference_fidelity.service import artifact_at
from codex_blender_modeler.workspace import sha256_file


def _fixture(root):
    """Author independent alpha/trimap evidence with only one of two parts observed locally."""

    reference = root / "input/reference.png"
    reference.parent.mkdir(parents=True)
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 10, 89, 89), fill=(90, 130, 180, 255))
    image.save(reference)
    raw = _showcase_spec().model_dump(mode="json")
    raw["objects"] = raw["objects"][:2]
    raw["sources"][0]["path"] = "input/reference.png"
    raw["objects"][0]["tags"] = ["qa_role:primary"]
    raw["objects"][0]["evidence"][0]["bbox_norm"] = [0.4, 0.4, 0.6, 0.6]
    raw["objects"][1]["tags"] = ["qa_role:supporting"]
    raw["objects"][1]["evidence"][0]["status"] = "inferred"
    scene = SceneSpec.model_validate(raw)
    subject_ids = sorted(item.id for item in scene.objects)
    source = root / "source_mask.png"
    trimap = root / "trimap.png"
    support = image.getchannel("A")
    support.save(source)
    support.save(trimap)
    extent = ReferenceSubjectExtentEvidenceV01(
        job_id=scene.job_id,
        reference=artifact_at(root, reference),
        reference_resolution=(100, 100),
        subject_object_ids=subject_ids,
        observation_id="subject-alpha",
        bbox_pixels=(10, 10, 90, 90),
        foreground_pixel_count=6400,
        confidence=1.0,
        uncertainty="Source-alpha support only; no hidden geometry or human acceptance.",
    )
    extent_path = root / "extent.json"
    extent_path.write_text(extent.model_dump_json())
    seed = ReferenceMaskSeedEvidenceV03.model_validate_json(
        json.dumps(
            {
                "job_id": scene.job_id,
                "reference": artifact_at(root, reference).model_dump(mode="json"),
                "reference_resolution": [100, 100],
                "subject_object_ids": subject_ids,
                "trimap": artifact_at(root, trimap).model_dump(mode="json"),
                "subject_extent": artifact_at(root, extent_path).model_dump(mode="json"),
                "seeds": [
                    {
                        "object_id": scene.objects[0].id,
                        "source_id": "ref.main",
                        "observation_id": "center-interior",
                        "bbox_norm": [0.45, 0.45, 0.55, 0.55],
                        "confidence": 0.99,
                    }
                ],
                "label_observations": [
                    {
                        "observation_id": "source-fg",
                        "bbox_norm": [0.2, 0.2, 0.3, 0.3],
                        "label": "foreground",
                        "confidence": 0.99,
                    },
                    {
                        "observation_id": "source-bg",
                        "bbox_norm": [0, 0, 0.05, 0.05],
                        "label": "background",
                        "confidence": 0.99,
                    },
                ],
            }
        )
    )
    (root / "job.json").write_text(json.dumps({
        "job_id": scene.job_id, "reference_content_scope": "primary_object_only",
        "reference_sha256": sha256_file(reference),
        "sources": [{"kind": "reference", "path": "input/reference.png",
                     "sha256": sha256_file(reference)}],
    }))
    return SimpleNamespace(
        root=root,
        scene=scene,
        reference=reference,
        source=source,
        trimap=trimap,
        extent=extent,
        extent_path=extent_path,
        seed=seed,
        subject_ids=set(subject_ids),
    )


def _prepare(fix, monkeypatch, *, name="run-v03", seed=None):
    """Exercise native scope/seed/publication rules with a deterministic segmentation seam."""

    run = fix.root / name
    run.mkdir()

    def sure_labels(_reference, trimap):
        """Return the independently supplied binary sure-label fixture, not rendered geometry."""
        return trimap.copy()

    monkeypatch.setattr(reference_mask_constraints, "refine_reference_trimap", sure_labels)
    return reference_mask.prepare_run_reference_mask(
        root=fix.root,
        run_dir=run,
        reference_path=fix.reference,
        analysis_mask_path=fix.source,
        spec=fix.scene,
        reference_content_scope="primary_object_only",
        seed_evidence=seed or fix.seed,
    )


def test_v03_scope_is_independent_of_parts_and_snapshots_exact_source(tmp_path, monkeypatch):
    """Keep full source support with inferred partitions while part measurements stay untouched."""

    fix = _fixture(tmp_path)
    paths = [fix.reference, fix.source, fix.trimap, fix.extent_path]
    before = [path.read_bytes() for path in paths]
    scene_before = fix.scene.model_dump_json()
    mask, manifest_path = _prepare(fix, monkeypatch)
    manifest = json.loads(manifest_path.read_text())
    assert mask.read_bytes() == fix.source.read_bytes()
    assert manifest["subject_evidence_bbox_norm"] == [0.1, 0.1, 0.9, 0.9]
    assert manifest["subject_extent_snapshot"]["sha256"] == sha256_file(fix.extent_path)
    assert (mask.parent / SNAPSHOT_NAME).read_bytes() == fix.extent_path.read_bytes()
    validate_subject_extent_manifest(fix.root, mask.parent, manifest, fix.seed)
    assert before == [path.read_bytes() for path in paths]
    assert fix.scene.model_dump_json() == scene_before
    assert fix.scene.objects[0].evidence[0].bbox_norm == (0.4, 0.4, 0.6, 0.6)
    assert fix.scene.objects[1].evidence[0].status == "inferred"


def test_v03_does_not_supply_authority_to_v02_partial_scope(tmp_path, monkeypatch):
    """Removing the explicitly selected companion restores the no-companion clipping refusal."""

    fix = _fixture(tmp_path)
    data = fix.seed.model_dump(mode="json")
    data.pop("subject_extent")
    data["schema_version"] = "0.2.0"
    legacy = ReferenceMaskSeedEvidenceV02.model_validate_json(json.dumps(data))
    with pytest.raises(ValueError, match="reference mask scope is unscorable"):
        _prepare(fix, monkeypatch, seed=legacy)
    assert list((tmp_path / "run-v03").iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "other_job"),
        ("reference", {"path": "input/reference.png", "sha256": "0" * 64}),
        ("reference_content_scope", "full_reference"),
        ("subject_object_ids", ["demo.custom_pyramid"]),
        ("reference_resolution", [99, 100]),
        ("bbox_pixels", [9, 10, 90, 90]),
        ("foreground_pixel_count", 6399),
        ("candidate_or_render_derived", True),
        ("extent_origin", "render_alpha_support"),
        ("semantic_extent_authority", True),
        ("canonical_write_authority", True),
        ("human_approval_authority", True),
    ],
)
def test_rehashed_but_semantically_wrong_extent_is_rejected(tmp_path, field, value):
    """A newly matching file hash cannot make mismatched or render-derived declarations valid."""

    fix = _fixture(tmp_path)
    data = json.loads(fix.extent_path.read_text())
    data[field] = value
    fix.extent_path.write_text(json.dumps(data))
    rebound = fix.seed.model_copy(update={"subject_extent": artifact_at(tmp_path, fix.extent_path)})
    with pytest.raises((ValueError, ValidationError)):
        validate_reference_subject_extent(
            tmp_path, fix.reference, fix.scene, rebound, allowed_object_ids=fix.subject_ids
        )


@pytest.mark.parametrize("target", ["reference", "extent_path", "trimap"])
def test_changed_exact_input_bytes_cannot_publish_a_run(tmp_path, monkeypatch, target):
    """Tampering any hash-bound input is a technical rejection before mask publication."""

    fix = _fixture(tmp_path)
    path = getattr(fix, target)
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="evidence changed"):
        _prepare(fix, monkeypatch)
    assert list((tmp_path / "run-v03").iterdir()) == []


@pytest.mark.parametrize("mode,alpha", [("RGB", 255), ("RGBA", 255), ("RGBA", 0)])
def test_unsupported_or_opaque_reference_is_not_an_automatic_subject_extent(tmp_path, mode, alpha):
    """Only source RGBA containing both support and transparent exterior can prove this profile."""

    fix = _fixture(tmp_path)
    color = (20, 40, 60, alpha) if mode == "RGBA" else (20, 40, 60)
    Image.new(mode, (100, 100), color).save(fix.reference)
    reference = artifact_at(tmp_path, fix.reference)
    metadata = json.loads((tmp_path / "job.json").read_text())
    metadata["reference_sha256"] = reference.sha256
    metadata["sources"][0]["sha256"] = reference.sha256
    (tmp_path / "job.json").write_text(json.dumps(metadata))
    extent = fix.extent.model_copy(update={"reference": reference})
    fix.extent_path.write_text(extent.model_dump_json())
    seed = fix.seed.model_copy(
        update={"reference": reference, "subject_extent": artifact_at(tmp_path, fix.extent_path)}
    )
    with pytest.raises(ValueError, match="original RGBA alpha|transparent exterior"):
        validate_reference_subject_extent(
            tmp_path, fix.reference, fix.scene, seed, allowed_object_ids=fix.subject_ids
        )


@pytest.mark.parametrize("ids", [None, {"demo.custom_pyramid"}, {"foreign"}])
def test_extent_cannot_broaden_or_narrow_declared_subject_scope(tmp_path, ids):
    """The contract must bind the exact native primary/supporting subject set."""

    fix = _fixture(tmp_path)
    with pytest.raises(ValueError, match="scope or subject membership"):
        validate_reference_subject_extent(
            tmp_path, fix.reference, fix.scene, fix.seed, allowed_object_ids=ids
        )


def test_extent_tampering_during_segmentation_publishes_no_mask(tmp_path, monkeypatch):
    """Revalidate the selected extent immediately before publishing any successful output."""

    fix = _fixture(tmp_path)
    run = tmp_path / "run-race"
    run.mkdir()

    def changed_extent(_reference, trimap):
        """Simulate a stale concurrent source edit after validated segmentation inputs."""
        fix.extent_path.write_bytes(fix.extent_path.read_bytes() + b" ")
        return trimap.copy()

    monkeypatch.setattr(reference_mask_constraints, "refine_reference_trimap", changed_extent)
    with pytest.raises(ValueError, match="evidence changed"):
        reference_mask.prepare_run_reference_mask(
            root=tmp_path,
            run_dir=run,
            reference_path=fix.reference,
            analysis_mask_path=fix.source,
            spec=fix.scene,
            reference_content_scope="primary_object_only",
            seed_evidence=fix.seed,
        )
    assert list(run.iterdir()) == []


@pytest.mark.parametrize("mutation", ["snapshot", "binding", "scope", "bbox"])
def test_run_extent_snapshot_and_manifest_are_exact(tmp_path, monkeypatch, mutation):
    """Read-only review refuses tampered snapshot bytes or a substituted manifest binding."""

    fix = _fixture(tmp_path)
    mask, path = _prepare(fix, monkeypatch)
    manifest = json.loads(path.read_text())
    if mutation == "snapshot":
        snapshot = mask.parent / SNAPSHOT_NAME
        snapshot.write_bytes(snapshot.read_bytes() + b" ")
    elif mutation == "binding":
        manifest["subject_extent_snapshot"]["path"] = "extent.json"
    elif mutation == "scope":
        manifest["subject_object_ids"] = ["foreign"]
    else:
        manifest["subject_evidence_bbox_norm"] = [0, 0, 1, 1]
    with pytest.raises(ValueError, match="subject extent|evidence changed"):
        validate_subject_extent_manifest(tmp_path, mask.parent, manifest, fix.seed)


def test_v03_dispatch_is_exact_and_old_serialized_models_are_unchanged(tmp_path):
    """New optional dispatch adds no default fields or hash drift to legacy seed contracts."""

    fix = _fixture(tmp_path)
    assert type(parse_reference_mask_seed_evidence(fix.seed)) is ReferenceMaskSeedEvidenceV03
    v02 = fix.seed.model_dump(mode="json")
    v02.pop("subject_extent")
    v02["schema_version"] = "0.2.0"
    legacy_v02 = ReferenceMaskSeedEvidenceV02.model_validate_json(json.dumps(v02))
    legacy_v01 = ReferenceMaskSeedEvidenceV01.model_validate_json(
        json.dumps(
            {
                key: value
                for key, value in v02.items()
                if key in ReferenceMaskSeedEvidenceV01.model_fields
            }
            | {"schema_version": "0.1.0"}
        )
    )
    for legacy in (legacy_v01, legacy_v02):
        before = legacy.model_dump_json()
        assert parse_reference_mask_seed_evidence(legacy).model_dump_json() == before
        assert "subject_extent" not in before
    with pytest.raises(ValidationError):
        parse_reference_mask_seed_evidence(fix.seed.model_copy(update={"schema_version": "0.4.0"}))


def test_preexisting_extent_snapshot_is_never_overwritten(tmp_path, monkeypatch):
    """A colliding immutable snapshot blocks publication rather than repairing old evidence."""

    fix = _fixture(tmp_path)
    run = tmp_path / "occupied"
    run.mkdir()
    snapshot = run / SNAPSHOT_NAME
    snapshot.write_bytes(b"preserved")
    with pytest.raises(FileExistsError, match="subject extent snapshot"):
        reference_mask.prepare_run_reference_mask(
            root=tmp_path,
            run_dir=run,
            reference_path=fix.reference,
            analysis_mask_path=fix.source,
            spec=fix.scene,
            reference_content_scope="primary_object_only",
            seed_evidence=fix.seed,
        )
    assert list(run.iterdir()) == [snapshot] and snapshot.read_bytes() == b"preserved"


def test_full_hypothesis_review_revalidates_extent_snapshot(tmp_path, monkeypatch):
    """The real review-manifest path consumes V0.3 and refuses later snapshot substitution."""

    from test_reference_fidelity import hypothesis
    from test_reference_mask_constraints import request_for

    from codex_blender_modeler.reference_fidelity.models import ModelingHypothesisV01
    from codex_blender_modeler.reference_fidelity.service import _validate_reference_seed_manifest

    fix = _fixture(tmp_path)
    mask, _manifest_path = _prepare(fix, monkeypatch)
    data = hypothesis().model_dump(mode="json")
    data.update(
        job_id=fix.scene.job_id,
        reference=fix.seed.reference.model_dump(mode="json"),
        reference_mask_seed_evidence=fix.seed.model_dump(mode="json"),
    )
    for observation in [*fix.seed.seeds, *fix.seed.label_observations]:
        data["observations"].append(
            {
                "observation_id": observation.observation_id,
                "region": observation.bbox_norm,
                "status": "observed",
                "confidence": observation.confidence,
                "description": "Independent synthetic original-reference evidence for testing.",
                "uncertainty": "Fixture only; no real quality or human acceptance.",
            }
        )
    plan = ModelingHypothesisV01.model_validate_json(json.dumps(data))
    request, request_artifact = request_for(tmp_path, fix.scene, fix.seed, mask)
    request_path = mask.parent / "request.json"
    _validate_reference_seed_manifest(
        tmp_path, plan, fix.scene, request, artifact_at(tmp_path, request_path)
    )
    snapshot = mask.parent / SNAPSHOT_NAME
    snapshot.write_bytes(snapshot.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="evidence changed"):
        _validate_reference_seed_manifest(
            tmp_path, plan, fix.scene, request, artifact_at(tmp_path, request_path)
        )


def test_interrupted_snapshot_publication_cannot_be_adopted_as_success(tmp_path, monkeypatch):
    """An interrupted new run stays incomplete, and an existing partial mask is never accepted."""

    from pathlib import Path

    fix = _fixture(tmp_path)
    original_open = Path.open

    def fail_snapshot_open(path, mode="r", *args, **kwargs):
        """Interrupt only the uniquely owned new extent snapshot write after mask generation."""
        if path.name == SNAPSHOT_NAME and mode == "xb":
            raise OSError("fixture snapshot publication interrupted")
        return original_open(path, mode, *args, **kwargs)

    with monkeypatch.context() as local:
        local.setattr(Path, "open", fail_snapshot_open)
        with pytest.raises(OSError, match="snapshot publication interrupted"):
            _prepare(fix, local)
    run = tmp_path / "run-v03"
    assert (run / "reference_mask.png").is_file()
    assert not (run / "reference_mask_manifest.json").exists()
    with pytest.raises(FileExistsError, match="artifacts already exist"):
        reference_mask.prepare_run_reference_mask(
            root=tmp_path,
            run_dir=run,
            reference_path=fix.reference,
            analysis_mask_path=fix.source,
            spec=fix.scene,
            reference_content_scope="primary_object_only",
            seed_evidence=fix.seed,
        )
    assert not (run / "reference_mask_manifest.json").exists()


def test_snapshot_review_rechecks_original_image_hash(tmp_path, monkeypatch):
    """A valid extent JSON/snapshot cannot conceal changed original reference bytes."""

    fix = _fixture(tmp_path)
    mask, manifest_path = _prepare(fix, monkeypatch)
    manifest = json.loads(manifest_path.read_text())
    fix.reference.write_bytes(fix.reference.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="evidence changed"):
        validate_subject_extent_manifest(tmp_path, mask.parent, manifest, fix.seed)


def test_animated_rgba_cannot_supply_static_subject_extent(tmp_path):
    """Reject APNG rather than silently validating only the first frame of a static profile."""

    fix = _fixture(tmp_path)
    with Image.open(fix.reference) as opened:
        first = opened.copy()
    second = first.copy()
    second.putpixel((0, 0), (0, 0, 0, 255))
    first.save(fix.reference, save_all=True, append_images=[second], duration=100, loop=0)
    reference = artifact_at(tmp_path, fix.reference)
    metadata = json.loads((tmp_path / "job.json").read_text())
    metadata["reference_sha256"] = reference.sha256
    metadata["sources"][0]["sha256"] = reference.sha256
    (tmp_path / "job.json").write_text(json.dumps(metadata))
    extent = fix.extent.model_copy(update={"reference": reference})
    fix.extent_path.write_text(extent.model_dump_json())
    seed = fix.seed.model_copy(
        update={"reference": reference, "subject_extent": artifact_at(tmp_path, fix.extent_path)}
    )
    with pytest.raises(ValueError, match="single-frame static"):
        validate_reference_subject_extent(
            tmp_path, fix.reference, fix.scene, seed, allowed_object_ids=fix.subject_ids
        )


def test_render_pixels_reclassified_as_immutable_reference_are_rejected(tmp_path):
    """Matching source bytes and a mutable source declaration cannot relabel a render as input."""
    fix = _fixture(tmp_path)
    rendered = tmp_path / "renders/preview.png"
    rendered.parent.mkdir()
    rendered.write_bytes(fix.reference.read_bytes())
    reference = artifact_at(tmp_path, rendered)
    raw = fix.scene.model_dump(mode="json")
    raw["sources"][0]["path"] = reference.path
    scene = SceneSpec.model_validate(raw)
    fix.extent_path.write_text(
        fix.extent.model_copy(update={"reference": reference}).model_dump_json()
    )
    seed = fix.seed.model_copy(update={
        "reference": reference, "subject_extent": artifact_at(tmp_path, fix.extent_path),
    })
    with pytest.raises(ValueError, match="recorded immutable job input"):
        validate_reference_subject_extent(tmp_path, rendered, scene, seed,
                                          allowed_object_ids=fix.subject_ids)
    with pytest.raises(ValueError, match="recorded immutable job input"):
        reference_mask_constraints.validate_reference_trimap(
            tmp_path, rendered, scene, seed, allowed_object_ids=fix.subject_ids
        )


@pytest.mark.parametrize("mutation", ["hash", "path", "duplicate", "missing", "scope"])
def test_extent_requires_recorded_original_input_identity(tmp_path, mutation):
    """Reject changed or ambiguous job metadata without granting mutable SceneSpec authority."""
    fix = _fixture(tmp_path)
    path = tmp_path / "job.json"
    metadata = json.loads(path.read_text())
    if mutation == "hash":
        metadata["sources"][0]["sha256"] = "0" * 64
    elif mutation == "path":
        metadata["sources"][0]["path"] = "renders/preview.png"
    elif mutation == "duplicate":
        metadata["sources"].append(metadata["sources"][0].copy())
    elif mutation == "missing":
        metadata["sources"] = []
    else:
        metadata["reference_content_scope"] = "full_reference"
    path.write_text(json.dumps(metadata))
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_reference_subject_extent(tmp_path, fix.reference, fix.scene, fix.seed,
                                          allowed_object_ids=fix.subject_ids)


def test_extent_preserves_exact_historical_input_relocation(tmp_path):
    """Historical absolute Windows locators may resolve only to exact owned input bytes."""
    root = tmp_path / "geometry_showcase"
    fix = _fixture(root)
    path = root / "job.json"
    metadata = json.loads(path.read_text())
    metadata["sources"][0]["path"] = r"E:\old\workspaces\geometry_showcase\input\reference.png"
    path.write_text(json.dumps(metadata))
    validate_reference_subject_extent(root, fix.reference, fix.scene, fix.seed,
                                      allowed_object_ids=fix.subject_ids)
    assert json.loads(path.read_text()) == metadata
