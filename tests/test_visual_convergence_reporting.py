from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader

import codex_blender_modeler.auto_revision.convergence_reporting as reporting
from codex_blender_modeler.auto_revision.convergence_reporting import (
    generate_visual_convergence_pdf_report,
)
from codex_blender_modeler.workspace import sha256_file


def _write_json(path: Path, payload: dict) -> None:
    """Write one deterministic UTF-8 JSON fixture for convergence-report tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _seed_session(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    """Create one isolated final convergence report and exact QA evidence source."""

    workspace = tmp_path / "workspaces"
    root = workspace / "convergence_report_test"
    monkeypatch.setenv("CBM_WORKSPACE_ROOT", str(workspace))
    session_root = root / "qa" / "convergence" / "session-01"
    report_path = session_root / "convergence_report.json"
    qa_report_path = session_root / "iterations" / "001" / "iteration.json"
    selection_path = session_root / "iterations" / "001" / "selection.json"
    _write_json(
        qa_report_path,
        {
            "schema_version": "0.6.0",
            "job_id": "convergence_report_test",
            "session_id": "session-01",
            "iteration_index": 1,
            "status": "accepted",
            "before_direct_score": 0.71,
            "after_direct_score": 0.82,
            "score_delta": 0.11,
            "changed_ids": ["asset.primary"],
        },
    )
    _write_json(
        selection_path,
        {
            "schema_version": "0.6.0",
            "job_id": "convergence_report_test",
            "session_id": "session-01",
            "iteration_index": 1,
            "selected_candidate_ids": ["candidate.primary.scale"],
        },
    )
    receipt_hash = sha256_file(qa_report_path)
    selection_hash = sha256_file(selection_path)
    stable_hash = "a" * 64
    _write_json(
        report_path,
        {
            "schema_version": "0.6.0",
            "job_id": "convergence_report_test",
            "session_id": "session-01",
            "plan_sha256": stable_hash,
            "approval_sha256": stable_hash,
            "input_fingerprint": stable_hash,
            "camera_fingerprint": stable_hash,
            "scoring_version": "semantic_bbox_v2",
            "initial_scene_spec_sha256": stable_hash,
            "final_scene_spec_sha256": stable_hash,
            "initial_qa_report_sha256": stable_hash,
            "final_qa_report_sha256": stable_hash,
            "target_reached": True,
            "manual_review_required": False,
            "initial_direct_score": 0.71,
            "final_direct_score": 0.82,
            "target_direct_score": 0.8,
            "initial_silhouette_iou": 0.72,
            "final_silhouette_iou": 0.84,
            "target_silhouette_iou": 0.8,
            "iteration_receipts": [
                {
                    "relative_path": (
                        "qa/convergence/session-01/iterations/001/iteration.json"
                    ),
                    "sha256": receipt_hash,
                },
            ],
            "iteration_evidence": [
                {
                    "relative_path": (
                        "qa/convergence/session-01/iterations/001/iteration.json"
                    ),
                    "sha256": receipt_hash,
                },
                {
                    "relative_path": (
                        "qa/convergence/session-01/iterations/001/selection.json"
                    ),
                    "sha256": selection_hash,
                },
            ],
            "accepted_iterations": 1,
            "rolled_back_iterations": 0,
            "termination_reason": "target_reached",
            "remaining_high_finding_ids": [],
            "reasons": ["The approved target score was reached."],
            "started_at": "2026-07-30T00:00:00+00:00",
            "completed_at": "2026-07-30T00:10:00+00:00",
        },
    )
    return root, report_path, qa_report_path


def _source_hashes(paths: list[Path]) -> dict[str, str]:
    """Capture exact source hashes to prove that PDF generation is read-only."""

    return {str(path): sha256_file(path) for path in paths}


def test_convergence_pdf_is_hash_bound_job_relative_and_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Generate a Korean-capable PDF and sidecar without changing machine evidence."""

    root, report_path, qa_report_path = _seed_session(tmp_path, monkeypatch)
    before = _source_hashes([report_path, qa_report_path])

    result = generate_visual_convergence_pdf_report(
        "convergence_report_test",
        "session-01",
    )

    output = Path(result["pdf"])
    manifest_path = Path(result["manifest"])
    assert output == root / "qa" / "convergence" / "session-01" / "convergence_report.pdf"
    assert manifest_path == output.with_suffix(".manifest.json")
    assert output.is_file()
    assert manifest_path.is_file()
    assert _source_hashes([report_path, qa_report_path]) == before
    assert result["pdf_sha256"] == sha256_file(output)

    reader = PdfReader(output)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "convergence_report_test" in extracted
    assert "session-01" in extracted
    assert "0.82" in extracted
    assert "accepted" in extracted
    assert "asset.primary" in extracted

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["pdf"]["relative_path"] == (
        "qa/convergence/session-01/convergence_report.pdf"
    )
    assert manifest["report_json"]["relative_path"] == (
        "qa/convergence/session-01/convergence_report.json"
    )
    assert manifest["pdf"]["sha256"] == sha256_file(output)
    assert manifest["source_fingerprint"] == result["source_fingerprint"]
    assert manifest["sources"][0]["sha256"] == sha256_file(report_path)
    assert manifest["sources"][1]["sha256"] == sha256_file(qa_report_path)
    assert manifest["sources"][2]["relative_path"].endswith("selection.json")
    assert all(
        not Path(item["relative_path"]).is_absolute() for item in manifest["sources"]
    )
    assert all(
        str(tmp_path) not in item["relative_path"] for item in manifest["sources"]
    )


