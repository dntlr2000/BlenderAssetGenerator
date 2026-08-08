from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from codex_blender_modeler.auto_revision.candidate_review_reporting import (
    generate_candidate_review_pdf,
)
from codex_blender_modeler.auto_revision.candidate_review_service import (
    _validate_candidate_invariants,
    _validate_review_plan,
    approve_candidate_review,
    evaluate_candidate_review,
    get_candidate_review_status,
    promote_candidate_review,
)
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.models import (
    REQUIRED_QA_PASS_KINDS,
    BoundingBoxMetric,
    DirectVisualMetrics,
    RenderPassManifest,
    RenderPassRecord,
    VisualQAReport,
    VisualQARequest,
)
from codex_blender_modeler.revision import RevisionOperation, RevisionPlan
from codex_blender_modeler.workspace import (
    canonical_scene_spec_write_lock,
    create_job,
    sha256_file,
)


def _scene(tmp_path: Path) -> tuple[Path, SceneSpec]:
    """Copy one expressive valid SceneSpec for candidate-policy unit tests."""

    source = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "geometry_showcase"
        / "scene_spec.seed.json"
    )
    path = tmp_path / "scene_spec.json"
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return path, SceneSpec.model_validate_json(path.read_text(encoding="utf-8"))


def _plan(path: Path, operation: RevisionOperation) -> RevisionPlan:
    """Build one exact RevisionPlan around a selected operation."""

    return RevisionPlan(
        job_id="geometry_showcase",
        base_spec_sha256=sha256_file(path),
        request="Evaluate the bounded candidate before canonical promotion.",
        operations=[operation],
        acceptance_criteria=["Direct evidence improves without regression."],
    )


def test_candidate_review_accepts_bounded_existing_object_parameter(tmp_path: Path) -> None:
    """Permit an existing-object transform change inside the isolated review envelope."""

    path, scene = _scene(tmp_path)
    plan = _plan(
        path,
        RevisionOperation(
            op="add",
            target_type="object",
            target_id="demo.profile_house",
            path=["transform", "location", 2],
            value=0.1,
            reason="Raise the observed house roofline slightly.",
        ),
    )

    _validate_review_plan(plan, scene)


@pytest.mark.parametrize(
    "operation",
    [
        RevisionOperation(
            op="add",
            target_type="camera",
            path=["location", 2],
            value=0.1,
            reason="Camera edits require the manual path.",
        ),
        RevisionOperation(
            op="set",
            target_type="object",
            target_id="demo.custom_pyramid",
            path=["geometry", "vertices", 0, 2],
            value=2.0,
            reason="Custom mesh vertices require redesign review.",
        ),
    ],
)
def test_candidate_review_rejects_unbounded_revision_operations(
    tmp_path: Path,
    operation: RevisionOperation,
) -> None:
    """Keep camera and custom-mesh redesign outside the no-preapproval envelope."""

    path, scene = _scene(tmp_path)

    with pytest.raises(ValueError, match="candidate_review"):
        _validate_review_plan(_plan(path, operation), scene)


def test_candidate_review_invariants_lock_camera_materials_and_membership(
    tmp_path: Path,
) -> None:
    """Reject a candidate whose camera or semantic membership differs from baseline."""

    _path, baseline = _scene(tmp_path)
    changed = baseline.model_copy(deep=True)
    changed.camera.location = (
        changed.camera.location[0] + 1.0,
        changed.camera.location[1],
        changed.camera.location[2],
    )
    with pytest.raises(ValueError, match="comparison camera"):
        _validate_candidate_invariants(baseline, changed)

    changed = baseline.model_copy(deep=True)
    changed.objects.pop()
    with pytest.raises(ValueError, match="semantic objects"):
        _validate_candidate_invariants(baseline, changed)


