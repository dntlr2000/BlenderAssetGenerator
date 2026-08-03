from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from codex_blender_modeler.background_quality.models import BackgroundRoleMap
from codex_blender_modeler.background_quality.roles import derive_background_role_map
from codex_blender_modeler.blender_artifacts import write_json_atomic
from codex_blender_modeler.build_provenance import collect_build_provenance
from codex_blender_modeler.models import SceneSpec
from codex_blender_modeler.qa import diagnostic_service as service
from codex_blender_modeler.qa.camera_attribution import attribute_camera_geometry
from codex_blender_modeler.qa.camera_fingerprint import camera_fingerprint
from codex_blender_modeler.qa.diagnostic_models import (
    BoundedCameraDelta,
    CameraProbeResult,
    CameraProbeSemanticScore,
    QADiagnosticBundleManifest,
    QADiagnosticReport,
    QADiagnosticRequest,
    SemanticReferenceMaskManifest,
    SemanticReferenceMaskRecord,
)
from codex_blender_modeler.qa.hashing import canonical_model_sha256
from codex_blender_modeler.qa.models import (
    REQUIRED_QA_PASS_KINDS,
    BoundingBoxMetric,
    DirectVisualMetrics,
    RenderPassManifest,
    RenderPassRecord,
    VisualQAReport,
    VisualQARequest,
)
from codex_blender_modeler.qa.multiview_sanity import (
    AssemblySanityFinding,
    AssemblySanityReport,
    AssemblySanityViewCoverage,
)
from codex_blender_modeler.workspace import create_job, sha256_file

JOB_ID = "diagnostic_service_test"
QA_RUN_ID = "qa-run-001"


