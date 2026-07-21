from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from codex_blender_modeler.auto_revision import (
    apply_job_approved_revision,
    approve_job_qa_revision,
    build_revision_candidates,
    compile_job_qa_revision,
)
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.models import (
    BoundingBoxMetric,
    DirectVisualMetrics,
    QAFinding,
    SuggestedEdit,
    VisualQAReport,
)
from codex_blender_modeler.workspace import sha256_file

SHA = "0" * 64


def _metrics(score: float) -> DirectVisualMetrics:
    """Build compact direct-reference metrics for service convergence tests."""

    return DirectVisualMetrics(
        silhouette_iou=score,
        silhouette_union_fraction=0.5,
        global_bbox=BoundingBoxMetric(
            reference_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            rendered_bbox_norm=(0.1, 0.1, 0.9, 0.9),
            center_error_norm=0,
            size_error_norm=0,
        ),
        overall_direct_score=score,
    )


def _report(
    scene_spec_path: Path,
    *,
    run_id: str,
    score: float,
    findings: list[QAFinding] | None = None,
) -> VisualQAReport:
    """Create one fixed-camera visual QA report bound to the fixture SceneSpec."""

    return VisualQAReport(
        job_id="asset_revision",
        run_id=run_id,
        request_sha256=SHA,
        camera_fingerprint=camera_fingerprint(scene_spec_path),
        direct_metrics=_metrics(score),
        findings=findings or [],
        generated_target_status="not_requested",
    )


def _safe_finding() -> QAFinding:
    """Create one directly evidenced, bounded numeric object edit."""

    return QAFinding(
        id="house.raise",
        target_ids=["demo.profile_house"],
        issue_type="position",
        severity="medium",
        description="Raise only the profile house.",
        evidence_sources=["direct_reference"],
        confidence=0.9,
        suggestion=SuggestedEdit(
            target_type="object",
            target_id="demo.profile_house",
            path=["transform", "location", 2],
            op="add",
            value=0.25,
        ),
    )


