"""Explicit existing V0.2 trimap selection without invented alpha or changed legacy plans."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_qa_evidence_selection import _contracts, _job, _plan

from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.orchestration import service as workflow
from codex_blender_modeler.qa import service as native
from codex_blender_modeler.qa.evidence_selection import load_reference_mask_selection
from codex_blender_modeler.reference_fidelity.models import ReferenceMaskSeedEvidenceV02
from codex_blender_modeler.reference_fidelity.service import artifact_at


def _v02_job(tmp_path, monkeypatch):
    """Use complete observed subject bounds and an exact source-only V0.2 trimap."""
    fix = _job(tmp_path, monkeypatch)
    raw = fix.scene.model_dump(mode="json")
    for obj in raw["objects"]:
        obj["evidence"][0].update(status="observed", bbox_norm=[0.1, 0.1, 0.9, 0.9])
    fix.scene = SceneSpec.model_validate(raw)
    fix.scene_path.write_text(fix.scene.model_dump_json())
    raw = fix.seed.model_dump(mode="json")
    raw.pop("subject_extent")
    raw["schema_version"] = "0.2.0"
    fix.seed = ReferenceMaskSeedEvidenceV02.model_validate_json(json.dumps(raw))
    fix.path.write_text(fix.seed.model_dump_json(indent=2) + "\n")
    fix.artifact = artifact_at(fix.root, fix.path)
    return fix


def test_v02_public_qa_preserves_source_and_publishes_only_existing_contract(tmp_path, monkeypatch):
    """No alpha companion is fabricated when the existing trimap contract is explicit."""
    fix = _v02_job(tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in (fix.reference, fix.path, fix.scene_path, fix.source)}
    result = native.run_job_visual_qa(
        "asset_qa", run_id="v02-public",
        reference_mask_seed_path=fix.artifact.path,
        reference_mask_seed_sha256=fix.artifact.sha256,
    )
    run = Path(result["run_dir"])
    assert (run / "reference_mask_seed_evidence.json").read_bytes() == before[fix.path]
    assert (run / "reference_trimap.png").is_file()
    assert not (run / "reference_subject_extent.json").exists()
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_v02_standard_plan_records_version_and_no_extent_output(tmp_path, monkeypatch):
    """A fresh host plan has an exact V0.2 discriminator and only valid native outputs."""
    fix = _v02_job(tmp_path, monkeypatch)
    state = _plan(fix)
    request, plan, _ = _contracts(fix, state)
    step = next(s for s in plan.steps if s.step_id == "qa.run")
    assert step.parameters["reference_mask_seed_version"] == "0.2.0"
    assert {x.artifact_id for x in step.outputs} >= {"qa.run.seed_evidence", "qa.run.trimap"}
    assert "qa.run.subject_extent" not in {x.artifact_id for x in step.outputs}
    assert workflow._validate_qa_mask_selection(fix.root, request, step) == fix.artifact
    step.parameters["reference_mask_seed_version"] = "0.3.0"
    with pytest.raises(ValueError, match="version differs"):
        workflow._validate_qa_mask_selection(fix.root, request, step)


@pytest.mark.parametrize("mutation", ["reference_hash", "source_path", "scope", "duplicate"])
def test_v02_requires_actual_recorded_immutable_source(tmp_path, monkeypatch, mutation):
    """Public V0.2 evidence cannot relabel a render or bypass the original metadata hash."""
    fix = _v02_job(tmp_path, monkeypatch)
    path = fix.root / "job.json"
    metadata = json.loads(path.read_text())
    if mutation == "reference_hash":
        metadata["reference_sha256"] = "f" * 64
    elif mutation == "source_path":
        target = fix.root / "renders/preview.png"
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(fix.reference.read_bytes())
        metadata["sources"][0]["path"] = "renders/preview.png"
    elif mutation == "scope":
        metadata["reference_content_scope"] = "full_reference"
    else:
        metadata["sources"].append(dict(metadata["sources"][0]))
    path.write_text(json.dumps(metadata))
    expected_error = FileNotFoundError if mutation == "source_path" else ValueError
    with pytest.raises(expected_error):
        load_reference_mask_selection(
            fix.root, fix.reference, fix.scene, "primary_object_only", fix.artifact
        )


@pytest.mark.parametrize("version", [None, "0.1.0", "0.4.0"])
def test_public_selection_requires_known_explicit_version(tmp_path, monkeypatch, version):
    """Unknown or omitted discriminators never select a version by shape or filename."""
    fix = _v02_job(tmp_path, monkeypatch)
    raw = json.loads(fix.path.read_text())
    if version is None:
        raw.pop("schema_version")
    else:
        raw["schema_version"] = version
    fix.path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="explicit V0.2 or V0.3"):
        load_reference_mask_selection(
            fix.root, fix.reference, fix.scene, "primary_object_only",
            artifact_at(fix.root, fix.path),
        )


def test_v02_does_not_bypass_partial_subject_clipping_guard(tmp_path, monkeypatch):
    """Only a validated V0.3 whole-subject extent can resolve incomplete observed bounds."""
    fix = _job(tmp_path, monkeypatch)
    raw = fix.seed.model_dump(mode="json")
    raw.pop("subject_extent")
    raw["schema_version"] = "0.2.0"
    fix.path.write_text(ReferenceMaskSeedEvidenceV02.model_validate_json(json.dumps(raw)).model_dump_json())
    selected = artifact_at(fix.root, fix.path)
    with pytest.raises(ValueError):
        native.run_job_visual_qa(
            "asset_qa", run_id="v02-no-fallback",
            reference_mask_seed_path=selected.path,
            reference_mask_seed_sha256=selected.sha256,
        )
    assert not (fix.root / "qa/runs/v02-no-fallback/visual_qa_report.json").exists()