def _scene_spec(*, explicit_qa_role: bool = True) -> SceneSpec:
    """Create one observed primary object for isolated companion diagnostics."""

    return SceneSpec.model_validate(
        {
            "job_id": JOB_ID,
            "mode": "concept",
            "nominal_scene_size": [4.0, 2.0, 2.0],
            "sources": [
                {
                    "id": "reference",
                    "path": "input/reference.png",
                    "kind": "reference",
                }
            ],
            "materials": [
                {
                    "id": "mat.body",
                    "name": "Body",
                    "base_color": [0.5, 0.5, 0.5, 1.0],
                    "roughness": 0.5,
                    "metallic": 0.0,
                }
            ],
            "objects": [
                {
                    "id": "asset.body",
                    "name": "Body",
                    "geometry": {
                        "kind": "primitive",
                        "primitive": "cube",
                        "dimensions": [3.0, 1.0, 1.0],
                    },
                    "material_id": "mat.body",
                    "tags": ["qa_role:primary"] if explicit_qa_role else [],
                    "evidence": [
                        {
                            "source_id": "reference",
                            "bbox_norm": [0.25, 0.25, 0.75, 0.75],
                            "status": "observed",
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
            "camera": {
                "projection": "PERSP",
                "location": [5.0, -8.0, 4.0],
                "target": [0.0, 0.0, 0.0],
                "focal_length_mm": 50.0,
                "ortho_scale": 6.0,
                "resolution": [128, 128],
            },
        }
    )


def _write_image(path: Path, *, object_id: bool = False) -> None:
    """Write one deterministic rectangular QA image fixture."""

    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (128, 128), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((32, 32, 95, 95), fill=(255, 0, 0) if object_id else (255, 255, 255))
    image.save(path)


def _seed_canonical_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    reference_content_scope: str = "full_reference",
    explicit_qa_role: bool = True,
) -> Path:
    """Seed a complete immutable V0.6 run and placeholder authoring blend."""

    workspace = tmp_path / "workspaces"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = tmp_path / "reference.png"
    _write_image(reference)
    create_job(
        JOB_ID,
        reference,
        "concept",
        [],
        reference_content_scope=reference_content_scope,
        target_subject=(
            "test subject" if reference_content_scope == "primary_object_only" else None
        ),
    )
    root = workspace / JOB_ID
    scene_path = root / "analysis" / "scene_spec.json"
    spec = _scene_spec(explicit_qa_role=explicit_qa_role)
    scene_path.write_text(spec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (root / "blender" / "scene.blend").write_bytes(b"immutable authoring blend")
    run_dir = root / "qa" / "runs" / QA_RUN_ID
    passes: list[RenderPassRecord] = []
    for kind in REQUIRED_QA_PASS_KINDS:
        path = run_dir / "passes" / f"{kind}.png"
        _write_image(path, object_id=kind == "object_id")
        passes.append(
            RenderPassRecord(
                kind=kind,
                path=f"passes/{kind}.png",
                sha256=sha256_file(path),
                width=128,
                height=128,
                encoding="png-rgb8",
            )
        )
    camera_sha = camera_fingerprint(spec)
    build_sha = str(collect_build_provenance(root, JOB_ID)["fingerprint"])
    manifest = RenderPassManifest(
        job_id=JOB_ID,
        run_id=QA_RUN_ID,
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=camera_sha,
        build_fingerprint=build_sha,
        blender_version="5.0.1",
        render_engine="BLENDER_EEVEE",
        render_device="CPU",
        resolution=(128, 128),
        passes=passes,
        object_id_colors={"asset.body": "#ff0000"},
    )
    manifest_path = run_dir / "render_pass_manifest.json"
    write_json_atomic(manifest_path, manifest.model_dump(mode="json"))
    reference_mask_path = run_dir / "reference_mask.png"
    _write_image(reference_mask_path)
    write_json_atomic(
        run_dir / "reference_mask_manifest.json",
        {
            "schema_version": "0.6.0",
            "reference_sha256": sha256_file(root / "input" / "reference.png"),
            "output_path": "reference_mask.png",
            "output_sha256": sha256_file(reference_mask_path),
        },
    )
    request = VisualQARequest(
        job_id=JOB_ID,
        run_id=QA_RUN_ID,
        mode="concept",
        reference_path=str((root / "input" / "reference.png").resolve()),
        reference_sha256=sha256_file(root / "input" / "reference.png"),
        reference_mask_path=str(reference_mask_path.resolve()),
        reference_mask_sha256=sha256_file(reference_mask_path),
        preview_path=str((run_dir / "passes" / "beauty.png").resolve()),
        preview_sha256=sha256_file(run_dir / "passes" / "beauty.png"),
        render_pass_manifest_path=str(manifest_path.resolve()),
        render_pass_manifest_sha256=sha256_file(manifest_path),
        scene_spec_sha256=sha256_file(scene_path),
        camera_fingerprint=camera_sha,
    )
    request_path = run_dir / "request.json"
    write_json_atomic(request_path, request.model_dump(mode="json"))
    report = VisualQAReport(
        job_id=JOB_ID,
        run_id=QA_RUN_ID,
        request_sha256=canonical_model_sha256(request),
        camera_fingerprint=camera_sha,
        direct_metrics=DirectVisualMetrics(
            silhouette_iou=0.5,
            silhouette_union_fraction=0.5,
            global_bbox=BoundingBoxMetric(
                reference_bbox_norm=(0.25, 0.25, 0.75, 0.75),
                rendered_bbox_norm=(0.3, 0.25, 0.8, 0.75),
                center_error_norm=0.05,
                size_error_norm=0.0,
            ),
            overall_direct_score=0.5,
        ),
        generated_target_status="not_requested",
    )
    write_json_atomic(run_dir / "visual_qa_report.json", report.model_dump(mode="json"))
    return root


def _fake_camera_probes(
    root: Path,
    *,
    job_id: str,
    qa_run_id: str,
    diagnostic_id: str,
    artifact_root: Path,
    scene_spec_path: Path,
    **_kwargs: object,
) -> tuple[list[CameraProbeResult], Path, Path]:
    """Create exact bounded-probe evidence without invoking Blender in unit tests."""

    role_map = derive_background_role_map(
        scene_spec_path,
        job_id=job_id,
        workflow_id=f"qa-diagnostic-{diagnostic_id}",
    )
    role_map_path = artifact_root / "role_map.json"
    write_json_atomic(role_map_path, role_map.model_dump(mode="json"))
    role_map_sha256 = sha256_file(role_map_path)
    plan_path = artifact_root / "camera_probes" / "plan.json"
    manifest_path = artifact_root / "camera_probes" / "render_manifest.json"
    probe_specs = [
        ("baseline", BoundedCameraDelta()),
        (
            "yaw-positive",
            BoundedCameraDelta(rotation_delta_deg=(7.5, 0.0, 0.0)),
        ),
    ]
    supplied_masks = _kwargs.get("semantic_reference_masks")
    semantic_reference_masks = []
    if isinstance(supplied_masks, dict):
        semantic_reference_masks = [
            {
                "semantic_id": semantic_id,
                "path": Path(binding[0]).relative_to(root).as_posix(),
                "sha256": str(binding[1]),
                "confidence": float(binding[2]),
            }
            for semantic_id, binding in sorted(supplied_masks.items())
        ]
    write_json_atomic(
        plan_path,
        {
            "schema_version": "0.6.0",
            "diagnostic_kind": "bounded_camera_probe",
            "job_id": job_id,
            "qa_run_id": qa_run_id,
            "diagnostic_id": diagnostic_id,
            "role_map_sha256": role_map_sha256,
            "semantic_reference_masks": semantic_reference_masks,
            "probes": [
                {
                    "probe_id": probe_id,
                    "camera_delta": delta.model_dump(mode="json"),
                }
                for probe_id, delta in probe_specs
            ],
        },
    )
    probe_records = []
    for probe_id, delta in probe_specs:
        passes = []
        for kind in ("silhouette", "object_id"):
            image_path = artifact_root / "camera_probes" / "renders" / probe_id / f"{kind}.png"
            service.save_png_atomic(
                Image.new("RGB", (8, 8), (255, 255, 255)),
                image_path,
            )
            passes.append(
                {
                    "kind": kind,
                    "path": image_path.resolve().relative_to(root.resolve()).as_posix(),
                    "sha256": sha256_file(image_path),
                }
            )
        probe_records.append(
            {
                "probe_id": probe_id,
                "camera_delta": delta.model_dump(mode="json"),
                "passes": passes,
            }
        )
    write_json_atomic(
        manifest_path,
        {
            "schema_version": "0.6.0",
            "diagnostic_kind": "bounded_camera_probe",
            "job_id": job_id,
            "qa_run_id": qa_run_id,
            "diagnostic_id": diagnostic_id,
            "probe_plan_sha256": sha256_file(plan_path),
            "role_map_sha256": role_map_sha256,
            "probes": probe_records,
        },
    )
    digest = sha256_file(manifest_path)
    scores = []
    for probe_id, overall, semantic, delta in (
        ("baseline", 0.5, 0.5, probe_specs[0][1]),
        ("yaw-positive", 0.56, 0.56, probe_specs[1][1]),
    ):
        scores.append(
            CameraProbeResult(
                probe_id=probe_id,
                is_baseline=probe_id == "baseline",
                status="scored",
                camera_delta=delta,
                overall_score=overall,
                semantic_scores=[
                    CameraProbeSemanticScore(
                        semantic_id="asset.body",
                        scorable=True,
                        score=semantic,
                    )
                ],
                evidence_path=(
                    manifest_path.resolve().relative_to(root.resolve()).as_posix()
                ),
                evidence_sha256=digest,
            )
        )
    return scores, plan_path, manifest_path


def test_visual_diagnostics_preserve_canonical_score_and_publish_exact_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Companion diagnostics remain advisory and bind every emitted source hash."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    direct_report = root / "qa" / "runs" / QA_RUN_ID / "visual_qa_report.json"
    direct_hash = sha256_file(direct_report)
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)

    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        include_multiview_sanity=False,
    )

    assert result["existing_direct_score"] == 0.5
    assert result["canonical_v06_score_unchanged"] is True
    assert sha256_file(direct_report) == direct_hash
    report = QADiagnosticReport.model_validate_json(
        Path(result["report"]).read_text(encoding="utf-8")
    )
    assert report.status == "degraded"
    assert report.semantic_metrics == []
    bundle = QADiagnosticBundleManifest.model_validate_json(
        Path(result["bundle_manifest"]).read_text(encoding="utf-8")
    )
    assert bundle.assembly_multiview.status == "not_requested"
    assert bundle.canonical_v06_score_unchanged is True

    with pytest.raises(FileExistsError, match="immutable QA diagnostic"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            include_multiview_sanity=False,
        )


def test_invalid_probe_budget_fails_before_creating_diagnostic_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject out-of-contract probe counts before allocating an attempt directory."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match=r"max_camera_probes must be within \[1, 12\]"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            diagnostic_id="invalid-probe-budget",
            max_camera_probes=13,
        )

    assert not (
        root
        / "qa"
        / "runs"
        / QA_RUN_ID
        / "diagnostics"
        / "invalid-probe-budget"
    ).exists()


def test_exact_multiview_visibility_failure_reaches_assembly_attribution(
    tmp_path: Path,
) -> None:
    """Preserve non-relation structural failures when classifying QA root cause."""

    report_path = tmp_path / "qa" / "assembly_sanity" / "runs" / "assembly-test" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    view_coverage = [
        AssemblySanityViewCoverage(
            view_id=view_id,
            visible_target_ids=["asset.body"],
            unseen_target_ids=["asset.trigger"],
            semantic_visibility_fraction=0.5,
        )
        for view_id in ("front", "right", "top", "rear", "oblique")
    ]
    report = AssemblySanityReport(
        job_id=JOB_ID,
        run_id="assembly-test",
        plan_sha256="1" * 64,
        render_manifest_sha256="2" * 64,
        scene_spec_sha256="3" * 64,
        modeling_plan_sha256="4" * 64,
        source_blend_sha256="5" * 64,
        build_fingerprint="6" * 64,
        structural_status="failed",
        reference_comparison_note="Structural-only test evidence.",
        target_ids=["asset.body", "asset.trigger"],
        visible_target_ids=["asset.body"],
        unseen_target_ids=["asset.trigger"],
        semantic_visibility_fraction=0.5,
        view_coverage=view_coverage,
        assembly_evaluation={"checks": []},
        findings=[
            AssemblySanityFinding(
                finding_id="visibility.all_views",
                category="visibility",
                severity="error",
                target_ids=["asset.trigger"],
                view_ids=["front", "right", "top", "rear", "oblique"],
                description="The trigger is absent from every structural view.",
            )
        ],
        generated_at="2026-08-03T00:00:00Z",
    )
    write_json_atomic(report_path, report.model_dump(mode="json"))
    evidence = service._assembly_evidence_from_multiview(
        tmp_path,
        {
            "status": "failed",
            "report_path": report_path.relative_to(tmp_path).as_posix(),
            "report_sha256": sha256_file(report_path),
        },
    )
    baseline = CameraProbeResult(
        probe_id="baseline",
        is_baseline=True,
        status="scored",
        camera_delta=BoundedCameraDelta(),
        overall_score=0.95,
        semantic_scores=[
            CameraProbeSemanticScore(
                semantic_id="asset.body",
                scorable=True,
                score=0.95,
            )
        ],
        evidence_path="qa/probes.json",
        evidence_sha256="7" * 64,
    )
    probe = baseline.model_copy(
        update={
            "probe_id": "yaw-positive",
            "is_baseline": False,
            "camera_delta": BoundedCameraDelta(rotation_delta_deg=(7.5, 0.0, 0.0)),
        }
    )

    attribution = attribute_camera_geometry(baseline, [probe], assembly=evidence)

    assert evidence.status == "failed"
    assert evidence.required_failure_ids == ["visibility.all_views"]
    assert attribution.classification == "assembly"
    assert attribution.assembly_failure_ids == ["visibility.all_views"]


def test_full_reference_without_semantic_masks_keeps_bbox_only_probe_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full-reference legacy run must not reuse its broad foreground as a subject mask."""

    _seed_canonical_qa(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def capture_probe_call(*args: object, **kwargs: object):
        """Capture optional mask arguments while delegating to the isolated fake probe."""

        captured.update(kwargs)
        return _fake_camera_probes(*args, **kwargs)

    monkeypatch.setattr(service, "run_bounded_camera_probes", capture_probe_call)

    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="camera-geometry-bbox-only",
        include_multiview_sanity=False,
    )

    assert result["ok"] is True
    assert captured["primary_reference_mask_path"] is None
    assert captured["primary_reference_mask_sha256"] is None
    assert captured["primary_reference_mask_source"] is None
    assert captured["max_camera_probes"] == 12
    report = QADiagnosticReport.model_validate_json(
        Path(result["report"]).read_text(encoding="utf-8")
    )
    assert any("bboxes only" in limitation for limitation in report.limitations)


def test_primary_object_scope_binds_the_exact_canonical_reference_mask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Object-only diagnostics pass their exact canonical QA mask into probe scoring."""

    root = _seed_canonical_qa(
        tmp_path,
        monkeypatch,
        reference_content_scope="primary_object_only",
    )
    captured: dict[str, object] = {}

    def capture_probe_call(*args: object, **kwargs: object):
        """Capture the exact primary mask binding before returning fake probe evidence."""

        captured.update(kwargs)
        return _fake_camera_probes(*args, **kwargs)

    monkeypatch.setattr(service, "run_bounded_camera_probes", capture_probe_call)

    service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="camera-geometry-primary-mask",
        include_multiview_sanity=False,
    )

    mask_path = root / "qa" / "runs" / QA_RUN_ID / "reference_mask.png"
    assert captured["primary_reference_mask_path"] == mask_path
    assert captured["primary_reference_mask_sha256"] == sha256_file(mask_path)
    assert (
        captured["primary_reference_mask_source"]
        == "canonical_primary_object_reference"
    )
    request = json.loads(
        (
            root
            / "qa"
            / "runs"
            / QA_RUN_ID
            / "diagnostics"
            / "camera-geometry-primary-mask"
            / "attempts"
            / "attempt-001"
            / "request.json"
        ).read_text(encoding="utf-8")
    )
    assert request["primary_reference_mask_sha256"] == sha256_file(mask_path)