def _job_fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, str]:
    """Create one job, baseline QA run, and safe candidate bundle without Blender."""

    workspace = tmp_path / "workspaces"
    root = workspace / "asset_revision"
    run_id = "run-baseline"
    run_dir = root / "qa" / "runs" / run_id
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    for path in (
        root / "input",
        root / "analysis",
        root / "history",
        root / "qa",
        run_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    reference = root / "input" / "reference.png"
    reference.write_bytes(b"immutable-reference")
    (root / "job.json").write_text(
        json.dumps(
            {
                "job_id": "asset_revision",
                "mode": "concept",
                "sources": [
                    {
                        "kind": "reference",
                        "path": str(reference),
                        "sha256": sha256_file(reference),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    repository = Path(__file__).resolve().parents[1]
    scene_raw = json.loads(
        (repository / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    scene_raw["job_id"] = "asset_revision"
    scene_spec = root / "analysis" / "scene_spec.json"
    scene_spec.write_text(json.dumps(scene_raw, indent=2), encoding="utf-8")

    report = _report(
        scene_spec,
        run_id=run_id,
        score=0.7,
        findings=[_safe_finding()],
    )
    report_path = run_dir / "visual_qa_report.json"
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    candidates = build_revision_candidates(
        report,
        report_path=report_path,
        scene_spec_path=scene_spec,
    )
    (run_dir / "revision_candidates.json").write_text(
        candidates.model_dump_json(indent=2), encoding="utf-8"
    )
    latest = {
        "job_id": "asset_revision",
        "run_id": run_id,
        "visual_qa_report": f"qa/runs/{run_id}/visual_qa_report.json",
    }
    (root / "qa" / "latest.json").write_text(
        json.dumps(latest, indent=2), encoding="utf-8"
    )
    return root, scene_spec, run_id


def _compile_and_approve(run_id: str) -> None:
    """Compile and explicitly approve the fixture's single safe candidate."""

    compile_job_qa_revision(
        "asset_revision",
        run_id,
        selected_candidate_ids=["candidate.house.raise"],
        request="Raise only the profile house.",
    )
    approve_job_qa_revision(
        "asset_revision",
        run_id,
        approved_candidate_ids=["candidate.house.raise"],
    )


def _post_qa(root: Path, scene_spec: Path, score: float):
    """Return a mock post-QA runner that persists one fixed-camera report and latest pointer."""

    def run(job_id: str, render_engine: str, render_device: str) -> dict[str, Any]:
        """Persist one deterministic post-apply report without invoking Blender."""

        assert job_id == "asset_revision"
        assert render_engine == "eevee"
        assert render_device == "auto"
        run_id = "run-post"
        run_dir = root / "qa" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        report = _report(scene_spec, run_id=run_id, score=score)
        report_path = run_dir / "visual_qa_report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        (root / "qa" / "latest.json").write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "run_id": run_id,
                    "visual_qa_report": f"qa/runs/{run_id}/visual_qa_report.json",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "job_id": job_id,
            "run_id": run_id,
            "visual_qa_report": str(report_path),
            "direct_score": score,
        }

    return run


def _pipeline_recorder(scene_spec: Path, failures: list[int] | None = None):
    """Return a mocked full pipeline and a list of observed canonical house heights."""

    heights: list[float] = []
    queued_failures = list(failures or [0])

    def run(
        job_id: str,
        root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Record the current canonical value and return successful derived-stage reports."""

        assert job_id == "asset_revision"
        raw = json.loads(scene_spec.read_text(encoding="utf-8"))
        house = next(item for item in raw["objects"] if item["id"] == "demo.profile_house")
        heights.append(float(house["transform"]["location"][2]))
        failure_count = queued_failures.pop(0) if queued_failures else 0
        constraint_results = (
            [
                {
                    "id": "constraint.primary",
                    "kind": "dimension",
                    "status": "failed",
                    "requested": 1.0,
                    "actual": 1.2,
                    "residual_m": 0.2,
                    "tolerance_m": 0.1,
                    "message": "mock failure",
                }
            ]
            if failure_count
            else []
        )
        return {
            "build": {"blend": str(root / "blender" / "scene.blend")},
            "preview": {"preview": str(root / "renders" / "preview.png")},
            "inventory_path": str(root / "reports" / "scene_inventory.json"),
            "object_count": len(raw["objects"]),
            "validation": {"ok": True, "errors": [], "warnings": []},
            "validation_path": str(root / "reports" / "validation.json"),
            "constraint_solution_path": None,
            "constraint_failures": failure_count,
            "constraint_results": constraint_results,
        }

    return run, heights


def test_compile_does_not_fabricate_approval(tmp_path: Path, monkeypatch) -> None:
    """Plan compilation persists an unapproved plan and never creates approval implicitly."""

    root, _scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    result = compile_job_qa_revision(
        "asset_revision",
        run_id,
        selected_candidate_ids=["candidate.house.raise"],
        request="Raise only the profile house.",
    )
    run_dir = root / "qa" / "runs" / run_id
    assert result["status"] == "compiled_unapproved"
    assert (run_dir / "revision_plan.json").is_file()
    assert not (run_dir / "revision_approval.json").exists()
    with pytest.raises(FileNotFoundError, match="revision_approval"):
        apply_job_approved_revision("asset_revision", run_id)


def test_explicit_approval_and_improved_apply_are_accepted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """One explicit approval replaces canonical once when direct QA improves."""

    from codex_blender_modeler.auto_revision import service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    input_hash = sha256_file(root / "input" / "reference.png")
    _compile_and_approve(run_id)
    pipeline, heights = _pipeline_recorder(scene_spec)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_post_visual_qa", _post_qa(root, scene_spec, 0.8))

    result = apply_job_approved_revision("asset_revision", run_id)

    assert result["status"] == "accepted"
    assert sha256_file(scene_spec) != before_hash
    assert sha256_file(root / "input" / "reference.png") == input_hash
    assert len(heights) == 1
    approval = json.loads(
        (root / "qa" / "runs" / run_id / "revision_approval.json").read_text(
            encoding="utf-8"
        )
    )
    assert approval["used"] is True
    assert list((root / "history").glob("*_scene_spec.json"))
    convergence = json.loads(Path(result["convergence_report"]).read_text(encoding="utf-8"))
    assert convergence["accepted"] is True


def test_non_improving_apply_restores_canonical_and_rebuilds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A lower direct score restores the archived SceneSpec and rebuilds exactly once."""

    from codex_blender_modeler.auto_revision import service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    latest_before = (root / "qa" / "latest.json").read_bytes()
    _compile_and_approve(run_id)
    pipeline, heights = _pipeline_recorder(scene_spec, failures=[0, 0])
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_post_visual_qa", _post_qa(root, scene_spec, 0.6))

    result = apply_job_approved_revision("asset_revision", run_id)

    assert result["status"] == "rolled_back"
    assert sha256_file(scene_spec) == before_hash
    assert len(heights) == 2
    assert heights[0] == pytest.approx(heights[1] + 0.25)
    assert (root / "qa" / "latest.json").read_bytes() == latest_before
    rollback = json.loads(Path(result["rollback_report"]).read_text(encoding="utf-8"))
    assert rollback["rollback_ok"] is True
    assert rollback["status"] == "restored"


def test_constraint_regression_rolls_back_even_when_visual_score_improves(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A new failed constraint ID overrides a higher direct visual score."""

    from codex_blender_modeler.auto_revision import service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _compile_and_approve(run_id)
    pipeline, _heights = _pipeline_recorder(scene_spec, failures=[1, 0])
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    monkeypatch.setattr(service, "_run_post_visual_qa", _post_qa(root, scene_spec, 0.8))

    result = apply_job_approved_revision("asset_revision", run_id)

    assert result["status"] == "rolled_back"
    assert sha256_file(scene_spec) == before_hash
    convergence = json.loads(Path(result["convergence_report"]).read_text(encoding="utf-8"))
    assert convergence["status"] == "regressed"
    assert convergence["after_failed_constraints"] == 1
    assert convergence["constraint_regressions"][0]["constraint_id"] == (
        "constraint.primary"
    )


def test_pipeline_error_restores_and_rebuilds_before_raising(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A post-apply pipeline error restores canonical state before surfacing failure."""

    from codex_blender_modeler.auto_revision import service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _compile_and_approve(run_id)
    calls = 0

    def fail_then_rebuild(
        job_id: str,
        job_root: Path,
        render_engine: str,
        render_device: str,
    ) -> dict[str, Any]:
        """Fail the revised build once, then accept the restored-baseline rebuild."""

        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("mock revised build failure")
        return {
            "build": {"blend": str(job_root / "blender" / "scene.blend")},
            "preview": {"preview": str(job_root / "renders" / "preview.png")},
            "inventory_path": str(job_root / "reports" / "scene_inventory.json"),
            "object_count": 1,
            "validation": {"ok": True, "errors": [], "warnings": []},
            "validation_path": str(job_root / "reports" / "validation.json"),
            "constraint_solution_path": None,
            "constraint_failures": 0,
            "constraint_results": [],
        }

    monkeypatch.setattr(service, "_run_job_pipeline", fail_then_rebuild)
    with pytest.raises(RuntimeError, match="failed verification and was rolled back"):
        apply_job_approved_revision("asset_revision", run_id)

    assert calls == 2
    assert sha256_file(scene_spec) == before_hash
    application = json.loads(
        (root / "qa" / "runs" / run_id / "application_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert application["status"] == "rolled_back_after_error"
    rollback = json.loads(
        (root / "qa" / "runs" / run_id / "rollback_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert rollback["rollback_ok"] is True


def test_application_report_error_after_replace_restores_canonical(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An exception immediately after canonical replacement restores and rebuilds baseline."""

    from codex_blender_modeler.auto_revision import service

    root, scene_spec, run_id = _job_fixture(tmp_path, monkeypatch)
    before_hash = sha256_file(scene_spec)
    _compile_and_approve(run_id)
    pipeline, heights = _pipeline_recorder(scene_spec)
    monkeypatch.setattr(service, "_run_job_pipeline", pipeline)
    original_write = service.write_json_atomic
    failed_once = False

    def fail_applied_report(path: Path, payload: dict[str, Any]) -> None:
        """Fail the first post-replacement application report write only."""

        nonlocal failed_once
        if (
            not failed_once
            and path.name == "application_report.json"
            and payload.get("status") == "applied_pending_qa"
        ):
            failed_once = True
            raise OSError("mock application report failure")
        original_write(path, payload)

    monkeypatch.setattr(service, "write_json_atomic", fail_applied_report)
    with pytest.raises(RuntimeError, match="failed verification and was rolled back"):
        apply_job_approved_revision("asset_revision", run_id)

    assert failed_once is True
    assert sha256_file(scene_spec) == before_hash
    assert len(heights) == 1
    rollback = json.loads(
        (root / "qa" / "runs" / run_id / "rollback_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert rollback["rollback_ok"] is True
    assert rollback["rebuild_requested"] is True
