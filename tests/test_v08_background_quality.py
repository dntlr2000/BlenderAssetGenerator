from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

import codex_blender_modeler.background_quality.fit as fit_service
import codex_blender_modeler.background_quality.quality as quality_service
from codex_blender_modeler.background_quality import (
    BackgroundFitReport,
    BackgroundQualityReport,
    BackgroundRoleMap,
    run_background_pre_qa_fit,
)
from codex_blender_modeler.background_quality.models import (
    BackgroundFitAttempt,
    BackgroundFitMetrics,
    BackgroundRoleAssignment,
    BackgroundScenePromotionReceipt,
)
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa.hashing import canonical_model_sha256
from codex_blender_modeler.qa.models import (
    DirectVisualMetrics,
    QAFinding,
    RenderPassManifest,
    RenderPassRecord,
    VisualQAReport,
    VisualQARequest,
)
from codex_blender_modeler.workspace import sha256_file

ROOT = Path(__file__).resolve().parents[1]
PASS_KINDS = (
    "beauty",
    "silhouette",
    "object_id",
    "material_id",
    "normal",
    "depth",
    "wireframe",
)


def _scene_payload(job_id: str) -> dict:
    """Create one valid role-tagged SceneSpec fixture from an existing geometry recipe."""

    seed = json.loads(
        (ROOT / "examples" / "geometry_showcase" / "scene_spec.seed.json").read_text(
            encoding="utf-8"
        )
    )
    seed["job_id"] = job_id
    base = deepcopy(seed["objects"][0])
    definitions = (
        (
            "vehicle.body",
            ["qa_role:primary"],
            [0.25, 0.25, 0.75, 0.75],
        ),
        (
            "vehicle.wheel.front",
            ["qa_role:supporting"],
            [0.2, 0.55, 0.35, 0.75],
        ),
        (
            "environment.rocks",
            ["qa_role:decorative"],
            [0.05, 0.7, 0.2, 0.9],
        ),
        (
            "environment.seabed",
            ["qa_role:ground_background"],
            [0.0, 0.7, 1.0, 1.0],
        ),
    )
    objects = []
    for index, (identifier, tags, bbox) in enumerate(definitions):
        item = deepcopy(base)
        item["id"] = identifier
        item["name"] = identifier
        item["tags"] = tags
        item["transform"]["location"] = [float(index * 3), 0.0, 0.0]
        item["evidence"] = [
            {
                "source_id": "ref.main",
                "bbox_norm": bbox,
                "status": "observed",
                "confidence": 0.9,
            }
        ]
        objects.append(item)
    seed["objects"] = objects
    seed["materials"] = [
        item for item in seed["materials"] if item["id"] == base["material_id"]
    ]
    return SceneSpec.model_validate(seed).model_dump(mode="json")