def test_primary_object_scope_rejects_a_stale_canonical_reference_mask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed object-only QA mask blocks companion evidence before camera rendering."""

    root = _seed_canonical_qa(
        tmp_path,
        monkeypatch,
        reference_content_scope="primary_object_only",
    )
    mask_path = root / "qa" / "runs" / QA_RUN_ID / "reference_mask.png"
    mask_path.write_bytes(b"tampered reference mask")
    called = False

    def unexpected_probe(*_args: object, **_kwargs: object):
        """Record an unsafe renderer call that must never occur for stale evidence."""

        nonlocal called
        called = True
        raise AssertionError("camera probe must not run")

    monkeypatch.setattr(service, "run_bounded_camera_probes", unexpected_probe)

    with pytest.raises(ValueError, match="reference mask hash changed"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            diagnostic_id="camera-geometry-stale-primary",
            include_multiview_sanity=False,
        )
    assert called is False


def test_full_reference_uses_only_an_explicit_semantic_subject_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full-scene diagnostics may use a hash-bound union of explicit subject masks."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    scene_path = root / "analysis" / "scene_spec.json"
    source_mask = root / "analysis" / "masks" / "asset.body.png"
    _write_image(source_mask)
    manifest = SemanticReferenceMaskManifest(
        job_id=JOB_ID,
        reference_path="input/reference.png",
        reference_sha256=sha256_file(root / "input" / "reference.png"),
        scene_spec_sha256=sha256_file(scene_path),
        masks=[
            SemanticReferenceMaskRecord(
                semantic_id="asset.body",
                source_id="reference",
                path="analysis/masks/asset.body.png",
                sha256=sha256_file(source_mask),
                confidence=0.95,
            )
        ],
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    write_json_atomic(
        root / "analysis" / "masks" / "semantic_manifest.json",
        manifest.model_dump(mode="json"),
    )
    captured: dict[str, object] = {}

    def capture_probe_call(*args: object, **kwargs: object):
        """Capture the explicit union binding while delegating probe evidence creation."""

        captured.update(kwargs)
        return _fake_camera_probes(*args, **kwargs)

    monkeypatch.setattr(service, "run_bounded_camera_probes", capture_probe_call)

    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="camera-geometry-semantic-union",
        include_multiview_sanity=False,
    )

    union_path = Path(str(captured["primary_reference_mask_path"]))
    assert captured["primary_reference_mask_source"] == "semantic_primary_supporting_union"
    assert union_path.is_file()
    assert captured["primary_reference_mask_sha256"] == sha256_file(union_path)
    report = QADiagnosticReport.model_validate_json(
        Path(result["report"]).read_text(encoding="utf-8")
    )
    assert [metric.semantic_id for metric in report.semantic_metrics] == ["asset.body"]
    request = json.loads(
        Path(result["request"]).read_text(encoding="utf-8")
    )
    assert request["semantic_reference_manifest_path"].startswith(
        f"qa/runs/{QA_RUN_ID}/diagnostics/camera-geometry-semantic-union/"
    )
    probe_masks = captured["semantic_reference_masks"]
    assert isinstance(probe_masks, dict)
    assert Path(probe_masks["asset.body"][0]).is_relative_to(root)


def test_later_semantic_registration_does_not_stale_attempt_owned_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a completed diagnostic current after the mutable canonical mask pointer moves."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    scene_path = root / "analysis" / "scene_spec.json"
    source_mask = root / "analysis" / "masks" / "asset.body.png"
    _write_image(source_mask)
    manifest = SemanticReferenceMaskManifest(
        job_id=JOB_ID,
        reference_path="input/reference.png",
        reference_sha256=sha256_file(root / "input" / "reference.png"),
        scene_spec_sha256=sha256_file(scene_path),
        masks=[
            SemanticReferenceMaskRecord(
                semantic_id="asset.body",
                source_id="reference",
                path="analysis/masks/asset.body.png",
                sha256=sha256_file(source_mask),
                confidence=0.95,
            )
        ],
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    canonical_manifest = root / "analysis" / "masks" / "semantic_manifest.json"
    write_json_atomic(canonical_manifest, manifest.model_dump(mode="json"))
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)
    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="semantic-snapshot-stability",
        include_multiview_sanity=False,
    )
    bundle_path = Path(result["bundle_manifest"])

    canonical_manifest.write_text('{"superseded":true}\n', encoding="utf-8")
    source_mask.write_bytes(b"superseded mutable source mask")

    bundle, _request, _report = service.validate_qa_diagnostic_bundle(
        root,
        bundle_path,
    )
    assert bundle.diagnostic_id == "semantic-snapshot-stability"

    request_payload = json.loads(Path(result["request"]).read_text(encoding="utf-8"))
    snapshot = root / request_payload["semantic_reference_manifest_path"]
    snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="semantic-mask manifest"):
        service.validate_qa_diagnostic_bundle(root, bundle_path)


def test_legacy_scene_without_explicit_qa_tags_uses_the_same_role_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use deterministic fallback roles consistently for probe, union, and report IDs."""

    root = _seed_canonical_qa(
        tmp_path,
        monkeypatch,
        explicit_qa_role=False,
    )
    scene_path = root / "analysis" / "scene_spec.json"
    source_mask = root / "analysis" / "masks" / "asset.body.png"
    _write_image(source_mask)
    manifest = SemanticReferenceMaskManifest(
        job_id=JOB_ID,
        reference_path="input/reference.png",
        reference_sha256=sha256_file(root / "input" / "reference.png"),
        scene_spec_sha256=sha256_file(scene_path),
        masks=[
            SemanticReferenceMaskRecord(
                semantic_id="asset.body",
                source_id="reference",
                path="analysis/masks/asset.body.png",
                sha256=sha256_file(source_mask),
                confidence=0.95,
            )
        ],
        generated_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    write_json_atomic(
        root / "analysis" / "masks" / "semantic_manifest.json",
        manifest.model_dump(mode="json"),
    )
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)

    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="legacy-role-fallback",
        include_multiview_sanity=False,
    )

    request = QADiagnosticRequest.model_validate_json(
        Path(result["request"]).read_text(encoding="utf-8")
    )
    report = QADiagnosticReport.model_validate_json(
        Path(result["report"]).read_text(encoding="utf-8")
    )
    role_map = BackgroundRoleMap.model_validate_json(
        (
            Path(result["request"]).parent / "role_map.json"
        ).read_text(encoding="utf-8")
    )
    assignment = next(item for item in role_map.assignments if item.object_id == "asset.body")
    assert assignment.role == "primary"
    assert assignment.source == "semantic_rule"
    assert [item.semantic_id for item in request.semantic_masks] == ["asset.body"]
    assert [item.semantic_id for item in report.semantic_metrics] == ["asset.body"]


