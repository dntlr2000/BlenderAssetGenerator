from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError

from codex_blender_modeler.qa.hashing import canonical_json_sha256
from codex_blender_modeler.reference_evidence.models import (
    CameraHypothesisSet,
    EvidenceArtifact,
    ReferenceEvidence,
)
from codex_blender_modeler.reference_evidence.segmentation import (
    generate_foreground_mask_candidates,
)
from codex_blender_modeler.reference_evidence.service import (
    load_camera_hypothesis_set,
    load_reference_evidence,
    run_reference_evidence,
)


def _sha256(path: Path) -> str:
    """Hash one test artifact for exact evidence assertions."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_reference(path: Path) -> None:
    """Create a deterministic hard-surface-like reference fixture."""

    image = Image.new("RGB", (160, 112), (232, 235, 238))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((35, 24, 128, 91), radius=11, fill=(35, 79, 118))
    draw.rectangle((47, 39, 116, 76), fill=(77, 141, 178))
    draw.ellipse((60, 46, 82, 68), fill=(215, 226, 232))
    draw.line((35, 86, 128, 86), fill=(16, 33, 48), width=4)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


class _FakeAdviser:
    """Return advisory-only observations without proposing canonical artifacts."""

    provider_name = "tests.fake_reference_adviser"
    provider_version = "1.2.3"

    def observe(self, image_path: Path) -> list[tuple[str, str, float]]:
        """Return bounded fixture advice while proving the source exists."""

        assert image_path.is_file()
        return [
            (
                "uncertainty",
                "The rear face remains occluded and must stay inferred.",
                0.75,
            )
        ]


def test_reference_evidence_models_reject_unknown_fields_and_unsafe_paths() -> None:
    """Require strict unknown-field and normalized relative-path validation."""

    digest = "a" * 64
    artifact = EvidenceArtifact(
        artifact_id="source-image",
        path="input/reference.png",
        sha256=digest,
        media_type="image/png",
        byte_size=10,
    )
    with pytest.raises(ValidationError):
        EvidenceArtifact.model_validate({**artifact.model_dump(), "unexpected": True})
    for unsafe in (
        "../input/reference.png",
        "/input/reference.png",
        "C:/input/reference.png",
        "input\\reference.png",
        "input//reference.png",
    ):
        with pytest.raises(ValidationError):
            EvidenceArtifact(
                artifact_id="source-image",
                path=unsafe,
                sha256=digest,
                media_type="image/png",
                byte_size=10,
            )


def test_pillow_segmentation_is_deterministic_and_bounded(tmp_path: Path) -> None:
    """Keep Pillow evidence deterministic, complete, and limited to three candidates."""

    image_path = tmp_path / "reference.png"
    _write_reference(image_path)
    first, first_warnings = generate_foreground_mask_candidates(
        image_path,
        tmp_path / "first",
        "reference_evidence/runs/run-one/masks",
        provider="pillow",
    )
    second, second_warnings = generate_foreground_mask_candidates(
        image_path,
        tmp_path / "second",
        "reference_evidence/runs/run-two/masks",
        provider="pillow",
    )
    assert first_warnings == second_warnings == []
    assert 1 <= len(first) <= 3
    assert [item.rank for item in first] == list(range(1, len(first) + 1))
    assert [item.artifact.sha256 for item in first] == [
        item.artifact.sha256 for item in second
    ]
    for candidate in first:
        assert candidate.provenance.provider == "pillow"
        assert 0.0 <= candidate.metrics.area_ratio <= 1.0
        assert 0.0 <= candidate.metrics.edge_agreement <= 1.0
        assert 0.0 <= candidate.metrics.border_contact_ratio <= 1.0
        assert 0.0 <= candidate.metrics.bilateral_symmetry <= 1.0
        assert 0.0 <= candidate.metrics.shadow_likelihood <= 1.0
        assert 0.0 <= candidate.metrics.reflection_likelihood <= 1.0
        assert 0.0 <= candidate.metrics.confidence <= 1.0


def test_auto_segmentation_always_retains_pillow_fallback(tmp_path: Path) -> None:
    """Retain at least one Pillow mask even when optional OpenCV candidates exist."""

    image_path = tmp_path / "reference.png"
    _write_reference(image_path)
    candidates, _ = generate_foreground_mask_candidates(
        image_path,
        tmp_path / "masks",
        "reference_evidence/runs/auto/masks",
        provider="auto",
    )
    assert 1 <= len(candidates) <= 3
    assert "pillow" in {item.provenance.provider for item in candidates}


def test_uniform_reference_is_reported_as_underconstrained(tmp_path: Path) -> None:
    """Avoid inventing a confident foreground mask for a uniform source image."""

    image_path = tmp_path / "uniform.png"
    Image.new("RGB", (80, 80), (128, 128, 128)).save(image_path)
    candidates, _ = generate_foreground_mask_candidates(
        image_path,
        tmp_path / "masks",
        "reference_evidence/runs/uniform/masks",
        provider="pillow",
    )
    assert len(candidates) == 1
    assert candidates[0].status == "underconstrained"
    assert candidates[0].provenance.method == "underconstrained_center_inset"


def test_service_writes_exact_run_owned_evidence_without_camera_mutation(
    tmp_path: Path,
) -> None:
    """Bind exact run hashes while preserving a pre-existing canonical camera file."""

    root = tmp_path / "asset_job"
    source = root / "input" / "reference.png"
    _write_reference(source)
    canonical_camera = root / "analysis" / "camera_solution.json"
    canonical_camera.parent.mkdir(parents=True, exist_ok=True)
    canonical_camera.write_text('{"immutable":"camera"}\n', encoding="utf-8")
    canonical_before = _sha256(canonical_camera)

    result = run_reference_evidence(
        root,
        job_id="asset_job",
        run_id="aq-ref-001",
        source_image_path="input/reference.png",
        workflow_id="workflow-001",
        dispatch_id="dispatch-001",
        provider="pillow",
    )

    evidence_path = root / Path(*result.reference_evidence_path.split("/"))
    cameras_path = root / Path(*result.camera_hypothesis_set_path.split("/"))
    evidence = load_reference_evidence(evidence_path)
    cameras = load_camera_hypothesis_set(cameras_path)
    manifest = json.loads(
        (evidence_path.parent / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert isinstance(evidence, ReferenceEvidence)
    assert isinstance(cameras, CameraHypothesisSet)
    assert result.reference_evidence_sha256 == _sha256(evidence_path)
    assert result.camera_hypothesis_set_sha256 == _sha256(cameras_path)
    assert result.summary_sha256 == _sha256(
        root / Path(*result.summary_path.split("/"))
    )
    assert cameras.reference_evidence_sha256 == result.reference_evidence_sha256
    assert cameras.source_fingerprint == evidence.source_fingerprint
    assert evidence.input_sha256 == canonical_json_sha256(manifest["request_binding"])
    assert evidence.workflow_id == "workflow-001"
    assert evidence.dispatch_id == "dispatch-001"
    assert cameras.input_sha256 == canonical_json_sha256(
        {
            "reference_evidence_path": result.reference_evidence_path,
            "reference_evidence_sha256": result.reference_evidence_sha256,
            "source_image_sha256": evidence.source_image.sha256,
            "source_fingerprint": evidence.source_fingerprint,
        }
    )
    assert {item.projection for item in cameras.hypotheses} == {
        "perspective",
        "orthographic",
    }
    assert cameras.projection_ambiguity in {"ambiguous", "underconstrained"}
    assert cameras.canonical_camera_mutated is False
    assert cameras.canonical_promotion_allowed is False
    assert result.input_sha256 == evidence.input_sha256
    missing_evidence = evidence.model_dump(mode="json")
    missing_evidence.pop("input_sha256")
    with pytest.raises(ValidationError):
        ReferenceEvidence.model_validate_json(json.dumps(missing_evidence))
    partial_evidence = evidence.model_dump(mode="json")
    partial_evidence["dispatch_id"] = None
    with pytest.raises(ValidationError):
        ReferenceEvidence.model_validate_json(json.dumps(partial_evidence))
    missing_cameras = cameras.model_dump(mode="json")
    missing_cameras.pop("input_sha256")
    with pytest.raises(ValidationError):
        CameraHypothesisSet.model_validate_json(json.dumps(missing_cameras))
    partial_cameras = cameras.model_dump(mode="json")
    partial_cameras["workflow_id"] = None
    with pytest.raises(ValidationError):
        CameraHypothesisSet.model_validate_json(json.dumps(partial_cameras))
    assert canonical_before == _sha256(canonical_camera)
    assert (evidence_path.parent / "reference_evidence_summary.md").is_file()
    assert all("\\" not in item.artifact.path for item in evidence.mask_candidates)


def test_advisory_provider_cannot_change_selected_mask(tmp_path: Path) -> None:
    """Keep optional provider observations advisory and outside deterministic selection."""

    root = tmp_path / "advisory_job"
    _write_reference(root / "input" / "reference.png")
    baseline_result = run_reference_evidence(
        root,
        job_id="advisory_job",
        run_id="baseline",
        source_image_path="input/reference.png",
        provider="pillow",
    )
    advised_result = run_reference_evidence(
        root,
        job_id="advisory_job",
        run_id="advised",
        source_image_path="input/reference.png",
        provider="pillow",
        advisory_provider=_FakeAdviser(),
    )
    baseline = load_reference_evidence(
        root / Path(*baseline_result.reference_evidence_path.split("/"))
    )
    advised = load_reference_evidence(
        root / Path(*advised_result.reference_evidence_path.split("/"))
    )
    assert baseline.source_fingerprint == advised.source_fingerprint
    assert baseline.workflow_id == advised.workflow_id == "reference-standalone"
    assert baseline.dispatch_id == advised.dispatch_id == "reference-standalone"
    assert baseline.input_sha256 is not None
    assert advised.input_sha256 is not None
    assert baseline.selected_candidate_id == advised.selected_candidate_id
    assert [item.artifact.sha256 for item in baseline.mask_candidates] == [
        item.artifact.sha256 for item in advised.mask_candidates
    ]
    assert len(advised.advisory_observations) == 1
    assert advised.advisory_observations[0].provenance.advisory_only is True


def test_service_adopts_exact_existing_run_and_rejects_path_escape(tmp_path: Path) -> None:
    """Adopt an exact complete run while rejecting paths outside the owning job."""

    root = tmp_path / "closed_job"
    _write_reference(root / "input" / "reference.png")
    first = run_reference_evidence(
        root,
        job_id="closed_job",
        run_id="immutable-run",
        source_image_path="input/reference.png",
        provider="pillow",
    )
    run_root = root / "reference_evidence" / "runs" / "immutable-run"
    before = {item.name: _sha256(item) for item in run_root.iterdir() if item.is_file()}
    second = run_reference_evidence(
        root,
        job_id="closed_job",
        run_id="immutable-run",
        source_image_path="input/reference.png",
        provider="pillow",
    )
    after = {item.name: _sha256(item) for item in run_root.iterdir() if item.is_file()}
    assert first == second
    assert before == after
    assert (run_root / "run_result.json").is_file()
    assert (run_root / "run_manifest.json").is_file()
    with pytest.raises(ValidationError):
        run_reference_evidence(
            root,
            job_id="closed_job",
            run_id="escape-run",
            source_image_path="../outside.png",
            provider="pillow",
        )


def test_service_recovers_a_complete_unpublished_stage(tmp_path: Path) -> None:
    """Publish a complete hash-valid stage after a process interruption."""

    root = tmp_path / "recover_job"
    _write_reference(root / "input" / "reference.png")
    expected = run_reference_evidence(
        root,
        job_id="recover_job",
        run_id="recoverable-run",
        source_image_path="input/reference.png",
        workflow_id="workflow-001",
        provider="pillow",
    )
    final_root = root / "reference_evidence" / "runs" / "recoverable-run"
    stage_root = final_root.parent / ".recoverable-run.staging"
    final_root.rename(stage_root)

    recovered = run_reference_evidence(
        root,
        job_id="recover_job",
        run_id="recoverable-run",
        source_image_path="input/reference.png",
        workflow_id="workflow-001",
        provider="pillow",
    )

    assert recovered == expected
    assert final_root.is_dir()
    assert not stage_root.exists()


def test_service_quarantines_incomplete_stage_and_fails_closed(tmp_path: Path) -> None:
    """Preserve incomplete staging evidence before allowing a later clean attempt."""

    root = tmp_path / "interrupted_job"
    _write_reference(root / "input" / "reference.png")
    runs_root = root / "reference_evidence" / "runs"
    stage_root = runs_root / ".interrupted-run.staging"
    stage_root.mkdir(parents=True)
    (stage_root / "partial.txt").write_text("interrupted\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="preserved at"):
        run_reference_evidence(
            root,
            job_id="interrupted_job",
            run_id="interrupted-run",
            source_image_path="input/reference.png",
            provider="pillow",
        )

    quarantines = list((root / "reference_evidence" / "interrupted_staging").iterdir())
    assert len(quarantines) == 1
    assert (quarantines[0] / "partial.txt").read_text(encoding="utf-8") == "interrupted\n"
    assert not stage_root.exists()
    assert not (runs_root / "interrupted-run").exists()

    result = run_reference_evidence(
        root,
        job_id="interrupted_job",
        run_id="interrupted-run",
        source_image_path="input/reference.png",
        provider="pillow",
    )
    assert result.run_id == "interrupted-run"


def test_service_rejects_tampered_or_differently_bound_existing_run(
    tmp_path: Path,
) -> None:
    """Fail closed for output tampering and provider/source binding changes."""

    root = tmp_path / "tamper_job"
    source = root / "input" / "reference.png"
    _write_reference(source)
    result = run_reference_evidence(
        root,
        job_id="tamper_job",
        run_id="bound-run",
        source_image_path="input/reference.png",
        dispatch_id="dispatch-001",
        provider="pillow",
    )
    with pytest.raises(ValueError, match="different exact request"):
        run_reference_evidence(
            root,
            job_id="tamper_job",
            run_id="bound-run",
            source_image_path="input/reference.png",
            dispatch_id="dispatch-001",
            provider="auto",
        )

    summary = root / Path(*result.summary_path.split("/"))
    summary.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing or stale"):
        run_reference_evidence(
            root,
            job_id="tamper_job",
            run_id="bound-run",
            source_image_path="input/reference.png",
            dispatch_id="dispatch-001",
            provider="pillow",
        )
    assert summary.read_text(encoding="utf-8") == "tampered\n"


def test_service_rejects_existing_run_after_source_change(tmp_path: Path) -> None:
    """Reject adoption when immutable source evidence no longer has the bound bytes."""

    root = tmp_path / "source_change_job"
    source = root / "input" / "reference.png"
    _write_reference(source)
    run_reference_evidence(
        root,
        job_id="source_change_job",
        run_id="source-bound-run",
        source_image_path="input/reference.png",
        provider="pillow",
    )
    Image.new("RGB", (160, 112), (1, 2, 3)).save(source)

    with pytest.raises(ValueError, match="different exact request"):
        run_reference_evidence(
            root,
            job_id="source_change_job",
            run_id="source-bound-run",
            source_image_path="input/reference.png",
            provider="pillow",
        )