def _mask(path: Path, box: tuple[int, int, int, int] | None) -> Path:
    """Write one deterministic binary image-space mask."""

    image = Image.new("L", (32, 32), 0)
    if box is not None:
        ImageDraw.Draw(image).rectangle(box, fill=255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _object_id_pass(
    path: Path,
    *,
    primary_box: tuple[int, int, int, int] | None,
) -> Path:
    """Write one exact-color semantic pass with role-separated fixture regions."""

    image = Image.new("RGB", (32, 32), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    if primary_box is not None:
        draw.rectangle(primary_box, fill=(255, 0, 0))
    draw.rectangle((6, 18, 10, 24), fill=(0, 0, 255))
    draw.rectangle((1, 23, 5, 28), fill=(0, 255, 0))
    draw.rectangle((0, 28, 31, 31), fill=(255, 255, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _quality_fixture(
    tmp_path: Path,
    *,
    primary_box: tuple[int, int, int, int] | None,
    findings: list[QAFinding],
) -> tuple[Path, str, Path, Path, Path]:
    """Write exact V0.6 and workflow-owned evidence for one quality classification."""

    job_id = "background_quality_fixture"
    root = tmp_path / job_id
    (root / "analysis").mkdir(parents=True)
    (root / "blender").mkdir()
    (root / "input").mkdir()
    (root / "workflows" / "wf-quality" / "artifacts" / "g" / "fit").mkdir(
        parents=True
    )
    scene_path = root / "analysis" / "scene_spec.json"
    scene_path.write_text(
        json.dumps(_scene_payload(job_id), indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "blender" / "scene.blend").write_bytes(b"fixture")
    reference = root / "input" / "reference.png"
    Image.new("RGB", (32, 32), (90, 120, 150)).save(reference)
    run_id = "v08-quality-fixture"
    run_root = root / "qa" / "runs" / run_id
    passes_root = run_root / "passes"
    passes_root.mkdir(parents=True)
    reference_mask = _mask(run_root / "reference_mask.png", (8, 8, 23, 23))
    records: list[RenderPassRecord] = []
    for kind in PASS_KINDS:
        path = passes_root / f"{kind}.png"
        if kind == "object_id":
            _object_id_pass(path, primary_box=primary_box)
        elif kind == "silhouette":
            _mask(path, primary_box)
        else:
            Image.new("RGB", (32, 32), (40, 50, 60)).save(path)
        records.append(
            RenderPassRecord(
                kind=kind,  # type: ignore[arg-type]
                path=f"passes/{path.name}",
                sha256=sha256_file(path),
                width=32,
                height=32,
                encoding="png",
            )
        )
    camera_fingerprint = "c" * 64
    build_fingerprint = "b" * 64
    manifest = RenderPassManifest(
        job_id=job_id,
        run_id=run_id,
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=camera_fingerprint,
        build_fingerprint=build_fingerprint,
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="DEFAULT",
        resolution=(32, 32),
        passes=records,
        object_id_colors={
            "vehicle.body": "#ff0000",
            "vehicle.wheel.front": "#0000ff",
            "environment.rocks": "#00ff00",
            "environment.seabed": "#ffff00",
        },
    )
    manifest_path = run_root / "render_pass_manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    request = VisualQARequest(
        job_id=job_id,
        run_id=run_id,
        mode="concept",
        reference_path=str(reference.resolve()),
        reference_sha256=sha256_file(reference),
        reference_mask_path=str(reference_mask.resolve()),
        reference_mask_sha256=sha256_file(reference_mask),
        preview_path=str((passes_root / "beauty.png").resolve()),
        preview_sha256=sha256_file(passes_root / "beauty.png"),
        render_pass_manifest_path=str(manifest_path.resolve()),
        render_pass_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=camera_fingerprint,
        include_generated_target=False,
    )
    request_path = run_root / "request.json"
    request_path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    direct = DirectVisualMetrics(
        silhouette_iou=0.9,
        silhouette_union_fraction=0.5,
        global_bbox={
            "reference_bbox_norm": [0.25, 0.25, 0.75, 0.75],
            "rendered_bbox_norm": [0.25, 0.25, 0.75, 0.75],
            "center_error_norm": 0.0,
            "size_error_norm": 0.0,
        },
        semantic_deviations=[],
        overall_direct_score=0.9,
    )
    report = VisualQAReport(
        job_id=job_id,
        run_id=run_id,
        request_sha256=canonical_model_sha256(request),
        camera_fingerprint=camera_fingerprint,
        direct_metrics=direct,
        findings=findings,
        generated_target_status="not_requested",
    )
    (run_root / "visual_qa_report.json").write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    fit_root = root / "workflows" / "wf-quality" / "artifacts" / "g" / "fit"
    role_map = BackgroundRoleMap(
        job_id=job_id,
        workflow_id="wf-quality",
        scene_spec_sha256=sha256_file(scene_path),
        assignments=[
            BackgroundRoleAssignment(
                object_id="vehicle.body",
                role="primary",
                source="explicit_tag",
                tags=["qa_role:primary"],
                reason="fixture",
            ),
            BackgroundRoleAssignment(
                object_id="vehicle.wheel.front",
                role="supporting",
                source="explicit_tag",
                tags=["qa_role:supporting"],
                reason="fixture",
            ),
            BackgroundRoleAssignment(
                object_id="environment.rocks",
                role="decorative",
                source="explicit_tag",
                tags=["qa_role:decorative"],
                reason="fixture",
            ),
            BackgroundRoleAssignment(
                object_id="environment.seabed",
                role="ground_background",
                source="explicit_tag",
                tags=["qa_role:ground_background"],
                reason="fixture",
            ),
        ],
        generated_at=datetime.now(UTC),
    )
    role_map_path = fit_root / "role_map.json"
    role_map_path.write_text(
        role_map.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    candidate = fit_root / "candidate.json"
    candidate.write_text(scene_path.read_text(encoding="utf-8"), encoding="utf-8")
    receipt = fit_root / "promotion_receipt.json"
    promotion = BackgroundScenePromotionReceipt(
        job_id=job_id,
        workflow_id="wf-quality",
        input_fingerprint="d" * 64,
        initial_candidate_path=candidate.relative_to(root).as_posix(),
        initial_candidate_sha256=sha256_file(candidate),
        selected_candidate_path=candidate.relative_to(root).as_posix(),
        selected_candidate_sha256=sha256_file(candidate),
        selected_attempt_index=0,
        previous_canonical_sha256=sha256_file(scene_path),
        new_canonical_sha256=sha256_file(scene_path),
        canonical_changed=False,
        role_map_path=role_map_path.relative_to(root).as_posix(),
        role_map_sha256=sha256_file(role_map_path),
        promoted_at=datetime.now(UTC),
    )
    receipt.write_text(
        promotion.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    fit_report = BackgroundFitReport(
        job_id=job_id,
        workflow_id="wf-quality",
        status="degraded",
        input_fingerprint="d" * 64,
        max_refinement_attempts=2,
        initial_candidate_sha256=sha256_file(candidate),
        selected_candidate_sha256=sha256_file(candidate),
        selected_attempt_index=0,
        role_map_path=role_map_path.relative_to(root).as_posix(),
        role_map_sha256=sha256_file(role_map_path),
        promotion_receipt_path=receipt.relative_to(root).as_posix(),
        promotion_receipt_sha256=sha256_file(receipt),
        attempts=[
            BackgroundFitAttempt(
                attempt_index=0,
                candidate_path=candidate.relative_to(root).as_posix(),
                candidate_sha256=sha256_file(candidate),
                input_fingerprint="e" * 64,
                metrics=BackgroundFitMetrics(
                    scorable=False,
                    limitations=["fixture"],
                ),
                selected=True,
                outcome="baseline",
                reason="fixture baseline",
            )
        ],
        limitations=["fixture"],
        completed_at=datetime.now(UTC),
    )
    fit_report_path = fit_root / "fit_report.json"
    fit_report_path.write_text(
        fit_report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return root, run_id, role_map_path, fit_report_path, scene_path


def _evaluate(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    run_id: str,
    role_map: Path,
    fit_report: Path,
) -> BackgroundQualityReport:
    """Evaluate one fixture while replacing only embedded Blender provenance lookup."""

    monkeypatch.setattr(
        quality_service,
        "collect_source_provenance",
        lambda *_args, **_kwargs: SimpleNamespace(
            source_fingerprint="a" * 64,
            build_fingerprint="b" * 64,
        ),
    )
    return quality_service.evaluate_background_quality(
        root,
        job_id=root.name,
        workflow_id="wf-quality",
        qa_run_id=run_id,
        role_map_path=role_map,
        fit_report_path=fit_report,
        output_path=root / "reports" / "background_quality.json",
    )


def test_decorative_high_finding_allows_passed_review_delivery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep decorative differences visible without making them primary blockers."""

    finding = QAFinding(
        id="direct.environment.rocks",
        target_ids=["environment.rocks"],
        issue_type="proportion",
        severity="high",
        description="Decorative rocks differ.",
        evidence_sources=["direct_reference"],
        confidence=0.9,
    )
    root, run_id, roles, fit_report, _scene = _quality_fixture(
        tmp_path,
        primary_box=(8, 8, 23, 23),
        findings=[finding],
    )
    report = _evaluate(monkeypatch, root, run_id, roles, fit_report)

    assert report.quality_status == "passed"
    assert report.quality_accepted is True
    assert report.decorative_warnings == [finding.id]
    assert report.standard_workflow_recommended is False


def test_primary_high_finding_delivers_needs_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Deliver complete evidence while preserving primary revision warnings."""

    findings = [
        QAFinding(
            id="direct.vehicle.body",
            target_ids=["vehicle.body"],
            issue_type="proportion",
            severity="high",
            description="Primary body proportions differ.",
            evidence_sources=["direct_reference"],
            confidence=0.95,
        ),
        QAFinding(
            id="direct.environment.rocks",
            target_ids=["environment.rocks"],
            issue_type="proportion",
            severity="high",
            description="Decorative rocks differ.",
            evidence_sources=["direct_reference"],
            confidence=0.9,
        ),
    ]
    root, run_id, roles, fit_report, _scene = _quality_fixture(
        tmp_path,
        primary_box=(0, 8, 11, 23),
        findings=findings,
    )
    report = _evaluate(monkeypatch, root, run_id, roles, fit_report)

    assert report.execution_status == "completed"
    assert report.delivery_status == "ready_for_review"
    assert report.quality_status == "needs_revision"
    assert report.quality_accepted is False
    assert report.standard_workflow_recommended is True
    assert "direct.vehicle.body" in report.primary_high_findings
    assert "quality.primary_silhouette" in report.primary_high_findings
    assert report.decorative_warnings == ["direct.environment.rocks"]


def test_missing_primary_object_id_is_unscorable_delivery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Complete review delivery without claiming quality when primary evidence is absent."""

    root, run_id, roles, fit_report, _scene = _quality_fixture(
        tmp_path,
        primary_box=None,
        findings=[],
    )
    report = _evaluate(monkeypatch, root, run_id, roles, fit_report)

    assert report.quality_status == "unscorable"
    assert report.quality_accepted is False
    assert report.standard_workflow_recommended is True
    assert report.unscorable_evidence


def _fit_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    """Create one isolated workflow candidate and deterministic reference mask."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    root = workspace / "background_fit_fixture"
    for relative in (
        "analysis/masks",
        "history",
        "workflows/wf-fit/artifacts/g",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    payload = _scene_payload(root.name)
    payload["objects"] = [payload["objects"][0]]
    payload["materials"] = [payload["materials"][0]]
    scene = root / "analysis" / "scene_spec.json"
    scene.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    initial = root / "workflows" / "wf-fit" / "artifacts" / "g" / (
        "initial_scene_spec.json"
    )
    initial.write_text(scene.read_text(encoding="utf-8"), encoding="utf-8")
    _mask(root / "analysis" / "masks" / "reference_content.png", (8, 8, 23, 23))
    return root, scene, initial


def test_pre_qa_fit_promotes_only_improved_camera_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Select one improved bounded candidate and preserve semantic/material identities."""

    root, scene, initial = _fit_workspace(monkeypatch, tmp_path)
    baseline = SceneSpec.model_validate_json(scene.read_text(encoding="utf-8"))
    baseline_hash = sha256_file(scene)

    def fake_render(
        _root: Path,
        _candidate: Path,
        _role_map: Path,
        attempt_root: Path,
    ) -> Path:
        """Render a bad baseline and an exact first refinement without Blender."""

        box = (0, 8, 15, 23) if attempt_root.name == "attempt-00" else (8, 8, 23, 23)
        return _mask(attempt_root / "primary_silhouette.png", box)

    monkeypatch.setattr(fit_service, "_render_candidate", fake_render)
    report = run_background_pre_qa_fit(
        root.name,
        workflow_id="wf-fit",
        input_fingerprint="f" * 64,
        initial_candidate_path=initial,
        fit_root=root / "workflows" / "wf-fit" / "artifacts" / "g" / "fit",
        max_attempts=2,
    )
    promoted = SceneSpec.model_validate_json(scene.read_text(encoding="utf-8"))

    assert report.status == "completed"
    assert report.selected_attempt_index == 1
    assert len(report.attempts) == 2
    assert sha256_file(scene) == report.selected_candidate_sha256
    assert sha256_file(scene) != baseline_hash
    assert [item.id for item in promoted.objects] == [item.id for item in baseline.objects]
    assert [item.id for item in promoted.materials] == [
        item.id for item in baseline.materials
    ]
    assert promoted.camera != baseline.camera
    receipt = json.loads(
        (
            root
            / report.promotion_receipt_path
        ).read_text(encoding="utf-8")
    )
    assert receipt["canonical_changed"] is True


def test_pre_qa_fit_retains_baseline_on_non_improvement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep the baseline canonical SceneSpec when bounded diagnostics do not improve."""

    root, scene, initial = _fit_workspace(monkeypatch, tmp_path)
    baseline_hash = sha256_file(scene)

    def fake_render(
        _root: Path,
        _candidate: Path,
        _role_map: Path,
        attempt_root: Path,
    ) -> Path:
        """Return the same poor diagnostic for every bounded candidate."""

        return _mask(attempt_root / "primary_silhouette.png", (0, 8, 15, 23))

    monkeypatch.setattr(fit_service, "_render_candidate", fake_render)
    report = run_background_pre_qa_fit(
        root.name,
        workflow_id="wf-fit",
        input_fingerprint="f" * 64,
        initial_candidate_path=initial,
        fit_root=root / "workflows" / "wf-fit" / "artifacts" / "g" / "fit",
        max_attempts=2,
    )

    assert report.selected_attempt_index == 0
    assert sha256_file(scene) == baseline_hash
    assert report.selected_candidate_sha256 == baseline_hash
    assert not list((root / "history").glob("*_scene_spec.json"))