def test_live_diagnostic_publication_lease_rejects_a_concurrent_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a second standalone diagnostic writer before allocating an attempt."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    diagnostic_root = (
        root / "qa" / "runs" / QA_RUN_ID / "diagnostics" / "concurrent-diagnostic"
    )
    with service.artifact_publication_lease(
        diagnostic_root,
        owner_kind="test_writer",
        owner_id="first",
    ):
        with pytest.raises(RuntimeError, match="Another live writer"):
            service.run_job_visual_diagnostics(
                JOB_ID,
                QA_RUN_ID,
                diagnostic_id="concurrent-diagnostic",
                include_multiview_sanity=False,
            )
    assert not (diagnostic_root / "attempts").exists()


def test_visual_diagnostics_reject_stale_canonical_scene(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SceneSpec change after canonical QA blocks a new companion diagnostic."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    scene_path = root / "analysis" / "scene_spec.json"
    payload = json.loads(scene_path.read_text(encoding="utf-8"))
    payload["nominal_scene_size"] = [5.0, 2.0, 2.0]
    scene_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)

    with pytest.raises(ValueError, match="SceneSpec hash changed"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            diagnostic_id="camera-geometry-v2",
            include_multiview_sanity=False,
        )


def test_visual_diagnostics_recheck_sources_before_terminal_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent canonical drift after probes blocks terminal companion publication."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)

    def mutate_during_multiview(*_args: object, **_kwargs: object) -> dict[str, str]:
        """Simulate a concurrent writer after diagnostic report construction."""

        scene_path = root / "analysis" / "scene_spec.json"
        scene_path.write_text(scene_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return {"status": "not_requested"}

    monkeypatch.setattr(
        service,
        "_run_optional_assembly_multiview",
        mutate_during_multiview,
    )

    with pytest.raises(ValueError, match="SceneSpec hash changed"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            diagnostic_id="camera-geometry-race",
            include_multiview_sanity=True,
        )
    assert not (
        root
        / "qa"
        / "runs"
        / QA_RUN_ID
        / "diagnostics"
        / "camera-geometry-race"
        / "bundle_manifest.json"
    ).exists()


def test_visual_diagnostics_rejects_role_map_drift_before_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed camera-role map cannot survive terminal bundle publication."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)

    def mutate_role_map(*_args: object, **_kwargs: object) -> dict[str, str]:
        """Simulate an unexpected writer changing semantic role ownership."""

        role_map = (
            root
            / "qa"
            / "runs"
            / QA_RUN_ID
            / "diagnostics"
            / "camera-geometry-role-map-race"
            / "attempts"
            / "attempt-001"
            / "role_map.json"
        )
        role_map.write_text(role_map.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        return {"status": "not_requested"}

    monkeypatch.setattr(
        service,
        "_run_optional_assembly_multiview",
        mutate_role_map,
    )

    with pytest.raises(RuntimeError, match="camera role map changed"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            diagnostic_id="camera-geometry-role-map-race",
            include_multiview_sanity=True,
        )


def test_visual_diagnostics_rejects_any_changed_canonical_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-beauty pass mutation must fail before advisory Blender probes run."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    (root / "qa" / "runs" / QA_RUN_ID / "passes" / "wireframe.png").write_bytes(
        b"tampered wireframe"
    )
    called = False

    def unexpected_probe(*_args: object, **_kwargs: object):
        """Record a probe invocation that stale seven-pass evidence must prevent."""

        nonlocal called
        called = True
        raise AssertionError("camera probe must not run")

    monkeypatch.setattr(service, "run_bounded_camera_probes", unexpected_probe)

    with pytest.raises(ValueError, match="render pass hash changed: wireframe"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            diagnostic_id="camera-geometry-stale-pass",
            include_multiview_sanity=False,
        )
    assert called is False


def test_visual_diagnostics_retry_uses_a_new_immutable_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit same-step retry preserves failure evidence and can publish once."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)

    def fail_after_attempt_creation(
        _root: Path,
        *,
        artifact_root: Path,
        **_kwargs: object,
    ) -> tuple[list[CameraProbeResult], Path, Path]:
        """Leave one immutable failure note after the service allocates an attempt."""

        write_json_atomic(artifact_root / "failure.json", {"error": "synthetic"})
        raise RuntimeError("synthetic Blender failure")

    monkeypatch.setattr(
        service,
        "run_bounded_camera_probes",
        fail_after_attempt_creation,
    )
    with pytest.raises(RuntimeError, match="synthetic Blender failure"):
        service.run_job_visual_diagnostics(
            JOB_ID,
            QA_RUN_ID,
            diagnostic_id="camera-geometry-retry",
            include_multiview_sanity=False,
        )

    diagnostic_root = (
        root
        / "qa"
        / "runs"
        / QA_RUN_ID
        / "diagnostics"
        / "camera-geometry-retry"
    )
    first_failure = diagnostic_root / "attempts" / "attempt-001" / "failure.json"
    first_failure_hash = sha256_file(first_failure)
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)

    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="camera-geometry-retry",
        include_multiview_sanity=False,
    )

    assert result["ok"] is True
    assert sha256_file(first_failure) == first_failure_hash
    assert (diagnostic_root / "attempts" / "attempt-002" / "request.json").is_file()
    assert (diagnostic_root / "bundle_manifest.json").is_file()


