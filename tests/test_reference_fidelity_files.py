"""Real file/hash contracts over mocked renders; these tests do not claim visual quality."""

from __future__ import annotations

import json

import pytest
from test_reference_fidelity import hypothesis, review
from test_visual_qa_service import _job_fixture, _mock_render

from codex_blender_modeler.qa import service as qa_service
from codex_blender_modeler.reference_fidelity.service import (
    artifact_at,
    capture_render_evidence,
    evaluate_review_file,
    publish,
)
from codex_blender_modeler.reference_fidelity.source_snapshot import validate_build_sources


def file_fixture(tmp_path, monkeypatch, *, object_limit=None):
    """Produce V0.6 files using the canonical request hash, distinct from its file hash."""

    root, target = _job_fixture(tmp_path, monkeypatch)
    if object_limit is not None:
        path = root / "analysis/scene_spec.json"
        scene = json.loads(path.read_text())
        prototype = scene["objects"][0]
        scene["objects"] = [json.loads(json.dumps(prototype)) for _ in range(object_limit)]
        for index, item in enumerate(scene["objects"][1:], start=1):
            item["id"] = f"{target}.fixture{index}"
        path.write_text(json.dumps(scene), encoding="utf-8")
    monkeypatch.setattr(qa_service, "_render_job_qa_passes", _mock_render(root, target))
    qa_service.run_job_visual_qa("asset_qa", run_id="fixture")
    evidence = capture_render_evidence(
        root, qa_run_id="fixture", output_dir=root / "fidelity/evidence"
    )
    plan = hypothesis()
    plan = plan.model_copy(
        update={
            "job_id": "asset_qa",
            "reference": artifact_at(root, root / "input/reference.png"),
            "requirements": [plan.requirements[0].model_copy(update={"target_ids": [target]})],
            "camera": plan.camera.model_copy(
                update={"camera_fingerprint": evidence.camera_fingerprint}
            ),
        }
    )
    plan_artifact = publish(root, root / "fidelity/hypothesis.json", plan)
    rating = review(plan, "defect").model_copy(
        update={
            "hypothesis": plan_artifact,
            "evidence": evidence,
        }
    )
    publish(root, root / "fidelity/review.json", rating)
    return root, evidence


def test_v06_canonical_request_hash_is_not_its_file_hash(tmp_path, monkeypatch) -> None:
    """Consume the existing V0.6 hashing contract without rewriting its request or QA report."""

    root, evidence = file_fixture(tmp_path, monkeypatch)
    before = (root / evidence.qa_report.path).read_bytes()
    assert json.loads(before)["request_sha256"] != evidence.qa_request.sha256
    artifact = evaluate_review_file(
        root, root / "fidelity/review.json", root / "fidelity/eval.json"
    )
    result = json.loads((root / artifact.path).read_bytes())
    assert result["legacy_direct_score"] == 1.0
    assert result["next_action"] == "structural_reentry"
    assert (root / evidence.qa_report.path).read_bytes() == before


def test_old_build_snapshots_survive_new_canonical_source(tmp_path, monkeypatch) -> None:
    """An immutable prior-round source remains readable after a later canonical revision."""

    root, evidence = file_fixture(tmp_path, monkeypatch)
    (root / "analysis/scene_spec.json").write_text("new canonical input", encoding="utf-8")
    validate_build_sources(root, evidence)
    evaluate_review_file(root, root / "fidelity/review.json", root / "fidelity/eval.json")


def test_snapshot_dependency_tampering_is_rejected(tmp_path, monkeypatch) -> None:
    """Rehash the actual snapshot bytes instead of trusting recorded provenance text alone."""

    root, evidence = file_fixture(tmp_path, monkeypatch)
    snapshot = next(iter(evidence.build_sources.files.values()))
    (root / snapshot.path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="evidence changed"):
        validate_build_sources(root, evidence)


def test_snapshot_cannot_omit_a_required_build_source(tmp_path, monkeypatch) -> None:
    """An empty dependency inventory cannot turn absent evidence into a passing source check."""

    root, evidence = file_fixture(tmp_path, monkeypatch)
    changed = evidence.model_copy(
        update={"build_sources": evidence.build_sources.model_copy(update={"files": {}})}
    )
    with pytest.raises(ValueError, match="omits or adds"):
        validate_build_sources(root, changed)


def test_nested_geometry_snapshots_survive_a_replaced_source_path(tmp_path) -> None:
    """A historical mesh dependency closure follows exact snapshots after canonical replacement."""

    from pathlib import Path

    from codex_blender_modeler.blender_artifacts import stable_json_digest
    from codex_blender_modeler.models import SceneSpec
    from codex_blender_modeler.reference_fidelity.service import _geometry_dependencies

    root = tmp_path
    scene_data = json.loads(
        (Path(__file__).parents[1] / "examples/geometry_showcase/scene_spec.seed.json").read_text()
    )
    scene_data["objects"] = [scene_data["objects"][0]]
    scene_data["objects"][0]["geometry"] = {"kind": "custom_mesh", "path": "geometry/outer.json"}
    scene = SceneSpec.model_validate_json(json.dumps(scene_data))
    (root / "geometry").mkdir()
    (root / "geometry/inner.json").write_bytes(b'{"fixture": "mesh-source"}')
    inner = artifact_at(root, root / "geometry/inner.json")
    sources = [inner.model_dump(mode="json")]
    (root / "geometry/outer.json").write_text(
        json.dumps(
            {
                "source_hashes": sources,
                "source_fingerprint_sha256": stable_json_digest(sources),
            }
        )
    )
    original = _geometry_dependencies(root, scene)
    (root / "fidelity").mkdir()
    snapshots = {}
    for index, item in enumerate(original):
        destination = root / "fidelity" / f"source-{index}.json"
        destination.write_bytes((root / item.path).read_bytes())
        snapshots[item.path] = artifact_at(root, destination)
    (root / "geometry/inner.json").write_bytes(b"new canonical geometry")
    (root / "geometry/outer.json").write_bytes(b"new canonical payload")
    assert _geometry_dependencies(root, scene, snapshots) == original
    partial = {key: value for key, value in snapshots.items() if key != "geometry/inner.json"}
    with pytest.raises(ValueError, match="omits a nested"):
        _geometry_dependencies(root, scene, partial)


def test_historical_anchor_audit_never_repairs_changed_bytes(tmp_path) -> None:
    """Explicit historical comparisons report changes without replacing an input or verdict."""

    import runpy
    from pathlib import Path

    auditor = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/audit_reference_fidelity_history.py")
    )["audit_history"]
    evidence = tmp_path / "historical.json"
    evidence.write_bytes(b'{"human_quality_disposition": "accepted"}')
    artifact = artifact_at(tmp_path, evidence)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"schema_version": "0.1.0", "anchors": [artifact.model_dump(mode="json")]})
    )
    assert auditor(tmp_path, manifest)["passed"] is True
    changed = b'{"changed_by_test_fixture": true}'
    evidence.write_bytes(changed)
    assert auditor(tmp_path, manifest)["passed"] is False
    assert evidence.read_bytes() == changed