def _fake_candidate_build(
    _root: Path,
    _scene_spec_path: Path,
    output_root: Path,
) -> tuple[Path, Path, Path]:
    """Create deterministic non-Blender build evidence for service orchestration tests."""

    output_root.mkdir(parents=True, exist_ok=False)
    blend = output_root / "scene.blend"
    inventory = output_root / "scene_inventory.json"
    validation = output_root / "validation.json"
    blend.write_bytes(b"candidate-review-blend")
    inventory.write_text('{"families": [], "objects": []}\n', encoding="utf-8")
    validation.write_text('{"ok": true}\n', encoding="utf-8")
    return blend, inventory, validation


def _fake_candidate_qa(
    job_id: str,
    *,
    scene_spec_path: Path,
    blend_path: Path,
    run_dir: Path,
    run_id: str,
    render_engine: str = "eevee",
    render_device: str = "auto",
) -> dict[str, object]:
    """Write exact seven-pass and direct-score fixtures without launching Blender."""

    del blend_path, render_engine, render_device
    root = next(parent for parent in scene_spec_path.parents if parent.name == job_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    pass_dir = run_dir / "passes"
    pass_dir.mkdir()
    records: list[RenderPassRecord] = []
    for kind in REQUIRED_QA_PASS_KINDS:
        path = pass_dir / f"{kind}.png"
        Image.new("RGB", (64, 64), (40, 80, 120)).save(path)
        records.append(
            RenderPassRecord(
                kind=kind,
                path=f"passes/{kind}.png",
                sha256=sha256_file(path),
                width=64,
                height=64,
                encoding="fixture",
            )
        )
    spec = SceneSpec.model_validate_json(scene_spec_path.read_text(encoding="utf-8"))
    provenance = collect_build_provenance(root, job_id, scene_spec_path=scene_spec_path)
    manifest = RenderPassManifest(
        job_id=job_id,
        run_id=run_id,
        scene_spec_sha256=sha256_file(scene_spec_path),
        camera_fingerprint=camera_fingerprint(spec),
        build_fingerprint=str(provenance["fingerprint"]),
        blender_version="fixture",
        render_engine="fixture",
        render_device="cpu",
        resolution=(64, 64),
        passes=records,
    )
    manifest_path = run_dir / "render_pass_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    reference_path = root / "input" / "reference.png"
    reference_mask_path = run_dir / "reference_mask.png"
    reference_mask_path.write_bytes(b"candidate-review-mask")
    request = VisualQARequest(
        job_id=job_id,
        run_id=run_id,
        mode=spec.mode,
        reference_path=str(reference_path.resolve()),
        reference_sha256=sha256_file(reference_path),
        reference_mask_path=str(reference_mask_path.resolve()),
        reference_mask_sha256=sha256_file(reference_mask_path),
        preview_path=str((pass_dir / "beauty.png").resolve()),
        preview_sha256=sha256_file(pass_dir / "beauty.png"),
        render_pass_manifest_path=str(manifest_path.resolve()),
        render_pass_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=sha256_file(scene_spec_path),
        camera_fingerprint=camera_fingerprint(spec),
    )
    request_path = run_dir / "request.json"
    request_path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    score = 0.8 if scene_spec_path.parent.name == "candidate" else 0.7
    metrics = DirectVisualMetrics(
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
    report = VisualQAReport(
        job_id=job_id,
        run_id=run_id,
        request_sha256=sha256_file(request_path),
        camera_fingerprint=camera_fingerprint(spec),
        direct_metrics=metrics,
        generated_target_status="not_requested",
    )
    report_path = run_dir / "visual_qa_report.json"
    report_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return {
        "visual_qa_report": str(report_path),
        "render_pass_manifest": str(manifest_path),
        "request": str(request_path),
    }


def test_candidate_review_evaluates_then_promotes_only_after_exact_approval(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep canonical geometry unchanged until one exact decision approval is consumed."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    Image.new("RGB", (32, 32), (120, 130, 140)).save(reference)
    create_job("candidate_service_asset", reference, "concept", [])
    root = workspace / "candidate_service_asset"
    source = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "geometry_showcase"
        / "scene_spec.seed.json"
    )
    payload = SceneSpec.model_validate_json(source.read_text(encoding="utf-8")).model_dump(
        mode="json"
    )
    payload["job_id"] = "candidate_service_asset"
    canonical = root / "analysis" / "scene_spec.json"
    canonical.write_text(
        SceneSpec.model_validate(payload).model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    baseline_hash = sha256_file(canonical)
    plan_root = root / "workflows" / "wf-candidate" / "artifacts" / "r"
    plan_root.mkdir(parents=True)
    plan_path = plan_root / "revision_plan.json"
    plan = RevisionPlan(
        job_id="candidate_service_asset",
        base_spec_sha256=baseline_hash,
        request="Raise the profile house after isolated comparison.",
        operations=[
            RevisionOperation(
                op="add",
                target_type="object",
                target_id="demo.profile_house",
                path=["transform", "location", 2],
                value=0.2,
                reason="Improve direct reference placement.",
            )
        ],
        acceptance_criteria=["Direct score improves without regression."],
    )
    plan_path.write_text(plan.model_dump_json(indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "codex_blender_modeler.auto_revision.candidate_review_service._build_candidate_scene",
        _fake_candidate_build,
    )
    monkeypatch.setattr(
        "codex_blender_modeler.auto_revision.candidate_review_service.run_scene_spec_visual_qa_snapshot",
        _fake_candidate_qa,
    )

    decision = evaluate_candidate_review(
        "candidate_service_asset",
        trial_id="trial-01",
        revision_plan_path=plan_path,
        input_fingerprint="c" * 64,
        workflow_id="wf-candidate",
    )
    decision_path = root / "qa" / "candidate_reviews" / "trial-01" / "decision_manifest.json"
    assert decision.promotable is True
    assert sha256_file(canonical) == baseline_hash
    report_result = generate_candidate_review_pdf("candidate_service_asset", "trial-01")
    assert Path(report_result["pdf"]).is_file()
    assert Path(report_result["manifest"]).is_file()
    status = get_candidate_review_status("candidate_service_asset", "trial-01")
    assert status["review_pdf_manifest_valid"] is True

    approval = approve_candidate_review(
        "candidate_service_asset",
        "trial-01",
        decision_sha256=sha256_file(decision_path),
        approval_note="Approve the measured improvement only.",
    )
    assert approval.used is False

    def fake_rebuild(
        rebuild_root: Path,
        _job_id: str,
    ) -> tuple[Path, Path, Path]:
        """Create canonical derived artifacts after the test promotion."""

        blend = rebuild_root / "blender" / "scene.blend"
        inventory = rebuild_root / "reports" / "scene_inventory.json"
        validation = rebuild_root / "reports" / "validation.json"
        blend.parent.mkdir(parents=True, exist_ok=True)
        inventory.parent.mkdir(parents=True, exist_ok=True)
        blend.write_bytes(b"promoted-blend")
        inventory.write_text('{"families": [], "objects": []}\n', encoding="utf-8")
        validation.write_text('{"ok": true}\n', encoding="utf-8")
        return blend, inventory, validation

    monkeypatch.setattr(
        "codex_blender_modeler.auto_revision.candidate_review_service._rebuild_canonical",
        fake_rebuild,
    )
    with canonical_scene_spec_write_lock("candidate_service_asset", "wf-candidate"):
        receipt = promote_candidate_review(
            "candidate_service_asset",
            "trial-01",
            workflow_id="wf-candidate",
        )

    assert receipt.status == "promoted"
    assert sha256_file(canonical) == decision.candidate_scene_spec.sha256
    approval_payload = root / "qa" / "candidate_reviews" / "trial-01" / "promotion_approval.json"
    assert '"used": true' in approval_payload.read_text(encoding="utf-8")