def test_terminal_bundle_rechecks_canonical_passes_and_role_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detect post-publication changes in nested canonical and role evidence."""

    root = _seed_canonical_qa(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)
    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="camera-geometry-terminal-validation",
        include_multiview_sanity=False,
    )
    bundle_path = Path(result["bundle_manifest"])
    service.validate_qa_diagnostic_bundle(root, bundle_path)

    wireframe = root / "qa" / "runs" / QA_RUN_ID / "passes" / "wireframe.png"
    wireframe.write_bytes(b"post-publication canonical tamper")
    with pytest.raises(ValueError, match="render pass hash changed: wireframe"):
        service.validate_qa_diagnostic_bundle(root, bundle_path)

    root = _seed_canonical_qa(tmp_path / "role", monkeypatch)
    monkeypatch.setattr(service, "run_bounded_camera_probes", _fake_camera_probes)
    result = service.run_job_visual_diagnostics(
        JOB_ID,
        QA_RUN_ID,
        diagnostic_id="camera-geometry-terminal-role",
        include_multiview_sanity=False,
    )
    bundle_path = Path(result["bundle_manifest"])
    role_map = (
        bundle_path.parent
        / "attempts"
        / "attempt-001"
        / "role_map.json"
    )
    role_map.write_text(role_map.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="camera role map"):
        service.validate_qa_diagnostic_bundle(root, bundle_path)


def test_semantic_mask_names_are_short_collision_resistant_and_long_path_safe(
    tmp_path: Path,
) -> None:
    """Preserve distinct semantic IDs and save evidence beyond legacy MAX_PATH."""

    assert service._semantic_mask_filename("asset:part") != service._semantic_mask_filename(
        "asset_part"
    )
    assert len(service._semantic_mask_filename("x" * 192)) <= 65
    source = tmp_path / "source.png"
    Image.new("L", (8, 8), 255).save(source)
    destination = (
        tmp_path
        / ("q" * 80)
        / ("d" * 80)
        / ("a" * 80)
        / "semantic-mask.png"
    )
    assert len(str(destination.resolve())) > 260
    service._aligned_reference_mask(source, destination, (8, 8))
    with service.open_image(destination) as saved:
        assert saved.size == (8, 8)
    with service.open_image(destination) as opened:
        assert opened.size == (8, 8)
