from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from PIL import Image
from pypdf import PdfReader

from codex_blender_modeler.reporting import (
    collect_job_report_payload,
    generate_job_pdf_report,
)
from codex_blender_modeler.workspace import sha256_file


def _write_json(path: Path, payload: dict) -> None:
    """Write one compact UTF-8 JSON fixture for the reporting tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    """Write one deterministic RGB image used as reference or report evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (96, 64), color).save(path)


def _seed_material_report_job(tmp_path: Path, monkeypatch) -> Path:
    """Create one isolated job with canonical material reports and a safe swatch image."""

    workspace = tmp_path / "workspaces"
    root = workspace / "pdf_report_test"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    reference = root / "input" / "reference.png"
    preview = root / "renders" / "preview.png"
    swatch = root / "renders" / "materials" / "mat.stone" / "swatch.png"
    _write_png(reference, (80, 130, 180))
    _write_png(preview, (90, 140, 90))
    _write_png(swatch, (110, 105, 95))
    _write_json(
        root / "job.json",
        {
            "job_id": "pdf_report_test",
            "mode": "concept",
            "project_version_created": "0.6.0",
            "reference_path": str(reference),
        },
    )
    _write_json(
        root / "analysis" / "scene_spec.json",
        {
            "schema_version": "0.2.0",
            "job_id": "pdf_report_test",
            "objects": [],
            "materials": [{"id": "mat.stone"}],
        },
    )
    _write_json(
        root / "analysis" / "material_plan.json",
        {
            "schema_version": "0.5.0",
            "job_id": "pdf_report_test",
            "materials": [
                {
                    "material_id": "mat.stone",
                    "shader_family": "rock",
                    "texture_strategy": "procedural",
                    "mapping": {"mode": "object"},
                }
            ],
        },
    )
    _write_json(
        root / "reports" / "material_contract_validation.json",
        {"ok": True, "passed": 3, "warnings": 0, "failed": 0},
    )
    _write_json(
        root / "reports" / "material_validation.json",
        {
            "ok": True,
            "summary": {"material_count": 1},
            "errors": [],
            "warnings": [],
            "materials": [
                {
                    "material_id": "mat.stone",
                    "source_type": "procedural",
                    "users": 1,
                    "node_count": 6,
                    "images": [],
                    "warnings": [],
                }
            ],
        },
    )
    _write_json(
        root / "reports" / "material_swatches.json",
        {
            "schema_version": "0.5.0",
            "job_id": "pdf_report_test",
            "material_count": 1,
            "swatches": [
                {
                    "material_id": "mat.stone",
                    "path": str(swatch),
                    "sha256": sha256_file(swatch),
                    "width": 96,
                    "height": 64,
                    "encoding": "png-rgb8",
                }
            ],
        },
    )
    return root


def _canonical_hashes(root: Path) -> dict[str, str]:
    """Hash every canonical fixture file so PDF generation can prove read-only behavior."""

    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_material_pdf_is_human_readable_hashed_and_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Generate a material PDF with safe provenance without mutating canonical job files."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    before = _canonical_hashes(root)

    result = generate_job_pdf_report("pdf_report_test", scope="material")

    pdf_path = Path(result["pdf"])
    manifest_path = Path(result["manifest"])
    assert pdf_path == tmp_path / "output" / "pdf" / "pdf_report_test" / "material_report.pdf"
    assert pdf_path.is_file()
    assert manifest_path.is_file()
    assert _canonical_hashes(root) == before
    assert sha256_file(pdf_path) == result["pdf_sha256"]

    reader = PdfReader(pdf_path)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) >= 2
    assert "pdf_report_test" in extracted

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "schemas"
            / "human_report_manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema, format_checker=None).validate(manifest)
    assert manifest["source_fingerprint"] == result["source_fingerprint"]
    assert manifest["pdf_sha256"] == result["pdf_sha256"]
    assert all(not Path(source["path"]).is_absolute() for source in manifest["sources"])
    assert all(str(tmp_path) not in source["path"] for source in manifest["sources"])
    repeated = collect_job_report_payload("pdf_report_test", "material")
    assert repeated["source_fingerprint"] == result["source_fingerprint"]


def test_external_report_image_is_skipped_without_path_disclosure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject report images outside the job while retaining a useful warning and PDF."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    outside = tmp_path / "external-swatch.png"
    _write_png(outside, (255, 0, 0))
    manifest_path = root / "reports" / "material_swatches.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["swatches"][0]["path"] = str(outside)
    _write_json(manifest_path, manifest)

    payload = collect_job_report_payload("pdf_report_test", "material")

    assert payload["images"]["material_swatches"] == []
    assert any("Skipped an external report asset" in item for item in payload["warnings"])
    assert all(str(outside) not in source.path for source in payload["sources"])


def test_stale_swatch_is_excluded_from_human_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Exclude changed visual evidence instead of presenting it under an obsolete hash."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    swatch = root / "renders" / "materials" / "mat.stone" / "swatch.png"
    _write_png(swatch, (0, 0, 0))

    payload = collect_job_report_payload("pdf_report_test", "material")

    assert payload["images"]["material_swatches"] == []
    assert any("Skipped stale report evidence" in item for item in payload["warnings"])