def test_convergence_pdf_surfaces_remaining_high_findings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Show unresolved high finding IDs instead of hiding them in canonical JSON."""

    _, report_path, _ = _seed_session(tmp_path, monkeypatch)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["target_reached"] = False
    payload["manual_review_required"] = True
    payload["final_direct_score"] = 0.76
    payload["final_silhouette_iou"] = 0.74
    payload["termination_reason"] = "plateau"
    payload["remaining_high_finding_ids"] = [
        "finding.primary.silhouette",
        "finding.supporting.proportion",
    ]
    payload["reasons"] = ["The approved session stopped on a plateau."]
    _write_json(report_path, payload)

    result = generate_visual_convergence_pdf_report(
        "convergence_report_test",
        "session-01",
    )

    reader = PdfReader(Path(result["pdf"]))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "finding.primary.silhouette" in extracted
    assert "finding.supporting.proportion" in extracted


@pytest.mark.parametrize(
    "source_path",
    [
        "../outside.json",
        r"C:\outside\evidence.json",
        "/tmp/outside.json",
    ],
)
def test_convergence_pdf_rejects_escaping_or_absolute_sources(
    tmp_path: Path,
    monkeypatch,
    source_path: str,
) -> None:
    """Reject source metadata that could disclose or read outside the selected job."""

    root, _, _ = _seed_session(tmp_path, monkeypatch)

    with pytest.raises(ValueError):
        generate_visual_convergence_pdf_report(
            "convergence_report_test",
            "session-01",
            source_relative_paths=[source_path],
        )

    session_root = root / "qa" / "convergence" / "session-01"
    assert not (session_root / "convergence_report.pdf").exists()
    assert not (session_root / "convergence_report.manifest.json").exists()


def test_convergence_pdf_fails_closed_when_source_changes_during_render(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Discard derived output when exact evidence changes during PDF rendering."""

    root, _, qa_report_path = _seed_session(tmp_path, monkeypatch)
    original_renderer = reporting._render_convergence_pdf

    def mutating_renderer(*args, **kwargs):
        """Render the PDF and then simulate an unplanned source mutation."""

        result = original_renderer(*args, **kwargs)
        _write_json(qa_report_path, {"tampered": True})
        return result

    monkeypatch.setattr(reporting, "_render_convergence_pdf", mutating_renderer)

    with pytest.raises(RuntimeError, match="changed during rendering"):
        generate_visual_convergence_pdf_report(
            "convergence_report_test",
            "session-01",
        )

    session_root = root / "qa" / "convergence" / "session-01"
    assert not (session_root / "convergence_report.pdf").exists()
    assert not (session_root / "convergence_report.manifest.json").exists()


def test_convergence_pdf_refuses_to_overwrite_existing_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Preserve immutable session reporting by rejecting a second generation attempt."""

    _seed_session(tmp_path, monkeypatch)
    generate_visual_convergence_pdf_report(
        "convergence_report_test",
        "session-01",
    )

    with pytest.raises(FileExistsError):
        generate_visual_convergence_pdf_report(
            "convergence_report_test",
            "session-01",
        )


def test_convergence_machine_report_must_match_selected_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Reject a machine report whose embedded session identity does not match."""

    _, report_path, _ = _seed_session(tmp_path, monkeypatch)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["session_id"] = "different-session"
    _write_json(report_path, payload)

    with pytest.raises(ValueError, match="different session"):
        generate_visual_convergence_pdf_report(
            "convergence_report_test",
            "session-01",
        )