def test_pdf_report_rejects_unknown_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject presentation scopes outside the four public reporting contracts."""

    _seed_material_report_job(tmp_path, monkeypatch)
    try:
        collect_job_report_payload("pdf_report_test", "unknown")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "scope must be one of" in str(exc)
    else:
        raise AssertionError("Unknown report scope was accepted")


def test_applied_qa_pdf_includes_revision_and_convergence_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Render accepted revision evidence instead of reporting only pre-apply candidates."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = "run-applied"
    run_dir = root / "qa" / "runs" / run_id
    beauty_path = run_dir / "passes" / "beauty.png"
    _write_png(beauty_path, (45, 65, 85))
    _write_json(
        run_dir / "render_pass_manifest.json",
        {
            "passes": [
                {
                    "kind": "beauty",
                    "path": "passes/beauty.png",
                    "sha256": sha256_file(beauty_path),
                }
            ]
        },
    )
    _write_json(
        run_dir / "visual_qa_report.json",
        {
            "direct_metrics": {
                "overall_direct_score": 0.6,
                "silhouette_iou": 0.5,
                "global_bbox": {
                    "center_error_norm": 0.1,
                    "size_error_norm": 0.2,
                },
            },
            "findings": [
                {
                    "id": "direct.position.asset.body",
                    "severity": "medium",
                    "issue_type": "position",
                    "target_ids": ["asset.body"],
                    "description": "Direct fixture mismatch.",
                    "evidence_sources": ["direct_reference"],
                    "confidence": 0.9,
                },
                {
                    "id": "advisory.color.asset.body",
                    "severity": "low",
                    "issue_type": "color_block",
                    "target_ids": ["asset.body"],
                    "description": "Generated target advisory only.",
                    "evidence_sources": ["generated_target"],
                    "confidence": 0.25,
                },
                {
                    "id": "direct.group_position.asset.main",
                    "severity": "medium",
                    "issue_type": "position",
                    "target_ids": ["asset.body", "asset.detail"],
                    "description": "Coherent group candidate bundle.",
                    "evidence_sources": ["direct_reference"],
                    "confidence": 0.8,
                },
            ],
        },
    )
    _write_json(
        run_dir / "revision_candidates.json",
        {
            "candidates": [
                {"id": "c1", "finding_id": "direct.position.asset.body"},
                {
                    "id": "group-body",
                    "finding_id": "direct.group_position.asset.main",
                },
                {
                    "id": "group-detail",
                    "finding_id": "direct.group_position.asset.main",
                },
            ]
        },
    )
    _write_json(run_dir / "revision_plan.json", {"operations": [{"candidate_id": "c1"}]})
    _write_json(run_dir / "revision_approval.json", {"used": True})
    _write_json(
        run_dir / "application_report.json",
        {
            "status": "accepted",
            "approved_candidate_ids": ["c1"],
            "changes": [
                {
                    "target_id": "asset.body",
                    "path": ["transform", "location"],
                    "before": [0, 0, 0],
                    "after": [1, 0, 0],
                }
            ],
        },
    )
    _write_json(
        run_dir / "convergence.json",
        {
            "before_direct_score": 0.6,
            "after_direct_score": 0.7,
            "score_delta": 0.1,
            "status": "improved",
            "reasons": ["Direct-reference score improved."],
        },
    )

    payload = collect_job_report_payload("pdf_report_test", "qa", qa_run_id=run_id)
    assert "revision_application" in payload["documents"]
    assert "convergence" in payload["documents"]
    assert any(source.kind == "revision_application" for source in payload["sources"])
    result = generate_job_pdf_report("pdf_report_test", scope="qa", qa_run_id=run_id)
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )
    assert "0.7" in extracted
    assert "asset.body" in extracted
    assert "직접 QA 발견: 1개" in extracted
    assert "생성 타깃 보조 발견: 1개" in extracted
    assert "일관 그룹 이동 제안: 1개 묶음" in extracted
    assert "Direct fixture mismatch." in extracted
    assert "Generated target advisory only." in extracted
    assert "Coherent group candidate bundle." in extracted
    assert "일반 후보: 1개" in extracted
    assert "그룹 이동 묶음: 1개" in extracted
    assert "그룹 member 연산: 2개" in extracted
    assert "수정 결과" in extracted
    assert "승인 전 QA beauty" in extracted
    assert "QA beauty는 승인 수정 전 기준선" in extracted


def test_unapproved_qa_pdf_labels_plan_and_beauty_as_pre_apply(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Mark an unapproved RevisionPlan and its QA beauty as pre-application evidence."""

    root = _seed_material_report_job(tmp_path, monkeypatch)
    run_id = "run-unapproved"
    run_dir = root / "qa" / "runs" / run_id
    beauty_path = run_dir / "passes" / "beauty.png"
    _write_png(beauty_path, (55, 75, 95))
    _write_json(
        run_dir / "render_pass_manifest.json",
        {
            "passes": [
                {
                    "kind": "beauty",
                    "path": "passes/beauty.png",
                    "sha256": sha256_file(beauty_path),
                }
            ]
        },
    )
    _write_json(
        run_dir / "visual_qa_report.json",
        {
            "direct_metrics": {
                "overall_direct_score": 0.5,
                "silhouette_iou": 0.4,
                "global_bbox": {
                    "center_error_norm": 0.1,
                    "size_error_norm": 0.2,
                },
            },
            "findings": [],
        },
    )
    _write_json(run_dir / "revision_candidates.json", {"candidates": []})
    _write_json(run_dir / "revision_plan.json", {"operations": []})

    result = generate_job_pdf_report("pdf_report_test", scope="qa", qa_run_id=run_id)
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(result["pdf"]).pages
    )

    assert "수정 계획" in extracted
    assert "승인 대기" in extracted
    assert "현재 QA 기준 프리뷰 (후보 적용 전)" in extracted
    assert "아직 적용되지 않았습니다" in extracted
